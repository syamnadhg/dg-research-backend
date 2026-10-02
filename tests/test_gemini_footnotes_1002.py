"""Wave 14, 2026-10-02 — Gemini's citations open the sources of Gemini's own
"Sources used in the report", and the document ends with that one list.

THE RECORDINGS. Each citation is `<source-footnote><sup class="superscript"
data-turn-source-index="N"></sup></source-footnote>`: no link, no words
(fixtures/gemini_1002/report_recording.json, 10-01's report). With the list open
(fixtures/gemini_1002/sources_open_recording.json, the owner's 18:45 recording of
an OpenAI governance report), "Sources used in the report" is 66 rows, each a
`<browse-web-item>` holding one `<a data-test-id="browse-web-item-link"
href=…>`, and no row carries a number. The owner hovered the two chips of one
paragraph — index 1 (it SHOWS "1") and index 3 (it SHOWS "2") — and the cards
that opened carry the addresses of rows 1 and 3. So chip N is row N, counted in
page order, and the number shown on screen is not N.

⭐ THE RULE these tests hold. Each chip becomes `\\[N\\]`, the write links it to
row N's address, and the document ends with ONE "Sources" list: all of Gemini's
rows in its order, row N written as number N. "Read but not used" is not in it.
⛔ On any doubt — a number with no row, a number 0 or none, a row with no web
address or two, a link or words in the list outside a row — no number and no
list are written: the document is today's, and one log line says why. The list
ends where the box holding its rows ends, never at the next list's title.
⛔ A closed list is opened for the read by a press of its own toggle, and closed
again after it — also when it opens only after the read stopped waiting.

Every page here is built from the recordings' own markup (`_gemini_1002_pages`),
runs in real headless Chrome through Gemini's production extraction, and
nothing leaves the machine (`G.offline`, `page.set_content`).
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

REC = G.sources_recording()
#: Gemini's "Sources used in the report", in page order: row N is USED[N - 1].
USED = REC["used"]
#: The chips the owner hovered, and the address on the card each one opened.
HOVERED = {1: "https://openai.com/index/built-to-benefit-everyone/",
           3: "https://openai.com/our-structure/"}
#: The first words of the paragraph those two chips sit in.
HOVERED_WORDS = ("Following nearly a year of formal dialogue with the Attorneys General "
                 "of California and Delaware, OpenAI executed a corp.")
#: Rows on cdn.openai.com — an agent's own host, never put in a document.
NOT_LISTED = {30, 58}
MARKER_RE = re.compile(r"\[\\\[(\d{1,3})\\\]\]\(([^()\s]*)\)")
OWN_RE = re.compile(r"(?<![\[\\])\\\[(\d{1,3})\\\](?!\]\()")
TAIL = "\n\n##### Sources\n\n"
ROW_RE = re.compile(r"- (?:\[(?P<t>[^\]]*)\]\((?P<u>[^()\s]+)\) — .+|(?P<p>.+?)) "
                    r"— cited as (?P<n>\d+)")
#: A link in the report's own words (the 10-01 recording's `bodyLinks`).
BODY_LINK = ("<p>The plugin model is documented in <a href='https://docs.example.org/"
             "relay/plugins'>the configuration guide</a> in full.</p>")
#: The second list's title, worded otherwise than Gemini's.
OTHER_TITLE = "Sources read but not cited in the report"
#: A row drawn by another element, with no web address (ASSUMED: no recording
#: holds one) — an uploaded file, say.
FILE_ROW = ('<browse-file-item class="ng-star-inserted"><div class="browse-item">'
            '<div data-test-id="sub-title" class="sub-title">governance-memo.pdf</div>'
            '</div></browse-file-item>')


@pytest.fixture
def lines(monkeypatch):
    out = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO", *a, **k: out.append(str(msg)))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    return out


def _said(lines, words):
    return [m for m in lines if words in m]


def _load(chrome, page, report=None, after=None, outside=""):
    G.offline(chrome, page)
    chrome.run(page.set_content(G.report_page(
        G.recorded_report() if report is None else report,
        after=G.recorded_sources() if after is None else after, outside=outside)))


def _extract(chrome, page, report=None, after=None, outside=""):
    _load(chrome, page, report, after, outside)
    return chrome.run(research.extract_gemini_response(page))


def _panel_html(chrome, page):
    return chrome.run(page.evaluate(
        "() => [...document.querySelectorAll('immersive-panel')].pop().innerHTML"))


def _today(chrome, page):
    """What Gemini's extraction wrote before this change, from the page as it is
    now: the panel converted as every HTML read converts it, then its noise strip."""
    return research._strip_gemini_panel_noise(research.html_to_markdown(_panel_html(chrome, page)))


def _rows(doc):
    """This file's own reading of the one Sources list: [(number, url, title)],
    url "" for a row listed by its title only."""
    assert doc.count(TAIL) == 1, "not exactly one Sources list"
    out = []
    for line in doc[doc.index(TAIL) + len(TAIL):].rstrip("\n").split("\n"):
        m = ROW_RE.fullmatch(line)
        assert m, line
        out.append((int(m["n"]), m["u"] or "", m["t"] if m["u"] else m["p"]))
    return out


def _paragraph(doc, words):
    start = doc.index(words)
    return doc[start: doc.index("\n", start)]


def _state(chrome, page):
    """The used list's toggle and rows as the page shows them right now."""
    return chrome.run(page.evaluate("""() => {
        const b = document.querySelector(
            'collapsible-button[data-test-id="used-sources-button"] button');
        return {expanded: b.getAttribute('aria-expanded'),
                rows: document.querySelectorAll('div.used-sources browse-web-item').length,
                presses: document.body.dataset.srPresses || null, url: location.href};
    }"""))


