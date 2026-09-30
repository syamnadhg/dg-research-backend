"""Mutation harness — wave 13, lane p3: a resumed podcast keeps its notebook.

⛔⛔ WHAT THIS CODE DECIDES.
  R* — a RESUMED Phase 3 goes back to the notebook its checkpoint recorded,
       instead of making a new notebook (and a new podcast) every time Chrome
       died in the podcast step (09-16: three notebooks, three podcasts, none
       delivered). Only a NotebookLM notebook address is opened from the
       checkpoint, and a prior Skip of NotebookLM is respected.
  H* — what the reopened notebook shows decides whether to carry on in it: a
       sign-in page is not a gone notebook; another research's notebook (same
       file names) is not ours; a podcast ready or being made is kept even
       when the sources panel has not drawn; a notebook with nothing of this
       research is replaced, and the tab that went looking is closed.
  B* — a dead browser is never "retried" on. The download step and the
       no-audio loop both ask the browser first, the loop before it gives up
       too, and a dead one unwinds as a browser crash — or as a login-command
       pause — so the run relaunches Chrome and resumes into the same notebook.
       The loop is the ONE place that unwinds: the download only hands back no
       file, and once the Chrome relaunches are spent the loop ends the podcast
       step at once and the report goes out with the notebook link — never the
       "Chrome kept closing" card with nothing delivered (cross-verify, 09-29).
       The login command's close spends none of that budget and still pauses.
  W* — the w13 integrated review (09-29): the checkpoint records WHICH worker
       made the notebook, and a resume carries on in it only on that worker —
       a moved run resumes on another worker's Chrome profile, maybe another
       Google account, and makes its own notebook there, as before wave 13. A
       checkpoint that does not say which worker made it is another worker's.
  P* — a resume past Phase 1 writes Phase 1's Firestore half again from
       brief.md: the brief document, the "Read Brief report" link, the
       record's brief slot and Phase 1 complete. A move in Phase 1's last
       seconds (or a crash between the two halves) left only the disk half,
       and the resume trusts the disk. No brief on disk, nothing is written.

⛔ NO SOURCE PIN SITS IN THE TEST SET. Every mutant here must die on behaviour:
the REAL `run_pipeline` driven from a resume directory into Phase 3, the real
`run_phase3_upload` / `run_phase3_audio`, and master's own `Browser.navigate` /
`new_tab` running on a fake browser (`research.Browser` is never constructed,
and no test opens a real website).

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/p3_w13_mutants.py
  .venv/bin/python .mutants/p3_w13_mutants.py R1 B2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

TESTS = ["tests/test_p3_resume_reuses_notebook_w13.py"]

WORKER_GATE = ("    if isinstance(made_on, int) and not isinstance(made_on, bool) "
               "and made_on == WORKER_ID:\n        return url\n")
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ R — the resume goes back to its own notebook ═══════════════════════
    ("R1", RESEARCH, "⛔⛔ the resume is not told which notebook it made — a new "
     "notebook and a new podcast on every Chrome death",
     # ⚠ RE-AIMED 2026-09-29 (w13 integrated review): the checkpoint's notebook
     # now comes through `_p3_notebook_to_reopen`.
     [("            _p3_recorded_nb = _p3_notebook_to_reopen(cp)",
       "            _p3_recorded_nb = \"\"")]),
    ("R2", RESEARCH, "⛔⛔ the notebook is reopened and then a new one is made anyway",
     [("        if await _p3_reopen_recorded_notebook(browser, recorded_notebook_url, md_files):",
       "        if await _p3_reopen_recorded_notebook(browser, recorded_notebook_url, "
       "md_files) and False:")]),
    ("R3", RESEARCH, "the reopened notebook's address is dropped — the share step "
     "runs again to find it",
     [("            return {\"links\": links, \"notebook_url\": recorded_notebook_url,",
       "            return {\"links\": links, \"notebook_url\": \"\",")]),
    ("R4", RESEARCH, "a person who skipped NotebookLM is taken back into it",
     [("            and \"notebooklm\" not in _controls.skipped_agents):",
       "            ):")]),
    ("R5", RESEARCH, "whatever address the checkpoint holds is opened, notebook or not",
     [("    if (recorded_notebook_url and validate_link(\"notebooklm\", recorded_notebook_url)",
       "    if (recorded_notebook_url")]),

    # ═══ H — what the notebook shows decides ════════════════════════════════
    ("H1", RESEARCH, "⛔⛔ a sign-in page reads as a gone notebook — a new notebook for "
     "a person who only had to sign in",
     [("    if await _page_shows_login_wall(page):\n"
       "        log(\"Phase 3: NotebookLM is asking to sign in",
       "    if False:\n"
       "        log(\"Phase 3: NotebookLM is asking to sign in")]),
    ("H2", RESEARCH, "⛔⛔ any notebook page counts as ours — the podcast step is sent "
     "into another research's notebook",
     [("    if _nlm_notebook_id(here) != _nlm_notebook_id(notebook_url):",
       "    if not _nlm_notebook_id(here):")]),
    ("H3", RESEARCH, "a notebook with nothing of this research is carried on in",
     [("    if not present and not ready and not making:",
       "    if False:")]),
    ("H4", RESEARCH, "⛔ a finished podcast is thrown away when the sources panel has "
     "not drawn",
     [("    if not present and not ready and not making:",
       "    if not present and not making:")]),
    ("H5", RESEARCH, "⛔ a podcast still being made is thrown away when the sources "
     "panel has not drawn",
     [("    if not present and not ready and not making:",
       "    if not present and not ready:")]),
    ("H6", RESEARCH, "a notebook tab that would not open is carried on in",
     [("            f\"({type(e).__name__}) — going to the upload instead\", \"WARN\")\n"
       "        return False",
       "            f\"({type(e).__name__}) — going to the upload instead\", \"WARN\")\n"
       "        return True")]),
    ("H7", RESEARCH, "the tab that looked for a gone notebook is left open",
     [("            \"open it) — making a new one\", \"WARN\")\n"
       "        try:\n            await page.close()\n",
       "            \"open it) — making a new one\", \"WARN\")\n"
       "        try:\n            pass\n")]),
    ("H8", RESEARCH, "the tab on an empty notebook is left open",
     [("            f\"{len(names)} sources and no podcast — making a new one\", \"WARN\")\n"
       "        try:\n            await page.close()\n",
       "            f\"{len(names)} sources and no podcast — making a new one\", \"WARN\")\n"
       "        try:\n            pass\n")]),
    ("H9", RESEARCH, "the log does not name a source the notebook is not showing",
     [("        + (f\" (not showing: {', '.join(missing)})\" if missing else \"\"))",
       "        + \"\")")]),

    # ═══ B — a dead browser is never retried on ═════════════════════════════
    ("B1", RESEARCH, "⛔ a download on a dead browser is reported as a failed download, "
     "with a Retry that cannot work",
     [("                    \"this time\", \"WARN\")\n"
       "            else:\n"
       "                fail_phase(3, \"Couldn't save the audio file\",",
       "                    \"this time\", \"WARN\")\n"
       "            if True:\n"
       "                fail_phase(3, \"Couldn't save the audio file\",")]),
    ("B2", RESEARCH, "⛔⛔ the no-audio loop retries on the dead browser — three five-"
     "minute waits, then no podcast",
     [("                if await _browser_context_is_dead(browser):\n"
       "                    if _login_interrupt_active() or _crash_retries < BROWSER_CRASH_MAX_RETRIES:\n"
       "                        raise _p3_browser_gone(\"before the podcast could be downloaded\")\n"
       "                    _p3_chrome_spent = True\n",
       "")]),
    ("B3", RESEARCH, "⛔ the loop asks only before a wait, not before it gives up — "
     "Chrome dying on the last retry ends the run without the podcast",
     [("                if await _browser_context_is_dead(browser):\n"
       "                    if _login_interrupt_active() or _crash_retries < BROWSER_CRASH_MAX_RETRIES:\n"
       "                        raise _p3_browser_gone(\"before the podcast could be downloaded\")\n"
       "                    _p3_chrome_spent = True\n",
       ""),
      ("                _audio_auto_retries += 1\n"
       "                _wait_min = _AUDIO_RETRY_INTERVAL_SEC // 60",
       "                if await _browser_context_is_dead(browser):\n"
       "                    raise _p3_browser_gone(\"before the podcast could be downloaded\")\n"
       "                _audio_auto_retries += 1\n"
       "                _wait_min = _AUDIO_RETRY_INTERVAL_SEC // 60")]),
    ("B4", RESEARCH, "⛔ the login command's closed Chrome is relaunched — a fight for "
     "the profile being signed into",
     [("    if _login_interrupt_active():\n"
       "        _runtime.last_failure_kind = \"login_interrupt\"\n"
       "        log(f\"[Phase3] the login command closed the browser",
       "    if False:\n"
       "        _runtime.last_failure_kind = \"login_interrupt\"\n"
       "        log(f\"[Phase3] the login command closed the browser")]),
    ("B5", RESEARCH, "⛔ the crash carries neither its flag nor its marker — an ordinary "
     "failure, no relaunch",
     [("    _runtime.last_failure_kind = \"browser_crash\"\n"
       "    log(f\"[Phase3] the browser is gone {where}",
       "    log(f\"[Phase3] the browser is gone {where}"),
      ("    return RuntimeError(f\"research browser died {where} (browser crash)\")",
       "    return RuntimeError(f\"research browser died {where}\")")]),

    # ═══ C — once the relaunches are spent, the report still goes out ═══════
    ("C1", RESEARCH, "⛔⛔ the download spends a Chrome relaunch on every death — once "
     "they run out the run ends on \"Chrome kept closing\" with nothing delivered",
     [("                log(\"[Phase3] Chrome closed under the podcast download — no file \"\n"
       "                    \"this time\", \"WARN\")",
       "                raise _p3_browser_gone(\"while the podcast was downloading\")")]),
    ("C2", RESEARCH, "⛔⛔ the loop unwinds a dead browser with no relaunch left — the "
     "crash card, no hand-off, delivery left \"ongoing\"",
     [("                    if _login_interrupt_active() or _crash_retries < BROWSER_CRASH_MAX_RETRIES:",
       "                    if True:")]),
    ("C3", RESEARCH, "⛔ one unwind past the budget: the last death still ends on the "
     "crash card",
     [("                    if _login_interrupt_active() or _crash_retries < BROWSER_CRASH_MAX_RETRIES:",
       "                    if _login_interrupt_active() or _crash_retries <= BROWSER_CRASH_MAX_RETRIES:")]),
    ("C4", RESEARCH, "a relaunch that was still owed is not made — the podcast given up "
     "one Chrome too early",
     [("                    if _login_interrupt_active() or _crash_retries < BROWSER_CRASH_MAX_RETRIES:",
       "                    if _login_interrupt_active() or _crash_retries < BROWSER_CRASH_MAX_RETRIES - 1:")]),
    ("C5", RESEARCH, "⛔ the login command's close is counted as a crash — past the budget "
     "the run is ended without the podcast while the person signs in",
     [("                    if _login_interrupt_active() or _crash_retries < BROWSER_CRASH_MAX_RETRIES:",
       "                    if _crash_retries < BROWSER_CRASH_MAX_RETRIES:")]),
    ("C6", RESEARCH, "⛔ with the relaunches spent the loop still waits five minutes, three "
     "times, retrying on a browser that is gone",
     [("                if _p3_chrome_spent or _audio_auto_retries >= _AUDIO_MAX_AUTO_RETRIES:",
       "                if _audio_auto_retries >= _AUDIO_MAX_AUTO_RETRIES:")]),
    ("C7", RESEARCH, "the log says \"after 3 auto-retries\" about retries that never ran",
     [("                    if _p3_chrome_spent:\n",
       "                    if False:\n")]),
    # ═══ W — only the worker that made the notebook carries on in it ═════════
    ("W1", RESEARCH, "⛔⛔ another worker's notebook is carried on in, on this worker's "
     "profile — maybe another Google account's",
     [("            _p3_recorded_nb = _p3_notebook_to_reopen(cp)",
       "            _p3_recorded_nb = cp.get(\"notebook_url\") or \"\"")]),
    ("W2", RESEARCH, "⛔ any recorded worker is taken for this one",
     [(WORKER_GATE, WORKER_GATE.replace(" and made_on == WORKER_ID:", ":"))]),
    ("W3", RESEARCH, "⛔ a checkpoint that does not name the worker is taken for this one's",
     [('    made_on = (cp or {}).get("notebook_worker")\n',
       '    made_on = (cp or {}).get("notebook_worker", WORKER_ID)\n')]),
    ("W4", RESEARCH, "⛔⛔ the worker is never recorded — no resume ever carries on in its "
     "own notebook again",
     [('    if cp.get("notebook_url") and "notebook_worker" not in cp:\n'
       '        cp["notebook_worker"] = WORKER_ID\n', "")]),
    ("W5", RESEARCH, "the checkpoint names the worker that made the OLD notebook after a "
     "new one was made here",
     [('    if cp.get("notebook_url") and "notebook_worker" not in cp:\n'
       '        cp["notebook_worker"] = WORKER_ID\n',
       '    if cp.get("notebook_url") and "notebook_worker" not in cp:\n'
       '        cp["notebook_worker"] = (load_checkpoint(queue_dir) or {}).get(\n'
       '            "notebook_worker", WORKER_ID)\n')]),

    # ═══ P — a resume past Phase 1 writes the brief to the app again ══════════
    ("P1", RESEARCH, "⛔⛔ the resume trusts brief.md and never writes the brief to the app",
     [("                    _resave_phase1_on_resume(raw)\n", "")]),
    ("P2", RESEARCH, "⛔ no brief on the Documents page",
     [('    save_document_to_firestore("brief", brief_md, "Research Brief")\n'
       '    url = in_app_document_url("brief")\n',
       '    url = in_app_document_url("brief")\n')]),
    ("P3", RESEARCH, "⛔ no Read Brief report link on the resumed run",
     [('    _update_firestore_research({"links.phase1": [\n',
       '    (lambda *_a: None)({"links.phase1": [\n')]),
    ("P4", RESEARCH, "⛔ Phase 1 is never marked complete after a reload",
     [('        {"label": "Read Brief report", "url": url, "verified": True, "primary": True}]})\n'
       '    _write_phase_terminal_status(1, "complete")\n',
       '        {"label": "Read Brief report", "url": url, "verified": True, "primary": True}]})\n')]),
    ("P5", RESEARCH, "the record's brief slot is left empty for the Doc and the video",
     [("    url = in_app_document_url(\"brief\")\n    _record_brief_in_aggregate(url)\n",
       "    url = in_app_document_url(\"brief\")\n")]),
    ("P6", RESEARCH, "⛔ the link goes out under a label the app's backfill does not make — "
     "the brief row shows twice",
     [('        {"label": "Read Brief report", "url": url, "verified": True, "primary": True}]})\n'
       '    _write_phase_terminal_status(1, "complete")\n',
       '        {"label": "Read brief", "url": url, "verified": True, "primary": True}]})\n'
       '    _write_phase_terminal_status(1, "complete")\n')]),
    ("P7", RESEARCH, "⛔ an empty brief on disk is called Phase 1 complete, with a link to "
     "nothing",
     [('    if not (brief_md or "").strip():\n        return\n    save_document_to_firestore(',
       '    save_document_to_firestore(')]),
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
    # ⛔⛔ AN IN-FLIGHT MARKER: a killed run must not leave a mutant in the source
    # silently. Run harnesses in a throwaway worktree, never in the live checkout.
    _INFLIGHT = Path(__file__).with_suffix(".inflight")
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    # ⛔ A SIGTERM MUST RESTORE TOO: Python's default SIGTERM skips `finally:`.
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
        print("⛔ BASELINE SKIPPED TESTS — a skipped baseline is not a measurement.\n"
              + out[-1500:])
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
