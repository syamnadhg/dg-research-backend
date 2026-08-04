"""Wave 4 — ChatGPT's DOM tier (the `builtin` rung) and the setup ladder.

Four things are pinned here, and each of them is a capability that did not exist
before, so the tests run the REAL page JS against the markup captured from the
live composer on 2026-08-02 rather than asserting on source text:

  * the effort-tier picker — read first, ordered hooks, leaf not wrapper, and a
    verdict that is only ``selected`` when the TRIGGER actually moved;
  * the pre-act toggle guard — clicking an already-selected Deep Research ADDS
    a second one, so "already on" must never click;
  * the one policy value for "does this platform have a separate thinking
    control", and the two texts that render from it;
  * the ladder — stop at the first rung that verifies, and only a POSITIVE read
    may skip a rung.

The captured menu, for reference (§1 of the round-2 DOM captures):

    Instant 5.5   menuitemradio      <- the ONLY row carrying a version
    Medium        menuitemradio
    High          menuitemradio
    Extra High    menuitemradio
    Pro           menuitemradio      <- the target
    GPT-5.6 Sol   menuitem           (the "other models" entry)
"""
import asyncio
import inspect
import re

import pytest

import models
import prompts
import research
from _domshim import NODE, el, js_constant, run_js
from conftest import code_only, code_only_deep

pytestmark = pytest.mark.skipif(NODE is None, reason="node required to run page JS")

TIERS = models.p1_words("chatgpt", "tier_words")
VERBS = models.p1_words("chatgpt", "upgrade_verbs")


# ── The ranking rule ──────────────────────────────────────────────────────

def test_the_highest_number_is_the_lowest_tier():
    """⭐ THE reason this platform needs its own rule. `Instant 5.5` is the only
    row with a version and it is the CHEAPEST mode, so `pick_highest_model` —
    correct for Claude and Gemini — would rank the menu upside down."""
    rows = ["Instant 5.5", "Medium", "High", "Extra High", "Pro", "GPT-5.6 Sol"]
    assert models.pick_effort_tier(rows, TIERS, VERBS)["label"] == "Pro"


def test_a_missing_tier_returns_nothing_rather_than_the_next_best_row():
    """⛔ No fallback to a lower tier. Quietly settling for `Extra High` when the
    subscription no longer offers Pro would mask the exact downgrade the
    caller's escalation exists to surface."""
    assert models.pick_effort_tier(["Instant 5.5", "Medium", "High", "Extra High"],
                                   TIERS, VERBS) is None


def test_an_upsell_row_names_the_tier_without_being_evidence_of_it():
    for cta in ("Upgrade to Pro", "Get Pro", "Try Pro", "Subscribe to Pro"):
        assert models.pick_effort_tier(["Medium", cta], TIERS, VERBS) is None, cta


def test_the_tier_word_needs_a_word_boundary_on_both_sides():
    """`pro` as a bare substring is the trap the Gemini reject list was written
    for. A description mentioning productivity is not the Pro tier."""
    rows = ["High Great for productivity", "Medium Improve your drafts"]
    assert models.pick_effort_tier(rows, TIERS, VERBS) is None
    # ...but a concatenated title+description that really does name it counts.
    assert models.pick_effort_tier(["Pro Our smartest model"], TIERS, VERBS)["label"] \
        == "Pro Our smartest model"


def test_a_version_only_breaks_a_tie_between_rows_that_already_name_the_tier():
    got = models.pick_effort_tier(["Pro", "Pro 5.5", "Instant 9.9"], TIERS, VERBS)
    assert (got["label"], got["version"]) == ("Pro 5.5", 5.5)


def test_the_glued_wrapper_is_killed_by_the_boundary_rule_alone():
    """A container's textContent concatenates its children with NO separator, so
    "…Extra High" + "Pro" glues into "…Extra HighPro" and the tier word loses its
    left boundary. That form never becomes a candidate in the first place."""
    glued = "Instant 5.5MediumHighExtra HighPro"
    assert models.pick_effort_tier([glued], TIERS, VERBS) is None


def test_the_leaf_wins_over_a_wrapper_the_boundary_rule_cannot_kill():
    """⚠ The case the tie-break actually covers, and the reason the first version
    of this test was vacuous: a wrapper whose children carry their own spacing
    ("… Extra High Pro") keeps the word boundary, so it IS a candidate and only
    the SHORTEST-label rule keeps it from winning. Clicking an ancestor never
    reaches the row's handler while the caller reports success."""
    wrapper = "Instant 5.5 Medium High Extra High Pro"
    got = models.pick_effort_tier([wrapper, "Pro"], TIERS, VERBS)
    assert got["label"] == "Pro"
    # And with the rows in the other order, so the result isn't just "first wins".
    got = models.pick_effort_tier(["Pro", wrapper], TIERS, VERBS)
    assert got["label"] == "Pro"


def test_empty_tier_words_pick_nothing_rather_than_everything():
    """Enforced by `has_term` itself — no term can match, so no row is a
    candidate. Stated as a test rather than as an early return, because the early
    return that used to sit here could not change the answer and a mutation that
    deleted it survived."""
    assert models.pick_effort_tier(["Pro"], [], VERBS) is None
    assert models.pick_effort_tier(["Pro"], ["", "  "], VERBS) is None


def test_no_tier_words_configured_is_unsure_and_opens_nothing(monkeypatch):
    """⛔ The caller's guard IS load-bearing, and this is the difference: with no
    tier words the answer is `unsure` (the next rung runs), never `no_target`
    (which the caller reads as "this account has no Pro"). And it must be decided
    BEFORE any menu is opened."""
    monkeypatch.setitem(models.P1_MODEL_POLICY["chatgpt"], "tier_words", [])
    touched = []

    class _P:
        async def evaluate(self, script, arg=None):
            touched.append(script)
            return {}

    assert asyncio.run(research._chatgpt_select_effort_tier(_P())) == "unsure"
    assert touched == [], "the page must not be touched at all"


def test_has_term_is_the_same_definition_as_reject_matches():
    """A thin alias on purpose — a second implementation of the boundary rule is
    how the JS ranker and its python mirror drifted the first time."""
    for text, terms in (("3.1 pro", ["pro"]), ("productivity", ["pro"]),
                        ("flash-litefastest", ["lite*"]), ("elite", ["lite*"])):
        assert models.has_term(text, terms) == models.reject_matches(text, terms)


# ── The trigger read ──────────────────────────────────────────────────────

def _trigger(spec, avoid="deep research"):
    fn = js_constant(research, "_CHATGPT_MODEL_TRIGGER_JS")
    return run_js(spec, fn, {"groups": research._CHATGPT_MODEL_TRIGGER_GROUPS,
                             "avoid": avoid})["ret"]


