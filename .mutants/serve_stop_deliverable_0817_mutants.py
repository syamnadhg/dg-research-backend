"""Mutation harness for "a stop signal has to be able to ARRIVE".

⛔ THE REPORT (owner, 2026-08-17). Three Ctrl+C presses on an idle serve produced
no line of any kind — not `stop requested`, not the `was no longer ours` drift
line the previous wave added — and the same process went on to claim and run a
job a minute later. So nothing was wedged and nothing had drifted in a way the
existing loop could see. A blocked signal produces exactly that: held PENDING,
never delivered, while `getsignal` still reports us and every re-assert pass
reports success.

⭐ THE OVER-CORRECTIONS ARE THE SHARP END here, because the fix writes to the
process signal mask:
  D3 — ⛔⛔ the mask READ becomes a mask WRITE. `pthread_sigmask(SIG_BLOCK, [])`
       is how you read it; passing the signums there instead BLOCKS the two
       signals this function exists to free. One word, total inversion.
  D4 — the whole mask is unblocked, handing the process every signal somebody
       else deliberately deferred.
  D8 — ⛔⛔ unblock before install, so a pending signal is delivered to whatever
       the disposition had drifted to. With SIG_DFL that is an outright kill of
       the server we are trying to shut down cleanly.
  D9 — a platform without pthread_sigmask raises instead of standing down, so
       Windows cannot start a serve at all.

    python .mutants/serve_stop_deliverable_0817_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_serve_stop_deliverable_0817.py"
T_REARM = "tests/test_serve_stop_rearm_0811.py"
T_SIG = "tests/test_serve_stop_signals_0810.py"
ALL = [T_NEW, T_REARM, T_SIG]

PY = str(ROOT / ".venv" / "bin" / "python")

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ── the repair itself ───────────────────────────────────────────────────
    ("D1", "under", "⭐⭐ THE ORIGINAL GAP — nothing is ever unblocked, so a "
     "blocked SIGINT stays pending forever while every check reports success",
     [("    stuck = [_s for _s in signums if _s in blocked]",
       "    stuck = []")],
     [T_NEW]),
    ("D2", "under", "the unblock is dropped but the WARN is kept — the log says "
     "it was fixed and it was not, which is worse than silence",
     [("    try:\n        sig_mod.pthread_sigmask(sig_mod.SIG_UNBLOCK, stuck)",
       "    try:\n        pass")],
     [T_NEW]),
    ("D3", "over", "⛔⛔ the mask READ becomes a mask WRITE — the two stop "
     "signals get BLOCKED by the function whose job is to free them",
     [("        blocked = sig_mod.pthread_sigmask(sig_mod.SIG_BLOCK, [])",
       "        blocked = sig_mod.pthread_sigmask(sig_mod.SIG_BLOCK, signums)")],
     [T_NEW]),
    ("D4", "over", "the whole mask is freed, not just the stop signals — every "
     "signal another library deliberately deferred is handed to the process",
     [("        sig_mod.pthread_sigmask(sig_mod.SIG_UNBLOCK, stuck)",
       "        sig_mod.pthread_sigmask(sig_mod.SIG_UNBLOCK, blocked)")],
     [T_NEW]),
    ("D5", "over", "one blocked signal drags the other along, so SIGTERM is "
     "unblocked because SIGINT was",
     [("    stuck = [_s for _s in signums if _s in blocked]",
       "    stuck = list(signums) if any(_s in blocked for _s in signums) else []")],
     [T_NEW]),

    # ── the evidence ────────────────────────────────────────────────────────
    ("D6", "under", "⛔ the repair is silent — the one line that would name this "
     "class is gone, which is the exact state the previous investigation began in",
     [('        if ("blocked", _s) not in reported:',
       '        if False and ("blocked", _s) not in reported:')],
     [T_NEW]),
    ("D7", "under", "'blocked' and 'blocked AND a press was already waiting' "
     "collapse into one line, so the proof that a human pressed it is lost",
     # ⛔ First attempt indented this by 8 and measured NOTHING (anchor 0x). The
     # block sits inside a `for` inside an `if`, so it is 12.
     [('            _waiting = (" and already pending — a stop had been pressed and "\n'
       '                        "swallowed") if _s in pending else ""',
       '            _waiting = ""')],
     [T_NEW]),
    ("D11", "over", "the once-per-signal guard is dropped — a WARN every pass, "
     "forever, on a loop that now runs once a second",
     [('            reported.add(("blocked", _s))', '            pass')],
     [T_NEW]),

    # ── the order, which is the dangerous part ──────────────────────────────
    ("D8", "over", "⛔⛔ unblock BEFORE install — a pending signal is delivered "
     "to whatever the disposition had drifted to, and SIG_DFL kills the server "
     "outright instead of draining it",
     [("    installed = _assert_stop_handlers(sig_mod, signums, handler, reported,\n"
       "                                      announce=announce)\n"
       "    freed = _unblock_stop_signals(sig_mod, signums, reported)",
       "    freed = _unblock_stop_signals(sig_mod, signums, reported)\n"
       "    installed = _assert_stop_handlers(sig_mod, signums, handler, reported,\n"
       "                                      announce=announce)")],
     [T_NEW]),

    # ── it must never be what stops a serve starting ────────────────────────
    ("D9", "over", "⛔ a platform with no signal mask raises instead of standing "
     "down, so Windows cannot start a serve at all",
     [("    try:\n        # Blocking the empty set is the documented way to READ the mask.\n"
       "        blocked = sig_mod.pthread_sigmask(sig_mod.SIG_BLOCK, [])\n"
       "    except Exception:\n        return freed",
       "    blocked = sig_mod.pthread_sigmask(sig_mod.SIG_BLOCK, [])")],
     [T_NEW]),
    ("D10", "over", "an unreadable pending set costs the repair, so the LINE's "
     "nice-to-have takes the cure down with it",
     [("    try:\n        pending = sig_mod.sigpending()\n"
       "    except Exception:\n        pending = set()",
       "    pending = sig_mod.sigpending()")],
     [T_NEW]),

    # ── wiring: the helper must actually be reached ─────────────────────────
    ("D12", "under", "⭐ the loop goes back to asserting the handler only, so the "
     "mask is never looked at and the whole helper is unreachable",
     [("    while True:\n        await asyncio.sleep(_STOP_REARM_S)\n"
       "        _hold_stop_signals(_sig, _signums, _on_stop, _reported)",
       "    while True:\n        await asyncio.sleep(_STOP_REARM_S)\n"
       "        _assert_stop_handlers(_sig, _signums, _on_stop, _reported)")],
     [T_NEW, T_REARM]),
    ("D13", "under", "the arm-time pass skips the mask, so a signal blocked "
     "before the server ever started stays blocked for the life of the process",
     [("    installed, freed = _hold_stop_signals(_sig, _signums, _on_stop, _reported,\n"
       "                                          announce=False)",
       "    installed = _assert_stop_handlers(_sig, _signums, _on_stop, _reported,\n"
       "                                      announce=False)\n    freed = []")],
     [T_NEW]),
    ("D14", "under", "startup stops announcing that it had to unblock something "
     "— the worst case of all, made invisible",
     [('    if freed:\n        log(f"[serve] {\', \'.join(freed)} had to be unblocked at arm time", "WARN")',
       '    if False:\n        log("", "WARN")')],
     [T_NEW]),

    # ── the period that bounds how long a press looks dead ──────────────────
    ("D15", "over", "the repair period goes back to five seconds, which is long "
     "enough that a swallowed press still reads as broken — the report itself",
     [("_STOP_REARM_S = 1.0", "_STOP_REARM_S = 5.0")],
     [T_REARM]),
]


# ⛔ A MUTANT CAN TURN A TEST INTO AN INFINITE LOOP, and then the harness hangs
# instead of reporting. That is not hypothetical: the first run of this file sat
# for twelve minutes on D12, because a test ended its (deliberately endless) loop
# by raising from a monkeypatched function that D12 stops calling. The test was
# fixed to terminate unconditionally, and this timeout is the backstop for the
# next one — a hang is a KILL with a note, never a stall.
_TEST_TIMEOUT_S = 180


def green(tests: list[str]) -> tuple[bool, bool]:
    """(passed, timed_out). A timeout counts as failing, i.e. mutant killed."""
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
        target = ROOT / SRC          # every mutant in this wave edits research.py
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
