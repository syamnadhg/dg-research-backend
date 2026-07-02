"""End-to-end: the standalone skill client sr.py against a live bridge.

Loads facade/skill/scripts/sr.py the way a runtime would (as a standalone file,
no facade import) and drives it against a real bridge whose Firestore is faked —
proving the chat slash-command path works over the loopback HTTP contract.
"""

import importlib.util
import re
import threading
import time
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
    last_update = None
    seeded = None
    last_page_size = None

    def __init__(self, _tp):
        pass

    def list_researches(self, uid, *, page_size=50):
        # Honor page_size like the real Firestore list (newest-first window) so a
        # test can prove a run buried beyond the window is/ isn't returned — not
        # just that the right page_size was requested.
        FakeFS.last_page_size = page_size
        return [dict(d) for d in list(FakeFS.researches.values())[:page_size]]

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

    def seed_chat_messages(self, uid, rid, *, topic, title):
        FakeFS.seeded = {"rid": rid, "topic": topic, "title": title}

    def enqueue_cancel(self, device_id, *, uid, research_id, owner_control=""):
        FakeFS.last_cancel = {"device_id": device_id, "research_id": research_id,
                              "owner_control": owner_control}
        return "C-1"

    def write_command(self, uid, research_id, action, *, device_id, extra=None):
        FakeFS.last_command = {"uid": uid, "rid": research_id, "action": action,
                               "device_id": device_id, "extra": extra}
        return "CMD-1"

    def update_research(self, uid, rid, patch, *, delete_fields=None):
        FakeFS.last_update = {"rid": rid, "patch": dict(patch),
                              "delete_fields": list(delete_fields or [])}
        d = FakeFS.researches.get(rid)
        if d is not None:
            d.update(patch)
            for f in (delete_fields or []):
                d.pop(f, None)

    def delete_research(self, uid, rid):
        FakeFS.researches.pop(rid, None)

    def patch_pipeline_config(self, uid, rid, pc_updates):
        FakeFS.last_pc_patch = {"rid": rid, "updates": pc_updates}


@pytest.fixture()
def bridge_port(monkeypatch):
    FakeFS.researches = {}
    FakeFS.devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    FakeFS.last_enqueue = None
    FakeFS.last_cancel = None
    FakeFS.last_command = None
    FakeFS.last_update = None
    FakeFS.seeded = None
    FakeFS.last_page_size = None
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    sel = {"v": None}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device", lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: sel.__setitem__("v", None))
    # Never hit PyPI from tests: neutralize the update notices by default (the
    # /status + /version routes call these). Tests that assert notices override them.
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda: None)
    monkeypatch.setattr(bridge.selfupdate, "backend_update_available", lambda b: None)
    # The update routes do a FRESH latest_on_pypi(force=True) check; default it to
    # None (= "couldn't determine → proceed"). "already up to date" tests override it.
    monkeypatch.setattr(bridge.selfupdate, "latest_on_pypi", lambda pkg, force=False: None)

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


def test_status_account_no_device_nudges_pairing(bridge_port, capsys):
    # #851 item 2: signed in but no paired device → can't run research yet, so
    # steer to pairing instead of leaving the user at a dead end.
    FakeFS.devices = []
    assert sr.main(["status-account"]) == 0
    out = capsys.readouterr().out
    assert "Signed in as e@x.y" in out
    assert "No device connected" in out and "access code" in out


def test_connected_msg_is_device_aware(bridge_port):
    # #851 item 2: the post-sign-in confirmation depends on whether a device exists.
    assert "all set" in sr._connected_msg("e@x.y")  # FakeFS has My PC
    FakeFS.devices = []
    assert "access code" in sr._connected_msg("e@x.y").lower()


def test_login_copy_does_not_demand_login_done():
    # #851 item 2: the user must NOT be told to run/repeat login-done — sign-in
    # auto-completes (the bridge auto-poller, #848); the AI confirms it.
    import inspect
    assert "login-done" not in inspect.getsource(sr.cmd_login).lower()


def test_prepare_stream_arm_account_wide_without_origin(monkeypatch):
    # #851 item 3: with no chat origin in env, arming falls back to the shared
    # account-wide watchdog directive (no per-chat shim write); rc ok, fixed
    # dedupable job name, and the self-teardown promise in the copy.
    for v in ("HERMES_SESSION_PLATFORM", "HERMES_SESSION_CHAT_ID", "HERMES_SESSION_THREAD_ID"):
        monkeypatch.delenv(v, raising=False)
    lines, payload, rc = sr._prepare_stream_arm()
    assert rc == 0 and payload["scoped"] is False
    blob = "\n".join(lines)
    assert "cronjob: create" in blob and 'name="sr-stream"' in blob
    assert "auto-removes when the run finishes" in blob


