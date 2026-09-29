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
3. "The CUA never types" is MECHANICAL: while the program owns the typing (the
   caret placement; the gate's diagnosis and fix with a ChatGPT prompt in
   play) the CUA and the Vision act step may only click, scroll, wait and press
   Escape. On 09-28 the CUA typed "test" on its own; only mission wording
   stood in the way. Every Phase 1 run in section 2 has its CUA — and, in act
   mode, its Vision step — TRY to type a word and press Enter.

Browser tests SKIP when patchright or Chrome is missing.
"""
import asyncio
import html as _html
from types import SimpleNamespace

import pytest

import research
import test_chatgpt_new_page_0928 as base
import test_vision_act_loop as val
import vision

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
        self.told = []               # the text of every tool result the model got
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, *, system, messages, **_kw):
        if len(messages) > 1:
            for res in messages[-1]["content"]:
                self.told += [c["text"] for c in res["content"] if c.get("type") == "text"]
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


def _click_type_enter(p1, word):
    """What the 09-28 CUA did on its own: click the box, type a word, send it."""
    return [_click_box(p1), ("type", {"text": word}), ("key", {"text": "Return"})]


class _ScriptedVision:
    """vision's client in act mode (DG_VISION_TIER=tier2): each hotspot's
    proposals in order, then it hands over to the CUA. "click_box" aims at the
    box; the page is 1280 x 900, as the browser fixture opens it."""

    def __init__(self, p1, scripts):
        self.p1 = p1
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.asked = []

    async def screenshot(self, page, *, full_page=False):
        return b"img", vision.ImgMeta(width_css=1280, height_css=900, dpr=1.0, captured_at=0.0)

    async def ask(self, img, meta, ctx, *, prompt=None, high_stakes=False, transport_retry=True):
        hotspot = ctx.get("workflow_name")
        self.asked.append(hotspot)
        queue = self.scripts.get(hotspot) or []
        action, extra = queue.pop(0) if queue else ("escalate_to_cua", {})
        kw = {"action": action, "reason": "scripted", "confidence": 0.9,
              "next_expected_state": "n", "model_used": "m"}
        if action == "click_box":
            kw.update(action="click", x_ratio=self.p1.box[0] / 1280, y_ratio=self.p1.box[1] / 900)
        kw.update(extra)
        return vision.ActionResult(**kw)


def _vision_types(word):
    return [("click_box", {}), ("type", {"text": word}), ("key", {"key": "Enter"}),
            ("declare_success", {})]


def _act_mode(monkeypatch, tmp_path, vc):
    """Vision drives first (act mode), with `vc` as its client."""
    monkeypatch.setattr(research._vision, "is_vision_enabled", lambda: "tier2")
    monkeypatch.setattr(research._vision, "default_client", lambda: vc)
    monkeypatch.setattr(research._vision, "ACT_STEP_SETTLE_S", 0.0)
    monkeypatch.setenv("DG_VISION_SHADOW_LOG", str(tmp_path / "vision_shadow.jsonl"))
    monkeypatch.delenv("DG_VISION_FIXTURE_AUTO", raising=False)


def _refused(logs):
    return [m for _lv, m in logs if "REFUSED" in m]


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


@pytest.mark.parametrize("mode", ["cua", "vision-act"])
def test_live_p1_a_send_that_posts_other_text_is_never_verified(
        chrome, page, p1, logs, monkeypatch, tmp_path, mode):
    """⛔ 09-28: other text in the thread and Stop up read as "✓ Verified". The
    gate must refuse it — through the DOM check AND its own CUA diagnosis and
    fix — and the CUA fallback, which is for a send that never happened, must
    not run after Send was pressed (the prompt would go in twice). The
    diagnosis and the fix both TRY to type a word and send it; neither may."""
    _load_p1(chrome, page, p1, sendmangle=True, streaming=True)
    if mode == "vision-act":
        vc = _ScriptedVision(p1, {"poll-fix": _vision_types("visionfix")})
        _act_mode(monkeypatch, tmp_path, vc)
    cua = _ScriptedCua({"diagnose": lambda: _click_type_enter(p1, "diagword"),
                        "fix": lambda: _click_type_enter(p1, "fixword")})
    assert p1.run(cua) == "not verified", logs
    prompt = p1.submits[0][0]
    assert _users(chrome, page) == [prompt[1:]]        # nothing else was ever sent
    assert p1.submits == [(prompt, False)]
    assert cua.missions == ["diagnose", "fix"]         # the gate's CUA steps DID run
    assert p1.polls == []
    assert any("not the prompt" in m for _lv, m in logs), logs
    # The diagnosis only looks: its click, word and Enter; the fix's word and Enter.
    assert len(_refused(logs)) == 5, _refused(logs)
    if mode == "vision-act":
        assert "poll-fix" in vc.asked
        assert any("refused type" in m for _lv, m in logs), logs


@pytest.mark.parametrize("mode", ["cua", "vision-act"])
def test_live_p1_the_cua_places_the_caret_and_the_program_sends(
        chrome, page, p1, logs, monkeypatch, tmp_path, mode):
    """No marker names the box: nothing is sent, the CUA fallback runs ONCE to
    put the caret in it, and the submit then types into the focused box, reads
    it back, sends it — and the gate verifies it. The fallback (and, in act
    mode, Vision before it) TRIES to type a test word and send it, as the
    09-28 CUA did; only the prompt may reach the thread."""
    _load_p1(chrome, page, p1, streaming=True)
    chrome.run(page.evaluate(UNNAME_BOX_JS))
    if mode == "vision-act":
        vc = _ScriptedVision(p1, {"1a-submit": _vision_types("visiontest")})
        _act_mode(monkeypatch, tmp_path, vc)
    cua = _ScriptedCua({"focus": lambda: _click_type_enter(p1, "test")})
    assert p1.run(cua) == "verified", logs
    prompt = p1.submits[0][0]
    assert _users(chrome, page) == [prompt]
    assert p1.submits == [(prompt, False), (prompt, True)]
    assert cua.missions == ["focus"]
    assert p1.polls == ["Phase1"]
    assert p1.navigated == ["https://chatgpt.com"]     # recorded, never loaded
    assert len(_refused(logs)) == 2, _refused(logs)
    assert any("was NOT carried out" in t for t in cua.told), cua.told
    if mode == "vision-act":
        assert vc.asked[0] == "1a-submit"


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
    cua = _ScriptedCua({"diagnose": lambda: _click_type_enter(p1, "fudiag"),
                        "fix": lambda: _click_type_enter(p1, "fufix")})
    assert p1.run(cua) == "verified", logs              # the brief itself was
    (prompt, _f1), (followup, f2) = p1.submits
    assert f2 is False and len(p1.submits) == 2
    assert p1.polls == ["Phase1"]                       # the follow-up never was
    assert cua.missions == ["diagnose", "fix"]
    norm = research._norm_prompt_text
    assert _norm_users(chrome, page) == [norm(prompt), norm(followup)[1:]]
    assert any("Follow-up may not have triggered" in m for _lv, m in logs), logs
    # The diagnosis only looks: its click, word and Enter; the fix's word and Enter.
    assert len(_refused(logs)) == 5, _refused(logs)


@pytest.mark.parametrize("mode", ["cua", "vision-act"])
def test_live_p1_a_follow_up_the_box_cannot_take_gets_the_caret_from_the_cua(
        chrome, page, p1, logs, monkeypatch, tmp_path, mode):
    _load_p1(chrome, page, p1, streaming=True)
    p1.extra = "Add the hospice's own records."

    async def _unname_the_box():
        await page.evaluate(UNNAME_BOX_JS)

    p1.after_poll = _unname_the_box
    if mode == "vision-act":
        vc = _ScriptedVision(p1, {"1a-submit": _vision_types("visionfu")})
        _act_mode(monkeypatch, tmp_path, vc)
    cua = _ScriptedCua({"focus": lambda: _click_type_enter(p1, "futest")})
    assert p1.run(cua) == "verified", logs
    prompt, followup = p1.submits[0][0], p1.submits[1][0]
    norm = research._norm_prompt_text
    assert _norm_users(chrome, page) == [norm(prompt), norm(followup)]
    assert p1.submits == [(prompt, False), (followup, False), (followup, True)]
    assert cua.missions == ["focus"]
    assert p1.polls == ["Phase1", "Phase1-followup"]
    assert len(_refused(logs)) == 2, _refused(logs)
    if mode == "vision-act":
        assert vc.asked[0] == "1a-submit"


# ═══ 3. "Never types" is mechanical ════════════════════════════════════════

@pytest.mark.parametrize("action,params", [
    ("left_click", {"coordinate": [1, 2]}), ("mouse_move", {"coordinate": [1, 2]}),
    ("scroll", {"direction": "down"}), ("wait", {"duration": 1}),
    ("key", {"text": "Escape"}), ("key", {"key": "esc"}), ("key", {"text": "escape"}),
])
def test_the_click_only_list_lets_a_cua_point_click_scroll_wait_and_escape(action, params):
    assert research._cua_refusal(action, params, research.CUA_CLICK_ONLY) == ""


@pytest.mark.parametrize("action,params", [
    ("type", {"text": "test"}), ("key", {"text": "Return"}), ("key", {"key": "Enter"}),
    ("key", {"text": "ctrl+v"}), ("key", {"text": "ctrl+a"}), ("key", {"text": "Delete"}),
    ("key", {"text": "Escape+Return"}), ("key", {"text": ""}),
    ("double_click", {"coordinate": [1, 2]}), ("triple_click", {"coordinate": [1, 2]}),
    ("right_click", {"coordinate": [1, 2]}), ("middle_click", {"coordinate": [1, 2]}),
    ("left_click_drag", {}),
])
def test_the_click_only_list_refuses_typing_keys_and_the_rest(action, params):
    assert research._cua_refusal(action, params, research.CUA_CLICK_ONLY) != ""
    assert research._cua_refusal(action, params, None) == ""        # no list: anything


def test_a_vision_step_is_judged_by_the_same_list():
    f = research._vision_refusal
    allow = research.CUA_CLICK_ONLY

    def r(action, **kw):
        return vision.ActionResult(action=action, reason="", confidence=0.9,
                                   next_expected_state="", **kw)

    assert f(r("click", x_ratio=0.5, y_ratio=0.5), allow) == ""
    assert f(r("scroll", scroll_dy_ratio=0.5), allow) == ""
    assert f(r("wait", duration_ms=100), allow) == ""
    assert f(r("key", key="Escape"), allow) == ""
    assert f(r("type", text="test"), allow) == "type"
    assert f(r("key", key="Enter"), allow) == "key 'Enter'"


def _run_executor(chrome, page, logs, allow):
    """The REAL agent_loop / execute_action on the page, with the model menu
    open: the scripted model presses Escape, clicks the box, types "test",
    presses Return and ctrl+v, and double-clicks."""
    _load(chrome, page, "new")
    chrome.run(page.add_style_tag(content=PIN_COMPOSER_CSS))
    box = chrome.run(page.evaluate(BOX_CENTER_JS))
    chrome.run(page.click('button[aria-label="Select ChatGPT model"]'))
    browser = research.Browser.__new__(research.Browser)
    browser.page = page
    cua = _ScriptedCua({"other": lambda: [
        ("key", {"text": "Escape"}), ("left_click", {"coordinate": box}),
        ("type", {"text": "test"}), ("key", {"text": "Return"}), ("key", {"text": "ctrl+v"}),
        ("double_click", {"coordinate": box})]})
    out = chrome.run(research.agent_loop(cua, browser, "a mission", "go", max_iterations=3,
                                         allow=allow))
    assert out["status"] == "done", out
    return cua


def test_live_the_cua_executor_refuses_what_the_list_does_not_allow(chrome, page, fast, logs):
    cua = _run_executor(chrome, page, logs, research.CUA_CLICK_ONLY)
    # What IS allowed still happens: Escape closed the menu, the click focused the box.
    assert chrome.run(page.evaluate("() => document.body.dataset.menuClosedBy")) == "escape"
    assert chrome.run(page.evaluate(
        "() => document.activeElement.getAttribute('aria-label')")) == "Ask ChatGPT"
    # Nothing was typed, nothing was sent.
    assert chrome.run(page.evaluate(base.BOX_JS)) == ""
    assert _users(chrome, page) == []
    refused = _refused(logs)
    assert len(refused) == 4, refused
    assert "type" in refused[0] and "'Enter'" in refused[1] and "double_click" in refused[3]
    # And the model was told, action by action.
    assert sum("was NOT carried out" in t for t in cua.told) == 4, cua.told


def test_live_without_a_list_the_same_moves_type_and_send(chrome, page, fast, logs):
    """The control: the executor DOES type and send — so the test above
    measures the list, not a script that could not have typed anyway."""
    _run_executor(chrome, page, logs, None)
    assert _users(chrome, page) == ["test"]
    assert _refused(logs) == []


def test_a_vision_act_step_outside_the_list_is_not_executed(monkeypatch, tmp_path):
    monkeypatch.setenv("DG_VISION_SHADOW_LOG", str(tmp_path / "vs.jsonl"))
    monkeypatch.setattr(vision, "ACT_STEP_SETTLE_S", 0.0)

    def run(refuse):
        pg = val._FakePage()
        vc = val._FakeVC([val._res("click", x=0.5, y=0.25), val._res("type", text="test"),
                          val._res("key", key="Enter"), val._res("declare_success")])
        out = asyncio.run(vision.act_loop(
            pg, vision=vc, flow_context={"phase": 1, "platform": "chatgpt"},
            hotspot_id="1a-submit", refuse=refuse))
        return out, pg.interactions

    out, done = run(lambda r: research._vision_refusal(r, research.CUA_CLICK_ONLY))
    assert done == [("click", 500.0, 200.0)]
    assert out.action == "escalate_to_cua" and "refused type" in out.reason
    out, done = run(None)                                  # the control
    assert done == [("click", 500.0, 200.0), ("type", "test"), ("press", "Enter")]
    assert out.action == "declare_success"


def test_other_platforms_keep_an_unrestricted_diagnosis_and_fix(monkeypatch):
    """Only a ChatGPT prompt in play holds the gate's CUA to the list: another
    platform's fix may still, say, press Enter on a prompt the program typed."""
    seen = []

    async def _agent_loop(client, browser, system_prompt, user_message, **kw):
        seen.append((_MISSION_NAMES.get(system_prompt), kw.get("allow")))
        return {"status": "done", "text": "nothing"}

    async def _no(*_a, **_k):
        return False

    async def _noop(*_a, **_k):
        return None

    async def _guard(*_a, **_k):
        return True

    monkeypatch.setattr(research, "asyncio", base._FastAsyncio())
    monkeypatch.setattr(research, "agent_loop", _agent_loop)
    monkeypatch.setattr(research, "_chatgpt_guard_box_before_fix", _guard)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    if research._vision is not None:
        monkeypatch.setattr(research._vision, "is_vision_enabled", lambda: "off")
    pg = SimpleNamespace(evaluate=_noop)
    browser = SimpleNamespace(switch_to_page=_noop)
    for prompt in (None, PROMPT):
        asyncio.run(research.wait_until_verified(
            _no, pg, "2B", browser=browser, cua_client=object(), max_retries=8, interval=0,
            chatgpt_prompt=prompt))
    assert seen == [("diagnose", None), ("fix", None),
                    ("diagnose", research.CUA_LOOK_ONLY), ("fix", research.CUA_CLICK_ONLY)]


