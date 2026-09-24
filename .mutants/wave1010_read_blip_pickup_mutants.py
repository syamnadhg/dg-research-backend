"""Wave 10.10 leftovers — can the tests see a restart's recovery lose a run to
a read that failed once?

Three places a restart recovers a run gave up for good on a Firestore blip at
boot. Each now retries silently, in the same process, on one short schedule:

  H/R/Q/K/X — the BOOT RESTORE. An entry whose record could not be read is
        HELD by the funnel (`hold_unreadable`), carried by every snapshot
        rewrite, offered again through the same funnel and the same #728
        whitelist, and drained by Reset Backend like any waiting job.
  M     — the REHYDRATE. A recovery mark that failed is written again, only
        after a read that answered "ongoing", and never over a run somebody
        started since boot.
  T     — the one question both retries ask before they act on "ongoing": has
        a Resume here, this process, a sibling's lock or another worker's
        stamp taken the run since boot (`_run_taken_since_boot`).
  C     — the RESUME. A failed record read asks the disk, by owner, instead of
        dropping the request; nothing on the disk still drops it silently.
  S     — the one spawner both retries go through.

The quiet ones matter most:

  H2/Q1 — the boot restore, or its retry, starts a run whose status nobody saw,
        or one rehydration parked for its person's Resume. That is #728 back.
  K1    — the writer stops carrying held entries: the first worker boundary
        erases the only description of the run, which is the defect itself.
  X1    — Reset Backend leaves a held entry, and it runs after the reset.
  Q4b   — the re-offer starts an entry Reset Backend drained while its read
        was out, or at any moment up to the settle's remove.
  T1-T4/R3 — the re-offer starts a second copy of a run a Resume started here
        or on a sibling worker, or one a sibling holds the lock for.
  T7/T8 — the re-offer reads a missing worker stamp as worker 1's, and worker 2
        lets go of its own mid-flight run (re-verify of this wave).
  T9/T10 — another member's Resume, or job, for a research with the same id
        lets go of this person's held run (ids are published to every member).
  M4/M5/M6 — the mark retry writes a Resume offer over a run the person
        stopped, over a record it could not read, or over a run somebody
        started since boot.
  Q9/Q10 — the re-offer's read runs on the loop, or waits for ever.
  Q13-Q15 — the loop stops waiting but the read's THREAD goes on, retrying for
        300 s in the shared executor (re-verify of this wave).

⛔ A KILL IS A FAILED OR ERRORED TEST, NEVER A SKIP. Fewer passes with more
skips is counted as a survivor: a pin that stops running looks exactly like one
that caught something.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED, from the checkout being measured:

  <venv>/bin/python -u .mutants/wave1010_read_blip_pickup_mutants.py
  <venv>/bin/python -u .mutants/wave1010_read_blip_pickup_mutants.py K1 M4
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
RESEARCH = "research.py"

PICKUP = ["tests/test_restart_recovery_retries_1010.py",
          "tests/test_failed_read_keeps_the_run_1010.py"]

# ── anchors: the funnel ─────────────────────────────────────────────────────
HOLD = ("            if hold_unreadable is not None:\n"
        "                hold_unreadable.append(job)")
GATE = "        if not take_unreadable:"
STATUS = "            if status not in allowed_statuses:"
SEEN = ("            if record_seen is not None:\n"
        "                record_seen.update(_record)")
FUNNEL_READ = '                .collection("researches").document(rid).get(**(read_options or {}))'

# ── anchors: the boot restore and its retry ─────────────────────────────────
RESTORE_CALL = ('        if _safe_enqueue(job_queue, j, source="disk-restore",\n'
                '                         allowed_statuses=("queued", "ongoing"),\n'
                '                         hold_unreadable=_UNREAD_RESTORES):')
RESTORE_SPAWN = ("    if _UNREAD_RESTORES:\n"
                 "        _retry_after_restart(_reoffer_unread_restores(job_queue))")
RETRY_CALL = ('    took = _safe_enqueue(staged, job, source="disk-restore-retry",\n'
              '                         allowed_statuses=("queued", "ongoing"),\n'
              '                         hold_unreadable=unread, record_seen=record,')
RETRY_READ_OPTIONS = ('                         hold_unreadable=unread, record_seen=record,\n'
                      '                         read_options={"retry": None,\n'
                      '                                       "timeout": '
                      '_RESTART_RETRY_READ_TIMEOUT_S})')
RETRY_NO_RETRY = '                         read_options={"retry": None,'
ASK_UNREAD = ('    if unread:\n'
              '        return "unread", {}')
RETRY_LET_GO = ('    if answer == "unread":\n'
                '        return\n'
                '    try:\n'
                '        _UNREAD_RESTORES.remove(job)')
RETRY_RELEASE = ("    try:\n"
                 "        _UNREAD_RESTORES.remove(job)\n"
                 "    except ValueError:")
DRAINED_SINCE = ("        return\n"
                 '    if answer != "take":')
RETRY_ROUNDS = ("    for delay in _RESTART_RETRY_DELAYS_S:\n"
                "        await asyncio.sleep(delay)\n"
                "        for job in list(_UNREAD_RESTORES):")
RETRY_READ = ("                answer, record = await asyncio.wait_for(\n"
              "                    asyncio.to_thread(_ask_about_held_entry, job),\n"
              "                    timeout=_RESTART_RETRY_READ_TIMEOUT_S)")
SETTLE_ASKS = ('    why = _run_taken_since_boot((job or {}).get("uid"), rid, record, job_queue,\n'
               "                                unstamped_is_worker_1=False)")

# ── anchors: the one question both retries ask ─────────────────────────────
TAKEN_RESUMED = "    if (uid, rid) in _RESUMED_HERE:"
TAKEN_HELD = ('    if any(((j or {}).get("uid"), (j or {}).get("research_id")) == (uid, rid)\n'
              "           for j in _jobs_held_locally(job_queue)):")
TAKEN_LOCK = "    holders = _scan_sibling_locks_for_research(rid, WORKER_ID)"
TAKEN_ONGOING = '    if (record or {}).get("status") == "ongoing":'
TAKEN_OWNER = "        if owner != WORKER_ID and 1 <= owner <= fleet:"
TAKEN_STAMP = ("        if not isinstance(stamp, int) and not unstamped_is_worker_1:\n"
               "            return None")
RESUME_RECORDS = "                _RESUMED_HERE.add((target_uid, target_rid))"

# ── anchors: the carry ──────────────────────────────────────────────────────
WRITER_CARRY = ("    pending_jobs = (list(pending_jobs or [])\n"
                "                    + _unread_restores_to_carry(pending_jobs, current_job))")
FORGET_CARRY = "    live += _unread_restores_to_carry(live, current)"
CARRY_SKIP = "        if rid in seen or _is_incognito_research(rid):"
CARRY_CURRENT = '    seen.add((current_job or {}).get("research_id"))'

# ── anchors: Reset Backend ──────────────────────────────────────────────────
RESET_DRAIN = ("                    _drained_jobs.extend(_UNREAD_RESTORES)\n"
               "                    del _UNREAD_RESTORES[:]")

# ── anchors: the rehydrate's recovery mark ──────────────────────────────────
PARK_RETRY = ('                        log(f"Rehydrate: mark paused_backend_restart failed for '
              '{research_id} — "\n'
              '                            "trying again shortly", "WARN")\n'
              "                        _retry_after_restart(_remark_after_restart(tree_uid, research_id))")
STOP_RETRY = ('                        log(f"Rehydrate: stop-mark failed for {research_id[:24]}… — "\n'
              '                            "trying again shortly", "WARN")\n'
              "                        _retry_after_restart(_remark_after_restart(tree_uid, research_id))")
MARK_ROUNDS = ("    for delay in _RESTART_RETRY_DELAYS_S:\n"
               "        await asyncio.sleep(delay)\n"
               "        withdrawn, record = await asyncio.to_thread(")
MARK_WITHDRAWN = ('            _pickup_withdrawn, tree_uid, research_id, "rehydrate-retry")\n'
                  "        if withdrawn:\n"
                  "            return False")
MARK_UNREAD = ("        if record is None:\n"
               "            continue\n"
               '        status = record.get("status")')
MARK_STATUS = ('        status = record.get("status")\n'
               '        if status != "ongoing":')
MARK_TAKEN = ("        why = _run_taken_since_boot(tree_uid, research_id, record,\n"
              '                                    _QUEUE_STATE.get("queue_ref"),\n'
              "                                    unstamped_is_worker_1=True)")
MARK_PATCH = ("        if await asyncio.to_thread(_update_research_doc, tree_uid, research_id,\n"
              "                                   _restart_recovery_patch(research_id)):")

# ── anchors: the Resume ─────────────────────────────────────────────────────
RESUME_DISK = "                    _on_disk = _run_dir_owning_research(target_rid, target_uid)"
RESUME_TAKE = "                    backend_run_id = _on_disk.name"
RESUME_NONE = ("                    if _on_disk is None:\n"
               "                        try: doc.reference.delete()\n"
               "                        except Exception: pass\n"
               "                        continue")

# ── anchors: the spawner ────────────────────────────────────────────────────
SPAWN = "        task = asyncio.get_running_loop().create_task(coro)"

MUTANTS = [
    # ══ 1. the funnel holds, and only what it could not see ════════════════
    ("H1", "under", "⛔⛔ the funnel says it holds and drops the job — the boot "
     "entry is lost at the next worker boundary, the defect itself",
     [(HOLD, "            if hold_unreadable is not None:\n"
             "                pass")],
     RESEARCH, PICKUP),
    ("H2", "over", "⛔⛔ a caller with a hold list TAKES the unreadable job — the "
     "boot restore relaunches a run whose status nobody saw (#728)",
     [(GATE, "        if not take_unreadable and hold_unreadable is None:")],
     RESEARCH, PICKUP),
    ("H3", "over", "an ANSWERED refusal is held too — a parked run is re-offered "
     "for the whole schedule and carried to every boot",
     [(STATUS, "            if status not in allowed_statuses:\n"
               "                if hold_unreadable is not None:\n"
               "                    hold_unreadable.append(job)")],
     RESEARCH, PICKUP),

    # ══ 2. the boot restore holds and starts the retry ══════════════════════
    ("R1", "under", "⛔⛔ the boot restore stops passing its hold list — back to "
     "a refusal that the next rewrite erases",
     [(RESTORE_CALL, '        if _safe_enqueue(job_queue, j, source="disk-restore",\n'
                     '                         allowed_statuses=("queued", "ongoing")):')],
     RESEARCH, PICKUP),
    ("R2", "under", "⛔ the held entry is never asked about again — it waits for a "
     "restart that may be days away",
     [(RESTORE_SPAWN, "    if False:\n"
                      "        _retry_after_restart(_reoffer_unread_restores(job_queue))")],
     RESEARCH, PICKUP),

    # ══ 3. the retry keeps #728 and ends on an answer ═══════════════════════
    ("Q1", "over", "⛔⛔ the retry takes the funnel's DEFAULT whitelist — a run "
     "rehydration parked for its person's Resume is relaunched (#728)",
     [(RETRY_CALL, '    took = _safe_enqueue(staged, job, source="disk-restore-retry",\n'
                   '                         hold_unreadable=unread, record_seen=record,')],
     RESEARCH, PICKUP),
    ("Q2", "over", "⛔⛔ the retry takes a job it still cannot check",
     [(RETRY_CALL, '    took = _safe_enqueue(staged, job, source="disk-restore-retry",\n'
                   '                         allowed_statuses=("queued", "ongoing"),\n'
                   "                         take_unreadable=True,\n"
                   '                         hold_unreadable=unread, record_seen=record,')],
     RESEARCH, PICKUP),
    ("Q3", "under", "⛔ the retry lets an entry go that never answered — dropped "
     "from memory, and from the file at the next rewrite",
     [(RETRY_LET_GO, '    if answer == "unread":\n'
                     '        pass\n'
                     '    try:\n'
                     '        _UNREAD_RESTORES.remove(job)')],
     RESEARCH, PICKUP),
    ("Q3b", "under", "the funnel's hold is read as a refusal — an unreadable "
     "entry is answered 'no' and let go",
     [(ASK_UNREAD, '    if False:\n'
                   '        return "unread", {}')],
     RESEARCH, PICKUP),
    ("Q4", "over", "an entry that got its answer stays held — re-offered every "
     "round and carried to every boot",
     [(RETRY_RELEASE, "    try:\n"
                      "        pass\n"
                      "    except ValueError:")],
     RESEARCH, PICKUP),
    ("Q4b", "over", "⛔ an entry Reset Backend drained is queued anyway when the "
     "settle's remove misses it — a run the reset just stopped starts",
     [(DRAINED_SINCE, "        pass\n"
                      '    if answer != "take":')],
     RESEARCH, PICKUP),
    ("Q5", "under", "the retry asks once and gives up — the schedule is one round",
     [(RETRY_ROUNDS, "    for delay in _RESTART_RETRY_DELAYS_S[:1]:\n"
                     "        await asyncio.sleep(delay)\n"
                     "        for job in list(_UNREAD_RESTORES):")],
     RESEARCH, PICKUP),
    ("Q6", "under", "⛔ the retry's whitelist drops 'ongoing' — a held mid-flight "
     "run is answered-refused, let go, and erased at the next rewrite",
     [(RETRY_CALL, '    took = _safe_enqueue(staged, job, source="disk-restore-retry",\n'
                   '                         allowed_statuses=("queued",),\n'
                   '                         hold_unreadable=unread, record_seen=record,')],
     RESEARCH, PICKUP),
    ("Q7", "over", "one entry's answer is taken for every entry of the round — an "
     "unreadable first entry keeps an answered one held, or the reverse",
     [(RETRY_READ, "                answer, record = await asyncio.wait_for(\n"
                   "                    asyncio.to_thread(_ask_about_held_entry, "
                   "_UNREAD_RESTORES[0]),\n"
                   "                    timeout=_RESTART_RETRY_READ_TIMEOUT_S)")],
     RESEARCH, PICKUP),
    # ⛔ Q8 IS RETIRED, NOT LOST. It removed the settle's membership check
    # before the remove; once the remove itself returns on a miss (Q4b's
    # decision) that check was redundant, so Q8 became an equivalent mutant —
    # and the check went, leaving the remove as the one guard.
    ("Q9", "over", "⛔ the read runs ON the loop — every held entry freezes the "
     "pipeline, the local API and the listeners for as long as it takes",
     [(RETRY_READ, "                answer, record = _ask_about_held_entry(job)")],
     RESEARCH, PICKUP),
    ("Q10", "under", "the read is unbounded — one that never returns holds up every "
     "other held entry and every later round",
     [(RETRY_READ, "                answer, record = await asyncio.to_thread("
                   "_ask_about_held_entry, job)")],
     RESEARCH, PICKUP),
    ("Q13", "under", "⛔ the re-offer's read is not told to give up — in an outage "
     "each one retries for 300 s, one more blocked thread per held entry per "
     "round in the shared executor",
     [(RETRY_READ_OPTIONS, "                         hold_unreadable=unread, "
                           "record_seen=record)")],
     RESEARCH, PICKUP),
    ("Q14", "under", "the read gets a deadline but keeps the client's retry — "
     "DeadlineExceeded is one of the errors it retries, for 300 s",
     [(RETRY_NO_RETRY, "                         read_options={")],
     RESEARCH, PICKUP),
    ("Q15", "under", "the funnel drops the read options it was handed — the "
     "re-offer's bound never reaches the read",
     [(FUNNEL_READ, '                .collection("researches").document(rid).get()')],
     RESEARCH, PICKUP),
    ("Q11", "over", "⛔⛔ the re-offer never asks whether somebody started the run "
     "since boot — one research runs twice",
     [(SETTLE_ASKS, "    why = None")],
     RESEARCH, PICKUP),
    ("Q12", "under", "the funnel stops handing back the record it read — the "
     "worker stamp is never seen, and a sibling's resumed run is started here",
     [(SEEN, "            if record_seen is not None:\n"
             "                pass")],
     RESEARCH, PICKUP),

    # ══ 3b. has somebody started the run since boot? ═══════════════════════
    ("T1", "over", "⛔⛔ a Resume on this computer is not asked about — a read "
     "landing before the Resume's job reaches the queue starts a second copy, or "
     "puts a Resume card over it",
     [(TAKEN_RESUMED, "    if False:")],
     RESEARCH, PICKUP),
    ("T2", "over", "⛔⛔ what this process holds is not asked about — a fresh copy "
     "is queued behind the resumed run, or behind the run already going",
     [(TAKEN_HELD, "    if False:")],
     RESEARCH, PICKUP),
    ("T3", "over", "⛔ a sibling's live lock is not asked about — a run a sibling "
     "is running is run here too, in the same folder",
     [(TAKEN_LOCK, "    holders = []")],
     RESEARCH, PICKUP),
    ("T4", "over", "⛔⛔ another worker's stamp is not asked about — a run a "
     "sibling resumed is started here, or marked for a Resume over its live run",
     [(TAKEN_OWNER, "        if False:")],
     RESEARCH, PICKUP),
    ("T5", "under", "the stamp rule loses the fleet bound — an orphan no live "
     "worker owns is let go, and its recovery mark never written",
     [(TAKEN_OWNER, "        if owner != WORKER_ID:")],
     RESEARCH, PICKUP),
    ("T6", "under", "⛔ the stamp is asked of a 'queued' record too — a stale stamp "
     "from an earlier start lets go of a run still waiting for its turn",
     [(TAKEN_ONGOING, "    if True:")],
     RESEARCH, PICKUP),
    ("T7", "under", "⛔⛔ the re-offer reads a missing stamp as worker 1 again — "
     "worker 2 lets go of its own mid-flight run, and nothing ever starts it",
     [(SETTLE_ASKS, '    why = _run_taken_since_boot((job or {}).get("uid"), rid, record, '
                    "job_queue,\n"
                    "                                unstamped_is_worker_1=True)")],
     RESEARCH, PICKUP),
    ("T9", "under", "⛔ what a Resume here started is matched on research id alone — "
     "another member's Resume of a research with the same id lets go of this "
     "person's held run, and ends this person's mark retry",
     [(TAKEN_RESUMED, "    if rid in {r for _u, r in _RESUMED_HERE}:")],
     RESEARCH, PICKUP),
    ("T10", "under", "⛔ what this process holds is matched on research id alone — "
     "another member's job for a research with the same id lets go of this "
     "person's held run",
     [(TAKEN_HELD, '    if any((j or {}).get("research_id") == rid\n'
                   "           for j in _jobs_held_locally(job_queue)):")],
     RESEARCH, PICKUP),
    ("T11", "over", "⛔⛔ the re-offer asks about nobody's run — a Resume here is "
     "never matched, and a held run it started is started a second time",
     [(SETTLE_ASKS, "    why = _run_taken_since_boot(None, rid, record, job_queue,\n"
                    "                                unstamped_is_worker_1=False)")],
     RESEARCH, PICKUP),
    ("T8", "under", "⛔ the stamp rule stops asking whether a stamp is there — the "
     "same let-go of worker 2's own unstamped run",
     [(TAKEN_STAMP, "        if False:\n"
                    "            return None")],
     RESEARCH, PICKUP),
    ("R3", "over", "⛔⛔ the Resume branch stops recording what it started — the "
     "retries cannot see a Resume whose job has not reached the queue yet",
     [(RESUME_RECORDS, "                pass")],
     RESEARCH, PICKUP),

    # ══ 4. every rewrite carries a held entry, once, and never a private one ═
    ("K1", "under", "⛔⛔ THE DEFECT: the writer stops carrying held entries — the "
     "first worker boundary erases the only description of the run",
     [(WRITER_CARRY, "    pending_jobs = list(pending_jobs or [])")],
     RESEARCH, PICKUP),
    ("K5", "over", "⛔ the carry ignores the running job — a held research that "
     "is running is written as current AND pending, two runs at the next boot",
     [(CARRY_CURRENT, "    pass")],
     RESEARCH, PICKUP),
    ("K6", "over", "the writer does not tell the carry what is running",
     [(WRITER_CARRY, "    pending_jobs = (list(pending_jobs or [])\n"
                     "                    + _unread_restores_to_carry(pending_jobs))")],
     RESEARCH, PICKUP),
    ("K7", "over", "the empty-queue rewrite does not tell the carry what is running",
     [(FORGET_CARRY, "    live += _unread_restores_to_carry(live)")],
     RESEARCH, PICKUP),
    ("K2", "under", "⛔ a rewrite with nothing queued deletes the file, held entry "
     "and all",
     [(FORGET_CARRY, "    pass")],
     RESEARCH, PICKUP),
    ("K3", "over", "⛔ no dedupe — a held entry is written twice, and two entries "
     "are two runs of one research at the next boot",
     [(CARRY_SKIP, "        if _is_incognito_research(rid):")],
     RESEARCH, PICKUP),
    ("K4", "over", "⛔⛔ a held run that keeps nothing is written to the disk",
     [(CARRY_SKIP, "        if rid in seen:")],
     RESEARCH, PICKUP),

    # ══ 5. Reset Backend takes held entries with the queue ══════════════════
    ("X1", "under", "⛔⛔ Reset Backend leaves a held entry — carried past the reset "
     "and run once a read sees 'queued'",
     [(RESET_DRAIN, "                    pass")],
     RESEARCH, PICKUP),
    ("X2", "under", "the reset stops the held run but keeps holding it — the "
     "reset's clean snapshot carries it back",
     [(RESET_DRAIN, "                    _drained_jobs.extend(_UNREAD_RESTORES)")],
     RESEARCH, PICKUP),

    # ══ 6. the rehydrate's recovery mark is written again ═══════════════════
    ("M1", "under", "⛔⛔ THE DEFECT: a failed Resume-card mark is never retried — "
     "the run sits 'ongoing' with nothing running it",
     [(PARK_RETRY, '                        log(f"Rehydrate: mark paused_backend_restart failed '
                   'for {research_id} — "\n'
                   '                            "trying again shortly", "WARN")')],
     RESEARCH, PICKUP),
    ("M2", "under", "⛔ a failed stop mark for a run that keeps nothing is never "
     "retried",
     [(STOP_RETRY, '                        log(f"Rehydrate: stop-mark failed for '
                   '{research_id[:24]}… — "\n'
                   '                            "trying again shortly", "WARN")')],
     RESEARCH, PICKUP),
    ("M3", "over", "the retry ignores the pickup rule — it writes to a research "
     "deleted since the scan",
     [(MARK_WITHDRAWN, '            _pickup_withdrawn, tree_uid, research_id, "rehydrate-retry")\n'
                       "        if False:\n"
                       "            return False")],
     RESEARCH, PICKUP),
    ("M4", "over", "⛔⛔ the retry marks a run the person stopped since — a stopped "
     "run is moved back to an offer of a Resume",
     [(MARK_STATUS, '        status = record.get("status")\n'
                    "        if False:")],
     RESEARCH, PICKUP),
    ("M5", "over", "⛔⛔ a record the retry cannot read is written blind — a run "
     "that finished or was stopped since is moved back to a Resume offer",
     [(MARK_UNREAD, "        if record is None:\n"
                    '            record = {"status": "ongoing"}\n'
                    '        status = record.get("status")')],
     RESEARCH, PICKUP),
    ("M5b", "under", "an unreadable round ends the retry — one more blip and the "
     "run stays unmarked until the next restart",
     [(MARK_UNREAD, "        if record is None:\n"
                    "            return False\n"
                    '        status = record.get("status")')],
     RESEARCH, PICKUP),
    ("M6", "over", "⛔⛔ the mark retry never asks whether somebody started the run "
     "since boot — a Resume card over a live run, here or on a sibling",
     [(MARK_TAKEN, "        why = None")],
     RESEARCH, PICKUP),
    ("M7", "under", "the mark retry tries once and gives up",
     [(MARK_ROUNDS, "    for delay in _RESTART_RETRY_DELAYS_S[:1]:\n"
                    "        await asyncio.sleep(delay)\n"
                    "        withdrawn, record = await asyncio.to_thread(")],
     RESEARCH, PICKUP),
    ("M8", "over", "⛔ the retry writes a Resume offer for every run — a run that "
     "keeps nothing is parked behind a card nobody can reach",
     [(MARK_PATCH, "        if await asyncio.to_thread(_update_research_doc, tree_uid, research_id,\n"
                   '                                   {"status": "paused_backend_restart"}):')],
     RESEARCH, PICKUP),

    # ══ 7. the Resume asks the disk ═════════════════════════════════════════
    ("C1", "under", "⛔⛔ THE DEFECT: a failed read drops the Resume without asking "
     "the disk — the press does nothing while the card stays up",
     [(RESUME_DISK, "                    _on_disk = None")],
     RESEARCH, PICKUP),
    ("C2", "over", "a run id is written into a record nobody could read",
     [(RESUME_TAKE, "                    backend_run_id = _on_disk.name\n"
                    "                    _update_research_doc(target_uid, target_rid,\n"
                    '                                         {"backendRunId": backend_run_id})')],
     RESEARCH, PICKUP),
    ("C3", "over", "⛔⛔ with nothing on the disk a failed read is reported as a "
     "failed run — 'no saved checkpoint', and auto-resume closed",
     [(RESUME_NONE, "                    if _on_disk is None:\n"
                    "                        _resume_drop_writeback(target_uid, target_rid, "
                    "RESUME_DROP_NO_RUN_ID)\n"
                    "                        try: doc.reference.delete()\n"
                    "                        except Exception: pass\n"
                    "                        continue")],
     RESEARCH, PICKUP),
    ("C4", "over", "⛔ with nothing on the disk the Resume doc is left in place — "
     "it replays at the next attach, possibly after the run finished",
     [(RESUME_NONE, "                    if _on_disk is None:\n"
                    "                        continue")],
     RESEARCH, PICKUP),

    # ══ 8. the spawner ══════════════════════════════════════════════════════
    ("S1", "under", "⛔ the spawner starts nothing — every retry is written and "
     "none of them runs",
     [(SPAWN, '        raise RuntimeError("no running loop")')],
     RESEARCH, PICKUP),
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
