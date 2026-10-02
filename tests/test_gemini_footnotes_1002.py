"""Wave 14, 2026-10-02 — Gemini's citations open the sources of Gemini's own
"Sources used in the report", and the document ends with that one list.

THE RECORDING (fixtures/gemini_1002/report_recording.json, an excerpt of the
owner's #Dev/wave14/recordings-1001/sr-cite-gemini-report.json). Each citation is
`<source-footnote><sup class="superscript" data-turn-source-index="N"></sup>
</source-footnote>`: no link, no words. In a table, where Gemini draws no chip,
its raw mark stays: "[cite: 5, 13]". The report ends with "Sources used in the
report" and "Sources read but not used in the report", each behind a button.
Today the chips vanish, the marks show as raw text, Gemini's list is cut off, and
the document ends with the sites the run saw Gemini open.

⛔⛔ WHICH ROW IS NUMBER N — WHAT THE FILES ON DISK SAY. The recording holds no
row of the list (`usedRows` is empty: the section was closed), the saved
documents hold none (it was cut off), and no fixture holds one. The one chip the
recording shows with a number on it reads "1" where its index is 7
(`numberish`). So a number is never joined to a row by its place in the list:
only by the row saying which number it is (the same `data-turn-source-index`),
and with every check passing. Otherwise the document is today's, byte for byte,
and one log line says why with the counts the next run needs.

⛔ The rows below are ASSUMED markup (`_gemini_1002_pages.sources_section`): one
shape with the number on the row, one without. Expected links are this file's
own: each number's row is chosen here by its number, in an order that is NOT the
numbers' order, so a join by place would link every number wrongly. The pages run
in real headless Chrome through Gemini's production extraction; nothing leaves
the machine (`page.set_content`).
"""
import asyncio
import re

import pytest

import research
import test_chatgpt_new_page_0928 as base
import _gemini_1002_pages as G
from test_footnotes_1001 import _firestore

chrome = base.chrome
page = base.page
fast = base.fast

#: The sources this report cites, by number, and the order Gemini's list shows
#: them in (ASSUMED — deliberately not the numbers' order).
SOURCES = {
    1: ("https://docs.example.org/relay/overview", "Overview - Relay Documentation"),
    2: ("https://github.com/example/relay", "GitHub - example/relay"),
    3: ("https://blog.example.net/tracing-agents", "Tracing agent harness behaviour"),
    4: ("https://docs.example.org/relay/plugins", "Plugins - Relay Documentation"),
    5: ("https://www.example.com/news/relay-launch?utm_source=gemini", "Relay launches"),
}
LIST_ORDER = [3, 1, 5, 2, 4]
UNUSED = [("https://unused.example.org/a", "Read but not used A"),
          ("https://unused.example.org/b", "Read but not used B")]
NUMBERED_ROW = 'data-turn-source-index="{n}"'
MARKER_RE = re.compile(r"\[\\\[(\d{1,3})\\\]\]\(([^()\s]*)\)")
OWN_RE = re.compile(r"(?<![\[\\])\\\[(\d{1,3})\\\](?!\]\()")
TAIL = "\n\n##### Sources\n\n"


@pytest.fixture
def lines(monkeypatch):
    out = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO", *a, **k: out.append(str(msg)))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    return out


def _said(lines, words):
    return [m for m in lines if words in m]


def _report(extra=""):
    """A report citing every source: chips in its sentences (the recorded markup,
    glued to the word they follow — ASSUMED), a run of two chips as one
    "[cite: 4, 5]" draws them, and a table whose cells keep Gemini's raw marks."""
    c = G.chip
    return ("<h1>Technical Evaluation of Relay</h1><h2>Overview</h2>"
            f"<p>{G.prose(1)} Relay sits between an agent and its models.{c(1)}</p>"
            f"<p>{G.prose(2)} Its source code is public{c(2)} and documented.{c(1)}</p>"
            "<h2>Plugins</h2>"
            f"<p>{G.prose(3)} Each plugin runs in a fixed order.{G.chips(4, 5)}</p>"
            "<table><thead><tr><th>Claim</th><th>Evidence</th></tr></thead><tbody>"
            "<tr><td>Traces every call</td><td><code>trace</code> [cite: 3]</td></tr>"
            "<tr><td>Launched in 2026</td><td>Launch post [cite: 5, 2]</td></tr>"
            "</tbody></table>"
            f"<h2>Verdict</h2><p>{G.prose(4)}</p><p>{G.prose(5)}</p>{extra}")