# ═══ 1. Each chip opens row N ════════════════════════════════════════════════

def test_the_chips_the_owner_hovered_open_the_cards_that_opened(chrome, page, fast, lines):
    """⭐⭐ THROUGH THE REAL EXTRACTION AND THE REAL WRITE. The paragraph the owner
    hovered: index 1 opens row 1, index 3 opens row 3 — the numbers written are
    the indexes, not the 1 and 2 the page shows — and every other chip opens its
    own row, by its place in the list."""
    # What the rule stands on, read off the recording's excerpt (never off the
    # code under test): 66 rows; every index within them; the hovered
    # paragraph's chips are index 1 and 3 and SHOW 1 and 2; the cards that
    # opened carry rows 1 and 3's addresses.
    assert len(USED) == 66 and REC["unusedCount"] == 136
    assert max(int(c["index"]) for c in REC["chips"]) == 64 and len(REC["chips"]) == 118
    hovered = [c for c in REC["chips"] if c["before"].startswith(HOVERED_WORDS[:60])]
    assert [(c["index"], c["shows"]) for c in hovered] == [("1", "1"), ("3", "2")]
    assert {c["href"] for c in REC["cards"]} == set(HOVERED.values())
    assert {n: USED[n - 1]["href"] for n in HOVERED} == HOVERED
    assert {n for n, r in enumerate(USED, 1) if "cdn.openai.com" in r["href"]} == NOT_LISTED
    md = _extract(chrome, page)
    assert md, lines
    out = research._number_document_sources(md, [], ["https://visited.example.org/x"],
                                            label="Gemini")
    assert _paragraph(out, HOVERED_WORDS) == (
        HOVERED_WORDS + "[\\[1\\]](https://openai.com/index/built-to-benefit-everyone/)"
        "[\\[3\\]](https://openai.com/our-structure/)")
    body = out[:out.index(TAIL)]
    links = MARKER_RE.findall(body)
    assert len(links) == 116, len(links)
    for n, url in links:
        assert url == USED[int(n) - 1]["href"], (n, url)
    want = [c["index"] for c in REC["chips"] if int(c["index"]) not in NOT_LISTED]
    assert [n for n, _u in links] == want
    assert [int(n) for n in OWN_RE.findall(body)] == [30, 58]
    assert out.count("##### Sources") == 1 and "visited.example.org" not in out
    assert _said(lines, "[Gemini] linked 116 of its own citation numbers to its own sources "
                        "list (64 rows) — 2 numbers whose row has no link stay as written")
    # The crash-retry read-back hands over what the extraction did.
    assert research._document_without_sources(out) == md


