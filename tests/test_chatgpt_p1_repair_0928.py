"""ChatGPT Phase 1, repaired 2026-09-29 — measured in real Chrome on the rebuilt
pages (tests/fixtures/chatgpt_0928, see test_chatgpt_new_page_0928.py for how
those pages are pinned to the owner's captures).

1. A message with an ATTACHED FILE (Phase 1 with the user's sources) is sent,
   confirmed and verified. ChatGPT draws the file card inside the user message,
   above the text, so the whole message reads "St_Bernard_notes.pdf PDF Please
   create…" — and the "starts with the prompt" check refused a real send while
   ChatGPT was already writing the brief.
2. Phase 1's own wiring, EXECUTED: run_phase1 runs against the page. Its verify
   gate needs OUR prompt (a Stop button beside other text is not "generating"),
   the CUA fallback runs only when nothing was sent, and the submit after it
   uses the box the CUA put the caret in — for the brief and the follow-up.
   These were pinned only by counting strings in run_phase1's source.

Browser tests SKIP when patchright or Chrome is missing.
"""
import html as _html
from types import SimpleNamespace

import pytest

import research
import test_chatgpt_new_page_0928 as base

PROMPT = base.PROMPT
LAYOUTS = base.LAYOUTS
USERS_JS = base.USERS_JS
CARD = "St_Bernard_notes.pdf"
GENERATING = "The response is still generating. CONCLUSION: GENERATING"

# The shared real-Chrome fixtures (one browser per module).
chrome = base.chrome
page = base.page
fast = base.fast
logs = base.logs


def _html_for(layout, *, thread=False, prompt=PROMPT, **hooks):
    """The rebuilt page with test hooks on <body> (attach=True → data-attach="1")."""
    src = (base.FIX / f"{layout}_page.html").read_text(encoding="utf-8")
    body = '<body data-sr-fixture="chat" data-sr-prompt="">'
    assert src.count(body) == 1, "the fixture's <body> contract changed"
    extra = "".join(f' data-{k}="1"' for k, v in sorted(hooks.items()) if v)
    return src.replace(body, (f'<body data-sr-fixture="{"thread" if thread else "chat"}" '
                              f'data-sr-prompt="{_html.escape(prompt, quote=True)}"{extra}>'))


def _load(chrome, page, layout, **kw):
    chrome.run(page.set_content(_html_for(layout, **kw)))


def _browser(page):
    return SimpleNamespace(page=page)


def _users(chrome, page):
    return chrome.run(page.evaluate(USERS_JS))


# ═══ 1. A message with an attached file ═════════════════════════════════════

@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_a_prompt_sent_with_an_attached_file_is_confirmed_and_verified(
        chrome, page, fast, logs, layout):
    """The owner's Phase 1 with sources: the file card is IN the message, above
    the prompt. The submit must say "sent", and the verify must say generating."""
    _load(chrome, page, layout, attach=True, streaming=True)
    out = {}
    ok = chrome.run(research.submit_chatgpt_direct(_browser(page), PROMPT, outcome=out))
    users = _users(chrome, page)
    # The card really is in the message, before the text (else this measures nothing).
    assert len(users) == 1 and users[0].startswith(CARD) and users[0].endswith(PROMPT), users
    assert ok is True and out["state"] == "sent", logs
    ver = chrome.run(research.wait_until_verified(
        research.verify_chatgpt_generating, page, "Phase1", max_retries=3, interval=0,
        chatgpt_prompt=PROMPT))
    assert ver is True, logs


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_verifier_reads_the_text_not_the_file_card(chrome, page, logs, layout):
    _load(chrome, page, layout, thread=True, attach=True)
    assert _users(chrome, page)[0].startswith(CARD)
    v = research._chatgpt_sent_prompt_verifier(PROMPT, "Phase1")
    assert chrome.run(v(page)) is True, logs
    # And "est" under a file card is still not the prompt.
    _load(chrome, page, layout, thread=True, attach=True, prompt="est")
    assert chrome.run(research.verify_chatgpt_generating(page)) is True
    assert chrome.run(v(page)) is False


