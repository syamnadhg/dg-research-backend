"""Gemini P2 kickoff-stall auto-nudge tests.

Covers the three helpers added 2026-05-24 to fix the Gemini "ACKs but
doesn't actually start research" stall (user screenshot 2026-05-22):
  - _GEMINI_KICKOFF_ACK_RE: regex matching Gemini's start-ack phrases
  - _GEMINI_RESEARCH_CARD_RE: regex matching "Researching N sources"
  - _GEMINI_COMPLETION_RE: regex matching the report-ready banner
  - _gemini_kickoff_pending(page): DOM read + combined match
  - _gemini_send_kickoff_nudge(page, label): paste_followup wrapper

Run via:
    pytest tests/test_gemini_kickoff.py -v
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
# _GEMINI_KICKOFF_ACK_RE
# ─────────────────────────────────────────────────────────────────────

class TestGeminiKickoffAckRegex:
    """ACK phrases anchor the pending check — without one of these,
    Gemini hasn't responded yet and the nudge is premature."""

    def test_user_image_ack_matches(self):
        """The exact text from the user's E2E image (gemini.google.com):
        'OK, starting now. As soon as your report is ready, I'll let you
        know. In the meantime, feel free to leave this chat.'"""
        from research import _GEMINI_KICKOFF_ACK_RE
        s = ("OK, starting now. As soon as your report is ready, I'll "
             "let you know. In the meantime, feel free to leave this chat.")
        assert _GEMINI_KICKOFF_ACK_RE.search(s)

    def test_user_image_post_nudge_ack_matches(self):
        """Second ACK after the user nudged with 'Done?': 'I'm on it.
        I'll let you know when your research is done. In the meantime,
        you can leave this chat.'"""
        from research import _GEMINI_KICKOFF_ACK_RE
        s = ("I'm on it. I'll let you know when your research is done. "
             "In the meantime, you can leave this chat.")
        assert _GEMINI_KICKOFF_ACK_RE.search(s)

    @pytest.mark.parametrize("text", [
        "OK, starting now.",
        "Starting now — I'll get back to you when the report is ready.",
        "I'll let you know when your research is done.",
        "Feel free to leave this chat.",
        "I'm on it.",
        "I’m on it.",  # curly apostrophe variant
    ])
    def test_positive_ack_phrases_match(self, text):
        from research import _GEMINI_KICKOFF_ACK_RE
        assert _GEMINI_KICKOFF_ACK_RE.search(text), f"should match: {text!r}"

    @pytest.mark.parametrize("text", [
        "Here are the research findings.",
        "I have completed the analysis of the topic.",
        "Could you clarify what you mean by 'deep research'?",
        # Don't false-fire on partial English text that isn't a kickoff ACK
        "Let me think about that for a moment.",
    ])
    def test_negative_phrases_dont_match(self, text):
        from research import _GEMINI_KICKOFF_ACK_RE
        assert not _GEMINI_KICKOFF_ACK_RE.search(text), f"should NOT match: {text!r}"


# ─────────────────────────────────────────────────────────────────────
# _GEMINI_RESEARCH_CARD_RE
# ─────────────────────────────────────────────────────────────────────

class TestGeminiResearchCardRegex:
    """The 'Researching N sources' card is the canonical 'actually
    running' signal. If it's visible, the kickoff succeeded and the
    nudge must NOT fire — false-positive cost is sending a duplicate
    follow-up that confuses Gemini."""

    def test_user_image_card_matches(self):
        """Exact card text from the user's E2E image."""
        from research import _GEMINI_RESEARCH_CARD_RE
        s = "Researching 25 sources..."
        assert _GEMINI_RESEARCH_CARD_RE.search(s)

    @pytest.mark.parametrize("text", [
        "Researching 1 source",
        "Researching 42 sources",
        "researching 100 sources",  # lowercase
        "Researching  25  sources",  # extra spaces
    ])
    def test_card_variants_match(self, text):
        from research import _GEMINI_RESEARCH_CARD_RE
        assert _GEMINI_RESEARCH_CARD_RE.search(text), f"should match: {text!r}"

    @pytest.mark.parametrize("text", [
        "Researching the topic",   # no digit
        "Found sources",            # no "Researching N"
        "Research started",         # not the canonical card text
    ])
    def test_non_card_text_doesnt_match(self, text):
        from research import _GEMINI_RESEARCH_CARD_RE
        assert not _GEMINI_RESEARCH_CARD_RE.search(text), f"should NOT match: {text!r}"


# ─────────────────────────────────────────────────────────────────────
# _GEMINI_COMPLETION_RE
# ─────────────────────────────────────────────────────────────────────

class TestGeminiCompletionRegex:
    """Suppresses the nudge if Gemini's report finished between ticks."""

    def test_completed_phrase_matches(self):
        from research import _GEMINI_COMPLETION_RE
        s = ("I've completed your research. Feel free to ask me follow-up "
             "questions or request changes.")
        assert _GEMINI_COMPLETION_RE.search(s)

    @pytest.mark.parametrize("text", [
        "completed your research",
        "Feel free to ask me follow-up questions",
        "feel free to ask me followup questions",  # hyphen variant
    ])
    def test_completion_variants_match(self, text):
        from research import _GEMINI_COMPLETION_RE
        assert _GEMINI_COMPLETION_RE.search(text), f"should match: {text!r}"


