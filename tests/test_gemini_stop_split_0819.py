"""Gemini's stop signal is TWO signals, and its spinner animates by NAME.

THE REPORT (owner e2e, 2026-08-19, run chat_1787133277467_1). At 03:12:35 the log
says `[2D] Clicked 'Start research' ✓ (confirmed it took)`; at 03:12:40, `Gemini
is researching ✓`. Then `[Gemini] DOM not-done: start_research_btn_visible
(pre-research)` every tick for NINETEEN MINUTES, until `no_stop +
report_button_trio (stale start-btn overridden)` at 03:33:20.

⭐ The DECISION was right every single tick — there was no done-marker, no stop
button and no weak running signal, so the ladder correctly fell through to its
last resort. The REASON STRING is what lied: "pre-research" asserts we have not
started, which the run had disproved ten seconds earlier. That false state is
what the 15-minute no-growth arbiter met, and it cost a CUA arbiter call plus a
CUA completion check.

⛔⛔ ROOT CAUSE WAS TWO INDEPENDENT MISSES, either of which alone would have
prevented the lie:

1. The stop scan could not see Gemini's stop button. `aria-label="Stop response"`
   — capital S — against `button[aria-label*="stop"]`, and CSS attribute matching
   is case-SENSITIVE without the `i` flag. Only the last selector in the list
   carried `i`, and that one also demanded `[role="button"]`, which a native
   <button> does not have. CUA's own screenshot described the button twice
   ("solid square (⬛) Stop button in the bottom right") while our scan was deaf.

2. The running-animation tier matched CLASS names. Gemini's live research
   skeletons are `class="_index_0 item-line ng-star-inserted"` and carry the word
   `pulse` in the ANIMATION NAME (`_ngcontent-ng-c379413341_pulse`). Four visible
   pulsing rows, 634×14, and the tier #897b promoted precisely to catch them saw
   nothing.

⛔⛔ AND BOTH OBVIOUS ONE-LINE FIXES WERE WRONG, IN OPPOSITE DIRECTIONS. Adding
`i` alone promotes a HIDDEN button (offsetParent null, 0×0) to a veto that
outranks every done-marker — explicit stop sits at the TOP of the ladder, so a
19-minute cosmetic lie becomes a 90-minute timeout. Gating on visibility alone
rejects the only running signal Gemini offers, because that button is invisible
WHILE RUNNING. Only two live captures — one during research, one after
completion, same conversation — could tell those two fixes apart.

⭐⭐ WHICH IS WHY THIS FILE EXECUTES THE PAGE JS instead of asserting its source
text. The old tests DID pin `hasStopExplicit`, DID pin `getAnimations`, and DID
pin the decision order — and both bugs sailed straight through all of them,
because neither is visible in the source shape. A case-sensitive selector and a
selector aimed at the wrong attribute look exactly like working ones. Both
captures are replayed below through the real JS, under tests/_domshim.py.

Run: pytest tests/test_gemini_stop_split_0819.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from tests._domshim import NODE, el, evaluate_js, run_js  # noqa: E402

GEM_SRC = inspect.getsource(research.detect_completion_gemini)
# Everything after the evaluate() — the Python ladder, with no docstring and no
# JS in it. Ordering assertions taken on the whole source silently measure
# docstring prose instead (the 948 file had exactly that shape).
GEM_LADDER = GEM_SRC[GEM_SRC.index('        text_len = int(data.get("textLen")'):]
POLL_SRC = inspect.getsource(research.poll_all_agents_round_robin)
VERIFY_SRC = inspect.getsource(research.verify_gemini_generating)

needs_node = pytest.mark.skipif(NODE is None, reason="node required to execute page JS")


def _js():
    return evaluate_js(research.detect_completion_gemini)


# ── the two live captures, as fixtures ───────────────────────────────────────
#
# Owner-run against gemini.google.com/app/fcdbb547a044faf0, viewport 728×748,
# once DURING research and once AFTER completion in the same conversation. Every
# element below carries the geometry and visibility the capture recorded.

def _ambient():
    """Gemini's permanent background animation. Running, visible, enormous — on a
    COMPLETED page as much as a live one. This is the reason "any running
    animation" is not an acceptable running signal, and it is in BOTH fixtures."""
    return [
        el("div", {"class": "nl-blob nl-bg-blob", "anim": "morphBG",
                   "w": "1293", "h": "688", "x": "0", "y": "0"}),
        el("div", {"class": "nl-blob", "anim": "scaleBG", "w": "1293", "h": "688"}),
        el("div", {"class": "gradient-strip", "anim": "gradientScroll",
                   "w": "6204", "h": "5821", "x": "0", "y": "0"}),
    ]


