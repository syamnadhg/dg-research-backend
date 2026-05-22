"""Unit tests for Track D D5c — user-mode token mint.

Originally covered three areas:
  - `_fresh_user_mode_id_token` (still active — used by other Track D
    request flows: device-patch, oauth-callback, etc.)
  - `_save_api_key_via_fe_bridge` (REMOVED — pair-time API keys now
    persist BE-local, not Firestore)
  - `_save_api_key_to_firestore` mode-branch (REMOVED — function deleted
    alongside the bridge)

The bridge tests were dropped when --pair Stage 3 moved to BE-local
persistence (Win User-scope env / .dg-supervisor.env). See
test_pair_prompt.py for the new `TestSaveApiKeyLocal` coverage.
"""

from __future__ import annotations

import importlib

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
