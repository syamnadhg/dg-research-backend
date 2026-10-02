"""Wave 14 part 2 + the no-download rule, 2026-10-02: a report's export is caught
in the page (Chrome downloads nothing), and ChatGPT's own citation numbers are
linked to their sources from its PDF export.

1. NO CHROME DOWNLOAD. Chrome 154 crashed in its own downloads button on 4 of
   the 49 ChatGPT report exports in every log read (#Dev/wave15/crash/
   crash-analysis-1001.json). The owner's recording (#Dev/wave14/
   recordings-1001/sr-cite-chatgpt-dr-top-full.json) shows how the export makes
   its file: on the TOP chatgpt.com page, `URL.createObjectURL(Blob)` then
   `HTMLAnchorElement.prototype.click()` on an `<a download>` whose href is that
   blob address — the Markdown (text/markdown;charset=utf-8, 101,627 bytes),
   then the PDF (application/pdf). A catcher on the top page now keeps each Blob
   and cancels that click; the bytes come back to Python. The pages here make
   their files exactly that way, and every test counts Chrome's own download
   events: none.
2. CHATGPT'S FOOTNOTES FROM ITS PDF. The owner's pair (tests/fixtures/
   documents_1001/chatgpt_dr_papertrade.md and .pdf, both exports of one
   report): 141 citation runs, 59 numbers, 27 sources on the PDF's sources
   pages. Each run becomes ChatGPT's own number linked to its source; the
   document ends with ONE "Sources" list shaped like ChatGPT's page 42. On any
   mismatch nothing is linked and the document is what it was before.

⛔ Expected values are this file's own: the sources table below is read off the
PDF's pages 42-43 (title, address, the numbers under it), and the order check
reads the PDF's chips with this file's own loop.
Nothing leaves the machine: the pages are served from reserved `.invalid` hosts
through a route that answers every request locally; node runs the catcher's
own script against a stand-in page.
"""
import asyncio
import base64
import copy
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import research
import _domshim
import test_chatgpt_new_page_0928 as base
from test_footnotes_1001 import _firestore

chrome = base.chrome
page = base.page
fast = base.fast

FIX = Path(__file__).resolve().parent / "fixtures" / "documents_1001"
MD = (FIX / "chatgpt_dr_papertrade.md").read_text(encoding="utf-8")
PDF = (FIX / "chatgpt_dr_papertrade.pdf").read_bytes()
#: The document the write produces from the pair (after our header).
GOLDEN = (FIX / "footnoted" / "chatgpt_dr_papertrade.md").read_text(encoding="utf-8")
HEADER = "# ChatGPT Deep Research\n\n"

#: The PDF's sources pages (42-43), as printed: the numbers under each source,
#: its title, its address.
SOURCES = [
    ((1, 12, 24, 59), "Papertrade — Synthetic perpetuals on Hyperliquid",
     "https://papertrade.xyz/"),
    ((2, 5, 43, 45, 46), "papertrade.xyz @papertrade_xyz - Twitter Profile | TwStalker",
     "https://www30.twstalker.com/papertrade_xyz"),
    ((3, 10, 13, 21, 22), "Papertrade - Projects & Protocols | IQ.wiki",
     "https://iq.wiki/wiki/papertrade"),
    ((4,), "Audits – CrypticDefense Audits", "https://crypticdefense.com/audits/"),
    ((6, 7, 11, 14, 18, 20, 23, 25, 26, 29, 30, 32, 44),
     "Papertrade Launch, 1000x Leverage & Onchain War Stories - blurr | BidClub",
     "https://www.bidclub.ai/e/papertrade-launch-1000x-leverage-onchain-war-sto"),
    ((8, 15), "Interacting with HyperCore | Hyperliquid Docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/"
     "interacting-with-hypercore"),
    ((9, 31), "GitHub - HakaiRhinohl/PaperTrade-Simulations · GitHub",
     "https://github.com/HakaiRhinohl/PaperTrade-Simulations"),
    ((16, 34), "GMX | GMX Docs", "https://docs.gmx.io/"),
    ((17, 40, 57), "CFTC Issues Order Against Uniswap Labs for Offering Illegal Digital "
     "Asset Derivatives Trading | CFTC", "https://www.cftc.gov/PressRoom/PressReleases/8961-24"),
    ((19,), "Read Me - Support Guide | Support | Hyperliquid Docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/support"),
    ((27, 35), "Funding | Hyperliquid Docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding"),
    ((28, 50), "Interaction timings | Hyperliquid Docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/"
     "interaction-timings"),
    ((33,), "Foundation non-validating node | Hyperliquid Docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/nodes/"
     "foundation-non-validating-node"),
    ((36, 56), "Fees | GMX Docs", "https://docs.gmx.io/docs/trading/fees/"),
    ((37,), "Protocol vaults | Hyperliquid Docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/vaults/protocol-vaults"),
    ((38,), "Providing liquidity | GMX Docs", "https://docs.gmx.io/docs/providing-liquidity/"),
    ((39, 55), "Liquidations and ADL | GMX Docs",
     "https://docs.gmx.io/docs/trading/liquidations/"),
    ((41,), "CSA and CIRO expect crypto trading platforms to prioritize applications for "
     "investment dealer registration and CIRO membership - Canadian Securities Administrators",
     "https://www.securities-administrators.ca/news/csa-and-ciro-expect-crypto-trading-"
     "platforms-to-prioritize-applications-for-investment-dealer-registration-and-ciro-"
     "membership/"),
    ((42,), "Registration - Canadian Securities Administrators",
     "https://www.securities-administrators.ca/registration/"),
    ((47,), "Address: 0x25f4f0b1...1fb100000 | HyperEVMScan Block Explorer",
     "https://hyperevmscan.io/address/0x25f4f0b1c8dd22143db976e51d530bb1fb100000"),
    ((48,), "The perpetual contract platform papertrade.xyz will launch on October 10, "
     "2026 - RootData | RootData", "https://www.rootdata.com/news/773992"),
    ((49,), "Hyperliquid-Based Perpetuals Platform Papertrade.xyz to Launch on October 10, "
     "2026 | Binance News on Binance Square",
     "https://www.binance.com/en/square/post/09-30-2026-hyperliquid-based-perpetuals-"
     "platform-papertrade-xyz-to-launch-on-october-10-2026-372069470019857"),
    ((51,), "Dual-block architecture | Hyperliquid Docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/"
     "dual-block-architecture"),
    ((52,), "Fees | Hyperliquid Docs", "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees"),
    ((53,), "Liquidations | Hyperliquid Docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations"),
    ((54,), "Contract specifications | Hyperliquid Docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications"),
    ((58,), "CFTC Issues Orders Against Operators of Three DeFi Protocols for Offering "
     "Illegal Digital Asset Derivatives Trading | CFTC",
     "https://www.cftc.gov/PressRoom/PressReleases/8774-23"),
]
NUMBER_URL = {n: u for nums, _t, u in SOURCES for n in nums}