def during_research(**kw):
    """`phase: DURING`. One stop-ish control in the whole document — icon-only,
    aria-label "Stop response", offsetParent null, 0×0 — and four pulsing
    skeleton rows whose CLASS says nothing and whose ANIMATION NAME says pulse.
    No leftover Start button (`leftoverStartResearch: []`)."""
    kids = [
        el("button", {"aria-label": "Stop response", "hidden": "",
                      "w": "0", "h": "0", "x": "0", "y": "0"}),
        *[el("div", {"class": "_index_0 item-line ng-star-inserted",
                     "anim": "_ngcontent-ng-c379413341_pulse",
                     "w": "634", "h": "14"}) for _ in range(4)],
        *_ambient(),
        el("message-content", {}, "Starting now — I'll let you know when it's done."),
    ]
    kids.extend(kw.get("extra", []))
    return el("body", {}, "", kids)


def after_completion(**kw):
    """`phase: AFTER_COMPLETION`. The stop button is GONE, the skeletons are gone,
    the ambient background is still running, the leftover "Start research" is
    present but vis=false, and the done markers are there (`Share and export`
    hidden at 0×0, `Export menu` visible at 40×40). The circular-progress
    animations DO contain "spin" and are 0×0 — they are in the fixture on purpose,
    because they are the trap the visibility gate exists for."""
    kids = [
        el("button", {"aria-label": "Start research", "hidden": "",
                      "w": "0", "h": "0"}),
        el("button", {"aria-label": "Export menu", "w": "40", "h": "40",
                      "x": "566", "y": "10"}),
        el("button", {"aria-label": "Share and export", "hidden": "",
                      "w": "0", "h": "0"}),
        el("button", {"aria-label": "Copy", "hidden": "", "w": "0", "h": "0"}),
        # 0×0 but NOT in a hidden subtree — the shape the capture recorded, and
        # the one that needs the rect check rather than offsetParent.
        el("div", {"class": "mdc-circular-progress-left",
                   "anim": "mdc-circular-progress-left-spin", "w": "0", "h": "0"}),
        el("div", {"class": "mdc-circular-progress-right",
                   "anim": "mdc-circular-progress-right-spin", "w": "0", "h": "0"}),
        el("div", {"class": "apd-ring", "anim": "apd-ring-fade-in", "w": "200", "h": "40"}),
        el("img", {"class": "hero", "anim": "image-fade-on", "w": "300", "h": "200"}),
        *_ambient(),
        el("message-content", {}, "I've completed your research. Feel free to ask "
                                  "me follow-up questions or request changes."),
    ]
    kids.extend(kw.get("extra", []))
    return el("body", {}, "", kids)


# ── 1. the capture taken WHILE Gemini was researching ────────────────────────

