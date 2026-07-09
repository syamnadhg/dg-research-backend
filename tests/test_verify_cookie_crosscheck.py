"""Regression guard: Stage-4 verify must catch a genuinely-logged-out platform
even when the navigation/vision layer is blinded (Cloudflare interstitial, or no
API key for the vision check) — WITHOUT nagging a real session a challenge hid,
and WITHOUT misreading an unreadable jar as a logout.

THE BUG (2026-07-09, live during pair): profile 1's claude.ai jar held only a
`pendingLogin` cookie (NO `sessionKey` — the Claude login never completed), yet
Stage-4 verify PASSED Claude as signed-in. `_verify_platform_logins` hit a
Cloudflare challenge on claude.ai, recorded status="no_check" ("you're likely
still signed in"), and `results[key] = (status != "missing")` counted that as
signed-in. So a logged-out Claude was silently accepted and the user was never
prompted to finish signing in. Same fail-open hole when there's no API key.

THE FIX: in the no_check branches, read the cookie jar and cross-check the
reliable host-only auth cookie (_auth_cookie_present_in / _PHASE_GATE_AUTH_COOKIES).
  cookie AFFIRMATIVELY absent  -> downgrade to "missing" (not signed in)
  cookie present               -> keep no_check (don't nag a hidden real session)
  jar unreadable (probe error) -> keep no_check (tri-state: unknown != absent)

Run: pytest tests/test_verify_cookie_crosscheck.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

_FUTURE = 9999999999  # expires far in the future (persistent, non-expired)


def _claude_cookie(name):
    return {"domain": ".claude.ai", "name": name, "value": "x", "expires": _FUTURE}


class _FakeTab:
    def __init__(self, url):
        self.url = url

    async def close(self):
        pass


class _FakeContext:
    def __init__(self, cookies, raise_on_read=False):
        self._cookies = cookies
        self._raise = raise_on_read

    async def cookies(self):
        if self._raise:
            raise RuntimeError("context closed")
        return self._cookies


class _FakeBrowser:
    def __init__(self, cookies, url="https://claude.ai/", raise_on_read=False):
        self.context = _FakeContext(cookies, raise_on_read)
        self._url = url

    async def open_isolated_tab(self, url):
        return _FakeTab(self._url)


def _run_verify(monkeypatch, *, blocked, cookies, cua_client, url="https://claude.ai/",
                raise_on_read=False, key="claude"):
    async def _noop(*a, **k):
        return None

    async def _dhv(page, platform, label):
        return (blocked, "Cloudflare")

    monkeypatch.setattr(research.asyncio, "sleep", _noop)
    monkeypatch.setattr(research, "detect_human_verification", _dhv)

    services = [s for s in research._LOGIN_SERVICES if s[2] == key]
    assert services, f"{key} must be a known login service"
    results, flags = {}, {}
    asyncio.run(research._verify_platform_logins(
        _FakeBrowser(cookies, url=url, raise_on_read=raise_on_read),
        services, cua_client, results=results, emit_row=lambda *a, **k: None, flags=flags))
    return results[key], flags[key]


# ── Cloudflare-blocked branch ──────────────────────────────────────────

def test_cloudflare_block_no_session_cookie_reports_missing(monkeypatch):
    # profile-1 Claude case: jar has pendingLogin but NO sessionKey.
    signed_in, flag = _run_verify(
        monkeypatch, blocked=True, cua_client=None,
        cookies=[_claude_cookie("pendingLogin")])
    assert flag == "missing" and signed_in is False, (
        "Cloudflare-blocked + no session cookie must be 'missing', not accepted."
    )


def test_cloudflare_block_with_session_cookie_stays_no_check(monkeypatch):
    signed_in, flag = _run_verify(
        monkeypatch, blocked=True, cua_client=None,
        cookies=[_claude_cookie("sessionKey")])
    assert flag == "no_check" and signed_in is True, (
        "Cloudflare-blocked WITH a live sessionKey must stay no_check (don't nag)."
    )


def test_cloudflare_block_unreadable_jar_stays_no_check(monkeypatch):
    # Tri-state: a jar we cannot read is UNKNOWN, not absent — keep fail-open.
    signed_in, flag = _run_verify(
        monkeypatch, blocked=True, cua_client=None, cookies=[], raise_on_read=True)
    assert flag == "no_check" and signed_in is True, (
        "an unreadable cookie jar must NOT be misread as a logout (stay no_check)."
    )


# ── No-API-key branch (no vision check) ────────────────────────────────

def test_no_apikey_no_session_cookie_reports_missing(monkeypatch):
    signed_in, flag = _run_verify(
        monkeypatch, blocked=False, cua_client=None,
        cookies=[_claude_cookie("pendingLogin")])
    assert flag == "missing" and signed_in is False, (
        "no API key + no session cookie must be 'missing', not fail-open no_check."
    )


def test_no_apikey_with_session_cookie_stays_no_check(monkeypatch):
    signed_in, flag = _run_verify(
        monkeypatch, blocked=False, cua_client=None,
        cookies=[_claude_cookie("sessionKey")])
    assert flag == "no_check" and signed_in is True, (
        "no API key but a live sessionKey stays no_check (signed in)."
    )


# ── Source guard ───────────────────────────────────────────────────────

def test_verify_crosschecks_auth_cookie_in_no_check_branches():
    src = inspect.getsource(research._verify_platform_logins)
    assert "_auth_cookie_present_in" in src and "_has_auth_cookie" in src, (
        "verify must cross-check the auth cookie to disambiguate no_check."
    )
    assert "is False" in src, (
        "downgrade to 'missing' only on an AFFIRMATIVE cookie-absent (is False), "
        "never on unknown/probe-error (keep prior fail-open no_check)."
    )
