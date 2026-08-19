"""Claude's Effort submenu: the gate that vetoed a submenu it could see.

⛔ THE REPORT (owner's e2e, 2026-08-17). The run set the model correctly and then:

    [setup_claude_dr] Step 1C: re-opened the model popover ✓
    [setup_claude_dr] Step 1C: marked the Effort row 'effortmax' (via testid)
    [WARN] Step 1C DIAG (submenu never mounted) — {"chain": [], "overlays": [
      {... "labels": ["Opus 5For complex tasks","EffortMax","More models"]},
      {"box": {"id":"_r_7k_","data":{"data-side":"inline-start"}}, "rows": 5,
       "labels": ["Low","Medium","HighDefault","Extra","Max"]}], "marked": false}
    [WARN] Step 1C WARN: the Effort row was pressed ... but no submenu mounted
    [WARN] [dom] p2 claude.select_effort_tier: missed via=none — wanted 'max'

⭐⭐ THE DIAGNOSTIC THAT SAYS "SUBMENU NEVER MOUNTED" CONTAINS THE SUBMENU. Five
rows, Low/Medium/HighDefault/Extra/Max, sitting in an overlay one line below the
verdict. The submenu was up. The gate could not see it, and Claude ran the whole
phase at whatever effort the model defaults to while telemetry said unconfirmed.

⭐⭐ WHY, and the log names it. The gate listed every short visible row in the
DOCUMENT, deduped, capped the list at 20, and looked for an effort word among
them. The rows it got were:

    visible short rows were ["new⇧⌘o","","projects","artifacts","scheduled",
                             "customize","projects","","","pinned"]

That is the SIDEBAR. Claude's submenu is a portalled popper appended at the END
of `<body>`, so it is last in document order — behind every sidebar entry and
every conversation title. The cap was reached before the walk ever arrived. A
larger cap would not have fixed it either: document order is the defect, and the
sink is what needed guarding, exactly as in the 2026-08-05 ChatGPT row wave.

⛔ THE SECOND HALF WAS DEAD ON ARRIVAL. The diagnostic rebuilt "what did we
press?" by re-reading the click marker — and `_sr_real_click` removes that marker
in a `finally`, by contract, on every path. So `"chain": []` and `"marked": false`
were printed on every failure this step has ever had, regardless of what was
pressed. The ancestry is now captured while the row is in hand.
"""
import json
import re

import pytest

import research
from _domshim import el, js_constant, run_js


def _src():
    with open("research.py", encoding="utf-8") as fh:
        return fh.read()


# ── The live page, rebuilt ───────────────────────────────────────────────────
#
# The six sidebar labels are the ones the failing run printed, verbatim. The
# conversation rows stand in for the titles that filled the rest of the cap; the
# run's log was truncated to ten entries, so their exact text is not recorded —
# their COUNT and their position ahead of the popper is what matters, and both
# are properties of the page, not of any one conversation.
SIDEBAR_LABELS = ["new⇧⌘o", "projects", "artifacts", "scheduled",
                  "customize", "pinned"]
LIVE_SUBMENU_LABELS = ["Low", "Medium", "HighDefault", "Extra", "Max"]
POPOVER_LABELS = ["Opus 5For complex tasks", "EffortMax", "More models"]


def _sidebar(n_convos=20):
    rows = [el("li", {"w": "180", "h": "28", "x": "0", "y": str(40 + i * 28)},
               text=t) for i, t in enumerate(SIDEBAR_LABELS)]
    rows += [el("li", {"w": "180", "h": "28", "x": "0", "y": str(300 + i * 28)},
                text=f"Chat {i}") for i in range(n_convos)]
    return el("nav", {"w": "200", "h": "900", "x": "0", "y": "0"}, kids=rows)


