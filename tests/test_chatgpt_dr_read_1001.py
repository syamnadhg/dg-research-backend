"""ChatGPT Deep research, 2026-10-01: the finished report is read off the app's
frame — nothing pressed, nothing downloaded — and a dead browser gets no card.

⛔⛔ THE 10-01 RUN (logs/runs/chat_1790816941167_1_20261001T010909/run.log):

  18:33:42  Deep research app, what its frames hold (done): … 43 elements,
            100 controls ["59", "339", "30 Sep • 59 sources", "Saint Bernard: …",
            "Export", "Expand", "1", "Copy table", …], 0 links, 37 headings,
            text 88718 chars
  18:33:45  Deep research download by the page: pressed ["Export",
            "Export to Markdown"] … Target page, context or browser has been closed
            (Chrome 154 crashed that instant: SIGSEGV on CrBrowserMain)
  18:33:45  All extraction methods failed → "Extraction attempt 1 returned no
            content — surfacing user decision" → a "ChatGPT failed" card
  18:34:45  the whole browser is gone … unwinding for checkpoint recovery

1. The report was already in the frame — 88,718 characters, 37 headings — in a
   card 400 px tall that only CLIPS it. It is now read from there and turned
   into markdown by the converter every HTML read uses; computer use downloads
   it (as on 09-30) only when the frame does not hold the whole report.
2. An empty extraction asks the browser before it becomes a card: a dead one
   takes the crash path at once, with no card, and ChatGPT is not first shown
   "failed" or saved "errored" for a crash the run retries silently.

── The pages ───────────────────────────────────────────────────────────────
The host page is the owner's recording 3c (tests/fixtures/chatgpt_0930/
3c-chatgpt-app-tab.json, 6.3 s: the finished page, the app in the thread's card,
no Stop). The app's frames are written out by hand from the run's own censuses
(the recorder's node shape, read 10-01; the files stay in the run's log folder):
  * done, frame 0: body > iframe#root, 768×484, title "sandbox";
  * done, frame 1: body > div#root > main > div.h-full > div.w-full.p-px >
    [counts line (role=img "59", "339"), card: header (div[title="30 Sep • 59
    sources"], title div, Export [aria-haspopup=menu], Expand), then
    div[role=button].h-[400px].overflow-hidden > … > div.flex.w-full.min-w-0.
    justify-center (32,989 px tall, 92,251 characters)], a module script of
    13,285,830 characters, div.mermaidTooltip. Citations:
    sup[role=button][data-citation-index][data-citation-interactive], text
    "N"; tables in div[tabindex=0] with an icon-only "Copy table" button; one
    svg[role="graphics-document document"].flowchart; NOT ONE LINK.
  * launch, frame 3 (the activity list): aside > … > section >
    [p#report-activity-title "Research activity", div.space-y-4 > 29 rows,
    each an icon column and a text column with source pills
    a[aria-label="Open source <host>"][target=_blank] and "N more" buttons],
    3,242 characters, 86 links, no heading.
⚠ ASSUMED (no census reaches it): what sits below the census's depth cut —
the report's own markup (a flat container of h1–h3, p, ul, the table wrappers
and the diagram), the counts line's words, the Export menu, the full title (the
census cut it at 60 of its 79 characters), the link shapes in test 3, the
script's size (300,000 characters here, against the measured 13 million), and
the shapes no census has shown: an opening paragraph with no heading, a citation
token run, a hidden tooltip and a code block's "Copy code" button.

Nothing leaves the machine: every request is answered by a local route from
reserved `.invalid` hosts; the run's census goes to a temporary folder.
"""
import asyncio
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import research
import _capture_page as cp
import test_chatgpt_dr_app_0930 as app
import test_chatgpt_new_page_0928 as base

chrome = base.chrome
page = base.page
fast = base.fast
logs = base.logs

APP = app.APP_URL
REPORT_URL = APP + "report"
HOST = app.HOST_URL + "-1001"
C3 = cp.load("3c-chatgpt-app-tab.json")

#: The finished report's title: the census's 60 characters ("Saint Bernard:
#: Breed, Health, Behaviour, Care, Costs, and Re") of its 79 (txtLen), ⚠ the
#: last 19 ASSUMED.
TITLE = "Saint Bernard: Breed, Health, Behaviour, Care, Costs, and Responsible Ownership"