def _sections(numbered=True, order=LIST_ORDER, rows=None):
    rows = rows if rows is not None else [
        (SOURCES[n][0], SOURCES[n][1], NUMBERED_ROW.format(n=n) if numbered else "")
        for n in order]
    unused = [(u, t, "") for u, t in UNUSED]
    return (G.sources_section("Sources used in the report", rows)
            + G.sources_section("Sources read but not used in the report", unused)
            + "<div class='thoughts'><button>Thoughts</button><p>Researching websites"
              "…</p></div>")


def _extract(chrome, page, report_html, after):
    G.offline(chrome, page)
    chrome.run(page.set_content(G.report_page(report_html, after=after)))
    return chrome.run(research.extract_gemini_response(page))


def _panel_html(chrome, page):
    return chrome.run(page.evaluate(
        "() => [...document.querySelectorAll('immersive-panel')].pop().innerHTML"))


def _today(chrome, page):
    """What Gemini's extraction wrote before this change, from the page as loaded:
    the panel converted as every HTML read converts it, then its noise strip."""
    return research._strip_gemini_panel_noise(research.html_to_markdown(_panel_html(chrome, page)))


def _rows(doc):
    """This file's own reading of the one Sources list: [(number, url, title)]."""
    assert doc.count(TAIL) == 1, "not exactly one Sources list"
    out = []
    for line in doc[doc.index(TAIL) + len(TAIL):].rstrip("\n").split("\n"):
        m = re.fullmatch(r"- \[(?P<t>[^\]]*)\]\((?P<u>[^()\s]+)\) — .+ — cited as (?P<n>\d+)", line)
        assert m, line
        out.append((int(m["n"]), m["u"], m["t"]))
    return out


def test_rows_that_say_their_number_give_each_citation_its_own_source(chrome, page, fast, lines):
    """⭐⭐ The page joins each number to a row (the row carries the chip's own
    `data-turn-source-index`): every chip and every table mark becomes Gemini's
    own number, glued to the word before it, and the document ends with ONE
    "Sources" list — Gemini's rows, in Gemini's order, each naming its number —
    and nothing of "Sources read but not used" or the thoughts after it."""
    md = _extract(chrome, page, _report(), _sections())
    assert md, lines
    rows = _rows(md)
    assert [n for n, _u, _t in rows] == LIST_ORDER
    for n, u, t in rows:
        assert t == SOURCES[n][1]
        assert u == research._doc_public_source_url(SOURCES[n][0])
    assert "utm_source" not in md
    body = md[:md.index(TAIL)]
    assert [int(n) for n in OWN_RE.findall(body)] == [1, 2, 1, 4, 5, 3, 5, 2]
    assert "models.\\[1\\]" in body and "public\\[2\\] and" in body
    assert "order.\\[4\\]\\[5\\]" in body
    assert "| `trace`\\[3\\] |" in body and "| Launch post\\[5\\]\\[2\\] |" in body
    assert "[cite:" not in md and "\ue300" not in md
    assert "Read but not used" not in md and "Researching websites" not in md
    assert "Sources used in the report" not in md
    assert _said(lines, "[Gemini] Gemini's own citation numbers, from its own list: "
                        "5 citation chips and 2 written marks naming 5 numbers, 1 to 5, every one")


def test_the_write_links_each_number_to_the_row_it_names(chrome, page, fast, lines):
    """⭐⭐ At the write, each number opens the address of the row that carries its
    number — never the row at its place — and the list stays the one list."""
    md = _extract(chrome, page, _report(), _sections())
    out = research._number_document_sources(md, [], ["https://visited.example.org/x"],
                                            label="Gemini")
    links = MARKER_RE.findall(out[:out.index(TAIL)])
    assert len(links) == 8
    for n, url in links:
        assert url == research._doc_public_source_url(SOURCES[int(n)][0])
    assert out.count("##### Sources") == 1 and "visited.example.org" not in out
    assert _said(lines, "[Gemini] linked 8 of its own citation numbers to its own sources list")
    # The crash-retry read-back hands over what the extraction did.
    assert research._document_without_sources(out) == md.rstrip("\n") or \
        research._document_without_sources(out) == md


