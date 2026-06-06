"""Live-server tests for the bridge's anti-CSRF / session-fixation defenses."""

import threading
from http.server import ThreadingHTTPServer

import pytest
import requests

from facade import bridge
from facade import store as store_mod


@pytest.fixture()
def live_bridge(monkeypatch):
    # In-memory store so nothing touches the real ~/.super-agent / keyring.
    mem = {}
    monkeypatch.setattr(store_mod, "load", lambda: mem.get("blob"))
    monkeypatch.setattr(store_mod, "save", lambda blob: mem.__setitem__("blob", dict(blob)))
    monkeypatch.setattr(store_mod, "clear", lambda: mem.pop("blob", None))

    state = bridge.BridgeState()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}", state, mem
    finally:
        httpd.shutdown()


def _good_body(state):
    return {
        "loginToken": state.login_token,
        "refreshToken": "RT-good",
        "uid": "u1",
        "email": "u@x.y",
        "expiresIn": 3600,
    }


def test_config_exposes_login_token(live_bridge):
    base, state, _ = live_bridge
    cfg = requests.get(base + "/login/config").json()
    assert cfg["loginToken"] == state.login_token
    assert cfg["apiKey"]


def test_callback_rejects_missing_token(live_bridge):
    base, state, _ = live_bridge
    body = _good_body(state)
    del body["loginToken"]
    r = requests.post(base + "/login/callback", json=body)
    assert r.status_code == 403


def test_callback_rejects_wrong_token(live_bridge):
    base, state, _ = live_bridge
    body = _good_body(state)
    body["loginToken"] = "forged"
    r = requests.post(base + "/login/callback", json=body)
    assert r.status_code == 403


def test_callback_rejects_cross_origin(live_bridge):
    base, state, _ = live_bridge
    r = requests.post(
        base + "/login/callback",
        json=_good_body(state),
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_callback_accepts_valid(live_bridge):
    base, state, mem = live_bridge
    r = requests.post(base + "/login/callback", json=_good_body(state))
    assert r.status_code == 200
    assert r.json()["uid"] == "u1"
    assert state.session is not None
    assert mem["blob"]["refresh_token"] == "RT-good"  # persisted


def test_callback_accepts_same_origin(live_bridge):
    base, state, _ = live_bridge
    # The real sign-in page posts with its own localhost origin.
    origin = f"http://localhost:{base.rsplit(':', 1)[1]}"
    r = requests.post(base + "/login/callback", json=_good_body(state), headers={"Origin": origin})
    assert r.status_code == 200


def test_rejects_bad_host_on_get_and_post(live_bridge):
    base, state, _ = live_bridge
    # DNS-rebinding: a rebound hostname carries Host: evil.com → rejected on every route.
    assert requests.get(base + "/healthz", headers={"Host": "evil.com"}).status_code == 403
    assert requests.get(base + "/login/config", headers={"Host": "evil.com"}).status_code == 403
    r = requests.post(base + "/login/callback", json=_good_body(state), headers={"Host": "evil.com:1234"})
    assert r.status_code == 403


def test_login_token_rotated_after_capture(live_bridge):
    base, state, _ = live_bridge
    first = state.login_token
    assert requests.post(base + "/login/callback", json=_good_body(state)).status_code == 200
    # The nonce is one-shot: the captured value no longer works, and a new one is live.
    assert state.login_token != first
    replay = {**_good_body(state), "loginToken": first}
    assert requests.post(base + "/login/callback", json=replay).status_code == 403


def test_callback_non_dict_body_is_clean_rejection(live_bridge):
    base, _, _ = live_bridge
    # A JSON array/scalar body must not crash the handler (AttributeError → 500);
    # it should be coerced to {} and cleanly rejected.
    r = requests.post(base + "/login/callback", json=[1, 2, 3])
    assert r.status_code in (400, 403)
    assert "error" in r.json()
