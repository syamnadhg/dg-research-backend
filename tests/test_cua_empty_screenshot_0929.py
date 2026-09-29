"""The vision step never sends Anthropic an empty picture (2026-09-29).

⛔⛔ THE DEFECT. A busy ChatGPT tab (writing a long answer) took too long to
capture. `Browser.screenshot` tried twice and returned "", and `agent_loop` put
that "" into the next tool result as an image. Anthropic refuses the WHOLE
request for an empty image, and `agent_loop` treats that 400 as the end, so the
vision step failed outright instead of looking again. The owner's log:

    10:07:03 [WARN]  Screenshot failed: Page.screenshot: Timeout 10000ms exceeded.
    10:07:21 [INFO]  Iteration 3/5
    10:07:21 [ERROR] API error: Error code: 400 - {... 'messages.4.content.0.
                     tool_result.content.1.image.source.base64: image cannot be empty'}
    10:07:21 [WARN]  [Phase1] CUA tier-3 didn't confirm panel: error code: 400 ...

⭐ THE RULE NOW. Every picture after the first goes through one helper: an empty
screenshot is taken once more, and if that fails too the model is told in words
("the page is busy, take another screenshot") and the step goes on.

Measured on the REAL `agent_loop`, the REAL `Browser.screenshot` and the REAL
`execute_action`. Only the page (whose screenshots time out on cue) and the API
client are stand-ins — and the client applies the API's own rule: any request
carrying an empty image is refused with the 400 the owner's run got. All five
places a picture is sent are driven, one at a time.
"""
import asyncio
from types import SimpleNamespace

import pytest

import research

PNG = b"\x89PNG-ok"
RETRY_PNG = b"\x89PNG-retry"
NOTE = "The screenshot could not be taken because the page is busy."


class _FastAsyncio:
    """research's `asyncio` with every sleep capped: `Browser.screenshot` waits
    2 s between its tries and `execute_action` 0.5 s after each action."""

    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(delay=0, *a, **k):
        await asyncio.sleep(0)


class _Page:
    """A page whose next `fail` screenshots time out, the way the busy ChatGPT
    tab did. After those, the next one is `RETRY_PNG` once, then `PNG`."""

    def __init__(self):
        self.fail = 0
        self.after_fail = None
        self.calls = 0
        self.mouse = SimpleNamespace(click=self._click)
        self.keyboard = SimpleNamespace(press=self._noop)
        self.clicks = 0

    async def _click(self, *a, **k):
        self.clicks += 1

    async def _noop(self, *a, **k):
        return None

    async def screenshot(self, **kw):
        self.calls += 1
        if self.fail > 0:
            self.fail -= 1
            if self.fail == 0:
                self.after_fail = RETRY_PNG
            raise TimeoutError("Page.screenshot: Timeout 10000ms exceeded.")
        if self.after_fail is not None:
            out, self.after_fail = self.after_fail, None
            return out
        return PNG


def _dicts(content):
    return [c for c in (content if isinstance(content, list) else []) if isinstance(c, dict)]


class _Client:
    """The API, as far as this defect goes: it refuses any request holding an
    empty image with the owner's 400; otherwise it plays `steps` (one tool use
    each, arming the page's timeouts as it hands the step out) and then answers
    in text."""

    def __init__(self, page, steps):
        self.page = page
        self.steps = list(steps)
        self.sent = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, *, messages, **kw):
        for m in messages:
            for c in _dicts(m.get("content")):
                blocks = _dicts(c.get("content")) if c.get("type") == "tool_result" else [c]
                for b in blocks:
                    if b.get("type") == "image" and not b["source"]["data"]:
                        raise RuntimeError(
                            "Error code: 400 - {'type': 'error', 'error': {'type': "
                            "'invalid_request_error', 'message': 'messages.4.content.0."
                            "tool_result.content.1.image.source.base64: image cannot be "
                            "empty'}}")
        self.sent.append(messages[-1])
        if self.steps:
            action, fail = self.steps.pop(0)
            self.page.fail = fail
            return SimpleNamespace(content=[SimpleNamespace(
                type="tool_use", id=f"tu{len(self.sent)}", input=dict(action))])
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="panel: open")])


