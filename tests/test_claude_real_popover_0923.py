"""Claude's model popover as it really is on 2026-09-23 — replayed through the
real page scripts.

The owner approved a read-only capture at 00:25 on 2026-09-23 (five rounds,
identical apart from React's generated ids). It is committed as
`fixtures/panels/claude_model_popover_20260923.html` (the popover's outerHTML) and
`.json` (the structural description the capture script wrote beside it):

    Fable 5.1 · Opus 5.5 (checked) · Sonnet 5 · Haiku 4.5 · Effort [Max] · More models

What it settled:

  * The Effort row is a plain `role="menuitem"` inside the `role="menu"` popover.
    It has NO `effort-menu-trigger` test id any more — the id the 08-17 fix
    relied on to find the row AND to tell the popover from the submenu.
  * The row shows the tier in effect beside its label ("Effort" + "Max").

What it did NOT capture, and these tests say so rather than guess:

  * The Effort SUBMENU. The script opens the top popover and presses Escape; it
    never clicks inside. Where a test needs a submenu it is CONSTRUCTED, labelled
    as such, and used only to show the production code fails SAFE (presses
    nothing it cannot identify) and LOUD (names what it saw).
  * The model BUTTON. The trigger below is reconstructed from facts on record:
    the 08-17 capture's `data-testid="model-selector-dropdown"` and "Model: …"
    aria-label, the logged text shape 'Opus 5 Max\\ue027' (backend.log, August),
    and this capture's checked row (Opus 5.5) and Effort value (Max).

Every script here is the production script, executed through tests/_domshim.py.
The end-to-end tests drive `setup_claude_dr` against a page double whose
`evaluate` RUNS each script on one persistent document (`run_js(keep_dom=True)`),
so a mark one script writes is there for the next — as in a browser.
"""
import asyncio
import copy
import inspect
import json
import re
import textwrap
from pathlib import Path

import pytest

import models
import research
from _domshim import NODE, el, evaluate_js, js_constant, run_js, spec_from_html
from conftest import code_only

pytestmark = pytest.mark.skipif(NODE is None, reason="node runs the page scripts")

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "panels"
POPOVER_HTML = FIXTURES / "claude_model_popover_20260923.html"
POPOVER_JSON = FIXTURES / "claude_model_popover_20260923.json"

EFFORT_ROW_ID = "base-ui-_r_56_"          # the captured Effort row
GLYPH = ""                           # the icon glyph the logged trigger text ends in
MARK = research._SR_CLICK_MARK
ROW_ATTR = research._CLAUDE_EFFORT_ROW_ATTR


# ── the page ──────────────────────────────────────────────────────────────

def _popover(effort="Max"):
    """The captured popover. `effort` rewrites ONLY the Effort row's value, to
    stand in for an account whose tier has drifted (the 09-20 run was on Low)."""
    spec = spec_from_html(POPOVER_HTML.read_text(encoding="utf-8"))
    if effort != "Max":
        row = _find(spec, lambda n: n["attrs"].get("id") == EFFORT_ROW_ID)
        val = _find(row, lambda n: n["text"] == "Max")
        val["text"] = effort
    return spec


def _trigger(text="Opus 5.5 Max"):
    """RECONSTRUCTED — see the module docstring."""
    return el("button", {"data-testid": research._CLAUDE_MODEL_TRIGGER_TESTID,
                         "aria-label": f"Model: {text}", "aria-haspopup": "menu",
                         "aria-expanded": "true", "id": "base-ui-_r_3i_"},
              text + GLYPH)


def _decoys():
    """Everything on a claude.ai page that reads "Effort…" and is NOT the row: a
    sidebar button, a sidebar conversation link, and a bullet in Claude's own
    reply. All of them come BEFORE the portalled popover in document order."""
    return [
        el("nav", {}, "", [
            el("button", {"aria-label": "DECOY-sidebar"}, "Effort estimates"),
            el("li", {}, "", [el("a", {"href": "/chat/8f3c"}, "Effort planning")]),
        ]),
        el("main", {}, "", [el("ul", {}, "", [el("li", {}, "Effort: max")])]),
    ]


