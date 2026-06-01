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
    def __init__(self):
        self.shots = 0

    async def screenshot(self, **kw):
        self.shots += 1
        return b"FAKE_PNG_BYTES"


def _run(verdicts, heavy=False):
    page = _FakePage()
    client = _FakeClient(verdicts)
    result = asyncio.run(research._cua_pro_tier_call(page, "chatgpt", client, heavy=heavy))
    return result, client.messages.calls, page.shots


def test_unsure_light_escalates_to_heavy_and_resolves():
    # Light says junk (unsure) → heavy says pro → final 'pro', two calls.
    result, calls, shots = _run(["maybe?", "pro"])
    assert result == "pro"
    assert len(calls) == 2
    assert calls[0]["model"] == research.VISION_LIGHT_MODEL
    assert calls[1]["model"] == research.VISION_HEAVY_MODEL
    assert shots == 2  # fresh screenshot for the heavy re-read


def test_clear_pro_does_not_escalate():
    result, calls, shots = _run(["pro and clearly so"])
    assert result == "pro"
    assert len(calls) == 1
    assert calls[0]["model"] == research.VISION_LIGHT_MODEL
    assert shots == 1


def test_clear_free_does_not_escalate():
    result, calls, _ = _run(["free tier"])
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
    result, calls, _ = _run(["???", "still not sure"])
    assert result == "unsure"
    assert len(calls) == 2
    assert calls[1]["model"] == research.VISION_HEAVY_MODEL
