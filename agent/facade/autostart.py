"""Keep the host bridge up across logon — the engine behind `agent resurrect` /
`agent retire`. Cross-platform, one install/uninstall/status/start_detached API
dispatched by OS:

  • Windows — a **Scheduled Task** (`SuperAgentBridge`) that launches the bridge
    WINDOWLESS (pythonw.exe) at logon. The proven, shipping path.
  • Linux   — a **systemd --user** service (`super-agent-bridge.service`).
  • macOS   — a **launchd LaunchAgent** (`io.superresearch.agent-bridge`).

All three launch the SAME tiny generated launcher (~/.super-agent/bridge_launcher.py)
which puts the agent package on sys.path and calls the `serve` entry point, so the
bridge resumes cleanly after a reboot (the account session + device selection persist
in keyring + prefs).

⚠ THE LAUNCHER MUST NEVER POINT INTO PIPX'S RUN CACHE. `pipx run superresearch-agent
connect` — the documented from-chat install — executes out of an EPHEMERAL venv that
pipx evicts (~14 days). Pinning the interpreter and sys.path there produces exactly
the reported symptom: the bridge comes back on an old build, or after eviction does
not come back at all, because both the interpreter path and the package path are
gone. So every pin resolves the DURABLE install (pipx's local venvs dir) first, and
`install()` REFUSES rather than writing a launcher it knows will rot.

The per-OS argv / unit / plist are built by pure functions (unit-testable); only
install / uninstall / status / start_detached shell out.

NOTE: the Windows path is the validated one. The Linux (systemd) and macOS (launchd)
paths are unit-tested at the generation + dispatch level but have NOT yet been
validated end-to-end on a live Linux/macOS host.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

TASK_NAME = "SuperAgentBridge"                    # Windows Scheduled Task name
SYSTEMD_UNIT = "super-agent-bridge.service"       # Linux systemd --user unit
LAUNCHD_LABEL = "io.superresearch.agent-bridge"   # macOS launchd LaunchAgent label

# The distribution name, and the name pipx gives the durable venv it installs into.
# Defined HERE rather than in selfupdate because selfupdate imports this module (the
# reverse import would be circular) — selfupdate re-exports it as AGENT_PKG.
PKG_NAME = "superresearch-agent"


# ── platform ───────────────────────────────────────────────────────────────────

def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def platform_label() -> str:
    if is_windows():
        return "Windows"
    if is_macos():
        return "macOS"
    if is_linux():
        return "Linux"
    return sys.platform


# ── where the DURABLE install lives ──────────────────────────────────────────
# pipx keeps two completely different venv trees and the difference is the whole
# bug: PIPX_LOCAL_VENVS/<pkg> is the persistent install `pipx install` creates and
# `pipx upgrade` maintains, while PIPX_VENV_CACHEDIR holds the throwaway venvs
# `pipx run` builds and evicts. A login pin is only as durable as the paths baked
# into it, so it must resolve the former and must never resolve the latter.

_pipx_values: "dict[str, str | None]" = {}


def _pipx_argv() -> "list[str] | None":
    """How to invoke pipx: the PATH shim, else `python -m pipx`.

    Every lookup is guarded. `shutil.which` is not as inert as it looks — it takes
    a platform-specific branch and can raise on a malformed PATH — and this sits on
    the path-resolution route that `agent_dir()` and therefore every launcher write
    goes through. Failing to find pipx must degrade to "can't tell", never take
    down the caller."""
    try:
        if exe := shutil.which("pipx"):
            return [exe]
        py = shutil.which("python3") or shutil.which("python") or sys.executable
    except Exception:  # noqa: BLE001 - unknowable environment; degrade, don't raise
        return None
    return [py, "-m", "pipx"] if py else None


def _pipx_value(name: str) -> "str | None":
    """`pipx environment --value <NAME>`, or None when pipx is absent or can't
    answer — every caller degrades rather than failing.

    ONLY SUCCESSES ARE MEMOISED. A failure is usually transient (a cold
    `python -m pipx` that overran the timeout, a momentarily busy machine), and
    caching one would make a healthy host look pipx-less for the rest of the
    process: `durable_venv()` returns None, pinning refuses, the bootstrap
    reinstalls over a perfectly good venv, and even after that succeeds the
    re-check reads the same poisoned answer and reports the install unresolvable.
    A repeated subprocess on a genuinely broken host is the cheaper mistake."""
    if _pipx_values.get(name):
        return _pipx_values[name]
    argv = _pipx_argv()
    if argv is None:
        return None
    try:
        r = subprocess.run([*argv, "environment", "--value", name],
                           capture_output=True, text=True, timeout=30)
        out = (r.stdout or "").strip()
    except Exception:  # noqa: BLE001 - no pipx / broken pipx: treat as unknown
        return None
    if r.returncode != 0 or not out:
        return None
    _pipx_values[name] = out
    return out


_uv_cache: "dict[str, str | None]" = {}


def _uv_cache_dir() -> "str | None":
    """`uv cache dir`, or None when uv isn't installed or can't answer.

    Load-bearing, not defensive. When uv is present pipx uses it as the install
    backend by DEFAULT, and a uv-backed `pipx run` does not touch
    PIPX_VENV_CACHEDIR at all — it executes out of uv's own archive store:

        ~/.cache/uv/archive-v0/<hash>/lib/python3.13/site-packages/facade/…
        ~/.cache/uv/archive-v0/<hash>/bin/python

    Measured, not assumed (pipx 1.16.5 + uv 0.9): the pip backend puts the same
    run under `<PIPX_HOME>/.cache/<digest>`, so a check that only knows pipx's
    cache reads uv's as DURABLE and pins it — which is the stale-launcher bug
    itself, on the configuration most machines are now in.

    Memoises successes only, for the reason spelled out in `_pipx_value`."""
    if _uv_cache.get("dir"):
        return _uv_cache["dir"]
    try:
        exe = shutil.which("uv")
    except Exception:  # noqa: BLE001 - malformed PATH; degrade, don't raise
        return None
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "cache", "dir"], capture_output=True, text=True,
                           timeout=30)
        out = (r.stdout or "").strip()
    except Exception:  # noqa: BLE001 - broken uv: treat as unknown
        return None
    if r.returncode != 0 or not out:
        return None
    _uv_cache["dir"] = out
    return out


def _under(child: Path, parent: "Path | None") -> bool:
    if parent is None:
        return False
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:  # noqa: BLE001 - unrelated trees / unresolvable path
        return False


def is_ephemeral(path: Path) -> bool:
    """True when ``path`` lives in a venv the tooling will EVICT (a `run` cache).

    TWO cache roots, because there are two backends and the one in use is the one
    we are least likely to be told about. `pipx run` lands in PIPX_VENV_CACHEDIR
    under the pip backend and in uv's archive store under the uv backend — and uv
    is the DEFAULT whenever uv is installed. Asking only pipx therefore answers
    "durable" for the majority configuration and pins an evictable path, which is
    the entire bug this module exists to stop.

    Containment is the authoritative answer, but only when it says YES. A "no" is
    not conclusive: hosts routinely have two pipxes (a brew one on PATH and a
    `python -m pipx`, or a `PIPX_HOME` exported in the shell that ran `pipx run`
    but not in ours), and the one we can reach reports a different cache root
    than the one we are running out of. So the name check gets to answer too.

    That check is deliberately narrow — it wants BOTH a cache-ish component and a
    tool-ish one — because a false positive (refusing to pin a perfectly good
    source checkout or a dev venv) breaks the install flow outright, while a
    false negative only leaves today's behaviour. `uv` is matched as a whole path
    component, not as a substring, so an ordinary directory that merely contains
    those two letters cannot trip it."""
    for root in (_pipx_value("PIPX_VENV_CACHEDIR"), _uv_cache_dir()):
        if root and _under(path, Path(root)):
            return True
    parts = [p.lower() for p in path.resolve().parts]
    # Being inside pipx's PERSISTENT tree is equally authoritative in the other
    # direction, and it is answered from the path rather than by asking pipx:
    # the ask returns None on exactly the hosts where the name check below is in
    # charge, so an escape built on it evaporates when it is most needed.
    # Reproduced before writing this: with PIPX_HOME under ~/.cache and pipx
    # unreachable, a real durable install answered "evictable" — which makes
    # `install()` refuse and leaves that user with no login pin at all.
    #
    # pipx's persistent tree is always `<PIPX_HOME>/venvs/<pkg>` and its run cache
    # is always `<PIPX_HOME>/.cache/<hash>`, disjoint by construction, so a
    # `venvs` COMPONENT is a durable install however the home was configured.
    # Whole component, not a substring: `<cache>/pipx/venvs-old/<hash>` is a
    # leftover cache tree, not an install.
    if any(p == "venvs" for p in parts):
        return False
    has_cache = any(p in ("cache", ".cache", "caches") for p in parts)
    has_tool = any("pipx" in p for p in parts) or any(p == "uv" for p in parts)
    return has_cache and has_tool


def durable_venv() -> "Path | None":
    """pipx's persistent venv for this package, or None if it isn't installed."""
    venvs = _pipx_value("PIPX_LOCAL_VENVS")
    if not venvs:
        return None
    p = Path(venvs) / PKG_NAME
    return p if p.is_dir() else None


def _venv_site_packages(venv: Path) -> "Path | None":
    """The site-packages inside ``venv`` that actually holds our package. Verified
    by the presence of `facade`, not by path shape: an empty or half-built venv
    must not be reported as a durable home."""
    roots = [venv / "Lib" / "site-packages"] if is_windows() else []
    roots += sorted(venv.glob("lib/python*/site-packages"))
    roots += sorted(venv.glob("Lib/site-packages"))
    for r in roots:
        if (r / "facade").is_dir():
            return r
    return None


def _ver_tuple(v: str) -> tuple:
    """`"0.1.31"` -> `(0, 1, 31)`; anything unparseable in a segment stops it."""
    out = []
    for chunk in (v or "").split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        out.append(int(digits or 0))
    return tuple(out)


def _ver_ge(a: str, b: str) -> bool:
    """Is version `a` at least version `b`?

    Both sides are ZERO-PADDED to the same length first, because tuples of
    different lengths do not compare the way versions do: `(0, 2) < (0, 2, 0)`,
    so `0.2` and `0.2.0` — the same release — would read as one being behind the
    other and the caller would tear down a perfectly good install on every
    connect to "fix" it. `selfupdate.version_gt` pads for the same reason.

    Separate from that function on purpose, and not worth unifying: it compares
    an INDEX version against ours and has to reason about pre-release markers,
    while this only answers "is the copy on disk behind the copy running", where
    both sides are builds we shipped. Keeping it here also keeps this module
    importable with nothing but the stdlib, which is what lets the generated
    launcher use it."""
    ta, tb = _ver_tuple(a), _ver_tuple(b)
    n = max(len(ta), len(tb))
    return ta + (0,) * (n - len(ta)) >= tb + (0,) * (n - len(tb))


def _installed_version(site_packages: Path) -> "str | None":
    """The version of OUR distribution inside ``site_packages``, from the
    dist-info directory name. Read off the filesystem rather than imported:
    `facade.__version__` is `importlib.metadata` against the RUNNING
    interpreter, so importing it would report the version we already know
    instead of the one sitting in the directory we are asking about."""
    stem = PKG_NAME.replace("-", "_") + "-"
    for d in site_packages.glob(stem + "*.dist-info"):
        v = d.name[len(stem):-len(".dist-info")]
        if v:
            return v
    return None


def durable_is_current() -> bool:
    """Whether the durable install is at least as new as the code running now.

    A durable pin is only worth having if it points at a build that is not
    BEHIND us. `pipx run superresearch-agent connect` — the documented from-chat
    install — fetches the newest agent and then asks this module where to pin it;
    if some older `pipx install` is still on the machine, redirecting to it would
    silently downgrade the user with the very command that exists to bring them
    up to date, and permanently, since login starts that copy from then on.

    Unreadable version => treated as CURRENT. A wrong "stale" verdict tears down
    a working install on every connect; a wrong "current" verdict is only
    today's behaviour."""
    venv = durable_venv()
    sp = _venv_site_packages(venv) if venv else None
    if sp is None:
        return False
    there = _installed_version(sp)
    if not there:
        return True
    return _ver_ge(there, _running_version())


