"""Mutation harness for S1/S2/S3 — the visual-confirm budget.

The fix has three halves and they fail in opposite directions, so both are
weighted:

  UNDER — put the unbounded loop back. Delete the corroborator, delete the
  budget, reset the DOM streak on a veto, drop the timeout. Any one of these
  returns the 2026-08-12 behaviour: 44 minutes and ~40 visual confirms spent
  arguing with a DOM that was right.

  OVER — ⛔ the more dangerous direction, and where most of the weight sits.
  Make the corroborator always true, or let a length signal corroborate, or
  drop the polarity rule so a budget that ran out with a Stop button named
  every time silently extracts instead of asking. Each of those trades a slow
  run for a WRONG one: an in-flight brief extracted as finished, which the
  #753/#755 notes both record as the strictly worse failure.

The single most important mutant in this file is O1. If a corroborator that
always says "done" survives, then S1 is not "skip the confirm when the page
agrees" — it is "never confirm", which is the failure mode the confirm loop
was built to prevent.

Safety: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, re-checks `git status` at the end.

    .venv/bin/python .mutants/cua_confirm_budget_0812_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = ("tests/test_cua_confirm_budget_0812.py "
          "tests/test_done_badge_one_pattern_0812.py "
          "tests/test_brief_done_label_0811.py "
          "tests/test_safety_net_verdict_753.py "
          "tests/test_safety_net_stop_veto_755.py "
          "tests/test_cua_generating_polarity.py "
          "tests/test_p1_extract_retry_754.py")

MUTANTS = [
    # ══════════════ S1 — the corroborator (OVER is the danger) ═════════════
    ("O1", "over", "⛔⛔ the corroborator always says done — S1 becomes 'never confirm'",
     [('    try:\n'
       '        hit = await page.evaluate(_DONE_BADGE_PROBE_JS)\n'
       '        if hit:\n'
       '            return str(hit)',
       '    try:\n'
       '        await page.evaluate(_DONE_BADGE_PROBE_JS)\n'
       '        return "always"')]),
    ("O2", "over", "⛔ a length signal corroborates — an in-flight brief reads as done",
     [("            _done_badge = await _chatgpt_done_badge(page)",
       "            _done_badge = (await _chatgpt_done_badge(page)) or (\n"
       '                "2000+ chars" if last_seen_len >= 2000 else "")')]),
    ("O3", "over", "⛔ an unreadable page corroborates instead of routing to vision",
     [("    except Exception:\n"
       "        # A page that cannot be read is not a page that says \"done\". Returning\n"
       "        # \"\" routes to the visual confirm, which is the correct fallback: no\n"
       "        # corroboration means the DOM is on its own.\n"
       '        return ""',
       "    except Exception:\n"
       '        return "unreadable"')]),
    ("U1", "under", "⭐ the corroborator is never consulted — every finished brief pays for a confirm",
     [("            _done_badge = await _chatgpt_done_badge(page)",
       '            _done_badge = ""')]),
    ("U2", "under", "the corroborator is read once and cached — a late badge never ends the argument",
     [("            _done_badge = await _chatgpt_done_badge(page)",
       "            _done_badge = (await _chatgpt_done_badge(page)\n"
       "                           if consecutive_not_generating == 2 else \"\")")]),
    ("U3", "under", "the badge is read but the gate ignores it",
     [('            if _done_badge:\n                _skip_confirm = f"the page itself shows {_done_badge!r}"',
       "            if False:\n                _skip_confirm = \"\"")]),
    ("U4", "under", "the DR-frame walk is dropped — a canvas-rendered answer never corroborates",
     [("        for frame in _chatgpt_surface_frame_targets(page)[1:]:\n"
       "            try:\n"
       "                hit = await frame.evaluate(_DONE_BADGE_PROBE_JS)\n"
       "                if hit:\n"
       "                    return str(hit)",
       "        for frame in _chatgpt_surface_frame_targets(page)[1:]:\n"
       "            try:\n"
       "                pass")]),

    # ════════════════════ S2 — the budget and its polarity ═════════════════
    ("U5", "under", "⭐ the budget is gone — the disagreement is unbounded again",
     [("    _CUA_CONFIRM_BUDGET = 3", "    _CUA_CONFIRM_BUDGET = 10**9")]),
    ("U6", "under", "⭐ the DOM streak is reset on a veto — the exact 2026-08-12 loop",
     [("                if _verdict == \"generating\":\n",
       "                if _verdict == \"generating\":\n"
       "                    consecutive_not_generating = 0\n")]),
    ("U7", "under", "the budget counter never advances",
     [("                cua_confirms_spent += 1", "                cua_confirms_spent += 0")]),
    ("U8", "under", "a failed confirm no longer costs budget — a dead endpoint loops forever",
     [("                if diag.get(\"status\") in (\"error\", \"max_iterations\"):",
       "                if (cua_confirms_spent := cua_confirms_spent - 1) >= 0 and diag.get(\"status\") in (\"error\", \"max_iterations\"):")]),
    ("U9", "under", "⭐ the timeout is gone — one diagnosis can run for as long as it likes",
     [("                    return await asyncio.wait_for(\n"
       "                        agent_loop(cua_client, browser, PROMPT_DIAGNOSE,\n"
       "                            _CONFIRM_COMPLETION_MISSION,\n"
       "                            model=CUA_MODEL, max_iterations=3, verbose=verbose),\n"
       "                        timeout=_CUA_CONFIRM_TIMEOUT_S)",
       "                    return await agent_loop(cua_client, browser, PROMPT_DIAGNOSE,\n"
       "                            _CONFIRM_COMPLETION_MISSION,\n"
       "                            model=CUA_MODEL, max_iterations=3, verbose=verbose)")]),
    ("U10", "under", "the backoff is flat — the argument gets cheaper but not shorter",
     [("    _CUA_CONFIRM_BACKOFF = (60, 120, 240)", "    _CUA_CONFIRM_BACKOFF = (60, 60, 60)")]),
    ("U11", "under", "the backoff always uses the first step",
     [("                    _backoff = _CUA_CONFIRM_BACKOFF[\n"
       "                        min(cua_confirms_spent, len(_CUA_CONFIRM_BACKOFF)) - 1]",
       "                    _backoff = _CUA_CONFIRM_BACKOFF[0]")]),
    ("O4", "over", "⛔ polarity is dropped — a real sensor conflict silently extracts",
     [("                if cua_stop_sightings >= _CUA_CONFIRM_BUDGET:",
       "                if False:")]),
    ("O5", "over", "⛔ any single Stop sighting contests — one flaky read becomes a user card",
     [("                if cua_stop_sightings >= _CUA_CONFIRM_BUDGET:",
       "                if cua_stop_sightings >= 1:")]),
    ("O6", "over", "the stop sighting is never counted, so the conflict can never be reported",
     [("                if _stop_seen:\n                    cua_stop_sightings += 1", "")]),
    ("O7", "over", "⛔ the contested raise becomes a silent return — no card, no decision",
     [("                    raise _BriefStreamStalled(\n"
       "                        f\"phase {phase} completion is contested \"",
       "                    return True\n"
       "                    raise _BriefStreamStalled(\n"
       "                        f\"phase {phase} completion is contested \"")]),
    ("O8", "over", "the budget resets whenever the DOM flips back — an oscillating page argues forever",
     [("        else:\n            consecutive_not_generating = 0\n"
       "            cua_checked = False  # Reset so CUA can check again if needed",
       "        else:\n            consecutive_not_generating = 0\n"
       "            cua_confirms_spent = 0\n"
       "            cua_stop_sightings = 0\n"
       "            cua_checked = False  # Reset so CUA can check again if needed")]),

    # ════════════════ S2 — the verdict routing (the #753 twin) ═════════════
    ("U12", "under", "⭐ 'ambiguous' vetoes again — 'I could not read the screen' blocks the phase",
     [('                if _verdict == "generating":',
       '                if _verdict in ("generating", "ambiguous"):')]),
    ("O9", "over", "⛔ a positively observed Stop button no longer vetoes at all",
     [('                if _verdict == "generating":', "                if False:")]),
    ("O10", "over", "⛔ the hardened parser is replaced by the greedy substring it replaced",
     [("                _verdict = _classify_completion_verdict(diag_text)",
       '                _verdict = ("complete" if "response complete" in diag_text.lower()\n'
       '                            else "generating")')]),
    ("U13", "under", "an error verdict is parsed as if it were a reading",
     [('                if diag.get("status") in ("error", "max_iterations"):',
       '                if diag.get("status") in ("error",) and False:')]),

    # ═══════════════════════ S3 — the mission prompt ═══════════════════════
    ("U14", "under", "⭐ the unanswerable AND is restored — completion needs the final paragraph",
     [('    "3) If you can see neither — the screen is blank, obscured, or you genuinely "\n'
       '    "cannot tell — reply \'cannot determine\' and describe what IS on screen. Never "\n'
       '    "guess: \'cannot determine\' is a valid and useful answer.")',
       '    "Only say \'response complete\' if there is NO stop button AND the final "\n'
       '    "paragraph of the response is visible.")')]),
    ("U15", "under", "the third verdict is dropped — 'I cannot tell' has to be spelled as a verdict",
     [('    "3) If you can see neither — the screen is blank, obscured, or you genuinely "\n'
       '    "cannot tell — reply \'cannot determine\' and describe what IS on screen. Never "\n'
       '    "guess: \'cannot determine\' is a valid and useful answer.")',
       '    "")')]),
    ("U16", "under", "the mission names only the old time badge",
     [('    "as \'Thought for 1m 14s\' or \'Worked for 16m 26s\'; a completed document or "',
       '    "as \'Thought for 1m 14s\'; a completed document or "')]),
    ("O11", "over", "the no-click instruction is dropped — the inspector may press Stop",
     [('"'"'Activity'"'"' side panel — all of those are normal. Observe only; do not click "\n'
       '    "anything.\\n"',
       '"'"'Activity'"'"' side panel — all of those are normal.\\n"')]),

    # ═══════════════════════ the contested card copy ═══════════════════════
    ("O12", "over", "⛔ the contested card claims the page stopped, which may be false",
     [('    if contested:\n        if salvageable:\n            return ("Couldn\'t confirm ChatGPT finished",',
       '    if contested and False:\n        if salvageable:\n            return ("Couldn\'t confirm ChatGPT finished",')]),
    ("O13", "over", "the salvage count is quoted on a card that offers no salvage",
     [('        return ("Couldn\'t confirm ChatGPT finished",\n'
       '                "Two checks disagree about whether ChatGPT is still writing, and "\n'
       '                "there isn\'t enough on screen to use either way. Retry starts the "\n'
       '                "brief over — the run cannot continue without a brief.")',
       '        return ("Couldn\'t confirm ChatGPT finished",\n'
       '                f"Two checks disagree about whether ChatGPT is still writing, and "\n'
       '                f"there isn\'t only {chars} on screen to use either way. Retry starts the "\n'
       '                f"brief over — the run cannot continue without a brief.")')]),
    ("U17", "under", "`contested` defaults to True — every 20-minute stall gets the wrong copy",
     [("    def __init__(self, message: str = \"\", text_len: int = 0, contested: bool = False):",
       "    def __init__(self, message: str = \"\", text_len: int = 0, contested: bool = True):")]),
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
            survivors.append((mid, direction, f"ANCHOR MISS: {exc}"))
        finally:
            path.write_text(original, encoding="utf-8")

    still_dirty = tracked_dirty()
    if still_dirty:
        print("\n⛔ the tree did not come back clean:\n" + "\n".join(still_dirty))
        return 2

    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed")
    for mid, direction, why in survivors:
        print(f"  SURVIVED {mid} [{direction}] {why}")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
