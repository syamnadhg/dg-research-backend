"""Bridge /device routes (owned flag, selection) + /research device resolution."""

import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge
from facade.firestore_rest import FirestoreError


class FakeFS:
    devices: list[dict] = []
    last_enqueue = None
    last_upsert = None
    enqueue_raises = False
    deleted: list[str] = []
    researches: dict = {}
    last_cancel = None
    last_pc_patch = None
    get_raises = False
    seeded = None

    def __init__(self, _token_provider):
        pass

    def get_research(self, uid, rid):
        if FakeFS.get_raises:
            raise FirestoreError(
                "GET /users/u1/researches/r1 -> HTTP 500: SECRET-UPSTREAM-BODY"
            )
        doc = FakeFS.researches.get(rid)
        return dict(doc) if doc else None

    def enqueue_cancel(self, device_id, *, uid, research_id):
        FakeFS.last_cancel = {"device_id": device_id, "uid": uid, "research_id": research_id}
        return "C-1"

    def list_researches(self, uid, *, page_size=50):
        return [dict(d) for d in FakeFS.researches.values()]

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]

    def upsert_research(self, uid, rid, fields):
        FakeFS.last_upsert = {"uid": uid, "rid": rid, "fields": fields}

    def enqueue_start(self, device_id, **kw):
        if FakeFS.enqueue_raises:
            raise FirestoreError("enqueue denied")
        FakeFS.last_enqueue = {"device_id": device_id, **kw}
        return "Q-1"

    def seed_chat_messages(self, uid, rid, *, topic, title):
        FakeFS.seeded = {"uid": uid, "rid": rid, "topic": topic, "title": title}

    def delete_research(self, uid, rid):
        FakeFS.deleted.append(rid)

    def patch_pipeline_config(self, uid, rid, pc_updates):
        FakeFS.last_pc_patch = {"rid": rid, "updates": pc_updates}


@pytest.fixture()
def live(monkeypatch):
    FakeFS.devices = []
    FakeFS.last_enqueue = None
    FakeFS.last_upsert = None
    FakeFS.enqueue_raises = False
    FakeFS.deleted = []
    FakeFS.researches = {}
    FakeFS.last_cancel = None
    FakeFS.last_pc_patch = None
    FakeFS.get_raises = False
    FakeFS.seeded = None
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)

    # In-memory device selection (don't touch the real ~/.super-agent/prefs.json).
    # The uid arg is accepted to match the real (uid-bound) signature; this mock
    # doesn't enforce uid-binding — that contract is covered in test_prefs.
    sel = {"v": None}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device", lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: sel.__setitem__("v", None))

    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", sel
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_devices_owned_flag(live):
    base, _ = live
    FakeFS.devices = [
        {"id": "own", "name": "My PC", "ownerUid": "u1"},
        {"id": "shr", "name": "Friend PC", "ownerUid": "u2", "sharedWith": ["u1"]},
    ]
    body = requests.get(base + "/devices").json()
    by_id = {d["id"]: d for d in body["devices"]}
    assert by_id["own"]["owned"] is True
    assert by_id["shr"]["owned"] is False
    assert body["selectedDeviceId"] is None


def test_select_persists_and_marks_selected(live):
    base, sel = live
    FakeFS.devices = [{"id": "own", "name": "My PC", "ownerUid": "u1"}]
    r = requests.post(base + "/device/select", json={"deviceId": "own"})
    assert r.status_code == 200 and r.json()["device"]["owned"] is True
    assert sel["v"] == "own"
    # now /devices marks it selected
    devs = requests.get(base + "/devices").json()
    assert devs["selectedDeviceId"] == "own"
    assert devs["devices"][0]["selected"] is True


def test_select_unknown_device_404(live):
    base, sel = live
    FakeFS.devices = [{"id": "own", "ownerUid": "u1"}]
    r = requests.post(base + "/device/select", json={"deviceId": "ghost"})
    assert r.status_code == 404 and sel["v"] is None


def test_select_requires_device_id(live):
    base, _ = live
    assert requests.post(base + "/device/select", json={}).status_code == 400


