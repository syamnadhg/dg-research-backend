"""Wave 14, 2026-10-02 — a report's pictures land in the saved document as images.

Owner, 10-01: "if there are any images, make sure to grab those images as well
into this. Diagrams, images, graphs and stuff."

What every page read did with a picture in the report, before this (each case
below is one of them, on a page in real headless Chrome, through the production
read and save):
  · `<img>` with a web address — kept by the image rehost (unchanged here);
  · `<img>` with the page's own `blob:` address — no one but the page can read it:
    LOST;
  · a chart or diagram drawn as `<svg>` — the converter wrote the words inside it
    (axis labels, node names) as loose prose; ChatGPT's frame read removed it;
  · a chart on a `<canvas>` — nothing at all.
Now the page draws each into a PNG before the report is read, and the rehost
stores it to the research's own images like any other.

⚠ ASSUMED: the pictures' markup (no recording of an agent's report holds a chart);
the report pages are `_gemini_1002_pages.report_page` (the recorded Gemini panel)
and Claude's artifact panel as its page read selects it. Nothing leaves the
machine: pages come from `page.set_content`, and an address on another site is
answered by a local route.
"""
import asyncio
import base64
import re
import struct
import time

import research
import test_chatgpt_new_page_0928 as base
import test_document_images_0913 as images
import _gemini_1002_pages as G
from test_footnotes_1001 import _firestore

chrome = base.chrome
page = base.page
fast = base.fast
#: The image rehost's own test world: a research, a token, a fake web that stores.
world = images.world

#: A bar chart as an svg: its colours come from the page's stylesheet, its words
#: are its axis labels.
SVG_CHART = (
    '<svg class="chart" viewBox="0 0 400 200" width="400" height="200" role="img" '
    'aria-label="Revenue by quarter"><g class="bars">'
    '<rect class="bar" x="20" y="60" width="60" height="120"></rect>'
    '<rect class="bar" x="120" y="30" width="60" height="150"></rect></g>'
    '<text x="30" y="195">Q1 revenue</text><text x="130" y="195">Q2 revenue</text></svg>')
STYLE = ("<style>.chart .bar{fill:rgb(200,30,30)} .chart text{font:12px sans-serif;"
         "fill:#222} figure{background:rgb(250,245,230)}</style>")
#: A chart on a canvas, drawn by the page's own script; and a picture the page
#: made itself, shown from its own `blob:` address.
SCRIPT = """<script>
const c = document.getElementById('cv'), g = c.getContext('2d');
g.fillStyle = 'rgb(20,120,220)'; g.fillRect(10, 10, 120, 80);
const m = document.createElement('canvas'); m.width = 160; m.height = 90;
const h = m.getContext('2d'); h.fillStyle = 'rgb(30,160,60)'; h.fillRect(0, 0, 160, 90);
m.toBlob((b) => {
  const img = document.getElementById('blobimg');
  img.onload = () => { document.body.dataset.ready = '1'; };
  img.src = URL.createObjectURL(b);
}, 'image/png');
</script>"""
ICON = ('<button aria-label="Copy"><svg width="64" height="64" viewBox="0 0 24 24">'
        '<path d="M0 0h24v24H0z"></path></svg></button>'
        '<svg width="16" height="16"><circle cx="8" cy="8" r="6"></circle></svg>')
MERMAID = ("<pre><code class='language-mermaid'>flowchart TD\n    A[Collateral] --&gt; "
           "B[Position]</code></pre>")
#: A picture with a web address (answered locally).
PHOTO = "https://img.sr-fixture.invalid/photo.png"


def _report(extra=""):
    sq = G.katex_samples()[2]
    return ("<h1>Quarterly Review</h1><h2>Revenue</h2>"
            f"<p>{G.prose(1)}</p><figure>{SVG_CHART}</figure><p>{G.prose(2)}</p>"
            '<canvas id="cv" width="300" height="150" style="width:300px;height:150px"></canvas>'
            f"<p>{G.prose(3)} The distance is {sq['html']} in the plane.</p>"
            '<img id="blobimg" alt="Margin trend" width="160" height="90">'
            f"<p>{G.prose(4)}</p>{ICON}{MERMAID}<p>{G.prose(5)}</p>{extra}")


def _page(report):
    return G.report_page(report).replace("</head>", STYLE + "</head>").replace(
        "</body>", SCRIPT + "</body>")