def _verify_with_cua_saying_generating(chrome, page, monkeypatch):
    """wait_until_verified with the DOM check failing, so only the CUA
    diagnosis ("still generating") can confirm — the second door."""
    async def _dom_says_no(p):
        return False

    async def _shadow(p, **kw):
        return {"text": GENERATING}

    async def _switch(p):
        return None

    monkeypatch.setattr(research, "_shadow_observed_cua", _shadow)
    return chrome.run(research.wait_until_verified(
        _dom_says_no, page, "Phase1", browser=SimpleNamespace(switch_to_page=_switch),
        cua_client=object(), max_retries=6, interval=0, chatgpt_prompt=PROMPT))


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_cua_confirm_reads_the_text_not_the_file_card(
        chrome, page, fast, logs, monkeypatch, layout):
    _load(chrome, page, layout, thread=True, attach=True)
    assert _verify_with_cua_saying_generating(chrome, page, monkeypatch) is True, logs
    assert any("CUA confirms generating" in m for _lv, m in logs), logs
    _load(chrome, page, layout, thread=True, attach=True, prompt="est")
    assert _verify_with_cua_saying_generating(chrome, page, monkeypatch) is False


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_a_message_without_its_text_block_is_read_whole(chrome, page, logs, layout):
    """A future page whose message text lost `whitespace-pre-wrap`: the message
    is read whole — the prompt is still recognised, never read as nothing."""
    _load(chrome, page, layout, thread=True)
    chrome.run(page.evaluate(
        "() => document.querySelectorAll('.whitespace-pre-wrap')"
        ".forEach(e => e.classList.remove('whitespace-pre-wrap'))"))
    assert chrome.run(page.evaluate("() => document.querySelectorAll('.whitespace-pre-wrap').length")) == 0
    v = research._chatgpt_sent_prompt_verifier(PROMPT, "Phase1")
    assert chrome.run(v(page)) is True, logs


# ═══ 2. Phase 1's own wiring, EXECUTED ══════════════════════════════════════
#
# run_phase1 itself runs against the rebuilt page in Chrome: the real submit,
# the real CUA fallback, the real verify gate with its CUA diagnosis and fix.
# Stubbed: the steps BEFORE the submit (sign-in probe, observer, human check,
# tier, Deep Research clear), the stream poll and the extractor AFTER the gate,
# and the Anthropic client — which answers each CUA mission with one scripted
# turn of computer actions that the REAL agent_loop / execute_action carry out.

class _Reached(Exception):
    """run_phase1 got past its verify gate: the brief extractor was called."""


_MISSION_NAMES = {research.PROMPT_SUBMIT_FALLBACK: "focus",
                  research.PROMPT_DIAGNOSE: "diagnose",
                  research.PROMPT_FIX_ISSUE: "fix"}

#: The box's centre in the viewport.
BOX_CENTER_JS = """() => {
    const r = document.querySelector('[contenteditable="true"]').getBoundingClientRect();
    return [Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2)];
}"""

#: ChatGPT's composer stays at the bottom of the window while the thread
#: scrolls; pinned here too, so a scripted CUA click lands on the box however
#: long the thread grows (the rebuilt page otherwise lets the reply push it down).
PIN_COMPOSER_CSS = "form { position: fixed; left: 140px; right: 140px; bottom: 16px; background: #fff; }"

#: A box no ChatGPT marker names (a future rename); the typing still works, and
#: it keeps its height, so it stays where a CUA click was aimed.
UNNAME_BOX_JS = """() => {
    const b = document.querySelector('.ProseMirror');
    b.style.minHeight = getComputedStyle(b).minHeight;
    b.removeAttribute('role'); b.removeAttribute('aria-label'); b.className = 'Editor-x1';
}"""


