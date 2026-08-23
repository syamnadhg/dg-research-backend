"""Wave 5: one throw must not end the listener that carries Start and Stop.

⛔⛔ MEASURED AGAINST THE REAL LIBRARY, 2026-08-22. `google.api_core.bidi`'s
`BackgroundConsumer._thread_main` invokes the snapshot callback from its own
thread, catches anything that escapes, logs it once and RETURNS. The thread is
gone; the bidi RPC is never closed, `_on_fatal_exception` is unset, and
`_on_rpc_done` never fires — so nothing downstream observes a thing. The three
watches this decides are the ones that carry a person's Start, their Stop, and
every device command.

And it is not hypothetical. `backend.err.log` on this machine carries

    Thread-ConsumeBidirectionalStream caught unexpected exception
    'NoneType' object is not callable and will exit.
      File "…/firestore_v1/watch.py", line 572, in push
        self._snapshot_callback(keys, appliedChanges, read_time)

plus three more consumer deaths raised inside the library itself.

⭐⭐ WHICH IS WHY THE GUARD ALONE IS NOT THE FIX. A guard around our callback can
only stop OUR bug — three of the four deaths in the corpus were raised BEFORE
our code was reached. Recovering from those needs the dead watch to be noticed
and re-attached, and recovery used to require `_firebase_db` to have gone None
as well: a watch that died while the client stayed healthy had no path back
short of the process restarting for an unrelated reason.

⭐ Several tests here drive the REAL `BackgroundConsumer` over a fake bidi RPC.
No network and no credentials — but the thread, the try/except and the exit are
the shipped library's, which is the only place this behaviour actually lives.

Run: pytest tests/test_watch_liveness_0822.py -v
"""
from __future__ import annotations

import inspect
import logging
import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402


# ⛔ READ AT IMPORT, BEFORE ANY TEST RUNS. Every test below resets this global
# through monkeypatch so its own arithmetic is predictable — which means not one
# of them can see what the module STARTS at, and the starting value is the whole
# question of whether the first re-arm waits.
_STAMP_AT_IMPORT = research._watch_rearm_last_at


# ══════════════════════════════════════════════════════════════════════════
#  a fake bidi RPC — the surface BackgroundConsumer actually touches
# ══════════════════════════════════════════════════════════════════════════

class _FakeRpc:
    def __init__(self):
        self.is_active = True
        self.closed = False

    def add_done_callback(self, cb):
        pass

    def open(self):
        pass

    def close(self):
        self.closed = True
        self.is_active = False

    def recv(self):
        time.sleep(0.005)
        return "response"


class _Ran(dict):
    """What the consumer looked like WHILE it was running.

    ⛔ Snapshotted before `stop()`, because stopping is itself what a healthy
    consumer's `is_active` goes False for — and `stop()` closes the RPC too. An
    earlier version of this helper asserted after the stop and could not tell a
    thread that died from one that was asked to."""
    __getattr__ = dict.__getitem__


def _drive(callback, seconds=0.3):
    """Run `callback` under the real BackgroundConsumer for a moment."""
    from google.api_core.bidi import BackgroundConsumer
    rpc = _FakeRpc()
    consumer = BackgroundConsumer(rpc, callback)
    consumer.start()
    time.sleep(seconds)
    snap = _Ran(consumer_active=consumer.is_active,
                rpc_active=rpc.is_active,
                rpc_closed=rpc.closed,
                consumer=consumer)
    try:
        consumer.stop()
    except Exception:
        pass
    return snap


# ══════════════════════════════════════════════════════════════════════════
#  1. the behaviour being fixed, against the shipped library
# ══════════════════════════════════════════════════════════════════════════

