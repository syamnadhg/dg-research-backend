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
