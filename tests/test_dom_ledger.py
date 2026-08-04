"""The DOM attempt ledger — one line per attempt, one verdict per run.

Why it exists: the prose around each DOM tier is correct and always has been.
What it could not do is answer "did the DOM layer work this run?" without
someone reading thousands of lines across three phases and correlating a setup
step with the vision mission that quietly rescued it two minutes later. The
2026-08 audit found three broken surfaces at once precisely because that answer
had been sitting in the corpus for months, spelled out, unread.

  grep '[dom]'          every attempt
  grep '[dom-summary]'  the verdict, and every miss with its evidence

The field order is fixed so two runs can be diffed, and so a miss can be
counted rather than described.
"""
from __future__ import annotations

import ast
import inspect

import pytest

import research


@pytest.fixture(autouse=True)
def _empty_ledger():
    research._dom_reset()
    yield
    research._dom_reset()


# ── One line per attempt ─────────────────────────────────────────────────────

def test_an_attempt_is_recorded_and_echoed(capsys):
    research._dom_note("chatgpt.select_model", "verified", phase=1,
                       via="pill", press="playwright", ms=1840,
                       detail="picked 'Pro'")
    out = capsys.readouterr().out
    assert "[dom] p1 chatgpt.select_model: verified" in out
    assert "via=pill" in out and "press=playwright" in out and "ms=1840" in out
    assert "picked 'Pro'" in out


def test_a_miss_is_a_warning_and_a_success_is_not(capsys):
    research._dom_note("a.b", "verified", phase=2)
    research._dom_note("c.d", "missed", phase=2)
    out = capsys.readouterr().out
    ok_line = [ln for ln in out.splitlines() if "a.b" in ln][0]
    bad_line = [ln for ln in out.splitlines() if "c.d" in ln][0]
    assert "WARN" not in ok_line
    assert "WARN" in bad_line, "a miss that logs at INFO is a miss nobody sees"


def test_already_on_target_counts_as_the_dom_layer_working():
    """⭐ Finding the control already correct and NOT touching it is the best
    possible outcome, not a skipped attempt. Counting it as a miss would make a
    healthy run look broken — the exact reporting bug this ledger exists to
    stop repeating, and the one P3's audio counter had for months."""
    research._dom_note("x.y", "already", phase=1)
    assert research._dom_summary()["missed"] == 0


@pytest.mark.parametrize("outcome", ["unsure", "no_target", "unverified",
                                     "missed", "error"])
def test_every_other_outcome_is_a_miss(outcome):
    research._dom_note("x.y", outcome, phase=1)
    assert research._dom_summary()["missed"] == 1


def test_the_note_returns_its_outcome_so_a_call_site_can_be_one_expression():
    assert research._dom_note("x.y", "unsure", phase=1) == "unsure"


def test_a_long_detail_is_truncated_rather_than_flooding_the_log():
    research._dom_note("x.y", "missed", phase=1, detail="z" * 5000)
    assert len(research._DOM_ATTEMPTS[0]["detail"]) <= 400


def test_a_non_numeric_duration_does_not_break_the_line(capsys):
    research._dom_note("x.y", "verified", phase=1, ms="soon")
    assert "[dom] p1 x.y: verified" in capsys.readouterr().out


# ── One verdict per run ──────────────────────────────────────────────────────

def test_the_summary_counts_and_then_lists_every_attempt(capsys):
    research._dom_note("chatgpt.select_model", "already", phase=1)
    research._dom_note("chatgpt.setup_deep_research", "missed", phase=2,
                       detail="vision/CUA setup fallback will run")
    research._dom_note("notebooklm.set_public_access", "verified", phase=3)
    # ⚠ Discard the per-attempt lines first. Without this the assertions below
    # are satisfied by `[dom]` output rather than by the summary — verified by
    # mutation, which gutted the summary's evidence and walked straight past a
    # version of this test that read the whole buffer.
    capsys.readouterr()
    got = research._dom_summary("run complete")
    out = capsys.readouterr().out
    assert "[dom]" not in out.replace("[dom-summary]", ""), (
        "the assertions below must be about the SUMMARY, not the attempt lines")

    assert got == {"total": 3, "ok": 2, "missed": 1}
    assert "2/3 DOM intents handled without escalating" in out
    assert "✓ p1 chatgpt.select_model: already" in out
    assert "✗ p2 chatgpt.setup_deep_research: missed" in out
    assert "vision/CUA setup fallback will run" in out, (
        "a miss listed without its evidence is a miss nobody can act on")


