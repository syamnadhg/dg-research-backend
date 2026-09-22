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
        self.attempts = 0

    async def close(self):
        self.attempts += 1
        await self.never.wait()


class _QuickCloseCtx:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _Pw:
    """The node driver handle. mode: 'ok' | 'hang' | 'error'. `events` is
    shared with the fake Chrome processes so a test can read the ORDER."""

    def __init__(self, mode="ok", events=None):
        self.mode = mode
        self.stopped = False
        self.stops = 0
        self.events = [] if events is None else events
        self.never = asyncio.Event()

    async def stop(self):
        self.stops += 1
        self.events.append("stop")
        if self.mode == "hang":
            await self.never.wait()
        if self.mode == "error":
            raise Exception("Driver connection already gone")
        self.stopped = True


class _Proc:
    def __init__(self, name, cmdline, events=None):
        self.info = {"pid": 4242, "name": name, "cmdline": cmdline}
        self.killed = False
        self.kills = 0
        self.events = [] if events is None else events

    def kill(self):
        self.killed = True
        self.kills += 1
        self.events.append("kill")


def _browser_with(tmp_path, ctx, monkeypatch, pw=None, events=None):
    events = [] if events is None else events
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    b = research.Browser(str(profile))
    b.context = ctx
    b.playwright = _Pw(events=events) if pw is None else pw
    ours = _Proc("Google Chrome", ["/Applications/Google Chrome",
                                   f"--user-data-dir={profile.resolve()}"],
                 events=events)
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


# ── D14: the kill arm gives up the DRIVER too ──────────────────────────────
# ⛔⛔ THE LEAK (repair round). `playwright.stop()` lived on the success path
# only, so every close that ended in the kill arm — a hung Chrome now, an
# erroring close long before that — left the node driver process and its open
# pipe running for the life of `--serve`, while the relaunch started another.
# A week of crash retries meant a driver apiece, and "Future exception was
# never retrieved" noise from the pipes nobody was reading.

def test_a_hung_close_stops_the_driver_and_gives_up_its_handles(
        tmp_path, monkeypatch, logs):
    """⛔⛔ THE DEFECT. Before the repair `playwright.stop calls: 0` and the
    handle was still set — the refuter's probe printed exactly that."""
    monkeypatch.setattr(research, "_BROWSER_CLOSE_TIMEOUT_SEC", 0.05)
    events = []
    pw = _Pw(events=events)
    b, ours, _theirs = _browser_with(tmp_path, _HungCloseCtx(), monkeypatch,
                                     pw=pw, events=events)
    _run_bounded(b.close())
    assert pw.stops == 1, "the driver outlives the kill unless we stop it"
    assert b.playwright is None and b.context is None
    assert ours.kills == 1
    assert events == ["kill", "stop"], (
        "the kill comes FIRST — stopping the driver while it is still waiting "
        "for a Chrome that never exits is the freeze one layer down")


