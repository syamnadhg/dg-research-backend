"""Gemini's RESEARCH-fail Redo — wave 10, lane 7 (2026-09-18).

⛔⛔ THE WINDOW THIS COVERS HAD NO FAILURE READER AT ALL. The [2D] loop's
re-draft branch is gated on `not start_clicked`, so it is dead from the moment
Start research is pressed — and the screen this file is about only exists after
that. A Gemini research that died went salvage → card → park, with no page
action of any kind, while the control that would re-run it sat in the failed
turn. (The plan had that veto the other way round at one point; a hook hung
inside the pre-Start branch could never have run here.)

⭐⭐ AND THE ONE THING THAT HAD TO CHANGE IS THE FAILURE READER, NOT THE
MACHINERY. `_gemini_reads_as_failed` refuses any turn longer than
`_GEMINI_PLAN_FAIL_MAX_CHARS`, because on the PLAN screen the turn restates the
user's brief and a plan about an outage would otherwise read as a failed draft.
A research that dies leaves the "Researching N websites" card and whatever
arrived of the report in the SAME turn — hundreds to thousands of characters —
so the plan reader refuses all of it, `_gemini_regen_next_step` reads that as
`'settled'`, and nothing is ever clicked. That is measured here, not asserted:
`test_the_plan_reader_is_the_thing_that_refuses_a_dead_research`.

⛔ NO CAPTURE OF THIS PAGE STATE EXISTS. The owner gave both DOMs for the
CONTROL — Redo, and the "Don't personalise" row — and they are built and
executed against in test_gemini_redraft_0910.py; what is missing is a dump of
the page a RESEARCH failure produces, and the owner says that failure is
platform-side and may not reproduce on demand. So every arm of
`_gemini_research_fail_verdict` is a refusal, and each one is pinned by the
exact reason string it returns rather than by "it said no somehow".
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402
from _domshim import NODE, run_js, spec_from_html  # noqa: E402

pytestmark_node = pytest.mark.skipif(
    NODE is None, reason="node is required to run page JS")


# ── What a dying research actually leaves on screen ───────────────────────────
# The card, then however much of the report arrived, then the error. Only the
# last part is the failure; the rest is why the plan reader cannot see it.
_FILLER = ("Early findings point to a steady consolidation among the mid-tier "
           "operators, with margins holding up better than the headline "
           "numbers suggested. ")

_RESEARCH_BODY = ("Researching 25 websites\n"
                  "I looked at industry filings, three market reports and a "
                  "set of regulatory notices to build a picture of how the "
                  "sector moved over the last four quarters.\n" + _FILLER * 6)

# The 2026-09-10 capture's own wording, at the END of a long turn.
RESEARCH_FAILED_TEXT = (
    _RESEARCH_BODY + "\nSorry, something went wrong. Please try your request again.")

# The same length, ending healthily.
RESEARCH_HEALTHY_TEXT = (
    _RESEARCH_BODY + "\nHere is the full picture, with the sources listed below.")

# ⛔ A REPORT THAT TALKS ABOUT A FAILURE. The phrases are identical to a real
# error's; what differs is where they sit. This one's are in the BODY, with more
# than a tail's worth of report after them.
RESEARCH_ABOUT_A_FAILURE = (
    "Researching 25 websites\n"
    "The 2019 launch failed to complete and an error occurred during the "
    "second attempt, which the post-mortem attributes to a cooling fault.\n"
    + _FILLER * 6
    + "\nThat concludes the timeline of the programme.")

# ⛔⛔ A FINISHED RESEARCH THAT MENTIONS AN ERROR IN ITS CLOSING LINE. Without
# the completion refusal this reads as a dead research and the report — the
# thing the whole run exists to collect — is re-drafted away.
RESEARCH_COMPLETED_TEXT = (
    _RESEARCH_BODY
    + "\nI encountered an error fetching two of the sources and skipped them. "
      "I've completed your research — feel free to ask me follow-up questions.")


# ── The reader ────────────────────────────────────────────────────────────────

def test_the_plan_reader_is_the_thing_that_refuses_a_dead_research():
    """⛔⛔ THE MEASUREMENT THE WHOLE LANE RESTS ON. If the plan reader could
    see this turn there would be nothing to build: the machinery would simply
    work on this screen. It cannot, and this is why."""
    norm = research._gemini_norm(RESEARCH_FAILED_TEXT)
    assert len(norm) > research._GEMINI_PLAN_FAIL_MAX_CHARS, (
        "the fixture has to be a REAL dying-research turn — card plus report "
        "fragments plus the error — or it proves nothing")
    assert research._gemini_reads_as_failed(RESEARCH_FAILED_TEXT) is False
    assert research._gemini_research_reads_as_failed(RESEARCH_FAILED_TEXT) is True


def test_a_research_that_merely_talks_about_a_failure_is_not_a_failed_research():
    """The over-correction the size bound exists to stop, moved to this screen:
    the report's own subject matter must not read as the page's state."""
    assert research._gemini_research_reads_as_failed(RESEARCH_ABOUT_A_FAILURE) is False


def test_a_completed_research_is_never_read_as_failed():
    """⛔⛔ THE ONE MOVE ON THIS SCREEN THAT CANNOT BE UNDONE. The closing line
    names an error; the turn also says the research is done. Re-drafting it
    throws the report away."""
    assert research._GEMINI_COMPLETION_RE.search(RESEARCH_COMPLETED_TEXT)
    # and without the completion refusal it WOULD read as failed — the ending
    # on its own matches, so this fixture can tell the two readings apart
    tail = research._gemini_norm(RESEARCH_COMPLETED_TEXT)[
        -research._GEMINI_RESEARCH_FAIL_TAIL_CHARS:]
    assert research._gemini_reads_as_failed(tail) is True
    assert research._gemini_research_reads_as_failed(RESEARCH_COMPLETED_TEXT) is False


def test_a_healthy_long_turn_is_not_read_as_failed():
    assert research._gemini_research_reads_as_failed(RESEARCH_HEALTHY_TEXT) is False


def test_nothing_on_screen_is_not_a_failure():
    assert research._gemini_research_reads_as_failed("") is False
    assert research._gemini_research_reads_as_failed(None) is False


def test_the_window_is_the_TURNS_ENDING_and_it_is_measured():
    """The same sentence, inside the window and just outside it. Nothing else
    differs, so this is the window and not a wording."""
    phrase = "Sorry, something went wrong."
    filler = "x" * research._GEMINI_RESEARCH_FAIL_TAIL_CHARS
    assert research._gemini_research_reads_as_failed(filler + " " + phrase) is True
    assert research._gemini_research_reads_as_failed(phrase + " " + filler) is False


def test_a_short_failure_reads_the_same_through_both_readers():
    """⭐ On a turn that is short anyway the two functions read the same
    characters, so this screen's reader can never be a second opinion about the
    plan screen — only a differently-scoped one."""
    for text in ("Sorry, something went wrong. Please try your request again.",
                 "I seem to be encountering an error.",
                 "Here is your research plan. Start research?"):
        assert (research._gemini_research_reads_as_failed(text)
                is research._gemini_reads_as_failed(text)), text


# ── Which reader a screen gets ────────────────────────────────────────────────

def test_the_plan_screen_keeps_the_reader_it_was_measured_with():
    assert research._gemini_screen_reads_as_failed(
        RESEARCH_FAILED_TEXT, screen="plan") is False
    assert research._gemini_screen_reads_as_failed(
        RESEARCH_FAILED_TEXT, screen="research") is True


def test_an_unknown_screen_name_falls_back_to_the_stricter_reader():
    """A typo must not silently buy the wider reader."""
    assert research._gemini_screen_reads_as_failed(
        RESEARCH_FAILED_TEXT, screen="reserch") is False


# ── WHICH PART of a reading each screen is given ──────────────────────────────

_SPLIT = {"found": True, "text": RESEARCH_HEALTHY_TEXT,
          "tail": RESEARCH_FAILED_TEXT, "controls": [], "rows": []}


def test_the_research_screen_is_given_the_turns_ENDING():
    """⛔⛔ `text` IS THE FIRST 4000 CHARACTERS OF THE TURN. A research that dies
    has already rendered the card and however much of the report arrived, so on
    any real report the error sentence sits far past 4000 and is sliced off the
    end of `text`. A reader whose failure text cannot contain the failure is the
    fifteen-month defect in a new costume."""
    assert research._gemini_screen_failure_text(
        _SPLIT, screen="research") == RESEARCH_FAILED_TEXT
    assert research._gemini_screen_failure_text(
        _SPLIT, screen="plan") == RESEARCH_HEALTHY_TEXT


def test_a_reading_with_no_tail_still_gets_an_answer():
    """⭐ The fallback is `text`, never the empty string: a reading this reader
    did not produce must not come out as a silent 'nothing is wrong here'."""
    no_tail = {"found": True, "text": RESEARCH_FAILED_TEXT}
    assert research._gemini_screen_failure_text(
        no_tail, screen="research") == RESEARCH_FAILED_TEXT
    assert research._gemini_screen_failure_text({}, screen="research") == ""
    assert research._gemini_screen_failure_text(None, screen="research") == ""


# ── The reader, EXECUTED, on a turn longer than `text` can hold ───────────────

_LONG_BODY = ("<p>The mid-tier operators consolidated steadily through the "
              "period, and margins held up better than the headline numbers "
              "suggested.</p>") * 40

LONG_RESEARCH_FAIL_DOM = """
<model-response>
  <div class="response-container">
    <structured-content-container class="model-response-text">
      <message-content>
        <p>Researching 25 websites</p>
        %(body)s
        <p>Sorry, something went wrong. Please try your request again.</p>
      </message-content>
    </structured-content-container>
    <message-actions>
      <div class="actions-container-v2">
        <div class="buttons-container-v2">
          <gem-icon-button data-test-id="thumb-up-button">
            <button aria-label="Good response"></button></gem-icon-button>
          <gem-icon-button data-test-id="regenerate-button">
            <regenerate-button>
              <button aria-label="Redo"><mat-icon fonticon="refresh"></mat-icon></button>
            </regenerate-button></gem-icon-button>
          <gem-icon-button data-test-id="copy-button">
            <button aria-label="Copy"></button></gem-icon-button>
        </div>
      </div>
    </message-actions>
  </div>
