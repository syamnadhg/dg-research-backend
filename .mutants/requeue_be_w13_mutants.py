"""Mutation harness — wave 13, "Move to queue" (the research computer's side).

⛔⛔ WHAT THIS CODE DECIDES.
  H* — the owner's "requeue" command, on the worker it names: only the owner,
       only the run that worker is running (research AND account), never a run
       that keeps nothing, one already handed to the cloud, or one on a backend
       started by hand. A move keeps everything, puts the run at #1 with its
       record queued, cuts the pipeline's own last writes off, keeps the worker
       off, publishes the order and restarts the worker — no stop, no `.stop`.
  G* — every worker is its own process on one command stream: only the named
       worker takes the command; a command naming no worker goes to worker 1.
  W* — the waiting runs, front first: the latest move leads; a damaged marker
       never stops the reader.
  C* — the next AWAKE worker takes one: a run a live worker holds is put back
       and keeps its place; a run nobody waits for stops waiting; a record the
       move never reached is still taken; the record says "running, here" only
       once the job is really queued.
  S* — the idle rescan takes a waiting run before any deferred start, on any
       worker count, and a deferred start is never claimed past one.
  L* — a new start waits behind a waiting run.
  E* — the published order: waiting runs first, everything else moves down.
  F* — boot rehydration: a resting worker parks its interrupted run; a run
       waiting in the queue is left there.
  T* — the boot restore: the queue's run is not restored or aged out; a
       resting worker's interrupted run is parked.
  K* — the startup sweep keeps a waiting run's folder.
  X* — Clear Local Storage keeps every run running or waiting, on ANY worker.
  Z* — Reset Backend ends the waiting runs too.
  Y* — the capability the app reads, in its own write.
  R* — the repair after review (rv13, 09-29): the move takes the run out of its
       old worker's snapshot; the boot restore and rehydration leave a run
       another worker runs or has taken; a run out of automatic attempts is
       never parked and, if it waited, gets its Resume card; a stop or cancel
       of a waiting run ends it as a running run's is (and every worker's copy
       writes the same); a run ended for good stops waiting; a resting
       worker's queued jobs wait behind, exactly as they were queued; the
       claim survives a leftover taken marker on Windows.

⛔ NO SOURCE PIN SITS IN THE TEST SET's KILLS. Every mutant here dies on
behaviour: the real device-command listener, the real idle rescan and worker
loop (lifted from `run_server`), the real start listener, boot rehydration,
the boot restore on a real file, the startup sweep, the queue publisher and
the heartbeat loop — against fakes of Firestore and a temporary disk.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/requeue_be_w13_mutants.py
  .venv/bin/python .mutants/requeue_be_w13_mutants.py H1 C2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

TESTS = ["tests/test_requeue_w13.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors used by more than one mutant ─────────────────────────────────────
OWNER_CHECK = "    if not who or who != owner:"
RUN_MATCH = ('    if (not rid or current.get("research_id") != rid\n'
             '            or str(current.get("uid") or "") != uid):')
EXITING = ('    if _exit_scheduled:\n'
           '        log(f"[device-cmds] REQUEUE: ignored — worker {WORKER_ID} is already "')
DETACH = ("    if _fb_research_id == rid:\n"
          "        _fb_uid = None\n"
          "        _fb_research_id = None\n")
RECORD = "    _update_research_doc(uid, rid, _waiting_record_patch())\n    _keep_worker_resting(WORKER_ID)"
EXIT = '    _schedule_server_exit("requeue", delay_sec=1.5)'
GATE = ("            elif (action == REQUEUE_ACTION\n"
        "                    and _requeue_target_worker(data) != WORKER_ID):")
SORT = '    out.sort(key=lambda r: (-r["moved_at_ms"], r["_dir"].name))'
CLAIM_STATUS = ('        if withdrawn or (record is not None and status not in '
                '("queued", "ongoing")):')
OFFER = "        if _front_waiting:\n            await _offer_waiting_run(_job_queue)\n            return"
EMPTY_PUBLISH = ("        # stale amber badges when the local deque drained too). Best-effort.\n"
                 "        try:\n"
                 '            _firebase_db.collection("devices").document(device_id).update(\n'
                 '                {"queueOwners": _front_owners + _local_owners})\n'
                 "        except Exception:\n"
                 "            pass\n"
                 "        _commit_queue_position_patches(_front_patches)\n")
FILTERED_PUBLISH = ("        # the local deque is empty too). Best-effort.\n"
                    "        try:\n"
                    '            _firebase_db.collection("devices").document(device_id).update(\n'
                    '                {"queueOwners": _front_owners + _local_owners})\n')
REHYDRATE_WAITING = ("                if _run_dir_waiting(_queue_dir_now):\n"
                     "                    _update_research_doc(tree_uid, research_id, "
                     "_waiting_record_patch())\n")
REHYDRATE_PARK = ("                                elif (await asyncio.to_thread(_worker_is_resting)\n"
                  "                                      and await asyncio.to_thread(\n")
RESTORE_WAITING = ("        if _run_dir_held_by_queue(_job_run_dir(j)):\n"
                   '            log(f"[pending_queue] {rid[:24]}… is waiting in the queue for a worker, "\n'
                   '                f"or one has taken it — left there", "INFO")\n'
                   "            skipped += 1\n"
                   "            withdrew = True\n"
                   "            continue\n")
RESTORE_PARK = ("        if (_worker_is_resting()\n"
                '                and (record or {}).get("status") in ("queued", "ongoing")\n')
RESTORE_TAKEN = ('        if why is not None:\n'
                 '            log(f"[pending_queue] {rid[:24]}… not restored — {why}", "INFO")\n')
PARK_REFUSAL = ('    if run_dir is not None and ((run_dir / ".stop").exists()\n'
                '                                or _no_auto_retry_marked(run_dir)):')
BEHIND_STATUS = ('        if status != "queued":\n'
                 '            _update_research_doc(str(job.get("uid") or ""), rid, {"status": "queued"})\n')
MOVED_CANCEL = ('                                        "summary": "Cancelled",\n'
                '                                        "cancelled": True,\n'
                '                                        "queuePosition": _DF,\n'
                '                                        "queuedBehindRunId": _DF,\n'
                '                                        "queuedBehindTitle": _DF,\n'
                '                                    }, movedToQueueAt=_DF))\n')
STOP_TOUCH = ('        try:\n            (d / ".stop").touch()\n        except Exception as e:\n'
              '            log(f"[moved-run] could not end {d.name}: {e}", "WARN")\n')
IN_USE_LOCK = ('                alive = bool(data.get("pid")) and _ps.pid_exists(int(data["pid"]))\n')

MUTANTS = [
    # ═══ H — the command, on the worker it names ═════════════════════════════
    ("H1", RESEARCH, "⛔⛔ anybody's command moves the run — a sharer moves the owner's",
     [(OWNER_CHECK, "    if False:")]),
    ("H2", RESEARCH, "⛔ an UNSIGNED command moves the run",
     [(OWNER_CHECK, "    if who and who != owner:")]),
    ("H3", RESEARCH, "⛔⛔ the research alone is matched — a command naming another "
     "account's research id moves this run",
     [(RUN_MATCH, '    if (not rid or current.get("research_id") != rid):')]),
    ("H4", RESEARCH, "a second press while the worker is leaving moves it again",
     [(EXITING, "    if False:\n"
                '        log(f"[device-cmds] REQUEUE: ignored — worker {WORKER_ID} is already "')]),
    ("H5", RESEARCH, "⛔ a run that keeps nothing is parked on disk to wait",
     [("    if _is_incognito_research(rid):\n"
       '        log(f"[device-cmds] REQUEUE: ignored — {rid[:8]}… keeps nothing, so it "',
       "    if False:\n"
       '        log(f"[device-cmds] REQUEUE: ignored — {rid[:8]}… keeps nothing, so it "')]),
    ("H6", RESEARCH, "a run already handed to the cloud is moved back to the queue",
     [("    if _handed_off_to_cloud(_job_run_dir(current)):", "    if False:")]),
    ("H7", RESEARCH, "⛔⛔ a backend started by hand exits — and nothing brings it back",
     [('    if not _supervisor_is_my_parent():\n'
       '        log(f"[device-cmds] REQUEUE: ignored — this backend is not running on "',
       '    if False:\n'
       '        log(f"[device-cmds] REQUEUE: ignored — this backend is not running on "')]),
    ("H8", RESEARCH, "⛔ the pipeline's last second writes \"ongoing\" over the queued record",
     [(DETACH, "")]),
    ("H9", RESEARCH, "⛔⛔ the record is never told it is queued — the person sees it running",
     [(RECORD, "    _keep_worker_resting(WORKER_ID)")]),
    ("H10", RESEARCH, "the worker is not kept off — a lost app write brings it back to "
     "take its own run", [("    _keep_worker_resting(WORKER_ID)\n    _publish_queue_positions_now()",
                           "    _publish_queue_positions_now()")]),
    ("H11", RESEARCH, "the order is not published before the exit — no amber pill",
     [("    _keep_worker_resting(WORKER_ID)\n    _publish_queue_positions_now()",
       "    _keep_worker_resting(WORKER_ID)")]),
    ("H12", RESEARCH, "⛔⛔ the worker never lets the run go — it keeps running while queued",
     [(EXIT, "    pass")]),
    ("H13", RESEARCH, "OVER-REACH: a stop is requested — \"stopped\" is written over the run",
     [(EXIT, "    _controls.request_stop()\n" + EXIT)]),
    ("H14", RESEARCH, "⛔ OVER-REACH: the run is ended for good (`.stop`) — nothing can "
     "take it", [(EXIT, '    (_job_run_dir(current) / ".stop").touch()\n' + EXIT)]),
    ("H15", RESEARCH, "the marker drops the delivery address — the resumed run emails nobody",
     [('        "email": str(job.get("email") or ""),\n        "config": dict(job.get("config") or {}),',
       '        "email": "",\n        "config": dict(job.get("config") or {}),')]),
    ("H16", RESEARCH, "a queued record keeps its decision card up",
     [('        "pendingDecision": _DF,\n        "queueEtaMs": _DF,', '        "queueEtaMs": _DF,')]),
    ("H17", RESEARCH, "⛔ the dispatch never runs — the command is taken and nothing happens",
     [("            if action == REQUEUE_ACTION:\n", "            if False:\n")]),

    # ═══ G — one worker's command ═════════════════════════════════════════════
    ("G1", RESEARCH, "⛔⛔ every worker takes the command — the one it names may never see it",
     [(GATE, "            elif (action == REQUEUE_ACTION\n                    and False):")]),
    ("G2", RESEARCH, "a command naming no worker is left for nobody, for ever",
     [("    return n if 1 <= n <= fleet else 1", "    return n")]),

    # ═══ W — the waiting runs, front first ═══════════════════════════════════
    ("W1", RESEARCH, "⛔ the OLDEST move leads — the owner's #1 is somebody else's",
     [(SORT, '    out.sort(key=lambda r: (r["moved_at_ms"], r["_dir"].name))')]),
    ("W2", RESEARCH, "the move's time is not written — every move ties",
     [('        "moved_at_ms": (min([w["moved_at_ms"] for w in _waiting_runs()] + [now_ms]) - 1\n'
       '                        if behind else now_ms),\n        "from_worker": int(from_worker),',
       '        "from_worker": int(from_worker),')]),
    ("W3", RESEARCH, "⛔ a marker with an odd time stops the reader — and every start",
     [('        rec["moved_at_ms"] = moved if isinstance(moved, int) and not isinstance(moved, bool) '
       'else 0\n', "")]),
    ("W4", RESEARCH, "a marker that is not an object stops the reader",
     [("        if not isinstance(rec, dict):\n            continue\n        moved = ",
       "        moved = ")]),

    # ═══ C — the next awake worker takes one ══════════════════════════════════
    ("C1", RESEARCH, "⛔⛔ a run its old worker still holds is taken — two browsers on one run",
     [("        if _scan_sibling_locks_for_research(rid, worker_id):\n            try:",
       "        if False:\n            try:")]),
    ("C2", RESEARCH, "⛔ a record the move never reached is dropped — the run is lost",
     [(CLAIM_STATUS, '        if withdrawn or (record is not None and status not in ("queued",)):')]),
    ("C3", RESEARCH, "⛔ a stopped or finished run is taken and run again",
     [(CLAIM_STATUS, "        if withdrawn:")]),
    ("C4", RESEARCH, "a run put back loses its marker — it never waits again",
     [("                os.replace(taken, d / WAITING_MARKER)\n            except Exception:\n"
       "                pass\n            continue\n        withdrawn, record",
       "                pass\n            except Exception:\n"
       "                pass\n            continue\n        withdrawn, record")]),
    ("C5", RESEARCH, "a run a sibling took first ends the search — the next one waits a tick",
     [("            continue  # a sibling worker took it first", "            return None")]),
    ("C6", RESEARCH, "the taken job has no folder to resume from — it starts over",
     [('            "resume_dir": str(d),\n', "")]),
    ("C7", RESEARCH, "the taken job is not marked as one — the dequeue leaves it looking "
     "taken for ever", [('            "moved_run": True,\n', "")]),
    ("C8", RESEARCH, "⛔ the record is never told who runs it — it still reads queued",
     [('        "status": "ongoing", "assignedWorker": WORKER_ID,\n',
       '        "assignedWorker": WORKER_ID,\n')]),
    ("C9", RESEARCH, "the record does not name the worker — a restart resumes it on the "
     "wrong accounts", [('        "status": "ongoing", "assignedWorker": WORKER_ID,\n',
                         '        "status": "ongoing",\n')]),
    ("C10", RESEARCH, "a run the funnel refused is left half-taken, holding its folder",
     [("        await asyncio.to_thread(_drop_waiting_claim, run_dir, WORKER_ID)\n", "")]),
    ("C11", RESEARCH, "the rest of the queue does not move up after a run is taken",
     [("    _kick_queue_publish()\n    return True\n\n\ndef _publish_queue_positions_now",
       "    return True\n\n\ndef _publish_queue_positions_now")]),
    ("C12", RESEARCH, "⛔ the record is told \"running\" before the funnel answers",
     [("    job = await asyncio.to_thread(_claim_waiting_run, WORKER_ID)\n"
       "    if job is None:\n        return False\n",
       "    job = await asyncio.to_thread(_claim_waiting_run, WORKER_ID)\n"
       "    if job is None:\n        return False\n"
       "    await asyncio.to_thread(_update_research_doc, job[\"uid\"], "
       "job[\"research_id\"], {\"status\": \"ongoing\"})\n")]),
    ("C13", RESEARCH, "the dequeue never lets the taken marker go",
     [("                _drop_waiting_claim(_job_run_dir(job), WORKER_ID)\n", "                pass\n")]),
    ("C14", RESEARCH, "boot puts back EVERY worker's taken runs, not only its own",
     [("        taken = d / _waiting_taken_name(worker_id)\n        try:\n            if taken.exists():",
       "        taken = next(iter(d.glob(f\"{WAITING_MARKER}.w*\")), d / \"_none_\")\n"
       "        try:\n            if taken.exists():")]),
    ("C15", RESEARCH, "runs put back at boot are not re-published",
     [("            f\"started are back in the queue\", \"INFO\")\n        _kick_queue_publish()\n",
       "            f\"started are back in the queue\", \"INFO\")\n")]),

    # ═══ S — the idle rescan ═════════════════════════════════════════════════
    ("S1", RESEARCH, "⛔ a single-worker computer never takes it — it waits for ever",
     [("        if load_worker_count() <= 1 and not _REST_DEFER_SEEN[\"v\"] and not _front_waiting:",
       "        if load_worker_count() <= 1 and not _REST_DEFER_SEEN[\"v\"]:")]),
    ("S2", RESEARCH, "⛔⛔ a deferred start is claimed past a run that could not be taken yet",
     [(OFFER, "        if _front_waiting and await _offer_waiting_run(_job_queue):\n            return")]),
    ("S3", RESEARCH, "⛔⛔ the rescan never offers the waiting run — deferred starts go first",
     [(OFFER, "        if False:\n            await _offer_waiting_run(_job_queue)\n            return")]),

    # ═══ L — a new start waits behind it ═════════════════════════════════════
    ("L1", RESEARCH, "⛔ a new start runs ahead of the moved run",
     [("                if (_resting\n                        or _front_waiting\n",
       "                if (_resting\n")]),
    ("L2", RESEARCH, "the waiting run is never seen by the start listener",
     [("            _front_waiting = bool(_waiting_runs())", "            _front_waiting = False")]),
    ("L3", RESEARCH, "a single worker skips the defer entirely — the start runs first",
     [("            if _resting or _front_waiting:\n                _REST_DEFER_SEEN[\"v\"] = True",
       "            if _resting:\n                _REST_DEFER_SEEN[\"v\"] = True")]),

    # ═══ E — the published order ═════════════════════════════════════════════
    ("E1", RESEARCH, "⛔ waiting runs are missing from `queueOwners` — no amber pill",
     [('            "queueOwners": _front_owners + _local_owners + _queue_owners,',
       '            "queueOwners": _local_owners + _queue_owners,')]),
    ("E2", RESEARCH, "⛔ everything else does not move down — two runs read #1",
     [("    _local_offset = len(_front_owners) + len(_local_owners)",
       "    _local_offset = len(_local_owners)")]),
    ("E3", RESEARCH, "with nothing else queued, the moved run is not published",
     [(EMPTY_PUBLISH, EMPTY_PUBLISH.replace("_front_owners + _local_owners", "_local_owners"))]),
    ("E4", RESEARCH, "with nothing else queued, the moved run's record gets no position",
     [(EMPTY_PUBLISH, EMPTY_PUBLISH.replace(
         "        _commit_queue_position_patches(_front_patches)\n", ""))]),
    ("E5", RESEARCH, "the waiting runs' records are never renumbered",
     [("    _commit_queue_position_patches(_front_patches + patches)",
       "    _commit_queue_position_patches(patches)")]),
    ("E6", RESEARCH, "the head deferred start says it waits behind nothing",
     [('                "queuedBehindRunId": (_front_owners + _local_owners)[-1]["runId"],',
       '                "queuedBehindRunId": "",')]),
    ("E7", RESEARCH, "runs waiting ahead are not counted by whose they are",
     [("        for _lo in _front_owners + _local_owners:", "        for _lo in _local_owners:")]),
    ("E8", RESEARCH, "⛔⛔ the renumber writes \"queued\" — a run taken meanwhile is put "
     "back in the queue", [('            "queuePosition": i + 1,\n            "queueTotalAhead": i,',
                            '            "status": "queued",\n            "queuePosition": i + 1,\n'
                            '            "queueTotalAhead": i,')]),
    ("E9", RESEARCH, "the second waiting run says it waits behind nothing",
     [('            "queuedBehindRunId": (str(front[i - 1].get("research_id") or "")\n'
       '                                  if i else _DF),',
       '            "queuedBehindRunId": _DF,')]),
    ("E10", RESEARCH, "with only claimed documents, the moved run is not published",
     [(FILTERED_PUBLISH, FILTERED_PUBLISH.replace("_front_owners + _local_owners", "_local_owners"))]),
    ("E11", RESEARCH, "a waiting run's own account is counted as someone else's",
     [('        mine = sum(1 for a in front[:i] if str(a.get("uid") or "") == uid_v)',
       "        mine = 0")]),

    # ═══ F — boot rehydration ═════════════════════════════════════════════════
    ("F1", RESEARCH, "⛔⛔ a resting worker resumes its interrupted run anyway",
     [(REHYDRATE_PARK, "                                elif (False\n"
                       "                                      and await asyncio.to_thread(\n")]),
    ("F2", RESEARCH, "⛔ OVER-REACH: every worker parks — nothing resumes at boot",
     [(REHYDRATE_PARK, "                                elif (True\n"
                       "                                      and await asyncio.to_thread(\n")]),
    ("F3", RESEARCH, "⛔⛔ a run waiting in the queue is resumed at boot — twice, or on a "
     "worker that is off", [(REHYDRATE_WAITING, "                if False:\n"
                             "                    _update_research_doc(tree_uid, research_id, "
                             "_waiting_record_patch())\n")]),
    ("F4", RESEARCH, "a waiting run's record is left reading \"ongoing\"",
     [(REHYDRATE_WAITING, REHYDRATE_WAITING.replace(
         "                    _update_research_doc(tree_uid, research_id, _waiting_record_patch())\n",
         ""))]),
    ("F5", RESEARCH, "boot's re-queued run is not re-published",
     [('                        f"a worker — left there", "INFO")\n                    _kick_queue_publish()\n',
       '                        f"a worker — left there", "INFO")\n')]),
    ("F6", RESEARCH, "a parked run's record is left reading \"ongoing\"",
     [("        _update_research_doc(str(job.get(\"uid\") or \"\"), rid, _waiting_record_patch())\n",
       "        pass\n")]),
    ("F7", RESEARCH, "a parked run is not published — no pill until something else moves",
     [('            f"worker that is on", "INFO")\n    _kick_queue_publish()\n    return True\n',
       '            f"worker that is on", "INFO")\n    return True\n')]),

    # ═══ T — the boot restore ═════════════════════════════════════════════════
    ("T1", RESEARCH, "⛔⛔ the moved run is restored onto the worker that was turned off",
     [(RESTORE_WAITING, "")]),
    ("T2", RESEARCH, "⛔ the moved run is judged by its age first — a week's wait drops it",
     [(RESTORE_WAITING, ""),
      ("            skipped += 1\n            withdrew = True\n            continue\n"
       "        # ⛔⛔ NOT ONE OF THIS COMPUTER'S ACCOUNTS",
       "            skipped += 1\n            withdrew = True\n            continue\n"
       + RESTORE_WAITING + "        # ⛔⛔ NOT ONE OF THIS COMPUTER'S ACCOUNTS")]),
    ("T3", RESEARCH, "⛔⛔ a resting worker's queued jobs go into its own line — the worker "
     "that is off runs them while the order shows them waiting",
     [(RESTORE_PARK, RESTORE_PARK.replace("        if (_worker_is_resting()",
                                          "        if (j is cur and _worker_is_resting()"))]),
    ("T4", RESEARCH, "⛔ a resting worker restores its interrupted run from the snapshot",
     [(RESTORE_PARK, RESTORE_PARK.replace("        if (_worker_is_resting()",
                                          "        if (False"))]),

    # ═══ K — the startup sweep ════════════════════════════════════════════════
    ("K1", RESEARCH, "⛔⛔ a week of resting workers and the sweep deletes the checkpoint",
     [("                if _run_dir_held_by_queue(d):\n                    continue\n", "")]),
    ("K2", RESEARCH, "a run taken but not started loses its folder",
     [('        return (d / WAITING_MARKER).exists() or any(d.glob(f"{WAITING_MARKER}.w*"))',
       "        return (d / WAITING_MARKER).exists()")]),

    # ═══ X — Clear Local Storage ══════════════════════════════════════════════
    ("X1", RESEARCH, "⛔⛔ the idle worker keeps only its own run — the busy one's is deleted",
     [("                            if entry.name in in_use:",
       "                            if _tracks_dir is not None and entry.name == _tracks_dir.name:")]),
    ("X2", RESEARCH, "another worker's live run is not seen",
     [('        if alive and data.get("run_id"):', "        if False:")]),
    ("X3", RESEARCH, "a dead worker's lock keeps a folder for ever",
     [(IN_USE_LOCK, "                alive = True\n")]),
    ("X4", RESEARCH, "⛔ the runs every worker has waiting in its line are not seen",
     [("            jobs.append(s.get(\"current\") or {})\n            jobs.extend(s.get(\"pending\") or [])\n",
       "            pass\n")]),
    ("X5", RESEARCH, "⛔ a run waiting for a worker is deleted",
     [("    names.update(d.name for d in dirs if _run_dir_held_by_queue(d))\n", "")]),

    # ═══ Z — Reset Backend ════════════════════════════════════════════════════
    ("Z1", RESEARCH, "⛔ Reset Backend leaves the waiting runs — they run after the reset",
     [("                    _drained_jobs.extend(_drain_waiting_runs())\n", "")]),
    ("Z2", RESEARCH, "a drained waiting run is not ended for good",
     [(STOP_TOUCH + "        for m in markers:\n", "        for m in markers:\n")]),
    ("Z3", RESEARCH, "⛔ a run another worker took and has not started survives the reset",
     [("        markers = [d / WAITING_MARKER] + list(d.glob(f\"{WAITING_MARKER}.w*\"))\n",
       "        markers = [d / WAITING_MARKER]\n")]),

    # ═══ R — the repair after review ══════════════════════════════════════════
    # the old worker's snapshot, and the boot that reads it
    ("R1", RESEARCH, "⛔⛔ the old worker's snapshot still names the moved run — its boot "
     "puts it back or runs it a second time",
     [("    _forget_running_job_in_snapshot()\n    _update_research_doc(uid, rid, _waiting_record_patch())\n",
       "    _update_research_doc(uid, rid, _waiting_record_patch())\n")]),
    ("R2", RESEARCH, "the move writes back a line Reset Backend is clearing",
     [('            if not _QUEUE_STATE.get("_hard_reset_in_progress"):\n'
       '                persist(current_job=None)',
       '            if True:\n                persist(current_job=None)')]),
    ("R3", RESEARCH, "⛔ a run another worker has taken (not started) is restored or parked "
     "from a stale snapshot", [(RESTORE_WAITING, RESTORE_WAITING.replace(
         "_run_dir_held_by_queue(_job_run_dir(j))", "_run_dir_waiting(_job_run_dir(j))"))]),
    ("R4", RESEARCH, "⛔⛔ a run another worker is running is put back at #1, or started "
     "a second time", [(RESTORE_TAKEN, RESTORE_TAKEN.replace(
         "        if why is not None:\n", "        if False:\n"))]),
    ("R5", RESEARCH, "a record with no worker named reads as worker 1's — worker 2 lets its "
     "own run go", [("        why = _run_taken_since_boot((j or {}).get(\"uid\"), rid, record, job_queue,\n"
                     "                                    unstamped_is_worker_1=False)\n",
                     "        why = _run_taken_since_boot((j or {}).get(\"uid\"), rid, record, job_queue,\n"
                     "                                    unstamped_is_worker_1=True)\n")]),
    ("R6", RESEARCH, "⛔ a Resume card or a stop is written over with \"queued\" by a stale "
     "snapshot", [(RESTORE_PARK, "        if (_worker_is_resting()\n")]),
    ("R7", RESEARCH, "⛔ the queued jobs go to the FRONT — ahead of the run that was running",
     [("behind=j is not cur,", "behind=False,")]),
    # a run out of automatic attempts
    ("R8", RESEARCH, "⛔ a run ended for good is parked — its stop is written over",
     [(PARK_REFUSAL, PARK_REFUSAL.replace('((run_dir / ".stop").exists()', "(False"))]),
    ("R9", RESEARCH, "⛔⛔ a run out of attempts is parked — its Retry card is taken away and "
     "it waits for ever", [(PARK_REFUSAL, PARK_REFUSAL.replace(
         "or _no_auto_retry_marked(run_dir)", "or False"))]),
    ("R10", RESEARCH, "⛔ a run that keeps nothing is written to disk to wait, brief and all",
     [("    if _is_incognito_research(rid):\n        return False\n    run_dir = _job_run_dir(job)\n",
       "    run_dir = _job_run_dir(job)\n")]),
    ("R11", RESEARCH, "⛔⛔ a waiting run out of attempts is left \"queued\" for ever",
     [("            await asyncio.to_thread(_update_research_doc, job[\"uid\"], rid,\n"
       "                                    _restart_recovery_patch(rid))\n", "")]),
    ("R12", RESEARCH, "a Resume card is written over a run stopped while it was being taken",
     [('        if (run_dir is not None and not (run_dir / ".stop").exists()\n'
       '                and _no_auto_retry_marked(run_dir)):',
       '        if (run_dir is not None\n                and _no_auto_retry_marked(run_dir)):')]),
    ("R13", RESEARCH, "the Resume card is written and the queue order is not re-published",
     [('                f"offered to its person to resume instead", "INFO")\n'
       '            _kick_queue_publish()\n',
       '                f"offered to its person to resume instead", "INFO")\n')]),
    # a waiting run ended for good
    ("R14", RESEARCH, "⛔⛔ a run ended for good stays #1 and holds every new start back",
     [('            if (d / ".stop").exists():\n                _retire_waiting_marker(marker)\n'
       '                continue\n', "")]),
    ("R15", RESEARCH, "a run ended for good keeps its folder for ever",
     [("                _retire_waiting_marker(marker)\n", "                pass\n")]),
    # stopping or cancelling a waiting run
    ("R16", RESEARCH, "⛔⛔ a cancelled waiting run is not ended — the next worker takes it",
     [(STOP_TOUCH + "        for m in live:\n", "        for m in live:\n")]),
    ("R17", RESEARCH, "a cancelled run still reads as waiting or taken",
     [("        for m in live:\n            _retire_waiting_marker(m)\n",
       "        for m in live:\n            pass\n")]),
    ("R18", RESEARCH, "⛔ the second worker's copy of the cancel writes the purge over it",
     [("            names = live + ([ended] if ended.exists() else [])\n",
       "            names = live\n")]),
    ("R19", RESEARCH, "⛔⛔ a waiting run's cancel purges a run with finished steps; the "
     "owner's Stop is dropped", [("                        elif _waiting_rec is not None or removed_taken:\n",
                                  "                        elif False:\n")]),
    ("R20", RESEARCH, "a run taken into this worker's line is cancelled as one that never ran",
     [("                        removed_taken = any(_cancels(j) and j.get(\"moved_run\") for j in dq)\n",
       "                        removed_taken = False\n")]),
    ("R21", RESEARCH, "a job that was only queued is ended as a running run — no phase reset",
     [('                        if _waiting_rec is not None and _waiting_rec.get("queued_job") is not None:\n',
       "                        if False:\n")]),
    ("R22", RESEARCH, "a cancel of a later start of the same research ends the old run instead",
     [("                                        if _start_doc_id is None and (removed_taken or not removed)\n",
       "                                        if (removed_taken or not removed)\n")]),
    ("R23", RESEARCH, "a cancelled waiting run stays the amber #1 until something else moves",
     [("                                    }, movedToQueueAt=_DF))\n                            _kick_queue_publish()\n",
       "                                    }, movedToQueueAt=_DF))\n")]),
    ("R24", RESEARCH, "a cancelled queued job is not taken out of the published order",
     [("                            removed = True\n                            _kick_queue_publish()\n",
       "                            removed = True\n")]),
    ("R25", RESEARCH, "a stopped run still reads as moved to the queue",
     [(MOVED_CANCEL, MOVED_CANCEL.replace("}, movedToQueueAt=_DF))", "}))"))]),
    ("R26", RESEARCH, "⛔ the owner's cancel resets the steps of a run with work in it",
     [("                                    _owner_control_patch(oc, running=True) or {\n",
       "                                    _owner_control_patch(oc, running=False) or {\n")]),
    ("R27", RESEARCH, "⛔ the person's own cancel resets the steps of a run with work in it",
     [(MOVED_CANCEL, MOVED_CANCEL.replace('"summary": "Cancelled",\n',
                                          '"summary": "Cancelled",\n"phase": 0,\n'))]),
    # the claim and the park
    ("R28", RESEARCH, "⛔ Windows: a leftover taken marker stalls this worker for good",
     [("            os.replace(d / WAITING_MARKER, taken)\n",
       "            os.rename(d / WAITING_MARKER, taken)\n")]),
    ("R29", RESEARCH, "a leftover taken marker stays beside the new one",
     [("        for stale in run_dir.glob(f\"{WAITING_MARKER}.w*\"):\n"
       "            stale.unlink(missing_ok=True)\n", "")]),
    # a resting worker's own line
    ("R30", RESEARCH, "⛔ a queued job with no folder yet cannot wait — the worker that is "
     "off runs it", [("    if behind and not run_dir.exists():\n", "    if False:\n")]),
    ("R31", RESEARCH, "⛔ the queued jobs jump the run that was running",
     [('        "moved_at_ms": (min([w["moved_at_ms"] for w in _waiting_runs()] + [now_ms]) - 1\n'
       '                        if behind else now_ms),\n',
       '        "moved_at_ms": now_ms,\n')]),
    ("R32", RESEARCH, "⛔⛔ a queued job loses what it was sent with — it resumes an empty "
     "folder, with no brief", [('    if behind:\n        rec["queued_job"] = dict(job)\n', "")]),
    ("R33", RESEARCH, "the taking worker ignores the job as it was queued",
     [("        if isinstance(queued_job, dict):\n", "        if False:\n")]),
    ("R34", RESEARCH, "a queued job taken from the queue still reads as taken once started",
     [("                        queued_at_ms=int(time.time() * 1000), moved_run=True)\n",
       "                        queued_at_ms=int(time.time() * 1000))\n")]),
    ("R35", RESEARCH, "a record that already says queued is written again",
     [(BEHIND_STATUS, BEHIND_STATUS.replace('        if status != "queued":\n', "        if True:\n"))]),
    ("R36", RESEARCH, "a queued Resume waiting behind still reads as running",
     [(BEHIND_STATUS, BEHIND_STATUS.replace('        if status != "queued":\n', "        if False:\n"))]),
    # rehydration
    ("R37", RESEARCH, "⛔⛔ boot resumes a run another worker has taken — two pipelines",
     [("                if _run_dir_held_by_queue(_queue_dir_now):\n", "                if False:\n")]),
    # what the lane claimed and nothing measured
    ("R38", RESEARCH, "⛔ the move restarts without waiting for uploads in flight",
     [("        left = _wait_for_uploads_to_settle(max_wait_s=5.0)\n", "        left = 0\n")]),
    ("R39", RESEARCH, "⛔ Clear Local Storage deletes the runs in this worker's own line",
     [('    jobs = list(_jobs_held_locally(_QUEUE_STATE.get("queue_ref"))) + list(_UNREAD_RESTORES)\n',
       "    jobs = list(_UNREAD_RESTORES)\n")]),
    ("R40", RESEARCH, "Clear Local Storage deletes the boot entries still to be checked",
     [('    jobs = list(_jobs_held_locally(_QUEUE_STATE.get("queue_ref"))) + list(_UNREAD_RESTORES)\n',
       '    jobs = list(_jobs_held_locally(_QUEUE_STATE.get("queue_ref")))\n')]),

    # ═══ Y — the capability ═══════════════════════════════════════════════════
    ("Y1", RESEARCH, "⛔ the capability is never published — the app never shows the chip",
     [("                        if _rq != _last_published_requeue_patch:",
       "                        if False:")]),
    ("Y2", RESEARCH, "⛔ a backend started by hand advertises it — the move would kill it",
     [('    if _supervisor_is_my_parent():\n        return {"requeueRuns": _REQUEUE_RUNS_CAPABILITY}',
       '    if True:\n        return {"requeueRuns": _REQUEUE_RUNS_CAPABILITY}')]),
    ("Y3", RESEARCH, "⛔ the capability rides the version patch — one unadmitted key refuses both",
     [("                        _vf = await asyncio.to_thread(_device_version_fields)\n",
       "                        _vf = dict(await asyncio.to_thread(_device_version_fields),\n"
       "                                   **(await asyncio.to_thread(_requeue_capability_patch)))\n")]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, tests):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider", "-rs"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    ok = (re.search(r"\b\d+ (failed|errors?)\b", out) is None
          and re.search(r"\b\d+ passed\b", out) is not None)
    return ok, out


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # ⛔⛔ AN IN-FLIGHT MARKER: a killed run (Windows ends a process with no
    # `finally:`) would otherwise leave a mutant in research.py silently.
    _INFLIGHT = Path(__file__).with_suffix(".inflight")
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    unknown = only - {m[0] for m in MUTANTS}
    if unknown:
        print(f"no such mutant: {', '.join(sorted(unknown))}")
        sys.exit(2)
    print("baseline… ", end="", flush=True)
    ok, out = green(ROOT, TESTS)
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.\n" + out[-2000:])
        sys.exit(2)
    if re.search(r"\b\d+ skipped\b", out):
        print("⛔ BASELINE SKIPPED TESTS — no kill below would mean anything.\n" + out[-1500:])
        sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
        path = ROOT / fname
        raw = ORIGINALS[fname]
        crlf = b"\r\n" in raw
        try:
            mutated = raw.decode("utf-8").replace("\r\n", "\n")
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as se:
                    raise AssertionError(f"mutant does not compile: {se}")
            _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            ok, _out = green(ROOT, TESTS)
            if ok:
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:4} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_bytes(raw)
            if _digest(path.read_bytes()) == DIGESTS[fname]:
                try:
                    _INFLIGHT.unlink()
                except FileNotFoundError:
                    pass

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
