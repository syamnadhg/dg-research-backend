"""Gemini share-preview tab guard tests.

Covers `_gemini_share_closer` — the per-page event handler registered
during `extract_share_link_gemini` that closes preview tabs Gemini's
Share & Export dialog spontaneously spawns when the public-link
toggle flips.

Observed in production (BE log 2026-05-23 20:52:20): a 72.3s
extraction left 4 preview tabs visible to the user until the finally-
block snapshot diff cleaned them up. This listener closes each tab
in ~ms after its URL settles past about:blank.

Run via:
    pytest tests/test_gemini_share_preview_guard.py -v
"""
import asyncio
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────
# _gemini_share_closer (URL-matching + close logic)
# ─────────────────────────────────────────────────────────────────────

class TestGeminiShareCloser:
    """The closer reads new_page.url with a settle-poll then closes
    iff the URL matches gemini.google.com/share/* or g.co/gemini/*.
    Must NOT close any non-share gemini.google.com tab (e.g. the
    legitimate agent chat tab we drive at gemini.google.com/app/...)."""

    def _mk_page(self, url="https://gemini.google.com/share/abc123"):
        """Mock page where .url is a settable property and .close is awaitable."""
        page = mock.AsyncMock()
        page.url = url
        page.close = mock.AsyncMock()
        return page

    def test_closes_share_url(self):
        """gemini.google.com/share/* is the canonical preview-tab URL."""
        from research import _gemini_share_closer
        page = self._mk_page("https://gemini.google.com/share/3a68c698bd82")
        _run(_gemini_share_closer(page))
        page.close.assert_awaited_once()

    def test_closes_gco_gemini_url(self):
        """g.co/gemini/* is the short-link variant Gemini sometimes uses."""
        from research import _gemini_share_closer
        page = self._mk_page("https://g.co/gemini/abc123")
        _run(_gemini_share_closer(page))
        page.close.assert_awaited_once()

    def test_does_not_close_agent_chat_tab(self):
        """gemini.google.com/app/... is the legitimate agent tab we drive.
        It must NOT be closed by this listener."""
        from research import _gemini_share_closer
        page = self._mk_page("https://gemini.google.com/app/some-conversation-id")
        _run(_gemini_share_closer(page))
        page.close.assert_not_awaited()

    def test_does_not_close_non_gemini_url(self):
        """Foreign URLs (ads, social shares, etc.) are handled by the
        global popup-guard's allowlist. This listener stays narrowly
        focused on share-preview URLs only."""
        from research import _gemini_share_closer
        page = self._mk_page("https://twitter.com/intent/tweet?url=...")
        _run(_gemini_share_closer(page))
        page.close.assert_not_awaited()

    def test_about_blank_does_not_close(self):
        """A page that never settles past about:blank is not a share
        tab — leave it alone (likely a still-loading agent tab the
        caller's flow will manage)."""
        from research import _gemini_share_closer
        page = self._mk_page("about:blank")
        _run(_gemini_share_closer(page))
        page.close.assert_not_awaited()

    def test_url_read_exception_returns_silently(self):
        """If new_page.url raises (page already closed/disposed), the
        listener must not propagate the exception — return silently."""
        from research import _gemini_share_closer
        page = mock.AsyncMock()
        # Property access via PropertyMock raises
        type(page).url = mock.PropertyMock(side_effect=Exception("disposed"))
        page.close = mock.AsyncMock()
        _run(_gemini_share_closer(page))
        page.close.assert_not_awaited()

    def test_close_exception_swallowed(self):
        """If page.close itself raises (race with another close path),
        the listener must not propagate the exception."""
        from research import _gemini_share_closer
        page = self._mk_page("https://gemini.google.com/share/x")
        page.close.side_effect = Exception("already closed")
        # Should not raise
        _run(_gemini_share_closer(page))

    def test_url_settles_after_about_blank_then_closes(self):
        """Simulate the realistic case: page opens as about:blank,
        then settles to a share URL within the poll window. The
        listener must wait for the settle then close."""
        from research import _gemini_share_closer
        page = mock.AsyncMock()
        # First two reads return about:blank, then settles.
        url_sequence = iter([
            "about:blank", "about:blank",
            "https://gemini.google.com/share/late-settle",
            "https://gemini.google.com/share/late-settle",
        ])
        type(page).url = mock.PropertyMock(side_effect=lambda: next(url_sequence))
        page.close = mock.AsyncMock()
        _run(_gemini_share_closer(page))
        page.close.assert_awaited_once()

    def test_sharer_path_does_not_match(self):
        """`gemini.google.com/sharer/...` shares the substring "share"
        with the share-preview URL but is a different path entirely.
        Path-boundary check (`/share/` with trailing slash) must reject
        it. Defends against future Gemini UI paths."""
        from research import _gemini_share_closer
        page = self._mk_page("https://gemini.google.com/sharer/abc")
        _run(_gemini_share_closer(page))
        page.close.assert_not_awaited()

    def test_shared_path_does_not_match(self):
        """`gemini.google.com/shared` (e.g. 'shared with me' section)
        must not be closed — `/share/` boundary keeps it distinct."""
        from research import _gemini_share_closer
        page = self._mk_page("https://gemini.google.com/shared")
        _run(_gemini_share_closer(page))
        page.close.assert_not_awaited()

    def test_foreign_url_with_share_substring_does_not_match(self):
        """A foreign URL embedding the share-link as a query parameter
        (e.g. `reddit.com/submit?url=https://gemini.google.com/share/x`)
        must NOT be closed by our host+path check. The reddit.com host
        fails the host equality test."""
        from research import _gemini_share_closer
        page = self._mk_page(
            "https://www.reddit.com/submit?url=https%3A%2F%2Fgemini.google.com%2Fshare%2Fx"
        )
        _run(_gemini_share_closer(page))
        page.close.assert_not_awaited()

    def test_share_url_with_query_string_matches(self):
        """Share URLs with utm tracking, fragment anchors, or other
        query strings must still match. Path-boundary check only
        looks at the URL path, not the query/fragment."""
        from research import _gemini_share_closer
        page = self._mk_page(
            "https://gemini.google.com/share/abc?utm_source=share&utm_medium=link#section"
        )
        _run(_gemini_share_closer(page))
        page.close.assert_awaited_once()
