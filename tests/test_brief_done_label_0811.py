"""A finished brief that polled for 40 more minutes, and a Skip that wasn't one.

WHAT HAPPENED (2026-08-11, full e2e)

Phase 1 submitted at 15:58 and the brief was fully rendered — 62492 chars — by
16:13. It then polled until 16:28, surfaced a stall card, and sat there until the
owner pressed a button at 16:53. Extraction immediately produced 65707 chars and
phase 2 ran normally. So nothing was ever broken about the brief; the run lost
~40 minutes plus a human decision to a detector that could not tell it was done.

ROOT CAUSE — a page label the vendor renamed.

The safety-net's vision check read the screen CORRECTLY on all three passes
(16:13, 16:19, 16:24). Its own words: "There is no filled square stop button
visible" and "I can see 'Worked for 9m' label at the top of the response". That
is a finished response, described accurately.

`_classify_completion_verdict`'s done-marker list was written 2026-06-02 and
contains the single literal "thought for". ChatGPT now writes "Worked for 9m".
No rule matched, so the classifier fell through to its ambiguous default and
returned "generating" — and the caller logged "Safety-net CUA confirms still
generating", a positive claim the parser had never made. Every 5 minutes, for 40
minutes, the log asserted the pipeline had looked and seen generation.

Independent corroboration the label changed, from the day before this run:
`queues/Worked_for_10m_32s_20260810_205153` — a run directory whose TITLE was
scraped off the page as "Worked for 10m 32s".

Not a regression: the classifier had not been touched since 2026-06-02, and
"worked for" appears nowhere in the codebase. A literal-string dependency on
someone else's UI simply aged out.

SECOND DEFECT — the stall card offered "Skip", and the copy said the user could
"write your own". Neither was true. Phase 2 attaches brief.md to every agent, so
phase 1 cannot be skipped at all; the branch actually falls through and extracts
whatever streamed. Here that was the right outcome and rescued the run — but it
is not what the button said, and against an empty screen the same button yields
a 0-char brief and a false "no brief generated".

WHAT THESE TESTS PIN
  1. The current label reads as complete, and so does the old one.
  2. The unit is required, so report prose ("worked for 3 teams") can't fake it.
  3. "recognised nothing" is reported distinctly from "observed generation",
     while behaving identically (keep polling).
  4. The salvage action is named for what it does and is only offered when
     there is something to salvage.
"""
import re

import pytest

import research

_v = research._classify_completion_verdict


# ── 1. the label the page actually shows ────────────────────────────────────

def test_the_live_2026_08_11_read_now_resolves_to_complete():
    """The verbatim shape of the vision read that was misclassified three times.
    If this ever returns anything but "complete" the 40-minute hang is back."""
    text = ("Observing the screen carefully: the button in the bottom-right of the "
            "composer is the animated waveform/audio equalizer icon — that is the "
            "voice input button, NOT a stop button. There is no filled square stop "
            "button visible. Response area: I can see \"Worked for 9m\" label at the "
            "top of the response.")
    assert _v(text) == "complete"


def test_the_previous_label_still_reads_as_complete():
    """The fix must not trade one label for another — both ship simultaneously
    in the wild, and ChatGPT has not removed the old one everywhere."""
    assert _v("No stop button. Thought for 1m 14s is shown above the answer.") == "complete"


@pytest.mark.parametrize("label", [
    "Worked for 9m", "worked for 12 min", "Thought for 1m 14s",
    "Reasoned for 45 seconds", "Researched for 2 hours",
])
def test_the_thinking_time_header_family_is_matched_as_a_shape(label):
    assert _v(f"No stop button is visible. {label} appears above the answer.") == "complete"


# ── 2. the unit is what stops it matching prose ─────────────────────────────

def test_report_prose_cannot_fake_the_done_marker():
    """⭐ The over-correction. The brief's own text is quoted back by the vision
    model, so a bare "worked for <number>" would let the REPORT declare itself
    finished. A false complete extracts an in-flight brief — the strictly worse
    failure, and the one #753 and #755 exist to prevent."""
    assert _v("No stop button. The report says the approach worked for 3 teams.") != "complete"
    assert _v("No stop button. It worked for 15 of the surveyed orgs.") != "complete"


def test_a_stop_button_still_beats_the_done_marker():
    """Unchanged priority: an affirmed stop button wins over any completion
    trace, so a half-rendered finalizing screen can't read as done."""
    assert _v("Stop button: Yes. Worked for 9m is shown but text is still streaming.") == "generating"


# ── 3. "recognised nothing" is not "observed generation" ────────────────────

def test_an_unrecognised_read_is_reported_as_ambiguous_not_generating():
    """The reporting defect. Behaviour is identical — both keep polling — but a
    log that says "confirms still generating" when the parser matched nothing is
    an assertion the code cannot support, and it is what hid this for 40 min."""
    assert _v("The screen shows a rendered document with several headings.") == "ambiguous"


