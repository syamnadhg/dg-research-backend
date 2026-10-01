"""Wave 14 · footnotes in the Phase 1 and Phase 2 documents (Claude and the brief).

The owner, 2026-10-01: "ChatGPT and Claude documents produced by a Super
Research run don't have footnotes. It needs to be an openable reference link in
between the document — the links of the sources. … They should be there for all
the documents of Phase 1 and Phase 2."

A footnote is the backend's own marker, `[\\[n\\]](url)`, which the web renders
as an accent "[n]" opening the source in a new tab (the scope rendered it).

MEASURED on the saved files before this change:
  • Claude 10-01: 164 escaped numbers `\\[n\\]` (52 distinct) against 52 rows of
    its own "## Sources" (48 `[title](url)`, 4 `<url>`); 09-30: 110 against 76.
    None was a link. The crash-retry read-back removed every number (9,905
    characters) and on the 09-30 shape Claude's whole list too (18,774);
    `save_meta`'s strip removed the 09-30 list (10,144).
  • The brief 10-01: 12 chips, 11 addresses, three "+2", no number, no list.
  • ChatGPT 10-01: TWO sources sections — its own "**Prioritized sources.**"
    (fifteen names, no link) and ours under it.

Every test goes through a function the pipeline calls: the per-agent write
(`extract_and_record_agent`), the finalize re-save (`_p2_persist_reports`), the
crash-retry read-back (`_p2_restorable_agents`), the regenerated write
(`_p2_regenerated_document`), `save_meta`, `run_pipeline`'s brief writes and the
real `save_document_to_firestore`. Only the browser, the network and Firestore
are stubbed; Firestore records what it is handed.

⛔ Expected values are read with this file's OWN parsers (rows, markers), never
by asking the code under test what a row or a marker is.
"""
import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
D1001 = FIX / "documents_1001"
#: The owner's real 10-01 files, byte for byte (Jev_TypeSafe_20261001_064737).
CLAUDE_1001 = (D1001 / "claude.md").read_text(encoding="utf-8")
BRIEF_1001 = (D1001 / "brief.md").read_text(encoding="utf-8")
CHATGPT_1001 = (D1001 / "chatgpt.md").read_text(encoding="utf-8")
#: …and the 09-30 Claude file (German_Sheperd_20260930_212911).
CLAUDE_0930 = (FIX / "documents_0930" / "claude.md").read_text(encoding="utf-8")
#: What computer use's download handed over: the file minus our header.
CLAUDE_HEADER = "# Claude Deep Research\n\n"
BRIEF_HEADER = "# Research Brief\n\n"
#: The web-render goldens: what the real writes produce, read by the web's
#: `DocumentMarkdown` test (dg-research tests/unit/footnotesRender.test.tsx).
GOLDEN = D1001 / "footnoted"

MARKER_RE = re.compile(r"\[\\\[(\d{1,3})\\\]\]\(([^()\s]*)\)")
#: An escaped number that is not a link's text.
PLAIN_RE = re.compile(r"(?<![\[\\])\\\[(\d{1,3})\\\](?!\]\()")
TAIL = "\n\n##### Sources\n\n"


def own_rows(doc):
    """{n: address} of the rows under the document's LAST "## Sources" — this
    file's own reading, in both of Claude's row forms."""
    tail = doc[doc.rindex("\n## Sources\n"):]
    rows = {}
    for m in re.finditer(r"^(\d+)\. (?:\[(?:\\.|[^\]\\])*\]\(([^)\s]+)\)|<([^>\s]+)>)",
                         tail, re.M):
        rows[int(m.group(1))] = m.group(2) or m.group(3)
    return rows


def body_of(doc):
    return doc[:doc.rindex("\n## Sources\n")]


def unlink(doc):
    """Our markers turned back into the agent's `\\[n\\]` — this file's own way."""
    return MARKER_RE.sub(lambda m: "\\[%s\\]" % m.group(1), doc)


# ── stubs: the browser, the network, Firestore ───────────────────────────────

class _Ref:
    def __init__(self, sink, path):
        self.sink, self.path = sink, path

    def collection(self, name):
        return _Ref(self.sink, f"{self.path}/{name}")

    def document(self, name):
        return _Ref(self.sink, f"{self.path}/{name}")

    def set(self, data, merge=False):
        self.sink.append((self.path, dict(data)))


class _Db:
    def __init__(self, sink):
        self.sink = sink

    def collection(self, name):
        return _Ref(self.sink, name)


def _firestore(monkeypatch):
    """The REAL `save_document_to_firestore` over a database that records."""
    sink = []
    monkeypatch.setattr(research, "_firebase_db", _Db(sink))
    monkeypatch.setattr(research, "_fb_uid", "uid-1")
    monkeypatch.setattr(research, "_fb_research_id", "rid-1")
    monkeypatch.setattr(research, "_be_payload", lambda d: dict(d))
    monkeypatch.setattr(research, "_grpc_write_with_heal", lambda op, what=None, **k: op())
    return sink