def test_status_account_inflight_signin_hint(monkeypatch, capsys):
    # #848 P3: a not-signed-in bridge with a sign-in mid-flight tells the user to
    # approve it in the browser (the auto-poller then connects them), instead of a
    # bare "Not signed in — run login".
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda: None)
    monkeypatch.setattr(bridge.selfupdate, "backend_update_available", lambda b: None)
    monkeypatch.setattr(bridge, "_backend_version", lambda: None)
    state = bridge.BridgeState()
    state.set_session(None)  # force not-signed-in regardless of any on-disk session
    state.set_remote(bridge.RemoteFlow(
        poll_token="PT", code="X", verify_url="https://x/c", expires_at=time.time() + 600,
    ))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", str(port))
    try:
        assert sr.main(["status-account"]) == 0
        out = capsys.readouterr().out.lower()
        assert "in progress" in out and "browser" in out and "not signed in" not in out
    finally:
        httpd.shutdown()
        httpd.server_close()


def _no_session_bridge(monkeypatch, *, remote_state: str | None = None):
    """A running bridge with NO account session (optionally a remote flow in
    `remote_state`). Returns (httpd) — caller closes it."""
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda: None)
    monkeypatch.setattr(bridge.selfupdate, "backend_update_available", lambda b: None)
    monkeypatch.setattr(bridge, "_backend_version", lambda: None)
    state = bridge.BridgeState()
    state.set_session(None)  # force not-signed-in regardless of any on-disk session
    if remote_state:
        rf = bridge.RemoteFlow(poll_token="PT", code="X", verify_url="https://x/c", expires_at=time.time() + 600)
        rf.state = remote_state
        state.set_remote(rf)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", str(httpd.server_address[1]))
    return httpd


def test_research_when_not_signed_in_steers_to_fresh_login(monkeypatch, capsys):
    # Research while not signed in → hand back a ready-to-click sign-in LINK (start a
    # fresh remote-login) and tell the user to log in then ask again — natural language,
    # no command word, no login-done, no auto-resume. (Mock the broker so no network.)
    monkeypatch.setattr(bridge.devicelogin, "start", lambda **kw: {
        "pollToken": "PT", "code": "ABCD",
        "verifyUrl": "https://superresearch.io/c/ABCD", "expiresIn": 600,
    })
    httpd = _no_session_bridge(monkeypatch)
    try:
        rc = sr.main(["research", "Golden retriever"])
        out = capsys.readouterr().out.lower()
        assert rc != 0
        assert "not signed in" in out and "log in here" in out
        assert "superresearch.io/c/abcd" in out
        assert "login-done" not in out
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_research_when_signin_in_flight_says_approve_in_browser(monkeypatch, capsys):
    # A sign-in is mid-flight → tell the user to finish it in the browser (the bridge
    # auto-captures), not to start a fresh login. Natural language, no command word.
    httpd = _no_session_bridge(monkeypatch, remote_state="pending")
    try:
        rc = sr.main(["research", "Golden retriever"])
        out = capsys.readouterr().out.lower()
        assert rc != 0
        assert "browser" in out and ("finish" in out or "almost" in out)
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_login_arms_watchdog_and_passes_origin(monkeypatch, capsys):
    # /sr login arms this chat's watchdog so the bridge's "✓ signed in" announce
    # posts proactively on capture, and passes the chat origin so it's scoped.
    posts = []
    monkeypatch.setattr(sr, "_post",
                        lambda path, body=None: posts.append((path, body)) or (200, {"verifyUrl": "https://x/c"}))
    monkeypatch.setattr(sr, "_origin_from_env", lambda: {"platform": "telegram", "chat_id": "111"})
    armed = {"n": 0}
    monkeypatch.setattr(sr, "_prepare_stream_arm",
                        lambda: armed.__setitem__("n", armed["n"] + 1) or (["cronjob: create …"], {}, 0))
    rc = sr.main(["login"])
    assert rc == 0
    start = [b for (p, b) in posts if p == "/login/remote/start"]
    assert start and start[0].get("origin") == {"platform": "telegram", "chat_id": "111"}
    assert armed["n"] == 1
    assert "cronjob: create" in capsys.readouterr().out


def test_research_401_stashes_topic_and_arms_watchdog(monkeypatch, capsys):
    # Research while signed out: the topic is stashed on the sign-in start (so the
    # post-login watchdog can offer to continue it) and the watchdog is armed.
    calls = []

    def fake_post(path, body=None):
        calls.append((path, body))
        if path == "/research":
            return 401, {"error": "unauthorized"}
        if path == "/login/remote/start":
            return 200, {"verifyUrl": "https://superresearch.io/c/XYZ"}
        return 200, {}

    monkeypatch.setattr(sr, "_post", fake_post)
    monkeypatch.setattr(sr, "_get", lambda path: (200, {"authed": False}))  # no in-flight login
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: (["cronjob: create …"], {}, 0))
    rc = sr.main(["research", "the EV battery market"])
    assert rc != 0
    start = [b for (p, b) in calls if p == "/login/remote/start"]
    assert start and start[0].get("pending_topic") == "the EV battery market"
    out = capsys.readouterr().out.lower()
    assert "log in here" in out and "pick this up" in out


