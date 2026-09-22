"""A hung Chrome is a dead Chrome: the run unwinds and relaunches instead of
freezing — and one closed NotebookLM tab is not a dead Chrome.

⛔⛔ THE DEFECT (wave 10.9, M12). `_browser_context_is_dead` asked the context
`await ctx.cookies()` with no bound, and the driver gives that call no timeout
of its own (`BrowserContext.cookies` → `_channel.send("cookies", None, …)`: no
timeout calculator). A HUNG Chrome — process alive, CDP silent — parked the
probe for ever at every call site, and the notebook park sits outside any phase
ceiling. No card, no relaunch, nothing in the log after the last line.

⛔⛔ AND THE UNWIND HAD THE SAME HOLE ONE STEP LATER. The probe answering True
sends the run to `run_pipeline`'s finally, which calls `Browser.close()` → the
driver sends Chrome `Browser.close` and waits, again with no timeout, for the
process to exit (`gracefullyClose` → `await waitForCleanup`). A hung Chrome
never exits. And `Browser.start()`'s orphan sweep would not have saved it on the
relaunch either: it spares every Chrome younger than the --serve process, which
the hung one is. So the close is bounded too, and its timeout lands in the
existing kill-our-profile fallback.

⭐ M8, THE SAME PROBE AT THE ONE SITE THAT JUDGED BY TEXT. The phase-3 upload
handler read "Target page, context or browser has been closed" and relaunched
Chrome — a crash-budget unit — when only the NotebookLM tab had gone. It now
asks the context first: dead or hung → unwind as before; alive → a fresh tab,
silently, while an attempt is left; the last attempt still reaches the card.

EVERY TEST HERE EXECUTES. The hang is a real never-set Event, every call sits
inside an outer `asyncio.wait_for`, and against the code before this wave the
hang cases time out rather than fail an assertion.
"""
from __future__ import annotations

import asyncio

import pytest

import research


CLOSED = "BrowserContext.cookies: Target page, context or browser has been closed"
TAB_CLOSED = "Page.goto: Target page, context or browser has been closed"
OUTER = 2.0  # the bound every hang case must beat; the patched probe is 0.05


class _Ctx:
    """A BrowserContext stand-in. mode: 'alive' | 'dead' | 'hung' | 'slow'."""

    def __init__(self, mode="alive", exc=None, delay=0.0):
        self.mode, self.exc, self.delay = mode, exc, delay
        self.asked = 0
        self.cancelled = False
        self.never = asyncio.Event()

    async def cookies(self):
        self.asked += 1
        if self.mode == "dead":
            raise (self.exc or Exception(CLOSED))
        if self.mode == "hung":
            try:
                await self.never.wait()  # nobody ever sets it
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.mode == "slow":
            await asyncio.sleep(self.delay)
        return []


class _Browser:
    def __init__(self, ctx):
        self.context = ctx


def _run_bounded(coro):
    """Run `coro` under an outer bound. A TimeoutError HERE is the freeze."""
    async def _go():
        return await asyncio.wait_for(coro, OUTER)
    return asyncio.run(_go())


@pytest.fixture
def short_probe(monkeypatch):
    monkeypatch.setattr(research, "_CTX_PROBE_TIMEOUT_SEC", 0.05)


@pytest.fixture
def logs(monkeypatch):
    seen = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO": seen.append((level, msg)))
    return seen


# ── M12: the probe is bounded, and a hang answers DEAD ─────────────────────

def test_a_hung_context_answers_dead_inside_the_bound(short_probe, logs):
    """⛔⛔ THE DEFECT. Before this wave the outer wait timed out here."""
    ctx = _Ctx("hung")
    assert _run_bounded(research._browser_context_is_dead(_Browser(ctx))) is True
    assert ctx.asked == 1


def test_the_hung_probe_is_cancelled_not_leaked(short_probe, logs):
    """The bound must CANCEL the stuck call, not walk away from it — a leaked
    probe per audio-poll cycle is a task pile-up on a browser that is hung."""
    ctx = _Ctx("hung")
    _run_bounded(research._browser_context_is_dead(_Browser(ctx)))
    assert ctx.cancelled is True


