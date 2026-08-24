"""Claude's "Gathered N sources" disclosure: press it, read it, and say what we saw.

⭐⭐ WHY, measured from this machine's own logs on 2026-08-22 rather than reasoned
about. Across `~/.super-research/logs/e2e*.log` + `backend.log`, 22 Claude runs
reached `CONFIRMED DONE`:

  * **13 of 22 recorded ZERO sources** — six of them on reports over 25,000 chars.
  * **74 of 78** `Artifact tracking:` reads returned exactly **ONE** url.
  * `walker_root=class` matched **0 of 147** times — the class-anchored primary
    selector has never once fired; the geometry fallback carries every read.
  * `didn't stick` fired **28** times against **23** `artifact panel opened`.

The panel we open is the progress CHECKLIST, its rows are not anchors, and the
walker's sweep is `a[href^="http"]` — so it finds one stray anchor and nothing
else. The panel that enumerates the sources had never been pressed.

⛔ ROW SHAPE IS NOT A PRECONDITION here, and the tests are written that way. The
conversation the owner measured had 0 sources, so whether a row is an `<a href>`
or a click-handler button — and whether the list virtualises — could not be
answered from it. Both shapes are covered below, and production REPORTS what it
found rather than assuming.

⛔ The JS is SYNCHRONOUS on purpose. `_domshim` has no `setTimeout` and `run_js`
JSON-stringifies the return, so an async page-JS body would not be executable
here at all — it could only be source-scanned, and this repo has shipped an
inverted gate that way before. Every wait, press and scroll lives in Python, and
is driven below by a fake page rather than pinned as source text.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import io

from _domshim import el, js_constant, run_js

research = importlib.import_module("research")

PROBE = js_constant(research, "_CLAUDE_SOURCES_PROBE_JS")
SCROLL = js_constant(research, "_CLAUDE_SOURCES_SCROLL_JS")
MARK = research._SR_CLICK_MARK
CLICK_VALUE = research._CLAUDE_SOURCES_CLICK_VALUE


# ── fixtures ──────────────────────────────────────────────────────────────────

def _toggle(label="Gathered 12 sources", *, disabled=False, expanded="false",
            controls=None, tag="button", aria_expanded=True):
    attrs = {}
    if aria_expanded:
        attrs["aria-expanded"] = expanded
    if disabled:
        attrs["disabled"] = ""
    if controls:
        attrs["aria-controls"] = controls
    if tag != "button":
        attrs["role"] = "button"
    return el(tag, attrs, label)


def _rows_anchor(hosts=("nature.com", "arxiv.org", "who.int")):
    return [el("li", {}, "", [el("a", {"href": f"https://{h}/x"}, h)])
            for h in hosts]


def _rows_button(titles=("Nature — gut microbiome study",
                         "arxiv.org preprint on transformers")):
    """Rows that are BUTTONS with no href — the shape we could not rule out."""
    return [el("li", {}, "", [el("button", {}, t)]) for t in titles]


def _page(toggle, rows, *, list_attrs=None, wrap_toggle_in_list=False):
    """A toggle plus the list it discloses, as siblings under one container."""
    lst = el("ol", dict({"role": "list"}, **(list_attrs or {})), "", rows)
    if wrap_toggle_in_list:
        # The pathological case: the toggle is itself a row of a list. The
        # ancestor walk must NOT choose that list as the disclosed region.
        return el("div", {}, "", [el("ol", {"role": "list"}, "",
                                     [el("li", {}, "", [toggle])]), lst])
    return el("div", {}, "", [toggle, lst])


def _probe(spec, mark=""):
    return run_js(spec, PROBE, mark)["ret"]


# ── the finder ────────────────────────────────────────────────────────────────

class TestFindingTheControl:
    def test_finds_the_measured_control_and_reads_its_count(self):
        r = _probe(_page(_toggle(), _rows_anchor()))
        assert r["found"] is True
        assert r["count"] == 12
        assert r["shape"] == "gathered"
        assert r["tag"] == "BUTTON"
        assert r["disabled"] is False

    def test_a_one_digit_count_is_read(self):
        """⛔ The capture script written to MEASURE this control demanded two
        digits, so it reported "(none found)" while `Gathered 0 sources` sat in
        the DOM. A count regex that cannot see a single digit cannot tell "no
        sources" from "no control" — the one distinction this whole path exists
        to make. Singular "source" too, which is what N==1 actually renders."""
        r = _probe(_page(_toggle("Gathered 1 source"), _rows_anchor(("who.int",))))
        assert r["found"] is True and r["count"] == 1
        # ⛔ SHAPE, not just count. Mutation caught this: with `[\d,]{2,}` the
        # bare-count FALLBACK still matched "1 source" and returned count=1, so a
        # count-only assertion passed against the very bug it was written for.
        assert r["shape"] == "gathered", (
            "the primary label regex must match a single digit itself, not lean "
            "on the fallback"
        )

    def test_zero_is_a_count_not_an_absence(self):
        r = _probe(_page(_toggle("Gathered 0 sources", disabled=True), []))
        assert r["found"] is True, "a disabled control is still a control"
        assert r["count"] == 0
        assert r["disabled"] is True

    def test_a_comma_grouped_count_is_read(self):
        r = _probe(_page(_toggle("Gathered 1,284 sources"), _rows_anchor()))
        assert r["count"] == 1284

    def test_a_checklist_row_with_the_same_words_is_not_the_control(self):
        """⚠ "Gathered N sources" also appears as a progress-CHECKLIST row — ten
        CUA readings in the corpus describe it that way. A row is an li, so
        requiring button/role=button already excludes it, and this pins that."""
        spec = el("div", {}, "", [
            el("ol", {"role": "list"}, "", [
                el("li", {}, "Research plan created"),
                el("li", {}, "Gathered 47 sources"),
                el("li", {}, "Done investigating a topic"),
            ]),
        ])
        assert _probe(spec)["found"] is False

    def test_the_bare_count_fallback_needs_a_disclosure_control(self):
        """The verb is the likeliest part of the label to rot, so a
        disclosure-shaped button labelled just "12 sources" still matches. A
        button WITHOUT aria-expanded must not — otherwise the finished report
        card and the running ticker both qualify, and neither opens a list."""
        with_expanded = _probe(_page(_toggle("12 sources"), _rows_anchor()))
        assert with_expanded["found"] is True
        assert with_expanded["shape"] == "bare-count"

        without = _probe(_page(_toggle("12 sources", aria_expanded=False),
                               _rows_anchor()))
        assert without["found"] is False

    def test_the_measured_label_outranks_the_bare_fallback(self):
        spec = el("div", {}, "", [
            _toggle("99 sources"),
            _toggle("Gathered 12 sources"),
            el("ol", {"role": "list"}, "", _rows_anchor()),
        ])
        r = _probe(spec)
        assert (r["count"], r["shape"]) == (12, "gathered")

    def test_an_aria_label_only_control_is_found(self):
        spec = el("div", {}, "", [
            el("button", {"aria-expanded": "false",
                          "aria-label": "Gathered 8 sources"}, ""),
            el("ol", {"role": "list"}, "", _rows_anchor()),
        ])
        assert _probe(spec)["count"] == 8

    def test_a_role_button_div_is_found_too(self):
        r = _probe(_page(_toggle(tag="div"), _rows_anchor()))
        assert r["found"] is True and r["tag"] == "DIV"

    def test_aria_disabled_true_disables_and_a_bare_string_does_not(self):
        """HTML semantics differ between the two and production tests both:
        the `disabled` ATTRIBUTE disables by presence, `aria-disabled` is a
        string that must equal "true"."""
        spec = el("div", {}, "", [
            el("button", {"aria-expanded": "false", "aria-disabled": "true"},
               "Gathered 0 sources"),
            el("ol", {"role": "list"}, "", []),
        ])
        assert _probe(spec)["disabled"] is True
        spec2 = el("div", {}, "", [
            el("button", {"aria-expanded": "false", "aria-disabled": "false"},
               "Gathered 5 sources"),
            el("ol", {"role": "list"}, "", _rows_anchor()),
        ])
        assert _probe(spec2)["disabled"] is False


# ── marking for a real press ──────────────────────────────────────────────────

class TestMarkingForARealPress:
    def test_an_enabled_collapsed_control_is_marked_for_playwright(self):
        """⛔ A synthetic el.click() dispatches a click event and nothing else;
        claude.ai's disclosures are React components whose trigger listens on
        pointerdown. The search happens in JS, the press in Playwright — so the
        JS's job is to STAMP, and this pins that it does."""
        out = run_js(_page(_toggle(), _rows_anchor()), PROBE, MARK)
        assert out["ret"]["marked"] is True
        assert out["clicks"] == [], "the JS must never press it itself"

    def test_a_disabled_control_is_not_marked(self):
        r = _probe(_page(_toggle("Gathered 0 sources", disabled=True), []), MARK)
        assert r["marked"] is False

    def test_an_already_open_control_is_not_marked(self):
        r = _probe(_page(_toggle(expanded="true"), _rows_anchor()), MARK)
        assert r["expanded"] is True and r["marked"] is False

    def test_no_mark_argument_means_no_stamp(self):
        r = _probe(_page(_toggle(), _rows_anchor()), "")
        assert r["marked"] is False


