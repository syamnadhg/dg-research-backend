"""Wave 15 (10-02) — Gemini just waits.

Gemini now starts its research by itself on a timer, as ChatGPT does. The owner:
"wait for the research without refreshing and then let the research finish …
keep it simple without making it complicated and causing alerts".

THE EVIDENCE
  · 10-01, research computer (3NH9Q7CH, retry2): "[2D] Gemini showed nothing
    new for 2 min — refreshing its chat (#1)" at 11:40:56; then at 11:45:02
    "Still streaming at 366s (≥ 360s) — a plan never streams this long, so
    Gemini has almost certainly auto-started its research". It had not: the
    page sat on "Generating research plan" until 12:25 — 47 minutes — when the
    round-robin's watch pressed the late 'Start research'.
  · 10-02 (CJFYMAB1): the same refresh at 00:19:37, the same 366 s hand-off at
    00:23:42 with "a plan with 'Start research' showing" on the page.

⭐ SO, IN THE PLAN WAIT AND AFTER IT: the chat is never reloaded; Stop and Redo
are never pressed; no new chat; no computer use; no card. A 'Start research'
that appears is pressed. The six-minute hand-off is gone; Gemini is handed to
the round-robin when the wait is over, with the late-Start watch armed, and the
round-robin lets it be: no "seems stuck" check and no computer-use completion
look while its research has not started.

── How it is measured ──────────────────────────────────────────────────────
The plan wait: the REAL `run_phase2` Gemini launch (2C/2D) in headless Chrome
with tests/test_gemini_plan_wait_1001.py's navigable fixture pages (every load of
a chat address is counted, so "never reloaded" is a count). Time is a clock the
program's own sleeps move.
The round-robin: the REAL `poll_all_agents_round_robin` over one Gemini on a
headless page, the same clock, its computer use a recorder.
"""
import asyncio
import time
from collections import Counter
from types import SimpleNamespace

import pytest

import research
from test_gemini_plan_wait_1001 import (
    APP, FOREIGN, OTHER, OURS, PLAN, SILENT, WITH_BUTTON, page, said)
from test_gemini_plan_wait_1001 import (  # noqa: F401  (fixtures, asked for by name below)
    chrome as _plan_chrome, launch as _plan_launch)
from test_gemini_redraft_0910 import CAPTURED_FAIL_TURN


@pytest.fixture(scope="module")
def chrome(request):
    """test_gemini_plan_wait_1001's headless Chrome. Imported as `chrome` itself
    it reads as a redefinition to the lint floor (F811, run with --ignore-noqa)."""
    return request.getfixturevalue("_plan_chrome")


@pytest.fixture
def launch(request):
    """test_gemini_plan_wait_1001's REAL Gemini launch (2C/2D), as `launch`."""
    return request.getfixturevalue("_plan_launch")

#: The 10-01 crash retry's screen: Gemini's own 'Stop response' showing and a
#: short reply that does not change.
VISIBLE_STOP = '<button aria-label="Stop response" style="width:24px;height:24px">■</button>'
STILL_REPLY = "<p>" + "I'm researching the import rules and the breeding sources now. " * 2 + "</p>"
#: The owner's captured failed plan (09-10), its Redo sized as its icon makes it
#: and recording a press the way the fixture records a Start press.
FAILED_PLAN = CAPTURED_FAIL_TURN.replace(
    '<button aria-label="Redo">',
    '<button aria-label="Redo" style="width:24px;height:24px" '
    'onclick="fetch(\'/__clicked/redo\')">')
NOT_YET = "No 'Start research' to press after"
SIX_MINUTE_CLAIM = "a plan never streams this long"


def _gemini(out):
    assert out.handed, "Gemini was never handed to the round-robin"
    return out.handed[0]["Gemini"]


# ══ the plan wait ════════════════════════════════════════════════════════════

def test_a_plan_slower_than_the_wait_is_handed_on_with_nothing_reloaded_pressed_or_raised(
        launch):
    """⭐⭐ THE OWNER'S RULE, end to end: ten minutes of a plan that has not come.
    The chat is loaded once — by the launch — and never again; nothing is
    pressed, no computer use, no card. Then Gemini goes to the round-robin with
    the late-Start watch armed, and the log says why in plain words.
    Before: a refresh at two minutes, one every two minutes after, the card at
    ten, then three computer-use passes."""
    out = launch(lambda cid, n: page(SILENT))
    assert out.loads == Counter({OURS: 1}), out.loads
    assert out.cards == [] and out.looks == [] and out.clicks == []
    hand = said(out, NOT_YET)
    assert len(hand) == 1 and hand[0][0] >= 600, hand
    assert "starts its research by itself" in hand[0][1]
    assert not said(out, "refreshing") and not said(out, SIX_MINUTE_CLAIM)
    g = _gemini(out)
    assert g["verified"] is False and g["gemini_watch_start"] is True, g


