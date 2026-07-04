"""Phase-2 Gemini robustness — NEVER-reload invariant (#897a), completion
detection under the collapsed-composer UI (#897b), and the plan-generation
wait timing + Start-Research guard + alert (2B/2C).

History: a ~10-min periodic page.reload() was added 2026-05-26 because Gemini
then didn't push the completed DR panel into the live DOM without a reload.
The 2026-07 Gemini SPA no longer restores the conversation on reload AT ALL —
every reload landed on the empty "new chat" home (image-verified live
2026-07-04) — so #897a DELETED the reload and its sidebar-reopen recovery
subsystem outright. The inverse is now the invariant this file guards:
Gemini is NEVER reloaded mid-run, for any reason.

Completion under the new UI (#897b, user-confirmed live): the collapsed
composer removed the persistent bottom input box (a launcher button becomes
the input only when clicked), so "stop button lives in the composer" is no
longer a running-signal. Done-markers key on visible TEXT:
  - the report button row "Contents" · "Share & Export" · "Create"
  - the chat line "I've completed your research. Feel free to ask me
    follow-up questions or request changes."
  - "Share & Export" alone (the pre-2026-07 marker, kept)
Running-signal: guarded running-CSS-animation tier (offsetParent + playState).
"""
import inspect

import research

MODSRC = inspect.getsource(research)


# ── #897a: Gemini is NEVER reloaded mid-run ──────────────────────────────────

def test_periodic_reload_block_is_gone():
    assert "Gemini periodic refresh (every GEMINI_REFRESH_INTERVAL)" not in MODSRC, (
        "the periodic-reload block must stay deleted — reloads land on the empty home"
    )
    assert "GEMINI_REFRESH_INTERVAL_SEC" not in MODSRC
    assert "GEMINI_REFRESH_GRACE_SEC" not in MODSRC
    assert '"last_refresh"' not in MODSRC, "the reload gate state must stay deleted"


def test_reload_recovery_subsystem_is_gone():
    # Sole caller was the reload block — the whole subsystem goes with it.
    for sym in ("_gemini_recover_if_empty", "_gemini_reopen_from_sidebar",
                "_gemini_conversation_present", "_gemini_conversation_id",
                "_GEMINI_CONVERSATION_PRESENT_JS"):
        assert not hasattr(research, sym), f"{sym} should be deleted with the reload"


def test_reauth_reload_is_guarded_for_gemini():
    # The shared mid-run session-expiry Retry branch reloads the tab so the
    # fresh cookie lands — for a MOUNTED Gemini conversation that reload would
    # drop the SPA to the empty home, so it's guarded off (the cookie applies
    # on Gemini's own background requests in place). A Gemini tab redirected
    # OFF gemini.google.com (login URL) has nothing left to lose — the reload
    # is what un-sticks it, so the guard keys on the current URL, not just
    # the platform name.
    assert '_gemini_mounted = name == "Gemini" and "gemini.google.com" in _cur_url' in MODSRC
    assert "if not _gemini_mounted:" in MODSRC, (
        "the re-auth retry reload must never fire on a mounted Gemini conversation"
    )


def test_completion_re_survives_the_deletion():
    # _GEMINI_COMPLETION_RE is still used by the kickoff-stall nudge
    # suppressor — it must NOT go down with the reload subsystem.
    assert hasattr(research, "_GEMINI_COMPLETION_RE")
    assert research._GEMINI_COMPLETION_RE.search(
        "I've completed your research. Feel free to ask me follow-up questions."
    )


# ── #897b: completion detection under the collapsed-composer UI ──────────────

DETECT_SRC = inspect.getsource(research.detect_completion_gemini)


def test_detector_keys_on_report_button_trio():
    # "Contents" · "Share & Export" · "Create" together = research complete
    # (user-confirmed live 2026-07-04). Text/label match, never class selectors.
    assert "reportButtonTrio" in DETECT_SRC
    lower = DETECT_SRC.lower()
    for kw in ("'contents'", "'create'", "share & export"):
        assert kw in lower, f"trio member {kw} missing from the detector"


def test_detector_trio_members_are_exact_text():
    # EXACT text so composer tools like "Create image" can't satisfy the
    # "Create" leg and a table of contents heading can't satisfy "Contents".
    assert "txt === 'contents'" in DETECT_SRC
    assert "txt === 'create'" in DETECT_SRC


def test_detector_keys_on_completed_chat_text():
    # Gemini's own completion chat line, rendered above the report tile —
    # anchored on the exact live line, apostrophe-normalized.
    assert "i've completed your research" in DETECT_SRC


def test_completed_chat_text_cannot_be_satisfied_by_user_text():
    # Review catch (MAJOR, #752-755 lesson): the pasted brief / mid-run user
    # chat sits in user-query bubbles inside body.innerText — a brief ending
    # "…once you have completed your research, compile a table" must never
    # read as Gemini's own completion line. The scan is scoped to MODEL
    # response nodes with user-query ancestry excluded; no body-wide scan.
    assert "closest('user-query" in DETECT_SRC
    assert "document.body && document.body.innerText" not in DETECT_SRC


def test_detector_has_guarded_running_animation_tier():
    # With the composer collapsed there may be NO stop button while the DR
    # spinner still runs — the animation tier must hold completion back, and
    # must carry the 2026-05-14 guards (visible + actually RUNNING) so
    # persisted/finished animations on UI chrome can't hold it hostage.
    assert "getAnimations" in DETECT_SRC
    assert "offsetParent" in DETECT_SRC
    assert "playState === 'running'" in DETECT_SRC


def test_detector_still_gates_on_start_button():
    # The planning-gate: "Start research" visible = pre-research, never done.
    assert "start research" in DETECT_SRC.lower()
    assert "start_research_btn_visible" in DETECT_SRC


def test_cua_completion_hint_describes_new_ui():
    # The round-robin CUA fallback hint must describe the collapsed composer
    # + the trio/chat-line markers, and keep the "response complete" /
    # "still generating" phrase anchors the parser keys on.
    assert "NO persistent bottom input box" in MODSRC
    assert "Contents', 'Share & Export'" in MODSRC


# ── 2B/2C: plan-wait timing + guard + alert ──────────────────────────────────

def test_plan_wait_caps_near_five_minutes_env_configurable():
    assert 'os.environ.get("GEMINI_PLAN_WAIT_SEC", str(5 * 60))' in MODSRC, (
        "the [2D] plan wait must cap ~5 min (env GEMINI_PLAN_WAIT_SEC), not a flat 10 min"
    )
    assert "_start_wait_max_sec = 10 * 60" not in MODSRC, "old flat 10-min cap must be gone"


def test_plan_wait_polls_and_heartbeats_smoothly():
    assert "_last_plan_emit >= 15" in MODSRC, "heartbeat should tighten to ~15s (was 60s)"
    assert "Tighter tick (was 30s)" in MODSRC, "the plan-wait poll tick should tighten to ~10s"


def test_start_research_click_is_verified_before_trusting():
    # A JS click that doesn't take must be re-clicked, not blindly trusted.
    assert "_start_present_js" in MODSRC
    assert "didn't take after 2 re-clicks" in MODSRC


def test_plan_failure_raises_retry_skip_alert_promptly():
    # [2C] submit-exhaustion, [2D] CUA-recovery-exhaustion, AND a failed user-retry
    # (hard retry) each raise the Retry/Skip alert (no silent drop to wall-clock cap).
    assert MODSRC.count("Gemini couldn't start its research plan") >= 3, (
        "fail_agent for an unstartable Gemini plan must fire at [2C], [2D], and on a "
        "failed user-retry"
    )
