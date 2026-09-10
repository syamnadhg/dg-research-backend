"""Mutation harness for the Gemini plan-fail wave — 2026-09-10.

⛔⛔ THE DEFECT THIS WAVE CLOSED WAS INVISIBLE FOR FIFTEEN MONTHS, AND THE REASON
IS THE POINT OF THIS HARNESS. Gemini's re-draft control is `aria-label="Redo"`;
the guard's word list was `retry|regenerate|try again|rerun|restart`. It could
never click it. One of the two real failure wordings says "encountering" and the
alternation said "encountered". Two words — and eight passing tests sat on top,
because the only test that read that pattern re-extracted the literal from the
source, un-doubled its escapes, compiled it in PYTHON, and fed it a sentence a
human wrote to satisfy it. Nothing executed what the browser executes, and
nothing had ever seen the real DOM.

⭐⭐ THE DIRECTION LABELS MEAN ONE THING HERE, BECAUSE CROSS-VERIFY FOUND SIX OF
THEM THE WRONG WAY ROUND IN THE FIRST DRAFT:

    "over"  · the guard FIRES WHEN IT SHOULD NOT — a healthy plan re-drafted, a
              good conversation abandoned, an alert held that should have gone up.
    "under" · the guard FAILS TO FIRE WHEN IT SHOULD — the fix undone, a
              safeguard removed, back toward the original defect.

⭐⭐ AND THE OVER-CORRECTIONS ARE WHERE THIS WAVE IS SHARPEST, because every one
of them destroys work that was fine:

  D1     — the size bound goes, and Gemini's own research PLAN starts reading as
           a failed draft. The turn restates the user's brief, so a topic about
           an outage, a post-mortem or an underperforming fund puts these exact
           phrases on screen as content. Four alternations match inside one
           realistic plan.
  S1     — the overlay is consulted before the turn's own text, so a leftover
           menu above a HEALTHY plan gets "Don't personalise" clicked and the
           call reports success. Two reviewers found this independently.
  G7     — the card is held at the site where the loop is GIVING UP, deferring
           the alert to a retry the next statement cancels. Nothing on screen
           for twelve minutes: the seventeen-minute ladder #921 removed, deleted
           by a boolean rather than an edit.
  O2/O7  — the ownership check condemns on page chrome, and the wrong-chat latch
           is never cleared. Together they walk a healthy run out of its own
           conversation and then collapse the ladder's wait to zero, producing
           duplicate Deep Research runs on the owner's account.
  C2     — the hold outranks the exhausted-attempts arm, so "the alert comes
           last" becomes "the alert never comes".

⭐ R1/R2 stay because they are the wave in miniature: a finder that matches the
right element and clicks the WRAPPER around it, reporting a truthy label for a
DOM no-op. R2 is the one that produces the wrapper click; R1 only blinds the
reader's name — the first draft had those two descriptions swapped.

    python .mutants/gemini_plan_redraft_0910_mutants.py
"""
from __future__ import annotations

import hashlib
import os
import re as _re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

RESEARCH = "research.py"
OURS = (RESEARCH,)

MINE_AGENT = "tests/"
MINE_ROOT = ("tests/test_gemini_redraft_0910.py "
             "tests/test_gemini_plan_gate_0910.py "
             "tests/test_gemini_orphan_gate_0910.py "
             "tests/test_gemini_plan_regen_755.py "
             "tests/test_gemini_dr_error_retry.py "
             "tests/test_narration_and_plan_card_0817.py "
             "tests/test_gemini_lost_send_955.py "
             "tests/test_bugs_953.py "
             "tests/test_gemini_start_watch_0817.py "
             "tests/test_alert_consistency_921.py")
MIN_SELECTED_AGENT = 1
MIN_SELECTED_ROOT = 250

ALL_AGENT = "tests/"
ALL_ROOT = "tests/"

# ⛔ ONE LEG. Everything this wave touches lives in `research.py`, which the ROOT
# suite reads; `_leg_for` sends it to the root leg and the agent leg never runs.
ROOT_LEG_FILES = (RESEARCH,)

_SOLO: "set[str]" = set()

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")


# The self-resolution shared by the reader and the clicker. Anchored once here
# because R2's whole point is the two of them DISAGREEING, so the mutant has to
# be able to patch one copy and leave the other alone.
_READER_AS_BUTTON = """  // this against the owner's capture, never by reading it.
  const isBtn = (n) => !!n && (String(n.tagName || '').toLowerCase() === 'button'
                               || (n.getAttribute && n.getAttribute('role') === 'button'));
  const asButton = (el) => {
    if (!el) return null;
    if (isBtn(el)) return el;
    const inner = el.querySelector ? el.querySelector('button, [role="button"]') : null;
    if (inner) return inner;
    return el.closest ? el.closest('button, [role="button"]') : null;
  };"""

_READER_CLOSEST_ONLY = """  // this against the owner's capture, never by reading it.
  const asButton = (el) => (el && el.closest)
    ? (el.closest('button, [role="button"]') || el) : el;"""

_AS_BUTTON = """  const asButton = (el) => {
    if (!el) return null;
    if (isBtn(el)) return el;
    const inner = el.querySelector ? el.querySelector('button, [role="button"]') : null;
    if (inner) return inner;
    return el.closest ? el.closest('button, [role="button"]') : null;
  };"""

