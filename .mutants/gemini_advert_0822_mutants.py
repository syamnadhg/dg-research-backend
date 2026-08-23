"""Mutation harness for wave 6 fix 1 — the Gemini advert rule, keyed on the plan.

⛔ WHAT THIS IS FOR. The Gemini model ranker had no sales-prompt exclusion at
all. A row that names the family, parses a version and carries an upgrade verb —
"Try 4.0 Flash with Google AI Ultra" — clears the `reject` list, outranks every
genuine row on version, gets clicked, opens a billing surface over the composer
and returns truthy, so the run reports a successful model pick into a modal.

⭐⭐ THE SHARPEST MUTANTS HERE:
  P2  — the nouns become the FAMILY word, which is what a straight port of the
        Claude rule would have done. Everything still reads as guarded and the
        two plan-only adverts are never scored: the guard that ships and
        matches nothing.
  P4  — the rule ships ENFORCED on a pattern nobody has measured, against the
        one platform with no `free_family`. Its failure is not an error; it is
        a run left on Gemini Pro Deep Research for one to two hours.
  P3  — bare "advanced" joins the nouns, so a genuine Flash row describing its
        own reasoning is binned. Same hang, arrived at from the other side.
  R4  — adverts are scored AFTER `rejected()`. Most of Google's sales copy
        names a plan containing "pro", so the measurement this ships to collect
        reports near zero and is read as "no adverts in this menu".
  R5  — the whitespace collapse drops back to this language's own \\s, so the
        port and its Python definition disagree about the same row.
  H2  — an eval error reports "no sales rows", which is a count for a menu that
        was never read.

⭐ Over-corrections:
  R3  — the skip ignores the shadow flag, so shipping dark ships live.
  H6  — the log sample is unbounded, across the page.evaluate boundary.

    python .mutants/gemini_advert_0822_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = "research.py"
MOD = "models.py"
MUTATED_FILES = [RES, MOD]

T_ADVERT = "tests/test_gemini_advert_shadow_0822.py"
# ⛔ The family/reject policy and the Claude ranker read the same UPSELL_VERBS
# and the same `_collapse_ws`; a change here that suits Gemini must not move
# either of them.
T_MODELS = "tests/test_model_policy.py"
T_CLAUDE = "tests/test_family_only_selection.py"
ALL = [T_ADVERT, T_MODELS, T_CLAUDE]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 900

MUTANTS: list[tuple[str, str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ policy: which nouns, and whether the rule acts ══════════════════════
    ("P1", MOD, "under", "the advert rule is configured out entirely",
     [('        "upsell_nouns": ["google ai", "gemini advanced", "google one",\n'
       '                         "advanced plan", "pro plan"],',
       '        "upsell_nouns": [],')],
     [T_ADVERT]),
    ("P2", MOD, "under",
     "⛔⛔ the nouns become the FAMILY word — the straight port of Claude's "
     "rule, which reads as shipped and matches Google's sales copy nowhere",
     [('        "upsell_nouns": ["google ai", "gemini advanced", "google one",\n'
       '                         "advanced plan", "pro plan"],',
       '        "upsell_nouns": ["flash"],')],
     [T_ADVERT]),
    ("P3", MOD, "over",
     "⛔⛔ bare \"advanced\" joins the nouns, so a Flash row describing its own "
     "reasoning is binned — and this platform has no family to fall back to",
     [('        "upsell_nouns": ["google ai", "gemini advanced", "google one",\n'
       '                         "advanced plan", "pro plan"],',
       '        "upsell_nouns": ["google ai", "gemini advanced", "google one",\n'
       '                         "advanced plan", "pro plan", "advanced"],')],
     [T_ADVERT]),
    ("P4", MOD, "over",
     "⛔⛔ the rule ships ENFORCED on an unmeasured pattern — its failure mode "
     "is a 1-2h hang, not an error",
     [('        "upsell_shadow": True,', '        "upsell_shadow": False,')],
     [T_ADVERT]),
    ("P5", MOD, "over",
     "a platform that carries nouns without saying defaults to ENFORCING them",
     [('    if isinstance(v, bool):\n'
       '        return v\n'
       '    return bool(upsell_nouns(platform))',
       '    if isinstance(v, bool):\n'
       '        return v\n'
       '    return False')],
     [T_ADVERT]),
    ("P6", MOD, "under",
     "a platform with NO nouns reports itself as shadowing a rule it does not "
     "have, so \"is the rule dark?\" stops meaning anything",
     [('    if isinstance(v, bool):\n'
       '        return v\n'
       '    return bool(upsell_nouns(platform))',
       '    if isinstance(v, bool):\n'
       '        return v\n'
       '    return True')],
     [T_ADVERT]),
    ("P7", MOD, "over",
     "⛔ an unconfigured platform silently inherits the family word as its "
     "advert noun — every platform acquires a guard nobody measured",
     [('    v = p2_labels(platform).get("upsell_nouns")\n'
       '    if not isinstance(v, (list, tuple)):\n'
       '        return []',
       '    v = p2_labels(platform).get("upsell_nouns")\n'
       '    if not isinstance(v, (list, tuple)):\n'
       '        return [p2_family(platform)] if p2_family(platform) else []')],
     [T_ADVERT]),
    ("P8", MOD, "under",
     "the nouns are not lowercased, so a policy edit in title case silently "
     "stops matching the lowercased row on both sides",
     [('    return [str(n).lower().strip() for n in v if str(n).strip()]',
       '    return [str(n).upper().strip() for n in v if str(n).strip()]')],
     [T_ADVERT]),
    ("P9", MOD, "over", "the two keys become overlay-settable, which makes "
     "enforcement a remote switch on a rule with a multi-hour failure mode",
     [('    "reject": list,', '    "reject": list,\n    "upsell_shadow": bool,')],
     [T_ADVERT]),

    # ══ is_upsell_any — the shared definition ═══════════════════════════════
    # ⚠ The FIRST form of this mutant (`for n in nouns or [""]`) was equivalent:
    # `is_upsell` already answers False for an empty noun, so both sides agreed
    # on every input. Dropping the guard outright is the observable version —
    # `nouns=None` then raises inside the ranker's own policy read.
    ("A1", MOD, "under", "the noun guard is dropped, so an unconfigured "
     "platform raises instead of answering \"no rule\"",
     [('    if not text or not nouns:\n        return False\n    for n in nouns:',
       '    for n in nouns:')],
     [T_ADVERT]),
    ("A2", MOD, "under", "only the FIRST noun is ever tried",
     [('    for n in nouns:\n'
       '        if is_upsell(text, str(n), window):\n'
       '            return True\n'
       '    return False',
       '    return is_upsell(text, str(list(nouns)[0]), window)')],
     [T_ADVERT]),
    ("A3", MOD, "over", "the window argument is dropped, so a caller widening "
     "or narrowing it is silently ignored",
     [('        if is_upsell(text, str(n), window):',
       '        if is_upsell(text, str(n)):')],
     [T_ADVERT]),

    # ══ the Python mirror ═══════════════════════════════════════════════════
    ("M1", MOD, "under", "the mirror ignores `sale_nouns` and always keys on "
     "the family, so it stops being a mirror of the Gemini ranker",
     [('        if drop_upsell and (is_upsell_any(t, sale_nouns) if sale_nouns\n'
       '                            else is_upsell(t, family)):',
       '        if drop_upsell and is_upsell(t, family):')],
     [T_ADVERT]),
    ("M2", MOD, "over", "`sale_nouns` alone enables the exclusion, so passing "
     "the nouns silently turns a switch the caller did not touch",
     [('        if drop_upsell and (is_upsell_any(t, sale_nouns) if sale_nouns\n'
       '                            else is_upsell(t, family)):',
       '        if (drop_upsell or sale_nouns) and (is_upsell_any(t, sale_nouns)\n'
       '                            if sale_nouns else is_upsell(t, family)):')],
     [T_ADVERT]),

    # ══ the ranker JS — what actually ships ═════════════════════════════════
    ("R1", RES, "under", "the advert skip is gone, so enforcing is a no-op",
     [('        if (dropUpsell && adv) continue;\n', '')],
     [T_ADVERT]),
    ("R2", RES, "under", "nothing is ever recorded, so the scan this wave "
     "ships to collect measures nothing",
     [('        if (adv && adverts.length < 8) adverts.push(t.slice(0, 60));\n', '')],
     [T_ADVERT]),
    ("R3", RES, "over", "⛔ the skip ignores the shadow flag — shipping dark "
     "ships live",
     [('        if (dropUpsell && adv) continue;',
       '        if (adv) continue;')],
     [T_ADVERT]),
    ("R4", RES, "under",
     "⛔⛔ adverts are scored AFTER reject. Google's sales copy usually names a "
     "plan containing \"pro\", so the count comes back near zero and reads as "
     "\"this menu has no adverts\"",
     [('        const adv = isUpsell(el.textContent || \'\');\n'
       '        if (adv && adverts.length < 8) adverts.push(t.slice(0, 60));\n'
       '        // Reject siblings FIRST (order matters — "Flash-Lite" also has "flash").\n'
       '        if (rejected(t)) continue;',
       '        // Reject siblings FIRST (order matters — "Flash-Lite" also has "flash").\n'
       '        if (rejected(t)) continue;\n'
       '        const adv = isUpsell(el.textContent || \'\');\n'
       '        if (adv && adverts.length < 8) adverts.push(t.slice(0, 60));')],
     [T_ADVERT]),
    ("R5", RES, "under",
     "⛔ the collapse drops back to JS's own \\s, so the port and its Python "
     "definition disagree about a row padded with \\x85 or a BOM",
     [("    const normU = s => (s || '').replace(/[\\\\s\\\\x1c-\\\\x1f\\\\x85\\\\ufeff]+/g, ' ').trim();\n"
       "    const isUpsell = (raw) => {",
       "    const normU = s => (s || '').replace(/\\\\s+/g, ' ').trim();\n"
       "    const isUpsell = (raw) => {")],
     [T_ADVERT]),
    # ⛔ The two-line anchor is not decoration. The `if` line alone, at this
    # indentation, is a SUBSTRING of the Claude ranker's copy four screens away
    # (same text, four more spaces), so a one-line anchor matched 4x and the
    # mutant measured nothing. Uniqueness, not presence.
    ("R6", RES, "over", "the window is ignored, so any verb anywhere in a row "
     "that mentions a plan makes it an advert",
     [('                        const j = s.indexOf(n, end);\n'
       '                        if (j !== -1 && j - end <= upsellWindow) return true;',
       '                        const j = s.indexOf(n, end);\n'
       '                        if (j !== -1) return true;')],
     [T_ADVERT]),
    ("R7", RES, "over", "the verb boundary test is dropped, so \"Gettysburg\" "
     "contains \"get\"",
     [('                    const leftOk = i === 0 || !isAlnum(s[i - 1]);\n'
       '                    const rightOk = end >= s.length || !isAlnum(s[end]);\n'
       '                    if (leftOk && rightOk) {\n'
       '                        const j = s.indexOf(n, end);',
       '                    if (true) {\n'
       '                        const j = s.indexOf(n, end);')],
     [T_ADVERT]),
    ("R8", RES, "under", "the winner's own verdict is never recorded, so the "
     "one number that decides whether the rule flips is always false",
     [('            bestAdv = adv;\n', '')],
     [T_ADVERT]),
    ("R9", RES, "over", "`advertPick` becomes \"the menu had an advert\" rather "
     "than \"we clicked one\" — the flip decision loses its subject",
     [('             advertPick: !!(bestEl && bestAdv), adverts };',
       '             advertPick: adverts.length > 0, adverts };')],
     [T_ADVERT]),
    ("R10", RES, "over", "the sample is unbounded across the evaluate boundary",
     [('        if (adv && adverts.length < 8) adverts.push(t.slice(0, 60));',
       '        if (adv) adverts.push(t.slice(0, 60));')],
     [T_ADVERT]),
    ("R11", RES, "under", "the sample is cut short of the plan phrase it exists "
     "to carry back",
     [('        if (adv && adverts.length < 8) adverts.push(t.slice(0, 60));',
       '        if (adv && adverts.length < 8) adverts.push(t.slice(0, 20));')],
     [T_ADVERT]),
    ("R12", RES, "under", "the nouns are never consulted — the loop body runs "
     "against an empty list, so nothing is ever an advert",
     [("        for (const rawNoun of (nouns || [])) {",
       "        for (const rawNoun of []) {")],
     [T_ADVERT]),

    # ══ the enforcement decision ════════════════════════════════════════════
    ("E1", RES, "over",
     "⛔⛔ the shadow flag is ignored in the one place it is read, so the rule "
     "goes live on an unmeasured pattern with everything else unchanged",
     [('    return nouns, bool(nouns) and not _models_upsell_shadow("gemini")',
       '    return nouns, bool(nouns)')],
     [T_ADVERT]),
    ("E2", RES, "over", "an EMPTY rule can be live — nothing is skipped and "
     "every log line says the rule is enforced",
     [('    return nouns, bool(nouns) and not _models_upsell_shadow("gemini")',
       '    return nouns, not _models_upsell_shadow("gemini")')],
     [T_ADVERT]),
    ("E3", RES, "under", "the rule can never be turned on",
     [('    return nouns, bool(nouns) and not _models_upsell_shadow("gemini")',
       '    return nouns, False')],
     [T_ADVERT]),

    # ══ what the caller says ════════════════════════════════════════════════
    ("H1", RES, "under", "a zero result is silent, so the denominator that "
     "decides whether the pattern works is never written down",
     [('    else:\n'
       '        lines.append(("INFO",\n'
       '                      f"[setup_gemini_dr] advert-scan ({mode}): no row in the model menu "\n'
       '                      f"reads as a sales prompt"))',
       '    else:\n'
       '        return lines')],
     [T_ADVERT]),
    ("H2", RES, "over",
     "⛔⛔ an eval error reports \"no sales rows\" — a count for a menu that was "
     "never read, which is the same untruth as a source count of zero",
     [('    if not isinstance(rank, dict) or "adverts" not in rank:\n        return []\n', '')],
     [T_ADVERT]),
    ("H3", RES, "over", "a platform with no rule still narrates one",
     [('    if not nouns:\n        return []\n', '')],
     [T_ADVERT]),
    ("H4", RES, "under", "a clicked advert is never called out, so the single "
     "actionable line in the whole scan is gone",
     [('    if rank.get("advertPick"):', '    if False:')],
     [T_ADVERT]),
    ("H5", RES, "under", "every line claims shadow, so a live rule reads as "
     "dark in the log",
     [('    mode = "enforced" if live else "shadow (not acted on)"',
       '    mode = "shadow (not acted on)"')],
     [T_ADVERT]),
    ("H6", RES, "over", "the log sample is unbounded",
     [('        _sample = " | ".join(str(a) for a in adverts[:4])',
       '        _sample = " | ".join(str(a) for a in adverts)')],
     [T_ADVERT]),
    ("H7", RES, "under", "the enforced-mode contradiction reads as the shadow "
     "message, so a ranker that disagrees with its own flag looks routine",
     [('        if live:\n'
       '            # Unreachable by construction', '        if False:\n'
       '            # Unreachable by construction')],
     [T_ADVERT]),

    # ══ the consumer ════════════════════════════════════════════════════════
    ("C1", RES, "under", "the helper is computed and never logged — the whole "
     "measurement this wave ships reaches nobody",
     [('        for _al in _gemini_advert_lines(_rank, live=_gm_advert_live,\n'
       '                                        nouns=_gm_nouns):\n'
       '            log(_al[1], _al[0])\n', '')],
     [T_ADVERT]),
    ("C2", RES, "under", "the ranker is never handed the nouns, so every row "
     "scores clean no matter what policy says",
     [('                "nouns": _gm_nouns, "verbs": list(UPSELL_VERBS),',
       '                "nouns": [], "verbs": list(UPSELL_VERBS),')],
     [T_ADVERT]),
    ("C3", RES, "over", "the ranker is handed a hardcoded enforce flag",
     [('                "upsellWindow": UPSELL_WINDOW, "dropUpsell": _gm_advert_live})',
       '                "upsellWindow": UPSELL_WINDOW, "dropUpsell": True})')],
     [T_ADVERT]),

    # ══ the shim fix this wave needed ══════════════════════════════════════
    # ⚠ Not production code, but a harness that silently truncates node's answer
    # reports a JSONDecodeError inside the caller's own fixture. Kept because a
    # revert here would take every whitespace-agreement assertion with it.
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
    for mid, fname, direction, why, edits, tests in MUTANTS:
        target = ROOT / fname
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
                    raise ValueError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]}")
                mutated = mutated.replace(frm, to, 1)
            target.write_text(mutated, encoding="utf-8")
            if target.read_text(encoding="utf-8") != mutated:
                raise ValueError("the mutation did not reach the file")
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

    over = sum(1 for m in MUTANTS if m[2] == "over")
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
