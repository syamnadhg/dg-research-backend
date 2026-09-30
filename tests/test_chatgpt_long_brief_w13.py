"""A LONG Pro brief on ChatGPT's new page (wave 13): the default page read, and
the Copy fallback behind it — measured in real headless Chrome.

The owner captured a finished Pro brief's page, structure only with text as
lengths (tests/fixtures/chatgpt_0928/chatgpt-copy-button-capture.json). Its
reply is a 38,715-character brief: an H1, H2 and H3 sections, paragraphs with
bold runs, a quote, inline code written as a span ChatGPT marks
data-markdown-copy="inline-code", tables with their own "Copy table" /
"Expand table" row, and source chips — a link to the source holding the
site's icon and name (a[data-testid="chatgpt-citation"]).
long_brief_reply.html rebuilds that reply with synthetic text; the first block
below pins it, and every Copy button on the page, to the capture.

⛔ WHAT THE PAGE READ GOT WRONG ON IT. HTML→markdown wrote every source chip as
a link wrapped around an IMAGE of the site's icon — `[![](<icon>)Site](url)` —
twenty of them in one brief, each an image the document funnel would try to
fetch and keep; and it wrote the inline code as plain prose, its underscores
escaped (`HD\\_score`). Headings, the quote, bold runs and the tables were
already right; the tables' own buttons carry no text, so none reaches the brief.

The page is served from memory at a local address (page.route); nothing leaves
the machine.
"""
import json
import re
from collections import Counter

import research
import test_chatgpt_copy_fallback_w13 as cf

base = cf.base
chrome = cf.chrome
page = cf.page
fast = cf.fast
logs = cf.logs
quick = cf.quick
p1 = cf.p1

CAPTURE = json.loads((base.FIX / "chatgpt-copy-button-capture.json").read_text(encoding="utf-8"))
ROOT = '[data-selected-text-overlay-target]'

#: Attributes whose values belong to one conversation (its ids) or are the
#: page's own words (a chip's aria-label names the real source): the fixture
#: carries them, with its own values.
_OWN_VALUES = {"data-turn-key", "data-chatgpt-selection-conversation-id",
               "data-chatgpt-selection-message-id", "data-selected-text-overlay-target"}


def _same_attrs(cap, got, where):
    for k, v in cap.items():
        assert k in got, f"{where}: attribute {k} missing"
        if k in _OWN_VALUES or (k == "aria-label" and got.get("data-testid") == "chatgpt-citation"):
            continue
        if v.startswith("<") and v.endswith(" chars>"):
            assert len(got[k]) == int(v[1:].split()[0]), f"{where}: {k} length"
        elif k == "class":
            # The capture cuts class values; the fixture carries the cut value.
            assert got[k].startswith(v), f"{where}: class {got[k]!r} vs {v!r}"
        else:
            assert got[k] == v, f"{where}: {k}={got[k]!r}, captured {v!r}"


_TREE_JS = """(el) => {
    const walk = (n) => ({ tag: n.tagName, textLen: n instanceof HTMLElement ? n.innerText.length : null,
        attrs: Object.fromEntries([...n.attributes].map((a) => [a.name, a.value])),
        kids: [...n.children].map(walk) });
    return walk(el);
}"""


def _same_tree(cap, got, where, in_button=False):
    assert got["tag"].upper() == cap["tag"].upper(), f"{where}: {got['tag']} vs {cap['tag']}"
    _same_attrs(cap.get("attrs") or {}, got["attrs"], where)
    # Text lengths as captured — except under a button, whose icons the capture
    # measured hidden (one reads a single blank character there).
    if cap.get("textLen") is not None and not in_button:
        assert got["textLen"] == cap["textLen"], f"{where}: {got['textLen']} chars, captured {cap['textLen']}"
    ckids, gkids = cap.get("kids") or [], got["kids"]
    assert len(gkids) == len(ckids), f"{where}: {len(gkids)} children, captured {len(ckids)}"
    for i, (ck, gk) in enumerate(zip(ckids, gkids)):
        _same_tree(ck, gk, f"{where}/{ck['tag']}[{i}]", in_button or cap["tag"] == "BUTTON")