def documents_written(sink, doc_type):
    return [d["content"] for p, d in sink if p.endswith(f"/documents/{doc_type}")]


class _Page:
    url = "https://claude.ai/chat/abc"


class _Browser:
    async def switch_to_page(self, page):
        return None


_EXTRACTORS = {"ChatGPT": "extract_chatgpt_response", "Claude": "extract_claude_response"}


@pytest.fixture
def run(monkeypatch, tmp_path):
    runtime = research.PipelineRuntime()
    logs, cloud = [], []
    monkeypatch.setattr(research, "_runtime", runtime, raising=False)
    monkeypatch.setattr(research, "log", lambda msg, *a, **k: logs.append(str(msg)))
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)

    async def _rehost(text, label=None, **kw):
        return text

    async def _no_sleep(*a, **k):
        return None

    sink = _firestore(monkeypatch)
    monkeypatch.setattr(research, "_rehost_document_images", _rehost)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_update_firestore_research", lambda rec: cloud.append(rec))
    monkeypatch.setattr(research.asyncio, "sleep", _no_sleep)

    class _Run:
        def __init__(self):
            self.runtime, self.logs, self.sink, self.cloud = runtime, logs, sink, cloud
            self.dir = tmp_path

        def poll(self, key, urls):
            runtime.agent_progress_snapshots[key] = {"source_urls": list(urls)[:200]}
            research._p2_fold_visited_sources(key, {"source_urls": list(urls)})

        def write(self, name, report):
            async def _extract(page, **kw):
                return report
            monkeypatch.setattr(research, _EXTRACTORS[name], _extract)
            asyncio.run(research.extract_and_record_agent(
                name, _Page(), _Browser(), None, tmp_path))
            return (tmp_path / "documents" / f"{name.lower()}.md").read_text(encoding="utf-8")

        def meta(self, key):
            research.save_meta(tmp_path, "Jev", 2)
            return cloud[-1]["agents"][key]

    return _Run()


# ══ 1. Claude: its own numbers, linked to its own rows ════════════════════════

#: Exact pairs, read off the 10-01 file by eye: row 1, a `<url>` row (5), both
#: halves of two back-to-back pairs — one in prose, one in a table cell — and a
#: number in a table cell after inline code.
PAIRS_1001 = [
    "(Noul).[\\[1\\]](https://docs.typesafe.ai/models)"
    "[\\[5\\]](https://docs.typesafe.ai/introduction) Type",
    "waitlist[\\[6\\]](https://typesafe.ai/blog/introducing-system-one-models-and-jev)"
    "[\\[9\\]](https://runtimewire.com/article/diogo-almeida-typesafe-jev-40m-seed-pong) |",
    "`jev-1.13.0`[\\[13\\]](https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook) |",
]
PAIRS_0930 = [
    "(submission-biased)[\\[5\\]](https://link.springer.com/article/10.1186/s40575-017-0046-4)"
    "[\\[14\\]](https://www.ufaw.org.uk/dogs/german-shepherd-hip-dysplasia) |",
]


@pytest.mark.parametrize("doc,count,distinct,pairs", [
    (CLAUDE_1001, 164, 52, PAIRS_1001),
    (CLAUDE_0930, 110, 76, None),
], ids=["claude-1001", "claude-0930"])
def test_every_claude_number_opens_its_own_row(run, doc, count, distinct, pairs):
    """⭐⭐ THE OWNER'S FILES, THROUGH THE REAL PER-AGENT WRITE. Every number is a
    link to row n of Claude's own list, on disk and in the copy the app reads,
    and the text is otherwise byte for byte what Claude wrote."""
    rows = own_rows(doc)
    assert len(rows) == distinct
    assert len(PLAIN_RE.findall(body_of(doc))) == count     # the input: none linked
    assert not MARKER_RE.search(doc)
    run.poll("claude", ["https://www.akc.org/visited-only"])
    local = run.write("Claude", doc[len(CLAUDE_HEADER):])
    assert documents_written(run.sink, "claude") == [local]
    marks = MARKER_RE.findall(local)
    assert len(marks) == count
    assert not PLAIN_RE.search(body_of(local))
    # ⛔ Each number opens ITS row — never a neighbour's, never an address that
    # is not in this document's own list.
    for n, url in marks:
        assert url == rows[int(n)].replace("(", "%28").replace(")", "%29"), n
    assert len({n for n, _ in marks}) == distinct
    for pair in pairs or []:
        assert pair in local, pair
    # Nothing else changed, and the list is untouched and the one list.
    assert unlink(local) == doc
    assert body_of(local).count("\n## Sources") == 0
    assert "##### Sources" not in local and "visited-only" not in local
    assert any("[Claude] linked %d of its own citation numbers to its own sources "
               "list (%d rows)" % (count, distinct) in m for m in run.logs)


