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

⛔⛔ AND THE THIRD (R, T, P, K): the owner-approved capture of 2026-09-23 showed
the Effort row inside the `role="menu"` popover with NO test id — the id Step 1C
used both to find the row and to tell the popover from the submenu. The quiet ones:

  R1   — the row search walks the DOCUMENT again; the sidebar comes first.
  R6   — the picker searches the popover first, and its miss names the POPOVER's
         rows: exactly the 09-20 log line nobody could diagnose from.
  R7-R9 — the consumer ignores the rule: one call site is not handed the mark.
  R13  — the Thinking policy lever is lost behind the row read.
  R14  — any read of the row confirms Max: a Low run reported as Max.
  T1   — the post-computer-use button read is never passed to the telemetry line.
  K1   — the shim's kept document is the one it was GIVEN, so every chained
         test here would measure nothing.

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

SUITES = ("tests/test_claude_real_popover_0923.py "
          "tests/test_drift_review_0805.py "
          "tests/test_model_selection_precision.py "
          "tests/test_known_good_fallback.py "
          "tests/test_claude_popover_skip.py "
          "tests/test_model_policy.py "
          "tests/test_prompts_model_policy.py "
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
    # ⚠ RE-ANCHORED 2026-09-23: the sentence is now models.VERSION_ORDER_RULE,
    # shared with the system prompt that rides in the same call (P1-P4 below).
    ("M16", "under", "the computer-use fallback loses the 'ten after nine' rule",
     [('f"one, close the menu without clicking it. {VERSION_ORDER_RULE} "\n',
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
    # (repair 1: the source pins that covered G7/G8/P7/P8 were deleted this wave
    # and nothing executed replaced them — both survived every model suite.)
    ("G7", "under", "⛔ Gemini's step-back takes a VERSION-LESS row ('Flash Newest', "
     "maybe the model that just failed, renamed) and spends the one retry on it",
     [("\n                if (k === null || cmpVer(k, bound) >= 0) continue;",
       "\n                if (k !== null && cmpVer(k, bound) >= 0) continue;")]),
    ("G8", "under", "Gemini's retired pin bounds the step-back instead of the "
     "failed version: 3.1 is picked over 3.9, a deeper downgrade than needed",
     [("\n                const bound = belowK !== null ? belowK : pinK;",
       "\n                const bound = pinK !== null ? pinK : belowK;")]),

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
    ("P7", "under", "⛔ the Claude step-back takes a VERSION-LESS row ('Opus Newest') "
     "and spends the one retry on it",
     [("                        if (k === null || cmpVer(k, bound) >= 0) continue;",
       "                        if (k !== null && cmpVer(k, bound) >= 0) continue;")]),
    ("P8", "under", "the Claude retired pin bounds the step-back instead of the "
     "failed version",
     [("                        const bound = belowK !== null ? belowK : pinK;",
       "                        const bound = pinK !== null ? pinK : belowK;")]),

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
    # ── the consumer: the pre-send check in start_agent_no_gemini_wait ─────
    # (repair 1: moved out of setup_claude_dr, which posted it BEFORE the
    # computer-use pass that is told to set the tier, and never corrected it)
    ("E9", "under", "⛔ the consumer ignores the rule: the caption is never shown",
     [("                if _eff_caption:\n", "                if False:\n")]),
    ("E10", "over", "⛔ the caption says Low after the computer-use pass set Max",
     [('                    if _eff_after["missing"] else None)',
       "                    if True else None)")]),
    ("E18", "over", "⛔ the caption goes up in setup again, before the computer-use "
     "pass is even asked to set the tier",
     [('        _P2_THINKING_STATE["claude"] = {"effort": _effort_confirmed, '
       '"thinking": _thinking_confirmed,',
       '        if _eff_report["notice"] and allow_probe:\n'
       '            emit_event("agent_progress", phase=2, agent="claude", '
       'status="starting", progress=_eff_report["notice"])\n'
       '        _P2_THINKING_STATE["claude"] = {"effort": _effort_confirmed, '
       '"thinking": _thinking_confirmed,')]),
    ("E19", "over", "⛔ the effort state outlives the setup that wrote it: a setup "
     "that stops early names the LAST run's tier",
     [('    _P2_PICKED_VERSION.pop("claude", None)\n'
       '    _P2_THINKING_STATE.pop("claude", None)\n',
       '    _P2_PICKED_VERSION.pop("claude", None)\n')]),
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

    # ══ task 3 — Step 1C against the REAL 2026-09-23 popover ══════════════
    # ── the Effort row is found inside an open menu, never on the page ─────
    ("R1", "over", "⛔⛔ the text search walks the DOCUMENT again: the sidebar "
     "button that precedes the portalled popover is the row pressed",
     [("                            for (const el of m.querySelectorAll(\n"
       "                                    '[role=\"menuitem\"], button, [role=\"option\"], li')) {",
       "                            for (const el of document.querySelectorAll(\n"
       "                                    '[role=\"menuitem\"], button, [role=\"option\"], li')) {")]),
    ("R2", "over", "the test id is resolved anywhere on the page again",
     [("                            for (const el of m.querySelectorAll(\n"
       "                                    '[data-testid=\"' + P.testid + '\"]')) {",
       "                            for (const el of document.querySelectorAll(\n"
       "                                    '[data-testid=\"' + P.testid + '\"]')) {")]),
    ("R3", "under", "⛔ the chosen row is never marked for the probe and the picker, "
     "so today's popover (no test id) reads as a submenu again",
     [("                        if (P.rowAttr) trigger.setAttribute(P.rowAttr, '1');\n", "")]),
    ("R4", "over", "a row mark from an earlier pass survives and names the wrong menu",
     [("                        for (const el of document.querySelectorAll('[' + P.rowAttr + ']')) {\n"
       "                            el.removeAttribute(P.rowAttr);\n",
       "                        for (const el of []) {\n"
       "                            el.removeAttribute(P.rowAttr);\n")]),
    # The 08-05 guards, now measured INSIDE a menu (test_drift_review_0805 was
    # re-anchored: outside a menu nothing is a candidate). Arm 1 of `linky` is
    # left out on purpose — `closest` includes the element itself, so arm 2
    # already covers a bare anchor and removing arm 1 is an equivalent mutant.
    ("D2", "over", "a row nested INSIDE a link is pressed — a navigation",
     [("\n                        || (el.closest && el.closest('a[href]'))\n", "\n")]),
    ("D3", "over", "an `li` WRAPPING a conversation link is pressed — a navigation",
     [("\n                        || (el.querySelector && el.querySelector('a[href]'));",
       ";")]),
    ("D4", "over", "⛔ links inside the menu are candidates again",
     [("if (linky(el)) { rejected.push(['link', t.slice(0, 60)]); continue; }", "")]),
    ("D5", "over", "prose starting 'Effort…' inside a menu is the row pressed",
     [("if (t.length > 40) { rejected.push(['long', t.slice(0, 60)]); continue; }", "")]),
    # ── the popover is excluded from the submenu, by the mark ──────────────
    ("R5", "under", "⛔ the probe ignores the mark: the popover alone reads 'maybe' "
     "and the picker runs against it",
     [("\n                        || (P.rowAttr && c.querySelector('[' + P.rowAttr + ']'))),",
       "),")]),
    ("R6", "under", "⛔⛔ the picker ignores the mark: it searches the popover first "
     "and its miss names the POPOVER's rows — the 09-20 log line",
     [("\n                            && !(P.rowAttr && m.querySelector('[' + P.rowAttr + ']')));",
       ");")]),
    ("R7", "under", "⛔ the consumer ignores the rule: the marker is never asked to "
     "write the row mark",
     [('                       "testid": _CLAUDE_EFFORT_TRIGGER_TESTID,\n'
       '                       "rowAttr": _CLAUDE_EFFORT_ROW_ATTR}) or {}',
       '                       "testid": _CLAUDE_EFFORT_TRIGGER_TESTID}) or {}')]),
    ("R8", "under", "⛔ the consumer ignores the rule: the probe is not handed the mark",
     [('                                 "rowAttr": _CLAUDE_EFFORT_ROW_ATTR,\n', "")]),
    ("R9", "under", "⛔ the consumer ignores the rule: the picker is not handed the mark",
     [('}""", {"trigTestid": _CLAUDE_EFFORT_TRIGGER_TESTID,\n'
       '                           "rowAttr": _CLAUDE_EFFORT_ROW_ATTR,\n',
       '}""", {"trigTestid": _CLAUDE_EFFORT_TRIGGER_TESTID,\n')]),
    # ── a miss is loud: the submenu's own rows, long ones cut not dropped ──
    ("R10", "under", "a submenu row with a description is dropped from the miss "
     "report, which comes back empty",
     [("const fromMenu = pools.length > 0 && pools[0] !== document;",
       "const fromMenu = false;")]),
    ("R11", "over", "⛔ the long-row report reaches the DOCUMENT pool: the user's "
     "own conversation goes into the log",
     [("const fromMenu = pools.length > 0 && pools[0] !== document;",
       "const fromMenu = pools.length > 0;")]),
    # ── the row already shows the tier: nothing is set ─────────────────────
    ("R12", "under", "⛔ the consumer ignores the rule: a row reading Max still sends "
     "the run into the uncaptured submenu",
     [("                if _eff_marked and not _claude_wants_thinking \\\n",
       "                if False and _eff_marked and not _claude_wants_thinking \\\n")]),
    ("R13", "over", "⛔ the Thinking policy lever is lost: with `thinking` on, the "
     "row read skips the submenu the toggle lives in",
     [("                if _eff_marked and not _claude_wants_thinking \\\n",
       "                if _eff_marked \\\n")]),
    ("R14", "over", "⛔⛔ ANY read of the row confirms the wanted tier — a Low run "
     "is reported as Max",
     [('    return bool(w) and str(row_shows or "").strip().lower() == w',
       "    return bool(w) and bool(row_shows)")]),
    ("R15", "over", "no wanted tier is 'confirmed' by an empty row",
     [('    return bool(w) and str(row_shows or "").strip().lower() == w',
       '    return str(row_shows or "").strip().lower() == w')]),
    # (repair 1: the old R16, `_effort_already_known` for `_effort_confirmed`,
    # became equivalent once a marked row can never reach this line; re-aimed
    # at the half that still decides — the trigger-confirmed run, never marked.)
    ("R16", "over", "a trigger-confirmed run still logs 'Effort control not found'",
     [("                elif not _effort_confirmed and not _eff_marked:\n",
       "                elif not _eff_marked:\n")]),
    ("R19", "over", "⛔ a row that was found and PRESSED is then reported as 'not "
     "found' — the wrong diagnosis, one line after the right one",
     [("                elif not _effort_confirmed and not _eff_marked:\n",
       "                elif not _effort_confirmed:\n")]),
    ("R20", "under", "a menu with no Effort row at all no longer says so",
     [("                elif not _effort_confirmed and not _eff_marked:\n",
       "                elif False:\n")]),
    ("R17", "under", "the click mark is left on the row nobody pressed",
     [("                    try:\n"
       "                        await page.evaluate(_SR_UNMARK_JS, {\"attr\": _SR_CLICK_MARK})\n"
       "                    except Exception:\n"
       "                        pass\n"
       "                elif _eff_marked:",
       "                    pass\n"
       "                elif _eff_marked:")]),
    ("R18", "under", "the ledger cannot tell a row read from a submenu set",
     [('                    _effort_via = "row"\n', '                    _effort_via = "submenu"\n')]),

    # ══ after the computer-use pass: the telemetry line says what is known ═
    ("T1", "under", "⛔ the consumer ignores the rule: the post-CUA button read is "
     "never passed, so a tier the CUA pass set is still 'unconfirmed'",
     [('                    bool((mode_state or {}).get("effortOk")))',
       "                    False)")]),
    ("T2", "under", "⛔ the pre-send check drops the button read on the way out",
     [('                    "effortOk": bool(state.get("effortOk"))}',
       "                    }")]),
    ("T3", "under", "the tier setup read is never named — 'unconfirmed' again",
     [("    if got:\n        return {\"missing\": f\"effort is '{got}', not the '{w}' wanted\", \"note\": None}\n",
       "")]),
    ("T4", "under", "the button read is ignored",
     [("    if button_shows_wanted:\n", "    if False:\n")]),
    ("T5", "under", "the post-CUA confirmation is computed and never said",
     [("                    log(f\"[{label}] Phoenix: {_eff_after['note']}\", \"INFO\")\n",
       "                    pass\n")]),
    ("T6", "over", "a row that read the wanted tier is reported as 'not the wanted'",
     [("    if got == w:\n        return {\"missing\": None, \"note\": None}\n", "")]),
    ("T7", "over", "a tier setup CONFIRMED is reported as unconfirmed",
     [('    if not w or st.get("effort"):', "    if not w:")]),

    # ══ the computer-use missions read "highest" by ORDER ════════════════
    ("P1", "under", "⛔ the system prompt that rides with the setup directive loses "
     "the rule — two readings of 'highest' in one call",
     [("close the menu without clicking it. {VERSION_ORDER_RULE} {no_upsell} In that SAME",
       "close the menu without clicking it. {no_upsell} In that SAME")], "prompts.py"),
    ("P2", "under", "the validator loses the rule",
     [('pick the highest-numbered "{fam}", and close it. {VERSION_ORDER_RULE} {no_upsell}',
       'pick the highest-numbered "{fam}", and close it. {no_upsell}')], "prompts.py"),
    ("P3", "under", "ChatGPT's tier mission loses the rule",
     [("        f'highest-numbered one. {VERSION_ORDER_RULE} Ignore any {cta} button — '",
       "        f'highest-numbered one. Ignore any {cta} button — '")], MODELS),
    ("P4", "under", "⛔ the rule reads versions as DECIMALS",
     [('"after the dot is NEWER than nine after the dot."',
       '"after the dot is OLDER than nine after the dot."')], MODELS),

    # ══ the harness that measures the above: the shim keeps the document ══
    ("K1", "under", "⛔⛔ the 'kept' document is the one the script was GIVEN — "
     "every mark evaporates between scripts and the chained tests measure nothing",
     [("  return { ret: out.ret, clicks: out.clicks, dom: toSpec(ROOT) };",
       "  return { ret: out.ret, clicks: out.clicks, dom: spec };")], "tests/_domshim.py"),
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