</model-response>
""" % {"body": _LONG_BODY}


def _read(html: str) -> dict:
    """Run the production reader over `html` and return its parsed reading."""
    import json
    out = run_js(spec_from_html("<body>" + html + "</body>"),
                 research._GEMINI_LATEST_TURN_JS)
    return json.loads(out["ret"])


@pytestmark_node
def test_the_reader_carries_the_ending_of_a_turn_too_long_for_text():
    """⛔⛔ THE MEASUREMENT THAT DECIDES WHETHER THIS LANE CAN EVER FIRE. The
    fixture is a research turn of the size a real one has. `text` cannot reach
    its error; `tail` can, and it is the same node and the same property read
    from the other end."""
    r = _read(LONG_RESEARCH_FAIL_DOM)
    assert r["found"] is True
    assert len(r["text"]) >= 4000, (
        "the fixture has to overflow `text`, or it proves nothing about the "
        "slice")
    assert "something went wrong" not in r["text"], (
        "the whole point: the error is past the first 4000 characters")
    assert "something went wrong" in r["tail"]
    assert research._gemini_research_reads_as_failed(r["tail"]) is True
    # and the control is still reachable in the same reading
    control, why = research._gemini_regen_control(r["controls"])
    assert control is not None, why
    assert control["name"] == "Redo"


@pytestmark_node
def test_the_ending_is_the_TURNS_ending_not_the_pages():
    """⛔ THE PAGE-WIDE READ IS WHAT THIS WHOLE WAVE REMOVED. The rail's chat
    titles sit in the body after the turn; a tail taken from `document.body`
    would end in one of them, and a healthy research would read as failed on the
    strength of an old conversation's name."""
    html = (LONG_RESEARCH_FAIL_DOM.replace(
        "<p>Sorry, something went wrong. Please try your request again.</p>",
        "<p>Here is the full picture, with the sources listed below.</p>")
        + '<div class="chat-history-list">'
          "<div>Sorry, something went wrong. Please try your request again.</div>"
          "</div>")
    r = _read(html)
    assert "something went wrong" not in r["tail"]
    assert research._gemini_research_reads_as_failed(r["tail"]) is False


