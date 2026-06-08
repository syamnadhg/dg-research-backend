"""`agent connect` — install the Super Research skill into a chat runtime.

Copies the bundled skill (``facade/skill/`` — SKILL.md + scripts/sr.py) into the
runtime's skills directory. Both Hermes and OpenClaw use Anthropic Agent-Skills,
so one bundle serves both; only the install path differs.

Pure file-copy + path logic, no network — the bundle is a thin client that calls
the already-running bridge at runtime. Install paths are overridable (``home`` /
``dest``) so this is unit-testable without touching the real runtime dirs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# runtime → skills dir, relative to the user's home.
RUNTIMES: dict[str, Path] = {
    "hermes": Path(".hermes") / "skills" / "research" / "super-research",
    "openclaw": Path(".openclaw") / "workspace" / "skills" / "super-research",
}


def skill_src_dir() -> Path:
    """The bundled skill source shipped inside the package."""
    return Path(__file__).parent / "skill"


def runtime_dest(runtime: str, home: Path | None = None) -> Path:
    base = home or Path.home()
    return base / RUNTIMES[runtime]


def detect_runtimes(home: Path | None = None) -> list[str]:
    """Runtimes whose top-level dir (~/.hermes, ~/.openclaw) exists on this host."""
    base = home or Path.home()
    return [rt for rt, rel in RUNTIMES.items() if (base / rel.parts[0]).exists()]


def install(runtime: str, *, dest: Path | None = None, home: Path | None = None) -> Path:
    """Copy the skill bundle into ``runtime``'s skills dir; return the dest path.

    Overwrites an existing install (idempotent re-connect). ``dest`` forces an
    explicit target dir (tests / power users); otherwise the runtime's standard
    path under ``home`` is used.
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
