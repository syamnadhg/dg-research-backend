"""Mutation harness for Wave 8 step D — publishing which runs a machine holds.

⛔⛔ WHY THE CHANNEL EXISTS. Local retention is 60 runs / 30 days and the research
documents outlive it, so a picker built from Firestore alone offers runs whose
logs are gone. The owner decided those rows are HIDDEN, not greyed out — "the
list shows only what can actually be sent" — and only the machine knows what that
is.

⭐⭐ IT PUBLISHES IDS, NEVER LABELS, and that is the property most of the `over`
mutants below attack. There is no topic and no title anywhere in a run folder;
`_run_log_folder_name` has no `run_id` parameter precisely so a topic cannot
reach a folder name. The app holds the labels already and joins on `researchId`.
A mutant that puts a topic in this document is putting every sharer's research
subject into a Firestore write the machine makes on their behalf.

⛔ AND THE ONE A CHANGE-GATE ALWAYS GETS WRONG is E1: when a submitter's last run
is pruned they drop out of the scan, so there is nothing to compare and the
obvious implementation simply skips them — leaving the picker offering a run
whose logs are gone, which is the exact thing the hidden-not-greyed decision was
meant to prevent.

    python .mutants/wave8_run_index_0824_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_run_index_publish_0824.py"
# ⛔ THE SIBLING FILES WHOSE PROPERTIES THIS SOURCE OWNS. `_scan_run_folders` and
# the row shape are shared with the bundle and capture suites, and a harness
# scoped to its own file has three times reported "suite gaps" in this repo that
# were nothing but its own blindness.
T_CAP = "tests/test_run_log_capture_0818.py"
T_BUNDLE = "tests/test_log_bundle_0818.py"
T_SEL = "tests/test_bundle_selection_0824.py"
ALL = [T_NEW, T_CAP, T_BUNDLE, T_SEL]

for _t in ALL:
    if not (ROOT / _t).is_file():
        raise SystemExit(f"harness names a test file that does not exist: {_t}")

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

_SKIP_UNATTRIBUTED = """        uid = row.get("submitterUid")
        if not uid:
            continue"""

_SORT_TRUNCATE = """        items.sort(key=lambda r: float(r.get("startedEpoch") or 0), reverse=True)"""

_TRUNCATE = """            "runs": [_run_index_entry(r) for r in items[:RUN_INDEX_MAX]],
            "truncated": len(items) > RUN_INDEX_MAX,"""

_ENTRY_NAME = """        "name": str(row.get("name") or "")[:96],"""

_ENTRY_STATUS = """        "status": str(row.get("status") or "unknown")[:24],"""

_EMPTIES = """    for uid in list(_run_index_published):
        payloads.setdefault(uid, {"runs": [], "truncated": False})"""

_CHANGE_GATE = """        if not force and _run_index_published.get(uid) == fingerprint:
            continue"""

_RECORD = """            _run_index_published[uid] = fingerprint
            written[uid] = True"""

_THROTTLE = """    if not force and stamp < _run_index_next_ms:
        return {}"""

# ⛔ WIDENED: three functions in this file open with the same two lines, so the
# narrow anchor matched 3x and measured nothing. It now carries the line that
# only this publisher has.
_NO_DEVICE = """    device_id = load_device_id()
    if not device_id:
        return {}
    payloads = _run_index_by_submitter(_scan_run_folders())"""

_HEARTBEAT_CALL = """                    await asyncio.wait_for(
                        asyncio.to_thread(_publish_run_log_index), timeout=15.0)"""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ what may be published, and to whom ════════════════════════════
    ("P1", "over", "⛔⛔ an UNATTRIBUTED run is published to somebody. Every run "
     "folder in the field is unattributed, so this is not an edge case — it is "
     "every machine's whole history, offered to whoever the fallback names",
     [(_SKIP_UNATTRIBUTED,
       '        uid = row.get("submitterUid") or "unknown"\n'
       "        if False:\n            continue")],
     [T_NEW]),
    ("P2", "over", "⛔⛔ THE TOPIC LEAKS. A label is added to the descriptor, so "
     "every sharer's research subject enters a Firestore document the machine "
     "writes on their behalf — through the one channel built to carry ids only",
     [(_ENTRY_NAME,
       '        "name": str(row.get("name") or "")[:96],\n'
       '        "topic": str(row.get("topic") or ""),')],
     [T_NEW]),
    ("P3", "over", "the folder name is published unbounded, so a pathological "
     "name pushes the document past what the rule accepts and the person's "
     "picker silently stays empty",
     [(_ENTRY_NAME, '        "name": str(row.get("name") or ""),')],
     [T_NEW]),
    ("P4", "under", "a run with no recorded status publishes an EMPTY status "
     "rather than `unknown`, so the picker cannot tell a corpse from a blank",
     [(_ENTRY_STATUS, '        "status": str(row.get("status") or "")[:24],')],
     [T_NEW]),

    # ══ the bound, and its direction ══════════════════════════════════
    ("B1", "under", "⛔ the list truncates the NEWEST instead of the oldest, so "
     "the run the person is about to complain about is the first one hidden",
     [(_SORT_TRUNCATE,
       '        items.sort(key=lambda r: float(r.get("startedEpoch") or 0))')],
     [T_NEW]),
    ("B2", "over", "the list is unbounded, so a busy machine can push a document "
     "past the size the rule allows — and a refused write is an empty picker",
     [(_TRUNCATE,
       '            "runs": [_run_index_entry(r) for r in items],\n'
       '            "truncated": False,')],
     [T_NEW]),
    ("B3", "under", "`truncated` is hardcoded true, so a complete list claims to "
     "be missing runs and the person goes looking for the terminal command",
     [(_TRUNCATE,
       '            "runs": [_run_index_entry(r) for r in items[:RUN_INDEX_MAX]],\n'
       '            "truncated": True,')],
     [T_NEW]),

    # ══ the publisher's lifecycle ═════════════════════════════════════
    ("E1", "under", "⛔⛔ THE ONE A CHANGE-GATE GETS WRONG. A submitter whose last "
     "run was pruned drops out of the scan, so nothing is compared and nothing "
     "is written — and the picker keeps offering a run whose logs are gone, "
     "which is the exact case the hidden-not-greyed decision was about",
     [(_EMPTIES, "    if False:\n        pass")],
     [T_NEW]),
    ("E2", "over", "the change gate is gone, so a directory walk plus a "
     "Firestore write per submitter runs on every tick forever",
     [(_CHANGE_GATE, "        if False:\n            continue")],
     [T_NEW]),
    ("E3", "over", "the throttle is gone, so the scan — a directory walk and a "
     "`meta.json` read per folder — runs on the five-second heartbeat tick",
     [(_THROTTLE, "    if False:\n        return {}")],
     [T_NEW]),
    ("E4", "over", "⛔ A FAILED WRITE IS RECORDED AS PUBLISHED. The rule ships "
     "separately from the code, so a 403 on every tick is the normal state until "
     "it is deployed — and this makes the machine believe it published, so the "
     "picker never fills after the rule lands",
     [(_RECORD,
       "            _run_index_published[uid] = fingerprint\n"
       "            written[uid] = True\n"
       "        except Exception:\n"
       "            _run_index_published[uid] = fingerprint")],
     [T_NEW]),
    ("E5", "over", "an unpaired machine publishes anyway, writing under an empty "
     "device id that no picker can ever match",
     [(_NO_DEVICE,
       "    device_id = load_device_id() or 'unknown'\n"
       "    payloads = _run_index_by_submitter(_scan_run_folders())")],
     [T_NEW]),

    # ══ where it is called from ═══════════════════════════════════════
    ("H1", "over", "⛔ the publish runs INLINE on the heartbeat's own task, so a "
     "slow Firestore write delays the liveness write and the app flips the "
     "device to Offline — a diagnostics feature becoming an availability bug",
     [(_HEARTBEAT_CALL, "                    _publish_run_log_index()")],
     [T_NEW]),
    ("H2", "under", "the heartbeat stops publishing at all, so the list is "
     "written once at boot and never again",
     [(_HEARTBEAT_CALL, "                    pass")],
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