if __name__ == "__main__":                                   # pragma: no cover
    import sys
    sys.exit(pytest.main([__file__, "-q"]))


# ═══ 4. No click sends (09-29 verify) ════════════════════════════════════════
#
# The allow-list kept a single click, and one click on Send sends whatever the
# box holds. Four ways that could happen, each driven through run_phase1: the
# caret CUA clicking Send over a leftover draft, the caret CUA run over text the
# program could not clear, the look-only diagnosis clicking Send, and — the
# belt — a step the guards do not see (a Vision click) sending anyway.

SEND_CENTER_JS = """() => {
    const b = document.querySelector('button[aria-label="Send"]');
    const r = b.getBoundingClientRect();
    return [Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2)];
}"""

#: The box will not empty with select-all + Delete (a page that swallows them).
BLOCK_CLEAR_JS = """() => {
    document.querySelector('.ProseMirror').addEventListener('keydown', (e) => {
        if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault(); e.stopImmediatePropagation(); }
    }, true);
}"""


def _leftover_draft(chrome, page, p1, *, unname=False, stuck=False):
    """The 09-28 leftover: "est" in the box. Returns Send's centre."""
    _load_p1(chrome, page, p1, streaming=True)
    chrome.run(page.click('.ProseMirror'))
    chrome.run(page.keyboard.insert_text("est"))
    if stuck:
        chrome.run(page.evaluate(BLOCK_CLEAR_JS))
    if unname:
        chrome.run(page.evaluate(UNNAME_BOX_JS))
    return chrome.run(page.evaluate(SEND_CENTER_JS))


