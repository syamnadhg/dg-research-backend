"""Gemini's plan-fail re-draft — the 2026-09-10 wave.

⛔⛔ WHAT WENT WRONG FOR FIFTEEN MONTHS, AND WHY THIS FILE IS SHAPED LIKE THIS.
The shared in-page retry guard has never clicked anything on Gemini's plan-fail
screen. Two words: the control is `aria-label="Redo"` and the word list says
`retry|regenerate|try again|rerun|restart`; the live text says "encountering an
error" and the alternation says "encountered". Neither miss was visible, because
the only test that read that pattern re-extracted the literal out of the source,
un-doubled its backslashes, compiled it in PYTHON, and fed it a sentence a human
had written to satisfy it. It never ran what the browser runs, and its fixture
came from the same imagination as the pattern.

So the rules here:

  * ⭐⭐ THE DOM FIXTURE IS THE OWNER'S CAPTURE, AND IT IS EXECUTED. The reader
    and the clicker run under node against the markup from the 09-10 console
    dump — not against markup shaped to suit them.
  * ⭐ EVERY DECISION IS A PURE FUNCTION, TESTED IN PYTHON, because that is the
    language it runs in. No regex crosses the JS bridge any more.
  * ⛔ The consumers are pinned too, not just the helpers: a helper that is
    lifted out and asserted about on its own is exactly how the last one passed.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research  # noqa: E402
from _domshim import NODE, run_js, spec_from_html  # noqa: E402


# ── The capture, 2026-09-10, conversation 748a05a1a2abc90c ────────────────────
# Recorded exactly as the owner dumped it: the failure bubble, the action row,
# the Redo control wrapped in its test-id'd icon button, and the five siblings.
# ⛔ The siblings are here ON PURPOSE. A finder that reaches for "the button in
# the action row" would pick Copy or Share with equal confidence, and a fixture
# holding only the control it means to find cannot see that.
CAPTURED_FAIL_TURN = """
<model-response>
  <div class="response-container">
    <structured-content-container class="model-response-text">
      <message-content>Sorry, something went wrong. Please try your request again.</message-content>
    </structured-content-container>
    <message-actions>
      <div class="actions-container-v2">
        <div class="buttons-container-v2">
          <gem-icon-button data-test-id="thumb-up-button">
            <button aria-label="Good response"></button></gem-icon-button>
          <gem-icon-button data-test-id="thumb-down-button">
            <button aria-label="Bad response"></button></gem-icon-button>
          <gem-icon-button data-test-id="share-and-export-menu-button">
            <button aria-label="Share &amp; export"></button></gem-icon-button>
          <gem-icon-button data-test-id="regenerate-button">
            <regenerate-button>
              <button aria-label="Redo"><mat-icon fonticon="refresh"></mat-icon></button>
            </regenerate-button></gem-icon-button>
          <gem-icon-button data-test-id="copy-button">
            <button aria-label="Copy"></button></gem-icon-button>
          <gem-icon-button data-test-id="more-menu-button">
            <button aria-label="More"></button></gem-icon-button>
        </div>
      </div>
    </message-actions>
  </div>
</model-response>
"""

# The overlay the Redo click opens onto. It hangs off the document root, NOT off
# the turn — which is why the reader looks for it separately, and why a reader
# scoped only to the turn would report "no menu" and re-click forever.
CAPTURED_REGEN_MENU = """
<div class="cdk-overlay-container">
  <div class="cdk-overlay-popover">
    <div class="cdk-overlay-pane">
      <gem-menu role="menu">
        <gem-menu-item data-test-id="regenerate-option" role="menuitem">
          <gem-menu-item-content class="active">
            <div class="label-container"><span class="label">Don't personalise</span></div>
          </gem-menu-item-content>
        </gem-menu-item>
      </gem-menu>
    </div>
  </div>
</div>
"""

# Two DISJOINT overlays, each with its own row — the shape that makes the
# picker's walk ORDER load-bearing. With one nested menu every pane contains
# every row, so any walk order lands on the same element and the coupling
# between the reader's indices and the picker's cannot be tested at all.
CAPTURED_TWO_OVERLAYS = """
<div class="cdk-overlay-container">
  <div class="cdk-overlay-popover">
    <gem-menu role="menu">
      <gem-menu-item role="menuitem"><span class="label">Share this chat</span></gem-menu-item>
    </gem-menu>
  </div>
  <div class="cdk-overlay-pane">
    <gem-menu role="menu">
      <gem-menu-item data-test-id="regenerate-option" role="menuitem">
        <span class="label">Don't personalise</span>
      </gem-menu-item>
    </gem-menu>
  </div>
</div>
"""

HEALTHY_PLAN_TURN = """
<model-response>
  <div class="response-container">
    <structured-content-container class="model-response-text">
      <message-content>Here is your research plan. Start research?</message-content>
    </structured-content-container>
  </div>
