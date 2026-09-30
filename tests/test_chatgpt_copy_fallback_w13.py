"""Phase 1 takes the brief from ChatGPT's Copy button when the page read comes
back empty (wave 13) — measured in real headless Chrome on the rebuilt pages
(tests/fixtures/chatgpt_0928; test_chatgpt_new_page_0928.py pins them to the
owner's captures).

⛔ THE CASE. The owner's run logged "[ChatGPT] HTML→MD miss: tried=21 sels,
matched=0", then "All extraction methods failed" — and Phase 1 had no brief
while the finished brief sat on the screen, under a Copy button that hands out
its markdown. The page read stays the default. Only when it comes back empty
does Phase 1 put a marker on the clipboard, press the Copy button under the
latest reply (or, when no Copy button can be found, have a CUA press it — a CUA
that may only click, and never on Send, Regenerate, Share, Edit message, Copy
message or a table's own Copy table / Expand table), and
read the clipboard, keeping the text only if it is not the marker, is as long as
the page read requires (more than 2000 characters of prose), is not our own
prompt, reads like a brief, and is text this page shows (fleet workers on one
computer share ONE clipboard — two tabs of one headless context share one too,
which is how another worker is played here).

WHERE the Copy button sits is the owner's capture of a finished Pro brief
(chatgpt-copy-button-capture.json, 2026-09-29): the turn's own row of icons,
div.turn-action-controls > div > span[data-state] > button[aria-label="Copy"],
inside the turn and outside the reply's unit and text. The same page's other
Copy buttons carry other labels: "Copy message" under the user's own message,
"Copy table" (beside "Expand table") on every table inside the reply. The new
page's fixture puts the reply's row there (hook body[data-reply-actions]);
test_chatgpt_long_brief_w13.py pins it to the capture button by button. The old
page's row (the testid) is still reconstructed, inside the reply's article.

The page is served at a local address the browser never leaves — page.route
answers it from the fixture file and refuses every other request. The clipboard
API needs a secure page; set_content's about:blank is not one here.

Section 1 runs run_phase1 itself (the step a person hits): page read, Copy
button, CUA, the re-read. Section 2 is the button lookup, section 3 the
clipboard marker and the verdict.
"""
import asyncio
import html as _html
from types import SimpleNamespace

import pytest

import research
import test_chatgpt_new_page_0928 as base
import test_chatgpt_p1_repair_0928 as p1r

PROMPT = base.PROMPT
HEADING = base.HEADING
LINK = base.LINK
TOPIC = "the St Bernard"
URL = "http://127.0.0.1:9/c/sr-fixture"     # answered by page.route — never fetched
ORIGIN = "http://127.0.0.1:9"
#: Another brief — a real one's shape and length (past the page read's floor of
#: 2000 characters), on another topic.
OLD_BRIEF = "\n\n".join([
    "## Research brief: the Newfoundland",
    "Scope: the breed's origins on the island, its water rescue work, and the "
    "health problems that come with its size and its dense double coat.",
    "Questions to answer: when the breed was first described, how its rescue "
    "reputation formed, and which of the famous rescues are actually documented.",
    "Method: prefer primary sources and veterinary studies over breeder material, "
    "and give both sides where the sources disagree about a date or a number.",
    "History: trace the dogs from the fishing villages of the island to the first "
    "kennel club registrations in England, and say which of the early accounts were "
    "written by people who actually saw the dogs working in the water.",
    "Working roles: cover the dogs that hauled nets and carts for fishermen, the "
    "lifesaving dogs kept on ships and at harbours, and the water rescue trials that "
    "breed clubs still run today, with the rules those trials follow.",
    "Health and welfare: list the conditions that are most common in the breed, "
    "such as heart disease, hip and elbow problems and cystinuria, with how often "
    "each is found and which screening tests breeders are asked to use.",
    "Breed standard: explain what the modern standard requires for size, coat and "
    "colour, how it differs between the main kennel clubs, and why the black and "
    "white variety is shown as a separate breed in some countries.",
    "Famous dogs: check the stories told about named Newfoundlands, from the dogs "
    "said to have saved shipwrecked sailors to the dog that went west with the "
    "explorers, and say which of those stories rest on letters or logbooks.",
    "Sources to start from: the breed club archives, the kennel club stud books, "
    "the veterinary literature on giant breeds, and the island's own museums and "
    "newspapers from the years when the dogs were still working with fishermen.",
    "Open questions: list what the evidence could not settle, such as the breed's "
    "exact ancestry, and say what kind of source would be needed to settle each one.",
    "Out of scope: training advice, product recommendations and other giant breeds, "
    "except where a comparison explains a Newfoundland trait that readers ask about.",
    "Deliverable: a structured report with sections, sources and open questions "
    "for the research agent to pursue, every claim traceable to its source.",
])
#: A long user feedback, so our own prompt is long enough to be a brief and
#: reads like prose — then only the "is it our prompt" check can refuse a copy
#: of it.
FEEDBACK = ("Cover the hospice kennels in the twentieth century in much more detail "
            "than usual, including who ran them, how the dogs were chosen and trained, "
            "how many dogs the hospice kept in each decade, where the puppies went when "
            "the kennel had too many of them, and how the monks decided which dogs to "
            "breed from when the old working lines began to thin out after the wars. "
            "Quote the kennel books wherever the hospice has published them.\n"
            "Explain how the road tunnel changed the work of the dogs at the pass, what "
            "the monks did with the dogs once travellers stopped coming on foot, why the "
            "kennel was eventually handed to a foundation in the valley, what that "
            "foundation does with the dogs today in summer and in winter, and how the "
            "visitors who come to see the dogs pay for their keep and their vet bills. "
            "Say which parts of this are documented and which are only told to tourists.\n"
            "Say which modern breeders still work with the hospice line, how their dogs "
            "differ from the show dogs registered elsewhere today in size, coat, head "
            "shape and health, which of those differences the breed clubs accept, which "
            "ones they argue about, and whether any study has compared the two groups "
            "for hip scores, heart disease or life expectancy. Give the numbers with "
            "their sources, and say plainly where no numbers could be found at all.\n"
            "Add a section on the paintings, stamps and postcards that made the dogs "
            "famous, with the barrel on the collar that the monks say their dogs never "
            "wore, and explain when that picture first appeared, who painted it, and "
            "how it spread through books for children and advertising in the century "
            "that followed. Keep this section short and clearly apart from the history.\n"
            "Finally, write the report for a reader who knows dogs well but has never "
            "read about this breed, avoid the breeders' own marketing words, and put "
            "every figure in a table with its source, its year and a short note on how "
            "reliable that source is, so the reader can check each one for themselves.")
EXTRA = ("Add the hospice's own records of every rescue they wrote down, with the "
         "year, the place on the pass and the name of the dog wherever the records "
         "give one, and say how many of those rescues were of travellers who were "
         "still alive when the dogs found them. Keep the records in the order the "
         "hospice wrote them, and mark any entry that was added or corrected later. "
         "Where two records describe the same rescue, say so and keep both.\n"
         "Say which of those rescues were reported in newspapers at the time, which "
         "ones only appear in books written a century or more later, and which ones "
         "first appear in the guidebooks sold to visitors. For each rescue that the "
         "newspapers reported, give the paper, the date and what it said, and note "
         "where the story grew in the retelling from one book to the next one. "
         "Treat every number that only appears in a guidebook as unconfirmed.\n"
         "Compare the number of rescues in the records with the famous figure of "
         "forty that is usually quoted for Barry, explain where that figure came "
         "from, who first wrote it down, how the story of his death was invented and "
         "later corrected, and what the museum in Bern says about his body and the "
         "way it was remodelled. Finish with a short list of what can be said about "
         "Barry with confidence, and what should be left out of the report entirely.\n"
         "Add the other dogs whose names the hospice remembers, the years they worked "
         "and what the records say they did, and say whether any of them were bred "
         "from Barry's line or brought in from farms in the valley below the pass. "
         "Where a name appears only in a book for children, leave that dog out.\n"
         "Say how the rescues were actually carried out: whether the dogs went out "
         "alone or with the monks, how they found people under the snow, what the "
         "monks carried with them, and how the work changed once telephones, better "
         "maps and the road made the crossing safer for the people who made it. "
         "Where the monks' own accounts and the visitors' accounts disagree about how "
         "the work was done, give both of them and say which one is better supported.")

logs = base.logs
fast = base.fast


@pytest.fixture(scope="module")
def chrome():
    """Headless Chrome with the clipboard granted to the fixture's address — as
    the backend's own Chrome has it granted browser-wide (Browser.start)."""
    try:
        from patchright.async_api import async_playwright
    except Exception as e:                                    # pragma: no cover
        pytest.skip(f"patchright unavailable: {e}")
    loop = asyncio.new_event_loop()

    async def _start():
        pw = await async_playwright().start()
        try:
            b = await pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            await pw.stop()
            raise
        ctx = await b.new_context(viewport={"width": 1280, "height": 900})
        await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=ORIGIN)
        return pw, b, ctx

    try:
        pw, b, ctx = loop.run_until_complete(_start())
    except Exception as e:                                    # pragma: no cover
        loop.close()
        pytest.skip(f"system Chrome unavailable: {e}")
    yield SimpleNamespace(run=loop.run_until_complete, ctx=ctx)
    loop.run_until_complete(b.close())
    loop.run_until_complete(pw.stop())
    loop.close()