def test_devices(bridge_port, capsys):
    assert sr.main(["devices"]) == 0
    out = capsys.readouterr().out
    assert "My PC" in out and "owned" in out


def test_devices_empty_guides_pairing(bridge_port, capsys):
    # Zero devices must NOT be a dead end — the user is told how to add one.
    FakeFS.devices = []
    assert sr.main(["devices"]) == 0
    out = capsys.readouterr().out
    assert "access code" in out and "superresearch --pair" in out


def test_device_use_by_name(bridge_port, capsys):
    # Switching takes the NAME (case-insensitive), never makes the user type an id.
    FakeFS.devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"},
                      {"id": "dev-b", "name": "Office PC", "ownerUid": "u1"}]
    assert sr.main(["device-use", "office pc"]) == 0
    assert "Office PC" in capsys.readouterr().out


def test_device_use_ambiguous_name_lists_matches(bridge_port, capsys):
    FakeFS.devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"},
                      {"id": "dev-b", "name": "Office PC", "ownerUid": "u1"}]
    assert sr.main(["device-use", "pc"]) == 1  # substring hits both
    out = capsys.readouterr().out
    assert "more than one device" in out and "My PC" in out and "Office PC" in out


def test_device_add_pairs_and_autoselects(bridge_port, monkeypatch, capsys):
    # First device: claim forwards to the web app route; the bridge auto-selects
    # it so research can start immediately.
    calls = {}
    def fake_fe(sess, path, payload):
        calls["path"], calls["payload"] = path, payload
        return 200, {"ok": True, "action": "initial-pair", "deviceId": "dev-new"}
    monkeypatch.setattr(bridge, "_fe_api_post", fake_fe)
    FakeFS.devices = [{"id": "dev-new", "name": "New Laptop", "ownerUid": "u1"}]
    assert sr.main(["device-add", "K7XQ-9B2M"]) == 0
    out = capsys.readouterr().out
    assert calls["path"] == "/api/devices/claim"
    assert calls["payload"] == {"code": "K7XQ-9B2M"}  # server normalizes dashes
    assert "Added" in out and "New Laptop" in out
    assert "selected" in out  # auto-selected as the first device


def test_device_add_friendly_errors(bridge_port, monkeypatch, capsys):
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda sess, path, payload: (404, {"error": "code_not_found"}))
    assert sr.main(["device-add", "BADCODE1"]) == 1
    assert "match any device" in capsys.readouterr().out


def test_device_remove_by_name_owner(bridge_port, monkeypatch, capsys):
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda sess, path, payload: (200, {"ok": True, "action": "owner-unlinked"}))
    assert sr.main(["device-remove", "my pc"]) == 0
    out = capsys.readouterr().out
    assert "Unlinked" in out and "My PC" in out and "re-paired" in out


def test_device_remove_sharer_leaves(bridge_port, monkeypatch, capsys):
    FakeFS.devices = [{"id": "dev-s", "name": "Boss PC", "ownerUid": "other"}]
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda sess, path, payload: (200, {"ok": True, "action": "left-shared"}))
    assert sr.main(["device-remove", "boss pc"]) == 0
    assert "Left the shared device" in capsys.readouterr().out


def test_version_reports_agent_and_backend(bridge_port, monkeypatch, capsys):
    # `version` from chat reads the bridge's /version: the agent's own version +
    # the co-located backend's version (parsed from `superresearch --version`).
    monkeypatch.setattr(bridge, "_backend_version", lambda: "0.1.1")
    assert sr.main(["version"]) == 0
    out = capsys.readouterr().out
    assert f"v{bridge.__version__}" in out      # agent version
    assert "backend  v0.1.1" in out             # backend version


def test_version_when_backend_absent(bridge_port, monkeypatch, capsys):
    # Backend not co-located (CLI off PATH) → say so, don't fabricate a version.
    monkeypatch.setattr(bridge, "_backend_version", lambda: None)
    assert sr.main(["version"]) == 0
    assert "not installed" in capsys.readouterr().out


def test_update_starts_backend(bridge_port, monkeypatch, capsys):
    # `update` from chat kicks `superresearch --update` on the connected device
    # (the bridge shells out; the backend's updater detaches and returns fast).
    monkeypatch.setattr(bridge, "_backend_version", lambda: "0.1.1")
    monkeypatch.setattr(bridge.selfupdate, "latest_on_pypi", lambda pkg, force=False: "0.2.0")  # newer
    calls = {}
    def _fake_update():
        calls["ran"] = True
        return {"rc": 0, "output": "started"}
    monkeypatch.setattr(bridge, "_start_backend_update", _fake_update)
    assert sr.main(["update"]) == 0
    assert calls.get("ran") is True
    assert "Updating Super Research" in capsys.readouterr().out


