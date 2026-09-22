"""Wave 10.9 — can the guards see a member acting on another member's run?

⛔⛔ WHAT THE WAVE CLOSED. Wave 10.8's round three corroborated that a run
belongs to the RESEARCH it is named for, and never that the research belongs to
the PERSON asking. Research ids are published to every member (`queueOwners`)
and the rules let a member create a research document under any id in their own
tree, so a member signing honestly as themselves could:

  N1 — resume another member's run into their own tree: the payload's run id,
       the research document's run id and the disk lookup all matched on
       researchId alone. Executed against the pre-fix code, Alice's run was
       enqueued under Bob, her `.pause` and `.no_auto_retry` cleared.
  N2 — cancel another member's QUEUED run: a deferred run is held by no worker,
       so the local gate saw nothing and the deferred scan deleted the first
       start doc whose researchId matched.
  N5 — the deferred-cancel tests exercised a COPY of that scan, so neither the
       defect nor its fix could turn them red.
  (+) boot recovery read `backendRunId` off a research document in the scanned
       tree and auto-resumed that directory into it — the same claim, unchecked.

⛔⛔ AND ROUND TWO OF CROSS-VERIFY FOUND THE FIX HALF-BUILT. Every check above
asks `queues/<claim>/owner.json` whose run a claim is, and a directory with no
readable record keeps its claim on purpose — so a claim that was a PATH walked
past all of it:

  N1r — `<Alice's run>/documents` has no `owner.json` of its own, so the claim
        was kept: Bob's config was merged into Alice's folder, her `.pause` was
        removed and a run was enqueued rooted inside her run. An ABSOLUTE claim
        left `queues/` altogether, so any directory this account can write was
        merged over and handed to `run_pipeline`. Both executed against the real
        listener. The claim is a NAME now, and the filesystem is asked where the
        join lands (N1-N7).
  W1-W4 — the owner's own control of a sharer's run was never EXECUTED: four
        one-token swaps from the tree's uid to the writer's each left all seven
        ownership and cancel suites green, and each silently drops exactly one
        thing the owner is supposed to be able to do.
  T1-T3 — the pre-claim terminal gate's tests were a replica of its status
        tuple living in the test file, so no change to the gate could turn them
        red; the gate now reads the module's one `TERMINAL_RESEARCH_STATUSES`
        and its tests drive the real start branch.
  U1-U5 — and the whole ownership gate was bypassed by writing LESS: the
        disagreement it rests on needs both identity fields, so a doc carrying
        another member's `uid` and no `submittedBy` disagreed with nobody. Every
        check above then compared the victim's uid to itself and admitted.
        Refusing it costs nothing — the create rule has required `submittedBy`
        since the collection existed and every writer stamps it — so the gate
        now answers the unsigned doc first (U1-U5).

Every mutant below is a way the fix could be put back to decoration while still
looking installed. The quiet ones matter most:

  M7  — the DOCUMENT's claim goes unchecked again. The payload is still
        corroborated, so every test that only sends a payload stays green; the
        hole has moved, not closed, and it costs the attacker one more write.
  M8  — the person checked is the WRITER (`submittedBy`), not the tree. It looks
        stricter, and it breaks exactly one thing: the device owner resuming a
        sharer's run, which writes `uid=<sharer>, submittedBy=<owner>` on
        purpose.
  M9  — the branch falls back to the raw payload when the resolution comes back
        empty — "more robust", and the attack verbatim.
  D2  — a foreign start doc STOPS the scan instead of being skipped past, so a
        person whose research id collides cannot cancel their own queued run.
  D5  — the deferred scan asks the writer instead of the tree: the owner's Stop
        on a sharer's queued run silently does nothing.
  M13a-c — the list the cancel gate reads loses a slot. The gate-pending and
        running checks that follow it have NO ownership clause of their own, so
        a forgotten slot is a run another member can stop.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE — a mutant that does not parse fails every test
and would be scored as a kill. Both are harness faults, counted OUT.

⚠ Two wave-10.8 mutants (O9, O15) were re-aimed at the same new lines; they
live in wave108_resume_drop_0921_mutants.py and are not duplicated here.

  .venv/bin/python .mutants/wave109_ownership_mutants.py
  .venv/bin/python .mutants/wave109_ownership_mutants.py M7 D2
"""
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_member_run_ownership_109.py "
          "tests/test_cancel_deferred.py "
          "tests/test_round_three_repairs_108.py "
          "tests/test_resume_drop_writeback_108.py "
          "tests/test_owner_control_only_109.py "
          "tests/test_supervised_auto_resume_enqueue.py")
