"""Mutation harness for Wave 14 part 1 (2026-10-01): footnotes in Claude's
document and the brief, and one sources section in ChatGPT's 10-01 document.

Each mutant takes back one piece of the change, or one protection around it —
Claude's numbers linked to their own rows (C), the read-backs that must turn
them back instead of deleting them (R), the brief numbered in the app's copy
only (B), and the "prioritized" qualifier (Q) — and the tests in
`tests/test_footnotes_1001.py` (plus the two files whose pins moved) must go red
for every one.

Safety, as the other harnesses here: refuses to start on a dirty tree, holds the
original in memory, restores in `finally`, re-checks `git status` at the end.

    .venv/bin/python .mutants/footnotes_1001_mutants.py
    ONLY=C1,B3 .venv/bin/python .mutants/footnotes_1001_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = [
    "tests/test_footnotes_1001.py",
    "tests/test_doc_visited_sources_1001.py",
    "tests/test_platform_host_filter_0903.py::test_the_writer_applies_the_filter",
]

MUTANTS = [
    # ── C: Claude's own numbers, linked to its own rows ─────────────────────
    ("C1", "each number opens the NEXT row (shifted by one)",
     [("        url = rows.get(n)\n", "        url = rows.get(n + 1)\n")]),
    ("C2", "the own-numbers step never runs",
     [("        linked = _doc_link_own_numbers(md, label)\n",
       "        linked = md\n")]),
    ("C3", "a list whose written numbers skip or repeat is linked anyway",
     [("    if [int(m.group(1)) for m in items] != list(range(1, len(items) + 1)):",
       "    if False:")]),
    ("C4", "a document already ending with OUR list is linked to our rows",
     [("    if md and not (_DOC_SOURCE_MARK_RE.search(md) or _DOC_VISITED_BLOCK_RE.search(md)):\n"
       "        linked = _doc_link_own_numbers(md, label)",
       "    if md:\n"
       "        linked = _doc_link_own_numbers(md, label)")]),
    # C5 moved to footnotes_review_1001_mutants.py (N4): the review repair
    # rewrote its line.
    ("C6", "numbers inside code are linked",
     [("    masked = _mask_code_spans(md)[0]\n    rows = _doc_own_list_rows(md, masked)",
       "    masked = md\n    rows = _doc_own_list_rows(md, masked)")]),
    ("C7", "a row that is the agent's own chat (or any non-public address) is linked",
     [("        if _doc_is_linkable_url(url):\n            rows[int(m.group(1))] = url",
       "        if url:\n            rows[int(m.group(1))] = url")]),
    ("C8", "a `<url>` row is not read",
     [('        url = (link.group("u") or link.group("a") or "") if link else ""',
       '        url = (link.group("u") or "") if link else ""')]),
    # C9 moved to footnotes_review_1001_mutants.py (N5).

    # ── R: the read-backs ───────────────────────────────────────────────────
    ("R1", "the crash-retry read-back deletes Claude's numbers again",
     [("    unlinked = _doc_own_numbers_unlinked(md)\n    if unlinked is not md:",
       "    unlinked = md\n    if unlinked is not md:")]),
    ("R2", "the read-back turns OUR markers back too, when our list follows the agent's",
     [("            and _strip_numbered_sources_section(md) == md and _doc_own_list_rows(md)):",
       "            and _doc_own_list_rows(md)):")]),
    ("R3", "save_meta sweeps addresses off the linked text (a pair reads as one address)",
     [("            _report_text = _doc_own_numbers_unlinked(content)\n",
       "            _report_text = content\n")]),
    ("R4", "the old strip takes a plain '## Sources' again (Claude's own list)",
     [(r"    r'\n\n(?:%s[ \t]+(?:%s|%s)|##[ \t]+%s)[ \t]*\n\n(?:\d{1,3}\. \[.*\n?)+\Z'",
       r"    r'\n\n(?:%s[ \t]+(?:%s|%s)|##[ \t]+(?:%s|Sources))[ \t]*\n\n(?:\d{1,3}\. \[.*\n?)+\Z'")]),

    # ── B: the brief, numbered in the app's copy only ───────────────────────
    ("B1", "the app's brief is not numbered",
     [('    if doc_type == "brief":\n        content = _brief_numbered_copy(content)',
       '    if False:\n        content = _brief_numbered_copy(content)')]),
    ("B2", "every document the writer saves is numbered as a brief",
     [('    if doc_type == "brief":\n        content = _brief_numbered_copy(content)',
       '    if True:\n        content = _brief_numbered_copy(content)')]),
    ("B3", "a repeat chip gets a new number and a second row",
     [("            if key not in numbers:\n", "            if True:\n")]),
    ("B4", "the '+2' stays in the row's title",
     [("                title = re.sub(r'\\s+', ' ', _BRIEF_CHIP_MORE_RE.sub(\"\", md[m.start(\"t\"):m.end(\"t\")]))",
       "                title = re.sub(r'\\s+', ' ', md[m.start(\"t\"):m.end(\"t\")])")]),
    # B5 moved to footnotes_review_1001_mutants.py (K8).
    ("B6", "a link after a colon is taken for a chip and loses its words",
     [("_BRIEF_CHIP_AFTER_RE = re.compile(r'[.!?][", "_BRIEF_CHIP_AFTER_RE = re.compile(r'[.!?:][")]),
    ("B7", "a link opening the next paragraph is taken for a chip",
     [("_BRIEF_CHIP_GAP_RE = re.compile(r'[ \\t]*\\Z')", "_BRIEF_CHIP_GAP_RE = re.compile(r'\\s*\\Z')")]),
    # B8 moved to footnotes_review_1001_mutants.py (K7).
    ("B9", "a brief already carrying our marker is numbered again",
     [("        if not md or _DOC_SOURCE_MARK_RE.search(md) or _DOC_VISITED_BLOCK_RE.search(md):",
       "        if not md:")]),
    ("B10", "one address linked twice in a sentence gets its number twice",
     [("            if (at, n) in placed:\n                continue\n",
       "            if False:\n                continue\n")]),
    ("B11", "a number may land inside the next link's words",
     [("code + link_spans, m.end(), doc_end)", "code, m.end(), doc_end)")]),

    # ── Q: one sources section for ChatGPT's 10-01 document ─────────────────
    ("Q1", "'prioritized' leaves the qualifiers",
     [("                          r'|further|additional|prioritized|list[ \\t]+of)')",
       "                          r'|further|additional|list[ \\t]+of)')")]),
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