def test_the_one_sources_section_is_geminis_list_in_its_order(chrome, page, fast, lines):
    """⭐⭐ The document ends with ONE "Sources" list: all 66 of Gemini's rows, in
    its order, row N as number N, each with its own title and address — the two
    on an agent's own host by their title only — and nothing of "Sources read but
    not used in the report" or the thoughts after it."""
    md = _extract(chrome, page)
    rows = _rows(md)
    assert [n for n, _u, _t in rows] == list(range(1, 67))
    for n, url, title in rows:
        assert title == G.row_words(USED[n - 1]["text"])[1], n
        assert url == ("" if n in NOT_LISTED else USED[n - 1]["href"]), n
    assert "cdn.openai.com" not in md
    for r in REC["unused"]:
        assert r["href"] not in md
    assert "Sources used in the report" not in md and "Researching websites" not in md
    assert "read but not used" not in md
    assert _said(lines, "[Gemini] Gemini's own citation numbers, from its own list: 118 "
                        "citation chips and 0 written marks naming 30 numbers, 1 to 64 with "
                        "gaps; its 66 sources listed in its order, row N as number N")


def test_a_list_exactly_as_long_as_the_highest_number_is_enough(chrome, page, fast, lines):
    """The highest number cited is 64: a list of 64 rows has a row for each."""
    md = _extract(chrome, page, after=G.recorded_sources(USED[:64]))
    assert [n for n, _u, _t in _rows(md)] == list(range(1, 65))


def test_a_rows_inner_element_of_the_same_kind_is_the_same_row(chrome, page, fast, lines):
    """A row element inside a row is that row, not the next one: every number
    still opens its own row."""
    rows = [G.recorded_row(r["href"], r["text"]) for r in USED]
    rows[4] = rows[4].replace("<a ", "<browse-web-item><a ", 1).replace(
        "</a>", "</a></browse-web-item>", 1)
    md = _extract(chrome, page, after=G.recorded_sources(rows))
    assert [(n, u) for n, u, _t in _rows(md)] == [
        (n, "" if n in NOT_LISTED else r["href"]) for n, r in enumerate(USED, 1)]


@pytest.mark.parametrize("second", ["titled-otherwise", "none"])
def test_the_list_ends_where_its_own_box_ends(chrome, page, fast, lines, second):
    """⭐ The list ends where the box holding its rows ends (the recorded
    `div.source-list.used-sources`), not at the next list's title. With that
    title worded otherwise, the other list's rows are not this list's; with no
    second list, nor are the thinking trace's site links after it. Either way the
    one Sources list is Gemini's 66 rows, every number its own. (Before: 72 rows,
    the other list's after them; or, with no second list, no number linked.)"""
    after = (G.recorded_sources(unused_title=OTHER_TITLE) if second != "none" else
             G.recorded_sources(unused_title=None,
                                thoughts="".join(G.chip_link(i) for i in range(3))))
    md = _extract(chrome, page, after=after)
    assert [(n, u) for n, u, _t in _rows(md)] == [
        (n, "" if n in NOT_LISTED else r["href"]) for n, r in enumerate(USED, 1)]
    for r in REC["unused"]:
        assert r["href"] not in md
    assert _said(lines, "its 66 sources listed in its order")


def test_spaces_and_notes_between_rows_are_not_words(chrome, page, fast, lines):
    """Between its rows the recorded list holds Angular's empty notes
    (`<!---->`). Spaces, a line break, or a note with words in it there
    (ASSUMED) are neither a row nor words in no row: the list is still joined."""
    rows = [G.recorded_row(r["href"], r["text"]) for r in USED]
    rows[3] += "\n   <!--ng-container *ngFor=\"let source of sources\"-->\n  "
    md = _extract(chrome, page, after=G.recorded_sources(rows))
    assert [(n, u) for n, u, _t in _rows(md)] == [
        (n, "" if n in NOT_LISTED else r["href"]) for n, r in enumerate(USED, 1)]