def _page(*, trigger="Opus 5.5 Max", effort="Max", decoys=True, popover=True):
    kids = (_decoys() if decoys else []) + [_trigger(trigger)]
    if popover:
        kids.append(_popover(effort))
    return el("body", {}, "", kids)


def _find(node, pred):
    if pred(node):
        return node
    for k in node.get("kids", []):
        hit = _find(k, pred)
        if hit is not None:
            return hit
    return None


def _all(node, pred, out=None):
    out = [] if out is None else out
    if pred(node):
        out.append(node)
    for k in node.get("kids", []):
        _all(k, pred, out)
    return out


def _text(node):
    return node["text"] + "".join(_text(k) for k in node.get("kids", []))


# ── the production scripts ────────────────────────────────────────────────

def _opener_js():
    return evaluate_js(research.setup_claude_dr, contains="const linky = el =>")


def _picker_js():
    return evaluate_js(research.setup_claude_dr, contains="isWanted")


_OPENER_ARGS = {"attr": MARK, "value": "claude-effort",
                "testid": research._CLAUDE_EFFORT_TRIGGER_TESTID, "rowAttr": ROW_ATTR}
_PROBE_ARGS = {"trigTestid": research._CLAUDE_EFFORT_TRIGGER_TESTID,
               "rowAttr": ROW_ATTR, "optTestid": "effort-option-max"}
_PICK_ARGS = {**_PROBE_ARGS, "word": "max", "attr": MARK,
              "value": "claude-effort-option"}
_MODEL_ARGS = {"fam": "opus", "verbs": list(models.UPSELL_VERBS),
               "upsellWindow": models.UPSELL_WINDOW}


def _open(spec):
    """Run the real Step 1C marker; return (its answer, the document after)."""
    out = run_js(spec, _opener_js(), _OPENER_ARGS, keep_dom=True)
    return out["ret"], out["dom"]


# ═════════════════════════════════════════════════════════════════════════════
# The fixture is the capture
# ═════════════════════════════════════════════════════════════════════════════

def test_the_fixture_is_the_capture_it_claims_to_be():
    """Guards the evidence itself: a fixture someone later "tidied" would pin
    their theory of the markup, not the page's."""
    spec = _popover()
    assert spec["attrs"].get("role") == "menu"
    rows = _all(spec, lambda n: n["attrs"].get("role") == "menuitemradio")
    assert [r["attrs"].get("data-model-id") for r in rows] == [
        "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5",
        "claude-haiku-4-5-20251001"]
    assert [r["attrs"].get("aria-checked") for r in rows] == [
        "false", "true", "false", "false"]
    effort = _find(spec, lambda n: n["attrs"].get("id") == EFFORT_ROW_ID)
    assert effort["attrs"].get("role") == "menuitem"
    assert "data-testid" not in effort["attrs"], "the 08-17 id is gone on today's page"
    # …and the structural JSON the capture wrote agrees about where the row lives.
    desc = json.loads(POPOVER_JSON.read_text(encoding="utf-8"))
    chain = desc["effort_rows"][0]["ancestors"]
    assert chain[1]["id"] == EFFORT_ROW_ID and chain[1]["role"] == "menuitem"
    assert chain[3]["role"] == "menu" and chain[3]["id"] == spec["attrs"]["id"]


# ═════════════════════════════════════════════════════════════════════════════
# The model: the real menu picks Opus 5.5, never Fable 5.1
# ═════════════════════════════════════════════════════════════════════════════

def _pick(page, **kw):
    out = run_js(page, js_constant(research.setup_claude_dr, "_pick_opus_js"),
                 {**_MODEL_ARGS, "triggerText": "", "pin": None, "below": None, **kw})
    return out["ret"], out["clicks"]


def test_the_real_menu_picks_the_opus_5_5_row():
    ret, clicks = _pick(_page(trigger="Sonnet 5 Max"))
    assert ret == {"label": "Opus 5.5", "version": "5.5"}, ret
    # The element clicked is the Opus row's own label — the only node on the
    # page whose text is exactly "Opus 5.5" — never the wrapper or another row.
    assert clicks == ["Opus 5.5"], clicks


