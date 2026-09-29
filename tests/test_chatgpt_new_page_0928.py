"""ChatGPT's new page, 2026-09-28 — every ChatGPT step, measured in real Chrome.

⛔⛔ THE DEFECT. ChatGPT changed its markup while the page LOOKED the same. The
message box lost `#prompt-textarea`, the messages lost `data-message-author-role`,
Send and Stop lost their `data-testid`. The run that morning (fix14/run_bad_0928.log):

  20:33:25  Direct submit: no textarea found
            → the CUA fallback typed "test" into a box it could not see, pressed
              ctrl+a (on macOS: go to LINE START) and Delete → "est"
  20:35:03  [Phase1] CUA attempting to fix … clicks Send on "est"
  20:35:13  [Phase1] ✓ Verified — actively generating      (the Stop button alone)
  20:35:43  panel census: "no user message on screen"       ("You said: est" visible)

── What is measured here ─────────────────────────────────────────────────────

Nobody may open chatgpt.com, so the strongest measurement available is the
owner's own captures of the live page (tests/fixtures/chatgpt_0928/*.json) rebuilt
as HTML (new_page.html) and driven in REAL Chrome through the project's own
patchright — running research.py's actual page JS and actual submit code. The
old page (old_page.html) runs through the same tests to prove it still works.

The first block checks the FIXTURE against the captures, attribute by attribute:
a fixture that drifted from the capture would make every test below measure a
page that does not exist.

Browser tests SKIP when patchright or Chrome is missing; the pure pieces (key
mapping, prompt matching, the verify gate, the splice) run everywhere.
"""
import ast
import asyncio
import html as _html
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import research

from _domshim import js_constant

FIX = Path(__file__).parent / "fixtures" / "chatgpt_0928"
PROMPT = ("Please create a detailed research report brief for a deep research LLM "
          "agent that covers this topic: the St Bernard. Be as thorough as you can.")
HEADING = "Research brief: the St Bernard"
LINK = "https://example.org/st-bernard-breed-standard"
LAYOUTS = ("new", "old")
NEW_BOX = 'div.ProseMirror[contenteditable="true"][role="textbox"]'
USERS_JS = ("() => [...document.querySelectorAll("
            "'[data-user-message-bubble=\"true\"], [data-message-author-role=\"user\"]')]"
            ".map(e => (e.innerText || '').trim())")
BOX_JS = ("() => { const b = document.querySelector("
          "'.ProseMirror[contenteditable=\"true\"], [contenteditable=\"true\"]');"
          " return b ? (b.innerText || '').trim() : null; }")


def _html_for(layout, *, thread=False, prompt=PROMPT):
    src = (FIX / f"{layout}_page.html").read_text(encoding="utf-8")
    body = '<body data-sr-fixture="chat" data-sr-prompt="">'
    assert src.count(body) == 1, "the fixture's <body> contract changed"
    return src.replace(body, (f'<body data-sr-fixture="{"thread" if thread else "chat"}" '
                              f'data-sr-prompt="{_html.escape(prompt, quote=True)}">'))


class _FastAsyncio:
    """research's `asyncio`, with every sleep capped — the submit's settle
    waits are real-page timings, and the fixture reacts in milliseconds."""

    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(delay=0, *a, **k):
        await asyncio.sleep(min(float(delay or 0), 0.05))


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    # raising=False: run against the pre-fix module too, so a test there fails
    # on BEHAVIOUR rather than on a missing name.
    monkeypatch.setattr(research, "_CHATGPT_COMPOSER_WAIT_S", 1.5, raising=False)


@pytest.fixture
def logs(monkeypatch):
    lines = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO": lines.append((level, str(msg))))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    return lines


@pytest.fixture(scope="module")
def chrome():
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
        return pw, b, await b.new_context(viewport={"width": 1280, "height": 900})

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


def _load(chrome, page, layout, **kw):
    chrome.run(page.set_content(_html_for(layout, **kw)))


def _browser(page):
    return SimpleNamespace(page=page)


# ═══ 0. The fixture IS the captured page ═════════════════════════════════════