def _composer(model_pill="Pro", dr_pill=None):
    kids = [el("button", {"class": "__composer-pill"}, model_pill)]
    if dr_pill:
        kids.insert(0, el("button", {"class": "__composer-pill"}, dr_pill))
    return el("body", {}, "", [el("form", {}, "", kids)])


def test_the_observed_class_hook_reads_the_pill():
    assert _trigger(_composer("Pro")) == {"found": True, "via": "pill", "text": "Pro"}


def test_a_semantic_hook_is_preferred_over_the_class_one():
    """Class is the weakest, most rotation-prone signal there is; it sits last."""
    spec = el("body", {}, "", [
        el("button", {"class": "__composer-pill"}, "Instant"),
        el("button", {"data-testid": "model-switcher"}, "Pro"),
    ])
    assert _trigger(spec) == {"found": True, "via": "testid", "text": "Pro"}


def test_the_deep_research_pill_is_never_mistaken_for_the_model_pill():
    """⛔ THE DESTRUCTIVE ONE. Both pills are `__composer-pill` buttons side by
    side. Clicking the Deep-Research one does not open a menu — it ADDS A SECOND
    DEEP RESEARCH. The policy tool label is the only discriminator the capture
    gives us, and it renders FIRST in the DOM, so document order alone picks the
    wrong one."""
    got = _trigger(_composer("Pro", dr_pill="Deep research"))
    assert got["text"] == "Pro", "the DR pill was read as the model trigger"


def test_the_tool_word_the_guard_relies_on_follows_policy(monkeypatch):
    monkeypatch.setitem(models.P2_MODEL_POLICY["chatgpt"], "tool", "deep dive")
    assert research._chatgpt_tier_policy()[2] == "deep dive"


def test_a_blank_policy_tool_word_still_arms_the_guard(monkeypatch):
    """⛔ Defaulted in ONE place, and it is the guard whose failure is
    destructive: with no word to avoid, the picker reads — and CLICKS — the
    Deep-Research pill, which adds a second Deep Research instead of opening a
    menu."""
    monkeypatch.setitem(models.P2_MODEL_POLICY["chatgpt"], "tool", "   ")
    assert research._chatgpt_tier_policy()[2] == "deep research"

    class _P:
        async def evaluate(self, script, arg=None):
            return run_js(_composer("Pro", dr_pill="Deep research"), script, arg)["ret"]

    got = asyncio.run(research._chatgpt_read_effort_tier(_P()))
    assert got["text"] == "Pro", "the DR pill was read as the model trigger"


def test_a_wrapper_that_swallows_the_whole_composer_cannot_pose_as_a_trigger():
    spec = el("body", {}, "", [
        el("button", {"class": "__composer-pill"}, "",
           [el("span", {}, "Instant 5.5 Medium High Extra High Pro and more besides")]),
    ])
    assert _trigger(spec)["found"] is False


def test_a_row_inside_an_open_menu_is_not_the_trigger():
    """A stale menu item while a different mode is live would otherwise
    false-positive — the same exclusion the Claude trigger read makes."""
    spec = el("body", {}, "", [
        el("div", {"role": "menu"}, "", [el("button", {"aria-label": "model"}, "Pro")]),
    ])
    assert _trigger(spec)["found"] is False


def test_an_upgrade_cta_on_the_trigger_is_not_already_on_target():
    """A trigger reading "Upgrade to Pro" names the tier without being evidence
    of it — and reading it as on-target would make the picker return `already`
    and skip every rung on exactly the account that has no Pro at all."""
    class _P:
        async def evaluate(self, script, arg=None):
            return run_js(_composer("Upgrade to Pro"), script, arg)["ret"]

    got = asyncio.run(research._chatgpt_read_effort_tier(_P()))
    assert got["found"] is True and got["on_target"] is False


def _mark(spec):
    fn = js_constant(research, "_CHATGPT_MARK_MODEL_TRIGGER_JS")
    return run_js(spec, fn,
                  {"groups": research._CHATGPT_MODEL_TRIGGER_GROUPS,
                   "avoid": "deep research",
                   "attr": research._SR_CLICK_MARK, "value": "model-trigger"})


def test_opening_the_menu_marks_the_same_element_the_read_returned():
    """⭐ 2026-08-04: this used to CLICK from inside page.evaluate and report
    `opened: true` because `el.click()` did not throw. On the one live attempt in
    the corpus that produced "opening the model menu" followed one second later
    by "did not mount any rows" — a synthetic click event never reaches a React
    overlay trigger listening on pointerdown. Nothing is pressed from JS now; the
    element is marked so a REAL Playwright click can be aimed at it, which is
    exactly what the tools menu two steps away has always done."""
    out = _mark(_composer("Instant", dr_pill="Deep research"))
    assert out["ret"]["marked"] is True
    assert out["ret"]["text"] == "Instant", "it must not mark the Deep-Research pill"
    assert out["clicks"] == [], "the JS must not press anything itself"


def test_the_selector_python_clicks_resolves_back_to_the_element_it_chose():
    """The mark is only worth anything if `[attr="value"]` finds the element the
    search picked. If it did not, Python's real click would miss and the safety
    exclusion above would be decorative — the press would land wherever
    Playwright's own selector happened to point."""
    fn = js_constant(research, "_CHATGPT_MARK_MODEL_TRIGGER_JS")
    round_trip = ("(P) => { const m = (" + fn + ")(P);"
                  " const el = document.querySelector("
                  "'[' + P.attr + '=\"' + P.value + '\"]');"
                  " return { marked: m.marked, resolved: el ?"
                  " (el.innerText || el.textContent || '').trim() : null }; }")
    out = run_js(_composer("Instant", dr_pill="Deep research"), round_trip,
                 {"groups": research._CHATGPT_MODEL_TRIGGER_GROUPS,
                  "avoid": "deep research",
                  "attr": research._SR_CLICK_MARK, "value": "model-trigger"})
    assert out["ret"] == {"marked": True, "resolved": "Instant"}


def test_marking_clears_a_marker_a_previous_pass_left_behind():
    """A stray marker is something the NEXT press would aim at, and the element
    it names may be gone, hidden, or the destructive pill."""
    fn = js_constant(research, "_CHATGPT_MARK_MODEL_TRIGGER_JS")
    count_all = ("(P) => { (" + fn + ")(P);"
                 " return document.querySelectorAll('[' + P.attr + ']').length; }")
    stale = el("body", {}, "", [
        el("div", {research._SR_CLICK_MARK: "model-trigger"}, "left over"),
        el("form", {}, "", [el("button", {"class": "__composer-pill"}, "Instant")]),
    ])
    out = run_js(stale, count_all,
                 {"groups": research._CHATGPT_MODEL_TRIGGER_GROUPS,
                  "avoid": "deep research",
                  "attr": research._SR_CLICK_MARK, "value": "model-trigger"})
    assert out["ret"] == 1, "more than one element carries the click marker"


