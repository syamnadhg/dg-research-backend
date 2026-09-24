"""node is a REQUIREMENT of this suite, not a condition it quietly degrades around.

⛔⛔ WHAT WAS MEASURED, 2026-09-17, and it is the precondition for believing any
wave-10 green. Sixteen test files gate themselves on node being installed, through
eighteen `skipif` definitions — seventeen reading `_domshim.NODE`, one shelling out
to `which node` in `test_platform_host_filter_0903.py`. Those marks are applied 152
times as decorators, and FOUR files skip WHOLESALE through a module-level
`pytestmark` (`test_chatgpt_dom_tier`, `test_chatgpt_dr_menu`,
`test_gemini_sidebar_expander`, `test_nlm_panels_wave5`).

Run those sixteen files with node hidden from `PATH` and pytest says:

    392 passed, 402 skipped

**402 test functions** — every one of them skipped for a node reason, none for any
other — evaporate on a machine without node, and the suite reports green. Nothing
anywhere asserted node was installed, so that green was indistinguishable from a
green that had run all 794. The earlier figure of "17 tests" in the plan counted
skip DEFINITIONS, not tests; it was ~24x too small.

⛔ THE STAKES ARE NOT HISTORICAL. Wave 10's lanes 1 and 2 put their ENTIRE evidence
inside that set: the DOM shim's attribute-driven visibility and the page code that
finally gets executed rather than source-grepped. On a node-less runner those lanes
report done having proved nothing.

⭐⭐ SO THIS FILE IS TWO HALVES AND NEITHER WORKS ALONE.

  (a) `test_node_is_installed...` and `test_node_actually_executes_page_js` turn the
      absence of node into a FAILURE. They carry no `skipif` — that is the entire
      point — and they are the only tests in this repo that can fail for this reason.

  (b) the CI half pins a node step into `.github/workflows/be-tests.yml`. Without it
      (a)'s truth would rest on GitHub's runner image rather than on this repo: the
      ubuntu image ships node today, so the assertion passes, the lane reports done,
      and the day the image drops node the assertion turns from a guard into an
      outage — a red suite nobody asked for, on a commit that changed nothing.

⭐ THE PRECEDENT IS IN THE WORKFLOW ALREADY, in the ffmpeg step's own comment:
"Without ffmpeg those tests SKIP, which is how a suite that was written precisely
because 'stubs cannot prove this' ran green here for a fortnight proving nothing."
Same failure, one order of magnitude larger, and node had no such step.

⛔ Verified by the STEP LIST, never by a run conclusion — a skipped step is unknown,
not fine. Hence the pins on `if:` being absent and on the step's ORDER relative to
the root pytest invocation: a node step that never runs, or runs after the suite,
buys nothing.

Parsed as text rather than YAML, for the reason `test_ci_gate_covers_both_suites.py`
gives: PyYAML is not a declared dependency of this package, and the assertions are
about literal step content anyway.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _domshim import NODE, el, run_js  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "be-tests.yml"

# The node line this fleet has settled on. Both front-end workflows
# (`unit-tests.yml`, `firestore-rules.yml`) pin the same one, so the page JS this
# suite executes runs under the same major the web half is built with. Bumping it
# is a deliberate act: change the workflow and this constant in one commit.
CI_NODE_VERSION = "20"

# The skipped-test census above, kept as literals so a failure message can say what
# was actually lost rather than "some tests were skipped".
GATED_TEST_FUNCTIONS = 402
GATED_FILES = 16


# ── (a) node's absence must FAIL, not skip ───────────────────────────────────

def test_node_is_installed_so_the_page_js_suites_are_not_silently_skipped() -> None:
    """The one assertion in this repo that can fail because node is missing.

    ⛔ `_domshim.NODE` is the shared resolver every one of those `skipif` marks
    reads (`shutil.which("node")` in `tests/_domshim.py`). Nothing else can make this
    pass: there is no fixture, flag or stub that produces a path here. Either node
    is on PATH or it is not.
    """
    assert NODE is not None, (
        "node is NOT installed, so this suite is about to report green having run "
        f"none of it: {GATED_TEST_FUNCTIONS} test functions across {GATED_FILES} "
        "files gate themselves on `_domshim.NODE` (four of those files wholesale, "
        "via a module-level pytestmark) and will all SKIP. Install node — do not "
        "skip this test, and do not give it a skipif. If you are seeing this in CI, "
        "the `actions/setup-node` step in .github/workflows/be-tests.yml has been "
        "removed or did not run."
    )


def test_node_actually_executes_page_js() -> None:
    """Pin the CONSUMER, not just the resolver.

    ⛔ `shutil.which` finding a path is not the same fact as node running JS — a
    broken shim, a node too old for the shim's syntax, or a wrapper script on PATH
    would all leave `NODE` non-None while every page-JS test that matters died. So
    drive the real `run_js` against a real spec and compare the returned value by
    EQUALITY. This is the same door all 402 gated tests go through.
    """
    spec = el("div", kids=[
        el("span", {"data-test-id": "decoy"}, text="no"),
        el("b", {"data-test-id": "target"}, text="page-js-ran"),
    ])
    out = run_js(spec, '() => document.querySelector(\'[data-test-id="target"]\').textContent')
    assert out["ret"] == "page-js-ran", (
        f"node is on PATH ({NODE}) but could not execute the DOM shim's page JS, so "
        f"every one of the {GATED_TEST_FUNCTIONS} gated tests is running against a "
        f"broken interpreter rather than being skipped. Got: {out!r}"
    )


# ── (b)/(c) the CI step that makes (a) true about THIS REPO ──────────────────

def _workflow_text() -> str:
    assert WORKFLOW.exists(), f"{WORKFLOW} is missing — the BE test gate is gone"
    return WORKFLOW.read_text(encoding="utf-8")


def _job_step_blocks(job: str = "tests") -> list[str]:
    """Every step of one job, in ORDER, each as its own block of stripped lines.

    Order is the point: `test_ci_gate_covers_both_suites.py`'s `_run_steps()` flattens
    the whole file into a bag of `run:` commands, which cannot tell a node install
    that happens BEFORE the suite from one that happens after it, nor one in this job
    from one in some future job that never feeds this one. Comment lines are dropped
    so a `#`-quoted `uses:` cannot be mistaken for a step.

    Hand-parsed by indentation, matching this workflow's layout: `jobs:` at column 0,
    the job name at 2, `steps:` at 4, step items at 6, their keys at 8.
    """
    blocks: list[str] = []
    cur: list[str] | None = None
    in_jobs = in_job = in_steps = False

    def _flush() -> None:
        nonlocal cur
        if cur is not None:
            blocks.append("\n".join(cur))
            cur = None

    for raw in _workflow_text().splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            _flush()
            in_jobs, in_job, in_steps = stripped == "jobs:", False, False
        elif indent == 2 and in_jobs:
            _flush()
            in_job = stripped.split(":", 1)[0] == job
            in_steps = False
        elif indent == 4 and in_job:
            _flush()
            in_steps = stripped == "steps:"
        elif in_steps and indent >= 6:
            if stripped.startswith("- "):
                _flush()
                cur = [stripped[2:].strip()]
            elif cur is not None:
                cur.append(stripped)
    _flush()
    return blocks


def _index_of(pattern: str) -> list[int]:
    return [i for i, b in enumerate(_job_step_blocks()) if re.search(pattern, b, re.M)]


def test_the_job_steps_were_actually_parsed() -> None:
    """Guard against the guard.

    Without this, `_job_step_blocks` returning `[]` after a layout change would make
    every ordering assertion below vacuous in the one direction that matters, and
    this file exists because a vacuously-passing gate is worse than no gate.
    """
    blocks = _job_step_blocks()
    assert len(blocks) >= 7, (
        f"parsed only {len(blocks)} steps out of the `tests:` job ({blocks!r}) — the "
        "indentation assumptions in _job_step_blocks no longer match be-tests.yml."
    )
    # The step this file's ordering pins are measured against must be findable.
    assert any(re.search(r"^run:\s*python -m pytest tests/", b, re.M) for b in blocks), (
        "the root suite's `python -m pytest tests/` step was not found in the "
        f"`tests:` job, so every ordering assertion below would be meaningless: {blocks!r}"
    )


def test_ci_installs_node_before_it_runs_the_backend_suite() -> None:
    """⛔ A node step in another job, or after the suite, installs node for nobody."""
    node_steps = _index_of(r"^uses:\s*actions/setup-node@")
    assert len(node_steps) == 1, (
        "be-tests.yml must set node up exactly once in the `tests:` job. Found "
        f"{len(node_steps)} setup-node step(s). Without one, this runner's image "
        f"decides whether {GATED_TEST_FUNCTIONS} test functions run or skip — and "
        "the image is not something this repo controls or can be reviewed against."
    )
    pytest_steps = _index_of(r"^run:\s*python -m pytest tests/")
    assert len(pytest_steps) == 1, (
        f"expected exactly one root-suite pytest step, found {pytest_steps!r}"
    )
    assert node_steps[0] < pytest_steps[0], (
        f"setup-node is step {node_steps[0]} and the root suite is step "
        f"{pytest_steps[0]} — node is installed AFTER the tests that need it, so "
        "they skip exactly as if the step were absent."
    )


def test_the_ci_node_step_is_pinned_and_unconditional() -> None:
    """⛔ Verify the STEP LIST, not a run conclusion: a skipped step is unknown.

    Three ways this step could exist and still buy nothing — a floating action tag
    that silently changes what runs, an unpinned `node-version` that drifts off the
    version the web half builds with, and an `if:` that can quietly evaluate false
    and leave the whole job green. All three are pinned shut here.
    """
    blocks = _job_step_blocks()
    node_block = next((b for b in blocks if re.search(r"^uses:\s*actions/setup-node@", b, re.M)), None)
    assert node_block is not None, (
        "no `actions/setup-node` step in the `tests:` job — see "
        "test_ci_installs_node_before_it_runs_the_backend_suite for what that costs."
    )

    ref = re.search(r"^uses:\s*actions/setup-node@(\S+)", node_block, re.M)
    assert ref is not None, f"could not read the setup-node reference from {node_block!r}"
    assert re.fullmatch(r"[0-9a-f]{40}", ref.group(1)), (
        f"setup-node is referenced by the floating tag {ref.group(1)!r}, not a commit "
        "SHA. Both front-end workflows pin this action by SHA; a moving tag means the "
        "code that decides whether node exists can change without a commit here."
    )

    version = re.search(r'^node-version:\s*"([^"]*)"\s*$', node_block, re.M)
    assert version is not None, (
        "the setup-node step declares no quoted `node-version:`, so the runner's "
        f"default decides it. Pin it to {CI_NODE_VERSION!r}. Step: {node_block!r}"
    )
    assert version.group(1) == CI_NODE_VERSION, (
        f"CI installs node {version.group(1)!r} but this suite is pinned to "
        f"{CI_NODE_VERSION!r} — the same major both front-end workflows use, so the "
        "page JS runs under the engine the web half is built with. Change the "
        "workflow and CI_NODE_VERSION in one commit, or not at all."
    )

    assert not re.search(r"^if:", node_block, re.M), (
        "the setup-node step carries an `if:` condition. A step that evaluates false "
        "reports as SKIPPED and leaves the job green, which is the precise shape of "
        f"the defect this file exists to close: {node_block!r}"
    )
