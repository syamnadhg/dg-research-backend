"""End-to-end: the standalone skill client sr.py against a live bridge.

Loads facade/skill/scripts/sr.py the way a runtime would (as a standalone file,
no facade import) and drives it against a real bridge whose Firestore is faked —
proving the chat slash-command path works over the loopback HTTP contract.
"""

import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import bridge


def _load_sr():
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
    spec = importlib.util.spec_from_file_location("sr_client_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load_sr()


class FakeFS:
    devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    researches: dict = {}
    last_enqueue = None
    last_cancel = None
    last_command = None
    last_pc_patch = None

    def __init__(self, _tp):
        pass

    def list_researches(self, uid, *, page_size=50):
        return [dict(d) for d in FakeFS.researches.values()]

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]

    def get_research(self, uid, rid):
        d = FakeFS.researches.get(rid)
        return dict(d) if d else None

    def upsert_research(self, uid, rid, fields):
        FakeFS.researches[rid] = {"id": rid, **{k: v for k, v in fields.items()}}

    def enqueue_start(self, device_id, **kw):
        FakeFS.last_enqueue = {"device_id": device_id, **kw}
        return "Q-1"

    def enqueue_cancel(self, device_id, *, uid, research_id, owner_control=""):
        FakeFS.last_cancel = {"device_id": device_id, "research_id": research_id,
                              "owner_control": owner_control}
        return "C-1"

    def write_command(self, uid, research_id, action, *, device_id, extra=None):
        FakeFS.last_command = {"uid": uid, "rid": research_id, "action": action,
                               "device_id": device_id, "extra": extra}
        return "CMD-1"

    def delete_research(self, uid, rid):
        FakeFS.researches.pop(rid, None)

    def patch_pipeline_config(self, uid, rid, pc_updates):
        FakeFS.last_pc_patch = {"rid": rid, "updates": pc_updates}


@pytest.fixture()
def bridge_port(monkeypatch):
    FakeFS.researches = {}
    FakeFS.last_enqueue = None
    FakeFS.last_cancel = None
    FakeFS.last_command = None
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    sel = {"v": None}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device", lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: sel.__setitem__("v", None))

    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", str(port))
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_status_account(bridge_port, capsys):
    assert sr.main(["status-account"]) == 0
    assert "Signed in as e@x.y" in capsys.readouterr().out


def test_devices(bridge_port, capsys):
    assert sr.main(["devices"]) == 0
    out = capsys.readouterr().out
    assert "My PC" in out and "owned" in out


def test_research_then_status(bridge_port, capsys):
    assert sr.main(["research", "Tesla 2025"]) == 0
    out = capsys.readouterr().out
    assert "Started" in out and "Tesla 2025" in out
    assert "My PC" in out          # the device is shown by NAME, not its id
    assert "agent-" not in out      # no raw run-id leaks into chat (I4)
    assert FakeFS.last_enqueue["device_id"] == "dev-a"  # auto-picked the sole device

    # status with no id resolves to the most recent run
    assert sr.main(["status"]) == 0
    assert "Tesla 2025" in capsys.readouterr().out


def test_podcast(bridge_port, monkeypatch, capsys):
    FakeFS.researches["agent-p"] = {
        "id": "agent-p", "title": "My Podcast Run", "status": "completed",
        "links": {"audio_file": {"url": "https://firebasestorage.googleapis.com/v0/b/x/o/"
                                        "audio%2Fu%2Fr%2Fov.m4a?alt=media&token=zzz", "phase": 3}},
    }
    monkeypatch.setattr(bridge, "_download_podcast_audio",
                        lambda url, dest_dir, rid: (dest_dir / f"{rid}.m4a", 2048))
    assert sr.main(["podcast", "agent-p"]) == 0
    out = capsys.readouterr().out
    assert "Podcast ready" in out and "My Podcast Run" in out
    assert "agent-p.m4a" in out
    assert "token=" not in out  # no tokenized URL leaks into chat


def test_podcast_not_ready(bridge_port, capsys):
    FakeFS.researches["agent-q"] = {"id": "agent-q", "status": "ongoing", "links": {}}
    assert sr.main(["podcast", "agent-q"]) == 1  # 409 → non-zero exit
    assert "isn't ready" in capsys.readouterr().out


def test_updates_json(bridge_port, capsys):
    sr.main(["research", "Topic A"])
    capsys.readouterr()
    assert sr.main(["--json", "updates"]) == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert "runs" in payload and payload["runs"]


