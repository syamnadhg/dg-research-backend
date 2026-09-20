"""The ChatGPT tier control became a SLIDER, and the picker could not see it.

⛔⛔ THE DEFECT THIS FILE PINS, measured in the 2026-09-19 E2E. ChatGPT's effort
tiers stopped being menu rows. The live picker holds ONE row carrying
`role="slider"` with `aria-valuemin="0" aria-valuemax="4"`, driven by
ArrowLeft/ArrowRight, whose five stops are the old rows:

    stop 0  Instant       aria-valuenow="0"
    stop 1  Medium
    stop 2  High
    stop 3  Extra High
    stop 4  6 Pro         <- the target; the row's aria-label is "Power"

Two renames compound. The tier rows are gone, so `pick_effort_tier` finds nothing
to rank; and the row that holds the slider is labelled `Power`, so the 2026-08-17
submenu walk — which looks for a row naming `effort` — finds nothing to walk
into either. The picker therefore did everything right and still answered
`unsure` on every single run, handing a paid Pro account to the CUA rung, which
then did the work slowly and at cost. The support bundle records exactly that.

⭐ HOW THESE TESTS MEASURE. The page JS runs for real, under the node shim,
against a spec built from the captured markup — `run_js`, the same harness the
2026-08 tier tests use. The driver tests go further and run the REAL
`_chatgpt_drive_effort_slider` coroutine against a page object whose `evaluate`
is also the real JS on the real spec; only the browser transport is faked, and
ArrowRight rebuilds the fixture one stop along, which is what the browser does.

⛔ EVERY TEST HERE FAILS AGAINST THE 2026-09-19 CODE. The integration test is the
load-bearing one: it drives the whole `_chatgpt_pick_effort_tier` over a slider
layout and demands `selected`. The unfixed picker returns `unsure` on that exact
fixture — the E2E's verdict, reproduced.
"""
import asyncio

import pytest

import models
import research
from _domshim import NODE, el, js_constant, run_js

pytestmark = pytest.mark.skipif(NODE is None, reason="node required to run page JS")

TIERS = models.p1_words("chatgpt", "tier_words")
VERBS = models.p1_words("chatgpt", "upgrade_verbs")

# The stops as captured. `PILL` is what the trigger reads once the menu closes;
# `DESC` is what the accessible description calls the stop. They differ at the
# top — "6 Pro" against "Pro" — and both name the tier, which is the point.
PILL = ["Instant", "Medium", "High", "Extra High", "6 Pro"]
DESC = ["Instant", "Medium", "High", "Extra High", "Pro"]


