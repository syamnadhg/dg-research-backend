"""Wave 10.10 — can the guards see a research the person deleted or archived
being picked up anyway?

The promise is "a research you deleted can never run again, even if its Resume
was already waiting". It rests on ONE rule, `_pickup_withdrawn`, and on every
pickup path actually asking it: the start listener, the Resume, the idle rescan
(where a Retry lands when every worker is busy), the worker's dequeue, the boot
restore from the disk snapshot, the boot rehydrate and the dead-worker
reconcile. Every mutant below is a way one of those could go back to what it was
while the code still looks like it learned.

The ones that matter most are the quiet ones:

  D1  — a read that FAILS counts as a deletion. Nothing breaks on a healthy
        network; on the first blip somebody's paid, watched run is dropped with
        its only queue document, and nobody is told.
  C2  — the Resume stops asking. That is the defect this wave exists for: a
        Resume that names its run was resumed, and EMAILED, for a research the
        person had deleted.
  C6  — the dequeue lets "missing" run again. Every job passes that line last,
        so it is the backstop for a Resume taken before the deletion landed.
  C8  — "archived" drops off the dequeue's bail list, which is how a research
        archived while queued under the old archive still ran.
  D4  — the rule is widened to "over", which refuses the Resume the recovery
        card offers for a watchdog-stopped run. An over-refusal is a defect too.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED. The tests run as
`sys.executable -m pytest` from the repo root, so `-m` puts this checkout first
on sys.path — which is what makes a worktree measure itself rather than the
editable install the venv points at.

  <venv>/bin/python -u .mutants/wave1010_deleted_mutants.py
  <venv>/bin/python -u .mutants/wave1010_deleted_mutants.py D1 C2
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_deleted_research_never_runs_1010.py "
          "tests/test_flip_stage_0806.py "
          "tests/test_member_run_ownership_109.py "
          "tests/test_owner_control_only_109.py "
          "tests/test_resume_drop_writeback_108.py "
          "tests/test_pending_queue_keeps_nothing_109.py")
RESEARCH = "research.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the rule ───────────────────────────────────────────────────────
RULE_READ = ('        snap = (_firebase_db.collection("users").document(uid)\n'
             '                .collection("researches").document(rid).get())\n'
             "        # Inside the try: a snapshot")
RULE_FAILED = ('                f"not a deletion", "WARN")\n'
               "        return None, None")
RULE_GONE = ('        _log_pickup_stand_down(where, rid, "deleted")\n'
             '        return "deleted", None')
RULE_ARCHIVED = "    if record.get(\"status\") == _PICKUP_WITHDRAWN_STATUS:"
RULE_TAKE = ('        return "archived", record\n'
             "    return None, record")
LINE_SCOPE = ("    with _machine_log_scope():\n"
              "        log(f\"[pickup:{where}] {str(research_id or '')[:8]}… was {reason} — \"")
UNREADABLE_SCOPE = ("    except Exception as err:\n"
                    "        with _machine_log_scope():\n"
                    '            log(f"[pickup:{where}] {rid[:8]}… record unreadable "')

# ── anchors: the consumers ──────────────────────────────────────────────────
START = ('            _withdrawn, _rd_found = _pickup_withdrawn(uid, research_id, "start")\n'
         "            if _withdrawn:")
RESUME = ('                _withdrawn, _ = _pickup_withdrawn(target_uid, target_rid, "resume")\n'
          "                if _withdrawn:")
RESUME_DELETE = ("                if _withdrawn:\n"
                 "                    try: doc.reference.delete()\n"
                 "                    except Exception: pass\n"
                 "                    continue")
RESCAN = ('                _pickup_withdrawn, uid, research_id, "idle-rescan")\n'
          "            if _withdrawn:")
RESCAN_DELETE = ('                _pickup_withdrawn, uid, research_id, "idle-rescan")\n'
                 "            if _withdrawn:\n"
                 "                try:\n"
                 "                    await asyncio.to_thread(snap.reference.delete)\n"
                 "                except Exception:\n"
                 "                    pass\n"
                 "                continue")
DEQUEUE_MISSING = ('            if flip_outcome == "missing":\n'
                   "                should_run = False")
DEQUEUE_FALLBACK = ("                    if not _snap.exists:\n"
                    '                        flip_outcome = "missing"\n'
                    "                    elif _cur:")
DEQUEUE_BAIL = ("                _PICKUP_WITHDRAWN_STATUS,\n"
                "            }")
RESTORE = ('                             "disk-restore")[0]:')
#: ⛔ Its own `elif`, so wave 10.9's `RESTORE_FORGET` anchor still matches.
RESTORE_SHED = "    elif withdrew:"
REHYDRATE = '                        _pickup_withdrawn, tree_uid, research_id, "rehydrate"))[0]:'
RECONCILE = '                _pickup_withdrawn, tree_uid, research_id, "dead-worker-reconcile"))[0]:'

MUTANTS = [
    # ══ the rule ═══════════════════════════════════════════════════════════
    ("D1", "over", "⛔⛔ a read that FAILS counts as a deletion — the first "
     "network blip drops somebody's paid, watched run with its only queue "
     "document, and nobody is told",
     [(RULE_FAILED, '                f"not a deletion", "WARN")\n'
                    '        return "deleted", None')]),
    ("D2", "under", "⛔⛔ a research with no record is taken — the deleted "
     "research runs, and emails",
     [(RULE_GONE, "        return None, None")]),
    ("D3", "under", "an archived research is taken — the old archive's queued "
     "run starts when its computer comes back",
     [(RULE_ARCHIVED, "    if False:")]),
    ("D4", "over", "⛔ the rule is widened to every run that is OVER, so the "
     "Resume the recovery card offers for a watchdog-stopped or discarded run "
     "is refused",
     [(RULE_ARCHIVED, "    if record.get(\"status\") in TERMINAL_RESEARCH_STATUSES:")]),
    ("D5", "over", "every readable record is withdrawn — nothing is ever "
     "picked up again",
     [(RULE_TAKE, '        return "archived", record\n'
                  '    return "deleted", record')]),
    ("D6", "under", "the rule reads the wrong document — the research id in "
     "the uid's place — so it answers about a record that is never there",
     [(RULE_READ, '        snap = (_firebase_db.collection("users").document(rid)\n'
                  '                .collection("researches").document(rid).get())\n'
                  "        # Inside the try: a snapshot")]),
    ("L1", "under", "⛔ the stand-down line is written into whatever run is "
     "armed — on a shared computer, somebody else's",
     [(LINE_SCOPE, "    if True:\n"
                   "        log(f\"[pickup:{where}] {str(research_id or '')[:8]}… was {reason} — \"")]),
    ("L2", "under", "the unreadable-record line is written into the armed run too",
     [(UNREADABLE_SCOPE, "    except Exception as err:\n"
                         "        if True:\n"
                         '            log(f"[pickup:{where}] {rid[:8]}… record unreadable "')]),

    # ══ one pickup path ignores the rule ═══════════════════════════════════
    ("C1", "under", "the start listener stops asking — a deleted research's "
     "start doc is claimed and its record written",
     [(START, '            _withdrawn, _rd_found = _pickup_withdrawn(uid, research_id, "start")\n'
              "            if False:")]),
    ("C2", "under", "⛔⛔ THE DEFECT: the Resume stops asking, and a research "
     "deleted while its card offered Resume is resumed and emailed",
     [(RESUME, '                _withdrawn, _ = _pickup_withdrawn(target_uid, target_rid, "resume")\n'
               "                if False:")]),
    ("C3", "under", "the Resume stands down but leaves its queue doc, which "
     "replays on every listener attach",
     [(RESUME_DELETE, "                if _withdrawn:\n"
                      "                    continue")]),
    ("C4", "under", "⛔ the idle rescan stops asking — an archived research is "
     "UN-archived by its 'ongoing' write and then runs",
     [(RESCAN, '                _pickup_withdrawn, uid, research_id, "idle-rescan")\n'
               "            if False:")]),
    ("C5", "under", "the rescan stands down but leaves the doc it claimed",
     [(RESCAN_DELETE, '                _pickup_withdrawn, uid, research_id, "idle-rescan")\n'
                      "            if _withdrawn:\n"
                      "                continue")]),
    ("C6", "under", "⛔⛔ the dequeue lets 'missing' run again — the backstop "
     "for a Resume taken before its research was deleted",
     [(DEQUEUE_MISSING, "            if False:\n"
                        "                should_run = False")]),
    ("C7", "under", "⛔ the dequeue's fallback read calls a record that is GONE "
     "unreadable again, and runs it",
     [(DEQUEUE_FALLBACK, "                    if _cur:")]),
    ("C8", "under", "⛔⛔ 'archived' drops off the dequeue's bail list — the "
     "original defect for a run archived while it waited",
     [(DEQUEUE_BAIL, "            }")]),
    ("C9", "under", "the boot restore stops asking — a deleted research's "
     "snapshot entry is re-offered at every boot",
     [(RESTORE, '                             "disk-restore")[0] and False:')]),
    ("C10", "under", "the boot restore asks but never sheds — the withdrawn "
     "entry stays in the file for good",
     [(RESTORE_SHED, "    elif False:")]),
    ("C11", "under", "the rehydrate stops asking — an archive made since the "
     "query is undone by the Resume mark",
     [(REHYDRATE, '                        _pickup_withdrawn, tree_uid, research_id, '
                  '"rehydrate"))[0] and False:')]),
    ("C12", "under", "the dead-worker reconcile stops asking — same undoing",
     [(RECONCILE, '                _pickup_withdrawn, tree_uid, research_id, '
                  '"dead-worker-reconcile"))[0] and False:')]),

    # ══ a failed read counts as deleted, at a consumer ══════════════════════
    ("F1", "over", "⛔⛔ the start listener treats an unreadable record as gone "
     "and drops the start doc",
     [(START, '            _withdrawn, _rd_found = _pickup_withdrawn(uid, research_id, "start")\n'
              "            if _withdrawn or _rd_found is None:")]),
    ("F2", "over", "⛔⛔ the Resume treats an unreadable record as gone — every "
     "Resume on a flaky network is thrown away",
     [(RESUME, '                _withdrawn, _ = _pickup_withdrawn(target_uid, target_rid, "resume")\n'
               "                if _withdrawn or _ is None:")]),
]


def _path(fname: str) -> Path:
    return ROOT / fname


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 600


def green():
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q",
             "-p", "no:cacheprovider", "-rs"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it. No "N passed" summary
    # at all (a collection error, an import that died) is not green — for the
    # baseline that stops the run, and for a mutant it is a kill.
    summary = [ln for ln in out.splitlines() if re.search(r"\d+ passed", ln)]
    if not summary:
        return False
    return " failed" not in summary[-1] and " error" not in summary[-1]


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    MUTANTS = [(*m, RESEARCH)[:5] for m in MUTANTS]
    files = sorted({m[4] for m in MUTANTS})
    ORIGINALS = {f: _path(f).read_text(encoding="utf-8") for f in files}

    def restore():
        for f, t in ORIGINALS.items():
            _path(f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    if not green():
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    faults = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, why, edits, fname in selected:
        path = ROOT / fname
        original = ORIGINALS[fname]
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as e:
                raise AssertionError(f"mutant does not parse: {e}")
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}", flush=True)
            else:
                print(f"  {mid}  ✓ killed", flush=True)
        except AssertionError as e:
            faults.append(mid)
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}", flush=True)
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if _path(f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed")
    if faults:
        print("⚠ HARNESS FAULT(S) — measured nothing, counted out: " + ", ".join(faults))
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if survivors or faults:
        sys.exit(1)
    print("clean.\n")