class TestWhatOneThrowDoesToAListener:

    def test_unguarded_one_throw_ends_the_listener_for_good(self):
        """⛔⛔ THE DEFECT. Not a claim about the library — this runs it."""
        seen = {"n": 0}

        def raises_on_the_third(_r):
            seen["n"] += 1
            if seen["n"] == 3:
                raise AttributeError("'NoneType' object has no attribute 'get'")

        ran = _drive(raises_on_the_third)
        assert seen["n"] == 3, (
            f"delivery stopped at {seen['n']} — it should stop at the throw")
        assert ran.consumer_active is False, "the consumer thread should be gone"

    def test_and_nothing_downstream_is_told(self):
        """⛔ The RPC is left looking healthy, so no done-callback fires and no
        close runs. That is why the machine reads ONLINE while it is deaf."""
        def always_raises(_r):
            raise RuntimeError("boom")

        ran = _drive(always_raises)
        assert ran.consumer_active is False
        assert ran.rpc_active is True, "the RPC was left active"
        assert ran.rpc_closed is False, "nothing closed the stream"

    def test_guarded_the_listener_survives_every_throw(self):
        """⭐ THE FIX, MEASURED. Same callback, same library, wrapped."""
        seen = {"n": 0}

        def always_raises(_r):
            seen["n"] += 1
            raise AttributeError("'NoneType' object has no attribute 'get'")

        ran = _drive(research._guard_snapshot(always_raises, "start"))
        assert seen["n"] > 3, (
            f"only {seen['n']} deliveries — the guard did not keep it running")
        assert ran.consumer_active is True, "the consumer thread should still be alive"

    def test_a_guarded_healthy_callback_is_untouched(self):
        seen = []
        ran = _drive(research._guard_snapshot(seen.append, "start"))
        assert len(seen) > 3
        assert ran.consumer_active is True


class TestTheGuardItself:

    def test_it_passes_every_argument_through_unchanged(self):
        """The library calls back with (keys, changes, read_time)."""
        got = []
        research._guard_snapshot(lambda *a: got.append(a), "x")(1, 2, 3)
        assert got == [(1, 2, 3)]

    def test_a_raise_does_not_escape(self):
        def boom(*_a):
            raise ValueError("nope")
        research._guard_snapshot(boom, "x")()  # no raise == the assertion

    def test_even_a_baseexception_subclass_that_is_an_exception_is_held(self):
        def boom(*_a):
            raise MemoryError("out")
        research._guard_snapshot(boom, "x")()

    def test_the_line_names_which_listener_stopped_handling(self, capsys):
        def boom(*_a):
            raise ValueError("inner cause")
        research._guard_snapshot(boom, "device-cmds")()
        out = capsys.readouterr().out
        assert "[watch:device-cmds]" in out
        assert "ValueError: inner cause" in out

    def test_it_says_the_listener_is_still_attached(self, capsys):
        """⛔ Without that clause the line reads like the outage it prevents."""
        research._guard_snapshot(lambda *a: (_ for _ in ()).throw(ValueError()), "start")()
        assert "still attached" in capsys.readouterr().out

    def test_every_traceback_line_is_timestamped_and_levelled(self, capsys):
        """⛔ A multi-line record through one print is how a log grows orphan
        lines — the same rule the stdlib bridge was written for."""
        def boom(*_a):
            raise ValueError("inner cause")
        research._guard_snapshot(boom, "commands")()
        lines = [x for x in capsys.readouterr().out.splitlines() if x.strip()]
        assert len(lines) >= 4
        assert all(re.match(r"^\[\d\d:\d\d:\d\d\] \[ERROR\] \[watch:commands\] ", x)
                   for x in lines), lines
        assert any("Traceback (most recent call last)" in x for x in lines)

    def test_it_is_an_error_not_a_warning(self, capsys):
        """A dropped Start is not a routine scan failure, and the log level is
        the only thing that separates the two for a reader."""
        research._guard_snapshot(lambda *a: 1 / 0, "start")()
        assert "[WARN]" not in capsys.readouterr().out


class TestEveryListenerIsWrapped:

    @pytest.mark.parametrize("fn,label", [
        ("_start_device_command_listener", "device-cmds"),
        ("start_firestore_start_listener", "start"),
        ("_start_command_listener", "commands"),
    ])
    def test_the_registration_site_wraps_its_callback(self, fn, label):
        src = code_only_deep(getattr(research, fn))
        assert '_guard_snapshot(' in src and f'"{label}"' in src, (
            f"{fn} attaches a bare callback — one throw ends that listener")

    def test_no_snapshot_is_attached_without_the_guard(self):
        """⭐ THE CLASS GUARD. A fourth listener added later gets caught here
        rather than in a support bundle six weeks after it stops working."""
        src = inspect.getsource(research)
        bare = [m.group(0) for m in re.finditer(r"\.on_snapshot\((?!_guard_snapshot)[^)]*\)", src)]
        assert not bare, f"un-guarded snapshot registrations: {bare}"

    def test_the_three_labels_are_the_three_dead_watch_names(self):
        """The label a throw prints and the name a re-arm prints must be the
        same word, or the two halves of one incident read as two incidents."""
        src = code_only_deep(research._dead_watch_names)
        for label in ("start", "device-cmds", "commands"):
            assert f'"{label}"' in src