@pytest.fixture(autouse=True)
def run_dir(tmp_path, monkeypatch):
    """Every census goes to a temporary folder, never the machine's logs."""
    monkeypatch.setattr(research, "_active_run_sink", lambda: SimpleNamespace(dir=tmp_path))
    monkeypatch.setattr(research, "_CHATGPT_DR_CENSUS_SEEN", {}, raising=False)
    monkeypatch.delenv("SR_CHATGPT_DR_PAGE_DOWNLOAD", raising=False)
    return tmp_path


# ═══ The pages ════════════════════════════════════════════════════════════════

def _host_html():
    """Recording 3c at 6.3 s: the finished page, the app in the thread's card
    (640×484), no Stop."""
    fr = C3["frames"][1]
    assert fr["ms"] == 6301 and not fr["stopButtons"]
    turn = "".join(cp.node_html(n) for n in fr["lastTurn"]).replace(app.REC_APP, APP)
    assert turn.count(f'src="{APP}"') == 1, "the app's frame is not in the recorded card"
    return cp.page_html("<main>" + turn + "</main><form></form>")


#: done, frame 0: the sandbox's own page, the report's frame inside it.
WRAPPER = ('<!doctype html><html><head><meta charset="utf-8"><title>sandbox</title></head>'
           f'<body style="margin:0"><iframe id="root" src="{REPORT_URL}" '
           'style="width:768px;height:484px;border:0"></iframe></body></html>')

#: Records every press in the frame (pointer, mouse, click, key), and plays the
#: Export menu (⚠ ASSUMED: the census shows Export with aria-haspopup=menu; the
#: 09-30 computer use then pressed "Export to Markdown", which downloads).
_FRAME_SCRIPT = """<script>
(() => {
  const rec = (e) => {
    const t = e.target && e.target.closest ? e.target.closest('[aria-label],[role],button,a') : null;
    const p = JSON.parse(document.body.dataset.srPressed || '[]');
    p.push(e.type + ':' + (t ? (t.getAttribute('aria-label') || t.getAttribute('role') || t.tagName) : '?'));
    document.body.dataset.srPressed = JSON.stringify(p);
  };
  for (const k of ['pointerdown', 'mousedown', 'click', 'keydown']) document.addEventListener(k, rec, true);
  document.getElementById('export').addEventListener('click', () => {
    document.getElementById('menu').hidden = false; });
  document.querySelector('#menu [role=menuitem]').addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['# Exported'], {type: 'text/markdown'}));
    a.download = 'deep-research-report.md'; document.body.appendChild(a); a.click(); });
})();
</script>"""

#: Tailwind's meaning for the card's two classes that clip it (the census: a
#: card 400 px tall holding a report 32,989 px tall).
_CARD_CSS = ".h-\\[400px\\]{height:400px}.overflow-hidden{overflow:hidden}"


def _report_frame(report, *, script_chars=300_000):
    """done, frame 1, as the census shows it, with `report` where the census's
    depth cut left the report's own element."""
    body = (
        '<div id="root"><main class="text-token-text-primary flex min-h-0 w-full flex-col sm:px-0">'
        '<div class="h-full w-full"><div class="w-full p-px">'
        '<div class="text-token-text-secondary mb-3 text-sm">'
        '<span role="img" aria-label="59"><span aria-hidden="true">59</span></span> sources · '
        '<span role="img" aria-label="339"><span aria-hidden="true">339</span></span> searches</div>'
        '<div class="group w-full rounded-2xl relative z-0">'
        '<div title="30 Sep • 59 sources" class="text-token-text-primary border-token-border-light flex">'
        '<div class="flex flex-row items-center gap-2 overflow-hidden ps-1">'
        '<div class="rounded-md p-1"><svg aria-hidden="true" class="m-0 text-white"></svg></div>'
        f'<div title="{TITLE}" class="truncate text-sm font-medium">{TITLE}</div></div>'
        '<div class="text-token-text-secondary flex flex-row items-center gap-1">'
        '<div class="relative z-30"><button id="export" aria-label="Export" aria-expanded="false" '
        'aria-haspopup="menu" type="button"><svg aria-label="" class="-mx-1 icon-sm"></svg></button></div>'
        '<button aria-label="Expand" type="button"><div class="flex w-full items-center"></div></button>'
        '</div></div>'
        '<div class="bg-token-bg-tertiary group relative">'
        '<div role="button" tabindex="0" class="relative flex h-[400px] overflow-hidden pb-0 cursor-pointer">'
        '<div class="from-token-bg-primary pointer-events-none"></div>'
        '<div class="relative flex w-full flex-1 items-start justify-center">'
        '<div class="flex w-full min-w-0 justify-center">' + report + '</div>'
        '</div></div></div></div></div></div></main></div>'
        '<script type="module">/* ' + "x" * script_chars + ' */</script>'
        '<div class="mermaidTooltip"></div>'
        '<div role="menu" id="menu" hidden><div role="menuitem" tabindex="-1">Export to Markdown</div></div>'
        + _FRAME_SCRIPT)
    return cp.page_html(body, extra_css=_CARD_CSS, title="")