class _ScriptedCua:
    """The Anthropic client agent_loop calls. A mission's FIRST turn returns its
    scripted computer actions (one turn, in order); every later turn says done.
    `missions` lists each agent_loop run by mission name."""

    def __init__(self, scripts):
        self.scripts = scripts
        self.missions = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, *, system, messages, **_kw):
        if len(messages) > 1:
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="done")])
        name = _MISSION_NAMES.get(system, "other")
        self.missions.append(name)
        acts = self.scripts.get(name, lambda: [])()
        if not acts:
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="nothing to do")])
        return SimpleNamespace(content=[
            SimpleNamespace(type="tool_use", id=f"tu_{len(self.missions)}_{i}",
                            input={"action": a, **params})
            for i, (a, params) in enumerate(acts)])


def _click_box(p1):
    return ("left_click", {"coordinate": list(p1.box)})


def _load_p1(chrome, page, p1, layout="new", **hooks):
    """The page for a Phase 1 run, composer pinned, the box's centre noted."""
    _load(chrome, page, layout, **hooks)
    chrome.run(page.add_style_tag(content=PIN_COMPOSER_CSS))
    p1.box = chrome.run(page.evaluate(BOX_CENTER_JS))


@pytest.fixture
def p1(chrome, page, fast, logs, monkeypatch):
    """run_phase1, ready to run on `page` (see the section note). `p1.run(cua)`
    returns "verified" when the gate passed, "not verified" when it returned."""
    st = SimpleNamespace(polls=[], submits=[], navigated=[], extra="", after_poll=None,
                         box=None)

    async def _yes(*_a, **_k):
        return True

    async def _nothing(*_a, **_k):
        return None

    async def _tier(*_a, **_k):
        return "already"

    async def _poll(_page, _verify, label, *_a, **_k):
        st.polls.append(label)
        if st.after_poll is not None:
            hook, st.after_poll = st.after_poll, None
            await hook()
        return True

    async def _extract(_page):
        raise _Reached()

    real_submit = research.submit_chatgpt_direct

    async def _submit(browser, prompt, **kw):
        st.submits.append((prompt, bool(kw.get("use_focused"))))
        return await real_submit(browser, prompt, **kw)

    real_wait_sent = research._chatgpt_wait_prompt_sent

    def _wait_sent(p, prompt, timeout_s=10.0):
        # The page answers in milliseconds: look for "sent" 1 s, not 10.
        return real_wait_sent(p, prompt, timeout_s=min(timeout_s, 1.0))

    for name, fn in (("_work_tab_signed_out", _nothing), ("inject_agent_observer", _yes),
                     ("check_hv_gate", _yes), ("_chatgpt_select_effort_tier", _tier),
                     ("_chatgpt_clear_deep_research", _nothing), ("poll_until_done", _poll),
                     ("extract_chatgpt_response", _extract), ("submit_chatgpt_direct", _submit),
                     ("_chatgpt_wait_prompt_sent", _wait_sent)):
        monkeypatch.setattr(research, name, fn)
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
        st.navigated.append(url)          # ⛔ never leaves the fixture page

    browser.navigate = _navigate

    def run(cua):
        try:
            out = chrome.run(research.run_phase1(browser, cua, "the St Bernard", []))
        except _Reached:
            return "verified"
        assert out is None, out
        return "not verified"

    st.run = run
    return st


def _norm_users(chrome, page):
    return [research._norm_prompt_text(u) for u in _users(chrome, page)]


