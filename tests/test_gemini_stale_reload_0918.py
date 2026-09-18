"""The stale deep research reloads itself — a BOUNDED CADENCE (wave 10, 09-18).

⛔⛔ WHAT THE OWNER REPORTED, AND WHY IT IS NOT A DETECTOR. "after Start Research
we should be able to refresh if the research is stale … it's getting stuck in
working phase, sometimes or mostly." Today that is cured only by the owner
noticing and refreshing by hand.

There is no stall detector to build on this screen, and a fix that claims one is
lying twice over:

  · the growth clock advances only on `partial_text_len` / `observer_text_len` /
    `sources`, and Gemini's reader does not see the deep-research surface — so
    "no growth for N minutes" is TRUE of a perfectly healthy Gemini research
    (the 2026-08-19 e2e tripped the no-growth arbiter twice while Gemini
    researched happily);
  · and every positively-read in-flight marker inherits that blindness. The only
    one in the tree, `_gemini_research_started`, is a PRESENCE signal: the
    "Researching N websites" card stays in the transcript whether the run is
    alive or wedged. "Named marker + bound" is a wall-clock cadence wearing a
    detector's name.

⭐⭐ WHAT MAKES A CADENCE ACCEPTABLE IS THAT PRECISION IS NOT LOAD-BEARING. The
research runs PLATFORM-SIDE and the tab is only a view onto it, and the owner
verified on 2026-09-16 that a post-Start reload comes back into the same
conversation. A reload on a HEALTHY run costs a page load, not the run. The one
destruction path left is the 2026-07 land-on-the-empty-home — which is why every
reload here is followed by an IDENTITY proof, never a liveness one: the liveness
prover the two existing rescues use returns True on Gemini's blank `/app` home
while the SPA hydrates, i.e. "rescued" on the exact failure it exists to catch.

⛔ C IS MEASURED, NOT GUESSED. Instrument: `run_analytics.json` — the per-device
phase-duration record `record_phase_duration` appends to and `load_analytics`
averages into `_phase_averages`. Read 2026-09-18: 40 completed Phase-2 records,
fastest 10.5 min, median 24.0, mean 29.4, p90 36.4 (nearest rank), slowest
101.2. All forty are simulated below, not two of them: the first cut of this
file pinned 10.5 and 24.0, the only two durations that give 0 and 1 reloads, and
called the result "at most one page load". The record says otherwise — 19 of the
40 healthy runs pay two or more, p90 pays three and the slowest paid EIGHT —
which is why the cadence now carries a ceiling as well as a window.

⛔⛔ AND THE CADENCE MUST NEVER COST THE OWNER THE STUCK CARD. C is 12 minutes,
STUCK_NO_GROWTH_SEC is 15, so a tick that rewinds `last_growth_time` puts the
growth clock permanently out of the arbiter's reach and a wedged Gemini runs
silently to the 90-minute hard cap — the lane disabling the only thing that
reports the symptom it was built for. This tick touches that clock on NO
verdict, and the wedged-run simulations below drive the real tick at the real
30-second poll interval to prove the card still fires at ~15.5 minutes.
"""

from __future__ import annotations

import ast
import asyncio
import collections
import inspect
import json
import os
import re
import sys
import textwrap
import time as _real_time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research  # noqa: E402


TOPIC = ("Solid-state sodium-ion cathodes: 2026 pilot lines, cycle-life data "
         "and the cobalt-free cost curve")
BRIEF = f"# Research Brief\n\n{TOPIC}\n\nProduce a comparative report."
CONVO = "https://gemini.google.com/app/c7d9e10ab2f34"
CONVO_ID = "c7d9e10ab2f34"
HOME = "https://gemini.google.com/app"

# Gemini's own chrome, which is what a blank home reads as while the SPA
# hydrates — long enough to clear the minimum-evidence threshold and containing
# none of this run's brief. This string is the whole reason the prover is
# identity-based rather than liveness-based.
CHROME = ("New chat Recent Gems Settings & help Upgrade Gemini Advanced "
          "Explore Gems Activity Help Send feedback About Privacy Terms")
CARD = "Researching 41 websites"
DONE = "I've completed your research. Feel free to ask me follow-up questions."

POLL_TICK = 30.0          # the Phase-2 round-robin poll interval


@pytest.fixture
def no_waiting(monkeypatch):
    """Collapse the real render/settle waits. The code under test paces itself
    against a live SPA; the fakes here mount instantly, so the only thing the
    sleeps buy a test is wall-clock. Nothing decides anything on a timer."""
    async def _instant(_secs):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


# ════════════════════════════════════════════════════════════════════════════
# The bound — a pure function, so every clause can be taken away one at a time
# ════════════════════════════════════════════════════════════════════════════

def _due(**over):
    """A tick on which the cadence SHOULD fire, minus whatever the caller
    overrides. Every test below removes exactly one reason."""
    kw = dict(research_started_at=1_000_000.0, last_reload_at=0.0,
              in_conversation=True, card_present=True, completion_seen=False,
              have_identity_brief=True, no_growth_secs=3600.0,
              window_sec=600.0)
    kw.update(over)
    now = kw.pop("now", 1_000_000.0 + 3600.0)
    return research._gemini_stale_reload_due(now, **kw)


def test_a_flat_post_start_research_tab_is_due_for_a_reload():
    assert _due() is True


def test_the_bare_home_is_never_reloaded():
    """A reload of `/app` restores nothing, and a `goto` of a conversation URL
    lands there — the 2026-07 finding, which still holds."""
    assert _due(in_conversation=False) is False


def test_without_this_runs_brief_the_cadence_refuses_to_fire_at_all():
    """⛔⛔ THE ONE WAY THIS BRANCH COULD DESTROY THE RUN IT IS SAVING. With no
    brief the identity prover can never return True, so every reload would fall
    through to adoption — whose own failure path walks the tab out to the bare
    home. No brief, no cadence."""
    assert _due(have_identity_brief=False) is False


def test_a_tab_with_no_research_card_is_left_alone():
    assert _due(card_present=False) is False


def test_a_finished_research_is_left_alone():
    assert _due(completion_seen=True) is False


