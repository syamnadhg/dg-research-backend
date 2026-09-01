"""The bridge routes that act on a blocked run: /updates, /research/{id},
/research/{id}/resolve and /research/{id}/resume, over a live loopback bridge.

⛔ THE PROPERTY THIS FILE EXISTS TO PIN: the row a chat client reads and the
route that acts on it must agree. They used to be two independent readings of
the same document — the row said "needs you" and offered "retry or skip" while
the route decided, separately, which command to write. So the row could advertise
a Skip the route would resolve into a command that TERMINATED THE RUN, and a
Retry the route resolved into a write nothing consumed. Both now come from
_run_plan over the same decoded doc; several tests below drive one fixture
through BOTH endpoints and compare.
"""

import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge

from test_decision_plan_0831 import (  # noqa: E402  (sibling fixture builders)
    browser_launch_card,
    crash_login_interrupt_card,
    crash_loop_card,
    env_card,
    p0_login_card,
    worktab_login_card,
)


class FakeFS:
    researches: dict = {}
    devices: list = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    commands: list = []
    resumes: list = []
    updates: list = []

    def __init__(self, _tp):
        pass

    def list_researches(self, uid, *, page_size=50):
        return [dict(d) for d in FakeFS.researches.values()]

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]

    def get_research(self, uid, rid):
        d = FakeFS.researches.get(rid)
        return dict(d) if d else None

    def write_command(self, uid, research_id, action, *, device_id, extra=None):
        FakeFS.commands.append({"rid": research_id, "action": action,
                                "device_id": device_id, "extra": extra})
        return "CMD-1"

    def enqueue_resume(self, device_id, *, uid, research_id, backend_run_id, email=""):
        FakeFS.resumes.append({"device_id": device_id, "uid": uid,
                               "research_id": research_id,
                               "backend_run_id": backend_run_id, "email": email})
        return "Q-R1"

    def update_research(self, uid, rid, patch, *, delete_fields=None):
        FakeFS.updates.append({"rid": rid, "patch": dict(patch),
                               "delete_fields": list(delete_fields or [])})
        d = FakeFS.researches.get(rid)
        if d is not None:
            d.update(patch)
            for f in (delete_fields or []):
                d.pop(f, None)


@pytest.fixture()
def live(monkeypatch):
    FakeFS.researches = {}
    FakeFS.devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    FakeFS.commands = []
    FakeFS.resumes = []
    FakeFS.updates = []
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: None)
    monkeypatch.setattr(bridge.prefs, "set_selected_device", lambda d, uid: None)
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: None)
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda **kw: None)
    monkeypatch.setattr(bridge.selfupdate, "latest_on_pypi", lambda pkg, force=False: None)
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _seed(rid="r1", *, card=None, status="ongoing", brid="run-9", device="dev-a"):
    doc = {"id": rid, "status": status, "links": {}, "deviceId": device}
    if brid:
        doc["backendRunId"] = brid
    if card is not None:
        doc["pendingDecision"] = card
    FakeFS.researches[rid] = doc
    return doc


def _row(base, rid="r1"):
    runs = requests.get(base + "/updates").json()["runs"]
    return next(r for r in runs if r["runId"] == rid)


def _resolve(base, intent, rid="r1"):
    return requests.post(f"{base}/research/{rid}/resolve", json={"intent": intent})


# ── the row carries the answers ──────────────────────────────────────────────

def test_updates_row_carries_action_details_offers(live):
    _seed(card=crash_loop_card())
    r = _row(live)
    assert r["needsAttention"] is True
    assert "last checkpoint" in r["attentionAction"]
    assert "didn't take" in r["attentionDetails"]
    assert r["attentionOffers"] == ["retry", "skip"]


def test_updates_row_omits_the_raw_pending_decision(live):
    """⛔ The tempting way to fix "chat drops details" is to ship the whole map.
    The row has no byte cap, the map is untruncated at source, and the client
    would then re-derive the classification in a script that ships on a DIFFERENT
    schedule from this bridge. Compute once here; ship the answers."""
    _seed(card=crash_loop_card())
    r = _row(live)
    assert "pendingDecision" not in r


