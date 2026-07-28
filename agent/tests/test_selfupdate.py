"""Agent self-update: PyPI version notices + the detached reconnect spawner."""

import json
import types

import pytest

from facade import selfupdate


def test_version_gt():
    assert selfupdate.version_gt("0.1.7", "0.1.6")
    assert selfupdate.version_gt("0.1.10", "0.1.9")     # numeric, not lexical
    assert selfupdate.version_gt("1.0.0", "0.9.9")
    assert not selfupdate.version_gt("0.1.6", "0.1.6")  # equal
    assert not selfupdate.version_gt("0.1.5", "0.1.6")  # older
    assert not selfupdate.version_gt("garbage", "0.1.6")  # parse error → False (never nag)
    assert not selfupdate.version_gt("1.0.0", "1.0")    # zero-pad: 1.0.0 == 1.0 (no false nag)
    assert not selfupdate.version_gt("1.0", "1.0.0")


def test_version_gt_ranks_a_prerelease_below_its_own_final_release():
    """The RC-to-final case: digits are identical, so without prerelease ranking
    somebody running 0.2.0rc1 is never told 0.2.0 shipped."""
    for rc in ("0.2.0rc1", "0.2.0b2", "0.2.0a1", "0.2.0.dev3", "0.2.0-rc1", "0.2.0.rc1"):
        assert selfupdate.version_gt("0.2.0", rc), f"{rc} should rank below 0.2.0"
        assert not selfupdate.version_gt(rc, "0.2.0"), f"{rc} must not rank above 0.2.0"
    # A prerelease is still newer than an older FINAL release.
    assert selfupdate.version_gt("0.2.0rc1", "0.1.9")
    # ...and prereleases of the same version are deliberately not ordered.
    assert not selfupdate.version_gt("0.2.0rc2", "0.2.0rc1")


def test_version_gt_never_invents_an_update_from_an_odd_suffix():
    """One-directional guarantee: may miss an update, must never manufacture one.

    `.post1` is the trap — it is NEWER than its base, so treating every
    non-numeric suffix as a prerelease would nudge a post-release user
    'forward' onto the older plain version on every single command.
    """
    assert not selfupdate.version_gt("1.0.0", "1.0.0.post1")
    assert not selfupdate.version_gt("1.0.0", "1.0.0+local.build")
    assert not selfupdate.version_gt("1.0.0", "1.0.0zzz")


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate, "_cache_path", lambda: tmp_path / ".version_check.json")
    return tmp_path


def test_latest_on_pypi_caches_for_24h(cache, monkeypatch):
    # One network call, then served from the 24h cache (no second hit).
    calls = {"n": 0}

    def fake_urlopen(url, timeout=0):
        calls["n"] += 1
        assert "superresearch-agent" in url
        return _FakeResp({"info": {"version": "0.1.9"}})

    monkeypatch.setattr(selfupdate.urllib.request, "urlopen", fake_urlopen)
    assert selfupdate.latest_on_pypi("superresearch-agent") == "0.1.9"
    assert selfupdate.latest_on_pypi("superresearch-agent") == "0.1.9"
    assert calls["n"] == 1  # second read came from the cache


def test_latest_on_pypi_force_bypasses_cache(cache, monkeypatch):
    # An explicit "update now" must re-check PyPI, not trust the 24h cache.
    versions = iter(["0.1.6", "0.1.9"])
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen",
                        lambda url, timeout=0: _FakeResp({"info": {"version": next(versions)}}))
    assert selfupdate.latest_on_pypi("superresearch-agent") == "0.1.6"            # caches 0.1.6
    assert selfupdate.latest_on_pypi("superresearch-agent") == "0.1.6"            # cached (no fetch)
    assert selfupdate.latest_on_pypi("superresearch-agent", force=True) == "0.1.9"  # fresh fetch


def test_latest_on_pypi_failsilent_offline(cache, monkeypatch):
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen",
                        lambda url, timeout=0: (_ for _ in ()).throw(OSError("offline")))
    assert selfupdate.latest_on_pypi("superresearch") is None  # never raises


