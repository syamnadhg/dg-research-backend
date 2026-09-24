"""Wave 10 REPAIR, 2026-09-18 — WHERE THE NUMBER LANDS.

The owner's ask was *"when I see a sentence I really want to see where did that
sentence come from."* `tests/test_numbered_sources_0918.py` pins the GRAMMAR of
the number. This file pins its POSITION, because a number on the wrong sentence
answers that ask WRONG rather than leaving it blank — and every defect below was
measured on the shape agent reports actually have.

⛔⛔ THE BULLETED LIST. `_FIND_SENT_TAIL_RE` knows `[.!?]\\s`, `\\n\\n` and a
heading, and nothing about line or block structure. A bullet that ends without a
full stop therefore does not end a sentence, so the first tail after ANY url in
the list is the blank line that ends the WHOLE list: every number in a list
migrated to its LAST bullet, on a claim the source does not support. Agent
reports are heavily bulleted.

⛔⛔ THE TABLE. GFM discards cells beyond the header's column count, so a marker
appended after a row's trailing `|` is a number the reader cannot see anywhere —
while its row still sits in the bibliography. That is the module's own stated
invariant ("nothing in the list points at a number the reader cannot find")
broken from the inside.

⛔⛔ THE FENCE. `_mask_code` blanks a fenced block to spaces but KEEPS its
newlines, so a blank line inside a fence reads as a paragraph break. A marker
placed there renders as literal text and corrupts a command a reader may copy.

⛔⛔ THE SECOND BIBLIOGRAPHY. Deep-research reports commonly END with a sources
list of their own, and ours was appended under a second, identical `## Sources`.

⛔⛔ THE PHANTOM SLICE. The web's Super Research planner indexes each agent report
by `/^(#{1,4})\\s+(.+?)\\s*$/gm` and offers every match to a section writer as
research material, so our own heading became up to three slices per run whose
text is a list of links. The web is shipped and read-only; the machine is the
only side that can stop producing the shape, so our heading is written at LEVEL
FIVE — below the planner's `#{1,4}` and below `save_meta`'s `#{1,3}`, and still
inside the `#{1,6}` the web's viewer and public share collapse into a
`Sources · n` disclosure.

⛔⛔ AND THE LEVEL IS WHERE THIS REPAIR NEARLY SEEDED THE NEXT DEFECT. The first
version wrote the heading SETEXT, which renders byte-identical `<h2>Sources</h2>`
and dodges the planner just as well — and would have silently stopped the
bibliography collapsing on the Documents page and in every public share, because
`markdown-components.tsx` matches ATX only. Three readers, not one, and the
cross-repo pins below hold all three literals.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402

from conftest import code_only_deep, web_file  # noqa: E402

#: Our marker, as `tests/test_numbered_sources_0918.py` spells it.
MARKER_RE = re.compile(r"\[\\\[(\d{1,3})\\\]\]\(([^)]*)\)")

#: Where the web keeps the three readers below, inside whichever web checkout
#: conftest's one finder answers with.
WEB_LIB = Path("src") / "lib"

#: The web's own heading index, ported from `indexSlices`'s `HEADING_LINE_RE`
#: in `superresearch-doc.ts`. Every match becomes a slice the planner may hand
#: a section writer as "Your material".
WEB_HEADING_LINE_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.M)

#: The web's DOCUMENT VIEWER and public share, ported from
#: `HEADING_RE` and `SOURCES_HEADING_RE` in `markdown-components.tsx`. The last
#: heading a document has is folded
#: into a `Sources · n` disclosure when both of these accept it.
WEB_VIEWER_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
WEB_VIEWER_SOURCES_RE = re.compile(r"^sources\b", re.I)

#: The literals above, as the TS declares them — checked against the shipped
#: files by `test_the_three_web_readers_are_still_the_literals_this_file_ports`.
WEB_LITERALS = {
    "superresearch-doc.ts": [
        (r"const HEADING_LINE_RE = /(?P<body>.+?)/[gimsuy]*;", r"^(#{1,4})\s+(.+?)\s*$"),
    ],
    "markdown-components.tsx": [
        (r"const HEADING_RE = /(?P<body>.+?)/[gimsuy]*;", r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$"),
        (r"const SOURCES_HEADING_RE = /(?P<body>.+?)/[gimsuy]*;", r"^sources\b"),
    ],
}

#: The tail this module appends, in its two titles.
SOURCES_TAIL = "\n\n##### Sources\n\n"
ALT_SOURCES_TAIL = "\n\n##### Sources (numbered)\n\n"


def _body(out):
    """The document without the bibliography this module appended."""
    for tail in (SOURCES_TAIL, ALT_SOURCES_TAIL, "\n\n## Sources\n\n"):
        if tail in out:
            return out.split(tail)[0]
    return out


def _markers_on(line):
    return [u for _n, u in MARKER_RE.findall(line)]


# ── the bulleted list ─────────────────────────────────────────────────────────

BULLETED = (
    "# Gemini Deep Research\n"
    "\n"
    "## Cost curves\n"
    "\n"
    "- Pack prices fell by a fifth last year, per https://bnef.example.com/packs\n"
    "- Charging build-out doubled over the same period, per https://iea.example.org/ev-outlook\n"
    "- Sodium-ion remains pre-commercial, per https://argonne.example.gov/na-ion\n"
    "\n"
    "The three together set the floor a 2027 forecast has to clear.\n"
)


class TestEachBulletKeepsItsOwnNumber:
    def test_every_bullets_number_names_the_source_that_bullet_cites(self):
        """⛔⛔ THE HIGH ONE. Before the clamp all three numbers sat on bullet 3,
        so two of the three pointed a reader at a page their sentence never
        mentioned — a confident, clickable, WRONG attribution, and nothing logged
        it. The url on each bullet is the url that bullet's marker must open."""
        out = research._document_with_sources(BULLETED)
        bullets = [ln for ln in _body(out).splitlines() if ln.startswith("- ")]
        assert len(bullets) == 3
        for line in bullets:
            cited = re.findall(r"per (https://\S+?)(?: |$)", line)
            assert len(cited) == 1, line
            assert _markers_on(line) == cited, line

    def test_no_bullet_is_handed_a_number_that_belongs_to_another(self):
        """The same claim from the other side: one marker per bullet, never three
        on the last one."""
        out = research._document_with_sources(BULLETED)
        counts = [len(MARKER_RE.findall(ln))
                  for ln in _body(out).splitlines() if ln.startswith("- ")]
        assert counts == [1, 1, 1]

    def test_the_numbers_still_ascend_and_the_list_still_matches_the_prose(self):
        out = research._document_with_sources(BULLETED)
        assert [int(n) for n, _u in MARKER_RE.findall(out)] == [1, 2, 3]
        rows = re.findall(r"^(\d{1,3})\. \[", out.split(SOURCES_TAIL)[-1], re.M)
        assert [int(n) for n in rows] == [1, 2, 3]


