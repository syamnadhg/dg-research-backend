"""#279 — Claude's live scraper was reading the column, not the panel.

⛔⛔ MEASURED ON THE 2026-09-03 RUN. Claude's report was WHOLE — 60,058
characters extracted — and this scraper saw 4,559 and one URL. On the same run
ChatGPT saw 87,949 of 89,816 and Gemini 103,773 of 106,497. Only Claude reads a
container it identifies BY NAME, and Claude is the one that writes into an
artifact panel while the scraper reads the chat column.

⛔⛔ AND THE ONE LINK IT REPORTED WAS AN ANTHROPIC SUPPORT PAGE — the link the
owner asked about — because that was the only link in the column it was reading.
A reading fault, not a research fault.

⭐ THE FILE ALREADY KNEW. `_claude_artifact_panel_state` was rewritten
geometry-first in 2026-07 with the reason written down: "the claude.ai panel no
longer reliably carries artifact-panel-style class names, so class-anchored
checks can read closed while the panel is plainly open". The progress scraper
kept asking for `aside .prose` and `[class*="artifact-panel"]` for two more
months. Same gates now, in the place that measures.

⛔ AND THREE MORE WHOLE-URL FILTERS HID HERE. They asked
`!a.href.includes('claude.')`, which names no host: `anthropic.com` does not
contain "claude.", so every Anthropic page passed, while a genuine source whose
path reads `claude.html` was dropped. Spelled differently enough from the nine
sites fixed the same day that a search for `claude.ai` never found them.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402
from _domshim import el, evaluate_js, run_js  # noqa: E402

# Shim viewport, which the gates are expressed against.
VW, VH = 1440, 900


def _scrape(*kids):
    return run_js(el("body", {"w": str(VW), "h": str(VH)}, "", list(kids)),
                  evaluate_js(research.scrape_progress_claude,
                              contains="printed_sources"))["ret"]


def _panel(text, kids=(), w=700, x=740, h=800, y=40):
    """A right-docked panel: flush right, past 22% of the viewport, tall."""
    return el("div", {"w": str(w), "h": str(h), "x": str(x), "y": str(y)}, text, list(kids))


def _column(text, kids=()):
    """The chat column — centred, so it fails the flush-right gate."""
    return el("div", {"class": "font-claude-message", "w": "800", "h": "800",
                      "x": "300", "y": "40"}, text, list(kids))


def _link(href):
    return el("a", {"href": href, "w": "200", "h": "20", "x": "760", "y": "300"}, "src")


REPORT = ("The measured effect is large and consistent across the whole cohort. " * 30)


class TestTheTextItMeasures:
    def test_the_panels_report_is_measured_not_the_columns_preview(self):
        """⛔⛔ THE 2026-09-03 NUMBERS. A short chat-column preview beside a whole
        report in the panel — the scraper reported the preview."""
        got = _scrape(_column("Here is a short preview of the research."),
                      _panel(REPORT))
        assert got["partial_text_len"] >= len(REPORT) - 5, got["partial_text_len"]

    def test_it_can_only_raise_the_number(self):
        """The panel is a MAX beside the three named containers, not a
        replacement, so a run where nothing right-docked exists measures exactly
        what it measured before."""
        long_column = "x " * 4000
        got = _scrape(_column(long_column))
        assert got["partial_text_len"] >= 7000

    def test_the_left_navigation_is_not_the_panel(self):
        """⛔ The nav is tall and full of text. It fails the left gate, and the
        nav-marker rule is the second line of defence — `_read_claude_artifact_panel`
        once returned 5,906 characters of "New chat / Search / Chats / Projects /
        Recents" for exactly this reason."""
        nav = el("aside", {"w": "288", "h": "860", "x": "0", "y": "20"},
                 "New chat\nSearch\nChats\nProjects\nRecents\nStarred\n" + REPORT)
        got = _scrape(nav, _column("preview"))
        assert got["panel_open"] is False
        assert got["partial_text_len"] < 100

    def test_a_wide_content_wrapper_beside_an_expanded_sidebar_is_not_the_panel(self):
        """⛔ The false-open that geometry alone lets through: with the sidebar
        expanded, the main content wrapper is flush right, tall, and starts past
        22% of the viewport. The width cap and the chat-marker test are what
        reject it — the artifact panel never contains the conversation."""
        wrapper = el("div", {"w": "1152", "h": "860", "x": "288", "y": "20"}, "",
                     [_column(REPORT)])
        got = _scrape(wrapper)
        assert got["panel_open"] is False