def test_a_number_past_the_list_never_opens_the_next_lists_row(chrome, page, fast, lines):
    """⛔ With the next list's title worded otherwise, a number one past the end
    of Gemini's list (67, of 66 rows) is past its end — never the other list's
    first row."""
    report = G.recorded_report(extra=f"<p>One more claim.{G.recorded_chip(67)}</p>")
    md = _extract(chrome, page, report=report, after=G.recorded_sources(unused_title=OTHER_TITLE))
    assert md == _today(chrome, page)
    assert REC["unused"][0]["href"] not in md
    said = _said(lines, "[Gemini] Gemini's citations stay as they are: ")
    assert len(said) == 1 and "number 67 is past the end of its list" in said[0], said


def test_a_closed_list_never_takes_the_next_lists_rows(chrome, page, fast, lines):
    """⛔⛔ Closed, the next list's title worded otherwise, and the press never
    answered: the only rows after the toggle are the OTHER list's (here as many
    as Gemini's own: ASSUMED). Read as this list's, every number would open the
    wrong page. That list's title is words in no row, so the document is today's.
    (Before, the toggle was not even pressed, and every number opened a row of
    the other list.)"""
    other = USED[::-1]
    md = _extract(chrome, page, after=G.recorded_sources(closed=True, unused=other,
                                                         unused_title=OTHER_TITLE))
    assert md == _today(chrome, page)
    said = _said(lines, "[Gemini] Gemini's citations stay as they are: ")
    assert len(said) == 1 and "words in its list are in no row" in said[0], said
    assert _said(lines, "pressed it open, but it showed no row")


def test_a_tables_raw_marks_are_the_same_numbers(chrome, page, fast, lines):
    """Where Gemini draws no chip (a table, in the 10-01 recording) it leaves its
    raw mark, "[cite: 5, 13]": the same numbers, glued to the word before them,
    each opening its own row. Inside code a mark is the code's own text."""
    table = ("<table><thead><tr><th>Claim</th><th>Evidence</th></tr></thead><tbody>"
             "<tr><td>Restructured in 2025</td><td>Filings [cite: 5, 13]</td></tr></tbody>"
             "</table><pre><code>| claim | [cite: 2] |</code></pre>")
    md = _extract(chrome, page, report=G.recorded_report(extra=table))
    assert "| Filings\\[5\\]\\[13\\] |" in md and "| claim | [cite: 2] |" in md
    out = research._number_document_sources(md, [], [], label="Gemini")
    assert (f"Filings[\\[5\\]]({USED[4]['href']})[\\[13\\]]({USED[12]['href']})" in out)


def test_a_row_on_the_owners_own_drive_is_listed_by_its_title_only(chrome, page, fast, lines):
    """⛔ Gemini reads Drive and Gmail. A row opening the owner's own file is
    listed by its title only — its address never reaches the document — and its
    number stays text at the write; every other number links."""
    private = "https://docs.google.com/document/d/abc123/edit"
    rows = [dict(USED[0]), dict(USED[1], href=private)] + USED[2:]
    md = _extract(chrome, page, after=G.recorded_sources(rows))
    assert "docs.google.com" not in md and "abc123" not in md
    assert "\n- Who owns OpenAI? Ownership structure explained (2026) — cited as 2\n" in md
    out = research._number_document_sources(md, [], [], label="Gemini")
    nums = {int(n) for n, _u in MARKER_RE.findall(out)}
    assert 2 not in nums and 1 in nums and 3 in nums
    assert "\\[2\\]" in out[:out.index(TAIL)]


# ═══ 2. A closed list is opened for the read, and closed again ═══════════════

