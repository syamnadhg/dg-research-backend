"""Wave 10.10, lane machine-runs — can the tests see each decision go back?

Five tasks, each a decision the research computer makes about a run's files or
lines, and each with a way to quietly go back to what it was:

  O*  a deleted research's folders leave within minutes when it ran today, and
      the hour still holds for every older run (the read bill);
  D*  the cloud-delivery thread's lines stay out of whichever run is armed
      next, and a private run's route answer stays out of the owner's log;
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

# ══ task 1: the recency tier ══════════════════════════════════════════════
TIER = ("    if (last_write_at is not None\n"
        "            and abs(float(now) - float(last_write_at)) < _ORPHAN_RECENT_WINDOW_SEC):\n"
        "        return True")
WINDOW = "_ORPHAN_RECENT_WINDOW_SEC = 24 * 60 * 60"
WROTE_AT = "                        _wrote_at = delivery_path.stat().st_mtime"
TIER_CALL = "                            rid, ORPHAN_RECHECK_SEC, _wrote_at):"

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
