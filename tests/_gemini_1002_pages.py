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

ASSUMED, and said so where it is built: the report's words, its headings and
tables, where a chip stands in a sentence, and every row of a sources section —
the recording holds none (`usedRows` is empty: the section was closed).
"""
from __future__ import annotations

import html
import json
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


def sources_section(title: str, rows: list) -> str:
    """A sources section as ASSUMED markup: the recorded button with its title,
    then one row per source — `rows` are (url, title, attrs[, inner]) where
    `attrs` is extra row markup (e.g. a number attribute), or "" for none, and
    `inner` more markup inside the row after its link."""
    body = "".join(
        f'<div class="source-row" {r[2]}><a href="{html.escape(r[0], quote=True)}" '
        f'target="_blank"><img src="https://www.google.com/s2/favicons?domain=x.example" '
        f'width="16" height="16" alt=""><span class="title">{html.escape(r[1])}</span>'
        f'<span class="host">{html.escape(r[0].split("/")[2])}</span></a>'
        f'{r[3] if len(r) > 3 else ""}</div>'
        for r in rows)
    return (f'<div class="sources-section"><button class="mat-mdc-tooltip-trigger">'
            f'<span><span>{html.escape(title)}</span></span></button>'
            f'<div class="rows">{body}</div></div>')


def report_page(report_html: str, *, after: str = "") -> str:
    """The whole page: the chat side (ASSUMED, short), and the side panel holding
    its toolbar, the report, and `after` (the sources sections)."""
    toolbar = ('<div class="toolbar"><span>Contents</span>'
               '<button aria-label="Share and export">Share and export</button>'
               '<button>Create</button></div>')
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Gemini</title></head>"
            "<body><chat-window><div class='conversation'><user-query>Research the "
            "system.</user-query><model-response>I've completed your research. Feel free "
            "to ask me follow-up questions or request changes.</model-response></div>"
            f"</chat-window><immersive-panel {panel_attrs()}>{toolbar}"
            f"<div class='markdown markdown-main-panel'>{report_html}</div>{after}"
            "</immersive-panel></body></html>")
