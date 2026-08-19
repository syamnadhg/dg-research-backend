"""Mutation harness for the 2026-08-17 narration + plan-card wave.

⛔ TWO REPORTS FROM ONE E2E:
  * Gemini's early [Retry][Skip] card fired at 248s and the plan arrived 25s
    later — while the very next log line read "(248s / 300s)". We told the owner
    an agent had failed while we ourselves were still waiting for it.
  * Five narration lines in the Phase 1 card, cut mid-phrase: "ChatGPT is
    selecting its", "Data thinness check: We", "ChatGPT is launching its deep".

⭐ THE OVER-CORRECTIONS ARE THE SHARP END, because both fixes make things STRICTER
and a strict gate with no floor is how a live surface goes silent:
  N1  — the timer arm is tied so hard the operator's setting is ignored.
  N4  — the regen arm is tied to the clock too, so PROOF of failure has to wait
        out a timer and #921's whole point is lost.
  N9  — the card is never raised at the give-up point, which (because the break
        sits above the card block) makes the timer arm unreachable and silently
        deletes the protection.
  N13 — the narration gate demands a sentence but the fallback templates are no
        longer checked against it, so a strict gate could silence the card.
  N16 — the trim mistakes a hostname for the end of a sentence and cuts every
        cited line in half, manufacturing the defect it is here to prevent.

    python .mutants/narration_plan_card_0817_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_narration_and_plan_card_0817.py"
T_921 = "tests/test_alert_consistency_921.py"
T_929 = "tests/test_bug_batch_929.py"
T_953 = "tests/test_bugs_953.py"
T_WATCH = "tests/test_gemini_start_watch_0817.py"
ALL = [T_NEW, T_921, T_929, T_953, T_WATCH]

PY = str(ROOT / ".venv" / "bin" / "python")

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ── the plan card ───────────────────────────────────────────────────────
    ("N1", "over", "⛔ THE ORIGINAL FALSE ALARM — the timer arm is untied from "
     "the loop's own patience and cries wolf 52s early again",
     [("    return elapsed >= max(float(alert_sec), float(wait_max_sec))",
       "    return elapsed >= float(alert_sec)")],
     [T_NEW]),
    ("N2", "over", "the operator's setting is discarded, so an explicitly "
     "quieter card becomes a louder one",
     [("    return elapsed >= max(float(alert_sec), float(wait_max_sec))",
       "    return elapsed >= float(wait_max_sec)")],
     [T_NEW]),
    ("N3", "under", "`max` becomes `min`+something unreachable — the card never "
     "fires on time at all",
     [("    return elapsed >= max(float(alert_sec), float(wait_max_sec))",
       "    return elapsed >= max(float(alert_sec), float(wait_max_sec)) * 10")],
     [T_NEW]),
    ("N4", "over", "⛔⛔ EXHAUSTED RE-DRAFTS HAVE TO WAIT OUT THE CLOCK — #921 "
     "exists precisely so proof of failure does not",
     [("    if regen_capped:\n        return True",
       "    if regen_capped:\n        pass")],
     [T_NEW]),
    ("N5", "under", "a visibly streaming plan is carded again — the 2026-07-09 "
     "false alarm that auto-skipped a working Gemini",
     [("    if streaming_recent:\n        return False\n    if regen_capped:",
       "    if False:\n        return False\n    if regen_capped:")],
     [T_NEW]),
    ("N6", "over", "the regen cap outranks live streaming, so a plan drafting in "
     "front of us is declared dead on its history",
     [("    if streaming_recent:\n        return False\n    if regen_capped:\n        return True",
       "    if regen_capped:\n        return True\n    if streaming_recent:\n        return False")],
     [T_NEW]),
    ("N7", "over", "a clicked Start still cards — an alert about something that "
     "has already happened",
     [("    if start_clicked:\n        return False", "    if False:\n        return False")],
     [T_NEW]),
    ("N8", "under", "the card site goes back to comparing the two numbers "
     "itself, so the tie is only in a helper nothing calls",
     [("""            if _gemini_plan_card_due(
                    elapsed=_elapsed, wait_max_sec=_start_wait_max_sec,
                    alert_sec=_PLAN_ALERT_SEC, regen_capped=_regen_cap_emitted,
                    streaming_recent=_streaming_recent,
                    start_clicked=bool(start_clicked)):
                _raise_plan_alert("plan clearly failed")""",
       """            if (not start_clicked and not _streaming_recent
                    and (_regen_cap_emitted or _elapsed > _PLAN_ALERT_SEC)):
                _raise_plan_alert("plan clearly failed")""")],
     [T_NEW]),
    ("N9", "under", "⛔⛔ the card is not raised at the give-up point — and since "
     "the break sits ABOVE the card block, the timer arm becomes unreachable "
     "and #921's protection is silently gone",
     [("""                if _gemini_plan_card_due(
                        elapsed=_elapsed, wait_max_sec=_start_wait_max_sec,
                        alert_sec=_PLAN_ALERT_SEC,
                        regen_capped=_regen_cap_emitted,
                        streaming_recent=_streaming_recent,
                        start_clicked=bool(start_clicked)):
                    _raise_plan_alert("our own plan-wait budget is spent")
                break""",
       "                break")],
     [T_NEW]),
    ("N10", "over", "the once-only guard goes, so every tick re-cards a stalled "
     "plan",
     [("            if _plan_alert_emitted or _controls.is_stop():\n                return",
       "            if False:\n                return")],
     [T_NEW]),

    # ── narration ───────────────────────────────────────────────────────────
    ("N11", "under", "⛔ THE `and` IS BACK — a 4-word fragment that is 24 "
     "characters long is shown to the owner again",
     [("    if len(words) < 5 or len(s) < 22:", "    if len(words) < 5 and len(s) < 22:")],
     [T_NEW]),
    ("N12", "under", "⭐⭐ the complete-sentence rule goes, and every line in the "
     "owner's screenshot ships again",
     [("    if not _narration_last_sentence(s):\n        return False",
       "    if False:\n        return False")],
     [T_NEW]),
    ("N13", "over", "the rule accepts anything with a dot ANYWHERE, so "
     "'reading docs.nvidia.com and' reads as a finished sentence",
     [("""        if i + 1 < len(s) and not s[i + 1].isspace():
            continue""",
       "        pass")],
     [T_NEW]),
    ("N14", "under", "'!' stops ending a sentence",
     [('        if ch not in ".!":', '        if ch not in ".":')],
     [T_NEW]),
    ("N15", "over", "'?' becomes terminal, smuggling back the question shape the "
     "gate rejects outright",
     [('        if ch not in ".!":', '        if ch not in ".!?":')],
     [T_NEW]),
    ("N16", "over", "⛔ the limit cuts rather than refuses — a whole sentence "
     "that does not fit comes back as a slice, which is the defect itself",
     [("        if limit is not None and i + 1 > limit:\n            break",
       "        if limit is not None and i + 1 > limit:\n            return s[:limit]")],
     [T_NEW]),
    ("N17", "under", "the trim returns the FIRST sentence rather than the "
     "longest run of them, throwing away narration the model did finish",
     [("        best = i\n    return s[:best + 1].strip() if best >= 0 else \"\"",
       "        best = i\n        break\n    return s[:best + 1].strip() if best >= 0 else \"\"")],
     [T_NEW]),
    ("N18", "over", "⛔⛔ the `[:140]` slice is back on the vision narration, "
     "cutting mid-word BEFORE the gate that exists to catch mid-word cuts",
     [('                    _vn_text = _narration_last_sentence(_vision_narration_p2, limit=140)',
       '                    _vn_text = (_vision_narration_p2 or "")[:140]')],
     [T_NEW]),
    ("N19", "under", "the phase narrator stops trimming, so a good sentence with "
     "a dangling clause is thrown away for a template instead of repaired",
     [("            text = _narration_last_sentence(text) or text",
       "            text = text")],
     [T_NEW]),
    ("N20", "under", "the per-agent narrator stops trimming",
     [("                        a_text = _narration_last_sentence(a_text) or a_text",
       "                        a_text = a_text")],
     [T_NEW]),
    ("N21", "over", "the trim DISCARDS a line with no sentence instead of "
     "handing it to the gate, so the gate's own reasons never run",
     [("            text = _narration_last_sentence(text) or text",
       "            text = _narration_last_sentence(text)")],
     [T_NEW]),
    ("N22", "under", "a Tier-4 template loses its full stop — and the whole "
     "strict-gate change is only safe because the floor passes its own gate",
     [('        "ChatGPT is reasoning through the brief with its latest thinking model.",',
       '        "ChatGPT is reasoning through the brief with its latest thinking model",')],
     [T_NEW]),
    # ⚠ ANCHORED ON THE SIBLING LINE: the template string occurs TWICE (the SKIP
    # escape hatch and the quality-gate rejection both fall back to it), so the
    # bare string would measure whichever came first rather than the one under
    # test. The rejection arm is the one the strict gate feeds.
    ("N23", "under", "the deterministic phase template loses its full stop, so "
     "the last line standing fails the gate and the card goes silent",
     [('            if text and not _is_acceptable_narration(text):\n'
       '                text = f"Super Research is in {_phase_short_label(phase)}."',
       '            if text and not _is_acceptable_narration(text):\n'
       '                text = f"Super Research is in {_phase_short_label(phase)}"')],
     [T_NEW]),
]

_TEST_TIMEOUT_S = 180


def green(tests: list[str]) -> tuple[bool, bool]:
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


def snapshot() -> dict[str, str]:
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before: dict[str, str]) -> list[str]:
    return [f for f, text in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != text]


def main() -> int:
    before = snapshot()

    print("baseline… ", end="", flush=True)
    ok, timed_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if timed_out else 'RED'}. "
              f"Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, direction, why, edits, tests in MUTANTS:
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor — mutates nothing: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:60]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, timed_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed, fix it)" if timed_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif timed_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}")
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in "
              "your source:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (harness faults — these measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