def test_gemini_showing_its_stop_for_the_whole_wait_is_not_called_started_at_six_minutes(
        launch):
    """⭐⭐ THE 10-01 CRASH RETRY'S SCREEN: Gemini's own Stop showing the whole
    time. The six-minute "it must have auto-started" hand-off is gone: Gemini is
    handed on when the wait is over, still watched for its Start — nothing
    raised, nothing reloaded. Before: handed off at 366 s as researching."""
    out = launch(lambda cid, n: page(STILL_REPLY, extra=VISIBLE_STOP))
    assert not said(out, SIX_MINUTE_CLAIM)
    hand = said(out, NOT_YET)
    assert len(hand) == 1 and hand[0][0] >= 600, hand
    assert _gemini(out)["gemini_watch_start"] is True
    assert out.cards == [] and out.looks == [] and out.clicks == []
    assert out.loads == Counter({OURS: 1}), out.loads


def test_a_plan_that_arrives_late_in_the_wait_is_started_with_no_reload(launch):
    """A 'Start research' that appears is still pressed — on the run's own chat,
    with the page never reloaded to find it."""
    arrived = []

    async def arrive(elapsed, pg):
        if elapsed >= 300 and not arrived:
            arrived.append(elapsed)
            await pg.evaluate("(h) => { document.querySelector('message-content')"
                              ".innerHTML = h; }", PLAN)

    out = launch(lambda cid, n: page(SILENT), on_tick=arrive)
    assert out.clicks == [OURS], out.clicks
    assert said(out, "Clicked 'Start research' via JS ✓")
    assert out.loads == Counter({OURS: 1}), out.loads
    assert out.cards == [] and out.looks == []
    assert not said(out, NOT_YET)


def test_a_failed_plan_is_never_redone_and_raises_nothing(launch):
    """⛔⛔ No Redo. The owner's captured failed plan: its Redo is never pressed,
    nothing is raised, and Gemini goes on to the round-robin, watched.
    Before: three re-drafts within about four minutes, then the card."""
    out = launch(lambda cid, n: page("", turn=FAILED_PLAN))
    assert out.clicks == [], out.clicks
    assert not said(out, "re-draft") and not said(out, "regenerate")
    assert out.cards == [] and out.looks == []
    assert _gemini(out)["gemini_watch_start"] is True


def test_a_tab_that_drifted_is_never_reloaded_or_pressed_and_is_not_watched(launch):
    """At 30 s the tab is on another chat whose plan has its own 'Start
    research'. It is not believed, nothing on it is pressed, and it is never
    reloaded or taken back; when the wait is over Gemini is handed on WITHOUT
    the late-Start watch, because the watch presses and this is not our chat.
    Before: the tab was loaded back to ours."""
    drifted = []

    def script(cid, n):
        return page(PLAN, brief=FOREIGN) if cid == OTHER else page(SILENT)

    async def drift(elapsed, pg):
        if elapsed >= 30 and not drifted:
            drifted.append(elapsed)
            await pg.goto(f"{APP}/{OTHER}")

    out = launch(script, on_tick=drift)
    assert out.clicks == [], out.clicks
    assert out.loads == Counter({OURS: 1, OTHER: 1}), out.loads
    assert not said(out, "going back to ours")
    assert out.cards == [] and out.looks == []
    assert _gemini(out)["gemini_watch_start"] is False


def test_a_shorter_wait_set_by_hand_hands_gemini_on_where_it_ends_with_no_card(
        launch, monkeypatch):
    """GEMINI_PLAN_WAIT_SEC still sets the wait. Where it ends Gemini is handed
    on — no card. Before: the card went up there."""
    monkeypatch.setenv("GEMINI_PLAN_WAIT_SEC", "300")
    out = launch(lambda cid, n: page(WITH_BUTTON), start="")
    hand = said(out, NOT_YET)
    assert len(hand) == 1 and 300 <= hand[0][0] < 330, hand
    assert out.cards == [] and out.looks == []