_CLOSEST_ONLY = """  const asButton = (el) => (el && el.closest)
    ? (el.closest('button, [role="button"]') || el) : el;"""

LABEL = r'''    r"\b(?:redo|retry|regenerate|rerun|restart|try again)\b")'''


def lbl(words: str) -> str:
    """The label list with `words` inside, in the source's own spelling."""
    return '    r"\\b(?:%s)\\b")' % words


MUTANTS = [
    ('R1', RESEARCH, 'under',
     'the READER resolves upwards only, so it reports the custom-element wrapper and its accessible name comes back empty — the label fallback then has nothing to work with and the log cannot say what it clicked',
     [('  // this against the owner\'s capture, never by reading it.\n  const isBtn = (n) => !!n && (String(n.tagName || \'\').toLowerCase() === \'button\'\n                               || (n.getAttribute && n.getAttribute(\'role\') === \'button\'));\n  const asButton = (el) => {\n    if (!el) return null;\n    if (isBtn(el)) return el;\n    const inner = el.querySelector ? el.querySelector(\'button, [role="button"]\') : null;\n    if (inner) return inner;\n    return el.closest ? el.closest(\'button, [role="button"]\') : null;\n  };',
       '  // this against the owner\'s capture, never by reading it.\n  const asButton = (el) => (el && el.closest)\n    ? (el.closest(\'button, [role="button"]\') || el) : el;')]),
    ('R2', RESEARCH, 'under',
     "⛔⛔ THE CLICKER RESOLVES UPWARDS ONLY WHILE THE READER STILL DESCENDS, so the reading names 'Redo' and the click lands on the `gem-icon-button` wrapper — a DOM no-op that hands back a truthy label. Every log line says the control was clicked and the page never moves. Two finders reading one DOM differently is the #905 lesson, and running the reader against the owner's capture is what caught this mid-build",
     [('  // Identical resolution to the reader\'s, and it has to stay identical: if the\n  // two disagree about which node a shape means, the reading and the click are\n  // about different buttons.\n  const isBtn = (n) => !!n && (String(n.tagName || \'\').toLowerCase() === \'button\'\n                               || (n.getAttribute && n.getAttribute(\'role\') === \'button\'));\n  const asButton = (el) => {\n    if (!el) return null;\n    if (isBtn(el)) return el;\n    const inner = el.querySelector ? el.querySelector(\'button, [role="button"]\') : null;\n    if (inner) return inner;\n    return el.closest ? el.closest(\'button, [role="button"]\') : null;\n  };',
       '  const asButton = (el) => (el && el.closest)\n    ? (el.closest(\'button, [role="button"]\') || el) : el;')]),
    ('R3', RESEARCH, 'over',
     'a control that is present but INVISIBLE or DISABLED is chosen anyway — the skeleton-button no-op that reports success',
     [('            if not c.get("visible"):\n                _blocked = _blocked or f"{shape} present but not visible"\n                continue\n            if c.get("disabled"):\n                _blocked = _blocked or f"{shape} present but disabled"\n                continue',
       '            if False:\n                continue')]),
    ('R3b', RESEARCH, 'over',
     'the CLICKER stops re-checking, so a node that went `aria-disabled` between the reading and the click is clicked and returns a truthy label',
     [("    const rr = b.getBoundingClientRect();\n    if (rr.width < 8 || rr.height < 8) return '';\n    const cs2 = getComputedStyle(b);\n    if (cs2.display === 'none' || cs2.visibility === 'hidden') return '';\n    if (parseFloat(cs2.opacity) < 0.1) return '';\n    if (b.disabled || b.getAttribute('aria-disabled') === 'true') return '';\n",
       '')]),
    ('R4', RESEARCH, 'under',
     '⛔⛔ THE ROW DEDUPE GOES FROM THE READER. The overlay nests its pane inside its popover and a `gem-menu-item[role="menuitem"]` satisfies two members of the row selector, so one captured row reads as three',
     [('      if (!isVisible(r) || seenRows.indexOf(r) !== -1) continue;\n      seenRows.push(r);\n      rows.push({',
       '      if (!isVisible(r)) continue;\n      rows.push({')]),
    ('R5', RESEARCH, 'under',
     'the shared overlay selector narrows to the inner pane, so a menu rendered in a popover is invisible to BOTH walks and the re-draft row is never offered to the decider at all',
     [('_GEMINI_MENU_PANE_SEL = (\n    \'.cdk-overlay-pane, .cdk-overlay-popover, .cdk-overlay-container [role="menu"]\')',
       "_GEMINI_MENU_PANE_SEL = '.cdk-overlay-pane'")]),
    ('R6', RESEARCH, 'under',
     '⛔ THE TURN SELECTORS GO BACK INTO ONE QUERY. Taking the last node of a comma list returns an INNER node of the latest turn — `message-content`, which does not contain the action row — so the reader reports a failure with no control anywhere near it',
     [("  let turn = null;\n  for (const sel of TURN_SELECTORS) {\n    const nodes = document.querySelectorAll(sel);\n    if (nodes.length) { turn = nodes[nodes.length - 1]; break; }\n  }\n  if (!turn) return JSON.stringify({found: false, text: '', controls: [], rows: []});",
       "  const _all = document.querySelectorAll(TURN_SELECTORS.join(', '));\n  let turn = _all.length ? _all[_all.length - 1] : null;\n  if (!turn) return JSON.stringify({found: false, text: '', controls: [], rows: []});")]),
    ('R7', RESEARCH, 'under',
     "⛔⛔ THE READ GOES PAGE-WIDE AGAIN. The turn's text becomes the whole body, which carries the pasted brief, the rail's chat titles and every earlier turn — so a failure that has ALREADY been re-drafted keeps authorising clicks, and the first working Redo becomes a loop that never ends",
     [("    text: (turn.innerText || '').slice(0, 4000),",
       "    text: (document.body.innerText || '').slice(0, 4000),")]),
    ('R8', RESEARCH, 'over',
     "⛔⛔ THE CONTROL'S DENY LIST GOES, so a test id migrated one level up onto the buttons container resolves to `thumb-up-button` and the run posts feedback to Google while logging that it re-drafted the plan",
     [('            if _GEMINI_REGEN_DENY_RE.search(_gemini_norm(c.get("name") or "")):\n                _blocked = _blocked or (\n                    f"{shape} resolved to {c.get(\'name\')!r}, which is another "\n                    "action in the row")\n                continue\n',
       '')]),
    ('W1', RESEARCH, 'under',
     "⛔⛔ CAUSE 2, RESTORED: the verb goes back to the past tense only, and 'I seem to be encountering an error' misses again",
     [('|encounter(?:ed|ing) an? (?:issue|error)',
       '|encountered an? (?:issue|error)')]),
    ('W2', RESEARCH, 'under',
     "⛔⛔ THE CURLY APOSTROPHE MAPPING GOES, so `can’t`, `I’m` and `couldn’t` stop matching — the exact miss that `'?` alternations hid one at a time",
     [('    "‘": "\'", "’": "\'", "‛": "\'", "ʼ": "\'", "´": "\'",',
       '    "‘": "‘",')]),
    ('W3', RESEARCH, 'over',
     '⛔⛔ A BARE `error` JOINS THE PATTERN. Together with the size bound going it would be fatal; on its own it still fires on any short turn that mentions one',
     [('    r"something went wrong"',
       '    r"error|something went wrong"')]),
    ('W4', RESEARCH, 'under',
     '⛔ THE WHITESPACE COLLAPSE GOES from the normaliser, so a phrase that wrapped across two lines in the bubble stops matching — silently, and only in the narrow window where it matters',
     [('    return re.sub(r"\\s+", " ", (text or "").translate(_GEMINI_QUOTE_MAP)).strip().lower()',
       '    return (text or "").translate(_GEMINI_QUOTE_MAP).strip().lower()')]),
    ('W5', RESEARCH, 'under',
     '⛔⛔ CAUSE 1, RESTORED: `redo` leaves the fallback word list, so the only wording Gemini has ever shown is unmatchable again',
     [('    r"\\b(?:redo|retry|regenerate|rerun|restart|try again)\\b")',
       '    r"\\b(?:retry|regenerate|rerun|restart|try again)\\b")')]),
    ('W6', RESEARCH, 'over',
     '`refresh` joins the label list, so a control whose accessible name means RELOAD THE PAGE is clicked as though it re-drafts a turn',
     [('    r"\\b(?:redo|retry|regenerate|rerun|restart|try again)\\b")',
       '    r"\\b(?:redo|refresh|retry|regenerate|rerun|restart|try again)\\b")')]),
    ('W7', RESEARCH, 'over',
     'the label list widens to the rest of the captured action row, so Copy or Share is clicked instead of Redo',
     [('    r"\\b(?:redo|retry|regenerate|rerun|restart|try again)\\b")',
       '    r"\\b(?:redo|copy|share|more|retry|regenerate|rerun|restart|try again)\\b")')]),
    ('D1', RESEARCH, 'over',
     "⛔⛔ THE SIZE BOUND GOES, and this is the over-correction that eats healthy work. The turn being read is Gemini's own research PLAN, which restates the user's brief — so a brief on an outage, a post-mortem, a failed mission or an underperforming fund puts these phrases on screen as CONTENT. Four separate alternations match inside one realistic plan. The loop then re-drafts a perfectly good plan up to the cap, and `start_present` cannot save it because the auto-start layout renders Start disabled for ever",
     [('    norm = _gemini_norm(latest_text)\n    if len(norm) > _GEMINI_PLAN_FAIL_MAX_CHARS:\n        return False\n    return bool(_GEMINI_PLAN_FAIL_RE.search(norm))',
       '    return bool(_GEMINI_PLAN_FAIL_RE.search(_gemini_norm(latest_text)))')]),
    ('D2', RESEARCH, 'under',
     "the bound is measured on the RAW text instead of the normalised one, so a bubble's own line breaks and indentation push a real failure message over it and the re-draft never fires",
     [('    norm = _gemini_norm(latest_text)\n    if len(norm) > _GEMINI_PLAN_FAIL_MAX_CHARS:',
       '    norm = _gemini_norm(latest_text)\n    if len(latest_text or "") > _GEMINI_PLAN_FAIL_MAX_CHARS:')]),
    ('D3', RESEARCH, 'under',
     'the bound tightens to a length the captured failures themselves exceed, so the feature stops recognising the two wordings it was built from',
     [('_GEMINI_PLAN_FAIL_MAX_CHARS = 400',
       '_GEMINI_PLAN_FAIL_MAX_CHARS = 40')]),
    ('M1', RESEARCH, 'over',
     "⛔⛔ AN UNREADABLE OVERLAY IS GUESSED AT. The first row is returned whatever it says — and this file already ruled on that: 'we do NOT blind-click — clicking an unidentified control risks a destructive misclick'",
     [('    return None, "menu is open but no row identifies itself as a re-draft"',
       '    return live[0], "first row, unidentified"')]),
    ('M2', RESEARCH, 'under',
     'the un-personalised row stops being preferred, so the owner\'s explicit instruction — pick "Don\'t personalise" when it shows — is dropped',
     [('    for r in owned:\n        if _GEMINI_NO_PERSONALISE_RE.search(_gemini_norm(r.get("name") or "")):\n            return r, "regenerate row, un-personalised"\n    if owned:',
       '    if owned:')]),
    ('M3', RESEARCH, 'under',
     'the row wording narrows to one spelling and one apostrophe, so a build that renders `Don’t personalize` stops being recognised — the same one-character miss as cause 2, in the other direction',
     [('_GEMINI_NO_PERSONALISE_RE = re.compile(r"don\'t personali[sz]e")',
       '_GEMINI_NO_PERSONALISE_RE = re.compile(r"don\'t personalise")')]),
    ('M4', RESEARCH, 'over',
     'the WORDING is consulted before the test id, so a row that merely reads like the option beats the row Gemini actually marks as its re-draft',
     [('    owned = [r for r in live\n             if _GEMINI_REGEN_ROW_TESTID in (r.get("testid") or "").lower()]\n    for r in owned:',
       '    for r in live:\n        if _GEMINI_NO_PERSONALISE_RE.search(_gemini_norm(r.get("name") or "")):\n            return r, "wording first"\n    owned = [r for r in live\n             if _GEMINI_REGEN_ROW_TESTID in (r.get("testid") or "").lower()]\n    for r in owned:')]),
    ('M5', RESEARCH, 'over',
     "⛔⛔ THE DENY LIST GOES FROM THE DECIDER, so a Delete row that answers to the regenerate test id — a build renaming one attribute onto another row — is returned as the re-draft. The other menu picker in this repo carries a deny list for exactly this: 'an off-by-two is not a failed download, it is a destroyed one'",
     [('    live = [r for r in rows if _ok(r)]\n    if not live:\n        return None, "every row in the menu reads as destructive"\n',
       '    live = list(rows)\n')]),
    ('M6', RESEARCH, 'over',
     "the deny list goes from the PAGE JS, so the decider's refusal is the only thing standing between a renamed Delete row and a click on it",
     [("      const low = raw.toLowerCase();\n      for (const d of DENY) { if (low.indexOf(d) !== -1) return ''; }\n",
       '')]),
    ('M7', RESEARCH, 'under',
     '⛔⛔ THE PICK GOES BACK TO THE ORDINAL. The index space depends on which overlay panes were VISIBLE at the instant of the reading, so a popover finishing its opacity ramp between the read and the click renumbers the rows and the click lands somewhere else',
     [('      if (want.testid) { if (tid !== String(want.testid).toLowerCase()) continue; }\n      else if (raw !== want.name) continue;',
       '      if (seenRows.length - 1 !== want.index) continue;')]),
    ('M8', RESEARCH, 'under',
     'the picker\'s inner query takes `[role="menuitem"]` back, which `querySelector` can only ever satisfy from a NESTED row — the wrong node by definition',
     [("      const hit = r.querySelector('button') || r;",
       '      const hit = r.querySelector(\'button, [role="menuitem"]\') || r;')]),
    ('S1', RESEARCH, 'over',
     '⛔⛔ THE ROWS ARE CONSULTED BEFORE THE TURN\'S OWN TEXT AGAIN. A regenerate overlay left open over a HEALTHY plan then returns `pick_menu`, the caller clicks "Don\'t personalise", a good plan is destroyed and the call reports `redrafted=True` with a success log line. Cross-verify demonstrated it from a literal reading, and the first harness had a mutant ENFORCING this order',
     [('    if not _gemini_reads_as_failed(r.get("text") or ""):\n        return "settled", "the latest turn no longer reads as failed"\n    rows = r.get("rows") or []\n    if opened_menu and rows:',
       '    rows = r.get("rows") or []\n    if opened_menu and rows:')]),
    ('S2', RESEARCH, 'over',
     "⛔⛔ ANY OPEN OVERLAY IS TREATED AS OURS. The reader sees every visible overlay in the document — Gemini's own model picker renders `menuitemradio` rows — so an unrelated menu diverts the whole call and the dismiss path presses Escape at a menu the user opened themselves",
     [('    if opened_menu and rows:',
       '    if rows:')]),
    ('S3', RESEARCH, 'under',
     "⛔ A PAGE THAT COULD NOT BE READ COMES OUT AS SETTLED — a probe failure reported as 'nothing is wrong here'",
     [('        return "no_turn", "no model turn rendered yet"',
       '        return "settled", "no model turn rendered yet"')]),
    ('S4', RESEARCH, 'under',
     'a failure with nothing clickable is reported as SETTLED rather than escalated, so the plain-chat stall goes quiet instead of carding',
     [('    return ("click", why) if control is not None else ("no_control", why)',
       '    return ("click", why) if control is not None else ("settled", why)')]),
    ('B1', RESEARCH, 'under',
     "⛔⛔ THE SINGLE-BOOLEAN CONTRACT IS BACK: `acted` collapses into the outcome, so a control that clicks and never re-drafts is clicked every ten seconds for the whole plan window — the Start-button spam #953 removed on the directive 'send it and wait, only retry if it doesn't fire'",
     [('        return False, _acted, True, "clicked, but the turn still reads as failed"',
       '        return False, False, True, "clicked, but the turn still reads as failed"')]),
    ('B2', RESEARCH, 'over',
     'a click the finder never landed still spends an attempt, so three readings of a page whose control keeps vanishing burn the whole cap without touching it',
     [('            _acted = False       # the finder returned empty: no node was clicked\n            return False, _acted, False, "the control was gone by the time the click ran"',
       '            return False, True, False, "the control was gone by the time the click ran"')]),
    ('B3', RESEARCH, 'over',
     "⛔⛔ `in_flight` COLLAPSES INTO `acted`, so the owner's card is held for an overlay we opened, could not read and then dismissed — waiting on a re-draft that is not happening and cannot start. That conflation is what cross-verify found, and it was the likeliest `acted` outcome of all on a build whose row labels have drifted",
     [('        await _gemini_dismiss_our_overlay(page)\n        return False, _acted, False, why\n\n    # Every remaining path has touched the page',
       '        await _gemini_dismiss_our_overlay(page)\n        return False, _acted, _acted, why\n\n    # Every remaining path has touched the page')]),
    ('B4', RESEARCH, 'over',
     "⛔⛔ THE VERIFY GOES. The call returns success on the strength of the click's own return value — which is what let opening a MENU count as a re-draft in the helper this replaces",
     [('    await asyncio.sleep(settle_s)\n    after = await _gemini_regen_read(page)',
       '    return True, _acted, False, f"re-drafted after \'{clicked}\'"\n    after = await _gemini_regen_read(page)')]),
    ('B5', RESEARCH, 'under',
     "the overlay WE opened and cannot read is left up instead of dismissed, so its backdrop intercepts every later click on the page — ours and the CUA ladder's",
     [('        await _gemini_dismiss_our_overlay(page)\n        return False, _acted, False, why',
       '        return False, _acted, False, why')]),
    ('B6', RESEARCH, 'under',
     '⛔ AN OVERLAY OF OURS THAT MOUNTS LATE IS LEFT ON SCREEN. The pane can appear after the post-click re-read, so the step machine never sees it and neither branch dismisses it — and one left over the third attempt is one the loop can never clear, because the loop has exited',
     [('    if _opened_menu and (after.get("rows") or []):\n        await _gemini_dismiss_our_overlay(page)\n        after = await _gemini_regen_read(page)\n',
       '')]),
    ('B7', RESEARCH, 'under',
     "the Stop check before the click goes, so a Stop arriving inside this helper's two round trips still results in a click — 'no post-Stop DOM driving' is the standing rule",
     [('        if _controls.is_stop():\n            return False, False, False, "stop requested before the re-draft click"\n',
       '')]),
    ('G1', RESEARCH, 'under',
     "⛔⛔ THE LOOP DELEGATES TO THE TEXT-GATED SHARED HELPER AGAIN, whose word list has never matched Gemini's control. This is the whole fifteen-month defect in one line, and it left every test green",
     [('                    (_redrafted, _acted, _in_flight,\n                     _why_rd) = await _gemini_redraft_plan(gemini_page, "2D-plan")',
       '                    _acted = await _try_inpage_retry_on_research_fail(\n                        gemini_page, "gemini", "2D-plan", max_wait_s=4)\n                    _redrafted, _in_flight, _why_rd = _acted, _acted, "legacy helper"')]),
    ('G2', RESEARCH, 'over',
     'the running-research probe is hoisted ABOVE the fail-text gate, so every healthy tick of the plan wait pays for a body read it has no use for',
     [('                _already_running = False\n                if _gemini_reads_as_failed(_latest):\n                    try:',
       '                _already_running = False\n                if True:\n                    try:')]),
    ('G3', RESEARCH, 'under',
     '⛔⛔ THE VERDICT IS HANDED A LITERAL, so its first arm is dead at its only call site — and that arm is the one that stops a RUNNING research being re-drafted, the single destructive move on this screen',
     [('                    research_started=_already_running,',
       '                    research_started=False,')]),
    ('G3b', RESEARCH, 'over',
     "⛔⛔ A RUNNING-RESEARCH PROBE THAT RAISED READS AS 'NOT RUNNING', which is what AUTHORISES the click. The function is documented fail-closed so a miss never fakes a start — and at this call site the polarity is inverted, so the safe answer is the dangerous one",
     [('                        # probe that could not answer must read as "assume it is\n                        # running": the cost is one re-draft skipped, against\n                        # re-drafting a live research run.\n                        _already_running = True',
       '                        _already_running = False')]),
    ('G4', RESEARCH, 'under',
     'the attempt is spent on the OUTCOME instead of the click, so a control that never re-drafts is never counted and is clicked every tick',
     [('                    if _acted:',
       '                    if _redrafted:')]),
    ('G5', RESEARCH, 'over',
     "the gate widens from 'failed' to 'anything but ready', so the plain-chat stall and a visibly drafting plan both get clicked at",
     [('                if _verdict == "failed":\n                    (_redrafted',
       '                if _verdict != "ready":\n                    (_redrafted')]),
    ('G6', RESEARCH, 'under',
     '⛔ THE HOLD FLAG MOVES INSIDE THE POLL LOOP, so it resets on every tick the 45-second cooldown skips the re-draft branch — and the card fires in the gap between two clicks, the exact window it is meant to be held through',
     [('        _redraft_pending = False\n        _logged_stall_diag = False',
       '        _logged_stall_diag = False')]),
    ('G7', RESEARCH, 'over',
     "⛔⛔ THE BREAK-SITE CARD IS HANDED THE HOLD FLAG AGAIN — the blocker two independent reviewers found. That site is the loop DECIDING TO STOP WAITING: the next statement is an unconditional break, so the alert is deferred to a retry the following line cancels. Nothing on screen at the moment the loop gives up, and the owner's first actionable surface arrives from the CUA ladder about twelve minutes later — the seventeen-minute ladder #921 exists to remove, deleted by a boolean instead of an edit",
     [('                        redraft_pending=False):\n                    _raise_plan_alert("our own plan-wait budget is spent")',
       '                        redraft_pending=_redraft_pending):\n                    _raise_plan_alert("our own plan-wait budget is spent")')]),
    ('G8', RESEARCH, 'under',
     'the in-loop card stops being told about the hold, so the alert is beside the clicks again rather than after them',
     [('                    start_clicked=bool(start_clicked),\n                    redraft_pending=_redraft_pending):\n                _raise_plan_alert("plan clearly failed")',
       '                    start_clicked=bool(start_clicked)):\n                _raise_plan_alert("plan clearly failed")')]),
    ('G9', RESEARCH, 'over',
     '⛔ THE COOLDOWN CLOCK GOES BACK TO ZERO, so it is already satisfied on the first tick and a re-draft can fire about two seconds after the brief was submitted — at a turn that is still painting',
     [("        _last_regen_at = time.time()      # re-draft can't burn the 3-cap",
       "        _last_regen_at = 0.0              # re-draft can't burn the 3-cap")]),
    ('G10', RESEARCH, 'over',
     "⛔⛔ OUR OWN RE-DRAFT'S STREAMING IS READ AS PROOF THAT GEMINI AUTO-STARTED ITS RESEARCH. A Redo we clicked restarts the plan, legitimately, and the heartbeat reports `generating` — so a planless Gemini is handed to the round-robin as though its research were running: no CUA ladder, no card, and a log line that is false",
     [('            if (_elapsed >= _stream_handoff_sec and _streaming_recent\n                    and (time.time() - _last_regen_at) >= _stream_handoff_sec):',
       '            if _elapsed >= _stream_handoff_sec and _streaming_recent:')]),
    ('G11', RESEARCH, 'over',
     '⛔ THE LAST ATTEMPT LOSES ITS WINDOW. The exhausted-attempts latch fires the instant the third click lands, so that attempt is judged ~10 seconds after it while the first two each got 45 — same page, same failure, and a card on the third the first would not have raised',
     [('                    and not _regen_cap_emitted and not _controls.is_stop()\n                    and (time.time() - _last_regen_at) > _GEMINI_REGEN_COOLDOWN_SEC):',
       '                    and not _regen_cap_emitted and not _controls.is_stop()):')]),
    ('G12', RESEARCH, 'under',
     'the diagnostic stops distinguishing a READ THAT FAILED from a silent plan, so the one artefact meant to make a Gemini UI revision visible names the wrong cause for the exact failure it exists to catch',
     [('                    if (_verdict == "silent" and not _reading.get("found")',
       '                    if (_verdict == "silent" and False')]),
    ('C1', RESEARCH, 'under',
     'the hold arm goes and the alert is beside the clicks again rather than after them',
     [('    if redraft_pending:\n        return False\n',
       '')]),
    ('C2', RESEARCH, 'over',
     "⛔⛔ THE HOLD OUTRANKS THE EXHAUSTED-ATTEMPTS ARM. Three spent re-drafts is EVIDENCE, not a timer, and #921 exists so it reaches the owner early — 'the alert comes last' must not become 'the alert never comes'. This ordering is load-bearing now that the cap lives in one place instead of two",
     [('    if regen_capped:\n        return True\n    if redraft_pending:\n        return False',
       '    if redraft_pending:\n        return False\n    if regen_capped:\n        return True')]),
    ('C3', RESEARCH, 'over',
     'the new arm defaults to True, so every OTHER caller of the predicate silently inherits a hold it never asked for',
     [('                          redraft_pending: bool = False) -> bool:',
       '                          redraft_pending: bool = True) -> bool:')]),
    ('O1', RESEARCH, 'over',
     "⛔⛔ 'I CANNOT TELL' COMES OUT AS 'SOMEBODY ELSE'S'. A conversation still rendering answers False, and False is ACTED on — so a healthy run whose bubble painted a moment late is walked out of its own thread. The owner ruled on this exact shape on 2026-08-27",
     [('    if len(b) < _CONVO_TEXT_MIN_CHARS or not (pasted_text or "").strip():\n        return None',
       '    if False:\n        return None')]),
    ('O2', RESEARCH, 'over',
     "⛔⛔ PAGE CHROME CONDEMNS A CONVERSATION. An `user-query` mounted but not yet filled is falsy, so the read falls through to `document.body` — and Gemini's rail ('New chat · Recent · Gems · Settings & help') always clears the evidence threshold and never contains this run's brief. The tab is then navigated away from the run's own conversation",
     [('    return False if from_turn else None',
       '    return False')]),
    ('O3', RESEARCH, 'under',
     "the shared template header stops being stripped, so the fingerprint is boilerplate every brief this product has ever written shares — it would call a stranger's thread ours",
     [('    if head.lstrip().lower().startswith("# research brief"):\n        head = head.split("\\n", 1)[1] if "\\n" in head else ""\n',
       '    pass\n')]),
    ('O4', RESEARCH, 'under',
     "⛔⛔ THE LANDING GOES BACK TO THE URL'S SHAPE, so a tab already inside a conversation passes on the first poll and the run is confirmed against a thread that may be the previous run's",
     [('            _convo_text, _from_turn = await _gemini_read_conversation_text(page)\n            _own = _gemini_conversation_ownership(\n                _convo_text, brief_to_paste, from_turn=_from_turn)\n            if _own is False:',
       '            _own = None\n            if False:')]),
    ('O5', RESEARCH, 'over',
     "the landing demands POSITIVE proof of ownership, so 'cannot tell' refuses — every slow-rendering run is sent into a recovery it does not need",
     [('            if _own is False:',
       '            if _own is not True:')]),
    ('O6', RESEARCH, 'under',
     "⛔⛔ THE LADDER'S CONFIRMATION `or`s BACK TO THE URL SHAPE, so a re-paste that ends up in a rejected chat is still reported as 'submission confirmed' — the fix bypassed on the path a recovering run actually takes",
     [('            if _landed or await _gemini_conversation_is_not_foreign():',
       '            if _landed or _gemini_in_conversation():')]),
    ('O7', RESEARCH, 'over',
     "⛔⛔ THE `_wrong_chat` LATCH IS NOT CLEARED when the tab leaves the conversation. It is `nonlocal` and read by both waits, so the ladder's own bail-out fires on poll one and its 40-second wait becomes ZERO on all three attempts — each re-pasting into an empty composer, producing duplicate Deep Research conversations on the owner's account for a send that had landed",
     [('                _wrong_chat = False\n                return False',
       '                return False')]),
    ('O8', RESEARCH, 'under',
     'the wrong-chat home reset moves AFTER the sidebar hunt, so the hunt is handed a tab that is inside a conversation — and its own rule is that it never reloads from there, which is how it freshens a stale Recent list',
     [('            if _wrong_chat and _gemini_in_conversation() and not _controls.is_stop():',
       '            if False:')]),
    ('O9', RESEARCH, 'over',
     'the adopt gate drops its not-in-a-conversation requirement, so the hunt runs from inside a chat and reloads where it has promised never to',
     [('            if not _controls.is_stop() and not _gemini_in_conversation():',
       '            if not _controls.is_stop():')]),
    ('O10', RESEARCH, 'under',
     "the conversation read goes body-first, so the rail's chat titles and every other turn are what the ownership check judges",
     [('    " const t = (q && q.innerText) || \'\';"',
       '    " const t = (document.body.innerText || \'\') || (q && q.innerText) || \'\';"')]),
    ('O11', RESEARCH, 'over',
     "⛔ WITH NO BRIEF TO COMPARE AGAINST, THE ANSWER BECOMES 'NOT OURS' rather than 'no evidence' — so a run whose brief text is unavailable evicts itself from its own conversation",
     [('    if len(b) < _CONVO_TEXT_MIN_CHARS or not (pasted_text or "").strip():',
       '    if len(b) < _CONVO_TEXT_MIN_CHARS:')]),
    ('O12', RESEARCH, 'under',
     'the adoption gate grows a SECOND copy of the ownership maths, so the hunt can adopt a chat the landing check has just refused',
     [('        _txt, _from_turn = await _gemini_read_conversation_text(p)\n        return _gemini_conversation_is_ours(_txt, pasted_text)',
       '        try:\n            body = await p.evaluate(\n                "() => { const q = document.querySelector(\'user-query\');"\n                " return ((q && q.innerText) || document.body.innerText || \'\')"\n                ".slice(0, 4000); }")\n        except Exception:\n            return False\n        b = re.sub(r"\\s+", " ", body or "").strip().lower()\n        return _gemini_owns_candidate(b[:300], pasted_head)')]),
    ('O13', RESEARCH, 'under',
     'the home reset is inlined again at one of its two sites, so the two branches can drift about how hard they try to leave a conversation',
     [('                await _gemini_reset_to_home()\n                if _gemini_in_conversation():',
       '                for _hg in range(3):\n                    try:\n                        await page.goto("https://gemini.google.com/app",\n                                        wait_until="domcontentloaded", timeout=20000)\n                    except Exception:\n                        pass\n                    if not _gemini_in_conversation():\n                        break\n                    await asyncio.sleep(1.5)\n                if _gemini_in_conversation():')]),
    ('O14', RESEARCH, 'under',
     'a chat that is PROVABLY not ours is polled for the rest of the deadline, so fifteen or forty seconds are burnt on a question whose answer cannot change before the recovery that would change it',
     [('                if _wrong_chat:\n                    return False\n',
       '')]),
    ('O15', RESEARCH, 'under',
     "the reset's answer is discarded, so the log below reports 'adoption rejected the sidebar candidate(s)' for a run where adoption never got to execute",
     [('                if not await _gemini_reset_to_home():',
       '                if False:')]),
]

