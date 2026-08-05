"""An app-driven update must never end in silence, and must not start when it is
already known to be doomed.

Three defects, one symptom. The user clicks Update in Settings → About, the row
spins, and nothing else ever happens:

  1. 2026-07-21..24, five times — the worker was killed mid-launch, so pipx never
     ran, no log line was written and no status reached the device doc. The waiter
     was spawned AFTER the process kill that frees the venv, and on a KeepAlive
     host that kill brings the supervisor straight back, whose startup sweep
     reaps the worker before it gets to the spawn.
  2. 2026-07-27/28, three times — the detached upgrade inherited the supervisor's
     narrow PATH, so pipx could not resolve the uv backend recorded in the venv's
     metadata. Neither `--backend pip` nor `PIPX_DEFAULT_BACKEND` can override that
     pin; PATH is the only lever, which is why it is checked BEFORE the shutdown.
  3. Any waiter that dies before writing its result — the reporting channel exists
     but has nothing to say, which is indistinguishable from a clean run.

Everything downstream of the process exit is postmortem by construction: the venv
cannot be rebuilt while its python is running, and the detached waiter holds no
credentials. So the preflight is the only fix that prevents the outage rather than
describing it, and the launch record is what makes "the reporter died" reportable.
"""
from __future__ import annotations

import json
import os
import time

import research
from conftest import code_only_deep, serving_version as _serving


# ── Preflight: refuse while we can still answer ───────────────────────────────

class TestUpgradePreflight:

    # Joined with os.pathsep rather than a literal ":" — the double below splits it
    # the way shutil.which does, and that separator is ";" on Windows, where a
    # colon-joined literal collapses to ONE unmatchable entry.
    #
    # Be precise about what that broke, because the shape matters more than the
    # count: it did NOT redden the class. Measured, exactly ONE case failed
    # (test_allows_a_uv_venv_whose_uv_is_reachable, the only one asserting uv IS
    # found). The other _wire-based cases all expect the refusal and got it — for
    # the wrong reason. A PATH the double can never match makes "uv is missing"
    # unfalsifiable, so those tests passed while asserting nothing, which is the
    # failure this fixture's own docstring warns about two lines below. The single
    # red test was the only visible symptom of four silently vacuous ones.
    #
    # Identical string on macOS and Linux, so this changes nothing there.
    WAITER_PATH = os.pathsep.join(["/opt/homebrew/bin", "/usr/bin"])
    SHELL_PATH = "/usr/bin"

    def _wire(self, monkeypatch, *, backend, uv_on_path):
        """The `which` double HONOURS its `path` argument — it has to.

        A double that answers the same regardless is how the one thing this check
        exists to do goes untested: `which("uv")` and
        `which("uv", path=<the waiter's PATH>)` would then look identical, and
        dropping the argument (which puts us straight back at the reported bug,
        because a login shell finds uv perfectly well) would pass every test here.
        So uv is placed on the WAITER's path only, and looking it up any other way
        finds nothing."""
        monkeypatch.setattr(research, "_pipx_recorded_backend", lambda: backend)
        monkeypatch.setattr(research, "_lifecycle_env",
                            lambda **kw: {"PATH": self.WAITER_PATH})
        monkeypatch.setenv("PATH", self.SHELL_PATH)
        import shutil

        def fake_which(name, mode=os.F_OK | os.X_OK, path=None):
            where = path if path is not None else os.environ.get("PATH", "")
            if name == "uv" and uv_on_path and "/opt/homebrew/bin" in where.split(os.pathsep):
                return "/opt/homebrew/bin/uv"
            return None

        monkeypatch.setattr(shutil, "which", fake_which)

    def test_refuses_a_uv_venv_whose_uv_is_not_on_the_service_path(self, monkeypatch):
        self._wire(monkeypatch, backend="uv", uv_on_path=False)
        why = research._upgrade_preflight()
        assert why and "uv" in why
        assert "PATH" in why, f"the refusal must name what is actually wrong: {why!r}"

    def test_allows_a_uv_venv_whose_uv_is_reachable(self, monkeypatch):
        self._wire(monkeypatch, backend="uv", uv_on_path=True)
        assert research._upgrade_preflight() is None

    def test_it_looks_on_the_waiters_path_not_our_own(self, monkeypatch):
        """The distinction the whole check turns on. uv sitting on the PATH of the
        process asking is worth nothing — the login shell always found it, which is
        precisely why the failure looked impossible. Only the detached waiter's
        PATH decides."""
        self._wire(monkeypatch, backend="uv", uv_on_path=True)
        monkeypatch.setattr(research, "_lifecycle_env",
                            lambda **kw: {"PATH": self.SHELL_PATH})
        assert research._upgrade_preflight() is not None

    def test_never_blocks_on_a_pip_backend(self, monkeypatch):
        """pip lives inside the venv — there is nothing on PATH to fail to find, so
        refusing here would block an update that works."""
        self._wire(monkeypatch, backend="pip", uv_on_path=False)
        assert research._upgrade_preflight() is None

    def test_never_blocks_when_the_backend_is_unknown(self, monkeypatch):
        """A source checkout, a pip install, an older pipx, a backend we have never
        heard of. A preflight that guesses is a preflight that blocks working
        updates, so anything it cannot NAME it lets through."""
        for backend in (None, "", "poetry"):
            self._wire(monkeypatch, backend=backend, uv_on_path=False)
            assert research._upgrade_preflight() is None, backend

    def test_the_refusal_happens_before_anything_is_torn_down(self, monkeypatch):
        """The property that matters. Ordering, not presence: a preflight that ran
        after the spawn would report the same message and still take the machine
        down."""
        trace: list = []
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["pipx"])
        monkeypatch.setattr(research, "_latest_on_pypi", lambda force=True: "0.1.11")
        monkeypatch.setattr(research, "_upgrade_preflight",
                            lambda: trace.append("preflight") or "uv is not on PATH")
        monkeypatch.setattr(research, "_spawn_detached_lifecycle",
                            lambda *a, **k: trace.append("spawn") or 999)
        res = research._perform_self_update(restart_after=True)
        assert res["state"] == "failed"
        assert res["reason"] == "uv is not on PATH"
        assert trace == ["preflight"], f"it tore the backend down anyway: {trace!r}"

    def test_a_clean_preflight_still_lets_the_upgrade_run(self, monkeypatch):
        """Guard against the guard: a preflight that refused unconditionally would
        satisfy every test above and break every update."""
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["pipx"])
        monkeypatch.setattr(research, "_latest_on_pypi", lambda force=True: "0.1.11")
        monkeypatch.setattr(research, "_upgrade_preflight", lambda: None)
        monkeypatch.setattr(research, "_spawn_detached_lifecycle", lambda *a, **k: 999)
        assert research._perform_self_update(restart_after=True)["state"] == "started"


