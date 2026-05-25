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
        """Exact card text from the user's E2E image (Avengers run)."""
        from research import _GEMINI_RESEARCH_CARD_RE
        s = "Researching 25 sources..."
        assert _GEMINI_RESEARCH_CARD_RE.search(s)

    def test_no_digit_websites_variant_matches(self):
        """User-observed 2026-05-24 Salaar E2E: Gemini's card emitted
        'Researching websites...' (no number) ~28 times. The detector
        MUST match this variant — historical regex requiring `\\d+`
        missed it entirely and the kickoff stall went undetected."""
        from research import _GEMINI_RESEARCH_CARD_RE
        s = "Researching websites..."
        assert _GEMINI_RESEARCH_CARD_RE.search(s)

    @pytest.mark.parametrize("text", [
        # Original digit + sources/source variants
        "Researching 1 source",
        "Researching 42 sources",
        "researching 100 sources",  # lowercase
        "Researching  25  sources",  # extra spaces
        # New: no-digit variants (today's bug class)
        "Researching websites",
        "Researching sources",
        "Researching searches",
        "Researching sites",
        # New: digit + alt-noun variants (mirrors scrape_progress_gemini)
        "Researching 12 websites",
        "Researching 3 searches",
        "Researching 7 sites",
    ])
    def test_card_variants_match(self, text):
        from research import _GEMINI_RESEARCH_CARD_RE
        assert _GEMINI_RESEARCH_CARD_RE.search(text), f"should match: {text!r}"

    @pytest.mark.parametrize("text", [
        "Researching the topic",   # noun not in allowlist
        "Found sources",            # no "Researching" prefix
        "Research started",         # not the canonical card text
        "Researching",              # noun missing entirely
        "Re-searching websites",    # different word (hyphen)
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
    the verbatim nudge string + right platform key + correct attempt-
    indexed wording. Mock paste_followup so we don't hit a real composer."""

    def test_default_attempt_uses_first_nudge(self):
        """No attempt_idx argument → defaults to 0 → polite directive."""
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
        assert "kickoff-nudge-1" in kwargs.get("label", "")

    def test_paste_followup_failure_propagates(self):
        """If paste_followup fails (no composer), return False."""
        import research
        page = mock.AsyncMock()
        with mock.patch.object(research, "paste_followup",
                               new=mock.AsyncMock(return_value=False)):
            result = _run(research._gemini_send_kickoff_nudge(page, "Gemini"))
        assert result is False


# ─────────────────────────────────────────────────────────────────────
# Escalating wording across multi-shot attempts
# ─────────────────────────────────────────────────────────────────────

class TestGeminiMultiShotNudgeWording:
    """Multi-shot nudges escalate wording across attempts to defend
    against Gemini ignoring a repeated polite phrasing. Attempt 0 is
    the polite directive, attempt 1 is a yes/no check-in question,
    attempt 2 mirrors the terse 'Done?' that empirically jolted Gemini
    in the user's manual intervention (2026-05-24)."""

    @pytest.mark.parametrize("attempt_idx,expected_text", [
        (0, "Please proceed with the deep research now."),
        (1, "Are you researching?"),
        (2, "Done?"),
    ])
    def test_attempt_wording(self, attempt_idx, expected_text):
        """Each attempt index maps to its verbatim wording."""
        import research
        page = mock.AsyncMock()
        with mock.patch.object(research, "paste_followup",
                               new=mock.AsyncMock(return_value=True)) as pf:
            _run(research._gemini_send_kickoff_nudge(page, "Gemini",
                                                     attempt_idx=attempt_idx))
        args, kwargs = pf.call_args
        assert args[1] == expected_text
        # Label includes 1-indexed attempt number for log readability
        assert f"kickoff-nudge-{attempt_idx + 1}" in kwargs.get("label", "")

    def test_attempt_idx_beyond_list_clamps_to_last(self):
        """Defensive clamp — attempt_idx=99 (caller bug) still produces
        the last wording rather than IndexError."""
        import research
        page = mock.AsyncMock()
        with mock.patch.object(research, "paste_followup",
                               new=mock.AsyncMock(return_value=True)) as pf:
            _run(research._gemini_send_kickoff_nudge(page, "Gemini", attempt_idx=99))
        args, _ = pf.call_args
        assert args[1] == "Done?"

    def test_attempt_idx_negative_clamps_to_first(self):
        """Defensive clamp — negative attempt_idx (caller bug) falls
        back to the first wording."""
        import research
        page = mock.AsyncMock()
        with mock.patch.object(research, "paste_followup",
                               new=mock.AsyncMock(return_value=True)) as pf:
            _run(research._gemini_send_kickoff_nudge(page, "Gemini", attempt_idx=-5))
        args, _ = pf.call_args
        assert args[1] == "Please proceed with the deep research now."

    def test_nudge_list_has_three_entries(self):
        """The constant should have exactly 3 entries. Adding/removing
        nudges changes the multi-shot fan-out — this is an alarm test."""
        from research import _GEMINI_KICKOFF_NUDGES
        assert len(_GEMINI_KICKOFF_NUDGES) == 3