def _running_version() -> str:
    """The version of the code executing right now. Imported lazily: `__init__`
    is this package's own module, and importing it at module scope would run the
    package initialiser while the package is still being imported."""
    from . import __version__
    return __version__


def durable_agent_dir() -> "Path | None":
    """site-packages of the DURABLE install — what the launcher should put on
    sys.path. None when there is no durable install worth pointing at, which
    includes one that is OLDER than the copy running (see
    `durable_is_current`)."""
    venv = durable_venv()
    if venv is None or not durable_is_current():
        return None
    return _venv_site_packages(venv)


def durable_python(*, windowless: bool = False) -> "str | None":
    """The DURABLE venv's interpreter — what the service manager should exec.

    Pinning `sys.executable` is half the stale-launcher bug: under `pipx run` that
    interpreter is inside the evictable cache too, so an evicted cache leaves the
    LaunchAgent/unit/task exec'ing a path that no longer exists and the bridge
    simply never comes back.

    Held to the same currency rule as `durable_agent_dir`, and that pairing is
    the point: an interpreter from one build with another build's site-packages
    injected ahead of it is a combination nobody tests."""
    venv = durable_venv()
    if venv is None or not durable_is_current():
        return None
    names = (["pythonw.exe", "python.exe"] if windowless else ["python.exe"]) \
        if is_windows() else ["python3", "python"]
    sub = "Scripts" if is_windows() else "bin"
    for n in names:
        cand = venv / sub / n
        if cand.exists():
            return str(cand)
    return None


