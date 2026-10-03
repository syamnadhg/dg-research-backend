"""Wave 15 (10-03) — Gemini: Redo on a failed plan, never a refresh while it plans;
the research refresh catches a finished report that never loaded.

THE OWNER, 10-03: "if the planning fails and if it shows some message and a
redo option, we will try redo, but we are not refreshing, because refreshing is
making the planning stage go stale. … refresh during the research is going,
just to make sure we are not stuck on researching, and even after finishing the
research — sometimes the researching process might go stale even after
finishing research, it might not load the completed result — so that refresh is
there. But only during planning we are not refreshing."

⭐ SO, WHILE GEMINI PLANS: nothing refreshes, navigates or opens a new chat. A
plan that visibly FAILED — Gemini's failure line on the plan turn, settled, and
Gemini's own Redo showing — gets that Redo pressed, at most twice, 45 seconds
apart. Only when both left the plan failed does the "Gemini's plan failed" card
go up. A plan that is only slow is never pressed.

⭐ WHILE IT RESEARCHES AND AFTER: the 12-minute refresh (at most 3) stays, and it
now sees the research on a real page. It read the first 8,000 characters of the
whole page, and the brief this run pastes comes first on that page: the
twenty-seven real briefs on record are 46,183 to 73,494 characters. So on a
real run it never saw the "Researching N websites" card, and a research that
finished on Gemini's side while the page sat on its old "researching" view was
never refreshed. It now reads Gemini's own replies, without the person's turns.

── How it is measured ──────────────────────────────────────────────────────
The plan wait: the REAL `run_phase2` Gemini launch (2C/2D) in headless Chrome,
with tests/test_gemini_plan_wait_1001.py's navigable pages (every load of a chat
address is counted, so "never refreshed" is a count, and a press of Gemini's
Redo is a request the page makes). The round-robin: the REAL
`poll_all_agents_round_robin` over one Gemini on a navigable headless page, its
computer use a recorder, its report reader a recorder. Time is a clock the
program's own sleeps move. Pages are served by the test on a `.invalid` host, so
nothing leaves the machine.
"""
import asyncio
import re
import time
from collections import Counter
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

import research
from _domshim import NODE, run_js, spec_from_html
from test_gemini_finished_on_its_own_w13 import DONE_LINE
from test_gemini_plan_wait_1001 import APP, OURS, PLAN, page, said
from test_gemini_plan_wait_1001 import (  # noqa: F401  (fixtures, asked for by name below)
    chrome as _plan_chrome, launch as _plan_launch)
from test_gemini_redraft_0910 import CAPTURED_FAIL_TURN, CAPTURED_REGEN_MENU


@pytest.fixture(scope="module")
def chrome(request):
    """test_gemini_plan_wait_1001's headless Chrome, under its own name here."""
    return request.getfixturevalue("_plan_chrome")


@pytest.fixture
def launch(request):
    """test_gemini_plan_wait_1001's REAL Gemini launch (2C/2D), as `launch`."""
    return request.getfixturevalue("_plan_launch")


# ══ the pages ════════════════════════════════════════════════════════════════

#: The smallest real brief on record is 46,183 characters (research.py, the note
#: above `_TOPIC_GUARD_MIN_CHARS`: 27 real briefs, 46,183 to 73,494).
REAL_BRIEF = ("# Research Brief\n\nThe economic history of the Hanseatic League and its "
              "Baltic trade routes between 1300 and 1600. ")
