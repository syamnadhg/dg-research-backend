#!/usr/bin/env python3
"""Bump the Super Research AGENT version everywhere it must move together.

The agent version lives in THREE files that must never drift:

  1. ``agent/pyproject.toml``              ``[project] version``   — the PUBLISHED version
  2. ``agent/facade/skill/scripts/sr.py``  ``_SKILL_BUILD``        — the "which copy am I" stamp
  3. ``agent/facade/__init__.py``          ``__version__`` fallback — used only when the
     installed package metadata is unavailable (i.e. a source checkout)

...plus the byte-identical hosted twin the web app serves
(``research-app/web/public/.well-known/skills/sr/scripts/sr.py``), refreshed by the
FE's own ``scripts/sync-agent-skill.mjs``.

Hand-editing four places is exactly how they drift — and how the same bump got done
twice from two machines. One command instead::

    python tools/bump_agent_version.py 0.1.29        # bump all three + sync the twin
    python tools/bump_agent_version.py --check       # verify lockstep (exit 1 on drift)
    python tools/bump_agent_version.py 0.1.29 --no-sync   # skip the FE twin sync

WHY ``_SKILL_BUILD`` CANNOT JUST READ THE PACKAGE METADATA
----------------------------------------------------------
It is deliberately a FROZEN literal, not a computed value. The chat runtime executes
its own COPY of ``sr.py`` (``HERMES_HOME/scripts``), while the bridge runs the
INSTALLED package. ``_SKILL_BUILD`` records the vintage of *that copy* so
``cmd_version`` can flag a stale copied script — the live 2026-07-02 failure where a
stale copy predating the podcast MEDIA fix silently kept sending bare audio paths.
If it resolved ``importlib.metadata.version("superresearch-agent")`` at runtime it
would always report the INSTALLED version, the comparison becomes a tautology, and
drift is never detected. So the literal stays; this script removes the hand-edit.

``agent/facade/__init__.py`` is different: it DOES resolve the metadata first and only
falls back to its literal in a source checkout — so that literal is a backstop, not a
staleness probe, and is bumped here purely to keep a source run honest.

Offline, deterministic, idempotent. Preserves each file's existing line endings.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# (label, relative path, compiled pattern with ONE capturing group around the version)
# Each pattern is anchored so it can only ever match the intended declaration.
_TARGETS = (
    ("pyproject", Path("agent/pyproject.toml"),
     re.compile(r'^(version\s*=\s*")([^"]+)(")', re.M)),
    ("_SKILL_BUILD", Path("agent/facade/skill/scripts/sr.py"),
     re.compile(r'^(_SKILL_BUILD\s*=\s*")([^"]+)(")', re.M)),
    # Two fallback literals; the metadata-backed assignment on the line above them is
    # `__version__ = _pkg_version(...)` (unquoted) so this pattern can't touch it.
    ("__init__ fallback", Path("agent/facade/__init__.py"),
     re.compile(r'^(\s*__version__\s*=\s*")([^"]+)(")', re.M)),
)

# Permissive but real: N(.N)* with an optional PEP 440-ish suffix. Rejects the
# typos that actually happen ("v0.1.9", "0,1,9", "0.1.9 ").
_VERSION_RE = re.compile(r"^\d+(\.\d+)*([a-zA-Z0-9.\-]*)$")


def valid_version(v: str) -> bool:
    return bool(v) and v == v.strip() and bool(_VERSION_RE.match(v))


def _read(path: Path) -> tuple[str, str]:
    """(text, newline) with the file's ORIGINAL line endings preserved."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    return text, nl


def _write(path: Path, text: str) -> None:
    # newline="" → write the string verbatim, so whatever endings _read saw survive.
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def read_versions(root: Path = _REPO_ROOT) -> dict[str, list[str]]:
    """{label: [every version literal found]} — a label with >1 entry (the
    __init__ fallbacks) must be internally consistent too."""
    found: dict[str, list[str]] = {}
    for label, rel, pat in _TARGETS:
        path = root / rel
        if not path.exists():
            found[label] = []
            continue
        text, _ = _read(path)
        found[label] = [m.group(2) for m in pat.finditer(text)]
    return found


