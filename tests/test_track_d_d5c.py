"""Unit tests for Track D D5c — user-mode FE bridge for API key saves.

Covers `_save_api_key_via_fe_bridge` HTTP paths and the `_save_api_key_to_firestore`
mode-branch. The mode-branch is small but it's the seam between legacy
(direct Firestore write) and user-mode (FE bridge), and the real risk is
silently picking the wrong branch.

Heavy mocking: keystore, RefreshTokenCredentials, requests.post.
"""

from __future__ import annotations

import importlib

import requests
import pytest

# Import via importlib so we can reload between tests if needed
research = importlib.import_module("research")


# ─── _fresh_user_mode_id_token ────────────────────────────────────────


class TestFreshUserModeIdToken:
    def test_returns_none_when_keystore_empty(self, monkeypatch):
        # Stub the keystore.try_recover() to return None (no creds saved).
        from auth import keystore as ks
        monkeypatch.setattr(ks, "install_uuid", lambda: "fake-uuid")
        monkeypatch.setattr(ks, "try_recover", lambda _: None)
        assert research._fresh_user_mode_id_token() is None

    def test_returns_token_on_successful_refresh(self, monkeypatch):
        from auth import keystore as ks, credentials as creds_mod
        monkeypatch.setattr(ks, "install_uuid", lambda: "fake-uuid")
        monkeypatch.setattr(ks, "try_recover", lambda _: "stored-refresh-token")

        class FakeCreds:
            token = "fake-id-token"
            def __init__(self, *_args, **_kwargs):
                pass
            def refresh(self, _request):
                self.token = "fake-id-token"

        monkeypatch.setattr(creds_mod, "RefreshTokenCredentials", FakeCreds)
        assert research._fresh_user_mode_id_token() == "fake-id-token"

    def test_returns_none_on_revoked(self, monkeypatch):
        from auth import keystore as ks, credentials as creds_mod
        monkeypatch.setattr(ks, "install_uuid", lambda: "fake-uuid")
        monkeypatch.setattr(ks, "try_recover", lambda _: "stored-refresh-token")
        cleared = {"called": False}
        def fake_clear(_iuid):
            cleared["called"] = True
        monkeypatch.setattr(ks, "clear_all", fake_clear)

        class FakeCreds:
            def __init__(self, *_args, **_kwargs):
                pass
            def refresh(self, _request):
                raise creds_mod.RevokedError("INVALID_REFRESH_TOKEN")

        monkeypatch.setattr(creds_mod, "RefreshTokenCredentials", FakeCreds)
        assert research._fresh_user_mode_id_token() is None
        # Defense-in-depth: keystore should be wiped on revoked-token signal.
        assert cleared["called"]


# ─── _save_api_key_via_fe_bridge ──────────────────────────────────────


def _make_resp(status: int, body: dict | str = ""):
    class FakeResp:
        status_code = status
        text = body if isinstance(body, str) else ""
        def json(self):
            if isinstance(body, dict):
                return body
            raise ValueError("not JSON")
    return FakeResp()


class TestSaveApiKeyViaFeBridge:
    def test_success_returns_true(self, monkeypatch):
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")

        captured = {}
        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers", {})
            captured["body"] = kwargs.get("json", {})
            return _make_resp(200, {"ok": True})

        monkeypatch.setattr(requests, "post", fake_post)
        assert research._save_api_key_via_fe_bridge("anthropic", "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxx") is True
        assert captured["url"].endswith("/api/devices/save-api-key")
        assert captured["headers"]["Authorization"] == "Bearer tok-abc"
        assert captured["body"]["keyName"] == "anthropic"
        assert captured["body"]["value"].startswith("sk-ant-")

    def test_no_token_returns_false_without_calling_post(self, monkeypatch):
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
        called = {"post": False}
        def fake_post(*_args, **_kwargs):
            called["post"] = True
            return _make_resp(200)
        monkeypatch.setattr(requests, "post", fake_post)
        assert research._save_api_key_via_fe_bridge("gemini", "AIzaXXXXX") is False
        # Critical: don't hit the network if the BE has no usable token.
        assert called["post"] is False

    def test_non_200_returns_false(self, monkeypatch):
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        monkeypatch.setattr(
            requests, "post",
            lambda url, **kw: _make_resp(403, {"error": "ownership_mismatch"}),
        )
        assert research._save_api_key_via_fe_bridge("anthropic", "sk-ant-aaaaaaaaaaaaaaaaaaaaaaaaa") is False

    def test_network_error_returns_false(self, monkeypatch):
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        def boom(*_args, **_kwargs):
            raise requests.ConnectionError("dns fail")
        monkeypatch.setattr(requests, "post", boom)
        assert research._save_api_key_via_fe_bridge("gemini", "AIza-xxxx-yyyy-zzzz-aaaa") is False


# ─── _save_api_key_to_firestore mode-branch ───────────────────────────


class TestSaveApiKeyAlwaysUsesBridge:
    """Post-D7: `_save_api_key_to_firestore` always delegates to the FE
    bridge — there's no legacy branch. The `uid` parameter is ignored;
    the bridge resolves the target ownerUid from the BE's custom-token
    claim server-side."""

    def test_bridge_always_called(self, monkeypatch):
        bridge_called = {"key_name": None, "value": None}
        def fake_bridge(key_name, value):
            bridge_called["key_name"] = key_name
            bridge_called["value"] = value
            return True
        monkeypatch.setattr(research, "_save_api_key_via_fe_bridge", fake_bridge)
        result = research._save_api_key_to_firestore("uid-ignored", "gemini", "AIza-xxxx-yyyy-zzzz-aaaa")
        assert result is True
        assert bridge_called["key_name"] == "gemini"
        assert bridge_called["value"].startswith("AIza")

    def test_bridge_failure_returns_false(self, monkeypatch):
        monkeypatch.setattr(research, "_save_api_key_via_fe_bridge", lambda k, v: False)
        result = research._save_api_key_to_firestore("uid", "anthropic", "sk-ant-zzz")
        assert result is False