def test_marking_reports_no_trigger_rather_than_marking_something_arbitrary():
    fn = js_constant(research, "_CHATGPT_MARK_MODEL_TRIGGER_JS")
    out = run_js(el("body", {}, "", []), fn,
                 {"groups": research._CHATGPT_MODEL_TRIGGER_GROUPS,
                  "avoid": "deep research",
                  "attr": research._SR_CLICK_MARK, "value": "model-trigger"})
    assert out["ret"] == {"marked": False, "via": "", "reason": "no_trigger"}
    assert out["clicks"] == []


# ── The picker, end to end, against a scripted page ───────────────────────

class _FakePage:
    """A page double that HONOURS its arguments: it runs the real JS under node
    against a DOM spec, and swaps the spec when the menu is opened or a row is
    clicked — so a picker that never clicks cannot pass, and one that claims
    success without re-reading the trigger cannot either.

    ⭐ The state only moves on `click()`, never on `evaluate()`. That mirrors the
    live page as of 2026-08-04 and is the whole point of the fix: marking an
    element from JS changes nothing, and a picker that marks without pressing
    must fail here exactly as it failed on the live run. Node builds a fresh DOM
    per call, so the marker's persistence is tracked here instead — what the JS
    itself decides (which element, and whether the exclusion held) is still
    executed for real.

    `play_click_fails` makes Playwright's click raise so the dispatched pointer
    chain has to carry the press, which is the rung that exists for an element
    Playwright refuses to act on.
    """

    def __init__(self, before, menu, after, play_click_fails=False,
                 play_fails_for=None):
        self.before, self.menu, self.after = before, menu, after
        self.state = "closed"
        self.clicks = []
        self.keys = []
        self.marked = None
        self.presses = []
        self._play_fails = play_click_fails
        # Which marks Playwright refuses. A trigger COVERED by an already-open
        # overlay is refused while the overlay's own rows stay perfectly
        # clickable — the case where "press failed" and "row pressed fine" are
        # both true at once, and the only one that can tell the trigger guard
        # from the row guard.
        self._fails_for = set(play_fails_for or ())

    def _spec(self):
        return {"closed": self.before, "open": self.menu, "done": self.after}[self.state]

    def _press(self):
        """What a landed press does to this page.

        It does NOT clear the marker — an attribute survives being clicked, and
        a double that cleared it here would make the unmark look done when it
        never ran. Verified by mutation: deleting the unmark survived until this
        was corrected.
        """
        if self.marked == "model-trigger":
            self.state = "open"
        elif self.marked == "model-row":
            self.state = "done"

    async def evaluate(self, script, arg=None):
        out = run_js(self._spec(), script, arg)
        self.clicks += out["clicks"]
        ret = out["ret"]
        if script is research._CHATGPT_MARK_MODEL_TRIGGER_JS and (ret or {}).get("marked"):
            self.marked = (arg or {}).get("value")
            self.clicks.append(ret.get("text"))
        if script is research._CHATGPT_CLICK_ROW_JS and (ret or {}).get("clicked"):
            self.marked = (arg or {}).get("value")
            self.clicks.append(ret.get("text"))
        if script is research._SR_UNMARK_JS:
            n = 1 if self.marked else 0
            self.marked = None
            return n
        if script is research._SR_POINTER_PRESS_JS:
            if not self.marked:
                return {"pressed": False, "reason": "marker_gone"}
            self.presses.append("pointer")
            self._press()
            return {"pressed": True}
        return ret

    async def click(self, selector, timeout=None):
        assert selector.startswith(f'[{research._SR_CLICK_MARK}="'), selector
        want = selector.split('"')[1]
        if self._play_fails or want in self._fails_for:
            raise RuntimeError("element is not visible")
        assert self.marked == want, (
            f"Playwright was asked to click {want!r} but the JS marked "
            f"{self.marked!r} — the press would land on the wrong element")
        self.presses.append("playwright")
        self._press()

    @property
    def keyboard(self):
        page = self

        class _K:
            async def press(self, key):
                page.keys.append(key)
        return _K()


MENU = el("body", {}, "", [
    el("div", {"role": "menuitemradio"}, "Instant 5.5"),
    el("div", {"role": "menuitemradio"}, "Medium"),
    el("div", {"role": "menuitemradio"}, "High"),
    el("div", {"role": "menuitemradio"}, "Extra High"),
    el("div", {"role": "menuitemradio"}, "Pro"),
    el("div", {"role": "menuitem"}, "GPT-5.6 Sol"),
])


def _pick(before, menu=MENU, after=None, phase=1):
    page = _FakePage(before, menu, after if after is not None else _composer("Pro"))
    verdict = asyncio.run(research._chatgpt_select_effort_tier(page, phase=phase))
    return verdict, page


def test_already_on_target_opens_nothing():
    """The #744 invariant: never open a popover you have nothing to do in. In P2
    this is the normal path — ChatGPT persists the tier per account."""
    verdict, page = _pick(_composer("Pro"))
    assert verdict == "already"
    assert page.clicks == [] and page.state == "closed"


def test_a_real_pick_clicks_the_row_and_reports_the_verified_trigger():
    verdict, page = _pick(_composer("Instant 5.5"))
    assert verdict == "selected"
    assert page.clicks == ["Instant 5.5", "Pro"]     # the trigger, then the row


def test_a_click_that_does_not_move_the_trigger_is_never_reported_as_success():
    """⛔ "The click didn't throw" is not evidence. A silent downgrade reported as
    a successful pick is the worst thing this path can produce."""
    verdict, page = _pick(_composer("Instant 5.5"), after=_composer("Instant 5.5"))
    assert verdict == "unverified"
    assert "Pro" in page.clicks, "it really did click the row"


def test_a_menu_with_no_tier_row_reports_no_target_and_clicks_nothing_in_it():
    menu = el("body", {}, "", [el("div", {"role": "menuitemradio"}, r)
                               for r in ("Instant 5.5", "Medium", "High", "Extra High")])
    verdict, page = _pick(_composer("Instant 5.5"), menu=menu)
    assert verdict == "no_target"
    assert page.clicks == ["Instant 5.5"], "only the trigger was clicked"


def test_an_unopenable_trigger_degrades_to_unsure_not_to_a_claim():
    verdict, page = _pick(el("body", {}, "", []))
    assert verdict == "unsure"
    assert page.clicks == []


