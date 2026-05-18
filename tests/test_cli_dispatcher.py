"""CLI dispatcher tests for the claude_chat_mode pause regression (DGOPS-7710).

Covers the F6 regression in PR #2 where Phase 2B's claude_chat_mode
pause's `r` (resume) and `s` (skip) keypresses released `wait_if_paused`
but the downstream `await_agent_decision` coroutine hung indefinitely.
The dispatcher only called `request_resume` / `request_skip_phase`, but
await_agent_decision (research.py:4274) polls for `consume_continue_anyway`
/ `consume_retry_agent` / `skipped_agents`, NOT phase-level flags.

Fix (research.py:3781-3815 dispatcher): `r` at claude_chat_mode now calls
`set_continue_anyway()`; `s` at claude_chat_mode now calls
`request_skip_agent("claude")`. Both before `request_resume()`.

Tests below verify:
  (a) Controls contract — set_continue_anyway / request_skip_agent set
      the state await_agent_decision consumes.
  (b) Integration — await_agent_decision on a live event loop returns
      'continue_anyway' / 'skip' when the corresponding signal fires
      (mirrors Jason's review ask: mock dispatcher + paused coroutine
      + assert release).

Run via:
    pytest tests/test_cli_dispatcher.py -v
"""
import asyncio
import os
import sys
import pytest

# Hack: make research.py importable. The script is at the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────
# Controls contract — the methods the F6 fix relies on
# ─────────────────────────────────────────────────────────────────────

class TestPipelineControlsContract:
    """The dispatcher's F6 fix calls set_continue_anyway / request_skip_agent.
    These tests verify those methods set the state await_agent_decision
    consumes — without these, the regression would silently recur."""

    def test_set_continue_anyway_then_consume_returns_true(self):
        from research import PipelineControls
        c = PipelineControls()
        c.set_continue_anyway()
        assert c.consume_continue_anyway() is True

    def test_consume_continue_anyway_false_when_unset(self):
        from research import PipelineControls
        c = PipelineControls()
        assert c.consume_continue_anyway() is False

    def test_consume_continue_anyway_is_one_shot(self):
        """First consume returns True; second returns False. Prevents
        leak into later phases that also consume continue_anyway (Phase 1
        Pro backstop at line ~14220, etc.)."""
        from research import PipelineControls
        c = PipelineControls()
        c.set_continue_anyway()
        assert c.consume_continue_anyway() is True
        assert c.consume_continue_anyway() is False

    def test_request_skip_agent_adds_to_skipped_agents(self):
        from research import PipelineControls
        c = PipelineControls()
        c.request_skip_agent("claude")
        assert "claude" in c.skipped_agents

    def test_request_skip_agent_lowercases(self):
        """The dispatcher passes 'claude' lowercase, but defense-in-depth:
        verify the controls method handles capitalized input too."""
        from research import PipelineControls
        c = PipelineControls()
        c.request_skip_agent("Claude")
        assert "claude" in c.skipped_agents

    def test_set_continue_anyway_also_releases_pause(self):
        """set_continue_anyway clears pause_event so wait_if_paused (line
        18702) returns immediately. Without this, the chat-mode coroutine
        would still wait for resume_event to fire separately."""
        from research import PipelineControls
        c = PipelineControls()
        c.request_pause("claude_chat_mode")
        assert c.is_pause() is True
        c.set_continue_anyway()
        assert c.is_pause() is False

    def test_request_skip_agent_releases_pause(self):
        """Same release semantics for skip — wait_if_paused returns
        after request_skip_agent."""
        from research import PipelineControls
        c = PipelineControls()
        c.request_pause("claude_chat_mode")
        assert c.is_pause() is True
        c.request_skip_agent("claude")
        assert c.is_pause() is False


# ─────────────────────────────────────────────────────────────────────
# Integration — drive await_agent_decision on a live event loop
# ─────────────────────────────────────────────────────────────────────

class TestAwaitAgentDecisionIntegration:
    """Jason's PR-review ask: mock the dispatcher + a paused Phase 2B
    coroutine + assert the coroutine releases after the keypress. These
    tests instantiate a fresh PipelineControls, schedule the dispatcher-
    side signal as an async task, and assert await_agent_decision returns
    the expected decision."""

    def test_returns_continue_anyway_when_flag_set(self):
        """`r` at claude_chat_mode → set_continue_anyway → await returns
        'continue_anyway' within one poll cycle (~0.5s)."""
        from research import PipelineControls

        async def _scenario():
            c = PipelineControls()
            async def _dispatch_after_brief_delay():
                await asyncio.sleep(0.05)
                c.set_continue_anyway()
            asyncio.create_task(_dispatch_after_brief_delay())
            decision = await c.await_agent_decision("claude", timeout=5.0)
            return decision

        assert asyncio.run(_scenario()) == "continue_anyway"

    def test_returns_skip_when_agent_in_skipped_agents(self):
        """`s` at claude_chat_mode → request_skip_agent('claude') →
        await returns 'skip' within one poll cycle."""
        from research import PipelineControls

        async def _scenario():
            c = PipelineControls()
            async def _dispatch_after_brief_delay():
                await asyncio.sleep(0.05)
                c.request_skip_agent("claude")
            asyncio.create_task(_dispatch_after_brief_delay())
            decision = await c.await_agent_decision("claude", timeout=5.0)
            return decision

        assert asyncio.run(_scenario()) == "skip"

    def test_returns_stop_when_stop_event_set(self):
        """Stop signal short-circuits the poll loop ahead of every other
        consume — covers the [Stop] button path at chat-mode alerts."""
        from research import PipelineControls

        async def _scenario():
            c = PipelineControls()
            async def _dispatch_after_brief_delay():
                await asyncio.sleep(0.05)
                c.request_stop()
            asyncio.create_task(_dispatch_after_brief_delay())
            decision = await c.await_agent_decision("claude", timeout=5.0)
            return decision

        assert asyncio.run(_scenario()) == "stop"

    def test_returns_timeout_when_no_signal(self):
        """Regression check: without any signal, await_agent_decision
        times out rather than hangs indefinitely. The F6 production bug
        manifested as the 3h timeout firing — this test catches the
        polling-loop liveness at a much shorter scale."""
        from research import PipelineControls

        async def _scenario():
            c = PipelineControls()
            decision = await c.await_agent_decision("claude", timeout=1.0)
            return decision

        assert asyncio.run(_scenario()) == "timeout"
