"""An upgrade that hangs must leave nothing of itself behind.

The waiter's twenty-minute ceiling turned "hangs forever" into a reported failure —
but it killed the wrong thing. `subprocess.run(timeout=)` kills only the process it
started, and the process it starts is a FRONT-END: pipx shells out to pip or uv, so
the thing holding the network read, the lock, or the venv is a GRANDCHILD, and it
survived the timeout that claimed to have handled it.

On Windows that is not untidiness. `free_venv` is true on the app-driven path there,
so the daemon-loop has already been killed and the restart leg is skipped on a
nonzero rc — leaving the box OFFLINE with a surviving grandchild holding the venv's
DLLs open, which is precisely what makes the next repair attempt fail the same way.

So these tests RUN the real waiter script against a real package-manager stand-in
that really does spawn a grandchild, and ask the operating system whether it is gone.
The old code passes every source-shape assertion about this and fails here.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import research
from conftest import code_only


WAITER = research._LIFECYCLE_WAITER

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX process groups; the Windows leg is taskkill /T and needs a Windows box",
)


# A package manager that hangs, having first spawned a child that also hangs — the
# shape of pipx delegating to pip/uv. The grandchild records its own pid so the test
# can ask the OS about it directly rather than trusting the waiter's report.
_HANGING_PM = r'''
import os, subprocess, sys, time
gpid_file = sys.argv[1]
kid = subprocess.Popen([sys.executable, "-c",
                        "import os,sys,time; "
                        "open(sys.argv[1],'w').write(str(os.getpid())); "
                        "time.sleep(600)",
                        gpid_file])
print("fake pipx: installing superresearch", flush=True)
time.sleep(600)
'''

# The same shape, but both processes IGNORE SIGTERM — a package manager holding a
# lock is entitled to, and a kill that stops at TERM would leave this pair running.
_STUBBORN_PM = r'''
import os, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
gpid_file = sys.argv[1]
kid = subprocess.Popen([sys.executable, "-c",
                        "import os,signal,sys,time; "
                        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                        "open(sys.argv[1],'w').write(str(os.getpid())); "
                        "time.sleep(600)",
                        gpid_file])
print("fake pipx: holding a lock and ignoring TERM", flush=True)
time.sleep(600)
'''

_CLEAN_PM = r'''
import sys
print("fake pipx: installed superresearch 0.1.13", flush=True)
sys.exit(0)
'''

_FAILING_PM = r'''
import sys
print("fake pipx: could not find a version that satisfies the requirement", flush=True)
sys.exit(1)
'''


def _write_pm(tmp_path: Path, body: str, name: str = "pm.py") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _exited_pid() -> int:
    """A pid that has already exited, so the waiter's launcher-wait finishes at once
    instead of burning its sixty seconds."""
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    return p.pid


def _patched_waiter(timeout_s: int) -> str:
    """The REAL waiter with two literals shrunk so a test can wait for it.

    Both substitutions are asserted: if either literal is renamed or duplicated the
    test fails loudly rather than quietly running the unmodified twenty-minute
    version and timing out in CI with no explanation."""
    src = WAITER
    out = src.replace("_TIMEOUT_S = 1200", f"_TIMEOUT_S = {timeout_s}")
    assert out != src and out.count(f"_TIMEOUT_S = {timeout_s}") == 1, \
        "the ceiling is no longer a single plain assignment"
    grace = out.replace("time.sleep(2)  # grace", "time.sleep(0)  # grace")
    assert grace != out, "the post-exit grace sleep moved"
    return grace


def _run_waiter(tmp_path: Path, pm_args, *, timeout_s: int = 5, restart=None,
                action: str = "upgrade"):
    """Execute the waiter for real and return (journal records, result dict, log)."""
    journal = tmp_path / "journal.jsonl"
    result = tmp_path / "result.json"
    log = tmp_path / "upgrade.log"
    intent = tmp_path / "intent.json"
    intent.write_text(json.dumps({"action": "upgrade", "waiter_pid": None}), encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "DG_LIFECYCLE_JOURNAL": str(journal),
        "DG_LIFECYCLE_RESULT": str(result),
        "DG_LIFECYCLE_INTENT": str(intent),
        "DG_LIFECYCLE_LOG": str(log),
        "DG_LIFECYCLE_ACTION": action,
        "DG_LIFECYCLE_FROM": "0.1.12",
        "DG_LIFECYCLE_TO": "0.1.13",
    })
    argv = [str(_exited_pid()), *pm_args]
    if restart:
        argv += ["--then--", *restart]
    # stdout into the log file, exactly as the launcher wires it — so the tail the
    # waiter publishes is the package manager's real output.
    with open(log, "wb") as fh:
        subprocess.run([sys.executable, "-c", _patched_waiter(timeout_s), *argv],
                       env=env, stdout=fh, stderr=subprocess.STDOUT,
                       timeout=180, check=False)
    records = [json.loads(line) for line in
               journal.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = json.loads(result.read_text(encoding="utf-8")) if result.exists() else None
    return records, payload, log.read_text(encoding="utf-8", errors="replace")


def _steps(records):
    return [r["step"] for r in records]


def _still_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_gone(pid: int, seconds: float = 8.0) -> bool:
    """Give the OS a moment to reap. A kill is asynchronous; a bare check straight
    after it can see a process that is already dying."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not _still_running(pid):
            return True
        time.sleep(0.1)
    return False


