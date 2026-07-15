"""#955 Phase 2G — Gemini lost-send recovery (adopt-first + reconnect card + nudge clock).

The live bug: after the brief is sent, Gemini's tab lands on an empty new-chat
home (`/app`) while the REAL conversation sits in the sidebar. The old order
re-pasted the brief 3× FIRST — which spawned a DUPLICATE run into a fresh chat
and orphaned the real one — and only tried to adopt the lost conversation
afterwards (by which point _landed was already true on the duplicate, so adopt
never ran). Phase 2G:

  1. ADOPT-FIRST: find + adopt the owned, brief-matching, pre-Start conversation
     (sibling tab / sidebar most-recent) BEFORE any re-submit. Only a genuine
     dropped send (adoption finds nothing) falls through to the re-paste ladder.
  2. ONE honest reconnect card visible throughout the ladder (not just a terminal
     blocker at the very end), retracted the instant we reconnect, escalated to
     the terminal Retry/Skip blocker only on total failure.
  3. The mid-run kickoff nudge no longer resets the stall clocks (that deferred
     the unified auto-skip ~7 min per nudge).

The Gemini branch drives a live browser, so these are source-inspection pins.

Run: pytest tests/test_gemini_lost_send_955.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

_GEM = inspect.getsource(research.start_agent_no_gemini_wait)
_POLL = inspect.getsource(research.poll_all_agents_round_robin)


# ── 1. adopt-FIRST reorder ───────────────────────────────────────────────────

def test_adopt_runs_before_the_repaste_ladder():
    i_adopt = _GEM.index("_gemini_adopt_lost_conversation(")
    i_ladder = _GEM.index("_max_attempts = 3")
    assert i_adopt < i_ladder, "adoption must run BEFORE the re-paste/re-submit ladder"


def test_only_one_adopt_call_old_end_block_removed():
    # The old adopt-at-END block was REMOVED (not shadowed) — exactly one call.
    assert _GEM.count("_gemini_adopt_lost_conversation(") == 1


def test_adopt_success_returns_without_repasting():
    # On adoption success we return immediately (no duplicate-spawning re-paste).
    i_adopt = _GEM.index("adopted lost conversation")
    tail = _GEM[i_adopt:i_adopt + 200]
    assert "return page, True" in tail


# ── 2. one honest reconnect card ─────────────────────────────────────────────

def test_reconnect_card_uses_the_unified_seam_as_recoverable():
    assert "_emit_gemini_recovery_card" in _GEM
    # authored via emit_decision as the recoverable agent_failed intent (NOT
    # fail_agent — that would persist an errored red tile while merely reconnecting).
    assert 'intent="agent_failed"' in _GEM
    assert "Reconnecting to Gemini" in _GEM
    # emitted BEFORE adoption so it's visible for the whole ladder.
    assert _GEM.index("_emit_gemini_recovery_card()") < _GEM.index("_gemini_adopt_lost_conversation(")


def test_reconnect_card_retracts_on_every_success_path():
    # Retracted on BOTH adoption success AND re-submit-landed success.
    assert '_retract_gemini_recovery_card("adopted lost conversation")' in _GEM
    assert '_retract_gemini_recovery_card("re-submit landed")' in _GEM
    # Retract = pipeline_warning on the SAME alert_id + clear the durable mirror.
    _rt = _GEM.index("def _retract_gemini_recovery_card")
    _body = _GEM[_rt:_rt + 700]
    assert 'emit_event("pipeline_warning", phase=2, agent="gemini"' in _body
    assert '_clear_pending_decision("gemini")' in _body


def test_reconnect_card_shares_the_gemini_error_alert_id():
    # Single-card contract: reconnect card, its retraction, and the terminal
    # blocker all key on the SAME gemini error alert_id (updates in place).
    assert '_gem_alert_id = _agent_error_alert_id("gemini", 2)' in _GEM


def test_failed_adopt_normalizes_to_home_and_fails_safe_if_stranded():
    # Adversarial-verify finding: a FAILED adoption can strand the tab on a
    # rejected /app/<id> (concurrent worker's chat / previous run's report); the
    # helper's home-reset is best-effort and can time out. Between the adopt block
    # and the ladder we force the tab back to the empty home — and if it STILL
    # won't leave, we fail to the terminal blocker rather than let the ladder
    # misread the stale chat as a landing and confirm on the WRONG conversation.
    i_adopt = _GEM.index('_retract_gemini_recovery_card("adopted lost conversation")')
    i_ladder = _GEM.index("_max_attempts = 3")
    seg = _GEM[i_adopt:i_ladder]
    assert "not _adopted and _gemini_in_conversation()" in seg
    assert 'page.goto("https://gemini.google.com/app"' in seg
    # stranded-and-can't-leave → terminal blocker + return False (safe fail)
    assert 'fail_agent("gemini", "Gemini couldn\'t start Deep Research"' in seg
    assert "return page, False" in seg


def test_total_failure_still_escalates_to_the_terminal_blocker():
    # Adoption found nothing AND every re-submit failed → terminal Retry/Skip
    # blocker (never a silent drop; the round-robin auto-skips if unattended).
    assert 'fail_agent("gemini", "Gemini couldn\'t start Deep Research"' in _GEM
    assert "no silent skip" not in _GEM.lower() or "auto-skips Gemini" in _GEM


# ── 3. kickoff-nudge clock integrity ─────────────────────────────────────────

def test_kickoff_nudge_does_not_reset_the_stall_clocks():
    # The nudge is a real recovery prod, but it must NOT reset start_time /
    # last_growth_time / stuck_warned_at — doing so deferred the unified
    # stall-detection + auto-skip ~7 min per nudge. Only the FE liveness
    # heartbeat is refreshed.
    i = _POLL.index("a kickoff nudge is a genuine recovery")
    blk = _POLL[i:i + 1600]   # spans the rationale comment + the heartbeat-only refresh
    assert 'p["last_heartbeat"] = time.time()' in blk
    assert 'p["start_time"]' not in blk
    assert 'p["last_growth_time"]' not in blk
    assert 'p["stuck_warned_at"]' not in blk
    # The nudge itself is KEPT (a genuine recovery) — only the clock reset is gone.
    assert "_gemini_send_kickoff_nudge" in _POLL


# ── sanity ───────────────────────────────────────────────────────────────────

def test_module_imports():
    assert callable(research.start_agent_no_gemini_wait)
    assert callable(research._gemini_adopt_lost_conversation)