def test_the_plan_draft_window_never_meets_a_reload():
    """Past Start by a FULL window, not merely past Start: the plan-draft
    window has its own machinery (the kickoff nudges, the late-Start watch).

    ⛔ THE OTHER TWO CLOCKS ARE HELD WIDE OPEN HERE ON PURPOSE. The first draft
    of this test let the growth clock do the refusing, so deleting the
    past-Start clause left it passing — a pin that measures nothing."""
    started = 1_000_000.0
    wide = dict(research_started_at=started, last_reload_at=started - 5_000.0,
                no_growth_secs=9_999.0)
    assert _due(now=started + 599.0, **wide) is False
    assert _due(now=started + 600.0, **wide) is True
    # And a research that never started at all, however long the tab has sat.
    assert _due(now=started + 9_999.0, research_started_at=0.0,
                last_reload_at=started - 5_000.0, no_growth_secs=9_999.0) is False


def test_a_second_reload_inside_the_window_is_refused():
    """The bound IS the feature — without it a wedged tab is reloaded on every
    30-second tick."""
    started, reloaded = 1_000_000.0, 1_000_500.0
    assert _due(now=reloaded + 599.0, research_started_at=started,
                last_reload_at=reloaded) is False
    assert _due(now=reloaded + 600.0, research_started_at=started,
                last_reload_at=reloaded) is True


def test_a_growth_clock_that_moved_recently_suppresses_the_reload():
    """The cheap extra AND. It is blind on this screen, so it can only ever
    SUPPRESS a reload — never justify one."""
    assert _due(no_growth_secs=599.0) is False


def test_a_zero_window_turns_the_cadence_off_completely():
    assert _due(window_sec=0) is False
    assert _due(window_sec=-1) is False


# ⛔⛔ THE WHOLE RECORD, NOT TWO FLATTERING POINTS FROM IT. Every completed
# Phase-2 duration in `run_analytics.json` on 2026-09-18, in minutes, sorted
# (n=40 — the same 40 the window C was derived from: min 10.5, median 24.0,
# mean 29.4, p90 36.4 by nearest rank, max 101.2). The first cut of this file
# simulated exactly two of them, 10.5 and 24.0, which are the ONLY two that give
# 0 and 1 — and 24.0 gives 1 only because the simulation loop excludes its
# endpoint, so 24.5 already gives 2. Pinning those two pinned the boundary that
# flatters the claim. The distribution below is the claim.
PHASE2_MINUTES = (
    10.5, 16.9, 17.3, 17.7, 17.7, 18.4, 18.6, 18.8, 19.3, 20.3,
    21.0, 21.5, 22.4, 22.4, 22.9, 23.0, 23.4, 23.8, 23.9, 24.0,
    24.0, 24.3, 24.4, 24.5, 24.6, 25.6, 25.6, 25.9, 29.6, 29.9,
    30.9, 30.9, 32.3, 34.3, 35.3, 36.4, 53.0, 63.4, 96.7, 101.2,
)


def _fires_over(run_seconds: float, *, cap: "int | None" = None) -> int:
    """How many times the cadence fires across a healthy run of this length,
    polled at the real Phase-2 tick, with the default measured window.

    `cap=None` uses the SHIPPED ceiling, i.e. what a run actually pays. Pass a
    large cap to see the raw rate the ceiling exists to stop.
    """
    start = 1_000_000.0
    last_reload = 0.0
    fires = 0
    t = start
    while t < start + run_seconds:
        if research._gemini_stale_reload_due(
                t, research_started_at=start, last_reload_at=last_reload,
                in_conversation=True, card_present=True, completion_seen=False,
                have_identity_brief=True, reloads_so_far=fires,
                # From `start`, never from the last reload: the tick does not
                # touch the growth clock, so a reload does not reset it.
                no_growth_secs=t - start,
                **({} if cap is None else {"max_reloads": cap})):
            fires += 1
            last_reload = t
        t += POLL_TICK
    return fires


def _spread(*, cap: "int | None") -> dict:
    """reloads → how many of the 40 recorded healthy runs pay that many."""
    return dict(collections.Counter(
        _fires_over(m * 60, cap=cap) for m in PHASE2_MINUTES))


def test_the_fastest_healthy_research_on_record_is_never_reloaded():
    """10.5 min is the shortest completed Phase 2 in `run_analytics.json`
    (n=40). C sits ABOVE it on purpose, so the quickest healthy run finishes
    without ever paying a page load."""
    assert _fires_over(10.5 * 60) == 0


def test_what_the_cadence_really_costs_across_the_whole_record():
    """⛔ THE COST IS AT THE TAIL, AND THE NOTE MUST SAY SO. Uncapped, the 40
    recorded healthy runs pay 76 reloads between them: 19 of the 40 pay two or
    more, p90 pays three and the two slowest pay EIGHT. The median pays one —
    and only just: half a minute past the median it is two. Every number here
    is the shipped predicate's own answer over the real record."""
    raw = _spread(cap=10_000)
    assert raw == {0: 1, 1: 20, 2: 14, 3: 1, 4: 1, 5: 1, 8: 2}
    assert sum(k * v for k, v in raw.items()) == 76
    assert sum(v for k, v in raw.items() if k >= 2) == 19
    # The median, and the half-minute that undoes the "at most one" claim.
    assert _fires_over(24.0 * 60, cap=10_000) == 1
    assert _fires_over(24.5 * 60, cap=10_000) == 2
    # p90 (36.4 min, nearest rank) and the slowest run on record.
    assert _fires_over(36.4 * 60, cap=10_000) == 3
    assert _fires_over(101.2 * 60, cap=10_000) == 8


def test_the_ceiling_stops_the_tail_and_costs_the_record_nothing_else():
    """⛔⛔ A CADENCE WITHOUT A CEILING IS THE `_ARBITER_MAX_WORKING_RESETS`
    LESSON REBUILT. Three sits ABOVE p90, so not one of the 40 recorded healthy
    runs loses a reload it would have used — only the 4/5/8 tail is cut, and a
    tab three reloads did not cure belongs to the stuck arbiter, not to a
    fourth reload."""
    shipped = _spread(cap=None)
    assert shipped == {0: 1, 1: 20, 2: 14, 3: 5}
    assert max(shipped) == research._GEMINI_STALE_RELOAD_MAX == 3
    assert _fires_over(101.2 * 60) == 3
    # Below p90 nothing moved: the ceiling is a tail cut, not a trim.
    for minutes in PHASE2_MINUTES:
        if minutes <= 36.4:
            assert _fires_over(minutes * 60) == _fires_over(minutes * 60, cap=10_000)


def test_a_spent_budget_refuses_every_later_tick():
    """The ceiling is part of the BOUND — one clause among the ANDs, taken away
    like any other, and fail-closed: a zero or negative cap turns the cadence
    off rather than turning it loose."""
    assert _due(reloads_so_far=2, max_reloads=3) is True
    assert _due(reloads_so_far=3, max_reloads=3) is False
    assert _due(reloads_so_far=9, max_reloads=3) is False
    assert _due(reloads_so_far=0, max_reloads=0) is False
    assert _due(reloads_so_far=0, max_reloads=-1) is False


