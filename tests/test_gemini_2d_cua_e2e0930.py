"""Gemini's plan wait: computer use only where it can help, and Skip stops it (09-30).

⛔⛔ THE 09-30 RUN. Gemini never drafted a plan. At five minutes the card went
up and the vision recovery started on a page with nothing to press:

    05:15:46 [2D] Gemini plan stall diag @ 101s: no plan, no error text, not
             streaming (verdict=silent); controls read: []
    05:19:09 [2D] CUA recovery: plan not ready — CUA retrying the plan (attempt 1/3)
             ... seven vision steps: a scroll, a click on the owner's OWN brief
             bubble, three more scrolls, "no Start research button visible" ...
    05:19:28 Command received: SKIP_AGENT agent=gemini
    05:20:33 [2D] User skipped Gemini during CUA recovery — finalizing skip

⭐ NOW (wave 15, 10-02: the vision recovery itself is gone — Gemini starts its
research by itself and the plan wait hands it on with nothing pressed)
  · the log says what the page shows about Gemini whenever that changes, and
    names the chat and how long it took to land.

── How it is measured ──────────────────────────────────────────────────────
The REAL `run_phase2` Gemini launch (2C/2D) runs against a local page in headless
Chrome, exactly as tests/test_gemini_finished_on_its_own_w13.py does. Only the
tab opener hands back the local page, and the round-robin after the launch is
stopped. The vision step is either a recorder or — for Skip — the REAL
dispatcher and the REAL `agent_loop` with a stand-in model that presses Skip
during its second turn. Time is a clock the program's own sleeps move forward.
The landing line is measured on `start_agent_no_gemini_wait`'s REAL statements
from Send onward, lifted out of research.py's parse tree.
"""
import ast
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import research
import test_claude_usage_limit_0916 as base

chrome = base.chrome
SRC_PATH = Path(research.__file__).resolve()

BRIEF_BUBBLE = "<user-query><div class='query-text'>## Research mandate</div></user-query>"
#: The 09-30 screen: Gemini mounted a reply and never finished it — no plan, no
#: error, not one button in it.
SILENT = f"<main>{BRIEF_BUBBLE}<model-response><message-content></message-content></model-response></main>"
#: A reply holding a control the vision step might press (not Start research).
WITH_BUTTON = (f"<main>{BRIEF_BUBBLE}<model-response><message-content><p>Here is a "
               "draft.</p><button>Edit plan</button></message-content></model-response></main>")
#: No reply read at all — "cannot tell", which keeps the vision step.
NO_REPLY = f"<main>{BRIEF_BUBBLE}</main>"
#: The 09-30 screen while Gemini is still working: its 'Stop response' button is
#: on the page but hidden.
SILENT_BUT_WORKING = SILENT.replace(
    "</main>", '<button aria-label="Stop response" style="display:none">■</button></main>')

#: Gemini's plan arriving late, with its Start research button (pressing it
#: removes it, the way a Start that took leaves the page).
PLAN_ARRIVES_JS = """() => {
    const m = document.querySelector('message-content');
    m.innerHTML = '<p>Here is my research plan.</p><button aria-label="Start research" '
        + 'onclick="this.remove()">Start research</button>';
}"""


class _Clock:
    def __init__(self):
        self.t = time.time()

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return self.t


class _Stop(Exception):
    """The launch is over; the round-robin after it is not under test."""


class _Model:
    """The vision model: a screenshot request per turn. During its second turn
    the owner presses Skip, the way 05:19:28 landed in the middle of the pass."""

    def __init__(self):
        self.turns = 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.turns += 1
        if self.turns == 2:
            research._controls.request_skip_agent("gemini")
        return SimpleNamespace(content=[SimpleNamespace(
            type="tool_use", id=f"tu{self.turns}", input={"action": "screenshot"})])


@pytest.fixture
def launch(chrome, monkeypatch, tmp_path):
    events, lines, looks, handed = [], [], [], []
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
    opened, arrive = [], {}

    def _emit(name, **k):
        events.append((name, k))
        # The plan lands on the page when the run says this — see
        # test_a_slow_plan_is_still_started_by_the_watch_without_a_vision_step.
        if arrive.get("at") and k.get("progress") == arrive["at"] and opened:
            arrive["at"] = None
            asyncio.ensure_future(opened[-1].evaluate(PLAN_ARRIVES_JS))

    monkeypatch.setattr(research, "emit_event", _emit)
    monkeypatch.setattr(research, "_p2_run_dir", lambda: tmp_path)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setenv("DG_P2_STAGGER_SEC", "0")
    monkeypatch.delenv("DG_VISION_TIER", raising=False)
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

    async def _round_robin(agents, *a, **k):
        handed.append({n: dict(v) for n, v in agents.items()})
        raise _Stop()

    monkeypatch.setattr(research, "poll_all_agents_round_robin", _round_robin)

    def run(html, *, real_vision=False, plan_arrives_at=None):
        model = _Model() if real_vision else None
        arrive["at"] = plan_arrives_at
        if not real_vision:
            async def _vision(*_a, **k):
                looks.append(k.get("hotspot_id"))
                return {}

            monkeypatch.setattr(research, "_shadow_observed_cua", _vision)

        async def _open(browser, cua_client, url, *a, **k):
            page = await chrome.ctx.new_page()
            await page.set_content(html)
            opened.append(page)
            return page, True

        monkeypatch.setattr(research, "start_agent_no_gemini_wait", _open)

        class _Browser:
            page = None

            async def switch_to_page(self, p):
                self.page = p

            async def screenshot(self):
                return "iVBORw0KGgo="

        try:
            chrome.run(asyncio.wait_for(research.run_phase2(
                _Browser(), model, "brief " * 40, enabled_agents=["gemini"]), timeout=120))
        except _Stop:
            pass
        cards = [k for name, k in events
                 if name == "pipeline_error" and k.get("agent") == "gemini"]
        return SimpleNamespace(cards=cards, lines=lines, looks=looks, handed=handed,
                               model=model, events=events)

    return run


