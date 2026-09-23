"""Wave 10.10, repair 1 — can the guards see each cross-verify fix undone?

Every mutant below reverts ONE fix from the repair round after 10.10's
cross-verify, or over-corrects it. The effort caption, the effort state, the
"not found" line and the two pickers' step-back rules live in
`wave1010_models_mutants.py` (E9, E10, E18, E19, R16, R19, R20, G7, G8, P7, P8),
next to the mutants they sit beside.

  A1/A2 — the alert rewrite: the drafted TITLE reaches the card again (the web
          then shows a parked agent as "retrying automatically, no action
          needed", or loses the "stopped:" evidence headline); or the rewrite
          quietly changes nothing at all.
  T1/T2 — the Chrome crash card's title loses the "stopped:" shape, the only
          one the web shows as written; it reads "Hit a snag … retrying".
  U1-U3 — a failed record read at pickup: the duplicate guard is skipped again
          (the sibling's research runs twice), widened to readable records
          (a waiting run is dropped for a lock), or matches ANY sibling's lock.
  O1-O3 — the title, summary and phase-3 save threads start without the run's
          context again, so their late lines land in the next run's folder.
  W1    — the incognito id-shape pin skips on a named checkout that lacks
          `src/lib/incognito.ts` instead of failing.

⛔ A KILL IS A FAILED OR ERRORED TEST, NEVER A SKIP. Fewer passes with more
skips is counted as a survivor: a pin that stops running looks exactly like one
that caught something.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED, from the checkout being measured:

  <venv>/bin/python -u .mutants/wave1010_repair1_mutants.py
  <venv>/bin/python -u .mutants/wave1010_repair1_mutants.py A1 U1
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
RESEARCH = "research.py"

ALERTS = ["tests/test_alert_ai_copy_955.py"]
CRASH = ["tests/test_crash_card_chrome_1010.py"]
PICKUP = ["tests/test_failed_read_keeps_the_run_1010.py"]
#: Only the three late-thread consumers: the rule tests above them in the file
#: set their own origin and cannot see a dispatch site.
ORIGIN = ["tests/test_log_folder_origin_1010.py", "-k", "late_thread_of_the_run"]
INCOG_T = "tests/test_incognito_capability_109.py"
INCOG = [INCOG_T]

# ── anchors ─────────────────────────────────────────────────────────────────
REEMIT = '            facts={"title": base_title, "details": new_details},'
CRASH_STREAK = ('                _card_error = ("Research stopped: Chrome kept closing" '
                'if _closes > 1')
CRASH_ONCE = '                               else "Research stopped: Chrome closed unexpectedly")'
DUP_GATE = '                if _rd_status == "ongoing" or _rd_found is None:'
DUP_SCAN = ('                    _siblings = _scan_sibling_locks_for_research(\n'
            '                        research_id, WORKER_ID\n'
            '                    )')
TITLE_THREAD = ('        _threading.Thread(target=_log_contextvars.copy_context().run, '
                'args=(_worker,),\n'
                '                          name="research-title-refresh", daemon=True).start()')
SUMMARY_THREAD = ('        _threading.Thread(target=_log_contextvars.copy_context().run, '
                  'args=(_worker,),\n'
                  '                          name="research-summary", daemon=True).start()')
SAVE_THREAD = ('            target=_log_contextvars.copy_context().run,\n'
               '            args=(save_meta, queue_dir, topic, phase),')
WEB_FINDER = '    return require_web_repo("the four copies of the incognito id shape")\n'

MUTANTS = [
    # ══ 1. the alert rewrite never changes the title ═══════════════════════
    ("A1", "under", "⛔⛔ the drafted title reaches the card: 'Claude is overloaded "
     "right now' turns a parked agent into 'retrying automatically, no action "
     "needed', and a rephrased evidence headline becomes 'Hit a snag … retrying'",
     [(REEMIT, '            facts={"title": _drafted_title_unused, "details": new_details},')],
     RESEARCH, ALERTS),
    ("A2", "over", "the rewrite keeps the plain body too — it changes nothing, "
     "and every title test above would pass against a rewrite that never ran",
     [(REEMIT, '            facts={"title": base_title, "details": base_details},')],
     RESEARCH, ALERTS),

    # ══ 2. the Chrome crash card's title reaches the screen ════════════════
    ("T1", "under", "⛔ 'Chrome kept closing' again — the web shows 'Hit a snag at "
     "the research step — retrying.' above a body saying we stopped",
     [(CRASH_STREAK, '                _card_error = ("Chrome kept closing" if _closes > 1')],
     RESEARCH, CRASH),
    ("T2", "under", "the single-close title loses the 'stopped:' shape",
     [(CRASH_ONCE, '                               else "Chrome closed unexpectedly")')],
     RESEARCH, CRASH),

    # ══ 5. a failed read never runs a research twice ═══════════════════════
    ("U1", "under", "⛔⛔ the duplicate guard waits for a status again: a failed read "
     "takes a duplicate start doc and a second worker runs the sibling's research",
     [(DUP_GATE, '                if _rd_status == "ongoing":')],
     RESEARCH, PICKUP),
    ("U2", "over", "⛔ a readable waiting run is dropped for a lock — a sibling "
     "still closing an earlier run of it costs the person their restart",
     [(DUP_GATE, "                if True:")],
     RESEARCH, PICKUP),
    ("U3", "over", "any sibling's lock drops this job, whatever research it holds",
     [(DUP_SCAN, '                    _siblings = _scan_sibling_locks_for_research(\n'
                 '                        "", WORKER_ID\n'
                 '                    )')],
     RESEARCH, PICKUP),

    # ══ 6. the run's late threads keep its log origin ══════════════════════
    ("O1", "under", "⛔ the title refresh starts with an empty context: its late "
     "line lands in the next run's folder",
     [(TITLE_THREAD, '        _threading.Thread(target=_worker,\n'
                     '                          name="research-title-refresh", '
                     'daemon=True).start()')],
     RESEARCH, ORIGIN),
    ("O2", "under", "⛔ the summary starts with an empty context",
     [(SUMMARY_THREAD, '        _threading.Thread(target=_worker,\n'
                       '                          name="research-summary", '
                       'daemon=True).start()')],
     RESEARCH, ORIGIN),
    ("O3", "under", "⛔ the phase-3 save starts with an empty context: its WARN and "
     "heal lines land in the next run's folder",
     [(SAVE_THREAD, '            target=save_meta,\n'
                    '            args=(queue_dir, topic, phase),')],
     RESEARCH, ORIGIN),

    # ══ 7. a named-but-wrong web checkout fails the id-shape pin ═══════════
    ("W1", "under", "⛔ the id-shape pin SKIPS on a named checkout without "
     "incognito.ts — the only check of the four copies reads as 'skipped'",
     [(WEB_FINDER, '    web = require_web_repo("the four copies of the incognito id shape")\n'
                   '    if not (web / _HALF).exists():\n'
                   '        pytest.skip("the web half of this wave is not in the checkout")\n'
                   '    return web\n')],
     INCOG_T, INCOG),
]


# ── the runner ──────────────────────────────────────────────────────────────

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 300
_COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected)")


def summary(tests):
    """pytest's own tally for `tests`, from its SUMMARY LINE — or a fault."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the tests ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    lines = [ln for ln in out.splitlines()
             if re.search(r" in [\d.]+s", ln) and _COUNT.search(ln)]
    if not lines:
        raise AssertionError("pytest printed no summary line — the run did not happen:\n"
                             + out[-1500:])
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for n, kind in _COUNT.findall(lines[-1]):
        if kind.startswith("error"):
            counts["error"] = int(n)
        elif kind in counts:
            counts[kind] = int(n)
    return counts


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`.
if __name__ == "__main__":
    only = set(sys.argv[1:])
    selected = [m for m in MUTANTS if not only or m[0] in only]
    files = sorted({m[4] for m in selected})
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in files}

    baselines = {}
    print("baseline… ", end="", flush=True)
    for tests in sorted({tuple(m[5]) for m in selected}):
        try:
            got = summary(list(tests))
        except AssertionError as e:
            print(f"⛔ BASELINE FAULT for {' '.join(tests)}: {e}")
            sys.exit(2)
        if got["failed"] or got["error"] or got["skipped"] or not got["passed"]:
            print(f"⛔ BASELINE NOT CLEAN for {' '.join(tests)}: {got} — a skip in "
                  f"the baseline is a pin that measures nothing")
            sys.exit(2)
        baselines[tests] = got
    print("green\n", flush=True)

    survivors, faults = [], []
    for mid, direction, why, edits, fname, tests in selected:
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
            got = summary(tests)
            if got["failed"] or got["error"]:
                print(f"  {mid}  ✓ killed  {got}", flush=True)
            else:
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}  {got}", flush=True)
        except AssertionError as e:
            faults.append(mid)
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}", flush=True)
        finally:
            path.write_text(original, encoding="utf-8")

    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    measured = len(selected) - len(faults)
    over = sum(1 for m in selected if m[1] == "over")
    print(f"\n{measured - len(survivors)}/{measured} killed ({over} over-corrections)")
    if faults:
        print("⚠ HARNESS FAULT(S) — measured nothing, counted out: " + ", ".join(faults))
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if survivors or faults:
        sys.exit(1)
    print("clean.\n")
