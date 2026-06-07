"""Full chat lifecycle, end to end, through the standalone skill client.

Drives sr.py (loaded as a runtime would) against a LIVE bridge whose remote-login
broker is a mock FE and whose Firestore is faked — exercising the whole arc a user
goes through in chat: not-signed-in → /login → approve → /device → /research →
/status → /updates → /skip → /cancel → /logout. The single live enqueue against a
real device is the human checkpoint (operator signs in); this proves the wiring.
"""

import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from _helpers import make_jwt

from facade import bridge, config
from facade import store as store_mod


def _load_sr():
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
    spec = importlib.util.spec_from_file_location("sr_e2e", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load_sr()


class FakeFS:
    devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    researches: dict = {}
    last_rid = None
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
        FakeFS.researches[rid] = {"id": rid, **fields}
        FakeFS.last_rid = rid

    def enqueue_start(self, device_id, **kw):
        return "Q-1"

    def enqueue_cancel(self, device_id, *, uid, research_id):
        FakeFS.last_cancel = research_id
        return "C-1"

    def delete_research(self, uid, rid):
        FakeFS.researches.pop(rid, None)

    def patch_pipeline_config(self, uid, rid, pc_updates):
        FakeFS.last_pc_patch = {"rid": rid, "updates": pc_updates}


@pytest.fixture()
def live(monkeypatch, mock_fe):
    FakeFS.researches = {}
    FakeFS.last_rid = FakeFS.last_cancel = FakeFS.last_pc_patch = None

    # in-memory secret store + prefs (no real ~/.super-agent / keyring)
    mem = {}
    monkeypatch.setattr(store_mod, "load", lambda: mem.get("blob"))
    monkeypatch.setattr(store_mod, "save", lambda b: mem.__setitem__("blob", dict(b)))
    monkeypatch.setattr(store_mod, "clear", lambda: mem.pop("blob", None))
    sel = {"v": None}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device", lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: sel.__setitem__("v", None))
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    # /podcast downloads host-side; fake it so the live HTTP test does no network.
    monkeypatch.setattr(bridge, "_download_podcast_audio",
                        lambda url, dest_dir, rid: (dest_dir / f"{rid}.m4a", 1234))

    # mock FE broker: start → approve immediately → custom-token exchange
    idt = make_jwt({"user_id": "u1", "email": "you@x.y"})
    fe = mock_fe(
        start_resp={"code": "AB-12", "pollToken": "PT",
                    "verifyUrl": "https://superresearch.io/connect-agent", "expiresIn": 600},
        poll_script=[(200, {"status": "approved", "customToken": "CT"})],
        exchange_resp={"idToken": idt, "refreshToken": "RT-r", "expiresIn": "3600"},
    )
    monkeypatch.setattr(config, "FE_BASE", fe)
    monkeypatch.setattr(config, "SIGN_IN_WITH_CUSTOM_TOKEN_URL", fe + "/identitytoolkit")

    state = bridge.BridgeState()  # starts signed-out (mem empty)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", str(port))
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_full_chat_lifecycle(live, capsys):
    state = live

    # 1. not signed in
    assert sr.main(["status-account"]) == 0
    assert "Not signed in" in capsys.readouterr().out

    # 2. /login → shows the sign-in link (no code typed — it's embedded in the link)
    assert sr.main(["login"]) == 0
    assert "connect-agent" in capsys.readouterr().out

    # 3. approve completes on the next poll → connected
    assert sr.main(["login-wait"]) == 0
    assert "Connected as you@x.y" in capsys.readouterr().out
    assert state.session is not None and state.session.uid == "u1"

    # 4. signed in now
    assert sr.main(["status-account"]) == 0
    assert "Signed in as you@x.y" in capsys.readouterr().out

    # 5. /device list + 6. switch
    assert sr.main(["devices"]) == 0
    assert "My PC" in capsys.readouterr().out
    assert sr.main(["device-use", "dev-a"]) == 0
    assert "Now running on" in capsys.readouterr().out

    # 7. /research → a run id immediately
    assert sr.main(["research", "Tesla 2025 outlook"]) == 0
    assert "Started" in capsys.readouterr().out
    rid = FakeFS.last_rid
    assert rid and rid.startswith("agent-")

    # 8. /status [id] + 9. /updates (cron)
    assert sr.main(["status", rid]) == 0
    assert "Tesla 2025 outlook" in capsys.readouterr().out
    assert sr.main(["--json", "updates"]) == 0
    import json
    assert any(r["runId"] == rid for r in json.loads(capsys.readouterr().out)["runs"])

    # 9b. /podcast → the run's audio resolves to a local file to send as native audio
    FakeFS.researches[rid]["links"] = {
        "audio_file": {"url": "https://firebasestorage.googleapis.com/v0/b/x/o/"
                              "audio%2Fu1%2Fr%2Fov.m4a?alt=media&token=tok", "phase": 3}
    }
    assert sr.main(["podcast", rid]) == 0
    pod_out = capsys.readouterr().out
    assert "Podcast ready" in pod_out and f"{rid}.m4a" in pod_out
    assert "token=" not in pod_out  # the Storage download token never reaches chat

    # 10. /skip → tunes the run config
    assert sr.main(["skip", rid, "video", "report"]) == 0
    capsys.readouterr()
    assert FakeFS.last_pc_patch["updates"] == {"videoEnabled": False, "emailEnabled": False}

    # 11. /cancel
    assert sr.main(["cancel", rid]) == 0
    assert FakeFS.last_cancel == rid
    capsys.readouterr()

    # 12. /logout → signed out again
    assert sr.main(["logout"]) == 0
    assert state.session is None
    assert sr.main(["status-account"]) == 0
    assert "Not signed in" in capsys.readouterr().out
