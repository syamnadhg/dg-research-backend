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


def test_an_unrecognised_read_can_complete_from_state_alone():
    src = _poll_src()
    assert '_sn_verdict == "ambiguous"' in src, (
        "the label-free path must key on 'recognised nothing', which is what a "
        "renamed page label produces"
    )


def test_it_never_overrides_a_positively_observed_generating_read():
    """⭐ The dangerous over-correction. If the model SAYS it sees generation,
    state must not out-vote it — that reintroduces #753's false-complete, which
    extracts an in-flight brief."""
    src = _poll_src()
    # Anchor on the CONDITION, not the bare phrase — the ambiguous log line
    # above also contains it, and matching that instead passed against a build
    # with no guard at all (caught by this test failing on its first run).
    at = src.index('and _sn_verdict == "ambiguous"')
    window = src[at:at + 400]
    assert "not _hard_stop_signal" in window, (
        "a hard Stop-button DOM signal must block the label-free completion"
    )
    # scoped to ambiguous only — a positively observed "generating" is believed
    assert '_sn_verdict in ("generating"' not in window


@pytest.mark.parametrize("condition,why", [
    ("not _hard_stop_signal", "a live Stop button means it really is generating"),
    ("last_seen_len >= _SAFETY_NET_MIN_BRIEF_LEN", "a stub is not a finished brief"),
    ("stall_window_start is not None", "flatness must have actually started"),
    ("SAFETY_NET_CUA_SEC", "flat for the full window, not for one poll"),
    ("_page_is_dead", "a dead tab has no Stop button either (2026-08-09)"),
])
def test_every_guard_on_the_label_free_path_is_present(condition, why):
    assert condition in _poll_src(), why


def test_a_dead_page_is_not_completion():
    """The 2026-08-09 failure in one line: 'not generating' has two causes, and
    a page that navigated to about:blank was declared complete after 3289s."""
    src = _poll_src()
    at = src.index("_lf_dead")
    assert "NOT calling that complete" in src[at:at + 500]


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
    assert "Use what's on screen" in src


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
