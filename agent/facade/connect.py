r"""`agent connect` — install the Super Research skill into a chat runtime.

Copies the bundled skill (``facade/skill/`` — SKILL.md + scripts/sr.py) into the
runtime's skills directory. Both Hermes and OpenClaw use Anthropic Agent-Skills,
so one bundle serves both; only the install path differs.

The runtime usually lives in **WSL** while the backend (and this bridge) run on
**Windows**, so detection looks in two places:
  • Windows home    — ~/.hermes, ~/.openclaw
  • WSL distro home — \\wsl.localhost\<distro>\home\<user>\.hermes|.openclaw
A WSL install reaches the Windows bridge over loopback only when WSL "mirrored
networking" is on (see ``mirrored_networking_enabled``); `agent connect` /
`agent doctor` surface that prerequisite.

Pure file-copy + path logic, no network — the bundle is a thin client that calls
the already-running bridge at runtime. Install paths are overridable (``home`` /
``dest``) so this is unit-testable without touching the real runtime dirs.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# runtime → skills dir, relative to the user's home (same shape on Windows & WSL).
#
# HARD INVARIANT: the dir LEAF must equal the SKILL.md frontmatter `name:`
# ("sr"). The gateway's skills LISTING advertises the frontmatter name, but its
# skill_view/loader resolves by DIRECTORY NAME ONLY — a mismatch makes the
# advertised skill unloadable ("Skill 'sr' not found") and the model then tries
# to perform the research itself in-chat (the endless-typing failure, 2026-06-11
# E2E). install() enforces this at runtime; test_connect pins it.
RUNTIMES: dict[str, Path] = {
    "openclaw": Path(".openclaw") / "workspace" / "skills" / "sr",
    "hermes": Path(".hermes") / "skills" / "research" / "sr",
}

# Prior install leaves (pre-rename). install() prunes a stale sibling from these
# on re-connect and uninstall() sweeps them too, so an upgrade never leaves two
# copies of the skill advertising the same name.
_LEGACY_LEAVES = ("super-research",)

# Display metadata for the branded picker. rgb tints the NAME (and any vector
# glyph) so each runtime reads as a colored brand mark matching its symbol's hue:
#   • OpenClaw — 🦞 (emoji, native red) + RED glowing name
#   • Hermes   — ⚚ staff-of-Hermes glyph tinted gold #E0A33A + GOLD glowing name
RUNTIME_META: dict[str, dict] = {
    "openclaw": {"label": "OpenClaw", "icon": "🦞", "rgb": (231, 76, 60)},
    "hermes": {"label": "Hermes", "icon": "⚚", "rgb": (224, 163, 58)},
}

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


# ── WSL mirrored-networking prerequisite ────────────────────────────────────

def networking_mode(text: str) -> str | None:
    """Parse ``[wsl2] networkingMode`` from a .wslconfig body (case-insensitive).

    Returns the lower-cased value (e.g. "mirrored", "nat") or None if unset."""
    in_wsl2 = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            in_wsl2 = line[1:-1].strip().lower() == "wsl2"
            continue
        if in_wsl2 and "=" in line:
            key, _, val = line.partition("=")
            if key.strip().lower() == "networkingmode":
                # .wslconfig values are conventionally unquoted, but tolerate a
                # quoted value rather than false-negative on it.
                return val.strip().strip("'\"").lower()
    return None


def wslconfig_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".wslconfig"


def mirrored_networking_enabled(home: Path | None = None) -> bool | None:
    """True/False if .wslconfig sets networkingMode; None if there's no .wslconfig
    (so callers can distinguish "explicitly NAT" from "never configured")."""
    p = wslconfig_path(home)
    if not p.exists():
        return None
    try:
        # utf-8-sig strips a leading BOM — Notepad (the likeliest editor for
        # %USERPROFILE%\.wslconfig) writes one by default, which would otherwise
        # break the "[wsl2]" section match and yield a false "not mirrored".
        return networking_mode(p.read_text(encoding="utf-8-sig", errors="ignore")) == "mirrored"
    except OSError:
        return None


def enable_mirrored_networking(home: Path | None = None, *, mode: str = "mirrored") -> tuple[bool, Path]:
    """Idempotently set ``[wsl2] networkingMode=<mode>`` in .wslconfig.

    Surgical + non-destructive: an existing ``[wsl2]`` section keeps its other
    keys (memory/swap/…) and comments; only the networkingMode line is added or
    rewritten. With no ``[wsl2]`` section a new one is appended; with no file at
    all one is created. Returns ``(changed, path)`` — ``changed`` is False when
    the value was already ``<mode>`` (so the caller can skip the "restart WSL"
    nudge). Reads utf-8-sig (BOM-tolerant — see ``mirrored_networking_enabled``)
    and writes plain utf-8.
    """
    p = wslconfig_path(home)
    try:
        text = p.read_text(encoding="utf-8-sig", errors="ignore") if p.exists() else ""
    except OSError:
        text = ""
    if networking_mode(text) == mode:
        return (False, p)

    out: list[str] = []
    in_wsl2 = False
    wrote = False
    saw_wsl2 = False
    line = f"networkingMode={mode}"
    for raw in text.splitlines():
        stripped = raw.split("#", 1)[0].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            # Leaving a [wsl2] block we never wrote into → drop the key in first.
            if in_wsl2 and not wrote:
                out.append(line)
                wrote = True
            in_wsl2 = stripped[1:-1].strip().lower() == "wsl2"
            saw_wsl2 = saw_wsl2 or in_wsl2
            out.append(raw)
            continue
        if in_wsl2 and not wrote and "=" in stripped and \
                stripped.split("=", 1)[0].strip().lower() == "networkingmode":
            out.append(line)   # rewrite an existing (e.g. nat) value
            wrote = True
            continue
        out.append(raw)
    if in_wsl2 and not wrote:        # file ended inside [wsl2]
        out.append(line)
        wrote = True
    if not saw_wsl2:                 # no [wsl2] anywhere → append a fresh section
        if out and out[-1].strip():
            out.append("")
        out.extend(["[wsl2]", line])

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return (True, p)


def wsl_shutdown() -> tuple[bool, str]:
    """Run ``wsl --shutdown`` (Windows only) so a networkingMode change takes
    effect. Returns ``(ok, message)``; ok is False off-Windows or on failure."""
    if sys.platform != "win32":
        return (False, "Windows-only")
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        r = subprocess.run(["wsl.exe", "--shutdown"], capture_output=True,
                           timeout=60, creationflags=no_window)
    except (OSError, subprocess.SubprocessError) as e:
        return (False, str(e))
    if r.returncode == 0:
        return (True, "")
    err = (r.stderr or b"").decode("utf-16-le", errors="ignore").strip()
    return (False, err or f"exit {r.returncode}")


# ── mirrored-networking port-collision guard ─────────────────────────────────
# Mirrored networking SHARES localhost between Windows and WSL, so a Windows
# process holding a port shadows the SAME port inside WSL — that is how a stray
# Windows :3000 dev server can knock out a WSL chat bridge (the #225 WhatsApp
# break). These are the ports dev servers / chat-runtime services most often use;
# `connect` flags any that Windows is already holding before it enables mirrored.
COMMON_SHARED_PORTS: tuple[int, ...] = (
    3000, 3001, 3737, 4000, 5000, 5173, 8000, 8080, 8888, 9000,
)


def _parse_listening_ports(netstat_text: str, wanted: set[int]) -> dict[int, str]:
    """Pure parser for `netstat -ano` output → {port: pid} for LISTENING TCP rows
    whose local port is in `wanted`. First holder per port wins."""
    found: dict[int, str] = {}
    for line in netstat_text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
            try:
                port = int(parts[1].rsplit(":", 1)[1])  # 127.0.0.1:3000 / [::]:3000
            except (ValueError, IndexError):
                continue
            if port in wanted and port not in found:
                found[port] = parts[4]
    return found


def windows_port_owners(ports: tuple[int, ...] = COMMON_SHARED_PORTS) -> dict[int, str]:
    """Which of `ports` a Windows process is LISTENING on → {port: pid}. Advisory
    + best-effort: returns {} off-Windows or on any failure, so it can NEVER break
    the connect flow. Used to warn that mirrored networking will let these Windows
    ports shadow the same port inside WSL."""
    if sys.platform != "win32":
        return {}
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        r = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=10, creationflags=no_window,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    return _parse_listening_ports(r.stdout or "", set(ports))


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
    if runtime == "hermes" and dest is None:
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
# by filename. Hermes-only: OpenClaw has no equivalent cron scheduler.
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
    """Remove the streaming watchdog from HERMES_HOME/scripts/ (best-effort)."""
    try:
        (hermes_scripts_dir(home) / _STREAM_SCRIPT).unlink()
    except OSError:
        pass


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
    if runtime == "hermes" and dest is None:
        _uninstall_stream_script(home)  # best-effort; the inert script is harmless if left
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