# ── resolving the disclosed region ────────────────────────────────────────────

class TestRegionResolution:
    def test_aria_controls_wins_when_offered(self):
        spec = el("div", {}, "", [
            _toggle(controls="src-list"),
            el("ol", {"role": "list", "id": "src-list"}, "", _rows_anchor()),
        ])
        r = _probe(spec)
        assert r["region"] == "aria-controls"
        assert r["links"] == 3

    def test_falls_back_to_the_nearest_ancestor_list(self):
        r = _probe(_page(_toggle(), _rows_anchor()))
        assert r["region"] == "ancestor-list"
        assert r["links"] == 3

    def test_the_list_the_toggle_sits_inside_is_never_the_region(self):
        """Without the `!list.contains(toggle)` guard the walk happily returns
        the list the toggle is a row of — which is the progress checklist, i.e.
        exactly the surface this whole path exists to stop reading."""
        r = _probe(_page(_toggle(), _rows_anchor(), wrap_toggle_in_list=True))
        assert r["region"] == "ancestor-list"
        assert r["links"] == 3, "it picked the checklist, not the source list"


# ── the inventory: the runtime observations the 0-source capture could not give ─

class TestInventory:
    def test_anchor_rows_yield_urls(self):
        r = _probe(_page(_toggle(), _rows_anchor()))
        assert r["links"] == 3 and r["rows"] == 3
        assert all(u.startswith("https://") for u in r["urls"])

    def test_button_rows_yield_hosts_and_never_invented_urls(self):
        """⛔ A row with no anchor gives us a DOMAIN, not a link. Synthesising
        "https://" + domain would put a fabricated url into source_urls, which
        feeds the findings cards and the user-visible source list. This file has
        already discarded 56% of a run's real sources by matching a whole url
        where it meant to match a host; inventing one is worse."""
        r = _probe(_page(_toggle(), _rows_button()))
        assert r["urls"] == [], "no anchors means no urls, ever"
        assert r["links"] == 0
        assert "arxiv.org" in r["hosts"]
        assert r["buttons"] >= 2, "the button rows are counted as buttons"
        assert r["rows"] == 2

    def test_claude_own_links_are_excluded(self):
        rows = [el("li", {}, "", [el("a", {"href": "https://claude.ai/chat/x"}, "chat")]),
                el("li", {}, "", [el("a", {"href": "https://nature.com/y"}, "nature.com")])]
        r = _probe(_page(_toggle(), rows))
        assert r["urls"] == ["https://nature.com/y"]

    def test_non_http_hrefs_are_excluded(self):
        rows = [el("li", {}, "", [el("a", {"href": "javascript:void(0)"}, "x")]),
                el("li", {}, "", [el("a", {"href": "https://who.int/z"}, "who.int")])]
        assert _probe(_page(_toggle(), rows))["links"] == 1

    def test_a_row_sample_is_captured_and_bounded(self):
        r = _probe(_page(_toggle(), _rows_anchor(tuple(f"h{i}.com" for i in range(9)))))
        assert 0 < len(r["row_sample"]) <= 5

    def test_the_scroll_box_is_reported_and_five_rows_are_not_scrollable(self):
        """The MEASURED state: at 5 rows scrollHeight == clientHeight. So "not
        scrollable" is a legitimate answer, and nothing about virtualisation can
        be inferred from a short list."""
        flat = _probe(_page(_toggle(), _rows_anchor(),
                            list_attrs={"sh": "300", "ch": "300"}))
        assert flat["scrollable"] is False
        assert (flat["scroll_h"], flat["client_h"]) == (300, 300)

        tall = _probe(_page(_toggle(), _rows_anchor(),
                            list_attrs={"sh": "2400", "ch": "400"}))
        assert tall["scrollable"] is True

    def test_a_collapsed_or_absent_region_reports_zeros_not_an_exception(self):
        spec = el("div", {}, "", [_toggle(controls="nope")])
        r = _probe(spec)
        assert r["found"] is True
        assert r["links"] == 0 and r["rows"] == 0


