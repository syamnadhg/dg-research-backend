"""Mutation harness for Wave 8 step A — who a run is attributable to.

⛔⛔ WHAT THIS REPLACED, AND WHY IT MATTERED. A run's `meta.json` recorded a
`submitterUid` taken from the queue document's `uid` field. `firestore.rules`
pins `submittedBy == request.auth.uid` on the device queue and says NOTHING at
all about `uid` — so the value being stamped was a claim by a device member, not
a verified identity. That was tolerable while the field was advisory. Wave 8
turns it into a PERMISSION: whose support bundle may carry this run. A permission
may not rest on an unpinned field, so attribution is now granted only when the
pinned writer and the executing tree name the same person.

⭐⭐ THE FAILURE DIRECTION IS THE WHOLE DESIGN. Every ambiguity resolves to
"attributable to nobody", never to a guess:

    local      no cloud identity at all (a --resume or topic run)
    unclaimed  a tree, no pinned writer — every run on disk today, and every
               run any shipped build has ever written
    disputed   both present and different, or a writer with no tree

The `over` mutants below are the ones that matter most: each is a plausible
"be helpful" reading that resolves an ambiguity toward MORE collection, which is
the one direction this must never fail in.

⛔ AND ONE GUARD IS DELIBERATELY START-ONLY. The owner-control path writes
`uid: <sharer>` with `submittedBy: <owner>` on purpose, and it is live — on a
`cancel` document. A blanket equality clause would break stop/cancel, so O3
restores exactly that over-correction.

    python .mutants/wave8_attribution_0824_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_CAP = "tests/test_run_log_capture_0818.py"
# ⛔ THE SIBLING FILES WHOSE PROPERTIES THIS SOURCE OWNS. A scope-limited harness
# in this repo has reported "real suite gaps" that were nothing but its own
# blindness three separate times. The row shape this wave changes is read by the
# bundle builder, so the bundle and clear suites are measured alongside.
T_BUNDLE = "tests/test_log_bundle_0818.py"
T_CLEAR = "tests/test_clear_local_logs_0818.py"
T_CMD = "tests/test_send_logs_command_0818.py"
ALL = [T_CAP, T_BUNDLE, T_CLEAR, T_CMD]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

_RESOLVE_AGREE = """    if claim and claim == tree:
        return claim, "queue\""""

_RESOLVE_UNCLAIMED = """    if not claim:
        return None, "unclaimed\""""

_RESOLVE_LOCAL = """    if not tree and not claim:
        return None, "local\""""

_RESOLVE_DISPUTED = """    return None, "disputed\""""

_SINK_RESOLVE = """        self.submitter_uid, self.submitter_source = _resolve_run_submitter(
            self.submitted_by, self.claimed_by)"""

_CAP_CLAIM_STORE = """        self.claimed_by = claimed_by"""

_WRAP_POP = """    _claimed = kwargs.pop("_submitted_by", None)"""

_CONFLICT_BOTH = """    if uid and claimed and uid != claimed:
        return uid, claimed"""

_CONFLICT_STRIP = """    uid = str((data or {}).get("uid") or "").strip()
    claimed = str((data or {}).get("submittedBy") or "").strip()"""

_LISTENER_REFUSE = """            if _start_doc_identity_refused(data, "start-listener"):"""

_RESCAN_REFUSE = """            if _start_doc_identity_refused(d, "idle-rescan"):"""

_LISTENER_DELETE = """            if _start_doc_identity_refused(data, "start-listener"):
                try:
                    doc.reference.delete()
                except Exception:
                    pass
                continue"""

_REFUSE_LOG = """    log(f"[{where}] refusing start — identity fields disagree """

_REFUSE_RETURN = """    conflict = _start_doc_identity_conflict(data)
    if conflict is None:
        return False"""

_LISTENER_ENQ = """                         "submitted_by": sb},"""

_RESCAN_ENQ = """                "submitted_by": str(d.get("submittedBy") or "").strip(),"""

_DEQUEUE = """                                     _submitted_by=job.get("submitted_by"),"""

_RETRY = """                           _submitted_by=_run_submitted_by(),"""