</model-response>
"""

pytestmark_node = pytest.mark.skipif(NODE is None, reason="node is required to run page JS")


def _read(html: str) -> dict:
    """Run the production reader over `html` and return its parsed reading."""
    import json
    out = run_js(spec_from_html("<body>" + html + "</body>"),
                 research._GEMINI_LATEST_TURN_JS)
    return json.loads(out["ret"])


# ── The reader, executed against the capture ─────────────────────────────────

@pytestmark_node
def test_the_reader_finds_the_control_the_owner_captured():
    r = _read(CAPTURED_FAIL_TURN)
    assert r["found"] is True
    by_shape = {c["shape"] for c in r["controls"]}
    assert "testid" in by_shape, (
        "the test-id'd icon button is the primary shape — if this misses, every "
        "fallback below it is carrying the feature")
    testid = [c for c in r["controls"] if c["shape"] == "testid"]
    assert len(testid) == 1
    assert testid[0]["name"] == "Redo", (
        "the control's accessible name is the one word the old word list did not "
        "have; reading it is how the fallback list can ever be right")


@pytestmark_node
def test_the_reader_does_not_offer_a_sibling_as_the_control():
    r = _read(CAPTURED_FAIL_TURN)
    control, why = research._gemini_regen_control(r["controls"])
    assert control is not None, why
    assert control["shape"] == "testid"
    # Copy / Share / More are all in the same action row and all aria-labelled.
    for forbidden in ("Copy", "Share & export", "More", "Good response",
                      "Bad response"):
        assert control["name"] != forbidden


@pytestmark_node
def test_the_click_lands_on_the_element_that_carries_the_name():
    """⛔ THE WRAPPER IS NOT THE BUTTON. The capture nests the real `<button>`
    two levels inside `gem-icon-button[data-test-id="regenerate-button"]`, so a
    finder that matches the test id and clicks THAT node clicks a custom element
    with no handler on it — a DOM no-op that returns a truthy label. This is the
    #905 disabled-skeleton-Start failure in a new costume: the click reports
    success and the page does not move."""
    r = _read(CAPTURED_FAIL_TURN)
    control, _ = research._gemini_regen_control(r["controls"])
    out = run_js(spec_from_html("<body>" + CAPTURED_FAIL_TURN + "</body>"),
                 research._GEMINI_REGEN_CLICK_JS,
                 {"shape": control["shape"], "index": control["index"]})
    assert out["ret"] == "Redo"
    assert out["clicks"] == ["Redo"], (
        "the click must land on the node carrying aria-label='Redo', not on the "
        f"custom-element wrapper around it (clicked: {out['clicks']})")


@pytestmark_node
def test_every_structural_shape_reaches_the_same_button():
    """The three structural shapes are three routes to one control. If they
    disagree about which node to click, the fallback order is not a fallback —
    it is three different behaviours wearing one name."""
    r = _read(CAPTURED_FAIL_TURN)
    seen = {}
    for shape in ("testid", "element", "icon"):
        cand = [c for c in r["controls"] if c["shape"] == shape]
        assert cand, f"the {shape} shape found nothing in the captured DOM"
        out = run_js(spec_from_html("<body>" + CAPTURED_FAIL_TURN + "</body>"),
                     research._GEMINI_REGEN_CLICK_JS,
                     {"shape": shape, "index": cand[0]["index"]})
        seen[shape] = out["clicks"]
    assert seen == {"testid": ["Redo"], "element": ["Redo"], "icon": ["Redo"]}, seen


@pytestmark_node
def test_the_clicker_refuses_a_control_that_went_disabled_between_the_two_reads():
    """⛔ RE-CHECKED AT THE CLICK, NOT ONLY AT THE READING. The reading and the
    click are two round trips; a node that goes `aria-disabled` in between would
    otherwise be clicked and hand back a truthy label — #905's
    disabled-skeleton Start, one more time, on a different button."""
    html = CAPTURED_FAIL_TURN.replace(
        '<button aria-label="Redo">', '<button aria-label="Redo" aria-disabled="true">')
    r = _read(CAPTURED_FAIL_TURN)          # read the HEALTHY page
    control, _ = research._gemini_regen_control(r["controls"])
    out = run_js(spec_from_html("<body>" + html + "</body>"),   # click the changed one
                 research._GEMINI_REGEN_CLICK_JS,
                 {"shape": control["shape"], "index": control["index"]})
    assert out["ret"] == ""
    assert out["clicks"] == [], "a disabled control was clicked"


@pytestmark_node
def test_the_clicker_refuses_a_control_that_went_invisible():
    html = CAPTURED_FAIL_TURN.replace(
        '<button aria-label="Redo">', '<button aria-label="Redo" w="0" h="0">')
    r = _read(CAPTURED_FAIL_TURN)
    control, _ = research._gemini_regen_control(r["controls"])
    out = run_js(spec_from_html("<body>" + html + "</body>"),
                 research._GEMINI_REGEN_CLICK_JS,
                 {"shape": control["shape"], "index": control["index"]})
    assert out["clicks"] == []


@pytestmark_node
def test_the_reader_reads_only_the_latest_turn():
    """⛔⛔ THE TRAP THIS FIX OPENS. The predicate this replaces tested
    `document.body.innerText`, so a failure that had ALREADY been re-drafted
    still authorised a click. That was survivable only while the guard could
    never fire; the first working Redo turns it into a loop that re-drafts a
    healthy plan forever. Scoping to the latest turn is what makes it stop."""
    r = _read(CAPTURED_FAIL_TURN + HEALTHY_PLAN_TURN)
    assert "something went wrong" not in r["text"].lower(), (
        "the failed turn above a healthy one must not be what the guard reads")
    assert "start research?" in r["text"].lower()
    step, why = research._gemini_regen_next_step(r)
    assert step == "settled", why


@pytestmark_node
def test_the_failed_turn_is_still_read_when_it_IS_the_latest():
    r = _read(HEALTHY_PLAN_TURN + CAPTURED_FAIL_TURN)
    assert "something went wrong" in r["text"].lower()
    step, why = research._gemini_regen_next_step(r)
    assert step == "click", why


@pytestmark_node
def test_the_reader_sees_the_overlay_menu_outside_the_turn():
    r = _read(CAPTURED_FAIL_TURN + CAPTURED_REGEN_MENU)
    assert len(r["rows"]) == 1, (
        f"one row was captured; the reader must not double-count an element "
        f"that matches two selectors in the list (rows: {r['rows']})")
    assert r["rows"][0]["testid"] == "regenerate-option"
    assert "don't personalise" in r["rows"][0]["name"].lower()
    step, why = research._gemini_regen_next_step(r, opened_menu=True)
    assert step == "pick_menu", why


@pytestmark_node
def test_an_overlay_we_did_not_open_is_left_alone():
    """⛔⛔ THE READER SEES EVERY OVERLAY IN THE DOCUMENT — Gemini's own model
    picker renders `menuitemradio` rows — so without knowing which one WE
    opened, any unrelated open menu diverted the whole call, and the dismiss
    path pressed Escape at a menu the user may have opened themselves."""
    r = _read(CAPTURED_FAIL_TURN + CAPTURED_REGEN_MENU)
    assert r["rows"], "the fixture must have an overlay for this to mean anything"
    step, why = research._gemini_regen_next_step(r)          # opened_menu default
    assert step == "click", why


@pytestmark_node
def test_the_menu_pick_finds_the_row_by_its_key_and_clicks_it():
    r = _read(CAPTURED_FAIL_TURN + CAPTURED_REGEN_MENU)
    row, why = research._gemini_menu_choice(r["rows"])
    assert row is not None, why
    out = run_js(
        spec_from_html("<body>" + CAPTURED_FAIL_TURN + CAPTURED_REGEN_MENU + "</body>"),
        research._GEMINI_MENU_PICK_JS,
        {"testid": row["testid"], "name": row["name"]})
    assert "don't personalise" in out["ret"].lower()
    assert out["clicks"], "the pick must actually click something"


@pytestmark_node
def test_the_pick_clicks_the_row_host_which_is_what_carries_the_role():
    """⛔ THE WRAPPER QUESTION AGAIN, ON THE CLICK THAT DOES THE WORK. The
    captured row is `gem-menu-item[data-test-id="regenerate-option"]
    [role="menuitem"]` with no descendant button — the ARIA role is on the HOST,
    so the host IS the control. `[role="menuitem"]` is deliberately not in the
    picker's inner query: `querySelector` never matches self, so it could only
    ever find a NESTED row, which is the wrong node by definition."""
    out = run_js(
        spec_from_html("<body>" + CAPTURED_FAIL_TURN + CAPTURED_REGEN_MENU + "</body>"),
        research._GEMINI_MENU_PICK_JS,
        {"testid": "regenerate-option", "name": ""})
    assert out["clicks"] == ["Don't personalise"], out["clicks"]


@pytestmark_node
def test_the_pick_never_reaches_past_the_row_into_a_nested_one():
    """⛔ `querySelector` NEVER MATCHES SELF, so a `[role="menuitem"]` descendant
    query can only ever find a NESTED row — a submenu item, which is by
    definition not the row the decider chose. The captured row carries the role
    on its HOST, so the host is the control and the inner query is for a real
    `<button>` or nothing."""
    # The nested row carries its own aria-label so the shim's click record can
    # tell the two apart: a click on the HOST reports the host's textContent,
    # a click on the child reports the child's label.
    nested = CAPTURED_REGEN_MENU.replace(
        '<span class="label">Don\'t personalise</span>',
        '<span class="label">Don\'t personalise</span>'
        '<gem-menu-item role="menuitem" aria-label="NESTED SUBMENU ROW">'
        '<span>Use a different model</span></gem-menu-item>')
    out = run_js(spec_from_html("<body>" + CAPTURED_FAIL_TURN + nested + "</body>"),
                 research._GEMINI_MENU_PICK_JS,
                 {"testid": "regenerate-option", "name": ""})
    assert out["clicks"], "nothing was clicked"
    assert out["clicks"] != ["NESTED SUBMENU ROW"], (
        "the pick reached past its own row into a nested one")
    assert "don't personalise" in out["clicks"][0].lower(), out["clicks"]


@pytestmark_node
def test_the_pick_refuses_a_row_whose_key_matches_but_reads_as_destructive():
    """The deny list is enforced where the click happens, not only where the
    choice is made — one definition, substituted into the page JS."""
    html = CAPTURED_FAIL_TURN + CAPTURED_REGEN_MENU.replace(
        "Don't personalise", "Delete this chat")
    out = run_js(spec_from_html("<body>" + html + "</body>"),
                 research._GEMINI_MENU_PICK_JS,
                 {"testid": "regenerate-option", "name": ""})
    assert out["ret"] == ""
    assert out["clicks"] == [], "a destructive row was clicked"


@pytestmark_node
def test_the_pick_refuses_a_row_whose_key_no_longer_matches():
    """The whole reason for keying rather than counting: if the row moved or was
    renamed between the reading and the click, nothing is clicked."""
    out = run_js(
        spec_from_html("<body>" + CAPTURED_FAIL_TURN + CAPTURED_REGEN_MENU + "</body>"),
        research._GEMINI_MENU_PICK_JS,
        {"testid": "some-other-option", "name": ""})
    assert out["ret"] == ""
    assert out["clicks"] == []


@pytestmark_node
def test_with_two_overlays_open_the_key_still_finds_the_right_row():
    """⭐⭐ THE TEST THAT RETIRED THE ORDINAL. Two DISJOINT overlays, each with its
    own row: under index addressing this is the shape where the reader's
    numbering and the picker's walk can disagree, and the click lands on Share
    instead of the re-draft. Keyed on the row's own test id, the walk order
    stops mattering at all — which is why the ordinal went rather than being
    tested harder."""
    html = CAPTURED_FAIL_TURN + CAPTURED_TWO_OVERLAYS
    r = _read(html)
    names = [row["name"] for row in r["rows"]]
    assert names == ["Share this chat", "Don't personalise"], names
    row, why = research._gemini_menu_choice(r["rows"])
    assert row is not None and row["testid"] == "regenerate-option", why
    out = run_js(spec_from_html("<body>" + html + "</body>"),
                 research._GEMINI_MENU_PICK_JS,
                 {"testid": row["testid"], "name": row["name"]})
    assert "don't personalise" in out["ret"].lower(), (
        f"the picker resolved the key to {out['ret']!r}")
    assert out["clicks"] == ["Don't personalise"], out["clicks"]


@pytestmark_node
def test_a_row_with_no_test_id_is_found_by_its_exact_label():
    """The fallback key, and it is EXACT rather than normalised: both ends read
    the label off the same node with the same expression, so there is nothing to
    normalise and no escaping to get wrong."""
    html = CAPTURED_FAIL_TURN + CAPTURED_TWO_OVERLAYS.replace(
        ' data-test-id="regenerate-option"', "")
    r = _read(html)
    row, why = research._gemini_menu_choice(r["rows"])
    assert row is not None and not row["testid"], why
    out = run_js(spec_from_html("<body>" + html + "</body>"),
                 research._GEMINI_MENU_PICK_JS,
                 {"testid": "", "name": row["name"]})
    assert out["clicks"] == ["Don't personalise"], out["clicks"]


@pytestmark_node
def test_an_empty_page_reads_as_no_turn_not_as_healthy():
    r = _read("<div>nothing here</div>")
    assert r["found"] is False
    step, why = research._gemini_regen_next_step(r)
    assert step == "no_turn", why


# ── The wording, in the language it runs in ──────────────────────────────────

def test_both_captured_wordings_are_recognised():
    """The second one is cause 2: the pattern said `encountered`, the UI says
    `encountering`. The old suite asserted a THIRD sentence — "I encountered an
    error doing what you asked" — which nobody has seen Gemini produce and which
    was written to satisfy the pattern it was certifying."""
    assert research._gemini_reads_as_failed(
        "Sorry, something went wrong. Please try your request again.")
    assert research._gemini_reads_as_failed(
        "I seem to be encountering an error. Can I try something else for you?")


def test_a_curly_apostrophe_does_not_defeat_the_pattern():
    """⭐ Every alternation in the old pattern wrote its apostrophe `'?`, which
    matches "cant" and "can't" and MISSES the curly `’` a real UI renders. One
    normaliser cannot be forgotten in the tenth alternation."""
    assert research._gemini_reads_as_failed("Sorry, I can’t help with that.")
    assert research._gemini_reads_as_failed("I couldn’t complete that request.")
    assert research._gemini_reads_as_failed("Sorry, I can't help with that.")


@pytest.mark.parametrize("text", [
    "An error occurred while generating your plan.",
    "I'm unable to start the research right now.",
    "Research stopped.",
    "Failed to start the research.",
])
def test_the_widened_wordings_are_recognised(text):
    assert research._gemini_reads_as_failed(text)


@pytest.mark.parametrize("text", [
    "Here is your research plan. Start research?",
    "Researching your topic — this may take a few minutes.",
    "I'll look into what went right with the deployment.",
    # ⛔⛔ THE TOPIC MAY BE ABOUT ERRORS. A research brief on error rates, outages
    # or post-mortems puts every one of these words on the page innocently, and
    # the turn being READ here is Gemini's own plan for that topic. A pattern
    # loose enough to match the subject matter would re-draft a perfectly good
    # plan forever — and this is the fixture that makes that testable rather
    # than a thing to be careful about.
    "Here is your plan: investigate error rates and failure modes in the 2026 "
    "fleet telemetry, including what went wrong in the March incident.",
    "Step 3: analyse why the migration was stopped and could not complete "
    "on the first attempt.",
    "",
])
def test_healthy_text_is_not_read_as_a_failure(text):
    assert not research._gemini_reads_as_failed(text)


# ── A plan is not an error, however it is worded ─────────────────────────────

REALISTIC_PLAN_ABOUT_FAILURES = (
    "Here is your research plan. Objective: establish why the Arecibo research "
    "stopped in 2020 and what the decommissioning cost. Step 1: gather the NSF "
    "reports and engineering assessments from 2017 onward. Step 2: identify "
    "every incident where the research stopped early, and the funds that "
    "failed to generate returns over the period. Step 3: review the published "
    "accounts of why the migration was unable to complete, and the cases where "
    "the response stopped mid-stream. Step 4: assemble a timeline and a cost "
    "model. Ready to start?")


def test_a_research_plan_about_failures_is_not_a_failed_plan():
    """⛔⛔ THE OVER-CORRECTION THAT ALMOST SHIPPED, AND CROSS-VERIFY CAUGHT IT BY
    FEEDING SENTENCES THE FIXTURES HAD BEEN WRITTEN AROUND. The turn this
    predicate reads is Gemini's own plan, which restates the user's brief — so a
    brief on an outage, a post-mortem, a failed mission or an underperforming
    fund puts these phrases on screen as CONTENT. Four separate alternations
    match inside this one plan. Unfixed, the loop re-drafts a perfectly good
    plan up to the cap, and `start_present` cannot save it because the auto-start
    layout renders Start disabled for ever.

    ⭐ The discriminator is LENGTH, not vocabulary: both captured failures are
    under seventy characters because that is all a UI error says, and a research
    plan is hundreds. No wording list can separate those two."""
    for phrase in ("research stopped", "failed to generate",
                   "unable to complete", "response stopped"):
        assert phrase in REALISTIC_PLAN_ABOUT_FAILURES
    assert len(REALISTIC_PLAN_ABOUT_FAILURES) > research._GEMINI_PLAN_FAIL_MAX_CHARS
    assert not research._gemini_reads_as_failed(REALISTIC_PLAN_ABOUT_FAILURES)


def test_the_captured_failures_are_comfortably_inside_the_size_bound():
    """The bound is only honest if the real messages are nowhere near it."""
    for text in ("Sorry, something went wrong. Please try your request again.",
                 "I seem to be encountering an error."):
        assert len(text) < research._GEMINI_PLAN_FAIL_MAX_CHARS / 4
        assert research._gemini_reads_as_failed(text)


def test_a_short_turn_that_says_it_failed_is_still_a_failure():
    """The bound must not become a way to miss a real error that arrives with a
    little more context around it."""
    assert research._gemini_reads_as_failed(
        "Sorry, something went wrong while drafting your research plan. "
        "Please try your request again in a moment.")


def test_the_bound_is_measured_after_normalising():
    """A bubble wraps, and a rendered turn carries far more whitespace than
    text: indentation, blank lines between blocks, the action row's own
    separators. Measured on the RAW string that pushes a real failure message
    past the bound and the re-draft never fires.

    ⛔ The padding here EXCEEDS the bound on its own — the first version of this
    test padded to about 230 characters against a 400 bound, so the mutant that
    measures the raw text survived the harness."""
    padded = ("\n   " * 150) + "Sorry,\n\n  something   went\twrong.\n" + ("\n  " * 60)
    assert len(padded) > research._GEMINI_PLAN_FAIL_MAX_CHARS
    assert len(research._gemini_norm(padded)) < research._GEMINI_PLAN_FAIL_MAX_CHARS
    assert research._gemini_reads_as_failed(padded)


def test_the_wording_survives_the_line_breaks_a_real_bubble_has():
    """⭐ THE NORMALISER EARNS ITS KEEP HERE. A rendered bubble wraps, so the
    phrase arrives split across lines and a pattern written against a single
    space would miss it — silently, and only on the narrow window."""
    assert research._gemini_reads_as_failed("Sorry, something\nwent wrong.")
    assert research._gemini_reads_as_failed("I am  encountering   an\terror.")


def test_no_regex_of_any_kind_crosses_into_the_page_js():
    r"""⛔⛔ THIS GUARD WAS HOLLOW AND CROSS-VERIFY PROVED IT. The first version
    asserted `"RegExp" not in js` and `"\\\\s" not in js` — but the
    fifteen-month defect was a regex LITERAL whose runtime value carries a
    SINGLE-backslash `\s`, so both assertions passed against the very string
    that caused the incident. A guard named after a root cause that cannot see
    that root cause is worse than none: it certifies the hole.

    ⛔ And it caught nothing when this wave's own first menu picker put
    `/[\u2018\u2019]/g` and `/\s+/g` back on that exact path to normalise a
    label. The label comparison is now EXACT against the raw string the reader
    reported, so there is nothing to normalise on the JS side at all.

    What is checked now is regex SYNTAX in any form, plus the escape classes
    that only appear inside one."""
    for name in ("_GEMINI_LATEST_TURN_JS", "_GEMINI_REGEN_CLICK_JS",
                 "_GEMINI_MENU_PICK_JS"):
        js = getattr(research, name)
        assert "RegExp" not in js, name
        # A regex literal always closes with a delimiter, and in JS it is
        # followed by flags or a method call.
        for token in ("/g", "/i", "/gi", "/ig", "/m", ".test(", ".match(",
                      ".exec("):
            assert token not in js, f"{name} carries regex syntax {token!r}"
        # These escapes are meaningless in a plain JS string and are the
        # signature of a pattern — in either the single- or double-backslash
        # spelling, which is the difference the old guard missed.
        for esc in ("\\s", "\\b", "\\d", "\\w", "\\S", "\\W"):
            assert esc not in js, f"{name} carries the escape {esc!r}"


def test_every_judgement_about_wording_happens_in_python():
    """The counterpart to the guard above: the deciding must be somewhere, and
    it has to be where the tests run it."""
    for pattern in (research._GEMINI_PLAN_FAIL_RE, research._GEMINI_REGEN_LABEL_RE,
                    research._GEMINI_NO_PERSONALISE_RE, research._GEMINI_REGEN_DENY_RE):
        assert hasattr(pattern, "search")


# ── The choices ──────────────────────────────────────────────────────────────

def _c(shape, index=0, name="Redo", visible=True, disabled=False):
    return {"shape": shape, "index": index, "name": name,
            "visible": visible, "disabled": disabled}


def test_the_structural_shapes_outrank_the_wording():
    control, why = research._gemini_regen_control(
        [_c("label", name="Try again"), _c("icon"), _c("element"), _c("testid")])
    assert control["shape"] == "testid", why


@pytest.mark.parametrize("better,worse", [
    ("testid", "element"), ("testid", "icon"), ("testid", "label"),
    ("element", "icon"), ("element", "label"), ("icon", "label"),
])
def test_the_shape_precedence_is_pinned_pairwise(better, worse):
    """⛔ THE FIRST VERSION OF THIS TEST WAS TAUTOLOGICAL and cross-verify said
    so: it put ONE control in and asserted the chosen shape was that shape, so
    the only possible outcomes were that control or nothing. It passed against a
    copy of the finder with the precedence REVERSED. Precedence is a claim about
    two candidates, so it takes two candidates."""
    control, why = research._gemini_regen_control(
        [_c(worse, name="Redo"), _c(better, name="Redo")])
    assert control["shape"] == better, why


def test_a_single_candidate_of_any_shape_is_still_usable():
    for shape in ("testid", "element", "icon", "label"):
        control, why = research._gemini_regen_control([_c(shape, name="Redo")])
        assert control is not None, why


def test_a_present_but_disabled_control_is_not_clicked():
    """#905's lesson, on a different button: clicking the disabled skeleton
    reported success and did nothing at all."""
    control, why = research._gemini_regen_control([_c("testid", disabled=True)])
    assert control is None
    assert "disabled" in why


def test_a_present_but_invisible_control_is_not_clicked():
    control, why = research._gemini_regen_control([_c("testid", visible=False)])
    assert control is None
    assert "visible" in why


def test_a_disabled_primary_shape_does_not_block_a_live_fallback():
    control, why = research._gemini_regen_control(
        [_c("testid", disabled=True), _c("icon")])
    assert control is not None and control["shape"] == "icon", why


def test_the_wording_fallback_now_knows_the_only_word_gemini_uses():
    control, why = research._gemini_regen_control([_c("label", name="Redo")])
    assert control is not None, why


@pytest.mark.parametrize("name", ["Copy", "Share & export", "More",
                                  "Good response", "Bad response", ""])
def test_the_wording_fallback_refuses_the_captured_siblings(name):
    control, why = research._gemini_regen_control([_c("label", name=name)])
    assert control is None, f"{name!r} was accepted as a re-draft control ({why})"


def test_refresh_is_not_a_wording_the_fallback_accepts():
    """⭐ The control's ICON is the refresh glyph and that is matched
    structurally. As an accessible NAME, "Refresh" far more likely means reload
    the page — and this list is the last resort, not the finder."""
    control, _ = research._gemini_regen_control([_c("label", name="Refresh")])
    assert control is None


@pytest.mark.parametrize("name", ["Good response", "Bad response", "Copy",
                                  "Share & export", "More options",
                                  "Thumbs up", "Sources"])
def test_a_structural_shape_that_resolves_to_a_sibling_action_is_refused(name):
    """⛔⛔ THE SHAPE THAT ALMOST SHIPPED. Every structural shape resolves through
    "the first descendant button", so a test id migrated one level up onto the
    buttons container — a routine change — makes the first descendant
    `thumb-up-button`. The finder would have returned it as "matched by testid",
    the clicker would have returned "Good response", and the log would have said
    it clicked its own control. The run posts feedback to Google and the plan
    never re-drafts.

    ⭐ This is a NEGATIVE name check, which is the opposite of finding by name:
    it never chooses a control because of its wording, it only refuses one that
    names itself as something else."""
    control, why = research._gemini_regen_control([_c("testid", name=name)])
    assert control is None, f"{name!r} was accepted as the re-draft control"
    assert "another action in the row" in why


def test_the_deny_list_does_not_refuse_the_control_itself():
    for name in ("Redo", "Regenerate", "Retry", ""):
        control, why = research._gemini_regen_control([_c("testid", name=name)])
        assert control is not None, f"{name!r} was refused ({why})"


def test_no_controls_at_all_is_reported_as_such():
    control, why = research._gemini_regen_control([])
    assert control is None
    assert "no controls" in why


# ── The menu ─────────────────────────────────────────────────────────────────

def _row(index, name, testid=""):
    return {"index": index, "name": name, "testid": testid}


def test_the_decider_returns_the_row_itself_not_its_ordinal():
    """⛔⛔ THE ORDINAL WAS A CORRECTNESS BUG, NOT AN INELEGANCE. The index space
    depends on which overlay panes were VISIBLE at the instant of the reading —
    so a popover finishing its opacity ramp, or a co-open menu closing between
    the read and the click, renumbers the rows and the click lands somewhere
    else. The decider was holding a stable key and threw it away; with a Delete
    row two places over, an off-by-two is not a missed re-draft."""
    row, why = research._gemini_menu_choice(
        [_row(0, "Something else"), _row(1, "Redraft", "regenerate-option")])
    assert isinstance(row, dict), why
    assert row["testid"] == "regenerate-option"
    assert row["name"] == "Redraft"


def test_the_un_personalised_row_wins_among_the_regenerate_rows():
    """The owner's instruction: pick "Don't personalise" when it shows."""
    row, why = research._gemini_menu_choice([
        _row(0, "Regenerate", "regenerate-option"),
        _row(1, "Don't personalise", "regenerate-option"),
    ])
    assert row["index"] == 1, why