def _load(chrome, page, report, pictures=()):
    G.offline(chrome, page, pictures)
    chrome.run(page.set_content(_page(report)))
    chrome.run(page.wait_for_function("() => document.body.dataset.ready === '1'"))


def _png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


class _Browser:
    async def switch_to_page(self, p):
        return None


def test_every_picture_in_a_gemini_report_reaches_the_saved_document(
        chrome, page, fast, world, monkeypatch, tmp_path):
    """⭐⭐ THROUGH THE REAL READ AND THE REAL SAVE. The svg chart, the canvas
    chart and the page's own blob picture are each drawn by the page, stored by
    the rehost (one upload each, a PNG at twice the size it is shown), and the
    saved document — on disk and in the copy the app reads — shows each as an
    image where it stood. The chart's words are in the picture, not loose in the
    text; an icon and a control's glyph are no picture; the equation stays an
    equation and the mermaid code stays code."""
    sink = _firestore(monkeypatch)
    runtime = research.PipelineRuntime()
    monkeypatch.setattr(research, "_runtime", runtime, raising=False)
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    _load(chrome, page, _report())
    res = chrome.run(research.extract_and_record_agent("Gemini", page, _Browser(), None, tmp_path))
    assert res["status"] == "done", world.logs[-8:]
    local = (tmp_path / "documents" / "gemini.md").read_text(encoding="utf-8")
    assert [d["content"] for p, d in sink if p.endswith("/documents/gemini")] == [local]
    images = re.findall(r"!\[([^\]]*)\]\((/document-images/[^)\s]+\.png)\)", local)
    assert [alt for alt, _r in images] == ["Revenue by quarter", "Chart", "Margin trend"]
    uploads = [base64.b64decode(p["json"]["data_base64"]) for p in world.posts]
    assert [_png_size(u) for u in uploads] == [(800, 400), (600, 300), (320, 180)]
    assert "data:" not in local and "blob:" not in local
    assert "Q1 revenue" not in local and "Q2 revenue" not in local
    assert local.index("![Revenue by quarter]") < local.index("Paragraph 2 of the report")
    assert "$$ \\sqrt{x^2 + y^2} $$" in local
    assert "```\nflowchart TD\n    A[Collateral] --> B[Position]\n```" in local
    said = [m for _lvl, m in world.logs if "pictures in the report" in m]
    assert said == ["[Gemini] pictures in the report: 3 drawn as images"], said


def test_a_drawn_chart_keeps_the_colours_and_the_ground_the_page_gave_it(
        chrome, page, fast, monkeypatch):
    """The page's stylesheet colours the bars; a drawing of the bare svg would
    have painted them black. The picture holds the page's red, on the cream the
    chart's figure sits on (the svg itself is transparent); the canvas, on no
    ground of its own, is on white."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    _load(chrome, page, _report())
    html = chrome.run(page.evaluate(research._doc_html_read_js("immersive-panel")))
    pics = dict((alt, src) for src, alt in re.findall(
        r'<img src="(data:image/png;base64,[^"]+)" alt="([^"]+)"', html))
    assert set(pics) == {"Revenue by quarter", "Chart", "Margin trend"}, html[:300]
    pixel = """async ([src, x, y]) => {
        const img = new Image(); img.src = src; await img.decode();
        const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
        const g = c.getContext('2d'); g.drawImage(img, 0, 0);
        return Array.from(g.getImageData(x, y, 1, 1).data); }"""
    chart = pics["Revenue by quarter"]
    assert chrome.run(page.evaluate(pixel, [chart, 100, 240])) == [200, 30, 30, 255]
    assert chrome.run(page.evaluate(pixel, [chart, 780, 20])) == [250, 245, 230, 255]
    canvas = pics["Chart"]
    assert chrome.run(page.evaluate(pixel, [canvas, 60, 60])) == [20, 120, 220, 255]
    assert chrome.run(page.evaluate(pixel, [canvas, 580, 280])) == [255, 255, 255, 255]


def test_claudes_page_read_keeps_its_pictures_too(chrome, page, fast, monkeypatch):
    """Claude's artifact panel, read as HTML (its page read): the same pictures."""
    logs = []
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    body = _report().replace('id="cv"', 'id="cv"')
    G.offline(chrome, page)
    chrome.run(page.set_content(
        "<!doctype html><html><head><meta charset='utf-8'>" + STYLE + "</head><body>"
        "<aside><div class='prose'>" + body + "</div></aside>" + SCRIPT + "</body></html>"))
    chrome.run(page.wait_for_function("() => document.body.dataset.ready === '1'"))
    md = chrome.run(research._extract_html_to_md(page, ["aside .prose"], "Claude"))
    assert re.findall(r"!\[([^\]]*)\]\(<data:image/png;base64,", md) == [
        "Revenue by quarter", "Chart", "Margin trend"]
    assert "Q1 revenue" not in md
    assert "[Claude] pictures in the report: 3 drawn as images" in logs