def test_updates_row_offers_only_retry_on_a_skipless_card(live):
    _seed(card=crash_login_interrupt_card())
    assert _row(live)["attentionOffers"] == ["retry"]


def test_updates_row_of_a_healthy_run_offers_nothing(live):
    _seed(status="ongoing")
    r = _row(live)
    assert r["needsAttention"] is False
    assert r["attentionAction"] is None and r["attentionOffers"] == []


def test_research_route_injects_the_same_five_keys(live):
    """⛔ `sr status` printed NO blocker line at all for a run blocked by STATUS,
    while `sr updates` printed one — the same run, two answers, depending which
    command you asked with. /research/{id} returns the raw doc, which carries no
    computed attention fields at all."""
    _seed(status="paused_backend_restart")
    doc = requests.get(live + "/research/r1").json()["research"]
    assert doc["needsAttention"] is True
    assert doc["attention"] == "paused after a backend restart"
    assert "last checkpoint" in doc["attentionAction"]
    assert doc["attentionOffers"] == ["retry"]


def test_resolve_and_updates_agree_on_every_card(live):
    """The single-entry-point property, driven end to end: whatever the row
    advertises, the route honours — and whatever it does not, the route refuses."""
    for card in (env_card(), p0_login_card(), worktab_login_card(),
                 crash_loop_card(), crash_login_interrupt_card(),
                 browser_launch_card()):
        FakeFS.researches = {}
        _seed(card=card)
        offers = _row(live)["attentionOffers"]
        for intent in ("retry", "skip"):
            code = _resolve(live, intent).status_code
            assert (code == 200) == (intent in offers), (card.get("alert_id"), intent, code)


# ── (c) the refusal ──────────────────────────────────────────────────────────

def test_skip_on_a_skipless_card_is_409_and_writes_nothing(live):
    _seed(card=crash_login_interrupt_card())
    r = _resolve(live, "skip")
    assert r.status_code == 409
    body = r.json()
    assert body["reason"] == "no_such_action"
    assert body["card"] == "crash_login_interrupt"
    assert body["offers"] == ["retry"]
    assert "no Skip" in body["error"]
    assert FakeFS.commands == [] and FakeFS.resumes == [] and FakeFS.updates == []


def test_skip_on_the_browser_launch_card_writes_nothing(live):
    """⛔⛔ THE HIDDEN STOP. research.py's phase-0 browser-launch gate terminates
    the pipeline for any decision that is not "retry". Chat used to mint
    skip_phase(0) here and report "Skipping the current blocker" — so a person
    asking to skip past one failure ended their whole run."""
    _seed(card=browser_launch_card())
    assert _resolve(live, "skip").status_code == 409
    assert FakeFS.commands == []


def test_a_refusal_is_409_not_400_so_an_old_client_still_prints_it(live):
    """sr.py's error path prints the bridge's `error` verbatim for any non-200,
    so the honest sentence lands even on a script that predates this change. It
    is 409 (state conflict) rather than 400 because the request was well-formed."""
    _seed(card=crash_login_interrupt_card())
    r = _resolve(live, "skip")
    assert r.status_code == 409
    assert r.json()["error"].startswith("That card has no Skip.")


def test_no_card_at_all_keeps_its_own_distinct_message(live):
    """"This run isn't waiting on a decision" and "that card has no Skip" are
    different answers; collapsing them would tell someone their blocked run is
    fine."""
    _seed(status="ongoing")
    r = _resolve(live, "skip")
    assert r.status_code == 409
    assert "isn't waiting on a decision" in r.json()["error"]
    assert "reason" not in r.json()


# ── (b) the real resume ──────────────────────────────────────────────────────

def test_retry_on_a_crash_card_enqueues_a_queue_resume_not_a_command(live):
    """⛔⛔ THE OWNER'S SECOND ASK, at the route. A per-run command here is
    consumed by nobody — the listener died with run_pipeline."""
    _seed(card=crash_loop_card())
    r = _resolve(live, "retry")
    assert r.status_code == 200
    assert r.json()["transport"] == "queue_resume"
    assert FakeFS.commands == []
    assert FakeFS.resumes == [{"device_id": "dev-a", "uid": "u1",
                               "research_id": "r1", "backend_run_id": "run-9",
                               "email": ""}]


