"""The 2026-08-06 panel opener: it pressed the agent's own report, twelve times.

    [12:52:20] DOM clicked but neither panel nor inline drawer verified — miss #1
               (anchor=global label="Complex reasoning")
    ... eleven more, through 13:11:11

"Complex reasoning" is not a control. It is a MARKDOWN TABLE CELL in the report
ChatGPT produced for this very run:

    documents/chatgpt.md:574
      | Complex reasoning | 2–3 | 4 | 5 vendor-intended | 4–5 model-dependent |

and the same opener pressed "Small reasoning safety classifier" five times in the
05:35 run — also a table cell, in that run's report.

WHY IT MATCHED. `STATUS_LINE` is `^(?:[\\w.+-]{1,12}\\s+)?(?:thinking|reasoning|
researching)\\b`. The optional prefix was written for "Pro thinking"; it accepts
ANY token up to 12 characters, so "Complex reasoning" qualifies, and at 17 chars
it clears the 60-char leaf cap. `hitScore` ranks a bare status line 3.2 — above
verb+count — so once the live strip was gone, a cell of the report was the
top-ranked hit on the whole document.

WHY IT NEVER STOPPED. Phase 1 has capped panel re-opens at 3 since #913
(`_panel_reopens`), and Claude P2 has the same budget — visible in this very log
as "click budget 1/3" at 12:41:34. ChatGPT P2 was the only re-opener in the file
with no ceiling at all. Its one stand-down was keyed on the anchor's label
reading "research complete", a test that by construction cannot fire when the
anchor is the wrong node.

⭐ The exclusion goes in `findHitsIn`, which every pass calls — not in the pass
that misbehaved. The structural pass already refuses composer/header/nav
subtrees; passes 1 and 2 refused nothing, and that asymmetry is the shape this
file keeps producing.

The JS is EXECUTED. A source assertion cannot tell a filter that runs from one
that is merely present.
"""
from __future__ import annotations

import pytest

import research
from _domshim import el, js_constant, run_js

_JS = js_constant(research._open_chatgpt_activity_panel, "JS")

# Verbatim from the two runs' own reports.
CELL_PM = "Complex reasoning"
CELL_AM = "Small reasoning safety classifier"
LIVE_STRIP = "Pro thinking"


def _open(spec, skip_structural=False):
    return run_js(spec, _JS, skip_structural)["ret"]


def _report_table(cell_text):
    """The rendered report body, with the offending cell in a real table."""
    return el("div", {"class": "markdown prose", "w": "700", "h": "900"}, kids=[
        el("table", {"w": "680", "h": "300"}, kids=[
            el("tr", {"w": "680", "h": "40"}, kids=[
                el("td", {"w": "200", "h": "40"}, cell_text),
                el("td", {"w": "80", "h": "40"}, "2-3"),
            ]),
        ]),
    ])


def _live_strip():
    """The real anchor: a short interactive row carrying the tier-prefixed
    shimmer wording. This is what opened the panel at 12:16:40."""
    return el("div", {"role": "button", "w": "180", "h": "24"}, LIVE_STRIP)


class TestTheReportIsNotAControl:

    @pytest.mark.parametrize("cell", [CELL_PM, CELL_AM])
    def test_a_table_cell_of_the_report_is_never_pressed(self, cell):
        res = _open(el("body", kids=[_report_table(cell)]))
        assert res["found"] is False, res
        assert not res.get("clicked")

    def test_the_regex_still_matches_it_so_the_exclusion_is_what_saves_us(self):
        # If the matcher had simply stopped matching, the test above would pass
        # for the wrong reason and the fix would be untested. Same text, out of
        # the table and out of the prose container, must still be a candidate.
        res = _open(el("body", kids=[
            el("div", {"role": "button", "w": "180", "h": "24"}, CELL_PM),
        ]))
        assert res["found"] is True, res

    def test_prose_outside_a_table_is_refused_too(self):
        res = _open(el("body", kids=[
            el("div", {"class": "markdown", "w": "700", "h": "900"}, kids=[
                el("p", {"w": "680", "h": "24"}, CELL_PM),
            ]),
        ]))
        assert res["found"] is False, res

    def test_a_link_is_never_pressed(self):
        # Pressing an <a> navigates — the 2026-08-05 sidebar-drift lesson,
        # applied to this walker for the first time.
        res = _open(el("body", kids=[
            el("a", {"href": "/c/6a72ce1e", "w": "200", "h": "24"}, LIVE_STRIP),
        ]))
        assert res["found"] is False, res

    def test_the_diagnostic_counts_what_it_refused(self):
        res = _open(el("body", kids=[_report_table(CELL_PM)]))
        assert res.get("prose", 0) >= 1, res


