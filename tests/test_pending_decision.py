"""#710 — a paused login Decision must re-surface when the user OPENS the chat,
even if it was raised while a DIFFERENT chat was the viewed tab.

E2E 2026-05-30: both workers paused at Phase 0 (Claude logged out). The viewed
chat showed the login+Retry card and recovered; the OTHER chat paused
identically server-side but surfaced NO card on open ("stuck at init"), so the
user couldn't resume. Root cause: the decision lived only in the transient
`pipeline_events` stream, whose per-browser seq cursor a background notifications
listener had already burned — so cold open had nothing to replay, and the run
doc carried nothing durable.

Fix (BE half): mirror the decision onto the ROOT research doc via
`_persist_pending_decision` at every login gate, and retract it with
`_clear_pending_decision` the instant the gate resolves. Source-inspection
guards on research.py.
"""
import inspect

import research


def test_pending_decision_helpers_exist():
    assert hasattr(research, "_persist_pending_decision"), (
        "BE must expose _persist_pending_decision to mirror the decision onto "
        "the root research doc (#710)."
    )
    assert hasattr(research, "_clear_pending_decision"), (
        "BE must expose _clear_pending_decision to retract the decision when "
        "the gate resolves (#710)."
    )
    # Persist writes the structured payload under the `pendingDecision` field.
    psrc = inspect.getsource(research._persist_pending_decision)
    assert '"pendingDecision": payload' in psrc, (
        "_persist_pending_decision must write the payload under pendingDecision "
        "on the root doc (#710)."
    )
    # Clear must remove the field (not leave a stale value) so a resolved
    # decision can't re-surface on a later cold open.
    csrc = inspect.getsource(research._clear_pending_decision)
    assert "DELETE_FIELD" in csrc and "pendingDecision" in csrc, (
        "_clear_pending_decision must DELETE_FIELD the pendingDecision (#710)."
    )


def test_login_gates_persist_then_clear():
    mod_src = inspect.getsource(research)
    # Both login gates (Phase 0 + phase-time) must mirror a login_required
    # decision durably onto the doc.
    assert mod_src.count('"kind": "login_required"') >= 2, (
        "both the Phase 0 and phase-time login gates must persist a "
        "login_required pendingDecision (#710)."
    )
    # Every persist must be paired with a clear so the card retracts on resolve.
    assert mod_src.count("_persist_pending_decision(") >= 2, (
        "each login gate must call _persist_pending_decision before pausing "
        "(#710)."
    )
    assert mod_src.count("_clear_pending_decision()") >= 2, (
        "each login gate must call _clear_pending_decision after the pause "
        "resolves (#710)."
    )


def test_phase0_login_event_now_carries_alert_id():
    # Phase 0 previously omitted alert_id on its login_required event while the
    # phase-time path included it; aligning them lets the live card and the
    # doc-hydrated card dedup on the same key.
    mod_src = inspect.getsource(research)
    assert "phase0_login_required_" in mod_src, (
        "the Phase 0 login_required event must carry a stable alert_id so the "
        "live and hydrated cards dedup (#710)."
    )