@pytest.mark.parametrize("pin,below", [
    (None, "5.5"),     # step back below a failed 5.5: Fable 5.1 IS below it
    ("5.1", None),     # a stale pin whose number Fable happens to carry
    ("5.1", "5.5"),
])
def test_fable_5_1_is_never_picked_by_the_opus_family(pin, below):
    """Fable 5.1 is the one versioned row on this menu below 5.5, so any
    retreat that lost the family rule would land on it. The Opus family has
    nothing below 5.5 here: the honest answer is to pick nothing."""
    ret, clicks = _pick(_page(), pin=pin, below=below)
    assert ret is None, ret
    assert not any("fable" in c.lower() for c in clicks), clicks


def test_the_probe_reads_5_5_as_the_highest_opus_offered():
    ret = run_js(_page(), js_constant(research.setup_claude_dr, "_probe_opus_js"),
                 _MODEL_ARGS)["ret"]
    assert ret["menu"] is True and ret["n"] > 0
    assert ret["highest"] == "5.5"
    assert ret["chipsAny"] is False, "no row on the real menu is a sales prompt"


def test_the_trigger_reads_5_5_beside_the_open_real_menu():
    """With the real popover OPEN, every model row is in the document — Fable
    5.1, Sonnet 5, Haiku 4.5. The trigger read must answer from the button."""
    ret = run_js(_page(), js_constant(research.setup_claude_dr, "_TRIGGER_READ_JS"),
                 {"effortWord": "max", "fam": "opus"})["ret"]
    assert ret["ver"] == "5.5" and ret["fam"] is True
    assert ret["effort"] == "max"


# ═════════════════════════════════════════════════════════════════════════════
# The Effort row: found inside the menu, never anywhere else on the page
# ═════════════════════════════════════════════════════════════════════════════

def _marked(dom):
    return [n["attrs"].get("id") or _text(n)[:30]
            for n in _all(dom, lambda n: MARK in n["attrs"])]


def test_the_effort_row_is_found_inside_the_real_menu():
    ret, dom = _open(_page(decoys=False))
    assert ret["marked"] is True and ret["via"] == "text"
    assert ret["shows"] == "effort max"
    assert research._claude_effort_from_row(ret["shows"]) == "max"
    assert _marked(dom) == [EFFORT_ROW_ID]


def test_an_effort_control_elsewhere_on_the_page_is_never_the_row_marked():
    """⭐ The whole scoping fix. The old search walked the DOCUMENT and took the
    first "Effort…" control in order — the sidebar button, which precedes the
    portalled popover. A real press on it opens something else entirely, and
    the run reports what that something reads as its effort tier."""
    ret, dom = _open(_page())
    assert _marked(dom) == [EFFORT_ROW_ID], _marked(dom)
    assert ret["shows"] == "effort max"
    # Nothing outside the menu was even a candidate.
    assert ret["rejected"] == [], ret["rejected"]


def test_the_old_test_id_outside_every_menu_is_not_the_row():
    """The id lookup is scoped too. An element carrying `effort-menu-trigger`
    that is not inside an open menu (a closed menu's shell left in the page, a
    settings screen reusing the id) is not the row in the popover the run
    opened — and pressing it opens something else."""
    stray = el("div", {"data-testid": research._CLAUDE_EFFORT_TRIGGER_TESTID,
                       "aria-label": "DECOY-stray-id"}, "Effort Low")
    ret, dom = _open(el("body", {}, "", [stray, _trigger(), _popover()]))
    assert ret["via"] == "text" and _marked(dom) == [EFFORT_ROW_ID], _marked(dom)
    ret, dom = _open(el("body", {}, "", [stray, _trigger()]))
    assert ret["marked"] is False and _marked(dom) == []


def test_with_no_menu_open_nothing_is_marked_at_all():
    """The popover closed (a model pick closes it): the decoys are all that is
    left, and none of them may be pressed as the Effort row."""
    ret, dom = _open(_page(popover=False))
    assert ret["marked"] is False and ret["menus"] == 0
    assert _marked(dom) == []


def test_the_row_marker_names_only_the_row_it_chose():
    """The attribute the probe and the picker read is written on the chosen row
    and nowhere else, and a stale one from an earlier pass is cleared first."""
    page = _page()
    stale = _find(page, lambda n: n["attrs"].get("aria-label") == "DECOY-sidebar")
    stale["attrs"][ROW_ATTR] = "1"
    _, dom = _open(page)
    stamped = _all(dom, lambda n: ROW_ATTR in n["attrs"])
    assert [n["attrs"].get("id") for n in stamped] == [EFFORT_ROW_ID]