@pytest.fixture
def page(chrome):
    p = chrome.run(chrome.ctx.new_page())
    yield p
    chrome.run(p.close())


#: A long Pro brief rebuilt from the owner's capture (the reply root's children).
LONG_BRIEF = base.FIX / "long_brief_reply.html"


def _long_reply():
    """The long brief's children, the file's header comment left out."""
    return LONG_BRIEF.read_text(encoding="utf-8").split("-->", 1)[1].strip()


def _html_for(layout, *, thread=False, prompt=PROMPT, long_brief=False, **hooks):
    """The rebuilt page, with test hooks on <body>: reply_actions=True →
    data-reply-actions="1"; copy_gives="nothing" → data-copy-gives="nothing".
    long_brief=True: every reply is the long brief (new page only)."""
    src = (base.FIX / f"{layout}_page.html").read_text(encoding="utf-8")
    body = '<body data-sr-fixture="chat" data-sr-prompt="">'
    assert src.count(body) == 1, "the fixture's <body> contract changed"
    if long_brief:
        tag = '<template id="sr-reply">'
        assert src.count(tag) == 1, "the fixture's reply template contract changed"
        head, rest = src.split(tag, 1)
        src = head + tag + _long_reply() + "</template>" + rest.split("</template>", 1)[1]
    extra = "".join(f' data-{k.replace("_", "-")}="{"1" if v is True else _html.escape(str(v))}"'
                    for k, v in sorted(hooks.items()) if v)
    return src.replace(body, (f'<body data-sr-fixture="{"thread" if thread else "chat"}" '
                              f'data-sr-prompt="{_html.escape(prompt, quote=True)}"{extra}>'))


#: Every clipboard write the PAGE's own code makes — its Copy buttons — kept on
#: <html data-sr-copied>. The program's own writes (the marker, and putting back
#: what the clipboard held) run in its own script world and are not seen here;
#: since the fallback gives the clipboard back after every read, this is how a
#: test sees what a Copy handed out.
RECORD_COPIES_JS = """(() => {
    const c = navigator.clipboard, write = c.writeText.bind(c);
    c.writeText = (t) => { document.documentElement.dataset.srCopied = t; return write(t); };
})();"""


def _open(chrome, page, layout="new", **kw):
    """Serve the fixture at URL from memory; every other request is refused."""
    body = _html_for(layout, **kw)

    async def _serve(route):
        if route.request.url == URL:
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)
        else:
            await route.abort()

    async def _go():
        await page.unroute("**/*")
        await page.route("**/*", _serve)
        await page.goto(URL)
        await page.add_script_tag(content=RECORD_COPIES_JS)

    chrome.run(_go())


def _copied(chrome, page):
    """What the page's own Copy last handed out (RECORD_COPIES_JS), or None."""
    return chrome.run(page.evaluate("() => document.documentElement.dataset.srCopied ?? null"))


def _clip(chrome, page):
    return chrome.run(page.evaluate("() => navigator.clipboard.readText()"))


def _set_clip(chrome, page, text):
    chrome.run(page.evaluate("(t) => navigator.clipboard.writeText(t)", text))


def _clicked(chrome, page):
    got = chrome.run(page.evaluate("() => document.body.dataset.clicked || ''"))
    return [x for x in got.split("|") if x]


def _users(chrome, page):
    return [research._norm_prompt_text(u) for u in chrome.run(page.evaluate(base.USERS_JS))]


def _lines(logs, needle):
    return [m for _lv, m in logs if needle in m]


def _fixture_markdown(heading=HEADING):
    """The markdown the fixture's Copy hands out, built the fixture's way."""
    tpl = (base.FIX / "new_page.html").read_text(encoding="utf-8")
    body = tpl.split('<template id="sr-reply">', 1)[1].split("</template>", 1)[0]
    import re
    paras = re.findall(r"<p[^>]*>(?:<span>)?(.*?)(?:</span>)?</p>", body)
    paras = [re.sub(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', r"[\2](\1)", p) for p in paras]
    return "\n\n".join([f"## {heading}", *[_html.unescape(p) for p in paras]])


# ═══ 1. Phase 1 itself ═══════════════════════════════════════════════════════
#
# run_phase1 runs against the page: the real submit and verify gate, the real
# page read, the real Copy fallback, the real agent_loop / execute_action for
# the CUA. Stubbed: the steps before the submit (sign-in probe, observer, human
# check, tier, Deep Research clear) and the stream poll, which waits for the
# page to draw the reply and then runs the test's hook.

class _CopyCua:
    """The Anthropic client agent_loop calls. The copy mission's FIRST turn is
    its script (computer actions, in order); every later turn says done."""

    def __init__(self, script):
        self.script = script
        self.missions = []
        self.told = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, *, system, messages, **_kw):
        if len(messages) > 1:
            for res in messages[-1]["content"]:
                self.told += [c["text"] for c in res["content"] if c.get("type") == "text"]
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="copied")])
        is_copy = system == research.PROMPT_COPY_REPLY_CHATGPT
        self.missions.append("copy" if is_copy else "other")
        acts = self.script() if is_copy else []
        if not acts:
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="nothing to do")])
        return SimpleNamespace(content=[
            SimpleNamespace(type="tool_use", id=f"tu_{len(self.missions)}_{i}",
                            input={"action": a, **params})
            for i, (a, params) in enumerate(acts)])


@pytest.fixture
def p1(chrome, page, fast, logs, monkeypatch):
    """run_phase1, ready to run on `page`. `p1.run(cua)` returns what it returns."""
    st = SimpleNamespace(polls=[], hooks=[], extra="")

    async def _yes(*_a, **_k):
        return True

    async def _nothing(*_a, **_k):
        return None

    async def _tier(*_a, **_k):
        return "already"

    async def _poll(_page, _verify, label, *_a, **_k):
        st.polls.append(label)
        await page.wait_for_function(
            "(n) => parseInt(document.body.dataset.replies || '0', 10) >= n",
            arg=len(st.polls), timeout=10000)
        if st.hooks:
            await st.hooks.pop(0)()
        return True

    real_wait_sent = research._chatgpt_wait_prompt_sent

    def _wait_sent(p, prompt, timeout_s=10.0):
        return real_wait_sent(p, prompt, timeout_s=min(timeout_s, 1.0))

    for name, fn in (("_work_tab_signed_out", _nothing), ("inject_agent_observer", _yes),
                     ("check_hv_gate", _yes), ("_chatgpt_select_effort_tier", _tier),
                     ("_chatgpt_clear_deep_research", _nothing), ("poll_until_done", _poll),
                     ("_chatgpt_wait_prompt_sent", _wait_sent)):
        monkeypatch.setattr(research, name, fn)
    # The clipboard is read for up to this long after a click that copied nothing.
    # raising=False: against the pre-fix module a test fails on BEHAVIOUR (no
    # brief), not on a missing name.
    monkeypatch.setattr(research, "_CG_COPY_READ_S", 1.0, raising=False)
    rt, ctl = research._runtime, research._controls
    monkeypatch.setattr(rt, "register_page", lambda *a, **k: None)
    monkeypatch.setattr(rt, "unregister_page", lambda *a, **k: None)
    monkeypatch.setattr(rt, "phase", rt.phase)
    monkeypatch.setattr(rt, "sub_state", rt.sub_state)
    monkeypatch.setattr(ctl, "is_stop", lambda: False)
    monkeypatch.setattr(ctl, "is_pause", lambda: False)
    monkeypatch.setattr(ctl, "peek_extra_context", lambda: st.extra)
    monkeypatch.setattr(ctl, "pop_extra_context", lambda: st.extra)
    if research._vision is not None:
        monkeypatch.setattr(research._vision, "is_vision_enabled", lambda: "off")

    browser = research.Browser.__new__(research.Browser)
    browser.page = page

    async def _navigate(url):
        st.navigated = url                # ⛔ never leaves the fixture page

    browser.navigate = _navigate

    def run(cua=None, feedback=""):
        return chrome.run(research.run_phase1(browser, cua, TOPIC, [], feedback=feedback))

    st.run = run
    return st


@pytest.mark.parametrize("layout", base.LAYOUTS)
def test_live_p1_a_page_read_that_works_never_touches_the_copy_button(chrome, page, p1, logs, layout):
    """The default: the page read. The Copy button is there and never pressed,
    and the owner's clipboard is never written."""
    _open(chrome, page, layout, reply_actions=True, streaming=True)
    _set_clip(chrome, page, "the owner's own clipboard")
    out = p1.run()
    assert HEADING in out["text"] and LINK in out["text"], logs
    assert "Copy" not in _clicked(chrome, page)
    assert _clip(chrome, page) == "the owner's own clipboard"
    assert _lines(logs, "Phase 1: brief read from the page ("), logs
    assert not _lines(logs, "Copy button"), logs


