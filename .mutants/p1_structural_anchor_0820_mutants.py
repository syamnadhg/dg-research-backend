"""Mutation harness for "the two halves of the shimmer were never recombined".

⛔ THE REPORT (owner, watching a live run): ChatGPT's shimmering P1 line "is only
clickable at times — like when it says stuff like 'Searched n websites'".

⛔ AND MY FIRST DIAGNOSIS WAS WRONG. I read the misses and built a fix on the
theory that `lub` (the last user message's bottom, in VIEWPORT coordinates) had
gone negative as the page scrolled, switching the structural pass off. The
panel-miss snapshot says `"lub": 202`, in both captures twelve minutes apart. The
brief never moved. Reverted; the band is untouched and pinned that way.

⭐⭐ THE ACTUAL CAUSE. The snapshot's `anim`/`clip` are SELF-only readings:
  the live line   anim=TRUE  clip=TRUE  animKid=true  inter/inTurn/named=false
  the model chip  anim=false clip=false animKid=TRUE
Every arm of the qualifier was false for the row. The 08-18 split — a subtree
shimmer must not decide, a static gradient must not decide — was right, and it
never recombined the pair ON THE SAME ELEMENT, which is the one thing on that
page that is both.

⭐ THE OVER-CORRECTIONS ARE MOST OF THE RISK, because "find the row more often"
has a bad failure mode of its own:
  N3 — a lone running animation qualifies ⇒ the composer's model chip is pressed.
  N4 — a lone gradient qualifies ⇒ a finished thinking step reads as live.
  N5 — the prose exclusion dropped ⇒ the markdown-table disease returns.
  N9 — the verb list widened instead, the arms race this file lost five times.

    .venv/bin/python .mutants/p1_structural_anchor_0820_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_p1_structural_anchor_0820.py"
# ⛔ THE SIBLING SUITES THAT OWN PARTS OF THIS SAME PASS. Reporting "real suite
# gaps" that are nothing but the harness's own scope has happened repeatedly here.
T_ANCHOR = "tests/test_p1_panel_anchor_0817.py"
T_PREC = "tests/test_p1_panel_precedence_0818.py"
T_CHIPS = "tests/test_p1_inline_chips_0819.py"
T_SHAPES = "tests/test_913_chatgpt_panel_shapes.py"
ALL = [T_NEW, T_ANCHOR, T_PREC, T_CHIPS, T_SHAPES]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

_ARM = """            const qualifies = (h) => h.named           // ChatGPT's own name for it
                || (h.animSelf && h.clipSelf)          // a live shimmering text row"""
