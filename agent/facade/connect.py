r"""`agent connect` — install the Super Research skill into a chat runtime.

Copies the bundled skill (``facade/skill/`` — SKILL.md + scripts/sr.py) into the
runtime's skills directory. Both Hermes and OpenClaw use Anthropic Agent-Skills,
so one bundle serves both; only the install path differs.

Detection looks in two places, since a runtime may live on this host OR inside a
WSL distro:
  • Windows home    — ~/.hermes, ~/.openclaw
  • WSL distro home — \\wsl.localhost\<distro>\home\<user>\.hermes|.openclaw
Model A: the bridge co-locates with the RUNTIME, so a co-located runtime shares
its loopback natively. A WSL runtime's bridge must run IN WSL too — so connect
hands a WSL target off to the in-distro package (``run_connect_in_wsl``) instead
of bridging Windows↔WSL networking.

Pure file-copy + path logic, no network — the bundle is a thin client that calls
the already-running bridge at runtime. Install paths are overridable (``home`` /
``dest``) so this is unit-testable without touching the real runtime dirs.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# ── runtime profiles ─────────────────────────────────────────────────────────
# Everything that differs between chat runtimes, in ONE place — so connect / cli /
# install logic reads a runtime's deltas from a RuntimeProfile instead of
# scattering `if runtime == "hermes"` branches across the module. (sr.py is the
# standalone skill client copied INTO the runtime and CANNOT import this — it
# stays self-contained; SKILL.md gates its own runtime-specific guidance.)
#
# DIR-LEAF INVARIANT: every runtime installs the skill into a dir whose LEAF ==
# the SKILL.md frontmatter `name:` ("sr"). The gateway REGISTERS the /command from
# the frontmatter `name` (the directory name is only a fallback), but the hub's
# install/lookup resolves a skill by `parent.name == name`, and the historical
# skill_view loader keyed off the directory too — a mismatch produced the
# 2026-06-11 "Skill 'sr' not found" → endless-typing failure. So keep dir-leaf ==
# frontmatter name; install() enforces it at runtime and test_connect pins it.

@dataclass(frozen=True)
class RuntimeProfile:
    """The per-runtime deltas the facade needs: display + install path + whether
    the /sr skill can arm a per-chat background job + how skills reload."""

    name: str                            # "hermes" | "openclaw"
    label: str                           # display name in the branded picker
    icon: str                            # brand glyph (⚚) or emoji (🦞)
    rgb: tuple[int, int, int]            # brand tint for the name (and a vector glyph)
    skill_subpath: Path                  # skills dir relative to home; LEAF == "sr"
    # Can the /sr skill arm a PER-CHAT recurring job from WITHIN chat? Hermes
    # exposes a `cronjob` no_agent tool the skill calls; OpenClaw's cron is
    # admin/operator.admin-gated and runs in the gateway process (not as an agent
    # exec call — issue #66142), so the skill cannot arm it → no chat watchdog.
    has_chat_armable_scheduler: bool
    # In-chat command to re-scan skills so /sr registers after a file-copy install
    # (Hermes caches its skill scan). None when the runtime auto-watches the skill
    # dir and so needs no manual reload.
    reload_hint: str | None

    @property
    def meta(self) -> dict:
        """Back-compat view for the branded picker (the old RUNTIME_META row)."""
        return {"label": self.label, "icon": self.icon, "rgb": self.rgb}


# Insertion order is load-bearing: detect_targets / the picker list runtimes in
# this order (openclaw, then hermes), matching the prior RUNTIMES/RUNTIME_META.
#   • OpenClaw — 🦞 (emoji, native red) + RED glowing name
#   • Hermes   — ⚚ staff-of-Hermes glyph tinted gold #E0A33A + GOLD glowing name
PROFILES: dict[str, RuntimeProfile] = {
    "openclaw": RuntimeProfile(
        name="openclaw",
        label="OpenClaw",
        icon="🦞",
        rgb=(231, 76, 60),
        skill_subpath=Path(".openclaw") / "workspace" / "skills" / "sr",
        has_chat_armable_scheduler=False,
        reload_hint=None,  # OpenClaw auto-watches the skill dir (skills.load.watch) — no manual reload command
    ),
    "hermes": RuntimeProfile(
        name="hermes",
        label="Hermes",
        icon="⚚",
        rgb=(224, 163, 58),
        skill_subpath=Path(".hermes") / "skills" / "research" / "sr",
        has_chat_armable_scheduler=True,
        reload_hint="/reload-skills",
    ),
}


def profile(runtime: str) -> RuntimeProfile:
    """The RuntimeProfile for ``runtime`` (raises KeyError on an unknown one)."""
    return PROFILES[runtime]


# Derived back-compat views — existing call sites read these unchanged.
RUNTIMES: dict[str, Path] = {name: p.skill_subpath for name, p in PROFILES.items()}
RUNTIME_META: dict[str, dict] = {name: p.meta for name, p in PROFILES.items()}

# Prior install leaves (pre-rename). install() prunes a stale sibling from these
# on re-connect and uninstall() sweeps them too, so an upgrade never leaves two
# copies of the skill advertising the same name.
_LEGACY_LEAVES = ("super-research",)

# Pin/override the WSL distro list (skips `wsl -l -q`); comma-separated.
WSL_DISTRO_ENV = "SUPER_AGENT_WSL_DISTRO"


def host_os_label() -> str:
    """Human label for the OS this bridge runs on (it co-locates with the
    backend). A "local" runtime install lives on this same host by definition."""
    return {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux")


def looks_containerized() -> bool:
    """Best-effort: is THIS bridge host running inside a container (Linux signals
    only)? Advisory — used to caveat the co-located "reaches loopback" claim,
    because a runtime in a SEPARATE network namespace can't reach a container's
    loopback. Never raises; False off-Linux / on any read failure."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        if Path("/.dockerenv").exists():
            return True
        cg = Path("/proc/1/cgroup")
        if cg.exists():
            text = cg.read_text(errors="ignore")
            return any(k in text for k in ("docker", "containerd", "lxc", "kubepods"))
    except OSError:
        pass
    return False