# ── shared launcher (every OS runs this) ─────────────────────────────────────

def agent_dir() -> Path:
    """The dir that contains the ``facade`` package (so ``import facade`` works
    even when the service launches with a cwd like C:\\Windows\\System32 or /).

    Prefers the DURABLE install whenever the copy we are running from is one pipx
    will evict. Running from a source checkout or from the durable venv itself
    returns that, unchanged — the redirect is scoped to the cache case."""
    here = Path(__file__).resolve().parent.parent
    if not is_ephemeral(here):
        return here
    return durable_agent_dir() or here


def pin_target_is_durable() -> bool:
    """Whether a pin written right now would survive a pipx cache eviction —
    i.e. `agent_dir()` resolved to something outside the run cache."""
    return not is_ephemeral(agent_dir())


def pythonw_exe() -> str:
    """No-console interpreter (pythonw.exe) sibling of the current interpreter on
    Windows; sys.executable elsewhere (POSIX has no windowless variant — the
    service manager detaches it). Resolves the DURABLE venv's interpreter first
    when we're running out of pipx's evictable run cache."""
    if is_ephemeral(Path(sys.executable)):
        if dur := durable_python(windowless=True):
            return dur
    cur = Path(sys.executable)
    if cur.name.lower() == "python.exe":
        sib = cur.parent / "pythonw.exe"
        if sib.exists():
            return str(sib)
    return str(cur)


