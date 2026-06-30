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


@pytest.fixture(autouse=True)
def _isolate_agent_session_write(monkeypatch):
    """On APPROVED, `_advance_remote_flow` writes the #790 agent-session row via a
    real Firestore POST (`_write_agent_session_connected`, 15s HTTP timeout). These
    tests verify only the POLL→CAPTURE transition — not that row write (it has its
    own tests) — so stub it. Without this, a slow/blocking Firestore call leaves the
    autopoll daemon mid-write past the 2s join() in
    test_autopoll_loop_captures_after_approval → an `is_alive()` flake. set_session
    runs BEFORE this call, so every capture assertion still holds."""
    monkeypatch.setattr(bridge, "_write_agent_session_connected", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _autostart_off_by_default(monkeypatch):
    """Sign-in auto-start (DG_AGENT_AUTOSTART — default ON in production) makes a
    Firestore call at capture to start a pending research server-side. Default it
    OFF for this file so the bare transition tests stay network-free + deterministic
    (they assert only the poll→capture→announce transition). The dedicated
    auto-start tests below re-enable it with a mocked FirestoreRest."""
    monkeypatch.setenv("DG_AGENT_AUTOSTART", "0")


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


def test_advance_records_signed_in_event(isolate_store, mock_fe, monkeypatch):
    """On capture (auto-start OFF — the fallback path), a one-shot 'signed in' event
    is recorded for the chat watchdog — carrying the email + any topic the user fired
    while signed out + the chat origin that started the flow (so the proactive
    announce is scoped + can offer to continue that research). The auto-start ON
    behavior is covered in the dedicated section below."""
    state = bridge.BridgeState()
    idt = make_jwt({"user_id": "u-si", "email": "si@x.y"})
    fe = mock_fe(
        poll_script=[(200, {"status": "approved", "customToken": "CT"})],
        exchange_resp={"idToken": idt, "refreshToken": "RT-si", "expiresIn": "3600"},
    )
    _point_exchange_at(monkeypatch, fe)
    flow = _pending_flow()
    flow.pending_topic = "EV battery market"
    flow.origin = {"platform": "telegram", "chat_id": "-100"}
    state.set_remote(flow)

    with state.remote_lock:
        bridge._advance_remote_flow(state)

    ev = state.signed_in
    assert ev is not None
    assert ev["email"] == "si@x.y"
    assert ev["pendingTopic"] == "EV battery market"
    assert ev["origin"] == {"platform": "telegram", "chat_id": "-100"}
    assert isinstance(ev["ts"], int)
    # A sign-out invalidates a not-yet-delivered announce.
    state.set_session(None)
    assert state.signed_in is None


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


# ── sign-in auto-start: the bridge starts a pending research server-side ───────
# A research fired while signed out used to depend on the chat agent interpreting
# a "yes" after sign-in — which kept misfiring live (the agent answered from its
# own knowledge / asked "yes to what?"). The bridge now starts it itself at the
# moment sign-in is captured, so the chat agent is off the critical path.

class _AutostartFS:
    """Minimal FirestoreRest stand-in for the sign-in auto-start path."""

    devices: list[dict] = []
    settings: dict | None = None
    enqueue_raises = False
    upserts: list[dict] = []
    enqueued: list[dict] = []
    deleted: list[str] = []
    seeded: list[str] = []

    def __init__(self, _token):
        pass

    def list_devices(self, uid):
        return [dict(d) for d in type(self).devices]

    def get_user_settings(self, uid):
        return type(self).settings

    def upsert_research(self, uid, rid, fields):
        type(self).upserts.append({"uid": uid, "rid": rid, "fields": fields})

    def enqueue_start(self, device_id, **kw):
        if type(self).enqueue_raises:
            raise bridge.FirestoreError("enqueue denied")
        type(self).enqueued.append({"device_id": device_id, **kw})
        return "Q-auto"

    def seed_chat_messages(self, uid, rid, *, topic, title):
        type(self).seeded.append(rid)

    def delete_research(self, uid, rid):
        type(self).deleted.append(rid)


@pytest.fixture()
def autostart(isolate_store, mock_fe, monkeypatch):
    """Arm sign-in auto-start with a controllable fake Firestore. Returns the fake
    class so a test sets `.devices` / `.enqueue_raises`. Re-enables the flag the
    autouse fixture defaulted off."""
    monkeypatch.setenv("DG_AGENT_AUTOSTART", "1")
    _AutostartFS.devices = []
    _AutostartFS.settings = None
    _AutostartFS.enqueue_raises = False
    _AutostartFS.upserts = []
    _AutostartFS.enqueued = []
    _AutostartFS.deleted = []
    _AutostartFS.seeded = []
    monkeypatch.setattr(bridge, "FirestoreRest", _AutostartFS)
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: None)
    # The auto-start I/O runs in a worker thread off the remote_lock; run it
    # synchronously in tests so the one-shot event is set by the time _advance returns.
    monkeypatch.setattr(bridge, "_spawn", lambda target, *args: target(*args))
    idt = make_jwt({"user_id": "u-as", "email": "as@x.y"})
    fe = mock_fe(
        poll_script=[(200, {"status": "approved", "customToken": "CT"})],
        exchange_resp={"idToken": idt, "refreshToken": "RT-as", "expiresIn": "3600"},
    )
    _point_exchange_at(monkeypatch, fe)
    return _AutostartFS


