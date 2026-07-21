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
        monkeypatch.setattr(research, "_spawn_detached_lifecycle", lambda a: spawn)

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

    def _fake_perform(*, force_check=True):
        perform_calls.append(force_check)
        return {"state": perform_state, "current": "0.1.5",
                "latest": "0.1.6", "reason": ""}
    monkeypatch.setattr(research, "_perform_self_update", _fake_perform)
    exits = []
    monkeypatch.setattr(research, "_schedule_server_exit",
                        lambda src, delay_sec=0: exits.append((src, delay_sec)))

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
    assert perform == [True], "forced update must run the upgrade"
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
    assert perform == [True]
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
    assert perform == [True]
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
    assert perform == [True]
    assert _status(store)["state"] == "already"
    assert exits == [], "no process exit when nothing was upgraded"