# ── the scroll step ───────────────────────────────────────────────────────────

class TestScrollStep:
    def test_it_advances_the_scroll_box(self):
        spec = _page(_toggle(expanded="true"), _rows_anchor(),
                     list_attrs={"sh": "2400", "ch": "400"})
        out = run_js(spec, SCROLL)
        assert out["ret"]["scrolled"] is True
        assert out["ret"]["top"] > 0

    def test_a_flat_list_reports_not_scrollable_rather_than_failing(self):
        spec = _page(_toggle(expanded="true"), _rows_anchor(),
                     list_attrs={"sh": "300", "ch": "300"})
        out = run_js(spec, SCROLL)
        assert out["ret"] == {"scrolled": False, "reason": "not-scrollable"}

    def test_no_toggle_is_reported_as_such(self):
        out = run_js(el("div", {}, "nothing here"), SCROLL)
        assert out["ret"]["reason"] == "no-toggle"


# ── the union ─────────────────────────────────────────────────────────────────

class TestClaudeSourceCount:
    """Each input is pinned SEPARATELY largest, so a mutation that drops one
    argument from the max has a test that fails. `max(a, b)` with a third
    argument nobody exercises is an untested argument."""

    def test_the_live_ticker_can_be_the_answer(self):
        assert research.claude_source_count(live=41, printed=3, toggle_label=2,
                                            vision=1) == 41

    def test_the_printed_total_can_be_the_answer(self):
        assert research.claude_source_count(live=3, printed=553, toggle_label=2,
                                            vision=1) == 553

    def test_the_toggle_label_can_be_the_answer(self):
        assert research.claude_source_count(live=3, printed=4, toggle_label=137,
                                            vision=1) == 137

    def test_the_vision_estimate_can_be_the_answer(self):
        """Folded in so the union cannot LOSE a number observed_sources was
        already carrying."""
        assert research.claude_source_count(live=3, printed=4, toggle_label=2,
                                            vision=88) == 88

    def test_all_zero_is_zero(self):
        assert research.claude_source_count() == 0

    def test_junk_and_negatives_read_as_zero_and_never_win(self):
        assert research.claude_source_count(live=None, printed="x",
                                            toggle_label=-5, vision=7) == 7
        assert research.claude_source_count(live=-9) == 0
        # ⛔ Mutation caught this: with the clamp removed, `max` still returns 0
        # whenever any sibling is 0, so a single negative proves nothing. Only an
        # all-negative call can see the clamp.
        assert research.claude_source_count(live=-9, printed=-3,
                                            toggle_label=-1, vision=-2) == 0

    def test_a_legitimate_zero_toggle_does_not_erase_a_real_count(self):
        """The measured case: a finished run whose toggle reads 0 while the
        printed total says 553. Max is the only combination that cannot drop a
        number Claude actually gave us."""
        assert research.claude_source_count(printed=553, toggle_label=0) == 553