RUN_RE = re.compile("\ue200[^\ue201]*\ue201")
MARKER_RE = re.compile(r"\[\\\[(\d{1,3})\\\]\]\(([^()\s]*)\)")
PLAIN_RE = re.compile(r"(?<![\[\\])\\\[(\d{1,3})\\\](?!\]\()")
ROW_RE = re.compile(r"^- \[(?P<t>(?:\\.|[^\]\\])*)\]\((?P<u>[^()\s]+)\) — (?P<l>.+?) — cited as "
                    r"(?P<n>\d+(?:, \d+)*)$")
TAIL = "\n\n##### Sources\n\n"


def _rows(doc):
    """This file's own reading of the one Sources list: (numbers, title, url)."""
    assert doc.count(TAIL) == 1, "not exactly one Sources list"
    out = []
    for line in doc[doc.index(TAIL) + len(TAIL):].rstrip("\n").split("\n"):
        m = ROW_RE.match(line)
        assert m, line
        out.append((tuple(int(x) for x in m.group("n").split(", ")),
                    re.sub(r"\\(.)", r"\1", m.group("t")), m.group("u")))
    return out


def _numbered(doc):
    """The linked document with each marker back to ChatGPT's `\\[n\\]`."""
    return MARKER_RE.sub(lambda m: "\\[%s\\]" % m.group(1), doc)


#: Each PDF read once per session: a reading takes about two seconds, and the
#: function is pure — every test still gets the real function's own answer.
#: (`getattr` and `raising=False`: against code without it, each test fails on
#: its own behaviour rather than the file failing to load.)
_REAL_TABLE = getattr(research, "_chatgpt_pdf_table", None)
_TABLES: dict = {}


@pytest.fixture(autouse=True)
def _one_reading_per_pdf(monkeypatch):
    def _read(pdf):
        key = hashlib.sha256(pdf or b"").hexdigest()
        if key not in _TABLES:
            try:
                _TABLES[key] = (True, _REAL_TABLE(pdf))
            except Exception as e:
                _TABLES[key] = (False, e)
        ok, got = _TABLES[key]
        if not ok:
            raise got
        return copy.deepcopy(got)
    monkeypatch.setattr(research, "_chatgpt_pdf_table", _read, raising=False)


@pytest.fixture
def lines(monkeypatch):
    out = []
    monkeypatch.setattr(research, "log", lambda m, lv="INFO", *a, **k: out.append((lv, str(m))))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    return out


def _said(lines, text):
    return [m for _lv, m in lines if text in m]


# ═══ 1. The pair: ChatGPT's own numbers, linked from its PDF ═══════════════════

def test_the_pdf_table_reads_the_chips_and_the_sources_pages():
    """141 numbered chips in the body, 59 numbers; 27 sources whose numbers,
    titles and addresses are the printed pages', in order."""
    table = research._chatgpt_pdf_table(PDF)
    assert len(table["body"]) == 141
    assert sorted({n for n, _u in table["body"]}) == list(range(1, 60))
    assert [(tuple(e["numbers"]), e["title"], e["url"]) for e in table["sources"]] == SOURCES
    for n, u in table["body"]:
        assert u == NUMBER_URL[n], n


def test_the_chips_in_order_are_the_runs_in_order():
    """An independent reading (position, not number): the PDF's 12-pt chips on
    its body pages, in the PDF's own order, against the runs in the Markdown —
    the order the decision measured, 141 of 141."""
    from pypdf import PdfReader
    chips = []
    for pg in PdfReader(io.BytesIO(PDF)).pages[:41]:
        for ref in pg.get("/Annots") or []:
            a = ref.get_object()
            r = [float(v) for v in a["/Rect"]]
            if abs(abs(r[2] - r[0]) - 12) < 0.5 and abs(abs(r[3] - r[1]) - 11.25) < 0.5:
                chips.append(str(a["/A"]["/URI"]))
    assert len(chips) == 141
    marks = [u for _n, u in MARKER_RE.findall(research._chatgpt_pdf_footnotes(MD, PDF))]
    assert marks == chips


def test_the_document_carries_chatgpts_numbers_and_one_sources_list(lines):
    """⭐⭐ THE OWNER'S PAIR. Each of the 141 runs is ChatGPT's own number, a link
    to the source ChatGPT's PDF links it to; the document ends with ONE Sources
    list, each source with its title, its address and the numbers citing it, as
    ChatGPT's page 42 prints them; the attached brief's runs are gone; and the
    text is otherwise byte for byte the export's."""
    # The pair as the decision measured it: 146 runs (141 cite, 5 filecite), no
    # link anywhere.
    runs = RUN_RE.findall(MD)
    assert len(runs) == 146 and PDF[:5] == b"%PDF-" and "](http" not in MD
    assert sum(1 for r in runs if r.startswith("\ue200cite\ue202")) == 141
    assert sum(1 for r in runs if r.startswith("\ue200filecite\ue202")) == 5
    doc = research._chatgpt_pdf_footnotes(MD, PDF)
    assert doc == GOLDEN
    marks = MARKER_RE.findall(doc)
    assert len(marks) == 141
    assert len({n for n, _u in marks}) == 59
    for n, u in marks:
        assert u == NUMBER_URL[int(n)], n
    assert not PLAIN_RE.search(doc[:doc.index(TAIL)]), "a number was left unlinked"
    assert _rows(doc) == SOURCES
    assert "filecite" not in doc and not re.search("[\ue200-\ue202]", doc)
    body = doc[:doc.index(TAIL)]
    assert re.sub(r"\\\[\d+\\\]", "", _numbered(body)) == re.sub(
        "[^\\S\n]*\ue200[^\ue201]*\ue201", "", MD).rstrip()
    said = _said(lines, "ChatGPT's own citation numbers, from its PDF export")
    assert said == ["[ChatGPT] ChatGPT's own citation numbers, from its PDF export: 141 "
                    "citations, 59 numbers, 27 sources; 31 of 31 reference ids have an address"]


