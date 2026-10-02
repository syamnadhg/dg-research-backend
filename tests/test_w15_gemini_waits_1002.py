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


#: A 'Start research' that counts its presses on the page itself (the DOM is
#: what the program's isolated script world and the page's own world share).
LATE_START = ('<button aria-label="Start research" style="width:90px;height:24px" '
              'onclick="document.body.dataset.pressed = '
              'String(Number(document.body.dataset.pressed || 0) + 1); this.remove()">'
              'Start research</button>')


@pytest.fixture
def round_robin(chrome, monkeypatch):
    """`run(watch, minutes)` runs the REAL round-robin over one Gemini on its
    planning screen for `minutes` of the program's own time. Returns what it
    asked computer use for, and the cards it raised.

    `retry` queues the person's Retry on Gemini before the first leg — the real
    hard retry runs, its setup stood in for: "brief-in" (the brief went into a
    new chat, which stays on the planning screen) or "brief-not-in" (the set-up
    failed). `start_at` puts a LATE_START on the page at that minute;
    `pressed` is how many times it was pressed. `emits` is every event."""
    clock = _Clock()

    class _FastAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(delay=0, *a, **k):
            clock.t += float(delay or 0)
            if clock.t - start["t"] > start["limit"]:
                raise _Enough()
            if (start.get("start_at") is not None and not start.get("start_shown")
                    and clock.t - start["t"] >= start["start_at"] * 60):
                start["start_shown"] = True
                await start["page"].evaluate(
                    "(h) => document.querySelector('message-content')"
                    ".insertAdjacentHTML('beforeend', h)", LATE_START)
            await asyncio.sleep(0)

    start = {"t": clock.t, "limit": 0}
    looks, cards, lines, emits, cua = [], [], [], [], []
    monkeypatch.setattr(research, "time", clock)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research, "log", lambda m, level="INFO": lines.append(str(m)))
    monkeypatch.setattr(research, "emit_event",
                        lambda name, *a, **k: emits.append((name, dict(k))))
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "fail_agent", lambda *a, **k: cards.append(a))
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "_AGENT_ERROR_CARD_TS", {})
    monkeypatch.setattr(research, "_clear_pending_decision", lambda *a, **k: None)

    async def _look(page, **k):
        looks.append(k.get("hotspot_id"))
        return {"text": "CONCLUSION: working\nCONCLUSION: generating"}

    async def _computer_use(*a, **k):
        cua.append(a[2] if len(a) > 2 else k.get("system_prompt"))
        return ""

    monkeypatch.setattr(research, "_shadow_observed_cua", _look)
    monkeypatch.setattr(research, "agent_loop", _computer_use)
    ctl = research._controls
    monkeypatch.setattr(ctl, "skipped_agents", set())
    monkeypatch.setattr(ctl, "retry_agents_hard", set())
    monkeypatch.setattr(ctl, "is_stop", lambda: False)
    monkeypatch.setattr(ctl, "is_pause", lambda: False)

    def run(*, watch, minutes, html=PLANNING, entry=None, retry=None, start_at=None):
        for seen in (looks, cards, lines, emits, cua):
            seen.clear()
        pg = chrome.run(chrome.ctx.new_page())
        try:
            chrome.run(pg.set_content(html))

            class _Browser:
                context = chrome.ctx
                page = pg

                async def switch_to_page(self, p):
                    self.page = p

                async def screenshot(self):
                    return "iVBORw0KGgo="

            async def _set_up_again(browser, cua_client, *a, reuse_page=None, **k):
                # The person's Retry: the same tab, a new chat, the brief in (or not).
                return reuse_page, retry == "brief-in"

            monkeypatch.setattr(research, "start_agent_no_gemini_wait", _set_up_again)
            if retry:
                ctl.request_retry_agent_hard("gemini")
            start.update(t=clock.t, limit=minutes * 60, start_at=start_at,
                         start_shown=False, page=pg)
            agents = {"Gemini": {"page": pg, "verified": False,
                                 "url": "https://gemini.google.com/app/ours1234abcd",
                                 "research_started_at": clock.t, "brief": "brief " * 40,
                                 "needs_start_verify": False, "gemini_watch_start": watch,
                                 **(entry or {})}}
            try:
                chrome.run(asyncio.wait_for(research.poll_all_agents_round_robin(
                    agents, _Browser(), object(), max_wait_min=600, poll_interval=60),
                    timeout=120))
            except _Enough:
                pass
            pressed = int(chrome.run(pg.evaluate(
                "() => document.body.dataset.pressed || '0'")))
        finally:
            chrome.run(pg.close())
        return SimpleNamespace(looks=looks, cards=cards, lines=lines, emits=emits,
                               cua=cua, pressed=pressed)

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


# ══ a person's Retry on Gemini ═══════════════════════════════════════════════

def _said_rr(out, words):
    return [m for m in out.lines if words in m]


