"""#896 — Claude's setup-time Cloudflare wall must surface as an HONEST
human-verification card (with real-Chrome trust-building guidance), never as
the generic "didn't start" card, and the pipeline must never report a
Cloudflare clear that is really the challenge's re-issue gap.

Live evidence (backend-2.log 2026-07-02, 18:57 + 20:37 runs): Claude's IN-APP
Cloudflare gate appeared MID-setup. The parent shell reads "Performing
security verification" while the "Verify you are human" checkbox text lives
inside the cross-origin Turnstile iframe — invisible to body.innerText — so
detect_human_verification missed it, the 8-iter CUA fallback correctly
refused the checkbox, attach+paste both failed on the walled page (Composer
absent; Clipboard API blocked by the challenge's permissions policy), and the
user got the misleading generic card. Separately: Cloudflare's checkbox is a
browser ATTESTATION — the automation window fails it, so the challenge
re-issues after every click there (an endless loop for the user), and only
real-Chrome sign-ins (the login command) build the trust that stops the
challenge from being issued at all.

Also #898a (login walk, pair-style) + #898b (graceful profile-Chrome kills).
"""
import inspect

import research

MODSRC = inspect.getsource(research)


# ── detector: the in-app Cloudflare gate is now visible ──────────────────────

def test_detector_knows_the_parent_shell_marker():
    src = inspect.getsource(research.detect_human_verification)
    assert "performing security verification" in src, (
        "the parent-shell text of Claude's in-app Cloudflare gate must be a marker — "
        "the checkbox text itself is inside the cross-origin iframe"
    )


def test_parent_shell_marker_is_scoped_to_claude_without_composer():
    # Review catch: the phrase is generic English that can appear in research
    # CONTENT (security-topic brief in a composer, a NotebookLM notebook named
    # after the topic) — and only Claude sits behind Cloudflare. The marker
    # must require platform==claude AND the composer to be unmounted.
    src = inspect.getsource(research.detect_human_verification)
    assert "platformKey === 'claude'" in src
    assert 'contenteditable' in src, "composer-absence must gate the phrase match"


# ── _hv_fail_copy: honest, reason-aware card copy ─────────────────────────────

def test_cloudflare_copy_is_short_hands_off_and_login_free():
    # 2026-07-09 (user): the Cloudflare HV copy is short + to the point, says
    # the wall can't be cleared from here, and does NOT mention the login
    # command (it isn't the right fix for a Cloudflare wall).
    title, details = research._hv_fail_copy("Claude", "Cloudflare")
    assert "Cloudflare" in title
    assert "login command" not in details.lower()
    assert "cleared from here" in details, "state it can't be solved in the automation window"
    assert "resumes automatically" in details
    assert len(details) < 200, "keep it to the point"


def test_non_cloudflare_copy_is_hands_off_no_retry():
    # Gap #1 + HV never-solve (user directive 2026-07-15): HV == Cloudflare ==
    # the same — non-Cloudflare walls (reCAPTCHA/hCaptcha/Claude-HV) are now
    # ALSO hands-off / Skip-only. A Retry would re-navigate the walled tab and
    # raise the bot score, so the copy no longer tells the user to "Retry"
    # (adversarial finding #6, 2026-07-15). The user can still solve it by hand
    # and re-run.
    title, details = research._hv_fail_copy("chatgpt", "reCAPTCHA")
    assert "reCAPTCHA" in details
    assert "Retry" not in details, "unified hands-off: no in-place Retry on any wall"
    assert "re-run" in details


def test_copy_uses_proper_platform_display_names():
    title, _ = research._hv_fail_copy("chatgpt", "Cloudflare")
    assert "ChatGPT" in title and "Chatgpt" not in title


# ── hv_blocked: sticky wall verdict on PipelineControls ───────────────────────

def test_controls_have_hv_blocked_and_reset_clears_it():
    c = research.PipelineControls()
    assert c.hv_blocked == {}
    c.hv_blocked["claude"] = "Cloudflare"
    c.reset()
    assert c.hv_blocked == {}, "reset() must clear the wall verdicts between runs"


def test_fresh_clean_nav_drops_the_stale_verdict():
    # A hard Retry that lands clean must not let last run's verdict mislabel
    # a later unrelated failure.
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    assert "hv_blocked.pop(platform_l, None)" in src


# ── fail paths route to the HV card before the generic/login-wall cards ──────

def test_paste_fail_paths_probe_for_a_wall_first():
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    assert src.count("_hv_setup_fail_card(") >= 2, (
        "both the attach+paste and the paste-only CRITICAL paths must probe for a wall "
        "before emitting the generic 'couldn't send the brief' card"
    )


def test_outer_agent_fail_paths_probe_hv_before_login_wall():
    # 2A + 2B: the HV probe is more specific than the #893 login-wall probe
    # and must run first (a Cloudflare page is not a "signed out" page).
    for probe, wall in ((' _hv_setup_fail_card(browser, chatgpt_page, "chatgpt", "2A")',
                         '_page_shows_login_wall(chatgpt_page)'),
                        (' _hv_setup_fail_card(browser, claude_page, "claude", "2B")',
                         '_page_shows_login_wall(claude_page)')):
        assert probe.strip() in MODSRC.replace("await ", " ").replace("  ", " ") or \
               probe.strip().replace(" _hv", "_hv") in MODSRC, f"missing outer probe: {probe}"
    assert MODSRC.index('_hv_setup_fail_card(browser, claude_page') < MODSRC.index(
        '_page_shows_login_wall(claude_page)')
    assert MODSRC.index('_hv_setup_fail_card(browser, chatgpt_page') < MODSRC.index(
        '_page_shows_login_wall(chatgpt_page)')