def test_a_driver_that_will_not_stop_does_not_hold_the_unwind(
        tmp_path, monkeypatch, logs):
    """The stop is bounded for the reason the close is: this arm is the run's
    way out. Against an unbounded stop the outer wait times out here."""
    monkeypatch.setattr(research, "_BROWSER_CLOSE_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(research, "_BROWSER_STOP_TIMEOUT_SEC", 0.05)
    events = []
    pw = _Pw("hang", events)
    b, ours, _theirs = _browser_with(tmp_path, _HungCloseCtx(), monkeypatch,
                                     pw=pw, events=events)
    _run_bounded(b.close())
    assert pw.stops == 1 and ours.kills == 1
    assert b.playwright is None and b.context is None


def test_a_driver_that_errors_on_stop_still_gives_up_its_handles(
        tmp_path, monkeypatch, logs):
    """A stop that throws must not escape close() — the callers that reach
    this arm are a pause and run_pipeline's own finally."""
    monkeypatch.setattr(research, "_BROWSER_CLOSE_TIMEOUT_SEC", 0.05)
    events = []
    pw = _Pw("error", events)
    b, ours, _theirs = _browser_with(tmp_path, _HungCloseCtx(), monkeypatch,
                                     pw=pw, events=events)
    _run_bounded(b.close())
    assert ours.kills == 1
    assert b.playwright is None and b.context is None
    assert any(lvl == "WARN" and "stop" in m.lower() for lvl, m in logs), logs


def test_a_second_close_after_a_hung_one_is_a_no_op(tmp_path, monkeypatch, logs):
    """⭐ The handles are cleared so the SECOND close — `pause_and_close_browser`
    and run_pipeline's finally both call it — does not repeat the bounded wait,
    the kill and the stop on handles we already gave up on."""
    monkeypatch.setattr(research, "_BROWSER_CLOSE_TIMEOUT_SEC", 0.05)
    events = []
    pw = _Pw(events=events)
    ctx = _HungCloseCtx()
    b, ours, _theirs = _browser_with(tmp_path, ctx, monkeypatch,
                                     pw=pw, events=events)
    _run_bounded(b.close())
    _run_bounded(b.close())
    assert ctx.attempts == 1, "nothing left to close"
    assert pw.stops == 1 and ours.kills == 1


def test_a_healthy_close_stops_the_driver_exactly_once(tmp_path, monkeypatch, logs):
    """⭐ ACCEPT POLARITY. The success path is untouched: one stop, no kill,
    and the fallback's stop does not run a second time on top of it."""
    monkeypatch.setattr(research, "_BROWSER_CLOSE_TIMEOUT_SEC", 0.5)
    events = []
    pw = _Pw(events=events)
    b, ours, theirs = _browser_with(tmp_path, _QuickCloseCtx(), monkeypatch,
                                    pw=pw, events=events)
    _run_bounded(b.close())
    assert pw.stops == 1 and events == ["stop"]
    assert ours.kills == 0 and theirs.kills == 0


def test_the_driver_stop_bound_is_short_and_finite():
    """Short because our Chrome is already dead by then and a driver with
    nothing left to wait for exits at once."""
    assert 1.0 <= research._BROWSER_STOP_TIMEOUT_SEC <= 60.0


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


# ── D5: the hang phase 2's poll loop could not see ─────────────────────────
# ⛔⛔ THE PROBE NEVER REACHED IT (repair round). The round-robin tick awaits
# `browser.switch_to_page(page)` → `page.bring_to_front()` and `page.evaluate`,
# none of which the driver bounds, and it consults `_browser_context_is_dead`
# only after a tab reports CLOSED — which a hung Chrome's tabs never do. So the
# tick parked inside a page call, the phase ceiling above it only warns, and the
# run sat frozen until the worker's five-hour ceiling.
#
# ⛔ A tick that overran cannot report its own overrun: the overrun IS an await
# that never returns, so there is no line after it to check the clock on. Only
# somebody outside the tick can see it. These tests drive that somebody.

class _ScriptedCtx:
    """A context whose answers are scripted per probe: 'ok' | 'hang' | 'closed'.
    The last entry repeats, so one word describes every probe."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = 0
        self.never = asyncio.Event()

    async def cookies(self):
        self.asked += 1
        answer = self.answers[min(self.asked - 1, len(self.answers) - 1)]
        if answer == "hang":
            await self.never.wait()  # nobody ever sets it
        if answer == "closed":
            raise Exception(CLOSED)
        return []


class _CtxThatFreesThePoll:
    """Silent, and on the silence that would spend the ladder it lets the poll
    finish first — the race a counter of silences creates."""

    def __init__(self, free_on, event):
        self.free_on, self.event = free_on, event
        self.asked = 0
        self.never = asyncio.Event()

    async def cookies(self):
        self.asked += 1
        if self.asked >= self.free_on:
            self.event.set()
            await asyncio.sleep(0.005)   # …and let it actually run to the end
        await self.never.wait()          # still inside this probe's bound


class _FrozenPoll:
    """The round-robin, parked in a page call the driver never bounds."""

    def __init__(self):
        self.cancelled = False
        self.never = asyncio.Event()

    async def run(self):
        try:
            await self.never.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {"never": "reached"}


class _WorkingPoll:
    """The round-robin doing something slow but real: a heavy page's evaluate
    can legitimately take tens of seconds, and several watchdog checks fall
    inside one of them."""

    def __init__(self, evaluate_sec, rounds=1):
        self.evaluate_sec, self.rounds = evaluate_sec, rounds
        self.cancelled = False

    async def run(self):
        try:
            for _ in range(self.rounds):
                await asyncio.sleep(self.evaluate_sec)   # page.evaluate(...)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {"ChatGPT": {"status": "complete"}}


@pytest.fixture
def fast_watchdog(monkeypatch):
    """The real ladder on a millisecond clock: three probes' worth of silence,
    a check apart, with the same arithmetic the shipped constants have."""
    monkeypatch.setattr(research, "_CTX_PROBE_TIMEOUT_SEC", 0.02)
    monkeypatch.setattr(research, "_PHASE2_HANG_CHECK_SEC", 0.01)
    monkeypatch.setattr(research, "_PHASE2_HANG_STRIKES", 2)
    monkeypatch.setattr(research, "_PHASE2_HANG_UNWIND_GRACE_SEC", 0.5)
    monkeypatch.setattr(research._runtime, "last_failure_kind", "")


def test_a_hung_chrome_unwinds_phase_two_instead_of_freezing_it(fast_watchdog, logs):
    """⛔⛔ THE DEFECT. Against the code before this repair the outer wait times
    out here — which is the bug, in one line: the run never comes back."""
    ctx, poll = _ScriptedCtx("hang"), _FrozenPoll()
    with pytest.raises(RuntimeError, match=r"\(browser crash\)") as ei:
        _run_bounded(research._poll_phase2_watching_for_a_hang(
            _Browser(ctx), poll.run()))
    # The same sentence shape the crash sweep raises, so the top-level handler
    # re-derives the kind from the exception alone — and the flag as well.
    assert research._is_browser_close_error(ei.value) is True
    assert research._runtime.last_failure_kind == "browser_crash"
    assert ctx.asked == 2, "one silence per check, until the ladder is spent"


def test_the_frozen_poll_is_cancelled_before_the_unwind_leaves(fast_watchdog, logs):
    """A run that unwound while its poll kept polling would relaunch Chrome
    underneath a loop still driving the old tabs.

    ⛔ Read AT THE RAISE, not after the test's event loop has closed: closing a
    loop cancels whatever is still pending, so a check made afterwards passes
    for code that never cancelled anything."""
    poll = _FrozenPoll()

    async def _go():
        try:
            await asyncio.wait_for(research._poll_phase2_watching_for_a_hang(
                _Browser(_ScriptedCtx("hang")), poll.run()), OUTER)
        except RuntimeError:
            return poll.cancelled
        raise AssertionError("the hang did not unwind")
    assert asyncio.run(_go()) is True


def test_a_slow_but_answering_browser_is_left_to_work(fast_watchdog, logs):
    """⭐ ACCEPT POLARITY, and the one the spec names: a tick sitting in a page
    evaluate that takes many checks is not a hang while the browser answers."""
    ctx = _ScriptedCtx("ok")
    poll = _WorkingPoll(evaluate_sec=0.2)
    out = _run_bounded(research._poll_phase2_watching_for_a_hang(
        _Browser(ctx), poll.run()))
    assert out == {"ChatGPT": {"status": "complete"}}
    assert poll.cancelled is False
    assert ctx.asked >= 2, "the watchdog really did check while it worked"


def test_a_stall_between_answers_never_adds_up(fast_watchdog, logs):
    """A one-off silence — a waking laptop, a disk stall on the profile — is
    not a hang: only CONSECUTIVE silences are, so an answer wipes the slate."""
    ctx = _ScriptedCtx("hang", "ok", "hang", "ok", "ok")
    poll = _WorkingPoll(evaluate_sec=0.02, rounds=12)
    out = _run_bounded(research._poll_phase2_watching_for_a_hang(
        _Browser(ctx), poll.run()))
    assert out == {"ChatGPT": {"status": "complete"}}
    assert poll.cancelled is False
    assert ctx.asked >= 5, "both silences happened and neither counted"


def test_a_phase_that_finished_during_the_last_probe_is_not_thrown_away(
        fast_watchdog, logs):
    """⭐ Each rung of the ladder costs a full probe, and the poll can come back
    during one — carrying the phase's results. Unwinding on a browser nobody is
    waiting on any more would buy the whole of phase 2 a second time."""
    freed = asyncio.Event()
    ctx = _CtxThatFreesThePoll(free_on=2, event=freed)

    async def _poll():
        await freed.wait()
        return {"ChatGPT": {"status": "complete"}}

    out = _run_bounded(research._poll_phase2_watching_for_a_hang(
        _Browser(ctx), _poll()))
    assert out == {"ChatGPT": {"status": "complete"}}
    assert ctx.asked == 2, "the ladder really was spent — this is the race"


def test_a_closed_browser_is_not_the_watchdogs_business(fast_watchdog, logs):
    """⛔⛔ THE PAUSE. `pause_and_close_browser` closes the browser and blocks
    for as long as the person likes; the poll resumes and relaunches after. A
    closed context ANSWERS, instantly, with an error — and reading that as a
    hang would end every long pause in a fake browser crash."""
    ctx = _ScriptedCtx("closed")
    poll = _WorkingPoll(evaluate_sec=0.2)
    out = _run_bounded(research._poll_phase2_watching_for_a_hang(
        _Browser(ctx), poll.run()))
    assert out == {"ChatGPT": {"status": "complete"}}
    assert poll.cancelled is False
    assert ctx.asked >= 2


def test_a_browser_with_no_context_is_not_a_hang(fast_watchdog, logs):
    """Same reason: between a close and the relaunch there is no handle to be
    silent. `_browser_context_is_dead` answers True there, on purpose, and that
    is exactly the answer this watchdog must not act on."""
    poll = _WorkingPoll(evaluate_sec=0.15)
    out = _run_bounded(research._poll_phase2_watching_for_a_hang(
        _Browser(None), poll.run()))
    assert out == {"ChatGPT": {"status": "complete"}} and poll.cancelled is False


def test_the_polls_own_crash_comes_back_untouched(fast_watchdog, logs):
    """The sweep's own unwind — the one this wave's first commit added — must
    reach the caller as itself, not as the watchdog's version of it."""
    boom = RuntimeError("research browser died during phase 2 (browser crash)")

    async def _poll():
        raise boom
    with pytest.raises(RuntimeError) as ei:
        _run_bounded(research._poll_phase2_watching_for_a_hang(
            _Browser(_ScriptedCtx("ok")), _poll()))
    assert ei.value is boom


def test_the_polls_results_come_back_unchanged(fast_watchdog, logs):
    """⭐ ACCEPT POLARITY for the ordinary phase: the wrapper is a wrapper."""
    results = {"Claude": {"status": "complete", "text": "x"}}
    ctx = _ScriptedCtx("ok")

    async def _poll():
        return results
    out = _run_bounded(research._poll_phase2_watching_for_a_hang(
        _Browser(ctx), _poll()))
    assert out is results
    assert ctx.asked == 0, "a poll that returns is never asked about"


@pytest.mark.parametrize("ctx, want", [
    (lambda: _Ctx("hung"), True),
    (lambda: _Ctx("alive"), False),
    # ⭐ The distinction `_browser_context_is_dead` deliberately does not make:
    # a context that says "I am closed" is talking to us. Somebody closed it
    # (a pause) or it died (the poll's own sweep unwinds within a tick).
    (lambda: _Ctx("dead"), False),
    (lambda: _Ctx("dead", exc=Exception("net::ERR_INTERNET_DISCONNECTED")), False),
    (lambda: _Ctx("slow", delay=0.01), False),
    (lambda: None, False),
])
def test_only_silence_reads_as_unresponsive(short_probe, logs, ctx, want):
    got = _run_bounded(research._browser_context_is_unresponsive(_Browser(ctx())))
    assert got is want


def test_the_silent_probe_is_cancelled_not_leaked(short_probe, logs):
    """One probe per check for as long as phase 2 runs — a leaked one apiece
    would pile up on the browser that is already not answering."""
    ctx = _Ctx("hung")
    _run_bounded(research._browser_context_is_unresponsive(_Browser(ctx)))
    assert ctx.cancelled is True


def test_the_poll_everybody_calls_is_the_watched_one():
    """⛔ THE WIRING. Nothing in the suite can execute the poll itself — four
    thousand lines of live browser work — so the decoration's mark on the
    function object is the pin, and the decorator's own decision is executed
    below on a stand-in the size of a test."""
    assert research.poll_all_agents_round_robin.watches_for_a_hung_browser is True


def test_the_decoration_stays_transparent_to_getsource():
    """Eight other files read this function's SOURCE. A wrapper that did not
    carry `__wrapped__` would hand them the three-line wrapper instead, and
    every one of those pins would quietly start measuring nothing."""
    import inspect
    assert (inspect.getsource(research.poll_all_agents_round_robin)
            == inspect.getsource(research.poll_all_agents_round_robin.__wrapped__))


def test_the_decoration_puts_the_watchdog_around_the_poll(fast_watchdog, logs):
    """The decorator's decision, executed: a hung browser unwinds the call."""
    poll = _FrozenPoll()

    @research._watched_for_a_hung_browser
    async def _poll(agents, browser, cua_client, verbose=False):
        return await poll.run()

    with pytest.raises(RuntimeError, match=r"\(browser crash\)"):
        _run_bounded(_poll({}, _Browser(_ScriptedCtx("hang")), None))


def test_the_decoration_watches_the_browser_the_caller_passed(fast_watchdog, logs):
    """By keyword as well as second-positional — a wrapper that watched the
    wrong argument would probe something with no context and never see a hang."""
    poll = _FrozenPoll()

    @research._watched_for_a_hung_browser
    async def _poll(agents, browser, cua_client, verbose=False):
        return await poll.run()

    with pytest.raises(RuntimeError, match=r"\(browser crash\)"):
        _run_bounded(_poll({}, browser=_Browser(_ScriptedCtx("hang")),
                           cua_client=None))


def test_the_decoration_hands_the_poll_its_arguments_and_its_result_back(
        fast_watchdog, logs):
    """⭐ ACCEPT POLARITY: on a browser that answers, the decoration is nothing
    but a pass-through — every argument in, the results out."""
    seen = {}

    @research._watched_for_a_hung_browser
    async def _poll(agents, browser, cua_client, max_wait_min=90, verbose=False):
        seen.update(agents=agents, cua=cua_client,
                    max_wait_min=max_wait_min, verbose=verbose)
        return {"Claude": {"status": "complete"}}

    out = _run_bounded(_poll({"Claude": 1}, _Browser(_ScriptedCtx("ok")), "cua",
                             max_wait_min=7, verbose=True))
    assert out == {"Claude": {"status": "complete"}}
    assert seen == {"agents": {"Claude": 1}, "cua": "cua",
                    "max_wait_min": 7, "verbose": True}


def test_the_watchdog_ladder_is_generous_but_finite():
    """Generous: a live Chrome answers a cookie read in milliseconds however
    hard its tabs work, but a machine can stall once. Finite: the ceiling this
    replaces is the worker's, measured in hours."""
    assert 30.0 <= research._PHASE2_HANG_CHECK_SEC <= 600.0
    assert 2 <= research._PHASE2_HANG_STRIKES <= 10
    assert (research._PHASE2_HANG_CHECK_SEC
            * research._PHASE2_HANG_STRIKES) <= 1800.0
    assert 5.0 <= research._PHASE2_HANG_UNWIND_GRACE_SEC <= 120.0