def service_python() -> str:
    """The interpreter a Linux/macOS service unit should exec. Same durability
    rule as `pythonw_exe`, without the Windows windowless dance."""
    if is_ephemeral(Path(sys.executable)):
        if dur := durable_python():
            return dur
    return sys.executable


def launcher_path() -> Path:
    """The generated launcher script the service / detached start run."""
    return config.store_dir() / "bridge_launcher.py"


def launcher_source(agentdir: Path | None = None) -> str:
    """Python source for the launcher: inject the agent dir on sys.path, then call
    the `serve` entry point. ``repr`` quotes the path safely (handles Windows
    backslashes), so there are no schtasks-quoting hazards."""
    d = str(agentdir or agent_dir())
    return (
        "# Auto-generated by `agent resurrect` — launches the Super Agent bridge.\n"
        "# Safe to delete; `agent retire` removes it.\n"
        "import sys\n"
        f"sys.path.insert(0, {d!r})\n"
        "from facade.cli import main\n"
        "raise SystemExit(main(['serve']))\n"
    )


def write_launcher(agentdir: Path | None = None) -> Path:
    """Write (refresh) the launcher script; return its path.

    Declines to overwrite an existing launcher with an evictable path. The guard
    lives HERE rather than at the call sites because the call sites are exactly
    where it gets missed: `_win_restart` checked before its own refresh and then
    fell through to `_win_start`, whose first act is an unconditional
    `write_launcher()` — so the path the guard exists to keep out got written by
    the fallback of the function that guarded against it. `_write_systemd_unit`
    and `_darwin_install` had the same shape. One check on the writer covers all
    four, and an explicit ``agentdir`` still wins (callers that pass one have
    already decided what they are pinning).

    Writing the FIRST launcher is still allowed even when only a cache path is
    available: something that works until eviction beats nothing at all, and
    `install()` separately refuses to pin it, so this cannot quietly become the
    login configuration."""
    p = launcher_path()
    if agentdir is None and p.exists() and not pin_target_is_durable():
        log.debug("keeping the existing launcher: nothing durable to point it at")
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(launcher_source(agentdir), encoding="utf-8")
    return p


