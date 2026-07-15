"""#955 Phase 1 — the intent catalog + the ONE auto-skip finalize.

Byte-parity guards for the alert-unification foundation: ALERT_INTENTS is the
only hard-coded part (class + action tokens + flags); `_alert_actions_for`
expands tokens into dicts BYTE-IDENTICAL to the inline dicts each call site
authored before the catalog; `_autoskip_details` single-sources the five
finalize notices verbatim; `_finalize_agent_autoskip` reproduces the exact
event shapes of the four inline copies it replaced. Actions/classes are
deterministic — never AI (the async copy sharpen lands in Phase 3 and touches
prose only).

Run: pytest tests/test_alert_intents.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(research, "emit_event",
                        lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_phase_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    return calls


# ── the catalog itself ────────────────────────────────────────────────────────

def test_catalog_classes_match_locked_decisions():
    # The recoverability tiering locked with the user (2026-07-14/15):
    # recoverable ~30min, hands_off ~5min, blocker never auto-fires,
    # infra reserved/unused (Stop-only dropped — CUA-down stays Retry-only).
    C = {k: v["class"] for k, v in research.ALERT_INTENTS.items()}
    assert C["phase_error"] == "recoverable"
    assert C["phase_error_noretry"] == "recoverable"
    assert C["agent_failed"] == "recoverable"
    assert C["agent_failed_handsoff"] == "hands_off"
    assert C["agent_stuck"] == "recoverable"
    assert C["hv_wall"] == "hands_off"
    assert C["pro_required"] == "blocker"
    assert C["chat_mode"] == "recoverable"
    assert C["login_required"] == "blocker"
    assert C["env_missing_key"] == "blocker"
    assert C["hv_solvable"] == "blocker"
    assert C["agent_link_failed"] == "recoverable"
    assert C["manual_brief"] == "blocker"
    assert C["crash_login_interrupt"] == "blocker"
    assert C["crash_loop"] == "recoverable"
    assert C["cua_unavailable"] == "blocker"          # Retry-only, UNCHANGED
    assert "infra" not in C.values(), "infra is reserved/unused (user dropped Stop-only)"


def test_hands_off_window_constant():
    assert research.HANDS_OFF_AUTO_SKIP_SEC == 300


# ── token expansion: byte-parity with the pre-catalog inline dicts ───────────

def test_phase_error_tokens_byte_identical():
    acts = research._alert_actions_for("phase_error", 3)
    assert acts == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "retry_phase", "phase": 3}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_phase", "phase": 3}},
    ]
    assert research._alert_actions_for("phase_error_noretry", 1) == [
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_phase", "phase": 1}},
    ]


def test_agent_failed_tokens_byte_identical():
    acts = research._alert_actions_for("agent_failed", 2, "gemini")
    assert acts == [
        {"id": "retry", "label": "Retry (hard)", "style": "primary",
         "command": {"action": "retry_agent", "agent": "gemini", "mode": "hard"}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_agent", "agent": "gemini"}},
    ]


def test_hands_off_skip_is_primary_and_only():
    # skip_only (Cloudflare) card: Skip is the ONLY action and styled primary.
    acts = research._alert_actions_for("agent_failed_handsoff", 2, "claude")
    assert acts == [
        {"id": "skip", "label": "Skip", "style": "primary",
         "command": {"action": "skip_agent", "agent": "claude"}},
    ]


def test_unwired_tokens_raise_until_their_phase():
    # Tokens land with their migration phase; an early call must fail loudly,
    # never emit a wrong button. (Explicit actions= callers bypass entirely.)
    for intent in ("pro_required", "chat_mode", "login_required", "hv_solvable",
                   "agent_link_failed", "manual_brief", "crash_login_interrupt",
                   "crash_loop"):
        try:
            research._alert_actions_for(intent, 2, "chatgpt")
            raise AssertionError(f"{intent} should raise until its phase wires it")
        except NotImplementedError:
            pass


# ── fail_phase / fail_agent still emit byte-identical actions ────────────────

def test_fail_phase_default_actions_unchanged(monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 1, raising=False)
    research.fail_phase(1, "No brief was generated", "details")
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["actions"] == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "retry_phase", "phase": 1}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_phase", "phase": 1}},
    ]


def test_fail_phase_explicit_actions_bypass_expander(monkeypatch):
    # Crash cards / CUA-down / backstops pass explicit actions= — verbatim.
    calls = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 0, raising=False)
    custom = [{"id": "retry", "label": "Retry", "style": "primary",
               "command": {"action": "resume_from_checkpoint"}}]
    research.fail_phase(0, "Paused by the login command", "d", actions=custom)
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["actions"] == custom


def test_fail_agent_default_actions_unchanged(monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_agent("gemini", "Gemini couldn't start")
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["actions"] == [
        {"id": "retry", "label": "Retry (hard)", "style": "primary",
         "command": {"action": "retry_agent", "agent": "gemini", "mode": "hard"}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_agent", "agent": "gemini"}},
    ]


def test_fail_agent_skip_only_actions_unchanged(monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_agent("claude", "Verify you are human", skip_only=True)
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["actions"] == [
        {"id": "skip", "label": "Skip", "style": "primary",
         "command": {"action": "skip_agent", "agent": "claude"}},
    ]
    assert pe["recoverability"] == "hands_off"


# ── the seam's new calling modes ──────────────────────────────────────────────

def test_emit_decision_intent_mode_derives_from_catalog(monkeypatch):
    calls = _capture(monkeypatch)
    did = research.emit_decision(
        intent="agent_failed", phase=2, agent="gemini",
        facts={"title": "Gemini couldn't start", "details": "d"},
        alert_id="phase2_agent_gemini_error")
    (args, kw) = calls[-1]
    assert args[0] == "pipeline_error"
    assert kw["intent"] == "agent_failed"
    assert kw["recoverability"] == "recoverable"
    assert kw["error"] == "Gemini couldn't start"
    assert kw["actions"][0]["command"]["action"] == "retry_agent"
    assert kw["decision_id"] == did


def test_emit_decision_requires_intent_or_explicit(monkeypatch):
    _capture(monkeypatch)
    try:
        research.emit_decision(phase=2, alert_id="x")
        raise AssertionError("must require intent= or explicit title/actions/recoverability")
    except ValueError:
        pass


def test_emit_decision_never_regenerates_a_passed_decision_id(monkeypatch):
    # Re-emittable cards (HV re-emits, the Phase-3 AI copy upgrade) must
    # update in place under the SAME id.
    calls = _capture(monkeypatch)
    did = research.emit_decision(
        phase=2, agent="claude", title="t", actions=[],
        recoverability="recoverable", alert_id="a1", decision_id="dec_keep_me")
    assert did == "dec_keep_me"
    assert calls[-1][1]["decision_id"] == "dec_keep_me"


def test_emit_decision_event_name_override(monkeypatch):
    # The soft-warn migration (Phase 5) emits pipeline_warning through the
    # same seam; the default stays pipeline_error (mirror gate + FE key on it).
    calls = _capture(monkeypatch)
    research.emit_decision(
        phase=2, title="t", actions=[], recoverability="recoverable",
        alert_id="a2", event_name="pipeline_warning")
    assert calls[-1][0][0] == "pipeline_warning"


def test_emit_decision_mirror_persists_custom_and_suppresses_generic(monkeypatch):
    calls = _capture(monkeypatch)
    persisted = []
    monkeypatch.setattr(research, "_persist_pending_decision",
                        lambda payload: persisted.append(payload))
    _mirror = {"kind": "pro_required", "phase": 2, "agent": "gemini"}
    research.emit_decision(
        phase=2, agent="gemini", title="t", actions=[],
        recoverability="blocker", alert_id="a3", mirror=_mirror)
    (args, kw) = calls[-1]
    assert kw["suppress_generic_mirror"] is True
    assert persisted == [_mirror]
    assert kw["recoverability"] == "blocker"


def test_emit_decision_tracks_active_decisions(monkeypatch):
    _capture(monkeypatch)
    research._active_decisions.clear()
    did = research.emit_decision(
        phase=2, agent="claude", title="t", actions=[],
        recoverability="recoverable", alert_id="a4")
    assert did in research._active_decisions


# ── the ONE finalize: notice copy + event shape byte-parity ──────────────────

_TAIL = "— skipped so your run can finish. The other agents aren't affected."


def test_autoskip_details_byte_identical_to_the_five_inline_copies():
    d = research._autoskip_details
    assert d("claude_2artifact", "Claude") == (
        "Claude's report never finished and the retry prompt went "
        f"unanswered {_TAIL}")
    assert d("setup_failed", "Gemini") == (
        "Gemini couldn't start (a platform-side setup or "
        "delivery problem) and its Retry/Skip alert wasn't "
        f"answered {_TAIL}")
    assert d("hard_cap_parked", "ChatGPT") == (
        f"ChatGPT sat on an unanswered alert past the time limit {_TAIL}")
    assert d("stuck", "Gemini", why="stayed frozen with no response") == (
        f"Gemini stayed frozen with no response {_TAIL}")
    assert d("hv_wall", "Claude") == (
        f"Claude hit a verification wall that wasn't cleared in time {_TAIL}")


def test_finalize_agent_autoskip_event_shape(monkeypatch):
    calls = _capture(monkeypatch)
    closes = []

    async def _fake_close(browser, page, key, name, **kw):
        closes.append((key, name, kw))
    monkeypatch.setattr(research, "_close_skipped_agent_tab", _fake_close)

    results = {}
    asyncio.run(research._finalize_agent_autoskip(
        None, None, "gemini", "Gemini",
        reason="auto_skip_hard_cap", copy_key="hard_cap_parked",
        partial="partial text", url="https://g", elapsed_sec=5401,
        results=results, results_name="Gemini"))

    assert results["Gemini"] == {
        "status": "auto_skipped", "text": "partial text",
        "url": "https://g", "page": None, "elapsed_sec": 5401,
    }
    sk = next(k for (a, k) in calls if a and a[0] == "agent_skipped")
    assert sk["phase"] == 2 and sk["agent"] == "gemini"
    assert sk["reason"] == "auto_skip_hard_cap"
    assert sk["partial_chars"] == len("partial text")
    warn = next(k for (a, k) in calls if a and a[0] == "pipeline_warning")
    assert warn["error"] == "Gemini skipped automatically"
    assert warn["alert_id"] == "agent_gemini_autoskip"
    assert warn["actions"] == [] and warn["auto_clear_on_resume"] is True
    assert closes == [("gemini", "Gemini", {"final_status": "skipped"})]


def test_finalize_agent_autoskip_no_results_dict(monkeypatch):
    # The HV wait / setup-context callers finalize without a results dict.
    calls = _capture(monkeypatch)

    async def _fake_close(*a, **k):
        pass
    monkeypatch.setattr(research, "_close_skipped_agent_tab", _fake_close)
    asyncio.run(research._finalize_agent_autoskip(
        None, None, "claude", "Claude",
        reason="auto_skip_unanswered_timeout", copy_key="claude_2artifact"))
    sk = next(k for (a, k) in calls if a and a[0] == "agent_skipped")
    assert sk["partial_chars"] == 0


def test_hv_finalize_routes_notice_through_autoskip_details():
    src = inspect.getsource(research._hv_auto_skip_finalize)
    assert '_autoskip_details("hv_wall"' in src
