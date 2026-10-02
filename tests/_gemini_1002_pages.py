"""A local gemini.google.com report page, built from the owner's 10-02 recording,
for headless Chrome.

The recording (`fixtures/gemini_1002/report_recording.json`, an excerpt of
#Dev/wave14/recordings-1001/sr-cite-gemini-report.json, snapshot "report") is a
census of a finished Deep Research report in Gemini's side panel. What it SHOWS
is taken from it, markup for markup:

  * the panel: `<immersive-panel>` with its own attributes (`panel.attrs`);
  * every equation's element, verbatim (`math.sample[].html`): `div.math-block`
    and `span.math-inline` with the TeX in `data-math` and KaTeX's drawing
    inside, and where each one sat (a display one in a `data-path-to-node` div,
    an inline one at the START of a list item's text — `data-index-in-node=0`
    under `data-path-to-node=162,0,0,0`). The recorder cut each element's HTML at
    2,500 characters; a cut one is closed again here (`_closed`), its own
    attributes and every box before the cut untouched;
  * a citation chip, verbatim (`citeLike.sample`): `<source-footnote>` holding an
    empty `<sup class="superscript" data-turn-source-index="N">`, inside a
    `response-element`;
  * the raw marks Gemini leaves in text it did not draw as chips
    (`rawCiteSample`: "[cite: 5, 13]");
  * the two sources sections, each opened by a BUTTON with its title
    (`openCards`: "Sources used in the report", "Sources read but not used in
    the report").

The SOURCES LISTS come from the owner's later recording of the same day
(`fixtures/gemini_1002/sources_open_recording.json`, an excerpt of
sr-gemini-sources-open.json, 18:45Z, both lists opened): the section's own
markup up to its first row, verbatim (`head`: `<deep-research-source-lists>`,
the toggle `collapsible-button[data-test-id="used-sources-button"] > button
[aria-expanded]` titled "Sources used in the report", and the open list's
`div.source-list.used-sources`); one row verbatim (`row`: a `<browse-web-item>`
holding one `a[data-test-id="browse-web-item-link"]` with its host and its
`sub-title`); and every row's address and words, in page order (`used`: 66,
`unused`: the first 6 of 136). Each row here is that recorded row with its own
address, host and title put in (`recorded_row`). The recording's 118 chips are
there too, in order: each one's index, the number it SHOWS, its class and the
first words of the block it sits in (`chips`); and the first three of the 103
site links the thinking trace holds after both lists, each an `a` with
`data-test-id="browse-chip-link"` (`chipLinks`, `chip_link`).

ASSUMED, and said so where it is built: the report's words, its headings and
tables, where a chip stands in a sentence, the markup of "Sources read but not
used in the report" (the recording cut the section's HTML before it: here it is
the used list's own markup with its own title), and what a press of the toggle
does to the page (a closed list's rows are not in the page — the 10-01
recording, `usedRows` empty — and a press puts them in, a little later).
"""
from __future__ import annotations

import base64
import html
import json
import re
from functools import lru_cache
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures" / "gemini_1002"