# ═════════════════════════════════════════════════════════════════════════════
# The popover is never mistaken for the submenu
# ═════════════════════════════════════════════════════════════════════════════

def test_the_real_popover_alone_reads_as_closed_not_as_a_submenu():
    """With no test id, the probe could not tell the popover from a submenu, so
    the popover ALONE read 'maybe' and the picker ran against it."""
    _, dom = _open(_page())
    probe = run_js(dom, research._CLAUDE_EFFORT_SUBMENU_JS, _PROBE_ARGS)["ret"]
    assert [o["trigger"] for o in probe["overlays"]] == [True]
    assert research._claude_effort_submenu_verdict(probe) == "closed"


def test_the_picker_never_searches_the_real_popover():
    """⭐ The 09-20 log line — "no 'max' row in the submenu — rows=[opus 5…,
    effortlow, more models]" — was the POPOVER's rows. The picker must search
    nothing when the popover is all that is open."""
    _, dom = _open(_page())
    ret = run_js(dom, _picker_js(), _PICK_ARGS)["ret"]
    assert ret["set"] is None
    assert ret["cands"] == 0 and ret["saw"] == [], ret


# A CONSTRUCTED submenu — the real one was not captured. Two shapes, and neither
# is a claim about claude.ai: the 08-06 capture's measured labels without Max
# (the shape of the 09-20 miss), and rows that carry a description the way every
# model row on today's popover does.
def _submenu(labels):
    return el("div", {"role": "menu", "id": "CONSTRUCTED-submenu"}, "", [
        el("div", {"role": "menuitemradio", "aria-checked": "false"}, t)
        for t in labels])


def _with_submenu(dom, labels):
    dom = copy.deepcopy(dom)
    dom["kids"].append(_submenu(labels))
    return dom


def test_a_miss_names_the_submenus_rows_not_the_popovers():
    _, dom = _open(_page())
    dom = _with_submenu(dom, ["Low", "Medium", "HighDefault", "Extra"])
    probe = run_js(dom, research._CLAUDE_EFFORT_SUBMENU_JS, _PROBE_ARGS)["ret"]
    assert research._claude_effort_submenu_verdict(probe) == "open"
    ret = run_js(dom, _picker_js(), _PICK_ARGS)["ret"]
    assert ret["set"] is None and ret["cands"] == 1
    assert ret["saw"] == ["low", "medium", "highdefault", "extra"], ret["saw"]


def test_a_submenu_row_with_a_description_is_reported_not_guessed_at():
    """FAIL SAFE AND LOUD. If the real submenu's rows carry descriptions, the
    exact-label match finds no 'max' and presses nothing — and the log now
    carries those rows (cut to 40 characters) instead of dropping every row
    longer than 24 and printing an empty list."""
    _, dom = _open(_page())
    dom = _with_submenu(dom, ["Low", "Max Deepest reasoning, uses more of your limit"])
    ret = run_js(dom, _picker_js(), _PICK_ARGS)["ret"]
    assert ret["set"] is None
    assert ret["saw"] == ["low", "max deepest reasoning, uses more of your"], ret["saw"]
    after = run_js(dom, _picker_js(), _PICK_ARGS, keep_dom=True)["dom"]
    assert not _all(after, lambda n: n["attrs"].get(MARK) == "claude-effort-option")


def test_with_no_menu_the_miss_report_keeps_to_short_labels():
    """⛔ The long-row report is for a MENU only. With no menu open the picker's
    last pool is the document (test-id resolution only), and a long text there is
    the user's own conversation — it must not reach the log, cut or not."""
    prose = "Max effort is what I asked for in the brief about the research"
    page = el("body", {}, "", [el("ul", {}, "", [el("li", {}, prose),
                                                  el("li", {}, "Short row")])])
    ret = run_js(page, _picker_js(), _PICK_ARGS)["ret"]
    assert ret["set"] is None and ret["menus"] == 0
    assert all(len(t) <= 24 for t in ret["saw"]), ret["saw"]
    assert not any(t.startswith("max effort is") for t in ret["saw"]), ret["saw"]


