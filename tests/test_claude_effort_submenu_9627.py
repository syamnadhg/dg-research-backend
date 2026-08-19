"""Claude's effort submenu: the nine-in-ten failure, root-caused from a capture.

The retained corpus read "'Max' effort not found in submenu" nine times against one
success, and two rounds of work guessed at the cause — first the trigger being
pressed on the wrong element, then the container scope. A live read-only capture of
this popover settles it, and it was neither:

    the picker compared `norm(el.textContent) === 'max'` — exact equality —
    and the real row's text is `Max` followed by U+E08F U+E03B, Claude's icon
    font rendering a check and a chevron as text.

So the comparison could never be true. Measured in the capture: the other tiers
('Low', 'Medium', 'HighDefault', 'Extra') carry NO private-use codepoints, so the
ligature rides on the SELECTED row — which is why the failure presented as
intermittent rather than total. The one success was a run that took the
already-confirmed path and never opened the submenu at all.

Same family as the NotebookLM audio menu, where a row could not be read past its
icon ligature. Stripping the private-use area is the shared cure.

⚠ HONEST LIMIT OF THE EVIDENCE. The probe kept only the largest overlay on its
first run, so the submenu's MARKUP was not retained — only its row labels, from the
structural JSON. The fixtures below therefore rebuild the submenu from those
measured labels rather than from its own HTML, and how the selected tier is
expressed in ATTRIBUTES (`aria-checked` / `data-state`) is still unverified. The
picker keeps checking both; if neither is present it clicks Max, which is harmless
when Max is already set. The probe now dumps every overlay so the next capture
closes this.
"""
import json
from pathlib import Path

import pytest

import research
from _domshim import js_constant, run_js, spec_from_html, stamp_panel_geometry

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "panels"
POPOVER = FIXTURES / "claude_model_popover_with_submenu_20260806.html"

# The exact labels the live submenu reported, private-use glyphs included.
LIVE_SUBMENU_LABELS = ["Low", "Medium", "HighDefault", "Extra", "Max"]


def _pick_js() -> str:
    """The production submenu picker, pulled out of `setup_claude_dr`.

    Located by a distinctive line rather than by index, so inserting another
    `page.evaluate` into that function cannot silently point this at the wrong JS.

    ⚠ RE-ANCHORED 2026-08-17: this asked for "ue000" and TWO of the step's scripts
    now strip the private-use range — the row MARKER gained it so the log stops
    reporting the Effort row as 'effortmax<glyph>' and its 40-char bound measures
    real characters. The invariant is unchanged, the literal stopped being unique.
    `isWanted` is the picker's own comparator and exists nowhere else.
    """
    from _domshim import evaluate_js
    return evaluate_js(research.setup_claude_dr, contains="isWanted")


def _menu(labels, *, with_trigger=False, role="menu"):
    rows = [{"tag": "button", "attrs": {"w": "200", "h": "32", "x": "500",
                                        "y": str(100 + i * 32)},
             "text": t, "kids": []} for i, t in enumerate(labels)]
    if with_trigger:
        rows.insert(0, {"tag": "div",
                        "attrs": {"role": "menuitem",
                                  "data-testid": "effort-menu-trigger",
                                  "w": "200", "h": "32", "x": "500", "y": "60"},
                        "text": "EffortMax", "kids": []})
    return {"tag": "div", "attrs": {"role": role, "w": "240", "h": "300",
                                    "x": "500", "y": "50"},
            "text": "", "kids": rows}


# ⚠ RE-ANCHORED 2026-08-17. The picker takes params now (the trigger and option
# test ids come from policy, never from a literal in the page script) and it MARKS
# the row for a real Playwright press instead of calling `el.click()` from inside
# `page.evaluate`. That synthetic click was the last one left in a menu path in
# this file, and the component library binds its rows on pointerdown — the same
# defect, twice paid for, that this repo removed from ChatGPT's model trigger and
# from this step's own submenu opener.
#
# ⭐ These fixtures deliberately carry NO option test ids, so every case below
# still exercises the TEXT fallback and the ligature handling it exists for. The
# test id path is covered separately.
#
# ⚠ 2026-08-17: `word` is new and REQUIRED. The picker used to compare against a
# literal 'max' while the test id beside it was derived from policy, so the two
# halves of one search disagreed the moment the policy asked for another tier —
# and the text half is the half that runs on a layout with no ids.
PARAMS = {"trigTestid": research._CLAUDE_EFFORT_TRIGGER_TESTID,
          "optTestid": "", "attr": research._SR_CLICK_MARK,
          "word": "max", "value": "claude-effort-option"}