def _cite(n):
    """A citation as the 10-01 census shows it: a button with its number only."""
    return ('<sup role="button" aria-pressed="false" tabindex="0" data-citation-index="%d" '
            'data-citation-interactive="true" class="focus-visible:outline-token-text-primary '
            'group inline-flex cursor-pointer align-super">%d</sup>' % (n, n))


def _table(rows):
    """A table as the census shows it: in a focusable wrapper with an icon-only
    "Copy table" button."""
    return ('<div tabindex="0" class="bg-token-main-surface-primary group relative overflow-hidden '
            'focus:outline-none"><button aria-label="Copy table" title="Copy table" type="button">'
            '<svg aria-label="" class="-mx-1 icon-sm"></svg></button><table><thead><tr>'
            '<th>Dimension</th><th>Profile</th></tr></thead><tbody>'
            + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows)
            + "</tbody></table></div>")


#: The census's one diagram (mermaid), its labels ⚠ ASSUMED.
DIAGRAM = ('<svg role="graphics-document document" id="mermaid-_r_6e_" class="flowchart">'
           '<g><text>Puppy screening</text><text>Adult health checks</text></g></svg>')


def _report(cite=_cite, *, whole=True):
    """The report as the frame holds it (⚠ ASSUMED below the census's cut: a flat
    container). `whole=False` is its first sections only."""
    f = cp.filler
    head = (f"<h1>{TITLE}</h1><h2>Executive summary</h2>"
            "<p>The Saint Bernard is a giant working breed from the Western Alps, kept at the "
            f"Great St Bernard Hospice for rescue and draught work.{cite(1)} Adult dogs commonly "
            f"weigh 64 to 120 kg, and males are larger than females.{cite(2)}{cite(3)} "
            f"{f(900, 1)}</p>"
            "<ul><li>Lifespan is short for a dog: most live eight to ten years."
            f"{cite(4)}</li><li>Hip and elbow dysplasia are the best documented orthopaedic "
            f"problems.{cite(5)}</li><li>Bloat is an emergency in every deep-chested breed.</li></ul>"
            "<h2>Physical profile</h2>"
            + _table([("Origin", "Great St Bernard Pass, Western Alps" + cite(6)),
                      ("Adult weight", "64–120 kg")])
            + f"<p>{f(1200, 2)}</p>")
    if not whole:
        return '<div class="markdown prose">' + head + "</div>"
    return ('<div class="markdown prose">' + head
            + f"<h3>Coat and colour</h3><p>{f(1200, 3)}</p>"
            + f"<h2>Health and longevity</h2><p>{f(1500, 4)}</p>" + DIAGRAM
            + f"<p>{f(1500, 5)}</p><h2>Care and costs</h2><p>{f(1500, 6)}</p>"
            + "<h2>Bibliography</h2><p>Fédération Cynologique Internationale. Saint Bernard "
            f"breed standard.{cite(7)}</p></div>")


def _activity_frame(rows=29):
    """launch, frame 3 — the activity list and its source pills: no heading,
    about 3,200 characters, 86 links (⚠ the hosts and each row's words ours)."""
    hosts = [f"www.source-{i:02d}.example.org" for i in range(90)]
    out = []
    for r in range(rows):
        pills = "".join(
            f'<a aria-label="Open source {h}" href="https://{h}/saint-bernard/{r}" target="_blank" '
            f'class="inline-flex items-center gap-2 rounded-full">{h}</a>'
            for h in hosts[3 * r:3 * r + 3])
        out.append('<div class="text-token-text-secondary flex items-start gap-2">'
                   '<div class="flex w-6 shrink-0 flex-col items-center"></div>'
                   f'<div class="flex-1"><p>{cp.filler(60, r)}</p><div class="flex gap-2">{pills}'
                   f'<button type="button">{r % 8 + 1} more</button></div></div></div>')
    body = ('<div id="root"><aside class="border-token-border-light bg-primary">'
            '<div class="flex min-h-0 flex-1 flex-col gap-3"><div class="bg-primary relative flex min-h-0 flex-1">'
            '<div class="overflow-y-scroll p-2 pt-3 pb-10 h-full"><section>'
            '<p id="report-activity-title">Research activity</p>'
            '<div class="space-y-4 py-1">' + "".join(out) + "</div></section></div></div>"
            '</div></aside></div><script type="module">/* app */</script>')
    return cp.page_html(body, title="")