def test_a_numbered_list_item_is_a_sentence_end_too():
    """`1.`/`2.` items are the other half of "a list", and they are how a
    deep-research report writes a ranking."""
    md = (
        "# Claude Deep Research\n"
        "\n"
        "## Ranked by cost\n"
        "\n"
        "1. Northvolt, whose disclosure is at https://bnef.example.com/packs\n"
        "2. CATL, whose filing is at https://iea.example.org/ev-outlook\n"
        "\n"
        "Both are pack-level numbers.\n"
    )
    out = research._document_with_sources(md)
    lines = [ln for ln in _body(out).splitlines() if re.match(r"^\d\. ", ln)]
    assert _markers_on(lines[0]) == ["https://bnef.example.com/packs"]
    assert _markers_on(lines[1]) == ["https://iea.example.org/ev-outlook"]


def test_a_paragraph_that_wraps_is_still_one_sentence():
    """⛔ THE CLAMP MUST NOT BECOME A LINE BREAKER. A hard-wrapped paragraph is
    ONE block, so a sentence that runs past the end of its line still ends where
    its full stop is — not at the wrap."""
    md = (
        "# ChatGPT Deep Research\n"
        "\n"
        "## Cost curves\n"
        "\n"
        "Pack prices fell by a fifth last year, as https://bnef.example.com/packs\n"
        "sets out in its second chapter and nobody has since disputed. A later\n"
        "note repeats it.\n"
    )
    out = research._document_with_sources(md)
    assert "since disputed [\\[1\\]](https://bnef.example.com/packs)." in out


