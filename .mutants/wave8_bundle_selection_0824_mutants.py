"""Mutation harness for Wave 8 step C — a bundle scoped to the runs one person picked.

⛔⛔ THE ONE DIRECTION THIS MUST NEVER FAIL IN. The collector's own docstring
already stated the rule before this wave — "falling back would resolve every
malformed request toward MORE collection than was agreed to" — so almost every
mutant below is an `over`: a plausible, helpful-looking reading that ships more
than the person agreed to send.

⭐⭐ THE ONE THAT DECIDES THE WAVE is A3: attribution failing OPEN. Not one run
folder in the field records a submitter — the field landed 2026-08-21 and the
shipped 0.1.13 wheel has zero occurrences of it — so "unknown submitter" is the
COMMON case, not an edge. Treating unknown as "matches whoever asked" hands a
sharer who ticked two runs the entire machine, every time, on every device.

⛔ AND THE MACHINE-LEVEL MATERIAL IS NOT A SMALLER VERSION OF THE RUNS. Measured:
`backend.log` on this machine carries 18 distinct research ids and 15 topics in
queue paths, against 5 run folders on disk. No filter makes those tails honest
inside a one-person bundle — only omission, which is what M1/M2 restore.

⚠ The accept-polarity mutants matter as much: an omission that omits everything
ships a bundle with no evidence in it, and would pass every "did it exclude X"
assertion ever written.

    python .mutants/wave8_bundle_selection_0824_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_bundle_selection_0824.py"
# ⛔ THE SIBLING FILES WHOSE PROPERTIES THIS SOURCE OWNS. A scope-limited harness
# in this repo has three times reported "real suite gaps" that were only its own
# blindness. `_build_log_bundle` is shared with all four of these.
T_BUNDLE = "tests/test_log_bundle_0818.py"
T_CLEAR = "tests/test_clear_local_logs_0818.py"
T_HONEST = "tests/test_bundle_tail_honesty_0822.py"
T_CMD = "tests/test_send_logs_command_0818.py"
T_CLI = "tests/test_send_logs_cli_0818.py"
ALL = [T_NEW, T_BUNDLE, T_CLEAR, T_HONEST, T_CMD, T_CLI]

# ⛔ A harness that names a test file which does not exist goes RED on every
# mutant and reports a clean sweep. This repo has shipped that once.
for _t in ALL:
    if not (ROOT / _t).is_file():
        raise SystemExit(f"harness names a test file that does not exist: {_t}")

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

_ATTRIB = """        if requester_uid is not None and row.get("submitterUid") != requester_uid:"""

_MISSING = """        row = by_name.get(name)
        if row is None:
            missing.append(name)
            continue"""

_DEDUPE = """        if name in seen:
            continue
        seen.add(name)"""

_SORT = """    picked.sort(key=lambda r: float(r.get("startedEpoch") or 0), reverse=True)"""

_CAP = """    cap = max(0, int(max_runs))
    over = [r["name"] for r in picked[cap:]]"""

_REFUSED_REPORT = """        "runsNotAttributed": len(refused),"""

_BRANCH = """    if only_runs is None:
        selected = _select_bundle_runs(rows, max_runs=max_runs,
                                       max_age_days=max_age_days, now=now)
        selection_report = {}"""

_SESSIONS = """    sessions = (_select_bundle_sessions(max_age_days=max_age_days, now=now)
                if include_machine else [])"""

_TAILS = """        for path in (_system_log_tails() if include_machine else []):"""

_SUMMARY_SELECTION = """        "selectionApplied": only_runs is not None,
        "requesterScoped": requester_uid is not None,
        "machineIncluded": bool(include_machine),
        **selection_report,"""

_MANIFEST_SELECTION = """            "selectionApplied": only_runs is not None,
            "requesterScoped": requester_uid is not None,
            "machineIncluded": bool(include_machine),"""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ attribution ═══════════════════════════════════════════════════
    ("A1", "over", "⛔⛔ THE ATTRIBUTION FILTER IS GONE — anyone who can name a "
     "folder collects it, so a sharer's pick reaches the owner's runs",
     [(_ATTRIB, "        if False:")],
     [T_NEW]),
    ("A2", "over", "the filter is inverted, so a person collects exactly the "
     "runs that are NOT theirs",
     [(_ATTRIB,
       '        if requester_uid is not None and row.get("submitterUid") == requester_uid:')],
     [T_NEW]),
    ("A3", "over", "⛔⛔ THE ONE THAT DECIDES THE WAVE: attribution fails OPEN on "
     "an unknown submitter. Every run folder in the field is unattributed, so "
     "this is not an edge case — it is the whole machine, every time",
     [(_ATTRIB,
       '        if (requester_uid is not None and row.get("submitterUid")\n'
       '                and row.get("submitterUid") != requester_uid):')],
     [T_NEW]),
    ("A4", "under", "the filter runs even with no requester, so the OWNER at "
     "their own terminal can no longer select the unattributed runs that are "
     "the only ones their machine has",
     [(_ATTRIB, '        if row.get("submitterUid") != requester_uid:')],
     [T_NEW]),
    ("A5", "over", "a refused run is silently absent instead of counted, so a "
     "narrowed selection reads as a complete one",
     [(_REFUSED_REPORT, '        "runsNotAttributed": 0,')],
     [T_NEW]),

    # ══ the machine-level material ════════════════════════════════════
    ("M1", "over", "⛔⛔ the raw device tails ride along on a one-person bundle — "
     "measured at 18 research ids and 15 topics against 5 run folders, i.e. "
     "everything the machine has ever done for everyone who uses it",
     [(_TAILS, "        for path in _system_log_tails():")],
     [T_NEW]),
    ("M2", "over", "the pairing/login/doctor sessions ride along too — the "
     "owner's own login and pairing history inside a sharer's bundle",
     [(_SESSIONS,
       "    sessions = _select_bundle_sessions(max_age_days=max_age_days, now=now)")],
     [T_NEW]),
    ("M3", "under", "⛔ THE ACCEPT-POLARITY FAILURE: the machine material is "
     "omitted from EVERY bundle, so the founding incident — a pairing failure "
     "that produced no run at all — ships with no evidence in it",
     [(_SESSIONS, "    sessions = []")],
     [T_NEW, T_BUNDLE, T_CLEAR]),
    ("M4", "under", "the tails are omitted from every bundle, for the same "
     "reason and with the same cost",
     [(_TAILS, "        for path in []:")],
     [T_NEW, T_BUNDLE, T_HONEST]),

    # ══ the selection itself ══════════════════════════════════════════
    ("S1", "over", "⛔⛔ AN EMPTY SELECTION MEANS 'EVERYTHING'. An owner who ticks "
     "nothing — the pairing-failure case — gets all thirty runs instead of the "
     "machine-level bundle they asked for",
     [(_BRANCH, "    if not only_runs:\n"
                "        selected = _select_bundle_runs(rows, max_runs=max_runs,\n"
                "                                       max_age_days=max_age_days, now=now)\n"
                "        selection_report = {}")],
     [T_NEW]),
    ("S2", "over", "a name that is not on disk is dropped without a word, so a "
     "stale page's pick produces a quietly shorter bundle",
     [(_MISSING,
       "        row = by_name.get(name)\n"
       "        if row is None:\n"
       "            continue")],
     [T_NEW]),
    ("S3", "over", "the signed-off count ceiling stops applying to an explicit "
     "pick, so one selection can carry every run on the disk",
     [(_CAP, "    cap = len(picked)\n    over = [r[\"name\"] for r in picked[cap:]]")],
     [T_NEW]),
    ("S4", "under", "the cap keeps the OLDEST instead of the newest, so the run "
     "the person is complaining about is the first one dropped",
     [(_SORT,
       '    picked.sort(key=lambda r: float(r.get("startedEpoch") or 0))')],
     [T_NEW]),
    ("S5", "under", "a duplicate tick is counted twice, so the requested count "
     "the person is shown disagrees with what they clicked",
     [(_DEDUPE, "        if False:\n            continue\n        seen.add(name)")],
     [T_NEW]),

    # ══ the receipt ═══════════════════════════════════════════════════
    ("R1", "over", "⛔⛔ THE ACCEPTED-AND-IGNORED FLAG. The summary reports a "
     "selection whatever happened, so a caller that drops the keyword ships the "
     "newest thirty under a row that says a selection was applied",
     [(_SUMMARY_SELECTION,
       '        "selectionApplied": True,\n'
       '        "requesterScoped": requester_uid is not None,\n'
       '        "machineIncluded": bool(include_machine),\n'
       "        **selection_report,")],
     [T_NEW]),
    ("R2", "under", "the summary stops reporting the selection at all, so no "
     "caller can tell a scoped bundle from a whole-machine one",
     [(_SUMMARY_SELECTION, "        **selection_report,")],
     [T_NEW]),
    ("R3", "under", "the manifest inside the archive stops saying which kind of "
     "bundle it is, so a reader takes a short scoped archive for a broken machine",
     [(_MANIFEST_SELECTION, '            "runsSelected": len(selected),')],
     [T_NEW]),
    ("R4", "over", "the manifest claims the machine material is present when it "
     "is not — the one lie that would send support looking for a file the "
     "bundle was never allowed to carry",
     [(_MANIFEST_SELECTION,
       '            "selectionApplied": only_runs is not None,\n'
       '            "requesterScoped": requester_uid is not None,\n'
       '            "machineIncluded": True,')],
     [T_NEW]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ A stale `__pycache__/*.pyc` served OLD bytecode for three rounds of
        # measurement here. In a harness that rewrites the source between runs it
        # is a kill or a survivor invented out of nothing.
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