def _fold_turn_wrapper(ancestors):
    """⚠ Between the two captures ChatGPT split one of the turn's wrappers in
    two: 2026-09-28's `div.flex.flex-col.gap-1.5[data-content-search-turn-key]`
    (chatgpt-reply-capture2.json, which the fixture keeps and
    test_chatgpt_new_page_0928 pins) is, on 2026-09-29, `div.flex.flex-col.
    gap-1.5` around a bare `div[data-content-search-turn-key]`. Folded back
    into one here; nothing else is."""
    out = []
    for a in ancestors:
        if (out and set(a["attrs"]) == {"data-content-search-turn-key"}
                and out[-1]["attrs"].get("class") == "flex flex-col gap-1.5"):
            out[-1] = {**out[-1], "attrs": {**out[-1]["attrs"], **a["attrs"]}}
        else:
            out.append(a)
    return out


def _open_long(chrome, page, **kw):
    cf._open(chrome, page, "new", thread=True, long_brief=True, **kw)


# ═══ 0. The fixture IS the captured reply ════════════════════════════════════

def test_live_the_long_brief_is_the_captured_reply(chrome, page):
    """Its first 60 children tag for tag, attribute for attribute and character
    count for character count (the capture cut children at 60); the reply's
    length within 1%; at least the captured count of every tag; the four tables
    the capture's "Copy table" buttons prove, at their captured lengths; and the
    chain of elements from the reply up to its turn."""
    _open_long(chrome, page)
    cap = CAPTURE["lastReply"]
    root = chrome.run(page.query_selector(ROOT))
    got = chrome.run(root.evaluate(_TREE_JS))
    for i, ck in enumerate(cap["tree"]["kids"]):
        _same_tree(ck, got["kids"][i], f"reply/{ck['tag']}[{i}]")
    assert len(cap["tree"]["kids"]) == 60 and len(got["kids"]) > 60
    assert abs(got["textLen"] - cap["tree"]["textLen"]) <= 0.01 * cap["tree"]["textLen"], got["textLen"]
    counts = Counter()

    def _count(n):
        counts[n["tag"].upper()] += 1
        for k in n["kids"]:
            _count(k)

    _count(got)
    for tag, n in (("P", 45), ("H1", 1), ("H2", 6), ("H3", 7), ("TABLE", 1), ("STRONG", 11),
                   ("BLOCKQUOTE", 1), ("BR", 5), ("A", 6), ("IMG", 6), ("BUTTON", 2), ("SPAN", 134)):
        assert counts[tag] >= n, (tag, counts[tag])
    assert counts["H1"] == 1
    tables = chrome.run(page.evaluate(
        "() => [...document.querySelectorAll('[data-markdown-table]')].map((t) => t.innerText.length)"))
    want = [b["ancestors"][2]["textLen"] for b in CAPTURE["copyButtons"]
            if b["button"]["attrs"]["aria-label"] == "Copy table"]
    assert want == [1345, 1586, 752, 2155] and len(tables) == 4
    for g, w in zip(tables, want):
        assert abs(g - w) <= 0.01 * w, (tables, want)
    up = chrome.run(root.evaluate("""(el) => { const out = []; let a = el.parentElement;
        for (let i = 0; i < 12 && a; i++, a = a.parentElement) out.push({ tag: a.tagName,
            attrs: Object.fromEntries([...a.attributes].map((x) => [x.name, x.value])) });
        return out; }"""))
    chain = _fold_turn_wrapper(cap["ancestors"])
    assert len(chain) == len(cap["ancestors"]) - 1        # the one split wrapper, folded
    for i, ca in enumerate(chain):
        assert up[i]["tag"] == ca["tag"], (i, up[i]["tag"])
        _same_attrs(ca["attrs"], up[i]["attrs"], f"reply ancestor {i}")


_BUTTONS_JS = """() => [...document.querySelectorAll('button[aria-label^="Copy"]')].map((b) => {
    const row = b.closest('.turn-action-controls, [data-block-actions]');
    const up = []; let a = b.parentElement;
    for (; a; a = a.parentElement) {
        up.push({ tag: a.tagName, attrs: Object.fromEntries([...a.attributes].map((x) => [x.name, x.value])) });
        if (a.hasAttribute('data-turn-key')) break;
    }
    return { label: b.getAttribute('aria-label'),
             attrs: Object.fromEntries([...b.attributes].map((x) => [x.name, x.value])),
             siblingLabels: [...row.querySelectorAll('button')].map((x) => x.getAttribute('aria-label')),
             inTurnKey: !!b.closest('[data-turn-key]'),
             inAssistantUnit: !!b.closest('[data-chatgpt-search-unit-key$=":assistant"]'),
             inReplyText: !!b.closest('[data-markdown-text-style="assistant-message"]'),
             inCodeBlock: !!b.closest('pre, code'), ancestors: up };
})"""

