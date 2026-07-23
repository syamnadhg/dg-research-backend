"""App-driven remote backend update — the `update` device command + the headless
`_perform_self_update` core it shares with the `superresearch --update` CLI.

Locks the guards the adversarial review + the design called out:
  - owner-only (defense-in-depth beyond the Firestore rule),
  - supervised-only (a foreground --serve has nothing to relaunch it),
  - mid-run DEFER unless force; force stops the active run first,
  - outcome written to updateStatus; started → schedules the process exit so the
    detached pipx-upgrade waiter can rebuild the venv.
"""

from __future__ import annotations

import importlib

research = importlib.import_module("research")


# ── _perform_self_update: the headless decision core ──────────────────────────

class TestPerformSelfUpdate:
    def _wire(self, monkeypatch, *, source=False, pipx=True, cur="0.1.5",
              latest="0.1.6", spawn=True):
        monkeypatch.setattr(research, "_is_source_checkout", lambda: source)
        monkeypatch.setattr(research, "_pipx_cmd", lambda: (["pipx"] if pipx else None))
        monkeypatch.setattr(research, "_sr_version", lambda: cur)
        monkeypatch.setattr(research, "_latest_on_pypi", lambda *, force=False: latest)
        monkeypatch.setattr(research, "_spawn_detached_lifecycle", lambda a, **kw: spawn)

    def test_started_when_outdated(self, monkeypatch):
        self._wire(monkeypatch, cur="0.1.5", latest="0.1.6")
        res = research._perform_self_update()
        assert res["state"] == "started" and res["latest"] == "0.1.6"

    def test_already_when_current(self, monkeypatch):
        self._wire(monkeypatch, cur="0.1.6", latest="0.1.6")
        assert research._perform_self_update()["state"] == "already"

    def test_offline_proceeds_started(self, monkeypatch):
        # latest None (PyPI unreachable) → proceed rather than strand the update.
        self._wire(monkeypatch, latest=None)
        assert research._perform_self_update()["state"] == "started"

    def test_source_checkout_unsupported(self, monkeypatch):
        self._wire(monkeypatch, source=True)
        assert research._perform_self_update()["state"] == "unsupported"

    def test_pipx_missing_failed(self, monkeypatch):
        self._wire(monkeypatch, pipx=False)
        assert research._perform_self_update()["state"] == "failed"

    def test_spawn_failure_failed(self, monkeypatch):
        self._wire(monkeypatch, spawn=False)
        assert research._perform_self_update()["state"] == "failed"

    def test_never_prints_or_exits(self, monkeypatch, capsys):
        # The headless core must not print (the CLI printer owns that).
        self._wire(monkeypatch)
        research._perform_self_update()
        assert capsys.readouterr().out == ""

    def test_forwards_restart_after_and_surfaces_waiter_pid(self, monkeypatch):
        # The middle link of the fix chain: restart_after must reach the spawner,
        # and the spawner's pid must surface as res["waiter_pid"] (so the caller can
        # protect the waiter from the exit reap). A mutation dropping either would
        # silently revert the macOS/Windows fix.
        seen = {}
        monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["pipx"])
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.5")
        monkeypatch.setattr(research, "_latest_on_pypi", lambda *, force=False: "0.1.6")

        def _spawn(action, *, restart_after=False):
            seen["restart_after"] = restart_after
            return 7777
        monkeypatch.setattr(research, "_spawn_detached_lifecycle", _spawn)
        res = research._perform_self_update(restart_after=True)
        assert seen["restart_after"] is True, "restart_after must propagate to the spawner"
        assert res["state"] == "started" and res["waiter_pid"] == 7777
        # And the CLI default must NOT request a restart.
        research._perform_self_update()
        assert seen["restart_after"] is False


# ── _pipx_cmd: locate pipx even when its shim isn't on PATH ────────────────────

