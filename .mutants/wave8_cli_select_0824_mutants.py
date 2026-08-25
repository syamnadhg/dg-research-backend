"""Mutation harness for Wave 8 step I — choosing runs from the terminal.

⛔⛔ WHAT `--runs N` COULD NOT DO. It took a COUNT, and the collector applied it
as "the newest N inside the age window" — so a person reporting one run that hung
on Tuesday either sent thirty or guessed how far back theirs was. There was no
list and no numbers; `_select_bundle_runs` picked for them.

⭐⭐ THE OWNER AT THE MACHINE SEES EVERY RUN ON IT, including the ones attributable
to nobody — which today is all of them, since no shipped build recorded a
submitter. They already hold these files on their own disk, so listing them
grants nothing; withholding them would hide the machine's whole history from the
one person who can act on it. That is the deliberate difference from the app,
where everybody sees only the runs they fired, and P1 restores the wrong one.

⛔ EVERY AMBIGUITY RESOLVES TOWARD LESS. The parser refuses rather than guessing,
on this file's standing rule — "falling back would resolve every malformed
request toward MORE collection than was agreed to". The sharpest mutant here is
R3: accepting `1-3` as a range, which is the obvious kindness and would send run
2 to somebody who typed a dash meaning "1 and 3".

⛔ AND THE PROMPT NEVER DECIDES IN SILENCE. It echoes what it understood and
gives up out loud, which is the same rule `_ask_yes_no_sync` was built under —
after a new owner answered a prompt with a number it never offered and had it
applied as the default without a word.

    python .mutants/wave8_cli_select_0824_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_send_logs_cli_0824.py"
# ⛔ THE SIBLING FILES WHOSE PROPERTIES THIS SOURCE OWNS. The consent helper and
# the builder call are shared with the older CLI suite and the selection suite; a
# harness scoped to its own file has three times in this repo reported "real
# suite gaps" that were nothing but its own blindness.
T_CLI = "tests/test_send_logs_cli_0818.py"
T_CMD = "tests/test_send_logs_command_0818.py"
T_SEL = "tests/test_bundle_selection_0824.py"
ALL = [T_NEW, T_CLI, T_CMD, T_SEL]

for _t in ALL:
    if not (ROOT / _t).is_file():
        raise SystemExit(f"harness names a test file that does not exist: {_t}")

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 300

_EMPTY = """    text = (answer or "").strip().lower()
    if not text:
        return []"""

_ALL = """    if text in ("all", "a", "*"):
        return list(range(count))"""

_DIGIT = """        if not token.isdigit():
            return None"""

_RANGE = """        n = int(token)
        if n < 1 or n > count:
            return None"""

_DEDUPE = """        if (n - 1) not in out:
            out.append(n - 1)"""

_SPLIT = """    for token in re.split(r"[,\\s]+", text):"""

_GIVEUP = """    print(f"  {_c(_WARN, '⚠')}  Could not read a choice. Nothing was sent.")
    return None"""

# ⛔ WIDENED: `for _ in range(3):` appears four times in this file, so the narrow
# anchor mutated a place this mutant was never about and reported a kill.
_RETRY = """    for _ in range(3):
        try:
            answer = input(f"  {_c(_ACCENT, '>')}  Choose ")"""

_ECHO = """            if picked:
                print(f"     {_c(_DIM, f'Sending {len(picked)} run(s).')}")"""

_NO_ROWS = """    if not rows:
        print(f"  {_c(_DIM, 'This machine is holding no run logs.')}")
        return []"""

_ROW_FIELDS = """    started = str(row.get("startedUtc") or "")[:19].replace("T", " ") or "unknown time"
    status = str(row.get("status") or "unknown")
    size_kb = int(row.get("sizeBytes") or 0) // 1024
    return f"{index:>3}. {started}  {status:<14} {size_kb:>6} KB\""""

_QUIT = """        chosen = _choose_runs_interactively(_scan_run_folders())
        if chosen is None:
            return 130
        only_runs = chosen"""

_ORDER = """    only_runs: "list[str] | None" = None
    if select:"""

_CONSENT_CALL = """    for line in _send_logs_consent_lines(
            len(only_runs) if only_runs is not None else n_runs,
            chosen_exactly=only_runs is not None):"""

_BUILDER_CALL = """        summary = _build_log_bundle(dest, support_code=code, max_runs=n_runs,
                                    only_runs=only_runs)"""

_EXACT_COPY = """        first = ("no runs — this machine's own log files only" if n == 0 else
                 f"the {n} run{'' if n == 1 else 's'} you chose, and only those")"""