def _menu(labels, *, trigger=False, attrs=None, testids=False):
    rows = []
    if trigger:
        rows.append(el("div", {"role": "menuitem",
                               "data-testid": research._CLAUDE_EFFORT_TRIGGER_TESTID,
                               "w": "200", "h": "32", "x": "500", "y": "60"},
                       text="EffortMax"))
    ids = {"Low": "low", "Medium": "medium", "HighDefault": "high",
           "Extra": "xhigh", "Max": "max"}
    for i, t in enumerate(labels):
        a = {"role": "menuitemradio", "w": "200", "h": "32", "x": "500",
             "y": str(100 + i * 32)}
        if testids and t in ids:
            a["data-testid"] = f"effort-option-{ids[t]}"
        rows.append(el("button", a, text=t))
    box = {"w": "240", "h": "300", "x": "500", "y": "50"}
    box.update(attrs or {"role": "menu"})
    return el("div", box, kids=rows)


def _page(*overlays, convos=20):
    return el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"},
              kids=[_sidebar(convos), *overlays])


def _probe(spec, *, opt_testid="effort-option-max"):
    ret = run_js(spec, research._CLAUDE_EFFORT_SUBMENU_JS,
                 {"trigTestid": research._CLAUDE_EFFORT_TRIGGER_TESTID,
                  "optTestid": opt_testid}).get("ret") or {}
    return ret


def _verdict(spec, **kw):
    return research._claude_effort_submenu_verdict(_probe(spec, **kw))


LIVE_PAGE_KWARGS = dict()


def _live_page(**kw):
    """The 2026-08-17 page: sidebar, model popover (with the trigger), submenu."""
    return _page(_menu(POPOVER_LABELS, trigger=True),
                 _menu(LIVE_SUBMENU_LABELS, **kw))


# ── 1. The failure, reproduced against the code that had it ──────────────────

