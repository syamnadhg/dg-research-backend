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


@pytest.mark.parametrize("path_filter", ["agent/requirements.txt", "agent/pyproject.toml"])
def test_agent_dependency_files_are_trigger_paths(path_filter: str) -> None:
    """A bare `requirements.txt` filter matches ONLY the root file.

    Without an explicit entry, bumping an agent dependency lands with no CI run
    at all — the one change most likely to break the suite is the one change
    that doesn't trigger it.
    """
    assert f'"{path_filter}"' in _workflow_text(), (
        f"{path_filter} is not in the workflow's trigger paths, so editing it alone "
        "runs no tests. GitHub path filters do not treat 'requirements.txt' as "
        "matching nested files."
    )
