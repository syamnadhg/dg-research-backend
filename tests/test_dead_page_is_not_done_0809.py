"""A page that is GONE must never be reported as a finished answer.

WHAT HAPPENED

2026-08-09, P1. ChatGPT ran deep research for 55 minutes — 139 URLs, 8 steps, 139
searches, the activity panel tracking normally the whole way. Then the tab reached
`about:blank`, and the pipeline said this:

    16:57:21  panel-miss snapshot: {"frames": ["about:blank"]}
    16:57:22  DOM says not generating after 3277s — scrolling + CUA visual confirm...
    16:57:30  CUA: "the screen is completely white/blank ... no chat interface, no
              composer, no response, no Stop button, no loading indicators"
              CONCLUSION: DONE
    16:57:33  Response complete (3289s)
    16:57:36  HTML->MD miss: tried=21 sels, matched=0, biggest_html_len=0
    16:57:36  Phase 1: brief generated but extraction empty (0 chars)

The visual check was not wrong about what it saw. It listed the absence of every
element — including the composer, which is present on a FINISHED page and absent
on a dead one — and still concluded DONE, because the code offered it only two
answers. "Not still generating" fell through to "complete".

WHY THE TESTS DID NOT CATCH IT

The wave that introduced this shipped 14 fixes and 9 new test files, all green.
Every one asserted a path somebody had thought of. None asked "what if the page is
gone?", so the third state did not exist to be tested.

These tests exercise the REAL `_page_is_dead` against page doubles, and assert the
polarity in both directions: a dead page must be refused, and a live one must not
be — a guard that rejects everything would pass a one-sided test and break every
run.
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _research():
    """Import research.py without paying for its heavy optional imports."""
    import importlib
    return importlib.import_module("research")


class _Page:
    """A page double shaped like the parts `_page_is_dead` actually touches."""

    def __init__(self, url="https://chatgpt.com/c/abc", closed=False,
                 body=True, eval_raises=None, url_raises=False, closed_raises=False):
        self._url = url
        self._closed = closed
        self._body = body
        self._eval_raises = eval_raises
        self._url_raises = url_raises
        self._closed_raises = closed_raises

    def is_closed(self):
        if self._closed_raises:
            raise RuntimeError("target crashed")
        return self._closed

    @property
    def url(self):
        if self._url_raises:
            raise RuntimeError("no url")
        return self._url

    async def evaluate(self, _expr):
        if self._eval_raises is not None:
            raise self._eval_raises
        return self._body


def _dead(page):
    return asyncio.run(_research()._page_is_dead(page))


# ── the exact live failure ──────────────────────────────────────────────────

def test_the_about_blank_tab_from_the_live_failure_is_dead():
    """The precise state of the 2026-08-09 run: the tab had navigated away."""
    assert _dead(_Page(url="about:blank")) is not None


def test_the_reason_names_what_is_wrong_rather_than_just_failing():
    """The operator reading the log has to be able to tell a dead tab from an empty
    answer — those have different causes and different fixes, and conflating them
    is what produced a 55-minute run ending in 0 chars."""
    reason = _dead(_Page(url="about:blank"))
    assert "about:blank" in reason, reason


# ── the other ways a page stops existing ────────────────────────────────────

@pytest.mark.parametrize("page,what", [
    (_Page(closed=True), "closed tab"),
    (_Page(url=""), "no address"),
    (_Page(url="about:srcdoc"), "another about: surface"),
    (_Page(url="chrome-error://chromewebdata/"), "a navigation error page"),
    (_Page(body=False), "a document with no body"),
    # ⭐ 2026-08-10 (self-review). The first version listed the bad prefixes —
    # `about:` and `chrome-error` — and let every other non-http surface through
    # while its own docstring promised "any non-http surface". These five are the
    # ones the list silently passed. It is the same defect the check exists to
    # fix, one level up: an enumeration of the failures somebody had already seen.
    (_Page(url="chrome://new-tab-page"), "an internal chrome page"),
    (_Page(url="file:///Users/x/tmp.html"), "a local file"),
    (_Page(url="data:text/html,<p>x"), "a data URL"),
    (_Page(url="blob:https://chatgpt.com/abc-123"), "a blob URL"),
    (_Page(url="view-source:https://chatgpt.com/c/abc"), "a view-source surface"),
])
def test_every_shape_of_gone_is_refused(page, what):
    assert _dead(page) is not None, what


@pytest.mark.parametrize("page,what", [
    (_Page(closed_raises=True), "is_closed() itself throws"),
    (_Page(url_raises=True), "reading .url throws"),
    (_Page(eval_raises=RuntimeError("Target closed")), "evaluate throws"),
])
def test_a_page_that_cannot_be_INSPECTED_is_treated_as_gone(page, what):
    """Fail closed. If we cannot tell whether the page is alive, the one thing we
    must not do is call it a finished answer — the cost of being wrong is a run
    reported complete with nothing in it, which is the failure this exists to end.
    """
    assert _dead(page) is not None, what


# ── polarity: a live page must NOT be refused ───────────────────────────────

@pytest.mark.parametrize("url", [
    "https://chatgpt.com/c/abc123",
    "https://gemini.google.com/app/xyz",
    "https://claude.ai/chat/abc",
    "https://notebooklm.google.com/notebook/1",
    "http://localhost:3000/x",
])
def test_a_live_page_is_not_refused(url):
    """The half a one-sided test would miss. A guard that calls everything dead
    passes every assertion above and breaks every run — it would turn each phase
    into an immediate abort, which is worse than the bug it replaced."""
    assert _dead(_Page(url=url)) is None, url


def test_a_live_page_is_not_refused_merely_for_a_long_url_or_query():
    assert _dead(_Page(url="https://chatgpt.com/c/abc?utm_source=x#frag")) is None


def test_the_rule_is_MUST_BE_HTTP_not_a_list_of_known_bad_prefixes():
    """The polarity that keeps the broadened check honest.

    Written as "must be http(s)" the guard is closed by construction: a surface
    nobody has thought of yet is refused, because it is not an answer page. Any
    future edit back toward a prefix list re-opens exactly the hole above, and
    this is the pair that says so — an unknown scheme is dead, and plain http is
    not (the local bridge and the emulator both serve it)."""
    assert _dead(_Page(url="wss://example.invalid/socket")) is not None
    assert _dead(_Page(url="devtools://devtools/bundled/x.html")) is not None
    assert _dead(_Page(url="http://localhost:8765/x")) is None


# ── the guard is actually WIRED into the completion path ────────────────────

def test_the_poll_loop_checks_liveness_before_trusting_not_generating():
    """Presence in the file is not enough — it has to run BEFORE the branch that
    reads "not generating" as done. The visual confirm sits inside that branch and
    argues FOR completion when the screen is blank, so a check placed after it
    would be satisfied by the bug.
    """
    src = Path(_research().__file__).read_text(encoding="utf-8")
    start = src.index("        if not generating:")
    # The window from the branch opening to the visual-confirm log line.
    window = src[start:src.index("DOM says not generating after", start)]
    assert "_page_is_dead(page)" in window, (
        "the liveness check must run inside `if not generating:` and before the "
        "CUA visual confirm, or a dead page still reaches the code that declares it done"
    )
    assert "return False" in window, (
        "a dead page must abort the poll, not fall through to the completion path"
    )


def test_the_dead_page_branch_does_not_return_True():
    """`return True` is this function's "complete" signal. The dead-page branch must
    never reach it."""
    src = Path(_research().__file__).read_text(encoding="utf-8")
    start = src.index("            _dead = await _page_is_dead(page)")
    branch = src[start:start + 700]
    head = branch[:branch.index("consecutive_not_generating += 1")]
    assert "return True" not in head, head