# ── Is the tab still in the conversation ──────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://gemini.google.com/app/748a05a1a2abc90c",
    "https://gemini.google.com/app/748a05a1a2abc90c?hl=en",
    "https://gemini.google.com/app/748a05a1a2abc90c#top",
])
def test_a_conversation_url_is_recognised(url):
    assert research._gemini_url_in_conversation(url) is True


@pytest.mark.parametrize("url", [
    "https://gemini.google.com/app",
    "https://gemini.google.com/app/",
    "https://gemini.google.com/app/?hl=en",
    "https://gemini.google.com/",
    "",
    None,
])
def test_the_bare_home_is_not_a_conversation(url):
    """#897a is the record of Gemini landing exactly here. There is no turn to
    re-draft on the home, and treating it as one is how a run walks out of its
    own conversation."""
    assert research._gemini_url_in_conversation(url) is False


# ── The gate ──────────────────────────────────────────────────────────────────

def _verdict(**kw):
    base = dict(cua_error=True, in_conversation=True, already_tried=False,
                found=True, latest_text=RESEARCH_FAILED_TEXT)
    base.update(kw)
    return research._gemini_research_fail_verdict(**base)


def test_the_gate_authorises_a_read_research_failure():
    assert _verdict() == "redraft"


def test_the_gate_refuses_without_an_independent_error_verdict():
    """⛔ NOTHING CALLED IT A FAILURE — not the CUA verdict and not this
    machine's own reader — so there is nothing to act on. (Until 2026-09-18 the
    CUA verdict was the ONLY key this lock had, and it is a key the screen
    cannot cut: see `test_the_gate_no_longer_waits_for_a_verdict_the_screen_
    cannot_produce`.)"""
    assert _verdict(cua_error=False) == "not_error"
    assert _verdict(cua_error=False, machine_failed=False) == "not_error"


def test_the_gate_refuses_a_second_attempt():
    assert _verdict(already_tried=True) == "already_tried"


def test_the_gate_refuses_outside_the_conversation():
    assert _verdict(in_conversation=False) == "not_in_conversation"


def test_the_gate_refuses_a_turn_it_could_not_read():
    """A probe that could not read the page must never come out as a reason to
    click — the same fail-closed rule the plan reader carries."""
    assert _verdict(found=False) == "no_turn"


def test_the_gate_refuses_a_turn_that_does_not_end_in_a_failure():
    assert _verdict(latest_text=RESEARCH_HEALTHY_TEXT) == "not_failed"
    assert _verdict(latest_text=RESEARCH_COMPLETED_TEXT) == "not_failed"


# ── The consumer, driven ──────────────────────────────────────────────────────

def _c(shape, index=0, name="Redo", visible=True, disabled=False):
    return {"shape": shape, "index": index, "name": name,
            "visible": visible, "disabled": disabled}


def _row(index, name, testid=""):
    return {"index": index, "name": name, "testid": testid}


class _FakeResearchPage:
    """A page inside a conversation that answers the reader with a scripted
    sequence of readings. Nothing here decides anything — every judgement under
    test belongs to research.py."""

    def __init__(self, readings, *, url="https://gemini.google.com/app/748a05a1"):
        self._readings = list(readings)
        self.url = url
        self.reads = 0
        self.clicks = []
        self.picks = []
        self.escapes = 0

        class _KB:
            def __init__(self, outer):
                self._outer = outer

            async def press(self, key):
                if key == "Escape":
                    self._outer.escapes += 1
        self.keyboard = _KB(self)

    async def evaluate(self, js, arg=None):
        import json
        if js is research._GEMINI_LATEST_TURN_JS:
            r = self._readings[min(self.reads, len(self._readings) - 1)]
            self.reads += 1
            return json.dumps(r)
        if js is research._GEMINI_REGEN_CLICK_JS:
            self.clicks.append(arg)
            return "Redo"
        if js is research._GEMINI_MENU_PICK_JS:
            self.picks.append(arg)
            return "Don't personalise"
        raise AssertionError("unexpected JS")


DEAD = {"found": True, "text": RESEARCH_FAILED_TEXT,
        "controls": [_c("testid")], "rows": []}
DEAD_MENU = {"found": True, "text": RESEARCH_FAILED_TEXT,
             "controls": [_c("testid")],
             "rows": [_row(0, "Don't personalise", "regenerate-option")]}
