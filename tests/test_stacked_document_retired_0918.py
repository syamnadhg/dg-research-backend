"""Wave 10, 2026-09-18 — the machine stops writing the STACKED document.

⛔⛔ WHAT IT WAS. Eleven lines inside the Phase-2 persistence block: one H1, then
each agent's report verbatim, written to `documents/consolidated.md` AND mirrored
to Firestore under the `consolidated` doc type. No model call, no token budget, no
size cap. The web now SYNTHESISES the real combined document at P5 —
`superresearch-generate.ts` → `documents/synthesis`, planner → sections → stitch —
and it reads THE THREE PER-AGENT REPORTS, never the stack. So the concatenation
has no reader of its own left, and the disk copy is retired here.

⭐⭐ WHAT THIS FILE PINS, and what it deliberately does NOT.
  · THE DISK COPY IS GONE FROM THE WHOLE MODULE, not merely from one line. The
    set of things `run_pipeline` writes into `documents/` is pinned by EQUALITY,
    so re-introducing the file under any other name, or behind a helper, fails
    here. A `not in` on one spelling would not have.
  · THE MERGED TEXT STILL REACHES BOTH OF ITS IN-MEMORY READERS — the post-P2
    summary refresh and the title refresh, which both need all three reports at
    once. Deleting the BUILD along with the write would have left those two
    summarising nothing, and every assertion about the write alone would still
    have passed. That is the failure this file exists to make impossible.
  · THE FIRESTORE MIRROR IS PINNED **ABSENT** — 2026-09-22, WAVE 10.9, AND IT IS
    THE ASSERTION THIS FILE SAID TO DELETE ON PURPOSE. Until 09-21 the mirror was
    pinned PRESENT here, because the web's P5 Summary read `documents/consolidated`
    as its ONLY source and refused without it, so deleting the mirror cost every
    run its Summary, silently. The web moved: the Summary is built from the Super
    Research document and only from it (owner's decision D-3 — `summary-generate.ts`
    reads `documents/synthesis`, plus the three agent reports for the contributor
    roster alone), the cloud route is the only runner of phases 4 and 5, and
    `/api/summary` and `/api/superresearch` no longer exist. So the machine stops
    writing the stack anywhere, and the pin is inverted rather than dropped.
  · THE DERIVED-STEM EXCLUSIONS STAY. Runs made before today still carry
    `consolidated.md` on disk, so a resume of one must still keep it out of the
    NotebookLM upload, out of the P1 attach list and out of the agent hydration.
    Those three exclusions are EXECUTED elsewhere (`test_brief_and_second_opinion
    _0902.py::test_the_fallback_scan_still_refuses_derived_documents` drives the
    handoff with a real `consolidated.md` on disk); here they are only pinned
    against being swept away as newly-dead code.

⛔ `run_pipeline` cannot be executed here — 4,000 lines, a browser and a queue —
so these are SOURCE pins on `code_only` text, the same mechanism and the same
reason as `test_document_images_0913.py`'s save-site pins. `code_only` blanks
every `#` comment first, so nothing in the prose above the code can satisfy an
assertion below it.

⭐⭐ AND AS OF WAVE 10.9 THEY ARE NO LONGER THE ONLY PINS. The writes moved into
`_p2_persist_reports`, which is a module-level function a test CAN run, so the
claim these pins could only read — a completed run saves the three agent reports
and no combined document, while the summary and the title refresh still get the
merged text — is EXECUTED against a fake Firestore in
`tests/test_consolidated_write_retired_109.py`. These stay as the cheap guard
that the write was retired rather than relocated; that file is the measurement.
"""
from __future__ import annotations

import re
from pathlib import Path

import research as R
from conftest import code_only  # type: ignore


def _pipeline() -> str:
    return code_only(R.run_pipeline)


def _persist() -> str:
    """The Phase-2 persistence helper — the finalize re-save and the merged
    corpus, which wave 10.9 moved out of `run_pipeline` so a test could run
    them."""
    return code_only(R._p2_persist_reports)


def _writers() -> str:
    """Both halves as one text. ⛔ Every count over `documents/` is over the
    PAIR: the move put the finalize write on the other side of a call, and a
    count that saw one half would be satisfied by emptying the other."""
    return _pipeline() + "\n" + _persist()


def _module() -> str:
    return code_only(Path(R.__file__).read_text(encoding="utf-8"))


def test_the_pipeline_writes_only_the_brief_and_the_three_agent_reports_to_disk():
    """EQUALITY, not absence. The stacked file was the seventh write into
    `documents/`; the six that remain are the brief (first save, skip-branch save,
    regen save) and the per-agent report (finalize, and the two regen paths).

    ⭐ Wave 10.9 — the finalize write is in `_p2_persist_reports` now, so it is
    the LAST of the six here rather than the fourth: `run_pipeline` contributes
    the three briefs and the two regen paths, the helper the finalize."""
    targets = re.findall(r'\(queue_dir / "documents" / ([^)]+)\)\.write_text',
                         _writers())
    assert targets == ['"brief.md"', '"brief.md"', '"brief.md"',
                       "fname", "fname", "fname"], targets