def test_an_auto_started_gemini_is_never_pressed_and_raises_nothing(launch):
    """#953's auto-start: its Start reads disabled and it streams. Nothing is
    pressed or reloaded, nothing raised, and the log makes no claim about what
    a plan "never" does."""
    auto = PLAN.replace('aria-label="Start research" ', 'aria-label="Start research" disabled ')
    out = launch(lambda cid, n: page(auto, extra='<div data-is-streaming="true">'
                                                 'Researching 12 websites</div>'))
    assert out.clicks == [] and out.cards == [] and out.looks == []
    assert out.loads == Counter({OURS: 1}), out.loads
    assert not said(out, SIX_MINUTE_CLAIM)


# ══ the round-robin after it ═════════════════════════════════════════════════

#: Gemini's planning screen, nothing growing: "Generating research plan".
PLANNING = ("<html><body><main><user-query><div class='query-text'>" + "brief " * 40 +
            "</div></user-query><model-response><message-content>"
            "<p>Generating research plan</p></message-content></model-response>"
            "</main></body></html>")


class _Clock:
    def __init__(self):
        self.t = time.time()

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return self.t


class _Enough(BaseException):
    """The round-robin has run as long as the test needs."""


@pytest.fixture
def round_robin(chrome, monkeypatch):
    """`run(watch, minutes)` runs the REAL round-robin over one Gemini on its
    planning screen for `minutes` of the program's own time. Returns what it
    asked computer use for, and the cards it raised."""
    clock = _Clock()

    class _FastAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(delay=0, *a, **k):
            clock.t += float(delay or 0)
            if clock.t - start["t"] > start["limit"]:
                raise _Enough()
            await asyncio.sleep(0)

    start = {"t": clock.t, "limit": 0}
    looks, cards, lines = [], [], []
    monkeypatch.setattr(research, "time", clock)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research, "log", lambda m, level="INFO": lines.append(str(m)))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "fail_agent", lambda *a, **k: cards.append(a))
    monkeypatch.setattr(research, "_tracks_dir", None)

    async def _look(page, **k):
        looks.append(k.get("hotspot_id"))
        return {"text": "CONCLUSION: working\nCONCLUSION: generating"}

    monkeypatch.setattr(research, "_shadow_observed_cua", _look)
    ctl = research._controls
    monkeypatch.setattr(ctl, "skipped_agents", set())
    monkeypatch.setattr(ctl, "is_stop", lambda: False)
    monkeypatch.setattr(ctl, "is_pause", lambda: False)

    def run(*, watch, minutes):
        pg = chrome.run(chrome.ctx.new_page())
        try:
            chrome.run(pg.set_content(PLANNING))

            class _Browser:
                context = chrome.ctx
                page = pg

                async def switch_to_page(self, p):
                    self.page = p

                async def screenshot(self):
                    return "iVBORw0KGgo="

            start["t"], start["limit"] = clock.t, minutes * 60
            agents = {"Gemini": {"page": pg, "verified": False,
                                 "url": "https://gemini.google.com/app/ours1234abcd",
                                 "research_started_at": clock.t, "brief": "brief " * 40,
                                 "needs_start_verify": False, "gemini_watch_start": watch}}
            try:
                chrome.run(asyncio.wait_for(research.poll_all_agents_round_robin(
                    agents, _Browser(), object(), max_wait_min=600, poll_interval=60),
                    timeout=120))
            except _Enough:
                pass
        finally:
            chrome.run(pg.close())
        return SimpleNamespace(looks=looks, cards=cards, lines=lines)

    return run


def test_a_gemini_whose_research_has_not_started_is_left_to_wait(round_robin):
    """⭐⭐ Forty minutes of "Generating research plan" (10-01 sat on it for 47),
    the watch armed: no "seems stuck" check, no computer-use look at all, no
    card. Beside it, the same page with the research started (watch cleared)
    gets both looks, as before — so it is the watch that holds them off."""
    out = round_robin(watch=True, minutes=40)
    assert out.looks == [], out.looks
    assert out.cards == [], out.cards
    assert not [m for m in out.lines if "CUA arbiter deciding stuck-vs-slow" in m]
    assert not [m for m in out.lines if "CUA checking completion" in m]

    out2 = round_robin(watch=False, minutes=40)
    assert "poll-stuck-arbiter" in out2.looks, out2.looks
    assert [m for m in out2.lines if "CUA checking completion" in m], out2.lines[-20:]