def picker(value=0, *, is_open=True, pills=None, descs=None, row_label="Power",
           locked=(), describedby="lbl-top lbl-desc", extra_slider=None,
           menu_hidden=False):
    """The 2026-09-19 composer, at one slider stop.

    `pills`/`descs` override the stop names so a free account (whose top stop is
    `Extra High`) and an upsell (whose top stop is `Upgrade to Pro`) are one
    argument away. `locked` marks stops the plan does not offer.
    """
    pills = list(pills or PILL)
    descs = list(descs or DESC)
    top = len(pills) - 1
    ticks = [el("span", {"data-locked": "true" if i in locked else "false",
                         "data-selected": "true" if i <= value else "false",
                         "w": "4", "h": "4"})
             for i in range(len(pills))]
    slider_row = el("div", {"role": "menuitem", "tabindex": "0",
                            "aria-describedby": describedby,
                            "aria-keyshortcuts": "ArrowLeft ArrowRight",
                            "aria-label": row_label,
                            "data-orientation": "vertical",
                            "w": "240", "h": "40"}, "", [
        el("div", {}, "", ticks),
        # ⚠ aria-hidden and tabindex=-1, exactly as captured. This is why the
        # focus target has to be the ROW: the element holding the value cannot
        # take the keys.
        el("span", {"role": "slider", "aria-valuemin": "0",
                    "aria-valuemax": str(top), "aria-valuenow": str(value),
                    "aria-orientation": "horizontal", "aria-hidden": "true",
                    "tabindex": "-1", "w": "28", "h": "28"}),
    ])
    menu_kids = [
        # The live labels the row POINTS AT. They sit outside the row in the
        # capture, which is why `aria-describedby` — not descendant text — is
        # the only way to read the current stop's name.
        el("div", {}, "", [
            el("div", {"id": "lbl-top", "w": "60", "h": "20"}, pills[value]),
            el("div", {"id": "lbl-desc", "w": "200", "h": "20"},
               f"{descs[value]}, {value + 1} of {len(pills)}. "
               f"Use Left and Right arrow keys to adjust power."),
        ]),
        slider_row,
        # The model rows that DO mount. They are why the picker's row read
        # succeeds and its tier read still finds nothing.
        el("div", {"role": "menuitem", "w": "240", "h": "32"}, "Latest GPT-5.6 Sol"),
        el("div", {"role": "menuitem", "w": "240", "h": "32"},
           "GPT-5.5 Leaving on October 14"),
    ]
    if extra_slider is not None:
        menu_kids.insert(0, el("div", {"role": "menuitem", "tabindex": "0",
                                       "aria-label": extra_slider,
                                       "w": "240", "h": "40"}, "", [
            el("span", {"role": "slider", "aria-valuemin": "0",
                        "aria-valuemax": "3", "aria-valuenow": "1",
                        "aria-hidden": "true", "tabindex": "-1",
                        "w": "28", "h": "28"}),
        ]))
    kids = [el("button", {"class": "__composer-pill", "type": "button",
                          "aria-haspopup": "menu", "id": "trigger",
                          "aria-expanded": "true" if is_open else "false",
                          "aria-controls": "menu", "w": "150", "h": "36"},
               # While the picker is OPEN the pill shows its placeholder, not the
               # value — captured, and the reason the pill is read after Escape.
               "Thinking effort" if is_open else pills[value]),
           el("button", {"class": "__composer-pill", "type": "button",
                         "w": "130", "h": "36"}, "Deep research"),
           el("div", {"id": "prompt-textarea", "contenteditable": "true",
                      "w": "600", "h": "48"}, "")]
    if is_open:
        menu_attrs = {"role": "menu", "id": "menu", "data-radix-menu-content": "",
                      "aria-orientation": "vertical", "data-state": "open",
                      "w": "260", "h": "88"}
        if menu_hidden:
            menu_attrs["hidden"] = ""
        kids.append(el("div", menu_attrs, "", menu_kids))
    return el("body", {}, "", kids)


def august_row_menu():
    """The 2026-08-02 layout: tier RADIOS, no slider anywhere. The rung under
    test must be completely invisible to it."""
    rows = [el("div", {"role": "menuitemradio", "w": "240", "h": "32"}, t)
            for t in ("Instant 5.5", "Medium", "High", "Extra High", "Pro")]
    return el("body", {}, "", [
        el("button", {"class": "__composer-pill", "aria-haspopup": "menu",
                      "aria-expanded": "true", "w": "150", "h": "36"}, "Instant"),
        el("div", {"role": "menu", "data-state": "open", "w": "260", "h": "200"},
           "", rows),
    ])


def read_slider(spec):
    return run_js(spec, js_constant(research, "_CHATGPT_SLIDER_JS"),
                  {"attr": research._SR_CLICK_MARK, "value": "effort-slider",
                   "rowWords": models.p1_words("chatgpt", "slider_row_words")})["ret"]


# ── What the page JS reads ────────────────────────────────────────────────

def test_the_slider_is_found_by_its_role_and_reports_its_range():
    out = read_slider(picker(0))
    assert out["found"] is True
    assert (out["now"], out["min"], out["max"]) == (0, 0, 4)


def test_the_stop_name_comes_from_aria_describedby():
    """⭐ The two live labels are OUTSIDE the row, so descendant text cannot
    reach them. `aria-describedby` is the platform naming its own stop."""
    names = read_slider(picker(4))["names"]
    assert any("6 Pro" in n for n in names), names
    assert any("Pro, 5 of 5" in n for n in names), names