#: ⚠ The user's own block changed between the two captures (2026-09-28's
#: chatgpt-reply-capture2.json, which the fixture's user block follows and
#: test_chatgpt_new_page_0928 pins, and this one): two class strings, and the
#: unit's class moved onto a new wrapper. So under "Copy message" only its row is
#: compared — the button, span[data-state], the turn-action-controls row and the
#: two divs around it — and that it sits in the user's unit, in the turn.
_USER_ROW_LEVELS = 4


def test_live_every_copy_button_sits_where_the_capture_puts_it(chrome, page):
    """The six Copy buttons of the captured page, in page order — the user's
    "Copy message", four tables' "Copy table", the reply's "Copy" — each with
    its row's labels, whether it is inside the turn, the reply's unit, the
    reply's text or a code block, and every element above it up to the turn."""
    _open_long(chrome, page, reply_actions=True)
    got = chrome.run(page.evaluate(_BUTTONS_JS))
    cap = CAPTURE["copyButtons"]
    assert [g["label"] for g in got] == [c["button"]["attrs"]["aria-label"] for c in cap] == [
        "Copy message", "Copy table", "Copy table", "Copy table", "Copy table", "Copy"]
    for i, (g, c) in enumerate(zip(got, cap)):
        where = f"{g['label']} #{i}"
        _same_attrs(c["button"]["attrs"], g["attrs"], where)
        assert g["siblingLabels"] == c["siblingLabels"], where
        for k in ("inTurnKey", "inAssistantUnit", "inReplyText", "inCodeBlock"):
            assert g[k] is c[k], (where, k)
        chain = _fold_turn_wrapper(c["ancestors"])
        turn = next(j for j, a in enumerate(chain) if "data-turn-key" in a["attrs"])
        if g["label"] == "Copy message":
            assert "data-turn-key" in g["ancestors"][-1]["attrs"], where
            assert any(a["attrs"].get("data-chatgpt-search-unit-key", "").endswith(":user")
                       for a in g["ancestors"]), where
            chain = chain[:_USER_ROW_LEVELS]
        else:
            assert len(g["ancestors"]) == turn + 1, (where, [a["tag"] for a in g["ancestors"]])
        for j, ca in enumerate(chain[:turn + 1]):
            assert g["ancestors"][j]["tag"] == ca["tag"], (where, j)
            _same_attrs(ca["attrs"], g["ancestors"][j]["attrs"], f"{where} ancestor {j}")


# ═══ 1. The default page read ═══════════════════════════════════════════════

#: What the page shows, read off the page itself: every heading, table, chip,
#: piece of inline code, bold run and quote of the reply, and its whole text.
_SHOWN_JS = """() => {
    const root = document.querySelector('[data-selected-text-overlay-target]');
    const txt = (e) => e.innerText.trim();
    return {
        text: root.innerText,
        headings: [...root.querySelectorAll('h1, h2, h3')].map((h) => '#'.repeat(+h.tagName[1]) + ' ' + txt(h)),
        tables: [...root.querySelectorAll('table')].map((t) =>
            [...t.querySelectorAll('tr')].map((tr) => [...tr.children].map(txt))),
        chips: [...root.querySelectorAll('a[data-testid="chatgpt-citation"]')].map((a) =>
            [txt(a), a.getAttribute('href'), a.querySelector('img').getAttribute('src')]),
        code: [...root.querySelectorAll('[data-markdown-copy="inline-code"]')].map((c) => c.textContent),
        strong: [...root.querySelectorAll('strong')].map(txt),
        quotes: [...root.querySelectorAll('blockquote')].map(txt),
    };
}"""


def _md_words(md):
    """The markdown's words as a person reads them: a link as its text, with
    no heading, quote, bold, code or table marks — and the spacing kept, so two
    words run together (`pass.**Paintings`) are one word here."""
    t = re.sub(r"\[([^\]]*)\]\([^)\s]*\)", r"\1", md)
    t = re.sub(r"^(?:#{1,6}|>) ", "", t, flags=re.M)
    t = re.sub(r"^\|(?: --- \|)+$", "", t, flags=re.M)
    return t.replace("**", "").replace("`", "").replace("|", " ").split()