def test_rows_that_do_not_say_their_number_keep_todays_document(chrome, page, fast, lines):
    """⛔⛔ THE JOIN IS NEVER BY PLACE. The same report and the same rows, in the
    numbers' own order, but with no number on any row: the document is exactly
    what Gemini's extraction wrote before, and one line says why, with the counts
    the next run needs to settle the join."""
    md = _extract(chrome, page, _report(), _sections(numbered=False, order=[1, 2, 3, 4, 5]))
    assert md == _today(chrome, page)
    assert "\\[1\\]" not in md and "Sources used in the report" not in md
    said = _said(lines, "[Gemini] Gemini's citations stay as they are: its list's rows do not "
                        "say which number each one is")
    assert len(said) == 1, lines
    assert ("5 citation chips and 2 written marks naming 5 numbers, 1 to 5, every one; its "
            "list \"Sources used in the report\" shows 5 rows") in said[0]


def _variant(name):
    """A page that fails exactly one check — (report, sections, why)."""
    rows = [(SOURCES[n][0], SOURCES[n][1], NUMBERED_ROW.format(n=n)) for n in LIST_ORDER]
    if name == "chip-without-number":
        return (_report(G.chip(1).replace(' data-turn-source-index="1"', "")
                        .join(["<p>One more sentence.", "</p>"])),
                _sections(), "a citation chip carries no number")
    if name == "no-list":
        return _report(), "", "the page holds no \"Sources used in the report\" list"
    if name == "closed-list":
        return (_report(), G.sources_section("Sources used in the report", []),
                "its list shows no row with an address")
    if name == "row-two-addresses":
        bad = rows[:1] + [rows[1] + ("<a href='https://other.example.org/x'>more</a>",)] + rows[2:]
        return _report(), _sections(rows=bad), "a row of its list has no number or not one address"
    if name == "number-on-two-rows":
        bad = rows + [("https://dup.example.org/y", "Dup", NUMBERED_ROW.format(n=3))]
        return _report(), _sections(rows=bad), "number 3 is on two rows of its list"
    if name == "link-in-no-row":
        bad = rows + [("https://loose.example.org/z", "Loose", "")]
        return _report(), _sections(rows=bad), "a link in its list is in no numbered row"
    if name == "row-nobody-cites":
        bad = rows + [("https://extra.example.org/w", "Extra", NUMBERED_ROW.format(n=6))]
        return (_report(), _sections(rows=bad),
                "the numbers cited and its list's rows do not match one for one "
                "(5 numbers, 6 rows)")
    if name == "number-without-row":
        return (_report(f"<p>A last claim.{G.chip(6)}</p>"), _sections(),
                "the numbers cited and its list's rows do not match one for one "
                "(6 numbers, 5 rows)")
    if name == "after-a-bullet":
        return (_report(f"<ul><li>{G.chip(2)} opens the item</li></ul>"), _sections(),
                "a citation comes right after a bullet")
    if name == "own-list-with-links":
        return (_report("<h2>Works cited</h2><ol><li><a href='https://own.example.org/p'>"
                        "Own</a></li></ol>"), _sections(),
                "the report ends with a sources list of its own that holds links")
    if name == "at-a-line-start":
        return (_report(f"<p>Line one<br>{G.chip(2)}line two</p>"), _sections(),
                "numbers would link at the write")
    raise AssertionError(name)


@pytest.mark.parametrize("name", [
    "chip-without-number", "no-list", "closed-list", "row-two-addresses",
    "number-on-two-rows", "link-in-no-row", "row-nobody-cites", "number-without-row",
    "after-a-bullet", "own-list-with-links", "at-a-line-start"])
def test_any_doubt_keeps_todays_document(chrome, page, fast, lines, name):
    """⛔ Each check, failed alone: no number and no list are written — the
    document is exactly today's — and one log line says which check."""
    report, sections, why = _variant(name)
    md = _extract(chrome, page, report, sections)
    assert md == _today(chrome, page)
    said = _said(lines, "[Gemini] Gemini's citations stay as they are: ")
    assert len(said) == 1 and why in said[0], (said, lines[-5:])
    assert not _said(lines, "Gemini's own citation numbers, from its own list")