def test_a_hang_says_so_at_WARN(short_probe, logs):
    """The one line that explains why a healthy-looking run relaunched Chrome."""
    _run_bounded(research._browser_context_is_dead(_Browser(_Ctx("hung"))))
    warns = [m for lvl, m in logs if lvl == "WARN"]
    assert any("hung" in m and "cookie" in m for m in warns), logs


def test_an_answer_inside_the_bound_is_still_alive(monkeypatch, logs):
    """⭐ ACCEPT POLARITY. "Every probe answers dead" must not pass this file:
    a context that answers slowly but inside the bound is alive."""
    monkeypatch.setattr(research, "_CTX_PROBE_TIMEOUT_SEC", 1.0)
    ctx = _Ctx("slow", delay=0.05)
    assert _run_bounded(research._browser_context_is_dead(_Browser(ctx))) is False
    assert not [m for lvl, m in logs if lvl == "WARN"], "no hang happened"


@pytest.mark.parametrize("ctx, want", [
    (lambda: _Ctx("alive"), False),
    (lambda: _Ctx("dead"), True),
    (lambda: _Ctx("dead", exc=Exception("net::ERR_INTERNET_DISCONNECTED")), False),
    (lambda: _Ctx("dead", exc=Exception("")), False),
])
def test_fast_answers_are_unchanged_by_the_bound(short_probe, logs, ctx, want):
    """Fast return → alive; fast close error → dead; fast unrelated error →
    alive (the fail-safe the docstring promises for what it cannot read)."""
    assert _run_bounded(research._browser_context_is_dead(_Browser(ctx()))) is want


def test_the_real_bound_lets_a_live_context_answer(logs):
    """Unpatched constant: a zero or negative bound would time out every probe,
    so every healthy run would relaunch at its first probe."""
    assert _run_bounded(research._browser_context_is_dead(_Browser(_Ctx("alive")))) is False


def test_the_default_bound_is_short_enough_to_matter():
    """A probe bounded at an hour is a freeze with extra steps; one bounded
    below a second would call a busy Chrome dead."""
    assert 1.0 <= research._CTX_PROBE_TIMEOUT_SEC <= 30.0


# ── M12, second half: the unwind's close cannot freeze either ──────────────

class _HungCloseCtx:
    def __init__(self):
        self.never = asyncio.Event()
        self.closed = False

    async def close(self):
        await self.never.wait()


class _QuickCloseCtx:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _Pw:
    def __init__(self):
        self.stopped = False

    async def stop(self):
        self.stopped = True


class _Proc:
    def __init__(self, name, cmdline):
        self.info = {"pid": 4242, "name": name, "cmdline": cmdline}
        self.killed = False

    def kill(self):
        self.killed = True


def _browser_with(tmp_path, ctx, monkeypatch):
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    b = research.Browser(str(profile))
    b.context, b.playwright = ctx, _Pw()
    ours = _Proc("Google Chrome", ["/Applications/Google Chrome",
                                   f"--user-data-dir={profile.resolve()}"])
    theirs = _Proc("Google Chrome", ["/Applications/Google Chrome",
                                     f"--user-data-dir={tmp_path.resolve()}/browser-profile-2"])
    psutil = pytest.importorskip("psutil")
    monkeypatch.setattr(psutil, "process_iter", lambda *_a, **_k: [ours, theirs])
    return b, ours, theirs


def test_a_hung_close_is_bounded_and_kills_our_chrome(tmp_path, monkeypatch, logs):
    """⛔⛔ THE SECOND FREEZE. Against the code before this wave the outer wait
    times out: the driver waits for a hung Chrome to exit, for ever."""
    monkeypatch.setattr(research, "_BROWSER_CLOSE_TIMEOUT_SEC", 0.05)
    b, ours, theirs = _browser_with(tmp_path, _HungCloseCtx(), monkeypatch)
    _run_bounded(b.close())
    assert ours.killed is True, "nothing else kills it — start()'s sweep spares it"
    assert theirs.killed is False, "another worker's Chrome is not ours to kill"
    assert any(lvl == "WARN" and "TimeoutError" in m for lvl, m in logs), logs