def test_a_submenu_that_offers_max_is_still_picked():
    """The exclusion must not cost the working path: the submenu is searched."""
    _, dom = _open(_page())
    dom = _with_submenu(dom, ["Low", "Medium", "High", "Max"])
    out = run_js(dom, _picker_js(), _PICK_ARGS, keep_dom=True)
    assert out["ret"]["set"] == "marked" and out["ret"]["picked"] == "max"
    picked = _all(out["dom"], lambda n: n["attrs"].get(MARK) == "claude-effort-option")
    assert [_text(n) for n in picked] == ["Max"]


# ═════════════════════════════════════════════════════════════════════════════
# The decision: a row that already shows the tier needs nothing set
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("shows,wanted,want", [
    ("max", "max", True),
    ("MAX", " Max ", True),
    ("low", "max", False),
    (None, "max", False),       # unread: never a confirmation
    ("", "max", False),
    ("max", "", False),         # nothing wanted, nothing to confirm
    (None, None, False),
])
def test_only_a_positive_read_of_the_wanted_tier_confirms(shows, wanted, want):
    assert research._claude_effort_row_confirms(shows, wanted) is want


# ═════════════════════════════════════════════════════════════════════════════
# End to end: setup_claude_dr against the real popover, every script executed
# ═════════════════════════════════════════════════════════════════════════════

class _Keyboard:
    def __init__(self, keys):
        self._keys = keys

    async def press(self, key):
        self._keys.append(key)


class DomPage:
    """A page whose `evaluate` RUNS each script on one persistent document.

    `hover`/`click` resolve the `[attr="value"]` selector `_sr_real_click` aims
    at; `on_press(page, node)` is what the press does to the page (by default,
    nothing — the submenu was never captured)."""

    def __init__(self, spec, on_press=None):
        self.spec = spec
        self.on_press = on_press
        self.scripts, self.clicks, self.presses, self.keys = [], [], [], []
        self.keyboard = _Keyboard(self.keys)

    async def evaluate(self, script, arg=None):
        self.scripts.append(script)
        out = run_js(self.spec, script, arg, keep_dom=True)
        self.spec = out["dom"]
        self.clicks.extend(out.get("clicks") or [])
        return out.get("ret")

    async def query_selector(self, sel):
        return None

    def _node(self, sel):
        m = re.fullmatch(r'\[([\w-]+)="([^"]*)"\]', sel)
        node = m and _find(self.spec, lambda n: n["attrs"].get(m.group(1)) == m.group(2))
        if not node:
            raise RuntimeError(f"no element matches {sel}")
        return node

    async def hover(self, sel, timeout=None):
        self._node(sel)

    async def click(self, sel, timeout=None):
        node = self._node(sel)
        self.presses.append(node["attrs"].get("id") or _text(node)[:30])
        if self.on_press:
            self.on_press(self, node)

    def ran(self, fragment):
        return any(fragment in s for s in self.scripts)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH", tmp_path / "mr.json")
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "1")

    async def _instant(_secs):
        return None
    monkeypatch.setattr(research.asyncio, "sleep", _instant)
    research._P2_THINKING_STATE.pop("claude", None)
    research._P2_PICKED_VERSION.pop("claude", None)


@pytest.fixture()
def said(monkeypatch):
    got = {"log": [], "events": []}
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: got["log"].append((level, msg)))
    monkeypatch.setattr(research, "emit_event",
                        lambda *a, **k: got["events"].append((a, k)))
    return got


def _run(page, **kw):
    return asyncio.run(research.setup_claude_dr(page, **kw))


def _lines(said, needle):
    return [m for _, m in said["log"] if needle in m]


def _captions(said):
    return [k.get("progress") for a, k in said["events"]
            if a and a[0] == "agent_progress" and k.get("agent") == "claude"]


def test_e2e_today_the_weekly_check_finds_5_5_is_the_newest(said):
    """The owner's account today: the button reads Opus 5.5 Max and the weekly
    model check is due. The popover opens, 5.5 is the highest Opus offered, and
    nothing on the menu is clicked."""
    page = DomPage(_page())
    _run(page, allow_probe=True)
    assert _lines(said, "Step 1B*: opus 5.5 is already the highest offered (5.5)"), said["log"]
    assert not _lines(said, "Effort control not found"), said["log"]
    assert not any(c in ("Opus 5.5", "Fable 5.1") for c in page.clicks), page.clicks
    assert research._P2_PICKED_VERSION.get("claude") == "5.5"
    assert research._P2_THINKING_STATE["claude"]["effort"] is True


