"""The owner's 09-30 run — Phase 2 setup and Phase 3 on the changed pages.

Round 1: only what needs no new capture. Every test here drives the consumer
the run went through, and fails on the code the run used (2eddcf8).

  1. NotebookLM renamed its audio icon (`audio_magic_eraser` → `audio_spark`).
     The done check, the card counts, the download picker and the ⋮-menu scope
     all looked for the old name, so the finished audio was invisible to the
     page read: 12 computer-use checks over 17 minutes. And the computer-use
     check ran on every poll even while the page itself said "Generating".
  2. NotebookLM's upload gave up ~3 s after "New notebook", before the
     Add-sources dialog mounted (3 + 3 computer-use steps), and the source
     check spent 2 more computer-use steps on a list the page already showed.
  3. ChatGPT's "+" lost its test id on 09-28; New chat was judged 2 s after
     the press, while the old thread was still on screen (17 s lost).
  4. Claude's effort was judged once, in setup. The tier was Low by Send and
     nothing said so; the computer-use passes spent six steps on a hover
     submenu they cannot hold open.

The markup below is the 09-30 run's own #757-B dump (run.log 05:54:11) and the
captured ChatGPT page (tests/fixtures/chatgpt_0928/new_page.html). Nothing here
opens a real website: page JS runs under node against those shapes, and the one
browser test loads the local fixture into headless Chrome.
"""
from __future__ import annotations

import asyncio
import html as _html
import inspect
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

import models
import research
from _domshim import NODE, el, run_js
from conftest import code_only

needs_node = pytest.mark.skipif(NODE is None, reason="node runs the page scripts")

GEN = "Generating Audio Overview…"


# ═════════════════════════════════════════════════════════════════════════════
# The pages
# ═════════════════════════════════════════════════════════════════════════════

def _audio_tile():
    """The Studio's "Audio Overview" create tile, as the 09-30 dump shows it.
    It carries the SAME icon name as a finished card — which is why every
    reader must look inside <artifact-library-item> only."""
    return el("basic-create-artifact-button", {}, "", [
        el("div", {"role": "button", "aria-label": "Audio Overview",
                   "class": "mat-mdc-tooltip-trigger blue create-artifact-button-container"},
           "", [el("span", {"class": "default-container"}, "", [
               el("span", {"class": "icon-container"}, "", [
                   el("mat-icon", {}, "audio_spark"),
                   el("span", {"class": "create-label-container"}, "Audio Overview")]),
               el("mat-icon", {}, "chevron_forward")])])])


def _audio_card(icon="audio_spark", title="Golden Retriever Science Versus Marketing Myths",
                meta="61:59 · Deep dive · 2 sources · 5m ago"):
    """A finished audio card — artifact-library-item.has-unseen-dot, text
    'audio_sparkUnread Golden Retriever Science Versus Marketing…' (05:54:11)."""
    return el("artifact-library-item", {"class": "has-unseen-dot",
                                        "data-studio-accent": "blue"}, "", [
        el("div", {"class": "artifact-item-button"}, "", [
            el("div", {"class": "artifact-button-content"}, "", [
                el("div", {"class": "artifact-primary-content", "aria-hidden": "true"}, "", [
                    el("mat-icon", {}, icon), el("span", {}, "Unread"),
                    el("span", {}, title)]),
                el("div", {"class": "artifact-secondary"}, meta)])]),
        el("button", {"aria-label": "More", "aria-haspopup": "menu", "id": f"kebab-{icon}"}, "")])


def _study_guide():
    """Another artifact type in the same library, with its own icon."""
    return el("artifact-library-item", {}, "", [
        el("div", {"class": "artifact-primary-content"}, "", [
            el("mat-icon", {}, "stylus_note"), el("span", {}, "Study guide")]),
        el("button", {"aria-label": "More", "aria-haspopup": "menu", "id": "kebab-study"}, "")])


def _placeholder():
    return el("div", {"class": "artifact-placeholder"}, "", [
        el("span", {}, GEN), el("span", {}, "Come back in a few minutes")])


