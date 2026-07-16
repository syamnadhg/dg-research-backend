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


def test_agent_failed_tokens():
    # #955: one "Retry" (restart) — no user-facing "hard"; the command carries
    # no `mode` (the dispatcher defaults a mode-less retry_agent to the restart).
    acts = research._alert_actions_for("agent_failed", 2, "gemini")
    assert acts == [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "retry_agent", "agent": "gemini"}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_agent", "agent": "gemini"}},
    ]


def test_retry_is_modeless_and_dispatcher_defaults_to_restart():
    # #955: one "Retry" for every agent card — no user-facing "hard", and the
    # command carries NO `mode`. Because a soft "please continue" can't recover a
    # broken/couldn't-start agent, the dispatcher must default a mode-less
    # retry_agent to the RESTART (close tab + re-run setup).
    retry = research._alert_actions_for("agent_failed", 2, "gemini")[0]
    assert retry["label"] == "Retry" and "hard" not in retry["label"].lower()
    assert "mode" not in retry["command"]
    src = inspect.getsource(research)
    assert 'data.get("mode") or "hard"' in src   # dispatcher default = restart


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
    # #955 Phase 4 wired pro_required + chat_mode. Phase 5A wired
    # login_required (skip_login) + hv_solvable (resume) + agent_link_failed
    # (retry_link/skip_link). Phase 5B wired crash_login_interrupt (retry_resume)
    # + crash_loop (retry_resume/discard) + env_missing_key (skip_login). The
    # ONLY remaining unwired token is brief_input (manual_brief): the site passes
    # an explicit actions=[] (type-in-chat, no button), so the expander is never
    # reached and the token stays intentionally unwired — a call that DID reach
    # it must still fail loudly rather than emit a wrong button.
    for intent in ("manual_brief",):
        try:
            research._alert_actions_for(intent, 2, "chatgpt")
            raise AssertionError(f"{intent} should raise until its phase wires it")
        except NotImplementedError:
            pass


# ── #955 Phase 4 — pro_required + chat_mode token expansion (byte-parity) ─────

def test_pro_required_actions_phase2_non_blocking():
    # Gap #1: at phase 2 the pro card is NON-BLOCKING. Two changes vs the old
    # inline dicts: (Finding 1) NO retry_phase action — a retry_phase(2) has no
    # round-robin consumer and the 120-min supervisor would restart the phase;
    # (Finding 2) "Continue with Free" is AGENT-SCOPED (continue_free{agent}),
    # not the global continue_anyway a sibling await_agent_decision would steal.
    acts = research._alert_actions_for("pro_required", 2, "gemini")
    assert acts == [
        {"id": "continue_with_free", "label": "Continue with Free", "style": "default",
         "command": {"action": "continue_free", "agent": "gemini"}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_agent", "agent": "gemini"}},
    ]


def test_pro_required_phase1_keeps_blocking_shape():
    # B1 guard: the P1 brief-gen pro gate is STILL BLOCKING and polls
    # consume_retry_phase(1) + consume_continue_anyway(). Its card must keep the
    # global continue_anyway command AND the Retry action — the non-blocking
    # rework is scoped to phase 2 only. (P0 is identical modulo skip target.)
    acts = research._alert_actions_for("pro_required", 1, "gemini")
    assert acts == [
        {"id": "continue_with_free", "label": "Continue with Free", "style": "default",
         "command": {"action": "continue_anyway"}},
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "retry_phase", "phase": 1}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_agent", "agent": "gemini"}},
    ]


def test_pro_ack_agents_is_agent_scoped_and_one_shot():
    # Gap #1 Finding 2: the non-blocking pro ack is a per-agent set, NOT the
    # global one-shot continue_anyway. Acking one agent must not consume
    # another's, and each ack is one-shot.
    c = research.PipelineControls()
    c.request_pro_continue_free("gemini")
    # sibling unaffected
    assert c.consume_pro_continue_free("chatgpt") is False
    # first consume True, second False (one-shot)
    assert c.consume_pro_continue_free("gemini") is True
    assert c.consume_pro_continue_free("gemini") is False
    # the global continue_anyway is untouched by the agent-scoped ack
    assert c.consume_continue_anyway() is False


def test_pro_required_skip_is_skip_init_verify_at_p0():
    acts = research._alert_actions_for("pro_required", 0, "chatgpt")
    assert acts[2] == {"id": "skip", "label": "Skip", "style": "default",
                       "command": {"action": "skip_init_verify"}}


def test_chat_mode_actions_keep_stop_and_named_skip():
    acts = research._alert_actions_for("chat_mode", 2, "claude")
    assert acts == [
        {"id": "continue_in_chat_mode", "label": "Continue in chat mode", "style": "default",
         "command": {"action": "continue_anyway"}},
        {"id": "skip_claude", "label": "Skip Claude", "style": "default",
         "command": {"action": "skip_agent", "agent": "claude"}},
        {"id": "stop", "label": "Stop", "style": "danger",
         "command": {"action": "stop"}},
    ]


def test_chat_mode_stamps_deadline_but_does_not_arm_the_registry(monkeypatch):
    # chat_mode is a SETUP-context card: its caller's await_agent_decision is the
    # firer, so the deadline is stamped on the EVENT (FE countdown) but the
    # round-robin registry is NOT armed (arm_registry=False) — the round-robin
    # can't reach an agent that isn't in its poll set yet (design G(ii)).
    calls = _capture(monkeypatch)
    research._pending_decisions.clear()
    research._emit_chat_mode_alert("gemini", auto_skip_deadline=999000)
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["intent"] == "chat_mode"
    assert pe["auto_skip_deadline"] == 999000       # FE countdown gets it
    assert research._pending_decisions == {}         # but the firer registry does NOT


def test_pro_required_blocker_never_arms_a_deadline(monkeypatch):
    # pro_required is a blocker (user resolves it); emit_decision refuses a
    # deadline on a blocker, and the emitter passes none.
    calls = _capture(monkeypatch)
    monkeypatch.setattr(research, "_persist_pending_decision", lambda *a, **k: None)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research._emit_pro_required_alert(phase=2, agent="chatgpt", source="t")
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["intent"] == "pro_required"
    assert pe["recoverability"] == "blocker"
    assert "auto_skip_deadline" not in pe


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
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "retry_agent", "agent": "gemini"}},
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