def _said(out, text):
    return [m for _lv, m in out.lines if text in m]


# ⛔⛔ WAVE 15 (10-02): THE COMPUTER-USE RECOVERY AFTER THE PLAN WAIT IS GONE,
# and with it the tests of when it looked and when Skip stopped it. Gemini starts
# its research by itself; the wait hands it to the round-robin with nothing
# pressed and nothing raised (tests/test_w15_gemini_waits_1002.py).


# ── What the page says about Gemini ──────────────────────────────────────────

def test_the_log_says_when_gemini_is_still_working(launch):
    """The hidden 'Stop response' button is Gemini's own running signal; the
    log says so, once."""
    out = launch(SILENT_BUT_WORKING)
    reads = _said(out, "Gemini's page now reads:")
    assert len(reads) == 1, reads
    assert "still working (its hidden 'Stop response' button is on the page)" in reads[0]
    assert out.looks == [] and out.cards == []


def test_the_log_says_when_nothing_is_running(launch):
    out = launch(SILENT)
    reads = _said(out, "Gemini's page now reads:")
    assert len(reads) == 1, reads
    assert "nothing running and nothing finished" in reads[0]
    assert out.looks == [] and out.cards == []


# ── The landing line: which chat, and how long after Send ────────────────────

def _send_onward():
    """`start_agent_no_gemini_wait`'s statements from the Send stamp to its end."""
    tree = ast.parse(SRC_PATH.read_text(encoding="utf-8"))
    fn = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
          and n.name == "start_agent_no_gemini_wait"]
    assert len(fn) == 1
    body = fn[0].body
    stamp = [i for i, s in enumerate(body) if isinstance(s, ast.Assign)
             and any(ast.unparse(t) == "_sent_at" for t in s.targets)]
    assert len(stamp) == 1, "the Send stamp moved — re-anchor this test"
    return body[stamp[0]:]


class _LandedPage:
    url = "https://gemini.google.com/app/0a1b2c3d4e5f"

    async def evaluate(self, *a, **k):
        return None


def test_the_confirmed_line_names_the_chat_and_how_long_it_took(monkeypatch):
    """⭐ 09-30: Send 05:12:09, confirmed 05:13:57 — 108 s, and the chat was
    logged nowhere. The 90-second failed-turn watch is part of the wait, so
    the stand-in for it moves the clock by 90 s; the landing itself is found
    on the first look."""
    clock = _Clock()
    lines = []

    class _FastAsyncio:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(delay=0, *a, **k):
            clock.t += float(delay or 0)

    async def _watch(page, label, max_wait_s=90):
        clock.t += 90
        return False

    # `page` is a parameter: the statements re-bind it (the adopted tab).
    shell = ast.parse("async def _after_send(page):\n    pass\n")
    shell.body[0].body = _send_onward()
    ast.fix_missing_locations(shell)
    page = _LandedPage()
    scope = {**vars(research), "label": "2C", "platform": "Gemini",
             "platform_l": "gemini", "browser": None, "cua_client": None,
             "verbose": False, "brief_to_paste": "brief", "time": clock,
             "asyncio": _FastAsyncio(), "_gemini_retry_failed_turn": _watch,
             "log": lambda m, level="INFO": lines.append(str(m))}
    exec(compile(shell, str(SRC_PATH), "exec"), scope)

    async def _read(p):
        return ("brief", True)

    scope["_gemini_read_conversation_text"] = _read
    scope["_gemini_conversation_ownership"] = lambda *a, **k: True
    got = asyncio.run(scope["_after_send"](page))
    assert got == (page, True)
    [line] = [m for m in lines if "Gemini submission confirmed" in m]
    assert "(conversation started)" in line
    assert f"chat {research.redacted_chat_url(page.url)}" in line, line
    assert "landed 93 s after Send" in line, line
    assert "0a1b2c3d4e5f" not in line, "a run log carries no chat address (09-02 rule)"