# ── the log line, which is where the severity decision lives ──────────────────

class TestSourcesLogLine:
    def _line(self, **kw):
        return research.claude_sources_log_line(kw)

    def test_absent_is_debug(self):
        msg, lvl = self._line(outcome="absent")
        assert lvl == "DEBUG"

    def test_a_disabled_zero_toggle_is_info_not_warn(self):
        """⛔ Claude reporting zero sources is an ANSWER, not a fault, and
        `note_line` tallies WARN into the per-run meta a support bundle is
        triaged on — a benign WARN makes an ordinary run look faulty."""
        msg, lvl = self._line(outcome="disabled", count=0)
        assert lvl == "INFO"
        assert "0 sources" in msg and "not a failure" in msg

    def test_a_press_that_never_landed_is_warn(self):
        msg, lvl = self._line(outcome="press_failed", count=137, press="playwright")
        assert lvl == "WARN"
        assert "137" in msg and "never expanded" in msg

    def test_a_read_that_threw_is_warn(self):
        msg, lvl = self._line(outcome="read_failed", error="boom")
        assert lvl == "WARN" and "boom" in msg

    def test_an_opened_panel_with_rows_is_info_and_reports_what_it_found(self):
        msg, lvl = self._line(outcome="opened", count=137, rows_before=5,
                              rows_after=137, links=137, buttons=140,
                              hosts=["a.com"], region="aria-controls",
                              tag="BUTTON", shape="gathered", scrolls=4,
                              scrollable=True, scroll_h=9000, client_h=400,
                              press="playwright", urls=["https://a.com"])
        assert lvl == "INFO"
        # Every runtime observation the 0-source capture could not give us.
        for frag in ("label=137", "rows 5->137", "links=137", "buttons=140",
                     "hosts=1", "region=aria-controls", "scrollable=True",
                     "scrolls=4"):
            assert frag in msg, frag

    def test_an_opened_but_empty_panel_is_warn(self):
        msg, lvl = self._line(outcome="opened", count=137, rows_after=0,
                              urls=[], hosts=[])
        assert lvl == "WARN" and "EMPTY" in msg

    def test_every_outcome_the_reader_can_return_has_a_line(self):
        """A reader outcome with no branch here would fall through to the
        opened/already_open text and describe itself wrongly."""
        for outcome in research._CLAUDE_SOURCES_OUTCOMES:
            msg, lvl = self._line(outcome=outcome, count=1, urls=["u"])
            assert msg.startswith("[Claude]") and lvl in ("DEBUG", "INFO", "WARN")


