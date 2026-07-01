"""Login-verify must not misread a Cloudflare / human-verification interstitial
as "not signed in".

E2E 2026-07-01: after a real-Chrome sign-in, Claude's patchright verify pass landed
on the claude.ai Cloudflare "Performing security verification" page. That page serves
on the CANONICAL host (no /login path), so it slips past _LOGIN_HOST_NEGATIVES; vision
then reads "no authenticated app" -> a FALSE "not signed in" that nagged the user to
re-log-in an account that was actually fine (the Claude first-login-didn't-persist
symptom). A challenge is NOT a logout -- the user already signed in on the plain-Chrome
pass. _verify_platform_logins must detect the challenge and record no_check ("likely
still signed in") instead of missing, so it never forces a bogus re-login. It must
NOT bypass the challenge and must NOT swallow a genuine logout.
"""
import asyncio
import inspect

import research


class _FakeCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeTab:
    def __init__(self, url):
        self.url = url

    async def close(self):
        pass


class _FakeBrowser:
    def __init__(self, url):
        self._url = url

    async def open_isolated_tab(self, url):
        return _FakeTab(self._url)


def _run_verify(monkeypatch, *, blocked, cf_reason, url, cua_ok=True, tier="pro"):
    async def _fast_sleep(*a, **k):
        return None

    monkeypatch.setattr(research.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(research, "_async_spinner_ctx", lambda label: _FakeCtx())

    calls = {"detect": 0, "verify": 0, "tier": 0}

    async def _fake_detect(page, platform, label):
        calls["detect"] += 1
        return (blocked, cf_reason)

    async def _fake_verify(page, key, cua):
        calls["verify"] += 1
        return cua_ok

    async def _fake_tier(page, key, cua):
        calls["tier"] += 1
        return tier

    monkeypatch.setattr(research, "detect_human_verification", _fake_detect)
    monkeypatch.setattr(research, "verify_login_cua", _fake_verify)
    monkeypatch.setattr(research, "_cua_pro_tier_call", _fake_tier)

    services = [("Claude", "https://claude.ai", "claude")]
    results, flags, rows = {}, {}, []

    def _emit(name, ok, label):
        rows.append((name, ok, label))

    asyncio.run(
        research._verify_platform_logins(
            _FakeBrowser(url), services, cua_client=object(),
            results=results, emit_row=_emit, flags=flags,
        )
    )
    return results, flags, calls


def test_cloudflare_challenge_is_no_check_not_missing(monkeypatch):
    # A challenge on the canonical host -> no_check + treated as signed in
    # (fail-open), NOT missing (which would force a re-login). Vision must NOT be
    # consulted (the challenge page would read as "no app" and false-flag it).
    results, flags, calls = _run_verify(
        monkeypatch, blocked=True, cf_reason="Cloudflare", url="https://claude.ai/",
    )
    assert flags["claude"] == "no_check", flags
    assert results["claude"] is True  # not missing -> not re-login-prompted
    assert calls["verify"] == 0       # challenge short-circuits the vision call
    # It gives the challenge one beat to settle -> two detect probes.
    assert calls["detect"] == 2, calls


def test_challenge_that_clears_falls_through_to_vision(monkeypatch):
    # First probe blocked, second clears -> proceed to the normal vision check.
    async def _fast_sleep(*a, **k):
        return None

    monkeypatch.setattr(research.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(research, "_async_spinner_ctx", lambda label: _FakeCtx())
    seq = [True, False]  # blocked, then cleared
    calls = {"verify": 0}

    async def _fake_detect(page, platform, label):
        return (seq.pop(0) if seq else False, "Cloudflare")

    async def _fake_verify(page, key, cua):
        calls["verify"] += 1
        return True

    async def _fake_tier(page, key, cua):
        return "pro"

    monkeypatch.setattr(research, "detect_human_verification", _fake_detect)
    monkeypatch.setattr(research, "verify_login_cua", _fake_verify)
    monkeypatch.setattr(research, "_cua_pro_tier_call", _fake_tier)

    results, flags = {}, {}
    asyncio.run(
        research._verify_platform_logins(
            _FakeBrowser("https://claude.ai/new"),
            [("Claude", "https://claude.ai", "claude")],
            cua_client=object(), results=results, emit_row=lambda *a: None, flags=flags,
        )
    )
    assert flags["claude"] == "ok", flags
    assert calls["verify"] == 1  # cleared -> vision ran


def test_no_challenge_signed_in_is_ok(monkeypatch):
    # Regression: the new challenge probe must not perturb the happy path.
    results, flags, calls = _run_verify(
        monkeypatch, blocked=False, cf_reason="", url="https://claude.ai/new",
        cua_ok=True, tier="pro",
    )
    assert flags["claude"] == "ok", flags
    assert results["claude"] is True
    assert calls["verify"] == 1


def test_no_challenge_logged_out_is_still_missing(monkeypatch):
    # The challenge fix must NOT swallow a genuine logout: a login-host URL with
    # no challenge is still missing.
    results, flags, calls = _run_verify(
        monkeypatch, blocked=False, cf_reason="", url="https://claude.ai/login",
    )
    assert flags["claude"] == "missing", flags
    assert results["claude"] is False


def test_verify_uses_detect_human_verification_source_guard():
    # Source guard: _verify_platform_logins must reuse the shared challenge
    # detector and classify a block as no_check (never missing).
    src = inspect.getsource(research._verify_platform_logins)
    assert "detect_human_verification" in src, (
        "_verify_platform_logins must call detect_human_verification to spot a "
        "Cloudflare / human-verification interstitial before trusting a NO verdict."
    )
    assert '"no_check"' in src, (
        "a detected challenge must be recorded as no_check (likely signed in), "
        "not missing (which forces a bogus re-login)."
    )


def test_seed_settles_before_close_source_guard():
    # Cheap flush insurance: the plain-Chrome seed must settle before the graceful
    # close so a just-completed sign-in flushes to the profile cookie DB before
    # phase 2 reopens it -- on the NORMAL path only (Ctrl+C must cancel instantly).
    src = inspect.getsource(research._seed_login_plain_chrome)
    assert "asyncio.sleep" in src, (
        "the seed must settle (asyncio.sleep) after Enter and before the graceful "
        "close so a just-completed sign-in flushes to disk before phase 2 reopens."
    )
