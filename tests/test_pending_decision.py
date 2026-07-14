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
import re

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
    # Every login pause must mirror a login_required decision durably onto
    # the doc. Post-#899 the persist sites are: the P0 walk, the env-check,
    # and the work-tab login pause (_work_tab_login_pause — the only
    # PHASE-TIME mirror left; its payload is functionally pinned in
    # test_worktab_preflight_899.py). The slimmed gate persists nothing.
    assert mod_src.count('"kind": "login_required"') >= 2, (
        "the P0 walk and the work-tab login pause must persist a "
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


def test_skip_agent_command_clears_pending_decision():
    # E2E 2026-07-01: a Phase-2 agent that FAILED TO LAUNCH (fail_agent →
    # added to skipped_agents but NOT in `pending`) never emits agent_skipped,
    # so the central clear seam in emit_event never fires. fail_agent had already
    # persisted a durable pipeline_error pendingDecision mirror, so on Skip the
    # mirror lingered and the FE AgentAlertPanel fallback (decisionToCard) kept
    # re-rendering the "Hit a snag" card even though the agent showed SKIPPED.
    # retry_agent already retracts the mirror at its command chokepoint (#777);
    # skip_agent must do the same. Isolate the skip_agent dispatcher block and
    # assert the clear call is present.
    mod_src = inspect.getsource(research)
    m = re.search(
        r'elif action == "skip_agent":(.*?)elif action == "skip_phase":',
        mod_src, re.DOTALL,
    )
    assert m, "skip_agent dispatcher block not found (has the handler moved?)."
    block = m.group(1)
    assert "_clear_pending_decision" in block, (
        "the skip_agent command handler must call _clear_pending_decision so the "
        "durable 'Hit a snag' pendingDecision mirror is retracted the instant the "
        "user clicks Skip — a launch-failed agent emits no agent_skipped, so the "
        "central seam never fires and the snag card lingered (#777 parity)."
    )
    # Symmetry guard: the retry_agent chokepoint (#777) must ALSO clear — this
    # locks both resolve paths so a future refactor can't silently drop one.
    mr = re.search(
        r'elif action == "retry_agent":(.*?)elif action == "continue_partial_agent":',
        mod_src, re.DOTALL,
    )
    assert mr and "_clear_pending_decision" in mr.group(1), (
        "the retry_agent handler must also clear the pendingDecision mirror (#777)."
    )


def test_clear_pending_decision_is_agent_scoped(monkeypatch):
    # Reviewer-confirmed cross-agent clobber: fail_agent's mirror is NON-blocking,
    # so a launch-failed ChatGPT mirror can be OVERWRITTEN by a later blocking
    # Claude decision on the single pendingDecision field. Skipping/​retrying the
    # still-visible ChatGPT card must NOT delete Claude's live mirror. A
    # command-time clear scoped to an agent only fires when the live mirror
    # targets THAT agent; the universal (no-agent) resolve path always fires.
    writes = []
    monkeypatch.setattr(research, "_update_firestore_research",
                        lambda patch: writes.append(patch))
    monkeypatch.setattr(research, "_pending_decision_active", False, raising=False)
    monkeypatch.setattr(research, "_pending_decision_agent", None, raising=False)

    # Claude's blocking decision is the live mirror.
    research._persist_pending_decision(
        {"kind": "pipeline_error", "phase": 2, "agent": "claude",
         "alert_id": "agent_claude_error"})
    assert research._pending_decision_agent == "claude"

    writes.clear()
    # Skipping a DIFFERENT agent (ChatGPT) must leave Claude's mirror intact.
    research._clear_pending_decision("chatgpt")
    assert writes == [], (
        "skipping chatgpt must NOT DELETE_FIELD claude's still-live mirror"
    )
    assert research._pending_decision_agent == "claude"

    # Skipping the SAME agent retracts it.
    research._clear_pending_decision("claude")
    assert len(writes) == 1 and "pendingDecision" in writes[0]
    assert research._pending_decision_agent is None

    # A universal (no-agent) clear always fires — central seam / login gates.
    research._persist_pending_decision(
        {"kind": "login_required", "phase": 0,
         "alert_id": "phase0_login_required_x"})
    writes.clear()
    research._clear_pending_decision()
    assert len(writes) == 1, "the no-agent resolve path must clear unconditionally"


def test_pending_decision_cleared_on_universal_resolve_signal():
    # The clear is centralized on the resolve EVENTS every gate emits, so it
    # covers gates that wait via their own poll loop (human-verify) as well as
    # those using wait_if_paused.
    src = inspect.getsource(research.emit_event)
    # 2026-07-11: the seam agent-scopes agent_skipped clears (skipping agent A
    # must not retract agent B's still-live mirror); agent-less events keep
    # the unconditional clear via the None arm — same #710 contract.
    # 2026-07-14: pipeline_resumed is scoped the SAME way now that the
    # non-blocking P2 model emits per-agent resumes (auto-skip/chat-mode/retry);
    # an agent-carrying resume must not blanket-wipe a sibling's live mirror.
    assert ('_clear_pending_decision(\n                agent if event_type in '
            '("agent_skipped", "pipeline_resumed") else None)') in src, (
        "emit_event must clear pendingDecision (#710) — agent-scoped for "
        "agent_skipped AND pipeline_resumed.")
    # Every resolution signal retracts the mirror: resume/stop AND skip
    # (#715 — a Skip emits agent_skipped/phase_skipped, not pipeline_resumed).
    for ev in ("pipeline_resumed", "pipeline_stopped", "agent_skipped", "phase_skipped"):
        assert f'"{ev}"' in src, (
            f"emit_event must clear pendingDecision on {ev} so every gate's "
            f"resolution (incl. Skip) retracts the card (#710/#715)."
        )