OLD_GATE_JS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
    const out = [];
    for (const el of document.querySelectorAll(
            '[role="menuitem"], [role="menuitemradio"], [role="option"], button, li')) {
        if (!el.getClientRects().length) continue;
        const t = norm(el.textContent);
        if (!t || t.length > 24) continue;
        if (out.indexOf(t) === -1) out.push(t);
    }
    return out.slice(0, 20);
}"""

OLD_GATE_WORDS = ("max", "max effort", "thinking", "low", "medium", "high", "extra")


def test_the_old_page_wide_gate_cannot_see_this_submenu():
    """⭐⭐ THE CONTROL, and the reason this fixture is trustworthy. The gate that
    shipped is reproduced verbatim here and run against the rebuilt page: it
    returns the sidebar and misses all five rungs, which is exactly what the run
    logged. Without this, the fix below would be a fix for a theory."""
    rows = run_js(_live_page(), OLD_GATE_JS).get("ret") or []
    assert not any(r in OLD_GATE_WORDS for r in rows), (
        "the fixture must reproduce the reported failure", rows)
    assert "projects" in rows and "artifacts" in rows, (
        "and it must fail the way the log says it failed — full of sidebar", rows)


def test_the_old_gate_was_beaten_by_document_order_not_by_the_menu():
    """⛔ Same page, no sidebar: the old gate suddenly works. So nothing about the
    submenu was ever wrong — it was queued behind the rest of the document. This
    is why a bigger cap would not have been a fix."""
    rows = run_js(_page(_menu(POPOVER_LABELS, trigger=True),
                        _menu(LIVE_SUBMENU_LABELS), convos=0),
                  OLD_GATE_JS).get("ret") or []
    assert any(r in OLD_GATE_WORDS for r in rows), rows


# ── 2. The scoped probe answers correctly on the same page ───────────────────

def test_the_scoped_probe_sees_the_submenu_the_old_gate_missed():
    """⭐⭐ THE FIX, on the page that broke."""
    assert _verdict(_live_page()) == "open"


@pytest.mark.parametrize("convos", [0, 20, 200])
def test_no_amount_of_sidebar_can_crowd_the_answer_out(convos):
    """The regression pin. The old gate's answer was a function of how many rows
    happened to precede the popper; this one asks each overlay separately, so the
    sidebar is not an input at all."""
    spec = _page(_menu(POPOVER_LABELS, trigger=True),
                 _menu(LIVE_SUBMENU_LABELS), convos=convos)
    assert research._claude_effort_submenu_verdict(_probe(spec)) == "open"


@pytest.mark.parametrize("attrs", [
    {"role": "menu"},
    {"data-radix-menu-content": ""},
    {"data-radix-popper-content-wrapper": ""},
    {"data-side": "inline-start", "data-radix-menu-content": ""},
])
def test_the_submenu_is_recognised_however_the_library_labels_its_box(attrs):
    """The captured box carried `data-side: inline-start` and an id, and the
    overlay selector has to survive a component-library rename — so all four
    container shapes this file already searches must answer the same."""
    assert _verdict(_live_page(attrs=attrs)) == "open"


def test_the_rungs_are_counted_with_the_default_suffix_included():
    """'HighDefault' is a real captured label: the default rung carries a suffix.
    A vocabulary of bare words would score this menu one rung lower."""
    got = _probe(_live_page())
    sub = [o for o in got["overlays"] if not o["trigger"]]
    assert sub and sub[0]["rungs"] == 5, got
    assert "highdefault" in sub[0]["labels"], got


def test_the_icon_ligatures_do_not_hide_a_rung():
    """The selected row carries private-use glyphs — the defect that cost nine
    runs in ten before 2026-08-06. Counting rungs has to strip them too."""
    labels = ["Low", "Medium", "HighDefault", "Extra", "Max"]
    got = _probe(_page(_menu(POPOVER_LABELS, trigger=True), _menu(labels)))
    sub = [o for o in got["overlays"] if not o["trigger"]]
    assert sub and sub[0]["rungs"] == 5, got


# ── 3. The parent popover is never mistaken for the submenu ──────────────────

def test_the_model_popover_alone_is_closed_not_open():
    """⛔ The popover shows the current tier as its own 'EffortMax' row. If that
    counted, the gate would wave through a submenu that never opened — the
    reported failure, inverted, and far worse: the picker would then press
    inside the popover."""
    assert _verdict(_page(_menu(POPOVER_LABELS, trigger=True))) == "closed"


def test_an_empty_page_is_closed():
    assert _verdict(_page()) == "closed"


def test_the_popover_is_excluded_by_its_trigger_not_by_its_labels():
    """⛔ A build that hangs the option's own test id on the popover's Effort row
    — plausible, since that row displays the selected tier — must still not read
    as an open submenu. The exclusion is structural on purpose."""
    popover = _menu(POPOVER_LABELS, trigger=True)
    popover["kids"][0]["attrs"]["data-testid"] = research._CLAUDE_EFFORT_TRIGGER_TESTID
    popover["kids"].append(el("button", {"role": "menuitemradio",
                                         "data-testid": "effort-option-max",
                                         "w": "200", "h": "32", "x": "500",
                                         "y": "200"}, text="Max"))
    assert _verdict(_page(popover)) == "closed"


def test_a_hidden_submenu_is_not_open():
    """It is `getClientRects()`, not presence in the DOM: a component library
    keeps a collapsed menu mounted."""
    sub = _menu(LIVE_SUBMENU_LABELS)
    sub["attrs"]["hidden"] = ""
    assert _verdict(_page(_menu(POPOVER_LABELS, trigger=True), sub)) == "closed"


# ── 4. The verdict function, on readings ─────────────────────────────────────

def test_the_option_test_id_alone_is_enough():
    """An id names the row directly. A relabelled UI whose rungs read in another
    language still resolves through it."""
    assert research._claude_effort_submenu_verdict(
        {"overlays": [{"trigger": False, "option": True, "rungs": 0,
                       "labels": ["niedrig", "hoch"]}]}) == "open"


def test_one_rung_alone_is_not_a_menu():
    """⛔ TWO, not one. A single 'max' in a stray overlay — a tooltip, a toast —
    is not evidence that a five-row radio group mounted."""
    assert research._claude_effort_submenu_verdict(
        {"overlays": [{"trigger": False, "option": False, "rungs": 1,
                       "labels": ["max"]}]}) == "maybe"


def test_two_rungs_are():
    assert research._claude_effort_submenu_verdict(
        {"overlays": [{"trigger": False, "option": False, "rungs": 2,
                       "labels": ["max", "low"]}]}) == "open"


def test_an_unrecognised_overlay_is_maybe_not_closed():
    """⭐ 'maybe' exists so the gate cannot veto a picker that verifies its own
    work. Something other than the popover is up and nothing in it was
    recognised: that describes the page, it does not settle the run."""
    assert research._claude_effort_submenu_verdict(
        {"overlays": [{"trigger": True, "option": False, "rungs": 0},
                      {"trigger": False, "option": False, "rungs": 0}]}) == "maybe"


@pytest.mark.parametrize("probe", [None, {}, {"overlays": None},
                                   {"overlays": ["junk", None, 7]}])
def test_a_missing_or_malformed_reading_is_closed_never_a_crash(probe):
    """The probe runs inside a try/except that yields {} on a navigation, and this
    is the one step that must never raise: effort is a quality knob and the run
    has to continue."""
    assert research._claude_effort_submenu_verdict(probe) == "closed"


def test_a_non_numeric_rung_count_is_not_truthy_by_accident():
    assert research._claude_effort_submenu_verdict(
        {"overlays": [{"trigger": False, "option": False, "rungs": "lots"}]}
    ) == "maybe"


# ── 5. The consumer. Extracting a helper is not testing it. ──────────────────

def _gate_region(src):
    """Step 1C's submenu gate. Anchored on the state initialiser, which is unique."""
    at = src.index('_eff_state, _eff_opened = "closed", False')
    end = src.index("# ── Step 1C': set Effort = Max", at)
    return src[at:end]


