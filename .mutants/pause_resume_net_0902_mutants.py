"""Mutation harness — stretch 7.5 STEP 1, the pause/resume safety net (2026-09-02).

⛔⛔ WHAT THIS CODE DECIDES. Whether a paused run comes back as the same run, or
comes back missing agents that the user is then told "crashed". Stretch 7.5
removes the conversation URL from every display and delivery surface — and that
same URL is the reattachment key this path reopens tabs at. Step 1 builds no
product change; it makes that break *loud*, because before this file every one of
these functions had ZERO test references anywhere in the repo.

⭐⭐ THE SHARPEST MUTANTS HERE:
  R3  — the empty-URL skip goes, so the resume opens a tab at "" and "restores"
        an agent onto a blank page. This is the shape a naive 7.5 sweep produces:
        the capture is gone, the reattach still runs, and the leg comes back
        pointed at nothing.
  R4  — the reattachment URL is dropped from the checkpoint restore, so EVERY
        agent silently fails to come back. The whole run is lost, quietly.
  R5  — `new_tab(url)` becomes `new_tab()`. The tab opens, the loop reports the
        agent restored, and it is attached to a fresh blank page — the most
        deceptive version of the same bug, because nothing errors.
  P6  — the pause stops awaiting the pause event, so Pause is instantly Resume.
        The run never stops and the checkpoint is written for nothing.
  P7  — the pause reports "not stopped" after a stop, so a stopped run walks on
        into the reattach path.
  D1  — the hand-off starts reading the links file's CONTENT instead of its
        existence. That is precisely the mistake step 5 is one edit away from:
        emptying the file is meant to be safe, and this makes it cost a phase.
  D2  — the links hand-off goes entirely, so a Flow B/C resume drops back into
        phase 2 and re-runs the whole research phase.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ SCORED AGAINST THIS STEP'S OWN GUARDS by default (`-k`), because a kill
borrowed from a pre-existing test is not evidence that the guard just written
works. `--unfiltered` asks the other question — whether the TREE catches it.

⛔⛔ AND `-k` THAT SELECTS NOTHING EXITS 5, WHICH A NAIVE RUNNER READS AS A KILL.
`_pytest` separates that case out; the filtered selection is verified to cover
EVERY test in the file this step owns before a single mutant is applied — a
count is the wrong property, and that was learned one stretch ago the hard way.

    .venv/bin/python .mutants/pause_resume_net_0902_mutants.py
    .venv/bin/python .mutants/pause_resume_net_0902_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The net itself, plus the two existing suites that read this state hand-off —
# so `--unfiltered` can answer "does the tree catch it?" honestly.
SUITES = ("tests/test_pause_resume_safety_net_0902.py "
          "tests/test_browser_crash_recovery.py "
          "tests/test_resume_at_phase5_handoff.py")

MINE = ("pause or resume or reattach or checkpoint or links_file or "
        "hands_the_run_over or hands_over or carries_the_run or "
        "podcast or terminal or saved_urls or no_saved_url or "
        "signed_out or refuses_to_open or blocks_until or "
        "browser_that_is_already_gone or no_queue_dir or "
        "dead_page_handles or urls_at_all or removing_the_links_write")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the very
# guard written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one. Every test in the file this step owns must be
# selected, or the harness refuses to score.
OWNED_FILES = ("tests/test_pause_resume_safety_net_0902.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
SAVE_CALL = "    save_pause_checkpoint(queue_dir, extra=extra_kwargs)"
PAUSED_EMIT = ('        emit_event("pipeline_paused", phase=phase,\n'
               '                   snapshot=_runtime.snapshot())')
# ⚠ THE CONTEXT TEST, NOT THE `browser is not None` TEST. Removing the None
# guard is an EQUIVALENT MUTANT — the AttributeError lands in the `except
# Exception` two lines below and the function completes exactly as before, so
# nothing observable changes and it would report as a survivor for no reason.
# Inverting the context test has a real consequence in both directions: a live
# browser is left open, and a dead one is closed twice.
BROWSER_GUARD = "            if browser.context is not None:"
# ⚠ Scoped to the pause site on purpose — the bare `await browser.close()` line
# matches three times in research.py, and the anchor ratchet caught it.
CLOSE_CALL = ('                log("[pause] Closing browser for resource-efficient pause...")\n'
              "                await browser.close()")
PAGES_CLEAR = "    _runtime.active_pages.clear()\n"
WAIT_CALL = "    # Block on pause event\n    await _controls.wait_if_paused()\n"
STOP_RETURN = "    return _controls.is_stop()  # True if stopped during pause"

QD_GUARD = ('def save_pause_checkpoint(queue_dir, extra=None):\n'
            '    """Write a full pause checkpoint combining runtime snapshot + extra fields."""\n'
            '    if not queue_dir:\n'
            '        return\n')
PAUSED_FLAG = '    cp["paused"] = True'
SNAP_CALL = ('    cp = _runtime.snapshot()\n'
             '    cp["timestamp"] = datetime.now().isoformat()')
SNAP_URLS = '            "agent_chat_urls": dict(self.agent_chat_urls),'

CP_GUARD = ('    if cp:\n'
            '        _runtime.phase = cp.get("phase", _runtime.phase)\n'
            '        _runtime.sub_state = cp.get("sub_state", "")\n'
            '        _runtime.agent_chat_urls = dict(cp.get("agent_chat_urls", {}))\n'
            '        _runtime.agent_statuses = dict(cp.get("agent_statuses", {}))\n'
            '        _runtime.original_inputs = dict(cp.get("original_inputs", {}))\n')
CP_PHASE = '        _runtime.phase = cp.get("phase", _runtime.phase)'
CP_SUBSTATE = '        _runtime.sub_state = cp.get("sub_state", "")'
CP_URLS = '        _runtime.agent_chat_urls = dict(cp.get("agent_chat_urls", {}))'
CP_INPUTS = '        _runtime.original_inputs = dict(cp.get("original_inputs", {}))'
DONE_SKIP = ('        if status == "done":\n'
             "            continue  # Don't reopen completed agents")
URL_SKIP = "        if not url:\n            continue\n"
NEW_TAB = ("            page = await browser.new_tab(url)\n"
           "            await asyncio.sleep(3)")
FAIL_CALL = ('                fail_agent(platform,\n'
             '                           f"{platform.capitalize()} session expired",')
EXPIRY_SKIP = ('                           f"{platform.capitalize()} signed out. Sign back in using the open browser, then Retry — or Skip it.")\n'
               "                continue\n")
REGISTER = ("            restored[platform] = page\n"
            "            _runtime.register_page(platform, page, url)")
REOPEN_CATCH = ("        except Exception as e:\n"
                '            log(f"[resume] {platform} reopen failed: {e}", "WARN")')
RESUMED_EMIT = ('    emit_event("pipeline_resumed", phase=_runtime.phase,\n'
                "               restored=list(restored.keys()))")
CLEAR_CP = "    clear_pause_checkpoint(queue_dir)\n    return restored"
START_CALL = "    await browser.start()\n    restored = {}"

LINKS_BRANCH = ('    if (queue_dir / "links.json").exists():\n'
                '        return 3, "Links exist — resuming from Phase 3 (NotebookLM)"')
MARKER_BRANCH = ('    if marker.exists():\n'
                 '        return 3, "Phase 2 complete marker present — resuming from Phase 3"')
PARTIAL_BRANCH = ('    if has_partial_research:\n'
                  '        return 2, "Phase 2 partial MDs present without completion marker — re-running Phase 2 (all agents)"')
PAUSE_HEAD = ('async def pause_and_close_browser(browser, queue_dir, phase, extra_kwargs=None):\n'
              '    """Save pause checkpoint → close browser → block until resume or stop."""\n'
              '    _runtime.phase = phase\n')
YT_BRANCH = ('    if cp and cp.get("youtube_url"):\n'
             '        return 5, "YouTube done — Phase 4 complete, FE will pick up Phase 5"')
AUDIO_BRANCH = ('    if audio_dir.exists() and any(audio_dir.glob("*.*")):\n'
                '        return 4, "Audio exists — Phase 3 done, resuming from Phase 4 (YouTube)"')
DELIVERY_BRANCH = ('            if delivery.get("status") == "completed":\n'
                   '                return 6, "Pipeline already complete"')

# (id, direction, why, [(from, to), ...])
MUTANTS = [
    # ═════════ P — the pause half ═══════════════════════════════════════════
    ("P1", "over",
     "the checkpoint is never written, so a paused run has no reattachment key "
     "on disk at all and a resume finds nothing to come back to",
     [(SAVE_CALL, "    pass")]),
    ("P2", "over",
     "the paused event stops carrying the snapshot, so the app is told a run "
     "paused but not which conversations it paused on",
     [(PAUSED_EMIT, '        emit_event("pipeline_paused", phase=phase)')]),
    ("P3", "over",
     "the browser is never closed on pause — the whole point of the pause is "
     "to give the machine back its memory",
     [(CLOSE_CALL,
       '                log("[pause] Closing browser for resource-efficient pause...")')]),
    ("P4", "over",
     "the dead page handles are kept, so the crash sweep is handed zombie pages "
     "that answer neither alive nor closed",
     [(PAGES_CLEAR, "")]),
    ("P5", "over",
     "⛔ the live-session test inverts, so a running browser is left open on "
     "pause and a session that is already gone is closed a second time",
     [(BROWSER_GUARD, "            if browser.context is None:")]),
    ("P6", "over",
     "⛔⛔ THE PAUSE STOPS PAUSING. Without the await, Pause returns immediately: "
     "the run never stops, the user's Pause does nothing, and the checkpoint was "
     "written for a run that kept going",
     [(WAIT_CALL, "    # Block on pause event\n")]),
    ("P7", "over",
     "⛔⛔ a stop during the pause reports 'not stopped', so a stopped run walks "
     "straight into the browser relaunch and reattach path",
     [(STOP_RETURN, "    return False  # True if stopped during pause")]),
    ("P8", "over",
     "⛔ the queue-dir guard INVERTS, so the checkpoint is written only when "
     "there is nowhere to write it and every real pause saves nothing. "
     "⚠ Deleting the guard outright is an EQUIVALENT MUTANT — the resulting "
     "`Path(None)` lands in the write's own `except` and nothing observable "
     "changes, so it would read as a survivor for no reason",
     [(QD_GUARD,
       'def save_pause_checkpoint(queue_dir, extra=None):\n'
       '    """Write a full pause checkpoint combining runtime snapshot + extra fields."""\n'
       '    if queue_dir:\n'
       '        return\n')]),
    ("P9", "under",
     "the checkpoint no longer marks itself paused — a crash-recovery reader "
     "cannot tell a deliberate pause from an abandoned run",
     [(PAUSED_FLAG, '    cp["paused"] = False')]),
    ("P10", "over",
     "⛔⛔ the snapshot drops the agent URLs, so the pause writes a checkpoint "
     "with everything EXCEPT the one field the resume needs",
     [(SNAP_URLS, "")]),

    ("P12", "over",
     "⛔⛔ an existing checkpoint is REUSED instead of rebuilt, so a second "
     "pause writes the state from the first and the resume reattaches to the "
     "address the agent had before it moved — a stale conversation, which is "
     "the exact failure class this whole stretch exists to remove",
     [(SNAP_CALL,
       '    cp = load_pause_checkpoint(queue_dir) or _runtime.snapshot()\n'
       '    cp["timestamp"] = datetime.now().isoformat()')]),

    # ═════════ R — the resume half ══════════════════════════════════════════
    ("R1", "over",
     "the phase is not restored from the checkpoint, so a resumed run reports "
     "whatever phase the fresh process happened to be in",
     [(CP_PHASE, "        pass")]),
    ("R2", "over",
     "the sub-state is not restored, so a run paused mid-poll resumes as if it "
     "were idle",
     [(CP_SUBSTATE, "        pass")]),
    ("R3", "over",
     "⛔⛔⛔ THE EMPTY-URL SKIP GOES. This is the exact shape a naive 7.5 sweep "
     "produces: the capture is removed, the reattach still runs, and the agent "
     "is 'restored' onto a tab opened at the empty string",
     [(URL_SKIP, "")]),
    ("R4", "over",
     "⛔⛔⛔ THE REATTACHMENT KEY IS NEVER READ BACK. Every agent silently fails "
     "to return and the whole paused run is lost with no error anywhere",
     [(CP_URLS, "        pass")]),
    ("R5", "over",
     "⛔⛔ the tab is opened with NO url. Nothing errors, the loop reports the "
     "agent restored, and it is attached to a blank page — the most deceptive "
     "version of losing the key",
     [(NEW_TAB, "            page = await browser.new_tab()\n            await asyncio.sleep(3)")]),
    ("R6", "over",
     "finished agents are reopened too, so a completed leg is re-polled and can "
     "overwrite a report already on disk",
     [(DONE_SKIP, '        if status == "never":\n            continue')]),
    ("R7", "over",
     "a signed-out agent is no longer failed — it just vanishes from the run "
     "with nothing telling the user to sign in",
     [(FAIL_CALL,
       '                _ = (platform,\n'
       '                     f"{platform.capitalize()} session expired",')]),
    ("R8", "over",
     "⛔ the session-expiry branch stops skipping, so an agent whose auth check "
     "just failed is registered as successfully restored",
     [(EXPIRY_SKIP,
       '                           f"{platform.capitalize()} signed out. Sign back in using the open browser, then Retry — or Skip it.")\n')]),
    ("R9", "over",
     "restored pages are never re-registered, so the poll loop cannot find the "
     "tabs the resume just reopened",
     [(REGISTER, "            restored[platform] = page")]),
    ("R10", "over",
     "one tab that refuses to open now aborts the entire resume, taking the "
     "healthy legs with it",
     [(REOPEN_CATCH,
       "        except KeyboardInterrupt as e:\n"
       '            log(f"[resume] {platform} reopen failed: {e}", "WARN")')]),
    ("R11", "under",
     "the resumed event no longer names who came back, so nothing downstream "
     "can tell a full recovery from a partial one",
     [(RESUMED_EMIT,
       '    emit_event("pipeline_resumed", phase=_runtime.phase,\n'
       "               restored=[])")]),
    ("R12", "over",
     "the pause checkpoint is left on disk after a successful resume, so a "
     "later crash replays a pause that is already over",
     [(CLEAR_CP, "    return restored")]),
    ("R13", "over",
     "the browser is never started, so every reattach runs against a dead "
     "session",
     [(START_CALL, "    restored = {}")]),
    ("R15", "over",
     "⛔⛔ the `if cp:` guard goes, so a resume with no checkpoint on disk "
     "OVERWRITES the live reattachment keys with an empty dict — every "
     "still-running agent is lost by the very code meant to bring it back",
     [(CP_GUARD,
       '    _runtime.phase = cp.get("phase", _runtime.phase)\n'
       '    _runtime.sub_state = cp.get("sub_state", "")\n'
       '    _runtime.agent_chat_urls = dict(cp.get("agent_chat_urls", {}))\n'
       '    _runtime.agent_statuses = dict(cp.get("agent_statuses", {}))\n'
       '    _runtime.original_inputs = dict(cp.get("original_inputs", {}))\n')]),
    ("R14", "over",
     "the original inputs are not restored, so a resumed run has lost the topic "
     "and brief it was researching",
     [(CP_INPUTS, "        pass")]),

    # ═════════ D — the research → podcast hand-off ══════════════════════════
    ("D1", "over",
     "⛔⛔⛔ THE HAND-OFF STARTS READING THE FILE'S CONTENT. This is the one edit "
     "step 5 is closest to making: emptying the links file is supposed to be "
     "safe, and this makes an emptied file cost a whole research phase",
     [(LINKS_BRANCH,
       '    if (queue_dir / "links.json").exists() and len((queue_dir / "links.json").read_text(encoding="utf-8")) > 4:\n'
       '        return 3, "Links exist — resuming from Phase 3 (NotebookLM)"')]),
    ("D2", "over",
     "⛔⛔ the links hand-off goes entirely, so a Flow B/C resume — the runs that "
     "never write the phase-2 marker — drops back into phase 2 and re-runs the "
     "whole research phase",
     [(LINKS_BRANCH, "")]),
    ("D3", "over",
     "the phase-2 marker hand-off goes, leaving the links file as the only "
     "signal — so a replacement for it would have nowhere to live",
     [(MARKER_BRANCH, "")]),
    ("D4", "under",
     "the links file now hands over to phase 4, skipping the podcast phase "
     "entirely on every resume",
     [(LINKS_BRANCH,
       '    if (queue_dir / "links.json").exists():\n'
       '        return 4, "Links exist — resuming from Phase 3 (NotebookLM)"')]),
    ("D5", "over",
     "a finished podcast no longer carries the run past phase 3, so a resume "
     "re-runs NotebookLM on a run that already has its audio",
     [(AUDIO_BRANCH,
       '    if audio_dir.exists() and any(audio_dir.glob("*.*")):\n'
       '        return 3, "Audio exists — Phase 3 done, resuming from Phase 4 (YouTube)"')]),
    ("D6", "over",
     "a published video sends the resume back to the podcast phase, so a run "
     "that is already on YouTube would build its podcast again",
     [(YT_BRANCH,
       '    if cp and cp.get("youtube_url"):\n'
       '        return 3, "YouTube done — Phase 4 complete, FE will pick up Phase 5"')]),
    ("D7", "over",
     "a completed delivery stops being terminal, so a finished run is resumable "
     "and can be delivered twice",
     [(DELIVERY_BRANCH,
       '            if delivery.get("status") == "never":\n'
       '                return 6, "Pipeline already complete"')]),
    ("D8", "over",
     "⛔ partial research with NO completion marker is treated as finished, so "
     "the run hands over to the podcast phase carrying only the agents that "
     "happened to have written a file — the coarse-marker bug, restored",
     [(PARTIAL_BRANCH,
       '    if has_partial_research:\n'
       '        return 3, "Phase 2 partial MDs present without completion marker — re-running Phase 2 (all agents)"')]),

    # ═════════ P11 — the pause's own early exit ═════════════════════════════
    ("P11", "over",
     "the pause bails out entirely when it has no queue dir, so a bad dir costs "
     "the browser close AND the pause itself — the run keeps going while the "
     "user is told it paused",
     [(PAUSE_HEAD,
       'async def pause_and_close_browser(browser, queue_dir, phase, extra_kwargs=None):\n'
       '    """Save pause checkpoint → close browser → block until resume or stop."""\n'
       '    _runtime.phase = phase\n'
       '    if not queue_dir:\n'
       '        return False\n')]),
]


def _mark(mid: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{TARGET}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _stranded() -> str | None:
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _digest() -> dict:
    return {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FILES}


def _pytest(kfilter: str | None) -> str:
    """'green' | 'red' | 'nothing-collected'."""
    purge_pycache(ROOT)
    args = [sys.executable, "-B", "-m", "pytest", *SUITES.split(),
            "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    code = sh(args, cwd=ROOT, env=ENV).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(kfilter: str | None) -> bool:
    got = _pytest(kfilter)
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check the filter")
    return got == "green"


def _collected(files, kfilter: str | None) -> set:
    args = [sys.executable, "-B", "-m", "pytest", *files,
            "--collect-only", "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    out = sh(args, cwd=ROOT, env=ENV).stdout
    return {ln.strip() for ln in out.splitlines() if "::" in ln and not ln.startswith(" ")}


def _filter_misses(kfilter: str) -> set:
    return _collected(OWNED_FILES, None) - _collected(OWNED_FILES, kfilter)


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    kfilter = None if unfiltered else MINE

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — spot check, not a score.")
    print("scope: THE WHOLE SELECTION (--unfiltered)" if unfiltered
          else "scope: THIS STEP'S OWN GUARDS (-k) — pass --unfiltered for the other number")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- {TARGET}), then delete\n    {_INFLIGHT}")
        return 2

    if kfilter:
        missed = _filter_misses(kfilter)
        total = len(_collected(OWNED_FILES, None))
        print(f"filter covers {total - len(missed)}/{total} of this step's own tests")
        if missed:
            print("⛔⛔ THE FILTER CANNOT SEE SOME OF THIS STEP'S OWN GUARDS, so "
                  "any mutant only they could kill would report as a SURVIVOR:")
            for tid in sorted(missed):
                print(f"    {tid}")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests(kfilter) or not run_tests(None):
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green (filtered and whole)\n")

    path = ROOT / TARGET
    survivors, faults, flaky = [], [], []
    for mid, direction, why, edits in selected:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            try:
                compile(mutated, TARGET, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                    "check the anchor's indentation") from None
            _mark(mid)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            # ⛔⛔ A FLAP IS ITS OWN OUTCOME, NOT A SURVIVOR. On disagreement,
            # run a third time and take the majority — reported separately,
            # because "the guards cannot see this" and "that run was noisy" are
            # different claims and collapsing them sends the next reader hunting
            # a defect that is not there.
            verdicts = [not run_tests(kfilter) for _ in range(SURVIVOR_CONFIRMATIONS)]
            flapped = len(set(verdicts)) > 1
            if flapped:
                verdicts.append(not run_tests(kfilter))
            killed = sum(verdicts) * 2 > len(verdicts)
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = (f"  ⚠ FLAPPED {sum(verdicts)}/{len(verdicts)} — tie broken by "
                    "majority" if flapped else "")
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
            elif flapped:
                flaky.append((mid, sum(verdicts), len(verdicts)))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    if (left := [f for f in before if before[f] != after[f]]):
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in left))
        return 3

    over = sum(1 for m in selected if m[1] == "over")
    scope = " [whole selection]" if unfiltered else " [own guards]"
    label = " (SPOT CHECK)" if only else ""
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if flaky:
        print(f"⚠ {len(flaky)} FLAPPED and were resolved by majority — killed, "
              f"but this selection is not perfectly stable:")
        for mid, k, n in flaky:
            print(f"    {mid}: killed in {k} of {n} runs")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
