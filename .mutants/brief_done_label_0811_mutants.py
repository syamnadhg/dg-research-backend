"""Mutation harness for the P1 "finished brief kept polling" fix.

A brief that was COMPLETE at 62492 chars polled for 40 more minutes and then sat
on a user-decision card. The vision check read the screen correctly every time —
"no stop button", "Worked for 9m" — and the classifier, whose done-marker list
was written 2026-06-02 with the single literal "thought for", matched nothing and
fell through to its ambiguous default. The caller then logged "confirms still
generating", a claim the parser had never made.

Three changes, and every one has an obvious too-far version:

  * matching the thinking-time header as a SHAPE — too far is dropping the time
    unit, which lets the report's own prose ("worked for 3 teams") declare the
    report finished;
  * reporting "recognised nothing" apart from "observed generating" — too far is
    letting ambiguous early-exit as complete;
  * completing from STATE when no wording is recognised — too far is letting
    state out-vote a positively observed "still generating", or firing without
    the flatness / size / live-page guards. Each of those is a different
    production failure this repo has already paid for once.

Half of these therefore mutate in the OVER-correction direction. A false
"complete" extracts an in-flight brief and reports "no brief generated" — the
strictly worse failure, and the whole reason #753 and #755 exist.

Safety, learned from an earlier harness on this repo that adopted a mutant as
its own baseline: refuses to start on a dirty tree, holds originals in memory
only, restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/brief_done_label_0811_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = (
    "tests/test_brief_done_label_0811.py "
    "tests/test_safety_net_verdict_753.py "
    "tests/test_safety_net_stop_veto_755.py "
    "tests/test_cua_generating_polarity.py "
    "tests/test_p1_extract_retry_754.py"
)

# (id, direction, why, [(from, to)])
MUTANTS = [
    # ── the label rot itself ────────────────────────────────────────────────
    ("L1", "under", "back to the single literal — the 2026-08-11 hang, restored",
     [(r'    r"\b(?:thought|worked|reasoned|researched)\s+for\s+\d+\s*"',
       r'    r"\b(?:thought)\s+for\s+\d+\s*"')]),
    ("L2", "under", "the header pattern is never consulted",
     [("    if _THINKING_TIME_HEADER.search(t):\n        return \"complete\"",
       "    if False and _THINKING_TIME_HEADER.search(t):\n        return \"complete\"")]),
    ("L3", "over", "the time unit is optional — report prose can declare itself done",
     [(r'    r"(?:hours|hour|hrs|hr|h|minutes|minute|mins|min|m|seconds|second|secs|sec|s)\b")',
       r'    r"(?:hours|hour|hrs|hr|h|minutes|minute|mins|min|m|seconds|second|secs|sec|s)?\b")')]),

    # ── ambiguous vs generating ─────────────────────────────────────────────
    ("A1", "under", "ambiguous collapses back into generating — the silent case returns",
     [('    return "ambiguous"', '    return "generating"')]),
    ("A2", "over", "an unrecognised read early-exits as complete",
     [('    return "ambiguous"', '    return "complete"')]),
    ("A3", "under", "the unrecognised-read WARN is gone, so a relabel is silent again",
     [('                    if _sn_verdict == "ambiguous":\n'
       '                        log(f"[{label}] Safety-net CUA verdict UNRECOGNISED',
       '                    if False:\n'
       '                        log(f"[{label}] Safety-net CUA verdict UNRECOGNISED')]),
    ("A4", "over", "ambiguous no longer keeps polling",
     [('                    _sn_is_generating = _sn_verdict in ("generating", "ambiguous")',
       '                    _sn_is_generating = _sn_verdict == "generating"')]),

    # ── the label-free completion rule (now a callable, so these are real) ──
    ("S1", "under", "the label-free path never fires — the 40-minute hang returns",
     [("    if page_dead_reason:\n        return False\n    return True",
       "    if page_dead_reason:\n        return False\n    return False")]),
    ("S2", "over", "a live Stop button no longer blocks it",
     [("    if hard_stop_signal:\n        return False\n", "")]),
    ("S3", "over", "a streaming stub is enough to call it done",
     [("    if text_len < min_len:\n        return False\n", "")]),
    ("S4", "over", "one flat poll is enough — no window required",
     [("    if flat_sec < window_sec:\n        return False\n", "")]),
    ("S5", "over", "a dead tab counts as a finished brief (the 2026-08-09 failure)",
     [("    if page_dead_reason:\n        return False\n", "")]),
    ("S6", "over", "state out-votes a positively observed 'still generating'",
     [('    if verdict != "ambiguous":\n        return False\n', "")]),
    ("S7", "under", "it completes but leaves no evidence for why",
     [('                            log(f"[{label}] Safety-net: no completion WORDING recognised, but "',
       '                            log(f"[{label}] Safety-net: complete "  # ')]),
    ("S8", "over", "the call site stops probing the page and always passes 'alive'",
     [("                        _lf_dead = await _page_is_dead(page)",
       "                        _lf_dead = None")]),
    ("S9", "under", "the call site re-decides inline instead of delegating",
     [("                        if _state_says_brief_is_done(",
       "                        if False and _state_says_brief_is_done(")]),

    # ── the salvage action ──────────────────────────────────────────────────
    ("K1", "over", "the salvage action is offered against an empty screen again",
     [("        if _p1s_salvageable:\n            _p1s_actions.append({\"id\": \"skip\"",
       "        if True:\n            _p1s_actions.append({\"id\": \"skip\"")]),
    ("K2", "under", "the button goes back to claiming it is a skip",
     [('"label": "Use what\'s on screen",', '"label": "Skip",')]),
    ("K3", "over", "the salvage floor drifts below the extract accept gate",
     [("_MIN_SALVAGEABLE_BRIEF_LEN = 2000", "_MIN_SALVAGEABLE_BRIEF_LEN = 1")]),
    ("K4", "over", "an unknown stalled length is treated as salvageable",
     [("        self.text_len = int(text_len or 0)", "        self.text_len = int(text_len or 10**9)")]),
    ("K5", "over", "retry is honoured past the attempt cap and recurses",
     [('            if p1s_decision == "retry" and retries_left_p1s > 0:',
       '            if p1s_decision == "retry":')]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    return sh([sys.executable, "-m", "pytest", *SUITES.split(), "-q"]).returncode == 0


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    path = ROOT / RESEARCH
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found: {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests()
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, why))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