# ══════════════════════════════════════════════════════════════════════════
#  2. noticing a watch that stopped
# ══════════════════════════════════════════════════════════════════════════

class _Handle:
    def __init__(self, active):
        self.is_active = active
        self.unsubscribed = 0

    def unsubscribe(self):
        self.unsubscribed += 1


class TestSpottingADeadWatch:

    def test_a_live_watch_is_not_dead(self):
        assert research._watch_is_dead(_Handle(True)) is False

    def test_a_stopped_watch_is_dead(self):
        assert research._watch_is_dead(_Handle(False)) is True

    def test_a_handle_we_never_had_is_not_a_fault(self):
        """⛔ None is "not attached", which is the ordinary state between runs
        and after a deliberate unsubscribe. Reading it as dead would re-arm
        listeners this process took down on purpose."""
        assert research._watch_is_dead(None) is False

    def test_something_with_no_is_active_is_left_alone(self):
        """A future library shape, or a test double, must not be able to drive
        an endless re-arm."""
        assert research._watch_is_dead(object()) is False

    def test_a_property_that_raises_is_left_alone(self):
        class Angry:
            @property
            def is_active(self):
                raise RuntimeError("gone")
        assert research._watch_is_dead(Angry()) is False

    def test_it_reads_the_librarys_own_answer(self):
        """⭐ Against the real BackgroundConsumer, whose `is_active` is what
        `Watch.is_active` delegates to. A dead thread reads dead."""
        ran = _drive(lambda *_a: (_ for _ in ()).throw(ValueError()))
        assert research._watch_is_dead(ran.consumer) is True


class TestWhichWatchesAreDead:

    @pytest.fixture(autouse=True)
    def _clean_globals(self, monkeypatch):
        monkeypatch.setattr(research, "_start_listener", None, raising=False)
        monkeypatch.setattr(research, "_device_cmd_watch", None, raising=False)
        monkeypatch.setattr(research, "_fb_listener", None, raising=False)

    def test_nothing_attached_is_nothing_dead(self):
        assert research._dead_watch_names() == []

    def test_all_healthy_is_nothing_dead(self, monkeypatch):
        for g in ("_start_listener", "_device_cmd_watch", "_fb_listener"):
            monkeypatch.setattr(research, g, _Handle(True), raising=False)
        assert research._dead_watch_names() == []

    @pytest.mark.parametrize("g,name", [
        ("_start_listener", "start"),
        ("_device_cmd_watch", "device-cmds"),
        ("_fb_listener", "commands"),
    ])
    def test_each_watch_is_reported_under_its_own_name(self, monkeypatch, g, name):
        monkeypatch.setattr(research, g, _Handle(False), raising=False)
        assert research._dead_watch_names() == [name]

    def test_all_three_can_be_dead_at_once(self, monkeypatch):
        for g in ("_start_listener", "_device_cmd_watch", "_fb_listener"):
            monkeypatch.setattr(research, g, _Handle(False), raising=False)
        assert research._dead_watch_names() == ["start", "device-cmds", "commands"]


# ══════════════════════════════════════════════════════════════════════════
#  3. putting it back
# ══════════════════════════════════════════════════════════════════════════

