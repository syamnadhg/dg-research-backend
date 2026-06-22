"""serve()-owned remote-login auto-poller + the shared transition helper (#848).

The browser's /approve only PARKS the one-time custom token; the bridge must POLL
to redeem it and capture the session. Before #848 the chat path required a second
`login-done` to trigger that poll, so a user who tapped Authenticate but never ran
login-done was left at authed:false (no live agentSessions row → the Account page
never flipped "Shared by X" → "Shared With"). `_remote_autopoll_loop` closes that
gap: a long-lived daemon (mirrors `_heartbeat_loop`) advances a pending flow every
tick under remote_lock, so capture happens the instant the user approves — no
second command.

These drive `_advance_remote_flow` / `_remote_autopoll_loop` directly (the loop is
spawned only by serve(), never a request handler), against the mock FE broker.
"""

import threading
import time

import pytest
from _helpers import make_jwt

from facade import bridge, config
from facade import store as store_mod


@pytest.fixture()
def isolate_store(monkeypatch):
    """In-memory secret store so capture never touches the real keyring/disk."""
    mem: dict = {}
    monkeypatch.setattr(store_mod, "load", lambda: mem.get("blob"))
    monkeypatch.setattr(store_mod, "save", lambda blob: mem.__setitem__("blob", dict(blob)))
    monkeypatch.setattr(store_mod, "clear", lambda: mem.pop("blob", None))
    return mem


def _point_exchange_at(monkeypatch, fe_base: str) -> None:
    """Route the real custom-token exchange (Identity Toolkit POST) at the mock
    FE so the decode + persist path runs for real."""
    monkeypatch.setattr(config, "FE_BASE", fe_base)
    monkeypatch.setattr(config, "SIGN_IN_WITH_CUSTOM_TOKEN_URL", fe_base + "/identitytoolkit")


def _pending_flow(poll_token: str = "PT", ttl: float = 600.0) -> bridge.RemoteFlow:
    return bridge.RemoteFlow(
        poll_token=poll_token, code="AB-12",
        verify_url="https://superresearch.io/agent-auth", expires_at=time.time() + ttl,
    )


# ── _advance_remote_flow: the shared transition ───────────────────────────────

def test_advance_captures_on_approved(isolate_store, mock_fe, monkeypatch):
    state = bridge.BridgeState()
    idt = make_jwt({"user_id": "u-auto", "email": "a@x.y"})
    fe = mock_fe(
        poll_script=[(200, {"status": "approved", "customToken": "CT"})],
        exchange_resp={"idToken": idt, "refreshToken": "RT-a", "expiresIn": "3600"},
    )
    _point_exchange_at(monkeypatch, fe)
    state.set_remote(_pending_flow())

    with state.remote_lock:
        bridge._advance_remote_flow(state)

    assert state.remote.state == "connected"
    assert state.session is not None and state.session.uid == "u-auto"


def test_advance_is_noop_on_absent_or_terminal_flow(monkeypatch):
    """No flow, or a flow already terminal, must never hit the broker."""
    calls = {"n": 0}
    monkeypatch.setattr(bridge.devicelogin, "poll_once",
                        lambda _t: calls.__setitem__("n", calls["n"] + 1) or {"status": "pending"})

    state = bridge.BridgeState()
    with state.remote_lock:
        bridge._advance_remote_flow(state)  # state.remote is None
    flow = _pending_flow()
    flow.state = "connected"
    state.set_remote(flow)
    with state.remote_lock:
        bridge._advance_remote_flow(state)  # terminal — short-circuit
    assert calls["n"] == 0


def test_advance_reads_state_remote_fresh_not_a_stale_ref(monkeypatch):
    """The helper must operate on the CURRENT state.remote, so a flow a concurrent
    start superseded can never be the one polled/captured (supersession safety)."""
    seen: list[str] = []
    monkeypatch.setattr(bridge.devicelogin, "poll_once",
                        lambda tok: seen.append(tok) or {"status": "pending"})
    state = bridge.BridgeState()
    state.set_remote(_pending_flow(poll_token="OLD"))
    state.set_remote(_pending_flow(poll_token="NEW"))  # supersede
    with state.remote_lock:
        bridge._advance_remote_flow(state)
    assert seen == ["NEW"]  # polled the current flow, not the stale OLD reference


