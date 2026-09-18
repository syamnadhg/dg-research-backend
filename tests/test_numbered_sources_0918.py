"""Wave 10 — NUMBERED SOURCES IN THE MACHINE'S OWN DOCUMENTS, 2026-09-18.

The reader's ask: *"when I see a sentence I really want to see where did that
sentence come from."* The web shipped this for the two documents IT generates;
this is the same contract for the four the machine writes — the phase-1 brief
and the three phase-2 agent reports.

⛔⛔ THE ONE THING THAT COULD GO SILENTLY WRONG IS THE GRAMMAR, AND IT IS WHAT
MOST OF THIS FILE PINS. `src/lib/doc-sources.ts` RESERVES `[[n]]` as the token a
MODEL writes, on the measured ground that "the doubled form has never appeared in
an agent report" — and both web generators feed the agent reports to the model
UNSTRIPPED and then rewrite every `[[n]]` in the reply against the WEB's own
numbering, which is computed across all three agents at once. A machine marker
written in that grammar would become model input, come back in the synthesis and
be renumbered to a DIFFERENT source: a citation that looks right and opens the
wrong page. Nothing would raise, and nothing would look broken.

⭐ So the machine emits `[\\[n\\]](url)` — a link whose TEXT is an ESCAPED
bracketed number. Verified against the web's own micromark + GFM stack: it
renders `<a href="url">[n]</a>`, identical to the web's `sourceMarker`, and it
contains no `[[` for the web's token regex to find.

⛔ THE SECOND HAZARD IS THE RENDERER, AND IT IS MEASURED, NOT ASSUMED. Appending
the marker directly after a BARE url is swallowed by GFM's autolink-literal
extension — `…/packs[\\[1\\]](…)` renders as ONE broken link whose href is the
marker's own text. A separating space fixes it in every shape, so the marker
carries one whenever the character before it is not already whitespace.

⛔ AND A NUMBER IS ONLY WRITTEN FOR A URL THE DOCUMENT ACTUALLY CONTAINS.
An unresolvable marker renders as literal text, so numbering and PLACEMENT are
one decision: a source earns a number only when its marker was placed, and the
list holds exactly the numbers that appear in the prose.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402


#: The web's own token regex, ported character for character from
#: `SOURCE_TOKEN_RE` in src/lib/doc-sources.ts. Anything this finds in a machine
#: document is a marker the web would renumber.
WEB_MODEL_TOKEN_RE = re.compile(r"\[\[(\d{1,3})\]\]")

#: Our marker, as a reader of this file can check by eye against the header.
MARKER_RE = re.compile(r"\[\\\[(\d{1,3})\\\]\]\(([^)]*)\)")

#: A marker glued to the tail of a bare url — the GFM autolink defect.
GLUED_RE = re.compile(r"https?://[^\s)\]]*\[\\\[")

#: The bibliography this module appends, heading and all.
#:
#: ⛔⛔ WAVE 10 REPAIR — THE HEADING IS LEVEL FIVE, NOT `## `. It is below the
#: `#{1,4}` the web's Super Research planner indexes (which turned our
#: bibliography into a phantom research slice) and below `save_meta`'s `#{1,3}`
#: count, while staying inside the `#{1,6}` the web's viewer and public share
#: collapse into a `Sources · n` disclosure. See
#: `tests/test_numbered_sources_placement_0918.py`.
SOURCES_TAIL = "\n\n##### Sources\n\n"

REPORT = (
    "# Claude Deep Research\n"
    "\n"
    "## Battery prices\n"
    "\n"
    "Pack prices fell by a fifth, reported at https://bnef.example.com/packs in "
    "a note. A second source, [the agency](https://iea.example.org/ev-outlook), "
    "puts it lower."
)


def _rows(md):
    """The bibliography's numbers, in the order the list gives them."""
    tail = md.split(SOURCES_TAIL)
    if len(tail) == 1:
        return []
    return [int(m.group(1)) for m in re.finditer(r"^(\d{1,3})\. \[", tail[-1], re.M)]


