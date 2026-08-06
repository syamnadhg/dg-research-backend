"""2026-08-05 — "the auto-skip timer didn't work or my Continue didn't work."

The owner's own words about the prod run. Both halves were true, for different
reasons, and neither was in the frontend.

Timeline (backend.log):

    07:01:34  parked, window=1800.0s deadline_ms=…294639   (= 07:31:34)
    07:07:50  [round-robin] ChatGPT parked kind=chat_mode
    07:31:49  Command received: AGENT_DECISION decision=continue_chat
    07:32:12  Command received: AGENT_DECISION decision=continue_chat   ← again
    07:34:21  [ChatGPT] Parked decision resolved (action=continue_anyway)

Four distinct defects:

1. THE KEEP PATH EMITTED NOTHING. `_resolve_parked_agent_decision`'s
   continue_anyway branch set state, logged, and returned. Every OTHER
   resolution of this park emits something the durable-mirror clear-seam
   recognises; KEEP was the one outcome that left both the mirror and the card
   standing. The web app re-enables the buttons ~4s after a click, so the card
   came back live still reading "Auto-skipping…" — which is why there are TWO
   commands. The action had worked; it never said so.

2. 2m32s TO RESOLVE. `_leg_dwell` cuts short for stop, pause, Skip and hard
   Retry — but not for a queued agent_decision, because none of those pause the
   pipeline, so the dispatcher's request_resume is a no-op. With three agents a
   rotation costs 3 × P2_AGENT_DWELL_SEC of dwell alone.

3. THE AUTO-SKIP DEADLINE HAD NO ACTOR. The web app's countdown is display-only
   (it renders "Auto-skipping…" at zero and sends nothing) and the backend read
   the window once per rotation. The deadline fell at 07:31:34; the earliest the
   backend could look was 07:34:21. The owner watched a timer reach zero and
   stay there, then clicked 15 seconds later.

4. chat_mode ARMED ITS WINDOW UNCONDITIONALLY — the one park kind the
   2026-08-02 window-family sweep never reached. With auto-skip switched OFF the
   user still got a 30-minute countdown to a fire their setting forbids, and the
   agent WAS dropped at 30 minutes.

Run:  pytest tests/test_decision_resolves_on_arrival.py -v
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from conftest import code_only

RESOLVE_SRC = code_only(research._resolve_parked_agent_decision)
PARK_SRC = code_only(research._park_chat_mode_decision)
RR_SRC = code_only(research.poll_all_agents_round_robin)
LISTENER_SRC = code_only(research._start_command_listener)


def _keep_branch() -> str:
    i = RESOLVE_SRC.index('if kind == "chat_mode":')
    tail = RESOLVE_SRC[i:]
    return tail[:tail.index("timeout / any non-continue")] if \
        "timeout / any non-continue" in tail else tail[:2000]


# ── 1. The KEEP path must retract its own card ────────────────────────────

def test_the_keep_path_retracts_the_durable_mirror():
    branch = _keep_branch()
    assert "_clear_pending_decision(" in branch, (
        "KEEP left the durable pendingDecision on the doc, so it re-surfaces on "
        "a later cold chat-open"
    )


def test_the_keep_path_emits_a_resolve_event_the_clear_seam_recognises():
    branch = _keep_branch()
    assert "emit_event(" in branch, "the KEEP path emitted nothing at all"
    assert "pipeline_resumed" in branch, (
        "the seam clears on pipeline_resumed / pipeline_stopped / agent_skipped "
        "/ phase_skipped / phase_restart — KEEP must emit one of them"
    )


def test_the_resolve_event_is_scoped_to_the_agent_that_was_answered():
    """An unscoped clear would wipe a SIBLING agent's still-live card — two
    agents failing share one pendingDecision slot.

    ⚠ BOTH halves must be scoped. The first version of this test checked only the
    emit, so a mutant dropping the argument from `_clear_pending_decision(key)`
    passed — and that is the half that actually retracts the durable mirror."""
    branch = _keep_branch()
    i = branch.index("emit_event(")
    assert "agent=" in branch[i:i + 220]
    assert "_clear_pending_decision(key)" in branch, (
        "the durable-mirror clear is unscoped — it wipes whichever agent's "
        "pendingDecision happens to be on the doc, not the one just answered"
    )


def test_the_event_the_keep_path_emits_is_one_the_seam_actually_watches():
    """Pin the coupling rather than the string: read the seam's own event list
    out of the mirror writer and assert the emitted type is in it."""
    mirror = code_only(research.emit_event)
    watched = mirror[mirror.index('if event_type in ("pipeline_resumed"'):]
    watched = watched[:watched.index(")") + 1]
    branch = _keep_branch()
    emitted = branch[branch.index("emit_event("):]
    emitted = emitted[:emitted.index(")")]
    assert '"pipeline_resumed"' in watched
    assert "pipeline_resumed" in emitted


def test_the_keep_log_line_says_the_card_was_retracted():
    """The owner's report was "nothing happened". Silence in the log is how that
    became a two-hour question."""
    assert "card retracted" in _keep_branch()


# ── 2. A queued decision must cut the dwell ───────────────────────────────

def _dwell_body() -> str:
    i = RR_SRC.index("async def _leg_dwell")
    return RR_SRC[i:RR_SRC.index("_first_leg_of_tick = True")]


def test_a_queued_agent_decision_ends_the_dwell():
    body = _dwell_body()
    assert "_controls.pending_agent_decision" in body, (
        "stop, pause, Skip and hard-Retry cut the dwell; Continue-in-chat-mode, "
        "soft retry, wait-longer and continue-partial did not"
    )


def test_the_pre_existing_early_exits_are_all_still_there():
    """This fix ADDS a clause. A refactor that replaced them would trade one
    latency bug for four."""
    body = _dwell_body()
    for flag in ("_controls.is_stop()", "_controls.is_pause()",
                 "_controls.skipped_agents", "_controls.retry_agents_hard"):
        assert flag in body, f"{flag} no longer cuts the dwell"


def test_an_expired_park_deadline_also_ends_the_dwell():
    body = _dwell_body()
    assert "park_window_elapsed(" in body, (
        "nothing was scheduled to act at the deadline's own epoch"
    )


def test_the_deadline_sweep_excludes_entries_with_no_park():
    """⚠ `park_window_elapsed(None)` returns TRUE — an absent `since` defaults to
    0, and now-0 clears any window. Sweeping unguarded would end every dwell
    immediately, on every agent, forever."""
    assert research.park_window_elapsed(None) is True, (
        "if this ever returns False the guard below is still correct, but this "
        "test's reason for existing has changed — read it before deleting"
    )
    body = _dwell_body()
    i = body.index("park_window_elapsed(")
    window = body[max(0, i - 200):i]
    assert 'pp.get("awaiting_decision")' in window, (
        "the sweep must skip agents that are not parked at all"
    )


def test_a_parked_agent_with_a_live_window_does_not_end_the_dwell():
    """The behavioural half — the guard must not fire on a park that is simply
    waiting."""
    live = {"since": time.time(), "timeout": 1800.0}
    assert research.park_window_elapsed(live) is False
    expired = {"since": time.time() - 1801, "timeout": 1800.0}
    assert research.park_window_elapsed(expired) is True
    no_deadline = {"since": time.time() - 99999, "timeout": 0}
    assert research.park_window_elapsed(no_deadline) is False


# ── 3. chat_mode must honour the auto-skip setting ────────────────────────

def test_the_chat_mode_window_is_derived_from_the_setting():
    assert "unacted_window_sec(" in PARK_SRC, (
        "chat_mode armed DG_CHATMODE_SEC unconditionally — the one park kind "
        "the 2026-08-02 window-family sweep never reached"
    )
    assert "_runtime.auto_skip_stuck" in PARK_SRC


def test_no_deadline_is_sent_to_the_card_when_auto_skip_is_off():
    """A countdown to a fire the setting forbids is the defect, not just the
    fire itself."""
    assert "if window_sec > 0 else None" in PARK_SRC


def test_the_env_override_tunes_the_length_not_whether_there_is_a_deadline():
    i = PARK_SRC.index("DG_CHATMODE_SEC")
    before = PARK_SRC[:i]
    assert "if _runtime.auto_skip_stuck:" in before, (
        "DG_CHATMODE_SEC must sit INSIDE the setting check, or the override "
        "silently re-arms a window the user switched off"
    )


def test_a_zero_window_is_read_as_no_deadline_by_the_firer():
    """The contract the fix depends on. `>= 0` is true on the very first tick,
    so a 0 window that meant "immediately" would auto-skip instantly — worse
    than the bug."""
    assert research.park_window_elapsed({"since": 0, "timeout": 0}) is False


def test_the_park_log_distinguishes_no_deadline_from_a_deadline():
    assert "auto-skip off" in PARK_SRC, (
        "the log must not print window=0.0s as though a timer were armed"
    )


def test_a_malformed_env_value_does_not_crash_the_park():
    """The park runs mid-setup on the live pipeline; a ValueError here would
    take the agent down instead of parking it."""
    assert "except (TypeError, ValueError):" in PARK_SRC


# ── 4. One answer per decision ────────────────────────────────────────────

def test_the_listener_remembers_which_decisions_it_has_answered():
    assert "_cmd_seen" in LISTENER_SRC, (
        "both ids already travelled on the wire and were read only to be echoed "
        "back in the ack — nothing remembered them"
    )


def test_a_duplicate_is_still_acked_but_not_dispatched():
    """A genuinely lost ack must still release the web app's button; only the
    second EXECUTION is suppressed."""
    assert 'emit_event("command_ack"' in LISTENER_SRC
    assert LISTENER_SRC.index('emit_event("command_ack"') < \
        LISTENER_SRC.index('if _dup_key and _dup_key in _cmd_seen["keys"]:'), (
        "the ack must be emitted BEFORE the duplicate check — otherwise a lost "
        "ack leaves the web app's button stuck on 'Sending…' forever, and the "
        "user's only recourse is the click that created the duplicate"
    )


def test_a_duplicate_short_circuits_before_the_dispatch():
    dup = LISTENER_SRC[LISTENER_SRC.index('if _dup_key and _dup_key in _cmd_seen["keys"]:'):]
    branch = dup[:dup.index('if _dup_key:')]
    assert "continue" in branch, "the duplicate is still being dispatched"


def test_the_dedupe_key_includes_the_action_so_changing_your_mind_works():
    """Continue → Skip on the same card is legitimate and must go through."""
    i = LISTENER_SRC.index("_dup_key = f\"d:")
    assert "action" in LISTENER_SRC[i:i + 160], (
        "keying on decisionId alone would swallow a user changing their answer"
    )


def test_the_dedupe_memory_is_bounded():
    """This listener lives for the whole run; an unbounded set grows with every
    click of a long session."""
    i = LISTENER_SRC.index('_cmd_seen["keys"].add(')
    region = LISTENER_SRC[i:i + 400]
    assert "while len(" in region and "popleft()" in region


def test_the_bound_evicts_from_both_halves_together():
    """A deque that pops without discarding from the set leaks, and a set that
    discards without popping loses its ordering — either way the bound stops
    working."""
    i = LISTENER_SRC.index('_cmd_seen["keys"].add(')
    region = LISTENER_SRC[i:i + 400]
    assert 'discard(' in region and 'popleft()' in region
    assert region.index("popleft()") > region.index("while len(")


def test_the_dedupe_block_is_actually_REACHABLE():
    """⚠ Every other test here finds STRINGS. A mutant that appended `and False`
    to the block's own entry condition left all of them in place and passed —
    including the ordering assertions, because the statements were still in the
    same order, just unreachable. Pin the condition.

    Same lesson as the topic guard's reachability test, one file over: a guard
    that cannot run satisfies every assertion about what it contains."""
    src = LISTENER_SRC
    i = src.index('_dec_id = (data.get("decisionId")')
    entry = src[:i]
    entry = entry[entry.rindex("if "):]
    assert "_cmd_id" in entry and "action" in entry, (
        f"the dedupe block's entry condition is {entry.strip()!r}"
    )
    assert "False" not in entry, (
        "the dedupe block is gated on something that can never be true"
    )


def test_a_command_with_no_ids_is_not_deduped_at_all():
    """A legacy client sends no command_id and nothing is waiting on an ack —
    it must not be silently dropped by an empty dedupe key."""
    assert "if _dup_key and" in LISTENER_SRC, (
        "an empty key must fall through to the dispatch, not match — a legacy "
        "client sends no command_id and nothing is waiting on its ack"
    )
    # …and the key starts out None so an id-less command can never collide.
    assert "_dup_key = None" in LISTENER_SRC
    assert LISTENER_SRC.index("_dup_key = None") < \
        LISTENER_SRC.index('if _dup_key and _dup_key in _cmd_seen["keys"]:')
