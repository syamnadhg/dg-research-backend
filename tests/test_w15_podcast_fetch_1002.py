"""Wave 15 (10-02) — the podcast without a Chrome download.

⛔⛔ THE CRASH CLASS. Chrome 154 crashes in its own downloads button while a
download updates (#Dev/wave15/crash/crash-analysis-1001.json), and NotebookLM
audio downloads killed the browser twice on 09-16, the instant the page pressed
them ("Download save failed: Download.save_as: Target page, context or browser
has been closed"). Every run still downloaded the podcast in Chrome: "Audio
downloaded via Playwright: ….m4a".

⭐ WHAT THE DOWNLOAD IS: this Mac's agent-profile download history — every
NotebookLM audio download starts at
`https://lh3.googleusercontent.com/notebooklm/<token>=m140-dv-mp2?authuser=0`.

⭐ NOW: while the page's own ⋮ → Download is pressed, the browser context stops
that request before Chrome can start a download, and the file is fetched from
the address with the context's own request API (its cookies). If that fails,
Download is pressed again with the catch off, and Chrome downloads it as before
— with a log line saying so.

── How it is measured ──────────────────────────────────────────────────────
Phase 3's REAL audio step, `run_phase3_audio`, in headless Chrome on the capture-5
NotebookLM page (test_nlm_customise_0930's fixture) with a finished audio card
whose real ⋮ menu and Download row are pressed by the step's own DOM rung. The
Download row asks for the audio's address the two ways a page can — following a
link in the same tab, or opening a tab — and the context's REAL route stops it.
Only the request API is a stand-in (it records what it is asked for and answers
with an audio file), and a catch-all route of the test's own stops anything else
that would leave the machine. Time is a clock the step's own sleeps move.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

import research
from test_nlm_customise_0930 import NB_URL
from test_nlm_customise_0930 import chrome as _customise_chrome  # noqa: F401  (fixture)
from test_nlm_short_deep_dive_0930 import DEEP_14, _Reloads, _studio_with_menus

AUDIO_URL = ("https://lh3.googleusercontent.com/notebooklm/AKYWMX_mHaNT736Amw27y3MqHGHb"
             "JpsNOM67fZzAxC1lmgsRhs1XHeeikljrjCm5Qdd77ud2K5lZJSpgbrtCU=m140-dv-mp2?authuser=0")
#: An audio file as NotebookLM serves it: an ISO container whose brand says M4A.
#: (Built from bytes, never typed as escapes.)
M4A = bytes([0, 0, 0, 32]) + b"ftypM4A " + bytes(4) + b"M4A mp42isom" + bytes(200_000)


#: A thumbnail on the same host and path, as NotebookLM's own page draws them.
THUMB_URL = "https://lh3.googleusercontent.com/notebooklm/AKYWMXthumbnail0001=w64-h64"
#: The player's own stream of the audio, on the same host and path.
PLAYER_URL = ("https://lh3.googleusercontent.com/notebooklm/AKYWMXplayerstream0001"
              "=m140?authuser=0")


def _download_row_asks(how: str) -> str:
    """A script for the fixture page: pressing the menu's Download row first
    draws a thumbnail from the audio's own host (an image the catch must let
    through), then asks for the audio's address `how` — "same_tab" (a link
    followed), "new_tab" (a tab opened on it) or "blank_tab" (a tab opened
    blank, then sent to it — the tab that must be closed)."""
    act = {
        # Asks for nothing on the audio's host: no address the catch can keep.
        "nothing": "null",
        # The player loads its own stream from the same host first (a media
        # request the catch must let through), then the link is followed.
        "player_first": "{ const au = new Audio(); au.src = P; au.load();"
                        " setTimeout(() => { const a = document.createElement('a');"
                        " a.href = U; document.body.append(a); a.click(); }, 150); }",
        "new_tab": "window.open(U, '_blank')",
        # A tab opened blank first and sent to the address: the tab is there.
        "blank_tab": "{ const w = window.open('about:blank', '_blank');"
                     " setTimeout(() => { w.location.href = U; }, 30); }",
        "same_tab": "{ const a = document.createElement('a'); a.href = U;"
                    " document.body.append(a); a.click(); }",
    }[how]
    return ("<script>document.addEventListener('click', (e) => {"
            " const row = e.target.closest('[role=\"menuitem\"]');"
            " if (!row || row.textContent.trim() !== 'Download') return;"
            f" const img = new Image(); img.src = {THUMB_URL!r}; document.body.append(img);"
            f" const U = {AUDIO_URL!r}; const P = {PLAYER_URL!r};"
            f" setTimeout(() => {act}, 60);"
            "});</script>")


@pytest.fixture(scope="module")
def chrome(request):
    """test_nlm_customise_0930's headless Chrome (aliased: see the lint floor)."""
    return request.getfixturevalue("_customise_chrome")


