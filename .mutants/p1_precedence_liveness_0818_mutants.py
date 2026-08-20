"""Mutation harness for "the pass that worked, and what live actually means".

⛔ THE REPORT (owner, 2026-08-18): ChatGPT's P1 stopped opening the sources panel.
"It was working all good before we did the ChatGPT and Claude DOM fix. It used to
work every run but now it's not working."

⭐⭐ IT REGRESSED, AND THE CAUSE WAS A FIX. Before 2026-08-17 PASS 0 gated on a
score threshold that could never be met, so it always fell through to the global
walk — the pass with all 13 recorded successes. Making that gate a predicate was
correct in isolation and handed the decision to a pass with no success record: it
now returns early on a COMPLETED thinking step and the global walk never runs.

⭐⭐ AND THE OWNER NAMED THE DEEPER ONE: the label text is topic-flavoured, so it
cannot be the discriminator — the shimmer must be. Following that: of the five
wording matchers, only ELLIPSIS can have fired on all 13 successes, and "…" is
just the text form of "this step is live". Then the actual shimmer check turned
out to be two static paint arms (`background-clip: text`, equally true of a
stopped gradient) and one animation arm that accepts a paused animation. The
vision tier called the chosen row "gray, not shimmering" while the detector
called it a shimmer.

⭐ THE OVER-CORRECTIONS ARE THE SHARP END HERE, because this repair NARROWS a
signal and REORDERS two passes:
  M2  — the structural pick is deleted rather than demoted, so a page with no
        wording match presses nothing at all.
  M5  — the static clip is dropped from the prefilter too, silently shrinking
        what the pass can even see (it used to ride inside `anim`).
  M7  — the weak tier competes with the strict one instead of backstopping it,
        which is the original false-positive with extra steps.
  M11 — a private copy of `shimmers` reappears beside the shared one, which is
        how the snapshot and the picker would come to describe different rows.
        (Until 2026-08-19 this mutant gave the snapshot a loose copy directly;
        the definitions are now a single spliced constant, so the only way back
        to that divergence is a copy re-growing, and that is what it mutates.)

    python .mutants/p1_precedence_liveness_0818_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_p1_panel_precedence_0818.py"
# ⛔ The reorder's blast radius is pinned in the 08-17 live-DOM file,
# where the fixtures live. A harness that ran only the new file would
# report a clean sweep over the half of the change it never touched.
T_DOM = "tests/test_p1_panel_anchor_0817.py"
ALL = [T_NEW, T_DOM]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 180

# ⭐⭐ 2026-08-19 — RE-ANCHORED ONTO THE SHARED CONSTANT. This used to be the
# PICKER's private copy at eight-space indent. The P1 chip-row wave needed the same
# predicate in a third walker, and rather than let a third copy exist the two were
# extracted into `_CHATGPT_SHIMMER_JS_HELPERS` and spliced into all three sites —
# so this text moved and M4/M6 matched zero times, which the anchor sweep caught
# and the ratchet refused to excuse. The mutants are unchanged in intent; only the
# indentation of their target moved.
STRICT = """    const shimmers = (n) => {
        try {
            const cs = getComputedStyle(n);
            return !!cs.animationName && cs.animationName !== 'none'
                && cs.animationPlayState !== 'paused';
        } catch (e) { return false; }
    };