def test_a_closed_list_is_opened_by_its_own_toggle_and_closed_again(chrome, page, fast, lines):
    """⭐⭐ The list closed, as the 10-01 recording found it (its rows are not in
    the page). The read presses its toggle, waits for its rows, reads exactly
    what the open list gives — and presses it again, so the page is as it was
    found: closed, no row, the same address, two presses."""
    open_md = _extract(chrome, page)
    lines.clear()
    md = _extract(chrome, page, report=G.recorded_report(extra=BODY_LINK),
                  after=G.recorded_sources(closed=True), outside=G.toggle_script())
    assert _state(chrome, page) == {"expanded": "false", "rows": 0, "presses": "2",
                                    "url": "about:blank"}
    # The same document as the open list gives, but for the report's own link.
    assert md.replace("\n\n" + _paragraph(md, "The plugin model"), "", 1) == open_md
    assert _said(lines, "[Gemini] Gemini's \"Sources used in the report\" was closed — "
                        "opened it for the read (66 rows)")
    assert _said(lines, "[Gemini] Gemini's \"Sources used in the report\" closed again, "
                        "as it was found")


@pytest.mark.parametrize("name", ["open", "cites-nothing", "says-open", "in-a-link",
                                  "two-toggles"])
def test_the_toggle_is_left_alone(chrome, page, fast, lines, name):
    """⛔ The toggle is pressed only to open a closed list of a report that cites:
    never an open list, never for a report citing nothing, never a list that says
    it is open, never a toggle inside a link, never when there are two. (First,
    the same closed page with none of these IS pressed, twice.)"""
    report, after = G.recorded_report(), G.recorded_sources(closed=True)
    _extract(chrome, page, report=report, after=after, outside=G.toggle_script())
    assert _state(chrome, page)["presses"] == "2"
    lines.clear()
    if name == "open":
        after = G.recorded_sources()
    elif name == "cites-nothing":
        report = "<h1>Report</h1>" + "".join(f"<p>{G.prose(i)}</p>" for i in range(8))
    elif name == "says-open":
        after = after.replace('aria-expanded="false"', 'aria-expanded="true"', 1)
    elif name == "in-a-link":
        after = after.replace("<collapsible-button", "<a href='https://example.invalid/x'>"
                              "<collapsible-button", 1).replace(
            "</collapsible-button>", "</collapsible-button></a>", 1)
    else:
        after = after + after
    md = _extract(chrome, page, report=report, after=after, outside=G.toggle_script())
    assert _state(chrome, page)["presses"] == "0"
    if name == "open":
        assert len(_rows(md)) == 66
    else:
        assert md == _today(chrome, page)
    assert not _said(lines, "\"Sources used in the report\" was closed")


def test_a_list_that_does_not_open_keeps_todays_document(chrome, page, fast, lines):
    """⛔ A press that shows no row (here nothing answers it): the read goes on,
    the document is today's, and the line says the list showed no row. After
    the read the list is watched as long again; it stays closed, so it is not
    pressed again, and the line says it was left as it was found."""
    md = _extract(chrome, page, after=G.recorded_sources(closed=True))
    assert md == _today(chrome, page)
    assert _said(lines, "pressed it open, but it showed no row in 3 s")
    said = _said(lines, "[Gemini] Gemini's citations stay as they are: ")
    assert len(said) == 1 and "its list shows no row (a closed list?)" in said[0], said
    assert _said(lines, "[Gemini] Gemini's \"Sources used in the report\" stayed closed after "
                        "the read — left as it was found")
    assert not _said(lines, "closed again") and not _said(lines, "did not close again")


def test_a_list_that_opens_after_the_read_gave_up_is_closed_again(chrome, page, lines):
    """⛔ The list opens only after the read stopped waiting for its rows (the
    toggle answers a second after the read's own wait; NO `fast`: these are the
    run's real waits). The read goes on with today's document, and the close
    step keeps watching as long again: it presses the list the moment it shows,
    so the tab ends as it was found — closed, no row, two presses — and, as the
    list is still open when the close step's own wait ends, one warning says so.
    (Before, the close step looked once, saw nothing, and the list opened after
    it and stayed open.)"""
    wait = research._GEMINI_SOURCES_WAIT_S
    delay_ms = int(wait * 1000) + 1000
    md = _extract(chrome, page, after=G.recorded_sources(closed=True),
                  outside=G.toggle_script(delay_ms=delay_ms))
    assert _said(lines, f"pressed it open, but it showed no row in {wait:g} s")
    assert _said(lines, "[Gemini] Gemini's \"Sources used in the report\" did not close again")
    assert not _said(lines, "stayed closed after the read")
    # The close press's own answer comes `delay_ms` after it.
    for _ in range(int(delay_ms / 100) + 20):
        if _state(chrome, page)["expanded"] == "false":
            break
        chrome.run(asyncio.sleep(0.1))
    assert _state(chrome, page) == {"expanded": "false", "rows": 0, "presses": "2",
                                    "url": "about:blank"}
    assert md == _today(chrome, page)