def test_advance_past_ttl_expires_without_broker_call(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(bridge.devicelogin, "poll_once",
                        lambda _t: calls.__setitem__("n", calls["n"] + 1) or {"status": "approved", "customToken": "CT"})
    state = bridge.BridgeState()
    flow = _pending_flow(ttl=600.0)
    flow.expires_at = 0.0  # force the deadline into the past
    state.set_remote(flow)
    with state.remote_lock:
        bridge._advance_remote_flow(state)
    assert state.remote.state == "expired" and state.session is None
    assert calls["n"] == 0  # never redeem a stale code


def test_advance_transient_stays_pending(monkeypatch):
    def boom(_t):
        raise bridge.DeviceLoginError("broker unreachable")

    monkeypatch.setattr(bridge.devicelogin, "poll_once", boom)
    state = bridge.BridgeState()
    state.set_remote(_pending_flow())
    with state.remote_lock:
        note = bridge._advance_remote_flow(state)
    assert state.remote.state == "pending" and state.session is None
    assert note  # a transient note is returned (the loop ignores it; the route attaches it)


# ── _remote_autopoll_loop: the serve()-owned daemon ───────────────────────────

def test_autopoll_loop_captures_after_approval(isolate_store, mock_fe, monkeypatch):
    """End-to-end: a pending flow + the running loop = capture with NO manual poll."""
    monkeypatch.setattr(config, "REMOTE_POLL_INTERVAL_SECONDS", 0.02)
    idt = make_jwt({"user_id": "u-loop", "email": "l@x.y"})
    fe = mock_fe(
        poll_script=[(200, {"status": "pending"}), (200, {"status": "approved", "customToken": "CT"})],
        exchange_resp={"idToken": idt, "refreshToken": "RT-l", "expiresIn": "3600"},
    )
    _point_exchange_at(monkeypatch, fe)
    state = bridge.BridgeState()
    state.set_remote(_pending_flow())

    stop = threading.Event()
    t = threading.Thread(target=bridge._remote_autopoll_loop, args=(state, stop), daemon=True)
    t.start()
    try:
        deadline = time.time() + 3.0
        while time.time() < deadline and state.session is None:
            time.sleep(0.02)
    finally:
        stop.set()
        t.join(timeout=2)
    assert not t.is_alive()
    assert state.session is not None and state.session.uid == "u-loop"
    assert state.remote.state == "connected"


def test_autopoll_loop_idle_does_no_broker_traffic(monkeypatch):
    """No pending flow → the loop must never call the broker (idle bridge silence)."""
    monkeypatch.setattr(config, "REMOTE_POLL_INTERVAL_SECONDS", 0.02)
    calls = {"n": 0}
    monkeypatch.setattr(bridge.devicelogin, "poll_once",
                        lambda _t: calls.__setitem__("n", calls["n"] + 1) or {"status": "pending"})
    state = bridge.BridgeState()  # no remote flow
    stop = threading.Event()
    t = threading.Thread(target=bridge._remote_autopoll_loop, args=(state, stop), daemon=True)
    t.start()
    time.sleep(0.15)
    stop.set()
    t.join(timeout=2)
    assert not t.is_alive()
    assert calls["n"] == 0


def test_autopoll_loop_survives_a_throwing_tick(monkeypatch):
    monkeypatch.setattr(config, "REMOTE_POLL_INTERVAL_SECONDS", 0.02)
    calls = {"n": 0}

    def boom(_state):
        calls["n"] += 1
        raise RuntimeError("tick blew up")

    monkeypatch.setattr(bridge, "_advance_remote_flow", boom)
    state = bridge.BridgeState()
    state.set_remote(_pending_flow())
    stop = threading.Event()
    t = threading.Thread(target=bridge._remote_autopoll_loop, args=(state, stop), daemon=True)
    t.start()
    time.sleep(0.15)
    stop.set()
    t.join(timeout=2)
    assert not t.is_alive()  # a throwing tick must not kill the thread
    assert calls["n"] >= 2  # it kept ticking past the first exception
