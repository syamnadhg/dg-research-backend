"""The panel that was never opened — 2026-08-06, second run.

    [21:17:30] [ChatGPT] activity already open (shape=side) at elapsed=204s - no click needed
    [21:17:31] [ChatGPT] panel tracking (shape=side): 0 URLs, 0 steps, 1 sections, searches=0

...and 0/0/0 on every sample to the end of the phase. The opener was never called
once: no "activity opened via DOM" and no panel-miss line anywhere in that run.
ChatGPT finished with sources=0.

The node the reader landed on one second later was

    DIV|flex w-full flex-col gap-1 empty:hidden items-end rtl:items-start

which is a right-aligned USER TURN wrapper. `items-end` is exactly why it sits in
the right half and clears the geometry, and nothing in the predicate asked
whether a conversation turn can be an activity panel.

⚠ WHAT IS NOT ESTABLISHED, and this file does not pretend otherwise: which
element, in which browsing context, actually satisfied the pre-check on that run.
It returned a bare boolean and logged nothing — while the opener it suppresses has
printed clickedTag and frameUrl since #913. Two independent analyses reached
opposite conclusions (host vs the about:blank frame) and neither could prove it,
because the evidence was never recorded. That asymmetry is half the defect and
the first thing fixed here.

THREE CHANGES, each correct whatever the trigger was:
  1. the probe returns IDENTITY (what, where, how many anchors) and the caller
     logs it, so a next occurrence is one grep rather than an argument;
  2. a conversation turn can never be the panel;
  3. the READER can overturn the pre-check. The latch could only ever be cleared
     by the same predicate that set it, so a false positive re-confirmed itself
     forever — while the reader held the disproof every single cycle.
"""

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, run_js  # noqa: E402

JS = research._CHATGPT_SIDE_PANEL_JS

# Verbatim from the run's own P2-panel-dbg line.
USER_TURN_CLS = "flex w-full flex-col gap-1 empty:hidden items-end rtl:items-start"


def _probe(spec):
    return run_js(spec, JS)["ret"]


def _user_turn(text="Deep research plan"):
    """The right-aligned user turn that satisfied the old predicate.

    Geometry from the live shape: right-aligned, panel-sized, past the midpoint.

    ⚠ The header text must be <= 40 chars and the leaf must sit past the viewport
    midpoint, or Signature A rejects it on those gates BEFORE the turn exclusion
    is ever consulted — and then every test here passes without exercising the
    fix. Both traps were hit while writing this file.
    """
    return el("body", {"w": "1440", "h": "900"}, kids=[
        el("main", {"w": "1440", "h": "900"}, kids=[
            el("article", {"data-testid": "conversation-turn-2",
                           "w": "800", "h": "300", "x": "600", "y": "100"}, kids=[
                el("div", {"data-message-author-role": "user",
                           "w": "760", "h": "260", "x": "620", "y": "110"}, kids=[
                    el("div", {"class": USER_TURN_CLS,
                               "w": "700", "h": "240", "x": "680", "y": "120"}, kids=[
                        el("div", {"w": "300", "h": "20", "x": "800", "y": "130"}, text),
                    ]),
                ]),
            ]),
        ]),
    ])


def _real_panel(anchors=6):
    """The genuine P2 activity panel: an ASIDE on the right with source rows."""
    rows = [el("li", {"w": "380", "h": "40", "x": "1000", "y": str(200 + i * 40)},
               kids=[el("a", {"href": "https://docs.nvidia.com/p%d" % i,
                              "w": "360", "h": "30", "x": "1010",
                              "y": str(205 + i * 40)}, "Source %d" % i)])
            for i in range(anchors)]
    return el("body", {"w": "1440", "h": "900"}, kids=[
        el("aside", {"class": "border-token-border-light bg-primary relative",
                     "w": "420", "h": "800", "x": "1010", "y": "40"}, kids=[
            el("div", {"w": "200", "h": "24", "x": "1020", "y": "50"}, "Activity"),
            el("ul", {"w": "400", "h": "700", "x": "1015", "y": "180"}, kids=rows),
        ]),
    ])


class TestAConversationTurnIsNeverThePanel:

    def test_the_observed_user_turn_no_longer_reads_as_open(self):
        assert _probe(_user_turn()) is None

    def test_it_would_still_have_matched_the_old_geometry(self):
        # If the turn simply stopped satisfying the shape, this test would pass
        # for the wrong reason. Strip the turn markers and the SAME element must
        # still be accepted — proving the exclusion is what refuses it.
        spec = el("body", {"w": "1440", "h": "900"}, kids=[
            el("main", {"w": "1440", "h": "900"}, kids=[
                el("div", {"class": USER_TURN_CLS,
                           "w": "700", "h": "240", "x": "680", "y": "120"}, kids=[
                    el("div", {"w": "300", "h": "20", "x": "800", "y": "130"},
                       "Deep research plan"),
                ]),
            ]),
        ])
        assert _probe(spec) is not None

    @pytest.mark.parametrize("marker", [
        {"data-message-author-role": "assistant"},
        {"data-testid": "conversation-turn-7"},
    ])
    def test_every_turn_marker_is_refused(self, marker):
        attrs = dict(marker)
        attrs.update({"w": "700", "h": "240", "x": "680", "y": "120"})
        spec = el("body", {"w": "1440", "h": "900"}, kids=[
            el("div", attrs, kids=[
                el("div", {"w": "300", "h": "20", "x": "800", "y": "130"},
                   "Deep research plan"),
            ]),
        ])
        assert _probe(spec) is None


