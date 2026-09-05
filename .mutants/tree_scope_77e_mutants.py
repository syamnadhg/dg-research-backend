"""7.7E backend — the run titles the machine stops publishing, and the tree it
stops enumerating.

⛔⛔ THE MUTANTS HERE FALL INTO TWO KINDS AND ONLY ONE OF THEM IS A PRIVACY BUG.

The first kind puts a title back. `devices/{deviceId}` is read WHOLE by the
owner, every sharer and the machine — Firestore cannot scope a read to fields —
so every one of these was a live list of what everybody else on a shared computer
was researching. This file had already written the reason down at the run-history
publisher, which refuses to put history on that document because "one sharer
would learn every other sharer's run history", and then three other sites put the
live one there anyway.

The second kind is about the rehydration scan, and it is a CORRECTNESS bug that
the privacy work uncovered rather than caused. Nothing in that loop looks at
`deviceId`: ownership is decided by `assignedWorker`, a worker NUMBER. So on a
sharer's tree a run that executed on somebody's OTHER computer — `assignedWorker`
unset, which defaults to worker 1 — satisfies `_i_own` here. Unscoped, this
machine marks that machine's healthy run `paused_backend_restart`, and on a
supervised device auto-resumes it against the wrong browser profiles.

⭐ S2 IS THE ONE TO READ TWICE. It scopes the OWNER's tree as well as the
sharer's, which looks like more of the same fix and is not: the tightened rule
admits an owner-tree list with no per-document test, the orphan safety net is
meant to reach runs whose owning worker is out of this fleet, and an equality
filter silently drops every document written before the `deviceId` stamp existed.
Three separate design reviews recommended exactly this.

⛔ W1 IS THE OTHER TRAP. It scopes on an EMPTY device id — the state a machine is
in mid-pairing — which matches nothing and disables rehydration for every sharer,
silently, on a build that looks correct.

  .venv/bin/python .mutants/tree_scope_77e_mutants.py
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_sharer_tree_scoping_77e.py"
# ⛔ THE SIBLING FILES WHOSE PROPERTIES THIS SOURCE OWNS. A scope-limited harness
# in this repo has three times reported "real suite gaps" that were only its own
# blindness — so the queue-position, queue-owners and deferred-recompute suites
# come along, because every title carrier is published by one of them.
T_REHYD = "tests/test_sharer_rehydration.py"
T_POS = "tests/test_global_queue_position.py"
T_OWNERS = "tests/test_queue_owners_union.py"
T_DEFER = "tests/test_deferred_recompute.py"
ALL = [T_NEW, T_REHYD, T_POS, T_OWNERS, T_DEFER]

# ⛔ EVERY NAME ABOVE IS CHECKED AGAINST THE DISK. A harness in this repo has
# already shipped a `tests:` list naming a file that does not exist: pytest treats
# a missing path as an error, the run goes red, and EVERY mutant reads as killed.
# A harness that cannot fail is worse than no harness.
for _t in ALL:
    if not (ROOT / _t).is_file():
        raise SystemExit(f"harness names a test file that does not exist: {_t}")

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

_SCOPE = """    _scoped_col = researches_col
    if tree_uid != owner_uid:
        _my_device_id = load_device_id() or ""
        if _my_device_id:
            _scoped_col = _fs_where(researches_col, "deviceId", "==", _my_device_id)"""

_CRUN = """                            "currentRunTitle": _crun_delete_field(),"""

_WORKERS = """                        f"workers.{WORKER_ID}": {
                            "uid": job.get("uid") or "",
                            "runId": job.get("research_id") or "",
                            "phase": 0,
                            "totalPhases": 6,
                        },"""

_QUEUE_OWNERS = """        _queue_owners.append({
            "uid": (d.get("submittedBy") or d.get("uid") or "").strip(),
            "runId": rid_v,
            "position": new_pos,
        })"""

_LOCAL_ENTRIES = """        out.append({
            "uid": uid_v,
            "runId": rid_v,
            "position": len(out) + 1,
        })"""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the rehydration scope ══════════════════════════════════════════
    ("S1", "under",
     "⛔⛔ the scan goes back to unscoped on a sharer's tree. Nothing below it "
     "reads deviceId, so a run that executed on that person's OTHER computer "
     "satisfies `_i_own` here — this machine marks their healthy run "
     "paused_backend_restart, and on a supervised device re-opens it against "
     "the wrong browser profiles",
     [(_SCOPE, "    _scoped_col = researches_col")],
     [T_NEW]),
    ("S2", "over",
     "⛔⛔ THE OWNER'S TREE IS SCOPED TOO, which three design reviews asked for. "
     "The tightened rule admits an owner-tree list with no per-document test, "
     "the orphan safety net is meant to reach runs whose owning worker is out "
     "of this fleet, and an equality filter silently drops every document "
     "written before the deviceId stamp existed",
     [(_SCOPE,
       '    _scoped_col = researches_col\n'
       '    _my_device_id = load_device_id() or ""\n'
       '    if _my_device_id:\n'
       '        _scoped_col = _fs_where(researches_col, "deviceId", "==", _my_device_id)')],
     [T_NEW]),
    ("W1", "over",
     "⛔⛔ the empty-id guard goes, so a machine mid-pairing filters on \"\" — "
     "which matches nothing and disables sharer rehydration entirely, on a "
     "build that looks correct and logs nothing",
     [('        _my_device_id = load_device_id() or ""\n'
       '        if _my_device_id:\n'
       '            _scoped_col = _fs_where(researches_col, "deviceId", "==", _my_device_id)',
       '        _my_device_id = load_device_id() or ""\n'
       '        _scoped_col = _fs_where(researches_col, "deviceId", "==", _my_device_id)')],
     [T_NEW]),
    ("S3", "under",
     "⛔ the scoped collection is computed and then not used, which is the "
     "cheapest way to make a wiring test pass while the query is unchanged",
     [('                        _fs_where(_scoped_col, "status", "==", sv).get()',
       '                        _fs_where(researches_col, "status", "==", sv).get()')],
     [T_NEW]),
    ("S4", "over",
     "⛔ the sharer-tree denial goes quiet again. Rules deploy in seconds and a "
     "wheel arrives when its owner upgrades, so a mismatch lands on a machine "
     "nobody can tell — at DEBUG the only symptom is that a run killed by a "
     "restart quietly stops being resumable",
     [('                    f"— relying on device-queue + on-disk state",\n'
       '                    "WARN",',
       '                    f"— relying on device-queue + on-disk state",\n'
       '                    "DEBUG",')],
     [T_NEW]),
    ("S5", "over",
     "⛔⛔ the dead-worker reconcile is scoped as well — the edit that looks like "
     "consistency. Its only caller passes the paired owner, so it never touches "
     "a sharer tree and buys no permission; what it does buy is dropping every "
     "pre-stamp document from the abandoned-run safety net",
     [('    researches_col = _firebase_db.collection("users").document(tree_uid) \\\n'
       '        .collection("researches")\n'
       '    try:\n'
       '        snaps = await asyncio.wait_for(\n'
       '            asyncio.to_thread(\n'
       '                lambda: list(_fs_where(researches_col, "status", "==", "ongoing").get())',
       '    researches_col = _fs_where(_firebase_db.collection("users").document(tree_uid) \\\n'
       '        .collection("researches"), "deviceId", "==", load_device_id() or "")\n'
       '    try:\n'
       '        snaps = await asyncio.wait_for(\n'
       '            asyncio.to_thread(\n'
       '                lambda: list(_fs_where(researches_col, "status", "==", "ongoing").get())')],
     [T_NEW]),

    # ══ the title carriers ═════════════════════════════════════════════
    ("C1", "over",
     "⛔⛔ the machine publishes its current run's topic onto the shared device "
     "record again, so the person queued behind you is told what you are "
     "researching — by name, live, in their browser",
     [(_CRUN, '                            "currentRunTitle": (job.get("topic") or "")[:60],')],
     [T_NEW, T_DEFER, T_OWNERS]),
    ("C2", "under",
     "⛔ the field stops being cleared as well as written, so whatever this "
     "machine last published stays on the record until the next STOP — the "
     "delete is what removes a value an older build already wrote",
     [(_CRUN, "")],
     [T_NEW, T_DEFER, T_OWNERS]),
    ("C3", "over",
     "⛔⛔ every worker publishes its run's topic in the busy-worker map, which "
     "is the same leak once per worker rather than once per machine",
     [(_WORKERS,
       '                        f"workers.{WORKER_ID}": {\n'
       '                            "uid": job.get("uid") or "",\n'
       '                            "runId": job.get("research_id") or "",\n'
       '                            "title": (job.get("topic") or "")[:60],\n'
       '                            "phase": 0,\n'
       '                            "totalPhases": 6,\n'
       '                        },')],
     [T_NEW, T_OWNERS, T_DEFER]),
    ("C4", "over",
     "⛔⛔ the WIDEST carrier comes back: queueOwners is a machine-wide snapshot "
     "of every queued run across every account on the hardware, so one array on "
     "one document tells everybody what everybody is working on",
     [(_QUEUE_OWNERS,
       '        _queue_owners.append({\n'
       '            "uid": (d.get("submittedBy") or d.get("uid") or "").strip(),\n'
       '            "runId": rid_v,\n'
       '            "title": (d.get("topic") or "")[:60],\n'
       '            "position": new_pos,\n'
       '        })')],
     [T_NEW, T_DEFER, T_OWNERS]),
    ("C5", "over",
     "⛔ the locally-pending half of that same array carries the topic, so the "
     "leak returns for the jobs this worker has claimed but not started",
     [(_LOCAL_ENTRIES,
       '        out.append({\n'
       '            "uid": uid_v,\n'
       '            "runId": rid_v,\n'
       '            "title": (job.get("topic") or "")[:60],\n'
       '            "position": len(out) + 1,\n'
       '        })')],
     [T_NEW, T_OWNERS]),
    ("Q1", "over",
     "⛔⛔ the machine reaches into the tree of the person queued AHEAD to fetch "
     "their topic, and writes it onto this person's research document — one "
     "account's private string stored in another account's record",
     [('        _, prev_data, _ = queue[my_idx - 1]\n'
       '        behind_rid = (prev_data.get("researchId") or "")\n'
       '    return (position, behind_rid, behind_title)',
       '        _, prev_data, _ = queue[my_idx - 1]\n'
       '        behind_rid = (prev_data.get("researchId") or "")\n'
       '        behind_title = (prev_data.get("topic") or "")[:60]\n'
       '    return (position, behind_rid, behind_title)')],
     [T_NEW, T_POS]),
    ("Q2", "over",
     "⛔ the enrichment helper does the same, on the path the FE banner reads — "
     "the sibling of Q1, and the one a fix that only patched the other would "
     "leave live",
     [('        # ⛔ Topic not extracted — see the note in the sibling helper above.\n'
       '        _, prev_data, _ = queue[my_idx - 1]\n'
       '        behind_rid = (prev_data.get("researchId") or "")\n'
       '        behind_uid = (prev_data.get("submittedBy") or "")',
       '        _, prev_data, _ = queue[my_idx - 1]\n'
       '        behind_rid = (prev_data.get("researchId") or "")\n'
       '        behind_title = (prev_data.get("topic") or "")[:60]\n'
       '        behind_uid = (prev_data.get("submittedBy") or "")')],
     [T_NEW, T_POS, T_DEFER]),
    ("Q3", "under",
     "⛔ the run id ahead is dropped along with the topic. The id routes and "
     "names nothing — taking it too would break the queue banner's ordering to "
     "buy no privacy at all, which is the over-correction this wave has to "
     "avoid being",
     [('        behind_rid = (prev_data.get("researchId") or "")\n'
       '    return (position, behind_rid, behind_title)',
       '    return (position, behind_rid, behind_title)')],
     [T_NEW, T_POS]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ A stale `__pycache__/*.pyc` served OLD bytecode for three rounds of
        # measurement in this repo. In a harness that rewrites the source between
        # runs it is a kill or a survivor invented out of nothing.
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