def test_the_window_is_the_measured_twelve_minutes():
    """Changing this is changing a measurement — re-derive it from
    `run_analytics.json` and move the simulations above with it."""
    assert research._GEMINI_STALE_RELOAD_SEC == 12 * 60


# ════════════════════════════════════════════════════════════════════════════
# The reads
# ════════════════════════════════════════════════════════════════════════════

def test_the_conversation_id_comes_from_the_url_and_not_the_dom():
    assert research._gemini_convo_url_id(CONVO) == CONVO_ID
    assert research._gemini_convo_url_id(CONVO + "?hl=en") == CONVO_ID
    assert research._gemini_convo_url_id(HOME) == ""
    assert research._gemini_convo_url_id("https://gemini.google.com/") == ""
    assert research._gemini_convo_url_id("") == ""


def test_the_deleted_897a_recovery_subsystem_stayed_deleted():
    """The cadence did NOT restore the periodic reload's helpers — it proves
    identity instead of presence, and recovers through the sidebar hunt that
    already exists rather than growing a second copy of one."""
    for sym in ("_gemini_recover_if_empty", "_gemini_reopen_from_sidebar",
                "_gemini_conversation_present", "_gemini_conversation_id",
                "_GEMINI_CONVERSATION_PRESENT_JS"):
        assert not hasattr(research, sym), f"{sym} came back with the reload"


class _Tab:
    """A Gemini tab. Answers the three page scripts this lane drives, records
    every navigation, and can be told to land somewhere else on reload."""

    def __init__(self, url=CONVO, body="", turn=None, state="pre_start"):
        self._url = url
        self.body = body
        self.turn = turn            # None → the ownership read falls to the body
        self.state = state
        self.reloads = 0
        self.reload_raises = False
        self.on_reload = None
        self.gotos = []
        self.fronted = 0
        self.observer_injected = False
        self.exposed = []
        self.context = None
        self.titles = []            # what the rail's Recent list reads back
        self.on_click = None        # where a sidebar entry click routes us

    @property
    def url(self):
        return self._url

    def land(self, url, *, body="", turn=None):
        self._url, self.body, self.turn = url, body, turn

    async def reload(self, **_kw):
        self.reloads += 1
        if self.reload_raises:
            raise RuntimeError("navigation timeout exceeded")
        if self.on_reload is not None:
            self.on_reload(self)

    async def goto(self, url, **_kw):
        self.gotos.append(url)
        self._url = url

    async def bring_to_front(self):
        self.fronted += 1

    async def expose_function(self, name, _cb):
        self.exposed.append(name)

    async def evaluate(self, js, arg=None):
        if js is research._GEMINI_CONVO_TEXT_JS:
            if self.turn:
                return json.dumps({"src": "turn", "text": self.turn[:4000]})
            return json.dumps({"src": "body", "text": self.body[:4000]})
        if "slice(0, 8000)" in js:
            return self.body[:8000]
        if "__agentObserver" in js:
            self.observer_injected = True
            return True
        if "immersive-panel" in js:
            return self.state
        # The left rail, for the sidebar probe.
        if "side-nav-sparkle-button" in js:
            return True
        if "const out = [], seen = new Set();" in js:
            return list(self.titles)
        if "if (t === title) { a.click(); return true; }" in js:
            if arg in self.titles and self.on_click is not None:
                self.on_click(self)
                return True
            return False
        raise AssertionError(f"unexpected page JS: {js[:90]}")


def test_the_surface_read_tells_the_card_and_the_completion_line_apart():
    """`_gemini_research_started` ORs them; the cadence needs them APART — the
    card says a research is mounted, the completion line says leave it alone."""
    assert asyncio.run(research._gemini_research_surface(
        _Tab(body=f"chatter {CARD} chatter"))) == (True, False)
    assert asyncio.run(research._gemini_research_surface(
        _Tab(body=f"{CARD}\n{DONE}"))) == (True, True)
    assert asyncio.run(research._gemini_research_surface(
        _Tab(body=CHROME))) == (False, False)


def test_the_surface_read_is_fail_closed_so_a_probe_miss_cannot_cause_a_reload():
    bad = _Tab(body=CARD)

    async def _boom(_js, arg=None):
        raise RuntimeError("target closed")

    bad.evaluate = _boom
    assert asyncio.run(research._gemini_research_surface(bad)) == (False, False)


def test_a_body_that_read_back_empty_is_no_card_either():
    """⛔ THE OTHER HALF OF FAIL-CLOSED, AND THE ONE NOTHING DROVE. A raise is
    not the only way this read comes back useless: Gemini's SPA serves an empty
    `document.body.innerText` for a beat after a navigation, and that is
    precisely the moment this cadence is looking. An empty body read as "the
    research card is up" would reload a tab that has nothing on it, on the
    schedule of the cadence, for the rest of the run."""
    blank = _Tab(url=CONVO, body="")
    assert asyncio.run(research._gemini_research_surface(blank)) == (False, False)


# ── The identity prover ─────────────────────────────────────────────────────

def _identity(tab, convo_id=CONVO_ID, brief=BRIEF, **kw):
    kw.setdefault("settle_sec", 0)
    return asyncio.run(
        research._gemini_reload_identity_ok(tab, convo_id, brief, **kw))


def test_identity_needs_both_the_url_and_the_brief():
    assert _identity(_Tab(url=CONVO, turn=TOPIC)) is True


def test_a_reload_that_landed_on_the_empty_home_is_not_our_conversation():
    """⛔⛔ THE CASE A LIVENESS PROVER GETS WRONG. Gemini's blank `/app` home
    animates while the SPA hydrates, so "is something running" answers YES on
    the very failure this exists to catch. Identity answers no."""
    assert _identity(_Tab(url=HOME, body=CHROME)) is False


def test_a_different_conversation_is_not_ours_however_familiar_it_reads():
    """A concurrent worker's similar-titled chat, or a previous run of the same
    brief: the body half alone would adopt it."""
    other = _Tab(url="https://gemini.google.com/app/zzz99different", turn=TOPIC)
    assert _identity(other) is False


def test_the_right_url_with_somebody_elses_content_is_not_ours():
    """And the URL half alone would accept this one."""
    assert _identity(_Tab(url=CONVO, turn="Quarterly hiring plan for the "
                                          "Berlin support team")) is False