DEAD_UNREADABLE_MENU = {"found": True, "text": RESEARCH_FAILED_TEXT,
                        "controls": [_c("testid")], "rows": [_row(0, "Pin")]}
RERUNNING = {"found": True, "text": "Researching 25 websites",
             "controls": [], "rows": []}
DONE = {"found": True, "text": RESEARCH_COMPLETED_TEXT,
        "controls": [_c("testid")], "rows": []}


def _hook(page, *, cua_error=True, already_tried=False):
    return asyncio.run(research._gemini_redraft_failed_research(
        page, "Gemini", cua_error=cua_error, already_tried=already_tried,
        settle_s=0))


def test_the_hook_presses_redo_and_picks_the_row_on_a_dead_research():
    """⭐⭐ THE LANE, END TO END, ON THE SCREEN THE PLAN READER CANNOT SEE. One
    click, then the overlay the click opened is RESOLVED — a click on its own
    re-drafts nothing."""
    # the hook reads once itself to reach its verdict before it hands the turn
    # on, so the script carries one more DEAD than `_gemini_redraft_plan`'s own
    page = _FakeResearchPage([DEAD, DEAD, DEAD_MENU, RERUNNING])
    ok, acted, why = _hook(page)
    assert (ok, acted) == (True, True), why
    assert page.clicks == [{"shape": "testid", "index": 0}]
    assert page.picks == [{"testid": "regenerate-option",
                           "name": "Don't personalise"}]


# ── and the same, on readings whose text and tail DISAGREE ───────────────────
LONG_DEAD = {"found": True, "text": RESEARCH_HEALTHY_TEXT,
             "tail": RESEARCH_FAILED_TEXT, "controls": [_c("testid")],
             "rows": []}
LONG_DEAD_MENU = {"found": True, "text": RESEARCH_HEALTHY_TEXT,
                  "tail": RESEARCH_FAILED_TEXT, "controls": [_c("testid")],
                  "rows": [_row(0, "Don't personalise", "regenerate-option")]}
LONG_RERUNNING = {"found": True, "text": RESEARCH_HEALTHY_TEXT,
                  "tail": "Researching 25 websites", "controls": [], "rows": []}
LONG_SETTLED = {"found": True, "text": RESEARCH_FAILED_TEXT,
                "tail": RESEARCH_HEALTHY_TEXT, "controls": [_c("testid")],
                "rows": []}


def test_the_hook_acts_on_a_turn_whose_error_is_past_the_first_4000_chars():
    """⛔⛔ THE REALISTIC CASE, AND THE ONE THE HOOK LIVES OR DIES ON. Every real
    dying research looks like this: `text` holds the report's opening and no
    error at all; the error is only in the ending."""
    page = _FakeResearchPage([LONG_DEAD, LONG_DEAD, LONG_DEAD_MENU,
                              LONG_RERUNNING])
    ok, acted, why = _hook(page)
    assert (ok, acted) == (True, True), why
    assert page.clicks == [{"shape": "testid", "index": 0}]
    assert page.picks == [{"testid": "regenerate-option",
                           "name": "Don't personalise"}]


def test_the_hook_ignores_a_failure_that_is_no_longer_the_turns_ending():
    """The other direction, which is what makes the test above a measurement of
    the TAIL rather than of 'a failure appears somewhere in the reading'."""
    page = _FakeResearchPage([LONG_SETTLED, LONG_SETTLED, LONG_DEAD_MENU,
                              LONG_RERUNNING])
    ok, acted, why = _hook(page)
    assert (ok, acted) == (False, False)
    assert why == "not re-drafting the research: not_failed"
    assert page.clicks == []


def test_a_turn_that_never_changed_is_never_reported_as_a_redraft():
    """⛔⛔ THE FABRICATED SUCCESS THIS SCREEN MAKES EASY. The outcome check has
    to use the SAME reader the entry did: judged with the plan reader, this long
    unchanged turn reads as 'no longer failed' and the call reports a re-draft
    for a page that did not move — the retired helper's defect in a new place."""
    page = _FakeResearchPage([DEAD, DEAD, DEAD_MENU, DEAD])
    ok, acted, why = _hook(page)
    assert (ok, acted) == (False, True), why
    assert len(page.clicks) == 1


def test_an_overlay_we_cannot_name_is_dismissed_and_is_not_a_success():
    """A CDK backdrop left up swallows every later click on the page, ours and
    the CUA ladder's — and opening a menu is not a re-draft."""
    page = _FakeResearchPage([DEAD, DEAD, DEAD_UNREADABLE_MENU, DEAD])
    ok, acted, why = _hook(page)
    assert (ok, acted) == (False, True), why
    assert page.picks == []
    assert page.escapes >= 1


def test_the_hook_refuses_a_screen_nothing_independent_called_a_failure():
    page = _FakeResearchPage([DEAD, DEAD_MENU, RERUNNING])
    ok, acted, why = _hook(page, cua_error=False)
    assert (ok, acted) == (False, False)
    assert why == "not re-drafting the research: not_error"
    assert page.clicks == []


def test_the_hook_refuses_a_second_attempt_in_the_same_phase():
    page = _FakeResearchPage([DEAD, DEAD_MENU, RERUNNING])
    ok, acted, why = _hook(page, already_tried=True)
    assert (ok, acted) == (False, False)
    assert why == "not re-drafting the research: already_tried"
    assert page.clicks == []