def test_a_healthy_close_kills_nothing(tmp_path, monkeypatch, logs):
    """⭐ ACCEPT POLARITY: a close that finishes is a close, not a kill."""
    monkeypatch.setattr(research, "_BROWSER_CLOSE_TIMEOUT_SEC", 0.5)
    ctx = _QuickCloseCtx()
    b, ours, theirs = _browser_with(tmp_path, ctx, monkeypatch)
    _run_bounded(b.close())
    assert ctx.closed and b.playwright.stopped
    assert ours.killed is False and theirs.killed is False


def test_the_default_close_bound_is_generous_but_finite():
    """Generous because a kill can drop a sign-in Chrome has not flushed
    (#898b); finite because the unwind behind it is the only way out."""
    assert 5.0 <= research._BROWSER_CLOSE_TIMEOUT_SEC <= 120.0


# ── M8: the upload failure asks the context before it reads the text ───────

@pytest.mark.parametrize("ctx, exc, want", [
    (lambda: _Ctx("alive"), Exception(TAB_CLOSED), "tab_closed"),
    (lambda: _Ctx("dead"), Exception(TAB_CLOSED), "browser_dead"),
    (lambda: _Ctx("alive"), Exception("Upload button not found"), "other"),
    # ⭐ The widening, on purpose: a dead browser behind an error that says
    # nothing about closing still unwinds — its Retry card could never work.
    (lambda: _Ctx("dead"), Exception("Timeout 30000ms exceeded"), "browser_dead"),
    (lambda: _Ctx("hung"), Exception("Timeout 30000ms exceeded"), "browser_dead"),
])
def test_the_upload_failure_kind(short_probe, logs, ctx, exc, want):
    got = _run_bounded(research._p3_upload_failure_kind(exc, _Browser(ctx())))
    assert got == want


# ── M8, the consumer: run_phase3_upload executed with fakes ────────────────

class _Page:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _UploadBrowser(_Browser):
    """new_tab raises the next scripted error, or returns a page if None."""

    def __init__(self, ctx, script):
        super().__init__(ctx)
        self.script = list(script)
        self.tabs = []

    async def new_tab(self, url):
        step = self.script.pop(0) if self.script else Exception("script exhausted")
        if isinstance(step, BaseException):
            raise step
        page = _Page()
        self.tabs.append(page)
        return page


@pytest.fixture
def p3(tmp_path, monkeypatch, logs):
    """Everything run_phase3_upload touches before the upload loop, faked."""
    md = tmp_path / "documents" / "claude.md"
    md.parent.mkdir(parents=True)
    md.write_text("x" * 200, encoding="utf-8")
    monkeypatch.setattr(research._runtime, "p2_links_for_p3", {"claude": "https://claude.ai/share/x"})
    monkeypatch.setattr(research._runtime, "p2_md_files_for_p3", [md])
    monkeypatch.setattr(research._runtime, "last_failure_kind", "")
    monkeypatch.setattr(research._controls, "skipped_agents", set())
    cards, decisions = [], []
    monkeypatch.setattr(research, "fail_phase",
                        lambda phase, title="", details="", **kw: cards.append((phase, title, kw)))

    async def _decide(phase, timeout=86400.0):
        decisions.append(phase)
        return "skip"
    monkeypatch.setattr(research._controls, "await_phase_decision", _decide)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)

    def run(browser):
        return _run_bounded(research.run_phase3_upload(browser, None, {}, "topic", tmp_path))
    run.cards, run.decisions = cards, decisions
    return run


