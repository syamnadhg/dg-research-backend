"""Mutation harness — Wave 13: a run paused by the login command continues by
itself when the login finishes.

⛔⛔ WHAT THIS CODE DECIDES.
  A* — the waiter: started after the paused attempt closes, waits while the
       login runs, then resumes through `_resume_from_checkpoint`, with the
       queue and worker taken at the pause.
  W* — a person's word wins: Stop on the record, `.stop`, a Pause.
  T* — one resume: the pause's token, checked under the helper's lock and
       cleared by any resume.
  C* — the words: the login card, the terminal's warning.
  H* — a human check the login interrupts gives way, and its cards say so.
  R* — (review 09-30) a Retry after the run continued by itself is refused:
       the note on disk and its liveness, this worker's waiting jobs, the
       resumed run spending the note, and the card coming down at the queue.
  S* — (review 09-30) a login open past 30 minutes keeps the run waiting.
Driven through the real `run_pipeline` catching a real phase-2 / phase-3 /
human-check raise, the real login marker helpers, the real resume helper and
the real start listener (tests/test_login_auto_resume_w13.py).

⛔ NO SOURCE PIN SITS IN THE TEST SET. Every mutant must die on behaviour.
⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/login_resume_w13_mutants.py
  .venv/bin/python .mutants/login_resume_w13_mutants.py A1 T2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

LOGIN_T = ["tests/test_login_auto_resume_w13.py"]
TESTS = LOGIN_T
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ A — the waiter ════════════════════════════════════════════════════
    ("A1", RESEARCH, "⛔⛔ THE CHANGE UNDONE: the run the login paused is never "
     "started again — it waits for a Retry, as before",
     [("    if _login_resume is not None:\n        _arm_login_auto_resume(_login_resume)\n",
       "    if False:\n        _arm_login_auto_resume(_login_resume)\n")], LOGIN_T),
    ("A2", RESEARCH, "⛔ the run goes back on the queue while the login still has "
     "the browser — Chrome relaunches onto the profile being signed into",
     [("        while _login_still_running():\n",
       "        while False:\n")], LOGIN_T),
    ("A3", RESEARCH, "⛔⛔ a second resume path: the job is queued, but the files "
     "and the record are left paused — not what a Retry does",
     [("        resumed = await asyncio.to_thread(\n"
       "            _resume_from_checkpoint, plan[\"queue_dir\"],\n",
       "        resumed = await asyncio.to_thread(\n"
       "            lambda *a, **k: plan[\"job_queue\"].put_nowait({\n"
       "                \"run_id\": plan[\"run_id\"], \"uid\": plan[\"uid\"],\n"
       "                \"research_id\": plan[\"research_id\"], \"email\": plan[\"email\"],\n"
       "                \"resume_dir\": str(plan[\"queue_dir\"])}) or True, plan[\"queue_dir\"],\n")],
     LOGIN_T),
    ("A4", RESEARCH, "⛔⛔ the queue and worker are read when the login finishes — "
     "two workers' runs both land on the last worker",
     [("email=plan[\"email\"], job_queue=plan[\"job_queue\"], loop=plan[\"loop\"],\n"
       "            worker_id=plan[\"worker_id\"],",
       "email=plan[\"email\"], job_queue=_QUEUE_STATE.get(\"queue_ref\"), loop=plan[\"loop\"],\n"
       "            worker_id=WORKER_ID,")], LOGIN_T),
    ("A5", RESEARCH, "a run with no record to resume it under gets a waiter anyway",
     [("if not (_firebase_db and uid and research_id and job_queue is not None):",
       "if not (_firebase_db and job_queue is not None):")], LOGIN_T),

    # ═══ W — a person's word wins ══════════════════════════════════════════
    ("W1", RESEARCH, "⛔⛔ Stop on a waiting run is overruled — it is flipped back to "
     "ongoing and run",
     [("    if record.get(\"status\") in TERMINAL_RESEARCH_STATUSES:\n        return \"stopped\"\n",
       "")], LOGIN_T),
    ("W2", RESEARCH, "a `.stop` on disk is ignored",
     [("    if (qd / \".stop\").exists():\n        return \"stopped\"\n", "")], LOGIN_T),
    ("W3", RESEARCH, "the person's Pause is ignored",
     [("    if (qd / \".pause\").exists():\n        return \"paused\"\n", "")], LOGIN_T),

    # ═══ T — one resume ════════════════════════════════════════════════════
    ("T1", RESEARCH, "⛔⛔ the pause's token is not compared — an old waiter resumes "
     "a pause another worker's waiter owns, and the run goes twice",
     [("return d.get(\"status\") == \"paused\" and bool(token) and d.get(\"loginPause\") == token",
       "return d.get(\"status\") == \"paused\"")], LOGIN_T),
    ("T2", RESEARCH, "⛔⛔ the helper resumes whatever it is handed — a Retry before "
     "the login finished is followed by a second resume",
     [("        if login_pause and not _login_pause_holds(queue_dir, login_pause):\n"
       "            return False\n", "")], LOGIN_T),
    ("T3", RESEARCH, "a resume keeps the old token — a later pause of another kind "
     "is taken by an old waiter",
     [("                        d.pop(\"loginPause\", None)\n", "")], LOGIN_T),

    # ═══ C — the words ═════════════════════════════════════════════════════
    ("C1", RESEARCH, "⛔ the card still tells the person to tap Retry after login",
     [("reason=(LOGIN_PAUSE_CONTINUES_COPY if _login_resume else",
       "reason=(LOGIN_PAUSE_CONTINUES_COPY if False else")], LOGIN_T),
    ("C2", RESEARCH, "a run with no waiter is promised one",
     [("reason=(LOGIN_PAUSE_CONTINUES_COPY if _login_resume else",
       "reason=(LOGIN_PAUSE_CONTINUES_COPY if True else")], LOGIN_T),
    ("C3", RESEARCH, "the login command's warning still says to press Retry",
     [("Each one continues by itself from its checkpoint when this login finishes.",
       "Interrupted runs can be resumed from the app (Retry on the alert) after login.")],
     LOGIN_T),

    # ═══ H — a human check the login clears ════════════════════════════════
    ("H1", RESEARCH, "⛔⛔ the human-check wait sits out its ten minutes on a page "
     "the login closed, then skips the platform",
     [("        if _login_interrupt_active() and await _hv_browser_gone(browser, page):",
       "        if False and await _hv_browser_gone(browser, page):")], LOGIN_T),
    ("H2", RESEARCH, "⛔ the gate's retry swallows the login interrupt and carries on "
     "as if the check had cleared",
     [("        except LoginInterrupted:\n", "        except _NeverRaised:\n"),
      ("class LoginInterrupted(RuntimeError):",
       "class _NeverRaised(Exception):\n    pass\n\n\nclass LoginInterrupted(RuntimeError):")],
     LOGIN_T),
    ("H3", RESEARCH, "the human-check cards do not say the login clears them",
     [("HV_LOGIN_LINE = (\" Or run superresearch --login, clear it in the window that \"\n"
       "                 \"opens, and the run continues by itself when you finish.\")",
       "HV_LOGIN_LINE = \"\"")], LOGIN_T),
    ("H4", RESEARCH, "the wait's own Cloudflare card leaves the line off",
     [("            + HV_LOGIN_LINE\n        )", "        )")], LOGIN_T),
    ("H5", RESEARCH, "the non-Cloudflare hands-off card leaves the line off",
     [("if you want it back.\" + HV_LOGIN_LINE,", "if you want it back.\",")], LOGIN_T),

    # ═══ R — review 09-30: a Retry after the run continued by itself ═══════
    ("R1", RESEARCH, "⛔⛔ the auto-resume leaves no note — a sibling's Retry starts "
     "the queued run a second time",
     [("if login_pause and fname == \"delivery.json\":", "if False:")], LOGIN_T),
    ("R2", RESEARCH, "⛔⛔ a Retry is never refused — the run already queued goes twice",
     [("if not login_pause and _run_already_queued(queue_dir, job_queue):", "if False:")],
     LOGIN_T),
    ("R3", RESEARCH, "⛔ a note left by a worker that is gone holds for ever — the "
     "run's Retry is refused after a restart",
     [("return pid > 0 and (psutil.Process(pid).create_time()\n"
       "                            <= float(note.get(\"at\") or 0) / 1000 + 1)",
       "return True")], LOGIN_T),
    ("R4", RESEARCH, "a note holds for any process with its number, even one younger "
     "than the note",
     [("return pid > 0 and (psutil.Process(pid).create_time()\n"
       "                            <= float(note.get(\"at\") or 0) / 1000 + 1)",
       "return pid > 0 and psutil.pid_exists(pid)")], LOGIN_T),
    ("R5", RESEARCH, "⛔ this worker's own waiting job is not looked at — a second "
     "Retry queues the run twice",
     [("return any(getattr(_job_run_dir(j), \"name\", None) == name for j in waiting)",
       "return False")], LOGIN_T),
    ("R6", RESEARCH, "⛔ the run this worker is letting go of counts as queued — a "
     "Retry in the ten seconds after the pause is refused",
     [("waiting = list(job_queue._queue)", "waiting = _jobs_held_locally(job_queue)")],
     LOGIN_T),
    ("R7", RESEARCH, "⛔ the resumed run never spends the note — a Retry on its "
     "next card is refused",
     [("        _spend_login_resume_note(queue_dir)\n        # Set the active-run global",
       "        # Set the active-run global")], LOGIN_T),
    ("R8", RESEARCH, "the record keeps the login card — it comes back on a cold open "
     "over a queued run",
     [("**({\"pendingDecision\": _DF_RESUME} if login_pause else {})", "**({})")], LOGIN_T),
    ("R9", RESEARCH, "⛔ the open tab keeps the login card and its Retry until the "
     "job starts",
     [("    if login_pause:\n        _send_login_card_down(uid, research_id, queue_dir)\n",
       "")], LOGIN_T),
    ("R10", RESEARCH, "⛔⛔ the card's clear is written where the run globals point — "
     "onto whichever research this worker runs by then",
     [("lambda d=doc: _firebase_db.collection(\"users\").document(uid)\n"
       "                    .collection(\"researches\").document(research_id)",
       "lambda d=doc: _firebase_db.collection(\"users\").document(_fb_uid)\n"
       "                    .collection(\"researches\").document(_fb_research_id)")],
     LOGIN_T),
    ("R11", RESEARCH, "the card's clear goes after the job — it can land after the "
     "resumed run's own start and reset its phase",
     [("    if login_pause:\n        _send_login_card_down(uid, research_id, queue_dir)\n",
       ""),
      ("    loop.call_soon_threadsafe(_do_resume_enqueue)\n",
       "    loop.call_soon_threadsafe(_do_resume_enqueue)\n"
       "    if login_pause:\n        _send_login_card_down(uid, research_id, queue_dir)\n")],
     LOGIN_T),

    # ═══ S — review 09-30: a login left open a long time ═══════════════════
    ("S1", RESEARCH, "⛔⛔ a login open past 30 minutes counts as finished — the run "
     "starts again on the profile the login window has open",
     [("        while _login_still_running():\n",
       "        while _login_interrupt_active():\n")], LOGIN_T),
    ("S2", RESEARCH, "a marker no process vouches for is believed for 12 hours",
     [("max_age_sec=LOGIN_RESUME_LIVE_LOGIN_CAP_S if vouched else 30 * 60)",
       "max_age_sec=LOGIN_RESUME_LIVE_LOGIN_CAP_S)")], LOGIN_T),
    ("S3", RESEARCH, "a live login is believed for ever — a reused number keeps the "
     "run waiting for good",
     [("LOGIN_RESUME_LIVE_LOGIN_CAP_S = 12 * 3600", "LOGIN_RESUME_LIVE_LOGIN_CAP_S = 10 ** 9")],
     LOGIN_T),
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
    selected = [m for m in MUTANTS if not only or m[0] in only]
    base_tests = sorted({t for m in selected for t in m[4]})
    print("baseline… ", end="", flush=True)
    ok, out = green(ROOT, base_tests)
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.\n" + out[-2000:])
        sys.exit(2)
    if re.search(r"\b\d+ skipped\b", out):
        print("⛔ BASELINE SKIPPED TESTS — a skipped test measures nothing here.\n"
              + out[-1500:])
        sys.exit(2)
    print("green\n")

    survivors = []
    for mid, fname, why, edits, tests in selected:
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
            ok, _out = green(ROOT, tests)
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