def _studio(*items):
    """The Studio panel chain from the dump: notebook > section.studio-panel >
    studio-panel > … > artifact-library-container > artifact-library."""
    return el("body", {}, "", [el("notebook", {}, "", [
        el("section", {"class": "studio-panel", "data-panel-state": "studio-home"}, "", [
            el("studio-panel", {}, "", [
                el("div", {"class": "panel-content-scrollable"}, "", [
                    el("div", {"class": "create-artifact-buttons-container"}, "", [_audio_tile()]),
                    el("div", {"class": "artifact-library-container"}, "", [
                        el("artifact-library", {"class": "luminous-ui"}, "", [
                            el("div", {"class": "artifact-library-ungrouped-items"}, "",
                               list(items))])])])])])])])


class NodePage:
    """`evaluate` RUNS each script under node against the current spec. A
    reload moves to the next spec in the list (the page NotebookLM serves on
    the next poll); the last one repeats. The poll reloads at the START of
    every cycle, so the first spec is the page before the poll begins."""

    def __init__(self, *specs, url="https://notebooklm.google.com/notebook/nb-0930"):
        self.specs, self.i, self.url = list(specs), 0, url
        self.keys = []
        self.keyboard = SimpleNamespace(press=self._press)

    @property
    def spec(self):
        return self.specs[min(self.i, len(self.specs) - 1)]

    async def _press(self, key):
        self.keys.append(key)

    async def evaluate(self, script, arg=None):
        return run_js(self.spec, script, arg).get("ret")

    async def reload(self, **kw):
        self.i += 1

    def is_closed(self):
        return False


def _go(coro):
    return asyncio.run(coro)


# ═════════════════════════════════════════════════════════════════════════════
# 1. NotebookLM: the renamed audio icon, everywhere
# ═════════════════════════════════════════════════════════════════════════════

@needs_node
def test_the_finished_0930_card_reads_as_done():
    assert _go(research._check_audio_complete_dom(NodePage(_studio(_audio_card())))) is True


@needs_node
def test_the_finished_0930_card_is_counted_once_and_the_create_tile_is_not():
    page = NodePage(_studio(_audio_card()))
    assert _go(research._count_nlm_audio_cards(page)) == 1
    assert _go(research._count_nlm_deep_dive_cards(page)) == 1


@needs_node
def test_the_picker_finds_the_0930_card():
    """05:54:11 'Download target: ordinal=1/0 (… no_cards)' — the picker saw none."""
    got = _go(research._pick_nlm_audio_card(NodePage(_studio(_audio_card())), "long"))
    assert got["count"] == 1 and got["complete"] is True, got


@needs_node
def test_the_old_icon_name_still_reads():
    """Both names stay: a page still serving the old one must not go blind."""
    page = NodePage(_studio(_audio_card(icon="audio_magic_eraser")))
    assert _go(research._check_audio_complete_dom(page)) is True
    assert _go(research._count_nlm_audio_cards(page)) == 1


@needs_node
def test_other_artifacts_are_still_not_audio():
    page = NodePage(_studio(_study_guide()))
    assert _go(research._check_audio_complete_dom(page)) is False
    assert _go(research._count_nlm_audio_cards(page)) == 0


@needs_node
def test_the_audio_menu_opens_on_the_audio_card_not_the_study_guide_above_it():
    """The ⋮-menu scope's first rung is "an artifact item carrying the audio
    icon". Blind to the new name, it fell to "any artifact item" (05:54:12
    'via=artifact-item') — which, with a study guide listed first, is the
    study guide's menu."""
    out = run_js(_studio(_study_guide(), _audio_card()), research._NLM_OPEN_AUDIO_MENU_JS,
                 {"scopes": research._NLM_AUDIO_MENU_SCOPES,
                  "triggers": research._NLM_AUDIO_TRIGGER_SELS})
    assert out["ret"]["via"] == "audio-card", out["ret"]
    assert out["ret"]["in_audio_card"] is True and len(out["clicks"]) == 1, out