@pytest.fixture
def logs(monkeypatch):
    lines = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO": lines.append((level, str(msg))))
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "asyncio", _FastAsyncio())
    monkeypatch.setattr(research._controls, "is_stop", lambda: False)
    monkeypatch.setattr(research._controls, "is_pause", lambda: False)
    return lines


CLICK = {"action": "left_click", "coordinate": [40, 40]}

#: (name, steps before the one under test, the step under test, agent_loop kwargs)
BRANCHES = [
    ("a screenshot the model asked for", [], {"action": "screenshot"}, {}),
    ("the picture after an action", [], CLICK, {}),
    ("the picture after a refused action", [], {"action": "type", "text": "hello"},
     {"allow": research.CUA_CLICK_ONLY}),
    ("the picture after a refused click on Send", [], CLICK,
     {"never_click": research.CUA_NEVER_CLICK_SEND}),
    ("the picture with the 'you seem stuck' hint", [(CLICK, 0)] * 4, CLICK, {}),
]


def _run(page, client, **kw):
    browser = research.Browser.__new__(research.Browser)
    browser.page = page
    return asyncio.run(research.agent_loop(client, browser, "sys", "open the activity",
                                           max_iterations=8, verbose=True, **kw))


def _result_after(client, n_before):
    """The tool result the model received for the step under test."""
    msg = client.sent[n_before + 1]
    [res] = [c for c in _dicts(msg["content"]) if c.get("type") == "tool_result"]
    return _dicts(res["content"])


@pytest.mark.parametrize("name,before,step,kw", BRANCHES, ids=[b[0] for b in BRANCHES])
def test_a_page_too_busy_to_screenshot_is_told_in_words_not_sent_as_an_empty_picture(
        logs, name, before, step, kw):
    """Both of `Browser.screenshot`'s tries time out, and so does the retry: the
    model is told in words and the step goes on. Before the fix the empty image
    went to the API, the API refused the request, and the step ended as an error."""
    page = _Page()
    client = _Client(page, before + [(step, 4)])
    out = _run(page, client, **kw)
    assert out["status"] == "done", out
    blocks = _result_after(client, len(before))
    assert not [b for b in blocks if b.get("type") == "image"], blocks
    assert any(NOTE in b.get("text", "") for b in blocks), blocks
    assert any(lv == "WARN" and "instead of sending an empty picture" in m
               for lv, m in logs), logs


@pytest.mark.parametrize("name,before,step,kw", BRANCHES, ids=[b[0] for b in BRANCHES])
def test_one_more_try_brings_the_picture_back(logs, name, before, step, kw):
    """Both of `Browser.screenshot`'s tries time out, and the one more try
    works: the model gets that picture, not the words."""
    page = _Page()
    client = _Client(page, before + [(step, 2)])
    out = _run(page, client, **kw)
    assert out["status"] == "done", out
    blocks = _result_after(client, len(before))
    images = [b for b in blocks if b.get("type") == "image"]
    assert [b["source"]["data"] for b in images] == [
        research.base64.b64encode(RETRY_PNG).decode("ascii")], blocks
    assert not any(NOTE in b.get("text", "") for b in blocks)
    assert not any("instead of sending an empty picture" in m for _lv, m in logs)


def test_a_good_screenshot_is_sent_as_is_and_not_taken_twice(logs):
    """The common case costs nothing: one screenshot per step, sent unchanged."""
    page = _Page()
    client = _Client(page, [(CLICK, 0)])
    out = _run(page, client)
    assert out["status"] == "done"
    blocks = _result_after(client, 0)
    assert [b["source"]["data"] for b in blocks if b.get("type") == "image"] == [
        research.base64.b64encode(PNG).decode("ascii")]
    # the first picture + the one after the click
    assert page.calls == 2
