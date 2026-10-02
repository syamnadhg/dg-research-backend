"""Gemini's plan wait: always on the run's own chat (2026-10-01), and since wave
15 (10-02) never reloaded.

THE OWNER, 2026-09-30: "… checking we are in the right chat …, because Gemini
might drift the chats too." That half stands, and is what this file measures:
nothing on a chat that is not provably the run's is read or pressed, and a chat
Gemini moves the run to is followed.

⛔⛔ THE OTHER HALF WAS REVERSED ON 10-02. The 10-01 refresh ("you should be
refreshing the chat"), the plan re-drafts, the card and the six-minute hand-off
are gone: Gemini starts its research by itself on a timer, and the owner said
"wait for the research without refreshing and then let the research finish".
tests/test_w15_gemini_waits_1002.py measures the wait as it is now; it uses this
file's fixture.

── How it is measured ──────────────────────────────────────────────────────
The REAL `run_phase2` Gemini launch (2C/2D) in headless Chrome, as in
tests/test_gemini_2d_cua_e2e0930.py — except that the tab is a page that can be
navigated: every request it makes is answered by the test (on a `.invalid` host,
so nothing can leave the machine), and each load of a chat address gets the page
the test scripts for that load. So a refresh, a drift to another chat and the
trip back are real navigations. Time is a clock the program's own sleeps move.
"""
import asyncio
import re
import time
from collections import Counter
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

import research
import test_claude_usage_limit_0916 as base

chrome = base.chrome

APP = "http://fixture.invalid/gemini.google.com/app"
OURS, OTHER, NEW = "ours1234abcd", "other5678efgh", "new9876zyxw"

BRIEF = ("Research mandate: the economic history of the Hanseatic League and its "
         "Baltic trade routes between 1300 and 1600. ") * 6
FOREIGN = "Plan a long weekend in Lisbon with museums, tiled churches and food markets."

#: The 10-01 screen at 91 s: a short reply, no plan, no button.
SILENT = "<p>Okay, let me look into that for you.</p>"
#: Gemini's plan with its Start research button. Pressing it removes it (a Start
#: that took) and tells the test which chat it was pressed on.
PLAN = ("<p>Here is my research plan.</p><button aria-label=\"Start research\" "
        "onclick=\"this.remove(); fetch('/__clicked/' + "
        "location.pathname.split('/').pop())\">Start research</button>")
#: A reply holding a control the vision step might press (not Start research).
WITH_BUTTON = "<p>Here is a draft.</p><button>Edit plan</button>"


def page(reply, *, brief=BRIEF, rail=(), extra="", turn=None):
    """One Gemini chat: Gemini's side list, the brief's turn, Gemini's reply
    (`turn` replaces the whole reply turn)."""
    links = "".join(f'<a href="/gemini.google.com/app/{cid}?via=rail">{cid}</a>'
                    for cid in rail)
    turn = turn or (f"<model-response><message-content>{reply}</message-content>"
                    "</model-response>")
    return (f"<html><body><nav>{links}</nav><main><user-query><div class='query-text'>"
            f"{brief}</div></user-query>{turn}{extra}</main></body></html>")


class _Clock:
    def __init__(self):
        self.t = time.time()

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return self.t


class _Stop(Exception):
    """The launch is over; the round-robin after it is not under test."""


