"""The correctness lint floor runs in the SUITE, not only in CI.

⛔⛔ WHY THIS EXISTS. `be-tests.yml` has a step called "Lint — correctness floor
(must be zero)" — pinned ruff, `--select E9,F821,F822,F823,F811,F402
--ignore-noqa`. It is deliberately not a style gate: those rules are syntax
errors and undefined names, which are latent crashes. On 2026-09-09 that step
was found **failing on every push from before 7.9-0 through 7.9-4** — six waves
reported as verified by a check that had never gone green — over a single line
in `research.py` using PEP 701 f-string syntax (a nested same quote plus a
backslash), which is legal from 3.12 and a SyntaxError on 3.11, while both
pyprojects declare `requires-python = ">=3.11"` and ruff is configured
`target-version = "py311"`.

⛔⛔ NOTHING IN EITHER SUITE COULD HAVE CAUGHT IT, and that is the real defect.
The tests run on 3.13, so the file imports and every one of the 7121 root tests
passed over it. The gate lived only in a YAML step whose result nobody read. A
gate that exists in exactly one place, off the developer's machine, is a gate
that fails silently — so it lives here too now, and a local `pytest tests/ -q`
answers the same question CI does.

⛔ THE RULE SELECTION AND THE RUFF VERSION ARE READ OUT OF THE WORKFLOW, not
retyped. A copy of the selection here would drift from the step it mirrors, and
then this file would be reporting on a gate that no longer exists.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "be-tests.yml"


def _ruff_cmd() -> "list[str] | None":
    """How to invoke ruff here, or None when it is genuinely absent.

    ⛔⛔ `shutil.which("ruff")` ALONE IS NOT ENOUGH AND IT SKIPPED THIS FILE'S
    ONLY REAL TEST. CI does `pip install ruff==0.16.0`, which puts a `ruff`
    binary on PATH — but a uv-managed venv reaches it as a MODULE
    (`python -m ruff`), so on the machine where the code is written the check
    silently did nothing. A guard whose subject is "an unread gate went red for
    six waves" cannot itself be a gate that does not run locally.
    """
    exe = shutil.which("ruff")
    if exe:
        return [exe]
    probe = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                           capture_output=True, text=True)
    return [sys.executable, "-m", "ruff"] if probe.returncode == 0 else None


def _workflow() -> str:
    if not WORKFLOW.exists():
        pytest.skip("be-tests.yml not present")
    return WORKFLOW.read_text(encoding="utf-8")


def _lint_step() -> str:
    """The workflow's lint `run:` line itself, with no surrounding prose.

    ⛔ EVERY ASSERTION ABOUT THE GATE READS THIS, not the whole file — the file
    is mostly comments, and several of them quote the flags."""
    m = re.search(r"^\s*run:\s*(ruff check \..*)$", _workflow(), re.M)
    assert m, "the workflow's lint step no longer matches — this guard is stale"
    return m.group(1).strip()


def _selected_rules() -> list[str]:
    """The exact `--select` list the workflow's lint step passes."""
    m = re.search(r"--select ([A-Z0-9,]+)", _lint_step())
    assert m, "the workflow's lint step no longer matches — this guard is stale"
    return m.group(1).split(",")


def _pinned_ruff() -> str:
    m = re.search(r"pip install ruff==([0-9.]+)", _workflow())
    assert m, "the workflow no longer pins a ruff version — this guard is stale"
    return m.group(1)


def test_the_workflow_still_has_a_correctness_floor():
    """⛔ THE GUARD ON THE GUARD. If the lint step is dropped from CI, the two
    tests below start asserting nothing while still passing — so the step's
    existence is pinned first, exactly as the two-suite CI gate is."""
    wf = _workflow()
    assert "ruff check . --select" in wf
    # ⛔⛔ THE FLAG IS READ OFF THE STEP LINE, NOT SEARCHED FOR IN THE FILE. The
    # first version did `"--ignore-noqa" in wf`, which the YAML COMMENT three
    # lines above the step satisfies — measured: deleting the flag from the live
    # `run:` left this whole file green, so a `# noqa` silencing a real F821 in
    # CI would have slipped past the assertion whose own message calls the flag
    # load-bearing. It is the comment-satisfies-the-search trap, in the guard
    # written to stop an unread gate.
    step = _lint_step()
    assert "--ignore-noqa" in step, (
        "`--ignore-noqa` is load-bearing and must be ON THE STEP: a `# noqa` on "
        "the offending line would otherwise silence a genuine NameError and "
        f"leave the step green. The step reads: {step!r}")
    assert set(_selected_rules()) >= {"E9", "F821"}, (
        "E9 (syntax) and F821 (undefined name) are the floor; the rest may grow")


def test_the_tree_passes_the_correctness_floor():
    """The check itself, over the whole repo, with the workflow's own rules."""
    ruff = _ruff_cmd()
    if ruff is None:
        pytest.skip("ruff not installed (it is in the dev extras and in CI)")
    out = subprocess.run(
        [*ruff, "check", ".", "--select", ",".join(_selected_rules()),
         "--ignore-noqa", "--output-format=concise"],
        cwd=ROOT, capture_output=True, text=True)
    findings = [ln for ln in out.stdout.splitlines()
                if re.match(r"^[^\s].*:\d+:\d+: ", ln)]
    assert out.returncode == 0, (
        "the correctness lint floor is RED — these are latent crashes, not style:\n  "
        + "\n  ".join(findings[:20]))


def test_the_installed_ruff_matches_the_pin():
    """⚠ A WARNING, NOT A FAILURE, and deliberately so. A local ruff newer than
    the pin can disagree with CI about a clean tree — which is the whole reason
    the workflow pins one — but a developer mid-upgrade should not be blocked by
    this file. The pin itself is asserted above; this only says so out loud."""
    ruff = _ruff_cmd()
    if ruff is None:
        pytest.skip("ruff not installed")
    have = subprocess.run([*ruff, "--version"], capture_output=True, text=True).stdout
    want = _pinned_ruff()
    # ⛔ IT HAD NO ASSERTION AT ALL — it could only pass or skip, never fail, and
    # it contributed one of the file's reassuring "3 passed". At minimum it must
    # prove it read a real version.
    assert re.search(r"\d+\.\d+\.\d+", have), f"ruff --version said {have!r}"
    if want not in have:
        pytest.skip(f"local ruff is {have.strip()!r}, CI pins {want} — "
                    "they can disagree about a clean tree")
