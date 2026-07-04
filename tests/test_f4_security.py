"""F4 security mitigation tests (DGOPS-7451).

Covers Jason's PR-review test-coverage requirement:
  - Unit: _matches_security_deny_host — subdomains match, lookalikes reject
  - Unit: _read_security_deny_hosts — env override + defaults
  - Unit: _detect_persisted_google_auth — planted cookies + platform exclusion
  - Unit: _scrub_persisted_google_auth — clears deny-host, preserves apex,
    no longer opens pages (post-cherry-pick of e992f07 / DGOPS-7451)

Browser-dependent integration / E2E tests (route handler at network
layer) deferred to follow-up — they need a live patchright context and
add ~30s to each run. The mocked-context unit tests below cover the
same cookie-iteration logic without the launch overhead.

Run via:
    pytest tests/test_f4_security.py -v
"""
import os
import sys
import pytest

# Hack: make research.py importable. The script is at the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────
# _matches_security_deny_host (pure unit)
# ─────────────────────────────────────────────────────────────────────

class TestMatchesDenyHost:
    """Subdomain matching is the load-bearing M4 defense after F4. These
    tests guard against both false negatives (incident-class hosts not
    matching) and false positives (legitimate research sources blocked)."""

    def test_exact_match(self):
        from research import _matches_security_deny_host
        # Exact apex match
        assert _matches_security_deny_host("dg-eng.com") == "dg-eng.com"

    def test_subdomain_matches(self):
        from research import _matches_security_deny_host
        # Subdomain of apex deny-host should match
        assert _matches_security_deny_host("api.dg-eng.com") == "dg-eng.com"
        assert _matches_security_deny_host("internal.distributedglobal.com") == "distributedglobal.com"

    def test_specific_incident_vector_blocked(self):
        from research import _matches_security_deny_host
        # The 2026-05-05 incident vector — must remain blocked.
        assert _matches_security_deny_host("dg-security-monitor.web.app") == "dg-security-monitor.web.app"

    def test_lookalike_rejected(self):
        from research import _matches_security_deny_host
        # Critical: webapp.com (different host) MUST NOT match web.app suffix.
        # The match function does endswith("." + pat) which prevents this,
        # but a bug in suffix-match logic could regress here.
        assert _matches_security_deny_host("webapp.com") is None
        assert _matches_security_deny_host("notdg-eng.com") is None
        assert _matches_security_deny_host("dgxeng.com") is None

    def test_empty_and_none_inputs(self):
        from research import _matches_security_deny_host
        assert _matches_security_deny_host("") is None
        assert _matches_security_deny_host(None) is None

    def test_case_insensitive(self):
        from research import _matches_security_deny_host
        assert _matches_security_deny_host("DG-ENG.COM") == "dg-eng.com"
        assert _matches_security_deny_host("Internal.DistributedGlobal.com") == "distributedglobal.com"

    def test_unrelated_research_source_passes(self):
        from research import _matches_security_deny_host
        # Legitimate research sources MUST NOT be in the deny-list.
        # The C5 fix tightened the list specifically to avoid blocking
        # these; regression test guards against re-broadening.
        assert _matches_security_deny_host("vendor-product.web.app") is None
        assert _matches_security_deny_host("openai.com") is None
        assert _matches_security_deny_host("github.io") is None
        assert _matches_security_deny_host("example.firebaseapp.com") is None


# ─────────────────────────────────────────────────────────────────────
# _read_security_deny_hosts (env override, pure unit)
# ─────────────────────────────────────────────────────────────────────

