"""Wave 10.10, lane machine-runs — can the tests see each decision go back?

Five tasks, each a decision the research computer makes about a run's files or
lines, and each with a way to quietly go back to what it was:

  O*  a deleted research's folders leave within minutes when it ran today, and
      the hour still holds for every older run (the read bill);
  D*  the cloud-delivery thread's lines stay out of whichever run is armed
      next, and a private run's route answer stays out of the owner's log
      (through the shipped `_quote_reply`, since the integration);
  T*  the terminal log keeps what a prompt holds back; the Linux health check
      names a fix once; the local run list tells an ongoing run from a finished
      one; a terminal resume of a private run is refused; the lease forgets a
      private run the web has already removed;
  F*  the loops that explain a run's fate always reach the owner's log;
  S*  the local serve API describes a private run without its subject.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written, and every file is restored and
compared after the run.

⛔ THE SUMMARY LINE DECIDES, NEVER THE EXIT CODE.

  <venv>/bin/python -u .mutants/wave1010_runs_mutants.py
  <venv>/bin/python -u .mutants/wave1010_runs_mutants.py O1 O4
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

T_SWEEP = "tests/test_incognito_teardown_109.py"
T_COST = "tests/test_orphan_sweep_read_cost_0920.py"
T_HANDOFF = "tests/test_cloud_handoff_record_108.py"
T_SCOPE = "tests/test_machine_log_scope_0824.py"

# ══ task 1: the recency tier ══════════════════════════════════════════════
TIER = ("    if (last_write_at is not None\n"
        "            and abs(float(now) - float(last_write_at)) < _ORPHAN_RECENT_WINDOW_SEC):\n"
        "        return True")
WINDOW = "_ORPHAN_RECENT_WINDOW_SEC = 24 * 60 * 60"
WROTE_AT = "                        _wrote_at = delivery_path.stat().st_mtime"
TIER_CALL = "                            rid, ORPHAN_RECHECK_SEC, _wrote_at):"

# ══ task 2: the delivery thread's lines ═══════════════════════════════════
# ⚠ 2026-09-23 (integration onto wave 10.9's last repair): the branch's own
# log-only `why_logged` is gone. The shipped `_quote_reply` already cuts the
# reply from `why` itself for a private run, so every line — logged, noted,
# recorded — says the status only, and a second variable for the log half
# could only ever equal the first. D2-D4 now measure that one gate from this
# lane's tests; D5-D8 put the route's raw answer back into one line each.
DRIVE_MARK = "    @_machine_logged\n    def _drive():"
REPLY_GATE = "    _quote_reply = not _is_incognito_research(research_id)"
LOG_FOLLOWUP = "                    f\"without running phase 5 ({why}) — asking for phase 5 alone \""
LOG_RAN = "            log(f\"FE trigger: BE-driven P4/P5 — the cloud ran the chain ✓ ({why}) \""
LOG_RETRY = "        log(f\"FE trigger: BE-driven P4/P5 attempt {_attempt} did not land ({why}) \""
LOG_GAVE_UP = "        f\"({verdict}: {why}) rid={research_id[:8]}… — recording the failure on \""
#: This lane's own delivery pins, by node id — so D2-D8 prove THEY still
#: measure the gate, not only the shipped round's pins in the same file.
T_HANDOFF_1010 = [
    T_HANDOFF + "::test_the_next_runs_folder_gets_none_of_the_drives_lines",
    T_HANDOFF + "::test_a_private_runs_route_answer_stays_out_of_the_machine_log",
    T_HANDOFF + "::test_an_ordinary_runs_route_answer_is_still_logged",
    T_HANDOFF + "::test_every_line_the_ladder_logs_for_a_private_run_names_the_status_only",
]
_RAW = "{str(_text)[:160]}"

MUTANTS = [
    # ── task 1 ────────────────────────────────────────────────────────────
    ("O1", "under", "⛔⛔ the tier is gone, so a research deleted on the day it "
     "ran keeps its folders and logs for up to an hour again",
     [(TIER, "    if False:\n        return True")], [T_SWEEP, T_COST]),
    ("O2", "over", "⛔⛔ every folder is recent, which is the 288-reads-a-day "
     "bill the hourly memo was written to stop",
     [(TIER, "    if True:\n        return True")], [T_SWEEP, T_COST]),
    ("O3", "over", "⛔ a file stamped ahead by a clock that moved is recent for "
     "as long as the clock is behind — days of reads",
     [(TIER, "    if (last_write_at is not None\n"
             "            and float(now) - float(last_write_at) < _ORPHAN_RECENT_WINDOW_SEC):\n"
             "        return True")], [T_SWEEP, T_COST]),
    ("O4", "under", "⛔⛔ THE CONSUMER IGNORES THE RULE: the helper is perfect and "
     "the sweep never hands it the time, so every folder stays hourly",
     [(TIER_CALL, "                            rid, ORPHAN_RECHECK_SEC):")],
     [T_SWEEP, T_COST]),
    ("O5", "under", "the sweep reads the DIRECTORY's time, which moves only when "
     "an entry is added or removed — a finished run looks old at once",
     [(WROTE_AT, "                        _wrote_at = d.stat().st_mtime")],
     [T_SWEEP, T_COST]),
    ("O6", "under", "the window shrinks to an hour, so a run from this morning "
     "is back on the hourly memo by lunch",
     [(WINDOW, "_ORPHAN_RECENT_WINDOW_SEC = 60 * 60")], [T_SWEEP, T_COST]),
    ("O7", "over", "an unknown time counts as recent, so a folder the sweep "
     "cannot stat is read on every tick for ever",
     [(TIER, "    if (last_write_at is None\n"
             "            or abs(float(now) - float(last_write_at)) < _ORPHAN_RECENT_WINDOW_SEC):\n"
             "        return True")], [T_SWEEP, T_COST]),

    # ── task 2 ────────────────────────────────────────────────────────────
    ("D1", "under", "⛔⛔ THE LEAK: the delivery thread is not a machine line, so "
     "the next person's run collects this run's id and the route's answer in "
     "its run.log and support bundle",
     [(DRIVE_MARK, "    def _drive():")], [T_HANDOFF, T_SCOPE]),
    ("D2", "under", "⛔⛔ a private run's route answer — an email error about "
     "this very research — rides the machine line into backend.log",
     [(REPLY_GATE, "    _quote_reply = True")], T_HANDOFF_1010),
    ("D3", "over", "every run's route answer is cut from the log, so the first "
     "thing a stuck-run report is read from says only a status code",
     [(REPLY_GATE, "    _quote_reply = False")], T_HANDOFF_1010),
    ("D4", "under", "the drive asks about the account instead of the run, so a "
     "private run is logged like any other",
     [(REPLY_GATE, "    _quote_reply = not _is_incognito_research(uid)")],
     T_HANDOFF_1010),
    ("D5", "under", "the follow-up line quotes the route's raw answer again",
     [(LOG_FOLLOWUP, "                    f\"without running phase 5 ({why} " + _RAW
                     + ") — asking for phase 5 alone \"")], T_HANDOFF_1010),
    ("D6", "under", "the 'ran the chain' line quotes the route's raw answer again",
     [(LOG_RAN, "            log(f\"FE trigger: BE-driven P4/P5 — the cloud ran the chain ✓ ({why} "
                + _RAW + ") \"")], T_HANDOFF_1010),
    ("D7", "under", "the retry line quotes the route's raw answer again",
     [(LOG_RETRY, "        log(f\"FE trigger: BE-driven P4/P5 attempt {_attempt} did not land ({why} "
                  + _RAW + ") \"")], T_HANDOFF_1010),
    ("D8", "under", "the give-up line quotes the route's raw answer again",
     [(LOG_GAVE_UP, "        f\"({verdict}: {why} " + _RAW
                    + ") rid={research_id[:8]}… — recording the failure on \"")],
     T_HANDOFF_1010),
]


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 600


def green(tests):
    try:
        r = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", *tests, "-q",
             "-p", "no:cacheprovider"],
            cwd=ROOT, env=ENV, capture_output=True, text=True,
            timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    summary = [ln for ln in out.splitlines()
               if re.search(r"\d+ (passed|failed|error)", ln)]
    if not summary:
        raise AssertionError("no pytest summary line — the run died before it "
                             "finished:\n" + out[-800:])
    last = summary[-1]
    return " failed" not in last and " error" not in last and "passed" in last


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep
# EXECUTES every harness in this directory to read its table.
if __name__ == "__main__":
    MUTANTS = [(*m, RESEARCH)[:6] for m in MUTANTS]
    files = sorted({m[5] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in files}

    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    selected = [m for m in MUTANTS if not only or m[0] in only]
    baseline = sorted({t for m in selected for t in m[4]})
    print("baseline… ", end="", flush=True)
    if not green(baseline):
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors, faults = [], []
    for mid, direction, why, edits, tests, fname in selected:
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
            if green(tests):
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
        if (ROOT / f).read_text(encoding="utf-8") != t:
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
