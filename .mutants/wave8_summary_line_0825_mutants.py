"""Mutation harness for Wave 8's verify tail — the log line that names the bundle.

⛔⛔ WHAT THIS PROTECTS. The archive's summary carries eleven facts and every one
was already written to Firestore. The machine's own log said `received` and
`bundle uploaded (N bytes)` — so the FIRST artefact a support engineer opens, the
log the person just sent, was the only place that could not say what was in the
archive next to it. S1 restores exactly that.

⛔ AND THE POSITION IS LOAD-BEARING, WHICH S2 IS ABOUT. The local copy is kept on
purpose — it is the floor the whole design rests on and `--doctor` prints where it
is — so a build that succeeds and an upload that fails still has to leave a record
of what the file on disk contains. Logging after the upload loses precisely the
case where this line is the only evidence left.

⭐ THE OVER-CORRECTIONS ARE MOSTLY ABOUT NOISE, and that is deliberate. A
diagnostic line is only worth having if people still read it after a year: S4
makes the clean case end in three zeroes and S14 files it at WARN, and both are
regressions even though both add information.

⛔⛔ ANCHORS ARE SINGLE LITERALS, NEVER CONCATENATIONS — the frontend sweep caught
this harness's sibling doing it on 2026-08-25, and the failure mode is silent: a
joined anchor resolves to its first fragment, so the sweep measures a prefix while
reporting on the whole mutant.

    python .mutants/wave8_summary_line_0825_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_send_logs_summary_0825.py"
# ⛔ THE SIBLINGS WHOSE PROPERTIES THIS SOURCE OWNS. A harness scoped to its own
# test file has three times in this repo reported "real suite gaps" that were
# only its own blindness — the property was pinned next door.
T_OPTIN = "tests/test_machine_optin_0825.py"
T_CMD = "tests/test_send_logs_command_0818.py"
T_SEL = "tests/test_bundle_selection_0824.py"
ALL = [T_NEW, T_OPTIN, T_CMD, T_SEL]

for _t in ALL:
    if not (ROOT / _t).is_file():
        raise SystemExit(f"harness names a test file that does not exist: {_t}")

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

# ── anchors: one literal each ──────────────────────────────────────────
CALL = "            log(_send_logs_summary_line(summary))\n"

HEAD = """    n_runs = int(summary.get("runCount") or 0)
    on_disk = int(summary.get("runsOnDisk") or 0)"""

RUNS_PART = """        f"{n_runs} run{'' if n_runs == 1 else 's'} of {on_disk} on disk","""

BYTES_PART = """        f"{int(summary.get('sizeBytes') or 0)} bytes "
        f"({int(summary.get('uncompressedBytes') or 0)} raw)","""

MACHINE_PART = """        f"machine={'yes' if summary.get('machineIncluded') else 'no'}","""

CAP_PART = """        f"cap {int(summary.get('maxRunsApplied') or 0)}","""

SELECTION = """    if summary.get("selectionApplied"):
        asked = int(summary.get("runsRequested") or 0)"""

ASKED = """        parts.append(f"asked for {asked}" if asked != n_runs else "picked, all present")"""

TRIPLE = """    for key, word in (("runsNotOnDisk", "not on disk"),
                      ("runsNotAttributed", "not attributed"),
                      ("runsOverCap", "over cap")):"""

GATE = """        n = int(summary.get(key) or 0)
        if n:
            parts.append(f"{n} {word}")"""

PREFIX = """    line = f"[send-logs] built {summary.get('supportCode') or '?'}: " + ", ".join(parts)"""

DROPPED = """        line += f" · dropped for size: {', '.join(str(d) for d in dropped)}\""""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the call itself ═══════════════════════════════════════════════
    ("S1", "under", "⛔⛔ THE DEFECT ITSELF: the summary is never logged. Eleven "
     "facts reach Firestore and the machine's own log is back to `received` and "
     "`bundle uploaded (N bytes)` — the one artefact a support engineer reads "
     "first, unable to describe the archive beside it",
     [(CALL, "")],
     [T_NEW]),
    ("S2", "over", "⛔⛔ LOGGED AFTER THE UPLOAD, so a build that succeeds and an "
     "upload that fails leaves no record of what the kept local copy contains — "
     "the exact case this line is the only evidence for",
     [(CALL, ""),
      ("            object_path = _upload_log_bundle_via_storage_rest(\n"
       "                dest, row_uid, device_id, code)",
       "            object_path = _upload_log_bundle_via_storage_rest(\n"
       "                dest, row_uid, device_id, code)\n"
       "            log(_send_logs_summary_line(summary))")],
     [T_NEW]),
    ("S3", "over", "⛔ FILED AT WARN. Every successful send now reads as a problem "
     "in a log people scan by severity — and this project has already misread its "
     "own log severity as system health once, reporting three non-problems as "
     "defects",
     [(CALL, '            log(_send_logs_summary_line(summary), "WARN")\n')],
     [T_NEW]),

    # ══ the facts that must always be there ══════════════════════════
    ("S4", "under", "⛔⛔ THE PAIR GOES: runs-sent without runs-on-disk. `1 run` "
     "alone cannot separate `they picked one of twelve` from `the machine only "
     "had one`, and those lead to opposite conclusions about whether the logs "
     "somebody is asking for still exist",
     [(RUNS_PART, '        f"{n_runs} run{\'\' if n_runs == 1 else \'s\'}",')],
     [T_NEW]),
    ("S5", "under", "the raw byte count goes, so a 383 KB archive holding 1.2 MB "
     "of text reads the same as one holding 400 KB — compression working and the "
     "trim having eaten almost everything become indistinguishable",
     [(BYTES_PART, '        f"{int(summary.get(\'sizeBytes\') or 0)} bytes",')],
     [T_NEW]),
    ("S6", "over", "⛔ the machine flag prints a Python bool, so `machine=True` "
     "leaks a repr into a support artefact a customer may be reading",
     [(MACHINE_PART, '        f"machine={summary.get(\'machineIncluded\')}",')],
     [T_NEW]),
    ("S7", "under", "the cap goes, so a bundle cut at 30 and one cut at 3 read "
     "identically — and the cap is the number a person disputes when a run they "
     "ticked is not in the archive",
     [(CAP_PART, "")],
     [T_NEW]),
    ("S8", "under", "⛔ THE SUPPORT CODE GOES. Two sends a minute apart are "
     "otherwise identical lines, and the code is the only thing that ties this "
     "line to the one the person quotes",
     [(PREFIX, '    line = "[send-logs] built: " + ", ".join(parts)')],
     [T_NEW]),
    ("S9", "over", "`1 runs`, because the plural is unconditional — small, and "
     "the kind of thing that makes a reader distrust the numbers beside it",
     [(RUNS_PART, '        f"{n_runs} runs of {on_disk} on disk",')],
     [T_NEW]),

    # ══ noise, in both directions ════════════════════════════════════
    ("S10", "over", "⛔⛔ THE ZERO GATE GOES, so every clean send ends in `0 not on "
     "disk, 0 not attributed, 0 over cap`. A line that always says the same three "
     "things is a line people stop reading, which is this project's own log-noise "
     "finding applied to its newest log line",
     [(GATE, '        n = int(summary.get(key) or 0)\n'
             '        parts.append(f"{n} {word}")')],
     [T_NEW]),
    ("S11", "under", "⛔⛔ `runsNotAttributed` STOPS BEING REPORTED — the sharpest "
     "of the three. It means the picker offered a run and the machine then refused "
     "to hand it over, so somebody ticked something and did not send it, and the "
     "whole per-run feature looks broken with no evidence why",
     [(TRIPLE, '    for key, word in (("runsNotOnDisk", "not on disk"),\n'
               '                      ("runsOverCap", "over cap")):')],
     [T_NEW]),
    ("S12", "under", "the dropped list becomes a COUNT, so a support engineer "
     "knows one run is missing from the archive in front of them and cannot tell "
     "the reporter which one",
     [(DROPPED, '        line += f" · {len(dropped)} dropped for size"')],
     [T_NEW]),

    # ══ the selection, which is the one boolean a dropped kwarg flips ═
    ("S13", "under", "⛔⛔ A BUNDLE BUILT WITH NO SELECTION REPORTS AS A HONOURED "
     "ONE. Every test stub for the builder in this repo is `lambda dest, **k`, so "
     "a lost `only_runs=` is invisible to all of them — two runs are requested, "
     "thirty ship, and this was the line that would have said so",
     [(SELECTION, '    if True:\n        asked = int(summary.get("runsRequested") or 0)')],
     [T_NEW]),
    ("S14", "over", "the discrepancy is reported as `picked N`, which reads as "
     "`N were sent` beside a leading count that says otherwise — a reader has to "
     "connect two numbers to notice three runs are missing",
     [(ASKED, '        parts.append(f"picked {asked}")')],
     [T_NEW]),

    # ══ it must never turn a success into a failure ═══════════════════
    ("S15", "over", "⛔ THE MISSING-KEY GUARDS GO, so a partial summary raises "
     "inside the worker's try and a successful send is logged as `bundle failed: "
     "KeyError` — a diagnostic line that manufactures the failure it describes",
     [(HEAD, '    n_runs = int(summary["runCount"])\n'
             '    on_disk = int(summary["runsOnDisk"])')],
     [T_NEW]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
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
        print(f"{'TIMED OUT' if timed_out else 'RED'}. Nothing below would mean anything.")
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