@lru_cache(maxsize=None)
def recording() -> dict:
    return json.loads((FIX / "report_recording.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def katex_samples() -> list:
    return json.loads((FIX / "katex_samples.json").read_text(encoding="utf-8"))["samples"]


def _closed(fragment: str) -> str:
    """A fragment the recorder cut, with its open elements closed again."""
    from bs4 import BeautifulSoup
    return str(BeautifulSoup(fragment, "html.parser"))


def math_samples() -> list:
    """Each recorded equation: {"tex", "block", "html"} — the TeX read from the
    recorded `data-math` attribute, never from code under test."""
    out = []
    for s in recording()["math"]["sample"]:
        attrs = dict(a.split("=", 1) for a in s["attrs"])
        out.append({"tex": attrs["data-math"], "block": attrs["class"] == "math-block",
                    "html": _closed(s["html"])})
    return out


def chip(n: int) -> str:
    """The recorded chip markup, with source number `n`, inside the element the
    recording shows as its parent (one each: ASSUMED)."""
    sample = recording()["citeLike"]["sample"][0]
    rec = sample["html"]
    assert 'data-turn-source-index="1"' in rec
    parent = dict(a.split("=", 1) for a in sample["parent"]["attrs"])
    assert sample["parent"]["tag"] == "response-element"
    return (f'<response-element class="{parent["class"]}" ng-version="{parent["ng-version"]}">'
            + rec.replace('data-turn-source-index="1"', f'data-turn-source-index="{int(n)}"')
            + "</response-element>")


def chips(*ns: int) -> str:
    """A run of chips as one `[cite: a, b]` mark draws them: one after another."""
    return "".join(chip(n) for n in ns)


def panel_attrs() -> str:
    parts = []
    for a in recording()["panel"]["attrs"]:
        k, _, v = a.partition("=")
        parts.append(f'{k}="{html.escape(v, quote=True)}"')
    return " ".join(parts)


def prose(i: int, words: int = 70) -> str:
    """A paragraph of ASSUMED report words, different for each `i`."""
    base = (f"Paragraph {i} of the report discusses the evaluated system, its "
            f"measured latency, its calibration and the evidence behind each claim. ")
    text = (base * (words // 20 + 1)).split()
    return " ".join(text[:words])


#: A 1×1 PNG, for any picture a page asks the network for.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def offline(chrome, page, pictures=()):
    """Every request the page makes is answered here, never by the network: an
    address in `pictures` gets a PNG, anything else is refused."""
    wanted = set(pictures)

    async def _answer(route):
        if route.request.url in wanted:
            await route.fulfill(status=200, content_type="image/png", body=PNG_1PX)
        else:
            await route.abort()
    chrome.run(page.unroute("**/*"))
    chrome.run(page.route("**/*", _answer))


@lru_cache(maxsize=None)
def sources_recording() -> dict:
    return json.loads((FIX / "sources_open_recording.json").read_text(encoding="utf-8"))


_OPENS = " Opens in a new window"
#: Where a row's site icon is asked for: a name that never resolves, and that
#: `offline` refuses anyway.
ICON = "https://icons.sr-fixture.invalid/favicon.png"
USED_TITLE = "Sources used in the report"
UNUSED_TITLE = "Sources read but not used in the report"


def row_words(text: str) -> tuple:
    """A recorded row's words as (host, title): the recorder read each row as
    "<host> <title> Opens in a new window" (checked against every whole row of
    the recorded HTML when the fixture was cut)."""
    assert text.endswith(_OPENS), text
    host, _, title = text[: -len(_OPENS)].partition(" ")
    return host, title


def recorded_row(href: str, text: str) -> str:
    """The recorded row, verbatim, with this row's address, host and title put
    in (and its site icon asked of `ICON`)."""
    rec = sources_recording()
    row, first = rec["row"], rec["used"][0]
    host0, title0 = row_words(first["text"])
    icon = re.search(r'class="favicon" src="([^"]*)"', row).group(1)
    host, title = row_words(text)
    for old, new in ((f'href="{first["href"]}"', f'href="{html.escape(href, quote=True)}"'),
                     (f'src="{icon}"', f'src="{ICON}"'),
                     (f">{html.escape(host0)}</div>", f">{html.escape(host)}</div>"),
                     (f">{html.escape(title0)}</div>", f">{html.escape(title)}</div>")):
        assert row.count(old) == 1, old
        row = row.replace(old, new)
    return row


def _parts() -> tuple:
    """The recorded section's head, cut where it is made of: the
    `<deep-research-source-lists>` tag, the used list's toggle, and the open
    list's own element (its rows follow it)."""
    head = sources_recording()["head"]
    start = head.index("<collapsible-button")
    end = head.index("</collapsible-button>") + len("</collapsible-button>")
    return head[:start], head[start:end], head[end:]


def used_list(rows=None) -> str:
    """The open list's own element with its rows — each a recorded row
    ({"href", "text"}) or markup as given; all 66 recorded rows by default."""
    rec = sources_recording()
    rows = rec["used"] if rows is None else rows
    body = rec["between"].join(r if isinstance(r, str) else recorded_row(r["href"], r["text"])
                               for r in rows)
    return _parts()[2] + body + "</div>"


def recorded_sources(rows=None, *, closed: bool = False, unused=None,
                     unused_title=UNUSED_TITLE, thoughts: str = "") -> str:
    """Gemini's two sources lists as the recording shows them, then its
    "Thoughts". `closed`: the used list as a closed one is — its toggle says so
    and its rows are not in the page. ASSUMED: "read but not used" is the used
    list's own markup with its own title (open, as it was in the recording).
    `unused`: that list's rows (as `used_list` takes them; the recorded 6 by
    default), `unused_title` its title (None: the page has no second list), and
    `thoughts` markup in the thinking trace after its words."""
    rec = sources_recording()
    opening, toggle, list_open = _parts()
    assert toggle.count('aria-expanded="true"') == 1
    unused_rows = rec["unused"] if unused is None else unused
    second = ""
    if unused_title is not None:
        unused_toggle = (toggle.replace(f">{USED_TITLE}<", f">{html.escape(unused_title)}<")
                         .replace("used-sources", "unused-sources"))
        second = (unused_toggle + list_open.replace("used-sources", "unused-sources")
                  + rec["between"].join(r if isinstance(r, str) else
                                        recorded_row(r["href"], r["text"]) for r in unused_rows)
                  + "</div>")
    used = (toggle.replace('aria-expanded="true"', 'aria-expanded="false"') if closed
            else toggle + used_list(rows))
    return (opening + used + second + "</deep-research-source-lists>"
            "<div class='thoughts'><button>Thoughts</button><p>Researching websites…</p>"
            + thoughts + "</div>")


def chip_link(n: int = 0) -> str:
    """The thinking trace's site link: the 18:45 recording holds 103 of them,
    after both lists, each an `a` carrying `data-test-id="browse-chip-link"` and
    its address (`chipLinks`: the first three). ASSUMED: the rest of its markup —
    here its recorded words alone."""
    rec = sources_recording()["chipLinks"][n]
    assert rec["attrs"][0] == "data-test-id=browse-chip-link", rec
    return (f'<a data-test-id="browse-chip-link" href="{html.escape(rec["href"], quote=True)}">'
            f'{html.escape(rec["text"])}</a>')


def toggle_script(rows=None, delay_ms: int = 150) -> str:
    """ASSUMED: what a press of the used list's toggle does, as Angular does it —
    a little later the list's element with its rows goes in after the toggle (or
    comes out again), and the toggle says which. Every press is counted on
    `<body data-sr-presses>`. Goes OUTSIDE the panel: the read never sees it."""
    rows_js = json.dumps(used_list(rows)).replace("</", "<\\/")
    return ("<script>(() => { const ROWS = %s; document.body.dataset.srPresses = '0';"
            "document.addEventListener('click', (ev) => {"
            " const b = ev.target.closest("
            "'collapsible-button[data-test-id=\"used-sources-button\"] button');"
            " if (!b) return;"
            " document.body.dataset.srPresses = String(+document.body.dataset.srPresses + 1);"
            " setTimeout(() => { const host = b.closest('collapsible-button');"
            "  const list = host.nextElementSibling;"
            "  if (list && list.matches('div.used-sources')) {"
            "   list.remove(); b.setAttribute('aria-expanded', 'false'); }"
            "  else { host.insertAdjacentHTML('afterend', ROWS);"
            "   b.setAttribute('aria-expanded', 'true'); } }, %d); }, true); })();</script>"
            % (rows_js, int(delay_ms)))


def recorded_chip(index, cls: str = "superscript", shows: str = "") -> str:
    """The recorded chip (`chip`), with this chip's index (None: no index at
    all), its class and the number it SHOWS — a chip drawn with a number is
    `superscript visible` holding " 1 " (the 10-01 `numberish` sample; the 18:45
    recording's hovered chips)."""
    out = chip(1)
    old = 'class="superscript" data-turn-source-index="1"><!----></sup>'
    assert out.count(old) == 1
    attr = "" if index is None else f' data-turn-source-index="{html.escape(str(index))}"'
    inner = f" {html.escape(shows)} <!---->" if shows else "<!---->"
    return out.replace(old, f'class="{html.escape(cls)}"{attr}>{inner}</sup>')


def recorded_report(chips=None, extra: str = "") -> str:
    """The report as the recording's chips cite it: one paragraph per block the
    recorder saw chips in (its first words, `before`), in order, with that
    block's chips after its words. ASSUMED: the headings, that a chip stands at
    its block's end, and the full stop after the words (a long block's words
    were cut at 120 characters by the recorder)."""
    chips = sources_recording()["chips"] if chips is None else chips
    blocks: dict = {}
    for c in chips:
        blocks.setdefault(c["before"], []).append(c)
    paras = [f"<p>{html.escape(words.rstrip(' .'))}."
             + "".join(recorded_chip(c["index"], c["cls"], c["shows"]) for c in cs) + "</p>"
             for words, cs in blocks.items()]
    half = len(paras) // 2
    return ("<h1>Corporate Governance and Capital Reorganization</h1><h2>Structure</h2>"
            + "".join(paras[:half]) + "<h2>Safety and litigation</h2>" + "".join(paras[half:])
            + extra)


def report_page(report_html: str, *, after: str = "", outside: str = "") -> str:
    """The whole page: the chat side (ASSUMED, short), the side panel holding its
    toolbar, the report, and `after` (the sources sections), and `outside`
    after the panel."""
    toolbar = ('<div class="toolbar"><span>Contents</span>'
               '<button aria-label="Share and export">Share and export</button>'
               '<button>Create</button></div>')
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Gemini</title></head>"
            "<body><chat-window><div class='conversation'><user-query>Research the "
            "system.</user-query><model-response>I've completed your research. Feel free "
            "to ask me follow-up questions or request changes.</model-response></div>"
            f"</chat-window><immersive-panel {panel_attrs()}>{toolbar}"
            f"<div class='markdown markdown-main-panel'>{report_html}</div>{after}"
            f"</immersive-panel>{outside}</body></html>")