# ── The tree ─────────────────────────────────────────────────────────────────

def test_a_timed_out_upgrade_leaves_no_grandchild_running(tmp_path):
    """⭐ THE ONE THAT MATTERS. pipx is a front-end; the survivor is what holds the
    venv open and makes the next repair fail too."""
    gpid_file = tmp_path / "grandchild.pid"
    pm = _write_pm(tmp_path, _HANGING_PM)
    records, payload, _log = _run_waiter(tmp_path, [sys.executable, str(pm), str(gpid_file)])

    assert gpid_file.exists(), "the stand-in never spawned its grandchild"
    gpid = int(gpid_file.read_text().strip())
    try:
        assert _wait_gone(gpid), (
            f"pid {gpid} outlived the upgrade that spawned it — on Windows this is the "
            f"process that keeps the venv locked and the machine offline"
        )
    finally:
        if _still_running(gpid):
            try:
                os.kill(gpid, signal.SIGKILL)
            except Exception:
                pass

    assert "package_manager_timeout" in _steps(records)
    assert payload["rc"] == 124 and payload["timed_out"] is True
    assert payload["orphaned"] is False, "the kill was confirmed, so nothing is orphaned"


def test_the_timeout_says_the_venv_may_be_half_written(tmp_path):
    """pipx upgrades IN PLACE, so a package manager stopped part-way can leave the
    venv neither build. No exit code records that; the journal has to."""
    gpid_file = tmp_path / "grandchild.pid"
    pm = _write_pm(tmp_path, _HANGING_PM)
    records, _payload, _log = _run_waiter(tmp_path, [sys.executable, str(pm), str(gpid_file)])
    try:
        note = next(r for r in records if r["step"] == "venv_may_be_inconsistent")
    except StopIteration:  # pragma: no cover - the assertion below reports it
        raise AssertionError(f"no half-written warning in {_steps(records)}")
    assert note["killed_tree"] is True
    assert "superresearch --update" in note["repair"]
    if gpid_file.exists():
        gpid = int(gpid_file.read_text().strip())
        if _still_running(gpid):
            os.kill(gpid, signal.SIGKILL)


def test_a_package_manager_that_ignores_TERM_is_still_stopped(tmp_path):
    """The escalation, pinned by execution rather than by reading the loop. A package
    manager holding a lock may legitimately ignore TERM; it must not get to stay."""
    gpid_file = tmp_path / "grandchild.pid"
    pm = _write_pm(tmp_path, _STUBBORN_PM, "stubborn.py")
    _records, payload, _log = _run_waiter(tmp_path, [sys.executable, str(pm), str(gpid_file)])
    assert gpid_file.exists()
    gpid = int(gpid_file.read_text().strip())
    try:
        assert _wait_gone(gpid), f"pid {gpid} ignored TERM and was never escalated to KILL"
    finally:
        if _still_running(gpid):
            os.kill(gpid, signal.SIGKILL)
    assert payload["orphaned"] is False


class _OsStub:
    """Just enough `os` for `_kill_tree`, with signalling neutered.

    ⛔ Deliberately not the real module: the answers under test are "the group is
    ours" and "the probe could not conclude", and reproducing either with a live
    process would mean firing SIGKILL at a group id chosen by arithmetic. This sends
    no signals at all."""

    def __init__(self, *, killpg_error, own_pgid):
        self._killpg_error = killpg_error
        self._own_pgid = own_pgid
        self.signalled: list = []

    def killpg(self, pgid, sig):
        self.signalled.append((pgid, sig))
        raise self._killpg_error

    def getpgid(self, pid):
        return self._own_pgid