def test_identity_waits_for_the_conversation_to_mount():
    """The content mounts lazily after the URL flips. A single-shot check one
    render tick early already defeated the sidebar recovery once."""
    tab = _Tab(url=CONVO, body=CHROME)
    reads = {"n": 0}
    _real = tab.evaluate

    async def _late(js, arg=None):
        if js is research._GEMINI_CONVO_TEXT_JS:
            reads["n"] += 1
            if reads["n"] >= 3:
                tab.turn = TOPIC
        return await _real(js, arg)

    tab.evaluate = _late
    assert _identity(tab) is True
    assert reads["n"] == 3


def test_identity_refuses_when_there_is_no_brief_to_prove_it_with():
    assert _identity(_Tab(url=CONVO, turn=TOPIC), brief="") is False
    assert _identity(_Tab(url=CONVO, turn=TOPIC), convo_id="") is False
    # ⛔⛔ AND THE CASE ONLY THE GUARD CAN REFUSE. The two above are inherited:
    # the URL compare refuses them whatever the guard does, so deleting
    # `if not convo_id or not (pasted_text or "").strip()` left this test green
    # (09-18 cross-verify). On the BARE HOME the compare cannot refuse anything
    # — `_gemini_convo_url_id("…/app")` is `""` and an unknown convo_id is `""`
    # too, so the two are EQUAL — and the home's chrome carries this run's own
    # brief in the sidebar rail. Without the guard "prove identity" then returns
    # True on the empty home, which is the exact 2026-07 destruction this whole
    # prover exists to catch.
    assert _identity(_Tab(url=HOME, turn=TOPIC), convo_id="") is False


# ════════════════════════════════════════════════════════════════════════════
# The consumer — the tick the round-robin leg actually calls
# ════════════════════════════════════════════════════════════════════════════

def _p(tab, *, flat_for=3600.0, brief=BRIEF, reloaded_at=0.0):
    # Real wall-clock: the tick compares against `time.time()`, so a synthetic
    # epoch would make its own log line read "29,812,039m flat".
    now = research.time.time()
    return {"page": tab, "url": tab.url, "brief": brief,
            "start_time": now - 3600.0,
            "last_growth_time": now - flat_for,
            "gemini_stale_reload_at": reloaded_at}


def _tick(p, monkeypatch=None):
    return asyncio.run(research._gemini_stale_reload_tick(p, "Gemini",
                                                          settle_sec=0))


def test_a_healthy_looking_but_flat_tab_is_reloaded_and_proven():
    tab = _Tab(url=CONVO, body=CARD, turn=TOPIC)
    p = _p(tab)
    before = p["last_growth_time"]
    assert _tick(p) == "survived"
    assert tab.reloads == 1
    assert p["last_growth_time"] == before, (
        "⛔⛔ A SURVIVING URL IS NOT GROWTH. Identity is explicitly not liveness, "
        "so proving we came back into the conversation says nothing about "
        "progress inside it — and C (12 min) is BELOW STUCK_NO_GROWTH_SEC (15), "
        "so a rewind here makes the stuck card unreachable for the whole run")
    assert p["gemini_stale_reloads"] == 1
    assert tab.observer_injected is True, "the observer is torn off by the nav"


def test_nothing_happens_on_a_tick_the_bound_refuses():
    tab = _Tab(url=CONVO, body=f"{CARD}\n{DONE}", turn=TOPIC)
    p = _p(tab)
    before = dict(p)
    assert _tick(p) == "held"
    assert tab.reloads == 0
    assert tab.observer_injected is False
    assert p["last_growth_time"] == before["last_growth_time"]
    assert "gemini_stale_reloads" not in p


def test_a_reload_that_throws_still_consumes_its_window():
    """⛔ Stamped BEFORE the navigation, never after — otherwise a tab whose
    reload times out is hammered on every 30-second tick."""
    tab = _Tab(url=CONVO, body=CARD, turn=TOPIC)
    tab.reload_raises = True
    p = _p(tab)
    before = p["last_growth_time"]
    assert _tick(p) == "reload_failed"
    assert p["gemini_stale_reload_at"] == pytest.approx(
        research.time.time(), abs=5)
    assert _tick(p) == "held", "the failed attempt used up the window"
    assert tab.reloads == 1
    assert tab.observer_injected is True, (
        "a domcontentloaded timeout does not mean the page stayed put — a slow "
        "SPA can navigate and then miss the deadline, tearing the observer off")
    assert p["last_growth_time"] == before, (
        "nothing was proven, so the stuck arbiter's clock must not move")


def test_a_reload_that_lands_on_the_home_falls_back_to_post_start_adoption(monkeypatch, no_waiting):
    tab = _Tab(url=CONVO, body=CARD, turn=TOPIC)
    tab.on_reload = lambda t: t.land(HOME, body=CHROME)
    adopted = _Tab(url=CONVO, body=f"{CARD}\n{DONE}", turn=TOPIC,
                   state="report_present")
    seen = {}

    async def _adopt(page, pasted, label, *, post_start=False, lost_convo_id=""):
        seen.update(page=page, pasted=pasted, label=label, post_start=post_start,
                    lost_convo_id=lost_convo_id)
        return adopted, True

    monkeypatch.setattr(research, "_gemini_adopt_lost_conversation", _adopt)
    p = _p(tab)
    before = p["last_growth_time"]
    assert _tick(p) == "adopted"
    assert seen["post_start"] is True, "the send path's verdict is the wrong one here"
    assert seen["pasted"] == BRIEF
    assert seen["lost_convo_id"] == CONVO_ID, (
        "⛔ THE TICK KNOWS WHICH CONVERSATION IT LOST AND MUST SAY SO. Without "
        "the id, the relaxed report verdict can adopt a PREVIOUS run of the "
        "same brief and deliver its report as this run's")
    assert p["page"] is adopted
    assert p["url"] == CONVO
    assert research._runtime.active_pages.get("gemini") is adopted
    assert adopted.observer_injected is True, "an adopted page never had an observer"
    assert p["last_growth_time"] == before, (
        "an adoption re-attaches a conversation; it does not make it grow")


