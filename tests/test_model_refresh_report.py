"""The model-selection observability report parser.

summarize() folds the log lines the pipeline already emits into a summary. It
must extract the right facts and never crash on odd input.

⭐ THE LESSON THIS FILE NOW ENCODES (2026-08-01). Every marker the parser keyed
on moved when the version floor was removed — and these tests kept PASSING,
because they fed hand-written sample lines that the pipeline no longer emitted.
A parser matching nothing produces the same clean report as a pipeline with
nothing to report, so the failure was invisible from both ends.

`test_every_marker_matches_a_line_research_py_actually_emits` is the fix: it
RECONSTRUCTS the lines research.py's f-strings produce and runs each parser regex
against them, so the parser and the code it parses cannot drift apart silently
again.

⛔ The first version of that guard did NOT do this. It compared a third,
hand-copied prose fragment against the source and only interpolated the regex
into its own failure message, so the regex itself was never applied — leaving
exactly the drift class above alive. Dropping the `!r` from `{picked!r}` on the
Gemini pick line emptied `gemini_picks` for every real run with all three guards
green. `test_dropping_a_repr_conversion_breaks_the_gemini_marker` pins that
specific mutation now, through the same rendering code path the guard uses.
"""
import ast
import importlib.util
import itertools
import os
import pathlib

import research

_SPEC = importlib.util.spec_from_file_location(
    "model_refresh_report",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "model_refresh_report.py"),
)
report = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(report)


# Real log lines, copied from the shapes research.py emits today.
_SAMPLE = [
    "2026-08-01 10:00:01 [setup_gemini_dr] model-pick OK: clicked the highest 'flash' offered — '3.5 flashall-around help' (v3.5)",
    "2026-08-01 11:00:01 [setup_gemini_dr] model-pick OK: clicked the highest 'flash' offered — '4.0 flash' (v4.0)",
    "2026-08-01 10:00:02 [setup_claude_dr] Step 1 OK: model already opus v4.8 (trigger) — NOT re-picking (#744)",
    "2026-08-01 10:00:03 [setup_claude_dr] Step 1A SKIPPED: trigger already reads 'Opus 4.8 Max' — family 'opus' and effort 'max' both confirmed without opening the popover",
    "2026-08-01 11:00:02 [setup_claude_dr] Step 1B OK: selected 'Opus 5 Max' (v5.0)",
    "2026-08-01 12:00:01 [setup_claude_dr] Step 1A: model+effort already confirmed off the trigger, but the periodic model-menu check is due — opening the popover once to look for a newer opus",
    "2026-08-01 12:00:02 [setup_claude_dr] Step 1B* UPGRADE: opus 5.0 → 6.0 ('Opus 6')",
    "2026-08-01 13:00:01 [setup_claude_dr] Step 1A: model+effort already confirmed off the trigger, but the periodic model-menu check is due — opening the popover once to look for a newer opus",
    "2026-08-01 13:00:02 [setup_claude_dr] Step 1B*: opus 6.0 is already the highest offered (6.0) — no re-pick (#744)",
    "2026-08-01 14:00:02 [setup_claude_dr] Step 1B*: model menu never mounted — cannot tell whether a newer opus exists; keeping 6.0",
    "2026-08-01 11:00:05 [2B] step-back: claude v6.0 did not verify into Deep Research — retrying once on an older model (known-good v5.0)",
    "2026-08-01 11:00:09 [2B] step-back verified — proceeding on v5.0",
    "2026-08-01 11:00:10 [2B] Phoenix: proceeding with Deep Research; thinking config unconfirmed (max effort) — telemetry only, no user alert (advisory, never gates)",
    "2026-08-01 10:59:59 some unrelated log line that should be ignored",
]


def test_summarize_extracts_gemini_picks():
    s = report.summarize(_SAMPLE)
    assert s["gemini_picks"]["3.5 flashall-around help"] == 1
    assert s["gemini_picks"]["4.0 flash"] == 1


def test_summarize_normalizes_claude_versions():
    s = report.summarize(_SAMPLE)
    # The keep, the pick, and the upgrade destination all key by version.
    assert s["claude_models"]["4.8"] == 1
    assert s["claude_models"]["5.0"] == 1
    assert s["claude_models"]["6.0"] == 1


