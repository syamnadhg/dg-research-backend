"""#743 — Gemini Pro-tier false-alarm fix: a vision "free" verdict for Gemini
is cross-checked against a full-document DOM read and FAILS OPEN.

Root cause: Gemini's Advanced badge is off-screen (collapsed sidebar), so the
composer screenshot the vision model judges looks free even on a paid account
(after DR setup it reads "Gemini" + Flash — exactly the prompt's FREE signals).
A vision "free" must NOT raise the blocking pro_required alert on its own —
only a clear DOM upsell CTA confirms genuine free; otherwise assume Pro
(return 'unsure', no alert). ChatGPT/Claude are unaffected (their Pro badge is
on-screen and reads reliably).

Run:  pytest tests/test_gemini_pro_failopen.py -v
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


class _Blk:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Blk(text)]


class _FakeMessages:
    def __init__(self, verdicts):
        self._verdicts = list(verdicts)
        self.calls = []

    def create(self, **kw):  # sync — called via asyncio.to_thread
        self.calls.append(kw)
        return _Resp(self._verdicts.pop(0) if self._verdicts else "")


class _FakeClient:
    def __init__(self, verdicts):
        self.messages = _FakeMessages(verdicts)


class _FakePage:
    """screenshot() returns bytes; evaluate() returns the configured DOM-tier
    dict — i.e. what _gemini_dom_tier's page.evaluate would yield for a given
    account state."""
    def __init__(self, dom_tier):
        self.shots = 0
        self.evals = 0
        self._dom_tier = dom_tier

    async def screenshot(self, **kw):
        self.shots += 1
        return b"FAKE_PNG_BYTES"

    async def evaluate(self, js, *a):
        self.evals += 1
        return dict(self._dom_tier)


def _run(platform, verdicts, dom_tier):
    page = _FakePage(dom_tier)
    client = _FakeClient(verdicts)
    result = asyncio.run(research._cua_pro_tier_call(page, platform, client))
    return result, page


# DOM-tier dict shapes returned by _gemini_dom_tier's page.evaluate
_NO_SIGNAL = {"upsell": False, "proMark": False, "upsellText": "", "proText": "", "dump": []}
_UPSELL = {"upsell": True, "proMark": False, "upsellText": "Get Gemini Advanced", "proText": "", "dump": ["Get Gemini Advanced"]}
_PROMARK = {"upsell": False, "proMark": True, "upsellText": "", "proText": "Gemini Advanced", "dump": ["Gemini Advanced"]}


def test_gemini_free_with_no_dom_signal_fails_open():
    # Paid account, Advanced badge off-screen → vision says "free", DOM finds
    # no upsell CTA → 'unsure' (fail open, NO alert). This is the exact bug the
    # user hit on BOTH workers.
    result, page = _run("gemini", ["free"], _NO_SIGNAL)
    assert result == "unsure"
    assert page.evals == 1  # the DOM cross-check ran


def test_gemini_free_with_dom_upsell_is_free():
    # Genuine free account: vision "free" + a clear "Get Gemini Advanced" CTA
    # in the DOM → 'free' (the warning is real).
    result, _ = _run("gemini", ["free"], _UPSELL)
    assert result == "free"


def test_gemini_free_but_dom_promark_is_pro():
    # Vision misread "free" but the DOM shows the Advanced plan label → trust
    # the DOM and return 'pro'.
    result, _ = _run("gemini", ["free"], _PROMARK)
    assert result == "pro"


def test_gemini_pro_verdict_skips_dom_crosscheck():
    # A clear "pro" vision verdict short-circuits before any DOM read.
    result, page = _run("gemini", ["pro"], _NO_SIGNAL)
    assert result == "pro"
    assert page.evals == 0


def test_chatgpt_free_with_no_dom_signal_fails_open():
    # #751 (2026-06-02): ChatGPT now gets the SAME DOM cross-check as Gemini.
    # A paid account whose Pro marker is off-screen (vision says "free") finds
    # no upsell CTA in the DOM → 'unsure' (fail open, NO pro_required alert).
    # This is the exact false-alarm the user hit on the 2026-06-02 E2E.
    result, page = _run("chatgpt", ["free"], _NO_SIGNAL)
    assert result == "unsure"
    assert page.evals == 1  # the DOM cross-check ran for chatgpt too


def test_chatgpt_free_with_dom_upsell_is_free():
    # Genuine free ChatGPT account: vision "free" + a clear upsell CTA in the
    # DOM → 'free' (the alert is real).
    result, _ = _run("chatgpt", ["free"], _UPSELL)
    assert result == "free"


def test_claude_free_is_unaffected_by_failopen():
    # Claude's Opus badge is on-screen and reads reliably, so a vision "free"
    # is still trusted directly with NO DOM cross-check.
    result, page = _run("claude", ["free"], _NO_SIGNAL)
    assert result == "free"
    assert page.evals == 0


def test_gemini_dom_tier_helper_exists():
    assert hasattr(research, "_gemini_dom_tier"), (
        "_gemini_dom_tier must exist as the authoritative DOM tier read (#743)."
    )