class TestTheLiveStripStillWins:
    """The exclusion must not cost the path that has actually worked."""

    def test_the_strip_is_found_with_the_report_on_the_same_page(self):
        res = _open(el("body", kids=[_report_table(CELL_PM), _live_strip()]))
        assert res["found"] is True, res
        assert LIVE_STRIP in (res.get("label") or "")

    def test_the_strip_wins_even_when_the_report_comes_second(self):
        res = _open(el("body", kids=[_live_strip(), _report_table(CELL_PM)]))
        assert res["found"] is True, res
        assert LIVE_STRIP in (res.get("label") or "")

    def test_a_completed_strip_inside_the_report_container_still_counts(self):
        # Only the two WEAKEST tiers are refused inside the prose container. A
        # completed strip carries a duration; prose cannot fake that, and
        # refusing it would break the end-of-phase source panel.
        res = _open(el("body", kids=[
            el("div", {"class": "markdown", "w": "700", "h": "900"}, kids=[
                el("div", {"role": "button", "w": "300", "h": "24"},
                   "Research completed in 8m · 17 citations"),
            ]),
        ]))
        assert res["found"] is True, res

    def test_a_live_ellipsis_line_inside_the_report_container_still_counts(self):
        res = _open(el("body", kids=[
            el("div", {"class": "markdown", "w": "700", "h": "900"}, kids=[
                el("div", {"role": "button", "w": "300", "h": "24"},
                   "Structuring a security research report..."),
            ]),
        ]))
        assert res["found"] is True, res


class TestTheStandDown:
    """Pure Python — the polarity of when the poller gives up."""

    def test_a_first_miss_keeps_trying(self):
        p = {"chatgpt_panel_click_misses": 1}
        assert research._chatgpt_panel_stand_down_reason(p, CELL_PM) == ""

    def test_the_same_element_twice_in_a_row_stands_down(self):
        p = {"chatgpt_panel_click_misses": 1}
        assert research._chatgpt_panel_stand_down_reason(p, CELL_PM) == ""
        reason = research._chatgpt_panel_stand_down_reason(p, CELL_PM)
        assert reason and CELL_PM in reason, reason

    def test_a_different_element_each_time_is_bounded_by_the_budget(self):
        p = {}
        labels = ["one", "two", "three", "four", "five"]
        tried = 0
        for i, lbl in enumerate(labels):
            if research._chatgpt_panel_stand_down_reason(p, lbl):
                break
            tried += 1
            p["chatgpt_panel_click_misses"] = i + 1
        assert tried <= research._CHATGPT_PANEL_CLICK_BUDGET, (
            f"{tried} presses before standing down — the run made twelve"
        )

    def test_the_budget_counts_presses_not_empty_cycles(self):
        # An early cycle where the walker found NO candidate is benign: the
        # strip has simply not rendered yet. Budgeting those would stop the
        # poller before the panel ever exists.
        p = {"chatgpt_panel_dom_misses": 9, "chatgpt_panel_click_misses": 0}
        assert research._chatgpt_panel_stand_down_reason(p, "") == ""

    def test_a_blank_label_does_not_count_as_a_repeat(self):
        # Two cycles that pressed nothing identifiable must not be read as
        # "the same element twice".
        p = {}
        assert research._chatgpt_panel_stand_down_reason(p, "") == ""
        assert research._chatgpt_panel_stand_down_reason(p, "") == ""

    def test_the_reason_names_the_element_so_the_log_is_actionable(self):
        p = {"chatgpt_panel_click_misses": research._CHATGPT_PANEL_CLICK_BUDGET}
        reason = research._chatgpt_panel_stand_down_reason(p, CELL_PM)
        assert "presses verified nothing open" in reason, reason


class TestTheCallerHonoursIt:

    def test_the_poller_gates_the_reopen_block_on_the_stand_down(self):
        import inspect
        src = inspect.getsource(research.poll_all_agents_round_robin)
        assert 'not p.get("chatgpt_panel_stand_down")' in src
        assert "_chatgpt_panel_stand_down_reason(" in src

    def test_a_verified_open_clears_the_press_history(self):
        import inspect
        src = inspect.getsource(research.poll_all_agents_round_robin)
        assert src.count('p["chatgpt_panel_click_misses"] = 0') == 3, (
            "every branch that records a verified-open must clear the budget, "
            "or one good cycle leaves the phase one press from standing down"
        )

    def test_the_miss_line_names_the_element_it_pressed(self):
        import inspect
        src = inspect.getsource(research.poll_all_agents_round_robin)
        i = src.index("DOM clicked but neither panel nor inline")
        block = src[i:i + 700]
        assert "clickedTag=" in block, (
            "twelve presses were logged without ever naming the element, and "
            "the element was the whole story"
        )
        assert "frame=" in block
