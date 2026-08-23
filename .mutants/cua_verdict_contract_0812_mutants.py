"""Mutation harness for the CUA verdict contract.

The fix replaces "sniff the model's reasoning for keywords" with "read the
model's stated conclusion". Two failure directions, both weighted:

  UNDER — the contract is not read, or the prose parser is consulted first
  anyway, or the anchoring is dropped so an echoed instruction counts again.
  Any of these restores the #753 / 2026-08-05 / hedge-list behaviour.

  OVER — ⛔ the fallback is deleted, so a model that ignores the format goes
  unparsed; or the STOP_BUTTON override is dropped, so an inconsistent answer
  resolves the EXPENSIVE way (a false "complete" extracts an in-flight
  response); or "unsure" starts counting as a Stop sighting, which turns
  hesitancy into a user card.

The single most important mutant is O1. Deleting the prose fallback would pass
every contract test in the new file and silently break every historical answer
in the corpus — which is the normal case, since nothing guarantees the model
complies with a format.

    .venv/bin/python .mutants/cua_verdict_contract_0812_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = ("tests/test_cua_verdict_contract_0812.py "
          "tests/test_cua_confirm_budget_0812.py "
          "tests/test_safety_net_verdict_753.py "
          "tests/test_safety_net_stop_veto_755.py "
          "tests/test_cua_generating_polarity.py "
          "tests/test_brief_done_label_0811.py")

MUTANTS = [
    # ═════════════════════ UNDER — back to sniffing prose ══════════════════
    ("U1", "under", "⭐ the contract is never read — every answer goes through the keyword parser",
     # ⛔⛔ RE-ANCHORED 2026-08-23. Wave 7 extracted this reader into
     # `_verdict_line_re` / `_last_verdict` so every verifier shares one, and
     # doing so stranded six anchors in the harness that PROVES the contract
     # works — in the exact area the refactor claimed to strengthen.
     [("    verdict = _last_verdict(t, _CUA_VERDICT_LINE)", '    verdict = ""')]),
    ("U2", "under", "⭐ prose is consulted FIRST, so a hedge still vetoes a stated verdict",
     # RE-ANCHORED 2026-08-23 onto the extracted reader (see U1).
     [('    if verdict:\n'
       "        if verdict == \"unknown\":\n"
       '            verdict = "ambiguous"\n'
       '        source = "contract"',
       '    if _classify_completion_verdict(t) == "generating":\n'
       '        verdict = "generating"\n'
       '        source = "contract"\n'
       "    elif verdict:\n"
       "        if verdict == \"unknown\":\n"
       '            verdict = "ambiguous"\n'
       '        source = "contract"')]),
    ("U3", "under", "⛔ the line anchor is dropped — an echoed instruction decides again (#753)",
     # RE-ANCHORED 2026-08-23: the pattern is BUILT now, so dropping the anchor
     # means dropping it for every field at once — a bigger version of the same
     # defect, and the reason one shared reader was worth extracting.
     [('        r"^[^\\S\\n]*" + field + r"[^\\S\\n]*[:=][^\\S\\n]*(" + "|".join(values) + r")\\b",\n'
       "        re.I | re.M)",
       '        r"" + field + r"[^\\S\\n]*[:=][^\\S\\n]*(" + "|".join(values) + r")\\b",\n'
       "        re.I)")]),
    ("U4", "under", "the FIRST verdict wins — a deliberation outranks the conclusion",
     # RE-ANCHORED 2026-08-23: choosing among matches moved into `_last_verdict`.
     [('    return hits[-1].lower() if hits else ""', '    return hits[0].lower() if hits else ""')]),
    ("U5", "under", "'unknown' stops mapping onto the existing vocabulary",
     [('        if verdict == "unknown":\n            verdict = "ambiguous"', "")]),
    ("U6", "under", "the confirm mission stops asking for the contract",
     [('    "guess: \'cannot determine\' is a valid and useful answer."\n'
       "    + _CUA_CONTRACT_BLOCK)",
       '    "guess: \'cannot determine\' is a valid and useful answer.")')]),
    ("U7", "under", "only ONE twin asks for the contract — two vocabularies again",
     [('                    "Remember: observe only — never click the Stop button or any control."\n'
       "                    + _CUA_CONTRACT_BLOCK)",
       '                    "Remember: observe only — never click the Stop button or any control.")')]),
    ("U8", "under", "the confirm twin parses the answer itself again",
     [('                _report = _cua_completion_report(diag_text)\n'
       '                _verdict = _report["verdict"]',
       '                _report = {"source": "prose"}\n'
       "                _verdict = _classify_completion_verdict(diag_text)")]),
    ("U9", "under", "the safety-net twin bypasses the shared reader",
     [('                    _sn_verdict = _cua_completion_report(_sn_text)["verdict"]',
       "                    _sn_verdict = _classify_completion_verdict(_sn_text)")]),
    ("U10", "under", "the contract stops naming 'unknown' as a real answer",
     [("are real \"\n    \"answers: use them rather than guessing.\")",
       "are real answers.\")")]),

    # ═══════════════════════════ OVER — overreach ══════════════════════════
    ("O1", "over", "⛔⛔ the prose fallback is deleted — every historical answer goes unparsed",
     [("        verdict = _classify_completion_verdict(t)\n"
       '        source = "prose"',
       '        verdict = "complete"\n        source = "prose"')]),
    ("O2", "over", "⛔ a reported Stop button no longer overrides 'complete'",
     [('    if stop_seen and verdict != "generating":\n        verdict = "generating"', "")]),
    ("O3", "over", "⛔ 'unsure' counts as a Stop sighting — hesitancy becomes a user card",
     [('        stop_seen = (stop == "yes")', '        stop_seen = (stop != "no")')]),
    ("O4", "over", "the pre-contract stop derivation is dropped from the fallback path",
     [('        stop_seen = (_cua_affirms(t, "stop button")\n'
       '                     or _cua_affirms(t, "stop:")\n'
       '                     or _cua_affirms(t, "stop icon"))',
       "        stop_seen = False")]),
    ("O5", "over", "the STOP_BUTTON line is never read — the polarity rule goes blind",
     # RE-ANCHORED 2026-08-23 onto the extracted reader (see U1).
     [('    stop = _last_verdict(t, _CUA_STOP_LINE)', '    stop = ""')]),
    ("O6", "over", "a bare verdict word with no label counts — prose starts deciding again",
     # RE-ANCHORED 2026-08-23: the label is now the `field` argument, so making
     # it optional makes every contract field label-optional at once.
     [('        r"^[^\\S\\n]*" + field + r"[^\\S\\n]*[:=][^\\S\\n]*(" + "|".join(values) + r")\\b",',
       '        r"^[^\\S\\n]*(?:" + field + r"[^\\S\\n]*[:=][^\\S\\n]*)?(" + "|".join(values) + r")\\b",')]),
    ("O7", "over", "the source label is a constant — a run carried by the fallback looks healthy",
     [('        source = "prose"', '        source = "contract"')]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q"],
            cwd=ROOT, capture_output=True, text=True, timeout=180).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    path = ROOT / RESEARCH
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found: {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests()
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, f"ANCHOR MISS: {exc}"))
        finally:
            path.write_text(original, encoding="utf-8")

    still_dirty = tracked_dirty()
    if still_dirty:
        print("\n⛔ the tree did not come back clean:\n" + "\n".join(still_dirty))
        return 2

    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed")
    for mid, direction, why in survivors:
        print(f"  SURVIVED {mid} [{direction}] {why}")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
