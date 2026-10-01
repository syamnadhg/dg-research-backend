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
import json
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

    def test_a_titles_only_works_cited_list_is_followed_by_the_links(self, run):
        """Gemini's export ends "Works cited" — and in a copy that lost its links
        that list is bare titles nobody can open. The visited sites follow it,
        under the alternate title so the document does not read "Sources" twice."""
        report = GEMINI_REPORT + "\n## Works cited\n\n1. RVC news release.\n2. PMC article.\n"
        run.runtime.agent_progress_snapshots["gemini"] = {"source_urls": GEMINI_TRACKED}
        local = run.write("Gemini", report)
        assert local == ("# Gemini Deep Research\n\n" + report.rstrip()
                         + "\n\n##### Sources (numbered)\n\n" + GEMINI_ROWS)


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
        monkeypatch.setattr(research, "_refresh_research_title_async", lambda *a, **k: None)
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

    @pytest.mark.parametrize("own", ["", "\n## Works cited\n\n1. AKC breed page.\n"])
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
