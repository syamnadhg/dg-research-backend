import time

import pytest

from facade import session as sess_mod
from facade.session import AccountSession, RevokedError


class FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload or {}
        self.text = text
        self.content = b"x" if payload is not None else b""

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_persist(monkeypatch):
    # Don't touch the real store during session tests.
    monkeypatch.setattr(sess_mod.store, "save", lambda blob: None)
    monkeypatch.setattr(sess_mod.store, "clear", lambda: None)


def test_id_token_returns_cached_when_unexpired(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    s = AccountSession(uid="u", email="e", refresh_token="RT",
                       id_token="ID-CACHED", expires_at=time.time() + 1000)
    assert s.id_token() == "ID-CACHED"
    assert called["n"] == 0  # no refresh


def test_refresh_rotates_and_updates(monkeypatch):
    resp = FakeResp(200, {
        "refresh_token": "RT-NEW", "id_token": "ID-NEW",
        "expires_in": "3600", "user_id": "u",
    })
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: resp)
    s = AccountSession(uid="u", email="e", refresh_token="RT-OLD",
                       id_token=None, expires_at=0.0)
    assert s.id_token() == "ID-NEW"
    assert s._refresh_token == "RT-NEW"  # rotated
    assert s._expires_at > time.time()


def test_force_refresh_bypasses_cache(monkeypatch):
    resp = FakeResp(200, {"refresh_token": "RT2", "id_token": "ID-FORCED",
                          "expires_in": "3600", "user_id": "u"})
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return resp
    monkeypatch.setattr(sess_mod.requests, "post", fake_post)
    # cached + unexpired, but force=True must still refresh
    s = AccountSession(uid="u", email="e", refresh_token="RT1",
                       id_token="ID-CACHED", expires_at=time.time() + 1000)
    assert s.id_token() == "ID-CACHED" and calls["n"] == 0
    assert s.id_token(force=True) == "ID-FORCED" and calls["n"] == 1


def test_revoked_refresh_raises(monkeypatch):
    resp = FakeResp(400, {"error": {"message": "INVALID_REFRESH_TOKEN"}}, text="bad")
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: resp)
    s = AccountSession(uid="u", email="e", refresh_token="RT", id_token=None, expires_at=0.0)
    with pytest.raises(RevokedError):
        s.id_token()


def test_generic_http_error_raises_runtime(monkeypatch):
    resp = FakeResp(500, {}, text="server boom")
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: resp)
    s = AccountSession(uid="u", email="e", refresh_token="RT", id_token=None, expires_at=0.0)
    with pytest.raises(RuntimeError):
        s.id_token()


def test_from_capture_sets_fields(monkeypatch):
    saved = {}
    monkeypatch.setattr(sess_mod.store, "save", lambda blob: saved.update(blob))
    s = AccountSession.from_capture(
        refresh_token="RT", id_token="ID", uid="u9", email="z@z.z", expires_in=3600,
    )
    assert s.uid == "u9" and s.email == "z@z.z"
    assert saved == {"uid": "u9", "email": "z@z.z", "refresh_token": "RT"}
    # cached token used immediately, no network
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not refresh")))
    assert s.id_token() == "ID"
