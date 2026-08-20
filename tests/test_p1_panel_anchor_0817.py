"""ChatGPT P1: the structural anchor that could never fire on one signal.

⛔ THE REPORT (owner, twice — 2026-08-16 and again after the 2026-08-17 e2e):
"P1 did not click the sources line and open the source panel for rich narration
and streaming data into the raw activity panel." The phase ran ~11 minutes with
nothing in the activity panel, and the log said the same thing fourteen times:

    [Phase1] panel DOM miss #14 (elapsed=492s, walked_hits=0) — scanned 903 nodes
      across 1 root(s) in 2 context(s) and nothing matched

⭐⭐ THE STRIP WAS THERE THE WHOLE TIME, and the step's own snapshot logged it.
Two live captures, both with the last user bubble ending at y=202:

    p1-miss2  {"t":"Structured the research brief","y":242,"btn":true,
               "anim":false,"ti":"cot-v5-pinned-row"}
    p1-miss5  {"t":"Developed the security scope","y":306,"cl":"block",
               "btn":true,"anim":true,"animKid":true}

⭐⭐ AND THE ARITHMETIC IS THE BUG. PASS 0 scored a candidate

    (inter ? 3 : 0) + (anim ? 3 : 0) + (wordy ? 2 : 0) - (top - lub) / 1000

and required `>= 3`. Three is exactly the weight of ONE signal, and the distance
penalty is ALWAYS subtracted — so a candidate carrying a single signal can never
clear the bar. The two captured strips scored **2.960** and **2.896**. The only
PASS 0 that ever fired in the corpus did so on `label="Searching the web"`, i.e.
because its wording matched (+2). An anchor built to survive rewording had been
decided by wording all along, silently, for as long as it has existed.

⭐ Two hooks the captures also handed over, both stronger than the shimmer:
  * `data-testid="cot-v5-pinned-row"` — ChatGPT's own name for this row.
  * `SECTION[data-testid="conversation-turn-2"]` — the containing turn, which is
    what stops a lone shimmer elsewhere from qualifying. The same capture shows
    the composer's model chip ("Pro", 400px lower) reporting `animKid:true`.
"""
import pytest

import research
from _domshim import el, js_constant, run_js


def _panel_js():
    return js_constant(research._open_chatgpt_activity_panel, "JS")


# ── The live page, rebuilt from the captures ─────────────────────────────────
#
# Geometry is the measured geometry: the user bubble ends at y=202, the strip
# sits at y=242 (p1-miss2) or y=306 (p1-miss5), the composer disclaimer at y=370
# and the model chip at y=724.
LUB_BOTTOM = 202


def _user_bubble():
    return el("div", {"data-message-author-role": "user", "w": "600", "h": "60",
                      "x": "300", "y": str(LUB_BOTTOM - 60)},
              text="Compare the three models")


def _model_chip():
    """The composer's model chip. The capture reports `animKid:true` on it, which
    is why a lone shimmer is not sufficient evidence on its own."""
    return el("div", {"w": "40", "h": "24", "x": "300", "y": "724"},
              kids=[el("span", {"anim": "pulse", "w": "40", "h": "24",
                                "x": "300", "y": "724"}, text="Pro")])


def _disclaimer():
    return el("div", {"class": "mt-auto", "w": "400", "h": "20", "x": "300",
                      "y": "370"},
              text="ChatGPT can make mistakes. Check important info.")


