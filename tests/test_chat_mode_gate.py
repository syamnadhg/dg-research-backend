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
from conftest import code_only


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
    # The generalized alert must be invoked with the platform. #955 Phase 4
    # stamps a 30-min countdown deadline on it (behavior #8: was a 3h wait).
    assert "_emit_chat_mode_alert(platform_l, auto_skip_deadline=" in mod_src, (
        "the gate must call the generalized _emit_chat_mode_alert(platform_l) "
        "with the stamped auto-skip deadline (#709 / #955 Phase 4)."
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
    """#744: the Claude chat-mode gate must OR a POSITIVE confirmation, NOT the
    loose `cua_ok` (which is also True on ambiguous/error and would let a real
    chat-mode degradation slip through silently, #709).

    Wave 4 widened WHERE that positive confirmation may come from — the CUA
    validator's verified/fixed verdict OR the setup ladder's own outcome probe —
    so the assertion is re-pointed at `setup_confirmed`. What may NOT change is
    the shape: a positive signal is OR-ed in, and the loose ok never is.
    """
    mod_src = code_only(inspect.getsource(research))
    assert "_confirmed = await validate_setup_with_cua(" in mod_src, (
        "the call site must still unpack the (ok, confirmed) tuple (#744)."
    )
    assert ('research_ok = bool((mode_state or {}).get("researchOn")) '
            "or bool(setup_confirmed)") in mod_src, (
        "the Claude gate must OR a positive confirmation, not researchOn alone (#744)."
    )
    assert 'or bool(cua_ok)' not in mod_src, (
        "the gate must NOT key on the loose cua_ok (True on ambiguous/error) (#744)."
    )


def test_positive_confirmation_accepts_either_source_and_only_positive_ones():
    """`setup_confirmed` is the successor to `cua_confirmed`: it must be true for
    a positive CUA verdict OR a verified ladder, and for nothing else.

    The failure this guards is specific. The ladder can now SKIP the CUA
    validation rung, so `_cua_verdict['confirmed']` is simply absent on the happy
    path — and a `.get(..., True)`-style default there would hand the chat-mode
    gate a fabricated confirmation on every run where the validator never spoke.
    """
    mod_src = code_only(inspect.getsource(research))
    assert ('setup_confirmed = bool(_cua_verdict.get("confirmed")) '
            'or bool(_ladder.get("verified"))') in mod_src, (
        "setup_confirmed must be the OR of the CUA verdict and the ladder's "
        "verified flag — and must default to absent-is-false."
    )
    # The "validation failed — proceeding anyway" warning must live INSIDE the
    # rung that produces the verdict. Hoisting it back out re-introduces the
    # question of what `ok` defaults to when the rung never ran, and the only
    # available default (True) then reads as a verdict nobody gave.
    rung = code_only(inspect.getsource(research))
    idx = rung.index("async def _rung_cua_validate():")
    body = rung[idx:idx + 900]
    assert "if not _ok:" in body and "CUA validation failed" in body, (
        "the failed-validation warning belongs to the rung, not to the caller"
    )


def test_bringing_the_agent_tab_to_front_no_longer_rides_on_the_skippable_rung():
    """`validate_setup_with_cua` opens with `switch_to_page(page)`, and the brief
    is typed/pasted into that tab afterwards. Once the ladder can SKIP that rung,
    the focus guarantee has to be stated where it is needed rather than inherited
    from a surface that may not run."""
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    # ⚠ Scoped to the window between the DOM setup and the ladder. A bare
    # "appears somewhere in the function" assertion passes on the switch_to_page
    # in the REUSE-PAGE branch a thousand lines earlier — a mutation that deleted
    # the new one survived exactly that way.
    _, _, after_setup = src.partition('log(f"[{label}] Playwright-direct setup OK")')
    window, _, _ = after_setup.partition("_ladder = await _run_intent_ladder(")
    assert "await browser.switch_to_page(page)" in window, (
        "the agent tab must be brought to front between the DOM setup and the "
        "ladder, independently of whether the validation rung runs"
    )