def test_summarize_counts_the_periodic_check():
    """⭐ The row that matters after this change: the periodic check is the ONLY
    thing that upgrades a healthy Claude account, so a report showing zero checks
    over a week means the upgrade path is dead while nothing looks broken."""
    s = report.summarize(_SAMPLE)
    assert s["probes_run"] == 2
    assert s["probes_skipped"] == 1
    assert s["probes_already_highest"] == 1
    assert s["probes_blind"] == 1
    assert s["claude_upgrades"]["5.0 -> 6.0"] == 1


def test_summarize_counts_stepbacks_and_thinking_misses():
    s = report.summarize(_SAMPLE)
    assert s["stepbacks"]["claude"] == 1
    assert s["stepbacks_verified"] == 1
    assert s["thinking_misses"]["max effort"] == 1


def test_summarize_tolerates_a_versionless_label():
    """A version-less family label ("Opus Max") logs v None. The parser must
    count the run rather than dropping it."""
    s = report.summarize([
        "[setup_claude_dr] Step 1 OK: model already opus vNone (trigger) — NOT re-picking (#744)",
    ])
    assert s["claude_models"]["None"] == 1


def test_summarize_never_crashes_on_junk():
    s = report.summarize([None, "", "random text", "12345"])
    assert sum(s["gemini_picks"].values()) == 0
    assert sum(s["claude_models"].values()) == 0
    assert s["probes_run"] == 0


def test_format_report_runs_on_empty():
    out = report.format_report(report.summarize([]))
    assert "model selection report" in out
    assert "none - the newest model verified on every run" in out


def test_format_report_flags_a_blind_periodic_check():
    """A check that opens the popover and never sees the menu burns the whole
    interval on nothing — it must be called out, not silently counted."""
    out = report.format_report(report.summarize(_SAMPLE))
    assert "never saw the menu" in out


def test_format_report_is_ascii_safe():
    # The report prints from a Windows cp1252 console — output must encode there.
    out = report.format_report(report.summarize(_SAMPLE))
    out.encode("cp1252")  # raises UnicodeEncodeError if any non-cp1252 char slips in


def test_every_sample_line_is_matched_by_the_parser():
    """No sample may be dead weight: a stale sample is exactly how this file
    passed for a whole release while the parser matched nothing."""
    for line in _SAMPLE:
        if "unrelated log line" in line:
            continue
        s = report.summarize([line])
        counted = (sum(s["gemini_picks"].values()) + sum(s["claude_models"].values())
                   + sum(s["claude_upgrades"].values()) + s["probes_run"]
                   + s["probes_skipped"] + s["probes_already_highest"] + s["probes_blind"]
                   + sum(s["stepbacks"].values()) + s["stepbacks_verified"]
                   + sum(s["thinking_misses"].values()))
        assert counted >= 1, f"the parser no longer matches this real log line:\n  {line}"


# ── The drift guard ──────────────────────────────────────────────────────────
#
# Reconstructs the strings research.py's f-strings evaluate to, so a parser regex
# can be run against the SOURCE the way it is run against a log file. Anything
# less is a proxy: comparing hand-copied prose leaves the variable part of a
# marker — the `!r` that supplies the quotes, the arrow, the `(v…)` — free to
# move while the guard stays green.
#
# The whole module is harvested, not three named functions: a marker that moves
# to a different function is drift the report survives, and pinning the function
# list is one more thing to keep in step by hand.

# Every interpolation is replaced by each of these in turn. "48" alone satisfies
# every group shape the parser uses today (`[^']*`, `\S+`, `\w+`, `[0-9.]+`); the
# other two exist so a future regex that expects letters, or a value with a
# space, still finds a rendering rather than failing for the wrong reason.
_VALUES = ("48", "opus", "Opus 5 Max")

# Above this, the cartesian product stops being worth it and only uniform
# assignments are tried. No marker line comes close (the widest is 5). A future
# one that did would FAIL here — loudly, pointing at this constant — rather than
# quietly losing coverage.
_FULL_PRODUCT_SLOTS = 5

_RENDER_CACHE: list = []


