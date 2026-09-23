"""Wave 10.10, lane machine-cards — can the tests see these going back?

  C — the terminal crash card names Chrome when Chrome is what kept closing,
      says how many times, says what to change before Retry, and leaves every
      other kind of failure with today's sentence.

Every mutant reverts ONE decision. The ones that matter most are the quiet ones:

  C1  — the branch is never taken. Nothing else breaks and the card is back to
        "The run kept hitting errors" for a Chrome that closed three times.
  C2  — the branch is taken for EVERY kind, so an ordinary failure sends the
        person off to update a browser that was fine.
  C7/C8 — the copy is computed and the card ignores it: the consumer-ignores-
        the-rule shape, which a test of the words alone cannot see.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED, from the checkout you want
measured — `-m pytest` puts this checkout first on sys.path.

  <venv>/bin/python -u .mutants/wave1010_cards_mutants.py
  <venv>/bin/python -u .mutants/wave1010_cards_mutants.py C1 C2
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_crash_card_chrome_1010.py "
          "tests/test_stop_is_not_a_crash_108.py")
RESEARCH = "research.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the terminal crash card ────────────────────────────────────────
C_BRANCH = '            if _captured_failure_kind == "browser_crash":'
C_COUNT = "                _closes = _crash_retries + 1"
C_TITLE = '                _card_error = ("Chrome kept closing" if _closes > 1'
C_STREAK = ('                     f"computer, so we stopped reopening it. " '
            'if _closes > 1')
C_ADVICE = ('                    + "Quit other Chrome windows there, update Chrome, or "\n'
            '                      "restart that computer, then Retry to start again from "\n'
            '                      "the last checkpoint — or Skip to stop here.")')
C_USE_ERROR = "                error=_card_error,"
C_USE_REASON = "                reason=_card_reason,"

MUTANTS = [
    # ── C: the terminal crash card ─────────────────────────────────────────
    ("C1", "under", "⛔⛔ THE DEFECT, RESTORED — the Chrome branch is never "
     "taken, so a Chrome that closed three times in a row is 'The run kept "
     "hitting errors' again, with a Retry into the same Chrome",
     [(C_BRANCH, "            if False:")]),
    ("C2", "over", "⛔⛔ THE OVER-CORRECTION — every failure is called Chrome, "
     "and somebody whose notebook upload was refused is told to update a "
     "browser that was fine",
     [(C_BRANCH, "            if True:")]),
    ("C3", "under", "⛔ the count forgets the first close, so the card says "
     "Chrome closed twice when it closed three times",
     [(C_COUNT, "                _closes = _crash_retries")]),
    ("C4", "over", "⛔ a single close is called a streak in the title — "
     "'Chrome kept closing' about one death the planner refused to retry",
     [(C_TITLE, '                _card_error = ("Chrome kept closing" if _closes > 0')]),
    ("C5", "over", "⛔ a single close is called a streak in the details — "
     "'Chrome closed 1 times in a row', the sentence this wave removes",
     [(C_STREAK, '                     f"computer, so we stopped reopening it. " '
                 'if _closes > 0')]),
    ("C6", "under", "⛔ the advice goes, so the card names Chrome and offers "
     "the same Retry into the same Chrome — half the point of the card",
     [(C_ADVICE, '                    + "Retry to start again from the last '
                 'checkpoint, or Skip to stop here.")')]),
    ("C7", "under", "⛔⛔ THE CONSUMER IGNORES THE RULE — the title is computed "
     "and the card still shows today's, so every test of the helper-shaped half "
     "would pass while the person reads 'errors'",
     [(C_USE_ERROR, '                error="The run kept hitting errors",')]),
    ("C8", "under", "⛔ the consumer ignores the details — the card says "
     "Chrome in the title and today's generic sentence underneath",
     [(C_USE_REASON, '                reason="We tried to recover a couple of '
                     'times and it didn\'t take. Retry to start again from the '
                     'last checkpoint, or Skip to stop here.",')]),
]


def _path(fname: str) -> Path:
    return ROOT / fname


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 300


def green():
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q",
             "-p", "no:cacheprovider", "-rs"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it.
    return " failed" not in out and " error" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    # Normalised to five columns — the shape the two sweeps in `.mutants/_*.py`
    # read — with the file defaulting to research.py.
    MUTANTS = [(*m, RESEARCH)[:5] for m in MUTANTS]
    files = sorted({m[4] for m in MUTANTS})
    ORIGINALS = {f: _path(f).read_text(encoding="utf-8") for f in files}

    def restore():
        for f, t in ORIGINALS.items():
            _path(f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    if not green():
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    faults = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, why, edits, fname in selected:
        path = ROOT / fname
        original = ORIGINALS[fname]
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as e:
                raise AssertionError(f"mutant does not parse: {e}")
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}", flush=True)
            else:
                print(f"  {mid}  ✓ killed", flush=True)
        except AssertionError as e:
            faults.append(mid)
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}", flush=True)
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if _path(f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed")
    if faults:
        print("⚠ HARNESS FAULT(S) — measured nothing, counted out: " + ", ".join(faults))
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if survivors or faults:
        sys.exit(1)
    print("clean.\n")