def _assert_clean_brief(md, shown):
    """The brief is the page's reply as clean markdown: its headings as
    #/##/###, its tables as markdown tables, each source chip a plain link to
    its source (no image, no icon address), its inline code as code (nothing
    escaped), its bold runs and quote as markdown, no button's words — and
    every word the page shows, in order, spaced as the page spaces them, and
    nothing else."""
    assert [ln for ln in md.splitlines() if ln.startswith("#")] == shown["headings"]
    assert len(shown["tables"]) == 4
    for rows in shown["tables"]:
        lines = ["| " + " | ".join(r) + " |" for r in rows]
        lines.insert(1, "| " + " | ".join("---" for _ in rows[0]) + " |")
        assert "\n".join(lines) in md, lines[0]
    assert len(shown["chips"]) >= 6
    for name, href, icon in shown["chips"]:
        assert f" [{name}]({href})" in md, name
        assert icon not in md
    assert "![" not in md and "icons." not in md
    assert len(shown["code"]) >= 6 and any("_" in c for c in shown["code"])
    for c in shown["code"]:
        assert f"`{c}`" in md, c
    assert "\\" not in md
    for s in shown["strong"]:
        assert f"**{s}**" in md, s
    for q in shown["quotes"]:
        assert f"\n> {q}\n" in md, q
    for junk in ("Copy table", "Expand table", "Copy message", "Read aloud"):
        assert junk not in md
    # Every word, in order, and nothing else: the links' destinations aside.
    assert _md_words(md) == shown["text"].split()


def test_live_the_page_read_of_a_long_brief_is_clean_markdown(chrome, page, fast, logs):
    """extract_chatgpt_response — Phase 1's page read, its HTML→markdown path —
    on the long brief."""
    _open_long(chrome, page)
    shown = chrome.run(page.evaluate(_SHOWN_JS))
    md = chrome.run(research.extract_chatgpt_response(page))
    assert len(md) > 35000, logs
    _assert_clean_brief(md, shown)
    assert research._chatgpt_copy_verdict(md, "m", (base.PROMPT,)) == ""


def test_live_phase1_takes_the_long_brief_from_the_page(chrome, page, p1, logs):
    """run_phase1, the step a person hits: the page read gives the brief — the
    same clean markdown — and the Copy button beside it is never pressed."""
    cf._open(chrome, page, "new", reply_actions=True, streaming=True, long_brief=True)
    out = p1.run()
    shown = chrome.run(page.evaluate(_SHOWN_JS))
    _assert_clean_brief(out["text"], shown)
    assert cf._lines(logs, "Phase 1: brief read from the page ("), logs
    assert cf._clicked(chrome, page) == []


# ═══ 2. The Copy fallback on the same page ══════════════════════════════════

def test_live_phase1_takes_the_long_brief_from_the_copy_button(chrome, page, p1, logs):
    """The owner's run on this page: no marker names the reply's text, so the
    page read comes back empty. The reply's Copy — never a table's Copy table or
    Expand table, never the user's Copy message — gives the brief, which passes
    the fallback's own checks: long enough, not our prompt, reads like a brief,
    and on this page."""
    cf._open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True,
             long_brief=True)
    out = p1.run()
    assert cf._lines(logs, "HTML→MD miss: tried=21 sels, matched=0"), logs
    assert cf._clicked(chrome, page) == ["Copy"]
    assert cf._lines(logs, "Phase 1: brief taken from ChatGPT's Copy button ("), logs
    text = out["text"]
    assert text == cf._clip(chrome, page).strip() and len(text) > 35000
    assert research._chatgpt_copy_verdict(text, "m", (base.PROMPT,)) == ""
    assert chrome.run(research._chatgpt_copy_on_page(page, text))
    shown = chrome.run(page.evaluate(_SHOWN_JS))
    assert [ln for ln in text.splitlines() if ln.startswith("#")] == shown["headings"]


# ── the CUA, when no Copy button can be found: a table's own buttons ─────────

