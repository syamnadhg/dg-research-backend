"""#893 — verification is OPT-IN everywhere (2026-07-02 bot-score work).

Live evidence that drove this: on a fresh profile the verify pass itself
sailed through (00:31:24 LOGGED IN ✓) and the Cloudflare challenge hit the
WORK page 16 seconds later — proactive verify navigations were pure extra
bot-score exposure. The batch:
  * --login runs Phase 1 only (real-Chrome sign-in; no automated verify);
  * pair Step 4 asks "Skip the verification step? [Y/n]" (default SKIP);
  * skipInitVerify defaults TRUE (BE config reads + bridge verifyLogins);
  * the phase-time gate trusts a present session cookie (zero navigations);
    #899 slimmed it further — a cookie miss now just emits an `unverified`
    tile line (no verify tab, no CUA, no pause; the phase's own work-tab
    preflight confirms sign-in on the page it actually drives);
  * the P2 inter-agent stagger is env-tunable (DG_P2_STAGGER_SEC).
"""
import re
import inspect
import types

import pytest

import research


# ── _platform_auth_cookie_present (the gate's trust-first probe) ─────────────

class _FakeCtx:
    def __init__(self, cookies):
        self._cookies = cookies

    async def cookies(self):
        return self._cookies


def _browser_with(cookies):
    return types.SimpleNamespace(context=_FakeCtx(cookies))


@pytest.mark.asyncio
async def test_cookie_probe_trusts_platform_session_cookie():
    b = _browser_with([
        {"name": "__Secure-next-auth.session-token", "domain": ".chatgpt.com",
         "value": "tok", "expires": -1},
    ])
    assert await research._platform_auth_cookie_present(b, "chatgpt") is True
    assert await research._platform_auth_cookie_present(b, "claude") is False


@pytest.mark.asyncio
async def test_cookie_probe_google_names_cover_gemini_and_notebooklm():
    b = _browser_with([
        {"name": "__Secure-1PSID", "domain": ".google.com", "value": "x", "expires": -1},
    ])
    assert await research._platform_auth_cookie_present(b, "gemini") is True
    assert await research._platform_auth_cookie_present(b, "notebooklm") is True


@pytest.mark.asyncio
async def test_cookie_probe_rejects_lookalikes_and_expired():
    import time as _t
    b = _browser_with([
        # consent/telemetry cookies Google + OpenAI set while logged OUT must
        # NOT read as a session (explicit-name matching, no loose prefixes)
        {"name": "__Secure-ENID", "domain": ".google.com", "value": "x", "expires": -1},
        {"name": "__Secure-next-auth.callback-url", "domain": ".chatgpt.com",
         "value": "x", "expires": -1},
        # right name, wrong domain
        {"name": "sessionKey", "domain": ".evil.example", "value": "x", "expires": -1},
        # right name+domain but expired / empty
        {"name": "sessionKey", "domain": ".claude.ai", "value": "x",
         "expires": _t.time() - 100},
        {"name": "__Secure-1PSID", "domain": ".google.com", "value": "", "expires": -1},
    ])
    for key in ("chatgpt", "claude", "gemini", "notebooklm"):
        assert await research._platform_auth_cookie_present(b, key) is False


@pytest.mark.asyncio
async def test_cookie_probe_failure_falls_back_to_full_gate():
    class _Boom:
        async def cookies(self):
            raise RuntimeError("context gone")
    b = types.SimpleNamespace(context=_Boom())
    assert await research._platform_auth_cookie_present(b, "chatgpt") is False


@pytest.mark.asyncio
async def test_cookie_probe_accepts_chunked_nextauth_cookie():
    # NextAuth splits >4KB session JWEs into .0/.1 chunks — those accounts
    # must still fast-path (else the verify tab quietly returns every run).
    b = _browser_with([
        {"name": "__Secure-next-auth.session-token.0", "domain": ".chatgpt.com",
         "value": "chunk", "expires": -1},
    ])
    assert await research._platform_auth_cookie_present(b, "chatgpt") is True


# ── _page_shows_login_wall (the stale-cookie failure-path tell) ──────────────

class _FakePage:
    def __init__(self, url, has_login_dom=False, raise_eval=False):
        self.url = url
        self._dom = has_login_dom
        self._raise = raise_eval

    async def evaluate(self, _js):
        if self._raise:
            raise RuntimeError("page dead")
        return self._dom


@pytest.mark.asyncio
async def test_login_wall_detects_login_host_and_anonymous_landing():
    assert await research._page_shows_login_wall(
        _FakePage("https://auth.openai.com/authorize?x=1")) is not None
    assert await research._page_shows_login_wall(
        _FakePage("https://accounts.google.com/signin/v2")) is not None
    # chatgpt serves the logged-out UI on its canonical host — DOM tell
    assert await research._page_shows_login_wall(
        _FakePage("https://chatgpt.com/", has_login_dom=True)) is not None
    # healthy work page → None; dead page eval → None (best-effort)
    assert await research._page_shows_login_wall(
        _FakePage("https://chatgpt.com/c/abc", has_login_dom=False)) is None
    assert await research._page_shows_login_wall(
        _FakePage("https://claude.ai/chat/x", raise_eval=True)) is None
    assert await research._page_shows_login_wall(None) is None