def test_device_current_none_when_unselected(live):
    base, _ = live
    FakeFS.devices = [{"id": "own", "ownerUid": "u1"}]
    r = requests.get(base + "/device").json()
    assert r["device"] is None and r["selectedDeviceId"] is None


def test_device_current_reports_stale_selection(live):
    base, sel = live
    sel["v"] = "gone"  # selected a device no longer reachable
    FakeFS.devices = [{"id": "own", "ownerUid": "u1"}]
    r = requests.get(base + "/device").json()
    assert r["device"] is None and r["selectedDeviceId"] == "gone" and r["stale"] is True


def test_research_uses_explicit_device(live):
    base, _ = live
    FakeFS.devices = [{"id": "a", "ownerUid": "u1"}, {"id": "b", "ownerUid": "u1"}]
    r = requests.post(base + "/research", json={"topic": "T", "deviceId": "b"})
    assert r.status_code == 200
    assert FakeFS.last_enqueue["device_id"] == "b"


def test_research_falls_back_to_selection(live):
    base, sel = live
    sel["v"] = "a"
    FakeFS.devices = [{"id": "a", "ownerUid": "u1"}, {"id": "b", "ownerUid": "u1"}]
    r = requests.post(base + "/research", json={"topic": "T"})
    assert r.status_code == 200 and FakeFS.last_enqueue["device_id"] == "a"


def test_research_409_when_selection_unreachable(live):
    base, sel = live
    sel["v"] = "gone"  # selection no longer in the reachable set
    FakeFS.devices = [{"id": "a", "ownerUid": "u1"}]
    r = requests.post(base + "/research", json={"topic": "T"})
    assert r.status_code == 409 and FakeFS.last_enqueue is None


def test_research_auto_picks_single_device(live):
    base, _ = live
    FakeFS.devices = [{"id": "only", "ownerUid": "u1"}]
    r = requests.post(base + "/research", json={"topic": "T"})
    assert r.status_code == 200 and FakeFS.last_enqueue["device_id"] == "only"


def test_research_400_when_ambiguous(live):
    base, _ = live
    FakeFS.devices = [{"id": "a", "ownerUid": "u1"}, {"id": "b", "ownerUid": "u1"}]
    r = requests.post(base + "/research", json={"topic": "T"})
    assert r.status_code == 400


def test_research_400_when_no_devices(live):
    base, _ = live
    FakeFS.devices = []
    r = requests.post(base + "/research", json={"topic": "T"})
    assert r.status_code == 400


def test_research_requires_topic(live):
    base, _ = live
    FakeFS.devices = [{"id": "a", "ownerUid": "u1"}]
    assert requests.post(base + "/research", json={"deviceId": "a"}).status_code == 400


def test_research_cleans_orphan_doc_on_enqueue_failure(live):
    base, _ = live
    FakeFS.devices = [{"id": "a", "ownerUid": "u1"}]
    FakeFS.enqueue_raises = True
    r = requests.post(base + "/research", json={"topic": "T", "deviceId": "a"})
    assert r.status_code == 502
    # the chat doc was created, then deleted when the enqueue failed
    assert FakeFS.last_upsert is not None
    assert FakeFS.deleted == [FakeFS.last_upsert["rid"]]


# ── /status (GET /research/<rid>) + /cancel (POST /research/<rid>/cancel) ──

def test_research_status_found(live):
    base, _ = live
    FakeFS.researches = {"r1": {"id": "r1", "title": "Alpha", "status": "ongoing", "phase": 2}}
    r = requests.get(base + "/research/r1")
    assert r.status_code == 200
    res = r.json()["research"]
    assert res["id"] == "r1" and res["status"] == "ongoing" and res["phase"] == 2


def test_research_status_404(live):
    base, _ = live
    assert requests.get(base + "/research/ghost").status_code == 404


def test_cancel_routes_to_device_queue(live):
    base, _ = live
    FakeFS.researches = {"r1": {"id": "r1", "deviceId": "dev-a", "status": "ongoing"}}
    r = requests.post(base + "/research/r1/cancel")
    assert r.status_code == 200 and r.json()["deviceId"] == "dev-a"
    assert FakeFS.last_cancel == {"device_id": "dev-a", "uid": "u1", "research_id": "r1"}


