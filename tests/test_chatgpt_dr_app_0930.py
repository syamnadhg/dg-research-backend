"""ChatGPT, round 2 of the 09-30 run's fixes (2 of 2) — Deep research as an APP.

Since 09-28 Deep research runs inside a cross-origin frame
(mcp-app-<hash>.web-sandbox.oaiusercontent.com), in the thread's card and then
the side viewer. The owner's recordings (tests/fixtures/chatgpt_0930/
3-chatgpt-dr-toppage.json, 3b, 3c) give the chatgpt.com page around it, built
here through `_capture_page`; the frame's inside is in no recording, so the app
is a local stand-in, ⚠ ASSUMED wherever it matters (said at each one).

  3. Done is the Stop button gone — "Worked for …" shows from launch; a census
     of the app's frames is written at launch, mid-run, done and on a miss; the
     report is downloaded inside the frame when it shows a download control,
     and by computer use when not.
  4. The document's sources: the export writes each citation as a token run
     naming ChatGPT's own source list, never a URL, and we deleted the runs —
     the owner's 09-30 document had no sources and no footnotes. Each run is now
     linked to the source the rendered report shows after the same words, and
     the document ends with its numbered sources.

Nothing leaves the machine: the page and the app's frame are served from
reserved `.invalid` hosts through a route that answers every request locally.
"""
import asyncio
import html as _html
import json
from types import SimpleNamespace

import pytest

import research
import _capture_page as cp
import test_chatgpt_new_page_0928 as base

chrome = base.chrome
page = base.page
fast = base.fast
logs = base.logs

DR = cp.load("3-chatgpt-dr-toppage.json")

# ═══ 3. Deep research as an app: done, the census, the download ═══════════════

#: Where the app's frame is served in these tests. It carries the real frame's
#: host name as a SUBSTRING (every reader matches on that), under the reserved
#: `.invalid` top-level name, so no request could ever reach a real host even if
#: the local route below were bypassed.
APP_URL = "http://mcp-app-srfixture.web-sandbox.oaiusercontent.com.sr-fixture.invalid/"
HOST_URL = "http://sr-fixture.invalid/c/dr-0930"
#: The recorded frame origin (3-chatgpt-dr-toppage.json), replaced by APP_URL.
REC_APP = "https://mcp-app-2b73da44fd70aaa0030b651d40adb9ce7ed6a62138bcbf96.web-sandbox.oaiusercontent.com"


def _dr_host_html(index, *, stop=None, strip_app=False, worked=None):
    """The recorded chatgpt.com page of frame `index` of the Deep research
    recording: the latest exchange, the side viewer when it was open, and the
    composer's Stop button as recorded (0×0 while the research runs: hidden).
    The app's frame is put where the recording says it was: in the thread's
    card, or — when its box is the viewer's — in the viewer's frame container
    (⚠ ASSUMED placement; the recorder gives the frame's origin and box only)."""
    fr = DR["frames"][index]
    turn = "".join(cp.node_html(n) for n in fr["lastTurn"])
    side = cp.node_html(fr["panels"][-1]) if fr.get("panels") else ""
    iframe = f'<iframe class="h-full min-h-0 min-w-0 w-full" src="{APP_URL}" title="Deep research"></iframe>'
    turn = turn.replace(REC_APP, APP_URL)
    if side and APP_URL not in turn:
        import re
        side = re.sub(r'(<div[^>]*data-mcp-app-side-panel-frame-container="true"[^>]*>)',
                      lambda m: m.group(1) + iframe, side, count=1)
    if worked:
        turn = turn.replace("Worked for a few seconds", worked)
    # The recorder lists Stop buttons without their tag: they are buttons.
    stops = [{**s, "tag": s.get("tag") or "BUTTON"}
             for s in ((fr.get("stopButtons") or []) if stop is None else stop)]
    stop_html = "".join(
        '<div style="display:none">' + cp.node_html(s) + "</div>" if s.get("box") == [0, 0, 0, 0]
        else cp.node_html(s) for s in stops)
    body = "<main>" + turn + "</main>" + side + "<form>" + stop_html + "</form>"
    if strip_app:
        body = body.replace(iframe, "")
        for attr in ("data-mcp-app-frame", "data-mcp-app-side-panel-frame-container",
                     "data-mcp-app-portal-target"):
            body = body.replace(attr, "data-sr-was-app")
        body = body.replace(f'<iframe class="h-full min-h-0 min-w-0 w-full" src="{APP_URL}" '
                            'title="Deep research"></iframe>', "")
    return cp.page_html(body)