def test_a_menu_that_never_mounts_leaves_no_popover_over_the_composer():
    verdict, page = _pick(_composer("Instant 5.5"), menu=el("body", {}, "", []))
    assert verdict == "unsure"
    assert page.keys == ["Escape"]


def test_every_non_already_exit_presses_escape():
    """Whatever happens, the picker must not leave the popover sitting over the
    composer — that is the screenshot behind #744."""
    for after in (_composer("Pro"), _composer("Instant 5.5")):
        _, page = _pick(_composer("Instant 5.5"), after=after)
        assert page.keys == ["Escape"], "the popover was left open"


def test_the_picker_survives_a_dead_page():
    class _Dead:
        async def evaluate(self, script, arg=None):
            raise RuntimeError("Execution context was destroyed")

    assert asyncio.run(research._chatgpt_select_effort_tier(_Dead())) == "unsure"


# ── The press: what the live run proved was missing ─────────────────────────

def test_the_trigger_is_pressed_for_real_not_from_inside_the_page():
    """⭐ THE live failure, 2026-08-03 23:14:54. The picker reported it had opened
    the model menu and one second later found no rows, because the "open" was a
    synthetic `el.click()` — a click event and nothing else, which a React
    overlay trigger listening on pointerdown never sees. Vision then had to
    select Pro by hand, which is what the owner watched happen."""
    verdict, page = _pick(_composer("Instant 5.5"))
    assert verdict == "selected"
    assert page.presses == ["playwright", "playwright"], (
        "the trigger and the row must both be pressed by the browser")


def test_a_marked_trigger_that_is_never_pressed_cannot_pass():
    """The double moves ONLY on a press, so a picker that marks and returns is
    reproducing the live failure — and must not be able to claim a tier."""
    class _MarksButNeverPresses(_FakePage):
        async def click(self, selector, timeout=None):
            raise RuntimeError("element is not visible")

        async def evaluate(self, script, arg=None):
            if script is research._SR_POINTER_PRESS_JS:
                return {"pressed": False, "reason": "marker_gone"}
            return await _FakePage.evaluate(self, script, arg)

    page = _MarksButNeverPresses(_composer("Instant 5.5"), MENU, _composer("Pro"))
    assert asyncio.run(research._chatgpt_select_effort_tier(page)) == "unsure"


def test_a_menu_we_did_not_open_is_never_acted_in():
    """⛔ The #744 principle, applied to the press. If nothing pressed the
    trigger, whatever menu is on screen is one we did not open — a leftover
    popover, another surface's overlay — and picking a row inside it is acting
    somewhere unknown while reporting the tier was selected.

    Contrived-looking and not contrived: an already-open overlay COVERS the
    trigger, so Playwright refuses the trigger for that exact reason while the
    overlay's own rows stay clickable. Both presses failing together is what
    hid this — the row guard caught it and the trigger guard looked redundant.
    """
    stale = el("body", {}, "", [
        el("form", {}, "", [el("button", {"class": "__composer-pill"}, "Instant 5.5")]),
        el("div", {"role": "menuitemradio"}, "Pro"),
    ])

    class _TriggerCovered(_FakePage):
        async def evaluate(self, script, arg=None):
            if script is research._SR_POINTER_PRESS_JS and self.marked == "model-trigger":
                return {"pressed": False, "reason": "marker_gone"}
            return await _FakePage.evaluate(self, script, arg)

    page = _TriggerCovered(stale, MENU, _composer("Pro"),
                           play_fails_for={"model-trigger"})
    assert asyncio.run(research._chatgpt_select_effort_tier(page)) == "unsure"
    assert page.presses == [], "a row was pressed in a menu we never opened"


def test_the_pointer_chain_carries_the_press_when_playwright_refuses():
    """The second rung. Playwright's click is trusted, scrolls and waits — but it
    also refuses an element it judges unactionable, and a dispatched chain still
    reaches a pointerdown handler. Ordered, not merged."""
    page = _FakePage(_composer("Instant 5.5"), MENU, _composer("Pro"),
                     play_click_fails=True)
    verdict = asyncio.run(research._chatgpt_select_effort_tier(page))
    assert verdict == "selected"
    assert page.presses == ["pointer", "pointer"]


def test_the_marker_is_always_taken_back_off():
    """A marker left behind is what the NEXT pass aims at, and by then it may
    name a hidden element — or the Deep-Research pill."""
    page = _FakePage(_composer("Instant 5.5"), MENU, _composer("Pro"),
                     play_click_fails=True)
    asyncio.run(research._chatgpt_select_effort_tier(page))
    assert page.marked is None


# ── The wait: an outcome, not an animation guess ────────────────────────────

class _SlowMenuPage(_FakePage):
    """The menu mounts only on the Nth row read. The old code took one look
    0.8 s after the press and called a still-animating menu a rotated hook."""

    def __init__(self, *a, mounts_on=3, **kw):
        super().__init__(*a, **kw)
        self._reads = 0
        self._mounts_on = mounts_on

    async def evaluate(self, script, arg=None):
        if script is research._CHATGPT_MENU_ROWS_JS and self.state == "open":
            self._reads += 1
            if self._reads < self._mounts_on:
                return {"via": "", "rows": []}
        return await _FakePage.evaluate(self, script, arg)


def test_a_menu_that_takes_a_moment_to_mount_is_still_used():
    page = _SlowMenuPage(_composer("Instant 5.5"), MENU, _composer("Pro"))
    assert asyncio.run(research._chatgpt_select_effort_tier(page)) == "selected"


def test_the_wait_is_bounded_rather_than_endless():
    page = _SlowMenuPage(_composer("Instant 5.5"), MENU, _composer("Pro"),
                         mounts_on=999)
    assert asyncio.run(research._chatgpt_select_effort_tier(page)) == "unsure"
    assert page._reads <= 12, "the poll must give up, not spin"


def test_a_menu_whose_rows_are_role_less_divs_is_still_read():
    """The tools menu's lesson, one overlay over: ChatGPT's own component library
    renders rows as plain DIVs whose only hook is the class. Roles first, class
    as the fallback — reached only when no role matched anything."""
    menu = el("body", {}, "", [
        el("div", {"class": "__menu-item"}, "Instant 5.5 Fast answers"),
        el("div", {"class": "__menu-item"}, "Pro Best for hard problems"),
    ])
    page = _FakePage(_composer("Instant 5.5"), menu, _composer("Pro"))
    assert asyncio.run(research._chatgpt_select_effort_tier(page)) == "selected"