def _strip(text, *, y, named=True, anim_on="kid", in_turn=True, button=True,
           turn_y=None):
    """One strip row, as captured: a narrow chain whose text sits on the inner
    element and whose shimmer sits on a span below that."""
    inner_attrs = {"w": "300", "h": "24", "x": "300", "y": str(y)}
    if named:
        inner_attrs["data-testid"] = "cot-v5-pinned-row-content"
    if anim_on == "self":
        inner_attrs["anim"] = "shimmer"
    if anim_on == "kid":
        inner = el("div", inner_attrs,
                   kids=[el("span", {"anim": "shimmer", "w": "300", "h": "24",
                                     "x": "300", "y": str(y)}, text=text)])
    elif anim_on == "overlay":
        # The shimmer on a TEXT-LESS overlay: a gradient span layered over the
        # row. Nothing that carries the shimmer carries any text, so no element
        # can qualify on its own — only asking the subtree can find it.
        inner = el("div", inner_attrs, text=text,
                   kids=[el("span", {"anim": "shimmer", "w": "300", "h": "24",
                                     "x": "300", "y": str(y)})])
    else:
        inner = el("div", inner_attrs, text=text)
    row_attrs = {"w": "300", "h": "24", "x": "300", "y": str(y)}
    if named:
        row_attrs["data-testid"] = "cot-v5-pinned-row"
    if button:
        row_attrs["role"] = "button"
    node = el("div", row_attrs, kids=[inner])
    if in_turn:
        # ⭐ 2026-08-20 — THE TURN'S POSITION IS ITS OWN KNOB NOW. It used to be
        # pinned to the row's own y, which made the wrapper invisible to any test
        # about distance: every row sat exactly at the top of its turn. The band
        # is measured from the turn (the row and its container scroll together,
        # the viewport does not), so a fixture that cannot move them apart cannot
        # test the band at all.
        node = el("section", {"data-testid": "conversation-turn-2", "w": "600",
                              "h": "1800", "x": "300",
                              "y": str(y if turn_y is None else turn_y)},
                  kids=[node])
    return node


def _page(*rows):
    return el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"},
              kids=[el("main", {"w": "1440", "h": "900", "x": "0", "y": "0"},
                       kids=[_user_bubble(), *rows, _disclaimer(),
                             _model_chip()])])


def _open(spec, skip_structural=False):
    out = run_js(spec, _panel_js(), skip_structural)
    return out.get("ret") or {}


# ── 1. The reported failure, reproduced and fixed ────────────────────────────

def test_the_capture_that_scored_2_896_is_now_clicked():
    """⭐⭐ p1-miss5: a shimmering line inside the assistant's turn, whose wording
    ("Developed the security scope") matches none of the verb, count, ellipsis,
    status or completed patterns. This is the run the owner watched go blind."""
    got = _open(_page(_strip("Developed the security scope", y=306)))
    assert got.get("anchor") == "structural", got
    assert "Developed the security scope" in (got.get("label") or ""), got
    assert got.get("clicked"), got


def test_the_capture_that_scored_2_960_is_now_clicked():
    """p1-miss2: no shimmer measurable on the row, but ChatGPT's own test id."""
    got = _open(_page(_strip("Structured the research brief", y=242,
                             anim_on="none")))
    assert got.get("anchor") == "structural", got
    assert "Structured the research brief" in (got.get("label") or ""), got


@pytest.mark.parametrize("text", [
    "Structured the research brief",
    "Developed the security scope",
    "Searched 24 websites",
    "Reviewed the vendor documentation",
])
def test_the_anchor_no_longer_depends_on_the_wording(text):
    """⭐ The whole point of a structural anchor. Three of these four wordings
    appeared in ONE run; none matches any wording pattern in the file."""
    got = _open(_page(_strip(text, y=306)))
    assert got.get("anchor") == "structural", (text, got)


def test_the_shimmer_is_found_on_an_inner_span():
    """⭐⭐ The measured difference between the two captures: `anim:false` on the
    row, `animKid:true` on its subtree. Reading only the element and its parent
    is how the shimmer was missed."""
    got = _open(_page(_strip("Developed the security scope", y=306,
                             named=False, button=False, anim_on="kid")))
    assert got.get("anchor") == "structural", got