def test_live_p1_an_empty_page_read_takes_the_brief_from_the_copy_button(chrome, page, p1, logs):
    """The owner's run: no marker names the reply's text ("HTML→MD miss:
    tried=21 sels, matched=0"). The Copy button gives the brief — its markdown,
    headings and links as ChatGPT wrote them."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True)
    out = p1.run()
    assert _lines(logs, "HTML→MD miss: tried=21 sels, matched=0"), logs
    assert out["text"] == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]
    assert _lines(logs, "the page read came back empty — taking the brief from "
                        "ChatGPT's Copy button"), logs
    assert _lines(logs, "Phase 1: brief taken from ChatGPT's Copy button ("), logs
    # At once — not after the three-minute re-read.
    assert not _lines(logs, "brief generated but extraction empty"), logs


def test_live_p1_the_old_pages_copy_button_gives_the_brief(chrome, page, p1, logs, monkeypatch):
    """The old page's Copy (data-testid="copy-turn-action-button"), with the page
    read coming back empty (its <article> would otherwise always read)."""
    async def _empty(_page):
        return ""

    monkeypatch.setattr(research, "extract_chatgpt_response", _empty)
    _open(chrome, page, "old", reply_actions=True, streaming=True)
    out = p1.run()
    assert out["text"] == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]


def test_live_p1_citation_tokens_in_the_copy_are_dropped(chrome, page, p1, logs):
    """ChatGPT's source-citation token runs never reach the brief — the same
    rule as the page read."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True,
          copy_gives="cited")
    out = p1.run()
    assert out["text"] == _fixture_markdown(), logs
    assert "turn0search1" not in out["text"]


def _first_draft_hook(page):
    """The poll hook that marks the first reply as the first draft."""
    async def _mark_first_draft():
        await page.evaluate(
            "() => { document.querySelector('[data-selected-text-overlay-target] h2')"
            ".textContent = 'Research brief: the St Bernard (first draft)'; }")
    return _mark_first_draft


def test_live_p1_a_copy_that_copied_nothing_never_hands_back_the_old_clipboard(
        chrome, page, p1, logs):
    """⛔ The clipboard holds an EARLIER draft of this very brief — text this
    page shows, long enough, prose, not our prompt, so every other check would
    keep it — and the Copy click copies nothing. Without the marker that first
    draft would come back as the updated brief. Every re-read tries the Copy
    button again."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True,
          copy_gives="nothing")
    p1.extra = EXTRA
    p1.hooks = [_first_draft_hook(page)]
    first_draft = _fixture_markdown(f"{HEADING} (first draft)")
    _set_clip(chrome, page, first_draft)
    out = p1.run()
    assert research._chatgpt_copy_verdict(first_draft, "m") == ""       # it WOULD pass
    assert chrome.run(research._chatgpt_copy_on_page(page, first_draft))  # and it is here
    assert p1.polls == ["Phase1", "Phase1-followup"]
    assert out["text"] == "", logs
    assert _clicked(chrome, page) == ["Copy", "Copy", "Copy"]       # the read + 2 re-reads
    assert len(_lines(logs, "was not used — nothing was copied")) == 3, logs


def test_live_p1_a_copy_of_our_own_prompt_is_refused(chrome, page, p1, logs):
    """A Copy that hands out the user's message is not the brief — and the line
    says so. (The prompt carries a long feedback here, so it is long enough to
    pass as a brief; on this page the box flattens its lines, so the reason the
    log gives is what tells this check from the "reads like a brief" one.)"""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True,
          copy_gives="prompt")
    out = p1.run(feedback=FEEDBACK)
    copied = _copied(chrome, page)
    assert FEEDBACK.split("\n")[0] in copied and len(copied) > 2000
    assert out["text"] == "", logs
    assert _lines(logs, "was not used — it was our own prompt"), logs


def test_live_p1_after_a_follow_up_the_latest_reply_is_copied(chrome, page, p1, logs):
    """The user added context mid-brief: a follow-up, a second reply. The Copy
    under the LATEST reply gives the updated brief, never the first draft."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True)
    p1.extra = EXTRA
    p1.hooks = [_first_draft_hook(page)]
    out = p1.run()
    assert p1.polls == ["Phase1", "Phase1-followup"]
    assert len(_users(chrome, page)) == 2
    assert out["text"] == _fixture_markdown(), logs
    assert "(first draft)" not in out["text"]


def test_live_p1_a_copy_of_the_follow_up_is_refused(chrome, page, p1, logs):
    """The follow-up is our prompt too: a Copy that hands it out is refused like
    the first prompt, for that reason."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True,
          copy_gives="prompt")
    p1.extra = EXTRA
    out = p1.run()
    copied = _copied(chrome, page)
    assert EXTRA.split("\n")[0] in copied and len(copied) > 2000
    assert out["text"] == "", logs
    assert _lines(logs, "was not used — it was our own prompt"), logs


#: ChatGPT's answer to the brief prompt when it asks before it writes: four
#: paragraphs of prose, about 660 characters — not a brief.
QUESTION = [
    "Before I write the brief, could you tell me a little more about what you want "
    "the research to cover, so that the agent does not spend its time in the wrong place?",
    "Should the report focus on the history of the breed at the hospice, on the modern "
    "breed as a family dog, or on its health and the screening that breeders use today?",
    "Is there a particular country whose kennel club standard you care about most, and do "
    "you want the report written for a general reader or for someone who already breeds dogs?",
    "Once you answer these questions I will write the complete research brief for you, with "
    "sections, sources and open questions for the research agent to pursue.",
]


def test_live_p1_a_short_reply_is_never_taken_as_the_brief(chrome, page, p1, logs):
    """⛔ ChatGPT answers the brief prompt with a clarifying question. Every
    marker still matches; the page read refuses it (it keeps only more than 2000
    characters of prose), and so does the Copy button's copy — Phase 1 has no
    brief, as it had before the Copy fallback ("No brief was generated", with
    Retry and Skip), instead of sending three research agents off on a question."""
    _open(chrome, page, "new", reply_actions=True, streaming=True)

    async def _short_reply():
        await page.evaluate(
            "(ps) => { const r = document.querySelector('[data-selected-text-overlay-target]');"
            " r.innerHTML = ps.map((p) => '<p>' + p + '</p>').join(''); }", QUESTION)

    p1.hooks = [_short_reply]
    out = p1.run()
    assert out["text"] == "", logs
    assert _clicked(chrome, page) == ["Copy", "Copy", "Copy"]       # the read + 2 re-reads
    assert QUESTION[0] in _copied(chrome, page)                      # it WAS copied
    assert len(_lines(logs, "was not used — it was only")) == 3, logs


#: The paragraphs of the fixture's reply, in its Copy's markdown.
REPLY_PARAS = _fixture_markdown().split("\n\n")[1:]
#: Worker 2's brief: the SAME topic (another run of it), long enough, prose, not
#: our prompt — every check but "is it on this page" keeps it. Its second line
#: is the closing line ChatGPT writes into every brief of this kind, word for
#: word the one on worker 1's page; one shared line is not enough.
OTHER = "\n\n".join([
    "## Research brief: the St Bernard (another run of it)",
    "Scope: the St Bernard as a family dog today, its temperament with small "
    "children, its exercise needs and the cost of keeping a giant breed at home.",
    REPLY_PARAS[-1],
    "Questions to answer: how much space and exercise a St Bernard needs, which "
    "health checks a buyer should ask a breeder for, and what insurance costs.",
    "Method: prefer veterinary sources and breed club surveys over breeder "
    "advertising, and give both sides where owners and vets disagree on a point.",
    "Family life: how the dogs behave with small children and with other pets, "
    "what owners report about drooling, shedding and the space the dogs need, and "
    "how often St Bernards are given up to rescue centres and for what reasons.",
    "Costs: the price of a puppy from a breeder who screens for hip and heart "
    "problems, the yearly cost of food, grooming and insurance, and the cost of "
    "the operations the breed most often needs, with the sources for each figure.",
    "Exercise: how much walking a grown dog needs, why puppies of giant breeds "
    "should not be walked too far, and what vets say about heat and summer walks.",
    "Health: the conditions a family should know about before buying, such as hip "
    "and elbow problems, bloat and heart disease, what each one costs to treat, and "
    "which of them a responsible breeder screens the parents for before a litter.",
    "Choosing a breeder: which questions to ask, which papers and test results to "
    "see, how to recognise a puppy farm, and what the breed clubs in each country "
    "offer to families who want to buy from someone who breeds for health first.",
    "Old age: how long the dogs usually live, what changes in their last years, "
    "how families cope with a dog that can no longer climb stairs or get into a car, "
    "and what vets advise about keeping an old giant dog comfortable at home.",
    "Out of scope: the hospice's history and the rescue legends, which the other "
    "report covers, and training advice beyond what a new owner needs to know.",
    "Deliverable: a structured report for a family deciding whether to take on a "
    "St Bernard, with sections, sources and a list of questions to ask a breeder.",
])
#: What another worker does with the shared clipboard: its Phase 2 paste, or its
#: own Copy fallback, writes a whole brief there.
_WRITE_JS = "(t) => navigator.clipboard.writeText(t)"
_READ_JS = "async () => { try { return await navigator.clipboard.readText(); } catch (e) { return null; } }"
_CLICKS_JS = ("([l, n]) => (document.body.dataset.clicked || '').split('|')"
              ".filter((x) => x === l).length >= n")


def _worker2(chrome, page):
    """Worker 2's ChatGPT tab: another Chrome on the same computer, sharing the
    one clipboard. Worker 1's tab is put back in front, as each worker's Chrome
    shows its own ChatGPT tab."""
    other = chrome.run(chrome.ctx.new_page())
    _open(chrome, other, "new", thread=True)
    chrome.run(page.bring_to_front())
    return other


async def _worker2_writes(page, other, label, times, delay):
    """Worker 2 writes its brief `delay` seconds after each of worker 1's first
    `times` clicks on `label`."""
    for n in range(1, times + 1):
        await page.wait_for_function(_CLICKS_JS, arg=[label, n], polling=50, timeout=30000)
        await asyncio.sleep(delay)
        await other.evaluate(_WRITE_JS, OTHER)


def _finish(chrome, other, tasks):
    for t in tasks:
        t.cancel()
    chrome.run(asyncio.sleep(0.05))
    chrome.run(other.close())


def test_live_p1_another_workers_brief_is_never_taken_as_this_runs(
        chrome, page, p1, logs, monkeypatch):
    """⛔ The Copy button copies nothing, and within the read window worker 2
    writes its brief — same topic — to the clipboard. The marker only proves
    that SOMETHING changed the clipboard; the brief is not on this page, so it
    is not used, on the read or on either re-read."""
    monkeypatch.setattr(research, "_CG_COPY_READ_S", 5.0, raising=False)
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True,
          copy_gives="nothing")
    other = _worker2(chrome, page)
    tasks = []

    async def _start():
        tasks.append(asyncio.ensure_future(_worker2_writes(page, other, "Copy", 3, 0.3)))

    p1.hooks = [_start]
    try:
        out = p1.run()
        assert out["text"] == "", logs                              # never worker 2's brief
        assert chrome.run(asyncio.wait_for(tasks[0], 10)) is None   # all three writes landed
    finally:
        _finish(chrome, other, tasks)
    assert research._chatgpt_copy_verdict(OTHER, "m", (PROMPT,)) == ""   # it WOULD pass
    assert _clicked(chrome, page) == ["Copy", "Copy", "Copy"]
    assert len(_lines(logs, "was not used — it is not text of the latest reply on this ChatGPT page")) == 3, logs
    assert not _lines(logs, "brief taken from"), logs


def test_live_p1_the_cuas_copy_overwritten_by_another_worker_is_not_used(
        chrome, page, p1, logs, monkeypatch):
    """⛔ No Copy button by its marker: the CUA presses Copy, which DOES copy
    this brief, and while the CUA takes its next look worker 2's brief lands on
    the clipboard. That is refused; the re-read presses Copy again and gets this
    page's own brief."""
    _cua_page(chrome, page, p1)
    other = _worker2(chrome, page)
    tasks, wrote = [], asyncio.Event()

    class _Look(base._FastAsyncio):
        """research's sleeps, capped — except the CUA's "wait 7.125" (a
        figure nothing else waits), its next look, which lasts until worker 2
        has written."""
        @staticmethod
        async def sleep(delay=0, *a, **k):
            if delay == 7.125:
                await asyncio.wait_for(wrote.wait(), 10)
            else:
                await asyncio.sleep(min(float(delay or 0), 0.05))

    monkeypatch.setattr(research, "asyncio", _Look())

    async def _write_once():
        await _worker2_writes(page, other, "Copy response", 1, 0.4)
        wrote.set()

    hook = p1.hooks[0]

    async def _hook():
        await hook()
        tasks.append(asyncio.ensure_future(_write_once()))

    p1.hooks = [_hook]
    cua = _CopyCua(lambda: [_click(p1, "copy"), ("wait", {"duration": 7.125})])
    try:
        out = p1.run(cua)
    finally:
        _finish(chrome, other, tasks)
    assert wrote.is_set()
    assert out["text"] == _fixture_markdown(), logs
    assert cua.missions == ["copy", "copy"]
    assert len(_lines(logs, "was not used — it is not text of the latest reply on this ChatGPT page")) == 1, logs
    assert _lines(logs, "brief taken from ChatGPT's Copy button, clicked by the CUA ("), logs