REAL_BRIEF = (REAL_BRIEF * (46183 // len(REAL_BRIEF) + 1))[:46183]

#: Gemini's own failed plan (the owner's 09-10 capture), its Redo sized as its
#: icon makes it. A press asks the test's server for /__clicked/redo, and opens
#: the menu Gemini opens (the owner's capture of it); picking "Don't personalise"
#: asks for /__clicked/redraft and, when `fix` is set on the page, draws a plan
#: with its 'Start research' in place of the failure.
_REDO_PRESS = ("fetch('/__clicked/redo');"
               "document.body.insertAdjacentHTML('beforeend', window.__menu);")
FAILED_PLAN_TURN = CAPTURED_FAIL_TURN.replace(
    '<button aria-label="Redo">',
    f'<button aria-label="Redo" style="width:24px;height:24px" onclick="{_REDO_PRESS}">')
MENU = CAPTURED_REGEN_MENU.replace(
    '<gem-menu-item data-test-id="regenerate-option" role="menuitem">',
    '<gem-menu-item data-test-id="regenerate-option" role="menuitem" '
    'style="display:block;width:160px;height:32px" onclick="window.__pick()">')
PICK_JS = ("<script>window.__menu = %s;"
           "window.__pick = function () {"
           "  fetch('/__clicked/redraft');"
           "  document.querySelectorAll('.cdk-overlay-container').forEach(n => n.remove());"
           "  if (document.body.dataset.fix === '1') {"
           "    document.querySelector('model-response').outerHTML = window.__plan; }"
           "};"
           "window.__plan = %s;</script>")


def _js_str(s):
    import json
    return json.dumps(s)


def failed_plan(*, fix=False, brief=None, extra=""):
    """The run's chat showing Gemini's failed plan. `fix`: a Redo that is picked
    brings back a plan with 'Start research'."""
    plan_turn = f"<model-response><message-content>{PLAN}</message-content></model-response>"
    html = page("", turn=FAILED_PLAN_TURN, extra=extra,
                **({"brief": brief} if brief else {}))
    script = PICK_JS % (_js_str(MENU), _js_str(plan_turn))
    html = html.replace("<html><body>", "<html><body" + (' data-fix="1"' if fix else "")
                        + ">" + script)
    return html


def _without_redo(html):
    """The captured action row without its Redo (the whole regenerate button)."""
    return re.sub(r'<gem-icon-button data-test-id="regenerate-button">.*?</gem-icon-button>',
                  "", html, count=1, flags=re.S)


#: Gemini's research view as a page that went stale shows it: the plan, then the
#: "Researching 143 websites" card, Gemini's hidden 'Stop response' (the 08-19
#: capture: icon-only, 0×0), no completion line and no report.
STALE_RESEARCH = ("<p>Here is my research plan for the Hanseatic League.</p>"
                  "<button aria-label=\"Start research\" disabled>Start research</button>"
                  "</message-content></model-response><model-response><message-content>"
                  "<p>Researching 143 websites</p>")
HIDDEN_STOP = '<button aria-label="Stop response" style="display:none">■</button>'


def finished_report(brief):
    """The same chat once its report has loaded: Gemini's completion line and the
    report's 'Contents · Share & Export · Create' row."""
    return page(f"<p>Here is my research plan for the Hanseatic League.</p>"
                f"</message-content></model-response><model-response><message-content>"
                f"<p>{DONE_LINE}</p>",
                brief=brief,
                extra="<immersive-panel><h1>The Hanseatic League</h1>"
                      + "<p>Findings of the research, in full.</p>" * 20
                      + "<button>Contents</button><button>Share &amp; Export</button>"
                        "<button>Create</button></immersive-panel>")


#: Gemini's planning screen: "Generating research plan", nothing growing.
def planning(brief):
    return page("<p>Generating research plan</p>", brief=brief)


# ══ the round-robin, on a page that can be reloaded ═════════════════════════

class _Clock:
    def __init__(self):
        self.t = time.time()

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return self.t


class _Enough(BaseException):
    """The round-robin has run as long as the test needs."""


#: In a round-robin `entry`: the moment the round-robin is handed Gemini.
NOW = "<now>"


@pytest.fixture
def round_robin(chrome, monkeypatch):
    """`run(script, minutes=…, entry=…, on_minute=…)` runs the REAL round-robin
    over one Gemini whose chat is served by `script(nth_load)` — so a refresh is
    a real reload, and counted. Returns the loads, the presses Gemini's page
    asked for, the cards, the computer use, what was collected and the log."""
    clock = _Clock()
    run_state = {"t": clock.t, "limit": 0, "hooks": [], "page": None}

    class _FastAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(delay=0, *a, **k):
            clock.t += float(delay or 0)
            if clock.t - run_state["t"] > run_state["limit"]:
                raise _Enough()
            for hook in list(run_state["hooks"]):
                await hook((clock.t - run_state["t"]) / 60.0, run_state["page"])
            await asyncio.sleep(0)

    lines, cards, cua, looks, collected = [], [], [], [], []
    monkeypatch.setattr(research, "time", clock)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research, "log",
                        lambda m, level="INFO": lines.append(
                            ((clock.t - run_state["t"]) / 60.0, str(m))))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "fail_agent",
                        lambda *a, **k: cards.append(((clock.t - run_state["t"]) / 60.0, a)))
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "_AGENT_ERROR_CARD_TS", {})
    monkeypatch.setattr(research, "_clear_pending_decision", lambda *a, **k: None)

    async def _look(page, **k):
        looks.append(k.get("hotspot_id"))
        return {"text": "CONCLUSION: working\nCONCLUSION: generating"}

    async def _computer_use(*a, **k):
        cua.append(a[2] if len(a) > 2 else k.get("system_prompt"))
        return ""

    async def _collect(name, page, *a, **k):
        collected.append((clock.t - run_state["t"]) / 60.0)
        return {"status": "done", "text": "The Hanseatic League report. " * 50,
                "url": page.url, "elapsed_sec": 0}

    monkeypatch.setattr(research, "_shadow_observed_cua", _look)
    monkeypatch.setattr(research, "agent_loop", _computer_use)
    monkeypatch.setattr(research, "extract_and_record_agent", _collect)
    ctl = research._controls
    monkeypatch.setattr(ctl, "skipped_agents", set())
    monkeypatch.setattr(ctl, "retry_agents_hard", set())
    monkeypatch.setattr(ctl, "is_stop", lambda: False)
    monkeypatch.setattr(ctl, "is_pause", lambda: False)

    def run(script, *, minutes, brief, entry=None, on_minute=None):
        for seen in (lines, cards, cua, looks, collected):
            seen.clear()
        loads, presses = [], []

        async def _answer(route):
            path = urlsplit(route.request.url).path
            if path.startswith("/__clicked/"):
                presses.append(((clock.t - run_state["t"]) / 60.0, path.rsplit("/", 1)[1]))
                await route.fulfill(status=204, body="")
                return
            m = re.fullmatch(r"/gemini\.google\.com/app/([A-Za-z0-9_-]*)", path)
            if m is None:
                await route.abort()
                return
            loads.append((clock.t - run_state["t"]) / 60.0)
            await route.fulfill(status=200, content_type="text/html",
                                body=script(len(loads)))

        pg = chrome.run(chrome.ctx.new_page())
        try:
            chrome.run(pg.route("**/*", _answer))
            chrome.run(pg.goto(f"{APP}/{OURS}"))

            class _Browser:
                context = chrome.ctx
                page = pg

                async def switch_to_page(self, p):
                    self.page = p

                async def screenshot(self):
                    return "iVBORw0KGgo="

            run_state.update(t=clock.t, limit=minutes * 60, page=pg,
                             hooks=[on_minute] if on_minute else [])
            agents = {"Gemini": {"page": pg, "verified": True, "url": pg.url,
                                 "research_started_at": clock.t, "brief": brief,
                                 "needs_start_verify": False, "gemini_watch_start": False,
                                 # NOW: the moment the round-robin is handed Gemini
                                 **{k: (clock.t if v == NOW else v)
                                    for k, v in (entry or {}).items()}}}
            out = {}
            try:
                out = chrome.run(asyncio.wait_for(research.poll_all_agents_round_robin(
                    agents, _Browser(), object(), max_wait_min=600, poll_interval=60),
                    timeout=180))
            except _Enough:
                pass
        finally:
            run_state["hooks"] = []
            chrome.run(pg.close())
        return SimpleNamespace(loads=loads, presses=presses, cards=list(cards),
                               cua=list(cua), looks=list(looks), collected=list(collected),
                               lines=list(lines), results=out or {})

    return run