class TestReadDenyHosts:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("DG_SECURITY_DENY_HOSTS", raising=False)
        from research import _read_security_deny_hosts, _SECURITY_DENY_HOSTS_DEFAULT
        result = _read_security_deny_hosts()
        assert result == _SECURITY_DENY_HOSTS_DEFAULT

    def test_default_when_env_empty(self, monkeypatch):
        monkeypatch.setenv("DG_SECURITY_DENY_HOSTS", "   ")
        from research import _read_security_deny_hosts, _SECURITY_DENY_HOSTS_DEFAULT
        result = _read_security_deny_hosts()
        assert result == _SECURITY_DENY_HOSTS_DEFAULT

    def test_env_override_replaces_defaults(self, monkeypatch):
        monkeypatch.setenv("DG_SECURITY_DENY_HOSTS", "internal.dg.com,other-app.run.app")
        from research import _read_security_deny_hosts
        result = _read_security_deny_hosts()
        assert result == ("internal.dg.com", "other-app.run.app")
        # Defaults are NOT mixed in — env override is total.
        assert "dg-eng.com" not in result

    def test_env_override_strips_whitespace_and_lowercases(self, monkeypatch):
        monkeypatch.setenv("DG_SECURITY_DENY_HOSTS", "  Internal.DG.com  , Other.RUN.app , ")
        from research import _read_security_deny_hosts
        result = _read_security_deny_hosts()
        assert result == ("internal.dg.com", "other.run.app")

    def test_env_override_filters_empty_tokens(self, monkeypatch):
        monkeypatch.setenv("DG_SECURITY_DENY_HOSTS", ",,host1,,,host2,")
        from research import _read_security_deny_hosts
        result = _read_security_deny_hosts()
        assert result == ("host1", "host2")


# ─────────────────────────────────────────────────────────────────────
# _detect_persisted_google_auth (mocked context, async)
# ─────────────────────────────────────────────────────────────────────

class _MockContext:
    """Minimal stub of playwright BrowserContext for cookie-related tests."""

    def __init__(self, cookies):
        self._cookies = cookies
        self._cleared = []  # list of (name, domain) tuples

    async def cookies(self):
        return list(self._cookies)

    async def clear_cookies(self, name=None, domain=None):
        self._cleared.append((name, domain))
        # Simulate clearing — remove matching cookies from internal state.
        self._cookies = [
            c for c in self._cookies
            if not (
                (name is None or c.get("name") == name)
                and (domain is None or c.get("domain") == domain)
            )
        ]

    async def new_page(self):
        # If anything in the simplified scrub path tries to open a page,
        # fail loudly — the post-DGOPS-7451 scrub MUST NOT open pages.
        raise AssertionError(
            "new_page() called — _scrub_persisted_google_auth opened a "
            "page after DGOPS-7451 scrub-deletion. The post-fix function "
            "should not navigate anywhere."
        )


@pytest.mark.asyncio
class TestDetectPersistedGoogleAuth:
    async def test_no_cookies_returns_none(self):
        from research import _detect_persisted_google_auth
        ctx = _MockContext([])
        result = await _detect_persisted_google_auth(ctx)
        assert result is None

    async def test_planted_apex_google_auth_cookie_detected(self):
        from research import _detect_persisted_google_auth
        ctx = _MockContext([
            {"name": "__Secure-1PSID", "domain": ".google.com", "value": "secret-token-abc"},
            {"name": "SAPISID", "domain": ".google.com", "value": "sapi-secret"},
        ])
        result = await _detect_persisted_google_auth(ctx)
        assert result is not None
        assert result["cookieMatches"] >= 2

    async def test_platform_subdomain_cookies_excluded(self):
        from research import _detect_persisted_google_auth
        # Cookies on gemini.google.com / notebooklm.google.com / studio.youtube.com
        # are platform sessions the user paired intentionally — must NOT
        # trigger refusal during pair preflight.
        ctx = _MockContext([
            {"name": "__Secure-1PSID", "domain": "gemini.google.com", "value": "x"},
            {"name": "__Secure-1PSID", "domain": "notebooklm.google.com", "value": "x"},
            {"name": "__Secure-1PSID", "domain": "studio.youtube.com", "value": "x"},
        ])
        result = await _detect_persisted_google_auth(ctx)
        assert result is None, "Platform subdomain cookies should not trigger detection"

    async def test_non_google_cookie_ignored(self):
        from research import _detect_persisted_google_auth
        ctx = _MockContext([
            {"name": "session", "domain": "example.com", "value": "x"},
            {"name": "__Secure-1PSID", "domain": "example.com", "value": "x"},  # wrong domain
        ])
        result = await _detect_persisted_google_auth(ctx)
        assert result is None