#: ChatGPT's source chips inside the reply: on the page, and not in the Copy's
#: markdown (the copy carries a citation token there, which is dropped). One
#: early in the first paragraph, one late in the second (past the part of a
#: line that is looked for on the page).
SOURCE_CHIPS_JS = """() => {
    const spans = document.querySelectorAll('[data-selected-text-overlay-target] p > span');
    const chip = () => { const b = document.createElement('button');
        b.textContent = 'akc.org +2'; b.dataset.srName = 'source chip'; return b; };
    spans[0].insertBefore(chip(), spans[0].firstChild.splitText('Scope: '.length));
    const tail = spans[1].lastChild;
    spans[1].insertBefore(chip(), tail.splitText(' and the hospice archives,'.length));
}"""


def test_live_p1_source_chips_on_the_page_do_not_cost_the_brief(chrome, page, p1, logs):
    """A copy is kept when two of its first three lines of prose open with words
    the page shows. A source chip inside a sentence is on the page and not in
    the copy; a link shows only its words."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True)

    async def _chips():
        await page.evaluate(SOURCE_CHIPS_JS)

    p1.hooks = [_chips]
    out = p1.run()
    assert chrome.run(page.evaluate(
        "() => document.querySelectorAll('[data-sr-name=\"source chip\"]').length")) == 2
    assert out["text"] == _fixture_markdown(), logs
    assert "akc.org" not in out["text"]


def test_live_p1_a_brief_written_as_a_numbered_list_is_taken(chrome, page, p1, logs):
    """The brief is a numbered list. Its copy writes "1.", "2.", … in front of
    each line; the page draws those numbers, so they are not in its text."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True)

    async def _as_list():
        await page.evaluate("""() => {
            const root = document.querySelector('[data-selected-text-overlay-target]');
            const ol = document.createElement('ol');
            for (const p of [...root.querySelectorAll('p')]) {
                const li = document.createElement('li');
                li.innerHTML = p.innerHTML;
                ol.appendChild(li);
                p.remove();
            }
            root.appendChild(ol);
        }""")

    p1.hooks = [_as_list]
    out = p1.run()
    want = f"## {HEADING}\n\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(REPLY_PARAS, 1))
    assert out["text"] == want, logs


# ── the CUA, when no Copy button can be found ────────────────────────────────

#: The row of icons pinned in place, so a scripted CUA click lands on it however
#: the page scrolls (the page read scrolls to the bottom first).
PIN_ROW_CSS = ("[data-sr-reply-actions] { position: fixed; left: 200px; top: 120px; "
               "z-index: 5; background: #fff; }")
CENTER_JS = """(s) => { const r = document.querySelector(s).getBoundingClientRect();
    return [Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2)]; }"""