def test_an_observed_generating_signal_is_still_reported_as_generating():
    assert _v("still generating") == "generating"
    assert _v("Stop button: Yes.") == "generating"


def test_ambiguous_and_generating_both_keep_polling():
    """The safety net must never early-exit on either — the cost asymmetry that
    #753 established is untouched by naming the two cases apart."""
    for text in ("", "The screen shows a rendered document.", "still generating"):
        assert _v(text) != "complete"


def test_the_caller_treats_ambiguous_as_keep_polling_and_says_which_it_was():
    """Guards the call site, not just the classifier: an ambiguous verdict must
    still poll, and must NOT print the 'confirms still generating' claim."""
    import inspect
    src = inspect.getsource(research.poll_until_done)
    assert '_sn_verdict in ("generating", "ambiguous")' in src, (
        "an unrecognised verdict must still keep polling"
    )
    m = re.search(r'"Safety-net CUA confirms still generating"\s*\n?\s*if _sn_verdict == "generating"', src)
    assert m, "the positive claim must be conditioned on a positive verdict"
    # The WARN that makes the next relabel visible must be guarded by the
    # verdict itself. Asserting only that the message exists passed against a
    # build where the branch was `if False:` — that mutant survived once.
    assert 'if _sn_verdict == "ambiguous":' in src, (
        "the unrecognised-read WARN must fire on the ambiguous verdict"
    )
    at = src.index('if _sn_verdict == "ambiguous":')
    assert "UNRECOGNISED" in src[at:at + 400], (
        "the guarded branch must be the one that logs the evidence"
    )


# ── 3b. the label-free rule: wording is a fast path, not the only path ──────
#
# The owner's requirement, and the right one: "even if 'worked for' changes in
# the future, it shouldn't break." Matching a wider family of words would still
# be matching words. So when the vision read recognises NOTHING, the decision is
# made from measured state instead — and these pin every condition, because each
# one is load-bearing and each removal is a different production failure.

def _poll_src():
    import inspect
    return inspect.getsource(research.poll_until_done)


# The 2026-08-11 run's own numbers, so "done" here means what it meant live.
DONE = dict(verdict="ambiguous", hard_stop_signal=False, text_len=62492,
            flat_sec=1224.0, page_dead_reason=None, min_len=2000, window_sec=300.0)


def _done(**over):
    return research._state_says_brief_is_done(**{**DONE, **over})


def test_the_live_stall_state_now_reads_as_finished():
    """The exact state at 16:13 on 2026-08-11, which polled for 40 more
    minutes. If this returns False the hang is back."""
    assert _done() is True


def test_it_never_overrides_a_positively_observed_generating_read():
    """⭐ The dangerous over-correction. If the model SAYS it sees generation,
    state must not out-vote it — that reintroduces #753's false-complete, which
    extracts an in-flight brief and reports 'no brief generated'."""
    assert _done(verdict="generating") is False
    assert _done(verdict="complete") is False


def test_a_live_stop_button_blocks_it():
    """The DOM saying 'generating' because of a real Stop button is not the
    residual-animation case this rule is for."""
    assert _done(hard_stop_signal=True) is False


def test_a_streaming_stub_is_not_a_finished_brief():
    assert _done(text_len=1999, min_len=2000) is False
    assert _done(text_len=2000, min_len=2000) is True


def test_it_requires_the_full_flat_window_not_one_poll():
    """One flat poll is normal mid-stream; the window is what makes flatness
    evidence."""
    assert _done(flat_sec=299.0, window_sec=300.0) is False
    assert _done(flat_sec=300.0, window_sec=300.0) is True


def test_flatness_that_never_started_is_not_flatness():
    """The caller passes -1 when no stall window is open — that must not read
    as 'flat forever'."""
    assert _done(flat_sec=-1.0) is False


@pytest.mark.parametrize("reason", [
    "the tab has been closed", "the tab is gone", "the tab has no address",
])
def test_a_dead_page_is_never_completion(reason):
    """The 2026-08-09 failure in one line: 'not generating' has two causes, and
    an about:blank tab was declared complete after 3289s. Every one of those
    pages also has no Stop button."""
    assert _done(page_dead_reason=reason) is False


def test_the_call_site_delegates_instead_of_re_deciding():
    """A second copy of this rule inline would drift from the tested one — the
    three-hand-rolled-copies failure that cost a run on 2026-08-05."""
    src = _poll_src()
    assert "_state_says_brief_is_done(" in src
    assert "page_dead_reason=_lf_dead" in src