def test_the_class_fallback_never_produces_a_no_pro_verdict():
    """⛔ The hazard the class hook introduces. `no_target` is read by the caller
    as "this account has no Pro" and it must not rest on the weakest hook: the
    class group is shared with the TOOLS menu, whose rows name no tier either.
    A class-group read that finds no tier cannot tell the two apart, so it says
    `unsure` and lets the next rung answer."""
    tools_menu = el("body", {}, "", [
        el("div", {"class": "__menu-item"}, "Deep research Get a detailed report"),
        el("div", {"class": "__menu-item"}, "Web search Find real-time news"),
    ])
    page = _FakePage(_composer("Instant 5.5"), tools_menu, _composer("Instant 5.5"))
    assert asyncio.run(research._chatgpt_select_effort_tier(page)) == "unsure"


def test_a_real_model_menu_with_no_pro_row_still_says_no_target():
    """…and the strong verdict survives where it IS earned: the menu answered on
    its own role hook and simply has no Pro row."""
    menu = el("body", {}, "", [el("div", {"role": "menuitemradio"}, r)
                               for r in ("Instant 5.5", "Medium", "High")])
    page = _FakePage(_composer("Instant 5.5"), menu, _composer("Instant 5.5"))
    assert asyncio.run(research._chatgpt_select_effort_tier(page)) == "no_target"


def test_a_menu_that_never_mounts_reports_what_was_on_screen(capsys):
    """"did not mount any rows" names no cause. The corpus has exactly one
    occurrence of that line and nothing to read beside it — the same failure as
    the silent panel bail-out, one surface over."""
    page = _FakePage(_composer("Instant 5.5"), el("body", {}, "", []),
                     _composer("Pro"))
    assert asyncio.run(research._chatgpt_select_effort_tier(page)) == "unsure"
    out = capsys.readouterr().out
    assert "mounted no rows" in out
    # ⚠ Assert the DATA, not the label. "hooks" and "overlays" are literals in
    # the format string and stay put when the diagnostic is gutted — verified by
    # mutation, which walked straight past a version asserting only those two
    # words while the line printed "hooks None, overlays None".
    assert "'name': 'radio'" in out, "the per-hook counts are missing"
    assert "'name': 'menu-item-class'" in out, "the class fallback is unreported"
    assert "overlays []" in out, "the overlay census is missing"


def test_the_verdict_vocabulary_is_closed():
    """The caller's ladder keys on these strings; a typo would silently turn a
    success into a fall-through (or worse, the reverse).

    Read off the PICKER, not the ledgered entry point that wraps it — the
    wrapper has one `return` and it is the picker's verdict passed through."""
    src = code_only(research._chatgpt_pick_effort_tier)
    returned = set(re.findall(r'return "([a-z_]+)"', src))
    assert returned == {"already", "selected", "no_target", "unverified", "unsure"}


def test_every_picker_verdict_reaches_the_ledger():
    """The wrapper must not swallow or rename a verdict on its way out —
    except the one rename it makes on purpose, `selected` → `verified`, so the
    summary counts one vocabulary across all five platforms."""
    src = code_only(research._chatgpt_select_effort_tier)
    assert "_dom_note(" in src, "the entry point no longer records anything"
    assert '"verified" if verdict == "selected" else verdict' in src, (
        "the ledger no longer passes the picker's verdict straight through")
    assert "return verdict" in src, "the wrapper alters the value it returns"


# ── The pre-act toggle guard ──────────────────────────────────────────────

def test_the_toggle_firewall_matches_the_selfheal_definition():
    import selfheal
    for a in (True, False):
        for b in (True, False):
            assert research._toggle_decision(a, b) == selfheal.decide_toggle(a, b)


def test_the_firewall_survives_the_selfheal_module_being_absent(monkeypatch):
    """A guard that disappears with an optional import is not a guard, and the
    failure it prevents here is destructive rather than merely unhelpful."""
    monkeypatch.setattr(research, "selfheal", None)
    assert research._toggle_decision(True, False) == "skip"
    assert research._toggle_decision(False, True) == "act"
    assert research._toggle_decision(False, False) == "ambiguous"


def test_setup_skips_the_click_when_deep_research_is_already_on(monkeypatch):
    """⭐ The whole reason Step 0 exists. Deep Research is sticky per account and
    `ensure_deep_mode_active` re-enters this function whenever its own read comes
    back false — so the old unconditional click could land on an already-selected
    tool, which ADDS A SECOND ONE."""
    calls = []

    class _P:
        async def evaluate(self, script, arg=None):
            calls.append(script)
            if script is research._CHATGPT_DR_ACTIVE_JS:
                return {"active": True, "pillText": "deep research",
                        "placeholder": "get a detailed report"}
            raise AssertionError("nothing else may run once DR reads active")

        async def query_selector(self, sel):
            raise AssertionError("the tools menu must not be opened")

    async def _no_tier(page):
        return "already"

    monkeypatch.setattr(research, "_chatgpt_p2_effort_tier", _no_tier)
    assert asyncio.run(research.setup_chatgpt_dr(_P(), allow_model_pick=True)) is True
    assert calls == [research._CHATGPT_DR_ACTIVE_JS]


def test_the_effort_menu_is_only_opened_from_the_initial_setup(monkeypatch):
    """The exact analogue of setup_claude_dr's `allow_probe`. This function is
    re-entered from the PRE-SEND check and the mid-run recovery paths, where the
    composer already holds the brief — opening the effort menu there is the #744
    screenshot, a popover over a loaded composer seconds before send."""
    ran = []

    async def _spy(page):
        ran.append(1)
        return "already"

    class _P:
        async def evaluate(self, script, arg=None):
            return {"active": True, "pillText": "deep research",
                    "placeholder": "get a detailed report"}

    monkeypatch.setattr(research, "_chatgpt_p2_effort_tier", _spy)
    assert asyncio.run(research.setup_chatgpt_dr(_P())) is True     # default: re-entry
    assert ran == [], "a pre-send re-run must not open the effort menu"
    assert asyncio.run(research.setup_chatgpt_dr(_P(), allow_model_pick=True)) is True
    assert ran == [1]


def test_only_the_initial_p2_setup_call_site_allows_the_model_pick():
    src = code_only(inspect.getsource(research))
    assert src.count("setup_chatgpt_dr(page, allow_model_pick=True)") == 1, (
        "exactly one call site — the LAYER 1 initial setup — may open the menu"
    )
    assert "await setup_chatgpt_dr(page)" in src, (
        "the pre-send / recovery re-runs must keep the default"
    )