class TestPipxCmdDiscovery:
    """The install one-liner pip --user-installs pipx, whose shim sits OFF the
    default PATH until a new shell runs `pipx ensurepath` — on macOS in
    ~/Library/Python/X.Y/bin, on Linux in ~/.local/bin. `--update` must still find
    it (the reported "pipx not found" on a machine that DID install correctly)."""

    def _no_path_pipx(self, monkeypatch, home):
        import shutil
        # No `pipx` shim and no module-python on PATH → forces the shim-dir probe.
        monkeypatch.setattr(shutil, "which", lambda _n: None)
        monkeypatch.setattr(research.os.path, "expanduser", lambda p: str(home))

    def test_prefers_shim_on_path(self, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/pipx" if n == "pipx" else None)
        assert research._pipx_cmd() == ["pipx"]

    def test_finds_macos_user_shim_off_path(self, monkeypatch, tmp_path):
        self._no_path_pipx(monkeypatch, tmp_path)
        shim = tmp_path / "Library" / "Python" / "3.13" / "bin" / "pipx"
        shim.parent.mkdir(parents=True)
        shim.write_text("#!/bin/sh\n")
        shim.chmod(0o755)
        assert research._pipx_cmd() == [str(shim)]

    def test_finds_local_bin_shim_off_path(self, monkeypatch, tmp_path):
        self._no_path_pipx(monkeypatch, tmp_path)
        shim = tmp_path / ".local" / "bin" / "pipx"
        shim.parent.mkdir(parents=True)
        shim.write_text("#!/bin/sh\n")
        shim.chmod(0o755)
        assert research._pipx_cmd() == [str(shim)]

    def test_prefers_newest_macos_python(self, monkeypatch, tmp_path):
        self._no_path_pipx(monkeypatch, tmp_path)
        for minor in ("3.12", "3.13"):
            s = tmp_path / "Library" / "Python" / minor / "bin" / "pipx"
            s.parent.mkdir(parents=True)
            s.write_text("#!/bin/sh\n")
            s.chmod(0o755)
        got = research._pipx_cmd()
        assert got == [str(tmp_path / "Library" / "Python" / "3.13" / "bin" / "pipx")]

    def test_none_when_truly_absent(self, monkeypatch, tmp_path):
        self._no_path_pipx(monkeypatch, tmp_path)
        assert research._pipx_cmd() is None


# ── _handle_update_command: the remote command handler ────────────────────────

class _FakeDocRef:
    def __init__(self, store, path):
        self._store, self._path = store, path

    def get(self):
        data = self._store.get(self._path)

        class _Snap:
            def __init__(s, d):
                s._d = d

            def to_dict(s):
                return s._d
        return _Snap(data)

    def update(self, patch):
        self._store.setdefault(self._path, {}).update(patch)


class _FakeColl:
    def __init__(self, store, prefix):
        self._store, self._prefix = store, prefix

    def document(self, doc_id):
        return _FakeDocRef(self._store, f"{self._prefix}/{doc_id}")


class _FakeDB:
    def __init__(self, store):
        self._store = store

    def collection(self, name):
        return _FakeColl(self._store, name)


class _FakeLoop:
    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, fn, *a):
        self.calls.append(fn)
        # do NOT actually invoke request_stop in the test


DEV = "dev-1"
OWNER = "owner-uid"


def _handle(monkeypatch, *, dev_doc, cmd, supervised=True, running=False,
            qsize=0, perform_state="started"):
    """Drive _handle_update_command with fakes; returns (store, exits, loop)."""
    store = {f"devices/{DEV}": dict(dev_doc)}
    monkeypatch.setattr(research, "_firebase_db", _FakeDB(store))
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.5")
    # Supervised gate now checks the OS auto-start artifact (source of truth).
    monkeypatch.setattr(research, "_detect_supervised", lambda: supervised)

    class _FakeQ:
        def qsize(self):
            return qsize
    monkeypatch.setattr(research, "_QUEUE_STATE",
                        {"running": running, "queue_ref": _FakeQ()})
    perform_calls = []

    def _fake_perform(*, force_check=True, restart_after=False):
        perform_calls.append((force_check, restart_after))
        return {"state": perform_state, "current": "0.1.5",
                "latest": "0.1.6", "reason": ""}
    monkeypatch.setattr(research, "_perform_self_update", _fake_perform)
    exits = []
    monkeypatch.setattr(research, "_schedule_server_exit",
                        lambda src, delay_sec=0, protect_pids=None: exits.append((src, delay_sec)))

    class _Ctl:
        def request_stop(self):
            pass
    monkeypatch.setattr(research, "_controls", _Ctl())
    loop = _FakeLoop()
    research._handle_update_command(cmd, DEV, loop)
    return store, exits, perform_calls, loop


