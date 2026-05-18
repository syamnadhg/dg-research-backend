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


# ─────────────────────────────────────────────────────────────────────
# DGOPS-7710-followup Bug 1: agent_link_failed pause + pop_agent_decision
# ─────────────────────────────────────────────────────────────────────

class TestBug1AgentLinkFailedFix:
    """Bug 1: wait_for_agent_decision (research.py:6381) used to return
    "skip" silently for CLI `r` because pop_agent_decision returned None
    (dispatcher never called set_agent_decision). Fix: pause reason
    "agent_link_failed" + dispatcher r → set_agent_decision("retry"),
    s → set_agent_decision("skip")."""

    def test_pop_agent_decision_returns_set_value(self):
        from research import PipelineControls
        c = PipelineControls()
        c.set_agent_decision("retry")
        assert c.pop_agent_decision() == "retry"

    def test_pop_agent_decision_is_one_shot(self):
        """Prevents the decision leaking across pause cycles."""
        from research import PipelineControls
        c = PipelineControls()
        c.set_agent_decision("retry")
        assert c.pop_agent_decision() == "retry"
        assert c.pop_agent_decision() is None

    def test_set_agent_decision_rejects_invalid_values(self):
        """Whitelist guard at research.py:3978 — only retry/skip/stop accepted."""
        from research import PipelineControls
        c = PipelineControls()
        c.set_agent_decision("garbage")
        assert c.pop_agent_decision() is None

    def test_set_agent_decision_accepts_retry_skip_stop(self):
        from research import PipelineControls
        for decision in ("retry", "skip", "stop"):
            c = PipelineControls()
            c.set_agent_decision(decision)
            assert c.pop_agent_decision() == decision

    def test_request_pause_with_reason_sets_pause_reason(self):
        """Bug 1 fix relies on request_pause carrying the reason so the
        dispatcher can route `r`/`s` differently for agent_link_failed."""
        from research import PipelineControls
        c = PipelineControls()
        c.request_pause("agent_link_failed")
        assert c.pause_reason == "agent_link_failed"


class TestBug1WaitForAgentDecisionIntegration:
    """Integration: wait_for_agent_decision returns the dispatcher-set
    decision. Mirrors the full Bug 1 fix path end-to-end."""

    def test_returns_retry_when_set_agent_decision_scheduled(self, monkeypatch):
        """CLI `r` at agent_link_failed → set_agent_decision("retry")
        + request_resume → wait_for_agent_decision returns "retry"."""
        from research import wait_for_agent_decision, _controls
        monkeypatch.setattr("research.emit_event", lambda *a, **kw: None)
        monkeypatch.setattr("research.log", lambda *a, **kw: None)

        async def _scenario():
            _controls.reset()
            async def _dispatch():
                await asyncio.sleep(0.05)
                _controls.set_agent_decision("retry")
                _controls.request_resume()
            asyncio.create_task(_dispatch())
            decision = await wait_for_agent_decision("claude", "link_dropped")
            return decision

        assert asyncio.run(_scenario()) == "retry"

    def test_returns_skip_when_set_agent_decision_skip_scheduled(self, monkeypatch):
        """CLI `s` at agent_link_failed → set_agent_decision("skip")
        + request_resume → wait_for_agent_decision returns "skip"."""
        from research import wait_for_agent_decision, _controls
        monkeypatch.setattr("research.emit_event", lambda *a, **kw: None)
        monkeypatch.setattr("research.log", lambda *a, **kw: None)

        async def _scenario():
            _controls.reset()
            async def _dispatch():
                await asyncio.sleep(0.05)
                _controls.set_agent_decision("skip")
                _controls.request_resume()
            asyncio.create_task(_dispatch())
            decision = await wait_for_agent_decision("claude", "link_dropped")
            return decision

        assert asyncio.run(_scenario()) == "skip"

    def test_default_skip_preserved_when_no_decision(self, monkeypatch):
        """Plain `request_resume` without any decision → defaults to "skip"
        (preserves pre-fix behavior for non-agent_link_failed paths
        that hit the wait_for_agent_decision function for unrelated reasons)."""
        from research import wait_for_agent_decision, _controls
        monkeypatch.setattr("research.emit_event", lambda *a, **kw: None)
        monkeypatch.setattr("research.log", lambda *a, **kw: None)

        async def _scenario():
            _controls.reset()
            async def _dispatch():
                await asyncio.sleep(0.05)
                _controls.request_resume()
            asyncio.create_task(_dispatch())
            decision = await wait_for_agent_decision("claude", "link_dropped")
            return decision

        assert asyncio.run(_scenario()) == "skip"

    # Stop-signal short-circuit coverage lives in F6's
    # TestAwaitAgentDecisionIntegration.test_returns_stop_when_stop_event_set
    # — that one uses a fresh PipelineControls() per test, sidestepping
    # the asyncio.Event-binding issue when the module-level _controls
    # singleton is reused across asyncio.run() invocations. Stop
    # semantics are identical between await_agent_decision and
    # wait_for_agent_decision (both check stop_event first), so the F6
    # coverage suffices.


