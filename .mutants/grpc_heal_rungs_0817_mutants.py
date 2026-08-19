"""Mutation harness for splitting the 403 heal's confounded experiment.

⛔ THE REPORT (owner, 2026-08-17): "the grpc-heal 403 fires on every run and
self-heals every time — let's root-cause it rather than heal forever."

⭐⭐ THE OLD LADDER COULD NOT ANSWER THE QUESTION IT CLAIMED TO. Its comment read
"the retry is the EXPERIMENT, so its result is the diagnosis" — but that retry
changed TWO things at once: a newly minted token AND a securetoken round-trip's
worth of elapsed time. "Cleared by the re-minted token — the cached credential
was stale" and "a propagation race resolved on its own" produce the identical
log line. Every run's first user-tree write logged one and every one self-healed,
which is exactly what a confounded experiment leaves behind.

A plain retry on the SAME token, with no delay, changes nothing except that a
first attempt already happened. It is now rung 1, ahead of the throttle (it never
touches securetoken), and its outcome finally separates the two hypotheses.

⭐ THE OVER-CORRECTIONS ARE THE SHARP END:
  G4/G6 — the retry's implicit `__context__` IS the original 403, so without
          `ignore` EVERY failure on the retry path — a dropped network, a bug —
          classifies as a rules denial and buys a securetoken round-trip.
  G5    — …and over-correcting THAT blinds the ladder to a genuinely NEW masked
          denial, which arrives on the very same edge. That is the flip, i.e.
          the write this whole heal was built for.
  G8    — rung 1 lands but the structural latch stays set, suppressing every
          future force-refresh over a problem that has already gone away.

⭐ One mutant is deliberately absent: G7 deleted a chain WALK inside the ignore
helper and survived, because a retry's context always reaches the original
exception object first. The walk was removed rather than covered.

    python .mutants/grpc_heal_rungs_0817_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_grpc_synth_403_heal.py"
T_FLIP = "tests/test_flip_stage_0806.py"
T_MULTI = "tests/test_multiworker_rehydration_728.py"
ALL = [T_NEW, T_FLIP, T_MULTI]

PY = str(ROOT / ".venv" / "bin" / "python")

RUNG1 = """        try:
            result = op()
            with _grpc_heal_lock:
                _grpc_heal_consec_fail = 0
                _grpc_heal_structural = False
            log(
                f"[grpc-heal] {what}: cleared by an IMMEDIATE retry on the SAME "
                f"token — no refresh, no delay. The credential was NOT stale, so "
                f"this denial was transient (claim/doc propagation), and no "
                f"securetoken round-trip was spent on it.",
                "INFO",
            )
            return result
        except Exception as _plain_e:
"""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    ("G1", "under", "⭐⭐ RUNG 1 IS GONE — back to the one confounded retry that "
     "could never tell a stale credential from a race",
     [(RUNG1, "        if True:\n            pass\n        try:\n            pass\n        except Exception as _plain_e:\n")],
     [T_NEW]),
    ("G2", "under", "rung 1 runs but its result is thrown away, so the write "
     "still pays for a token it did not need",
     [("            result = op()\n            with _grpc_heal_lock:\n"
       "                _grpc_heal_consec_fail = 0\n"
       "                _grpc_heal_structural = False",
       "            result = None\n            op()\n            with _grpc_heal_lock:\n"
       "                _grpc_heal_consec_fail = 0\n"
       "                _grpc_heal_structural = False")],
     [T_NEW]),
    ("G3", "under", "⛔ rung 1 moves BEHIND the throttle — but the throttle exists "
     "to protect securetoken, which rung 1 never touches, so a throttled write "
     "loses the one free attempt that may be all it needed",
     [("        # Throttle + structural latch under the lock so concurrent worker\n"
       "        # threads can't all slip past the cooldown and fire simultaneous heals.\n"
       "        with _grpc_heal_lock:\n"
       "            now = time.time()\n"
       "            if _grpc_heal_structural or (now - _grpc_heal_last_ts < _GRPC_HEAL_COOLDOWN_S):",
       "        # Throttle + structural latch under the lock so concurrent worker\n"
       "        # threads can't all slip past the cooldown and fire simultaneous heals.\n"
       "        with _grpc_heal_lock:\n"
       "            now = time.time()\n"
       "            if True or _grpc_heal_structural or (now - _grpc_heal_last_ts < _GRPC_HEAL_COOLDOWN_S):")],
     [T_NEW]),
    ("G4", "over", "⛔⛔ the original 403 is no longer excluded from the retry's "
     "chain, so a dropped network on the retry reads as a rules denial and mints "
     "a token to 'fix' it",
     [("            if not _is_synth_permission_denied(_plain_e, ignore=exc):",
       "            if not _is_synth_permission_denied(_plain_e):")],
     [T_NEW]),
    ("G5", "under", "⛔⛔ the exclusion swallows a genuinely NEW masked denial — "
     "the transactional flip, which is the write this heal exists for",
     [("            if not _is_synth_permission_denied(_plain_e, ignore=exc):\n                raise",
       "            raise")],
     [T_NEW]),
    ("G6", "over", "the ignore-set is empty, which is G4 by another route",
     [("    seen: \"set[int]\" = {id(ignore)} if ignore is not None else set()",
       "    seen: \"set[int]\" = set()")],
     [T_NEW]),
    # ⛔ G7 REMOVED, and its removal is the finding. It deleted the chain WALK in
    # a helper that seeded `ignore`'s whole chain — and it survived every test,
    # because a retry's __context__ always reaches the original exception OBJECT
    # before anything deeper in its chain. The walk could not change an answer,
    # so the helper is gone rather than covered.
    ("G8", "over", "⛔ rung 1 lands but the structural latch stays set — every "
     "future force-refresh suppressed over a problem that already went away",
     [("            with _grpc_heal_lock:\n                _grpc_heal_consec_fail = 0\n"
       "                _grpc_heal_structural = False\n            log(\n"
       "                f\"[grpc-heal] {what}: cleared by an IMMEDIATE retry",
       "            with _grpc_heal_lock:\n                pass\n            log(\n"
       "                f\"[grpc-heal] {what}: cleared by an IMMEDIATE retry")],
     [T_NEW]),
    ("G9", "under", "the rung-2 success line goes back to claiming a stale "
     "credential without saying the plain rung had already failed — the exact "
     "unearned conclusion this wave removed",
     [("                f\"[grpc-heal] {what}: cleared by the RE-MINTED token after a plain \"\n"
       "                f\"retry on the same token had already failed — so the cached \"",
       "                f\"[grpc-heal] {what}: cleared by the re-minted token — the cached \"\n"
       "                f\"credential was stale. Ignore this line. \"")],
     [T_NEW]),
    ("G10", "under", "an unhealed denial stops saying that BOTH rungs failed, so "
     "the corpus cannot rule out a transient race either",
     [("                    f\"[grpc-heal] {what}: neither a plain retry nor a re-minted \"",
       "                    f\"[grpc-heal] {what}: the re-minted token did NOT clear the \"")],
     [T_NEW]),
]

_TEST_TIMEOUT_S = 180


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        rc = subprocess.run([PY, "-m", "pytest", "-q", *tests], cwd=ROOT,
                            capture_output=True, timeout=_TEST_TIMEOUT_S).returncode
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