def _status(store):
    return (store[f"devices/{DEV}"].get("updateStatus") or {})


def test_owner_mismatch_refused(monkeypatch):
    store, exits, perform, _ = _handle(
        monkeypatch,
        dev_doc={"ownerUid": OWNER},
        cmd={"action": "update", "submittedBy": "someone-else"},
    )
    assert _status(store)["state"] == "failed"
    assert "owner" in _status(store)["reason"].lower()
    assert perform == [] and exits == []


def test_not_supervised_refused(monkeypatch):
    store, exits, perform, _ = _handle(
        monkeypatch,
        dev_doc={"ownerUid": OWNER},
        cmd={"action": "update", "submittedBy": OWNER},
        supervised=False,
    )
    assert _status(store)["state"] == "failed"
    assert "supervised" in _status(store)["reason"].lower()
    assert perform == [] and exits == []


def test_mid_run_defers_without_force(monkeypatch):
    store, exits, perform, _ = _handle(
        monkeypatch,
        dev_doc={"ownerUid": OWNER, "busyWorkerIds": [1]},
        cmd={"action": "update", "submittedBy": OWNER},
        running=True,
    )
    assert _status(store)["state"] == "deferred"
    assert perform == [] and exits == []


def test_force_during_run_stops_then_updates(monkeypatch):
    store, exits, perform, loop = _handle(
        monkeypatch,
        dev_doc={"ownerUid": OWNER, "busyWorkerIds": [1]},
        cmd={"action": "update", "submittedBy": OWNER, "force": True},
        running=True,
        perform_state="started",
    )
    assert loop.calls, "force during a run must signal the active run to stop"
    # force_check + restart_after (the app can't run --restart itself).
    assert perform == [(True, True)], "forced update must run the upgrade"
    assert _status(store)["state"] == "started"
    assert exits and exits[0][0] == "device-update"


def test_force_no_op_upgrade_does_not_stop_the_run(monkeypatch):
    # Regression (review MAJOR): if a forced update turns out to be a no-op
    # (already current / launch failed), the in-flight run must NOT be stopped —
    # request_stop only fires once an upgrade is actually started.
    store, exits, perform, loop = _handle(
        monkeypatch,
        dev_doc={"ownerUid": OWNER, "busyWorkerIds": [1]},
        cmd={"action": "update", "submittedBy": OWNER, "force": True},
        running=True,
        perform_state="already",
    )
    assert perform == [(True, True)]  # force_check + restart_after (app can't run --restart itself)
    assert loop.calls == [], "must NOT stop the active run when nothing was upgraded"
    assert exits == []
    assert _status(store)["state"] == "already"


def test_idle_owner_supervised_updates_and_exits(monkeypatch):
    store, exits, perform, _ = _handle(
        monkeypatch,
        dev_doc={"ownerUid": OWNER},
        cmd={"action": "update", "submittedBy": OWNER},
        perform_state="started",
    )
    assert perform == [(True, True)]  # force_check + restart_after (app can't run --restart itself)
    assert _status(store)["state"] == "started"
    assert exits and exits[0][0] == "device-update"


def test_check_update_publishes_version_and_checkedat(monkeypatch):
    # The About-page "Check" command forces a fresh check and republishes the
    # version signal + a versionCheckedAt stamp (so the FE spinner clears). No exit.
    store = {f"devices/{DEV}": {"ownerUid": OWNER}}
    monkeypatch.setattr(research, "_firebase_db", _FakeDB(store))
    seen = {}

    def _fields(*, force=False):
        seen["force"] = force
        return {"version": "0.1.5", "updateAvailable": "0.1.6"}

    monkeypatch.setattr(research, "_device_version_fields", _fields)
    research._handle_check_update_command(DEV)
    doc = store[f"devices/{DEV}"]
    assert seen["force"] is True, "check must force a fresh PyPI read"
    assert doc["version"] == "0.1.5" and doc["updateAvailable"] == "0.1.6"
    assert isinstance(doc.get("versionCheckedAt"), int)


