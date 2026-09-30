"""A podcast resumed after a Chrome death goes back to the notebook it made.

⛔⛔ THE DEFECT (wave 13, the 09-16 bundle). When Chrome died during the podcast
step, the silent relaunch resumed the run at Phase 3 — and Phase 3 always began
by clicking "Create new notebook". The notebook the run had already made, and
the podcast inside it that was generating or already finished, were forgotten.
One research on 09-16 made three notebooks and three podcasts; a finished
29-minute podcast was thrown away, and after 1h40m in the podcast step the
person still got no podcast.

⭐ THE FIX. The checkpoint already records the notebook before the podcast step
starts. A resumed Phase 3 now opens that notebook first and carries on in it —
the podcast step then adopts a finished podcast, waits on one still being made,
or starts one in the same notebook. A new notebook is made only when the old
one is not there to carry on in.

⛔⛔ THE SECOND DEFECT. When Chrome died at the moment the finished podcast was
downloaded, nothing asked whether the browser was still there: the no-audio
retry loop waited five minutes and "retried" three times on the dead browser,
then ended the run without the podcast. It now asks first, and a dead browser
goes down the crash path — relaunch Chrome, resume, and (with the fix above)
download the finished podcast from the same notebook.

▶ EXECUTED, NOT READ. Every test drives the REAL `run_pipeline` from a resume
directory into Phase 3. Only the edges are stubbed: the network, the log, and
NotebookLM's page. The browser is a fake that runs the real
`Browser.navigate` / `new_tab` / `current_url` on fake tabs — `research.Browser`
itself is never constructed (it opens a visible window) and no test opens a
real website.
"""
import asyncio
import json

import pytest

import research


NB_ID = "9351b159-2d9d-4ffe-bc41-44a1b1129bcb"
# The host the owner's machine sees today (09-16 log). It does not contain
# "notebooklm", so the podcast step navigates to the notebook itself — as live.
NB_URL = f"https://notebook.google.com/notebook/{NB_ID}"
NEW_NB_URL = "https://notebook.google.com/notebook/7187233f-16e7-47a1-b316-665ae3d717fb"
# ANOTHER research's notebook. Every research uploads the same file names.
OTHER_ID = "c8819561-73f1-4041-9b3e-384df0b34e19"
OTHER_NB_URL = f"https://notebook.google.com/notebook/{OTHER_ID}"
HOME_URL = "https://notebook.google.com/"
SIGN_IN_URL = "https://accounts.google.com/v3/signin/identifier?continue=nlm"
SOURCES = ("chatgpt.md", "gemini.md")

_REAL_RUN_PHASE3_AUDIO = research.run_phase3_audio
_REAL_PLAN = research._plan_pipeline_auto_retry
_REAL_P3_PUBLISH = research._p3_publish_audio


class _Reached(Exception):
    """Raised by a fake podcast step to end the run once it has been asked."""


class _Closed(Exception):
    """What the driver raises once Chrome is gone."""

    def __init__(self, where="BrowserContext.cookies"):
        super().__init__(f"{where}: Target page, context or browser has been closed")


class _Notebook:
    """The one NotebookLM notebook this research made, as its page shows it."""

    def __init__(self):
        self.exists = True
        self.sources = set(SOURCES)
        self.ready = 0
        self.generating = 0
        self.signed_in = True
        # Where NotebookLM sends a tab asked for this notebook once it is gone.
        self.gone_to = HOME_URL
        # Another research's notebook, when a test needs one on screen.
        self.other: "_Notebook | None" = None


class _FakePage:
    def __init__(self, browser, url="about:blank"):
        self._browser = browser
        self.url = url
        self.closed = False
        self.download_handlers = []
        self.asked_for = ""

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True

    async def goto(self, url, **_k):
        if self._browser.dead or self.closed:
            raise _Closed("Page.goto")
        self.asked_for = self.asked_for or url
        self.url = self._browser._land(url)

    async def evaluate(self, *_a, **_k):
        if self._browser.dead or self.closed:
            raise _Closed("Page.evaluate")
        return False

    def on(self, event, handler):
        if event == "download":
            self.download_handlers.append(handler)

    def remove_listener(self, event, handler):
        if handler in self.download_handlers:
            self.download_handlers.remove(handler)


class _FakeContext:
    def __init__(self, browser):
        self._browser = browser

    async def cookies(self, *_a, **_k):
        if self._browser.dead:
            raise _Closed("BrowserContext.cookies")
        return []

    async def new_page(self):
        if self._browser.dead:
            raise _Closed("BrowserContext.new_page")
        page = _FakePage(self._browser)
        self._browser.pages.append(page)
        return page


class _FakeBrowser:
    """Stands in for `research.Browser`, which is never constructed here.

    Its navigation is master's OWN code: the three methods below are the real
    `Browser` functions, run against this object's fake context and tabs."""

    navigate = research.Browser.navigate
    new_tab = research.Browser.new_tab
    current_url = research.Browser.current_url

    notebook: "_Notebook" = None
    instances: list = []

    def __init__(self, *_a, **_k):
        self.dead = False
        self.context = _FakeContext(self)
        self.page = _FakePage(self)
        self._known_pages = set()
        self.opened: list = []
        self.pages: list = []
        _FakeBrowser.instances.append(self)

    def _attach_file_handler(self, _page):
        return None

    async def start(self):
        return None

    async def close(self):
        return None

    def die(self):
        """Chrome crashes: every tab and the context go with it."""
        self.dead = True
        self.page.closed = True

    def _land(self, url):
        """Where NotebookLM puts a tab asked for `url`."""
        self.opened.append(url)
        nb = _FakeBrowser.notebook
        if not nb.signed_in:
            return SIGN_IN_URL
        if research._nlm_notebook_id(url) == NB_ID and not nb.exists:
            return nb.gone_to
        return url

    def set_upload_file(self, *_a):
        return None

    def clear_upload_file(self):
        return None


def _shown(page):
    """The notebook this tab shows, or None."""
    if getattr(page, "closed", False):
        return None
    nb = _FakeBrowser.notebook
    here = research._nlm_notebook_id(getattr(page, "url", "") or "")
    if here == NB_ID and nb.exists:
        return nb
    if here == OTHER_ID and nb.other is not None:
        return nb.other
    return None


def _on_the_notebook(page):
    return _shown(page) is _FakeBrowser.notebook


class _FailingDownload:
    suggested_filename = "State.m4a"

    async def save_as(self, _dest):
        raise _Closed("Download.save_as")