def _serve(chrome, page, frame_html, *, host_html=None):
    """The host page (3c), the sandbox's page and the report's frame, all local;
    everything else aborted. Waits for the report's frame to load."""
    host_html = host_html or _host_html()

    async def _route(route):
        u = route.request.url
        if u == HOST:
            await route.fulfill(status=200, content_type="text/html", body=host_html)
        elif u == REPORT_URL:
            await route.fulfill(status=200, content_type="text/html", body=frame_html)
        elif u == APP:
            await route.fulfill(status=200, content_type="text/html", body=WRAPPER)
        else:
            await route.abort()

    async def _go():
        await page.unroute("**/*")
        await page.route("**/*", _route)
        await page.goto(HOST)
        for _ in range(100):
            fr = _report_frame_of(page)
            if fr is not None:
                try:
                    if await fr.evaluate("() => document.readyState") == "complete":
                        return
                except Exception:
                    pass
            await asyncio.sleep(0.05)
        raise AssertionError("the report's frame never loaded")

    chrome.run(_go())


def _report_frame_of(page):
    """The report's frame, by its address alone (no code under test)."""
    return next((f for f in page.frames if (f.url or "") == REPORT_URL), None)


def _pressed(chrome, page):
    fr = _report_frame_of(page)
    return json.loads(chrome.run(fr.evaluate("() => document.body.dataset.srPressed || '[]'")))


def _downloads(page):
    got = []
    page.on("download", lambda d: got.append(d))
    return got


def _extract(chrome, page, monkeypatch, cua, **kw):
    monkeypatch.setattr(research, "_extract_via_cua_download", cua.download)
    return chrome.run(research.extract_chatgpt_response(
        page, browser=SimpleNamespace(page=page), cua_client=object(), **kw))


def _said(logs, text):
    return [m for _lv, m in logs if text in m]


# ═══ 1. The report, read off the frame ════════════════════════════════════════

@pytest.mark.parametrize("press_on", [False, True])
def test_the_report_is_read_off_the_frame_nothing_pressed(chrome, page, fast, logs, monkeypatch,
                                                          press_on):
    """⭐⭐ THE 10-01 FRAME. The finished report is read straight off the app's
    frame: its headings, list and table kept, its numbered citations (buttons
    with no link in them) left out rather than glued to the words, the frame's
    header, buttons and diagram left out. Nothing is pressed in the frame,
    nothing downloads, computer use is never asked — and with the page's own
    Export press turned back on, the read still comes first."""
    if press_on:
        monkeypatch.setenv("SR_CHATGPT_DR_PAGE_DOWNLOAD", "1")
    _serve(chrome, page, _report_frame(_report()))
    downloads = _downloads(page)
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 0, "computer use was asked for a report the frame holds"
    assert _pressed(chrome, page) == [], "something was pressed inside the app's frame"
    assert downloads == [], "a file was downloaded"
    assert md.startswith("# " + TITLE + "\n"), md[:200]
    assert "\n## Executive summary\n" in md and "\n### Coat and colour\n" in md
    assert "\n## Bibliography\n" in md
    assert ("Great St Bernard Hospice for rescue and draught work. Adult dogs commonly weigh"
            in md), "a citation's number is still in the sentence"
    assert "males are larger than females. " in md and "females.2" not in md
    assert "\n- Lifespan is short for a dog: most live eight to ten years.\n" in md
    assert "| Dimension | Profile |" in md
    assert "| Origin | Great St Bernard Pass, Western Alps |" in md
    assert "Saint Bernard breed standard." in md and "standard.7" not in md
    for chrome_word in ("Copy table", "Export", "Expand", "30 Sep", "339", "Worked for",
                        "Puppy screening", "xxxxxxxx"):
        assert chrome_word not in md, chrome_word
    assert _said(logs, "Extracted via the Deep research app's frame (no download)")
    said = _said(logs, "Report read from the Deep research app's frame")
    assert len(said) == 1 and "7 citations had no link in the frame" in said[0], said
    assert "1 diagram left out" in said[0], said
    assert not _said(logs, "Deep research download by the page")


def _done_len(chrome, page):
    """What the REAL done check reads on the page as it stands, and the frame's
    body length beside it (the two are the same measure)."""
    done, _why, snap = chrome.run(research.detect_completion_chatgpt(page))
    body = chrome.run(_report_frame_of(page).evaluate("() => document.body.innerText.length"))
    assert done, _why
    return int(snap["text_len"]), body