def test_a_number_sits_where_its_run_stood():
    """A run after a sentence's full stop becomes its number, glued to the stop;
    the words after it keep their space; a run in a table cell stays in its
    cell."""
    doc = research._chatgpt_pdf_footnotes(MD, PDF)
    assert ("still says “trade coming soon.”[\\[1\\]](https://papertrade.xyz/) The project’s"
            in doc)
    assert "| Advertised leverage | Up to 1,000×.[\\[1\\]](https://papertrade.xyz/) |" in doc
    assert "treats those figures as leads rather than conclusions.\n\n" in doc


def _cut_run(md, k):
    """The Markdown without its k-th cite run."""
    m = [r for r in RUN_RE.finditer(md) if r.group(0).startswith("\ue200cite")][k]
    return md[:m.start()] + md[m.end():]


def _table_with(change):
    """The real PDF table, changed by `change(table)`."""
    real = research._chatgpt_pdf_table(PDF)

    def _tab(_pdf):
        t = json.loads(json.dumps(real))
        change(t)
        return t
    return _tab


def _ref_conflict(t):
    """A group whose first reference is also cited alone under another number:
    that group's address changed everywhere — every number still opens one
    address and the sources pages still agree, but one reference id now opens
    two addresses."""
    groups = {}
    for r in RUN_RE.findall(MD):
        parts = r[1:-1].split("\ue202")
        if parts[0] == "cite":
            refs = tuple(parts[1:])
            if refs not in groups:
                groups[refs] = len(groups) + 1
    single = {refs[0]: n for refs, n in groups.items() if len(refs) == 1}
    n = next(n for refs, n in groups.items() if len(refs) > 1 and refs[0] in single
             and NUMBER_URL[n] == NUMBER_URL[single[refs[0]]])
    for i, (num, _u) in enumerate(t["body"]):
        if num == n:
            t["body"][i] = [num, "https://moved.example.org/x"]
    for e in t["sources"]:
        e["urls"] = ["https://moved.example.org/x" if num == n else u
                     for num, u in zip(e["numbers"], e["urls"])]


def _blank_pdf():
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


@pytest.mark.parametrize("why,md,table,pdf", [
    ("140 numbered citations in the PDF, 141 in the Markdown", None, "drop-chip", PDF),
    ("141 numbered citations in the PDF, 140 in the Markdown", "cut-run", None, PDF),
    ("the PDF's numbers are not the Markdown's citations numbered by first use", None,
     "swap-number", PDF),
    ("number 6 opens two different addresses in the PDF", None, "two-addresses", PDF),
    ("the PDF's sources pages do not list the numbers and addresses its text links", None,
     "sources-differ", PDF),
    ("number 4 is listed twice on the PDF's sources pages", None, "listed-twice", PDF),
    ("reference turn", None, "ref-conflict", PDF),
    ("the PDF could not be read", None, None, b"%PDF-1.7 not a pdf"),
    ("the PDF holds no numbered citation", None, None, "blank"),
    ("the Markdown export already writes bracketed numbers of its own", "own-number", None, PDF),
    ("numbers would link at the write", "line-start", None, PDF),
], ids=["chip-dropped", "run-dropped", "numbers-swapped", "two-addresses", "sources-differ",
        "listed-twice", "reference-conflict", "unreadable", "no-chips", "own-numbers",
        "run-at-line-start"])
def test_any_mismatch_writes_no_link_and_keeps_todays_document(lines, monkeypatch, why, md,
                                                                table, pdf):
    """⛔⛔ A SHIFTED LINK IS WORSE THAN NO FOOTNOTE. Every check before anything
    is written: chips = runs (in number and per number), one number → one
    address, the sources pages = the body, one reference id → one address, every
    number written links. Any mismatch: no number, no list — the export with its
    runs removed, as before (the write then ends it with the visited sites) —
    and one log line saying why."""
    text = MD
    if md == "cut-run":
        text = _cut_run(MD, 70)
    elif md == "own-number":
        text = MD.replace("**Research cutoff:", "Step \\[3\\]. **Research cutoff:", 1)
    elif md == "line-start":
        k = MD.index("\ue200cite")
        text = MD[:k].rstrip(" ") + "\n" + MD[k:]
    changes = {
        "drop-chip": lambda t: t["body"].pop(30),
        "swap-number": lambda t: t["body"].__setitem__(
            -1, [7, NUMBER_URL[7]]) if t["body"][-1][0] != 7 else None,
        "two-addresses": lambda t: t["body"].__setitem__(
            next(i for i, (n, _u) in enumerate(t["body"]) if n == 6), [6, "https://x.example.org/"]),
        "sources-differ": lambda t: t["sources"][3]["urls"].__setitem__(0, "https://x.example.org/"),
        "listed-twice": lambda t: t["sources"][0]["numbers"].append(4)
        or t["sources"][0]["urls"].append(NUMBER_URL[4]),
        "ref-conflict": _ref_conflict,
    }
    if table:
        monkeypatch.setattr(research, "_chatgpt_pdf_table", _table_with(changes[table]))
    if pdf == "blank":
        pdf = _blank_pdf()
    out = research._chatgpt_pdf_footnotes(text, pdf)
    assert out == research._strip_chatgpt_citation_tokens(text)
    assert not MARKER_RE.search(out) and TAIL not in out
    said = _said(lines, "no source links from ChatGPT's PDF export")
    assert len(said) == 1 and why in said[0], said
    assert "ends with the sites ChatGPT visited" in said[0]


def test_no_pdf_keeps_todays_document(lines):
    out = research._chatgpt_document_from_exports(MD, None)
    assert out == research._strip_chatgpt_citation_tokens(MD)
    assert _said(lines, "no PDF export was caught")


def test_the_reports_own_sources_section_with_no_link_is_replaced():
    """⭐ ONE SOURCES SECTION. ChatGPT's 10-01 export ended with its own
    "**Prioritized sources.**" — names, no link. ChatGPT's own list from the PDF
    replaces it: the document has one."""
    own = "\n\n**Prioritized sources.**\n\n- The project's own website\n- The BidClub interview\n"
    doc = research._chatgpt_pdf_footnotes(MD + own, PDF)
    assert "Prioritized sources" not in doc and "BidClub interview" not in doc
    assert doc == GOLDEN


def test_a_sources_section_of_its_own_that_holds_links_keeps_todays_document(lines):
    own = "\n\n## References\n\n- [The site](https://papertrade.xyz/)\n"
    out = research._chatgpt_pdf_footnotes(MD + own, PDF)
    assert not MARKER_RE.search(out)
    assert _said(lines, "ends with a sources list of its own that holds links")


# ═══ 2. The write: linked once, read back as written, one list ═══════════════

