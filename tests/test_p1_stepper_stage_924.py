"""#924 (2026-07-09): P1 milestone stepper was stuck at "Submitted".

User-captured screenshot: the Phase-1 "Research Brief" stepper sat on
"Submitted" for the whole phase (4.2 min in) even though ChatGPT was plainly
generating the brief. Root cause: P1 is Pro + Extended Thinking (NOT Deep
Research), so it has NO research counters (sources/searches/websites), and
poll_until_done's agent_progress emit carried no `stage` field — so the FE
`agentStepper` had nothing to advance it off "Submitted".

Fix (verified here): poll_until_done (P1-only) now emits an honest `stage` for
phase 1 — "researching" while the brief thinks/streams, "writing" once real
text (>=500 chars) or an outline exists. The scrape+emit is at the TOP of the
poll loop (before any sleep), so the stepper advances off Submitted the instant
polling starts — i.e. right after the send is confirmed (the user's ask).
"""

import inspect

import research

_POLL = inspect.getsource(research.poll_until_done)


def test_poll_emits_a_stage_field():
    # The agent_progress emit must now carry a `stage` kwarg (was absent — the
    # reason the P1 stepper never left Submitted).
    assert "stage=_p1_stage" in _POLL


def test_stage_is_phase1_scoped():
    # Only phase 1 computes a stage (poll_until_done is P1-only, but the guard
    # keeps it from ever stamping a stage on some future non-P1 reuse).
    assert "if phase == 1:" in _POLL
    assert '_p1_stage = ""' in _POLL


def test_stage_researching_then_writing():
    # researching by default (in the poll ⇒ verified generating); writing once
    # real brief text streams or an outline exists.
    assert '"researching"' in _POLL
    assert '"writing"' in _POLL
    assert "_merged_partial_len >= 500" in _POLL


def test_emit_is_at_top_of_loop_before_verify_and_sleep():
    """The stepper must advance ~immediately, not after a 30s poll gap: the
    scrape+emit block precedes the verify_fn call + the poll sleep."""
    emit_at = _POLL.index("emit_event(\"agent_progress\"")
    verify_at = _POLL.index("generating = await verify_fn(page)")
    assert emit_at < verify_at
