"""Gemini page JS that no test has ever EXECUTED — 2026-09-17, wave 10 lane 2.

Three pieces of production JavaScript, all of them pinned today by assertions
about their SOURCE TEXT and nothing else:

  * the 2026-09-10 re-draft reader's `isVisible` and the clicker's re-check.
    Both read `getBoundingClientRect` + `getComputedStyle`. Until the shim's
    computed style became attribute-driven (same change as this file), only the
    SIZE half could be driven negative by a fixture — so the style half had
    never executed once, in either function. It executes here.
  * the Start trio (`_GEMINI_START_PREDICATE_JS` and the two functions built
    from it). #905 was a live incident: the run clicked the DISABLED skeleton
    Start that Gemini renders while the plan is still streaming, and went blind
    on a control rendered as `[role="button"]` rather than `<button>`. Both
    fixes are asserted today by `startswith`/`in` checks on the source string.
  * `_GEMINI_DR_STATE_JS`, the Deep-Research state probe, which decides whether
    Gemini is in research mode before a brief is ever pasted.

⛔ Page code no test EXECUTES rots. The fifteen-month re-draft defect was two
wrong words guarded by a test that re-compiled the pattern in Python and fed it
a sentence its own author had written.

⛔ NO `skipif(NODE is None)` — see the note in test_domshim_computed_style_0917
and the suite-wide requirement in test_node_is_required_not_skipped_0917. If node
is absent these fail; they do not vanish.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research  # noqa: E402
from _domshim import run_js, spec_from_html  # noqa: E402

# ⭐ THE OWNER'S OWN CAPTURE, IMPORTED RATHER THAN COPIED. A second transcription
# of the failed turn would be a fixture built to match this file's theory of the
# markup, which is the exact failure the 09-10 wave was written to end.
from test_gemini_redraft_0910 import CAPTURED_FAIL_TURN  # noqa: E402


# ── The 09-10 visibility check, executed for the first time ──────────────────

def _read(html: str) -> dict:
    out = run_js(spec_from_html("<body>" + html + "</body>"),
                 research._GEMINI_LATEST_TURN_JS)
    return json.loads(out["ret"])


def _style_on_redo(attrs: str) -> str:
    """The owner's capture with `attrs` added to the Redo BUTTON and nothing else.

    ⛔ The geometry, the wrapper chain, the five sibling controls and the failure
    text are all untouched, so the only thing that can change a reading is the
    style attribute itself.
    """
    old = '<button aria-label="Redo">'
    assert CAPTURED_FAIL_TURN.count(old) == 1, (
        "the capture's Redo button is no longer written the way this file "
        "patches it — every measurement below would silently test the "
        "unmodified page")
    return CAPTURED_FAIL_TURN.replace(old, '<button aria-label="Redo" ' + attrs + '>')


def _testid(reading: dict) -> dict:
    hits = [c for c in reading["controls"] if c["shape"] == "testid"]
    assert len(hits) == 1, f"expected exactly one test-id'd control, got {hits}"
    return hits[0]


# `op` sits BELOW the reader's 0.1 floor rather than at zero: a gate written as
# `opacity > 0` would still pass this, and a gate written as `!== '0'` would too.
HIDDEN_BY_STYLE = [
    ('disp="none"', "display:none"),
    ('vis="hidden"', "visibility:hidden"),
    ('op="0.05"', "opacity under the 0.1 floor"),
]


def test_the_captured_control_reads_visible_and_enabled_when_nothing_hides_it():
    """The control case for everything below. Without it, "not visible" could be
    satisfied by a reader that had simply stopped finding the button."""
    r = _read(CAPTURED_FAIL_TURN)
    c = _testid(r)
    assert (c["name"], c["visible"], c["disabled"]) == ("Redo", True, False)
    control, why = research._gemini_regen_control(r["controls"])
    assert why == "matched by testid"
    assert control["name"] == "Redo"


@pytest.mark.parametrize("attrs,css", HIDDEN_BY_STYLE)
def test_a_control_hidden_only_by_computed_style_is_read_as_not_visible(attrs, css):
    """⛔⛔ THE CHECK THIS LANE EXISTS FOR, RUN FOR THE FIRST TIME. The reader's
    `isVisible` has four clauses and only the size one had ever been exercised;
    the other three could have been deleted, inverted or misspelled and every
    test in the repo would still have passed."""
    r = _read(_style_on_redo(attrs))
    c = _testid(r)
    assert c["name"] == "Redo", "the control is still THERE — this is not a lost button"
    assert c["disabled"] is False, "and it is not being refused for the other reason"
    assert c["visible"] is False, f"{css} must reach the reader"
    # ⛔ THE SIZE GATE CANNOT BE WHAT REFUSED IT. Identical markup, identical
    # geometry, one inert attribute in place of the style one.
    assert _testid(_read(_style_on_redo('data-probe="1"')))["visible"] is True

    control, why = research._gemini_regen_control(r["controls"])
    assert control is None
    assert why == "testid present but not visible"


@pytest.mark.parametrize("attrs,css", HIDDEN_BY_STYLE)
def test_the_clicker_refuses_a_control_that_went_invisible_by_style_mid_flight(attrs, css):
    """⛔ RE-CHECKED AT THE CLICK, NOT ONLY AT THE READING — and that re-check's
    style clauses had never run either. The reading and the click are two round
    trips apart; a control that goes `display:none` in between must not be
    clicked and must not hand back a truthy label. That is #905's
    disabled-skeleton Start wearing yet another costume."""
    r = _read(CAPTURED_FAIL_TURN)                       # read the healthy page
    control, _ = research._gemini_regen_control(r["controls"])
    arg = {"shape": control["shape"], "index": control["index"]}

    out = run_js(spec_from_html("<body>" + _style_on_redo(attrs) + "</body>"),
                 research._GEMINI_REGEN_CLICK_JS, arg)
    assert out["ret"] == "", css
    assert out["clicks"] == [], f"a control hidden by {css} was clicked"

    # ...and the same call against the same markup, minus the style attribute,
    # does click — so the refusal above is not a clicker that clicks nothing.
    live = run_js(spec_from_html("<body>" + _style_on_redo('data-probe="1"') + "</body>"),
                  research._GEMINI_REGEN_CLICK_JS, arg)
    assert (live["ret"], live["clicks"]) == ("Redo", ["Redo"])


# ── The Start trio (#905), executed for the first time ───────────────────────

# Gemini renders the control both ways and the #905 forensics caught each one
# failing separately: (a) the disabled skeleton rendered while the plan streams,
# (b) a `[role="button"]` the `<button>`-only match could not see.
START_BUTTON = '<button>Start research</button>'
START_ARIA_ROLE = '<div role="button" aria-label="Start research"></div>'
START_SKELETON = '<button disabled>Start research</button>'
START_ARIA_DISABLED = '<button aria-disabled="true">Start research</button>'
START_UNRENDERED = '<button w="4" h="4">Start research</button>'
UNRELATED_BUTTON = '<button aria-label="Share &amp; export">Share</button>'
# ⛔⛔ THE CLAUSE NOTHING WAS DRIVING. Every other clause of this predicate is
# killed by a case above; widening `'start research'` to `'start'` survived all
# 343 Gemini tests on 09-18, because the only negative fixture in this file was
# "Share & export", which contains no "start" at all. The predicate feeds
# `_GEMINI_CLICK_START_JS`, which CLICKS THE FIRST MATCH, and `CAND` includes
# `[role="button"]` containers whose textContent carries whatever is inside
# them — so a bare word match presses the wrong control on a live page. (7.9-5b:
# "a bare word match is not a signal".) These two are enabled, rendered, plainly
# pressable, and named with the word — the name is the ONLY thing that may
# refuse them.
START_NEW_CHAT = '<button>Start a new chat</button>'
GET_STARTED = '<div role="button" aria-label="Get started"></div>'


def _start(html: str) -> tuple:
    """(present?, clicked-and-what) for one page, through BOTH trio members."""
    spec = spec_from_html("<body>" + html + "</body>")
    present = run_js(spec, research._GEMINI_START_PRESENT_JS)
    clicked = run_js(spec, research._GEMINI_CLICK_START_JS)
    return present["ret"], (clicked["ret"], clicked["clicks"])


@pytest.mark.parametrize("html,label", [
    (START_BUTTON, "Start research"),
    (START_ARIA_ROLE, "Start research"),
])
def test_both_rendered_shapes_of_start_research_are_found_and_clicked(html, label):
    """⛔ BOTH ELEMENT SHAPES. The pre-#905 matcher queried `<button>` only and
    went blind in a run whose own stall diagnostic was dumping a visible
    `{"aria":"Start research"}` control at the same moment."""
    assert _start(html) == (True, (True, [label]))


@pytest.mark.parametrize("html,why", [
    (START_SKELETON, "the `disabled` property Gemini sets while the plan streams"),
    (START_ARIA_DISABLED, "`aria-disabled=\"true\"`, which is a string not a property"),
    (START_UNRENDERED, "a 4x4 rect — present in the DOM, not rendered"),
    (UNRELATED_BUTTON, "an enabled button that is not Start research"),
    (START_NEW_CHAT, "a pressable button whose text merely STARTS WITH the word "
                     "— matching it re-opens the chat and loses the run"),
    (GET_STARTED, "a pressable role=button whose accessible name merely "
                  "CONTAINS the word"),
])
def test_start_research_is_neither_reported_nor_clicked_when_it_is_not_pressable(html, why):
    """⛔⛔ #905's ACTUAL INCIDENT. Clicking the disabled skeleton reported
    success and did nothing, and the run then waited out a research that had
    never been started. Each refusal below is a separate clause of one
    predicate, and not one of them had ever been executed."""
    assert _start(html) == (False, (False, [])), why


def test_the_skeleton_is_skipped_and_the_real_control_below_it_is_the_one_clicked():
    """⛔ THE ORDERING CASE, WHICH IS THE ONE THAT ACTUALLY HAPPENED: the page
    holds BOTH at once for a moment. A predicate that stopped at the first
    textual match would click the skeleton and return true."""
    page = START_SKELETON + '<button aria-label="Start research now"></button>'
    assert _start(page) == (True, (True, ["Start research now"]))


def test_start_is_clicked_exactly_once_even_when_the_page_offers_two():
    """The loop returns on its first successful click. Two identical controls
    must produce ONE click, not two — a double press on Gemini re-sends."""
    second = '<div role="button" aria-label="Start research (second)"></div>'
    present, (ret, clicks) = _start(START_BUTTON + second)
    assert (present, ret) == (True, True)
    # Exactly one click, and it is the FIRST control — the second carries its own
    # label so a loop that fell through to it would be named, not just counted.
    assert clicks == ["Start research"], clicks


# ── The Deep-Research state probe, executed for the first time ───────────────

DR_RESEARCH_MODE = """
<rich-textarea><div contenteditable="true"
    data-placeholder="What do you want to research?"></div></rich-textarea>