def _render_fstring(node: ast.JoinedStr, values) -> str:
    """One concrete string an f-string could produce, honouring `!r` / `!a`.

    The conversion is the point, not a detail: `{picked!r}` is what puts the
    quotes into `'3.5 flash'`, and `_RE_GEMINI_PICK` requires them.
    """
    supply = iter(values)
    out = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            out.append(part.value)
        elif isinstance(part, ast.FormattedValue):
            value = next(supply)
            if part.conversion == ord("r"):
                out.append(repr(value))
            elif part.conversion == ord("a"):
                out.append(ascii(value))
            else:
                out.append(value)
    return "".join(out)


def _renderings(node: ast.JoinedStr) -> list:
    slots = sum(1 for p in node.values if isinstance(p, ast.FormattedValue))
    if slots == 0:
        return [_render_fstring(node, ())]
    if slots <= _FULL_PRODUCT_SLOTS:
        combos = itertools.product(_VALUES, repeat=slots)
    else:
        combos = ((v,) * slots for v in _VALUES)
    return [_render_fstring(node, c) for c in combos]


def emitted_lines(source: str) -> list:
    """Every string research.py's f-strings can evaluate to, for the values above."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.JoinedStr):
            out.extend(_renderings(node))
    return out


def _research_source() -> str:
    return pathlib.Path(research.__file__).read_text(encoding="utf-8")


def _research_emits() -> list:
    if not _RENDER_CACHE:  # parsing 50k lines once per session, not once per test
        _RENDER_CACHE.extend(emitted_lines(_research_source()))
    return _RENDER_CACHE


def _markers() -> list:
    """(name, regex) for every parser regex the report defines.

    Read off the module rather than listed here, so adding a regex to the parser
    without a marker for it is impossible — the old hand-kept list could simply
    be left one entry short.
    """
    return sorted((n, getattr(report, n)) for n in vars(report) if n.startswith("_RE_"))


def test_every_marker_matches_a_line_research_py_actually_emits():
    """⭐ THE DRIFT GUARD — and it applies `rx`, which is the whole point.

    Reword any part of a marker, fixed or interpolated, and the regex stops
    matching every reconstruction and fails HERE, instead of silently reporting
    zero of that event forever.
    """
    emits = _research_emits()
    assert len(emits) > 1000, "the f-string harvest came back near-empty; the guard is vacuous"
    markers = _markers()
    # A loop over a shortened list passes for every marker it no longer contains.
    assert len(markers) >= 11, (
        f"only {len(markers)} parser regexes reached the guard — if one was "
        f"deliberately retired, drop this floor in the same commit")
    for name, rx in markers:
        assert any(rx.search(line) for line in emits), (
            f"{name} matches nothing research.py can emit — its log line was "
            f"reworded, so the report counts zero of these forever. Pattern: "
            f"{rx.pattern!r}"
        )


def test_every_marker_matches_one_of_the_documented_samples():
    """The other half of the chain: sample → regex → source.

    Without this a regex could track research.py while `_SAMPLE` rotted, and the
    samples are what a reader consults to see what the parser is looking for.
    """
    for name, rx in _markers():
        assert any(rx.search(line) for line in _SAMPLE), (
            f"{name} matches none of _SAMPLE — the samples no longer document "
            f"what this parser reads"
        )


def test_dropping_a_repr_conversion_breaks_the_gemini_marker():
    """Guard the guard, through the SAME code path the guard uses.

    This is the mutation that survived the old prose check: `{picked!r}` →
    `{picked}` removes the quotes `_RE_GEMINI_PICK` requires, `gemini_picks` goes
    empty for every real run, and the fixed prose it compared is untouched.
    """
    src = _research_source()
    mutated = src.replace("f\"{picked!r} (v", "f\"{picked} (v")
    assert mutated != src, (
        "the Gemini pick line no longer interpolates `{picked!r}` — if it was "
        "deliberately reworded, re-point this mutation at whatever now supplies "
        "the quotes, and do not simply delete the test"
    )
    assert not any(report._RE_GEMINI_PICK.search(line) for line in emitted_lines(mutated)), (
        "dropping the !r conversion no longer breaks the Gemini marker, so the "
        "drift guard is not reading the interpolations at all"
    )