@pytest.mark.parametrize("name", ["Don't personalise", "Don’t personalise",
                                  "Don't personalize", "DON'T PERSONALISE"])
def test_both_spellings_and_both_apostrophes_are_accepted(name):
    row, _ = research._gemini_menu_choice([_row(0, "Regenerate", "regenerate-option"),
                                           _row(1, name, "regenerate-option")])
    assert row["index"] == 1, f"{name!r} was not recognised"


def test_the_wording_can_find_the_row_when_the_test_id_is_gone():
    row, why = research._gemini_menu_choice(
        [_row(0, "Share"), _row(1, "Don't personalise")])
    assert row["index"] == 1, why


def test_a_test_id_row_outranks_a_wording_match_on_an_unmarked_row():
    """⛔ ORDER, NOT COINCIDENCE. If the wording were consulted first, a row
    that merely READS like the option would beat the row Gemini actually marks
    as its re-draft — and the wording is the fallback precisely because it is
    the thing that has already been wrong twice in this feature."""
    row, why = research._gemini_menu_choice([
        _row(0, "Don't personalise this answer"),
        _row(1, "Redraft", "regenerate-option"),
    ])
    assert row["index"] == 1, why


@pytest.mark.parametrize("name", ["Delete", "Delete this chat", "Remove",
                                  "Report a problem", "Discard draft",
                                  "Move to trash", "Block"])
