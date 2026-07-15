"""#955 Phase 5A — gate events onto the intent catalog (BE authoring migration).

The remaining custom-event decision cards (login_required, human_verification_
required, agent_link_failed, manual_brief_required) are re-authored through the
`emit_decision` seam. `event_name=` overrides keep the FE routing byte-identical;
the seam's additions (intent / recoverability / decision_id / an FE-inert actions
list) are sanctioned-additive on these events (the FE builds its own buttons for
them today). This file locks:

  1. the four newly-wired token shapes (skip_login / resume / retry_link /
     skip_link) BYTE-EXACT to the FE builders in pipeline-decision.ts, and
  2. the seam-authored events preserve every legacy wire field, add the
     additive ones, arm NO deadline (all blocker/recoverable-without-auto_skip),
     and reuse the decision_id on the re-card / re-emit paths, and
  3. the consumer-side fix that makes the Claude 2-artifact hard-fail card's
     Retry/Skip actually work (agent-scoped pending_agent_decision consumed by
     the non-blocking park poll — was dead, resolved only by the 300s timeout).

Run: pytest tests/test_phase5_gate_migration_955.py -v
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


def _capture(monkeypatch):
    """Capture emit_event calls + persisted mirrors; stub the terminal-status
    writers so the seam runs without Firestore."""
    events, mirrors = [], []
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(research, "_persist_pending_decision", lambda p: mirrors.append(p))
    monkeypatch.setattr(research, "_clear_pending_decision", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_phase_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    return events, mirrors


def _last(events, name):
    """The most recent captured event of a given type."""
    for a, k in reversed(events):
        if a and a[0] == name:
            return k
    raise AssertionError(f"no {name!r} event captured")


# ── 1. token byte-parity (byte-exact to dg-research/src/lib/pipeline-decision.ts) ──

def test_skip_login_is_destination_aware_and_names_the_platform():
    # phase >= 1, single platform → "Skip <Label>" / skip_agent (work-tab pause);
    # matches FE loginDecisionAlert pipeline-decision.ts:96-103.
    acts = research._alert_actions_for("login_required", 1, "chatgpt")
    assert acts == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "retry_phase", "phase": 1}},
        {"id": "skip", "label": "Skip ChatGPT", "style": "default",
         "command": {"action": "skip_agent", "agent": "chatgpt"}},
    ]
    # NotebookLM label — the P3 work-tab login pause caller (the added map entry).
    p3 = research._alert_actions_for("login_required", 3, "notebooklm")
    assert p3[1] == {"id": "skip", "label": "Skip NotebookLM", "style": "default",
                     "command": {"action": "skip_agent", "agent": "notebooklm"}}


def test_skip_login_at_phase0_is_skip_init_verify():
    # phase 0 (init walk / env-check) → "Skip sign-in check" / skip_init_verify,
    # byte-exact to the FE P0 loginDecisionAlert card (isEnv/phase0 branch).
    acts = research._alert_actions_for("login_required", 0, None)
    assert acts == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "retry_phase", "phase": 0}},
        {"id": "skip", "label": "Skip sign-in check", "style": "default",
         "command": {"action": "skip_init_verify"}},
    ]


def test_hv_solvable_is_resume_plus_named_skip():
    # non-Cloudflare HV → Resume + Skip (byte-exact to FE humanVerifyAlert
    # non-Cloudflare branch, pipeline-decision.ts:159-171). command+style match;
    # id/label of the Skip intentionally reuse the generic skip_agent token
    # (the §8.10 waiver — FE-inert since the FE builds its own HV buttons).
    acts = research._alert_actions_for("hv_solvable", 2, "claude")
    assert acts == [
        {"id": "resume", "label": "Resume", "style": "primary",
         "command": {"action": "resume"}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_agent", "agent": "claude"}},
    ]


def test_hv_wall_is_skip_only_primary():
    # Cloudflare HV → Skip only, primary (hands_off styling matches the FE
    # Cloudflare card's Skip-primary).
    acts = research._alert_actions_for("hv_wall", 2, "gemini")
    assert acts == [
        {"id": "skip", "label": "Skip", "style": "primary",
         "command": {"action": "skip_agent", "agent": "gemini"}},
    ]


def test_agent_link_tokens_are_agent_decision_commands():
    # agent_link_failed → agent_decision(retry|skip), byte-exact to FE
    # agentLinkFailedAlert (pipeline-decision.ts:182-185).
    acts = research._alert_actions_for("agent_link_failed", 2, "claude")
    assert acts == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "agent_decision", "agent": "claude", "decision": "retry"}},
        {"id": "skip", "label": "Skip Claude", "style": "default",
         "command": {"action": "agent_decision", "agent": "claude", "decision": "skip"}},
    ]


def test_agent_link_failed_no_longer_ai_upgrades():
    # §8.3: the ai_upgrade flag is DROPPED (wrong-surface re-emit + stop-path
    # resurrect risk). The row keeps its class + tokens.
    row = research.ALERT_INTENTS["agent_link_failed"]
    assert row["class"] == "recoverable"
    assert row["actions"] == ["retry_link", "skip_link"]
    assert "ai_upgrade" not in row


# ── 2. seam-authored events preserve the wire + add the additive fields ─────────

def test_login_required_event_is_agentless_with_additive_intent(monkeypatch):
    # The P0 login walk event carries NO agent field (emit_event drops falsy
    # agent); the seam preserves that + every legacy kwarg, and ADDS
    # intent/recoverability/decision_id (+ an FE-inert actions list).
    events, _ = _capture(monkeypatch)
    research.emit_decision(
        intent="login_required", event_name="login_required",
        phase=0, agent=None,
        facts={"title": "ChatGPT needs a login.", "details": ""},
        actions=research._alert_actions_for("login_required", 0, None),
        alert_id="phase0_login_required_chatgpt",
        platforms=["chatgpt"], platformLabels=["ChatGPT"],
        machineName="setup-pc", attempt=3, message="ChatGPT needs a login.")
    ev = _last(events, "login_required")
    # legacy wire fields preserved verbatim
    assert ev["platforms"] == ["chatgpt"] and ev["platformLabels"] == ["ChatGPT"]
    assert ev["machineName"] == "setup-pc" and ev["attempt"] == 3
    assert ev["message"] == "ChatGPT needs a login."
    assert ev["alert_id"] == "phase0_login_required_chatgpt"
    # agent-less wire shape (agent kwarg is None → emit_event drops it downstream;
    # the seam forwards agent=None as the top-level kwarg)
    assert ev.get("agent") is None
    # additive seam fields
    assert ev["intent"] == "login_required"
    assert ev["recoverability"] == "blocker"
    assert ev["decision_id"]
    # blocker → never a deadline
    assert "auto_skip_deadline" not in ev


def test_login_required_is_a_blocker_and_refuses_a_deadline(monkeypatch):
    _capture(monkeypatch)
    try:
        research.emit_decision(
            intent="login_required", event_name="login_required", phase=1,
            facts={"title": "x"}, actions=[], alert_id="x",
            auto_skip_deadline=123456)
        raise AssertionError("a blocker login card must refuse a deadline")
    except ValueError:
        pass


def test_hv_intent_split_and_agent_first_class(monkeypatch):
    # Cloudflare → hv_wall (hands_off); other → hv_solvable (blocker). Both carry
    # agent= as a first-class field + preserve platform/platformLabel/reason.
    events, _ = _capture(monkeypatch)
    research.emit_decision(
        intent="hv_wall", event_name="human_verification_required",
        phase=2, agent="gemini",
        facts={"title": "Gemini hit Cloudflare's check.", "details": ""},
        actions=research._alert_actions_for("hv_wall", 2, "gemini"),
        alert_id="phase2_human_verify_gemini",
        platform="gemini", platformLabel="Gemini",
        reason="cloudflare challenge", message="Gemini hit Cloudflare's check.")
    ev = _last(events, "human_verification_required")
    assert ev.get("agent") == "gemini"
    assert ev["platform"] == "gemini" and ev["platformLabel"] == "Gemini"
    assert ev["reason"] == "cloudflare challenge"
    assert ev["intent"] == "hv_wall" and ev["recoverability"] == "hands_off"
    # loop-local firer — no registry deadline stamped
    assert "auto_skip_deadline" not in ev


def test_hv_solvable_is_blocker(monkeypatch):
    events, _ = _capture(monkeypatch)
    research.emit_decision(
        intent="hv_solvable", event_name="human_verification_required",
        phase=2, agent="claude", facts={"title": "solve it"}, actions=[],
        alert_id="phase2_human_verify_claude", platform="claude")
    ev = _last(events, "human_verification_required")
    assert ev["intent"] == "hv_solvable" and ev["recoverability"] == "blocker"


def test_agent_link_gate_preserves_reason_and_options(monkeypatch):
    events, _ = _capture(monkeypatch)
    research.emit_decision(
        intent="agent_link_failed", event_name="agent_link_failed",
        phase=2, agent="claude",
        facts={"title": "Couldn't get Claude's report link",
               "details": "Claude finished but we couldn't grab its result link."},
        actions=research._alert_actions_for("agent_link_failed", 2, "claude"),
        alert_id="phase2_agent_link_claude",
        reason="link extraction failed", options=["retry", "skip"])
    ev = _last(events, "agent_link_failed")
    assert ev.get("agent") == "claude"
    assert ev["reason"] == "link extraction failed"
    assert ev["options"] == ["retry", "skip"]
    assert ev["intent"] == "agent_link_failed"
    assert ev["recoverability"] == "recoverable"
    # gate holds a global pause — no deadline
    assert "auto_skip_deadline" not in ev


def test_manual_brief_keeps_empty_actions_and_message(monkeypatch):
    # actions=[] is load-bearing (manual_brief_required RENDERS evt.data.actions);
    # the brief_input token stays unwired and is never reached.
    events, _ = _capture(monkeypatch)
    research.emit_decision(
        intent="manual_brief", event_name="manual_brief_required", phase=1,
        actions=[],
        facts={"title": "Type your research brief into chat, then press Resume."},
        message="Type your research brief into chat, then press Resume.",
        dismissible=True, alert_id="phase1_manual_brief_required")
    ev = _last(events, "manual_brief_required")
    assert ev["actions"] == []
    assert ev["message"] == "Type your research brief into chat, then press Resume."
    assert ev["intent"] == "manual_brief" and ev["recoverability"] == "blocker"
    assert ev["dismissible"] is True


def test_decision_id_reuse_updates_in_place(monkeypatch):
    # A re-card / re-emit that passes the captured decision_id keeps the SAME id
    # (never regenerated) so the live + hydrated cards update in one slot.
    _capture(monkeypatch)
    did = research.emit_decision(
        intent="login_required", event_name="login_required", phase=1,
        agent=None, facts={"title": "signed out"},
        actions=research._alert_actions_for("login_required", 1, "chatgpt"),
        alert_id="phase1_login_required_chatgpt")
    did2 = research.emit_decision(
        intent="login_required", event_name="login_required", phase=1,
        agent=None, facts={"title": "still signed out"},
        actions=research._alert_actions_for("login_required", 1, "chatgpt"),
        alert_id="phase1_login_required_chatgpt", decision_id=did)
    assert did2 == did


# ── 3. consumer-side dead-button fix (Claude 2-artifact hard-fail) ──────────────

def _fresh_controls():
    return research.PipelineControls() if hasattr(research, "PipelineControls") \
        else research._controls


def test_poll_consumes_agent_decision_scoped_to_the_agent():
    # The FE 2-artifact card sends {action:agent_decision, agent, decision} →
    # set_agent_decision. The NON-blocking park poll must now consume it, scoped
    # to the agent, and return the mapped verdict.
    c = _fresh_controls()
    c.pending_agent_decision = None
    c.pending_agent_decision_agent = ""
    c.skipped_agents = set()
    c.set_agent_decision("retry", "claude")
    assert c.poll_agent_decision("claude") == "retry"
    # consumed once — the second poll is back to pending
    assert c.poll_agent_decision("claude") == "pending"


def test_agent_decision_is_not_stolen_by_a_sibling_park():
    # A decision meant for claude must NOT be consumed by a gemini park poll
    # (the whole point of the agent scoping — parks run concurrently).
    c = _fresh_controls()
    c.pending_agent_decision = None
    c.pending_agent_decision_agent = ""
    c.skipped_agents = set()
    c.set_agent_decision("skip", "claude")
    assert c.poll_agent_decision("gemini") == "pending"   # not stolen
    assert c.poll_agent_decision("claude") == "skip"      # the right park gets it


def test_agent_decision_stop_maps_through_poll():
    c = _fresh_controls()
    c.pending_agent_decision = None
    c.pending_agent_decision_agent = ""
    c.skipped_agents = set()
    c.stop_event.clear()
    c.set_agent_decision("stop", "claude")
    assert c.poll_agent_decision("claude") == "stop"


def test_blocking_gate_still_pops_globally():
    # The prod-orphaned gate (wait_for_agent_decision) still pops the decision
    # globally — the agent scoping doesn't break the legacy pop path.
    c = _fresh_controls()
    c.set_agent_decision("retry", "claude")
    assert c.pop_agent_decision() == "retry"
    assert c.pending_agent_decision is None
    assert c.pending_agent_decision_agent == ""
