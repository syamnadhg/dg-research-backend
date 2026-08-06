"""Ctrl+C on the supervisor stops the workers — and waits for them.

The owner's report: "I started serve and Ctrl+C'd it, but these still exist." The
processes that actually survived that day were a supervisor I had started from a
detached background shell — no controlling terminal, so a terminal SIGINT could
never have reached it. But digging into it surfaced two real defects on the way:

  1. `run_daemon_loop`'s docstring claimed "The --serve child process is NOT killed
     — it stays alive so the current pipeline finishes." That was already untrue of
     the multi-worker branch, which had been terminating its workers on
     KeyboardInterrupt. A stale docstring is worse than none: it is what sent the
     investigation down the wrong path in the first place.
  2. The handler called `terminate()` and returned IMMEDIATELY. SIGTERM is a
     request, so a worker draining uvicorn or tearing down Chromium can outlive the
     supervisor that asked it to stop — which from the outside looks exactly like
     "Ctrl+C didn't stop anything", the report itself.

Owner's decision, recorded: Ctrl+C stops the workers. Accepted cost: an in-flight
pipeline is aborted. `--retire` stays the out-of-band stop.

⚠ These drive `_terminate_worker_fleet` with fake process handles rather than
scanning `run_daemon_loop` for the call. A terminate-and-return-anyway version would
satisfy every string assertion — which is the same lesson the drift wave paid for.
"""

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402


class _Proc:
    """A worker handle. `deaths_after` is how many `wait()` calls it survives.

    `None` means it never dies on SIGTERM — the wedged worker the escalation to
    SIGKILL exists for.

    ⚠ `wait()` CONSUMES ITS TIMEOUT when it is going to time out. The first version
    returned instantly, which made the shared-deadline test meaningless: with no time
    passing, `deadline - monotonic()` never shrank, so a per-worker grace and a shared
    one granted the same numbers and the mutant survived. A fake that cannot spend time
    cannot test a deadline. Every granted timeout is also recorded, because the wall
    clock is the flaky way to assert this and the granted values are the exact way.
    """

    def __init__(self, pid, deaths_after=0):
        self.pid = pid
        self._deaths_after = deaths_after
        self.terminated = 0
        self.killed = 0
        self.waits = 0
        self.timeouts = []
        self._alive = True

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1
        self._alive = False

    def _timeout(self, timeout):
        import time as _t
        self.timeouts.append(timeout)
        if timeout:
            _t.sleep(min(float(timeout), 2.0))
        raise subprocess.TimeoutExpired("serve", timeout)

    def wait(self, timeout=None):
        self.waits += 1
        if not self.terminated and not self.killed:
            self._timeout(timeout)
        if self.killed:
            self.timeouts.append(timeout)
            return -9
        if self._deaths_after is None or self.waits <= self._deaths_after:
            self._timeout(timeout)
        self.timeouts.append(timeout)
        self._alive = False
        return 0

    @property
    def alive(self):
        return self._alive


class _FH:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _fleet(*specs):
    """specs: (key, deaths_after) — or (key, deaths_after, dead=True)."""
    out = {}
    for spec in specs:
        k, deaths, *rest = spec
        if rest and rest[0]:
            out[k] = {"_dead": True}
            continue
        out[k] = {"process": _Proc(9000 + k, deaths), "out_fh": _FH(),
                  "err_fh": _FH(), "port": 8000 + k - 1}
    return out


def _stop(workers, reason="Interrupted (Ctrl+C)", grace_s=0.0):
    lines = []
    exited, forced = research._terminate_worker_fleet(
        workers, reason, grace_s=grace_s,
        log_fn=lambda m, lvl="INFO": lines.append((lvl, m)))
    return exited, forced, lines


def test_every_live_worker_is_asked_to_stop():
    workers = _fleet((1, 0), (2, 0), (3, 0))
    exited, forced, _ = _stop(workers)
    assert exited == 3 and forced == 0
    for st in workers.values():
        assert st["process"].terminated == 1
        assert st["process"].killed == 0
        assert not st["process"].alive


def test_a_worker_that_ignores_sigterm_is_killed():
    """The whole point of waiting. A worker that never honours SIGTERM used to
    outlive the supervisor that asked it to stop."""
    workers = _fleet((1, 0), (2, None))
    exited, forced, lines = _stop(workers)
    assert exited == 1 and forced == 1
    assert workers[2]["process"].killed == 1
    assert not workers[2]["process"].alive
    assert any("still alive" in m and lvl == "WARN" for lvl, m in lines), lines


def test_it_does_not_return_while_a_worker_is_still_running():
    """The defect, stated as the property it violated: the old handler called
    terminate() and returned, so the supervisor's own exit raced the workers'."""
    workers = _fleet((1, None), (2, None), (3, None))
    _stop(workers)
    assert not any(st["process"].alive for st in workers.values())


def test_a_killed_worker_is_reaped_not_left_a_zombie():
    """An unreaped SIGKILLed child is a zombie for as long as this supervisor
    lives — and a zombie shows up in the process list, which is the symptom."""
    workers = _fleet((1, None))
    _stop(workers)
    proc = workers[1]["process"]
    assert proc.killed == 1
    assert proc.waits >= 2, "kill must be followed by a wait that reaps it"


