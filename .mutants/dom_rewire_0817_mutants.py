"""Mutation harness for the 2026-08-17 DOM rewire (ChatGPT picker + Claude effort).

TWO PLATFORMS, ONE SHAPE OF DEFECT: a control moved, the selector kept reporting
something, and nothing downstream could tell "we set it" from "we looked at where
it used to be".

  N* — ChatGPT's picker grew a level. The tier rows are still `menuitemradio`
       rows; they sit one submenu down, behind a row that is only shown once the
       menu is expanded. The picker read the top level, found no tier, and
       stopped. ⛔ The compact state also leaves the Effort row IN THE DOM with a
       real client rect, laid out below the menu's bottom edge — so the
       containment gate is not defensive, it is the difference between pressing
       the row and pressing whatever is behind the menu.
  S* — the scoped read. Ordered hook groups already keep the parent's rows out of
       the RADIO pool, so scope earns its keep on the FALLBACK groups, where the
       parent's "EffortPro" row names the tier without being selectable.
  X* — the post-select confirm was reading an EMPTY trigger, and a hidden
       measuring strip mounted while the picker is open contains "Pro Extended".
  C* — Claude: picking the model CLOSES the popover, so Effort was being looked
       for in a popover that no longer existed.
  L* — the ladder and the validator, which interlock: the outcome check had no
       effort term so it never descended, and the validator's prompt forbade the
       repair. Lifting either alone is worse than lifting neither.

⛔ THE OVER-CORRECTIONS ARE THE HALF THAT MATTER HERE. N2/N7/C2/C4/L2 are all
ways to make this MORE eager — press a clipped row, press an open popover shut,
claim a tier from a press that changed nothing, send every healthy run into the
model popover — and each of those costs money or breaks a run that was fine.

    .venv/bin/python .mutants/dom_rewire_0817_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_SUITES = ("tests/test_chatgpt_picker_walk_0817.py "
               "tests/test_chatgpt_confirm_trigger_0817.py "
               "tests/test_claude_popover_reopen_0817.py "
               "tests/test_claude_effort_submenu_9627.py "
               "tests/test_claude_mode_detect.py "
               "tests/test_prompts_model_policy.py "
               "tests/test_chatgpt_dom_tier.py")

MUTATED_FILES = ("research.py", "models.py", "prompts.py")

SURVIVOR_CONFIRMATIONS = 2

ENV = {**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "")}

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ── N: the ChatGPT picker walk ──────────────────────────────────────────
    ("N1", "research.py", "under",
     "⭐⭐ the containment gate is dropped, so the CLIPPED Effort row is marked "
     "and a real press lands at coordinates outside the menu — on whatever is "
     "behind it",
     [("    if (effortRow && inside(effortRow, menu)) {",
       "    if (effortRow) {")]),

    ("N2", "research.py", "over",
     "⛔ containment is widened until everything is 'inside' — the same clipped "
     "press, reached by a tolerance instead of by a missing check",
     [("        return a.top >= b.top - 1 && a.bottom <= b.bottom + 1 &&",
       "        return a.top >= b.top - 1000 && a.bottom <= b.bottom + 1000 &&")]),

    ("N3", "research.py", "under",
     "⛔ an `aria-controls` id with no element behind it is reported as an open "
     "submenu, handing the caller a scope it cannot read",
     [("        if (sub && document.getElementById(sub)) {",
       "        if (sub) {")]),

    ("N4", "research.py", "under",
     "⛔⛔ the tool-word exclusion goes, so the Deep-Research pill can be taken "
     "for the picker — and pressing that one does not open a menu, it ADDS A "
     "SECOND DEEP RESEARCH",
     [("            if (avoid && t.toLowerCase().indexOf(avoid) !== -1) continue;\n"
       "            const m = document.getElementById(b.getAttribute('aria-controls'));",
       "            const m = document.getElementById(b.getAttribute('aria-controls'));")]),

    ("N5", "research.py", "under",
     "⭐ the row is matched on its WHOLE text rather than its leading label — "
     "'EffortInstant' stops matching 'effort', so the walk binds to the very "
     "value it exists to change",
     [("                                     hasWord(leadLabel(r), P.effortWords));",
       "                                     hasWord(norm(r.textContent), P.effortWords));")]),

    ("N6", "research.py", "over",
     "⛔ the walk presses the same step for ever — a loop of REAL CLICKS on a "
     "live page, which is the one runaway this driver must not become",
     [("        if seen_states.count(state) > 2:",
       "        if False:")]),

    ("N7", "research.py", "under",
     "⭐ the caller never walks — the page script is perfect and nothing asks it, "
     "which is this repo's most repeated failure",
     [("        _scope = await _chatgpt_open_effort_submenu(page, tag=tag, trace=tr)",
       '        _scope = ""')]),

    ("N8", "research.py", "under",
     "⛔⛔ ONE Escape again, so the NESTED submenu closes and the picker is left "
     "sitting over the composer — #751 verbatim on the other platform, and what "
     "triggers the #744 re-click loop on pre-send re-activation. FOUND BY THE "
     "ADVERSARIAL PASS; the whole page-script suite could not see it",
     [("        for _ in range(3):\n"
       "            try:\n"
       "                await page.keyboard.press(\"Escape\")",
       "        for _ in range(1):\n"
       "            try:\n"
       "                await page.keyboard.press(\"Escape\")")]),

    ("N9", "research.py", "over",
     "⛔ Escape is pressed a FIXED number of times instead of until the picker is "
     "actually shut — a keystroke aimed at whatever happens to be focused once "
     "there is nothing left open",
     [("            if not st.get(\"open\"):\n                return",
       "            if False:\n                return")]),

    ("N10", "research.py", "under",
     "⛔⛔ a read of the picker's STRUCTURAL rows is reported as a no-Pro "
     "SUBSCRIPTION, taking a working Pro account down the no-subscription path. "
     "FOUND BY THE ADVERSARIAL PASS",
     [('        if via != "radio":', "        if False:")]),

    ("N11", "research.py", "over",
     "⛔⛔ the no-Pro verdict is never given at all, so a genuinely lapsed or "
     "absent Pro plan is reported as merely `unsure` and the escalation that "
     "exists to surface it never fires. ⚠ This is the direction my FIRST fix for "
     "N10 broke, and an existing test caught it",
     [('        if via != "radio":', "        if True:")]),

    # ── S: the scoped read and click ────────────────────────────────────────
    ("S1", "research.py", "under",
     "⭐ the row read ignores the scope and goes document-wide again, so the "
     "parent's 'EffortPro' row is ranked against the real tier row whenever the "
     "read falls to the fallback hook groups",
     [("    const root = P.scope ? document.getElementById(P.scope) : document;\n"
       "    if (P.scope && !root) return { via: '', rows: [], rejected: 0, seen_used: [],\n"
       "                                   scope_gone: true };",
       "    const root = document;")]),

    ("S2", "research.py", "over",
     "⛔ a VANISHED scope silently widens to the document — a submenu that closed "
     "under us becomes a read of whatever else is on screen, which is the exact "
     "mis-aim the parameter exists to prevent",
     [("    const root = P.scope ? document.getElementById(P.scope) : document;\n"
       "    if (P.scope && !root) return { clicked: false, reason: 'scope_gone' };",
       "    const root = document;")]),

    ("S3", "research.py", "under",
     "⛔ the click re-resolves its index against a DIFFERENT set than the read "
     "ranked — clicking by position alone is the mis-click the leaf work was about",
     [('                                       "seen": _seen_used, "scope": _scope,',
       '                                       "seen": _seen_used, "scope": "",')]),

    # ── X: the post-select confirm ──────────────────────────────────────────
    ("X1", "research.py", "under",
     "⭐ the trigger fallback goes and the confirm is back to reading '' — every "
     "branch below then decides from an empty string, which is the live log",
     [("            if (!mtrig) {\n"
       "                const avoid = norm(P.avoid || '').toLowerCase();",
       "            if (false) {\n"
       "                const avoid = norm(P.avoid || '').toLowerCase();")]),

    ("X2", "research.py", "over",
     "⛔⛔ the marker scan runs while the picker is OPEN, so the hidden measuring "
     "strip's 'Pro Extended' pins the verdict to 'extended' whatever the live "
     "mode is — an INVERTED detection, not a missed one",
     [("            const extMark = pickerOpen ? null : markCands",
       "            const extMark = markCands")]),

    ("X3", "research.py", "under",
     "⛔ the tool word is dropped from the confirm's fallback, so the "
     "Deep-Research pill beside it can answer as the mode trigger",
     [("                    if (!t || t.length > 40) return false;\n"
       "                    return !(avoid && t.toLowerCase().indexOf(avoid) !== -1);",
       "                    if (!t || t.length > 40) return false;\n"
       "                    return true;")]),

    # ── C: Claude's popover and effort ──────────────────────────────────────
    ("C1", "research.py", "under",
     "⭐⭐ the popover is not re-opened after a model pick, so Step 1C searches a "
     "popover that no longer exists — the defect this wave root-caused",
     [("            if _model_changed and not _effort_already_known:",
       "            if False and _model_changed and not _effort_already_known:")]),

    ("C2", "research.py", "over",
     "⛔ the popover is re-opened on EVERY run, including the ones that skipped "
     "it deliberately — churn the #744 work removed",
     [("            if _model_changed and not _effort_already_known:",
       "            if True:")]),

    ("C3", "research.py", "over",
     "⛔⛔ an ALREADY-OPEN popover is pressed, which CLOSES it — the helper "
     "creating the exact state it exists to repair, on the runs that were fine",
     [('    if str(marked.get("expanded")) == "true":\n        return True',
       "    if False:\n        return True")]),

    ("C4", "research.py", "over",
     "⛔ the re-open reports success without verifying it opened — 'the click did "
     "not throw' as evidence, which is the equivalence three waves removed",
     [('        if st.get("expanded"):\n            return True\n    return False',
       "        return True\n    return False")]),

    ("C5", "research.py", "under",
     "⭐⭐ 'extra' maps to its LABEL rather than its captured id — addressing "
     "nothing, silently, one rung below the tier we asked for",
     [('             "extra": "xhigh", "extra high": "xhigh", "xhigh": "xhigh",',
       '             "extra": "extra", "extra high": "extra", "xhigh": "xhigh",')]),

    ("C6", "research.py", "over",
     "⛔ an unknown effort word CONSTRUCTS a test id, so the page script "
     "addresses an element that does not exist and its text fallback never runs",
     [('    return f"effort-option-{slug}" if slug else ""',
       '    return f"effort-option-{slug or word}"')]),

    ("C7", "research.py", "over",
     "⛔⛔ the effort row is pressed and CLAIMED without checking it became the "
     "selected one — a press that lands and changes nothing reports success. "
     "⚠ RE-AIMED: the first version of this mutant SURVIVED, because the verdict "
     "was a statement nothing observed rather than a value something held",
     [("    return bool(pressed and checked)", "    return bool(pressed)")]),

    ("C7b", "research.py", "over",
     "⛔ the verification's ANSWER is replaced by a constant at the call site — "
     "the pure function stays correct and stops being asked",
     [("                        pressed=_eff_pressed, checked=_eff_checked)",
       "                        pressed=_eff_pressed, checked=True)")]),

    ("C7c", "research.py", "under",
     "⛔ an ALREADY-selected tier is pressed anyway, which on a radio row that is "
     "already the answer is a click for nothing and on some components a toggle",
     [("    if already:\n        return True", "    if False:\n        return True")]),

    ("C7d", "research.py", "under",
     "⛔ a row that was never FOUND still reports a set tier — 'not found' has to "
     "outrank everything, since there is nothing to press and nothing to verify",
     [("    if not marked:\n        return False", "    if False:\n        return False")]),

    ("C8", "research.py", "under",
     "⛔ the page script goes back to clicking the row from inside "
     "`page.evaluate` — a synthetic click this component library does not act on",
     [("                        if (!already) pick.setAttribute(P.attr, P.value);",
       "                        if (!already) pick.click();")]),

    # ── L: the ladder and the validator, which interlock ────────────────────
    ("L1", "research.py", "under",
     "⭐⭐ the ladder drops the effort term, so a missed tier still reads as a "
     "satisfied outcome and vision_cua + cua_validate are both skipped",
     [('            return ("on" if (st.get("hasExtended") and st.get("researchOn")\n'
       '                             and st.get("effortOk")) else "unknown")',
       '            return ("on" if (st.get("hasExtended") and st.get("researchOn")\n'
       '                             ) else "unknown")')]),

    ("L2", "research.py", "over",
     "⛔⛔ the PRE-SEND check gates on effort too — re-running the entire Claude "
     "setup, model popover and all, seconds before the brief is submitted",
     [('            if reactivate and (not state.get("hasExtended") or not state.get("researchOn")):',
       '            if reactivate and (not state.get("hasExtended") or not state.get("researchOn")\n'
       '                               or not state.get("effortOk")):')]),

    ("L3", "research.py", "under",
     "⛔ the effort is read PAGE-WIDE rather than off the winning trigger — this "
     "account's plan chip also says 'Max', so effort-is-set on every page",
     [("        const label = (trigger.getAttribute('aria-label') || '') + ' '\n"
       "                    + (trigger.textContent || '');",
       "        const label = document.body.innerText || '';")]),

    ("L3b", "research.py", "under",
     "⛔⛔ the effort word is not required, so an EMPTY word reads as a set tier — "
     "the live trigger ends in a chevron ICON, a trailing non-alphanumeric makes "
     "`split` emit an empty token, and `indexOf('')` finds it. "
     "⚠ HISTORY: a `.filter(Boolean)` was added here as a 'fix' and announced as "
     "a real bug found by mutation. It was NOT a bug — the guard already covered "
     "it, the two were redundant, and that is precisely why NEITHER could be "
     "killed while the other stood. Measured: the false reading needs BOTH gone. "
     "The redundant line was removed so this guard is the one that answers",
     [("    if (trigger && ew) {", "    if (trigger) {")]),

    ("L3c", "research.py", "over",
     "⛔ the test id alone is taken as evidence of the family, so an upsell chip "
     "carrying it would answer as the selected model",
     [("        if (!famRe.test(t) || upsellRe.test(t)) trigger = null;",
       "        if (false) trigger = null;")]),

    ("L4", "research.py", "over",
     "⛔ the validator is told the tier is fine on EVERY run, so the rung the "
     "ladder now descends to is once again forbidden to repair it",
     [("    return bool((thinking_state or {}).get(\"effort\", True))",
       "    return True")]),

    ("L5", "research.py", "under",
     "⛔ the polarity is inverted: the validator goes fixing on the runs that "
     "were already correct and stands down on the ones that were not",
     [("    return bool((thinking_state or {}).get(\"effort\", True))",
       "    return not bool((thinking_state or {}).get(\"effort\", True))")]),

    ("L6", "prompts.py", "under",
     "⛔ the system prompt keeps its blanket ban, so the permission the run "
     "computed never reaches the agent",
     [("        if effort_ok else\n"
       "        f'That button ALSO shows the effort right on it, and on THIS run it does '",
       "        if True else\n"
       "        f'That button ALSO shows the effort right on it, and on THIS run it does '")]),

    ("L7", "models.py", "under",
     "⛔ the USER message keeps saying 'verify' while the system prompt says "
     "'fix' — one CUA call holding two instructions that disagree",
     [("    if not effort_ok:", "    if False:")]),
]


def run_tests() -> bool:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *ROOT_SUITES.split(), "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, env=ENV,
    )
    return r.returncode == 0


def snapshot() -> dict:
    """The exact bytes of every file this harness will mutate.

    ⛔⛔ WHY NOT `git status`. The sibling harnesses ask git whether the tree is
    clean, which answers a DIFFERENT question when the wave being tested is itself
    uncommitted: every one of these files is legitimately modified, so the check
    reports "not clean" on every run and means nothing. It reported exactly that
    here, and it would have said the same thing whether or not a mutant was still
    sitting in the source.

    ⭐ That is not hypothetical. This harness was once killed by an external
    timeout between "write the mutant" and the `finally` that restores it, and it
    left a live mutant in `research.py` — the Claude popover re-open rewritten to
    fire on every run. It was caught by hand. Comparing against bytes taken at
    START is the check that would have caught it by itself.
    """
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before: dict) -> list[str]:
    return [f for f, text in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != text]


def main() -> int:
    before = snapshot()
    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    survivors = []
    for mid, fname, direction, why, edits in MUTANTS:
        path = ROOT / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                # ⛔⛔ UNIQUENESS, NOT MERE PRESENCE. A substring match once hit a
                # function 2,300 lines away and reported a gap that did not exist.
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor — this mutates nothing")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests()
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                killed = not run_tests()
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, f"HARNESS FAULT — measured nothing: {why}"))
        finally:
            path.write_text(original, encoding="utf-8")

    # ⛔ Compared against the bytes taken at START, not against git — see
    # `snapshot`. A wave under test is uncommitted, so git cannot tell this
    # harness's leftovers from the work it is measuring.
    leftover = drifted(before)
    if leftover:
        print("\n⛔ A MUTANT IS STILL IN YOUR SOURCE — these files did not come back:\n"
              + "\n".join(f"  {f}" for f in leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[2] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
