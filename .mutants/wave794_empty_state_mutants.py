"""Mutation harness — THE EMPTY STATE (wave 7.9-4, items C1 and C5, 2026-09-08).

⛔⛔ WHAT THIS CODE DECIDES. What somebody with NO research computer is told they
can do. Before this wave the answer was the same on all ten screens that gave it:
buy or borrow a machine and paste a pair code — while the account had been able to
ask to use somebody else's since 7.9-2. Every mutant below puts one of those ten
screens back to a dead end, or takes the LIST out of the offer, which turns a next
step back into advice.

⛔⛔ THE THREE THINGS, AND WHY EACH IS LOAD-BEARING:
  · there is no computer on this account — without it the reader does not know
    whether the silence is a fault or a state;
  · your own can be added with a pair code — the route for somebody who HAS a
    machine, which is the only route that used to be named;
  · or you can ask to use somebody else's, WITH THE ONES ON OFFER LISTED — an
    offer with nothing named is advice, and the ids are what the next command
    takes, because public labels collide on the string "Research computer".

⭐⭐ THE SHARPEST MUTANTS HERE:
  E3/E4/E5 — the third thing disappears on exactly one branch. E4 and E5 are the
             ones that matter: the offer is TRUE whether or not the list could be
             read and whether or not anybody is offering today, and dropping it on
             those branches restores the dead end silently, on the paths nobody
             looks at.
  L1       — the offer keeps its sentence and loses its rows, which is the shape
             the whole wave exists to remove.
  L11      — the empty state stops sharing the browse screen's row renderer. That
             is how the ten wordings happened; extracting a helper does not test
             it, so a mutant has to ask whether both consumers still read it.
  R10      — the device-list clause loses its action gate, and "remove my mac"
             prints a list instead of unlinking. That defect was LIVE for the
             narrow noun list ("remove my node") and widening the list without
             this gate would have spread it to five more words.
  R12      — a bare noun is taken as a NAME again, and a DESTRUCTIVE confirm
             quotes a machine called “mac” whose own "yes" cannot resolve.
  R14/R15  — the four nouns that double as machine NAMES. Fold them in flat and a
             named ask ("request access to that Mac") answers with everybody's
             machines; leave the determiner check out and "ask for a mac" raises
             the disclosing consent question about a machine called “mac”.
  F3       — the past-tense caller phrase reaches the fallback again, so a signed-
             out person with no computer reads "Couldn't asked for your requests".
  C1/C2    — the anti-drift mutants. Four sentences are printed by two screens
             each; the sweep caught me hand-copying them into the second site
             while building the wave that exists to stop exactly that.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ SCORED AGAINST THIS WAVE'S OWN GUARDS. Pass --unfiltered to ask the other
question — whether the TREE catches it — which is deliberately separate.

    .venv/bin/python .mutants/wave794_empty_state_mutants.py
    .venv/bin/python .mutants/wave794_empty_state_mutants.py --unfiltered
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

CLI = "agent/facade/cli.py"
BRIDGE = "agent/facade/bridge.py"
SR = "agent/facade/skill/scripts/sr.py"
SKILL = "agent/facade/skill/SKILL.md"
WATCH = "agent/facade/skill/scripts/sr_attention_poll.py"
OURS = (CLI, BRIDGE, SR, SKILL, WATCH)

# ⭐ THE GUARDS THIS WAVE ADDED OR CORRECTED. The four older files are here
# because this wave rewrote assertions inside them that were pinning defects —
# those corrections are this wave's work and a score that skipped them would be
# scoring half the change.
MINE = ("tests/test_empty_state_794.py "
        "tests/test_routing_794.py "
        "tests/test_chat_public_792.py "
        "tests/test_public_devices_792.py "
        "tests/test_chat_owner_793.py "
        "tests/test_sr_client.py "
        "tests/test_sr_do.py "
        "tests/test_sr_stream.py")
MIN_SELECTED = 400

ALL_SUITES = "tests/"

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ⛔⛔ RE-ANCHORED 2026-09-24 — the agent's 2026-09-20..23 fixes moved the text
    # under these, and `test_no_new_stale_anchors` caught it before a push:
    #   E2-E5, L1, L2, L5, L10, L11, T2-T4, W2, X14, X15, X17, X19 — the `Public
    #   computers` section, `_public_rows_block`, the install page in place of
    #   `--pair`; X22 retired (see there)
    # Each keeps its ORIGINAL defect on the new text, and each was re-run and
    # KILLED against this harness's own selection before this note was written.
    # ⛔⛔ AND AGAIN, LATER THE SAME DAY — the owner's one "Add a computer" line
    # replaced `_ADD_WITH_CODE`, `_SETUP_NODE_LINES`, the terminal's closing install
    # block and the watcher's closing pair, so eleven anchors matched nothing and
    # `test_no_new_stale_anchors` went red:
    #   E2, E7, S2, S5, T3, T4, W2, W3, X17, X19, X23 — plus E8, whose anchor still
    #   matched but whose replacement named the deleted `_SETUP_NODE_LINES`, so it
    #   "killed" on a NameError instead of measuring the order it is about.
    # ⭐ The install page no longer trails the screen; it is INSIDE the add line.
    # So E7 and X19 now take the page out of that line — the same defect (no route
    # for somebody with no machine at all) on the text that carries it now. Each
    # was re-run and KILLED against this harness's own selection, as above.
    # ═══════════ E — the empty state itself ══════════════════════════════════
    ("E1", SR, "under",
     "⛔⛔ THE FIRST THING GOES. Without it the reader cannot tell whether the "
     "silence is a fault or the ordinary state of a new account",
     [('    lines.append("No research computer on this account yet.")\n', '')]),
    ("E2", SR, "under",
     "the add line goes, so somebody who ALREADY HAS a machine is never told the "
     "one step that connects it — and somebody with none is never given the page",
     [('    lines.append(_ADD_A_COMPUTER)\n'
       '    pub = _public_offer_lines()\n',
       '    pub = _public_offer_lines()\n')]),
    ("E3", SR, "under",
     "⛔⛔ THE THIRD THING GOES ENTIRELY and every screen is a dead end again — "
     "the exact state this wave exists to end, on all seven chat doors at once",
     [('    pub = _public_offer_lines()\n',
       '    pub = []\n')]),
    ("E4", SR, "under",
     "⛔⛔ A FAILED LOOK EATS THE OFFER. The option is true whether or not the "
     "list could be fetched, so a transport hiccup silently restores one way out",
     [('        return [f"{_PUBLIC_HEAD} — ask to use somebody else’s. Say "\n'
       '                "“show me public computers” and I’ll look again."]',
       '        return []')]),
    ("E5", SR, "under",
     "⛔⛔ NOBODY OFFERING TODAY EATS THE OFFER, so the reader is told only the "
     "bad news about a route they were never told existed",
     [('        lines = [f"{_PUBLIC_HEAD} — ask to use somebody else’s. Nobody is "\n'
       '                 "offering one publicly right now.",\n'
       '                 _PUBLIC_NONE_WHY]',
       '        lines = [_PUBLIC_NONE_WHY]')]),
    ("E6", SR, "under",
     "the lead is dropped, so the sign-in announce stops naming the topic that "
     "has nowhere to run and reads as an unprompted lecture about hardware",
     [('    lines = [lead] if lead else []', '    lines = []')]),
    ("E7", SR, "under",
     "the install page leaves the add line, so somebody with NO machine at all is "
     "offered an access code from a computer that is not running anything",
     [('_ADD_A_COMPUTER = (f"Add a computer: set one up at {_INSTALL_PAGE_URL}, then send "',
       '_ADD_A_COMPUTER = ("Add a computer: send "')]),
    ("E8", SR, "over",
     "the add line leads, so the step arrives before the sentence that says what "
     "happened — a next step for a state the reader has not been told about",
     [('    lines.append("No research computer on this account yet.")',
       '    lines.append(_ADD_A_COMPUTER)\n'
       '    lines.append("No research computer on this account yet.")'),
      ('    lines.append(_ADD_A_COMPUTER)\n'
       '    pub = _public_offer_lines()\n',
       '    pub = _public_offer_lines()\n')]),

    # ═══════════ L — the list, which is what makes it a next step ════════════
    ("L1", SR, "under",
     "⛔⛔ THE OFFER KEEPS ITS SENTENCE AND LOSES ITS ROWS. \"Or ask for a public "
     "one\" with nothing named is advice, and the reader has no id to hand back",
     [('                 "offer right now:"]\n'
       '    lines += _public_rows_block(rows)\n',
       '                 "offer right now:"]\n')]),
    ("L2", SR, "under",
     "⛔⛔ THE ID LEAVES THE ROW EVEN WHERE LABELS COLLIDE — every unnamed machine "
     "reads as the identical string, so nothing identifies a row",
     [('    return f"  • {label}{dot}{full}" + (f"  (id {d.get(\'deviceId\')})" if show_id else "")',
       '    return f"  • {label}{dot}{full}"')]),
    ("L3", SR, "under",
     "⛔ THE `full` MARKER GOES, so a machine that will certainly refuse is "
     "offered as a choice and the ask spends one of five an hour on a known no",
     [('    full = " · can’t take anyone else" if d.get("full") else ""',
       '    full = ""')]),
    ("L4", SR, "under",
     "online/offline leaves the row, so a machine that cannot answer today looks "
     "the same as one that can",
     [('    dot = " · online" if d.get("online") else " · offline"', '    dot = ""')]),
    ("L5", SR, "under",
     "truncation is unreported beside a short list, so \"these are on offer\" "
     "reads as the whole story when the scan filled up",
     [('    if body.get("truncated"):\n'
       '        lines.append(_PUBLIC_TRUNCATED_SOME)\n'
       '    lines.append("")\n'
       '    lines.append(_PUBLIC_ASK_INVITE)',
       '    lines.append("")\n'
       '    lines.append(_PUBLIC_ASK_INVITE)')]),
    ("L6", SR, "under",
     "⛔⛔ TRUNCATION IS UNREPORTED ON THE EMPTY BRANCH — the branch where it "
     "matters most, because zero rows over a filled scan means everything found "
     "was filtered out and \"nobody is offering\" is then definitely wrong",
     [('        if body.get("truncated"):\n'
       '            lines.append(_PUBLIC_TRUNCATED_NONE)\n'
       '        return lines', '        return lines')]),
    ("L7", SR, "under",
     "the invitation and its disclosure go, so a list of strangers' machines is "
     "printed with no word about what asking for one tells them",
     [('    lines.append(_PUBLIC_ASK_INVITE)\n    return lines', '    return lines')]),
    ("L8", SR, "under",
     "the row guard goes, so one non-dict row from the app takes down a screen "
     "that was answering something else entirely",
     [('    rows = [d for d in (body.get("devices") or []) if isinstance(d, dict)]\n    if not rows:\n        # ⛔⛔ THE THIRD THING',
       '    rows = body.get("devices") or []\n    if not rows:\n        # ⛔⛔ THE THIRD THING')]),
    ("L9", SR, "over",
     "⛔ THE SECOND LOOK GETS THE BROWSE COMMAND'S OWN BUDGET, so a slow app can "
     "hold open an answer the reader asked a different question to get",
     [('_PUBLIC_LOOK_TIMEOUT = 20', '_PUBLIC_LOOK_TIMEOUT = 40')]),
    ("L10", SR, "under",
     "the empty-public branch drops the option and keeps only the bad news",
     [('        lines = [f"{_PUBLIC_HEAD} — ask to use somebody else’s. Nobody is "\n'
       '                 "offering one publicly right now.",\n',
       '        lines = ["Nobody is offering one publicly right now.",\n')]),
    ("L11", SR, "over",
     "⛔⛔ THE EMPTY STATE STOPS SHARING THE BROWSE SCREEN'S ROW RENDERER and "
     "writes its own. That is exactly how ten wordings of one fact came to exist; "
     "extracting a helper does not test it, so this asks whether BOTH consumers "
     "still read it",
     [('                 "offer right now:"]\n'
       '    lines += _public_rows_block(rows)\n',
       '                 "offer right now:"]\n'
       '    lines += [f"  • {d.get(\'label\')}" for d in rows]\n')]),

    # ═══════════ T — the terminal, which had the emptiest screen of all ══════
    ("T1", CLI, "under",
     "⛔⛔ THE TERMINAL GOES BACK TO ONE SENTENCE WITH NO NEXT STEP — no pair "
     "code, no install link, no mention that somebody else's machine can be asked "
     "for. Nothing pinned that line before this wave",
     [('    if not devices:\n        _print_no_devices()\n        return 0',
       '    if not devices:\n        print("No devices reachable by this account.")\n        return 0')]),
    ("T2", CLI, "under",
     "the terminal keeps the offer and loses the list, so the reader is told to "
     "ask for a computer and given no id to ask for",
     [('          "now:")\n'
       '    for i, d in enumerate(rows, 1):\n'
       '        print(_public_row(i, d))\n',
       '          "now:")\n')]),
    ("T3", CLI, "under",
     "a failed look eats the terminal's offer too, on the one surface where the "
     "reader cannot simply ask again in words",
     [('        print("  Public computers — ask to use somebody else\'s:  "\n'
       '              "agent device public")\n'
       '        return\n',
       '        return\n')]),
    ("T4", CLI, "over",
     "⛔ THE TERMINAL INVENTS A THIRD NAME FOR THE CODE. The chat client, the "
     "watcher and SKILL.md all say \"8-character access code\"",
     [('    print("                       add the 8-character access code the computer shows")',
       '    print("                       add the 8-character code the computer shows")')]),
    ("T5", CLI, "over",
     "⛔⛔ THE TERMINAL'S INVITATION SAYS \"your name and email address\" AGAIN — "
     "wrong twice, and the phrasing the chat confirm was corrected away from in "
     "7.9-2 while this screen kept saying it",
     [('_PUBLIC_ASK_INVITE_T = ("     Its owner decides. They see your name — or your "\n                        "email, if you have not set one.")',
       '_PUBLIC_ASK_INVITE_T = "     Its owner decides. Asking tells them your name and email address."')]),

    # ═══════════ W — the two surfaces delivered word for word ════════════════
    ("W1", BRIDGE, "under",
     "⛔⛔ THE WIRE SENTENCE DROPS THE SECOND WAY OUT. The terminal reads NONE of "
     "the reason codes and prints this English verbatim, so this is the only "
     "thing a person running a research command on an empty account is told",
     [('                                          "it here (agent device add <code>), or ask "\n                                          "to use somebody else\'s (agent device public)"})',
       '                                          "it here (agent device add <code>)"})')]),
    ("W2", WATCH, "under",
     "⛔⛔ THE WATCHER DROPS IT TOO. It runs with `no_agent`, so its text reaches "
     "the person with no model turn to launder it — and it is PROACTIVE, which "
     "makes it the one screen somebody reads without having asked anything",
     [('            f"Connection)\\n\\n"\n'
       '            f"Public computers — ask to use somebody else\'s. Ask me for the "\n'
       '            f"public computers and I\'ll list the ones on offer. Tell me which one "\n'
       '            f"to ask for. Once the request is accepted you can use that computer. "\n'
       '            f"They see your name — or your email, if you have not set one."\n',
       '            f"Connection)"\n')]),
    ("W3", BRIDGE, "under",
     "the wire sentence loses the add-a-computer half instead, so somebody who owns "
     "a machine already is sent to ask a stranger for one, and somebody with none "
     "is never given the page",
     [('                                 "error": "no research computer on this account yet "\n                                          "— set one up at "\n                                          "https://superresearch.io/install, then "\n                                          "grab the access code from its screen (or "\n                                          "one a computer\'s owner gave you) and add "\n                                          "it here (agent device add <code>), or ask "',
       '                                 "error": "no research computer on this account yet "\n                                          "— ask "')]),

    # ═══════════ R — the routing: the rule that did not exist, and the six ═══
    #               hand-written noun lists the last wave's comment claimed
    #               were already unified.
    ("R1", SR, "under",
     "⛔⛔ THE RULE GOES AND \"I don't have a computer of my own\" REACHES THE "
     "CATCH-ALL AGAIN — the phrasing SKILL.md gives as its own worked example, "
     "and the one sentence a person with nothing actually says",
     [('    if not _artefact_kw and (re.search(\n            rf"\\b(?:i (?:do not|don\'?t|dont) have|i have no|i haven\'?t got"\n            rf"|i\'?ve got no|i (?:do not|don\'?t|dont) own)\\b[^.?!]*"\n            rf"\\b(?:{_MACHINE_NOUNS_SAID})\\b", low)\n            # ⛔⛤ AND THE BARE FORM OF THE SAME SENTENCE. SKILL.md teaches\n            # "no devices — set one up" and it reached the catch-all: the\n            # negation vocabulary above is all first-person, and a person\n            # reporting the state does not always put themselves in it.\n            or re.fullmatch(rf"(?:no|zero|0)\\s+(?:{_MACHINE_NOUNS_SAID})\\b"\n                            rf"[^.?!]{{0,32}}", low)):\n        return ["devices"], None\n\n',
       '')]),
    ("R2", SR, "over",
     "⛔⛔ IT ANSWERS FROM THE PUBLIC LIST INSTEAD OF THE ACCOUNT'S OWN. That "
     "list structurally cannot contain the asker's machine, so somebody who DOES "
     "have one is told to go and ask a stranger",
     [('    if not _artefact_kw and (re.search(\n            rf"\\b(?:i (?:do not|don\'?t|dont) have|i have no|i haven\'?t got"\n            rf"|i\'?ve got no|i (?:do not|don\'?t|dont) own)\\b[^.?!]*"\n            rf"\\b(?:{_MACHINE_NOUNS_SAID})\\b", low)\n            # ⛔⛤ AND THE BARE FORM OF THE SAME SENTENCE. SKILL.md teaches\n            # "no devices — set one up" and it reached the catch-all: the\n            # negation vocabulary above is all first-person, and a person\n            # reporting the state does not always put themselves in it.\n            or re.fullmatch(rf"(?:no|zero|0)\\s+(?:{_MACHINE_NOUNS_SAID})\\b"\n                            rf"[^.?!]{{0,32}}", low)):\n        return ["devices"], None\n\n',
     # ⛔ REPAIRED 2026-09-17 — ONE CHARACTER, `low)` -> `low))`. Wave 1.2 wrapped
     # this rule's condition in a second pair of parens and re-anchored R2 onto
     # the new shape, but the REPLACEMENT still closed only the inner `re.search(`
     # — so the mutated file had an unclosed `(` and R2 has measured nothing since
     # 2026-09-12. The MUTATION is untouched: the rule still answers from the
     # PUBLIC list, which structurally cannot hold the asker's own machine.
       '    if not _artefact_kw and (re.search(\n            rf"\\b(?:i (?:do not|don\'?t|dont) have|i have no|i haven\'?t got"\n            rf"|i\'?ve got no|i (?:do not|don\'?t|dont) own)\\b[^.?!]*"\n            rf"\\b(?:{_MACHINE_NOUNS})\\b", low)):\n        return ["devices-public"], None\n')]),
    ("R4", SR, "under",
     "the add/pair guard reverts to the narrow list, so \"add my mac\" and "
     "\"connect my workstation\" reach the catch-all — which then offers to "
     "manage devices, the thing it has just failed to do",
     [('            (re.search(rf"\\b(add|pair|connect)\\b.*\\b({_MACHINE_NOUNS_SAID})\\b", low)',
       '            (re.search(r"\\b(add|pair|connect)\\b.*\\b(device|node|machine|pc|computer)\\b", low)')]),
    ("R5", SR, "under",
     "the device-list clause reverts, so \"show my computers\" and \"which "
     "machines do I have\" reach the catch-all",
     [('    _list_wide = re.search(rf"\\b(which|what|list|show|my)\\b.*\\b({_MACHINE_NOUNS_SAID})\\b", low)',
       '    _list_wide = None')]),
    ("R6", SR, "under",
     "⛔⛔ THE CATEGORY GUARD REVERTS AND \"ask for a public mac\" RAISES THE "
     "DISCLOSING CONSENT QUESTION about a machine called “public mac”. That is "
     "the 7.9-2 defect whose repair comment sits thirty lines above it",
     [('        or re.fullmatch(rf"{_CATEGORY_DET}+(?:{_MACHINE_NOUNS})", _ask_obj, re.I)\n'
       '        or (re.fullmatch(rf"(?:{_MACHINE_NOUNS})", _ask_obj, re.I)\n'
       '            and _ask_obj_generic_det))', '        )')]),
    ("R7", SR, "under",
     "the ASK branch's leading-noun strip goes, so a category ask carries the "
     "noun into the name it quotes back",
     [('        _ask_obj = _strip_leading_noun(_ask_obj)',
       '        pass')]),
    ("R8", SR, "under",
     "the SWITCH branch's strip goes, so \"switch to the mac LABPC001\" looks up "
     "a device called \"mac LABPC001\"",
     [('        name = _strip_leading_noun(name)\n        if _is_bare_machine_noun(name):\n',
       '        if _is_bare_machine_noun(name):\n')]),
    ("R9", SR, "under",
     "⛔ THE UNLINK BRANCH'S STRIP GOES — the DESTRUCTIVE one, whose confirm then "
     "quotes a name its own follow-up cannot resolve",
     [('        name = _strip_leading_noun(name)\n        # ⛔⛔ AND NOT "that device" EITHER.',
       '        # ⛔⛔ AND NOT "that device" EITHER.')]),
    ("R10", SR, "under",
     "⛔⛔ THE LIST CLAUSE LOSES ITS ACTION GATE and swallows the verbs below it: "
     "\"remove my mac\" prints a list instead of unlinking. That defect was LIVE "
     "for the narrow list (\"remove my node\") and widening the nouns without "
     "this gate spreads it to five more words",
     [('    if (not _dev_verb and (_list_narrow or (_list_wide and _wide_is_clean))) or \\',
       '    if (_list_narrow or (_list_wide and _wide_is_clean)) or \\')]),
    ("R11", SR, "under",
     "the list clause loses its artefact gate, so \"ask for the podcast on my "
     "computer\" becomes a request to list devices and the podcast rule below "
     "never sees it",
     [('    if (not _dev_verb and (_list_narrow or (_list_wide and _wide_is_clean))) or \\',
       '    if (not _dev_verb and (_list_narrow or _list_wide)) or \\')]),
    ("R12", SR, "under",
     "⛔⛔ A BARE NOUN IS A NAME AGAIN. \"remove my mac\" offers to unlink a "
     "machine called “mac” — a DESTRUCTIVE confirm whose own yes resolves to "
     "\"No device matching “mac”\"",
     [('    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*[-_][A-Za-z0-9_-]*[A-Za-z0-9]", w))\n\n',
       '    return False')]),
    ("R13", SR, "under",
     "`phone` drops out of the bare-noun test, and the unlink rule admits it as a "
     "thing people say while nothing in this product is one — so \"remove my "
     "phone\" quotes “phone” back as a machine",
     [('    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*[-_][A-Za-z0-9_-]*[A-Za-z0-9]", w))\n\n',
       '    return bool(re.fullmatch(\n        rf"(?:(?:all|every|each|both)\\s+(?:my\\s+|the\\s+|of\\s+my\\s+)?)?"\n        rf"(?:{_MACHINE_NOUNS})", (name or "").strip(), re.I))')]),
    ("R14", SR, "under",
     "⛔⛔ THE DETERMINER CHECK GOES, so \"ask for a mac\" is a NAME again and "
     "raises the consent question about a machine called “mac”. The capture has "
     "already eaten the determiner, which is why this has to read the message",
     [('        or (re.fullmatch(rf"(?:{_MACHINE_NOUNS})", _ask_obj, re.I)\n'
       '            and _ask_obj_generic_det))', '        )')]),
    ("R15", SR, "over",
     "⛔⛔ THE AMBIGUOUS NOUNS GO IN FLAT and a NAMED ask answers with everybody "
     "else's machines: \"request access to that Mac\" points at one row, and "
     "reading “Mac” as a category ignores it",
     [('        re.fullmatch(rf"{_CATEGORY_DET}*"\n'
       '                     r"(?:computers?|machines?|devices?|pcs?|nodes?|laptops?"\n'
       '                     r"|one|something|access|permission)",\n'
       '                     _ask_obj, re.I)',
       '        re.fullmatch(rf"{_CATEGORY_DET}*"\n'
       '                     rf"(?:{_MACHINE_NOUNS}|one|something|access|permission)",\n'
       '                     _ask_obj, re.I)')]),
    ("R16", SR, "under",
     "the switch branch stops testing for a bare noun, so \"switch to the mac\" "
     "looks up a device literally called \"mac\" and reports it missing",
     [('        if _is_bare_machine_noun(name):\n            name = ""\n', '')]),

    # ═══════════ F — the refusal a signed-out person with none actually reads ═
    ("F1", SR, "under",
     "⛔⛔ THE BRIDGE'S OWN 401 KEYS NO ROW AGAIN and falls to the fallback, so "
     "chat reads \"Couldn’t ask for your requests: not signed in — run /login\" — "
     "a terminal command, in a chat, to somebody who has neither an account "
     "session nor a computer",
     [('    if str(err).lower().startswith("not signed in"):\n'
       '        return "You’re not signed in yet — tell me to log you in and I’ll send a link."\n', '')]),
    ("F2", CLI, "under",
     "the same on the terminal, where the fallback does not even have the "
     "one-word patch its sibling had",
     [('        if err.lower().startswith("not signed in"):\n'
       '            return "not signed in — run:  agent login"\n', '')]),
    ("F3", SR, "under",
     "⛔⛔ THE PAST TENSE REACHES THE FALLBACK AGAIN. `what` has to be past tense "
     "for the rate-limit sentence, so this printed \"Couldn’t asked for your "
     "requests\" for two waves on the one screen meant to help these people",
     [('    return _PLAIN_VERBS.get(what, what)', '    return what')]),
    ("F4", SR, "over",
     "the chat refusal prints the bridge's own text, so a person talking in words "
     "is handed a slash command that belongs to the terminal",
     [('        return "You’re not signed in yet — tell me to log you in and I’ll send a link."',
       '        return f"You’re not signed in: {err}"')]),

    # ═══════════ S — the file the assistant reads to decide what to run ══════
    ("S1", SKILL, "over",
     "⛔⛔ THE ROW DOCUMENTS AN OUTPUT THE CODE HAS NEVER PRINTED AGAIN. Both "
     "clients print `public`/`private`, and this same file said so correctly "
     "ninety lines earlier — so the file disagreed with itself and with the code",
     [("the row for a computer the user OWNS says `public` or `private` (the same two words the command uses, and the web app's toggle)",
       'the row for a computer the user OWNS says `findable` or `hidden`')]),
    ("S2", SKILL, "under",
     "the deviceless row goes, so the assistant has no instruction for the one "
     "sentence this whole wave is about",
     [('| "I don\'t have a computer of my own", "I have no computer", "I haven\'t got a machine", "no devices — set one up" | `sr.py devices`',
       '| unrouted |')]),
    ("S3", SKILL, "under",
     "⛔ `install` LEAVES THE SAFE-DEFAULTS LIST, whose next clause says "
     "everything not listed runs on a clear request — and it was missing from "
     "BOTH confirm lists at HEAD while being confirm-gated in the client",
     [('`device-visibility public`, `update`, and `install`**',
       '`device-visibility public`, and `update`**')]),
    ("S4", SKILL, "under",
     "`install` leaves the Safety bullet — the third list, and the one 7.9-2 "
     "already recorded as the one people forget",
     [('  `device-deny`, `device-visibility public`, `install` (installs the backend on\n  the connected computer), and `update`',
       '  `device-deny`, `device-visibility public`, and `update`')]),
    ("S5", SKILL, "under",
     "the paragraph telling the assistant an empty account is not a dead end "
     "goes, so the model is free to relay the shortest of the ten old sentences",
     [("**An account with NO computer is not a dead end.** Every screen that reports it\nnames BOTH routes — “Add a computer: set one up at https://superresearch.io/install,\nthen send me the 8-character access code the computer shows (or one a computer's\nowner gave you)”, or ask to use somebody else's — and the full ones (`devices`,\n`research`, the sign-in announce) also LIST the public computers on offer. Relay\nthat list; never present setting up a machine as the only route.\n⛔ Keep https://superresearch.io/install inside the “Add a computer” sentence.\nThe access code comes from the person's computer at the end of that setup — never\nsay it comes from the app. The one-line sign-in confirmation names both routes\nwithout a list, which is deliberate: it must not make a second call to render one.\n\n",
       '')]),

    # ═══════════ C — the anti-drift constants ════════════════════════════════
    ("C1", SR, "over",
     "⛔⛔ THE INVITATION IS HAND-WRITTEN AGAIN IN ONE PLACE, so the browse screen "
     "and the empty state can disagree about what asking costs. Four sentences "
     "are printed by two screens each, and the anchor sweep caught me copying "
     "them by hand while building the wave that exists to stop that",
     [('    lines.append(_PUBLIC_ASK_INVITE)\n    return lines',
       '    lines.append("Tell me which one to ask for and I’ll ask its owner.")\n    return lines')]),
    ("C2", SR, "over",
     "⛔ THE SHARED SENTENCE IS SPLICED AFTER AN EM-DASH AGAIN, printing "
     "\"— A computer shows up there…\" with a capital A mid-sentence. It is "
     "written as a sentence because the browse screen uses it as one",
     [('                 "offering one publicly right now.",\n'
       '                 _PUBLIC_NONE_WHY]',
       '                 "offering one publicly right now — " + _PUBLIC_NONE_WHY]')]),

    # ═══════════ X — THE REPAIRS CROSS-VERIFICATION FORCED ═══════════════════
    #   ⛔⛔ 7.9-3's OWN RECORD IS WHY THIS SERIES EXISTS. That wave fixed 68
    #   defects found after green, verified every one BY HAND, wrote none of them
    #   down — and the harness then killed 19 mutants' worth of undefended repair.
    #   Every fix below has a guard, and every guard has a mutant here.
    ("X1", SR, "under",
     '⛔⛔ THE STRIP EATS THE FIRST WORD OF A REAL NAME AGAIN. "switch to the Mac Studio" reaches for “Studio”, "remove my MacBook Air" offers to unlink “Air”. Four of the widened nouns are words people put IN a machine\'s name, and cross-verify caught all three cases',
     [('    m = re.match(rf"^(?:{_NAMEABLE_NOUNS})\\s+(.+)$", whole, re.I)\n    if m and _looks_like_an_identifier(m.group(1).strip()):',
       '    m = re.match(rf"^(?:{_NAMEABLE_NOUNS})\\s+(.+)$", (name or "").strip(), re.I)\n    if m:')]),
    ("X2", SR, "over",
     'the identifier test accepts any single token, so “Studio” and “Air” are read as ids and stripped — the same defect one rung in',
     [('    if not any(c.isalpha() for c in rest):\n        return False\n    return rest.isupper() or any(c.isdigit() for c in rest)',
       '    return True')]),
    ("X3", SR, "under",
     '⛔⛔ THE NO-COMPUTER RULE LOSES ITS LAST GUARD and answers "I don\'t have the report from my laptop" with a device list — a wrong answer where the catch-all would at least be an honest one',
     # ⛔ REPAIRED 2026-09-17 — the replacement KEEPS THE OPEN PAREN. Wave 1.2
     # wrapped this condition in a second pair of parens; the re-anchor picked up
     # the new anchor and dropped the `(` from the replacement, so the mutated
     # file carried an unmatched `)` and X3 has measured nothing since
     # 2026-09-12. The MUTATION is untouched: `not _artefact_kw and` goes, which
     # is the rule's last guard.
     [('    if not _artefact_kw and (re.search(',
       '    if (re.search(')]),
    ("X4", SR, "under",
     '⛔⛔ THE ARTEFACT GATE APPLIES TO THE WHOLE LIST CLAUSE AGAIN, so "which device is my run on", "list my devices and runs" and "show me my devices and their status" fall into the catch-all that boasts it can manage devices',
     [('    _list_narrow = re.search(r"\\b(which|what|list|show|my)\\b.*\\b(devices?|nodes?)\\b", low)',
       '    _list_narrow = None')]),
    ("X5", SR, "under",
     '`running` leaves the wide clause\'s bail, so "what\'s running on my mac" — a question about RUNS — is answered with an inventory',
     [('    _wide_is_clean = (not _artefact_kw and not _control_kw\n                      and not re.search(r"\\brunning\\b", low))',
       '    _wide_is_clean = (not _artefact_kw and not _control_kw)')]),
    ("X6", SR, "under",
     '⛔⛔ THE ADD/PAIR GUARD LOSES ITS RESEARCH BAIL and answers a research topic with "paste the access code" — it sits ABOVE the research rule',
     [('    elif (not _NL_RESEARCH_RE.match(t)) and (\n',
       '    elif (\n')]),
    ("X7", SR, "under",
     '`run on` goes back to bare, so "which device is my run ON" is treated as a switch and the inventory question it is reaches nothing',
     [('    _dev_verb = re.search(rf"\\b(?:{_UNLINK_VERBS[3:-1]}|add|pair|connect|"\n                          rf"switch to)\\b|\\brun (?:it |everything )?on\\s+\\S", low)',
       '    _dev_verb = re.search(r"\\b(remove|unlink|forget|delete|add|pair|connect|"\n                          r"switch to|run on)\\b", low)')]),
    # ⛔⛔ X8 IS RETIRED, NOT MOVED — 7.9-5b, 2026-09-10. It mutated the body of
    # `_is_bulk_machine_phrase`, which has been FOLDED INTO the one predicate
    # `_names_a_set`: 7.9-5 had added a second answer to the same question and the
    # two disagreed, and duplication is what produced an equivalent mutant twice
    # in the Gemini wave. Repointing X8 at the folded predicate would make it a
    # duplicate of that wave's P1/P2/P3 and S1, and an equivalent mutant is a
    # harness bug that inflates a score rather than measuring anything.
    # ⭐ THE PROPERTY IT ASSERTED IS STILL PINNED, in two places:
    #   · wave795b_bulk_gate_0910_mutants.py  S1  — the unlink call site,
    #   · agent/tests/test_bulk_gate_0910.py::test_there_is_one_predicate_for_this_question_not_two
    #     — which asserts the fold kept every shape 7.9-4's gate answered.
    ("X9", SR, "over",
     'the bulk answer becomes "which one?", which hides that unlink takes exactly one machine and the request as made cannot be carried out at all',
     [('            return None, ["I unlink one computer at a time. Ask me to list them and "\n                          "name the one to remove — nothing is removed until you do."]',
       '            return None, ["Which computer should I unlink?"]')]),
    ("X10", SR, "under",
     'the determiner strip narrows back to `the|my`, so "remove that computer" and "unlink their laptop" carry the word into a DESTRUCTIVE confirm',
     # ⛔⛔ RE-ANCHORED ONTO THE SITE THE WHY-LINE IS ABOUT, 2026-09-17. The
     # anchor had been re-pointed at the SWITCH-TO capture four lines up — a
     # different branch, already mutated by wave12_router_captures N-series — while
     # the replacement stayed the UNLINK branch's old narrow strip at its 8-space
     # indent. So the mutant emitted the unlink line into the switch statement and
     # has not parsed since 2026-09-12. `remove that computer` and `unlink their
     # laptop` are unlink phrasings, and the source comment at the unlink capture
     # names them word for word. ⭐ The anchor is now the ONE LINE that carries
     # the determiner, so a re-wrap of the verb list above it cannot break it
     # again — the long anchor is what broke.
     [('                      rf"(?:{_NAME_DETERMINER}\\s+)?(.+)$",',
       '                      rf"(?:the\\s+|my\\s+)?(.+)$",')]),
    ("X11", SR, "under",
     'the quote strip goes and the confirm prints a doubled name — this client tells people to reply with the name in quotes',
     [('        name = _quoted_name(t) or name.strip().strip(_NL_QUOTE_CHARS).strip()\n        # ⛔⛤ THE DESTRUCTIVE CONFIRM QUOTED THE WHOLE SENTENCE. This site ran to\n',
       '')]),
    ("X12", SR, "under",
     "⛔⛔ --json PAYS FOR LINES IT THROWS AWAY: up to twenty seconds of wall clock on the STREAMING CRON's own invocation, every minute, to build a string `_emit` discards",
     [('    if not _RENDERING_LINES:\n        return []\n',
       '')]),
    ("X13", SR, "under",
     'the browse screen loses its row guard again, so one non-dict row from the app takes it down while the empty state beside it survives',
     [('    rows = [d for d in (body.get("devices") or []) if isinstance(d, dict)]\n    if not rows:\n        lines = ["Nobody is offering',
       '    rows = body.get("devices") or []\n    if not rows:\n        lines = ["Nobody is offering')]),
    ("X14", SR, "under",
     '⛔ A LIST OF NOTHING BUT FULL MACHINES CALLS ITSELF AN OFFER, and every ask it invites is a certain `share_cap_reached`',
     [('    if all(d.get("full") for d in rows):\n'
       '        lines = [f"{_PUBLIC_HEAD} — ask to use somebody else’s, but every "',
       '    if False:\n'
       '        lines = [f"{_PUBLIC_HEAD} — ask to use somebody else’s, but every "')]),
    ("X15", SR, "under",
     'a rate-limited look is reported as a failed one, so the reader is told to ask again immediately and spends another look on the same refusal',
     [('        if isinstance(body, dict) and body.get("error") == "rate_limited":\n'
       '            return [f"{_PUBLIC_HEAD} — ask to use somebody else’s. "\n'
       '                    f"{said}"]\n',
       '')]),
    ("X16", SR, "under",
     '⛔⛔ THE DEVICE LIST RELAYS THE BRIDGE\'S TERMINAL SYNTAX INTO CHAT — "not signed in — run /login" — and this wave made this command the answer to "I have no computer", so it hits exactly the people it was written for',
     [('        return _emit(body, args.json, [f"✗ {_signed_out_or(body.get(\'error\', code))}"],',
       '        return _emit(body, args.json, [f"✗ {body.get(\'error\', code)}"],')]),
    ("X17", WATCH, "under",
     '⛔⛔ THE WATCHER DROPS THE EMAIL HALF OF THE DISCLOSURE. Somebody who never set a display name is told a stranger sees their NAME when the product hands over their EMAIL — and this surface reaches them verbatim, with no model turn',
     [('            f"They see your name — or your email, if you have not set one."\n',
       '            f"They see your name."\n')]),
    ("X18", BRIDGE, "under",
     "the wire's two commands lose their program name, so neither is runnable as printed on the one surface that prints this sentence verbatim",
     [('                                          "it here (agent device add <code>), or ask "\n                                          "to use somebody else\'s (agent device public)"})',
       '                                          "it here (device add <code>), or ask "\n                                          "to use somebody else\'s (device public)"})')]),
    ("X19", CLI, "under",
     "the terminal loses the route for somebody with NO machine at all — the "
     "install page — from the add line, the one place its empty state names it",
     [('    print("  Add a computer:      set one up at https://superresearch.io/install, then")\n',
       '    print("  Add a computer:")\n')]),
    ("X20", CLI, "over",
     'the terminal looks AFTER it starts printing again, so it emits three lines and then blocks for up to twenty seconds mid-message',
     [('    res = _bridge_get("/devices/public", timeout=20.0)\n    print("No research computer on this account yet.")',
       '    print("No research computer on this account yet.")\n    res = _bridge_get("/devices/public", timeout=20.0)')]),
    ("X21", SR, "under",
     '`phone` leaves the strip while staying in the bare test, so "remove my phone LABPC001" quotes “phone LABPC001” back',
     [('_NAMEABLE_NOUNS = r"pcs?|laptops?|macs?|macbooks?|desktops?|workstations?|phones?"',
       '_NAMEABLE_NOUNS = r"pcs?|laptops?|macs?|macbooks?|desktops?|workstations?"')]),
    # ⛔ X22 RETIRED 2026-09-24 — ITS SUBJECT WAS REMOVED BY THE OWNER, NOT BY DRIFT.
    # It guarded the invitation offering "the id beside it". On 2026-09-20 the owner
    # asked for the invitation to name no id ("it's quite confusing") and to keep
    # only "they see your name"; the id now appears on a row ONLY when two labels
    # collide (`_public_rows_block`), which L2 and wave792 P11 still measure. A
    # mutant re-aimed onto some other sentence would be a different mutant under
    # an old name, so it is retired rather than moved.
    ("X23", SKILL, "under",
     '⛔ SKILL.md NAMES THE NO-COMPUTER SCREEN BY A STRING NO SURFACE PRINTS ANY MORE, so the rule that keeps `install` OFF that screen — the one where a brand-new person meets the install page — cannot be recognised',
     [('  says **"no research computer on this account yet"** (reason `no_devices`): that',
       '  says "no devices yet" (reason `no_devices`): that')]),
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


def run_tests(filtered: bool) -> bool:
    purge_pycache(AGENT)
    py = str(AGENT / ".venv" / "bin" / "python")
    suites = MINE.split() if filtered else [ALL_SUITES]
    out = _pytest([py, "-B", "-m", "pytest", *suites, "-q", "-p", "no:cacheprovider"],
                  AGENT, ENV)
    if out == "nothing-collected":
        raise AssertionError("the agent leg collected NO tests — check the selection")
    return out == "green"


def _selected_count() -> int:
    py = str(AGENT / ".venv" / "bin" / "python")
    out = sh([py, "-B", "-m", "pytest", *MINE.split(), "--collect-only", "-q",
              "-p", "no:cacheprovider"], cwd=AGENT, env=ENV).stdout
    m = _re.search(r"^(\d+) tests? collected", out, _re.M)
    return int(m.group(1)) if m else 0


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]

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

    if not unfiltered:
        n = _selected_count()
        print(f"the wave's own files collect {n} test(s)")
        if n < MIN_SELECTED:
            print(f"⛔⛔ TOO FEW (need >= {MIN_SELECTED}) — a selection that matches "
                  "nothing exits 5 and scores every mutant killed. Refusing to run.")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    if not run_tests(filtered=not unfiltered):
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
            killed = not run_tests(filtered=not unfiltered)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                again = not run_tests(filtered=not unfiltered)
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