# What a successful pick now reports. `marked` means "this row is the one, press
# it"; the caller presses and then verifies it became checked.
PICKED = ("marked", "max (already)")


def _run(spec, params=None):
    return (run_js(spec, _pick_js(), params or PARAMS) or {}).get("ret") or {}


# ── The defect, reproduced and fixed against the measured labels ─────────────

def test_the_max_row_is_found_despite_its_icon_ligature():
    """The whole ticket. Exact equality against 'max' cannot match
    'max\\ue08f\\ue03b'."""
    got = _run({"tag": "body", "attrs": {}, "text": "",
                "kids": [_menu(LIVE_SUBMENU_LABELS)]})
    assert got.get("set") in PICKED, got


def test_the_ligature_is_what_broke_it():
    """Control: strip the glyphs from the fixture and the OLD comparison would have
    worked. Proves the fixture's ligature is the operative difference, not some
    other property of the row."""
    plain = [t.rstrip("") for t in LIVE_SUBMENU_LABELS]
    assert "Max" in plain
    got = _run({"tag": "body", "attrs": {}, "text": "",
                "kids": [_menu(plain)]})
    assert got.get("set") in PICKED


@pytest.mark.parametrize("glyphs", ["", "", "", "",
                                    ""])
def test_any_private_use_glyph_is_tolerated(glyphs):
    """Anchored on the RANGE, not the two codepoints observed — an icon font is
    free to renumber its glyphs between releases."""
    got = _run({"tag": "body", "attrs": {}, "text": "",
                "kids": [_menu(["Low", "High", f"Max{glyphs}"])]})
    assert got.get("set") in PICKED, (glyphs, got)


# ── Scoping: the submenu is a sibling menu, and the popover has its own rows ──

def test_the_picker_scopes_to_the_menu_without_the_trigger():
    """Two visible menus, as the live capture had: the model popover carrying its
    own 'EffortMax' row, and the submenu carrying the tiers. Choosing the popover
    would find no bare 'Max'."""
    spec = {"tag": "body", "attrs": {}, "text": "", "kids": [
        _menu(["Opus 5For complex tasks", "More models"], with_trigger=True),
        _menu(LIVE_SUBMENU_LABELS),
    ]}
    got = _run(spec)
    assert got.get("scoped") is True
    assert got.get("menus") == 2
    assert got.get("set") in PICKED


def test_the_trigger_row_itself_is_never_mistaken_for_the_tier():
    """`EffortMax` normalises to 'effortmax', not 'max', so it cannot be picked —
    but assert it, because a looser match would land on the trigger and reopen the
    submenu instead of choosing a tier."""
    spec = {"tag": "body", "attrs": {}, "text": "", "kids": [
        _menu(["Opus 5For complex tasks"], with_trigger=True)]}
    got = _run(spec)
    assert got.get("set") is None
    # ⚠ The first draft ended this line with `or True`, which made it vacuous.
    # The trigger had to be SEEN (so we knew the scan reached it) and REFUSED.
    #
    # ⚠ RE-ANCHORED 2026-08-17, to something STRICTLY STRONGER: the popover is no
    # longer scanned at all, so there is nothing to refuse. It used to fall back
    # to "the newest menu even if it holds the trigger", and the popover DISPLAYS
    # the selected tier — a nested element reading exactly "Max" — so that
    # fallback could mark the display and report a tier set from a page where the
    # submenu had never opened. `saw` is empty because the search is, and the
    # counts are what prove the page WAS read: one menu, none of it a candidate.
    assert got.get("saw") == [], got.get("saw")
    assert got.get("menus") == 1 and got.get("cands") == 0, got