def test_live_p1_the_caret_cua_cannot_click_send(chrome, page, p1, logs):
    """No marker names the box and it holds a leftover draft; the caret CUA
    clicks the box, then Send. The click on Send is refused, the program
    clears the box, types, reads back and sends: only the prompt is sent."""
    send = _leftover_draft(chrome, page, p1, unname=True)
    cua = _ScriptedCua({"focus": lambda: [_click_box(p1), ("left_click", {"coordinate": send})]})
    assert p1.run(cua) == "verified", logs
    prompt = p1.submits[0][0]
    assert _users(chrome, page) == [prompt]
    assert [m for m in _refused(logs) if "click on Send" in m], _refused(logs)
    assert any("would have clicked Send" in t for t in cua.told), cua.told


def test_live_p1_text_the_box_would_not_give_up_is_never_handed_to_a_cua(chrome, page, p1, logs):
    """The box holds text that will not clear: the program types nothing and
    sends nothing — and no CUA gets the page, because one allowed click on Send
    would send that text. The caret CUA would click Send; it never runs."""
    send = _leftover_draft(chrome, page, p1, stuck=True)
    cua = _ScriptedCua({"focus": lambda: [("left_click", {"coordinate": send})]})
    assert p1.run(cua) == "not verified", logs
    assert _users(chrome, page) == []
    assert "focus" not in cua.missions, cua.missions
    assert len(p1.submits) == 1, p1.submits