_WARN_LINE = """        "⚠ only the first line above is what your choice changes — everything "
        "else leaves in full whichever runs you pick"
        if chosen_exactly else"""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the parser: every ambiguity must resolve toward LESS ══════════
    ("R1", "over", "⛔⛔ AN EMPTY ANSWER MEANS EVERYTHING. Pressing Enter — the "
     "thing a person does when they are not sure — sends every run on the "
     "machine instead of none",
     [(_EMPTY, '    text = (answer or "").strip().lower()\n'
               "    if not text:\n        return list(range(count))")],
     [T_NEW]),
    ("R2", "over", "an unreadable answer falls back to everything rather than "
     "being re-asked, which is the exact fallback this file's own docstring "
     "forbids",
     [(_DIGIT, "        if not token.isdigit():\n            return list(range(count))")],
     [T_NEW]),
    ("R3", "over", "⛔⛔ THE OBVIOUS KINDNESS THAT OVER-COLLECTS. `1-3` is accepted "
     "as a range, so somebody who meant \"1 and 3\" and typed a dash silently "
     "sends run 2 as well",
     [(_SPLIT, '    for token in re.split(r"[,\\s-]+", text):')],
     [T_NEW]),
    ("R4", "over", "a number outside the list is clamped instead of refused, so "
     "a typo picks a run nobody named",
     [(_RANGE, "        n = max(1, min(int(token), count))")],
     [T_NEW]),
    ("R5", "under", "`all` stops meaning all, so the one answer that IS an "
     "instruction reads as an unreadable one",
     [(_ALL, "    if False:\n        return list(range(count))")],
     [T_NEW]),
    ("R6", "under", "a repeated number is counted twice, so the count the person "
     "is shown disagrees with what they typed",
     [(_DEDUPE, "        out.append(n - 1)")],
     [T_NEW]),
    ("R7", "over", "an empty answer becomes indistinguishable from an unreadable "
     "one, so the pairing-failure case — no runs, machine logs only — can no "
     "longer be asked for at all",
     [(_EMPTY, '    text = (answer or "").strip().lower()\n'
               "    if not text:\n        return None")],
     [T_NEW]),

    # ══ the prompt: never decide in silence ═══════════════════════════
    ("P1", "under", "⛔⛔ THE LIST IS FILTERED TO ATTRIBUTED RUNS, which is the "
     "app's rule applied where it is wrong. Every run folder in the field is "
     "attributable to nobody, so the owner sees an EMPTY list on their own "
     "machine, holding files they can open in a text editor",
     [("    if not rows:\n        print(f\"  {_c(_DIM, 'This machine is holding no run logs.')}\")",
       '    rows = [r for r in rows if r.get("submitterUid")]\n'
       "    if not rows:\n        print(f\"  {_c(_DIM, 'This machine is holding no run logs.')}\")")],
     [T_NEW]),
    ("P2", "over", "⛔ an unreadable answer is applied as a default nobody chose "
     "— the exact silence that produced this file's one yes/no reader",
     [(_GIVEUP, "    return []")],
     [T_NEW]),
    ("P3", "under", "there is no retry, so one typo abandons the send",
     [(_RETRY, "    for _ in range(1):\n"
               "        try:\n"
               "            answer = input(f\"  {_c(_ACCENT, '>')}  Choose \")")],
     [T_NEW]),
    ("P4", "under", "the prompt stops echoing what it understood, so a person "
     "who typed something ambiguous never learns how it was read",
     [(_ECHO, "            if False:\n"
              "                print(f\"     {_c(_DIM, f'Sending {len(picked)} run(s).')}\")")],
     [T_NEW]),
    ("P5", "over", "a machine with no runs prompts anyway, asking somebody to "
     "choose from an empty list",
     [(_NO_ROWS, "    if False:\n        print(\"\")\n        return []")],
     [T_NEW]),
    ("P6", "over", "⛔⛔ THE TOPIC REACHES THE TERMINAL LIST. There is nowhere to "
     "read one from — a run folder carries no topic and no title by design — so "
     "this can only come from parsing run.log, which is a parser over "
     "user-controlled text feeding a disclosure decision",
     [(_ROW_FIELDS, '    started = str(row.get("startedUtc") or "")[:19].replace("T", " ") or "unknown time"\n'
                    '    status = str(row.get("status") or "unknown")\n'
                    '    size_kb = int(row.get("sizeBytes") or 0) // 1024\n'
                    '    topic = str(row.get("topic") or "")\n'
                    '    return f"{index:>3}. {started}  {status:<14} {size_kb:>6} KB  {topic}"')],
     [T_NEW]),

    # ══ the command: what the choice actually does ════════════════════
    ("C1", "over", "⛔⛔ QUITTING THE PROMPT STILL SENDS. A person who pressed "
     "Ctrl-C gets a bundle built from a default they never picked",
     [(_QUIT, "        chosen = _choose_runs_interactively(_scan_run_folders())\n"
              "        only_runs = chosen or []")],
     [T_NEW]),
    ("C2", "under", "the selection never reaches the builder, so the flag is "
     "accepted and ignored — and every stub in the suite takes `**k`, so nothing "
     "else would notice",
     [(_BUILDER_CALL,
       "        summary = _build_log_bundle(dest, support_code=code, max_runs=n_runs)")],
     [T_NEW, T_CLI]),
    ("C3", "under", "the disclosure is printed BEFORE the choice, so the screen "
     "names a number the person has not chosen yet and then builds a different "
     "bundle",
     [(_ORDER, '    only_runs: "list[str] | None" = None\n'
               "    if False:")],
     [T_NEW]),

    # ══ the copy the choice produces ══════════════════════════════════
    ("K1", "over", "⛔⛔ A SELECTION IS DESCRIBED AS A CEILING — \"at most 2\" for a "
     "request the person made precisely, which understates what they asked for "
     "and re-introduces the ambiguity the list removed",
     [(_CONSENT_CALL, "    for line in _send_logs_consent_lines(\n"
                      "            len(only_runs) if only_runs is not None else n_runs):")],
     [T_NEW, T_CLI]),
    ("K2", "over", "choosing NOTHING reads as choosing everything: the first line "
     "renders a bare count where a reader completes it as \"no limit\"",
     [(_EXACT_COPY,
       '        first = f"the {n} run{\'\' if n == 1 else \'s\'} you chose, and only those"')],
     [T_NEW]),
    ("K3", "under", "⛔ the honesty line goes for a selection, so ticking two runs "
     "reads as \"only those two things leave\" — while the sessions and the raw "
     "tails ship in full whichever runs were picked",
     [(_WARN_LINE, '        ""\n        if chosen_exactly else')],
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