def _cap(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


_NODE_JS = """(el) => {
    const walk = (n) => ({ tag: n.tagName, attrs: Object.fromEntries(
        [...n.attributes].map(a => [a.name, a.value])),
        kids: [...n.children].map(walk) });
    const up = []; let a = el;
    while (a && a.tagName !== 'MAIN') { up.push({ tag: a.tagName, attrs: Object.fromEntries(
        [...a.attributes].map(x => [x.name, x.value])) }); a = a.parentElement; }
    return { tree: walk(el), ancestors: up };
}"""


def _same_attrs(cap_attrs, got_attrs, where):
    for k, v in cap_attrs.items():
        assert k in got_attrs, f"{where}: attribute {k} missing"
        if v.startswith("<") and v.endswith(" chars>"):
            assert len(got_attrs[k]) == int(v[1:].split()[0]), f"{where}: {k} length"
        elif k == "class":
            # The capture cuts class values at ~100 characters; the fixture
            # carries the cut value (or, where another capture was longer, that).
            assert got_attrs[k].startswith(v), f"{where}: class {got_attrs[k]!r} vs {v!r}"
        else:
            assert got_attrs[k] == v, f"{where}: {k}={got_attrs[k]!r}, captured {v!r}"


def _same_tree(cap, got, where):
    assert got["tag"].upper() == cap["tag"].upper(), f"{where}: tag {got['tag']} vs {cap['tag']}"
    _same_attrs(cap.get("attrs") or {}, got["attrs"], where)
    ckids = [k for k in (cap.get("kids") or []) if k.get("tag") != "svg"]
    gkids = [k for k in got["kids"] if k["tag"].upper() != "SVG"]
    if (cap.get("attrs") or {}).get("data-markdown-text-style"):
        # The reply's own text: the captured paragraph must be there; the
        # heading/link paragraphs the readers need are extra (not captured).
        for ck in ckids:
            assert any(g["tag"] == ck["tag"] and all(g["attrs"].get(k) == v
                       for k, v in (ck.get("attrs") or {}).items()) for g in gkids), where
        return
    assert len(gkids) == len(ckids), f"{where}: {len(gkids)} children, captured {len(ckids)}"
    for i, (ck, gk) in enumerate(zip(ckids, gkids)):
        _same_tree(ck, gk, f"{where}/{ck['tag']}[{i}]")


def test_live_the_new_fixture_reproduces_the_captured_blocks(chrome, page):
    """Both blocks of chatgpt-reply-capture2.json, tag / attribute / class /
    nesting, and every ancestor above them up to the capture's depth."""
    _load(chrome, page, "new", thread=True)
    cap = _cap("chatgpt-reply-capture2.json")
    bubble = chrome.run(page.query_selector("[data-user-message-bubble]"))
    got_user = chrome.run(bubble.evaluate(
        "(b) => (" + _NODE_JS + ")(b.closest('.block-BQZwFn'))"))
    unit = chrome.run(page.query_selector('[data-chatgpt-search-unit-key$=":assistant"]'))
    got_asst = chrome.run(unit.evaluate(_NODE_JS))
    for blk, got in ((cap["blocks"][0], got_user), (cap["blocks"][1], got_asst)):
        _same_tree(blk["block"], got["tree"], blk["label"])
        for i, ca in enumerate(blk["ancestors"]):
            assert i < len(got["ancestors"]), f"{blk['label']}: ancestor {i} missing"
            assert got["ancestors"][i]["tag"] == ca["tag"]
            _same_attrs(ca["attrs"], got["ancestors"][i]["attrs"], f"{blk['label']} ancestor {i}")


def test_live_the_new_fixture_reproduces_the_composer_and_the_buttons(chrome, page):
    """The box, the model button and its menu (chatgpt-composer-capture), and
    the Start Voice / Send / Stop button (chatgpt-thread-capture)."""
    _load(chrome, page, "new")
    frames = {f["ms"]: f for f in _cap("chatgpt-composer-capture-trimmed.json")["frames"]}
    box = frames[2]["composers"][0]
    got = chrome.run(page.evaluate("""() => {
        const b = document.querySelector('[contenteditable="true"]');
        return { tag: b.tagName, id: b.id || null, role: b.getAttribute('role'),
                 cls: b.className, aria: b.getAttribute('aria-label'),
                 placeholder: b.getAttribute('placeholder'),
                 dataPlaceholder: b.getAttribute('data-placeholder'),
                 ce: b.getAttribute('contenteditable'), inForm: !!b.closest('form') };
    }"""))
    assert (got["tag"], got["id"], got["role"], got["cls"], got["aria"]) == (
        box["tag"], box["id"], box["role"], box["cls"], box["aria"])
    assert got["placeholder"] is None and got["dataPlaceholder"] is None
    assert got["ce"] == box["contenteditable"] and got["inForm"] is box["inForm"]
    trig = frames[2]["pill"][0]
    got_t = chrome.run(page.evaluate(
        "() => { const b = document.querySelector('button[aria-label=\"Select ChatGPT model\"]');"
        " return { id: b.id, cls: b.className, hp: b.getAttribute('aria-haspopup') }; }"))
    assert got_t["id"] == trig["id"] and got_t["hp"] == "menu"
    assert got_t["cls"].startswith(trig["cls"])
    # Open the menu, as the tier step does: the captured menu, rows and thumb.
    chrome.run(page.click('button[aria-label="Select ChatGPT model"]'))
    menu = [o for o in frames[3971]["open"] if o.get("role") == "menu"][0]
    thumb = frames[10732]["sliders"][0]
    got_m = chrome.run(page.evaluate("""() => {
        const m = document.querySelector('[role="menu"]');
        const s = document.querySelector('[role="slider"]');
        return { mid: m.id, mcls: m.className, active: document.activeElement.getAttribute('role'),
                 rows: [...m.querySelectorAll('[role="menuitem"]')].map(r => r.getAttribute('aria-label')),
                 scls: s.className, stag: s.tagName, hidden: !!s.closest('[aria-hidden="true"]'),
                 smax: s.getAttribute('aria-valuemax'), smin: s.getAttribute('aria-valuemin') };
    }"""))
    assert got_m["mid"] == menu["id"] and got_m["mcls"] == menu["cls"]
    assert got_m["active"] == frames[3971]["active"]["role"] == "menu"
    assert got_m["rows"] == ["Select model", "Power"]
    assert (got_m["stag"], got_m["scls"]) == (thumb["tag"], thumb["cls"])
    assert got_m["hidden"] is thumb["box"]["ariaHiddenAncestor"] is True
    assert (got_m["smin"], got_m["smax"]) == (thumb["min"], thumb["max"])
    # Escape: the menu closes and focus lands on the MODEL BUTTON (14693) — not
    # the box, which the capture shows is focused only by clicking it (137689).
    chrome.run(page.keyboard.press("Escape"))
    after = frames[14693]["active"]
    got_a = chrome.run(page.evaluate(
        "() => ({ tag: document.activeElement.tagName,"
        " aria: document.activeElement.getAttribute('aria-label'),"
        " menus: document.querySelectorAll('[role=\"menu\"]').length })"))
    assert (got_a["tag"], got_a["aria"]) == (after["tag"], after["aria"])
    assert got_a["menus"] == 0
    # The action button: Start Voice empty, Send (type=submit) with text.
    thread = _cap("chatgpt-thread-capture.json")["frames"]
    send = [b for b in thread[0]["buttons"] if b["attrs"].get("aria-label") == "Send"][0]
    voice = [b for b in thread[1]["buttons"] if b["attrs"].get("aria-label") == "Start Voice"][0]
    stop = [b for b in thread[3]["buttons"] if b["attrs"].get("aria-label") == "Stop"][0]
    act = "() => { const b = document.querySelector('#sr-action button'); return Object.fromEntries([...b.attributes].map(a => [a.name, a.value])); }"
    _same_attrs(voice["attrs"], chrome.run(page.evaluate(act)), "Start Voice")
    chrome.run(page.click(NEW_BOX))
    chrome.run(page.keyboard.insert_text("hello"))
    _same_attrs(send["attrs"], chrome.run(page.evaluate(act)), "Send")
    chrome.run(page.keyboard.press("Enter"))
    _same_attrs(stop["attrs"], chrome.run(page.evaluate(act)), "Stop")


# ═══ 1. The submit: found, focused, typed, READ BACK, sent, confirmed ════════

@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_prompt_is_typed_read_back_and_sent(chrome, page, fast, logs, layout):
    """⛔ On the new page this is the step that said "no textarea found"."""
    _load(chrome, page, layout)
    if layout == "new":
        # The tier step leaves the model menu open behind it.
        chrome.run(page.click('button[aria-label="Select ChatGPT model"]'))
        assert chrome.run(page.evaluate("() => document.querySelectorAll('[role=\"menu\"]').length")) == 1
    ok = chrome.run(research.submit_chatgpt_direct(_browser(page), PROMPT))
    assert ok is True, logs
    assert chrome.run(page.evaluate(USERS_JS)) == [PROMPT]
    assert chrome.run(page.evaluate(BOX_JS)) == ""
    # Sent with ChatGPT's own Send button (either page's), not the Enter fallback.
    assert chrome.run(page.evaluate("() => document.body.dataset.sentVia")) == "button"
    assert chrome.run(page.evaluate("() => document.querySelectorAll('[role=\"menu\"]').length")) == 0
    if layout == "new":
        # Closed by the submit's own bounded Escape — not left for the box
        # click to dismiss by accident.
        assert chrome.run(page.evaluate("() => document.body.dataset.menuClosedBy")) == "escape"


def test_live_a_send_that_posts_other_text_is_not_counted_as_sent(chrome, page, fast, logs):
    """The page shows something else after Send: not "sent" — and the outcome
    says Send WAS pressed, so no fallback types the prompt a second time."""
    _load(chrome, page, "new")
    chrome.run(page.evaluate("() => { document.body.dataset.sendmangle = '1'; }"))
    out = {}
    ok = chrome.run(research.submit_chatgpt_direct(_browser(page), PROMPT, outcome=out))
    assert ok is False and out["state"] == "sent_unconfirmed"
    assert chrome.run(page.evaluate(USERS_JS)) == [PROMPT[1:]]
    assert any("not counting it as sent" in m for _lv, m in logs), logs


def test_live_after_the_menu_closes_the_box_is_found_and_focused_by_a_click(chrome, page, fast, logs):
    """The capture: Escape leaves focus on the model button. The submit's own
    lookup and click must put the caret in the box, and what it types must
    read back exactly."""
    _load(chrome, page, "new")
    chrome.run(page.click('button[aria-label="Select ChatGPT model"]'))
    chrome.run(page.keyboard.press("Escape"))
    assert chrome.run(page.evaluate("() => document.activeElement.getAttribute('aria-label')")) \
        == "Select ChatGPT model"
    box = chrome.run(research._chatgpt_find_composer(page))
    assert box is not None
    assert chrome.run(research._chatgpt_type_prompt_verified(page, box, PROMPT)) is True
    assert chrome.run(page.evaluate(
        "() => document.activeElement.getAttribute('aria-label')")) == "Ask ChatGPT"
    assert chrome.run(page.evaluate(BOX_JS)) == PROMPT


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_a_lossy_read_back_is_cleared_and_retyped(chrome, page, fast, logs, layout):
    """The first insert loses its first character (the test hook) — "est".
    It is caught BEFORE Send, cleared, retyped, and the exact prompt goes."""
    _load(chrome, page, layout)
    chrome.run(page.evaluate("() => { document.body.dataset.mangle = '1'; }"))
    ok = chrome.run(research.submit_chatgpt_direct(_browser(page), PROMPT))
    assert ok is True
    assert chrome.run(page.evaluate(USERS_JS)) == [PROMPT]
    assert any("read-back mismatch (try 1/2)" in m for _lv, m in logs), logs


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_a_box_that_never_holds_the_prompt_sends_nothing(chrome, page, fast, logs, layout):
    _load(chrome, page, layout)
    chrome.run(page.evaluate("() => { document.body.dataset.mangle = '99'; }"))
    out = {}
    ok = chrome.run(research.submit_chatgpt_direct(_browser(page), PROMPT, outcome=out))
    assert ok is False and out["state"] == "not_sent"
    assert chrome.run(page.evaluate(USERS_JS)) == []
    assert chrome.run(page.evaluate(BOX_JS)) == ""
    assert any("NOT sending anything" in m for _lv, m in logs), logs
    # And the diagnostic line names the box and the focus.
    assert any("box=DIV[" in m and "focus=" in m for _lv, m in logs), logs


def test_live_no_box_is_a_one_line_diagnosis_not_a_send(chrome, page, fast, logs):
    _load(chrome, page, "new")
    chrome.run(page.evaluate("() => document.querySelector('.ProseMirror').remove()"))
    out = {}
    assert chrome.run(research.submit_chatgpt_direct(_browser(page), PROMPT, outcome=out)) is False
    assert out["state"] == "not_sent"
    diag = [m for _lv, m in logs if "no message box found —" in m and "box=none" in m]
    assert diag and "editables=0" in diag[0], logs


def test_live_the_caret_a_cua_click_placed_is_used_when_no_marker_names_the_box(
        chrome, page, fast, logs):
    """The CUA fallback only puts the caret in the box; the program types,
    reads back and sends. A box no marker can name (a future rename) is found
    through focus — and ONLY when the caller says a click put the caret there."""
    _load(chrome, page, "new")
    chrome.run(page.evaluate("""() => {
        const b = document.querySelector('.ProseMirror');
        b.removeAttribute('role'); b.removeAttribute('aria-label'); b.className = 'Editor-x1';
    }"""))
    out = {}
    assert chrome.run(research.submit_chatgpt_direct(_browser(page), PROMPT, outcome=out)) is False
    assert out["state"] == "not_sent"
    chrome.run(page.click(".Editor-x1"))            # what the CUA's click does
    assert chrome.run(research.submit_chatgpt_direct(_browser(page), PROMPT,
                                                     use_focused=True, outcome=out)) is True
    assert out["state"] == "sent"
    assert chrome.run(page.evaluate(USERS_JS)) == [PROMPT]


def test_live_ctrl_a_from_the_cua_empties_the_box_on_this_machine(chrome, page):
    """⛔ The "est" keystroke, reproduced: "test", ctrl+a, Delete. On macOS
    Control+A is MoveToBeginningOfLine, so without the mapping this leaves
    "est" — exactly what the run sent."""
    _load(chrome, page, "new")
    chrome.run(page.click(NEW_BOX))
    chrome.run(page.keyboard.insert_text("test"))
    b = _browser(page)
    chrome.run(research.Browser.key(b, "ctrl+a"))
    chrome.run(research.Browser.key(b, "Delete"))
    assert chrome.run(page.evaluate(BOX_JS)) == ""


# ═══ 2. Sent means OUR prompt, on the DOM path and the CUA paths ═════════════

@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_verifier_refuses_est_even_with_stop_showing(chrome, page, logs, layout):
    _load(chrome, page, layout, thread=True, prompt="est")
    # The Stop button alone still says "generating" — that is what accepted it.
    assert chrome.run(research.verify_chatgpt_generating(page)) is True
    v = research._chatgpt_sent_prompt_verifier(PROMPT, "Phase1")
    assert chrome.run(v(page)) is False
    assert any("not the prompt" in m for _lv, m in logs)
    _load(chrome, page, layout, thread=True)
    assert chrome.run(v(page)) is True


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_box_is_cleared_of_anything_but_the_prompt_before_a_cua_fix(
        chrome, page, fast, logs, layout):
    _load(chrome, page, layout)
    box = 'div.ProseMirror[contenteditable="true"]'
    chrome.run(page.click(box))
    chrome.run(page.keyboard.insert_text("est"))
    assert chrome.run(research._chatgpt_guard_box_before_fix(page, PROMPT, "Phase1")) is True
    assert chrome.run(page.evaluate(BOX_JS)) == ""
    chrome.run(page.keyboard.insert_text(PROMPT))
    assert chrome.run(research._chatgpt_guard_box_before_fix(page, PROMPT, "Phase1")) is True
    assert chrome.run(page.evaluate(BOX_JS)) == PROMPT          # the prompt is left alone
    chrome.run(page.evaluate("() => document.querySelector('.ProseMirror').remove()"))
    assert chrome.run(research._chatgpt_guard_box_before_fix(page, PROMPT, "Phase1")) is False


# ═══ 3. The readers: user message, reply text / links / headings, Stop ══════

@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_census_sees_the_user_message(chrome, page, logs, layout):
    """⛔ "structural pass DID NOT RUN (no user message on screen)" with
    "You said: est" on screen — the census's lub was -1."""
    _load(chrome, page, layout, thread=True)
    snap = chrome.run(page.evaluate(js_constant(research._log_chatgpt_thread_snapshot, "JS")))
    assert snap["lub"] > 0, snap
    # The reply's "ChatGPT said:" label sits in the TURN but outside the reply
    # text, on either page — only the turn marker can place it (a new-page turn
    # holds the user block and the reply; an old one was an article).
    rows = [r for r in snap["rows"] if r["t"] == "ChatGPT said:"]
    assert rows and all(r["inTurn"] for r in rows), snap["rows"]
    inline = chrome.run(page.evaluate(research._CHATGPT_INLINE_ACTIVITY_JS))
    assert inline is not None and inline["dbg"]["lub"] > 0, inline
    res = chrome.run(research._open_chatgpt_activity_panel(page))
    assert res.get("structSkip", "") != "no user message on screen", res
    assert res.get("structRan") is True, res


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_scraper_reads_the_reply_its_links_and_headings(chrome, page, logs, layout):
    _load(chrome, page, layout, thread=True)
    r = chrome.run(research.scrape_progress_chatgpt(page))
    reply_len = chrome.run(page.evaluate(
        "() => { const m = document.querySelectorAll('[data-markdown-text-style=\"assistant-message\"],"
        " [data-message-author-role=\"assistant\"]'); return m[m.length - 1].innerText.length; }"))
    # The reply's own text at least (a later pass may measure the whole turn).
    assert r["partial_text_len"] >= reply_len > 2000, r
    assert LINK in r["source_urls"], r
    assert HEADING in r["sections"], r
    assert r["status"] == "generating", r            # the Stop button, read
    if layout == "new":
        assert r["model"] == "Pro"


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_scrapers_own_host_read_sees_the_reply(chrome, page, logs, monkeypatch, layout):
    """The same, with the in-turn walker silenced: its pass also measures the
    reply, and would otherwise cover for a blind host read."""
    monkeypatch.setattr(research, "_CHATGPT_INLINE_ACTIVITY_JS", "() => null")
    _load(chrome, page, layout, thread=True)
    r = chrome.run(research.scrape_progress_chatgpt(page))
    assert r["partial_text_len"] > 2000, r
    assert LINK in r["source_urls"], r
    assert HEADING in r["sections"], r


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_stream_observer_attaches_to_the_reply(chrome, page, layout):
    _load(chrome, page, layout, thread=True)
    assert chrome.run(research.inject_agent_observer(page, "chatgpt")) is True


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_a_password_box_beside_the_composer_is_not_a_lost_session(chrome, page, layout):
    """A visible password field + login words reads as "signed out" UNLESS a
    composer is on the page. On the new page no old marker named one."""
    _load(chrome, page, layout)
    chrome.run(page.evaluate("""() => {
        const d = document.createElement('div');
        d.innerHTML = '<p>Enter your password to unlock connectors</p><input type="password">';
        document.body.appendChild(d);
    }"""))
    expired, why = chrome.run(research.detect_session_expiry(page, "chatgpt", "ChatGPT"))
    assert expired is False, why


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_stop_is_recognised_by_every_generating_check(chrome, page, layout):
    _load(chrome, page, layout, thread=True)
    assert chrome.run(research.verify_chatgpt_generating(page)) is True
    assert chrome.run(research._verify_chatgpt_generating_diag(page)).startswith("stop_composer:")
    assert chrome.run(research.is_agent_generating(page, "chatgpt")) is True
    probe = chrome.run(page.evaluate(research._CHATGPT_DONE_PROBE_JS))
    assert probe["hasStop"] is True and probe["assistantLen"] > 200, probe
    # And the named Stop matches the ONE marker (the broad aria scan would
    # have caught "Stop" anyway — this pins the marker itself).
    assert chrome.run(page.evaluate(
        "(s) => !!document.querySelector(s)", research.CHATGPT_STOP_SEL)) is True


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_brief_is_extracted_from_the_reply(chrome, page, fast, logs, layout):
    """Phase 1's ONLY extractor (HTML→markdown). On the new page `.markdown`
    matches nothing — the reply root is `MarkdownRoot-…`."""
    _load(chrome, page, layout, thread=True)
    md = chrome.run(research.extract_chatgpt_response(page))
    assert HEADING in md and LINK in md and "Deliverable" in md, (md, logs)
    assert PROMPT[:40] not in md          # the reply, never the prompt


@pytest.mark.parametrize("layout", LAYOUTS)
def test_live_the_thread_readers_see_the_messages(chrome, page, layout):
    _load(chrome, page, layout, thread=True)
    assert chrome.run(research.read_chatgpt_first_user_message(page)) == PROMPT
    st = chrome.run(page.evaluate(research._CHATGPT_NEW_CHAT_STATE_JS))
    assert st["composer"] is True and st["msgs"] >= 2, st
    _load(chrome, page, layout)
    st = chrome.run(page.evaluate(research._CHATGPT_NEW_CHAT_STATE_JS))
    assert st == {"composer": True, "msgs": 0}


def test_live_the_old_page_keeps_its_deep_research_probe_and_focus_helper(chrome, page):
    """OLD page only. On the new page these two already found the box through
    their generic `[contenteditable="true"]` fallbacks — they were routed
    through the one marker, not repaired — so a new-page run of this test
    would pass on the old code too and prove nothing about the change."""
    layout = "old"
    _load(chrome, page, layout)
    dr = chrome.run(page.evaluate(research._CHATGPT_DR_ACTIVE_JS))
    assert dr["active"] is False and dr["placeholder"] in ("ask chatgpt", "ask anything"), dr
    f = chrome.run(page.evaluate(research._CHATGPT_FOCUS_COMPOSER_END_JS))
    assert f["ok"] is True
    assert chrome.run(page.evaluate(
        "() => document.activeElement.getAttribute('contenteditable')")) == "true"


# ═══ 4. Pure pieces — run everywhere ═══════════════════════════════════════

@pytest.mark.parametrize("combo,darwin,other", [
    ("ctrl+a", "Meta+a", "Control+a"),
    ("ctrl+c", "Meta+c", "Control+c"),
    ("ctrl+v", "Meta+v", "Control+v"),
    ("ctrl+x", "Meta+x", "Control+x"),
    ("ctrl+z", "Meta+z", "Control+z"),
    ("ctrl+shift+z", "Meta+Shift+z", "Control+Shift+z"),
    ("ctrl+l", "Control+l", "Control+l"),       # not an edit shortcut: untouched
    ("Return", "Enter", "Enter"),
    ("Delete", "Delete", "Delete"),
    ("cmd+a", "Meta+a", "Meta+a"),
])
def test_cua_edit_shortcuts_are_command_on_macos(combo, darwin, other):
    assert research._cua_key_combo(combo, platform="darwin") == darwin
    assert research._cua_key_combo(combo, platform="linux") == other
    assert research._cua_key_combo(combo, platform="win32") == other


def test_the_browser_key_action_uses_the_mapping(monkeypatch):
    pressed = []

    class _KB:
        async def press(self, k):
            pressed.append(k)

    monkeypatch.setattr(research.sys, "platform", "darwin")
    asyncio.run(research.Browser.key(SimpleNamespace(page=SimpleNamespace(keyboard=_KB())), "ctrl+a"))
    assert pressed == ["Meta+a"]


def test_select_all_is_the_platform_one(monkeypatch):
    monkeypatch.setattr(research.sys, "platform", "darwin")
    assert research._platform_select_all() == "Meta+a"
    monkeypatch.setattr(research.sys, "platform", "linux")
    assert research._platform_select_all() == "Control+a"


def test_a_sent_message_must_start_with_the_prompt():
    f = research._chatgpt_text_is_prompt_start
    assert f(PROMPT, PROMPT) is True
    assert f("  " + PROMPT.replace(" ", "\n", 3) + "\n", PROMPT) is True
    assert f("est", PROMPT) is False
    assert f("test", PROMPT) is False
    assert f("", PROMPT) is False
    assert f(PROMPT, "") is False
    assert f(PROMPT[:30], PROMPT) is False           # a clipped prefix is not the prompt


def test_the_composer_diagnostic_is_one_readable_line():
    line = research._composer_diag_line({
        "box": {"tag": "DIV", "role": "textbox", "aria": "Ask ChatGPT", "ce": "true",
                "id": "", "cls": "ProseMirror", "vis": True},
        "active": {"tag": "BUTTON", "aria": "Select ChatGPT model", "vis": True},
        "menus": 0, "expanded": [], "editables": 1})
    assert "\n" not in line
    assert "box=DIV[role=textbox aria='Ask ChatGPT' ce=true cls=ProseMirror visible]" in line
    assert "focus=BUTTON[aria='Select ChatGPT model' visible]" in line
    assert "open menus=0" in line and "editables=1" in line


def _run_verify(monkeypatch, last_text, *, verify=True, diag_text="", guard=True,
                max_retries=3):
    calls = []

    async def _last(page):
        return last_text

    async def _gen(page):
        return verify

    async def _shadow(page, **kw):
        calls.append(kw.get("hotspot_id"))
        return {"text": diag_text}

    async def _guard(page, prompt, label):
        calls.append("guard")
        return guard

    async def _switch(p):
        return None

    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research, "_chatgpt_last_user_text", _last)
    monkeypatch.setattr(research, "_shadow_observed_cua", _shadow)
    monkeypatch.setattr(research, "_chatgpt_guard_box_before_fix", _guard)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    ok = asyncio.run(research.wait_until_verified(
        _gen, object(), "Phase1", browser=SimpleNamespace(switch_to_page=_switch),
        cua_client=object(), max_retries=max_retries, interval=0,
        chatgpt_prompt=PROMPT))
    return ok, calls