def test_after_a_persons_retry_gemini_just_waits_too(round_robin):
    """⭐⭐ THE OTHER DOOR TO THE PLANNING ALERT. A person's Retry gives Gemini a
    new chat, and its plan is still being drafted. Before: ninety seconds, then
    computer use pointed at the plan, then two more minutes, then "Gemini
    couldn't start Deep Research" — the card the plan wait no longer raises — and
    an unwatched Gemini that the "seems stuck" check looked at. Now it goes back
    to the round-robin to wait, watched: forty minutes with no card, no computer
    use and no look, and the 'Start research' that appears at minute 20 is
    pressed, once.
    ⛔ Beside it, the other side: a Retry whose brief did not go in (its set-up's
    own card is up) is not watched — the watch presses, and that tab is not
    provably the run's chat — so its 'Start research' is left alone and the
    round-robin's ordinary checks run."""
    out = round_robin(watch=False, minutes=40, retry="brief-in", start_at=20)
    assert _said_rr(out, "Hard retry #1"), out.lines[:20]
    assert out.cards == [], out.cards
    assert out.cua == [], out.cua
    assert out.looks == [], out.looks
    assert out.pressed == 1, out.pressed
    assert _said_rr(out, "its research has not started yet")
    assert _said_rr(out, "late 'Start research' appeared — clicked #1/3")

    out2 = round_robin(watch=False, minutes=40, retry="brief-not-in", start_at=20)
    assert _said_rr(out2, "Hard retry #1"), out2.lines[:20]
    assert out2.pressed == 0, out2.pressed
    assert "poll-stuck-arbiter" in out2.looks, out2.looks

    # And a plan that is already there: its Start is pressed by the retry itself,
    # one look confirms the research is running, and nothing is left to watch.
    ready = (PLANNING.replace("</message-content>", LATE_START + "</message-content>")
             .replace("</main>", VISIBLE_STOP + "</main>"))
    out3 = round_robin(watch=False, minutes=5, retry="brief-in", html=ready)
    assert out3.pressed == 1, out3.pressed
    assert _said_rr(out3, "Hard retry successful ✓"), out3.lines[:20]
    assert not _said_rr(out3, "its research has not started yet")
    assert out3.cards == [] and out3.cua == [], (out3.cards, out3.cua)


def test_a_start_confirmed_a_leg_late_raises_no_recovered_notice(round_robin):
    """⛔ 2D pressed Start and its one instant look could not confirm it, so the
    round-robin's first legs re-check. When it confirms, nothing is said unless a
    card is up: the app takes a retraction only for a live card and shows
    anything else as a notice of its own — "Gemini recovered and began its deep
    research" about a Gemini nothing went wrong with (the plan wait raises no
    card, so this is the usual case). Beside it, the same confirmation with a
    card up takes that card down, once, by its own alert id."""
    researching = PLANNING.replace("</main>", VISIBLE_STOP + "</main>")
    out = round_robin(watch=False, minutes=3, html=researching,
                      entry={"needs_start_verify": True})
    assert _said_rr(out, "confirmed on round-robin re-check"), out.lines[-20:]
    assert not [k for n, k in out.emits if n == "pipeline_warning"], out.emits

    research._AGENT_ERROR_CARD_TS["gemini"] = 1.0
    out2 = round_robin(watch=False, minutes=3, html=researching,
                       entry={"needs_start_verify": True})
    took = [k for n, k in out2.emits if n == "pipeline_warning"]
    assert len(took) == 1, took
    assert took[0]["alert_id"] == "phase2_agent_gemini_error" and took[0]["actions"] == []
    assert "gemini" not in research._AGENT_ERROR_CARD_TS


# ══ review 10-02: what still reaches the person ══════════════════════════════

def _skipped(out):
    return [k for n, k in out.emits if n == "agent_skipped"]


def test_with_auto_skip_off_a_gemini_that_never_starts_is_asked_about_once(
        round_robin, monkeypatch):
    """⭐ Settings → Pipeline → Auto-skip stuck OFF means "ask me", not "never
    tell me". Gemini sits on "Generating research plan", watched: nothing is
    raised before the 90-minute ceiling, and at it the person is asked once —
    Retry or Skip — with no computer use. Before: four hours, nothing at all.
    Beside it, auto-skip ON skips Gemini at the ceiling, as before, and asks
    nothing."""
    monkeypatch.setattr(research._runtime, "auto_skip_stuck", False)
    out = round_robin(watch=True, minutes=89)
    assert out.cards == [], out.cards

    out = round_robin(watch=True, minutes=240)
    assert out.cards == [("gemini", *research._GEMINI_CANT_START)], out.cards
    assert out.cua == [] and out.looks == [], (out.cua, out.looks)
    assert _said_rr(out, "has not started after 90 min and auto-skip is off")
    assert _skipped(out) == []

    # A Gemini whose research has started is judged by the round-robin's own
    # checks, which still run for it — this ask is not one of them.
    started = round_robin(watch=False, minutes=240)
    assert ("gemini", *research._GEMINI_CANT_START) not in started.cards, started.cards

    monkeypatch.setattr(research._runtime, "auto_skip_stuck", True)
    on = round_robin(watch=True, minutes=120)
    assert on.cards == [], on.cards
    assert [k["reason"] for k in _skipped(on)] == ["auto_skip_hard_cap"]