def _serve(chrome, page, host_html, app_html, host_url=HOST_URL):
    """Serve the host page and the app's frame locally; abort everything else."""
    async def _route(route):
        u = route.request.url
        if u == host_url:
            await route.fulfill(status=200, content_type="text/html", body=host_html)
        elif u.startswith(APP_URL):
            await route.fulfill(status=200, content_type="text/html", body=app_html)
        else:
            await route.abort()

    async def _go():
        await page.unroute("**/*")
        await page.route("**/*", _route)
        await page.goto(host_url)
        for _ in range(50):
            if _app_frame(page) is not None or APP_URL not in host_html:
                break
            await asyncio.sleep(0.1)

    chrome.run(_go())


#: ⚠ ASSUMED — the app's own markup is in no recording. A running app: its
#: status line. A finished app: the report, and, when `download` is on, a
#: header with a download icon (top right, where the 09-30 computer use pressed
#: it) whose menu offers "Export to Markdown" (the row computer use pressed).
def _app_html(state="finished", *, download=True, report="", export=""):
    if state == "running":
        return ('<!doctype html><body><div role="status">Researching…</div>'
                '<div role="progressbar" aria-valuenow="30"></div></body>')
    head = ""
    if download:
        head = ('<header style="display:flex;justify-content:flex-end;height:48px">'
                '<button type="button" aria-label="Share">s</button>'
                '<button type="button" aria-label="Download" id="dl">d</button></header>'
                '<div role="menu" id="menu" hidden>'
                '<div role="menuitem" tabindex="-1" data-kind="md">Export to Markdown</div>'
                '<div role="menuitem" tabindex="-1" data-kind="doc">Export to Word</div></div>')
    script = """<script>
      const press = (w) => { const p = JSON.parse(document.body.dataset.srPressed || '[]');
        p.push(w); document.body.dataset.srPressed = JSON.stringify(p); };
      const dl = document.getElementById('dl');
      if (dl) dl.addEventListener('click', () => { press('download');
        document.getElementById('menu').hidden = false; });
      for (const r of document.querySelectorAll('[role=menuitem]')) r.addEventListener('click', () => {
        press('row:' + r.textContent);
        if (r.dataset.kind !== 'md') return;
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([EXPORT], {type: 'text/markdown'}));
        a.download = 'deep-research-report.md';
        document.body.appendChild(a); a.click(); });
      document.addEventListener('click', (e) => { const x = e.target.closest('a[href^="http"]');
        if (x) { e.preventDefault(); press('link'); } }, true);
    </script>""".replace("EXPORT", json.dumps(export))
    return ("<!doctype html><html><body>" + head + "<article>" + report + "</article>"
            + script + "</body></html>")


def _app_frame(page):
    """The app's frame, found by its address alone (no code under test)."""
    return next((f for f in page.frames if (f.url or "").startswith(APP_URL)), None)


def _pressed_in_app(chrome, page):
    fr = _app_frame(page)
    return json.loads(chrome.run(fr.evaluate("() => document.body.dataset.srPressed || '[]'")))


def test_the_recording_shows_the_app_and_its_stop(chrome):
    """What the done rule stands on, in the recording itself: the app's frame
    from launch to the end, a Stop button (0×0 once the card is up) for the
    whole run, none once it is over, and the finished header reading "Worked
    for a few seconds" — no digit, so the thinking-time pattern never reads it."""
    frames = DR["frames"]
    running = [f for f in frames if 29000 < f["ms"] < 123000]
    finished = [f for f in frames if f["ms"] >= 448000]
    assert running and finished
    assert all(any("web-sandbox.oaiusercontent.com" in (x.get("origin") or "")
                   for x in f["frames"]) for f in running + finished)
    assert all(any(s["a"].get("aria-label") == "Stop" for s in f["stopButtons"]) for f in running)
    assert all(not f["stopButtons"] for f in finished)
    import re
    blob = json.dumps(finished[0]["lastTurn"])
    assert "Worked for a few seconds" in blob
    assert not re.search(research._THINKING_TIME_HEADER_SRC, "Worked for a few seconds", re.I)