# ── the grammar collision ─────────────────────────────────────────────────────

class TestTheGrammarIsNotTheWebsToken:
    def test_the_inline_marker_is_an_escaped_bracketed_number_link(self):
        """⛔⛔ EQUALITY, NOT CONTAINMENT. `[[1]](url)` CONTAINS every character
        a laxer assertion would look for, so only the exact string separates the
        grammar we chose from the one that collides."""
        assert research._doc_source_marker(1, "https://e.example.com/a") == (
            "[\\[1\\]](https://e.example.com/a)")

    def test_a_numbered_document_carries_nothing_the_web_would_renumber(self):
        """⛔⛔ THE WHOLE LANE IN ONE ASSERTION — and the count is what stops it
        being satisfiable by a document with no markers at all.

        ⛔ WAVE 10 REPAIR, AND IT IS A SCOPE CORRECTION, NOT A WIDENING. This
        pins THE MACHINE against a copy of the web's token, so the only drift it
        can ever catch is the machine changing its own grammar. It cannot see the
        WEB widening `SOURCE_TOKEN_RE`, which is the direction the lane is
        actually afraid of — that is what the test below is for."""
        out = research._document_with_sources(REPORT)
        assert len(MARKER_RE.findall(out)) == 2
        assert WEB_MODEL_TOKEN_RE.search(out) is None

    def test_the_ported_token_is_still_the_literal_the_web_ships(self):
        """⛔⛔ THE ONLY CROSS-REPO PIN AVAILABLE FROM THIS SIDE, and the reason
        it has to exist: if the web ever widens `SOURCE_TOKEN_RE` — to accept
        `[n]`, or an escaped form — machine markers become model input again and
        come back renumbered to a different source, with a fully green backend
        suite and nothing to notice. Nothing in the backend reads the TS file, so
        the ported copy above can only ever fail on MACHINE drift.

        It reads the sibling checkout when there is one. SKIPPED is the honest
        answer where there is not — a shipped wheel has no web repo beside it —
        and the skip names what went unmeasured rather than passing quietly."""
        ts = (Path(__file__).resolve().parents[2]
              / "dg-research" / "src" / "lib" / "doc-sources.ts")
        if not ts.exists():
            pytest.skip("no dg-research checkout beside this repo: the web's "
                        "SOURCE_TOKEN_RE was NOT compared against the port")
        m = re.search(r"export const SOURCE_TOKEN_RE = /(?P<body>.+?)/[gimsuy]*;",
                      ts.read_text(encoding="utf-8"))
        assert m, "SOURCE_TOKEN_RE is no longer declared the way this reads it"
        assert m.group("body") == WEB_MODEL_TOKEN_RE.pattern

    def test_the_bibliography_carries_nothing_the_web_would_renumber_either(self):
        """A row whose TITLE happens to be bracketed must not manufacture the
        token the prose was kept clear of."""
        md = ("# Claude Deep Research\n\n## [[2]] revisited\n\n"
              "The follow-up is at https://e.example.com/a and says as much.\n")
        out = research._document_with_sources(md)
        assert SOURCES_TAIL in out
        assert WEB_MODEL_TOKEN_RE.search(out.split(SOURCES_TAIL)[-1]) is None


# ── every number opens a source ───────────────────────────────────────────────