def test_per_package_cache_is_independent(cache, monkeypatch):
    # Both packages cache side-by-side in one file, keyed by name.
    monkeypatch.setattr(selfupdate.urllib.request, "urlopen",
                        lambda url, timeout=0: _FakeResp({"info": {"version":
                            "9.9.9" if "agent" in url else "1.1.1"}}))
    assert selfupdate.latest_on_pypi("superresearch-agent") == "9.9.9"
    assert selfupdate.latest_on_pypi("superresearch") == "1.1.1"
    data = json.loads((cache / ".version_check.json").read_text())
    assert set(data) == {"superresearch-agent", "superresearch"}


def test_agent_update_available(cache, monkeypatch):
    monkeypatch.setattr(selfupdate, "__version__", "0.1.6")
    monkeypatch.setattr(selfupdate, "latest_on_pypi", lambda pkg, force=False: "0.1.8")
    assert selfupdate.agent_update_available() == "0.1.8"
    monkeypatch.setattr(selfupdate, "latest_on_pypi", lambda pkg, force=False: "0.1.6")
    assert selfupdate.agent_update_available() is None  # already latest


def test_no_backend_update_available_symbol():
    # The agent no longer surfaces backend updates anywhere — the helper is gone.
    assert not hasattr(selfupdate, "backend_update_available")


def test_spawn_detached_reconnect_builds_pipx_connect(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: None)  # no recorded runtime
    # Isolate the inner waiter command: no cgroup-escape prefix, unsupervised host.
    monkeypatch.setattr(selfupdate, "_cgroup_escape_prefix", lambda: [])
    monkeypatch.setattr(selfupdate.autostart, "is_installed", lambda: False)
    seen = {}

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        return types.SimpleNamespace()

    monkeypatch.setattr(selfupdate.subprocess, "Popen", fake_popen)
    assert selfupdate.spawn_detached_reconnect() is True
    cmd = seen["cmd"]
    assert cmd[0] == "python3" and "-c" in cmd                # waiter runs under a stable python
    assert str(__import__("os").getpid()) in cmd              # waits for THIS bridge pid
    # The waiter carries a JSON config: it upgrades the PERSISTENT install
    # (pipx upgrade → --force → uninstall+install, uv-backed-pipx safe) then connects
    # from it (durable ONLOGON launcher), falling back to `pipx run --no-cache`.
    cfg = json.loads(cmd[-1])
    assert cfg["pipx"] == ["pipx"]
    assert cfg["pkg"] == "superresearch-agent"
    assert cfg["connect_args"] == ["connect", "--yes", "--no-login"]  # no runtime pin here
    # Unsupervised (no login pin) → the reconnect binds the freed port itself, so
    # there's no supervisor to restart.
    assert cfg["restart_args"] == []


def test_spawn_detached_reconnect_targets_recorded_runtime(tmp_path, monkeypatch):
    # The reconnect must pin the SAME runtime that was connected, or a 2-runtime host
    # aborts connect and leaves no bridge (B1).
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: "hermes")
    monkeypatch.setattr(selfupdate, "_cgroup_escape_prefix", lambda: [])
    monkeypatch.setattr(selfupdate.autostart, "is_installed", lambda: False)
    seen = {}
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(cmd=cmd) or types.SimpleNamespace())
    assert selfupdate.spawn_detached_reconnect() is True
    cfg = json.loads(seen["cmd"][-1])
    assert cfg["connect_args"][-2:] == ["--runtime", "hermes"]


def test_spawn_detached_reconnect_supervised_cycles_the_supervisor(tmp_path, monkeypatch):
    # On a SUPERVISED host the reconnect can't rebind the port (the supervisor owns
    # it + Restart=always relaunches the OLD build), so the waiter must cycle it via
    # `agent restart` after the upgrade — the fix for "said updated but stayed vX".
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: None)
    monkeypatch.setattr(selfupdate, "_cgroup_escape_prefix", lambda: [])
    monkeypatch.setattr(selfupdate.autostart, "is_installed", lambda: True)  # pinned
    seen = {}
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(cmd=cmd) or types.SimpleNamespace())
    assert selfupdate.spawn_detached_reconnect() is True
    cfg = json.loads(seen["cmd"][-1])
    assert cfg["restart_args"] == ["restart"]


_ESCAPE = ["systemd-run", "--user", "--collect", "--quiet", "--"]


def _escaped_host(tmp_path, monkeypatch, *, escape=None):
    """A supervised Linux host where the cgroup escape is available."""
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: None)
    monkeypatch.setattr(selfupdate.autostart, "is_installed", lambda: True)
    monkeypatch.setattr(selfupdate, "_cgroup_escape_prefix",
                        lambda: list(_ESCAPE if escape is None else escape))


