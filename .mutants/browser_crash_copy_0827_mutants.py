"""Mutation harness for the 2026-08-27 browser-crash notice.

The sentence this replaces promised *"auto-retrying from checkpoint… The
pipeline will rebuild the browser session and resume."* Measured: the tab died at
17:21:00 and the phase reported COMPLETE at 17:21:06 with two of three agents.
Nothing was rebuilt; nothing resumed.

⛔⛔ THE OVER-CORRECTIONS ARE THE DANGEROUS HALF HERE, and they are all the same
temptation: the copy reads better if it names a culprit. It must not. We hold
"our scrapers read nothing new" and "our arbiter said it looked fine" — neither
separates a platform stall from our own blindness, and a dead tab is identical
whether the platform hung, Chrome ran out of memory, or a profile lock was lost.
B11 and B12 are each one word and each ships a guess as a fact.

    .venv/bin/python .mutants/browser_crash_copy_0827_mutants.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATED_FILES = ["research.py"]

SUITES = "tests/test_browser_crash_copy_0827.py tests/test_skip_reporting.py"

ENV = {**os.environ,
       "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": os.pathsep.join(
           [str(ROOT)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}

SURVIVOR_CONFIRMATIONS = 3
SUMMARY_RE = re.compile(r"^=*\s*(?:\d+\s+\w+(?:,\s*)?)+\s+in\s+[\d.]+s", re.M)
SKIP_RE = re.compile(r"(\d+)\s+skipped")

MUTANTS = [
    # ══════════ under: the fix stops working ══════════
    ("B1", "under",
     "⭐⭐ THE BROKEN PROMISE RETURNS — the notice says the run will rebuild and "
     "resume, which measurably does not happen",
     [('    return message, f"{body} Nothing on your side caused this; the run continued without it."',
       '    return message, "The pipeline will rebuild the browser session and resume."')]),
    ("B2", "under",
     "⭐ 'at least' is dropped, so a floor is reported as an exact age — and the "
     "arbiter can rewind the growth clock, so the true silence is LONGER",
     [('        head = f"It went quiet{where} for at least {quiet} minutes and never recovered"',
       '        head = f"It went quiet{where} for {quiet} minutes and never recovered"')]),
    ("B3", "under",
     "⛔⛔ the never-grew guard goes, so a leg that produced nothing from the "
     "start reports its whole life as silence — a true-sounding number about a "
     "thing that never began",
     [('                _crash_quiet = (int(time.time() - _crash_p["last_growth_time"])\n'
       '                                if _crash_grew and _crash_p.get("last_growth_time") else None)',
       '                _crash_quiet = (int(time.time() - _crash_p["last_growth_time"])\n'
       '                                if _crash_p.get("last_growth_time") else None)')]),
    ("B4", "under",
     "the elapsed clock is dropped at the emit site, so every crash reports no "
     "duration at all",
     [("                    elapsed_sec=_crash_elapsed,", "                    elapsed_sec=None,")]),
    ("B5", "under",
     "the recheck count stops being passed — the sentence loses 'we re-checked "
     "it N times', which is the part that says we did not give up early",
     [('                    rechecks=int(_crash_p.get("arbiter_working_resets", 0) or 0))',
       '                    rechecks=0)')]),
    ("B6", "under",
     "⭐ 'on its own page' is dropped, so the failure reads as the person's own "
     "browser again — the exact misread the old copy caused",
     [('    where = " on its own page" if named else ""', '    where = ""')]),
    ("B7", "under",
     "a zero or missing clock stops meaning 'unknown', so a crash renders "
     "'after 0 minutes'",
     [("                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0",
       "                if isinstance(v, (int, float)) and not isinstance(v, bool)")]),
    ("B8", "under",
     "booleans stop being excluded — True is an int in Python, so a truthy flag "
     "renders as '1 minutes'",
     [("                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0",
       "                if isinstance(v, (int, float)) and v > 0")]),
    ("B9", "under",
     "the one-minute floor goes, so a page that died in forty seconds reports "
     "'after 0 minutes' — a sentence that reads as a bug",
     [("        return (max(1, round(v / 60))", "        return (round(v / 60)")]),
    ("B10", "under",
     "the singular collapses — 'we re-checked it 1 times'",
     [('        if rechecks > 0:\n'
       '            head += (" — we re-checked it once before giving up" if rechecks == 1\n'
       '                     else f" — we re-checked it {rechecks} times before giving up")',
       '        if rechecks > 0:\n'
       '            head += f" — we re-checked it {rechecks} times before giving up"')]),

    # ══════════ over: the copy starts guessing ══════════
    ("B11", "over",
     "⛔⛔ IT NAMES A CAUSE IT CANNOT KNOW — 'a problem on their side' is a guess "
     "wearing a fact's clothes; nothing we hold separates a platform stall from "
     "our own scrapers going blind",
     [('    return message, f"{body} Nothing on your side caused this; the run continued without it."',
       '    return message, f"{body} This is a problem on their side; the run continued without it."')]),
    ("B12", "over",
     "⛔ an unnamed crash claims a page it cannot name — 'The page on its own "
     "page stopped responding', and a whole-browser death blamed on a platform",
     [('    where = " on its own page" if named else ""',
       '    where = " on its own page"')]),
    ("B13", "over",
     "⛔ the emitter stops delegating and hard-codes one sentence, so every "
     "clock we carried out of the pending entry is thrown away",
     [("    _msg, _details = browser_crash_copy(",
       "    _msg, _details = (lambda *a, **k: (f\"{agent} stopped responding\", \"\"))(")]),
    ("B14", "over",
     "⛔ the outcome is dropped — the person is told a page died and never told "
     "the run carried on without it, which is the only actionable half",
     [('    return message, f"{body} Nothing on your side caused this; the run continued without it."',
       '    return message, f"{body} Nothing on your side caused this."')]),
]


def sh(cmd, *, env=None):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env or ENV)


def purge_pycache():
    for d in (ROOT / "tests").rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def tracked_dirty():
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests():
    """(green, skipped). ⛔ Summary line only — a full-output scan reads the
    suite's own fixtures as skips. See the 08-27 guard note in
    `review_blockers_0813_mutants.py`."""
    purge_pycache()
    proc = sh([sys.executable, "-B", "-m", "pytest", *SUITES.split(), "-q",
               "-p", "no:cacheprovider"])
    line = None
    for m in SUMMARY_RE.finditer(proc.stdout + proc.stderr):
        line = m.group(0)
    hits = SKIP_RE.findall(line) if line else []
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
        print(f"green but {skipped} SKIPPED — refusing to score.")
        return 2
    print("green")

    path = ROOT / "research.py"
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                n = mutated.count(frm)
                if n != 1:
                    raise AssertionError(
                        f"anchor matched {n}x (must be exactly 1): {frm[:70]!r}")
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
            print(f"{mark} {mid} [{direction}] {why}{'  ⚠ FLAPPED' if flapped else ''}")
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