def test_a_wrapped_line_that_starts_with_a_year_is_not_a_list():
    """⛔⛔ WHAT THE CLAMP ITSELF MADE POSSIBLE, CAUGHT AND CLOSED. `2025. Prices`
    at the start of a line looks exactly like an ordered-list item, and the first
    clamp treated it as one — so a wrapped sentence ended at the WRAP and the
    number landed mid-sentence, a placement the unclamped code never produced.
    CommonMark is the arbiter and says the same thing: only `1.`/`1)` may
    interrupt a paragraph, so a numbered item ends a sentence only inside a list
    or when it is the list's first item."""
    md = (
        "# ChatGPT Deep Research\n"
        "\n"
        "## Cost curves\n"
        "\n"
        "The survey at https://bnef.example.com/packs covers every pack shipped in\n"
        "2025. Prices fell by a fifth over the year.\n"
    )
    out = research._document_with_sources(md)
    assert "shipped in\n2025 [\\[1\\]](https://bnef.example.com/packs). Prices" in out


def test_a_list_that_opens_at_one_still_ends_the_sentence_before_it():
    """The other side of the same rule: `1.` DOES interrupt a paragraph, so a
    citation in the line above a list keeps its number on that line."""
    md = (
        "# ChatGPT Deep Research\n"
        "\n"
        "## Cost curves\n"
        "\n"
        "The three drivers are set out at https://bnef.example.com/packs\n"
        "1. Cell chemistry\n"
        "2. Pack integration\n"
    )
    out = research._document_with_sources(md)
    assert ("The three drivers are set out at https://bnef.example.com/packs "
            "[\\[1\\]](https://bnef.example.com/packs)\n1. Cell") in out


# ── the table ─────────────────────────────────────────────────────────────────

TABLE_REPORT = (
    "# ChatGPT Deep Research\n"
    "\n"
    "## Vendors\n"
    "\n"
    "| Vendor | Price | Source |\n"
    "| --- | --- | --- |\n"
    "| Northvolt | $98/kWh | https://bnef.example.com/packs |\n"
    "| CATL | $88/kWh | https://iea.example.org/ev-outlook |\n"
    "\n"
    "Both are pack-level numbers.\n"
)


def _cells(row):
    """The cells GFM will render: the pipe-separated fields of a row, with the
    leading and trailing pipe dropped."""
    parts = row.split("|")
    assert parts[0].strip() == "" and parts[-1].strip() == "", row
    return parts[1:-1]


class TestATableCellsNumberIsVisible:
    def test_a_marker_never_lands_past_the_rows_last_pipe(self):
        """⛔⛔ GFM DISCARDS CELLS BEYOND THE HEADER'S COLUMN COUNT. A marker
        after the trailing `|` is a number that exists in the file, has a row in
        the bibliography, and renders NOWHERE — the invariant this module states
        about itself, broken on the most citation-dense block a report has."""
        out = research._document_with_sources(TABLE_REPORT)
        rows = [ln for ln in _body(out).splitlines() if ln.startswith("|")]
        header, _delim, *data = rows
        width = len(_cells(header))
        assert width == 3
        for row in data:
            cells = _cells(row)
            assert len(cells) == width, row
            assert len(MARKER_RE.findall(row)) == 1, row
            assert MARKER_RE.search(cells[-1]) is not None, row

    def test_each_rows_number_opens_that_rows_own_source(self):
        out = research._document_with_sources(TABLE_REPORT)
        data = [ln for ln in _body(out).splitlines()
                if ln.startswith("|") and "kWh" in ln]
        assert _markers_on(data[0]) == ["https://bnef.example.com/packs"]
        assert _markers_on(data[1]) == ["https://iea.example.org/ev-outlook"]


# ── the fenced block ──────────────────────────────────────────────────────────

FENCED_REPORT = (
    "# Claude Deep Research\n"
    "\n"
    "## How to run it\n"
    "\n"
    "The result is discussed at https://real.example.com/a\n"
    "```bash\n"
    "run --one\n"
    "\n"
    "run --all\n"
    "```\n"
    "\n"
    "That is the whole recipe.\n"
)


def test_no_marker_is_ever_written_inside_a_fenced_block():
    """⛔⛔ `_mask_code` BLANKS A FENCE BUT KEEPS ITS NEWLINES, so a blank line
    inside one reads as a paragraph break and the marker was inserted between two
    commands. It renders as literal text — the "unresolvable marker renders as
    visible breakage" outcome the module header says the design prevents — and it
    corrupts a command a reader may copy."""
    out = research._document_with_sources(FENCED_REPORT)
    assert MARKER_RE.search(out) is not None, "the citation must still be numbered"
    for fence in research._CODE_FENCE_RE.findall(out):
        assert MARKER_RE.search(fence) is None, fence
    assert "run --one\n\nrun --all" in out, "the code block is byte-identical"