class _GoodDownload:
    suggested_filename = "State.m4a"

    async def save_as(self, dest):
        with open(dest, "wb") as fh:
            fh.write(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 8192)


@pytest.fixture
def resumed(tmp_path, monkeypatch):
    """A research whose Chrome died in the podcast step, resumed at Phase 3.

    Returns `(run, nb, queue_dir, seen)`. `run(audio)` drives the real
    `run_pipeline`; `audio` is the podcast step — a fake
    `audio(browser, notebook_url, prefer_existing_audio)`, or None for the real
    `run_phase3_audio`."""
    queue_dir = tmp_path / "Grid_storage_20260916_114045"
    docs = queue_dir / "documents"
    docs.mkdir(parents=True)
    (docs / "brief.md").write_text("# Research Brief\n\n" + "brief " * 60, encoding="utf-8")
    for name in SOURCES:
        (docs / name).write_text(f"# {name}\n\n" + "finding " * 80, encoding="utf-8")
    (queue_dir / "links.json").write_text("{}", encoding="utf-8")
    (queue_dir / "config.json").write_text(
        '{"skipInitVerify": true, "skipPhases": [4, 5]}', encoding="utf-8")
    # What the first attempt recorded before its podcast step began.
    research.save_checkpoint(queue_dir, 3, topic="Grid storage", brief_url="",
                             notebook_url=NB_URL)

    nb = _Notebook()
    _FakeBrowser.notebook = nb
    _FakeBrowser.instances = []
    seen = {"created": 0, "audio": [], "plan": [], "cards": [], "lines": [],
            "waits": [], "downloads": [], "published": [], "hotspots": [],
            "shared": 0}

    monkeypatch.setattr(research, "resolve_api_key", lambda *_a, **_k: "test-key")
    monkeypatch.setattr(research, "_capture_anthropic_attribution", lambda *a, **k: None)
    monkeypatch.setattr(research, "clear_clipboard", lambda *a, **k: None)
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: seen["lines"].append(str(msg)))
    monkeypatch.setattr(research, "init_tracks", lambda *a, **k: None)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    monkeypatch.setattr(research, "Browser", _FakeBrowser)
    monkeypatch.setattr(research, "_profile_dir", lambda *_a, **_k: tmp_path / "profile")
    monkeypatch.setattr(research, "_update_firestore_research", lambda *a, **k: None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "fail_phase",
                        lambda *a, **k: seen["cards"].append(a[1] if len(a) > 1 else k.get("error")))
    monkeypatch.setattr(research, "_probe_google_credentials", lambda *a, **k: None)
    monkeypatch.setattr(research, "_post_fe_p4p5_trigger", lambda *a, **k: None)
    monkeypatch.setattr(research, "_save_meta_in_background", lambda *a, **k: None)
    monkeypatch.setattr(research, "_observe_dom_success", lambda *a, **k: None)

    async def _none(*_a, **_k):
        return None
    for name in ("run_input_dispatcher", "_probe_cua_available", "_dump_nlm_audio_dom"):
        monkeypatch.setattr(research, name, _none)

    async def _scrub(*_a, **_k):
        return {}
    monkeypatch.setattr(research, "_scrub_persisted_google_auth", _scrub)

    async def _gate(*_a, **_k):
        return "ok"
    monkeypatch.setattr(research, "_phase_verify_gate", _gate)

    async def _hv(*_a, **_k):
        return True
    monkeypatch.setattr(research, "check_hv_gate", _hv)

    # ── NotebookLM's page, read from whichever fake notebook the tab shows ──
    async def _census(page, expected):
        shown = _shown(page)
        if shown is None:
            return set(), -1
        return {n for n in expected if n in shown.sources}, (len(shown.sources) or -1)
    monkeypatch.setattr(research, "_nlm_visible_source_names", _census)

    async def _ready(page):
        shown = _shown(page)
        return shown.ready if shown is not None else 0
    monkeypatch.setattr(research, "_count_nlm_audio_cards", _ready)
    monkeypatch.setattr(research, "_count_nlm_deep_dive_cards", _ready)

    async def _generating(page):
        shown = _shown(page)
        return shown.generating if shown is not None else 0
    monkeypatch.setattr(research, "_count_nlm_audio_generating", _generating)

    async def _complete(page):
        # The podcast is finished wherever the podcast step looks: on the base
        # code that is a NEW notebook, and the run must not poll for ever.
        return not getattr(page, "closed", False)
    monkeypatch.setattr(research, "_check_audio_complete_dom", _complete)

    async def _pick(page, *_a, **_k):
        return {"count": 1, "target_ordinal": 1, "complete": True, "reason": "test"}
    monkeypatch.setattr(research, "_pick_nlm_audio_card", _pick)

    async def _menu(*_a, **_k):
        return {"verified": False, "why": "test drives the visual rung"}
    monkeypatch.setattr(research, "_nlm_open_audio_menu", _menu)

    # ── making a NEW notebook: what the base code did on every resume ──
    async def _upload(browser, page, md_files, **_k):
        seen["created"] += 1
        page.url = NEW_NB_URL
        return {p.name for p in md_files}
    monkeypatch.setattr(research, "_nlm_dom_upload_sources", _upload)

    async def _repair(*_a, **_k):
        return set()
    monkeypatch.setattr(research, "_verify_and_repair_nlm_sources", _repair)

    async def _rename(*_a, **_k):
        return True
    monkeypatch.setattr(research, "_nlm_dom_rename", _rename)

    async def _share(browser, *_a, **_k):
        seen["shared"] += 1
        return research.LinkResult(url=browser.page.url, verified=True)
    monkeypatch.setattr(research, "extract_notebooklm_url", _share)

    # ── the visual agent: only the download click does anything. Each click
    # takes the next outcome from `nb.downloads`: "saved", "chrome died"
    # (09-16: Chrome gone two seconds after the click) or "no file" (the
    # download failed on a live browser). An empty plan saves.
    async def _cua(page, *, hotspot_id, **_k):
        seen["hotspots"].append(hotspot_id)
        if hotspot_id == "audio-download":
            browser = _FakeBrowser.instances[-1]
            outcome = nb.downloads.pop(0) if nb.downloads else "saved"
            seen["downloads"].append(outcome)
            if outcome == "chrome died":
                browser.die()
            for handler in list(page.download_handlers):
                await handler(_GoodDownload() if outcome == "saved" else _FailingDownload())
        return {}
    monkeypatch.setattr(research, "_shadow_observed_cua", _cua)
    nb.downloads = []

    def _no_scan(*_a, **_k):
        return (None, "", False)
    monkeypatch.setattr(research, "_find_recent_audio", _no_scan)
    monkeypatch.setattr(research, "_transcode_audio_to_mp3", lambda p: p)

    async def _publish(audio_path, _rid):
        seen["published"].append(audio_path)
        return "https://firebasestorage.example/podcast.m4a" if audio_path else ""
    monkeypatch.setattr(research, "_p3_publish_audio", _publish)

    # ── the waits between podcast retries: recorded, not slept ──
    async def _wait(seconds, *_a, **_k):
        seen["waits"].append(seconds)
        return None
    monkeypatch.setattr(research._controls, "interruptible_sleep", _wait)

    # ── no person answers a card here. A card's wait is bounded by a day, so a
    # run that reached one would sit for a day: it is answered Skip at once.
    async def _skip(*_a, **_k):
        return "skip"
    monkeypatch.setattr(research._controls, "await_phase_decision", _skip)

    real_sleep = asyncio.sleep

    async def _fast_sleep(_d=0, *a, **k):
        await real_sleep(0)
    monkeypatch.setattr(research.asyncio, "sleep", _fast_sleep)

    def _plan(qd, rd, kind, crash_retries):
        seen["plan"].append(kind)
        return (False, 0, kind == "browser_crash")
    monkeypatch.setattr(research, "_plan_pipeline_auto_retry", _plan)

    async def _relaunch(**kw):
        kw.pop("_submitted_by", None)
        await research.run_pipeline(**kw)
    monkeypatch.setattr(research, "run_pipeline_captured", _relaunch)

    def _run(audio, crash_retries=0):
        if audio is None:
            async def _podcast_step(browser, cua_client, notebook_url, queue_dir, verbose=False,
                                    podcast_length="long", prefer_existing_audio=False):
                seen["audio"].append({"url": notebook_url,
                                      "prefer_existing_audio": prefer_existing_audio})
                return await _REAL_RUN_PHASE3_AUDIO(
                    browser, cua_client, notebook_url, queue_dir, verbose,
                    podcast_length=podcast_length,
                    prefer_existing_audio=prefer_existing_audio)
        else:
            async def _podcast_step(browser, cua_client, notebook_url, queue_dir, verbose=False,
                                    podcast_length="long", prefer_existing_audio=False):
                seen["audio"].append({"url": notebook_url,
                                      "prefer_existing_audio": prefer_existing_audio,
                                      "tab": browser.page.url})
                return await audio(browser, notebook_url, prefer_existing_audio)
        monkeypatch.setattr(research, "run_phase3_audio", _podcast_step)
        asyncio.run(research.run_pipeline(
            topic="Grid storage", resume_dir=str(queue_dir),
            uid=None, email=None, api_key="test-key",
            _crash_retries=crash_retries))
        return seen

    return _run, nb, queue_dir, seen


