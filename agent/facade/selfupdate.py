"""Self-update for the AGENT (the chat bridge + skill). The agent no longer
updates the Super Research BACKEND — the app surfaces backend updates (the BE
self-reports its version + update signal on its device-doc heartbeat) and the user
runs `superresearch --update` on the Research computer.

Two pieces:
  • version notice — a pip-style "a newer AGENT is on PyPI" nudge, cached 24h so
    it costs at most one short network call per day and can never block or break a
    command. (`latest_on_pypi` is generic and still used for backend INSTALL.)
  • a detached reconnect — "update the agent" REPLACES the persistent install
    (remove the old venv, then install the new one cleanly, restoring the previous
    version if the install fails) and reconnects from it, ONCE the current bridge
    process exits (so the new bridge can bind the freed port). The persistent
    install is what makes updates STICK: the ONLOGON launcher pins sys.path and the
    interpreter to wherever the code that ran `connect` lived, and a `pipx run` venv
    is ephemeral (pipx evicts it), so a launcher pinned there goes stale and a
    reboot resurrects the OLD bridge — or, after eviction, nothing at all (the
    "said updated but stayed vX / reboot brought the old one back" bug). Two things
    stop that now: `ensure_durable_install` puts a real install on the machine
    BEFORE anything is pinned, and `autostart.install` refuses to write a pin whose
    paths sit in the cache. If the persistent venv still can't be resolved the
    ephemeral `pipx run --no-cache` reconnect keeps chat alive (`--no-cache` is
    load-bearing there — `pipx run` reuses its ~14-day cached venv and would re-run
    the STALE build). Mirrors the backend's proven `_spawn_detached_lifecycle` /
    `_LIFECYCLE_WAITER` pattern (research.py).

SUPPLY CHAIN (DGOPS-9507): the install invocations below fetch code from the
configured index that then EXECUTES on the host, and `POST /agent-install` reaches
this path without caller authentication (see bridge.py's TRUST MODEL). They stay
unpinned by hash and by INDEX URL — an internal mirror is a supported
configuration — but they are floored by VERSION, so an update can never move the
host backwards. Which calls carry the floor, and why two deliberately do not, is
at `_agent_floor_spec()` below. The recorded decision and what carries the
residual risk instead (publish rights on the index) are in ARCHITECTURE.md
§ "Package distribution + supply chain". Read it before adding another install
call here.
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

AGENT_PKG = autostart.PKG_NAME   # single definition; autostart owns it (see there)
BACKEND_PKG = "superresearch"
_CACHE_TTL = 86400  # 24h — one PyPI call per package per day at most
_PYPI = "https://pypi.org/pypi/{pkg}/json"


def _cache_path() -> Path:
    return config.store_dir() / ".version_check.json"


# PEP 440 prerelease spellings, normalised (trailing digits stripped). `post` is
# deliberately ABSENT: a post-release is NEWER than its base, so ranking it lower
# would invent an update that doesn't exist — see version_gt's fail-safe rule.
_PRERELEASE_MARKERS = ("a", "b", "c", "rc", "alpha", "beta", "pre", "dev")


def version_gt(a: str, b: str) -> bool:
    """True iff version `a` is strictly newer than `b`.

    Numeric-tolerant (1.0.10 > 1.0.9). A PEP 440 prerelease sorts BELOW its own
    final release (0.2.0rc1 < 0.2.0): the digits alone are identical, so without
    this an RC-to-final bump reads as "no update available" and anyone running an
    RC never gets nudged onto the release. Prereleases of the same version are
    NOT ordered against each other (rc1 vs rc2 compares equal) — PyPI's
    ``info.version`` never offers a prerelease as latest, so RC-to-final is the
    only case that reaches here.

    Every other unparseable thing keeps the old "ignore the suffix" behaviour
    rather than being ranked lower, and any parse error returns False. The rule
    is one-directional: this function may fail to report an update, but it must
    never manufacture one — a false nudge spams every command.
    """
    def parse(v: str) -> tuple:
        nums: list = []
        final = 1  # 1 = a real release; 0 = prerelease, which sorts below it
        for chunk in str(v).split("."):
            digits = ""
            for ch in chunk:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            suffix = chunk[len(digits):].lstrip("-_").lower()
            if suffix.rstrip("0123456789") in _PRERELEASE_MARKERS:
                final = 0
            nums.append(int(digits) if digits else 0)
        return nums, final
    try:
        (na, fa), (nb, fb) = parse(a), parse(b)
        n = max(len(na), len(nb))  # zero-pad so 1.0.0 == 1.0 (no false nag)
        na += [0] * (n - len(na))
        nb += [0] * (n - len(nb))
        return (na, fa) > (nb, fb)
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
# Why replace a persistent install (not just `pipx run`): the ONLOGON launcher
# (autostart.py) pins sys.path AND the interpreter to wherever the code that ran
# `connect` lived. A `pipx run` venv is EPHEMERAL — pipx evicts it — so a launcher
# pinned there goes stale and a reboot resurrects the OLD bridge, or after the
# eviction nothing at all (the "still v0.1.25 after update / reboot brought the old
# one back" bug). A clean `pipx install` gives the launcher a DURABLE venv. If that
# can't be resolved we fall back to the ephemeral `pipx run --no-cache` path, which
# keeps chat alive — and autostart refuses to PIN to it, so the fallback can no
# longer bake the cache into the login launcher.
_RECONNECT_WAITER = r'''
import os, sys, time, json, subprocess
from pathlib import Path
pid = int(sys.argv[1]); cfg = json.loads(sys.argv[2])
pipx = cfg["pipx"]; pkg = cfg["pkg"]; connect_args = cfg["connect_args"]
restart_args = cfg.get("restart_args") or []
# Version-floored requirement (DGOPS-9507, see _agent_floor_spec). `pkg` stays the
# bare name — pipx needs it as the venv/app identity, and only the FRESH-resolve
# calls take the spec. Falls back to the bare name so a cfg written by an older
# build can still drive this waiter.
spec = cfg.get("spec") or pkg
# The version we are running: both the floor a successful install has to clear
# and the build a failed one rolls back to. One value, because it is one fact.
# Absent in a cfg written by an older build, in which case the floor check
# abstains rather than inventing a verdict.
floor = (cfg.get("prev") or "").strip()
# Heartbeat straight INTO the log file, not via stdout. Under the cgroup escape
# systemd-run diverts stdout to the journal, so a print would leave self-update.log
# empty — indistinguishable from "the waiter never started", which is the one thing
# the log has to be able to tell us. Writing the path directly makes an EMPTY log a
# positive signal: no heartbeat means no waiter, full stop. Best-effort and never
# raises: diagnostics must not be able to break the update they are reporting on.
_log = cfg.get("log")
def note(msg):
    if not _log:
        return
    try:
        with open(_log, "a", encoding="utf-8") as fh:
            fh.write("[waiter %s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass
note("started (pid %d), waiting for bridge pid %d to exit" % (os.getpid(), pid))
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
def _local_venvs():
    """pipx's persistent venv root, or None."""
    try:
        r = subprocess.run(pipx + ["environment", "--value", "PIPX_LOCAL_VENVS"],
                           capture_output=True, text=True, timeout=30)
        out = (r.stdout or "").strip()
        return out if (r.returncode == 0 and out) else None
    except Exception:
        return None