def test_an_unrecoverable_reload_leaves_the_stuck_arbiters_clock_alone(monkeypatch, no_waiting):
    """⛔⛔ THE PIN THAT KEEPS THE CADENCE FROM HIDING THE STALL. Rewinding the
    growth clock on an unproven page pushes the stuck card and the 90-minute
    auto-skip one window further out EVERY time the cadence fires — a fix that
    makes the reported symptom last longer."""
    tab = _Tab(url=CONVO, body=CARD, turn=TOPIC)
    tab.on_reload = lambda t: t.land(HOME, body=CHROME)

    async def _adopt(page, pasted, label, *, post_start=False, lost_convo_id=""):
        return page, False

    monkeypatch.setattr(research, "_gemini_adopt_lost_conversation", _adopt)
    p = _p(tab)
    before = p["last_growth_time"]
    assert _tick(p) == "lost"
    assert p["last_growth_time"] == before
    assert tab.observer_injected is True, "still re-injected after every reload"


def test_an_adoption_that_raises_is_not_a_proven_identity(monkeypatch, no_waiting):
    tab = _Tab(url=CONVO, body=CARD, turn=TOPIC)
    tab.on_reload = lambda t: t.land(HOME, body=CHROME)

    async def _adopt(page, pasted, label, *, post_start=False, lost_convo_id=""):
        raise RuntimeError("sidebar rail never expanded")

    monkeypatch.setattr(research, "_gemini_adopt_lost_conversation", _adopt)
    p = _p(tab)
    before = p["last_growth_time"]
    assert _tick(p) == "lost"
    assert p["last_growth_time"] == before


def test_the_cadence_reloads_at_most_once_per_window_on_a_wedged_tab():
    tab = _Tab(url=CONVO, body=CARD, turn=TOPIC)
    p = _p(tab)
    assert _tick(p) == "survived"
    # The window was stamped before the reload, so nothing else happens until it
    # has elapsed — on the reload clock AND on the growth clock.
    for _ in range(5):
        assert _tick(p) == "held"
    assert tab.reloads == 1


# ════════════════════════════════════════════════════════════════════════════
# ⛔⛔ THE WEDGED RUN — the whole reason the lane exists, simulated end to end
#
# The first cut of this lane rewound `last_growth_time` whenever the reload came
# back into a proven conversation. C is 12 min and STUCK_NO_GROWTH_SEC is 15, so
# that rewind meant the growth clock could never reach 15 again: the L1 arbiter,
# the [Retry][Skip] card, the owner's ping and the 30-minute unacted auto-skip
# all became unreachable for Gemini after Start, and a genuinely wedged run went
# silently to the 90-minute hard cap. The lane built for "it's getting stuck in
# working phase" disabled the only thing that reports stuck.
#
# ⛔ NO TEST BELOW READS SOURCE FOR THIS. They drive the REAL tick at the REAL
# 30-second poll interval over a wedged tab and ask what the arbiter would have
# seen, because that is the only question that was ever in doubt.
# ════════════════════════════════════════════════════════════════════════════

class _Clock:
    """A fake wall clock for `research.time`. Only `time()` is fake — every
    other attribute falls through to the real module, so nothing else about the
    code under test changes."""

    def __init__(self, t0: float):
        self.now = float(t0)

    def time(self) -> float:
        return self.now

    def tick(self, secs: float) -> None:
        self.now += float(secs)

    def __getattr__(self, attr):
        return getattr(_real_time, attr)


def _leg_const(name: str):
    """The value the round-robin gives one of its own constants — PARSED and
    evaluated, never matched as text, and read the way the leg reads it so a
    changed default moves this simulation with it."""
    tree = ast.parse(textwrap.dedent(LEG))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name):
            return eval(compile(ast.Expression(node.value), "<leg>", "eval"),
                        {"os": os, "int": int})
    raise AssertionError(f"{name} is no longer assigned in the round-robin")


def _wedged_run(minutes: float, monkeypatch, *, cadence: bool) -> dict:
    """Drive a wedged-but-present Gemini research through `minutes` of the real
    poll loop and report what the stuck arbiter would have seen.

    The tab is the owner's reported symptom exactly: the research card is up,
    no completion line ever appears, the conversation never leaves its URL and
    nothing the growth clock can see ever moves. Every reload therefore comes
    back PROVEN — which is the case the rewind was written for.
    """
    stuck_after = _leg_const("STUCK_NO_GROWTH_SEC")
    min_elapsed = _leg_const("STUCK_MIN_ELAPSED_SEC")
    clock = _Clock(1_000_000.0)
    monkeypatch.setattr(research, "time", clock)
    tab = _Tab(url=CONVO, body=CARD, turn=TOPIC)
    start = clock.now
    p = {"page": tab, "url": tab.url, "brief": BRIEF, "start_time": start,
         "last_growth_time": start, "gemini_stale_reload_at": 0.0}
    carded_at = None
    worst_no_growth = 0.0
    while clock.now < start + minutes * 60:
        if cadence:
            asyncio.run(research._gemini_stale_reload_tick(
                p, "Gemini", settle_sec=0))
        # What the arbiter computes, one line later in the same loop body.
        no_growth = clock.now - p["last_growth_time"]
        worst_no_growth = max(worst_no_growth, no_growth)
        if (carded_at is None and no_growth > stuck_after
                and (clock.now - start) > min_elapsed):
            carded_at = (clock.now - start) / 60.0
        clock.tick(POLL_TICK)
    return {"carded_at": carded_at, "worst_no_growth": worst_no_growth,
            "reloads": int(p.get("gemini_stale_reloads", 0) or 0),
            "stuck_after": stuck_after}


def test_a_wedged_gemini_still_reaches_the_stuck_card_with_the_cadence_running(
        monkeypatch, no_waiting):
    """⛔⛔ THE REGRESSION THIS LANE MUST NOT BE. The cadence may not cost the
    owner the card: a 90-minute wedged run has to raise it at the same ~15.5
    minutes it did before wave 10, whether the cadence is running or not."""
    off = _wedged_run(90, monkeypatch, cadence=False)
    on = _wedged_run(90, monkeypatch, cadence=True)
    assert off["carded_at"] == pytest.approx(15.5, abs=0.6)
    assert on["carded_at"] is not None, (
        "the cadence swallowed the stuck card entirely — a wedged Gemini now "
        "runs silently to the 90-minute hard cap")
    assert on["carded_at"] == pytest.approx(off["carded_at"], abs=0.6), (
        "the cadence delayed the card the owner is waiting for")
    # And it keeps growing afterwards, so the 30-minute unacted auto-skip and
    # the arbiter's re-verdicts still land on their original schedule.
    assert on["worst_no_growth"] > 80 * 60


