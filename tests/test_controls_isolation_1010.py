"""A test file may not leave the run controls bound to a loop that has closed.

`research._controls` is a module singleton, and its three asyncio.Events bind to
the first loop that blocks on them. `test_pause_resume_safety_net_0902.py` hands
each test fresh Events, because pytest-asyncio gives each test a fresh loop.
⛔ It used to do that by plain assignment, so the file's LAST Events stayed on
the singleton after the file ended, bound to a loop that was already closed. The
next test anywhere in the run that blocked on one got "bound to a different
event loop". Whether it failed depended only on which file ran next.

This runs that exact order in a child pytest: the safety-net file, then a probe
that blocks on each Event under a new loop. The probe is inert in the ordinary
suite, and only the child process turns it on, so its own binding dies with
that process.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_PROBE_ENV = "SR_CONTROLS_ISOLATION_PROBE"
_EVENTS = ("stop_event", "pause_event", "resume_event")

#: The Events the singleton holds at COLLECTION, which pytest finishes before any
#: test runs. ⛔ Blocking alone misses an Event the file's last test never
#: blocked on: it is left behind unbound, harmless in this order and bound to a
#: dead loop in another. The rule is that the file hands back what it found.
_AT_COLLECTION: dict = {}
if os.environ.get(_PROBE_ENV) == "1":
    import research as _research
    _AT_COLLECTION = {n: getattr(_research._controls, n) for n in _EVENTS}


@pytest.mark.skipif(os.environ.get(_PROBE_ENV) != "1",
                    reason="runs only inside test_the_safety_net_file_leaves_the_controls_usable")
def test_probe_every_control_event_blocks_on_a_new_loop():
    import research

    left = [n for n in _EVENTS if getattr(research._controls, n) is not _AT_COLLECTION[n]]
    assert not left, f"the safety-net file left its own Events on the singleton: {left}"

    async def _block_briefly():
        for name in _EVENTS:
            ev = getattr(research._controls, name)
            ev.clear()
            # Blocking is what binds an Event to a loop, and what fails when it
            # is already bound to another one. A timeout is the healthy answer.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ev.wait(), 0.01)

    asyncio.run(_block_briefly())


def test_the_safety_net_file_leaves_the_controls_usable():
    env = dict(os.environ, **{_PROBE_ENV: "1"})
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider",
         "tests/test_pause_resume_safety_net_0902.py",
         "tests/test_controls_isolation_1010.py::test_probe_every_control_event_blocks_on_a_new_loop"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    out = proc.stdout + proc.stderr
    tail = "\n".join(out.strip().splitlines()[-15:])
    # ⛔ The probe must have RUN, after the file, and passed: a skipped or
    # deselected probe measures nothing, and `-rA` names every outcome.
    assert ("PASSED tests/test_controls_isolation_1010.py::"
            "test_probe_every_control_event_blocks_on_a_new_loop") in out, tail
    assert proc.returncode == 0, tail