def _approve(state):
    with state.remote_lock:
        bridge._advance_remote_flow(state)


def test_autostart_fires_pending_research_when_a_node_exists(autostart):
    autostart.devices = [{"id": "d1", "name": "Laptop"}]
    state = bridge.BridgeState()
    flow = _pending_flow()
    flow.pending_topic = "Golden Retriever"
    flow.origin = {"platform": "telegram", "chat_id": "-77"}
    state.set_remote(flow)

    _approve(state)

    # Enqueued server-side — no chat round-trip, no "reply yes".
    assert len(autostart.enqueued) == 1
    assert autostart.enqueued[0]["topic"] == "Golden Retriever"
    ev = state.signed_in
    assert ev["autoStarted"] is True
    assert ev["runId"].startswith("agent-")
    assert ev["topic"] == "Golden Retriever"
    assert ev["deviceName"] == "Laptop"
    # The "reply yes" offer is suppressed + the topic consumed so login-done can't
    # double-fire it.
    assert ev["pendingTopic"] == ""
    assert state.remote.pending_topic is None
    # Tagged viaAgent + chatOrigin so the EXISTING watchdog streams it (no extra arm).
    fields = autostart.upserts[0]["fields"]
    assert fields["viaAgent"] is True
    assert fields["chatOrigin"] == {"platform": "telegram", "chat_id": "-77"}


def test_autostart_picks_the_selected_device(autostart, monkeypatch):
    autostart.devices = [{"id": "d1", "name": "Laptop"}, {"id": "d2", "name": "Office PC"}]
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: "d2")
    state = bridge.BridgeState()
    flow = _pending_flow()
    flow.pending_topic = "Mars colonization"
    state.set_remote(flow)

    _approve(state)

    assert autostart.enqueued[0]["device_id"] == "d2"
    assert state.signed_in["deviceName"] == "Office PC"


def test_autostart_signals_needs_device_when_account_has_no_node(autostart):
    autostart.devices = []  # no research node on the account
    state = bridge.BridgeState()
    flow = _pending_flow()
    flow.pending_topic = "Golden Retriever"
    state.set_remote(flow)

    _approve(state)

    assert autostart.enqueued == []  # nothing to enqueue
    ev = state.signed_in
    assert ev["needsDevice"] is True
    assert not ev.get("autoStarted")
    assert ev["topic"] == "Golden Retriever"
    assert ev["pendingTopic"] == ""  # the pair-a-node message covers it


def test_autostart_is_ambiguous_with_multiple_unselected_devices(autostart):
    autostart.devices = [{"id": "d1", "name": "A"}, {"id": "d2", "name": "B"}]
    # no selection (fixture default) → can't guess → fall back to confirm-then-run
    state = bridge.BridgeState()
    flow = _pending_flow()
    flow.pending_topic = "EV market"
    state.set_remote(flow)

    _approve(state)

    assert autostart.enqueued == []
    ev = state.signed_in
    assert not ev.get("autoStarted")
    # Topic was claimed under the lock (nulled on the flow), but re-offered via the
    # announce so the legacy "reply yes" handoff still works.
    assert ev["pendingTopic"] == "EV market"
    assert state.remote.pending_topic is None


def test_autostart_falls_back_to_reply_yes_when_enqueue_fails(autostart):
    autostart.devices = [{"id": "d1", "name": "Laptop"}]
    autostart.enqueue_raises = True
    state = bridge.BridgeState()
    flow = _pending_flow()
    flow.pending_topic = "Golden Retriever"
    state.set_remote(flow)

    _approve(state)

    ev = state.signed_in
    assert not ev.get("autoStarted")
    # Degrade to confirm-then-run: re-offered via the announce (topic was claimed).
    assert ev["pendingTopic"] == "Golden Retriever"
    assert state.remote.pending_topic is None
    assert autostart.deleted  # the orphan research doc was cleaned up


def test_autostart_disabled_by_env_uses_reply_yes(autostart, monkeypatch):
    monkeypatch.setenv("DG_AGENT_AUTOSTART", "0")
    autostart.devices = [{"id": "d1", "name": "Laptop"}]
    state = bridge.BridgeState()
    flow = _pending_flow()
    flow.pending_topic = "Golden Retriever"
    state.set_remote(flow)

    _approve(state)

    assert autostart.enqueued == []
    assert state.signed_in["pendingTopic"] == "Golden Retriever"


def test_autostart_no_pending_topic_just_confirms(autostart):
    autostart.devices = [{"id": "d1", "name": "Laptop"}]
    state = bridge.BridgeState()
    state.set_remote(_pending_flow())  # no pending_topic

    _approve(state)

    assert autostart.enqueued == []
    ev = state.signed_in
    assert not ev.get("autoStarted") and not ev.get("needsDevice")
    assert ev["pendingTopic"] == ""
