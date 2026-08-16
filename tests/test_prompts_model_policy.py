"""Every CUA / vision prompt is FAMILY-ONLY — no model version, anywhere.

Rewritten 2026-08-01. These used to assert the OPPOSITE: that the prompts
rendered "4.8" / "4.7" / "4.x" from the policy floor, and that the rendered text
was byte-identical to the older hand-typed literals. Deriving a version from a
constant still rots as TEXT — telling the agent to "pick Opus 4.8" on an account
already running Opus 5 made it reason "this is NOT Opus 4.8, so I need to fix
it" and open the model menu (the "selector opens twice" report). Owner directive:
"only model family is gonna be there and both dom and CUA (fallback) must auto
heal on every model release."

The one thing every test here enforces: a digit next to a model name is a bug.
"""
import inspect
import re

import models
import prompts
import research

# Prompts that drive or judge a model choice. A version number in ANY of these
# is the rot this whole change removes.
_MODEL_PROMPTS = (
    "PROMPT_CLAUDE_DEEP_RESEARCH",
    "PROMPT_VALIDATE_CLAUDE_SETUP",
    "PROMPT_SELECT_PRO",
    "PROMPT_DETECT_CHATGPT_PRO",
    "PROMPT_DETECT_CLAUDE_PRO",
    "PROMPT_DETECT_GEMINI_PRO",
)

# "Opus 4.8", "GPT-5", "gpt-4o", "2.5 Pro", "3.5 Flash", "o1 pro" …
_VERSIONED_MODEL = re.compile(
    r"(?:opus|sonnet|haiku|flash|gemini|gpt|claude|o\d)\s*[-–]?\s*\d"
    r"|\d+(?:\.\d+)?\s*(?:pro|flash|opus|sonnet|deep\s*think)",
    re.IGNORECASE,
)


def test_no_unrendered_fstring_token_leaked():
    for name in _MODEL_PROMPTS:
        s = getattr(prompts, name)
        assert "{_OPUS" not in s and "{_CL_EFFORT" not in s, (
            f"{name} has an unrendered f-string token — the f-prefix or var is wrong."
        )


def test_no_prompt_names_a_model_version():
    """⭐ THE DIRECTIVE, AS ONE ASSERTION. Catches a version reintroduced by
    hand AND one that arrives derived from a policy value — both rot the same
    way, because what reaches the agent is the rendered text."""
    offenders = []
    for name in _MODEL_PROMPTS:
        for m in _VERSIONED_MODEL.finditer(getattr(prompts, name)):
            offenders.append(f"{name}: …{m.group(0)!r}…")
    assert not offenders, "version-pinned model names in prompts:\n  " + "\n  ".join(offenders)


def test_version_tokens_are_no_longer_importable():
    """`_OPUS` is now the FAMILY word. The version renderers are gone from
    models entirely, so a prompt cannot re-acquire one by importing."""
    assert prompts._OPUS == models.p2_family("claude").capitalize()
    assert not any(ch.isdigit() for ch in prompts._OPUS)
    for gone in ("p2_claude_ver", "p2_claude_prev_ver", "p2_claude_major"):
        assert not hasattr(models, gone)


def test_claude_dr_prompt_asks_for_the_family_and_the_highest_of_it():
    p = prompts.PROMPT_CLAUDE_DEEP_RESEARCH
    fam = models.p2_family("claude").capitalize()
    assert fam in p
    assert "VERSION NUMBER DOES NOT MATTER" in p, (
        "the agent must be told the number is irrelevant, or a mismatch reads "
        "as something to fix"
    )
    assert "HIGHEST" in p, "the CUA path must still upgrade to the newest offered"


def test_claude_dr_prompt_agrees_with_the_directive_it_ships_with():
    """⭐ These two go to the SAME CUA call — PROMPT_CLAUDE_DEEP_RESEARCH as the
    system prompt, p2_claude_setup_directive() as the user message. They
    contradicted each other after the family-only rewrite: the system prompt
    said "leave it alone" while the directive said "open the menu once and pick
    the highest", which is a coin-flip between upgrading and never upgrading on
    the one path that fires precisely because the DOM could not."""
    p = prompts.PROMPT_CLAUDE_DEEP_RESEARCH
    d = models.p2_claude_setup_directive()
    for text, who in ((p, "system prompt"), (d, "setup directive")):
        low = text.lower()
        assert "highest" in low, f"the {who} must ask for the newest offered"
        assert "once" in low, f"the {who} must bound it to a single menu open"
        assert "without clicking" in low, (
            f"the {who} must not re-click a model that is already the highest"
        )
    # …and neither may tell the agent to leave a WRONG model alone: the escape
    # hatch for a Sonnet account is what stops it being stranded forever.
    assert "not open the model menu" not in p.lower(), (
        "that rule belongs to the VALIDATE prompt, which runs after the DOM "
        "path succeeded — here it would remove the last upgrade lever"
    )