def test_e2e_the_effort_row_showing_max_is_confirmed_without_a_press(said):
    """⭐ The button does not show the tier, so Step 1C runs — on today's page,
    against the real row, which reads Max. Nothing is pressed; the submenu whose
    markup nobody has captured is never entered; the run says Max."""
    page = DomPage(_page(trigger="Opus 5.5"))
    _run(page, allow_probe=True)
    assert page.presses == [], page.presses
    assert not page.ran("isWanted"), "the submenu picker ran for a tier already set"
    assert _lines(said, "Step 1C OK: the Effort row already shows 'max'"), said["log"]
    assert not _lines(said, "Effort control not found")
    assert research._P2_THINKING_STATE["claude"]["effort"] is True
    assert research._P2_THINKING_STATE["claude"]["effort_got"] == "max"
    ledger = _lines(said, "claude.select_effort_tier")
    assert ledger and "verified" in ledger[-1] and "via=row" in ledger[-1], ledger
    assert _captions(said) == []
    assert not _all(page.spec, lambda n: MARK in n["attrs"]), "a click mark was left behind"


def test_e2e_a_low_row_is_pressed_on_the_row_and_the_run_says_low(said):
    """The 09-20 account (Low), on today's markup. The press lands on the real
    row, not the sidebar button that precedes it. No submenu mounts (none was
    captured), the popover is not mistaken for one, the picker never runs
    against it — and the run says Low in the log, and records it for the tile.

    ⛔ NOT ON THE TILE YET. The computer-use pass that runs next is told to set
    Max; a caption posted here said "Low — Max could not be set" for minutes
    after that pass had set it. The caption is the pre-send check's (below).
    ⛔ And no "Effort control not found" after the row WAS found and pressed."""
    page = DomPage(_page(trigger="Opus 5.5", effort="Low"))
    _run(page, allow_probe=True)
    assert page.presses == [EFFORT_ROW_ID], page.presses
    assert _lines(said, "no submenu mounted"), said["log"]
    assert not _lines(said, "Effort control not found"), said["log"]
    assert not page.ran("isWanted"), "the picker searched the popover as a submenu"
    assert _lines(said, "effort in effect: 'low' — wanted 'max', which could not be set")
    assert _captions(said) == []
    assert research._P2_THINKING_STATE["claude"]["effort"] is False
    assert research._P2_THINKING_STATE["claude"]["effort_got"] == "low"


def _without_effort_row(spec):
    """The captured page with the Effort row taken out of the popover."""
    def _prune(node):
        node["kids"] = [k for k in node.get("kids", [])
                        if k["attrs"].get("id") != EFFORT_ROW_ID]
        for k in node["kids"]:
            _prune(k)
    _prune(spec)
    assert _find(spec, lambda n: n["attrs"].get("id") == EFFORT_ROW_ID) is None
    return spec


def test_e2e_a_menu_with_no_effort_row_says_the_control_was_not_found(said):
    """The other polarity: with no row to press, "not found" IS the diagnosis."""
    page = DomPage(_without_effort_row(_page(trigger="Opus 5.5")))
    _run(page, allow_probe=True)
    assert page.presses == [], page.presses
    assert _lines(said, "Effort control not found in the 1 open menu(s)"), said["log"]
    assert not _lines(said, "no submenu mounted"), said["log"]


def test_e2e_a_setup_that_stops_early_does_not_keep_the_last_runs_tier(said):
    """⛔ The effort state is process-wide and written only at the end of setup.
    Run 1 reads Low; run 2 stops at Step 1B. Before the fix run 2's pre-send
    line said "effort is 'low'" — a tier run 2 never read."""
    _run(DomPage(_page(trigger="Opus 5.5", effort="Low")), allow_probe=True)
    assert research._P2_THINKING_STATE["claude"]["effort_got"] == "low"
    assert _run(DomPage(_page()), step_below="5.5") is False
    assert _lines(said, "Step 1B FAIL"), said["log"]
    assert "claude" not in research._P2_THINKING_STATE
    lines, captions = _run_telemetry(research._P2_THINKING_STATE.get("claude"),
                                     {"effortOk": False}, with_captions=True)
    assert [m for _, m in lines if "thinking config unconfirmed (max effort)" in m], lines
    assert captions == []