def test_no_aria_no_name_even_when_a_class_named_div_holds_the_text():
    """⛔⛔ THE RULE, PINNED. The captured class names (`d1BZWq_SliderTopRowMotion`)
    are build-hashed and will not survive a deploy. Strip the ARIA link and the
    read must go BLIND — if this ever starts answering, something has reached for
    a class and the picker will break silently on the next ChatGPT build."""
    spec = picker(4, describedby="")
    assert read_slider(spec)["names"] == []


def test_the_mark_lands_on_the_row_not_on_the_thumb():
    """The thumb holds the value; the ROW holds the keyboard contract. Marking
    the thumb would focus an `aria-hidden`, `tabindex=-1` element and every
    ArrowRight would go to whatever had focus instead."""
    out = run_js(picker(0),
                 "(P) => { const r = (" + js_constant(research, "_CHATGPT_SLIDER_JS")
                 + ")(P); const m = document.querySelector('[' + P.attr + ']');"
                 + "  return { r: r, tag: m && m.tagName,"
                 + "           role: m && m.getAttribute('role'),"
                 + "           label: m && m.getAttribute('aria-label'),"
                 + "           keys: m && m.getAttribute('aria-keyshortcuts') }; }",
                 {"attr": research._SR_CLICK_MARK, "value": "effort-slider",
                  "rowWords": models.p1_words("chatgpt", "slider_row_words")})["ret"]
    assert out["r"]["marked"] is True
    assert out["role"] == "menuitem"
    assert out["label"] == "Power"
    assert out["keys"] == "ArrowLeft ArrowRight"


def test_the_august_row_menu_reports_no_slider_at_all():
    """⛔ The rung must be INVISIBLE to every layout that still lists rows — a
    rollback, an A-B bucket, or the capture the 2026-08 tests are built on."""
    assert read_slider(august_row_menu()) == {"found": False, "reason": "no_slider"}


def test_a_slider_in_a_hidden_overlay_is_not_the_tier_control():
    assert read_slider(picker(0, menu_hidden=True))["found"] is False


def test_two_sliders_and_neither_named_by_policy_is_refused():
    """⛔ Driving the wrong knob to maximum is not a failed pick — it is a silent
    change to a setting the user never mentioned, on their own account."""
    out = read_slider(picker(0, row_label="Intensity", extra_slider="Length"))
    assert out == {"found": False, "reason": "ambiguous_slider", "count": 2}


def test_two_sliders_and_the_policy_names_one_of_them():
    out = read_slider(picker(0, extra_slider="Length"))
    assert out["found"] is True and out["named"] is True
    assert out["max"] == 4          # the tier slider's range, not the other's 3


def test_locked_stops_are_counted():
    out = read_slider(picker(2, locked=(3, 4)))
    assert (out["locked"], out["stops"]) == (2, 5)


# ── What the driver does with it ──────────────────────────────────────────

class _Keys:
    def __init__(self, page):
        self.page = page

    async def press(self, key):
        p = self.page
        p.presses.append(key)
        if key == "Escape":
            p.is_open = False
        elif key == "ArrowRight" and p.value < p.reachable:
            p.value += 1
        elif key == "ArrowLeft" and p.value > 0:
            p.value -= 1


class FakePage:
    """Real JS, real DOM, real coroutine — only the transport is faked.

    `reachable` is the highest stop the keys can actually get to, which is how a
    plan ceiling behaves: the thumb simply stops moving.
    """

    def __init__(self, value=0, *, reachable=99, is_open=True, **kw):
        self.value = value
        self.reachable = reachable
        self.is_open = is_open
        self.kw = kw
        self.presses, self.clicks, self.focused = [], [], []
        self.keyboard = _Keys(self)

    @property
    def spec(self):
        return picker(self.value, is_open=self.is_open, **self.kw)

    async def evaluate(self, js, arg=None):
        return run_js(self.spec, js, arg)["ret"]

    async def focus(self, sel, timeout=None):
        self.focused.append(sel)

    async def click(self, sel, timeout=None):
        self.clicks.append(sel)
        self.is_open = True

    async def hover(self, sel, timeout=None):
        self.clicks.append("hover:" + sel)


def drive(page):
    return asyncio.run(research._chatgpt_drive_effort_slider(
        page, tag="[test]", tiers=TIERS, verbs=VERBS, trace={}))