# ── the poll loop, run for real ─────────────────────────────────────────────

def _poll_loop_source() -> str:
    """run_phase3_audio's completion poll, verbatim, as a function."""
    src = inspect.getsource(research.run_phase3_audio)
    a = src.index("    while True:\n        # ── Stop/Pause check per cycle ──")
    b = src.index("    # Download audio", a)
    body = textwrap.indent(textwrap.dedent(src[a:b]), "    ")
    return ("async def __poll__(browser, cua_client, podcast_length, notebook_url,\n"
            "                   verbose, poll_start):\n"
            "    _dup_logged = False\n    audio_done = False\n"
            + body + "    return audio_done\n")


class _Controls:
    """Stops the poll after `cycles` checks, so a reader that never sees the
    finished card ends the test instead of hanging it."""

    def __init__(self, cycles=8):
        self.left = cycles

    def is_stop(self):
        self.left -= 1
        return self.left < 0

    def is_pause(self):
        return False

    async def interruptible_sleep(self, *a, **k):
        return None


class _FastAsyncio:
    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(*a, **k):
        return None


def _run_poll(page, monkeypatch, cua_says="still generating"):
    lines, cua_calls = [], []

    async def _cua(*a, **k):
        cua_calls.append(k.get("current_step"))
        return {"text": cua_says}

    async def _no(*a, **k):
        return False

    async def _nothing(*a, **k):
        return None

    monkeypatch.setattr(research, "log", lambda m, lv="INFO", *a, **k: lines.append((lv, m)))
    ns = dict(vars(research))
    ns.update({"_controls": _Controls(), "_shadow_observed_cua": _cua,
               "_browser_context_is_dead": _no, "_work_tab_signed_out": _no,
               "_dump_nlm_audio_dom": _nothing, "emit_event": lambda *a, **k: None,
               "asyncio": _FastAsyncio(),
               "log": lambda m, lv="INFO", *a, **k: lines.append((lv, m))})
    exec(compile(_poll_loop_source(), "<poll>", "exec"), ns)
    done = _go(ns["__poll__"](SimpleNamespace(page=page), object(), "long",
                              page.url, False, research.time.time()))
    return done, cua_calls, [m for _, m in lines]


@needs_node
def test_no_computer_use_look_while_the_page_says_generating(monkeypatch):
    """The 09-30 poll: placeholder, placeholder, then the finished card. The
    page answered every one of those polls by itself."""
    page = NodePage(_studio(_placeholder()),                      # before the poll
                    _studio(_placeholder()), _studio(_placeholder()),
                    _studio(_placeholder()), _studio(_audio_card()))
    done, cua_calls, lines = _run_poll(page, monkeypatch)
    assert done is True
    assert cua_calls == [], f"computer use looked {len(cua_calls)} time(s) at a generating card"
    assert any("Audio generation complete ✓ (DOM-detected)" in m for m in lines), lines
    assert sum("no computer-use check this round" in m for m in lines) == 3, lines


@needs_node
def test_computer_use_still_looks_when_the_page_shows_neither(monkeypatch):
    """No placeholder and no finished card is not an answer — the fallback
    stays for exactly that poll."""
    page = NodePage(_studio(), _studio(), _studio(_audio_card()))
    done, cua_calls, _lines = _run_poll(page, monkeypatch)
    assert done is True and cua_calls == ["poll_audio_complete"], cua_calls


# ═════════════════════════════════════════════════════════════════════════════
# 2. NotebookLM: wait for the upload control; no computer-use look at a listed set
# ═════════════════════════════════════════════════════════════════════════════

class _Clock:
    def __init__(self):
        self.t = 0.0

    def asyncio(self):
        clock = self

        class _A:
            def __getattr__(self, name):
                return getattr(asyncio, name)

            @staticmethod
            async def sleep(secs=0, *a, **k):
                clock.t += float(secs or 0)
        return _A()


class _Input:
    def __init__(self):
        self.files = []

    async def set_input_files(self, files):
        self.files.extend(files)