@pytest.mark.parametrize("second", ["titled-otherwise", "none"])
def test_a_closed_list_is_opened_whatever_follows_it(chrome, page, fast, lines, second):
    """⭐ The toggle counts the rows in its own list's box, never every link
    after it. Closed, with the next list's title worded otherwise, or with no
    second list and the thinking trace's site links after it (the 18:45
    recording: 103 of them after both lists), the list shows no row: it is
    opened, read — Gemini's 66 rows, every number its own — and closed again.
    (Before, those links counted as its rows, and it was never opened.)"""
    assert REC["chipLinkCount"] == 103
    after = (G.recorded_sources(closed=True, unused_title=OTHER_TITLE) if second != "none" else
             G.recorded_sources(closed=True, unused_title=None,
                                thoughts="".join(G.chip_link(i) for i in range(3))))
    md = _extract(chrome, page, after=after, outside=G.toggle_script())
    assert _state(chrome, page) == {"expanded": "false", "rows": 0, "presses": "2",
                                    "url": "about:blank"}
    assert [(n, u) for n, u, _t in _rows(md)] == [
        (n, "" if n in NOT_LISTED else r["href"]) for n, r in enumerate(USED, 1)]
    assert _said(lines, "opened it for the read (66 rows)")


def test_a_list_that_opens_empty_is_closed_again(chrome, page, fast, lines):
    """A press that opens the list with no row in it: the toggle says open, so
    it is pressed again, and the read waits until it says closed."""
    md = _extract(chrome, page, after=G.recorded_sources(closed=True),
                  outside=G.toggle_script(rows=[]))
    assert _state(chrome, page) == {"expanded": "false", "rows": 0, "presses": "2",
                                    "url": "about:blank"}
    assert md == _today(chrome, page)
    assert _said(lines, "closed again, as it was found")


# ═══ 3. Any doubt keeps today's document ═════════════════════════════════════

def _variant(name):
    """A page that fails exactly one check — (report, sources, why)."""
    rows = [G.recorded_row(r["href"], r["text"]) for r in USED]
    report, why = G.recorded_report(), None
    if name == "list-shorter-than-a-number":
        return report, G.recorded_sources(USED[:63]), "number 64 is past the end of its list"
    if name in ("row-without-address", "row-not-a-web-address", "row-two-addresses"):
        old = f'href="{USED[4]["href"]}"'
        assert rows[4].count(old) == 1
        rows[4] = (rows[4].replace(old, "") if name == "row-without-address" else
                   rows[4].replace(old, 'href="/app/06be5842def539f5"')
                   if name == "row-not-a-web-address" else
                   rows[4].replace("</browse-web-item>",
                                   "<a href='https://other.example.org/x'>more</a>"
                                   "</browse-web-item>"))
        why = "row 5 of its list has no web address or more than one"
    elif name == "link-in-no-row":
        rows.insert(10, "<a href='https://loose.example.org/z'>Loose</a>")
        why = "a link in its list is in no row"
    elif name == "rows-of-another-kind":
        rows = [r.replace("browse-web-item", "div") for r in rows]
        why = "a link in its list is in no row"
    elif name == "row-of-another-kind-without-address":
        # ⛔ Row 5 drawn by another element, with no link (a file, say: ASSUMED —
        # in no recording). Skipped, every number from 5 on would open the row
        # after its own; its words are in no row.
        rows.insert(4, FILE_ROW)
        why = "words in its list are in no row (in <browse-file-item class>)"
    if why:
        return report, G.recorded_sources(rows), why
    if name == "number-0":
        return (G.recorded_report(extra=f"<p>One more claim.{G.recorded_chip(0)}</p>"),
                G.recorded_sources(), "a citation names number 0")
    if name == "mark-0":
        return (G.recorded_report(extra="<table><tbody><tr><td>Claim</td><td>Filing "
                                        "[cite: 0]</td></tr></tbody></table>"),
                G.recorded_sources(), "a citation names number 0")
    if name == "chip-without-number":
        return (G.recorded_report(extra=f"<p>One more claim.{G.recorded_chip(None)}</p>"),
                G.recorded_sources(), "a citation chip carries no number")
    if name == "no-list":
        return report, "", "the page holds no \"Sources used in the report\" list"
    if name == "after-a-bullet":
        return (G.recorded_report(extra=f"<ul><li>{G.recorded_chip(2)} opens the item</li></ul>"),
                G.recorded_sources(), "a citation comes right after a bullet")
    if name == "own-list-with-links":
        return (G.recorded_report(extra="<h2>Works cited</h2><ol><li><a href='https://own."
                                        "example.org/p'>Own</a></li></ol>"),
                G.recorded_sources(),
                "the report ends with a sources list of its own that holds links")
    if name == "at-a-line-start":
        return (G.recorded_report(extra=f"<p>Line one<br>{G.recorded_chip(2)}line two</p>"),
                G.recorded_sources(), "numbers would link at the write")
    raise AssertionError(name)