class TestEveryNumberOpensASource:
    def test_the_prose_and_the_list_hold_exactly_the_same_numbers(self):
        out = research._document_with_sources(REPORT)
        assert [int(n) for n, _u in MARKER_RE.findall(out)] == [1, 2]
        assert _rows(out) == [1, 2]

    def test_every_marker_points_at_the_url_its_row_points_at(self):
        out = research._document_with_sources(REPORT)
        tail = out.split(SOURCES_TAIL)[-1]
        for n, url in MARKER_RE.findall(out):
            assert ("%s. [" % n) in tail
            assert ("](%s)" % url) in tail

    def test_a_finding_whose_url_the_document_never_mentions_earns_no_number(self):
        """⛔⛔ THE FAILURE THIS DESIGN EXISTS TO MAKE IMPOSSIBLE. `_extract_findings`
        emits the PANEL's spelling of a url when the panel supplied one, and the
        panel's spelling need not appear in the prose at all — so a marker placed
        from the finding alone could name a source no sentence mentions. Numbers
        are given out at PLACEMENT, so the absent one takes no number and leaves
        no gap in the ones that remain."""
        findings = [
            {"url": "https://absent.example.com/never-cited", "snippet": "x",
             "sourceTitle": "Absent"},
            {"url": "https://bnef.example.com/packs", "snippet": "y",
             "sourceTitle": "Battery prices"},
        ]
        out = research._number_document_sources(REPORT, findings)
        assert "absent.example.com" not in out
        assert [int(n) for n, _u in MARKER_RE.findall(out)] == [1]
        assert _rows(out) == [1]

    def test_a_url_shown_inside_a_code_fence_is_teaching_not_citing(self):
        """A report that shows you `curl http://localhost/api` is not citing it,
        which is the rule `_sweep_source_urls` already applies — through the same
        `_mask_code`, so the two cannot drift."""
        md = ("# Gemini Deep Research\n\n## How to check\n\n"
              "```\ncurl https://fenced.example.com/api\n```\n\n"
              "The result is discussed at https://real.example.com/a in full.\n")
        findings = [
            {"url": "https://fenced.example.com/api", "snippet": "x", "sourceTitle": "How to check"},
            {"url": "https://real.example.com/a", "snippet": "y", "sourceTitle": "How to check"},
        ]
        out = research._number_document_sources(md, findings)
        # ⛔⛔ WAVE 10 REPAIR — THIS LINE USED TO READ
        # `assert "fenced.example.com/api[" not in out`, WHICH COULD NOT FAIL.
        # A marker is never glued to a url by design (the separating space plus
        # sentence-tail placement), so that string was unreachable whether
        # `_mask_code` ran or not: remove the mask and the assertion still
        # passed. What the mask actually decides is whether the fenced url
        # becomes a DESTINATION — a marker's or a row's — and it is the only
        # thing that can put it there.
        assert "](https://fenced.example.com/api)" not in out
        assert [u for _n, u in MARKER_RE.findall(out)] == ["https://real.example.com/a"]
        assert _rows(out) == [1]

    def test_an_agents_own_conversation_never_gets_a_number(self):
        """⛔⛔ THESE DOCUMENTS ARE FROZEN INTO A PUBLIC SHARE AND INSERTED INTO A
        DELIVERED GOOGLE DOC. A report can cite the chat it was written in, and a
        number behind that address hands a stranger the owner's private session."""
        md = ("# ChatGPT Deep Research\n\n## Method\n\n"
              "The working session is at https://chatgpt.com/c/abc123 for reference "
              "and the data came from https://real.example.com/a as well.\n")
        findings = [
            {"url": "https://chatgpt.com/c/abc123", "snippet": "x", "sourceTitle": "Method"},
            {"url": "https://real.example.com/a", "snippet": "y", "sourceTitle": "Method"},
        ]
        out = research._number_document_sources(md, findings)
        assert [u for _n, u in MARKER_RE.findall(out)] == ["https://real.example.com/a"]
        assert "](https://chatgpt.com" not in out

    def test_a_document_whose_findings_are_all_unplaceable_is_returned_untouched(self):
        findings = [{"url": "https://absent.example.com/x", "snippet": "x",
                     "sourceTitle": "Absent"}]
        assert research._number_document_sources(REPORT, findings) == REPORT

    def test_a_document_with_no_findings_at_all_is_returned_untouched(self):
        assert research._number_document_sources(REPORT, []) == REPORT


# ── the renderer ──────────────────────────────────────────────────────────────