async def _stop_here(_browser, _url, _prefer):
    raise _Reached()


def _checkpoint(queue_dir):
    return json.loads((queue_dir / "checkpoint.json").read_text(encoding="utf-8"))


# ══ 1. a resumed Phase 3 carries on in the notebook it made ═══════════════

@pytest.mark.parametrize("ready, generating", [
    (1, 0),   # the podcast finished while Chrome was down (09-16, 12:57)
    (0, 1),   # the podcast was still being made (09-16, 12:28)
    (0, 0),   # the sources were in, the podcast not started
])
def test_a_resume_goes_back_to_the_notebook_it_made(resumed, ready, generating):
    """⛔⛔ THE OWNER'S CASE. The checkpoint holds the notebook; the resume opens
    it and the podcast step runs on it. No second notebook is made."""
    run, nb, _qd, _seen = resumed
    nb.ready, nb.generating = ready, generating
    seen = run(_stop_here)

    assert seen["audio"], "the run never reached the podcast step"
    assert seen["created"] == 0, "a resumed run made a second notebook"
    step = seen["audio"][0]
    assert step["url"] == NB_URL, "the podcast step was pointed at another notebook"
    assert research._nlm_notebook_id(step["tab"]) == NB_ID, (
        "the podcast step did not start on the notebook's own page")
    assert seen["shared"] == 0, (
        "the notebook's share step ran again — it was shared when it was made")


@pytest.mark.parametrize("ready, generating", [(1, 0), (0, 1)])
def test_a_notebook_whose_sources_are_not_showing_but_has_a_podcast_is_kept(
        resumed, ready, generating):
    """The podcast is what the resume came back for. A sources panel that has
    not drawn yet does not throw away a podcast that is there."""
    run, nb, _qd, _seen = resumed
    nb.sources = set()
    nb.ready, nb.generating = ready, generating
    seen = run(_stop_here)

    assert seen["created"] == 0
    assert seen["audio"] and seen["audio"][0]["url"] == NB_URL


def test_a_podcast_still_being_made_is_waited_on_not_made_again(resumed, monkeypatch):
    """⭐⭐ THE FIRST 09-16 CRASH, END TO END (Chrome died 18 minutes into a
    podcast). The resume goes back to the notebook, sees the podcast still being
    made, never clicks Generate, waits for it and downloads it.

    ⛔ NOT the retry mode. `prefer_existing_audio=True` — which the audit
    proposed for the resume — refuses outright when no podcast is FINISHED yet,
    so it would have given up on exactly this one."""
    run, nb, queue_dir, _seen = resumed
    nb.generating = 1

    async def _generating_text(page):
        return nb.generating > 0 and _on_the_notebook(page)
    monkeypatch.setattr(research, "_check_audio_generating", _generating_text)
    seen = run(None)

    assert seen["created"] == 0
    assert "audio-generate" not in seen["hotspots"], (
        "Generate was clicked while this research's podcast was still being made")
    assert seen["downloads"] == ["saved"]
    assert [a["url"] for a in seen["audio"]] == [NB_URL]
    assert list((queue_dir / "podcasts").glob("*.m4a"))


def test_a_notebook_missing_one_source_is_still_carried_on_in(resumed):
    run, nb, _qd, _seen = resumed
    nb.sources = {"chatgpt.md"}
    seen = run(_stop_here)

    assert seen["created"] == 0 and seen["audio"][0]["url"] == NB_URL
    assert any("not showing: gemini.md" in ln for ln in seen["lines"]), (
        "the missing source was not named")


