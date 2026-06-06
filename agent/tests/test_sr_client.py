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

    def enqueue_cancel(self, device_id, *, uid, research_id):
        FakeFS.last_cancel = {"device_id": device_id, "research_id": research_id}
        return "C-1"

    def delete_research(self, uid, rid):
        FakeFS.researches.pop(rid, None)

    def patch_pipeline_config(self, uid, rid, pc_updates):
        FakeFS.last_pc_patch = {"rid": rid, "updates": pc_updates}


@pytest.fixture()
def bridge_port(monkeypatch):
    FakeFS.researches = {}
    FakeFS.last_enqueue = None
    FakeFS.last_cancel = None
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
    assert "Started" in out and "agent-" in out
    assert FakeFS.last_enqueue["device_id"] == "dev-a"  # auto-picked the sole device

    # status with no id resolves to the most recent run
    assert sr.main(["status"]) == 0
    assert "Tesla 2025" in capsys.readouterr().out


def test_updates_json(bridge_port, capsys):
    sr.main(["research", "Topic A"])
    capsys.readouterr()
    assert sr.main(["--json", "updates"]) == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert "runs" in payload and payload["runs"]


def test_cancel(bridge_port, capsys):
    FakeFS.researches["agent-x"] = {"id": "agent-x", "deviceId": "dev-a", "status": "ongoing"}
    assert sr.main(["cancel", "agent-x"]) == 0
    assert "Cancel requested" in capsys.readouterr().out
    assert FakeFS.last_cancel == {"device_id": "dev-a", "research_id": "agent-x"}


def test_skip_by_name(bridge_port, capsys):
    FakeFS.researches["agent-y"] = {"id": "agent-y", "pipelineConfig": {}}
    assert sr.main(["skip", "agent-y", "video", "report"]) == 0
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