def test_the_finished_app_page_is_done_by_its_stop_gone(chrome, page, logs):
    """⭐⭐ The recorded finished page (448 s): no Stop, "Worked for a few
    seconds", the report in the app's frame. Before: no marker at all — the
    badge has no digit, the viewer has no download button — so the page read
    never said done."""
    _serve(chrome, page, _dr_host_html(35), _app_html("finished", download=False,
                                                       report="<p>" + cp.filler(900) + "</p>"))
    done, reason, _snap = chrome.run(research.detect_completion_chatgpt(page))
    assert done is True, reason
    assert reason == "no_stop + done_marker=stop_gone_dr_app ctx=host", reason


def test_the_running_app_page_is_not_done(chrome, page, logs):
    """The recorded running page (39.8 s): the hidden Stop keeps it running."""
    _serve(chrome, page, _dr_host_html(17), _app_html("running"))
    done, reason, _snap = chrome.run(research.detect_completion_chatgpt(page))
    assert done is False and reason.startswith("stop_btn_present"), reason


def test_worked_for_is_never_the_done_sign_on_the_app_page(chrome, page, logs):
    """⛔ "Worked for 7s" (the 09-30 run's wording, with a digit) is on the app's
    page from launch; it is not what says done. With the Stop gone the reason is
    the Stop, not the badge; with the Stop there, not done."""
    _serve(chrome, page, _dr_host_html(17, stop=[], worked="Worked for 7s"), _app_html("running"))
    done, reason, _snap = chrome.run(research.detect_completion_chatgpt(page))
    assert (done, reason) == (True, "no_stop + done_marker=stop_gone_dr_app ctx=host"), reason
    _serve(chrome, page, _dr_host_html(17, worked="Worked for 7s"), _app_html("running"))
    done, reason, _snap = chrome.run(research.detect_completion_chatgpt(page))
    assert done is False and reason.startswith("stop_btn_present"), reason


def test_a_page_without_the_app_is_not_done_by_a_missing_stop(chrome, page, logs):
    """⛔ The rule is the app's: the same finished page with the app taken out
    has no Stop and no marker, and stays not done."""
    chrome.run(page.set_content(_dr_host_html(35, strip_app=True)))
    done, reason, _snap = chrome.run(research.detect_completion_chatgpt(page))
    assert done is False and reason.startswith("no_done_marker"), reason


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "_active_run_sink", lambda: SimpleNamespace(dir=tmp_path))
    monkeypatch.setattr(research, "_CHATGPT_DR_CENSUS_SEEN", {}, raising=False)
    return tmp_path


def test_the_census_is_written_at_launch_and_five_minutes_in(chrome, page, logs, run_dir):
    """The Phase 2 poll's census: the app's frame, in the recorder's own node
    shape, once at launch and once five minutes in — and never twice."""
    _serve(chrome, page, _dr_host_html(17), _app_html("running"))
    p = {"page": page, "start_time": __import__("time").time() - 301}
    chrome.run(research._chatgpt_dr_census_tick(p))
    chrome.run(research._chatgpt_dr_census_tick(p))
    files = sorted(x.name for x in run_dir.iterdir())
    assert files == ["chatgpt_dr_census_launch.json", "chatgpt_dr_census_mid-run.json"], files
    c = json.loads((run_dir / "chatgpt_dr_census_launch.json").read_text(encoding="utf-8"))
    assert c["stage"] == "launch" and len(c["frames"]) == 1
    fr = c["frames"][0]
    assert "web-sandbox.oaiusercontent.com" in fr["origin"]
    assert {"tag", "a", "box", "txtLen"} <= set(fr["tree"])
    assert any((x.get("a") or {}).get("role") == "status" for x in fr["controls"])
    lines = [m for _lv, m in logs if "what its frames hold" in m]
    assert len(lines) == 2 and "(launch)" in lines[0] and "(mid-run)" in lines[1], lines