class TestTheMarkerSurvivesTheRenderer:
    def test_the_whole_document_is_emitted_exactly_like_this(self):
        """⛔⛔ THE CONTRACT IN ONE STRING — grammar, placement, the separating
        space, the ascending numbers, the heading and the row format. Verified
        against the web's own micromark + GFM stack, which renders it as

            <p>… <a href="…/packs">https://…/packs</a> in a note
            <a href="…/packs">[1]</a>. …</p>
            <h2>Sources</h2><ol><li><a …>Battery prices</a> — bnef.example.com</li>…

        i.e. an inline `[1]` that OPENS the source, plus a browsable list."""
        assert research._document_with_sources(REPORT) == (
            "# Claude Deep Research\n"
            "\n"
            "## Battery prices\n"
            "\n"
            "Pack prices fell by a fifth, reported at https://bnef.example.com/packs "
            "in a note [\\[1\\]](https://bnef.example.com/packs). A second source, "
            "[the agency](https://iea.example.org/ev-outlook), puts it lower "
            "[\\[2\\]](https://iea.example.org/ev-outlook).\n"
            "\n"
            "##### Sources\n"
            "\n"
            "1. [Battery prices](https://bnef.example.com/packs) — bnef.example.com\n"
            "2. [Battery prices](https://iea.example.org/ev-outlook) — iea.example.org\n"
        )

    def test_no_marker_is_ever_glued_to_the_tail_of_a_bare_url(self):
        """⛔⛔ THE MEASURED RENDERER DEFECT. Without the separating space GFM's
        autolink-literal extension swallows the marker into the preceding href
        and BOTH links break — the source link and the number."""
        md = ("# Claude Deep Research\n\n## Findings\n\n"
              "The whole case rests on https://bare.example.com/a")
        findings = [{"url": "https://bare.example.com/a", "snippet": "x",
                     "sourceTitle": "Findings"}]
        out = research._number_document_sources(md, findings)
        assert MARKER_RE.search(out) is not None
        assert GLUED_RE.search(out) is None

    def test_a_number_that_ends_the_document_sits_before_the_full_stop(self):
        """`[.!?]\\s` needs the space, so a report ending without a newline has no
        sentence tail to find — the number must not be orphaned past the stop."""
        md = ("# Claude Deep Research\n\n## Findings\n\n"
              "The whole case rests on https://bare.example.com/a and nothing else.")
        findings = [{"url": "https://bare.example.com/a", "snippet": "x",
                     "sourceTitle": "Findings"}]
        out = research._number_document_sources(md, findings)
        assert out.split(SOURCES_TAIL)[0].endswith(
            "nothing else [\\[1\\]](https://bare.example.com/a).")

    def test_a_url_carrying_parentheses_is_encoded_in_the_marker_and_the_row(self):
        """⛔ An unencoded `)` ends the markdown link early, so the tail of the
        address becomes visible prose and the number opens a truncated URL — a
        broken link that LOOKS like a working one."""
        url = "https://en.wikipedia.example.org/wiki/Mercury_(planet)"
        md = ("# Gemini Deep Research\n\n## Planets\n\n"
              "Mercury is small, as %s explains at some length.\n" % url)
        out = research._number_document_sources(
            md, [{"url": url, "snippet": "x", "sourceTitle": "Planets"}])
        assert "Mercury_%28planet%29)" in out
        assert [u for _n, u in MARKER_RE.findall(out)] == [
            "https://en.wikipedia.example.org/wiki/Mercury_%28planet%29"]


# ── order, and running twice ──────────────────────────────────────────────────