def test_the_shimmer_is_found_when_it_carries_no_text_of_its_own():
    """⭐ THE CASE THE SUBTREE SCAN EXISTS FOR, and the first draft of this file
    did not have it: when the shimmer sits on a span that HAS the text, that span
    is a perfectly good candidate by itself and the scan changes nothing (mutation
    P8 survived on exactly that). A gradient overlay layered over the row carries
    no text, so it is filtered out as a candidate — and then only asking the
    subtree can tell that this row is the live one."""
    got = _open(_page(_strip("Developed the security scope", y=306,
                             named=False, button=False, anim_on="overlay")))
    assert got.get("anchor") == "structural", got
    assert "Developed the security scope" in (got.get("label") or ""), got


def test_the_shimmer_on_the_element_itself_still_counts():
    got = _open(_page(_strip("Developed the security scope", y=306,
                             named=False, button=False, anim_on="self")))
    assert got.get("anchor") == "structural", got


# ── 2. What must NOT be clicked ──────────────────────────────────────────────

def test_a_shimmer_outside_the_assistants_turn_is_not_the_strip():
    """⛔ The composer's model chip reported an animated descendant in the same
    capture. With the strip absent it is the only shimmer on the page, and a
    gate that accepted a lone shimmer would press it — closing the model picker
    over the composer, and reporting the panel opened."""
    got = _open(_page())
    assert got.get("anchor") != "structural", got


def test_the_strip_wins_over_the_model_chip_when_both_are_present():
    got = _open(_page(_strip("Developed the security scope", y=306)))
    assert "Pro" not in (got.get("label") or ""), got


def test_a_plain_clickable_row_near_the_message_is_not_enough():
    """⛔ The counterweight to loosening the gate. `inter` alone blesses half the
    thread — every button in the turn's toolbar sits in this band."""
    row = el("section", {"data-testid": "conversation-turn-2", "w": "600",
                         "h": "40", "x": "300", "y": "250"},
             kids=[el("button", {"w": "80", "h": "24", "x": "300", "y": "250"},
                      text="Copy")])
    got = _open(_page(row))
    assert got.get("anchor") != "structural", got


def test_a_clickable_row_whose_text_names_a_known_state_is_still_pressed():
    """The original two-signal rule, preserved — but 2026-08-18 moved WHICH pass
    gets there.

    ⭐ `inter && wordy` is now structurally unreachable as a deciding arm, and
    that is correct rather than broken: "wordy" is exactly what the global walk
    matches on, so any row this arm would qualify is a row the pass with 13
    recorded successes already handles. The arm stays as a last resort for the
    case where the global walk is somehow blind. What must not change is that
    this shape still gets PRESSED — so that is what this pins now, instead of
    the anchor that used to report it."""
    row = el("section", {"data-testid": "conversation-turn-2", "w": "600",
                         "h": "40", "x": "300", "y": "250"},
             kids=[el("div", {"role": "button", "w": "300", "h": "24",
                              "x": "300", "y": "250"},
                      text="Searching the web")])
    got = _open(_page(row))
    assert got.get("clicked") is True, got
    assert "Searching the web" in (got.get("label") or ""), got


def test_the_composer_subtree_is_still_excluded():
    """A shimmering line inside the composer is the composer's own affordance."""
    comp = el("form", {"data-testid": "composer-root", "w": "600", "h": "80",
                       "x": "300", "y": "250"},
              kids=[el("div", {"data-testid": "cot-v5-pinned-row", "role": "button",
                               "anim": "shimmer", "w": "300", "h": "24",
                               "x": "300", "y": "250"}, text="Thinking...")])
    got = _open(_page(comp))
    assert got.get("anchor") != "structural", got


def test_skip_structural_still_skips_it():
    """⛔ The escape hatch the caller uses after two failed attempts: if PASS 0
    keeps picking something whose click never verifies, it must be able to stand
    down so the wording passes and the frame walk get their turn."""
    got = _open(_page(_strip("Developed the security scope", y=306)),
                skip_structural=True)
    assert got.get("anchor") != "structural", got