def test_already_up_to_date_no_exit(monkeypatch):
    store, exits, perform, _ = _handle(
        monkeypatch,
        dev_doc={"ownerUid": OWNER},
        cmd={"action": "update", "submittedBy": OWNER},
        perform_state="already",
    )
    assert perform == [(True, True)]  # force_check + restart_after (app can't run --restart itself)
    assert _status(store)["state"] == "already"
    assert exits == [], "no process exit when nothing was upgraded"


# ── the supervised-self-update fix: escape the cgroup + restart after upgrade ──

class TestRestartAfterUpgrade:
    """The app-driven update must cycle the supervisor onto the rebuilt venv, run
    from OUTSIDE the supervisor's cgroup — else systemd reaps the waiter and the
    version never bumps (the 'taking longer than expected' bug)."""

    WAITER_PID = 4242

    def _wire_spawn(self, monkeypatch, *, entry="/venvs/superresearch/bin/superresearch",
                    escape=("systemd-run", "--user", "--collect", "--quiet", "--")):
        monkeypatch.setattr(research, "_pipx_cmd", lambda: ["pipx"])
        monkeypatch.setattr(research, "_path_python", lambda: "python3")
        monkeypatch.setattr(research, "_installed_sr_entry", lambda: entry)
        monkeypatch.setattr(research, "_cgroup_escape_prefix", lambda: list(escape))
        monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [])
        monkeypatch.setattr(research, "_kill_pids", lambda pids: None)

    def _popen(self, monkeypatch, seen=None, order=None):
        import types

        def _p(cmd, **kw):
            if seen is not None:
                seen["cmd"] = cmd
            if order is not None:
                order.append("spawn")
            return types.SimpleNamespace(pid=self.WAITER_PID)
        monkeypatch.setattr(research.subprocess, "Popen", _p)

    def test_upgrade_with_restart_builds_escaped_then_restart(self, monkeypatch, tmp_path):
        self._wire_spawn(monkeypatch)
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        seen = {}
        self._popen(monkeypatch, seen=seen)
        assert research._spawn_detached_lifecycle("upgrade", restart_after=True) == self.WAITER_PID
        cmd = seen["cmd"]
        # cgroup-escaped
        assert cmd[:5] == ["systemd-run", "--user", "--collect", "--quiet", "--"]
        # runs the waiter, which upgrades then restarts the installed build
        assert "--then--" in cmd
        tail = cmd[cmd.index("--then--") + 1:]
        assert tail == ["/venvs/superresearch/bin/superresearch", "--restart"]

    def test_returns_the_waiter_pid_for_reap_protection(self, monkeypatch, tmp_path):
        # The PID must flow back so the caller can shield the waiter from the
        # pre-exit child-reap (the fix for the macOS/Windows never-bumps gap).
        self._wire_spawn(monkeypatch)
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        self._popen(monkeypatch)
        assert research._spawn_detached_lifecycle("upgrade", restart_after=True) == self.WAITER_PID

    def test_cli_upgrade_is_neither_escaped_nor_restarted(self, monkeypatch, tmp_path):
        # The CLI `--update` (restart_after=False) must stay as-is: no escape, no
        # auto-restart (the user runs `--restart`). Regression guard.
        self._wire_spawn(monkeypatch)
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        seen = {}
        self._popen(monkeypatch, seen=seen)
        assert research._spawn_detached_lifecycle("upgrade") == self.WAITER_PID
        cmd = seen["cmd"]
        assert cmd[0] == "python3"           # no systemd-run prefix
        assert "--then--" not in cmd         # no auto-restart

    def test_spawns_before_freeing_the_venv(self, monkeypatch, tmp_path):
        # Order matters: a failed launch must NOT have already killed the backend.
        # Force Windows so the venv-free kill actually runs (it's needed there for
        # the file lock), then assert spawn precedes kill.
        self._wire_spawn(monkeypatch)
        monkeypatch.setattr(research.sys, "platform", "win32")
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_enumerate_research_py_procs",
                            lambda: [(999, "cmd", "daemon-loop")])
        order = []
        self._popen(monkeypatch, order=order)
        monkeypatch.setattr(research, "_kill_pids", lambda pids: order.append("kill"))
        assert research._spawn_detached_lifecycle("upgrade", restart_after=True) == self.WAITER_PID
        assert order == ["spawn", "kill"], "waiter must be spawned before victims are killed"

    def test_restart_after_does_not_kill_daemon_loop_off_windows(self, monkeypatch, tmp_path):
        # On Unix pipx rebuilds a venv with open files, so the daemon-loop kill is
        # skipped — killing it (the systemd unit's main process) would tear the
        # cgroup down and SIGTERM the worker still writing updateStatus.
        self._wire_spawn(monkeypatch)
        monkeypatch.setattr(research.sys, "platform", "linux")
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_enumerate_research_py_procs",
                            lambda: [(999, "cmd", "daemon-loop")])
        killed = []
        self._popen(monkeypatch)
        monkeypatch.setattr(research, "_kill_pids", lambda pids: killed.extend(pids))
        assert research._spawn_detached_lifecycle("upgrade", restart_after=True) == self.WAITER_PID
        assert killed == [], "must not kill the daemon-loop on the Unix restart_after path"

    def test_cli_upgrade_still_frees_the_venv_off_windows(self, monkeypatch, tmp_path):
        # Regression guard: the CLI path (restart_after=False) must STILL free the
        # venv on Unix, exactly as before.
        self._wire_spawn(monkeypatch)
        monkeypatch.setattr(research.sys, "platform", "linux")
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_enumerate_research_py_procs",
                            lambda: [(999, "cmd", "daemon-loop")])
        killed = []
        self._popen(monkeypatch)
        monkeypatch.setattr(research, "_kill_pids", lambda pids: killed.extend(pids))
        assert research._spawn_detached_lifecycle("upgrade") == self.WAITER_PID
        assert killed == [999], "CLI --update must still free the venv"

    def test_failed_spawn_leaves_backend_running(self, monkeypatch, tmp_path):
        # Force Windows (free_venv=True) so the ONLY reason the kill is skipped is
        # the failed spawn — proving a launch failure never tears the backend down.
        self._wire_spawn(monkeypatch)
        monkeypatch.setattr(research.sys, "platform", "win32")
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        killed = []
        monkeypatch.setattr(research, "_enumerate_research_py_procs",
                            lambda: [(999, "cmd", "daemon-loop")])
        monkeypatch.setattr(research, "_kill_pids", lambda pids: killed.extend(pids))

        def _boom(cmd, **kw):
            raise OSError("no spawn")
        monkeypatch.setattr(research.subprocess, "Popen", _boom)
        assert research._spawn_detached_lifecycle("upgrade", restart_after=True) is None
        assert killed == [], "a failed launch must not tear the backend down"

    def test_restart_and_escape_both_omitted_when_entry_unresolvable(self, monkeypatch, tmp_path):
        # No console script found → append NO `--restart` tail AND no cgroup-escape
        # (there's nothing to restart, so nothing to survive a restart for).
        self._wire_spawn(monkeypatch, entry=None)
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        seen = {}
        self._popen(monkeypatch, seen=seen)
        assert research._spawn_detached_lifecycle("upgrade", restart_after=True) == self.WAITER_PID
        assert "--then--" not in seen["cmd"]
        assert seen["cmd"][0] == "python3", "no cgroup-escape when there is no restart to protect"

    def test_windows_entry_unresolvable_does_not_strand_the_box(self, monkeypatch, tmp_path):
        # Windows normally frees the venv (kills the daemon-loop) — but with NO
        # resolvable console script there's no `--restart` to relaunch it, so killing
        # it would leave the box offline until next logon. Must NOT kill in that case.
        self._wire_spawn(monkeypatch, entry=None)
        monkeypatch.setattr(research.sys, "platform", "win32")
        monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
        monkeypatch.setattr(research, "_enumerate_research_py_procs",
                            lambda: [(999, "cmd", "daemon-loop")])
        killed = []
        self._popen(monkeypatch)
        monkeypatch.setattr(research, "_kill_pids", lambda pids: killed.extend(pids))
        assert research._spawn_detached_lifecycle("upgrade", restart_after=True) == self.WAITER_PID
        assert killed == [], "must not kill the daemon-loop when it can't be restarted"