# ── merging into the snapshot ─────────────────────────────────────────────────

class TestMergeIntoSnapshot:
    def test_it_unions_and_keeps_the_first_seen_form(self):
        snap = {"source_urls": ["https://a.com/x"], "sources": 1}
        research.merge_claude_sources(snap, ["https://a.com/x", "https://b.com/y"])
        assert snap["source_urls"] == ["https://a.com/x", "https://b.com/y"]

    def test_sources_stays_exactly_the_url_count(self):
        """`sources == len(source_urls)` is load-bearing — the FE chip disagreed
        with an empty url list the last time the two were merged."""
        snap = {"source_urls": [], "sources": 99}
        research.merge_claude_sources(snap, ["https://a.com"], label_count=137)
        assert snap["sources"] == 1
        assert snap["observed_sources"] == 137

    def test_the_label_count_lands_in_observed_and_never_in_sources(self):
        snap = {"source_urls": [], "sources": 0, "observed_sources": 0}
        research.merge_claude_sources(snap, [], label_count=553)
        assert snap["sources"] == 0
        assert snap["observed_sources"] == 553

    def test_an_existing_observed_count_is_not_lowered_by_a_smaller_label(self):
        snap = {"source_urls": [], "observed_sources": 400}
        research.merge_claude_sources(snap, [], label_count=12)
        assert snap["observed_sources"] == 400

    def test_hosts_become_a_count_and_never_urls(self):
        snap = {"source_urls": []}
        research.merge_claude_sources(snap, [], ["a.com", "b.com", "a.com"])
        assert snap["source_urls"] == []
        # ⛔ RENAMED 2026-08-24 by cross-verification. This wrote an INT to
        # `source_hosts` — the same key the ChatGPT inline-chip path carries a
        # LIST of hostnames under, which `_merge_host_chips` iterates. The two
        # never met, so nothing broke; routing a Claude snapshot through that
        # helper would have iterated an integer.
        assert snap["source_host_count"] == 2
        assert "source_hosts" not in snap, (
            "the int is back under the key the chip path uses for a list")

    def test_the_host_count_reaches_a_reader(self):
        """⭐ It was written every run and consumed by nothing — the completion
        emit and meta.json forwarded neither, and the next poll cycle overwrote
        the snapshot. A count nobody reads cannot say that the panel held eight
        domains and no links, which is the one thing it exists to say."""
        src = io.open(research.__file__, encoding="utf-8").read()
        assert '"sourceHostCount": int(_snap.get("source_host_count", 0)' in src

    def test_the_url_list_is_capped(self):
        snap = {"source_urls": []}
        research.merge_claude_sources(
            snap, [f"https://h{i}.com" for i in range(research._SOURCE_LIST_CAP + 40)])
        assert len(snap["source_urls"]) == research._SOURCE_LIST_CAP


