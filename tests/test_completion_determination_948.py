"""#948 — ChatGPT + Gemini completion determination blind past finish.

TWO E2E RUNS (2026-07-13, backend.log wk1, runs at 14:15 and 01:22):

ChatGPT: the afternoon run's page showed "Research completed in 10m ·
27 citations" — our own panel tracker used that exact text as a click
anchor — while detect_completion_chatgpt simultaneously reported
"Research-complete text missing": the chip lives in a node that
body.innerText EXCLUDES (collapsed/virtualized), and the detector only
grepped innerText. The night run (canvas layout) had no text marker at all
in innerText and stayed blind 30+ min until the user stopped the run —
while the panel tracker click-looped into the finished document (21
misses + a CUA tier-3 scroll hunt: the user-observed "stuck scrolling the
finished doc"), and the CUA completion checks kept answering "still
generating" on a finished report.

Gemini: detect_completion_gemini's FIRST gate was "Start research button
visible → pre-research". The old plan bubble keeps its Start button in the
conversation DOM after the click, so the gate held for the ENTIRE run —
both runs logged start_research_btn_visible while the snapshot carried the
finished 97k/111k-char report — and the #897b trio marker below it was
unreachable. Same stale-gate-outranks-done-marker disease as Claude's
liveActive (fixed 2026-07-11).

THE FIX (user-directed: the completed affordances ARE the done signal —
no document opening/scrolling needed):
  ChatGPT: completedChip matched on body.textContent (includes hidden
    nodes; anchored forms "in Xm" / "· N citations|sources" only) +
    docPanelAffordances (right-docked geometry panel whose header strip
    has download AND expand/enlarge buttons — the Document panel that
    replaces the Researching panel). Tracker halts re-open attempts once
    the anchor reads the completed chip; CUA hint teaches both completed
    states and forbids scroll-hunting.
  Gemini: decision order is now explicit-stop → trio/completion-line
    (done-only UI outranks the stale Start button and weak running
    signals) → weak-running veto → VISIBLE-only Start gate → Share&Export.

Run: pytest tests/test_completion_determination_948.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

CGPT_SRC = inspect.getsource(research.detect_completion_chatgpt)
GEM_SRC = inspect.getsource(research.detect_completion_gemini)
POLL_SRC = inspect.getsource(research.poll_all_agents_round_robin)


# ── ChatGPT: completed chip via textContent ──────────────────────────────────

def test_chatgpt_completed_chip_uses_textcontent():
    assert "completedChip" in CGPT_SRC
    assert "document.body?.textContent" in CGPT_SRC, (
        "the completed chip must be matched on body.TEXTCONTENT — innerText "
        "excludes the collapsed/virtualized node the chip lives in (the "
        "2026-07-13 afternoon run had the chip on-screen as our own click "
        "anchor while the innerText regex missed it)"
    )


def test_chatgpt_completed_chip_forms_are_anchored():
    # Both anchored forms; a bare "research completed" in report PROSE must
    # not satisfy the chip (textContent scans hidden text, so the anchor
    # tails are the only guard against prose false-positives).
    assert "in\\\\s+\\\\d+\\\\s*[hms]" in CGPT_SRC, (
        "chip form 1 must anchor on 'in Xm' (e.g. 'Research completed in 10m')"
    )
    assert "citations?|sources?" in CGPT_SRC, (
        "chip form 2 must anchor on '· N citations/sources'"
    )


def test_chatgpt_doc_panel_affordances_marker():
    assert "docPanelAffordances" in CGPT_SRC
    # #951 (2026-07-13): the DOWNLOAD button ALONE, in a large right-anchored
    # panel header with no stop button, is the done signal. The prior rev
    # required download AND an expand button, but ChatGPT's finished-canvas
    # header is download + SHARE — so the AND missed every finished canvas and
    # the poller burned 17+ min scroll-checking a done document. Header-strip
    # scoping (r.top+96) + right-edge anchor + min-height stay.
    _i = CGPT_SRC.index("let docPanelAffordances")
    _blk = CGPT_SRC[_i:_i + 1600]
    assert "r.top + 96" in _blk, "affordance scan is scoped to the header strip"
    assert "r.right < vw - 40" in _blk and "r.height < vh * 0.5" in _blk, (
        "right-edge anchor + min-height keep it specific to a document panel"
    )
    assert "/download/.test(t)" in _blk
    assert "if (hasDl) { docPanelAffordances = true; break; }" in _blk, (
        "the download button ALONE flips the done signal"
    )
    # The expand requirement AND the right-dock left floor are both gone —
    # they were the two reasons the near-full-width finished canvas was missed.
    assert "hasExpand" not in _blk
    assert "r.left < vw * 0.22" not in _blk


def test_chatgpt_done_marker_includes_new_signals():
    assert ("thoughtFor || researchDone || completedChip || docPanelAffordances"
            in CGPT_SRC), (
        "doneMarker must accept the chip and the doc-panel affordances — "
        "the canvas layout carries NO text marker at all (30-min blind run)"
    )
    # Reason strings distinguish which marker fired (log-greppable).
    assert "completed_chip" in CGPT_SRC
    assert "doc_panel_affordances" in CGPT_SRC


def test_chatgpt_stop_button_still_vetoes():
    # The affordance markers must not outrank a live stop button.
    idx_stop = CGPT_SRC.index("if has_stop:")
    idx_marker = CGPT_SRC.index("if not has_done_marker:")
    assert idx_stop < idx_marker


# ── Gemini: done-only markers outrank the stale Start button ─────────────────

def test_gemini_trio_outranks_stale_start_button():
    # Decision order: explicit stop → trio/completion-line → weak running →
    # visible Start gate → Share&Export.
    i_stop = GEM_SRC.index('data.get("hasStopExplicit")')
    i_trio = GEM_SRC.index('data.get("reportButtonTrio")')
    i_chat = GEM_SRC.index('data.get("completedChatText")')
    i_weak = GEM_SRC.index('"running_weak_signal')
    # return-form (the docstring also mentions the reason string).
    i_start = GEM_SRC.index('return (False, "start_research_btn_visible')
    assert i_stop < i_trio < i_chat < i_weak < i_start, (
        "the done-only markers (trio / completion chat line) must outrank "
        "the Start-button gate — the old plan bubble keeps its Start button "
        "in the DOM forever, and both 2026-07-13 runs sat at 'pre-research' "
        "with the finished report in their own snapshot"
    )


def test_gemini_start_button_scan_requires_visibility():
    scan = GEM_SRC[GEM_SRC.index("let hasStartBtn"):GEM_SRC.index("let hasShareExport")]
    assert "offsetParent === null" in scan, (
        "a hidden leftover Start button must not gate completion"
    )


def test_gemini_explicit_stop_split_from_weak_signals():
    assert "hasStopExplicit" in GEM_SRC and "hasRunningWeak" in GEM_SRC, (
        "explicit stop buttons and weak running signals (streaming markers / "
        "animation tier) must be separate flags — only the explicit stop may "
        "veto the done-only markers"
    )
    # The animation tier feeds the WEAK flag, not the explicit one.
    anim = GEM_SRC[GEM_SRC.index("getAnimations"):GEM_SRC.index("hasStartBtn")]
    assert "hasRunningWeak = true" in anim


def test_gemini_stale_override_is_logged():
    assert "stale start-btn overridden" in GEM_SRC, (
        "a done verdict that overrode the stale Start button must say so in "
        "its reason string (log-greppable postmortems)"
    )


def test_gemini_share_export_alone_stays_weakest():
    # Share&Export-alone (bare 'share'/'export' text) keeps its old rank:
    # BELOW the weak-running veto and the Start gate.
    i_weak = GEM_SRC.index('"running_weak_signal')
    i_start = GEM_SRC.index('"start_research_btn_visible')
    i_share = GEM_SRC.index('"no_stop + share_export_visible"')
    assert i_weak < i_share and i_start < i_share


# ── Tracker: no click-loop into a finished document ──────────────────────────

def test_tracker_halts_on_completed_chip_anchor():
    assert "chatgpt_done_chip_anchor" in POLL_SRC
    # The open-gate must exclude the flag: the flag check precedes the
    # actual _open call that follows it (search FROM the gate — the helper
    # name also appears in earlier comments).
    gate = POLL_SRC.index('not p.get("chatgpt_done_chip_anchor")')
    openc = POLL_SRC.index("_open_chatgpt_activity_panel(", gate)
    assert gate < openc, (
        "once the anchor reads the completed chip, the tracker must stop "
        "trying to re-open the researching panel — it no longer exists "
        "(21 click-misses into the finished document, 2026-07-13 night run)"
    )
    # ...and the chip is detected from the click result's label.
    assert 're.search(r"research\\s+complete", _res_lbl, re.I)' in POLL_SRC


def test_tier3_escalation_respects_chip_flag():
    i = POLL_SRC.index("DOM missed strip 2x")
    cond = POLL_SRC[i - 700:i]
    assert 'not p.get("chatgpt_done_chip_anchor")' in cond, (
        "the CUA tier-3 panel hunt must not fire when the panel is "
        "legitimately gone (finished DR)"
    )


# ── CUA hint: completed states, no scroll-hunting ────────────────────────────

def test_chatgpt_cua_hint_teaches_completed_states():
    assert "Research completed in Xm" in POLL_SRC, (
        "the ChatGPT CUA hint must describe the completed chip"
    )
    assert "download and expand/enlarge buttons" in POLL_SRC, (
        "the hint must describe the Document-panel completed state"
    )
    assert "cannot see its end" in POLL_SRC, (
        "the hint must forbid answering 'generating' for an unscrollable "
        "long document — the night run's checks did exactly that 6×"
    )
