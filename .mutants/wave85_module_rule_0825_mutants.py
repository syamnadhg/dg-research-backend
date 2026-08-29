"""Mutation harness for Wave 8.5 — the module-boundary rule, written into the repo.

⛔⛔ WHAT THIS PROTECTS IS A PROMISE, NOT A CODE PATH. DGOPS-9506 asked for
`research.py` to be split and was closed will-not-do on 2026-08-05. The thing
that made the refusal defensible was a compensating control: *a new subsystem
goes in a new module*. That control lived in a closed Jira comment and nowhere
else — not the README, not ARCHITECTURE.md, not a test — so nobody working in
this repo could find it and the reviewer who raised the ticket could not check
it was being honoured. M1 restores exactly that state.

⭐ AND THE HARD PART IS THAT A DOC GUARD IS EASY TO WRITE VACUOUSLY. Asserting
`"new module" in text` passes against a section that has rotted to a heading.
The D-series is entirely about that: D1 guts the section to its title, D2 drops
the half of the rule that bounds `research.py`, D3 removes the only pointer that
makes the section reachable, and D5 adds an unexplained module — the one thing
the rule exists to make visible in review.

⚠ THE GROWTH FIGURE IS THE PART THAT EXPIRES, and the two number mutants say so
from both sides. G1 overstates the size, which flatters the argument, and G2
lets it go stale by more than the guard tolerates. An honest counterweight that
has silently stopped being true is worse than no counterweight.

⛔⛔ ANCHORS ARE SINGLE LITERALS, NEVER CONCATENATIONS — the frontend sweep
caught this harness family doing it twice on 2026-08-25.

    python .mutants/wave85_module_rule_0825_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCH = "ARCHITECTURE.md"
README = "README.md"
MUTATED_FILES = [ARCH, README]

T_NEW = "tests/test_module_boundaries_0825.py"
ALL = [T_NEW]

for _t in ALL:
    if not (ROOT / _t).is_file():
        raise SystemExit(f"harness names a test file that does not exist: {_t}")

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

# ── anchors: one literal each ──────────────────────────────────────────
RULE = """> **A new subsystem goes in a new module. Only work that belongs to the existing
> phase-by-phase flow lands in `research.py`.**"""

PROVENANCE = """That is a standing rule, not an aspiration, and it is written here because until
now it existed **only in a closed Jira comment** (DGOPS-9506, closed will-not-do
2026-08-05). A rule nobody reading this repo can find is not a rule."""

TABLE_ROW_SELFHEAL = "| `selfheal.py` | the self-healing selector engine |\n"
TABLE_ROW_LOGQUIET = "| `logquiet.py` | log quieting |\n"

COUNT = "seven subsystems live in their own modules"

# ⛔ RE-ANCHORED 2026-08-28. The row was `| **today (2026-08-25)** | **75,965** |`
# until stretch 6.6B removed 1,302 lines from research.py and the doc had to be
# re-measured — at which point the doc OVERSTATED the file, the one direction
# G1 exists to forbid, and the live-disk anchor ratchet reported both mutants
# stale. A stale anchor measures nothing and reports a kill, so it is re-pointed
# here rather than allowlisted.
TODAY_ROW = "| **today (2026-08-28)** | **74,663** |"

REVISIT = """- A second engineer edits `research.py` regularly. Single-author work has been
  hiding what would otherwise be constant merge pain."""

POINTER = """│                               # ⛔ READ § Module boundaries BEFORE adding a subsystem:
│                               #    a new subsystem goes in a NEW module, not research.py."""

