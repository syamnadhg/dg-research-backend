"""A Gemini that starts and finishes on its own gets no "couldn't start" card (wave 13).

⛔⛔ THE DEFECT (the 09-21 run in the fix14 bundle). Gemini started its Deep
Research by itself — no "Start research" button to press — and finished it
inside the five-minute plan wait. The wait never looked for a finished report:

    14:41:40 [2D] Plan not started after 302s — surfacing early [Retry][Skip] card
    14:41:43 Claude: The page shows a finished research report — "I've completed
             your research" is visible ... **research already running**
    ... two more vision re-drafts, 2.3 minutes each ...
    14:48:50 [2D] CUA recovery exhausted (3 attempts)
    14:53:18 [Gemini] Retracted the stale failure card — agent completed

⭐ NOW every tick of the wait first asks whether Gemini's finished report is on
the page (the report's "Contents · Share & Export · Create" row or Gemini's own
"I've completed your research" line, no Stop showing). If it is, Gemini goes
straight to the round-robin, which collects the report: no card, no vision step.

── How it is measured ──────────────────────────────────────────────────────
The REAL `run_phase2` Gemini launch (2C/2D) runs against a local page in headless
Chrome. Only the tab opener (`start_agent_no_gemini_wait`, which would open
gemini.google.com) hands back the local page, the vision step is a recorder, and
the round-robin after the launch is stopped. Time is a clock that the program's
own sleeps move forward, so the base code's five-minute wait runs in a moment.

⚠ ASSUMED, NOT CAPTURED: the finished page's markup. It is built from what the
detectors already key on (their docstrings quote the live page) and what the
09-21 log shows: a plan bubble whose "Start research" can no longer be pressed.
"""
import asyncio
import time
from types import SimpleNamespace

import pytest

import research
import test_claude_usage_limit_0916 as base

chrome = base.chrome

REPORT = "Internet Computer (ICP): An Empirical Investigation"
DONE_LINE = ("I've completed your research. Feel free to ask me follow-up questions "
             "or request changes.")


def gemini_page(*, trio=True, done_line=True, stop=False):
    plan = ('<model-response><message-content><p>Here is my research plan for the '
            'Internet Computer.</p><button aria-label="Start research" disabled>'
            'Start research</button></message-content></model-response>')
    done = (f"<model-response><message-content><p>{DONE_LINE}</p></message-content>"
            "</model-response>" if done_line else "")
    buttons = ("<button>Contents</button><button>Share &amp; Export</button>"
               "<button>Create</button>" if trio else "")
    stopb = '<button aria-label="Stop response">■</button>' if stop else ""
    return ("<main><user-query><div class='query-text'>brief " * 1 + "</div></user-query>"
            f"{plan}{done}<immersive-panel><h1>{REPORT}</h1>"
            + "<p>Findings of the research, in full.</p>" * 20
            + f"{buttons}{stopb}</immersive-panel></main>")


class _Clock:
    """research's `time`, with `time()` moved only by the program's sleeps."""

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
    events, lines, cua, handed = [], [], [], []
    clock = _Clock()

    class _FastAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(delay=0, *a, **k):
            clock.t += float(delay or 0)
            await asyncio.sleep(0)

    monkeypatch.setattr(research, "time", clock)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research, "log", lambda m, level="INFO": lines.append((level, str(m))))
    monkeypatch.setattr(research, "emit_event", lambda name, **k: events.append((name, k)))
    monkeypatch.setattr(research, "_p2_run_dir", lambda: tmp_path)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setenv("DG_P2_STAGGER_SEC", "0")
    monkeypatch.setattr(research, "_AGENT_ERROR_CARD_TS", {})
    monkeypatch.setattr(research, "_pending_decisions", {})
    monkeypatch.setattr(research, "_active_decisions", set())
    monkeypatch.setattr(research, "_active_decision_agents", {})
    ctl = research._controls
    monkeypatch.setattr(ctl, "skipped_agents", set())
    monkeypatch.setattr(ctl, "auto_skip_reasons", {})
    monkeypatch.setattr(ctl, "cookie_trust_broken", set())
    monkeypatch.setattr(ctl, "hv_blocked", {})
    monkeypatch.setattr(ctl, "hv_auto_skipped", set())
    monkeypatch.setattr(ctl, "is_stop", lambda: False)
    monkeypatch.setattr(ctl, "is_pause", lambda: False)
    monkeypatch.setattr(ctl, "pro_warning_acknowledged", True)

    async def _vision(*_a, **k):
        cua.append(k.get("hotspot_id"))
        return {}

    monkeypatch.setattr(research, "_shadow_observed_cua", _vision)

    async def _round_robin(agents, *a, **k):
        handed.append({n: dict(v) for n, v in agents.items()})
        raise _Stop()

    monkeypatch.setattr(research, "poll_all_agents_round_robin", _round_robin)

    def run(html):
        async def _open(browser, cua_client, url, *a, **k):
            page = await chrome.ctx.new_page()
            await page.set_content(html)
            return page, True

        monkeypatch.setattr(research, "start_agent_no_gemini_wait", _open)

        class _Browser:
            page = None

            async def switch_to_page(self, p):
                self.page = p

        try:
            chrome.run(asyncio.wait_for(research.run_phase2(
                _Browser(), None, "brief " * 40, enabled_agents=["gemini"]), timeout=120))
        except _Stop:
            pass
        cards = [k for name, k in events
                 if name == "pipeline_error" and k.get("agent") == "gemini"]
        return SimpleNamespace(cards=cards, lines=lines, cua=cua, handed=handed)

    return run


@pytest.mark.parametrize("trio,done_line", [(True, True), (True, False), (False, True)])
def test_a_gemini_that_finished_on_its_own_goes_to_the_round_robin(launch, trio, done_line):
    """⭐⭐ THE 09-21 RUN. The report is on the page and the plan's Start button
    can no longer be pressed: no card, no vision step, and Gemini is handed to
    the round-robin as having run. Before: the card at five minutes, then three
    vision re-drafts of a plan that had already turned into a report."""
    out = launch(gemini_page(trio=trio, done_line=done_line))
    assert out.cards == [], [c.get("error") for c in out.cards]
    assert out.cua == [], out.cua
    assert out.handed and out.handed[0]["Gemini"]["verified"] is True
    assert any("started and finished its research on its own" in m for _lv, m in out.lines)


def test_a_report_with_stop_still_showing_is_not_finished(launch):
    """A visible Stop outranks every done mark: that research is still running,
    and it is not handed over as finished."""
    out = launch(gemini_page(stop=True))
    assert not any("started and finished its research on its own" in m
                   for _lv, m in out.lines)