def test_spawn_detached_reconnect_escapes_cgroup_on_linux(tmp_path, monkeypatch):
    # On Linux the waiter must run OUTSIDE the bridge's systemd cgroup, or it's
    # reaped when the unit restarts (the empty self-update.log symptom).
    _escaped_host(tmp_path, monkeypatch)
    seen = {}
    # poll() -> 0: systemd ACCEPTED the transient unit. The front-end is now
    # confirmed rather than assumed, so the fake has to answer for it.
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(cmd=cmd)
                        or types.SimpleNamespace(poll=lambda: 0))
    assert selfupdate.spawn_detached_reconnect() is True
    cmd = seen["cmd"]
    assert cmd[:5] == _ESCAPE
    assert "python3" in cmd and "-c" in cmd  # the waiter still runs, just re-parented


def test_a_rejected_cgroup_escape_falls_back_to_a_plain_detached_child(tmp_path, monkeypatch):
    """systemd-run exiting NON-ZERO must not be reported as a launched update.

    `systemd-run` submits a transient unit and exits, so a bare Popen success only
    proves the FRONT-END started. When systemd then rejects the job (unreachable
    bus, no user manager despite the runtime dir existing), the old code returned
    True: /agent-install shut the bridge down, nothing upgraded, and the supervisor
    restored the OLD version — "said updated but stayed vX" by a second route.
    The escape is an optimisation against the cgroup reap, so losing it must
    degrade to the pre-escape behaviour, never abort the update.
    """
    _escaped_host(tmp_path, monkeypatch)
    calls: list = []

    def fake_popen(cmd, **kw):
        calls.append(cmd)
        # First attempt is the escaped one and is rejected; the fallback is the
        # long-lived waiter, which is still running when we look (poll -> None).
        return types.SimpleNamespace(poll=lambda: 1 if len(calls) == 1 else None)

    monkeypatch.setattr(selfupdate.subprocess, "Popen", fake_popen)
    assert selfupdate.spawn_detached_reconnect() is True
    assert len(calls) == 2, "a rejected escape must be retried unescaped"
    assert calls[0][:5] == _ESCAPE
    assert calls[1][0] == "python3", "the fallback must run the waiter directly"
    assert calls[1][:5] != _ESCAPE


def test_the_unescaped_spawn_is_not_polled_for_an_exit_status(tmp_path, monkeypatch):
    """The waiter OUTLIVES us by design, so confirming its exit would always time out.

    Only the front-end is confirmed. This pins the asymmetry: a fake whose poll()
    raises proves the unescaped path never consults it.
    """
    _escaped_host(tmp_path, monkeypatch, escape=[])  # unsupervised-equivalent: no escape

    def boom():
        raise AssertionError("the plain detached waiter must not be polled")

    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: types.SimpleNamespace(poll=boom))
    assert selfupdate.spawn_detached_reconnect() is True


def test_a_still_running_front_end_counts_as_launched(tmp_path, monkeypatch):
    """Never report a launch as failed just because confirmation timed out.

    A front-end that hasn't exited yet has not been rejected. Returning False here
    would spawn a redundant SECOND waiter, and two waiters racing the same pipx
    venv is worse than the reap this escape exists to avoid.
    """
    _escaped_host(tmp_path, monkeypatch)
    monkeypatch.setattr(selfupdate, "_ESCAPE_CONFIRM_SECS", 0.1)
    calls: list = []
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: calls.append(cmd)
                        or types.SimpleNamespace(poll=lambda: None))
    assert selfupdate.spawn_detached_reconnect() is True
    assert len(calls) == 1, "a slow front-end is not a rejection — no fallback spawn"


def test_the_waiter_heartbeats_into_the_log_file_itself(tmp_path, monkeypatch):
    """Under the escape, stdout goes to the JOURNAL — so the log path is passed in.

    Without a heartbeat written directly to the file, an empty self-update.log is
    ambiguous between "the waiter never started" and "it started and said nothing",
    and that distinction is the whole diagnostic value of the file.
    """
    _escaped_host(tmp_path, monkeypatch)
    seen = {}
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(cmd=cmd)
                        or types.SimpleNamespace(poll=lambda: 0))
    assert selfupdate.spawn_detached_reconnect() is True
    cfg = json.loads(seen["cmd"][-1])
    assert cfg["log"] == str(tmp_path / "self-update.log")
    # The waiter must WRITE to that path, not print — print lands in the journal.
    assert 'open(_log, "a"' in selfupdate._RECONNECT_WAITER
    assert "note(" in selfupdate._RECONNECT_WAITER


