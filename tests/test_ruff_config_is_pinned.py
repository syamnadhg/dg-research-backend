"""The lint baseline must be reproducible — DGOPS-9508.

Before this, neither pyproject.toml pinned a ruleset, so `ruff check` reported
whatever the installed version defaulted to: 235 findings under `E4,E7,E9,F`
versus 2609 under ruff 0.16.0's bare defaults, on the same commit. "ruff clean"
was not a falsifiable claim, and a PR description had already asserted it off the
narrower number.

Three things have to hold for the count to stay reproducible, and two for the
floor to stay meaningful:

  * `select` is spelled out — ruff resolves config per file to the nearest
    ancestor with a [tool.ruff] table, so the agent needs its own copy;
  * the two copies agree, or a repo-root run mixes two rulesets;
  * ruff itself is pinned exactly, since rule implementations move between
    releases;
  * E9 + the F82x name-error family can never be switched off. Those are
    latent crashes, not style opinions — unlike the style exclusions, which are
    judgement calls anyone may revisit;
  * and no FILE may be carved out of the run. Rule codes were the only thing
    checked here at first, which left a second, quieter switch: one line of
    `exclude = ["research.py"]` under [tool.ruff] and the CI floor prints "All
    checks passed!" over the very file the ticket was about, with every test in
    this module still green. Reproduced against real ruff.
"""
from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = {"root": ROOT / "pyproject.toml", "agent": ROOT / "agent" / "pyproject.toml"}

# Rules whose zero-count is the ticket's acceptance criterion.
PROTECTED_RULES = ("E9", "F821", "F822", "F823", "F811", "F402")


def _cfg(path: Path) -> dict:
    assert path.exists(), f"{path} is missing"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _lint(path: Path) -> dict:
    return _cfg(path).get("tool", {}).get("ruff", {}).get("lint", {})


def _swallows(pattern: str, rule: str) -> bool:
    """Does an ignore entry switch `rule` off?

    Ruff matches rule codes by PREFIX, so `ignore = ["F8"]` kills F821/F822/F823
    without naming any of them — the shape a plausible-looking diff hides in. The
    reverse direction matters too: `per-file-ignores` may carry a longer code
    than the one being protected.

    Module-level so the guard and the guard-the-guard exercise the same code. As
    an assertion written inline it was re-implemented by its own test, which then
    passed on Python's semantics no matter what the real check did.
    """
    return rule.startswith(pattern) or pattern.startswith(rule)


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