# ── the reader, driven by a fake page ─────────────────────────────────────────

class _FakePage:
    """Answers `evaluate` the way the shim-verified JS would, so the PYTHON
    orchestration (press, wait, re-probe, scroll-accumulate) is executed rather
    than source-scanned."""

    def __init__(self, states, *, click="playwright", scroll_ok=True):
        self._states = list(states)
        self._click = click
        self.scroll_ok = scroll_ok
        self.probes = 0
        self.scrolls = 0

    def _next(self):
        s = self._states[0] if len(self._states) == 1 else self._states.pop(0)
        return s

    async def evaluate(self, js, arg=None):
        if js is SCROLL:
            self.scrolls += 1
            return {"scrolled": self.scroll_ok}
        self.probes += 1
        return self._next()

    async def click(self, sel, timeout=None):
        if self._click != "playwright":
            raise RuntimeError("no")


def _state(**kw):
    base = {"found": True, "count": 12, "shape": "gathered", "tag": "BUTTON",
            "disabled": False, "expanded": False, "marked": True,
            "region": "ancestor-list", "rows": 3, "links": 3, "buttons": 3,
            "scroll_h": 300, "client_h": 300, "scrollable": False,
            "urls": ["https://a.com", "https://b.com", "https://c.com"],
            "hosts": ["a.com", "b.com", "c.com"], "row_sample": ["a", "b", "c"]}
    base.update(kw)
    return base


def _read(page, **kw):
    return asyncio.run(research.read_claude_sources_panel(page, **kw))


class TestReadClaudeSourcesPanel:
    def test_no_control_reads_absent(self):
        r = _read(_FakePage([{"found": False}]))
        assert r["outcome"] == "absent"

    def test_a_disabled_control_reads_disabled_and_is_never_pressed(self):
        page = _FakePage([_state(count=0, disabled=True, marked=False)])
        r = _read(page)
        assert r["outcome"] == "disabled" and r["count"] == 0
        assert page.scrolls == 0

    def test_an_already_open_control_is_read_without_a_press(self):
        r = _read(_FakePage([_state(expanded=True, marked=False)]))
        assert r["outcome"] == "already_open"
        assert r["press"] == "none"

    def test_a_successful_press_reads_opened(self):
        page = _FakePage([_state(), _state(expanded=True), _state(expanded=True)])
        r = _read(page)
        assert r["outcome"] == "opened"
        assert r["press"] == "playwright"
        assert r["links"] == 3

    def test_a_press_that_never_expands_reads_press_failed(self):
        """⭐ "It opened" is read from the control's OWN aria-expanded, never
        from "rows came back". #914 paid for that on this exact panel: a flag
        inferred from "the scrape returned data" lied open for a panel the CUA
        had closed, and the re-click was skipped forever. So a page that keeps
        handing back rows while staying collapsed must still read as failed."""
        page = _FakePage([_state(expanded=False)])
        r = _read(page)
        assert r["outcome"] == "press_failed"
        assert r["count"] == 12, "the label is still reported"

    def test_a_control_the_js_could_not_stamp_is_not_claimed_as_pressed(self):
        page = _FakePage([_state(marked=False)])
        r = _read(page)
        assert r["outcome"] == "press_failed" and r["press"] == "unmarked"

    def test_an_evaluate_failure_reads_read_failed(self):
        class _Boom:
            async def evaluate(self, js, arg=None):
                raise RuntimeError("detached frame")
        r = _read(_Boom())
        assert r["outcome"] == "read_failed" and "detached" in r["error"]

    def test_the_post_press_inventory_is_what_gets_reported(self):
        """⛔ Mutation caught this: reporting the PRE-press snapshot survived
        every other test, because the fixtures happened to hand back the same
        state twice. The re-probe exists because a React re-render replaces the
        node — the inventory taken before the disclosure opened describes a
        closed panel."""
        before = _state(expanded=False, rows=0, links=0, urls=[], hosts=[],
                        region="parent")
        after = _state(expanded=True, rows=9, links=9, region="aria-controls",
                       urls=[f"https://h{i}.com" for i in range(9)],
                       hosts=[f"h{i}.com" for i in range(9)])
        page = _FakePage([before, after, after, after])
        r = _read(page)
        assert r["outcome"] == "opened"
        assert r["links"] == 9, "the pre-press inventory said 0"
        assert r["region"] == "aria-controls"
        assert len(r["urls"]) == 9

    def test_a_flat_list_is_not_scrolled(self):
        page = _FakePage([_state(expanded=True, scrollable=False)])
        _read(page)
        assert page.scrolls == 0, "nothing to scroll is not a failure"

    def test_a_scrollable_list_accumulates_across_scrolls(self):
        """Correct whether or not the list virtualises — which is the point,
        because a 0-source panel could never tell us which it is."""
        first = _state(expanded=True, scrollable=True, rows=3,
                       urls=["https://a.com"], hosts=["a.com"])
        second = _state(expanded=True, scrollable=True, rows=6,
                        urls=["https://b.com"], hosts=["b.com"])
        third = _state(expanded=True, scrollable=True, rows=6,
                       urls=["https://b.com"], hosts=["b.com"])
        # Two `first` reads: production probes to decide the outcome, then
        # re-probes after the disclosure settles, because a React re-render
        # replaces the node and the pre-press inventory is stale.
        page = _FakePage([first, first, second, third, third, third, third])
        r = _read(page, settle_s=0)
        assert set(r["urls"]) == {"https://a.com", "https://b.com"}
        assert r["rows_after"] == 6 and r["rows_before"] == 3
        assert r["scrolls"] >= 1

    def test_accumulation_stops_after_two_flat_rounds(self):
        flat = _state(expanded=True, scrollable=True, rows=3,
                      urls=["https://a.com"], hosts=["a.com"])
        page = _FakePage([flat], scroll_ok=True)
        r = _read(page, max_scrolls=12, settle_s=0)
        assert r["scrolls"] == 2, "a list that stops growing must stop the loop"


