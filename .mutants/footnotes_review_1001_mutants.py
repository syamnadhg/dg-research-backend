"""Mutation harness for the Wave 14 footnotes review repairs (2026-10-01).

Each mutant takes back one piece of a repair, and `tests/test_footnotes_1001.py`
must go red for every one:

  N  Claude's numbers are linked only when they match its own list one for one,
     never inside a link's words, never after a space, read off the text as
     written; a link never opens on an escaped bracket.
  K  the brief's chip rule: a chip ends its line, and a list item's own "1." or
     an abbreviation is not the end of a sentence; a brief ending with its own
     sources section is left as it is.

Four mutants moved here from `footnotes_1001_mutants.py` because the repair
rewrote their lines: C5 is N4, C9 is N5, B5 is K8, B8 is K7.

Safety, as the other harnesses here: refuses to start on a dirty tree, holds the
original in memory, restores in `finally`, re-checks `git status` at the end.

    .venv/bin/python .mutants/footnotes_review_1001_mutants.py
    ONLY=N1,K2 .venv/bin/python .mutants/footnotes_review_1001_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = ["tests/test_footnotes_1001.py"]

MUTANTS = [
    # ── N: Claude's own numbers ─────────────────────────────────────────────
    ("N1", "numbers that do not match the list one for one are linked anyway",
     [("    if cited != written:\n", "    if False:\n")]),
    ("N2", "a row nobody cites is not checked (only: every number has a row)",
     [("    if cited != written:\n", "    if not cited <= written:\n")]),
    ("N3", "a number past the end of the list is not checked (only: every row is cited)",
     [("    if cited != written:\n", "    if not written <= cited:\n")]),
    ("N4", "a number inside a link's words is linked (a link inside a link)",
     [('    text = _BRIEF_LINK_RE.sub(lambda m: " " * len(m.group(0)), masked[:own_at])\n',
       "    text = masked[:own_at]\n")]),
    ("N5", "numbers inside the list's own rows are linked too",
     [('    text = _BRIEF_LINK_RE.sub(lambda m: " " * len(m.group(0)), masked[:own_at])\n',
       '    text = _BRIEF_LINK_RE.sub(lambda m: " " * len(m.group(0)), masked)\n')]),
    ("N6", "a bracketed number after a space is linked (\"Step [1]\")",
     [("               if not (m.start() and md[m.start() - 1].isspace())]\n",
       "               if True]\n")]),
    ("N7", "the space is read off the masked text (a number after inline code or a link drops)",
     [("               if not (m.start() and md[m.start() - 1].isspace())]\n",
       "               if not (m.start() and text[m.start() - 1].isspace())]\n")]),
    ("N8", "a link may open on an escaped bracket",
     [(r"    r'(?<![!\\])\[(?P<t>", r"    r'(?<!!)\[(?P<t>")]),

    # ── K: the brief's chips ────────────────────────────────────────────────
    ("K1", "a chip need not end its line (a link with words after it loses them)",
     [("            if (_brief_ends_its_line(md, m.end(), link_spans)\n",
       "            if (True\n")]),
    ("K2", "words between two links do not stop the first being a chip",
     [("        if md[at:start].strip():\n            return False\n",
       "        if False:\n            return False\n")]),
    ("K3", "the rest of the line after the last link is not read",
     [("    return not md[at:line_end].strip()\n", "    return True\n")]),
    ("K4", "a stop that ends no sentence is not checked",
     [("                    and not _BRIEF_NOT_A_STOP_RE.search(before)\n",
       "                    and True\n")]),
    ("K5", "a numbered item's own '1.' counts as the end of a sentence",
     [(r"    r'(?:(?:\A|\n)[ \t]{0,3}\d{1,9}'", r"    r'(?:(?:\A|\n)[ \t]{0,3}\d{1,9}(?!)'")]),
    ("K6", "an abbreviation's stop counts as the end of a sentence",
     [(r"    r'|(?<![A-Za-z.])(?:e\.g|i\.e|", r"    r'|(?!)(?:e\.g|i\.e|")]),
    ("K7", "a brief ending with its own sources section is numbered anyway (was B8)",
     [('        if own_at is not None:\n            log("[Brief] it ends with its own sources section',
       '        if False:\n            log("[Brief] it ends with its own sources section')]),
    ("K8", "no chip folds into its number (was B5)",
     [("            if (_brief_ends_its_line(md, m.end(), link_spans)\n",
       "            if False and (_brief_ends_its_line(md, m.end(), link_spans)\n")]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    return sh([sys.executable, "-m", "pytest", *SUITES, "-q", "-x",
               "-p", "no:cacheprovider"]).returncode == 0


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    path = ROOT / RESEARCH
    original = path.read_text(encoding="utf-8")
    for mid, _why, edits in MUTANTS:
        for frm, _to in edits:
            if original.count(frm) != 1:
                print(f"! ANCHOR {mid} found {original.count(frm)} times: {frm[:70]!r}")
                return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    only = [m for m in os.environ.get("ONLY", "").split(",") if m]
    run = [m for m in MUTANTS if not only or m[0] in only]
    if only and len(run) != len(only):
        print(f"ONLY names {len(only)} mutant(s) and {len(run)} exist")
        return 2
    survivors = []
    try:
        for mid, why, edits in run:
            mutated = original
            for frm, to in edits:
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests()
            print(f"{'killed  ' if killed else 'SURVIVED'} {mid} {why}", flush=True)
            if not killed:
                survivors.append((mid, why))
            path.write_text(original, encoding="utf-8")
    finally:
        path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\nTHE TREE DID NOT COME BACK CLEAN — a mutant may still be in the source:\n"
              + "\n".join(leftover))
        return 3

    print(f"\n{len(run) - len(survivors)}/{len(run)} killed")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} {w}" for m, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