def test_it_drives_instant_all_the_way_to_pro():
    page = FakePage(0)
    assert drive(page) == "moved"
    assert page.value == 4
    assert page.presses == ["ArrowRight"] * 4


def test_it_stops_at_the_tier_and_does_not_run_on_to_the_end():
    """The target is a NAMED stop, not the maximum. Here `Pro` sits at stop 3 and
    there is a stop above it; a drive-to-`aria-valuemax` implementation would
    sail past the tier the policy asked for."""
    page = FakePage(0, pills=["Instant", "Medium", "Pro", "Ludicrous"],
                    descs=["Instant", "Medium", "Pro", "Ludicrous"])
    assert drive(page) == "moved"
    assert page.value == 2


def test_it_touches_the_slider_with_keys_only_never_a_click():
    """⛔⛔ A slider track sets its value from WHERE it is clicked. The marking
    and real-click machinery every other control here uses is, on this one, a
    way to land on an arbitrary tier."""
    page = FakePage(0)
    drive(page)
    assert page.clicks == []
    assert page.focused == [f'[{research._SR_CLICK_MARK}="effort-slider"]']


def test_a_stop_that_already_names_the_tier_is_not_driven():
    page = FakePage(4)
    assert drive(page) == "already"
    assert page.presses == []


def test_a_plan_whose_top_stop_is_not_pro_reports_no_target():
    """The honest no-subscription signal: every stop was visited and named, and
    none of them is the tier. ⛔ NOT a quiet settle for `Extra High`."""
    four = ["Instant", "Medium", "High", "Extra High"]
    page = FakePage(0, pills=four, descs=four)
    assert drive(page) == "no_target"
    assert page.value == 3


def test_an_upsell_at_the_top_stop_is_not_evidence_of_the_tier():
    """"Upgrade to Pro" names the tier without being it — the same two-part rule
    the row picker uses, because a free account's top stop is a sales prompt."""
    up = ["Instant", "Medium", "High", "Upgrade to Pro"]
    page = FakePage(0, pills=up, descs=up)
    assert drive(page) == "no_target"


def test_a_locked_stop_ahead_is_a_plan_limit():
    """The thumb stops moving at stop 2 and stops 3-4 are locked. That is a fact
    about the SUBSCRIPTION, and it is the one case where a stalled key may be
    reported as one."""
    page = FakePage(0, reachable=2, locked=(3, 4))
    assert drive(page) == "no_target"


def test_a_stalled_key_with_nothing_locked_is_not_a_plan_limit():
    """⛔⛔ THE ASYMMETRY THAT MATTERS. `no_target` sends a perfectly good Pro
    account down the no-subscription path. With no locked stop, a thumb that
    will not move is a fact about our keyboard, so the verdict is `unsure` and a
    lower rung answers."""
    page = FakePage(0, reachable=0)
    assert drive(page) == "unsure"


def test_a_key_that_does_not_move_the_thumb_is_pressed_once_not_four_times():
    """⛔ Never hammer a live page. One press that changes nothing IS the
    diagnosis; three more are keystrokes aimed at whatever has focus."""
    page = FakePage(0, reachable=0)
    drive(page)
    assert page.presses == ["ArrowRight"]


def test_an_unnameable_stop_is_never_driven():
    """With no readable stop name the only rule left is "go to the maximum", and
    the maximum is not always the tier."""
    page = FakePage(0, describedby="")
    assert drive(page) == "unsure"
    assert page.presses == []


def test_the_august_layout_falls_straight_through():
    """`""` — not a verdict. The row walk below it must run untouched."""
    class RowPage(FakePage):
        @property
        def spec(self):
            return august_row_menu()
    assert drive(RowPage(0)) == ""


@pytest.mark.parametrize("answer", [{}, None, {"found": False}, "nonsense",
                                    {"found": False, "reason": "some_future_word"}])
