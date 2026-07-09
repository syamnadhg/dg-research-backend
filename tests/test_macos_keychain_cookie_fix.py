"""Regression guard for the macOS login-profile bug (2026-07-09).

THE BUG (macOS-only; Windows was fine):
  The plain-Chrome sign-in (_seed_login_plain_chrome, launched via `open` so it is
  the user's REAL Chrome) encrypts its cookies with the macOS login-Keychain key
  "Chrome Safe Storage". But Browser.start opens the SAME profile with patchright
  (channel="chrome"), and patchright/Playwright inject `--use-mock-keychain` by
  default. That swaps in a MOCK encryption key, so the automated Chrome cannot
  decrypt the seed's cookies — it drops them and rewrites the jar empty. Net
  effect: verify + every research run reopen the profile the user signed into but
  read it as SIGNED-OUT, and the saved session is wiped. Windows was unaffected
  because Windows cookies use DPAPI, which --use-mock-keychain does not touch.

  On-device proof (Chrome 150, Terminal AND launchd): seed writes N cookies; the
  reopen with --use-mock-keychain reads 0 and wipes the jar; dropping the flag
  reads them back decrypted and preserves them.

THE FIX: Browser.start passes ignore_default_args=["--use-mock-keychain"] on macOS
  so the automated Chrome uses the SAME real Keychain key as the seed. Real
  (non-automated) Chrome never sets that flag, so this is also better for stealth.
  Scoped to Darwin so Windows/Linux launch is byte-for-byte unchanged.

Run: pytest tests/test_macos_keychain_cookie_fix.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


class _StopAtLaunch(Exception):
    """Raised by the fake launcher after we've captured its kwargs, so
    Browser.start never reaches the post-launch page/clipboard/route wiring."""


def _install_fake_patchright(monkeypatch, captured):
    """Inject a fake `patchright.async_api` whose launch_persistent_context records
    the kwargs Browser.start passes, then aborts via _StopAtLaunch."""

    class _FakeChromium:
        async def launch_persistent_context(self, **kwargs):
            captured.update(kwargs)
            captured["_called"] = True
            raise _StopAtLaunch()

    class _FakePlaywright:
        def __init__(self):
            self.chromium = _FakeChromium()

    class _FakeAPW:
        async def start(self):
            return _FakePlaywright()

    mod = types.ModuleType("patchright.async_api")
    mod.async_playwright = lambda: _FakeAPW()
    monkeypatch.setitem(sys.modules, "patchright", types.ModuleType("patchright"))
    monkeypatch.setitem(sys.modules, "patchright.async_api", mod)


def _run_start_capture(monkeypatch, tmp_path, platform):
    monkeypatch.setattr(sys, "platform", platform)
    captured: dict = {}
    _install_fake_patchright(monkeypatch, captured)
    browser = research.Browser(str(tmp_path / "browser-profile"))
    with pytest.raises(_StopAtLaunch):
        asyncio.run(browser.start())
    assert captured.get("_called"), "launch_persistent_context was not reached"
    return captured


# ── Behavioural: the real Browser.start launch kwargs ──────────────────

def test_macos_drops_mock_keychain(monkeypatch, tmp_path):
    kw = _run_start_capture(monkeypatch, tmp_path, "darwin")
    assert kw.get("channel") == "chrome", "run must use the real Chrome channel"
    assert kw.get("ignore_default_args") == ["--use-mock-keychain"], (
        "on macOS Browser.start MUST drop --use-mock-keychain so the automated "
        "Chrome decrypts cookies with the SAME real Keychain key the plain-Chrome "
        "seed used — otherwise every run/verify reads the signed-in profile as "
        "signed-out and wipes the saved session."
    )


def test_non_macos_launch_is_unchanged(monkeypatch, tmp_path):
    # Windows/Linux cookies use DPAPI / the password-store, NOT the macOS Keychain,
    # and they already work — the launch must NOT gain an ignore_default_args
    # override there (byte-for-byte unchanged from before the fix).
    for plat in ("win32", "linux"):
        kw = _run_start_capture(monkeypatch, tmp_path, plat)
        assert "ignore_default_args" not in kw, (
            f"{plat} launch must be unchanged (no --use-mock-keychain override)"
        )
        assert kw.get("channel") == "chrome"


# ── Source guard: the fix + rationale stay put (repo convention) ───────

def test_fix_present_darwin_scoped_and_documented():
    src = inspect.getsource(research.Browser.start)
    assert "ignore_default_args" in src and "use-mock-keychain" in src, (
        "Browser.start must drop --use-mock-keychain via ignore_default_args."
    )
    assert 'sys.platform == "darwin"' in src, (
        "the mock-keychain drop must be Darwin-scoped so Windows/Linux are untouched."
    )
    assert "Keychain" in src, (
        "the WHY (macOS Chrome Safe Storage / Keychain cookie encryption) must be "
        "documented at the fix so it is not 'cleaned up' later."
    )


def test_browser_start_logs_profile_and_keychain_state():
    # Instrumentation invariant: backend.log alone must be able to root-cause a
    # profile/keychain mismatch (resolved dir, HOME, worker, real_keychain flag).
    src = inspect.getsource(research.Browser.start)
    assert "[browser] launch" in src and "real_keychain=" in src, (
        "Browser.start must log the resolved profile_dir, home, worker, and whether "
        "the macOS real-Keychain fix is active."
    )