_RUN_SUBMITTED_BY = """    sink = _active_run_sink()
    return getattr(sink, "claimed_by", None) if sink is not None else None"""

_INDEX_PRIVATE = """_INDEX_PRIVATE_KEYS = ("dir", "submitterUid", "submitterSource")"""

_ROW_KEYS = """            "submitterUid": meta.get("submitterUid"),
            "submitterSource": meta.get("submitterSource") or "unknown","""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the resolver: the policy itself ═══════════════════════════════
    ("R1", "over", "⛔⛔ THE DEFECT THIS WAVE EXISTS TO REMOVE, restored: the "
     "unpinned tree uid alone attributes the run, so a device member's claim "
     "decides whose bundle may carry it",
     [(_RESOLVE_UNCLAIMED, '    if not claim:\n        return tree, "queue"')],
     [T_CAP]),
    ("R2", "over", "⛔⛔ a disagreement resolves to the WRITER, so someone who "
     "names a tree they do not own collects that tree's run",
     [(_RESOLVE_DISPUTED, '    return claim, "queue"')],
     [T_CAP]),
    ("R3", "over", "a disagreement resolves to the TREE — the other half of the "
     "same over-collection, and the more tempting one because the tree is where "
     "the run actually executed",
     [(_RESOLVE_DISPUTED, '    return tree, "queue"')],
     [T_CAP]),
    ("R4", "under", "agreement stops granting anything, so no run is ever "
     "attributable and the whole per-run picker is empty for everyone",
     [(_RESOLVE_AGREE, '    if False:\n        return claim, "queue"')],
     [T_CAP]),
    ("R5", "under", "⛔ the three kinds of nothing collapse into one, so a "
     "reader cannot tell 'this run had no cloud identity' from 'two people "
     "disagreed about it' — the distinction the null exists to carry",
     [(_RESOLVE_UNCLAIMED, '    if not claim:\n        return None, "local"')],
     [T_CAP]),
    ("R6", "over", "a local run is attributed to the empty string rather than "
     "to nobody, which compares equal to a missing uid downstream",
     [(_RESOLVE_LOCAL, '    if not tree and not claim:\n        return "", "local"')],
     [T_CAP]),
    ("R7", "over", "whitespace stops being stripped, so ' U1 ' and 'U1' are two "
     "different people and an agreement reads as a dispute",
     [(_CONFLICT_STRIP,
       '    uid = str((data or {}).get("uid") or "")\n'
       '    claimed = str((data or {}).get("submittedBy") or "")')],
     [T_CAP]),

    # ══ the capture wiring ════════════════════════════════════════════
    ("C1", "over", "the resolver is bypassed and the tree uid is stamped "
     "directly — the pre-Wave-8 behaviour with the new field names on it",
     [(_SINK_RESOLVE,
       "        self.submitter_uid, self.submitter_source = (\n"
       '            self.submitted_by, "queue" if self.submitted_by else "local")')],
     [T_CAP]),
    ("C2", "under", "the capture drops the pinned writer on the way in, so "
     "EVERY run resolves to unclaimed and nobody can send anything",
     [(_CAP_CLAIM_STORE, "        self.claimed_by = None")],
     [T_CAP]),
    ("C3", "over", "⛔ the wrapper FORWARDS the private kwarg instead of "
     "popping it — a TypeError on every queued run, because run_pipeline has no "
     "such parameter",
     [(_WRAP_POP, '    _claimed = kwargs.get("_submitted_by", None)')],
     [T_CAP]),
    ("C4", "under", "the crash retry stops carrying the claim, so attempt 2 — "
     "the attempt most likely to be worth sending — is attributable to nobody",
     [(_RETRY, "                           _submitted_by=None,")],
     [T_CAP]),
    ("C5", "over", "⛔ THE TEMPTING WRONG SOURCE for the retry: the process-wide "
     "global. It holds the executing TREE, is bound after the sink is written, "
     "and survives between runs",
     [(_RUN_SUBMITTED_BY, '    return _RUN_SUBMITTER.get("uid")')],
     [T_CAP]),

    # ══ the claim sites ═══════════════════════════════════════════════
    # ⛔⛔ RE-ANCHORED 2026-08-24, AND THE RE-ANCHOR IS THE LESSON. Both of these
    # SURVIVED their first run: the mutant left the guard's CALL in place and
    # neutered only its branch, and the test counted calls. A call is not a
    # branch. The test now walks the AST for an `If` whose condition IS the
    # guard, and the duplicated refusal sentence moved into the guard itself.
    ("O1", "under", "⛔⛔ the start listener stops refusing a divergent doc, so a "
     "run executes in a tree its writer does not own",
     [(_LISTENER_REFUSE, "            if False:")],
     [T_CAP]),
    ("O2", "under", "⛔⛔ only the LISTENER refuses. The idle rescan sweeps up "
     "exactly the documents the listener declined, so the refusal becomes a "
     "one-minute delay",
     [(_RESCAN_REFUSE, "            if False:")],
     [T_CAP]),
    ("O1b", "under", "the listener refuses but LEAVES THE DOCUMENT, so the same "
     "divergent doc is re-delivered on every listener attach forever",
     [(_LISTENER_DELETE,
       '            if _start_doc_identity_refused(data, "start-listener"):\n'
       "                continue")],
     [T_CAP]),
    ("O1c", "under", "⛔ the refusal goes SILENT — a queue doc that vanishes with "
     "no line is indistinguishable from one that was never written, which is the "
     "exact shape this repo keeps finding",
     [(_REFUSE_LOG, "    if False: log(f\"[{where}] refusing start — identity fields disagree \"")],
     [T_CAP]),
    ("O1d", "over", "the guard refuses EVERY start doc, not just a divergent one "
     "— the machine stops running research at all",
     [(_REFUSE_RETURN,
       "    conflict = _start_doc_identity_conflict(data)\n"
       "    if False:\n        return False")],
     [T_CAP]),
    ("O3", "over", "⛔⛔ ABSENT IS TREATED AS DISAGREEING. Every legacy start doc "
     "— and every doc written by a build older than this one — is refused, so "
     "the guard breaks the runs it was never about",
     [(_CONFLICT_BOTH,
       "    if uid != claimed:\n        return uid, claimed")],
     [T_CAP]),
    ("O4", "under", "the start listener's enqueue drops the pinned writer, so "
     "the guard passes and the run is still unattributable",
     [(_LISTENER_ENQ, '                         "submitted_by": ""},')],
     [T_CAP]),
    ("O5", "under", "the idle rescan's enqueue drops it — the same hole on the "
     "path that handles a doc the listener missed",
     [(_RESCAN_ENQ, '                "submitted_by": "",')],
     [T_CAP]),
    ("O6", "under", "the dequeue never reads it off the job, so every claim "
     "site can be correct and the folder still records nobody",
     [(_DEQUEUE, "                                     _submitted_by=None,")],
     [T_CAP]),

    # ══ the archive boundary ══════════════════════════════════════════
    ("I1", "over", "⛔⛔ the submitter uid ships INSIDE the support bundle's "
     "index — an account identifier for every run in the archive, disclosed to "
     "us under a consent screen that names no such thing",
     [(_INDEX_PRIVATE, '_INDEX_PRIVATE_KEYS = ("dir",)')],
     [T_CAP, T_BUNDLE]),
    ("I2", "under", "the row stops carrying the submitter, so the server-side "
     "intersection has nothing to intersect against and must either fail every "
     "selection or trust the client's",
     [(_ROW_KEYS,
       '            "submitterUid": None,\n'
       '            "submitterSource": "unknown",')],
     [T_CAP]),
    # ⛔ RE-MEASURED 2026-08-24: this survived until a test wrote a real
    # pre-Wave-8 meta.json — the shape of every run folder in the field.
    ("I3", "over", "a meta with no source key reads as a QUEUED run rather than "
     "an unknown one, which is the one value that grants attribution",
     [(_ROW_KEYS,
       '            "submitterUid": meta.get("submitterUid"),\n'
       '            "submitterSource": meta.get("submitterSource") or "queue",')],
     [T_CAP]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ A stale `__pycache__/*.pyc` served OLD bytecode for three rounds of
        # measurement in this repo. In a harness that rewrites the source between
        # every run, a cached module is not a nuisance — it is a kill or a
        # survivor invented out of nothing.
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
