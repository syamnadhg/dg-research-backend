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


def test_backend_update_available():
    import facade.selfupdate as su

    def with_latest(v):
        su.latest_on_pypi = lambda pkg: v  # type: ignore[assignment]

    orig = su.latest_on_pypi
    try:
        with_latest("0.1.2")
        assert su.backend_update_available("0.1.1") == "0.1.2"
        assert su.backend_update_available("0.1.2") is None
        assert su.backend_update_available(None) is None  # backend not installed
    finally:
        su.latest_on_pypi = orig  # type: ignore[assignment]


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
    # …then reconnects from the latest published agent
    assert cmd[-6:] == ["pipx", "run", "superresearch-agent", "connect", "--yes", "--no-login"]


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


def test_agent_resolvable(monkeypatch):
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="agent 0.1.7"))
    assert selfupdate.agent_resolvable() is True
    monkeypatch.setattr(selfupdate.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout=""))
    assert selfupdate.agent_resolvable() is False  # pipx couldn't resolve (offline / not on PyPI)
    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: None)
    assert selfupdate.agent_resolvable() is False