def test_the_write_links_chatgpts_numbers_and_keeps_its_list(lines):
    """The extraction hands over ChatGPT's numbers as `\\[n\\]` and its list; the
    write's own-numbers step links them — the visited sites never added — and
    the crash-retry read-back turns them back into the text handed over."""
    numbered = research._chatgpt_document_from_exports(MD, PDF)
    assert not MARKER_RE.search(numbered) and len(PLAIN_RE.findall(numbered)) == 141
    assert research._doc_own_list_rows(numbered) == {
        n: u for n, u in NUMBER_URL.items()}
    linked = research._number_document_sources(
        HEADER + numbered, [{"url": "https://papertrade.xyz/", "snippet": "x"}],
        visited=["https://visited.example.org/only"], label="ChatGPT")
    assert linked == HEADER + GOLDEN
    assert research._document_without_sources(linked) == HEADER + numbered.rstrip("\n") + "\n"
    assert research._strip_numbered_sources_section(linked) == linked
    assert research._doc_own_numbers_unlinked(linked) == HEADER + numbered.rstrip("\n") + "\n"
    assert _said(lines, "[ChatGPT] linked 141 of its own citation numbers")


def test_the_self_check_does_not_log_and_the_write_does(lines):
    numbered = research._chatgpt_document_from_exports(MD, PDF)
    n = len(lines)
    research._doc_link_own_numbers(numbered, "ChatGPT", quiet=True)
    assert len(lines) == n
    research._doc_link_own_numbers(numbered, "ChatGPT")
    assert len(lines) == n + 1


@pytest.mark.parametrize("change", [
    lambda s: s.replace("— cited as 4\n", "— cited as 4\nA line of prose.\n", 1),
    lambda s: s.replace("— cited as 19\n", "— cited as 19, 4\n", 1),
    lambda s: s.replace("##### Sources\n", "##### Sources used\n", 1),
    lambda s: s.replace("[Audits – CrypticDefense Audits]", "[Audits `x` CrypticDefense]", 1),
], ids=["prose-row", "number-twice", "other-heading", "code-in-a-row"])
def test_a_list_not_in_chatgpts_shape_links_nothing(lines, change):
    """Only OUR shape of ChatGPT's list is read as its list: every row a source
    with the numbers citing it, each number once, under "Sources"."""
    numbered = change(research._chatgpt_document_from_exports(MD, PDF))
    assert research._doc_own_list_rows(numbered) == {}
    assert not MARKER_RE.search(research._doc_link_own_numbers(numbered, "ChatGPT"))


def test_a_source_on_an_agents_own_page_keeps_its_number_as_text(monkeypatch, lines):
    """A source we would never put behind a number (ChatGPT's own help page)
    keeps its title and address as words, and its numbers stay `[n]`; every
    other number still links."""
    help_url = "https://help.openai.com/en/articles/1"

    def change(t):
        for i, (n, _u) in enumerate(t["body"]):
            if n == 4:
                t["body"][i] = [4, help_url]
        t["sources"][3]["urls"] = [help_url]
        t["sources"][3]["url"] = help_url
    monkeypatch.setattr(research, "_chatgpt_pdf_table", _table_with(change))
    doc = research._chatgpt_pdf_footnotes(MD, PDF)
    assert "\n- Audits – CrypticDefense Audits — help.openai.com/en/articles/1 — cited as 4\n" in doc
    marks = MARKER_RE.findall(doc)
    plain = PLAIN_RE.findall(doc[:doc.index(TAIL)])
    assert plain and set(plain) == {"4"}
    assert len(marks) + len(plain) == 141
    assert help_url not in [u for _n, u in marks]


# ═══ 3. The catcher, executed: node runs its own script against a page ═══════

#: A stand-in for the page the catcher goes on: node's own `URL.createObjectURL`
#: and `Blob`, an anchor whose `click()` dispatches a click to the window's
#: listeners and then — unless one cancelled it — DOWNLOADS (the browser's
#: default for an `<a download>`), and a way to click without `click()` (a
#: dispatched event, or a real press).
_PAGE = r"""
const DOWNLOADS = [], NAVIGATED = [], LISTENERS = [];
globalThis.window = globalThis;
window.addEventListener = (type, fn, capture) => { if (type === 'click') LISTENERS.push(fn); };
class HTMLAnchorElement {
  constructor(href, download) {
    this.attrs = {};
    if (href !== undefined) this.attrs.href = href;
    if (download !== undefined) this.attrs.download = download;
  }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  get href() { return this.attrs.href || ''; }
  closest(sel) { return sel === 'a[download]' && this.hasAttribute('download') ? this : null; }
  click() { press(this); }
}
globalThis.HTMLAnchorElement = HTMLAnchorElement;
function press(a) {
  const e = { target: a, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  for (const fn of LISTENERS) fn(e);
  if (e.defaultPrevented) return;
  if (a.hasAttribute('download')) DOWNLOADS.push(a.getAttribute('download'));
  else NAVIGATED.push(a.href);
}
"""