def _installed_ruff_version() -> str | None:
    """Version of the ruff a bare `ruff check` here would actually run, or None when
    ruff is not available at all. Metadata first (how CI and the dev extra install
    it), then the console script, so a PATH-only install is still seen."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("ruff")
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    exe = shutil.which("ruff")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+\.\d+\.\d+)", out.stdout or "")
    return m.group(1) if m else None


def test_the_installed_ruff_matches_the_declared_pin() -> None:
    """The pin only reproduces anything if the ruff actually RUNNING is the pinned one.

    Every other test here checks what the config DECLARES. Nothing checked what the
    environment PROVIDES, and that gap was live: measured on this repo, the declared
    pin was 0.16.0 while the interpreter running the suite had ruff 0.15.16, so a
    local `python -m ruff check` reported a clean tree at a version CI never used.
    That is the same version-dependent disagreement this ticket set out to remove —
    just relocated from the ruleset to the binary, where it is harder to see because
    the output still says "All checks passed!".

    Skipped when ruff is absent: a plain `pytest` run on a machine that never
    installed the dev extras is not a lint failure.
    """
    declared = _ruff_pin(CONFIGS["root"])
    assert declared, "root pyproject.toml does not pin ruff exactly"
    installed = _installed_ruff_version()
    if installed is None:
        pytest.skip("ruff is not installed in this environment — nothing to compare")
    assert installed == declared, (
        f"installed ruff {installed} != declared pin {declared}. A local run measures "
        f"a different rule implementation than CI, so 'ruff clean' here is not the "
        f"same claim CI makes. Fix with: pip install ruff=={declared}"
    )


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
                assert not _swallows(pattern, rule), (
                    f"{name}: {pattern!r} switches off {rule}, which is a latent "
                    "crash rather than a style opinion"
                )


def test_the_prefix_check_would_catch_a_swallowing_pattern() -> None:
    """Guard the guard — the test above passes by finding nothing.

    It calls `_swallows`, the same function the guard calls. The earlier version
    restated the prefix logic inline, so it asserted a property of Python rather
    than of the guard: weakening the real check to `pattern != rule` left both
    tests green while `ignore = ["F8"]` sailed through.
    """
    assert _swallows("F8", "F821"), 'the guard no longer detects `ignore = ["F8"]`'
    assert _swallows("F821", "F821"), "an exact ignore is still an ignore"
    assert _swallows("F821", "F8"), "a per-file ignore longer than the rule still swallows it"
    assert not _swallows("E7", "F821"), "unrelated codes must not match"


# ── Nothing may be carved out of the run ─────────────────────────────────────

def _shipped_paths(name: str) -> set:
    """Repo-relative .py paths this config governs that MUST stay linted.

    Two groups, both derived from the file rather than listed here so the set
    cannot fall behind a packaging change:

      * what actually ships — [tool.setuptools] py-modules + packages, which is
        the code whose latent NameError reaches a user;
      * the suite next to it — a crash hiding in a test is a test that proves
        nothing, and excluding tests/ is the cheapest way to turn a red floor
        green.
    """
    base = CONFIGS[name].parent
    cfg = _cfg(CONFIGS[name]).get("tool", {}).get("setuptools", {})
    out = set()
    for mod in cfg.get("py-modules", []):
        p = base / f"{mod}.py"
        if p.exists():
            out.add(p.relative_to(base).as_posix())
    for pkg in [*cfg.get("packages", []), "tests"]:
        for p in (base / pkg).rglob("*.py"):
            out.add(p.relative_to(base).as_posix())
    return out


def _exclusion_patterns(name: str) -> list:
    """Every place ruff accepts a file-exclusion pattern, per config.

    `lint.exclude` sits alongside the two top-level keys because it removes a
    file from LINTING specifically, which is the whole of what the floor is.
    """
    ruff = _cfg(CONFIGS[name]).get("tool", {}).get("ruff", {})
    return [
        *ruff.get("exclude", []),
        *ruff.get("extend-exclude", []),
        *ruff.get("lint", {}).get("exclude", []),
    ]


def _excluded_by(pattern: str, paths) -> list:
    """Which of `paths` a ruff exclude pattern removes.

    Ruff's patterns are gitignore-style and match a path or any directory on the
    way to it, so `["auth"]`, `["auth/*"]`, `["*.py"]` and `["research.py"]` all
    have to register. fnmatch's `*` crossing `/` is what makes the directory
    forms work here.
    """
    pat = pattern.strip().rstrip("/")
    hit = []
    for path in paths:
        parts = path.split("/")
        prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        if any(fnmatch.fnmatch(c, pat) for c in (*prefixes, parts[-1])):
            hit.append(path)
    return sorted(hit)


@pytest.mark.parametrize("name", list(CONFIGS))
def test_no_shipped_file_can_be_excluded_from_the_lint(name: str) -> None:
    """⛔ The second switch. Every other test here reads rule CODES.

    `exclude = ["research.py"]` under [tool.ruff] — cover story: "54k lines, slow
    to lint" — leaves select, ignore and per-file-ignores untouched, so all of
    them stay green, while `ruff check . --select E9,F821,… --ignore-noqa` goes
    from reporting the undefined name to printing "All checks passed!". Verified
    against real ruff. That is the exact NameError class DGOPS-9508 existed for.
    """
    paths = _shipped_paths(name)
    assert paths, f"{name}: no source files resolved — this guard would be vacuous"
    for pattern in _exclusion_patterns(name):
        gone = _excluded_by(pattern, paths)
        assert not gone, (
            f"{name} pyproject.toml excludes {pattern!r} from ruff, which removes "
            f"{len(gone)} file(s) from the CI correctness floor — starting with "
            f"{gone[:3]}. The lint would still print 'All checks passed!' with an "
            f"undefined name in them. Exclusions belong to style rules, and the "
            f"floor is not a style rule."
        )


@pytest.mark.parametrize("name", list(CONFIGS))
def test_the_protected_set_covers_everything_that_ships(name: str) -> None:
    """⚠ "Non-empty" is not "complete", and the difference is exploitable.

    With no exclusions configured today, the loop in the test above never
    executes, so a `_shipped_paths` that quietly stopped collecting the root
    modules would go unnoticed — until someone added `exclude = ["research.py"]`
    later and the guard waved it through. Found by mutation: dropping the
    py-modules read left `tests/` in the set and every assertion green.

    Each declared module and package must contribute at least one path, and the
    declaration is read from pyproject rather than listed here.
    """
    base = CONFIGS[name].parent
    setup = _cfg(CONFIGS[name]).get("tool", {}).get("setuptools", {})
    paths = _shipped_paths(name)
    for mod in setup.get("py-modules", []):
        if (base / f"{mod}.py").exists():
            assert f"{mod}.py" in paths, f"{name}: shipped module {mod}.py is unprotected"
    for pkg in [*setup.get("packages", []), "tests"]:
        if not (base / pkg).is_dir():
            continue
        assert any(p.startswith(f"{pkg}/") for p in paths), (
            f"{name}: nothing under {pkg}/ is protected from a lint exclusion")


def test_the_exclusion_check_would_catch_a_real_exclude() -> None:
    """Guard the guard, through `_excluded_by` — the function the guard calls.

    Each pattern below is one someone would plausibly write, and each must
    register; the last two must not, or the guard fires on unrelated entries and
    gets deleted for being noisy.
    """
    paths = {"research.py", "auth/keystore.py", "tests/test_x.py"}
    for pattern in ("research.py", "*.py", "auth", "auth/", "auth/*", "research*", "tests"):
        assert _excluded_by(pattern, paths), f"{pattern!r} no longer registers as an exclusion"
    assert not _excluded_by("build", paths)
    assert not _excluded_by("*.md", paths)
