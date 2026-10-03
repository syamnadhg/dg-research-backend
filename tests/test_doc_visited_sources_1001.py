"""2026-10-01 — ChatGPT's and Gemini's documents end with the sites they visited.

The owner, 2026-09-30, about to publish: "ChatGPT's documents wouldn't end with
the sources, even the Super Research ChatGPT documents. It needs to be fixed
right away in this release."

MEASURED on that run (German_Sheperd_20260930_212911): chatgpt.md held 0 links
and gemini.md 0 links, while the poll loop had tracked 68 sites for ChatGPT
(its activity panel's "Open source" links) and 90 for Gemini (the links on its
page). claude.md held 76 links under its own "## Sources" and must not change.
ChatGPT's panel reads EMPTY once the report is up, so the snapshot the document
is written from had none of its 68 left; the run keeps its own list now
(`_p2_fold_visited_sources`).

⛔⛔ ONLY PUBLIC PAGES. The tracking is read from the agents' signed-in browsers,
so it can hold the chat itself, the sandbox frame the report renders in, a
sign-in page, a Google redirect, the owner's own files. These documents are
frozen into public shares, the delivered Google Doc and NotebookLM.

Every test here goes through a function the pipeline itself calls: the per-agent
write (`extract_and_record_agent`), the regenerated write
(`_p2_regenerated_document`), the numbering funnel every write site uses
(`_document_with_sources`) and `save_meta`, whose `agents.<agent>.sourceUrls` is
the field the web numbers the Super Research document from
(`superresearch-generate.ts`, `numberSources(rData.agents)`).
"""
import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402


# ── the 09-30 shapes ─────────────────────────────────────────────────────────

#: ChatGPT's report as computer use's "Export to Markdown" left it: its
#: citations were token runs that are stripped, and it ends with a paragraph
#: naming sources with no address at all.
CHATGPT_REPORT = (
    "# German Shepherd Dog: Evidence-Based Guide to Breed, Health and Costs\n"
    "\n"
    "**Research completion date: October 1, 2026**\n"
    "\n"
    "## Health, genetics, preventive care, and ageing\n"
    "\n"
    "Hip and elbow dysplasia remain the most reported orthopaedic problems in the "
    "breed, and screening through the national registries lowers the risk.\n"
    "\n"
    "## Decision framework, recommendations, and research appendices\n"
    "\n"
    "**British Columbia, Vancouver and current costs:** Province of British "
    "Columbia, pets and tenancy.  City of Vancouver, dog licensing.  BC SPCA "
    "adoption fees and environmental guidance.\n"
)

#: Gemini's copy: numbered headings, its page furniture, no link anywhere.
GEMINI_REPORT = (
    "## German Shepherd Research Metaplan\n"
    "\n"
    "ContentsShare and export\n"
    "\n"
    "# The German Shepherd Dog: An Evidence-Based Monograph\n"
    "\n"
    "## 20. Lifetime costs\n"
    "\n"
    "Insurance, food and training together come to several thousand dollars a "
    "year in the Lower Mainland, before any orthopaedic surgery.\n"
    "\n"
    "## 21. Synthesis and Final Decision Framework\n"
    "\n"
    "Households with fenced yards and stable schedules will find the breed a "
    "loyal and rewarding partner.\n"
)

#: Claude's report: prose that names no address, then its own one sources list.
CLAUDE_LINKS = [
    "https://avsab.org/resources/position-statements/",
    "https://juneconway.com/2019/12/stratas-and-pets/",
    "https://en.wikipedia.org/wiki/German_Shepherd",
    "https://link.springer.com/article/10.1186/s40575-017-0046-4",
    "https://www.dogstrust.org.uk/downloads/life-expectancy-breeds-table-2024.pdf",
    "https://www.adventureden.ca/daycare-pricing",
]


def _claude_report(links):
    rows = "\n".join(f"{i + 1}. [Source {i + 1}]({u})" for i, u in enumerate(links))
    return (
        "# German Shepherd Dog Ownership: Evidence, Risks, Costs\n"
        "\n"
        "## 16. Decision synthesis\n"
        "\n"
        "The breed suits an experienced, active household that budgets for "
        "orthopaedic care and reward-based training from the first week.\n"
        "\n"
        "## Sources\n"
        "\n" + rows + "\n")


#: What ChatGPT's panel tracked, junk included: its own chat, the sandbox frame
#: the report renders in, a sign-in page, a Google redirect to a public page, a
#: tagged copy and an untagged duplicate of one page.
CHATGPT_TRACKED = [
    "https://chatgpt.com/c/68dc1f2e-0b7c-8003-a1b2-5f0c9d2e7a10",
    "https://www.akc.org/dog-breeds/german-shepherd-dog/?utm_source=chatgpt.com",
    "https://connector_openai_deep_research.web-sandbox.oaiusercontent.com/?app=chatgpt",
    "https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fwww.akc.org%2F",
    "https://www.google.com/url?q=https://www.ofa.org/diseases/hip-dysplasia/&sa=U&ved=2ahUKE",
    "https://www.akc.org/dog-breeds/german-shepherd-dog/",
    "https://pubmed.ncbi.nlm.nih.gov/28770095/",
    "https://en.wikipedia.org/wiki/Hip_dysplasia_(canine)",
]

#: The clean public list those eight come to, in the order first seen.
CHATGPT_ROWS = (
    "1. [akc.org/dog-breeds/german-shepherd-dog]"
    "(https://www.akc.org/dog-breeds/german-shepherd-dog/)\n"
    "2. [ofa.org/diseases/hip-dysplasia](https://www.ofa.org/diseases/hip-dysplasia/)\n"
    "3. [pubmed.ncbi.nlm.nih.gov/28770095](https://pubmed.ncbi.nlm.nih.gov/28770095/)\n"
    "4. [en.wikipedia.org/wiki/Hip_dysplasia_(canine)]"
    "(https://en.wikipedia.org/wiki/Hip_dysplasia_%28canine%29)\n"
)

#: What Gemini's page links held on 09-30, junk included: Google's own products
#: page (the real first entry), its app, a search page and an avatar.
GEMINI_TRACKED = [
    "https://www.google.ca/intl/en-GB/about/products",
    "https://gemini.google.com/app/5f0c9d2e7a10",
    "https://www.rvc.ac.uk/news-and-events/rvc-news/new-research-reveals-secrets",
    "https://www.google.com/search?q=german+shepherd+hip+dysplasia",
    "https://lh3.googleusercontent.com/a/ACg8ocK3",
    "https://pmc.ncbi.nlm.nih.gov/articles/PMC5532765/",
    "https://www.rvc.ac.uk/news-and-events/rvc-news/new-research-reveals-secrets?utm_medium=gemini",
]