def test_a_whole_report_passes_the_done_checks_length(chrome, page, fast, logs, monkeypatch):
    """The done check read the frame's body; a frame that still holds it all is
    read, header and counts line included in that length."""
    _serve(chrome, page, _report_frame(_report()))
    t1, body = _done_len(chrome, page)
    assert t1 == body, (t1, body)
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua, done_text_len=t1)
    assert cua.calls == 0 and md.startswith("# " + TITLE), _said(logs, "Report")


def test_a_title_above_the_rest_of_the_report_stays_in(chrome, page, fast, logs, monkeypatch):
    """⚠ ASSUMED shape: the title, then one element holding nearly all the rest.
    The read never goes past a heading beside the element it would go into."""
    f = cp.filler
    rep = (f"<article><h1>{TITLE}</h1><section><h2>Executive summary</h2><p>{f(2500, 1)}</p>"
           f"<h2>Health</h2><p>{f(2500, 2)}</p></section></article>")
    _serve(chrome, page, _report_frame(rep))
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 0 and md.startswith("# " + TITLE + "\n"), md[:120]


def test_a_part_of_the_report_with_no_heading_of_its_own_stays_in(chrome, page, fast, logs,
                                                                   monkeypatch):
    """⚠ ASSUMED shape: an opening summary with no heading, then one element
    holding every heading. The read goes down only into a child holding nearly
    all the text, so the summary is not dropped for having no heading."""
    f = cp.filler
    rep = (f"<div><p>Opening summary. {f(1500, 1)}</p><div><h1>{TITLE}</h1>"
           f"<h2>Health</h2><p>{f(2500, 2)}</p><h2>Care</h2><p>{f(2500, 3)}</p></div></div>")
    _serve(chrome, page, _report_frame(rep))
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 0 and md.startswith("Opening summary."), md[:120]
    assert "\n# " + TITLE + "\n" in md


def test_a_short_opening_paragraph_with_no_heading_stays_in(chrome, page, fast, logs,
                                                             monkeypatch):
    """⚠ ASSUMED shape: an opening paragraph with no heading, well under a tenth
    of the text, then one element holding every heading. The read does not go
    past more than a line of text beside the element it would go into."""
    f = cp.filler
    rep = (f"<div><p>INTRO-MARK Opening summary. {f(550, 1)}</p><div id='rest'><h1>{TITLE}</h1>"
           f"<h2>Health</h2><p>{f(3500, 2)}</p><h2>Care</h2><p>{f(3500, 3)}</p></div></div>")
    _serve(chrome, page, _report_frame(rep))
    # Only the new rule keeps it: the element holding the headings has more
    # than the share the read goes down into.
    rest, body = chrome.run(_report_frame_of(page).evaluate(
        "() => [document.getElementById('rest').innerText.length, document.body.innerText.length]"))
    assert rest >= research._CHATGPT_DR_REPORT_SHARE * body, (rest, body)
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 0 and md.startswith("INTRO-MARK Opening summary."), md[:120]
    assert "\n# " + TITLE + "\n" in md
    for chrome_word in ("Export", "Expand", "30 Sep", "339"):
        assert chrome_word not in md, chrome_word


def test_a_citation_token_run_in_the_frame_is_stripped(chrome, page, fast, logs, monkeypatch):
    """⚠ ASSUMED (the 10-01 frame showed none): a citation token run the app did
    not turn into a button. Every other tier strips these; so does the read."""
    tok = chr(0xE200) + "cite" + chr(0xE202) + "turn0search3" + chr(0xE201)
    rep = _report().replace(
        "<h2>Care and costs</h2>",
        f"<p>Bloat needs a vet at once.{tok} Know the signs.</p><h2>Care and costs</h2>")
    assert rep.count(tok) == 1
    _serve(chrome, page, _report_frame(rep))
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 0
    assert "Bloat needs a vet at once. Know the signs." in md, md[-1500:]
    assert chr(0xE200) not in md and "turn0search3" not in md


def test_what_the_page_does_not_draw_and_a_controls_label_stay_out(chrome, page, fast, logs,
                                                                     monkeypatch):
    """⚠ ASSUMED shapes (the 10-01 frame's buttons are icon-only): a tooltip the
    page does not draw, and a code block's "Copy code" button. Neither is report
    text; the code is."""
    extra = ('<div style="display:none"><p>HIDDEN-MARK tooltip text</p></div>'
             '<div class="code"><div class="flex"><span>python</span>'
             '<button type="button">Copy code</button></div>'
             '<pre><code>weight_kg = 64</code></pre></div>')
    rep = _report().replace("<h2>Care and costs</h2>", extra + "<h2>Care and costs</h2>")
    _serve(chrome, page, _report_frame(rep))
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 0 and "weight_kg = 64" in md, md[-2500:]
    assert "HIDDEN-MARK" not in md
    assert "Copy code" not in md
    said = _said(logs, "Report read from the Deep research app's frame")
    assert said and "7 citations had no link in the frame" in said[0], said