def test_update_already_latest(bridge_port, monkeypatch, capsys):
    # On the newest published backend → say so, don't pointlessly reinstall/restart.
    monkeypatch.setattr(bridge, "_backend_version", lambda: "0.1.1")
    monkeypatch.setattr(bridge.selfupdate, "latest_on_pypi", lambda pkg, force=False: "0.1.1")
    ran = {"v": False}
    monkeypatch.setattr(bridge, "_start_backend_update", lambda: ran.__setitem__("v", True))
    assert sr.main(["update"]) == 0
    out = capsys.readouterr().out
    assert "already up to date" in out and "0.1.1" in out
    assert ran["v"] is False  # never shelled the updater


def test_update_when_backend_absent(bridge_port, monkeypatch, capsys):
    # No backend on the connected device → a clear chat error (route 404s), not a
    # crash or a silent no-op.
    def _absent():
        raise FileNotFoundError("backend_not_installed")
    monkeypatch.setattr(bridge, "_start_backend_update", _absent)
    assert sr.main(["update"]) == 1
    assert "isn't installed" in capsys.readouterr().out


def test_version_shows_update_notices(bridge_port, monkeypatch, capsys):
    # `version` surfaces a pip-style "newer available" nudge for BOTH the agent and
    # the backend (the bridge checks PyPI; cached 24h).
    monkeypatch.setattr(bridge, "_backend_version", lambda: "0.1.1")
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda: "0.1.9")
    monkeypatch.setattr(bridge.selfupdate, "backend_update_available", lambda b: "0.2.0")
    assert sr.main(["version"]) == 0
    out = capsys.readouterr().out
    assert "v0.1.9 available" in out and "update the agent" in out
    assert "v0.2.0 available" in out


def test_version_no_notices_when_current(bridge_port, monkeypatch, capsys):
    monkeypatch.setattr(bridge, "_backend_version", lambda: "0.1.1")
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda: None)
    monkeypatch.setattr(bridge.selfupdate, "backend_update_available", lambda b: None)
    assert sr.main(["version"]) == 0
    assert "available" not in capsys.readouterr().out


def test_agent_update_starts(bridge_port, monkeypatch, capsys):
    # `agent-update` (the agent's own self-update) pre-flights resolvability, spawns
    # the detached reconnect, returns 200, then the bridge restarts itself. The 200 is
    # sent before the shutdown fires, so the client sees success.
    monkeypatch.setattr(bridge.selfupdate, "agent_resolvable", lambda: True)
    monkeypatch.setattr(bridge.selfupdate, "spawn_detached_reconnect", lambda: True)
    assert sr.main(["agent-update"]) == 0
    assert "Updating the Super Research agent" in capsys.readouterr().out


def test_agent_install_alias_still_works(bridge_port, monkeypatch, capsys):
    # `agent-install` stays a back-compat alias for `agent-update`.
    monkeypatch.setattr(bridge.selfupdate, "agent_resolvable", lambda: True)
    monkeypatch.setattr(bridge.selfupdate, "spawn_detached_reconnect", lambda: True)
    assert sr.main(["agent-install"]) == 0
    assert "Updating the Super Research agent" in capsys.readouterr().out


def test_agent_update_already_latest(bridge_port, monkeypatch, capsys):
    # Agent already on the newest published version → say so, no reconnect/restart.
    monkeypatch.setattr(bridge.selfupdate, "latest_on_pypi", lambda pkg, force=False: bridge.__version__)
    spawned = {"v": False}
    monkeypatch.setattr(bridge.selfupdate, "spawn_detached_reconnect",
                        lambda: spawned.__setitem__("v", True) or True)
    assert sr.main(["agent-update"]) == 0
    out = capsys.readouterr().out
    assert "already up to date" in out and bridge.__version__ in out
    assert spawned["v"] is False  # never tore the bridge down


def test_agent_update_refuses_when_unavailable(bridge_port, monkeypatch, capsys):
    # Pre-flight fails (offline / not yet on PyPI) → REFUSE without shutting the
    # bridge down, so the user is never stranded with no chat (B2).
    monkeypatch.setattr(bridge.selfupdate, "agent_resolvable", lambda: False)
    assert sr.main(["agent-update"]) == 1
    assert "still running" in capsys.readouterr().out.lower()


def test_agent_update_helper_fails(bridge_port, monkeypatch, capsys):
    monkeypatch.setattr(bridge.selfupdate, "agent_resolvable", lambda: True)
    monkeypatch.setattr(bridge.selfupdate, "spawn_detached_reconnect", lambda: False)
    assert sr.main(["agent-update"]) == 1
    assert "pipx" in capsys.readouterr().out.lower()


def test_install_backend_starts(bridge_port, monkeypatch, capsys):
    # `install` installs the backend on the host (turning it into a research host),
    # then the chat guides the user through host-side pairing.
    monkeypatch.setattr(bridge, "_backend_cli", lambda: None)  # not yet installed
    monkeypatch.setattr(bridge.selfupdate, "spawn_detached_backend_install", lambda: True)
    assert sr.main(["install"]) == 0
    out = capsys.readouterr().out
    assert "Installing Super Research" in out and "--pair" in out