@pytest.mark.parametrize("name", [
    "list-shorter-than-a-number", "row-without-address", "row-not-a-web-address",
    "row-two-addresses", "link-in-no-row", "rows-of-another-kind",
    "row-of-another-kind-without-address", "number-0", "mark-0",
    "chip-without-number", "no-list", "after-a-bullet", "own-list-with-links",
    "at-a-line-start"])
def test_any_doubt_keeps_todays_document(chrome, page, fast, lines, name):
    """⛔ Each check, failed alone: no number and no list are written — the
    document is exactly today's — and one log line says which check."""
    report, sources, why = _variant(name)
    md = _extract(chrome, page, report=report, after=sources)
    assert md == _today(chrome, page)
    said = _said(lines, "[Gemini] Gemini's citations stay as they are: ")
    assert len(said) == 1 and why in said[0], (said, lines[-5:])
    assert not _said(lines, "Gemini's own citation numbers, from its own list")


def test_a_report_citing_nothing_says_nothing(chrome, page, fast, lines):
    """A report with no chip and no mark is today's document, and no line about
    citations is written — while the same page with one chip says why."""
    plain = "<h1>Report</h1>" + "".join(f"<p>{G.prose(i)}</p>" for i in range(8))
    md = _extract(chrome, page, report=plain)
    assert md == _today(chrome, page)
    assert not _said(lines, "Gemini's citations")
    _extract(chrome, page, report=plain + f"<p>Cited.{G.recorded_chip(70)}</p>")
    assert len(_said(lines, "Gemini's citations stay as they are")) == 1


def test_citations_only_inside_code_leave_nothing_to_number(chrome, page, fast, lines):
    """A report whose only citations are inside code has no number to write: it
    is today's document, and the line says so."""
    plain = ("<h1>Report</h1>" + "".join(f"<p>{G.prose(i)}</p>" for i in range(8))
             + "<pre><code>see [cite: 1]</code></pre>")
    md = _extract(chrome, page, report=plain)
    assert md == _today(chrome, page)
    assert _said(lines, "Gemini's citations stay as they are: no citation is left to number")


def test_a_link_less_works_cited_of_its_own_is_replaced(chrome, page, fast, lines):
    """One sources section: the report's own trailing "Works cited" with no link
    in it is replaced by Gemini's own list."""
    own = "<h2>Works cited</h2><ol><li>OpenAI's structure page</li><li>Quartz</li></ol>"
    md = _extract(chrome, page, report=G.recorded_report(extra=own))
    assert "Works cited" not in md and md.count("##### Sources") == 1
    assert _said(lines, "replaced by Gemini's own sources list")


