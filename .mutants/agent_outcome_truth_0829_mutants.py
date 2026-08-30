"""Mutation harness — a Phase-2 agent that produced nothing must not look finished.

The owner watched a run where Gemini died and the tile drew a green tick. The
frontend half of that is fixed in the web app; this is the backend half, and the
backend half is the reason the frontend could not tell.

⛔⛔ THE DANGEROUS DIRECTION HERE IS THE OVER-CORRECTION, and every one of them
reads as a tidy-up. "Just write skipped for everything that is not done", "let
the backstop write unconditionally", "drop the `results and` guard", "overwrite
the sources while we are here" — each is one expression, each looks like a
simplification, and each replaces one lie with another.

⛔ THREE SPECIFIC THINGS THIS HARNESS IS WATCHING FOR.

  1. A backstop that OVERWRITES a real status. `fail_agent` writes "errored" with
     a REASON, and the UI shows that reason as a sentence. A backstop that
     flattened it into a bare "skipped" would destroy the only explanation the
     user gets — a fix that is worse than the bug, which is a shape this project
     has shipped before.
  2. A phase renamed "errored" when some agents DID deliver. Two of three is a
     finished phase; calling that failed is a second lie in the other direction.
  3. A source fallback that overwrites a real report's citations. An agent WITH a
     report already has the better list — what the report actually cited, not
     what the panel happened to show.

⛔⛔ THIS HARNESS DOES ITS OWN ANCHOR-UNIQUENESS CHECK. A presence test plus a
first-occurrence replace silently mutates a place the mutant was never about and
reports a kill.

⛔ AND A SKIP IS NOT A PASS. pytest exits 0 for a run in which tests were skipped
and for a run that collected far fewer than it should. This runner reads the
summary line and refuses a verdict rather than guessing — the backend suite
learned that on 2026-08-27, when 68 tests skipped for a missing `node`, pytest
exited 0, and a mutant three tests kill was reported as a survivor.

    .venv/bin/python .mutants/agent_outcome_truth_0829_mutants.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = ("tests/test_agent_outcome_truth_0829.py "
          "tests/test_p2_share_removed_0828.py tests/test_p3_audio_gate_0828.py "
          "tests/test_skip_reporting.py tests/test_alert_consistency_921.py "
          "tests/test_phase_notices_0816.py tests/test_drift_review_0805.py")

# The smallest passing-test count this harness accepts. A run that collects fewer
# has measured something other than the suite; the verdict is refused, not
# reported.
FLOOR = 150

MUTANTS = [
    # ══ B — the per-agent backstop ═════════════════════════════════════════

    ("B1", "under",
     "⛔⛔ THE HOLE, PUT BACK. The finalize loop returns to writing 'complete' for "
     "four statuses and nothing for the rest, so `partial`, `interrupted`, "
     "`browser_crashed` and `paused` all end the run on the launch-time 'running' "
     "— a value the frontend's status union did not even list",
     [('                _write_agent_terminal_status(\n'
       '                    _ag_key_lc, "skipped",\n'
       '                    reason="no_report_at_phase_end",\n'
       '                    detail=f"{_ag_name} finished without producing a report.")',
       '                pass  # the backstop is gone')]),

    ("B2", "over",
     "⛔⛔ THE BACKSTOP OVERWRITES A REAL STATUS. `fail_agent` writes 'errored' "
     "WITH a reason and the UI shows that reason as a sentence — flattening it "
     "into a bare 'skipped' destroys the only explanation the user gets, which is "
     "a fix worse than the bug it replaces",
     [('                if _p2_recorded.get(_ag_key_lc) in ("complete", "skipped", "errored"):\n'
       '                    continue\n',
       '')]),

    ("B3", "over",
     "⛔⛔ THE BACKSTOP REDDENS INSTEAD OF GREYING. We do not know that the agent "
     "FAILED — only that the run ended with nothing from it — so 'errored' claims "
     "a diagnosis nothing recorded, and the user is shown an alarm for something "
     "that may simply have been stopped",
     [('                    _ag_key_lc, "skipped",\n'
       '                    reason="no_report_at_phase_end",',
       '                    _ag_key_lc, "errored",\n'
       '                    reason="no_report_at_phase_end",')]),

    ("B4", "over",
     "⛔ A FINISHED AGENT FALLS THROUGH TO THE BACKSTOP as well as taking the fast "
     "path, so a completed report is re-stamped 'skipped' a line later. "
     "⚠ REWRITTEN 2026-08-29: the first version dropped only the `continue` and was "
     "EQUIVALENT — `_p2_recorded` is a LIVE reference into `_agent_status_by_rid`, "
     "and the status helper records synchronously BEFORE its async write, so the "
     "guard two lines down already saw the 'complete' this same iteration had just "
     "written. There are two defences here and removing one changes nothing; the "
     "mutant has to take both to be the defect it describes",
     [('                    _write_agent_terminal_status(_ag_key_lc, "complete")\n'
       '                    continue',
       '                    _write_agent_terminal_status(_ag_key_lc, "complete")'),
      ("            _p2_recorded = _agent_status_by_rid.get(_fb_research_id, {}) or {}",
       "            _p2_recorded = dict(_agent_status_by_rid.get(_fb_research_id, {}) or {})")]),

    ("B5", "over",
     "⛔ THE RECORDED-STATUS GUARD READS THE WRONG MAP, so it never matches and "
     "every agent is re-stamped by the backstop regardless of what was written",
     [("            _p2_recorded = _agent_status_by_rid.get(_fb_research_id, {}) or {}",
       "            _p2_recorded = {}")]),

    # ══ T — the off-topic rejection ════════════════════════════════════════

    ("T1", "under",
     "⛔⛔ THE WORST OF THE THREE COMES BACK, and it is not a missing write but a "
     "WRONG one: the sweep rejects a foreign-topic report AFTER 'complete' was "
     "persisted, and nothing rewrites it — so a report we deliberately refused is "
     "reported to the user as a completed agent with a green tick",
     [('                if _ag_r.get("off_topic_rejected"):', "                if False:")]),

    ("T2", "under",
     "⛔⛔ THE OFF-TOPIC WRITE STOPS BEING FORCED, so the stale 'complete' already "
     "on the record is what the user keeps seeing",
     [('                        _ag_key_lc, "errored", force=True,\n'
       '                        reason="off_topic_rejected",',
       '                        _ag_key_lc, "errored",\n'
       '                        reason="off_topic_rejected",')]),

    ("T3", "over",
     "⛔ THE REJECTION IS RECORDED AS A GREY SKIP, so a report we read and refused "
     "is presented as if nothing ever ran — losing the one thing we actually know "
     "about it",
     [('                        _ag_key_lc, "errored", force=True,\n'
       '                        reason="off_topic_rejected",',
       '                        _ag_key_lc, "skipped", force=True,\n'
       '                        reason="off_topic_rejected",')]),

    ("T4", "over",
     "⛔ THE OFF-TOPIC BRANCH FALLS THROUGH INTO THE BACKSTOP, so the errored write "
     "is immediately followed by a skipped one and the last writer wins. "
     "⚠ REWRITTEN 2026-08-29 for the same reason as B4 — dropping the `continue` "
     "alone was equivalent, because the live recorded-status guard below already "
     "catches the 'errored' this branch just wrote",
     [('                               f"topic, so it was not used.")\n'
       '                    continue',
       '                               f"topic, so it was not used.")'),
      ('                if _p2_recorded.get(_ag_key_lc) in ("complete", "skipped", "errored"):\n'
       '                    continue\n',
       '')]),

    # ══ P — the phase's own status ═════════════════════════════════════════

    ("P1", "under",
     "⛔⛔ THE PHASE IS 'complete' AGAIN even when every single agent died — "
     "`done_count` goes back to gating nothing but a log line, and the tile paints "
     "a green phase node over a Phase 2 that produced nothing at all",
     [("            _p2_wipeout = (done_count == 0 and (bool(results) or _p2_user_skipped))",
       "            _p2_wipeout = False")]),

    ("P2", "over",
     "⛔⛔ A PHASE WHERE SOME AGENTS DELIVERED IS CALLED ERRORED. Two of three is a "
     "finished phase, and renaming it is a second lie in the other direction — "
     "the per-agent record is where a single agent's fate belongs",
     [("            _p2_wipeout = (done_count == 0 and (bool(results) or _p2_user_skipped))",
       "            _p2_wipeout = (done_count < len(results))")]),

    ("P3", "over",
     "⛔ AN ALL-DISABLED PHASE IS REPORTED AS ERRORED. Every agent turned off in "
     "config leaves `results` empty — a phase that had nothing to do, not one that "
     "failed",
     [("            _p2_wipeout = (done_count == 0 and (bool(results) or _p2_user_skipped))",
       "            _p2_wipeout = (done_count == 0)")]),

    ("P4", "over",
     "⛔⛔ THE EVENT IS EMITTED BEFORE THE VERDICT AGAIN, so the frontend announces "
     "'Research docs ready' — a push and an email — for a run where every agent "
     "died. And the correction then RACES its own event: the emit hook writes the "
     "phase status on a daemon thread and the fix writes it on another, "
     "non-transactionally, on the same array",
     [("                skipped=_p2_wipeout,\n", "")]),

    ("P5", "under",
     "⛔⛔ A PHASE THE USER EXPLICITLY SKIPPED IS RECORDED COMPLETE. That path leaves "
     "`results` empty, so dropping the user-skip term lets it straight through — "
     "after `phase_skipped` had already said otherwise",
     [("            _p2_wipeout = (done_count == 0 and (bool(results) or _p2_user_skipped))",
       "            _p2_wipeout = (done_count == 0 and bool(results))")]),

    ("H1", "under",
     "⛔⛔ AN AGENT THAT SALVAGED TEXT IS TOLD IT PRODUCED NOTHING, while the same "
     "block writes that text to disk and to Firestore — the sentence is "
     "contradicted by the report sitting in the person's documents list",
     [('                if (_ag_r.get("text") or "").strip():', "                if False:")]),

    ("H2", "under",
     "⛔⛔ A CRASH WE WATCHED IS FLATTENED INTO THE GREY A DELIBERATE SKIP PRODUCES, "
     "throwing away the one thing we actually know about it",
     [('                if _ag_status in ("browser_crashed", "not_verified", "wrong_conversation"):',
       "                if False:")]),

    ("H3", "over",
     "⛔ THE KNOWN-FAILURE COPY SPECULATES ABOUT A CAUSE THE RUN DID NOT RECORD, "
     "which is the one thing every sentence in this file is written not to do",
     [('        "{name}\'s tab stopped responding partway through and the run continued without it.",',
       '        "{name} crashed because the platform was overloaded.",')]),

    # ══ S — the sources of a dead agent ════════════════════════════════════

    ("S1", "under",
     "⛔⛔ AN AGENT WITH NO REPORT PERSISTS NO SOURCES AGAIN, so a leg that ran "
     "forty minutes and gathered sources records nothing but a status — and the "
     "card the owner asked to show them is empty after every reload",
     [('        if platform not in agents or "sources" not in agents.get(platform, {}):',
       "        if False:")]),

    ("S2", "over",
     "⛔⛔ THE FALLBACK OVERWRITES A REAL REPORT'S CITATIONS. An agent WITH a "
     "report already has the better list — what it actually CITED, not what the "
     "panel happened to show — and this replaces it with the panel's",
     [('        if platform not in agents or "sources" not in agents.get(platform, {}):',
       "        if True:")]),

    ("S3", "over",
     "⛔⛔ `setdefault` BECOMES AN ASSIGNMENT, which is the same overwrite one "
     "layer down: the presence check passes for an agent whose entry exists "
     "without a `sources` key, and the assignment then clobbers everything else "
     "the rebuild put there",
     [('                _entry.setdefault("sourceUrls", _fallback_urls)',
       '                _entry["sourceUrls"] = _fallback_urls')]),

    ("S4", "over",
     "⛔ A ROW OF ZEROES IS WRITTEN FOR AN AGENT THAT NEVER RAN, inventing an "
     "entry for a config-disabled platform — the exact thing the status re-stamp "
     "above it is careful not to do",
     [("            if _fallback_urls or _fallback_searches or _fallback_observed:",
       "            if True:")]),

    ("S5", "under",
     "⛔ THE EXPLICIT ZERO CHARACTER COUNT GOES. A missing `outputChars` and a "
     "zero one read the same to the frontend, but only the explicit zero says we "
     "LOOKED — and it is what stops these sources being mistaken for a report",
     [('                _entry.setdefault("outputChars", 0)\n', "")]),

    ("S6", "over",
     "⛔ THE SOURCE FALLBACK RUNS BEFORE THE STATUS RE-STAMP, so it decides which "
     "agents are 'missing' from a map the re-stamp has not filled in yet",
     [('        _astat = (_agent_status_by_rid.get(_fb_research_id, {}) or {}).get(platform) \\\n'
       "            or _prior_agent_status.get(platform)\n"
       "        if _astat:\n"
       '            agents.setdefault(platform, {})["status"] = _astat\n',
       "")]),

    ("S7", "under",
     "⛔ THE URL LIST LOSES ITS CAP, so a pathological run puts an unbounded array "
     "on a Firestore document that already carries three agents' worth",
     [('            _fallback_urls = list(_fallback_snap.get("source_urls", []) or [])[:_SOURCE_LIST_CAP]',
       '            _fallback_urls = list(_fallback_snap.get("source_urls", []) or [])')]),

    # ══ E — the failure emit ═══════════════════════════════════════════════

    ("E1", "under",
     "⛔⛔ THE FAILURE EMIT GOES BACK TO CARRYING NO SOURCES, so a dead agent's "
     "card is empty even DURING the run — before the reload that also loses them",
     [("                       sourceUrls=_fail_urls,\n", "")]),

    ("E2", "over",
     "⛔ THE SOURCE COUNT STOPS TAKING THE LARGER OF THE TWO. The counter and the "
     "url list are gathered by different readers and either can be the fuller one "
     "— the completion emit beside it already does it this way",
     [('                       sources=max(int(_fail_snap.get("sources", 0) or 0), len(_fail_urls)),',
       '                       sources=int(_fail_snap.get("sources", 0) or 0),')]),

    ("E3", "under",
     "⛔⛔ THE SNAPSHOT READ LOSES ITS GUARD, so a missing runtime ring turns a bad "
     "agent into a bad RUN — an exception in the failure path of something that "
     "has already failed",
     [("        try:\n"
       '            _fail_snap = dict(getattr(_runtime, "agent_progress_snapshots", {}).get(agent_key, {}) or {})\n'
       "        except Exception:\n"
       "            _fail_snap = {}",
       '        _fail_snap = dict(_runtime.agent_progress_snapshots[agent_key])')]),

    ("E4", "under",
     "⛔ THE SEARCH AND OBSERVED COUNTS GO, so a dead agent's card can show urls "
     "with no numbers beside them — and the 'N sources observed' line, which is "
     "the only signal when no url could be built at all, disappears",
     [('                       searches=int(_fail_snap.get("searches", 0) or 0),\n'
       '                       observedSources=int(_fail_snap.get("observed_sources", 0) or 0),\n',
       "")]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> tuple[bool, str | None]:
    """(green, refuse). `refuse` non-None means the run cannot be scored at all —
    the caller must treat it as an ERROR, never as a kill and never as a survivor."""
    proc = sh([sys.executable, "-m", "pytest", *SUITES.split(), "-q", "--no-header"])
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    passed = re.search(r"(\d+) passed", tail)
    failed = re.search(r"(\d+) failed", tail)
    errors = re.search(r"(\d+) error", tail)
    skipped = re.search(r"(\d+) skipped", tail)
    if not passed and not failed:
        return False, f"pytest printed no counts — the run did not happen: {tail!r}"
    if skipped:
        return False, f"{skipped.group(1)} test(s) SKIPPED — a skip is the absence of a measurement"
    n = int(passed.group(1) if passed else 0) + int(failed.group(1) if failed else 0)
    if n < FLOOR:
        return False, (f"only {n} tests collected, expected at least {FLOOR}"
                       " — the run measured something other than this suite")
    green = proc.returncode == 0 and not failed and not errors
    return green, None


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    green, refuse = run_tests()
    if refuse:
        print(f"REFUSED: {refuse}")
        return 2
    if not green:
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    path = ROOT / RESEARCH
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                # ⛔⛔ UNIQUENESS, NOT PRESENCE. An anchor matching twice mutates
                # a place the mutant was never about, silently, and reports a kill.
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x (needs exactly 1): {frm[:70]!r}")
                if frm == to:
                    raise AssertionError(f"replacement equals the anchor: {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed, refuse = run_tests()
            if refuse:
                raise AssertionError(f"verdict refused — {refuse}")
            killed = not killed
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, f"STALE ANCHOR — measured nothing ({exc})"))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
