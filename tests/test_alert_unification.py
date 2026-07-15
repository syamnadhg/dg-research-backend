"""Alert-system unification (2026-07-14) — one decision primitive.

Every user-facing decision card funnels through `emit_decision`, which emits
`pipeline_error` (the FE's existing decision primitive) plus three unifying
fields: `recoverability` (recoverable/blocker/infra), `auto_skip_deadline`
(epoch-ms, armed only for recoverable), and `decision_id` (stable id for
command-ack + flicker suppression). These guard Phase 0 (scaffolding): the
seam exists, the two core primitives route through it, the additive fields
ride the event + the durable mirror, and no existing behavior changed.

Run: pytest tests/test_alert_unification.py -v
"""
from __future__ import annotations

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


# ── the seam itself ───────────────────────────────────────────────────────────

def test_emit_decision_emits_pipeline_error_with_unifying_fields(monkeypatch):
    calls = _capture(monkeypatch)
    did = research.emit_decision(
        phase=2, agent="gemini", title="t", details="d",
        actions=[{"id": "skip", "label": "Skip"}],
        recoverability="recoverable", alert_id="phase2_agent_gemini_error")
    (args, kw) = calls[-1]
    assert args[0] == "pipeline_error"
    assert kw["phase"] == 2 and kw["agent"] == "gemini"
    assert kw["recoverability"] == "recoverable"
    assert kw["decision_id"] == did
    # No deadline passed → the field is absent (no misleading countdown).
    assert "auto_skip_deadline" not in kw


def test_emit_decision_arms_registry_only_with_a_deadline(monkeypatch):
    _capture(monkeypatch)
    research._pending_decisions.clear()
    research.emit_decision(phase=2, agent="claude", title="t", actions=[],
                           recoverability="recoverable", alert_id="a1")
    assert research._pending_decisions == {}, "no deadline → not registered"
    did = research.emit_decision(phase=2, agent="claude", title="t", actions=[],
                                 recoverability="recoverable", alert_id="a2",
                                 auto_skip_deadline=1_800_000)
    assert research._pending_decisions[did]["deadline"] == 1_800_000
    assert research._pending_decisions[did]["agent"] == "claude"


def test_decision_ids_are_unique(monkeypatch):
    _capture(monkeypatch)
    a = research._new_decision_id()
    b = research._new_decision_id()
    assert a != b


# ── the two Phase-0 primitives route through the seam ─────────────────────────

def test_fail_agent_routes_through_emit_decision(monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_agent("gemini", "Gemini couldn't start")
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["recoverability"] == "recoverable"
    assert pe["decision_id"]
    assert pe["alert_id"] == "phase2_agent_gemini_error"


def test_fail_agent_skip_only_is_hands_off(monkeypatch):
    # The hands-off Cloudflare skip-only card is HANDS_OFF: the user can't solve
    # the wall (only Skip), so it auto-skips on a short window rather than
    # waiting — greyed honestly as "verification wall wasn't cleared".
    calls = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_agent("gemini", "Verify you are human", skip_only=True)
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["recoverability"] == "hands_off"


def test_fail_phase_routes_through_emit_decision(monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 1, raising=False)
    research.fail_phase(1, "No brief was generated", "details")
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["recoverability"] == "recoverable"
    assert pe["decision_id"]
    assert pe["alert_id"] == "phase1_error"


def test_seam_exists_and_registry_defined():
    assert callable(research.emit_decision)
    assert isinstance(research._pending_decisions, dict)
    src = inspect.getsource(research.emit_decision)
    assert 'emit_event("pipeline_error"' in src
    assert "recoverability" in src and "decision_id" in src