def test_the_0930_pair_is_pinned_by_address():
    """The 09-30 shape's own back-to-back pair, through the numbering funnel."""
    out = research._document_with_sources(CLAUDE_0930, label="Claude")
    for pair in PAIRS_0930:
        assert pair in out, pair


def test_findings_are_still_read_from_the_clean_text(run):
    """The Findings tab is built from the report BEFORE its numbers are linked:
    no finding's snippet holds a marker, and none of their addresses is a
    marker's address glued to its neighbour (`…/2609.37647)[\\[4\\`)."""
    run.write("Claude", CLAUDE_1001[len(CLAUDE_HEADER):])
    findings = run.runtime.agent_findings["claude"]
    assert findings
    for f in findings:
        assert "[\\[" not in (f.get("snippet") or ""), f
        assert "[" not in f["url"] and ")" not in f["url"].rstrip(")"), f


@pytest.mark.parametrize("doc", [CLAUDE_1001, CLAUDE_0930], ids=["1001", "0930"])
def test_save_meta_keeps_claudes_list_and_its_addresses(run, doc):
    """⛔⛔ `save_meta` reads every report back off disk. Its strip took the
    09-30 list off once the document carried a marker (10,144 characters), and
    its address sweep read a linked pair as ONE address — 52 sources became 79.
    `sourceUrls` is what the web numbers the Super Research document from: it
    is still exactly Claude's own list, in its own order."""
    local = run.write("Claude", doc[len(CLAUDE_HEADER):])
    assert research._strip_numbered_sources_section(local) == local
    rows = own_rows(doc)
    agent = run.meta("claude")
    assert agent["sourceUrls"] == [rows[n] for n in sorted(rows)]
    assert agent["sources"] == len(rows)


# ── the shapes it must not link ───────────────────────────────────────────────

def _report(body, rows):
    return ("# Report\n\n" + body + "\n\n## Sources\n\n"
            + "\n".join(f"{n}. {r}" for n, r in rows) + "\n")


A, B, C = "https://a.example.org/one", "https://b.example.org/two", "https://c.example.org/three"


def test_a_number_with_no_row_or_no_link_stays_as_written(monkeypatch):
    """A number past the list, and a row that is only a title or is the agent's
    own chat, have nothing safe to open: they stay `\\[n\\]`."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    md = _report("One.\\[1\\] Two.\\[2\\] Three.\\[3\\] Four.\\[4\\]",
                 [(1, f"[One]({A})"), (2, "A paper with no link."),
                  (3, "[This chat](https://claude.ai/chat/1b2c)")])
    out = research._document_with_sources(md, label="Claude")
    assert out == md.replace("One.\\[1\\]", f"One.[\\[1\\]]({A})")


def test_rows_that_do_not_count_one_two_three_link_nothing(monkeypatch):
    """⛔⛔ A viewer numbers an ordered list from its first item: written "1. 2.
    4." the third row SHOWS as 3, so "[4]" linked to it would open the row the
    reader reads as 3. A list whose written numbers skip, repeat or do not start
    at 1 is left alone."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    for rows in ([(1, f"[A]({A})"), (2, f"[B]({B})"), (4, f"[C]({C})")],
                 [(1, f"[A]({A})"), (1, f"[B]({B})"), (1, f"[C]({C})")],
                 [(2, f"[A]({A})"), (3, f"[B]({B})"), (4, f"[C]({C})")]):
        md = _report("One.\\[1\\] Two.\\[2\\] Four.\\[4\\]", rows)
        assert research._document_with_sources(md, label="Claude") == md, rows
    good = _report("One.\\[1\\] Two.\\[2\\] Three.\\[3\\]",
                   [(1, f"[A]({A})"), (2, f"[B]({B})"), (3, f"[C]({C})")])
    assert len(MARKER_RE.findall(research._document_with_sources(good))) == 3