@pytest.fixture
def launch(chrome, monkeypatch, tmp_path):
    clock = _Clock()
    t0, hooks = {}, []

    class _FastAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(delay=0, *a, **k):
            clock.t += float(delay or 0)
            if "at" in t0:
                for hook in list(hooks):
                    await hook(clock.t - t0["at"])
            await asyncio.sleep(0)

    def _since():
        return clock.t - t0.get("at", clock.t)

    lines, events, cards, looks, handed, beats = [], [], [], [], [], []

    def _log(m, level="INFO"):
        m = str(m)
        if "--- 2D: Gemini" in m and "at" not in t0:
            t0["at"] = clock.t
        lines.append((_since(), level, m))

    def _emit(name, **k):
        events.append((name, k))
        if name == "pipeline_error" and k.get("agent") == "gemini":
            cards.append((_since(), k))
        if name == "agent_progress" and k.get("agent") == "gemini" and "at" in t0:
            beats.append(_since())

    monkeypatch.setattr(research, "time", clock)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research, "log", _log)
    monkeypatch.setattr(research, "emit_event", _emit)
    monkeypatch.setattr(research, "_p2_run_dir", lambda: tmp_path)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setenv("DG_P2_STAGGER_SEC", "0")
    for var in ("DG_VISION_TIER", "GEMINI_PLAN_WAIT_SEC", "GEMINI_PLAN_ALERT_SEC",
                "GEMINI_PLAN_REFRESH_SEC"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(research, "_AGENT_ERROR_CARD_TS", {})
    monkeypatch.setattr(research, "_pending_decisions", {})
    monkeypatch.setattr(research, "_active_decisions", set())
    monkeypatch.setattr(research, "_active_decision_agents", {})
    ctl = research._controls
    monkeypatch.setattr(ctl, "skipped_agents", set())
    monkeypatch.setattr(ctl, "user_skip_taps", set())
    monkeypatch.setattr(ctl, "auto_skip_reasons", {})
    monkeypatch.setattr(ctl, "cookie_trust_broken", set())
    monkeypatch.setattr(ctl, "hv_blocked", {})
    monkeypatch.setattr(ctl, "hv_auto_skipped", set())
    monkeypatch.setattr(ctl, "pause_event", asyncio.Event())
    monkeypatch.setattr(ctl, "resume_event", asyncio.Event())
    monkeypatch.setattr(ctl, "is_stop", lambda: False)
    monkeypatch.setattr(ctl, "is_pause", lambda: False)
    monkeypatch.setattr(ctl, "pro_warning_acknowledged", True)

    async def _vision(*_a, **k):
        looks.append((_since(), k.get("hotspot_id")))
        return {}

    monkeypatch.setattr(research, "_shadow_observed_cua", _vision)

    async def _round_robin(agents, *a, **k):
        handed.append({n: dict(v) for n, v in agents.items()})
        raise _Stop()

    monkeypatch.setattr(research, "poll_all_agents_round_robin", _round_robin)

    def run(script, *, start=OURS, on_tick=None, app=APP):
        """`script(chat_id, nth_load)` is the page each load of a chat address
        gets; `start` is the chat the brief landed in ("" = Gemini's bare /app)."""
        loads, clicks, urls, opened = Counter(), [], [], []

        async def _answer(route):
            path = urlsplit(route.request.url).path
            if path.startswith("/__clicked/"):
                clicks.append(path.rsplit("/", 1)[1])
                await route.fulfill(status=204, body="")
                return
            m = re.fullmatch(r"/gemini\.google\.com/(?:u/\d+/)?app/?([A-Za-z0-9_-]*)", path)
            if m is None:
                await route.abort()
                return
            loads[m.group(1)] += 1
            urls.append(route.request.url)
            await route.fulfill(status=200, content_type="text/html",
                                body=script(m.group(1), loads[m.group(1)]))

        async def _open(browser, cua_client, url, *a, **k):
            pg = await chrome.ctx.new_page()
            await pg.route("**/*", _answer)
            await pg.goto(f"{app}/{start}" if start else app)
            opened.append(pg)
            return pg, True

        monkeypatch.setattr(research, "start_agent_no_gemini_wait", _open)
        hooks.clear()
        if on_tick is not None:
            async def _hook(elapsed):
                await on_tick(elapsed, opened[-1])

            hooks.append(_hook)

        class _Browser:
            page = None

            async def switch_to_page(self, p):
                self.page = p

            async def screenshot(self):
                return "iVBORw0KGgo="

        try:
            chrome.run(asyncio.wait_for(research.run_phase2(
                _Browser(), None, BRIEF, enabled_agents=["gemini"]), timeout=120))
        except _Stop:
            pass
        finally:
            hooks.clear()
            for pg in opened:
                try:
                    chrome.run(pg.close())
                except Exception:
                    pass
        return SimpleNamespace(lines=lines, events=events, cards=cards, looks=looks,
                               handed=handed, loads=loads, clicks=clicks, urls=urls,
                               beats=beats)

    return run


def said(out, text):
    return [(t, m) for t, _lv, m in out.lines if text in m]


# ⛔⛔ WAVE 15 (10-02): THE REFRESH, THE RE-DRAFTS, THE CARD AND THE SIX-MINUTE
# HAND-OFF ARE GONE, and the tests that pinned them went with them. The owner:
# "wait for the research without refreshing and then let the research finish …
# keep it simple without making it complicated and causing alerts". What the
# wait does now is measured in tests/test_w15_gemini_waits_1002.py; what stays
# true of it — the run's own chat, every time — is measured here.


# ── The right chat, every time ───────────────────────────────────────────────

@pytest.mark.parametrize("how", ["landed_there", "drifted_there"])
def test_a_chat_holding_another_brief_is_never_pressed(launch, how):
    """⭐ Right chat, every time — also before Gemini has given the run's chat its
    address. The tab is on another chat whose plan has its own 'Start research':
    nothing on it is pressed, it is never reloaded, no computer use is pointed at
    it, and nothing is raised."""
    drifted = []

    def script(cid, n):
        return page(PLAN, brief=FOREIGN) if cid == OTHER else page(SILENT)

    async def drift(elapsed, pg):
        if elapsed >= 30 and not drifted:
            drifted.append(elapsed)
            await pg.goto(f"{APP}/{OTHER}")

    if how == "landed_there":
        out = launch(script, start=OTHER)
        assert out.loads == Counter({OTHER: 1}), out.loads
    else:
        out = launch(script, start="", on_tick=drift)
        assert out.loads == Counter({"": 1, OTHER: 1}), out.loads
    assert out.clicks == [], out.clicks
    held = said(out, "holds another brief")
    assert len(held) == 1, held
    assert out.looks == [] and out.cards == []


def test_a_tab_back_on_our_address_is_believed_only_once_it_is_proven(launch):
    """The tab drifts to another chat at 30 s, and at 60 s Gemini takes it back
    to the run's own address — but what loads there now holds another brief. It
    is on our address and still not believed: nothing on it is pressed."""
    moves = []

    def script(cid, n):
        if cid == OTHER:
            return page(SILENT, brief=FOREIGN)
        return page(SILENT) if n == 1 else page(PLAN, brief=FOREIGN)

    async def wander(elapsed, pg):
        if elapsed >= 30 and not moves:
            moves.append(elapsed)
            await pg.goto(f"{APP}/{OTHER}")
        elif elapsed >= 60 and len(moves) == 1:
            moves.append(elapsed)
            await pg.goto(f"{APP}/{OURS}")

    out = launch(script, on_tick=wander)
    assert len(moves) == 2 and out.loads == Counter({OURS: 2, OTHER: 1}), out.loads
    assert out.clicks == [], out.clicks
    assert not said(out, "back on the run's own chat (proven on a later look)")
    assert out.cards == [] and out.looks == []


def test_a_chat_that_never_proves_it_is_ours_is_read_as_before_and_never_reloaded(launch):
    """The tab has an address but its first turn cannot be read: its address is
    never taken as the run's. "Cannot tell" is read as before — not as somebody
    else's chat, even though the page's other text (Gemini's side list here) is
    long enough to judge — and the tab is never loaded again."""
    out = launch(lambda cid, n: page(SILENT, brief="", rail=(OTHER, NEW)), start=OTHER)
    assert out.loads == Counter({OTHER: 1}), out.loads
    assert not said(out, "This run's chat has its address")
    assert not said(out, "holds another brief")
    assert out.cards == []


def test_a_drifted_tab_holding_a_finished_report_is_not_believed(launch):
    """The tab drifts onto another chat whose research has FINISHED. For the rest
    of the wait nothing on it is believed — its report is not taken for this
    run's — and it is neither reloaded nor taken back."""
    from test_gemini_finished_on_its_own_w13 import gemini_page as finished_page
    drifted = []

    def script(cid, n):
        return finished_page() if cid == OTHER else page(SILENT)

    async def drift(elapsed, pg):
        if elapsed >= 155 and not drifted:
            drifted.append(elapsed)
            await pg.goto(f"{APP}/{OTHER}")

    out = launch(script, on_tick=drift)
    assert not said(out, "finished its research on its own")
    assert out.clicks == []
    assert out.loads == Counter({OURS: 1, OTHER: 1}), out.loads


@pytest.mark.parametrize("how", ["page_load", "in_place"])
def test_gemini_moving_the_runs_chat_to_a_new_address_is_followed(launch, how):
    """⭐⭐ THE OWNER'S 10-01 RUN. The brief landed on one address; at 111 s the
    tab moved, and the plan with 'Start research' was on ANOTHER address — which
    holds this run's brief, so it is this run's chat, moved by Gemini. It is
    followed and its Start is pressed, as base did at 115 s."""
    moved = []

    def script(cid, n):
        return page(PLAN) if cid == NEW else page(SILENT)

    async def move(elapsed, pg):
        if elapsed >= 111 and not moved:
            moved.append(elapsed)
            if how == "page_load":
                await pg.goto(f"{APP}/{NEW}")
            else:
                await pg.evaluate(
                    "([p, html]) => { history.pushState(null, '', p);"
                    " document.querySelector('message-content').innerHTML = html; }",
                    [f"/gemini.google.com/app/{NEW}", PLAN])

    out = launch(script, on_tick=move)
    follow = said(out, "Gemini moved this run's chat to a new address — following it")
    assert len(follow) == 1 and 111 <= follow[0][0] < 130, follow
    assert out.clicks == [NEW], out.clicks
    assert out.cards == [] and out.looks == []
    assert out.loads == (Counter({OURS: 1, NEW: 1}) if how == "page_load"
                         else Counter({OURS: 1})), out.loads


def test_a_new_address_holding_a_finished_report_is_not_followed(launch):
    """A retry pastes the same brief, so an earlier attempt's FINISHED chat also
    holds it. Before 'Start research', a report is an earlier run's: the tab is
    not followed there, and that report is not taken for this run's."""
    from test_gemini_finished_on_its_own_w13 import DONE_LINE
    finished = page(f"<p>{DONE_LINE}</p>", extra="<button>Contents</button>"
                    "<button>Share &amp; Export</button><button>Create</button>")
    moved = []

    def script(cid, n):
        return finished if cid == NEW else page(SILENT)

    async def move(elapsed, pg):
        if elapsed >= 111 and not moved:
            moved.append(elapsed)
            await pg.goto(f"{APP}/{NEW}")

    out = launch(script, on_tick=move)
    assert not said(out, "following it")
    assert not said(out, "finished its research on its own")
    assert out.clicks == [], out.clicks
    assert out.loads == Counter({OURS: 1, NEW: 1}), out.loads


def test_the_address_gemini_gives_later_is_the_runs_chat(launch):
    """The brief lands on the bare /app and Gemini gives the chat its address at
    150 s (in place, the way its app does). From then on that is the run's chat,
    and the plan that shows there is started — with no load of it."""
    given = []

    async def assign(elapsed, pg):
        if elapsed >= 150 and not given:
            given.append(elapsed)
            await pg.evaluate(f"() => history.pushState(null, '', '/gemini.google.com/app/{OURS}')")
        if elapsed >= 200 and len(given) == 1:
            given.append(elapsed)
            await pg.evaluate("(h) => { document.querySelector('message-content')"
                              ".innerHTML = h; }", PLAN)

    out = launch(lambda cid, n: page(SILENT), start="", on_tick=assign)
    assert said(out, "This run's chat has its address")
    assert out.loads == Counter({"": 1}), out.loads
    assert out.clicks == [OURS]


def test_a_chat_under_an_account_index_is_the_runs_chat_too(launch):
    """A profile signed in to more than one Google account opens Gemini under
    /u/<n>/app/<id>. That is the run's chat as much as /app/<id> is: its address
    is taken and its plan started."""
    out = launch(lambda cid, n: page(PLAN),
                 app="http://fixture.invalid/gemini.google.com/u/1/app")
    assert said(out, "This run's chat has its address")
    assert out.clicks == [OURS], out.clicks
    assert out.cards == []


# ── Never while something is showing ─────────────────────────────────────────

LONG_PLAN = "<p>" + "Step: read the primary sources and compare them. " * 15 + "</p>"
WORKING = '<button aria-label="Stop response" style="display:none">■</button>'
#: Something on the page still animating, which only the heartbeat's reading
#: sees (it keys on class names; the page reading keys on animation names).
MOVING = ('<style>@keyframes blink{from{opacity:1}to{opacity:.4}}</style>'
          '<div class="animate-dots" style="width:12px;height:12px;'
          'animation:blink 1s infinite">…</div>')


@pytest.mark.parametrize("kind", ["growing", "long_plan", "still_working",
                                  "heartbeat_moving"])
def test_a_page_that_is_moving_or_shows_a_plan_is_never_refreshed(launch, kind):
    """Text that is still growing, a plan already on the page, Gemini's own
    'still working' signal, or something the heartbeat sees moving: the chat is
    left alone."""
    async def grow(elapsed, pg):
        if elapsed < 600:
            await pg.evaluate("() => document.querySelector('message-content')"
                              ".insertAdjacentText('beforeend', ' ..')")

    if kind == "growing":
        out = launch(lambda cid, n: page(SILENT), on_tick=grow)
    elif kind == "long_plan":
        out = launch(lambda cid, n: page(LONG_PLAN))
    elif kind == "still_working":
        out = launch(lambda cid, n: page(SILENT, extra=WORKING))
    else:
        out = launch(lambda cid, n: page(SILENT, extra=MOVING))
        assert said(out, "Gemini's page now reads: nothing running and nothing finished")
    assert out.loads == Counter({OURS: 1}), out.loads
    assert not said(out, "refreshing its chat")


def test_the_tile_hears_from_the_wait_while_the_tab_is_not_provably_ours(launch):
    """The tab drifts to a chat holding another brief at 30 s and stays there.
    Nothing on it is read, but the tile still gets its planning update about every
    fifteen seconds and the log its 'Still waiting' line, to the end of the wait."""
    drifted = []

    async def drift(elapsed, pg):
        if elapsed >= 30 and not drifted:
            drifted.append(elapsed)
            await pg.goto(f"{APP}/{OTHER}")

    out = launch(lambda cid, n: page(SILENT, brief=FOREIGN) if cid == OTHER
                 else page(SILENT), on_tick=drift)
    beats = [t for t in out.beats if t < 600]
    assert beats and beats[-1] > 560, beats[-3:]
    assert all(b - a <= 45 for a, b in zip(beats, beats[1:])), beats
    waits = [t for t, _m in said(out, "Still waiting for Gemini research plan")]
    assert waits and waits[-1] > 580, waits[-3:]
    assert all(b - a <= 45 for a, b in zip(waits, waits[1:])), waits


def test_skip_during_the_wait_still_ends_it(launch):
    """Skip pressed before the plan: the skip is finalized as before, with no card
    and no hand-off."""
    pressed = []

    async def skip(elapsed, pg):
        if elapsed >= 150 and not pressed:
            pressed.append(elapsed)
            research._controls.request_skip_agent("gemini")

    out = launch(lambda cid, n: page(SILENT), on_tick=skip)
    assert said(out, "User skipped Gemini during the plan wait — finalizing skip")
    assert ("agent_skipped", {"phase": 2, "agent": "gemini", "reason": "user_skip"}) \
        in out.events
    assert out.cards == [] and not out.handed
