"""ChatGPT Phase 1, repaired 2026-09-29 — measured in real Chrome on the rebuilt
pages (tests/fixtures/chatgpt_0928, see test_chatgpt_new_page_0928.py for how
those pages are pinned to the owner's captures).

1. A message with an ATTACHED FILE (Phase 1 with the user's sources) is sent,
   confirmed and verified. ChatGPT draws the file card inside the user message,
   above the text, so the whole message reads "St_Bernard_notes.pdf PDF Please
   create…" — and the "starts with the prompt" check refused a real send while
   ChatGPT was already writing the brief.

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


if __name__ == "__main__":                                   # pragma: no cover
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