def test_a_number_in_code_in_a_links_text_or_in_the_list_is_not_linked(monkeypatch):
    """Only the text before the list is linked: a number in code is teaching,
    one inside a link's words would nest a link in a link, and one in a row of
    the list is the list's own."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    body = ("Prose.\\[1\\]\n\n```\nprint('\\[2\\]')\n```\n\nInline `x\\[2\\]` and "
            f"[see \\[2\\]]({B}) here.")
    md = _report(body, [(1, f"[A]({A})"), (2, f"[B]({B}) — it builds on \\[1\\]")])
    out = research._document_with_sources(md)
    assert out == md.replace("Prose.\\[1\\]", f"Prose.[\\[1\\]]({A})")


def test_an_address_with_brackets_is_written_safely(monkeypatch):
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    wiki = "https://en.wikipedia.org/wiki/Hip_dysplasia_(canine)"
    md = _report("Hips.\\[1\\]", [(1, f"[Hip dysplasia]({wiki})")])
    out = research._document_with_sources(md)
    assert "Hips.[\\[1\\]](https://en.wikipedia.org/wiki/Hip_dysplasia_%28canine%29)" in out


@pytest.mark.parametrize("ours", [
    # the sites the agent visited, which replaced its own titles-only list
    "\n\n##### Sources\n\n1. [akc.org/x](https://www.akc.org/x)\n"
    "2. [ofa.org/y](https://www.ofa.org/y)\n",
    # our numbered list under the alternate title, after the agent's own
    "\n\n## Sources\n\n1. [A](https://a.example.org/one)\n"
    "\n##### Sources (numbered)\n\n1. [z](https://z.example.org/prose)\n",
], ids=["visited-list", "alternate-title"])
def test_text_still_ending_with_our_list_is_never_linked_to_ours(ours, monkeypatch):
    """⛔⛔ Text that already ends with OUR list has ours as its last list, and
    its rows are not the agent's: a "[1]" linked there opens a page the agent
    never numbered 1 — a visited site, say. Such text is left exactly as it is.
    (A report whose own list of titles was replaced by the visited sites is
    exactly this shape when it is written again.)"""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    md = "# Report\n\nOne.\\[1\\] Two.\\[2\\] See https://z.example.org/prose." + ours
    assert research._document_with_sources(md, label="Claude") == md


def test_linking_twice_is_linking_once(monkeypatch):
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    once = research._document_with_sources(CLAUDE_1001, visited=["https://x.example.org/"])
    assert research._document_with_sources(once, visited=["https://y.example.org/"]) == once


# ══ 2. re-entry and regeneration keep the links and never delete text ═════════

@pytest.mark.parametrize("doc,count", [(CLAUDE_1001, 164), (CLAUDE_0930, 110)],
                         ids=["1001", "0930"])
def test_a_crash_retry_reads_claudes_report_back_as_claude_wrote_it(run, doc, count):
    """⛔⛔ A kept agent's file is read back for the consolidated text
    (`_p2_restorable_agents`). It used to come back with every number deleted
    and, on the 09-30 shape, without its list. It comes back BYTE FOR BYTE as
    the download handed it over, and a regenerated write links it again."""
    text = doc[len(CLAUDE_HEADER):]
    run.write("Claude", text)
    research._p2_mark_agent_done(run.dir, "claude", True, elapsed_sec=60)
    kept = research._p2_restorable_agents(run.dir, ["claude"])
    assert kept["claude"]["text"] == text
    again = research._p2_regenerated_document("Claude", kept["claude"]["text"], "retry")
    assert len(MARKER_RE.findall(again)) == count
    assert unlink(again) == "# Claude Deep Research (retry)\n\n" + text
    assert research._document_without_sources(again) == "# Claude Deep Research (retry)\n\n" + text


def test_the_finalize_resave_writes_the_same_linked_document(run, monkeypatch):
    """The end of Phase 2 writes every report again from its text
    (`_p2_persist_reports`): the same linked document, on disk and in the app."""
    text = CLAUDE_1001[len(CLAUDE_HEADER):]
    first = run.write("Claude", text)
    monkeypatch.setattr(research, "_generate_research_summary_async", lambda *a, **k: None)
    monkeypatch.setattr(research, "_refresh_research_title_async", lambda *a, **k: None)
    before = len(run.sink)
    asyncio.run(research._p2_persist_reports(
        {"Claude": {"text": text, "status": "done"}}, run.dir, "Jev", "a brief"))
    again = (run.dir / "documents" / "claude.md").read_text(encoding="utf-8")
    assert again == first
    assert documents_written(run.sink[before:], "claude") == [first]


def test_a_document_numbered_the_old_way_still_loses_only_our_numbers(monkeypatch):
    """The read-back's old rule still holds where it applies: a report whose
    citations WE numbered (our list after it) loses our markers and our list,
    and keeps its own list."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    md = ("# Report\n\nPack prices fell, reported at https://bnef.example.com/packs in "
          "a note nobody disputed.\n\n## Sources\n\n- [BNEF](https://bnef.example.com/packs)\n")
    out = research._document_with_sources(md)
    assert "##### Sources (numbered)" in out and MARKER_RE.search(out)
    assert research._document_without_sources(out) == md.rstrip()