# ─────────────────────────────────────────────────────────────────────
# _scrub_persisted_google_auth — post-DGOPS-7451 narrowed scrub
# ─────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────
# #898b — platform-session hard allow-list in the scrub
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestScrubPlatformAllowList:
    """#898b: the invariant is "worker profiles are never cleared except
    --unpair --deep". Even a misconfigured DG_SECURITY_DENY_HOSTS that
    suffix-matches a platform-session domain (e.g. a bare "google.com" or
    "claude.ai" entry) must NEVER let the scrub clear a platform cookie —
    that silently signs the worker out and resets its human-check trust.
    M4's network-layer route block stays the load-bearing F4 defense."""

    async def test_misconfigured_denylist_cannot_clear_platform_cookies(self, monkeypatch):
        import research
        from research import _scrub_persisted_google_auth
        monkeypatch.setattr(research, "_SECURITY_DENY_HOSTS",
                            ("google.com", "claude.ai", "chatgpt.com", "web.app"))
        ctx = _MockContext([
            {"name": "__Secure-1PSID", "domain": "gemini.google.com", "value": "g"},
            {"name": "sessionKey", "domain": ".claude.ai", "value": "c"},
            {"name": "session-token", "domain": ".chatgpt.com", "value": "o"},
            {"name": "auth", "domain": "dg-security-monitor.web.app", "value": "x"},
        ])
        summary = await _scrub_persisted_google_auth(ctx, scope="test")
        remaining = {c["domain"] for c in ctx._cookies}
        assert "gemini.google.com" in remaining, "platform cookie scrubbed — allow-list broken"
        assert ".claude.ai" in remaining, "platform cookie scrubbed — allow-list broken"
        assert ".chatgpt.com" in remaining, "platform cookie scrubbed — allow-list broken"
        assert "dg-security-monitor.web.app" not in remaining, (
            "the real deny-host must still be cleared — the allow-list must not disable M3"
        )
        assert summary["cookiesCleared"] == 1

    async def test_misconfigured_denylist_cannot_clear_apex_google_session(self, monkeypatch):
        # Review catch (MAJOR): the Google/YouTube session lives in APEX
        # cookies (SID / __Secure-1PSID on .google.com), not on
        # gemini.google.com — the scrub's preserve list must cover the
        # parent domains or the fix fails its own motivating scenario.
        import research
        from research import _scrub_persisted_google_auth
        monkeypatch.setattr(research, "_SECURITY_DENY_HOSTS",
                            ("google.com", "youtube.com", "web.app"))
        ctx = _MockContext([
            {"name": "SID", "domain": ".google.com", "value": "s"},
            {"name": "__Secure-1PSID", "domain": ".google.com", "value": "p"},
            {"name": "LSID", "domain": "accounts.google.com", "value": "l"},
            {"name": "VISITOR_INFO1_LIVE", "domain": ".youtube.com", "value": "y"},
            {"name": "auth", "domain": "dg-security-monitor.web.app", "value": "x"},
        ])
        summary = await _scrub_persisted_google_auth(ctx, scope="test")
        remaining = {c["domain"] for c in ctx._cookies}
        assert ".google.com" in remaining, "apex Google session cookies scrubbed — worker signed out"
        assert "accounts.google.com" in remaining
        assert ".youtube.com" in remaining
        assert "dg-security-monitor.web.app" not in remaining
        assert summary["cookiesCleared"] == 1

    async def test_scrub_preserve_stays_out_of_m2_detection(self):
        # The scrub-only list must NOT loosen M2: pair-flow second-account
        # detection still flags apex .google.com auth cookies.
        from research import _detect_persisted_google_auth
        ctx = _MockContext([
            {"name": "__Secure-1PSID", "domain": ".google.com", "value": "secret"},
        ])
        assert await _detect_persisted_google_auth(ctx) is not None

    async def test_normal_denylist_behavior_unchanged(self):
        from research import _scrub_persisted_google_auth
        ctx = _MockContext([
            {"name": "sessionKey", "domain": ".claude.ai", "value": "c"},
            {"name": "auth", "domain": "dg-security-monitor.web.app", "value": "x"},
        ])
        summary = await _scrub_persisted_google_auth(ctx, scope="test")
        assert {c["domain"] for c in ctx._cookies} == {".claude.ai"}
        assert summary["cookiesCleared"] == 1


