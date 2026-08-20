"""Mutation harness for "Gemini's stop signal is two signals".

⛔ THE REPORT: nineteen minutes of `start_research_btn_visible (pre-research)`,
starting ten seconds after the same log said `Clicked 'Start research' ✓
(confirmed it took)` and `Gemini is researching ✓`. The DECISION was right every
tick; the REASON was a lie, and the lie is what the 15-minute no-growth arbiter
met.

⭐ TWO INDEPENDENT MISSES, either of which alone would have prevented it: a
case-SENSITIVE stop selector against `aria-label="Stop response"`, and an
animation tier matching CLASS names while Gemini carries `pulse` in the
ANIMATION NAME.

⭐⭐ AND BOTH OBVIOUS ONE-LINE FIXES WERE WRONG, IN OPPOSITE DIRECTIONS — which
is what most of the over-corrections below are:
  S3 — the hidden stop promoted to a veto. That is the naive `i` fix, and on a
       finished report with a leftover invisible stop it is a 90-minute timeout
       on every Gemini run.
  L1 — the same thing done in the ladder instead of the scan.
  A2 — the name regex dropped, i.e. "any running animation". Gemini's background
       animates FOREVER, so this pins hasRunningWeak true and kills the weakest
       done path permanently.
  V1 — a visibility gate added to verify_gemini_generating, the one probe that
       works BECAUSE it has none.
  H1 — the shim reports every animation as running, which would make every
       executed test below pass against a detector with no playState check.

    .venv/bin/python .mutants/gemini_stop_split_0819_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = "research.py"
SHIM = "tests/_domshim.py"
MUTATED_FILES = [SRC, SHIM]

T_NEW = "tests/test_gemini_stop_split_0819.py"
# ⛔ THE SIBLING SUITES THAT ALSO OWN PROPERTIES OF THIS SOURCE. Reporting "real
# suite gaps" that are nothing but the harness's own scope has happened three
# times in this repo; the decision order and the verbatim pre-research string are
# pinned by 948 and the start-watch wave, not here.
T_948 = "tests/test_completion_determination_948.py"
T_WATCH = "tests/test_gemini_start_watch_0817.py"
T_RELOAD = "tests/test_gemini_reload_and_plan_wait.py"
T_953 = "tests/test_bugs_953.py"
ALL = [T_NEW, T_948, T_WATCH, T_RELOAD, T_953]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 240

# ── shared anchors ──────────────────────────────────────────────────────────
_VIS_TEST = ("                if (b.offsetParent !== null && rect.width > 0 "
             "&& rect.height > 0) {")
_HIDDEN_RUNG = ('        if data.get("hasStopHidden"):\n'
                '            return (False, f"running_hidden_stop_btn (text={text_len})", snap)')
_WEAK_RUNG = ('        if data.get("hasRunningWeak"):\n'
              '            return (False, f"running_weak_signal '
              "({data.get('runningWeakVia') or 'unnamed'}\"\n"
              '                           f", text={text_len})", snap)')
_SEED = '            "gemini_running_confirmed": bool(agent.get("verified")),'
_ANIM_NAME = "                    const nm = String(a.animationName || '');"

MUTANTS: list[tuple[str, str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the stop scan — the original bug and its two wrong fixes ════════════
    ("S1", SRC, "under", "⭐⭐ THE ORIGINAL BUG — the stop match goes back to "
     "case-sensitive, so `aria-label=\"Stop response\"` matches nothing and the "
     "detector is deaf for the whole research again",
     [("            const STOP_RE = /\\\\bstop\\\\b/i;",
       "            const STOP_RE = /\\\\bstop\\\\b/;")],
     [T_NEW]),
    ("S2", SRC, "over", "the veto widens from a word-boundary match to a bare "
     "substring, so any control whose label merely CONTAINS the letters s-t-o-p "
     "can hold a finished report hostage",
     [("            const STOP_RE = /\\\\bstop\\\\b/i;",
       "            const STOP_RE = /stop/i;")],
     [T_NEW]),
    ("S3", SRC, "over", "⛔⛔ THE NAIVE `i` FIX — every stop button counts as "
     "VISIBLE, so the invisible leftover on a finished report vetoes the done "
     "markers and the run times out at ninety minutes",
     [(_VIS_TEST, "                if (true) {")],
     [T_NEW]),
    ("S4", SRC, "under", "the offsetParent half of the visibility gate goes, so a "
     "hidden-but-boxed stop button reads as an on-screen veto",
     [(_VIS_TEST, "                if (rect.width > 0 && rect.height > 0) {")],
     [T_NEW]),
    ("S5", SRC, "under", "the rect half goes, so a collapsed 0×0 stop control that "
     "merely has an offsetParent reads as visible",
     [(_VIS_TEST, "                if (b.offsetParent !== null) {")],
     [T_NEW]),
    ("S6", SRC, "under", "the hidden branch stops recording, so the split exists "
     "in name only and the last resort goes back to claiming pre-research",
     [("                hasStopHidden = true;", "                hasStopHidden = false;")],
     [T_NEW]),
    ("S7", SRC, "under", "`title` stops being read, so a stop button that carries "
     "its label as a tooltip is invisible to us",
     [("                const isStop = STOP_RE.test(al) || STOP_RE.test(ti)",
       "                const isStop = STOP_RE.test(al)")],
     [T_NEW]),
    ("S8", SRC, "under", "the Cancel wordings are dropped from the scan",
     [("                    || al.trim().toLowerCase() === 'cancel'\n"
       "                    || ti.trim().toLowerCase() === 'cancel'\n", "")],
     [T_NEW]),
    ("S9", SRC, "under", "the bare-text wordings are dropped, so an icon-plus-text "
     "Stop button with no aria-label is missed",
     [("                    || txt === 'stop' || txt === 'stop generating' "
       "|| txt === 'cancel';", "                    || false;")],
     [T_NEW]),

    # ══ the animation tier — the second, independent miss ═══════════════════
    ("A1", SRC, "under", "⭐⭐ THE SECOND BUG — the tier goes back to reading the "
     "element's CLASS instead of the animation's NAME, and four visibly pulsing "
     "`item-line` skeletons read as a still page",
     [(_ANIM_NAME, "                    const nm = String((a.effect && a.effect.target "
                   "&& a.effect.target.className) || '');")],
     [T_NEW]),
    ("A2", SRC, "over", "⛔⛔ \"any running animation\" — the name filter goes, so "
     "Gemini's permanent background (morphBG/scaleBG/gradientScroll, running and "
     "viewport-scale on a COMPLETED page) pins the running flag true forever and "
     "the weakest done path can never fire again",
     [("                    if (!RUN_RE.test(nm)) continue;",
       "                    if (false) continue;")],
     [T_NEW]),
    ("A3", SRC, "under", "the visibility gate goes, so the 0×0 circular-progress "
     "animations on a finished page — which DO match the name regex — hold "
     "completion hostage",
     [("                    if (r.width <= 0 || r.height <= 0) continue;",
       "                    if (false) continue;")],
     [T_NEW]),
    ("A4", SRC, "under", "the playState check goes, so a persisted-but-FINISHED "
     "animation reads as live — the exact false positive the 2026-05-14 note "
     "moved these probes off computed styles to avoid",
     [("                    if (a.playState !== 'running') continue;",
       "                    if (false) continue;")],
     [T_NEW]),
    ("A6", SRC, "under", "the reason stops saying WHERE the animation was, which "
     "is the only evidence anyone will have when deciding whether the "
     "response-region scope can safely become a gate",
     [("                        + (inResponse ? ' in-response' : ' page-wide');",
       "                        + '';")],
     [T_NEW]),
    ("A7", SRC, "over", "the scope check is inverted, so the evidence points at "
     "the wrong region and a future gate would be built backwards",
     [("                            'message-content, .model-response-text, model-response'));",
       "                            'body, html, div'));")],
     [T_NEW]),
    ("A5", SRC, "under", "the streaming-attribute tier stops setting the flag, so "
     "a platform state that announces itself outright is ignored",
     [("            )) { hasRunningWeak = true; runningWeakVia = 'streaming-marker'; }",
       "            )) { runningWeakVia = 'streaming-marker'; }")],
     [T_NEW]),
    ("R1", SRC, "under", "`hasStopHidden` never crosses back into Python, so the "
     "whole split is computed and thrown away",
     [("            return { hasStopVisible, hasStopHidden, hasRunningWeak, runningWeakVia,",
       "            return { hasStopVisible, hasRunningWeak, runningWeakVia,")],
     [T_NEW]),

    # ══ the ladder ═════════════════════════════════════════════════════════
    ("L1", SRC, "over", "⛔⛔ the hidden stop is promoted to the hard veto in the "
     "ladder instead of the scan — same 90-minute timeout, one layer up",
     [('        if data.get("hasStopVisible"):\n'
       '            return (False, f"stop_btn_present (text={text_len})", snap)',
       '        if data.get("hasStopVisible") or data.get("hasStopHidden"):\n'
       '            return (False, f"stop_btn_present (text={text_len})", snap)')],
     [T_NEW]),
    ("L2", SRC, "under", "the hidden-stop rung is deleted, so the one running "
     "signal Gemini offers during research stops being reported at all",
     [(_HIDDEN_RUNG, '        if False:\n'
                     '            return (False, f"running_hidden_stop_btn '
                     '(text={text_len})", snap)')],
     [T_NEW]),
    ("L3", SRC, "under", "the weak-running rung is deleted, so a page full of live "
     "skeletons falls through to the Share&Export done path",
     [(_WEAK_RUNG, '        if False:\n'
                   '            return (False, f"running_weak_signal '
                   "({data.get('runningWeakVia') or 'unnamed'}\"\n"
                   '                           f", text={text_len})", snap)')],
     [T_NEW]),
    ("L4", SRC, "under", "the reason stops naming the animation it believed, which "
     "is the only thing that makes a future ambient false-positive a one-grep "
     "diagnosis rather than a code read",
     [("            return (False, f\"running_weak_signal "
       "({data.get('runningWeakVia') or 'unnamed'}\"",
       '            return (False, f"running_weak_signal (unnamed"')],
     [T_NEW]),
    ("L5", SRC, "under", "the hidden stop stops being named in the override list, "
     "so a done verdict that overrode it says nothing about it",
     [('        if data.get("hasStopHidden"):\n'
       '            stale_bits.append("hidden stop-btn overridden")\n', "")],
     [T_NEW]),
    ("L6", SRC, "over", "⛔ the visible-stop veto is deleted — a report still "
     "streaming under a live Stop button gets called finished",
     [('        if data.get("hasStopVisible"):\n'
       '            return (False, f"stop_btn_present (text={text_len})", snap)',
       '        if False:\n'
       '            return (False, f"stop_btn_present (text={text_len})", snap)')],
     [T_NEW, T_948]),
    ("L7", SRC, "under", "the running-confirmed fact is ignored, so the label goes "
     "back to asserting pre-research about a run we watched start",
     [("            if running_confirmed:", "            if False:")],
     [T_NEW]),
    ("L8", SRC, "over", "⛔ the honest label is applied UNCONDITIONALLY, which "
     "deletes the correct account of the 2026-08-17 ninety-minute failure — there "
     "`pre-research` was true once a minute for an hour and a half",
     [("            if running_confirmed:", "            if True:")],
     [T_NEW, T_WATCH]),

    # ══ the wiring — and the WRONG FACT the plan asked for ══════════════════
    ("W1", SRC, "under", "the per-agent fact is never seeded from 2D's own verify, "
     "so an agent confirmed running at launch still gets the lying label",
     [(_SEED, '            "gemini_running_confirmed": bool(False),')],
     [T_NEW]),
    ("W2", SRC, "over", "⛔⛔ THE FACT THE PLAN ASKED FOR — \"Start was confirmed "
     "pressed\". That was TRUE in the ninety-minute failure too (the click "
     "reported success, the verify disagreed), so it cannot tell a run that "
     "started from one that never did",
     [(_SEED, '            "gemini_running_confirmed": bool(\n'
              '                agent.get("verified") or agent.get("needs_start_verify")),')],
     [T_NEW]),
    ("W3", SRC, "under", "the deferred start-verify leg stops recording the "
     "confirmation, so an agent verified one cycle late keeps the false label for "
     "the rest of the run",
     [('                        p["needs_start_verify"] = False\n'
       '                        p["gemini_running_confirmed"] = True',
       '                        p["needs_start_verify"] = False')],
     [T_NEW]),
    ("W4", SRC, "under", "the watch leg stops recording it, so the auto-started "
     "case — research running with no click of ours — keeps the false label",
     [('                        p["gemini_watch_start"] = False\n'
       '                        p["gemini_running_confirmed"] = True',
       '                        p["gemini_watch_start"] = False')],
     [T_NEW]),
    ("W5", SRC, "under", "the fast-confirm re-poll runs the detector WITHOUT the "
     "fact, so the same tick can produce two different labels for one state",
     [('                            dom_done2, dom_reason2, snap2 = await detect_fn(\n'
       '                                p["page"], **_detect_kw)',
       '                            dom_done2, dom_reason2, snap2 = await detect_fn(p["page"])')],
     [T_NEW]),
    ("W6", SRC, "over", "the keyword is handed to every platform — ChatGPT's and "
     "Claude's detectors take no such argument, so this is a TypeError on every "
     "poll of a healthy run",
     [('                _detect_kw = ({"running_confirmed": bool(p.get("gemini_running_confirmed"))}\n'
       '                              if name == "Gemini" else {})',
       '                _detect_kw = {"running_confirmed": bool(p.get("gemini_running_confirmed"))}')],
     [T_NEW]),

    # ══ the probe that works BECAUSE it has no visibility gate ══════════════
    ("V1", SRC, "over", "⛔⛔ the \"obvious missing guard\" is added to "
     "verify_gemini_generating — and it rejects the only evidence there is, so "
     "`[2D] Gemini is researching ✓` never fires on a healthy run again",
     [("            const btns = document.querySelectorAll('button');\n"
       "            for (const b of btns) {\n"
       "                const a = (b.getAttribute('aria-label') || '').toLowerCase();\n"
       "                const t = (b.getAttribute('title') || '').toLowerCase();\n"
       "                const txt = (b.textContent || '').trim().toLowerCase();\n"
       "                if (a.includes('stop') || t.includes('stop') || txt === 'stop') return true;",
       "            const btns = document.querySelectorAll('button');\n"
       "            for (const b of btns) {\n"
       "                if (b.offsetParent === null) continue;\n"
       "                const a = (b.getAttribute('aria-label') || '').toLowerCase();\n"
       "                const t = (b.getAttribute('title') || '').toLowerCase();\n"
       "                const txt = (b.textContent || '').trim().toLowerCase();\n"
       "                if (a.includes('stop') || t.includes('stop') || txt === 'stop') return true;")],
     [T_NEW]),
    ("V2", SRC, "under", "the warning that keeps V1 from being an obvious cleanup "
     "is deleted — the note IS the guard here, because the code looks wrong",
     [("    ⛔⛔ DO NOT ADD A VISIBILITY GATE TO THE BUTTON SCAN BELOW.",
       "    A note about the button scan below.")],
     [T_NEW]),

    # ══ what this wave did NOT fix, and the tempting wrong fix for it ══════
    ("X1", SRC, "over", "⛔⛔ THE TEMPTING WRONG FIX for the 15-minute arbiter — "
     "\"generating\" added to its active-status list. That silences the stuck "
     "arbiter for EVERY platform, because a frozen page reports generating too "
     "(off stale panel steps), which is the exact promote-a-skipped-low shape",
     [('            _active_statuses = ("planning", "thinking", "researching", "searching")',
       '            _active_statuses = ("planning", "thinking", "researching",\n'
       '                                "searching", "generating")')],
     [T_NEW]),
    ("X2", SRC, "under", "the measurement that says the arbiter's status gate is "
     "DEAD is deleted, so the next reader believes it protects something",
     [("            # ⛔⛔ 2026-08-19 — NOT ONE OF THOSE FOUR VALUES IS EVER PRODUCED. All",
       "            # A note about the tuple above. All")],
     [T_NEW]),

    # ══ the shim — because it is what makes the tests above mean anything ═══
    ("H1", SHIM, "over", "⛔⛔ the shim reports every animation as RUNNING, so "
     "every executed test above would pass against a detector with no playState "
     "check at all — the check those probes exist for",
     [("    const state = this._attrs['playstate'] || 'running';",
       "    const state = 'running';")],
     [T_NEW]),
    ("H2", SHIM, "under", "the shim reports no animations at all, so the tier can "
     "never be exercised and the fixtures measure nothing",
     [("    return names.map(n => ({", "    return [].map(n => ({")],
     [T_NEW]),
    ("H3", SHIM, "under", "the document-wide view only looks at the root, so a "
     "skeleton nested anywhere is invisible to it",
     [("  getAnimations: () => [ROOT, ...ROOT.descendants()].flatMap(e => e.getAnimations()),",
       "  getAnimations: () => [ROOT].flatMap(e => e.getAnimations()),")],
     [T_NEW]),
]


def green(tests):
    try:
        # ⛔⛔ MEASURED 2026-08-18: a stale `__pycache__/*.pyc` served OLD bytecode
        # for a source file that had already been fixed, and the measurement
        # disagreed with the file for three rounds. In a harness that rewrites the
        # source between every run, a cached module is not a nuisance — it is a
        # kill or a survivor invented out of nothing.
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def skipped(tests) -> int:
    """How many tests SKIPPED. Every executed-JS test here needs node; a run
    where node is missing would report a clean sweep having measured nothing."""
    try:
        out = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                              *tests], cwd=ROOT, capture_output=True, text=True,
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                             timeout=_TEST_TIMEOUT_S).stdout
    except subprocess.TimeoutExpired:
        return 0
    for line in out.splitlines():
        if "skipped" in line:
            for part in line.replace("=", " ").split(","):
                if "skipped" in part:
                    for tok in part.split():
                        if tok.isdigit():
                            return int(tok)
    return 0


def snapshot():
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before):
    return [f for f, t in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != t]


def main() -> int:
    before = snapshot()
    print("baseline… ", end="", flush=True)
    ok, t_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if t_out else 'RED'}. Nothing below would mean anything.")
        return 2
    n_skip = skipped([T_NEW])
    print(f"green ({n_skip} skipped)", flush=True)
    if n_skip:
        print(f"⚠ {n_skip} test(s) SKIPPED — without node every executed-JS mutant "
              "below measures NOTHING. Fix that before reading the report.")

    survivors, stale = [], []
    for mid, path, direction, why, edits, tests in MUTANTS:
        target = ROOT / path
        original = target.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs 1): {frm[:60]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, t_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed)" if t_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif t_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}", flush=True)
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[2] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
