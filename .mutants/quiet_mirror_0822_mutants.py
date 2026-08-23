"""Mutation harness for wave 6 fix 7 (backend half) — `quiet` and the mirror.

⛔ WHAT THIS IS FOR. `fail_phase(..., mark_phase_errored=False)` is a preflight
abort: a later phase could not be REACHED, nothing in it errored, and badging
its tile red tells the user a step failed that never ran. `quiet` says "surface
the card, do not badge the tile" — and `emit_event`'s durable-mirror seam
enumerated eleven keys and not that one.

⚠ The gate makes that look harmless until you read `force_mirror`. The seam
normally REFUSES to mirror a quiet card, so for most of them there is nothing to
carry. `force_mirror` is the deliberate exception and it exists for exactly one
shape: a card quiet BY DESIGN that must still survive a cold open — the login
interrupt, where nothing errored. That is the card the mirror rebuilt as a red ✖.

⭐⭐ THE SHARPEST MUTANTS HERE:
  Q1 — the key goes. Every other assertion about the mirror still passes and the
       one card that needed it comes back loud.
  Q2 — the value is mirrored raw. A truthy STRING then fails the frontend's
       `quiet === true` test, so the flag is carried and still does nothing.
  Q5 — the gate stops excluding quiet cards, so every transient preflight abort
       becomes a durable decision that re-surfaces on cold open.

    python .mutants/quiet_mirror_0822_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_QUIET = "tests/test_quiet_flag_mirror_0822.py"
# ⛔ The mirror seam and the alert intents share one emit path; a change here
# must not move what the other one persists.
T_INTENTS = "tests/test_alert_intents.py"
ALL = [T_QUIET, T_INTENTS]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    ("Q1", "under", "⛔⛔ the key goes — the one card that needed it comes back "
     "loud, and every other mirror assertion still passes",
     [('                "quiet": bool(data.get("quiet")),\n', "")],
     [T_QUIET]),
    ("Q2", "under", "⛔ the value is mirrored raw, so a truthy STRING fails the "
     "frontend's `quiet === true` test — carried and still doing nothing",
     [('                "quiet": bool(data.get("quiet")),',
       '                "quiet": data.get("quiet"),')],
     [T_QUIET]),
    ("Q3", "under", "the flag is hardcoded false, so force_mirror carries a lie",
     [('                "quiet": bool(data.get("quiet")),',
       '                "quiet": False,')],
     [T_QUIET]),
    ("Q4", "over", "every mirrored card claims to be quiet, so no cold-open card "
     "ever badges its tile again",
     [('                "quiet": bool(data.get("quiet")),',
       '                "quiet": True,')],
     [T_QUIET]),
    ("Q5", "over", "⛔⛔ the gate stops excluding quiet cards, so every transient "
     "preflight abort becomes a durable decision that re-surfaces on cold open",
     [('                and (not data.get("quiet") or _force_mirror)\n', "")],
     [T_QUIET]),
    ("Q6", "under", "force_mirror stops being the exception, so the one card "
     "that must survive a cold open no longer does",
     [('                and (not data.get("quiet") or _force_mirror)',
       '                and not data.get("quiet")')],
     [T_QUIET]),
    ("Q7", "under", "a card with no buttons is mirrored, so an FYI with nothing "
     "to answer becomes a durable decision",
     [('        if (event_type == "pipeline_error" and data.get("actions")',
       '        if (event_type == "pipeline_error"')],
     [T_QUIET]),
    ("F1", "under", "the producer stops marking a preflight abort quiet, so the "
     "flag this fix carries is never set in the first place",
     [('    if not mark_phase_errored:\n        payload["quiet"] = True\n', "")],
     [T_QUIET]),
    ("F2", "under", "#908 goes: a failure tagged with a phase the run has not "
     "reached paints that phase's tile red again",
     [('        if mark_phase_errored and isinstance(_cur_phase, int) and phase > _cur_phase:',
       '        if False:')],
     [T_QUIET]),
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
            if not tests:
                raise ValueError("no tests declared")
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:70]}")
                mutated = mutated.replace(frm, to, 1)
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
