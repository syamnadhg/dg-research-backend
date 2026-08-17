"""Mutation harness for "somebody must press Gemini's Start research button".

⛔ THE REPORT: Gemini auto-skipped after 90 minutes without ever starting. Two
detectors named the state once a minute for the whole hour and a half — the DOM
one as `start_research_btn_visible (pre-research)`, the vision one literally as
"This is the NEEDS_CLICK state" — and nothing pressed the button.

⭐ The press machinery already existed and was already careful (bounded,
enabled-only, took-checked on the following leg). It was armed for a
still-streaming hand-off and NOT for the one state both failing runs ended in: we
pressed Start and could not confirm it took.

⭐ THE OVER-CORRECTIONS matter more than usual here, because "click Start more"
has a genuinely bad failure mode of its own:
  G3 — the watch armed unconditionally. On a FINISHED research the plan bubble
       keeps a grayed Start in the scrollback, so this re-arms forever and hides
       a dead Gemini behind endless re-arming.
  G6 — ⛔⛔ the done-markers stop outranking the stale Start button. That is the
       2026-07-13 disease, and arming the watch more often makes it far worse: it
       would start pressing a leftover button on a completed report.
  G8 — the needs_click branch presses the button itself, bypassing every guard
       the watch leg has.

    .venv/bin/python .mutants/gemini_start_watch_0817_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = "research.py"
MUTATED_FILES = [SRC]

T_WATCH = "tests/test_gemini_start_watch_0817.py"
T_DET = "tests/test_completion_determination_948.py"
ALL = [T_WATCH, T_DET]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 180

_ARM = ('                                "gemini_watch_start": bool(\n'
        '                                    _streaming_handoff\n'
        '                                    or (start_clicked and not verified_b))}')

MUTANTS = [
    # ── the arming condition ────────────────────────────────────────────────
    ("G1", "under", "⭐⭐ THE ORIGINAL BUG — the watch arms only for a streaming "
     "hand-off, so an unverified Start click is never pressed again and the run "
     "burns to the 90-minute auto-skip",
     [(_ARM, '                                "gemini_watch_start": bool(_streaming_handoff)}')],
     [T_WATCH]),
    ("G2", "under", "the streaming case is dropped while fixing the other one — a "
     "slow plan that finishes drafting after hand-off loses its clicker",
     [(_ARM, '                                "gemini_watch_start": bool(\n'
             '                                    start_clicked and not verified_b)}')],
     [T_WATCH]),
    ("G3", "over", "⛔ the watch is armed on every run. On a FINISHED research the "
     "plan bubble keeps a grayed Start forever, so this re-arms endlessly and "
     "hides a genuinely dead Gemini behind it",
     [(_ARM, '                                "gemini_watch_start": bool(True)}')],
     [T_WATCH]),
    ("G4", "over", "the arming ignores whether we ever clicked, so a Gemini that "
     "was never started by us — a user-skip, an error card — gets clicked at",
     [(_ARM, '                                "gemini_watch_start": bool(\n'
             '                                    _streaming_handoff or not verified_b)}')],
     [T_WATCH]),
    ("G5", "under", "the two flags disagree again: needs_start_verify acts on the "
     "unverified click and the watch does not, which is exactly the split that "
     "cost the agent",
     [('                                "needs_start_verify": bool(start_clicked and not verified_b),',
       '                                "needs_start_verify": False,')],
     [T_WATCH]),

    # ── the stale-Start guard this fix leans on ─────────────────────────────
    ("G6", "over", "⛔⛔ the completed-report markers stop outranking the stale "
     "Start button — the 2026-07-13 disease, and now much worse, because the "
     "watch is armed more often and would press a leftover button on a finished "
     "research",
     [('        if data.get("reportButtonTrio"):\n'
       '            return (True, f"no_stop + report_button_trio (Contents/Share & Export/Create){stale}", snap)',
       '        if False:\n'
       '            return (True, f"no_stop + report_button_trio (Contents/Share & Export/Create){stale}", snap)')],
     [T_WATCH, T_DET]),
    ("G7", "over", "the completion chat line stops outranking it too — same "
     "disease through the other marker",
     [('        if data.get("completedChatText"):\n'
       '            return (True, f"no_stop + completed_chat_text{stale}", snap)',
       '        if False:\n'
       '            return (True, f"no_stop + completed_chat_text{stale}", snap)')],
     [T_WATCH, T_DET]),

    # ── the verdict that was parsed and dropped ────────────────────────────
    ("G8", "under", "⛔ `needs_click` goes back to being parsed and discarded, so "
     "the vision tier can name the state in words and nothing acts on it",
     [('                if verdict == "needs_click" and name.lower() == "gemini":',
       '                if False and name.lower() == "gemini":')],
     [T_WATCH]),
    ("G9", "over", "the re-arm fires for every agent, setting a Gemini-shaped flag "
     "off a ChatGPT or Claude verdict where nothing reads it",
     [('                if verdict == "needs_click" and name.lower() == "gemini":',
       '                if verdict == "needs_click":')],
     [T_WATCH]),
    ("G10", "over", "the WARN fires on every completion check instead of on the "
     "transition, burying the one line that matters under repeats",
     [('                    if not p.get("gemini_watch_start"):', '                    if True:')],
     [T_WATCH]),

    # ── the card withdrawn from a dead run ─────────────────────────────────
    ("G11", "under", "⛔ the plan-stall card is retracted on a click that merely "
     "returned true again — the live run withdrew the user's only actionable "
     "surface six seconds before the verify disagreed",
     [('                        await asyncio.sleep(5)\n                        break\n                    await asyncio.sleep(5)',
       '                        _retract_plan_alert("CUA recovery re-draft")\n'
       '                        await asyncio.sleep(5)\n                        break\n                    await asyncio.sleep(5)')],
     [T_WATCH]),
    ("G12", "under", "the retraction never happens at all, so a healthy "
     "researching Gemini keeps a stale [Retry][Skip] card sitting on it",
     [('            _retract_plan_alert("verified running")\n', '')],
     [T_WATCH]),
    ("G13", "over", "the retraction stops being idempotent, so the paths that can "
     "now both reach it emit a duplicate 'recovered' event",
     [('            if not _plan_alert_emitted:\n                return',
       '            if False:\n                return')],
     [T_WATCH]),
]


def green(tests):
    try:
        rc = subprocess.run([PY, "-m", "pytest", "-q", *tests], cwd=ROOT,
                            capture_output=True, timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def snapshot():
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before):
    return [f for f, t in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != t]


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