def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def _mark(mid: str, fname: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _refuse_if_a_previous_run_died() -> "str | None":
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _path_for(fname: str) -> Path:
    return ROOT / fname


def _digest() -> dict:
    """Content hash of every file this harness can touch.

    ⭐ CONTENT, NOT `git status`. Uncommitted work is the normal state mid-wave,
    so a git check would report dirty on every run and a real leftover mutant
    would be invisible inside that noise."""
    return {f: hashlib.sha256(_path_for(f).read_bytes()).hexdigest() for f in OURS}


def _pytest(args, cwd, env) -> str:
    """'green' | 'red' | 'nothing-collected'.

    ⛔⛔ EXIT 5 IS NOT A FAILURE. pytest returns 5 when nothing is collected, and
    a runner that only asks `returncode == 0` reads that as red — so one typo in
    the selection would score every mutant killed against zero tests."""
    code = sh(args, cwd=cwd, env=env).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def _leg_for(fname: str) -> str:
    """Which suite can SEE a repair to this file.

    ⛔⛔ THE REASON THIS EXISTS. Every harness before this one ran the agent
    suite only, which was right while every wave was agent-only. This wave
    repaired `research.py` (the f-string that had CI's lint floor red for six
    pushes) and a ROOT-suite harness guard — and an agent-only runner would have
    scored both as killed without running one test that could see them. A score
    is only a score if the tests it ran could have failed."""
    return "root" if fname in ROOT_LEG_FILES else "agent"


def _leg_conf(leg: str):
    if leg == "root":
        return (ROOT, str(ROOT / ".venv" / "bin" / "python"),
                MINE_ROOT.split(), [ALL_ROOT], MIN_SELECTED_ROOT)
    return (AGENT, str(AGENT / ".venv" / "bin" / "python"),
            MINE_AGENT.split(), [ALL_AGENT], MIN_SELECTED_AGENT)


def run_tests(filtered: bool, leg: str = "agent") -> bool:
    cwd, py, mine, allsuites, _floor = _leg_conf(leg)
    purge_pycache(cwd if leg == "root" else AGENT)
    suites = mine if filtered else allsuites
    out = _pytest([py, "-B", "-m", "pytest", *suites, "-q", "-p", "no:cacheprovider"],
                  cwd, ENV)
    if out == "nothing-collected":
        raise AssertionError(f"the {leg} leg collected NO tests — check the selection")
    return out == "green"


def _selected_count(leg: str) -> int:
    cwd, py, mine, _all, _floor = _leg_conf(leg)
    out = sh([py, "-B", "-m", "pytest", *mine, "--collect-only", "-q",
              "-p", "no:cacheprovider"], cwd=cwd, env=ENV).stdout
    m = _re.search(r"^(\d+) tests? collected", out, _re.M)
    return int(m.group(1)) if m else 0


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if not only:
        selected = [m for m in selected if m[0] not in _SOLO]

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — a spot check, not a score.")
    print("scope: THE WHOLE AGENT SUITE (--unfiltered)" if unfiltered
          else "scope: THIS WAVE'S OWN GUARDS ONLY — pass --unfiltered for the other number")

    stranded = _refuse_if_a_previous_run_died()
    if stranded:
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {stranded}\nRestore that file, then delete\n    {_INFLIGHT}")
        return 2

    legs = sorted({_leg_for(m[1]) for m in selected})
    if not unfiltered:
        for leg in legs:
            n = _selected_count(leg)
            floor = _leg_conf(leg)[4]
            print(f"the wave's own {leg} files collect {n} test(s)")
            if n < floor:
                print(f"⛔⛔ TOO FEW on the {leg} leg (need >= {floor}) — a selection "
                      "that matches nothing exits 5 and scores every mutant killed. "
                      "Refusing to run.")
                return 2

    before = _digest()
    for leg in legs:
        print(f"baseline [{leg}]… ", end="", flush=True)
        if not run_tests(filtered=not unfiltered, leg=leg):
            print("RED — fix the tree before mutating")
            return 2
        print("green")

    survivors, faults = [], []
    for mid, fname, direction, why, edits in selected:
        path = _path_for(fname)
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            # ⛔⛔ COMPILED BEFORE IT IS WRITTEN. A mis-indented anchor still
            # substring-matches and yields an unparseable file; the suite then
            # goes red on an import error and the mutant banks a kill it never
            # earned.
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as syn:
                    raise AssertionError(
                        f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                        "check the anchor's indentation") from None
            _mark(mid, fname)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            leg = _leg_for(fname)
            killed = not run_tests(filtered=not unfiltered, leg=leg)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                again = not run_tests(filtered=not unfiltered, leg=leg)
                if again != killed:
                    flapped = True
                    killed = False
            mark = "✓ killed  " if killed and not flapped else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed or flapped:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    leftover = [f for f in before if before[f] != after[f]]
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the wave's score)" if only else ""
    scope = " [whole agent suite]" if unfiltered else " [own guards]"
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
