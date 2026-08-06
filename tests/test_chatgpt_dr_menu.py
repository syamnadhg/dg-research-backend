"""#709 / Wave 4 — setup_chatgpt_dr finds the "Deep research" row that EXISTS.

History. #709 concluded the row was a `role="menuitemradio"` with exact text
"Deep research" and empty aria/testid, and pinned that with source-inspection
guards. The 2026-08-02 capture of the live "+" menu says otherwise: `ROOTS 0` —
the menu is not in a portal, not `[role=menu]`, not `[data-state=open]` — and
its rows are plain DIVs with **no role at all**, `class="group __menu-item
gap-1.5"`, carrying title+description CONCATENATED ("Deep research Get a
detailed report"). So the role-based selector matched nothing, the exact `===`
could not have matched a concatenated label either, and Step 2 had been falling
through to the CUA fallback on every run.

The old guards did not catch that, and one of them could not have: it asserted
`[role="menuitemradio"]` appeared somewhere in the function, and after the fix
that string still appears — in the DIAGNOSTIC DUMP. A presence assertion cannot
tell a live selector from a dump. These tests EXECUTE the real page JS against
the captured markup instead.
"""
import asyncio
import inspect

import pytest

import research
from _domshim import NODE, el, js_constant, run_js
from conftest import code_only_deep

pytestmark = pytest.mark.skipif(NODE is None, reason="node required to run page JS")


def _menu_item(text):
    """One live "+" menu row: a DIV, no role, no aria, no testid — class only."""
    return el("div", {"class": "group __menu-item gap-1.5"}, text)


def _suggestion_chip(text):
    """A SUGGESTION-STRIP chip. Different class, a Dismiss sibling, and a label
    that mimics a tool name with different words ("Search the web" vs the menu's
    "Web search"). Captured 2026-08-02."""
    return el("div", {"class": "group enabled:hover:bg-token-text-primary/3 relative fl"}, "",
              [el("button", {}, text),
               el("button", {"data-testid": "close-button", "aria-label": f"Dismiss {text}"}, "")])


def _live_plus_menu():
    """The captured "+" menu, with the suggestion strip rendered above it."""
    return el("body", {}, "", [
        _suggestion_chip("Create an image"),
        _suggestion_chip("Write or edit"),
        _suggestion_chip("Search the web"),
        _menu_item("Add photos & files Upload from computer"),
        _menu_item("Create image Visualize anything"),
        _menu_item("Web search Find real-time news and info"),
        _menu_item("Deep research Get a detailed report"),
        _menu_item("Figma Design and prototype"),
    ])


def _rows(spec):
    fn = js_constant(research, "_CHATGPT_MENU_ROWS_JS")
    return run_js(spec, fn, {"groups": research._CHATGPT_TOOL_ROW_GROUPS})["ret"]


def test_the_captured_rows_are_found_at_all():
    """The whole point: a class-only DIV row must be a candidate."""
    out = _rows(_live_plus_menu())
    assert out["via"] == "menu-item-class"
    assert "Deep research Get a detailed report" in out["rows"]


def test_the_suggestion_strip_is_not_in_the_candidate_set():
    """⛔ The recorded trap. An unscoped element search reaches the suggestion
    chips, clicks one, and the tool is silently never enabled — a failure that
    looks exactly like success from the caller."""
    out = _rows(_live_plus_menu())
    joined = " | ".join(out["rows"])
    for chip in ("Create an image", "Write or edit", "Search the web"):
        assert chip not in joined, f"the suggestion chip {chip!r} became a menu candidate"


def test_a_role_based_menu_still_works_when_the_class_is_gone():
    """Ordered hooks: if the class rotates away but roles come back, pass 2
    picks the menu up rather than the run falling to CUA."""
    spec = el("body", {}, "", [
        el("div", {"role": "menuitemradio"}, "Deep research Get a detailed report"),
        el("div", {"role": "menuitemradio"}, "Web search Find real-time news and info"),
    ])
    out = _rows(spec)
    assert out["via"] == "role"
    assert out["rows"][0].startswith("Deep research")


def test_hidden_rows_are_not_candidates():
    spec = el("body", {}, "", [
        el("div", {"class": "__menu-item", "hidden": ""}, "Deep research Get a detailed report"),
    ])
    out = _rows(spec)
    # 2026-08-05: the read now also reports what it threw away and which census it
    # applied, so assert the two fields the on-screen gate governs rather than the
    # whole dict — a diagnostic field is not a behaviour change.
    assert out["rows"] == []
    assert out["via"] == ""


