"""Claude P2 clarification auto-reply tests.

Covers the three new helpers added 2026-05-18:
  - _CLAUDE_CLARIFICATION_SIGNOFF_RE: regex that gates the auto-reply
  - _claude_asking_clarification(page): DOM read + tail-match
  - _claude_send_clarification_reply(page, label): type + submit

Run via:
    pytest tests/test_claude_clarification.py -v
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
# _CLAUDE_CLARIFICATION_SIGNOFF_RE
# ─────────────────────────────────────────────────────────────────────

class TestClaudeClarificationSignoffRegex:
    """The regex is the 5th condition gating the auto-reply. False-positive
    risk = mis-firing on real research output. False-negative cost = falling
    back to today's manual-operator path (acceptable). Skew toward strict."""

    def test_user_image_phrasing_matches(self):
        """The exact sign-off from the user's E2E image (claude.ai chat):
        'Once you clarify, I'll launch into the research right away.'"""
        from research import _CLAUDE_CLARIFICATION_SIGNOFF_RE
        s = "Once you clarify, I'll launch into the research right away."
        assert _CLAUDE_CLARIFICATION_SIGNOFF_RE.search(s)

    @pytest.mark.parametrize("text", [
        # Variations of the "Once you X, I'll Y the research" pattern
        "Once you confirm the details, I will start the deep research.",
        "Once you share more context, I'll dive into the research.",
        "Once you provide the specific markets, I'll begin the research.",
        "Once you tell me, I will kick off the deep research.",
        # "Let me know" opener
        "Let me know which option you prefer and I'll dive into the research.",
        # "With those" opener
        "With those answers, I'll kick off the research.",
        "With those clarifications, I will launch the research.",
        # Typo-tolerant: "Once clarify" without "you" (user's example phrasing)
        "Once clarify, I'll launch into the research right away.",
    ])
    def test_positive_phrasings_match(self, text):
        from research import _CLAUDE_CLARIFICATION_SIGNOFF_RE
        assert _CLAUDE_CLARIFICATION_SIGNOFF_RE.search(text), f"should match: {text!r}"

    @pytest.mark.parametrize("text", [
        # Mid-research / non-clarification — must NOT match
        "I'll start with the analysis of X.",                  # no "once you" / "let me know" opener
        "I'll launch into a brief discussion.",                 # no "research" anchor
        "Here is the research I found.",                        # no "I'll {action}"
        "What do you think? Should we proceed?",                # no sign-off structure
        "Let me know if you want me to expand. I'll start the analysis.",  # no "research" anchor
        "I have a few questions but I'll proceed with the research.",      # no "once you" opener
        # Punctuation-breaking gap: "?" between opener and I'll → must not match
        # because [^.!?] gap is broken
        "Could you tell me which markets? Then I'll start the research.",
    ])
    def test_negative_phrasings_dont_match(self, text):
        from research import _CLAUDE_CLARIFICATION_SIGNOFF_RE
        assert not _CLAUDE_CLARIFICATION_SIGNOFF_RE.search(text), f"should NOT match: {text!r}"

    def test_curly_apostrophe_in_ill_matches(self):
        """Claude sometimes uses U+2019 right-single-quotation-mark in
        contractions instead of ASCII apostrophe. Regex permits both."""
        from research import _CLAUDE_CLARIFICATION_SIGNOFF_RE
        s = "Once you clarify, I’ll launch into the research."
        assert _CLAUDE_CLARIFICATION_SIGNOFF_RE.search(s)


# ─────────────────────────────────────────────────────────────────────
# _claude_asking_clarification (DOM read + regex)
# ─────────────────────────────────────────────────────────────────────

class TestClaudeAskingClarification:
    """Lightweight wrapper around _CLAUDE_CLARIFICATION_SIGNOFF_RE that
    reads the last assistant message text via page.evaluate. Tests mock
    page.evaluate to return canned text."""

    def test_matched_when_signoff_in_tail(self):
        from research import _claude_asking_clarification
        text = (
            "Hi! The brief you've shared is a generic template. I need a bit "
            "more from you before I can dig in:\n\n"
            "1. What is the actual research topic?\n"
            "2. Are there source documents?\n"
            "3. Any specific scope?\n\n"
            "Once you clarify, I'll launch into the research right away."
        )
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value=text)
        matched, last_text, q_count = _run(_claude_asking_clarification(page))
        assert matched is True
        assert last_text == text
        assert q_count == 3  # 3 question marks

    def test_no_signoff_returns_false(self):
        """Text without clarification sign-off should not match."""
        from research import _claude_asking_clarification
        text = "Here are my preliminary findings. The market is large."
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value=text)
        matched, last_text, q_count = _run(_claude_asking_clarification(page))
        assert matched is False
        assert q_count == 0

    def test_empty_dom_returns_false(self):
        """Empty page.evaluate result (no assistant message yet)."""
        from research import _claude_asking_clarification
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value="")
        matched, last_text, q_count = _run(_claude_asking_clarification(page))
        assert matched is False
        assert last_text == ""
        assert q_count == 0

    def test_evaluate_exception_returns_false(self):
        """Page evaluation failure should not crash — return false-tuple."""
        from research import _claude_asking_clarification
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(side_effect=Exception("page closed"))
        matched, last_text, q_count = _run(_claude_asking_clarification(page))
        assert matched is False

    def test_signoff_buried_mid_text_doesnt_match_outside_tail(self):
        """The regex matches against the last 600 chars. Verify a sign-off
        in the FIRST 100 chars of a 2000-char message is NOT matched
        (because the tail window won't include it)."""
        from research import _claude_asking_clarification
        # Sign-off at start, 1500 chars of filler after → falls outside the
        # 600-char tail window. Filler intentionally avoids the regex
        # opener patterns ("once you", "let me know", "with those")
        # AND the "I'll {action} ... research" sequence so a fresh tail
        # match can't fire.
        filler = "Here are detailed findings on multiple market segments. " * 30
        text = (
            "Once you clarify, I'll launch the research. " + filler
        )
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value=text)
        matched, _, _ = _run(_claude_asking_clarification(page))
        assert matched is False, "signoff outside tail window should not match"