class TestOrderAndIdempotency:
    def test_numbers_ascend_through_the_document_whatever_order_they_arrive_in(self):
        """The findings list is first-MENTION ordered, but a caller may hand back
        a reordered list (a resume reads a persisted one). The numbers a reader
        meets must still count up."""
        findings = [
            {"url": "https://iea.example.org/ev-outlook", "snippet": "y", "sourceTitle": "B"},
            {"url": "https://bnef.example.com/packs", "snippet": "x", "sourceTitle": "A"},
        ]
        out = research._number_document_sources(REPORT, findings)
        assert MARKER_RE.findall(out) == [
            ("1", "https://bnef.example.com/packs"),
            ("2", "https://iea.example.org/ev-outlook"),
        ]

    def test_numbering_an_already_numbered_document_changes_nothing(self):
        """⛔⛔ THE RESUME PATH DEPENDS ON THIS. The phase-1 skip branch reads
        brief.md back off disk and hands it on, and the phase-2 attachment writer
        can write it again — a second pass that appended a second bibliography
        would be visible to the owner on every resumed run."""
        once = research._document_with_sources(REPORT)
        assert research._document_with_sources(once) == once

    def test_a_reordered_findings_list_produces_the_same_document(self):
        a = research._document_with_sources(REPORT)
        findings = list(reversed(research._extract_findings(REPORT, [])))
        assert research._number_document_sources(REPORT, findings) == a


# ── the bibliography row ──────────────────────────────────────────────────────

class TestTheBibliographyRow:
    def test_two_sources_under_one_heading_are_told_apart_by_their_host(self):
        """⛔ `_extract_findings`' title is the nearest heading IN OUR OWN
        DOCUMENT, not the page's name, so both rows here arrive called "Battery
        prices". Without the host column the list tells a reader nothing about
        where either number goes."""
        tail = research._document_with_sources(REPORT).split(SOURCES_TAIL)[-1]
        assert tail == (
            "1. [Battery prices](https://bnef.example.com/packs) — bnef.example.com\n"
            "2. [Battery prices](https://iea.example.org/ev-outlook) — iea.example.org\n")

    def test_a_row_whose_title_is_already_its_host_does_not_say_it_twice(self):
        assert research._doc_sources_row(3, "https://www.e.example.com/a", "e.example.com") == (
            "3. [e.example.com](https://www.e.example.com/a)")

    def test_brackets_in_a_title_are_escaped_so_the_row_stays_a_link(self):
        assert research._doc_sources_row(1, "https://e.example.com/a", "The [2020] review") == (
            "1. [The \\[2020\\] review](https://e.example.com/a) — e.example.com")

    def test_the_numbers_are_written_out_not_left_to_the_renderer(self):
        """⛔ The document is also inserted into a delivered Google Doc and frozen
        into a share as PLAIN TEXT, where a renderer-computed `1.` repeated would
        leave every number in the prose pointing at a position nothing states."""
        tail = research._document_with_sources(REPORT).split(SOURCES_TAIL)[-1]
        assert tail.splitlines()[1].startswith("2. ")


# ── the write-site face ───────────────────────────────────────────────────────

