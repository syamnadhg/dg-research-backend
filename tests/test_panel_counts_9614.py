"""The activity panel under-reported its sources by 56%, and the cause was a
whole-URL substring test standing in for a host test.

DGOPS-9614 recorded that the panel's figures did not agree with the platform's
own end-of-run summary and could not say why, because the panel exists only
while a phase is in flight. This suite settles it by REPLAYING the panel markup
captured mid-run on 6 August through the production extractor, rather than
against a fixture hand-built to match somebody's theory of the markup.

The replay reproduces the live run exactly — same panel chosen, `source_urls=16`,
`searches=31`, `sections=0` — which is what makes it trustworthy as ground truth
for the fixes. Measured on that document:

* 40 anchors, all external research sources, 36 distinct once the platform's own
  tracking parameter is discounted.
* 22 of the 40 were discarded by `h.includes('chatgpt.com')`, because ChatGPT
  appends `?utm_source=chatgpt.com` to every outbound source link. The filter
  written to skip the platform's own pages was eating the platform's own
  citations. 20 real sources lost.
* Zero heading elements at any level, so `sections=0` was the correct answer all
  along and the ticket's parse-gap reading was wrong.
* The panel says "15 more" in BOTH captures — while one holds 5 anchors and the
  other 40 — so that remainder is per-row, and the old `shown + hidden` sum was
  never a panel total.

⚠ The grown capture is TRUNCATED (it hit the old 60,000-char limit mid-tag), so
36 is a floor. Every count here is asserted as "at least", never as exact.
"""
import sys
from pathlib import Path

import pytest

import research
from _domshim import (js_constant, run_js, spec_from_html,
                      stamp_panel_geometry)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "panels"
GROWN = FIXTURES / "chatgpt_activity_panel_grown_20260806.html"
COLLAPSED = FIXTURES / "chatgpt_activity_panel_collapsed_20260806.html"

PANEL_JS = js_constant(research.scrape_chatgpt_activity_panel_tracking, "JS")


def _replay(path: Path) -> dict:
    spec = stamp_panel_geometry(
        spec_from_html(path.read_text(encoding="utf-8", errors="replace")))
    return (run_js(spec, PANEL_JS) or {}).get("ret") or {}


@pytest.fixture(scope="module")
def grown():
    return _replay(GROWN)


@pytest.fixture(scope="module")
def collapsed():
    return _replay(COLLAPSED)


# ── The replay is faithful, or nothing below it means anything ───────────────

def test_the_replay_selects_the_same_panel_the_live_run_did(grown):
    """The live log named the chosen node `SECTION|_56rfYG_screen …`. If the
    replay picked something else, every count here would describe a different
    element than the one the defect was observed on."""
    assert (grown.get("dbg_panel_tag") or "").startswith("SECTION|_56rfYG_screen")


# ── The headline fix: the host filter was eating the sources ─────────────────

def test_every_source_the_panel_holds_is_now_read(grown):
    """16 before, on a document that holds 36 distinct sources."""
    urls = grown.get("source_urls") or []
    assert len(urls) >= 36, f"only {len(urls)} sources read"


def test_the_platforms_tracking_tag_no_longer_hides_a_source(grown):
    """The specific mechanism: these are ordinary external pages whose only
    connection to the platform is a tracking parameter it appended itself."""
    urls = grown.get("source_urls") or []
    hosts = {u.split("/")[2] for u in urls if "://" in u}
    assert "developer.nvidia.com" in hosts
    assert "docs.nvidia.com" in hosts
    assert "github.com" in hosts


def test_no_stored_url_carries_a_tracking_parameter(grown):
    offenders = [u for u in (grown.get("source_urls") or []) if "utm_" in u]
    assert offenders == [], f"tracking params survived into stored urls: {offenders[:3]}"


def test_the_same_page_cited_twice_is_one_source(grown):
    """Tagged and untagged citations of one page must collapse — otherwise
    recovering the 22 would have re-inflated the count to 38 rather than 36."""
    urls = grown.get("source_urls") or []
    assert len(urls) == len(set(urls))


# ── …without letting the platform's own pages back in ────────────────────────

def _urls_from(anchor_hrefs) -> list:
    """Run the extractor over a minimal panel holding just these anchors."""
    kids = [{"tag": "a", "attrs": {"href": h}, "text": "src", "kids": []}
            for h in anchor_hrefs]
    # An 'Activity'-headed leaf is what the panel finder climbs from.
    kids.insert(0, {"tag": "div", "attrs": {}, "text": "Activity", "kids": []})
    spec = stamp_panel_geometry(
        {"tag": "section", "attrs": {"aria-label": "Reasoning details"},
         "text": "", "kids": kids})
    return ((run_js(spec, PANEL_JS) or {}).get("ret") or {}).get("source_urls") or []


