"""Tests for #724 item 2 — Pro/Free vision-verdict heavy-model escalation.

`_cua_pro_tier_call` returns 'pro'|'free'|'unsure'. Pre-fix, an ambiguous
LIGHT-model verdict ('unsure') was returned immediately (caller assumes Pro,
fail-open). Now an unsure light verdict triggers ONE escalated re-read on the
heavy model (a fresh screenshot after a short settle), mirroring
verify_login_cua's attempts>=2 rule. heavy=True passes never recurse.

Run:  pytest tests/test_pro_tier_heavy_escalation.py -v
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
        text = self._verdicts.pop(0) if self._verdicts else ""
        return _Resp(text)


class _FakeClient:
    def __init__(self, verdicts):
        self.messages = _FakeMessages(verdicts)


class _FakePage:
    def __init__(self, dom_tier=None):
        self.shots = 0
        self.evals = 0
        # Default = no DOM signal (no upsell, no pro marker) so the #751 ChatGPT
        # DOM cross-check on a vision-"free" verdict fails OPEN to 'unsure'.
        self._dom_tier = dom_tier or {
            "upsell": False, "proMark": False, "modelPro": False,
            "upsellText": "", "proText": "", "dump": [],
        }

    async def screenshot(self, **kw):
        self.shots += 1
        return b"FAKE_PNG_BYTES"

    async def evaluate(self, js, *a):
        self.evals += 1
        return dict(self._dom_tier)


def _run(verdicts, heavy=False, dom_tier=None, platform="chatgpt"):
    page = _FakePage(dom_tier)
    client = _FakeClient(verdicts)
    result = asyncio.run(research._cua_pro_tier_call(page, platform, client, heavy=heavy))
    return result, client.messages.calls, page.shots


# The light→heavy escalation mechanism applies to Claude/Gemini (their badges
# read cleanly on the cheap model, so the light fast-path is worth keeping).
# ChatGPT deliberately SKIPS the light pass (see test_chatgpt_skips_light below),
# so these mechanism tests use "claude".
def test_unsure_light_escalates_to_heavy_and_resolves():
    # Light says junk (unsure) → heavy says pro → final 'pro', two calls.
    result, calls, shots = _run(["maybe?", "pro"], platform="claude")
    assert result == "pro"
    assert len(calls) == 2
    assert calls[0]["model"] == research.VISION_LIGHT_MODEL
    assert calls[1]["model"] == research.VISION_HEAVY_MODEL
    assert shots == 2  # fresh screenshot for the heavy re-read


def test_clear_pro_does_not_escalate():
    result, calls, shots = _run(["pro and clearly so"], platform="claude")
    assert result == "pro"
    assert len(calls) == 1
    assert calls[0]["model"] == research.VISION_LIGHT_MODEL
    assert shots == 1


def test_chatgpt_skips_light_and_reads_on_heavy_directly():
    # ChatGPT skips the cheap light pre-check (Sonnet reliably preambles →
    # always 'unsure' → always escalates) and reads tier directly on the heavy
    # (Opus) model: ONE call, no escalation, no wasted Sonnet pass.
    result, calls, shots = _run(["pro"], platform="chatgpt")
    assert result == "pro"
    assert len(calls) == 1
    assert calls[0]["model"] == research.VISION_HEAVY_MODEL  # Opus directly, not Sonnet
    assert shots == 1


def test_clear_free_does_not_escalate_to_heavy():
    # #751: a clear ChatGPT "free" no longer escalates to the HEAVY vision model
    # (still ONE messages.create call) — but it now diverts to the DOM
    # cross-check, which with no upsell CTA fails OPEN to 'unsure' (no false
    # pro_required alert). The heavy-escalation contract this file guards is
    # intact: free never triggers a 2nd vision call.
    result, calls, _ = _run(["free tier"])
    assert result == "unsure"
    assert len(calls) == 1


def test_clear_free_with_dom_upsell_is_free():
    # A genuine free account (vision "free" + DOM upsell CTA) still returns
    # 'free' without any heavy escalation.
    result, calls, _ = _run(
        ["free tier"],
        dom_tier={"upsell": True, "proMark": False, "modelPro": False,
                  "upsellText": "Upgrade to ChatGPT Plus", "proText": "", "dump": []},
    )
    assert result == "free"
    assert len(calls) == 1


def test_heavy_unsure_does_not_recurse():
    # Entering with heavy=True and an unsure verdict must NOT recurse.
    result, calls, _ = _run(["dunno"], heavy=True)
    assert result == "unsure"
    assert len(calls) == 1
    assert calls[0]["model"] == research.VISION_HEAVY_MODEL


def test_unsure_both_passes_returns_unsure():
    # Light unsure → heavy also unsure → fail-open 'unsure', two calls.
    result, calls, _ = _run(["???", "still not sure"], platform="claude")
    assert result == "unsure"
    assert len(calls) == 2
    assert calls[1]["model"] == research.VISION_HEAVY_MODEL
