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
    monkeypatch.setattr(selfupdate, "latest_on_pypi", lambda pkg: "0.1.8")
    assert selfupdate.agent_update_available() == "0.1.8"
    monkeypatch.setattr(selfupdate, "latest_on_pypi", lambda pkg: "0.1.6")
    assert selfupdate.agent_update_available() is None  # already latest


def test_no_backend_update_available_symbol():
    # The agent no longer surfaces backend updates anywhere — the helper is gone.
    assert not hasattr(selfupdate, "backend_update_available")


def test_spawn_detached_reconnect_builds_pipx_connect(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: None)  # no recorded runtime
    seen = {}

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        return types.SimpleNamespace()

    monkeypatch.setattr(selfupdate.subprocess, "Popen", fake_popen)
    assert selfupdate.spawn_detached_reconnect() is True
    cmd = seen["cmd"]
    assert cmd[0] == "python3" and "-c" in cmd                # waiter runs under a stable python
    assert str(__import__("os").getpid()) in cmd              # waits for THIS bridge pid
    # …then reconnects from the latest published agent. --no-cache is REQUIRED:
    # without it pipx re-runs its cached (stale) run-venv → the stuck-at-vX bug.
    assert cmd[-7:] == ["pipx", "run", "--no-cache", "superresearch-agent",
                        "connect", "--yes", "--no-login"]


def test_spawn_detached_reconnect_targets_recorded_runtime(tmp_path, monkeypatch):
    # The reconnect must pin the SAME runtime that was connected, or a 2-runtime host
    # aborts connect and leaves no bridge (B1).
    monkeypatch.setattr(selfupdate.config, "store_dir", lambda: tmp_path)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate.prefs, "get_runtime", lambda: "hermes")
    seen = {}
    monkeypatch.setattr(selfupdate.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(cmd=cmd) or types.SimpleNamespace())
    assert selfupdate.spawn_detached_reconnect() is True
    assert seen["cmd"][-2:] == ["--runtime", "hermes"]


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