class _NewNotebookPage:
    """A fresh notebook whose Add-sources dialog mounts `mounts_at` seconds in:
    before that there is no file input and no control matching anything."""

    def __init__(self, clock, mounts_at):
        self.clock, self.mounts_at = clock, mounts_at
        self.input = _Input()
        self.url = "https://notebooklm.google.com/notebook/nb-0930"

    async def query_selector(self, sel):
        if sel == 'input[type="file"]' and self.clock.t >= self.mounts_at:
            return self.input
        return None

    async def evaluate(self, script, arg=None):
        return None            # no control matches, nothing to unmark


def _add_files(monkeypatch, mounts_at):
    clock = _Clock()
    monkeypatch.setattr(research, "asyncio", clock.asyncio())
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    page = _NewNotebookPage(clock, mounts_at)
    browser = SimpleNamespace(set_upload_file=lambda p: None, clear_upload_file=lambda: None,
                              _upload_queue=[])
    ok = _go(research._nlm_dom_add_files(browser, page, ["/q/chatgpt.md", "/q/claude.md"]))
    return ok, page, clock


def test_the_upload_waits_for_a_dialog_that_mounts_six_seconds_in(monkeypatch):
    """05:32:50 create, 05:32:53 'no Upload control found', 05:32:59 the
    computer use sees the dialog with its Upload files button."""
    ok, page, clock = _add_files(monkeypatch, mounts_at=6)
    assert ok is True
    assert page.input.files == ["/q/chatgpt.md", "/q/claude.md"]


def test_the_upload_wait_is_bounded(monkeypatch):
    ok, page, clock = _add_files(monkeypatch, mounts_at=10_000)
    assert ok is False and page.input.files == []
    assert 14 <= clock.t <= 18, f"waited {clock.t}s — the bound is about 15 s"


class _DialogPage:
    """The Add-sources dialog mounts at `mounts_at` s with an "Upload files"
    control and no file input; pressing that control reveals the input. Page
    JS runs for real under node against whichever page is up at that moment."""

    def __init__(self, clock, mounts_at):
        self.clock, self.mounts_at = clock, mounts_at
        self.input, self.pressed = _Input(), []
        self.url = "https://notebooklm.google.com/notebook/nb-0930"
        self.marked = None

    def _spec(self):
        kids = [el("div", {"class": "source-panel"}, "", [el("p", {}, "Sources")])]
        if self.clock.t >= self.mounts_at:
            kids.append(el("div", {"role": "dialog", "w": "600", "h": "400"}, "", [
                el("p", {}, "or drop your files"),
                el("button", {"id": "upload-files"}, "", [
                    el("mat-icon", {}, "upload"), el("span", {}, "Upload files")])]))
        return el("body", {}, "", kids)

    async def query_selector(self, sel):
        if sel == 'input[type="file"]' and "upload-files" in self.pressed:
            return self.input
        return None

    async def evaluate(self, script, arg=None):
        out = run_js(self._spec(), script, arg, keep_dom=True)
        hit = [n for n in _walk(out["dom"]) if research._SR_CLICK_MARK in n["attrs"]]
        if hit:
            self.marked = hit[0]["attrs"].get("id")
        return out.get("ret")

    async def click(self, sel, timeout=None):
        self.pressed.append(self.marked)

    async def hover(self, sel, timeout=None):
        return None

    def expect_file_chooser(self, timeout=None):
        class _NoChooser:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                raise TimeoutError("no chooser — the dialog uses its hidden input")
        return _NoChooser()


def _walk(node):
    yield node
    for k in node.get("kids", []):
        yield from _walk(k)