class TestSignatureBRefusesTurnsToo:
    """⭐ Mutation escape. Every turn test above went through Signature A, so
    deleting the exclusion from Signature B — the bare `aside` / `[role=region]`
    / `[aria-label*=research]` sweep — survived untouched. Signature B is the
    LOOSER of the two: it needs no header text at all, only a right-side box with
    50 characters in it. A conversation turn clears that trivially."""

    def _turn_shaped_like(self, tag, attrs):
        a = dict(attrs)
        a.update({"data-message-author-role": "assistant",
                  "w": "420", "h": "400", "x": "1000", "y": "60"})
        return el("body", {"w": "1440", "h": "900"}, kids=[
            el(tag, a, kids=[
                el("div", {"w": "380", "h": "300", "x": "1010", "y": "80"},
                   "A long assistant reply that easily clears the fifty "
                   "character floor this signature applies."),
            ]),
        ])

    @pytest.mark.parametrize("tag,attrs", [
        ("aside", {}),
        ("div", {"role": "region"}),
        ("div", {"aria-label": "research output"}),
    ])
    def test_a_turn_wearing_a_panel_shape_is_refused(self, tag, attrs):
        assert _probe(self._turn_shaped_like(tag, attrs)) is None

    @pytest.mark.parametrize("tag,attrs", [
        ("aside", {}),
        ("div", {"role": "region"}),
        ("div", {"aria-label": "research output"}),
    ])
    def test_the_same_shape_without_the_turn_marker_is_accepted(self, tag, attrs):
        # Proves the exclusion is what refuses it, not the geometry or the text.
        a = dict(attrs)
        a.update({"w": "420", "h": "400", "x": "1000", "y": "60"})
        spec = el("body", {"w": "1440", "h": "900"}, kids=[
            el(tag, a, kids=[
                el("div", {"w": "380", "h": "300", "x": "1010", "y": "80"},
                   "A long panel body that easily clears the fifty character "
                   "floor this signature applies."),
            ]),
        ])
        assert _probe(spec) is not None


class TestTheRealPanelStillReadsAsOpen:
    """The predicate exists to stop blind re-clicking closing a live panel."""

    def test_a_panel_with_sources_is_open(self):
        assert _probe(_real_panel()) is not None

    def test_a_sparse_freshly_opened_panel_is_still_open(self):
        # #913 removed the old 50-char floor for exactly this reason; an empty
        # panel must not be bounced.
        assert _probe(_real_panel(anchors=0)) is not None


class TestItSaysWhatItFound:

    def test_the_hit_carries_identity(self):
        hit = _probe(_real_panel())
        for key in ("why", "tag", "cls", "anchors", "rows", "len"):
            assert key in hit, (key, hit)

    def test_the_anchor_count_is_real(self):
        assert _probe(_real_panel(anchors=6))["anchors"] == 6

    def test_the_state_helper_reports_the_context(self):
        src = inspect.getsource(research._chatgpt_activity_state)
        assert '"side_panel_id"' in src and '"side_panel_ctx"' in src
        assert '"host"' in src

    def test_the_caller_logs_the_identity(self):
        src = inspect.getsource(research.poll_all_agents_round_robin)
        i = src.index("activity already open (shape=")
        block = src[i:i + 900]
        assert "anchors=" in block and "ctx=" in block, (
            "this decision suppresses the opener for the whole phase and the log "
            "could not say what it was based on"
        )


class TestTheReaderCanOverturnThePreCheck:

    def _poll_src(self):
        return inspect.getsource(research.poll_all_agents_round_robin)

    def test_a_run_of_empty_reads_clears_an_unclicked_latch(self):
        src = self._poll_src()
        assert "chatgpt_panel_bare_reads" in src
        assert "_CHATGPT_PANEL_BARE_LIMIT" in src
        i = src.index("_CHATGPT_PANEL_BARE_LIMIT")
        block = src[i:i + 900]
        assert 'p["chatgpt_activity_panel_open"] = False' in block

    def test_one_empty_read_is_not_enough(self):
        # A real panel is legitimately sparse on its first sample.
        assert research._CHATGPT_PANEL_BARE_LIMIT >= 2

    def test_a_verified_click_is_never_overturned(self):
        src = self._poll_src()
        i = src.index("_CHATGPT_PANEL_BARE_LIMIT")
        block = src[i:i + 900]
        assert 'not p.get("chatgpt_panel_click_verified")' in block, (
            "a panel we watched mount must not be closed by this override"
        )

    def test_a_verified_click_sets_that_flag(self):
        src = self._poll_src()
        assert 'p["chatgpt_panel_click_verified"] = True' in src

    def test_the_override_resets_after_it_fires(self):
        # Otherwise it would re-fire on the very next sample and thrash.
        src = self._poll_src()
        i = src.index("_CHATGPT_PANEL_BARE_LIMIT")
        block = src[i:i + 900]
        assert 'p["chatgpt_panel_bare_reads"] = 0' in block

    def test_a_non_empty_read_resets_the_counter(self):
        # ⭐ Mutation escape. This asserted the substring "if _bare else 0",
        # which `+ (1 if _bare else 0)` also contains — so turning a consecutive
        # counter into a lifetime tally survived. Evaluate the expression instead.
        src = self._poll_src()
        i = src.index('p["chatgpt_panel_bare_reads"] = (')
        expr = src[i + len('p["chatgpt_panel_bare_reads"] = ('):]
        expr = expr[:expr.index("\n", expr.index(")"))].strip().rstrip(")")
        for prior, bare, want in ((3, True, 4), (3, False, 0), (0, True, 1)):
            got = eval(expr, {}, {  # noqa: S307 - the production expression itself
                "p": {"chatgpt_panel_bare_reads": prior}, "_bare": bare})
            assert got == want, (
                f"{prior} prior + bare={bare} gave {got}, expected {want} — the "
                f"counter must count CONSECUTIVE empties, not empties ever seen"
            )