def test_the_growth_clock_is_never_rewound_by_a_reload_that_proved_nothing_moved(
        monkeypatch, no_waiting):
    """The mechanism behind the test above, stated on its own: over a wedged
    run the cadence reloads repeatedly and PROVES identity every time, and the
    growth clock keeps counting from the last real growth regardless. Capping
    it at one window (720 s) is what made the card unreachable."""
    on = _wedged_run(90, monkeypatch, cadence=True)
    assert on["reloads"] >= 1, "the cadence never fired; this measures nothing"
    assert on["worst_no_growth"] > on["stuck_after"], (
        "the growth clock never crossed STUCK_NO_GROWTH_SEC on a tab that grew "
        "nothing for 90 minutes")
    assert on["worst_no_growth"] > research._GEMINI_STALE_RELOAD_SEC + POLL_TICK


def test_a_wedged_run_pays_the_ceiling_and_not_one_reload_more(
        monkeypatch, no_waiting):
    """⛔ THE TAB THE CEILING IS FOR. Uncapped, this 90-minute wedge pays seven
    reloads — seven page loads on the one platform this module avoids them for,
    each blocking the Gemini leg ~35-40 s, on a tab the first one did not cure.
    Three, then the stuck arbiter owns it."""
    on = _wedged_run(90, monkeypatch, cadence=True)
    assert on["reloads"] == research._GEMINI_STALE_RELOAD_MAX == 3


# ════════════════════════════════════════════════════════════════════════════
# The adoption verdict — executed, both ways
# ════════════════════════════════════════════════════════════════════════════

class _Ctx:
    def __init__(self, pages):
        self.pages = pages


OTHER = "https://gemini.google.com/app/9f3aa0bb1c2d5"   # last run, same topic


def _adopt_over_sibling(state, *, post_start, at=CONVO, lost=CONVO_ID):
    """Drive the REAL sidebar/tab hunt over one sibling tab in that state.

    `at` is where the sibling conversation lives and `lost` is the id the
    post-Start caller says it lost — the same by default, different when the
    candidate is a previous run of the same brief.
    """
    ours = _Tab(url=HOME, body=CHROME)
    sibling = _Tab(url=at, turn=TOPIC, state=state)
    ours.context = sibling.context = _Ctx([ours, sibling])
    return asyncio.run(research._gemini_adopt_lost_conversation(
        ours, BRIEF, "Gemini", post_start=post_start,
        lost_convo_id=(lost if post_start else "")))


def test_the_send_path_still_refuses_a_conversation_holding_a_report(no_waiting):
    """Before Start, a matching conversation that already holds a report is a
    PREVIOUS run of the same brief — adopting it would deliver stale research
    and strand [2D] hunting a Start button that will never appear. Unchanged."""
    page, adopted = _adopt_over_sibling("report_present", post_start=False)
    assert adopted is False
    assert page.url == HOME


def test_the_post_start_caller_reads_a_present_report_as_success(no_waiting):
    """From the other side of Start the conversation is the one we just lost,
    and a present report is that research having FINISHED while the tab was
    away — the best outcome available, not a stale one."""
    page, adopted = _adopt_over_sibling("report_present", post_start=True)
    assert adopted is True
    assert page.url == CONVO
    assert page.fronted == 1


def test_the_pre_start_states_are_adopted_by_both_callers(no_waiting):
    for state in ("start_waiting", "pre_start"):
        for post_start in (False, True):
            page, adopted = _adopt_over_sibling(state, post_start=post_start)
            assert adopted is True, (state, post_start)
            assert page.url == CONVO


def _adopt_over_sidebar(state, *, post_start, at=CONVO, lost=CONVO_ID):
    """Drive the REAL sidebar probe — probe 2, which has its own copy of the
    report verdict. Without this the flag's second site is unmeasured."""
    ours = _Tab(url=HOME, body=CHROME, state=state)
    ours.context = _Ctx([ours])          # no sibling tab → fall through to the rail
    ours.titles = ["Solid-state sodium-ion cathodes 2026 pilot lines"]
    ours.on_click = lambda t: t.land(at, turn=TOPIC)
    return asyncio.run(research._gemini_adopt_lost_conversation(
        ours, BRIEF, "Gemini", post_start=post_start,
        lost_convo_id=(lost if post_start else "")))


def test_the_sidebar_probe_carries_the_same_two_verdicts(no_waiting):
    page, adopted = _adopt_over_sidebar("report_present", post_start=False)
    assert adopted is False
    assert page.gotos[-1] == "https://gemini.google.com/app", (
        "a refused sidebar candidate is backed out to a fresh home")
    page, adopted = _adopt_over_sidebar("report_present", post_start=True)
    assert adopted is True
    assert page.url == CONVO
    page, adopted = _adopt_over_sidebar("start_waiting", post_start=False)
    assert adopted is True


def test_the_relaxed_report_verdict_is_scoped_to_the_conversation_we_lost(no_waiting):
    """⛔⛔ THE RE-RUN. The ownership evidence is the BRIEF, and on a re-run of
    the same topic LAST RUN's finished conversation matches it deterministically
    — so a post-Start relaxation that asks only "does this hold a report" adopts
    it and delivers last run's research as this run's gemini.md, silently,
    looking exactly like a successful recovery. The tick knows the id it lost;
    a report-bearing candidate at any other id is refused exactly as the send
    path refuses it. Both probes, because both carry a copy of the verdict."""
    page, adopted = _adopt_over_sibling("report_present", post_start=True,
                                        at=OTHER, lost=CONVO_ID)
    assert adopted is False, (
        "adopted a PREVIOUS run's finished conversation as this run's")
    assert page.url == HOME
    page, adopted = _adopt_over_sidebar("report_present", post_start=True,
                                        at=OTHER, lost=CONVO_ID)
    assert adopted is False
    assert page.gotos[-1] == "https://gemini.google.com/app"


def test_an_unknown_lost_id_falls_back_to_the_send_paths_refusal(no_waiting):
    """Fail-closed: `post_start` alone no longer relaxes anything. A caller that
    cannot say which conversation it lost gets the strict verdict — we keep
    hunting or report `lost`, which leaves the stuck arbiter's clock where it
    is, rather than guessing at a report."""
    page, adopted = _adopt_over_sibling("report_present", post_start=True,
                                        at=CONVO, lost="")
    assert adopted is False
    # …and the pre-Start states are still adopted without an id, because the
    # relaxation is the only thing scoped.
    for state in ("start_waiting", "pre_start"):
        _pg, ok = _adopt_over_sibling(state, post_start=True, lost="")
        assert ok is True, state