def test_the_next_conversation_gets_its_own_census(chrome, page, logs, run_dir):
    """Once per stage per CONVERSATION: the same tab in a later run (another
    conversation) writes its launch census again."""
    _serve(chrome, page, _dr_host_html(17), _app_html("running"))
    assert chrome.run(research._chatgpt_dr_census(page, "launch")) is not None
    assert chrome.run(research._chatgpt_dr_census(page, "launch")) is None
    _serve(chrome, page, _dr_host_html(17), _app_html("running"), host_url=HOST_URL + "-next")
    assert chrome.run(research._chatgpt_dr_census(page, "launch")) is not None


def test_the_census_keeps_no_long_text(chrome, page, logs, run_dir):
    _serve(chrome, page, _dr_host_html(35), _app_html(
        "finished", report="<p>" + cp.filler(3000) + "</p><p>short</p>"))
    chrome.run(research._chatgpt_dr_census(page, "done"))
    raw = (run_dir / "chatgpt_dr_census_done.json").read_text(encoding="utf-8")
    assert cp.filler(3000)[:60] not in raw
    assert '"label": "short"' in raw


class _NoCua:
    """Tier 1's computer use, stood in: what it was asked, and the export it
    downloads (the 09-30 path)."""

    def __init__(self, export=""):
        self.calls = 0
        self.export = export

    async def download(self, *a, **k):
        self.calls += 1
        return self.export


def _extract(chrome, page, monkeypatch, cua):
    monkeypatch.setattr(research, "_extract_via_cua_download", cua.download)
    browser = SimpleNamespace(page=page)
    return chrome.run(research.extract_chatgpt_response(page, browser=browser,
                                                        cua_client=object()))


# ═══ 4. The report: downloaded in the frame, its citations linked ═════════════

#: ChatGPT's citation token run: start, separator, end (Private Use Area).
RUN_START, RUN_SEP, RUN_END = chr(0xE200), chr(0xE202), chr(0xE201)


def _run(*ids, kind="cite"):
    return RUN_START + kind + RUN_SEP + RUN_SEP.join(ids) + RUN_END


#: A report shaped like the owner's 09-30 export (documents/chatgpt.md, 100,945
#: chars after the strip; 107,195 before): its citations sit after a sentence's
#: full stop ("…the supplied brief.␣RUN␣The…" — 138 double spaces after a full
#: stop in the stripped file), inside table cells, and at the end of every
#: reference line (91 lines ending in a space); a `filecite` run names the
#: attached brief; and not one URL anywhere. (Words ours; shape the export's.)
#: Each entry: (markdown with {n} where a run goes, [(source url, site, title)]).
SOURCES = [
    ("https://www.akc.org/dog-breeds/golden-retriever/", "American Kennel Club",
     "Golden Retriever Dog Breed Information"),
    ("https://www.thekennelclub.org.uk/breed-standards/gundog/retriever-golden/",
     "The Royal Kennel Club", "Retriever (Golden) breed standard"),
    ("https://www.ofa.org/diseases/breed-statistics", "Orthopedic Foundation for Animals",
     "Breed statistics"),
    ("https://morrisanimalfoundation.org/golden-retriever-lifetime-study",
     "Morris Animal Foundation", "Golden Retriever Lifetime Study"),
    ("https://www.naphia.org/industry-data/", "NAPHIA", "State of the Industry"),
]
BLOCKS = [
    "# Golden Retriever: Breed, Health, Care and Ownership",
    "## Executive summary",
    "This report follows the research mandate specified in the supplied brief. {f} The breed is "
    "a versatile retriever whose trainability makes it an excellent companion for an active "
    "household. {0} Adults usually weigh **25–34 kg**, males larger than females. {0}{1}",
    "## Health and longevity",
    "Hip and elbow dysplasia remain the best-documented orthopedic concerns, and screening "
    "results should be read against each registry's own population. {2} Cancer is the "
    "leading cause of death in the long-running cohort study. {3}",
    "| Dimension | Profile |\n|---|---|\n| Original function | Land-and-water game retriever "
    "developed in nineteenth-century Scotland. {1} |\n| Insurance | Average premiums for large "
    "dogs rose again in the latest industry data. {4} |",
    "## Bibliography",
    "American Kennel Club. Golden Retriever dog breed information and standard. {0}",
    "Orthopedic Foundation for Animals. Breed statistics for hips and elbows. {2}",
    "Morris Animal Foundation. Golden Retriever Lifetime Study, cohort findings. {3}",
]