class TestDuringResearch:

    @needs_node
    def test_the_stop_button_is_found_at_all(self):
        """⛔ The whole 19-minute lie in one assertion: before the split, BOTH
        stop flags read false here, because `*="stop"` cannot match "Stop
        response"."""
        r = run_js(during_research(), _js())["ret"]
        assert (r["hasStopVisible"] or r["hasStopHidden"]), (
            "the case-sensitive selector is back — `aria-label=\"Stop response\"` "
            "is the only stop control Gemini renders while researching"
        )

    @needs_node
    def test_it_is_found_as_HIDDEN_and_never_as_the_veto(self):
        """⛔⛔ The direction that matters. This button is offsetParent null and
        0×0 WHILE RUNNING, and the explicit-stop rung vetoes even a finished
        report — so classifying it visible turns a cosmetic 19-minute lie into a
        90-minute timeout on every Gemini run."""
        r = run_js(during_research(), _js())["ret"]
        assert r["hasStopHidden"] is True
        assert r["hasStopVisible"] is False

    @needs_node
    def test_the_pulsing_skeletons_are_seen_by_animation_name(self):
        """⛔⛔ The second, independent miss. The class is `item-line`; the word
        `pulse` is in the animation name. A class-based selector reads four
        visibly pulsing rows as a still page."""
        r = run_js(during_research(), _js())["ret"]
        assert r["hasRunningWeak"] is True, (
            "the tier is matching class names again — Gemini's skeletons are "
            "class=\"_index_0 item-line ng-star-inserted\""
        )
        assert "pulse" in r["runningWeakVia"], r["runningWeakVia"]

    @needs_node
    def test_a_platform_that_announces_streaming_outright_is_believed(self):
        """The oldest of the three running tiers, and it had no test at all until
        a mutant deleted it and nothing noticed. It is the cheapest and most
        trustworthy of them — the page saying so itself — and it must keep
        outranking nothing and vetoing the weak paths, exactly like the others."""
        spec = el("body", {}, "", [
            el("div", {"data-is-streaming": "true", "w": "600", "h": "200"}),
            el("message-content", {}, "Working on it."),
        ])
        r = run_js(spec, _js())["ret"]
        assert r["hasRunningWeak"] is True
        assert r["runningWeakVia"] == "streaming-marker", r["runningWeakVia"]
        done, reason, _s = asyncio.run(research.detect_completion_gemini(_FakePage(spec)))
        assert done is False and "streaming-marker" in reason, reason

    @needs_node
    def test_the_other_two_streaming_class_markers_count_too(self):
        for cls in ("loading-indicator", "streaming"):
            spec = el("body", {}, "", [el("div", {"class": cls, "w": "60", "h": "60"})])
            r = run_js(spec, _js())["ret"]
            assert r["hasRunningWeak"] is True, cls
            assert r["runningWeakVia"] == "streaming-marker", cls

    @needs_node
    def test_the_reason_says_where_the_animation_was(self):
        """⭐ The belt-and-braces the plan asked for, delivered as EVIDENCE
        rather than as a gate. Scoping the search to model-response nodes was
        the obvious move — but neither capture records the ancestry of Gemini's
        `item-line` skeletons, so a positive scope could equally be a guard that
        cannot fire. The reason string carries the answer instead, which is
        exactly what someone needs to turn it into a gate without guessing."""
        outside = run_js(during_research(), _js())["ret"]
        assert outside["runningWeakVia"].endswith(" page-wide"), outside["runningWeakVia"]

        inside = el("body", {}, "", [
            el("message-content", {}, "Working", [
                el("div", {"class": "item-line", "anim": "ng_pulse",
                           "w": "634", "h": "14"})]),
        ])
        r = run_js(inside, _js())["ret"]
        assert r["runningWeakVia"].endswith(" in-response"), r["runningWeakVia"]

    @needs_node
    def test_nothing_here_reads_as_finished(self):
        r = run_js(during_research(), _js())["ret"]
        assert r["reportButtonTrio"] is False
        assert r["completedChatText"] is False
        assert r["hasShareExport"] is False

    @needs_node
    def test_the_verdict_is_running_and_names_the_animation(self):
        done, reason, _snap = asyncio.run(
            research.detect_completion_gemini(_FakePage(during_research())))
        assert done is False
        assert reason.startswith("running_weak_signal"), reason
        assert "pulse" in reason, (
            "the reason must name the animation it believed — that name is the "
            "whole diagnosis if a future ambient animation ever matches"
        )
        assert "pre-research" not in reason


# ── 2. the capture taken AFTER the report was finished ───────────────────────