def test_the_old_numbered_title_at_level_two_still_comes_off(monkeypatch):
    """"## Sources (numbered)" is ours alone (written before the wave 10
    repair); a plain "## Sources" is Claude's and stays."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    prose = "# Report\n\nPrices fell [\\[1\\]](https://a.example.org/one)."
    ours = prose + "\n\n## Sources (numbered)\n\n1. [a](https://a.example.org/one)\n"
    assert research._strip_numbered_sources_section(ours) == prose
    claude = prose + "\n\n## Sources\n\n1. [a](https://a.example.org/one)\n"
    assert research._strip_numbered_sources_section(claude) == claude


# ══ 3. the brief: numbered in the copy the app shows, and only there ══════════

#: ChatGPT's chips in the 10-01 brief become these, in page order. The fourth
#: and seventh are "+2" chips; the seventh is the repeat of the first address.
BRIEF_PAIRS_1001 = [
    "system-one-models-and-jev`. [\\[1\\]](https://typesafe.ai/blog/introducing-system-one-models-and-jev)\n",
    "known-limitations pages. [\\[2\\]](https://docs.typesafe.ai/llms.txt)\n",
    "model aliases can change. [\\[3\\]](https://docs.typesafe.ai/models)\n",
    "or headline charts. [\\[4\\]](https://evals.typesafe.ai/)\n",
    "primitives/noul`. [\\[5\\]](https://docs.typesafe.ai/primitives/choice)\n",
    "the advertised gains. [\\[1\\]](https://typesafe.ai/blog/introducing-system-one-models-and-jev)\n",
    "change the picture. [\\[11\\]](https://docs.typesafe.ai/model-jaggedness/jev-1.13)\n",
]
BRIEF_ROWS_1001 = (
    "1. [TypeSafe AI](https://typesafe.ai/blog/introducing-system-one-models-and-jev) — typesafe.ai\n"
    "2. [TypeSafe AI](https://docs.typesafe.ai/llms.txt) — docs.typesafe.ai\n"
    "3. [TypeSafe AI](https://docs.typesafe.ai/models) — docs.typesafe.ai\n"
    "4. [Evals](https://evals.typesafe.ai/) — evals.typesafe.ai\n"
    "5. [TypeSafe AI](https://docs.typesafe.ai/primitives/choice) — docs.typesafe.ai\n"
    "6. [TypeSafe AI](https://docs.typesafe.ai/confidence) — docs.typesafe.ai\n"
    "7. [arXiv](https://arxiv.org/abs/2609.37647) — arxiv.org\n"
    "8. [arXiv](https://arxiv.org/abs/2609.23986) — arxiv.org\n"
    "9. [arXiv](https://arxiv.org/abs/2609.30922) — arxiv.org\n"
    "10. [arXiv](https://arxiv.org/abs/2609.24052) — arxiv.org\n"
    "11. [TypeSafe AI](https://docs.typesafe.ai/model-jaggedness/jev-1.13) — docs.typesafe.ai\n")
BRIEF_TEXT_1001 = BRIEF_1001[len(BRIEF_HEADER):]
CHIP_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^)\s]+)\)")


def _assert_numbered_app_copy(app):
    """The 10-01 brief as the app shows it: every chip a number, a repeat chip
    its first number, "+2" gone, one list of 11 rows — and every other byte is
    the brief's own."""
    marks = MARKER_RE.findall(app)
    assert len(marks) == 12 and len({n for n, _ in marks}) == 11
    for pair in BRIEF_PAIRS_1001:
        assert pair in app, pair
    assert "+2" not in app and "TypeSafe AI](" not in app.split(TAIL)[0]
    assert app.count("##### Sources") == 1
    assert app.endswith(TAIL + BRIEF_ROWS_1001)
    # Each chip, put back, gives the brief ChatGPT wrote: nothing else moved.
    chips = iter(CHIP_RE.findall(BRIEF_1001))
    rebuilt = MARKER_RE.sub(lambda m: "[%s](%s)" % next(chips), app.split(TAIL)[0])
    assert rebuilt == BRIEF_1001.rstrip()


class _Taken(Exception):
    """Raised when the run reaches Phase 2: the rest is not under test."""