GEMINI_ROWS = (
    "1. [rvc.ac.uk/news-and-events/rvc-news/new-research-reveals-secrets]"
    "(https://www.rvc.ac.uk/news-and-events/rvc-news/new-research-reveals-secrets)\n"
    "2. [pmc.ncbi.nlm.nih.gov/articles/PMC5532765](https://pmc.ncbi.nlm.nih.gov/articles/PMC5532765/)\n"
)


# ── the real write site, driven ──────────────────────────────────────────────

class _Page:
    url = "https://chatgpt.com/c/abc"


class _Browser:
    async def switch_to_page(self, page):
        return None


_EXTRACTORS = {"ChatGPT": "extract_chatgpt_response",
               "Gemini": "extract_gemini_response",
               "Claude": "extract_claude_response"}


@pytest.fixture
def run(monkeypatch, tmp_path):
    """One run: the real runtime class, the real write site and `save_meta`.
    Only the browser, the network and Firestore are stubbed."""
    runtime = research.PipelineRuntime()
    logs, saved, cloud = [], [], []
    monkeypatch.setattr(research, "_runtime", runtime, raising=False)
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)

    async def _rehost(text, label=None, **kw):
        return text

    async def _save(doc_type, content, name=None, **kw):
        saved.append((doc_type, content))
        return True

    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr(research, "_rehost_document_images", _rehost)
    monkeypatch.setattr(research, "save_document_to_firestore_with_retry", _save)
    monkeypatch.setattr(research, "_firebase_db", object())
    monkeypatch.setattr(research, "_fb_uid", "uid-1")
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_update_firestore_research", lambda rec: cloud.append(rec))
    monkeypatch.setattr(research.asyncio, "sleep", _no_sleep)

    class _Run:
        def __init__(self):
            self.runtime, self.logs, self.saved, self.cloud = runtime, logs, saved, cloud
            self.dir = tmp_path

        def poll(self, key, urls):
            """One poll-loop tick: the snapshot, then the run's own list —
            the two writes `poll_all_agents_round_robin` makes."""
            progress = {"source_urls": list(urls)}
            runtime.agent_progress_snapshots[key] = {"source_urls": list(urls)[:200]}
            research._p2_fold_visited_sources(key, progress)

        def write(self, name, report):
            async def _extract(page, **kw):
                return report
            monkeypatch.setattr(research, _EXTRACTORS[name], _extract)
            asyncio.run(research.extract_and_record_agent(
                name, _Page(), _Browser(), None, tmp_path))
            return (tmp_path / "documents" / f"{name.lower()}.md").read_text(encoding="utf-8")

        def source_urls(self, key):
            research.save_meta(tmp_path, "German Shepherd", 2)
            return cloud[-1]["agents"][key]["sourceUrls"]

    return _Run()


TAIL = "\n\n##### Sources\n\n"


