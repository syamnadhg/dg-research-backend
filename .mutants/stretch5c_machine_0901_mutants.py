"""Mutation harness — stretch 5C, the machine half.

⛔⛔ WHAT THIS IS ABOUT. Two of 5C's three items reach onto the disk, and both
turned out to be the same defect wearing different clothes: a rule that was
written down and never enforced.

  item 4  The 30-day retention had NO CLOCK. `_prune_local_logs` had exactly two
          callers — arming a run, and supervisor startup — so the age bound only
          fired as a side effect of the machine being USED. A device up and idle
          kept 45-day-old folders; one that never ran another pipeline kept them
          forever. And the raw tails had no age bound of ANY kind: measured here
          2026-09-01, backend.log 44 MB and backend-2.log 40 MB, both last
          written 27 days earlier, 187 MB of logs, under the byte cap and beyond
          every other reach.
  item 3  P4 and P5 run in the cloud and left NOTHING a support bundle could
          collect. Across six run folders the dispatch string appears ZERO
          times, against 23 in the machine-wide log.

⛔⛔ THE DANGEROUS DIRECTION HERE IS DELETION. Almost every mutant below either
stops something being removed or starts removing the wrong thing, and the second
is far worse: the whole point of matching a run folder on `meta.json`'s
researchId rather than on its name is that the name is a SANITISED id, so a
prefix match can miss the real folder AND hit somebody else's. D1 and D4 are
those two mistakes written out.

⛔ THE OTHER SHAPE IS THE TRIGGER. T1/T2/T3 and C9 all leave the mechanism
perfect and cut the thing that calls it — the mistake this stretch has now made
four times. A prune that nobody runs is the state item 4 found.

⛔ ANCHOR UNIQUENESS IS CHECKED, NOT ASSUMED, and every mutant is compiled before
it is measured: a mutant that cannot parse measures nothing and would otherwise
be reported as a kill.

    python .mutants/stretch5c_machine_0901_mutants.py [ID ...]
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
MUTATED_FILES = (RESEARCH,)

# The two new suites, plus the neighbours that own the seams these mutants touch:
# the run-log capture (folder naming, liveness, the seal), the bundle collector
# and its selection, and the log-noise suite that pins the tail contract. A
# harness that ran only the new files would call collateral damage a kill.
SUITES = (
    "tests/test_retention_0901.py "
    "tests/test_cloud_log_pull_0901.py "
    "tests/test_run_log_capture_0818.py "
    "tests/test_log_noise_0819.py "
    "tests/test_bundle_selection_0824.py "
    "tests/test_bundle_tail_honesty_0822.py"
)
FLOOR = 200

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# These suites touch the real filesystem under tmp_path. A survivor is re-run
# before it is believed rather than reported on one noisy verdict.
SURVIVOR_CONFIRMATIONS = 3

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ══ R — the constants, because the NAMES were half the defect ═══════════

    ("R1", RESEARCH, "under",
     "⛔⛔ THE AGE BOUND BECOMES MEANINGLESS — ten years instead of thirty days, and "
     "nothing anywhere fails. This is the promise the product makes, expressed as one "
     "number, and no other assertion in the tree pins it",
     [("LOCAL_LOG_MAX_AGE_DAYS = 30", "LOCAL_LOG_MAX_AGE_DAYS = 3000")]),

    ("R2", RESEARCH, "under",
     "⛔ THE TAILS DRIFT OFF THE POLICY — bound to their own number instead of the "
     "one the product promises, which is exactly how they came to have no age bound "
     "at all while runs and sessions had one",
     [("LOCAL_TAIL_MAX_AGE_DAYS = LOCAL_LOG_MAX_AGE_DAYS",
       "LOCAL_TAIL_MAX_AGE_DAYS = 3650")]),

    ("R3", RESEARCH, "under",
     "⛔ THE RUN INDEX ADVERTISES MORE RUNS THAN THE DISK KEEPS, so a picker offers a "
     "folder the valve has already deleted — a button that leads nowhere",
     [("RUN_INDEX_MAX = LOCAL_RUNS_DISK_VALVE", "RUN_INDEX_MAX = 500")]),

    # ══ T — the trigger. The bound existed; the guarantee did not ═══════════

    ("T1", RESEARCH, "under",
     "⛔⛔ THE THROTTLE STOPS ADVANCING, so the sweep runs on every 5-second heartbeat: "
     "a directory walk plus a meta.json read per folder, twelve times a minute, forever",
     [("    _prune_next_ms = stamp + int(LOCAL_PRUNE_INTERVAL_SEC) * 1000\n    return True",
       "    return True")]),

    ("T2", RESEARCH, "under",
     "⛔ THE SWEEP NO LONGER STARTS DUE, so a machine coming back after two months waits "
     "another six hours before it cleans up — and one that is restarted often never "
     "reaches the deadline at all",
     [("_PRUNE_START_DUE_MS = 0", "_PRUNE_START_DUE_MS = 9_999_999_999_999")]),

    ("T3", RESEARCH, "under",
     "⛔⛔ THE HEARTBEAT STOPS CALLING THE SWEEP — the exact state item 4 found, with the "
     "30-day code present and unreachable. Every unit test of the bound still passes",
     [("                if _prune_due(_now_ms):", "                if False:")]),

    # ══ A — the raw tails ═══════════════════════════════════════════════════

    ("A1", RESEARCH, "under",
     "⛔⛔ ROLLED TAILS ARE NEVER RETIRED, which is where this started: the largest files "
     "on the disk, and the only ones no code path could reach",
     [("        rolled_at = _raw_tail_started_at(path, now=now_t)\n        if rolled_at >= cutoff:",
       "        rolled_at = _raw_tail_started_at(path, now=now_t)\n        if True:")]),

    ("A2", RESEARCH, "over",
     "⛔⛔⛔ THE TIMER DELETES THE LIVE TAIL. The supervisor holds backend.log open in "
     "append mode, so unlinking it leaves every later write going to an inode with no "
     "name — the hazard `_clear_local_logs` documents as its reason to truncate. The "
     "over-correction that looks like consistency and loses the machine's own log",
     [('        rolled = [p for p in base.iterdir() if p.is_file() and p.name.endswith(".log.1")]',
       "        rolled = [p for p in base.iterdir() if p.is_file()]")]),

    ("A3", RESEARCH, "under",
     "⛔ AN AGED TAIL IS NEVER ROLLED, so the live half of the bound does nothing and only "
     "the already-rolled generation is ever removed",
     [("    if age <= float(max_age_days) * 86400.0:\n        return 0.0",
       "    if True:\n        return 0.0")]),

    ("A4", RESEARCH, "over",
     "⛔⛔ EVERY TAIL IS ROLLED ON EVERY CHECK — three times per boot, so the previous "
     "generation is destroyed before anyone can read it and a support bundle carries "
     "one boot's worth of log",
     [("    if age <= float(max_age_days) * 86400.0:\n        return 0.0",
       "    if False:\n        return 0.0")]),

    ("A5", RESEARCH, "under",
     "⛔ AN AGE ROLL DOES NOT RESTART THE CLOCK, so the marker keeps describing a "
     "generation that no longer exists and the next check rolls a file that is seconds old",
     [("    _begin_raw_tail_generation(p, now=now_t)\n    return float(age)",
       "    return float(age)")]),

    ("A6", RESEARCH, "under",
     "⛔⛔ A SIZE ROLL DOES NOT RESTART THE CLOCK — the cross-path one. Two rotations "
     "share one marker, so a brand-new file inherits an ancient timestamp and the very "
     "next age check rolls it again",
     [("        _begin_raw_tail_generation(p)\n        return int(size)",
       "        return int(size)")]),

    ("A7", RESEARCH, "under",
     "⛔⛔⛔ A MISSING MARKER SEEDS TO THE EPOCH, so the first run after an upgrade deletes "
     "every existing tail on the machine. Throwing away a person's whole log on the "
     "strength of a guess is the one outcome worse than keeping it too long",
     [("    seeded = now_t\n", "    seeded = 0.0\n")]),

    ("A8", RESEARCH, "under",
     "⛔ THE PRUNE STOPS RETIRING TAILS, so the third of the collector's three sources "
     "goes back to being the one nothing sweeps — which is the state it was already in",
     [("    removed.extend(_retire_stale_rotations(max_age_days=max_age_days, now=now_t))\n",
       "")]),

    # ══ D — deleting a run reaches the disk ═════════════════════════════════

    ("D1", RESEARCH, "under",
     "⛔⛔⛔ FOLDERS ARE MATCHED BY NAME INSTEAD OF BY META. The folder name is a "
     "SANITISED id, so this both misses folders whose id contains anything the pattern "
     "strips AND deletes a DIFFERENT research that happens to share a sanitised prefix. "
     "Somebody else's diagnostics, gone, because two ids look alike",
     [('        if str(meta.get("researchId") or "").strip() != rid:\n            continue',
       "        if not folder.name.startswith(rid):\n            continue")]),

    ("D2", RESEARCH, "under",
     "⛔⛔ A RUNNING RUN'S FOLDER BECOMES DELETABLE — the cross-process half of the "
     "liveness test goes, and worker 1's sweep reaches the folder worker 2 is writing "
     "into. The exact multi-worker hole mutation found in the prune in August",
     [("        if _folder_is_live(folder):\n            continue\n", "")]),

    ("D3", RESEARCH, "under",
     "⛔ THE IN-PROCESS SINK LIST IS IGNORED, so a run this worker armed can have its own "
     "live folder swept out from under it",
     [("        if str(folder) in live or folder.parent != base:",
       "        if folder.parent != base:")]),

    ("D4", RESEARCH, "over",
     "⛔⛔⛔ AN EMPTY RESEARCH ID MATCHES NOTHING BECOMES MATCHES EVERYTHING — one "
     "malformed owner.json and the sweep deletes every run folder on the machine. The "
     "accept-polarity mistake, in the direction that destroys data",
     [("    # bad input and deleting somebody's diagnostics.\n    if not rid:\n        return out",
       "    # bad input and deleting somebody's diagnostics.\n    if False:\n        return out")]),

    ("D5", RESEARCH, "under",
     "⛔⛔ THE SWEEP STOPS REMOVING LOG FOLDERS, which is the state item 4 found: "
     "deleting a run cleared the cloud copy within five minutes and left the verbose "
     "half of it on disk for a month",
     [("                        for _lf in _run_log_folders_for_research(rid):",
       "                        for _lf in []:")]),

    # ══ C — the cloud pull ══════════════════════════════════════════════════

    ("C1", RESEARCH, "under",
     "⛔ THE WINDOW GOES, so every run folder on the machine is queried every quarter "
     "hour forever — a Firestore read per run, for runs whose cloud half arrived weeks ago",
     [("    fresh = [p for p in folders if (now_t - _safe_mtime(p)) <= CLOUD_LOG_PULL_WINDOW_SEC]",
       "    fresh = list(folders)")]),

    ("C2", RESEARCH, "under",
     "⛔ THE PER-TICK CAP GOES, so a machine with sixty fresh folders issues sixty "
     "queries inside one heartbeat, on the loop that owns the liveness write",
     [("    fresh = fresh[:CLOUD_LOG_PULL_MAX_FOLDERS]\n", "")]),

    ("C3", RESEARCH, "under",
     "⛔⛔ FOLDERS WITH NO OWNER ARE SKIPPED SILENTLY. This is the MEASURED MAJORITY "
     "case — five of six folders here carry no uid — so reporting only \"updated 0\" "
     "reads as \"the cloud sent nothing\" when the truth is \"we cannot ask\"",
     [('            out["unattributable"] += 1\n            continue',
       "            continue")]),

    ("C4", RESEARCH, "under",
     "⛔ THE META'S OWN SUBMITTER IS IGNORED in favour of the queue map alone, so a run "
     "whose queue directory has aged out loses its cloud half even when the folder "
     "itself names the owner",
     [('        uid = str(meta.get("submitterUid") or "").strip() or owners.get(rid, "")',
       '        uid = owners.get(rid, "")')]),

    ("C5", RESEARCH, "under",
     "⛔⛔ AN UNCHANGED PULL REWRITES THE FILE ANYWAY, moving the folder's mtime every "
     "fifteen minutes — and that mtime is what the age bound reads and what the bundle's "
     "run selection sorts by, so a finished run looks freshly touched forever and never "
     "ages out",
     [('            if target.exists() and target.read_text(encoding="utf-8") == text:\n'
       "                # ⭐ Nothing new. Rewriting an identical file would move the",
       "            if False:\n"
       "                # ⭐ Nothing new. Rewriting an identical file would move the")]),

    ("C6", RESEARCH, "under",
     "⛔ THE RENDER IS UNORDERED. There is deliberately no `seq` on these records — that "
     "absence is what keeps them out of the app's live listener — so the write time is "
     "the only ordering there is, and dropping it interleaves two phases at random",
     [("    rows.sort(key=lambda r: r[0])\n", "")]),

    ("C7", RESEARCH, "under",
     "⛔ A TRUNCATED CAPTURE STOPS ADMITTING IT, so a reader concludes the cloud went "
     "quiet where it actually hit the bound — the same rule the tail filter already follows",
     [('        if dropped:\n            out.append(f"── {dropped} further line(s) dropped at the capture bound ──")',
       "        if False:\n            out.append(f\"── {dropped} further line(s) dropped at the capture bound ──\")")]),

    ("C8", RESEARCH, "under",
     "⛔⛔ THE RENDER IS UNBOUNDED. The collector's cap decides per RUN, not per file, so "
     "one oversized cloud log takes that run's MACHINE logs out of the bundle with it — "
     "the diagnostic evicting the diagnosis",
     [('    if len(text.encode("utf-8", "ignore")) > CLOUD_LOG_MAX_BYTES:', "    if False:")]),

    ("C9", RESEARCH, "under",
     "⛔⛔ THE HEARTBEAT STOPS CALLING THE PULL. Every unit test of the puller still "
     "passes and not one cloud line ever reaches a run folder — the fourth time this "
     "stretch that a perfect helper had no caller",
     [("                if _cloud_pull_due(_now_ms):", "                if False:")]),

    ("C10", RESEARCH, "under",
     "⛔⛔ A HALF KEY IS ACCEPTED, so a queue directory naming only a researchId yields "
     "`users//researches/{rid}` — a different document path entirely, and one that "
     "cannot be read",
     [("        if uid and rid:\n            out[rid] = uid",
       "        if uid or rid:\n            out[rid] = uid")]),

    ("C11", RESEARCH, "under",
     "⛔ THE WRITE STOPS BEING ATOMIC. Send Logs is a button a person presses, not "
     "something this process schedules, so the collector can walk the folder at any "
     "moment and catch a half-written file",
     [("            _atomic_write_text(target, text, create_parents=False)",
       '            target.write_text(text, encoding="utf-8")')]),
    # ══ X — what the cross-verify found in the first build ══════════════════

    ("X1", RESEARCH, "under",
     "⛔⛔⛔ THE WRITE RESURRECTS A DELETED FOLDER. The pull lists folders and writes "
     "seconds later; Clear Logs or the orphan sweep can remove one in that gap, and a "
     "writer that mkdir's its way back puts a run the person DELETED back on the disk, "
     "cloud output and all, ready for the next support bundle",
     [("        if not folder.is_dir():\n            continue\n", "")]),

    ("X2", RESEARCH, "under",
     "⛔⛔⛔ THE ROLLED COPY IS AGED BY mtime AGAIN — and `os.replace` PRESERVES mtime, "
     "so a 40-day generation arrives as a `.1` already past the bound and is deleted on "
     "the same boot that rolled it, taking yesterday's lines with it",
     [("        rolled_at = _raw_tail_started_at(path, now=now_t)",
       "        rolled_at = _safe_mtime(path)")]),

    ("X3", RESEARCH, "under",
     "⛔ THE ROLLED COPY NEVER STARTS ITS OWN CLOCK, so it falls back to the preserved "
     "mtime and X2's failure returns by a different route",
     [("    _begin_raw_tail_generation(keep, now=now_t)\n", "")]),

    ("X4", RESEARCH, "under",
     "⛔⛔ TRUNCATION KEEPS THE BEGINNING AGAIN. A support bundle is opened because "
     "something went wrong at the END; keeping the first 512 KB of a chatty upload and "
     "dropping the exception is the exact opposite of useful",
     [('        body = text.encode("utf-8", "ignore")[-keep:].decode("utf-8", "ignore")',
       '        body = text.encode("utf-8", "ignore")[:keep].decode("utf-8", "ignore")')]),

    ("X5", RESEARCH, "under",
     "⛔⛔ THE MAINTENANCE JOBS GO BACK ON THE HEARTBEAT'S CRITICAL PATH. Awaiting them "
     "puts up to 75 seconds between liveness writes against a front end that flips a "
     "device Offline after two missed 5-second ticks — housekeeping that makes the "
     "machine look dead",
     [("                    _spawn_maintenance(\"cloud log pull\", _pull_cloud_logs, _cloud_pull_report)",
       "                    await _spawn_maintenance(\"cloud log pull\", _pull_cloud_logs, _cloud_pull_report)")]),

    ("X6", RESEARCH, "under",
     "⛔ THE MAJORITY DROP PATH STOPS BEING REPORTED. On this machine five of six run "
     "folders cannot be attributed, so a tick that fetched nothing for that reason "
     "reads exactly like a tick where the cloud sent nothing",
     [('    if res.get("unattributable"):\n        parts.append(f"{res[\'unattributable\']} folder(s) have no owner on disk, "\n                     "so their cloud logs cannot be fetched")',
       '    if False:\n        parts.append(f"{res[\'unattributable\']} folder(s) have no owner on disk, "\n                     "so their cloud logs cannot be fetched")')]),
]


def sh(args, **kw):
    return subprocess.run(args, cwd=kw.pop("cwd", ROOT), capture_output=True,
                          text=True, env=kw.pop("env", ENV), **kw)


def purge_pycache():
    """⛔ STALE BYTECODE HAS FAKED THREE ROUNDS OF MEASUREMENT IN THIS REPO BEFORE."""
    for d in (ROOT / "tests",):
        if not d.exists():
            continue
        for p in d.rglob("__pycache__"):
            shutil.rmtree(p, ignore_errors=True)
    shutil.rmtree(ROOT / "__pycache__", ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *MUTATED_FILES, "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERRORS = re.compile(r"(\d+) error")
_SKIPPED = re.compile(r"(\d+) skipped")


def _verdict(proc, floor: int, label: str):
    """(green, refusal). ⛔ A SKIP IS THE ABSENCE OF A MEASUREMENT, and pytest exits 0
    for a run that collected almost nothing. Refuse rather than guess."""
    tail = (proc.stdout or "")[-3000:] + (proc.stderr or "")[-1500:]
    passed, failed = _PASSED.search(tail), _FAILED.search(tail)
    errors, skipped = _ERRORS.search(tail), _SKIPPED.search(tail)
    if not passed and not failed:
        return None, f"{label}: pytest printed no counts — the run did not happen: {tail[-300:]!r}"
    if skipped:
        return None, f"{label}: {skipped.group(1)} test(s) SKIPPED — a skip is not a pass"
    n = int(passed.group(1) if passed else 0) + int(failed.group(1) if failed else 0)
    if n < floor:
        return None, (f"{label}: only {n} tests collected, expected at least {floor}"
                      " — the run measured something other than this suite")
    return proc.returncode == 0 and not failed and not errors, None


def run_tests():
    purge_pycache()
    proc = sh([sys.executable, "-B", "-m", "pytest", *SUITES.split(),
               "-q", "-p", "no:cacheprovider"])
    return _verdict(proc, FLOOR, "machine")


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    only = {a for a in sys.argv[1:] if not a.startswith("-")}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if only and len(selected) != len(only):
        print(f"unknown mutant id(s): {only - {m[0] for m in selected}}")
        return 2

    seen = set()
    for m in selected:
        if m[0] in seen:
            print(f"duplicate mutant id: {m[0]}")
            return 2
        seen.add(m[0])

    print("baseline… ", end="", flush=True)
    green, refuse = run_tests()
    if refuse:
        print(f"REFUSED: {refuse}")
        return 2
    if not green:
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    survivors = []
    for mid, fname, direction, why, edits in selected:
        path = ROOT / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                # ⛔ EXACTLY ONE. A stale anchor measured nothing and would still
                # report a kill; a duplicated one mutates a place nobody meant.
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                    "check the anchor's indentation") from None
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            green, refuse = run_tests()
            if refuse:
                raise AssertionError(f"verdict refused — {refuse}")
            killed = not green
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                green, refuse = run_tests()
                if refuse:
                    raise AssertionError(f"verdict refused — {refuse}")
                killed = not green
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}", flush=True)
            survivors.append((mid, direction, f"STALE ANCHOR — measured nothing ({exc})"))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed "
          f"({over} over-corrections)")
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
