"""#709 — the Deep-Research chat-mode gate is generalized to all P2 agents.

E2/DGOPS-7364 added a gate that pauses + surfaces a decision alert when an
agent can't enable Deep Research (so it doesn't silently run in chat mode and
green-tick a fast chat answer as a "Deep Research" result). It was Claude-only
with the comment "ChatGPT/Gemini filed separately if they exhibit the same
regression." #709 IS that filing — last E2E both ChatGPT (Extended Pro) and
Gemini (Flash) stuck in chat mode. The gate + alert are now platform-general.
Source-inspection guards on research.py + prompts.py.
"""
import inspect

import research
import prompts


def test_chat_mode_alert_is_platform_parameterized():
    assert hasattr(research, "_emit_chat_mode_alert"), (
        "the chat-mode alert must be generalized to _emit_chat_mode_alert("
        "platform) (#709)."
    )
    src = inspect.getsource(research._emit_chat_mode_alert)
    # Must build agent/alert_id/source from the platform argument, not hardcode
    # 'claude'.
    assert "platform_l" in src and "phase2_{platform_l}_chat_mode" in src, (
        "the alert must derive its agent/alert_id from the platform arg (#709)."
    )
    # Back-compat shim retained for the original Claude call sites.
    assert hasattr(research, "_emit_claude_chat_mode_alert"), (
        "the Claude alert name must remain as a back-compat shim (#709)."
    )


def test_send_gate_runs_for_chatgpt_and_gemini():
    # The gate lives in the agent-setup routine; scan the whole module source
    # for the generalized guard literals rather than guessing the fn name.
    mod_src = inspect.getsource(research)
    assert 'if platform_l in ("claude", "gemini", "chatgpt"):' in mod_src, (
        "the chat-mode gate must run for all three P2 agents, not Claude "
        "only (#709)."
    )
    # The non-Claude branch must gate on the `active` flag from mode_state.
    assert 'research_ok = bool((mode_state or {}).get("active"))' in mod_src, (
        "ChatGPT/Gemini must gate the send on mode_state['active'] (#709)."
    )
    # The generalized alert must be invoked with the platform.
    assert "_emit_chat_mode_alert(platform_l)" in mod_src, (
        "the gate must call the generalized _emit_chat_mode_alert(platform_l) "
        "(#709)."
    )


def test_gemini_validate_prompt_requires_placeholder():
    p = prompts.PROMPT_VALIDATE_GEMINI_SETUP
    assert "What do you want to research?" in p, (
        "the Gemini CUA validate prompt must require the research-mode "
        "placeholder as proof of active DR (#709)."
    )
    # Must explicitly reject treating a merely-visible chip as active.
    assert "merely" in p.lower() and "not" in p.lower(), (
        "the prompt must tell the CUA a merely-visible chip is NOT proof of "
        "active Deep Research (#709)."
    )


# ── #744 — the Claude gate honors a POSITIVE CUA confirmation only ────


def test_validate_setup_returns_ok_and_confirmed_tuple():
    """#744: validate_setup_with_cua must return (ok, confirmed). `confirmed`
    is True ONLY on a positive verified/fixed verdict — an ambiguous or errored
    validation is ok=True (don't block) but confirmed=False (no proof DR is on)."""
    src = inspect.getsource(research.validate_setup_with_cua)
    assert "return True, True" in src, (
        "a positive verified/fixed verdict must return (ok=True, confirmed=True) (#744)."
    )
    assert "return False, False" in src, (
        "an explicit 'failed' verdict must return (ok=False, confirmed=False) (#744)."
    )
    # Ambiguous AND error paths must be ok-but-not-confirmed.
    assert src.count("return True, False") >= 2, (
        "ambiguous and error paths must return (ok=True, confirmed=False) so they "
        "never count as proof Deep Research is on (#744)."
    )


def test_claude_gate_keys_on_positive_confirmation_not_loose_ok():
    """#744: the Claude chat-mode gate must OR the POSITIVE `cua_confirmed`
    signal, NOT the loose `cua_ok` (which is also True on ambiguous/error and
    would let a real chat-mode degradation slip through silently, #709)."""
    mod_src = inspect.getsource(research)
    assert 'cua_ok, cua_confirmed = await validate_setup_with_cua(' in mod_src, (
        "the call site must unpack the (ok, confirmed) tuple (#744)."
    )
    assert ('research_ok = bool((mode_state or {}).get("researchOn")) '
            "or bool(cua_confirmed)") in mod_src, (
        "the Claude gate must OR the positive cua_confirmed, not researchOn alone (#744)."
    )
    assert 'or bool(cua_ok)' not in mod_src, (
        "the gate must NOT key on the loose cua_ok (True on ambiguous/error) (#744)."
    )