def _node(script):
    """Run `script` after the stand-in page and the catcher's own install; it
    ends by assigning `OUT`. Returns OUT, with what was downloaded."""
    if _domshim.NODE is None:
        pytest.skip("node is not installed")
    js = (_PAGE + "\nconst INSTALL = (" + research._EXPORT_CATCH_JS + ");\n"
          + "const LIST = (" + research._EXPORT_CATCH_LIST_JS + ");\n"
          + "const READ = (" + research._EXPORT_CATCH_READ_JS + ");\n"
          + "let OUT = {};\n(async () => {\n" + script
          + "\nOUT.downloads = DOWNLOADS; OUT.navigated = NAVIGATED;\n"
          + "console.log(JSON.stringify(OUT));\n})().catch((e) => { console.log(JSON.stringify("
          + "{error: String(e && e.stack || e)})); });\n")
    with tempfile.TemporaryDirectory(prefix="sr_catch_") as d:
        path = os.path.join(d, "run.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(js)
        p = subprocess.run([_domshim.NODE, path], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout.strip().split("\n")[-1])
    assert "error" not in out, out["error"]
    return out


def test_the_exports_click_is_cancelled_and_its_file_kept():
    """⭐⭐ THE RECORDING'S SHAPE: the page makes a Blob into an address, puts
    it on an `<a download>` and calls `click()`. Chrome is never asked to
    download it: the catcher keeps the file, its name, type and size."""
    out = _node(r"""
      OUT.armed = INSTALL();
      const blob = new Blob(['# Report\n\nText.'], {type: 'text/markdown;charset=utf-8'});
      const a = new HTMLAnchorElement(URL.createObjectURL(blob), 'deep-research-report.md');
      a.click();
      OUT.list = LIST();
    """)
    assert out["armed"] == {"armed": True, "again": False}
    assert out["downloads"] == []
    assert out["list"] == [{"id": 1, "name": "deep-research-report.md",
                            "type": "text/markdown;charset=utf-8", "size": 15,
                            "via": "anchor.click()"}]


def test_a_dispatched_or_real_click_is_cancelled_too():
    """A click that does not go through `click()` — dispatched by the page, or a
    real press by computer use — is cancelled by the window's own listener."""
    out = _node(r"""
      INSTALL();
      const a = new HTMLAnchorElement(URL.createObjectURL(new Blob(['%PDF-1.7'],
          {type: 'application/pdf'})), 'Report.pdf');
      press(a);
      OUT.list = LIST();
    """)
    assert out["downloads"] == []
    assert [(c["name"], c["type"], c["via"]) for c in out["list"]] == [
        ("Report.pdf", "application/pdf", "click event")]


def test_the_file_comes_back_byte_for_byte_in_pieces():
    """Every byte value, read back as base64 a piece at a time, is the file."""
    out = _node(r"""
      INSTALL();
      const bytes = new Uint8Array(70000);
      for (let i = 0; i < bytes.length; i++) bytes[i] = (i * 7) % 256;
      new HTMLAnchorElement(URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'})),
                            'x.pdf').click();
      OUT.whole = await READ({id: 1, start: 0, end: 70000});
      OUT.parts = [await READ({id: 1, start: 0, end: 40000}),
                   await READ({id: 1, start: 40000, end: 70000})];
      OUT.gone = await READ({id: 9, start: 0, end: 10});
    """)
    want = bytes((i * 7) % 256 for i in range(70000))
    assert base64.b64decode(out["whole"]) == want
    assert b"".join(base64.b64decode(p) for p in out["parts"]) == want
    assert out["gone"] is None


def test_only_an_export_of_the_pages_own_file_is_stopped():
    """A link to a web address with `download`, a blob link with no `download`,
    and a file the page already let go of are not the catcher's: they behave as
    they always did."""
    out = _node(r"""
      INSTALL();
      new HTMLAnchorElement('https://example.org/data.csv', 'data.csv').click();
      const u = URL.createObjectURL(new Blob(['x'], {type: 'text/plain'}));
      new HTMLAnchorElement(u).click();
      const v = URL.createObjectURL(new Blob(['y'], {type: 'text/markdown'}));
      URL.revokeObjectURL(v);
      new HTMLAnchorElement(v, 'late.md').click();
      OUT.list = LIST();
    """)
    assert out["list"] == []
    assert out["downloads"] == ["data.csv", "late.md"]
    assert len(out["navigated"]) == 1


def test_a_file_let_go_after_its_click_is_still_read_back():
    """The page lets the address go right after its click (as file-savers do):
    the catcher holds the file itself, not its address."""
    out = _node(r"""
      INSTALL();
      const u = URL.createObjectURL(new Blob(['kept'], {type: 'text/markdown'}));
      new HTMLAnchorElement(u, 'r.md').click();
      URL.revokeObjectURL(u);
      OUT.b64 = await READ({id: 1, start: 0, end: 4});
    """)
    assert base64.b64decode(out["b64"]) == b"kept"


def test_putting_it_on_twice_is_once_and_it_holds_only_the_last_sixteen():
    out = _node(r"""
      INSTALL();
      OUT.again = INSTALL();
      const urls = [];
      for (let i = 0; i < 20; i++) urls.push(URL.createObjectURL(new Blob(['b' + i])));
      new HTMLAnchorElement(urls[0], 'first.md').click();
      for (let i = 4; i < 24; i++) new HTMLAnchorElement(urls[Math.min(i, 19)], 'n' + i + '.md').click();
      OUT.list = LIST();
    """)
    assert out["again"] == {"armed": True, "again": True}
    # the first Blob was let go of when the seventeenth was made: Chrome would
    # download it — no page makes twenty files for one export
    assert out["downloads"] == ["first.md"]
    assert len(out["list"]) == 16 and out["list"][0]["id"] == 5


@pytest.mark.parametrize("entry,kind", [
    ({"type": "text/markdown;charset=utf-8", "name": "deep-research-report.md"}, "markdown"),
    ({"type": "", "name": "report.md"}, "markdown"),
    ({"type": "text/plain", "name": "report.markdown"}, "markdown"),
    ({"type": "application/pdf", "name": "Report.pdf"}, "pdf"),
    ({"type": "application/octet-stream", "name": "Report.pdf"}, "pdf"),
    ({"type": "text/plain", "name": "notes.pdf"}, "other"),
    ({"type": "application/json", "name": "x.json"}, "other"),
])
def test_what_a_caught_file_is(entry, kind):
    assert research._export_kind(entry) == kind


# ═══ 4. In Chrome: ChatGPT's two exports, caught on the top page ═════════════
# The page is local: a chatgpt.com-like top page holding the Deep research app's
# frame. The frame shows the report's Export control and its menu; a row posts
# to the top page, which makes the file exactly as the owner's recording shows —
# `URL.createObjectURL(Blob)`, then `click()` on an `<a download>` — with the
# pair's real bytes. ⚠ ASSUMED: how the frame tells the top page (a message):
# no recording reaches inside the frame; the top page's half is recorded.

APP = "http://mcp-app-sr1002.web-sandbox.oaiusercontent.com.sr-fixture.invalid/"
HOST = "http://sr-fixture.invalid/c/exports-1002"
PDF_NAME = ("Papertrade — Full Documentation Review, Investment Memo, and Prioritized "
            "Action Plan.pdf")


def _host_html(md, pdf, *, via="click"):
    data = json.dumps({"md": md, "pdf": base64.b64encode(pdf or b"").decode()})
    return ("<!doctype html><html><head><meta charset='utf-8'><title>ChatGPT</title></head>"
            "<body><main><div data-message-author-role='assistant'>"
            f"<iframe src='{APP}' title='Deep research' style='width:900px;height:640px;border:0'>"
            "</iframe></div></main><script>\n"
            f"const DATA = {data};\nconst VIA = {json.dumps(via)};\n"
            r"""window.__srMade = [];
            const save = (kind) => {
              let blob, name;
              if (kind === 'md') {
                blob = new Blob([DATA.md], {type: 'text/markdown;charset=utf-8'});
                name = 'deep-research-report.md';
              } else {
                const raw = atob(DATA.pdf), b = new Uint8Array(raw.length);
                for (let i = 0; i < raw.length; i++) b[i] = raw.charCodeAt(i);
                blob = new Blob([b], {type: 'application/pdf'});
                name = """ + json.dumps(PDF_NAME) + r""";
              }
              const a = document.createElement('a');
              a.href = URL.createObjectURL(blob);
              a.download = name;
              document.body.appendChild(a);
              if (VIA === 'event') a.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
              else a.click();
              a.remove();
              setTimeout(() => URL.revokeObjectURL(a.href), 100);
              window.__srMade.push(kind);
            };
            window.__srSave = save;
            window.addEventListener('message', (e) => { if (e.data && e.data.srExport) save(e.data.srExport); });
            </script></body></html>""")


def _app_html(rows=("Export to Markdown", "Export to Word", "Export to PDF"), *, export=True,
              report=""):
    menu = "".join(f'<div role="menuitem" tabindex="-1">{r}</div>' for r in rows)
    head = ('<header style="display:flex;justify-content:flex-end;height:48px">'
            '<button type="button" aria-label="Expand"><svg width="12" height="12"></svg></button>'
            '<button type="button" id="exp" aria-label="Export" aria-haspopup="menu">'
            '<svg width="12" height="12"></svg></button>'
            f'</header><div role="menu" id="menu" hidden>{menu}</div>') if export else ""
    return ("<!doctype html><html><head><meta charset='utf-8'></head><body>" + head
            + "<article>" + report + "</article><script>"
            r"""const press = (w) => { const p = JSON.parse(document.body.dataset.srPressed || '[]');
              p.push(w); document.body.dataset.srPressed = JSON.stringify(p); };
            const exp = document.getElementById('exp');
            if (exp) exp.addEventListener('click', () => { press('Export');
              document.getElementById('menu').hidden = false; });
            for (const r of document.querySelectorAll('[role=menuitem]')) r.addEventListener('click', () => {
              press(r.textContent); document.getElementById('menu').hidden = true;
              const kind = /markdown/i.test(r.textContent) ? 'md' : /pdf/i.test(r.textContent) ? 'pdf' : '';
              if (kind) window.top.postMessage({srExport: kind}, '*'); });
            </script></body></html>""")


#: A report the frame holds, for when no export is caught (⚠ ASSUMED markup).
FRAME_REPORT = ("<h1>Papertrade — Full Documentation Review</h1><h2>Executive memo</h2>"
                + "".join(f"<p>{'Paragraph %d of the report, read off the frame. ' % i * 6}</p>"
                          for i in range(12)))


def _serve(chrome, page, host_html, app_html):
    async def _route(route):
        u = route.request.url
        if u == HOST:
            await route.fulfill(status=200, content_type="text/html", body=host_html)
        elif u.startswith(APP):
            await route.fulfill(status=200, content_type="text/html", body=app_html)
        else:
            await route.abort()

    async def _go():
        await page.unroute("**/*")
        await page.route("**/*", _route)
        await page.goto(HOST)
        for _ in range(100):
            fr = next((f for f in page.frames if (f.url or "").startswith(APP)), None)
            if fr is not None:
                try:
                    if await fr.evaluate("() => document.readyState") == "complete":
                        return
                except Exception:
                    pass
            await asyncio.sleep(0.05)
        raise AssertionError("the app's frame never loaded")

    chrome.run(_go())


def _pressed(chrome, page):
    fr = next(f for f in page.frames if (f.url or "").startswith(APP))
    return json.loads(chrome.run(fr.evaluate("() => document.body.dataset.srPressed || '[]'")))


def _made(chrome, page):
    """The files the top page made (its own script's record, in the page's world)."""
    return chrome.run(research._page_world_evaluate(page, "() => window.__srMade"))


def _downloads(page):
    got = []
    page.on("download", lambda d: got.append(d))
    return got


@pytest.fixture(autouse=True)
def run_dir(tmp_path, monkeypatch):
    """Every census goes to a temporary folder, never the machine's logs."""
    monkeypatch.setattr(research, "_active_run_sink", lambda: SimpleNamespace(dir=tmp_path))
    monkeypatch.setattr(research, "_CHATGPT_DR_CENSUS_SEEN", {}, raising=False)
    return tmp_path


class _Browser:
    def __init__(self, page):
        self.page = page

    async def switch_to_page(self, page):
        return None


def _extract(chrome, page, **kw):
    return chrome.run(research.extract_chatgpt_response(page, browser=_Browser(page), **kw))


@pytest.mark.parametrize("via", ["click", "event"])
def test_both_exports_are_caught_and_chrome_downloads_nothing(chrome, page, fast, lines, via):
    """⭐⭐ THE NO-DOWNLOAD RULE, ON THE RECORDING'S SHAPE. The page presses
    Export → "Export to Markdown", then Export → "Export to PDF", inside the app's
    frame; the top page makes each file and clicks its link — by `click()` as
    recorded, or by a dispatched click — and Chrome downloads NOTHING. The
    Markdown is the document, numbered from the PDF."""
    _serve(chrome, page, _host_html(MD, PDF, via=via), _app_html(report=FRAME_REPORT))
    downloads = _downloads(page)
    md = _extract(chrome, page, cua_client=None)
    assert downloads == [], "Chrome downloaded a report file"
    assert _made(chrome, page) == ["md", "pdf"]
    assert _pressed(chrome, page) == ["Export", "Export to Markdown", "Export", "Export to PDF"]
    assert research._doc_link_own_numbers(md, "ChatGPT") == GOLDEN
    caught = _said(lines, "export caught in the page, no download")
    assert len(caught) == 2, caught
    assert "markdown \"deep-research-report.md\", %d bytes" % len(MD.encode()) in caught[0]
    assert "pdf \"%s\", %d bytes" % (PDF_NAME, len(PDF)) in caught[1]
    via_word = "anchor.click()" if via == "click" else "click event"
    assert all(via_word in c for c in caught), caught
    assert _said(lines, "Chrome downloads seen during the export: 0")
    assert _said(lines, "Extracted via ChatGPT's Markdown export, caught in the page")
    assert not _said(lines, "Extracted via the Deep research app's frame")


def test_the_saved_document_and_its_cloud_copy_carry_the_links(chrome, page, fast, lines,
                                                              monkeypatch, tmp_path):
    """⭐⭐ THROUGH THE REAL WRITE. The per-agent write saves the caught export
    with ChatGPT's own numbers linked and its one Sources list — on disk and in
    the copy the app reads — and the visited sites the run tracked are NOT added
    after it: the document ends with one sources section."""
    sink = _firestore(monkeypatch)
    runtime = research.PipelineRuntime()
    monkeypatch.setattr(research, "_runtime", runtime, raising=False)
    visited = ["https://visited-only.example.org/a", "https://visited-two.example.org/b"]
    runtime.agent_progress_snapshots["chatgpt"] = {"source_urls": visited}
    research._p2_fold_visited_sources("chatgpt", {"source_urls": visited})
    monkeypatch.setattr(research, "reject_off_topic_text", lambda text, *a, **k: text)

    async def _same(text, **k):
        return text
    monkeypatch.setattr(research, "_rehost_document_images", _same)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    _serve(chrome, page, _host_html(MD, PDF), _app_html(report=FRAME_REPORT))
    downloads = _downloads(page)
    res = chrome.run(research.extract_and_record_agent(
        "ChatGPT", page, _Browser(page), None, tmp_path))
    local = (tmp_path / "documents" / "chatgpt.md").read_text(encoding="utf-8")
    assert downloads == []
    assert res["status"] == "done"
    assert local == HEADER + GOLDEN
    assert [d["content"] for p, d in sink if p.endswith("/documents/chatgpt")] == [local]
    assert "visited-only" not in local and local.count("\n##### Sources\n") == 1
    assert _said(lines, "[ChatGPT] linked 141 of its own citation numbers")


def test_no_pdf_caught_keeps_todays_document_and_its_visited_sites(chrome, page, fast, lines,
                                                                   monkeypatch, tmp_path):
    """The menu offers no PDF (or it never comes): the Markdown export is still
    the document, its citations removed as before, and the write ends it with
    the sites ChatGPT visited — today's behaviour, said in the log."""
    _serve(chrome, page, _host_html(MD, PDF), _app_html(rows=("Export to Markdown",),
                                                         report=FRAME_REPORT))
    downloads = _downloads(page)
    md = _extract(chrome, page, cua_client=None)
    assert downloads == [] and _made(chrome, page) == ["md"]
    assert md == research._strip_chatgpt_citation_tokens(MD)
    assert _said(lines, 'Deep research pdf export by the page: pressed ["Export"] but no '
                        'file was caught')
    assert _said(lines, "no PDF export was caught")
    doc = research._document_with_sources(HEADER + md, visited=[
        "https://visited-only.example.org/a"], label="ChatGPT")
    assert doc.endswith("\n\n##### Sources\n\n1. [visited-only.example.org/a]"
                        "(https://visited-only.example.org/a)\n")


def test_a_pdf_that_does_not_match_writes_no_link(chrome, page, fast, lines):
    """⛔⛔ The Markdown and the PDF are not one report (a run dropped): nothing
    is linked, the export's runs come out as before, and the log says why."""
    _serve(chrome, page, _host_html(_cut_run(MD, 3), PDF), _app_html(report=FRAME_REPORT))
    md = _extract(chrome, page, cua_client=None)
    assert md == research._strip_chatgpt_citation_tokens(_cut_run(MD, 3))
    said = _said(lines, "no source links from ChatGPT's PDF export")
    assert len(said) == 1 and "141 numbered citations in the PDF, 140 in the Markdown" in said[0]


def test_nothing_is_pressed_without_the_catcher(chrome, page, fast, lines, monkeypatch):
    """⛔ The export is never pressed when the catcher cannot be put on the
    page: the report is read off the app's frame instead, nothing downloads."""
    real = research._page_world_evaluate

    async def _no_catcher(target, js, *a, **k):
        if js == research._EXPORT_CATCH_JS:
            raise RuntimeError("the page refused the script")
        return await real(target, js, *a, **k)
    monkeypatch.setattr(research, "_page_world_evaluate", _no_catcher)
    _serve(chrome, page, _host_html(MD, PDF), _app_html(report=FRAME_REPORT))
    downloads = _downloads(page)
    md = _extract(chrome, page, cua_client=None)
    assert _pressed(chrome, page) == [] and downloads == []
    assert md.startswith("# Papertrade — Full Documentation Review")
    assert _said(lines, "the export catcher could not be put on the page")
    assert _said(lines, "Extracted via the Deep research app's frame (no download)")


def test_no_export_control_and_no_computer_use_reads_the_frame(chrome, page, fast, lines):
    """No Export control in the frame and no computer use: nothing is pressed,
    a census of the miss is written, and the report is read off the frame."""
    _serve(chrome, page, _host_html(MD, PDF), _app_html(export=False, report=FRAME_REPORT))
    md = _extract(chrome, page, cua_client=None)
    assert _made(chrome, page) == []
    assert md.startswith("# Papertrade — Full Documentation Review")
    assert _said(lines, "Deep research markdown export by the page: no export control")


class _ExportingCua:
    """Computer use, stood in: each loop "presses" the export the prompt names
    — the top page makes that file and clicks its link — then keeps looping
    (as the vision agent re-clicks a menu row that does not visibly close)
    until the catch stops it."""

    def __init__(self, page):
        self.page, self.prompts, self.presses = page, [], 0

    async def loop(self, client, browser, prompt, msg, *, abort_event=None, **k):
        self.prompts.append(prompt)
        kind = "pdf" if prompt is research.PROMPT_CHATGPT_EXPORT_PDF else "md"
        for _ in range(40):
            if abort_event is not None and abort_event.is_set():
                return {"status": "aborted"}
            self.presses += 1
            await research._page_world_evaluate(self.page, "(k) => window.__srSave(k)", kind)
            for _ in range(10):
                if abort_event is not None and abort_event.is_set():
                    return {"status": "aborted"}
                await asyncio.sleep(0.05)
        return {"status": "done"}


def test_computer_use_presses_when_the_page_cannot_and_stops_at_the_catch(
        chrome, page, fast, lines, monkeypatch):
    """No Export control the page can find: computer use presses each export
    (Markdown with the Markdown prompt, then PDF with the PDF prompt), and the
    first file caught stops it before another press — no download either way."""
    cua = _ExportingCua(page)
    monkeypatch.setattr(research, "agent_loop", cua.loop)
    _serve(chrome, page, _host_html(MD, PDF), _app_html(export=False, report=FRAME_REPORT))
    downloads = _downloads(page)
    md = _extract(chrome, page, cua_client=object())
    assert downloads == []
    assert cua.prompts == [research.PROMPT_CHATGPT_DOWNLOAD_MD, research.PROMPT_CHATGPT_EXPORT_PDF]
    assert cua.presses == 2, "computer use pressed again after the file was caught"
    assert _made(chrome, page) == ["md", "pdf"]
    assert research._doc_link_own_numbers(md, "ChatGPT") == GOLDEN


def test_a_file_caught_before_the_press_is_not_this_export(chrome, page, fast, lines):
    """A Markdown file the page made earlier (the catcher already on) is not the
    one this press made: each press takes only a file caught after it began."""
    _serve(chrome, page, _host_html(MD, PDF), _app_html(report=FRAME_REPORT))
    assert chrome.run(research._export_catch_arm(page, "ChatGPT"))
    chrome.run(research._page_world_evaluate(page, """() => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob(['# An earlier file\\n\\n' + 'x'.repeat(900)],
                                              {type: 'text/markdown'}));
        a.download = 'earlier.md'; document.body.appendChild(a); a.click(); a.remove(); }"""))
    md = _extract(chrome, page, cua_client=None)
    assert research._doc_link_own_numbers(md, "ChatGPT") == GOLDEN


def test_a_download_the_catcher_misses_is_logged(chrome, page, fast, lines, monkeypatch):
    """⛔ A file the catcher cannot stop (here an export made from a `data:`
    address, not the page's own Blob) is downloaded by Chrome — and the log
    says so, every time, with the count at the end of the export."""
    monkeypatch.setattr(research, "_CHATGPT_DR_FILE_S", 1.0)
    host = _host_html(MD, PDF).replace(
        "a.href = URL.createObjectURL(blob);",
        "a.href = 'data:text/markdown;base64,' + btoa('# Missed\\n');")
    _serve(chrome, page, host, _app_html(report=FRAME_REPORT))
    downloads = _downloads(page)
    _extract(chrome, page, cua_client=None)
    assert len(downloads) == 1, "the stand-in no longer makes a download the catcher misses"
    said = _said(lines, "Chrome started a download during the export")
    assert len(said) == 1 and "deep-research-report.md" in said[0], said
    assert _said(lines, "Chrome downloads seen during the export: 1")


def test_an_export_that_is_a_sources_list_is_not_the_report(chrome, page, fast, lines):
    """The Markdown export that is a list of addresses (the wrong artifact) is
    not the document: the PDF is not pressed and the report is read off the
    frame."""
    sources = "## Sources\n\n" + "".join(
        f"{i}. https://www.example-source-{i:02d}.org/research/papertrade/page\n" for i in range(40))
    assert research._is_sources_not_document(sources, platform="chatgpt")
    _serve(chrome, page, _host_html(sources, PDF), _app_html(report=FRAME_REPORT))
    md = _extract(chrome, page, cua_client=None)
    assert _made(chrome, page) == ["md"]
    assert md.startswith("# Papertrade — Full Documentation Review")
    assert _said(lines, "the Markdown export is a sources list")


def test_computer_use_presses_when_there_is_no_app_frame(chrome, page, fast, lines,
                                                         monkeypatch):
    """No Deep research frame at all (the older page): computer use presses the
    exports, the catcher takes both files, Chrome downloads nothing."""
    cua = _ExportingCua(page)
    monkeypatch.setattr(research, "agent_loop", cua.loop)
    host = _host_html(MD, PDF).replace(
        f"<iframe src='{APP}' title='Deep research' style='width:900px;height:640px;border:0'>"
        "</iframe>", "<p>The report card.</p>")
    assert APP not in host

    async def _route(route):
        if route.request.url == HOST:
            await route.fulfill(status=200, content_type="text/html", body=host)
        else:
            await route.abort()

    async def _go():
        await page.unroute("**/*")
        await page.route("**/*", _route)
        await page.goto(HOST)
    chrome.run(_go())
    downloads = _downloads(page)
    md = _extract(chrome, page, cua_client=object())
    assert downloads == [] and cua.presses == 2
    assert research._doc_link_own_numbers(md, "ChatGPT") == GOLDEN


def test_a_citation_inside_code_is_removed_not_numbered():
    """A run inside inline code is code, not a citation in the prose: it is
    removed (as every run was before) and no number is written into the code;
    every other run is numbered and linked."""
    run = RUN_RE.search(MD).group(0)
    k = MD.index(run)
    md = MD[:k] + "`" + run + "`" + MD[k + len(run):]
    doc = research._chatgpt_pdf_footnotes(md, PDF)
    assert len(MARKER_RE.findall(doc)) == 140
    assert "``" in doc and "`\\[1\\]`" not in doc and run not in doc


def test_a_title_with_a_backtick_still_links(monkeypatch):
    """A source's title with a backtick in it would make a code span of its
    row, which the list's reader refuses; the backtick becomes a quote."""
    def change(t):
        t["sources"][3]["title"] = "Audits – `CrypticDefense` Audits"
    monkeypatch.setattr(research, "_chatgpt_pdf_table", _table_with(change))
    doc = research._chatgpt_pdf_footnotes(MD, PDF)
    assert "[Audits – 'CrypticDefense' Audits](https://crypticdefense.com/audits/)" in doc
    assert len(MARKER_RE.findall(doc)) == 141


def test_a_row_opening_an_agents_own_page_is_not_read_as_a_link():
    """The list's reader never puts one of the agents' own pages behind a
    number, even in a row written as a link."""
    numbered = research._chatgpt_document_from_exports(MD, PDF).replace(
        "- [Audits – CrypticDefense Audits](https://crypticdefense.com/audits/)",
        "- [Audits – CrypticDefense Audits](https://help.openai.com/x)")
    rows = research._doc_own_list_rows(numbered)
    assert 4 not in rows and len(rows) == 58


def _one_page_pdf(runs, links):
    """A one-page PDF: text runs `(text, x, y, size)` set in Helvetica, and link
    annotations `(rect, address)` — enough to put a chip where this file wants."""
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                               FloatObject, NameObject, TextStringObject)
    w = PdfWriter()
    pg = w.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    pg[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject(
        {NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data("".join("BT /F1 %s Tf %s %s Td (%s) Tj ET\n" % (s, x, y, t)
                            for t, x, y, s in runs).encode("latin-1"))
    pg[NameObject("/Contents")] = w._add_object(stream)
    annots = ArrayObject()
    for rect, uri in links:
        annots.append(w._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
            NameObject("/A"): DictionaryObject({NameObject("/S"): NameObject("/URI"),
                                                NameObject("/URI"): TextStringObject(uri)})})))
    pg[NameObject("/Annots")] = annots
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def test_a_chips_number_is_read_by_its_size_not_the_words_beside_it():
    """A chip's number is the SMALL text in it: words set at the body's size that
    start inside its box (a tight line) are not part of the number."""
    pdf = _one_page_pdf([("5", 103, 700, 6), ("next", 108, 701, 9)],
                        [((99, 698, 111, 709.25), "https://a.example.org/")])
    assert _REAL_TABLE(pdf)["body"] == [(5, "https://a.example.org/")]