def test_cgroup_escape_prefix_linux_with_systemd_run(monkeypatch, tmp_path):
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate.shutil, "which",
                        lambda n: "/usr/bin/systemd-run" if n == "systemd-run" else None)
    # A REAL directory: the runtime dir is now existence-checked, and this test
    # ran off a hardcoded /run/user/1000 that exists on no dev machine.
    monkeypatch.setitem(selfupdate.os.environ, "XDG_RUNTIME_DIR", str(tmp_path))
    pre = selfupdate._cgroup_escape_prefix()
    assert pre[:2] == ["/usr/bin/systemd-run", "--user"] and pre[-1] == "--"


def test_cgroup_escape_prefix_ignores_a_runtime_dir_that_does_not_exist(monkeypatch, tmp_path):
    """A stale/clobbered XDG_RUNTIME_DIR must degrade, not fail the spawn.

    The unit now sets Environment=XDG_RUNTIME_DIR=/run/user/%U, and a unit-level
    Environment= overrides the manager's. On a host whose runtime dir is
    elsewhere that value is present but dead — emitting the prefix would point
    `systemd-run --user` at a bus that isn't there and kill the update entirely,
    which is strictly worse than the plain detached child we fall back to.
    """
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate.shutil, "which",
                        lambda n: "/usr/bin/systemd-run" if n == "systemd-run" else None)
    monkeypatch.setitem(selfupdate.os.environ, "XDG_RUNTIME_DIR", str(tmp_path / "gone"))
    monkeypatch.delitem(selfupdate.os.environ, "DBUS_SESSION_BUS_ADDRESS", raising=False)
    assert selfupdate._cgroup_escape_prefix() == []


def test_cgroup_escape_prefix_still_works_off_the_dbus_address_alone(monkeypatch, tmp_path):
    """DBUS_SESSION_BUS_ADDRESS is an independent signal — a missing runtime dir
    must not veto it, or a host that exports only the bus address loses the escape."""
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate.shutil, "which",
                        lambda n: "/usr/bin/systemd-run" if n == "systemd-run" else None)
    monkeypatch.setitem(selfupdate.os.environ, "XDG_RUNTIME_DIR", str(tmp_path / "gone"))
    monkeypatch.setitem(selfupdate.os.environ, "DBUS_SESSION_BUS_ADDRESS", "unix:path=/x/bus")
    assert selfupdate._cgroup_escape_prefix()[:2] == ["/usr/bin/systemd-run", "--user"]


def test_cgroup_escape_prefix_empty_off_linux(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, "platform", "win32")
    assert selfupdate._cgroup_escape_prefix() == []


def test_cgroup_escape_prefix_empty_without_systemd_run(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate.shutil, "which", lambda n: None)
    assert selfupdate._cgroup_escape_prefix() == []


def test_cgroup_escape_prefix_empty_without_user_manager(monkeypatch):
    # systemd-run present but no reachable user bus → `systemd-run --user` errors,
    # so we must not emit the prefix.
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate.shutil, "which",
                        lambda n: "/usr/bin/systemd-run" if n == "systemd-run" else None)
    monkeypatch.delitem(selfupdate.os.environ, "XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delitem(selfupdate.os.environ, "DBUS_SESSION_BUS_ADDRESS", raising=False)
    assert selfupdate._cgroup_escape_prefix() == []


def test_spawn_detached_reconnect_unsupervised_does_not_escape(tmp_path, monkeypatch):
    # On an unsupervised foreground serve there's no systemd service cgroup to
    # escape, so we must NOT wrap in systemd-run (which would divert the waiter's
    # output to the journal, leaving self-update.log empty). Even if systemd-run is
    # available, the escape is gated on being supervised.
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: None)
    monkeypatch.setattr(selfupdate.autostart, "is_installed", lambda: False)  # unsupervised
    monkeypatch.setattr(selfupdate, "_cgroup_escape_prefix",
                        lambda: ["systemd-run", "--user", "--collect", "--quiet", "--"])
    seen = {}
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(cmd=cmd) or types.SimpleNamespace())
    assert selfupdate.spawn_detached_reconnect() is True
    assert seen["cmd"][0] == "python3", "no cgroup-escape on an unsupervised host"