def _cua_page(chrome, page, p1, *, draft=False):
    """A future rename: neither the reply's text nor its Copy button carries a
    marker any more. The hook pins the row and the composer, optionally leaves
    a draft in the box (so Send shows), and notes where everything is."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True)

    async def _hook():
        await page.add_style_tag(content=PIN_ROW_CSS + "\n" + p1r.PIN_COMPOSER_CSS)
        await page.evaluate("() => document.querySelector('[data-sr-act=\"copy\"]')"
                            ".setAttribute('aria-label', 'Copy response')")
        if draft:
            await page.click('[contenteditable="true"]')
            await page.keyboard.type("draft")
        p1.at = {k: await page.evaluate(CENTER_JS, s) for k, s in (
            ("copy", '[data-sr-act="copy"]'), ("regen", '[aria-label="Regenerate response"]'),
            ("box", '[contenteditable="true"]'),
            ("send", 'button[aria-label="Send"]' if draft else '[contenteditable="true"]'))}

    p1.hooks = [_hook]


def _click(p1, what):
    return ("left_click", {"coordinate": list(p1.at[what])})


def test_live_p1_with_no_copy_button_found_the_cua_clicks_it(chrome, page, p1, logs):
    _cua_page(chrome, page, p1)
    cua = _CopyCua(lambda: [_click(p1, "copy")])
    out = p1.run(cua)
    assert cua.missions == ["copy"]
    assert out["text"] == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy response"]
    assert _lines(logs, "no Copy button found under ChatGPT's reply — asking the CUA"), logs
    assert _lines(logs, "brief taken from ChatGPT's Copy button, clicked by the CUA ("), logs


#: The buttons under the user's own message, "Edit message" and "Share prompt"
#: (both captured labels), pinned where a stray click can reach them — clear of
#: the pinned row of icons under the reply.
PIN_EDIT_SHARE_JS = """() => {
    const pin = (label, left, top) => {
        const b = document.querySelector(`[aria-label="${label}"]`);
        document.body.appendChild(b);
        b.style.cssText = `position: fixed; left: ${left}px; top: ${top}px; width: 40px; `
            + 'height: 30px; z-index: 9; display: block; visibility: visible; opacity: 1;';
    };
    pin('Edit message', 900, 500);
    pin('Share prompt', 1000, 300);
}"""


def test_live_p1_the_copy_cua_only_clicks_and_never_regenerate_or_send(chrome, page, p1, logs):
    """⛔ The CUA tries what must never happen: Regenerate (it would throw the
    brief away), a word typed into the box and Enter, Send on a leftover draft,
    Share next to Copy (a public link to the chat), the user's Edit message (its
    Send re-submits the prompt). None of it is carried out; its Copy click still
    gives the brief."""
    _cua_page(chrome, page, p1, draft=True)
    hook = p1.hooks[0]

    async def _hook():
        await hook()
        await page.evaluate(PIN_EDIT_SHARE_JS)
        p1.at.update({k: await page.evaluate(CENTER_JS, s) for k, s in (
            ("share", '[data-sr-reply-actions] [aria-label="Share"]'),
            ("share prompt", '[aria-label="Share prompt"]'),
            ("edit", '[aria-label="Edit message"]'))})

    p1.hooks = [_hook]
    cua = _CopyCua(lambda: [_click(p1, "regen"), _click(p1, "box"),
                            ("type", {"text": "hello"}), ("key", {"text": "Return"}),
                            _click(p1, "send"), _click(p1, "share"), _click(p1, "share prompt"),
                            _click(p1, "edit"), _click(p1, "copy")])
    out = p1.run(cua)
    assert out["text"] == _fixture_markdown(), logs
    users = _users(chrome, page)                         # the prompt, and nothing else
    assert len(users) == 1 and users[0].startswith("Please create a detailed"), users
    assert chrome.run(page.evaluate(base.BOX_JS)) == "draft"   # never sent, never typed on
    clicked = _clicked(chrome, page)
    for never in ("Regenerate response", "Share", "Share prompt", "Edit message"):
        assert never not in clicked, clicked
    for label, at in (("Share", "share"), ("Share prompt", "share prompt"), ("Edit message", "edit")):
        assert chrome.run(page.evaluate(      # each click aimed at that button itself
            "([x, y]) => document.elementFromPoint(x, y).closest('button').getAttribute('aria-label')",
            p1.at[at])) == label
    refused = _lines(logs, "REFUSED")
    assert len(refused) == 7, refused
    assert len(_lines(logs, "[cua] REFUSED a click on Send, Regenerate, Share, Edit, Copy "
                            "message or a table's own button — this task only clicks the Copy "
                            "button under ChatGPT's latest reply")) == 5, refused
    assert any("Click only the Copy button directly under ChatGPT's latest reply." in t
               for t in cua.told), cua.told


#: Something left open over the reply's row of icons (a popover, say), placed
#: over the whole row; a click closes it.
COVER_JS = """() => {
    const r = document.querySelector('[data-sr-reply-actions]').getBoundingClientRect();
    const c = document.createElement('div');
    c.dataset.srCover = '';
    c.style.cssText = `position: fixed; left: ${r.left - 10}px; top: ${r.top - 10}px; `
        + `width: ${r.width + 20}px; height: ${r.height + 20}px; z-index: 10; `
        + 'background: rgba(0, 0, 0, 0.3);';
    c.addEventListener('click', () => c.remove());
    document.body.appendChild(c);
}"""


def test_live_p1_a_copy_button_that_cannot_be_clicked_is_left_to_the_cua(
        chrome, page, p1, logs, monkeypatch):
    """The Copy button is found, but something covers it and its click times
    out. The CUA takes over: it closes what covers the row and presses Copy."""
    monkeypatch.setattr(research, "_CG_COPY_CLICK_MS", 500, raising=False)
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True)

    async def _hook():
        await page.add_style_tag(content=PIN_ROW_CSS)
        await page.evaluate(COVER_JS)
        p1.at = {k: await page.evaluate(CENTER_JS, s) for k, s in (
            ("copy", '[data-sr-act="copy"]'), ("cover", '[data-sr-cover]'))}
        assert await page.evaluate(
            "([x, y]) => !!document.elementFromPoint(x, y).closest('[data-sr-cover]')",
            p1.at["copy"])                               # the Copy button IS covered

    p1.hooks = [_hook]
    cua = _CopyCua(lambda: [_click(p1, "cover"), _click(p1, "copy")])
    out = p1.run(cua)
    assert _lines(logs, "the Copy button under ChatGPT's reply could not be clicked"), logs
    assert cua.missions == ["copy"]
    assert out["text"] == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]


def test_live_p1_without_a_cua_no_copy_button_means_no_brief(chrome, page, p1, logs):
    _cua_page(chrome, page, p1)
    out = p1.run(None)
    assert out["text"] == "", logs
    assert _lines(logs, "no Copy button found under ChatGPT's reply, and no CUA"), logs


# ── the CUA leaves the chat (wave 13 review) ────────────────────────────────

#: Another chat put on the screen by one click, as ChatGPT does it — inside
#: chatgpt.com, the tab never reloads. mode "sidebar": a conversation in the
#: sidebar; its click moves the tab to that chat's address and draws that
#: chat's thread instead of this one. mode "suggestion": a suggested reply under
#: the brief; its click SENDS it (one more message of the person's, at the same
#: address) and ChatGPT answers it. Either way the chat now on the screen holds
#: another brief (`paras`), named by the reply's marker, with its row of icons
#: and its Copy pinned where a click reaches it — every check but "is it the
#: same chat" keeps what that Copy hands out. The page's click listener records
#: the chip as "suggestion"; a link is not a button, so it records nothing.
CHAT_CHANGER_JS = """([mode, paras]) => {
    const draw = () => {
        const turn = document.getElementById('sr-turn').content.cloneNode(true);
        const col = turn.querySelector('div[class="flex flex-col gap-3 browser:gap-1"]');
        const user = document.getElementById('sr-user-block').content.cloneNode(true);
        user.querySelector('div[dir="auto"]').textContent =
            mode === 'sidebar' ? 'Please write a research brief on the Newfoundland.'
                               : 'Make it about the Newfoundland instead.';
        col.appendChild(user);
        const blk = document.getElementById('sr-assistant-block').content.cloneNode(true);
        blk.querySelector('[data-markdown-text-style]').innerHTML = paras.map((p, i) => i === 0
            ? '<h2>' + p.replace(/^## /, '') + '</h2>' : '<p><span>' + p + '</span></p>').join('');
        col.appendChild(blk);
        const row = document.getElementById('sr-reply-actions').content.cloneNode(true);
        const copy = row.querySelector('[data-sr-act="copy"]');
        copy.dataset.srName = 'other copy';
        copy.style.cssText = 'position:fixed;left:600px;top:400px;width:40px;height:30px;'
            + 'z-index:20;overflow:hidden';
        col.parentElement.appendChild(row);
        return turn;
    };
    const t = document.getElementById('sr-transcript');
    const el = document.createElement(mode === 'sidebar' ? 'a' : 'button');
    el.textContent = mode === 'sidebar' ? 'St Bernard brief (yesterday)' : 'Make it about the Newfoundland';
    el.dataset.srName = mode;
    el.style.cssText = 'position:fixed;left:4px;top:300px;width:160px;height:30px;display:block;'
        + 'z-index:30;background:#eee';
    if (mode === 'sidebar') el.href = '/c/another-chat';
    el.addEventListener('click', (e) => {
        e.preventDefault();
        if (mode === 'sidebar') {
            t.replaceChildren(draw());
            history.pushState({}, '', '/c/another-chat');
        } else {
            t.appendChild(draw());
        }
    });
    document.body.appendChild(el);
}"""


def _chat_changer_page(chrome, page, p1, mode):
    """No Copy button by its marker (a future rename), and a click that puts
    another chat holding OLD_BRIEF on the screen (CHAT_CHANGER_JS)."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True)

    async def _hook():
        await page.evaluate("() => document.querySelector('[data-sr-act=\"copy\"]')"
                            ".setAttribute('aria-label', 'Copy response')")
        await page.evaluate(CHAT_CHANGER_JS, [mode, OLD_BRIEF.split("\n\n")])
        p1.at = {"changer": await page.evaluate(CENTER_JS, f'[data-sr-name="{mode}"]'),
                 "other copy": [620, 415]}

    p1.hooks = [_hook]


@pytest.mark.parametrize("mode,moved", [
    ("sidebar", "(another page)"),
    ("suggestion", "(1 → 2 of your messages on screen)")])
def test_live_p1_a_cua_click_that_changes_the_chat_never_gives_its_brief(
        chrome, page, p1, logs, mode, moved):
    """⛔ The copy CUA's first click puts another chat on the screen — a
    conversation in the sidebar (another address, the same number of messages)
    or a suggested reply that is sent and answered (the same address, one more
    message) — and its next click is its own job: the Copy under the latest
    reply, which is now another brief. That copy is long enough, prose, not our
    prompt and the latest reply's text — only the chat has changed. The
    clipboard is not read; and the re-reads, three minutes later, read nothing
    from a tab that no longer shows the chat the brief was written in."""
    _chat_changer_page(chrome, page, p1, mode)
    cua = _CopyCua(lambda: [_click(p1, "changer"), _click(p1, "other copy")])
    out = p1.run(cua)
    assert _copied(chrome, page) == OLD_BRIEF                 # it WAS copied — another brief
    assert "Newfoundland" not in out["text"] and out["text"] == "", logs
    assert cua.missions == ["copy"]
    assert _lines(logs, "Phase 1: the clipboard was not read — the ChatGPT tab no longer "
                        f"shows this run's chat {moved}"), logs
    assert len(_lines(logs, "Phase 1: the brief was not read — the ChatGPT tab no longer "
                            f"shows the chat it was written in {moved}")) == 2, logs
    assert not _lines(logs, "brief taken from"), logs
    if mode == "suggestion":
        assert _clicked(chrome, page) == ["suggestion", "other copy"]
        assert len(chrome.run(page.evaluate(base.USERS_JS))) == 2
    else:
        assert _clicked(chrome, page) == ["other copy"]
        assert chrome.run(page.evaluate("() => location.href")).endswith("/c/another-chat")


@pytest.mark.parametrize("renamed", [False, True], ids=["page-read", "copy-button"])
def test_live_p1_a_chat_that_cannot_be_read(chrome, page, p1, logs, monkeypatch, renamed):
    """The chat's mark cannot be read (the page does not answer). The page
    read, which clicks nothing, reads as it always did (a control); the Copy
    fallback, whose CUA can leave the chat, cannot tell whether it has, and
    takes nothing."""
    async def _unreadable(_page):
        return None

    monkeypatch.setattr(research, "_chatgpt_user_msg_count", _unreadable)
    _open(chrome, page, "new", reply_actions=True, reply_renamed=renamed, streaming=True)
    out = p1.run()
    if not renamed:
        assert HEADING in out["text"] and LINK in out["text"], logs
        assert _lines(logs, "Phase 1: brief read from the page ("), logs
        return
    assert out["text"] == "", logs
    assert _clicked(chrome, page) == ["Copy", "Copy", "Copy"]
    assert len(_lines(logs, "the clipboard was not read — the ChatGPT tab no longer shows "
                            "this run's chat (the page could not be read)")) == 3, logs


#: A first draft whose every paragraph opens differently from the updated brief
#: (a follow-up rewrote it): the poll hook after the first reply.
def _rewritten_first_draft_hook(page):
    async def _rewrite():
        await page.evaluate(
            "() => document.querySelectorAll('[data-selected-text-overlay-target] p > span')"
            ".forEach((s) => { s.textContent = 'In the first draft of this brief: ' + s.textContent; })")
    return _rewrite


def test_live_p1_after_a_follow_up_the_cuas_copy_of_the_first_draft_is_refused(
        chrome, page, p1, logs):
    """⛔ The user added context mid-brief: two replies, each with its own Copy,
    and no Copy found by its marker (a future rename). The CUA presses the FIRST
    reply's Copy: the first draft — long enough, prose, not our prompt, and on
    this page — is not the latest reply's text, so it is refused, and the user's
    added context is not dropped. The re-read's CUA presses the latest reply's
    Copy and that is the brief."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True)
    p1.extra = EXTRA

    async def _pin_both_copies():
        await page.evaluate("""() => {
            const all = [...document.querySelectorAll('[data-sr-act="copy"]')];
            all.forEach((b, i) => {
                b.setAttribute('aria-label', 'Copy response');
                b.dataset.srName = i === 0 ? 'first copy' : 'latest copy';
                b.style.cssText = `position:fixed;left:${600 + 100 * i}px;top:400px;width:40px;`
                    + 'height:30px;z-index:20;overflow:hidden';
            });
        }""")

    p1.hooks = [_rewritten_first_draft_hook(page), _pin_both_copies]
    presses = iter([[("left_click", {"coordinate": [620, 415]})]]
                   + [[("left_click", {"coordinate": [720, 415]})]] * 2)
    cua = _CopyCua(lambda: next(presses))
    out = p1.run(cua)
    assert p1.polls == ["Phase1", "Phase1-followup"]
    first = chrome.run(page.evaluate(      # the first draft IS on the page
        "() => document.querySelector('[data-selected-text-overlay-target]').innerText"))
    assert first.count("In the first draft of this brief: ") == 7
    assert out["text"] == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["first copy", "latest copy"]
    assert cua.missions == ["copy", "copy"]
    assert len(_lines(logs, "was not used — it is not text of the latest reply on this "
                            "ChatGPT page")) == 1, logs


# ═══ 2. Which button ═══════════════════════════════════════════════════════
#
# chatgpt_brief_via_copy on a finished exchange (thread=True), no CUA.

def _brief(chrome, page, **kw):
    return chrome.run(research.chatgpt_brief_via_copy(page, ours=(PROMPT,), **kw))


#: A code block in the reply with its own "Copy" (as ChatGPT draws one), which
#: copies the code.
CODE_BLOCK_JS = """() => {
    const root = document.querySelector('[data-selected-text-overlay-target]');
    const pre = document.createElement('pre');
    pre.innerHTML = '<div><span>python</span><button aria-label="Copy" data-sr-name="code copy">'
        + 'Copy code</button></div><code>def rescue(dog):\\n    return dog.find(traveller)</code>';
    pre.querySelector('button').addEventListener('click',
        () => navigator.clipboard.writeText(pre.querySelector('code').textContent.repeat(40)));
    root.appendChild(pre);
}"""


@pytest.fixture
def quick(monkeypatch, fast, logs):
    monkeypatch.setattr(research, "_CG_COPY_READ_S", 1.0, raising=False)


def test_live_a_code_blocks_copy_button_is_never_used(chrome, page, quick, logs):
    """⛔ No row of icons under the reply, no marker on its text (a future
    rename) — only a code block's own "Copy", labelled exactly that. It sits in
    no turn's row, so it is never pressed."""
    _open(chrome, page, "new", thread=True, reply_renamed=True)
    chrome.run(page.evaluate(CODE_BLOCK_JS))
    assert _brief(chrome, page) == ""
    assert "code copy" not in _clicked(chrome, page)
    assert _lines(logs, "no Copy button found under ChatGPT's reply"), logs


def test_live_with_a_code_block_the_copy_under_the_reply_is_used(chrome, page, quick, logs):
    _open(chrome, page, "new", thread=True, reply_renamed=True, reply_actions=True)
    chrome.run(page.evaluate(CODE_BLOCK_JS))
    got = _brief(chrome, page)
    assert got.startswith(f"## {HEADING}") and "def rescue(dog)" in got, logs
    assert _clicked(chrome, page) == ["Copy"]


def test_live_a_copy_button_inside_the_reply_text_is_never_used(chrome, page, quick, logs):
    """A "Copy" inside the reply's own text (a table's, labelled plain "Copy"
    here — the captured one says "Copy table") is not the reply's Copy."""
    _open(chrome, page, "new", thread=True)
    chrome.run(page.evaluate("""() => {
        const root = document.querySelector('[data-markdown-text-style="assistant-message"]');
        const d = document.createElement('div');
        d.innerHTML = '<table><tr><td>Barry</td><td>1800</td></tr></table>'
            + '<button aria-label="Copy" data-sr-name="table copy">Copy table</button>';
        d.querySelector('button').addEventListener('click',
            () => navigator.clipboard.writeText(root.innerText));
        root.appendChild(d);
    }"""))
    assert _brief(chrome, page) == ""
    assert "table copy" not in _clicked(chrome, page)


def _second_exchange(chrome, page, prompt="And now the updated brief, please."):
    """Send a second message; wait for its reply."""
    chrome.run(page.click('[contenteditable="true"]'))
    chrome.run(page.keyboard.type(prompt))
    chrome.run(page.keyboard.press("Enter"))
    chrome.run(page.wait_for_function(
        "() => parseInt(document.body.dataset.replies || '0', 10) >= 2", timeout=10000))


def test_live_an_earlier_replys_copy_is_never_used(chrome, page, quick, logs):
    """⛔ The latest reply has no Copy yet; the earlier one has. Its copy would
    be an older brief handed back as the latest. (The latest turn's only
    Copy-like button is the user's own "Copy message".)"""
    _open(chrome, page, "new", thread=True, reply_actions=True)
    _second_exchange(chrome, page)
    chrome.run(page.evaluate(
        "() => [...document.querySelectorAll('[data-sr-reply-actions]')].pop().remove()"))
    assert _brief(chrome, page) == ""
    assert _clicked(chrome, page) == []


def test_live_with_no_reply_marker_a_row_before_the_newest_message_is_never_pressed(
        chrome, page, quick, logs):
    """⛔ No marker names the replies (a future rename), and the latest reply's
    row of icons is not drawn yet. The last Copy row on the page is then the
    EARLIER reply's, before the person's newest message — an older brief. It is
    not pressed; the CUA is asked instead (here there is none)."""
    _open(chrome, page, "new", thread=True, reply_renamed=True, reply_actions=True)
    _second_exchange(chrome, page)
    chrome.run(page.evaluate(
        "() => [...document.querySelectorAll('[data-sr-reply-actions]')].pop().remove()"))
    assert chrome.run(page.evaluate(       # one Copy row left: the earlier reply's
        "(s) => document.querySelectorAll(s).length", research.CHATGPT_COPY_REPLY_SEL)) == 1
    assert _brief(chrome, page) == ""
    assert _clicked(chrome, page) == []
    assert _lines(logs, "no Copy button found under ChatGPT's reply, and no CUA to click it"), logs


def test_live_with_no_marker_on_the_persons_message_the_whole_page_is_looked_at(
        chrome, page, quick, logs):
    """A rename of the person's own message too: where the latest exchange
    begins cannot be told, so the Copy row and the copy's text are looked for
    across the page, as before — the brief is not lost for it. (A control: it
    passes before the latest-reply check too, and fails if that check refuses
    what it cannot place.)"""
    _open(chrome, page, "new", thread=True, reply_renamed=True, reply_actions=True)
    chrome.run(page.evaluate("() => document.querySelector('[data-user-message-bubble]')"
                             ".removeAttribute('data-user-message-bubble')"))
    assert chrome.run(page.evaluate(
        "(s) => document.querySelectorAll(s).length", research.CHATGPT_USER_MSG_SEL)) == 0
    assert _brief(chrome, page) == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]


#: A second row of icons in the reply's turn, after the one shown, that ChatGPT
#: keeps hidden — as it draws a table's icons twice, one of them hidden, for two
#: screen widths (the capture's CompactSource / LeadingSource).
HIDDEN_ROW_JS = """() => {
    const row = document.getElementById('sr-reply-actions').content.cloneNode(true).firstElementChild;
    row.style.display = 'none';
    row.removeAttribute('data-sr-reply-actions');
    row.querySelector('[aria-label="Copy"]').dataset.srName = 'hidden copy';
    const shown = document.querySelector('[data-sr-reply-actions]');
    shown.parentElement.appendChild(row);
}"""


def test_live_a_hidden_copy_button_is_passed_over(chrome, page, quick, logs):
    """A Copy row ChatGPT keeps hidden after the one it shows is not the one to
    press — pressing it would time out and lose the brief."""
    _open(chrome, page, "new", thread=True, reply_actions=True)
    chrome.run(page.evaluate(HIDDEN_ROW_JS))
    assert chrome.run(page.evaluate(
        "() => !!document.querySelector('[data-turn-key] [data-sr-name=\"hidden copy\"]')"))
    got = _brief(chrome, page)
    assert got == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]