class TestTheWriteSiteHelper:
    def test_it_finds_the_documents_own_citations_when_no_findings_are_handed_in(
            self, monkeypatch):
        """The regen sites have no findings in hand; the numbering must come from
        the report's OWN text rather than from nothing.

        ⛔⛔ WAVE 10 REPAIR — THIS TEST USED TO BE BYTE-FOR-BYTE
        `test_a_numbered_document_carries_nothing_the_web_would_renumber`'s first
        line, on the same fixture: it could not fail independently of that test,
        and it could not tell "extracted from the report" from "handed in" — the
        one thing its name claims. Its sibling below pins that the extraction
        does NOT run when rows are given; this one pins the other half, that it
        DOES run, and on the document itself."""
        seen = []
        real = research._extract_findings

        def _spy(md, source_urls):
            seen.append((md, list(source_urls)))
            return real(md, source_urls)

        monkeypatch.setattr(research, "_extract_findings", _spy)
        out = research._document_with_sources(REPORT)
        assert seen == [(REPORT, [])]
        assert len(MARKER_RE.findall(out)) == 2
        # ⛔ AND THE PANEL'S SPELLING IS FORWARDED, NOT DROPPED. `source_urls` is
        # the whole reason this face takes a second argument: a panel row and the
        # report's own citation of the same page have to compare equal.
        seen.clear()
        research._document_with_sources(REPORT, ["https://iea.example.org/ev-outlook"])
        assert seen == [(REPORT, ["https://iea.example.org/ev-outlook"])]

    def test_a_failed_extraction_costs_the_numbers_and_never_the_document(self, monkeypatch):
        """⛔ Every caller is a WRITE. An un-numbered document is a small loss; an
        exception here would take the report with it."""
        def _boom(*_a, **_k):
            raise RuntimeError("extraction exploded")

        monkeypatch.setattr(research, "_extract_findings", _boom)
        assert research._document_with_sources(REPORT) == REPORT

    def test_handed_findings_are_used_and_nothing_is_re_extracted(self, monkeypatch):
        """The two phase-2 write sites extract from the CLEAN report and pass the
        rows in — re-extracting here would read the bibliography this pass is
        about to append."""
        def _boom(*_a, **_k):
            raise AssertionError("_extract_findings must not run when rows are given")

        monkeypatch.setattr(research, "_extract_findings", _boom)
        out = research._document_with_sources(
            REPORT, findings=[{"url": "https://bnef.example.com/packs", "snippet": "x",
                               "sourceTitle": "Battery prices"}])
        assert [int(n) for n, _u in MARKER_RE.findall(out)] == [1]


# ── the consumer that reads the report back ───────────────────────────────────

class TestSaveMetaStillReadsTheReportAndNotOurTail:
    """⛔⛔ `save_meta` JUDGES THE REPORT'S OWN STRUCTURE, so appending a heading
    to the file changes what it concludes. Its bold-pseudo-heading fallback fires
    only at two headings or fewer — the shape ChatGPT reports have."""

    @staticmethod
    def _sections(run_dir, monkeypatch, content):
        (run_dir / "documents").mkdir(parents=True, exist_ok=True)
        (run_dir / "documents" / "chatgpt.md").write_text(content, encoding="utf-8")

        class _Runtime:
            agent_progress_snapshots = {}

        monkeypatch.setattr(research, "_runtime", _Runtime(), raising=False)
        research.save_meta(run_dir, "a topic", 2)
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        return meta["agents"]["chatgpt"]["sections"]

    #: Two real headings — so one more would push it past the fallback's test —
    #: and its actual section titles written in ChatGPT's bold style.
    BOLD_REPORT = (
        "# ChatGPT Deep Research\n"
        "\n"
        "## Overview\n"
        "\n"
        "**Market structure**\n"
        "\n"
        "The market is concentrated, as https://packs.example.com/a sets out at "
        "length in its second chapter.\n"
        "\n"
        "**Regulatory outlook**\n"
        "\n"
        "Rules tighten from 2027 onward, which every forecaster now assumes.\n"
    )

    def test_an_appended_bibliography_does_not_cost_a_bold_titled_report_its_sections(
            self, tmp_path, monkeypatch):
        """⛔⛔ THE REGRESSION THIS LANE WOULD OTHERWISE HAVE SHIPPED. Two headings
        plus our `## Sources` is three, the fallback is skipped, and a ChatGPT
        report loses every section title it has — on the analytics surface, with
        nothing raised."""
        numbered = research._document_with_sources(self.BOLD_REPORT)
        assert SOURCES_TAIL in numbered  # the fixture must actually be numbered
        got = self._sections(tmp_path, monkeypatch, numbered)
        assert "Market structure" in got
        assert "Regulatory outlook" in got

    def test_our_own_heading_is_never_reported_as_a_section_of_the_report(
            self, tmp_path, monkeypatch):
        numbered = research._document_with_sources(self.BOLD_REPORT)
        assert "Sources" not in self._sections(tmp_path, monkeypatch, numbered)

    def test_the_sections_are_the_same_ones_the_unnumbered_report_gave(
            self, tmp_path, monkeypatch):
        """The strongest form of the same claim: numbering a document changes
        NOTHING about what this reader concludes from it."""
        plain = self._sections(tmp_path / "a", monkeypatch, self.BOLD_REPORT)
        numbered = self._sections(
            tmp_path / "b", monkeypatch, research._document_with_sources(self.BOLD_REPORT))
        assert numbered == plain


