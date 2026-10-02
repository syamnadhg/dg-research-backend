"""Tests for #732 — Claude/ChatGPT P4 markdown download idempotency.

The bug: Claude's artifact "Download as Markdown" menu item does not visibly
close after a click, so the CUA vision agent thinks the click "didn't
register" and re-clicks — observed up to 6× in prod, each click a real .md
download. The fix has two cooperating parts:

  1. agent_loop(abort_event=...) — checked at the top of every iteration AND
     before each tool dispatch, so once the event is set the loop issues NO
     further clicks (even a second click queued in the same model turn).
     Deterministic regardless of event-loop timing (the synchronous Anthropic
     call would otherwise delay a task .cancel()).

  2. _cua_export_caught (2026-10-02; was _extract_via_cua_download, which read
     Chrome's own download) — the page's export catcher holds every file the
     export makes and Chrome downloads none; the FIRST file of the kind asked
     for, caught after the press began, sets that abort_event and is the one
     read back; a page that lost the catcher (a navigation) has it put back.

These tests use fakes (no real browser / Anthropic client) to prove both.

Run:  pytest tests/test_cua_download_idempotency.py -v
"""
import asyncio
import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


# ── fakes ──────────────────────────────────────────────────────────────
class _TextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, action, coordinate, id="tb1"):
        self.input = {"action": action, "coordinate": coordinate}
        self.id = id


class _FakeResp:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    """Returns `n_clicks` left_click tool_uses per `create`, configurable."""

    def __init__(self, outer):
        self._outer = outer

    def create(self, **kw):
        self._outer.create_calls += 1
        blocks = [_TextBlock("clicking download as markdown")]
        for i in range(self._outer.clicks_per_turn):
            blocks.append(_ToolUseBlock("left_click", (1059, 59 + i), id=f"tb{i}"))
        return _FakeResp(blocks)


class _FakeBeta:
    def __init__(self, outer):
        self.messages = _FakeMessages(outer)


class _FakeClient:
    def __init__(self, clicks_per_turn=1):
        self.create_calls = 0
        self.clicks_per_turn = clicks_per_turn
        self.beta = _FakeBeta(self)


class _FakeBrowserPage:
    """Minimal page used by execute_action's keyboard.insert_text branch."""

    class _Kb:
        async def insert_text(self, text):
            pass

    def __init__(self):
        self.keyboard = self._Kb()


class _FakeBrowser:
    """Each left_click optionally fires `on_click` (used to set the abort)."""

    def __init__(self, on_click=None):
        self.clicks = 0
        self.page = _FakeBrowserPage()
        self._on_click = on_click

    async def switch_to_page(self, p):
        pass

    async def screenshot(self):
        return "ZmFrZXNz"  # non-empty so agent_loop doesn't early-return

    async def left_click(self, x, y):
        self.clicks += 1
        if self._on_click is not None:
            self._on_click()


# ── agent_loop abort_event guard ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_agent_loop_aborts_before_any_click_when_event_preset():
    # Event already set on entry → loop returns 'aborted' before the API call
    # or any click.
    ev = asyncio.Event()
    ev.set()
    client = _FakeClient(clicks_per_turn=1)
    browser = _FakeBrowser()
    res = await research.agent_loop(
        client, browser, "sys", "msg",
        max_iterations=5, abort_event=ev,
    )
    assert res["status"] == "aborted"
    assert browser.clicks == 0
    assert client.create_calls == 0


@pytest.mark.asyncio
async def test_agent_loop_stops_after_first_click_when_event_trips():
    # The first click sets the event (models _capture_download firing). The
    # loop must NOT issue a second click on the next iteration.
    ev = asyncio.Event()
    browser = _FakeBrowser(on_click=ev.set)
    client = _FakeClient(clicks_per_turn=1)
    res = await research.agent_loop(
        client, browser, "sys", "msg",
        max_iterations=10, abort_event=ev,
    )
    assert res["status"] == "aborted"
    assert browser.clicks == 1, f"expected exactly 1 click, got {browser.clicks}"


@pytest.mark.asyncio
async def test_agent_loop_skips_second_click_in_same_model_turn():
    # Two left_clicks emitted in ONE model response. The first sets the event;
    # the per-tool-use guard must skip the second before dispatching it.
    ev = asyncio.Event()
    browser = _FakeBrowser(on_click=ev.set)
    client = _FakeClient(clicks_per_turn=2)
    res = await research.agent_loop(
        client, browser, "sys", "msg",
        max_iterations=10, abort_event=ev,
    )
    assert res["status"] == "aborted"
    assert browser.clicks == 1, f"second same-turn click not skipped: {browser.clicks}"




# ── _cua_export_caught orchestration ─────────────────────────────────────
class _CatchPage:
    """The page as the export catcher sees it: the files it has caught, read
    by the catcher's own three scripts (put on, list, read back)."""

    def __init__(self, lost=False):
        self.caught, self.files, self.armed, self.lost = [], {}, 0, lost

    def make(self, name, type_, body):
        n = len(self.caught) + 1
        self.caught.append({"id": n, "name": name, "type": type_, "size": len(body),
                            "via": "anchor.click()"})
        self.files[n] = body

    async def evaluate(self, js, arg=None):
        if js == research._EXPORT_CATCH_JS:
            self.armed += 1
            again, self.lost = not self.lost, False
            return {"armed": True, "again": again}
        if js == research._EXPORT_CATCH_LIST_JS:
            return None if self.lost else [dict(c) for c in self.caught]
        if js == research._EXPORT_CATCH_READ_JS:
            return base64.b64encode(self.files[arg["id"]][arg["start"]:arg["end"]]).decode()
        raise AssertionError(f"unexpected page script: {js[:60]!r}")


