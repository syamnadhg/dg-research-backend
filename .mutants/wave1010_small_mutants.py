"""Wave 10.10 — two small machine fixes. Can the tests see either one undone?

1. A RUN'S FOLDER HOLDS ONLY ITS OWN LINES. `_log_write_through` copied every
   line into whichever run folder was armed when it was written, so a private
   run's late line — a copied-context thread still busy after the run ended —
   landed in the NEXT person's folder, which rides that person's support
   bundle. `_line_is_another_runs` now keeps a line with a DIFFERENT origin out.

     O1 — the writer stops asking (the consumer ignores the rule).
     O2 — "no origin" counts as another run: the SDK thread's STOP lines, the
          only account some runs keep of how they ended, leave the folder.
     O5 — a folder whose research is unknown takes a line that is known to
          be one run's.
     O6 — only a PRIVATE origin is kept out, so an ordinary run's late line
          still lands in the next person's folder.

2. A FAILED READ NEVER DROPS A RUN WHOSE QUEUE DOCUMENT IS GONE. The start
   listener and the idle rescan delete the queue document and THEN call the
   enqueue funnel, which refused on any non-403 failure. They now pass
   `take_unreadable=True`; the boot restore and the rehydrate keep refusing.

     T1/T2 — one of the two callers stops passing it (the consumer ignores it).
     T5/T6 — taking is widened to a read that ANSWERED: a deleted or stopped
             research is started anyway.
     T7/T8/T9 — the boot restore or the rehydrate start taking, which is the
             #728 relaunch of a run parked for its person's Resume.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

  <venv>/bin/python -u .mutants/wave1010_small_mutants.py
  <venv>/bin/python -u .mutants/wave1010_small_mutants.py O1 T1
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_log_folder_origin_1010.py "
          "tests/test_failed_read_keeps_the_run_1010.py "
          "tests/test_incognito_backend_log_109.py "
          "tests/test_machine_log_scope_0824.py "
          "tests/test_owner_log_lines_1010.py "
          "tests/test_deleted_research_never_runs_1010.py "
          "tests/test_pending_queue_keeps_nothing_109.py "
          "tests/test_safe_enqueue_stop_sentinel.py "
          "tests/test_multiworker_rehydration_728.py")
RESEARCH = "research.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the folder rule ────────────────────────────────────────────────
WT_ASKS = "    if _line_is_another_runs(sink):\n        return"
NO_ORIGIN = ('    origin = str(_LOG_RUN.get() or "").strip()\n'
             "    if not origin:\n"
             "        return False")
ORIGIN_READ = '    origin = str(_LOG_RUN.get() or "").strip()'
ARMED_READ = '    armed = str(getattr(sink, "research_id", None) or "").strip()'
COMPARE = "    return origin != armed"

# ── anchors: the funnel and its callers ────────────────────────────────────
START_PASSES = "                        take_unreadable=True):"
RESCAN_PASSES = ("# failed read would drop the run for good. See `_safe_enqueue`.\n"
                 "                take_unreadable=True)")
DEFAULT = "                  *, take_unreadable: bool = False) -> bool:"
NO_CLIENT = '        unreadable = "Firestore unavailable"'
EXC_UNREADABLE = '                unreadable = f"Firestore check failed ({type(e).__name__}: {e})"'
GATE = "        if not take_unreadable:"
TAKE_LOG = 'f"reads the record again before anything runs", "WARN")'
EXISTS = ("            if not snap.exists:\n"
          '                log(f"[safe_enqueue:{source}] skipped — research {rid[:24]}… '
          'no longer exists in Firestore", "INFO")')
STATUS = "            if status not in allowed_statuses:"
RESTORE_CALL = ('        if _safe_enqueue(job_queue, j, source="disk-restore",\n'
                '                         allowed_statuses=("queued", "ongoing")):')
REHYDRATE_CALL = '}, source="rehydrate-supervised-auto-resume"):'

MUTANTS = [
    # ══ 1. the folder rule ══════════════════════════════════════════════════
    ("O1", "under", "⛔⛔ the writer stops asking — a private run's late line "
     "lands in the next person's folder and ships in their bundle",
     [(WT_ASKS, "    if False:\n        return")]),
    ("O2", "over", "⛔ a line with NO origin counts as another run's — the SDK "
     "thread's STOP lines leave the folder of the run they ended",
     [(NO_ORIGIN, '    origin = str(_LOG_RUN.get() or "").strip()\n'
                  "    if not origin:\n"
                  "        return True")]),
    ("O3", "under", "the rule never refuses",
     [(COMPARE, "    return False")]),
    ("O4", "over", "the rule refuses everything with an origin — a run loses "
     "its own lines",
     [(COMPARE, "    return True")]),
    ("O5", "under", "a folder whose research is unknown takes a line known to "
     "be one run's",
     [(COMPARE, "    return bool(armed) and origin != armed")]),
    ("O6", "under", "⛔ only a PRIVATE origin is kept out — an ordinary run's "
     "late line still lands in the next person's folder",
     [(COMPARE, "    return origin != armed and _is_incognito_research(origin)")]),
    ("O7", "under", "⛔ the origin is read from the write-time global again — "
     "the defect class 10.9's last repair removed from the console",
     [(ORIGIN_READ, '    origin = str(_fb_research_id or "").strip()')]),
    ("O8", "over", "the folder's research is read from the wrong field",
     [(ARMED_READ, '    armed = str(getattr(sink, "parent_research_id", None) or "").strip()')]),

    # ══ 2. the funnel ═══════════════════════════════════════════════════════
    ("T1", "under", "⛔⛔ the start listener stops passing it — a Firestore "
     "blip drops a paid run whose queue document is already deleted",
     [(START_PASSES, "                        take_unreadable=False):")]),
    ("T2", "under", "⛔⛔ the idle rescan stops passing it — the same drop on "
     "the second claim site",
     [(RESCAN_PASSES, "# failed read would drop the run for good. See `_safe_enqueue`.\n"
                      "                take_unreadable=False)")]),
    ("T3", "under", "⛔ the funnel ignores the caller — a failed read refuses "
     "for everybody, as before",
     [(GATE, "        if True:")]),
    ("T4", "under", "no Firestore client is not treated as unreadable — the "
     "heartbeat dropping the client in the same second drops the run",
     [(NO_CLIENT, '        log(f"[safe_enqueue:{source}] skipped — Firestore '
                  'unavailable", "WARN")\n        return False')]),
    ("T5", "over", "⛔⛔ taking is widened to a record that is GONE — a deleted "
     "research is started from the listener",
     [(EXISTS, "            if not snap.exists and not take_unreadable:\n"
               '                log(f"[safe_enqueue:{source}] skipped — research {rid[:24]}… '
               'no longer exists in Firestore", "INFO")')]),
    ("T6", "over", "⛔⛔ taking is widened past the whitelist — a run somebody "
     "stopped between the claim and the enqueue is started",
     [(STATUS, "            if status not in allowed_statuses and not take_unreadable:")]),
    ("T7", "over", "⛔⛔ the default flips to taking — the boot restore relaunches "
     "a run whose status it could not see (#728)",
     [(DEFAULT, "                  *, take_unreadable: bool = True) -> bool:")]),
    ("T8", "over", "⛔⛔ the boot restore takes a job it could not check",
     [(RESTORE_CALL, '        if _safe_enqueue(job_queue, j, source="disk-restore",\n'
                     '                         allowed_statuses=("queued", "ongoing"),\n'
                     "                         take_unreadable=True):")]),
    ("T9", "over", "⛔ the rehydrate auto-resumes a run it could not check "
     "instead of offering a Resume",
     [(REHYDRATE_CALL, '}, source="rehydrate-supervised-auto-resume", take_unreadable=True):')]),
    ("T10", "over", "a failed read is never unreadable — every caller takes it",
     [(EXC_UNREADABLE, "                pass")]),
    ("T11", "under", "the taking branch says it takes the job and then drops it",
     [(TAKE_LOG, 'f"reads the record again before anything runs", "WARN")\n'
                 "        return False")]),
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
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. No "N passed" summary at all
    # (a collection error, an import that died) is not green — for the
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