def test_a_sign_in_page_is_not_a_gone_notebook(resumed):
    """⛔ Signed out, NotebookLM sends the tab to Google's sign-in page. That is
    a person who has to sign in, not a notebook that is gone — the podcast step
    pauses for the sign-in on the notebook's own address."""
    run, nb, _qd, _seen = resumed
    nb.signed_in = False
    seen = run(_stop_here)

    assert seen["created"] == 0, "a sign-in page made a new notebook"
    assert seen["audio"] and seen["audio"][0]["url"] == NB_URL


# ══ 2. …and makes a new one only when the old one is not there ════════════

def _reopened_tab(browser):
    """The tab the resume opened for the recorded notebook."""
    return next((p for p in browser.pages if p.asked_for == NB_URL), None)


def test_a_notebook_that_is_gone_is_replaced(resumed):
    """⭐ ACCEPT POLARITY. NotebookLM no longer opens the recorded notebook. The
    tab that went looking for it is closed, so the new notebook's is the only
    NotebookLM tab left."""
    run, nb, _qd, _seen = resumed
    nb.exists = False
    seen = run(_stop_here)

    assert seen["created"] == 1, "no new notebook for a notebook that is gone"
    assert seen["audio"] and seen["audio"][0]["url"] == NEW_NB_URL
    tab = _reopened_tab(_FakeBrowser.instances[0])
    assert tab is not None and tab.url == HOME_URL and tab.closed


def test_a_notebook_with_nothing_of_this_research_is_replaced(resumed):
    run, nb, _qd, _seen = resumed
    nb.sources = set()
    seen = run(_stop_here)

    assert seen["created"] == 1
    assert seen["audio"] and seen["audio"][0]["url"] == NEW_NB_URL
    tab = _reopened_tab(_FakeBrowser.instances[0])
    assert tab is not None and tab.url == NB_URL and tab.closed


def test_another_researchs_notebook_is_not_carried_on_in(resumed):
    """⛔ Every research uploads the same file names — chatgpt.md, gemini.md —
    so a tab that landed on ANOTHER research's notebook shows "our" sources and
    a podcast. Only the notebook this research made is carried on in."""
    run, nb, _qd, _seen = resumed
    nb.exists = False
    nb.gone_to = OTHER_NB_URL
    nb.other = _Notebook()
    nb.other.ready = 1
    seen = run(_stop_here)

    assert seen["created"] == 1, "the podcast step was sent into another research's notebook"
    assert seen["audio"] and seen["audio"][0]["url"] == NEW_NB_URL


def test_a_recorded_address_that_is_not_a_notebook_is_not_opened(resumed):
    """The checkpoint is read, not trusted: only a NotebookLM notebook address
    is ever opened from it."""
    run, _nb, queue_dir, _seen = resumed
    research.save_checkpoint(queue_dir, 3, topic="Grid storage", brief_url="",
                             notebook_url=HOME_URL)
    seen = run(_stop_here)

    assert HOME_URL not in _FakeBrowser.instances[0].opened
    assert seen["created"] == 1


def test_a_notebook_tab_that_will_not_open_goes_to_the_upload(resumed, monkeypatch):
    """Chrome is alive but the notebook's tab failed to open (a page-load
    timeout). The run goes on to the upload rather than stalling on it."""
    run, _nb, _qd, _seen = resumed
    real_new_tab = _FakeBrowser.new_tab

    async def _times_out(self, url=None):
        if research._nlm_notebook_id(url or "") == NB_ID:
            raise TimeoutError("Page.goto: Timeout 30000ms exceeded")
        return await real_new_tab(self, url)
    monkeypatch.setattr(_FakeBrowser, "new_tab", _times_out)
    seen = run(_stop_here)

    assert seen["created"] == 1
    assert seen["audio"] and seen["audio"][0]["url"] == NEW_NB_URL


def test_a_run_with_no_notebook_recorded_makes_one(resumed):
    """Chrome died during the upload, before a notebook was recorded."""
    run, _nb, queue_dir, _seen = resumed
    research.save_checkpoint(queue_dir, 2, topic="Grid storage", brief_url="")
    seen = run(_stop_here)

    assert seen["created"] == 1
    assert NB_URL not in _FakeBrowser.instances[0].opened, (
        "a run with no recorded notebook went looking for one")


def test_a_prior_skip_of_notebooklm_is_respected(resumed, monkeypatch):
    """A person who skipped NotebookLM earlier in this run is not taken back
    into it by the resume."""
    run, _nb, _qd, _seen = resumed
    real_reset = research._controls.reset

    def _reset_then_skip():
        real_reset()
        research._controls.skipped_agents.add("notebooklm")
    monkeypatch.setattr(research._controls, "reset", _reset_then_skip)
    seen = run(_stop_here)

    assert NB_URL not in _FakeBrowser.instances[0].opened
    assert seen["created"] == 0


def test_chrome_already_gone_at_the_reopen_unwinds_as_a_crash(resumed, monkeypatch):
    """The relaunched Chrome dies again before the notebook opens. That is a
    browser crash — not a notebook to replace, and not a podcast step on a
    browser that is not there."""
    run, _nb, _qd, _seen = resumed
    real_new_tab = _FakeBrowser.new_tab

    async def _dies_on_open(self, url=None):
        if research._nlm_notebook_id(url or "") == NB_ID:
            self.die()
        return await real_new_tab(self, url)
    monkeypatch.setattr(_FakeBrowser, "new_tab", _dies_on_open)
    seen = run(_stop_here)

    assert "browser_crash" in seen["plan"]
    assert seen["created"] == 0 and seen["audio"] == []


def test_the_next_crash_resumes_into_the_same_notebook_again(resumed):
    """The checkpoint written after the resume still names the SAME notebook,
    so a second Chrome death comes back to it too — not to a third one."""
    run, nb, queue_dir, _seen = resumed
    nb.generating = 1
    run(_stop_here)

    assert _checkpoint(queue_dir)["notebook_url"] == NB_URL


# ── …and only on the worker that made it (w13 integrated review, 09-29) ──

def _recorded_on(monkeypatch, queue_dir, worker):
    """The first attempt recorded its notebook on `worker` (None: a checkpoint
    that does not say which)."""
    if worker is None:
        cp = _checkpoint(queue_dir)
        cp.pop("notebook_worker", None)
        (queue_dir / "checkpoint.json").write_text(json.dumps(cp), encoding="utf-8")
        return
    monkeypatch.setattr(research, "WORKER_ID", worker)
    research.save_checkpoint(queue_dir, 3, topic="Grid storage", brief_url="",
                             notebook_url=NB_URL)


