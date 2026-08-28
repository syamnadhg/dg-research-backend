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
import subprocess
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


@pytest.fixture
def safe(h, monkeypatch):
    """`main()` with every route to production source cut.

    ⛔⛔ THIS FIXTURE IS THE FIX FOR A REAL INCIDENT, TWICE OVER. Tests here call
    `main()`, and `main()`'s job is to write mutants into `research.py`. The
    first version relied on each test patching what it happened to need — so the
    moment a MUTANT disabled the gate that test was exercising, control fell
    through to the genuine 36-mutant loop and rewrote `research.py` for real.
    Killing that run left a mutant in the tree.

    ▶ **A test must not depend on the code under test behaving, to stay safe.**
    Both `run_tests` and `MUTANTS` are neutralised here unconditionally, before
    any individual test gets to express a preference. A test that wants a mutant
    in the loop re-points `ROOT` at a scratch directory as well.
    """
    monkeypatch.setattr(h, "run_tests", lambda: (True, 0))
    monkeypatch.setattr(h, "MUTANTS", [])
    monkeypatch.setattr(h, "tracked_dirty", lambda: [])
    return h


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

    # ⛔⛔ THE ONE THAT BIT THIS GUARD ITSELF. When these very tests FAIL, pytest
    # prints the assertion diff — which contains the fixture string
    # "72 passed, 68 skipped in 17.48s". A detector that scans all output reads
    # its own test data as evidence and refuses five perfectly good verdicts.
    # Measured 2026-08-27: exactly that, five times.
    def test_it_reads_the_summary_line_not_the_assertion_diffs(self, h):
        noisy = (
            "E   AssertionError: assert 0 == 68\n"
            "E    +  where 68 = skipped_count('72 passed, 68 skipped in 17.48s')\n"
            "4 failed, 12 passed in 0.29s"
        )
        assert h.skipped_count(noisy) == 0

    def test_a_real_skip_still_reads_through_the_noise(self, h):
        noisy = ("some diff mentioning 99 skipped in prose\n"
                 "70 passed, 2 skipped in 1.10s")
        assert h.skipped_count(noisy) == 2

    # ⛔ More than one summary line happens for real — xdist and rerun plugins
    # both print one per pass. The LAST is the run's actual outcome.
    def test_the_last_summary_wins_when_there_are_several(self, h):
        two = "70 passed, 2 skipped in 1.10s\nrerunning...\n60 passed, 12 skipped in 0.90s"
        assert h.skipped_count(two) == 12

    def test_prose_with_no_summary_line_at_all_is_zero(self, h):
        assert h.skipped_count("we skipped lunch. 5 skipped things happened.") == 0

    def test_the_number_is_read_not_merely_detected(self, h):
        # A guard keyed on "does the word appear" would pass for any count and
        # so could never tell 1 skip from 68.
        assert h.skipped_count("139 passed, 1 skipped in 18s") == 1