def test_a_resume_without_a_backend_run_id_is_refused_up_front(live):
    """⛔ The backend's resume handler DELETES the queue doc with only a local
    WARN when backendRunId is missing (the synthetic device user cannot read the
    research doc to recover it). Chat would report a resume that evaporated on
    the far side, silently."""
    _seed(card=crash_loop_card(), brid=None)
    r = _resolve(live, "retry")
    assert r.status_code == 409
    assert r.json()["reason"] == "no_checkpoint"
    assert FakeFS.resumes == []


def test_paused_backend_restart_resolves_by_queue(live):
    _seed(status="paused_backend_restart")
    r = _resolve(live, "retry")
    assert r.status_code == 200 and r.json()["transport"] == "queue_resume"
    assert len(FakeFS.resumes) == 1 and FakeFS.commands == []


def test_the_resume_route_stops_claiming_a_restart_paused_run_resumed(live):
    """⛔ /research/{id}/resume answered a cheerful 200 for a write whose
    listener died with the old daemon. It now takes the same queue transport."""
    _seed(status="paused_backend_restart")
    r = requests.post(live + "/research/r1/resume")
    assert r.status_code == 200 and r.json()["transport"] == "queue_resume"
    assert FakeFS.commands == [] and len(FakeFS.resumes) == 1


def test_the_resume_route_keeps_the_command_path_for_a_normally_paused_run(live):
    """A run paused by the user is LIVE — its listener is bound, and the per-run
    command is the correct, cheaper write. Widening the queue path to cover it
    would restart a run that only needed un-pausing."""
    _seed(status="paused")
    r = requests.post(live + "/research/r1/resume")
    assert r.status_code == 200 and r.json()["transport"] == "command"
    assert [c["action"] for c in FakeFS.commands] == ["resume"]
    assert FakeFS.resumes == []


def test_the_resume_payload_carries_no_config(live):
    """The backend merges a supplied config PERMANENTLY into the run's
    config.json — a resume that shipped one would silently rewrite the run's own
    configuration."""
    _seed(card=crash_loop_card())
    _resolve(live, "retry")
    assert "config" not in FakeFS.resumes[0]


# ── the commands the route actually writes ───────────────────────────────────

def test_worktab_skip_writes_skip_agent(live):
    """⛔ It used to write skip_init_verify, which that loop reads as a RETRY —
    so the wall re-carded forever instead of dropping the platform."""
    _seed(card=worktab_login_card())
    assert _resolve(live, "skip").status_code == 200
    assert FakeFS.commands[-1]["action"] == "skip_agent"
    assert FakeFS.commands[-1]["extra"] == {"agent": "claude"}


def test_env_card_retry_targets_phase_zero(live):
    _seed(card=env_card())
    assert _resolve(live, "retry").status_code == 200
    assert FakeFS.commands[-1]["action"] == "retry_phase"
    assert FakeFS.commands[-1]["extra"] == {"phase": 0}


def test_crash_loop_skip_clears_the_durable_card(live):
    """The bridge's equivalent of the app's Discard: the card is what re-surfaces
    on every cold chat open, so clearing the durable slot IS the skip."""
    _seed(card=crash_loop_card())
    r = _resolve(live, "skip")
    assert r.status_code == 200 and r.json()["action"] == "discard"
    assert FakeFS.updates == [{"rid": "r1", "patch": {},
                               "delete_fields": ["pendingDecision"]}]
    assert FakeFS.commands == []


def test_a_run_with_no_device_is_still_refused(live):
    _seed(card=crash_loop_card(), device="")
    r = _resolve(live, "retry")
    assert r.status_code == 409 and "no device" in r.json()["error"]
    assert FakeFS.resumes == []


def test_a_malformed_card_does_not_take_the_updates_route_down(live):
    """A card whose fields are the wrong types must not 500 /updates — that would
    hide every OTHER run on the account behind one bad document."""
    _seed(rid="r1", card={"kind": True, "phase": ["x"], "agent": 7,
                          "machineName": False, "details": 12})
    _seed(rid="r2", status="ongoing")
    body = requests.get(live + "/updates")
    assert body.status_code == 200
    assert {r["runId"] for r in body.json()["runs"]} == {"r1", "r2"}
