"""The end-of-run summary counts every computer-use call, by phase and purpose (09-30).

⛔⛔ THE DEFECT. The only end-of-run word on vision spend was the DOM ledger's
verdict, which tracks eight setup intents:

    05:56:18 [dom-summary] run complete 6/8 DOM intents handled without
             escalating (2 missed)

while the run had made 28 computer-use sessions (75 steps) and one vision-model
screen read: completion checks, panels, downloads, uploads, audio polls and
recovery never enter that ledger.

⭐ NOW every computer-use session is counted where it runs (`agent_loop`, with
its steps), every vision-model screen read where it is made, and the same
end-of-run summary prints a `[cua-summary]` line for the run and one per
phase · platform · purpose. The purpose is the step name the call site already
gives the dispatcher; a session started outside it is named by its prompt.

Measured on the REAL dispatcher (`_shadow_observed_cua`, vision tier off, the
default), the REAL `agent_loop`, the REAL source-link reader
(`extract_source_urls_via_vision`) and the REAL `_dom_summary`. Only the page,
the model and the HTTP post are stand-ins.
"""
import asyncio
from types import SimpleNamespace

import pytest

import research


class _FastAsyncio:
    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(delay=0, *a, **k):
        await asyncio.sleep(0)


class _Page:
    async def screenshot(self, **kw):
        return b"\x89PNG-ok"


class _Model:
    """A session of `turns` model turns: a screenshot request on each but the
    last, which answers in text. A step is one model turn, the unit the log's
    "Iteration N/M" lines count."""

    def __init__(self, turns):
        self.left = turns
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.left -= 1
        if self.left > 0:
            return SimpleNamespace(content=[SimpleNamespace(
                type="tool_use", id=f"tu{self.left}", input={"action": "screenshot"})])
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="done")])


@pytest.fixture
def run(monkeypatch):
    lines = []
    monkeypatch.setattr(research, "log", lambda m, level="INFO": lines.append(str(m)))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research._controls, "is_stop", lambda: False)
    monkeypatch.setattr(research._controls, "is_pause", lambda: False)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    monkeypatch.delenv("DG_VISION_TIER", raising=False)
    research._dom_reset()
    browser = research.Browser.__new__(research.Browser)
    browser.page = _Page()

    async def _dispatched(turns, *, phase, platform, step):
        async def _factory():
            return await research.agent_loop(_Model(turns), browser, "sys", "go",
                                             max_iterations=10)
        return await research._shadow_observed_cua(
            browser.page, hotspot_id="h", phase=phase, platform=platform,
            current_step=step, context_hint="", cua_coro_factory=_factory)

    async def _direct(turns, *, prompt, phase, agent):
        return await research.agent_loop(_Model(turns), browser, prompt, "go",
                                         max_iterations=10, phase=phase,
                                         agent_name=agent)

    yield SimpleNamespace(lines=lines, dispatched=_dispatched, direct=_direct,
                          page=browser.page)
    research._dom_reset()


def _summary(lines):
    return [m for m in lines if m.startswith("[cua-summary]")]