def test_install_backend_already_present(bridge_port, monkeypatch, capsys):
    monkeypatch.setattr(bridge, "_backend_cli", lambda: "/usr/local/bin/superresearch")
    assert sr.main(["install"]) == 0
    assert "already installed" in capsys.readouterr().out.lower()


def test_install_backend_helper_fails(bridge_port, monkeypatch, capsys):
    monkeypatch.setattr(bridge, "_backend_cli", lambda: None)
    monkeypatch.setattr(bridge.selfupdate, "spawn_detached_backend_install", lambda: False)
    assert sr.main(["install"]) == 1
    assert "pipx" in capsys.readouterr().out.lower()


def test_status_account_prompts_available_updates(bridge_port, monkeypatch, capsys):
    # The welcome / bare-/sr proactively nudges when an update is available.
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda: "0.1.9")
    monkeypatch.setattr(bridge.selfupdate, "backend_update_available", lambda b: "0.2.0")
    assert sr.main(["status-account"]) == 0
    out = capsys.readouterr().out
    assert "Super Research v0.2.0 is available" in out and "update" in out
    assert "Agent v0.1.9 is available" in out


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
    assert "My Podcast Run" in out  # the run title is the caption
    # #895: an explicit MEDIA:<path> tag — the gateway's AUDIO partition
    # (native playable player). A BARE path routes to document delivery
    # (the "📎 File" attachment of the 2026-07-02 live failure).
    assert re.search(r"^MEDIA:.*agent-p\.m4a$", out, re.M)
    assert "[[audio" not in out  # audio_as_voice would suppress the title text
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


def test_list_shows_all_researches(bridge_port, capsys):
    # `list` is account-wide (every status), so the user can ask for any one by name.
    FakeFS.researches = {
        "r1": {"id": "r1", "title": "EV battery market", "status": "completed", "links": {}},
        "r2": {"id": "r2", "title": "Mars colonization", "status": "ongoing", "links": {}},
    }
    assert sr.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "EV battery market" in out and "completed" in out
    assert "Mars colonization" in out and "ongoing" in out


def test_list_alias_researches(bridge_port, capsys):
    FakeFS.researches = {"r1": {"id": "r1", "title": "Reef survey", "status": "stopped", "links": {}}}
    assert sr.main(["researches"]) == 0
    assert "Reef survey" in capsys.readouterr().out


def test_list_empty_invites_a_topic(bridge_port, capsys):
    FakeFS.researches = {}
    assert sr.main(["list"]) == 0
    assert "don't have any researches" in capsys.readouterr().out.lower()


def test_stop_running_is_graceful(bridge_port, capsys):
    # `stop` (and its `cancel` alias) on a RUNNING run writes a per-run stop
    # command (keeps results + chat) — NOT the destructive queue cancel.
    FakeFS.researches["agent-x"] = {"id": "agent-x", "title": "Mars colony",
                                    "deviceId": "dev-a", "status": "ongoing"}
    assert sr.main(["cancel", "agent-x"]) == 0
    out = capsys.readouterr().out
    assert "Stopped" in out and "Mars colony" in out and "kept" in out
    assert FakeFS.last_cancel is None  # never the destructive queue cancel
    assert FakeFS.last_command == {"uid": "u1", "rid": "agent-x", "action": "stop",
                                   "device_id": "dev-a", "extra": None}
    # AUTHORITATIVE terminal flip — status:"stopped", NO `cancelled` (results+chat kept),
    # gate banner cleared — so it really stops even if the command isn't consumed.
    assert FakeFS.last_update["patch"]["status"] == "stopped"
    assert "cancelled" not in FakeFS.last_update["patch"]
    assert "pendingDecision" in FakeFS.last_update["delete_fields"]


def test_stop_queued_is_preserved(bridge_port, capsys):
    # A still-QUEUED run is preserved via ownerControl:"stop" (kept, chat intact).
    FakeFS.researches["agent-z"] = {"id": "agent-z", "deviceId": "dev-a", "status": "queued"}
    assert sr.main(["stop", "agent-z"]) == 0
    assert "Stopped" in capsys.readouterr().out
    assert FakeFS.last_command is None
    assert FakeFS.last_cancel == {"device_id": "dev-a", "research_id": "agent-z",
                                  "owner_control": "stop"}
    assert FakeFS.last_update["patch"]["status"] == "stopped"  # authoritative flip for queued too


