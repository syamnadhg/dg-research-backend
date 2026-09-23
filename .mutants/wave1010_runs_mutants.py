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
T_PROMPT = "tests/test_prompt_console_quiet_0919.py"
T_DOCTOR = "tests/test_doctor_handover_0822.py"
T_LOCAL = "tests/test_local_run_api_1010.py"
T_EDGES = "tests/test_incognito_edges_1010.py"
T_LEASE = "tests/test_incognito_fuse_renewal_109.py"
T_OWNER = "tests/test_owner_log_lines_1010.py"

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

# ══ task 3: the small fixes ═══════════════════════════════════════════════
HOLD_MIRROR = "            tee._writer.write_line(_visible_text(text))"
HOLD_TRIM = ("        _CONSOLE_HELD.append((text, tee))\n"
             "        if len(_CONSOLE_HELD) > _CONSOLE_HELD_MAX:\n"
             "            del _CONSOLE_HELD[0]")
REPLAY_SCREEN_ONLY = ("    if tee is None:\n"
                      "        print(text)\n"
                      "        return\n"
                      "    try:\n"
                      "        tee._stream.write(text + \"\\n\")")
DROPPED_NOTE = ("        if dropped:\n"
                "            _writer = next((t._writer for _x, t in held if t is not None), None)")
DROPPED_RESET = "            dropped, _CONSOLE_HELD_DROPPED[0] = _CONSOLE_HELD_DROPPED[0], 0"
DOCTOR_BARE = ("                      \"graphical-session terminal\")\n"
               "                manual_actions.append(_remedy_resurrect())")
DOCTOR_HINT = ("                      \"browser may fail post-reboot — re-run --resurrect from a \"\n"
               "                      \"graphical-session terminal\")")
ROW_STATUS = "        \"status\": _LOCAL_RUN_LIST_STATUS.get(state, state),"
LIST_CALL = "                runs.append(_local_run_row(d))"
GET_STATE = "        pipeline_state = _local_run_state(queue, delivery)"
STATE_STOP = "    if (q / \".stop\").exists():\n        return \"stopped\""
LIST_VOCAB = "_LOCAL_RUN_LIST_STATUS = {\"running\": \"ongoing\"}"
RESUME_CALL = "        _refusal = _terminal_resume_refusal(resume_path)"
SERVE_RESUME = ("        if _queue_dir_keeps_nothing(queue):\n"
                "            return JSONResponse({\"error\": _resume_refusal(queue, \"here\")}, 409)")
RESUME_GATE = "    if _queue_dir_keeps_nothing(resume_path):"
KEEPS_BY_RECORD = "    return (_is_incognito_research(_queue_dir_research_id(p))"
KEEPS_BY_NAME = "            or bool(_INCOGNITO_RUN_DIR_RE.fullmatch(p.name)))"
RUN_DIR_RE = ("_INCOGNITO_RUN_DIR_RE = re.compile("
              "r\"^incognito_[0-9]{13}_[0-9]{1,6}_[0-9]{8}_[0-9]{6}$\")")
LEASE_NOT_FOUND = "            if isinstance(e, _gax_exc.NotFound):"
LEASE_REMEMBER = "                _INCOGNITO_LEASE_GONE.add((uid, rid))"
LEASE_DROP = "                _dropped = _drop_gone_incognito_job(uid, rid)"
LEASE_SKIP = ("        if (uid, rid) in _INCOGNITO_LEASE_GONE:\n"
              "            continue")
LEASE_FORGET = "    for key in list(_INCOGNITO_LEASE_GONE):"
LEASE_FUSE = "                .update(_be_payload(_with_incognito_renewal({}, rid))),"
DROP_MATCH = ("                    if str((j or {}).get(\"uid\") or \"\").strip() == uid\n"
              "                    and (j or {}).get(\"research_id\") == rid]:")
DROP_SHED = ("    if removed:\n"
             "        try:\n"
             "            _shed_from_pending_snapshot(queue)")

# ══ task 4: owner lines ═══════════════════════════════════════════════════
# ⚠ 2026-09-23 (integration onto wave 10.9's last repair): the branch's third
# scope (`_owner_log_scope` / `@_owner_logged`) is gone. The shipped origin rule
# already sends a line with no run origin to the owner's log AND the armed
# run's folder, and none of the four is a run's work. F1-F5 now measure what
# this lane's executed loop pins hold on the origin rule: the console judging
# by the armed run again, a loop marked as the machine's (its run's folder goes
# quiet — the 08-24 silence), and the watchdog's verdict carrying the run's
# origin because the worker set it.
ORIGIN_READ = ("    origin = _LOG_RUN.get()\n"
               "    return about_the_run and bool(origin) and _is_incognito_research(origin)")