def test_stop_running_is_graceful(bridge_port, capsys):
    # `stop` (and its `cancel` alias) on a RUNNING run writes a per-run stop
    # command (keeps results + chat) — NOT the destructive queue cancel.
    FakeFS.researches["agent-x"] = {"id": "agent-x", "title": "Mars colony",
                                    "deviceId": "dev-a", "status": "ongoing"}
    assert sr.main(["cancel", "agent-x"]) == 0
    out = capsys.readouterr().out
    assert "Stopping" in out and "Mars colony" in out and "kept" in out
    assert FakeFS.last_cancel is None  # never the destructive queue cancel
    assert FakeFS.last_command == {"uid": "u1", "rid": "agent-x", "action": "stop",
                                   "device_id": "dev-a", "extra": None}


def test_stop_queued_is_preserved(bridge_port, capsys):
    # A still-QUEUED run is preserved via ownerControl:"stop" (kept, chat intact).
    FakeFS.researches["agent-z"] = {"id": "agent-z", "deviceId": "dev-a", "status": "queued"}
    assert sr.main(["stop", "agent-z"]) == 0
    assert "Stopping" in capsys.readouterr().out
    assert FakeFS.last_command is None
    assert FakeFS.last_cancel == {"device_id": "dev-a", "research_id": "agent-z",
                                  "owner_control": "stop"}


def test_stop_by_title_latest_active(bridge_port, capsys):
    # bare `stop` targets the newest ACTIVE run; a title arg resolves by match.
    FakeFS.researches["agent-old"] = {"id": "agent-old", "title": "Old", "status": "completed"}
    FakeFS.researches["agent-new"] = {"id": "agent-new", "title": "Quantum batteries",
                                      "deviceId": "dev-a", "status": "ongoing"}
    assert sr.main(["stop", "quantum"]) == 0  # case-insensitive title match
    assert FakeFS.last_command["rid"] == "agent-new"


def test_retry_resumes_pending_decision(bridge_port, capsys):
    FakeFS.researches["agent-r"] = {
        "id": "agent-r", "deviceId": "dev-a", "status": "ongoing",
        "pendingDecision": {"kind": "pipeline_error", "phase": 2, "title": "Hit a snag"},
    }
    assert sr.main(["retry", "agent-r"]) == 0
    assert "Retrying" in capsys.readouterr().out
    assert FakeFS.last_command["action"] == "retry_phase"
    assert FakeFS.last_command["extra"] == {"phase": 2}


def test_retry_nothing_to_do(bridge_port, capsys):
    FakeFS.researches["agent-ok"] = {"id": "agent-ok", "deviceId": "dev-a", "status": "ongoing"}
    assert sr.main(["retry", "agent-ok"]) == 1  # 409 → nothing waiting on a decision
    assert "retry" in capsys.readouterr().out.lower()


def test_skip_blocker_resolves_decision(bridge_port, capsys):
    # `skip` with NO phases → skip whatever the run is blocked on. An
    # agent_link_failed decision → agent_decision{decision:"skip"}.
    FakeFS.researches["agent-b"] = {
        "id": "agent-b", "deviceId": "dev-a", "status": "ongoing",
        "pendingDecision": {"kind": "agent_link_failed", "agent": "gemini", "title": "Link failed"},
    }
    assert sr.main(["skip", "--run", "agent-b"]) == 0
    assert "Skipping" in capsys.readouterr().out
    assert FakeFS.last_command["action"] == "agent_decision"
    assert FakeFS.last_command["extra"] == {"agent": "gemini", "decision": "skip"}


def test_status_surfaces_blocker(bridge_port, capsys):
    # C1: a run waiting on the user shows the "Needs you" line + a chat action.
    FakeFS.researches["agent-s"] = {
        "id": "agent-s", "status": "ongoing", "phase": 2,
        "pendingDecision": {"kind": "login_required", "title": "Sign in to ChatGPT"},
    }
    assert sr.main(["status", "agent-s"]) == 0
    out = capsys.readouterr().out
    assert "Needs you" in out and "Sign in to ChatGPT" in out
    assert "retry" in out.lower()


def test_skip_by_name(bridge_port, capsys):
    FakeFS.researches["agent-y"] = {"id": "agent-y", "status": "ongoing", "pipelineConfig": {}}
    assert sr.main(["skip", "video", "report", "--run", "agent-y"]) == 0
    assert "skip" in capsys.readouterr().out.lower()
    u = FakeFS.last_pc_patch["updates"]
    assert u["videoEnabled"] is False and u["emailEnabled"] is False


def test_unreachable_bridge_is_graceful(monkeypatch, capsys):
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", "1")  # nothing listening
    # graceful (no traceback) but a NON-zero exit so the cron detects failure
    assert sr.main(["devices"]) == 2
    assert "unreachable" in capsys.readouterr().out.lower()


def test_bad_port_env_falls_back(monkeypatch, capsys):
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", "not-a-port")
    sr.main(["devices"])  # must not crash; uses 9876 (nothing there → unreachable)
    assert "9876" in capsys.readouterr().err