def test_pause_is_resumable_not_terminal(bridge_port, capsys):
    # pause writes a per-run pause command and is RESUMABLE — it must NOT write the
    # authoritative terminal flip (that's stop's job).
    FakeFS.researches["agent-pz"] = {"id": "agent-pz", "title": "Reef survey",
                                     "deviceId": "dev-a", "status": "ongoing"}
    assert sr.main(["pause", "agent-pz"]) == 0
    out = capsys.readouterr().out
    assert "Paused" in out and "Reef survey" in out and "resume" in out.lower()
    assert FakeFS.last_command == {"uid": "u1", "rid": "agent-pz", "action": "pause",
                                   "device_id": "dev-a", "extra": None}
    assert FakeFS.last_update is None  # NOT a terminal flip — the run stays resumable


def test_resume_writes_resume_command(bridge_port, capsys):
    FakeFS.researches["agent-rz"] = {"id": "agent-rz", "title": "Reef survey",
                                     "deviceId": "dev-a", "status": "paused"}
    assert sr.main(["resume", "agent-rz"]) == 0
    assert "Resumed" in capsys.readouterr().out
    assert FakeFS.last_command["action"] == "resume"


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


def test_status_shows_sr_and_platform_links_but_hides_tokenized_audio(bridge_port, capsys):
    # Policy: 🔒 SR permanent shares for Brief/reports/Podcast AND 🔗 the real
    # platform links for the final Google Doc (and NotebookLM/YouTube when present).
    # The tokenized Storage audio_file URL must NEVER print into chat.
    FakeFS.researches["agent-d"] = {
        "id": "agent-d", "title": "EV market", "status": "completed", "phase": 5,
        "srShares": {"podcast": "SHARE-P", "brief": "SHARE-B", "chatgpt": "SHARE-C"},
        "links": {
            "doc": {"url": "https://docs.google.com/document/d/final", "phase": 5},
            "audio_file": {"url": "https://firebasestorage.googleapis.com/v0/b/x/o/"
                                  "a.m4a?alt=media&token=SECRET", "phase": 3},
        },
    }
    assert sr.main(["status", "agent-d"]) == 0
    out = capsys.readouterr().out
    # 🔒 permanent SR links for the brief + reports + podcast.
    assert "Phase 1 (Research Brief) complete" in out
    assert "🔒 Brief: " in out and "/shared/doc/SHARE-B" in out
    assert "/shared/doc/SHARE-C" in out      # ChatGPT report (SR share, not chatgpt.com)
    assert "/shared/podcast/SHARE-P" in out  # podcast SR share
    # 🔗 the real final Google Doc link now surfaces (shareable — opens signed out).
    assert "🔗 Google Doc: " in out and "docs.google.com/document/d/final" in out
    # But the tokenized Storage audio URL must NEVER reach chat (not in any phase plan).
    assert "token=" not in out and "firebasestorage" not in out


def test_status_no_permanent_block_when_not_delivered(bridge_port, capsys):
    # Pre-delivery runs have no srShares → no empty "Permanent links" header.
    FakeFS.researches["agent-e"] = {"id": "agent-e", "title": "WIP", "status": "ongoing",
                                    "phase": 2, "links": {}}
    assert sr.main(["status", "agent-e"]) == 0
    assert "Permanent links" not in capsys.readouterr().out


def test_status_midflight_shows_no_links_until_a_phase_completes(bridge_port, capsys):
    # A run with no phase done yet (phase 1, ongoing) surfaces NO links — a phase's
    # link (SR or platform) only appears once that phase COMPLETES. So even though
    # the incremental `links` already hold a notebooklm/doc URL, nothing is rendered.
    FakeFS.researches["agent-mid"] = {
        "id": "agent-mid", "title": "EV", "status": "ongoing", "phase": 1,
        "links": {
            "chatgpt": {"url": "https://chatgpt.com/share/RAW", "phase": 2},
            "notebooklm": {"url": "https://notebooklm.google.com/n/1", "phase": 3},
            "doc": {"url": "https://docs.google.com/document/d/RAW", "phase": 5},
        },
    }
    assert sr.main(["status", "agent-mid"]) == 0
    out = capsys.readouterr().out
    assert "🔗" not in out and "🔒" not in out
    assert "chatgpt.com" not in out and "notebooklm" not in out and "docs.google.com" not in out


# ── pipeline-config visibility: the agent can answer "is P4/P5 skipped?" ───────

def test_fmt_pipeline_config_renders_on_off():
    # videoEnabled/emailEnabled false → OFF; absent → on (matches the FE's !==false).
    s = sr._fmt_pipeline_config({"videoEnabled": False, "emailEnabled": False})[0]
    assert "P4 Video OFF" in s and "P5 Email OFF" in s
    assert "P1 Brief on" in s and "P2 Research on" in s and "P3 Podcast on" in s


def test_fmt_pipeline_config_skipped_and_agents():
    s = sr._fmt_pipeline_config(
        {"skippedPhases": [1, 3], "agents": {"chatgpt": True, "gemini": False, "claude": True}})[0]
    assert "P1 Brief OFF" in s and "P3 Podcast OFF" in s
    assert "P2 Research on (ChatGPT, Claude)" in s and "Gemini" not in s  # off agent omitted


