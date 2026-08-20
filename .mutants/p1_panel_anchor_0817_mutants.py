"""Mutation harness for "the structural anchor that one signal could never clear".

⛔ THE REPORT (owner, 2026-08-16 and again 2026-08-17): ChatGPT's P1 never opened
the sources panel, so the activity panel streamed nothing for eleven minutes.

⭐⭐ THE STRIP WAS ON THE PAGE and the step's own snapshot logged it — twice, in
two different runs. PASS 0 scored candidates `inter*3 + anim*3 + wordy*2 -
(top-lub)/1000` and required `>= 3`: three is exactly the weight of ONE signal,
and the distance penalty is always subtracted, so a one-signal candidate can
never qualify. The captured strips scored 2.960 and 2.896. The only PASS 0 that
has ever fired did so because its text read "Searching the web" (+2 wordy) — a
wording-free anchor decided by wording.

⭐ THE OVER-CORRECTIONS ARE THE SHARP END, because the repair LOOSENS a gate:
  P2  — everything qualifies; PASS 0 presses whatever is nearest the message.
  P5  — a lone shimmer qualifies anywhere, and the composer's model chip has an
        animated descendant 400px below the strip (measured, same capture).
  P6  — any clickable row qualifies, which is half the thread.
  P9  — the named-row selector loosens to "has a test id", which every
        conversation turn does.
  P11 — the composer subtree stops being excluded.
  P13 — the band widens to the whole page.

    python .mutants/p1_panel_anchor_0817_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_p1_panel_anchor_0817.py"
ALL = [T_NEW]

PY = str(ROOT / ".venv" / "bin" / "python")

# 2026-08-20: the pair `animSelf && clipSelf` gained an arm — the 08-18 split had
# never recombined the two halves of the shimmer on the same element, which is
# what left the live P1 row unqualified for twelve minutes.
QUALIFIES = """            const qualifies = (h) => h.named           // ChatGPT's own name for it
                || (h.animSelf && h.clipSelf)          // a live shimmering text row
                || (h.anim && h.inTurn)                // the shimmer, contained
                || (h.inter && h.anim)                 // the original two-signal rule
                || (h.inter && h.wordy);               // clickable AND a known state
"""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    ("P1", "under", "⭐⭐ THE ORIGINAL DEFECT — the sum is the gate again, and the "
     "bar equals one signal minus a penalty that is always subtracted",
     [("            let ranked = structural.filter(qualifies);",
       "            let ranked = structural.filter(h => h.score >= 3);")],
     [T_NEW]),
    ("P2", "over", "⛔⛔ everything qualifies — PASS 0 presses whatever sits "
     "nearest the last user message",
     [(QUALIFIES, "            const qualifies = (h) => true;\n")],
     [T_NEW]),
    ("P3", "under", "ChatGPT's own name for the row stops counting, so the "
     "capture whose shimmer was not measurable is refused again",
     [("            const qualifies = (h) => h.named           // ChatGPT's own name for it",
       "            const qualifies = (h) => false")],
     [T_NEW]),
    ("P4", "under", "the contained shimmer stops counting — the anchor is back "
     "to needing a second signal it does not have",
     [("                || (h.anim && h.inTurn)                // the shimmer, contained",
       "                || false")],
     [T_NEW]),
    ("P5", "over", "⛔⛔ a lone shimmer qualifies anywhere on the page, and the "
     "composer's model chip has an animated descendant",
     [("                || (h.anim && h.inTurn)                // the shimmer, contained",
       "                || h.anim")],
     [T_NEW]),
    ("P6", "over", "⛔ any clickable row near the message qualifies — that is "
     "every button in the turn's own toolbar",
     [("                || (h.inter && h.wordy);               // clickable AND a known state",
       "                || h.inter;")],
     [T_NEW]),
    ("P7", "under", "the one PASS 0 shape that has ever fired in the corpus "
     "stops firing",
     [("                || (h.inter && h.wordy);               // clickable AND a known state",
       "                || false;")],
     [T_NEW]),
    ("P8", "under", "the shimmer is read off the element and its parent only — "
     "measured `anim:false` there and `animKid:true` in the subtree",
     [("""                if (!anim) {
                    try {
                        let seen = 0;
                        for (const kid of el.querySelectorAll('*')) {
                            if (++seen > 12) break;
                            if (shimmers(kid)) { anim = true; break; }
                        }
                    } catch (e) {}
                }""",
       "                if (!anim) { /* subtree not consulted */ }")],
     [T_NEW]),
    ("P9", "over", "⛔ the named-row selector loosens to 'carries a test id', "
     "which every conversation turn does",
     [("""                    named = !!el.closest('[data-testid^="cot-v"][data-testid*="pinned-row"]');""",
       """                    named = !!el.closest('[data-testid]');""")],
     [T_NEW]),
    ("P10", "under", "the qualifiers are no longer filtered before ranking, so "
     "an unqualified higher scorer buries the strip beneath it",
     [("            let ranked = structural.filter(qualifies);",
       "            let ranked = structural.slice();")],
     [T_NEW]),
    ("P11", "over", "⛔ the composer subtree stops being excluded — its own "
     "shimmering affordance becomes the strip",
     [("""                if (el.closest && el.closest(
                        'form, [data-testid*="composer" i], #prompt-textarea, ' +
                        'header, [role="toolbar"], nav')) { DIAG.structProse++; continue; }""",
       "                if (false) { DIAG.structProse++; continue; }")],
     [T_NEW]),
    ("P12", "under", "⛔ the caller's escape hatch is ignored: after two "
     "unverified presses PASS 0 must stand down so the wording passes and the "
     "frame walk get their turn",
     [("        if (!skipStructural && lub > 0) {", "        if (lub > 0) {")],
     [T_NEW]),
    ("P13", "over", "the band widens to the whole page, so a strip from an "
     "earlier turn — or anything else — is 'below the last user message'",
     [("                if (offTop < -8 || offTop > 600) { DIAG.structOffBand++; continue; }",
       "                if (offTop < -8 || offTop > 5000) { DIAG.structOffBand++; continue; }")],
     [T_NEW]),
    ("P14", "under", "the band narrows below the measured distance — the strip "
     "sat 104px under the bubble",
     [("                if (offTop < -8 || offTop > 600) { DIAG.structOffBand++; continue; }",
       "                if (offTop < -8 || offTop > 60) { DIAG.structOffBand++; continue; }")],
     [T_NEW]),
    ("P15", "under", "the pick stops saying WHICH signal carried it, which is "
     "exactly what no previous miss line could answer",
     [("            picked.why = (deferredStructural.named ? 'named' : '')",
       "            picked.why = ''; const _dead = (")],
     [T_NEW]),
    ("P16", "over", "the nearest-wins ranking is dropped, so the strip from a "
     "previous turn can outrank the live one",
     [("""                ranked.sort((a, b) => (Number(!!b.named) - Number(!!a.named))
                                      || (b.score - a.score) || (a.len - b.len));""",
       """                ranked.sort((a, b) => (Number(!!b.named) - Number(!!a.named))
                                      || (a.len - b.len));""")],
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