class TestReArming:

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.setattr(research, "_start_listener", None, raising=False)
        monkeypatch.setattr(research, "_device_cmd_watch", None, raising=False)
        monkeypatch.setattr(research, "_fb_listener", None, raising=False)
        monkeypatch.setattr(research, "_watch_rebinder", None, raising=False)
        monkeypatch.setattr(research, "_fb_uid", None, raising=False)
        monkeypatch.setattr(research, "_fb_research_id", None, raising=False)
        monkeypatch.setattr(research, "_controls", object(), raising=False)
        monkeypatch.setattr(research, "_watch_rearm_last_at", 0.0, raising=False)

    def test_the_long_lived_pair_goes_through_the_rebinder(self, monkeypatch):
        calls = []
        monkeypatch.setattr(research, "_watch_rebinder", lambda: calls.append(1))
        back = research._rearm_dead_watches(["start", "device-cmds"], None)
        assert calls == [1], "the rebinder was not called"
        assert back == ["start", "device-cmds"]

    def test_one_of_the_pair_still_rebinds_both(self, monkeypatch):
        """They share one tested path, which unsubscribes and re-attaches the
        pair together. Reporting only what was asked for would understate it."""
        monkeypatch.setattr(research, "_watch_rebinder", lambda: None)
        assert research._rearm_dead_watches(["device-cmds"], None) == ["device-cmds"]

    def test_with_no_rebinder_it_says_so_and_does_not_pretend(self, capsys, monkeypatch):
        monkeypatch.setattr(research, "_watch_rebinder", None)
        assert research._rearm_dead_watches(["start"], None) == []
        out = capsys.readouterr().out
        assert "restart the backend" in out

    def test_a_rebinder_that_raises_does_not_escape(self, monkeypatch, capsys):
        def boom():
            raise RuntimeError("attach refused")
        monkeypatch.setattr(research, "_watch_rebinder", boom)
        assert research._rearm_dead_watches(["start"], None) == []
        assert "attach refused" in capsys.readouterr().out

    def test_the_command_listener_re_arms_from_the_live_run(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(research, "_fb_uid", "u1")
        monkeypatch.setattr(research, "_fb_research_id", "r1")
        monkeypatch.setattr(research, "_start_command_listener",
                            lambda u, r, loop: seen.update(uid=u, rid=r, loop=loop))
        assert research._rearm_dead_watches(["commands"], "LOOP") == ["commands"]
        assert seen == {"uid": "u1", "rid": "r1", "loop": "LOOP"}

    def test_the_dead_command_handle_is_dropped_before_re_attaching(self, monkeypatch):
        """⛔ Same discipline as the pair's rebind: null the global BETWEEN the
        unsubscribe and the attach, so a failure part way through cannot leave a
        handle to a stream that is already gone."""
        old = _Handle(False)
        monkeypatch.setattr(research, "_fb_listener", old)
        monkeypatch.setattr(research, "_fb_uid", "u1")
        monkeypatch.setattr(research, "_fb_research_id", "r1")
        seen = {}
        monkeypatch.setattr(research, "_start_command_listener",
                            lambda u, r, loop: seen.update(at_attach=research._fb_listener))
        research._rearm_dead_watches(["commands"], None)
        assert old.unsubscribed == 1, "the dead handle was never unsubscribed"
        assert seen["at_attach"] is None, "the stale handle was still in place"

    def test_an_unsubscribe_that_raises_still_re_attaches(self, monkeypatch):
        """A stream torn down by the fault raises here; that is the ordinary
        case, not a reason to leave the run without a Stop button."""
        class Angry(_Handle):
            def unsubscribe(self):
                raise RuntimeError("already closed")
        monkeypatch.setattr(research, "_fb_listener", Angry(False))
        monkeypatch.setattr(research, "_fb_uid", "u1")
        monkeypatch.setattr(research, "_fb_research_id", "r1")
        monkeypatch.setattr(research, "_start_command_listener", lambda u, r, loop: None)
        assert research._rearm_dead_watches(["commands"], None) == ["commands"]

    def test_a_torn_down_run_is_not_re_armed(self, monkeypatch, capsys):
        """⛔ `_fb_uid` is nulled by teardown, so a command listener that stops
        AS the run ends has nothing to re-attach to. Re-arming on a stale id
        would subscribe to a research that is over."""
        called = []
        monkeypatch.setattr(research, "_start_command_listener",
                            lambda *a, **k: called.append(1))
        assert research._rearm_dead_watches(["commands"], None) == []
        assert called == []

    def test_a_command_attach_that_raises_does_not_escape(self, monkeypatch, capsys):
        monkeypatch.setattr(research, "_fb_uid", "u1")
        monkeypatch.setattr(research, "_fb_research_id", "r1")

        def boom(*_a, **_k):
            raise RuntimeError("attach refused")
        monkeypatch.setattr(research, "_start_command_listener", boom)
        assert research._rearm_dead_watches(["commands"], None) == []
        assert "attach refused" in capsys.readouterr().out

    def test_the_two_halves_are_independent(self, monkeypatch):
        """A missing rebinder must not cost the run its Stop button."""
        monkeypatch.setattr(research, "_watch_rebinder", None)
        monkeypatch.setattr(research, "_fb_uid", "u1")
        monkeypatch.setattr(research, "_fb_research_id", "r1")
        monkeypatch.setattr(research, "_start_command_listener", lambda u, r, loop: None)
        assert research._rearm_dead_watches(["start", "commands"], None) == ["commands"]


class TestThePerPassCheck:

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.setattr(research, "_start_listener", None, raising=False)
        monkeypatch.setattr(research, "_device_cmd_watch", None, raising=False)
        monkeypatch.setattr(research, "_fb_listener", None, raising=False)
        monkeypatch.setattr(research, "_watch_rearm_last_at", 0.0, raising=False)

    def _armed(self, monkeypatch, result=("start",)):
        calls = []
        monkeypatch.setattr(research, "_rearm_dead_watches",
                            lambda names, loop: (calls.append(list(names)), list(result))[1])
        return calls

    @pytest.mark.asyncio
    async def test_a_healthy_machine_does_nothing_and_says_nothing(self, monkeypatch, capsys):
        calls = self._armed(monkeypatch)
        monkeypatch.setattr(research, "_start_listener", _Handle(True))
        assert await research._rearm_dead_watches_if_any() == []
        assert calls == []
        assert capsys.readouterr().out == ""

    @pytest.mark.asyncio
    async def test_a_dead_watch_is_named_and_re_armed(self, monkeypatch, capsys):
        calls = self._armed(monkeypatch)
        monkeypatch.setattr(research, "_start_listener", _Handle(False))
        assert await research._rearm_dead_watches_if_any() == ["start"]
        assert calls == [["start"]]
        assert "start" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_it_says_what_happened_before_it_repairs_it(self, monkeypatch, capsys):
        """⭐ THE LINE THAT EXPLAINS THE INCIDENT. A machine that answered every
        health check and never started the run someone asked for has exactly one
        sentence written about it, and a repair that logs only its own success
        leaves that sentence unwritten."""
        printed = []
        monkeypatch.setattr(research, "_rearm_dead_watches",
                            lambda names, loop: (printed.append(capsys.readouterr().out),
                                                 ["start"])[1])
        monkeypatch.setattr(research, "_start_listener", _Handle(False))
        await research._rearm_dead_watches_if_any()
        assert "stopped delivering" in printed[0], (
            "nothing was logged before the repair ran")
        assert "online" in printed[0]

    @pytest.mark.asyncio
    async def test_a_second_pass_inside_the_gap_does_not_re_arm_again(
            self, monkeypatch):
        """⛔ THE THRASH GUARD. This runs on a five-second loop, and a watch that
        comes back dead would otherwise be torn down and re-attached twelve
        times a minute for as long as the fault lasts."""
        calls = self._armed(monkeypatch)
        monkeypatch.setattr(research, "_start_listener", _Handle(False))
        await research._rearm_dead_watches_if_any()
        assert await research._rearm_dead_watches_if_any() == []
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_but_it_tries_again_once_the_gap_has_passed(self, monkeypatch):
        calls = self._armed(monkeypatch)
        monkeypatch.setattr(research, "_start_listener", _Handle(False))
        await research._rearm_dead_watches_if_any()
        monkeypatch.setattr(
            research, "_watch_rearm_last_at",
            time.time() - research._WATCH_REARM_MIN_GAP_SEC - 1)
        await research._rearm_dead_watches_if_any()
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_the_first_attempt_is_immediate(self, monkeypatch):
        """The gap is a floor on retries, not a delay before the first one — a
        minute of a dead Start button is a minute too many."""
        calls = self._armed(monkeypatch)
        monkeypatch.setattr(research, "_start_listener", _Handle(False))
        await research._rearm_dead_watches_if_any()
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_a_re_arm_that_raises_does_not_take_the_loop_down(
            self, monkeypatch, capsys):
        """This is awaited from the loop that keeps the machine reachable."""
        def boom(_names, _loop):
            raise RuntimeError("thread pool refused")
        monkeypatch.setattr(research, "_rearm_dead_watches", boom)
        monkeypatch.setattr(research, "_start_listener", _Handle(False))
        assert await research._rearm_dead_watches_if_any() == []
        assert "thread pool refused" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_it_runs_off_the_event_loop(self, monkeypatch):
        """⛔ `_rearm_dead_watches` unsubscribes watches, which stops and JOINS
        a background thread. Called inline it would stall the heartbeat, which
        is how a repair turns into a device the app reports as offline."""
        where = {}
        import threading
        monkeypatch.setattr(
            research, "_rearm_dead_watches",
            lambda names, loop: (where.update(t=threading.current_thread().name), [])[1])
        monkeypatch.setattr(research, "_start_listener", _Handle(False))
        await research._rearm_dead_watches_if_any()
        assert where["t"] != threading.main_thread().name, (
            "the re-arm ran on the event loop's thread")


def test_the_stamp_this_module_starts_with_allows_an_immediate_first_try():
    """⛔ FOUND BY MUTATION. Starting the stamp at `time.time()` rather than 0
    turns the retry floor into a wait before the FIRST attempt, and every test
    above resets the global in its own fixture — so all of them agreed the first
    try was immediate while the shipped module would have slept a minute on it.
    A fixture that makes a test predictable can also make it blind."""
    assert time.time() - _STAMP_AT_IMPORT > research._WATCH_REARM_MIN_GAP_SEC, (
        "the module starts with a stamp recent enough to delay the first re-arm")


def test_no_test_in_this_suite_is_nested_inside_another_function():
    """⛔⛔ FOUND THE HARD WAY, 2026-08-22. A module-level function inserted into
    the middle of a class body closes the class, and every method after it
    becomes a NESTED function — valid Python, silently never collected. Two
    tests in this file disappeared that way, the file still ran green, and the
    only symptom was a mutant surviving that had been killed an hour earlier.

    Repo-wide because nothing about it is specific to this file: pytest reports
    a smaller number and no error at all."""
    import ast
    root = Path(__file__).resolve().parent
    nested = []

    def walk(node, depth):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.name.startswith("test_") and depth > 0:
                    nested.append(f"{path.name}:{child.lineno} {child.name}")
                walk(child, depth + 1)
            elif isinstance(child, ast.ClassDef):
                walk(child, depth)
            else:
                walk(child, depth)

    for path in sorted(root.rglob("test_*.py")):
        walk(ast.parse(path.read_text(encoding="utf-8")), 0)
    assert not nested, (
        "these tests are defined inside another function and are never run:\n"
        + "\n".join(nested))


def test_the_reconnect_loop_checks_while_firestore_is_HEALTHY():
    """⛔⛔ THE WHOLE POINT, AND THE EASIEST THING TO GET WRONG. Everything else
    in that loop hangs off `_firebase_db` having gone None. A watch that dies
    while the client stays healthy is exactly the case with no cover, so the
    check has to sit in the branch that runs when nothing is wrong."""
    src = code_only_deep(research._firebase_reconnect_loop)
    healthy = src.split("if _firebase_db is not None:", 1)
    assert len(healthy) == 2, "the healthy branch has been reworded"
    body = healthy[1].split("if _firebase_db is None", 1)[0]
    assert "_rearm_dead_watches_if_any()" in body, (
        "the dead-watch check is not in the branch that runs while Firestore is up")


def test_the_check_is_awaited_not_merely_called():
    """A coroutine left un-awaited never runs, and would warn on stderr — the
    stream this wave exists to stop relying on."""
    src = code_only_deep(research._firebase_reconnect_loop)
    assert "await _rearm_dead_watches_if_any()" in src


# ══════════════════════════════════════════════════════════════════════════
#  4. the death notice reaches the log people are asked to send
# ══════════════════════════════════════════════════════════════════════════

_VENDOR = "google.api_core.bidi"


@pytest.fixture
def _fresh_vendor_bridge():
    """Detach every logger the installer touches, run, put them all back.

    ⛔⛔ IT COVERED ONLY THE VENDOR LOGGER AT FIRST, and that leaked. Installing
    the bridge sets `propagate = False` on OUR five as well; pytest reacts to a
    non-propagating logger by attaching its own capture handler DIRECTLY to it
    at the next test's setup — and that handler re-raises on a format error. So
    a pre-existing test three files away, `test_a_broken_format_string_does_not_
    take_the_process_down`, failed whenever this file had run first and passed
    whenever it had not. A leak that only shows up in another file's result is
    the worst kind to leave behind."""
    names = (*research._BRIDGED_LOGGERS, *research._BRIDGED_VENDOR_LOGGERS)
    saved = {}
    for name in names:
        lg = logging.getLogger(name)
        saved[name] = (list(lg.handlers), lg.level, lg.propagate)
        lg.handlers = [h for h in lg.handlers
                       if not isinstance(h, research._StdlibLogBridge)]
    yield logging.getLogger(_VENDOR)
    for name, (handlers, level, propagate) in saved.items():
        lg = logging.getLogger(name)
        lg.handlers = handlers
        lg.level = level
        lg.propagate = propagate


class TestTheOnlyLoggerThatSaysAListenerDied:

    def test_the_bidi_logger_is_bridged(self):
        """⛔⛔ It was not. Four consumer deaths sit in this machine's
        `backend.err.log` and none of them is in `backend.log` — the notice that
        Start and Stop have stopped arriving lands in the half of the logs a
        person is never asked to send."""
        assert _VENDOR in research._BRIDGED_VENDOR_LOGGERS

    def test_it_is_bridged_at_warning_not_debug(self, _fresh_vendor_bridge):
        """⚠ Ours are bridged at DEBUG because every line they write is wanted.
        This one logs `waiting for recv.` once per message received."""
        assert research._BRIDGED_VENDOR_LOGGERS[_VENDOR] == logging.WARNING
        research._install_stdlib_log_bridge()
        assert _fresh_vendor_bridge.level == logging.WARNING

    def test_our_own_loggers_are_still_debug(self, _fresh_vendor_bridge):
        research._install_stdlib_log_bridge()
        for name in research._BRIDGED_LOGGERS:
            assert logging.getLogger(name).level == logging.DEBUG

    def test_a_vendor_logger_is_never_one_of_ours(self):
        """Two lists, one installer. Overlap would make the level ambiguous."""
        assert not (set(research._BRIDGED_VENDOR_LOGGERS)
                    & set(research._BRIDGED_LOGGERS))

    def test_the_death_notice_reaches_the_one_writer(self, capsys, _fresh_vendor_bridge):
        research._install_stdlib_log_bridge()
        logging.getLogger(_VENDOR).warning(
            "Thread-ConsumeBidirectionalStream caught unexpected exception "
            "%s and will exit.", "'NoneType' object is not callable")
        out = capsys.readouterr()
        assert "[WARN] [google.api_core.bidi] Thread-ConsumeBidirectionalStream" in out.out
        assert out.err == "", "it still reaches bare stderr"

    def test_its_per_message_chatter_stays_out(self, capsys, _fresh_vendor_bridge):
        """⭐ The reason for the level. `log()` has no filter of its own, so a
        DEBUG-bridged transport logger would write a line per received message
        into the file a person is asked to send."""
        research._install_stdlib_log_bridge()
        logging.getLogger(_VENDOR).debug("waiting for recv.")
        assert "waiting for recv." not in capsys.readouterr().out

    def test_propagation_is_off(self, _fresh_vendor_bridge):
        research._install_stdlib_log_bridge()
        assert _fresh_vendor_bridge.propagate is False

    def test_installing_twice_attaches_once(self, _fresh_vendor_bridge):
        research._install_stdlib_log_bridge()
        research._install_stdlib_log_bridge()
        assert sum(isinstance(h, research._StdlibLogBridge)
                   for h in _fresh_vendor_bridge.handlers) == 1

    def test_the_bridged_name_is_the_module_the_library_logs_under(self):
        """⛔ A logger name that does not exist bridges nothing, and there is no
        error to notice. Read it off the shipped library rather than trusting
        the string."""
        from google.api_core import bidi
        assert bidi._LOGGER.name == _VENDOR