def test_fmt_pipeline_config_all_agents_off_is_research_off():
    assert "P2 Research OFF" in sr._fmt_pipeline_config(
        {"agents": {"chatgpt": False, "gemini": False, "claude": False}})[0]


def test_fmt_pipeline_config_tolerates_skipPhases_alias():
    # Agent-start config uses skipPhases; the doc/FE use skippedPhases — read both.
    assert "P1 Brief OFF" in sr._fmt_pipeline_config({"skipPhases": [1]})[0]


def test_fmt_pipeline_config_empty_returns_nothing():
    assert sr._fmt_pipeline_config(None) == [] and sr._fmt_pipeline_config({}) == []


def test_status_includes_pipeline_config_line(bridge_port, capsys):
    # A run with video+email toggled off shows those as OFF, so the agent can answer
    # "are P4/P5 skipped?" from a fresh status (the FE toggle writes pipelineConfig).
    FakeFS.researches["agent-cfg"] = {
        "id": "agent-cfg", "title": "EV", "status": "ongoing", "phase": 2,
        "pipelineConfig": {"videoEnabled": False, "emailEnabled": False,
                           "agents": {"chatgpt": True, "gemini": True, "claude": True}},
    }
    assert sr.main(["status", "agent-cfg"]) == 0
    out = capsys.readouterr().out
    assert "⚙ Phases:" in out and "P4 Video OFF" in out and "P5 Email OFF" in out


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


def test_research_tags_chat_origin(bridge_port, monkeypatch, capsys):
    # sr.py reads the gateway's per-session env and tags the run with its origin
    # chat, so a per-chat watchdog can scope updates to this chat only.
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "-100123")
    monkeypatch.setenv("HERMES_SESSION_THREAD_ID", "")
    assert sr.main(["research", "EV market"]) == 0
    capsys.readouterr()
    rid = next(iter(FakeFS.researches))
    assert FakeFS.researches[rid]["chatOrigin"] == {"platform": "telegram", "chat_id": "-100123"}


def test_research_without_origin_env_omits_chat_origin(bridge_port, monkeypatch, capsys):
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)
    monkeypatch.delenv("HERMES_SESSION_CHAT_ID", raising=False)
    assert sr.main(["research", "No origin"]) == 0
    capsys.readouterr()
    rid = next(iter(FakeFS.researches))
    assert "chatOrigin" not in FakeFS.researches[rid]


