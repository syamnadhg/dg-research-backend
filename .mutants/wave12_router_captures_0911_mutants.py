"""Mutation harness for wave 1.2 — THE CAPTURES, 2026-09-11.

⛔⛔ WHAT WAVE 1.2 MEASURED. 7,091 phrases BUILT from targets whose expected name
is known by construction, so every defect is COMPUTED and not eyeballed. Only
2,428 came out right — 34%. 73 distinct defects after dedup by subject. Wave 1.1
pinned whether the router ACTS; this pins what it acts ON, and the seam is what
makes a diff in either attributable to one kind of change.

⭐⭐ OWNER'S RULE, 09-09: THE MUTANTS COME FROM THE MEASURED FINDINGS, NOT FROM THE
REPAIR LIST. Every entry below says what its finding DID when it was reproduced
against the live resolver before a line of the repair existed.

⭐⭐ THE DIRECTION LABELS:

    "over"  · the capture takes TOO MUCH or fires where it should not — a trim
              that eats a real machine name, a signal that steals a browse
              request, a veto that refuses one honest ask.
    "under" · back toward the measured defect — a politeness word welded into a
              name, a dropped name, a dead phrasing, a paid run nobody asked for.

⭐⭐ THE ONES THAT MATTER MOST, AND WHY:

  Q1     — ⛔⛔⛔ THE ONLY DEFECT IN THIS WAVE THAT ACTED ON THE WRONG MACHINE.
           The quoted span was a CHARACTER CLASS, so an apostrophe inside a name
           terminated it: `hide "Sam's MacBook Pro"` captured “Sam”, which then
           SUBSTRING-MATCHED a different machine and hid it, with a ✓. Measured
           on an account holding only “Donna Mac”. `<First>'s MacBook Pro` is what
           a Mac calls itself out of the box, and the curly ’ — what phones type —
           behaves identically.
  V5     — ⛔⛔ `un-delist my Studio PC` HID THE MACHINE. The un- guard sat on one
           arm of the hide signal and `delist|disable|unshare|deregister` lived in
           a second arm without it, so the person asked to un-hide and got a hide
           while `un-unlist` correctly published.
  T1     — the politeness trim goes and 592 of 7,091 phrasings break on one
           courteous word: `hide my mac please` refuses a machine `hide my mac`
           hides.
  S2     — `research my devices` STARTS A PAID RUN titled “my devices”. The
           research branch took 100% of research-verb openings, 392 of 392.
  S6/S7  — a code-shaped token in a sentence about an existing machine PAIRED it:
           a run-stop, a consent decision, and a SUPPORT code the document teaches
           in two places and which is not a pair code at all.
  K3     — a person could not skip a phase of any run but the newest active one,
           from chat, AT ALL. Nineteen phrasings dropped the name.
  K6     — `skip all but the podcast` SKIPPED THE PODCAST.
  L3/L4  — ⛔ MY OWN NEW STRIP EATING A REAL NAME, both caught by tests I wrote in
           the same hour: `my Nodes Mac` lost its name because the remainder was
           a bare noun, and `"Nodes & Bolts"` came out “& Bolts” because a `\\b`
           after a symbol never matches.
  S9/R8  — ⛔ MY OWN NEW VETO AND MY OWN NEW PEEL, TOO WIDE, both caught by the
           A/B before they shipped: the compound rule refused four real phrasings
           including one the document teaches, and the feature-word peel turned
           `hide Sharing Mac` into “Mac”.

    python .mutants/wave12_router_captures_0911_mutants.py
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

SR = "agent/facade/skill/scripts/sr.py"
SKILL = "agent/facade/skill/SKILL.md"
OURS = (SR, SKILL)

# ⛔ ONE LEG. Everything this wave touches lives under the skill, which the AGENT
# suite reads; the root suite never imports it, so a root-leg run would score
# every mutant killed against tests that cannot see the file.
ROOT_LEG_FILES: "tuple[str, ...]" = ()

MINE_AGENT = ("tests/test_router_captures_0911.py "
              "tests/test_router_gates_0911.py "
              "tests/test_chat_owner_793.py "
              "tests/test_chat_public_792.py "
              "tests/test_chat_picker_791.py "
              "tests/test_sr_do.py "
              "tests/test_sr_skip_agents.py "
              "tests/test_unlink_copy_795.py "
              "tests/test_routing_794.py "
              "tests/test_owner_verbs_793.py "
              "tests/test_bulk_gate_0910.py "
              "tests/test_empty_state_794.py "
              "tests/test_skill_commands_resolve.py")
MINE_ROOT = "tests/"
MIN_SELECTED_AGENT = 1400
MIN_SELECTED_ROOT = 1

ALL_AGENT = "tests/"
ALL_ROOT = "tests/"

# ⛔⛔⛔ EIGHT MUTANTS RETIRED AS SUBSUMED, AND THE RETIREMENT IS ITSELF A FINDING.
# Each pins a guard that a LATER, STRONGER guard — added in the cross-verify round
# — now covers completely, and the harness proved it: probed with thirteen inputs
# aimed at exactly what each one touches, not one changed an outcome. A guard that
# cannot change an outcome is dead code, and dead code in this file is what every
# "the comment claimed a unification that had not happened" note is about.
#   T4  -> the trim's own quoted bypass (Y3). The second copy of the condition was
#          DELETED; this is what remains of it.
#   D2  -> `_quoted_name` winning outright at switch/unlink (X1, X2) makes the
#          edge-strip fallback unreachable for a quoted name.
#   R6  -> `_names_a_machine` (Y1) rejects every copula span the guard did.
#   V17 -> the verb-initial `link` arm (Y14) admits it whatever the first arm holds.
#   S9  -> narrowing the compound SECOND-verb list (Y10) makes the head narrowing
#          unable to matter.
#   K14 -> the bare arm's object requirement (Y19) already refuses `skip nothing`.
#   E7  -> the machine-noun requirement on `use` (Y4) subsumes the stop-list.
#   V15 -> `drop`'s membership of the device and unlink verbs routes every
#          `drop <machine>` phrasing whether the control-word veto fires or not.
# ⭐ THEY STAY IN THE FILE, not deleted, because each names a real defect and the
# next person to widen one of those guards needs the sentence. Pass the id to run
# one: `python <harness>.py T4`.
_SOLO: "set[str]" = {"T4", "D2", "R6", "V17", "S9", "K14", "E7", "V15"}

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")


MUTANTS = [
    ('T1', SR, 'under',
     '⛔⛔ THE POLITENESS TRIM GOES, and 592 of 7,091 driven phrasings break on one courteous word. `hide my mac please` captured “mac please”, which resolves to nothing — so a command that WORKED without the word REFUSED with it, on six separate capture sites',
     [('        stripped = _NAME_TAIL_SPACED.sub("", out).strip()\n        if stripped == out or not stripped:\n            break',
       '        stripped = out\n        if True:\n            break')]),
    ('T2', SR, 'under',
     '⛔ THE TRIM STOPS LOOPING, so stacked politeness survives: `hide my Studio PC now, thanks` keeps “, thanks”. People stack these words constantly and one pass is not enough',
     [('        commaed = _NAME_TAIL_COMMAED.sub("", out).strip()\n        if commaed and commaed != out:\n            out = commaed\n            continue',
       '        commaed = out\n        if False:\n            out = commaed\n            continue')]),
    ('T3', SR, 'under',
     '⛔⛔ THE TAIL WORDS STOP DERIVING FROM THE SET HEAD and shrink to the two obvious ones. This is the 7.9-5b failure exactly: a hand-written list goes short, silently, because a missing word looks like a word nobody says. `today`, `now`, `also`, `instead`, `again`, `anymore`, `alone` and `too` all weld back onto names',
     [('_NAME_TAIL_ALWAYS = rf"(?:please|{_POLITE_TAIL[3:-1]})"',
       '_NAME_TAIL_ALWAYS = r"(?:please|thanks)"')]),
    ('T4', SR, 'over',
     '⛔⛔ THE QUOTED NAME LOSES ITS EXEMPTION and the trim runs on it too — so the ONE escape hatch this wave gives a person whose machine is genuinely called “Studio PC Now” is gone. Quoting is what the picker itself tells people to type. My own test caught this the first time',
     [('            if not _vis_quoted and (re.fullmatch(',
       '            if (re.fullmatch(')]),
    ('T5', SR, 'under',
     '⛔⛤ THE CONSENT SURFACE LOSES THE TRIM. `approve Sam please` asked “Say yes to “Sam please”?” and `approve Sam and show me the rest` asked about “Sam and show me the rest” — a CONSENT decision quoting a person who does not exist',
     [('            _who = _trim_trailing_clause(_who, t)',
       '            _who = _who')]),
    ('T6', SR, 'under',
     '⛔⛤ THE ASK SURFACE GOES BACK TO ITS PRIVATE FIVE-PHRASE LIST, which went short by four: `today`, `now`, `pls` and `ok` all survived into the name and into the lookup',
     [('        _ask_obj = _trim_trailing_clause(_ask_obj, t)',
       '        _ask_obj = re.sub(r"[,;]?\\s+(?:please|thanks|thank you|for me|"\n                          r"if (?:i|you) (?:can|could|may|would))\\s*$", "",\n                          _ask_obj, flags=re.I).strip()')]),
    ('T7', SR, 'under',
     '⛔⛔ THE DESTRUCTIVE CONFIRM LOSES THE TRIM. `remove my Studio PC please` offered to unlink “Studio PC please”; `remove my Studio PC and show me the rest` offered to unlink the whole sentence. Saying yes to that confirm rotates a pair code',
     [('        name = _trim_trailing_clause(name, t)\n        # ⛔ A LEADING DEVICE NOUN IS NOT PART OF THE NAME. "switch to the machine',
       '        name = _strip_leading_noun(name)')]),
    ('T8', SR, 'under',
     '⛔⛔ THE BRANCH THAT MUTATES WITH NO CONFIRM AT ALL LOSES THE TRIM. `switch to my Studio PC please` EXECUTED `device-use` on “Studio PC please”, and `switch to my Studio PC and show me the rest` executed on the whole clause',
     [('        name = _trim_trailing_clause(name, t)\n        # ⛔ A LEADING DEVICE NOUN IS NOT PART OF THE NAME. "switch to the machine',
       '        name = name')]),
    ('T9', SR, 'over',
     '⛔ THE NEVER-RETURN-EMPTY GUARD GOES, so a machine actually called “Please” comes back empty and the command falls to the picker — the unconfirmed-wrong-machine outcome this file exists to avoid. 7.9-5b measured it on “Not My Mac”',
     [('    return out or whole\n\n\ndef _names_a_set',
       '    return out\n\n\ndef _names_a_set')]),
    ('P1', SR, 'under',
     '⛔ THE LINKING PREPOSITION GOES BACK INTO THE NAME: `set my Studio PC to private` captures “Studio PC to”, `put my Studio PC on private` captures “Studio PC on”, `turn my Studio PC into private` captures “Studio PC into”. Only the bare-adjective form was ever clean',
     [('rf"(.+?)\\s+(?:(?:to|into|on|onto|as)\\s+)?(?:the\\s+)?"',
       'rf"(.+?)\\s+(?:the\\s+)?"')]),
    ('P2', SR, 'under',
     '⛔ THE POLARITY LIST IN THE CAPTURE STOPS DERIVING and goes back to six hand-typed words — short by `visible`, which is half of why `make my mac visible` answered with a device LIST',
     [('rf"(?:{_NEG_WORDS}\\s+)?(?:be\\s+|being\\s+|stay\\s+|"\n                            rf"remain\\s+)?{_VIS_POLARITY_ALL}\\b", t, flags=re.I)',
       'rf"(?:{_NEG_WORDS}\\s+)?(?:be\\s+|being\\s+|stay\\s+|"\n                            rf"remain\\s+)?(?:public|private|findable|discoverable|hidden|unlisted)\\b", t, flags=re.I)')]),
    ('P3', SR, 'under',
     '⛔ THE `-ly` FORMS LEAVE THE CAPTURE POLARITY LIST. `\\bpublic\\b` does not match “publicly”, so `list my Studio PC publicly` and `offer my Studio PC publicly` reached the confirm with NO NAME — a word the polarity list has held all along, in a spelling it never had',
     [('_VIS_POLARITY_ALL = _alt(_NAME_END_POLARITY + ("invisible", "undiscoverable",\n                                               "publicly", "privately"))',
       '_VIS_POLARITY_ALL = _alt(_NAME_END_POLARITY + ("invisible", "undiscoverable"))')]),
    ('N1', SR, 'under',
     '⛔ A NEGATOR BEFORE THE POLARITY WORD GOES BACK INTO THE NAME: `make my mac not private` quoted the machine as “mac not” and `make my Studio PC no longer public` quoted “Studio PC no longer”',
     [('rf"(?:{_NEG_WORDS}\\s+)?(?:be\\s+|being\\s+|stay\\s+|"',
       'rf"(?:be\\s+|being\\s+|stay\\s+|"')]),
    ('Q1', SR, 'under',
     '⛔⛔⛔ THE ONE DEFECT IN THIS WAVE THAT ACTED ON THE WRONG MACHINE. The quoted span goes back to a CHARACTER CLASS, so every quote character is a terminator and an apostrophe INSIDE a name ends the capture: `hide \\"Sam\'s MacBook Pro\\"` captures “Sam”, which SUBSTRING-MATCHES a different machine and hides it, with a ✓. Measured on an account holding only “Donna Mac”. The curly ’ behaves identically and is what macOS and iOS autocorrect actually type',
     [('        _vm = (re.search(rf"\\b{_VIS_SETTERS}\\s+{_QUOTED_SPAN}", t, flags=re.I)',
       '        _vm = (re.search(rf"\\b{_VIS_SETTERS}\\s+"\n                         rf"[{re.escape(_NL_QUOTE_CHARS)}]([^{re.escape(_NL_QUOTE_CHARS)}]+)", t, flags=re.I)')]),
    ('Q2', SR, 'under',
     "⛔ THE CURLY-QUOTE ALTERNATIVE LEAVES THE PAIRED SPAN, so `hide “Studio PC”` — what the client's own picker PRINTS, and what a phone substitutes — stops being a quoted name, and the apostrophe defect's other half comes back for every name typed on a phone",
     [('_QUOTED_SPAN = r"(?:\\"([^\\"]+)\\"|“([^”]+)”|‘([^’]+)’)"',
       '_QUOTED_SPAN = r"(?:\\"([^\\"]+)\\")"')]),
    ('Q3', SR, 'under',
     "⛔ THE CAPTURE READER GOES BACK TO `group(1)`, so the paired span's second and third alternatives return None and every curly-quoted or single-quoted name comes out empty — a silent fall to the picker",
     [('    return next((g for g in (m.groups() if m else ()) if g), "")',
       '    return (m.group(1) or "") if m else ""')]),
    ('L1', SR, 'under',
     '⛔ THE VISIBILITY BRANCH LOSES THE LEADING-NOUN STRIP — the 7.9-3 defect, still live on hide and publish when this wave started. `hide the machine LABPC001` looked up “machine LABPC001” and found nothing',
     [('            _vis_obj = _strip_leading_noun(_vis_obj)',
       '            _vis_obj = _vis_obj')]),
    ('L2', SR, 'under',
     '⛔ THE CONSENT SURFACE LOSES ITS CATEGORY-WORD STRIP: `approve the person Sam` asked “Say yes to “person Sam”?” and `approve my colleague Sam` kept the possessive too',
     [('            _who = re.sub(r"^(?:person|user|account|colleague|coworker|co-worker|"\n                          r"guy|woman|man|requester|requestor)\\s+(?=\\S)", "",\n                          _who, flags=re.I).strip()',
       '            _who = _who.strip()')]),
    ('L3', SR, 'over',
     '⛔⛔ MY OWN NEW STRIP EATING A REAL NAME, and my own test caught it within the hour. `my Nodes Mac` has a device noun for its FIRST word and another for its LAST, so stripping the first leaves “Mac” — a bare noun every caller blanks. Twenty frames of that one machine lost their name the moment the visibility branch got this strip',
     [('        if _is_bare_machine_noun(rest) or _is_bare_machine_noun(\n                re.sub(rf"[\\s,;]+{_NAME_TAIL_COMMA_ONLY}$", "", rest, flags=re.I)):\n            return whole',
       '        if False:\n            return whole')]),
    ('L4', SR, 'over',
     '⛔ THE `&` ANCHOR REVERTS AND 1.1\'S CONJUNCTION GUARD FAILS ON A SYMBOL. `\\b` after a `&` needs a word character on one side and `\\"& Bolts\\"` has a space, so `hide \\"Nodes & Bolts\\"` had its first word eaten as a category noun and came out “& Bolts”',
     [('        return whole if re.match(r"^(?:(?:and|or|plus|as\\s+well\\s+as)\\b|[&+])",\n                                 rest, re.I) else rest',
       '        return whole if re.match(r"^(?:and|or|&|plus|as\\s+well\\s+as)\\b", rest, re.I) else rest')]),
    ('D1', SR, 'under',
     '⛔ THE SWITCH DETERMINER LIST NARROWS BACK TO `the|my`, so `switch to that mac`, `to their laptop` and `to this computer` all EXECUTE — no confirm — on a string no lookup can resolve',
     [('    m = re.search(rf"\\b(?:switch to|run (?:it |everything )?on|use)\\s+"\n                  rf"(?:{_NAME_DETERMINER}\\s+)?(.+)$", t, flags=re.I)',
       '    m = re.search(r"\\b(?:switch to|run (?:it |everything )?on|use)\\s+"\n                  r"(?:the\\s+|my\\s+)?(.+)$", t, flags=re.I)')]),
    ('D2', SR, 'under',
     "⛔ THE SWITCH BRANCH STOPS STRIPPING QUOTES, so `use “Studio PC”` — the picker's own printed phrasing — carries the quote marks into a lookup that matches on name, hostname and substring",
     [('        name = name.strip().strip(_NL_QUOTE_CHARS).strip()\n        # ⛔⛤ AND THE TRAILING CLAUSE COMES OFF HERE TOO.',
       '        # ⛔⛤ AND THE TRAILING CLAUSE COMES OFF HERE TOO.')]),
    ('R1', SR, 'under',
     '⛔⛤ THE HIDE-VERB CAPTURE ARM STOPS DERIVING and goes back to four hand-typed verbs — so `disable`, `unshare` and `deregister` reach the hide signal with NO capture arm and hand the command a machine it was never told',
     [('               or re.search(rf"\\b{_VIS_HIDE_ALL}\\s+(.+?)$", t, flags=re.I)',
       '               or re.search(r"\\b(?:hide|unlist|unpublish|delist)\\s+(.+?)$", t, flags=re.I)')]),
    ('R2', SR, 'under',
     '⛔ THE PUBLISH-VERB CAPTURE ARM GOES, so every phrasing the widened signal newly admits — `publish my Studio PC`, `offer my Studio PC`, `advertise my Studio PC` — reaches the confirm naming “that computer” instead of the machine',
     [('               or re.search(rf"\\b{_VIS_PUBLISH_ALL}\\s+(.+?)$", t, flags=re.I)',
       '               or re.search(r"\\b(?:zzznever)\\s+(.+?)$", t, flags=re.I)')]),
    ('R3', SR, 'under',
     '⛔ THE `stop <gerund>` CAPTURE ARM GOES: `stop sharing my Studio PC` and `turn off sharing for my Studio PC` hide whichever machine the picker lands on',
     [('               or re.search(r"\\b(?:stop|shut|quit|cease|end)\\s+"\n                            r"(?:off\\s+|down\\s+)?(?:offering|sharing|listing|"\n                            r"publishing|letting|showing|allowing)\\s+(.+?)$",\n                            t, flags=re.I)',
       '               or re.search(r"\\b(?:zzznever)\\s+(.+?)$", t, flags=re.I)')]),
    ('R4', SR, 'under',
     '⛔ THE `off the list` ARM MOVES BACK BELOW THE POLARITY ARM, so `take my Studio PC off the public list` matches `take … public` first and captures “Studio PC off” — the word that makes the phrase a HIDE goes into the name',
     [('        _vm = (re.search(rf"\\b{_VIS_SETTERS}\\s+{_QUOTED_SPAN}", t, flags=re.I)\n               or re.search(rf"\\b{_alt(_VIS_OFF_VERBS)}\\s+(.+?)\\s+"\n                            rf"(?:off|out of|from)\\b", t, flags=re.I)',
       '        _vm = (re.search(rf"\\b{_VIS_SETTERS}\\s+{_QUOTED_SPAN}", t, flags=re.I)')]),
    ('R5', SR, 'under',
     '⛔ THE SHAPE-BASED FALLBACK ARM GOES, so a phrasing that reaches this branch on a polarity word with a verb no inventory holds loses its name: `list my Studio PC publicly` is the measured one, and `list` is deliberately not a setter because it is the device-LIST request word',
     [('               or re.search(rf"^\\W*\\w+(?:\\s+\\w+)?\\s+"\n                            rf"((?:(?!\\b(?:is|are|was|were|isn\'?t|aren\'?t|has|"\n                            rf"have|does|do|did)\\b)[^.?!])+?)\\s+"',
       '               or re.search(rf"^zzznever\\W*\\w+(?:\\s+\\w+)?\\s+"\n                            rf"((?:(?!\\b(?:is|are|was|were|isn\'?t|aren\'?t|has|"\n                            rf"have|does|do|did)\\b)[^.?!])+?)\\s+"')]),
    ('R6', SR, 'over',
     "⛔⛤ THE FALLBACK'S COPULA GUARD GOES, and my own first version did exactly this: `my mac is not public` is a STATEMENT and the arm captured “is not” as a machine name, then offered to PUBLISH it",
     [('                            rf"((?:(?!\\b(?:is|are|was|were|isn\'?t|aren\'?t|has|"\n                            rf"have|does|do|did)\\b)[^.?!])+?)\\s+"',
       '                            rf"([^.?!]+?)\\s+"')]),
    ('R7', SR, 'under',
     '⛔⛤ THE FEATURE-WORD PEEL GOES, and my own A/B caught the need for it: giving every hide verb a bare arm made `disable sharing on my mac` capture “sharing on my mac” as a MACHINE NAME — a phrase that resolves to nothing, so a command that reached the picker started refusing',
     [('                _peeled = re.sub(r"^(?:(?:sharing|listing|publishing|offering|"\n                                 r"discovery|visibility|discoverability)\\s+)?"\n                                 r"(?:on|for|of|to|from|off|down)\\s+", "",\n                                 _peeled, flags=re.I).strip()',
       '                _peeled = _peeled.strip()')]),
    ('R8', SR, 'over',
     '⛔⛤ THE PEEL STOPS REQUIRING A PREPOSITION, and that is the version my own probe rejected: written as a bare word list it turned `hide Sharing Mac` into “Mac”. A setting word only means a setting when a machine follows it THROUGH `on`, `for` or `of`',
     [('                                 r"(?:on|for|of|to|from|off|down)\\s+", "",\n                                 _peeled, flags=re.I).strip()',
       '                                 r"(?:on|for|of|to|from|off|down)?\\s*", "",\n                                 _peeled, flags=re.I).strip()')]),
    ('R9', SR, 'under',
     '⛔ THE AUDIENCE PEEL GOES: `stop letting people find my pc` captured “people find my pc”. The people are WHO, the pc is WHICH — an existing test caught this one',
     [('                _peeled = re.sub(r"^(?:people|persons?|users?|anyone|anybody|"\n                                 r"everyone|everybody|others|strangers|folks|"\n                                 r"other\\s+(?:people|persons?|users?))\\s+"\n                                 r"(?:to\\s+)?(?:find|use|see|discover|access|"\n                                 r"borrow|reach)\\s+", "", _vis_obj,\n                                 flags=re.I).strip()',
       '                _peeled = _vis_obj.strip()')]),
    ('A1', SR, 'under',
     '⛔ THE AUDIENCE TAIL TRIM GOES: `share my Studio PC with other people` captured the whole tail, which then matched the about-other-people test and BLANKED the capture — so naming the audience cost you the machine and the publish fell to the picker',
     [('    out = re.sub(r"\\s+(?:with|to|for)\\s+(?:other\\s+(?:people|persons?|users?)|"\n                 r"everyone|everybody|anyone|anybody|strangers|the\\s+world|"\n                 r"the\\s+public|all)\\b.*$", "", out, flags=re.I).strip()',
       '    out = out.strip()')]),
    ('A2', SR, 'under',
     '⛔ THE AUDIENCE EXEMPTION STOPS COVERING THE PUBLISH VERBS, so `make my mac public to everyone` is exempt while `offer my Studio PC to everyone` is REFUSED as a bulk publish — the same sentence, the same audience, two answers',
     [('    if re.search(rf"\\b{_VIS_PUBLISH_ALL}\\b", bare, re.I):\n        bare = re.sub(rf"\\bto\\s+{_SET_AUDIENCE_WHO}\\b", " ", bare, flags=re.I)',
       '    if False:\n        bare = re.sub(rf"\\bto\\s+{_SET_AUDIENCE_WHO}\\b", " ", bare, flags=re.I)')]),
    ('A3', SR, 'over',
     '⛔⛔ THE AUDIENCE BLANKER EATS THE WHOLE SPAN FROM THE VERB — the 40-character window 1.1 had to REMOVE. `offer all my macs to everyone` is a genuine set and comes out exempt, so a bulk publish executes on one machine',
     [('        bare = re.sub(rf"\\bto\\s+{_SET_AUDIENCE_WHO}\\b", " ", bare, flags=re.I)',
       '        bare = re.sub(rf"[^.?!]{{0,40}}\\bto\\s+{_SET_AUDIENCE_WHO}\\b", " ", bare, flags=re.I)')]),
    ('A4', SR, 'under',
     '⛔ TWO QUOTED NAMES JOINED BY A CONJUNCTION STOP BEING A SET — the quoted path takes the first span and `hide “Studio PC” and “Lab PC”` hides ONE machine and silently drops the other, with no refusal. A set-gate hole 1.1 did not cover',
     [('_SET_CONJ_BARE = (r"(?:,\\s*|;\\s*|and\\s+|or\\s+|&\\s*|as\\s+well\\s+as\\s+|plus\\s+|"',
       '_SET_CONJ_BARE = (r"(?:,\\s*|;\\s*|or\\s+|&\\s*|as\\s+well\\s+as\\s+|plus\\s+|"')]),
    ('V1', SR, 'under',
     '⛔⛔ THE SETTER LIST STOPS BEING BUILT FROM THE ROLES and goes back to the sixteen hand-typed words — so `delist`, `unshare`, `deregister`, `advertise` and `expose` leave every reader of it at once: the act-verb list, the named-target test, the polite imperative and the capture arms',
     [('_VIS_SETTERS = _alt(_VIS_POLAR_VERBS + _VIS_HIDE_VERBS + _VIS_PUBLISH_VERBS\n                    + _VIS_OFF_VERBS)',
       '_VIS_SETTERS = r"(?:make|set|switch|turn|put|hide|unlist|unpublish|offer|share|publish|disable|take|remove|drop|pull)"')]),
    ('V2', SR, 'under',
     "⛔⛔ THE FINITE PUBLISH VERBS LEAVE THE SIGNAL and the DEVICE-LIST THEFT comes back — 312 measured shapes. `publish my mac`, `offer my Studio PC` and `share my Studio PC` all answer with a list of the person's own computers instead of publishing the one they named",
     [('    _offering_kw = (re.search(rf"\\b{_VIS_PUBLISH_ALL}\\b", low)\n',
       '    _offering_kw = (re.search(r"\\b(sharing|offering|discoverable|findable)\\b", low)\n')]),
    ('V3', SR, 'under',
     '⛔⛔ THE INFLECTIONS GO. Measured: NO `-s` form anywhere in this file fired, and the two sides were exact inverses — the hide side had only the BARE form (`hiding my mac` was dead) and the publish side only the `-ing` form (`offer my mac` was dead while `offering my mac` worked). Nobody chose that; it is what two hand-written lists drift into',
     [('        out.append(v + "es" if re.search(r"(?:sh|ch|s|x|z)$", v) else v + "s")\n        out.append(v[:-1] + "ing" if v.endswith("e") else v + "ing")',
       '        pass')]),
    ('V4', SR, 'under',
     '⛔ THE `-es` RULE BREAKS, so `publish` inflects to `publishs` and `unpublishes`/`disables` stop being spelled the way English spells them — the words a person actually types stop matching',
     [('out.append(v + "es" if re.search(r"(?:sh|ch|s|x|z)$", v) else v + "s")',
       'out.append(v + "s")')]),
    ('V5', SR, 'under',
     '⛔⛔⛔ THE `un-` GUARD LEAVES THE HIDE ARM AND `un-delist my Studio PC` HIDES THE MACHINE. The person asks to un-hide and gets a hide — while `un-unlist` correctly publishes. Two answers to the same question, which is what made it a bug and not a design',
     [('        re.search(rf"(?<!un-)(?<!un )\\b(?:{_HIDE_POLARITY[3:-1]}|hidden|unlisted|"',
       '        re.search(rf"\\b(?:{_HIDE_POLARITY[3:-1]}|hidden|unlisted|"')]),
    ('V6', SR, 'under',
     '⛔ THE HIDE VERBS LEAVE THE MERGED ARM, so `disable`, `unshare`, `delist` and `deregister` stop signalling a hide at all and `disable my Studio PC` answers with a device list',
     [('rf"{_VIS_HIDE_ALL[3:-1]})\\b", _pol_low)',
       'rf"hide)\\b", _pol_low)')]),
    ('V7', SR, 'under',
     '⛔ THE HIDE POLARITY LIST STOPS DERIVING, so the negation test that INVERTS a polarity word and the signal that reads it drift apart again — the exact shape that had two polarity lists in this file with neither derived from the other',
     [('_HIDE_POLARITY = _alt(_HIDE_POLARITY_WORDS)',
       '_HIDE_POLARITY = _alt(("private", "hidden", "unlisted"))')]),
    ('V8', SR, 'over',
     "⛔⛔ THE TWO POLARITY SIDES MERGE AND 1.1'S ASYMMETRY DIES — I did exactly this and two of 1.1's own tests caught it within minutes. Negating a PUBLISH is a concrete hide, so `make my mac not private` is a publish; negating a HIDE names no state at all",
     [('rf"\\b{_NEG_WORDS}\\b[^.?!]{{0,40}}\\b(?:{_alt(_PUBLISH_POLARITY_WORDS)[3:-1]}|"',
       'rf"\\b{_NEG_WORDS}\\b[^.?!]{{0,40}}\\b(?:{_POLARITY_WORDS[3:-1]}|"')]),
    ('V9', SR, 'under',
     '⛔ THE PUBLISH VERBS LEAVE THE NEGATED-PUBLISH TEST, and a live regression comes back: `no longer publishing my mac` becomes a NEGATED COMMAND and reaches the catch-all. It means “stop publishing it” — a hide',
     [('    rf"{_VIS_PUBLISH_ALL[3:-1]}|"\n    rf"let\\s+(?:people|persons|users|anyone|anybody|everyone|everybody|others|"',
       '    rf"let\\s+(?:people|persons|users|anyone|anybody|everyone|everybody|others|"')]),
    ('V10', SR, 'under',
     '⛔ THE PUBLISH-SIDE POLARITY WORDS LEAVE THE SIGNAL. Four of them sat in the polarity constant and in NO signal at all, so `make my mac visible`, `make my mac listed` and `make my mac shared` answered with a device LIST while `make my mac not visible` hid it',
     [('                    or (re.search(rf"\\b{_alt(_PUBLISH_POLARITY_WORDS)}\\b", low)',
       '                    or (False')]),
    ('V11', SR, 'under',
     '⛔ THE ADMISSION TESTS GO BACK TO THE STRIP LIST, which has no `phone`. `hide my phone` reaches the catch-all while `hide my phones` gets the set refusal and `remove my phone` works — five sites hand-spliced the word back on and the admission tests were the ones that did not',
     [('    _machine_kw = re.search(rf"\\b({_MACHINE_NOUNS_SAID})\\b", low)',
       '    _machine_kw = re.search(rf"\\b({_MACHINE_NOUNS})\\b", low)')]),
    ('V12', SR, 'under',
     '⛔ THE POLITE IMPERATIVE STOPS DERIVING — the fourth hand copy of the setter list, twelve of twenty-one words — so `can you delist my Studio PC` and `could you take my mac off the list` are read as QUESTIONS and answered with a device list',
     [('rf"(?:please\\s+)?{_VIS_SETTERS}\\b",',
       'r"(?:please\\s+)?(?:make|set|switch|turn|put|hide|unlist|unpublish|offer|share|publish|disable)\\b",')]),
    ('V13', SR, 'under',
     '⛔ THE QUOTED ARM OF THE NAMED-TARGET TEST STOPS DERIVING, so a quoted name after `take`, `remove`, `drop`, `pull`, `delist`, `unshare`, `deregister`, `advertise` or `expose` is not a named target at all',
     [('                     or re.search(rf"\\b{_VIS_SETTERS}\\s+"\n                                  rf"[{re.escape(_NL_QUOTE_CHARS)}]", t))',
       '                     or re.search(r"\\b(?:make|set|switch|turn|put|hide|unlist|"\n                                  r"unpublish|offer|share|publish|disable)\\s+"\n                                  rf"[{re.escape(_NL_QUOTE_CHARS)}]", t))')]),
    ('V14', SR, 'under',
     '⛔ `cancel` LEAVES THE CONTROL-WORD LIST, and the two lists differ by exactly that word again: `cancel on my Studio PC` reaches the device list while the identical `stop on my Studio PC` reaches the catch-all',
     [('                            r"cancel|drop)\\b", low)',
       '                            r"skip)\\b", low)')]),
    ('V15', SR, 'under',
     "⛔⛤ RE-AIMED AFTER IT SURVIVED, AND THE RETIREMENT IS THE FINDING. As written it pinned a machine-noun exclusion I had added so `drop` would stop vetoing the visibility branch — and the harness proved that exclusion measures NOTHING: `drop` is in the device verbs and the unlink verbs now, so every `drop <machine>` phrasing reaches the unlink confirm by that road whether the veto fires or not. The guard was DELETED as dead code. What this pins instead is `drop`'s membership of the control words at all — without it `drop the video` stops being a skip",
     [('    _control_kw = re.search(r"\\b(stop|end|abort|pause|resume|unpause|retry|skip|"\n                            r"cancel|drop)\\b", low)',
       '    _control_kw = re.search(r"\\b(stop|end|abort|pause|resume|unpause|retry|skip|"\n                            r"cancel)\\b", low)')]),
    ('V16', SR, 'under',
     '⛔ `drop` LEAVES THE UNLINK VERBS, so `drop my Studio PC` — a synonym of `remove` on this surface — stops reaching the unlink confirm',
     [('_UNLINK_VERBS = r"(?:remove|unlink|forget|delete|drop)"',
       '_UNLINK_VERBS = r"(?:remove|unlink|forget|delete)"')]),
    ('V17', SR, 'under',
     '⛔ `link` LEAVES THE PAIRING WORDS. It sat in the act-verb list and in NO other, so `link my computer` reached the catch-all — which also meant its own negation veto could never fire, because there was nothing to veto',
     [('            (re.search(rf"\\b(add|pair|connect)\\b.*\\b({_MACHINE_NOUNS_SAID})\\b", low)',
       '            (re.search(rf"\\b(add|pair)\\b.*\\b({_MACHINE_NOUNS_SAID})\\b", low)')]),
    ('V18', SR, 'under',
     '⛔⛔ THE BARE MACHINE TOKEN STOPS NAMING A MACHINE, and the largest single class of dead phrasings in the wave comes back: 432 of 1,225 — more than a third — were `hide LABPC001`, `make LABPC001 public` and `remove LABPC001`, while `switch to LABPC001` worked, so nothing told the person which verbs would take it',
     [('                 or _id_target or _pronoun_target',
       '                 or _pronoun_target')]),
    ('V19', SR, 'over',
     '⛔ THE MACHINE-TOKEN TEST DROPS ITS DIGIT-OR-SEPARATOR REQUIREMENT, so any five-letter word after a setter names a machine — `hide mars` and `hide topic` become device commands, which is the shape that once turned `ask for feedback` into a consent question about a stranger',
     [('    return bool(re.search(r"\\d", w) or re.search(r"[-_]", w)) and \\\n        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", w))',
       '    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", w))')]),
    ('V20', SR, 'under',
     '⛔ THE `un-` PUBLISH ARM STOPS DERIVING and goes short by four of the seven hide verbs, so `un-disable`, `un-unpublish` and `un-unshare` answer with a DEVICE LIST while `un-hide` publishes',
     [('rf"\\bun[- ]?{_VIS_HIDE_ALL}\\b|\\bun-?conceal\\b",',
       'r"\\bun-?(?:hide|unlist|delist|conceal)\\b",')]),
    ('S1', SR, 'under',
     "⛔ THE OWN-MACHINE WORD GAP NARROWS BACK TO TWO, so a three-word machine name defeats it and `advertise my Now or Never Mac publicly` is routed as SOMEBODY ELSE'S machine — answered with the browse list of strangers' computers",
     [('    _mine_kw = re.search(rf"\\b(my|mine|our|this)\\b"\n                         rf"(?:\\s+(?!(?:{_POLARITY_WORDS[3:-1]})\\b)[\\w\'-]+){{0,4}}\\s+"\n                         rf"(?:{_MACHINE_NOUNS_SAID})\\b", low)',
       '    _mine_kw = re.search(rf"\\b(my|mine|our|this)\\b"\n                         rf"(?:\\s+(?!(?:{_POLARITY_WORDS[3:-1]})\\b)[\\w\'-]+){{0,2}}\\s+"\n                         rf"(?:{_MACHINE_NOUNS_SAID})\\b", low)')]),
    ('S2', SR, 'under',
     '⛔⛔ THE INVENTORY VETO GOES AND `research my devices` STARTS A PAID RUN titled “my devices”. The research branch took 100% of research-verb openings — 392 of 392 driven — because its veto was a fullmatch on three bare words, so anything longer was a topic by default',
     [('            or re.fullmatch(r"(?:my|our|this|these)\\s+(?:own\\s+)?"\n                            rf"(?:{_MACHINE_NOUNS_SAID})", topic, re.I)',
       '            or False')]),
    ('S3', SR, 'under',
     '⛔ THE RUN-ARTEFACT VETO GOES: `research the status of my run` and `research the podcast from my mac` both start PAID RUNS on a title that names something the account already has',
     [('            or re.fullmatch(rf"(?:{_NAME_DETERMINER}\\s+)?"\n                            rf"(?:status|progress|podcast|audio|video|brief|report|"\n                            rf"links?|results?|logs?)\\s+(?:of|from|for|on)\\s+"\n                            # ⛔ `the` GOES: the comment beside this says the\n                            # test is WHOSE, and `the laptop market` is nobody\'s.\n                            rf"(?:my|this|that)\\s+"\n                            rf"(?:run|research|{_MACHINE_NOUNS_SAID})\\b.{{0,20}}",\n                            topic, re.I)',
       '            or False')]),
    ('S4', SR, 'over',
     '⛔⛤ THE ARTEFACT VETO WIDENS BACK TO ANY NOUN, and an existing test caught me writing it this way: `research the status of the EV market` — a perfectly good subject — is refused. What makes a phrase not-a-topic is WHOSE thing it names, not which noun',
     [('                            rf"links?|results?|logs?)\\s+(?:of|from|for|on)\\s+"\n                            # ⛔ `the` GOES: the comment beside this says the\n                            # test is WHOSE, and `the laptop market` is nobody\'s.',
       '                            rf"links?|results?|logs?)\\b.{{0,40}}",')]),
    ('S5', SR, 'under',
     '⛔ THE `<word> run` VETO GOES, so `look into the Mars run` starts a paid research run on the title of a run the person is asking ABOUT',
     [('            or re.fullmatch(r"(?:my|our|this|these)\\s+(?:own\\s+)?"\n                            rf"(?:{_MACHINE_NOUNS_SAID})", topic, re.I)',
       '            or re.fullmatch(rf"(?:{_NAME_DETERMINER}\\s+)?(?:own\\s+)?"\n                            rf"(?:{_MACHINE_NOUNS_SAID})", topic, re.I)')]),
    ('S6', SR, 'under',
     '⛔⛔ THE RUN AND CONSENT VERBS LEAVE THE EXISTING-MACHINE LIST, and a code-shaped token in a sentence about a machine PAIRS it: `stop the machine LABPC001 run` and `approve the machine LABPC001` both emit `device-add`',
     [('rf"|stop|end|abort|cancel|pause|resume|unpause|retry|skip"\n                              rf"|approve|accept|allow|grant|deny|refuse|reject|block"\n',
       '')]),
    ('S7', SR, 'under',
     '⛔⛔ THE SEND-LOGS WORDS LEAVE THE EXISTING-MACHINE LIST, and `did my logs go through? code AB12CD34` PAIRS THE SUPPORT CODE as a Research Computer. A support code is taught in two places in the document and is not a pair code at all',
     [('rf"|logs?|log\\s+files?|diagnostics|support"\n',
       '')]),
    ('S8', SR, 'under',
     '⛔⛔ THE COMPOUND-ASK RETURN GOES, and a message naming two acts loses half of itself silently: `pause the run and switch to the office PC` pauses a run called “run and switch to the office PC” and drops the switch; `stop the tesla run and hide my mac` offers to stop a run called “tesla run and hide my mac”',
     [('    if _is_compound_ask(t):\n        return None, [_NL_CATCH_ALL]',
       '    if False:\n        return None, [_NL_CATCH_ALL]')]),
    ('S9', SR, 'over',
     '⛔⛤ THE COMPOUND RULE WIDENS TO ANY MUTATION, AND MY OWN A/B CAUGHT THAT VERSION: it refused FOUR real phrasings — `skip the video and drop claude` (one ask, two phases), `hide my mac and make it private` (one ask said twice), and `find a public one and ask its owner for access`, which the document itself teaches',
     [('_COMPOUND_ASK = re.compile(\n    r"\\b(?:stop|end|abort|cancel|pause|resume|unpause|retry)\\b[^.?!]*?"\n    r"\\s+(?:and|then|also|plus|,\\s*and|;)\\s+(?:please\\s+|also\\s+)?"',
       '_COMPOUND_ASK = re.compile(\n    r"[^.?!]"\n    r"\\s+(?:and|then|also|plus|,\\s*and|;)\\s+(?:please\\s+|also\\s+)?"')]),
    ('S10', SR, 'under',
     '⛔⛔ THE COMPOUND CHECK BECOMES A BAIL INSTEAD OF A RETURN — the whole lesson of wave 1.1. A veto in an ordered ladder hands its message to the NEXT branch, which then acts on the wrong feature; four defects in one wave came from exactly this',
     [('    if _is_compound_ask(t):\n        return None, [_NL_CATCH_ALL]',
       '    if _is_compound_ask(t):\n        pass')]),
    ('S11', SR, 'over',
     '⛔ THE COMPOUND CHECK MOVES ABOVE THE RESEARCH BRANCH, and a TOPIC is allowed to contain anything: `research how to stop smoking and start running` is ONE ask and comes back refused',
     [('    rm = _NL_RESEARCH_RE.match(t)\n    if rm:',
       '    if _is_compound_ask(t):\n        return None, [_NL_CATCH_ALL]\n    rm = _NL_RESEARCH_RE.match(t)\n    if rm:')]),
    ('S12', SR, 'under',
     "⛔ THE SHAPE ARM LEAVES THE NAMED-TARGET TEST, so `list the Studio PC publicly` answers with the BROWSE list of strangers' machines — `list` is deliberately not a setter, because it is the device-LIST request word, so no vocabulary arm sees the machine the person named",
     [('                     or (re.search(rf"\\b{_POLARITY_WORDS}\\b", low)\n                         and re.search(',
       '                     or (False\n                         and re.search(')]),
    ('S13', SR, 'over',
     '⛔⛤ THE SHAPE ARM DROPS ITS NAME-AND-SINGULAR REQUIREMENT, and two existing tests caught that version: it claimed `list the public computers` and `find me a public computer` — BROWSE requests — from the branch that serves them. The adjective `public` is not a name, and a set of machines is not one machine',
     [('                             rf"(?:(?!(?:{_POLARITY_WORDS[3:-1]}|other|own|"\n                             rf"more|any|some)\\b)[\\w\'-]+\\s+){{1,3}}"\n                             rf"{_MACHINE_SINGULAR}\\b", low))',
       '                             rf"[\\w\' -]*(?:{_MACHINE_NOUNS_SAID})\\b", low))')]),
    ('S14', SR, 'under',
     '⛔ THE RESEARCH BLANKER LOSES ITS DETERMINER SLOT, so `research my computers` still carries the artefact word `research` and fails the device-list gate — it reaches the catch-all while `research my devices` answers. Two spellings of the same ask, two answers',
     [('rf"\\bresearch(?:es)?\\s+(?:{_NAME_DETERMINER}\\s+)?"\n                        rf"(?:own\\s+)?(?:{_MACHINE_NOUNS_SAID})\\b", "  ", low)',
       'rf"\\bresearch(?:es)?\\s+(?:{_MACHINE_NOUNS_SAID})\\b", "  ", low)')]),
    ('K1', SR, 'under',
     "⛔⛔ THE CHAT PHASE WORDS STOP DERIVING FROM THE COMMAND'S OWN MAP, and the shortfall is invisible: `sr skip audio` and `sr skip youtube` work at the CLI while `skip the audio` reaches the router's BARE form, which resolves the run's current BLOCKER — a mutating act nobody asked for",
     [('_NL_PHASE_WORDS = tuple(sorted(dict.fromkeys(_SKIP_NAMES), key=len, reverse=True))',
       '_NL_PHASE_WORDS = ("brief", "podcast", "video", "report", "email")')]),
    ('K2', SR, 'under',
     '⛔ THE CHAT AGENT WORDS STOP DERIVING, so `openai` and `anthropic` — both mapped by the command — are dead in chat and land on the bare form instead, resolving a blocker',
     [('_NL_AGENT_WORDS = tuple(sorted(dict.fromkeys(_SKIP_AGENTS), key=len, reverse=True))',
       '_NL_AGENT_WORDS = ("chatgpt", "claude", "gemini", "gpt")')]),
    ('K3', SR, 'under',
     '⛔⛔ THE RUN NAME GOES AND THE MEASURED HEADLINE COMES BACK: a person cannot skip a phase of any run but the newest active one, from chat, AT ALL. Nineteen phrasings drop the name and reconfigure whichever run is newest; the capability exists only at the raw CLI',
     [('    _run_flag = [f"--run={_skip_run}"] if _skip_run else []',
       '    _run_flag = []')]),
    ('K4', SR, 'over',
     '⛔ THE RUN NAME GOES BACK TO THE SHARED HELPER\'S FALLBACK, which is "everything after the verb" — and here that is the PHASE LIST. `skip the video and the report` comes out naming a run called “video and the report”',
     [('    _skip_rm = (_NL_QUOTED_RE.search(t)\n                or re.search(r"\\brun\\s+(?:called|named|titled)\\s+"\n                             r"([\\w\'\\u2019 -]+?)\\s*$", t, re.I)\n                or re.search(r"\\b(?:on|for|in|of)\\s+(?:the\\s+|my\\s+)?"\n                             r"((?!(?:the|a|an|my|our|this|that|current|latest|"\n                             r"last|newest|run|research)\\b)[\\w\'\\u2019 -]+?)"\n                             r"\\s+(?:run|research)\\b", t, re.I)\n                # ⛔ AND WITHOUT A PREPOSITION: `skip the Mars run` names a run\n                #    and no phase, which is what the bare form is for.\n                # ⛔⛤ THE TITLE CARRIES NO PREPOSITION OF ITS OWN. A space-tolerant\n                #    capture reached ACROSS one — `skip the podcast on the run`\n                #    came out naming a run “podcast on the” — so each word after\n                #    the first is guarded, not only the first.\n                or re.search(r"\\b(?:the|my)\\s+"\n                             r"((?!(?:the|a|an|my|our|this|that|current|latest|"\n                             r"last|newest|run|research)\\b)[\\w\'\\u2019-]+"\n                             r"(?:\\s+(?!(?:on|for|in|of|the|a|an|my|our|this|that)\\b)"\n                             r"[\\w\'\\u2019-]+)*?)"\n                             r"\\s+(?:run|research)\\b", t, re.I))',
       '    _skip_rm = _NL_QUOTED_RE.search(t)')]),
    ('K5', SR, 'over',
     "⛔⛤ RE-AIMED AFTER IT SURVIVED, AND CHASING IT FOUND TWO DEFECTS OF MINE. As written it pinned a phase-word rejection that was WRONG — all three capture shapes are explicit run-naming, so a run genuinely called “brief” lost the only means the product offers of naming it and the skip landed on the newest run. The real defect underneath: the phase scan read the WHOLE message, so `skip the report for the brief run` came out `['skip','brief','report']` and skipped the BRIEF as well — the run is CALLED brief. This pins the blanking of the run-name span before the scan",
     [('        _scan = low\n        if _skip_rm:\n            _scan = low[:_skip_rm.start()] + " " + low[_skip_rm.end():]',
       '        _scan = low')]),
    ('K6', SR, 'under',
     '⛔⛔ THE EXCLUSION INVERTS ITSELF AGAIN: `skip all but the podcast` SKIPS THE PODCAST — the one thing the person said to keep — because the phase words are collected by presence and an exclusion names the KEEPER',
     [('            if _totaliser and (_keep_phases or _keep_agents):',
       '            if False:')]),
    ('K7', SR, 'under',
     "⛔⛔ PHASE NUMBERS GO BACK TO UNROUTABLE, AND THEY LAND ON A MUTATION: `skip phase 3`, `skip 4 and 5` and `skip step 2` all reach the bare form, which resolves the run's current BLOCKER. The CLI has accepted numbers all along",
     [('        for _n in _nums:\n            if _n not in phases:\n                phases.append(_n)',
       '        for _n in []:\n            if _n not in phases:\n                phases.append(_n)')]),
    ('K8', SR, 'under',
     "⛔ AN UNSKIPPABLE PHASE NUMBER STOPS BEING REFUSED BY NAME, so `skip step 2` finds no phase, falls to the bare arm and RESOLVES THE RUN'S BLOCKER — a mutation the person never asked for",
     [('        if _bad:\n',
       '        if False:\n')]),
    ('K9', SR, 'under',
     '⛔⛔ THE PHASE ARM LOSES THE SET GATE — it was the ONLY mutating act branch without one. `skip the podcast on all my runs` applies the change to ONE run and says nothing about the rest, while pause, resume, retry and stop all refuse the same phrasing',
     [('            if _request_names_a_set(t, _skip_run):\n                return None, [_NL_SKIP_ONE_RUN]\n            return ["skip"] + _run_flag + phases + agents, None',
       '            return ["skip"] + _run_flag + phases + agents, None')]),
    ('K10', SR, 'under',
     '⛔ THE DEVICE BAIL GOES BACK TO UNCONDITIONAL: `skip the podcast on my computer` bails here, branch 2 catches it and returns the bare form — which resolves the BLOCKER. The person named a PHASE and got a different mutation, silently. The machine in that sentence is WHERE, not WHAT',
     [('    if not _skip_question and (not _device_noun or _phase_is_the_object) \\',
       '    if not _skip_question and (not _device_noun) \\')]),
    ('K11', SR, 'over',
     '⛔⛤ THE PHASE-WORD LOOKAHEAD GOES AND THE EXCEPTION REOPENS THE VERY SWAP THE DEVICE BAIL PREVENTS: `remove my video PC` names a computer called “video PC” and comes out as `skip video`, reconfiguring a live run instead of asking to unlink a machine',
     [('        rf"(?!\\s+(?:{_MACHINE_NOUNS_SAID})\\b)", low)',
       '        rf"", low)')]),
    ('K12', SR, 'under',
     '⛔ AGENT ADJACENCY GOES BACK TO VERB-ONLY, so `skip the video and chatgpt` silently drops ChatGPT while `skip chatgpt and the video` turns it off — the same ask, said the other way round, two answers',
     [('            rf"(?:[^.?!]{{0,28}}?\\b(?:and|or|,|plus|as\\s+well\\s+as)\\s+)?"\n',
       '')]),
    ('K13', SR, 'under',
     '⛔⛔ THE QUESTION GUARD GOES AND `can i skip the podcast` DOWNLOADS THE AUDIO — it falls past both skip branches and reaches the PODCAST branch. Bailing is not enough; this is a RETURN because a veto in an ordered ladder hands the message to the next branch',
     [('    if _skip_question and re.search(r"\\bskip(?:s|ped|ping)?\\b|\\bdrop(?:s|ped|ping)?\\b", low) and \\',
       '    if False and re.search(r"\\bskip(?:s|ped|ping)?\\b|\\bdrop(?:s|ped|ping)?\\b", low) and \\')]),
    ('K14', SR, 'under',
     "⛔ `skip nothing` REACHES THE BARE FORM AND RESOLVES THE RUN'S BLOCKER — the one thing it says not to do",
     [('    if re.search(r"\\bskip\\s+(?:nothing|none|neither)\\b", low):\n        return None, [_NL_CATCH_ALL]',
       '    if False:\n        return None, [_NL_CATCH_ALL]')]),
    ('K15', SR, 'over',
     '⛔ THE PHASE ORDER REVERTS TO THE MATCH ORDER, which is sorted longest-first so "chatgpt" beats its own substring "gpt" — reusing it here reversed `skip the video and the report` into report-then-video, and two existing tests pin the run\'s real phase order',
     [('        phases = [w for w in sorted(_hits, key=lambda w: (_SKIP_NAMES[w], _order[w]))',
       '        phases = [w for w in _hits')]),
    ('K16', SR, 'under',
     '⛔ `--run` LEAVES THE ROUTED FLAG SET, so the relay classifies it as a POSITIONAL and the run name is passed behind `--` as a phase — argparse refuses it and the whole chat turn becomes "I didn\'t catch a Super Research request in that"',
     [('_DO_FLAGS = frozenset({"--no-video", "--no-email", "--machine", "--agent-log",\n                       "--run"})',
       '_DO_FLAGS = frozenset({"--no-video", "--no-email", "--machine", "--agent-log"})')]),
    ('K17', SR, 'under',
     '⛔ THE RELAY GOES BACK TO EXACT-MEMBERSHIP MATCHING, so `--run=Mars Water` is not recognised as a flag at all and the whole token is passed as a phase name',
     [('    _is_flag = lambda a: a.split("=", 1)[0] in _DO_FLAGS',
       '    _is_flag = lambda a: a in _DO_FLAGS')]),
    ('K18', SR, 'under',
     '⛔ THE RANGE CHECK GOES AND ANY INTEGER IS POSTED: `sr skip 0`, `sr skip 2` — the Research stage, which is not skippable — and `sr skip 99` all reach the backend',
     [('            if int(p) not in _SKIP_PHASE_NUMBERS:\n',
       '            if False:\n')]),
    ('K19', SR, 'under',
     '⛔ THE REFUSAL STOPS DERIVING and names four of the seven phase words and three of the six agent words — so `audio`, `youtube`, `openai` and `anthropic` all WORK and the error message says they do not',
     [('    _accepted = (f"{\'/\'.join(str(n) for n in _SKIP_PHASE_NUMBERS)}, "\n                 f"{\'/\'.join(_SKIP_NAMES)}, or a Research agent: "\n                 f"{\'/\'.join(_SKIP_AGENTS)}")',
       '    _accepted = "1/3/4/5, brief/podcast/video/report, or a Research agent: chatgpt/gemini/claude"')]),
    ('E1', SR, 'under',
     '⛔ THE HELP ROUTE GOES. `help` and `what can you do?` reached the CATCH-ALL, whose line opens "I didn\'t catch a Super Research request in that" — and the list that follows is exactly the right answer. The client knew what to say and told the person they had failed to say it',
     [('    if re.fullmatch(r"(?:please\\s+)?(?:help|help me|what can you do|what do you do|"',
       '    if re.fullmatch(r"(?:zzznever)(?:help|help me|what can you do|what do you do|"')]),
    ('E2', SR, 'under',
     '⛔ THE ARTEFACT-LINK ROUTE GOES. SKILL.md teaches `the brief link`, `a report link`, `the NotebookLM link`, `the doc` and `the video` as things to SAY and every one reached the catch-all — the links live in the status output and nothing routed a person to it',
     [('    if re.fullmatch(r"(?:please\\s+|can\\s+you\\s+|could\\s+you\\s+|send\\s+|show\\s+"',
       '    if re.fullmatch(r"(?:zzznever)(?:please\\s+|can\\s+you\\s+|could\\s+you\\s+|send\\s+|show\\s+"')]),
    ('E3', SR, 'under',
     '⛔ THE PAST-RESEARCH ROUTE GOES: `my past research` and `my runs` reach the catch-all while `list` works',
     [('        r"(?:my|the|all|our)\\s+(?:past|previous|old|earlier|recent)\\s+"',
       '        r"(?:zzznever)\\s+"')]),
    ('E4', SR, 'under',
     '⛔ THE `did they answer?` ROUTE GOES. The document teaches it and one other phrasing as the way to check on a request you sent; the surface exists and nothing pointed at it',
     [('    if re.fullmatch(r"(?:please\\s+)?(?:did (?:they|he|she|the owner) (?:answer|reply|"',
       '    if re.fullmatch(r"(?:zzznever)(?:did (?:they|he|she|the owner) (?:answer|reply|"')]),
    ('E5', SR, 'under',
     '⛔ THE PRONOUN TARGET GOES: `take it off the public list` is a phrasing SKILL.md teaches and it reached the catch-all — the hide signal fired and no clause said the message had a target at all',
     [('                 or _id_target or _pronoun_target',
       '                 or _id_target')]),
    ('E6', SR, 'under',
     '⛔ THE UNQUOTED `use <name>` GOES. `use \\"Studio PC\\"` worked and `use Studio PC` reached the catch-all — so following the picker\'s own printed instruction worked only if you typed the quotes it printed',
     [('    _bare_use = t[:4].lower() == "use " and (\n        t[4:5] in _NL_QUOTE_CHARS\n        or bool(re.search(rf"\\b(?:{_MACHINE_NOUNS_SAID})\\b", _use_obj, re.I)\n                or _looks_like_a_machine_token(_use_obj))',
       '    _bare_use = t[:4].lower() == "use " and (\n        t[4:5] in _NL_QUOTE_CHARS\n        or bool(False\n                or _looks_like_a_machine_token(_use_obj))')]),
    ('E7', SR, 'over',
     '⛔ THE BARE-USE STOP LIST GOES, so `use less video` and `use chatgpt` become DEVICE SWITCHES — a branch that mutates with no confirm at all, acting on a string that names no machine',
     [('            rf"(?!(?:{\'|\'.join(_NL_PHASE_WORDS)}|{\'|\'.join(_NL_AGENT_WORDS)}|"\n            rf"less|more|fewer|another|it|this|that|them|one)\\b)"\n',
       '')]),
    ('E8', SR, 'under',
     "⛔ THE MULTI-WORD TRIGGERS STOP BEING SHARED between each branch and its own tail strip, so the trigger phrase stays in the message and becomes the run TITLE: `hold on` pauses a run called “hold on”, `continue the paused run` resumes “continue the paused”, and `that's enough` offers to stop “that's enough”",
     [('        name = _nl_run_name(t, re.sub(rf"^.*?\\b{_T_PAUSE}\\b", "", t, flags=re.I).strip())',
       '        name = _nl_run_name(t, re.sub(r"^.*?\\bpause\\b", "", t, flags=re.I).strip())')]),
    ('E9', SR, 'under',
     '⛔ THE ASK-OWNER ROUTE GOES. `ask its owner if I can use it` is taught and resolved nowhere; it names no machine, so the honest landing is the list you pick one from',
     [('            r"(?:please\\s+)?(?:can (?:i|we) )?(?:ask|request)\\s+"',
       '            r"(?:zzznever)(?:can (?:i|we) )?(?:ask|request)\\s+"')]),
    ('E10', SR, 'under',
     '⛔ THE BARE `no devices` FORM GOES. The negation vocabulary above it is all first-person, and a person reporting the state does not always put themselves in it — the document teaches the bare phrasing and it reached the catch-all',
     [('            or re.fullmatch(rf"(?:no|zero|0)\\s+(?:{_MACHINE_NOUNS_SAID})\\b"\n                            rf"[^.?!]{{0,32}}", low)):',
       '            or False):')]),
    ('X1', SR, 'under',
     '⛔⛤ FROM THE SURVIVOR ROUND, AND IT WAS MY OWN DEFECT. The switch branch stops letting a QUOTED name win outright and goes back to stripping quote characters off the EDGES — which works only while the quote IS the edge. `switch to “Nodes Mac”, thanks` keeps the closing `”`, the leading-noun strip then eats `Nodes`, and the lookup gets `Mac”` — which matched TWO machines on a three-machine account. This branch mutates with NO confirm',
     [('        name = _quoted_name(t) or re.sub(r"[?.!,]+$", "", m.group(1)).strip()',
       '        name = re.sub(r"[?.!,]+$", "", m.group(1)).strip()')]),
    ('X2', SR, 'under',
     '⛔⛤ THE SAME REPAIR AT THE UNLINK BRANCH, where getting it wrong rotates a pair code. `remove “Nodes Mac”, thanks` loses the pairing and the destructive confirm quotes a string no lookup can resolve',
     [('        name = _quoted_name(t) or name.strip().strip(_NL_QUOTE_CHARS).strip()',
       '        name = name.strip().strip(_NL_QUOTE_CHARS).strip()')]),
    ('X3', SR, 'under',
     "⛔ THE SHARED QUOTED-NAME HELPER STOPS PAIRING and takes only the straight-quote alternative, so the picker's own printed `use “<name>”` — and everything a phone types — stops being recognised as a quoted name at the two branches that now rely on it",
     [('_QUOTED_RE = re.compile(_QUOTED_SPAN)',
       '_QUOTED_RE = re.compile(r"\\"([^\\"]+)\\"")')]),
    ('X4', SR, 'over',
     '⛔⛤ FROM THE SURVIVOR ROUND. The skip run-name capture goes back to REJECTING a title that looks like a phase word — which is what I wrote first and it was wrong: all three capture shapes are explicit run-naming, so a run genuinely called “brief” loses the only means the product offers of naming it and the skip lands on the NEWEST run instead',
     [('    if _skip_run and (_skip_run.lower() in _NL_GENERIC_RUN\n                      or _is_bare_machine_noun(_skip_run)):',
       '    if _skip_run and (re.fullmatch(\n            rf"(?:{_NAME_DETERMINER}\\\\s+)?(?:{\'|\'.join(_NL_PHASE_WORDS)})",\n            _skip_run, re.I)\n            or _skip_run.lower() in _NL_GENERIC_RUN\n                      or _is_bare_machine_noun(_skip_run)):')]),
    ('Y1', SR, 'over',
     '⛔⛔⛔ FROM CROSS-VERIFY, AND IT WAS THE MOST DANGEROUS THING THE ROUND FOUND. The last-word test goes and the capture arms mint machine names out of ordinary sentence fragments: `why is my mac not public` captured “mac not”, which SUBSTRING-MATCHED “Mac Notebook” and HID IT with no confirm — a read-only question mutating a machine nobody named. Also `make sure my mac is not public` → “sure my mac is”, `my mac should not be public` → “should not be”, `add my computer to the public list` → “to the”',
     [('            if _vis_obj and not _names_a_machine(_vis_obj):\n                _vis_obj = ""',
       '            if False:\n                _vis_obj = ""')]),
    ('Y2', SR, 'over',
     '⛔⛔⛔ FROM CROSS-VERIFY, AND MY OWN TRIM CAUSED IT. The ambiguous tail words go back to trimming on sight, and the outcome this file refuses above all others returns: on an account holding both “Studio PC Now” and “Studio PC”, `hide my Studio PC Now` HIDES Studio PC with no confirm. 118 distinct name→machine pairs, 430 on branches that never confirm',
     [('_NAME_TAIL_SPACED = re.compile(rf"(?:\\s*[,;]\\s*|\\s+){_NAME_TAIL_ALWAYS}"\n                               rf"\\s*[.!?]*$", re.I)',
       '_NAME_TAIL_SPACED = re.compile(rf"(?:\\\\s*[,;]\\\\s*|\\\\s+)(?:{_NAME_TAIL_ALWAYS[3:-1]}|"\n                               rf"{_NAME_TAIL_COMMA_ONLY[3:-1]})\\\\s*[.!?]*$", re.I)')]),
    ('Y3', SR, 'under',
     '⛔⛔ THE QUOTED ESCAPE HATCH GOES. It worked at ONE capture site of six, and even there it read the matched PATTERN\'s group count rather than whether anything had been quoted — so `pause “Not Today”` captured “Not” and paused a DIFFERENT run, and `stop sharing "Studio PC Now"` was trimmed anyway. Quoting is the one thing a person can do to be unambiguous',
     [('    if whole_message:\n        q = _quoted_name(whole_message)\n        if q and (name or "").strip().strip(_NL_QUOTE_CHARS).strip() == q.strip():\n            return q.strip()',
       '    if False:\n        pass')]),
    ('Y4', SR, 'over',
     '⛔⛔ THE UNQUOTED `use <name>` GOES BACK TO A STOP-LIST, and 24 of 24 driven ordinary objects EXECUTE a device switch with no confirm — `use the web`, `use plain english`, `use bullet points`, `use dark mode`, `use google`, `use my judgment`. That branch repoints where every future run executes',
     [('        or bool(re.search(rf"\\b(?:{_MACHINE_NOUNS_SAID})\\b", _use_obj, re.I)\n                or _looks_like_a_machine_token(_use_obj))',
       '        or bool(True)')]),
    ('Y5', SR, 'over',
     '⛔⛔⛔ THE COSTLIEST WIDENING IN THE WAVE, RESTORED: the publish-side polarity words admit a message with no setter and no copula guard. 192 driven DEVICE LIST requests move onto a publish CONFIRM — `show my shared computers`, `list my visible machines`, `who has access to my shared mac` — along with every copula statement, including `my mac is not visible on the network`, which is the exact opposite of the sentence',
     [('                    or (re.search(rf"\\b{_alt(_PUBLISH_POLARITY_WORDS)}\\b", low)\n                        and re.search(rf"\\b{_VIS_SETTERS}\\b", low)\n                        and not re.search(rf"\\b(?:is|are|was|were|isn\'?t|aren\'?t|"\n                                          rf"wasn\'?t|weren\'?t)\\s+(?:not\\s+)?"\n                                          rf"(?:\\w+\\s+){{0,2}}"\n                                          rf"{_alt(_PUBLISH_POLARITY_WORDS)}\\b", low))',
       '                    or (re.search(rf"\\b{_alt(_PUBLISH_POLARITY_WORDS)}\\b", low))')]),
    ('Y6', SR, 'over',
     '⛔⛔ THE PRONOUN TARGET STOPS REQUIRING A POLARITY WORD, and `turn it off` — the commonest way anybody says STOP THE RUN — executes an UNCONFIRMED HIDE',
     [('    _pronoun_target = bool(re.fullmatch(\n        r"(?:please\\s+|can you\\s+|could you\\s+)*"\n        r"(?:take|put|make|set|switch|turn|keep)\\s+"\n        r"(?:it|this|that|mine)\\s+[^.?!]{0,40}", low)\n        and re.search(rf"\\b(?:{_POLARITY_WORDS[3:-1]}|list|listing|directory)\\b", low))',
       '    _pronoun_target = bool(re.fullmatch(\n        r"(?:please\\\\s+|can you\\\\s+|could you\\\\s+)*"\n        r"(?:take|put|make|set|switch|turn|keep)\\\\s+"\n        r"(?:it|this|that|mine)\\\\s+[^.?!]{0,40}", low))')]),
    ('Y7', SR, 'under',
     "⛔⛔ `keep` LEAVES THE NEGATION FILLER and `don't keep hiding my Studio PC` runs an UNCONFIRMED HIDE — the ask was to STOP hiding it. The gerunds entered the act verbs this wave and the filler had never had to carry it",
     [('_NEG_FILLER = r"(?:\\s+(?:you|i|we|it|to|please|ever|even|really|actually|just|bother(?:ing)?|keep|keeps|continue|carry\\s+on|want\\s+to|need\\s+to|try(?:ing)?\\s+to))*"',
       '_NEG_FILLER = r"(?:\\\\s+(?:you|i|we|it|to|please|ever|even|really|actually|just|bother(?:ing)?|want\\\\s+to|need\\\\s+to|try(?:ing)?\\\\s+to))*"')]),
    ('Y8', SR, 'over',
     '⛔ THE BARE MACHINE TOKEN STOPS REQUIRING TO BE THE WHOLE OBJECT, and ordinary sentences carrying a hyphenated identifier reach a publish confirm: `share COVID-19 findings`, `publish RFC-2119`, `share ISO-8601 with the team` — and `take GPT-4 off the list` EXECUTES a hide',
     [('    _id_target = bool(re.fullmatch(rf"(?:{_NL_LEAD_IN})?{_VIS_SETTERS}\\s+"\n                                   rf"(?:{_NAME_DETERMINER}\\s+)?"\n                                   rf"[A-Za-z0-9][A-Za-z0-9._-]*"\n                                   rf"(?:\\s+(?:to|into|on|onto|as)?\\s*"\n                                   rf"{_VIS_POLARITY_ALL})?"\n                                   rf"(?:[\\s,;]+(?:{_NAME_TAIL_ALWAYS[3:-1]}|"\n                                   rf"{_NAME_TAIL_COMMA_ONLY[3:-1]}))*[.!?]*", low)',
       '    _id_target = bool(True\n                      and re.search(rf"\\\\b{_VIS_SETTERS}\\\\s+(?:{_NAME_DETERMINER}\\\\s+)?"\n                                    rf"([A-Za-z0-9][A-Za-z0-9._-]*)\\\\b", t, re.I)')]),
    ('Y9', SR, 'over',
     "⛔ A POLARITY WORD IN THE GAP MAKES A MACHINE MINE AGAIN, so `show me this week's public computers` and `this is a public computer` are read as the asker's own — which vetoes the browse surface and sends them to a publish confirm naming “week's”",
     [('    _mine_kw = re.search(rf"\\b(my|mine|our|this)\\b"\n                         rf"(?:\\s+(?!(?:{_POLARITY_WORDS[3:-1]})\\b)[\\w\'-]+){{0,4}}\\s+"\n                         rf"(?:{_MACHINE_NOUNS_SAID})\\b", low)',
       '    _mine_kw = re.search(rf"\\\\b(my|mine|our|this)\\\\b(?:\\\\s+[\\\\w\'-]+){{0,4}}\\\\s+"\n                         rf"(?:{_MACHINE_NOUNS_SAID})\\\\b", low)')]),
    ('Y10', SR, 'over',
     "⛔⛔ THE COMPOUND RULE SPLICES THE SETTER LIST AGAIN — the file's own point about that list is that it is a TARGET list, not a signal one. 56 driven ordinary follow-ups are refused: `stop the run and take a break`, `pause the run and put it on hold`, `stop the run and set it aside`",
     [('    rf"(?:switch\\s+to|use|run\\s+(?:it|everything)\\s+on|remove|unlink|forget|delete|"\n    rf"{_VIS_HIDE_ALL[3:-1]}|{_VIS_PUBLISH_ALL[3:-1]})\\b",',
       '    rf"(?:switch\\\\s+to|use|run\\\\s+(?:it|everything)\\\\s+on|{_UNLINK_VERBS[3:-1]}|"\n    rf"{_VIS_HIDE_ALL[3:-1]}|{_VIS_PUBLISH_ALL[3:-1]}|{_VIS_SETTERS[3:-1]})\\\\b",')]),
    ('Y11', SR, 'over',
     '⛔ THE COMPOUND TEST STOPS BLANKING RUN TITLES, so 16 driven titles carrying a conjunction are refused as two commands — `stop the Pause and Share run`, `pause the Stop and Remove research` — and quoting becomes the only escape',
     [('    bare = re.sub(r"\\bthe\\s+[\\w\'\\u2019 -]+?\\s+(?:run|research)\\b", " the run ", bare, flags=re.I)\n    bare = re.sub(r"\\b(?:on|for|in|of)\\s+(?:the\\s+|my\\s+)?[\\w\'\\u2019 -]+?\\s+(?:run|research)\\b",\n                  " on the run ", bare, flags=re.I)',
       '    bare = bare')]),
    ('Y12', SR, 'over',
     "⛔ THE INVENTORY VETO'S DETERMINER BECOMES OPTIONAL AGAIN, so a bare plural product noun counts as an inventory of this account's machines: 90 of 96 driven `research phones|laptops|macs|macbooks` reach the catch-all, and those are ordinary subjects",
     [('            or re.fullmatch(r"(?:my|our|this|these)\\s+(?:own\\s+)?"\n                            rf"(?:{_MACHINE_NOUNS_SAID})", topic, re.I)',
       '            or re.fullmatch(rf"(?:{_NAME_DETERMINER}\\\\s+)?(?:own\\\\s+)?"\n                            rf"(?:{_MACHINE_NOUNS_SAID})", topic, re.I)')]),
    ('Y13', SR, 'under',
     '⛔ `audio overview` GOES BACK INTO THE ARTEFACT-LINK RETURN and is taken from the podcast branch two rules below — the only command that delivers playable audio. The product gets two spellings with two answers',
     [('                    r"(?:brief|report|doc|document|google\\s+doc|notebooklm|"\n                    r"video|youtube|links?|results?)"',
       '                    r"(?:brief|report|doc|document|google\\s+doc|notebooklm|"\n                    r"audio\\s+overview|video|youtube|links?|results?)"')]),
    ('Y14', SR, 'under',
     '⛔ `link` GOES BACK INTO THE PAIRING WORDS AS A BARE NOUN, so any artefact link scoped to a machine is answered with pairing instructions — 8 driven shapes, including `the brief link for my mac`',
     [('            (re.search(rf"\\b(add|pair|connect)\\b.*\\b({_MACHINE_NOUNS_SAID})\\b", low)\n             or re.match(rf"{_NL_LEAD_IN}link\\b.*\\b({_MACHINE_NOUNS_SAID})\\b", low))',
       '            re.search(rf"\\b(add|pair|connect|link)\\b.*\\b({_MACHINE_NOUNS_SAID})\\b", low)')]),
    ('Y15', SR, 'under',
     '⛔ THE DID-THEY-ANSWER BARE ARM GOES DEAD AGAIN on a mandatory space before an optional group: `any news`, `any word`, `any reply` all reach the catch-all while `any news yet` works',
     [('                    r"respond|say yes|get back to me)|any (?:word|answer|reply|news)"\n                    r"(?:\\s+(?:back|yet))?|have they (?:answered|replied|responded)|"',
       '                    r"respond|say yes|get back to me)|any (?:word|answer|reply|news) "\n                    r"(?:back|yet)?|have they (?:answered|replied|responded)|"')]),
    ('Y16', SR, 'under',
     '⛔ `help` GOES BACK TO THE ACCOUNT CHECK, which on an account that already has a computer prints `✓ Signed in as <email>` and nothing else — so the commonest question there is answers a different one',
     [('        return None, [_NL_CATCH_ALL.split("that. ", 1)[-1]\n                      if "that. " in _NL_CATCH_ALL else _NL_CATCH_ALL]',
       '        return ["status-account"], None')]),
    ('Y17', SR, 'over',
     '⛔⛔ THE EXCLUSION GOES BACK TO ONE SHAPE AND ONE KEEPER, and everything else INVERTS: `skip all but phase 3` SKIPS PHASE 3, `skip all but claude and gemini` turns off BOTH keepers, `skip all but the podcast and the brief` skips the brief, and the whole `but keep | but not | but leave` family skips the thing it was told to keep',
     [('        _excl = re.search(r"\\b(?:but|except|apart\\s+from|other\\s+than|excluding)\\s+"\n                          r"(?:not\\s+|leave\\s+|keep\\s+)?(.+)$|"\n                          r"\\b(?:keep|leave|save)\\s+(.+)$", _scan)',
       '        _excl = re.search(r"\\\\bzzznever\\\\b(.+)$", _scan)')]),
    ('Y18', SR, 'under',
     '⛔⛔ THE SKIP QUESTION GUARD GOES BACK TO A `re.match` ANCHORED AT CHARACTER 0, so any preamble defeats it and POSTS A REAL SKIP: `please could you skip the brief`, `btw can i skip the podcast`, `quick question - can i skip the email`. Skip is not confirm-gated',
     [('    _skip_question = (not _polite_skip_order) and (bool(_q_start) or bool(re.match(',
       '    _skip_question = (False) and (bool(_q_start) or bool(re.match(')]),
    ('Y19', SR, 'under',
     "⛔⛔ THE BARE SKIP ARM GOES BACK TO `^skip\\\\b`, so ANY object it does not recognise reaches it — `skip the summary`, `skip the sources`, `skip the transcript`, `skip my computer` — and the bare form RESOLVES THE RUN'S CURRENT BLOCKER, a mutation none of them asked for",
     [('    if (re.fullmatch(r"(?:please\\s+|just\\s+|now\\s+|ok\\s+)*skip"\n                     r"(?:\\s+(?:it|this|that|the\\s+step|the\\s+blocker|"\n                     r"the\\s+current\\s+one|ahead|forward|please|now))*[.!]*", low)\n            or re.search(r"\\bskip (it|this|that|the step|the blocker)\\b", low)\n            or (_skip_run and re.match(rf"{_NL_LEAD_IN}skip\\b", low))) \\\n            and not _skip_question:',
       '    if re.search(r"^skip\\b|\\bskip (it|this|that|the step|the blocker)\\b", low) \\\n            and not _skip_question:')]),
    ('Y20', SR, 'under',
     '⛔ THE `-ing` FORMS LEAVE THE SKIP ADMISSION GATE and `skipping the podcast` falls past both branches into the PODCAST branch, which makes the bridge DOWNLOAD THE AUDIO',
     [('            re.search(r"\\bskip(?:s|ping)?\\b|\\bdrop(?:s|ping)?\\b|"\n                      r"\\b(remove|cut|leave out|without|no)\\b", low):',
       '            re.search(r"\\\\b(skip|drop|remove|cut|leave out|without|no)\\\\b", low):')]),
    ('Y21', SR, 'under',
     '⛔ THE SKIP NUMBER SCAN READS THE UNBLANKED MESSAGE AGAIN, so a number inside a RUN TITLE becomes a phase: `skip phase 3 for the 2024 run` is refused as “Phase 2024” and `skip the video on "Phase 3 Review"` skips phase 3 as well',
     [('        if re.fullmatch(r"(?:please\\s+|just\\s+)*(?:skip|drop)\\s+"\n                        r"\\d+(?:\\s*(?:,|and|&)\\s*\\d+)*[.!]*", _scan):\n            _nums = re.findall(r"\\b(\\d+)\\b", _scan)\n        elif re.search(r"\\b(?:phases?|steps?|p)\\s*\\d", _scan):',
       '        if False:\n            _nums = []\n        elif re.search(r"\\\\b(?:phases?|steps?|p)\\\\s*\\\\d", low):')]),
    ('Y22', SR, 'under',
     '⛔ THE `called|named|titled` SHAPE GOES BACK BELOW THE BARE ONE and is eaten by it — `skip the podcast on run called Deep Research` names a run “run called Deep” — and the bare shape stops rejecting a determiner, so `skip the podcast on the run` names a run “the”, which SUBSTRING-MATCHES an arbitrary run and skips a phase of it',
     [('    _skip_rm = (_NL_QUOTED_RE.search(t)\n                or re.search(r"\\brun\\s+(?:called|named|titled)\\s+"\n                             r"([\\w\'\\u2019 -]+?)\\s*$", t, re.I)\n                or re.search(r"\\b(?:on|for|in|of)\\s+(?:the\\s+|my\\s+)?"\n                             r"((?!(?:the|a|an|my|our|this|that|current|latest|"\n                             r"last|newest|run|research)\\b)[\\w\'\\u2019 -]+?)"\n                             r"\\s+(?:run|research)\\b", t, re.I)\n                # ⛔ AND WITHOUT A PREPOSITION: `skip the Mars run` names a run\n                #    and no phase, which is what the bare form is for.\n                # ⛔⛤ THE TITLE CARRIES NO PREPOSITION OF ITS OWN. A space-tolerant\n                #    capture reached ACROSS one — `skip the podcast on the run`\n                #    came out naming a run “podcast on the” — so each word after\n                #    the first is guarded, not only the first.\n                or re.search(r"\\b(?:the|my)\\s+"\n                             r"((?!(?:the|a|an|my|our|this|that|current|latest|"\n                             r"last|newest|run|research)\\b)[\\w\'\\u2019-]+"\n                             r"(?:\\s+(?!(?:on|for|in|of|the|a|an|my|our|this|that)\\b)"\n                             r"[\\w\'\\u2019-]+)*?)"\n                             r"\\s+(?:run|research)\\b", t, re.I))',
       '    _skip_rm = (_NL_QUOTED_RE.search(t)\n                or re.search(r"\\b(?:on|for|in|of)\\s+(?:the\\s+|my\\s+)?"\n                             r"([\\w\'\\u2019 -]+?)\\s+(?:run|research)\\b", t, re.I)\n                or re.search(r"\\brun\\s+(?:called|named|titled)\\s+"\n                             r"([\\w\'\\u2019 -]+?)\\s*$", t, re.I))')]),
    ('Y23', SR, 'under',
     '⛔ THE SKIP SET REFUSAL GOES BACK INSIDE THE BARE ARM, so `skip all my runs` and `skip both my runs` reach the CATCH-ALL, which says nothing about the thing being asked for, instead of the line that says skip works one run at a time',
     [('    if re.search(r"\\bskip(?:s|ping)?\\b|\\bdrop(?:s|ping)?\\b", low) \\\n            and not _skip_question and _request_names_a_set(t, _skip_run):\n        return None, [_NL_SKIP_ONE_RUN]',
       '    if False:\n        return None, [_NL_SKIP_ONE_RUN]')]),
    ('Y24', SR, 'under',
     '⛔ THE RESEARCH FLAG GATE GOES BACK TO A HAND COPY short by audio, youtube, openai and anthropic against the very lists the loop below it iterates — so `research tesla without audio` starts a PAID RUN titled “tesla without audio” with the exclusion silently dropped',
     [('                rf"(?:the\\s+|a\\s+|any\\s+)?(?:{\'|\'.join(_NL_PHASE_WORDS)}|"\n                rf"{\'|\'.join(_NL_AGENT_WORDS)})s?\\b",',
       '                r"(?:the\\\\s+|a\\\\s+|any\\\\s+)?(?:video|email|podcast|brief|report|chatgpt|gpt|claude|gemini)s?\\\\b",')]),
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
