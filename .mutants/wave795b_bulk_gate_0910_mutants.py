"""Mutation harness for the bulk gate, rebuilt — 7.9-5b, 2026-09-10.

⛔⛔ WHY THIS WAVE EXISTS. 7.9-5 built a gate so a request for a SET of machines
was refused on all six verbs that could ask. It shipped 52/52 on its own harness
and cross-verify then MEASURED IT AS A REGRESSION: `_BULK_MACHINES` carried a
wildcard filler, so any real machine name shaped `<all|every|each|both> <word>
<machine-noun>` full-matched it. 96 measured phrases, 12 names x 8 verbs — "All
Hands Mac" could no longer be unlinked, published, hidden, asked for, approved or
denied, while `switch to All Hands Mac` still resolved it, so the router read one
string as a name and as a set in the same message. The owner reverted it.

⭐⭐ OWNER'S CALL, 09-09: THE MUTANTS COME FROM THE MEASURED FINDINGS, NOT FROM
THE REPAIR LIST. Every entry below names what its finding DID when it was
reproduced against the live resolver, before a line of the repair existed. That
is the whole reason the numbers here mean anything: the previous harness scored
its own repairs.

⭐⭐ THE DIRECTION LABELS:

    "over"  · the gate FIRES WHEN IT SHOULD NOT — a real machine name refused, a
              browse answered with a refusal, a read-only question answered with
              an offer to publish.
    "under" · the gate FAILS TO FIRE WHEN IT SHOULD — back toward the measured
              defect: an unconfirmed hide, a destructive unlink confirm, a
              stranger let onto somebody's machine.

⭐⭐ THE ONES THAT MATTER MOST, AND WHY:

  P4/P5  — the 7.9-5 defect itself, restored two ways. A wildcard in the
           determiner slot is all it takes for 96 real names to become sets.
  P6     — the bug I WROTE while writing the fix for that bug: `_QUANTIFIERS` as
           a bare alternation leaks `all` as a top-level alternative, and all 384
           generated names classify as sets. It survived my reading of the code
           and died on the corpus.
  P3/S3  — the consent surface, which the signed signal could not see at all
           because the set there is of PEOPLE. `let them all in` and `refuse
           everyone` capture NOTHING and `_resolve_asker("")` returns the sole
           waiting row: one stranger let in, or one person refused for a week,
           while the person believes they answered the queue.
  C1     — the composed rule with the capture as its override, which is how I
           built it first. It defeated four real sets, because on those the
           capture is a FRAGMENT OF the set phrase. The behavioural A/B found it;
           the predicate was 44/44 either way.
  Q1     — quoting stops exempting a name, which removes the one escape the
           plural-NAME residue has and re-eats the run titles.
  S6/R1  — the mirror of the whole wave: a BROWSE refused as a set, and a
           read-only question answered with an offer to publish an unnamed
           machine.

    python .mutants/wave795b_bulk_gate_0910_mutants.py
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
OURS = (SR,)

# ⛔ ONE LEG. Everything this wave touches lives in the skill's `sr.py`, which the
# AGENT suite reads; the root suite never imports it, so a root-leg run would
# score every mutant killed against tests that cannot see the file.
ROOT_LEG_FILES: "tuple[str, ...]" = ()

MINE_AGENT = ("tests/test_bulk_gate_0910.py "
              "tests/test_routing_794.py "
              "tests/test_chat_owner_793.py "
              "tests/test_chat_public_792.py "
              "tests/test_chat_picker_791.py "
              "tests/test_empty_state_794.py "
              "tests/test_owner_verbs_793.py "
              "tests/test_unlink_copy_795.py "
              "tests/test_crossverify_fixes_795.py "
              "tests/test_cli_device_commands_795.py")
MINE_ROOT = "tests/"
MIN_SELECTED_AGENT = 600
MIN_SELECTED_ROOT = 1

ALL_AGENT = "tests/"
ALL_ROOT = "tests/"

_SOLO: "set[str]" = set()

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")


MUTANTS = [
    ('P1', SR, 'under',
     '⛔⛔ THE PLURAL SIGNAL GOES. This is the signed signal and it carries the machine surfaces on its own — `hide my machines` goes straight back to RUNNING the unconfirmed hide with no name, so the picker hides whichever machine it lands on',
     # ⭐ ANCHOR MOVED: cross-verify forced the possessed-head form.
     [('_SET_SIGNAL_PLURAL = re.compile(\n    rf"\\b{_SET_POSSESSIVE}(?:{_MACHINE_PLURAL}|{_RUN_PLURAL})\\b{_SET_HEAD}", re.I)',
       '_SET_SIGNAL_PLURAL = re.compile(r"(?!x)x", re.I)')]),
    ('P2', SR, 'under',
     '⛔⛔ THE QUANTIFIED-SINGULAR SIGNAL GOES, so `hide every computer` and `every computer i have` stop being sets — they use the SINGULAR noun, which is why the signed signal missed them and why this second reading exists',
     # ⭐ ANCHOR MOVED: the signal grew the singular-run arm in cross-verify.
     [('_SET_SIGNAL_QUANTIFIED = re.compile(\n    rf"\\b(?:{_QUANTIFIERS}\\s+{_SET_DETERMINER}"',
       '_SET_SIGNAL_QUANTIFIED = re.compile(\n    rf"(?!x)x(?:{_QUANTIFIERS}\\s+{_SET_DETERMINER}"')]),
    ('P3', SR, 'under',
     '⛔⛔ THE PEOPLE-COLLECTIVE GOES AND THE WHOLE QUEUE IS OPEN AGAIN. This is the surface the signed signal could not see — there is no machine noun in it — and it is the worst one: `let them all in` and `refuse everyone` capture NOTHING, `_resolve_asker("")` returns the sole waiting row, so one stranger is let onto the machine or one person is refused for seven days while the person believes they answered the queue',
     # ⭐ ANCHOR MOVED: the collective grew the head test for `everyone`.
     [('_SET_SIGNAL_COLLECTIVE = re.compile(\n    # ⛔ `everyone`/`everybody` NEEDS THE HEAD TEST TOO — a person can be labelled\n    # "Everyone Smith", and cross-verify found `approve Everyone Smith` refused.\n    rf"\\b(?:them all|all of them|"',
       '_SET_SIGNAL_COLLECTIVE = re.compile(\n    rf"(?!x)x(?:them all|all of them|"')]),
    ('P4', SR, 'over',
     "⛔⛔ THE 7.9-5 DEFECT ITSELF, RESTORED: a wildcard filler joins the determiner slot, so `<quantifier> <word> <machine-noun>` full-matches and every real machine name shaped like 'All Hands Mac' becomes a set — 96 measured phrases, 12 names across 8 verbs, unusable on six verbs while `switch to` still resolved them",
     # ⭐ ANCHOR MOVED to the composed slot: the wildcard goes in the POSSESSIVE
     # word now, which is the same 96-phrase defect in the new shape.
     [('_SET_POSS_WORD = r"(?:my|the|your|their|our|his|her|its)\\s+"',
       '_SET_POSS_WORD = r"(?:\\w+)\\s+"')]),
    ('P5', SR, 'over',
     "⛔ THE DETERMINER SLOT STOPS BEING OPTIONAL-BUT-CLOSED and becomes a bare wildcard word, which is the same defect one notch narrower: 'All Hands Mac' is caught, 'all my computers' still is, and nothing distinguishes them",
     # ⭐ ANCHOR MOVED: the adjective slot is the other place a wildcard fits.
     [('_SET_ADJECTIVE = r"(?:public|private|hidden|other|remaining|spare|old|new)\\s+"',
       '_SET_ADJECTIVE = r"(?:[A-Za-z]+)\\s+"')]),
    ('P6', SR, 'over',
     "⛔⛔ THE QUANTIFIER CONSTANT LOSES ITS GROUP — the exact bug I wrote while writing this fix. Interpolated into the collective's alternation, the trailing `\\s+…` binds to `any` alone and `all`, `every`, `each`, `both` become TOP-LEVEL alternatives, so the bare word 'All' in 'All Hands Mac' matches and all 384 generated names classify as sets",
     [('_QUANTIFIERS = r"(?:all|every|each|both|any)"',
       '_QUANTIFIERS = r"all|every|each|both|any"')]),
    ('P7', SR, 'under',
     '⛔ THE RUN NOUNS GO, so `stop all my runs` and `stop all three runs` stop being sets and each comes back a confident single-run confirm quoting the set as though it were one title',
     [('_RUN_PLURAL = r"(?:runs|researches|reports|briefs)"',
       '_RUN_PLURAL = r"(?!x)x"')]),
    ('P8', SR, 'under',
     "⛔ THE MASS RUN NOUN GOES. `research` has no plural form anywhere in it, so `stop all of my research` — which used to answer 'Stop the current run?' — is invisible to a plural-only test",
     [('_RUN_MASS = r"(?:research|work)"',
       '_RUN_MASS = r"(?!x)x"')]),
    ('Q1', SR, 'over',
     '⛔⛔ QUOTING STOPS EXEMPTING A NAME. The quoted span is no longer blanked, so `stop "All Reports"` is refused as a set — a run title 7.9-5 ate — and so is `make "All Hands Mac" public`, which is the exact string this client\'s own picker tells people to type. It also removes the only escape the plural-NAME residue has',
     [('    return _SET_QUOTED_SPAN.sub(" ", text or "")',
       '    return text or ""')]),
    ('Q2', SR, 'over',
     '⛔ THE QUOTED SPAN IS DELETED INSTEAD OF BLANKED, welding the characters either side into a word nobody typed. ⭐ IT SURVIVED THE FIRST RUN and that survival is what exposed a blocker of mine — see Q2b',
     [('    return _SET_QUOTED_SPAN.sub(" ", text or "")',
       '    return _SET_QUOTED_SPAN.sub("", text or "")')]),
    # ⭐⭐ THE REPAIR MUTANTS. 7.9-3 fixed fourteen blockers WITHOUT pinning them
    # and 17 repair mutants then survived; a survivor closed by an edit rather
    # than by a mutant is a survivor waiting to come back.
    ('Q2b', SR, 'over',
     '⛔⛔ THE BLOCKER Q2\'s SURVIVAL EXPOSED, RESTORED: the span goes back to ANY TWO of the six quote characters, so two contractions make one — `don\'t hide all my computers, it\'s fine` blanks to "don s fine", the set vanishes and the UNCONFIRMED HIDE RUNS. The exact defect this wave closes, reintroduced by the line that grants the escape from it — and this file had already written the warning: `_NL_QUOTED_RE` says apostrophes are not delimiters for precisely this reason',
     [('_SET_QUOTED_SPAN = re.compile(r\'"[^"]*"|“[^”]*”|‘[^’]*’\')',
       '_SET_QUOTED_SPAN = re.compile(\n    rf"[{re.escape(_NL_QUOTE_CHARS)}][^{re.escape(_NL_QUOTE_CHARS)}]*"\n    rf"[{re.escape(_NL_QUOTE_CHARS)}]")')]),
    ('Q2c', SR, 'over',
     "⛔ THE CURLY SINGLE STOPS BEING A PAIR, so the picker's own copy — which substitutes curly singles on phones — loses the quoting escape it tells people to use",
     [('_SET_QUOTED_SPAN = re.compile(r\'"[^"]*"|“[^”]*”|‘[^’]*’\')',
       '_SET_QUOTED_SPAN = re.compile(r\'"[^"]*"|“[^”]*”\')')]),
    ('X1', SR, 'over',
     '⛔⛔ TWO MEASURED 7.9-5 DEFECTS COME BACK: exclusions stop being blanked, so `make my Studio PC public, not all my devices` and `hide the Studio PC and leave all my other machines alone` are refused — one named target plus a clause saying which set to leave out, which is what its whole-message `search` could never tell apart',
     [('    return re.sub(_SET_EXCLUSION, " ", bare, flags=re.I)',
       '    return _outside_quoted_names(text)')]),
    ('X2', SR, 'over',
     "⛔⛔ THE EXCLUSION SPAN LOSES ITS CLAUSE BOUND and runs to the end of the message, so one 'not' anywhere blanks every set after it — `not now. hide all my macs` stops being a set at all. An unbounded span is how 7.9-5's filler ate real names",
     [('r"rather\\s+than|instead\\s+of|but\\s+not|but\\s+leave|"',
       'r"rather\\s+than|instead\\s+of)\\b.*"')]),
    ('X3', SR, 'under',
     '⛔ THE TRAILING EXCLUSION IS NOT TRIMMED OFF A CAPTURED NAME, so `hide the Studio PC and leave all my other machines alone` passes the whole tail as the machine name, resolves to nothing, and drops to the picker',
     # ⭐ ANCHOR MOVED: the trim grew an empty-result guard in cross-verify.
     [('            _vis_obj = _trim_trailing_clause(_vis_obj, t)',
       '            _vis_obj = _vis_obj')]),
    ('C1', SR, 'under',
     "⛔⛔ THE CAPTURE BECOMES THE OVERRIDE — the version I built first. It reads well and it silently unrefuses four real sets, because on those the capture is a FRAGMENT OF the set phrase rather than a name beside it: `approve the queue` captures 'queue', `approve the rest` captures 'rest', `stop all my research on tesla` captures 'tesla'. Each came back a confident single-target confirm and the predicate was 44/44 either way",
     [('    return _names_a_set(_outside_exclusions(message))',
       '    if captured and not _names_a_set(captured):\n        return False\n    return _names_a_set(_outside_exclusions(message))')]),
    ('C2', SR, 'under',
     '⛔ THE RULE READS THE CAPTURE INSTEAD OF THE MESSAGE, so a quoted name — which arrives stripped of its quotes — is refused, and the sets that capture nothing at all go free',
     [('    return _names_a_set(_outside_exclusions(message))',
       '    return _names_a_set(_outside_exclusions(captured or ""))')]),
    ('S1', SR, 'under',
     "⛔⛔ THE UNLINK GATE GOES. Measured, all three on the DESTRUCTIVE confirm: `remove my two macs` offered to unlink a machine called 'two macs', `remove my 2 computers` one called '2 computers', and `remove any of my computers` reopened the 7.9-4 fix — a 'yes' on any of them acts on whatever the resolver lands on",
     [('        if _request_names_a_set(t, name):\n            # ⛔ UNLINK TAKES EXACTLY ONE MACHINE.',
       '        if False:\n            # ⛔ UNLINK TAKES EXACTLY ONE MACHINE.')]),
    ('S2', SR, 'under',
     '⛔⛔ THE VISIBILITY GATE GOES AND THE UNCONFIRMED HIDE IS BACK. Measured: `hide my machines` and `hide my computers` RAN `device-visibility private` with NO name, so the picker hid whichever machine it landed on — no confirm anywhere on that path, by design, because hiding is supposed to be narrowing',
     [('        if _request_names_a_set(t, _vis_obj):\n            _verb = "hide" if _hiding_kw else "publish"',
       '        if False:\n            _verb = "hide" if _hiding_kw else "publish"')]),
    ('S3', SR, 'under',
     '⛔⛔ THE CONSENT GATE GOES. The single most costly one measured: `approve them all`, `approve the queue`, `let them all in`, `refuse everyone` and the whole deny mirror. The ones that capture nothing reach `_resolve_asker("")`, which RETURNS THE SOLE WAITING ROW — one stranger let onto the machine, or one person refused for seven days, while the person believes they answered the queue',
     [('        if _request_names_a_set(t, _who):\n            _plural = "no to" if (_no_kw and not _yes_kw) else "yes to"',
       '        if False:\n            _plural = "no to" if (_no_kw and not _yes_kw) else "yes to"')]),
    ('S4', SR, 'under',
     "⛔ THE STOP GATE GOES. Measured three ways: `stop all of my research` came back 'Stop the current run?', `stop all my research on tesla` came back 'Stop “tesla”?' and `stop all three runs` confirmed — three ways of asking for every run, three confident single-run answers",
     [('        if _request_names_a_set(t, name):\n            return None, ["I stop one run at a time.',
       '        if False:\n            return None, ["I stop one run at a time.')]),
    ('S5', SR, 'under',
     '⛔ THE ASK GATE GOES, so a request for a SET of machines files a disclosure against every owner in it while the confirm can only name one',
     [('        if _request_names_a_set(t, _ask_obj):',
       '        if False and _request_names_a_set(t, _ask_obj):')]),
    ('S6', SR, 'over',
     '⛔⛔ THE SET ARM LOSES ITS SETTER-VERB PAIRING, so `find public computers` and `what public computers are there` — BROWSE requests — enter the visibility branch and are refused as sets. That is the mirror of the defect this wave exists to fix: a reading verb answered with a refusal',
     [('    _set_target = bool(_request_names_a_set(t)\n                       and re.search(rf"\\b{_VIS_SETTERS}\\b", low))',
       '    _set_target = bool(_request_names_a_set(t))')]),
    ('S7', SR, 'under',
     "⛔ THE SET ARM GOES, so `make all the computers public` goes back to answering with the BROWSE list of STRANGERS' machines and `hide every computer` back to the catch-all that denies having the verb",
     [('                 or _set_target) \\',
       '                 ) \\')]),
    ('R1', SR, 'over',
     "⛔⛝ THE LEAD-IN GOES FROM THE STATE QUESTION. Measured: `so are all my computers public?` reached the PUBLISH confirm and offered to publish 'that computer' with NO name, so a 'yes' published whichever one the picker landed on. One conversational word — `so`, `and`, `hey` — turned a read-only question into an offer",
     [('    _asking_state = (re.match(_NL_LEAD_IN + r"(is|are|does|do|can|could|who|what|"',
       '    _asking_state = (re.match(r"^(is|are|does|do|can|could|who|what|"')]),
    ('R2', SR, 'over',
     '⛔ THE LEAD-IN LIST IS COPIED RATHER THAN SHARED, so the research pattern and the state question can drift — which is exactly how `_machine_kw` and `_mine_kw` ended up differing by two words and silently broke four guards',
     [('_NL_LEAD_IN = r"(?:please |can you |could you |would you |hey |ok |okay |go |now |so |and |also |then |just )*"',
       '_NL_LEAD_IN = r"(?:please |can you |could you |would you |hey |ok |okay |go |now )*"')]),
    ('W1', SR, 'under',
     "⛔ THE UNLINK REFUSAL GOES BACK TO ASKING WHICH ONE, which is 7.9-4's measured lesson undone: answering a bulk request with 'which one?' hides that the thing asked for cannot be done at all",
     [('            return None, ["I unlink one computer at a time. Ask me to list them and "\n                          "name the one to remove — nothing is removed until you do."]',
       '            return None, ["Which computer should I unlink? Ask me to list them and "\n                          "name one — nothing is removed until you do."]')]),
    ('W2', SR, 'under',
     '⛔ THE CONSENT REFUSAL STOPS SAYING ONE AT A TIME, so a person asking for the whole queue is told to name somebody without being told the queue cannot be answered at once',
     [('            return None, [f"I say {_plural} one person at a time. Ask me who is "',
       '            return None, [f"Who should I say {_plural}? Ask me who is "')]),
    ('E1', SR, 'over',
     '⛔ THE THREE SIGNALS COLLAPSE TO `any`, so a message needs to trip all three at once — every phrase with only one signal goes free, which is most of them',
     [('    return any(s.search(bare) for s in _SET_SIGNALS)',
       '    return all(s.search(bare) for s in _SET_SIGNALS)')]),
    ('E2', SR, 'under',
     '⛔ THE PHONE WORD GOES from the plural list. `phones?` is deliberately outside `_MACHINE_NOUNS` and inside this gate, because the unlink rule admits it as a thing people SAY while nothing in this product is a phone — so `remove all my phones` is a set and can never be a name',
     [('_MACHINE_PLURAL = "(?:" + _MACHINE_NOUNS_SAID.replace("s?", "s") + ")"',
       '_MACHINE_PLURAL = "(?:" + _MACHINE_NOUNS.replace("s?", "s") + ")"')]),
    # ⭐⭐ THE SECOND ROUND OF REPAIR MUTANTS — cross-verify measured FIFTEEN false
    # positives against the first build, every one a regression on the revision
    # this wave started from. A repair closed by an edit rather than by a mutant
    # is a repair waiting to come back: 7.9-3 left 17 of them.
    ('N1', SR, 'over',
     '⛔⛔ THE POSSESSIVE REQUIREMENT GOES and the plural fires on a bare word anywhere, which is how I shipped it. Fifteen measured false positives: `unlink my Nodes Mac`, `hide my Backup PCs Room` and `remove my Reports Desktop` are SINGULAR machines whose NAMES contain a plural word, and `stop the laptops comparison` and `stop my research how to compare laptops` are research TOPICS — in a research product',
     [('_SET_SIGNAL_PLURAL = re.compile(\n    rf"\\b{_SET_POSSESSIVE}(?:{_MACHINE_PLURAL}|{_RUN_PLURAL})\\b{_SET_HEAD}", re.I)',
       '_SET_SIGNAL_PLURAL = re.compile(\n    rf"\\b(?:{_MACHINE_PLURAL}|{_RUN_PLURAL})\\b", re.I)')]),
    ('N2', SR, 'over',
     "⛔⛔ THE HEAD TEST GOES, so a plural buried mid-name counts: `unlink my Nodes Mac` and `remove my Reports Desktop` are refused again. The plural has to be what the sentence is ABOUT, not a word inside the thing's name",
     [('_SET_HEAD = (r"(?=\\s*$|[,.;:!?]|\\s+(?:"\n             + "|".join(_NAME_END_POLARITY + _NAME_END_ADVERB) + r"))")',
       '_SET_HEAD = r""')]),
    ('N3', SR, 'over',
     "⛔ `everyone` LOSES ITS HEAD TEST, so a person labelled 'Everyone Smith' cannot be approved or denied — cross-verify measured it",
     [('    rf"(?:everyone|everybody)(?=\\s*$|[,.;:!?]|\\s+(?:waiting|pending|who|in\\b|else|but|except|apart|other\\s+than))|"',
       '    rf"everyone|everybody|"')]),
    ('N4', SR, 'under',
     '⛔⛝ THE DETERMINER SLOT GOES BACK TO ENUMERATED COMBINATIONS instead of three independent optional parts, and goes short on the first pairing nobody listed: `ask for all the public computers` needs `the` AND `public` and matched neither alone. A list of combinations is always one combination behind',
     [('_SET_DETERMINER = (rf"(?:{_SET_OF}(?:{_SET_POSS_WORD})?(?:{_SET_COUNT})?"\n                   rf"(?:{_SET_ADJECTIVE})?)")',
       '_SET_DETERMINER = (rf"(?:{_SET_OF}(?:{_SET_POSS_WORD})?(?:{_SET_COUNT})?)")')]),
    # ⭐⭐ THE CROSS-VERIFY REPAIR MUTANTS. Five lenses found ELEVEN defects
    # after 30/30 green; two of them were regressions I introduced in the
    # first build and one was a gap that pre-dates this wave. Each repair
    # gets a mutant, because 7.9-3 fixed fourteen blockers with edits alone
    # and 17 repair mutants then survived.
    ('N5', SR, 'over',
     "⛔⛔ THE POLITE IMPERATIVE LOSES THE LEAD-IN WHILE THE QUESTION TEST KEEPS IT — my own regression, eleven measured phrasings. `_asking_state` is 'question-word AND NOT this', so giving the lead-in to only one side made the question fire while its veto silently could not: `hey can you hide my computer` and `so could you make my computer public` were answered with a bare device list instead of doing the thing",
     [('    _polite_imperative = re.match(_NL_LEAD_IN + r"(?:can|could|would|will|please|do)"',
       '    _polite_imperative = re.match(r"^(?:can|could|would|will|please|do)"')]),
    ('N6', SR, 'over',
     "⛔⛔ THE EXCLUSION TRIM EATS THE WHOLE NAME AGAIN. Written to remove a trailing clause, it took everything when the NAME itself opens with a trigger word — a machine called 'Not My Mac' or 'Other Than Desktop' came back empty and the command fell to the picker, which is the unconfirmed-wrong-machine outcome the branch exists to avoid. Seven measured. The optional separator was what made the whole string matchable",
     # ⛔⛔ RE-AIMED 2026-09-24 ONTO THE DEFECT THESE WORDS DESCRIBE. Wave 1.2 moved
     # the trim into one shared helper and re-pointed this edit at the visibility
     # call — swapping it for the helper's inner half, which drops only the
     # QUOTED-NAME escape at that one site. That is a different defect, nothing in
     # this harness's own selection pins it, and it survived the 10.10 close
     # sweep while the whole-name eat went unmeasured. The eat now needs BOTH of
     # the helper's protections gone — the required separator and the
     # never-empty return; each alone leaves `hide my Not My Mac` intact.
     [('    out = re.sub(rf"\\s*(?:,|;|\\band\\b)\\s*{_SET_EXCLUSION}\\s*$", "", out, flags=re.I).strip()',
       '    out = re.sub(rf"\\s*(?:,|;|\\band\\b)?\\s*{_SET_EXCLUSION}\\s*$", "", out, flags=re.I).strip()'),
      ('    out = re.sub(r"[\\s,;]+$", "", out).strip()\n    return out or whole\n',
       '    out = re.sub(r"[\\s,;]+$", "", out).strip()\n    return out\n')]),
    # ⛔⛔ N6's OLD EDIT, KEPT AS ITS OWN MUTANT. It is a real defect of its own:
    # nothing pins the quoted-name escape at the visibility capture. ⛔ PENDING —
    # its killing test is being written in the owner's Windows session (agent/ is
    # theirs), so N6b SURVIVES until that lands; report it, never hide it.
    ('N6b', SR, 'under',
     '⛔⛔ A QUOTED NAME IS TRIMMED AT THE VISIBILITY CAPTURE. The visibility call takes the trim\'s inner half, which skips the quoted-name escape, so `hide "Mac, not the PC"` cuts the exclusion off the quoted name and hides a machine called \'Mac\' — quoting, the one way to be unambiguous, stops working on hide and publish. Killing test PENDING in the owner\'s Windows session (agent/ is theirs); survives until it lands',
     [('            _vis_obj = _trim_trailing_clause(_vis_obj, t)',
       '            _vis_obj = _trim_trailing_clause_inner(_vis_obj)')]),
    ('N7', SR, 'under',
     '⛔⛔ THE TOTALISER GOES AND FOUR SURFACES REOPEN AT ONCE. The words it holds are exactly the words this file\'s three capture-blankers erase to "", so a blank capture stops meaning anything: `pause everything`, `resume all of it` and `retry it all` EXECUTE with no confirm, `stop everything` and `approve the whole queue` reach confident single-target confirms',
     [('_SET_SIGNALS = (_SET_SIGNAL_PLURAL, _SET_SIGNAL_QUANTIFIED, _SET_SIGNAL_COLLECTIVE,\n                _SET_SIGNAL_TOTALISER, _SET_SIGNAL_CONJUNCTION)',
       '_SET_SIGNALS = (_SET_SIGNAL_PLURAL, _SET_SIGNAL_QUANTIFIED, _SET_SIGNAL_COLLECTIVE)')]),
    ('N8', SR, 'over',
     "⛔⛔ BARE `them` GOES BACK INTO THE TOTALISER, and English has a SINGULAR them: `let them use my computer` is a phrasing this client itself teaches and it means ONE person. The A/B over the product's own corpus is what caught it",
     [('    r"them all|all of them|all of it|it all|both of them|"',
       '    r"them|them all|all of them|all of it|it all|both of them|"')]),
    ('N9', SR, 'under',
     '⛔ THE SINGULAR RUN NOUN GOES, so `every run`, `each run` and `every run i have` stop being sets — and pause/resume/retry EXECUTE with no confirm, so all three ran against whichever run happened to be current',
     [('rf"|{_QUANTIFIERS_TOTAL}\\s+{_SET_DETERMINER}runs?)\\b", re.I)',
       'rf")\\b", re.I)')]),
    ('N10', SR, 'over',
     "⛔ `any` JOINS THE TOTALISING QUANTIFIERS, so `stop any run` is refused — and that is on 7.9-5's measured TOO-WIDE list alongside `approve any`. `any` means whichever one; `every` means all of them",
     [('_QUANTIFIERS_TOTAL = r"(?:all|every|each|both)"',
       '_QUANTIFIERS_TOTAL = r"(?:all|every|each|both|any)"')]),
    ('N11', SR, 'under',
     '⛔⛔ THE SWITCH-TO GATE GOES — the one act branch on this surface that mutates with NO CONFIRM AT ALL, and the one I originally missed. `switch to every computer i have`, `switch to my two macs` and `run it on my remaining laptops` all EXECUTED `device-use` with a set as the machine name',
     [('        if _request_names_a_set(_sw_t, name):\n            return None, ["I run on one computer at a time. Ask me to list them "',
       '        if False:\n            return None, ["I run on one computer at a time. Ask me to list them "')]),
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
