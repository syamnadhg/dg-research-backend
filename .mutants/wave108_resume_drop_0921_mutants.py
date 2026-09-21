"""Wave 10.8 — can the guards see a Resume the machine threw away?

⛔⛔ WHAT THE WAVE CLOSED. The resume handler has exactly ONE Firestore write
and it sits on the success path. NINE other exits delete the queue entry and
write nothing at all, so the research document keeps whatever status put the
Resume banner on screen — which the web reads as a run that is paused but NOT
over. On the web side `resumePipelineFromCheckpoint` is a bare `addDoc` with no
listener and no timeout, and the chat cleared its card the moment that write
resolved. Four seconds after the press there was no banner, no error and no
button, on a request this process had already thrown away.

⛔⛔ AND NOT ONE TEST COULD SEE ANY OF IT. `grep -rn "Resume:" tests/` returned
nothing before this wave, and so did every drop branch's log string.

Every mutant below is a way the fix could be put back to decoration while still
looking installed. The ones that matter most are the quiet ones:

  R4  — the write-back moves BELOW the delete. Still present, still greppable,
        and the delete is what stops anything bringing us back here.
  R6  — the 12-hour case starts stamping the failed status. That status is
        absent from `_safe_enqueue`'s whitelist, so it permanently closes
        auto-resume — on the one branch whose artifacts are still on disk and
        whose run really can be picked up.
  R10 — the write-back spreads to the TRANSIENT exits, telling somebody their
        run failed when it is about to replay on the next restart. The
        over-correction, and the one a reviewer is most likely to wave through
        as "more coverage".
  R9  — the three sentences collapse into one, so a swept folder and a
        deliberate stop read identically. Flattening is this project's
        recurring way of undoing a fix while keeping it.

⭐ THE W SECTION IS THE SAME WAVE'S OTHER HALF: a run whose WORKER abandoned it.
The #64 backstop marks such runs `paused_backend_restart` so a Resume appears —
and it covered ONE death path in four. The supervisor gives up on a worker when
the initial fleet spawn fails, when a respawn after a watchdog kill fails, in
the crash loop, and when a respawn after a crash fails; only the crash loop
wrote the marker worker 1 reads. W1-W3 are those three paths going quiet again;
W5 and W6 are the two lines that make the whole mechanism run and that fifteen
existing tests never touched — delete either and every one of them still passes.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. W4 proved
it on its first run: `"reason": reason,` matches a second payload elsewhere in
the file, and the static sweep caught it before the harness could report a
phantom kill.

  .venv/bin/python .mutants/wave108_resume_drop_0921_mutants.py
  .venv/bin/python .mutants/wave108_resume_drop_0921_mutants.py R4 R6
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_resume_drop_writeback_108.py "
          "tests/test_dead_worker_wiring_108.py")
RESEARCH = "research.py"
FILES = (RESEARCH,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: research.py ────────────────────────────────────────────────────
#: The helper's identity refusal.
IDENTITY = "    if not uid or not research_id:\n        return False\n    updates: dict = {\"lastError\": reason}"
#: The optional status, which one caller needs to be absent.
OPTIONAL_STATUS = "    if status:\n        updates[\"status\"] = status"
#: The three sentences.
S_NO_RUN = "RESUME_DROP_NO_RUN_ID = ("
S_GONE = "RESUME_DROP_ARTIFACTS_GONE = ("
S_STOPPED = "RESUME_DROP_TERMINALLY_STOPPED = ("
#: Branch 1 — no backendRunId at all.
B_NO_RUN = ("                    _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_NO_RUN_ID)\n"
            "                    try: doc.reference.delete()")
#: Branch 2 — the run folder was swept.
B_GONE = ("                    _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_ARTIFACTS_GONE)\n"
          "                    try: doc.reference.delete()")
#: Branch 3 — a .stop sentinel.
B_STOPPED = ("                    _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_TERMINALLY_STOPPED)\n"
             "                    try: doc.reference.delete()")
#: The 12-hour sweep's write, and the guard that keeps it off start docs.
B_STALE = ("                if data.get(\"action\") == \"resume\":\n"
           "                    _resume_drop_writeback(\n"
           "                        data.get(\"uid\") or \"\", data.get(\"researchId\") or \"\",\n"
           "                        RESUME_DROP_WENT_STALE, status=None)")
#: A transient exit that must stay silent — the doc replays on restart.
B_TRANSIENT = ("                            log(\n"
               "                                \"Resume: read denied on research doc + no backendRunId in payload — drop queue entry\",\n"
               "                                \"WARN\",\n"
               "                            )")

# ── anchors: the dead-worker backstop's wiring ──────────────────────────────
#: The boot spawn that never marked.
W_BOOT = ('            if _st is None:\n'
          '                _write_worker_dead_marker(k, reason="spawn_failed_at_boot")')
#: The respawn after a watchdog kill that never marked.
W_WATCHDOG = ('                            _write_worker_dead_marker(\n'
              '                                k, reason="respawn_failed_after_watchdog")')
#: The respawn after a crash that never marked.
W_CRASH_RESPAWN = ('                        _write_worker_dead_marker(\n'
                   '                            k, crash_count=len(state.get("crash_window") or []),\n'
                   '                            reason="respawn_failed_after_crash")')
#: The parameter that lets four outcomes say four things.
#: ⛔ ANCHORED ON THE LINE ABOVE IT TOO. `"reason": reason,` alone matches a
#: second payload elsewhere in the file, and the sweep caught it before the
#: harness could report a phantom kill. `died_at` is unique to this marker.
W_REASON = ('            "died_at": int(time.time() * 1000),\n'
            '            "reason": reason,')
#: Worker 1 scheduling the reconciler — the line that makes all of it run.
W_SCHEDULE = "            asyncio.create_task(_dead_worker_reconcile_loop())"
#: A repaired worker retracting its own marker at boot.
W_RETRACT = "            _clear_worker_dead_marker(WORKER_ID)"

MUTANTS = [
    ("R1", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — a resume with no saved run is dropped in silence "
     "again. The person's banner sits unchanged, still offering a Resume that "
     "takes the same path and vanishes the same way",
     [(B_NO_RUN, "                    try: doc.reference.delete()")]),

    ("R2", "under", RESEARCH,
     "⛔⛔ the swept-folder drop goes quiet. This is the likeliest of the three: "
     "boot rehydration writes the paused status to FIRESTORE ONLY and never "
     "touches delivery.json, so the 7-day sweep removes the folder of the very "
     "run whose banner is still asking to be resumed",
     [(B_GONE, "                    try: doc.reference.delete()")]),

    ("R3", "under", RESEARCH,
     "⛔ a terminally stopped run drops the resume with no word, so the person "
     "retries a run that ended on purpose, for ever",
     [(B_STOPPED, "                    try: doc.reference.delete()")]),

    ("R4", "under", RESEARCH,
     "⛔⛔ THE WRITE MOVES BELOW THE DELETE. Still present, still greppable, and "
     "the queue entry — the only thing that would bring us back here — is gone "
     "before the sentence is written. A source pin cannot tell these apart",
     [(B_NO_RUN,
       "                    try: doc.reference.delete()\n"
       "                    except Exception: pass\n"
       "                    _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_NO_RUN_ID)\n"
       "                    try: pass")]),

    ("R5", "under", RESEARCH,
     "⛔⛔ THE 12-HOUR CARVE-OUT, RESTORED. A resume that waited overnight is "
     "deleted in silence — and the banner's own copy is 'Start Super Research on "
     "your PC, then tap Resume', so tapping before booting is the order the "
     "product asks for",
     [(B_STALE, "                if False:\n                    pass")]),

    ("R6", "over", RESEARCH,
     "⛔⛔ THE OVER-CORRECTION THAT COSTS THE MOST — the 12-hour case stamps the "
     "failed status. That status is absent from `_safe_enqueue`'s whitelist, so "
     "it permanently closes auto-resume, on the one branch whose artifacts are "
     "still on disk and whose run really can be picked up",
     [("                        RESUME_DROP_WENT_STALE, status=None)",
       "                        RESUME_DROP_WENT_STALE)")]),

    ("R7", "over", RESEARCH,
     "⛔ the helper ignores `status=None` and always stamps the failed status, "
     "reaching the same harm as R6 from the other end — a caller that asked for "
     "a message gets a policy change",
     [(OPTIONAL_STATUS, "    updates[\"status\"] = status or \"paused_backend_restart_failed\"")]),

    ("R8", "over", RESEARCH,
     "⛔ the helper stops refusing a half identity, so a queue doc missing its "
     "uid writes to `users//researches/...` — either a raise inside a listener "
     "callback or a write nobody can find",
     [(IDENTITY, "    updates: dict = {\"lastError\": reason}")]),

    ("R9", "under", RESEARCH,
     "⛔ the three reasons collapse into one, so a swept folder, a missing "
     "checkpoint and a deliberate stop all read the same. Flattening is how this "
     "project keeps undoing a fix while appearing to keep it",
     [(S_GONE + "\n    \"The saved files for this run have been cleared from the computer, so it \"\n"
                "    \"can't be picked up from where it stopped. Start it again to run it fresh.\"\n)",
       S_GONE + "\n    \"This run has no saved checkpoint on the computer, so there is nothing to \"\n"
                "    \"pick up from. Start it again to run it fresh.\"\n)")]),

    ("R10", "over", RESEARCH,
     "⛔⛔ THE WRITE-BACK SPREADS TO A TRANSIENT EXIT — a read that failed once is "
     "reported to the person as a failed run, when the queue doc is still there "
     "and replays on the next restart. Telling somebody their work is gone when "
     "it is about to resume is the lie this wave exists to end, pointed the other "
     "way",
     [(B_TRANSIENT, B_TRANSIENT +
       "\n                            _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_ARTIFACTS_GONE)")]),

    # ── W: the Resume backstop for a run its worker abandoned ──────────────
    ("W1", "under", RESEARCH,
     "⛔⛔ THE BOOT-SPAWN DEATH GOES UNMARKED AGAIN — a worker that never comes "
     "up still owns yesterday's runs, and with no marker worker 1 cannot see "
     "it. Those runs stay frozen ongoing with no Resume, which is exactly the "
     "2026-07-16 state the stale KNOWN LIMITATION still describes",
     [(W_BOOT, "            if False:\n                pass")]),

    ("W2", "under", RESEARCH,
     "⛔ the watchdog-respawn death goes unmarked — the watchdog killed a wedged "
     "worker, it would not come back, and the runs it held get no rescue",
     [(W_WATCHDOG, "                            pass")]),

    ("W3", "under", RESEARCH,
     "⛔ the crash-respawn death goes unmarked — indistinguishable to the person "
     "from the crash-loop branch one step above it, which DOES mark",
     [(W_CRASH_RESPAWN, "                        pass")]),

    ("W4", "under", RESEARCH,
     "⛔ all four deaths report the same cause again. Nothing READS the reason, "
     "so this costs nothing at runtime and everything to the next reader — one "
     "hardcoded literal is why three missing call sites survived two months",
     [(W_REASON, '            "died_at": int(time.time() * 1000),\n'
                 '            "reason": "crash_loop",')]),

    ("W5", "under", RESEARCH,
     "⛔⛔ THE RECONCILER IS NEVER SCHEDULED. Fifteen tests drive it as a "
     "function and every one still passes, while no orphaned run is ever marked "
     "recoverable again — the helper-pinned-consumer-not shape at its purest",
     [(W_SCHEDULE, "            pass")]),

    ("W6", "under", RESEARCH,
     "⛔ a repaired worker no longer retracts its own marker, so worker 1 keeps "
     "re-pausing the runs that worker is booting to recover — an operator repair "
     "gains a manual step nobody documents",
     [(W_RETRACT, "            pass")]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green():
    r = _run(f".venv/bin/python -m pytest {SUITES} -q")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it.
    return " failed" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY, and the sweep is why. The
# static anchor sweep loads every harness in this directory with
# `spec.loader.exec_module`, which EXECUTES it — so an unguarded runner turns a
# seconds-long static check into a full mutation run, and the sweep's own
# verdict is buried under the harness's output. Mine did exactly that once.
if __name__ == "__main__":
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}


    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")


    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    if not green():
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, fname, why, edits in selected:
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
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}")
            else:
                print(f"  {mid}  ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (anchor)")
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