def test_a_report_citing_nothing_says_nothing(chrome, page, fast, lines):
    """A report with no chip and no mark is today's document, and no line about
    citations is written — while the same page with one chip says why."""
    plain = "<h1>Report</h1>" + "".join(f"<p>{G.prose(i)}</p>" for i in range(8))
    md = _extract(chrome, page, plain, _sections())
    assert md == _today(chrome, page)
    assert not _said(lines, "Gemini's citations")
    _extract(chrome, page, plain + f"<p>Cited.{G.chip(1)}</p>", _sections(numbered=False))
    assert len(_said(lines, "Gemini's citations stay as they are")) == 1


def test_a_row_that_is_not_a_public_page_keeps_its_number_as_text(chrome, page, fast, lines):
    """⛔ Gemini reads Drive and Gmail. A row opening the owner's own file is listed
    by its title only — its address never reaches the document — and its number
    stays text at the write; every other number links."""
    private = "https://docs.google.com/document/d/abc123/edit"
    rows = [(SOURCES[n][0] if n != 2 else private, SOURCES[n][1], NUMBERED_ROW.format(n=n))
            for n in LIST_ORDER]
    md = _extract(chrome, page, _report(), _sections(rows=rows))
    assert "docs.google.com" not in md and "abc123" not in md
    assert "\n- GitHub - example/relay — cited as 2\n" in md
    out = research._number_document_sources(md, [], [], label="Gemini")
    nums = [int(n) for n, _u in MARKER_RE.findall(out)]
    assert 2 not in nums and sorted(set(nums)) == [1, 3, 4, 5]
    assert "public\\[2\\] and" in out


def test_a_link_less_works_cited_of_its_own_is_replaced(chrome, page, fast, lines):
    """One sources section: the report's own trailing "Works cited" with no link
    in it is replaced by Gemini's own list."""
    own = "<h2>Works cited</h2><ol><li>Relay documentation</li><li>Relay on GitHub</li></ol>"
    md = _extract(chrome, page, _report(own), _sections())
    assert "Works cited" not in md and md.count("Sources") == 1
    assert _said(lines, "replaced by Gemini's own sources list")


def test_the_saved_document_and_its_cloud_copy_carry_the_links(chrome, page, fast, lines,
                                                              monkeypatch, tmp_path):
    """⭐⭐ THROUGH THE REAL WRITE: the per-agent save writes Gemini's numbers
    linked to its own rows and its one list — on disk and in the copy the app
    reads — and the sites the run tracked are NOT added after it."""
    sink = _firestore(monkeypatch)
    runtime = research.PipelineRuntime()
    monkeypatch.setattr(research, "_runtime", runtime, raising=False)
    visited = ["https://visited-only.example.org/a", "https://visited-two.example.org/b"]
    runtime.agent_progress_snapshots["gemini"] = {"source_urls": visited}
    research._p2_fold_visited_sources("gemini", {"source_urls": visited})
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)

    async def _same(text, **k):
        return text
    monkeypatch.setattr(research, "_rehost_document_images", _same)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    G.offline(chrome, page)
    chrome.run(page.set_content(G.report_page(_report(), after=_sections())))

    class _Browser:
        async def switch_to_page(self, p):
            return None
    res = chrome.run(research.extract_and_record_agent("Gemini", page, _Browser(), None, tmp_path))
    local = (tmp_path / "documents" / "gemini.md").read_text(encoding="utf-8")
    assert res["status"] == "done"
    assert [d["content"] for p, d in sink if p.endswith("/documents/gemini")] == [local]
    assert "visited-only" not in local and local.count("\n##### Sources\n") == 1
    links = MARKER_RE.findall(local)
    assert len(links) == 8 and all(
        u == research._doc_public_source_url(SOURCES[int(n)][0]) for n, u in links)