def test_live_p1_the_diagnosis_only_looks(chrome, page, p1, logs):
    """The gate's diagnosis runs before the box guard; with a ChatGPT prompt in
    play it may not click at all — a click on Send there sent the leftover."""
    send = _leftover_draft(chrome, page, p1, stuck=True)
    cua = _ScriptedCua({"diagnose": lambda: [("left_click", {"coordinate": send})]})
    assert p1.run(cua) == "not verified", logs
    assert "diagnose" in cua.missions, cua.missions
    assert _users(chrome, page) == []
    assert [m for m in _refused(logs) if "left_click" in m], _refused(logs)


def test_live_p1_a_message_sent_during_the_caret_step_stops_the_prompt(
        chrome, page, p1, logs, monkeypatch, tmp_path):
    """⛔ THE BELT. A step the guards do not see — here Vision, in act mode,
    clicking Send over the leftover — sends it. The program sees a message it
    did not send appear during the caret step and does NOT type the prompt."""
    send = _leftover_draft(chrome, page, p1, unname=True)
    vc = _ScriptedVision(p1, {"1a-submit": [
        ("click", {"x_ratio": send[0] / 1280, "y_ratio": send[1] / 900}),
        ("declare_success", {})]})
    _act_mode(monkeypatch, tmp_path, vc)
    cua = _ScriptedCua({})
    assert p1.run(cua) == "not verified", logs
    assert _users(chrome, page) == ["est"]              # Vision's send, and nothing after it
    prompt = p1.submits[0][0]
    assert p1.submits == [(prompt, False)], p1.submits   # no second submit
    assert any(lv == "ERROR" and "while the CUA was only placing the caret" in m
               for lv, m in logs), logs