def test_cancel_unknown_run_404(live):
    base, _ = live
    assert requests.post(base + "/research/ghost/cancel").status_code == 404
    assert FakeFS.last_cancel is None


def test_cancel_run_without_device_409(live):
    base, _ = live
    FakeFS.researches = {"r2": {"id": "r2", "status": "queued"}}  # no deviceId
    assert requests.post(base + "/research/r2/cancel").status_code == 409
    assert FakeFS.last_cancel is None


def test_status_rejects_malformed_rid(live):
    base, _ = live
    # A rid that isn't a clean doc-id (path-traversal / odd chars) → 404, and the
    # bridge never builds an out-of-tree Firestore URL from it.
    assert requests.get(base + "/research/bad$id").status_code == 404
    assert requests.get(base + "/research/a.b").status_code == 404


def test_cancel_rejects_malformed_rid(live):
    base, _ = live
    assert requests.post(base + "/research/bad$id/cancel").status_code == 404
    assert FakeFS.last_cancel is None


def test_status_502_is_non_reflective(live):
    base, _ = live
    FakeFS.get_raises = True
    r = requests.get(base + "/research/r1")
    assert r.status_code == 502
    # the upstream path / body must NOT leak to the client
    assert "SECRET-UPSTREAM-BODY" not in r.text
    assert "users/" not in r.text
    assert r.json()["error"] == "could not reach the research store — try again"


# ── P4 streaming: events on /research/<rid> + /updates ──

def test_status_includes_flattened_events(live):
    base, _ = live
    FakeFS.researches = {"r1": {"id": "r1", "status": "ongoing", "phase": 2, "links": {
        "chatgpt": {"url": "u-c", "phase": 2},
        "brief": {"url": "u-b", "label": "Brief", "phase": 1},
    }}}
    r = requests.get(base + "/research/r1").json()
    assert [e["kind"] for e in r["events"]] == ["brief", "chatgpt"]  # phase-ordered
    assert r["events"][0]["url"] == "u-b"


def test_updates_lists_runs_with_events(live):
    base, _ = live
    FakeFS.researches = {
        "r1": {"id": "r1", "status": "ongoing", "phase": 2, "topic": "T1",
               "links": {"brief": {"url": "u-b", "phase": 1}}},
        "r2": {"id": "r2", "status": "completed", "phase": 5, "topic": "T2", "links": {}},
    }
    all_runs = requests.get(base + "/updates").json()["runs"]
    assert {r["runId"] for r in all_runs} == {"r1", "r2"}
    r1 = next(r for r in all_runs if r["runId"] == "r1")
    assert r1["links"][0]["kind"] == "brief" and r1["status"] == "ongoing"


def test_updates_active_filter(live):
    base, _ = live
    FakeFS.researches = {
        "r1": {"id": "r1", "status": "ongoing", "links": {}},
        "r2": {"id": "r2", "status": "completed", "links": {}},
    }
    active = requests.get(base + "/updates?active=1").json()["runs"]
    assert {r["runId"] for r in active} == {"r1"}


def test_updates_active_keeps_needs_attention_runs(live):
    # C1 safety-critical: a run that NEEDS the user must survive active=1 even
    # though it isn't "ongoing"/"queued" — else a chat poller would miss exactly
    # the runs it must surface. A plain completed run is still filtered out.
    base, _ = live
    FakeFS.researches = {
        "r1": {"id": "r1", "status": "ongoing", "links": {}},
        "r2": {"id": "r2", "status": "errored", "links": {}},  # stuck → keep
        "r3": {"id": "r3", "status": "ongoing", "phase": 2,     # snag card → keep
               "pendingDecision": {"kind": "login_required", "title": "Sign in to ChatGPT"}},
        "r4": {"id": "r4", "status": "completed", "links": {}},  # done → drop
    }
    active = requests.get(base + "/updates?active=1").json()["runs"]
    assert {r["runId"] for r in active} == {"r1", "r2", "r3"}
    r2 = next(r for r in active if r["runId"] == "r2")
    assert r2["needsAttention"] is True and r2["attention"]  # human reason surfaced
    r3 = next(r for r in active if r["runId"] == "r3")
    assert r3["needsAttention"] is True and "Sign in" in (r3["attention"] or "")