FENCE_ON_THE_CITING_LINE = (
    "# Claude Deep Research\n"
    "\n"
    "## Steps\n"
    "\n"
    "Run the check described at https://real.example.com/a ```bash\n"
    "run --one\n"
    "\n"
    "run --all\n"
    "```\n"
    "\n"
    "Done.\n"
)


def test_a_fence_opened_on_the_citing_line_keeps_the_marker_outside_it():
    """⛔⛔ THE ONE SHAPE THE BLOCK CLAMP ALONE DOES NOT CLOSE, AND WHY THE MASKED
    SPANS ARE KEPT. Masking blanks every line INSIDE a fence, so the clamp can
    never walk into one — but when the fence OPENS on the citing line, the end of
    that line is already inside the fence span, and the marker landed in the info
    string (```` ```bash [\\[1\\]](…) ````) where it is part of the code block,
    not a citation. Rejecting a position that falls inside a masked span is the
    only thing that catches it."""
    out = research._document_with_sources(FENCE_ON_THE_CITING_LINE)
    line = [ln for ln in out.splitlines() if ln.startswith("Run the check")][0]
    assert line == ("Run the check described at https://real.example.com/a "
                    "[\\[1\\]](https://real.example.com/a) ```bash")


def test_the_number_sits_at_the_end_of_the_line_that_cites():
    out = research._document_with_sources(FENCED_REPORT)
    line = [ln for ln in out.splitlines() if ln.startswith("The result")][0]
    assert line == ("The result is discussed at https://real.example.com/a "
                    "[\\[1\\]](https://real.example.com/a)")


# ── a report that brought its own bibliography ────────────────────────────────

OWN_SOURCES_REPORT = (
    "# ChatGPT Deep Research\n"
    "\n"
    "## Findings\n"
    "\n"
    "Pack prices fell by a fifth, reported at https://bnef.example.com/packs in "
    "a note that the industry has not disputed since.\n"
    "\n"
    "## Sources\n"
    "\n"
    "- BNEF, *Battery pack price survey*\n"
)


class TestOneSourcesHeadingPerDocument:
    def test_a_report_that_ends_with_its_own_sources_gets_no_second_one(self):
        """⛔⛔ Deep-research reports commonly end with a source list, so this is
        the COMMON case, and it shows in the document, the share and the Google
        Doc. Ours is titled apart rather than stacked under a second identical
        heading — appending our rows INTO the agent's list would be worse still,
        because a renderer continues an ordered list and our explicit `1.` would
        render as the next number."""
        out = research._document_with_sources(OWN_SOURCES_REPORT)
        headings = [h for _lvl, h in WEB_HEADING_LINE_RE.findall(out)]
        assert headings.count("Sources") == 1
        assert ALT_SOURCES_TAIL in out

    def test_the_agents_own_section_is_returned_untouched_by_the_strip(self):
        """The strip takes OUR tail back off and leaves the report's own list,
        which is what `save_meta` then reads."""
        out = research._document_with_sources(OWN_SOURCES_REPORT)
        stripped = research._strip_numbered_sources_section(out)
        assert stripped.endswith("- BNEF, *Battery pack price survey*")
        assert "Numbered sources" not in stripped
        assert stripped == _body(out)
        assert "## Sources" in stripped


# ── the heading the planner must not see ──────────────────────────────────────