def _said(out, words):
    return [(round(t, 1), m) for t, m in out.lines if words in m]


# ══ the plan wait (2D): Gemini's own Redo, never a refresh ═══════════════════

PRESSED = "pressed Gemini's own Redo"


def _gemini(out):
    assert out.handed, "Gemini was never handed to the round-robin"
    return out.handed[0]["Gemini"]


def test_a_failed_plan_is_redone_and_the_plan_it_brings_back_is_started(launch):
    """⭐⭐ THE OWNER'S RULE, end to end. Gemini's plan failed — its failure line
    and its Redo showing. The Redo is pressed, its menu's "Don't personalise" row
    picked, the plan comes back with 'Start research', and that is pressed — all
    on the run's own chat, loaded once and never again, with nothing raised.
    Before: nothing was pressed; the failed plan sat for ten minutes and then
    went to the round-robin, which raised "Gemini's plan failed"."""
    out = launch(lambda cid, n: failed_plan(fix=True))
    assert out.clicks == ["redo", "redraft", OURS], out.clicks
    assert out.loads == Counter({OURS: 1}), out.loads
    assert out.cards == [] and out.looks == []
    assert said(out, "Clicked 'Start research' via JS ✓")
    assert len(said(out, PRESSED)) == 1, said(out, PRESSED)
    assert said(out, "1 of 2")
    assert _gemini(out)["gemini_plan_redos"] == 1
    # The tile says so while it happens.
    assert [k["progress"] for n, k in out.events if n == "agent_progress"
            and "pressed its Redo" in (k.get("progress") or "")] == [
        "Gemini's plan hit an error — pressed its Redo (1 of 2)"]