def test_updates_and_status_carry_permanent_sr_links(live):
    # srShares (the P5-minted permanent share ids) must be projected as full
    # /shared/{doc,podcast}/<id> URLs on both /updates rows and /research/{id}.
    base, _ = live
    FakeFS.researches = {
        "r1": {"id": "r1", "status": "completed", "phase": 5, "links": {},
               "srShares": {"podcast": "SP", "brief": "SB", "claude": "SC"}},
        "r2": {"id": "r2", "status": "ongoing", "links": {}},  # not delivered yet
    }
    rows = requests.get(base + "/updates").json()["runs"]
    r1 = next(r for r in rows if r["runId"] == "r1")
    assert r1["srLinks"]["podcast"].endswith("/shared/podcast/SP")
    assert r1["srLinks"]["brief"].endswith("/shared/doc/SB")
    assert r1["srLinks"]["claude"].endswith("/shared/doc/SC")
    r2 = next(r for r in rows if r["runId"] == "r2")
    assert r2["srLinks"] == {}
    one = requests.get(base + "/research/r1").json()
    assert one["srLinks"]["podcast"].endswith("/shared/podcast/SP")


# ── /device/pair + /device/remove (forwarded to the web app as the user) ──

def test_device_pair_forwards_and_autoselects_first_device(live, monkeypatch):
    base, sel = live
    calls = {}
    def fake_fe(sess, path, payload):
        calls["path"], calls["payload"] = path, payload
        return 200, {"ok": True, "action": "initial-pair", "deviceId": "dev-n"}
    monkeypatch.setattr(bridge, "_fe_api_post", fake_fe)
    FakeFS.devices = [{"id": "dev-n", "name": "New PC", "ownerUid": "u1"}]
    r = requests.post(base + "/device/pair", json={"code": "K7XQ9B2M"})
    assert r.status_code == 200
    body = r.json()
    assert calls["path"] == "/api/devices/claim" and calls["payload"] == {"code": "K7XQ9B2M"}
    assert body["action"] == "initial-pair" and body["deviceName"] == "New PC"
    assert body["selected"] is True and sel["v"] == "dev-n"  # first device auto-selected


def test_device_pair_keeps_existing_selection(live, monkeypatch):
    base, sel = live
    sel["v"] = "dev-a"  # the user already chose a device — don't stomp it
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda s, p, b: (200, {"ok": True, "action": "share-claim", "deviceId": "dev-x"}))
    body = requests.post(base + "/device/pair", json={"code": "AAAAAAAA"}).json()
    assert body["selected"] is False and sel["v"] == "dev-a"


def test_device_pair_relays_claim_errors(live, monkeypatch):
    base, _sel = live
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda s, p, b: (429, {"error": "rate_limited", "retryAfterMs": 9000}))
    r = requests.post(base + "/device/pair", json={"code": "AAAAAAAA"})
    assert r.status_code == 429
    assert r.json() == {"error": "rate_limited", "retryAfterMs": 9000}


def test_device_remove_clears_dangling_selection(live, monkeypatch):
    base, sel = live
    sel["v"] = "dev-a"
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda s, p, b: (200, {"ok": True, "action": "owner-unlinked"}))
    body = requests.post(base + "/device/remove", json={"deviceId": "dev-a"}).json()
    assert body["action"] == "owner-unlinked"
    assert sel["v"] is None  # no stale selection pointing at the removed device


def test_device_remove_other_device_keeps_selection(live, monkeypatch):
    base, sel = live
    sel["v"] = "dev-a"
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda s, p, b: (200, {"ok": True, "action": "left-shared"}))
    requests.post(base + "/device/remove", json={"deviceId": "dev-other"})
    assert sel["v"] == "dev-a"