def test_verified_needs_our_prompt_as_the_last_message(monkeypatch):
    assert _run_verify(monkeypatch, "est")[0] is False
    assert _run_verify(monkeypatch, None)[0] is False
    assert _run_verify(monkeypatch, PROMPT)[0] is True


def test_the_cua_confirm_needs_our_prompt_too(monkeypatch):
    """The diagnosis step's own "✓ CUA confirms generating" is a second door."""
    said = "The response is still generating. CONCLUSION: GENERATING"
    ok, calls = _run_verify(monkeypatch, "est", verify=False, diag_text=said, max_retries=6)
    assert ok is False and "poll-diagnose" in calls
    ok, _ = _run_verify(monkeypatch, PROMPT, verify=False, diag_text=said, max_retries=6)
    assert ok is True


def test_the_cua_fix_runs_only_when_the_guard_allows_it(monkeypatch):
    ok, calls = _run_verify(monkeypatch, "est", verify=False, guard=False, max_retries=8)
    assert ok is False and "guard" in calls and "poll-fix" not in calls
    ok, calls = _run_verify(monkeypatch, "est", verify=False, guard=True, max_retries=8)
    assert calls.index("guard") < calls.index("poll-fix")


def test_without_a_chatgpt_prompt_nothing_changes_for_other_platforms(monkeypatch):
    calls = []

    async def _gen(page):
        return True

    async def _last(page):
        calls.append("read")
        return "est"

    monkeypatch.setattr(research, "_chatgpt_last_user_text", _last)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    assert asyncio.run(research.wait_until_verified(_gen, object(), "2B", max_retries=2,
                                                    interval=0)) is True
    assert calls == []