def test_live_p1_a_send_that_posts_other_text_is_never_verified(chrome, page, p1, logs):
    """⛔ 09-28: other text in the thread and Stop up read as "✓ Verified". The
    gate must refuse it — through the DOM check AND its own CUA diagnosis and
    fix — and the CUA fallback, which is for a send that never happened, must
    not run after Send was pressed (the prompt would go in twice)."""
    _load_p1(chrome, page, p1, sendmangle=True, streaming=True)
    cua = _ScriptedCua({"diagnose": lambda: [_click_box(p1)],
                        "fix": lambda: [_click_box(p1)]})
    assert p1.run(cua) == "not verified", logs
    prompt = p1.submits[0][0]
    assert _users(chrome, page) == [prompt[1:]]
    assert p1.submits == [(prompt, False)]
    assert cua.missions == ["diagnose", "fix"]         # the gate's CUA steps DID run
    assert p1.polls == []
    assert any("not the prompt" in m for _lv, m in logs), logs


def test_live_p1_the_cua_places_the_caret_and_the_program_sends(chrome, page, p1, logs):
    """No marker names the box: nothing is sent, the CUA fallback runs ONCE to
    put the caret in it, and the submit then types into the focused box, reads
    it back, sends it — and the gate verifies it."""
    _load_p1(chrome, page, p1, streaming=True)
    chrome.run(page.evaluate(UNNAME_BOX_JS))
    cua = _ScriptedCua({"focus": lambda: [_click_box(p1)]})
    assert p1.run(cua) == "verified", logs
    prompt = p1.submits[0][0]
    assert p1.submits == [(prompt, False), (prompt, True)]
    assert cua.missions == ["focus"]
    assert _users(chrome, page) == [prompt]
    assert p1.polls == ["Phase1"]
    assert p1.navigated == ["https://chatgpt.com"]     # recorded, never loaded


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_p1_with_an_attached_source_is_verified(chrome, page, p1, logs, layout):
    _load_p1(chrome, page, p1, layout, attach=True, streaming=True)
    cua = _ScriptedCua({})
    assert p1.run(cua) == "verified", logs
    assert cua.missions == []
    users = _users(chrome, page)
    assert len(users) == 1 and users[0].startswith(CARD), users


def test_live_p1_a_follow_up_that_posts_other_text_is_not_verified(chrome, page, p1, logs):
    """The follow-up (context the user sent mid-brief) goes through the same
    gate with ITS text: a thread showing other text is not the follow-up
    generating, and the fallback does not run after its Send was pressed."""
    _load_p1(chrome, page, p1, streaming=True)
    p1.extra = "Add the hospice's own records."

    async def _mangle_the_next_send():
        await page.evaluate("() => { document.body.dataset.sendmangle = '1'; }")

    p1.after_poll = _mangle_the_next_send
    cua = _ScriptedCua({"diagnose": lambda: [_click_box(p1)],
                        "fix": lambda: [_click_box(p1)]})
    assert p1.run(cua) == "verified", logs              # the brief itself was
    (prompt, _f1), (followup, f2) = p1.submits
    assert f2 is False and len(p1.submits) == 2
    assert p1.polls == ["Phase1"]                       # the follow-up never was
    assert cua.missions == ["diagnose", "fix"]
    norm = research._norm_prompt_text
    assert _norm_users(chrome, page) == [norm(prompt), norm(followup)[1:]]
    assert any("Follow-up may not have triggered" in m for _lv, m in logs), logs


def test_live_p1_a_follow_up_the_box_cannot_take_gets_the_caret_from_the_cua(
        chrome, page, p1, logs):
    _load_p1(chrome, page, p1, streaming=True)
    p1.extra = "Add the hospice's own records."

    async def _unname_the_box():
        await page.evaluate(UNNAME_BOX_JS)

    p1.after_poll = _unname_the_box
    cua = _ScriptedCua({"focus": lambda: [_click_box(p1)]})
    assert p1.run(cua) == "verified", logs
    prompt, followup = p1.submits[0][0], p1.submits[1][0]
    assert p1.submits == [(prompt, False), (followup, False), (followup, True)]
    assert cua.missions == ["focus"]
    assert p1.polls == ["Phase1", "Phase1-followup"]
    norm = research._norm_prompt_text
    assert _norm_users(chrome, page) == [norm(prompt), norm(followup)]


if __name__ == "__main__":                                   # pragma: no cover
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