def test_research_with_zero_devices_guides_pairing(live):
    base, _sel = live  # FakeFS.devices = [] from the fixture
    r = requests.post(base + "/research", json={"topic": "EVs"})
    assert r.status_code == 400
    err = r.json()["error"]
    assert "pair code" in err and "device add" in err  # actionable, not a dead end


def test_research_seeds_topic_and_intro_messages(live):
    # Issue 1: an agent-started run must seed the topic + "researching" chat
    # bubbles the web app writes client-side — else the in-app chat opens
    # missing its first messages. The bridge is the agent's stand-in for the
    # missing web client.
    base, _sel = live
    FakeFS.devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    r = requests.post(base + "/research", json={"topic": "EV battery market 2026"})
    assert r.status_code == 200
    rid = r.json()["runId"]
    assert FakeFS.seeded is not None
    assert FakeFS.seeded["rid"] == rid
    assert FakeFS.seeded["topic"] == "EV battery market 2026"


def test_completed_phases_from_status_and_advancement():
    done = bridge._completed_phases({"phase": 3, "status": "ongoing",
                                     "phases": [{"phase": 4, "status": "skipped"}]})
    assert done.get(0) == "complete" and done.get(1) == "complete" and done.get(2) == "complete"
    assert done.get(4) == "skipped"
    assert 3 not in done  # the current ongoing phase isn't done yet


def test_completed_phases_clean_completion_marks_final():
    done = bridge._completed_phases({"phase": 5, "status": "completed"})
    assert done.get(5) == "complete"


def test_phase_updates_are_sr_only():
    # SR-only: only the permanent Super Research links surface (Brief P1, the three
    # reports P2, the Podcast P3). Platform links (NotebookLM, YouTube, the final
    # Google Doc) are NEVER included — P4/P5 carry no links, just progress.
    doc = {"phase": 5, "status": "completed",
           "srShares": {"brief": "B", "chatgpt": "C", "gemini": "G", "claude": "CL", "podcast": "P"},
           "links": {
               "notebooklm": {"url": "https://notebooklm.google.com/n", "phase": 3},
               "youtube": {"url": "https://youtu.be/x", "phase": 4},
               "gdocs": {"url": "https://docs.google.com/d/final", "phase": 5},
           }}
    sr = bridge._sr_links(doc)
    pus = {pu["phase"]: pu for pu in bridge._phase_updates(doc, sr)}
    assert [lk["label"] for lk in pus[1]["links"]] == ["Brief"] and pus[1]["links"][0]["permanent"]
    assert {lk["label"] for lk in pus[2]["links"]} == {"ChatGPT", "Gemini", "Claude"}
    assert all(lk["permanent"] for lk in pus[2]["links"])
    p3 = {lk["label"]: lk for lk in pus[3]["links"]}
    assert set(p3) == {"Podcast"}  # NotebookLM (platform) dropped
    assert p3["Podcast"]["permanent"] is True and p3["Podcast"]["url"].endswith("/shared/podcast/P")
    assert pus[4]["links"] == []                     # YouTube (platform) dropped
    assert pus[5]["final"] is True and pus[5]["links"] == []  # final Google Doc (platform) dropped
    all_urls = [lk["url"] for pu in pus.values() for lk in pu["links"]]
    assert not any(("notebooklm" in u) or ("youtu.be" in u) or ("docs.google.com" in u) for u in all_urls)


def test_sr_mint_gap_detects_unminted_complete_phase():
    done = {1: "complete"}
    platform = {"brief": "https://docs.google.com/brief"}  # proof the brief exists
    assert bridge._sr_mint_gap({}, platform, done) is True          # no SR yet → gap
    assert bridge._sr_mint_gap({"brief": "u"}, platform, done) is False  # already minted
    assert bridge._sr_mint_gap({}, {}, done) is False              # no proof → not a gap