@pytest.mark.parametrize("made_on, resumed_on", [(2, 1), (1, 2), (None, 1)],
                         ids=["worker-2-then-1", "worker-1-then-2", "worker-not-recorded"])
def test_a_notebook_another_worker_made_is_not_carried_on_in(
        resumed, monkeypatch, made_on, resumed_on):
    """⛔⛔ A MOVE ALWAYS RESUMES THE RUN ON ANOTHER WORKER — another Chrome
    profile, and maybe another Google account. The notebook was made public
    before it was recorded, so there it opens view-only and passes the reopen's
    checks; the podcast step then ran in a notebook this account may not be
    able to use. A new notebook is made instead, as before wave 13, and the
    checkpoint then names it and this worker."""
    run, nb, queue_dir, _seen = resumed
    nb.ready = 1
    _recorded_on(monkeypatch, queue_dir, made_on)
    monkeypatch.setattr(research, "WORKER_ID", resumed_on)
    seen = run(_stop_here)

    assert NB_URL not in _FakeBrowser.instances[0].opened, (
        "another worker's notebook was opened on this worker's profile")
    assert seen["created"] == 1
    assert seen["audio"] and seen["audio"][0]["url"] == NEW_NB_URL
    cp = _checkpoint(queue_dir)
    assert (cp["notebook_url"], cp["notebook_worker"]) == (NEW_NB_URL, resumed_on)


def test_the_worker_that_made_the_notebook_carries_on_in_it(resumed, monkeypatch):
    """The control: a crash relaunch on the same worker — the same profile —
    goes back to its notebook, whichever worker that is."""
    run, nb, queue_dir, _seen = resumed
    nb.ready = 1
    _recorded_on(monkeypatch, queue_dir, 2)
    seen = run(_stop_here)

    assert seen["created"] == 0
    assert seen["audio"] and seen["audio"][0]["url"] == NB_URL
    assert _checkpoint(queue_dir)["notebook_worker"] == 2


# ══ 3. a dead browser is never "retried" on ═══════════════════════════════

def test_chrome_dying_under_the_download_is_not_retried_on_the_dead_browser(resumed):
    """⛔⛔ THE SECOND FINDING, EXECUTED. Chrome dies two seconds after the
    Download click (09-16 13:35:58). The run must unwind as a browser crash at
    once — not show "Couldn't save the audio file", not wait five minutes, and
    not retry three times on a browser that is gone."""
    run, nb, _qd, _seen = resumed
    nb.ready = 1
    nb.downloads = ["chrome died"]
    seen = run(None)

    assert seen["downloads"] == ["chrome died"]
    assert "browser_crash" in seen["plan"], "the dead browser was not treated as a crash"
    assert 300 not in seen["waits"], "the run waited five minutes on a dead browser"
    assert len(seen["audio"]) == 1, (
        f"the podcast step was retried {len(seen['audio']) - 1} time(s) on a dead browser")
    assert "Couldn't save the audio file" not in seen["cards"], (
        "a dead browser was reported as a failed download, with a Retry that cannot work")


def test_after_the_relaunch_the_finished_podcast_is_downloaded_from_the_same_notebook(
        resumed, monkeypatch):
    """⭐⭐ THE WHOLE 09-16 SEQUENCE, END TO END. Resumed with the podcast
    finished in the recorded notebook; Chrome dies under the download; the run
    relaunches Chrome (the real retry plan), resumes, goes back to the same
    notebook and downloads the podcast. One notebook, one podcast, delivered."""
    run, nb, queue_dir, seen = resumed
    nb.ready = 1
    nb.downloads = ["chrome died", "saved"]

    def _real_plan(qd, rd, kind, crash_retries):
        seen["plan"].append(kind)
        return _REAL_PLAN(qd, rd, kind, crash_retries)
    monkeypatch.setattr(research, "_plan_pipeline_auto_retry", _real_plan)
    run(None)

    assert len(_FakeBrowser.instances) == 2, "Chrome was not relaunched"
    assert seen["created"] == 0, "a notebook was made on the way"
    assert seen["downloads"] == ["chrome died", "saved"]
    assert [a["url"] for a in seen["audio"]] == [NB_URL, NB_URL]
    podcasts = list((queue_dir / "podcasts").glob("*.m4a"))
    assert podcasts and seen["published"][-1] == podcasts[0]
    assert _checkpoint(queue_dir).get("audio_path") == str(podcasts[0])


def test_a_retry_that_finds_chrome_gone_unwinds_before_the_next_wait(resumed):
    """The podcast step came back empty on a LIVE browser; its retry then met a
    dead one. The loop must ask before its next five-minute wait."""
    run, _nb, _qd, _seen = resumed

    async def _audio(browser, _url, prefer):
        if not prefer:
            return {"audio_path": None, "audio_stored_url": ""}
        browser.die()
        raise _Closed("BrowserContext.new_page")
    seen = run(_audio)

    assert len(seen["audio"]) == 2, (
        f"{len(seen['audio']) - 2} more retries ran on a dead browser")
    assert seen["waits"] == [300]
    assert "browser_crash" in seen["plan"]


def test_chrome_dying_on_the_last_retry_is_a_crash_not_a_give_up(resumed):
    """Two retries find no file on a live browser; the third meets a dead one.
    With the budget spent, the loop's next stop was "continue with the notebook
    link only" — the run ended without a podcast that was sitting finished in
    the notebook. The browser is asked BEFORE the loop gives up."""
    run, _nb, _qd, seen = resumed

    async def _audio(browser, _url, _prefer):
        if len(seen["audio"]) < 4:
            return {"audio_path": None, "audio_stored_url": ""}
        browser.die()
        raise _Closed("BrowserContext.new_page")
    run(_audio)

    assert len(seen["audio"]) == 4 and seen["waits"] == [300, 300, 300]
    assert "browser_crash" in seen["plan"], (
        "the run gave up on the podcast instead of relaunching Chrome")