class TestReapProtectsUpgradeWaiter:
    """_schedule_server_exit reaps the child tree before os._exit; the upgrade
    waiter (a direct child off-Linux) MUST be spared or the update never applies."""

    class _FakeChild:
        def __init__(self, pid, killed):
            self.pid = pid
            self._killed = killed

        def kill(self):
            self._killed.append(self.pid)

    def _fake_psutil(self, monkeypatch, children, killed):
        import types
        fake_children = [self._FakeChild(p, killed) for p in children]
        proc = types.SimpleNamespace(children=lambda recursive=False: fake_children)
        fake_ps = types.SimpleNamespace(
            Process=lambda pid: proc,
            NoSuchProcess=Exception, AccessDenied=Exception,
        )
        import sys as _sys
        monkeypatch.setitem(_sys.modules, "psutil", fake_ps)

    def test_reap_kills_all_when_unprotected(self, monkeypatch):
        killed = []
        self._fake_psutil(monkeypatch, [101, 102, 103], killed)
        n = research._reap_child_processes("test", protect_pids=None)
        assert n == 3 and set(killed) == {101, 102, 103}

    def test_reap_spares_the_protected_waiter(self, monkeypatch):
        killed = []
        self._fake_psutil(monkeypatch, [101, 4242, 103], killed)
        n = research._reap_child_processes("test", protect_pids={4242})
        assert 4242 not in killed, "the upgrade waiter must survive the reap"
        assert set(killed) == {101, 103} and n == 2

    def test_schedule_server_exit_forwards_protect_pids_to_the_reap(self, monkeypatch):
        # Link 3: _schedule_server_exit must forward protect_pids to the reap. Mock
        # the reap (record args) and os._exit (raise to stop the daemon thread), so
        # a mutation dropping the forward is caught without actually exiting pytest.
        import os as _os
        import time as _time
        monkeypatch.setattr(research, "_exit_scheduled", False, raising=False)
        monkeypatch.setattr(research, "_clear_current_run_id_best_effort", lambda *a, **k: None)
        seen = {}
        monkeypatch.setattr(research, "_reap_child_processes",
                            lambda source, protect_pids=None: seen.update(
                                source=source, protect=protect_pids) or 0)

        # No-op the real exit so the daemon thread finishes cleanly (nothing runs
        # after os._exit in _runner) instead of terminating pytest.
        monkeypatch.setattr(_os, "_exit", lambda code: seen.update(exit=code))
        research._schedule_server_exit("test", delay_sec=0, protect_pids={4242})
        for _ in range(60):
            if "protect" in seen:
                break
            _time.sleep(0.05)
        assert seen.get("protect") == {4242}, "protect_pids must reach the reap"

    def test_handle_update_protects_the_waiter_pid(self, monkeypatch):
        # End-to-end wiring: the pid _perform_self_update returns must reach
        # _schedule_server_exit as protect_pids (the load-bearing link for macOS/Win).
        store = {f"devices/{DEV}": {"ownerUid": OWNER}}
        monkeypatch.setattr(research, "_firebase_db", _FakeDB(store))
        monkeypatch.setattr(research, "_sr_version", lambda: "0.1.5")
        monkeypatch.setattr(research, "_detect_supervised", lambda: True)
        monkeypatch.setattr(research, "_QUEUE_STATE", {"running": False, "queue_ref": None})
        monkeypatch.setattr(research, "_perform_self_update",
                            lambda *, force_check=True, restart_after=False: {
                                "state": "started", "current": "0.1.5", "latest": "0.1.6",
                                "reason": "", "waiter_pid": 4242})
        seen = {}
        monkeypatch.setattr(research, "_schedule_server_exit",
                            lambda src, delay_sec=0, protect_pids=None: seen.update(
                                src=src, protect=protect_pids))
        research._handle_update_command({"action": "update", "submittedBy": OWNER}, DEV, None)
        assert seen["protect"] == {4242}, "the waiter pid must be protected from the exit reap"