def test_a_destructive_row_is_never_returned_whatever_key_matched_it(name):
    """⛔⛔ THE DENY LIST, AND THIS REPO ALREADY WROTE THE REASON DOWN. The note
    on the other menu picker's deny list says it plainly: "an off-by-two is not
    a failed download, it is a destroyed one." Gemini's overlays carry Delete
    and Report rows, this menu is opened programmatically, and the row we want
    is keyed on a test id a build can rename onto something else."""
    row, why = research._gemini_menu_choice([_row(0, name, "regenerate-option")])
    assert row is None, f"{name!r} was returned as the re-draft row"
    assert "destructive" in why


def test_a_destructive_row_does_not_hide_a_good_one_beside_it():
    row, why = research._gemini_menu_choice([
        _row(0, "Delete this chat", "regenerate-option"),
        _row(1, "Don't personalise", "regenerate-option"),
    ])
    assert row is not None and row["index"] == 1, why


def test_an_unreadable_menu_is_closed_rather_than_guessed_at():
    """⛔ This file already ruled on blind-clicking once, in the plan-stall
    diagnostic: "we do NOT blind-click — clicking an unidentified control risks
    a destructive misclick." An overlay we opened and cannot read is that."""
    row, why = research._gemini_menu_choice([_row(0, "Share"), _row(1, "Pin")])
    assert row is None
    assert "no row identifies itself" in why
    step, _ = research._gemini_regen_next_step(
        {"found": True, "text": "something went wrong",
         "controls": [_c("testid")], "rows": [_row(0, "Pin")]},
        opened_menu=True)
    assert step == "close_menu"