#: Two citation shapes that carry their source (⚠ ASSUMED — the 10-01 frame had
#: none): Phase 1's pill (4-chatgpt-p1-thinking.json), and a numbered citation
#: holding a link.
AKC = "https://www.akc.org/dog-breeds/saint-bernard/"
RKC = "https://www.thekennelclub.org.uk/breed-standards/working/saint-bernard/"


def _linked_cite(n):
    if n == 1:
        return ('<span class="contents" data-state="closed"><span class="ms-1 inline-flex" '
                'data-search-result-target=""><a data-testid="chatgpt-citation" '
                f'aria-label="American Kennel Club: Saint Bernard, {AKC}" href="{AKC}">'
                'American Kennel Club +1</a></span></span>')
    if n == 2:
        return ('<sup role="button" tabindex="0" data-citation-index="2" '
                f'data-citation-interactive="true"><a href="{RKC}" target="_blank">'
                'The Royal Kennel Club</a></sup>')
    return _cite(n)


def test_a_citation_that_carries_its_source_keeps_it_and_the_document_numbers_it(
        chrome, page, fast, logs, monkeypatch):
    """⭐ The owner wants the sources in the document. A citation that names its
    source in the frame keeps it as a markdown link — without the pill's "+1" —
    and the document then ends with its numbered sources, as every agent's does."""
    _serve(chrome, page, _report_frame(_report(_linked_cite)))
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 0
    assert f"[American Kennel Club]({AKC})" in md and "+1" not in md, md[:900]
    assert f"[The Royal Kennel Club]({RKC})" in md
    said = _said(logs, "Report read from the Deep research app's frame")
    assert said and "2 links" in said[0] and "5 citations had no link" in said[0], said
    doc = research._document_with_sources("# ChatGPT Deep Research\n\n" + md)
    assert "\n##### Sources" in doc
    tail = doc[doc.rindex("Sources"):]
    assert AKC in tail and RKC in tail
    assert research._doc_source_marker(1, AKC) in doc[:doc.rindex("Sources")]


# ═══ 2. Not the whole report: computer use downloads it, as on 09-30 ══════════

def test_a_frame_holding_only_a_card_goes_to_computer_use(chrome, page, fast, logs, monkeypatch):
    """⚠ ASSUMED card: the title as a heading and a few lines. Too little to be
    the report — computer use downloads it, and nothing is pressed in the frame."""
    rep = f'<div class="markdown"><h1>{TITLE}</h1><p>{cp.filler(500, 1)}</p></div>'
    _serve(chrome, page, _report_frame(rep))
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 1 and md.startswith("# Golden Retriever")
    assert _pressed(chrome, page) == []
    said = _said(logs, "Report not read from the Deep research app's frame")
    assert said and "characters of report" in said[0], said


def test_the_activity_list_is_never_taken_for_the_report(chrome, page, fast, logs, monkeypatch):
    """⛔ The 10-01 launch census's activity frame — source pills and short lines,
    no heading — is a sources list, not the report, even though it is long
    enough and reads as no sources list to the old check. Not taken."""
    act = _activity_frame()
    _serve(chrome, page, act)
    html = chrome.run(_report_frame_of(page).evaluate("() => document.body.innerHTML"))
    md0 = research.html_to_markdown(html)
    # Nothing but the heading check can refuse it: long enough, and the old
    # sources check lets it through.
    assert research._doc_img_prose_len(md0) > 2000
    assert not research._is_sources_not_document(md0, platform="chatgpt")
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 1 and md.startswith("# Golden Retriever")
    said = _said(logs, "Report not read from the Deep research app's frame")
    assert said and "no heading" in said[0], said