@dataclass(frozen=True)
class Target:
    """A concrete place to install the skill: a runtime + the home that holds it."""

    runtime: str           # "hermes" | "openclaw"
    location: str          # "local" (this host, shares the bridge's loopback) | "wsl"
    home: Path             # the home dir containing .hermes / .openclaw
    distro: str | None = None  # WSL distro name (None for a local install)

    @property
    def dest(self) -> Path:
        return self.home / RUNTIMES[self.runtime]

    @property
    def where(self) -> str:
        # "local" renders as the actual host OS (Windows/Linux/macOS) — a local
        # target is, by construction, found under this host's home.
        return f"WSL · {self.distro}" if self.location == "wsl" else host_os_label()


def skill_src_dir() -> Path:
    """The bundled skill source shipped inside the package."""
    return Path(__file__).parent / "skill"


def runtime_dest(runtime: str, home: Path | None = None) -> Path:
    base = home or Path.home()
    return base / RUNTIMES[runtime]


def detect_runtimes(home: Path | None = None) -> list[str]:
    """Runtimes whose top-level dir (~/.hermes, ~/.openclaw) exists on this host.

    Windows-local only — kept for back-compat (the bridge's revoke path + older
    callers). The interactive flow uses ``detect_targets`` (which also sees WSL).
    """
    base = home or Path.home()
    return [rt for rt, rel in RUNTIMES.items() if (base / rel.parts[0]).exists()]


# ── WSL discovery ───────────────────────────────────────────────────────────