def test_a_strip_far_below_the_message_is_out_of_band():
    """The band is what makes "the first row of the turn" mean anything.

    2026-08-20: measured from the TURN, not from the user bubble. A shimmering
    row 1400px below the top of its own turn is somewhere inside the streamed
    report, not the pinned row at the top of it — and unlike a viewport
    measurement, that distance does not change when the page scrolls."""
    got = _open(el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"}, kids=[
        el("main", {"w": "1440", "h": "900", "x": "0", "y": "0"}, kids=[
            _user_bubble(),
            # One turn, carrying its report — so the container itself is filtered
            # by the 200-char leaf cap exactly as a live turn is, and the only
            # candidate left is the row 1400px down inside the report.
            el("section", {"data-testid": "conversation-turn-2", "w": "600",
                           "h": "1800", "x": "300", "y": "200"},
               text=("Report body, which on a live page runs to pages. " * 8),
               kids=[el("div", {"anim": "shimmer", "role": "button", "w": "300",
                                "h": "24", "x": "300", "y": "1600"},
                        text="Developed the security scope")]),
        ])]))
    assert got.get("anchor") != "structural", got


def test_the_stale_strip_from_an_earlier_turn_does_not_win():
    """A completed turn leaves its old strip on the page; the live one belongs to
    the newest turn.

    ⛔ 2026-08-20 — THE OLD FIXTURE COULD NOT HAPPEN. It put two assistant turns
    back to back with no user message between them, which is the one arrangement
    where "nearest to the bubble" and "inside the newest turn" disagree — so it
    was measuring the fixture's own impossibility. A real page interleaves them,
    and then both readings pick the same row, which is what this asserts."""
    got = _open(el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"}, kids=[
        el("main", {"w": "1440", "h": "900", "x": "0", "y": "0"}, kids=[
            # the previous exchange, still on the page above
            el("div", {"data-message-author-role": "user", "w": "600", "h": "60",
                       "x": "300", "y": "-400"}, text="an earlier question"),
            _strip("Searched 24 websites", y=-340),
            # the newest exchange
            _user_bubble(),
            _strip("Developed the security scope", y=242),
            _disclaimer(), _model_chip(),
        ])]))
    assert "Developed the security scope" in (got.get("label") or ""), got


def test_a_qualifying_row_behind_a_higher_scoring_reject_is_still_reached():
    """⛔ The list used to be ranked and only `[0]` inspected, so an unqualified
    top scorer buried every qualifier beneath it.

    The decoy here outscores the real strip on purpose: shimmer + wording is 5,
    while a bare shimmer inside the turn is 3. But the decoy sits outside every
    conversation turn — a page-chrome banner — so it must not be pressed, and the
    strip below it must still be found."""
    # ⛔ The decoy used to read "Searching for updates..." — which is a WORDING
    # match, so after 2026-08-18 demoted PASS 0 the global walk claimed it and
    # this fixture silently stopped testing PASS 0's ranking. The decoy has to be
    # invisible to every wording matcher for the structural ranking to be what
    # answers here.
    decoy = el("div", {"anim": "shimmer", "w": "300", "h": "24", "x": "300",
                       "y": "210"}, text="Update available")
    strip = _strip("Developed the security scope", y=306, named=False,
                   button=False)
    got = _open(_page(decoy, strip))
    assert got.get("anchor") == "structural", got
    assert "Developed the security scope" in (got.get("label") or ""), got


def test_the_named_row_outranks_a_bare_shimmer():
    got = _open(_page(_strip("Developed the security scope", y=306),
                      _strip("Some other animated line", y=250, named=False,
                             button=False)))
    assert "Developed the security scope" in (got.get("label") or ""), got


def test_the_pick_reports_why_it_qualified():
    """The next drift has to be diagnosable from the log alone — which signal
    carried the pick is exactly what no previous miss line could say."""
    got = _open(_page(_strip("Developed the security scope", y=306)))
    assert "named" in (got.get("why") or ""), got
    assert "turn" in (got.get("why") or ""), got


# ── 4. The gate itself, pinned ───────────────────────────────────────────────

def _pass0(src):
    at = src.index("// #913 PASS 0 — STRUCTURAL anchor")
    return src[at:src.index("// 2026-04-28: PASS 1", at)]


