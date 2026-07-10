"""HV unacted → clean auto-skip (2026-07-10).

An hands-off human-verification wall (Cloudflare — Skip is the only real move)
that the user never acts on used to end up as a RED errored `fail_agent` card
that STILL required a manual Skip: the tier-5 pause timed out into the caller's
fail_agent, and the setup-fail path added the agent to `skipped_agents` so the
round-robin consumer greyed it LATE (only when the poll loop started) with a
mislabeled `user_skip` reason.

Live repro (backend-2.log 2026-07-10 11:01→11:23): Claude hit Cloudflare, the
pause timed out at 11:11 (600s), a red Skip-only card sat until 11:23 when the
round-robin greyed it and logged "Skipped by user" — but the user never tapped
Skip; it was the internal add at start of setup-fail.

Fix: on the unacted HV timeout (grace window UNCHANGED at ~10 min), with
auto-skip ON, finalize a CLEAN grey-skip immediately — agent_skipped with an
HONEST reason (auto_skip_hv_unanswered), an informational notice (not a red
card), tab closed — gated by the same `_runtime.auto_skip_stuck` toggle as the
L3 stuck-agent auto-skip. When auto-skip is OFF, the manual Skip-only card
stays. The window is NOT coupled to the 30-min L3 knob (AUTO_SKIP_UNACTED_SEC).
"""
import inspect

import research

MODSRC = inspect.getsource(research)


# ── the finalize helper: L3-consistent grey-fade dynamics ────────────────────

def test_finalize_helper_exists_and_greys_with_honest_reason():
    src = inspect.getsource(research._hv_auto_skip_finalize)
    # Greys the tile via agent_skipped with the honest auto reason (NOT user_skip).
    assert 'emit_event("agent_skipped"' in src
    assert 'reason="auto_skip_hv_unanswered"' in src
    assert "user_skip" not in src
    # Informational notice, NOT a red error card.
    assert 'emit_event("pipeline_warning"' in src
    assert "fail_agent(" not in src, "auto-skip must NOT emit a red error card"


def test_finalize_closes_the_tab_and_clears_the_decision():
    src = inspect.getsource(research._hv_auto_skip_finalize)
    assert "_close_skipped_agent_tab(" in src, "must close the walled tab (hands-off)"
    assert "_clear_pending_decision()" in src, "must retract the durable card mirror"


def test_finalize_marks_both_skip_sets():
    src = inspect.getsource(research._hv_auto_skip_finalize)
    # skipped_agents so the setup/caller 'no card' branches fire; hv_auto_skipped
    # so the round-robin consumer knows it's already finalized.
    assert "_controls.skipped_agents.add(agent_key)" in src
    assert "_controls.hv_auto_skipped.add(agent_key)" in src


# ── toggle-gating (same knob as L3), NOT the 30-min duration ─────────────────

def test_tier5_timeout_gates_on_the_toggle_and_finalizes():
    src = inspect.getsource(research.wait_for_verification_clearance)
    assert "if _runtime.auto_skip_stuck:" in src, "auto-skip must honor the on/off toggle"
    assert "_hv_auto_skip_finalize(" in src, "the timeout must finalize a clean grey-skip"


def test_setup_fail_card_gates_on_the_toggle():
    src = inspect.getsource(research._hv_setup_fail_card)
    assert "if _runtime.auto_skip_stuck:" in src
    assert "_hv_auto_skip_finalize(" in src
    # When the toggle is OFF, the manual Skip-only card path is still present.
    assert "fail_agent(" in src


def test_hv_window_is_unchanged_and_not_coupled_to_the_30min_l3_knob():
    # The user's explicit call: keep the ~10-min HV grace (max_wait_loops=120,
    # 600s), NOT the 30-min L3 AUTO_SKIP_UNACTED_SEC. Pin both facts so a future
    # edit can't silently re-couple them.
    sig = inspect.getsource(research.wait_for_verification_clearance)
    assert "max_wait_loops: int = 120" in sig, "HV grace window must stay ~10 min"
    assert "AUTO_SKIP_UNACTED_SEC" not in sig, (
        "the HV auto-skip must gate on the auto_skip_stuck toggle, not the 30-min "
        "L3 unacted duration"
    )


# ── round-robin consumer: no double-emit / re-close ─────────────────────────

def test_consumer_guards_already_finalized_hv_auto_skips():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert "if _ag_key in _controls.hv_auto_skipped:" in src, (
        "the skip consumer must short-circuit an agent the HV finalize already "
        "greyed + closed, so it doesn't re-emit agent_skipped with a user_skip reason"
    )


# ── Controls lifecycle ──────────────────────────────────────────────────────

def test_controls_track_and_reset_hv_auto_skipped():
    assert "self.hv_auto_skipped: set[str] = set()" in MODSRC
    assert "self.hv_auto_skipped.clear()" in MODSRC, "reset() must clear the set per run"
