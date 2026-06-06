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