class TestAfterCompletion:

    @needs_node
    def test_the_ambient_background_is_not_a_running_signal(self):
        """⛔ The trap that makes "any running animation" unshippable: morphBG,
        scaleBG and gradientScroll are running, visible and viewport-scale on a
        COMPLETED page. Unscoped, this flag would be permanently true and would
        veto the weakest done path for the rest of time."""
        r = run_js(after_completion(), _js())["ret"]
        assert r["hasRunningWeak"] is False, (
            f"a finished page reads as running via {r['runningWeakVia']!r}"
        )

    @needs_node
    def test_a_zero_by_zero_spinner_is_not_a_running_signal(self):
        """`mdc-circular-progress-left-spin` DOES match the name regex. It is
        0×0. The visibility gate is the only thing standing between it and a
        permanent false "still generating"."""
        r = run_js(after_completion(), _js())["ret"]
        assert r["hasRunningWeak"] is False, r["runningWeakVia"]

    @needs_node
    def test_the_hidden_stop_button_really_is_gone(self):
        """The measured fact that retired the "case-insensitive alone would have
        hung every run" claim: post-completion there is no stop control at all,
        so `i` alone would not have hung. It is still not enough on its own —
        the button is invisible while RUNNING, which is the other half."""
        r = run_js(after_completion(), _js())["ret"]
        assert r["hasStopHidden"] is False
        assert r["hasStopVisible"] is False

    @needs_node
    def test_the_leftover_start_button_does_not_gate(self):
        r = run_js(after_completion(), _js())["ret"]
        assert r["hasStartBtn"] is False, (
            "the leftover Start research is vis=false in the capture; the "
            "visibility check on that scan is doing real work"
        )

    @needs_node
    def test_the_report_is_called_done(self):
        done, reason, snap = asyncio.run(
            research.detect_completion_gemini(_FakePage(after_completion())))
        assert done is True, reason
        assert snap["text_len"] > 0


# ── 3. the hidden stop must never outrank a done marker ──────────────────────

def _trio():
    return [el("button", {"w": "80", "h": "36"}, "Contents"),
            el("button", {"w": "120", "h": "36"}, "Share & Export"),
            el("button", {"w": "80", "h": "36"}, "Create")]


class TestHangProofByConstruction:

    @needs_node
    def test_a_hidden_stop_plus_a_finished_report_is_DONE(self):
        """⛔⛔ THE 90-MINUTE TIMEOUT THAT MUST NEVER SHIP. This is the state the
        naive `i` fix would have produced: a done report with an invisible stop
        button left in the DOM. If the hidden stop is ranked as a veto, this run
        never completes."""
        spec = during_research(extra=_trio())
        done, reason, _s = asyncio.run(
            research.detect_completion_gemini(_FakePage(spec)))
        assert done is True, reason
        assert "report_button_trio" in reason
        assert "hidden stop-btn overridden" in reason, (
            "the override has to be in the reason string — it is the only way a "
            "postmortem can tell this rung fired"
        )

    @needs_node
    def test_a_VISIBLE_stop_still_vetoes_a_finished_report(self):
        """The other direction, unchanged: a real, on-screen Stop button means
        Gemini is writing, and a trio rendered underneath it is a report still
        being streamed into place."""
        spec = during_research(extra=[
            el("button", {"aria-label": "Stop response", "w": "40", "h": "40"}),
            *_trio()])
        done, reason, _s = asyncio.run(
            research.detect_completion_gemini(_FakePage(spec)))
        assert done is False, reason
        assert reason.startswith("stop_btn_present"), reason

    @needs_node
    def test_a_hidden_stop_alone_still_says_running(self):
        """With no skeletons and no markers, the hidden stop is the only evidence
        left — and it must still be enough to keep the last resort from claiming
        pre-research."""
        spec = el("body", {}, "", [
            el("button", {"aria-label": "Stop response", "hidden": "",
                          "w": "0", "h": "0"}),
            *_ambient(),
            el("message-content", {}, "Starting now."),
        ])
        r = run_js(spec, _js())["ret"]
        assert r["hasStopHidden"] is True and r["hasRunningWeak"] is False
        done, reason, _s = asyncio.run(research.detect_completion_gemini(_FakePage(spec)))
        assert done is False
        assert reason.startswith("running_hidden_stop_btn"), reason


# ── 4. what "hidden" means, in both of the two shapes a browser has ──────────

