"""Mutation harness for the Ctrl+C re-assert fix.

The 08-10 fix armed the stop handlers once and logged on arrival. The evidence
line worked: on 08-11 a live serve was measured honouring SIGTERM (logged,
drained, exited in ~3s) while ignoring SIGINT entirely (no line, no backstop
thread, still serving HTTP two milliseconds later). Same handler, same install.
So the disposition was being reset underneath us mid-run, and the fix is to hold
the handlers rather than install them once.

Half of these mutate in the OVER-correction direction, because this fix has
several obvious too-far versions and one of them is a refactor anyone would call
a cleanup: rebuilding the handler on every re-assert. That hands each pass a
fresh press counter and silently kills the second Ctrl+C — the press that exists
to escape a stalled graceful shutdown.

The under-correction that matters most is C1: gating the re-install on
`getsignal`. It looks strictly better, it passes any test that asks "is our
handler installed?", and it restores the exact bug — because `getsignal` reports
Python's own record, which stays correct when the disposition is changed below
it.

Safety, learned from an earlier harness on this repo that adopted a mutant as
its own baseline: refuses to start on a dirty tree, holds originals in memory
only, restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/serve_stop_rearm_0811_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
REARM = "tests/test_serve_stop_rearm_0811.py"
ARMED = "tests/test_serve_stop_signals_0810.py"
BOTH_SUITES = f"{REARM} {ARMED}"

# (id, direction, why, [(from, to)], test_target)
MUTANTS = [
    # ── the install must be unconditional ───────────────────────────────────
    ("C1", "under", "re-install gated on getsignal — the original bug, restored",
     [("        try:\n            sig_mod.signal(_s, handler)\n            installed.append(name)",
       "        try:\n            if current is not handler:\n                sig_mod.signal(_s, handler)\n            installed.append(name)")],
     BOTH_SUITES),

    # ── the handlers must be HELD, not installed once ───────────────────────
    ("C2", "under", "the re-assert loop is gone; one install again",
     [("    while True:\n        await asyncio.sleep(_STOP_REARM_S)\n"
       "        _assert_stop_handlers(_sig, _signums, _on_stop, _reported)",
       "    return")],
     BOTH_SUITES),
    ("C3", "under", "the loop runs once and stops",
     [("    while True:\n        await asyncio.sleep(_STOP_REARM_S)\n"
       "        _assert_stop_handlers(_sig, _signums, _on_stop, _reported)",
       "    await asyncio.sleep(_STOP_REARM_S)\n"
       "    _assert_stop_handlers(_sig, _signums, _on_stop, _reported)")],
     BOTH_SUITES),
    ("C4", "under", "only SIGINT is held, so a supervisor's SIGTERM rots",
     [("    _signums = (_sig.SIGINT, _sig.SIGTERM)",
       "    _signums = (_sig.SIGINT,)")],
     BOTH_SUITES),

    # ── the evidence line ───────────────────────────────────────────────────
    ("C5", "under", "drift is repaired silently — no line ever names the culprit",
     [('        if announce and current is not handler and ("drift", _s) not in reported:',
       '        if False and current is not handler and ("drift", _s) not in reported:')],
     BOTH_SUITES),
    ("C6", "under", "the drift line no longer says WHAT it drifted to",
     [('                f"({_stop_handler_description(sig_mod, current)}) — restoring it. "',
       '                f"— restoring it. "')],
     BOTH_SUITES),
    ("C7", "under", "SIG_IGN and a native install collapse into one description",
     [('    if current is None:\n        return "not set from Python — installed by native code"',
       '    if current is None:\n        return "SIG_IGN — the signal was being discarded"')],
     BOTH_SUITES),
    ("C8", "under", "arming failure is a DEBUG whisper again",
     [('                log(f"[serve] could not arm {name}: {_se}", "WARN")',
       '                log(f"[serve] could not arm {name}: {_se}", "DEBUG")')],
     BOTH_SUITES),

    # ── over-corrections ────────────────────────────────────────────────────
    ("C9", "over", "the handler is rebuilt per pass, resetting the press counter",
     [("    while True:\n        await asyncio.sleep(_STOP_REARM_S)\n"
       "        _assert_stop_handlers(_sig, _signums, _on_stop, _reported)",
       "    while True:\n        await asyncio.sleep(_STOP_REARM_S)\n"
       "        def _fresh(signum, _frame, _h=_on_stop):\n"
       "            return _h(signum, _frame)\n"
       "        _assert_stop_handlers(_sig, _signums, _fresh, _reported)")],
     BOTH_SUITES),
    ("C10", "over", "the first install announces drift, crying wolf every startup",
     [("    installed = _assert_stop_handlers(_sig, _signums, _on_stop, _reported,\n"
       "                                      announce=False)",
       "    installed = _assert_stop_handlers(_sig, _signums, _on_stop, _reported,\n"
       "                                      announce=True)")],
     BOTH_SUITES),
    ("C11", "over", "the once-per-signal guard is dropped — a WARN every few seconds forever",
     [('            reported.add(("drift", _s))', '            pass')],
     BOTH_SUITES),
    ("C12", "over", "one signal failing to arm aborts the other",
     [("        except Exception as _se:            # non-main thread, or a platform",
       "        except Exception as _se:\n            if True:\n                raise" + "  # noqa\n"
       "        except BaseException as _se:")],
     BOTH_SUITES),
    ("C13", "over", "arming failure propagates and takes serve down with it",
     [("    installed = []\n    for _s in signums:", "    installed = []\n    raise RuntimeError('boom')\n    for _s in signums:")],
     BOTH_SUITES),
    ("C14", "over", "re-asserting every 100ms — two syscalls a tick, forever",
     [("_STOP_REARM_S = 5.0", "_STOP_REARM_S = 0.1")],
     BOTH_SUITES),
    ("C15", "over", "the period exceeds the grace window, so a drift outlives a stop",
     [("_STOP_REARM_S = 5.0", "_STOP_REARM_S = 20.0")],
     BOTH_SUITES),
]


def sh(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests(target: str) -> bool:
    """True when the suite PASSES."""
    return sh([sys.executable, "-m", "pytest", *target.split(), "-q"]).returncode == 0


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    for target in {m[4] for m in MUTANTS}:
        print(f"baseline {target}… ", end="", flush=True)
        if not run_tests(target):
            print("RED. Nothing below would mean anything.")
            return 2
        print("green")

    path = ROOT / RESEARCH
    survivors = []
    for mid, direction, why, edits, target in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found: {frm[:70]!r}")
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