def test_a_picture_the_page_cannot_draw_is_left_as_it_was(chrome, page, fast, monkeypatch):
    """⛔ A canvas holding another site's picture cannot be read by the page (the
    browser forbids it): it is left as before — no image — and the log says one
    could not be drawn, while the others are drawn."""
    logs = []
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    other = "http://pictures.sr-fixture.invalid/a.png"
    tainted = ('<canvas id="tc" width="200" height="100" style="width:200px;height:100px">'
               '</canvas><script>const t = new Image(); t.onload = () => {'
               "document.getElementById('tc').getContext('2d').drawImage(t, 0, 0, 200, 100);"
               "document.body.dataset.tainted = '1'; };"
               f"t.src = '{other}';</script>")
    _load(chrome, page, _report(tainted), pictures=[other])
    chrome.run(page.wait_for_function("() => document.body.dataset.tainted === '1'"))
    md = chrome.run(research._extract_html_to_md(page, ["immersive-panel"], "Gemini"))
    assert len(re.findall(r"!\[[^\]]*\]\(<data:image/png;base64,", md)) == 3
    assert ("[Gemini] pictures in the report: 3 drawn as images, 1 could not be drawn and "
            "stay as the page shows them") in logs


def test_icons_controls_and_web_images_are_not_drawn(chrome, page, fast, monkeypatch):
    """⛔ No picture is made of an icon (smaller than the rehost keeps), a glyph in
    a button or a link, or KaTeX's own strokes; a picture with a web address is
    left to the rehost, as it always was — while the chart beside them is drawn."""
    logs = []
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    extra = ('<a href="https://example.org/x"><svg width="80" height="80"><rect width="80" '
             'height="80"></rect></svg></a>'
             '<div role="button"><canvas width="90" height="90"></canvas></div>'
             '<canvas width="40" height="40"></canvas><canvas width="300" height="20"></canvas>'
             '<div style="display:none"><svg width="100" height="100"></svg></div>'
             '<svg width="100" height="100" style="visibility:hidden"></svg>'
             f'<img src="{PHOTO}" alt="Photo" width="300" height="200">')
    # The photo loads (from a local answer), from another site than the page.
    G.offline(chrome, page, [PHOTO])
    chrome.run(page.set_content(G.report_page(f"<h1>R</h1><p>{G.prose(1)}</p>{SVG_CHART}"
                                              f"{ICON}{extra}<p>{G.prose(2)}</p>"
                                              f"<p>{G.katex_samples()[2]['html']}</p>")))
    md = chrome.run(research._extract_html_to_md(page, ["immersive-panel"], "Gemini"))
    assert re.findall(r"!\[([^\]]*)\]\(<(data|https)", md) == [
        ("Revenue by quarter", "data"), ("Photo", "https")]
    assert "$$ \\sqrt{x^2 + y^2} $$" in md
    # Exactly this line: a web image the page tried to redraw would be counted
    # as one it could not draw.
    assert [m for m in logs if "pictures in the report" in m] == [
        "[Gemini] pictures in the report: 1 drawn as images"], logs


# ── The read's own limits (review 10-02: none of them was pinned) ───────────

def _said(logs):
    return [m for m in logs if "pictures in the report" in m]


def _charts(n):
    """`n` svg charts, each with its own axis label."""
    return "".join(SVG_CHART.replace("Q1 revenue", f"Axis label {i}").replace(
        "Revenue by quarter", f"Chart number {i}") for i in range(1, n + 1))


