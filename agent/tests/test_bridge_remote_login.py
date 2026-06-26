"""End-to-end bridge remote-login flow against a mock FE broker (§11a).

Exercises POST /login/remote/start + /login/remote/poll, including the real
custom-token → session exchange (Identity Toolkit POST mocked at the requests
layer) so the decode + persist path runs for real.
"""

import threading
from http.server import ThreadingHTTPServer

import pytest
import requests
from _helpers import make_jwt

from facade import bridge, config
from facade import store as store_mod


@pytest.fixture()
def live(monkeypatch):
    # In-memory store so nothing touches the real ~/.super-agent / keyring.
    mem = {}
    monkeypatch.setattr(store_mod, "load", lambda: mem.get("blob"))
    monkeypatch.setattr(store_mod, "save", lambda blob: mem.__setitem__("blob", dict(blob)))
    monkeypatch.setattr(store_mod, "clear", lambda: mem.pop("blob", None))

    state = bridge.BridgeState()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", state, mem
    finally:
        httpd.shutdown()
        httpd.server_close()


def _point_exchange_at(monkeypatch, fe_base: str) -> None:
    """Route the real custom-token exchange (Identity Toolkit POST) at the mock
    FE's /identitytoolkit endpoint, so the decode + persist path runs for real
    without globally monkeypatching requests.post."""
    monkeypatch.setattr(config, "FE_BASE", fe_base)
    monkeypatch.setattr(config, "SIGN_IN_WITH_CUSTOM_TOKEN_URL", fe_base + "/identitytoolkit")


