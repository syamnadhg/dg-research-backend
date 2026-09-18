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
  · THE FIRESTORE MIRROR IS PINNED **PRESENT**, ON PURPOSE. The web's P5 SUMMARY
    document reads `documents/consolidated` as its ONLY source and refuses
    without it (`summary-generate.ts:103`, `summary-doc.ts:76` — "no consolidated
    report to summarise"). On BOTH P5 legs the summary runs BEFORE the synthesis,
    so `documents/synthesis` does not exist when that input is built, and the
    web's own note calls swapping the two call sites FILED, NOT BUILT. Deleting
    the mirror today costs every run its Summary document, silently — and that
    document is minted a share link and quoted in the delivery mail. When the web
    moves, THIS is the assertion to delete on purpose.
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
"""
from __future__ import annotations

import re
from pathlib import Path

import research as R
from conftest import code_only  # type: ignore


def _pipeline() -> str:
    return code_only(R.run_pipeline)


def _module() -> str:
    return code_only(Path(R.__file__).read_text(encoding="utf-8"))


def test_the_pipeline_writes_only_the_brief_and_the_three_agent_reports_to_disk():
    """EQUALITY, not absence. The stacked file was the seventh write into
    `documents/`; the six that remain are the brief (first save, skip-branch save,
    regen save) and the per-agent report (finalize, and the two regen paths)."""
    targets = re.findall(r'\(queue_dir / "documents" / ([^)]+)\)\.write_text',
                         _pipeline())
    assert targets == ['"brief.md"', '"brief.md"', '"brief.md"',
                       "fname", "fname", "fname"], targets


def test_the_stacked_file_is_not_written_anywhere_in_the_module():
    """The write is RETIRED, not relocated. Scoped to the whole module so moving
    it into a helper — or into the resume path that never rebuilt it — fails."""
    mod = _module()
    # The QUOTED literal, because two live log strings still name the file as a
    # sink a rejected leg does NOT reach (`f"consolidated.md, or handed to
    # NotebookLM"`), and a bare `in` would be satisfied by those forever.
    assert '"consolidated.md"' not in mod
    assert '"documents" / "consolidated' not in mod
    assert ".write_text(_consolidated_md" not in mod


def test_the_merged_corpus_still_reaches_both_of_its_readers():
    """⛔ THE ONE A WRITE-ONLY DELETION WOULD HAVE BROKEN SILENTLY. The merged
    text is the input to the post-P2 summary and to the title refresh; both take
    "what the research found" from all three reports at once. Four uses, by
    equality: the build, the Firestore mirror, and one per reader."""
    src = _pipeline()
    assert len(re.findall(r"_consolidated_md", src)) == 4
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

    tree = ast.parse(textwrap.dedent(_pipeline()))
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


def test_the_firestore_mirror_survives_because_the_web_summary_reads_it():
    """⛔⛔ DELIBERATE, AND THE REASON IS IN ANOTHER REPO. `documents/consolidated`
    is the only source the web's P5 summary has, and it runs before the synthesis
    on both legs. The disk copy going while the mirror stays is the whole shape of
    this change."""
    mod = _module()
    assert '"consolidated.md"' not in mod
    assert mod.count(
        'save_document_to_firestore("consolidated", _consolidated_md, "Consolidated Report")'
    ) == 1
    # The gate the web reads as "with no agent output there is no document at
    # all" (summary-doc.ts). It is a cross-repo contract, not an implementation
    # detail, so it moves only with that file.
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