def test_the_hook_refuses_a_tab_that_left_the_conversation():
    page = _FakeResearchPage([DEAD, DEAD_MENU, RERUNNING],
                             url="https://gemini.google.com/app")
    ok, acted, why = _hook(page)
    assert (ok, acted) == (False, False)
    assert why == "not re-drafting the research: not_in_conversation"
    assert page.clicks == []


def test_the_hook_leaves_a_completed_research_alone():
    page = _FakeResearchPage([DONE, DEAD_MENU, RERUNNING])
    ok, acted, why = _hook(page)
    assert (ok, acted) == (False, False)
    assert why == "not re-drafting the research: not_failed"
    assert page.clicks == []


def test_the_hook_refuses_a_page_it_could_not_read():
    page = _FakeResearchPage([{"found": False, "text": "", "controls": [],
                               "rows": []}])
    ok, acted, why = _hook(page)
    assert (ok, acted) == (False, False)
    assert why == "not re-drafting the research: no_turn"
    assert page.clicks == []


def test_a_page_whose_url_cannot_be_read_is_not_in_a_conversation():
    """Fail-closed: an unreadable URL is not permission to click."""
    class _NoUrl(_FakeResearchPage):
        @property
        def url(self):
            raise RuntimeError("the page is gone")

        @url.setter
        def url(self, _v):
            pass

    page = _NoUrl([DEAD, DEAD_MENU, RERUNNING])
    ok, acted, why = _hook(page)
    assert (ok, acted) == (False, False)
    assert why == "not re-drafting the research: not_in_conversation"
    assert page.clicks == []


def test_the_hook_does_not_drive_the_page_after_stop():
    """"No post-Stop DOM driving" is the standing rule, and this is the
    outermost thing on the path — it must not even read."""
    class _Stopping:
        def is_stop(self):
            return True

    page = _FakeResearchPage([DEAD, DEAD_MENU, RERUNNING])
    real = research._controls
    research._controls = _Stopping()
    try:
        ok, acted, why = _hook(page)
    finally:
        research._controls = real
    assert (ok, acted) == (False, False)
    assert why == "stop requested before the research re-draft"
    assert page.reads == 0
    assert page.clicks == []


# ── And the plan screen is unchanged ──────────────────────────────────────────

PLAN_ABOUT_FAILURES = {
    "found": True,
    "text": ("Here is my research plan for the 2019 launch. I will establish "
             "why the mission failed to complete, what the error report said, "
             "and how the programme responded.\n" + _FILLER * 5
             + "\nThe final section will cover why the migration was unable to "
               "complete."),
    "controls": [_c("testid")], "rows": []}


def test_the_plan_path_still_refuses_a_long_plan_about_failures():
    """⛔ THE DEFAULT IS `plan`, AND IT HAS TO STAY THERE. Read with this
    screen's reader, this plan's ENDING says it failed — and a re-drafted plan
    is destroyed work. Nothing that calls `_gemini_redraft_plan` without naming
    a screen may buy the wider reader."""
    page = _FakeResearchPage([PLAN_ABOUT_FAILURES, DEAD_MENU, RERUNNING])
    ok, acted, in_flight, why = asyncio.run(
        research._gemini_redraft_plan(page, "2D-plan", settle_s=0))
    assert (ok, acted, in_flight) == (False, False, False), why
    assert page.clicks == []
    # and the fixture really is one this screen's reader would have clicked
    assert research._gemini_research_reads_as_failed(
        PLAN_ABOUT_FAILURES["text"]) is True


# ── Where it is wired ─────────────────────────────────────────────────────────
# ⛔ The poll loop is not driven by any test in this suite, so these are
# structural — and they are counts and ORDERINGS, never "the name appears
# somewhere", against a source with comments and docstrings blanked out.
_POLL = code_only_deep(research.poll_all_agents_round_robin)


def test_the_hook_is_called_exactly_once_and_only_for_gemini():
    assert _POLL.count("_gemini_redraft_failed_research(") == 1
    call = _POLL.index("_gemini_redraft_failed_research(")
    gate = _POLL.rindex('normalize_agent_key(name) == "gemini"', 0, call)
    latch = _POLL.rindex('p["_gemini_research_redraft_used"] = True', 0, call)
    assert gate < latch < call, (
        "the attempt is Gemini's alone, and the once-per-phase latch is taken "
        "BEFORE the page is touched — a refusal must not be able to become a "
        "retry loop against a page that is already unwell")


def test_the_hook_sits_in_the_error_branch_after_the_salvage():
    """⛔ A re-draft replaces the turn, so clicking before the salvage would
    destroy the partial output the branch is about to keep."""
    call = _POLL.index("_gemini_redraft_failed_research(")
    branch = _POLL.rindex("if is_error:", 0, call)
    salvage = _POLL.index("_err_text = await extract_fns[name](", branch)
    assert branch < salvage < call


def test_only_a_landed_redraft_keeps_gemini_in_rotation():
    """⛔ `acted` is not the outcome. A click that opened a menu and re-drafted
    nothing must fall through to the card, exactly as it would have with no hook
    at all — that is what makes this incapable of being worse than the branch it
    sits in."""
    call = _POLL.index("_gemini_redraft_failed_research(")
    cont = _POLL.index("continue", call)
    between = _POLL[call:cont]
    assert between.count("if _rr_ok:") == 1
    assert "_rr_acted" not in between.split("if _rr_ok:")[1], (
        "nothing between the success test and the continue may consult `acted`")