# ─────────────────────────────────────────────────────────────────────
# _gemini_kickoff_pending (DOM read + combined match)
# ─────────────────────────────────────────────────────────────────────

class TestGeminiKickoffPending:
    """Combines the three regexes against page innerText. pending=True
    iff (ACK present) AND (no card) AND (no completion)."""

    def test_ack_without_card_returns_pending(self):
        """The exact failure mode from the user's screenshot."""
        from research import _gemini_kickoff_pending
        body = ("OK, starting now. As soon as your report is ready, I'll "
                "let you know. In the meantime, feel free to leave this chat.")
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value=body)
        pending, reason = _run(_gemini_kickoff_pending(page))
        assert pending is True
        assert reason == "ack-no-card"

    def test_card_present_returns_not_pending(self):
        """Research is actually running — do NOT nudge."""
        from research import _gemini_kickoff_pending
        body = ("OK, starting now. I'll let you know when done.\n"
                "Researching 25 sources...")
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value=body)
        pending, reason = _run(_gemini_kickoff_pending(page))
        assert pending is False
        assert reason == "card-present"

    def test_completion_present_returns_not_pending(self):
        """Report already arrived — definitely don't nudge."""
        from research import _gemini_kickoff_pending
        body = ("I've completed your research. Feel free to ask me "
                "follow-up questions or request changes.")
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value=body)
        pending, reason = _run(_gemini_kickoff_pending(page))
        assert pending is False
        assert reason == "completion-present"

    def test_completion_overrides_ack_in_same_body(self):
        """If both ACK and completion phrases are in the body (e.g.,
        the full chat history including the original 'starting now'),
        completion wins — research is done."""
        from research import _gemini_kickoff_pending
        body = ("OK, starting now. I'll let you know when done.\n"
                "[... lots of research text ...]\n"
                "I've completed your research. Feel free to ask me "
                "follow-up questions.")
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value=body)
        pending, reason = _run(_gemini_kickoff_pending(page))
        assert pending is False
        assert reason == "completion-present"

    def test_card_overrides_ack(self):
        """If both ACK and card text are in the body (normal case
        during research), card wins — kickoff succeeded."""
        from research import _gemini_kickoff_pending
        body = "OK, starting now. Researching 12 sources..."
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value=body)
        pending, reason = _run(_gemini_kickoff_pending(page))
        assert pending is False
        assert reason == "card-present"

    def test_no_ack_yet_returns_not_pending(self):
        """Gemini hasn't responded yet — premature to nudge."""
        from research import _gemini_kickoff_pending
        body = "Start research\n[brief text pasted into composer]"
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value=body)
        pending, reason = _run(_gemini_kickoff_pending(page))
        assert pending is False
        assert reason == "no-ack-yet"

    def test_empty_body_returns_not_pending(self):
        from research import _gemini_kickoff_pending
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(return_value="")
        pending, reason = _run(_gemini_kickoff_pending(page))
        assert pending is False
        assert reason == "empty-body"

    def test_evaluate_exception_returns_not_pending(self):
        """Page evaluation failure should not crash — return false-tuple."""
        from research import _gemini_kickoff_pending
        page = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(side_effect=Exception("page closed"))
        pending, reason = _run(_gemini_kickoff_pending(page))
        assert pending is False
        assert reason == "evaluate-failed"


# ─────────────────────────────────────────────────────────────────────
# _gemini_send_kickoff_nudge (paste_followup wrapper)
# ─────────────────────────────────────────────────────────────────────

class TestGeminiSendKickoffNudge:
    """Thin wrapper around paste_followup — confirms it's called with
    the verbatim nudge string and the right platform key. Mock
    paste_followup so we don't hit a real composer."""

    def test_exact_nudge_text_and_platform(self):
        """The nudge must be the verbatim user-approved string —
        don't drift the wording silently."""
        import research
        page = mock.AsyncMock()
        with mock.patch.object(research, "paste_followup",
                               new=mock.AsyncMock(return_value=True)) as pf:
            result = _run(research._gemini_send_kickoff_nudge(page, "Gemini"))
        assert result is True
        pf.assert_awaited_once()
        args, kwargs = pf.call_args
        assert args[0] is page
        assert args[1] == "Please proceed with the deep research now."
        assert args[2] == "gemini"
        assert "kickoff-nudge" in kwargs.get("label", "")

    def test_paste_followup_failure_propagates(self):
        """If paste_followup fails (no composer), return False."""
        import research
        page = mock.AsyncMock()
        with mock.patch.object(research, "paste_followup",
                               new=mock.AsyncMock(return_value=False)):
            result = _run(research._gemini_send_kickoff_nudge(page, "Gemini"))
        assert result is False