def test_a_worker_already_marked_dead_is_not_touched():
    """`{"_dead": True}` slots have no handle at all; treating one as live would
    raise inside the handler that is trying to shut down cleanly."""
    workers = _fleet((1, 0), (2, 0, True))
    exited, forced, _ = _stop(workers)
    assert exited == 1 and forced == 0


def test_an_empty_or_missing_fleet_is_not_an_error():
    for empty in ({}, None, {1: None}, {1: {"process": None}}):
        exited, forced, lines = _stop(empty)
        assert (exited, forced) == (0, 0)
        assert any("no live workers" in m for _lvl, m in lines), lines


def test_the_grace_period_is_shared_not_per_worker():
    """Three wedged workers must not take 3× the grace. One deadline for the fleet —
    otherwise a large worker count turns Ctrl+C into a long wait, and a Ctrl+C that
    appears to hang is the report this came from.

    Asserted on the TIMEOUTS GRANTED, not the wall clock: the granted values are the
    thing the shared deadline actually controls, and a wall-clock bound on a loaded
    machine is the flaky way to ask the same question. The first worker may take the
    whole grace; by the time the third is reached there must be nothing left.
    """
    grace = 0.3
    workers = _fleet((1, None), (2, None), (3, None))
    _stop(workers, grace_s=grace)
    granted = [st["process"].timeouts[0] for _k, st in sorted(workers.items())]
    assert granted[0] <= grace + 0.01, granted
    assert granted == sorted(granted, reverse=True), (
        f"the deadline is not shared — each worker was granted its own grace: {granted}")
    assert sum(granted) <= grace + 0.05, (
        f"the fleet spent {sum(granted):.2f}s of a {grace}s budget: {granted}")
    assert granted[-1] < grace / 2, granted


def test_the_whole_grace_still_goes_to_a_lone_wedged_worker():
    """The other side of one shared deadline: a single worker must not be shortchanged
    by the accounting that bounds three."""
    workers = _fleet((1, None))
    _stop(workers, grace_s=0.3)
    assert workers[1]["process"].timeouts[0] == pytest.approx(0.3, abs=0.02)


def test_the_log_says_who_had_to_be_forced():
    """"Forced" is the operational signal that a worker's own shutdown is wedged.
    A summary that only said "stopped 3 workers" would hide it."""
    workers = _fleet((1, 0), (2, None))
    _e, _f, lines = _stop(workers)
    summary = [m for _lvl, m in lines if "exited on request" in m]
    assert len(summary) == 1, lines
    assert "1 worker(s) exited on request" in summary[0]
    assert "1 needed SIGKILL" in summary[0]


def test_the_user_is_told_the_run_is_being_aborted():
    """The accepted cost has to be visible where it happens. A run dying without a
    word is how "Ctrl+C corrupted my run" reports start."""
    workers = _fleet((1, 0))
    _e, _f, lines = _stop(workers)
    assert any("aborted" in m for _lvl, m in lines), lines


def test_log_handles_are_closed():
    workers = _fleet((1, 0), (2, None))
    _stop(workers)
    for st in workers.values():
        assert st["out_fh"].closed and st["err_fh"].closed


def test_a_terminate_that_raises_does_not_abandon_the_rest_of_the_fleet():
    """One dead handle must not leave two live workers running."""
    workers = _fleet((1, 0), (2, 0))

    def _boom():
        raise OSError("handle gone")

    workers[1]["process"].terminate = _boom
    _stop(workers)
    assert workers[2]["process"].terminated == 1


# ── Wiring: the helper is reached from both exits of the multi-worker loop. ──

def test_ctrl_c_and_a_loop_crash_both_stop_the_fleet():
    src = inspect.getsource(research.run_daemon_loop)
    assert 'except KeyboardInterrupt:\n            _terminate_worker_fleet(' in src, (
        "the Ctrl+C handler must go through the waiting terminator")
    assert src.count("_terminate_worker_fleet(workers,") == 2, (
        "both the interrupt and the loop-crash exit must stop the fleet — the crash "
        "path especially, since it exists so a respawn can rebind ports 8000+")


def test_no_bare_terminate_survives_in_the_shutdown_handlers():
    """The shape that was wrong: `state["process"].terminate()` in a loop with no
    wait. The watchdog's own single-worker terminate is a different thing (it
    respawns that worker deliberately) and stays."""
    src = inspect.getsource(research.run_daemon_loop)
    for handler in ("except KeyboardInterrupt:", "except Exception as _mw_err:"):
        i = src.index(handler)
        block = src[i:src.index("            return", i)]
        assert 'state["process"].terminate()' not in block, block


