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

  2. _extract_via_cua_download — a page.on("download") listener captures the
     FIRST file and sets that abort_event; any straggler that still slips
     through is deleted; the listener is always detached in finally.

These tests use fakes (no real browser / Anthropic client) to prove both.

Run:  pytest tests/test_cua_download_idempotency.py -v
"""
import asyncio
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


# ── _extract_via_cua_download orchestration ──────────────────────────────
class _FakeDownload:
    def __init__(self, content):
        self._content = content
        self._path = None
        self.deleted = False

    async def path(self):
        return self._path

    async def delete(self):
        self.deleted = True


class _FakeDLPage:
    def __init__(self):
        self._handlers = {}

    def on(self, event, cb):
        self._handlers.setdefault(event, []).append(cb)

    def remove_listener(self, event, cb):
        lst = self._handlers.get(event, [])
        if cb in lst:
            lst.remove(cb)

    def emit_download(self, dl):
        for cb in list(self._handlers.get("download", [])):
            cb(dl)

    def n_listeners(self):
        return len(self._handlers.get("download", []))


def _mk_download(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    dl = _FakeDownload(body)
    dl._path = str(p)
    return dl


@pytest.mark.asyncio
async def test_extract_keeps_first_deletes_extras_and_detaches(tmp_path, monkeypatch):
    page = _FakeDLPage()
    body0 = "FIRST report " + "x" * 600
    body1 = "SECOND dup " + "y" * 600
    body2 = "THIRD dup " + "z" * 600
    dl0 = _mk_download(tmp_path, "r0.md", body0)
    dl1 = _mk_download(tmp_path, "r1.md", body1)
    dl2 = _mk_download(tmp_path, "r2.md", body2)

    # Fake CUA: emits THREE downloads in one burst (worst case), then honors
    # the abort. Only the first should be captured/read; the rest are extras.
    async def fake_agent_loop(client, browser, sp, um, *, abort_event=None, **kw):
        page.emit_download(dl0)
        page.emit_download(dl1)
        page.emit_download(dl2)
        await asyncio.sleep(0.01)
        if abort_event is not None and abort_event.is_set():
            return {"status": "aborted", "text": "burst"}
        return {"status": "max_iterations", "text": "all"}

    monkeypatch.setattr(research, "agent_loop", fake_agent_loop)

    content = await research._extract_via_cua_download(
        page, _FakeBrowser(), object(), "Claude",
        "prompt", "user",
        max_iterations=12, cua_timeout_s=5.0,
        download_timeout_ms=5000, min_chars=500,
    )

    assert content == body0, "must return the FIRST captured file, not a dup"
    assert dl1.deleted and dl2.deleted, "straggler downloads must be deleted"
    assert page.n_listeners() == 0, "download listener must be detached in finally"


@pytest.mark.asyncio
async def test_extract_single_download_happy_path(tmp_path, monkeypatch):
    page = _FakeDLPage()
    body = "the one true report " + "q" * 600
    dl = _mk_download(tmp_path, "only.md", body)

    async def fake_agent_loop(client, browser, sp, um, *, abort_event=None, **kw):
        # One click → one download → abort fires → no re-clicks.
        for i in range(6):
            if abort_event is not None and abort_event.is_set():
                return {"status": "aborted", "text": f"stopped@{i}"}
            if i == 0:
                page.emit_download(dl)
            await asyncio.sleep(0.01)
        return {"status": "max_iterations", "text": "looped"}

    monkeypatch.setattr(research, "agent_loop", fake_agent_loop)

    content = await research._extract_via_cua_download(
        page, _FakeBrowser(), object(), "ChatGPT",
        "prompt", "user",
        max_iterations=12, cua_timeout_s=5.0,
        download_timeout_ms=5000, min_chars=500,
    )
    assert content == body
    assert page.n_listeners() == 0