def test_updates_via_agent_filters_and_builds_phase_updates(live, monkeypatch):
    base, _sel = live
    FakeFS.researches = {
        "a1": {"id": "a1", "title": "EV", "status": "ongoing", "phase": 2, "viaAgent": True,
               "srShares": {"brief": "B"},
               "links": {"brief": {"url": "https://docs.google.com/brief", "phase": 1}}},
        "w1": {"id": "w1", "title": "Web run", "status": "ongoing", "phase": 1},  # no viaAgent
    }
    monkeypatch.setattr(bridge, "_mint_sr", lambda *a, **k: None)  # brief already minted
    runs = requests.get(base + "/updates?via=agent").json()["runs"]
    assert {r["runId"] for r in runs} == {"a1"}  # web run filtered out
    pus = {pu["phase"]: pu for pu in runs[0]["phaseUpdates"]}
    assert pus[1]["status"] == "complete"
    assert any(lk["url"].endswith("/shared/doc/B") and lk["permanent"] for lk in pus[1]["links"])


def test_updates_includes_pipeline_config(live, monkeypatch):
    # The /updates payload carries the live pipelineConfig so a chat client can
    # answer "is video/email/podcast skipped?" without a second round-trip.
    base, _sel = live
    FakeFS.researches = {
        "a1": {"id": "a1", "title": "EV", "status": "ongoing", "phase": 2, "viaAgent": True,
               "pipelineConfig": {"videoEnabled": False, "emailEnabled": False}},
    }
    monkeypatch.setattr(bridge, "_mint_sr", lambda *a, **k: None)
    runs = requests.get(base + "/updates?via=agent").json()["runs"]
    assert runs[0]["pipelineConfig"] == {"videoEnabled": False, "emailEnabled": False}


def test_updates_via_agent_mints_missing_sr_link(live, monkeypatch):
    base, _sel = live
    FakeFS.researches = {
        "a1": {"id": "a1", "title": "EV", "status": "ongoing", "phase": 2, "viaAgent": True,
               "srShares": {},  # brief NOT minted yet
               "links": {"brief": {"url": "https://docs.google.com/brief", "phase": 1}}},
    }
    minted = {}
    monkeypatch.setattr(bridge, "_mint_sr",
                        lambda sess, rid, title: minted.update(rid=rid) or {"brief": "https://sr.io/shared/doc/Bnew"})
    runs = requests.get(base + "/updates?via=agent").json()["runs"]
    assert minted["rid"] == "a1"  # mint triggered (platform brief present, srShares empty)
    pu1 = next(pu for pu in runs[0]["phaseUpdates"] if pu["phase"] == 1)
    assert any("Bnew" in lk["url"] for lk in pu1["links"])


def test_research_status_mints_and_builds_phase_updates(live, monkeypatch):
    # A MANUAL `status` (GET /research/<id>) must mint the permanent SR link for a
    # complete phase and return phaseUpdates — so the chat shows the never-revoked
    # SR link, not the raw platform link.
    base, _sel = live
    FakeFS.researches = {
        "a1": {"id": "a1", "title": "EV", "status": "ongoing", "phase": 2,
               "srShares": {},  # brief NOT minted yet
               "links": {"brief": {"url": "https://docs.google.com/brief", "phase": 1}}},
    }
    minted = {}
    monkeypatch.setattr(bridge, "_mint_sr",
                        lambda sess, rid, title: minted.update(rid=rid) or {"brief": "https://sr.io/shared/doc/Bnew"})
    body = requests.get(base + "/research/a1").json()
    assert minted["rid"] == "a1"  # mint triggered on the per-run status path too
    pu1 = next(pu for pu in body["phaseUpdates"] if pu["phase"] == 1)
    assert any("Bnew" in lk["url"] and lk["permanent"] for lk in pu1["links"])
    assert body["srLinks"].get("brief", "").endswith("/shared/doc/Bnew")


def test_updates_without_via_never_mints_or_builds_phase_updates(live, monkeypatch):
    base, _sel = live
    FakeFS.researches = {"a1": {"id": "a1", "status": "ongoing", "phase": 2, "viaAgent": True,
                                "srShares": {}, "links": {"brief": {"url": "u", "phase": 1}}}}
    called = {"v": False}
    monkeypatch.setattr(bridge, "_mint_sr", lambda *a, **k: called.__setitem__("v", True) or None)
    runs = requests.get(base + "/updates").json()["runs"]  # interactive, no via=agent
    assert called["v"] is False           # interactive /updates never mints
    assert runs[0]["phaseUpdates"] == []  # …nor computes phase updates


