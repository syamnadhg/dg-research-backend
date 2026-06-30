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


def test_skill_is_lean():
    # The whole point — keep it small so Hermes reads little per turn. The lean
    # rewrite is ~205 lines; guard against silent bloat back toward the old 401.
    n = len((_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").splitlines())
    assert n < 260, f"SKILL.md grew to {n} lines — keep it lean (was ~205 after the rewrite)"