# ─────────────────────────────────────────────────────────────────────
# DGOPS-7710-followup Bug 2: human_verification_required + pause_target_agent
# ─────────────────────────────────────────────────────────────────────

class TestBug2HumanVerificationFix:
    """Bug 2: Human verification pause's poll loop (research.py:18372)
    checks `skipped_agents`. CLI `s` used to set `skipped_phases` —
    wrong set, silently no-op. Fix: pause_target_agent field carries
    the platform name so dispatcher's `s` can call request_skip_agent
    with the right target."""

    def test_pause_target_agent_default_empty(self):
        from research import PipelineControls
        c = PipelineControls()
        assert c.pause_target_agent == ""

    def test_pause_target_agent_settable(self):
        from research import PipelineControls
        c = PipelineControls()
        c.pause_target_agent = "chatgpt"
        assert c.pause_target_agent == "chatgpt"

    def test_request_resume_clears_pause_target_agent(self):
        """Each resume clears the field so a subsequent pause without
        explicit target_agent set doesn't inherit a stale platform."""
        from research import PipelineControls
        c = PipelineControls()
        c.pause_target_agent = "chatgpt"
        c.request_pause("human_verification_required")
        c.request_resume()
        assert c.pause_target_agent == ""

    def test_reset_clears_pause_target_agent(self):
        from research import PipelineControls
        c = PipelineControls()
        c.pause_target_agent = "claude"
        c.reset()
        assert c.pause_target_agent == ""

    def test_human_verification_pause_reason_set(self):
        from research import PipelineControls
        c = PipelineControls()
        c.request_pause("human_verification_required")
        assert c.pause_reason == "human_verification_required"


# ─────────────────────────────────────────────────────────────────────
# DGOPS-7710-followup Bug 3: cua_unavailable honors skip_init_verify
# ─────────────────────────────────────────────────────────────────────

class TestBug3CuaUnavailableFix:
    """Bug 3: cua_unavailable block (research.py:21796) used to always
    retry — no skip path at all, even though CLI `s` at Phase 0 sets
    skip_init_verify. Fix: add `if skip_init_verify: break` after the
    is_stop check, matching the login_required pattern at line ~21700."""

    def test_request_skip_init_verify_sets_flag(self):
        from research import PipelineControls
        c = PipelineControls()
        c.request_skip_init_verify()
        assert c.skip_init_verify is True

    def test_request_skip_init_verify_releases_pause(self):
        """request_skip_init_verify at research.py:4104 also clears
        pause_event + sets resume_event so wait_if_paused returns."""
        from research import PipelineControls
        c = PipelineControls()
        c.request_pause("cua_unavailable")
        assert c.is_pause() is True
        c.request_skip_init_verify()
        assert c.is_pause() is False

    def test_skip_init_verify_default_false(self):
        from research import PipelineControls
        c = PipelineControls()
        assert c.skip_init_verify is False

    def test_reset_clears_skip_init_verify(self):
        from research import PipelineControls
        c = PipelineControls()
        c.request_skip_init_verify()
        c.reset()
        assert c.skip_init_verify is False

    def test_cua_unavailable_pause_reason(self):
        """Bug 3 fix adds a pause reason for log clarity."""
        from research import PipelineControls
        c = PipelineControls()
        c.request_pause("cua_unavailable")
        assert c.pause_reason == "cua_unavailable"