class TestTheStripOnlyEverRemovesOurOwnTail:
    def test_an_agents_own_sources_section_is_left_alone(self):
        """⛔ The strip must not reach into a report that wrote its own sources
        list — only a tail carrying OUR markers is ours to remove."""
        md = ("# ChatGPT Deep Research\n\n## Findings\n\nProse.\n\n"
              "## Sources\n\n1. [A page](https://e.example.com/a)\n")
        assert research._strip_numbered_sources_section(md) == md

    def test_our_tail_comes_off_and_the_report_is_byte_identical_again(self):
        numbered = research._document_with_sources(REPORT)
        stripped = research._strip_numbered_sources_section(numbered)
        assert SOURCES_TAIL not in stripped and "##### Sources" not in stripped
        assert stripped.startswith("# Claude Deep Research")
        # The markers stay — they are inline citations, not our appended tail —
        # and every one of them still names a url the report itself carries.
        for _n, url in MARKER_RE.findall(stripped):
            assert url in REPORT


# ── the phase-2 write path, executed ──────────────────────────────────────────

class _Page:
    url = "https://chatgpt.com/c/abc"


class _Browser:
    async def switch_to_page(self, page):
        return None


class _Runtime:
    def __init__(self):
        self.agent_findings = {}
        self.agent_progress_snapshots = {}


CITED_REPORT = (
    "## Battery prices\n"
    "\n"
    "Pack prices fell by a fifth, reported at https://bnef.example.com/packs in "
    "a note that the industry has not disputed since.\n"
)


def _drive_the_phase_two_write(monkeypatch, tmp_path, report):
    """The REAL write site — `extract_and_record_agent` — driven end to end.

    Only the browser, the network and Firestore are stubbed; the extraction, the
    findings pass, the numbering and both writes are the shipped code."""
    import asyncio

    saved = []

    async def _extract(page, **kw):
        return report

    async def _rehost(text, label=None, **kw):
        return text

    async def _save(doc_type, content, name=None, **kw):
        saved.append((doc_type, content))
        return True

    async def _no_sleep(*a, **k):
        return None

    runtime = _Runtime()
    monkeypatch.setattr(research, "_runtime", runtime, raising=False)
    monkeypatch.setattr(research, "extract_chatgpt_response", _extract)
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)
    monkeypatch.setattr(research, "_rehost_document_images", _rehost)
    monkeypatch.setattr(research, "save_document_to_firestore_with_retry", _save)
    monkeypatch.setattr(research, "_firebase_db", object())
    monkeypatch.setattr(research, "_fb_uid", "uid-1")
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research.asyncio, "sleep", _no_sleep)
    asyncio.run(research.extract_and_record_agent(
        "ChatGPT", _Page(), _Browser(), None, tmp_path))
    return runtime, saved, (tmp_path / "documents" / "chatgpt.md").read_text(encoding="utf-8")


