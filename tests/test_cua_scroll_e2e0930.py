"""Computer-use scrolling goes where the model asks (09-30 run).

⛔⛔ THE DEFECT. The computer tool `agent_loop` declares (`computer_20251124`)
sends a scroll as `scroll_direction` / `scroll_amount`. The executor read
`direction` / `amount`, found neither, and scrolled DOWN by 3 every time: all 71
scrolls ever logged on the Mac say "down". In the 09-30 Phase 1 escalation the
model asked three times to scroll UP, was scrolled down each time, said "The page
didn't scroll up" and gave up:

    05:07:56 [ACTION] scroll — (640,400) down
    05:08:03 [ACTION] scroll — (640,400) down
    05:08:11 [ACTION] scroll — (640,400) down

⭐ NOW the tool's own names are read first; the old names stay as a fallback.

Measured on the REAL `agent_loop`, the REAL `execute_action` and the REAL
`Browser.scroll`. Only the page (which records the wheel it is given) and the
API client (which asks for one scroll, then answers in text) are stand-ins.
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
    def __init__(self):
        self.wheels = []
        self.moves = []
        self.mouse = SimpleNamespace(wheel=self._wheel, move=self._move)

    async def _wheel(self, dx, dy):
        self.wheels.append((dx, dy))

    async def _move(self, x, y):
        self.moves.append((x, y))

    async def screenshot(self, **kw):
        return b"\x89PNG-ok"


class _Client:
    """One tool use (`step`), then a text answer."""

    def __init__(self, step):
        self.steps = [step]
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, *, messages, **kw):
        if self.steps:
            return SimpleNamespace(content=[SimpleNamespace(
                type="tool_use", id="tu1", input=dict(self.steps.pop(0)))])
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="done")])


@pytest.fixture
def run(monkeypatch):
    actions = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO": None)
    monkeypatch.setattr(research, "log_action",
                        lambda action, details="": actions.append((action, details)))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research._controls, "is_stop", lambda: False)
    monkeypatch.setattr(research._controls, "is_pause", lambda: False)

    def _run(step):
        page = _Page()
        browser = research.Browser.__new__(research.Browser)
        browser.page = page
        out = asyncio.run(research.agent_loop(_Client(step), browser, "sys", "look",
                                              max_iterations=4))
        assert out["status"] == "done", out
        return page, actions

    return _run


def test_an_upward_scroll_the_model_asks_for_goes_up_by_its_amount(run):
    """⭐⭐ THE 09-30 SHAPE: the tool's own keys. Before the fix this wheel
    went DOWN by 300."""
    page, actions = run({"action": "scroll", "coordinate": [640, 400],
                         "scroll_direction": "up", "scroll_amount": 5})
    assert page.wheels == [(0, -500)], page.wheels
    assert page.moves == [(640, 400)]
    assert actions == [("scroll", "(640,400) up 5")], actions


@pytest.mark.parametrize("direction,amount,wheel", [
    ("down", 2, (0, 200)), ("left", 4, (-400, 0)), ("right", 1, (100, 0))])
def test_every_direction_the_tool_names_is_carried_out(run, direction, amount, wheel):
    page, _ = run({"action": "scroll", "coordinate": [10, 20],
                   "scroll_direction": direction, "scroll_amount": amount})
    assert page.wheels == [wheel], page.wheels


def test_the_old_key_names_still_work(run):
    page, _ = run({"action": "scroll", "coordinate": [10, 20],
                   "direction": "up", "amount": 2})
    assert page.wheels == [(0, -200)], page.wheels


def test_a_scroll_that_names_nothing_still_goes_down_by_three(run):
    page, _ = run({"action": "scroll", "coordinate": [10, 20]})
    assert page.wheels == [(0, 300)], page.wheels
