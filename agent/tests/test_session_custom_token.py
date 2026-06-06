"""AccountSession.from_custom_token — the remote device-flow exchange (§11a)."""

import pytest
from _helpers import FakeResp, make_jwt

from facade import session as sess_mod
from facade.session import AccountSession, CustomTokenError, _decode_jwt_claims


@pytest.fixture(autouse=True)
def _no_persist(monkeypatch):
    monkeypatch.setattr(sess_mod.store, "save", lambda blob: None)
    monkeypatch.setattr(sess_mod.store, "clear", lambda: None)


def test_exchange_decodes_uid_and_email(monkeypatch):
    saved = {}
    monkeypatch.setattr(sess_mod.store, "save", lambda blob: saved.update(blob))
    idt = make_jwt({"user_id": "u-remote", "email": "r@x.y"})
    resp = FakeResp(200, {"idToken": idt, "refreshToken": "RT-remote", "expiresIn": "3600"})
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: resp)

    s = AccountSession.from_custom_token("CUSTOM")
    assert s.uid == "u-remote" and s.email == "r@x.y"
    assert saved["refresh_token"] == "RT-remote"
    # cached id token used immediately, no extra refresh
    monkeypatch.setattr(sess_mod.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no refresh")))
    assert s.id_token() == idt


def test_explicit_email_overrides_claim(monkeypatch):
    idt = make_jwt({"sub": "u2", "email": "claim@x.y"})
    monkeypatch.setattr(sess_mod.requests, "post",
                        lambda *a, **k: FakeResp(200, {"idToken": idt, "refreshToken": "RT", "expiresIn": "3600"}))
    s = AccountSession.from_custom_token("CUSTOM", email="override@x.y")
    assert s.uid == "u2" and s.email == "override@x.y"


def test_rejected_custom_token_raises(monkeypatch):
    resp = FakeResp(400, {"error": {"message": "INVALID_CUSTOM_TOKEN"}}, text="bad")
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: resp)
    with pytest.raises(CustomTokenError):
        AccountSession.from_custom_token("CUSTOM")


def test_missing_tokens_raises(monkeypatch):
    resp = FakeResp(200, {"idToken": "", "refreshToken": ""})
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: resp)
    with pytest.raises(CustomTokenError):
        AccountSession.from_custom_token("CUSTOM")


def test_no_uid_in_claims_raises(monkeypatch):
    idt = make_jwt({"email": "noid@x.y"})  # no user_id / sub
    resp = FakeResp(200, {"idToken": idt, "refreshToken": "RT", "expiresIn": "3600"})
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: resp)
    with pytest.raises(CustomTokenError):
        AccountSession.from_custom_token("CUSTOM")


class _NonJsonResp:
    """A response whose .json() raises (e.g. an HTML body from a proxy)."""

    def __init__(self, status_code, text="<html>502</html>"):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text
        self.content = b"<html>502</html>"

    def json(self):
        raise ValueError("no json")


def test_non_json_success_body_raises_customtoken(monkeypatch):
    # 2xx with a non-JSON body must surface as CustomTokenError, NOT a raw
    # ValueError that would escape and wedge the bridge poll.
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: _NonJsonResp(200))
    with pytest.raises(CustomTokenError):
        AccountSession.from_custom_token("CUSTOM")


def test_non_json_error_body_raises_customtoken(monkeypatch):
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: _NonJsonResp(502))
    with pytest.raises(CustomTokenError):
        AccountSession.from_custom_token("CUSTOM")


def test_non_object_json_body_raises_customtoken(monkeypatch):
    # A valid-JSON-but-not-an-object 2xx (e.g. a list) must not AttributeError.
    monkeypatch.setattr(sess_mod.requests, "post", lambda *a, **k: FakeResp(200, [1, 2, 3]))
    with pytest.raises(CustomTokenError):
        AccountSession.from_custom_token("CUSTOM")


def test_network_error_raises(monkeypatch):
    import requests as real_requests

    def boom(*a, **k):
        raise real_requests.ConnectionError("down")
    monkeypatch.setattr(sess_mod.requests, "post", boom)
    with pytest.raises(CustomTokenError):
        AccountSession.from_custom_token("CUSTOM")


def test_decode_jwt_claims_malformed():
    assert _decode_jwt_claims("not-a-jwt") == {}
    assert _decode_jwt_claims("") == {}
    assert _decode_jwt_claims("a.!!!notbase64!!!.c") == {}
    # a valid round-trip
    assert _decode_jwt_claims(make_jwt({"user_id": "u"}))["user_id"] == "u"
