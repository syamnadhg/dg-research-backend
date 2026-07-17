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
  2. SILENT self-heal (e2e 2026-07-16): the recovery raises NO alert and does NOT
     pause. The earlier build emitted a recoverable [Retry][Skip] card here (a
     pipeline_error the FE auto-pauses on) BEFORE even attempting the sidebar
     adopt — which normally resolves in seconds — and its "retract" was only a
     pipeline_warning that neither un-paused the FE nor cleared the card, so an
     adopt-SUCCESS stranded the run "Paused" needing a manual resume. Now: a
     single agent_progress heartbeat keeps the tile alive during a quiet recovery
     (a 2-3 min ladder is well inside the 30-min P2 event-silence watchdog), and
     ONLY when recovery is EXHAUSTED does the terminal fail_agent [Retry][Skip]
     blocker fire — the one genuine user-action alert.
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


# ── 2. silent self-heal (no pausing card during recovery) ────────────────────

def test_lost_send_recovery_raises_no_pausing_card():
    # The old build emitted a recoverable [Retry][Skip] card (pipeline_error →
    # FE auto-pause) the moment the URL read bare /app — before even trying the
    # adopt. That machinery is GONE (removed, not shadowed): no emit helper, no
    # retract helper, no shared alert-id var, and no agent_failed decision in
    # this function (the terminal fail_agent authors its own downstream).
    assert "_emit_gemini_recovery_card" not in _GEM
    assert "_retract_gemini_recovery_card" not in _GEM
    assert "_gem_alert_id" not in _GEM
    assert 'intent="agent_failed"' not in _GEM


def test_recovery_shows_a_silent_agent_progress_not_an_alert():
    # A single non-blocking agent_progress keeps the tile alive during the quiet
    # recovery — a status, NOT an alert (no actions, no pause).
    assert 'emit_event("agent_progress", phase=2, agent="gemini"' in _GEM
    assert "Reconnecting to Gemini" in _GEM
    assert "silent self-heal" in _GEM
    # …and it's emitted BEFORE the adopt so the tile isn't dead during it.
    assert _GEM.index('emit_event("agent_progress"') < _GEM.index("_gemini_adopt_lost_conversation(")


def test_adopt_and_resubmit_success_paths_are_silent():
    # On BOTH silent-recovery success paths we just log + return page,True —
    # there is no card to clear (none was ever shown).
    assert _GEM.count("return page, True") >= 2
    i_adopt = _GEM.index("adopted lost conversation")
    assert "return page, True" in _GEM[i_adopt:i_adopt + 200]
    i_resub = _GEM.index("re-submit landed")
    assert "return page, True" in _GEM[i_resub:i_resub + 200]


def test_failed_adopt_normalizes_to_home_and_fails_safe_if_stranded():
    # Adversarial-verify finding: a FAILED adoption can strand the tab on a
    # rejected /app/<id> (concurrent worker's chat / previous run's report); the
    # helper's home-reset is best-effort and can time out. Between the adopt block
    # and the ladder we force the tab back to the empty home — and if it STILL
    # won't leave, we fail to the terminal blocker rather than let the ladder
    # misread the stale chat as a landing and confirm on the WRONG conversation.
    i_adopt = _GEM.index('adopted lost conversation')
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