SECTION_HEAD = "## Module boundaries — what may be added to `research.py`"

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the rule itself ══════════════════════════════════════════════
    ("M1", "under", "⛔⛔ THE STATE THE REVIEW FOUND US IN: the rule is nowhere in "
     "the repo again, so the compensating control that made closing DGOPS-9506 "
     "defensible exists only in a closed ticket and no contributor or reviewer "
     "can check it is being honoured",
     [(RULE, "")],
     [T_NEW]),
    ("M2", "under", "⛔⛔ HALF THE RULE GOES — the half that bounds `research.py`. "
     "'A new subsystem goes in a new module' alone reads as advice about new "
     "modules and says nothing about what this file may absorb, which is the "
     "entire point: the file grew 17,000 lines while five new modules appeared",
     [(RULE, "> **A new subsystem goes in a new module.**")],
     [T_NEW]),
    ("M3", "under", "⛔ THE PROVENANCE GOES, so the rule arrives with no ticket, no "
     "date and no decision behind it — and the next person to hit the file's size "
     "re-litigates a question that was already answered with reasons",
     [(PROVENANCE, "That is a standing rule.")],
     [T_NEW]),
    ("M4", "over", "⛔ THE RULE IS SOFTENED TO A PREFERENCE. 'should generally go' "
     "is a rule that has already conceded the argument — and the whole reason it "
     "is written down is that the default, without it, is to add to research.py",
     [(RULE, "> A new subsystem should generally go in its own module where practical.")],
     [T_NEW]),

    # ══ the doc guard, and the ways a doc guard passes vacuously ═════
    ("D1", "under", "⛔⛔ THE SECTION IS GUTTED TO ITS OWN HEADING. Every `in` "
     "assertion over a shrunken section is satisfied by there being nothing left "
     "to contradict it — the failure mode a doc guard is most likely to have",
     [(RULE, ""), (PROVENANCE, ""), (REVISIT, ""),
      (TABLE_ROW_SELFHEAL, ""), (TABLE_ROW_LOGQUIET, "")],
     [T_NEW]),
    ("D2", "under", "⛔ A MODULE VANISHES FROM THE TABLE while its file stays on "
     "disk, so the doc describes six subsystems and the repo has seven — the "
     "drift direction that makes the section quietly wrong rather than obviously "
     "stale",
     [(TABLE_ROW_SELFHEAL, "")],
     [T_NEW]),
    ("D3", "under", "⛔⛔ THE ONLY POINTER GOES. The section is still perfect and "
     "nothing in the repo leads to it — the same shape as the rule living in a "
     "closed ticket, one level up: present, correct, unreachable",
     [(POINTER, "")],
     [T_NEW]),
    ("D4", "over", "⛔ THE POINTER STOPS SAYING THE RULE and becomes a bare "
     "cross-reference. A contributor scanning the layout learns a section exists "
     "but not that it constrains what they are about to do, which is the one "
     "moment the rule has to land",
     [(POINTER, "│                               # See § Module boundaries.")],
     [T_NEW]),
    ("D5", "over", "⛔⛔ AN UNEXPLAINED MODULE. A new root module appears with no "
     "row in the table — exactly the event the rule exists to make visible in "
     "review, and the guard's whole reason for matching on filenames",
     [(COUNT, "eight subsystems live in their own modules")],
     [T_NEW]),
    ("D6", "over", "the count is stated as a word that no longer matches the "
     "table below it, so the prose and the list disagree and a reader has to "
     "guess which one was updated",
     [(COUNT, "five subsystems live in their own modules")],
     [T_NEW]),

    # ══ the honest counterweight, which is the part that expires ═════
    ("G1", "over", "⛔⛔ THE SIZE IS OVERSTATED. The one direction this figure must "
     "never drift: a doc that inflates the problem makes the refusal look braver "
     "than it was, and an inflated number is the kind a reviewer checks",
     [(TODAY_ROW, "| **today (2026-08-28)** | **95,000** |")],
     [T_NEW]),
    ("G2", "under", "⚠ THE FIGURE GOES BADLY STALE — understated by more than the "
     "guard tolerates, so the growth objection reads as answered when it has "
     "simply stopped being measured",
     [(TODAY_ROW, "| **today (2026-08-28)** | **58,800** |")],
     [T_NEW]),
    ("G3", "under", "⛔ THE REVISIT CONDITIONS GO, so a will-not-do becomes "
     "permanent by omission. The second-engineer condition is the one most likely "
     "to come true and the one nobody would think to re-derive",
     [(REVISIT, "")],
     [T_NEW]),
    ("G4", "over", "⛔ THE SECTION IS RENAMED to something a contributor would not "
     "search for. The guard resolves it by title, so a rename with no redirect "
     "makes the rule unfindable while every word of it survives",
     [(SECTION_HEAD, "## Notes on file organisation")],
     [T_NEW]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
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
        print(f"{'TIMED OUT' if timed_out else 'RED'}. Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, direction, why, edits, tests in MUTANTS:
        originals = {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}
        try:
            texts = dict(originals)
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor — mutates nothing: {frm[:60]}")
                where = [f for f in MUTATED_FILES if texts[f].count(frm) == 1]
                total = sum(texts[f].count(frm) for f in MUTATED_FILES)
                if len(where) != 1 or total != 1:
                    raise ValueError(f"anchor occurs {total}x across the docs "
                                     f"(needs exactly 1): {frm[:60]}")
                texts[where[0]] = texts[where[0]].replace(frm, to)
            for f in MUTATED_FILES:
                (ROOT / f).write_text(texts[f], encoding="utf-8")
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
            for f in MUTATED_FILES:
                (ROOT / f).write_text(originals[f], encoding="utf-8")

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