def test_a_plan_that_stays_failed_is_redone_twice_45_seconds_apart_and_never_refreshed(
        launch):
    """Both presses leave the plan failed: the Redo is pressed twice and no
    more, at least 45 seconds apart, the chat is never reloaded and nothing is
    raised in the wait. Gemini goes on, watched, with both presses spent, and
    the log says so once. Before: never pressed."""
    out = launch(lambda cid, n: failed_plan())
    assert out.clicks == ["redo", "redraft", "redo", "redraft"], out.clicks
    presses = said(out, PRESSED)
    assert [m.split(PRESSED + ", ", 1)[1][:6] for _t, m in presses] == ["1 of 2", "2 of 2"]
    assert presses[1][0] - presses[0][0] >= 45, presses
    assert out.loads == Counter({OURS: 1}), out.loads
    assert out.cards == [] and out.looks == []
    assert len(said(out, "its Redo, pressed twice, did not bring it back")) == 1
    g = _gemini(out)
    assert g["gemini_plan_redos"] == 2 and g["gemini_watch_start"] is True, g


def test_only_a_plan_that_visibly_failed_is_redone(launch):
    """A settled failure with Gemini's Redo showing is pressed (the first run);
    beside it, three plans that are NOT pressed and not reloaded:
      · a turn whose short, failure-sounding text is still changing — a plan
        still streaming;
      · a failure line while the research is already running;
      · a failure line with no Redo on it (nothing to press: the round-robin's
        card is the answer, as before).
    Before: the first was never pressed either."""
    grown = []

    async def stream(elapsed, pg):
        grown.append(elapsed)
        await pg.evaluate("(n) => { const m = document.querySelector('message-content');"
                          " m.textContent = 'Something went wrong with ' + n; }", len(grown))

    # (first: the launch fixture's tick hook can only follow its first run's page)
    streaming = launch(lambda cid, n: failed_plan(), on_tick=stream)
    out = launch(lambda cid, n: failed_plan())
    assert out.clicks[:1] == ["redo"], out.clicks
    # The research's turn ABOVE the failed one, which stays the latest turn.
    running = launch(lambda cid, n: failed_plan().replace(
        "<model-response>\n  <div class=\"response-container\">",
        "<model-response><message-content><p>Researching 12 websites</p>"
        "</message-content></model-response>"
        "<model-response>\n  <div class=\"response-container\">", 1))
    no_redo = launch(lambda cid, n: _without_redo(failed_plan()))
    for what, o in (("streaming", streaming), ("running", running), ("no Redo", no_redo)):
        assert o.clicks == [], (what, o.clicks)
        assert o.loads == Counter({OURS: 1}), (what, o.loads)
    # The fixture keeps one log and one card list across the four runs: the only
    # presses in it are the first run's two, nothing was raised, and only the
    # run with no Redo on its failed plan said so — once.
    assert len(said(no_redo, PRESSED)) == 2 and no_redo.cards == []
    assert len(said(no_redo, "it shows no Redo to press")) == 1


# ══ the round-robin while Gemini plans: the card only after both presses ═════