def test_the_click_is_by_identity_not_position():
    """Ranking happens in python between two evaluates. If the menu re-renders in
    that gap the index points at a different row, and clicking by position alone
    is the mis-click the leaf/wrapper work was about."""
    fn = js_constant(research, "_CHATGPT_CLICK_ROW_JS")
    spec = _live_plus_menu()
    params = {"groups": research._CHATGPT_TOOL_ROW_GROUPS, "via": "menu-item-class",
              "index": 3, "expect": "Deep research Get a detailed report",
              "attr": research._SR_CLICK_MARK, "value": "tool-row"}
    # 2026-08-04: the JS MARKS the row and Playwright presses it — see
    # _sr_real_click. Nothing is pressed from inside page.evaluate any more, so
    # the round trip is what proves identity held, not a recorded click.
    round_trip = ("(P) => { const r = (" + fn + ")(P);"
                  " const el = document.querySelector("
                  "'[' + P.attr + '=\"' + P.value + '\"]');"
                  " return { clicked: r.clicked, reason: r.reason, text: r.text,"
                  " resolved: el ? (el.innerText || el.textContent || '').trim()"
                  " : null }; }")
    out = run_js(spec, round_trip, params)
    assert out["ret"]["clicked"] is True
    assert out["ret"]["resolved"] == "Deep research Get a detailed report"
    assert out["clicks"] == [], "the JS must not press the row itself"

    stale = dict(params, expect="Deep research")     # the label the menu no longer has
    out2 = run_js(spec, round_trip, stale)
    assert out2["ret"]["clicked"] is False
    assert out2["ret"]["reason"] == "label_changed"
    assert out2["ret"]["resolved"] is None, "a refused row must not be left marked"
    assert out2["clicks"] == []

    # …and a marker a PREVIOUS pass left behind must be gone too. Without that,
    # a refusal here hands Playwright the last pass's element to press — which
    # on this menu is a different tool.
    stale = dict(spec)
    stale["kids"] = [el("div", {research._SR_CLICK_MARK: "tool-row"}, "left over"),
                     *spec["kids"]]
    out3 = run_js(stale, round_trip, dict(params, expect="Deep research"))
    assert out3["ret"]["clicked"] is False
    assert out3["ret"]["resolved"] is None, (
        "a stale marker survived a refusal — the next press aims at it")


def test_a_gone_index_or_group_refuses_rather_than_clicking_something_else():
    fn = js_constant(research, "_CHATGPT_CLICK_ROW_JS")
    spec = _live_plus_menu()
    out = run_js(spec, fn, {"groups": research._CHATGPT_TOOL_ROW_GROUPS,
                            "via": "menu-item-class", "index": 99, "expect": "x"})
    # `clicked` is the field the caller branches on — a refusal that still
    # reports clicked:true is a click the caller believes happened and didn't.
    assert out["ret"] == {"clicked": False, "reason": "index_gone"}
    assert out["clicks"] == []
    out = run_js(spec, fn, {"groups": research._CHATGPT_TOOL_ROW_GROUPS,
                            "via": "nope", "index": 0, "expect": "x"})
    assert out["ret"] == {"clicked": False, "reason": "group_gone"}
    assert out["clicks"] == []


def test_the_candidate_set_excludes_the_generic_elements_the_chips_are_made_of():
    """`button, a, li` is what the suggestion strip is built from. Its absence is
    the SAFETY half of the fix, so it is asserted on the code, not the prose."""
    groups = research._CHATGPT_TOOL_ROW_GROUPS
    sels = " ".join(g["sel"] for g in groups)
    for generic in ("button", " a,", " li"):
        assert generic not in sels, (
            f"{generic!r} in the tool-row candidate set re-opens the suggestion-chip hole"
        )


