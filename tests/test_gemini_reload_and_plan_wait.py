"""Phase-2 Gemini robustness — periodic-reload empty-chat recovery (2A) and
plan-generation wait timing + Start-Research guard + alert (2B/2C).

Root-caused 2026-06-29 from a live stuck run ("OpenShell vs NemoClaw", conv
/app/1f44b0c0faafb512): the DR FINISHED (CUA said "done 1/2"), but the ~10-min
periodic page.reload() then re-rendered Gemini's empty "What's the vibe" home,
wiping the completed panel before the 2nd CUA confirmation → it looped forever.
Separately, the [2D] plan-draft wait was a flat 10 min (+6 min CUA recovery) with
a 30s/60s tick, far past the user's "Start research in 3-5 min max" + it felt
frozen, and a never-started plan dropped to the wall-clock cap instead of a prompt
Retry/Skip.

Guards:
  2A  - the periodic reload STOPS once CUA confirms done (done_count >= 1) so a
        finished panel isn't wiped;
      - after a reload it probes the DOM (not the stale URL) for the empty home and
        recovers IN-CHAT via the sidebar (primary) then goto (fallback);
      - the stuck-watchdog baselines reset ONLY when the conversation is present,
        so an unrecoverable empty home escalates instead of polling a dead page.
  2B/2C - the plan wait caps near ~5 min (env GEMINI_PLAN_WAIT_SEC), the heartbeat
        + poll tick tighten, the Start-Research click is verified (re-click if it
        didn't take), and exhaustion (here AND on a user-retry) raises fail_agent.
"""
import inspect

import research

MODSRC = inspect.getsource(research)


# ── 2A: conversation-id helper (pure) ────────────────────────────────────────

def test_conversation_id_extracted_from_app_url():
    f = research._gemini_conversation_id
    assert f("https://gemini.google.com/app/1f44b0c0faafb512") == "1f44b0c0faafb512"
    assert f("https://gemini.google.com/app/1f44b0c0faafb512?hl=en") == "1f44b0c0faafb512"


def test_conversation_id_blank_for_bare_or_missing():
    f = research._gemini_conversation_id
    assert f("https://gemini.google.com/app") == ""   # bare new-chat home
    assert f("") == ""
    assert f("https://gemini.google.com/") == ""


# ── 2A: reload hardening wiring ──────────────────────────────────────────────

def test_periodic_reload_stops_once_cua_confirms_done():
    # The empty-chat hang: CUA said "done 1/2", the NEXT reload wiped the panel.
    # Once done_count >= 1, the periodic reload must be suppressed.
    assert 'p.get("done_count", 0) < 1' in MODSRC, (
        "periodic Gemini reload must skip once CUA has a done confirmation"
    )


def test_reload_holds_during_active_generation_grace():
    # A live run (Golden Retriever, 3 workers) lost its Gemini DR: the periodic
    # reload fired ~11 min in WHILE the DR was still generating, dropped the SPA to
    # the empty home, and recovery couldn't restore it. The reload must wait out a
    # grace (CUA tracks progress in that window) before it can fire.
    assert "GEMINI_REFRESH_GRACE" in MODSRC
    assert 'os.environ.get("GEMINI_REFRESH_GRACE_SEC"' in MODSRC
    assert "(time.time() - p[\"start_time\"]) >= GEMINI_REFRESH_GRACE" in MODSRC, (
        "the periodic reload must be gated on the active-generation grace"
    )


def test_sidebar_recovery_matches_real_gemini_controls():
    # The recovery failed because the expand-button selector only matched
    # menu/expand — Gemini's real controls are "Open sidebar" + "Toggle Recent".
    src = inspect.getsource(research._gemini_reopen_from_sidebar)
    assert "open sidebar" in src.lower(), "must click Gemini's 'Open sidebar' control"
    assert "recent" in src.lower(), "must expand Gemini's 'Toggle Recent' list"


def test_reload_recovers_empty_home_and_helpers_exist():
    assert hasattr(research, "_gemini_recover_if_empty")
    assert hasattr(research, "_gemini_reopen_from_sidebar")
    assert hasattr(research, "_gemini_conversation_present")
    # the reload block calls the recovery (not the old stale-URL drift check)
    assert "_gemini_recover_if_empty(" in MODSRC
    # recovery probes the DOM for conversation markers, not page.url
    assert "_GEMINI_CONVERSATION_PRESENT_JS" in MODSRC
    assert "post-reload URL drifted" not in MODSRC, (
        "the unreliable stale-URL drift recovery should be replaced by the DOM probe"
    )


def test_sidebar_is_the_primary_recovery():
    src = inspect.getsource(research._gemini_recover_if_empty)
    # sidebar reopen is attempted BEFORE the goto fallback
    assert src.index("_gemini_reopen_from_sidebar") < src.index("page.goto"), (
        "sidebar click must be the PRIMARY recovery (a cold goto often re-renders empty)"
    )


def test_watchdog_baselines_reset_only_when_conversation_present():
    # If recovery failed (still empty home), DON'T reset the stuck-watchdog
    # baselines — let it escalate, instead of polling a dead page forever.
    assert "if _recovered:" in MODSRC


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
