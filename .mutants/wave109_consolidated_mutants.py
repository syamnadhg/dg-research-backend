"""Wave 10.9, 2026-09-22 — the machine stops SAVING the combined document.

⛔⛔ WHAT CHANGED. One `save_document_to_firestore("consolidated", …)` is gone:
the three agent reports concatenated under one H1, mirrored to the `consolidated`
doc type. `documents/consolidated.md` went on 09-18; this was the last copy. The
web's P5 Summary used to read `documents/consolidated` as its ONLY source and
refuse without it — that is why the mirror outlived the disk write by four days
— and the Summary is now built from the Super Research document and only from it
(decision D-3; `summary-generate.ts` reads `documents/synthesis`, plus the three
agent reports for the contributor roster alone). The cloud route is the only
runner of phases 4 and 5, and `/api/summary` and `/api/superresearch` are gone.

⭐⭐ AND THE MEASUREMENT CHANGED WITH IT. The writes used to sit four thousand
lines inside `run_pipeline`, behind a browser and a queue, so the only pins they
could have were on their source TEXT (`wave10_stacked_document_0918_mutants.py`,
which still runs and is re-anchored). They now live in `_p2_persist_reports`, a
module-level function `tests/test_consolidated_write_retired_109.py` DRIVES with
a fake Firestore — so every mutant below is judged on what the run WROTE and on
what the two readers RECEIVED, not on what the file says.

⭐ THE TWO HALVES, and the second is the point:
  · THE WRITE COMING BACK — M1 (under its own doc type), M2 (under another one),
    M3 (through the retry wrapper), M4 (back onto disk). M2 and M3 are the ones
    worth reading: an absence pin on the string `"consolidated"` calls both of
    them clean, which is why the pin is an EQUALITY on the doc types a drive
    records.
  · THE STRING GOING WITH IT — M5 (the build is emptied), M6/M7 (the gate moves
    in either direction), M8 (a reader is dropped), M9 (the two dispatches share
    one `try`, so a failed summary costs the title refresh), M10 (an agent is
    dropped from the corpus), M11 (the brief stops reaching the readers). With no
    persisted copy left, NOTHING but the drive would notice any of these: the
    gate goes False, no exception and no log line, and every run quietly loses
    its /researches one-liner and its refreshed title.
  · AND THE CALLER — M12/M13. A helper a test drives and the pipeline does not
    ask for is a test of nothing, so the call is pinned as a statement of the
    phase-2 finalize body: M12 puts it behind a flag, M13 deletes it.

⛔ DELIBERATELY ABSENT — recorded so the next reader does not re-add them:
  * "the finalize re-save stops honouring `_p2_needs_resave`". Already measured,
    on the same line, by wave109_phase2retry_mutants.py::M11. Re-adding it here
    would be a second opinion about one decision, not a second measurement.
  * "the rehost funnel is deleted from the helper". Already measured by
    wave4_document_images_0913_mutants.py::K6, re-anchored with this change.
  * "the derived-stem exclusions go with the writer". T5/T6/T7 in
    wave10_stacked_document_0918_mutants.py, which is the harness that owns the
    source pins for them.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

⭐ THIS HARNESS DOES NOT TRUST PYTEST'S EXIT CODE ALONE. A suite that dies part
way can still exit 0, and this repo has committed on one that did. `_pytest`
requires the runner's own summary line and reports a run without one as a fault,
so a mutant can never be scored against a suite that did not finish.

  .venv/bin/python .mutants/wave109_consolidated_mutants.py
  .venv/bin/python .mutants/wave109_consolidated_mutants.py --unfiltered
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = "tests/test_consolidated_write_retired_109.py"

MINE = (
    "saves_the_three_agent_reports_and_no_combined_document or "
    "both_readers_still_receive_the_merged_text or "
    "merged_text_carries_the_clean_extraction or "
    "every_agent_failed_saves_nothing_and_dispatches_nothing or "
    "one_survivor_still_reaches_both_readers or "
    "kept_agents_copies_stand or "
    "failed_summary_dispatch_does_not_cost_the_title_refresh or "
    "brief_reaches_both_readers or "
    "hands_the_phase_to_the_helper_unconditionally or "
    "the_faked_names_are_the_real_ones"
)

OWNED_FILES = ("tests/test_consolidated_write_retired_109.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")
_SUMMARY = re.compile(r"\b\d+ (passed|failed|error|errors|skipped|deselected)\b")

# ── anchors ─────────────────────────────────────────────────────────────
#: The gate and the build, together — the two lines a re-added write sits under.
GATE_AND_BUILD = ('    if len(consolidated_parts) > 1:\n'
                  '        _consolidated_md = "\\n".join(consolidated_parts)')
#: The gate alone, for the two mutants that move it.
GATE = '    if len(consolidated_parts) > 1:'
#: The one line that actually FILLS the merged corpus.
APPEND = ('            consolidated_parts.append(f"\\n## {name} Research'
          '\\n\\n{r[\'text\']}")')
#: The roster the corpus is built from, in the order its readers expect. Carries
#: the build's first line, because the same roster is written once more inside
#: `run_pipeline` (the links pass) at a deeper indent, and a bare `for name in
#: […]:` is a SUBSTRING of that one.
ROSTER = ('    consolidated_parts = [f"# Consolidated Research Report: {topic}\\n"]\n'
          '    for name in ["ChatGPT", "Gemini", "Claude"]:')
#: The first reader: the one-line `summary` FIELD on /researches.
SUMMARY_CALL = ('        try:\n'
                '            _generate_research_summary_async(\n'
                '                topic,\n'
                '                brief_text,\n'
                '                _consolidated_md,\n'
                '            )\n'
                '        except Exception as _sum_e:\n'
                '            log(f"[summary] post-P2 dispatch failed: {_sum_e}", "WARN")')
#: The second reader: the post-P2 title refresh.
TITLE_CALL = ('        try:\n'
              '            _refresh_research_title_async(\n'
              '                topic,\n'
              '                brief_text,\n'
              '                _consolidated_md,\n'
              '            )\n'
              '        except Exception as _tit_e:\n'
              '            log(f"[title-refresh] post-P2 dispatch failed: {_tit_e}", "WARN")')
#: The brief, on its way to the first reader.
SUMMARY_BRIEF = ('            _generate_research_summary_async(\n'
                 '                topic,\n'
                 '                brief_text,')
#: The caller — `run_pipeline`'s phase-2 finalize body.
HELPER_CALL = ('            await _p2_persist_reports(\n'
               '                results, queue_dir, topic,\n'
               '                brief_artifact.text if brief_artifact else "")')

MUTANTS = [
    ("M1", "under",
     "⛔⛔ THE FIRESTORE MIRROR COMES BACK, under its own doc type and inside the "
     "gate it always sat in. Nothing reads it: the web's Summary is built from "
     "the Super Research document, `visibleDocuments` hides the stack wherever a "
     "synthesis exists, and the concatenation is not an input to anything. ~250 "
     "KB a run, and a document that disagrees with its own inputs after any "
     "resume — the stack is built HERE and nowhere else, while both re-save "
     "paths re-write the per-agent reports without rebuilding it. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_a_completed_run_saves_the_three_agent_reports_and_no_combined_document",
     [(GATE_AND_BUILD,
       GATE_AND_BUILD + '\n'
       '        save_document_to_firestore("consolidated", _consolidated_md,\n'
       '                                   "Consolidated Report")')]),
    ("M2", "under",
     "⛔⛔ THE WRITE COMES BACK UNDER ANOTHER DOC TYPE, and this is why the pin "
     "is an EQUALITY on the doc types a drive records rather than an absence of "
     "the word \"consolidated\". Every source pin in the suite — and the previous "
     "harness's — is satisfied by this: the string never appears, and the run "
     "saves a fourth document anyway, which the Documents page shows as an "
     "unknown kind it cannot hide. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_a_completed_run_saves_the_three_agent_reports_and_no_combined_document",
     [(GATE_AND_BUILD,
       GATE_AND_BUILD + '\n'
       '        save_document_to_firestore("combined", _consolidated_md,\n'
       '                                   "Combined Report")')]),
    ("M3", "under",
     "⛔⛔ THE WRITE COMES BACK THROUGH THE RETRY WRAPPER — the same defect one "
     "call deeper, and the shape a well-meaning repair takes (\"the old write was "
     "unguarded, so add the retry\"). A pin that named `save_document_to_"
     "firestore(` would miss it. The drive catches it because the wrapper funnels "
     "into the same call, so what the RUN wrote is what is asserted. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_a_completed_run_saves_the_three_agent_reports_and_no_combined_document",
     [(GATE_AND_BUILD,
       GATE_AND_BUILD + '\n'
       '        await save_document_to_firestore_with_retry(\n'
       '            "consolidated", _consolidated_md, "Consolidated Report")')]),
    ("M4", "under",
     "⛔ THE DISK COPY COMES BACK TOO. Retired on 09-18 and pinned absent in "
     "source since; this is the executed half of that claim — the file appears "
     "in the run's `documents/`, where the P3 NotebookLM scan, the Flow-B "
     "fallback scan and the P1 attach scan each have to exclude it by name. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_a_completed_run_saves_the_three_agent_reports_and_no_combined_document",
     [(GATE_AND_BUILD,
       GATE_AND_BUILD + '\n'
       '        (queue_dir / "documents" / "consolidated.md").write_text(\n'
       '            _consolidated_md, encoding="utf-8")')]),
    ("M5", "under",
     "⛔⛔ THE MERGED CORPUS IS NEVER FILLED, AND EVERY WIRE STAYS ATTACHED. The "
     "list stays one long, so the gate is False and neither reader is called — "
     "no exception, no log line, every run losing its /researches one-liner and "
     "its refreshed title. With the mirror retired there is no saved copy left "
     "whose absence would hint at it, so this drive is the only thing that "
     "notices. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_both_readers_still_receive_the_merged_text_they_receive_today",
     [(APPEND, '            pass')]),
    ("M6", "over",
     "⛔ THE GATE LOOSENS TO `>= 1`, so a phase where every agent failed hands an "
     "H1 and nothing else to two model calls, and the /researches tile animates "
     "the result as what the research found. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_a_run_where_every_agent_failed_saves_nothing_and_dispatches_nothing",
     [(GATE, '    if len(consolidated_parts) >= 1:')]),
    ("M7", "over",
     "⛔ THE GATE TIGHTENS TO `> 2`, the other direction and the one an absence "
     "pin cannot see at all: a run where two of the three agents failed still "
     "produced research, and it silently stops refreshing its summary and its "
     "title. Pins the threshold from BELOW — without this, `> 1` could drift "
     "upward and every assertion about the three-agent case would still pass. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_one_survivor_still_reaches_both_readers",
     [(GATE, '    if len(consolidated_parts) > 2:')]),
    ("M8", "under",
     "⛔ THE TITLE REFRESH IS DROPPED — the quiet half of the pair. The run keeps "
     "the startup title built from the user's raw input, which is the paragraph "
     "with \"Goal:\" sections the refresh exists to replace, and nothing in the "
     "run reports anything wrong. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_both_readers_still_receive_the_merged_text_they_receive_today",
     [(TITLE_CALL, '        pass')]),
    ("M9", "under",
     "⛔⛔ THE TWO DISPATCHES SHARE ONE `try`, so a summary dispatch that raises "
     "costs the title refresh as well — two independent daemon kicks collapsed "
     "into one failure domain by a tidy-up that looks like a de-duplication. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_a_failed_summary_dispatch_does_not_cost_the_title_refresh",
     [(SUMMARY_CALL,
       '        try:\n'
       '            _generate_research_summary_async(\n'
       '                topic,\n'
       '                brief_text,\n'
       '                _consolidated_md,\n'
       '            )\n'
       '            _refresh_research_title_async(\n'
       '                topic,\n'
       '                brief_text,\n'
       '                _consolidated_md,\n'
       '            )\n'
       '        except Exception as _sum_e:\n'
       '            log(f"[summary] post-P2 dispatch failed: {_sum_e}", "WARN")'),
      (TITLE_CALL, '        pass')]),
    ("M10", "under",
     "⛔ AN AGENT IS DROPPED FROM THE CORPUS. Claude's report is still written, "
     "still mirrored and still in the person's documents — and the one-line "
     "summary and the title are built as though it had never run. The readers "
     "take \"what the research found\" from all three at once; this is the failure "
     "that leaves no trace anywhere else. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_both_readers_still_receive_the_merged_text_they_receive_today",
     [(ROSTER,
       '    consolidated_parts = [f"# Consolidated Research Report: {topic}\\n"]\n'
       '    for name in ["ChatGPT", "Gemini"]:')]),
    ("M11", "under",
     "⛔ THE BRIEF STOPS REACHING THE SUMMARY. `_generate_research_summary_async` "
     "takes the brief alongside the findings, so the one-liner is written with no "
     "idea what was asked — a paragraph about the reports rather than an answer "
     "to the question. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_both_readers_still_receive_the_merged_text_they_receive_today",
     [(SUMMARY_BRIEF,
       '            _generate_research_summary_async(\n'
       '                topic,\n'
       '                "",')]),
    ("M12", "under",
     "⛔⛔ THE CALLER PUTS THE WRITES BEHIND A FLAG. `_p2_clean_finish` is already "
     "in scope twenty lines above — it gates the phase-2 completion marker — so "
     "this is one plausible line, and it means a run stopped or paused after its "
     "agents finished persists NOTHING: the reports are extracted, the person "
     "sees P2 turn green, and the documents never arrive. The helper's own drive "
     "stays green throughout, which is exactly why the caller is pinned too. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_run_pipeline_hands_the_phase_to_the_helper_unconditionally",
     [(HELPER_CALL,
       '            if _p2_clean_finish:\n'
       '                await _p2_persist_reports(\n'
       '                    results, queue_dir, topic,\n'
       '                    brief_artifact.text if brief_artifact else "")')]),
    ("M13", "under",
     "⛔⛔ THE CALL IS DELETED OUTRIGHT — the decision is extracted, tested and "
     "asked for by nobody. Every assertion in this file's drive still passes, "
     "because the drive calls the helper itself; the run writes no documents at "
     "all. This is the mutant that says an extraction's pins are worth nothing "
     "without a pin on its consumer. "
     "KILLED BY tests/test_consolidated_write_retired_109.py::"
     "test_run_pipeline_hands_the_phase_to_the_helper_unconditionally",
     [(HELPER_CALL, '            pass')]),
]


def _mark(mid: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{TARGET}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _stranded() -> "str | None":
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


def _pytest(kfilter: "str | None") -> str:
    """'green' | 'red' | 'nothing-collected' | 'no-summary'.

    ⛔⛔ THE SUMMARY LINE, NEVER THE EXIT CODE ALONE. A suite that dies part way
    can still exit 0, and a mutant scored against a run that never finished is a
    verdict about nothing."""
    purge_pycache(ROOT)
    args = [sys.executable, "-B", "-m", "pytest", *SUITES.split(),
            "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    done = sh(args, cwd=ROOT, env=ENV)
    if done.returncode == 5:
        return "nothing-collected"
    if not _SUMMARY.search(done.stdout + done.stderr):
        return "no-summary"
    return "green" if done.returncode == 0 else "red"


def run_tests(kfilter: "str | None") -> bool:
    got = _pytest(kfilter)
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check the filter")
    if got == "no-summary":
        raise AssertionError(
            "the runner printed no summary line — the suite did not finish, so "
            "this mutant was measured against nothing")
    return got == "green"


def _collected(files, kfilter: "str | None") -> set:
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
          else "scope: THIS WAVE'S OWN GUARDS (-k) — pass --unfiltered for the other number")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- {TARGET}), then delete\n    {_INFLIGHT}")
        return 2

    if kfilter:
        missed = _filter_misses(kfilter)
        total = len(_collected(OWNED_FILES, None))
        print(f"filter covers {total - len(missed)}/{total} of this wave's own tests")
        if missed:
            print("⛔⛔ THE FILTER CANNOT SEE SOME OF THIS WAVE'S OWN GUARDS, so "
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
