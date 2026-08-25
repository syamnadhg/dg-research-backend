"""CI-gate contract: the workflow must actually run every suite it reports for.

Added after review of the DGOPS-7335 snapshot PR, which caught the failure this
guards: `.github/workflows/be-tests.yml` triggered on `**.py` — so editing
`agent/facade/bridge.py` fired the workflow and posted a GREEN check — while the
only pytest invocation was root `tests/`. The agent package's 747 tests never
ran. A gate that is silent about what it skips is worse than no gate, because
the green check is read as coverage.

Two packages live in this repo and each has its own suite, dependency file and
pytest config:

    superresearch        ->  tests/            (root requirements.txt)
    superresearch-agent  ->  agent/tests/      (agent/requirements.txt)

The agent suite only resolves with `working-directory: agent` — that is what
picks up agent/pyproject.toml's ``testpaths`` and puts agent/ on ``sys.path`` so
``import facade`` works. Dropping the working-directory silently turns the step
into a re-run of the root suite, so it is pinned too.

A second review pass found the same failure shape in the TRIGGERS: the workflow
listed itself under `push` but not under `pull_request`, so a PR whose only change
was to this file — narrowing the gate, dropping the agent step, moving the Python
version — was reviewable with no CI run at all. The filters are therefore checked
per-trigger and pinned equal, not grepped from the whole file; a whole-file grep
sees a filter that exists under either trigger and calls it covered.

Parsed as text, not YAML: PyYAML is not a declared dependency of this package,
and the assertions are about literal step content anyway.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "be-tests.yml"


def _workflow_text() -> str:
    assert WORKFLOW.exists(), f"{WORKFLOW} is missing — the BE test gate is gone"
    return WORKFLOW.read_text(encoding="utf-8")


def _run_steps() -> list[str]:
    """Every `run:` command in the workflow, one per entry.

    Only single-line `run:` scalars are used in this workflow; a future block
    scalar (`run: |`) would need handling here, and the pytest-invocation test
    below would fail loudly rather than silently pass.
    """
    return [m.group(1).strip() for m in re.finditer(r"^\s*run:\s*(\S.*)$", _workflow_text(), re.M)]


def test_workflow_invokes_both_test_suites() -> None:
    runs = _run_steps()
    pytest_runs = [r for r in runs if "pytest" in r]
    assert len(pytest_runs) >= 2, (
        "be-tests.yml must invoke BOTH suites (root tests/ and agent/tests/). "
        f"Found only these pytest commands: {pytest_runs!r}. The workflow triggers on "
        "'**.py', so an agent-only change reports a green check off whatever runs here."
    )


def test_agent_suite_runs_from_the_agent_directory() -> None:
    """`working-directory: agent` is what makes the agent suite resolve at all."""
    text = _workflow_text()
    assert re.search(r"^\s*working-directory:\s*agent\s*$", text, re.M), (
        "the agent pytest step lost 'working-directory: agent' — without it "
        "agent/pyproject.toml's testpaths and the 'facade' import root are not picked "
        "up, and the step degrades into a second run of the root suite."
    )


def test_agent_dependencies_are_installed() -> None:
    runs = _run_steps()
    assert any("agent/requirements.txt" in r for r in runs), (
        "be-tests.yml never installs agent/requirements.txt. Relying on the root "
        "requirements happening to carry compatible floors for the agent's deps is "
        "how this gap reappears."
    )


def test_the_correctness_lint_floor_runs_in_ci() -> None:
    """DGOPS-9508: undefined names + syntax errors are gated, not trusted.

    Style lint stays local by design; this is only the crash floor. `--ignore-noqa`
    is part of the contract — without it a `# noqa` on the offending line turns a
    genuine NameError back into a green check. The pinned install matters for the
    same reason the ruleset does: rule implementations move between ruff releases.
    """
    runs = _run_steps()
    floor = [r for r in runs if "ruff check" in r and "--select" in r]
    assert floor, (
        "be-tests.yml no longer runs the scoped `ruff check --select ...` floor, so "
        "undefined names are caught only if someone happens to lint locally."
    )
    for rule in ("E9", "F821"):
        assert any(rule in r for r in floor), f"{rule} dropped out of the floor: {floor!r}"
    assert any("--ignore-noqa" in r for r in floor), (
        f"the floor lost `--ignore-noqa`, so a comment can now hide a crash: {floor!r}"
    )
    assert any("ruff==" in r for r in runs if "pip install" in r), (
        "ruff is installed unpinned in CI — the gate's verdict would depend on "
        "release timing rather than on the code."
    )


def _trigger_paths(trigger: str) -> list[str]:
    """The `paths:` filters declared under one trigger (`push` / `pull_request`).

    Per-trigger, deliberately. The earlier version of this guard substring-matched
    the whole file, which cannot tell WHICH trigger a filter belongs to — and that
    is precisely how the asymmetry below slipped review: `.github/workflows/
    be-tests.yml` was listed under `push` only, so a whole-file grep for it passed
    while pull requests editing the gate ran nothing.

    Hand-parsed by indentation (PyYAML is not a dependency of this package, per the
    module docstring). Structure assumed: `on:` at column 0, triggers at 2, `paths:`
    at 4, list items at 6.
    """
    out: list[str] = []
    in_on = in_trigger = in_paths = False
    for raw in _workflow_text().splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_on, in_trigger, in_paths = stripped == "on:", False, False
        elif indent == 2 and in_on:
            # `workflow_dispatch: {}` has a value, so match on the key alone.
            in_trigger = stripped.split(":", 1)[0] == trigger
            in_paths = False
        elif indent == 4 and in_trigger:
            in_paths = stripped == "paths:"
        elif indent >= 6 and in_paths and stripped.startswith("- "):
            out.append(stripped[2:].strip().strip('"').strip("'"))
    return out


# Every filter both triggers must carry. The workflow file itself is on the list:
# narrowing the gate is the change that most needs the gate to run.
REQUIRED_PATH_FILTERS = (
    "**.py",
    "requirements.txt",
    "pyproject.toml",
    "agent/requirements.txt",
    "agent/pyproject.toml",
    # ⛔⛔ ADDED 2026-08-24, AND IT IS THE SAME FAILURE SHAPE THIS FILE WAS
    # WRITTEN FOR. `bundle-contract.json` is committed byte-identical to the app
    # repo; two suites pin it and a third compares the two copies. It matched no
    # filter here, so the ONE file whose whole purpose is to be guarded was the
    # one file whose change ran none of its guards. `**.py` does not match it.
    "bundle-contract.json",
    ".github/workflows/be-tests.yml",
)


@pytest.mark.parametrize("trigger", ["push", "pull_request"])
def test_the_trigger_paths_were_actually_parsed(trigger: str) -> None:
    """Guard against the guard: a layout change that breaks parsing must fail loudly.

    Without this, `_trigger_paths` returning [] would make the subset assertions
    below vacuous in the one direction that matters — and this whole file exists
    because a vacuously-passing gate is worse than no gate.
    """
    assert len(_trigger_paths(trigger)) >= 5, (
        f"parsed only {_trigger_paths(trigger)!r} under `{trigger}:` — the indentation "
        "assumptions in _trigger_paths no longer match be-tests.yml."
    )


@pytest.mark.parametrize("trigger", ["push", "pull_request"])
@pytest.mark.parametrize("path_filter", REQUIRED_PATH_FILTERS)
def test_required_trigger_paths_are_present_on_both_triggers(trigger: str, path_filter: str) -> None:
    """A bare `requirements.txt` filter matches ONLY the root file.

    Without an explicit entry, bumping an agent dependency lands with no CI run
    at all — the one change most likely to break the suite is the one change
    that doesn't trigger it. GitHub path filters do not treat `requirements.txt`
    as matching nested files.
    """
    assert path_filter in _trigger_paths(trigger), (
        f"{path_filter!r} is missing from the `{trigger}:` trigger paths, so a change "
        f"touching only that file runs no tests on {trigger}."
    )


def test_push_and_pull_request_watch_the_same_paths() -> None:
    """Asymmetry between the two lists is a silent coverage hole, so pin equality.

    The subset checks above only enforce the filters known TODAY; this catches the
    next one added to one trigger and forgotten on the other — the actual mistake,
    which is one of omission rather than of getting a filter wrong.
    """
    push, pull = _trigger_paths("push"), _trigger_paths("pull_request")
    assert set(push) == set(pull), (
        "be-tests.yml triggers disagree — push-only: "
        f"{sorted(set(push) - set(pull))}, pull_request-only: {sorted(set(pull) - set(push))}. "
        "A path watched on push but not on pull_request means the change can be "
        "REVIEWED with no CI and only tested once it has already landed."
    )