def test_a_clean_run_still_lists_what_it_did(capsys):
    """A summary that prints only on failure teaches nobody what "working"
    looks like, and there is nothing to diff the next miss against."""
    research._dom_note("a.b", "verified", phase=1)
    research._dom_summary()
    out = capsys.readouterr().out
    assert "1/1 DOM intents handled" in out
    assert "✓ p1 a.b: verified" in out


def test_a_run_with_no_attempts_says_so_rather_than_claiming_success(capsys):
    """⛔ Zero attempts is not a perfect score. If the ledger were never
    reached — a run that died in P0, or a wiring regression — "0/0 handled"
    would read as green, which is how a silent failure survives."""
    got = research._dom_summary()
    out = capsys.readouterr().out
    assert got["total"] == 0
    assert "no DOM attempts were recorded" in out
    assert "WARN" in out


def test_the_summary_is_safe_to_call_twice():
    research._dom_note("a.b", "verified", phase=1)
    assert research._dom_summary() == research._dom_summary()


def test_a_reset_clears_the_previous_runs_verdict():
    """A worker is long-lived. Carrying the last run's misses into this one
    would make a healthy run look broken and hide a real regression in the
    noise of an old one."""
    research._dom_note("a.b", "missed", phase=1)
    research._dom_reset()
    assert research._dom_summary()["total"] == 0


# ── Wiring: the ledger has to be reached ─────────────────────────────────────

def _fn(name):
    return ast.parse(inspect.getsource(getattr(research, name)))


def _calls(tree, name):
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == name]


def test_the_run_starts_with_an_empty_ledger():
    assert _calls(_fn("run_pipeline"), "_dom_reset"), (
        "run_pipeline no longer resets the ledger — a worker would carry the "
        "previous run's verdict into this one")


def test_the_verdict_is_printed_on_every_way_a_run_can_end():
    """Including the ways it ends badly. A run that died part-way is exactly
    the run someone is about to go and diagnose, so its verdict matters more,
    not less."""
    tree = _fn("run_pipeline")
    tags = set()
    for c in _calls(tree, "_dom_summary"):
        for a in c.args:
            if isinstance(a, ast.Constant):
                tags.add(a.value)
    assert {"run complete", "run interrupted", "run failed"} <= tags, sorted(tags)


def test_the_intents_that_matter_all_report():
    """Names the surfaces, so a tier that stops reporting cannot quietly shrink
    what the summary is a summary OF."""
    src = inspect.getsource(research)
    for intent in ("chatgpt.select_model",
                   "notebooklm.open_audio_menu",
                   "notebooklm.set_public_access",
                   "notebooklm.copy_share_link"):
        # ⚠ The trailing comma matters. Without it `chatgpt.select_model` is a
        # PREFIX of `chatgpt.select_model_unused` and a renamed intent passes —
        # verified by mutation, which renamed exactly that one and survived.
        assert f'_dom_note("{intent}",' in src, f"{intent} no longer reports"
    # The three setup ladders share one call site and one f-string.
    assert '_dom_note(f"{platform_l}.setup_deep_research"' in src


def test_the_model_picker_reports_the_same_intent_on_every_path():
    """⚠ The wrapper records twice — once on the verdict, once when the picker
    raises — and a substring check passes while ONE of them is renamed. That is
    the path that carries a crash, i.e. the one whose absence from the summary
    would be least noticed. Read the calls, not the text."""
    tree = _fn("_chatgpt_select_effort_tier")
    intents = [c.args[0].value for c in _calls(tree, "_dom_note")
               if c.args and isinstance(c.args[0], ast.Constant)]
    assert len(intents) >= 2, "the raise path no longer reaches the ledger"
    assert set(intents) == {"chatgpt.select_model"}, intents


def test_the_setup_ledger_sits_on_the_primary_attempt_not_the_retries():
    """⚠ Counting a recovery re-run as its own DOM intent would make the
    summary read WORSE the harder the run had to work to succeed, which is
    backwards. Exactly one setup site records."""
    src = inspect.getsource(research)
    assert src.count('_dom_note(f"{platform_l}.setup_deep_research"') == 1