def test_remote_login_happy_path(live, mock_fe, monkeypatch):
    base, state, mem = live
    idt = make_jwt({"user_id": "u-remote", "email": "r@x.y"})
    fe = mock_fe(
        start_resp={"code": "AB-12", "pollToken": "PT", "verifyUrl": "https://superresearch.io/connect-agent", "expiresIn": 600},
        poll_script=[(200, {"status": "pending"}), (200, {"status": "approved", "customToken": "CT"})],
        exchange_resp={"idToken": idt, "refreshToken": "RT-r", "expiresIn": "3600"},
    )
    _point_exchange_at(monkeypatch, fe)

    r = requests.post(base + "/login/remote/start", json={"runtime": "hermes"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "AB-12"
    assert "pollToken" not in body  # the bearer stays server-side

    r1 = requests.post(base + "/login/remote/poll").json()
    assert r1["state"] == "pending" and r1["authed"] is False

    r2 = requests.post(base + "/login/remote/poll").json()
    assert r2["state"] == "connected" and r2["authed"] is True, f"unexpected: {r2}"
    assert r2["email"] == "r@x.y"
    assert mem["blob"]["refresh_token"] == "RT-r"
    assert state.session is not None and state.session.uid == "u-remote"


def test_poll_after_connected_is_idempotent(live, mock_fe, monkeypatch):
    base, state, _ = live
    idt = make_jwt({"user_id": "u-remote", "email": "r@x.y"})
    fe = mock_fe(
        start_resp={"code": "X", "pollToken": "PT", "verifyUrl": "https://x/c", "expiresIn": 600},
        poll_script=[(200, {"status": "approved", "customToken": "CT"})],
        exchange_resp={"idToken": idt, "refreshToken": "RT-r", "expiresIn": "3600"},
    )
    _point_exchange_at(monkeypatch, fe)
    sr = requests.post(base + "/login/remote/start", json={})
    assert sr.status_code == 200, f"start failed: {sr.status_code} {sr.text}"
    p1 = requests.post(base + "/login/remote/poll").json()
    assert p1.get("state") == "connected", f"unexpected poll body: {p1}"
    # A second poll just re-reports the terminal state; it must not re-exchange
    # (we'd 500 / error if it tried, since the script is exhausted → repeats).
    again = requests.post(base + "/login/remote/poll").json()
    assert again["state"] == "connected" and again["authed"] is True


def test_remote_poll_without_start_is_400(live):
    base, _, _ = live
    assert requests.post(base + "/login/remote/poll").status_code == 400


def test_start_stashes_pending_topic_and_origin(live, mock_fe, monkeypatch):
    """A research fired while signed out starts the sign-in carrying its topic +
    chat origin, so the post-login announce can offer to continue it (in the right
    chat)."""
    base, state, _ = live
    fe = mock_fe(start_resp={"code": "X", "pollToken": "PT", "verifyUrl": "https://x/c", "expiresIn": 600})
    monkeypatch.setattr(config, "FE_BASE", fe)
    r = requests.post(base + "/login/remote/start", json={
        "pending_topic": "the EV battery market",
        "origin": {"platform": "telegram", "chat_id": "111"},
    })
    assert r.status_code == 200
    assert state.remote.pending_topic == "the EV battery market"
    assert state.remote.origin == {"platform": "telegram", "chat_id": "111"}


def test_pending_attaches_topic_to_in_flight_flow(live, mock_fe, monkeypatch):
    """A user who started login, then fired a research before approving: the topic
    attaches to the EXISTING flow (no fresh flow that would void their link)."""
    base, state, _ = live
    fe = mock_fe(start_resp={"code": "X", "pollToken": "PT", "verifyUrl": "https://x/c", "expiresIn": 600})
    monkeypatch.setattr(config, "FE_BASE", fe)
    requests.post(base + "/login/remote/start", json={})
    same_token = state.remote.poll_token
    r = requests.post(base + "/login/remote/pending", json={
        "pending_topic": "Mars colonization", "origin": {"platform": "telegram", "chat_id": "9"},
    })
    assert r.status_code == 200 and r.json().get("ok") is True
    assert state.remote.pending_topic == "Mars colonization"
    assert state.remote.poll_token == same_token  # SAME flow — link stays valid


def test_pending_without_flow_is_409(live):
    base, _, _ = live
    r = requests.post(base + "/login/remote/pending", json={"pending_topic": "x"})
    assert r.status_code == 409


def test_remote_login_expired(live, mock_fe, monkeypatch):
    base, state, _ = live
    fe = mock_fe(
        start_resp={"code": "X", "pollToken": "PT", "verifyUrl": "https://x/c", "expiresIn": 600},
        poll_script=[(410, {})],  # broker reports the code gone
    )
    monkeypatch.setattr(config, "FE_BASE", fe)
    requests.post(base + "/login/remote/start", json={})
    r = requests.post(base + "/login/remote/poll").json()
    assert r["state"] == "expired" and r["authed"] is False
    assert state.session is None


def test_poll_past_deadline_expires_without_calling_broker(live, mock_fe, monkeypatch):
    base, state, _ = live
    # If the FE were polled it would report approved — but the bridge's own
    # deadline guard must trip first and never redeem a stale code.
    fe = mock_fe(
        start_resp={"code": "X", "pollToken": "PT", "verifyUrl": "https://x/c", "expiresIn": 600},
        poll_script=[(200, {"status": "approved", "customToken": "CT"})],
    )
    monkeypatch.setattr(config, "FE_BASE", fe)
    requests.post(base + "/login/remote/start", json={})
    state.remote.expires_at = 0.0  # force the deadline into the past
    r = requests.post(base + "/login/remote/poll").json()
    assert r["state"] == "expired" and state.session is None


def test_remote_start_broker_unreachable_is_502(live, monkeypatch):
    base, _, _ = live
    monkeypatch.setattr(config, "FE_BASE", "http://127.0.0.1:1")
    assert requests.post(base + "/login/remote/start", json={}).status_code == 502


def test_status_surfaces_inflight_remote_login(live, mock_fe, monkeypatch):
    # #848 P3: while a sign-in is mid-flight (started, not yet approved/captured),
    # /status carries `remoteLogin: "pending"` so the CLI/chat can say "approve it
    # in your browser — you'll connect automatically" instead of a bare "not
    # signed in". (The live fixture runs no serve()-owned auto-poller, so the flow
    # stays pending deterministically.)
    base, _state, _ = live
    fe = mock_fe(
        start_resp={"code": "X", "pollToken": "PT", "verifyUrl": "https://x/c", "expiresIn": 600},
        poll_script=[(200, {"status": "pending"})],
    )
    monkeypatch.setattr(config, "FE_BASE", fe)
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda: None)
    monkeypatch.setattr(bridge.selfupdate, "backend_update_available", lambda _v: None)
    monkeypatch.setattr(bridge, "_backend_version", lambda: None)

    s0 = requests.get(base + "/status").json()
    assert s0["authed"] is False and "remoteLogin" not in s0  # no flow yet
    requests.post(base + "/login/remote/start", json={})
    s1 = requests.get(base + "/status").json()
    assert s1["authed"] is False and s1["remoteLogin"] == "pending"


def test_remote_login_bad_custom_token_error_state(live, mock_fe, monkeypatch):
    base, state, _ = live
    fe = mock_fe(
        start_resp={"code": "X", "pollToken": "PT", "verifyUrl": "https://x/c", "expiresIn": 600},
        poll_script=[(200, {"status": "approved", "customToken": "CT"})],
        exchange_resp={"error": {"message": "INVALID_CUSTOM_TOKEN"}},
        exchange_status=400,
    )
    _point_exchange_at(monkeypatch, fe)
    requests.post(base + "/login/remote/start", json={})
    r = requests.post(base + "/login/remote/poll").json()
    assert r.get("state") == "error" and "error" in r, f"unexpected poll body: {r}"
    assert state.session is None and r["authed"] is False