DEF_RECONNECT = "\nasync def _firebase_reconnect_loop():"
DEF_RELINK = "\nasync def _revoked_recovery_loop():"
DEF_DEVICE = "    def _on_snap(_col_snapshot, changes, _read_time):"
WORKER_TASK = "                    _pipe_task = asyncio.ensure_future("

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

    # ── task 3a: the terminal log ─────────────────────────────────────────
    ("T1", "under", "⛔⛔ a held line waits for the screen before it reaches the "
     "session log, so anything past the 500 the screen replays reaches no file",
     [(HOLD_MIRROR, "            pass")], [T_PROMPT]),
    ("T2", "over", "the replay goes back through the tee, so the session log "
     "holds every held line twice",
     [(REPLAY_SCREEN_ONLY, "    if True:\n"
                           "        print(text)\n"
                           "        return\n"
                           "    try:\n"
                           "        tee._stream.write(text + \"\\n\")")], [T_PROMPT]),
    ("T3", "under", "a full buffer keeps the OLDEST lines, so the screen replays "
     "the start of a long wait and never the end",
     [(HOLD_TRIM, "        _CONSOLE_HELD.append((text, tee))\n"
                  "        if len(_CONSOLE_HELD) > _CONSOLE_HELD_MAX:\n"
                  "            del _CONSOLE_HELD[-1]")], [T_PROMPT]),
    ("T4", "under", "the screen says nothing about the lines it did not replay",
     [(DROPPED_NOTE, "        if False:\n"
                     "            _writer = next((t._writer for _x, t in held if t is not None), None)")],
     [T_PROMPT]),
    ("T5", "over", "one long prompt's count carries into every prompt after it",
     [(DROPPED_RESET, "            dropped = _CONSOLE_HELD_DROPPED[0]")], [T_PROMPT]),

    # ── task 3b: the Linux health check ───────────────────────────────────
    ("T6", "under", "⛔⛔ the hint rides the remedy again, and Linux lists "
     "--resurrect twice in one summary",
     [(DOCTOR_BARE, "                      \"graphical-session terminal\")\n"
                    "                manual_actions.append(_remedy_resurrect() + "
                    "\"  — run it from a graphical-session terminal\")")], [T_DOCTOR]),
    ("T7", "under", "the graphical-session hint is lost altogether",
     [(DOCTOR_HINT, "                      \"browser may fail post-reboot — re-run --resurrect\")")],
     [T_DOCTOR]),

    # ── task 3c: the local run list ───────────────────────────────────────
    ("T8", "under", "⛔⛔ the row calls a run 'completed' the moment delivery.json "
     "exists — which is the moment it starts",
     [(ROW_STATUS, "        \"status\": \"completed\" if (d / \"delivery.json\").exists() "
                   "else \"ongoing\",")], [T_LOCAL]),
    ("T9", "under", "⛔⛔ THE CONSUMER IGNORES THE RULE: the list route builds its "
     "own rows again",
     [(LIST_CALL, "                runs.append({\"id\": d.name, \"status\": \"completed\" "
                  "if (d / \"delivery.json\").exists() else \"ongoing\"})")], [T_LOCAL]),
    ("T10", "under", "the single-run route reads the state its own way again, and "
     "the two views disagree about stopped and paused runs",
     [(GET_STATE, "        pipeline_state = \"completed\" if delivery and "
                  "delivery.get(\"status\") == \"completed\" else \"running\"")], [T_LOCAL]),
    ("T11", "under", "a stopped run reads as still running",
     [(STATE_STOP, "    if False:\n        return \"stopped\"")], [T_LOCAL]),
    ("T12", "under", "the list speaks the route's word 'running', which the app's "
     "Research status does not have",
     [(LIST_VOCAB, "_LOCAL_RUN_LIST_STATUS = {}")], [T_LOCAL]),

    # ── task 3d: the terminal resume ──────────────────────────────────────
    ("T13", "under", "⛔⛔ THE CONSUMER IGNORES THE RULE: `--resume` never asks, "
     "and an incognito run runs with nothing keeping its record alive",
     [(RESUME_CALL, "        _refusal = None")], [T_EDGES]),
    ("T14", "over", "every terminal resume is refused",
     [(RESUME_GATE, "    if True:")], [T_EDGES]),
    ("T15", "under", "a folder whose owner.json says incognito is not believed",
     [(KEEPS_BY_RECORD, "    return (False")], [T_EDGES]),
    ("T16", "under", "a folder named like the mint's incognito shape is not "
     "believed, so a run whose owner.json write failed resumes",
     [(KEEPS_BY_NAME, "            or False)")], [T_EDGES]),
    ("T17", "over", "the name rule widens to any 'incognito_' prefix, so an "
     "ordinary research about incognito is refused",
     [(RUN_DIR_RE, "_INCOGNITO_RUN_DIR_RE = re.compile(r\"^incognito_.*$\")")], [T_EDGES]),
    ("T17b", "under", "⛔ the serve API's resume never asks, so the same "
     "unleased private run starts through the other door",
     [(SERVE_RESUME, "        if False:\n"
                     "            return JSONResponse({\"error\": _resume_refusal(queue, \"here\")}, 409)")],
     [T_EDGES]),
    ("T17c", "over", "the serve API refuses every resume",
     [(SERVE_RESUME, "        if True:\n"
                     "            return JSONResponse({\"error\": _resume_refusal(queue, \"here\")}, 409)")],
     [T_EDGES]),

    # ── task 3e: the lease forgets a deleted record ───────────────────────
    ("T18", "under", "⛔⛔ a deleted record reads as a network blip: WARN every "
     "hour, and the waiting job stays to run into nothing",
     [(LEASE_NOT_FOUND, "            if False:")], [T_EDGES, T_LEASE]),
    ("T19", "over", "every failed write reads as deleted, so a network blip "
     "throws a person's waiting run out of the queue",
     [(LEASE_NOT_FOUND, "            if True:")], [T_EDGES, T_LEASE]),
    ("T20", "under", "the running run's gone record is not remembered, so it is "
     "written to and announced every hour",
     [(LEASE_REMEMBER, "                pass")], [T_EDGES, T_LEASE]),
    ("T21", "under", "⛔ THE CONSUMER IGNORES THE RULE: the gone job is announced "
     "and left in the queue",
     [(LEASE_DROP, "                _dropped = 0")], [T_EDGES, T_LEASE]),
    ("T22", "under", "the memory is never asked, so a remembered run is written "
     "to again",
     [(LEASE_SKIP, "        if False:\n            continue")], [T_EDGES, T_LEASE]),
    ("T23", "over", "the memory is never pruned and grows for the life of the "
     "process",
     [(LEASE_FORGET, "    for key in []:")], [T_EDGES, T_LEASE]),
    ("T24", "under", "the lease stops carrying the fuse — its whole purpose",
     [(LEASE_FUSE, "                .update(_be_payload({})),")], [T_EDGES, T_LEASE]),
    ("T25", "over", "the drop takes every waiting job of that person, not just "
     "the one whose record is gone",
     [(DROP_MATCH, "                    if str((j or {}).get(\"uid\") or \"\").strip() == uid]:")],
     [T_EDGES, T_LEASE]),
    ("T26", "under", "the snapshot on disk keeps describing the removed job",
     [(DROP_SHED, "    if False:\n"
                  "        try:\n"
                  "            _shed_from_pending_snapshot(queue)")], [T_EDGES, T_LEASE]),

    # ── task 4: owner lines ───────────────────────────────────────────────
    ("F1", "under", "⛔⛔ a line with no origin is judged by the run that is "
     "armed, so a revoked credential, a Reset Backend or a watchdog kill "
     "vanishes from the owner's log while a private run is armed",
     [(ORIGIN_READ, "    origin = _LOG_RUN.get() or getattr(_active_run_sink(), "
                    "\"research_id\", None)\n"
                    "    return about_the_run and bool(origin) and _is_incognito_research(origin)")],
     [T_OWNER]),
    ("F2", "over", "⛔⛔ the reconnect loop becomes a machine line, so an "
     "ORDINARY run's folder no longer says its commands stopped because of an "
     "outage — the 08-24 silence",
     [(DEF_RECONNECT, "\n@_machine_logged\nasync def _firebase_reconnect_loop():")],
     [T_OWNER]),
    ("F3", "over", "⛔ the revoked-credential loop becomes a machine line, so "
     "the run's folder no longer says why its writes failed",
     [(DEF_RELINK, "\n@_machine_logged\nasync def _revoked_recovery_loop():")],
     [T_OWNER]),
    ("F4", "over", "⛔ the device-command callback becomes a machine line, so "
     "the run a Reset Backend killed has no line saying so",
     [(DEF_DEVICE, "    @_machine_logged\n"
                   "    def _on_snap(_col_snapshot, changes, _read_time):")], [T_OWNER]),
    ("F5", "under", "⛔⛔ the worker sets the run's origin itself, not the "
     "wrapper around exactly the pipeline — so the watchdog's verdict on a "
     "private run is held back from the owner's log",
     [(WORKER_TASK, "                    _LOG_RUN.set(job.get(\"research_id\"))\n"
                    "                    _pipe_task = asyncio.ensure_future(")], [T_OWNER]),
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