def test_the_gate_polls_the_scoped_probe():
    region = _gate_region(_src())
    assert "_CLAUDE_EFFORT_SUBMENU_JS" in region
    assert "_claude_effort_submenu_verdict(" in region


def test_the_page_wide_scan_is_gone_from_the_gate():
    """⛔ The exact shape that shipped the bug: a document-order walk with a cap."""
    region = _gate_region(_src())
    assert "out.slice(0, 20)" not in region
    assert '"max effort", "thinking"' not in region


def test_the_gate_keeps_polling_until_the_submenu_is_open():
    """A 'maybe' on the first look must not end the wait — a submenu that mounts
    on the fourth poll is the ordinary case, and settling for 'maybe' would skip
    the Thinking probe on a page that was about to be fine."""
    region = _gate_region(_src())
    assert 'if _eff_state == "open":\n                            break' in region


def test_a_maybe_still_reaches_the_row_picker():
    """⭐ The gate must not be able to overrule a picker that checks its own work.
    Step 1C' is scoped to the same overlay and verifies the press before claiming
    anything, so attempting it converts a blind veto into a named diagnosis."""
    src = _src()
    region = _gate_region(src)
    assert 'if _eff_state != "closed":' in region, (
        "the picker must run on 'maybe' too")
    assert "if _eff_opened:\n                    await asyncio.sleep" not in region


def test_the_picker_is_handed_the_policy_tier_by_the_call_site():
    """⛔ `family-only-models`: the tier reaches the page script as a parameter.
    A call site that stopped passing it would leave `want` empty and the text
    fallback matching nothing, on the only layout where it runs."""
    src = _src()
    at = src.index('"value": "claude-effort-option"')
    args = src[at - 400:at]
    assert '"word": str(_claude_effort or "").lower()' in args, args