def test_an_answer_this_rung_does_not_recognise_falls_through(answer):
    """⛔⛔ THE REGRESSION I SHIPPED AND CAUGHT, PINNED SO IT CANNOT RETURN.

    The first version asked `if reason != "no_slider"` and called everything else
    an unusable slider — a verdict that STOPS the row walk. So any answer it did
    not recognise silently disabled the path below it, and two existing tests
    went from `no_target` to `unsure`: a real tier list with no Pro row stopped
    reporting the lapsed subscription, which is the single thing that verdict
    exists to say.

    Not knowing there is a slider is not a finding about a slider.
    """
    class Odd(FakePage):
        async def evaluate(self, js, arg=None):
            if "no_slider" in js:
                return answer
            return await super().evaluate(js, arg)
    page = Odd(0)
    assert drive(page) == ""
    assert page.presses == [] and page.focused == []


@pytest.mark.parametrize("answer", [{"found": True},
                                    {"found": True, "now": None, "max": 4},
                                    {"found": True, "now": "x", "max": "y"}])
def test_found_without_a_usable_range_never_raises(answer):
    """The docstring says this function never raises, and a page can answer
    anything. `int(None)` in the middle of the picker would take down the whole
    P1 tier step over a malformed read."""
    class Odd(FakePage):
        async def evaluate(self, js, arg=None):
            if "no_slider" in js:
                return answer
            return await super().evaluate(js, arg)
    assert drive(Odd(0)) == ""


@pytest.mark.parametrize("reason", ["ambiguous_slider", "no_value"])
def test_only_a_positively_unusable_slider_stops_the_row_walk(reason):
    """The other side of the same rule: these two ARE findings about a slider,
    and each means the rows below cannot be the tier list either."""
    class Odd(FakePage):
        async def evaluate(self, js, arg=None):
            if "no_slider" in js:
                return {"found": False, "reason": reason}
            return await super().evaluate(js, arg)
    assert drive(Odd(0)) == "unsure"


# ── The whole picker, over a slider layout ────────────────────────────────

def pick(page):
    return asyncio.run(research._chatgpt_pick_effort_tier(page, phase=1))


def test_the_picker_selects_pro_on_the_live_layout():
    """⛔⛔ THE E2E, REPRODUCED. This is the run that cost money: a Pro account,
    a picker that works, and `unsure` on every attempt because the tiers moved
    into a slider and the row that holds it was renamed `Power`.

    The unfixed picker answers `unsure` on this exact fixture — it finds the two
    model rows, ranks no tier among them, walks for a row naming `effort`, finds
    a row named `Power` instead, and correctly declines to guess. Nothing about
    it is broken; it simply cannot see the control.
    """
    page = FakePage(0, is_open=False)
    assert pick(page) == "selected"
    assert page.value == 4
    assert "Escape" in page.presses          # the picker was closed behind us
    assert page.is_open is False


def test_the_picker_reports_already_without_opening_anything():
    """ChatGPT persists the tier per account, so P2 is a read. The pill reads
    `6 Pro` before anything is touched and no menu may be opened — the #744
    invariant."""
    page = FakePage(4, is_open=False)
    assert pick(page) == "already"
    assert page.clicks == [] and page.presses == []


def test_the_picker_reports_no_target_for_an_account_without_the_tier():
    four = ["Instant", "Medium", "High", "Extra High"]
    page = FakePage(0, is_open=False, pills=four, descs=four)
    assert pick(page) == "no_target"


# ── Policy ────────────────────────────────────────────────────────────────

def test_the_row_name_lives_in_policy_so_the_next_rename_is_one_edit():
    """`Effort` → `Power` is the rename that broke the submenu walk. Both words
    are in the list; a third rename is a third entry, not a code change."""
    words = models.p1_words("chatgpt", "slider_row_words")
    assert "power" in words and "effort" in words


def test_emptying_the_row_words_disables_the_tie_break_not_the_picker():
    """⛔ The policy list is a DISAMBIGUATOR. The slider is found by role, so a
    single-slider picker must still work with the list empty — otherwise the
    hook is really the word, and the role comment above it is a lie."""
    out = run_js(picker(0), js_constant(research, "_CHATGPT_SLIDER_JS"),
                 {"attr": research._SR_CLICK_MARK, "value": "effort-slider",
                  "rowWords": []})["ret"]
    assert out["found"] is True and out["max"] == 4


