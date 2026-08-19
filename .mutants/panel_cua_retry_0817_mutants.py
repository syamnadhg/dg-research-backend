"""Mutation harness for "one flaky click must not cost a phase its narration".

⛔ THE REPORT (owner, mid-e2e 2026-08-17): ChatGPT P1 never opened the activity /
sources panel, so the app's raw-activity drilldown stayed empty for the phase.

⭐⭐ The log said something neither of us expected: the DOM rung missed the strip
in BOTH of the last two runs, identically. Nothing regressed — the feature had
quietly come to rest on a single CUA click, and the runs differed only in whether
that one click landed. When it did not, the one-shot cap meant eleven further
minutes of polling produced nothing at all.

⭐ THE OVER-CORRECTIONS ARE THE POINT here, because "retry more" is a cost and a
mis-click risk, not a free win:
  P4 — the attempt ceiling back as its own literal, free to drift from the table.
       ⛔ Its first version — "delete the ceiling" — SURVIVED, and so did P8,
       because the ceiling and the table-bounds check were numerically identical:
       each was the other's only protection, so neither could be killed. The
       redundancy was removed rather than tested around, which is this repo's own
       rule for a pair of guards that cover for each other.
  P5 — retries fire back-to-back, so attempt 2 is the same click against the same
       pixels a second later, i.e. the same failure.
  P7 — ⛔⛔ the caller's "there is legitimately nothing to click" block is
       dropped, so a FINISHED deep-research panel gets clicked at 21 times again
       (the 2026-07-13 night run).
  P9 — ⛔ `= 1` instead of `+= 1`: the counter can never pass one, so the schedule
       keeps granting attempt 1 forever — an unbounded retry wearing the cap's
       clothes.

    .venv/bin/python .mutants/panel_cua_retry_0817_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = "research.py"
MUTATED_FILES = [SRC]

T_RETRY = "tests/test_panel_cua_retry_0817.py"
T_CHIP = "tests/test_completion_determination_948.py"
ALL = [T_RETRY, T_CHIP]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 180

MUTANTS = [
    # ── the schedule ────────────────────────────────────────────────────────
    # The ceiling is derived from the table now, so "one attempt ever" — the
    # original bug — is expressed by shortening the table to one entry.
    ("P1", "under", "⭐⭐ THE ORIGINAL BUG — one attempt, ever. A flaky click "
     "costs the phase every source and all its narration",
     [("_PANEL_CUA_RETRY_AT_MISSES = (2, 6, 14)",
       "_PANEL_CUA_RETRY_AT_MISSES = (2,)")],
     [T_RETRY]),
    ("P2", "under", "the first attempt moves later, so a short phase never gets "
     "one at all",
     [("_PANEL_CUA_RETRY_AT_MISSES = (2, 6, 14)",
       "_PANEL_CUA_RETRY_AT_MISSES = (8, 12, 20)")],
     [T_RETRY]),
    ("P3", "under", "⛔ the last chance lands after a 12-minute phase has already "
     "finished — a retry that cannot happen is not a retry",
     [("_PANEL_CUA_RETRY_AT_MISSES = (2, 6, 14)",
       "_PANEL_CUA_RETRY_AT_MISSES = (2, 6, 40)")],
     [T_RETRY]),
    # P4 was "delete the _PANEL_CUA_MAX_ATTEMPTS ceiling". It SURVIVED, and so
    # did P8 — because the ceiling and the table-bounds check were numerically
    # identical, so each was the other's only protection. The redundancy was
    # removed (one bound now) and this took its place: the ceiling reappearing as
    # an independent literal is what would let them drift apart again.
    ("P4", "over", "the attempt ceiling goes back to being its own literal, so it "
     "can disagree with the schedule table and one of the two becomes untestable",
     [("_PANEL_CUA_MAX_ATTEMPTS = len(_PANEL_CUA_RETRY_AT_MISSES)",
       "_PANEL_CUA_MAX_ATTEMPTS = 3")],
     [T_RETRY]),
    ("P5", "over", "⭐ the retries stop being spaced: attempt 2 fires on the very "
     "next poll, which is the same click against the same pixels",
     [("    return dom_misses >= _PANEL_CUA_RETRY_AT_MISSES[attempts]",
       "    return dom_misses >= _PANEL_CUA_RETRY_AT_MISSES[0]")],
     [T_RETRY]),
    ("P6", "over", "an already-open panel is clicked again — the strip is a "
     "TOGGLE, so this closes the panel it just opened",
     [("    if panel_open:\n        return False\n", "")],
     [T_RETRY, T_CHIP]),
    ("P7", "over", "⛔⛔ the caller's 'nothing to click' block is ignored, so a "
     "finished deep-research panel gets hunted 21 times again",
     [("    if blocked:\n        return False\n", "")],
     [T_RETRY, T_CHIP]),
    ("P8", "over", "the schedule index runs off the end of the table instead of "
     "refusing — an IndexError inside the poll loop",
     [("    if attempts >= len(_PANEL_CUA_RETRY_AT_MISSES):\n        return False\n", "")],
     [T_RETRY]),
    ("P10", "under", "the threshold becomes exclusive, so every attempt waits one "
     "extra poll and the first one slips past the early window",
     [("    return dom_misses >= _PANEL_CUA_RETRY_AT_MISSES[attempts]",
       "    return dom_misses > _PANEL_CUA_RETRY_AT_MISSES[attempts]")],
     [T_RETRY]),

    # ── the call sites (a helper is not a fix until something calls it) ─────
    ("P9", "over", "⛔ P1 assigns instead of incrementing — the counter can never "
     "pass one, so the schedule grants attempt 1 forever: an unbounded retry "
     "disguised as the cap",
     [("                        _panel_cua_attempts += 1",
       "                        _panel_cua_attempts = 1")],
     [T_RETRY]),
    ("P11", "over", "P2 ChatGPT assigns instead of incrementing — same unbounded "
     "retry, different variable",
     [('                    p["chatgpt_panel_cua_attempts"] = p.get("chatgpt_panel_cua_attempts", 0) + 1',
       '                    p["chatgpt_panel_cua_attempts"] = 1')],
     [T_RETRY]),
    ("P12", "over", "Claude assigns instead of incrementing",
     [('                    p["claude_artifact_cua_attempts"] = p.get("claude_artifact_cua_attempts", 0) + 1',
       '                    p["claude_artifact_cua_attempts"] = 1')],
     [T_RETRY]),
    ("P13", "under", "P1 goes back to a hand-rolled one-shot condition, leaving "
     "the shared schedule perfect and unused at the site that reported the bug",
     [("                    if (panel_cua_should_escalate(\n"
       "                                dom_misses=_panel_dom_misses,\n"
       "                                attempts=_panel_cua_attempts,\n"
       "                                panel_open=_panel_open_done)\n"
       "                            and cua_client and browser):",
       "                    if (not _panel_open_done\n"
       "                            and _panel_dom_misses >= 2\n"
       "                            and _panel_cua_attempts == 0\n"
       "                            and cua_client and browser):")],
     [T_RETRY]),
    ("P14", "over", "Claude's artifact COUNT is queried before the cheap schedule "
     "check, paying for a DOM query on every quiet poll of every P2 run",
     [("                if (panel_cua_should_escalate(\n"
       "                            dom_misses=p.get(\"claude_artifact_dom_misses\", 0),\n"
       "                            attempts=p.get(\"claude_artifact_cua_attempts\", 0),\n"
       "                            panel_open=bool(p.get(\"artifact_panel_open\")))\n"
       "                        and cua_client\n"
       "                        and await _count_claude_artifacts(p[\"page\"]) > 0):",
       "                if (await _count_claude_artifacts(p[\"page\"]) > 0\n"
       "                        and panel_cua_should_escalate(\n"
       "                            dom_misses=p.get(\"claude_artifact_dom_misses\", 0),\n"
       "                            attempts=p.get(\"claude_artifact_cua_attempts\", 0),\n"
       "                            panel_open=bool(p.get(\"artifact_panel_open\")))\n"
       "                        and cua_client):")],
     [T_RETRY]),

    # ── the diagnostic that has to answer the DOM question next run ─────────
    ("P15", "under", "⭐ the snapshot stops deduping, so all 20 rows come back as "
     "the same nested line again and the strip's neighbours stay invisible — the "
     "exact reason no wording-free matcher exists yet",
     [("            if (seen.has(key)) {", "            if (false) {")],
     [T_RETRY]),
    ("P16", "under", "the shimmer is only ever looked for on the element itself, "
     "which is what reported anim:false on a line the vision tier described as "
     "shimmering",
     [("                for (const kid of el.querySelectorAll('*')) {\n"
       "                    if (shimmers(kid)) { animKid = true; break; }\n"
       "                }", "")],
     [T_RETRY]),
    ("P17", "under", "the log line is cut back to 1800 chars, which after the "
     "dedupe throws away exactly the tail the neighbours moved into",
     [("{line[:3500]}", "{line[:1800]}")],
     [T_RETRY]),
]


def green(tests):
    try:
        # ⛔⛔ MEASURED 2026-08-18: a stale `__pycache__/*.pyc` served OLD bytecode
        # for a source file that had already been fixed, and the measurement
        # disagreed with the file for three rounds. In a harness that rewrites the
        # source between every run, a cached module is not a nuisance — it is a
        # kill or a survivor invented out of nothing. Three earlier waves had
        # already learned this and set the flag; it was never propagated.
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def snapshot():
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before):
    return [f for f, text in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != text]


def main() -> int:
    before = snapshot()
    print("baseline… ", end="", flush=True)
    ok, t_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if t_out else 'RED'}. Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors, stale = [], []
    for mid, direction, why, edits, tests in MUTANTS:
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs 1): {frm[:60]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, t_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed)" if t_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif t_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}", flush=True)
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