def test_post_start_relaxes_the_report_verdict_and_nothing_else(no_waiting):
    """A conversation that is not ours is refused from BOTH sides — the flag
    moves one verdict, never the ownership evidence."""
    ours = _Tab(url=HOME, body=CHROME)
    sibling = _Tab(url=CONVO, turn="Berlin support team hiring plan",
                   state="report_present")
    ours.context = sibling.context = _Ctx([ours, sibling])
    page, adopted = asyncio.run(research._gemini_adopt_lost_conversation(
        ours, BRIEF, "Gemini", post_start=True, lost_convo_id=CONVO_ID))
    assert adopted is False


# ════════════════════════════════════════════════════════════════════════════
# The wiring, and the refusals that must NOT have moved
# ════════════════════════════════════════════════════════════════════════════

LEG = inspect.getsource(research.poll_all_agents_round_robin)
TICK = "_gemini_stale_reload_tick"

# ⛔⛔ THE WIRING IS PINNED ON THE TREE, NOT ON THE TEXT — AND THIS IS WHY.
# The first cut of these three tests read `LEG` (and `run_phase2`) as RAW SOURCE
# and counted substrings in it. On 2026-09-18 the cross-verify unwired this
# entire lane in a sandbox clone — `pass  # await _gemini_stale_reload_tick(p,
# name)` — and every test in this file stayed green, because a comment naming
# the call satisfies both the count and the ordering. Commenting out the brief
# seed did the same: 829 tests green with the cadence refusing, silently, for
# the whole run. The lane the owner actually asked for could have shipped
# completely dead behind a green gate.
#
# A comment contributes NO NODE to the tree, so nothing below can be paid for
# with prose. `LEG` itself stays raw on purpose: the two tests further down
# deliberately assert about comment text, which is the one thing `ast` cannot
# see.
LEG_TREE = ast.parse(textwrap.dedent(LEG))


def _awaited_calls(tree, func_name: str) -> list:
    """Every `await <func_name>(...)` the tree really MAKES, in source order."""
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name)
            and n.value.func.id == func_name]


def _innermost_if(tree, target) -> ast.If:
    """The `if` whose BODY holds `target` — the guard it really runs under.

    Only `node.body` counts: an `else`/`elif` arm is a DIFFERENT branch, and a
    call that moved into one runs under the negation of the guard below."""
    holding = [n for n in ast.walk(tree) if isinstance(n, ast.If)
               and any(target in ast.walk(stmt) for stmt in n.body)]
    assert holding, f"{TICK} is not inside any `if` at all"
    return max(holding, key=lambda n: n.lineno)


def _and_clauses(test) -> set:
    """The `and`-ed clauses of one `if` test, each unparsed back to source."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return {ast.unparse(v) for v in test.values}
    return {ast.unparse(test)}


def test_the_cadence_is_wired_into_the_gemini_leg_before_the_dom_scrape():
    calls = _awaited_calls(LEG_TREE, TICK)
    assert len(calls) == 1, (
        "the Gemini leg awaits the cadence exactly once — a commented-out call "
        "is not a call, and this is the pin that says so")
    assert [ast.unparse(a) for a in calls[0].value.args] == ["p", "name"], (
        "the tick must be handed THIS agent's pending record and its name")
    scrapes = [n for n in ast.walk(LEG_TREE)
               if isinstance(n, ast.Assign) and len(n.targets) == 1
               and isinstance(n.targets[0], ast.Name)
               and n.targets[0].id == "scrape_fn"]
    assert len(scrapes) == 1, "the leg's one DOM-scrape lookup moved or multiplied"
    assert calls[0].lineno < scrapes[0].lineno, (
        "the reload must happen BEFORE the scrape: a scrape that runs into a "
        "reloading page reads a blank DOM and the leg banks it as this tick's "
        "progress")


def test_the_leg_gates_the_cadence_on_gemini_past_start_and_not_stopped():
    guard = _and_clauses(
        _innermost_if(LEG_TREE, _awaited_calls(LEG_TREE, TICK)[0]).test)
    assert "name == 'Gemini'" in guard
    assert "not _controls.is_stop()" in guard
    assert "not p.get('gemini_watch_start')" in guard, (
        "a late-Start watch must finish before a reload can touch the tab")
    assert "not p.get('needs_start_verify')" in guard


def test_gemini_is_still_not_reload_safe():
    """⛔⛔ THE SHORTCUT THIS LANE MUST NOT TAKE. `RELOAD_SAFE` enables the two
    EXISTING rescues, whose survival test is LIVENESS — which returns True on
    Gemini's blank home while the SPA hydrates. Adding Gemini there would mark
    it "rescued" on the exact failure the cadence exists to catch."""
    tree = ast.parse(textwrap.dedent(LEG))
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "RELOAD_SAFE"):
            found.append(ast.literal_eval(node.value))
    assert found == [{"ChatGPT", "Claude"}]


def test_every_pending_seed_carries_this_runs_brief():
    """⛔ Each of these literals REPLACES the whole entry, so a key the poll
    body reads and a literal omits simply stops existing. Without the brief the
    cadence refuses to fire — silently, and for the rest of the run."""
    tree = ast.parse(textwrap.dedent(LEG))
    seeds = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].value, ast.Name)
                and node.targets[0].value.id == "pending"
                and isinstance(node.value, ast.Dict)):
            seeds.append([k.value for k in node.value.keys
                          if isinstance(k, ast.Constant)])
    assert len(seeds) == 4, "a new pending seed appeared — give it a brief too"
    for keys in seeds:
        assert "brief" in keys


def _phase_two_agent_seeds() -> list:
    """Every `agents["<name>"] = {<dict literal>}` seed run_phase2 writes, as
    (agent name, {key: unparsed value}) pairs — PARSED, so a key is counted
    only where it is really written and only for the agent it is really
    written for."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(research.run_phase2)))
    seeds = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        tgt = node.targets[0]
        if not (isinstance(tgt, ast.Subscript)
                and isinstance(tgt.value, ast.Name) and tgt.value.id == "agents"
                and isinstance(tgt.slice, ast.Constant)
                and isinstance(node.value, ast.Dict)):
            continue
        seeds.append((tgt.slice.value,
                      {k.value: ast.unparse(v)
                       for k, v in zip(node.value.keys, node.value.values)
                       if isinstance(k, ast.Constant)}))
    return seeds