def test_the_failed_plan_card_goes_up_only_after_two_redo_presses_left_it_failed(
        round_robin):
    """⭐⭐ Gemini reaches the round-robin still planning, and its plan fails
    there. Gemini's own Redo is pressed twice, 45 seconds apart; the page is
    never reloaded; and only when the second press has had its 45 seconds and
    the plan is still failed does the card go up — in the same words as before.
    Beside it: a Gemini whose plan wait spent both presses — the second just
    before the hand-off — gets no third press, and the card only once that press
    has had its 45 seconds; and a failed plan with no Redo on it gets the card at
    once, as before. Before: the card went up on the first look, with nothing
    pressed."""
    out = round_robin(lambda n: failed_plan(), minutes=10, brief="brief " * 40,
                      entry={"verified": False, "gemini_watch_start": True})
    redos = [t for t, what in out.presses if what == "redo"]
    assert len(redos) == 2 and redos[1] - redos[0] >= 0.75, out.presses
    assert out.loads == [0.0], out.loads
    assert len(out.cards) == 1, out.cards
    at, card = out.cards[0]
    assert card[:2] == ("gemini", "Gemini's plan failed"), card
    assert card[2] == ("Gemini showed: Sorry, something went wrong. Please try your "
                       "request again. Retry starts a fresh chat, or Skip it."), card
    assert at >= redos[1] + 0.75, (at, redos)
    assert _said(out, "Gemini's own Redo, pressed twice, did not bring it back")
    assert out.cua == [] and out.looks == []

    spent = round_robin(lambda n: failed_plan(), minutes=5, brief="brief " * 40,
                        entry={"verified": False, "gemini_watch_start": True,
                               "gemini_plan_redos": 2, "gemini_plan_redo_at": NOW})
    assert spent.presses == [] and len(spent.cards) == 1, (spent.presses, spent.cards)
    assert spent.cards[0][0] >= 0.75, spent.cards

    no_redo = round_robin(lambda n: _without_redo(failed_plan()), minutes=5,
                          brief="brief " * 40,
                          entry={"verified": False, "gemini_watch_start": True})
    assert no_redo.presses == [] and len(no_redo.cards) == 1, (no_redo.presses,
                                                               no_redo.cards)
    assert no_redo.cards[0][0] < 0.75, no_redo.cards
    assert _said(no_redo, "Gemini shows no Redo to press")


def test_a_redo_that_brings_the_plan_back_raises_nothing_and_its_start_is_pressed(
        round_robin):
    """The round-robin's press brings the plan back with 'Start research': the
    watch presses that Start and no card goes up. Before: the card went up and
    the Redo was never pressed."""
    out = round_robin(lambda n: failed_plan(fix=True), minutes=10, brief="brief " * 40,
                      entry={"verified": False, "gemini_watch_start": True})
    assert [what for _t, what in out.presses][:3] == ["redo", "redraft", OURS], out.presses
    assert out.cards == [], out.cards
    assert out.loads == [0.0], out.loads
    assert _said(out, "late 'Start research' appeared — clicked #1/3")


# ══ the research: the refresh sees it on a real page ════════════════════════

def test_a_finished_research_whose_report_never_loaded_is_refreshed_and_collected(
        round_robin):
    """⭐⭐ THE OWNER'S CASE. Gemini finished its research, but the page kept its
    old "Researching 143 websites" view — no completion line, no report, nothing
    moving — until it is reloaded. With this run's real-size brief on the page,
    the twelve-minute refresh reloads it, the report is there, and it is
    collected. Before: the refresh read the first 8,000 characters of the page —
    all brief — never saw the research card, and never reloaded; the page sat
    until the 90-minute limit."""
    def script(n):
        return (page(STALE_RESEARCH, brief=REAL_BRIEF, extra=HIDDEN_STOP) if n == 1
                else finished_report(REAL_BRIEF))

    out = round_robin(script, minutes=40, brief=REAL_BRIEF)
    assert len(out.loads) == 2, out.loads
    assert 12 <= out.loads[1] < 13.5, out.loads
    assert _said(out, "(research showing, no finished report) — refreshing it, #1 of 3"), \
        out.lines[-30:]
    assert len(out.collected) == 1 and out.collected[0] > out.loads[1], out.collected
    assert out.results.get("Gemini", {}).get("status") == "done", out.results
    assert out.cards == [], out.cards


