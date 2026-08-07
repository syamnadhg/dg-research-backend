"""The 2026-08-06 blind completion detector: one probe, every context, combined.

`detect_completion_chatgpt` computed every signal from the MAIN FRAME plus the
first frame whose URL contained "deep_research"/"oaiusercontent", then `break`ed.
On 2026-08-06 the frame inventory captured at the same poll cycle was:

    chatgpt.com/c/<id>
    chatgpt.com/backend-api/sentinel/frame.html
    connector-openai-deep-research.web-sandbox.oaiusercontent.com/?app=chatg
    about:blank

The filter matched the CONNECTOR SHELL, evaluated it, found nothing, and stopped
— so `about:blank`, where the Deep Research surface actually lived, was never
visited. Every cycle from 12:41 to 13:11 logged the same line:

    DOM not-done: no_done_marker (...all missing); snap={'text_len': 0, 'sources': 0, 'steps': 1}

while the vision arbiter described "a richly populated table ... plus narrative
text below it". Same tick, same page, the panel tracker — which walks EVERY frame
(the #913 fix) — read 26 source URLs. A detector evaluating the same document
could not have scored 0.

⭐ THE LESSON, for the fourth time in this file: a fix that lands on ONE of the
paths to a sink leaves the others exactly as broken. `#913` wrote the reason down
in 2026-07 — "the old deep_research|oaiusercontent filter simply never visited the
frame that renders it" — and five other consumers kept the substring list.

⭐ The second half was an ASYMMETRIC PAYLOAD: the host branch ran a rich probe and
the iframe branch a thin one that computed only two markers. The two markers added
2026-07-13 *for the finished-canvas layout* existed on the host path only, so even
a widened filter could not have seen what that layout renders. There is now one
payload, and a test below asserts there is exactly one.

These tests EXECUTE the probe against captured markup and drive the real detector
with fake frames that RECORD being asked. Counting the calls is the point: a test
that only checks the return value passes against a walk that never runs.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, evaluate_js, run_js, spec_from_html, stamp_panel_geometry  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "panels"
PROBE = research._CHATGPT_DONE_PROBE_JS

# The shim's viewport. Both floors in `_chatgpt_surface_frame_targets`' companion
# constants must sit under it or the fixtures below could never qualify.
SHIM_VW, SHIM_VH = 1440, 900

# Verbatim from the panel-miss snapshot the run dumped (e2e.log:445 and 585): the
# only rows below the last user message were ten copies of the disclaimer. This is
# what the main frame actually held while the report was finished elsewhere.
DISCLAIMER = "ChatGPT can make mistakes. Check important info."


def _probe(spec):
    return run_js(spec, PROBE)["ret"]


def _host_shell():
    """The 2026-08-06 main frame: a user turn, a disclaimer, and nothing else.

    Note what is ABSENT — no `[data-message-author-role="assistant"]`. That
    absence is the whole of `text_len: 0`.
    """
    return el("body", kids=[
        el("main", kids=[
            el("div", {"data-message-author-role": "user", "w": "700", "h": "40"},
               "NemoClaw vs NemoHermes vs Nemotron and also about OpenShell"),
            el("div", {"data-testid": "thread-disclaimer", "w": "700", "h": "20"},
               DISCLAIMER, repeat=10),
        ]),
    ])


def _finished_canvas():
    """A finished DR document panel: right-anchored, tall, download in the header.

    The geometry is the documented contract of the 2026-07-13 `docPanelAffordances`
    marker (right edge, >=380 wide, >=half the viewport tall, header strip only).
    The citation anchors are lifted from the real captured panel, so the source
    count is measured against markup the page actually produced rather than
    against markup written to match a theory of it.
    """
    captured = spec_from_html(
        (FIXTURES / "chatgpt_activity_panel_grown_20260806.html").read_text(
            encoding="utf-8", errors="replace")
    )
    stamp_panel_geometry(captured)
    return el("body", kids=[
        el("div", {"w": "1400", "h": "860", "x": "40", "y": "0"}, kids=[
            el("button", {"aria-label": "Download", "w": "32", "h": "32",
                          "x": "1380", "y": "10"}),
            captured,
        ]),
    ])


class TestTheProbeReadsTheMainFrameHonestly:
    """Fixture (a): what the detector was actually looking at for 33 minutes."""

    def test_the_2026_08_06_main_frame_measures_zero(self):
        r = _probe(_host_shell())
        # Every number in the live log line, reproduced from markup.
        assert r["assistantLen"] == 0
        assert r["panelLen"] == 0
        assert r["sources"] == 0
        assert r["docPanelAffordances"] is False
        assert r["thoughtFor"] is False
        assert r["completedChip"] is False

    def test_a_disclaimer_is_not_a_done_marker(self):
        r = _probe(_host_shell())
        assert not any(r[k] for k in
                       ("thoughtFor", "researchDone", "completedChip",
                        "docPanelAffordances"))


class TestTheProbeReadsTheSurfaceWhereverItIs:
    """Fixture (b): the document the detector never ran against."""

    def test_the_finished_canvas_reports_done_and_a_real_length(self):
        r = _probe(_finished_canvas())
        assert r["docPanelAffordances"] is True, "the download header did not register"
        # `assistantLen` is still 0 here — the canvas is not a conversation turn.
        # That is exactly why `panelLen` had to exist: without it this surface
        # measures 0 even once the right document is being read.
        assert r["assistantLen"] == 0
        # The captured panel really does carry ~8.2k characters of readable text.
        # The live log said `text_len: 0` against a document like this one.
        assert r["panelLen"] > 5_000, r["panelLen"]
        assert r["sources"] >= 26, r["sources"]

    def test_the_panel_length_is_what_rescues_the_flatness_gate(self):
        r = _probe(_finished_canvas())
        assert max(r["assistantLen"], r["panelLen"]) > 0

    def test_a_canvas_in_the_MAIN_frame_still_measures(self):
        # ⭐ Mutation escape. Every other test here puts the surface in a frame,
        # where `bodyLen` also counts — so deleting `panelLen` from the snapshot
        # changed nothing any of them could see. But `docPanelAffordances` is a
        # document-wide scan on the host too, so ChatGPT rendering the finished
        # canvas full-page in the MAIN frame is a real layout — and there
        # `assistantLen` is 0 (a canvas is not a conversation turn) and `bodyLen`
        # is deliberately not counted (it would drag in the sidebar). `panelLen`
        # is the only thing left, and without it the caller's 2-cycle flatness
        # gate has nothing that moves.
        page = _Page(_reading(docPanelAffordances=True, panelLen=93159,
                              bodyLen=500_000, sources=26), [])
        done, reason, snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is True, reason
        assert snap["text_len"] == 93159, snap


class _Ctx:
    """A frame that RECORDS being evaluated. Counting is the assertion."""

    def __init__(self, url, payload):
        self.url = url
        self._payload = payload
        self.calls = []

    async def evaluate(self, js, arg=None):
        self.calls.append(js)
        return dict(self._payload)


class _Page(_Ctx):
    def __init__(self, payload, frames):
        super().__init__("https://chatgpt.com/c/6a74e262-aedc-83ea-bdd0-f5ac61629bea",
                         payload)
        self.main_frame = self
        self.frames = [self] + list(frames)


def _reading(**over):
    base = {"hasStop": False, "thoughtFor": False, "researchDone": False,
            "completedChip": False, "docPanelAffordances": False,
            "assistantLen": 0, "panelLen": 0, "bodyLen": 0,
            "sources": 0, "steps": 0, "vw": SHIM_VW, "vh": SHIM_VH}
    base.update(over)
    return base


def _live_inventory():
    """The literal frame list the run recorded, with the live readings."""
    sentinel = _Ctx("https://chatgpt.com/backend-api/sentinel/frame.html?sv=20260423af3c",
                    _reading())
    connector = _Ctx("https://connector-openai-deep-research.web-sandbox."
                     "oaiusercontent.com/?app=chatg", _reading())
    surface = _Ctx("about:blank",
                   _reading(docPanelAffordances=True, completedChip=True,
                            bodyLen=93159, sources=50, steps=26))
    page = _Page(_reading(steps=1), [sentinel, connector, surface])
    return page, sentinel, connector, surface


class TestTheDetectorVisitsTheFrameTheSurfaceIsIn:

    def test_the_about_blank_frame_is_actually_evaluated(self):
        page, sentinel, connector, surface = _live_inventory()
        asyncio.run(research.detect_completion_chatgpt(page))
        # The bug was never about the verdict logic — it was that this call
        # never happened. Assert the call, not the answer.
        assert surface.calls, "the about:blank frame was never evaluated"

    def test_the_connector_shell_no_longer_ends_the_walk(self):
        page, sentinel, connector, surface = _live_inventory()
        asyncio.run(research.detect_completion_chatgpt(page))
        assert connector.calls and surface.calls, (
            "the walk stopped at the first URL match again"
        )

    def test_the_run_is_now_called_complete(self):
        page, _s, _c, _surface = _live_inventory()
        done, reason, snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is True, reason
        assert snap["text_len"] > 0
        assert snap["sources"] == 50

    def test_the_reason_names_the_context_that_supplied_the_marker(self):
        page, _s, _c, _surface = _live_inventory()
        _done, reason, _snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert "ctx=about:blank" in reason, reason

    def test_a_frame_that_throws_does_not_take_the_others_down(self):
        page, _s, connector, surface = _live_inventory()

        async def _boom(js, arg=None):
            raise RuntimeError("cross-origin")
        connector.evaluate = _boom
        done, _reason, snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is True
        assert snap["sources"] == 50

    def test_an_irrelevant_frame_is_not_visited(self):
        # The sentinel frame is same-site but is not a surface candidate; a walk
        # that asks every frame on the page would be a different, sloppier fix.
        page, sentinel, _c, _s = _live_inventory()
        asyncio.run(research.detect_completion_chatgpt(page))
        assert not sentinel.calls


class TestAStopButtonAnywhereStillVetoes:

    def test_a_stop_button_in_the_surface_frame_beats_a_done_marker(self):
        page, _s, _c, surface = _live_inventory()
        surface._payload = _reading(hasStop=True, docPanelAffordances=True,
                                    bodyLen=93159, sources=50)
        done, reason, _snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is False
        assert "stop_btn_present" in reason

    def test_a_stop_button_in_the_main_frame_still_vetoes(self):
        page, _s, _c, _surface = _live_inventory()
        page._payload = _reading(hasStop=True)
        done, _reason, _snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is False


class TestWhatAFrameIsNotAllowedToDecideOnItsOwn:
    """Widening the reach is where a FALSE DONE could be introduced. A false done
    publishes a report, so these are the load-bearing negative tests."""

    def test_the_loose_research_complete_text_does_not_count_from_a_frame(self):
        # The canvas frame holds the report PROSE. A report about research may
        # well contain "research complete"; the main frame's chrome will not.
        page, _s, _c, surface = _live_inventory()
        surface._payload = _reading(researchDone=True, bodyLen=93159)
        done, _reason, _snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is False

    def test_the_same_loose_text_still_counts_from_the_main_frame(self):
        page, _s, _c, surface = _live_inventory()
        surface._payload = _reading()
        page._payload = _reading(researchDone=True)
        done, reason, _snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is True
        assert "research_complete" in reason

    def test_a_tiny_frame_may_not_call_the_run_finished_from_its_geometry(self):
        # Geometry inside a frame is FRAME-relative: in a 200x100 telemetry blank
        # every element is right-anchored and half the viewport tall, so a stray
        # button labelled Download would otherwise read as a finished document.
        page, _s, _c, surface = _live_inventory()
        surface._payload = _reading(docPanelAffordances=True, vw=200, vh=100,
                                    bodyLen=400)
        done, _reason, _snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is False

    def test_a_real_sized_frame_may(self):
        page, _s, _c, surface = _live_inventory()
        surface._payload = _reading(docPanelAffordances=True,
                                    vw=research._CHATGPT_FRAME_SURFACE_MIN_VW,
                                    vh=research._CHATGPT_FRAME_SURFACE_MIN_VH,
                                    bodyLen=93159)
        done, _reason, _snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is True

    def test_the_anchored_chip_counts_from_a_frame_at_any_size(self):
        # `completedChip` carries a duration or a citation count — it cannot be
        # produced by prose, so it needs no surface gate.
        page, _s, _c, surface = _live_inventory()
        surface._payload = _reading(completedChip=True, vw=200, vh=100)
        done, _reason, _snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert done is True

    def test_the_main_frame_body_does_not_inflate_the_snapshot(self):
        # The main frame's body innerText includes the sidebar's conversation
        # list. Counting it would give the flatness gate a number that moves for
        # reasons having nothing to do with this run.
        page, _s, _c, surface = _live_inventory()
        page._payload = _reading(bodyLen=500_000)
        surface._payload = _reading(completedChip=True, bodyLen=1234)
        _done, _reason, snap = asyncio.run(research.detect_completion_chatgpt(page))
        assert snap["text_len"] == 1234


class TestNoEvaluableContextIsNotDone:

    def test_a_page_that_cannot_be_evaluated_reports_an_error_not_a_verdict(self):
        class _Dead:
            url = "https://chatgpt.com/c/x"
            frames = []

            def __init__(self):
                self.main_frame = self

            async def evaluate(self, js, arg=None):
                raise RuntimeError("target closed")
        done, reason, snap = asyncio.run(research.detect_completion_chatgpt(_Dead()))
        assert done is False
        assert "detect_error" in reason
        assert snap == {}


class TestOnePayloadForEveryContext:

    def test_the_detector_evaluates_one_shared_constant_and_no_inline_script(self):
        # The asymmetric-payload half of the bug, pinned as a property of the
        # source rather than a comment. Two payloads is how `completedChip` and
        # `docPanelAffordances` came to exist on the host path and not the frame
        # path. Walking the AST is what makes this checkable: an inline literal
        # would be a second payload no matter how similar its text.
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(research.detect_completion_chatgpt)))
        names, literals = [], []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "evaluate" and node.args):
                arg = node.args[0]
                if isinstance(arg, ast.Name):
                    names.append(arg.id)
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    literals.append(arg.value[:60])
        assert literals == [], f"an inline probe came back: {literals}"
        assert names == ["_CHATGPT_DONE_PROBE_JS"], names

    def test_the_shared_probe_runs_against_a_frame_as_well_as_the_page(self):
        # And the constant really is handed to BOTH kinds of context — the two
        # readings must be produced by the identical script.
        page, _s, _c, surface = _live_inventory()
        asyncio.run(research.detect_completion_chatgpt(page))
        assert page.calls == [PROBE]
        assert surface.calls == [PROBE]

    def test_the_probe_carries_every_marker(self):
        for marker in ("thoughtFor", "researchDone", "completedChip",
                       "docPanelAffordances", "panelLen"):
            assert marker in PROBE, marker


class TestEverySiblingReachesTheSameContexts:
    """The four consumers that carried private copies of the URL substrings."""

    def _inventory(self):
        page, sentinel, connector, surface = _live_inventory()
        return page, surface

    def test_the_shared_helper_includes_the_about_blank_frame(self):
        page, surface = self._inventory()
        assert surface in research._chatgpt_surface_frame_targets(page)

    def test_the_shared_helper_starts_with_the_page_itself(self):
        page, _surface = self._inventory()
        assert research._chatgpt_surface_frame_targets(page)[0] is page

    def test_the_shared_helper_excludes_unrelated_same_site_frames(self):
        page, _surface = self._inventory()
        urls = [getattr(t, "url", "") for t in
                research._chatgpt_surface_frame_targets(page)[1:]]
        assert not any("sentinel" in u for u in urls), urls

    def test_the_extraction_tier_reaches_the_same_contexts(self):
        # `_chatgpt_dr_frame_targets` fed the HTML→MD tiers. Its own substring
        # copy is why the 2026-08-06 run fell all the way to a CUA download for a
        # report that was sitting in a frame.
        page, surface = self._inventory()
        assert surface in research._chatgpt_dr_frame_targets(page)

    def test_the_helper_is_bounded(self):
        page, _surface = self._inventory()
        page.frames = [page] + [_Ctx("about:blank", _reading()) for _ in range(60)]
        assert len(research._chatgpt_surface_frame_targets(page)) <= 21

    @pytest.mark.parametrize("fn_name", [
        "verify_chatgpt_generating",
        "scrape_progress_chatgpt",
    ])
    def test_the_poll_and_scrape_paths_no_longer_carry_their_own_filter(self, fn_name):
        # Asserting the CONDITION, not an identifier: neither function may still
        # contain the substring test that skipped the surface.
        import inspect
        src = inspect.getsource(getattr(research, fn_name))
        assert '"deep_research" in src' not in src, fn_name
        assert "_chatgpt_surface_frame_targets" in src, fn_name