class TestRunTests:
    """`run_tests` must REPORT the skips, not just the exit code."""

    class _Proc:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def test_it_returns_the_parsed_skip_count(self, h, monkeypatch):
        monkeypatch.setattr(h, "purge_pycache", lambda: None)
        monkeypatch.setattr(h, "sh", lambda *a, **k: self._Proc(0, "72 passed, 68 skipped in 17.48s"))
        assert h.run_tests() == (True, 68)

    def test_a_green_run_reports_zero(self, h, monkeypatch):
        monkeypatch.setattr(h, "purge_pycache", lambda: None)
        monkeypatch.setattr(h, "sh", lambda *a, **k: self._Proc(0, "140 passed in 18.14s"))
        assert h.run_tests() == (True, 0)

    def test_a_red_run_is_reported_red(self, h, monkeypatch):
        monkeypatch.setattr(h, "purge_pycache", lambda: None)
        monkeypatch.setattr(h, "sh", lambda *a, **k: self._Proc(1, "3 failed, 197 passed in 19.98s"))
        assert h.run_tests() == (False, 0)

    # ⛔ pytest's summary can land on stderr under some plugins/CI wrappers.
    # Reading only stdout would hide every skip there.
    def test_the_summary_is_found_on_stderr_too(self, h, monkeypatch):
        monkeypatch.setattr(h, "purge_pycache", lambda: None)
        monkeypatch.setattr(h, "sh", lambda *a, **k: self._Proc(0, "", "72 passed, 68 skipped in 17.48s"))
        assert h.run_tests() == (True, 68)


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

    def test_it_refuses_when_a_tool_is_missing(self, safe, monkeypatch, capsys):
        h = safe
        monkeypatch.setattr(h, "missing_tooling", lambda: ["node"])
        assert h.main() == 2
        out = capsys.readouterr().out
        assert "REFUSING TO SCORE" in out
        assert "killed" not in out

    def test_it_refuses_when_the_baseline_skips(self, safe, monkeypatch, capsys):
        h = safe
        monkeypatch.setattr(h, "missing_tooling", lambda: [])
        monkeypatch.setattr(h, "run_tests", lambda: (True, 68))
        assert h.main() == 2
        out = capsys.readouterr().out
        assert "REFUSING TO SCORE" in out
        assert "68" in out
        # ⛔ The old harness would have carried straight on and scored 36 mutants
        # against a suite missing half its tests.
        assert "SURVIVED" not in out

    def test_a_green_baseline_with_no_skips_is_allowed_through(self, safe, monkeypatch, capsys):
        h = safe
        monkeypatch.setattr(h, "missing_tooling", lambda: [])
        # ⛔⛔ MUTANTS EMPTIED ON PURPOSE. The first version of this test left the
        # real list in place, so calling main() drove the genuine mutation loop
        # and wrote 36 mutants into research.py. Killing the run mid-loop left
        # one of them THERE — the exact hazard this repo has now hit three times.
        # A test for the gate must never be able to edit production source.
        monkeypatch.setattr(h, "MUTANTS", [])
        assert h.main() == 0
        out = capsys.readouterr().out
        assert "baseline… green" in out
        assert "REFUSING TO SCORE" not in out

    # ⛔⛔ THE MID-RUN CASE, which is the one that actually bit. The environment
    # can lose a tool between mutants, and from inside the loop that is
    # indistinguishable from a suite with no opinion. It must be an ERROR, never
    # a confident SURVIVED.
    def test_a_skip_during_a_mutant_is_an_error_not_a_survivor(self, safe, monkeypatch, capsys, tmp_path):
        h = safe
        monkeypatch.setattr(h, "missing_tooling", lambda: [])
        # ⛔ ROOT is re-pointed at a scratch directory so the loop's real
        # read/write lands on a throwaway file. See the note above — this test
        # needs a mutant to enter the loop at all, and it must not be a real one.
        monkeypatch.setattr(h, "ROOT", tmp_path)
        (tmp_path / "scratch.py").write_text("KEEP_ME = 1\n", encoding="utf-8")
        monkeypatch.setattr(h, "MUTANTS", [
            ("X1", "scratch.py", "under", "a scratch mutant",
             [("KEEP_ME = 1", "KEEP_ME = 2")]),
        ])
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
        # And it still restored what it touched.
        assert (tmp_path / "scratch.py").read_text(encoding="utf-8") == "KEEP_ME = 1\n"


    # ⛔⛔ THE FIRST CHECK, ISOLATED. With confirmations left on, removing the
    # check inside the loop body is masked by the identical check in the
    # confirmation re-run — each covers for the other, so neither is pinned.
    # Setting confirmations to 1 removes the understudy.
    def test_the_first_check_alone_refuses_a_skipping_mutant(self, safe, monkeypatch, capsys, tmp_path):
        h = safe
        monkeypatch.setattr(h, "missing_tooling", lambda: [])
        monkeypatch.setattr(h, "SURVIVOR_CONFIRMATIONS", 1)
        monkeypatch.setattr(h, "ROOT", tmp_path)
        (tmp_path / "scratch.py").write_text("KEEP_ME = 1\n", encoding="utf-8")
        monkeypatch.setattr(h, "MUTANTS", [
            ("X1", "scratch.py", "under", "a scratch mutant",
             [("KEEP_ME = 1", "KEEP_ME = 2")]),
        ])
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            return (True, 0) if calls["n"] == 1 else (True, 68)

        monkeypatch.setattr(h, "run_tests", flaky)
        rc = h.main()
        out = capsys.readouterr().out
        assert "! ERROR" in out and "68" in out
        assert "✗ SURVIVED" not in out
        assert rc != 0


    # ⛔⛔ THE CONFIRMATION RE-RUN NEEDS ITS OWN KILLER. The first check cannot
    # cover for it: an environment that is healthy on the mutant's first run and
    # loses a tool before the re-run reaches the loop with the first check
    # already satisfied. Measured 2026-08-27 — deleting the check inside the
    # confirmation loop left every test in this file green.
    def test_a_skip_in_the_CONFIRMATION_rerun_is_also_refused(self, safe, monkeypatch, capsys, tmp_path):
        h = safe
        monkeypatch.setattr(h, "missing_tooling", lambda: [])
        monkeypatch.setattr(h, "SURVIVOR_CONFIRMATIONS", 3)
        monkeypatch.setattr(h, "ROOT", tmp_path)
        (tmp_path / "scratch.py").write_text("KEEP_ME = 1\n", encoding="utf-8")
        monkeypatch.setattr(h, "MUTANTS", [
            ("X1", "scratch.py", "under", "a scratch mutant",
             [("KEEP_ME = 1", "KEEP_ME = 2")]),
        ])
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            # 1 = baseline (clean), 2 = the mutant's first run (clean, and it
            # SURVIVES so the loop is entered), 3+ = the re-run, now skipping.
            return (True, 0) if calls["n"] <= 2 else (True, 68)

        monkeypatch.setattr(h, "run_tests", flaky)
        rc = h.main()
        out = capsys.readouterr().out
        assert "! ERROR" in out and "68" in out
        assert "✗ SURVIVED" not in out, "a survivor confirmed by a broken environment is not a survivor"
        assert rc != 0


class TestTheHarnessStillRestores:
    """The guards must not have cost the tree-restore promise."""

    def test_research_py_is_untouched_by_a_refusal(self, safe, monkeypatch):
        h = safe
        before = (ROOT / "research.py").read_text(encoding="utf-8")
        monkeypatch.setattr(h, "missing_tooling", lambda: ["node"])
        h.main()
        assert (ROOT / "research.py").read_text(encoding="utf-8") == before

    # ⛔⛔ THE ONE THAT WOULD HAVE CAUGHT MY OWN MISTAKE. Nothing in this file may
    # leave production source modified, whatever path main() takes.
    def test_no_test_in_this_file_leaves_research_py_modified(self):
        out = subprocess.run(["git", "status", "--porcelain", "--", "research.py"],
                             cwd=ROOT, capture_output=True, text=True).stdout
        assert out.strip() == "", f"research.py is modified: {out!r}"