class _FakeBrowser:
    def __init__(self, *_a, **_k):
        self.context = None
        self.page = None

    async def start(self):
        return None

    async def close(self):
        return None

    async def current_url(self):
        return ""


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """The REAL `run_pipeline` from a resume directory, until Phase 2 starts.
    `run_phase2` is where it stops, and it records the brief text the agents are
    handed — the paste copy."""
    queue_dir = tmp_path / "Jev_TypeSafe_20261001_064737"
    (queue_dir / "documents").mkdir(parents=True)
    (queue_dir / "config.json").write_text('{"skipInitVerify": true}', encoding="utf-8")
    seen = {"paste": [], "p1_runs": 0}
    sink = _firestore(monkeypatch)
    for name, value in (
            ("resolve_api_key", lambda *_a, **_k: "test-key"),
            ("_capture_anthropic_attribution", lambda *a, **k: None),
            ("clear_clipboard", lambda *a, **k: None),
            ("log", lambda *a, **k: None),
            ("init_tracks", lambda *a, **k: None),
            ("_login_interrupt_active", lambda: False),
            ("Browser", _FakeBrowser),
            ("_profile_dir", lambda *_a, **_k: tmp_path / "profile"),
            ("_update_firestore_research", lambda *a, **k: None),
            ("_write_phase_terminal_status", lambda *a, **k: None),
            ("update_link_in_firestore", lambda *a, **k: None),
            ("emit_event", lambda *a, **k: None),
            ("_plan_pipeline_auto_retry", lambda *a, **k: (False, 0, False)),
            ("_probe_google_credentials", lambda *a, **k: None),
            ("_post_fe_p4p5_trigger", lambda *a, **k: None),
            ("_save_meta_in_background", lambda *a, **k: None),
            ("_observe_dom_success", lambda *a, **k: None),
            ("fail_phase", lambda *a, **k: None)):
        monkeypatch.setattr(research, name, value)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)

    async def _none(*_a, **_k):
        return None
    for name in ("run_input_dispatcher", "_probe_cua_available"):
        monkeypatch.setattr(research, name, _none)

    async def _scrub(*_a, **_k):
        return {}
    monkeypatch.setattr(research, "_scrub_persisted_google_auth", _scrub)

    async def _gate(*_a, **_k):
        return "ok"
    monkeypatch.setattr(research, "_phase_verify_gate", _gate)

    async def _run_phase2(_browser, _cua, brief_text, *a, **k):
        seen["paste"].append(brief_text)
        raise _Taken()
    monkeypatch.setattr(research, "run_phase2", _run_phase2)

    def go(*, start_phase=1, replies=(BRIEF_TEXT_1001,), brief_file=None, on_p1=None):
        answers = list(replies)

        async def _run_phase1(*_a, **_k):
            seen["p1_runs"] += 1
            if on_p1:
                on_p1(seen["p1_runs"])
            return {"text": answers.pop(0), "url": "https://chatgpt.com/c/abc"}

        async def _decide(_phase, *a, **k):
            return "stop"

        monkeypatch.setattr(research, "detect_resume_phase",
                            lambda _qd: (start_phase, "test: Phase %d" % start_phase))
        monkeypatch.setattr(research, "run_phase1", _run_phase1)
        monkeypatch.setattr(research._controls, "await_phase_decision", _decide)
        monkeypatch.setattr(research._controls, "consume_phase_skip", lambda *a, **k: False)
        try:
            asyncio.run(research.run_pipeline(
                topic="Jev and TypeSafe AI", resume_dir=str(queue_dir),
                brief_file=brief_file, uid=None, email=None, api_key="test-key"))
        except _Taken:
            pass
        disk = queue_dir / "documents" / "brief.md"
        return {"disk": disk.read_text(encoding="utf-8") if disk.exists() else None,
                "app": documents_written(sink, "brief"), "paste": seen["paste"],
                "p1_runs": seen["p1_runs"]}

    go.queue_dir = queue_dir
    return go


def test_phase1s_brief_is_numbered_in_the_app_and_nowhere_else(pipeline):
    """⭐⭐ THE PAGE-READ BRANCH OF `run_pipeline`. The app's copy is numbered;
    `brief.md` (attached to the agents, pasted on a hard retry) and the text the
    agents are pasted are byte for byte what ChatGPT wrote — the wave 10 rule."""
    got = pipeline()
    assert got["disk"] == BRIEF_1001
    assert got["paste"] == [BRIEF_TEXT_1001]
    assert len(got["app"]) == 1
    _assert_numbered_app_copy(got["app"][0])


def test_a_brief_from_a_file_is_numbered_in_the_app_only(pipeline, tmp_path):
    """The `--brief-file` branch: the same rule."""
    f = tmp_path / "given-brief.md"
    f.write_text(BRIEF_1001, encoding="utf-8")
    got = pipeline(brief_file=str(f))
    assert got["p1_runs"] == 0
    assert got["disk"] == BRIEF_1001
    assert got["paste"] == [BRIEF_TEXT_1001]
    _assert_numbered_app_copy(got["app"][-1])


def test_a_resume_past_phase1_writes_the_numbered_copy_again(pipeline):
    """`_resave_phase1_on_resume`: a run resumed into Phase 2 writes the app's
    brief again from `brief.md`, numbered; the agents get the file's text."""
    (pipeline.queue_dir / "documents" / "brief.md").write_text(BRIEF_1001, encoding="utf-8")
    got = pipeline(start_phase=2)
    assert got["p1_runs"] == 0
    assert got["disk"] == BRIEF_1001
    assert got["paste"] == [BRIEF_TEXT_1001]
    assert len(got["app"]) == 1
    _assert_numbered_app_copy(got["app"][0])