def test_the_decision_is_the_functions_answer_alone():
    """⭐ Asserted on the SYNTAX TREE, not on a substring.

    `if False and _state_says_brief_is_done(...)` disables the whole rule while
    leaving every identifier a text search looks for exactly where it was — that
    mutant survived two rounds of substring tests. Reading the `if` node makes
    the shape itself the assertion: the guard must BE the call, so ANDing it
    with anything at all changes the node type and fails here."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(research.poll_until_done))
    shapes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if isinstance(test, ast.Call) and getattr(test.func, "id", "") == _FN:
            shapes.append("call")
        elif isinstance(test, ast.BoolOp) and any(
                isinstance(v, ast.Call) and getattr(v.func, "id", "") == _FN
                for v in test.values):
            shapes.append("weakened")
    assert shapes == ["call"], (
        f"the completion decision must be the function's answer alone, "
        f"used exactly once; found {shapes}"
    )


_FN = "_state_says_brief_is_done"


def test_the_call_site_probes_the_page_before_deciding():
    """`page_dead_reason` is only meaningful if the caller actually asks."""
    src = _poll_src()
    at = src.index("_state_says_brief_is_done(")
    assert "_lf_dead = await _page_is_dead(page)" in src[:at], (
        "the page must be probed before the verdict, not after"
    )


def test_the_label_free_completion_says_why_it_decided():
    """It overrides a detector that still says 'generating', so it must leave
    the numbers that justified it — chars, flat seconds, and the DOM reason."""
    src = _poll_src()
    at = src.index("no completion WORDING recognised")
    line = src[at:at + 500]
    for token in ("last_seen_len", "_lf_flat", "_diag_reason"):
        assert token in line, f"the evidence line must carry {token}"


# ── 4. the salvage action is honest, and gated ──────────────────────────────

def test_the_stall_carries_how_much_text_was_on_screen():
    """The card's offer depends on it, so it cannot be a guess."""
    e = research._BriefStreamStalled("phase 1 response stalled (text=62492)", text_len=62492)
    assert e.text_len == 62492


def test_a_stall_with_no_text_length_defaults_to_offering_nothing():
    """Safe direction: an unknown amount must not be treated as salvageable."""
    assert research._BriefStreamStalled("stalled").text_len == 0
    assert 0 < research._MIN_SALVAGEABLE_BRIEF_LEN


def test_the_salvage_floor_matches_the_extract_accept_gate():
    """Drift here offers the user a salvage the extractor then rejects — the
    card would promise a brief and the run would fail with 0 chars."""
    import inspect
    poll_src = inspect.getsource(research.poll_until_done)
    m = re.search(r"_SAFETY_NET_MIN_BRIEF_LEN\s*=\s*(\d+)", poll_src)
    assert m, "the safety-net extract gate must stay a named constant"
    assert int(m.group(1)) == research._MIN_SALVAGEABLE_BRIEF_LEN


def test_the_card_never_says_skip_and_never_promises_a_user_written_brief():
    """⭐ What the owner actually hit: a button labelled Skip, copy offering to
    let them "write your own", and a behaviour that did neither. Phase 2
    attaches brief.md to every agent — phase 1 cannot be skipped."""
    import inspect
    src = inspect.getsource(research.run_phase1)
    assert "Skip and write your own" not in src
    # ⭐ Assert the BUTTON LABEL, not the phrase. The card's body copy also
    # contains "Use what's on screen", so a loose `in src` passed while the
    # label itself had been mutated back to "Skip" — that mutant survived the
    # first version of this suite.
    assert '"label": "Use what\'s on screen"' in src
    at = src.index('"action": "skip_phase", "phase": 1')
    assert '"label": "Skip"' not in src[max(0, at - 300):at], (
        "the phase-1 salvage button must never be labelled Skip — phase 2 "
        "attaches brief.md to every agent, so phase 1 cannot be skipped"
    )


def test_the_salvage_action_is_only_offered_when_there_is_something_to_salvage():
    """Against an empty screen the same command produces a 0-char brief and the
    false 'no brief generated' failure."""
    import inspect
    src = inspect.getsource(research.run_phase1)
    assert "_p1s_salvageable" in src
    at = src.index("_p1s_salvageable =")
    assert "_MIN_SALVAGEABLE_BRIEF_LEN" in src[at:at + 200]
    # the skip action must sit under the salvageable guard, not be unconditional
    skip_at = src.index('"command": {"action": "skip_phase", "phase": 1}')
    guard_at = src.rindex("if _p1s_salvageable:", 0, skip_at)
    assert guard_at < skip_at


def test_retry_past_the_cap_falls_through_instead_of_recursing():
    """A stale card in a reopened tab can still send retry_phase after the
    attempts are spent; honouring it would recurse past the cap."""
    import inspect
    src = inspect.getsource(research.run_phase1)
    assert 'if p1s_decision == "retry" and retries_left_p1s > 0:' in src