class TestOurHeadingIsNotAResearchSlice:
    def test_numbering_adds_no_heading_the_web_planner_would_index(self):
        """⛔⛔ `indexSlices` (superresearch-doc.ts) indexes each agent report by its own
        ATX headings and `planPromptInput` feeds that list to the plan
        call, so our `## Sources` became a slice a section writer could be handed
        as "Your material" — up to three per run, each one a list of links. The
        web is shipped and read-only to this repo."""
        clean = BULLETED
        numbered = research._document_with_sources(clean)
        assert numbered != clean
        assert (WEB_HEADING_LINE_RE.findall(numbered)
                == WEB_HEADING_LINE_RE.findall(clean))

    def test_the_viewer_and_the_share_still_collapse_it(self):
        """⛔⛔ THE READER-FACING HALF, AND THE ONE THE FIRST DRAFT OF THIS REPAIR
        BROKE. `DocumentMarkdown` folds a document's LAST heading into a
        `Sources · n` disclosure when it is ATX 1-6 AND its text starts with
        "sources" — on the Documents page AND on every public share. A setext
        heading dodges the planner just as well and renders the same `<h2>`, and
        it would have stopped this collapsing on both surfaces with nothing to
        see. Level five is the only form that clears the planner and still
        folds."""
        for md in (BULLETED, OWN_SOURCES_REPORT):
            out = research._document_with_sources(md)
            lines = out.splitlines()
            last = max(i for i, ln in enumerate(lines)
                       if WEB_VIEWER_HEADING_RE.match(ln))
            title = WEB_VIEWER_HEADING_RE.match(lines[last]).group(2).strip()
            assert title in ("Sources", "Sources (numbered)"), title
            assert WEB_VIEWER_SOURCES_RE.match(title), title
            assert "\n".join(lines[last + 1:]).strip().startswith("1. ["), out

    def test_the_three_web_readers_are_still_the_literals_this_file_ports(self):
        """⛔⛔ THE ONLY CROSS-REPO PIN AVAILABLE FROM THIS SIDE. Nothing in the
        backend reads the TS, so the ports above can only ever fail on MACHINE
        drift — and the hazard runs the other way: the planner widening to
        `#{1,6}`, or the viewer narrowing to `#{1,3}`, would each put the
        bibliography back where it must not be, with a green backend suite.

        SKIPPED is the honest answer with no web checkout beside this repo, and
        the skip names what went unmeasured rather than passing quietly."""
        for name, pairs in WEB_LITERALS.items():
            src = web_file("the planner and viewer heading rules",
                           str(WEB_LIB / name)).read_text(encoding="utf-8")
            for decl, ported in pairs:
                m = re.search(decl, src)
                assert m, "%s: %s is no longer declared the way this reads it" % (name, decl)
                assert m.group("body") == ported, (name, m.group("body"), ported)

    def test_save_meta_cannot_read_our_heading_as_a_section_either(self):
        """The machine's own heading scanner is `^#{1,3}\\s+`, which is why
        `_strip_numbered_sources_section` had to exist. It still runs; this pins
        that a strip that failed could no longer cost a bold-titled report its
        sections."""
        out = research._document_with_sources(BULLETED)
        assert re.findall(r"^#{1,3}\s+(.+)$", out, re.M) == [
            "Gemini Deep Research", "Cost curves"]


# ── the brief the agents are handed ───────────────────────────────────────────

def test_the_brief_the_agents_receive_carries_no_marker_they_could_echo():
    """SOURCE PIN — the three `run_pipeline` brief saves and `run_phase2`'s
    attachment writer each need a browser, a queue and a live run.

    ⛔⛔ THE SELF-INFLICTED ONE. `brief.md` is the file ChatGPT and Claude
    RECEIVE — attached when `use_file_attach`, pasted off disk on a hard retry —
    and wave 10 numbered it. `_DOC_SOURCE_MARK_RE` is this module's idempotency
    sentinel, and its comment claims it "cannot collide with anything an agent
    writes"; numbering the brief made that false BY CONSTRUCTION. One imitated
    marker in an agent's report and `_number_document_sources` returns that report
    COMPLETELY unnumbered, with no bibliography, on the Documents page, in the
    share and in the Google Doc, with nothing raised.

    ⭐ THE DECISION, AND WHY IT IS THE ONLY ONE AVAILABLE. The other option named
    was "make the sentinel something an agent cannot echo" — but the sentinel has
    to be IN the numbered output to make the pass idempotent, and the numbered
    output IS what the agent is holding. Any sentinel we could choose is, by
    construction, text they have in hand. The collision is only closable at the
    other end: stop handing them a numbered document. It also restores what the
    agents are asked to research to byte-identical-to-pre-wave-10."""
    src = code_only_deep(research.run_pipeline) + code_only_deep(research.run_phase2)
    #: Three phase-1 saves, the phase-2 attachment writer, and the inline-brief
    #: persist that was never numbered. A sixth fails here until it is counted.
    builds = src.count('f"# Research Brief\\n\\n{brief_text}"')
    assert builds == 5, builds
    assert '_document_with_sources(f"# Research Brief' not in src
    assert "_document_with_sources" not in "".join(
        ln for ln in src.splitlines() if "# Research Brief" in ln)