def test_a_regenerated_brief_is_numbered_in_the_app_only(pipeline, monkeypatch):
    """The resume-with-input branch: Phase 1 paused, resumed with more to say,
    and the brief written again from ChatGPT's new reply."""
    state = {"paused": False, "context": True}

    def _pause_once():
        if not state["paused"] and (pipeline.queue_dir / "documents" / "brief.md").exists():
            state["paused"] = True
            return True
        return False

    async def _resume(*a, **k):
        return False

    def _pop():
        said, state["context"] = state["context"], False
        return "Also cover the pricing." if said else ""
    monkeypatch.setattr(research._controls, "is_stop_or_pause", _pause_once)
    monkeypatch.setattr(research._controls, "is_stop", lambda: False)
    monkeypatch.setattr(research._controls, "peek_extra_context", lambda: state["context"])
    monkeypatch.setattr(research._controls, "pop_extra_context", _pop)
    monkeypatch.setattr(research, "pause_and_close_browser", _resume)
    first = "# A first brief\n\nNothing cited here at all, only questions to answer."
    got = pipeline(replies=(first, BRIEF_TEXT_1001))
    assert got["p1_runs"] == 2 and state["paused"]
    assert got["disk"] == BRIEF_1001
    assert got["paste"] == [BRIEF_TEXT_1001]
    assert got["app"][0] == BRIEF_HEADER + first
    _assert_numbered_app_copy(got["app"][-1])


def test_numbering_the_app_copy_twice_is_numbering_it_once():
    app = research._brief_numbered_copy(BRIEF_1001)
    assert research._brief_numbered_copy(app) == app


def test_the_0928_fixture_brief_numbers_all_twenty_chips(monkeypatch):
    """The 09-28 fixture's long brief (twenty chips) gets twenty numbers and
    twenty rows. The old numbering capped at twelve."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    html = (FIX / "chatgpt_0928" / "long_brief_reply.html").read_text(encoding="utf-8")
    md = BRIEF_HEADER + research.html_to_markdown(html)
    chips = CHIP_RE.findall(md)
    assert len(chips) == 20
    app = research._brief_numbered_copy(md)
    marks = MARKER_RE.findall(app)
    assert [int(n) for n, _ in marks] == list(range(1, 21))
    assert [u for _n, u in marks] == [u for _t, u in chips]
    rows = re.findall(r"^(\d+)\. \[([^\]]*)\]\(([^)]+)\)", app.split(TAIL)[1], re.M)
    assert [(t, u) for _n, t, u in rows] == chips


@pytest.mark.parametrize("md,want", [
    # a link in the middle of a sentence keeps its words; its number goes at
    # the end of the sentence, as in the agent reports
    ("Read [the launch post](https://a.example.org/post) before anything else.\n",
     "Read [the launch post](https://a.example.org/post) before anything else "
     "[\\[1\\]](https://a.example.org/post).\n"),
    # ⛔ after a colon it is a link a reader needs, not a chip
    ("See: [the launch post](https://a.example.org/post)\n",
     "See: [the launch post](https://a.example.org/post) [\\[1\\]](https://a.example.org/post)\n"),
    # two chips side by side both fold, the second right after the first
    ("Prices fell. [Site A](https://a.example.org/x) [Site B+1](https://b.example.org/y)\n",
     "Prices fell. [\\[1\\]](https://a.example.org/x) [\\[2\\]](https://b.example.org/y)\n"),
    # ⛔ a link opening the next paragraph is not a chip, even right after one
    ("Prices fell. [Site A](https://a.example.org/x)\n\n[The full table](https://b.example.org/y) "
     "has the rest.\n",
     "Prices fell. [\\[1\\]](https://a.example.org/x)\n\n[The full table](https://b.example.org/y) "
     "has the rest [\\[2\\]](https://b.example.org/y).\n"),
    # a chip after a quoted, bold title
    ("Start from **“Introducing Jev.”** [TypeSafe AI+2](https://a.example.org/x)\n",
     "Start from **“Introducing Jev.”** [\\[1\\]](https://a.example.org/x)\n"),
    # one address linked twice in a sentence: one number at its end
    ("Read [the post](https://a.example.org/x) and [the post again](https://a.example.org/x) "
     "today.\n",
     "Read [the post](https://a.example.org/x) and [the post again](https://a.example.org/x) "
     "today [\\[1\\]](https://a.example.org/x).\n"),
    # ⛔ a stop inside the next link's words is not where a number may go: it
    # would split that link
    ("See [a](https://a.example.org/x) and [Dr. Who](https://b.example.org/y) here.\n",
     "See [a](https://a.example.org/x) and [\\[1\\]](https://a.example.org/x) "
     "[Dr. Who](https://b.example.org/y) here [\\[2\\]](https://b.example.org/y).\n"),
], ids=["mid-sentence", "after-a-colon", "two-chips", "next-paragraph", "after-a-title",
        "same-address-twice", "a-stop-inside-a-link"])
def test_the_chip_rule(md, want, monkeypatch):
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    out = research._brief_numbered_copy(BRIEF_HEADER + md)
    assert out.split(TAIL)[0] == (BRIEF_HEADER + want).rstrip()


@pytest.mark.parametrize("md", [
    BRIEF_HEADER + "Nothing cited at all.\n",
    BRIEF_HEADER + "Code only: `[x](https://a.example.org/x)`.\n",
    BRIEF_HEADER + "A picture. ![chart](https://a.example.org/c.png)\n",
    BRIEF_HEADER + "Text. [Our chat](https://chatgpt.com/c/abc)\n",
    # its own list of links is the one list
    BRIEF_HEADER + "Prices fell. [Site A](https://a.example.org/x)\n\n## Sources\n\n"
    "- [Site A](https://a.example.org/x)\n",
    # already carrying our marker: numbered once is numbered
    BRIEF_HEADER + "Prices fell. [\\[1\\]](https://a.example.org/x)\n",
], ids=["no-links", "in-code", "an-image", "a-chat-link", "own-list", "our-marker"])
def test_a_brief_with_nothing_to_number_is_left_as_it_is(md, monkeypatch):
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    assert research._brief_numbered_copy(md) == md


def test_only_the_brief_is_numbered_by_the_firestore_writer(monkeypatch):
    """An agent report passes through `save_document_to_firestore` untouched:
    its numbering is the write sites' (and a ChatGPT report holds links)."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    sink = _firestore(monkeypatch)
    report = "# ChatGPT Deep Research\n\nPrices fell. [Site A](https://a.example.org/x)\n"
    assert research.save_document_to_firestore("chatgpt", report, "ChatGPT Deep Research")
    assert research.save_document_to_firestore("brief", report, "Research Brief")
    assert documents_written(sink, "chatgpt") == [report]
    assert documents_written(sink, "brief") == [research._brief_numbered_copy(report)]
    assert documents_written(sink, "brief") != [report]