def wsl_distros() -> list[str]:
    """Installed WSL distro names (empty off-Windows or on any failure).

    Honors ``SUPER_AGENT_WSL_DISTRO`` (comma-separated) to skip the subprocess.
    ``wsl -l -q`` emits UTF-16LE, one distro per line, sometimes with a trailing
    default-distro marker / NULs — decoded + cleaned here.
    """
    pinned = os.environ.get(WSL_DISTRO_ENV)
    if pinned:
        return [d.strip() for d in pinned.split(",") if d.strip()]
    if sys.platform != "win32":
        return []
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        r = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            capture_output=True, timeout=15, creationflags=no_window,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    text = (r.stdout or b"").decode("utf-16-le", errors="ignore")
    out: list[str] = []
    for ln in text.splitlines():
        # Some Windows builds prefix a UTF-16 BOM (U+FEFF) and/or pad with NULs;
        # str.strip() removes neither, so scrub them explicitly before trimming.
        name = ln.replace("\x00", "").replace("\ufeff", "").strip()
        if name and name not in out:
            out.append(name)
    return out


def wsl_root(distro: str) -> Path:
    """The Windows UNC mount point for a WSL distro's filesystem."""
    return Path(rf"\\wsl.localhost\{distro}")


def wsl_user_homes(distro: str, root: Path | None = None) -> list[Path]:
    """Candidate home dirs inside a WSL distro: every /home/* dir plus /root.

    ``root`` overrides the UNC mount (tests point it at a fake tree). Bounded +
    best-effort: a distro that isn't running / mounted yields []."""
    base = root or wsl_root(distro)
    homes: list[Path] = []
    try:
        home_parent = base / "home"
        if home_parent.exists():
            homes.extend(sorted(p for p in home_parent.iterdir() if p.is_dir()))
        root_home = base / "root"
        if root_home.exists():
            homes.append(root_home)
    except OSError:
        pass
    return homes


def detect_wsl_targets(distros: list[str] | None = None,
                       root_for: Callable[[str], Path] | None = None) -> list[Target]:
    """Targets for runtimes installed in any WSL distro (Windows only).

    ``distros`` / ``root_for`` are injectable for tests (``root_for(distro)`` →
    the distro's UNC/fake root)."""
    if sys.platform != "win32" and distros is None:
        return []
    out: list[Target] = []
    for distro in (distros if distros is not None else wsl_distros()):
        root = root_for(distro) if root_for else wsl_root(distro)
        for home in wsl_user_homes(distro, root=root):
            for rt, rel in RUNTIMES.items():
                if (home / rel.parts[0]).exists():
                    out.append(Target(rt, "wsl", home, distro))
    return out


def detect_targets(home: Path | None = None, *, include_wsl: bool = True) -> list[Target]:
    """Every place a runtime is found — Windows-local first, then WSL distros."""
    base = home or Path.home()
    targets: list[Target] = [
        Target(rt, "local", base)
        for rt, rel in RUNTIMES.items()
        if (base / rel.parts[0]).exists()
    ]
    if include_wsl:
        targets.extend(detect_wsl_targets())
    return targets


# ── WSL delegation (Model A: connect runs INSIDE the distro) ─────────────────
# A loopback-only bridge can only be reached by a runtime on its OWN machine, so
# a WSL runtime's bridge must run IN WSL (not on Windows). Instead of the old
# mirrored-networking dance, connect runs its own self-install inside the distro
# via the published package — the bridge then co-locates with the WSL runtime and
# shares WSL's loopback natively.