def test_phase_two_hands_the_brief_to_the_round_robin():
    """⛔⛔ THE KEY, ON THE RECORD THAT NEEDS IT. The pin this replaces counted
    `'"brief": brief_text,'` once in the raw source of run_phase2 and never tied
    it to Gemini — so commenting the line out kept it green (the cadence then
    refuses for the whole run, silently), and so did moving it onto ChatGPT's
    seed, which run_phase2 also writes. Parsed and keyed, neither is payable.

    The setup-FAILED Gemini seed is deliberately exempt: that record carries
    `verified=False` plus the internal skip marker, so the poll set drops it on
    tick 1 and it is never polled at all."""
    live = [keys for name, keys in _phase_two_agent_seeds()
            if name == "Gemini" and "setup_failed" not in keys]
    assert len(live) == 1, "run_phase2 seeds the live Gemini record exactly once"
    assert live[0].get("brief") == "brief_text", (
        "the identity prover has no brief to prove the conversation with, so "
        "`have_identity_brief` is False and the cadence never fires again")


def test_the_contradicting_refusal_sentence_was_rewritten():
    """⛔ The leg's own comment used to read "Do NOT reload Gemini mid-run for
    any reason", which the branch below it now contradicts. The 2026-07 finding
    was about `page.goto`; the reload of a mounted post-Start tab is what the
    owner verified on 2026-09-16."""
    # It survives ONCE, and only as a quoted, retired sentence.
    assert LEG.count("Do NOT reload Gemini mid-run for any reason") == 1
    assert '# "Do NOT reload Gemini mid-run for any reason" — IS NO LONGER TRUE,' in LEG
    assert "Do NOT reload Gemini mid-run for any reason; completion" not in LEG, (
        "the old sentence must not still stand as a rule")
    assert "the ONLY mid-run\n            # reload of Gemini" in LEG


# The class of claim the cadence retired: "this module never reloads Gemini
# mid-run". NOT the narrower rules that are still true and must stay — the
# session-expiry branch's "never reload a MOUNTED Gemini conversation", the
# sidebar hunt's "never reload once in a conversation" — which say where a
# reload may not happen, not that none ever does.
_OLD_RULE_RE = re.compile(
    r"(never\s+reloaded\s+mid-?run"
    r"|gemini\s+is\s+never\s+reloaded"
    r"|do\s+not\s+reload\s+gemini\s+mid-?run"
    r"|don'?t\s+reload\s+gemini\s+mid-?run)", re.I)
# A sentence may survive only as a QUOTED, explicitly retired one.
_RETIRED_RE = re.compile(
    r"(no longer true|corrected|stopped being true|retired|used to read)", re.I)


def _quoted_spans(line: str):
    return [(m.start(), m.end()) for m in re.finditer(r'"[^"]*"', line)]


def test_no_surviving_sentence_still_says_gemini_is_never_reloaded_mid_run():
    """⛔⛔ THE RULE, NOT THE ONE INSTANCE OF IT. The wave-10 fix rewrote the
    wiring site's copy of this sentence and left a second one standing three
    lines under `RELOAD_SAFE`, ~1,700 lines above the branch that now reloads
    Gemini — because the test policed the sentence it NAMED instead of the
    claim. This one reads every comment line in the module and allows a match
    only where it is quoted AND marked retired, so the next copy fails here
    wherever in the file it is written.
    """
    lines = inspect.getsource(research).splitlines()
    offenders = []
    for i, line in enumerate(lines):
        # Every line, not just the ones that look like comments — a docstring
        # continuation line has neither a `#` nor a leading quote, and that is
        # exactly where a rule like this goes to survive unnoticed.
        for m in _OLD_RULE_RE.finditer(line):
            quoted = any(a < m.start() and m.end() < b
                         for a, b in _quoted_spans(line))
            context = "\n".join(lines[max(0, i - 4):i + 5])
            if quoted and _RETIRED_RE.search(context):
                continue
            offenders.append(f"{i + 1}: {line.strip()}")
    assert offenders == [], (
        "a comment still asserts the retired rule as current:\n"
        + "\n".join(offenders))


def test_the_other_refusal_sites_were_not_widened():
    src = inspect.getsource(research)
    # #897a, the session-expiry Retry branch: a MOUNTED Gemini conversation is
    # never reloaded for a cookie — the fresh cookie applies to its background
    # requests in place.
    assert ('_gemini_mounted = name == "Gemini" and "gemini.google.com" in _cur_url'
            in src)
    assert "if not _gemini_mounted:" in src
    # The sidebar hunt's own rule, and the caller that keeps it: the hunt
    # refreshes only the EMPTY HOME, and never from inside a conversation.
    assert "We\n    #     never reload once in a conversation, and never after opening one." in src
    assert "is that it never reloads while inside a conversation" in src


# ════════════════════════════════════════════════════════════════════════════
# The landed re-draft, and what has to be re-armed with the clock
# ════════════════════════════════════════════════════════════════════════════

def _branch_writes(if_test_name: str) -> dict:
    """Every `p["<key>"] = <literal>` the round-robin makes inside the branch
    guarded by `if <if_test_name>:` — PARSED from the tree, so a commented-out
    line writes nothing and a line moved out of the branch is not counted."""
    tree = ast.parse(textwrap.dedent(LEG))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == if_test_name):
            continue
        writes = {}
        for stmt in ast.walk(node):
            if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
                continue
            tgt = stmt.targets[0]
            if (isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name) and tgt.value.id == "p"
                    and isinstance(tgt.slice, ast.Constant)):
                try:
                    writes[tgt.slice.value] = ast.literal_eval(stmt.value)
                except Exception:
                    writes[tgt.slice.value] = "<computed>"
        return writes
    raise AssertionError(f"the round-robin no longer branches on {if_test_name}")


def test_a_landed_research_redraft_re_arms_the_late_start_watch():
    """⛔ Gemini's Redo on a deep-research turn plausibly comes back as a PLAN
    with a fresh "Start research", and nothing else in the poll loop presses
    one: `gemini_watch_start` is set only by a later CUA `needs_click`, up to
    five minutes away. The re-draft branch resets the growth clock; the watch
    belongs beside it — and re-arming it also correctly suppresses the stale
    reload cadence while a start is pending."""
    writes = _branch_writes("_rr_ok")
    assert writes.get("gemini_watch_start") is True, (
        "a landed re-draft leaves the late-Start watch disarmed — nothing "
        "presses a Start button that renders after it")
    assert "last_growth_time" in writes, (
        "the watch must be armed ALONGSIDE the clock reset, in the same branch")
    assert writes.get("gemini_watch_click_count") == 0, (
        "a click budget spent on the ORIGINAL plan's Start would clear the "
        "fresh watch on its very first leg")
