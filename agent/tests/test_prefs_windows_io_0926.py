"""prefs.json under Windows file locking (2026-09-26, the Windows-sync review).

⛔⛔ A GUARD NOTHING EXECUTED. The retry on a colliding read or replace
(`_retrying`, 2026-09-25) was only ever reached by a two-thread test that cannot
fail on POSIX and is serialised by the in-process lock on Windows — so a retry of
one attempt passed everything. These drive the real functions against a real
file in the per-test store (conftest points `config.store_dir()` at tmp), with
the collisions injected where Windows makes them: `Path.read_bytes` and
`os.replace` raising PermissionError.

⛔ NOT HERE: a writer whose read fails for good still saves over the file (the
wipe the same review found). A first fix made every writer RAISE instead, and
cross-verify showed callers that then die after the work is done — a research
queued and reported as a dead bridge, so a retry queues a second, paid run. It
was backed out; the wipe needs a per-writer answer, after the E2E.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from facade import config, prefs


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(prefs._time, "sleep", lambda _s: None)   # retries, instantly
    return config.store_dir()


def _write(store: Path, data) -> Path:
    p = store / "prefs.json"
    store.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(data if isinstance(data, str) else json.dumps(data))
    return p


def _on_disk(p: Path):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _collide(monkeypatch, target, name, times):
    """`target.name` raises PermissionError `times` times, then works; returns the
    call counter."""
    real = getattr(target, name)
    calls = {"n": 0}

    def fake(*a, **kw):
        calls["n"] += 1
        if times is None or calls["n"] <= times:
            raise PermissionError(13, "The process cannot access the file")
        return real(*a, **kw)

    monkeypatch.setattr(target, name, fake)
    return calls


def test_a_read_that_collides_is_retried_until_it_lands(store, monkeypatch):
    """⛔ A read landing mid-replace is refused on Windows; it is retried, and the
    reader sees the file, not `{}` (a parked note that briefly "did not exist").

    Would this pass against a retry of one attempt? No: the first PermissionError
    would end it, and `load()` would return {}."""
    _write(store, {"verbose": True})
    calls = _collide(monkeypatch, Path, "read_bytes", times=3)
    assert prefs.load() == {"verbose": True}
    assert calls["n"] == 4


def test_a_replace_that_collides_is_retried_and_the_write_lands(store, monkeypatch):
    """⛔ A replace onto a file somebody is reading is refused on Windows; it is
    retried, and the change is saved rather than lost.

    Would this pass against a retry of one attempt? No: `set_verbose` would raise."""
    p = _write(store, {"agentLabel": "Studio"})
    calls = _collide(monkeypatch, prefs.os, "replace", times=2)
    prefs.set_verbose(True)
    assert calls["n"] == 3
    assert _on_disk(p) == {"agentLabel": "Studio", "verbose": True}


def test_the_retries_are_bounded(store, monkeypatch):
    """A file that stays locked is given up on after `_IO_RETRIES` tries — a reader
    then sees {} (as it always did), and never spins."""
    _write(store, {"verbose": True})
    calls = _collide(monkeypatch, Path, "read_bytes", times=None)
    assert prefs.load() == {}
    assert calls["n"] == prefs._IO_RETRIES


def test_a_file_that_is_not_json_still_starts_again(store):
    """⭐ What was in it is already lost, so a writer starts the file again."""
    p = _write(store, "{ not json")
    prefs.set_verbose(True)
    assert _on_disk(p) == {"verbose": True}


def test_the_terminal_client_never_reaches_a_real_bridge():
    """⛔⛔ conftest's `_no_real_bridge` promised every test a port nothing listens
    on, and set only the variable the chat scripts read — the terminal client reads
    `config.BRIDGE_PORT`, frozen at import, so it still reached 9876 (the
    developer's live bridge, when one runs). With nothing but the autouse fixtures
    active, both of its bridge calls must find nobody there.

    Would this pass against the conftest an hour ago? Not on a machine running its
    bridge: the origin was http://127.0.0.1:9876 whatever the variable said."""
    from facade import cli
    assert config.bridge_origin() != f"http://127.0.0.1:{config.DEFAULT_BRIDGE_PORT}"
    assert str(config.BRIDGE_PORT) == __import__("os").environ["SUPER_AGENT_BRIDGE_PORT"]
    assert cli._bridge_get("/status", timeout=2) is None
    assert cli._bridge_post("/login/remote/start", {}, timeout=2) is None


def test_a_missing_file_is_created(store):
    p = store / "prefs.json"
    assert not p.exists()
    prefs.set_verbose(True)
    assert _on_disk(p) == {"verbose": True}