def wsl_uvx_available(distro: str) -> bool:
    """Is ``uvx`` resolvable inside ``distro``? (i.e. is uv installed there.)

    Probed through a LOGIN shell (``bash -lc``) so it sees the same PATH an
    interactive WSL session does — uv installs to ~/.local/bin, which a bare
    ``wsl -- <cmd>`` PATH usually omits. False off-Windows / on any failure."""
    if sys.platform != "win32":
        return False
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        r = subprocess.run(
            ["wsl.exe", "-d", distro, "--", "bash", "-lc", "command -v uvx"],
            capture_output=True, timeout=15, creationflags=no_window,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def run_connect_in_wsl(distro: str, extra_args: list[str] | None = None) -> int:
    """Run the agent's own ``connect`` INSIDE ``distro`` via the published package
    (``uvx superresearch-agent connect``), so the bridge lands with the WSL
    runtime. Runs through a LOGIN shell (uv's PATH) and INHERITS stdio, so the
    in-distro connect's interactive 4-step flow drives this same terminal. Returns
    its exit code; 1 off-Windows or if ``wsl`` can't be launched (a non-zero from a
    started connect — e.g. uvx can't resolve the package pre-PyPI — flows through
    so the caller can offer the manual fallback)."""
    if sys.platform != "win32":
        return 1
    inner = " ".join(
        shlex.quote(p)
        for p in ("uvx", "superresearch-agent", "connect", *(extra_args or []))
    )
    try:
        r = subprocess.run(["wsl.exe", "-d", distro, "--", "bash", "-lc", inner])
    except (OSError, subprocess.SubprocessError):
        return 1
    return r.returncode


# ── install / uninstall ──────────────────────────────────────────────────────

def install(runtime: str, *, dest: Path | None = None, home: Path | None = None) -> Path:
    """Copy the skill bundle into ``runtime``'s skills dir; return the dest path.

    Overwrites an existing install (idempotent re-connect). ``dest`` forces an
    explicit target dir (tests / power users); ``home`` selects the base (a WSL
    UNC home for a WSL install); otherwise the runtime's standard path under the
    current user's home is used.
    """
    if runtime not in RUNTIMES:
        raise ValueError(f"unknown runtime: {runtime}")
    src = skill_src_dir()
    target = dest or runtime_dest(runtime, home)
    if dest is None:
        # ENFORCE dir-leaf == frontmatter name (see the RUNTIMES invariant): the
        # gateway loads skills by directory name, so a drifted edit to either
        # side must fail the install loudly, not produce an unloadable skill.
        fm_name = _frontmatter_name(src / "SKILL.md")
        if fm_name and target.name != fm_name:
            raise RuntimeError(
                f"skill dir leaf {target.name!r} != SKILL.md frontmatter name {fm_name!r} "
                "— the runtime resolves skills by directory name, so these must match"
            )
    scripts = target / "scripts"
    # Mirror the bundle: prune the scripts dir first so a file dropped from the
    # bundle doesn't linger in an existing install on re-connect. (Bounded to the
    # scripts/ subdir we own — never the whole target.)
    if scripts.exists():
        shutil.rmtree(scripts)
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "SKILL.md", target / "SKILL.md")
    for f in (src / "scripts").glob("*.py"):
        shutil.copy2(f, scripts / f.name)
    _normalize_modes(target)
    if dest is None:
        # Upgrade hygiene: a pre-rename install at a legacy leaf (sibling dir)
        # would advertise the same skill name twice — prune it.
        _prune_legacy_installs(target.parent)
    # Standard-path installs only (dest=None): a custom dest is a test/power-user
    # location, not the runtime's HERMES_HOME, so the cron script doesn't belong
    # there (and we must never write to the real ~/.hermes during a dest test).
    # Only a runtime whose /sr skill can arm a chat cron needs the watchdog script.
    if PROFILES[runtime].has_chat_armable_scheduler and dest is None:
        _install_stream_script(home)
    return target