class _MenuPage:
    """A page double that honours its arguments: the real Step-2 JS runs under
    node against the captured "+" menu, `query_selector` hands back a clickable
    plus button, and the composer read flips to active once the row is clicked —
    so a Step 2 that matches nothing cannot pass."""

    def __init__(self, spec):
        self.spec = spec
        self.dr_on = False
        self.clicks = []
        self.opened = []
        self.marked_text = None

    async def evaluate(self, script, arg=None):
        if script is research._CHATGPT_DR_ACTIVE_JS:
            return ({"active": True, "pillText": "deep research",
                     "placeholder": "get a detailed report"} if self.dr_on else
                    {"active": False, "pillText": "", "placeholder": "ask anything"})
        if script is research._SR_UNMARK_JS:
            return 1 if self.marked_text else 0
        out = run_js(self.spec, script, arg)
        self.clicks += out["clicks"]
        ret = out["ret"]
        # 2026-08-04: the row is MARKED here, not pressed. Nothing may change on
        # the page until the real click lands, so a Step 2 that marks and never
        # presses leaves Deep Research off — which is the live failure the
        # marking exists to remove, kept reproducible.
        if script is research._CHATGPT_CLICK_ROW_JS and (ret or {}).get("clicked"):
            self.marked_text = ret.get("text") or ""
        return ret

    async def click(self, selector, timeout=None):
        assert selector.startswith(f'[{research._SR_CLICK_MARK}="'), selector
        assert self.marked_text is not None, (
            "Playwright was asked to click with nothing marked")
        self.clicks.append(self.marked_text)
        # Only the Deep-Research row turns Deep Research on. Flipping on ANY
        # pressed row would make the double agree with a Step 2 that pressed the
        # wrong thing, which is precisely what these tests exist to catch.
        if self.marked_text.lower().startswith("deep research"):
            self.dr_on = True
        self.marked_text = None

    async def query_selector(self, sel):
        page = self

        class _Btn:
            async def click(self):
                page.opened.append(sel)
        return _Btn() if "composer-plus-btn" in sel else None


def test_step2_selects_the_concatenated_deep_research_row_end_to_end():
    """⭐ The row label is "Deep research Get a detailed report" — title and
    description CONCATENATED. #709's exact `===` could never have matched it, and
    a JS-only test cannot show that: the matching is python, between the two
    evaluates."""
    page = _MenuPage(_live_plus_menu())
    assert asyncio.run(research.setup_chatgpt_dr(page)) is True
    assert page.opened == ['button[data-testid="composer-plus-btn"]']
    assert page.clicks == ["Deep research Get a detailed report"]


def test_step2_clicks_no_suggestion_chip_when_the_menu_never_mounts():
    """Only the suggestion strip is on screen — Step 2 must find nothing rather
    than click a chip whose label mimics a tool name."""
    page = _MenuPage(el("body", {}, "", [
        _suggestion_chip("Search the web"), _suggestion_chip("Create an image")]))
    assert asyncio.run(research.setup_chatgpt_dr(page)) is False
    assert page.clicks == []


def test_step1_opens_via_the_captured_testid_first():
    """The observed control is `composer-plus-btn` with aria-label "Add files and
    more" — which the two aria patterns that used to lead cannot match ("Attach"
    is absent, and `*="More"` is case-SENSITIVE so it misses "more"). Worse,
    `*="Attach"` reaching a real attachment button opens a file chooser."""
    src = code_only_deep(research.setup_chatgpt_dr)
    order = [s for s in ('composer-plus-btn', 'Add files', 'Use a tool', 'Attach', 'more')
             if s in src]
    assert order[0] == "composer-plus-btn", "the observed testid must be tried first"
    assert 'aria-label*="more" i]' in src, "the aria patterns must be case-insensitive"


def test_step2_dumps_menu_items_on_failure():
    src = code_only_deep(research.setup_chatgpt_dr)
    assert "Step 2 menu-item dump" in src, (
        "on Step 2 total failure, setup_chatgpt_dr must dump the menu items "
        "so the exact Deep-research selector can be pinned from a real run "
        "instead of guessed (#709)."
    )
    assert "cls: c.slice(" in src and "el.className" in src, (
        "the dump must report the element's ACTUAL class — the live rows turned "
        "out to be class-only DIVs, which a role/aria/testid dump could never "
        "have revealed, and an empty `cls` field is the same blind spot with a "
        "column header on it."
    )


def test_the_target_word_comes_from_policy_not_a_literal(monkeypatch):
    """Behavioural, not a presence check: rename the tool in policy and the row
    Step 2 clicks must follow it."""
    import models
    monkeypatch.setitem(models.P2_MODEL_POLICY["chatgpt"], "tool", "web search")
    page = _MenuPage(_live_plus_menu())
    assert asyncio.run(research.setup_chatgpt_dr(page)) is False   # DR never turns on
    assert page.clicks == ["Web search Find real-time news and info"], (
        "Step 2 must match the policy tool label, not a frozen literal"
    )
    src = code_only_deep(inspect.getsource(research.setup_chatgpt_dr))
    assert "'deep research'" not in src, "no frozen tool literal in Step 2"