def test_an_unreadable_composer_declines_to_click_rather_than_gambling():
    """⛔ The firewall's actual rule: a toggle may only ever move a
    CONFIRMED-opposite control. An empty placeholder is not evidence the tool is
    off, and a wrong guess here does not toggle — it ADDS A SECOND Deep
    Research. Declining costs one Vision/CUA fallback; guessing costs a
    duplicated tool that then rides into the run."""
    seen, opened = [], []

    class _P:
        async def evaluate(self, script, arg=None):
            seen.append(script)
            return {"active": False, "pillText": "", "placeholder": ""}

        async def query_selector(self, sel):
            # RECORDED, not raised. A raise here is swallowed by the function's
            # own except and the test would pass on the strength of the crash —
            # which is how a guard-removal mutant slips through a test that
            # looks like it covers it.
            opened.append(sel)
            return None

    assert asyncio.run(research.setup_chatgpt_dr(_P())) is False
    assert opened == [], "the tools menu must not be opened on an ambiguous read"
    assert seen == [research._CHATGPT_DR_ACTIVE_JS]


def test_a_readable_composer_with_no_pill_is_a_confirmed_off_and_proceeds():
    """The other half — the guard must not become a blanket refusal. A composer
    that reads back a normal placeholder IS positive evidence the tool is off."""
    opened = []

    class _P:
        async def evaluate(self, script, arg=None):
            if script is research._CHATGPT_DR_ACTIVE_JS:
                return {"active": False, "pillText": "", "placeholder": "ask anything"}
            return {"via": "", "rows": []}

        async def query_selector(self, sel):
            opened.append(sel)
            return None

    assert asyncio.run(research.setup_chatgpt_dr(_P())) is False   # no menu button
    assert opened, "Step 1 must have been reached"


def test_confirmed_off_requires_a_readable_composer():
    src = code_only_deep(research.setup_chatgpt_dr)
    assert 'and bool(_st0.get("placeholder"))' in src, (
        "confirmed-off requires a READABLE composer, not merely a false predicate"
    )


def test_the_acting_validator_is_warned_about_the_duplicate_too():
    """The DOM tier can decline to click on an ambiguous read; the CUA validator
    that runs when the ladder has NOT verified is the surface that then acts, and
    it was told to click "Deep research" with no mention that doing so on an
    already-selected tool adds a second one that cannot be clicked back off."""
    p = prompts.PROMPT_VALIDATE_CHATGPT_SETUP.lower()
    assert "adds a second deep research" in p
    assert "only click" in p


def test_the_clear_path_can_no_longer_click_the_pill_itself():
    """Strategy B accepted a control whose aria-label merely CONTAINS the tool
    name as a remove control — and the token's own control is labelled exactly
    that, so the clear path could add a Deep Research instead of removing one."""
    src = code_only_deep(research._chatgpt_clear_deep_research)
    assert "a.includes('deep research')" not in src, (
        "the DR label is not a remove verb — this clause clicked the pill"
    )
    for verb in ("remove", "close", "turn off", "deselect"):
        assert f"a.includes('{verb}')" in src, f"the real remove verb {verb!r} was lost"


# ── One policy value for the thinking control ─────────────────────────────

def test_chatgpt_has_no_separate_thinking_control():
    assert models.has_thinking_control("chatgpt", 1) is False
    assert models.has_thinking_control("chatgpt", 2) is False


def test_the_other_platforms_keep_their_real_answers():
    assert models.has_thinking_control("gemini", 2) is True       # "extended"
    assert models.has_thinking_control("claude", 2) is False      # dropped with Opus 5


def test_a_blank_string_is_not_a_control(monkeypatch):
    """The P2 value is a bool for one platform and the control's NAME for
    another, so truthiness has to be normalised rather than assumed."""
    monkeypatch.setattr(models, "P2_MODEL_POLICY",
                        {"x": {"thinking": "   "}, "y": {"thinking": "extended"}})
    assert models.has_thinking_control("x", 2) is False
    assert models.has_thinking_control("y", 2) is True


def test_an_unknown_platform_answers_false_not_true():
    """The safe direction: a wrong False costs one unset quality knob, a wrong
    True sends every surface hunting a control that isn't there."""
    assert models.has_thinking_control("nosuch", 1) is False
    assert models.has_thinking_control("nosuch", 2) is False


def test_the_mission_stops_telling_the_agent_to_find_a_toggle():
    p = prompts.PROMPT_SELECT_PRO.lower()
    assert "no separate thinking" in p
    assert "if a thinking / extended-thinking / reasoning toggle is visible, enable it" not in p


def test_the_user_message_beside_the_mission_says_the_same_thing():
    """⚠ THREE texts, not two. The one-line user message rides alongside the
    system prompt and is the one the agent reads LAST — it said "Select ChatGPT
    Pro model with Extended Thinking" while the system prompt above it had just
    been cleaned of exactly that instruction."""
    msg = research._p1_tier_mission()
    assert "extended thinking" not in msg.lower()
    assert "no separate thinking toggle" in msg.lower()
    # The caller greps this answer, so the marker has to survive the rewrite.
    assert "no pro available" in msg


def test_no_call_site_smuggles_the_phantom_toggle_back_into_the_vision_actor():
    """⚠ FOUR texts reach this hotspot, not three. `_shadow_observed_cua` APPENDS
    the call site's `context_hint` to the hotspot hint as "run detail", so a
    sentence written out there lands in front of the Vision actor however clean
    the hint above it is — and both ChatGPT select-Pro call sites said "with
    Extended Thinking"."""
    src = code_only_deep(inspect.getsource(research))
    # Scoped to what a Vision actor is actually SHOWN — the two kwargs whose text
    # is handed to it — rather than the whole module, where "Extended Thinking"
    # also appears in prose describing what Phase 1 is.
    lines = src.splitlines()
    shown = []
    for i, line in enumerate(lines):
        if "context_hint=" in line or "expected_outcome=" in line:
            shown += lines[i:i + 3]        # the kwarg plus its continuation lines
    joined = "\n".join(shown)
    assert "Extended Thinking" not in joined, (
        "a call site still shows the Vision actor a control the platform lacks:\n"
        + "\n".join(x for x in shown if "Extended Thinking" in x)
    )
    head = code_only_deep(inspect.getsource(research.run_phase1)).partition("# Attach PDFs")[0]
    assert head.count("_p1_tier_mission()") >= 3, (
        "the CUA user message and both Vision context hints must render from policy"
    )


def test_the_user_message_re_arms_with_the_policy(monkeypatch):
    monkeypatch.setitem(models.P1_MODEL_POLICY["chatgpt"], "thinking_control", True)
    assert "no separate thinking toggle" not in research._p1_tier_mission().lower()