class _Clock:
    def __init__(self):
        self.t = time.time()

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return self.t


class _Answer:
    def __init__(self, status, body, headers):
        self.status, self._body, self.headers = status, body, headers
        self.ok = 200 <= status < 300

    async def body(self):
        return self._body

    async def dispose(self):
        return None


class _RequestApi:
    """The context's request API: records each address it is asked to fetch."""

    def __init__(self, status=200, body=M4A, headers=None):
        self.asked, self._answer = [], (status, body, headers or {
            "content-type": "audio/mp4",
            "content-disposition": 'attachment; filename="Golden Retriever $Story.m4a"'})

    async def get(self, url, **k):
        self.asked.append(url)
        return _Answer(*self._answer)


class _Context:
    """The REAL browser context — its routes are real — with the request API
    stood in for."""

    def __init__(self, ctx, api):
        self._ctx, self.request = ctx, api

    def __getattr__(self, name):
        return getattr(self._ctx, name)


class _Controls:
    skipped_agents: set = set()

    async def interruptible_sleep(self, *a, **k):
        return None

    def is_stop(self):
        return False

    def is_pause(self):
        return False


class _HandedToComputerUse(BaseException):
    """The download reached computer use: today's way, the fallback."""


def _run(chrome, monkeypatch, tmp_path, *, how="same_tab", api=None):
    """Run the audio step to its end (or to computer use). Returns what it
    returned, the request API, computer use's steps, the log, the Chrome
    downloads seen, and the page's menu presses."""
    import json
    lines, cua, downloads = [], [], []
    api = api or _RequestApi()
    clock = _Clock()

    class _FastAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(secs=0, *a, **k):
            clock.t += float(secs or 0)
            await asyncio.sleep(min(float(secs or 0), 0.02))

    async def _cua(page, **k):
        cua.append(k.get("current_step"))
        if k.get("current_step") == "download_audio_overview":
            raise _HandedToComputerUse()
        return {"text": "generating"}

    async def _none(*a, **k):
        return None

    async def _false(*a, **k):
        return False

    async def _true(*a, **k):
        return True

    async def _published(path, rid):
        return f"stored:{path.name}" if path else ""

    monkeypatch.setattr(research, "log", lambda m, lv="INFO", *a, **k: lines.append(str(m)))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research, "time", clock)
    monkeypatch.setattr(research, "_controls", _Controls())
    monkeypatch.setattr(research, "_work_tab_signed_out", _false)
    monkeypatch.setattr(research, "_browser_context_is_dead", _false)
    monkeypatch.setattr(research, "check_hv_gate", _true)
    monkeypatch.setattr(research, "start_narration_ticker", lambda *a, **k: (None, None))
    monkeypatch.setattr(research, "stop_narration_ticker", _none)
    monkeypatch.setattr(research, "_observe_dom_success", lambda *a, **k: None)
    monkeypatch.setattr(research, "_dump_nlm_audio_dom", _none)
    monkeypatch.setattr(research, "_shadow_observed_cua", _cua)
    monkeypatch.setattr(research, "_transcode_audio_to_mp3", lambda p: p)
    monkeypatch.setattr(research, "_p3_publish_audio", _published)
    monkeypatch.setattr(research, "_find_recent_audio", lambda *_a, **_k: (None, "", False))

    ctx = chrome.ctx
    stopped = []

    async def _nothing_leaves(route):
        # Answered here, never sent — and answered as a page that went nowhere
        # (204), so a link the fixture follows leaves the notebook where it was.
        stopped.append(route.request.url)
        await route.fulfill(status=204, body="")

    page = chrome.run(ctx.new_page())
    # The test's own catch-all, under the step's: nothing leaves the machine.
    chrome.run(ctx.route("**/*", _nothing_leaves))
    page.on("download", lambda d: downloads.append(d.suggested_filename))
    pages_before = len(ctx.pages)
    out = None
    try:
        html = _studio_with_menus(DEEP_14)
        html = html.replace("</body>", _download_row_asks(how) + "</body>")
        chrome.run(page.set_content(html))

        async def _url():
            return NB_URL

        # The step reloads the notebook between polls; the fixture page stays.
        browser = SimpleNamespace(page=_Reloads(page), current_url=_url,
                                  context=_Context(ctx, api))
        try:
            out = chrome.run(research.run_phase3_audio.__wrapped__(
                browser, object(), NB_URL, tmp_path, podcast_length="default",
                prefer_existing_audio=True))
        except _HandedToComputerUse:
            out = None
        presses = json.loads(chrome.run(page.evaluate("() => document.body.dataset.menus || '[]'")))
        extra_pages = len(ctx.pages) - pages_before
    finally:
        chrome.run(ctx.unroute("**/*", _nothing_leaves))
        chrome.run(page.close())
    return SimpleNamespace(out=out, api=api, cua=cua, lines=lines, downloads=downloads,
                           presses=presses, extra_pages=extra_pages, stopped=stopped)


