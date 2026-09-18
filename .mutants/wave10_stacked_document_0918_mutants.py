"""Wave 10 — the stacked document's retirement, and the two things it kept.

⛔⛔ WHAT WAS RETIRED. Eleven lines in the Phase-2 persistence block wrote
`documents/consolidated.md`: an H1 and each agent's report verbatim, with no
model call and no cap. The web now SYNTHESISES the real combined document at P5
from the three PER-AGENT reports, so the concatenation has no reader of its own
left, and the disk copy goes.

⛔⛔ WHAT IT KEPT, AND WHY A WRITE-ONLY DELETION WOULD HAVE BEEN WORSE THAN NO
DELETION:
  · THE FIRESTORE MIRROR STAYS. `documents/consolidated` is the ONLY source the
    web's P5 Summary has (`summary-generate.ts:103`), and on both P5 legs the
    summary runs BEFORE the synthesis, so `documents/synthesis` does not exist
    when that input is built. Deleting the mirror costs every run its Summary
    document, silently — and that document is minted a share link and quoted in
    the delivery mail.
  · THE MERGED TEXT STAYS. It is the in-memory input to the post-P2 summary AND
    to the title refresh, which both need all three reports at once.
  · THE DERIVED-STEM EXCLUSIONS STAY. Every run made before today still carries
    `consolidated.md` on disk, and a resume of one reads that directory — so it
    must still be kept out of the NotebookLM upload, the P1 attach list and the
    agent hydration.

⭐ SO THE MUTANTS ARE IN TWO HALVES: the write coming BACK (T1/T2), and the
three things that must NOT have gone with it (T3-T8). The second half is the
point. A deletion that takes a load-bearing neighbour with it is this repo's
recorded shape for a silent outage, and every assertion about the WRITE alone
would still have passed.

⭐ THE ONES WORTH READING:
  T2  — the file comes back under ANOTHER NAME. The pin is an EQUALITY on what
        `run_pipeline` writes into `documents/`, not a `not in` on one spelling,
        and this is the mutant that says so.
  T3  — the Firestore mirror goes. This is the cross-repo contract; when the web
        moves its summary onto the synthesis, THIS is the assertion to delete on
        purpose, and until then it is the one that must not drift.
  T4  — the `> 1` gate loosens to `>= 1`, so a run where every agent failed
        publishes a consolidated document that is an H1 and nothing else, and
        the web summarises a title.
  T8  — THE BUILD IS EMPTIED while every wire stays attached. `_consolidated_md`
        is still handed to both readers and the list is never filled, so the
        gate is False, the mirror never happens, and the summary and the title
        refresh silently stop — no error, no log line. Nothing in the suite
        could fail on this before the pin added with this harness.

⛔ DELIBERATELY ABSENT — recorded so the next reader does not re-add them:
  * "the resume scan stops accepting a partial research". `has_partial_research`
    excludes only `brief`, and `consolidated.md` could never have been its sole
    satisfier (the per-agent write loop runs immediately before the stack build,
    and the build requires at least one agent's report). Mutating it would
    measure the resume detector, which is 08-xx code this wave did not touch.
  * "`save_meta` stops listing the documents". Same reason: the row simply
    disappeared with the file, which the wave record states; the meta scan is
    not this lane's code.
  * "the three exclusions are collapsed into one shared constant". A refactor,
    not a defect — it changes no answer, so it would be an equivalent mutant.
    T5/T6/T7 delete the stem from each one separately, which is the failure that
    actually costs an old run its upload.

⭐ OWN PINS ADDED WITH THIS HARNESS (tests/test_stacked_document_retired_0918.py):
  test_the_merged_corpus_is_really_built_from_the_three_reports → kills T8
Nothing in the suite could fail on T8: the existing test proves `_consolidated_md`
is HANDED to both readers and nothing proved it was ever filled.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/wave10_stacked_document_0918_mutants.py
  .venv/bin/python .mutants/wave10_stacked_document_0918_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = "tests/test_stacked_document_retired_0918.py"

MINE = (
    "writes_only_the_brief_and_the_three_agent_reports or "
    "stacked_file_is_not_written_anywhere or "
    "merged_corpus_still_reaches_both_of_its_readers or "
    "merged_corpus_is_really_built_from_the_three_reports or "
    "firestore_mirror_survives or derived_stem_exclusions_outlive_the_writer"
)

OWNED_FILES = ("tests/test_stacked_document_retired_0918.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
#: The gate and the build, together — the two lines a re-added write would sit
#: under, and the gate the web reads as "no agent output, no document".
GATE_AND_BUILD = ('            if len(consolidated_parts) > 1:\n'
                  '                _consolidated_md = "\\n".join(consolidated_parts)')
#: The gate alone, for the mutant that loosens it.
GATE = '            if len(consolidated_parts) > 1:'
#: The Firestore mirror — the cross-repo contract.
MIRROR = ('                save_document_to_firestore("consolidated", '
          '_consolidated_md, "Consolidated Report")')
#: The one line that actually FILLS the merged corpus.
APPEND = ('                    consolidated_parts.append(f"\\n## {name} Research'
          '\\n\\n{r[\'text\']}")')
#: The three derived-stem exclusions that outlive the writer.
STEMS_NLM = '    _DERIVED_STEMS = {"brief", "consolidated"}'
STEMS_P3 = '        _P3_DERIVED_STEMS = {"brief", "consolidated"}'
STEMS_P1 = '                    if _f.stem in ("brief", "consolidated"):'

MUTANTS = [
    ("T1", "under",
     "⛔⛔ THE DISK WRITE COMES BACK, under its own name and inside the gate it "
     "always sat in. The file has no reader left in any of the four repos — the "
     "web synthesises from the three per-agent reports — so this is dead bytes "
     "in every run's queue directory and a seventh document in a list the "
     "Documents page shows. "
     "KILLED BY tests/test_stacked_document_retired_0918.py::"
     "test_the_pipeline_writes_only_the_brief_and_the_three_agent_reports_to_disk, "
     "which pins the write targets by EQUALITY",
     [(GATE_AND_BUILD,
       GATE_AND_BUILD + '\n'
       '                (queue_dir / "documents" / "consolidated.md").write_text(\n'
       '                    _consolidated_md, encoding="utf-8")')]),
    ("T2", "under",
     "⛔⛔ THE WRITE COMES BACK UNDER ANOTHER NAME. This is why the pin is an "
     "EQUALITY on the write targets and not a `not in` on one spelling: a `not "
     "in \"consolidated.md\"` guard would have called this clean, and the file "
     "would be back with a new name and the same absent reader. "
     "KILLED BY tests/test_stacked_document_retired_0918.py::"
     "test_the_pipeline_writes_only_the_brief_and_the_three_agent_reports_to_disk",
     [(GATE_AND_BUILD,
       GATE_AND_BUILD + '\n'
       '                (queue_dir / "documents" / "stack.md").write_text(\n'
       '                    _consolidated_md, encoding="utf-8")')]),
    ("T3", "under",
     "⛔⛔ THE FIRESTORE MIRROR GOES WITH THE DISK COPY — the write-only "
     "deletion's mirror image, and the one that costs every run its SUMMARY "
     "document. `documents/consolidated` is the only source the web's P5 summary "
     "has, and it runs before the synthesis on both legs, so there is nothing "
     "for it to fall back to. Silent: the summary simply refuses, and that "
     "document is minted a share link and quoted in the delivery mail. "
     "KILLED BY tests/test_stacked_document_retired_0918.py::"
     "test_the_firestore_mirror_survives_because_the_web_summary_reads_it",
     [(MIRROR, '                pass')]),
    ("T4", "over",
     "⛔ THE GATE LOOSENS TO `>= 1`, so a phase where every agent failed still "
     "publishes a consolidated document — an H1 and nothing else — and the web "
     "summarises a title. The gate is what the web reads as \"with no agent "
     "output there is no document at all\" (summary-doc.ts); it is a cross-repo "
     "contract, not an implementation detail. "
     "KILLED BY tests/test_stacked_document_retired_0918.py::"
     "test_the_firestore_mirror_survives_because_the_web_summary_reads_it, whose "
     "last assertion is an exact count of that gate",
     [(GATE, '            if len(consolidated_parts) >= 1:')]),
    ("T8", "under",
     "⛔⛔ THE MERGED CORPUS IS NEVER FILLED, AND EVERY WIRE STAYS ATTACHED. "
     "`_consolidated_md` is still built, still mirrored, still handed to the "
     "summary and the title refresh — and the list is one long, so the gate is "
     "False and NONE of it happens. No error, no log line, every run quietly "
     "losing its Summary document and its refreshed title. This is the exact "
     "shape the file's header says a write-only deletion would have had, and "
     "nothing in the suite could fail on it. "
     "KILLED BY tests/test_stacked_document_retired_0918.py::"
     "test_the_merged_corpus_is_really_built_from_the_three_reports, ADDED WITH "
     "THIS HARNESS",
     [(APPEND, '                    pass')]),
    ("T5", "under",
     "⛔ THE NOTEBOOKLM UPLOAD STOPS EXCLUDING THE STEM. Every run made before "
     "today still has `consolidated.md` on disk, so a resume of one uploads the "
     "stack alongside the three reports it is made of — the same text three "
     "times, in the one place a size budget matters. "
     "KILLED BY tests/test_stacked_document_retired_0918.py::"
     "test_the_derived_stem_exclusions_outlive_the_writer",
     [(STEMS_NLM, '    _DERIVED_STEMS = {"brief"}')]),
    ("T6", "under",
     "⛔ THE P3 SCAN STOPS EXCLUDING IT — same defect, the other derived-stem "
     "set. The writer went; the exclusions must not follow it as newly-dead "
     "code, which is exactly how they read to someone deleting the writer. "
     "KILLED BY tests/test_stacked_document_retired_0918.py::"
     "test_the_derived_stem_exclusions_outlive_the_writer",
     [(STEMS_P3, '        _P3_DERIVED_STEMS = {"brief"}')]),
    ("T7", "under",
     "⛔ THE P1 ATTACH SCAN STOPS EXCLUDING IT, so a resumed old run hands an "
     "agent the whole stack as an attachment — every agent's report fed back to "
     "one of them as source material. "
     "KILLED BY tests/test_stacked_document_retired_0918.py::"
     "test_the_derived_stem_exclusions_outlive_the_writer",
     [(STEMS_P1, '                    if _f.stem in ("brief",):')]),
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


def run_tests(kfilter: "str | None") -> bool:
    got = _pytest(kfilter)
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check the filter")
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