@needs_node
def test_an_upload_control_on_screen_ends_the_wait_and_is_pressed(monkeypatch):
    """The dialog that mounted at 05:32:59 held an "Upload files" button. The
    wait ends when it is SEEN, and that button is what gets pressed."""
    clock = _Clock()
    monkeypatch.setattr(research, "asyncio", clock.asyncio())
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    page = _DialogPage(clock, mounts_at=3)
    browser = SimpleNamespace(set_upload_file=lambda p: None, clear_upload_file=lambda: None,
                              _upload_queue=[])
    ok = _go(research._nlm_dom_add_files(browser, page, ["/q/chatgpt.md"]))
    assert ok is True and page.input.files == ["/q/chatgpt.md"], (page.pressed, clock.t)
    assert page.pressed and page.pressed[0] == "upload-files", page.pressed
    assert clock.t <= 7, f"the wait ran {clock.t}s past a control that was on screen"


def _sources(*names, rows=True):
    if rows:
        kids = [el("div", {"class": "single-source-container"}, "", [
            el("mat-icon", {}, "article"), el("span", {}, n)]) for n in names]
    else:
        kids = [el("p", {}, " ".join(names))]
    return el("body", {}, "", [el("div", {"class": "source-panel"}, "", kids)])


def _verify_sources(monkeypatch, spec):
    cua_calls = []

    async def _cua(*a, **k):
        cua_calls.append(k.get("current_step"))
        return {"text": "ALL OK"}

    async def _nap(*a, **k):
        return None

    monkeypatch.setattr(research, "_shadow_observed_cua", _cua)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    browser = SimpleNamespace(page=NodePage(spec))
    missing = _go(research._verify_and_repair_nlm_sources(
        browser, object(), [Path("/q/chatgpt.md"), Path("/q/claude.md")]))
    return missing, cua_calls


@needs_node
def test_no_computer_use_source_check_when_every_file_is_listed(monkeypatch):
    missing, cua_calls = _verify_sources(monkeypatch, _sources("chatgpt.md", "claude.md"))
    assert missing == set()
    assert cua_calls == [], "the Sources panel already listed every file"


@needs_node
def test_the_computer_use_check_stays_when_no_source_row_was_read(monkeypatch):
    """Names found only in the page's text are weaker evidence than rows."""
    missing, cua_calls = _verify_sources(
        monkeypatch, _sources("chatgpt.md", "claude.md", rows=False))
    assert missing == set() and cua_calls == ["verify_sources_health"], cua_calls


# ═════════════════════════════════════════════════════════════════════════════
# 3. ChatGPT Phase 2: the new "+" marker; New chat waits for the old thread
# ═════════════════════════════════════════════════════════════════════════════

FIX = Path(__file__).parent / "fixtures" / "chatgpt_0928"


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


def test_live_the_plus_is_found_by_its_marker_when_its_label_changes(chrome, monkeypatch):
    """The captured "+" ('Add files and more', data-composer-navigation-target=
    "add-context"), with its label in another wording. The label patterns miss
    it; the durable marker must not."""
    src = (FIX / "new_page.html").read_text(encoding="utf-8")
    old = 'aria-label="Add files and more"'
    assert src.count(old) == 1, "the captured + button moved in the fixture"
    src = src.replace(old, 'aria-label="' + _html.escape("Ajouter des fichiers et plus") + '"')
    lines = []
    monkeypatch.setattr(research, "log", lambda m, lv="INFO", *a, **k: lines.append(str(m)))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    page = chrome.run(chrome.ctx.new_page())
    try:
        chrome.run(page.set_content(src))
        chrome.run(page.evaluate(
            "() => document.addEventListener('click', e => {"
            " const b = e.target.closest('button');"
            " (window.__pressed = window.__pressed || []).push("
            "   b ? (b.getAttribute('data-composer-navigation-target') || b.getAttribute('aria-label') || '?') : '-');"
            "}, true)"))
        chrome.run(research.setup_chatgpt_dr(page))
        pressed = chrome.run(page.evaluate("() => window.__pressed || []"))
    finally:
        chrome.run(page.close())
    assert pressed and pressed[0] == "add-context", (pressed, lines)
    assert any('Step 1 OK: opened tools menu via '
               'button[data-composer-navigation-target="add-context"]' in m for m in lines), lines