#: A later turn that holds no reply the page read would read (no reply marker
#: names it — a reply of another kind, a notice), with its own row of icons.
LATER_TURN_JS = """() => {
    const turn = document.getElementById('sr-turn').content.cloneNode(true);
    const col = turn.querySelector('div[class="flex flex-col gap-3 browser:gap-1"]');
    const note = document.createElement('div');
    note.className = 'block-BQZwFn';
    note.textContent = 'Something went wrong while generating the response.';
    col.appendChild(note);
    const row = document.getElementById('sr-reply-actions').content.cloneNode(true).firstElementChild;
    row.removeAttribute('data-sr-reply-actions');
    row.querySelector('[aria-label="Copy"]').dataset.srName = 'later copy';
    col.parentElement.appendChild(row);
    document.getElementById('sr-transcript').appendChild(turn);
}"""


def test_live_a_later_turns_copy_is_not_the_latest_replys(chrome, page, quick, logs):
    """⛔ The page read reads the latest reply its marker names; the Copy pressed
    is THAT reply's, in its own turn — not the Copy of a later turn that holds no
    such reply."""
    _open(chrome, page, "new", thread=True, reply_actions=True)
    chrome.run(page.evaluate(LATER_TURN_JS))
    got = _brief(chrome, page)
    assert got == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]