def test_a_numbered_list_of_addresses_is_never_taken_for_the_report(chrome, page, fast, logs,
                                                                      monkeypatch):
    """⚠ ASSUMED shape — the one `_is_sources_not_document` was written for: a
    heading and a numbered list of addresses. Long enough and headed, so only
    that check refuses it."""
    rep = ("<div><h2>Sources</h2><ol>" + "".join(
        f"<li>https://www.example-source-{i:02d}.org/research/saint-bernard/page</li>"
        for i in range(34)) + "</ol></div>")
    _serve(chrome, page, _report_frame(rep))
    cua = app._NoCua(app._export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 1 and md.startswith("# Golden Retriever")
    said = _said(logs, "Report not read from the Deep research app's frame")
    assert said and "sources list" in said[0], said


# ═══ The poll loop: the extraction and what is done with its answer ═══════════
# `poll_all_agents_round_robin` cannot be run whole. The statements of each of
# its two extraction blocks — from the `_queue_dir` line before the call to the
# end of the block — are lifted out of research.py's parse tree at test time (a
# mutation is measured) and run with the REAL `extract_and_record_agent` and
# `extract_chatgpt_response` on the headless page.

SRC = Path(research.__file__).resolve()
_TREES: dict = {}


def _extraction_block(marker):
    text = SRC.read_text(encoding="utf-8")
    if text not in _TREES:
        _TREES.clear()
        _TREES[text] = ast.parse(text)
    tree = _TREES[text]
    rr = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
          and n.name == "poll_all_agents_round_robin"]
    assert len(rr) == 1
    found = []
    for node in ast.walk(rr[0]):
        for field in ("body", "orelse"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for i, s in enumerate(stmts):
                if (isinstance(s, ast.Assign) and len(s.targets) == 1
                        and ast.unparse(s.targets[0]) == "res"
                        and "extract_and_record_agent(" in ast.unparse(s.value)
                        and any(marker in ast.unparse(x) for x in stmts[i:])):
                    found.append((stmts, i))
    assert len(found) == 1, f"expected ONE extraction block holding {marker!r}, found {len(found)}"
    stmts, i = found[0]
    assert ast.unparse(stmts[i - 1]).startswith("_queue_dir ="), "the block moved — re-anchor"
    return stmts[i - 1:]


#: The Phase 2 poll's two extraction blocks: after the page said done, and
#: after computer use said done.
PAGE_DONE, CUA_DONE = "_empty_extract_cap", "ag_key_empty"


def _run_block(chrome, monkeypatch, marker, page_, browser, *, cua_client, t1=0, cards=None,
               emits=None, saved=None):
    """Run one extraction block; `cards` collects every card it puts up,
    `emits` every event as (kind, agent, status) and `saved` every agent status
    written to the run's record as (agent, status)."""
    shell = ast.parse("async def _go():\n    for name in [NAME]:\n        pass\n")
    shell.body[0].body[0].body = _extraction_block(marker)
    ast.fix_missing_locations(shell)
    runtime = SimpleNamespace(agent_progress_snapshots={}, agent_findings={},
                              last_failure_kind=None)
    monkeypatch.setattr(research, "_runtime", runtime, raising=False)
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)

    async def _same(text, **k):
        return text

    async def _no_look(*a, **k):
        return None

    monkeypatch.setattr(research, "_rehost_document_images", _same)
    emits = [] if emits is None else emits
    saved = [] if saved is None else saved
    monkeypatch.setattr(research, "emit_event", lambda kind, phase=None, agent=None, **d:
                        emits.append((kind, agent, d.get("status"))))
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda key, status, *a, **k:
                        saved.append((key, status)))
    monkeypatch.setattr(research, "_shadow_observed_cua", _no_look)
    cards = [] if cards is None else cards
    p = {"page": page_, "extraction_attempts": 1, "flat_history": [],
         "done_marker_first_at": 0.0, "start_time": 0.0}
    scope = {**vars(research), "NAME": "ChatGPT", "p": p, "browser": browser,
             "cua_client": cua_client, "verbose": False, "elapsed": 1000,
             "_partial_text_len": 0, "t1": t1, "results": {}, "pending": {"ChatGPT": p},
             "agent_key": "chatgpt", "_tracks_dir": None, "_runtime": runtime,
             "fail_agent": lambda *a, **k: cards.append(a)}
    exec(compile(shell, str(SRC), "exec"), scope)
    chrome.run(scope["_go"]())
    return cards, runtime


async def _to_front(_page):
    return None


