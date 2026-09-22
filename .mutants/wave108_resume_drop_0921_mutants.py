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
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_resume_drop_writeback_108.py "
          "tests/test_dead_worker_wiring_108.py "
          "tests/test_stop_is_not_a_crash_108.py "
          "tests/test_cloud_handoff_record_108.py "
          "tests/test_region_comments_108.py "
          # ⛔ ROUND THREE'S TWO SUITES, because a mutant whose killer lives
          # outside the harness's own test list survives for a reason that has
          # nothing to do with the code.
          "tests/test_owner_control_only_109.py "
          "tests/test_round_three_repairs_108.py "
          # ⛔ AND WAVE 10.9's, for the same reason: O9 and O15 were re-aimed at
          # the resume resolution that replaced their old line, and the tests
          # that EXECUTE the resume branch live there.
          "tests/test_member_run_ownership_109.py")
RESEARCH = "research.py"
FILES = (RESEARCH,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: research.py ────────────────────────────────────────────────────
#: The helper's identity refusal.
IDENTITY = "    if not uid or not research_id:\n        return False\n    # \u26d4\u26d4 ITS OWN FIELD"
#: The optional status, which one caller needs to be absent.
OPTIONAL_STATUS = ("    if status and not _research_is_terminal(uid, research_id):\n"
                   "        updates[\"status\"] = status")
#: The three sentences.
S_NO_RUN = "RESUME_DROP_NO_RUN_ID = ("
S_GONE = "RESUME_DROP_ARTIFACTS_GONE = ("
S_STOPPED = "RESUME_DROP_TERMINALLY_STOPPED = ("
#: Branch 1 — no backendRunId at all.
#: ⛔ RE-ANCHORED IN THE REPAIR ROUND. The branch grew a fork — a run whose
#: files are still on disk keeps its recovery — so the old two-line needle
#: matched inside the `else:` arm and removing it left that arm EMPTY. The
#: mutant stopped parsing, which the backend's own ratchet caught: a harness
#: with no pre-write compile guard would have reported those as kills.
B_NO_RUN = ("                    else:\n"
            "                        _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_NO_RUN_ID)\n"
            "                        try: doc.reference.delete()")
#: Branch 2 — the run folder was swept.
B_GONE = ("                    _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_ARTIFACTS_GONE)\n"
          "                    try: doc.reference.delete()")
#: Branch 3 — a .stop sentinel.
B_STOPPED = ("                    _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_TERMINALLY_STOPPED)\n"
             "                    try: doc.reference.delete()")
#: The 12-hour sweep's write, and the guard that keeps it off start docs.
#: ⛔ RE-AIMED 2026-09-21 (round three). This branch grew an owner-control gate:
#: it ran sixty lines above the line that even reads `action`, so it reached a
#: named person's research document before either ownership layer was consulted.
B_STALE = ("                if (data.get(\"action\") == \"resume\"\n"
           "                        and not _owner_control_refused(data, \"stale-sweep\")):\n"
           "                    _resume_drop_writeback(\n"
           "                        data.get(\"uid\") or \"\", data.get(\"researchId\") or \"\",\n"
           "                        RESUME_DROP_WENT_STALE, status=None)")
#: A transient exit that must stay silent — the doc replays on restart.
#: ⛔ RE-ANCHORED IN WAVE 10.9. The read moved into `_resume_run_id` and the
#: listener's `except` around it lost a level of indentation; the sentence
#: gained "usable", because a refused payload claim now reaches it too.
B_TRANSIENT = ("                        log(\n"
               "                            \"Resume: read denied on research doc + no usable backendRunId in payload — drop queue entry\",\n"
               "                            \"WARN\",\n"
               "                        )")

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

# ── anchors: a Stop is not a crash, and a crash we gave up on stays up ──────
#: The branch that tells a deliberate Stop apart from a browser death.
S_BRANCH = "        if _stop_requested:"
#: What that branch writes, which this exit never used to write at all.
S_STATUS = '            _update_firestore_research({"status": "stopped", "phase": last_phase})'
#: The marker the terminal card leaves so automatic paths stop relaunching.
S_MARK = "                (queue_dir / NO_AUTO_RETRY_MARKER).write_text("
#: The gate that reads it.
S_GATE = "    if _stop_path is not None and _no_auto_retry_marked(_stop_path.parent):"
#: The human path clearing it — the reason the gate needs no caller list.
S_CLEAR = "                _clear_no_auto_retry(queue_dir)"
#: The marker's name, which must not be the terminal stop sentinel.
S_NAME = 'NO_AUTO_RETRY_MARKER = ".no_auto_retry"'

# ── anchors: the run's record surviving the hand-off ───────────────────────
#: Resolving the destination from the RESEARCH, not from whatever is armed.
H_RESOLVE = "        folders = _run_folders_for_research_any(rid)"
#: The resolver's match — on meta.json's researchId, never on the folder name.
H_MATCH = '        if str(meta.get("researchId") or "").strip() == rid:'
#: Its own file, because the capped writer is closed after the seal.
H_FILE = '            with open(folder / CLOUD_HANDOFF_FILENAME, "a", encoding="utf-8") as fh:'
#: Re-checked immediately before the write.
H_RECHECK = "            if not folder.is_dir():"
#: The one call both POST outcomes reach.
#: ⛔ ANCHORED WITH THE LINE ABOVE. The repair round added a SECOND
#: `_note_cloud_handoff(research_id, _hl)` in the exception branch, so the
#: bare line started matching twice and the sweep caught it.
#: ⛔ RE-ANCHORED (wave 10.9, 542-5/S4). The drive became a retry ladder and
#: each outcome got its own sentence, so the single post-branch call this used
#: to name is gone — but the shape the item is about survives: the refusal and
#: the exhausted ladder SHARE one unconditional record at the bottom, and
#: guarding it is still how a 401/403 comes to leave nothing anywhere.
#: ⚠ THE CALL ALONE, not the call plus the line after it: a comment landed
#: between the two and the two-line anchor stopped matching, which the sweep
#: caught. This one is unique and cannot drift on a comment edit.
H_BOTH = "    note(_sentence)\n"

# ── anchors: the comments the region navigates by ──────────────────────────
#: The identity check that is the whole safety margin on `manual_brief`.
C_GUARD = "    if actions is None:\n        # #955: the default action set is authored by the intent catalog"
#: The first of the two emitters that dodge the unwired token.
C_DODGE = ('                emit_decision(intent="manual_brief", event_name="manual_brief_required",\n'
           '                              phase=1, actions=[],')
#: The planner gate the corrected comment now asserts.
#: ⛔ ANCHORED WITH THE LINE ABOVE IT. The gate's text alone matches TWICE —
#: the corrected comment beside the dead flag quotes it verbatim, which is the
#: same trap that made the first version of that comment's test pass off its
#: own prose. `crash_budget_ok =` appears once.
C_GATE = ("    crash_budget_ok = crash_retries < BROWSER_CRASH_MAX_RETRIES\n"
          "    if not ((not resume_dir) or (is_crash and crash_budget_ok)):")
#: The assignment to the dead flag, beside the comment that says it is dead.
C_DEAD = "        _runtime.is_retry_attempt = True"
#: A comment that deliberately refuses to cite a line number.
C_NOLINE = "No line number on purpose"
#: A repaired worker retracting its own marker at boot.
W_RETRACT = "            _clear_worker_dead_marker(WORKER_ID)"

# ── anchors: the repair round, after cross-verify ──────────────────────────
#: The guard that stops a drop write-back demoting a finished run.
X_TERMINAL = "    if status and not _research_is_terminal(uid, research_id):"
#: Its fail-closed direction on an unreadable document.
X_FAILCLOSED = ('    except Exception as _tr_err:\n'
                '        log(f"[terminal-check] read failed for {research_id[:8]}… "\n'
                '            f"({_tr_err}) — assuming terminal={on_error}", "DEBUG")\n'
                '        return on_error')
#: The same guard on the new Stop exit.
X_STOPGUARD = ("            if _fb_uid and _fb_research_id and not _research_is_terminal(\n"
               "                    _fb_uid, _fb_research_id, on_error=False):")
#: The elapsed-time evidence that tells a cut connection from one never made.
#: (X_ELAPSED retired with X4 — wave 10.9's retry ladder moved that branch into
#: `_dispatch_verdict`, and `wave109_handoff_mutants.py` H17 aims at it there.
#: Two harnesses mutating one line is duplicated cost, not doubled coverage.)
#: The disk second-opinion before closing a run's automatic recovery.
X_ONDISK = "                    if _orphaned is not None:"
#: (X_RETRACT retired with X6 — round two removed the supervisor's retraction
#: entirely, and Z2 mutates it back from the correct direction.)

# ── anchors: round two of cross-verify ─────────────────────────────────────
#: The dedicated field the card can read for every recovery status.
Z_FIELD = '        "resumeDropReason": reason,'
#: The failure direction, chosen per caller.
Z_DIRECTION = "def _research_is_terminal(uid: str, research_id: str, *, on_error: bool = True) -> bool:"
#: The stop exit asking for the OTHER direction.
Z_STOPDIR = "                    _fb_uid, _fb_research_id, on_error=False):"
#: The on-disk arm repairing the document instead of refusing.
Z_REPAIR = "                        backend_run_id = _orphaned.name"
#: The connect timeout, bounded below the discriminator.
#: ⛔ RE-ANCHORED (wave 10.9, 542-5): the POST moved into `_post`, one nesting
#: level shallower, so the indentation changed from sixteen spaces to twelve.
Z_TIMEOUT = "            timeout=(10, 3600),"
#: The exception class deciding whether the request ever left.
#: ⛔ THE FIRST AIM WAS AN EQUIVALENT MUTANT, WHICH IS A HARNESS FAULT AND NOT A
#: SURVIVOR. It removed the ConnectTimeout/ProxyError check — and both are
#: SUBCLASSES of ConnectionError, so the line below still caught them and the
#: behaviour was unchanged. It is aimed at the classifier's whole premise now:
#: the clock deciding alone, which is the defect this function exists to end.
Z_CLASS = "    exc_mod = _rq.exceptions"

MUTANTS = [
    ("R1", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — a resume with no saved run is dropped in silence "
     "again. The person's banner sits unchanged, still offering a Resume that "
     "takes the same path and vanishes the same way",
     [(B_NO_RUN, "                    else:\n"
                 "                        try: doc.reference.delete()")]),

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
       "                    else:\n"
       "                        try: doc.reference.delete()\n"
       "                        except Exception: pass\n"
       "                        _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_NO_RUN_ID)\n"
       "                        try: pass")]),

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
     [(IDENTITY, "    # \u26d4\u26d4 ITS OWN FIELD")]),

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
       "\n                        _resume_drop_writeback(target_uid, target_rid, RESUME_DROP_ARTIFACTS_GONE)")]),

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

    # ── S: a Stop is not a crash, and a crash we gave up on stays down ─────
    ("S1", "under", RESEARCH,
     "⛔⛔ THE DEFECT I SHIPPED ON 09-20 — a deliberate Stop falls through to "
     "the crash branches again and the person who ended their own run is told "
     "'The run kept hitting errors'. The Stop handler closes the browser on "
     "purpose and every unwind site now tags that as a crash, so the two are "
     "indistinguishable without this test",
     [(S_BRANCH, "        if False:")]),

    ("S2", "under", RESEARCH,
     "⛔ the stop branch stops writing a run-level status, so a Stop that "
     "arrives mid-phase leaves the document `ongoing` for ever — the listing "
     "tile animates a run that ended, which is the wave-10.7 defect reached "
     "through a door 10.7 never looked at",
     [(S_STATUS, "            pass")]),

    ("S3", "under", RESEARCH,
     "⛔⛔ THE TERMINAL CARD STOPS RECORDING THAT IT GAVE UP. `_crash_retries` "
     "is a function parameter, so with nothing on disk a supervised boot "
     "re-enqueues the run at attempt zero — three more Chrome launches while "
     "the person looks at a card saying we stopped trying",
     [(S_MARK, "                (queue_dir / \"unused.tmp\").write_text(")]),

    ("S4", "under", RESEARCH,
     "⛔ the enqueue funnel stops reading the marker, so writing it becomes "
     "bookkeeping nobody consults — the exact shape of a guard that is present, "
     "greppable and decorative",
     [(S_GATE, "    if False:")]),

    ("S5", "over", RESEARCH,
     "⛔⛔ THE OVER-CORRECTION — the human path stops clearing the marker, so a "
     "person pressing Retry on the crash card is refused by a gate meant only "
     "for machines. The card offers an action that silently does nothing, which "
     "is worse than offering none",
     [(S_CLEAR, "                pass")]),

    ("S6", "over", RESEARCH,
     "⛔⛔ AND THE ONE-LINE VERSION OF THIS FIX THAT LOOKS TIDIER — reuse "
     "`.stop`. It refuses the person's own Retry the same way, and since this "
     "wave's drop write-back it also tells them the run 'was stopped for good', "
     "which is a false account of a crash",
     [(S_NAME, 'NO_AUTO_RETRY_MARKER = ".stop"')]),

    # ── H: the run's record surviving the hand-off ────────────────────────
    ("H1", "under", RESEARCH,
     "⛔⛔ THE CROSS-RUN MIS-ATTRIBUTION, RESTORED — the destination comes from "
     "whatever sink is armed at write time again. The drive writes minutes "
     "after this run's sink was popped, so run A's outcome lands in run B's "
     "folder and ships in B's support bundle. Filed as a HIGH in its own right",
     [(H_RESOLVE,
       "        _s = _active_run_sink()\n"
       "        folders = [_s.dir] if _s is not None else []")]),

    ("H2", "under", RESEARCH,
     "⛔ the sweep's resolver is reused, and it SKIPS a folder a sink is armed "
     "on — correct for a delete path, wrong here. The drive starts while the "
     "pipeline is still finishing, so the pre-seal line is dropped and the "
     "harder case looks handled",
     [(H_RESOLVE, "        folders = _run_log_folders_for_research(rid)")]),

    ("H3", "under", RESEARCH,
     "⛔ the resolver matches on the FOLDER NAME instead of the meta. The name "
     "is sanitised, so two researches can share a prefix and a research whose "
     "id the pattern strips does not appear in its own name at all",
     [(H_MATCH, "        if rid[:8] in folder.name:")]),

    ("H4", "under", RESEARCH,
     "⛔⛔ THE LINE GOES BACK INTO `run.log`, WHICH IS CLOSED. `finalize()` "
     "closes the capped writer and a write to a closed writer is a silent "
     "no-op — the record is lost at exactly the moment it matters, and nothing "
     "reports a failure",
     [(H_FILE, '            with open(folder / "run.log", "a", encoding="utf-8") as fh:')]),

    # ⛔ THIS MUTANT WAS EQUIVALENT ON ITS FIRST RUN, and that is a HARNESS bug,
    # not a survivor. It removed the `is_dir()` re-check — but `open(..., "a")`
    # does not create parent directories, so the only thing that changed was a
    # DEBUG line. The property the test actually asserts is that the folder is
    # never RE-CREATED, so the mutant now does the thing that would break it.
    ("H5", "over", RESEARCH,
     "⛔ a `mkdir` creeps in beside the write — the natural repair for the "
     "exception the missing folder throws — and a sweep that removed the "
     "folder between the listing and the append gets it back holding one line "
     "and no meta: a shape the next sweep cannot identify and the bundle index "
     "cannot describe",
     [(H_RECHECK,
       "            folder.mkdir(parents=True, exist_ok=True)\n"
       "            if not folder.is_dir():")]),

    ("H6", "under", RESEARCH,
     "⛔⛔ THE REFUSAL STOPS BEING RECORDED — the shared call moves inside the "
     "2xx branch, so a 401/403 leaves nothing anywhere. The web deliberately "
     "writes nothing on those two exits (no verified identity to write under) "
     "and says in its own words that this half belongs to the machine. This is "
     "the whole of the item",
     [(H_BOTH, "    if verdict != \"refused\":\n        note(_sentence)\n")]),

    # ── C: the comments the region navigates by ───────────────────────────
    ("C1", "under", RESEARCH,
     "⛔⛔ THE `manual_brief` CRASH GOES LIVE — one emitter stops passing an "
     "explicit empty action list, so the expander runs, finds a catalogue "
     "token the builder has no case for, and raises out of phase 1 at a person "
     "waiting to type their brief. The existing test pins the trap OPEN and "
     "passes either way",
     [(C_DODGE, '                emit_decision(intent="manual_brief", event_name="manual_brief_required",\n'
                '                              phase=1,')]),

    ("C2", "under", RESEARCH,
     "⛔⛔ AND THE ONE-WORD VERSION OF THE SAME THING — `is None` becomes a "
     "truthiness test. `[]` is falsy, so both dodges stop working at once and "
     "the crash is live on both paths. This is the commonest tidy-up in Python "
     "and it is the entire safety margin here",
     [(C_GUARD, "    if not actions:\n        # #955: the default action set is authored by the intent catalog")]),

    ("C3", "under", RESEARCH,
     "⛔ a new `research.py:NNNN` self-pointer is added. Every one already in "
     "the file lands on unrelated code, and the sweep that fixes them is wave "
     "10.10's — the ratchet exists to stop the count growing while that waits",
     [(C_NOLINE, "see research.py:12345")]),

    ("C4", "under", RESEARCH,
     "⛔ something READS `is_retry_attempt`, so the comments calling it dead "
     "become the next wrong pointer — and a comment wrong in a safe-sounding "
     "direction is the one nobody re-checks",
     [(C_DEAD, "        _runtime.is_retry_attempt = True\n"
               "        _ = _runtime.is_retry_attempt")]),

    ("C5", "over", RESEARCH,
     "⛔ the planner stops letting a crash retry a resumed run — which is what "
     "the OLD comment claimed and what the corrected one denies. The behaviour "
     "may be worth changing one day; changing it without the comment is how "
     "this pair got out of step in the first place",
     [(C_GATE, "    crash_budget_ok = crash_retries < BROWSER_CRASH_MAX_RETRIES\n"
               "    if resume_dir:")]),

    # ── X: the repair round, after cross-verify ───────────────────────────
    ("X1", "over", RESEARCH,
     "⛔⛔ THE NASTIEST SHAPE IN THE WAVE, RESTORED — a drop write-back demotes a "
     "TERMINAL run. The card offers Resume on a watchdog-stopped or discarded "
     "run, so pressing it lands here, and `paused_backend_restart_failed` is "
     "deliberately outside the web's terminal set: the listing page recomputes "
     "the run as active and puts Stop and Pause back on something that ended "
     "hours ago, where pressing Stop overwrites the record for good",
     [(X_TERMINAL, "    if status:")]),

    ("X2", "over", RESEARCH,
     "⛔ the terminal check fails OPEN on an unreadable document, so one 503 "
     "demotes a finished run. Failing closed costs a sentence without a status "
     "change; failing open costs the record",
     [(X_FAILCLOSED, '    except Exception:\n        return False')]),

    ("X3", "over", RESEARCH,
     "⛔⛔ THE STOP EXIT OVERWRITES `stopped_by_watchdog` AGAIN. A watchdog kill "
     "queues a stop command whose handler closes the browser, so that death "
     "lands in this branch — and a blind plain-'stopped' write erases the "
     "attribution seconds later. Plain `stopped` is not a recovery status, so "
     "the chat then CLEARS the card and the person loses the only sentence "
     "explaining a ceiling stop, and both its buttons",
     [(X_STOPGUARD, "            if True:")]),

    # (X4 retired — see X_ELAPSED above. The branch it named moved into
    # `_dispatch_verdict` with wave 10.9's retry ladder, where
    # `wave109_handoff_mutants.py` H17 mutates it.)

    ("X5", "over", RESEARCH,
     "⛔ the no-backendRunId branch stops asking the disk, so a run whose files "
     "are still in `queues/` — the write-back of that field can fail while the "
     "run proceeds — has its automatic recovery closed permanently, because the "
     "status it gets is outside BOTH enqueue whitelists",
     [(X_ONDISK, "                    if False:")]),

    # ── Z: round two of cross-verify — the repairs that cancelled ─────────
    ("Z1", "under", RESEARCH,
     "⛔⛔ THE DEADLOCK, RESTORED — the refusal goes back to `lastError` alone. "
     "On the two TERMINAL recovery statuses the status is deliberately not "
     "moved, so the card (which cannot read a stale `lastError`) never changes, "
     "and the chat's 45-second fallback stamps 'your computer didn't pick this "
     "up' over a refusal that can never change — frozen, beside a Resume that "
     "cannot work. Worse than what it replaced",
     [(Z_FIELD, '        "_unread": reason,')]),

    ("Z2", "over", RESEARCH,
     "⛔⛔ THE SUPERVISOR RETRACTS AGAIN. `_spawn_worker` returns the instant "
     "`Popen` succeeds — no health check, no poll — so this measures a "
     "successful FORK, not a live worker: a worker that dies at import has its "
     "marker cleared about seven seconds after it was written, never reaching "
     "the reader's sixty-second grace. The rescue is deleted by the code that "
     "was widening it",
     [("                            new_state[\"watchdog_window\"] = state.get(\"watchdog_window\", [])",
       "                            _clear_worker_dead_marker(k)\n"
       "                            new_state[\"watchdog_window\"] = state.get(\"watchdog_window\", [])")]),

    ("Z3", "over", RESEARCH,
     "⛔⛔ THE STOP EXIT FAILS THE WRONG WAY. One unreadable read there "
     "suppresses the ONLY terminal status that exit writes, so a run the person "
     "stopped sits `ongoing` for ever with Stop and Pause live — and the process "
     "calls os._exit(0) three seconds later, so nothing corrects it",
     [(Z_STOPDIR, "                    _fb_uid, _fb_research_id):")]),

    ("Z4", "under", RESEARCH,
     "⛔ the on-disk arm finds the run id and throws it away again, refusing a "
     "run it just proved is recoverable and advising a Resume that takes the "
     "identical branch for ever — a closed loop whose own sentence tells the "
     "person to keep pressing it",
     [(Z_REPAIR, "                        backend_run_id = \"\"")]),

    ("Z5", "under", RESEARCH,
     "⛔ the connect timeout goes back to 3600 with the read. A black-holed SYN "
     "then fails tens of seconds later rather than at once, past the "
     "discriminator — and the run's permanent record says the cloud received a "
     "request that never left the machine",
     [(Z_TIMEOUT, "            timeout=3600,")]),

    ("Z7", "under", RESEARCH,
     "⛔ the read-timeout check moves BELOW the connection-error check. "
     "`ReadTimeout` is a `ConnectionError` subclass in some versions of "
     "requests, so a request the cloud received and worked on for five minutes "
     "is filed as one that never left — the order of these checks is "
     "load-bearing, not incidental",
     [("    if isinstance(exc, (exc_mod.ReadTimeout, exc_mod.ChunkedEncodingError)):\n"
       "        return False\n",
       "")]),

    ("Z6", "under", RESEARCH,
     "⛔ the exception class stops deciding and the clock decides alone, which "
     "names the wrong subject: only a sub-second DNS failure lands on the "
     "honest side, and every other never-left failure is filed as one the cloud "
     "received",
     [(Z_CLASS, "    return elapsed_sec < _DRIVE_SENT_AFTER_SEC\n    exc_mod = _rq.exceptions")]),

    # ── Z8/Z9: the classifier, corrected the OTHER way ─────────────────────
    #
    # ⛔⛔ ROUND THREE INDUCED THE REAL EXCEPTION AND FOUND Z6's FIX TOO WIDE.
    # urllib3 wraps a socket cut MID-FLIGHT in the same bare `ConnectionError`
    # it uses for a connection that never opened — and a mid-flight cut is this
    # route's defining failure, a severance at exactly 300 s while the request
    # keeps being served. So the class may answer only where it is unambiguous.
    ("Z8", "under", RESEARCH,
     "⛔⛔⛔ EVERY bare ConnectionError is filed as 'never left' again, so the "
     "permanent support-bundle record says the cloud never received requests it "
     "received and finished — the exact sentence round one removed, on the "
     "majority path",
     [("    if isinstance(exc, (exc_mod.ConnectTimeout, exc_mod.ProxyError)):\n"
       "        return True\n",
       "    if isinstance(exc, (exc_mod.ConnectTimeout, exc_mod.ProxyError)):\n"
       "        return True\n"
       "    if isinstance(exc, exc_mod.ConnectionError):\n"
       "        return True\n")]),

    ("Z9", "under", RESEARCH,
     "⛔ ChunkedEncodingError leaves the received tuple. Exercised only at 301 s "
     "the clock fallback agreed anyway, so this survived — a body-stream break "
     "moments after dispatch is still a request the cloud received",
     [("    if isinstance(exc, (exc_mod.ReadTimeout, exc_mod.ChunkedEncodingError)):",
       "    if isinstance(exc, (exc_mod.ReadTimeout,)):")]),

    # ── O: round three, and the half both identity layers could not see ────
    #
    # ⛔⛔ THE WIRING TESTS COULD NOT SEE THE FOUNDING DEFECT COME BACK. Round
    # three built O1 and O2 by hand and ran the previous suite's own AST logic
    # against them; both stayed green, and O2 IS this wave's founding defect
    # verbatim. A guard worth having is a guard a test can execute.
    ("O1", "under", RESEARCH,
     "⛔⛔ the refusal stops DELETING the document it refused, so the next "
     "snapshot re-reads it and the idle rescan sweeps up precisely the documents "
     "the listener declined — a refusal implemented as a delay",
     [("    try:\n        doc.reference.delete()\n    except Exception:\n        pass\n"
       "    return True\n\n\ndef _job_is_another_persons",
       "    return True\n\n\ndef _job_is_another_persons")]),

    ("O2", "under", RESEARCH,
     "⛔⛔ the verdict is computed, logged and thrown away — the branch falls "
     "through and cancels the victim's run anyway. This is the wave's founding "
     "defect verbatim, and the previous wiring test passed against it",
     [("    if not _owner_control_refused(data, where):\n        return False\n",
       "    if not _owner_control_refused(data, where):\n        return False\n"
       "    return False\n")]),

    ("O3", "under", RESEARCH,
     "⛔ the cancel branch's guard becomes one term of a compound condition, so "
     "something else decides the branch while a name-search still finds the call",
     [('                if _refuse_owner_control(doc, data, "start-listener"):\n'
       '                    continue\n'
       '                target_rid = data.get("researchId", "")',
       '                if False and _refuse_owner_control(doc, data, "start-listener"):\n'
       '                    continue\n'
       '                target_rid = data.get("researchId", "")')]),

    ("O4", "under", RESEARCH,
     "⛔⛔ a job's owner stops being consulted, so a member who signs honestly as "
     "themselves and names somebody else's researchId stops, purges and "
     "permanently un-resumes that person's run — with no identity divergence for "
     "either layer to catch",
     [("    owner = str((job or {}).get(\"uid\") or \"\").strip()\n"
       "    wanted = str(target_uid or \"\").strip()\n"
       "    return bool(owner and wanted and owner != wanted)",
       "    return False")]),

    ("O5", "over", RESEARCH,
     "⛔ absent becomes disagreeing, so a job dict from before the uid "
     "requirement can no longer be cancelled by anyone — the shape that takes "
     "the product away instead of the attack",
     [("    return bool(owner and wanted and owner != wanted)",
       "    return owner != wanted")]),

    # ⛔⛔⛔ O6 AND O9 SURVIVED THEIR FIRST RUN, and both for the same reason:
    # the guard was an `if` inside a 4000-line listener and the test read the
    # parse tree for NAMES. `if False and <call>` keeps every name, every line
    # number and every ordering. The fix in both cases was the one this wave
    # already used twice — extract the decision so a test can EXECUTE it, and
    # pin the consumer on its SHAPE rather than its words. These two are re-aimed
    # at the shape, and O13-O16 attack the extractions themselves.
    ("O6", "under", RESEARCH,
     "⛔⛔ the cancel branch stops asking whose run it is before stopping it. "
     "`.stop` is permanent, and this wave's own resume path then answers every "
     "later Resume with 'This run was stopped for good'",
     [("                if _refuse_foreign_run(doc, _local_jobs, target_rid, target_uid,\n"
       "                                       \"start-listener\"):\n"
       "                    continue\n",
       "")]),

    ("O13", "under", RESEARCH,
     "⛔⛔⛔ THE MUTANT THAT SURVIVED ROUND THREE'S FIRST HARNESS RUN — the "
     "ownership gate becomes one term of a compound condition. Every name stays, "
     "every line number stays, the ordering stays, and the victim's run is "
     "stopped anyway",
     [("                if _refuse_foreign_run(doc, _local_jobs, target_rid, target_uid,\n",
       "                if False and _refuse_foreign_run(doc, _local_jobs, target_rid, target_uid,\n")]),

    ("O14", "under", RESEARCH,
     "⛔⛔ the foreign-run refusal keeps its verdict and stops DELETING the "
     "document, so the next snapshot re-reads it and the idle rescan sweeps up "
     "exactly the cancel the listener declined",
     # ⛔ RE-ANCHORED IN WAVE 10.9: the log line names `{verb}`, because the
     # resume branch now asks the same question through the same helper.
     [("    log(f\"[{where}] refusing {verb} of {str(research_id)[:8]}… — the run this \"\n"
       "        f\"names belongs to another person on this computer\", \"WARN\")\n"
       "    try:\n        doc.reference.delete()\n    except Exception:\n        pass\n"
       "    return True",
       "    log(f\"[{where}] refusing {verb} of {str(research_id)[:8]}… — the run this \"\n"
       "        f\"names belongs to another person on this computer\", \"WARN\")\n"
       "    return True")]),

    ("O15", "under", RESEARCH,
     "⛔ the corroborated run id is computed and then not used — the assignment "
     "keeps the client's claim, which is the surviving mutant's effect achieved "
     "by a different route",
     # ⛔ RE-AIMED IN WAVE 10.9 at the consumer's new shape: the resolution is
     # still called, and the branch reads the raw payload claim anyway.
     [("                    backend_run_id, rd = _resume_run_id(data, target_uid, target_rid)\n",
       "                    _unused, rd = _resume_run_id(data, target_uid, target_rid)\n"
       "                    backend_run_id = (data.get(\"backendRunId\") or \"\").strip() or _unused\n")]),

    ("O16", "over", RESEARCH,
     "⛔⛔ a directory with no readable owner.json loses its claim, so every run "
     "predating that file stops being resumable at all — the over-correction "
     "that takes the product away instead of the attack",
     [("    except Exception:\n        return claimed\n    owns = str((owner or {}).get(\"researchId\") or \"\").strip()",
       "    except Exception:\n        return \"\"\n    owns = str((owner or {}).get(\"researchId\") or \"\").strip()")]),

    ("O7", "under", RESEARCH,
     "⛔ the deque scan drops any job with the named research id regardless of "
     "who owns it — 'the job I named' and 'the job I own' become the same "
     "sentence again",
     [("                            return (j.get(\"research_id\") == _r\n"
       "                                    and not _job_is_another_persons(j, _u))",
       "                            return j.get(\"research_id\") == _r")]),

    ("O8", "under", RESEARCH,
     "⛔ the race re-check on current_job loses its ownership clause — and that "
     "branch exists precisely because a job can arrive after the listener-thread "
     "gate ran, so the one window the gate cannot cover is the one left open",
     [("                        if (current_now.get(\"research_id\") == rid\n"
       "                                and not _job_is_another_persons(current_now, u)):",
       "                        if current_now.get(\"research_id\") == rid:")]),

    ("O9", "under", RESEARCH,
     "⛔⛔ a client-supplied backendRunId is taken on trust again, so a resume "
     "runs somebody else's run directory under this person's research — clearing "
     "their .no_auto_retry and their .pause on the way",
     # ⛔ RE-AIMED IN WAVE 10.9: the payload claim is corroborated inside
     # `_resume_run_id` now, so "taken on trust" is that line reading it raw.
     [("    claimed = _corroborated_run_id((data or {}).get(\"backendRunId\"), research_id, uid)\n",
       "    claimed = str((data or {}).get(\"backendRunId\") or \"\").strip()\n")]),

    ("O10", "under", RESEARCH,
     "⛔ the mismatch is REPORTED and then used anyway — a log line where a "
     "refusal should be, which is the shape round two caught on the "
     "no-backendRunId branch",
     # ⛔ RE-ANCHORED IN WAVE 10.9: the helper now corroborates the research
     # document's claim and boot recovery's too, so the log stopped saying
     # "payload".
     [("    if owns and owns != rid:\n"
       "        log(f\"Resume: run {claimed} was named for {rid[:8]}… but that run \"\n"
       "            f\"belongs to {owns[:8]}… — ignoring the claim\", \"WARN\")\n"
       "        return \"\"\n",
       "    if owns and owns != rid:\n"
       "        log(f\"Resume: run {claimed} was named for {rid[:8]}… but that run \"\n"
       "            f\"belongs to {owns[:8]}… — ignoring the claim\", \"WARN\")\n")]),

    ("O11", "under", RESEARCH,
     "⛔⛔ the twelve-hour sweep writes into a named person's research document "
     "again, sixty lines above the line that even reads `action` — the one path "
     "where the machine guard and the Firestore rule are not two layers but one",
     [("                if (data.get(\"action\") == \"resume\"\n"
       "                        and not _owner_control_refused(data, \"stale-sweep\")):",
       "                if data.get(\"action\") == \"resume\":")]),

    ("O12", "under", RESEARCH,
     "⛔⛔ a successful resume stops retiring its own refusal, so "
     "`resumeDropReason` has one writer and no deleter again — round one's "
     "stale-field defect on the field that replaced it, and the card now prefers "
     "it for all four recovery statuses",
     [("                                      \"resumeDropReason\": _DF_RESUME,\n"
       "                                      \"resumeDropAt\": _DF_RESUME})",
       "                                      })")]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green():
    # ⭐ THE INTERPRETER RUNNING THIS FILE, not a hard-coded `.venv/bin/python`
    # (wave 10.9). A worktree has no `.venv` of its own, so the literal path
    # made every run from one report BASELINE RED — a harness that cannot load
    # its own runner looks exactly like a suite that is broken, and the repair
    # in flight looks like the cause. pytest puts the cwd first on sys.path, so
    # the tree under test is still the one measured.
    r = _run(f"{shlex.quote(sys.executable)} -m pytest {SUITES} -q -p no:cacheprovider")
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