class TestVisibilityHasTwoShapes:

    @needs_node
    def test_display_none_shape_zero_box_inside_a_hidden_subtree(self):
        spec = el("body", {}, "", [el("button", {"aria-label": "Stop response",
                                                 "hidden": "", "w": "0", "h": "0"})])
        r = run_js(spec, _js())["ret"]
        assert r["hasStopHidden"] is True and r["hasStopVisible"] is False

    @needs_node
    def test_visibility_hidden_shape_a_real_box_with_no_offsetParent(self):
        """A `visibility:hidden` element keeps its box. Without the offsetParent
        half of the gate this reads as an on-screen Stop and vetoes everything."""
        spec = el("body", {}, "", [el("button", {"aria-label": "Stop response",
                                                 "hidden": "", "w": "40", "h": "40"})])
        r = run_js(spec, _js())["ret"]
        assert r["hasStopHidden"] is True and r["hasStopVisible"] is False

    @needs_node
    def test_collapsed_shape_a_zero_box_that_is_not_in_a_hidden_subtree(self):
        """And the mirror: without the rect half of the gate, a 0×0 control that
        merely has an offsetParent reads as visible."""
        spec = el("body", {}, "", [el("button", {"aria-label": "Stop response",
                                                 "w": "0", "h": "0"})])
        r = run_js(spec, _js())["ret"]
        assert r["hasStopHidden"] is True and r["hasStopVisible"] is False

    @needs_node
    def test_an_on_screen_stop_button_is_the_veto(self):
        spec = el("body", {}, "", [el("button", {"aria-label": "Stop response",
                                                 "w": "40", "h": "40"})])
        r = run_js(spec, _js())["ret"]
        assert r["hasStopVisible"] is True


# ── 5. the veto is the narrow rung, on purpose ───────────────────────────────

class TestTheVetoStaysNarrow:

    @needs_node
    def test_a_glued_word_is_not_a_stop_button(self):
        """⚠ HYPOTHETICAL, and labelled as such: no such control was captured.
        The pin exists because the veto is the ONE rung that can hold a finished
        run hostage, so widening it from a word-boundary match back to a bare
        substring is a change that should have to argue for itself."""
        spec = el("body", {}, "", [el("button", {"aria-label": "Stopwatch",
                                                 "w": "40", "h": "40"}),
                                   *_trio()])
        r = run_js(spec, _js())["ret"]
        assert r["hasStopVisible"] is False and r["hasStopHidden"] is False

    @needs_node
    def test_the_wordings_that_ARE_stop_buttons_all_match(self):
        for label in ("Stop response", "Stop generating", "STOP", "stop",
                      "Stop streaming"):
            spec = el("body", {}, "", [el("button", {"aria-label": label,
                                                     "w": "40", "h": "40"})])
            r = run_js(spec, _js())["ret"]
            assert r["hasStopVisible"] is True, label

    @needs_node
    def test_title_and_bare_text_still_count(self):
        for attrs, text in (({"title": "Stop response"}, ""),
                            ({}, "Stop generating"),
                            ({"aria-label": "Cancel"}, "")):
            spec = el("body", {}, "", [
                el("button", {**attrs, "w": "40", "h": "40"}, text)])
            r = run_js(spec, _js())["ret"]
            assert r["hasStopVisible"] is True, (attrs, text)


# ── 6. the label that lied, and the one fact that unlies it ──────────────────

class _FakePage:
    """Runs the REAL page JS under the shim, so the ladder below is fed the same
    reading production would compute. Falls back to a literal dict when a test
    wants to pin one flag directly."""

    def __init__(self, spec_or_reading):
        self._spec = spec_or_reading

    async def evaluate(self, js, arg=None):
        if isinstance(self._spec, dict) and "tag" not in self._spec:
            return dict(self._spec)
        return run_js(self._spec, js)["ret"]


def _reading(**over):
    base = {"hasStopVisible": False, "hasStopHidden": False,
            "hasRunningWeak": False, "runningWeakVia": "",
            "hasStartBtn": False, "hasShareExport": False,
            "reportButtonTrio": False, "completedChatText": False,
            "textLen": 176, "sources": 0, "steps": 28}
    base.update(over)
    return base


def _detect(reading, **kw):
    return asyncio.run(research.detect_completion_gemini(_FakePage(reading), **kw))


