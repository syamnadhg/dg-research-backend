"""Mutation harness for "the gate that vetoed a submenu it could see".

⛔ THE REPORT (owner's e2e, 2026-08-17): Claude's Effort submenu WAS open — the
step's own diagnostic printed it, five rows, Low/Medium/HighDefault/Extra/Max —
and the line above the diagnostic said "submenu never mounted". Effort silently
stayed at the model's default for the whole phase while telemetry reported it
unconfirmed. The gate listed every short visible row in the DOCUMENT, capped the
list at 20, and got the sidebar: Claude portals its popper to the end of `<body>`.

⭐ THE OVER-CORRECTIONS ARE THE SHARP END, because the repair WIDENS what runs:
  E4  — the popover stops being excluded, so the menu that HOLDS the trigger can
        satisfy the gate; the picker then presses inside it.
  E15 — the page-wide Thinking search rides along with the widened effort
        attempt, clicking an unscoped switch on a page whose submenu never opened.
  E17 — the verdict is hardcoded open, so everything nested runs against a closed
        menu — the 2026-08-04 defect, restored.
  E22 — the picker searches the trigger's own menu, whose Effort row DISPLAYS the
        selected tier: it marks the display, presses it, re-opens the submenu, and
        reports the tier as set.
  E26 — the document fallback regains its page-wide text search, which is the
        decoy press ("Max" as a list item in Claude's own reply) this file has
        already paid for once.

    python .mutants/claude_effort_gate_0817_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_claude_effort_gate_0817.py"
T_SUB = "tests/test_claude_effort_submenu_9627.py"
T_SKIP = "tests/test_claude_popover_skip.py"
T_PICK = "tests/test_claude_model_pick.py"
ALL = [T_NEW, T_SUB, T_SKIP, T_PICK]

PY = str(ROOT / ".venv" / "bin" / "python")

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ── the verdict ─────────────────────────────────────────────────────────
    ("E1", "under", "⭐ the option's own test id stops being enough, so a UI that "
     "renames its rungs (or ships them in another language) reads as closed",
     [('        if o.get("option"):\n            return "open"',
       '        if False:\n            return "open"')],
     [T_NEW]),
    ("E2", "over", "one rung is enough — a lone 'max' in a tooltip or a toast now "
     "satisfies a gate that exists to see a five-row radio group",
     [("        if rungs >= 2:", "        if rungs >= 1:")],
     [T_NEW]),
    ("E3", "under", "three rungs are demanded, so a menu that relabels one rung "
     "stops being recognised",
     [("        if rungs >= 2:", "        if rungs >= 3:")],
     [T_NEW]),
    ("E4", "over", "⛔⛔ THE POPOVER STOPS BEING EXCLUDED — the menu that HOLDS the "
     "Effort trigger can satisfy the gate, and it displays the selected tier",
     [('    candidates = [o for o in overlays if not o.get("trigger")]',
       '    candidates = list(overlays)')],
     [T_NEW]),
    ("E5", "over", "every page reads as 'maybe', so the picker runs against a "
     "page with nothing open at all",
     [('    return "maybe" if candidates else "closed"', '    return "maybe"')],
     [T_NEW]),
    ("E6", "under", "'maybe' collapses into 'closed' — the blind veto is back, "
     "which is the reported bug",
     [('    return "maybe" if candidates else "closed"', '    return "closed"')],
     [T_NEW, T_SKIP]),
    ("E7", "over", "an unreadable rung count reads as many, so any overlay "
     "whose count came back malformed is called an open submenu",
     [("            rungs = 0\n        if rungs >= 2:", "            rungs = 99\n        if rungs >= 2:")],
     [T_NEW]),

    # ── the probe ───────────────────────────────────────────────────────────
    ("E8", "under", "only `[role=menu]` counts as an overlay — the captured box "
     "carried `data-side` and an id, and a component library is free to drop the "
     "role from a portalled popper",
     [("""            '[role="menu"], [data-radix-menu-content], '
            + '[data-radix-popper-content-wrapper]')) {""",
       """            '[role="menu"]')) {""")],
     [T_NEW]),
    ("E9", "under", "the icon-font private-use glyphs stop being stripped, so "
     "the SELECTED rung — the one that carries them — no longer counts",
     [("""    const norm = s => (s || '')
        .replace(/[\\ue000-\\uf8ff]/g, ' ')
        .replace(/\\s+/g, ' ').trim().toLowerCase();
    const RUNGS = ['low', 'medium', 'high', 'extra', 'max', 'xhigh'];""",
       """    const norm = s => (s || '')
        .replace(/\\s+/g, ' ').trim().toLowerCase();
    const RUNGS = ['low', 'medium', 'high', 'extra', 'max', 'xhigh'];""")],
     [T_NEW]),
    ("E10", "under", "'HighDefault' stops counting as a rung — the default rung "
     "carries that suffix, so every menu scores one lower",
     [("    const isRung = t => RUNGS.indexOf(t) !== -1 ||\n"
       "                        RUNGS.some(r => t === r + 'default');",
       "    const isRung = t => RUNGS.indexOf(t) !== -1;")],
     [T_NEW]),
    ("E11", "over", "a mounted-but-hidden menu counts as open — component "
     "libraries keep a collapsed menu in the DOM",
     [("        if (!c.getClientRects().length) continue;\n        if (seen.has(c)) continue;",
       "        if (seen.has(c)) continue;")],
     [T_NEW]),
    ("E12", "over", "⛔ the trigger and the option test ids are swapped, so the "
     "SUBMENU is the overlay that gets excluded",
     [("""            trigger: !!(P.trigTestid &&
                        c.querySelector('[data-testid="' + P.trigTestid + '"]')),""",
       """            trigger: !!(P.optTestid &&
                        c.querySelector('[data-testid="' + P.optTestid + '"]')),""")],
     [T_NEW]),

    # ── the wiring ──────────────────────────────────────────────────────────
    ("E13", "under", "the poll stops at the first 'maybe', so a submenu that "
     "mounts a beat later is never confirmed and the Thinking probe is skipped "
     "on a page that was about to be fine",
     [('                        if _eff_state == "open":\n                            break',
       '                        if _eff_state != "closed":\n                            break')],
     [T_NEW]),
    ("E14", "under", "⭐ the gate can veto the picker again — 'maybe' stops "
     "reaching Step 1C', which is the whole shape of the reported failure",
     [('                if _eff_state != "closed":\n                    await asyncio.sleep(0.5)',
       '                if _eff_opened:\n                    await asyncio.sleep(0.5)')],
     [T_NEW, T_SKIP]),
    ("E15", "over", "⛔⛔ the page-wide Thinking search rides along with the "
     "widened effort attempt — an unscoped click on a page whose submenu may "
     "never have opened",
     [("                    _think_probed = bool(_claude_wants_thinking and _eff_opened)",
       '                    _think_probed = bool(_claude_wants_thinking and _eff_state != "closed")')],
     [T_SKIP]),
    ("E16", "under", "the diagnostic loses the ancestry again — 'what did we "
     "press?' goes back to being unanswerable, which is how this shipped",
     [('                            _eff_dbg["pressed_chain"] = _eff_mark.get("chain") or []',
       '                            pass')],
     [T_NEW]),
    ("E17", "over", "⛔⛔ the verdict is hardcoded open — everything nested in the "
     "submenu runs against a menu that never mounted, the 2026-08-04 defect",
     [("                        _eff_state = _claude_effort_submenu_verdict(_eff_probe)",
       '                        _eff_state = "open"')],
     [T_SKIP]),
    ("E18", "under", "the poll takes a single look, so a submenu that animates "
     "in is missed on every run",
     [("                    for _try in range(8):\n                        if _try:\n"
       "                            await asyncio.sleep(0.25)\n                        try:\n"
       "                            _eff_probe = await page.evaluate(",
       "                    for _try in range(1):\n                        if _try:\n"
       "                            await asyncio.sleep(0.25)\n                        try:\n"
       "                            _eff_probe = await page.evaluate(")],
     [T_SKIP]),
    ("E19", "under", "the mark pass stops capturing the ancestry, so the "
     "diagnostic has nothing to carry",
     [("                        const chain = [];\n"
       "                        for (let el = trigger, i = 0; el && i < 8; i++, el = el.parentElement) {\n"
       "                            chain.push(desc(el));\n                        }",
       "                        const chain = [];")],
     [T_NEW]),

    # ── the picker ──────────────────────────────────────────────────────────
    ("E20", "under", "'HighDefault' stops matching, so the default rung cannot "
     "be selected by text at all",
     [("                            return !!want && (t === want || t === want + ' effort'\n"
       "                                              || t === want + 'default');",
       "                            return !!want && t === want;")],
     [T_NEW]),
    ("E21", "over", "⛔ an empty policy word matches an empty label — the picker "
     "presses whichever icon-only row comes first",
     [("                            return !!want && (t === want || t === want + ' effort'",
       "                            return (t === want || t === want + ' effort'")],
     [T_NEW]),
    ("E22", "over", "⛔⛔ the picker searches the trigger's OWN menu, whose Effort "
     "row displays the selected tier — it marks the display, and the caller "
     "reports a tier set from a submenu that never opened",
     [("                        const pools = cands.length\n"
       "                            ? cands\n"
       "                            : (menus.length ? [] : [document]);",
       "                        const pools = cands.length\n"
       "                            ? cands\n"
       "                            : [menus[menus.length - 1] || document];")],
     [T_NEW, T_SUB]),
    ("E23", "under", "only the FIRST candidate overlay is searched — the row is "
     "reported missing from a page that is showing it, the same wrong-sink shape "
     "as the gate",
     [("                        const pools = cands.length\n                            ? cands\n",
       "                        const pools = cands.length\n                            ? [cands[0]]\n")],
     [T_NEW]),
    ("E24", "over", "the tier goes back to a literal 'max', so every other "
     "policy tier silently selects nothing on the layout without ids",
     [("                            if (!hit && allowText) hit = rows.find(isWanted);",
       "                            if (!hit && allowText) hit = rows.find(el => norm(el.textContent) === 'max');")],
     [T_NEW]),
    ("E25", "under", "the call site stops handing the policy tier to the page "
     "script, so `want` is empty and the text fallback matches nothing",
     [('                           "word": str(_claude_effort or "").lower(),', '')],
     [T_NEW]),
    ("E26", "over", "⛔⛔ the document fallback regains its page-wide TEXT search "
     "— the decoy press: Claude's own reply renders a list item reading 'Max'",
     [("                        const allowText = cands.length > 0;",
       "                        const allowText = true;")],
     [T_NEW]),

    # ── the read-back ───────────────────────────────────────────────────────
    ("E27", "under", "the read-back cannot see the default rung it just pressed, "
     "so a correct press is reported as a failure and the run downgrades itself",
     [("        if (!want || (t !== want && t !== want + 'default')) continue;",
       "        if (!want || t !== want) continue;")],
     [T_NEW]),
    ("E28", "over", "with no tier asked for the read-back matches an icon-only "
     "row, confirming a tier off whichever one comes first",
     [("        if (!want || (t !== want && t !== want + 'default')) continue;",
       "        if ((t !== want && t !== want + 'default')) continue;")],
     [T_NEW]),
]


# ⛔ A MUTANT CAN TURN A TEST INTO AN INFINITE LOOP, and then the harness hangs
# instead of reporting. A hang is a KILL with a note, never a stall.
_TEST_TIMEOUT_S = 180


def green(tests: list[str]) -> tuple[bool, bool]:
    """(passed, timed_out). A timeout counts as failing, i.e. mutant killed."""
    try:
        rc = subprocess.run([PY, "-m", "pytest", "-q", *tests], cwd=ROOT,
                            capture_output=True, timeout=_TEST_TIMEOUT_S).returncode
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