def test_the_hook_is_not_inside_the_reload_rescue_which_can_never_run_for_gemini():
    """RELOAD_SAFE is {"ChatGPT", "Claude"} because Gemini's SPA lands on the
    empty home (#897a). A hook placed inside that rescue would be as dead as one
    placed inside the pre-Start branch."""
    assert 'RELOAD_SAFE = {"ChatGPT", "Claude"}' in _POLL
    call = _POLL.index("_gemini_redraft_failed_research(")
    rescue = _POLL.index('if (name in RELOAD_SAFE and not p.get("_reload_rescue_used")',
                         _POLL.rindex("if is_error:", 0, call))
    assert call < rescue


# ═══ THE THIRD GUARD IN THIS LANE THAT COULD NOT FIRE (repaired 2026-09-18) ═══
#
# ⛔⛔ THE HOOK'S ONLY DOOR WAS THE CUA `error` VERDICT, AND THE SCREEN CANNOT
# PRODUCE IT. `PROMPT_DIAGNOSE` says "If an error banner or blocking popup is
# visible -> ERROR. Otherwise default to GENERATING", and the Gemini-only
# platform hint appended to that same mission ends "...otherwise say 'still
# generating'". A Gemini research failure renders as a chat BUBBLE — neither a
# banner nor a popup — so the CUA answers `generating`, the poll loop waits, and
# the reader that can read that bubble perfectly is never asked. Zero clicks,
# exactly like `_try_inpage_retry_on_research_fail` for fifteen months.
#
# ⭐ WHICH OF THE TWO REPAIRS, AND WHY. Teaching the platform hint that a bubble
# is an error was the other option and was NOT taken: a prompt can only be
# pinned by asserting its own words back (a test a comment can satisfy and a
# vision model need not obey), and widening the CUA's `error` verdict widens the
# branch that ends in `fail_agent` + out of rotation — it would buy the click by
# putting healthy agents in front of the drop. The machine's own reader is
# deterministic, drivable, and enters a path that can only press Redo once.

def _machine(page, *, p=None, settle_s=0, redraft_settle_s=0):
    state = p if p is not None else {"page": page}
    return state, asyncio.run(research._gemini_research_redraft_on_own_reading(
        state, "Gemini", settle_s=settle_s, redraft_settle_s=redraft_settle_s))


def test_the_gate_no_longer_waits_for_a_verdict_the_screen_cannot_produce():
    """⛔⛔ THE GATE ARM ITSELF. `cua_error` False and the machine's own reader
    True is the ONLY combination a real Gemini research failure can present, and
    until this wave it returned `'not_error'` — the refusal that made every
    other arm unreachable."""
    assert _verdict(cua_error=False, machine_failed=True) == "redraft"
    # …and the other four refusals still bind on a machine entry, so the entry
    # is a second KEY, not a second lock removed.
    assert _verdict(cua_error=False, machine_failed=True,
                    already_tried=True) == "already_tried"
    assert _verdict(cua_error=False, machine_failed=True,
                    in_conversation=False) == "not_in_conversation"
    assert _verdict(cua_error=False, machine_failed=True,
                    found=False) == "no_turn"
    assert _verdict(cua_error=False, machine_failed=True,
                    latest_text=RESEARCH_HEALTHY_TEXT) == "not_failed"


def test_the_machine_reads_the_bubble_and_the_hook_IS_REACHED():
    """⛔⛔ THE PIN THAT THE LANE CAN FIRE AT ALL, AND IT IS THE CLICK THAT
    PROVES IT — not a reader returning True. Three dead guards in a row on this
    one lane were each covered by a test showing the READER worked; what none of
    them drove was the path from "the screen is in this state" to "the control
    was pressed". This drives it, with no CUA verdict anywhere in the call."""
    # two settled readings, the gate's own re-read, then `_gemini_redraft_plan`'s
    # three (entry, post-click, after the settle)
    page = _FakeResearchPage([LONG_DEAD, LONG_DEAD, LONG_DEAD, LONG_DEAD,
                              LONG_DEAD_MENU, LONG_RERUNNING])
    p, (ok, why) = _machine(page)
    assert ok is True, why
    assert page.clicks == [{"shape": "testid", "index": 0}], (
        "the hook was not reached: the entry that replaces the unsatisfiable "
        "CUA verdict must end in a press of Gemini's own Redo")
    assert page.picks == [{"testid": "regenerate-option",
                           "name": "Don't personalise"}]


def test_a_landed_machine_redraft_resets_the_clocks_and_rearms_the_start_watch():
    """The same state the error-branch entry leaves behind, because it is the
    same function that writes it — a re-drafted turn is a NEW turn, so the
    late-Start watch and its click budget go with the clocks."""
    page = _FakeResearchPage([LONG_DEAD, LONG_DEAD, LONG_DEAD, LONG_DEAD,
                              LONG_DEAD_MENU, LONG_RERUNNING])
    p, (ok, why) = _machine(page, p={"page": page, "last_growth_time": 0.0,
                                     "last_heartbeat": 0.0,
                                     "gemini_watch_click_count": 3})
    assert ok is True, why
    assert p["last_growth_time"] > 0 and p["last_heartbeat"] > 0
    assert p["gemini_watch_start"] is True
    assert p["gemini_watch_click_count"] == 0