def test_a_research_gemini_started_by_itself_is_refreshed_once_it_shows_but_never_while_it_plans(
        round_robin):
    """⭐⭐ Gemini starts its research by itself, so it reaches the round-robin
    still planning, watched for its 'Start research'. For its first 15 minutes it
    plans — and nothing refreshes it, however quiet. Then its research shows
    ("Researching 143 websites"), the watch lets go, and when that view goes
    stale the refresh reloads it and the finished report is collected.
    Before: with a real-size brief the watch never saw the research card, so it
    never let go, and nothing ever refreshed the research."""
    shown = []

    def script(n):
        return planning(REAL_BRIEF) if n == 1 else finished_report(REAL_BRIEF)

    async def research_shows(minute, pg):
        if minute >= 15 and not shown:
            shown.append(minute)
            await pg.evaluate(
                "(h) => { const r = document.querySelector('model-response');"
                " r.outerHTML = '<model-response><message-content>' + h +"
                " '</message-content></model-response>';"
                " document.querySelector('main').insertAdjacentHTML('beforeend', %s); }"
                % _js_str(HIDDEN_STOP), STALE_RESEARCH)

    out = round_robin(script, minutes=60, brief=REAL_BRIEF,
                      entry={"verified": False, "gemini_watch_start": True},
                      on_minute=research_shows)
    assert shown, "the research never showed"
    assert len(out.loads) == 2, out.loads
    assert out.loads[1] >= 15 + 12, out.loads
    assert _said(out, "Watch-start: research is running"), out.lines[-30:]
    assert len(out.collected) == 1, out.collected
    assert out.cards == [], out.cards


def test_a_research_view_that_stays_stale_is_refreshed_three_times_and_no_more(
        round_robin):
    """The same 12 minutes and the same ceiling of three, on a real page: a
    research view that no reload cures is reloaded at about 12, 24 and 36
    minutes and then left to the stuck check and the time limit. Before: never
    reloaded at all."""
    out = round_robin(lambda n: page(STALE_RESEARCH, brief=REAL_BRIEF, extra=HIDDEN_STOP),
                      minutes=80, brief=REAL_BRIEF)
    reloads = out.loads[1:]
    assert len(reloads) == 3, out.loads
    assert all(b - a >= 12 for a, b in zip([0.0] + reloads, reloads)), reloads
    assert out.collected == []


# ══ one look, between two reads ══════════════════════════════════════════════

class _Reads:
    """A page whose latest turn reads `readings`, one per read (the last one
    repeats). Nothing on it is research, nothing is a 'Start research', and a
    press would be an evaluate this fake refuses."""

    def __init__(self, *readings):
        self.readings, self.pressed = list(readings), []

    async def evaluate(self, script, *a):
        import json
        if script == research._GEMINI_LATEST_TURN_JS:
            r = self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
            return json.dumps(r)
        if script in (research._GEMINI_START_PRESENT_JS,):
            return False
        if script == research._GEMINI_REPLIES_TEXT_JS:
            return ""
        self.pressed.append(script[:40])
        return ""


FAIL_LINE = "Sorry, something went wrong. Please try your request again."


@pytest.mark.parametrize("third, verdict", [
    ({"found": True, "text": "Here is my research plan. Start research?"}, "not_failed"),
    ({"found": False}, "hold"),
], ids=["it-came-back", "unreadable"])
def test_a_plan_that_came_back_or_could_not_be_read_on_the_look_is_not_pressed(
        monkeypatch, third, verdict):
    """The plan read as failed twice, two seconds apart — and on the look that
    would press, it has come back (a plan, not a failure) or cannot be read. It
    is not pressed, no attempt is spent, and no card is called for ('no_redo'
    is the card's answer)."""
    monkeypatch.setattr(research, "_GEMINI_PLAN_FAIL_SETTLE_SEC", 0)
    failed = {"found": True, "text": FAIL_LINE}
    pg, state = _Reads(failed, failed, third), {}
    got = asyncio.run(research._gemini_plan_redo_tick(pg, state, "t"))
    assert got[0] == verdict, got
    assert pg.pressed == [] and state.get("gemini_plan_redos", 0) == 0


# ══ the page script, executed ═══════════════════════════════════════════════

@pytest.mark.skipif(NODE is None, reason="node is required to run page JS")
def test_the_replies_read_leaves_out_the_persons_turns_and_keeps_geminis():
    """The read the refresh and the watch now use, run against a page: Gemini's
    own words are in it, the person's turn is not — so a brief of any size, or a
    brief that itself says "researching 12 sources", cannot hide or fake the
    research card."""
    html = ("<body><nav>Recent chats</nav><main><user-query><div class='query-text'>"
            "Please describe researching 12 sources " + "brief " * 3000 +
            "</div></user-query><model-response><message-content>"
            "Researching 143 websites</message-content></model-response></main></body>")
    out = run_js(spec_from_html(html), research._GEMINI_REPLIES_TEXT_JS)
    text = out["ret"]
    assert "Researching 143 websites" in text
    assert "Please describe" not in text and "brief brief" not in text
    assert "Recent chats" in text