def test_every_session_is_counted_by_phase_platform_and_purpose(run, monkeypatch):
    """⭐⭐ THE 09-30 SHAPE: two Gemini recovery passes, a Phase 1 panel pass,
    a session outside the dispatcher and a source-link read — all in the
    summary, with their steps. Before: no [cua-summary] line at all."""
    asyncio.run(run.dispatched(3, phase=2, platform="gemini",
                               step="start_or_regenerate_plan"))
    asyncio.run(run.dispatched(2, phase=2, platform="gemini",
                               step="start_or_regenerate_plan"))
    asyncio.run(run.dispatched(1, phase=1, platform="phase1",
                               step="open_activity_panel_p1"))
    asyncio.run(run.direct(4, prompt=research.PROMPT_CLICK_SEND, phase=2, agent="claude"))

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"candidates": [{"content": {"parts": [
                {"text": '{"urls": [], "confidence": 0}'}]}}]}

    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(research, "resolve_gemini_api_key", lambda: "k")
    asyncio.run(research.extract_source_urls_via_vision(run.page, "claude"))

    research._dom_note("chatgpt.select_model", "missed", phase=1)
    run.lines.clear()
    research._dom_summary("run complete")
    out = _summary(run.lines)
    assert out[0] == ("[cua-summary] run complete computer use ran 4 times (10 steps in "
                      "all), plus 1 vision-model screen read — the DOM line above counts "
                      "only the setup steps it tracks"), out
    assert out[1:] == [
        "[cua-summary] run complete   p1 chatgpt · open activity panel p1: 1 time, 1 step",
        "[cua-summary] run complete   p2 claude · click send: 1 time, 4 steps",
        "[cua-summary] run complete   p2 claude · read source links off the screen: "
        "1 vision read",
        "[cua-summary] run complete   p2 gemini · start or regenerate plan: 2 times, 5 steps",
    ], out


def test_a_run_with_no_dom_attempts_still_gets_the_count(run):
    """The DOM ledger's "nothing recorded" branch returns early; the count is
    printed there too."""
    asyncio.run(run.dispatched(2, phase=3, platform="notebooklm",
                               step="poll_audio_complete"))
    research._dom_summary("run failed")
    out = _summary(run.lines)
    assert out[0].startswith("[cua-summary] run failed computer use ran 1 time (2 steps")
    assert "[cua-summary] run failed   p3 notebooklm · poll audio complete: 1 time, 2 steps" \
        in out


def test_a_run_with_no_computer_use_says_so(run):
    research._dom_note("a.b", "verified", phase=1)
    research._dom_summary("run complete")
    assert _summary(run.lines) == [
        "[cua-summary] run complete no computer use and no vision-model screen reads "
        "this run"]


def test_a_new_run_starts_the_count_from_zero(run):
    asyncio.run(run.dispatched(1, phase=2, platform="claude", step="copy_final_artifact_t3"))
    research._dom_reset()
    research._dom_summary()
    assert _summary(run.lines) == [
        "[cua-summary] no computer use and no vision-model screen reads this run"]


def test_the_purpose_does_not_leak_past_its_call(run):
    """The call site's purpose is in force only while its own computer use runs:
    a session started afterwards, outside the dispatcher, is named by its own
    prompt. ⚠ Both in ONE task, the way a phase runs them: each `asyncio.run`
    starts from a fresh copy of the context, so two separate runs could never
    show a leak (the mutation harness caught exactly that)."""
    async def _one_task():
        await run.dispatched(1, phase=2, platform="gemini", step="start_or_regenerate_plan")
        await run.direct(1, prompt=research.PROMPT_DIAGNOSE, phase=2, agent="chatgpt")

    asyncio.run(_one_task())
    research._dom_summary()
    assert "[cua-summary]   p2 chatgpt · diagnose: 1 time, 1 step" in _summary(run.lines)


def test_a_vision_step_that_acts_is_counted_too(run, monkeypatch):
    """With the vision tier acting (DG_VISION_TIER=act), the vision model can
    finish a step without any computer use; that read is counted under the
    same step name."""
    async def _act_loop(page, **kw):
        return SimpleNamespace(action="declare_success", reason="panel open")

    monkeypatch.setattr(research, "_vision", SimpleNamespace(
        is_vision_enabled=lambda: "tier2", act_loop=_act_loop, ACT_MAX_STEPS_DEFAULT=3))
    out = asyncio.run(run.dispatched(2, phase=1, platform="phase1",
                                     step="open_activity_panel_p1"))
    assert out["status"] == "vision_success", out
    research._dom_summary()
    assert _summary(run.lines)[1:] == [
        "[cua-summary]   p1 chatgpt · open activity panel p1: 1 vision read"]