def test_the_vision_hint_and_the_mission_agree_because_both_render_from_policy():
    hint = research._HOTSPOT_VISION_HINTS["1a-select-pro"]
    assert "no separate thinking toggle" in hint["context_hint"].lower()
    assert not any("thinking" in s.lower() for s in hint["success_signals"])


def test_flipping_the_policy_re_arms_both_texts(monkeypatch):
    """The point of a policy value: a ChatGPT that grows a separate toggle is one
    edit away, and BOTH surfaces move together."""
    monkeypatch.setitem(models.P1_MODEL_POLICY["chatgpt"], "thinking_control", True)
    assert "if a separate thinking" in models.p1_select_pro_directive().lower()
    assert "with its thinking" in research._p1_select_pro_hotspot()["context_hint"].lower()


def test_the_mission_carries_no_model_name_or_version():
    for word in ("gpt", "o1", "4.8", "5.5"):
        assert word not in models.p1_select_pro_directive().lower(), word


def test_the_mission_tier_word_follows_the_policy(monkeypatch):
    monkeypatch.setitem(models.P1_MODEL_POLICY["chatgpt"], "tier_words", ["max"])
    text = models.p1_select_pro_directive()
    assert '"Max"' in text and "Max mode selected" in text


# ── The ladder ────────────────────────────────────────────────────────────

def _ladder(states, rungs):
    """Drive _run_intent_ladder with a scripted sequence of outcome readings.

    Each rung is ``(tier, kind)`` where kind is ``"ran"`` (the caller ran it
    itself), ``"run"`` (the ladder runs it) or ``"none"`` (declared with no
    runner — what the P2 call site passes for the Vision/CUA rung when the DOM
    setup already succeeded).
    """
    seq = list(states)
    seen = []

    async def _verify():
        return seq.pop(0)

    def _rung(name):
        async def _r():
            seen.append(name)
        return _r

    spec = []
    for tier, kind in rungs:
        if kind == "ran":
            spec.append({"tier": tier, "ran": True})
        elif kind == "none":
            spec.append({"tier": tier, "run": None})
        else:
            spec.append({"tier": tier, "run": _rung(tier)})
    out = asyncio.run(research._run_intent_ladder("x.y", spec, verify=_verify, label="L"))
    return out, seen


RUNGS = [("builtin", "ran"), ("vision_cua", "run"), ("cua_validate", "run")]


def test_an_outcome_that_already_holds_runs_nothing_at_all():
    """With every rung still to run, nothing runs and nothing is credited."""
    out, seen = _ladder(["on"], [("vision_cua", "run"), ("cua_validate", "run")])
    assert (out["tier"], out["verified"], seen) == ("already", True, [])
    assert out["ran"] == [] and out["skipped"] == ["vision_cua", "cua_validate"]


def test_a_pre_run_rung_gets_the_credit_rather_than_being_reported_as_unrun():
    """⚠ The commonest path there is: the DOM setup ran at the call site, left
    the outcome satisfied, and the ladder's first read finds it on. Reporting
    "no rung ran" there would be false, and this log line is the first thing read
    when diagnosing which surface is carrying a platform."""
    out, seen = _ladder(["on"], RUNGS)
    assert (out["tier"], out["verified"], seen) == ("builtin", True, [])
    assert out["ran"] == ["builtin"]
    assert out["skipped"] == ["vision_cua", "cua_validate"]


def test_the_first_rung_that_verifies_stops_the_ladder():
    """⭐ The fix: after a rung wins, the surfaces below it do not run."""
    out, seen = _ladder(["off", "on"], [("vision_cua", "run"), ("cua_validate", "run")])
    assert (out["tier"], seen) == ("vision_cua", ["vision_cua"])
    assert out["skipped"] == ["cua_validate"]


def test_a_pre_run_rung_is_read_ONCE_not_twice():
    """One reading answers both "does the outcome already hold?" and "did the
    pre-run rung achieve it?" — they are the same question about the same page.
    Two reads cost an extra page probe and could log two different answers for
    one rung with nothing in between."""
    out, _ = _ladder(["on"], RUNGS)
    assert out["states"] == ["on"], "the pre-run rung must not be probed twice"
    out, _ = _ladder(["off", "off", "on"], RUNGS)
    assert out["states"] == ["off", "off", "on"]
    assert out["ran"] == ["builtin", "vision_cua", "cua_validate"]


def test_a_middle_rung_that_wins_stops_the_one_below_it():
    """After the DOM tier lost, the setup mission and the validation ran
    back-to-back on the same control, and a CUA "fix" toggled a working Deep
    Research back OFF (#709)."""
    out, seen = _ladder(["off", "on"], RUNGS)
    assert (out["tier"], seen) == ("vision_cua", ["vision_cua"])
    assert out["skipped"] == ["cua_validate"]


def test_an_unknown_reading_descends_instead_of_skipping():
    """⛔ ONLY a positive reading may skip a rung. A brittle probe must degrade to
    today's behaviour, never silently disarm a lower rung."""
    out, seen = _ladder(["unknown", "unknown", "unknown", "unknown"], RUNGS)
    assert out["verified"] is False
    assert seen == ["vision_cua", "cua_validate"]


def test_a_rung_that_throws_does_not_stop_the_ladder():
    """A rung failing is what lower rungs are for. Note the outcome is still
    re-read after it: a rung can act and THEN throw, and the page is the
    authority on what happened, not the exception."""
    async def _boom():
        raise RuntimeError("vision died")

    async def _verify():
        return seq.pop(0)

    seq = ["off", "off", "on"]
    ran = []

    async def _ok():
        ran.append("validate")

    out = asyncio.run(research._run_intent_ladder(
        "x.y",
        [{"tier": "builtin", "ran": True},
         {"tier": "vision_cua", "run": _boom},
         {"tier": "cua_validate", "run": _ok}],
        verify=_verify))
    assert out["tier"] == "cua_validate" and ran == ["validate"]
    assert out["ran"] == ["builtin", "vision_cua", "cua_validate"]


def test_a_failing_outcome_probe_is_unknown_not_a_stop():
    async def _verify():
        raise RuntimeError("detached frame")

    out = asyncio.run(research._run_intent_ladder(
        "x.y", [{"tier": "only", "ran": True}], verify=_verify))
    assert out["verified"] is False and out["states"] == ["unknown"]


def test_a_rung_with_no_runner_is_not_recorded_as_having_run():
    """`vision_cua` is passed with `run=None` when the DOM setup succeeded, so
    the ladder must neither run nor report a rung that did nothing."""
    out, seen = _ladder(["off", "on"],
                        [("builtin", "ran"), ("vision_cua", "none"), ("cua_validate", "run")])
    assert out["ran"] == ["builtin", "cua_validate"] and seen == ["cua_validate"]
    assert out["tier"] == "cua_validate"