def _export():
    """The report as the export writes it: token runs, no URL."""
    out = []
    for b in BLOCKS:
        s = b.replace("{f}", _run("turn0file0", kind="filecite"))
        for i in range(len(SOURCES)):
            s = s.replace("{%d}" % i, _run(f"turn{10 + i}view0", f"turn{10 + i}view1"))
        out.append(s)
    return "\n\n".join(out) + "\n"


def _pill(i):
    """A citation as Phase 1's reply renders one (4-chatgpt-p1-thinking.json:
    span[data-state] > span[data-search-result-target] >
    a[data-testid=chatgpt-citation], aria-label "Site: Title, url") — ⚠ ASSUMED
    to be how the app's rendered report draws it too."""
    url, site, title = SOURCES[i]
    return ('<span class="contents" data-state="closed"><span class="ms-1 inline-flex" '
            'data-search-result-target=""><a data-testid="chatgpt-citation" '
            f'aria-label="{_html.escape(site)}: {_html.escape(title)}, {url}" '
            f'href="{url}">{_html.escape(site)} +1</a></span></span>')


def _rendered():
    """The same report as the app renders it: HTML, each run a citation link."""
    import re
    html_out = []
    for b in BLOCKS:
        s = _html.escape(b, quote=False)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = s.replace("{f}", "")
        for i in range(len(SOURCES)):
            s = s.replace("{%d}" % i, _pill(i))
        if s.startswith("# "):
            html_out.append("<h1>" + s[2:] + "</h1>")
        elif s.startswith("## "):
            html_out.append("<h2>" + s[3:] + "</h2>")
        elif s.startswith("|"):
            rows = [r for r in s.split("\n") if r and not r.startswith("|---")]
            html_out.append("<table>" + "".join(
                "<tr>" + "".join(f"<td>{c.strip()}</td>" for c in r.strip("|").split("|")) + "</tr>"
                for r in rows) + "</table>")
        else:
            html_out.append("<p>" + s + "</p>")
    return "".join(html_out)


def test_the_export_is_shaped_like_the_0930_one():
    md = _export()
    assert "http" not in md
    assert md.count(RUN_START) == 11 and md.count("filecite") == 1
    stripped = research._strip_chatgpt_citation_tokens(md)
    # The 09-30 document's own marks of a removed run.
    assert "brief.  The breed" in stripped and "Scotland.  |" in stripped
    assert "Study, cohort findings. \n" in stripped