def test_phase_one_verifies_with_its_prompt_and_the_fallback_only_focuses():
    src = inspect.getsource(research.run_phase1)
    # The tier step's menu is closed before anything else touches the page.
    assert src.index("_chatgpt_close_open_menus(browser.page") < src.index(
        "submit_chatgpt_direct(browser, prompt")
    assert src.count("chatgpt_prompt=prompt") == 1
    assert src.count("chatgpt_prompt=followup") == 1
    assert src.count('.get("state") == "not_sent"') == 2
    assert src.count("use_focused=True") == 2
    import prompts
    assert "Do NOT type anything" in prompts.PROMPT_SUBMIT_FALLBACK
    assert "Press Enter or click Send" not in prompts.PROMPT_SUBMIT_FALLBACK
    assert "Do NOT type" in research._HOTSPOT_VISION_HINTS["1a-submit"]["context_hint"]


# ═══ 5. One place for the markers ═════════════════════════════════════════

@pytest.mark.parametrize("name,old,new", [
    ("CHATGPT_COMPOSER_SEL", "#prompt-textarea", NEW_BOX),
    ("CHATGPT_USER_MSG_SEL", '[data-message-author-role="user"]', '[data-user-message-bubble="true"]'),
    ("CHATGPT_ASSISTANT_MSG_SEL", '[data-message-author-role="assistant"]',
     '[data-markdown-text-style="assistant-message"]'),
    ("CHATGPT_REPLY_TEXT_SEL", '[data-message-author-role="assistant"] .markdown',
     '[data-markdown-text-style="assistant-message"]'),
    ("CHATGPT_TURN_SEL", '[data-testid^="conversation-turn"]', "[data-turn-key]"),
    ("CHATGPT_SEND_SEL", 'button[data-testid="send-button"]', 'button[aria-label="Send"]'),
    ("CHATGPT_STOP_SEL", 'button[data-testid="stop-button"]', 'button[aria-label="Stop"]'),
    ("CHATGPT_MODEL_TRIGGER_SEL", '[data-testid="model-selector"]',
     'button[aria-label="Select ChatGPT model"][aria-haspopup="menu"]'),
])
def test_every_marker_accepts_the_old_page_and_the_new(name, old, new):
    parts = [p.strip() for p in getattr(research, name).split(",")]
    assert old in parts and new in parts


