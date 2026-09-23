"""Wave 10.10 (machine-models) — can the guards see a model version read as a
decimal again?

⛔⛔ WHAT THE WAVE CLOSED. Every page script that read a model version ended in
`parseFloat(m[1])`, and every Python reader in `float(...)`. So "5.10" was 5.1:
{Opus 5.5, Opus 5.10} picked 5.5, Gemini {3.8, 3.10} picked 3.8, a computer
already on 5.10 was "upgraded" back to 5.5 on every probe, and a step-back below
a failed 5.10 found nothing to pick. The same number was the exact-pin test, the
step-back bound AND the learned known-good persisted on every installed
computer as a JSON number — so the fix is one ORDER (`models.version_key` and
its browser twin `_VERSION_ORDER_JS`) plus a translator that still reads the
stored 5.0 / 3.8.

Every mutant below reverts ONE decision. The quiet ones:

  M2   — the translator stops reading a stored NUMBER. Nothing breaks on a
         fresh install; every computer that already learned a model loses its
         pin on the first run after the upgrade.
  M12  — "unchanged" compared by text, so a stored 5.0 and a verified "5" are
         two different models: a write on every run, and nothing looks wrong.
  S1/S4/S5 — a numbers-only gate in front of a version that now arrives as
         TEXT. Each one looks like a harmless type check; each silently turns a
         whole path off (the weekly upgrade, the learned pick, the step-back).
  S7   — the consumer ignores the rule: the pin is never sent, and the step-back
         still "works" by retreating one row instead of to the proven model.
  V1   — the browser stops reading a number pin, the legacy half of the
         translator: a stored 5.0 no longer exact-matches "Opus 5".

⛔⛔ AND THE SECOND TASK (E1-E17): Claude's Deep Research went out at Low on
09-20 with a log that said only "Max NOT confirmed". Step 1C now reads the
Effort row the way it is rendered (the walker copied from the ChatGPT trigger
reader) and the run says which tier it is on. The quiet ones:

  E4/E11/E12 — a row read BEFORE an unverified press is reported as the tier:
         the log and the caption state a tier nothing proved.
  E8   — an UNREAD tier reaches the person: the "could not confirm" false alarm
         the 2026-06-22 decision removed.
  E9   — the consumer ignores the rule: everything is computed, nothing shown.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written. The JS mutants are written to
stay valid JS: a script that no longer parses is killed by node refusing it,
which measures nothing.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED, from the checkout you want
measured:

  <venv>/bin/python -u .mutants/wave1010_models_mutants.py
  <venv>/bin/python -u .mutants/wave1010_models_mutants.py G1 S7
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_model_selection_precision.py "
          "tests/test_known_good_fallback.py "
          "tests/test_claude_popover_skip.py "
          "tests/test_model_policy.py "
          "tests/test_family_only_selection.py "
          "tests/test_claude_model_pick.py "
          "tests/test_gemini_flash_rank.py "
          "tests/test_claude_mode_detect.py")
RESEARCH = "research.py"
MODELS = "models.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ── models.version_key: the ORDER, and the translator ──────────────────
    ("M1", "under", "a bool reads as version 1 (isinstance(True, int) is true)",
     [("    if isinstance(v, bool):\n        return None\n"
       "    if isinstance(v, (int, float)):\n",
       "    if isinstance(v, (int, float)):\n")], MODELS),
    ("M2", "under", "⛔⛔ the translator stops reading a stored NUMBER — every "
     "computer that learned 5.0 / 3.8 loses its pin on the first run after this",
     [("        s = repr(float(v))\n", "        return None\n")], MODELS),
    ("M3", "under", "a non-ASCII digit reads as a version the browser cannot parse",
     [("    if not all(p.isascii() and p.isdigit() for p in parts):\n",
       "    if not all(p.isdigit() for p in parts):\n")], MODELS),
    ("M4", "under", "trailing zeros kept: a stored 5.0 and a verified '5' are "
     "two different models",
     [("    while len(key) > 1 and key[-1] == 0:\n        key.pop()\n", "")], MODELS),
    ("M5", "under", "an all-zero version collapses to () and becomes writable",
     [("    while len(key) > 1 and key[-1] == 0:\n",
       "    while len(key) > 0 and key[-1] == 0:\n")], MODELS),
    ("M6", "under", "a hand-edited ' 5.10 ' in the overlay reads as junk",
     [("        s = v.strip()\n", "        s = v\n")], MODELS),
    ("M7", "under", "⛔ the Python mirror parses a version as a float again",
     [("    return m.group(1) if m else None\n",
       "    return float(m.group(1)) if m else None\n")], MODELS),
    ("M8", "under", "ChatGPT's tier tie-break ranks versions as TEXT ('5.5' > '5.10')",
     [("        rank = (0, ()) if v is None else (1, version_key(v))\n",
       "        rank = (0, ()) if v is None else (1, v)\n")], MODELS),
    ("M9", "under", "the ranker spec ranks by float again (5.10 under 5.5)",
     [("        rank = (0, ()) if k is None else (1, k)\n",
       "        rank = (0, ()) if k is None else (1, float(v))\n")], MODELS),
    ("M10", "under", "the step-back bound admits the version that just failed",
     [("            if k is None or k >= bound:\n",
       "            if k is None or k > bound:\n")], MODELS),
    ("M11", "under", "⛔ the known-good is SAVED as a float: Opus 5.10 stored as 5.1",
     [("    return _merge_overlay_entry(platform, **{key: version_text(version)})\n",
       "    return _merge_overlay_entry(platform, **{key: float(version)})\n")], MODELS),
    ("M12", "under", "⛔ 'unchanged' compared by text: a stored 5.0 vs a verified "
     "'5' rewrites the file on every run",
     [("    if version_key(_platform_entry(platform).get(key)) == v:\n",
       "    if _platform_entry(platform).get(key) == version_text(version):\n")], MODELS),
    ("M13", "under", "version 0 is learned as a known-good",
     [("    if v is None or v == (0,):\n", "    if v is None:\n")], MODELS),
    ("M14", "under", "the reader hands back the raw stored value (a float 5.0)",
     [("    return version_text(raw)\n", "    return raw\n")], MODELS),
    ("M15", "under", "stepped_back_to goes back to numbers only — a text retreat "
     "(5.10 → 5.9) is never announced",
     [("    p, f = version_key(picked), version_key(failed)\n",
       "    p, f = ((version_key(picked), version_key(failed))\n"
       "            if isinstance(picked, (int, float)) and isinstance(failed, (int, float))\n"
       "            else (None, None))\n")], MODELS),
    ("M16", "under", "the computer-use fallback loses the 'ten after nine' rule",
     [('f"one, close the menu without clicking it. Compare versions part by part "\n'
       '        f"as whole numbers, never as decimals: the part after the dot counts on "\n'
       '        f"past nine, so ten after the dot is NEWER than nine after the dot. "\n',
       'f"one, close the menu without clicking it. "\n')], MODELS),

    # ── _VERSION_ORDER_JS: the browser's one definition ────────────────────
    ("V1", "under", "⛔ the browser stops reading a NUMBER pin — the legacy half "
     "of the translator; a stored 5.0 no longer matches 'Opus 5'",
     [("        for (const part of String(x).split('.')) {\n",
       "        for (const part of (typeof x === 'string' ? x : '').split('.')) {\n")]),
    ("V2", "under", "a missing part is not zero: '5' and '5.0' are different versions",
     [("const x = i < a.length ? a[i] : 0, y = i < b.length ? b[i] : 0;",
       "const x = i < a.length ? a[i] : -1, y = i < b.length ? b[i] : -1;")]),
    ("V3", "under", "a non-digit part reads as a version (NaN) instead of no pin",
     [("            for (const c of part) if (c < '0' || c > '9') return null;\n", "")]),
    ("V4", "under", "an empty part ('5.', '') reads as a version instead of no pin",
     [("            if (!part) return null;\n", "")]),

    # ── the Gemini Flash ranker ────────────────────────────────────────────
    ("G1", "under", "⛔ Gemini parses the version with parseFloat again (3.10 = 3.1)",
     [("        return m ? m[1] : null;\n    };\n"
       "    // Character-level port of models.reject_matches",
       "        return m ? parseFloat(m[1]) : null;\n    };\n"
       "    // Character-level port of models.reject_matches")]),
    ("G2", "under", "Gemini keeps the text but ranks it as a decimal",
     [("\n        const k = verKey(v);\n        let rank;",
       "\n        const k = v === null ? null : [parseFloat(v)];\n        let rank;")]),
    ("G3", "under", "Gemini's exact pin compares TEXT: a stored '3' misses the "
     "'3.0 Flash' row it names",
     [("\n        if (pinK !== null && k !== null && cmpVer(k, pinK) === 0) {",
       "\n        if (pinK !== null && k !== null && v === String(pin)) {")]),
    ("G4", "under", "Gemini's step-back re-admits the version that just failed",
     [("\n                if (k === null || cmpVer(k, bound) >= 0) continue;",
       "\n                if (k === null || cmpVer(k, bound) > 0) continue;")]),
    ("G5", "under", "Gemini reports the sort KEY instead of the version text",
     [("\n            bestVer = v;\n", "\n            bestVer = k;\n")]),
    ("G6", "under", "Gemini compares ranks with a bare `>` (arrays as strings)",
     [("        if (bestEl === null || rank[0] > bestRank[0] || (rank[0] === bestRank[0] && d > 0)",
       "        if (bestEl === null || rank[0] > bestRank[0] || (rank[0] === bestRank[0] && rank[1] > bestRank[1])")]),

    # ── Claude: the picker ─────────────────────────────────────────────────
    ("P1", "under", "⛔ the Claude picker parses with parseFloat again (5.10 under 5.5)",
     [("                return m ? m[1] : null;\n            };\n"
       "            // Character-level port of models.is_upsell",
       "                return m ? parseFloat(m[1]) : null;\n            };\n"
       "            // Character-level port of models.is_upsell")]),
    ("P2", "under", "the Claude picker keeps the text but ranks it as a decimal",
     [("                const k = verKey(v);\n                let rank;",
       "                const k = v === null ? null : [parseFloat(v)];\n                let rank;")]),
    ("P3", "under", "the Claude picker's exact pin compares TEXT: '5' misses 'Opus 5.0'",
     [("                if (pinK !== null && k !== null && cmpVer(k, pinK) === 0) {",
       "                if (pinK !== null && k !== null && v === String(pin)) {")]),
    ("P4", "under", "the Claude step-back re-admits the version that just failed",
     [("                        if (k === null || cmpVer(k, bound) >= 0) continue;",
       "                        if (k === null || cmpVer(k, bound) > 0) continue;")]),
    ("P5", "under", "the Claude picker reports the sort KEY instead of the text",
     [("best = el; bestRank = rank; bestLen = t.length; bestVer = v;",
       "best = el; bestRank = rank; bestLen = t.length; bestVer = k;")]),
    ("P6", "under", "the Claude picker compares ranks with a bare `>`",
     [("                if (best === null || rank[0] > bestRank[0] || (rank[0] === bestRank[0] && d > 0)",
       "                if (best === null || rank[0] > bestRank[0] || (rank[0] === bestRank[0] && rank[1] > bestRank[1])")]),

    # ── Claude: the trigger read and the offered-probe ─────────────────────
    ("T1", "under", "⛔ the trigger reads 'Opus 5.10 Max' as 5.1 again",
     [("                return m ? m[1] : null;\n            };\n"
       "            // An upsell chip",
       "                return m ? parseFloat(m[1]) : null;\n            };\n"
       "            // An upsell chip")]),
    ("T2", "under", "the trigger's page-wide max compares version TEXT",
     [("if (k !== null && (bestK === null || cmpVer(k, bestK) > 0)) {",
       "if (k !== null && (best === null || v > best)) {")]),
    ("Q1", "under", "⛔ the offered-probe reads 5.10 as 5.1 again",
     [("                return m ? m[1] : null;\n            };\n"
       "            // Same port, same reason",
       "                return m ? parseFloat(m[1]) : null;\n            };\n"
       "            // Same port, same reason")]),
    ("Q2", "under", "the offered-probe's max compares version TEXT",
     [("if (highK === null || cmpVer(k, highK) > 0) { highest = v; highK = k; }",
       "if (highest === null || v > highest) { highest = v; highK = k; }")]),

    # ── the Python consumers ───────────────────────────────────────────────
    ("S1", "under", "⛔⛔ Step 1B* lets only NUMBERS through: every offered version "
     "is text now, so the weekly upgrade never fires again",
     [("                    _off_k = version_key(_offered)\n",
       "                    _off_k = version_key(_offered) if isinstance(_offered, (int, float)) else None\n")]),
    ("S2", "under", "Step 1B* re-clicks the current model (>=): the #744 loop",
     [("(_cur_k is None or _off_k > _cur_k):", "(_cur_k is None or _off_k >= _cur_k):")]),
    ("S3", "under", "Step 1B* reads a text trigger as 'no version', so anything "
     "offered counts as newer and the popover re-picks every interval",
     [("                    _cur_k = version_key(model_trigger_ver)\n",
       "                    _cur_k = version_key(model_trigger_ver) if isinstance(model_trigger_ver, (int, float)) else None\n")]),
    ("S4", "under", "⛔ the learned pick lets only NUMBERS through and falls back "
     "to re-reading the label",
     [("            if version_key(_picked_version) is not None\n",
       "            if isinstance(_picked_version, (int, float))\n")]),
    ("S5", "under", "⛔⛔ the step-back lets only NUMBERS through: a text failed "
     "version leaves BOTH targets None and the one retry never runs",
     [("            _failed_v = version_text(_failed)\n",
       "            _failed_v = version_text(_failed) if isinstance(_failed, (int, float)) else None\n")]),
    ("S6", "under", "the pin is compared as TEXT: a learned 5.9 is 'not older' "
     "than a failed 5.10",
     [("and version_key(_kg) < version_key(_failed_v) else None)",
       "and _kg < _failed_v else None)")]),
    ("S7", "under", "⛔ the consumer ignores the rule: the learned pin is never sent",
     [("            _pin = (_kg if _failed_v is not None\n",
       "            _pin = (None if _failed_v is not None\n")]),

    # ══ task 2 — the effort the run ACTUALLY got ═══════════════════════════
    # ── the page read: the Effort row, gap-aware ───────────────────────────
    ("E1", "under", "⛔ the row is read glued again ('efforthighdefault'): a "
     "two-span tier is no tier at all",
     [("                                shows: spaced(trigger).slice(0, 60),",
       "                                shows: norm(trigger.textContent).slice(0, 60),")]),
    ("E2", "under", "the walker supplies no gap at an element boundary",
     [("\n                                else if (c.nodeType === 1) { out += ' '; walk(c); out += ' '; }",
       "\n                                else if (c.nodeType === 1) { walk(c); }")]),
    # ── the pure reads ─────────────────────────────────────────────────────
    ("E3", "under", "a one-node row ('EffortLow') names no tier",
     [('        if w.startswith("effort"):\n            return w[len("effort"):]\n', "")]),
    ("E17", "under", "the tier is not the word AFTER 'effort'",
     [("            return words[i + 1] if i + 1 < len(words) else None\n",
       "            return words[i]\n")]),
    ("E4", "over", "⛔ a row read BEFORE an unverified press is still reported as "
     "the tier in effect",
     [("    if pressed:\n        return None\n    return row_shows or None",
       "    return row_shows or None")]),
    ("E5", "under", "a CONFIRMED tier reports the stale pre-set row instead",
     [('        return str(wanted or "").strip().lower() or None\n    if pressed:',
       "        return row_shows or None\n    if pressed:")]),
    ("E6", "over", "⛔ a run AT the wanted tier gets the 'could not be set' caption",
     [("    if g and (g == w or not w):", "    if g and not w:")]),
    ("E7", "over", "a policy that wants nothing shows '— could not be set'",
     [("    if g and (g == w or not w):", "    if g and g == w:")]),
    ("E8", "over", "⛔ an UNREAD tier is shown to the person — the 06-22 false alarm back",
     [('                           f"be weaker than the run reports"),\n'
       '                "notice": None}',
       '                           f"be weaker than the run reports"),\n'
       '                "notice": "Claude could not confirm its effort"}')]),
    # ── the consumer: setup_claude_dr ──────────────────────────────────────
    ("E9", "under", "⛔ the consumer ignores the rule: the caption is never shown",
     [('        if _eff_report["notice"] and allow_probe:', "        if False:")]),
    ("E10", "over", "the caption is re-sent from every re-activation and step-back",
     [('        if _eff_report["notice"] and allow_probe:',
       '        if _eff_report["notice"]:')]),
    ("E11", "over", "⛔ the press is not passed on, so a stale pre-press read is "
     "reported as the tier",
     [("row_shows=_eff_row_shows, pressed=_eff_option_pressed)",
       "row_shows=_eff_row_shows, pressed=False)")]),
    ("E12", "over", "the landed press is never recorded",
     [("                        _eff_option_pressed = _eff_pressed\n", "")]),
    ("E13", "under", "the consumer reads the glued `text`, not the gap-aware `shows`",
     [('_eff_row_shows = _claude_effort_from_row(_eff_mark.get("shows"))',
       '_eff_row_shows = _claude_effort_from_row(_eff_mark.get("text"))')]),
    ("E14", "under", "the DOM ledger keeps saying only 'tier left as it was'",
     [('            detail=("" if _effort_confirmed else _eff_report["detail"]))',
       '            detail=("" if _effort_confirmed else "tier left as it was"))')]),
    ("E15", "under", "the tier in effect is not recorded with the run's effort state",
     [('                                        "effort_got": _effort_got}',
       '                                        "effort_got": None}')]),
    ("E16", "under", "⛔ the run log never names the tier",
     [("        log(f\"[setup_claude_dr] {_eff_report['log']}\", _eff_report[\"level\"])\n",
       "")]),
]


def _path(fname: str) -> Path:
    return ROOT / fname


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 600


def green():
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q", "-x",
             "-p", "no:cacheprovider", "-rs"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ node is REQUIRED. Half of these mutants live in page JS that only the
    # domshim executes; a skip there would read as "the suite was fine".
    if re.search(r"SKIPPED \[\d+\].*node", out):
        raise SystemExit("⛔ the page-JS tests SKIPPED — node is not on PATH")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE.
    return " failed" not in out and " error" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
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