class TestEachGateOnItsOwn:
    """⛔⛔ A FIXTURE REJECTED BY FIVE GATES MEASURES NONE OF THEM. The first draft
    of this file used realistic pages — a nav, a wrapper — and every gate mutant
    survived, because removing any ONE still left four others saying no. Each
    fixture below is rejected by exactly one gate."""

    def test_a_wide_centred_card_is_not_the_panel(self):
        """Only the flush-right gate rejects this: width, left, height and the
        chat-marker test all pass. Without it the chat column itself qualifies."""
        centred = el("div", {"w": "700", "h": "800", "x": "400", "y": "40"}, REPORT)
        assert _scrape(centred)["panel_open"] is False

    def test_a_right_docked_container_holding_the_conversation_is_not_the_panel(self):
        """Only the chat-marker test rejects this — it passes every geometric
        gate. The artifact panel never contains the conversation."""
        wrapper = el("div", {"w": "700", "h": "800", "x": "740", "y": "40"}, "",
                     [el("div", {"class": "font-claude-message", "w": "600", "h": "700",
                                 "x": "760", "y": "60"}, REPORT)])
        assert _scrape(wrapper)["panel_open"] is False

    def test_a_container_wider_than_three_quarters_of_the_viewport_is_not_the_panel(self):
        """Only the width cap rejects this: flush right, starts past 22% of the
        viewport, tall, no chat markers. The real panel is about half the screen."""
        too_wide = el("div", {"w": "1123", "h": "800", "x": "317", "y": "40"}, REPORT)
        assert _scrape(too_wide)["panel_open"] is False

    def test_a_short_right_docked_element_is_not_the_panel(self):
        """Only the height gate rejects this — a toast or a dialog docked right
        would otherwise outscore the panel whenever it holds more text."""
        toast = el("div", {"w": "700", "h": "200", "x": "740", "y": "40"}, REPORT)
        assert _scrape(toast)["panel_open"] is False

    def test_the_left_gate_is_live_at_the_automation_viewport_and_not_at_this_one(self):
        """⛔⛔ RECORDED BECAUSE A MUTANT REMOVING THE LEFT GATE SURVIVED, and the
        reason is arithmetic rather than a missing guard.

        Flush-right means `left = right - width >= (vw - 40) - width`. For `left`
        to fall under `0.22·vw` the element must be wider than `0.78·vw - 40`,
        which the width cap `0.75·vw` already forbids — whenever
        `0.78·vw - 40 >= 0.75·vw`, i.e. `vw >= 1333`.

        The shim runs at 1440, so the gate cannot fire here and no fixture can
        make it. The automation viewport is 1280×800, where it CAN. The gate is
        load-bearing in production and untestable in this harness, which is a
        limitation of the harness — not a redundant gate to delete."""
        def left_gate_can_fire(vw):
            return 0.78 * vw - 40 < 0.75 * vw
        assert left_gate_can_fire(1280) is True
        assert left_gate_can_fire(VW) is False


class TestTheLinksItCollects:
    def test_a_source_cited_only_in_the_panel_is_collected(self):
        """The report lives in the panel, so every link the report cites lives
        there too — and no selector in this scraper could reach it."""
        got = _scrape(_panel(REPORT, [_link("https://www.nature.com/articles/x")]))
        assert got["source_urls"] == ["https://www.nature.com/articles/x"]

    def test_the_anthropic_support_page_no_longer_walks_through(self):
        """⛔⛔ THE OWNER'S LINK, AND THE FILTER IT WALKED THROUGH.
        `!a.href.includes('claude.')` names no host — `anthropic.com` does not
        contain the string "claude." — so every Anthropic page passed three
        separate sweeps."""
        got = _scrape(_panel(REPORT, [
            el("div", {"class": "tool-result", "w": "600", "h": "100", "x": "760", "y": "200"}, "",
               [_link("https://support.anthropic.com/en/articles/1")]),
            _link("https://www.nature.com/articles/x"),
        ]))
        assert got["source_urls"] == ["https://www.nature.com/articles/x"]

    def test_a_real_source_whose_path_says_claude_is_kept(self):
        """⛔ The same filter's other direction. A page ABOUT Claude is an ordinary
        source, and a whole-URL substring test deleted it."""
        got = _scrape(_panel(REPORT, [_link("https://www.theverge.com/claude.html")]))
        assert got["source_urls"] == ["https://www.theverge.com/claude.html"]

    def test_a_source_the_platform_tagged_is_kept(self):
        got = _scrape(_panel(REPORT, [_link("https://docs.nvidia.com/g?utm_source=chatgpt.com")]))
        assert got["source_urls"] == ["https://docs.nvidia.com/g?utm_source=chatgpt.com"]


def test_no_sweep_in_this_scraper_still_tests_a_platform_name_against_a_whole_url():
    """⛔⛔ THE GUARD THAT WOULD HAVE FOUND THESE THREE. The sweep written the same
    day for the other nine sites searched for `claude\\.ai` and never matched
    `'claude.'`, so a filter naming no host survived in the one scraper whose
    misread started this."""
    js = evaluate_js(research.scrape_progress_claude, contains="printed_sources")
    import re
    code = re.sub(r"(?m)^\s*//.*$", "", js)
    assert "includes('claude." not in code
    assert "includes('anthropic" not in code
