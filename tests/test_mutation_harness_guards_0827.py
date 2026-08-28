"""The mutation harness must refuse to score when it cannot measure.

⛔⛔ WHY THIS FILE EXISTS. On 2026-08-27 `review_blockers_0813_mutants.py`
printed **35/36 killed** and named M6 a survivor, three confirmations deep. M6
is not a survivor: three tests kill it, and re-running the harness's own exact
pytest invocation proves it. What actually happened is that the harness ran from
a shell with no `node` on PATH, so **68 of the 140 tests in
`test_review_blockers_0813.py` SKIPPED** — including all three of M6's killers —
and pytest still exited 0.

The harness read "exit 0" as "no test caught this". Its survivor-confirmation
loop then re-ran the *same broken environment* twice more and got the same
answer, which is exactly what a confirmation loop cannot protect against.

▶ **A SKIP IS NOT A PASS AND NOT A FAILURE — it is the absence of a
measurement**, and a score computed over absences is wrong in BOTH directions. A
false survivor costs a repair round chasing a defect that is not there. A false
KILL is worse: it certifies coverage that does not exist.

This is the same class as the stale-bytecode incident the harness's own header
already warns about — the apparatus lied, not the code under test. So the guard
belongs in the apparatus, and these are the tests for it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / ".mutants" / "review_blockers_0813_mutants.py"


def _harness():
    """Import the harness by path — it lives in a dot-directory, so it is not
    a package and cannot be imported by name."""
    spec = importlib.util.spec_from_file_location("_rb_harness", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def h():
    assert HARNESS.exists(), f"the harness moved: {HARNESS}"
    return _harness()


class TestSkippedCount:
    """Read pytest's own summary, because pytest's exit code will not say."""

    # ⭐ Every string below is real output copied from a run of this repo's
    # suites on 2026-08-27 — not invented shapes.
    def test_a_clean_green_run_has_no_skips(self, h):
        assert h.skipped_count("140 passed in 18.14s") == 0

    def test_the_run_that_faked_the_score(self, h):
        # The exact summary produced with node hidden from PATH.
        assert h.skipped_count("72 passed, 68 skipped in 17.48s") == 68

    def test_failures_are_not_skips(self, h):
        assert h.skipped_count("3 failed, 197 passed in 19.98s") == 0

    def test_a_skip_only_run(self, h):
        assert h.skipped_count("3 skipped, 137 deselected in 1.77s") == 3

    def test_no_output_at_all_is_zero_not_a_crash(self, h):
        assert h.skipped_count("") == 0
        assert h.skipped_count(None) == 0

    # ⛔ THE LAST MATCH WINS. pytest prints per-file progress and short summary
    # lines before the totals, so an earlier "1 skipped" must not be read as the
    # total — that would under-report and let a half-measured run through.
    def test_the_total_wins_over_an_earlier_line(self, h):
        out = "1 skipped, 2 passed\nsome other line\n72 passed, 68 skipped in 17.48s"
        assert h.skipped_count(out) == 68

    def test_the_number_is_read_not_merely_detected(self, h):
        # A guard keyed on "does the word appear" would pass for any count and
        # so could never tell 1 skip from 68.
        assert h.skipped_count("139 passed, 1 skipped in 18s") == 1


class TestMissingTooling:
    def test_node_is_required(self, h, monkeypatch):
        monkeypatch.setattr(h.shutil, "which", lambda exe: None if exe == "node" else "/usr/bin/" + exe)
        assert h.missing_tooling() == ["node"]

    def test_nothing_missing_when_everything_resolves(self, h, monkeypatch):
        monkeypatch.setattr(h.shutil, "which", lambda exe: "/usr/bin/" + exe)
        assert h.missing_tooling() == []

    # ⛔ node really is on PATH in a healthy dev box; if this fails, the harness
    # would have been blind, which is the whole point of the guard.
    def test_this_machine_can_actually_run_the_javascript_tests(self, h):
        assert "node" not in h.missing_tooling(), (
            "node is not on PATH — the JavaScript filter tests would SKIP and any "
            "mutation score measured here would be fiction"
        )


class TestTheHarnessRefusesToScore:
    """`main()` must exit non-zero and print nothing resembling a score."""

    def test_it_refuses_when_a_tool_is_missing(self, h, monkeypatch, capsys):
        monkeypatch.setattr(h, "missing_tooling", lambda: ["node"])
        # If the gate leaks, this would run the real suite; make that impossible.
        monkeypatch.setattr(h, "run_tests", lambda: pytest.fail("ran the suite anyway"))
        monkeypatch.setattr(h, "tracked_dirty", lambda: [])
        assert h.main() == 2
        out = capsys.readouterr().out
        assert "REFUSING TO SCORE" in out
        assert "killed" not in out

    def test_it_refuses_when_the_baseline_skips(self, h, monkeypatch, capsys):
        monkeypatch.setattr(h, "missing_tooling", lambda: [])
        monkeypatch.setattr(h, "tracked_dirty", lambda: [])
        monkeypatch.setattr(h, "run_tests", lambda: (True, 68))
        assert h.main() == 2
        out = capsys.readouterr().out
        assert "REFUSING TO SCORE" in out
        assert "68" in out
        # ⛔ The old harness would have carried straight on and scored 36 mutants
        # against a suite missing half its tests.
        assert "SURVIVED" not in out

    def test_a_green_baseline_with_no_skips_is_allowed_through(self, h, monkeypatch, capsys):
        monkeypatch.setattr(h, "missing_tooling", lambda: [])
        monkeypatch.setattr(h, "tracked_dirty", lambda: [])
        monkeypatch.setattr(h, "run_tests", lambda: (True, 0))
        # Every mutant "kills" instantly, so this exercises the gate and the loop
        # without touching research.py.
        h.main()
        out = capsys.readouterr().out
        assert "baseline… green" in out
        assert "REFUSING TO SCORE" not in out

    # ⛔⛔ THE MID-RUN CASE, which is the one that actually bit. The environment
    # can lose a tool between mutants, and from inside the loop that is
    # indistinguishable from a suite with no opinion. It must be an ERROR, never
    # a confident SURVIVED.
    def test_a_skip_during_a_mutant_is_an_error_not_a_survivor(self, h, monkeypatch, capsys):
        monkeypatch.setattr(h, "missing_tooling", lambda: [])
        monkeypatch.setattr(h, "tracked_dirty", lambda: [])
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            return (True, 0) if calls["n"] == 1 else (True, 68)

        monkeypatch.setattr(h, "run_tests", flaky)
        rc = h.main()
        out = capsys.readouterr().out
        assert "! ERROR" in out
        assert "skipped" in out
        assert "✗ SURVIVED" not in out
        assert rc != 0


class TestTheHarnessStillRestores:
    """The guards must not have cost the tree-restore promise."""

    def test_research_py_is_untouched_by_a_refusal(self, h, monkeypatch):
        before = (ROOT / "research.py").read_text(encoding="utf-8")
        monkeypatch.setattr(h, "missing_tooling", lambda: ["node"])
        monkeypatch.setattr(h, "tracked_dirty", lambda: [])
        h.main()
        assert (ROOT / "research.py").read_text(encoding="utf-8") == before