def test_no_rows_is_not_a_menu():
    row, why = research._gemini_menu_choice([])
    assert row is None
    assert "no menu rows" in why


# ── The verdict that gates the loop ──────────────────────────────────────────

def test_a_started_research_outranks_everything():
    assert research._gemini_plan_verdict(
        research_started=True, start_present=True, streaming=True,
        latest_text="something went wrong") == "researching"


def test_an_actionable_start_control_outranks_a_failure_above_it():
    """⭐ The goal is a started run, not a tidy page."""
    assert research._gemini_plan_verdict(
        research_started=False, start_present=True, streaming=False,
        latest_text="something went wrong") == "ready"


def test_a_failure_outranks_a_streaming_animation():
    assert research._gemini_plan_verdict(
        research_started=False, start_present=False, streaming=True,
        latest_text="Sorry, something went wrong.") == "failed"


def test_a_visibly_drafting_plan_is_left_alone():
    assert research._gemini_plan_verdict(
        research_started=False, start_present=False, streaming=True,
        latest_text="Working on your plan") == "drafting"


def test_the_plain_chat_case_is_named_silent_and_that_is_what_the_card_is_for():
    """⛔ THE ONE STATE WHERE THE ALERT IS THE RIGHT ANSWER. No plan, no error,
    nothing moving — the 2026-07-08 run where Gemini answered the brief as plain
    chat. There is nothing to click, so holding the card for a re-draft that can
    never happen would be the guard-that-cannot-fire shape again."""
    assert research._gemini_plan_verdict(
        research_started=False, start_present=False, streaming=False,
        latest_text="Sure, here are some thoughts on your topic.") == "silent"