def _open_constructed_submenu(labels, *, checks=True):
    """on_press: pressing the Effort row mounts a CONSTRUCTED submenu; pressing
    one of its rows checks it."""
    def _press(page, node):
        if node["attrs"].get("id") == EFFORT_ROW_ID:
            page.spec["kids"].append(_submenu(labels))
        elif checks and node["attrs"].get("role") == "menuitemradio":
            node["attrs"]["aria-checked"] = "true"
    return _press


def test_e2e_a_submenu_without_max_is_reported_by_its_own_rows(said):
    page = DomPage(_page(trigger="Opus 5.5", effort="Low"),
                   on_press=_open_constructed_submenu(["Low", "Medium", "HighDefault",
                                                       "Extra"]))
    _run(page, allow_probe=True)
    miss = _lines(said, "no 'max' row in the submenu")
    assert miss and '["low", "medium", "highdefault", "extra"]' in miss[-1], miss
    assert "opus" not in miss[-1] and "effortlow" not in miss[-1], miss
    assert _lines(said, "effort in effect: 'low'")


def test_e2e_a_submenu_that_offers_max_sets_it(said):
    page = DomPage(_page(trigger="Opus 5.5", effort="Low"),
                   on_press=_open_constructed_submenu(["Low", "Medium", "High", "Max"]))
    _run(page, allow_probe=True)
    assert page.presses[0] == EFFORT_ROW_ID and page.presses[1] == "Max", page.presses
    assert _lines(said, "Step 1C OK: Effort 'max' selected"), said["log"]
    assert research._P2_THINKING_STATE["claude"]["effort"] is True


def test_e2e_the_real_menu_selects_opus_5_5_when_the_model_is_wrong(said):
    page = DomPage(_page(trigger="Sonnet 5 Max"))
    _run(page, allow_probe=True)
    assert "Opus 5.5" in page.clicks and "Fable 5.1" not in page.clicks, page.clicks
    assert _lines(said, "Step 1B OK: selected 'Opus 5.5' (v5.5)"), said["log"]
    assert research._P2_PICKED_VERSION.get("claude") == "5.5"


def test_e2e_a_step_back_below_5_5_never_lands_on_fable(said):
    """The one row below 5.5 on today's menu is Fable 5.1. The Opus family has
    nothing to retreat to, so the step-back selects nothing and says so."""
    page = DomPage(_page())
    assert _run(page, step_below="5.5") is False
    assert "Fable 5.1" not in page.clicks, page.clicks
    assert _lines(said, "Step 1B FAIL: no 'opus' option found"), said["log"]


# ═════════════════════════════════════════════════════════════════════════════
# After the computer-use pass: the telemetry line says what is known
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("state,button,missing,note", [
    ({"effort": True, "effort_got": "max"}, False, None, None),
    ({"effort": True, "effort_got": None}, False, None, None),
    ({"effort": False, "effort_got": "low"}, False, "effort is 'low', not the 'max' wanted", None),
    ({"effort": False, "effort_got": None}, False, "max effort", None),
    ({"effort": False, "effort_got": "low"}, True, None,
     "effort 'max' now shows on the model button — set after setup, by the computer-use pass"),
    ({"effort": False, "effort_got": "max"}, False, None, None),
    ({}, False, "max effort", None),
    (None, False, "max effort", None),
])
def test_the_effort_after_setup(state, button, missing, note):
    got = research._claude_effort_after_setup("max", state, button)
    assert got == {"missing": missing, "note": note}


def test_no_wanted_tier_means_no_effort_clause():
    assert research._claude_effort_after_setup("", {"effort": False, "effort_got": "low"},
                                               False) == {"missing": None, "note": None}


