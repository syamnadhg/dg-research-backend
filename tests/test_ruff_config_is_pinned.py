"""The lint baseline must be reproducible — DGOPS-9508.

Before this, neither pyproject.toml pinned a ruleset, so `ruff check` reported
whatever the installed version defaulted to: 235 findings under `E4,E7,E9,F`
versus 2609 under ruff 0.16.0's bare defaults, on the same commit. "ruff clean"
was not a falsifiable claim, and a PR description had already asserted it off the
narrower number.

Three things have to hold for the count to stay reproducible, and one for the
floor to stay meaningful:

  * `select` is spelled out — ruff resolves config per file to the nearest
    ancestor with a [tool.ruff] table, so the agent needs its own copy;
  * the two copies agree, or a repo-root run mixes two rulesets;
  * ruff itself is pinned exactly, since rule implementations move between
    releases;
  * and E9 + the F82x name-error family can never be switched off. Those are
    latent crashes, not style opinions — unlike the style exclusions, which are
    judgement calls anyone may revisit.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = {"root": ROOT / "pyproject.toml", "agent": ROOT / "agent" / "pyproject.toml"}

# Rules whose zero-count is the ticket's acceptance criterion.
PROTECTED_RULES = ("E9", "F821", "F822", "F823", "F811", "F402")


def _lint(path: Path) -> dict:
    assert path.exists(), f"{path} is missing"
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    return cfg.get("tool", {}).get("ruff", {}).get("lint", {})


def _ruff_pin(path: Path) -> str | None:
    """Exact version from a `ruff==X.Y.Z` dev entry, or None if not pinned."""
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    for entry in cfg.get("project", {}).get("optional-dependencies", {}).get("dev", []):
        if entry.split("=")[0].split(">")[0].split("<")[0].split("~")[0].strip() == "ruff":
            return entry.split("==", 1)[1].strip() if "==" in entry else None
    return None


@pytest.mark.parametrize("name", list(CONFIGS))
def test_the_ruleset_is_declared_explicitly(name: str) -> None:
    """Deleting `select` restores version-dependent defaults and reads as a no-op."""
    assert _lint(CONFIGS[name]).get("select"), (
        f"{name} pyproject.toml declares no [tool.ruff.lint] select, so its finding "
        "count is whatever the installed ruff happens to default to."
    )


def test_root_and_agent_agree() -> None:
    """The agent duplicates the ruleset rather than using a relative `extend`.

    `extend = "../pyproject.toml"` would dangle once the agent is linted outside
    the monorepo, since it publishes as its own package. This holds the copies
    together, and pins the ruff versions equal for the same reason.
    """
    root, agent = _lint(CONFIGS["root"]), _lint(CONFIGS["agent"])
    assert root.get("select") == agent.get("select"), (
        f"select differs — root {root.get('select')!r} vs agent {agent.get('select')!r}; "
        "a repo-root `ruff check .` would report a number from two rulesets."
    )
    assert root.get("ignore", []) == agent.get("ignore", [])
    assert _ruff_pin(CONFIGS["root"]) == _ruff_pin(CONFIGS["agent"])


@pytest.mark.parametrize("name", list(CONFIGS))
def test_ruff_is_pinned_exactly(name: str) -> None:
    """A floor reproduces the ruleset but not the count."""
    assert _ruff_pin(CONFIGS[name]) is not None, (
        f"{name} pyproject.toml does not pin ruff with `==`. A floor like "
        "`ruff>=0.5` is how one machine measured 235 findings and another 2609 on "
        "the same commit."
    )


def test_correctness_rules_cannot_be_switched_off() -> None:
    """E9 + the F82x family stay selected, and un-ignorable — prefixes included.

    `ignore = ["F8"]` kills F821 without ever naming it, which is how a floor like
    this gets lost in a plausible-looking diff. Per-file-ignores are checked too:
    a per-file escape hatch is still an escape hatch.
    """
    for name, path in CONFIGS.items():
        lint = _lint(path)
        select, ignore = lint.get("select", []), lint.get("ignore", [])
        per_file = [p for pats in lint.get("per-file-ignores", {}).values() for p in pats]
        for rule in PROTECTED_RULES:
            assert any(rule.startswith(s) for s in select), (
                f"{name}: nothing in select={select!r} covers {rule}"
            )
            for pattern in (*ignore, *per_file):
                assert not (rule.startswith(pattern) or pattern.startswith(rule)), (
                    f"{name}: {pattern!r} switches off {rule}, which is a latent "
                    "crash rather than a style opinion"
                )


def test_the_prefix_check_would_catch_a_swallowing_pattern() -> None:
    """Guard the guard — the test above passes by finding nothing."""
    rule, pattern = "F821", "F8"
    assert rule.startswith(pattern), "prefix matching no longer detects `ignore = [\"F8\"]`"
    assert not ("F821".startswith("E7") or "E7".startswith("F821")), "unrelated codes must not match"