# ── The pill's own text, as the page actually renders it ──────────────────

def two_span_pill(value=4, is_open=False):
    """The composer with the pill's tier split across TWO inline spans.

    ⛔⛔ THIS IS THE LIVE SHAPE AND MY FIXTURE DID NOT HAVE IT. The captured
    `smallStops` show the top tier rendered as `<span>6</span>` next to
    `<span data-max-effort="true">Pro</span>` — two elements, separated by CSS
    and by nothing else. My fixture put "6 Pro" in one text node, which is what
    the accessible DESCRIPTION says, not what the PILL is built from. So the
    tests passed while the real read returned "6Pro".
    """
    return el("body", {}, "", [
        el("button", {"class": "__composer-pill", "type": "button",
                      "aria-haspopup": "menu", "id": "trigger",
                      "aria-expanded": "true" if is_open else "false",
                      "w": "150", "h": "36"}, "", [
            el("span", {"class": "max-w-40 truncate"}, "", [
                el("span", {"class": "text-token-text-primary min-w-0 truncate"}, str(value + 2)),
                el("span", {"data-max-effort": "true", "class": "shrink-0"}, "Pro"),
            ]),
        ]),
        el("button", {"class": "__composer-pill", "type": "button",
                      "w": "130", "h": "36"}, "Deep research"),
    ])


def read_trigger(spec):
    return run_js(spec, js_constant(research, "_CHATGPT_MODEL_TRIGGER_JS"),
                  {"groups": research._CHATGPT_MODEL_TRIGGER_GROUPS,
                   "avoid": "deep research"})["ret"]


def test_the_pill_reads_with_the_space_the_user_sees():
    """⛔⛔ THE DEFECT THE 2026-09-19 RUN CAUGHT, TWICE.

    The run log, verbatim:
        ✗ p1 chatgpt.select_model: unverified — slider on tier; pill still '6Pro'
        ✗ p2 chatgpt.select_model: unverified — slider on tier; pill still '6Pro'

    The slider drove to the Pro stop correctly and then the confirm rejected
    its own success, because `textContent` glues two inline spans into "6Pro"
    and the tier test is word-boundary aware: the character to the left of
    "pro" is the alphanumeric "6", so it does not match. The whole rung — the
    one built to stop paying CUA for this — fell through on every run.
    """
    assert read_trigger(two_span_pill())["text"] == "6 Pro"


def test_and_that_text_satisfies_the_tier_check():
    """The consumer. The read is only worth anything if `on_target` flips —
    that boolean is what decides `already` in P2 and confirms the drive in P1."""
    assert models.has_term("6Pro", TIERS) is False     # the string we used to produce
    assert models.has_term("6 Pro", TIERS) is True     # the string we produce now


def test_a_single_text_node_label_is_unchanged():
    """⛔ The no-widening guard. Every other layout puts the label in one text
    node, and separating elements must not start inserting spaces INSIDE a
    word or padding a plain chip."""
    spec = el("body", {}, "", [
        el("button", {"class": "__composer-pill", "aria-haspopup": "menu",
                      "w": "150", "h": "36"}, "Instant"),
    ])
    assert read_trigger(spec)["text"] == "Instant"


def test_the_deep_research_pill_is_still_excluded():
    """The safety exclusion survives the new read. Clicking the DR pill does
    not open a menu — it ADDS A SECOND DEEP RESEARCH — so a read that started
    returning it would be destructive, not merely wrong."""
    got = read_trigger(two_span_pill())
    assert "Deep research" not in got["text"]


def test_a_nested_wrapper_does_not_become_a_trigger():
    """The 40-character cap still applies to the spaced read. Separating
    elements makes labels LONGER, so a wrapper that used to squeak under the
    cap could now pose as a chip — or a real chip could be pushed over it."""
    spec = el("body", {}, "", [
        el("div", {"class": "__composer-pill", "w": "600", "h": "40"}, "", [
            el("span", {}, "Thinking effort"), el("span", {}, "Deep research"),
            el("span", {}, "Attach"), el("span", {}, "Dictate"), el("span", {}, "Send"),
        ]),
    ])
    assert read_trigger(spec)["found"] is False
