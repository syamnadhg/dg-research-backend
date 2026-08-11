"""Mutation harness for the two review findings that turned out to be real.

The triage of this PR's 14 review findings had these two down as declinable. They
were not — re-checking each one against the tree found both reachable, so they are
fixed here and these mutants prove the tests would have noticed the fix being wrong.

Half of them mutate in the OVER-correction direction, because both fixes have an
obvious too-far version: "empty latest means always restart" puts a Restart prompt
on screen after every successful offline update, and dropping `--force` turns the
durable install into a no-op that reports success.

Safety, learned from an earlier harness on this repo that adopted a mutant as its
own baseline: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/review_should_fix_0811_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
SELFUPDATE = "agent/facade/selfupdate.py"

OUTCOME = "tests/test_update_outcome_reporting.py"
DURABLE = "agent/tests/test_durable_install.py"

# (id, direction, why, file, [(from, to)], test_target)
MUTANTS = [
    # ── Finding 3: unknown PyPI latest suppressed the needs-restart verdict ──
    ("U1", "under", "target no longer falls back to the on-disk version",
     RESEARCH, [("        target = want or running", "        target = want")], OUTCOME),
    ("U2", "under", "success check re-gated on a known latest",
     RESEARCH, [("        if target and served == target:", "        if want and served == want:")], OUTCOME),
    ("U3", "under", "drift branch re-gated on a known latest",
     RESEARCH, [("        if target and served and served != target:",
                 "        if want and served and served != want:")], OUTCOME),
    ("U4", "under", "drift branch reports the served version as the target",
     RESEARCH, [('            return {"state": "installed", "current": served, "latest": target,',
                 '            return {"state": "installed", "current": served, "latest": served,')], OUTCOME),
    ("U5", "over", "an unknown served version now counts as owing a restart",
     RESEARCH, [("        if target and served and served != target:",
                 "        if target and served != target:")], OUTCOME),
    ("U6", "over", "every unknown latest demands a restart",
     RESEARCH, [('        return {"state": "installed", "current": served or running,\n'
                 '                "latest": target, "needsRestart": False, "reason": ""}',
                 '        return {"state": "installed", "current": served or running,\n'
                 '                "latest": target, "needsRestart": True, "reason": ""}')], OUTCOME),

    # ── Finding 1: the durable install tore down before it had a replacement ──
    ("D1", "under", "the destructive uninstall is back",
     SELFUPDATE, [("    try:\n        r = subprocess.run([*pipx, \"install\", \"--force\", _agent_floor_spec()],",
                   "    if autostart.durable_venv() is not None:\n"
                   "        try:\n"
                   "            subprocess.run([*pipx, \"uninstall\", AGENT_PKG], capture_output=True,\n"
                   "                           text=True, timeout=600)\n"
                   "        except Exception:\n"
                   "            pass\n"
                   "    try:\n        r = subprocess.run([*pipx, \"install\", \"--force\", _agent_floor_spec()],")], DURABLE),
    ("D2", "over", "--force dropped, so the install is a no-op reporting success",
     SELFUPDATE, [('        r = subprocess.run([*pipx, "install", "--force", _agent_floor_spec()],',
                   '        r = subprocess.run([*pipx, "install", _agent_floor_spec()],')], DURABLE),
]


def sh(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "agent", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests(target: str) -> bool:
    """True when the suite PASSES."""
    if target.startswith("agent/"):
        return sh([sys.executable, "-m", "pytest", target[len("agent/"):], "-q"],
                  cwd=ROOT / "agent").returncode == 0
    return sh([sys.executable, "-m", "pytest", target, "-q"]).returncode == 0


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    for target in {m[5] for m in MUTANTS}:
        print(f"baseline {target}… ", end="", flush=True)
        if not run_tests(target):
            print("RED. Nothing below would mean anything.")
            return 2
        print("green")

    survivors = []
    for mid, direction, why, rel, edits, target in MUTANTS:
        path = ROOT / rel
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found in {rel}: {frm[:80]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests(target)
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, why))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
