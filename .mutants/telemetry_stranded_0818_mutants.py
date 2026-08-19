"""Mutation harness for "the batch a dead process was holding".

⛔⛔ MEASURED: an adopted spool file was destroyed by its first failed delivery.
Old code, nine real events in, zero out. The call site read

    _merge_back(claimed, path if ".sending." not in path.name else path)

and both arms of that ternary are `path` — so for a file adopted under its own
name, `claimed` IS `path`, and _merge_back read it, wrote it back into itself,
and unlinked what it had just written.

⭐⭐ The two conditions for total loss are the two conditions of an incident: the
owning process is dead, and delivery is failing. This system exists to report
outages and threw away its evidence during them.

⛔ THE FIRST REPRO WAS WRONG and agreed for the wrong reason — events with no `t`
are age-expired and legitimately dropped, so the file vanished on an unrelated
path. M6 below is that trap, kept as a mutant: age-expiry must stay.

    python .mutants/telemetry_stranded_0818_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "telemetry.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_telemetry_stranded_batch_0818.py"
# ⛔ The spool's existing invariants — age expiry and the owed remainder past the
# batch cap — live in the 08-18 file, and both are properties of the function
# edited here. A harness scoped to the new file alone reported them as suite gaps
# when the suite covers them perfectly well; the harness was the thing with the
# gap.
T_TM = "tests/test_telemetry_0818.py"
ALL = [T_NEW, T_TM]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 180

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    ("S1", "under", "⭐⭐ THE DEFECT ITSELF — the destination is the claimed name "
     "again, so an adopted file is merged into itself and unlinked",
     [("            _merge_back(claimed, _unclaimed_name(path))",
       "            _merge_back(claimed, path)")],
     [T_NEW]),
    ("S2", "under", "the self-merge guard is removed, so one careless call site "
     "destroys a batch again",
     [("    if claimed.resolve() == path.resolve():\n        return\n", "")],
     [T_NEW]),
    ("S3", "under", "the guard compares unresolved paths, so a symlinked or "
     "relative spool dir slips past it",
     [("    if claimed.resolve() == path.resolve():",
       "    if str(claimed) == str(path) and False:")],
     [T_NEW]),
    ("S4", "under", "the suffix stripper leaves the pid on, so recovered events "
     "land under a name the next flush treats as still claimed",
     [('    return path.with_name(re.sub(r"\\.sending\\.\\d+(?=\\.jsonl$)", "", path.name))',
       "    return path")],
     [T_NEW]),
    ("S5", "over", "⛔ the stripper eats the whole name, collapsing every spool "
     "source into one file",
     [('    return path.with_name(re.sub(r"\\.sending\\.\\d+(?=\\.jsonl$)", "", path.name))',
       '    return path.with_name("pending.jsonl")')],
     [T_NEW]),
    ("S6", "over", "⛔ age-expiry is dropped — the trap the first repro fell "
     "into. Stale events must still be discarded",
     [("            if float(record.get(\"t\", 0)) / 1000.0 < cutoff:\n                continue\n", "")],
     [T_NEW, T_TM]),
    ("S7", "under", "the owed remainder past the batch cap stops being written "
     "back, which is the loss this file was already fixed for once",
     [("            if owed:\n                _write_back(owed, path)", "            if owed:\n                pass")],
     [T_NEW, T_TM]),
    ("S8", "over", "adoption stops checking whether the owner is alive, so two "
     "processes post the same batch",
     [("    return not _pid_alive(pid)", "    return True")],
     [T_NEW]),
    ("S9", "under", "nothing is ever adopted, so a dead process's events sit on "
     "disk forever",
     [("    return not _pid_alive(pid)", "    return False")],
     [T_NEW]),
    ("S10", "under", "merge order flips, so recovered events land BEHIND ones "
     "that arrived later and the sequence reads backwards",
     [('        path.write_text(owed + newer, encoding="utf-8")',
       '        path.write_text(newer + owed, encoding="utf-8")')],
     [T_NEW]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ MEASURED 2026-08-18: a stale `__pycache__/*.pyc` served OLD bytecode
        # for a source file that had already been fixed, and the measurement
        # disagreed with the file for three rounds. In a harness that rewrites the
        # source between every run, a cached module is not a nuisance — it is a
        # kill or a survivor invented out of nothing. Three earlier waves had
        # already learned this and set the flag; it was never propagated.
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def snapshot() -> dict[str, str]:
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before: dict[str, str]) -> list[str]:
    return [f for f, text in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != text]


def main() -> int:
    before = snapshot()

    print("baseline… ", end="", flush=True)
    ok, timed_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if timed_out else 'RED'}. "
              f"Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, direction, why, edits, tests in MUTANTS:
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor — mutates nothing: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:60]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, timed_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed, fix it)" if timed_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif timed_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}")
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in "
              "your source:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (harness faults — these measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