@pytest.mark.asyncio
async def test_the_first_caught_file_is_kept_and_stops_the_loop(monkeypatch):
    """Three files in one burst (the worst case): the first is the one read
    back, and the loop is told to stop."""
    page = _CatchPage()
    seen = {}

    async def fake_agent_loop(client, browser, sp, um, *, abort_event=None, **kw):
        page.make("r0.md", "text/markdown", b"FIRST report " + b"x" * 600)
        page.make("r1.md", "text/markdown", b"SECOND dup " + b"y" * 600)
        page.make("r2.md", "text/markdown", b"THIRD dup " + b"z" * 600)
        try:
            for _ in range(100):
                if abort_event is not None and abort_event.is_set():
                    seen["stopped"] = "aborted"
                    return {"status": "aborted"}
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            seen["stopped"] = "cancelled"
            raise
        return {"status": "max_iterations"}

    monkeypatch.setattr(research, "agent_loop", fake_agent_loop)
    got = await research._cua_export_caught(
        page, _FakeBrowser(), object(), "Claude", "prompt", "user",
        kind="markdown", since=0, max_iterations=12, cua_timeout_s=5.0, grace_s=0.5)
    assert got["bytes"] == b"FIRST report " + b"x" * 600
    assert got["name"] == "r0.md" and seen.get("stopped"), seen


@pytest.mark.asyncio
async def test_one_press_one_file_and_no_second_press(monkeypatch):
    page = _CatchPage()
    presses = []

    async def fake_agent_loop(client, browser, sp, um, *, abort_event=None, **kw):
        for i in range(50):
            if abort_event is not None and abort_event.is_set():
                return {"status": "aborted"}
            presses.append(i)
            if i == 0:
                page.make("only.md", "text/markdown", b"the one true report " + b"q" * 600)
            await asyncio.sleep(0.05)
        return {"status": "max_iterations"}

    monkeypatch.setattr(research, "agent_loop", fake_agent_loop)
    got = await research._cua_export_caught(
        page, _FakeBrowser(), object(), "ChatGPT", "prompt", "user",
        kind="markdown", since=0, cua_timeout_s=5.0, grace_s=0.5)
    assert got["bytes"].startswith(b"the one true report")
    assert len(presses) < 15, "computer use kept pressing after the file was caught"


@pytest.mark.asyncio
async def test_a_file_of_another_kind_or_caught_before_is_not_taken(monkeypatch):
    """Asked for the PDF: the Markdown caught before the press began and the
    Markdown this press made are not it — nothing comes back."""
    page = _CatchPage()
    page.make("before.pdf", "application/pdf", b"%PDF-old")

    async def fake_agent_loop(client, browser, sp, um, *, abort_event=None, **kw):
        page.make("r.md", "text/markdown", b"# not the pdf" + b"m" * 600)
        return {"status": "done"}

    monkeypatch.setattr(research, "agent_loop", fake_agent_loop)
    got = await research._cua_export_caught(
        page, _FakeBrowser(), object(), "ChatGPT", "prompt", "user",
        kind="pdf", since=1, cua_timeout_s=2.0, grace_s=0.3)
    assert got is None


@pytest.mark.asyncio
async def test_a_page_that_lost_the_catcher_gets_it_back(monkeypatch):
    """The page navigated and lost the catcher: it is put back before the file
    is looked for, so computer use's press is still caught."""
    page = _CatchPage(lost=True)

    async def fake_agent_loop(client, browser, sp, um, *, abort_event=None, **kw):
        for _ in range(100):
            if page.armed and not page.caught:
                page.make("r.md", "text/markdown", b"# after the navigation " + b"n" * 600)
            if abort_event is not None and abort_event.is_set():
                return {"status": "aborted"}
            await asyncio.sleep(0.02)
        return {"status": "max_iterations"}

    monkeypatch.setattr(research, "agent_loop", fake_agent_loop)
    got = await research._cua_export_caught(
        page, _FakeBrowser(), object(), "ChatGPT", "prompt", "user",
        kind="markdown", since=0, cua_timeout_s=5.0, grace_s=0.5)
    assert page.armed == 1 and got["bytes"].startswith(b"# after the navigation")


# ── reading a caught file back ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_file_larger_than_one_read_comes_back_whole(monkeypatch):
    """Read back a piece at a time, the pieces are the file."""
    monkeypatch.setattr(research, "_EXPORT_CHUNK", 1000)
    page = _CatchPage()
    body = bytes((i * 13) % 256 for i in range(4321))
    page.make("big.pdf", "application/pdf", body)
    assert await research._export_catch_read(page, dict(page.caught[0]), "ChatGPT") == body


@pytest.mark.asyncio
async def test_a_file_too_large_or_cut_short_is_not_taken(monkeypatch):
    """Larger than the cap: not read at all. Read back short: not taken."""
    monkeypatch.setattr(research, "_EXPORT_MAX_BYTES", 100)
    page = _CatchPage()
    page.make("huge.pdf", "application/pdf", b"x" * 101)
    assert await research._export_catch_read(page, dict(page.caught[0]), "ChatGPT") is None
    page.make("short.md", "text/markdown", b"y" * 50)
    entry = dict(page.caught[1], size=60)
    assert await research._export_catch_read(page, entry, "ChatGPT") is None