def test_the_page_wide_thinking_search_still_needs_a_confirmed_submenu():
    """⛔ The counterweight. The Thinking probe is NOT scoped — it searches the
    whole document for a switch and clicks it. Widening the effort attempt to
    'maybe' must not also widen an unscoped click."""
    src = _src()
    at = src.index("_think_probed = bool(")
    assert "_eff_opened" in src[at:at + 120], src[at:at + 120]
    assert "_eff_state" not in src[at:at + 120]


def test_the_diagnostic_no_longer_reads_a_marker_that_is_already_removed():
    """⛔⛔ THE DEAD HALF. `_sr_real_click` removes the click marker in a `finally`
    — always, by contract — so the diagnostic's `querySelector` on that attribute
    could never resolve. It printed `"chain": [], "marked": false` on every
    failure this step has ever had, including the run where the press had landed
    on exactly the right row."""
    region = _gate_region(_src())
    at = region.index("Step 1C DIAG")
    diag = region[:at]
    assert "querySelector('[' + P.attr + ']')" not in diag
    assert 'pressed_chain' in region
    assert '_eff_mark.get("chain")' in region


def test_the_press_helper_still_removes_the_marker():
    """The premise of the test above, pinned where it lives. If this ever stops
    being true the diagnostic could go back to re-reading the page — but nothing
    would say so, and the old version looked correct for months."""
    src = _src()
    at = src.index("async def _sr_real_click(")
    body = src[at:src.index("\ndef _p1_tier_mission(", at)]
    assert "finally:" in body
    assert "_SR_UNMARK_JS" in body


def test_the_marker_pass_captures_the_ancestry_while_it_holds_the_row():
    """Where the chain comes from now: the marking JS, which has the element."""
    src = _src()
    at = src.index('"value": "claude-effort",')
    mark = src[max(0, at - 6000):at]
    assert "chain: chain" in mark
    assert "el.parentElement" in mark


def test_the_diag_still_refuses_to_copy_the_users_conversations():
    """⛔ STRUCTURE ONLY. The sidebar and the transcript are the user's own text,
    and a diagnostic has no business putting them in a log that a support bundle
    may one day carry."""
    region = _gate_region(_src())
    at = region.index("Step 1C DIAG")
    diag = region[:at]
    assert "outerHTML" not in diag
    assert "t.length <= 28" in diag, "labels stay short-control-sized"


# ── 6. The picker searches every candidate, and takes its tier from policy ───

def _pick_js():
    from _domshim import evaluate_js
    return evaluate_js(research.setup_claude_dr, contains="isWanted")


def _pick(spec, word="max", opt=""):
    return (run_js(spec, _pick_js(),
                   {"trigTestid": research._CLAUDE_EFFORT_TRIGGER_TESTID,
                    "optTestid": opt, "word": word,
                    "attr": research._SR_CLICK_MARK,
                    "value": "claude-effort-option"}).get("ret") or {})


def test_the_picker_searches_past_a_decoy_overlay():
    """⭐ `find` chose ONE menu and, if the row was not in it, reported the row
    missing from a page that was showing it — the same wrong-sink shape as the
    gate. Every candidate is searched now."""
    decoy = _menu(["Copy", "Delete"], attrs={"role": "menu"})
    got = _pick(_page(_menu(POPOVER_LABELS, trigger=True), decoy,
                      _menu(LIVE_SUBMENU_LABELS)))
    assert got.get("set") == "marked", got
    assert got.get("picked") == "max", got


def test_the_picker_still_refuses_the_popovers_own_effort_row():
    """The guard that must survive the widening: the trigger's menu is excluded
    however many candidates are searched."""
    got = _pick(_page(_menu(POPOVER_LABELS, trigger=True)))
    assert not got.get("set"), got