# ── the once-per-run read, and the two call sites that need it ───────────────

class TestFinishedSourcesRead:
    def test_it_merges_the_panel_into_the_snapshot_extract_actually_reads(self):
        """⚠ THE SNAPSHOT, not `progress`. `extract_and_record_agent` reads
        `_runtime.agent_progress_snapshots`, which is written once per poll
        BEFORE this read happens — so merging into `progress` alone would be
        dead by the time anything looked."""
        page = _FakePage([_state(expanded=True, count=553,
                                urls=["https://new.com"], hosts=["new.com"])])
        snaps = {"claude": {"source_urls": ["https://old.com"], "sources": 1,
                            "observed_sources": 2}}
        p = {}
        res = asyncio.run(research.claude_finished_sources_read(page, p, snaps))
        assert res["outcome"] == "already_open"
        assert snaps["claude"]["source_urls"] == ["https://old.com", "https://new.com"]
        assert snaps["claude"]["sources"] == 2
        assert snaps["claude"]["observed_sources"] == 553

    def test_the_run_verdict_judges_the_merged_numbers(self):
        """⛔ Mutation caught this: the verdict reading an EMPTY snapshot instead
        of the merged one survived every other test. It has to judge the numbers
        the panel read produced, or it reports the state before the read it is
        summarising — and would call every run blind."""
        page = _FakePage([_state(expanded=True, count=44,
                                urls=[f"https://s{i}.com" for i in range(44)],
                                hosts=[f"s{i}.com" for i in range(44)])])
        snaps = {"claude": {"source_urls": [], "sources": 0,
                            "observed_sources": 0}}
        lines = []
        orig = research.log
        research.log = lambda m, lvl="INFO": lines.append((m, lvl))
        try:
            asyncio.run(research.claude_finished_sources_read(page, {}, snaps))
        finally:
            research.log = orig
        verdicts = [(m, lvl) for m, lvl in lines if "finished with" in m]
        assert verdicts, "the run verdict must be logged"
        msg, lvl = verdicts[-1]
        assert lvl == "INFO", msg
        assert "44 source urls" in msg, msg

    def test_it_runs_at_most_once_per_run(self):
        page = _FakePage([_state(expanded=True)])
        p = {}
        assert asyncio.run(research.claude_finished_sources_read(page, p, {})) is not None
        before = page.probes
        assert asyncio.run(research.claude_finished_sources_read(page, p, {})) is None
        assert page.probes == before, "the second call must not touch the page"

    def test_the_latch_lives_on_p_so_a_serve_process_reads_every_run(self):
        """`--serve` runs many runs in one process; `pending[name]` is rebuilt
        per phase, so a module global would silence every run after the first."""
        page = _FakePage([_state(expanded=True)])
        assert asyncio.run(research.claude_finished_sources_read(page, {}, {})) is not None
        assert asyncio.run(research.claude_finished_sources_read(page, {}, {})) is not None

    def test_a_missing_snapshot_entry_is_not_an_error(self):
        page = _FakePage([_state(expanded=True)])
        assert asyncio.run(
            research.claude_finished_sources_read(page, {}, {})) is not None

    def test_both_extract_call_sites_do_the_read(self):
        """⛔⛔ THE CORRECTION THAT MATTERS MOST. `extract_and_record_agent` has
        TWO call sites for the same agent — Playwright-confirmed-done and
        CUA-confirmed-done — and Claude completing through the CUA never reaches
        the first. The corpus run this read exists for ("5 URLs, 15 steps") went
        through exactly that path, because only the CUA, which scrolls first,
        ever caught it. Wired to one site, this would have been a guard that
        cannot fire on the runs it was written for.

        Source-pinned because nothing in the suite executes
        `poll_all_agents_round_robin`; counted rather than substring-matched, so
        deleting one site fails this."""
        src = inspect.getsource(research.poll_all_agents_round_robin)
        assert src.count("await claude_finished_sources_read(") == 2, (
            "both extract_and_record_agent call sites must do the sources read"
        )
        # And each one must precede its extract, because extract_claude_response
        # closes the artifact panel as its first act.
        for block in src.split("await claude_finished_sources_read(")[1:]:
            head = block[:1200]
            assert "extract_and_record_agent(" in head, (
                "the read must sit immediately before its extract"
            )


