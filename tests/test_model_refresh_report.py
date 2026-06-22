"""Phoenix (model_refresh) Phase E — the observability report parser.

summarize() folds the log lines the pipeline already emits into a summary.
It must extract the right facts and never crash on odd input. Pure-function
tests against representative log lines (the report itself is read-only and
adds zero runtime code).
"""
import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "model_refresh_report",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "model_refresh_report.py"),
)
report = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(report)


_SAMPLE = [
    "2026-06-22 10:00:01 [setup_gemini_dr] model-pick OK: ranker clicked '3.5 flash' (v3.5, floor=3.5) | legacy /3.5 flash/ -> '3.5 flash'",
    "2026-06-22 11:00:01 [setup_gemini_dr] model-pick OK: ranker clicked '4.0 flash' (v4.0, floor=3.5) | legacy /3.5 flash/ -> '3.5 flash' — DIVERGES from legacy!",
    "2026-06-22 10:00:02 [setup_claude_dr] Step 1 OK: model already Opus 4.8 (trigger) — NOT re-picking (#744)",
    "2026-06-22 11:00:02 [setup_claude_dr] Step 1B OK: selected Opus 5.0 Max",
    "2026-06-22 11:00:05 [2B] Phoenix: latest model unverified for Deep Research — retrying once pinned to known-good claude v4.8",
    "2026-06-22 11:00:09 [2B] Phoenix: known-good fallback verified — proceeding on v4.8",
    "2026-06-22 11:00:10 [2B] Phoenix: proceeding with Deep Research but thinking config unconfirmed (max effort) — default level in use",
    "2026-06-22 10:59:59 some unrelated log line that should be ignored",
]


def test_summarize_extracts_gemini_picks_and_divergence():
    s = report.summarize(_SAMPLE)
    assert s["gemini_picks"]["3.5 flash"] == 1
    assert s["gemini_picks"]["4.0 flash"] == 1
    assert s["gemini_divergences"] == 1  # only the 4.0 line diverged


def test_summarize_normalizes_claude_versions():
    s = report.summarize(_SAMPLE)
    # Both the "already Opus 4.8" keep and the "selected Opus 5.0 Max" pick
    # are keyed by version.
    assert s["claude_models"]["4.8"] == 1
    assert s["claude_models"]["5.0"] == 1


def test_summarize_counts_fallbacks_and_thinking_misses():
    s = report.summarize(_SAMPLE)
    assert s["fallbacks"]["claude"] == 1
    assert s["fallbacks_verified"] == 1
    assert s["thinking_misses"]["max effort"] == 1


def test_summarize_never_crashes_on_junk():
    # None / blank / unrelated lines are ignored, not fatal.
    s = report.summarize([None, "", "random text", "12345"])
    assert sum(s["gemini_picks"].values()) == 0
    assert sum(s["claude_models"].values()) == 0


def test_format_report_runs_on_empty():
    out = report.format_report(report.summarize([]))
    assert "Phoenix model_refresh report" in out
    assert "none - the latest model verified on every run" in out


def test_format_report_is_ascii_safe():
    # The report prints from a Windows cp1252 console — output must encode there.
    out = report.format_report(report.summarize(_SAMPLE))
    out.encode("cp1252")  # raises UnicodeEncodeError if any non-cp1252 char slips in
