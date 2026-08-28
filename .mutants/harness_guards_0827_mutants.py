"""Mutation harness for the mutation harness's own guards.

⛔⛔ THE CIRCULARITY IS THE POINT. On 2026-08-27 `review_blockers_0813_mutants.py`
reported **35/36 killed** with M6 as a survivor. M6 is killed by three tests. The
harness had run without `node`, 68 tests skipped, pytest exited 0, and the
harness read that as "nothing caught it" — then confirmed it twice more against
the same broken environment.

So the guards added that day are load-bearing in a way ordinary code is not: if
THEY are wrong, every future score in this repo is wrong and nothing says so.
The over-corrections matter as much as the under- ones — a guard that refuses
every run is a harness nobody can use, which ends with someone deleting it.

    .venv/bin/python .mutants/harness_guards_0827_mutants.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ".mutants/review_blockers_0813_mutants.py"
SUITES = "tests/test_mutation_harness_guards_0827.py"

ENV = {**os.environ,
       "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": os.pathsep.join(
           [str(ROOT)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}

SURVIVOR_CONFIRMATIONS = 2
SKIP_RE = re.compile(r"(\d+)\s+skipped")

# (id, direction, why, [(from, to), ...])
MUTANTS = [
    # ───────────────────────── skipped_count ─────────────────────────
    ("G1", "under", "⭐ the guard goes blind — every run reports zero skips, "
     "which is the exact 35/36 lie restored",
     [("    hits = SKIP_RE.findall(pytest_output or \"\")\n"
       "    return int(hits[-1]) if hits else 0",
       "    hits = SKIP_RE.findall(pytest_output or \"\")\n"
       "    return 0")]),
    ("G2", "under", "the FIRST match wins — an early per-file '1 skipped' is "
     "read as the total, so 68 skips report as 1",
     [("    return int(hits[-1]) if hits else 0",
       "    return int(hits[0]) if hits else 0")]),
    ("G3", "under", "presence, not count — cannot tell 1 skip from 68, so the "
     "message the operator reads names the wrong scale",
     [("    return int(hits[-1]) if hits else 0",
       "    return (1 if hits else 0)")]),
    ("G4", "under", "the regex reads 'passed' instead of 'skipped' — a healthy "
     "run is refused and a skipping one sails through",
     [('SKIP_RE = re.compile(r"(\\d+)\\s+skipped")',
       'SKIP_RE = re.compile(r"(\\d+)\\s+passed")')]),
    ("G5", "over", "⛔ the whitespace class is dropped, so 'in 17.48s' style "
     "summaries stop matching and skips go unseen",
     [('SKIP_RE = re.compile(r"(\\d+)\\s+skipped")',
       'SKIP_RE = re.compile(r"(\\d+)skipped")')]),

    ("G16", "under", "⭐⭐ the summary-line anchor is dropped, so the detector "
     "reads assertion diffs again — its own fixtures become 'skips'",
     [('    for m in SUMMARY_RE.finditer(pytest_output or ""):\n'
       '        line = m.group(0)',
       '    for m in [None]:\n'
       '        line = pytest_output or ""')]),
    ("G17", "over", "⛔ no summary line is ever found, so every run reports "
     "zero skips — the gate is dead",
     [('    if line is None:\n        return 0',
       '    if True:\n        return 0')]),

    # ───────────────────────── missing_tooling ───────────────────────
    ("G6", "under", "⭐ node is no longer required — the JavaScript filter "
     "tests skip and the harness scores anyway. THE ORIGINAL DEFECT.",
     [('    return [exe for exe in ("node", "git") if shutil.which(exe) is None]',
       '    return [exe for exe in ("git",) if shutil.which(exe) is None]')]),
    ("G7", "under", "nothing is ever missing — the gate is decorative",
     [('    return [exe for exe in ("node", "git") if shutil.which(exe) is None]',
       '    return []')]),
    ("G8", "over", "⛔ every tool reports missing — the harness can never run "
     "again, and a harness nobody can run gets deleted",
     [('    return [exe for exe in ("node", "git") if shutil.which(exe) is None]',
       '    return ["node", "git"]')]),

    # ───────────────────────── run_tests ─────────────────────────────
    ("G9", "under", "run_tests always claims zero skips, so both gates below "
     "are fed a constant and can never fire",
     [("    return proc.returncode == 0, skipped_count(proc.stdout + proc.stderr)",
       "    return proc.returncode == 0, 0")]),
    ("G10", "under", "only stdout is read — pytest writing its summary to "
     "stderr would hide every skip",
     [("    return proc.returncode == 0, skipped_count(proc.stdout + proc.stderr)",
       "    return proc.returncode == 0, skipped_count(proc.stderr)")]),

    # ───────────────────────── the gates in main() ───────────────────
    ("G11", "under", "⭐ the tooling gate never fires — back to scoring "
     "without node",
     [("    absent = missing_tooling()\n    if absent:",
       "    absent = missing_tooling()\n    if False:")]),
    ("G12", "under", "⭐ the baseline skip gate never fires — a half-measured "
     "suite is scored as if whole",
     [("    if skipped:\n        print(f\"green, but {skipped} test(s) SKIPPED.",
       "    if False:\n        print(f\"green, but {skipped} test(s) SKIPPED.")]),
    ("G13", "over", "⛔ the baseline is refused whenever it is GREEN — the "
     "harness refuses exactly the runs it should accept",
     [("    if skipped:\n        print(f\"green, but {skipped} test(s) SKIPPED.",
       "    if not skipped:\n        print(f\"green, but {skipped} test(s) SKIPPED.")]),

    # ───────────────────────── the mid-run gate ──────────────────────
    ("G14", "under", "⭐⭐ a skip DURING a mutant stops being a fault — the "
     "environment can rot mid-run and print a confident SURVIVED",
     [("            if skipped:\n"
       "                raise AssertionError(f\"{skipped} test(s) skipped — verdict refused\")\n"
       "            killed = not green",
       "            if False:\n"
       "                raise AssertionError(f\"{skipped} test(s) skipped — verdict refused\")\n"
       "            killed = not green")]),
    ("G15", "under", "the CONFIRMATION re-runs stop checking skips, so a "
     "survivor claim can still be confirmed by a broken environment",
     [("                green, skipped = run_tests()\n"
       "                if skipped:\n"
       "                    raise AssertionError(f\"{skipped} test(s) skipped — verdict refused\")\n"
       "                killed = not green",
       "                green, skipped = run_tests()\n"
       "                killed = not green")]),
]


def sh(cmd, *, env=None):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env or ENV)


def purge_pycache():
    # ⛔ SCOPED TO `tests/`. An unscoped rglob walks `.venv`, which holds
    # thousands of caches — it turned a 2-second suite into a run that had to be
    # killed, and a killed harness leaves a mutant in the tree.
    for d in (ROOT / "tests").rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def tracked_dirty():
    out = sh(["git", "status", "--porcelain", "--", TARGET, "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests():
    purge_pycache()
    proc = sh([sys.executable, "-B", "-m", "pytest", *SUITES.split(), "-q",
               "-p", "no:cacheprovider"])
    hits = SKIP_RE.findall(proc.stdout + proc.stderr)
    return proc.returncode == 0, (int(hits[-1]) if hits else 0)


def main():
    if shutil.which("git") is None:
        print("git is not on PATH — refusing to run without a restore path.")
        return 2
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    ok, skipped = run_tests()
    if not ok:
        print("RED. Nothing below would mean anything.")
        return 2
    if skipped:
        print(f"green but {skipped} skipped — refusing to score (the very fault "
              f"these guards exist for).")
        return 2
    print("green")

    path = ROOT / TARGET
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if mutated.count(frm) != 1:
                    raise AssertionError(
                        f"anchor matched {mutated.count(frm)}x (must be exactly 1): {frm[:60]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            green, sk = run_tests()
            if sk:
                raise AssertionError(f"{sk} test(s) skipped — verdict refused")
            killed = not green
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                green, sk = run_tests()
                if sk:
                    raise AssertionError(f"{sk} test(s) skipped — verdict refused")
                killed = not green
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, why))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN:\n" + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