#: A table's own buttons at work: the first button of a table's row (its "Copy
#: table") copies that one table — written here as a markdown table, the way
#: the reply's Copy writes tables (what ChatGPT's own Copy table writes is not
#: captured). Keyed on the row, not the label, so a relabelled one still copies.
TABLE_COPY_JS = """() => {
    for (const row of document.querySelectorAll('[data-block-actions]')) {
        row.querySelector('button').addEventListener('click', () => {
            const t = row.closest('[data-markdown-table]').querySelector('table');
            const rows = [...t.querySelectorAll('tr')].map((tr) =>
                [...tr.children].map((c) => c.innerText.trim()));
            const md = [rows[0], rows[0].map(() => '---'), ...rows.slice(1)]
                .map((r) => '| ' + r.join(' | ') + ' |').join('\\n');
            setTimeout(() => navigator.clipboard.writeText(md), 150);
        });
    }
}"""
#: One button pinned where a scripted click reaches it, and named for the test
#: (its icons clipped to it: an empty <svg> is drawn 300 pixels wide).
PIN_JS = """([s, i, name, left]) => {
    const b = document.querySelectorAll(s)[i];
    b.dataset.srPin = name;
    b.style.cssText = `position: fixed; left: ${left}px; top: 300px; width: 40px; `
        + 'height: 30px; z-index: 9; display: block; overflow: hidden;';
}"""


def _cua_long_page(chrome, page, p1, *, table_label=None):
    """The owner's run on the long brief after a future rename: no marker names
    the reply's text or its own Copy (relabelled "Copy response"), so the CUA
    is asked to press it. Every table's Copy table copies its table. Pinned
    where a click reaches them, clear of one another: the reply's row, the
    fourth table's Copy table (the captured 2155-character table), the second
    table's Expand table and the user's Copy message. `table_label`: that Copy
    table relabelled too."""
    cf._open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True,
             long_brief=True)

    async def _hook():
        await page.add_style_tag(content=cf.PIN_ROW_CSS)
        await page.evaluate("() => document.querySelector('[data-sr-act=\"copy\"]')"
                            ".setAttribute('aria-label', 'Copy response')")
        await page.evaluate(TABLE_COPY_JS)
        for name, s, i, left in (("table", 'button[aria-label="Copy table"]', 3, 600),
                                 ("expand", 'button[aria-label="Expand table"]', 1, 700),
                                 ("message", 'button[aria-label="Copy message"]', 0, 800)):
            await page.evaluate(PIN_JS, [s, i, name, left])
        if table_label:
            await page.evaluate("(l) => document.querySelector('[data-sr-pin=\"table\"]')"
                                ".setAttribute('aria-label', l)", table_label)
        p1.at = {n: await page.evaluate(cf.CENTER_JS, f'[data-sr-pin="{n}"]')
                 for n in ("table", "expand", "message")}
        p1.at["copy"] = await page.evaluate(cf.CENTER_JS, '[data-sr-act="copy"]')

    p1.hooks = [_hook]


#: What the copy mission's refusal says (agent_loop's line).
REFUSED = ("[cua] REFUSED a click on Send, Regenerate, Share, Edit, Copy message or a "
           "table's own button — this task only clicks the Copy button under ChatGPT's "
           "latest reply")


def test_live_p1_the_cua_pressing_a_tables_copy_never_makes_the_table_the_brief(
        chrome, page, p1, logs):
    """⛔ The fallback's own case on the captured brief: the CUA presses the
    Copy of a table INSIDE the reply — the first icon of that table's row, as
    the reply's Copy is the first of the reply's. That one table (over 2000
    characters, its rows as wordy as prose, and on this page) would have been
    Phase 1's whole brief, and the research would start from one table. The
    click is refused, on the read and on both re-reads; with no other click,
    Phase 1 has no brief."""
    _cua_long_page(chrome, page, p1)
    cua = cf._CopyCua(lambda: [cf._click(p1, "table")])
    out = p1.run(cua)
    assert out["text"] == "", logs
    assert chrome.run(page.evaluate(      # the click aimed at that button itself
        "([x, y]) => document.elementFromPoint(x, y).closest('button').getAttribute('aria-label')",
        p1.at["table"])) == "Copy table"
    assert cf._clicked(chrome, page) == []
    assert cua.missions == ["copy", "copy", "copy"]
    assert len(cf._lines(logs, REFUSED)) == 3, logs
    assert not cf._lines(logs, "brief taken from"), logs