def _telemetry_source() -> str:
    """The telemetry block of start_agent_no_gemini_wait, verbatim (comments
    blanked by `code_only`), wrapped as a function returning nothing."""
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    head = '        if research_ok and platform_l in ("claude", "gemini"):'
    tail = '        if not research_ok:'
    assert src.count(head) == 1, "the telemetry block header moved"
    i = src.index(head)
    block = textwrap.dedent(src[i:src.index(tail, i)])
    return "def __telemetry__(research_ok):\n" + textwrap.indent(block, "    ")


def _run_telemetry(state, mode_state, with_captions=False):
    lines, events = [], []
    ns = dict(vars(research))
    ns.update({"platform_l": "claude", "label": "2B", "mode_state": mode_state,
               "_P2_THINKING_STATE": {"claude": state},
               "record_known_good": lambda *a, **k: None,
               "emit_event": lambda *a, **k: events.append((a, k)),
               "log": lambda msg, level="INFO", *a, **k: lines.append((level, msg))})
    exec(compile(_telemetry_source(), "<telemetry>", "exec"), ns)
    ns["__telemetry__"](True)
    if with_captions:
        return lines, _captions({"events": events})
    return lines


def test_the_telemetry_line_names_the_tier_setup_read():
    lines = _run_telemetry({"effort": False, "thinking": False, "effort_got": "low"},
                           {"effortOk": False})
    hit = [m for _, m in lines if "thinking config unconfirmed" in m]
    assert hit and "(effort is 'low', not the 'max' wanted)" in hit[0], lines


def test_the_telemetry_line_rereads_the_button_after_the_computer_use_pass():
    lines = _run_telemetry({"effort": False, "thinking": False, "effort_got": "low"},
                           {"effortOk": True})
    assert not [m for _, m in lines if "thinking config unconfirmed" in m], lines
    assert [m for lv, m in lines
            if lv == "INFO" and "effort 'max' now shows on the model button" in m], lines


def test_a_low_run_says_low_on_the_tile_once_the_computer_use_pass_has_run():
    """⭐ The caption goes up at the pre-send check, after the computer-use pass
    was told to set Max and the button was read again: still Low → it says so."""
    _lines_, captions = _run_telemetry(
        {"effort": False, "thinking": False, "effort_got": "low"},
        {"effortOk": False}, with_captions=True)
    assert captions == ["Claude is researching at Low effort — Max could not be set"]


def test_no_low_caption_when_the_computer_use_pass_set_max():
    """⛔ The defect: setup read Low, the computer-use pass then set Max, and the
    tile kept saying Low and "Max could not be set" until the run was verified."""
    _lines_, captions = _run_telemetry(
        {"effort": False, "thinking": False, "effort_got": "low"},
        {"effortOk": True}, with_captions=True)
    assert captions == []


def test_no_caption_for_a_tier_nobody_read():
    _lines_, captions = _run_telemetry(
        {"effort": False, "thinking": False, "effort_got": None},
        {"effortOk": False}, with_captions=True)
    assert captions == []


def test_an_unknown_tier_is_still_worded_as_before():
    lines = _run_telemetry({"effort": False, "thinking": False, "effort_got": None},
                           {"effortOk": False})
    assert [m for _, m in lines if "thinking config unconfirmed (max effort)" in m], lines


def test_the_model_refresh_report_still_counts_the_named_tier():
    """The consumer of that line. It reads the list up to the first ')', so the
    named-tier clause must parse — as its own row in the weekly report."""
    from scripts import model_refresh_report as report
    lines = _run_telemetry({"effort": False, "thinking": False, "effort_got": "low"},
                           {"effortOk": False})
    s = report.summarize([m for _, m in lines])
    assert s["thinking_misses"] == {"effort is 'low', not the 'max' wanted": 1}


def test_the_pre_send_check_hands_the_button_read_back(monkeypatch):
    """`effortOk` is computed by the detector and was dropped on the way out; the
    telemetry line cannot re-read what the pre-send check does not return."""
    page = DomPage(_page(trigger="Opus 5.5 Max"))
    state = asyncio.run(research.ensure_deep_mode_active(page, "claude", "2B",
                                                         reactivate=False))
    assert state.get("effortOk") is True, state
    page = DomPage(_page(trigger="Opus 5.5 Low"))
    state = asyncio.run(research.ensure_deep_mode_active(page, "claude", "2B",
                                                         reactivate=False))
    assert state.get("effortOk") is False, state