class TestLifecycleHelpers:
    def test_lifecycle_waiter_compiles(self):
        compile(research._LIFECYCLE_WAITER, "<lifecycle-waiter>", "exec")

    def test_lifecycle_waiter_splits_on_then(self):
        src = research._LIFECYCLE_WAITER
        assert "--then--" in src and "rc == 0" in src  # restart only after a clean upgrade

    def test_lifecycle_waiter_runs_restart_only_on_clean_upgrade(self, tmp_path):
        # EXECUTE the embedded waiter (compile+substring can't catch an inverted
        # gate or an off-by-one split). Use a dead pid so it proceeds immediately;
        # stub `cmd`/`after` as marker-writing python one-liners.
        import subprocess
        import sys as _sys
        py = _sys.executable
        m_cmd = (tmp_path / "cmd.marker").as_posix()
        m_after = (tmp_path / "after.marker").as_posix()

        def waiter(cmd, after):
            return subprocess.run([py, "-c", research._LIFECYCLE_WAITER, "999999",
                                   *cmd, "--then--", *after], timeout=60)

        # clean upgrade (rc 0) → the restart (after) MUST run
        waiter([py, "-c", f"open(r'{m_cmd}','w').close()"],
               [py, "-c", f"open(r'{m_after}','w').close()"])
        assert (tmp_path / "cmd.marker").exists()
        assert (tmp_path / "after.marker").exists(), "restart must run after a clean upgrade"
        # failed upgrade (rc 1) → the restart MUST be skipped (no half-built venv)
        m_after2 = (tmp_path / "after2.marker").as_posix()
        waiter([py, "-c", f"import sys; open(r'{m_cmd}','w').close(); sys.exit(1)"],
               [py, "-c", f"open(r'{m_after2}','w').close()"])
        assert not (tmp_path / "after2.marker").exists(), "no restart after a failed upgrade"

    def test_cgroup_escape_prefix_off_linux(self, monkeypatch):
        monkeypatch.setattr(research.sys, "platform", "win32")
        assert research._cgroup_escape_prefix() == []

    def test_cgroup_escape_prefix_linux_with_systemd_run(self, monkeypatch):
        import shutil
        monkeypatch.setattr(research.sys, "platform", "linux")
        monkeypatch.setattr(shutil, "which",
                            lambda n: "/usr/bin/systemd-run" if n == "systemd-run" else None)
        monkeypatch.setitem(research.os.environ, "XDG_RUNTIME_DIR", "/run/user/1000")
        pre = research._cgroup_escape_prefix()
        assert pre[:2] == ["/usr/bin/systemd-run", "--user"] and pre[-1] == "--"

    def test_cgroup_escape_prefix_linux_no_systemd_run(self, monkeypatch):
        import shutil
        monkeypatch.setattr(research.sys, "platform", "linux")
        monkeypatch.setattr(shutil, "which", lambda n: None)
        assert research._cgroup_escape_prefix() == []

    def test_cgroup_escape_prefix_linux_no_user_manager(self, monkeypatch):
        # systemd-run present but no reachable user bus → `systemd-run --user` would
        # error, so we must NOT emit the prefix (else the escaped waiter never runs).
        import shutil
        monkeypatch.setattr(research.sys, "platform", "linux")
        monkeypatch.setattr(shutil, "which",
                            lambda n: "/usr/bin/systemd-run" if n == "systemd-run" else None)
        monkeypatch.delitem(research.os.environ, "XDG_RUNTIME_DIR", raising=False)
        monkeypatch.delitem(research.os.environ, "DBUS_SESSION_BUS_ADDRESS", raising=False)
        assert research._cgroup_escape_prefix() == []

    def test_installed_sr_entry_prefers_path_shim(self, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which",
                            lambda n: "/usr/local/bin/superresearch" if n == "superresearch" else None)
        assert research._installed_sr_entry() == "/usr/local/bin/superresearch"

    def test_installed_sr_entry_none_without_pipx(self, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda n: None)
        monkeypatch.setattr(research, "_pipx_cmd", lambda: None)
        assert research._installed_sr_entry() is None
