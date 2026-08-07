"""The source-list ceiling, and the two sides that have to agree about it.

The 2026-08-06 run's ChatGPT activity panel held 142 distinct non-platform URLs
in ONE sample — it went from 3 anchors to 157 in a single 45-second tick — and
every walker truncated its own sample to 50 before the cross-sample union ever
saw it. 92 sources were dropped at the door, permanently, and the card read
"50 sources" for the rest of the run.

⛔ The obvious fix was the wrong one. "Keep the newest 50" is measurably WORSE on
this exact panel: the head is the topic's primary evidence
(github.com/NVIDIA/NemoClaw, docs.nvidia.com/nemoclaw/…,
github.com/NVIDIA/OpenShell/releases) and the tail is where the search drifted
(goodreads "august releases", a games round-up, a book blog). Document order in
this panel is roughly relevance order, so head-first is right and it was the
CEILING that was wrong.

The ceiling now lives in `_SOURCE_LIST_CAP`. The JavaScript walkers cannot import
a Python constant, so they carry the literal — and this file is the only thing
keeping the two sides in step.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, run_js, spec_from_html, stamp_panel_geometry  # noqa: E402

SRC = Path(research.__file__).read_text(encoding="utf-8")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "panels"
CAP = research._SOURCE_LIST_CAP


def test_the_ceiling_is_above_every_panel_this_project_has_measured():
    # 142 distinct URLs in the 2026-08-06 capture. A ceiling at or below that is
    # the defect, restated.
    assert CAP > 142, CAP


def test_the_ceiling_is_still_a_ceiling():
    # Unbounded would be the other failure: a pathological panel must not be
    # able to grow a Firestore document without limit.
    assert CAP <= 1000, CAP


class TestBothSidesCarryTheSameNumber:

    def _js_source_slices(self):
        """Every `slice(0, N)` applied to a source list, with its N."""
        out = []
        for m in re.finditer(r"(source_urls|source_items|srcSet)\)?\.?"
                             r"[^\n]*?slice\(0,\s*(\d+)\)", SRC):
            out.append((m.group(1), int(m.group(2)), SRC[:m.start()].count("\n") + 1))
        return out

    def test_there_are_javascript_walkers_to_check(self):
        # An empty sweep would pass silently — the decorative-guard failure mode
        # this project keeps hitting.
        assert len(self._js_source_slices()) >= 10, self._js_source_slices()

    def test_every_javascript_walker_uses_the_shared_ceiling(self):
        bad = [(name, n, ln) for name, n, ln in self._js_source_slices() if n != CAP]
        assert bad == [], (
            f"these JS source caps disagree with _SOURCE_LIST_CAP={CAP}: {bad}. "
            f"A walker capped below the merge throws sources away before any "
            f"later tick can recover them."
        )

    def _py_source_slices(self):
        """Every `[:N]` applied to something named like a source list."""
        out = []
        tree = ast.parse(SRC)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
                continue
            up = node.slice.upper
            if not isinstance(up, ast.Constant) or not isinstance(up.value, int):
                continue
            seg = ast.get_source_segment(SRC, node) or ""
            if re.search(r"source_urls|source_items|srcSet|unique_urls|filtered",
                         seg):
                out.append((seg[:60], up.value, node.lineno))
        return out

    def test_no_python_site_still_carries_a_bare_number(self):
        assert self._py_source_slices() == [], (
            "these Python source caps are still literals: "
            f"{self._py_source_slices()}"
        )

    def test_the_parallel_title_list_moves_with_the_url_list(self):
        # `source_urls[i]` and `source_items[i]` are pushed together in one
        # forEach. Capping them differently pairs a url with another page's title.
        urls = [n for name, n, _ln in self._js_source_slices() if name == "source_urls"]
        items = [n for name, n, _ln in self._js_source_slices() if name == "source_items"]
        assert items, "the title list vanished — it must still be capped"
        assert set(urls) == set(items) == {CAP}


class TestTheWalkerNowSurvivesAPanelBiggerThanTheOldCeiling:
    """Executed against real captured markup, not asserted from the source.

    ⚠ HONEST NOTE ON THE FIXTURE. The decisive artefact — the 12:25 capture that
    held 142 distinct sources in one sample — was destroyed after this wave began
    (both `p2_panel_dump_*.html` files were overwritten with 100 bytes of filler
    at 18:01 by a read-only analysis run that should not have written anything).
    Its counts are recorded in the log line that dumped it:

        [12:25:28] [P2-panel-dbg] dumped panel DOM (207954 of 207959 chars,
        textlen=32841, reason=grew) — anchors=157 rows=154

    So the ROW MARKUP below is the real thing, lifted verbatim from the surviving
    05:35 capture, and only the MULTIPLICITY is synthetic: the same row shape
    repeated with distinct hrefs until the panel is larger than the old ceiling.
    That is enough to exercise the cap, the dedupe and the host filter against
    markup the page actually produced — it is not a claim about the lost capture.
    """

    CAPTURE = "chatgpt_activity_panel_grown_20260806.html"

    def _row(self, i):
        """One extra source row, in the shape the capture actually uses."""
        return (
            '<li><a target="_blank" rel="noopener" '
            'class="hover:bg-token-surface-hover flex flex-col gap-0.5 rounded-xl px-3 py-2.5" '
            f'href="https://docs.example{i}.com/nemoclaw/page?utm_source=chatgpt.com">'
            f'<div class="line-clamp-1 flex h-6 items-center gap-2 text-xs">Site {i}</div>'
            f'<div class="line-clamp-2 text-sm">Row {i} body text</div></a></li>'
        )

    def _panel(self, extra):
        """The REAL captured panel with `extra` further rows spliced into its
        own <ul>. Growing the capture rather than rebuilding it keeps every
        selector the walker uses to find and rank the panel root."""
        raw = (FIXTURES / self.CAPTURE).read_text(encoding="utf-8", errors="replace")
        marker = "</ul>"
        assert marker in raw, "the capture no longer has a source list"
        html = raw.replace(
            marker, "".join(self._row(i) for i in range(extra)) + marker, 1)
        spec = spec_from_html(html)
        stamp_panel_geometry(spec)
        return el("body", kids=[spec])

    def _walk(self, extra):
        from _domshim import js_constant
        js = js_constant(research.scrape_chatgpt_activity_panel_tracking, "JS")
        return run_js(self._panel(extra), js)["ret"]

    def test_the_capture_alone_is_under_the_old_ceiling(self):
        # Which is why it has to be grown: an unmodified capture cannot show a
        # 50-cap binding, so a test built on it would pass for the wrong reason.
        assert 30 <= len(self._walk(0)["source_urls"]) < 50

    def test_a_panel_past_the_old_ceiling_no_longer_loses_the_remainder(self):
        base = len(self._walk(0)["source_urls"])
        out = self._walk(80)
        assert len(out["source_urls"]) == base + 80 > 50, len(out["source_urls"])

    def test_the_new_ceiling_still_binds(self):
        out = self._walk(CAP + 40)
        assert len(out["source_urls"]) == CAP, len(out["source_urls"])

    def test_the_titles_stay_paired_with_their_urls(self):
        # The two arrays are pushed in one pass and capped separately; capping
        # them differently pairs a url with another page's title.
        out = self._walk(80)
        assert len(out["source_items"]) == len(out["source_urls"])
        for u, it in zip(out["source_urls"], out["source_items"]):
            assert it["url"] == u

    def test_the_head_is_what_is_kept(self):
        # The direction that was nearly reversed. In the 2026-08-06 panel the
        # head is the run's primary evidence and the tail is where the search
        # drifted, so head-first is deliberate.
        out = self._walk(CAP + 40)
        # The capture's own rows come first in document order and must survive.
        assert "nvidia" in " ".join(out["source_urls"][:5]).lower(), out["source_urls"][:5]

    def test_the_real_capture_still_parses_through_the_same_walker(self):
        # The synthetic multiplicity above must not be the only thing exercised.
        spec = spec_from_html(
            (FIXTURES / "chatgpt_activity_panel_grown_20260806.html").read_text(
                encoding="utf-8", errors="replace"))
        stamp_panel_geometry(spec)
        from _domshim import js_constant
        js = js_constant(research.scrape_chatgpt_activity_panel_tracking, "JS")
        out = run_js(el("body", kids=[spec]), js)["ret"]
        assert len(out["source_urls"]) >= 30, len(out["source_urls"])
        assert len(set(out["source_urls"])) == len(out["source_urls"])
        assert "nvidia" in " ".join(out["source_urls"][:10]).lower()