class _SpliceVisitor(ast.NodeVisitor):
    """Counts `__CG_` string constants and records those NOT inside a
    `_cg_js(...)` call, the marker table, or the splice function itself."""

    def __init__(self, offset):
        self.inside, self.seen, self.bad, self.offset = 0, 0, [], offset

    def _scoped(self, node, yes):
        self.inside += yes
        self.generic_visit(node)
        self.inside -= yes

    def visit_Call(self, node):
        self._scoped(node, isinstance(node.func, ast.Name) and node.func.id == "_cg_js")

    def visit_Assign(self, node):
        self._scoped(node, any(isinstance(t, ast.Name) and t.id == "_CG_JS_MARKERS"
                               for t in node.targets))

    def visit_FunctionDef(self, node):
        self._scoped(node, node.name == "_cg_js")

    def visit_Constant(self, node):
        if isinstance(node.value, str) and "__CG_" in node.value:
            self.seen += 1
            if not self.inside:
                self.bad.append(node.lineno + self.offset)


def _statements_holding(src, needle):
    """(first line index, text) of each TOP-LEVEL statement whose text holds
    `needle` — parsing the whole 90k-line module costs ~20 s, these cost ~1 s."""
    lines = src.split("\n")
    head = __import__("re").compile(r"(async def |def |class |@|[A-Za-z_]\w*\s*(:[^=]*)?=)")
    starts = [i for i, ln in enumerate(lines) if head.match(ln)] + [len(lines)]
    out = []
    for a, b in zip(starts, starts[1:]):
        # A decorator belongs to the def below it.
        if lines[a].startswith("@"):
            continue
        chunk = "\n".join(lines[a:b])
        if needle in chunk:
            out.append((a, chunk))
    return out