def _said(r, text):
    return [m for m in r.lines if text in m]


@pytest.mark.parametrize("how", ["same_tab", "new_tab", "blank_tab"])
def test_the_podcast_is_fetched_from_its_address_with_no_chrome_download(
        chrome, monkeypatch, tmp_path, how):
    """⭐⭐ THE FEATURE. The page's own Download is pressed once; the request it
    makes for the audio is stopped before Chrome sees a download, and the file is
    fetched from that very address with the context's request API; it is what
    the step returns and publishes. No computer use, no Chrome download, no tab
    left behind. Before: "Audio downloaded via Playwright"."""
    r = _run(chrome, monkeypatch, tmp_path, how=how)
    assert r.api.asked == [AUDIO_URL], r.api.asked
    # The thumbnail on the same host was let through, not taken for the audio.
    assert THUMB_URL in r.stopped, r.stopped
    assert r.downloads == [], "Chrome started a download"
    assert "download_audio_overview" not in r.cua, r.cua
    path = r.out["audio_path"]
    assert path.parent == tmp_path / "podcasts" and path.read_bytes() == M4A
    assert path.name == "Golden Retriever Story.m4a", path.name
    assert r.out["audio_stored_url"] == f"stored:{path.name}"
    assert [p for p in r.presses if p.startswith("download:")] == [
        "download:The Golden Retriever Question"], r.presses
    assert r.extra_pages == 0, "the tab the Download opened was left open"
    assert _said(r, "Audio fetched straight from its address, no Chrome download")
    assert not _said(r, "Audio downloaded via Playwright")
    assert AUDIO_URL not in "\n".join(r.lines), "the audio's address is a credential"


@pytest.mark.parametrize("api, why", [
    (_RequestApi(status=403), "was refused (HTTP 403)"),
    (_RequestApi(body=b"<html>sign in</html>" * 10), "not an audio overview"),
    (_RequestApi(body=bytes(100_000), headers={"content-type": "text/html"}),
     "is not audio"),
], ids=["refused", "too-small", "not-audio"])
def test_a_fetch_that_fails_falls_back_to_todays_download_and_says_so(
        chrome, monkeypatch, tmp_path, api, why):
    """⛔ The fallback: the catch comes off, Download is pressed again, and the
    podcast goes through Chrome as before (here, on to the step's own fallbacks,
    up to computer use) — with a line saying why."""
    r = _run(chrome, monkeypatch, tmp_path, api=api)
    assert r.api.asked == [AUDIO_URL]
    assert _said(r, why), r.lines[-30:]
    assert _said(r, "pressing Download again, and Chrome downloads it as before")
    assert [p for p in r.presses if p.startswith("download:")] == [
        "download:The Golden Retriever Question"] * 2, r.presses
    # The second press was not stopped by the step: it went to the test's own
    # catch-all, as it would have gone to Chrome.
    assert AUDIO_URL in r.stopped
    assert not (tmp_path / "podcasts" / ".audio_fetch.part").exists()
    assert not list((tmp_path / "podcasts").glob("*.m4a"))


def test_the_players_own_stream_is_let_through_and_the_download_is_fetched(
        chrome, monkeypatch, tmp_path):
    """Review 10-02. The press first loads the player's own stream from the
    audio's host (a media request), then follows the download link. The stream
    is let through to the page, untouched; the address fetched is the
    download's. Taking the stream would answer the player with nothing and fetch
    the wrong address."""
    r = _run(chrome, monkeypatch, tmp_path, how="player_first")
    assert PLAYER_URL in r.stopped, r.stopped
    assert r.api.asked == [AUDIO_URL], r.api.asked
    assert r.out["audio_path"].read_bytes() == M4A


def test_a_download_that_asks_for_no_audio_address_says_chrome_downloads_it(
        chrome, monkeypatch, tmp_path):
    """Review 10-02. The page's Download is pressed and asks for nothing on the
    audio's host: nothing is fetched, and the log says, once, that Chrome
    downloads it as before (here, on to the step's own fallbacks)."""
    r = _run(chrome, monkeypatch, tmp_path, how="nothing")
    assert r.api.asked == []
    assert len(_said(r, "the page's Download asked for no audio address this run "
                        "knows — Chrome downloads it, as before")) == 1, r.lines[-30:]
    assert not _said(r, "pressing Download again")