# ── the printed count, executed through the real scraper JS ──────────────────

def _claude_scrape(body_text, extra_kids=()):
    """Run the real `scrape_progress_claude` JS against a fixture body."""
    from _domshim import evaluate_js
    spec = el("div", {}, "", [el("p", {}, body_text), *extra_kids])
    return run_js(spec, evaluate_js(research.scrape_progress_claude,
                                    contains="printed_sources"))["ret"]


class TestPrintedSourceCount:
    def test_the_final_printed_total_is_captured_not_discarded(self):
        """⭐ This regex has matched "Research complete · 553 sources · 24m 41s"
        since 2026-04-26 and thrown the 553 away every time, because the digits
        sat in a non-capturing group read only as a boolean. It is the most
        authoritative figure Claude prints — the FINAL count, where the ticker
        is mid-run and vanishes on completion."""
        r = _claude_scrape("Research complete · 553 sources · 24m 41s")
        assert r["printed_sources"] == 553

    def test_a_comma_grouped_printed_total_is_captured(self):
        r = _claude_scrape("Research complete · 1,284 sources · 1h 4m")
        assert r["printed_sources"] == 1284

    def test_a_done_marker_with_no_count_reports_zero_not_a_crash(self):
        r = _claude_scrape("Research completed in 5m")
        assert r["printed_sources"] == 0

    def test_the_mid_run_ticker_is_kept_separate_from_the_printed_total(self):
        """⛔ Two separate facts. The ticker proves the run is ALIVE — the
        scraper's own "still generating" test reads it for exactly that — while
        the printed total says how many sources it ended with. Merging them
        would let a completed count masquerade as liveness and pin a finished
        run at "generating" forever."""
        r = _claude_scrape("47 sources and counting")
        assert r["observed_sources"] == 47
        assert r["printed_sources"] == 0

    def test_the_printed_total_never_becomes_the_liveness_ticker(self):
        """⛔ Mutation caught this. Folding the printed total into
        `observed_sources` at the SCRAPE looks harmless and is not: that field's
        neighbour `liveSrcCount` is read by the scraper's own "still generating"
        test, and a completed count arriving as liveness pins a finished run at
        `generating` forever. The union belongs in Python, where the completion
        state is known — never in the scraper."""
        r = _claude_scrape("Research complete · 553 sources · 24m 41s")
        assert r["printed_sources"] == 553
        assert r["observed_sources"] == 0, (
            "the scraper must not report a finished count as live activity"
        )
        assert r["searches"] == 0

    def test_the_url_derived_count_is_untouched_by_the_capture(self):
        r = _claude_scrape("Research complete · 553 sources · 24m 41s")
        assert r["sources"] == len(r["source_urls"])