def _code(region):
    """The region with its `//` comment lines dropped.

    ⚠ Not cosmetic: this block's comments quote the defect verbatim ("`score >=
    3`, and 3 is exactly the weight of ONE signal"), so a naive substring check
    on the raw text passes on the strength of the note explaining why the code is
    gone. The first draft of the test below did exactly that."""
    return "\n".join(ln for ln in region.splitlines()
                     if not ln.strip().startswith("//"))


def _src():
    with open("research.py", encoding="utf-8") as fh:
        return fh.read()


def test_the_threshold_that_one_signal_could_never_clear_is_gone():
    """⛔⛔ `score >= 3` against a scale where one signal IS 3, minus a penalty
    that is always subtracted. Not a tuning problem — an unreachable branch."""
    pass0 = _code(_pass0(_src()))
    assert "score >= 3" not in pass0
    assert "const qualifies = (h) =>" in pass0


def test_the_distance_penalty_only_ranks():
    """It stays in the score — nearest-wins is right — but it must not be able
    to decide whether anything qualifies at all."""
    pass0 = _code(_pass0(_src()))
    # 2026-08-20: the same quantity, now named `offTop` (`r.top - lub`) so the
    # census can report which gate rejected a row.
    assert "- offTop / 1000" in pass0
    assert "const offTop = r.top - lub;" in pass0
    qual = pass0[pass0.index("const qualifies"):pass0.index("let ranked")]
    assert "r.top" not in qual and "lub" not in qual and "offTop" not in qual, qual


def test_every_qualifying_row_is_considered_not_just_the_top_scorer():
    pass0 = _code(_pass0(_src()))
    assert "structural.filter(qualifies)" in pass0


def test_the_captured_test_id_is_matched_version_free():
    """`cot-v5-pinned-row` will become `cot-v6-` the next time OpenAI renames a
    component. The row is the same row, so the digit stays out of the selector."""
    pass0 = _code(_pass0(_src()))
    assert 'data-testid^="cot-v"' in pass0
    assert "cot-v5" not in pass0, pass0


# ── the reorder's blast radius, 2026-08-18 ───────────────────────────────────

def test_the_global_walk_will_not_press_a_shimmering_banner_outside_the_thread():
    """⛔⛔ The composer and the page chrome were excluded by PASS 0 ONLY. While
    PASS 0 answered first that was invisible; demoting it to a last resort made
    the global walk the first pass to see the whole document, and it pressed a
    "Searching for updates..." banner sitting above every conversation turn.

    Found by an existing PASS 0 test whose fixture the reorder quietly handed to
    a different pass — which is the reason a suite gets re-run rather than
    reasoned about."""
    # ⛔ Placed BELOW the strip on purpose. Equal-scoring hits are broken by
    # "bottom-most wins", so a banner above the thread loses that tiebreak on its
    # own and the fixture proves nothing — the first version of this test passed
    # with the exclusion deleted. A toast at the foot of the window is both the
    # realistic shape and the one where only the exclusion can save the strip.
    banner = el("header", {"w": "1440", "h": "40", "x": "0", "y": "700"},
                kids=[el("div", {"anim": "shimmer", "w": "300", "h": "24",
                                 "x": "300", "y": "705"},
                         text="Searching for updates...")])
    strip = _strip("Searching the web now...", y=306)
    got = _open(_page(banner, strip))
    assert "Searching the web now" in (got.get("label") or ""), got


def test_the_global_walk_will_not_press_the_composer():
    """The composer's own affordance reads exactly like a live strip."""
    # Below the strip, where the composer actually sits — see the note above.
    comp = el("form", {"data-testid": "composer-root", "w": "600", "h": "80",
                       "x": "300", "y": "700"},
              kids=[el("div", {"w": "300", "h": "24", "x": "300", "y": "705"},
                       text="Searching for anything...")])
    strip = _strip("Searching the web now...", y=306)
    got = _open(_page(comp, strip))
    assert "Searching the web now" in (got.get("label") or ""), got