# ── #819 per-chat watchdog isolation: chatOrigin tagging + scoped /updates ──

def test_clean_origin_requires_platform_and_chat():
    assert bridge._clean_origin({"platform": "telegram", "chat_id": "123"}) == {
        "platform": "telegram", "chat_id": "123"}
    assert bridge._clean_origin(
        {"platform": "telegram", "chat_id": "123", "thread_id": "9"}) == {
        "platform": "telegram", "chat_id": "123", "thread_id": "9"}
    assert bridge._clean_origin({"platform": "telegram"}) is None   # no chat
    assert bridge._clean_origin({"chat_id": "123"}) is None         # no platform
    assert bridge._clean_origin({"platform": " ", "chat_id": "1"}) is None  # blank platform
    assert bridge._clean_origin("nope") is None
    # over-long values are clamped; ints coerced to str
    long_chat = bridge._clean_origin({"platform": "t", "chat_id": 42})
    assert long_chat == {"platform": "t", "chat_id": "42"}


def test_new_research_fields_includes_chat_origin():
    f = bridge._new_research_fields("T", "dev", "u1", None,
                                    {"platform": "telegram", "chat_id": "5"})
    assert f["chatOrigin"] == {"platform": "telegram", "chat_id": "5"}
    assert "chatOrigin" not in bridge._new_research_fields("T", "dev", "u1", None)


def test_research_tags_chat_origin_from_body(live):
    base, _ = live
    FakeFS.devices = [{"id": "a", "ownerUid": "u1"}]
    r = requests.post(base + "/research", json={
        "topic": "T", "deviceId": "a",
        "origin": {"platform": "telegram", "chat_id": "-100", "thread_id": ""}})
    assert r.status_code == 200
    assert FakeFS.last_upsert["fields"]["chatOrigin"] == {"platform": "telegram", "chat_id": "-100"}


def test_research_without_origin_omits_chat_origin(live):
    base, _ = live
    FakeFS.devices = [{"id": "a", "ownerUid": "u1"}]
    requests.post(base + "/research", json={"topic": "T", "deviceId": "a"})
    assert "chatOrigin" not in FakeFS.last_upsert["fields"]


def test_updates_scoped_to_chat_origin(live, monkeypatch):
    # A per-chat watchdog (platform+chat query) sees ONLY runs fired from that
    # chat; another chat's agent run and an un-tagged run are both excluded.
    base, _ = live
    FakeFS.researches = {
        "tg": {"id": "tg", "title": "TG run", "status": "ongoing", "phase": 1, "viaAgent": True,
               "chatOrigin": {"platform": "telegram", "chat_id": "111"}, "links": {}},
        "wa": {"id": "wa", "title": "WA run", "status": "ongoing", "phase": 1, "viaAgent": True,
               "chatOrigin": {"platform": "whatsapp", "chat_id": "222"}, "links": {}},
        "old": {"id": "old", "title": "Untagged", "status": "ongoing", "phase": 1, "viaAgent": True,
                "links": {}},  # pre-#819 agent run, no chatOrigin
    }
    minted = {"n": 0}
    monkeypatch.setattr(bridge, "_mint_sr", lambda *a, **k: minted.__setitem__("n", minted["n"] + 1) or None)
    runs = requests.get(base + "/updates?via=agent&platform=telegram&chat=111").json()["runs"]
    assert {r["runId"] for r in runs} == {"tg"}
    assert runs[0]["chatOrigin"] == {"platform": "telegram", "chat_id": "111"}


def test_updates_chat_scope_case_insensitive_platform(live):
    base, _ = live
    FakeFS.researches = {
        "tg": {"id": "tg", "status": "ongoing", "phase": 1, "viaAgent": True,
               "chatOrigin": {"platform": "Telegram", "chat_id": "111"}, "links": {}},
    }
    runs = requests.get(base + "/updates?via=agent&platform=TELEGRAM&chat=111").json()["runs"]
    assert {r["runId"] for r in runs} == {"tg"}


