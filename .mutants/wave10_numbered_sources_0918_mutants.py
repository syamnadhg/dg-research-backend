"""Wave 10 — the numbering funnel: every number a reader opens.

⛔⛔ WHY THIS HARNESS EXISTS AT ALL. Wave 10 added seven lanes and SIX OF THEM
ADDED NO MUTANTS: the whole anchor delta was 17 F-mutants for the Redo hook. The
largest new surface in the wave is this one — `_number_document_sources` rewrites
EVERY document a reader opens, on the Documents page, in the public share and in
the delivered Google Doc — and it was measured only by tests nothing had ever
tried to defeat. This repo's own history says that is exactly where the silent
failures live, so the funnel gets a harness before the wave ships.

⭐ WHAT THE LANE IS. A finding's URL is found in the report's own prose, an
inline `[\\[n\\]](url)` marker is inserted at the end of that citation's
SENTENCE, and a `##### Sources` list is appended carrying the same numbers. The
design invariant the module states about itself is "nothing in the list points at
a number the reader cannot find" — so most of the mutants below are ways for a
number to exist in one half and not the other.

⛔⛔ THE THREE THAT ARE THIS WAVE'S OWN REPAIRS, and the reason they are first:
  N8  — the block clamp goes and the naked sentence-tail regex is back. In a
        bulleted list whose items do not end in a full stop, the first "sentence
        tail" after ANY bullet's url is the blank line that ends the WHOLE list,
        so every number in the list migrated to its LAST bullet. The reader gets
        a confident, clickable, WRONG attribution — worse than no number — and
        agent reports are heavily bulleted.
  N9  — the table-row clamp goes. GFM DISCARDS cells beyond the header's column
        count, so a marker written after a row's trailing `|` is a number that is
        in the file, has a bibliography row, and renders NOWHERE. A comparison
        table with a Source column is the most citation-dense block in a report.
  N10 — the code-span rejection goes. Masking keeps a fence's newlines, so a
        blank line inside one reads as a paragraph break and the marker lands
        INSIDE the code block, corrupting a command a reader may copy.

⭐ THE OTHERS WORTH READING:
  N1  — the escaped-bracket grammar becomes the web's own `[[n]]`, which
        `SOURCE_TOKEN_RE` in `src/lib/doc-sources.ts` renumbers to a DIFFERENT
        source. This grammar exists to be invisible to that regex.
  N2  — the separating space goes. Glued to a bare url, GFM's autolinker eats
        `[\\[1\\]` into the href and BOTH links break — the web's own `[[n]]`
        grammar has the same defect, so this was never a cost of the escape.
  N3  — the idempotency sentinel goes and a re-save numbers an already-numbered
        document, so the second pass numbers the first pass's bibliography.
  N16 — an OVER-correction, and the one this wave had to undo: `brief.md` is
        numbered again. That file is what ChatGPT and Claude RECEIVE, so
        numbering it hands them this module's own sentinel; one echoed marker in
        a reply and the whole report comes back unnumbered, with no bibliography,
        silently. Our output must not be our input.
  N13 — the heading drops back to `##`, where the web's Super Research planner
        indexes it as a research SLICE and can hand a section writer a list of
        links as "your material".

⛔ DELIBERATELY ABSENT — recorded so the next reader does not re-add them:
  * "`save_meta` stops stripping our tail" (`content =
    _strip_numbered_sources_section(...)` → the raw read). APPLIED AND MEASURED
    2026-09-18: it is an EQUIVALENT MUTANT TODAY and shipping it would have been
    a harness bug, not a survivor. The strip guards `save_meta`'s `^#{1,3}`
    section count, and since this wave writes the heading at level FIVE that
    count cannot see our tail whether the strip runs or not; our rows are
    `n. [Title](url)`, which is neither a heading nor a bold pseudo-heading. The
    strip is belt-and-braces — the code says so in its own docstring — and the
    thing that makes it matter (`_DOC_SOURCES_HEADING_LEVEL`) IS measured, by
    N13. If the heading level ever moves back to `##`, this mutant becomes real
    and belongs here.
  * "the bibliography's ROW WORDING changes". Every guard on the row is a
    rendered-output comparison; a reworded row would be a guaranteed survivor
    that measures the guards' shape rather than the code. N1/N13 make the
    grammar and the heading WRONG, which is what the rows actually claim.
  * "`_doc_is_linkable_url` diverges from the web's host+path table" — a real
    finding (a public Gemini share page loses its number), but it is a CHANGE
    this wave did not make, so a mutant of it would measure the divergence
    rather than the wave. Filed, not built.

⭐ OWN PINS ADDED WITH THIS HARNESS: none. Every mutant below is killed by a
test that already existed when the harness was written, and each one names it.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/wave10_numbered_sources_0918_mutants.py
  .venv/bin/python .mutants/wave10_numbered_sources_0918_mutants.py --unfiltered
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The lane's two own files. `test_document_images_0913.py` is NOT here: it holds
# the brief-save anchors N16 also trips, and it costs 19 s a mutant to say what
# the placement file says in two.
SUITES = ("tests/test_numbered_sources_0918.py "
          "tests/test_numbered_sources_placement_0918.py")

MINE = (
    # tests/test_numbered_sources_0918.py
    "escaped_bracketed_number_link or nothing_the_web_would_renumber or "
    "literal_the_web_ships or bibliography_carries_nothing or "
    "exactly_the_same_numbers or every_marker_points_at_the_url or "
    "never_mentions_earns_no_number or teaching_not_citing or "
    "own_conversation_never_gets_a_number or all_unplaceable or "
    "no_findings_at_all or emitted_exactly_like_this or "
    "glued_to_the_tail_of_a_bare_url or sits_before_the_full_stop or "
    "carrying_parentheses or numbers_ascend_through_the_document or "
    "already_numbered_document_changes_nothing or reordered_findings_list or "
    # ⛔ 2026-09-19 (the E2E source-title fix) renamed the host-suffix pin, which
    # had pinned the defect, and added the title ladder's own class and the
    # incident's twelve-title report. The old name matched nothing from then on.
    "link_label_names_its_own_page or SourceTitleIsThePagesOwnName or "
    "twelve_distinct_titles or does_not_say_it_twice or "
    "brackets_in_a_title or written_out_not_left_to_the_renderer or "
    "finds_the_documents_own_citations or a_failed_extraction_costs or "
    "handed_findings_are_used or bold_titled_report_its_sections or "
    "never_reported_as_a_section or same_ones_the_unnumbered_report_gave or "
    "agents_own_sources_section_is_left_alone or byte_identical_again or "
    "numbers_on_disk_and_in_firestore or read_from_the_report or "
    "written_exactly_as_it_was or routes_through_the_numbering_funnel or "
    "destination_we_would_not_put_behind_a_number or "
    # tests/test_numbered_sources_placement_0918.py
    "every_bullets_number_names_the_source or "
    "no_bullet_is_handed_a_number or still_ascend_and_the_list_still_matches or "
    "numbered_list_item_is_a_sentence_end or paragraph_that_wraps or "
    "starts_with_a_year_is_not_a_list or list_that_opens_at_one or "
    "never_lands_past_the_rows_last_pipe or each_rows_number_opens or "
    "inside_a_fenced_block or fence_opened_on_the_citing_line or "
    "end_of_the_line_that_cites or gets_no_second_one or "
    "returned_untouched_by_the_strip or heading_the_web_planner_would_index or "
    "viewer_and_the_share_still_collapse or three_web_readers or "
    "save_meta_cannot_read_our_heading or "
    "brief_the_agents_receive_carries_no_marker"
)

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_numbered_sources_0918.py",
               "tests/test_numbered_sources_placement_0918.py")

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
#: The inline marker itself — the grammar the whole lane turns on.
MARKER = r'    return "[\\[%d\\]](%s)" % (n, _doc_markdown_url(url))'
#: The separating space in front of a marker.
LEAD = '        lead = "" if at <= 0 or md[at - 1].isspace() else " "'
#: The idempotency sentinel's gate, inside `_number_document_sources`.
SENTINEL = '    if _DOC_SOURCE_MARK_RE.search(md):'
#: The one call that both masks code and remembers WHERE the code was.
MASK = '    masked, spans = _mask_code_spans(md)'
#: Ascending order, so the numbers a reader meets count up.
SORT = '    placements.sort(key=lambda p: (p[0], p[1]))'
#: The step back over a sentence's own closing stop.
STEP_BACK = '    if at - 1 >= url_end and md[at - 1] in ".!?":\n        at -= 1'
#: The platform refusal — an agent's own conversation is never numbered.
PLATFORM = '    return not _find_is_platform_host(t)'
#: THE BLOCK CLAMP. The wave-10 repair: a bullet ends a sentence.
BLOCK_CLAMP = ('        limit = _doc_block_end(\n'
               '            masked, url_end, in_list=bool(_DOC_LIST_ITEM_RE.match(line)))')
#: THE TABLE CLAMP. A marker may not go past the row's own cell.
TABLE_CLAMP = '    if _DOC_TABLE_ROW_RE.match(line):'
#: THE CODE-SPAN REJECTION. A position inside a masked span is pulled out of it.
SPAN_REJECT = ('    for start, end in spans:\n'
               '        if start < at < end:\n'
               '            at = start')
#: The ordered-item clamp's own trap: `2025. Prices fell…` is not a list item.
ORDERED = '        if ordered and (in_list or ordered.group("n") == "1"):'
#: The alternate title, for a report that already ends with its own sources.
ALT_TITLE = ('    heading = _doc_sources_heading(\n'
             '        _DOC_SOURCES_ALT_TITLE if _doc_ends_with_its_own_sources(masked)\n'
             '        else _DOC_SOURCES_TITLE)')
#: The heading level — read by three web surfaces, see `_doc_sources_heading`.
LEVEL = '_DOC_SOURCES_HEADING_LEVEL = 5'
#: The strip's gate: it only ever removes a tail carrying OUR markers.
STRIP_GATE = ('    if not md or not _DOC_SOURCE_MARK_RE.search(md):\n'
              '        return md or ""')
#: The brief the agents RECEIVE, written unnumbered on purpose.
BRIEF_WRITE = ('                brief_path.write_text(f"# Research Brief\\n\\n{brief_text}",\n'
               '                                      encoding="utf-8")')
#: Handed findings are used as handed; nothing is re-extracted over them.
HANDED = '        rows = findings if findings else _extract_findings(md, list(source_urls or []))'

MUTANTS = [
    # ═════════ the wave-10 placement repairs ═════════════════════════════════
    ("N8", "under",
     "⛔⛔ THE BLOCK CLAMP GOES AND EVERY NUMBER IN A LIST MIGRATES TO ITS LAST "
     "BULLET. `_FIND_SENT_TAIL_RE` knows `[.!?]\\s`, a blank line and a heading, "
     "and nothing about line or block structure — so in a bulleted list whose "
     "items do not end in a full stop the first tail after ANY bullet's url is "
     "the blank line that ends the WHOLE list. Two of three numbers then sit on "
     "a claim their source does not support, clickable and confident, and "
     "nothing logs it. "
     "KILLED BY tests/test_numbered_sources_placement_0918.py::"
     "TestEachBulletKeepsItsOwnNumber::"
     "test_every_bullets_number_names_the_source_that_bullet_cites",
     [(BLOCK_CLAMP, '        limit = len(masked)')]),
    ("N9", "under",
     "⛔⛔ THE TABLE CLAMP GOES AND THE NUMBER RENDERS NOWHERE. The marker lands "
     "after the row's trailing `|`, and GFM DISCARDS cells beyond the header's "
     "column count — so the document carries a bibliography row for a number the "
     "reader cannot find, which is the one invariant this module states about "
     "itself. A comparison table with a Source column is a staple of deep "
     "research output. "
     "KILLED BY tests/test_numbered_sources_placement_0918.py::"
     "TestATableCellsNumberIsVisible::test_a_marker_never_lands_past_the_rows_last_pipe",
     [(TABLE_CLAMP, '    if False:')]),
    ("N10", "under",
     "⛔⛔ THE MARKER GOES INSIDE THE CODE BLOCK. Masking blanks a fence to "
     "spaces but KEEPS its newlines, so a blank line inside one still reads as a "
     "paragraph break and the position taken from masked text lands in code the "
     "mask exists to keep out. It renders as literal text and corrupts a command "
     "a reader may copy — in a document frozen into a share and inserted into "
     "the delivered Google Doc. "
     "KILLED BY tests/test_numbered_sources_placement_0918.py::"
     "test_a_fence_opened_on_the_citing_line_keeps_the_marker_outside_it",
     [(SPAN_REJECT,
       '    for start, end in ():\n'
       '        if start < at < end:\n'
       '            at = start')]),
    ("N11", "over",
     "⛔ THE CLAMP'S OWN TRAP, AS AN OVER-CORRECTION. Every ordered item ends "
     "the line above it, `in_list` or not — so a WRAPPED SENTENCE whose second "
     "line begins `2025. Prices fell…` is cut at the wrap and the number lands "
     "mid-sentence, which the unclamped code never did. CommonMark settles it: "
     "only `1.`/`1)` may interrupt a paragraph. "
     "KILLED BY tests/test_numbered_sources_placement_0918.py::"
     "test_a_wrapped_line_that_starts_with_a_year_is_not_a_list",
     [(ORDERED, '        if ordered:')]),

    # ═════════ the grammar, and the two halves staying in step ═══════════════
    ("N1", "under",
     "⛔⛔ THE WEB'S OWN TOKEN GRAMMAR IS BACK. `[[n]]` is exactly what "
     "`SOURCE_TOKEN_RE` in src/lib/doc-sources.ts hunts for, so a machine marker "
     "copied into a synthesis document is RENUMBERED to whatever source the web "
     "holds at that index — a number that opens the wrong page. The escaped form "
     "renders identically and is invisible to that regex. "
     "KILLED BY tests/test_numbered_sources_0918.py::TestTheGrammarIsNotTheWebsToken::"
     "test_the_inline_marker_is_an_escaped_bracketed_number_link",
     [(MARKER, r'    return "[[%d]](%s)" % (n, _doc_markdown_url(url))')]),
    ("N2", "under",
     "⛔⛔ THE SEPARATING SPACE GOES AND BOTH LINKS BREAK. Glued to a bare url, "
     "GFM's autolinker swallows `[\\[1\\]` into the href: the citation becomes "
     "`…/packs%5B%5C%5B1%5C` and the marker's own link is destroyed. Measured on "
     "the web's own micromark + gfm stack. "
     "KILLED BY tests/test_numbered_sources_0918.py::TestTheMarkerSurvivesTheRenderer::"
     "test_no_marker_is_ever_glued_to_the_tail_of_a_bare_url",
     [(LEAD, '        lead = ""')]),
    ("N3", "under",
     "⛔⛔ THE IDEMPOTENCY SENTINEL GOES. A re-save numbers an already-numbered "
     "document, so the second pass numbers the FIRST pass's bibliography and the "
     "reader gets two lists and two sets of numbers over the same sources. Every "
     "agent report is re-saved at least once (finalize, regen). "
     "KILLED BY tests/test_numbered_sources_0918.py::TestOrderAndIdempotency::"
     "test_numbering_an_already_numbered_document_changes_nothing",
     [(SENTINEL, '    if False:')]),
    ("N4", "under",
     "⛔ A URL A REPORT SHOWS YOU INSIDE A FENCE IS TEACHING, NOT CITING, and "
     "without the mask it earns a number and a bibliography row — and the marker "
     "is inserted into the code. The same rule `_sweep_source_urls` already "
     "applies, through the same helper. "
     "KILLED BY tests/test_numbered_sources_0918.py::TestEveryNumberOpensASource::"
     "test_a_url_shown_inside_a_code_fence_is_teaching_not_citing",
     [(MASK, '    masked, spans = md, []')]),
    ("N5", "under",
     "⛔ THE NUMBERS COUNT DOWN THROUGH THE DOCUMENT. Numbering and placement "
     "are one decision — `i + 1` indexes the same `placements` list for the "
     "marker and the row — so reversing the sort does not break the pairing, it "
     "just means the reader meets [3] before [1]. A bibliography whose order "
     "contradicts the prose is the thing the ascending sort is for. "
     "KILLED BY tests/test_numbered_sources_0918.py::TestOrderAndIdempotency::"
     "test_numbers_ascend_through_the_document_whatever_order_they_arrive_in",
     [(SORT, '    placements.sort(key=lambda p: (-p[0], -p[1]))')]),
    ("N6", "under",
     "⛔ THE NUMBER IS ORPHANED AFTER THE FULL STOP. `Prices fell by a fifth. "
     "[1]` instead of `Prices fell by a fifth [1].` — every other number in the "
     "document sits before the punctuation, and a document is compared "
     "byte-for-byte by the renderer test. "
     "KILLED BY tests/test_numbered_sources_0918.py::TestTheMarkerSurvivesTheRenderer::"
     "test_a_number_that_ends_the_document_sits_before_the_full_stop",
     [(STEP_BACK, '    if False:\n        at -= 1')]),
    ("N7", "under",
     "⛔⛔ AN AGENT'S OWN CONVERSATION EARNS A NUMBER. A report can cite the "
     "chat it was written in, and these documents are FROZEN INTO PUBLIC SHARES "
     "and inserted into a delivered Google Doc — a private conversation link "
     "with a bibliography row beside it. "
     "KILLED BY tests/test_numbered_sources_0918.py::TestEveryNumberOpensASource::"
     "test_an_agents_own_conversation_never_gets_a_number",
     [(PLATFORM, '    return True')]),
    ("N12", "under",
     "⛔ A SECOND `Sources` HEADING, BACK TO BACK WITH THE REPORT'S OWN. Deep "
     "research reports commonly end with a sources list; appending an identical "
     "heading under it shows the reader two, in the document, in the share and "
     "in the Google Doc. The alternate title still begins with the word, so the "
     "web's `/^sources\\b/i` collapse still fires. "
     "KILLED BY tests/test_numbered_sources_placement_0918.py::"
     "TestOneSourcesHeadingPerDocument::"
     "test_a_report_that_ends_with_its_own_sources_gets_no_second_one",
     [(ALT_TITLE, '    heading = _doc_sources_heading(_DOC_SOURCES_TITLE)')]),
    ("N13", "under",
     "⛔⛔ THE HEADING DROPS BACK TO `##`, WHERE THE WEB READS IT AS RESEARCH. "
     "The Super Research planner indexes each agent report by `/^(#{1,4})\\s+/` "
     "and offers every match to a section writer as \"your material\" — at `##` "
     "our bibliography became a phantom research slice, up to three per run, and "
     "a section could be written from a list of links. Level five is the only "
     "form the viewer still folds and the planner cannot see. "
     "KILLED BY tests/test_numbered_sources_placement_0918.py::"
     "TestOurHeadingIsNotAResearchSlice::"
     "test_numbering_adds_no_heading_the_web_planner_would_index",
     [(LEVEL, '_DOC_SOURCES_HEADING_LEVEL = 2')]),
    ("N14", "over",
     "⛔ THE STRIP STOPS BEING GATED ON OUR OWN MARKERS, so it runs on any "
     "document — and the first time it meets a report whose tail has already "
     "come off it eats the AGENT'S own sources list instead. A strip that "
     "removes somebody else's content is worse than a strip that never runs. "
     "KILLED BY tests/test_numbered_sources_0918.py::"
     "TestTheStripOnlyEverRemovesOurOwnTail::"
     "test_an_agents_own_sources_section_is_left_alone",
     [(STRIP_GATE, '    if not md:\n        return md or ""')]),
    ("N17", "under",
     "⛔ HANDED FINDINGS ARE THROWN AWAY AND THE DOCUMENT IS RE-EXTRACTED. The "
     "callers extract from the CLEAN report before numbering it, deliberately; "
     "re-extracting inside the funnel is how the appended bibliography's own "
     "links become \"findings\" and the Findings tab fills with bibliography "
     "lines. "
     "KILLED BY tests/test_numbered_sources_0918.py::TestTheWriteSiteHelper::"
     "test_handed_findings_are_used_and_nothing_is_re_extracted",
     [(HANDED, '        rows = _extract_findings(md, list(source_urls or []))')]),
    ("N16", "over",
     "⛔⛔ THE OVER-CORRECTION THIS WAVE HAD TO UNDO: `brief.md` IS NUMBERED "
     "AGAIN. That file is what ChatGPT and Claude RECEIVE — attached when "
     "`use_file_attach`, pasted off disk on a hard retry — so numbering it hands "
     "them this module's own idempotency sentinel. One echoed `[\\[n\\]](url)` "
     "in a reply and `_number_document_sources` returns that agent's whole report "
     "UNNUMBERED, with no bibliography, on the Documents page, in the share and "
     "in the Google Doc, with nothing raised. Our output must not be our input. "
     "KILLED BY tests/test_numbered_sources_placement_0918.py::"
     "test_the_brief_the_agents_receive_carries_no_marker_they_could_echo",
     [(BRIEF_WRITE,
       '                brief_path.write_text(_document_with_sources(\n'
       '                    f"# Research Brief\\n\\n{brief_text}"),\n'
       '                                      encoding="utf-8")')]),
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
            # ⛔⛔ A FLAP IS ITS OWN OUTCOME, NOT A SURVIVOR.
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