#: A "Copy" elsewhere on the page, after the transcript and in no turn's row —
#: a side panel's, say. It copies text that is on the page and long enough.
PANEL_COPY_JS = """() => {
    const panel = document.createElement('aside');
    panel.innerHTML = '<button aria-label="Copy" data-sr-name="panel copy"><svg></svg></button>';
    panel.querySelector('button').addEventListener('click',
        () => navigator.clipboard.writeText(document.body.innerText));
    document.body.appendChild(panel);
}"""


def test_live_a_copy_outside_every_turns_row_is_never_used(chrome, page, quick, logs):
    """⛔ No marker names the reply (a future rename), so the Copy is looked for
    across the page — but only in a turn's own row of icons, where the capture
    puts it. A side panel's "Copy" after the transcript is never pressed."""
    _open(chrome, page, "new", thread=True, reply_renamed=True, reply_actions=True)
    chrome.run(page.evaluate(PANEL_COPY_JS))
    got = _brief(chrome, page)
    assert got == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]


def test_live_a_reply_no_turn_holds_gets_no_copy_button(chrome, page, quick, logs):
    """⛔ The reply's marker still names it, but no turn marker holds it (a
    rename of the turn). Its row's Copy is on the page and the marker names it —
    yet it is not looked for across the page, where it could as well be an
    earlier reply's: none is found, and the CUA is asked to press it (here there
    is no CUA, so no brief)."""
    _open(chrome, page, "new", thread=True, reply_actions=True)
    chrome.run(page.evaluate("() => document.querySelector('[data-turn-key]').removeAttribute('data-turn-key')"))
    assert chrome.run(page.evaluate(
        "(s) => document.querySelectorAll(s).length", research.CHATGPT_TURN_SEL)) == 0
    assert chrome.run(page.evaluate(
        "(s) => document.querySelectorAll(s).length", research.CHATGPT_ASSISTANT_MSG_SEL)) == 1
    assert chrome.run(page.evaluate(
        "(s) => [...document.querySelectorAll(s)].map((b) => b.getAttribute('aria-label'))",
        research.CHATGPT_COPY_REPLY_SEL)) == ["Copy"]
    assert chrome.run(research._chatgpt_find_copy_button(page)) is None
    assert _brief(chrome, page) == ""
    assert _clicked(chrome, page) == []
    assert _lines(logs, "no Copy button found under ChatGPT's reply, and no CUA to click it"), logs


def test_live_the_users_copy_message_is_never_used(chrome, page, quick, logs):
    """A message of ours after the latest reply (a follow-up whose reply has not
    started): its "Copy message" is ours, and its turn holds no reply — the
    latest reply's Copy, in that reply's own turn, is the one (the page read
    reads that reply too)."""
    _open(chrome, page, "new", thread=True, reply_actions=True)
    chrome.run(page.evaluate("""() => {
        const turn = document.getElementById('sr-turn').content.cloneNode(true);
        const col = turn.querySelector('div[class="flex flex-col gap-3 browser:gap-1"]');
        const user = document.getElementById('sr-user-block').content.cloneNode(true);
        user.querySelector('div[dir="auto"]').textContent = 'One more thing.';
        col.appendChild(user);
        document.getElementById('sr-transcript').appendChild(turn);
    }"""))
    got = _brief(chrome, page)
    assert got == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]


# ═══ 3. The clipboard marker, and what counts as the brief ══════════════════

def test_live_a_clipboard_that_cannot_be_read_is_never_used(chrome, page, quick, logs):
    """No clipboard read here → the Copy button is not even pressed, and a plain
    line says why."""
    _open(chrome, page, "new", thread=True, reply_actions=True)
    chrome.run(chrome.ctx.clear_permissions())
    try:
        assert _brief(chrome, page) == ""
        assert _clicked(chrome, page) == []
        assert _lines(logs, "Phase 1: can't use the clipboard in this browser"), logs
    finally:
        chrome.run(chrome.ctx.grant_permissions(["clipboard-read", "clipboard-write"],
                                                origin=ORIGIN))


def test_live_a_chatgpt_tab_behind_another_tab_still_gets_its_brief(chrome, page, quick, logs):
    """Another tab of the same Chrome is in front of ChatGPT's: the clipboard
    answers only the tab in front, and a tab behind reads it back empty. The
    ChatGPT tab is brought to the front first, so the Copy button still gives
    the brief. (Measured on a finished chat nobody has typed into: headless
    Chrome keeps the clipboard with a tab that has had typing in it, whatever
    tab is in front, so run_phase1's own page cannot show this here.)"""
    _open(chrome, page, "new", thread=True, reply_renamed=True, reply_actions=True)
    other = chrome.run(chrome.ctx.new_page())
    try:
        _open(chrome, other, "new", thread=True)            # opened after ChatGPT's: in front
        chrome.run(page.evaluate(_WRITE_JS, "probe"))
        assert chrome.run(page.evaluate(_READ_JS)) == "", "the ChatGPT tab is not behind"
        got = _brief(chrome, page)
    finally:
        chrome.run(other.close())
    assert got == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]
    assert not _lines(logs, "can't use the clipboard"), logs