def _rm_launcher() -> None:
    try:
        launcher_path().unlink(missing_ok=True)
    except OSError:
        pass


def _exec(argv: list[str]) -> tuple[bool, str]:
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if is_windows() else 0
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30, creationflags=no_window)
    except (OSError, subprocess.SubprocessError) as e:  # pragma: no cover - env-specific
        return False, str(e)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


# ── talking to the live bridge ────────────────────────────────────────────────
# A restart has to cycle whatever process HOLDS THE PORT, which is often not the
# thing the service manager launched (on Windows, connect/resurrect start the
# bridge with a detached Popen). These probes reach that process directly.
#
# Stdlib only, deliberately: this module's sole local import is `config` (it runs
# from a generated launcher and from the service manager), so it must not need
# `requests`, and importing `bridge` here would be both heavy and circular-ish.


def _healthz(timeout: float = 2.0) -> dict | None:
    """The live bridge's ``/healthz`` body, or None when nothing there is ours.

    Marker-checked (``{"ok": true, "version": …}``) for exactly the reason
    ``cli._bridge_up`` and ``bridge._port_holder_is_bridge`` are: a foreign server
    squatting the port must never read as the bridge — whatever this says yes to
    is what we go on to POST ``/shutdown`` at."""
    try:
        with urllib.request.urlopen(config.bridge_origin() + "/healthz", timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001 - any transport/parse failure means "not our bridge"
        return None
    if isinstance(body, dict) and body.get("ok") is True and "version" in body:
        return body
    return None


def _post_shutdown(timeout: float = 10.0) -> None:
    """Ask the live bridge to stop — the same call `agent retire` makes.

    Best-effort: connection-refused just means it is already gone, and the bridge
    may well die mid-response (it answers 200, then stops serving on a thread).
    The method MUST be an explicit POST — a bare ``urlopen(url)`` sends GET, which
    ``/shutdown`` answers 404, and every restart would then sit out the stop
    timeout waiting for a bridge nobody asked to stop."""
    req = urllib.request.Request(
        config.bridge_origin() + "/shutdown", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=timeout).close()
    except Exception:  # noqa: BLE001 - already down, or it died answering; both fine
        pass


def _wait_gone(timeout: float) -> bool:
    """True once nothing answers ``/healthz``, plus a grace for the OS to release
    the loopback socket — mirroring the self-update waiter's own exit poll +
    2s port grace. Deliberately NOT a ``bind()`` probe: Windows SO_REUSEADDR
    semantics make a successful bind an ambiguous signal."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _healthz() is None:
            time.sleep(2)
            return True
        time.sleep(0.5)
    return False


def _wait_healthz(timeout: float) -> dict | None:
    """The ``/healthz`` body of a bridge that comes up within ``timeout``, else
    None. A launch that was merely *attempted* leaves nothing here."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = _healthz()
        if body is not None:
            return body
        time.sleep(0.5)
    return None


# ── Windows: Scheduled Task (validated) ──────────────────────────────────────

def run_command(exe: str | None = None, launcher: Path | None = None) -> str:
    """The /TR command line: ``"pythonw.exe" "<launcher>"`` (both quoted)."""
    return f'"{exe or pythonw_exe()}" "{launcher or launcher_path()}"'


def install_argv(task_name: str = TASK_NAME, command: str | None = None) -> list[str]:
    # ONLOGON so it starts at sign-in; LIMITED run level (no elevation); /F
    # overwrites (idempotent re-install). /IT (interactive token) is LOAD-BEARING:
    # without it schtasks makes an S4U task whose logon token cannot decrypt the
    # per-user DPAPI Credential Locker — keyring.get_password() returns nothing and
    # the rehydrated bridge comes up unauthenticated after a reboot, breaking the
    # "resumes cleanly without re-login" promise. pythonw.exe stays windowless
    # regardless of /IT.
    return ["schtasks", "/Create", "/TN", task_name, "/TR", command or run_command(),
            "/SC", "ONLOGON", "/RL", "LIMITED", "/IT", "/F"]


def uninstall_argv(task_name: str = TASK_NAME) -> list[str]:
    return ["schtasks", "/Delete", "/TN", task_name, "/F"]


def status_argv(task_name: str = TASK_NAME) -> list[str]:
    return ["schtasks", "/Query", "/TN", task_name]


def _win_start(exe: str | None = None, launcher: Path | None = None) -> tuple[bool, str]:
    """Start the bridge NOW — windowless + detached, so it survives this process.
    Mirrors research.py's detached daemon-loop spawn."""
    exe = exe or pythonw_exe()
    p = launcher or write_launcher()
    detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    newgroup = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        subprocess.Popen(
            [exe, str(p)],
            creationflags=detached | newgroup | no_window,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, close_fds=True,
        )
    except (OSError, ValueError) as e:  # pragma: no cover - env-specific
        return False, str(e)
    return True, ""


_STOP_WAIT_SECONDS = 45.0   # for the old bridge to let go of the port
_START_WAIT_SECONDS = 45.0   # for a new one to answer /healthz


def _win_restart(task_name: str = TASK_NAME) -> tuple[bool, str]:
    """Cycle the bridge onto the code on disk, and only claim success if it did.

    Stops the LISTENER rather than the scheduled-task instance. The bridge that is
    actually running is usually NOT one the scheduler launched — `agent connect`
    and `agent resurrect` both start it with a detached Popen (`_win_start`), which
    Task Scheduler has no handle on — so `schtasks /End` has nothing to end. And
    `/Run` exits 0 for merely ATTEMPTING a launch. Together those two reported a
    confident success while the very same process kept serving the very same code.

    The wait between stop and start is load-bearing: a second instance started
    while the old one still owns the port finds it taken, recognises the holder as
    a bridge and returns (``bridge.serve``) — leaving the OLD code serving with
    /Run's exit code still saying 0.
    """
    before = _healthz()

    # Refresh the launcher BEFORE stopping anything: the agent dir moves on a pipx
    # upgrade, which is precisely when a restart gets called, and doing it here
    # means an unwritable store dir aborts with the old bridge still serving.
    #
    # …but only when the refresh would be an improvement. Invoked as `pipx run
    # superresearch-agent restart` with no durable install to resolve, this would
    # overwrite a perfectly good pin with cache paths — turning a working login
    # launcher into one that rots. Leaving the existing pin alone is strictly
    # better: the restart below still cycles the bridge. That decision now lives
    # inside `write_launcher`, so the `_win_start` fallback further down honours
    # it too — it used to write the cache path this branch had just refused.
    try:
        write_launcher()
    except OSError as e:
        return False, f"couldn't refresh the bridge launcher: {e}"

    # A scheduler-launched instance, if there happens to be one. Still best-effort
    # (an idle task legitimately returns non-zero) but no longer the only stop
    # path, so its failures are now diagnosable rather than merely swallowed.
    ended_ok, ended_out = _exec(["schtasks", "/End", "/TN", task_name])
    if not ended_ok:
        log.debug("schtasks /End: %s", ended_out)

    # Only ask the holder to stop once we have PROVEN it is our bridge — a blind
    # POST would fire /shutdown at whatever unrelated local service owns the port.
    if before is not None:
        _post_shutdown()
        if not _wait_gone(_STOP_WAIT_SECONDS):
            return False, f"the bridge on port {config.BRIDGE_PORT} did not stop"

    ok, out = _exec(["schtasks", "/Run", "/TN", task_name])
    if not ok:
        return False, out or "schtasks /Run failed"

    after = _wait_healthz(_START_WAIT_SECONDS)
    if after is None:
        # /IT tasks need an interactive session, and the scheduler can decline for
        # reasons it doesn't report. Fall back to the detached start that
        # connect/resurrect already depend on, rather than leaving the host with no
        # bridge at all.
        started, serr = _win_start()
        if started:
            after = _wait_healthz(_START_WAIT_SECONDS)
        if after is None:
            return False, f"restart issued but no bridge came back ({serr or 'no listener'})"

    # Same version is NOT a failure — restarting onto identical code is legitimate
    # (a config change, an operator cycling it) — but it's worth a log line, since
    # after an upgrade it means the new build isn't what came back.
    if before and before.get("version") == after.get("version"):
        log.info("bridge restarted; version unchanged (%s)", after.get("version"))
    return True, "restarted"


# ── Linux: systemd --user service ─────────────────────────────────────────────

def systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT


def systemd_unit_source(exe: str | None = None, launcher: Path | None = None) -> str:
    """The `systemd --user` unit text.

    `Environment=XDG_RUNTIME_DIR` is load-bearing for SELF-UPDATE, not cosmetic.
    ``selfupdate._cgroup_escape_prefix()`` only emits its `systemd-run --user`
    wrapper when a user bus looks reachable, and a unit's environment is not the
    login shell's. Without the escape the update waiter stays in this unit's
    cgroup and systemd's default KillMode=control-group reaps it the instant the
    bridge exits — exactly the documented failure (an empty self-update.log and a
    bridge stuck on the old version). The user manager normally exports this
    variable to its own units already; stating it makes the dependency explicit
    and covers a host where it isn't propagated. `%U` is the unit owner's numeric
    uid, expanded by systemd, and /run/user/$UID is systemd's own default. If a
    host puts the runtime dir elsewhere, the escape degrades to a plain detached
    child rather than failing (see the isdir guard in _cgroup_escape_prefix).
    """
    e = exe or service_python()
    p = str(launcher or launcher_path())
    return (
        "[Unit]\n"
        "Description=Super Agent bridge (Super Research)\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f'ExecStart="{e}" "{p}"\n'  # quoted — systemd splits on spaces otherwise
        'Environment="XDG_RUNTIME_DIR=/run/user/%U"\n'
        "Restart=always\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def systemctl_argv(*verbs: str) -> list[str]:
    return ["systemctl", "--user", *verbs]


def _write_systemd_unit() -> Path:
    write_launcher()
    up = systemd_unit_path()
    up.parent.mkdir(parents=True, exist_ok=True)
    up.write_text(systemd_unit_source(), encoding="utf-8")
    return up


def _linux_install() -> tuple[bool, str]:
    _write_systemd_unit()
    ok, out = _exec(systemctl_argv("daemon-reload"))
    if not ok:
        return ok, out
    return _exec(systemctl_argv("enable", SYSTEMD_UNIT))


def _linux_uninstall() -> tuple[bool, str]:
    ok, out = _exec(systemctl_argv("disable", "--now", SYSTEMD_UNIT))
    try:
        systemd_unit_path().unlink(missing_ok=True)
    except OSError:
        pass
    _rm_launcher()
    if not ok:
        return ok, out
    # disable succeeded → the result that matters now is daemon-reload; surface its
    # failure (with its own message) rather than swallowing it.
    return _exec(systemctl_argv("daemon-reload"))


def _linux_status() -> tuple[bool, str]:
    return _exec(systemctl_argv("is-enabled", SYSTEMD_UNIT))


def _linux_start() -> tuple[bool, str]:
    return _exec(systemctl_argv("start", SYSTEMD_UNIT))


def _linux_restart() -> tuple[bool, str]:
    # `restart` cycles the running unit onto the code on disk. `start` is a NO-OP
    # when the unit is already running (Restart=always keeps it up), so it would
    # keep serving the OLD build after a pipx upgrade.
    return _exec(systemctl_argv("restart", SYSTEMD_UNIT))


# ── macOS: launchd LaunchAgent ───────────────────────────────────────────────

def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def launchd_plist_source(exe: str | None = None, launcher: Path | None = None) -> str:
    e = _xml_escape(exe or service_python())
    p = _xml_escape(str(launcher or launcher_path()))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        f'  <key>Label</key><string>{LAUNCHD_LABEL}</string>\n'
        '  <key>ProgramArguments</key>\n'
        '  <array>\n'
        f'    <string>{e}</string>\n'
        f'    <string>{p}</string>\n'
        '  </array>\n'
        '  <key>RunAtLoad</key><true/>\n'
        '  <key>KeepAlive</key><true/>\n'
        '</dict>\n'
        '</plist>\n'
    )


def launchctl_argv(*verbs: str) -> list[str]:
    return ["launchctl", *verbs]


def _darwin_install() -> tuple[bool, str]:
    write_launcher()
    pl = launchd_plist_path()
    pl.parent.mkdir(parents=True, exist_ok=True)
    pl.write_text(launchd_plist_source(), encoding="utf-8")
    return _exec(launchctl_argv("load", "-w", str(pl)))


def _darwin_uninstall() -> tuple[bool, str]:
    pl = launchd_plist_path()
    ok, out = _exec(launchctl_argv("unload", "-w", str(pl)))
    try:
        pl.unlink(missing_ok=True)
    except OSError:
        pass
    _rm_launcher()
    return ok, out


def _darwin_status() -> tuple[bool, str]:
    return _exec(launchctl_argv("list", LAUNCHD_LABEL))


def _darwin_start() -> tuple[bool, str]:
    return _exec(launchctl_argv("start", LAUNCHD_LABEL))


def _darwin_restart() -> tuple[bool, str]:
    # `kickstart -k` kills then restarts the loaded job in one atomic step, so the
    # bridge re-execs the code on disk. `launchctl start` alone doesn't cycle a
    # KeepAlive job that's already up (it stays on the OLD build after an upgrade).
    label = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
    return _exec(launchctl_argv("kickstart", "-k", label))


# ── dispatch (public API) ─────────────────────────────────────────────────────

def _unsupported() -> tuple[bool, str]:
    return (False, f"run-on-startup isn't supported on this platform ({sys.platform})")


def supported() -> bool:
    """Whether run-on-startup pinning is implemented for this OS."""
    return is_windows() or is_linux() or is_macos()


def kind_label() -> str:
    """What the login-pin is on this OS (for user-facing copy)."""
    if is_windows():
        return "Scheduled Task"
    if is_linux():
        return "systemd --user service"
    if is_macos():
        return "launchd LaunchAgent"
    return "service"


_EPHEMERAL_REFUSAL = (
    "the running copy is in pipx's evictable run cache and there is no durable "
    "install to pin to — install it first: pipx install " + PKG_NAME
)


def install(task_name: str = TASK_NAME) -> tuple[bool, str]:
    """Pin the bridge to start on login — Windows Scheduled Task / Linux systemd
    --user / macOS launchd. (``task_name`` only affects the Windows task name.)

    REFUSES when the only paths available are inside pipx's run cache. A pin
    written there reports success, works until the cache is evicted, and then
    resurrects an old bridge or none at all — a failure that surfaces weeks later
    on a reboot, with nothing on screen tying it back to this moment. Refusing
    here is the whole point of the check: the caller installs durably and retries."""
    if not pin_target_is_durable():
        return False, _EPHEMERAL_REFUSAL
    if is_windows():
        write_launcher()
        return _exec(install_argv(task_name))
    if is_linux():
        return _linux_install()
    if is_macos():
        return _darwin_install()
    return _unsupported()


def uninstall(task_name: str = TASK_NAME) -> tuple[bool, str]:
    """Remove the login pin + the generated launcher (best-effort)."""
    if is_windows():
        ok, out = _exec(uninstall_argv(task_name))
        _rm_launcher()
        return ok, out
    if is_linux():
        return _linux_uninstall()
    if is_macos():
        return _darwin_uninstall()
    return _unsupported()


def status(task_name: str = TASK_NAME) -> tuple[bool, str]:
    if is_windows():
        return _exec(status_argv(task_name))
    if is_linux():
        return _linux_status()
    if is_macos():
        return _darwin_status()
    return _unsupported()


def is_installed(task_name: str = TASK_NAME) -> bool:
    """Whether the login pin currently exists (False on an unsupported OS)."""
    return status(task_name)[0]


def start_detached(exe: str | None = None, launcher: Path | None = None) -> tuple[bool, str]:
    """Start the bridge NOW in the background (windowless on Windows; via the
    service manager on Linux/macOS)."""
    if is_windows():
        return _win_start(exe, launcher)
    if is_linux():
        return _linux_start()
    if is_macos():
        return _darwin_start()
    return _unsupported()


def restart(task_name: str = TASK_NAME) -> tuple[bool, str]:
    """Restart the ALREADY-PINNED background bridge so it re-execs the code on
    disk — the post-update step. A pipx upgrade replaces the package, but the
    running bridge keeps the OLD code in memory until it is cycled, and
    `start_detached` alone can't do it: `systemctl start` / `launchctl start` are
    no-ops on an already-running unit. Mirrors the backend's `_restart_supervisor`
    (whose Windows branch still has the `/End`+`/Run` defect fixed here — see
    `_win_restart`).

    Refuses (False, "not installed") when nothing is pinned. Never raises. On
    Windows it now returns False rather than reporting a success it can't back up:
    `_win_restart` confirms a bridge is actually listening afterwards."""
    if not is_installed(task_name):
        return False, "not installed"
    if is_windows():
        return _win_restart(task_name)
    if is_linux():
        return _linux_restart()
    if is_macos():
        return _darwin_restart()
    return _unsupported()