def test_a_live_browser_still_gets_its_download_retries(resumed):
    """⭐ ACCEPT POLARITY. A podcast that did not download on a LIVE browser is
    retried exactly as before: five minutes later, adopting the finished one."""
    run, _nb, queue_dir, _seen = resumed
    podcast = queue_dir / "podcasts" / "State.m4a"

    async def _audio(_browser, _url, prefer):
        if not prefer:
            return {"audio_path": None, "audio_stored_url": ""}
        podcast.parent.mkdir(exist_ok=True)
        podcast.write_bytes(b"podcast")
        return {"audio_path": podcast, "audio_stored_url": "https://storage.example/p.m4a"}
    seen = run(_audio)

    assert [a["prefer_existing_audio"] for a in seen["audio"]] == [False, True]
    assert seen["waits"] == [300]
    assert "browser_crash" not in seen["plan"]
    assert _checkpoint(queue_dir).get("audio_path") == str(podcast)


def test_a_live_browser_whose_download_failed_still_gets_the_card(resumed):
    """⭐ ACCEPT POLARITY for the download site: Chrome is alive, the file just
    did not arrive — the honest "Couldn't save the audio file" card stays."""
    run, nb, queue_dir, _seen = resumed
    nb.ready = 1
    nb.downloads = ["no file", "saved"]
    seen = run(None)

    assert seen["downloads"] == ["no file", "saved"]
    assert "Couldn't save the audio file" in seen["cards"]
    assert "browser_crash" not in seen["plan"]
    # …and the ordinary retry, five minutes on, adopts and downloads it.
    assert [a["prefer_existing_audio"] for a in seen["audio"]] == [False, True]
    assert seen["waits"].count(300) == 1
    assert list((queue_dir / "podcasts").glob("*.m4a"))


def test_the_login_command_pauses_the_run_instead_of_relaunching(resumed, monkeypatch):
    """The login command closes Chrome on purpose. That pauses the run at its
    checkpoint — relaunching would fight the sign-in for the same profile."""
    run, _nb, _qd, _seen = resumed

    async def _audio(browser, _url, _prefer):
        browser.die()
        monkeypatch.setattr(research, "_login_interrupt_active", lambda: True)
        return {"audio_path": None, "audio_stored_url": ""}
    seen = run(_audio)

    assert "login_interrupt" in seen["plan"]
    assert "browser_crash" not in seen["plan"]
    assert len(seen["audio"]) == 1 and 300 not in seen["waits"]


# ══ 4. …until the relaunches are spent: then the report goes out without it ═

def _recorded_real_plan(seen):
    def _plan(qd, rd, kind, crash_retries):
        seen["plan"].append(kind)
        return _REAL_PLAN(qd, rd, kind, crash_retries)
    return _plan


def _watch_the_hand_off(monkeypatch):
    """Record the hand-off to the Doc and email step, and every event."""
    handed_off, events = [], []
    monkeypatch.setattr(research, "_post_fe_p4p5_trigger",
                        lambda *a, **k: handed_off.append(a))
    monkeypatch.setattr(research, "emit_event",
                        lambda event_type, phase=None, agent=None, **data:
                        events.append((event_type, phase, data)))
    return handed_off, events


@pytest.mark.parametrize("crash_retries", [
    0,   # every Chrome launch of this research dies under its download
    1,   # 09-16: a mid-poll crash had already spent one relaunch
    2,   # every relaunch already spent: the first death ends the podcast step
])
def test_chrome_dying_under_every_download_still_delivers_the_report(
        resumed, monkeypatch, crash_retries):
    """⛔⛔ CROSS-VERIFY'S FINDING, EXECUTED. Chrome dies under EVERY download
    click. Each death relaunches Chrome into the same notebook while the crash
    budget lasts. Once it is spent the run ends as it did before wave 13 — the
    report and the notebook link handed off without the podcast — and NOT on
    "Research stopped: Chrome kept closing" with nothing delivered and
    delivery.json left "ongoing". It ends there at once, too: no five-minute
    retries on a browser that is gone."""
    run, nb, queue_dir, seen = resumed
    nb.ready = 1
    nb.downloads = ["chrome died"] * 6
    handed_off, events = _watch_the_hand_off(monkeypatch)
    monkeypatch.setattr(research, "_plan_pipeline_auto_retry", _recorded_real_plan(seen))
    run(None, crash_retries=crash_retries)

    launches = research.BROWSER_CRASH_MAX_RETRIES + 1 - crash_retries
    assert len(_FakeBrowser.instances) == launches, (
        "Chrome was not reopened exactly while the relaunches lasted")
    assert seen["downloads"] == ["chrome died"] * launches
    assert [a["url"] for a in seen["audio"]] == [NB_URL] * launches
    assert seen["created"] == 0
    assert not [c for c in seen["cards"] if str(c).startswith("Research stopped")], (
        f"the run ended on a crash card with nothing delivered: {seen['cards']}")
    assert "Couldn't save the audio file" not in seen["cards"]
    assert handed_off, "the report was never handed off to the Doc and email step"
    delivery = json.loads((queue_dir / "delivery.json").read_text(encoding="utf-8"))
    assert delivery["status"] == "completed"
    skipped = [d for kind, phase, d in events if kind == "phase_skipped" and phase == 3]
    assert [d["reason"] for d in skipped] == ["audio_unavailable_after_auto_retries"]
    assert [link["url"] for link in skipped[0]["links"]] == [NB_URL], (
        "the notebook link did not go out with the report")
    assert 300 not in seen["waits"], (
        "the run waited five minutes to retry on a browser that is gone")
    assert any("not reopened for the podcast" in ln for ln in seen["lines"])


def test_the_login_command_still_pauses_the_run_once_the_relaunches_are_spent(
        resumed, monkeypatch):
    """The relaunch budget is for Chrome CRASHES. The login command closing
    Chrome is not one and never relaunched anything: it still pauses the run
    at its checkpoint, so after the sign-in a Retry comes back for the podcast
    — the run is not ended without it."""
    run, _nb, _qd, _seen = resumed
    handed_off, _events = _watch_the_hand_off(monkeypatch)

    async def _audio(browser, _url, _prefer):
        browser.die()
        monkeypatch.setattr(research, "_login_interrupt_active", lambda: True)
        return {"audio_path": None, "audio_stored_url": ""}
    seen = run(_audio, crash_retries=research.BROWSER_CRASH_MAX_RETRIES)

    assert "login_interrupt" in seen["plan"]
    assert not handed_off, "the run was ended without the podcast during a sign-in"