class _NewChatPage:
    """A ChatGPT conversation tab. After New chat the address moves at once,
    and the old question and reply stay mounted until `clears_at` seconds."""

    def __init__(self, clock, clears_at):
        self.clock, self.clears_at = clock, clears_at
        self.url = "https://chatgpt.com/c/6a72ce1e-2284-83ea"
        self.pressed_at = None

    async def evaluate(self, script, arg=None):
        if arg == research._SR_CLICK_MARK:                 # the marker pass
            return 'button[aria-label*="New chat" i]'
        old_still_there = self.pressed_at is None or (
            self.clock.t - self.pressed_at < self.clears_at)
        return {"composer": True, "msgs": 2 if old_still_there else 0}


def _new_chat(monkeypatch, clears_at):
    clock = _Clock()
    page = _NewChatPage(clock, clears_at)

    async def _press(p, value, *, tag, **kw):
        p.url = "https://chatgpt.com/"
        p.pressed_at = clock.t
        return "pointer"

    lines = []
    monkeypatch.setattr(research, "asyncio", clock.asyncio())
    monkeypatch.setattr(research, "_sr_real_click", _press)
    monkeypatch.setattr(research, "log", lambda m, lv="INFO", *a, **k: lines.append((lv, m)))
    return _go(research._chatgpt_force_new_chat(page, "2A")), clock, lines


def test_a_new_chat_whose_old_thread_clears_at_three_seconds_is_a_new_chat(monkeypatch):
    """05:08:40 pressed, 05:08:42 'thread already holds 2 message(s) — NOT a
    fresh chat', 05:08:52 ready after a reload. The chat was new."""
    ok, clock, lines = _new_chat(monkeypatch, clears_at=3)
    assert ok is True, lines
    assert not [m for lv, m in lines if "NOT a fresh chat" in m], lines


def test_a_thread_that_never_clears_is_still_refused_within_about_five_seconds(monkeypatch):
    ok, clock, lines = _new_chat(monkeypatch, clears_at=10_000)
    assert ok is False
    assert 4.5 <= clock.t <= 6, f"waited {clock.t}s"
    assert [m for lv, m in lines if lv == "WARN" and "NOT a fresh chat" in m], lines


# ═════════════════════════════════════════════════════════════════════════════
# 4. Claude's effort, told honestly
# ═════════════════════════════════════════════════════════════════════════════

def _trigger(text):
    return el("button", {"data-testid": research._CLAUDE_MODEL_TRIGGER_TESTID,
                         "aria-label": f"Model: {text}", "aria-haspopup": "menu"}, text)


def _research_pill():
    return el("button", {"aria-label": "Research", "aria-pressed": "true"}, "Research")


def _composer(trigger_text):
    return el("body", {}, "", [
        el("nav", {}, "", [el("button", {"aria-label": "plan"}, "Boss · Max")]),
        _trigger(trigger_text), _research_pill()])


def _telemetry_source() -> str:
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    head = '        if research_ok and platform_l in ("claude", "gemini"):'
    tail = '        if not research_ok:'
    assert src.count(head) == 1, "the telemetry block header moved"
    i = src.index(head)
    block = textwrap.dedent(src[i:src.index(tail, i)])
    return "def __telemetry__(research_ok):\n" + textwrap.indent(block, "    ")


def _label(word):
    return getattr(models, "effort_label", lambda w: str(w).capitalize())(word)