@pytest.mark.asyncio
class TestScrubPersistedGoogleAuth:
    """Post-DGOPS-7451 the scrub:
      - Clears cookies on internal-infra deny-list hosts ONLY
      - Does NOT open any page (storage scrub deleted)
      - Does NOT touch Google domains
    These tests are the CI-enforced contract Jason asked for in C2."""

    async def test_clears_deny_host_cookies(self):
        from research import _scrub_persisted_google_auth
        ctx = _MockContext([
            {"name": "auth", "domain": "dg-security-monitor.web.app", "value": "x"},
            {"name": "session", "domain": ".dg-eng.com", "value": "y"},
            {"name": "csrf", "domain": "internal.distributedglobal.com", "value": "z"},
        ])
        summary = await _scrub_persisted_google_auth(ctx, scope="test")
        assert summary["cookiesCleared"] == 3
        # All deny-host cookies are gone post-scrub.
        remaining_domains = [c["domain"] for c in ctx._cookies]
        assert all("dg-eng" not in d and "distributedglobal" not in d
                   and "dg-security-monitor" not in d for d in remaining_domains)

    async def test_preserves_apex_google_cookies(self):
        """The bug we just fixed: scrub MUST NOT touch apex .google.com
        cookies. Wiping them broke Gemini/NotebookLM/YouTube login on
        every run — the regression that prompted DGOPS-7451 fix."""
        from research import _scrub_persisted_google_auth
        ctx = _MockContext([
            {"name": "__Secure-1PSID", "domain": ".google.com", "value": "apex-token"},
            {"name": "SAPISID", "domain": ".google.com", "value": "sapi-token"},
            {"name": "session", "domain": ".dg-eng.com", "value": "x"},  # this gets cleared
        ])
        summary = await _scrub_persisted_google_auth(ctx, scope="test")
        # Only the deny-host cookie cleared; apex Google cookies preserved.
        assert summary["cookiesCleared"] == 1
        remaining_names = [c["name"] for c in ctx._cookies]
        assert "__Secure-1PSID" in remaining_names
        assert "SAPISID" in remaining_names

    async def test_no_page_opened(self):
        """Post-DGOPS-7451 the scrub must NOT navigate to any URL. The
        previous storage-wipe path opened https://accounts.google.com/__f4_scrub_404
        and ran localStorage.clear() — that's deleted. _MockContext.new_page()
        raises AssertionError if called, so this test fails loud if a
        future regression re-introduces the storage scrub."""
        from research import _scrub_persisted_google_auth
        ctx = _MockContext([
            {"name": "auth", "domain": ".dg-eng.com", "value": "x"},
        ])
        # If the scrub opens a page, _MockContext.new_page() raises and
        # this call would fail. Reaching the assert below means clean.
        summary = await _scrub_persisted_google_auth(ctx, scope="test")
        assert summary["originsCleared"] == 0  # field preserved, always 0 now

    async def test_no_google_cookies_cleared(self):
        """Mirror of preserve-apex but expressed as "the scrub never
        touches *.google.com" — defensive check that the cookie-iteration
        logic doesn't accidentally include Google domains."""
        from research import _scrub_persisted_google_auth
        ctx = _MockContext([
            {"name": "X", "domain": "accounts.google.com", "value": "a"},
            {"name": "Y", "domain": "myaccount.google.com", "value": "b"},
            {"name": "Z", "domain": ".google.com", "value": "c"},
            {"name": "W", "domain": "gemini.google.com", "value": "d"},
        ])
        summary = await _scrub_persisted_google_auth(ctx, scope="test")
        assert summary["cookiesCleared"] == 0
        # Every Google cookie still present.
        assert len(ctx._cookies) == 4

    async def test_empty_cookies_clean(self):
        from research import _scrub_persisted_google_auth
        ctx = _MockContext([])
        summary = await _scrub_persisted_google_auth(ctx, scope="test")
        assert summary["cookiesCleared"] == 0
        assert summary["originsCleared"] == 0
        assert summary["errors"] == []
