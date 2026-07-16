"""Alert → pause → auto-resume + phase-gating audit (2026-07-14).

The user's #1 pain: an alert FE-pauses the run, but resolutions (manual skip,
manual retry, and EVERY auto-action) leave it STUCK paused. Plus P1 and P2
ChatGPT alerts bled into each other because fail_agent hardcoded phase=2 and a
phase-LESS alert_id (`agent_{key}_error`) collided across phases.

These guard the BE half of the fix:
  - fail_agent now emits the LIVE phase + a phase-tokened alert_id, and its 5
    completion-retracts use the SAME helper so the retract id always matches.
  - _hv_auto_skip_finalize releases its HV pause (request_resume +
    pipeline_resumed) when it resolves an ACTIVE pause (the unacted-timeout
    caller), never on the setup-fail caller.
  - the chat-mode gate skip/timeout branches emit pipeline_resumed AND mark
    skipped_agents (suppresses the caller's contradictory red card).
  - the retry_agent intake (soft + hard) emits pipeline_resumed so every
    surface auto-resumes.

Run: pytest tests/test_p2_alerts_pause_resume.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

MOD_SRC = inspect.getsource(research)
FAIL_AGENT_SRC = inspect.getsource(research.fail_agent)
HV_FINALIZE_SRC = inspect.getsource(research._hv_auto_skip_finalize)
START_AGENT_SRC = inspect.getsource(research.start_agent_no_gemini_wait)


# ── Phase-gated per-agent error id ────────────────────────────────────────────

def test_agent_error_alert_id_is_phase_tokened(monkeypatch):
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    assert research._agent_error_alert_id("chatgpt") == "phase2_agent_chatgpt_error"
    assert research._agent_error_alert_id("gemini", 1) == "phase1_agent_gemini_error"


def test_agent_error_alert_id_distinguishes_p1_and_p2_same_agent():
    # The whole point: a P1 chatgpt card and a P2 chatgpt card must NOT share an
    # id (else they co-dismiss / co-dedup / cross-hydrate).
    assert (research._agent_error_alert_id("chatgpt", 1)
            != research._agent_error_alert_id("chatgpt", 2))


def test_agent_error_alert_id_defaults_to_two_when_phase_unknown(monkeypatch):
    monkeypatch.setattr(research._runtime, "phase", None, raising=False)
    assert research._agent_error_alert_id("claude") == "phase2_agent_claude_error"


# ── fail_agent honors the live phase ──────────────────────────────────────────

def _capture_fail_agent(monkeypatch, live_phase):
    calls = []
    monkeypatch.setattr(research, "emit_event",
                        lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(research, "_write_agent_terminal_status",
                        lambda *a, **k: None)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    monkeypatch.setattr(research._runtime, "phase", live_phase, raising=False)
    return calls


def test_fail_agent_p2_emits_phase2_and_tokened_id(monkeypatch):
    calls = _capture_fail_agent(monkeypatch, 2)
    research.fail_agent("chatgpt", "ChatGPT didn't start", "details")
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["phase"] == 2
    assert pe["alert_id"] == "phase2_agent_chatgpt_error"


def test_fail_agent_p1_context_is_not_mislabeled_phase2(monkeypatch):
    # A relaunch/setup failure while the run is in Phase 1 must be tagged phase
    # 1 (routes to the P1 phase tile, not the P2 agent slot). Pre-fix this was
    # hardcoded phase=2 and leaked a P1 ChatGPT failure into the P2 dropdown.
    calls = _capture_fail_agent(monkeypatch, 1)
    research.fail_agent("chatgpt", "ChatGPT session expired")
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["phase"] == 1
    assert pe["alert_id"] == "phase1_agent_chatgpt_error"


def test_fail_agent_explicit_phase_override(monkeypatch):
    calls = _capture_fail_agent(monkeypatch, 2)
    research.fail_agent("gemini", "t", phase=1)
    pe = next(k for (a, k) in calls if a and a[0] == "pipeline_error")
    assert pe["phase"] == 1
    assert pe["alert_id"] == "phase1_agent_gemini_error"


def test_fail_agent_docstring_declares_phase_qualified_id():
    assert "phase<phase>_agent_<key>_error" in FAIL_AGENT_SRC


# ── retracts must use the SAME helper (id always matches the card) ─────────────

def test_no_stale_phaseless_agent_error_ids_remain():
    # Every fail_agent-card retract must be phase-tokened via the helper — a
    # leftover bare `agent_{key}_error` would MISS the (now phase-tokened) card
    # and leave a stale red card up.
    assert 'alert_id=f"agent_{agent_key}_error"' not in MOD_SRC
    assert 'alert_id=f"agent_{_agent_key}_error"' not in MOD_SRC
    assert 'alert_id=f"agent_{agent_key_stuck}_error"' not in MOD_SRC
    assert 'alert_id="agent_gemini_error"' not in MOD_SRC


def test_retracts_route_through_the_id_helper():
    # 5 completion/recovery retracts + the fail_agent emit all go through the
    # single helper so they can never drift.
    assert MOD_SRC.count("_agent_error_alert_id(") >= 6


# ── HV auto-skip finalize releases its pause ──────────────────────────────────

def test_hv_finalize_has_release_pause_param():
    assert "release_pause" in inspect.signature(research._hv_auto_skip_finalize).parameters


def test_hv_finalize_resumes_only_when_release_pause():
    # The resume is GATED on release_pause so the setup-fail caller (no active
    # pause) can't spuriously drop an unrelated agent's pause.
    assert "if release_pause:" in HV_FINALIZE_SRC
    assert "_controls.request_resume()" in HV_FINALIZE_SRC
    assert 'emit_event("pipeline_resumed"' in HV_FINALIZE_SRC


def test_hv_finalize_resume_precedes_the_informational_warning():
    # pipeline_resumed must fire BEFORE the auto_clear_on_resume warning, else
    # the FE's resume sweep wipes the "skipped automatically" notice.
    resume_at = HV_FINALIZE_SRC.index('emit_event("pipeline_resumed"')
    warn_at = HV_FINALIZE_SRC.index('emit_event("pipeline_warning"')
    assert resume_at < warn_at


def test_hv_unacted_timeout_caller_releases_pause():
    # The wait_for_verification_clearance timeout path (an ACTIVE pause) must
    # pass release_pause=True; grep the module for that call shape.
    assert "release_pause=True" in MOD_SRC


# ── chat-mode gate skip auto-resumes + suppresses the red card ────────────────

def test_chat_mode_gate_is_non_blocking():
    # Gap #1: the chat_mode gate no longer pauses the pipeline (which froze the
    # sequential setup coroutine + starved siblings for up to 30 min). It submits
    # the brief in chat mode, records chat_mode_pending, and falls through — so
    # start_agent has NO request_pause / await_agent_decision for chat_mode.
    assert 'request_pause(f"{platform_l}_chat_mode")' not in START_AGENT_SRC
    assert "await_agent_decision(platform_l" not in START_AGENT_SRC
    assert "chat_mode_pending[platform_l]" in START_AGENT_SRC


def test_chat_mode_marker_popped_on_send_failure():
    # Gap #1 (adversarial finding): the chat_mode gate sets chat_mode_pending
    # BEFORE the mode-agnostic Send. If Send fails (brief chip lost + re-attach/
    # re-paste failed), the marker must be undone — else a Send-failed but
    # /c/-alive ChatGPT hands off to the round-robin, parks kind=chat_mode, and
    # its fail-card Retry is silently converted to a skip by the parked resolver.
    assert START_AGENT_SRC.count("chat_mode_pending.pop(platform_l, None)") >= 2


def test_chat_mode_resolution_lives_in_round_robin():
    # Gap #1: keep/skip for a chat_mode-parked agent is resolved by the
    # round-robin's parked-decision resolver (continue → keep + finalize;
    # timeout → discard + auto-skip grey+close), NOT inline in start_agent. The
    # gate itself no longer marks skipped_agents for chat_mode.
    res = inspect.getsource(research._resolve_parked_agent_decision)
    assert 'if kind == "chat_mode":' in res
    assert 'copy_key="chat_mode"' in res
    assert START_AGENT_SRC.count("_controls.skipped_agents.add(platform_l)") == 0


# ── retry_agent intake auto-resumes every surface ─────────────────────────────

def test_retry_agent_intake_emits_pipeline_resumed():
    # Soft AND hard retry each schedule a pipeline_resumed so a second tab /
    # phone / cold reopen unpauses too (the acting tab clears optimistically).
    assert MOD_SRC.count('reason="agent_retry"') >= 2


def test_retry_agent_resume_scheduled_on_loop_thread():
    # emit_event does Firestore I/O + mutates loop-thread state — it must be
    # scheduled via call_soon_threadsafe, not called on the listener thread.
    assert 'call_soon_threadsafe(\n                        lambda a=_ag_norm: emit_event(' in MOD_SRC
