"""Gemini's plan wait: nothing is raised for ten minutes, and a chat that shows
nothing new is refreshed — always on the run's own chat (2026-10-01).

THE OWNER, 2026-09-30: "In Gemini the planning is taking a little more time now.
Wait for at least 10 minutes in that planning session before raising anything.
And you should be refreshing the chat, and also checking we are in the right chat
while refreshing, because Gemini might drift the chats too."

THE OWNER'S RUN (chat_1790816941167, 10-01):
    18:19:20 [2C] Gemini submission confirmed ✓ (conversation started)
    18:20:57 [2D] Gemini plan stall diag @ 91s: ... its reply: 36 chars, 0 buttons
    18:21:17 [2D] Gemini's page now reads: unreadable (... because of a navigation., at 111s)
    18:21:27 [2D] Gemini's page now reads: a plan with 'Start research' showing (at 121s)
    18:21:30 [2D] Clicked 'Start research' via JS ✓ (confirmed it took)
A fresh load of the chat showed a plan the open page had not. On 09-30 the same
silent screen sat for five minutes and then the card went up.

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


# ── Nothing is raised before ten minutes ─────────────────────────────────────

def test_nothing_is_raised_before_ten_minutes(launch):
    """⭐⭐ The owner's rule. A reply holding a button keeps the vision step, so
    this page measures both: no card and no computer use before 600 s — and both
    still come after it. Before: the card at ~300 s and the vision step with it."""
    out = launch(lambda cid, n: page(WITH_BUTTON), start="")
    assert out.cards, "the couldn't-start card must still go up after the wait"
    assert out.cards[0][0] >= 600, out.cards[0][0]
    assert out.looks, "the vision step must still run after the wait"
    assert out.looks[0][0] >= 600, out.looks
    assert said(out, "Still waiting for Gemini research plan... (0s / 600s)")


def test_three_spent_redrafts_still_wait_the_ten_minutes(launch):
    """⭐ The owner's "before raising anything" includes the evidence arm. The
    plan reads as failed (the owner's captured turn, 09-10) and its Redo never
    re-drafts: all three re-drafts are spent within about four minutes, and the
    card still waits for the ten. Before: the card went up as the third was
    judged."""
    from test_gemini_redraft_0910 import CAPTURED_FAIL_TURN
    # The capture's icon buttons are empty: give Redo a size, as its icon does.
    failed = CAPTURED_FAIL_TURN.replace(
        '<button aria-label="Redo">', '<button aria-label="Redo" style="width:24px;height:24px">')
    out = launch(lambda cid, n: page("", turn=failed))
    spent = said(out, "auto-regenerate exhausted")
    assert len(said(out, "Gemini plan re-draft ")) == 3
    assert spent and spent[0][0] < 300, spent
    assert out.cards and out.cards[0][0] >= 600, out.cards[:1]


def test_the_card_is_never_due_before_the_wait_is_over():
    """Three spent re-drafts no longer card early either: nothing before the wait
    is over. Past it, the evidence arm still counts when the alert second is set
    later than the wait."""
    kw = dict(wait_max_sec=600, alert_sec=600, streaming_recent=False,
              start_clicked=False)
    assert research._gemini_plan_card_due(elapsed=599, regen_capped=True, **kw) is False
    assert research._gemini_plan_card_due(elapsed=600, regen_capped=True, **kw) is True
    assert research._gemini_plan_card_due(elapsed=600, regen_capped=False, **kw) is True
    later = {**kw, "alert_sec": 900}
    assert research._gemini_plan_card_due(elapsed=600, regen_capped=True, **later) is True
    assert research._gemini_plan_card_due(elapsed=600, regen_capped=False, **later) is False


# ── A quiet chat is refreshed ────────────────────────────────────────────────

def test_a_quiet_chat_is_refreshed_and_the_plan_it_shows_is_started(launch):
    """⭐⭐ THE 10-01 RUN, done by the program: two minutes of nothing new, one
    refresh, the plan is there, 'Start research' is pressed — on the run's chat."""
    out = launch(lambda cid, n: page(SILENT if n == 1 else PLAN))
    ref = said(out, "Gemini showed nothing new for 2 min — refreshing its chat (#1)")
    assert len(ref) == 1, said(out, "refreshing")
    assert 120 <= ref[0][0] < 140, ref
    back = said(out, "back on the run's own chat")
    assert back and "a plan with 'Start research' showing" in back[0][1], back
    assert said(out, "Clicked 'Start research' via JS ✓")
    assert out.clicks == [OURS]
    assert out.loads == Counter({OURS: 2})
    assert out.cards == [] and out.looks == []


def test_a_chat_is_refreshed_at_most_once_per_two_minutes(launch):
    """A plan that never comes: one refresh per two minutes of nothing new, never
    faster, and the card after ten minutes as before."""
    out = launch(lambda cid, n: page(SILENT))
    times = [t for t, _m in said(out, "refreshing its chat (#")]
    assert len(times) >= 3, times
    assert all(b - a >= 120 for a, b in zip(times, times[1:])), times
    assert out.loads[OURS] == len(times) + 1
    assert out.cards and out.cards[0][0] >= 600
    # The 10-01 drafting screen (nothing running, no Stop) is not "still working".
    assert not said(out, "Handing off to the round-robin")


# ── The right chat, every time ───────────────────────────────────────────────

@pytest.mark.parametrize("in_side_list", [True, False])
def test_a_tab_that_drifted_goes_back_to_the_runs_chat(launch, in_side_list):
    """⭐⭐ "Gemini might drift the chats." At 30 s the tab is on another chat
    holding a plan of its own. Nothing is pressed there and it is never reloaded:
    the tab goes back to ours — through Gemini's side list when the chat is in
    it, by its address when not — and the plan there is started.
    Before: the other chat's 'Start research' was pressed."""
    drifted = []

    def script(cid, n):
        if cid == OTHER:
            # Gemini's side list holds every chat, the one on screen first.
            return page(PLAN, brief=FOREIGN, rail=(OTHER, OURS) if in_side_list else ())
        return page(SILENT if n == 1 else PLAN)

    async def drift(elapsed, pg):
        if elapsed >= 30 and not drifted:
            drifted.append(elapsed)
            await pg.goto(f"{APP}/{OTHER}")

    out = launch(script, on_tick=drift)
    assert out.clicks == [OURS], out.clicks
    assert out.loads == Counter({OURS: 2, OTHER: 1}), out.loads
    back = said(out, "drifted to another chat — going back to ours (#1;")
    assert len(back) == 1 and back[0][0] < 50, back
    assert said(out, "back on the run's own chat")
    assert not said(out, "refreshing its chat")
    assert ("via=rail" in out.urls[-1]) is in_side_list, out.urls


def test_no_refresh_until_gemini_gives_the_chat_an_address(launch):
    """Refreshing Gemini's bare /app would lose the chat: it is never done. The
    wait says why once, and the card still comes after ten minutes."""
    out = launch(lambda cid, n: page(SILENT), start="")
    assert out.loads == Counter({"": 1}), out.loads
    held = said(out, "not refreshing")
    assert len(held) == 1 and 120 <= held[0][0] < 140, held
    assert "has not given this chat its address yet" in held[0][1]
    assert out.cards and out.cards[0][0] >= 600


def test_a_chat_that_never_proves_it_is_ours_is_never_refreshed(launch):
    """The tab has an address but its first turn cannot be read: its address is
    never taken as the run's, so it is never refreshed and the wait says why.
    "Cannot tell" is read as before — not as somebody else's chat, even though the
    page's other text (Gemini's side list here) is long enough to judge."""
    out = launch(lambda cid, n: page(SILENT, brief="", rail=(OTHER, NEW)), start=OTHER)
    assert out.loads == Counter({OTHER: 1}), out.loads
    held = said(out, "not refreshing")
    assert len(held) == 1 and "could not be proven to be this run's" in held[0][1], held
    assert not said(out, "This run's chat has its address")
    assert not said(out, "holds another brief")


@pytest.mark.parametrize("how", ["landed_there", "drifted_there"])
def test_a_chat_holding_another_brief_is_never_pressed_before_the_address_is_taken(
        launch, how):
    """⭐ Right chat, every time — also before Gemini has given the run's chat its
    address. The tab is on another chat whose plan has its own 'Start research':
    nothing on it is pressed, no computer use is pointed at it, and the card comes
    at ten minutes. Before: that chat's Start was pressed."""
    drifted = []

    def script(cid, n):
        return page(PLAN, brief=FOREIGN) if cid == OTHER else page(SILENT)

    async def drift(elapsed, pg):
        if elapsed >= 30 and not drifted:
            drifted.append(elapsed)
            await pg.goto(f"{APP}/{OTHER}")

    if how == "landed_there":
        out = launch(script, start=OTHER)
    else:
        out = launch(script, start="", on_tick=drift)
    assert out.clicks == [], out.clicks
    held = said(out, "holds another brief")
    assert len(held) == 1, held
    assert out.looks == [] and said(out, "no computer use on it")
    assert out.cards and out.cards[0][0] >= 600, out.cards[:1]


def test_a_drifted_tab_is_not_believed_while_it_waits_to_go_back(launch):
    """The tab drifts 30 s after a refresh, onto another chat whose research has
    FINISHED. A load is not allowed again until two minutes after the refresh, and
    for that whole time nothing on the other chat is believed — its report is not
    taken for this run's. Then the tab goes back and our plan is started."""
    from test_gemini_finished_on_its_own_w13 import gemini_page as finished_page
    drifted = []

    def script(cid, n):
        if cid == OTHER:
            return finished_page()
        return page(PLAN if n >= 3 else SILENT)

    async def drift(elapsed, pg):
        if elapsed >= 155 and not drifted:
            drifted.append(elapsed)
            await pg.goto(f"{APP}/{OTHER}")

    out = launch(script, on_tick=drift)
    ref = said(out, "refreshing its chat (#1)")
    back = said(out, "going back to ours (#2;")
    assert ref and back, said(out, "[2D]")
    assert back[0][0] - ref[0][0] >= 120, (ref, back)
    assert not said(out, "finished its research on its own")
    assert out.clicks == [OURS]
    assert out.loads == Counter({OURS: 3, OTHER: 1}), out.loads


@pytest.mark.parametrize("how", ["page_load", "in_place"])
def test_gemini_moving_the_runs_chat_to_a_new_address_is_followed(launch, how):
    """⭐⭐ THE OWNER'S 10-01 RUN. The brief landed on one address; at 111 s the
    tab moved, and the plan with 'Start research' was on ANOTHER address — which
    holds this run's brief, so it is this run's chat, moved by Gemini. It is
    followed and its Start is pressed, as base did at 115 s. Before this fix it
    was called a drift: the tab was taken back to the old address, Start was
    never pressed, and the card went up at ten minutes."""
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
    assert not said(out, "drifted to another chat")
    assert out.cards == [] and out.looks == []
    assert out.loads == (Counter({OURS: 1, NEW: 1}) if how == "page_load"
                         else Counter({OURS: 1})), out.loads


def test_a_refresh_that_gemini_answers_at_a_new_address_is_followed(launch):
    """The run's chat is refreshed and Gemini's app answers the load at a new
    address (it rewrites the address as the page loads), holding this run's brief
    and its plan. The refresh believes it there and then, and its Start is
    pressed. Before: the refresh called the page not the run's own, and every
    later look dragged the tab back to the old address."""
    moved = ("<script>history.replaceState(null, '', "
             f"'/gemini.google.com/app/{NEW}')</script>")
    out = launch(lambda cid, n: page(SILENT) if n == 1 else page(PLAN, extra=moved))
    assert said(out, "refreshing its chat (#1)")
    follow = said(out, "following it")
    assert len(follow) == 1, follow
    back = said(out, "back on the run's own chat")
    assert back and "a plan with 'Start research' showing" in back[0][1], back
    assert not said(out, "not provably the run's own chat")
    assert out.clicks == [NEW], out.clicks
    assert out.cards == [] and out.looks == []


def test_a_new_address_holding_a_finished_report_is_not_followed(launch):
    """A retry pastes the same brief, so an earlier attempt's FINISHED chat also
    holds it. Before 'Start research', a report is an earlier run's: the tab is
    not followed there, that report is not taken for this run's, and the tab goes
    back to the run's own chat, where the plan is started."""
    from test_gemini_finished_on_its_own_w13 import DONE_LINE
    finished = page(f"<p>{DONE_LINE}</p>", extra="<button>Contents</button>"
                    "<button>Share &amp; Export</button><button>Create</button>")
    moved = []

    def script(cid, n):
        if cid == NEW:
            return finished
        return page(SILENT if n == 1 else PLAN)

    async def move(elapsed, pg):
        if elapsed >= 111 and not moved:
            moved.append(elapsed)
            await pg.goto(f"{APP}/{NEW}")

    out = launch(script, on_tick=move)
    assert not said(out, "following it")
    assert not said(out, "finished its research on its own")
    assert said(out, "drifted to another chat — going back to ours (#1;")
    assert out.clicks == [OURS], out.clicks
    assert out.loads == Counter({OURS: 2, NEW: 1}), out.loads


def test_our_own_redraft_press_restarts_the_quiet_clock(launch):
    """A failed plan whose Redo is pressed: the page shows nothing new afterwards,
    but it is not refreshed until two minutes after the LAST press — a refresh
    must never cut into a re-draft we just asked for."""
    from test_gemini_redraft_0910 import CAPTURED_FAIL_TURN
    failed = CAPTURED_FAIL_TURN.replace(
        '<button aria-label="Redo">', '<button aria-label="Redo" style="width:24px;height:24px">'
    ).replace('<gem-icon-button data-test-id="share-and-export-menu-button">\n'
              '            <button aria-label="Share &amp; export"></button></gem-icon-button>', "")
    out = launch(lambda cid, n: page("", turn=failed))
    presses = [t for t, _m in said(out, "Gemini plan re-draft ")]
    ref = said(out, "refreshing its chat (#1)")
    assert len(presses) == 3 and ref, (presses, said(out, "refreshing"))
    assert ref[0][0] - presses[-1] >= 120, (presses, ref)


def test_the_address_gemini_gives_later_is_the_one_refreshed(launch):
    """The brief lands on the bare /app and Gemini gives the chat its address at
    150 s (in place, the way its app does). From then on that is the run's chat:
    the refresh goes to it and its plan is started."""
    given = []

    async def assign(elapsed, pg):
        if elapsed >= 150 and not given:
            given.append(elapsed)
            await pg.evaluate(f"() => history.pushState(null, '', '/gemini.google.com/app/{OURS}')")

    out = launch(lambda cid, n: page(PLAN if cid == OURS else SILENT), start="",
                 on_tick=assign)
    assert said(out, "This run's chat has its address")
    assert said(out, "refreshing its chat (#1)")
    assert out.loads == Counter({"": 1, OURS: 1}), out.loads
    assert out.clicks == [OURS]


@pytest.mark.parametrize("theirs", [PLAN, WITH_BUTTON], ids=["plan", "a_button"])
def test_a_refreshed_page_that_is_not_provably_ours_is_never_clicked(launch, theirs):
    """After the refresh the address is ours but the chat holds another brief.
    Nothing on it is pressed — not by the wait, not by the recovery after it —
    and no computer use is pointed at it; the card comes at ten minutes.
    (Two pages, because the recovery stands itself down on a pressable Start —
    the one with only a button is where it would otherwise act.)"""
    out = launch(lambda cid, n: page(SILENT) if n == 1 else page(theirs, brief=FOREIGN))
    assert out.clicks == [], out.clicks
    assert said(out, "not provably the run's own chat")
    assert not said(out, "back on the run's own chat")
    assert out.looks == [], out.looks
    assert said(out, "no computer use on it")
    assert out.cards and out.cards[0][0] >= 600
    assert 2 <= out.loads[OURS] <= 6, out.loads


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
    left alone (until the wait ends, or a moving page is handed off)."""
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
        # The page reading itself calls this page still — only the heartbeat
        # holds the refresh off.
        assert said(out, "Gemini's page now reads: nothing running and nothing finished")
    assert out.loads == Counter({OURS: 1}), out.loads
    assert not said(out, "refreshing its chat")


#: The 10-01 crash retry's screen: Gemini's 'Stop response' button showing, and a
#: short reply that does not change (171 characters from 0 s to the card at 306 s).
VISIBLE_STOP = '<button aria-label="Stop response" style="width:24px;height:24px">■</button>'
STILL_REPLY = "<p>" + "I'm researching the import rules and the breeding sources now. " * 2 + "</p>"


def test_a_visible_stop_hands_gemini_off_at_six_minutes(launch):
    """⭐ The 10-01 crash retry: Gemini's own Stop was showing for the whole wait
    (very likely its research, already running) and the heartbeat's stop test
    misses that button. It is Gemini still working: #953 hands it to the
    round-robin at six minutes, with the late-Start watch armed — no card, no
    computer use, no refresh. Before: the card at ten minutes, then the ladder,
    and ChatGPT and Claude unpolled until about sixteen."""
    out = launch(lambda cid, n: page(STILL_REPLY, extra=VISIBLE_STOP))
    hand = said(out, "Handing off to the round-robin")
    assert len(hand) == 1 and 360 <= hand[0][0] < 380, hand
    assert out.cards == [] and out.looks == [] and out.clicks == []
    assert out.loads == Counter({OURS: 1}), out.loads
    assert out.handed and out.handed[0]["Gemini"]["gemini_watch_start"] is True


def test_a_stop_read_on_a_tab_no_longer_believed_does_not_count(launch):
    """The run's chat showed its Stop, then the tab went to another chat and
    every load after it is not provably ours. The last reading from our chat is
    not news from the tab now: no hand-off as though Gemini were still working,
    and the card comes at ten minutes."""
    drifted = []

    def script(cid, n):
        if cid == OTHER:
            return page(SILENT, brief=FOREIGN)
        return page(STILL_REPLY, extra=VISIBLE_STOP) if n == 1 else page(SILENT, brief=FOREIGN)

    async def drift(elapsed, pg):
        if elapsed >= 100 and not drifted:
            drifted.append(elapsed)
            await pg.goto(f"{APP}/{OTHER}")

    out = launch(script, on_tick=drift)
    assert said(out, "going back to ours (#1;")
    assert not said(out, "Handing off to the round-robin")
    assert out.cards and out.cards[0][0] >= 600, out.cards[:1]


def test_a_shorter_wait_set_by_hand_still_cards_where_it_gives_up(launch, monkeypatch):
    """GEMINI_PLAN_WAIT_SEC set to five minutes on its own: the card still goes
    up where that wait gives up. Before: the alert stayed at ten minutes, so the
    only card was the ladder's, at about eleven."""
    monkeypatch.setenv("GEMINI_PLAN_WAIT_SEC", "300")
    out = launch(lambda cid, n: page(WITH_BUTTON), start="")
    assert out.cards and 300 <= out.cards[0][0] < 330, out.cards[:1]


def test_the_tile_hears_from_the_wait_while_the_tab_is_not_provably_ours(launch):
    """After a refresh the run's chat cannot be proven, for the rest of the wait.
    Nothing on it is read, but the tile still gets its planning update about every
    fifteen seconds and the log its 'Still waiting' line. Before: both stopped
    after the refresh until the wait was over."""
    out = launch(lambda cid, n: page(SILENT) if n == 1 else page(SILENT, brief=FOREIGN))
    assert said(out, "not provably the run's own chat")
    beats = [t for t in out.beats if t < 600]
    assert beats and beats[-1] > 560, beats[-3:]
    assert all(b - a <= 45 for a, b in zip(beats, beats[1:])), beats
    waits = [t for t, _m in said(out, "Still waiting for Gemini research plan")]
    assert waits and waits[-1] > 580, waits[-3:]
    assert all(b - a <= 45 for a, b in zip(waits, waits[1:])), waits


def test_a_chat_under_an_account_index_is_refreshed_too(launch):
    """A profile signed in to more than one Google account opens Gemini under
    /u/<n>/app/<id>. That is the run's chat as much as /app/<id> is: it is
    refreshed and its plan started. Before: it was read as having no address,
    so it was never refreshed and the card went up at ten minutes."""
    out = launch(lambda cid, n: page(SILENT if n == 1 else PLAN),
                 app="http://fixture.invalid/gemini.google.com/u/1/app")
    assert said(out, "This run's chat has its address")
    assert said(out, "refreshing its chat (#1)")
    assert out.clicks == [OURS], out.clicks
    assert out.cards == []


def test_an_auto_started_gemini_is_handed_off_untouched(launch):
    """#953: Gemini started by itself — its Start reads disabled and it is
    streaming. No press, no refresh, no card: it goes to the round-robin."""
    auto = PLAN.replace('aria-label="Start research" ', 'aria-label="Start research" disabled ')
    out = launch(lambda cid, n: page(auto, extra='<div data-is-streaming="true">'
                                                 'Researching 12 websites</div>'))
    assert said(out, "Handing off to the round-robin")
    assert out.clicks == [] and out.cards == [] and out.looks == []
    assert out.loads == Counter({OURS: 1})
    assert out.handed and out.handed[0]["Gemini"]["verified"] is False


def test_skip_during_the_wait_still_ends_it(launch):
    """Skip pressed after a refresh, before the plan: the skip is finalized as
    before, with no card and no hand-off."""
    pressed = []

    async def skip(elapsed, pg):
        if elapsed >= 150 and not pressed:
            pressed.append(elapsed)
            research._controls.request_skip_agent("gemini")

    out = launch(lambda cid, n: page(SILENT), on_tick=skip)
    assert said(out, "refreshing its chat (#1)")
    assert said(out, "User skipped Gemini during the plan wait — finalizing skip")
    assert ("agent_skipped", {"phase": 2, "agent": "gemini", "reason": "user_skip"}) \
        in out.events
    assert out.cards == [] and not out.handed


# ── The two small rules, at their edges ──────────────────────────────────────

def test_quiet_means_nothing_running_a_short_reply_and_no_growth():
    q = research._gemini_plan_page_quiet
    calm = "no_done_marker (trio/completion-text/Share & Export all missing)"
    assert q(calm, reply_found=True, reply_len=36, last_reply_len=36) is True
    assert q(calm, reply_found=True, reply_len=37, last_reply_len=36) is False
    assert q(calm, reply_found=False, reply_len=0, last_reply_len=0) is False
    cap = research._GEMINI_PLAN_FAIL_MAX_CHARS
    assert q(calm, reply_found=True, reply_len=cap, last_reply_len=cap) is True
    assert q(calm, reply_found=True, reply_len=cap + 1, last_reply_len=cap + 1) is False
    for busy in ("running_hidden_stop_btn (text=0)", "start_research_btn_visible (pre-research)",
                 "detect_error: boom", "stop_btn_present (text=0)", ""):
        assert q(busy, reply_found=True, reply_len=36, last_reply_len=36) is False, busy


def test_a_refresh_waits_for_two_quiet_minutes_and_two_since_the_last():
    due = research._gemini_plan_refresh_due
    assert due(1000.0, quiet_since=880.0, last_refresh_at=0.0, window_sec=120) is True
    assert due(1000.0, quiet_since=881.0, last_refresh_at=0.0, window_sec=120) is False
    assert due(1000.0, quiet_since=0.0, last_refresh_at=880.0, window_sec=120) is True
    assert due(1000.0, quiet_since=0.0, last_refresh_at=881.0, window_sec=120) is False
    assert due(1000.0, quiet_since=0.0, last_refresh_at=0.0, window_sec=0) is False
    assert research._GEMINI_PLAN_REFRESH_SEC == 120