def test_a_failure_while_reading_them_keeps_todays_document(chrome, page, fast, lines,
                                                           monkeypatch):
    """⛔ Anything that goes wrong while the citations are read leaves the document
    as it was, with one line."""
    def _boom(html, label="Gemini"):
        raise ValueError("unexpected markup")
    monkeypatch.setattr(research, "_gemini_footnoted", _boom)
    md = _extract(chrome, page)
    assert md == _today(chrome, page)
    assert _said(lines, "Gemini's citations stay as they are: they could not be read (ValueError)")


# ═══ 4. The write ════════════════════════════════════════════════════════════

def _own_list(rows, cites):
    return ("A claim." + "".join(f"\\[{n}\\]" for n in cites) + " More words follow it.\n\n"
            "##### Sources\n\n" + "\n".join(
                f"- [Row {i}](https://r{i}.example.org/) — r{i}.example.org — cited as {ns}"
                for i, ns in enumerate(rows, 1)) + "\n")


def test_the_write_links_a_list_that_counts_up_with_rows_nobody_cites(lines):
    """⭐ Gemini's list, one number on each row counting 1, 2, 3: a row the text
    does not cite is still its row, and each number cited opens its own row."""
    out = research._number_document_sources(_own_list(["1", "2", "3"], [3, 1]), [], [],
                                            label="Gemini")
    assert MARKER_RE.findall(out) == [("3", "https://r3.example.org/"),
                                      ("1", "https://r1.example.org/")]


@pytest.mark.parametrize("rows,cites,inside", [
    (["1", "2", "3"], [2, 4], [2]),       # a number past the end of the list
    (["1, 3", "2"], [1, 3], [1, 3]),      # rows naming several numbers (ChatGPT's shape)
    (["1", "3"], [1], [1]),               # rows that skip a number
], ids=["number-past-the-end", "several-on-a-row", "rows-skip"])
def test_any_other_list_still_matches_one_for_one(lines, rows, cites, inside):
    """⛔ Only a list counting 1, 2, 3, one number on each row, may have rows
    nobody cites — and even there every number cited needs its row. Any other
    list links nothing unless the numbers and its rows match one for one. (The
    numbers within it, against a list counting 1, 2, 3, do link.)"""
    counting = research._number_document_sources(_own_list(["1", "2", "3"], inside), [], [],
                                                 label="Gemini")
    assert [int(n) for n, _u in MARKER_RE.findall(counting)] == inside
    md = _own_list(rows, cites)
    assert research._number_document_sources(md, [], [], label="Gemini") == md
    assert _said(lines, "left its own citation numbers as written")


# ═══ 5. Through the real save ════════════════════════════════════════════════

def test_the_saved_document_and_its_cloud_copy_carry_the_links(chrome, page, fast, lines,
                                                              monkeypatch, tmp_path):
    """⭐⭐ THROUGH THE REAL WRITE, with the list closed as the owner's runs find
    it: the per-agent save writes Gemini's numbers linked to its own rows and its
    one list — on disk and in the copy the app reads — and the sites the run
    tracked are NOT added after it."""
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
    _load(chrome, page, after=G.recorded_sources(closed=True), outside=G.toggle_script())

    class _Browser:
        async def switch_to_page(self, p):
            return None
    res = chrome.run(research.extract_and_record_agent("Gemini", page, _Browser(), None, tmp_path))
    local = (tmp_path / "documents" / "gemini.md").read_text(encoding="utf-8")
    assert res["status"] == "done"
    assert [d["content"] for p, d in sink if p.endswith("/documents/gemini")] == [local]
    assert "visited-only" not in local and local.count("\n##### Sources\n") == 1
    assert _paragraph(local, HOVERED_WORDS) == (
        HOVERED_WORDS + "[\\[1\\]](https://openai.com/index/built-to-benefit-everyone/)"
        "[\\[3\\]](https://openai.com/our-structure/)")
    links = MARKER_RE.findall(local)
    assert len(links) == 116 and all(u == USED[int(n) - 1]["href"] for n, u in links)
    assert _state(chrome, page)["presses"] == "2"


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