# ── The step machine ─────────────────────────────────────────────────────────

def test_the_menu_we_opened_is_resolved_before_anything_is_clicked_again():
    """⛔ A SECOND CLICK WHILE THE OVERLAY IS UP LANDS ON ITS BACKDROP. The
    capture puts the re-draft behind an overlay row, so the control click alone
    changes nothing — and counting that as an attempt spends the cap on moves
    that re-drafted nothing. Three attempts, three menus, no plan."""
    step, why = research._gemini_regen_next_step(
        {"found": True, "text": "something went wrong",
         "controls": [_c("testid")],
         "rows": [_row(0, "Don't personalise", "regenerate-option")]},
        opened_menu=True)
    assert step == "pick_menu", why


def test_a_settled_turn_ends_the_machine_even_with_an_overlay_above_it():
    """⛔⛔ THE ORDERING BLOCKER CROSS-VERIFY FOUND, AND THE HARNESS HAD A MUTANT
    ENFORCING THE WRONG WAY ROUND. Rows were consulted BEFORE the turn's own
    text, so a regenerate overlay left open over a HEALTHY plan returned
    `pick_menu` — the caller then clicked "Don't personalise", destroyed a good
    plan, and returned `redrafted=True` with a success log line. A settled turn
    is the end of this machine, whatever is floating above it."""
    step, why = research._gemini_regen_next_step(
        {"found": True, "text": "Here is your research plan. Start research?",
         "controls": [_c("testid")],
         "rows": [_row(0, "Don't personalise", "regenerate-option")]},
        opened_menu=True)
    assert step == "settled", why