def test_the_popovers_own_tier_display_is_never_the_row_pressed():
    """⛔ The parent popover SHOWS the selected tier — the live capture's row read
    'EffortMax' — and the row search includes `div`, so the element rendering that
    value is a candidate the moment the trigger's menu stops being excluded.
    Pressing it re-opens the submenu instead of choosing anything, and the caller
    would then report the tier as set."""
    popover = _menu(POPOVER_LABELS, trigger=True)
    popover["kids"][0]["kids"] = [
        el("div", {"w": "40", "h": "20", "x": "660", "y": "60"}, text="Max")]
    popover["kids"][0]["text"] = "Effort"
    got = _pick(_page(popover))
    assert not got.get("set"), got


def test_with_no_menu_at_all_only_a_test_id_may_resolve():
    """The last-resort pool is the whole document, and a test id is globally
    unique there. Safe."""
    page = _page(el("div", {"role": "menuitemradio",
                            "data-testid": "effort-option-max",
                            "w": "120", "h": "24", "x": "100", "y": "400"},
                    text="Max"))
    got = _pick(page, opt="effort-option-max")
    assert got.get("via") == "testid", got


def test_with_no_menu_at_all_a_bare_max_is_never_pressed():
    """⛔ And matching page-wide TEXT there is the decoy press this file has
    already paid for: Claude's own reply renders list items reading exactly
    'Max', and document order puts the reply ahead of the composer."""
    decoy = el("li", {"aria-label": "DECOY-in-the-assistants-reply", "w": "120",
                      "h": "24", "x": "100", "y": "400"}, text="Max")
    got = _pick(_page(decoy))
    assert not got.get("set"), got


def test_the_older_max_effort_label_still_resolves():
    """A layout that spells the row 'Max effort' predates the ids and is the only
    thing the text fallback exists for."""
    got = _pick(_page(_menu(POPOVER_LABELS, trigger=True),
                      _menu(["Low", "Max effort"])))
    assert got.get("set") == "marked", got


@pytest.mark.parametrize("word,label", [("max", "Max"), ("extra", "Extra"),
                                        ("medium", "Medium")])
def test_the_picker_takes_the_tier_from_policy_not_from_a_literal(word, label):
    """⛔ `family-only-models` is the standing rule and this path broke it: the
    text search compared against a hardcoded 'max' while the test id beside it
    was derived from policy. Ask for another tier and the two halves of one
    search disagreed — on the older layout, which is the only place the text
    half runs."""
    got = _pick(_page(_menu(POPOVER_LABELS, trigger=True),
                      _menu(LIVE_SUBMENU_LABELS)), word=word)
    assert got.get("set") == "marked", (word, got)
    assert got.get("picked") == label.lower(), (word, got)


def test_the_default_rungs_suffix_does_not_hide_it_from_the_picker():
    """'High' is rendered 'HighDefault'. Exact equality alone cannot select the
    default tier at all."""
    got = _pick(_page(_menu(POPOVER_LABELS, trigger=True),
                      _menu(LIVE_SUBMENU_LABELS)), word="high")
    assert got.get("set") == "marked", got
    assert got.get("picked") == "highdefault", got


def test_an_empty_policy_word_selects_nothing_rather_than_anything():
    """⛔ With no tier asked for, the text fallback must match NO row.

    ⚠ The icon-only row is what makes this test real, and its first draft did not
    have one: every label in the submenu is non-empty, so an unguarded `t === ''`
    matched nothing and the assertion passed against code with no guard at all
    (mutation E21). A menu row rendered as a single glyph normalises to the empty
    string, and that is the row an empty `want` would press."""
    got = _pick(_page(_menu(POPOVER_LABELS, trigger=True),
                      _menu(["", *LIVE_SUBMENU_LABELS])), word="")
    assert not got.get("set"), got


def test_the_option_test_id_still_outranks_the_text():
    got = _pick(_page(_menu(POPOVER_LABELS, trigger=True),
                      _menu(LIVE_SUBMENU_LABELS, testids=True)),
                word="max", opt="effort-option-max")
    assert got.get("via") == "testid", got