class TestTheReasonStringStopsLying:

    def test_a_confirmed_running_agent_is_not_called_pre_research(self):
        """The 08-19 state exactly: a visible leftover Start button, no marker
        yet, and a run whose start three separate probes had confirmed."""
        done, reason, _s = _detect(_reading(hasStartBtn=True), running_confirmed=True)
        assert done is False
        assert "pre-research" not in reason, reason
        assert reason.startswith("stale_start_btn_no_done_marker"), reason

    def test_an_UNCONFIRMED_agent_keeps_the_verbatim_pre_research_label(self):
        """⛔ The 2026-08-17 ninety-minute failure: we clicked Start, the verify
        disagreed, and nothing ever started. `pre-research` was the CORRECT label
        there, once a minute for an hour and a half. Suppressing it would have
        deleted the only honest account of that run."""
        done, reason, _s = _detect(_reading(hasStartBtn=True))
        assert done is False
        assert reason == "start_research_btn_visible (pre-research)"

    def test_the_confirmation_cannot_promote_anything_to_done(self):
        """It renames one not-done reason. It must not be able to decide done."""
        for kw in ({}, {"running_confirmed": True}):
            done, _r, _s = _detect(_reading(hasStartBtn=True), **kw)
            assert done is False
            done, _r, _s = _detect(_reading(), **kw)
            assert done is False

    def test_a_confirmed_running_agent_with_a_stop_button_still_reports_the_stop(self):
        done, reason, _s = _detect(_reading(hasStopVisible=True, hasStartBtn=True),
                                   running_confirmed=True)
        assert reason.startswith("stop_btn_present"), reason


# ── 7. the ladder's ranks, executed rather than read ─────────────────────────

class TestTheLadderRanks:

    def test_visible_stop_outranks_every_done_marker(self):
        done, reason, _s = _detect(_reading(
            hasStopVisible=True, reportButtonTrio=True, completedChatText=True,
            hasShareExport=True))
        assert done is False and reason.startswith("stop_btn_present")

    def test_the_trio_outranks_every_weak_signal(self):
        done, reason, _s = _detect(_reading(
            reportButtonTrio=True, hasRunningWeak=True, hasStopHidden=True,
            hasStartBtn=True))
        assert done is True, reason
        for bit in ("stale start-btn overridden", "weak running-signal overridden",
                    "hidden stop-btn overridden"):
            assert bit in reason, (bit, reason)

    def test_the_completion_line_outranks_every_weak_signal(self):
        done, reason, _s = _detect(_reading(
            completedChatText=True, hasRunningWeak=True, hasStopHidden=True))
        assert done is True, reason
        assert "completed_chat_text" in reason

    def test_a_weak_running_signal_vetoes_the_share_export_path(self):
        done, reason, _s = _detect(_reading(hasRunningWeak=True, hasShareExport=True))
        assert done is False and reason.startswith("running_weak_signal"), reason

    def test_a_hidden_stop_vetoes_the_share_export_path_too(self):
        """The weakest done rung is the only thing a hidden stop can cost — which
        is what makes ranking it here safe."""
        done, reason, _s = _detect(_reading(hasStopHidden=True, hasShareExport=True))
        assert done is False and reason.startswith("running_hidden_stop_btn"), reason

    def test_share_export_alone_still_completes_a_quiet_page(self):
        done, reason, _s = _detect(_reading(hasShareExport=True))
        assert done is True and "share_export_visible" in reason

    def test_a_page_with_nothing_on_it_is_not_done(self):
        done, reason, _s = _detect(_reading())
        assert done is False and reason.startswith("no_done_marker")

    def test_the_source_order_matches_the_executed_order(self):
        """Belt for the executed rungs above: the two done-marker returns must
        sit between the veto and the weak rungs in the SOURCE too, so a reorder
        cannot pass by accident on a reading that exercises one path."""
        i_stop = GEM_LADDER.index('data.get("hasStopVisible")')
        i_trio = GEM_LADDER.index('data.get("reportButtonTrio")')
        i_chat = GEM_LADDER.index('data.get("completedChatText")')
        i_weak = GEM_LADDER.index('"running_weak_signal')
        i_hidden = GEM_LADDER.index('"running_hidden_stop_btn')
        i_start = GEM_LADDER.index('return (False, "start_research_btn_visible')
        i_share = GEM_LADDER.index('"no_stop + share_export_visible"')
        assert i_stop < i_trio < i_chat < i_weak < i_hidden < i_start < i_share


