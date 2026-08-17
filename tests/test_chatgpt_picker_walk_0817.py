"""ChatGPT's composer picker grew a level (captured live 2026-08-17).

WHAT ACTUALLY CHANGED, because the report that reached us was "the effort
selector is a slider now" and that is not the thing that has to be driven. The
tier rows are still `menuitemradio` rows reading `Instant / Medium / High /
Extra High / Pro`. They moved one submenu down, behind a row labelled "Effort"
that is only shown once the menu is expanded. The picker opened the pill, read
`Advanced / Model … / Effort …`, found no row naming the tier, and stopped —
correctly, by its own rules. It simply had no way to walk in. CUA reached for
the slider for the same reason: it could not find the rows either.

⛔⛔ THE TRAP THIS FILE EXISTS FOR. In the COMPACT state the Effort row is
already in the DOM. It has a non-empty `getClientRects()`, it has an
`offsetParent`, and every visibility idiom in this codebase calls it visible —
but it is laid out BELOW the menu's own bottom edge and clipped out of the
panel. Marking it and handing those coordinates to a real Playwright press would
click whatever is behind the menu. The geometry in these fixtures is copied
from the live capture verbatim for exactly that reason: the compact menu ends at
y=464 and the Effort row starts at y=504.

These tests EXECUTE the production page JS through the node DOM shim. A
source-text assertion cannot tell a selector that matches from one that cannot.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from models import p1_words  # noqa: E402
from _domshim import el, run_js  # noqa: E402

MARK = research._SR_CLICK_MARK
TESTID = research._CHATGPT_PICKER_MENU_TESTID
ROW_GROUPS = research._CHATGPT_MODEL_ROW_GROUPS

PILL_ID = "radix-pill"
MENU_ID = "radix-menu"
EFFORT_ID = "radix-effort"
SUB_ID = "radix-sub"

# Geometry lifted from the capture. The compact menu is 96px tall and the
# advanced one 132px; the advanced ROWS sit at a fixed offset either way, which
# is what puts them out of the panel in the compact state.
MENU_BOX_COMPACT = {"x": "396", "y": "388", "w": "224", "h": "76"}   # bottom 464
MENU_BOX_EXPANDED = {"x": "396", "y": "388", "w": "224", "h": "112"}  # bottom 500
TOGGLE_COMPACT = {"x": "406", "y": "432", "w": "96", "h": "32"}       # bottom 464 — in
TOGGLE_EXPANDED = {"x": "406", "y": "388", "w": "96", "h": "32"}      # bottom 420 — in
MODEL_ROW_IN = {"x": "406", "y": "428", "w": "204", "h": "36"}        # bottom 464 — in
EFFORT_ROW_IN = {"x": "406", "y": "464", "w": "204", "h": "36"}       # bottom 500 — in
EFFORT_ROW_CLIPPED = {"x": "406", "y": "504", "w": "204", "h": "36"}  # bottom 540 — OUT

TIERS = ["Instant", "Medium", "High", "Extra High", "Pro"]


def _labelled_row(rid, label, value, box, *, expanded="false", controls=None):
    """A submenu-owning row: a leading label div, then the current value.

    The row's whole text is "EffortInstant" — label plus the value it holds —
    which is why production matches the LEADING label and never the whole text.
    """
    attrs = {"role": "menuitem", "id": rid, "aria-haspopup": "menu",
             "aria-expanded": expanded, **box}
    if controls:
        attrs["aria-controls"] = controls
    return el("div", attrs, kids=[
        el("div", {}, kids=[el("div", {}, label)]),
        el("span", {}, value),
    ])


def _picker(*, view, effort_expanded=False, with_submenu=False,
            effort_value="Instant", testid=True, extra_pills=()):
    """The composer with the picker open, in either view state."""
    compact = view == "simple"
    menu_box = MENU_BOX_COMPACT if compact else MENU_BOX_EXPANDED
    toggle_box = TOGGLE_COMPACT if compact else TOGGLE_EXPANDED
    effort_box = EFFORT_ROW_CLIPPED if compact else EFFORT_ROW_IN

    rows = [
        # The compact view's slider row. Present in both states; production must
        # not mistake it for a tier row (it owns no submenu and names no tier).
        el("div", {"role": "menuitem", "aria-label": "Power",
                   "aria-keyshortcuts": "ArrowLeft ArrowRight",
                   "x": "396", "y": "396", "w": "224", "h": "32"}),
        el("div", {"role": "menuitem", "aria-expanded": "true" if not compact else "false",
                   "aria-label": ("Show compact options" if not compact
                                  else "Show advanced options"), **toggle_box},
           kids=[el("span", {}, kids=[el("span", {}, "Advanced")])]),
        _labelled_row("radix-model", "Model", "GPT-5.6 Sol", MODEL_ROW_IN),
        _labelled_row(EFFORT_ID, "Effort", effort_value, effort_box,
                      expanded="true" if effort_expanded else "false",
                      controls=SUB_ID if effort_expanded else None),
    ]

    group_attrs = {"role": "group", **menu_box}
    if testid:
        group_attrs["data-testid"] = TESTID
    menu = el("div", {"role": "menu", "id": MENU_ID, "aria-labelledby": PILL_ID,
                      **menu_box},
              kids=[el("div", group_attrs, kids=rows)])

    kids = [
        el("button", {"id": PILL_ID, "aria-haspopup": "menu",
                      "aria-expanded": "true", "aria-controls": MENU_ID,
                      "class": "__composer-pill"}, effort_value),
    ]
    kids.extend(extra_pills)
    kids.append(menu)
    if with_submenu:
        kids.append(el("div", {"role": "menu", "id": SUB_ID,
                               "aria-labelledby": EFFORT_ID,
                               "x": "257", "y": "458", "w": "147", "h": "200"},
                       kids=[el("div", {"role": "group"}, kids=[
                           el("div", {"role": "menuitemradio",
                                      "aria-checked": "true" if t == effort_value else "false",
                                      "x": "267", "y": str(468 + 36 * i),
                                      "w": "127", "h": "36"},
                              kids=[el("span", {}, t)])
                           for i, t in enumerate(TIERS)])]))
    return el("body", {"x": "0", "y": "0", "w": "728", "h": "748"}, kids=kids)


def _walk(spec):
    return run_js(spec, research._CHATGPT_PICKER_NAV_JS, {
        "menuTestid": TESTID,
        "effortWords": p1_words("chatgpt", "effort_row_words"),
        "advancedWords": p1_words("chatgpt", "advanced_words"),
        "avoid": "deep research",
        "attr": MARK, "value": "picker-step",
    })["ret"]


# ── the walk ──────────────────────────────────────────────────────────────────

class TestPickerWalk:
    def test_expanded_menu_marks_the_effort_row(self):
        out = _walk(_picker(view="advanced"))
        assert out["state"] == "effort", out
        # Identity, not just "a row was marked": the Model row sits directly
        # above it and owns a submenu too.
        assert "Effort" in out["label"]

    def test_compact_menu_expands_FIRST(self):
        # ⭐⭐ The whole point. The Effort row is present and "visible" by every
        # idiom this codebase uses, and it is NOT reachable.
        out = _walk(_picker(view="simple"))
        assert out["state"] == "advanced", out
        assert "Advanced" in out["label"]

    def test_a_clipped_row_is_never_the_thing_we_mark(self):
        # Stated as its own claim because the consequence is a real press at
        # coordinates outside the menu — the failure mode is not "we missed",
        # it is "we clicked something else".
        out = _walk(_picker(view="simple"))
        assert "Effort" not in out.get("label", "")

    def test_open_submenu_is_reported_with_its_id(self):
        out = _walk(_picker(view="advanced", effort_expanded=True, with_submenu=True))
        assert out["state"] == "open", out
        assert out["submenu"] == SUB_ID

    def test_expanded_but_open_submenu_element_missing_is_not_open(self):
        # `aria-expanded=true` with no element behind the id is a half-rendered
        # menu, and answering "open" would hand the caller an id it cannot read.
        out = _walk(_picker(view="advanced", effort_expanded=True, with_submenu=False))
        assert out["state"] != "open", out

    def test_no_picker_open(self):
        out = _walk(el("body", {}, kids=[el("button", {"id": PILL_ID}, "Instant")]))
        assert out["state"] == "no_menu"

    def test_a_picker_with_no_effort_row_says_so(self):
        spec = _picker(view="advanced")
        # Strip the Effort row, keeping the Model row that also owns a submenu.
        group = spec["kids"][-1]["kids"][0]
        group["kids"] = [k for k in group["kids"]
                         if k["attrs"].get("id") != EFFORT_ID]
        out = _walk(spec)
        assert out["state"] == "no_effort", out
        assert out["clipped"] is False


class TestFindingTheMenu:
    def test_aria_controls_finds_it_when_the_testid_rotates(self):
        # The id link between the trigger and its popup is the durable half; the
        # testid is a name and names rot.
        out = _walk(_picker(view="advanced", testid=False))
        assert out["state"] == "effort", out
        assert out["via"] == "aria-controls"

    def test_the_testid_is_used_when_present(self):
        out = _walk(_picker(view="advanced"))
        assert out["via"] == "testid"

    def test_the_deep_research_pill_is_never_taken_for_the_picker(self):
        # ⛔ Both are composer pills with popup menus. Pressing the wrong one does
        # not open a picker — on this platform it ADDS A SECOND DEEP RESEARCH.
        dr = el("button", {"id": "dr-pill", "aria-haspopup": "menu",
                           "aria-expanded": "true", "aria-controls": "dr-menu",
                           "class": "__composer-pill"}, "Deep research")
        dr_menu = el("div", {"role": "menu", "id": "dr-menu",
                             "x": "0", "y": "0", "w": "200", "h": "200"})
        spec = _picker(view="advanced", testid=False, extra_pills=[dr, dr_menu])
        # Put the DR pill FIRST in document order so a naive scan would take it.
        spec["kids"] = [dr, dr_menu] + [k for k in spec["kids"]
                                        if k is not dr and k is not dr_menu]
        out = _walk(spec)
        assert out["state"] == "effort", out


# ── the scoped row read ───────────────────────────────────────────────────────

def _rows(spec, scope=""):
    return run_js(spec, research._CHATGPT_MENU_ROWS_JS,
                  {"groups": ROW_GROUPS, "seen": [], "scope": scope})["ret"]


class TestScopedRead:
    def test_scoped_read_returns_only_the_submenu_rows(self):
        spec = _picker(view="advanced", effort_expanded=True, with_submenu=True)
        out = _rows(spec, scope=SUB_ID)
        assert out["rows"] == TIERS, out

    def test_the_radio_group_already_excludes_the_parent_row(self):
        # ⚠ WRITTEN AFTER BEING WRONG ABOUT THIS. The first draft claimed an
        # unscoped read would rank the parent "EffortPro" row against the real
        # `Pro` row. It does not: the row groups are ORDERED, `menuitemradio`
        # matches only the submenu's rows, and the first group to yield anything
        # wins — so the read never reaches the group the parent row lives in.
        # Recorded as its own test because the next person will have the same
        # thought, and because it pins the property the ordering provides.
        spec = _picker(view="advanced", effort_expanded=True, with_submenu=True,
                       effort_value="Pro")
        assert _rows(spec)["rows"] == TIERS
        assert _rows(spec)["via"] == "radio"

    def test_scope_is_what_protects_the_FALLBACK_groups(self):
        # ⭐⭐ And here the ambiguity is real. If the submenu's rows ever stop
        # being radios — the exact rotation the third hook group exists for —
        # the read falls to `menuitem`, which matches the parent's rows too. The
        # parent's Effort row then reads "EffortPro": it NAMES the tier, it is
        # shorter than nothing else on offer, and clicking it opens a submenu
        # rather than selecting anything, while every downstream guard passes
        # because it is the element that was ranked. Scope removes the question.
        spec = _picker(view="advanced", effort_expanded=True, with_submenu=True,
                       effort_value="Pro")
        sub = [k for k in spec["kids"] if k["attrs"].get("id") == SUB_ID][0]
        for row in sub["kids"][0]["kids"]:
            row["attrs"]["role"] = "menuitem"

        unscoped = _rows(spec)
        assert unscoped["via"] == "menuitem"
        assert any(r.startswith("Effort") for r in unscoped["rows"]), (
            "the fixture must reproduce the ambiguity for this test to mean anything")

        scoped = _rows(spec, scope=SUB_ID)
        assert scoped["rows"] == TIERS
        assert not any(r.startswith("Effort") for r in scoped["rows"])

    def test_a_scope_that_has_gone_is_not_widened_to_the_document(self):
        # Silently falling back to the document would turn a vanished submenu
        # into a read of whatever else is on screen.
        spec = _picker(view="advanced", effort_expanded=True, with_submenu=True)
        out = _rows(spec, scope="no-such-id")
        assert out["rows"] == []
        assert out["scope_gone"] is True


class TestScopedClick:
    def _click(self, spec, index, expect, scope):
        return run_js(spec, research._CHATGPT_CLICK_ROW_JS,
                      {"groups": ROW_GROUPS, "via": "radio", "index": index,
                       "expect": expect, "seen": [], "scope": scope,
                       "attr": MARK, "value": "model-row"})["ret"]

    def test_the_index_resolves_inside_the_same_scope_the_read_used(self):
        spec = _picker(view="advanced", effort_expanded=True, with_submenu=True)
        out = self._click(spec, TIERS.index("Pro"), "Pro", SUB_ID)
        assert out["clicked"] is True
        assert out["text"] == "Pro"

    def test_a_moved_row_is_refused_rather_than_clicked_by_position(self):
        spec = _picker(view="advanced", effort_expanded=True, with_submenu=True)
        out = self._click(spec, 0, "Pro", SUB_ID)
        assert out["clicked"] is False
        assert out["reason"] == "label_changed"

    def test_a_vanished_scope_refuses_the_click(self):
        spec = _picker(view="advanced", effort_expanded=True, with_submenu=True)
        out = self._click(spec, 0, "Instant", "no-such-id")
        assert out["clicked"] is False
        assert out["reason"] == "scope_gone"


# ── the policy words ──────────────────────────────────────────────────────────

class _WalkPage:
    """A page that answers the nav script from a scripted list of states.

    ⚠ WRITTEN BECAUSE A MUTANT SURVIVED. Every test above exercises the page
    SCRIPT; the python driver around it — the loop that presses, waits, re-reads
    and eventually gives up — had no test at all, so removing its no-progress
    bound changed nothing anybody could see. That bound is the difference between
    a driver and a loop of real clicks on a live page.
    """

    def __init__(self, states):
        self._states = list(states)
        self.reads, self.presses, self.hovers = 0, [], []

    async def evaluate(self, js, arg=None):
        # ⚠ Only the NAV script advances the script of states. `_sr_real_click`
        # also evaluates (to clear its marker), and counting that as a read made
        # the walk appear to skip a step — the fixture lying, not the code.
        if "effortWords" not in js:
            return 0
        self.reads += 1
        # The last state repeats for ever — a picker that will not advance.
        i = min(self.reads - 1, len(self._states) - 1)
        st = self._states[i]
        return dict(st) if isinstance(st, dict) else st

    async def hover(self, sel, timeout=None):
        self.hovers.append(sel)

    async def click(self, sel, timeout=None):
        self.presses.append(sel)


def _drive(states):
    import asyncio
    page = _WalkPage(states)
    got = asyncio.run(research._chatgpt_open_effort_submenu(page, tag="[t]"))
    return got, page


class TestTheDriverLoop:
    def test_it_walks_advanced_then_effort_then_reports_the_submenu(self):
        got, page = _drive([
            {"state": "advanced", "via": "testid", "label": "Advanced"},
            {"state": "effort", "via": "testid", "label": "EffortInstant"},
            {"state": "open", "via": "testid", "submenu": SUB_ID, "label": "EffortPro"},
        ])
        assert got == SUB_ID
        assert len(page.presses) == 2, page.presses

    def test_a_picker_that_never_advances_is_ABANDONED(self):
        # ⛔⛔ The runaway guard. Unbounded, this is real clicks on a live page for
        # as long as the page keeps answering the same way.
        got, page = _drive([{"state": "advanced", "via": "", "label": "Advanced"}])
        assert got == ""
        assert len(page.presses) <= 3, (
            f"the walk pressed {len(page.presses)} times without progress")

    def test_it_gives_up_immediately_when_there_is_no_picker(self):
        got, page = _drive([{"state": "no_menu", "via": ""}])
        assert got == "" and page.presses == []

    def test_it_gives_up_when_the_picker_offers_no_such_row(self):
        got, page = _drive([{"state": "no_effort", "via": "testid", "clipped": False,
                             "expanded": "true", "rows": ["Advanced"]}])
        assert got == "" and page.presses == []

    def test_an_already_open_submenu_costs_no_press(self):
        got, page = _drive([
            {"state": "open", "via": "testid", "submenu": SUB_ID, "label": "EffortPro"}])
        assert got == SUB_ID and page.presses == []

    def test_the_submenu_row_is_HOVERED_not_only_pressed(self):
        # A nested menu opens on the pointer ARRIVING. The corpus paid for this
        # on Claude's Effort submenu: nine reported clicks, nine missing menus.
        _got, page = _drive([
            {"state": "effort", "via": "testid", "label": "EffortInstant"},
            {"state": "open", "via": "testid", "submenu": SUB_ID, "label": "EffortPro"},
        ])
        assert page.hovers, "the submenu trigger must be hovered before pressing"

    def test_the_expand_toggle_is_pressed_WITHOUT_a_hover(self):
        # It is an ordinary button, and hovering costs a quarter-second per step.
        _got, page = _drive([
            {"state": "advanced", "via": "testid", "label": "Advanced"},
            {"state": "no_effort", "via": "testid", "clipped": False,
             "expanded": "true", "rows": []},
        ])
        assert page.hovers == [], "the toggle needs no hover"

    def test_a_page_that_explodes_is_survived(self):
        class _Boom:
            async def evaluate(self, js, arg=None):
                raise RuntimeError("target closed")
        import asyncio
        assert asyncio.run(
            research._chatgpt_open_effort_submenu(_Boom(), tag="[t]")) == ""

    def test_a_press_that_cannot_land_ends_the_walk(self):
        class _Stuck(_WalkPage):
            async def click(self, sel, timeout=None):
                raise RuntimeError("not clickable")

        import asyncio
        page = _Stuck([{"state": "effort", "via": "testid", "label": "EffortInstant"}])
        # ⚠ `_sr_real_click` falls back to a dispatched pointer chain, which the
        # nav script's own return decides — so this asserts the walk ENDS rather
        # than that it never pressed.
        assert asyncio.run(
            research._chatgpt_open_effort_submenu(page, tag="[t]")) == ""


class _PickerPage:
    """Drives `_chatgpt_pick_effort_tier` end to end by script identity.

    ⛔⛔ WRITTEN BECAUSE THE ADVERSARIAL PASS FOUND A REAL DEFECT THE WHOLE SUITE
    ABOVE COULD NOT SEE. The walk gives ChatGPT's picker a NESTED submenu, and the
    function dismissed with ONE Escape at all eight of its exits. One Escape
    closes the inner menu and leaves the picker sitting over the composer — which
    is #751 verbatim on the other platform: "the restructure added the nested
    submenu but kept the single Escape". Every test above exercises a page script
    in isolation, so none of them could observe how many times Escape was pressed.
    """

    def __init__(self, *, open_for=0, rows=("Advanced", "ModelGPT-5.6 Sol")):
        self.open_for = open_for      # how many Escapes it takes to shut
        self.rows = list(rows)
        self.escapes = 0
        self.keyboard = self._Keyboard(self)

    class _Keyboard:
        def __init__(self, page):
            self._page = page

        async def press(self, key):
            if key == "Escape":
                self._page.escapes += 1

    async def evaluate(self, js, arg=None):
        if "effortWords" in js:                       # the walk
            return {"state": "no_effort", "via": "testid", "clipped": False,
                    "expanded": "true", "rows": self.rows}
        if "open: true, trigger" in js:               # is the picker still shut?
            return {"open": self.escapes < self.open_for, "trigger": "Instant"}
        if "reason: 'no_trigger'" in js:              # mark the trigger
            return {"marked": True, "via": "pill", "text": "Instant"}
        if "seen_used" in js:                         # the row read
            return {"via": "menuitem", "rows": self.rows, "rejected": 0,
                    "seen_used": []}
        if "out.indexOf(t) === -1" in js:             # the pre-open census
            return []
        if "let n = 0;" in js:                        # unmark
            return 0
        if "found: false, via: '', text: ''" in js:   # the trigger read
            return {"found": True, "via": "pill", "text": "Instant"}
        return {}

    async def hover(self, sel, timeout=None):
        pass

    async def click(self, sel, timeout=None):
        pass


def _pick(page):
    import asyncio
    return asyncio.run(research._chatgpt_pick_effort_tier(page, phase=1))


class TestTheNoProVerdictIsNotOverclaimed:
    """⛔⛔ SECOND DEFECT FOUND BY THE ADVERSARIAL PASS.

    `no_target` is the "this account has no Pro" verdict and the caller acts on it
    as a fact about the SUBSCRIPTION. Reading the two-level picker's STRUCTURAL
    rows — `Advanced`, `Model …`, `Effort …` — and reporting a plan limit from them
    takes a perfectly good Pro account down the no-subscription path. The
    function's own comment had already set the rule it was breaking: "`no_target`
    is a STRONG claim … it must not rest on the weakest hook."

    ⚠ AND MY FIRST FIX FOR IT WAS WRONG, caught by an EXISTING test. I keyed the
    verdict on "did the walk reach the submenu", which broke the legitimate case:
    on the older FLAT layout the rows already read ARE the tier list, so "none
    names Pro" is exactly the signal that must still be given. The question was
    never "did the walk succeed" but "was what we ranked a TIER LIST" — and the
    capture answers that: tiers are `menuitemradio`, structural rows are plain
    `menuitem`.
    """

    def test_structural_rows_are_not_a_tier_list_so_the_verdict_is_UNSURE(self):
        page = _PickerPage(open_for=0, rows=["Advanced", "ModelGPT-5.6 Sol"])
        assert _pick(page) == "unsure", (
            "structural rows must not be reported as a no-Pro subscription")

    def test_a_real_TIER_LIST_with_no_pro_row_IS_a_no_pro_verdict(self):
        # The control, and the reason this must not be softened everywhere:
        # a lapsed or absent Pro plan is a real thing the caller has to hear.
        class _Tiers(_PickerPage):
            async def evaluate(self, js, arg=None):
                if "seen_used" in js:
                    return {"via": "radio",
                            "rows": ["Instant", "Medium", "High", "Extra High"],
                            "rejected": 0, "seen_used": []}
                return await super().evaluate(js, arg)

        assert _pick(_Tiers(open_for=0)) == "no_target"

    def test_a_tier_list_reached_THROUGH_the_submenu_also_says_no_pro(self):
        # The new layout's honest no-Pro path: we walked in, the tiers were there,
        # and Pro was not among them.
        class _Walked(_PickerPage):
            async def evaluate(self, js, arg=None):
                if "effortWords" in js:
                    return {"state": "open", "via": "testid", "submenu": SUB_ID,
                            "label": "EffortInstant"}
                if "seen_used" in js:
                    return {"via": "radio",
                            "rows": ["Instant", "Medium", "High", "Extra High"],
                            "rejected": 0, "seen_used": []}
                return await super().evaluate(js, arg)

        assert _pick(_Walked(open_for=0)) == "no_target"


class TestTheMenuIsActuallyDismissed:
    # ⚠ These assert on the ESCAPE COUNT, not on the verdict. The verdict for this
    # fixture is `unsure` — the walk never reaches the tier rows — and pinning it
    # here as well would make a dismissal test fail for a reason about something
    # else, which is how a test ends up being "fixed" by deleting it.

    def test_a_nested_submenu_takes_more_than_one_escape(self):
        # ⛔ The defect. With the picker still reporting open after one press, a
        # single-Escape dismissal walks away leaving it over the composer.
        page = _PickerPage(open_for=2)
        _pick(page)
        assert page.escapes >= 2, (
            f"pressed Escape {page.escapes}x and left the picker open")

    def test_a_single_level_menu_costs_exactly_one_escape(self):
        # ⭐ And no more. A blind double-press would send a second Escape into a
        # UI with nothing open — a keystroke aimed at whatever is focused.
        page = _PickerPage(open_for=1)
        _pick(page)
        assert page.escapes == 1, page.escapes

    def test_it_stops_pressing_rather_than_hammering_a_stuck_menu(self):
        page = _PickerPage(open_for=99)
        _pick(page)
        assert page.escapes <= 3, page.escapes

    def test_an_already_closed_picker_is_left_alone_after_one_press(self):
        page = _PickerPage(open_for=0)
        _pick(page)
        assert page.escapes == 1


class TestTheCallerActuallyWalks:
    """⭐ Pinning the CONSUMER. A walk that is correct and never called is the
    failure this repo has hit five times in one effort, and every test above
    exercises the page script directly."""

    def _src(self):
        import inspect
        return inspect.getsource(research._chatgpt_pick_effort_tier)

    def test_the_walk_is_reached_from_the_picker(self):
        src = self._src()
        assert "_chatgpt_open_effort_submenu(page, tag=tag, trace=tr)" in src

    def test_it_runs_only_AFTER_the_flat_read_found_no_tier(self):
        # ⛔ The ordering that keeps every older layout untouched. Walking first
        # would open a submenu on a menu that already listed the tiers, which is
        # the "the model selector opens twice" complaint by another road.
        src = self._src()
        first_pick = src.index("pick = pick_effort_tier(rows, tiers, verbs)")
        walk = src.index("_chatgpt_open_effort_submenu")
        assert first_pick < walk, "the flat read must be tried first"
        guard = src.rindex("if not pick:", 0, walk)
        assert walk - guard < 900, "the walk must be guarded by the flat read failing"

    def test_the_rows_are_re_read_INSIDE_the_submenu(self):
        src = self._src()
        at = src.index("_CHATGPT_MENU_ROWS_JS,\n                        {\"groups\"")
        assert '"scope": _scope' in src[at:at + 260]

    def test_the_click_resolves_in_that_same_scope(self):
        src = self._src()
        at = src.index("_CHATGPT_CLICK_ROW_JS")
        assert '"scope": _scope' in src[at:at + 400], (
            "the click must re-resolve its index against the set the read ranked")


class TestPolicyWords:
    def test_the_walk_words_live_in_policy_not_in_the_page_script(self):
        # A rename must be one policy edit with a test behind it, not a regex
        # buried in a JS string — which is what every other word here already is.
        assert p1_words("chatgpt", "effort_row_words") == ["effort"]
        assert p1_words("chatgpt", "advanced_words") == ["advanced"]

    def test_no_walk_word_means_no_walk_rather_than_a_failure(self):
        # A platform that never grew a second level opts out by having no word,
        # and that must not read as a broken selector.
        assert p1_words("gemini", "effort_row_words") == []