def test_live_p1_the_cua_is_held_off_every_other_copy_on_the_page(chrome, page, p1, logs):
    """The CUA tries a table's Copy table and Expand table and the user's Copy
    message before the reply's own Copy: each of the three is refused, with the
    copy mission's words, and the reply's Copy gives the whole brief."""
    _cua_long_page(chrome, page, p1)
    cua = cf._CopyCua(lambda: [cf._click(p1, "table"), cf._click(p1, "expand"),
                               cf._click(p1, "message"), cf._click(p1, "copy")])
    out = p1.run(cua)
    for label, at in (("Copy table", "table"), ("Expand table", "expand"),
                      ("Copy message", "message"), ("Copy response", "copy")):
        assert chrome.run(page.evaluate(
            "([x, y]) => document.elementFromPoint(x, y).closest('button').getAttribute('aria-label')",
            p1.at[at])) == label
    assert cf._clicked(chrome, page) == ["Copy response"]
    assert cua.missions == ["copy"]
    assert len(cf._lines(logs, REFUSED)) == 3, logs
    text = out["text"]
    assert text == cf._clip(chrome, page).strip() and len(text) > 35000, logs
    assert cf._lines(logs, "brief taken from ChatGPT's Copy button, clicked by the CUA ("), logs


def test_live_p1_a_table_copied_under_another_label_is_still_not_the_brief(
        chrome, page, p1, logs):
    """⛔ A later rename could change the table's label too — here to plain
    "Copy", which no never-click rule can refuse without refusing the reply's
    own. The CUA presses it and it copies the table: the copy is refused as not
    reading like a brief, since a table's rows are not counted as prose."""
    _cua_long_page(chrome, page, p1, table_label="Copy")
    cua = cf._CopyCua(lambda: [cf._click(p1, "table")])
    out = p1.run(cua)
    assert cf._clicked(chrome, page) == ["Copy", "Copy", "Copy"]     # it WAS pressed
    assert cf._clip(chrome, page).startswith("| ")                  # and copied its table
    assert out["text"] == "", logs
    assert len(cf._lines(logs, "was not used — it does not read like a brief")) == 3, logs


# ═══ 3. HTML→markdown on the captured shapes, with no browser ═══════════════

CHIP = ('<p>The hospice kept dogs. <span data-state="closed" class="contents"><span '
        'data-search-result-target=""><a data-testid="chatgpt-citation" aria-label="Pass Archive: '
        'records" href="https://pass-archive.example/a?utm_source=chatgpt.com" target="_blank">'
        '<span><span><span class="Favicon-xZwQNw"><img alt="" src="https://cdn.example.net/i/pa.png">'
        '</span><span>Pass Archive</span></span></span></a></span></span></p>')


def test_a_source_chip_is_a_plain_link_and_its_icon_is_dropped():
    md = research.html_to_markdown(CHIP)
    assert md == ("The hospice kept dogs. "
                  "[Pass Archive](https://pass-archive.example/a?utm_source=chatgpt.com)")


def test_an_image_inside_any_other_link_is_still_kept():
    """Only a ChatGPT source chip's icon is dropped: a chart inside an ordinary
    link stays an image (the document funnel stores it)."""
    md = research.html_to_markdown('<p>See <a href="https://example.org/report">'
                                   '<img alt="Chart" src="https://cdn.example.net/chart.png"></a></p>')
    assert md == "See [![Chart](<https://cdn.example.net/chart.png>)](https://example.org/report)"


def test_inline_code_written_as_a_span_is_code():
    md = research.html_to_markdown(
        '<p><strong><span>Search string:</span></strong><br><span data-markdown-copy="inline-code" '
        'class="InlineCode-Cddi3Y" dir="ltr">hip_score *giant* site:ofa.example</span></p>'
        '<p><span>a plain span_with an underscore</span></p>')
    assert md == ("**Search string:**\n`hip_score *giant* site:ofa.example`\n\n"
                  "a plain span\\_with an underscore")


def test_inline_code_with_a_backtick_or_spaces_at_its_edges():
    """A backtick inside the code gets a longer fence, spaced; spaces at its
    edges go outside the fence — and the spans around it keep their spacing."""
    md = research.html_to_markdown(
        '<p><span>Run the </span><span data-markdown-copy="inline-code">grep `ls`</span>'
        '<span> check, then</span><span data-markdown-copy="inline-code"> edge </span>'
        '<span>now.</span></p>')
    assert md == "Run the `` grep `ls` `` check, then `edge` now."