def test_gate_skips_fast_path_for_trust_broken_platforms():
    src = inspect.getsource(research._phase_verify_gate)
    assert "cookie_trust_broken" in src, (
        "a platform whose trusted cookie was falsified mid-run must not "
        "re-trust the stale jar on the post-sign-in Retry"
    )


def test_controls_track_and_reset_cookie_trust():
    src = inspect.getsource(research)
    assert "self.cookie_trust_broken: set[str] = set()" in src
    assert "self.cookie_trust_broken.clear()" in src


def test_p2_fail_paths_are_login_wall_aware():
    src = inspect.getsource(research.run_phase2)
    # 2A + 2B swap the generic "didn't start" card for the honest signed-out
    # one when the already-open page shows a login wall; 2C records the break.
    assert src.count("_page_shows_login_wall") >= 3
    assert "ChatGPT looks signed out" in src and "Claude looks signed out" in src
    assert src.count('cookie_trust_broken.add') >= 3


def test_gemini_gets_a_zero_navigation_tier_backstop():
    src = inspect.getsource(research.run_phase2)
    assert "_gemini_dom_tier(gemini_page)" in src, (
        "with verification off by default the 2C DOM tier read is Gemini's "
        "only Free-tier tell (P0 walk + gate tier checks no longer run)"
    )
    assert "phase2/setup_pro_backstop" in src


def test_gate_has_trust_first_fast_path():
    src = inspect.getsource(research._phase_verify_gate)
    assert "_platform_auth_cookie_present" in src, (
        "the phase-time gate must consult the cookie probe — a present "
        "session cookie is trusted with ZERO navigations (#893)"
    )
    # #899: the gate is a trust CHECK only — no isolated verify tab, no CUA,
    # no pause. A cookie miss emits the honest `unverified` tile line and
    # returns 'ok'; the phase's own work-tab preflight owns the real outcome
    # (probing the page the phase drives, which the throwaway tab never was).
    assert "open_isolated_tab" not in src
    assert "verify_login_cua" not in src
    assert "_cua_pro_tier_call" not in src
    assert "request_pause" not in src
    # ...including the REALISTIC re-add vectors (review): calling the
    # sibling pause helper (which pauses internally), blocking on an
    # already-armed pause, or re-emitting the login card in-gate.
    assert "_work_tab_login_pause(" not in src
    assert "wait_if_paused" not in src
    assert 'emit_event("login_required"' not in src
    assert 'status="unverified"' in src
    assert "will confirm on the work page" in src


# ── skipInitVerify defaults TRUE (config reads) ──────────────────────────────

def test_config_reads_default_skip_verification():
    src = inspect.getsource(research)
    assert 'pipeline_config.get("skipInitVerify", True)' in src, (
        "both config reads must default skipInitVerify to TRUE (opt-in verification)"
    )
    assert 'pipeline_config.get("skipInitVerify", False)' not in src


# ── login / pair verify modes ────────────────────────────────────────────────

def test_login_one_profile_supports_verify_modes():
    src = inspect.getsource(research._login_one_profile)
    assert "verify_mode" in src
    assert "Skip the verification step?" in src, "pair's ask-mode prompt"
    # default answer (Enter) must mean SKIP — user direction 2026-07-02
    assert '"verify" if ans in ("n", "no") else "skip"' in src
    # skip mode still runs the F4 security check (cookie read, no page loads)
    assert src.index('if mode == "skip"') < src.index("_verify_platform_logins")
    # skip mode records TRUTHFUL per-platform cookie presence — never a
    # blanket all-True (a closed-without-signing-in Chrome must not mint
    # green badges or a workerCount slot). The cookie read now lives in the
    # shared _probe_profile_logins helper the skip branch delegates to.
    assert "_probe_profile_logins(" in src, (
        "skip mode must delegate the truthful cookie read to _probe_profile_logins"
    )
    probe_src = inspect.getsource(research._probe_profile_logins)
    assert "_platform_auth_cookie_present(browser, _k2)" in probe_src, (
        "_probe_profile_logins must record per-platform cookie presence "
        "(never a blanket all-True)"
    )
    # the ask answer is PINNED across the [r] reopen-fix loop — re-asking let
    # a habitual Enter (default skip) defeat the re-verify the user chose
    assert "resolved_mode = mode" in src


def test_run_login_uses_phase1_only():
    src = inspect.getsource(research.run_login)
    assert 'verify_mode="skip"' in src, "--login must not run the automated verify"


def test_pair_step4_asks_with_skip_default():
    src = inspect.getsource(research._continue_pair_stages_2_to_5)
    assert src.count('verify_mode="ask"') >= 2, (
        "pair profile-1 AND the multi-profile loop must both use ask-mode"
    )


# ── P2 stagger knob ──────────────────────────────────────────────────────────

def test_p2_stagger_is_env_tunable():
    src = inspect.getsource(research.run_phase2)
    assert 'os.environ.get("DG_P2_STAGGER_SEC", "30")' in src
    # both gaps (before Claude, before Gemini) must use the knob
    assert len(re.findall(r"asyncio\.sleep\(_p2_stagger_sec\)", src)) == 2