def _kill_tree_from_waiter(os_stub):
    """The waiter's own `_kill_tree`, lifted out and made callable.

    Exercised against the real function rather than asserted about in prose, because
    the two answers that matter cannot be produced by a real process — nothing
    survives SIGKILL, and a group we must refuse to touch is our own."""
    import ast as _ast
    tree = _ast.parse(WAITER)
    fn = next(n for n in tree.body
              if isinstance(n, _ast.FunctionDef) and n.name == "_kill_tree")
    # `time` belongs here for the same reason `os` does: the function polls the
    # group-emptiness probe rather than asking it once, because a kill is
    # asynchronous and the immediate answer is "still dying" on any loaded
    # machine. Leaving it out does not make the test stricter — it makes the
    # function raise NameError before reaching the branch under test.
    ns: dict = {"os": os_stub, "sys": sys, "subprocess": subprocess, "time": time}
    exec(compile(_ast.Module(body=[fn], type_ignores=[]), "<waiter>", "exec"), ns)
    return ns["_kill_tree"]


class _NeverDies:
    """A process that reports itself still running, whatever is sent to it."""

    def __init__(self, pid):
        self.pid = pid
        self.kills = 0

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("pm", timeout)

    def poll(self):
        return None

    def kill(self):
        self.kills += 1


def test_a_kill_that_cannot_be_confirmed_is_reported_as_an_orphan():
    """"I could not see it" must never be published as "it is gone" — the operator's
    repair differs (a reboot, not another attempt)."""
    stub = _OsStub(killpg_error=PermissionError("not permitted"), own_pgid=4242)
    kill_tree = _kill_tree_from_waiter(stub)
    fake = _NeverDies(9999)
    assert kill_tree(fake, 5555) is False
    assert stub.signalled, "it must at least have tried"


def test_a_probe_that_cannot_answer_is_not_read_as_a_clean_kill():
    """The front-end exited, so there is nothing left to poll — but the group could
    not be inspected. "I could not look" is not "it is gone", and the difference is
    whether the operator is told a survivor may be holding the venv."""
    stub = _OsStub(killpg_error=PermissionError("not permitted"), own_pgid=4242)
    kill_tree = _kill_tree_from_waiter(stub)

    class _FrontEndGone(_NeverDies):
        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    assert kill_tree(_FrontEndGone(9999), 5555) is False


def test_a_group_already_empty_is_reported_as_cleanly_gone():
    """The one real proof available: once the group holds nothing, `killpg` raises."""
    stub = _OsStub(killpg_error=ProcessLookupError(), own_pgid=4242)
    kill_tree = _kill_tree_from_waiter(stub)

    class _Exited(_NeverDies):
        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    assert kill_tree(_Exited(9999), 5555) is True


def test_it_refuses_to_kill_a_group_that_turns_out_to_be_ours():
    """If the child never got its own session, its group is the WAITER's. Killing it
    would take down the process holding the only copy of the outcome, turning a
    reported timeout back into the silent hang the sentinel exists to end."""
    stub = _OsStub(killpg_error=ProcessLookupError(), own_pgid=5555)
    kill_tree = _kill_tree_from_waiter(stub)
    fake = _NeverDies(9999)
    assert kill_tree(fake, 5555) is False
    assert stub.signalled == [], "it signalled a group containing the waiter itself"
    assert fake.kills == 1, "it should still stop the front-end it can reach"


def test_the_group_id_is_read_while_the_child_is_certainly_alive():
    """After the child is reaped `getpgid` raises, and a kill with nothing to aim at
    is the bug in a different costume. Order, not presence: the read has to sit
    between the spawn and the wait."""
    src = code_only(WAITER)
    spawn = src.index("subprocess.Popen(cmd, **_spawn_kw)")
    read = src.index("_pgid = os.getpgid(_proc.pid)")
    wait = src.index("rc = _proc.wait(timeout=_TIMEOUT_S)")
    assert spawn < read < wait