def installed_entry():
    """Path to the persistently-installed agent console script, or None."""
    venvs = _local_venvs()
    if not venvs:
        return None
    rel = ("Scripts", pkg + ".exe") if sys.platform == "win32" else ("bin", pkg)
    cand = Path(venvs).joinpath(pkg, *rel)
    return str(cand) if cand.exists() else None
def venv_present():
    """Whether pipx's venv DIRECTORY for us exists — a different question from
    installed_entry(), and the one that decides what pipx will do next.

    A venv whose console script is gone (an earlier uninstall that hit a locked
    file part-way is the way this happens) is still in pipx's way: a plain
    install no-ops on it. Deciding "is one installed" from the script therefore
    skipped the repair on exactly the machines that needed it."""
    venvs = _local_venvs()
    return bool(venvs) and Path(venvs).joinpath(pkg).is_dir()
def installed_version():
    """The version pipx reports as installed, or None if it can't say."""
    try:
        r = subprocess.run(pipx + ["list", "--json"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return None
        v = json.loads(r.stdout or "{}").get("venvs", {}).get(pkg) or {}
        return ((v.get("metadata") or {}).get("main_package") or {}).get("package_version")
    except Exception:
        return None
def _ver(v):
    out = []
    for chunk in (v or "").split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        out.append(int(digits or 0))
    return tuple(out)
def usable_install():
    """Whether what is on disk NOW is something we would be happy to run.

    This is the post-condition, and it exists because a pipx exit code is not
    one. Measured against real pipx: `pipx install <spec>` over an existing venv
    prints "already seems to be installed" and exits 0 — so every "the upgrade
    succeeded" this waiter has ever logged after a failed uninstall was a plain
    install that did nothing. Asking the disk instead of the exit code is the
    difference between reporting an update and performing one.

    Both halves matter: the console script catches the half-broken venv (rc 0,
    still no script), the version catches an index that answered BELOW the floor.
    An unreadable version is treated as fine — refusing on it would trigger a
    destructive repair over a bookkeeping hiccup.

    What it deliberately does NOT claim: that the version moved. The waiter is
    given `>=<the build we are running>` and never the target number, so "the
    upgrade stalled" and "a repair reinstalled the same version" are the same
    observation here and both have to pass. The before/after comparison belongs
    to the backend, which is the side that holds both numbers."""
    if installed_entry() is None:
        return False
    v = installed_version()
    return not (v and floor) or _ver(v) >= _ver(floor)
# 1) Replace the PERSISTENT install. Not `pipx upgrade`: an in-place upgrade
#    LAYERS the new distribution over the old venv, so a module the release
#    deleted stays importable and a half-written venv stays half-written.
#
#    `pipx install --force` is the primary path, and the reasoning is measured
#    rather than inherited. Against real pipx 1.16.5:
#      • a plain `pipx install <spec>` over an existing venv prints "already
#        seems to be installed" and EXITS 0. It is not a clean install with a
#        safety catch, it is a no-op that reports success — including over a
#        venv whose console script is missing, which is the state a half-failed
#        uninstall leaves behind.
#      • `--force` reinstalls the distribution and its dependencies in place, so
#        nothing from the old build survives that pip/uv tracked, and it repairs
#        the script-less venv the plain form cannot touch.
#      • and on FAILURE it is the non-destructive one: pipx explicitly refuses to
#        remove a venv it did not create in the same session ("Not removing
#        existing venv … because it was not created in this session"), so a
#        network blip mid-window leaves the previous agent installed and working.
#
#    Uninstall-first is therefore the RECOVERY order, not the clean one — it is
#    the only thing that clears an obstruction `--force` could not overwrite, and
#    it is also the only order that can leave the host with no agent at all. So
#    it is gated on proof that the replacement is actually fetchable, and
#    followed by a rollback to the build we were running (`prev`).
#
#    DGOPS-9507: every call here is a FRESH resolve with no prior version to be
#    protected by, so each carries the version floor. The rollback is pinned with
#    `==` on purpose — it is a return to a known build, not an update.
def _run(argv):
    try:
        return subprocess.run(argv, timeout=600).returncode == 0
    except Exception:
        return False
def _fetchable():
    """Can the replacement actually be downloaded and run, right now?

    Asked only before the destructive branch. Deleting the working install and
    then discovering the index is unreachable is the one failure mode with no
    way back — the rollback needs the same network the install just failed on.
    This is the same check /agent-install pre-flights with, repeated here
    because minutes have passed since then.

    It is not free, and `--no-cache` does not mean what it sounds like. Measured
    against pipx 1.16.5, it means "do not REUSE a cached run-venv", and what
    happens next depends on the backend: under **pip** the probe builds a new
    entry in PIPX_VENV_CACHEDIR and LEAVES it there; under **uv** it builds in a
    temp dir and deletes it on exit. So the pip case costs a cache entry per
    probe. Acceptable here — the entry is the version we were trying to install,
    not an older one, so a later `pipx run` replaying it cannot walk the host
    backwards, and the cleaner removes it on disconnect. Worth knowing before
    adding another one of these to a path that runs often."""
    return _run(pipx + ["run", "--no-cache", "--spec", spec, pkg, "--version"])
def _do_upgrade():
    if _run(pipx + ["install", "--force", spec]) and usable_install():
        return True
    note("the forced install did not leave a usable install")
    if venv_present() and _fetchable() and _run(pipx + ["uninstall", pkg]):
        # The venv is gone now, so a plain install is a real install.
        if _run(pipx + ["install", spec]) and usable_install():
            return True
    note("clean install failed")
    if floor and _run(pipx + ["install", "--force", "%s==%s" % (pkg, floor)]) \
            and installed_entry():
        note("restored the previous version (%s)" % floor)
    return False
_upgraded = _do_upgrade()
#    Resolve the entry point regardless of the OUTCOME. A rollback that succeeded
#    leaves a perfectly good durable install on disk, and skipping this on failure
#    would send the waiter to the ephemeral fallback — which resolves the floored
#    spec straight back to the release that just refused to install. Reconnecting
#    from the restored build is the whole point of restoring it.
entry = installed_entry()
note("upgrade %s; persistent entry %s" % ("ok" if _upgraded else "FAILED",
                                          entry or "<none> -> pipx run fallback"))
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
    # The version floor goes in `--spec`, NOT the positional. `pipx run`'s
    # positional is the APP name (that is how it decides which console script to
    # execute), so passing a requirement string there relies on pipx parsing the
    # package name back out of it — undocumented behaviour that differs by pipx
    # version. `--spec <requirement> <app>` is the documented pair and keeps the
    # app identity explicit.
    subprocess.run(pipx + ["run", "--no-cache", "--spec", spec, pkg] + connect_args)
note("finished")
'''


def _agent_floor_spec() -> str:
    """`superresearch-agent>=<running version>` — the monotonicity floor (DGOPS-9507).

    A self-update must never move the host BACKWARDS onto an older build. Which of
    the calls in this module need the floor is not uniform, and the difference is
    measurable rather than a judgement call:

      • `pipx upgrade` does NOT need it and must not carry it. It runs
        `pip install --upgrade PACKAGE`, which leaves a newer installed version
        alone when the index's latest is older ("Requirement already satisfied"),
        so it cannot be walked backwards. And pipx SILENTLY DROPS a constraint
        passed to `upgrade` — `pipx upgrade 'pkg>=0.1.31'` exits 0 reporting
        "already at latest version 0.1.30" — so a floor there is not merely
        redundant, it is theatre that reads as protection.
      • `pipx install --force` and `pipx run` DO need it. Both are FRESH resolves —
        --force recreates the venv, run builds an ephemeral one — so neither has a
        prior version to be protected by, and each installs whatever the index
        calls latest, an older build included.

    `>=` and not `==`: re-installing the SAME version has to stay possible, because
    repairing a half-broken venv is a supported use of --update.

    Deliberately NOT an `--index-url` pin. A mirror host still resolves normally;
    it just cannot serve a downgrade. That keeps the mirror configuration working,
    which is why the index pin was declined on DGOPS-9507 in the first place.

    Fails CLOSED, and that is safe here: pipx refuses to remove a venv it did not
    create in the same session, so an unsatisfiable floor exits non-zero with the
    durable venv untouched — the host keeps running the build it already had. The
    pre-flight (`agent_resolvable`) applies this same spec BEFORE the bridge shuts
    down, so the normal outcome is /agent-install declining the update outright
    rather than a bridge that never comes back.
    """
    return f"{AGENT_PKG}>={__version__}"


def ensure_durable_install() -> "tuple[bool, str]":
    """Make sure a DURABLE pipx install exists before anything gets pinned to it.

    `pipx run superresearch-agent connect` is the documented from-chat install, and
    it executes out of a venv pipx evicts. Pinning the login launcher at that
    moment bakes both the interpreter path and the package path into a directory
    with a ~14-day life expectancy — which is why the bridge "starts on an old
    version", or after eviction does not start at all. So: before pinning, put a
    real install on the machine and pin THAT.

    Returns (ok, note). Already-durable is a no-op success — and "durable" now
    excludes an install OLDER than this code, because `agent_dir()` declines to
    redirect to one (see `autostart.durable_is_current`). That is the layer the
    check belongs at: gating HERE would not help, since the caller only reaches
    this function when the pin target already failed the durability test.

    `--force` on the install, and it is not belt-and-braces. Measured against
    real pipx: `pipx install <spec>` over a venv that still exists prints
    "already seems to be installed" and EXITS 0 — so a plain install would report
    success having changed nothing, and we would pin the stale copy while telling
    the user we replaced it. `--force` reinstalls in place instead, and pipx
    refuses to delete a venv it did not create in the same session, so a failure
    leaves the old install working rather than leaving the host with none.

    ⛔ THERE IS NO UNINSTALL FIRST, and the reason is written out in the detached
    waiter a few hundred lines up: uninstall-first "is the RECOVERY order, not the
    clean one", and "the only order that can leave the host with no agent at all".
    `_do_upgrade` therefore runs `--force` first and reaches for `uninstall` only
    after `--force` has already failed AND `_fetchable()` has proved a replacement
    is obtainable, with a floor-pinned rollback behind it. This function used to
    uninstall unconditionally, two lines above a docstring crediting `--force`
    with leaving the old install working — a property the uninstall voided. If the
    install then failed, `cli._pin_startup` returns before `autostart.install()`,
    so the EXISTING pin survives pointing at the venv just deleted, and login
    regresses from starting an old bridge to starting nothing.

    Not preflighting-and-restoring instead: that puts a `pipx run --no-cache`
    resolve into the foreground connect path, which costs minutes and, per
    `_fetchable`'s own note, leaks a run-cache entry per probe under the pip
    backend. The only thing dropping the uninstall gives up is clearing an
    obstruction `--force` cannot overwrite — a Windows file lock — and a lock
    fails the uninstall too, so that recovery was always theoretical."""
    if autostart.pin_target_is_durable():
        return True, ""
    pipx = _pipx_cmd()
    if pipx is None:
        return False, "pipx not found"
    try:
        r = subprocess.run([*pipx, "install", "--force", _agent_floor_spec()],
                           capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001 - surface the reason, never raise into connect
        return False, str(e)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        return False, (tail[-1][:200] if tail else "pipx install failed")
    if not autostart.pin_target_is_durable():
        # pipx exited 0 but we still can't resolve a durable package dir — pinning
        # now would write the cache path anyway, which is the exact bug. Say so.
        return False, "installed, but its package directory couldn't be resolved"
    # The run-cache copy is now dead weight, and a ~14-day-old one is worse than
    # that: `pipx run` reuses it, so a later bootstrap would replay a build older
    # than the install we just made. Dropping it is what makes "no cache needed"
    # true rather than merely intended. Deferred until this process exits — we are
    # running out of the very venv being removed.
    spawn_detached_cache_clear()
    return True, "installed a durable copy to pin to"


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


# How long to wait for the cgroup-escape front-end to report whether systemd
# ACCEPTED the transient unit. `systemd-run` submits and exits in milliseconds, so
# this ceiling only bounds the pathological case; it is the longest the
# /agent-install response can be delayed by the confirmation.
_ESCAPE_CONFIRM_SECS = 5.0


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
    # XDG_RUNTIME_DIR only counts if the directory actually EXISTS. The unit sets
    # it explicitly (autostart.systemd_unit_source) and a unit-level Environment=
    # overrides whatever the manager exported, so on a host that keeps its runtime
    # dir off systemd's default path the variable would be present but wrong.
    # Emitting the prefix then points `systemd-run --user` at a dead bus and the
    # spawn fails outright; returning [] falls back to the plain detached child,
    # which is the pre-existing behaviour and merely degrades.
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and not os.path.isdir(runtime_dir):
        runtime_dir = None
    if not (runtime_dir or os.environ.get("DBUS_SESSION_BUS_ADDRESS")):
        return []
    return [exe, "--user", "--collect", "--quiet", "--"]


def agent_resolvable() -> bool:
    """Pre-flight for a self-update: can pipx actually resolve + run the latest
    agent right now? Lets /agent-install REFUSE (and keep the current bridge alive)
    when the update can't proceed — offline, the package isn't published yet, or
    pipx is broken — instead of shutting the bridge down into a dead end. Uses
    `--no-cache` so it validates the SAME fresh build the reconnect will run (a
    cached run-venv would false-pass on the stale version, hiding a broken/absent
    new release right up until the bridge is already shutting down).

    DGOPS-9507: it resolves against the SAME version floor the waiter will use, and
    that has to stay true. A pre-flight that resolves UNFLOORED while the waiter
    resolves floored would pass here, let /agent-install shut the bridge down, and
    then fail every install attempt in the detached waiter — turning a clean refusal
    into a host with no bridge. Checking the floor here is what makes fail-closed
    safe: the refusal happens while the current bridge is still alive."""
    pipx = _pipx_cmd()
    if pipx is None:
        return False
    try:
        r = subprocess.run([*pipx, "run", "--no-cache", "--spec", _agent_floor_spec(),
                            AGENT_PKG, "--version"],
                           capture_output=True, text=True, timeout=180)
        return r.returncode == 0
    except Exception:
        return False


def _spawn_detached(cmd: list, log_name: str, *, confirm_exit: "float | None" = None) -> bool:
    """Launch `cmd` fully detached (survives this process), logging to
    ~/.super-agent/<log_name>. Returns True if it launched. Stdlib only;
    cross-platform (Windows DETACHED_PROCESS / POSIX start_new_session).

    `confirm_exit` is for a launcher FRONT-END — a command that submits work and
    exits immediately, so its exit STATUS is the only report of whether the work
    was accepted (`systemd-run`, below). With it set, wait up to that many seconds
    and return False if the front-end exited NON-ZERO. A process still running at
    the deadline counts as launched: that is the normal case for the long-lived
    waiter, and it is why this is opt-in rather than the default — polling a child
    that by design outlives us would turn every spawn into a timeout.
    """
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
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=creationflags, **kwargs)
    except Exception:
        return False
    finally:
        if logf is not subprocess.DEVNULL:
            try:
                logf.close()  # the child holds its own dup of the fd
            except Exception:
                pass
    if confirm_exit is None:
        return True
    deadline = time.monotonic() + confirm_exit
    while time.monotonic() < deadline:
        try:
            rc = proc.poll()
        except Exception:
            return True  # can't tell — never report a launch as failed on our own error
        if rc is not None:
            return rc == 0
        time.sleep(0.05)
    return True


def spawn_detached_reconnect() -> bool:
    """Spawn a DETACHED process that, once THIS (bridge) process exits, upgrades the
    PERSISTENT agent install (remove the old venv, then a clean `pipx install`) and
    reconnects from it — fetching the latest agent from PyPI, redeploying the skill,
    re-pinning the ONLOGON launcher to the DURABLE venv (so a reboot comes back on
    the new version), and starting the new bridge. Falls back to the ephemeral
    `pipx run --no-cache … connect` when the persistent venv can't be resolved, so
    it is never worse than before. Returns True if the helper launched.

    The caller (the /agent-install route) shuts the bridge down right after. On an
    unsupervised foreground serve the waiter's connect then binds the freed port;
    on a SUPERVISED host it instead cycles the bridge via `agent restart` (the
    supervisor owns the port, so a reconnect can't rebind it). The waiter is run
    cgroup-escaped on Linux so systemd can't reap it when the unit restarts — and
    the escape is CONFIRMED accepted before being trusted, falling back to a plain
    detached child if systemd rejects the transient unit."""
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
    # `log`: the waiter appends its own heartbeat here so an empty self-update.log
    # means "never started" rather than "started and said nothing" — see the note()
    # helper in the waiter. Resolved HERE because the waiter is stdlib-only and has
    # no access to config.store_dir().
    try:
        log_path = str(config.store_dir() / "self-update.log")
    except Exception:
        log_path = None
    # `spec` is the version floor (DGOPS-9507). Resolved HERE, not in the waiter:
    # the waiter is stdlib-only and cannot import `__version__` from the package it
    # is about to replace — and reading it after the upgrade would compare the new
    # build against itself, which is no floor at all.
    # `prev` is the build we are running, and it answers two questions with one
    # value: the rollback target if the install fails, and the floor a successful
    # install has to clear before the waiter will call it a success (an exit code
    # will not tell it — see `usable_install`). Read here for the same reason
    # `spec` is: the waiter is stdlib-only and cannot import __version__ from a
    # package it is in the middle of replacing.
    cfg = json.dumps({"pipx": pipx, "pkg": AGENT_PKG, "spec": _agent_floor_spec(),
                      "prev": __version__, "connect_args": connect_args,
                      "restart_args": restart_args, "log": log_path})
    # Escape the cgroup ONLY when supervised — that's the only case where systemd's
    # KillMode reaps the waiter as the bridge exits. On an unsupervised foreground
    # serve there's no service cgroup, so a plain detached child survives AND its
    # output still lands in self-update.log (systemd-run would divert it to the
    # journal).
    escape = _cgroup_escape_prefix() if supervised else []
    waiter = [py, "-c", _RECONNECT_WAITER, str(os.getpid()), cfg]
    # CONFIRM, don't assume. `systemd-run` submits a transient unit and exits — it is
    # a front-end, not the waiter — so a bare Popen success only means the FRONT-END
    # started. If systemd then rejects the job (unreachable bus, no user manager
    # despite XDG_RUNTIME_DIR existing, a broken systemd-run), the old code still
    # reported success: /agent-install shut the bridge down, nothing upgraded, and
    # the supervisor brought it back on the OLD version — the same "said updated but
    # stayed vX" symptom this module's docstring describes, reached by a different
    # route. Because the front-end exits immediately its exit status is observable,
    # so a non-zero one means the escape is unusable: fall through to the plain
    # detached child (the pre-escape behaviour, which merely risks the cgroup reap
    # instead of guaranteeing no update at all). `--quiet` still lets the rejection
    # reason through on stderr, which lands in self-update.log above the retry.
    if escape and _spawn_detached(escape + waiter, "self-update.log",
                                  confirm_exit=_ESCAPE_CONFIRM_SECS):
        return True
    return _spawn_detached(waiter, "self-update.log")


def spawn_detached_backend_install() -> bool:
    """Install the Super Research BACKEND on THIS host (``pipx install
    superresearch``) in a detached process — the bridge keeps running (the backend
    is a SEPARATE package, no restart) and the multi-minute install doesn't block
    the HTTP response. Returns True if the install launched. Pairing (stages 2-5:
    API keys + browser logins) is interactive on the host afterwards.

    Deliberately NOT version-floored, unlike the agent calls above (DGOPS-9507).
    The floor there is a MONOTONICITY guard — never move this host backwards from
    the build it is running — and that has no meaning here: this is a first install
    of a DIFFERENT package onto a host that has none, so there is no prior version
    to be walked backwards from. The only floor available would be a literal minimum
    hardcoded in this file, which buys nothing the agent floor buys and goes stale on
    every backend release. Left unfloored on purpose, not by omission."""
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
# cache entries that CONTAIN our package; never touches other tools' caches,
# never raises.
#
# Identified by contents, not by name, because pipx names a run-venv after a
# truncated sha256 of the spec and nothing else — real examples from pipx
# 1.16.5: `aa2125a9e139d3c`, `6b504b0006266e7`. A filter looking for
# "superresearch" in the directory name matches none of them, so the cleaner it
# guarded deleted nothing at all while reporting that it had.
#
# Scope is pipx's OWN run cache, deliberately. A uv-backed pipx runs out of uv's
# archive store instead, and that store does not have the staleness problem this
# cleaner exists for: `uv tool run --from <spec>` re-resolves against the index
# every time, where pipx's cached run-venv is reused as-is for ~14 days. Reaching
# into uv's content-addressed, hard-linked archive by hand would risk other
# tools' environments to fix a problem it does not have.
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
def is_ours(entry):
    """A run-venv that has OUR package installed in it. Mirrors the shape
    autostart._venv_site_packages looks for, on both venv layouts."""
    try:
        if not entry.is_dir():
            return False
        if (entry / "Lib" / "site-packages" / "facade").is_dir():
            return True
        for sp in entry.glob("lib/python*/site-packages"):
            if (sp / "facade").is_dir():
                return True
    except Exception:
        pass
    return False
try:
    root = Path(cachedir)
    if root.is_dir():
        for entry in root.iterdir():
            if is_ours(entry):
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