# ── The launch record: a waiter that dies is still an outcome ─────────────────

class TestUpdateIntent:

    def _intent(self, monkeypatch, tmp_path, **over):
        p = tmp_path / "update_intent.json"
        payload = {"action": "upgrade", "waiter_pid": None,
                   "at": int(time.time() * 1000) - 120_000,
                   "current": "0.1.10", "latest": "0.1.11"}
        payload.update(over)
        p.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(research, "_UPDATE_INTENT_PATH", p)
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", tmp_path / "absent.json")
        return p

    def test_a_dead_waiter_with_no_result_reports_a_failure(self, tmp_path, monkeypatch):
        self._intent(monkeypatch, tmp_path)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        st = research._consume_pending_update_result()
        assert st is not None and st["state"] == "failed"
        assert "0.1.10" in st["reason"], f"say what it is still running: {st['reason']!r}"

    def test_a_live_waiter_is_left_alone(self, tmp_path, monkeypatch):
        """Liveness, not a timer. While the process is alive the upgrade is simply
        still going, however long that takes — and on the CLI path the supervisor
        routinely relaunches a worker while pipx is still running."""
        self._intent(monkeypatch, tmp_path, waiter_pid=os.getpid())
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        assert research._consume_pending_update_result() is None

    def test_a_just_launched_update_is_left_alone(self, tmp_path, monkeypatch):
        """The pid may already be unreadable (re-parented by systemd-run, or simply
        raced), so a short floor keeps a fresh launch from being declared dead."""
        self._intent(monkeypatch, tmp_path, at=int(time.time() * 1000))
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        assert research._consume_pending_update_result() is None

    def test_a_dead_waiter_that_actually_installed_reports_success(self, tmp_path, monkeypatch):
        """The reporter dying after the install is not a failed update. Reading the
        installed version rather than trusting the record is what tells them apart —
        and reading the SERVED one alongside it is what stops the success from
        being overstated (see the restart test below)."""
        self._intent(monkeypatch, tmp_path)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.11")
        _serving(monkeypatch, "0.1.11")
        st = research._consume_pending_update_result()
        assert st["state"] == "installed" and st["needsRestart"] is False

    def test_a_waiter_killed_before_its_restart_leg_asks_for_one(self, tmp_path, monkeypatch):
        """This is the case the function exists to describe, and it used to be the
        one it got wrong.

        The waiter is only unreported because it died, so its `--then--` restart
        provably never ran: the files are on 0.1.11 and the process serving the app
        is still 0.1.10. Deciding from the INSTALLED version made that
        indistinguishable from a finished update — `_sr_version()` is already
        0.1.11 the moment pipx exits, in this very process — so the app was told
        "Updated ✓", the About row published the new number, and the box served the
        old build forever with nothing anywhere saying so."""
        self._intent(monkeypatch, tmp_path)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.11")
        _serving(monkeypatch, "0.1.10")
        st = research._consume_pending_update_result()
        assert st["state"] == "installed" and st["needsRestart"] is True
        assert "0.1.10" in st["reason"] and "restart" in st["reason"].lower()

    def test_the_record_is_not_believed_forever(self, tmp_path, monkeypatch):
        """A pid is a number, and numbers get reused — immediately, on Windows.

        A record left by a waiter that was killed (the machine slept, the box was
        rebooted because the row looked stuck) keeps naming a pid something else now
        holds. Believing it forever is not a stalled update, it is a wedged machine:
        the verdict is never published, the heartbeat pulses "installing" every 20s,
        that pulse is what tells the app to keep waiting, and every later Update tap
        is answered "one is already running"."""
        old = int(time.time() * 1000) - research._UPDATE_INTENT_MAX_AGE_MS - 60_000
        self._intent(monkeypatch, tmp_path, waiter_pid=os.getpid(), at=old)
        assert research._update_in_flight() is None
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        _serving(monkeypatch, "0.1.10")
        st = research._consume_pending_update_result()
        assert st is not None and st["state"] == "failed", (
            "the verdict stayed suppressed behind a recycled pid"
        )

    def test_a_long_but_live_upgrade_is_still_left_alone(self, tmp_path, monkeypatch):
        """Guard against the guard: the ceiling bounds pid REUSE, not how long an
        upgrade may take. A cold venv rebuild over a slow link legitimately runs for
        many minutes, and cutting it off would report a failure mid-install."""
        recent = int(time.time() * 1000) - research._UPDATE_INTENT_MAX_AGE_MS + 60_000
        self._intent(monkeypatch, tmp_path, waiter_pid=os.getpid(), at=recent)
        assert research._update_in_flight() is not None

    def test_the_real_result_wins_over_the_launch_record(self, tmp_path, monkeypatch):
        """The waiter's own exit code carries the pipx error text; the launch record
        can only say "it stopped". Never let the vaguer one win."""
        self._intent(monkeypatch, tmp_path)
        res = tmp_path / "update_result.json"
        res.write_text(json.dumps({"action": "upgrade", "rc": 3, "current": "0.1.10",
                                   "latest": "0.1.11", "log_tail": "uv not found"}),
                       encoding="utf-8")
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", res)
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        st = research._consume_pending_update_result()
        assert st["state"] == "failed" and "uv not found" in st["reason"]

    def test_discarding_clears_the_launch_record_too(self, tmp_path, monkeypatch):
        """Leaving it behind would republish the same update as a failure on every
        subsequent startup."""
        p = self._intent(monkeypatch, tmp_path)
        research._discard_pending_update_result()
        assert not p.exists()

    def test_a_pending_report_is_distinguishable_from_nothing_to_report(self, tmp_path, monkeypatch):
        """The heartbeat latches "nothing to report" permanently, so it must not
        latch while an upgrade is still in flight — that throws away the verdict."""
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", tmp_path / "absent.json")
        monkeypatch.setattr(research, "_UPDATE_INTENT_PATH", tmp_path / "absent2.json")
        assert research._update_report_pending() is False
        self._intent(monkeypatch, tmp_path, waiter_pid=os.getpid())
        assert research._update_report_pending() is True

    def test_the_heartbeat_only_latches_when_nothing_is_owed(self):
        """The latch is permanent for the life of the process, so latching on a
        bare "no verdict yet" throws the verdict away.

        It happens on the ordinary CLI path: the supervisor relaunches a worker
        while pipx is still running, the first heartbeat finds an in-flight update,
        and if that latches then the failure — when it arrives — is never published
        by this process at all.

        Source-shape, and deliberately so: the surrounding coroutine is the live
        heartbeat and cannot be driven here. What it guards is the GUARD; the
        decision itself is `_update_report_pending`, which is tested for real
        above. Read from code with docstrings and comments stripped, because the
        comment right beside this line explains the very condition it asserts."""
        src = code_only_deep(research._heartbeat_loop)
        blk = src[src.index("_consume_pending_update_result"):]
        blk = blk[:blk.index("_ur_err")]
        i_none = blk.index("if _ur is None:")
        i_latch = blk.index("_update_result_published = True", i_none)
        guard = blk[i_none:i_latch]
        assert "_update_report_pending" in guard, (
            "the heartbeat latches on 'no verdict yet' and will never report the "
            f"outcome of an update still in flight:\n{guard}"
        )
        # The SENSE of it, not just the name. Dropping the negation inverts the
        # guard into "latch only while something IS owed" — the identifier is
        # still there, so a presence check passes against the exact bug it names.
        assert "if not await asyncio.to_thread(_update_report_pending)" in guard, (
            f"the pending check is no longer what decides the latch:\n{guard}"
        )

    def test_a_corrupt_record_is_dropped_rather_than_retried(self, tmp_path, monkeypatch):
        p = tmp_path / "update_intent.json"
        p.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(research, "_UPDATE_INTENT_PATH", p)
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", tmp_path / "absent.json")
        assert research._consume_pending_update_result() is None
        assert not p.exists(), "a bad record must not be re-read forever"