_SELF = "                const animSelf = shimmers(el);\n                const clipSelf = clipped(el);"
_PROSE = ("                if (el.closest && el.closest(\n"
          "                        'table, td, th, code, pre, a[href], '\n"
          "                        + '.markdown, [class*=\"markdown\"], [class*=\"prose\"]')) {\n"
          "                    DIAG.structProse++; continue;\n"
          "                }")

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the bug itself ══════════════════════════════════════════════════════
    ("N1", "under", "⭐⭐ THE ORIGINAL BUG — the pair loses its arm, so the one "
     "row on the page carrying both a running animation and gradient-clipped "
     "text of its own goes unqualified, exactly as it did for twelve minutes",
     [(_ARM, """            const qualifies = (h) => h.named           // ChatGPT's own name for it""")],
     [T_NEW]),
    ("N2", "under", "the self-only readings are taken from the BROADENED probes, "
     "so a shimmer anywhere in the subtree counts — which is what makes the "
     "composer's model chip indistinguishable from the strip",
     [(_SELF, "                const animSelf = shimmers(el) || shimmers(el.parentElement || el);\n"
              "                const clipSelf = clipped(el) || clipped(el.parentElement || el);")],
     [T_NEW]),
    ("N3", "over", "⛔ a lone running animation qualifies, so the composer's "
     "model chip — animated child, nothing of its own — becomes the click target",
     [(_ARM, _ARM.replace("(h.animSelf && h.clipSelf)", "h.animSelf                 "))],
     [T_NEW]),
    ("N4", "over", "⛔ a lone gradient qualifies, so a FINISHED thinking step "
     "(still clipped, no longer moving) reads as the live line — the exact false "
     "positive the 08-18 split was made to remove",
     [(_ARM, _ARM.replace("(h.animSelf && h.clipSelf)", "h.clipSelf                 "))],
     [T_NEW]),
    ("N5", "over", "⛔⛔ the prose exclusion is dropped from this pass. It only "
     "ever lived in the WORDING walk, and a new qualifying arm here needs it — "
     "twelve presses in one phase once landed in a markdown table",
     [(_PROSE, "                if (false) {\n                    DIAG.structProse++; continue;\n                }")],
     [T_NEW]),
    ("N6", "over", "the composer and page-chrome exclusion goes, so a shimmering "
     "\"Searching for updates...\" banner is pressed instead of the strip",
     [("                        'header, [role=\"toolbar\"], nav')) { DIAG.structProse++; continue; }",
       "                        'header, [role=\"toolbar\"], nav')) { DIAG.structProse++; }")],
     [T_NEW, T_ANCHOR]),
    ("N7b", "over", "⛔ naming stops being a TIER and goes back to being four "
     "points — which ties exactly with anim(3)+clip(1), so a shimmering stranger "
     "outranks the row ChatGPT itself names, decided by pixels",
     [("                ranked.sort((a, b) => (Number(!!b.named) - Number(!!a.named))\n"
       "                                      || (b.score - a.score) || (a.len - b.len));",
       "                ranked.sort((a, b) => (b.score - a.score) || (a.len - b.len));")],
     [T_NEW]),
    # ⛔ N7 ("named loses its four score points") WAS REMOVED as an EQUIVALENT
    # mutant. Once naming became a tier in the sort, that term could not change
    # any outcome — so the mutant measured nothing and survived by construction,
    # which is a harness bug, not a suite gap. The term is gone from the source
    # too; N7b below covers the ordering that actually decides.
    ("N7c", "under", "the `named` ARM is dropped from the qualifier, so a row "
     "ChatGPT names but that carries no shimmer of its own stops qualifying at "
     "all — the 08-17 capture's shape",
     [("            const qualifies = (h) => h.named           // ChatGPT's own name for it\n",
       "            const qualifies = (h) => false             // ChatGPT's own name for it\n")],
     [T_NEW, T_ANCHOR]),
    ("N8", "over", "the signal prefilter goes, so any short row near the top of "
     "the conversation qualifies — the bar the 08-17 note refused to lower",
     [("                if (!inter && !anim && !clip && !named) { DIAG.structNoSignal++; continue; }",
       "                if (false) { DIAG.structNoSignal++; continue; }")],
     [T_NEW, T_ANCHOR, T_PREC]),
    ("N9", "over", "⛔ THE ARMS RACE — the verb anchor is widened with the "
     "past-tense labels instead of fixing the pass. Five prior commits did this "
     "\"with no end in sight\"",
     [("        const VERB_ONLY = /^(thinking|reasoning|searching|looking|browsing|"
       "investigating|analyzing|reading|exploring|checking|visiting|researching)\\\\b/i;",
       "        const VERB_ONLY = /^(thinking|reasoning|searching|looking|browsing|"
       "investigating|analyzing|reading|exploring|checking|visiting|researching|"
       "mapped|designed|compared|scoped|structured|developed)\\\\b/i;")],
     [T_NEW]),

    # ══ the census — without it the next run says nothing again ═════════════
    ("C1", "under", "the miss line stops carrying the census, so twenty-three "
     "identical lines can once again mean three different pages",
     [("                + _chatgpt_structural_census(res))", "                )")],
     [T_NEW]),
    ("C2", "under", "a pass that never ran reports the same way as one that ran "
     "and found nothing",
     [('    if not res.get("structRan"):\n'
       '        return " · structural pass DID NOT RUN (no turn and no on-screen user message)"',
       '    if not res.get("structRan"):\n        return ""')],
     [T_NEW]),
    ("C3", "under", "the pass stops recording that it ran at all",
     [("            DIAG.structRan = true;", "            DIAG.structRan = false;")],
     [T_NEW]),
    ("C4", "under", "the in-band count is never incremented, so \"rows reached "
     "the band and every one failed the signal test\" cannot be said — which is "
     "the sentence that would have diagnosed this in one tick",
     [("                DIAG.structInBand++;", "")],
     [T_NEW]),
    ("C5", "under", "the census never crosses back from the page into Python",
     [("            structRan: DIAG.structRan, structAnchor: DIAG.structAnchor,",
       "            structRan: false, structAnchor: '',")],
     [T_NEW]),
    ("C6", "over", "every counter prints whether or not it fired, which is wave "
     "2's log-flood lesson re-learned on a per-tick DEBUG line",
     [('        n = int(res.get(key) or 0)\n        if n:\n            bits.append(f"{name}={n}")',
       '        n = int(res.get(key) or 0)\n        bits.append(f"{name}={n}")')],
     [T_NEW]),
]


def green(tests):
    try:
        # ⛔⛔ MEASURED 2026-08-18: a stale `__pycache__/*.pyc` served OLD bytecode
        # for a file that had already been fixed, and the measurement disagreed
        # with the source for three rounds.
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def skipped(tests) -> int:
    """Every executed-JS test here needs node. A run where node is missing would
    report a clean sweep having measured nothing."""
    try:
        out = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                              *tests], cwd=ROOT, capture_output=True, text=True,
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                             timeout=_TEST_TIMEOUT_S).stdout
    except subprocess.TimeoutExpired:
        return 0
    for line in out.splitlines():
        if "skipped" in line:
            for part in line.replace("=", " ").split(","):
                if "skipped" in part:
                    for tok in part.split():
                        if tok.isdigit():
                            return int(tok)
    return 0


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
    n_skip = skipped([T_NEW])
    print(f"green ({n_skip} skipped)", flush=True)
    if n_skip:
        print(f"⚠ {n_skip} test(s) SKIPPED — without node every executed-JS mutant "
              "below measures NOTHING. Fix that before reading the report.")

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