class TestThePhaseTwoWriteSiteNumbersWhatItSaves:
    def test_the_saved_report_carries_its_numbers_on_disk_and_in_firestore(
            self, monkeypatch, tmp_path):
        """⛔ THE CONSUMER, NOT THE HELPER. Both writes must carry the SAME
        numbered document — a mirror that disagreed with the file would show one
        reader a citation the other does not have."""
        _runtime, saved, local = _drive_the_phase_two_write(
            monkeypatch, tmp_path, CITED_REPORT)
        assert MARKER_RE.findall(local) == [("1", "https://bnef.example.com/packs")]
        assert local.endswith(
            SOURCES_TAIL +
            "1. [Battery prices](https://bnef.example.com/packs) — bnef.example.com\n")
        assert saved == [("chatgpt", local)]

    def test_the_findings_are_read_from_the_report_and_not_from_the_bibliography(
            self, monkeypatch, tmp_path):
        """⛔⛔ THE ORDERING DEFECT THIS SITE WAS RESTRUCTURED TO AVOID. Extracted
        AFTER the numbering, every link in the appended list is itself "a url in
        the report", so the Findings tab fills with rows whose snippet is a
        bibliography line and whose title is "Sources"."""
        runtime, _saved, _local = _drive_the_phase_two_write(
            monkeypatch, tmp_path, CITED_REPORT)
        got = runtime.agent_findings["chatgpt"]
        assert [f["sourceTitle"] for f in got] == ["Battery prices"]
        assert "## Sources" not in got[0]["snippet"]

    def test_a_report_citing_nothing_is_written_exactly_as_it_was(
            self, monkeypatch, tmp_path):
        plain = "## Findings\n\nThe market is concentrated and always has been.\n"
        _runtime, saved, local = _drive_the_phase_two_write(monkeypatch, tmp_path, plain)
        assert local == "# ChatGPT Deep Research\n\n" + plain
        assert saved == [("chatgpt", local)]


def test_every_document_write_site_routes_through_the_numbering_funnel():
    """SOURCE PIN — the pipeline's write sites cannot all be executed here.

    The per-agent save, the finalize re-save and the two regen re-saves: the
    four AGENT-REPORT documents that reach a reader, and a fifth write site
    fails this until it is funneled and counted.

    ⛔⛔ WAVE 10 REPAIR — THE THREE BRIEF SAVES AND THE PHASE-2 ATTACHMENT WRITER
    ARE DELIBERATELY NOT HERE, AND THE COUNT IS HOW THAT STAYS TRUE. `brief.md`
    is the file the agents RECEIVE, so numbering it handed them this module's own
    idempotency sentinel and one echoed marker cost a whole agent report its
    numbers and its bibliography, silently. The brief builds are pinned unnumbered
    in `tests/test_numbered_sources_placement_0918.py`; re-funnelling one would
    raise this count and fail here.

    ⛔⛔ COUNTED ON CODE, AND PER FUNCTION. The first cut of this pin counted
    `inspect.getsource` — comments included — over the three functions joined
    into one string, and the 09-18 cross-verify paid for a deleted call with a
    comment naming it: the run_pipeline finalize re-save stopped numbering, the
    owner would have seen citations in one copy of a report and none in the
    re-saved one, and all 41 tests here stayed green. Only ONE of the sites has
    an executed consumer (`extract_and_record_agent`, driven above), so the
    other three were bought outright. `code_only_deep` blanks comments AND
    docstrings, so a mention of the call is no longer a call; per-function
    counts stop a new site anywhere from paying for a deleted one somewhere
    else."""
    from conftest import code_only_deep

    sites = {fn.__name__: code_only_deep(fn).count("_document_with_sources(")
             for fn in (research.run_pipeline, research.run_phase2,
                        research.extract_and_record_agent)}
    assert sites == {
        # the finalize re-save + the two regen re-saves
        "run_pipeline": 3,
        # nothing: phase 2 records through extract_and_record_agent
        "run_phase2": 0,
        # the per-agent save, the site the executed test above drives
        "extract_and_record_agent": 1,
    }


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "data:text/html,<b>x</b>",
    "https://e.example.com/a b",
    "https://e.example.com/<script>",
    "ftp://e.example.com/a",
    "",
    None,
    12,
])
def test_a_destination_we_would_not_put_behind_a_number(bad):
    """⛔ A `javascript:` or `data:` destination reaching markdown is a script
    surface, and whitespace inside a link destination silently truncates the
    href — another way to render a number that opens somewhere other than where
    it says."""
    assert research._doc_is_linkable_url(bad) is False