def test_the_child_leads_its_own_session_so_the_group_is_only_its_own():
    """Without this the group is OURS, and killing it would kill the waiter itself
    before it could publish the outcome — a worse bug than the one being fixed."""
    src = code_only(WAITER)
    assert '_spawn_kw["start_new_session"] = True' in src
    body = src[src.index("def _kill_tree("):src.index('_note("package_manager_start"')]
    # Escalate rather than going straight to KILL: a package manager holding a lock
    # deserves the chance to release it, and one ignoring TERM must not get to stay.
    assert "SIGTERM" in body and "SIGKILL" in body
    assert body.index("SIGTERM") < body.index("SIGKILL")


def test_windows_kills_the_tree_with_taskkill():
    """There are no process groups to kill there, and /T is what walks the chain.
    Asserted on the source because this leg cannot run on a POSIX box — stated
    plainly rather than left to look like coverage it is not."""
    src = code_only(WAITER)
    i = src.index("def _kill_tree(")
    body = src[i:i + 1200]
    assert '"taskkill", "/T", "/F", "/PID"' in body
    assert "proc.kill()" in body, "taskkill can be absent; still drop the front-end"


# ── The other outcomes must be unchanged by all of that ──────────────────────

def test_a_clean_upgrade_still_reports_success_and_carries_its_tail(tmp_path):
    pm = _write_pm(tmp_path, _CLEAN_PM)
    records, payload, log = _run_waiter(tmp_path, [sys.executable, str(pm)])
    assert payload["rc"] == 0 and payload["timed_out"] is False
    assert payload["orphaned"] is False
    assert "package_manager_done" in _steps(records)
    assert "installed superresearch" in payload["log_tail"], \
        "the tail is carried on SUCCESS too — the confusing case is a success that " \
        "did not move the version"
    assert "installed superresearch" in log


def test_a_failing_upgrade_reports_its_exit_code(tmp_path):
    pm = _write_pm(tmp_path, _FAILING_PM)
    _records, payload, _log = _run_waiter(tmp_path, [sys.executable, str(pm)])
    assert payload["rc"] == 1 and payload["timed_out"] is False
    assert "could not find a version" in payload["log_tail"]


def test_a_package_manager_that_cannot_even_start_is_reported(tmp_path):
    """A missing executable used to land in the same blanket handler as a timeout.
    It must still produce an outcome rather than an exception nobody sees."""
    _records, payload, _log = _run_waiter(
        tmp_path, [str(tmp_path / "does-not-exist-anywhere")])
    assert payload["rc"] == 125 and payload["timed_out"] is False


def test_the_restart_leg_runs_after_a_clean_upgrade(tmp_path):
    pm = _write_pm(tmp_path, _CLEAN_PM)
    stamp = tmp_path / "restarted"
    restart = [sys.executable, "-c",
               f"open({str(stamp)!r}, 'w').write('cycled')"]
    records, payload, _log = _run_waiter(tmp_path, [sys.executable, str(pm)],
                                         restart=restart)
    assert payload["restarting"] is True
    assert "restart_issued" in _steps(records)
    assert stamp.exists() and stamp.read_text() == "cycled"


def test_the_restart_leg_is_refused_after_a_timeout(tmp_path):
    """Never cycle the supervisor onto a half-written venv — and off-Windows the
    daemon-loop is still alive and SERVING, so a restart there would break a working
    machine to chase a broken update. The box may stay down; the reason is published."""
    gpid_file = tmp_path / "grandchild.pid"
    pm = _write_pm(tmp_path, _HANGING_PM)
    stamp = tmp_path / "restarted"
    restart = [sys.executable, "-c",
               f"open({str(stamp)!r}, 'w').write('cycled')"]
    records, payload, _log = _run_waiter(
        tmp_path, [sys.executable, str(pm), str(gpid_file)], restart=restart)
    assert payload["restarting"] is False
    assert not stamp.exists(), "the supervisor was cycled onto a half-written venv"
    skipped = next(r for r in records if r["step"] == "restart_skipped")
    assert skipped["timed_out"] is True, "a timeout must be distinguishable here"
    if gpid_file.exists():
        gpid = int(gpid_file.read_text().strip())
        if _still_running(gpid):
            os.kill(gpid, signal.SIGKILL)


def test_the_waiter_claims_the_launch_record_before_anything_else(tmp_path):
    """Only this process knows which pid is doing the work — on Linux the spawner's
    `Popen.pid` is a systemd-run front-end that is already dead."""
    pm = _write_pm(tmp_path, _CLEAN_PM)
    _records, _payload, _log = _run_waiter(tmp_path, [sys.executable, str(pm)])
    rec = json.loads((tmp_path / "intent.json").read_text(encoding="utf-8"))
    assert isinstance(rec["waiter_pid"], int) and rec["waiter_pid"] > 0


