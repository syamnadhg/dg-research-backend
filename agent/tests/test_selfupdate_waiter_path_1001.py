"""The reconnect waiter starts with uv's and pipx's homes on its PATH.

pipx replays the backend a venv was built with, and for a uv-built venv it finds
uv only through PATH. The bridge runs under launchd (the plist sets no PATH) or a
systemd user unit, and the waiter used to inherit that narrow PATH — so where uv
lives in ~/.local/bin or /opt/homebrew/bin, every install rung failed, the old
build reconnected, and the host said "updated" while still on the old version.
The backend's own waiter had already been given the wider PATH; these tests drive
`spawn_detached_reconnect` and read what each spawned process was actually given.
"""

import os
import sys
import types

from facade import selfupdate

_NARROW = os.pathsep.join(["/usr/bin", "/bin"])
_ESCAPE = ["systemd-run", "--user", "--collect", "--quiet", "--"]


def _local_bin() -> str:
    return os.path.join(os.path.expanduser("~"), ".local", "bin")


def _host(tmp_path, monkeypatch, *, supervised, escape=()):
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: None)
    monkeypatch.setattr(selfupdate.autostart, "is_installed", lambda: supervised)
    monkeypatch.setattr(selfupdate, "_cgroup_escape_prefix", lambda: list(escape))
    # What a supervisor hands the bridge: no uv home anywhere on it.
    monkeypatch.setenv("PATH", _NARROW)
    calls: list = []

    def fake_popen(cmd, **kw):
        calls.append((cmd, kw))
        # The escaped front-end exits 0 (systemd accepted the unit); the plain
        # waiter is still running when looked at.
        return types.SimpleNamespace(poll=lambda: 0 if cmd[0] == "systemd-run" else None)

    monkeypatch.setattr(selfupdate.subprocess, "Popen", fake_popen)
    return calls


def _dirs(path_value: str) -> list:
    return path_value.split(os.pathsep)


def test_a_plain_detached_waiter_gets_the_uv_homes_first_on_its_path(tmp_path, monkeypatch):
    """macOS, Windows and an unsupervised serve all spawn the waiter directly, so
    Popen's env is the only way the wider PATH can reach it."""
    calls = _host(tmp_path, monkeypatch, supervised=False)
    assert selfupdate.spawn_detached_reconnect() is True
    assert len(calls) == 1
    cmd, kw = calls[0]
    assert cmd[0] == "python3"
    env = kw.get("env")
    assert env is not None, "the waiter inherited the supervisor's PATH unchanged"
    dirs = _dirs(env["PATH"])
    assert _local_bin() in dirs, dirs
    if sys.platform != "win32":
        assert "/opt/homebrew/bin" in dirs, dirs
    # The supervisor's own entries stay, behind the tool homes.
    assert "/usr/bin" in dirs and "/bin" in dirs, dirs
    assert dirs.index(_local_bin()) < dirs.index("/usr/bin"), dirs


def test_a_supervised_linux_waiter_hands_its_path_to_the_transient_unit(tmp_path, monkeypatch):
    """systemd-run gives the transient unit the user manager's environment, not
    ours, so the PATH has to ride in the command, as a systemd-run option."""
    calls = _host(tmp_path, monkeypatch, supervised=True, escape=_ESCAPE)
    assert selfupdate.spawn_detached_reconnect() is True
    assert len(calls) == 1, "an accepted escape needs no fallback spawn"
    cmd, _kw = calls[0]
    setenv = [a for a in cmd if a.startswith("--setenv=PATH=")]
    assert len(setenv) == 1, cmd
    # Before the `--`: after it, systemd-run would try to run `--setenv=…` as the
    # command instead of passing it on.
    assert cmd.index(setenv[0]) < cmd.index("--"), cmd
    assert cmd[cmd.index("--") + 1] == "python3", cmd
    dirs = _dirs(setenv[0][len("--setenv=PATH="):])
    assert _local_bin() in dirs and "/usr/bin" in dirs, dirs


def test_the_fallback_after_a_rejected_escape_still_gets_the_path(tmp_path, monkeypatch):
    """When systemd rejects the unit, the waiter runs as a plain child — which is
    exactly the case where only Popen's env can carry the PATH."""
    calls = _host(tmp_path, monkeypatch, supervised=True, escape=_ESCAPE)

    def rejecting_popen(cmd, **kw):
        calls.append((cmd, kw))
        return types.SimpleNamespace(poll=lambda: 1 if cmd[0] == "systemd-run" else None)

    monkeypatch.setattr(selfupdate.subprocess, "Popen", rejecting_popen)
    assert selfupdate.spawn_detached_reconnect() is True
    assert len(calls) == 2, calls
    cmd, kw = calls[1]
    assert cmd[0] == "python3"
    assert kw.get("env") is not None, "the fallback waiter got the narrow PATH"
    assert _local_bin() in _dirs(kw["env"]["PATH"])


def test_the_waiter_keeps_the_rest_of_our_environment_and_no_duplicates(tmp_path, monkeypatch):
    calls = _host(tmp_path, monkeypatch, supervised=False)
    monkeypatch.setenv("PATH", os.pathsep.join([_local_bin(), "/usr/bin"]))
    monkeypatch.setenv("SR_WAITER_KEEP_1001", "kept")
    assert selfupdate.spawn_detached_reconnect() is True
    env = calls[0][1]["env"]
    assert env["SR_WAITER_KEEP_1001"] == "kept"
    dirs = _dirs(env["PATH"])
    assert dirs.count(_local_bin()) == 1, dirs