def test_the_document_ends_with_its_numbered_sources(chrome, page, logs, run_dir, monkeypatch):
    """⭐⭐ THE OWNER'S 09-30 DOCUMENT: no sources, no footnotes. The export came
    through computer use (Tier 1) as on 09-30, its citations only token runs;
    the report the app shows links each citation. Now every run becomes the
    link shown after the same words, and the document — numbered by the same
    code as every other agent's — ends with its numbered sources, each marker
    in the text linking to its source."""
    _serve(chrome, page, _dr_host_html(35),
           _app_html("finished", download=False, report=_rendered()))
    cua = _NoCua(_export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 1, "Tier 1 was not the path, as it was on 09-30"
    assert RUN_START not in md and RUN_END not in md
    doc = research._document_with_sources("# ChatGPT Deep Research\n\n" + md)
    urls = [u for u, _s, _t in SOURCES]
    assert "\n##### Sources" in doc, "the document ends with no sources (09-30)"
    tail = doc[doc.rindex("Sources"):]
    for n, u in enumerate(urls, 1):
        assert f"{n}. [" in tail and u in tail, (n, u, tail)
    body = doc[:doc.rindex("Sources")]
    for n, u in enumerate(urls, 1):
        assert research._doc_source_marker(n, u) in body, (n, u)
    # Each marker sits at the end of the sentence the report cited, its sources
    # linked by the name the page shows on the citation.
    akc, rkc = SOURCES[0][0], SOURCES[1][0]
    assert ("an excellent companion for an active household "
            f"[American Kennel Club]({akc}) " + research._doc_source_marker(1, akc) + ".") in body
    # Two citations side by side: both sources, one sentence.
    assert (f"males larger than females [American Kennel Club]({akc}) "
            f"[The Royal Kennel Club]({rkc}) " + research._doc_source_marker(2, rkc) + ".") in body
    assert any("Citations: 10 of 11 in the report linked" in m for _lv, m in logs), \
        [m for _lv, m in logs if "Citations" in m]


def test_a_citation_the_page_does_not_show_is_removed_as_before(chrome):
    md, linked, seen = research._chatgpt_cite_runs_to_links(_export(), [])
    assert (linked, seen) == (0, 11)
    assert research._strip_chatgpt_citation_tokens(md) == research._strip_chatgpt_citation_tokens(
        _export())


def test_the_link_goes_before_the_full_stop_of_the_cited_sentence():
    links = [{"url": SOURCES[2][0], "label": "OFA: Breed statistics, " + SOURCES[2][0],
              "text": "OFA", "before": "its own population."}]
    md = "Screening results should be read against its own population. " + _run("turn1view0") + " Next."
    out, linked, _seen = research._chatgpt_cite_runs_to_links(md, links)
    assert linked == 1
    assert out == ("Screening results should be read against its own population "
                   f"[OFA]({SOURCES[2][0]}).  Next."), out


def test_the_report_is_downloaded_inside_the_app_frame(chrome, page, logs, run_dir, monkeypatch):
    """⭐ The finished app shows a download icon at its top right and a menu with
    "Export to Markdown" (what computer use pressed on 09-30): the page presses
    both, the file is the report, and computer use is never asked."""
    _serve(chrome, page, _dr_host_html(35),
           _app_html("finished", download=True, report=_rendered(), export=_export()))
    cua = _NoCua("")
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 0, "computer use was asked although the page could download"
    assert _pressed_in_app(chrome, page) == ["download", "row:Export to Markdown"]
    assert md.startswith("# Golden Retriever") and SOURCES[0][0] in md
    assert any("Extracted via T0 page download (Export to Markdown)" in m for _lv, m in logs)


def test_no_download_control_leaves_the_download_to_computer_use(chrome, page, logs, run_dir,
                                                                  monkeypatch):
    """No control in the frame: nothing is pressed, a census of the miss is
    written, and computer use downloads it as before."""
    _serve(chrome, page, _dr_host_html(35),
           _app_html("finished", download=False, report=_rendered()))
    cua = _NoCua(_export())
    md = _extract(chrome, page, monkeypatch, cua)
    assert cua.calls == 1 and md.startswith("# Golden Retriever")
    assert _pressed_in_app(chrome, page) == []
    assert (run_dir / "chatgpt_dr_census_miss-download.json").exists()
    assert (run_dir / "chatgpt_dr_census_done.json").exists()


def test_the_download_never_fires_while_the_research_runs(chrome, page, logs, run_dir):
    """⛔ The running app (the recording at 39.8 s): no download control — the
    page download finds nothing and presses nothing."""
    _serve(chrome, page, _dr_host_html(17), _app_html("running"))
    assert chrome.run(research._chatgpt_dr_dom_download(page)) == ""
    assert _pressed_in_app(chrome, page) == []


def test_a_link_in_the_report_is_never_taken_for_the_download(chrome, page, logs, run_dir):
    """⛔ The report's own link saying "Download the dataset" is not a control."""
    rep = '<p><a href="https://example.org/data.csv">Download the dataset</a></p>'
    _serve(chrome, page, _dr_host_html(35), _app_html("finished", download=False, report=rep))
    assert chrome.run(research._chatgpt_dr_dom_download(page)) == ""
    assert _pressed_in_app(chrome, page) == []


def test_the_phase2_poll_writes_the_census_for_chatgpt_only(monkeypatch):
    """The census moments ride on the Phase 2 poll's own page read — the real
    statements of `poll_all_agents_round_robin`, lifted as round 1's test does —
    and only for ChatGPT."""
    import test_p2_stop_skips_cua_e2e0930 as rr
    ticks = []

    async def _tick(p, **k):
        ticks.append(k.get("label"))

    monkeypatch.setattr(research, "_chatgpt_dr_census_tick", _tick, raising=False)
    for name in ("ChatGPT", "Claude"):
        rr._run_polls(name, [rr.STOP] * 2, lines=[], looks=[])
    assert ticks == ["ChatGPT", "ChatGPT"], ticks
