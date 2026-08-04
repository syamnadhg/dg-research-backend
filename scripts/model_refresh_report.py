#!/usr/bin/env python3
"""Model-selection observability report.

Summarizes which model each P2 agent actually got, whether the periodic
model-menu check is reaching the account, any step-back fallbacks, and
thinking-config misses — by parsing the log lines the pipeline ALREADY emits (no
new runtime instrumentation, so this can never affect a run). Point it at
backend.log:

    python scripts/model_refresh_report.py [path/to/backend.log ...]

If no path is given it tries ./backend.log and ./logs/backend.log.

⭐ Rewritten 2026-08-01 for family-only selection. Every marker below moved when
the version floor was removed, and the old parser silently matched NOTHING while
its own tests kept passing against sample lines the pipeline no longer emitted —
a report that reports zero looks the same as a pipeline with nothing to report.
`test_model_refresh_report.py` now cross-checks these markers against the live
f-strings in research.py so the pair cannot drift apart again.

The PROBE rows are the ones to read after this change: the periodic check is the
only thing that upgrades a healthy Claude account, so "probes seen: 0" over a
week of runs means the upgrade path is dead even though nothing looks broken.
"""
from __future__ import annotations

import re
import sys
from collections import Counter

# Markers the pipeline already logs. Kept as narrow regexes over the FIXED part
# of each format string so a minor wording change degrades to "not counted",
# never a crash — and the drift test pins the fixed parts.
_RE_GEMINI_PICK = re.compile(
    r"\[setup_gemini_dr\] model-pick OK: clicked the highest '([^']*)' offered — "
    r"'([^']*)' \(v([0-9.]+|None)\)")
_RE_CLAUDE_KEEP = re.compile(
    r"\[setup_claude_dr\] Step 1 OK: model already (\S+) v([0-9.]+|None)")
_RE_CLAUDE_PICK = re.compile(
    r"\[setup_claude_dr\] Step 1B OK: selected '([^']*)' \(v([0-9.]+|None)\)")
_RE_CLAUDE_UPGRADE = re.compile(
    r"\[setup_claude_dr\] Step 1B\* UPGRADE: (\S+) ([0-9.]+|None) → ([0-9.]+)")
_RE_PROBE_DUE = re.compile(
    r"\[setup_claude_dr\] Step 1A: model\+effort already confirmed off the trigger")
_RE_PROBE_SKIPPED = re.compile(
    r"\[setup_claude_dr\] Step 1A SKIPPED: trigger already reads")
_RE_PROBE_ALREADY_HIGHEST = re.compile(
    r"\[setup_claude_dr\] Step 1B\*: \S+ (?:[0-9.]+|None) is already the highest offered")
_RE_PROBE_BLIND = re.compile(
    r"\[setup_claude_dr\] Step 1B\*: model menu never mounted")
_RE_STEPBACK_TRY = re.compile(
    r"step-back: (\w+) v([0-9.]+|None) did not verify into Deep Research")
_RE_STEPBACK_OK = re.compile(
    r"step-back verified — proceeding on v([0-9.]+|None)")
_RE_THINKING_MISS = re.compile(
    r"proceeding with Deep Research; thinking config unconfirmed \(([^)]*)\)")


