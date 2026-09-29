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
that may only click, and never on Send or Regenerate), and read the clipboard,
keeping the text only if it is not the marker, is long enough, is not our own
prompt and reads like a brief.

⚠ ASSUMED, NOT CAPTURED: WHERE the Copy button sits. The capture names it
(aria-label "Copy"; the user's own message has "Copy message") but not its
place. The fixtures put the reply's row of icons right after the reply — inside
the reply's block on the new page, inside its article on the old page (hooks
body[data-reply-actions]). The owner's ~/Downloads/chatgpt-copy-button-capture.json
will settle it; CHATGPT_COPY_REPLY_SEL is the one line a new capture edits.

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
OLD_BRIEF = "\n\n".join([
    "## Research brief: the Newfoundland",
    "Scope: the breed's origins on the island, its water rescue work, and the "
    "health problems that come with its size and its dense double coat.",
    "Questions to answer: when the breed was first described, how its rescue "
    "reputation formed, and which of the famous rescues are actually documented.",
    "Method: prefer primary sources and veterinary studies over breeder material, "
    "and give both sides where the sources disagree about a date or a number.",
    "Deliverable: a structured report with sections, sources and open questions "
    "for the research agent to pursue, every claim traceable to its source.",
])
#: A long user feedback, so our own prompt is long and reads like prose — then
#: only the "is it our prompt" check can refuse a copy of it.
FEEDBACK = ("Cover the hospice kennels in the twentieth century in much more detail "
            "than usual, including who ran them and how the dogs were trained.\n"
            "Explain how the tunnel changed the work of the dogs at the pass, and "
            "what the monks did with the dogs once travellers stopped coming.\n"
            "Say which modern breeders still work with the hospice line, and how "
            "their dogs differ from the show dogs registered elsewhere today.")
EXTRA = ("Add the hospice's own records of every rescue they wrote down, with the "
         "year and the name of the dog wherever the records give one.\n"
         "Say which of those rescues were reported in newspapers at the time, and "
         "which ones only appear in books written a century or more later.\n"
         "Compare the number of rescues in the records with the famous figure of "
         "forty that is usually quoted for Barry, and explain where it came from.")

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


def _html_for(layout, *, thread=False, prompt=PROMPT, **hooks):
    """The rebuilt page, with test hooks on <body>: reply_actions=True →
    data-reply-actions="1"; copy_gives="nothing" → data-copy-gives="nothing"."""
    src = (base.FIX / f"{layout}_page.html").read_text(encoding="utf-8")
    body = '<body data-sr-fixture="chat" data-sr-prompt="">'
    assert src.count(body) == 1, "the fixture's <body> contract changed"
    extra = "".join(f' data-{k.replace("_", "-")}="{"1" if v is True else _html.escape(str(v))}"'
                    for k, v in sorted(hooks.items()) if v)
    return src.replace(body, (f'<body data-sr-fixture="{"thread" if thread else "chat"}" '
                              f'data-sr-prompt="{_html.escape(prompt, quote=True)}"{extra}>'))


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

    chrome.run(_go())


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
    monkeypatch.setattr(research, "_CG_COPY_READ_S", 1.0)
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