#: Gemini's own failed plan (the owner's 09-10 capture) on the run's chat.
FAILED_PLAN_PAGE = ("<html><body><main><user-query><div class='query-text'>" + "brief " * 40
                    + "</div></user-query>" + CAPTURED_FAIL_TURN + "</main></body></html>")


@pytest.mark.parametrize("auto_skip", [True, False], ids=["auto-skip-on", "auto-skip-off"])
def test_a_failed_plan_is_one_honest_card_and_never_read_as_a_report(
        round_robin, monkeypatch, auto_skip):
    """⭐⭐ The failed plan shows no Stop and does show Share & export, which the
    done check read as a finished report: computer use copied it, the read failed,
    and "Couldn't read Gemini's report" went up eight times in four hours. Now:
    one card that says what Gemini showed, no computer use, nothing extracted. An
    unanswered card is skipped as an agent that "couldn't start" — at its
    window with auto-skip on, at the agent's 90-minute limit with it off."""
    monkeypatch.setattr(research._runtime, "auto_skip_stuck", auto_skip)
    out = round_robin(watch=True, minutes=240, html=FAILED_PLAN_PAGE)
    assert out.cards == [("gemini", "Gemini's plan failed",
                          "Gemini showed: Sorry, something went wrong. Please try your "
                          "request again. Retry starts a fresh chat, or Skip it.")], out.cards
    assert out.cua == [] and out.looks == [], (out.cua, out.looks)
    assert not _said_rr(out, "CONFIRMED DONE")
    assert _said_rr(out, "its research plan failed")
    [skip] = _skipped(out)
    assert skip["reason"] == ("auto_skip_setup_failed" if auto_skip else "auto_skip_hard_cap")
    assert skip["partial_chars"] == 0


def test_retry_on_the_failed_plan_card_starts_a_fresh_chat(round_robin, monkeypatch):
    """The card says "Retry starts a fresh chat", and it must: the person presses
    Retry once the card is up, and Gemini is set up again. ⛔ Even when an earlier
    leg had half-read the failed page as done — a reading the Retry would take for
    a finished agent, and swallow."""
    raised = []

    def _card_then_retry(*a, **k):
        raised.append(a)
        if a[1] == "Gemini's plan failed":
            research._controls.request_retry_agent_hard("gemini")
    monkeypatch.setattr(research, "fail_agent", _card_then_retry)
    out = round_robin(watch=True, minutes=10, html=FAILED_PLAN_PAGE,
                      entry={"done_count": 1})
    assert [c[1] for c in raised][:1] == ["Gemini's plan failed"], raised
    assert _said_rr(out, "Hard retry #1"), out.lines[-20:]
    assert not _said_rr(out, "already completed"), out.lines[-20:]


def test_a_failure_line_above_an_enabled_start_is_pressed_not_carded(round_robin):
    """What is actionable outranks a diagnosis: a 'Start research' showing under a
    turn that reads as failed is pressed, and the failed-plan card is not raised.
    (What this toy page shows after the press — the same failed turn — is not
    what a started research shows, so only the press and the card are read.)"""
    ready = FAILED_PLAN_PAGE.replace("</message-content>",
                                     "</message-content>" + LATE_START, 1)
    out = round_robin(watch=True, minutes=5, html=ready)
    assert out.pressed == 1, out.pressed
    assert not [c for c in out.cards if c[1] == "Gemini's plan failed"], out.cards
    assert not _said_rr(out, "its research plan failed")


class _Turns:
    """A page whose latest turn reads `texts`, one per read."""

    def __init__(self, *texts, start=False, body=""):
        self.texts, self.start, self.body = list(texts), start, body

    async def evaluate(self, script, *a):
        if script == research._GEMINI_LATEST_TURN_JS:
            text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
            return '{"found": true, "text": %s}' % __import__("json").dumps(text)
        if script == research._GEMINI_START_PRESENT_JS:
            return self.start
        return self.body


FAIL_LINE = "Sorry, something went wrong. Please try your request again."


@pytest.mark.parametrize("page, said", [
    (_Turns(FAIL_LINE), FAIL_LINE),
    (_Turns("Sorry, something went wrong", FAIL_LINE), ""),
    (_Turns(FAIL_LINE, start=True), ""),
    (_Turns(FAIL_LINE, body="Researching 12 websites"), ""),
    (_Turns("Here is my plan for the research."), ""),
], ids=["settled-failure", "still-changing", "start-showing", "research-running",
        "a-plan"])
def test_only_a_settled_failed_plan_reads_as_failed(monkeypatch, page, said):
    monkeypatch.setattr(research, "_GEMINI_PLAN_FAIL_SETTLE_SEC", 0)
    assert asyncio.run(research._gemini_watched_plan_failed(page)) == said