def test_a_settled_turn_stops_the_machine():
    step, _ = research._gemini_regen_next_step(
        {"found": True, "text": "Here is your research plan.",
         "controls": [_c("testid")], "rows": []})
    assert step == "settled"


def test_a_failure_with_no_reachable_control_is_reported_not_retried():
    step, why = research._gemini_regen_next_step(
        {"found": True, "text": "something went wrong", "controls": [], "rows": []})
    assert step == "no_control", why


def test_an_unreadable_page_is_never_reported_as_settled():
    """Fail-closed: a probe that could not read the page must not come out as
    "nothing is wrong here"."""
    for reading in ({}, None, {"found": False}):
        step, _ = research._gemini_regen_next_step(reading)
        assert step == "no_turn"


# ── The orchestrator, against a page that answers like the capture ───────────

class _FakePage:
    """A page that answers the reader with a scripted sequence of readings."""

    def __init__(self, readings):
        self._readings = list(readings)
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


FAILED = {"found": True, "text": "Sorry, something went wrong.",
          "controls": [_c("testid")], "rows": []}
MENU_UP = {"found": True, "text": "Sorry, something went wrong.",
           "controls": [_c("testid")],
           "rows": [_row(0, "Don't personalise", "regenerate-option")]}
UNREADABLE_MENU = {"found": True, "text": "Sorry, something went wrong.",
                   "controls": [_c("testid")], "rows": [_row(0, "Pin")]}
REDRAFTED = {"found": True, "text": "Here is your research plan. Start research?",
             "controls": [], "rows": []}


def _run(page):
    """`(redrafted, acted, in_flight, why)` — three different facts, and the
    caller needs all three, so all three are pinned."""
    return asyncio.run(research._gemini_redraft_plan(page, "T", settle_s=0))


def test_the_happy_path_clicks_the_control_then_picks_the_menu_row():
    page = _FakePage([FAILED, MENU_UP, REDRAFTED])
    ok, acted, in_flight, why = _run(page)
    assert (ok, acted, in_flight) == (True, True, False), why
    assert len(page.clicks) == 1
    assert page.clicks[0] == {"shape": "testid", "index": 0}
    assert page.picks == [{"testid": "regenerate-option",
                           "name": "Don't personalise"}], (
        "the row must be handed to the picker by its own stable key, never by "
        "the ordinal it happened to have in one reading")