# ── The outcome probe ─────────────────────────────────────────────────────

def _probe(platform, payload):
    class _P:
        async def evaluate(self, script, arg=None):
            if isinstance(payload, Exception):
                raise payload
            return payload
    return asyncio.run(research._dr_outcome_state(_P(), platform))


def test_chatgpt_reads_off_only_from_a_readable_composer():
    assert _probe("chatgpt", {"active": True}) == "on"
    assert _probe("chatgpt", {"active": False, "placeholder": "ask anything"}) == "off"
    assert _probe("chatgpt", {"active": False, "placeholder": ""}) == "unknown"


def test_gemini_keys_on_the_placeholder_not_the_pill():
    """#709: a merely-visible chip is NOT proof, in either direction."""
    assert _probe("gemini", {"placeholderResearch": True}) == "on"
    assert _probe("gemini", {"placeholderChat": True}) == "off"
    assert _probe("gemini", {"pillVisible": True, "pressed": True}) == "unknown"


def test_claude_needs_both_halves_of_the_intent_and_never_reads_off():
    """⛔ Two rules at once.

    BOTH halves: the rung this reading can skip is the CUA validator, which
    checks the model AND the Research tool. Answering `on` from the tool alone
    would silently drop the model half of a surface that was doing two jobs.

    And never `off`: claude.ai renders the Research pill without the attributes
    the detector keys on, so a TRUE state reads false — a False is the absence of
    evidence, not evidence of absence.
    """
    assert _probe("claude", {"hasExtended": True, "researchOn": True}) == "on"
    assert _probe("claude", {"hasExtended": True, "researchOn": False}) == "unknown"
    assert _probe("claude", {"hasExtended": False, "researchOn": True}) == "unknown"
    assert _probe("claude", {}) == "unknown"


def test_an_unknown_platform_and_a_dead_page_are_unknown():
    assert _probe("nosuch", {"active": True}) == "unknown"
    assert _probe("chatgpt", RuntimeError("boom")) == "unknown"


def test_the_claude_mode_detector_has_exactly_one_definition():
    """The pre-send mode check and the ladder probe must read the same constant —
    two copies of a detector is how the ChatGPT Step-3 verify drifted away from
    the shared composer detector.

    ⚠ The narrow marker is the DECISION clause. `aria-pressed` on its own also
    appears in the #744 diagnostic dump in the same function, and a dump is not
    a second detector — asserting on the bare attribute name would fail for a
    reason that has nothing to do with the invariant.
    """
    pre = code_only_deep(inspect.getsource(research.ensure_deep_mode_active))
    assert "_claude_state_js = _CLAUDE_MODE_STATE_JS" in pre, (
        "the pre-send check must read the shared constant"
    )
    assert "'data-state') === 'on'" not in pre, "a second copy of the detector came back"
    assert "'data-state') === 'on'" in research._CLAUDE_MODE_STATE_JS
    assert "hasExtended" in research._CLAUDE_MODE_STATE_JS
    # And the ladder's probe reads that same constant, not its own re-typing.
    assert "_CLAUDE_MODE_STATE_JS" in code_only(research._dr_outcome_state)


# ── Wiring: the P1 rung, and the corrected self-heal contract ─────────────

def test_the_p1_dom_rung_runs_before_the_cua_selector_and_gates_it():
    """The tier selection had NO DOM rung, and the whole block sat behind
    `if cua_client` — so a host with no CUA key ran the brief on whatever tier
    the account was left on, silently."""
    src = code_only(inspect.getsource(research.run_phase1))
    assert "_p1_tier = await _chatgpt_select_effort_tier(" in src
    assert '_p1_tier_ok = _p1_tier in ("already", "selected")' in src, (
        "only a mechanically VERIFIED verdict may skip the rungs below"
    )
    assert "if cua_client and not _p1_tier_ok:" in src
    # `no_target` must NOT short-circuit: the no-subscription escalation belongs
    # to the CUA path, and a DOM miss must never be able to fabricate one.
    assert '"no_target"' not in src.split("_p1_tier_ok =")[1].split("\n")[0]


def test_the_pro_claim_flag_is_bound_before_the_block_that_can_be_skipped():
    """It used to be defined inside `if cua_client:` and read afterwards as
    `if cua_client and _pro_select_claimed` — safe only while the two conditions
    were the same one. The DOM rung can now skip that block with cua_client
    still set, which would raise on an unbound name."""
    src = code_only(inspect.getsource(research.run_phase1))
    head, _, tail = src.partition("if cua_client and not _p1_tier_ok:")
    assert "_pro_select_claimed = False" in head
    assert "_pro_select_claimed = False" not in tail


def test_the_intent_no_longer_asserts_the_selector_is_absent():
    """The contract declared the outcome "a model selector is ABSENT" and marked
    itself detect-only. The capture shows a composer pill that opens a menu of
    menuitemradio rows, so the predicate was asserting something false and the
    shadow layer logged a hardcoded pass against it."""
    import selfheal
    for intents in (selfheal._INTENTS, selfheal.load_intents()):
        it = intents["chatgpt.select_model"]
        assert it["outcome_predicate"] == "chatgpt_trigger:tier_selected"
        assert "detect_only" not in it["signal_hints"]
        assert it["signal_hints"].get("value_contains") == TIERS[0]


def test_the_shadow_observation_carries_the_real_verdict():
    src = code_only_deep(research._chatgpt_p2_effort_tier)
    assert 'outcome_pass=verdict in ("already", "selected")' in src, (
        "the shadow log must record the picker's actual verdict, not a literal True"
    )
    assert "outcome_pass=True" not in src


def test_the_p2_tier_pick_runs_on_the_already_active_branch_too():
    """Step 0 returns early when Deep Research is already on. If the tier pick
    only hung off Step 3, the commonest P2 path would never reach it."""
    src = code_only_deep(research.setup_chatgpt_dr)
    assert src.count("await _chatgpt_p2_effort_tier(page)") == 2, (
        "both the already-active early return and the Step-3 success path must "
        "run the tier pick"
    )
    assert src.count("if allow_model_pick:") == 2, (
        "and both must be behind the initial-setup gate"
    )


def test_step3_verifies_through_the_shared_composer_detector():
    """It used to carry its own inline check that had drifted BOTH ways: it
    demanded the pill text be exactly "deep research", and its placeholder signal
    looked for "research" when the real Deep-Research placeholder is "Get a
    detailed report"."""
    src = code_only_deep(research.setup_chatgpt_dr)
    assert "active = await _dr_state()" in src
    assert "placeholder.includes('research')" not in src