def test_a_real_platform_page_is_still_excluded():
    """The filter's original job. A sign-in or settings page on the platform's own
    host is not a research source."""
    got = _urls_from(["https://chatgpt.com/auth/login",
                      "https://docs.example.com/guide"])
    assert got == ["https://docs.example.com/guide"]


def test_a_platform_subdomain_is_excluded():
    assert _urls_from(["https://cdn.openai.com/asset.png"]) == []


def test_a_lookalike_host_is_not_excluded():
    """Anchored at both ends on purpose — a bare suffix test would swallow this."""
    assert _urls_from(["https://notchatgpt.com/article"]) == \
        ["https://notchatgpt.com/article"]


def test_a_source_tagged_by_the_platform_is_kept():
    assert _urls_from(["https://docs.example.com/a?utm_source=chatgpt.com"]) == \
        ["https://docs.example.com/a"]


def test_a_load_bearing_query_parameter_is_preserved():
    """Only the utm_* family is dropped. Anything else in a query string can be
    what makes the page resolve."""
    got = _urls_from(["https://ex.com/p?id=42&utm_source=chatgpt.com&utm_medium=x"])
    assert got == ["https://ex.com/p?id=42"]


def test_a_fragment_survives_parameter_stripping():
    got = _urls_from(["https://ex.com/p?utm_source=chatgpt.com#section-3"])
    assert got == ["https://ex.com/p#section-3"]


def test_two_urls_differing_only_by_tracking_tag_collapse_to_one():
    got = _urls_from(["https://ex.com/p",
                      "https://ex.com/p?utm_source=chatgpt.com"])
    assert got == ["https://ex.com/p"]


# ── Sections: zero was always the right answer ───────────────────────────────

def test_the_panel_holds_no_headings_at_all(grown):
    """So a heading count of zero is correct output, not a parse gap. This is the
    assertion that should stop the ticket being re-raised.

    2026-08-06: the `sections == []` half moved. No headings is still true and is
    still what `dbg_headings` reports — but "no headings" turned out not to mean
    "no structure": the panel carries two group labels ("Pro thinking",
    "Sources · N") and now reports them. `tests/test_panel_sections_0806.py` owns
    that behaviour; this test keeps the heading fact it was written for."""
    assert grown.get("dbg_headings") == 0
    # Whatever `sections` now contains, none of it came from a heading element.
    assert not any(s.lower().startswith("h1") for s in (grown.get("sections") or []))


def test_headings_are_reported_separately_from_sections():
    """Zero headings present and zero surviving the length filter are different
    facts. Given a heading that IS present but too long to keep, the raw count
    must still say one was there."""
    spec = stamp_panel_geometry(
        {"tag": "section", "attrs": {"aria-label": "Reasoning details"}, "text": "",
         "kids": [{"tag": "div", "attrs": {}, "text": "Activity", "kids": []},
                  {"tag": "h2", "attrs": {}, "text": "x" * 200, "kids": []}]})
    r = (run_js(spec, PANEL_JS) or {}).get("ret") or {}
    assert r.get("dbg_headings") == 1
    assert (r.get("sections") or []) == []


def test_a_real_heading_still_extracts():
    spec = stamp_panel_geometry(
        {"tag": "section", "attrs": {"aria-label": "Reasoning details"}, "text": "",
         "kids": [{"tag": "div", "attrs": {}, "text": "Activity", "kids": []},
                  {"tag": "h3", "attrs": {}, "text": "Findings so far", "kids": []}]})
    r = (run_js(spec, PANEL_JS) or {}).get("ret") or {}
    assert r.get("sections") == ["Findings so far"]
    assert r.get("dbg_headings") == 1


# ── The remainder is per-row, so it is not added to a panel total ────────────

def test_the_collapsed_remainder_is_reported_but_not_summed(grown):
    """Both captures read "15 more" while holding 5 and 40 anchors respectively,
    which is only possible if the affordance belongs to one row. The old
    `shown + hidden` gave 51 here once the source read was fixed — an over-count
    of a figure the user compares against the platform's own display."""
    assert grown.get("dbg_more_remainder") == 15
    assert grown.get("searches") == len(grown.get("source_urls") or [])
    assert grown.get("searches") != len(grown.get("source_urls") or []) + 15


def test_the_remainder_is_identical_in_both_captures(collapsed, grown):
    """The measurement that disproves the panel-wide reading. If these ever
    differ, revisit whether the affordance is per-row after all."""
    assert collapsed.get("dbg_more_remainder") == grown.get("dbg_more_remainder") == 15
    assert len(collapsed.get("source_urls") or []) < len(grown.get("source_urls") or [])