"""

FALLBACK = """        if (!hits.length && deferredStructural) {"""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    ("M1", "under", "⭐⭐ THE REGRESSION ITSELF — the structural pass clicks and "
     "returns again, so the pass with 13 successes is unreachable",
     [("""                deferredStructural = ranked[0];""",
       """                return clickAndReturn(ranked[0].el, structural.length, 'structural');""")],
     [T_NEW]),
    ("M2", "over", "⛔⛔ the structural pick is deleted instead of demoted — a "
     "page with no wording match now presses nothing at all",
     [(FALLBACK, "        if (false) {")],
     [T_NEW]),
    ("M3", "under", "the fallback fires even when the global walk DID find "
     "something, putting the bad pass back in front",
     [(FALLBACK, "        if (deferredStructural) {")],
     [T_NEW]),
    ("M4", "under", "⭐⭐ THE LIVENESS DEFECT RESTORED — the static gradient clip "
     "is back inside `shimmers`, so a completed gray step reads as shimmering",
     [(STRICT, """    const shimmers = (n) => {
        try {
            const cs = getComputedStyle(n);
            return (cs.animationName && cs.animationName !== 'none')
                || cs.webkitBackgroundClip === 'text'
                || cs.backgroundClip === 'text';
        } catch (e) { return false; }
    };
""")],
     [T_NEW]),
    ("M5", "over", "⛔ the clip arm is dropped from the prefilter as well, so "
     "rows that used to reach the ranking vanish silently",
     [("                if (!inter && !anim && !clip && !named) { DIAG.structNoSignal++; continue; }",
       "                if (!inter && !anim && !named) { DIAG.structNoSignal++; continue; }")],
     [T_NEW]),
    ("M6", "under", "a paused animation counts as running again — a finished "
     "step still has an animation name",
     [(STRICT, STRICT.replace("""&& cs.animationName !== 'none'
                && cs.animationPlayState !== 'paused';""",
                                """&& cs.animationName !== 'none';"""))],
     [T_NEW]),
    ("M7", "over", "⛔ the weak tier stops backstopping and starts competing, "
     "which is the original false positive with extra steps",
     [("""            let ranked = structural.filter(qualifies);
            let weakTier = false;
            if (!ranked.length) {""",
       """            let ranked = structural.filter(h => qualifies(h) || qualifiesWeak(h));
            let weakTier = false;
            if (false) {""")],
     [T_NEW]),
    ("M8", "under", "a dead gradient outscores a running shimmer, so the "
     "completed step wins the ranking it was demoted out of",
     [("+ (clip ? 1 : 0)", "+ (clip ? 9 : 0)")],
     [T_NEW]),
    ("M9", "under", "the press stops saying a static gradient carried it, so "
     "the next miss line cannot answer the question this wave opened",
     [("                + (deferredStructural.weak ? '+staticonly' : '')", "")],
     [T_NEW]),
    ("M10", "under", "the miss snapshot forgets containment and interactivity "
     "again — two of the four terms the picker turns on",
     [("                          clip, inter, inTurn, named };",
       "                          clip };")],
     [T_NEW]),
    # ⭐⭐ M11 REWRITTEN, BECAUSE ITS ORIGINAL PREMISE NO LONGER EXISTS. It used to
    # give the SNAPSHOT a loose private copy while the picker kept the strict one,
    # "so the log describes a row nobody chose". With a single shared definition the
    # two cannot disagree, and inventing an anchor to keep the old mutant alive
    # would have been a fake measurement. What replaces it is the hazard the
    # extraction created: a private copy reappearing NEXT TO the shared one, which
    # is how the divergence would come back.
    ("M11", "over", "⛔ the snapshot re-grows its own private `shimmers`, so the "
     "shared definition stops being the only one and the two can drift again",
     [("""            let anim = shimmers(el);
            let clip = clipped(el);""",
       """            const shimmers = (n) => {
                try {
                    const cs = getComputedStyle(n);
                    return cs.backgroundClip === 'text';
                } catch (e) { return false; }
            };
            let anim = shimmers(el);
            let clip = clipped(el);""")],
     [T_NEW]),
    ("M12", "under", "the dedupe drops a gradient only the inner copy saw, the "
     "same way it once dropped the shimmer",
     [("                prev.clip = prev.clip || clip;", "")],
     [T_NEW]),
    ("M13", "under", "the qualifying gate goes back to being a sum, restoring "
     "the bar that one signal could never clear",
     [("            let ranked = structural.filter(qualifies);",
       "            let ranked = structural.filter(h => h.score >= 3);")],
     [T_NEW]),
    ("M14", "over", "⛔⛔ the global walk sees the whole document again — the "
     "chrome exclusion PASS 0 used to provide is gone and a shimmering banner "
     "above the thread is pressed instead of the strip",
     [('                    if (!inProse && el.closest(\n                            \'form, [data-testid*="composer" i], #prompt-textarea, \'\n                            + \'header, [role="toolbar"], nav\')) inProse = true;', "")],
     [T_DOM]),
    ("M15", "under", "the composer stops being excluded from the global walk, "
     "so its own affordance becomes the strip",
     [('                    if (!inProse && el.closest(\n                            \'form, [data-testid*="composer" i], #prompt-textarea, \'\n                            + \'header, [role="toolbar"], nav\')) inProse = true;',
       """                    if (!inProse && el.closest(
                            'header, [role="toolbar"], nav')) inProse = true;""")],
     [T_DOM]),
]


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