# ── 8. the caller hands over the one fact that separates the two states ──────

class TestTheWiring:

    def test_the_detector_is_given_the_confirmation_at_both_call_sites(self):
        assert POLL_SRC.count("**_detect_kw") == 2, (
            "the fast-confirm re-poll runs the same detector — passing the fact "
            "to only one of the two call sites gives one of them a lying label"
        )

    def test_the_fact_is_the_running_verify_and_NOT_the_start_click(self):
        """⛔⛔ THE PLAN ASKED FOR THE WRONG FACT. "Start was confirmed pressed"
        was TRUE in the 2026-08-17 ninety-minute failure as well — the click
        reported success and the verify disagreed — so it cannot tell a run that
        started from one that never did, and using it would have suppressed the
        correct label on the very run that needed it. `verified` is the fact that
        differs between the two incidents."""
        # ⛔ AN EXACT LINE, not "does the right name appear somewhere in the
        # next 120 characters". The first version of this pin asked exactly that,
        # and a mutant that widened the seed to
        # `agent.get("verified") or agent.get("needs_start_verify")` — which IS
        # "we clicked Start", spelled the way this file spells it — satisfied
        # every clause of it and survived. A presence check cannot see a meaning
        # change that ADDS a term.
        assert ('            "gemini_running_confirmed": bool(agent.get("verified")),\n'
                in POLL_SRC), (
            "the seed is no longer exactly the running-verify. Any other "
            "expression here is a different claim about what happened, and "
            '"we pressed Start" was TRUE in the ninety-minute failure too'
        )

    def test_the_two_later_confirmations_also_set_it(self):
        """2D's instant verify is not the only path: the deferred start-verify leg
        and the watch leg both establish the same fact seconds later, and an
        agent confirmed by either must not keep the pre-research label."""
        assert POLL_SRC.count('p["gemini_running_confirmed"] = True') == 2
        # Adjacency, spelled out — a neighbourhood-sized slice would let the
        # assignment drift anywhere inside it, including onto a branch that does
        # not actually confirm anything.
        assert ('                        p["needs_start_verify"] = False\n'
                '                        p["gemini_running_confirmed"] = True'
                in POLL_SRC)
        assert ('                        p["gemini_watch_start"] = False\n'
                '                        p["gemini_running_confirmed"] = True'
                in POLL_SRC)

    def test_only_gemini_gets_the_keyword(self):
        """ChatGPT's and Claude's detectors take no such argument; handing it to
        them is a TypeError on every poll of a healthy run."""
        assert ('                _detect_kw = ({"running_confirmed": '
                'bool(p.get("gemini_running_confirmed"))}\n'
                '                              if name == "Gemini" else {})'
                in POLL_SRC)


# ── 9. the probe that works because it has NO visibility gate ────────────────

class TestVerifyGeminiGeneratingKeepsItsBlindSpot:

    def test_the_button_scan_has_no_visibility_gate(self):
        """⛔⛔ A "consistency fix" here would break the one Gemini probe that
        works. `[2D] Gemini is researching ✓` fires because this scan lowercases
        the attributes and does NOT check visibility — and the only stop control
        Gemini renders while researching is offsetParent null and 0×0. Adding the
        gate that the Start scans have would reject the only evidence there is.
        Same DOM fact, a different question, a different ranking."""
        scan = VERIFY_SRC[VERIFY_SRC.index("Broad button scan"):
                          VERIFY_SRC.index("Animation/streaming indicators")]
        assert "offsetParent" not in scan, (
            "verify_gemini_generating answers 'is it alive', where a hidden stop "
            "button is good enough evidence; only the completion detector needs "
            "to rank it below the done markers"
        )
        assert "'stop'" in scan and ".toLowerCase()" in scan

    def test_the_reason_it_must_stay_is_written_down(self):
        assert "DO NOT ADD A VISIBILITY GATE" in VERIFY_SRC