def test_the_machine_entry_refuses_a_turn_THAT_IS_STILL_MOVING():
    """⛔⛔ THE GUARD THE SECOND ENTRY CANNOT GO WITHOUT, AND THE ONE THING THIS
    REPAIR MAKES NEWLY POSSIBLE. Reading "this turn ends with a failure" once is
    a SAMPLE. A research still streaming its report is mid-sentence at every
    instant, and a report ABOUT a failure whose newest paragraph names it reads
    exactly like a dead one. Two readings a real gap apart separate them: a
    streaming turn is never byte-identical twice, a dead one never changes."""
    moving_a = dict(LONG_DEAD, tail=_FILLER + "the migration was unable to complete")
    moving_b = dict(LONG_DEAD,
                    tail=_FILLER + "the migration was unable to complete, and the")
    assert research._gemini_research_reads_as_failed(moving_a["tail"]) is True
    assert research._gemini_research_reads_as_failed(moving_b["tail"]) is True
    page = _FakeResearchPage([moving_a, moving_b, LONG_DEAD_MENU, LONG_RERUNNING])
    p, (ok, why) = _machine(page)
    assert ok is False
    assert "still moving" in why
    assert page.clicks == [], "a streaming research must never be re-drafted"
    assert not p.get("_gemini_research_redraft_used"), (
        "a turn we refused to judge must not cost the phase its one attempt")


def test_the_machine_entry_costs_one_read_on_a_healthy_research():
    """⭐ The first reading is the cheap one: a healthy turn fails the failure
    test and this returns without sleeping or reading a second time, so the
    price on every other CUA tick is one DOM read."""
    page = _FakeResearchPage([{"found": True, "text": RESEARCH_HEALTHY_TEXT,
                               "tail": RESEARCH_HEALTHY_TEXT,
                               "controls": [_c("testid")], "rows": []}])
    p, (ok, why) = _machine(page)
    assert ok is False
    assert page.reads == 1
    assert page.clicks == []


def test_the_machine_entry_spends_its_one_attempt_per_phase():
    page = _FakeResearchPage([LONG_DEAD, LONG_DEAD, LONG_DEAD, LONG_DEAD,
                              LONG_DEAD_MENU, LONG_DEAD])
    p, (ok, why) = _machine(page)
    assert ok is False, "the turn never changed, so this is not a re-draft"
    assert p["_gemini_research_redraft_used"] is True
    before = len(page.clicks)
    _p2, (ok2, why2) = _machine(page, p=p)
    assert ok2 is False
    assert "already spent" in why2
    assert len(page.clicks) == before, (
        "the latch is taken BEFORE the page is touched, so a refusal can never "
        "become a retry loop against a page that is already unwell")


def test_the_machine_entry_leaves_a_completed_research_alone():
    page = _FakeResearchPage([{"found": True, "text": RESEARCH_COMPLETED_TEXT,
                               "tail": RESEARCH_COMPLETED_TEXT,
                               "controls": [_c("testid")], "rows": []}])
    p, (ok, why) = _machine(page)
    assert ok is False
    assert page.clicks == []


def test_the_machine_entry_does_not_drive_the_page_after_stop():
    """⛔ "No post-Stop DOM driving" is the standing rule, and this entry is now
    the outermost thing on the path — its settled reading touches the page two
    ticks before `_gemini_redraft_failed_research` gets to ask, so the check has
    to be here as well. It must not even READ."""
    class _Stopping:
        def is_stop(self):
            return True

    page = _FakeResearchPage([LONG_DEAD, LONG_DEAD, LONG_DEAD, LONG_DEAD,
                              LONG_DEAD_MENU, LONG_RERUNNING])
    real = research._controls
    research._controls = _Stopping()
    try:
        p, (ok, why) = _machine(page)
    finally:
        research._controls = real
    assert ok is False
    assert page.reads == 0, "it must not even have looked"
    assert page.clicks == []


# ── Where the second entry is wired, and where it deliberately is NOT ─────────

def test_the_machine_entry_sits_on_the_branch_the_cua_actually_lands_on():
    """⛔⛔ THE POSITION IS THE REPAIR. A Gemini research-fail bubble makes the
    CUA answer `generating`, so the ONLY branch it reaches is this one — a
    second entry anywhere else would be the fourth dead guard in this lane."""
    assert _POLL.count("_gemini_research_redraft_on_own_reading(") == 1
    call = _POLL.index("_gemini_research_redraft_on_own_reading(")
    branch = _POLL.rindex("if is_generating and not is_done:", 0, call)
    gate = _POLL.index('normalize_agent_key(name) == "gemini"', branch)
    assert branch < gate < call
    # and it really is the branch that keeps waiting, not one that resolves
    assert _POLL.index('p["done_count"] = 0', call) > call


def test_the_machine_entry_is_NOT_in_the_error_branch_that_drops_the_agent():
    """⛔⛔ THE HARM THIS PLACEMENT REFUSES. The `is_error` branch salvages,
    cards and DROPS the agent from rotation; entering it on OUR OWN reading
    would mean one misread ends a healthy research. The machine entry can only
    press Redo once and leave the agent exactly where it was, so its worst case
    is the behaviour that exists without it."""
    call = _POLL.index("_gemini_research_redraft_on_own_reading(")
    err = _POLL.rindex("if is_error:", 0, call)
    # every statement of the error branch is behind us: the branch's own hook,
    # its reload rescue and its fail card all precede this call site.
    assert _POLL.index("_gemini_redraft_failed_research(", err) < call
    assert _POLL.index('if (name in RELOAD_SAFE and not p.get("_reload_rescue_used")',
                       err) < call