def test_a_read_draws_twenty_pictures_and_counts_every_one_past_them(chrome, page, fast,
                                                                     monkeypatch):
    """⛔ Review 10-02: a report with 21 charts — the first 20 are drawn and the
    21st stays as the page shows it; the log counts it ("20 drawn" alone hid
    it), so a run log shows a report held more pictures than one read draws."""
    logs = []
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    G.offline(chrome, page)
    chrome.run(page.set_content(G.report_page(
        f"<h1>R</h1><p>{G.prose(1)}</p>{_charts(21)}<p>{G.prose(2)}</p>")))
    md = chrome.run(research._extract_html_to_md(page, ["immersive-panel"], "Gemini"))
    assert re.findall(r"!\[([^\]]*)\]\(<data:image/png;base64,", md) == [
        f"Chart number {i}" for i in range(1, 21)]
    assert re.findall(r"Axis label \d+", md) == ["Axis label 21"]
    assert _said(logs) == ["[Gemini] pictures in the report: 20 drawn as images, 1 could "
                           "not be drawn and stay as the page shows them"], logs


def test_a_read_past_its_time_draws_nothing_more_and_counts_it(chrome, page, fast,
                                                                monkeypatch):
    """With the read's time spent (its budget set to none), not one picture is
    drawn: each stays as the page shows it, and the log counts all three."""
    logs = []
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    monkeypatch.setattr(research, "_DOC_FIGURES_BUDGET_MS", 0)
    _load(chrome, page, _report())
    md = chrome.run(research._extract_html_to_md(page, ["immersive-panel"], "Gemini"))
    assert "data:image" not in md and "Q1 revenue" in md
    assert _said(logs) == ["[Gemini] pictures in the report: 0 drawn as images, 3 could "
                           "not be drawn and stay as the page shows them"], logs


def test_a_picture_too_big_to_store_is_not_put_in(chrome, page, fast, monkeypatch):
    """A drawn picture larger than the image store keeps (its size cap set below
    any picture here) is not put in the copy: each stays as the page shows it,
    and the log counts it."""
    logs = []
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    monkeypatch.setattr(research, "_DOC_FIGURES_MAX_CHARS", 100)
    _load(chrome, page, _report())
    md = chrome.run(research._extract_html_to_md(page, ["immersive-panel"], "Gemini"))
    assert "data:image" not in md and "Q1 revenue" in md
    assert _said(logs) == ["[Gemini] pictures in the report: 0 drawn as images, 3 could "
                           "not be drawn and stay as the page shows them"], logs


def test_an_svg_that_never_finishes_drawing_does_not_hold_the_read(chrome, page, fast,
                                                                   monkeypatch):
    """⛔ `page.evaluate` has no time limit of its own: an svg whose drawing never
    loads would hold the whole page read forever. Here `Image` never loads
    anything; the read gives that drawing its wait (set short here), counts it,
    and comes back with the report.
    (Set through `page.evaluate`, not the page's own script: patchright runs the
    read in a world of its own, where the page's globals are not seen.)"""
    logs = []
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    monkeypatch.setattr(research, "_DOC_FIGURES_WAIT_MS", 300)
    G.offline(chrome, page)
    chrome.run(page.set_content(G.report_page(
        f"<h1>R</h1><p>{G.prose(1)}</p>{SVG_CHART}<p>{G.prose(2)}</p>")))
    assert chrome.run(page.evaluate(
        "() => { window.Image = function () { return {}; }; return !(new Image()).decode; }"))
    started = time.monotonic()
    md = chrome.run(asyncio.wait_for(
        research._extract_html_to_md(page, ["immersive-panel"], "Gemini"), 8))
    # Inside the wait it was given, not the 3 s it is when nothing sets it.
    assert time.monotonic() - started < 2.5
    assert "Paragraph 2 of the report" in md and "data:image" not in md
    assert _said(logs) == ["[Gemini] pictures in the report: 0 drawn as images, 1 could "
                           "not be drawn and stay as the page shows them"], logs


def test_a_copy_that_does_not_match_the_page_gets_no_picture(chrome, page, fast):
    """⛔ The pictures go into the copy element by element, matched by position.
    Both reads today clone the copy in the same step, so they always match; a
    read that took something out of its copy first (as the frame read does right
    after) would put each picture in the wrong place. So a copy that does not
    match gets none, and nothing in it changes."""
    _load(chrome, page, _report())
    got = chrome.run(page.evaluate("""async () => {
        const root = document.querySelector('immersive-panel');
        const copy = root.cloneNode(true);
        copy.querySelector('h1').remove();
        const before = copy.innerHTML;
        const got = await (""" + research._doc_figures_js() + """)(root, copy);
        return [got.made, got.failed, copy.innerHTML === before];
    }"""))
    assert got == [0, 0, True]
