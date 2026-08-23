"""Mutation harness for wave 7 — one verdict contract for every verifier.

⛔ WHAT THIS IS FOR. A vision verdict recovered by sniffing prose has cost this
file four separate incidents. The answer was a stated-conclusion contract:
anchored to the start of a line, horizontal whitespace only, LAST match wins.
It was applied to one verifier, and the diagnose mission kept an unanchored
first-match search — while its own prompt says the LAST line carries the answer
and prints all four legal values above it.

⭐⭐ THE SHARPEST MUTANTS HERE:
  A1 — the anchor goes. An instruction echoed mid-sentence becomes the verdict,
       which is #753 restored in the reader that fixed it.
  L1 — first match wins again. The prompts PRINT the menu above the answer, so
       the first match in a quoting reply is the first menu item.
  W1 — horizontal whitespace becomes `\\s`, which spans newlines and quietly
       undoes the anchoring written beside it.
  D2 — the loose fallback runs FIRST, so the anchored read can never decide
       anything: every property above is present and unreachable.
  M1 — the one-word cap on the login check is lifted. Nothing fails, and a
       prefix read that was sound only because the model could not write prose
       starts reading reasoning.

    .venv/bin/python .mutants/verdict_contract_0823_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_VERDICT = "tests/test_verdict_contract_0823.py"
# ⛔ The completion verifier reads through the same helper now, so a change to
# the reader must not move a single historical answer in the incident corpus.
T_COMPLETION = "tests/test_cua_verdict_contract_0812.py"
ALL = [T_VERDICT, T_COMPLETION]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ── the reader's three properties ────────────────────────────────────────
    ("A1", "under", "⛔⛔ the line anchor goes — an instruction echoed "
     "mid-sentence becomes the verdict, which is #753 restored inside the "
     "reader that was written to fix it",
     [('        r"^[^\\S\\n]*" + field + r"[^\\S\\n]*[:=][^\\S\\n]*(" + "|".join(values) + r")\\b",',
       '        r"[^\\S\\n]*" + field + r"[^\\S\\n]*[:=][^\\S\\n]*(" + "|".join(values) + r")\\b",')],
     [T_VERDICT, T_COMPLETION]),
    ("W1", "under", "⛔ horizontal whitespace becomes `\\s`, which spans "
     "newlines and undoes the anchoring written beside it",
     [('        r"^[^\\S\\n]*" + field + r"[^\\S\\n]*[:=][^\\S\\n]*(" + "|".join(values) + r")\\b",',
       '        r"^\\s*" + field + r"\\s*[:=]\\s*(" + "|".join(values) + r")\\b",')],
     [T_VERDICT]),
    ("A2", "under", "the multiline flag goes, so `^` means start of STRING and "
     "only a reply whose very first characters are the verdict is ever read",
     [("        re.I | re.M)\n\n\ndef _last_verdict", "        re.I)\n\n\ndef _last_verdict")],
     [T_VERDICT, T_COMPLETION]),
    ("A3", "under", "case sensitivity returns — the prompt states its values in "
     "capitals, so the reader and the contract agree only by accident",
     [("        re.I | re.M)\n\n\ndef _last_verdict", "        re.M)\n\n\ndef _last_verdict")],
     [T_VERDICT]),
    ("A4", "under", "the word boundary goes, so `doneish` reads as `done`",
     [('r")\\b",', 'r")",')],
     [T_VERDICT]),
    ("L1", "under", "⛔⛔ FIRST match wins again — the prompts print the whole "
     "menu of legal values above the answer, so a reply that quotes its "
     "instructions is read as the first item on that menu",
     [("    return hits[-1].lower() if hits else \"\"", "    return hits[0].lower() if hits else \"\"")],
     [T_VERDICT, T_COMPLETION]),
    ("L2", "under", "the reader stops lower-casing, so every caller's `==` "
     "comparison against a lower-case value silently fails",
     [("    return hits[-1].lower() if hits else \"\"", "    return hits[-1] if hits else \"\"")],
     [T_VERDICT]),
    ("L3", "under", "an empty answer raises instead of answering — this runs "
     "inside a poll loop whose whole job is to keep answering",
     [('    hits = pattern.findall(text or "")', "    hits = pattern.findall(text)")],
     [T_VERDICT]),

    # ── the vocabulary ───────────────────────────────────────────────────────
    ("V1", "under", "⛔ `needs_click` drops out of the diagnose vocabulary — the "
     "verdict the 90-minute Gemini loss turned on collapses into "
     "none-of-the-above, which the caller reads as keep-waiting",
     [('    "conclusion", "generating", "done", "needs_click", "error")',
       '    "conclusion", "generating", "done", "error")')],
     [T_VERDICT]),
    ("V2", "under", "the diagnose reader borrows the COMPLETION vocabulary, so "
     "it can see none of the four values its own prompt mandates",
     [('    "conclusion", "generating", "done", "needs_click", "error")',
       '    "conclusion", "complete", "generating", "unknown")')],
     [T_VERDICT]),
    ("V3", "under", "the diagnose reader looks for the completion keyword, so "
     "the stated conclusion is invisible and the prose fallback carries every "
     "decision",
     [('_CUA_CONCLUSION_LINE = _verdict_line_re(\n    "conclusion",',
       '_CUA_CONCLUSION_LINE = _verdict_line_re(\n    "verdict",')],
     [T_VERDICT]),
    ("V4", "under", "the stop-button field loses its alternate spellings, so a "
     "model writing `stop button:` is not heard and the polarity rule that "
     "makes bounding the confirm loop safe goes quiet",
     [('_CUA_STOP_LINE = _verdict_line_re("stop[_ -]?button", "yes", "no", "unsure")',
       '_CUA_STOP_LINE = _verdict_line_re("stop_button", "yes", "no", "unsure")')],
     [T_VERDICT]),

    # ── the diagnose call site ───────────────────────────────────────────────
    ("D1", "under", "⛔⛔ the diagnose verdict goes back to the unanchored "
     "first-match search — the defect this whole fix is about",
     [("            verdict = _last_verdict(diag_text, _CUA_CONCLUSION_LINE)\n"
       "            if not verdict:\n"
       "                _loose = re.search(", "            if True:\n"
       "                _loose = re.search(")],
     [T_VERDICT]),
    ("D2", "under", "⛔⛔ the loose fallback runs FIRST, so the anchored reader "
     "is present, correct and unable to decide anything",
     [("            verdict = _last_verdict(diag_text, _CUA_CONCLUSION_LINE)\n"
       "            if not verdict:\n"
       "                _loose = re.search(\n"
       "                    r'conclusion\\s*:\\s*(generating|done|needs_click|error)',\n"
       "                    diag_text,\n"
       "                )\n"
       "                verdict = _loose.group(1) if _loose else \"\"",
       "            _loose = re.search(\n"
       "                r'conclusion\\s*:\\s*(generating|done|needs_click|error)',\n"
       "                diag_text,\n"
       "            )\n"
       "            verdict = (_loose.group(1) if _loose else\n"
       "                       _last_verdict(diag_text, _CUA_CONCLUSION_LINE))")],
     [T_VERDICT]),
    ("D3", "over", "the fallback is deleted outright, so an answer that splits "
     "`CONCLUSION:` from its value across two lines stops resolving at all",
     [("            if not verdict:\n"
       "                _loose = re.search(\n"
       "                    r'conclusion\\s*:\\s*(generating|done|needs_click|error)',\n"
       "                    diag_text,\n"
       "                )\n"
       "                verdict = _loose.group(1) if _loose else \"\"\n", "")],
     [T_VERDICT]),

    # ── the completion verifier still reads the same way ─────────────────────
    ("C1", "under", "the completion verifier stops taking the LAST verdict, so "
     "a model that reasons aloud is read at its first thought",
     [("    verdict = _last_verdict(t, _CUA_VERDICT_LINE)",
       "    verdict = (_CUA_VERDICT_LINE.findall(t) or [\"\"])[0].lower()")],
     [T_COMPLETION]),
    ("C2", "under", "the stop-button field is read at its FIRST statement, so a "
     "model that corrects itself is heard saying the opposite",
     [("    stop = _last_verdict(t, _CUA_STOP_LINE)",
       "    stop = (_CUA_STOP_LINE.findall(t) or [\"\"])[0].lower()")],
     [T_COMPLETION]),

    # ── the two verifiers that are safe by construction ──────────────────────
    ("M1", "under", "⛔⛔ the one-word cap on the LOGIN check is lifted — nothing "
     "fails, and a prefix read that was sound only because the model could not "
     "write prose starts reading reasoning",
     [("            max_tokens=8,\n            # Thinking MUST be explicit. On the 5-series models an omitted",
       "            max_tokens=1024,\n            # Thinking MUST be explicit. On the 5-series models an omitted")],
     [T_VERDICT]),
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
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            if not tests:
                raise ValueError("no tests declared")
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:70]}")
                mutated = mutated.replace(frm, to, 1)
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
