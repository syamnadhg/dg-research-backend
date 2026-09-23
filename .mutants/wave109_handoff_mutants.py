"""Wave 10.9 — after phase 3 the machine hands off and stops interfering.

⛔⛔ WHAT THE WAVE CLOSED (items N8, 542-4, 542-5, 542-S4). One rule underneath
all four: when phase 3 ends the machine writes `beDone`, kicks the cloud route
until it answers, and after that NEVER writes `status`, `phase` or any fe* field
on that run. `delivery.json` "completed" means the hand-off is done, never that
the run is.

  N8    `_wait_for_prior_fe_completion` held the next dequeue behind the
        PREVIOUS run's cloud tail for up to 4200 seconds, and the start listener
        predicted the same wait and landed the new submission "queued" naming
        that other run. Phases 4 and 5 run on Cloud Run: there was nothing on
        this computer to contend for. Its boot half went further and stamped the
        run it could not wait on — "Backend restarted before this run reached
        completion", status "stopped" — on runs that were mid-upload, and
        relabelled ERRORED runs "stopped" with a restart blamed for them.

  542-4 The same confusion in three more readers. `detect_resume_phase` read
        `delivery.json` as "finished" and answered 6, so a Resume did nothing at
        all; `_rehydrate_ongoing_for_tree` had no guard, so every restart during
        a tail marked the run `paused_backend_restart` or re-enqueued it.

  542-5 The kick was sent ONCE: no token, a POST that never left, or a 5xx
        delivered nothing, on a run nobody was watching.

  542-S4 And both log lines a stuck-run report is read from lied — "marker
        written" for a write that returned False, and a 202 ("another caller
        holds the claim") as "dispatched ✓".

Every mutant below is a way one of those could be put back while still looking
fixed. The quiet ones matter most:

  H3  — the hand-off test reads `delivery.json` from anywhere on the disk again,
        so a run id that is a PATH decides the branch on a file that was never
        a run's.
  H6  — the rehydrate guard runs but its `continue` is dropped, so the run is
        re-kicked AND stamped: the tile goes red under a healthy upload.
  H8  — the refusal is recorded as `feP4State` instead of `phases[4]`. It looks
        stricter and it reroutes the run: `cloudKickDecision` then asks for
        phase 5 ALONE, and the Doc and the email go out with no video for an
        upload that never ran (542-S2 through a different door).
  H11 — a 202 is classified as this machine's dispatch again, which is the log
        line a stuck-run report rests on.
  H14 — the retry ladder keeps its shape and loses its effect: one attempt.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE — a mutant that does not parse fails every test
and would be scored as a kill. Both are harness faults, counted OUT.

⚠ Two of this group's mutants live elsewhere because their anchors do:
`wave109_ownership_mutants.py` holds N7 (the dead-worker sweep's claim test,
re-anchored onto the shared `_claim_is_handed_off`) and M13a/c (the slots the
cancel gate reads, one of which the queue gate used to fill).

    .venv/bin/python .mutants/wave109_handoff_mutants.py
    .venv/bin/python .mutants/wave109_handoff_mutants.py H8 H11
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_handoff_is_the_end_109.py "
          "tests/test_cloud_handoff_record_108.py "
          "tests/test_cloud_tasks.py "
          "tests/test_resume_at_phase5_handoff.py "
          "tests/test_per_worker_rehydration_966.py "
          "tests/test_sharer_rehydration.py")
RESEARCH = "research.py"
FILES = (RESEARCH,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: what `delivery.json` means ────────────────────────────────────
#: The one definition of the hand-off, read off the run directory.
A_MEANING = ("        return json.loads(\n"
             "            delivery_path.read_text(encoding=\"utf-8\")).get(\"status\") == \"completed\"")
#: A missing record is not a hand-off.
A_MISSING = ("        if not delivery_path.exists():\n"
             "            return False\n")
#: The claim is a NAME, and the filesystem answers where it lands.
A_CLAIM = "    return _handed_off_to_cloud(_run_dir_inside_queues(claimed_run_id))"
#: `detect_resume_phase`'s use of it, and the sentence it hands the caller.
A_RESUME_SIX = ("    if _handed_off_to_cloud(queue_dir):\n"
                "        return 6, \"Already handed off to the cloud — nothing left for this machine to run\"")

# ── anchors: boot recovery leaves a handed-off run alone ───────────────────
#: Sixteen spaces — the dead-worker sweep's call is the same line at eight.
#: ⛔ RE-ANCHORED (wave 10.9, #536). The guard now asks `_recovery_sees_handoff`,
#: because the disk half of the answer — `queues/<run>/delivery.json` — is
#: deleted at the hand-off for a run that keeps nothing.
R_GUARD = ("                if _recovery_sees_handoff(research_id, data):\n"
           "                    log(f\"[rehydrate] {research_id[:24]}… was handed off to the cloud \"\n")
#: The re-kick itself.
R_KICK = ("                        await asyncio.to_thread(\n"
          "                            _post_fe_p4p5_trigger, tree_uid, research_id)")
#: And the branch stops there — nothing below it may touch the run.
R_CONTINUE = ("                            f\"{_kick_err}\", \"WARN\")\n"
              "                    continue\n")

# ── anchors: the resume path re-fires rather than sitting down ─────────────
S_TERMINAL = "            if _research_is_terminal(_fb_uid, _fb_research_id, on_error=False):"
S_KICK = ("            try:\n"
          "                _post_fe_p4p5_trigger(_fb_uid, _fb_research_id)\n"
          "            except Exception as _trig_err:\n"
          "                log(f\"FE trigger dispatch failed on handed-off resume (non-fatal): {_trig_err}\", \"WARN\")")

# ── anchors: the refusal reaches the chat, on the right field ──────────────
F_FIELD = ("        entry[\"status\"] = \"errored\"\n"
           "        entry[\"reason\"] = reason")
F_UPSERT = ("        if entry is None:\n"
            "            entry = {\"phase\": 4, \"label\": \"Phase 4\",\n")
F_CALL = ("                record_failure=lambda _reason: _record_cloud_kick_refusal(\n"
          "                    uid, research_id, _reason),")

# ── anchors: the dispatch verdict ──────────────────────────────────────────
V_CLAIMED = "    if status_code == 202:\n        return \"claimed\""
V_RETRYABLE_4XX = "    if status_code in (401, 403):\n        return \"retry\""
V_REFUSED = ("    if isinstance(status_code, int) and 400 <= status_code < 500:\n"
             "        return \"refused\"")
#: ⛔ THE TAIL, NOT THE LINE. `    return "retry"` alone matches eleven times in
#: this file — `mutated.count` counts substrings, so it matches deeper
#: indentation too — and an anchor that lands somewhere else measures nothing.
V_DEFAULT = "        return \"refused\"\n    return \"retry\""
V_EXC = "        return \"retry\" if _dispatch_never_left(exc, elapsed_sec) else \"cut\""

# ── anchors: the route's "answered without phase 5" contract ───────────────
P_RULE = "    return isinstance(parsed, dict) and \"p5\" not in parsed"
P_UNPARSED = ("    try:\n"
              "        parsed = json.loads(body_text or \"\")\n"
              "    except Exception:\n"
              "        return False")
P_FOLLOWUP = "            if not _p5_only and _answered_without_phase_5(_text):"
P_FLIP = ("                _p5_only = True\n"
          "                _attempt = 0\n"
          "                continue")
P_BODY = ("        if p5_only:\n"
          "            _body[\"p5_only\"] = True")

# ── anchors: the ladder ────────────────────────────────────────────────────
L_BACKOFF = "_DRIVE_BACKOFF_SEC = (5, 15, 30, 60)"
L_ATTEMPTS = "    attempts = len(_DRIVE_BACKOFF_SEC) + 1"
L_TOKEN = ("        if not id_token:\n"
           "            verdict, why = \"retry\", \"no synth id-token (creds revoked?)\"")
L_CUT_RETURN = ("            log(f\"FE trigger: BE-driven P4/P5 connection cut after {_elapsed}s \"\n"
                "                f\"({why}) — the cloud has the request rid={research_id[:8]}…\", \"WARN\")\n"
                "            return verdict")
L_REFUSED_BREAK = "        if verdict == \"refused\":"

# ── anchors: the two lines a stuck-run report is read from ─────────────────
G_MARKER = ("    if written:\n"
            "        log(f\"FE trigger: needsFeTrigger marker written rid={research_id[:8]}…\")\n"
            "    else:")
G_MARKER_TARGET = ("        written = _update_research_doc(uid, research_id, {\n"
                   "            \"needsFeTrigger\": True,")
G_202_LINE = ("            note(\"P4/P5 was already claimed by another caller (HTTP 202) — \"\n"
              "                 \"the cloud is running it, and this machine's kick did nothing.\")")

MUTANTS = [
    # ── 542-4: what the delivery record means ───────────────────────────────
    ("H1", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — a handed-off run stops counting as handed off, so "
     "every boot sweep and every Resume is free to stamp it again",
     [(A_MEANING, "        return False")]),

    ("H2", "over", RESEARCH,
     "⛔ a run with NO delivery record reads as handed off, so a run that died "
     "mid-phase-3 is never resumed and never marked — it simply stops",
     [(A_MISSING, "        if not delivery_path.exists():\n            return True\n")]),

    ("H3", "under", RESEARCH,
     "⛔⛔ the claim is joined raw again, so a run id that is a PATH decides the "
     "hand-off branch on a delivery.json that was never a run's",
     [(A_CLAIM, "    return _handed_off_to_cloud(\n"
                "        Path(__file__).parent / \"queues\" / str(claimed_run_id or \"\"))")]),

    ("H4", "under", RESEARCH,
     "⛔ six goes back to claiming the run is COMPLETE — the sentence a caller "
     "acts on, and the reason the resume branch sat down on a stalled tail",
     [(A_RESUME_SIX, "    if _handed_off_to_cloud(queue_dir):\n"
                     "        return 6, \"Pipeline already complete\"")]),

    # ── 542-4: boot recovery ────────────────────────────────────────────────
    ("H5", "under", RESEARCH,
     "⛔⛔ the rehydrate guard is gone — a restart during a cloud tail marks the "
     "run paused_backend_restart, or re-enqueues it for a second pass",
     [(R_GUARD, "                if False:\n"
                "                    log(f\"[rehydrate] {research_id[:24]}… was handed off to the cloud \"\n")]),

    ("H6", "under", RESEARCH,
     "⛔⛔ the guard runs and then falls through — the run is re-kicked AND "
     "stamped, which is the worst of both",
     [(R_CONTINUE, "                            f\"{_kick_err}\", \"WARN\")\n"
                   "                    pass\n")]),

    ("H7", "under", RESEARCH,
     "⛔ the guard skips the run but never re-kicks it, so a tail whose kick "
     "never landed is left for a tab that may never open",
     [(R_KICK, "                        pass")]),

    # ── 542-4: the resume path ──────────────────────────────────────────────
    ("H8", "under", RESEARCH,
     "⛔⛔ a Resume on a handed-off run goes back to doing nothing at all — the "
     "last door out of #542 for somebody with no tab open",
     [(S_KICK, "            pass")]),

    ("H9", "over", RESEARCH,
     "⛔ the terminal check is dropped, so a run the route already FINISHED is "
     "kicked again on every Resume",
     [(S_TERMINAL, "            if False:")]),

    # ── 542-5: the refusal reaches the chat ─────────────────────────────────
    ("H10", "under", RESEARCH,
     "⛔⛔ the refusal is written as feP4State instead of phases[4] — it looks "
     "stricter and it REROUTES the run: cloudKickDecision then asks for phase 5 "
     "alone and delivers the Doc and the email with no video",
     [(F_FIELD, "        entry[\"feP4State\"] = \"failed\"\n"
                "        entry[\"reason\"] = reason")]),

    ("H11", "under", RESEARCH,
     "⛔ a run that already has a phase-4 entry gets a SECOND one, so whichever "
     "row a surface finds first decides the tile",
     [(F_UPSERT, "        if True:\n"
                 "            entry = {\"phase\": 4, \"label\": \"Phase 4\",\n")]),

    ("H12", "under", RESEARCH,
     "⛔⛔ the drive stops recording the refusal at all — back to #542's "
     "symptom, a run that says nothing and waits for a chat that never opens",
     [(F_CALL, "                record_failure=lambda _reason: None,")]),

    # ── 542-5: the verdict ──────────────────────────────────────────────────
    ("H13", "under", RESEARCH,
     "⛔⛔ a 202 is classified as this machine's dispatch again — the 542-S4 log "
     "line, and the wrong party named in every report that rests on it",
     [(V_CLAIMED, "    if status_code == 202:\n        return \"ran\"")]),

    ("H14", "over", RESEARCH,
     "⛔ 401/403 stop being retried, so a token that was stale for one second, "
     "or a claim that had not propagated, costs the run its last two phases",
     [(V_RETRYABLE_4XX, "    if status_code in (401, 403):\n        return \"refused\"")]),

    ("H15", "under", RESEARCH,
     "⛔ every 4xx is retried, including the 400s that cannot clear — load for "
     "nothing, and a refusal the run is never told about",
     [(V_REFUSED, "    if isinstance(status_code, int) and 400 <= status_code < 500:\n"
                  "        return \"retry\"")]),

    ("H16", "over", RESEARCH,
     "⛔⛔ an unrecognised answer is written off instead of asked again — the "
     "fail-safe direction inverted",
     [(V_DEFAULT, "        return \"refused\"\n    return \"refused\"")]),

    ("H17", "under", RESEARCH,
     "⛔⛔ a socket cut AFTER the cloud had the request is retried as if it "
     "never left, so the chain is asked for twice and the record says the "
     "opposite of what happened",
     [(V_EXC, "        return \"retry\"")]),

    # ── 542-5: the route's "answered without phase 5" contract ──────────────
    ("H26", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — a 200 that answered phase 4 and stopped is taken "
     "for a finished chain again. On the two re-kicks that land on a completed "
     "phase 4 (boot, Resume) that is no Super Research, no Doc and no email",
     [(P_FOLLOWUP, "            if False:")]),

    ("H27", "under", RESEARCH,
     "⛔ the rule inverts: a body that HAS run phase 5 is followed up and one "
     "that has not is let through",
     [(P_RULE, "    return isinstance(parsed, dict) and \"p5\" in parsed")]),

    ("H28", "over", RESEARCH,
     "⛔⛔ an answer that could not be READ is treated as a missing phase 5, so "
     "a phase 5 that may be mid-flight is asked for again on every unparseable "
     "reply — the browser refuses exactly this",
     [(P_UNPARSED, "    try:\n"
                   "        parsed = json.loads(body_text or \"\")\n"
                   "    except Exception:\n"
                   "        return True")]),

    ("H29", "over", RESEARCH,
     "⛔ the follow-up never flips the flag, so the drive asks for phase 4 "
     "again — and loops on the same answer until the budget runs out",
     [(P_FLIP, "                _attempt = 0\n"
               "                continue")]),

    ("H30", "under", RESEARCH,
     "⛔ the follow-up POSTs without `p5_only`, so the route runs the phase-4 "
     "path again and answers the same way — a loop that delivers nothing",
     [(P_BODY, "        if False:\n"
               "            _body[\"p5_only\"] = True")]),

    # ── 542-5: the ladder ───────────────────────────────────────────────────
    ("H18", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — one attempt again. No token, a POST that never "
     "left, or one 5xx and the run loses its video, its Doc and its email",
     [(L_ATTEMPTS, "    attempts = 1")]),

    ("H19", "under", RESEARCH,
     "⛔ a missing token gives up instead of being minted again — a refresh "
     "that blips for five seconds costs the run its last two phases",
     [(L_TOKEN, "        if not id_token:\n"
                "            verdict, why = \"refused\", \"no synth id-token (creds revoked?)\"")]),

    ("H20", "over", RESEARCH,
     "⛔ the backoff is removed, so five requests go out back to back at a "
     "route that is restarting",
     [(L_BACKOFF, "_DRIVE_BACKOFF_SEC = (0, 0, 0, 0)")]),

    ("H21", "over", RESEARCH,
     "⛔⛔ the cut case stops returning, so a request the cloud is still working "
     "on is sent four more times and then recorded as a failure",
     [(L_CUT_RETURN, "            log(f\"FE trigger: BE-driven P4/P5 connection cut after {_elapsed}s \"\n"
                     "                f\"({why}) — the cloud has the request rid={research_id[:8]}…\", \"WARN\")")]),

    ("H22", "over", RESEARCH,
     "⛔ a refusal on the merits is retried to exhaustion — four more requests "
     "the route has already declined",
     [(L_REFUSED_BREAK, "        if False:")]),

    # ── 542-S4: the two lines a report is read from ─────────────────────────
    ("H23", "under", RESEARCH,
     "⛔⛔ the marker line goes back to saying 'written' whatever happened — the "
     "FIRST line of every stuck-run report, false",
     [(G_MARKER, "    if True:\n"
                 "        log(f\"FE trigger: needsFeTrigger marker written rid={research_id[:8]}…\")\n"
                 "    else:")]),

    ("H24", "under", RESEARCH,
     "⛔ the marker goes back through the pipeline globals, so a call made for "
     "a run this worker is NOT running writes to the wrong document or none",
     [(G_MARKER_TARGET, "        written = _update_firestore_research({\n"
                        "            \"needsFeTrigger\": True,")]),

    ("H25", "under", RESEARCH,
     "⛔⛔ the 202 is recorded as a dispatch in the run's own folder — the line "
     "the support bundle carries, naming the wrong party",
     [(G_202_LINE, "            note(f\"P4/P5 dispatched to the cloud ✓ (HTTP 202)\")")]),
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