def test_arm_stream_scoped_writes_shim(tmp_path, monkeypatch, capsys):
    # With a chat origin in the env, arm-stream writes a per-chat shim that bakes
    # the origin in + delegates to the shared watchdog, and prints the exact
    # script + job name to arm.
    (tmp_path / "sr_attention_poll.py").write_text("# watchdog\n", encoding="utf-8")
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "whatsapp")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "4477@c.us")
    monkeypatch.delenv("HERMES_SESSION_THREAD_ID", raising=False)
    import json
    assert sr.main(["--json", "arm-stream"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scoped"] is True
    assert payload["script"].startswith("sr_poll_whatsapp_") and payload["script"].endswith(".py")
    assert payload["name"].startswith("sr-stream-whatsapp_")
    assert payload["origin"] == {"platform": "whatsapp", "chat_id": "4477@c.us"}
    # the shim landed beside the watchdog and imports it with the origin baked in
    shim = (tmp_path / payload["script"]).read_text(encoding="utf-8")
    assert "import sr_attention_poll" in shim
    assert "'platform': 'whatsapp'" in shim and "'chat_id': '4477@c.us'" in shim
    assert "main(origin=ORIGIN)" in shim


def test_arm_stream_slug_matches_watchdog(tmp_path):
    # The script slug sr.py generates MUST equal the slug the watchdog derives for
    # its state file (so sr_poll_<slug>.py ↔ .sr_poll_<slug>.state.json line up).
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr_attention_poll.py"
    spec = importlib.util.spec_from_file_location("sr_poll_slug_check", path)
    poll = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(poll)
    origin = {"platform": "telegram", "chat_id": "-100123", "thread_id": "7"}
    assert sr._origin_slug(origin) == poll._origin_slug(origin)


def test_scripts_dir_deployed_layout_is_authoritative(tmp_path, monkeypatch, capsys):
    # Deployed Hermes layout: <home>/.hermes/skills/research/sr/scripts/sr.py.
    # _scripts_dir must resolve to <home>/.hermes/scripts EVEN WHEN the watchdog
    # copy isn't there yet — so a broken install yields a clean "re-run connect"
    # error (via _write_poll_shim) instead of silently writing the shim into the
    # bundle's own scripts dir (a path the cron tool rejects).
    fake = tmp_path / ".hermes" / "skills" / "research" / "sr" / "scripts" / "sr.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("# x", encoding="utf-8")
    monkeypatch.setattr(sr, "__file__", str(fake))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    assert sr._scripts_dir() == tmp_path / ".hermes" / "scripts"  # not the bundle dir
    # and arm-stream over a watchdog-less scripts dir reports the clean error
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "55")
    capsys.readouterr()
    assert sr.main(["arm-stream"]) == 1
    out = capsys.readouterr().out
    assert "agent connect" in out
    assert not list((tmp_path / ".hermes" / "scripts").glob("sr_poll_*.py"))


def test_arm_stream_unscoped_without_origin(monkeypatch, capsys):
    # No origin in the env → account-wide fallback (the shared watchdog), no shim.
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)
    monkeypatch.delenv("HERMES_SESSION_CHAT_ID", raising=False)
    import json
    assert sr.main(["--json", "arm-stream"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scoped"] is False
    assert payload["script"] == "sr_attention_poll.py" and payload["name"] == "sr-stream"


def test_arm_stream_missing_watchdog_errors(tmp_path, monkeypatch, capsys):
    # arm-stream refuses to arm if the shared watchdog isn't installed (a broken
    # connect) — it must not write a shim that would import-fail every tick.
    monkeypatch.setattr(sr, "_scripts_dir", lambda: tmp_path)  # no sr_attention_poll.py here
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "99")
    assert sr.main(["arm-stream"]) == 1
    assert "agent connect" in capsys.readouterr().out
    assert not list(tmp_path.glob("sr_poll_*.py"))


def test_unreachable_bridge_is_graceful(monkeypatch, capsys):
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", "1")  # nothing listening
    # graceful (no traceback) but a NON-zero exit so the cron detects failure
    assert sr.main(["devices"]) == 2
    assert "unreachable" in capsys.readouterr().out.lower()


def test_bad_port_env_falls_back(monkeypatch, capsys):
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", "not-a-port")
    sr.main(["devices"])  # must not crash; uses 9876 (nothing there → unreachable)
    assert "9876" in capsys.readouterr().err


# ── deep run-lookup window: older runs resolve by name (the "Rocky Port" bug) ──

def test_resolution_commands_scan_a_deep_window(bridge_port, monkeypatch, capsys):
    # status / podcast / list must scan a DEEP window so a run buried >20 back
    # (named, not active) still resolves by title — the bug where `podcast
    # "Rocky Port…"` silently found nothing and the agent improvised. End-to-end:
    # sr.py asks for _LOOKUP_LIMIT and the bridge honors it (page_size on the list).
    assert sr._LOOKUP_LIMIT == 100
    monkeypatch.setattr(bridge, "_download_podcast_audio",
                        lambda url, dest_dir, rid: (dest_dir / f"{rid}.m4a", 8))
    # 25 newer runs come first, then the target buried at index 25 — OUTSIDE the
    # old 20-window, INSIDE the new 100-window. (FakeFS slices by page_size.)
    for i in range(25):
        FakeFS.researches[f"agent-{i:02d}"] = {
            "id": f"agent-{i:02d}", "title": f"Filler {i}", "status": "completed", "links": {}}
    FakeFS.researches["agent-rocky"] = {
        "id": "agent-rocky", "title": "Rocky Port Incident", "status": "completed",
        "links": {"audio_file": {"url": "https://firebasestorage.googleapis.com/v0/b/x/o/"
                                        "a.m4a?alt=media&token=zz", "phase": 3}},
    }
    # Proof the run really is beyond the OLD window: a 20-run page wouldn't see it.
    assert "agent-rocky" not in [r["id"] for r in FakeFS(None).list_researches("u1", page_size=20)]
    # …but every by-title command now resolves it (deep window + honored cap).
    for argv in (["status", "rocky port"], ["podcast", "rocky port"]):
        FakeFS.last_page_size = None
        assert sr.main(argv) == 0, argv          # found + acted (not "No runs yet")
        assert FakeFS.last_page_size == 100, argv  # deep window, not the old 20
        assert "Rocky Port Incident" in capsys.readouterr().out, argv
    assert sr.main(["list"]) == 0
    assert "Rocky Port Incident" in capsys.readouterr().out  # also visible in the listing


def test_updates_keeps_the_shallow_window(bridge_port):
    # `updates` runs the via=agent path (per-phase SR-link minting) — it must STAY
    # at the default shallow window so it never mints across 100 runs every tick.
    sr.main(["updates"])
    assert FakeFS.last_page_size == 20


def test_updates_limit_cap_clamps_to_100(bridge_port):
    # The bridge caps ?limit so a huge value can't pull the whole account, but the
    # ceiling is now 100 (was 50) so the deep by-title window is honored end-to-end.
    sr._get("/updates?limit=100")
    assert FakeFS.last_page_size == 100
    sr._get("/updates?limit=500")          # above the cap
    assert FakeFS.last_page_size == 100    # clamped to the ceiling, not 50, not 500
    sr._get("/updates?limit=5")            # below → honored verbatim
    assert FakeFS.last_page_size == 5