def test_copy_contents_that_hangs_is_left_after_a_short_wait(chrome, page, fast, lines,
                                                            monkeypatch):
    """⛔ "Share & Export → Copy contents" hung for the owner. When the panel read
    finds nothing and computer use's press never returns, the press is given up
    after its short cap (here 0.5 s; 45 s in a run, where it was 90) and the
    ladder moves on to the next tier."""
    monkeypatch.setattr(research, "_GEMINI_COPY_CONTENTS_S", 0.5, raising=False)
    monkeypatch.setattr(research, "get_clipboard", lambda: "")
    held = {}

    async def _hangs(*a, **k):
        loop = asyncio.get_running_loop()
        held["start"] = loop.time()
        try:
            await asyncio.Event().wait()
        finally:
            held["for"] = loop.time() - held["start"]
    monkeypatch.setattr(research, "agent_loop", _hangs)
    G.offline(chrome, page)
    chrome.run(page.set_content("<!doctype html><html><body><p>nothing here</p></body></html>"))

    class _Browser:
        async def switch_to_page(self, p):
            return None

    async def _go():
        return await asyncio.wait_for(
            research.extract_gemini_response(page, browser=_Browser(), cua_client=object()), 20)
    assert chrome.run(_go()) == ""
    assert held["for"] < 2.5, held
    assert _said(lines, "Falling back to select-all")


def test_rows_with_numbers_that_skip_still_join_by_the_number(chrome, page, fast, lines):
    """The numbers a report cites need not run 1…K: Gemini's rows carry 1, 2, 3
    and 5 and the report cites exactly those. Each links its own row — a join by
    place would have sent 5 to the fourth row — and the log says the numbers skip."""
    rows = [(SOURCES[n][0], SOURCES[n][1], NUMBERED_ROW.format(n=n)) for n in (3, 5, 1, 2)]
    report = _report().replace(G.chips(4, 5), G.chip(5))
    md = _extract(chrome, page, report, _sections(rows=rows))
    assert [n for n, _u, _t in _rows(md)] == [3, 5, 1, 2]
    out = research._number_document_sources(md, [], [], label="Gemini")
    for n, url in MARKER_RE.findall(out):
        assert url == research._doc_public_source_url(SOURCES[int(n)][0])
    assert _said(lines, "naming 4 numbers, 1 to 5 with gaps")


def test_a_mark_inside_code_stays_and_a_row_cited_only_there_is_not_listed(
        chrome, page, fast, lines):
    """⛔ Inside code a mark is the code's own text: it stays "[cite: N]". Its
    number still counts as cited, so the list and the citations match; a row cited
    only inside code is not listed (no number in the text opens it). A row's inner
    element carrying its number too is the same row."""
    code = "<pre><code>| claim | [cite: 2] |\n| other | [cite: 6] |</code></pre>"
    rows = [(SOURCES[n][0], SOURCES[n][1], NUMBERED_ROW.format(n=n),
             f'<sup {NUMBERED_ROW.format(n=n)}></sup>') for n in LIST_ORDER]
    rows.append(("https://only-in-code.example.org/c", "Only in code", NUMBERED_ROW.format(n=6)))
    md = _extract(chrome, page, _report(code), _sections(rows=rows))
    assert "| claim | [cite: 2] |" in md and "| other | [cite: 6] |" in md
    assert [n for n, _u, _t in _rows(md)] == LIST_ORDER
    assert "only-in-code" not in md
    assert _said(lines, "5 of its 6 sources listed")


def test_citations_only_inside_code_leave_nothing_to_number(chrome, page, fast, lines):
    """A report whose only citations are inside code has no number to write: it
    is today's document, and the line says so."""
    plain = ("<h1>Report</h1>" + "".join(f"<p>{G.prose(i)}</p>" for i in range(8))
             + "<pre><code>see [cite: 1]</code></pre>")
    rows = [(SOURCES[1][0], SOURCES[1][1], NUMBERED_ROW.format(n=1))]
    md = _extract(chrome, page, plain, _sections(rows=rows))
    assert md == _today(chrome, page)
    assert _said(lines, "Gemini's citations stay as they are: no citation is left to number")


def test_a_failure_while_reading_them_keeps_todays_document(chrome, page, fast, lines,
                                                           monkeypatch):
    """⛔ Anything that goes wrong while the citations are read leaves the document
    as it was, with one line."""
    def _boom(html, label="Gemini"):
        raise ValueError("unexpected markup")
    monkeypatch.setattr(research, "_gemini_footnoted", _boom)
    md = _extract(chrome, page, _report(), _sections())
    assert md == _today(chrome, page)
    assert _said(lines, "Gemini's citations stay as they are: they could not be read (ValueError)")