def _frontmatter_name(skill_md: Path) -> str | None:
    """The frontmatter ``name:`` of a SKILL.md (None if unreadable/absent)."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^name:\s*(\S+)\s*$", text[:500], re.MULTILINE)
    return m.group(1) if m else None


def _prune_legacy_installs(parent: Path) -> None:
    """Remove pre-rename copies of OUR skill under ``parent`` (best-effort).
    Only runs for standard-path installs, where a legacy-named sibling can only
    be our own previous install — so the name alone is sufficient (a half-broken
    old copy without scripts/sr.py must go too, or it keeps advertising /sr)."""
    for leaf in _LEGACY_LEAVES:
        stale = parent / leaf
        try:
            if stale.is_dir():
                shutil.rmtree(stale)
        except OSError:
            pass


# The streaming watchdog (sr_attention_poll.py) runs as a Hermes `no_agent` cron
# job the /sr skill arms via the gateway's `cronjob` tool — which requires the
# script under HERMES_HOME/scripts/ (it validates containment there, rejecting the
# bundle path). Mirror the bundled copy into that dir so the skill can arm the job
# by filename. Gated on RuntimeProfile.has_chat_armable_scheduler (Hermes only):
# OpenClaw HAS cron (`openclaw cron …`) but it is admin/operator.admin-gated and
# runs in the gateway process — NOT as an agent exec call (issue #66142) — so the
# /sr skill can't arm it from chat the Hermes way, hence no per-chat watchdog there.
_STREAM_SCRIPT = "sr_attention_poll.py"


def hermes_scripts_dir(home: Path | None = None) -> Path:
    """HERMES_HOME/scripts for the default home layout (home/.hermes)."""
    return (home or Path.home()) / ".hermes" / "scripts"


def _install_stream_script(home: Path | None) -> None:
    """Copy the streaming watchdog into HERMES_HOME/scripts/ so the /sr skill's
    cron job can run it by filename. Best-effort — never breaks the skill install
    (a WSL 9p / UNC mount can reject the write)."""
    src = skill_src_dir() / "scripts" / _STREAM_SCRIPT
    if not src.is_file():
        return
    try:
        dst_dir = hermes_scripts_dir(home)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / _STREAM_SCRIPT
        shutil.copy2(src, dst)
        try:
            dst.chmod(0o644)
        except OSError:
            pass
    except OSError:
        pass


def _uninstall_stream_script(home: Path | None) -> None:
    """Remove the streaming watchdog + its de-dup state from HERMES_HOME/scripts/
    (best-effort), PLUS every per-chat shim (sr_poll_<slug>.py) and its per-chat
    state (.sr_poll_<slug>.state.json) that `sr.py arm-stream` generated. Clearing
    the state means a later re-connect + re-arm starts from a clean silent
    baseline instead of replaying old phases."""
    scripts = hermes_scripts_dir(home)
    targets = [scripts / _STREAM_SCRIPT, scripts / ".sr_stream_state.json"]
    try:
        targets += list(scripts.glob("sr_poll_*.py"))
        targets += list(scripts.glob(".sr_poll_*.state.json"))
    except OSError:
        pass
    for p in targets:
        try:
            p.unlink()
        except OSError:
            pass


def _is_stream_job(job: object) -> bool:
    """True for any watchdog cron job we own: the shared `sr-stream` / its script,
    or a per-chat `sr-stream-<slug>` job / its generated `sr_poll_<slug>.py` shim."""
    if not isinstance(job, dict):
        return False
    name = job.get("name") or ""
    script = job.get("script") or ""
    return (name == "sr-stream" or name.startswith("sr-stream-")
            or script == _STREAM_SCRIPT or script.startswith("sr_poll_"))


def _stream_jobs_present(jobs_file: Path) -> bool | None:
    """Whether jobs.json currently holds any watchdog job. None when it can't be
    read (missing handled by the caller). Used to CONFIRM a removal actually
    stuck, since the gateway reads jobs.json fresh each tick but could clobber a
    host-side edit with its own concurrent save."""
    try:
        data = json.loads(jobs_file.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        return None
    return any(_is_stream_job(j) for j in jobs)


def _remove_stream_cron(home: Path | None) -> bool:
    """Remove the watchdog cron jobs from the runtime's cron/jobs.json so they
    stop firing (and erroring on the now-removed scripts) after disconnect —
    both the shared `sr-stream` job and every per-chat `sr-stream-<slug>` job.
    The cron job is a GATEWAY artifact the agent arms via the cronjob tool; a
    host-side disconnect can't reach the gateway API, so we edit jobs.json
    directly. Best-effort + atomic (temp + replace); preserves every other job.
    jobs.json shape: {"jobs": [ {name, script, …}, … ], …}.

    Returns True when, AFTER this call, jobs.json is confirmed free of watchdog
    jobs (so the caller may safely delete the watchdog script). Returns False
    when a watchdog job might still remain — jobs.json is unreadable / oddly
    shaped, the write failed, or a concurrent gateway save clobbered our edit. In
    that case the caller MUST KEEP the script: a surviving job then runs a script
    that simply exits silently (the bridge is down post-disconnect), instead of
    the scheduler erroring "Script not found" into chat every tick. The leftover
    job is swept on the next disconnect or by `/sr logout` (gateway-side)."""
    jobs_file = (home or Path.home()) / ".hermes" / "cron" / "jobs.json"
    if not jobs_file.is_file():
        return True  # no jobs file → nothing references the watchdog script
    present = _stream_jobs_present(jobs_file)
    if present is None:
        return False  # can't read/parse → can't confirm; keep the script to be safe
    if not present:
        return True  # already clean
    try:
        data = json.loads(jobs_file.read_text("utf-8"))
        data["jobs"] = [j for j in data.get("jobs", []) if not _is_stream_job(j)]
        tmp = jobs_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), "utf-8")
        os.replace(tmp, jobs_file)
    except (OSError, ValueError):
        return False
    # Confirm the removal stuck (a racing gateway save could have re-added it).
    return _stream_jobs_present(jobs_file) is False


def _normalize_modes(target: Path) -> None:
    """Best-effort 0644 on the copied skill files. copy2 carries the SOURCE mode
    (Windows ACL bits) onto POSIX/WSL, which can leave odd permissions on a
    multi-user host; normalize to plain readable files (no +x — sr.py runs via
    `python`). Never raises (a WSL 9p / UNC mount can reject chmod)."""
    for p in (target / "SKILL.md", *(target / "scripts").glob("*")):
        try:
            p.chmod(0o644)
        except OSError:
            pass


# The skill dir leaf — both runtimes install to a dir named after the SKILL.md
# frontmatter name (the gateway loads by dir name). A resolved uninstall target
# should end in this (or a legacy leaf). Guards a mistyped --dest.
_SKILL_LEAF = "sr"


def uninstall(runtime: str, *, dest: Path | None = None, home: Path | None = None) -> bool:
    """Remove the skill bundle from ``runtime``'s skills dir (inverse of install).

    Idempotent — returns True if a skill dir was removed, False otherwise. Bounded
    to the skill dir we own: it only rmtrees a target whose leaf is ours (current
    or legacy name) OR that VERIFIES as our bundle (SKILL.md + scripts/sr.py), so
    a mistyped ``--dest`` pointing at an unrelated dir is refused, never deleted.
    Also sweeps pre-rename legacy installs at the standard path. Used by
    `agent disconnect` (the only full teardown).
    """
    if runtime not in RUNTIMES:
        raise ValueError(f"unknown runtime: {runtime}")
    if PROFILES[runtime].has_chat_armable_scheduler and dest is None:
        # Remove the gateway cron JOB(S) FIRST, then the script — and only delete
        # the script if the job removal is CONFIRMED (jobs.json free of watchdog
        # jobs). A job-without-script is exactly what spams "Script not found"
        # every tick, so if removal can't be confirmed we KEEP the script: any
        # surviving job then runs it and it exits silently (bridge is down), and
        # the job is swept next disconnect / by `/sr logout`. Ordering matters —
        # the old order (script first) left a window where a still-armed job hit
        # a missing script.
        if _remove_stream_cron(home):
            _uninstall_stream_script(home)  # confirmed jobless → safe to remove + clear state
    target = dest or runtime_dest(runtime, home)
    removed = False
    own_leaves = (_SKILL_LEAF, *_LEGACY_LEAVES)
    if target.exists() and (target.name in own_leaves or verify(target)):
        shutil.rmtree(target)
        removed = True
    if dest is None:
        # A pre-rename install may still sit at a legacy leaf — remove it too so
        # disconnect never strands an older copy that keeps advertising /sr.
        # (Standard path only: a legacy-named sibling there is ours by construction.)
        for leaf in _LEGACY_LEAVES:
            stale = target.parent / leaf
            if stale.is_dir():
                shutil.rmtree(stale)
                removed = True
    return removed


def verify(target: Path) -> bool:
    """The install landed: SKILL.md + scripts/sr.py both present."""
    return (target / "SKILL.md").is_file() and (target / "scripts" / "sr.py").is_file()