# ─────────────────────────────────────────────────────────────────────
# _claude_send_clarification_reply (type + submit)
# ─────────────────────────────────────────────────────────────────────

class TestClaudeSendClarificationReply:
    """The auto-reply sender. Tries composer selectors in order, then
    Send-button selectors in order (mirror paste_followup at
    research.py:5170), with Enter fallback if no button is enabled."""

    def _mk_page(self, composer_sel=None, button_sel=None, button_enabled=True):
        """Build a mock page where:
          - query_selector returns a truthy element ONLY for composer_sel
            and button_sel; everything else returns None.
          - The button mock's is_enabled() returns button_enabled.
          - click() / type() / press() / etc. are AsyncMocks."""
        page = mock.AsyncMock()

        composer_el = mock.AsyncMock()
        composer_el.click = mock.AsyncMock()

        button_el = mock.AsyncMock()
        button_el.click = mock.AsyncMock()
        button_el.is_enabled = mock.AsyncMock(return_value=button_enabled)

        async def _query(sel):
            if sel == composer_sel:
                return composer_el
            if sel == button_sel:
                return button_el
            return None

        page.query_selector = _query
        page.keyboard = mock.AsyncMock()
        page.keyboard.type = mock.AsyncMock()
        page.keyboard.press = mock.AsyncMock()
        return page, composer_el, button_el

    def test_happy_path_send_button(self):
        """Composer found via div[contenteditable], Send button found via
        data-testid — Enter not pressed (button-first wins)."""
        from research import _claude_send_clarification_reply
        page, composer_el, button_el = self._mk_page(
            composer_sel='div[contenteditable="true"]',
            button_sel='button[data-testid="send-button"]',
        )
        result = _run(_claude_send_clarification_reply(page, "Claude"))
        assert result is True
        composer_el.click.assert_awaited()
        page.keyboard.type.assert_awaited_once()
        button_el.click.assert_awaited_once()
        page.keyboard.press.assert_not_awaited()

    def test_enter_fallback_when_no_button(self):
        """No Send button found → falls back to Enter."""
        from research import _claude_send_clarification_reply
        page, composer_el, _ = self._mk_page(
            composer_sel='.ProseMirror',
            button_sel=None,  # No button matched
        )
        result = _run(_claude_send_clarification_reply(page, "Claude"))
        assert result is True
        composer_el.click.assert_awaited()
        page.keyboard.type.assert_awaited_once()
        page.keyboard.press.assert_awaited_once_with("Enter")

    def test_disabled_button_falls_through_to_enter(self):
        """Send button present but disabled (mid-stream / empty input) →
        Enter fallback."""
        from research import _claude_send_clarification_reply
        page, _, button_el = self._mk_page(
            composer_sel='div[contenteditable="true"]',
            button_sel='button[aria-label="Send"]',
            button_enabled=False,
        )
        result = _run(_claude_send_clarification_reply(page, "Claude"))
        assert result is True
        button_el.click.assert_not_awaited()  # disabled, skipped
        page.keyboard.press.assert_awaited_once_with("Enter")

    def test_no_composer_returns_false(self):
        """If no composer is reachable, return False and do nothing else."""
        from research import _claude_send_clarification_reply
        page, _, _ = self._mk_page(composer_sel=None, button_sel=None)
        result = _run(_claude_send_clarification_reply(page, "Claude"))
        assert result is False
        page.keyboard.type.assert_not_awaited()
        page.keyboard.press.assert_not_awaited()

    def test_exact_reply_text(self):
        """The reply must be the verbatim user-specified string —
        don't drift the wording silently."""
        from research import _claude_send_clarification_reply
        page, composer_el, _ = self._mk_page(
            composer_sel='div[contenteditable="true"]',
            button_sel='button[data-testid="send-button"]',
        )
        _run(_claude_send_clarification_reply(page, "Claude"))
        # The typed text is the first positional arg of keyboard.type
        call = page.keyboard.type.call_args
        typed = call.args[0] if call.args else call.kwargs.get("text", "")
        assert typed == "Up to Claude to decide for the best output."