def test_a_remainder_with_no_links_beside_it_does_not_borrow_the_panels():
    """The case the climb's panel guard exists for, and which neither capture
    contains — so the first mutation pass let the guard be deleted with everything
    green.

    A remainder chip sitting on its own, with the panel's links elsewhere: the
    climb must give up at the panel boundary and count the remainder alone. Let it
    walk INTO the panel and `rowTotal` becomes panel-links-plus-remainder, which is
    exactly the panel-wide over-count the row scoping removes.
    """
    links = [{"tag": "a", "attrs": {"href": f"https://ex{i}.com/p"}, "text": "s",
              "kids": []} for i in range(5)]
    spec = stamp_panel_geometry({
        "tag": "section", "attrs": {"aria-label": "Reasoning details"}, "text": "",
        "kids": [
            {"tag": "div", "attrs": {}, "text": "Activity", "kids": []},
            {"tag": "div", "attrs": {"class": "sources-row"}, "text": "",
             "kids": links},
            # Its own branch, no anchors anywhere under it.
            {"tag": "div", "attrs": {"class": "footer"}, "text": "", "kids": [
                {"tag": "div", "attrs": {}, "text": "9 more", "kids": []}]},
        ]})
    r = (run_js(spec, PANEL_JS) or {}).get("ret") or {}
    assert len(r.get("source_urls") or []) == 5
    assert r.get("dbg_more_remainder") == 9
    assert r.get("searches") == 9, (
        f"expected the remainder counted alone, got {r.get('searches')} — "
        f"5 + 9 means the climb escaped into the panel")


def test_an_explicit_count_in_words_still_wins_when_it_is_larger():
    """The count is the larger of what the panel says and what we read, so a
    panel that states a total above the links it has rendered is believed."""
    spec = stamp_panel_geometry(
        {"tag": "section", "attrs": {"aria-label": "Reasoning details"}, "text": "",
         "kids": [{"tag": "div", "attrs": {}, "text": "Activity", "kids": []},
                  {"tag": "div", "attrs": {}, "text": "Searched 193 websites",
                   "kids": []},
                  {"tag": "a", "attrs": {"href": "https://ex.com/a"}, "text": "a",
                   "kids": []}]})
    r = (run_js(spec, PANEL_JS) or {}).get("ret") or {}
    assert r.get("searches") == 193


# ── The capture must never be silently cut again ─────────────────────────────

def test_the_capture_limit_covers_this_panel(grown):
    """The retained document re-serializes larger than the old 60,000 limit, which
    is how we know that limit bit. The new one must clear it with room."""
    full = grown.get("dbg_html_full_len") or 0
    assert full > 60000, f"fixture no longer exceeds the old limit ({full})"
    assert len(grown.get("dbg_html") or "") == full, "still truncating"


def test_a_truncated_capture_says_so(monkeypatch, capsys):
    """The Python half. A cut file parses fine and every figure read off it is a
    floor that reads like an exact number — assert the operator is told."""
    monkeypatch.setattr(research, "_p2_panel_dbg_dumps", 0, raising=False)
    monkeypatch.setattr(research, "_p2_panel_last_fp", None, raising=False)
    monkeypatch.setattr(research, "_p2_panel_dbg_last_len", 0, raising=False)
    monkeypatch.setattr(research, "_p2_panel_dbg_frozen_done", False, raising=False)
    res = {"source_urls": ["u"], "steps": [], "sections": [], "searches": 1,
           "dbg_fp": {"tag": "SECTION", "kids": 1, "textlen": 9000,
                      "anchors": 1, "rows": 1},
           "dbg_html": "x" * 100, "dbg_html_full_len": 250,
           "dbg_headings": 0, "dbg_more_remainder": 0}
    research._p2_panel_dbg_record(res)          # first sample: records fingerprint
    research._p2_panel_dbg_record(dict(res))    # identical → triggers the dump
    out = capsys.readouterr().out
    assert "TRUNCATED" in out, out[-400:]
    assert "100 of 250 chars" in out


def test_a_whole_capture_does_not_claim_truncation(monkeypatch, capsys):
    monkeypatch.setattr(research, "_p2_panel_dbg_dumps", 0, raising=False)
    monkeypatch.setattr(research, "_p2_panel_last_fp", None, raising=False)
    monkeypatch.setattr(research, "_p2_panel_dbg_last_len", 0, raising=False)
    monkeypatch.setattr(research, "_p2_panel_dbg_frozen_done", False, raising=False)
    res = {"source_urls": ["u"], "steps": [], "sections": [], "searches": 1,
           "dbg_fp": {"tag": "SECTION", "kids": 1, "textlen": 9000,
                      "anchors": 1, "rows": 1},
           "dbg_html": "x" * 100, "dbg_html_full_len": 100,
           "dbg_headings": 0, "dbg_more_remainder": 0}
    research._p2_panel_dbg_record(res)
    research._p2_panel_dbg_record(dict(res))
    out = capsys.readouterr().out
    assert "TRUNCATED" not in out
    assert "100 of 100 chars" in out