# ── the probe polls; it does not ask once (CI, 2026-08-10) ──────────────────

class _Reaped:
    """A front-end that has already exited and been reaped.

    That is the state `_kill_tree` is in by the time it probes the group: the
    direct child must be reaped first, because a zombie keeps the group alive and
    would read as a survivor. So the only question left is the descendants."""

    def __init__(self, pid):
        self.pid = pid

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


def test_a_group_that_empties_A_MOMENT_LATER_is_still_a_clean_kill():
    """THE CI FLAKE, and the production defect under it.

    SIGKILL returns as soon as the signal is queued; the kernel takes the
    descendants down and reaps them afterwards. Asking `killpg(pgid, 0)` in the
    instant after therefore sees a group that is dying but not yet empty — and on
    a loaded machine that is the ORDINARY outcome, not a rare one. The same
    commit passed on one runner and failed on a busier one, while the test's own
    eight-second wait confirmed the descendant really had died.

    Reporting "orphaned" there is not harmless conservatism: it publishes "a
    process from the upgrade survived the kill and may still hold the venv open"
    and tells the operator their venv may be inconsistent — about a kill that
    worked. A path whose whole job is telling the truth about a failed upgrade
    must not invent a second failure on top of it.
    """
    # The stub's killpg is replaced below, so the constructor argument is only
    # there to satisfy its signature — nothing ever raises it.
    stub = _OsStub(killpg_error=ProcessLookupError(), own_pgid=4242)
    calls = {"n": 0}

    def _killpg(pgid, sig):
        if sig == 0:
            calls["n"] += 1
            if calls["n"] < 3:      # still dying on the first two probes
                return None
            raise ProcessLookupError()
        return None

    stub.killpg = _killpg
    assert _kill_tree_from_waiter(stub)(_Reaped(9999), 5555) is True, (
        "a group that empties a moment after the kill is a CLEAN kill"
    )
    assert calls["n"] >= 3, "the probe must be polled, not asked once"


def test_a_group_that_never_empties_is_STILL_reported_as_orphaned():
    """The polarity, and the reason the poll is bounded.

    Waiting forever for a group that will not die turns a reported failure into
    the silent hang this whole sentinel exists to end. A tree that genuinely
    survives must still be named — that is the honest answer, and the operator
    can only act on it if someone says it."""
    stub = _OsStub(killpg_error=ProcessLookupError(), own_pgid=4242)
    stub.killpg = lambda pgid, sig: None   # never raises → the group is never empty
    started = time.time()
    assert _kill_tree_from_waiter(stub)(_Reaped(9999), 5555) is False
    assert time.time() - started < 60, "the wait must be bounded, not indefinite"


def test_the_probe_loop_is_bounded_in_the_source():
    """Pins the bound itself. The two tests above pass with any deadline at all,
    including one long enough to strand the update path for an hour."""
    src = WAITER[WAITER.index("def _kill_tree"):]
    src = src[:src.index("\n_note(")] if "\n_note(" in src else src
    assert "time.time() + 10.0" in src, src[-600:]


def test_the_probe_loop_does_not_BUSY_SPIN_while_it_waits():
    """It sleeps between probes. Without that it is a tight loop on `killpg`,
    burning a core for up to the whole deadline — on a machine already loaded
    enough that the descendants have not been reaped yet, which is the only
    situation this loop ever runs in.

    Measured, not read: the group here empties after a WALL-CLOCK delay rather
    than after a fixed number of calls, so the probe count is a direct reading of
    how often the loop asks. Paced at 0.1s that is a handful; spinning, it is
    tens of thousands — and a source assertion for a `sleep` would pass on a loop
    that slept in the wrong place."""
    stub = _OsStub(killpg_error=ProcessLookupError(), own_pgid=4242)
    calls = {"n": 0}
    empty_at = time.time() + 0.35

    def _killpg(pgid, sig):
        if sig == 0:
            calls["n"] += 1
            if time.time() < empty_at:
                return None
            raise ProcessLookupError()
        return None

    stub.killpg = _killpg
    assert _kill_tree_from_waiter(stub)(_Reaped(9999), 5555) is True
    assert 2 <= calls["n"] < 50, (
        f"probed {calls['n']} times in ~0.35s — the loop is spinning, not pacing"
    )