class TestIntentIsWrittenAtLaunch:

    def _wire(self, monkeypatch, tmp_path):
        import types
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["pipx"])
        monkeypatch.setattr(research, "_path_python", lambda: "python3")
        monkeypatch.setattr(research, "_installed_sr_entry", lambda: "/venvs/sr/bin/superresearch")
        monkeypatch.setattr(research, "_cgroup_escape_prefix", lambda: [])
        monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [])
        monkeypatch.setattr(research, "_kill_pids", lambda pids: None)
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_UPDATE_INTENT_PATH", tmp_path / "update_intent.json")
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", tmp_path / "update_result.json")
        monkeypatch.setattr(research.subprocess, "Popen",
                            lambda cmd, **kw: types.SimpleNamespace(pid=4242))

    def test_an_upgrade_is_recorded_with_the_version_pair(self, monkeypatch, tmp_path):
        self._wire(monkeypatch, tmp_path)
        research._spawn_detached_lifecycle("upgrade", restart_after=True,
                                           current="0.1.10", latest="0.1.11")
        rec = json.loads((tmp_path / "update_intent.json").read_text())
        assert (rec["current"], rec["latest"]) == ("0.1.10", "0.1.11")
        assert rec["at"] > 0

    def test_the_spawner_does_not_record_a_pid(self, monkeypatch, tmp_path):
        """⭐ `Popen.pid` is NOT the upgrade on Linux.

        The app path submits the waiter through `systemd-run`, a front-end that
        exits in milliseconds — so `Popen.pid` names a process that is already dead
        by the time anyone looks. Recording it would make the liveness check read
        every Linux update as abandoned, and the interim backend would publish
        "the background upgrade stopped without reporting back" about thirty
        seconds in, while pipx was still installing. Only the waiter can name the
        pid that is actually doing the work."""
        self._wire(monkeypatch, tmp_path)
        research._spawn_detached_lifecycle("upgrade", restart_after=True,
                                           current="0.1.10", latest="0.1.11")
        rec = json.loads((tmp_path / "update_intent.json").read_text())
        assert rec["waiter_pid"] is None, (
            f"the spawner stamped a pid it cannot vouch for: {rec!r}"
        )

    def test_the_record_exists_before_the_waiter_is_spawned(self, monkeypatch, tmp_path):
        """Ordering: the waiter claims the record as its first act, so it has to be
        on disk already. Written after the spawn, a fast waiter finds nothing to
        claim and stays permanently unclaimed — i.e. permanently "abandoned"."""
        import types
        self._wire(monkeypatch, tmp_path)
        seen: list = []

        def _p(cmd, **kw):
            seen.append((tmp_path / "update_intent.json").exists())
            return types.SimpleNamespace(pid=4242)

        monkeypatch.setattr(research.subprocess, "Popen", _p)
        research._spawn_detached_lifecycle("upgrade", restart_after=True,
                                           current="0.1.10", latest="0.1.11")
        assert seen == [True], "the waiter was spawned before its record existed"

    def test_the_waiter_is_told_where_to_claim(self, monkeypatch, tmp_path):
        """The path reaches the waiter by env, and — on Linux — survives the
        systemd-run hand-off, which does NOT pass our environment through."""
        import types
        self._wire(monkeypatch, tmp_path)
        monkeypatch.setattr(research, "_cgroup_escape_prefix",
                            lambda: ["systemd-run", "--user", "--collect", "--quiet", "--"])
        seen = {}
        monkeypatch.setattr(research.subprocess, "Popen",
                            lambda cmd, **kw: seen.update(cmd=cmd, env=kw.get("env"))
                            or types.SimpleNamespace(pid=4242))
        research._spawn_detached_lifecycle("upgrade", restart_after=True,
                                           current="0.1.10", latest="0.1.11")
        want = str(tmp_path / "update_intent.json")
        assert seen["env"]["DG_LIFECYCLE_INTENT"] == want
        assert f"--setenv=DG_LIFECYCLE_INTENT={want}" in seen["cmd"], (
            "systemd-run hands the transient unit the user manager's environment, "
            f"not ours — the claim path never arrives: {seen['cmd']!r}"
        )

    def test_the_waiter_claims_the_record_with_its_own_pid(self, monkeypatch, tmp_path):
        """Executed for real: the waiter source is run against a live record and we
        read back what it wrote. Asserting on the source text instead would pass
        just as happily against a claim that never reaches disk."""
        import subprocess as sp
        import sys
        rec = tmp_path / "update_intent.json"
        rec.write_text(json.dumps({"action": "upgrade", "waiter_pid": None,
                                   "at": 1, "current": "0.1.10", "latest": "0.1.11"}),
                       encoding="utf-8")
        dead = sp.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        env = {**os.environ, "DG_LIFECYCLE_INTENT": str(rec)}
        sp.run([sys.executable, "-c", research._LIFECYCLE_WAITER, str(dead.pid),
                sys.executable, "-c", "pass"],
               env=env, timeout=120, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        got = json.loads(rec.read_text())
        assert isinstance(got["waiter_pid"], int) and got["waiter_pid"] > 0, (
            f"the waiter never claimed the record: {got!r}"
        )
        assert got["waiter_pid"] != dead.pid
        # …and it must not lose the rest of the record while claiming it.
        assert (got["current"], got["latest"]) == ("0.1.10", "0.1.11")

    def test_a_launch_that_never_starts_leaves_no_record(self, monkeypatch, tmp_path):
        """The record is written before the spawn, so a spawn that THROWS must take
        it back — the caller reports that failure synchronously, and a leftover
        record would republish the same attempt as a mystery on the next startup."""
        self._wire(monkeypatch, tmp_path)
        monkeypatch.setattr(research.subprocess, "Popen",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
        assert research._spawn_detached_lifecycle(
            "upgrade", restart_after=True, current="0.1.10", latest="0.1.11") is None
        assert not (tmp_path / "update_intent.json").exists()

    def test_an_uninstall_records_nothing(self, monkeypatch, tmp_path):
        """The record exists to report a failed UPGRADE to the app. An uninstall has
        no app waiting on it, and a leftover record would be read as one."""
        self._wire(monkeypatch, tmp_path)
        research._spawn_detached_lifecycle("uninstall")
        assert not (tmp_path / "update_intent.json").exists()

    def test_a_new_attempt_clears_the_previous_record(self, monkeypatch, tmp_path):
        self._wire(monkeypatch, tmp_path)
        (tmp_path / "update_result.json").write_text('{"action":"upgrade","rc":1}',
                                                     encoding="utf-8")
        research._spawn_detached_lifecycle("upgrade", restart_after=True,
                                           current="0.1.10", latest="0.1.11")
        assert not (tmp_path / "update_result.json").exists(), (
            "the previous attempt's outcome would be republished as this one's"
        )


# ── The 2026-07-21..24 family: spawn before you kill ──────────────────────────

class TestSpawnBeforeFreeingTheVenv:
    """Five `update` commands produced a full supervisor cycle in the same second
    and no pipx run at all. Freeing the venv means killing the daemon-loop, and on a
    KeepAlive/Restart=always host that brings the supervisor straight back — whose
    startup sweep kills this worker. Do it before the spawn and the spawn never
    happens: no pipx, no log line, no status, nothing on disk."""

    def _order(self, monkeypatch, tmp_path, **kw):
        import types
        order: list = []
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["pipx"])
        monkeypatch.setattr(research, "_path_python", lambda: "python3")
        monkeypatch.setattr(research, "_installed_sr_entry", lambda: "/venvs/sr/bin/superresearch")
        monkeypatch.setattr(research, "_cgroup_escape_prefix", lambda: [])
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_UPDATE_INTENT_PATH", tmp_path / "i.json")
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", tmp_path / "r.json")
        monkeypatch.setattr(research, "_enumerate_research_py_procs",
                            lambda: [(777, "python research.py --daemon-loop", "daemon-loop")])
        monkeypatch.setattr(research, "_kill_pids",
                            lambda pids: order.append("kill"))
        monkeypatch.setattr(research.subprocess, "Popen",
                            lambda cmd, **k: order.append("spawn") or types.SimpleNamespace(pid=4242))
        research._spawn_detached_lifecycle("upgrade", **kw)
        return order

    def test_the_waiter_is_spawned_before_the_venv_is_freed(self, monkeypatch, tmp_path):
        order = self._order(monkeypatch, tmp_path)   # CLI path: it does free the venv
        assert "spawn" in order and "kill" in order, order
        assert order.index("spawn") < order.index("kill"), (
            f"killed the supervisor before spawning the upgrade — the restart's sweep "
            f"can reap this worker first and nothing ever runs: {order!r}"
        )

    def test_the_launch_record_is_written_before_the_venv_is_freed(self, monkeypatch, tmp_path):
        """Same reasoning one level up: if the record is written after the kill, the
        one failure mode it exists to catch is the one that skips writing it."""
        monkeypatch.setattr(research, "_kill_pids", lambda pids: (_ for _ in ()).throw(
            SystemExit("reaped by the supervisor sweep")))
        try:
            self._order(monkeypatch, tmp_path)
        except SystemExit:
            pass
        assert (tmp_path / "i.json").exists(), (
            "a worker killed while freeing the venv leaves no trace of the attempt"
        )

    def test_the_app_path_does_not_free_the_venv_at_all(self, monkeypatch, tmp_path):
        """Off-Windows, pipx can rebuild a venv whose files are open, so the kill
        buys nothing and costs the cgroup the update is running in."""
        monkeypatch.setattr(research.sys, "platform", "darwin")
        order = self._order(monkeypatch, tmp_path, restart_after=True)
        assert order == ["spawn"], f"the app path still kills the supervisor: {order!r}"


# ── The supervisor's PATH is every child's PATH ───────────────────────────────

def _local_bin() -> str:
    """`~/.local/bin`, built the way `_lifecycle_path_dirs` builds it.

    Deliberately NOT `os.path.expanduser("~/.local/bin")`: expanduser substitutes
    the `~` and leaves the rest of the string untouched, so on Windows it returns
    a path whose separators are mixed, while the product joins the components and
    gets native ones. The two are the same string on POSIX — which is exactly why
    comparing against the expanduser form passed on macOS and could only ever fail
    here. The assertion is about which directory is on PATH, so it has to be built
    the same way the value under test is."""
    return os.path.join(os.path.expanduser("~"), ".local", "bin")


class TestSupervisorPath:

    def test_it_carries_the_tool_homes_the_upgrade_needs(self, monkeypatch):
        monkeypatch.setattr(research.sys, "platform", "darwin")
        got = research._supervisor_path_value().split(os.pathsep)
        assert "/opt/homebrew/bin" in got, (
            "the supervisor still cannot see Homebrew — the update fails before it "
            "starts, and so does anything else that shells out to a brew tool"
        )
        assert _local_bin() in got

    def test_the_tool_homes_come_first(self, monkeypatch):
        """Login-shell order, deliberately. System-first would resolve a system copy
        of a tool the user never installed in preference to the one they did, which
        is the bug — at the accepted cost that a user-writable dir can shadow an OS
        one for supervised children. Asserted so the trade stays a decision."""
        monkeypatch.setattr(research.sys, "platform", "darwin")
        got = research._supervisor_path_value().split(os.pathsep)
        assert got.index("/opt/homebrew/bin") < got.index("/usr/bin")
        assert got.index(_local_bin()) < got.index("/usr/bin")

    def test_no_duplicates(self, monkeypatch):
        monkeypatch.setattr(research.sys, "platform", "darwin")
        got = research._supervisor_path_value().split(os.pathsep)
        assert len(got) == len(set(got)), got

    def test_it_is_not_the_old_literal(self, monkeypatch):
        monkeypatch.setattr(research.sys, "platform", "darwin")
        assert research._supervisor_path_value() != "/usr/local/bin:/usr/bin:/bin"


class TestSupervisorTemplatesUsePathValue:
    """Both generators, one rule. The macOS plist is the reported case; a systemd
    --user unit that states no PATH inherits the manager's equally narrow default,
    which has neither ~/.local/bin nor ~/.cargo/bin — where uv installs itself on
    Linux."""

    # Docstrings stripped, deliberately: the docstrings here QUOTE the old narrow
    # literal in order to explain why it was wrong, which would satisfy an
    # assertion hunting for its absence.

    def test_the_plist_embeds_the_widened_path(self):
        src = code_only_deep(research._arm_supervisor_macos)
        assert "supervisor_path" in src, "the plist PATH is not derived"
        assert "/usr/local/bin:/usr/bin:/bin" not in src, (
            "the narrow literal is still in the plist template"
        )

    def test_the_systemd_unit_states_a_path(self):
        src = code_only_deep(research._arm_supervisor_linux)
        assert "_supervisor_path_value()" in src, (
            "the unit inherits systemd's default PATH, which cannot see uv"
        )
        assert 'Environment="PATH=' in src

    def test_the_linux_display_warning_still_fires(self):
        """PATH is unconditionally present now, so a `if not env_lines` check would
        silently never fire again and the reboot-safety warning would be lost."""
        src = code_only_deep(research._arm_supervisor_linux)
        assert "if not env_lines:" not in src
        assert "no DISPLAY in the calling shell" in src


# ── Saying "still working", so a slow success isn't called a failure ──────────

class TestLivenessPulse:
    """Off-Windows the update deliberately leaves the daemon-loop alive, and its
    job is to relaunch the worker. So during a perfectly healthy upgrade there IS a
    backend answering: up, on the OLD version, still advertising the same pending
    release. From the app's side that is byte-for-byte a failed update. Something
    alive has to say otherwise, and this is it."""

    def _record(self, tmp_path, monkeypatch, pid):
        p = tmp_path / "update_intent.json"
        p.write_text(json.dumps({"action": "upgrade", "waiter_pid": pid,
                                 "at": int(time.time() * 1000) - 120_000,
                                 "current": "0.1.10", "latest": "0.1.11"}),
                     encoding="utf-8")
        monkeypatch.setattr(research, "_UPDATE_INTENT_PATH", p)
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", tmp_path / "absent.json")

    def test_a_live_helper_is_reported_as_in_flight(self, tmp_path, monkeypatch):
        self._record(tmp_path, monkeypatch, os.getpid())
        live = research._update_in_flight()
        assert live and live["latest"] == "0.1.11"

    def test_a_dead_helper_is_not(self, tmp_path, monkeypatch):
        self._record(tmp_path, monkeypatch, 1)
        monkeypatch.setattr(research, "_pid_alive", lambda pid: False)
        assert research._update_in_flight() is None

    def test_an_unclaimed_record_is_not_in_flight(self, tmp_path, monkeypatch):
        """No pid means nothing ever picked the work up. Treating that as progress
        would suppress the report of the exact failure the record exists for."""
        self._record(tmp_path, monkeypatch, None)
        assert research._update_in_flight() is None

    def test_the_heartbeat_publishes_it_on_a_slow_cadence(self):
        """Source-shape (the live heartbeat coroutine can't be driven here): the
        pulse must be throttled and must be gated on a LIVE helper, not merely on
        an update having been attempted."""
        src = code_only_deep(research._heartbeat_loop)
        blk = src[src.index("_consume_pending_update_result"):]
        blk = blk[:blk.index("_ur_err")]
        assert '"state": "installing"' in blk, "nothing ever says the upgrade is alive"
        assert "_update_in_flight" in blk, (
            "the pulse is not gated on the helper actually running"
        )
        assert "_UPDATE_LIVE_REPUBLISH_MS" in blk, "the pulse is unthrottled"
        # …and it has to be WRITTEN, not merely composed. Matched on the
        # whitespace-stripped text so the assertion pins ADJACENCY rather than
        # "both of these appear somewhere nearby" — a payload assigned to a local
        # reaches nobody and, in a window-based match, looks identical to one that
        # is published (the `await` on the line above satisfies the window).
        flat = "".join(blk.split())
        assert 'awaitasyncio.to_thread(_write_update_status,device_id,{"state":"installing"' in flat, (
            "the installing payload is built but never published"
        )

    def test_the_cadence_is_slower_than_the_heartbeat(self):
        """It exists so the app can tell "working" from "came back unchanged", not
        to animate a bar — one device-doc write per heartbeat tick would be pure
        cost."""
        assert research._UPDATE_LIVE_REPUBLISH_MS >= 10_000


class TestSecondClickIsAnswered:
    """Two clicks three minutes apart is what actually happened on 2026-07-27, and
    it is the natural response to a row that looks stuck. Acting on the second one
    clears the first's launch record and races a second pipx over the same venv."""

    def _wire(self, monkeypatch, *, in_flight):
        seen: list = []
        # ⚠ LOAD-BEARING. The success path really does call `_schedule_server_exit`,
        # which arms a daemon thread that `os._exit(0)`s 1.5s later — it is the whole
        # point of the handler. Left unstubbed it kills the PYTEST process, and it
        # does so 1.5s downstream, so the run dies partway through whichever file is
        # unlucky enough to be executing by then, with exit code 0 and no summary.
        # Diagnosed the hard way; do not remove.
        monkeypatch.setattr(research, "_schedule_server_exit",
                            lambda *a, **k: seen.append("exit-scheduled"))
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.10")
        monkeypatch.setattr(research, "_write_update_status",
                            lambda dev, st: seen.append(st) or True)
        monkeypatch.setattr(research, "_update_in_flight",
                            lambda: {"current": "0.1.10", "latest": "0.1.11"} if in_flight else None)
        monkeypatch.setattr(research, "_detect_supervised", lambda: True)
        monkeypatch.setattr(research, "_perform_self_update",
                            lambda **kw: seen.append("spawned") or
                            {"state": "started", "current": "0.1.10", "latest": "0.1.11"})

        class _Doc:
            def get(self_):
                return type("S", (), {"to_dict": lambda s: {"ownerUid": "u1"}})()

            def update(self_, *a, **k):
                return None

        monkeypatch.setattr(research, "_firebase_db", type("DB", (), {
            "collection": lambda s, n: type("C", (), {
                "document": lambda s2, d: _Doc()})()})())
        return seen

    def test_a_second_click_reports_progress_instead_of_starting_another(self, monkeypatch):
        seen = self._wire(monkeypatch, in_flight=True)
        research._handle_update_command({"submittedBy": "u1"}, "dev1", None)
        assert "spawned" not in seen, "it started a second concurrent upgrade"
        assert seen and seen[-1]["state"] == "installing", (
            f"the click went unanswered: {seen!r}"
        )

    def test_a_first_click_still_starts_one(self, monkeypatch):
        """Guard against the guard: refusing unconditionally would satisfy the test
        above and break every update."""
        seen = self._wire(monkeypatch, in_flight=False)
        research._handle_update_command({"submittedBy": "u1"}, "dev1", None)
        assert "spawned" in seen, f"the update never started: {seen!r}"
        assert "exit-scheduled" in seen, (
            "the worker must exit so pipx can rebuild the venv it is running from"
        )

    def test_update_anyway_can_break_out_of_a_stuck_record(self, monkeypatch, tmp_path):
        """Everything the guard rests on can be true of a process that is not ours:
        a pid stays alive because something else was handed the number. When that
        happens this branch answers every future update with "one is already
        running" and nothing the user can reach changes it — the row spins, and the
        machine can only be freed by deleting a file by hand.

        So "Update anyway" clears the record and proceeds. It is read BEFORE the
        guard for that reason; sitting three steps later, where the mid-run check
        reads it, it could never be consulted."""
        seen = self._wire(monkeypatch, in_flight=True)
        intent = self._records(monkeypatch, tmp_path)[0]
        research._handle_update_command({"submittedBy": "u1", "force": True},
                                        "dev1", None)
        assert "spawned" in seen, f"the escape hatch does not open: {seen!r}"
        assert not intent.exists(), (
            "it spawned over a record that is still there to block the next one"
        )

    def _records(self, monkeypatch, tmp_path):
        """A launch record and an UNPUBLISHED successful outcome, both on disk."""
        intent = tmp_path / "update_intent.json"
        intent.write_text(json.dumps({"action": "upgrade", "waiter_pid": os.getpid(),
                                      "at": int(time.time() * 1000)}), encoding="utf-8")
        result = tmp_path / "update_result.json"
        result.write_text(json.dumps({"action": "upgrade", "rc": 0, "restarting": True,
                                      "current": "0.1.10", "latest": "0.1.11",
                                      "at": int(time.time() * 1000)}), encoding="utf-8")
        monkeypatch.setattr(research, "_UPDATE_INTENT_PATH", intent)
        monkeypatch.setattr(research, "_UPDATE_RESULT_PATH", result)
        return intent, result

    def test_forcing_never_throws_away_an_outcome_nobody_has_been_told(self, monkeypatch,
                                                                      tmp_path):
        """The sentinel is the SINGLE copy of an update's outcome, and there is a
        90-second window — the restart settle window — in which the app is shown
        nothing at all. That is exactly when someone taps "Update anyway". Clearing
        both files at the guard would delete a success that was still on its way to
        being reported."""
        self._wire(monkeypatch, in_flight=True)
        _intent, result = self._records(monkeypatch, tmp_path)
        research._handle_update_command({"submittedBy": "u1", "force": True},
                                        "dev1", None)
        assert result.exists(), "it deleted the only copy of an unpublished outcome"

    def test_a_force_that_gets_refused_leaves_the_record_alone(self, monkeypatch,
                                                               tmp_path):
        """Ordering, not presence. Clearing at the guard also fires on the paths
        that then DECLINE — an unsupervised host, or a run in progress — throwing
        the record away with nothing put in its place, so the update that is
        genuinely still running becomes unreportable."""
        seen = self._wire(monkeypatch, in_flight=True)
        monkeypatch.setattr(research, "_detect_supervised", lambda: False)
        intent, result = self._records(monkeypatch, tmp_path)
        research._handle_update_command({"submittedBy": "u1", "force": True},
                                        "dev1", None)
        assert "spawned" not in seen
        assert intent.exists() and result.exists(), (
            "it cleared the record on a path that refused to replace it"
        )


class TestBundledUvIsNotRefused:
    """`pipx install pipx[uv]` / `uv tool install pipx` put uv alongside pipx, and
    pipx asks that package for the binary before it ever looks at PATH. Refusing
    there would block an upgrade that works, and tell the user to install a uv they
    already have."""

    def test_the_preflight_defers_to_a_bundled_uv(self, monkeypatch):
        import shutil
        monkeypatch.setattr(research, "_pipx_recorded_backend", lambda: "uv")
        monkeypatch.setattr(research, "_lifecycle_env", lambda **kw: {"PATH": "/nowhere"})
        monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
        monkeypatch.setattr(research, "_pipx_bundles_uv", lambda: True)
        assert research._upgrade_preflight() is None

    def test_it_still_refuses_when_uv_is_nowhere(self, monkeypatch):
        import shutil
        monkeypatch.setattr(research, "_pipx_recorded_backend", lambda: "uv")
        monkeypatch.setattr(research, "_lifecycle_env", lambda **kw: {"PATH": "/nowhere"})
        monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
        monkeypatch.setattr(research, "_pipx_bundles_uv", lambda: False)
        assert research._upgrade_preflight() is not None

    def test_the_probe_asks_pipxs_own_interpreter(self, monkeypatch, tmp_path):
        """Not ours. pipx routinely lives in a different interpreter (a pip --user
        install, a brew python), and `import uv` in this process says nothing about
        whether pipx can find it."""
        shim = tmp_path / "pipx"
        shim.write_text("#!/somewhere/python3.13\n", encoding="utf-8")
        monkeypatch.setattr(research, "_pipx_cmd", lambda: [str(shim)])
        seen: list = []
        monkeypatch.setattr(research.subprocess, "run",
                            lambda argv, **kw: seen.append(list(argv)) or
                            type("R", (), {"returncode": 0})())
        assert research._pipx_bundles_uv() is True
        assert seen == [["/somewhere/python3.13", "-c", "import uv"]], seen

    def test_the_probe_resolves_an_env_shebang(self, monkeypatch, tmp_path):
        import shutil
        shim = tmp_path / "pipx"
        shim.write_text("#!/usr/bin/env python3.13\n", encoding="utf-8")
        monkeypatch.setattr(research, "_pipx_cmd", lambda: [str(shim)])
        monkeypatch.setattr(shutil, "which", lambda n: f"/opt/{n}")
        seen: list = []
        monkeypatch.setattr(research.subprocess, "run",
                            lambda argv, **kw: seen.append(list(argv)) or
                            type("R", (), {"returncode": 1})())
        assert research._pipx_bundles_uv() is False
        assert seen == [["/opt/python3.13", "-c", "import uv"]], seen

    def test_an_unreadable_shim_does_not_vouch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(research, "_pipx_cmd", lambda: [str(tmp_path / "nope")])
        assert research._pipx_bundles_uv() is False
