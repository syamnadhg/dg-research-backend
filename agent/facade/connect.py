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
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# runtime → skills dir, relative to the user's home (same shape on Windows & WSL).
RUNTIMES: dict[str, Path] = {
    "openclaw": Path(".openclaw") / "workspace" / "skills" / "super-research",
    "hermes": Path(".hermes") / "skills" / "research" / "super-research",
}

# Display metadata for the branded picker. icon = native-color glyph; rgb tints
# the NAME so both runtimes read as colored brand marks (the user's parity ask):
#   • OpenClaw — 🦞 (native orange) + orange name
#   • Hermes   — ⚚ staff-of-Hermes, gold #E0A33A (default until a brand hex lands)
RUNTIME_META: dict[str, dict] = {
    "openclaw": {"label": "OpenClaw", "icon": "🦞", "rgb": (232, 115, 46)},
    "hermes": {"label": "Hermes", "icon": "⚚", "rgb": (224, 163, 58)},
}

# Pin/override the WSL distro list (skips `wsl -l -q`); comma-separated.
WSL_DISTRO_ENV = "SUPER_AGENT_WSL_DISTRO"


@dataclass(frozen=True)
class Target:
    """A concrete place to install the skill: a runtime + the home that holds it."""

    runtime: str           # "hermes" | "openclaw"
    location: str          # "windows" | "wsl"
    home: Path             # the home dir containing .hermes / .openclaw
    distro: str | None = None  # WSL distro name (None on Windows)

    @property
    def dest(self) -> Path:
        return self.home / RUNTIMES[self.runtime]

    @property
    def where(self) -> str:
        return f"WSL · {self.distro}" if self.location == "wsl" else "Windows"


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
        Target(rt, "windows", base)
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
    return target


def uninstall(runtime: str, *, dest: Path | None = None, home: Path | None = None) -> bool:
    """Remove the skill bundle from ``runtime``'s skills dir (inverse of install).

    Idempotent — returns True if a skill dir was removed, False if nothing was
    there. Bounded to the ``super-research`` skill dir we own (the same path
    install() populates) — never a parent/shared dir. Used by `agent disconnect`
    and by the bridge's revoke-consult (app Revoke = sign out + uninstall).
    """
    if runtime not in RUNTIMES:
        raise ValueError(f"unknown runtime: {runtime}")
    target = dest or runtime_dest(runtime, home)
    if target.exists():
        shutil.rmtree(target)
        return True
    return False


def verify(target: Path) -> bool:
    """The install landed: SKILL.md + scripts/sr.py both present."""
    return (target / "SKILL.md").is_file() and (target / "scripts" / "sr.py").is_file()
