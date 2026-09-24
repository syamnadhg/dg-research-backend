"""Wave 10.10 leftovers — the run controls end with the test, and no prompt points at a line.

  C* — THE SAFETY-NET FIXTURE. It gives each test fresh asyncio Events on the
      `research._controls` singleton. Through monkeypatch they end with the test;
      by plain assignment the file's last Events stayed bound to a closed loop,
      and whichever test ran next and blocked on one failed. Each Event is put
      back to plain assignment in turn: `test_controls_isolation_1010.py` runs
      the file and then a probe in a child pytest, and must go red.
  P* — THE PROMPT GUARD. The note guard does not read prompt text by design, so
      `PROMPT_DIAGNOSE` kept two dead research.py line numbers. P1 puts one back;
      P2 and P3 break the scan so that it reads docstrings too, or reads nothing.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated Python file must still COMPILE. Both are harness faults, counted OUT.

  .venv/bin/python .mutants/wave1010_leftovers_mutants.py
  .venv/bin/python .mutants/wave1010_leftovers_mutants.py C2 P1
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = "tests/test_pause_resume_safety_net_0902.py"
PROMPTS = "prompts.py"
PROMPT_GUARD = "tests/test_prompts_carry_no_line_pointers_1010.py"
FILES = (FIXTURE, PROMPTS, PROMPT_GUARD)

ISOLATION_SUITE = "tests/test_controls_isolation_1010.py"
PROMPT_SUITE = "tests/test_prompts_carry_no_line_pointers_1010.py"
SUITES = {FIXTURE: ISOLATION_SUITE, PROMPTS: PROMPT_SUITE, PROMPT_GUARD: PROMPT_SUITE}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def _plain(event):
    return [(f'    monkeypatch.setattr(research._controls, "{event}", asyncio.Event())\n',
             f"    research._controls.{event} = asyncio.Event()\n")]


P_TEXT = "older callers parse for those substrings"
P_DOCS = "            and id(n) not in docstrings]"
P_READ = "    return [(n.lineno, n.value) for n in ast.walk(tree)"

MUTANTS = [
    ("C1", FIXTURE, "the stop Event outlives the test, bound to a closed loop",
     _plain("stop_event")),
    ("C2", FIXTURE, "the pause Event outlives the test, bound to a closed loop",
     _plain("pause_event")),
    ("C3", FIXTURE, "the resume Event outlives the test, bound to a closed loop",
     _plain("resume_event")),
    ("P1", PROMPTS, "the diagnose prompt tells the model a research.py line number again",
     [(P_TEXT, "older callers (research.py:6509) parse for those substrings")]),
    ("P2", PROMPT_GUARD, "the prompt scan reads docstrings too, which are the note guard's",
     [(P_DOCS, "            ]")]),
    ("P3", PROMPT_GUARD, "the prompt scan reads nothing, so it passes by looking at nothing",
     [(P_READ, "    return [] and [(n.lineno, n.value) for n in ast.walk(tree)")]),
]


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}

    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    for suite in sorted(set(SUITES.values())):
        if not green(suite):
            print(f"⛔ BASELINE RED ({suite}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
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
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as se:
                    raise AssertionError(f"mutant does not compile: {se}")
            path.write_text(mutated, encoding="utf-8")
            if green(SUITES[fname]):
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED — {why}")
            else:
                print(f"  {mid}  ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (anchor)")
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