def test_the_headings_count_reaches_the_log(monkeypatch, capsys):
    """Otherwise `sections=0` stays unexplained in the one place an operator
    looks, and the ticket gets re-raised from the log alone."""
    monkeypatch.setattr(research, "_p2_panel_last_fp", None, raising=False)
    res = {"source_urls": [], "steps": [], "sections": [], "searches": 0,
           "dbg_fp": {"tag": "SECTION", "kids": 1, "textlen": 10,
                      "anchors": 0, "rows": 0},
           "dbg_headings": 0, "dbg_more_remainder": 15}
    research._p2_panel_dbg_record(res)
    out = capsys.readouterr().out
    assert "headings=0" in out
    assert "more=15" in out


# ── Guards on the replay harness itself ──────────────────────────────────────

def test_a_void_tag_does_not_swallow_its_siblings():
    """`childElementCount` is what the panel's leaf scan branches on, so an <img>
    that captured every following sibling as a child would silently change which
    nodes count as leaves."""
    spec = spec_from_html("<div><img src=a><span>one</span><span>two</span></div>")
    assert [k["tag"] for k in spec["kids"]] == ["img", "span", "span"]


def test_a_stray_close_tag_does_not_pop_an_ancestor():
    """Truncated captures routinely carry one. Popping the wrong node would
    reparent everything after it."""
    spec = spec_from_html("<div><span>a</span></p><span>b</span></div>")
    assert [k["tag"] for k in spec["kids"]] == ["span", "span"]


def test_text_survives_the_parse():
    spec = spec_from_html("<div><p>hello</p><p>world</p></div>")
    assert [k["text"] for k in spec["kids"]] == ["hello", "world"]


def test_unclosed_tags_at_end_of_input_still_parse():
    spec = spec_from_html("<div><ul><li>a</li><li>b</li")
    assert spec["tag"] == "div"


def test_outer_html_round_trips_through_the_parser():
    """`outerHTML` is what production measures a capture with. If the shim's
    serializer and parser disagree, a truncation assertion means nothing."""
    html = '<section aria-label="x"><a href="https://e.com/p">t</a></section>'
    spec = spec_from_html(html)
    # `document.body` IS the root here; a descendant query would not match it.
    r = run_js(spec, "() => document.body.outerHTML")
    assert 'href="https://e.com/p"' in r["ret"]
    assert 'aria-label="x"' in r["ret"]
    assert spec_from_html(r["ret"])["tag"] == "section"


def test_geometry_stamping_leaves_a_deliberate_override_alone():
    """A fixture must still be able to pin one element off-screen."""
    spec = stamp_panel_geometry(
        {"tag": "section", "attrs": {}, "text": "",
         "kids": [{"tag": "div", "attrs": {"x": "-999"}, "text": "", "kids": []}]})
    assert spec["kids"][0]["attrs"]["x"] == "-999"


# ── The harness must not depend on how much fits in a command line ───────────

def test_the_shim_never_passes_the_script_as_a_command_line_argument():
    """⚠ CI-only failure, 2026-08-06: `OSError: [Errno 7] Argument list too long`.

    `run_js` embedded the shim source and the whole spec into a single `node -e`
    argument. Linux caps ONE argument at 128 KB regardless of total argv room;
    macOS is far more generous, so every one of these passed locally and five
    failed on the runner. The huge-panel fixtures in the sibling suite are 455 KB
    and 207 KB of JSON — nowhere near fitting.

    The fix writes the script to a temp file, which removes the dependency on any
    limit rather than staying under a particular one. Asserted on the call shape,
    because the failure cannot be reproduced on this platform: the guard has to be
    "no payload in argv", not "payload is small enough".
    """
    from conftest import code_only
    import _domshim
    src = code_only(_domshim.run_js)
    assert '"-e"' not in src and "'-e'" not in src, "the script is back in argv"
    assert "TemporaryDirectory" in src
    assert "subprocess.run([NODE, script]" in src


def test_a_spec_far_larger_than_a_command_line_still_runs():
    """The size that broke CI, executed end to end. 200k of JSON is past every
    single-argument limit on every platform this suite runs on."""
    big = {"tag": "div", "attrs": {}, "text": "", "kids": [
        {"tag": "span", "attrs": {"data-i": str(i), "class": "x" * 40},
         "text": f"row {i}", "kids": []} for i in range(3000)]}
    import json as _json
    assert len(_json.dumps(big)) > 200_000
    r = run_js(big, "() => document.querySelectorAll('span').length")
    assert r["ret"] == 3000
