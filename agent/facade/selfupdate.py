"""Self-update for the AGENT (the chat bridge + skill). The agent no longer
updates the Super Research BACKEND — the app surfaces backend updates (the BE
self-reports its version + update signal on its device-doc heartbeat) and the user
runs `superresearch --update` on the Research computer.

Two pieces:
  • version notice — a pip-style "a newer AGENT is on PyPI" nudge, cached 24h so
    it costs at most one short network call per day and can never block or break a
    command. (`latest_on_pypi` is generic and still used for backend INSTALL.)
  • a detached reconnect — "update the agent" is a
    `pipx run --no-cache superresearch-agent connect` that runs ONCE the current
    bridge process exits (so the new bridge can bind the freed port). The
    `--no-cache` is LOAD-BEARING: `pipx run` reuses its cached run-venv for ~14
    days and would otherwise silently re-run the STALE build instead of the
    newly-published one (the "said updated but stayed vX" bug) — the same reason
    connect.py:run_agent_in_wsl forces it for connect/serve/resurrect. This
    mirrors the backend's proven `_spawn_detached_lifecycle` / `_LIFECYCLE_WAITER`
    pattern (research.py).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import __version__, config, prefs

AGENT_PKG = "superresearch-agent"
BACKEND_PKG = "superresearch"
_CACHE_TTL = 86400  # 24h — one PyPI call per package per day at most
_PYPI = "https://pypi.org/pypi/{pkg}/json"


def _cache_path() -> Path:
    return config.store_dir() / ".version_check.json"


def version_gt(a: str, b: str) -> bool:
    """True iff version `a` is strictly newer than `b`. Numeric-tolerant
    (1.0.10 > 1.0.9); non-numeric suffixes are ignored. Returns False on any parse
    error so a weird version string can never spam an upgrade nudge."""
    def parse(v: str) -> list:
        out = []
        for chunk in str(v).split("."):
            digits = ""
            for ch in chunk:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            out.append(int(digits) if digits else 0)
        return out
    try:
        pa, pb = parse(a), parse(b)
        n = max(len(pa), len(pb))  # zero-pad so 1.0.0 == 1.0 (no false nag)
        pa += [0] * (n - len(pa))
        pb += [0] * (n - len(pb))
        return pa > pb
    except Exception:
        return False


def latest_on_pypi(pkg: str, *, force: bool = False) -> "str | None":
    """Latest published version of `pkg` on PyPI, or None. Cached 24h per package
    at ~/.super-agent/.version_check.json; fail-silent on offline / timeout / parse
    so it can NEVER block or break a command. The 2.5s timeout applies at most once
    per day per package (on a cache miss). `force=True` bypasses the cache read for a
    FRESH check (used by the update commands — an explicit "update now" must not be
    decided off a stale 24h cache); it still refreshes the cache."""
    cache = _cache_path()
    now = time.time()
    data: dict = {}
    try:
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                data = {}
            elif not force:
                entry = data.get(pkg) or {}
                if now - float(entry.get("checked_at", 0)) < _CACHE_TTL:
                    return entry.get("latest") or None
    except Exception:
        data = {}
    latest = ""
    try:
        with urllib.request.urlopen(_PYPI.format(pkg=pkg), timeout=2.5) as r:
            latest = ((json.loads(r.read().decode("utf-8")).get("info") or {}).get("version")) or ""
    except Exception:
        latest = ""
    try:
        if not isinstance(data, dict):
            data = {}
        # On a successful fetch cache for the full 24h; on failure (empty result)
        # backdate the stamp so it retries in ~1h — a transient blip must not
        # suppress the notice for a whole day, but an offline host shouldn't re-hit
        # PyPI on every single command either.
        stamp = now if latest else (now - _CACHE_TTL + 3600)
        data[pkg] = {"checked_at": stamp, "latest": latest}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass
    return latest or None


def agent_update_available() -> "str | None":
    """The newer agent version published on PyPI if one exists, else None."""
    latest = latest_on_pypi(AGENT_PKG)
    return latest if (latest and version_gt(latest, __version__)) else None


# NOTE: no `backend_update_available` — the agent no longer surfaces backend
# updates anywhere (chat, bridge /status + /version, or the CLI). The app owns the
# backend-update prompt (the BE self-reports its update signal on its device-doc
# heartbeat; the user runs `superresearch --update` on the Research computer).
# `latest_on_pypi` + `BACKEND_PKG` stay — BACKEND_PKG is still used by
# spawn_detached_backend_install (installing a backend on a fresh host is a
# separate, supported action).


# Detached helper: wait for the bridge process (passed pid) to exit, then run the
# reconnect command. Stdlib only; cross-platform. Mirrors research.py's
# _LIFECYCLE_WAITER so the freed loopback port lets the NEW bridge bind.
_RECONNECT_WAITER = r'''
import os, sys, time, subprocess
pid = int(sys.argv[1]); cmd = sys.argv[2:]
def alive(p):
    if sys.platform == "win32":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, 0, p)  # SYNCHRONIZE
        if not h:
            return False
        r = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
        ctypes.windll.kernel32.CloseHandle(h)
        return r == 0x00000102  # WAIT_TIMEOUT -> still running
    try:
        os.kill(p, 0); return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
for _ in range(120):  # wait up to ~60s for the bridge to exit
    if not alive(pid):
        break
    time.sleep(0.5)
time.sleep(2)  # grace for the OS to release the loopback port
subprocess.run(cmd)
'''


def _pipx_cmd() -> "list[str] | None":
    """How to invoke pipx: the PATH shim if present, else the module form
    (`python -m pipx`) which works even when pipx's shim isn't wired onto PATH."""
    exe = shutil.which("pipx")
    if exe:
        return [exe]
    py = shutil.which("python3") or shutil.which("python") or sys.executable
    return [py, "-m", "pipx"] if py else None


def _waiter_python() -> "str | None":
    """A STABLE interpreter for the detached waiter — a system python on PATH, not
    the ephemeral `pipx run` venv interpreter (which could be evicted while the
    waiter sleeps). Falls back to the current interpreter."""
    return shutil.which("python3") or shutil.which("python") or sys.executable


def agent_resolvable() -> bool:
    """Pre-flight for a self-update: can pipx actually resolve + run the latest
    agent right now? Lets /agent-install REFUSE (and keep the current bridge alive)
    when the update can't proceed — offline, the package isn't published yet, or
    pipx is broken — instead of shutting the bridge down into a dead end. Uses
    `--no-cache` so it validates the SAME fresh build the reconnect will run (a
    cached run-venv would false-pass on the stale version, hiding a broken/absent
    new release right up until the bridge is already shutting down)."""
    pipx = _pipx_cmd()
    if pipx is None:
        return False
    try:
        r = subprocess.run([*pipx, "run", "--no-cache", AGENT_PKG, "--version"],
                           capture_output=True, text=True, timeout=180)
        return r.returncode == 0
    except Exception:
        return False


def _spawn_detached(cmd: list, log_name: str) -> bool:
    """Launch `cmd` fully detached (survives this process), logging to
    ~/.super-agent/<log_name>. Returns True if it launched. Stdlib only;
    cross-platform (Windows DETACHED_PROCESS / POSIX start_new_session)."""
    logf = subprocess.DEVNULL
    try:
        config.store_dir().mkdir(parents=True, exist_ok=True)
        logf = open(config.store_dir() / log_name, "ab")
    except Exception:
        logf = subprocess.DEVNULL
    creationflags = 0
    kwargs: dict = {}
    if sys.platform == "win32":
        creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=creationflags, **kwargs)
        return True
    except Exception:
        return False
    finally:
        if logf is not subprocess.DEVNULL:
            try:
                logf.close()
            except Exception:
                pass


def spawn_detached_reconnect() -> bool:
    """Spawn a DETACHED process that, once THIS (bridge) process exits, runs
    ``pipx run superresearch-agent connect --yes --no-login`` — fetching the latest
    agent from PyPI, redeploying the skill, re-pinning the launcher to the new code,
    and starting the new bridge. Returns True if the helper launched.

    The caller (the /agent-install route) shuts the bridge down right after, so the
    waiter's connect finds the loopback port free and the new bridge binds it."""
    pipx = _pipx_cmd()
    py = _waiter_python()
    if pipx is None or py is None:
        return False
    # --no-cache is REQUIRED: without it `pipx run` re-uses its cached (~14-day)
    # run-venv and re-runs the STALE build, so "update the agent" would redeploy
    # the old version forever (the reported stuck-at-vX bug). Mirrors
    # connect.py:run_agent_in_wsl, which forces it for connect/serve/resurrect.
    reconnect = [*pipx, "run", "--no-cache", AGENT_PKG, "connect", "--yes", "--no-login"]
    # Target the SAME runtime that was originally connected — otherwise a host with
    # both runtimes installed would hit connect's "multiple runtimes — pass
    # --runtime" abort, finish without starting a bridge, and (since we shut the old
    # one down) leave chat dead.
    rt = prefs.get_runtime()
    if rt:
        reconnect += ["--runtime", rt]
    cmd = [py, "-c", _RECONNECT_WAITER, str(os.getpid()), *reconnect]
    return _spawn_detached(cmd, "self-update.log")


def spawn_detached_backend_install() -> bool:
    """Install the Super Research BACKEND on THIS host (``pipx install
    superresearch``) in a detached process — the bridge keeps running (the backend
    is a SEPARATE package, no restart) and the multi-minute install doesn't block
    the HTTP response. Returns True if the install launched. Pairing (stages 2-5:
    API keys + browser logins) is interactive on the host afterwards."""
    pipx = _pipx_cmd()
    if pipx is None:
        return False
    return _spawn_detached([*pipx, "install", BACKEND_PKG], "backend-install.log")