<button aria-pressed="true">Deep research</button>
"""

DR_CHAT_MODE = """
<rich-textarea><div contenteditable="true"
    data-placeholder="Ask Gemini"></div></rich-textarea>
<button>Deep research</button>
"""


def _dr(html: str) -> dict:
    return run_js(spec_from_html("<body>" + html + "</body>"),
                  research._GEMINI_DR_STATE_JS)["ret"]


def test_the_probe_reads_research_mode_off_a_page_that_is_in_it():
    """Full-dict equality on purpose: every field this probe returns is consumed
    somewhere, and a `assert x['pressed']` style check would leave the other
    seven free to be anything at all."""
    assert _dr(DR_RESEARCH_MODE) == {
        "pillVisible": True,
        "pressed": True,
        "placeholderResearch": True,
        "placeholderChat": False,
        "placeholder": "what do you want to research?",
        "pillText": "Deep research",
        "pillCls": "",
        "pillAria": "",
    }


def test_the_probe_reads_plain_chat_mode_off_a_page_that_is_in_it():
    assert _dr(DR_CHAT_MODE) == {
        "pillVisible": True,
        "pressed": False,
        "placeholderResearch": False,
        "placeholderChat": True,
        "placeholder": "ask gemini",
        "pillText": "Deep research",
        "pillCls": "",
        "pillAria": "",
    }


@pytest.mark.parametrize("attr", [
    'aria-pressed="true"',
    'aria-selected="true"',
    'data-active="true"',
    'class="mdc-evolution-chip--selected"',
    'class="pill selected"',
    'class="pill active"',
    'class="pill mdc-chip--filled"',
])
def test_every_way_gemini_marks_the_pill_pressed_is_read_as_pressed(attr):
    """Seven alternations in one boolean, none of them ever executed. Gemini has
    changed how it marks the pill more than once, which is why there are seven;
    a test that ran one of them would have said nothing about the other six."""
    st = _dr('<button ' + attr + '>Deep research</button>')
    assert (st["pillVisible"], st["pressed"]) == (True, True)


def test_an_unpressed_pill_is_not_read_as_pressed():
    """The negative half. Without it the parametrised test above is satisfied by
    `pressed = !!pill`, which is the mistake that shape of code invites."""
    st = _dr('<button class="pill mdc-evolution-chip">Deep research</button>')
    assert (st["pillVisible"], st["pressed"]) == (True, False)


def test_a_pill_that_is_not_rendered_is_not_the_pill():
    """⛔ `if (!p.offsetParent) continue;` — Gemini keeps a Deep-research chip in
    a collapsed toolbar, and reading that one would report research mode on a
    page showing none. The clause had never run."""
    st = _dr('<div hidden><button aria-pressed="true">Deep research</button></div>')
    assert (st["pillVisible"], st["pressed"], st["pillText"]) == (False, False, "")


def test_the_pill_is_matched_on_its_whole_name_not_a_word_inside_it():
    """`norm(p.textContent) === 'deep research'` is an equality, and the toolbar
    carries neighbours whose labels contain the phrase."""
    st = _dr('<button aria-pressed="true">Deep research settings</button>')
    assert st["pillVisible"] is False


def test_the_composer_fallback_picks_the_lowest_candidate_on_the_page():
    """⛔ THE FALLBACK NOBODY HAS RUN. With no `rich-textarea` the probe collects
    every placeholder-bearing editable, sorts by `top` DESCENDING and takes the
    first — the composer at the BOTTOM of the page. A sort written the other way
    round would read the placeholder of whatever sits highest, which on this
    screen is an unrelated search field."""
    page = ('<textarea placeholder="Search your chats" y="80"></textarea>'
            '<textarea placeholder="What do you want to research?" y="820"></textarea>')
    st = _dr(page)
    assert (st["placeholder"], st["placeholderResearch"]) == (
        "what do you want to research?", True)


def test_the_composer_fallback_ignores_an_unrendered_candidate():
    """`.filter(e => e.offsetParent)` — a composer left in the DOM by the
    previous route must not be the one whose placeholder decides the mode."""
    page = ('<div hidden><textarea placeholder="What do you want to research?"'
            ' y="900"></textarea></div>'
            '<textarea placeholder="Ask Gemini" y="820"></textarea>')
    st = _dr(page)
    assert (st["placeholder"], st["placeholderResearch"], st["placeholderChat"]) == (
        "ask gemini", False, True)


def test_the_probe_answers_safely_on_a_page_with_neither_composer_nor_pill():
    """A cold `/app` home, which is what a reload can land on. Every field must
    be its negative value; a probe that threw here would read as a stuck page."""
    assert _dr('<div>nothing here yet</div>') == {
        "pillVisible": False,
        "pressed": False,
        "placeholderResearch": False,
        "placeholderChat": False,
        "placeholder": "",
        "pillText": "",
        "pillCls": "",
        "pillAria": "",
    }
