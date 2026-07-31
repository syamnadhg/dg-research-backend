"""Phoenix (model_refresh) Phase A3 — the Claude CUA prompts derive their model
version from the central P2_MODEL_POLICY, not a hand-typed literal.

These guard that PROMPT_CLAUDE_DEEP_RESEARCH / PROMPT_VALIDATE_CLAUDE_SETUP
render the version tokens from p2_claude_ver/prev/major (so a floor bump tracks
through), with no unrendered f-string token leaking, and that the rendered text
is byte-identical to the legacy literal at the default floor (4.8).
"""
import inspect

import models
import prompts
import research


def test_no_unrendered_fstring_token_leaked():
    for name in ("PROMPT_CLAUDE_DEEP_RESEARCH", "PROMPT_VALIDATE_CLAUDE_SETUP"):
        s = getattr(prompts, name)
        assert "{_OPUS" not in s, f"{name} has an unrendered f-string token — the f-prefix or var is wrong."


def test_claude_dr_prompt_derives_version_from_policy():
    cur, prev = models.p2_claude_ver(), models.p2_claude_prev_ver()
    p = prompts.PROMPT_CLAUDE_DEEP_RESEARCH
    # The model the CUA is told to pick must be the policy floor, not a frozen literal.
    assert f'pick "Opus {cur}"' in p
    assert f'single "Opus {prev} Adaptive" option' in p
    assert f"if {cur}/Effort aren't present" in p
    assert f"If Opus {cur} + Max effort + Adaptive thinking are already set" in p


def test_claude_validate_prompt_derives_version_from_policy():
    cur, major = models.p2_claude_ver(), models.p2_claude_major()
    p = prompts.PROMPT_VALIDATE_CLAUDE_SETUP
    assert f'If it reads "Opus {cur}" — or any "Opus {major}.x"' in p
    assert f'pick "Opus {cur}", and close it' in p


def test_validate_user_msg_derives_version_from_policy():
    # The CUA validate user-message in research.py routes the version through
    # p2_claude_ver() and the effort label through p2_labels (not literals).
    src = inspect.getsource(research.validate_setup_with_cua)
    assert "p2_claude_ver()" in src, "the validate user_msg must derive the version"
    assert "p2_labels('claude')" in src, "and the effort label"
    assert '"Verify Opus 4.8 +' not in src, "the validate user_msg must not keep a hardcoded 4.8"


def test_validate_user_msg_treats_the_floor_as_a_floor():
    """2026-07-30. "Verify Opus 4.8" on an account already running Opus 5 made
    the validator reason "this is NOT Opus 4.8, so I need to fix it" and click
    into the model menu before self-correcting a step later — the second
    model-menu interaction reported as "the modal selector opens twice"."""
    src = inspect.getsource(research.validate_setup_with_cua)
    assert "OR NEWER" in src, "a higher Opus must be stated as correct"
    assert "leave it alone" in src, (
        "the validator must be told not to touch an at-or-above model — without "
        "this it opens the model menu on a healthy page"
    )
    assert "Adaptive thinking" not in src, (
        "Opus 5 has no Thinking toggle; asking the validator to confirm one "
        "guarantees a false negative on the quality knobs"
    )


def test_default_floor_renders_the_legacy_literals():
    # Byte-identity at the default floor: the exact phrases the prompts carried
    # before the refactor must still appear (4.8 / 4.7 / 4.x).
    assert 'pick "Opus 4.8"' in prompts.PROMPT_CLAUDE_DEEP_RESEARCH
    assert 'single "Opus 4.7 Adaptive" option' in prompts.PROMPT_CLAUDE_DEEP_RESEARCH
    assert 'If it reads "Opus 4.8" — or any "Opus 4.x"' in prompts.PROMPT_VALIDATE_CLAUDE_SETUP