def test_a_frame_that_lost_text_after_the_done_check_goes_to_computer_use(
        chrome, page, fast, logs, monkeypatch):
    """⭐ The poll loop hands the extraction what the done check read in the
    frame. Here the REAL done check reads the whole report, then the frame is
    left holding its first sections only: long enough and headed, but the frame
    lost text after the done check, so computer use downloads the report.
    ⚠ This is all that length can catch: the done check reads this same frame,
    so a frame that never held the whole report passes it."""
    _serve(chrome, page, _report_frame(_report()))
    t1, body = _done_len(chrome, page)
    assert t1 == body, (t1, body)
    fr = _report_frame_of(page)
    chrome.run(fr.evaluate(
        "(h) => { document.querySelector('div.flex.w-full.min-w-0.justify-center').innerHTML = h; }",
        _report(whole=False)))
    cut = chrome.run(fr.evaluate("() => document.body.innerText.length"))
    assert 2500 < cut < 0.5 * t1, (cut, t1)
    cua = app._NoCua(app._export())
    monkeypatch.setattr(research, "_extract_via_cua_download", cua.download)
    browser = SimpleNamespace(page=page, context=chrome.ctx, switch_to_page=_to_front)
    _run_block(chrome, monkeypatch, PAGE_DONE, page, browser, cua_client=object(), t1=t1)
    assert cua.calls == 1, "a frame that lost text after the done check was taken for the report"
    said = _said(logs, "Report not read from the Deep research app's frame")
    assert said and f"of the {t1} characters the done check read" in said[0], said
    assert "the frame changed after the done check" in said[0], said
    assert _said(logs, "Extracted via T1 CUA download")


def _dying_browser(chrome):
    """A browser of its own, which dies the moment computer use downloads — as
    Chrome did on 10-01 the instant the Export press started the file."""
    ctx = chrome.run(chrome.ctx.browser.new_context())
    pg = chrome.run(ctx.new_page())

    class _CrashingCua:
        calls = 0

        async def download(self, *a, **k):
            _CrashingCua.calls += 1
            await ctx.close()
            return ""

    return ctx, pg, _CrashingCua()


@pytest.mark.parametrize("marker", [PAGE_DONE, CUA_DONE])
def test_a_dead_browser_takes_the_crash_path_with_no_card(chrome, fast, logs, monkeypatch, marker):
    """⛔⛔ 10-01: Chrome died during ChatGPT's extraction, every tier then failed
    on the closed browser, and the poll put up "Couldn't read ChatGPT's report"
    — a card about a browser that was gone. Now the browser is asked first: it
    is gone, so the run unwinds for checkpoint recovery at once, no card. And
    ChatGPT is not shown red first: no "failed" status is sent and no "errored"
    is saved for a crash the run retries silently."""
    ctx, pg, cua = _dying_browser(chrome)
    _serve(chrome, pg, _report_frame(
        f'<div class="markdown"><h1>{TITLE}</h1><p>{cp.filler(500, 1)}</p></div>'))
    monkeypatch.setattr(research, "_extract_via_cua_download", cua.download)
    browser = SimpleNamespace(page=pg, context=ctx, switch_to_page=_to_front)
    cards, emits, saved = [], [], []
    with pytest.raises(RuntimeError) as exc:
        _run_block(chrome, monkeypatch, marker, pg, browser, cua_client=object(), cards=cards,
                   emits=emits, saved=saved)
    assert cua.calls == 1 and pg.is_closed(), "the browser did not die where 10-01's did"
    assert cards == [], "a card was put up for a dead browser"
    # The recorder is on the path (the extraction's first status went through it).
    assert ("agent_progress", "chatgpt", "extracting") in emits, emits
    assert ("agent_progress", "chatgpt", "failed") not in emits, "ChatGPT shown failed for a crash"
    assert ("chatgpt", "errored") not in saved, "'errored' saved for a crash"
    assert _said(logs, "no content, and the whole browser is gone")
    assert research._is_browser_close_error(exc.value), str(exc.value)
    assert research._runtime.last_failure_kind == "browser_crash"
    assert not _said(logs, "surfacing user decision")
    assert _said(logs, "the whole browser is gone")


def test_a_live_browser_still_gets_the_card(chrome, page, fast, logs, monkeypatch):
    """The other side: a live browser whose report could not be read still gets
    its card, its "failed" status and its saved "errored", exactly as before."""
    chrome.run(page.set_content("<main><p>nothing here</p></main>"))
    browser = SimpleNamespace(page=page, context=chrome.ctx, switch_to_page=_to_front)
    emits, saved = [], []
    cards, runtime = _run_block(chrome, monkeypatch, PAGE_DONE, page, browser, cua_client=None,
                                emits=emits, saved=saved)
    assert len(cards) == 1 and cards[0][1] == "Couldn't read ChatGPT's report", cards
    assert runtime.last_failure_kind is None
    assert ("agent_progress", "chatgpt", "failed") in emits, emits
    assert ("chatgpt", "errored") in saved, saved
    assert not _said(logs, "the whole browser is gone")