def test_the_docstring_states_the_behaviour_the_code_has():
    """This is not cosmetic. The old sentence — "The --serve child process is NOT
    killed — it stays alive so the current pipeline finishes" — was false for the
    multi-worker branch and is what misdirected the investigation.

    ⚠ Asserting the LIVE CLAIM, not the absence of the old words: the docstring
    quotes the retracted sentence on purpose, so that whoever reads it next knows the
    behaviour changed rather than wondering whether it ever worked. A bare
    `"NOT killed" not in doc` would forbid that history.
    """
    doc = research.run_daemon_loop.__doc__ or ""
    # The retracted claim survives ONLY inside the paragraph that retracts it.
    head, _, retraction = doc.partition("said the opposite")
    assert retraction, "the docstring must say what it is correcting"
    assert "NOT killed" not in head, head
    assert "CTRL+C STOPS THE WORKERS TOO" in doc
    assert "in-flight pipeline is" in doc, "the accepted cost must be stated"
    assert "retire" in doc.lower(), "the out-of-band alternative must still be named"


# ── The other half: a stopped worker must take Chromium with it. ──

def test_serve_registers_a_child_reap_for_a_graceful_exit():
    """uvicorn handles SIGTERM as a GRACEFUL shutdown: the server loop returns,
    `run_server` returns, and the interpreter exits normally — noticing nothing
    about the patchright node driver or the Chromium hanging off it. Those orphan,
    and an orphaned Chromium still holds the profile lock, so the next worker starts
    against a wedged profile.

    `atexit` is the right hook because it fires on that normal exit and NOT on
    `os._exit` (which reaps explicitly already) or SIGKILL (where nothing can run).
    """
    src = inspect.getsource(research.main)
    i = src.index("if args.serve:")
    block = src[i:src.index("asyncio.run(run_server(", i)]
    assert "_atexit.register(_reap_child_processes" in block, block


def test_the_in_process_exit_path_still_reaps_explicitly():
    """Pins that the atexit hook is an ADDITION, not a replacement — `os._exit`
    skips atexit entirely, so the explicit reap there is still the only thing
    covering the Stop button."""
    src = inspect.getsource(research._schedule_server_exit)
    assert "_reap_child_processes(source, protect_pids)" in src


def test_the_reaper_spares_the_upgrade_waiter():
    """Regression belt for the new caller: the reap must keep honouring
    `protect_pids`, or a Ctrl+C during an update would kill the detached waiter that
    is supposed to outlive us and the version would never move."""
    src = inspect.getsource(research._reap_child_processes)
    assert "if child.pid in _protect:" in src
    assert "continue" in src.split("if child.pid in _protect:")[1][:120]


def test_the_atexit_reap_can_still_see_the_upgrade_waiter(monkeypatch):
    """⚠ A RISK THE ATEXIT HOOK INTRODUCED, closed here. The hook is registered at
    `--serve` startup, long before any upgrade waiter exists, so it cannot be handed
    a `protect_pids` argument. Without a module-level channel, a SIGTERM arriving
    inside the update window — a Ctrl+C, a watchdog respawn — would exit normally,
    run the hook, and SIGKILL the very process whose job is to outlive us. The
    version would never move: exactly the bug the waiter was built to fix.

    Driven with a fake psutil so the protection is proved, not read.
    """
    import types

    killed = []

    class _Child:
        def __init__(self, pid):
            self.pid = pid

        def kill(self):
            killed.append(self.pid)

    class _Me:
        def children(self, recursive=False):
            return [_Child(101), _Child(202), _Child(303)]

    fake = types.SimpleNamespace(Process=lambda _pid: _Me(),
                                 NoSuchProcess=RuntimeError,
                                 AccessDenied=RuntimeError)
    monkeypatch.setitem(sys.modules, "psutil", fake)
    monkeypatch.setattr(research, "_ALWAYS_PROTECTED_PIDS", {202})

    # No argument at all — exactly how atexit calls it.
    n = research._reap_child_processes("serve-exit")
    assert 202 not in killed, "the upgrade waiter was reaped"
    assert sorted(killed) == [101, 303]
    assert n == 2


def test_an_explicit_protect_list_still_works_alongside_the_set(monkeypatch):
    import types

    killed = []

    class _Child:
        def __init__(self, pid):
            self.pid = pid

        def kill(self):
            killed.append(self.pid)

    fake = types.SimpleNamespace(
        Process=lambda _pid: types.SimpleNamespace(
            children=lambda recursive=False: [_Child(1), _Child(2), _Child(3)]),
        NoSuchProcess=RuntimeError, AccessDenied=RuntimeError)
    monkeypatch.setitem(sys.modules, "psutil", fake)
    monkeypatch.setattr(research, "_ALWAYS_PROTECTED_PIDS", {2})
    research._reap_child_processes("device-update", protect_pids={3})
    assert killed == [1]


def test_the_waiter_is_registered_the_instant_it_is_spawned():
    """Order, because the window is the bug: anything between the Popen and the
    registration is time in which a reap would abort the update. And this path does
    real work right after — it kills leftover backend processes to free the venv."""
    src = inspect.getsource(research._spawn_detached_lifecycle)
    spawn = src.index("waiter_pid = _proc.pid")
    reg = src.index("_ALWAYS_PROTECTED_PIDS.add(waiter_pid)")
    free = src.index("free_venv =")
    assert spawn < reg < free, (spawn, reg, free)