@needs_node
def test_a_tier_that_moved_after_setup_is_said_on_the_tile_the_log_and_the_summary(monkeypatch):
    """⛔⛔ 09-30: setup read the wanted tier off the button (05:09:54, "already
    via=trigger"); the tier was Low by Send (05:11:18); Claude researched at Low,
    the tile said nothing and the end-of-run summary said "✓ already". The LAST
    read before Send decides now."""
    wanted = models.p2_labels("claude")["effort"]
    lines, events = [], []
    monkeypatch.setattr(research, "_DOM_ATTEMPTS", [])
    monkeypatch.setattr(research, "log", lambda m, lv="INFO", *a, **k: lines.append((lv, str(m))))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: events.append((a, k)))
    # Setup, as it went: the button showed the wanted tier.
    research._dom_note("claude.select_effort_tier", "already", phase=2, via="trigger")
    state = {"effort": True, "thinking": False, "effort_got": wanted, "model": True}
    # The real pre-send read, on a button that now reads Low.
    mode_state = _go(research.ensure_deep_mode_active(
        NodePage(_composer("Opus 5.5 Low")), "claude", "2B", reactivate=False))
    assert mode_state.get("effortShown") == "low", mode_state
    ns = dict(vars(research))
    ns.update({"platform_l": "claude", "label": "2B", "mode_state": mode_state,
               "_P2_THINKING_STATE": {"claude": state},
               "record_known_good": lambda *a, **k: None,
               "emit_event": lambda *a, **k: events.append((a, k)),
               "log": lambda m, lv="INFO", *a, **k: lines.append((lv, str(m)))})
    exec(compile(_telemetry_source(), "<telemetry>", "exec"), ns)
    ns["__telemetry__"](True)
    captions = [k.get("progress") for a, k in events
                if a and a[0] == "agent_progress" and k.get("agent") == "claude"]
    assert captions == [f"Claude is researching at Low effort — {_label(wanted)} could "
                        f"not be set"], (captions, lines)
    assert any(lv == "WARN" and f"(effort is 'low', not the '{wanted}' wanted)" in m
               for lv, m in lines), lines
    research._dom_summary("run complete")
    summary = [m for _, m in lines if m.startswith("[dom-summary] run complete   ")]
    assert any("✗ p2 claude.select_effort_tier: missed" in m and "right before Send" in m
               for m in summary), summary
    assert not any("✓ p2 claude.select_effort_tier" in m for m in summary), summary


@needs_node
def test_the_wanted_tier_on_the_button_at_send_says_nothing(monkeypatch):
    wanted = models.p2_labels("claude")["effort"]
    lines, events = [], []
    monkeypatch.setattr(research, "_DOM_ATTEMPTS", [])
    monkeypatch.setattr(research, "log", lambda m, lv="INFO", *a, **k: lines.append((lv, str(m))))
    research._dom_note("claude.select_effort_tier", "already", phase=2, via="trigger")
    mode_state = _go(research.ensure_deep_mode_active(
        NodePage(_composer(f"Opus 5.5 {wanted.capitalize()}")), "claude", "2B",
        reactivate=False))
    ns = dict(vars(research))
    ns.update({"platform_l": "claude", "label": "2B", "mode_state": mode_state,
               "_P2_THINKING_STATE": {"claude": {"effort": True, "effort_got": wanted}},
               "record_known_good": lambda *a, **k: None,
               "emit_event": lambda *a, **k: events.append((a, k)),
               "log": lambda m, lv="INFO", *a, **k: lines.append((lv, str(m)))})
    exec(compile(_telemetry_source(), "<telemetry>", "exec"), ns)
    ns["__telemetry__"](True)
    assert events == [] and not [m for lv, m in lines if lv == "WARN"], (events, lines)
    assert [r["outcome"] for r in research._DOM_ATTEMPTS] == ["already"]


def test_the_wanted_tier_is_extra_high_in_the_existing_words():
    """The owner, 09-30: Extra (Max uses 5.5× or more usage). The policy keeps
    the Effort menu's own word, which every reader already knows — and since
    round 2 the run SAYS the page's word too: the 09-30 capture's row reads
    "Extra" and the model button "Opus 5.5 Extra"."""
    assert models.p2_labels("claude")["effort"] == "extra"
    assert research._claude_effort_option_testid("extra") == "effort-option-xhigh"
    assert models.effort_label("extra") == "Extra"
    assert models.effort_label("max") == "Max"


@needs_node
def test_a_run_whose_only_miss_is_the_tier_does_not_descend_to_computer_use():
    """Both rungs below are computer-use passes, which no longer touch effort."""
    page = NodePage(_composer("Opus 5.5 Low"))
    assert _go(research._dr_outcome_state(page, "claude")) == "on"