def test_live_p1_a_copy_that_copied_nothing_never_hands_back_the_old_clipboard(
        chrome, page, p1, logs):
    """⛔ The clipboard holds an EARLIER brief and the Copy click copies nothing.
    Without the marker that old brief would come back as this run's. Every
    re-read tries the Copy button again."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True,
          copy_gives="nothing")
    _set_clip(chrome, page, OLD_BRIEF)
    assert research._chatgpt_copy_verdict(OLD_BRIEF, "m") == ""   # it WOULD pass
    out = p1.run()
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
    copied = _clip(chrome, page)
    assert FEEDBACK.split("\n")[0] in copied and len(copied) > 500
    assert out["text"] == "", logs
    assert _lines(logs, "was not used — it was our own prompt"), logs


def test_live_p1_after_a_follow_up_the_latest_reply_is_copied(chrome, page, p1, logs):
    """The user added context mid-brief: a follow-up, a second reply. The Copy
    under the LATEST reply gives the updated brief, never the first draft."""
    _open(chrome, page, "new", reply_actions=True, reply_renamed=True, streaming=True)
    p1.extra = EXTRA

    async def _mark_first_draft():
        await page.evaluate(
            "() => { document.querySelector('[data-selected-text-overlay-target] h2')"
            ".textContent = 'Research brief: the St Bernard (first draft)'; }")

    p1.hooks = [_mark_first_draft]
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
    copied = _clip(chrome, page)
    assert EXTRA.split("\n")[0] in copied and len(copied) > 500
    assert out["text"] == "", logs
    assert _lines(logs, "was not used — it was our own prompt"), logs


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


def test_live_p1_the_copy_cua_only_clicks_and_never_regenerate_or_send(chrome, page, p1, logs):
    """⛔ The CUA tries what must never happen: Regenerate (it would throw the
    brief away), a word typed into the box and Enter, Send on a leftover draft.
    None of it is carried out; its Copy click still gives the brief."""
    _cua_page(chrome, page, p1, draft=True)
    cua = _CopyCua(lambda: [_click(p1, "regen"), _click(p1, "box"),
                            ("type", {"text": "hello"}), ("key", {"text": "Return"}),
                            _click(p1, "send"), _click(p1, "copy")])
    out = p1.run(cua)
    assert out["text"] == _fixture_markdown(), logs
    users = _users(chrome, page)                         # the prompt, and nothing else
    assert len(users) == 1 and users[0].startswith("Please create a detailed"), users
    assert chrome.run(page.evaluate(base.BOX_JS)) == "draft"   # never sent, never typed on
    assert "Regenerate response" not in _clicked(chrome, page)
    refused = _lines(logs, "REFUSED")
    assert len(refused) == 4, refused
    assert len(_lines(logs, "[cua] REFUSED a click on Send or Regenerate — this task only "
                            "clicks the Copy button under ChatGPT's latest reply")) == 2, refused
    assert any("Click only the Copy button directly under ChatGPT's latest reply." in t
               for t in cua.told), cua.told


def test_live_p1_without_a_cua_no_copy_button_means_no_brief(chrome, page, p1, logs):
    _cua_page(chrome, page, p1)
    out = p1.run(None)
    assert out["text"] == "", logs
    assert _lines(logs, "no Copy button found under ChatGPT's reply, and no CUA"), logs


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
    monkeypatch.setattr(research, "_CG_COPY_READ_S", 1.0)


def test_live_a_code_blocks_copy_button_is_never_used(chrome, page, quick, logs):
    """⛔ No row of icons under the reply, no marker on its text (a future
    rename) — only a code block's own "Copy". It is never pressed."""
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
    """A "Copy" inside the reply's own text (a table's, say — not a code block)
    is not the reply's Copy."""
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
    be an older brief handed back as the latest."""
    _open(chrome, page, "new", thread=True, reply_actions=True)
    _second_exchange(chrome, page)
    chrome.run(page.evaluate(
        "() => [...document.querySelectorAll('[data-sr-reply-actions]')].pop().remove()"))
    assert _brief(chrome, page) == ""
    assert _clicked(chrome, page) == []


def test_live_a_hidden_copy_button_is_passed_over(chrome, page, quick, logs):
    """A "Copy" ChatGPT keeps hidden (a closed menu's, say) after the row is not
    the one to press — pressing it would time out and lose the brief."""
    _open(chrome, page, "new", thread=True, reply_actions=True)
    chrome.run(page.evaluate("""() => {
        const m = document.createElement('div');
        m.style.display = 'none';
        m.innerHTML = '<button aria-label="Copy" data-sr-name="hidden copy">Copy</button>';
        document.querySelector('main').appendChild(m);
    }"""))
    got = _brief(chrome, page)
    assert got == _fixture_markdown(), logs
    assert _clicked(chrome, page) == ["Copy"]


def test_live_the_users_copy_message_is_never_used(chrome, page, quick, logs):
    """A message of ours after the latest reply (a follow-up whose reply has not
    started): its "Copy message" is ours — the reply's Copy is the one."""
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


MARK = "superresearch-copy-check-0123456789abcdef"
CODE = "\n".join(["def rescue(dog, traveller):",
                  "    # find the traveller in the snow and bring them back to the hospice",
                  "    for step in range(dog.max_steps):",
                  "        if dog.smells(traveller): return dog.carry(traveller)",
                  "    return None"] * 6)
PLAIN = OLD_BRIEF.replace("## ", "")


@pytest.mark.parametrize("text,why", [
    (MARK, "nothing was copied"),
    ("", "nothing was copied"),
    ("   \n", "nothing was copied"),
    ("x" * 300, "it was only 300 characters"),
    (PROMPT + "\n\n" + FEEDBACK, "it was our own prompt, not ChatGPT's reply"),
    ("St_Bernard_notes.pdf PDF " + PROMPT + "\n\n" + FEEDBACK,
     "it was our own prompt, not ChatGPT's reply"),
    (CODE, "it does not read like a brief"),
    (OLD_BRIEF, ""),
    (PLAIN, ""),
    (_fixture_markdown(), ""),
])
def test_what_counts_as_the_brief(text, why):
    assert research._chatgpt_copy_verdict(text, MARK, (PROMPT + "\n\n" + FEEDBACK,)) == why


def test_a_brief_needs_three_lines_of_prose():
    two = "\n\n".join(OLD_BRIEF.split("\n\n")[:3]) + "\n\n" + "x" * 400
    assert research._chatgpt_copy_verdict(two, MARK) == "it does not read like a brief"
    three = "\n\n".join(OLD_BRIEF.split("\n\n")[:4]) + "\n\n" + "x" * 300
    assert research._chatgpt_copy_verdict(three, MARK) == ""


def test_the_copy_marker_is_one_place_and_takes_both_pages():
    parts = [p.strip() for p in research.CHATGPT_COPY_REPLY_SEL.split(",")]
    assert parts == ['[data-testid="copy-turn-action-button"]', 'button[aria-label="Copy"]']
    assert research._CG_JS_MARKERS["__CG_COPY__"] is research.CHATGPT_COPY_REPLY_SEL
