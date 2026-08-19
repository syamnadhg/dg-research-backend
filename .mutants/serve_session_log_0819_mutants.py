"""Mutation harness for the serve session log (2026-08-19).

⛔⛔ WHAT IT REPLACED. `_session_command_name` excluded `--serve` because "its
stdout is already redirected into backend.log by the supervisor" — true of a
supervised worker, false of `python research.py --serve` in a terminal, which has
no supervisor. That session wrote NO log file at all: startup, pairing, the
device-command listener and the whole shutdown tail existed only in terminal
scrollback, and a support bundle collected none of it.

⭐ It is also why the e2e recording command wrapped serve in `tee` with a signal
trap. The file is strictly better than the pipe: a `tee` dies with its process
group on Ctrl+C and loses the ending, which is the half that matters.

⛔⛔ AND THE HAZARD IT INTRODUCED: `--serve` is MULTI-THREADED, while the three
commands that used this writer before were not — so the unlocked writer was safe
by accident. `self.lines += 1` is a read-modify-write and the GIL does not make it
atomic; the same race corrupts the byte counter and the live-segment list around
every rollover.

    python .mutants/serve_session_log_0819_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_serve_session_log_0819.py"
# ⛔ THE SIBLING FILES WHOSE PROPERTIES THIS SOURCE OWNS. The capped writer and
# the session tee are shared with the run-capture and bundle suites, and the
# clear covers the sessions/ directory — a harness scoped to its own file has
# three times in this repo reported "suite gaps" that were only its own scope.
T_CAPTURE = "tests/test_run_log_capture_0818.py"
T_BUNDLE = "tests/test_log_bundle_0818.py"
T_CLEAR = "tests/test_clear_local_logs_0818.py"
ALL = [T_NEW, T_CAPTURE, T_BUNDLE, T_CLEAR]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    ("V1", "under", "⭐⭐ THE DEFECT ITSELF — a manual serve is excluded again, so "
     "the whole session logs into a void and the bundle carries none of it",
     [('    if getattr(args, "serve", False) and getattr(args, "worker_id", None) is None:\n'
       '        return "serve"\n', "")],
     [T_NEW]),
    ("V2", "over", "⛔ a SUPERVISED worker gets a session file too, so every line "
     "is written twice and the bundle ships both copies",
     [('    if getattr(args, "serve", False) and getattr(args, "worker_id", None) is None:',
       '    if getattr(args, "serve", False):')],
     [T_NEW]),
    ("V3", "over", "the supervisor itself is handed a session file on top of the "
     "backend.log it already writes",
     [('    if getattr(args, "serve", False) and getattr(args, "worker_id", None) is None:',
       '    if getattr(args, "serve", False) or getattr(args, "daemon_loop", False):')],
     [T_NEW]),
    ("V4", "under", "the three interactive commands lose their files, which is the "
     "gap wave 1 closed",
     [('    for flag in ("pair", "login", "doctor"):\n'
       "        if getattr(args, flag, False):\n"
       "            return flag\n", "")],
     [T_NEW]),
    ("V5", "under", "⛔⛔ THE LOCK GOES, so concurrent serve threads lose lines "
     "around every rollover — the exact bytes a wedged session needs",
     [("        with self._lock:\n            self._write_locked(line, n)",
       "        self._write_locked(line, n)")],
     [T_NEW, T_CAPTURE]),
    ("V6", "under", "the lock is created per call rather than per writer, so it "
     "guards nothing at all",
     [("        self._lock = __import__(\"threading\").RLock()",
       "        self._lock = None")],
     [T_NEW, T_CAPTURE]),
    ("V7", "under", "the session file lands outside the log root, so the "
     "collector's allowlist refuses it and the bundle silently omits it",
     [("            _sessions_log_root() / f\"{command}_{stamp}.log\",",
       "            Path.home() / f\"{command}_{stamp}.log\",")],
     [T_NEW, T_BUNDLE]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ MEASURED 2026-08-18: a stale `__pycache__/*.pyc` served OLD bytecode
        # for a source file that had already been fixed, and the measurement
        # disagreed with the file for three rounds. In a harness that rewrites the
        # source between every run, a cached module is not a nuisance — it is a
        # kill or a survivor invented out of nothing.
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