def test_the_already_selected_report_names_the_policy_tier():
    """It used to read 'max (already)' from a literal, on a run that had asked
    for something else."""
    sub = _menu(LIVE_SUBMENU_LABELS)
    for row in sub["kids"]:
        if row["text"] == "Extra":
            row["attrs"]["aria-checked"] = "true"
    got = _pick(_page(_menu(POPOVER_LABELS, trigger=True), sub), word="extra")
    assert got.get("set") == "extra (already)", got


# ── 7. The read-back has to be able to see what the picker pressed ───────────

def _checked(labels, word, *, checked_label=None, opt=""):
    rows = []
    for i, t in enumerate(labels):
        a = {"role": "menuitemradio", "w": "200", "h": "32", "x": "500",
             "y": str(100 + i * 32)}
        if t == checked_label:
            a["aria-checked"] = "true"
        rows.append(el("button", a, text=t))
    spec = el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"},
              kids=[el("div", {"role": "menu", "w": "240", "h": "300",
                               "x": "500", "y": "50"}, kids=rows)])
    return (run_js(spec, js_constant(research, "_CLAUDE_EFFORT_CHECKED_JS"),
                   {"optTestid": opt, "word": word}).get("ret") or {})


def test_the_read_back_sees_the_default_rung_it_just_pressed():
    """⛔ A verification that cannot read the row the picker pressed is worse than
    none: it reports a correct press as a failure and the run downgrades itself."""
    got = _checked(LIVE_SUBMENU_LABELS, "high", checked_label="HighDefault")
    assert got.get("found") and got.get("checked"), got


def test_the_read_back_still_says_no_when_the_row_is_unchecked():
    got = _checked(LIVE_SUBMENU_LABELS, "high", checked_label="Max")
    assert got.get("found") and not got.get("checked"), got


def test_the_read_back_matches_no_row_when_no_tier_is_asked_for():
    """⛔ The icon-only row is the point. With no tier asked for, an unguarded
    comparison equals the empty label of a row that renders as a single glyph —
    and the read-back would report a tier confirmed off whichever one came first.
    """
    got = _checked(["", *LIVE_SUBMENU_LABELS], "", checked_label="Max")
    assert not got.get("found"), got


def test_the_call_site_hands_the_read_back_the_policy_tier():
    """The word has to arrive from policy at BOTH ends: the picker chooses the
    row and this reads it back, and a mismatch would confirm the wrong rung."""
    src = _src()
    at = src.index("_CLAUDE_EFFORT_CHECKED_JS,")
    assert "_claude_effort" in src[at:at + 400]


# ── 8. The log the next run will be read from ────────────────────────────────

def test_the_diag_headline_reports_the_state_it_actually_reached():
    """It said "submenu never mounted" for both 'closed' and everything else. The
    owner read that line and believed the submenu had not opened; it had."""
    region = _gate_region(_src())
    assert "submenu never mounted" not in region
    assert "Step 1C DIAG (submenu {_eff_state})" in region


def test_the_closed_warning_reports_overlays_rather_than_sidebar_rows():
    """The old WARN printed the first ten short rows on the page, which is how a
    log full of "projects, artifacts, scheduled" came to be the evidence for a
    menu verdict."""
    region = _gate_region(_src())
    assert "visible short rows were" not in region
    assert "visible overlays were" in region


def test_the_overlay_report_is_json_safe():
    """The labels can carry private-use glyphs and any language; the WARN dumps
    them into a log line."""
    got = _probe(_live_page())
    assert json.loads(json.dumps(got, ensure_ascii=False)) == got


def test_the_gate_states_are_the_three_the_verdict_can_return():
    """A fourth string in the consumer would be a branch nothing can reach."""
    region = _gate_region(_src())
    states = set(re.findall(r'_eff_state (?:==|!=) "([a-z]+)"', region))
    assert states <= {"open", "maybe", "closed"}, states
