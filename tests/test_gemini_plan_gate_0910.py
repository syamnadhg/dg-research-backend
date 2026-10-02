"""The plan verdict's vocabulary (2026-09-10).

⛔⛔ WAVE 15 (10-02): THE [2D] PLAN GATE THIS FILE PINNED IS GONE. The plan wait
no longer re-drafts a plan, and the early "couldn't start" card and its timing
rule (`_gemini_plan_card_due`) went with it: Gemini starts its research by itself
on a timer, and the owner said "wait for the research without refreshing and then
let the research finish … keep it simple without making it complicated and
causing alerts" (tests/test_w15_gemini_waits_1002.py). The wiring and ordering
tests of that loop were deleted with the loop.

What stays is `_gemini_plan_verdict`, which the send path's failed-turn re-draft
still asks (`_gemini_retry_failed_turn`) — and its vocabulary, pinned below.
"""

from __future__ import annotations

import research


VERDICTS = {"researching", "ready", "failed", "drafting", "silent"}


def test_the_verdict_vocabulary_is_exactly_the_five_the_consumer_knows():
    """⛔ THE CONSUMER'S GATE IS A SINGLE EQUALITY (`!= "failed"`), so a sixth
    verdict would be handled by nothing at all and read as "leave it alone" —
    silently, on whichever state someone added it for. Run over the whole
    input matrix: the vocabulary must not grow without this failing, and all
    five must be reachable, because an unreachable verdict is a branch the
    consumer is carrying for nothing."""
    seen = set()
    for started in (False, True):
        for present in (False, True):
            for streaming in (False, True):
                for text in ("Sorry, something went wrong.",
                             "Here is your research plan.",
                             ""):
                    seen.add(research._gemini_plan_verdict(
                        research_started=started, start_present=present,
                        streaming=streaming, latest_text=text))
    assert seen == VERDICTS, f"vocabulary drifted: {seen ^ VERDICTS}"
