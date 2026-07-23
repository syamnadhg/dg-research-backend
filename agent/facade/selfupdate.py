"""Self-update for the AGENT (the chat bridge + skill). The agent no longer
updates the Super Research BACKEND — the app surfaces backend updates (the BE
self-reports its version + update signal on its device-doc heartbeat) and the user
runs `superresearch --update` on the Research computer.

Two pieces:
  • version notice — a pip-style "a newer AGENT is on PyPI" nudge, cached 24h so
    it costs at most one short network call per day and can never block or break a
    command. (`latest_on_pypi` is generic and still used for backend INSTALL.)
  • a detached reconnect — "update the agent" upgrades the PERSISTENT install
    (`pipx install --force superresearch-agent`) and reconnects from it, ONCE the
    current bridge process exits (so the new bridge can bind the freed port). The
    persistent install is what makes updates STICK: the ONLOGON launcher pins
    sys.path to the interpreter that ran `connect`, and a `pipx run` venv is
    ephemeral (pipx evicts it), so a launcher pinned there goes stale and a reboot
    resurrects the OLD bridge (the "said updated but stayed vX / reboot brought the
    old one back" bug). If the persistent venv can't be resolved it falls back to
    the ephemeral `pipx run --no-cache` reconnect (`--no-cache` is load-bearing
    there — `pipx run` reuses its ~14-day cached venv and would re-run the STALE
    build), so it is never worse than before. Mirrors the backend's proven
    `_spawn_detached_lifecycle` / `_LIFECYCLE_WAITER` pattern (research.py).
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

from . import __version__, autostart, config, prefs

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


def agent_update_available(*, force: bool = False) -> "str | None":
    """The newer agent version published on PyPI if one exists, else None.
    `force=True` bypasses the 24h cache for a FRESH read — used when the user
    EXPLICITLY asks ("version" / "any update?"); passive nudges (welcome,
    status) stay on the cached daily read."""
    latest = latest_on_pypi(AGENT_PKG, force=force)
    return latest if (latest and version_gt(latest, __version__)) else None


# NOTE: no `backend_update_available` — the agent no longer surfaces backend
# updates anywhere (chat, bridge /status + /version, or the CLI). The app owns the
# backend-update prompt (the BE self-reports its update signal on its device-doc
# heartbeat; the user runs `superresearch --update` on the Research computer).
# `latest_on_pypi` + `BACKEND_PKG` stay — BACKEND_PKG is still used by
# spawn_detached_backend_install (installing a backend on a fresh host is a
# separate, supported action).


# Detached helper: wait for the bridge process (passed pid) to exit, then upgrade
# the PERSISTENT install and reconnect from it. Stdlib only; cross-platform.
# Mirrors research.py's _LIFECYCLE_WAITER so the freed loopback port lets the NEW
# bridge bind.
#
# Why upgrade a persistent install (not just `pipx run`): the ONLOGON launcher
# (autostart.py) pins sys.path to the dir of whatever interpreter ran `connect`.
# A `pipx run` venv is EPHEMERAL — pipx evicts it — so a launcher pinned there
# goes stale and a reboot resurrects the OLD bridge (the "still v0.1.25 after
# update / reboot brought the old one back" bug). `pipx install --force` pins the
# launcher to a DURABLE venv. If that can't be resolved we fall back to the
# original ephemeral `pipx run --no-cache` path, so this is never worse than before.
_RECONNECT_WAITER = r'''
import os, sys, time, json, subprocess
from pathlib import Path
pid = int(sys.argv[1]); cfg = json.loads(sys.argv[2])
pipx = cfg["pipx"]; pkg = cfg["pkg"]; connect_args = cfg["connect_args"]
restart_args = cfg.get("restart_args") or []
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
def installed_entry():
    """Path to the persistently-installed agent console script, or None."""
    try:
        r = subprocess.run(pipx + ["environment", "--value", "PIPX_LOCAL_VENVS"],
                           capture_output=True, text=True, timeout=30)
        venvs = (r.stdout or "").strip()
        if r.returncode != 0 or not venvs:
            return None
        rel = ("Scripts", pkg + ".exe") if sys.platform == "win32" else ("bin", pkg)
        cand = Path(venvs).joinpath(pkg, *rel)
        return str(cand) if cand.exists() else None
    except Exception:
        return None
# 1) Upgrade the PERSISTENT install so the launcher pins to a durable venv.
entry = None
try:
    r = subprocess.run(pipx + ["install", "--force", pkg], timeout=600)
    if r.returncode == 0:
        entry = installed_entry()
except Exception:
    entry = None
# 2) Connect from the persistent install if resolved; else the ephemeral pipx-run
#    fallback (never worse than before). Both redeploy the skill + re-pin the
#    launcher + start the new bridge.
if entry:
    subprocess.run([entry] + connect_args)
    # 3) On a SUPERVISED host, cycle the bridge via its supervisor so the running
    #    process re-execs the new venv. connect re-pins the launcher/unit, but its
    #    `start` step is a NO-OP when the supervisor already relaunched the OLD
    #    bridge (systemd Restart=always / launchd KeepAlive) — only a real restart
    #    swaps the live code. Without this the update "succeeds" but stays vX (the
    #    reported bug). Skipped (restart_args empty) on an unsupervised foreground
    #    serve, where the reconnect above binds the freed port directly.
    if restart_args:
        try:
            subprocess.run([entry] + restart_args)
        except Exception:
            pass
else:
    subprocess.run(pipx + ["run", "--no-cache", pkg] + connect_args)
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


def _cgroup_escape_prefix() -> "list[str]":
    """Prefix that runs the detached waiter OUTSIDE the bridge's process group.

    On Linux the bridge runs as a systemd --user service's MAIN process, so a
    plain detached child lives in the SAME cgroup — when the bridge exits (and the
    self-update restarts the unit), systemd's default KillMode=control-group reaps
    the child before it can upgrade (the live symptom: an empty self-update.log +
    the bridge stuck on the old version). `systemd-run --user --collect` runs the
    waiter in its OWN transient scope so it survives the bridge's death and the
    supervisor restart. Empty list off-Linux, without systemd-run, or with no user
    manager reachable (macOS/Windows detached children already survive) — so it is
    never worse than before."""
    if not sys.platform.startswith("linux"):
        return []
    exe = shutil.which("systemd-run")
    if not exe:
        return []
    # A user manager must be reachable, else `systemd-run --user` errors out.
    if not (os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("DBUS_SESSION_BUS_ADDRESS")):
        return []
    return [exe, "--user", "--collect", "--quiet", "--"]


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
    """Spawn a DETACHED process that, once THIS (bridge) process exits, upgrades the
    PERSISTENT agent install (`pipx install --force superresearch-agent`) and
    reconnects from it — fetching the latest agent from PyPI, redeploying the skill,
    re-pinning the ONLOGON launcher to the DURABLE venv (so a reboot comes back on
    the new version), and starting the new bridge. Falls back to the ephemeral
    `pipx run --no-cache … connect` when the persistent venv can't be resolved, so
    it is never worse than before. Returns True if the helper launched.

    The caller (the /agent-install route) shuts the bridge down right after. On an
    unsupervised foreground serve the waiter's connect then binds the freed port;
    on a SUPERVISED host it instead cycles the bridge via `agent restart` (the
    supervisor owns the port, so a reconnect can't rebind it). The waiter is run
    cgroup-escaped on Linux so systemd can't reap it when the unit restarts."""
    pipx = _pipx_cmd()
    py = _waiter_python()
    if pipx is None or py is None:
        return False
    connect_args = ["connect", "--yes", "--no-login"]
    # Target the SAME runtime that was originally connected — otherwise a host with
    # both runtimes installed would hit connect's "multiple runtimes — pass
    # --runtime" abort, finish without starting a bridge, and (since we shut the old
    # one down) leave chat dead.
    rt = prefs.get_runtime()
    if rt:
        connect_args += ["--runtime", rt]
    # Cycle the supervisor onto the new venv ONLY when one is pinned. A foreground
    # serve has no supervisor — there the reconnect's own `serve` binds the port.
    supervised = autostart.is_installed()
    restart_args = ["restart"] if supervised else []
    cfg = json.dumps({"pipx": pipx, "pkg": AGENT_PKG, "connect_args": connect_args,
                      "restart_args": restart_args})
    # Escape the cgroup ONLY when supervised — that's the only case where systemd's
    # KillMode reaps the waiter as the bridge exits. On an unsupervised foreground
    # serve there's no service cgroup, so a plain detached child survives AND its
    # output still lands in self-update.log (systemd-run would divert it to the
    # journal).
    escape = _cgroup_escape_prefix() if supervised else []
    cmd = escape + [py, "-c", _RECONNECT_WAITER, str(os.getpid()), cfg]
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


# Detached helper: wait for THIS (disconnect) process to exit, then delete pipx's
# cached `run` venv(s) for the agent. `pipx run` reuses a cached venv for ~14
# days, so without this a post-disconnect `pipx run superresearch-agent connect`
# would replay the STALE build (the same cache trap the self-update path fixes) —
# "removed" wouldn't mean removed. Runs AFTER exit because the venv is in use
# while disconnect (itself a `pipx run …`) is running. Surgical: only removes
# cache entries whose name contains "superresearch"; never touches other tools'
# caches, never raises.
_CACHE_CLEAR_WAITER = r'''
import os, sys, time, shutil
from pathlib import Path
pid = int(sys.argv[1]); cachedir = sys.argv[2]
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
for _ in range(120):  # wait up to ~60s for disconnect to exit
    if not alive(pid):
        break
    time.sleep(0.5)
time.sleep(2)  # grace for the OS to release the venv's files
try:
    root = Path(cachedir)
    if root.is_dir():
        for entry in root.iterdir():
            if "superresearch" in entry.name.lower():
                shutil.rmtree(entry, ignore_errors=True)
except Exception:
    pass
'''


def _pipx_cache_dir() -> "str | None":
    """pipx's `run` venv-cache dir (PIPX_VENV_CACHEDIR) — where
    ``pipx run superresearch-agent …`` caches its throwaway venv. None if pipx
    can't report it (old pipx / not installed)."""
    pipx = _pipx_cmd()
    if pipx is None:
        return None
    try:
        r = subprocess.run([*pipx, "environment", "--value", "PIPX_VENV_CACHEDIR"],
                           capture_output=True, text=True, timeout=30)
        out = (r.stdout or "").strip()
        return out if (r.returncode == 0 and out) else None
    except Exception:
        return None


def spawn_detached_cache_clear() -> bool:
    """After THIS process exits, delete pipx's cached run-venv(s) for the agent so
    a later ``pipx run superresearch-agent connect`` rebuilds fresh from PyPI
    instead of replaying the stale cached build. Used by `disconnect` so a full
    teardown leaves NO stale cache behind. Best-effort — returns True if the
    detached cleaner launched, False if pipx can't report its cache dir."""
    cachedir = _pipx_cache_dir()
    py = _waiter_python()
    if not cachedir or py is None:
        return False
    cmd = [py, "-c", _CACHE_CLEAR_WAITER, str(os.getpid()), cachedir]
    return _spawn_detached(cmd, "cache-clear.log")