# ══ 5. a resume past Phase 1 writes the brief to the app again ══════════════
#
# ⛔⛔ THE w13 INTEGRATED REVIEW (09-29). Phase 1 ends in two halves: brief.md
# and the checkpoint on disk, then the brief document, the "Read Brief report"
# link and Phase 1's "complete" in Firestore. A Move to queue cuts the run's
# Firestore writes off and keeps the pipeline running for its exit window, so a
# brief that arrived in that window reached the disk and nothing else — and the
# resume trusts the disk: it starts at Phase 2 and never wrote the brief again.
# A crash between the two halves leaves the same gap.

def _phase1_writes(monkeypatch):
    """Phase 1's Firestore half, as the real writers are asked for it."""
    w = {"documents": [], "record": [], "phases": [], "slot": []}
    monkeypatch.setattr(research, "save_document_to_firestore",
                        lambda kind, content, name=None:
                        w["documents"].append((kind, content, name)) or True)
    monkeypatch.setattr(research, "_update_firestore_research",
                        lambda updates: w["record"].append(dict(updates)))
    monkeypatch.setattr(research, "_write_phase_terminal_status",
                        lambda phase, status: w["phases"].append((phase, status)))
    monkeypatch.setattr(research, "_record_brief_in_aggregate",
                        lambda url: w["slot"].append(url))
    return w


def _stop_at_phase_2(monkeypatch):
    """End the run where Phase 2 starts: this is about what came before it."""
    def _emit(event_type, phase=None, agent=None, **data):
        if event_type == "phase_start" and phase == 2:
            raise _Reached()
    monkeypatch.setattr(research, "emit_event", _emit)


@pytest.mark.parametrize("start", [2, 3], ids=["resumed-at-phase-2", "resumed-at-phase-3"])
def test_a_resume_past_phase_1_writes_the_brief_to_the_app_again(
        resumed, monkeypatch, start):
    run, _nb, queue_dir, _seen = resumed
    monkeypatch.setattr(research, "_fb_research_id", "chat_1759200000000_brief")
    if start == 2:
        (queue_dir / "links.json").unlink()
        _stop_at_phase_2(monkeypatch)
    assert research.detect_resume_phase(queue_dir)[0] == start, "precondition"
    w = _phase1_writes(monkeypatch)
    run(_stop_here)

    brief_md = (queue_dir / "documents" / "brief.md").read_text(encoding="utf-8")
    page = "/documents?open=chat_1759200000000_brief:brief"
    assert w["documents"].count(("brief", brief_md, "Research Brief")) == 1, (
        "the brief document was not written again from brief.md")
    assert {"links.phase1": [{"label": "Read Brief report", "url": page,
                              "verified": True, "primary": True}]} in w["record"], (
        "no Read Brief report link on the resumed run")
    assert (1, "complete") in w["phases"], "Phase 1 never marked complete"
    assert w["slot"] == [page], "the record's brief slot was not filled"


@pytest.mark.parametrize("brief", ["missing", "empty"])
def test_a_resume_with_no_brief_on_disk_writes_no_brief(resumed, monkeypatch, brief):
    """The control: Phase 1 made no brief (skipped after an error), so there is
    nothing to write again — and Phase 1 is not called complete."""
    run, _nb, queue_dir, _seen = resumed
    if brief == "missing":
        (queue_dir / "documents" / "brief.md").unlink()
    else:
        (queue_dir / "documents" / "brief.md").write_text("", encoding="utf-8")
    w = _phase1_writes(monkeypatch)
    run(_stop_here)

    assert not [d for d in w["documents"] if d[0] == "brief"]
    assert (1, "complete") not in w["phases"]
    assert not [u for u in w["record"] if "links.phase1" in u]


# ══ 6. a resume past Phase 3 publishes the podcast on disk again ════════════
#
# ⛔⛔ THE w13 INTEGRATED REVIEW, SECOND ROUND (09-30) — Phase 1's gap has a
# Phase 3 twin. The podcast lands in podcasts/, then `_p3_publish_audio` uploads
# it and writes the `audios` row and `links.audio_file`. A Move to queue cuts
# the run's record off and gives an upload in flight five seconds: the upload
# is cut off, or it finishes and its two writes are skipped. The resume trusted
# the disk — "Phase 3 done" — and never published it: no Podcasts entry, no
# Play in the chat, no "Podcast ready", and the cloud's video step found no
# podcast. A crash between the download and the publish left the same gap.

RID = "chat_1759200000000_p3end"
UID = "sharer-uid"
STORED = "https://firebasestorage.example/podcast.mp3"


def _the_real_publish(monkeypatch, *, upload_ok=True):
    """The REAL `_p3_publish_audio`. Its upload answers the URL (even with the
    record cut off: the upload read the record when it began), and its two
    writes land under the record the globals name when each is made — a write
    made with them unset is dropped, as both real writers drop it."""
    w = {"uploaded": [], "rows": [], "links": []}
    monkeypatch.setattr(research, "_p3_publish_audio", _REAL_P3_PUBLISH)

    def _upload(path):
        w["uploaded"].append(path.name)
        return STORED if upload_ok else None
    monkeypatch.setattr(research, "upload_audio_to_storage", _upload)

    def _landed(key, *row):
        if research._fb_uid and research._fb_research_id:
            w[key].append((*row, research._fb_uid, research._fb_research_id))
    monkeypatch.setattr(research, "save_audio_to_firestore",
                        lambda audio_id, _name, _dur, url: _landed("rows", audio_id, url))
    monkeypatch.setattr(research, "update_link_in_firestore",
                        lambda kind, url, **_f: _landed("links", kind, url)
                        if kind == "audio_file" else None)
    monkeypatch.setattr(research, "_audio_duration_sec", lambda _p: 600)
    monkeypatch.setattr(research, "smart_title", lambda s: s)
    return w


def _watch_in_order(monkeypatch):
    """Every event and the hand-off's kick, in the order they happened."""
    seen = []
    monkeypatch.setattr(research, "emit_event",
                        lambda event_type, phase=None, agent=None, **data:
                        seen.append((event_type, phase, data)))
    monkeypatch.setattr(research, "_post_fe_p4p5_trigger",
                        lambda uid, rid: seen.append(("hand-off", uid, rid)))
    return seen


def _published(w):
    """The run's podcast reached the app, under this research."""
    return (w["rows"] and all(r[1:] == (STORED, UID, RID) for r in w["rows"])
            and ("audio_file", STORED, UID, RID) in w["links"])


def _podcast(queue_dir, name="Grid_storage.m4a", body=b"\x00" * 4096):
    pod = queue_dir / "podcasts"
    pod.mkdir(exist_ok=True)
    (pod / name).write_bytes(body)
    return pod / name