def test_the_two_entries_cannot_drift_apart_on_what_a_landed_redraft_leaves():
    """⛔⛔ TWO COPIES, PINNED KEY-FOR-KEY AGAINST EACH OTHER. The error
    branch's four writes stay INLINE because the stale-reload suite parses that
    branch for them — hoisting them into the shared writer would move the rule
    out from under its own measurement. So the copies are held together here
    instead: parsed from both trees, compared as SETS of keys, so adding a key
    to one entry and not the other fails whichever one was forgotten."""
    import ast
    import textwrap

    def _p_writes(src):
        keys = set()
        for node in ast.walk(ast.parse(textwrap.dedent(src))):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            tgt = node.targets[0]
            if (isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name) and tgt.value.id == "p"
                    and isinstance(tgt.slice, ast.Constant)):
                keys.add(tgt.slice.value)
        return keys

    shared = _p_writes(inspect.getsource(
        research._gemini_note_research_redraft_landed))
    assert shared == {"last_heartbeat", "last_growth_time",
                      "gemini_watch_start", "gemini_watch_click_count"}

    # the error branch's own copy, taken from the `if _rr_ok:` arm alone
    poll = textwrap.dedent(inspect.getsource(research.poll_all_agents_round_robin))
    inline = None
    for node in ast.walk(ast.parse(poll)):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "_rr_ok"):
            inline = _p_writes(ast.unparse(node))
            break
    assert inline is not None, "the error branch no longer has an `if _rr_ok:` arm"
    assert inline == shared, (
        f"the two research-re-draft entries disagree about what a landed "
        f"re-draft leaves behind: inline={sorted(inline)} "
        f"shared={sorted(shared)}")

    # and the machine entry really does go through the shared writer
    src = code_only_deep(research._gemini_research_redraft_on_own_reading)
    assert src.count("_gemini_note_research_redraft_landed(p)") == 1


# ═══ THE COMPLETION REFUSAL WAS STRUCTURALLY BLIND (repaired 2026-09-18) ══════
#
# ⛔⛔ IT SEARCHED THE 400-CHAR TAIL, AND THIS FILE'S OWN GEMINI HINT SAYS THE
# COMPLETION LINE SITS ABOVE THE REPORT TILE. So on the layout the module itself
# documents, the one refusal the lane calls un-undoable could not see its own
# marker. The turn is only readable in two pieces — `text` is its first 4000
# characters, `tail` its last 400 — so the refusal now runs over both.

_COMPLETED_ABOVE_THE_REPORT = (
    "I've completed your research. Feel free to ask me follow-up questions or "
    "request changes.\n" + _RESEARCH_BODY + _FILLER * 40)
_COMPLETED_REPORT_ENDING = (
    _FILLER * 3 + "\nThe 2019 attempt was unable to complete, and the vendor's "
    "own note said something went wrong.")

_COMPLETED_SPLIT = {"found": True,
                    "text": _COMPLETED_ABOVE_THE_REPORT[:4000],
                    "tail": _COMPLETED_REPORT_ENDING[-400:],
                    "controls": [_c("testid")], "rows": []}


def test_the_completion_line_above_the_report_is_outside_the_tail():
    """The fixture is the layout the module's own platform hint describes, or it
    proves nothing: completion at the top, report below, error words at the end.
    Both halves are asserted, so a fixture that drifts fails here first."""
    assert research._GEMINI_COMPLETION_RE.search(_COMPLETED_SPLIT["text"])
    assert not research._GEMINI_COMPLETION_RE.search(_COMPLETED_SPLIT["tail"])
    assert len(_COMPLETED_ABOVE_THE_REPORT + _COMPLETED_REPORT_ENDING) > 4400


def test_a_finished_research_is_refused_even_when_only_the_tail_is_read():
    """⛔⛔ THE ONE MOVE ON THIS SCREEN THAT CANNOT BE UNDONE, ON THE LAYOUT THE
    FILE ITSELF DOCUMENTS. Read the tail alone and this finished research is a
    dead one; the report the whole run exists to collect is re-drafted away."""
    tail = _COMPLETED_SPLIT["tail"]
    text = _COMPLETED_SPLIT["text"]
    assert research._gemini_research_reads_as_failed(tail) is True, (
        "the fixture has to be one the TAIL cannot tell apart, or this test "
        "measures nothing")
    assert research._gemini_research_reads_as_failed(tail, full_text=text) is False
    assert research._gemini_research_fail_verdict(
        cua_error=True, in_conversation=True, already_tried=False, found=True,
        latest_text=tail, full_text=text) == "not_failed"


def test_the_hook_refuses_a_finished_research_whose_completion_line_is_at_the_top():
    """⭐ THE CONSUMER, DRIVEN. The reading is the one the production JS emits —
    `text` is the turn's opening, `tail` its ending — and the hook must not
    touch it."""
    page = _FakeResearchPage([_COMPLETED_SPLIT, LONG_DEAD_MENU, LONG_RERUNNING])
    ok, acted, why = _hook(page)
    assert (ok, acted) == (False, False)
    assert why == "not re-drafting the research: not_failed"
    assert page.clicks == []


def test_the_machine_entry_refuses_it_too():
    """Both doors, one refusal — the completion marker is checked inside the
    reader, so neither entry can reach a finished research."""
    page = _FakeResearchPage([_COMPLETED_SPLIT])
    p, (ok, why) = _machine(page)
    assert ok is False
    assert page.clicks == []
    assert not p.get("_gemini_research_redraft_used")


def test_the_outcome_check_reads_the_whole_turn_too():
    """⛔ The post-click re-read decides whether a click was a re-draft. If it
    keeps reading the tail alone, a turn that came back COMPLETED — the best
    possible outcome — is reported as 'still reads as failed' and the agent is
    carded. Same reader, same two pieces, both sides of the click."""
    page = _FakeResearchPage([LONG_DEAD, LONG_DEAD_MENU, _COMPLETED_SPLIT])
    ok, acted, in_flight, why = asyncio.run(
        research._gemini_redraft_plan(page, "Gemini", settle_s=0,
                                      screen="research"))
    assert (ok, acted, in_flight) == (True, True, False), why