def summarize(lines) -> dict:
    """Pure: fold log lines into a summary dict. Never raises on odd input."""
    out = {
        "gemini_picks": Counter(),        # picked-label -> count
        "claude_models": Counter(),       # version -> count
        "claude_upgrades": Counter(),     # "4.8 -> 5.0" -> count
        "probes_run": 0,                  # popover opened for the periodic check
        "probes_skipped": 0,              # nothing to do, check not yet due
        "probes_already_highest": 0,       # check ran, nothing newer offered
        "probes_blind": 0,                # check ran but the menu never mounted
        "stepbacks": Counter(),           # platform -> count
        "stepbacks_verified": 0,
        "thinking_misses": Counter(),     # missing-knob text -> count
    }
    for raw in lines:
        line = (raw or "").rstrip("\n")
        m = _RE_GEMINI_PICK.search(line)
        if m:
            out["gemini_picks"][m.group(2)] += 1
            continue
        m = _RE_CLAUDE_KEEP.search(line)
        if m:
            out["claude_models"][m.group(2)] += 1
            continue
        m = _RE_CLAUDE_PICK.search(line)
        if m:
            out["claude_models"][m.group(2)] += 1
            continue
        m = _RE_CLAUDE_UPGRADE.search(line)
        if m:
            out["claude_upgrades"][f"{m.group(2)} -> {m.group(3)}"] += 1
            out["claude_models"][m.group(3)] += 1
            continue
        if _RE_PROBE_DUE.search(line):
            out["probes_run"] += 1
            continue
        if _RE_PROBE_SKIPPED.search(line):
            out["probes_skipped"] += 1
            continue
        if _RE_PROBE_ALREADY_HIGHEST.search(line):
            out["probes_already_highest"] += 1
            continue
        if _RE_PROBE_BLIND.search(line):
            out["probes_blind"] += 1
            continue
        m = _RE_STEPBACK_TRY.search(line)
        if m:
            out["stepbacks"][m.group(1)] += 1
            continue
        if _RE_STEPBACK_OK.search(line):
            out["stepbacks_verified"] += 1
            continue
        m = _RE_THINKING_MISS.search(line)
        if m:
            out["thinking_misses"][m.group(1)] += 1
    return out


def format_report(s: dict) -> str:
    # ASCII-only output: this is run from a Windows console (cp1252), where
    # box-drawing / checkmark / em-dash chars raise UnicodeEncodeError on print.
    lines = ["== model selection report =="]
    lines.append("Gemini -- newest Flash picked (dropdown opens every run):")
    for label, n in s["gemini_picks"].most_common() or [("(none seen)", 0)]:
        lines.append(f"    {n:>4}x  {label}")
    lines.append("Claude -- version in use:")
    for ver, n in s["claude_models"].most_common() or [("(none seen)", 0)]:
        lines.append(f"    {n:>4}x  v{ver}")
    lines.append("Claude -- periodic model-menu check (the ONLY thing that upgrades")
    lines.append("          a healthy account; 0 over a week means it is dead):")
    lines.append(f"    {s['probes_run']:>4}  checks run")
    lines.append(f"    {s['probes_skipped']:>4}  runs that skipped it (not due yet)")
    lines.append(f"    {s['probes_already_highest']:>4}  checks that found nothing newer")
    if s["probes_blind"]:
        lines.append(f"    [!] {s['probes_blind']} check(s) never saw the menu -- the popover "
                     f"markup may have rotated; the check is burning its interval on nothing")
    if sum(s["claude_upgrades"].values()):
        lines.append("    upgrades taken:")
        for step, n in s["claude_upgrades"].most_common():
            lines.append(f"        {n:>4}x  {step}")
    else:
        lines.append("        no upgrades taken in this window")
    lines.append("Step-backs (newest model couldn't run Deep Research):")
    if sum(s["stepbacks"].values()):
        for plat, n in s["stepbacks"].most_common():
            lines.append(f"    {n:>4}x  {plat}")
        lines.append(f"    {s['stepbacks_verified']} verified on the older model")
    else:
        lines.append("    none - the newest model verified on every run [ok]")
    lines.append("Thinking-config misses (advisory; run still proceeded):")
    if sum(s["thinking_misses"].values()):
        for miss, n in s["thinking_misses"].most_common():
            lines.append(f"    {n:>4}x  {miss}")
    else:
        lines.append("    none [ok]")
    return "\n".join(lines)


def main(argv) -> int:
    import os
    paths = argv[1:] or [p for p in ("backend.log", os.path.join("logs", "backend.log")) if os.path.exists(p)]
    if not paths:
        print("No log file given and no ./backend.log or ./logs/backend.log found.", file=sys.stderr)
        print("Usage: python scripts/model_refresh_report.py path/to/backend.log", file=sys.stderr)
        return 2
    all_lines = []
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                all_lines.extend(fh.readlines())
        except OSError as e:
            print(f"(skipping {p}: {e})", file=sys.stderr)
    print(format_report(summarize(all_lines)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