def test_live_a_clipboard_that_does_not_keep_the_marker_is_never_used(chrome, page, quick, logs):
    """The marker is written and something else reads back (a clipboard tool
    that rewrites it, a write that did not land): the clipboard cannot tell a
    copy from what was there, so the Copy button is not pressed."""
    _open(chrome, page, "new", thread=True, reply_actions=True)
    # The same (isolated) script world the reads run in; the page's own code
    # cannot reach it.
    chrome.run(page.evaluate("() => { navigator.clipboard.readText = async () => 'an older text'; }"))
    assert _brief(chrome, page) == ""
    assert _clicked(chrome, page) == []
    assert _lines(logs, "can't use the clipboard in this browser (the marker did not come back)"), logs


@pytest.mark.parametrize("gives", ["", "nothing"], ids=["the-brief", "nothing"])
def test_live_p1_the_clipboard_is_given_back_after_the_copy(chrome, page, p1, logs, gives):
    """⛔ Fleet workers and the owner share ONE clipboard. Whatever the Copy
    gave — the whole brief, or nothing (the marker would stay) — the clipboard
    holds what it held before once the fallback is done."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True,
          copy_gives=gives)
    _set_clip(chrome, page, "the owner's own clipboard")
    out = p1.run()
    assert out["text"] == ("" if gives else _fixture_markdown()), logs
    assert _copied(chrome, page) == (None if gives else _fixture_markdown())
    assert _clicked(chrome, page) == ["Copy"] * (3 if gives else 1)
    assert _clip(chrome, page) == "the owner's own clipboard"


def test_live_a_clipboard_that_could_not_be_read_first_is_emptied_not_left_with_the_marker(
        chrome, page, quick, logs):
    """What the clipboard held could not be read before the marker went on:
    nothing can be put back, so it is emptied — never left holding the marker.
    (The owner's content is what cannot be read here; the marker reads back,
    so the Copy is still pressed.)"""
    _open(chrome, page, "new", thread=True, reply_actions=True, copy_gives="nothing")
    _set_clip(chrome, page, "the owner's content that cannot be read")
    # The program's script world (see the test above).
    chrome.run(page.evaluate("""() => {
        const real = navigator.clipboard.readText.bind(navigator.clipboard);
        navigator.clipboard.readText = async () => {
            const t = await real();
            if (t === "the owner's content that cannot be read") throw new Error('Read denied.');
            return t;
        };
    }"""))
    assert _brief(chrome, page) == ""
    assert _clicked(chrome, page) == ["Copy"]
    assert _lines(logs, "was not used — nothing was copied"), logs
    assert _clip(chrome, page) == ""


MARK = "superresearch-copy-check-0123456789abcdef"
CODE = "\n".join(["def rescue(dog, traveller):",
                  "    # find the traveller in the snow and bring them back to the hospice",
                  "    for step in range(dog.max_steps):",
                  "        if dog.smells(traveller): return dog.carry(traveller)",
                  "    return None"] * 12)
PLAIN = OLD_BRIEF.replace("## ", "")
#: A brief in Japanese, written as headings and bullet sentences: no spaces
#: between its words, so its lines are counted by their letters.
JA_LINES = [
    "- セントバーナードの歴史について、修道院の記録と当時の新聞記事を比べて調べる。",
    "- 峠での救助活動がいつ始まり、どのような犬が選ばれていたのかを一次資料で確かめる。",
    "- 有名な救助の話のうち、記録で裏付けられるものと後から作られた話を分けて書く。",
    "- 現代の犬種標準が何を求めているのか、各国のケンネルクラブの違いも含めて説明する。",
    "- よく見られる病気と、繁殖の前に行われている検査の種類と頻度を表にまとめる。",
    "- 資料どうしの記述が食い違う場合は両方を示し、どちらがより確かなのかを述べる。",
]
JA_BRIEF = "\n".join(["## 調査の概要"] + JA_LINES + ["## 調べること"] + JA_LINES * 8
                     + ["## 成果物"] + JA_LINES)
#: The same length in Japanese, but only short labels — no line reads like prose.
JA_LABELS = "\n".join(["## 調査の概要"] + ["- 犬種：セントバーナード", "- 地域：スイスとイタリア",
                                          "- 期間：十八世紀から現在"] * 60)


def _sized(n):
    """A brief of exactly `n` characters (cut from PLAIN, repeated)."""
    t = (PLAIN + "\n\n" + PLAIN)[:n]
    assert len(t) == n and t == t.strip()
    return t


#: One table on its own, as a table's own "Copy table" hands it out (the
#: owner's captured brief has four): past the floor, and every row as wordy as
#: prose — but a table is not the brief.
TABLE = "\n".join(["| Part of the brief | What the research agent should do |", "| --- | --- |"]
                  + [f"| {k} | {v.strip()} |" for k, v in
                     (p.split(":", 1) for p in OLD_BRIEF.split("\n\n")[1:])])


#: A short brief padded past the floor by an image's ADDRESS — which the page
#: read does not count either (`_doc_img_prose_len`).
IMAGED = ("\n\n".join(PLAIN.split("\n\n")[:4])
          + "\n\n![chart](https://example.org/" + "a" * 2000 + ".png)")


@pytest.mark.parametrize("text,why", [
    (MARK, "nothing was copied"),
    ("", "nothing was copied"),
    ("   \n", "nothing was copied"),
    ("x" * 300, "it was only 300 characters"),
    # The page read's own floor: more than 2000 characters of prose.
    (_sized(2000), "it was only 2000 characters"),
    (_sized(2001), ""),
    (IMAGED, f"it was only {research._doc_img_prose_len(IMAGED)} characters"),
    (PROMPT + "\n\n" + FEEDBACK, "it was our own prompt, not ChatGPT's reply"),
    ("St_Bernard_notes.pdf PDF " + PROMPT + "\n\n" + FEEDBACK,
     "it was our own prompt, not ChatGPT's reply"),
    (CODE, "it does not read like a brief"),
    (OLD_BRIEF, ""),
    (PLAIN, ""),
    (_fixture_markdown(), ""),
    # A script written without spaces: its lines are counted by their letters.
    (JA_BRIEF, ""),
    (JA_LABELS, "it does not read like a brief"),
    (TABLE, "it does not read like a brief"),
    # A brief WITH a table is still a brief.
    (OLD_BRIEF + "\n\n" + TABLE, ""),
], ids=["marker", "empty", "blank", "300", "2000", "2001", "image-address", "our-prompt",
        "our-prompt-after-a-file-card", "code", "another-brief", "plain", "the-reply",
        "japanese", "japanese-labels", "a-table-alone", "a-brief-with-a-table"])
def test_what_counts_as_the_brief(text, why):
    assert research._chatgpt_copy_verdict(text, MARK, (PROMPT + "\n\n" + FEEDBACK,)) == why


def test_a_brief_needs_three_lines_of_prose():
    two = "\n\n".join(OLD_BRIEF.split("\n\n")[:3]) + "\n\n" + "x" * 2000
    assert research._chatgpt_copy_verdict(two, MARK) == "it does not read like a brief"
    three = "\n\n".join(OLD_BRIEF.split("\n\n")[:4]) + "\n\n" + "x" * 2000
    assert research._chatgpt_copy_verdict(three, MARK) == ""


def test_the_copy_marker_is_one_place_and_takes_both_pages():
    parts = [p.strip() for p in research.CHATGPT_COPY_REPLY_SEL.split(",")]
    assert parts == ['[data-testid="copy-turn-action-button"]',
                     '.turn-action-controls button[aria-label="Copy"]']
    assert research._CG_JS_MARKERS["__CG_COPY__"] is research.CHATGPT_COPY_REPLY_SEL


def test_live_the_marker_names_only_the_replys_own_copy(chrome, page, quick):
    """On the captured long brief — the user's "Copy message", four tables'
    "Copy table" and "Expand table", the reply's row — plus a code block's own
    "Copy" and a side panel's, the marker names exactly one button per reply:
    the reply's Copy in its turn's row. On the old page, its testid."""
    _open(chrome, page, "new", thread=True, reply_actions=True, long_brief=True)
    chrome.run(page.evaluate(CODE_BLOCK_JS))
    chrome.run(page.evaluate(PANEL_COPY_JS))
    names = ("(s) => [...document.querySelectorAll(s)].map((b) => "
             "b.dataset.srName || b.getAttribute('aria-label'))")
    assert chrome.run(page.evaluate(
        "() => document.querySelectorAll('button[aria-label^=\"Copy\"]').length")) == 8
    assert chrome.run(page.evaluate(names, research.CHATGPT_COPY_REPLY_SEL)) == ["Copy"]
    _open(chrome, page, "old", thread=True, reply_actions=True)
    assert chrome.run(page.evaluate(names, research.CHATGPT_COPY_REPLY_SEL)) == ["Copy"]
