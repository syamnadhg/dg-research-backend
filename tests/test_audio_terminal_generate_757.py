"""#757-A — NotebookLM duplicate-audio fix: make the Generate click TERMINAL.

OBSERVED root cause (4 E2Es, 2026-06-02): after a legitimate, correctly-
configured Generate, the CUA agent_loop kept going (driven by SYSTEM_BASE's
"POST-ACTION VERIFY" habit) and on the very next iteration clicked the Audio
Overview card body to "verify" — which fires NotebookLM's one-click DEFAULT
audio = a SECOND card. The clean run never did that probe → 1 card. Logged
misclick was at iter ~4, the iteration right after Generate at iter ~3.

Two fixes, both guarded here:

  (1) prompts.make_prompt_audio_generate — step 7 is now TERMINAL: after the
      single Generate click, CUA must not click ANYTHING (explicitly overriding
      the post-action-verify habit), only read the screenshot it already has and
      say "generating". This makes agent_loop exit at `not tool_uses` the moment
      CUA stops acting, so the card-body misclick never happens.

  (2) research.run_phase3_audio — the NON-reuse verify call no longer hands
      wait_until_verified a cua_client. Its retry-7 escalation runs
      PROMPT_FIX_ISSUE ("click any needed buttons"), and on a finished/empty
      notebook the only thing it can click to "fix" is the card body → the same
      duplicate. Fix B had already closed the reuse path; this closes the
      non-reuse path. The code-side _check_audio_generating + the download poll
      loop are the authoritative backstops, so a missed verify only WARNs.

NOT changed (deliberate): max_iterations stays 15. The misclick is at iter ~4,
so no cap ≥ 4 prevents it; and the long-variant customize flow can legitimately
need ~10 iters, so lowering to 6 would truncate a valid run before Generate and
produce NO audio — a worse failure than a detectable duplicate.

Run:  pytest tests/test_audio_terminal_generate_757.py -v
"""
import inspect

import prompts
import research


# ── (1) The prompt is terminal ───────────────────────────────────────────────

def _gen_prompt(variant="long"):
    return prompts.make_prompt_audio_generate(variant)


def test_generate_is_marked_final_click_all_variants():
    # Every length variant must label the Generate click as the FINAL click so
    # the model has no license to click again.
    for v in ("short", "default", "long"):
        p = _gen_prompt(v)
        assert "FINAL click" in p, (
            f"[{v}] the Generate step no longer flags itself as the FINAL click "
            f"— the terminal guarantee is gone"
        )


def test_no_click_after_generate_overrides_post_action_verify():
    # The terminal step must explicitly neutralize SYSTEM_BASE's post-action
    # verify habit (the documented cause of the verify-click duplicate).
    p = _gen_prompt("long")
    low = p.lower()
    assert "post-action verify" in low or "post action verify" in low, (
        "step 7 no longer references / overrides the post-action-verify habit "
        "that drives the card-body misclick"
    )
    assert "override" in low, "step 7 no longer OVERRIDES the verify habit"
    # The card body / tile is named as the forbidden target.
    assert "card" in low and ("tile" in low or "thumbnail" in low), (
        "step 7 no longer forbids clicking the card / tile after Generate"
    )


def test_terminal_step_warns_duplicate_is_unrecoverable():
    # The model must be told WHY: a post-Generate click fires a second default
    # audio that can't be undone — that's the whole point of the no-delete world.
    p = _gen_prompt("long").lower()
    assert "second" in p and "default audio" in p, (
        "step 7 no longer warns that a stray click fires a SECOND default audio"
    )


def test_says_generating_as_terminal_text_only():
    # The exit condition is unchanged: say "generating" — but now as the LAST
    # thing, with no trailing action, so agent_loop ends on a text-only turn.
    p = _gen_prompt("long").lower()
    assert "generating" in p
    assert "stop" in p, "step 7 no longer tells the model to STOP after generating"


# ── (2) The non-reuse verify path drops the CUA fix vector ────────────────────

def _phase3_src():
    return inspect.getsource(research.run_phase3_audio)


def test_nonreuse_verify_passes_no_cua_client():
    # The non-reuse branch must call wait_until_verified WITHOUT a live
    # cua_client, so its retry-7 PROMPT_FIX_ISSUE can't click the card body.
    src = _phase3_src()
    # The reuse branch sets verified=True; the else branch is the verify call.
    else_block = src.split("if _reuse_existing:", 1)[1].split("if not verified:", 1)[0]
    assert "cua_client=None" in else_block, (
        "the non-reuse Phase-3 audio verify no longer passes cua_client=None — "
        "wait_until_verified's retry-7 'click any needed buttons' fix can fire a "
        "duplicate default audio again"
    )
    # And it must NOT pass the live client there.
    assert "cua_client=cua_client" not in else_block, (
        "the non-reuse verify call is handing wait_until_verified the live "
        "cua_client again — the retry-7 misclick vector is back open"
    )


# ── (2b) The poll-loop completion CHECK is read-only / no-click ───────────────
# Third duplicate vector (surfaced in adversarial review): the poll loop calls
# agent_loop(make_prompt_audio_check) with the REAL cua_client every 90s. The
# prompt issues no click steps but carries SYSTEM_BASE's POST-ACTION VERIFY, so
# a "verify" click on the card could fire a default audio. The check prompt now
# forbids all clicks explicitly.

def test_audio_check_prompt_is_read_only_no_click():
    for v in ("short", "default", "long"):
        c = prompts.make_prompt_audio_check(v).lower()
        assert "read-only check" in c, (
            f"[{v}] the audio completion-check prompt no longer declares itself "
            f"READ-ONLY — a verify-click can fire a duplicate default audio"
        )
        assert "do not click anything" in c, (
            f"[{v}] the audio completion-check prompt no longer forbids ALL clicks"
        )
        assert "duplicate" in c, (
            f"[{v}] the check prompt no longer warns a click fires a DUPLICATE"
        )


# ── (2c) Legacy alias delegates to the hardened factory (no stale literal) ────

def test_legacy_alias_delegates_to_factory():
    # The backward-compat PROMPT_AUDIO_GENERATE must equal the factory's "long"
    # output, so it can never serve the old non-terminal (duplicate-prone) copy.
    assert prompts.PROMPT_AUDIO_GENERATE == prompts.make_prompt_audio_generate("long"), (
        "PROMPT_AUDIO_GENERATE diverged from make_prompt_audio_generate('long') "
        "again — the stale non-terminal step 7 footgun is back"
    )
    assert "FINAL click" in prompts.PROMPT_AUDIO_GENERATE, (
        "the legacy alias lost the terminal-Generate hardening"
    )


# ── (3) max_iterations stays 15 (anti-regression on the deliberate choice) ────

def test_generate_loop_keeps_max_iterations_15():
    # Lowering this was explicitly rejected: the misclick is at iter ~4 (a lower
    # cap can't stop it) and the long-variant flow can need ~10 iters (a low cap
    # truncates a valid run → no audio). Guard the decision.
    src = _phase3_src()
    # The generate agent_loop call uses the long-form make_prompt_audio_generate.
    # #778 added a panel_already_open kwarg to the call, so split on the prefix
    # (no closing paren) to stay tolerant of extra kwargs.
    gen_call = src.split("make_prompt_audio_generate(podcast_length", 1)[1].split(
        "stop_narration_ticker", 1)[0]
    assert "max_iterations=15" in gen_call, (
        "the audio-generate agent_loop max_iterations changed from 15 — lowering "
        "it does NOT stop the iter-4 misclick and risks truncating the long-"
        "variant customize flow before Generate (no audio at all)"
    )