@pytest.mark.parametrize("where", ["checkpoint", "folder"],
                         ids=["named-by-the-checkpoint", "in-the-folder-only"])
def test_a_resume_past_phase_3_publishes_the_podcast_on_disk_again(
        resumed, monkeypatch, where):
    """The owner's case is `in-the-folder-only`: the move cut the upload off,
    so the checkpoint never named the file. `named-by-the-checkpoint` is a crash
    after a publish whose writes the move skipped."""
    run, _nb, queue_dir, _seen = resumed
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_fb_research_id", RID)
    audio = _podcast(queue_dir, "Grid_storage.mp3")
    if where == "checkpoint":
        research.save_checkpoint(queue_dir, 3, topic="Grid storage", brief_url="",
                                 notebook_url=NB_URL, audio_path=str(audio))
    assert research.detect_resume_phase(queue_dir)[0] == 4, "precondition"
    w = _the_real_publish(monkeypatch)
    order = _watch_in_order(monkeypatch)
    run(_stop_here)

    assert w["uploaded"] == ["Grid_storage.mp3"], "the podcast on disk was not uploaded"
    assert _published(w), f"the podcast never reached the app: {w}"
    kinds = [(e[0], e[1]) for e in order]
    assert ("phase_complete", 3) in kinds, "Phase 3 was never completed on the podcast"
    assert ("hand-off", UID, RID) in order, "the run was not handed off"
    assert kinds.index(("phase_complete", 3)) < order.index(("hand-off", UID, RID)), (
        "the podcast was published after the hand-off")


def test_a_transcode_cut_off_is_finished_before_the_podcast_is_published(
        resumed, monkeypatch):
    """The mp3 transcode deletes its original only once it finished, so an
    original beside an mp3 is a transcode that did not — and that mp3 may be
    half written. The original is transcoded again and the result published."""
    run, _nb, queue_dir, _seen = resumed
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_fb_research_id", RID)
    original = _podcast(queue_dir, "Grid_storage.m4a")
    half = _podcast(queue_dir, "Grid_storage.mp3", b"\x00" * 16)
    asked = []

    def _transcode(src):
        asked.append(src.name)
        if src.suffix == ".mp3":
            return src
        half.write_bytes(b"\x00" * 4096)
        src.unlink()
        return half
    monkeypatch.setattr(research, "_transcode_audio_to_mp3", _transcode)
    w = _the_real_publish(monkeypatch)
    _watch_in_order(monkeypatch)
    run(_stop_here)

    assert asked == [original.name], "the unfinished transcode was not run again"
    assert w["uploaded"] == ["Grid_storage.mp3"]
    assert _published(w)


def test_a_podcast_that_does_not_reach_the_app_completes_nothing(resumed, monkeypatch):
    """The control: the upload fails, so there is no podcast in the app — and
    no Phase 3 "complete" or "Podcast ready" for one. The run is handed off
    without it, as before."""
    run, _nb, queue_dir, _seen = resumed
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_fb_research_id", RID)
    _podcast(queue_dir, "Grid_storage.mp3")
    w = _the_real_publish(monkeypatch, upload_ok=False)
    order = _watch_in_order(monkeypatch)
    run(_stop_here)

    assert w["uploaded"] == ["Grid_storage.mp3"]
    assert not w["rows"] or all(r[1] is None for r in w["rows"])
    assert not [e for e in order if e[:2] == ("phase_complete", 3)]
    assert ("hand-off", UID, RID) in order


def test_a_stray_file_in_the_podcast_folder_is_not_published(resumed, monkeypatch):
    """The control: `detect_resume_phase` reads any file in podcasts/ as Phase 3
    done. A file that is not a podcast is not uploaded as one."""
    run, _nb, queue_dir, _seen = resumed
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_fb_research_id", RID)
    _podcast(queue_dir, "notes.txt", b"not a podcast")
    assert research.detect_resume_phase(queue_dir)[0] == 4, "precondition"
    w = _the_real_publish(monkeypatch)
    order = _watch_in_order(monkeypatch)
    run(_stop_here)

    assert w["uploaded"] == [] and not w["rows"] and not w["links"]
    assert not [e for e in order if e[:2] == ("phase_complete", 3)]
    assert ("hand-off", UID, RID) in order


def test_a_run_moved_as_its_podcast_upload_finishes_is_published_by_the_next_worker(
        resumed, monkeypatch):
    """⛔⛔ END TO END. The move lands during the podcast upload, and the upload
    finishes inside the move's five-second wait: its two writes are skipped,
    because the move cut the record off, and the pipeline runs on to the
    hand-off in its last second. The hand-off used to be written to disk there,
    so the worker that took the run read "handed off" and only re-sent the
    kick: the podcast never reached the app. Now the moved run hands nothing
    off, and the worker that takes it publishes the podcast and hands it off."""
    run, nb, queue_dir, _seen = resumed
    nb.ready = 1
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_fb_research_id", RID)
    w = _the_real_publish(monkeypatch)
    order = _watch_in_order(monkeypatch)

    async def _moved_during_the_upload(_browser, _url, _prefer):
        audio = _podcast(queue_dir, "Grid_storage.mp3")
        # `_handle_requeue_command`, on the device-command thread meanwhile:
        # the run's marker goes into its folder, then the record is cut off.
        assert research._park_waiting_run(
            {"resume_dir": str(queue_dir), "uid": UID, "research_id": RID,
             "topic": "Grid storage"}, from_worker=1) == queue_dir
        research._fb_uid = None
        research._fb_research_id = None
        stored = await research._p3_publish_audio(audio, RID)
        return {"audio_path": audio, "audio_stored_url": stored}
    run(_moved_during_the_upload)

    assert w["uploaded"] == ["Grid_storage.mp3"] and not w["rows"] and not w["links"], (
        "precondition: the move's cut-off skipped the podcast's writes")
    assert not [e for e in order if e[0] == "hand-off"], "the moved run handed off"
    assert not research._handed_off_to_cloud(queue_dir), (
        "the moved run wrote its hand-off to disk — the next worker would only "
        "re-send the kick")
    assert research.detect_resume_phase(queue_dir)[0] == 4

    # The next worker takes it: the marker goes, the record is this run's again.
    (queue_dir / research.WAITING_MARKER).unlink()
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_fb_research_id", RID)
    del order[:]
    run(_stop_here)

    assert _published(w), f"the podcast never reached the app: {w}"
    assert ("hand-off", UID, RID) in order