def test_live_p1_a_message_sent_during_the_follow_ups_caret_step_stops_the_follow_up(
        chrome, page, p1, logs, monkeypatch, tmp_path):
    """The belt on the follow-up: after the brief, the box loses its name and
    holds a leftover; Vision's caret step clicks Send over it. The follow-up
    is not typed after a message the program did not send."""
    _load_p1(chrome, page, p1, streaming=True)
    chrome.run(page.click('.ProseMirror'))
    chrome.run(page.keyboard.insert_text("x"))
    send = chrome.run(page.evaluate(SEND_CENTER_JS))    # where Send sits once the box has text
    chrome.run(page.keyboard.press("Backspace"))
    p1.extra = "Add the hospice's own records."

    async def _leftover_in_an_unnamed_box():
        await page.evaluate(UNNAME_BOX_JS)
        await page.focus('[contenteditable="true"]')
        await page.keyboard.insert_text("est")

    p1.after_poll = _leftover_in_an_unnamed_box
    vc = _ScriptedVision(p1, {"1a-submit": [
        ("click", {"x_ratio": send[0] / 1280, "y_ratio": send[1] / 900}),
        ("declare_success", {})]})
    _act_mode(monkeypatch, tmp_path, vc)
    assert p1.run(_ScriptedCua({})) == "verified", logs     # the brief itself was
    prompt, followup = p1.submits[0][0], p1.submits[1][0]
    assert _norm_users(chrome, page) == [research._norm_prompt_text(prompt), "est"]
    assert p1.submits == [(prompt, False), (followup, False)], p1.submits
    assert any(lv == "ERROR" and m.startswith("[p1:followup]")
               and "while the CUA was only placing the caret" in m for lv, m in logs), logs
