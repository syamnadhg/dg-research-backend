"""The vision step's wait for Claude no longer freezes the program (wave 13).

⛔⛔ THE DEFECT. `agent_loop` called the Anthropic client straight from the event
loop. That call blocks until the model answers — up to ~24 s a turn in the
owner's bundle — and while it blocked NOTHING else ran: the 5-second online
signal missed seven beats, and Stop and every other command waited behind it.

⭐ NOW the call runs in a worker thread (`asyncio.to_thread`); its retries, the
stop/pause checks and `abort_event` are unchanged.

Measured on the REAL `agent_loop`: the client is a stand-in whose call blocks
the way a real HTTPS request does (`time.sleep`), and a ticker coroutine stands
for the online signal. Nothing leaves the machine.
"""
import asyncio
import time
from types import SimpleNamespace

import research

PNG = "iVBORw0KGgo="


class _Browser:
    async def screenshot(self):
        return PNG

    async def switch_to_page(self, _p):
        return None


class _SlowClient:
    """Blocks for `delay` seconds per call, like a real request. `fail_first`:
    the first call raises Anthropic's transient 500 instead."""

    def __init__(self, delay=0.6, fail_first=False):
        self.delay = delay
        self.fail_first = fail_first
        self.calls = 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **_kw):
        self.calls += 1
        time.sleep(self.delay)
        if self.fail_first and self.calls == 1:
            raise RuntimeError("Error code: 500 - internal server error")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="done")])


def _run_with_ticker(client, monkeypatch):
    """agent_loop on `client` while a ticker beats every 50 ms. Returns
    (agent_loop's result, the beats counted during it)."""
    monkeypatch.setattr(research._controls, "is_stop", lambda: False)
    monkeypatch.setattr(research._controls, "is_pause", lambda: False)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)

    async def main():
        beats = []

        async def ticker():
            while True:
                beats.append(time.monotonic())
                await asyncio.sleep(0.05)

        t = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        n0 = len(beats)
        out = await research.agent_loop(client, _Browser(), "system", "look",
                                        max_iterations=1)
        n = len(beats) - n0
        t.cancel()
        return out, n

    return asyncio.run(main())


def test_the_program_keeps_running_while_the_vision_reply_is_awaited(monkeypatch):
    """⭐⭐ THE FIX. A 0.6 s vision reply: the ticker beats through it. Before,
    the loop was frozen for the whole call and the ticker beat at most once."""
    out, beats = _run_with_ticker(_SlowClient(delay=0.6), monkeypatch)
    assert out["status"] == "done"
    assert beats >= 5, f"the program was frozen during the vision call ({beats} beats)"


def test_a_transient_500_is_still_retried_in_place(monkeypatch):
    """The retry around the call is unchanged: a 500, then the answer — one
    mission turn, two calls, and the program kept running through both."""
    real_sleep = asyncio.sleep

    async def _quick(delay=0, *a, **k):
        await real_sleep(min(delay, 0.01))

    monkeypatch.setattr(research.asyncio, "sleep", _quick)
    client = _SlowClient(delay=0.3, fail_first=True)
    out, beats = _run_with_ticker(client, monkeypatch)
    assert out["status"] == "done"
    assert client.calls == 2
    assert beats >= 5
