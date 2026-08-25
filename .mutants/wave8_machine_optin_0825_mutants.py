"""Mutation harness for Wave 8 step J — the machine's own logs are OPT-IN.

⛔⛔ WHAT THIS CHANGED. Wave 8 gave an OWNER the machine-level material on every
send automatically: pairing and sign-in sessions, the raw device tails. The
reasoning was that an owner is entitled to their own machine's logs — which is
true, and is not the same as having ASKED for them. Defaulting to the larger
bundle is the one direction this whole wave is supposed to fail in. Owner's call
2026-08-25: a tick-box under the run list, unticked.

⭐ AND THE FLAG IS READ OFF THE COMMAND, the opposite of the call made for
`consent`. That one is a claim about what a person was shown, so a caller could
forge it and the sink must not trust it. This one can only ever make the bundle
SMALLER, because it is ANDed with ownership — so failing closed and failing safe
are the same thing here. O3 restores the version that trusts it without the AND.

⛔ THE TERMINAL IS DELIBERATELY UNCHANGED, and L1 restores the version that is
not. `--send-logs` still sends the machine material by default: the person
running it is physically at the machine, and the founding incident was a pairing
failure that produced no run at all, so that material is the whole evidence.

    python .mutants/wave8_machine_optin_0825_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_machine_optin_0825.py"
# ⛔ THE SIBLING FILES WHOSE PROPERTIES THIS SOURCE OWNS. A harness scoped to its
# own file has three times in this repo reported "real suite gaps" that were only
# its own blindness.
T_CMD = "tests/test_send_logs_command_0818.py"
T_SEL = "tests/test_bundle_selection_0824.py"
T_CLI = "tests/test_send_logs_cli_0824.py"
T_CLI_OLD = "tests/test_send_logs_cli_0818.py"
ALL = [T_NEW, T_CMD, T_SEL, T_CLI, T_CLI_OLD]

for _t in ALL:
    if not (ROOT / _t).is_file():
        raise SystemExit(f"harness names a test file that does not exist: {_t}")

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

_PARSE = """    return data.get("includeMachine") is True"""

_DECIDE = """    machine_wanted = (is_owner and _parse_include_machine(data)) if selected else True"""

_NOTHING = """        if not only_runs and not machine_wanted:"""

_CLI_BUILD = """        summary = _build_log_bundle(dest, support_code=code, max_runs=n_runs,
                                    only_runs=only_runs)"""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the flag itself ═══════════════════════════════════════════════
    ("O1", "over", "⛔⛔ THE DEFAULT THIS CHANGE EXISTS TO REMOVE, restored: every "
     "owner's send carries the pairing history and the raw device tails again, "
     "without being asked for",
     [(_DECIDE, "    machine_wanted = True")],
     [T_NEW]),
    ("O2", "over", "⛔ TRUTHINESS instead of identity, so `1`, `\"true\"` and any "
     "non-empty string ask for the machine — the shapes a hand-written or older "
     "client sends, every one of them resolving toward MORE collection",
     [(_PARSE, '    return bool(data.get("includeMachine"))')],
     [T_NEW]),
    ("O3", "over", "⛔⛔ THE OWNERSHIP AND GOES, so a SHARER who sets the flag gets "
     "the owner's pairing history and raw device tails — which is the whole "
     "reason reading this off the command is safe, removed",
     [(_DECIDE,
       "    machine_wanted = _parse_include_machine(data) if selected else True")],
     [T_NEW]),
    ("O4", "under", "the flag is ignored, so an owner who ticked the box gets "
     "runs only and the control is decoration",
     [(_PARSE, "    return False")],
     [T_NEW]),
    ("O5", "over", "an ABSENT flag asks for the machine, so an app build that "
     "predates the box — and any caller that forgets it — collects everything",
     [(_PARSE, '    return data.get("includeMachine") is not False')],
     [T_NEW]),

    # ══ the legacy path must not move ═════════════════════════════════
    ("L1", "under", "⛔⛔ the LEGACY actions lose the machine material. `send-logs` "
     "MEANS \"this machine's own cap\" and there is no box on that path to "
     "consult, so this silently shrinks what every older app build collects",
     [(_DECIDE,
       "    machine_wanted = is_owner and _parse_include_machine(data)")],
     [T_NEW, T_CMD]),
    ("L2", "under", "⛔ the TERMINAL stops sending the machine material, so a "
     "pairing failure that produced no run sends an archive with no evidence in "
     "it — the founding incident, in the one place it is guaranteed to be hit",
     [(_CLI_BUILD,
       "        summary = _build_log_bundle(dest, support_code=code, max_runs=n_runs,\n"
       "                                    only_runs=only_runs,\n"
       "                                    include_machine=False)")],
     [T_NEW, T_CLI, T_CLI_OLD]),

    # ══ nothing to send ══════════════════════════════════════════════
    ("N1", "over", "⛔⛔ an empty pick with the box unticked builds an EMPTY "
     "ARCHIVE and hands back a support code that explains nothing — worse than a "
     "refusal, because the person believes they sent something",
     [(_NOTHING, "        if False:")],
     [T_NEW]),
    ("N2", "over", "the guard reverts to sharer-only, so an OWNER reaches the "
     "empty archive — the exact case the tick-box created",
     [(_NOTHING, "        if not only_runs and not is_owner:")],
     [T_NEW]),
    ("N3", "under", "the guard refuses a machine-only send, so the "
     "pairing-failure case — no runs to tick, box ticked instead — cannot be "
     "asked for at all",
     [(_NOTHING, "        if not only_runs:")],
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
