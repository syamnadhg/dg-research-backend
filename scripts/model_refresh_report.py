#!/usr/bin/env python3
"""Phoenix (model_refresh) observability report.

Summarizes which model each P2 agent picked, any known-good fallbacks, thinking-
config misses, and ranker-vs-legacy divergences — by parsing the log lines the
pipeline ALREADY emits (no new runtime instrumentation, so this can never affect
a run). Point it at backend.log:

    python scripts/model_refresh_report.py [path/to/backend.log ...]

If no path is given it tries ./backend.log and ./logs/backend.log. This is the
deliberately-zero-risk form of Phase E telemetry; a structured JSONL writer can
be added later if structured data is wanted.
"""
from __future__ import annotations

import re
import sys
from collections import Counter

# Markers the pipeline already logs (A/B/C/D). Kept as plain substrings +
# narrow regexes so a minor log-wording change degrades to "not counted",
# never a crash.
_RE_GEMINI_PICK = re.compile(
    r"\[setup_gemini_dr\] model-pick OK: ranker clicked '([^']*)' \(v([0-9.]+|None|-1), "
    r"floor=([^)]*)\) \| legacy /3\.5 flash/ -> '([^']*)'(.*)$")
_RE_CLAUDE_KEEP = re.compile(
    r"\[setup_claude_dr\] Step 1 OK: model already Opus ([0-9.]+)")
_RE_CLAUDE_PICK = re.compile(
    r"\[setup_claude_dr\] Step 1B OK: selected (.+)$")
_RE_FALLBACK_TRY = re.compile(
    r"Phoenix: latest model unverified for Deep Research — retrying once pinned "
    r"to known-good (\w+) v([0-9.]+)")
_RE_FALLBACK_OK = re.compile(
    r"Phoenix: known-good fallback verified — proceeding on v([0-9.]+)")
_RE_THINKING_MISS = re.compile(
    r"Phoenix: proceeding with Deep Research but thinking config unconfirmed \(([^)]*)\)")


def summarize(lines) -> dict:
    """Pure: fold log lines into a summary dict. Never raises on odd input."""
    out = {
        "gemini_picks": Counter(),       # picked-label -> count
        "gemini_divergences": 0,         # ranker != legacy /3.5 flash/
        "claude_models": Counter(),      # opus version -> count
        "fallbacks": Counter(),          # platform -> count of known-good retries
        "fallbacks_verified": 0,
        "thinking_misses": Counter(),    # missing-knob text -> count
    }
    for raw in lines:
        line = (raw or "").rstrip("\n")
        m = _RE_GEMINI_PICK.search(line)
        if m:
            out["gemini_picks"][m.group(1)] += 1
            if "DIVERGES" in m.group(5):
                out["gemini_divergences"] += 1
            continue
        m = _RE_CLAUDE_KEEP.search(line)
        if m:
            out["claude_models"][m.group(1)] += 1
            continue
        m = _RE_CLAUDE_PICK.search(line)
        if m:
            # Normalize "Opus 5.0 Max" → "5.0" so picked/kept share one key.
            vm = re.search(r"opus[^0-9]*([0-9.]+)", m.group(1), re.I)
            out["claude_models"][vm.group(1) if vm else m.group(1).strip()] += 1
            continue
        m = _RE_FALLBACK_TRY.search(line)
        if m:
            out["fallbacks"][m.group(1)] += 1
            continue
        if _RE_FALLBACK_OK.search(line):
            out["fallbacks_verified"] += 1
            continue
        m = _RE_THINKING_MISS.search(line)
        if m:
            out["thinking_misses"][m.group(1)] += 1
    return out


def format_report(s: dict) -> str:
    # ASCII-only output: this is run from a Windows console (cp1252), where
    # box-drawing / checkmark / em-dash chars raise UnicodeEncodeError on print.
    lines = ["== Phoenix model_refresh report =="]
    lines.append("Gemini -- models picked (latest-Flash ranker):")
    for label, n in s["gemini_picks"].most_common() or [("(none seen)", 0)]:
        lines.append(f"    {n:>4}x  {label}")
    if s["gemini_divergences"]:
        lines.append(f"    [!] ranker diverged from legacy /3.5 flash/ on {s['gemini_divergences']} run(s) "
                     f"(a newer Flash than 3.5 was picked)")
    lines.append("Claude -- Opus version selected:")
    for ver, n in s["claude_models"].most_common() or [("(none seen)", 0)]:
        lines.append(f"    {n:>4}x  Opus {ver}")
    lines.append("Known-good fallbacks (latest model couldn't run Deep Research):")
    if sum(s["fallbacks"].values()):
        for plat, n in s["fallbacks"].most_common():
            lines.append(f"    {n:>4}x  {plat}")
        lines.append(f"    {s['fallbacks_verified']} verified on the fallback model")
    else:
        lines.append("    none - the latest model verified on every run [ok]")
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