def test_a_closed_tab_on_a_live_browser_retries_silently_then_asks(p3):
    """⭐ THE M8 SHAPE. Two silent fresh tabs, then the card on the last
    attempt — never a relaunch, never an unwind, never NotebookLM dropped in
    silence. Before this wave the first close raised a browser crash."""
    b = _UploadBrowser(_Ctx("alive"), [Exception(TAB_CLOSED)] * 3)
    out = p3(b)
    assert out["notebook_url"] == ""
    assert b.script == [], "all three attempts must run — the first two silently"
    assert len(p3.cards) == 1, p3.cards
    phase, title, kw = p3.cards[0]
    assert phase == 3 and title == "NotebookLM upload failed"
    assert kw.get("can_retry") is False, "the last attempt has no retry to offer"
    assert p3.decisions == []
    assert research._runtime.last_failure_kind == ""


def test_the_silent_tab_retry_spends_an_attempt(p3):
    """One silent tab retry, then an ordinary failure: the card offers exactly
    the attempts that are left, so the loop is bounded by one counter."""
    b = _UploadBrowser(_Ctx("alive"), [Exception(TAB_CLOSED), Exception("Upload button not found")])
    p3(b)
    assert len(p3.cards) == 1
    assert p3.cards[0][2].get("can_retry") is True
    assert p3.decisions == [3]


def test_the_closed_tab_is_closed_before_the_fresh_one_opens(p3, monkeypatch):
    """A crashed tab lingers as a sad tab; the retry closes it, the way the
    user-Retry path always has."""
    _real_sleep = asyncio.sleep
    monkeypatch.setattr(research.asyncio, "sleep", lambda *_a, **_k: _real_sleep(0))
    calls = []

    async def _signed_out(page, *_a, **_k):
        calls.append(page)
        raise Exception(TAB_CLOSED)
    monkeypatch.setattr(research, "_work_tab_signed_out", _signed_out)
    b = _UploadBrowser(_Ctx("alive"), [None, Exception("Upload button not found")])
    p3(b)
    assert len(b.tabs) == 1 and calls == b.tabs
    assert b.tabs[0].closed is True


def test_a_dead_browser_still_unwinds_as_a_crash(p3):
    """⛔ The 8D9CWHZJ fix survives: no upload card about a browser that no
    longer exists, and the kind rides on the exception text as well as the flag."""
    b = _UploadBrowser(_Ctx("dead"), [Exception(TAB_CLOSED)])
    with pytest.raises(RuntimeError, match=r"\(browser crash\)") as ei:
        p3(b)
    assert research._is_browser_close_error(ei.value) is True
    assert research._runtime.last_failure_kind == "browser_crash"
    assert p3.cards == [] and p3.decisions == []
    assert b.script == [], "exactly one attempt"


def test_a_dead_browser_behind_an_unrelated_error_unwinds_too(p3):
    """⭐ The widening: before this wave a timeout on a dead Chrome got the
    'Retry to try again' card, and the Retry could never work."""
    b = _UploadBrowser(_Ctx("dead"), [Exception("Timeout 30000ms exceeded")])
    with pytest.raises(RuntimeError, match=r"\(browser crash\)"):
        p3(b)
    assert p3.cards == []


def test_a_hung_browser_at_upload_unwinds_inside_the_bound(p3, short_probe):
    """⛔⛔ M12 through a consumer: the upload handler's probe meets a hung
    Chrome and the run unwinds, rather than the handler freezing on the probe."""
    b = _UploadBrowser(_Ctx("hung"), [Exception("Timeout 30000ms exceeded")])
    with pytest.raises(RuntimeError, match=r"\(browser crash\)"):
        p3(b)
    assert research._runtime.last_failure_kind == "browser_crash"


def test_an_ordinary_failure_on_a_live_browser_still_gets_the_card(p3):
    """⭐ ACCEPT POLARITY for the card: an upload that failed on a healthy
    browser is a question for the person, on the first attempt."""
    b = _UploadBrowser(_Ctx("alive"), [Exception("Upload button not found")])
    p3(b)
    assert len(p3.cards) == 1 and p3.cards[0][2].get("can_retry") is True
    assert p3.decisions == [3]
    assert research._runtime.last_failure_kind == ""
