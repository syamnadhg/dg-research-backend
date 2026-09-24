"""Every window a browser can die in, and the marker that survives the unwind.

⛔⛔ THE INCIDENT — support bundle 8D9CWHZJ, 2026-09-20. Chrome's BROWSER process
took a SIGSEGV; macOS wrote the report itself. Nothing in this repo closed it.
What was ours is everything after: the phase-2 sweep asked `page.is_closed()`, a
question about ONE TAB, so a whole dead browser was indistinguishable from three
dead tabs. It failed each agent, emptied `pending`, let Phase 2 report
"COMPLETE: 1/3", and then parked a Retry card about a browser that no longer
existed. Nine hours, ended by the owner's own Stop.

⛔⛔ AND THE FIRST REPAIR CLOSED ONE WINDOW OF FIVE. An adversarial pass over it
found four more paths to the same nine hours, each one soft in its own way:

  B1 — the phase-3 AUDIO POLL, still on `_poll_pg.is_closed()`. The very lens
       the sweep's own commit message says cost the nine hours, left in place
       one phase over.
  B2 — the phase-2 HARD RETRY's `except Exception`, which fails one agent and
       `del pending[...]` on anything at all. The only path that can drain
       `pending` without the sweep ever running.
  B3 — the phase-3 ENTRY GATE. "None of the agents produced a report" is a true
       sentence about a dead browser and a useless one, and the wait takes
       `await_phase_decision`'s 24-hour default.
  B4/B5 — the NOTEBOOK PARK, worst of the four: every rung answers softly on a
       dead page, and the block sits OUTSIDE `_await_phase_with_active_deadline`
       so no 15-minute ceiling covers it. A straight 24-hour hang. B5 is the
       ORDERING — `_page_shows_login_wall` never raises and answers None on a
       dead page, so asking it first sends a crash down the "signed out" branch.
  B6/B7 — THE COUPLING. Each site raises a RuntimeError in OUR words, and none
       of those words matched `_is_browser_close_error`, so the entire recovery
       rode on `_runtime.last_failure_kind` — one side channel, set on the line
       before the raise, pinned by nothing. B7 is the other direction and is
       the dangerous one: a `--login` kill that classified as a crash would
       relaunch Chrome onto the profile being signed into, and the login side
       would kill it again. A fight, not a recovery.
  B8 — the sweep's raise itself. Setting the flag unwinds NOTHING;
       `run_pipeline`'s failure path is what calls `_plan_pipeline_auto_retry`,
       and it only runs when something raises.
  B9 — the probe's fail-safe DIRECTION. A wrong "dead" unwinds a healthy run
       and relaunches Chrome underneath it; a wrong "alive" costs only what
       today already costs.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/browser_death_windows_0920_mutants.py
  .venv/bin/python .mutants/browser_death_windows_0920_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_browser_death_unwinds_0920.py "
          "tests/test_browser_death_unwinds_every_window_0920.py "
          "tests/test_browser_crash_recovery.py "
          "tests/test_browser_crash_copy_0827.py")

MINE = ("a_closed_context_is_recognised or a_live_context_is_not or "
        "a_missing_context_counts_as_dead or every_spelling_the_driver_uses or "
        "TargetClosedError_is_matched_by_its_TYPE_not_its_message or "
        "an_unrelated_error_does_NOT_read_as_a_dead_browser or "
        "the_probe_shares_the_classifier_rather_than_a_second_opinion or "
        "the_sweep_asks_whether_the_whole_browser_died or "
        "and_RAISES_so_the_checkpoint_recovery_can_run or "
        "a_single_dead_tab_is_still_just_a_failed_agent or "
        "a_user_skip_is_still_not_a_crash or the_login_interrupt_still_wins or "
        "phase_three_classifies_a_dead_browser_before_blaming_the_upload or "
        "the_cookie_gate_no_longer_buries_a_browser_death_at_debug or "
        "every_crash_we_raise_classifies_from_its_own_text or "
        "and_every_one_of_them_is_actually_in_the_source or "
        "a_login_interrupt_is_NOT_swept_up_by_the_marker or "
        "the_login_sites_carry_no_crash_marker_in_the_source or "
        "an_ordinary_failure_is_still_not_a_crash or "
        "a_crash_at_phase_two_really_does_plan_a_silent_retry or "
        "a_crash_in_any_phase_the_recovery_covers_is_planned or "
        "the_retry_is_capped_and_the_cap_is_not_infinity or "
        "a_user_stop_is_never_auto_retried or nor_is_a_terminal_delivery_status or "
        "a_login_interrupt_stands_down_rather_than_fighting or "
        "the_audio_poll_asks_the_CONTEXT_not_just_the_tab or "
        "the_phase_two_hard_retry_no_longer_drains_pending_on_a_dead_browser or "
        "the_phase_three_entry_gate_does_not_park_for_a_day_on_a_dead_browser or "
        "the_notebook_park_classifies_before_offering_an_impossible_retry")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_browser_death_unwinds_0920.py",
               "tests/test_browser_death_unwinds_every_window_0920.py")

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
#: The audio poll's widening — the cheap tab question, then the context.
POLL = ('        if not _browser_dead:\n'
        '            _browser_dead = await _browser_context_is_dead(browser)')
#: The hard-retry classification, ahead of failing one agent.
HARD = ('                if await _browser_context_is_dead(browser):\n'
        '                    _runtime.last_failure_kind = "browser_crash"')
#: The phase-3 entry gate's question.
GATE = ('            if await _browser_context_is_dead(browser):\n'
        '                _runtime.last_failure_kind = (\n'
        '                    "login_interrupt" if _login_interrupt_active() else "browser_crash")')
#: The notebook park's question, asked BEFORE the login-wall probe.
PARK = '                    if await _browser_context_is_dead(browser):'
#: The login-wall probe it must precede.
WALL = '                    _nb_wall = await _page_shows_login_wall(getattr(browser, "page", None))'
#: The marker that lets the unwind classify itself.
MARKER = '        or "(browser crash)" in msg'
#: The sweep's raise — the thing that makes the checkpoint recovery reachable.
SWEEP_RAISE = '                        "research browser died during phase 2 (browser crash)")'
#: The probe's fail-safe direction.
SAFE = '    except Exception as _e:\n        return _is_browser_close_error(_e)'

MUTANTS = [
    ("B1", "under",
     "⛔⛔ the audio poll goes back to the TAB-ONLY lens. That is the exact "
     "question the phase-2 sweep was asking when it cost nine hours — a browser "
     "process that is gone while the page object still reports open loops "
     "'Audio still generating...' forever, because every per-step failure in "
     "that loop is deliberately swallowed",
     [(POLL, "        if not _browser_dead:\n            pass")]),

    ("B2", "under",
     "⛔⛔ the hard-retry catch stops asking, so it fails ONE agent and deletes "
     "it from `pending` on a dead browser — the same draining the sweep used to "
     "do, reached without the sweep. Chrome dying while the last agents restart "
     "empties the set one agent at a time and Phase 2 reports COMPLETE",
     [(HARD, '                if False:\n                    _runtime.last_failure_kind = "browser_crash"')]),

    ("B3", "under",
     "⛔⛔ the phase-3 entry gate parks unclassified again. 'None of the agents "
     "produced a report' is TRUE of a dead browser and useless, the card offers "
     "a Retry that cannot run, and the wait takes await_phase_decision's "
     "24-hour default",
     [(GATE, '            if False:\n                _runtime.last_failure_kind = (\n'
             '                    "login_interrupt" if _login_interrupt_active() else "browser_crash")')]),

    ("B4", "under",
     "⛔⛔⛔ THE WORST WINDOW REOPENS. The notebook park stops asking, and "
     "nothing else there can tell: extract_notebooklm_url returns a RESULT "
     "rather than raising and _page_shows_login_wall is documented never to "
     "raise. This block sits OUTSIDE _await_phase_with_active_deadline, so "
     "there is no 15-minute ceiling — a straight twenty-four-hour hang behind "
     "a Retry that cannot work",
     [(PARK, "                    if False:")]),

    ("B5", "under",
     "⛔⛔ the ORDERING goes: the login-wall probe runs first. It answers None "
     "on a dead page, so a browser crash is reported as 'NotebookLM looks "
     "signed out' and the person is asked to sign in to a browser that does "
     "not exist. Worse than the hang, because it looks actionable",
     [(WALL + "\n", ""), (PARK, WALL + "\n" + PARK)]),

    ("B6", "under",
     "⛔⛔ the crash marker leaves the classifier, so the six sentences we "
     "raise stop classifying as browser deaths and the whole recovery rides on "
     "`_runtime.last_failure_kind` alone again — one side channel set on the "
     "line before the raise, which any reset on the unwind path silently turns "
     "into an ordinary one-shot failure",
     [(MARKER, '        or "(browser crash)" in tname')]),

    ("B7", "over",
     "⛔⛔⛔ THE DANGEROUS DIRECTION: the marker widens to bare 'browser' so a "
     "--login kill classifies as a crash. The run then relaunches Chrome onto "
     "the very profile the person is signing into and the login side kills it "
     "again — a fight between the two halves, each doing its job",
     [(MARKER, '        or "browser" in msg')]),

    ("B8", "under",
     "⛔⛔ the sweep sets the flag and does not raise. This IS the original "
     "defect: `run_pipeline`'s failure path is what calls "
     "`_plan_pipeline_auto_retry`, and it only runs when something raises, so "
     "the recovery machinery stays unreachable while every comment claims it "
     "resumes from the checkpoint",
     [("                    raise RuntimeError(\n" + SWEEP_RAISE,
       "                    _ = (\n" + SWEEP_RAISE)]),

    ("B9", "over",
     "⛔⛔ the probe stops failing safe: anything it cannot classify reads as a "
     "dead browser. A transient network blip or a permission error now unwinds "
     "a HEALTHY run and relaunches Chrome underneath it. A wrong 'alive' costs "
     "only what today already costs; a wrong 'dead' destroys work in progress",
     [(SAFE, "    except Exception as _e:\n        return True")]),
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