def test_every_marker_placeholder_reaches_the_page_spliced():
    """A `__CG_…__` left in a string that never went through `_cg_js` is a
    selector that matches NOTHING, silently. Every one must sit inside a
    `_cg_js(...)` call (or be the marker table / the splice itself)."""
    src = Path(research.__file__).read_text(encoding="utf-8")
    seen, bad = 0, []
    for first, chunk in _statements_holding(src, "__CG_"):
        try:
            tree = ast.parse(chunk)
        except SyntaxError:
            # A column-0 line inside a string split a statement: parse it all.
            tree, first = ast.parse(src), 0
            v = _SpliceVisitor(first)
            v.visit(tree)
            seen, bad = v.seen, v.bad
            break
        v = _SpliceVisitor(first)
        v.visit(tree)
        seen += v.seen
        bad += v.bad
    assert seen > 20, "the splice is not in use — this test would measure nothing"
    assert src.count("__CG_") >= seen
    assert not bad, f"__CG_ placeholders outside _cg_js at lines {bad}"


def test_an_unknown_placeholder_is_refused():
    with pytest.raises(ValueError):
        research._cg_js("'__CG_NOPE__'")
    assert research._cg_within("a, b", "h2") == "a h2, b h2"


def test_the_other_platforms_keep_their_own_markers():
    """Claude's `data-testid="user-message"` is Claude's; nothing here may have
    folded it into ChatGPT's user marker, or ChatGPT's into Claude's walkers."""
    assert 'data-testid="user-message"' not in research.CHATGPT_USER_MSG_SEL
    src = inspect.getsource(research.detect_completion_claude)
    assert "__CG_" not in src and "CHATGPT_" not in src


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