def test_a_bare_max_elsewhere_on_the_page_is_never_pressed():
    """⚠ The case the scoping exists for, and which the first mutation pass let
    through: with only menus in the fixture, a document-wide search still finds the
    submenu's row, so reverting the scope changed nothing.

    Claude's own reply can render a list item reading exactly "Max". Document-wide,
    `find` takes the FIRST match in document order — the reply — and clicks it. No
    tier is set, and the run reports success. That is the same shape as the sidebar
    conversation link that caused the wrong-conversation harvest.
    """
    decoy = {"tag": "div",
             "attrs": {"aria-label": "DECOY-outside-any-menu", "w": "120",
                       "h": "24", "x": "100", "y": "400"},
             "text": "Max", "kids": []}
    spec = {"tag": "body", "attrs": {}, "text": "", "kids": [
        decoy,                                    # earlier in document order
        _menu(["Opus 5For complex tasks"], with_trigger=True),
        _menu(LIVE_SUBMENU_LABELS),
    ]}
    out = run_js(spec, _pick_js(), PARAMS) or {}
    got, clicks = out.get("ret") or {}, out.get("clicks") or []
    assert got.get("set") == "marked", got
    # ⭐ RE-ANCHORED 2026-08-17: identity now comes from the row the picker
    # REPORTS it chose. The old form asserted on the click list, which cannot
    # survive the move to marking — and marking is the fix, not a refactor.
    assert "max" in (got.get("picked") or ""), got
    assert "decoy" not in (got.get("picked") or "").lower(), got
    # ⛔ AND THE PAGE SCRIPT CLICKED NOTHING. This is the regression guard for the
    # synthetic press: `pick.click()` reported success against a page that had not
    # changed, because this component library binds its rows on pointerdown.
    assert clicks == [], (
        f"the page script clicked something instead of marking it: {clicks}")


def test_helper_prose_is_still_refused():
    """The exact-match intent survives the ligature fix."""
    got = _run({"tag": "body", "attrs": {}, "text": "", "kids": [
        _menu(["Higher effort means slower, deeper answers",
               "Max effort is best for research"])]})
    assert got.get("set") is None


def test_a_missing_row_reports_what_it_saw():
    """So the next drift is diagnosable from the log rather than needing another
    capture — which is what cost this ticket two rounds."""
    got = _run({"tag": "body", "attrs": {}, "text": "", "kids": [
        _menu(["Low", "Medium", "High"])]})
    assert got.get("set") is None
    saw = got.get("saw") or []
    assert "low" in saw and "high" in saw, saw
    assert got.get("menus") == 1


def test_the_report_is_json_safe():
    """It is logged through json.dumps; a private-use codepoint must not break
    that."""
    got = _run({"tag": "body", "attrs": {}, "text": "", "kids": [
        _menu(["Low", "Extra"])]})
    json.dumps(got.get("saw") or [], ensure_ascii=False)


# ── The captured popover is real, and carries the anchor the fix relies on ────

def test_the_capture_carries_the_effort_trigger_test_id():
    """The scoping key. If Claude drops this test id the fix falls back to "newest
    menu", which is why that fallback exists — but the log will still say
    `scoped=`, so the change is visible."""
    html = POPOVER.read_text(encoding="utf-8", errors="replace")
    assert 'data-testid="effort-menu-trigger"' in html
    assert html.count("effort-menu-trigger") == 1, "the anchor must be unambiguous"


def test_the_captured_trigger_is_a_menuitem_not_a_span():
    """Two elements in the live popover match the text 'effort'; both are inner
    spans of this one row. The interactive element is the menuitem."""
    spec = spec_from_html(POPOVER.read_text(encoding="utf-8", errors="replace"))
    found = []

    def walk(n):
        if n["attrs"].get("data-testid") == "effort-menu-trigger":
            found.append(n)
        for k in n["kids"]:
            walk(k)

    walk(spec)
    assert len(found) == 1
    assert found[0]["tag"] == "div"
    assert found[0]["attrs"].get("role") == "menuitem"


def test_the_selected_model_row_is_the_one_marked_checked():
    """Sanity on the capture itself — it should show Opus 5 selected, matching the
    run's own log. A fixture that disagrees with the log is the wrong fixture."""
    spec = stamp_panel_geometry(
        spec_from_html(POPOVER.read_text(encoding="utf-8", errors="replace")))
    checked = []

    def text_of(n):
        return (n["text"] or "") + "".join(text_of(k) for k in n["kids"])

    def walk(n):
        if n["attrs"].get("aria-checked") == "true":
            checked.append(text_of(n))
        for k in n["kids"]:
            walk(k)

    walk(spec)
    assert any("Opus" in c for c in checked), checked
