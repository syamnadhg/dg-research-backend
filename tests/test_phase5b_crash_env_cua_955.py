"""#955 Phase 5B — crash cards + cua_unavailable + env_missing_key + soft-warn.

The remaining explicit-actions decision cards move onto the catalog through an
extended `fail_phase` (real intent= / recoverability= / decision_id= params — NOT
**extra, which would collide with fail_phase's own explicit recoverability= and
TypeError), plus the env-check gate and the phase soft-timeout warning. This
locks:

  1. the crash tokens (retry_resume / discard) BYTE-EXACT to the explicit lists
     the crash cards authored before the migration,
  2. the ONE non-additive wire delta: crash_login_interrupt + cua_unavailable
     flip recoverability "recoverable" → "blocker" (keeps emit_decision's
     no-deadline guard live for them; FE-neutral),
  3. cua_unavailable stays Retry-only + fail-closed, and the two cards get
     DISTINCT alert_ids (the old phase0_error collision is fixed),
  4. env_missing_key authors through the seam on the login_required event, and
  5. the soft-warn lift keeps event_name=pipeline_warning + the message title +
     the verbatim Wait/Retry/Skip actions, gaining a decision_id.

Run: pytest tests/test_phase5b_crash_env_cua_955.py -v
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


def _capture(monkeypatch):
    events = []
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(research, "_persist_pending_decision", lambda p: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_phase_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    return events


def _last(events, name):
    for a, k in reversed(events):
        if a and a[0] == name:
            return k
    raise AssertionError(f"no {name!r} event captured")


# ── 1. crash tokens byte-parity (== the explicit lists the crash cards dropped) ──

def test_retry_resume_token_matches_the_crash_card():
    acts = research._alert_actions_for("crash_login_interrupt", 2, None)
    assert acts == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "resume_from_checkpoint"}},
    ]


def test_crash_loop_tokens_match_the_terminal_card():
    acts = research._alert_actions_for("crash_loop", 2, None)
    assert acts == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "resume_from_checkpoint"}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "discard_restart_prompt"}},
    ]


def test_cua_unavailable_is_retry_only_no_skip():
    # Fail-closed: cua_unavailable never offers a Skip (skip-verify is a login
    # switch, not an infra bypass). Byte-identical to the explicit list dropped.
    acts = research._alert_actions_for("cua_unavailable", 0, "system")
    assert acts == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "retry_phase", "phase": 0}},
    ]


# ── 2. catalog classes (the §8.1 recoverability flip) ──────────────────────────

def test_crash_and_cua_recoverability_classes():
    C = research.ALERT_INTENTS
    # blocker: the user resolves them; never auto-fire → keeps the no-deadline guard.
    assert C["crash_login_interrupt"]["class"] == "blocker"
    assert C["cua_unavailable"]["class"] == "blocker"
    # crash_loop stays recoverable (the round-robin firer is dead post-run, and
    # the catalog omits auto_skip so no deadline is ever armed anyway).
    assert C["crash_loop"]["class"] == "recoverable"
    assert "auto_skip" not in C["crash_loop"]


def test_env_missing_key_row_matches_the_fe_card():
    row = research.ALERT_INTENTS["env_missing_key"]
    assert row["class"] == "blocker"
    assert row["actions"] == ["retry_phase", "skip_login"]
    # phase-0 expansion = Retry + "Skip sign-in check" (skip_init_verify), the FE card.
    acts = research._alert_actions_for("env_missing_key", 0, None)
    assert acts[1] == {"id": "skip", "label": "Skip sign-in check", "style": "default",
                       "command": {"action": "skip_init_verify"}}


# ── 3. fail_phase intent= extension ────────────────────────────────────────────

def test_fail_phase_intent_derives_blocker_recoverability(monkeypatch):
    events = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_phase(
        phase=2, error="Paused by the login command", reason="r",
        agent=None, intent="crash_login_interrupt",
        mark_phase_errored=False, force_mirror=True,
        alert_id="phase2_login_interrupt")
    ev = _last(events, "pipeline_error")
    assert ev["recoverability"] == "blocker"
    assert ev["intent"] == "crash_login_interrupt"
    # the token-derived actions (Retry → resume_from_checkpoint)
    assert ev["actions"] == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "resume_from_checkpoint"}}]
    # override flag rides through to emit_event
    assert ev.get("force_mirror") is True
    # quiet (mark_phase_errored=False) preserved
    assert ev.get("quiet") is True
    # blocker → no deadline armed
    assert "auto_skip_deadline" not in ev


def test_fail_phase_crash_loop_is_recoverable(monkeypatch):
    events = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_phase(phase=2, error="The run kept hitting errors",
                        reason="r", agent=None, intent="crash_loop")
    ev = _last(events, "pipeline_error")
    assert ev["recoverability"] == "recoverable"
    assert ev["actions"] == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "resume_from_checkpoint"}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "discard_restart_prompt"}}]


def test_fail_phase_intent_blocker_refuses_a_deadline(monkeypatch):
    _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 0, raising=False)
    try:
        research.fail_phase(phase=0, error="AI service unavailable", reason="r",
                            agent="system", intent="cua_unavailable",
                            auto_skip_deadline=999999)
        raise AssertionError("a blocker cua card must refuse a deadline")
    except ValueError:
        pass


def test_fail_phase_explicit_actions_still_bypass_the_expander(monkeypatch):
    # A caller passing explicit actions= keeps them verbatim even with intent=.
    events = _capture(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    custom = [{"id": "retry", "label": "Retry Phase 2", "style": "primary",
               "command": {"action": "retry_phase", "phase": 2}}]
    research.fail_phase(phase=2, error="x", reason="y", actions=custom)
    ev = _last(events, "pipeline_error")
    assert ev["actions"] == custom


# ── 4. cua alert_id collision fix ──────────────────────────────────────────────

def test_cua_cards_have_distinct_alert_ids():
    import inspect
    src = inspect.getsource(research.run_pipeline)
    # The probe card + the per-platform login-walk card no longer share
    # "phase0_error" — each carries its own cua alert_id.
    assert '"phase0_cua_unavailable"' in src            # probe
    assert 'f"phase0_cua_unavailable_{key}"' in src     # per-platform walk


# ── 5. env_missing_key emitter ────────────────────────────────────────────────

def test_env_missing_key_authors_on_the_login_required_event(monkeypatch):
    events = _capture(monkeypatch)
    research.emit_decision(
        intent="env_missing_key", event_name="login_required",
        phase=0, agent=None,
        facts={"title": "Add your Anthropic key", "details": ""},
        actions=research._alert_actions_for("env_missing_key", 0, None),
        alert_id="phase0_env_check",
        platforms=[], platformLabels=[], machineName="pc",
        envErrors=["Anthropic key missing"], attempt=1,
        message="Add your Anthropic key")
    ev = _last(events, "login_required")
    assert ev["envErrors"] == ["Anthropic key missing"]
    assert ev["alert_id"] == "phase0_env_check"
    assert ev["intent"] == "env_missing_key" and ev["recoverability"] == "blocker"
    assert "auto_skip_deadline" not in ev


# ── 6. soft-warn lift ─────────────────────────────────────────────────────────

def test_soft_warn_stays_a_pipeline_warning_with_message_title(monkeypatch):
    events = _capture(monkeypatch)
    research.emit_decision(
        phase=1, title="This step is taking a while",
        details="This step is still running and may just be a long one. "
                "Keep waiting, or restart it / skip it.",
        actions=[
            {"id": "wait", "label": "Wait — keep going", "style": "primary",
             "command": {"action": "dismiss_alert"}},
            {"id": "retry", "label": "Retry from checkpoint", "style": "default",
             "command": {"action": "retry_phase", "phase": 1}},
            {"id": "skip", "label": "Skip phase", "style": "default",
             "command": {"action": "skip_phase", "phase": 1}}],
        recoverability="recoverable", event_name="pipeline_warning",
        alert_id="phase1_soft_timeout_x", dismissible=True, alertType="warn",
        message="This step is taking a while")
    ev = _last(events, "pipeline_warning")
    # FE warning handler reads the title from message, never error
    assert ev["message"] == "This step is taking a while"
    assert ev["alertType"] == "warn"
    # the verbatim 3-action list (the FE RENDERS actions on pipeline_warning)
    assert [a["id"] for a in ev["actions"]] == ["wait", "retry", "skip"]
    assert ev["actions"][0]["label"] == "Wait — keep going"
    # gained a decision_id without changing the wire routing
    assert ev["decision_id"]
    assert ev["recoverability"] == "recoverable"


def test_wait_label_is_not_in_the_token_expander():
    # §8.8: soft-warn stays explicit-mode — the "Wait" button must NOT leak into
    # _alert_actions_for (a source pin in test_fail_agent_no_wait forbids it).
    import inspect
    exp = inspect.getsource(research._alert_actions_for)
    assert '"label": "Wait' not in exp