def check_lockstep(root: Path = _REPO_ROOT) -> tuple[bool, list[str]]:
    """(ok, messages). Verifies every declaration carries the SAME version."""
    found = read_versions(root)
    msgs: list[str] = []
    missing = [lbl for lbl, vs in found.items() if not vs]
    if missing:
        return False, [f"no version declaration found for: {', '.join(missing)}"]
    everything = {v for vs in found.values() for v in vs}
    for label, vs in found.items():
        msgs.append(f"  {label:<18} {', '.join(vs)}")
    if len(everything) != 1:
        return False, ["agent version DRIFT — these must all match:", *msgs]
    return True, [f"agent version lockstep OK: {everything.pop()}", *msgs]


def bump(new_version: str, root: Path = _REPO_ROOT) -> list[str]:
    """Rewrite every declaration to `new_version`. Returns per-file change notes.
    Idempotent: a file already at the target is reported as unchanged."""
    if not valid_version(new_version):
        raise ValueError(f"not a valid version string: {new_version!r}")
    notes: list[str] = []
    for label, rel, pat in _TARGETS:
        path = root / rel
        if not path.exists():
            raise FileNotFoundError(f"missing {rel} (run from the backend repo root)")
        text, _nl = _read(path)
        olds = [m.group(2) for m in pat.finditer(text)]
        if not olds:
            raise ValueError(f"no version declaration matched in {rel}")
        new_text = pat.sub(lambda m: f"{m.group(1)}{new_version}{m.group(3)}", text)
        if new_text == text:
            notes.append(f"  {label:<18} already {new_version} (unchanged)")
            continue
        _write(path, new_text)
        notes.append(f"  {label:<18} {' ,'.join(sorted(set(olds)))} -> {new_version}"
                     f"  ({rel.as_posix()})")
    return notes


def _web_root(root: Path) -> Path:
    """The sibling web checkout that hosts the byte-identical skill twin."""
    override = os.environ.get("SR_WEB_ROOT")
    if override:
        return Path(override)
    return root.parent / "research-app" / "web"


def sync_fe_twin(root: Path = _REPO_ROOT) -> tuple[bool, str]:
    """Refresh the hosted skill twin via the FE's own sync script. Best-effort:
    a missing web checkout or missing node is reported, never fatal — the bump
    itself already succeeded and the twin can be synced later."""
    web = _web_root(root)
    script = web / "scripts" / "sync-agent-skill.mjs"
    if not script.exists():
        return False, f"FE sync skipped — no {script} (set SR_WEB_ROOT to the web root)"
    node = shutil.which("node")
    if not node:
        return False, "FE sync skipped — `node` not on PATH"
    try:
        # Decode as UTF-8 explicitly: the sync script emits check-marks and
        # em-dashes, and the Windows locale (cp1252) would mojibake them.
        proc = subprocess.run([node, str(script)], cwd=str(web),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"FE sync failed to run: {e}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    tail = out[-1] if out else "(no output)"
    if proc.returncode != 0:
        return False, f"FE sync exited {proc.returncode}: {tail}"
    return True, f"FE twin synced: {tail}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="bump_agent_version.py",
        description="Bump the agent version in pyproject + _SKILL_BUILD + __init__, "
                    "then re-sync the hosted skill twin.")
    ap.add_argument("version", nargs="?", help="new version, e.g. 0.1.29")
    ap.add_argument("--check", action="store_true",
                    help="verify all declarations agree; exit 1 on drift")
    ap.add_argument("--no-sync", action="store_true",
                    help="skip the FE hosted-twin sync")
    args = ap.parse_args(argv)

    # Windows consoles default to cp1252, which cannot encode check/warn glyphs
    # or em-dashes -- a release tool must never die on its own status line. The
    # status MARKERS are plain ASCII (below); this hardens the prose too, plus
    # anything a synced script echoes back. (This is a real crash, not a theory.)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if args.check:
        ok, msgs = check_lockstep()
        print("\n".join(msgs))
        return 0 if ok else 1

    if not args.version:
        ap.error("give a version to bump to, or --check")
    if not valid_version(args.version):
        print(f"ERROR: not a valid version string: {args.version!r}", file=sys.stderr)
        return 2

    try:
        notes = bump(args.version)
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"agent version -> {args.version}")
    print("\n".join(notes))

    if not args.no_sync:
        ok, msg = sync_fe_twin()
        print(("OK:   " if ok else "WARN: ") + msg)

    ok, msgs = check_lockstep()
    print("\n".join(msgs))
    if not ok:
        return 1
    print("\nNext: commit agent/ (+ the web twin if it changed), rebuild the agent "
          "wheel (`cd agent && uv build --out-dir dist`), then publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