def test_claude_validate_prompt_accepts_any_version_including_none():
    p = prompts.PROMPT_VALIDATE_CLAUDE_SETUP
    assert "followed by ANY version number" in p
    assert "with no number at all" in p, (
        "a version-LESS label is the endpoint of the naming trend this change "
        "responds to; the validator must not read it as a wrong model"
    )


def test_validate_user_msg_comes_from_the_policy_module():
    """⚠ Asserted on the RENDERED string, not on research.py source. The message
    used to be an f-string built inline across several source lines, so a
    grep-the-source assertion silently passed or failed on where the author
    happened to wrap — it could not see the text the agent actually receives."""
    src = inspect.getsource(research.validate_setup_with_cua)
    assert "p2_claude_validate_directive(" in src, (
        "the validate user_msg must render from the policy module"
    )
    # ⭐ …and it must render with the family THIS RUN is on, not the policy
    # default. The validator's rule is "only touch the model if the button does
    # not name <fam>": frozen to the primary family, that clause fires on the
    # CORRECT model for every pass of a run that fell back to the fallback
    # family, and sends the validator into a menu whose only primary-family rows
    # are the sales chips the DOM layer just refused. Both the system prompt and
    # the user message go to ONE call, so both have to learn the family.
    for call in ("p2_claude_validate_directive(_p2_active_family(\"claude\"))",
                 "claude_validate_setup_prompt(_p2_active_family(\"claude\"))"):
        assert call in src, f"the validate CUA call must be family-scoped: missing {call}"
    assert "p2_claude_ver" not in src, "the version renderer is gone"
    d = models.p2_claude_validate_directive()
    fam = models.p2_family("claude").capitalize()
    effort = str(models.p2_labels("claude").get("effort")).capitalize()
    assert fam in d and f"{effort} effort" in d


def test_validate_directive_says_the_version_is_irrelevant():
    """Runs after a DOM setup that SUCCEEDED, so its job is to leave the model
    alone — the DOM has already taken the highest offered."""
    d = models.p2_claude_validate_directive()
    assert "THE VERSION NUMBER DOES NOT MATTER" in d
    assert "leave it alone and do NOT open the model menu" in d, (
        "the validator must be told not to touch a correct model — without this "
        "it opens the model menu on a healthy page"
    )
    assert "Adaptive thinking" not in d, (
        "Opus 5 has no Thinking toggle; asking the validator to confirm one "
        "guarantees a false negative on the quality knobs"
    )


def test_validate_directive_carries_no_version():
    d = models.p2_claude_validate_directive()
    assert not _VERSIONED_MODEL.search(d), (
        f"a model version leaked into the validate directive: {d!r}"
    )


def test_the_two_cua_directives_differ_on_opening_the_menu():
    """⭐ The distinction the whole double-modal fix rests on. Setup fires only
    after the DOM path FAILED and must be free to open the menu and upgrade;
    validate fires after it SUCCEEDED and must not touch the model. Collapsing
    them either way reintroduces a shipped bug."""
    setup = models.p2_claude_setup_directive().lower()
    validate = models.p2_claude_validate_directive().lower()
    assert "open the model menu" in setup and "highest" in setup
    assert "do not open the model menu" in validate
    assert "highest" not in validate, (
        "asking the validator for the highest model requires it to open the menu"
    )


def test_tier_detection_matches_the_plan_word_not_a_model_name():
    """Phase-0 PRO/FREE detection listed specific model names on BOTH sides.
    Those lists go wrong on their own schedule: a name that moves from the paid
    tier to the free one flips the verdict with no code change."""
    def flat(s):
        # These prompts are hard-wrapped, so a phrase can straddle a newline —
        # normalise before matching rather than pinning where the author wrapped.
        return " ".join(s.split())
    assert 'ends in (or contains) the word "Pro"' in flat(prompts.PROMPT_DETECT_CHATGPT_PRO)
    assert "with or without a version number" in flat(prompts.PROMPT_DETECT_CLAUDE_PRO)
    assert "never on a version number" in flat(prompts.PROMPT_DETECT_GEMINI_PRO)


def test_tier_detection_still_rejects_an_upgrade_cta():
    """"Upgrade to Pro" contains the tier word while meaning the opposite. With
    the model names gone the word "Pro" carries more weight, so this guard
    matters more than it did."""
    assert "OPPOSITE of a Pro signal" in prompts.PROMPT_DETECT_CHATGPT_PRO


def test_select_pro_matches_the_word_and_takes_the_highest():
    p = prompts.PROMPT_SELECT_PRO
    assert "match on \"Pro\"" in p
    assert "highest-numbered one" in p, (
        "when several Pro options exist the newest is the right one"
    )
    assert "sales prompt, not the model" in p, "an upgrade CTA is not the picker"