# ══ 4. ChatGPT 10-01: one sources section ═════════════════════════════════════

def test_the_1001_chatgpt_document_ends_with_one_sources_section(run):
    """⛔⛔ ITS OWN "**Prioritized sources.**" — fifteen names, no link — was not
    read as its sources section, so the visited list went after it: two
    sections. "Prioritized" is a qualifier now; ours replaces it, and every byte
    of the report before it is as it was."""
    header = "# ChatGPT Deep Research\n\n"
    cut = CHATGPT_1001.index(TAIL)
    report, ours = CHATGPT_1001[:cut], CHATGPT_1001[cut + len(TAIL):]
    visited = re.findall(r"^\d+\. \[[^\]]*\]\(([^)]+)\)", ours, re.M)
    assert len(visited) == 35
    lead = report.index("**Prioritized sources.**")
    assert "](http" not in report[lead:]
    run.poll("chatgpt", visited)
    local = run.write("ChatGPT", report[len(header):])
    assert local == report[:lead].rstrip() + TAIL + ours
    assert "Prioritized sources" not in local
    assert local.count("##### Sources") == 1


@pytest.mark.parametrize("own", [
    "**Prioritized sources.**\n\n1. **TypeSafe AI, Models.** The specification.\n",
    "## Prioritized sources\n\n1. TypeSafe AI, Models.\n",
], ids=["bold-lead", "heading"])
def test_prioritized_is_a_sources_qualifier(own, monkeypatch):
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    body = "# ChatGPT Deep Research\n\n## Findings\n\nThe breed is popular in Canada.\n"
    out = research._document_with_sources(body + "\n" + own,
                                          visited=["https://www.akc.org/dog-breeds/"])
    assert out == body.rstrip() + TAIL + "1. [akc.org/dog-breeds](https://www.akc.org/dog-breeds/)\n"


# ══ 5. the goldens the web renders ═══════════════════════════════════════════

@pytest.mark.parametrize("name,make", [
    ("claude.md", lambda: research._document_with_sources(CLAUDE_1001, label="Claude")),
    ("claude_0930.md", lambda: research._document_with_sources(CLAUDE_0930, label="Claude")),
    ("brief.md", lambda: research._brief_numbered_copy(BRIEF_1001)),
], ids=["claude-1001", "claude-0930", "brief-1001"])
def test_the_web_render_goldens_are_what_the_writes_produce(name, make, monkeypatch):
    """The web's `footnotesRender.test.tsx` renders these through the app's own
    `DocumentMarkdown` and counts the clickable footnotes. ⛔ They are pinned to
    what the code writes today, so a change here fails until they are made
    again from the code — never edited by hand."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    assert (GOLDEN / name).read_text(encoding="utf-8") == make()