def test_updates_via_agent_without_chat_returns_all_agent_runs(live):
    # via=agent with NO platform/chat (the shared/account-wide watchdog, or a
    # single-chat setup) still returns every agent run — backwards compatible.
    base, _ = live
    FakeFS.researches = {
        "tg": {"id": "tg", "status": "ongoing", "phase": 1, "viaAgent": True,
               "chatOrigin": {"platform": "telegram", "chat_id": "111"}, "links": {}},
        "wa": {"id": "wa", "status": "ongoing", "phase": 1, "viaAgent": True,
               "chatOrigin": {"platform": "whatsapp", "chat_id": "222"}, "links": {}},
    }
    runs = requests.get(base + "/updates?via=agent").json()["runs"]
    assert {r["runId"] for r in runs} == {"tg", "wa"}


def test_updates_tolerates_bad_limit(live):
    base, _ = live
    assert requests.get(base + "/updates?limit=999").status_code == 200
    assert requests.get(base + "/updates?limit=abc").status_code == 200


def test_oversized_post_body_rejected_413(live):
    base, _ = live
    # A body beyond the 1 MiB cap is refused with 413 (drained cleanly, no RST).
    big = b'{"topic":"' + b"x" * (1 << 20) + b'"}'
    r = requests.post(base + "/research", data=big,
                      headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# ── P6 /skip (POST /research/<rid>/skip) ──

def test_skip_phases_1_and_3_merge_into_skippedPhases(live):
    base, _ = live
    FakeFS.researches = {"r1": {"id": "r1", "status": "ongoing",
                                "pipelineConfig": {"skippedPhases": [3]}}}
    r = requests.post(base + "/research/r1/skip", json={"phases": [1]})
    assert r.status_code == 200 and r.json()["skipped"] == [1]
    assert FakeFS.last_pc_patch["updates"]["skippedPhases"] == [1, 3]  # merged + sorted


def test_skip_video_and_report_set_flags(live):
    base, _ = live
    FakeFS.researches = {"r1": {"id": "r1"}}
    r = requests.post(base + "/research/r1/skip", json={"phases": [4, 5]})
    assert r.status_code == 200
    u = FakeFS.last_pc_patch["updates"]
    assert u["videoEnabled"] is False and u["emailEnabled"] is False
    assert "skippedPhases" not in u  # 4/5 don't touch skippedPhases


def test_skip_rejects_non_skippable_phases(live):
    base, _ = live
    FakeFS.researches = {"r1": {"id": "r1"}}
    assert requests.post(base + "/research/r1/skip", json={"phases": [0, 2]}).status_code == 400
    assert FakeFS.last_pc_patch is None


def test_skip_requires_phase_list(live):
    base, _ = live
    FakeFS.researches = {"r1": {"id": "r1"}}
    assert requests.post(base + "/research/r1/skip", json={}).status_code == 400


def test_skip_unknown_run_404(live):
    base, _ = live
    assert requests.post(base + "/research/ghost/skip", json={"phases": [1]}).status_code == 404


def test_skip_rejects_bool_and_float_phases(live):
    base, _ = live
    FakeFS.researches = {"r1": {"id": "r1"}}
    # JSON true (a bool) and 1.0 (a float) are not phase numbers → nothing valid → 400
    assert requests.post(base + "/research/r1/skip", json={"phases": [True, 1.0]}).status_code == 400
    assert FakeFS.last_pc_patch is None


def test_skip_tolerates_malformed_existing_skippedPhases(live):
    base, _ = live
    # A non-list skippedPhases on the doc must not 500 the handler.
    FakeFS.researches = {"r1": {"id": "r1", "pipelineConfig": {"skippedPhases": "oops"}}}
    r = requests.post(base + "/research/r1/skip", json={"phases": [3]})
    assert r.status_code == 200
    assert FakeFS.last_pc_patch["updates"]["skippedPhases"] == [3]