def test_reconnect_waiter_runs_restart_after_connect():
    # The waiter must cycle the supervisor (restart_args) after connecting from the
    # persistent install — the load-bearing fix. Guard the embedded source.
    src = selfupdate._RECONNECT_WAITER
    assert "restart_args" in src
    assert "[entry] + restart_args" in src


def test_reconnect_waiter_compiles():
    # The waiter is an embedded `-c` string; a typo would only surface at runtime
    # during a real self-update. Compile it here so it's regression-guarded.
    compile(selfupdate._RECONNECT_WAITER, "<reconnect-waiter>", "exec")


def test_reconnect_waiter_upgrade_is_uv_pipx_safe():
    # A uv-backed pipx REFUSES `install --force` on an existing venv ("use --clear"),
    # so the waiter tries `upgrade` (in-place) FIRST, then --force for a standard pipx.
    src = selfupdate._RECONNECT_WAITER
    assert '"upgrade", pkg' in src             # in-place upgrade tried first (uv-safe)
    assert '"install", "--force", pkg' in src  # then force (standard pipx)
    assert "_do_upgrade" in src
    # It must NEVER `pipx uninstall` in the upgrade path: a following install failure
    # would delete the durable venv and strand the host with no install (a MAJOR
    # regression the review caught). Both fail -> non-destructive pipx-run fallback.
    assert '"uninstall"' not in src


def test_spawn_detached_reconnect_no_pipx(monkeypatch):
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: None)
    assert selfupdate.spawn_detached_reconnect() is False


def test_spawn_detached_backend_install(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    seen = {}
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(cmd=cmd) or types.SimpleNamespace())
    assert selfupdate.spawn_detached_backend_install() is True
    assert seen["cmd"] == ["pipx", "install", "superresearch"]  # backend package


def test_spawn_detached_backend_install_no_pipx(monkeypatch):
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: None)
    assert selfupdate.spawn_detached_backend_install() is False


def test_cache_clear_waiter_compiles():
    # The waiter is an embedded `-c` string; a typo would only surface at runtime
    # during a real disconnect. Compile it here so it's regression-guarded.
    compile(selfupdate._CACHE_CLEAR_WAITER, "<cache-clear-waiter>", "exec")


def test_pipx_cache_dir_reads_environment(monkeypatch):
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="/home/u/.local/pipx/.cache\n"))
    assert selfupdate._pipx_cache_dir() == "/home/u/.local/pipx/.cache"
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: None)
    assert selfupdate._pipx_cache_dir() is None


def test_spawn_detached_cache_clear_builds_waiter(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cache_dir", lambda: "/cache/dir")
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    seen = {}
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(cmd=cmd) or types.SimpleNamespace())
    assert selfupdate.spawn_detached_cache_clear() is True
    cmd = seen["cmd"]
    assert cmd[0] == "python3" and "-c" in cmd
    assert str(__import__("os").getpid()) in cmd  # waits for THIS disconnect pid
    assert "/cache/dir" in cmd                     # targets the pipx run-cache dir


def test_spawn_detached_cache_clear_no_cache_dir(monkeypatch):
    monkeypatch.setattr(selfupdate, "_pipx_cache_dir", lambda: None)
    assert selfupdate.spawn_detached_cache_clear() is False


def test_disconnect_clears_pipx_cache():
    # Wiring guard: a full disconnect must clear the agent's pipx run-cache so a
    # reinstall pulls fresh (no stale build replayed).
    import inspect
    from facade import cli
    assert "spawn_detached_cache_clear" in inspect.getsource(cli.cmd_disconnect)


def test_agent_resolvable(monkeypatch):
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    seen = {}

    def _run_ok(*a, **k):
        seen["argv"] = list(a[0])
        return types.SimpleNamespace(returncode=0, stdout="agent 0.1.7")

    monkeypatch.setattr(selfupdate.subprocess, "run", _run_ok)
    assert selfupdate.agent_resolvable() is True
    # The preflight must validate the FRESH build (the one the reconnect will run),
    # not a cached stale venv that would false-pass.
    assert "--no-cache" in seen["argv"]
    monkeypatch.setattr(selfupdate.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout=""))
    assert selfupdate.agent_resolvable() is False  # pipx couldn't resolve (offline / not on PyPI)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: None)
    assert selfupdate.agent_resolvable() is False