def test_opening_a_menu_is_not_success_but_it_is_in_flight():
    """⛔ THE OLD CONTRACT WOULD HAVE STOPPED AT THE CLICK AND CALLED IT A RETRY.
    A click that opens a menu re-drafts nothing, and the cap must not be spent
    on it — but once the row IS picked and the turn has simply not come back
    yet, that is the one genuinely in-flight state, and the card waits for it."""
    page = _FakePage([FAILED, MENU_UP, MENU_UP])
    ok, acted, in_flight, why = _run(page)
    assert ok is False
    assert acted is True, (
        "the page WAS touched, so the attempt must be spent and the cooldown "
        "armed — otherwise a control that clicks and never re-drafts is clicked "
        "every ten seconds forever")
    assert in_flight is True
    assert "still reads as failed" in why


def test_the_control_is_never_clicked_twice_in_one_call():
    """A turn still showing the failure a moment after the click has not
    refused — it has not repainted. Re-clicking there turns a bounded cap into
    a burst."""
    page = _FakePage([FAILED, FAILED, FAILED])
    ok, acted, in_flight, _ = _run(page)
    assert (ok, acted, in_flight) == (False, True, True)
    assert len(page.clicks) == 1


def test_a_direct_redraft_with_no_menu_is_still_success():
    """Nothing here assumes the overlay is mandatory — only that it may appear.
    The capture proves the menu exists, not that Redo never re-drafts on its
    own, and a design that required the menu would break the day it stops
    appearing."""
    page = _FakePage([FAILED, REDRAFTED, REDRAFTED])
    ok, acted, in_flight, why = _run(page)
    assert (ok, acted, in_flight) == (True, True, False), why
    assert page.picks == []


def test_an_overlay_that_was_already_open_is_not_touched():
    """⛔⛔ THE FIRST VERSION PRESSED ESCAPE AT WHATEVER OVERLAY IT FOUND ON
    ENTRY, and the reader sees every overlay in the document — including
    Gemini's own model picker, whose rows are `menuitemradio`. Dismissing a menu
    the user opened is not this function's business. It now only ever resolves
    an overlay it opened itself, so an unrelated one simply does not divert the
    call."""
    page = _FakePage([UNREADABLE_MENU, MENU_UP, REDRAFTED])
    ok, acted, in_flight, why = _run(page)
    assert (ok, acted) == (True, True), why
    assert page.escapes == 0, "an overlay we did not open was dismissed"
    assert len(page.clicks) == 1


def test_a_settled_turn_on_entry_is_not_counted_as_a_redraft():
    page = _FakePage([REDRAFTED])
    ok, acted, in_flight, why = _run(page)
    assert (ok, acted, in_flight) == (False, False, False)
    assert page.clicks == []
    assert "no longer reads as failed" in why


def test_a_control_that_vanishes_before_the_click_spends_no_attempt():
    """⛔ THE READING AND THE CLICK ARE TWO ROUND TRIPS. Between them Gemini can
    repaint the turn away, and the clicker then finds nothing and returns empty.
    Nothing was touched, so nothing may be counted."""
    class _Vanishes(_FakePage):
        async def evaluate(self, js, arg=None):
            if js is research._GEMINI_REGEN_CLICK_JS:
                self.clicks.append(arg)
                return ""          # the finder matched nothing this time
            return await super().evaluate(js, arg)

    page = _Vanishes([FAILED, FAILED])
    ok, acted, in_flight, why = _run(page)
    assert (ok, acted, in_flight) == (False, False, False)
    assert "gone by the time the click ran" in why


def test_a_page_that_cannot_be_read_never_reports_a_redraft():
    class _Dead(_FakePage):
        async def evaluate(self, js, arg=None):
            raise RuntimeError("target closed")
    ok, acted, in_flight, why = _run(_Dead([FAILED]))
    assert (ok, acted, in_flight) == (False, False, False)
    assert "no model turn" in why


def test_an_unreadable_menu_ends_the_call_and_is_dismissed():
    """Touched, so the attempt is spent — but NOT in flight: the overlay is
    closed and nothing is generating, so holding the owner's alert for it would
    be waiting on something that cannot arrive."""
    page = _FakePage([FAILED, UNREADABLE_MENU, UNREADABLE_MENU])
    ok, acted, in_flight, why = _run(page)
    assert ok is False
    assert acted is True, "the control was clicked before the menu proved unreadable"
    assert in_flight is False
    assert page.picks == []
    assert page.escapes == 1
    assert "no row identifies itself" in why


def test_an_overlay_of_ours_that_mounts_late_is_still_dismissed():
    """⛔ CROSS-VERIFY'S FIND. The pane can mount LATER than the post-click
    re-read, in which case the step machine never saw it and neither branch
    dismissed it — and a CDK backdrop intercepts pointer events, so every later
    click on the page, ours or the CUA ladder's, lands on it. An overlay left
    over the third attempt is one the loop can never clear, because the loop has
    exited."""
    page = _FakePage([FAILED, FAILED, MENU_UP, REDRAFTED])
    ok, acted, in_flight, why = _run(page)
    assert page.escapes == 1, "the late overlay was left on screen"
    assert page.picks == []


def test_a_stop_between_the_reading_and_the_click_is_honoured():
    """⛔ The loop checks Stop before entering, and this helper then does two
    round trips and a settle. A Stop arriving inside that window must not
    result in a click — "no post-Stop DOM driving" is the standing rule."""
    class _Stopping:
        def __init__(self):
            self.stop = False

        def is_stop(self):
            return self.stop

    page = _FakePage([FAILED, MENU_UP, REDRAFTED])
    real = research._controls
    fake = _Stopping()
    research._controls = fake
    try:
        fake.stop = True
        ok, acted, in_flight, why = _run(page)
    finally:
        research._controls = real
    assert (ok, acted) == (False, False)
    assert page.clicks == []
    assert "stop requested" in why
