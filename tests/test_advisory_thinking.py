"""Phoenix (model_refresh) Phase C2 — advisory thinking-config verification.

User decision #4 = verify + SOFT-escalate (never hard-gate). setup_*_dr record
whether the policy thinking knobs (Claude max-effort + thinking toggle, Gemini
extended thinking) were confirmed; the caller surfaces a soft AMBER notice when
proceeding in research mode without them. The thinking knobs must NOT be part
of the success contract (model + Research tool stay the only hard gates), and
must NOT be re-read in ensure_deep_mode_active (the backend.log-49728 regression).
"""
import inspect

import research


def test_claude_thinking_flags_are_default_initialized():
    # Review fix: _think/_eff_set are bound only on the popover-opened path, so
    # the confirmation flags must be initialized up front (no unset-local read).
    src = inspect.getsource(research.setup_claude_dr)
    assert "_effort_confirmed = False" in src and "_thinking_confirmed = False" in src


def test_thinking_is_not_in_the_success_contract():
    # The hard gate stays model + research ONLY — thinking is advisory.
    src = inspect.getsource(research.setup_claude_dr)
    assert "return bool(opus_selected) and bool(research_enabled)" in src, (
        "thinking/effort must NOT be added to setup_claude_dr's success contract."
    )


def test_setup_records_thinking_state():
    sc = inspect.getsource(research.setup_claude_dr)
    sg = inspect.getsource(research._gemini_select_flash_model)
    assert '_P2_THINKING_STATE["claude"]' in sc
    assert '_P2_THINKING_STATE["gemini"]' in sg


def test_caller_thinking_advisory_is_telemetry_only_when_proceeding():
    # 2026-06-22 live finding: the thinking/effort confirmation false-alarms on
    # nearly every run (Claude folded Max-effort into Extended Pro, so the separate
    # control is absent). The advisory is now TELEMETRY ONLY — it logs the miss but
    # must NOT raise a user-facing alert, and must never reach the blocking gate.
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    adv = src.find("thinking-config telemetry (NO user alert)")
    assert adv != -1
    # Scope precisely to the telemetry section: from its comment up to the
    # chat-mode gate that follows it (avoids bleeding into that gate's code).
    block = src[adv:src.find("if not research_ok:", adv)]
    assert 'if research_ok and platform_l in ("claude", "gemini")' in block
    # It reads the recorded state + policy and logs the miss, but raises NOTHING.
    assert "_P2_THINKING_STATE.get(platform_l)" in block and "p2_labels(" in block
    assert "_emit_model_drift_alert(" not in block  # no amber alert (false-alarm)
    assert "_emit_chat_mode_alert" not in block     # never the red blocking gate


def test_ensure_deep_mode_active_still_excludes_thinking():
    # Guard against re-introducing the backend.log-49728 needless re-activation:
    # the pre-send check must NOT scan for thinking/effort.
    src = inspect.getsource(research.ensure_deep_mode_active)
    assert "_thinking_confirmed" not in src and "_P2_THINKING_STATE" not in src
