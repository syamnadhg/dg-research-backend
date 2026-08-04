"""A failed self-update must reach the app instead of spinning forever.

The gap this locks (Research Computer, 2026-07-27): `_perform_self_update` returns
"started" *before* pipx runs — its state enum has no value for "the upgrade ran and
failed", because by then the worker that would report has already exited so the venv
can be rebuilt. The detached waiter learns pipx's exit code but holds no credentials
(it runs on a non-venv python precisely so it can outlive the rebuild), so a nonzero
exit was silent: the About row span until the app's own 5-minute timeout.

The handoff is therefore a disk sentinel — waiter writes, next backend publishes.

`_LIFECYCLE_WAITER` is a `-c` STRING payload executed by a foreign interpreter, so
nothing in the normal import path ever exercises it. These tests run it for real.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from conftest import serving_version

research = importlib.import_module("research")


def _run_waiter(tmp_path: Path, *, pipx_body: str, restart: bool = False) -> dict:
    """Execute the real waiter payload against a fake pipx. Returns the sentinel."""
    fake_pipx = tmp_path / "fake-pipx"
    fake_pipx.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(pipx_body))
    fake_pipx.chmod(0o755)

    result = tmp_path / "update_result.json"
    restart_marker = tmp_path / "restart-ran"
    # The restart leg records whether the sentinel was ALREADY on disk when it
    # ran. Without that there is nothing to assert ordering on: both artifacts
    # exist at the end whichever order produced them.
    fake_sr = tmp_path / "fake-superresearch"
    fake_sr.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        f"open({str(restart_marker)!r}, 'w').write("
        f"'yes' if os.path.exists({str(result)!r}) else 'no')\n"
    )
    fake_sr.chmod(0o755)

    log = tmp_path / "upgrade.log"

    # A child we reap first, so its pid is gone by the time the waiter probes it.
    doomed = subprocess.Popen([sys.executable, "-c", "pass"])
    doomed.wait()

    argv = [str(doomed.pid), sys.executable, str(fake_pipx), "upgrade", "superresearch"]
    if restart:
        argv += ["--then--", sys.executable, str(fake_sr)]

    env = dict(os.environ)
    env.update({
        "DG_LIFECYCLE_RESULT": str(result),
        "DG_LIFECYCLE_LOG": str(log),
        "DG_LIFECYCLE_ACTION": "upgrade",
        "DG_LIFECYCLE_FROM": "0.1.9",
        "DG_LIFECYCLE_TO": "0.1.10",
    })
    with open(log, "wb") as fh:
        subprocess.run([sys.executable, "-c", research._LIFECYCLE_WAITER, *argv],
                       stdout=fh, stderr=subprocess.STDOUT, env=env, timeout=120,
                       check=False)
    out = {"result": None, "restarted": restart_marker.exists(),
           "saw_result": restart_marker.read_text() if restart_marker.exists() else None,
           "log": log.read_text(errors="replace")}
    if result.exists():
        out["result"] = json.loads(result.read_text())
    return out


class TestWaiterWritesItsOutcome:
    def test_failed_upgrade_is_recorded_with_the_real_error(self, tmp_path):
        """The exact shape of the observed failure: pipx exits nonzero having printed
        the uv-backend error. Pre-fix this produced no artifact at all."""
        got = _run_waiter(tmp_path, pipx_body="""
            import sys
            print("upgrading superresearch...")
            print("The uv backend was requested but the 'uv' executable could not be found.")
            sys.exit(3)
        """)
        res = got["result"]
        assert res is not None, "no sentinel written — a failed upgrade stays invisible"
        assert res["rc"] == 3
        assert res["current"] == "0.1.9" and res["latest"] == "0.1.10"
        assert "uv backend was requested" in res["log_tail"], res["log_tail"]
        assert res["restarting"] is False

    def test_successful_upgrade_is_recorded_and_restarts(self, tmp_path):
        got = _run_waiter(tmp_path, pipx_body="""
            print("upgraded package superresearch from 0.1.9 to 0.1.10")
        """, restart=True)
        res = got["result"]
        assert res is not None and res["rc"] == 0
        assert res["restarting"] is True
        assert got["restarted"], "the --then-- restart leg did not run"

    def test_failed_upgrade_does_not_restart(self, tmp_path):
        # Never cycle the supervisor onto a half-built venv.
        got = _run_waiter(tmp_path, pipx_body="import sys; sys.exit(1)", restart=True)
        assert got["result"]["rc"] == 1
        assert not got["restarted"], "restarted despite a failed upgrade"

    def test_sentinel_is_written_before_the_restart(self, tmp_path):
        """Ordering matters: `--then--` cycles the supervisor, so a sentinel written
        AFTER the restart would race the new backend's read of that same file.

        The restart script REPORTS whether the sentinel existed when it ran. It
        used to assert only that both artifacts exist at the end, which is true in
        either order — verified by reordering the waiter so the restart leg runs
        first: the old assertion still passed."""
        got = _run_waiter(tmp_path, pipx_body="print('ok')", restart=True)
        assert got["restarted"], "the --then-- restart leg did not run"
        assert got["saw_result"] == "yes", (
            "the restart ran BEFORE the sentinel was written — the new backend can "
            "race the write it is supposed to read"
        )

    def test_no_result_env_means_no_sentinel(self, tmp_path):
        """The uninstall path passes no DG_LIFECYCLE_RESULT — it must not leave an
        update outcome behind for the next backend to publish."""
        fake_pipx = tmp_path / "p"
        fake_pipx.write_text("#!/usr/bin/env python3\nprint('gone')\n")
        fake_pipx.chmod(0o755)
        doomed = subprocess.Popen([sys.executable, "-c", "pass"])
        doomed.wait()
        env = dict(os.environ)
        env.pop("DG_LIFECYCLE_RESULT", None)
        subprocess.run([sys.executable, "-c", research._LIFECYCLE_WAITER,
                        str(doomed.pid), sys.executable, str(fake_pipx),
                        "uninstall", "superresearch"],
                       env=env, timeout=120, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        assert not (tmp_path / "update_result.json").exists()


class TestConsumePendingUpdateResult:
    def _write(self, tmp_path, monkeypatch, payload):
        p = tmp_path / "update_result.json"
        p.write_text(json.dumps(payload))
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", p)
        return p

    def test_none_when_no_update_ran(self, tmp_path, monkeypatch):
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", tmp_path / "nope.json")
        assert research._consume_pending_update_result() is None

    def test_failure_surfaces_the_pipx_error_text(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 3, "current": "0.1.9", "latest": "0.1.10",
            "log_tail": "The uv backend was requested but the 'uv' executable "
                        "could not be found."})
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.9")
        st = research._consume_pending_update_result()
        assert st["state"] == "failed"
        # The app must be able to show WHY, not just "failed".
        assert "uv" in st["reason"] and "exit 3" in st["reason"]

    def test_success_reports_installed(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.9", "latest": "0.1.10"})
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        serving_version(monkeypatch, "0.1.10")
        st = research._consume_pending_update_result()
        assert st == {"state": "installed", "current": "0.1.10",
                      "latest": "0.1.10", "needsRestart": False, "reason": ""}

    def test_clean_exit_but_old_build_still_running_needs_a_restart(self, tmp_path, monkeypatch):
        """pipx said OK but the restart leg never landed, so the new files are on disk
        while the process serving the app is still the old build. Reported as
        installed-but-needs-restart rather than a flat failure: the upgrade DID land,
        and the remedy is the `restart` command the app's fallback button issues.

        The two versions have to come from two different places, and this test used
        to take both from one. `_sr_version()` reads wheel metadata off DISK, so it
        is ALREADY 0.1.10 the instant pipx finishes — inside this very process. A
        fixture that stubs it to 0.1.9 to mean "still running the old build" is
        describing a state that cannot occur, so the branch it exercised was
        unreachable in production and the Restart button it renders was dead code.
        What is installed comes from the disk; what is SERVING comes from the
        marker `--serve` stamps."""
        self._write(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.9", "latest": "0.1.10"})
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        serving_version(monkeypatch, "0.1.9")
        st = research._consume_pending_update_result()
        assert st["state"] == "installed" and st["needsRestart"] is True
        assert "restart" in st["reason"].lower()
        assert "0.1.9" in st["reason"], "say which build is still serving"

    def test_a_restart_already_under_way_is_not_reported_as_owing_one(self, tmp_path,
                                                                     monkeypatch):
        """The sentinel is written BEFORE the waiter cycles the supervisor, so a
        heartbeat landing in that window sees the old build still serving. Without
        a settle window every successful update would flash a Restart button for
        the seconds the cycle takes — and the row's own copy would contradict the
        version bump arriving right behind it."""
        self._write(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.9", "latest": "0.1.10",
            "restarting": True, "at": int(time.time() * 1000)})
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        serving_version(monkeypatch, "0.1.9")
        assert research._consume_pending_update_result() is None

    def test_a_clock_stepped_backwards_does_not_suppress_the_outcome(self, tmp_path,
                                                                     monkeypatch):
        """The settle window is bounded at BOTH ends. A bare `< SETTLE` is
        satisfied by any negative age, so an NTP correction or a VM snapshot
        restore landing between the waiter's write and this read would return None
        on every tick forever — and nothing else re-reads this to a conclusion, so
        the outcome is simply never published."""
        self._write(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.9", "latest": "0.1.10",
            "restarting": True, "at": int(time.time() * 1000) + 3600_000})
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        serving_version(monkeypatch, "0.1.9")
        assert research._consume_pending_update_result() is not None, (
            "a clock that jumped backwards silenced the report permanently"
        )

    def test_a_stamp_that_is_not_a_number_cannot_wedge_the_report(self, tmp_path,
                                                                  monkeypatch):
        """`int(raw["at"])` on a record that PARSED but carries junk raises, the
        heartbeat swallows it, and because the file is still there the pending
        check stays true — so the verdict is never published, never latched, and
        the record is never deleted, on every tick and every boot."""
        for junk in ("soon", None, [1], {"a": 1}):
            self._write(tmp_path, monkeypatch, {
                "action": "upgrade", "rc": 0, "current": "0.1.9", "latest": "0.1.10",
                "restarting": True, "at": junk})
            monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
            serving_version(monkeypatch, "0.1.9")
            assert research._consume_pending_update_result() is not None, junk

    def test_a_restart_that_never_finished_is_reported_once_the_window_passes(
            self, tmp_path, monkeypatch):
        """Guard against the guard: waiting forever would restore the silence."""
        stale = int(time.time() * 1000) - research._RESTART_SETTLE_MS - 1000
        self._write(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.9", "latest": "0.1.10",
            "restarting": True, "at": stale})
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        serving_version(monkeypatch, "0.1.9")
        assert research._consume_pending_update_result()["needsRestart"] is True

    def test_a_normal_success_does_not_ask_for_a_restart(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.9", "latest": "0.1.10"})
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        serving_version(monkeypatch, "0.1.10")
        assert research._consume_pending_update_result()["needsRestart"] is False

    def test_nothing_serving_is_not_evidence_of_a_missing_restart(self, tmp_path,
                                                                  monkeypatch):
        """No marker means nothing is serving yet — a machine mid-cycle, or one
        whose worker has not come back. That is an absence of evidence, and turning
        it into a Restart prompt would put one on screen during every ordinary
        supervisor relaunch."""
        self._write(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.9", "latest": "0.1.10"})
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        serving_version(monkeypatch, None)
        assert research._consume_pending_update_result()["needsRestart"] is False

    def test_reading_does_NOT_delete_so_a_failed_publish_can_retry(self, tmp_path, monkeypatch):
        """The sentinel is the ONLY copy of the outcome. Deleting it on read meant a
        single Firestore hiccup lost the answer forever — the exact thing this feature
        exists to deliver. Read leaves it; the caller discards only once the app has
        actually been told."""
        p = self._write(tmp_path, monkeypatch, {
            "action": "upgrade", "rc": 0, "current": "0.1.9", "latest": "0.1.10"})
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        assert research._consume_pending_update_result() is not None
        assert p.exists(), "read must not consume — a failed publish could not retry"
        # …and it still reads the same on a retry.
        assert research._consume_pending_update_result() is not None
        research._discard_pending_update_result()
        assert not p.exists()
        assert research._consume_pending_update_result() is None

    def test_the_publisher_discards_only_after_a_successful_write(self):
        """Ordering guard on the heartbeat: publish, THEN discard, THEN latch. Any other
        order can drop an outcome on a transient write failure.

        Anchored on the OUTCOME publish, not on the first `_write_update_status`
        in the block. The liveness pulse added later calls the same function
        earlier in the same slice, so a bare `.index(...)` started matching the
        pulse — after which moving the discard ahead of the real publish still
        satisfied the comparison. Verified by injecting exactly that reordering."""
        src = inspect.getsource(research._heartbeat_loop)
        blk = src[src.index("_update_result_published"):]
        publish = "elif await asyncio.to_thread(_write_update_status, device_id, _ur):"
        i_write = blk.find(publish)
        assert i_write > -1, (
            "the outcome publish was reworded — this guard is now anchored on "
            "nothing and would pass on any ordering"
        )
        i_discard = blk.index("_discard_pending_update_result", i_write)
        i_latch = blk.index("_update_result_published = True", i_write)
        assert i_write < i_discard < i_latch, (
            "must be write -> discard -> latch; anything else can lose the outcome"
        )
        # And _write_update_status has to actually report success for that to mean
        # anything — it swallows its own exceptions.
        assert "-> bool" in inspect.getsource(research._write_update_status)

    def test_malformed_sentinel_is_discarded_not_raised(self, tmp_path, monkeypatch):
        p = tmp_path / "update_result.json"
        p.write_text("{not json")
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", p)
        assert research._consume_pending_update_result() is None
        assert not p.exists(), "a poison sentinel must not persist across restarts"

    def test_uninstall_sentinel_is_ignored(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, {"action": "uninstall", "rc": 0})
        assert research._consume_pending_update_result() is None


class TestStaleSentinelIsClearedBeforeSpawn:
    def test_previous_outcome_cannot_be_reported_as_this_attempt(self, monkeypatch, tmp_path):
        stale = tmp_path / "update_result.json"
        stale.write_text(json.dumps({"action": "upgrade", "rc": 0}))
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", stale)
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["/usr/bin/pipx"])
        monkeypatch.setattr(research, "_path_python", lambda: "/usr/bin/python3")
        monkeypatch.setattr(research, "_cgroup_escape_prefix", lambda: [])
        monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [])

        class _P:
            pid = 11
            def __init__(self, *a, **kw):
                pass
        monkeypatch.setattr(research.subprocess, "Popen", _P)
        research._spawn_detached_lifecycle("upgrade", current="0.1.9", latest="0.1.10")
        assert not stale.exists(), "a stale sentinel would be republished as this run"


class TestRestartCommand:
    """The About row's fallback Restart button needs a real command behind it, or it
    is decorative. Deliberately NOT hard_reset: that sweeps Firestore, cancels the
    active run and drains the queue. This is the narrow "finish the update" action."""

    def _dispatch(self, monkeypatch, *, busy=False, worker_id=1):
        src = inspect.getsource(research._start_device_command_listener)
        assert 'if action == "restart":' in src, "no restart branch in the dispatcher"
        return src, busy, worker_id

    def test_restart_is_worker_1_only(self):
        """Gated with update/check-update for the same delete-race reason: a sibling
        worker deleting the doc first can drop the command with no replay."""
        src = inspect.getsource(research._start_device_command_listener)
        assert 'elif action in ("update", "check-update", "restart") and WORKER_ID != 1:' in src

    def test_restart_exits_the_worker_rather_than_hard_resetting(self):
        src = inspect.getsource(research._start_device_command_listener)
        blk = src[src.index('if action == "restart":'):]
        blk = blk[:blk.index("continue", blk.index("_schedule_server_exit"))]
        assert '_schedule_server_exit("device-restart"' in blk
        # None of hard_reset's collateral may appear on this path.
        for forbidden in ("_hard_reset_in_progress", "_wait_for_uploads_to_settle",
                          "hard_reset_sweep", "persist_fn"):
            assert forbidden not in blk, f"restart must not do hard_reset's {forbidden}"

    def test_restart_refuses_mid_run_instead_of_destroying_it(self):
        src = inspect.getsource(research._start_device_command_listener)
        blk = src[src.index('if action == "restart":'):]
        blk = blk[:blk.index("_schedule_server_exit")]
        assert '_QUEUE_STATE.get("running")' in blk and "qsize()" in blk, (
            "a restart must check for an in-flight run"
        )
        assert '"state": "deferred"' in blk, (
            "a refused restart must tell the app why, not fail silently"
        )