def test_the_stacked_file_is_not_written_anywhere_in_the_module():
    """The write is RETIRED, not relocated. Scoped to the whole module so moving
    it into a helper — or into the resume path that never rebuilt it — fails."""
    mod = _module()
    # The QUOTED literal. It used to be the only spelling that worked, because
    # two live off-topic-sweep log lines named the file as a sink a rejected leg
    # does NOT reach; wave 10.9 re-pointed both at the merged corpus, since
    # nothing has merged into a FILE since 09-18. The quoted form stays anyway —
    # it is what a re-added write would be spelled as, and it cannot be paid for
    # by prose that happens to mention the name.
    assert '"consolidated.md"' not in mod
    assert '"documents" / "consolidated' not in mod
    assert ".write_text(_consolidated_md" not in mod


def test_the_merged_corpus_still_reaches_both_of_its_readers():
    """⛔ THE ONE A WRITE-ONLY DELETION WOULD HAVE BROKEN SILENTLY. The merged
    text is the input to the post-P2 summary and to the title refresh; both take
    "what the research found" from all three reports at once.

    ⭐ Wave 10.9 — THREE uses now, by equality, and the one that went is the
    Firestore mirror. The readers take the STRING, never a saved document, which
    is exactly why retiring the mirror could leave them untouched — and why the
    equality has to drop to three rather than be relaxed to a minimum: a fourth
    use would be a re-added write."""
    src = _persist()
    assert len(re.findall(r"_consolidated_md", src)) == 3
    build = src.index('_consolidated_md = "\\n".join(consolidated_parts)')
    for call in ("_generate_research_summary_async(", "_refresh_research_title_async("):
        at = src.index(call, build)
        window = src[at:at + 300]
        assert "_consolidated_md" in window, call
        assert ")" in window.split("_consolidated_md", 1)[1], call


def test_the_merged_corpus_is_really_built_from_the_three_reports():
    """⛔⛔ THE BUILD, NOT ONLY ITS WIRING — AND IT HAD NO PIN AT ALL. The test
    above proves `_consolidated_md` is HANDED to both readers; nothing proved it
    was ever filled. Emptying the append (`consolidated_parts.append(...)` →
    `pass`) left the whole stacked-document file green on 09-18: the list stays
    one long, `len(consolidated_parts) > 1` is False, and the Firestore mirror,
    the summary and the title refresh all silently stop happening — no error, no
    log line, every run losing its Summary document. Parsed from the tree rather
    than counted in text, so a comment naming the append cannot pay for it."""
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(_persist()))
    appends = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "append"
               and isinstance(n.func.value, ast.Name)
               and n.func.value.id == "consolidated_parts"]
    assert len(appends) == 1, "the merged corpus is built in exactly one place"
    arg = ast.unparse(appends[0].args[0])
    assert "r['text']" in arg or 'r["text"]' in arg, (
        "the stack must carry each agent's CLEAN extraction — `_agent_md` is the "
        "numbered copy and would put markers into the summary's input")
    # …and it is the three agents, in the order the readers expect.
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and any(appends[0] is c for c in ast.walk(n))]
    assert loops, "the append is not inside a loop over the agents"
    assert ast.literal_eval(ast.unparse(loops[0].iter)) == [
        "ChatGPT", "Gemini", "Claude"]


def test_the_firestore_mirror_is_retired_too_and_did_not_move():
    """⛔⛔ 2026-09-22, WAVE 10.9 — INVERTED ON PURPOSE, AND THE REASON IS IN
    ANOTHER REPO. This assertion pinned the mirror PRESENT while the web's P5
    Summary read `documents/consolidated` as its only source. The Summary is now
    built from the Super Research document and only from it (decision D-3), the
    cloud route is the only phase-5 runner, and `/api/summary` and
    `/api/superresearch` are gone — so the machine writes no combined document
    at all, and the pin flips rather than disappearing.

    ⛔ ABSENCE OF THE DOC TYPE, not of one call spelling: scoped to the whole
    module, on the `"consolidated"` ARGUMENT, so re-adding the write under
    `save_document_to_firestore_with_retry`, from the regen paths, or from a
    helper fails here too.

    ⭐ THE GATE STAYS, and it is the reason this is not simply a deletion. With
    no agent output there is no merged corpus, and the summary and the title
    refresh must not be dispatched on an H1 and nothing else."""
    mod = _module()
    assert '"consolidated.md"' not in mod
    assert 'save_document_to_firestore("consolidated"' not in mod
    assert '"consolidated", _consolidated_md' not in mod
    assert not re.search(r'save_document_to_firestore\w*\(\s*\n?\s*"consolidated"', mod)
    assert "Consolidated Report" not in mod
    assert mod.count("if len(consolidated_parts) > 1:") == 1


def test_the_derived_stem_exclusions_outlive_the_writer():
    """The writer went; the three exclusions must not follow it. Every run made
    before today still has `consolidated.md` on disk, and a resume of one reads
    that directory."""
    mod = _module()
    assert '"consolidated.md"' not in mod
    assert mod.count('\n    _DERIVED_STEMS = {"brief", "consolidated"}') == 1
    assert mod.count('_P3_DERIVED_STEMS = {"brief", "consolidated"}') == 1
    assert mod.count('if _f.stem in ("brief", "consolidated"):') == 1
