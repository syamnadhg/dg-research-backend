"""Mutation harness for Clear logs — the LOCAL half (2026-08-18 owner wave).

⛔⛔ WHAT THIS FUNCTION REPLACED. "Clear Shared Logs" deleted the bundles already
uploaded and left every log file on the machine. For a control a person presses
for privacy reasons, the whole payload — topics, result links, account email,
agent screens — stayed on their own disk. The owner's instruction was to make the
short label true, so the action grew a device command and this is what it runs.

⭐⭐ THE DEFINING TEST CANNOT AGREE WITH THE CODE BY CONSTRUCTION. It clears, then
BUILDS a bundle, and asserts the archive holds only its own manifest/index/
collected. Every "did it cover source X" mutant below is measured against that,
not against a list this harness repeats.

⛔ Two mutants exist to pin choices that a reviewer would plausibly reverse:
unlinking the raw tails instead of truncating them (the supervisor holds them
open in append mode), and clearing the parked-row file LAST (the reconnect
watcher republishes from it on every tick, so any window resurrects a bundle the
person just cleared).

    python .mutants/clear_local_logs_0818_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_clear_local_logs_0818.py"
# ⛔ THE SIBLING FILES WHOSE PROPERTIES THIS SOURCE OWNS. Three separate times a
# harness in this repo reported "real suite gaps" that were nothing but its own
# scope: the mutated function shares `_folder_is_live`, `_system_log_tails` and
# `_build_log_bundle` with the bundle and run-capture suites, and a mutant that
# breaks one of those must be measured against the tests that already cover it.
T_BUNDLE = "tests/test_log_bundle_0818.py"
T_CAPTURE = "tests/test_run_log_capture_0818.py"
T_CMD = "tests/test_send_logs_command_0818.py"
ALL = [T_NEW, T_BUNDLE, T_CAPTURE, T_CMD]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ── coverage of each source the collector reads ──
    ("C1", "under", "⭐⭐ run folders are never removed — the biggest payload on "
     "the disk survives a clear",
     [("            shutil.rmtree(folder)\n            out[\"runs\"] += 1",
       "            out[\"runs\"] += 1")],
     [T_NEW]),
    ("C2", "under", "session files are never removed — and the founding incident "
     "produced NO run, so its whole evidence is a session",
     [("            path.unlink()\n            out[\"sessions\"] += 1",
       "            out[\"sessions\"] += 1")],
     [T_NEW]),
    ("C3", "under", "the raw tails are left full — 18 MB of backend.log carrying "
     "the machine's whole history",
     [("            with open(path, \"r+b\") as fh:\n                fh.truncate(0)\n"
       "            out[\"tails\"] += 1",
       "            out[\"tails\"] += 1")],
     [T_NEW]),
    ("C4", "under", "the machine's own finished bundle and its parked rows are "
     "left — the same payload under a different name",
     [("            path.unlink()\n            out[\"bundles\"] += 1",
       "            out[\"bundles\"] += 1")],
     [T_NEW]),

    # ── the truncate-vs-unlink choice ──
    ("C5", "over", "⛔ the tails are UNLINKED instead of truncated, so the "
     "supervisor keeps appending to an inode with no name",
     [("            with open(path, \"r+b\") as fh:\n                fh.truncate(0)",
       "            path.unlink()")],
     [T_NEW]),
    ("C6", "over", "⛔ the tail filter is dropped and every file in the log root "
     "is truncated, including a developer's own captures",
     [("    for path in _system_log_tails(base):",
       "    for path in [p for p in base.iterdir() if p.is_file()]:")],
     [T_NEW]),

    # ── the in-flight run guard ──
    ("C7", "over", "⛔ a RUNNING pipeline's folder is destroyed under it — its "
     "checkpoint and open log handle go with it",
     [("        if str(folder) in live or _folder_is_live(folder):",
       "        if False:")],
     [T_NEW]),
    ("C8", "over", "only the in-process sink list guards liveness, so worker 1 "
     "destroys the folder worker 2 is writing into",
     [("        if str(folder) in live or _folder_is_live(folder):",
       "        if str(folder) in live:")],
     [T_NEW]),
    ("C9", "under", "the meta is trusted verbatim, so one crashed run pins its "
     "folder on the disk forever",
     [("        if str(folder) in live or _folder_is_live(folder):",
       "        if str(folder) in live or (folder / \"meta.json\").exists():")],
     [T_NEW]),

    # ── the ordering that closes the resurrection window ──
    ("C10", "over", "⛔⛔ the parked-row file is cleared LAST, so a reconnect-"
     "watcher drain during the rmtree republishes a bundle just cleared",
     [("    leftovers = []\n    pending = base / \"pending-bundle-rows.jsonl\"\n"
       "    if pending.exists():\n        leftovers.append(pending)",
       "    leftovers = []\n    pending = base / \"pending-bundle-rows.jsonl\"\n"
       "    if False:\n        leftovers.append(pending)")],
     [T_NEW]),

    # ── the honesty of the report ──
    ("C11", "under", "a failure is swallowed instead of counted, so a partial "
     "clear reports as a whole one",
     [("            out[\"failed\"] += 1\n            log(f\"[clear-logs] run folder {folder.name}: {exc}\", \"WARN\")",
       "            log(f\"[clear-logs] run folder {folder.name}: {exc}\", \"WARN\")")],
     [T_NEW]),
    ("C12", "under", "the kept count is never incremented, so a preserved live "
     "run is invisible in the only record anybody reads",
     [("            out[\"kept\"] += 1\n            continue",
       "            continue")],
     [T_NEW]),

    # ── the dispatch wiring ──
    ("C13", "under", "⛔⛔ `clear-logs` drops out of the worker-1 gate tuple, so "
     "worker 2 deletes the command before worker 1 ever sees it",
     [("                            \"clear-logs\",\n                            SEND_LOGS_ACTION,",
       "                            SEND_LOGS_ACTION,")],
     [T_NEW]),
    ("C14", "over", "every worker runs the clear concurrently, racing each "
     "other's rmtree",
     [("                if WORKER_ID == 1:\n                    try:\n                        cleared = _clear_local_logs()",
       "                if True:\n                    try:\n                        cleared = _clear_local_logs()")],
     [T_NEW]),
    # ⛔ RE-ANCHORED 2026-08-19: a seventh counter (`telemetry`) joined the dict
    # when the clear was extended past the collector's own sources.
    ("C15", "under", "the handler reports only three of the seven counters, so a "
     "partial clear reads as total in the log",
     [("                            f\"tails={cleared['tails']} bundles={cleared['bundles']} \"\n"
       "                            f\"telemetry={cleared['telemetry']} \"\n"
       "                            f\"kept={cleared['kept']} failed={cleared['failed']}\")",
       "                            f\"tails={cleared['tails']}\")")],
     [T_NEW]),
    ("C16", "over", "the handler stops guarding against a raise, so one OSError "
     "queues every later device command behind it",
     [("                    try:\n                        cleared = _clear_local_logs()",
       "                    if True:\n                        cleared = _clear_local_logs()")],
     [T_NEW]),
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