RESEARCH = "research.py"
FILES = (RESEARCH,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the owner.json record names a person ───────────────────────────
#: The person half of the corroboration.
A_PERSON = ("    if not _owner_record_admits(owner, uid):\n"
            "        log(f\"Resume: run {claimed} was named for {rid[:8]}… but it belongs to \"\n"
            "            f\"another person on this computer — ignoring the claim\", \"WARN\")\n"
            "        return \"\"\n")
#: The one definition both helpers share.
A_ADMITS = ("    recorded = str((owner or {}).get(\"uid\") or \"\").strip()\n"
            "    return not recorded or recorded == str(uid or \"\").strip()")
A_ADMITS_RETURN = "    return not recorded or recorded == str(uid or \"\").strip()"
#: The disk lookup's match.
A_DISK = ("        if (str(owner.get(\"researchId\") or \"\").strip() == rid\n"
          "                and _owner_record_admits(owner, uid)):\n"
          "            return d")
#: The listener's disk fallback.
A_DISK_CALL = "                    _orphaned = _run_dir_owning_research(target_rid, target_uid)"

# ── anchors: the resume resolution ─────────────────────────────────────────
R_PAYLOAD = "    claimed = _corroborated_run_id((data or {}).get(\"backendRunId\"), research_id, uid)\n"
R_KEEP = "    if claimed:\n        return claimed, {}\n"
R_DOC = "    return _corroborated_run_id(rd.get(\"backendRunId\"), research_id, uid), rd"
R_CONSUMER = "                    backend_run_id, rd = _resume_run_id(data, target_uid, target_rid)\n"
R_NOT_FOUND = ("                if rd is None:\n"
               "                    log(f\"Resume: research {target_rid[:8]}... not found\", \"WARN\")")
#: The resume branch's local gate.
R_GATE = ("                if _refuse_foreign_run(doc, _jobs_held_locally(job_queue), target_rid,\n"
          "                                       target_uid, \"start-listener\", verb=\"resume\"):\n"
          "                    continue\n")
R_GATE_HEAD = "                if _refuse_foreign_run(doc, _jobs_held_locally(job_queue), target_rid,\n"
R_GATE_JOBS = "_refuse_foreign_run(doc, _jobs_held_locally(job_queue), target_rid,"

# ── anchors: the jobs this process holds ───────────────────────────────────
J_SLOTS = ("    jobs = [_QUEUE_STATE.get(\"current_job\") or {},\n"
           "            _QUEUE_STATE.get(\"gate_pending_job\") or {}]")
J_DEQUE = ("    try:\n        jobs.extend(list(job_queue._queue))\n    except Exception:\n"
           "        pass\n    return jobs")
J_CANCEL = "                _local_jobs = _jobs_held_locally(job_queue)"

# ── anchors: the deferred scan ─────────────────────────────────────────────
D_PERSON = ("        if str(d.get(\"uid\") or \"\").strip() != who:\n"
            "            log(f\"Cancel: the queued start doc for {rid[:8]}… belongs to another \"\n"
            "                f\"person — leaving it\", \"WARN\")\n"
            "            continue\n")
D_SKIP = ("                f\"person — leaving it\", \"WARN\")\n"
          "            continue\n")
D_TEST = "        if str(d.get(\"uid\") or \"\").strip() != who:\n"
#: ⛔ ANCHORED ON THE LOOP HEAD TOO. The filter line alone matches five times —
#: the start branch and the idle rescan read `action` the same way.
D_ACTION = ("    for snap in docs or ():\n"
            "        d = snap.to_dict() or {}\n"
            "        if (d.get(\"action\") or \"start\") != \"start\":\n            continue\n")
D_CONSUMER = ("                                _start_doc_id = _deferred_start_doc_id(\n"
              "                                    col_ref.limit(50).stream(), rid, u)\n")
D_ARGS = "col_ref.limit(50).stream(), rid, u)"

# ── anchors: boot recovery ─────────────────────────────────────────────────
H_CLAIM = ("                    run_id = _corroborated_run_id(data.get(\"backendRunId\"),\n"
           "                                                  research_id, tree_uid)")

# ── anchors: a run id is a NAME, not a path ────────────────────────────────
#: The spelling half — nothing with a separator in it is a directory name.
N_SPELLING = "    if not claimed or \"/\" in claimed or \"\\\\\" in claimed:\n        return None\n"
#: The containment half — where the join actually lands.
N_CONTAIN = ("        if candidate.resolve().parent != root.resolve():\n"
             "            return None\n")
#: The corroboration asks the question before it reads the record.
N_CALL = ("    run_dir = _run_dir_inside_queues(claimed)\n"
          "    if run_dir is None:\n")
#: The disk lookup will not follow a link out of `queues/`.
N_DISK = "        if _run_dir_inside_queues(d.name) is None:\n            continue\n"
#: The dead-worker sweep's delivery-tail probe.
N_SWEEP = ("        _run_dir = _run_dir_inside_queues(data.get(\"backendRunId\"))\n"
           "        if _run_dir is not None:\n"
           "            _dpath = _run_dir / \"delivery.json\"\n")

# ── anchors: the pre-claim terminal gate ───────────────────────────────────
T_SET = ("TERMINAL_RESEARCH_STATUSES = (\n"
         "    \"stopped\", \"completed\", \"archived\",\n"
         "    \"terminated_by_user_discard\", \"stopped_by_watchdog\",\n"
         ")")
T_GATE = "                if _rd_status in TERMINAL_RESEARCH_STATUSES:"

# ── anchors: a doc that names a run must name its writer ───────────────────
#: The whole unsigned refusal, comment excluded so a deletion still parses.
U_BLOCK = ("    claimed = str((data or {}).get(\"submittedBy\") or \"\").strip()\n"
           "    if not claimed:\n"
           "        unsigned = str((data or {}).get(\"uid\") or \"\").strip()\n"
           "        if unsigned:\n"
           "            log(f\"[{where}] refusing {(data or {}).get('action', '?')} — it names \"\n"
           "                f\"a run (uid={unsigned[:8]}…) and no writer at all; every client \"\n"
           "                f\"that may write this queue stamps submittedBy\", \"WARN\")\n"
           "            return True\n")
#: The refusal's verdict, so the log can be kept while the answer is lost.
U_VERDICT = ("stamps submittedBy\", \"WARN\")\n"
             "            return True\n")
#: The test itself — `    if not claimed:` alone matches twice.
U_TEST = ("    if not claimed:\n"
          "        unsigned = str((data or {}).get(\"uid\") or \"\").strip()\n")
#: The half that keeps a doc naming NOBODY out of it.
U_NAMED = "        if unsigned:\n"
#: The gate the unsigned test has to run BEFORE.
U_ORDER_TAIL = ("    # ⭐ THE DISAGREEMENT IS DEFINED ONCE, and this reuses it rather than\n"
                "    # restating it — the file's own note beside that helper says why (\"one\n"
                "    # definition, two claim sites\"), and a second copy of the same two lines\n"
                "    # also made another harness's anchor match twice, which the sweep caught.\n"
                "    # What differs here is only WHO is allowed to disagree.\n"
                "    conflict = _start_doc_identity_conflict(data)\n"
                "    if conflict is None:\n"
                "        return False\n")

MUTANTS = [
    # ── N1: the disk record's person half ──────────────────────────────────
    ("M1", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — the payload's run id is corroborated against the "
     "research only again. Research ids are published to every member, so Bob "
     "names Alice's research and her run, and it resumes into his tree",
     [(A_PERSON, "")]),

    ("M2", "under", RESEARCH,
     "⛔⛔ the shared definition stops asking — both helpers and boot recovery "
     "lose the person at once, while every call site still reads correctly",
     [(A_ADMITS, "    return True")]),

    ("M3", "over", RESEARCH,
     "⛔ absent becomes disagreeing: a record naming no uid refuses everybody, so "
     "every run whose owner.json predates the uid half stops being resumable — "
     "the product taken away instead of the attack",
     [(A_ADMITS_RETURN, "    return recorded == str(uid or \"\").strip()")]),

    ("M4", "under", RESEARCH,
     "⛔⛔ THE EVIDENCE'S OWN PATH — the disk lookup matches the research alone "
     "again. A document minted with no backendRunId sends the resume to the "
     "disk, the disk answers with Alice's directory, and the branch 'repairs' "
     "Bob's document with it",
     [(A_DISK, "        if str(owner.get(\"researchId\") or \"\").strip() == rid:\n"
               "            return d")]),

    ("M5", "over", RESEARCH,
     "⛔ a foreign directory is REFUSED instead of skipped, so when two people "
     "hold a directory for the same research id, one of them loses theirs "
     "depending on the order the filesystem lists them in",
     [(A_DISK, "        if str(owner.get(\"researchId\") or \"\").strip() == rid:\n"
               "            return d if _owner_record_admits(owner, uid) else None")]),

    ("M6", "over", RESEARCH,
     "⛔ the listener stops passing the person to the disk lookup, so the "
     "fallback cross-verify built for a failed backendRunId write-back finds "
     "nobody's directory and closes the run's recovery for good",
     [(A_DISK_CALL, "                    _orphaned = _run_dir_owning_research(target_rid, None)")]),

    # ── N1: the resolution ─────────────────────────────────────────────────
    ("M7", "under", RESEARCH,
     "⛔⛔⛔ THE HOLE MOVED, NOT CLOSED — the research document's backendRunId is "
     "taken unchecked. The document sits in the sender's own tree, so a refused "
     "payload claim followed by this is the same attack with one more write",
     [(R_DOC, "    return str(rd.get(\"backendRunId\") or \"\").strip(), rd")]),

    ("M8", "over", RESEARCH,
     "⛔⛔ the person checked is the WRITER, not the tree. Looks stricter, and "
     "breaks exactly the device owner resuming a sharer's run — which writes "
     "uid=<sharer>, submittedBy=<owner> on purpose",
     [(R_PAYLOAD, "    claimed = _corroborated_run_id((data or {}).get(\"backendRunId\"), "
                  "research_id, (data or {}).get(\"submittedBy\"))\n")]),

    ("M9", "under", RESEARCH,
     "⛔⛔ THE 'ROBUST' FALLBACK — when the resolution comes back empty the branch "
     "reads the raw payload claim. It is the attack verbatim, reached only when "
     "a payload claim AND a minted document arrive together",
     [(R_CONSUMER, R_CONSUMER +
       "                    backend_run_id = backend_run_id or (data.get(\"backendRunId\") or \"\").strip()\n")]),

    ("M15", "under", RESEARCH,
     "⛔ the research document is never consulted, so a person whose payload "
     "carries no run id loses the document's answer and every resume from the "
     "research doc alone falls through to the disk",
     [(R_KEEP, "    if True:\n        return claimed, {}\n")]),

    ("M16", "over", RESEARCH,
     "⛔ the not-found exit is lost in the refactor: a resume for a research "
     "that does not exist goes on to the disk and writes a refusal to a "
     "document nobody has",
     [(R_NOT_FOUND, "                if False:\n"
                    "                    log(f\"Resume: research {target_rid[:8]}... not found\", \"WARN\")")]),

    # ── N1: the resume branch's local gate ─────────────────────────────────
    ("M10", "under", RESEARCH,
     "⛔⛔ the resume branch stops asking whose run it is holding. A directory "
     "written before the uid half of owner.json decides nothing, and the job in "
     "hand is the only thing that still names its owner",
     [(R_GATE, "")]),

    ("M11", "under", RESEARCH,
     "⛔⛔ the resume gate becomes one term of a compound condition — every name, "
     "line and ordering stays, and the run is resumed anyway",
     [(R_GATE_HEAD, "                if False and _refuse_foreign_run(doc, _jobs_held_locally(job_queue), target_rid,\n")]),

    ("M12", "under", RESEARCH,
     "⛔ the resume gate is handed an empty list, so it asks the question of "
     "nothing and always answers 'not somebody else's'",
     [(R_GATE_JOBS, "_refuse_foreign_run(doc, [], target_rid,")]),

    # ── the jobs this process holds ────────────────────────────────────────
    ("M13a", "under", RESEARCH,
     "⛔⛔ the running job leaves the list — the cancel branch's running-job "
     "check has no ownership clause of its own, so Bob stops Alice's live run, "
     "touches a permanent .stop and schedules the exit",
     [(J_SLOTS, "    jobs = [_QUEUE_STATE.get(\"gate_pending_job\") or {}]")]),

    ("M13b", "under", RESEARCH,
     "⛔⛔ the gate-pending job leaves the list — its sync check matches on "
     "research_id alone, so Bob stops Alice's run while it waits at the gate",
     [(J_SLOTS, "    jobs = [_QUEUE_STATE.get(\"current_job\") or {}]")]),

    ("M13c", "under", RESEARCH,
     "⛔ the deque leaves the list, so a cancel naming a job queued here for "
     "somebody else is no longer refused and flips a status on the way out",
     [(J_DEQUE, "    return jobs")]),

    ("M14", "under", RESEARCH,
     "⛔⛔ the cancel branch stops reading the shared list — the refactor that "
     "moved its five lines into a helper, undone the quiet way",
     [(J_CANCEL, "                _local_jobs = []")]),

    # ── N2: the deferred scan ──────────────────────────────────────────────
    ("D1", "under", RESEARCH,
     "⛔⛔⛔ THE DEFECT ITSELF — the deferred scan matches researchId alone again, "
     "and a member's cancel deletes another member's queued run with no worker "
     "holding it to refuse",
     [(D_PERSON, "")]),

    ("D2", "over", RESEARCH,
     "⛔ a foreign start doc STOPS the scan instead of being skipped past, so the "
     "old `break` becomes a refusal of the person's own queued run whenever a "
     "stranger's doc is listed first",
     [(D_SKIP, "                f\"person — leaving it\", \"WARN\")\n"
               "            return None\n")]),

    ("D3", "under", RESEARCH,
     "⛔ 'absent is not disagreeing' creeps in: a start doc naming no uid matches "
     "anyone, which only lets anyone who knows the id delete it — such a doc "
     "never runs, so matching it buys nothing",
     [(D_TEST, "        if d.get(\"uid\") and str(d.get(\"uid\")).strip() != who:\n")]),

    ("D4", "under", RESEARCH,
     "⛔⛔ the listener goes back to its inline scan — the helper stays, tested "
     "and correct, and nothing calls it. Helper-pinned, consumer-not",
     [(D_CONSUMER,
       "                                for _qsnap in col_ref.limit(50).stream():\n"
       "                                    _qd = _qsnap.to_dict() or {}\n"
       "                                    if (_qd.get(\"researchId\") == rid\n"
       "                                            and (_qd.get(\"action\") or \"start\") == \"start\"):\n"
       "                                        _start_doc_id = _qsnap.id\n"
       "                                        break\n")]),

    ("D5", "over", RESEARCH,
     "⛔⛔ the scan asks the WRITER instead of the tree, so the owner's Stop on a "
     "sharer's queued run silently leaves it queued",
     [(D_ARGS, "col_ref.limit(50).stream(), rid, data.get(\"submittedBy\"))")]),

    ("D6", "over", RESEARCH,
     "⛔ the action filter goes, so a cancel's scan can delete another cancel "
     "document instead of the start doc it was sent for",
     [(D_ACTION, "    for snap in docs or ():\n        d = snap.to_dict() or {}\n")]),

    # ── (+) boot recovery ──────────────────────────────────────────────────
    ("H1", "under", RESEARCH,
     "⛔⛔ boot recovery takes the research document's run id on trust again, and "
     "a supervised device auto-resumes another member's run into the scanned "
     "tree at the next boot",
     [(H_CLAIM, "                    run_id = data.get(\"backendRunId\") or \"\"")]),

    ("H2", "over", RESEARCH,
     "⛔ boot recovery corroborates against the DEVICE OWNER, so no sharer's run "
     "ever auto-resumes again — the #724 sharer rehydration quietly turned off",
     [(H_CLAIM, "                    run_id = _corroborated_run_id(data.get(\"backendRunId\"),\n"
                "                                                  research_id, owner_uid)")]),

    # ── round two: a run id is a NAME, not a path ──────────────────────────
    ("N1", "under", RESEARCH,
     "⛔⛔⛔ THE DEFECT ITSELF — the claim is joined onto queues/ wherever it "
     "points. `<Alice's run>/documents` has no owner.json of its own, so silence "
     "keeps it; an absolute claim leaves queues/ altogether",
     [(N_CONTAIN, "        if False:\n            return None\n")]),

    ("N2", "under", RESEARCH,
     "⛔ the spelling half goes, so a claim that walks out of a run and back in "
     "by name is taken — a run id stops being a name and becomes a path again",
     [(N_SPELLING, "    if not claimed:\n        return None\n")]),

    ("N3", "under", RESEARCH,
     "⛔⛔ HELPER-PINNED, CONSUMER-NOT — the corroboration goes on reading "
     "`queues/<claim>/owner.json` and the shape question is asked of nobody",
     [(N_CALL, "    run_dir = Path(__file__).parent / \"queues\" / claimed\n"
               "    if False:\n")]),

    ("N4", "over", RESEARCH,
     "⛔ a claim whose directory is gone is refused HERE instead of further "
     "down, so a run whose artifacts were cleaned up loses the sentence that "
     "says so and every legacy claim is answered as an attack",
     [(N_CONTAIN, N_CONTAIN + "        if not candidate.exists():\n            return None\n")]),

    ("N5", "under", RESEARCH,
     "⛔ the containment test stops resolving, so a symlink inside queues/ "
     "pointing anywhere on the disk passes as a run directory",
     [(N_CONTAIN, "        if candidate.parent != root:\n            return None\n")]),

    ("N6", "under", RESEARCH,
     "⛔ the disk lookup follows a link out of queues/ again — `is_dir()` "
     "follows one, so whatever sits at the other end is handed back as a run",
     [(N_DISK, "")]),

    ("N7", "under", RESEARCH,
     "⛔ the dead-worker sweep joins the document's run id raw again and decides "
     "the Cloud-Run-tail branch on a delivery.json that was never a run's",
     [(N_SWEEP, "        _dpath = (Path(__file__).parent / \"queues\"\n"
                "                  / (data.get(\"backendRunId\") or \"\") / \"delivery.json\")\n"
                "        if data.get(\"backendRunId\"):\n")]),

    # ── the pre-claim terminal gate, which used to be tested by a replica ──
    ("T1", "under", RESEARCH,
     "⛔⛔ a watchdog-stopped run stops counting as over, so the queue doc that "
     "replays after a cancel is claimed and the cancelled job runs",
     [(T_SET, T_SET.replace(" \"stopped_by_watchdog\",", ""))]),

    ("T2", "over", RESEARCH,
     "⛔ the pre-claim gate calls a paused run finished, and every start doc for "
     "a run the person paused is deleted instead of claimed",
     [(T_GATE, "                if _rd_status in TERMINAL_RESEARCH_STATUSES + (\"paused\",):")]),

    ("T3", "under", RESEARCH,
     "⛔⛔ the pre-claim gate is neutered the quiet way — every name and line "
     "stays and a finished run's document is stamped with a fresh run id",
     [(T_GATE, "                if False and _rd_status in TERMINAL_RESEARCH_STATUSES:")]),

    # ── the owner's control of a sharer's run, never executed until now ────
    ("W1", "over", RESEARCH,
     "⛔⛔ the cancel gate judges a held job by the WRITER, so the owner's Stop of "
     "a sharer's running or gate-pending run is silently dropped",
     [("                if _refuse_foreign_run(doc, _local_jobs, target_rid, target_uid,",
       "                if _refuse_foreign_run(doc, _local_jobs, target_rid, "
       "data.get(\"submittedBy\") or target_uid,")]),

    ("W2", "over", RESEARCH,
     "⛔⛔ the same swap on the resume side: the owner's Resume of a sharer's "
     "held run is refused as if it were somebody else's",
     [(R_GATE, "                if _refuse_foreign_run(doc, _jobs_held_locally(job_queue), target_rid,\n"
               "                                       data.get(\"submittedBy\") or target_uid, "
               "\"start-listener\", verb=\"resume\"):\n"
               "                    continue\n")]),

    ("W3", "over", RESEARCH,
     "⛔⛔ the disk lookup is asked about the WRITER, so the owner can never "
     "resume a sharer's run whose backendRunId write-back failed",
     [(A_DISK_CALL, "                    _orphaned = _run_dir_owning_research(target_rid, "
                    "data.get(\"submittedBy\") or target_uid)")]),

    # ── round two: a doc that names a run must name its writer ────────────
    ("U1", "under", RESEARCH,
     "⛔⛔⛔ THE BYPASS ITSELF — omitting `submittedBy` skips the whole ownership "
     "gate, because the disagreement below needs both fields. A doc carrying "
     "another member's uid and no writer resumes their run and writes "
     "{status: stopped, cancelled: True} into THEIR tree",
     [(U_BLOCK, "")]),

    ("U2", "under", RESEARCH,
     "⛔⛔ THE FOUNDING DEFECT'S SHAPE — the refusal keeps its log and loses its "
     "verdict, so the machine says it refused and admits the doc anyway",
     [(U_VERDICT, "stamps submittedBy\", \"WARN\")\n")]),

    ("U3", "under", RESEARCH,
     "⛔⛔ the unsigned rule is scoped to `cancel`, and resume is the half that "
     "merges the sender's config into another member's run and clears their "
     "pause — the sweep's write-back goes with it",
     [(U_TEST, "    if not claimed and (data or {}).get(\"action\") == \"cancel\":\n"
               "        unsigned = str((data or {}).get(\"uid\") or \"\").strip()\n")]),

    ("U4", "under", RESEARCH,
     "⛔⛔ THE TIDY-UP — the unsigned test moves below the disagreement, which "
     "returns False on an unsigned doc before it is ever reached. Every line "
     "of the refusal is still there, in the wrong order",
     [(U_BLOCK + U_ORDER_TAIL, U_ORDER_TAIL + U_BLOCK)]),

    ("U5", "over", RESEARCH,
     "⛔ a doc naming NOBODY is refused too, so the `{}` and missing-uid shapes "
     "the branch's own guard handles are turned into owner-control refusals "
     "and logged as somebody's run",
     [(U_NAMED, "        if True:\n")]),

    ("W4", "over", RESEARCH,
     "⛔⛔ the research document is read from the WRITER's tree, where a sharer's "
     "research does not exist — the owner's Resume becomes 'research not found'",
     [("    snap = (_firebase_db.collection(\"users\").document(uid)\n"
       "            .collection(\"researches\").document(research_id).get())\n"
       "    if not snap.exists:\n",
       "    snap = (_firebase_db.collection(\"users\")"
       ".document((data or {}).get(\"submittedBy\") or uid)\n"
       "            .collection(\"researches\").document(research_id).get())\n"
       "    if not snap.exists:\n")]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green():
    # ⭐ THE INTERPRETER RUNNING THIS FILE, so a worktree with no `.venv` of its
    # own still measures its own tree (pytest puts the cwd first on sys.path).
    r = _run(f"{shlex.quote(sys.executable)} -m pytest {SUITES} -q -p no:cacheprovider")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it.
    return " failed" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — so an unguarded runner would turn the sweep into a full mutation run.
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
            # ⛔ A MUTANT THAT DOES NOT PARSE FAILS EVERY TEST and would be
            # scored as a kill. Refuse it before it reaches the disk.
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as se:
                raise AssertionError(f"mutant does not compile: {se}")
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
