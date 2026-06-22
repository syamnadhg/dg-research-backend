"""Phoenix (model_refresh) Phase C1 — known-good model fallback.

User decision #1 (auto-adopt + verify + fallback): if the LATEST model can't
be verified into Deep Research, retry ONCE pinned to a known-good model before
the chat-mode gate fires — so a newer model that doesn't yet support DR
degrades to a working older model instead of a Skip. Source-inspection guards
(the pin pick is JS in a live page) + a behavioral check that the fallback
notice is an AMBER warning, never a red error (badge philosophy).
"""
import inspect
from unittest import mock

import research


def test_setup_functions_accept_pin_model():
    assert "pin_model=None" in inspect.signature(research.setup_claude_dr).__str__() or \
        "pin_model" in str(inspect.signature(research.setup_claude_dr))
    assert "pin_model" in str(inspect.signature(research.setup_gemini_dr))
    assert "pin_model" in str(inspect.signature(research._gemini_select_flash_model))


def test_pin_forces_exact_version_in_pickers():
    # Claude picker + Gemini ranker both branch on `pin` to target an EXACT
    # version (Math.abs(v - pin) ...), distinct from the floor "highest" path.
    sc = inspect.getsource(research.setup_claude_dr)
    assert "Math.abs(v - pin)" in sc and "({floor, pin})" in sc
    js = research._GEMINI_FLASH_RANK_JS
    assert "Math.abs(v - pin)" in js and "{floor, doClick, pin}" in js


def test_pin_forces_repick_even_when_model_already_ok():
    # The #744 "don't re-pick a correct model" guard must be BYPASSED when
    # pinning (the higher model is the one that just failed DR), so model_ok is
    # gated on `pin_model is None`.
    sc = inspect.getsource(research.setup_claude_dr)
    assert "model_ok = (pin_model is None)" in sc


def test_fallback_runs_before_the_chat_mode_gate_and_is_single_shot():
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    fb = src.find("known-good fallback")
    gate = src.find("_emit_chat_mode_alert(platform_l)")
    assert fb != -1 and gate != -1 and fb < gate, (
        "the known-good fallback must run BEFORE the chat-mode gate fires."
    )
    # ChatGPT (no model lever) is not eligible.
    assert 'platform_l in ("claude", "gemini")' in src
    # Fallback target is the canary known-good, else the policy floor.
    assert "p2_known_good(platform_l) or p2_floor(platform_l)" in src
    # Single-shot: the fallback block must not introduce a retry LOOP construct
    # (it's a straight-line `if`). Guard on actual loop syntax, not the English
    # word "for" that appears in the log strings.
    block = src[fb:gate]
    assert "range(" not in block and "while True" not in block, (
        "the known-good fallback must be straight-line (single attempt), not a loop."
    )
    # It pins the known-good model into the same invariant-safe setup functions.
    assert "setup_claude_dr(page, pin_model=_kg)" in src
    assert "setup_gemini_dr(page, pin_model=_kg)" in src


def test_drift_alert_is_amber_warning_not_red_error():
    # Badge philosophy: a "fell back / FYI" notice is a pipeline_warning
    # (alertType warn), NEVER a red pipeline_error.
    with mock.patch.object(research, "emit_event") as em:
        research._emit_model_drift_alert("gemini", "msg", "details")
    assert em.call_count == 1
    args, kwargs = em.call_args
    assert args[0] == "pipeline_warning", "must use pipeline_warning, not pipeline_error"
    assert kwargs.get("alertType") == "warn"
    assert kwargs.get("dismissible") is True
    assert kwargs.get("actions") == []  # informational, no decision buttons
