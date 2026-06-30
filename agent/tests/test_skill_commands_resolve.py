"""Guard: every command the SKILL.md tells the agent to run is a REAL sr.py
subcommand.

The chat agent was "very non-dependable" (2026-06-29): on a noisy 401-line
SKILL.md the model interrogated/confabulated instead of running the right
command. The skill was rewritten lean (~205 lines) with one tight intent→command
table. This test pins the contract the user asked for — "make sure all the
commands actually work" — so a future SKILL.md edit can never reference a command
that doesn't resolve in the parser (which is what makes the agent reliably ACT).
"""
import importlib.util
import re
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parents[1] / "facade" / "skill"


def _load_sr():
    path = _SKILL_DIR / "scripts" / "sr.py"
    spec = importlib.util.spec_from_file_location("sr_skill_cmd_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _registered_subcommands() -> set[str]:
    sr = _load_sr()
    choices: set[str] = set()
    for action in sr.build_parser()._actions:
        if getattr(action, "choices", None):
            choices |= set(action.choices.keys())  # subparser names + aliases
    return choices


def _commands_used_in_skill() -> set[str]:
    skill = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    return set(re.findall(r"sr\.py ([a-z][a-z-]+)", skill))


def test_every_skill_command_resolves_to_a_real_subcommand():
    used = _commands_used_in_skill()
    registered = _registered_subcommands()
    missing = sorted(used - registered)
    assert not missing, (
        f"SKILL.md references sr.py command(s) the parser doesn't register: {missing}. "
        "Either the command was renamed/removed or the skill has a typo — the agent "
        "would fail to act on that intent."
    )


def test_skill_covers_the_core_intents():
    # The actions the agent must be able to drive (the ones whose absence caused
    # the live failures: list / podcast / link-via-status / device-add by access
    # code / research / sign-in).
    used = _commands_used_in_skill()
    for core in ("research", "status", "list", "podcast", "device-add", "login", "stop"):
        assert core in used, f"SKILL.md no longer maps an intent to `sr.py {core}`"


def test_device_add_is_unambiguous_in_the_skill():
    # The device-add failure: the model confused an access code with phones /
    # chat-platform pairing. The skill must state, in words, that an 8-char code
    # → device-add and is NOT a platform/runtime pairing.
    skill = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower()
    assert "device-add" in skill
    assert "access code" in skill
    assert "8-char" in skill or "8-character" in skill
    # explicitly disclaims the platform/runtime confusion the agent fell into
    assert "telegram" in skill or "platform" in skill


def test_skill_within_sanity_bound():
    # NOTE: the aggressive 401->205 trim (0.1.14) regressed multiple flows live
    # (sign-in handoff, never-improvise, podcast substitution, device-add) because
    # the LLM relies on the explicit/emphatic wording — so we REVERTED to the
    # proven verbose version (reliability > a smaller file). This is just a loose
    # upper bound to catch unbounded growth, NOT a trim mandate.
    n = len((_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").splitlines())
    assert n < 460, f"SKILL.md grew to {n} lines — unexpectedly large"


def test_signin_handoff_continues_from_the_announce_topic():
    # Bug 1 (live, 2026-06-29): "yes" after the watchdog's "continue with
    # '<topic>'?" produced "what should I do with that?" — the lean trim dropped
    # the point that the topic is already in that announce. The handoff must tell
    # the agent to fire research with THAT topic directly, and never ask back.
    low = " ".join((_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower().split())
    assert "continue with" in low and "already in hand" in low, (
        "sign-in handoff must say the topic from the 'continue with <topic>?' "
        "announce is in hand → run research directly"
    )
    assert "what should i continue" in low, (
        "must explicitly forbid asking 'what should I continue?' after a sign-in link"
    )


def test_never_improvise_research_is_a_hard_rule():
    # Bug 2 (live, 2026-06-29): a re-sent "super research on X" got answered from
    # the model's own knowledge. The trim had softened the never-improvise rule;
    # the emphatic research-specific framing must be restored.
    low = " ".join((_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower().split())
    assert "hard rule" in low and "never improvise the research" in low
    assert "not even when you easily could" in low, (
        "restore the emphatic clause that directly catches the observed improvise"
    )