def _cua_setup_rung_source() -> str:
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    a = src.index("    async def _rung_cua_setup():")
    b = src.index("    async def _rung_cua_validate():", a)
    return textwrap.dedent(src[a:b])


def _run_cua_setup_rung(monkeypatch, state):
    sent = []

    async def _agent_loop(client, browser, system, user, **k):
        sent.append((system, user))
        return "ready for paste"

    async def _observed(page, **k):
        return await k["cua_coro_factory"]()

    monkeypatch.setitem(research._P2_THINKING_STATE, "claude", state)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    ns = dict(vars(research))
    ns.update({"platform_l": "claude", "platform": "Claude", "label": "2B",
               "prompt_system": "SETUP-SYSTEM", "prompt_user": "SETUP-USER",
               "cua_client": object(), "browser": object(), "page": object(),
               "verbose": False, "agent_loop": _agent_loop,
               "_shadow_observed_cua": _observed, "log": lambda *a, **k: None})
    exec(compile(_cua_setup_rung_source(), "<rung>", "exec"), ns)
    _go(ns["_rung_cua_setup"]())
    return sent


def test_a_confirmed_model_leaves_computer_use_only_the_research_switch(monkeypatch):
    """05:09:57: DOM had read Opus 5.5 and missed only Research; the full
    mission spent steps 1-3 reopening the model menu."""
    sent = _run_cua_setup_rung(monkeypatch, {"effort": True, "model": True})
    assert len(sent) == 1
    system, user = sent[0]
    assert (system, user) != ("SETUP-SYSTEM", "SETUP-USER"), "the full mission went out"
    assert "do NOT open the model menu" in user and "switch 'Research' ON" in user, user
    assert "DO NOT open the model menu" in system, system


def test_an_unconfirmed_model_keeps_the_full_mission(monkeypatch):
    sent = _run_cua_setup_rung(monkeypatch, {"effort": True, "model": False})
    assert sent == [("SETUP-SYSTEM", "SETUP-USER")]


@needs_node
def test_setup_records_that_the_page_confirmed_the_model(monkeypatch):
    """The fact the rung above keys on is written by setup itself."""
    wanted = models.p2_labels("claude")["effort"]

    async def _instant(*a, **k):
        return None
    monkeypatch.setattr(research.asyncio, "sleep", _instant)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_DOM_ATTEMPTS", [])
    monkeypatch.delitem(research._P2_THINKING_STATE, "claude", raising=False)
    page = NodePage(el("body", {}, "", [_trigger(f"Opus 5.5 {wanted.capitalize()}")]),
                    url="https://claude.ai/new")

    async def _no_click(*a, **k):
        return None
    page.click = _no_click
    page.hover = _no_click
    page.query_selector = _no_click
    _go(research.setup_claude_dr(page))
    assert research._P2_THINKING_STATE["claude"].get("model") is True


def test_the_validator_is_never_sent_into_the_effort_submenu(monkeypatch):
    """05:10:43-05:10:51: the validator was pointed at the Effort submenu,
    said it would not expand, and gave up. Driven through the validator itself
    with setup NOT having confirmed the tier — the case that used to grant it."""
    missions = []

    async def _observed(page, **k):
        missions.append(k.get("mission_prompt") or "")
        return {"text": "setup verified"}

    async def _switch(p):
        return None

    monkeypatch.setitem(research._P2_THINKING_STATE, "claude",
                        {"effort": False, "effort_got": "low", "model": True})
    monkeypatch.setattr(research, "_shadow_observed_cua", _observed)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    browser = SimpleNamespace(switch_to_page=_switch)
    _go(research.validate_setup_with_cua(browser, object(), object(), "claude", "2B"))
    assert len(missions) == 1
    low = missions[0].lower()
    assert "open the \"effort\" submenu, choose" not in low
    assert "open the effort submenu, choose" not in low
    assert models.EFFORT_HANDS_OFF.lower() in low