# ── 10. what this wave did NOT fix, and must not be "fixed" by widening ──────

class TestTheArbitersOwnCause:
    """⛔⛔ THE PLAN SAID THIS FIX WOULD REMOVE THE CUA SPEND. IT DOES NOT, and the
    reason is a second dead guard nobody had looked at.

    The 15-minute no-growth arbiter that fired on 08-19 reads
    `status_is_active`, which is the SCRAPER's status measured against
    ("planning", "thinking", "researching", "searching"). All three scrapers in
    SCRAPE_FNS emit exactly `generating`, `complete`, `idle` or `scrape_error` —
    so that half of the gate has never been true for any platform, and the only
    live half is `phase == "planning"`. The arbiter never reads this detector's
    verdict or its reason, so a truthful reason string cannot quiet it.

    It is deliberately LEFT DEAD. Adding "generating" would silence the stuck
    arbiter for every platform, and the note beside it already records why: the
    scraper reports movement off stale panel steps on a frozen page. What
    "active" should mean is a judgement about which evidence is trustworthy, not
    a wider tuple."""

    def test_none_of_the_four_active_statuses_is_a_value_any_scraper_emits(self):
        # ⛔ To the closing paren, NOT to a character count. The first version of
        # this pin took 90 characters, and the mutant that added "generating"
        # reformatted the tuple onto two lines — so the forbidden word landed
        # just outside the window and the mutant survived a test written to
        # catch exactly it. A slice with a length in it measures the length.
        at = POLL_SRC.index("_active_statuses = (")
        decl = POLL_SRC[at:POLL_SRC.index(")", at) + 1]
        for never_emitted in ("planning", "thinking", "researching", "searching"):
            assert never_emitted in decl
        for actually_emitted in ("generating", "complete", "idle", "scrape_error"):
            assert f'"{actually_emitted}"' not in decl, (
                f"{actually_emitted!r} was added to the arbiter's active-status "
                "list — that silences the 10-minute stuck arbiter for every "
                "platform, because a frozen page reports it too"
            )

    def test_the_measurement_is_written_down_beside_it(self):
        at = POLL_SRC.index("_active_statuses = (")
        assert "NOT ONE OF THOSE FOUR VALUES IS EVER PRODUCED" in POLL_SRC[at:at + 900]


# ── 11. the shim's new capability, tested before it is trusted ───────────────

class TestTheShimAnswersLikeABrowser:

    @needs_node
    def test_a_finished_animation_is_not_running(self):
        """⛔ If the shim reported every animation as running, every test above
        would pass against a detector with no playState check at all — and the
        playState check is the entire reason these probes use getAnimations()
        instead of the computed style (a browser leaves animationName set on a
        FINISHED animation)."""
        spec = el("body", {}, "", [
            el("div", {"class": "row", "anim": "somepulse", "playstate": "finished",
                       "w": "600", "h": "14"})])
        r = run_js(spec, _js())["ret"]
        assert r["hasRunningWeak"] is False, (
            "a persisted-but-finished animation read as running"
        )

    @needs_node
    def test_a_running_animation_reaches_the_detector(self):
        spec = el("body", {}, "", [
            el("div", {"class": "row", "anim": "somepulse", "w": "600", "h": "14"})])
        r = run_js(spec, _js())["ret"]
        assert r["hasRunningWeak"] is True and "somepulse" in r["runningWeakVia"]

    @needs_node
    def test_document_getAnimations_reports_document_order(self):
        spec = el("body", {}, "", [
            el("div", {"anim": "alpha-spin", "w": "10", "h": "10"}),
            el("div", {"anim": "beta-spin", "w": "10", "h": "10"}),
        ])
        out = run_js(spec, "() => document.getAnimations().map(a => a.animationName)")
        assert out["ret"] == ["alpha-spin", "beta-spin"], out["ret"]

    @needs_node
    def test_an_element_with_no_animation_reports_none(self):
        out = run_js(el("body", {}, "", [el("div", {"w": "10", "h": "10"})]),
                     "() => document.getAnimations().length")
        assert out["ret"] == 0