class TestChatGPTAndGeminiEndWithTheSitesTheyVisited:
    def test_chatgpt_ends_with_exactly_the_clean_public_list(self, run):
        """⛔⛔ THE 09-30 CHATGPT RUN. Its panel tracked the sites while the
        research ran and reads EMPTY once the report is up — so the snapshot the
        write reads has nothing left, and only the run's own list can supply
        them. Junk never reaches the document; the redirect is followed; the
        tagged copy and its duplicate are one row."""
        run.poll("chatgpt", CHATGPT_TRACKED)
        run.poll("chatgpt", [])           # the report is up: the panel is empty
        local = run.write("ChatGPT", CHATGPT_REPORT)
        head = "# ChatGPT Deep Research\n\n" + CHATGPT_REPORT.rstrip()
        assert local == head + TAIL + CHATGPT_ROWS
        assert run.saved == [("chatgpt", local)]
        assert ("[ChatGPT] the document cites no sources itself — ending it with "
                "the 4 sites ChatGPT visited") in run.logs
        # ⛔ A visited site is no finding: a finding needs a sentence citing it.
        assert not run.runtime.agent_findings.get("chatgpt")

    def test_gemini_ends_with_exactly_the_clean_public_list(self, run):
        """Gemini's tracking stays on its page to the end, so its list comes
        off the latest snapshot (the run's own list is left empty here, so only
        the snapshot can supply it). Google's products page, the app, a search
        page and an avatar never reach the document."""
        run.runtime.agent_progress_snapshots["gemini"] = {"source_urls": GEMINI_TRACKED}
        local = run.write("Gemini", GEMINI_REPORT)
        head = "# Gemini Deep Research\n\n" + GEMINI_REPORT.rstrip()
        assert local == head + TAIL + GEMINI_ROWS
        assert ("[Gemini] the document cites no sources itself — ending it with "
                "the 2 sites Gemini visited") in run.logs
        # …and the field the web numbers from holds the same two, not the junk
        # the snapshot still carries.
        assert run.source_urls("gemini") == [
            "https://www.rvc.ac.uk/news-and-events/rvc-news/new-research-reveals-secrets",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC5532765/"]

    def test_claude_is_written_byte_for_byte_as_before(self, run):
        """⛔⛔ Claude's report ends with its own one list (76 links on 09-30). A
        list of visited sites is tracked for it too, and the document must not
        change by a byte."""
        run.poll("claude", ["https://www.akc.org/x", "https://www.ofa.org/y"])
        report = _claude_report(CLAUDE_LINKS)
        local = run.write("Claude", report)
        assert local == "# Claude Deep Research\n\n" + report

    def test_a_report_whose_own_list_holds_a_few_links_gets_no_second_list(self, run):
        """The same with only three links in its own list — fewer than the five
        that count as citing enough. Its own list is still the one list."""
        run.poll("claude", ["https://www.akc.org/x", "https://www.ofa.org/y"])
        report = _claude_report(CLAUDE_LINKS[:3])
        local = run.write("Claude", report)
        assert local == "# Claude Deep Research\n\n" + report

    def test_a_report_citing_enough_sources_itself_gets_no_visited_list(self, run):
        """Five public citations of its own: the document is numbered exactly
        as it always was, and none of the visited sites is added."""
        cited = "".join(
            f"Finding {i} about the breed's health is reported in detail at "
            f"https://journal{i}.example-vet.org/paper{i} by the registry.\n\n"
            for i in range(5))
        run.poll("chatgpt", ["https://www.akc.org/visited-only"])
        local = run.write("ChatGPT", "## Findings\n\n" + cited)
        assert "visited-only" not in local
        assert local == research._number_document_sources(
            "# ChatGPT Deep Research\n\n## Findings\n\n" + cited,
            run.runtime.agent_findings["chatgpt"])
        assert len(re.findall(r"^\d+\. \[", local, re.M)) == 5

    def test_a_titles_only_works_cited_list_is_replaced_by_the_links(self, run):
        """Gemini's export ends "Works cited" — and in a copy that lost its links
        that list is bare titles nobody can open.

        ⛔⛔ CHANGED 2026-10-01, AND ON PURPOSE. This test used to expect the
        visited sites AFTER the titles, under "Sources (numbered)": two sources
        sections, which is exactly what the owner ruled out ("don't add two
        sources like we faced last time in a Claude document"). The titles-only
        list is now REPLACED by ours, and the document reads "Sources" once."""
        report = GEMINI_REPORT + "\n## Works cited\n\n1. RVC news release.\n2. PMC article.\n"
        run.runtime.agent_progress_snapshots["gemini"] = {"source_urls": GEMINI_TRACKED}
        local = run.write("Gemini", report)
        assert local == "# Gemini Deep Research\n\n" + GEMINI_REPORT.rstrip() + TAIL + GEMINI_ROWS


class TestTheSuperResearchFieldCarriesThem:
    """`agents.<agent>.sourceUrls` is what the web numbers the Super Research
    document and the Summary from."""

    def test_chatgpt_visited_sites_reach_source_urls(self, run):
        run.poll("chatgpt", CHATGPT_TRACKED)
        run.poll("chatgpt", [])
        run.write("ChatGPT", CHATGPT_REPORT)
        assert run.source_urls("chatgpt") == [
            "https://www.akc.org/dog-breeds/german-shepherd-dog/",
            "https://www.ofa.org/diseases/hip-dysplasia/",
            "https://pubmed.ncbi.nlm.nih.gov/28770095/",
            "https://en.wikipedia.org/wiki/Hip_dysplasia_(canine)",
        ]

    def test_a_report_citing_two_links_still_hands_over_every_visited_site(self, run):
        """⛔⛔ REVIEW, 2026-10-01. A report keeping two raw links ends with those
        two rows and the visited ones in ONE numbered list — so it carries inline
        markers, and a read-back gated on "no marker" lost every visited site.
        The panel snapshot is empty for ChatGPT by then, so nothing else
        supplied them."""
        report = CHATGPT_REPORT + (
            "\nThe registry's hip data is at https://ofa.org/diseases/?utm_source=chatgpt.com "
            "and has been collected since the nineteen sixties.\n"
            "\nThe breed club's health page is https://gsdca.org/health-genetics/ for "
            "anyone choosing a breeder in North America.\n")
        run.poll("chatgpt", CHATGPT_TRACKED)
        run.poll("chatgpt", [])
        local = run.write("ChatGPT", report)
        assert len(re.findall(r"^\d+\. \[", local, re.M)) == 6
        assert ("[ChatGPT] the document cites only 2 sources itself (fewer than 5) — "
                "ending it with the 4 other sites ChatGPT visited") in run.logs
        assert run.source_urls("chatgpt") == [
            "https://ofa.org/diseases/?utm_source=chatgpt.com",
            "https://gsdca.org/health-genetics/",
            "https://www.akc.org/dog-breeds/german-shepherd-dog/",
            "https://www.ofa.org/diseases/hip-dysplasia/",
            "https://pubmed.ncbi.nlm.nih.gov/28770095/",
            "https://en.wikipedia.org/wiki/Hip_dysplasia_(canine)",
        ]

    def test_a_page_with_brackets_is_one_source_not_two(self, run):
        """⛔ REVIEW, 2026-10-01. Our row writes `(canine)` as `%28canine%29`;
        Gemini's snapshot, which lasts to the end of its run, says `(canine)`.
        Both went into one agent's `sourceUrls`, and the web gave the page two
        numbers."""
        run.runtime.agent_progress_snapshots["gemini"] = {"source_urls": [
            "https://en.wikipedia.org/wiki/Hip_dysplasia_(canine)",
            "https://www.ofa.org/diseases/"]}
        local = run.write("Gemini", GEMINI_REPORT)
        assert "Hip_dysplasia_%28canine%29" in local
        assert run.source_urls("gemini") == [
            "https://en.wikipedia.org/wiki/Hip_dysplasia_(canine)",
            "https://www.ofa.org/diseases/"]

    def test_a_cited_page_with_brackets_is_one_source_not_two(self, run):
        """The same through a citation: the prose says `(canine)` and the inline
        marker beside it `%28canine%29`, and both were read as sources."""
        report = CHATGPT_REPORT + (
            "\nThe condition is summarised for owners at "
            "https://en.wikipedia.org/wiki/Hip_dysplasia_(canine) with its history.\n")
        local = run.write("ChatGPT", report)
        assert "[\\[1\\]](https://en.wikipedia.org/wiki/Hip_dysplasia_%28canine%29)" in local
        assert run.source_urls("chatgpt") == [
            "https://en.wikipedia.org/wiki/Hip_dysplasia_(canine)"]

    def test_an_address_in_a_rows_text_is_not_read_as_a_source(self, run):
        """⛔ REVIEW, 2026-10-01. A visited row's text is the address as typed,
        so an archive link SHOWS the address it archives. Only link targets are
        read back; and a translate link to the owner's Google Doc is no public
        page at all."""
        run.poll("chatgpt", [
            "https://web.archive.org/web/2024/https://www.akc.org/x",
            "https://translate.google.com/translate?u=https://docs.google.com/document/d/1Ab/edit&hl=en",
        ])
        local = run.write("ChatGPT", CHATGPT_REPORT)
        assert "docs.google.com" not in local
        assert run.source_urls("chatgpt") == [
            "https://web.archive.org/web/2024/https://www.akc.org/x"]


class TestNeverTwice:
    def test_the_finalize_resave_writes_the_same_one_list(self, run, monkeypatch):
        """The end of Phase 2 writes every report again from its text
        (`_p2_persist_reports`), over the file the per-agent write left. Same
        document, one list — and the list is there on this write too."""
        run.poll("chatgpt", CHATGPT_TRACKED)
        run.poll("chatgpt", [])
        first = run.write("ChatGPT", CHATGPT_REPORT)
        resaved = []
        monkeypatch.setattr(research, "save_document_to_firestore",
                            lambda t, c, n=None: resaved.append((t, c)) or True)
        monkeypatch.setattr(research, "_generate_research_summary_async", lambda *a, **k: None)
        asyncio.run(research._p2_persist_reports(
            {"ChatGPT": {"text": CHATGPT_REPORT, "status": "done"}},
            run.dir, "German Shepherd", "a brief"))
        again = (run.dir / "documents" / "chatgpt.md").read_text(encoding="utf-8")
        assert again == first
        assert resaved == [("chatgpt", first)]

    def test_a_regenerated_report_read_back_from_its_file_has_one_list(self, run):
        """A kept agent's file is read back without our list
        (`_document_without_sources`), re-run, and written again: one list,
        the same rows."""
        run.poll("chatgpt", CHATGPT_TRACKED)
        local = run.write("ChatGPT", CHATGPT_REPORT)
        body = research._document_without_sources(local).partition("\n\n")[2]
        again = research._p2_regenerated_document("ChatGPT", body, "retry")
        assert again == ("# ChatGPT Deep Research (retry)\n\n" + CHATGPT_REPORT.rstrip()
                         + TAIL + CHATGPT_ROWS)

    @pytest.mark.parametrize("own", [
        "",
        "\n## Works cited\n\n1. AKC breed page.\n",
        # what an earlier build of this branch wrote: the titles, then ours
        # under the alternate title
        "\n## Works cited\n\n1. AKC breed page.\n\n##### Sources (numbered)\n\n"
        "1. [akc.org/x](https://www.akc.org/x)\n",
    ])
    def test_text_still_carrying_our_list_is_left_as_it_is(self, run, own):
        """Text that somehow still ends with our list — under either title — is
        never given a second one, even when more sites were tracked since."""
        run.poll("chatgpt", CHATGPT_TRACKED[:3])
        first = research._p2_regenerated_document("ChatGPT", CHATGPT_REPORT + own, "retry")
        assert first.count("##### Sources") == 1
        run.poll("chatgpt", CHATGPT_TRACKED)        # more sites since
        body = first.partition("\n\n")[2]
        again = research._p2_regenerated_document("ChatGPT", body, "regenerated")
        assert again.partition("\n\n")[2] == body


# ── exactly one sources section (owner, 2026-10-01) ───────────────────────────
#
# "Don't add two sources like we faced last time in a Claude document." MEASURED
# on the real 09-30 ChatGPT file before this change: the numbering funnel
# returned TWO sections — ChatGPT's own "**Cited-source bibliography.**" block
# (six "**Category:** names…" paragraphs, not one link), then our "##### Sources"
# with the links.

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "documents_0930"
#: The owner's real 09-30 files, byte for byte (German_Sheperd_20260930_212911).
CHATGPT_0930 = (FIXTURES / "chatgpt.md").read_text(encoding="utf-8")
CLAUDE_0930 = (FIXTURES / "claude.md").read_text(encoding="utf-8")

#: The closed word set a sources section is titled with — PORTED here rather
#: than read from the code, so the count below does not ask the code under test
#: what a section is. ⭐ Wave 14: "prioritized" (ChatGPT's 10-01 "**Prioritized
#: sources.**").
_W = (r"(?:(?:key|main|principal|selected|cited-source|cited|full|further|additional"
      r"|prioritized|list[ \t]+of)[ \t]+)?"
      r"(?:sources?|references?|citations?|bibliography|works[ \t]+cited"
      r"|reference[ \t]+list)"
      r"(?:[ \t]+(?:cited|consulted|used)"
      r"|[ \t]+and[ \t]+(?:further[ \t]+reading|notes|references|sources))?")
#: A paragraph lead's words are the PLURAL ones: "Source: OFA registry" is a
#: table caption, not a section.
_W_LEAD = _W.replace("sources?|references?|citations?", "sources|references|citations")
assert _W_LEAD != _W
#: A heading's section number: 14, 14.2, IV., A.
_NUM = r"(?:(?:\d{1,3}(?:\.\d{1,3})*[.)]?|(?:[ivxlc]{1,6}|[a-z])[.)])[ \t]+)?"
_EM = r"(?:\*\*|__|\*|_)?"
#: Every heading, bold lead or plain lead that titles a sources section —
#: our own alternate title included, so a kept block beside ours counts as two.
#: A heading may wrap its title in emphasis and close with a `#` run.
SECTION_TITLE_RE = re.compile(
    r"^(?:#{1,6}[ \t]+" + _EM + _NUM + _W + r"(?:[ \t]+\(numbered\))?" + _EM
    + r"[ \t]*[.:]?(?:[ \t]+#+)?[ \t]*$"
    r"|(?:\*\*|__)" + _W_LEAD + r"[.:]?(?:\*\*|__)[.:]?(?:[ \t]|$)"
    r"|" + _W_LEAD + r":)",
    re.IGNORECASE | re.MULTILINE)


def sources_sections(doc):
    return [m.group(0).strip() for m in SECTION_TITLE_RE.finditer(doc)]


ONE_ROW = "1. [akc.org/dog-breeds](https://www.akc.org/dog-breeds/)\n"
BODY = "# ChatGPT Deep Research\n\n## Findings\n\nThe breed is popular in Canada.\n"

#: A report's own trailing section with no public link, in each shape the rule
#: names. Each is appended to BODY after a blank line.
LINKLESS_OWN = {
    "gemini-empty-sources": "## Sources\n",
    "works-cited-titles": "## Works cited\n\n1. AKC breed page.\n2. OFA hip dysplasia.\n",
    "numbered-key-sources": "## 14. Key sources\n\n- AKC, *German Shepherd Dog*.\n"
                            "- OFA, *Hip dysplasia*.\n",
    "bold-references": "**References:** AKC, *German Shepherd Dog*; OFA, *Hip dysplasia*.\n",
    "bold-then-colon": "**Selected sources**: AKC breed page; OFA hip page.\n",
    # ⛔ a LIST under the title: a prose paragraph after a lead ends the match
    # (see the kept shapes below), so a sources lead never cuts the report
    "bold-no-stop-then-list": "**Sources consulted**\n\n- AKC breed page\n- OFA hip page\n",
    "plain-references": "References: AKC, German Shepherd Dog; OFA, Hip dysplasia.\n",
    "only-a-private-link": "## Sources\n\n1. [This conversation](https://chatgpt.com/c/68dc1f2e)\n",
    # the heading's title read past emphasis, a closing `#` run and a roman or
    # letter section number
    "bold-in-the-heading": "## **References**\n\n1. AKC breed page.\n",
    "italic-in-the-heading": "## *Works cited*\n\n1. AKC breed page.\n",
    "closing-hashes": "## Sources ##\n\n- AKC breed page\n",
    "roman-numbered": "## IV. References\n\n1. AKC breed page.\n",
    "letter-numbered": "## A. Sources\n\n- AKC breed page\n",
    # the rest of the closed set
    "underscore-bold": "__Sources__\n\n- AKC breed page\n- OFA hip page\n",
    "reference-list": "## Reference list\n\n1. AKC breed page.\n",
    "list-of-sources": "**List of sources**\n\n- AKC breed page\n",
    "and-further-reading": "## Sources and further reading\n\n- AKC breed page\n",
    "bibliography-categories": "**Cited-source bibliography.** The principal sources.\n\n"
                               "**Health:** OFA; AKC.\n\n**Behaviour:** AVSAB.\n",
}


def _with_visited(md, visited=("https://www.akc.org/dog-breeds/",)):
    return research._document_with_sources(md, visited=list(visited), label="ChatGPT")


CHATGPT_HEADER = "# ChatGPT Deep Research\n\n"
BIBLIOGRAPHY = "**Cited-source bibliography.**"


def _chatgpt_0930_variant(kind):
    """The owner's real 09-30 ChatGPT file, changed in one way a report plausibly
    is (the reviewer's three shapes, 2026-10-01)."""
    md = CHATGPT_0930
    if kind == "caption-under-the-ledger":
        # a table caption under its "Condensed evidence ledger"
        at = md.index("\n\n**Most important unresolved")
        return md[:at] + "\n\nSource: OFA program rules; VetCompass cohort." + md[at:]
    if kind == "bold-titled-with-a-caption":
        # its `##` headings written as bold leads (the bold-titled ChatGPT shape
        # save_meta's fallback exists for), and a caption after its first table
        md = re.sub(r"^## (.+)$", r"**\1**", md, flags=re.M)
        at = md.index("\n\n", md.index("| Rating |"))
        return md[:at] + "\n\nSource: AKC breed standard (2024)." + md[at:]
    assert kind == "recommendation-after-the-bibliography"
    start = md.index("**Final recommendation.**")
    end = md.index("\n\n", start)
    return md[:start] + md[end + 2:].rstrip() + "\n\n" + md[start:end] + "\n"


def _citing(n):
    """`n` paragraphs, each citing its own public page in its prose."""
    return "".join(f"Finding {i} on the breed's hips is reported at "
                   f"https://www.site{i}.org/paper{i} in full.\n\n" for i in range(n))


MARKER_RE = re.compile(r"\[\\\[\d{1,3}\\\]\]\(")


class TestExactlyOneSourcesSection:
    def test_the_real_0930_chatgpt_document_ends_with_one_sources_section(self, run):
        """⛔⛔ THE OWNER'S FILE, THROUGH THE REAL PER-AGENT WRITE. Its own block
        goes, our list takes its place, and every byte of the report before the
        block is as it was. save_meta still reads our rows back."""
        header = "# ChatGPT Deep Research\n\n"
        assert CHATGPT_0930.startswith(header)
        # the input's one section is ChatGPT's own, with no link in it
        assert sources_sections(CHATGPT_0930) == ["**Cited-source bibliography.**"]
        block = CHATGPT_0930.index("**Cited-source bibliography.**")
        assert "](http" not in CHATGPT_0930[block:]
        run.poll("chatgpt", CHATGPT_TRACKED)
        run.poll("chatgpt", [])
        local = run.write("ChatGPT", CHATGPT_0930[len(header):])
        assert local == CHATGPT_0930[:block].rstrip() + TAIL + CHATGPT_ROWS
        assert sources_sections(local) == ["##### Sources"]
        assert "Cited-source bibliography" not in local
        assert "**Breed standards, history and screening:**" not in local
        assert ("[ChatGPT] the report's own sources section holds no link — "
                "replaced by this list, so the document ends with one") in run.logs
        assert research._strip_numbered_sources_section(local) == CHATGPT_0930[:block].rstrip()
        assert run.source_urls("chatgpt") == [
            "https://www.akc.org/dog-breeds/german-shepherd-dog/",
            "https://www.ofa.org/diseases/hip-dysplasia/",
            "https://pubmed.ncbi.nlm.nih.gov/28770095/",
            "https://en.wikipedia.org/wiki/Hip_dysplasia_(canine)",
        ]

    @pytest.mark.parametrize("kind", ["caption-under-the-ledger",
                                      "bold-titled-with-a-caption"])
    def test_a_caption_in_the_real_file_removes_nothing_but_the_bibliography(
            self, run, kind):
        """⛔⛔ REVIEW BLOCKER, 2026-10-01. A paragraph led by "Source:" opened
        the report's "own sources section", which ran to the end of the file and
        was cut: one caption under the evidence ledger took 5,566 characters,
        "**Final recommendation.**" with them, and in the bold-titled shape a
        caption after the first table took 84% of the report. Only the
        bibliography goes now; every byte before it stays."""
        md = _chatgpt_0930_variant(kind)
        run.poll("chatgpt", CHATGPT_TRACKED)
        local = run.write("ChatGPT", md[len(CHATGPT_HEADER):])
        assert local == md[:md.index(BIBLIOGRAPHY)].rstrip() + TAIL + CHATGPT_ROWS
        assert "**Final recommendation.**" in local
        assert sources_sections(local) == ["##### Sources"]

    def test_a_bibliography_the_report_goes_on_after_is_never_cut(self, run):
        """⛔⛔ The same blocker's third shape: the real file with its "**Final
        recommendation.**" after the bibliography. The bibliography is not the
        trailing section any more, so nothing is removed and ours is added after
        the report — two sections in this shape, and that is the price of never
        cutting a report: losing the recommendation is worse."""
        md = _chatgpt_0930_variant("recommendation-after-the-bibliography")
        assert md.rstrip().endswith("contingency plans before they are needed.")
        run.poll("chatgpt", CHATGPT_TRACKED)
        local = run.write("ChatGPT", md[len(CHATGPT_HEADER):])
        assert local == md.rstrip() + TAIL + CHATGPT_ROWS

    @pytest.mark.parametrize("caption", [
        "Source: OFA registry, 2024.", "**Source:** OFA registry, 2024.",
        "Sources: OFA registry, 2024.", "**Sources:** OFA registry, 2024."])
    @pytest.mark.parametrize("head", ["## Health", "**Health.**"])
    @pytest.mark.parametrize("n", [3, 6])
    @pytest.mark.parametrize("visited", [None, ["https://www.akc.org/dog-breeds/"]],
                             ids=["no-visited", "visited"])
    def test_a_caption_never_stops_the_citations_after_it_being_numbered(
            self, caption, head, n, visited, monkeypatch):
        """⛔ REVIEW, 2026-10-01 (the blocker's other face). With the caption as
        the start of an "own section", every address cited after it counted as
        LISTED: no number, and its links kept the list out — a report citing
        public pages ended with no sources at all. Each citation keeps its number
        and its row, and not a byte of the report goes."""
        monkeypatch.setattr(research, "log", lambda *a, **k: None)
        md = (CHATGPT_HEADER + head + "\n\n| Test | Result |\n|---|---|\n| Hips | Fair |\n\n"
              + caption + "\n\n" + _citing(n))
        out = research._document_with_sources(md, visited=visited, label="ChatGPT")
        assert len(MARKER_RE.findall(out)) == n
        rows = n + (1 if visited and n < 5 else 0)
        assert out.count(TAIL) == 1
        assert len(re.findall(r"^\d+\. \[", out.split(TAIL)[1], re.M)) == rows
        assert research._document_without_sources(out) == md.rstrip()

    @pytest.mark.parametrize("own", [
        "**Cited-source bibliography.** The principal sources.\n\n**Health:** OFA; AKC.\n",
        "## References\n\n1. OFA hip registry.\n2. AKC breed standard.\n",
        "## Sources\n\n- BNEF, *Battery pack price survey*\n",
    ], ids=["bold-bibliography", "references-heading", "sources-heading-titles"])
    @pytest.mark.parametrize("visited", [None, ["https://www.akc.org/dog-breeds/"]],
                             ids=["no-visited", "visited"])
    def test_a_report_citing_five_sources_also_ends_with_one_section(
            self, own, visited, monkeypatch):
        """⛔ REVIEW, 2026-10-01. Five citations of its own, so no visited site is
        added — and the cut used to run only when one was, so the report's own
        link-less section stayed above our numbered list: two sections. It is
        replaced whenever a list is added, visited sites or not."""
        monkeypatch.setattr(research, "log", lambda *a, **k: None)
        body = CHATGPT_HEADER + "## Findings\n\n" + _citing(5)
        out = research._document_with_sources(body + own, visited=visited, label="ChatGPT")
        assert sources_sections(out) == ["##### Sources"]
        assert len(MARKER_RE.findall(out)) == 5
        assert len(re.findall(r"^\d+\. \[", out, re.M)) == 5
        assert research._document_without_sources(out) == body.rstrip()

    def test_two_citations_and_a_linkless_references_line_end_with_one_section(
            self, monkeypatch):
        """Two citations of its own and a final "**References:** AKC; OFA." with
        no link: the cut and the visited rows run together. The line is replaced,
        and the one list holds the two cited rows first, then the visited site.
        ⛔ The own section's links are read from THAT section: the prose's two
        links must not count as the section holding links."""
        monkeypatch.setattr(research, "log", lambda *a, **k: None)
        body = CHATGPT_HEADER + "## Findings\n\n" + _citing(2)
        out = _with_visited(body + "**References:** AKC; OFA.\n")
        assert sources_sections(out) == ["##### Sources"]
        assert re.findall(r"^\d+\. \[[^\]]*\]\(([^)]+)\)", out, re.M) == [
            "https://www.site0.org/paper0", "https://www.site1.org/paper1",
            "https://www.akc.org/dog-breeds/"]
        assert research._document_without_sources(out) == body.rstrip()

    def test_the_real_0930_claude_document_keeps_its_one_list(self, run):
        """⛔⛔ Claude's own "## Sources" holds 76 links: it is the one list,
        sites tracked or not.

        ⭐ CHANGED IN WAVE 14, AND ON PURPOSE. This test used to say the
        document does not change by a byte. The owner, 2026-10-01: footnotes
        "should be there for all the documents of Phase 1 and Phase 2" — so
        Claude's 110 numbers are now links to their own rows, and every other
        byte is as it was (pinned pair by pair in
        `tests/test_footnotes_1001.py`)."""
        assert len(re.findall(r"^\d+\. \[[^\]]+\]\(https?://", CLAUDE_0930, re.M)) == 76
        run.poll("claude", CHATGPT_TRACKED)
        local = run.write("Claude", CLAUDE_0930[len("# Claude Deep Research\n\n"):])
        assert len(MARKER_RE.findall(local)) == 110
        assert re.sub(r"\[\\\[(\d+)\\\]\]\([^()\s]*\)", r"\\[\1\\]", local) == CLAUDE_0930
        assert sources_sections(local) == ["## Sources"]
        assert _with_visited(CLAUDE_0930, CHATGPT_TRACKED) == local

    def test_a_gemini_document_ending_with_an_empty_sources_heading(self, run):
        """Gemini-shaped, through the real write: "## Sources" with nothing
        under it is replaced, not followed."""
        run.runtime.agent_progress_snapshots["gemini"] = {"source_urls": GEMINI_TRACKED}
        local = run.write("Gemini", GEMINI_REPORT + "\n## Sources\n")
        assert local == "# Gemini Deep Research\n\n" + GEMINI_REPORT.rstrip() + TAIL + GEMINI_ROWS
        assert sources_sections(local) == ["##### Sources"]

    @pytest.mark.parametrize("shape", sorted(LINKLESS_OWN))
    def test_a_linkless_own_section_is_replaced_by_ours(self, shape, monkeypatch):
        monkeypatch.setattr(research, "log", lambda *a, **k: None)
        md = BODY + "\n" + LINKLESS_OWN[shape]
        assert len(sources_sections(md)) == 1      # the shape IS a section
        out = _with_visited(md)
        assert out == BODY.rstrip() + TAIL + ONE_ROW
        assert sources_sections(out) == ["##### Sources"]

    def test_a_lead_on_the_line_right_under_the_last_heading(self, monkeypatch):
        """No blank line between the last heading and the lead: the lead is
        still its paragraph's first line, because paragraphs are read from the
        END of that heading. Only the lead's section goes; the heading stays."""
        monkeypatch.setattr(research, "log", lambda *a, **k: None)
        md = BODY + "\n## Appendices\n**References:** AKC, *German Shepherd Dog*; OFA.\n"
        out = _with_visited(md)
        assert out == BODY + "\n## Appendices" + TAIL + ONE_ROW
        assert sources_sections(out) == ["##### Sources"]

    @pytest.mark.parametrize("own", [
        "**References:** [AKC](https://www.akc.org/dog-breeds/german-shepherd-dog/); "
        "[OFA](https://www.ofa.org/diseases/hip-dysplasia/).\n",
        "## Key sources\n\n- https://www.akc.org/dog-breeds/german-shepherd-dog/\n"
        "- https://pubmed.ncbi.nlm.nih.gov/28770095/\n",
        "References: https://www.akc.org/dog-breeds/german-shepherd-dog/\n",
        # Claude's shape: its own numbered "## Sources" of links, fewer than five
        "## Sources\n\n1. [AKC](https://www.akc.org/dog-breeds/german-shepherd-dog/)\n"
        "2. [OFA](https://www.ofa.org/diseases/hip-dysplasia/)\n",
        # a bibliography lead whose entries are links
        "**Works cited**\n\nAKC. https://www.akc.org/dog-breeds/german-shepherd-dog/\n\n"
        "OFA. https://www.ofa.org/diseases/hip-dysplasia/\n",
    ], ids=["bold-references-links", "key-sources-links", "plain-references-link",
            "claude-shaped-sources", "works-cited-link-paragraphs"])
    def test_an_own_section_holding_links_is_untouched(self, own, monkeypatch):
        """Fewer than five links, so only its being the report's own section with
        a public link keeps the visited list out — and nothing is replaced."""
        monkeypatch.setattr(research, "log", lambda *a, **k: None)
        md = BODY + "\n" + own
        assert _with_visited(md, CHATGPT_TRACKED) == md

    @pytest.mark.parametrize("md", [
        BODY + "\n## Sources of funding\n\nThe registry is funded by breeders.\n"
        "\n## Conclusion\n\nA fine breed for an active household.\n",
        BODY + "\n## Sources\n\nAKC breed page; OFA.\n"
        "\n## Conclusion\n\nA fine breed for an active household.\n",
        BODY + "\n**Sources:** the AKC and the OFA agree on the breed's health.\n"
        "\n## Conclusion\n\nA fine breed for an active household.\n",
        BODY + "\n## Sources of uncertainty\n\nThe registry data are self-reported.\n",
        BODY + "\nReferences to the breed standard: the FCI wrote it in 1899.\n",
        BODY + "\nThe breed club publishes its data openly; see its\n"
        "**Selected references** page for the full list.\n",
        BODY + "\nThe breed club publishes its data openly; it says\n"
        "**Selected references:** the club's page lists them all.\n",
        # ⛔⛔ the review blocker's shapes: each used to delete itself and
        # everything after it
        BODY + "\n**References:** ask the breeder for two previous puppy buyers.\n"
        "\n**Contract:** get the return clause in writing.\n",
        BODY + "\nReferences: ask the breeder for two previous buyers.\n"
        "\nInsurance: get a quote before pickup.\n",
        BODY + "\n1. Health: ask for the OFA results.\n"
        "\n2. References: ask for two previous buyers.\n"
        "\n3. Insurance: get a quote before pickup.\n",
        BODY + "\nReference: FCI standard No. 166.\n"
        "\nThe breed was first shown in 1882.\n",
        BODY + "\n**Selected references** from the club are worth reading.\n"
        "\nThe club also runs health clinics.\n",
        BODY + "\n**References:** ask the breeder for two previous puppy buyers:\n"
        "\n- a name\n- a phone number\n",
        BODY + "\n**Sources:**\n\n**Breeders:** the club's list.\n"
        "\n**Rescues:** the regional shelter.\n",
        BODY + "\n**Sources consulted**\n\nAKC breed page; OFA hip page.\n",
        BODY + "\n**Cited-source bibliography.** The principal sources.\n"
        "\n**Health:** OFA; AKC.\n\nThis report is not veterinary advice.\n",
        BODY + "\n**Cited-source bibliography.** The principal sources.\n"
        "\n**Health:** OFA; AKC.\n\n**Final recommendation.** A fine breed.\n",
        # the last paragraph, and still no section: a singular caption under
        # the report's last table, and bold emphasis in running prose
        BODY + "\n| Test | Result |\n|---|---|\n| Hips | Fair |\n"
        "\nSource: OFA registry, 2024.\n",
        BODY + "\n**Selected references** from the club are worth reading.\n",
    ], ids=["sources-of-funding", "sources-mid-report", "bold-sources-mid-report",
            "last-heading-sources-of", "plain-references-to", "bold-on-a-wrapped-line",
            "lead-on-a-wrapped-line", "breeder-references-then-contract",
            "plain-references-then-insurance", "numbered-references-in-a-loose-list",
            "singular-reference", "selected-references-running-prose",
            "references-line-then-a-list", "bare-sources-then-bold-labels",
            "sources-consulted-then-prose", "bibliography-then-a-disclaimer",
            "bibliography-then-a-recommendation", "table-caption-at-the-end",
            "running-prose-bold-at-the-end"])
    def test_a_section_like_title_that_is_not_the_trailing_section_is_untouched(
            self, md, monkeypatch):
        """Only the TRAILING section, and only a title in the closed set. A
        section ABOUT sources, or a sources section with the report going on
        after it, stays; ours is added at the end as for any report.

        ⛔⛔ AND A PARAGRAPH LEAD NEVER CUTS THE REPORT (review blocker,
        2026-10-01). Only a bold or plain lead in the PLURAL set counts, and the
        section it opens must be nothing but source entries to the end of the
        file — a list, a paragraph holding a link, or (after a lead naming a
        bibliography) a "**Category:**" paragraph. A bare "References:" with words
        after it must be the last paragraph. Anything else after it — prose, a
        pseudo-heading such as "**Final recommendation.**", the checklist's
        "**Contract:**" — and nothing is removed."""
        monkeypatch.setattr(research, "log", lambda *a, **k: None)
        assert _with_visited(md) == md.rstrip() + TAIL + ONE_ROW

    @pytest.mark.parametrize(
        "md", [CHATGPT_0930, CLAUDE_0930]
        + [BODY + "\n" + LINKLESS_OWN[k] for k in sorted(LINKLESS_OWN)],
        ids=["chatgpt-0930", "claude-0930"] + sorted(LINKLESS_OWN))
    def test_running_twice_is_running_once(self, md, monkeypatch):
        monkeypatch.setattr(research, "log", lambda *a, **k: None)
        once = _with_visited(md, CHATGPT_TRACKED)
        twice = _with_visited(once, CHATGPT_TRACKED + ["https://www.akc.org/tracked-since"])
        assert twice == once
        assert len(sources_sections(once)) == 1


# ── the gate: only public pages, through the numbering funnel ─────────────────

#: Every shape that must never be listed. Each is offered beside one public
#: page, so a list that is empty for another reason cannot pass.
NEVER_LISTED = [
    "https://chatgpt.com/c/68dc1f2e",                          # the chat itself
    "https://chatgpt.com/g/g-abc/c/68dc1f2e",
    "https://chat.openai.com/c/abc",
    "https://files.oaiusercontent.com/file-abc?se=2026&sig=x",  # user content
    "https://gemini.google.com/app/5f0c9d2e7a10",
    "https://claude.ai/chat/1b2c",
    "https://notebooklm.google.com/notebook/abc",
    "https://accounts.google.com/v3/signin/identifier",        # sign-in
    "https://login.microsoftonline.com/common/oauth2",
    "https://www.nytimes.com/login",
    "https://consent.google.com/ml?continue=https://www.google.com/&gl=CA",
    "https://consent.youtube.com/m?gl=CA&hl=en",
    "https://www.google.com/search?q=german+shepherd",          # search pages
    "https://www.bing.com/search?q=gsd",
    "https://www.youtube.com/results?search_query=gsd",
    "https://www.google.com/url?q=https://docs.google.com/document/d/1Ab/edit",
    "https://docs.google.com/document/d/1Ab/edit",              # owner's files
    "https://drive.usercontent.google.com/download?id=1abc",
    "https://lh3.googleusercontent.com/a/ACg8ocK",
    "https://chat.google.com/room/AAAA",
    "https://console.cloud.google.com/home/dashboard?project=dg-research-prod",
    "https://myactivity.google.com/product/gemini",
    "https://claude.site/artifacts/1234",
    "https://abc.claudeusercontent.com/x",
    "https://abc.scf.usercontent.goog/frame",
    "https://distributedglobal.atlassian.net/browse/DGOPS-8583",
    "https://www.notion.so/dgworkspace/Plan-123",
    "https://teams.microsoft.com/l/meetup-join/abc",
    "https://platform.openai.com/settings/organization/api-keys",
    "https://github.com/settings/profile",
    "https://www.dropbox.com/scl/fi/abc/file.pdf?rlkey=xyz&dl=0",
    "https://example-cdn.org/report.pdf?X-Amz-Signature=abc",  # secrets
    "https://news.example.org/a?token=abc123",
    "https://news.example.org/a?x=eyJhbGciOiJIUzI1.eyJzdWIiOiIx.sig",
    "http://127.0.0.1:8080/x",                                 # local addresses
    "http://127.1/",
    "http://[::1]:3000/x",
    "http://192.168.1.10/admin",
    "https://intranet.corp/policies",
    "https://printer.lan/",
    "https://user:pw@news.example.org/a",
    "https://translate.google.com/translate?u=https://docs.google.com/document/d/1Ab/edit",
    "data:text/html,hello",
    "blob:https://chatgpt.com/abc",
    "about:blank",
]


@pytest.mark.parametrize("bad", NEVER_LISTED)
def test_a_private_or_junk_address_is_never_listed(bad, monkeypatch):
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    md = "# ChatGPT Deep Research\n\n## Findings\n\nThe breed is popular in Canada.\n"
    out = research._document_with_sources(
        md, visited=[bad, "https://www.akc.org/dog-breeds/"], label="ChatGPT")
    assert out == md.rstrip() + TAIL + "1. [akc.org/dog-breeds](https://www.akc.org/dog-breeds/)\n"


def test_tracking_keys_and_the_fragment_come_off_a_listed_address(monkeypatch):
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    out = research._document_with_sources(
        "## Findings\n\nText.\n", label="ChatGPT", visited=[
            "https://www.akc.org/a?utm_source=chatgpt.com&page=2&fbclid=x&gclid=y&ref=z#top"])
    assert out.endswith("(https://www.akc.org/a?page=2)\n")


def test_the_poll_loop_folds_every_tick_into_the_runs_own_list():
    """SOURCE PIN — the round-robin cannot be executed here. It must add each
    tick's tracking to the run's own list, which never shrinks; the snapshot
    beside it is replaced every tick."""
    src = code_only_deep(research.poll_all_agents_round_robin)
    assert src.count("_p2_fold_visited_sources(agent_key, progress)") == 1
    assert (src.index("_runtime.agent_progress_snapshots[agent_key] =")
            < src.index("_p2_fold_visited_sources(agent_key, progress)"))


def test_the_runs_list_never_shrinks_and_starts_empty_each_run(monkeypatch):
    runtime = research.PipelineRuntime()
    monkeypatch.setattr(research, "_runtime", runtime, raising=False)
    research._p2_fold_visited_sources("chatgpt", {"source_urls": ["https://www.akc.org/a"]})
    research._p2_fold_visited_sources("chatgpt", {"source_urls": []})
    research._p2_fold_visited_sources("chatgpt", {"source_items": [{"url": "https://www.ofa.org/b"}]})
    assert research._p2_visited_sources("chatgpt") == [
        "https://www.akc.org/a", "https://www.ofa.org/b"]
    runtime.reset()
    assert research._p2_visited_sources("chatgpt") == []