def test_gemini_outer_fail_path_skips_wall_probe_when_hv_known():
    assert '"gemini" not in _controls.hv_blocked' in MODSRC


# ── wait_for_verification_clearance: no false clears, honest tier-5 copy ─────

def test_every_tier_uses_the_settled_clear_probe():
    src = inspect.getsource(research.wait_for_verification_clearance)
    # tier 0 (playwright click), tier 1 (CUA in place), cooldown retry,
    # kill-tab, and BOTH tier-5 poll checks (resume-verify + auto-clear).
    assert src.count("_settled_clear()") >= 6, (
        "a Cloudflare 'clear' must survive the second probe everywhere — a single "
        "probe can land in the re-issue gap and report a false clear"
    )


def test_cleared_paths_drop_the_hv_blocked_verdict():
    src = inspect.getsource(research.wait_for_verification_clearance)
    assert src.count("_mark_cleared()") >= 5


def test_tier5_cloudflare_copy_is_short_and_hands_off():
    # 2026-07-06 hands-off directive + 2026-07-09 (user): the copy is short and
    # to the point — it says the wall can't be cleared from here (touching it
    # only makes Cloudflare ask harder) and that Skip is the move, and it must
    # NOT tell the user to run the login command (not the right fix for a CF wall).
    src = inspect.getsource(research.wait_for_verification_clearance)
    assert "trying only makes Cloudflare ask harder" in src
    assert "resumes automatically" in src
    # The login-command instruction is gone from the Cloudflare HV message.
    assert "builds Cloudflare's trust" not in src
    assert "run the login command on this computer later" not in src


# ── review fixes: no false clears via frozen reason / dead pages / brief text ─

def test_settled_clear_fails_closed_on_unknown_reason():
    # Review catch (major): the top probe can land in a detection gap and
    # freeze reason="" — which must be treated as UNKNOWN (double-probe),
    # never as "not Cloudflare" (single-probe fast path). 2026-07-06: the
    # fast-path check goes through the STICKY _is_cloudflare (a gap-landing
    # probe can't downgrade a confirmed Cloudflare verdict and re-open the
    # single-probe path); empty reason still lands on the double probe.
    # Functional polarity pin: test_p2_botscore_fixes.py::
    # test_functional_cloudflare_verdict_is_sticky.
    src = inspect.getsource(research.wait_for_verification_clearance)
    assert "if reason and not _is_cloudflare():" in src
    assert "nonlocal reason" in src, "later probes must refresh the frozen top-probe reason"
    assert "initial_reason" in src, "callers must be able to seed their confirmed reason"


def test_settled_clear_never_trusts_a_dead_page():
    # Review catch: a closed page probes as "no challenge" (fail-open), so a
    # kill-tab fault must not auto-clear the pause and pop the sticky verdict.
    src = inspect.getsource(research.wait_for_verification_clearance)
    assert "page.is_closed()" in src


def test_callers_seed_their_confirmed_reason():
    # check_hv_gate (P1/P3) probes right before the shared cascade and seeds its
    # confirmed reason. Gap #1 (2026-07-15): the two P2 callers no longer route
    # through the blocking cascade (hands-off + non-blocking via
    # _hv_setup_fail_card), so they no longer pass initial_reason — only the P1/P3
    # gate does now.
    assert MODSRC.count("initial_reason=") >= 1


def test_hv_card_preserves_893_cookie_trust_bookkeeping():
    # Review catch: Cloudflare can serve its challenge AT the login redirect,
    # so the HV card winning must not silently drop #893's cookie-trust flag.
    src = inspect.getsource(research._hv_setup_fail_card)
    assert "_page_shows_login_wall(page)" in src
    assert "cookie_trust_broken.add(platform_key)" in src


def test_detector_text_scan_excludes_composer_content():
    # Review catch: the paste-fail probes run while the pasted BRIEF may sit
    # in the composer — a brief quoting 'verify you are human' etc. must not
    # satisfy the text markers (#751/#752 lesson).
    src = inspect.getsource(research.detect_human_verification)
    assert "split(t).join(' ')" in src


# ── #898a: login walks profiles pair-style, no [n/total] step chrome ──────────

def test_login_flow_has_no_step_chrome():
    src = inspect.getsource(research.run_login_flow)
    assert "_setup_step(" not in src, (
        "login profiles are a walk (pair-Stage-4 style), not numbered setup steps"
    )
    assert "browser profile" in src and "detected" in src, (
        "the walk must open with the 'N browser profiles detected' intro line"
    )
    assert "f'Profile {n}'" in src, "plain per-profile header replaces the [n/total] header"


# ── #898b: profile Chromes close gracefully so sign-ins flush ─────────────────

def test_kill_chrome_for_profile_graceful_is_real_on_windows():
    src = inspect.getsource(research._kill_chrome_for_profile)
    assert '"taskkill"' in src and '"/T"' in src, (
        "Windows graceful close needs taskkill /T (WM_CLOSE to the tree)"
    )
    assert '"/F"' not in src, "no /F — that's the hard kill this path exists to avoid"
    assert "-> int" in src or "return signaled" in src, (
        "must report how many processes were signaled so callers can skip the flush wait"
    )


def test_seed_login_prekill_is_graceful_first():
    src = inspect.getsource(research._seed_login_plain_chrome)
    assert "_kill_chrome_for_profile(profile_dir, graceful=True)" in src, (
        "a hard pre-kill can drop a seconds-old sign-in before Chrome flushes it"
    )


def test_browser_start_orphan_kill_is_graceful_with_bounded_fallback():
    src = inspect.getsource(research.Browser.start)
    assert "graceful, hard-kill fallback" in src
    assert "wait_procs" in src, "hard-kill only what survives the bounded graceful window"
