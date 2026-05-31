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


def test_parity_all_decision_gates_persist_pendingdecision():
    # #710 parity: env-check, human-verify, agent-link, and pro_required all
    # mirror their decision onto the doc so a cold chat-open re-surfaces the
    # card, not just login.
    mod_src = inspect.getsource(research)
    for kind in ("human_verification_required", "agent_link_failed", "pro_required"):
        assert f'"kind": "{kind}"' in mod_src, (
            f"the {kind} gate must persist a pendingDecision of that kind (#710)."
        )
    # env-check reuses the login_required kind but with a distinct alert_id.
    assert "phase0_env_check" in mod_src, (
        "the env-check gate must persist a pendingDecision (alert_id "
        "phase0_env_check) so an env failure re-surfaces on cold open (#710)."
    )
    # Each carded gate stamps an alert_id so live + hydrated cards dedup.
    assert "_human_verify_" in mod_src and "_agent_link_" in mod_src, (
        "human-verify and agent-link events must carry stable alert_ids (#710)."
    )


def test_generic_pipeline_error_persists_in_emit_event():
    # #715 universal alert persistence: emit_event must mirror ANY blocking
    # pipeline_error (actions present, not quiet) as a kind='pipeline_error'
    # pendingDecision so cua_unavailable / chat_mode / 429-key-card /
    # phase_timeout / bare fail_phase all re-surface on cold chat-open.
    src = inspect.getsource(research.emit_event)
    assert 'event_type == "pipeline_error"' in src and 'data.get("actions")' in src, (
        "emit_event must gate the generic persist on a pipeline_error carrying "
        "actions (#715)."
    )
    assert 'not data.get("quiet")' in src, (
        "the generic persist must EXCLUDE quiet pipeline_errors so transient "
        "auto-retry infra banners stay non-durable (#715)."
    )
    assert '"kind": "pipeline_error"' in src, (
        "the generic persist must write kind='pipeline_error' (#715)."
    )
    assert "suppress_generic_mirror" in src, (
        "emit_event must honor suppress_generic_mirror so a richer kind-specific "
        "mirror (pro_required) isn't clobbered (#715)."
    )


def test_pro_required_suppresses_generic_mirror():
    # pro_required persists its own richer kind; it must tell emit_event's
    # generic seam to stand down so it isn't overwritten in the same tick.
    src = inspect.getsource(research._emit_pro_required_alert)
    assert "suppress_generic_mirror=True" in src, (
        "_emit_pro_required_alert must pass suppress_generic_mirror=True to "
        "emit_event (#715)."
    )


def test_pending_decision_cleared_on_universal_resolve_signal():
    # The clear is centralized on the resolve EVENTS every gate emits, so it
    # covers gates that wait via their own poll loop (human-verify) as well as
    # those using wait_if_paused.
    src = inspect.getsource(research.emit_event)
    assert "_clear_pending_decision()" in src, "emit_event must clear pendingDecision (#710)."
    # Every resolution signal retracts the mirror: resume/stop AND skip
    # (#715 — a Skip emits agent_skipped/phase_skipped, not pipeline_resumed).
    for ev in ("pipeline_resumed", "pipeline_stopped", "agent_skipped", "phase_skipped"):
        assert f'"{ev}"' in src, (
            f"emit_event must clear pendingDecision on {ev} so every gate's "
            f"resolution (incl. Skip) retracts the card (#710/#715)."
        )
