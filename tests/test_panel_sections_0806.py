"""sections=0 on every sample of the 2026-08-06 run — and the reason is not what
it looked like.

    [P2-panel-dbg] urls/steps/sections/searches=(26, 3, 0, 26) headings=0 more=7
    node=ASIDE|… textlen=1653 anchors=26 rows=0

The obvious reading is "the selectors match nothing, fix the selectors". Replaying
the captured panel settles it the other way: the panel contains no h1-h6 and no
role="heading" at any level. It is a list of activity rows, not a report outline,
so zero headings is the CORRECT count and `dbg_headings` was added precisely to
say so.

⭐ But "no headings" is not "no structure". The captured DOM carries two group
labels, and they are exactly what a reader would call the panel's sections:

    <div class="text-token-text-secondary mb-3 text-[1.05rem] font-medium">
      …<span class="min-w-0 truncate">Pro thinking</span>
    <div class="… font-medium">…<span>Sources</span> · <span>168</span>

So the panel reported no structure at all while carrying two labels describing it.
The heading scan is untouched; this adds the labels as a second source.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, js_constant, run_js, spec_from_html, stamp_panel_geometry  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "panels"
JS = js_constant(research.scrape_chatgpt_activity_panel_tracking, "JS")


def _walk(name):
    raw = (FIXTURES / name).read_text(encoding="utf-8", errors="replace")
    spec = spec_from_html(raw)
    stamp_panel_geometry(spec)
    return run_js(el("body", kids=[spec]), JS)["ret"]


GROWN = "chatgpt_activity_panel_grown_20260806.html"
COLLAPSED = "chatgpt_activity_panel_collapsed_20260806.html"


class TestZeroHeadingsWasTheTruth:

    @pytest.mark.parametrize("name", [GROWN, COLLAPSED])
    def test_the_capture_really_has_no_heading_element(self, name):
        raw = (FIXTURES / name).read_text(encoding="utf-8", errors="replace")
        assert re.search(r"<h[1-6][\s>]", raw) is None
        assert 'role="heading"' not in raw

    @pytest.mark.parametrize("name", [GROWN, COLLAPSED])
    def test_the_diagnostic_still_reports_the_raw_heading_count(self, name):
        # "0 headings present" and "0 survived the length filter" are different
        # facts with opposite fixes; this is what keeps them distinguishable.
        assert _walk(name)["dbg_headings"] == 0


class TestThePanelNowReportsItsOwnGroups:

    def test_the_grown_panel_no_longer_reports_no_structure(self):
        sections = _walk(GROWN)["sections"]
        assert sections, "the panel still reports no structure at all"

    def test_the_thinking_group_is_named(self):
        assert "Pro thinking" in _walk(GROWN)["sections"]

    def test_the_sources_group_is_named_with_its_count(self):
        sections = _walk(GROWN)["sections"]
        assert any(s.startswith("Sources") for s in sections), sections

    def test_the_collapsed_panel_reports_its_group_too(self):
        # The early panel shape, before any source row exists.
        assert "Pro thinking" in _walk(COLLAPSED)["sections"]

    def test_the_source_rows_are_not_mistaken_for_groups(self):
        # 37 rows in the capture; if the row markup matched, sections would be
        # dominated by page titles and the label would be lost in them.
        sections = _walk(GROWN)["sections"]
        assert len(sections) <= 5, sections
        assert not any("http" in s for s in sections), sections

    def test_sections_are_deduplicated(self):
        sections = _walk(GROWN)["sections"]
        assert len(set(sections)) == len(sections), sections

    def test_the_bound_still_holds(self):
        assert len(_walk(GROWN)["sections"]) <= 20


class TestARealHeadingWouldStillWin:
    """The addition is additive — a future build that renders headings must not
    lose them to the new source.

    Both fixtures GROW the real capture rather than hand-building a panel: the
    walker's root selection is part of what is under test, and a minimal
    stand-in is not selected as a panel at all, so a test built on one would
    pass or fail for reasons having nothing to do with sections."""

    def _grown_with(self, injected):
        raw = (FIXTURES / GROWN).read_text(encoding="utf-8", errors="replace")
        marker = "</ul>"
        assert marker in raw
        spec = spec_from_html(raw.replace(marker, marker + injected, 1))
        stamp_panel_geometry(spec)
        return run_js(el("body", kids=[spec]), JS)["ret"]

    def test_a_heading_is_still_collected(self):
        out = self._grown_with("<h2>Executive summary</h2>")
        assert "Executive summary" in out["sections"], out["sections"]
        assert out["dbg_headings"] == 1

    def test_a_heading_does_not_displace_the_group_labels(self):
        out = self._grown_with("<h2>Executive summary</h2>")
        assert "Pro thinking" in out["sections"], out["sections"]

    def test_a_long_label_is_refused(self):
        # The same bounds the heading scan applies. A paragraph that happens to
        # carry the class is not a section name.
        long_label = '<div class="font-medium">' + ("word " * 40) + "</div>"
        out = self._grown_with(long_label)
        assert not any(s.startswith("word word") for s in out["sections"]), out["sections"]

    def test_a_label_carrying_a_url_is_refused(self):
        out = self._grown_with(
            '<div class="font-medium">https://docs.nvidia.com/nemoclaw</div>')
        assert not any("http" in s for s in out["sections"]), out["sections"]
