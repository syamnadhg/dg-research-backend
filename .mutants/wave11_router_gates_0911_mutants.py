"""Mutation harness for wave 1.1 — THE GATES, 2026-09-11.

⛔⛔ WHAT WAVE 1 MEASURED. 12,700 phrasings driven through the live resolver,
124 defects, 39 of them EXECUTING. This harness pins the VETO half — the five
fixes that decide WHETHER the router acts. The capture half is wave 1.2 and is
deliberately not pinned here, so a diff in either is attributable to one kind of
change.

⭐⭐ OWNER'S RULE, 09-09: THE MUTANTS COME FROM THE MEASURED FINDINGS, NOT FROM THE
REPAIR LIST. Every entry below says what its finding DID when it was reproduced
against the live resolver before a line of the repair existed.

⭐⭐ THE DIRECTION LABELS:

    "over"  · the gate FIRES WHEN IT SHOULD NOT — a real machine name refused as
              a set, a legitimate command sent to the catch-all, a question
              guard that eats its own product's wording.
    "under" · the gate FAILS TO FIRE — back toward the measured defect: an
              unconfirmed hide, a negation that executes the verb it refuses, a
              question that pauses a live run, a computer paired unasked.

⭐⭐ THE ONES THAT MATTER MOST, AND WHY:

  N1     — the negation veto goes and 81 of 112 negated forms execute again.
           `don't send the logs` SENDS THE LOGS to support.
  N2     — the veto forgets that the two directions are NOT symmetric. Negating a
           PUBLISH names a concrete act (a hide); negating a HIDE names nothing.
           I flattened this on my first attempt and the existing suite caught it.
  N4/N5  — a negator inside a machine NAME. `make my Now or Never Mac public` HID
           the machine, and the fix for it nearly ate `make my mac not private`.
  C5     — the 84 false positives I SHIPPED IN 7.9-5b: `and`/`or` in the head test
           made `hide my Nodes and Bolts PC` refuse while `hide my Nodes Mac`
           worked. Same defect, one word later.
  Q5/Q6  — ⛔⛔ THE LESSON OF THIS WAVE. A veto in an ordered ladder is NOT inert:
           it hands the message to the NEXT branch. Three times while building
           this, a new veto produced an action on the WRONG feature — pause fell
           through to a device switch, skip fell through to FETCHING A PODCAST.
           "Did not pause" was true in every one of them.
  P3     — the documented past mistake, repeated by me and caught by a test: the
           file says a previous repair "BROKE PAIRING ITSELF" by excluding any
           message containing `use`, the word in `use this code K7XQ-9B2M`. My
           first guard did exactly that.
  F1/F2  — my gate refusing the product's OWN wording: `run everything on my
           Studio PC`, whose branch spells `run (it|everything) on` verbatim.

    python .mutants/wave11_router_gates_0911_mutants.py
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

MINE_AGENT = ("tests/test_router_gates_0911.py "
              "tests/test_bulk_gate_0910.py "
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
    # ---------------- THE FIFTH SET SIGNAL: A CONJUNCTION ----------------
    ('C1', SR, 'under',
     '⛔⛔ THE WHOLE CONJUNCTION SIGNAL GOES, and a set named with `and` is invisible again on EIGHT verbs. Two EXECUTE with no confirm — `hide my mac and pc` and `pause the tesla run and the ford run` — and the rest reach CONFIDENT SINGLE-TARGET confirms, including the destructive unlink (`remove my mac and pc`) and the access grant (`approve my mac and pc`)',
     [('_SET_SIGNALS = (_SET_SIGNAL_PLURAL, _SET_SIGNAL_QUANTIFIED, _SET_SIGNAL_COLLECTIVE,\n                _SET_SIGNAL_TOTALISER, _SET_SIGNAL_CONJUNCTION)',
       '_SET_SIGNALS = (_SET_SIGNAL_PLURAL, _SET_SIGNAL_QUANTIFIED, _SET_SIGNAL_COLLECTIVE,\n                _SET_SIGNAL_TOTALISER)')]),
    ('C2', SR, 'under',
     '⛔ SHAPE i GOES — the repeated determiner that starts a SECOND noun phrase. `hide the Studio PC and the Lab Mac` and `pause the tesla run and the ford run` stop being sets, and both are NAMED machines and runs, so the confirm quotes a welded string as one title',
     [('rf"(?:{_SET_CONJ_NAMED}{_SET_NOUN}|{_SET_NOUN})\\b{_SET_HEAD}"',
       'rf"(?:{_SET_NOUN})\\b{_SET_HEAD}"')]),
    ('C3', SR, 'under',
     '⛔ SHAPE ii GOES — two BARE nouns, which cannot be one name. `hide my mac and pc`, `hide my mac or pc` and `unpublish my mac & pc` go back to executing an unconfirmed hide with the whole phrase as the machine name',
     [('rf"(?:{_SET_CONJ_NAMED}{_SET_NOUN}|{_SET_NOUN})\\b{_SET_HEAD}"',
       'rf"(?:{_SET_CONJ_NAMED}{_SET_NOUN})\\b{_SET_HEAD}"')]),
    ('C4', SR, 'under',
     '⛔⛔ SHAPE iii GOES — two names sharing ONE PLURAL HEAD. `stop my tesla and ford runs` means my tesla runs AND my ford runs; there is only one noun, at the end, so both noun-on-each-side shapes are blind to it, and the possessive is not adjacent to the plural either so the PLURAL signal cannot see it. It came back a confident `Stop "tesla and ford runs"?`',
     [('    rf"|\\b{_SET_POSS_WORD}(?:[\\w\'-]+\\s+){{0,2}}{_SET_CONJ_BARE}(?:[\\w\'-]+\\s+){{0,2}}"\n    rf"(?:{_MACHINE_PLURAL}|{_RUN_PLURAL})\\b{_SET_HEAD}", re.I)',
       '    rf"", re.I)')]),
    ('C5', SR, 'over',
     '⛔⛔⛔ THE 84 FALSE POSITIVES I SHIPPED IN 7.9-5b, RESTORED: `and`/`or` go back into the head test, so any machine whose name has a device noun as its FIRST word and another as its head satisfies it. `hide my Nodes Mac` worked and `hide my Nodes and Bolts PC` came back "I hide one computer at a time" — the same defect one word later, in the class the whole previous wave existed to fix',
     [('_NAME_END_ADVERB = ("alone", "too", "please", "now", "also", "instead",\n                    "again", "anymore", "today")',
       '_NAME_END_ADVERB = ("alone", "too", "please", "now", "also", "instead",\n                    "again", "anymore", "today", "and", "or")')]),
    ('C6', SR, 'over',
     '⛔ THE BOUNDED GAP IN SHAPE i BECOMES AN UNBOUNDED WILDCARD, which is exactly how 7.9-5 ate 96 real machine names. Any name at all can now sit between the conjunction and the head noun',
     [("_SET_CONJ_NAMED = rf\"{_SET_POSS_WORD}(?:{_SET_COUNT})?(?:{_SET_ADJECTIVE})?(?:[\\w'-]+\\s+){{0,2}}\"",
       '_SET_CONJ_NAMED = rf"{_SET_POSS_WORD}(?:{_SET_COUNT})?(?:{_SET_ADJECTIVE})?(?:.*?\\s+)?"')]),
    ('C7', SR, 'over',
     '⛔⛔ SHAPE i STOPS REQUIRING A NEW DETERMINER, which is the ONE fact separating a set from a long name. Without it `my Nodes and Bolts PC` matches the same shape as `the Studio PC and the Lab Mac`, and the 84 false positives come back by a different road',
     [("_SET_CONJ_NAMED = rf\"{_SET_POSS_WORD}(?:{_SET_COUNT})?(?:{_SET_ADJECTIVE})?(?:[\\w'-]+\\s+){{0,2}}\"",
       "_SET_CONJ_NAMED = rf\"(?:{_SET_POSS_WORD})?(?:{_SET_COUNT})?(?:{_SET_ADJECTIVE})?(?:[\\w'-]+\\s+){{0,2}}\"")]),
    ('C8', SR, 'under',
     '⛔ THE RUN NOUNS LEAVE THE CONJUNCTION NOUN LIST, so every run conjunction is unguarded while the machine ones are fine — `pause the tesla run and the ford run` EXECUTES and `retry the tesla run, the ford run and the bmw run` confirms one title',
     [('_SET_NOUN = (rf"(?:{_MACHINE_SINGULAR}|{_MACHINE_PLURAL}|{_RUN_PLURAL}|"\n             rf"runs?|researches?|reports?|briefs?)")',
       '_SET_NOUN = (rf"(?:{_MACHINE_SINGULAR}|{_MACHINE_PLURAL})")')]),
    ('C9', SR, 'over',
     '⛔ THE HEAD TEST LEAVES THE CONJUNCTION SIGNAL, so a name whose second device noun is followed by more words is refused: `hide my Mac and PC Room` is ONE machine and `Room` cannot continue a verb\'s object',
     [('rf"(?:{_SET_CONJ_NAMED}{_SET_NOUN}|{_SET_NOUN})\\b{_SET_HEAD}"',
       'rf"(?:{_SET_CONJ_NAMED}{_SET_NOUN}|{_SET_NOUN})\\b"')]),
    ('C10', SR, 'under',
     '⛔ THE CONJUNCTION VOCABULARY SHRINKS TO BARE `and`, so `or`, `&`, a comma series, `as well as`, `plus` and `but also` all stop naming sets — `hide my mac or pc` and `hide mac, pc and laptop` go back to executing',
     [('_SET_CONJ = r"(?:\\s*,\\s*|\\s*;\\s*|\\s+and\\s+|\\s+or\\s+|\\s*&\\s*|"',
       '_SET_CONJ = r"(?:\\s+and\\s+|"')]),

    # ---------------- MY OWN FOUR FALSE POSITIVES ----------------
    ('F1', SR, 'over',
     "⛔⛔ THE SWITCH BRANCH LOSES ITS LOCAL BLANKING, and my gate refuses the product's OWN documented wording: `run everything on my Studio PC` comes back \"I run on one computer at a time\" while that branch's capture spells `run (?:it |everything )?on` verbatim — ONE machine is named, right after the word. ⭐ THE EXEMPTION MOVED HERE FROM THE TOTALISER because cross-verify measured FIVE regressions from carrying it in the shared signal: `everything` means all the RUNS to a run verb and the whole RESEARCH to this one, so only the branch that owns the wording can own the exemption (see X1)",
     [('        _sw_t = re.sub(r"\\brun\\s+everything\\s+on\\b", "run on", t, flags=re.I)',
       '        _sw_t = t')]),
    ('F2', SR, 'over',
     '⛔ THE PUBLISH AUDIENCE BECOMES A COUNT OF MACHINES. `make my mac public to everyone` was refused as a set — but `everyone` there is WHO CAN SEE IT, publishing is inherently to everyone, and exactly ONE machine was named',
     [('    bare = re.sub(_SET_AUDIENCE, " ", bare, flags=re.I)',
       '    bare = bare')]),
    ('F3', SR, 'over',
     '⛔ A TRAILING READ-ONLY QUESTION BECOMES A SET AGAIN. `stop the tesla run and show me the rest` names ONE run and then asks a second, read-only thing; the `and` is not nominal at all, and `the rest` made it a collective',
     [('    bare = re.sub(_SET_READ_TAIL, " ", bare, flags=re.I)',
       '    bare = bare')]),
    ('F4', SR, 'under',
     '⛔⛔ THE READ-ONLY TAIL STOPS BEING TRIMMED FROM THE CAPTURED NAME, so the phrases the blanker above just un-refused now ACT on a welded title: `Stop "tesla run and show me the rest"?`. ⭐ A fix that turns a wrong REFUSAL into a wrong ACTION is not a fix, which is why both halves ship together',
     [('    out = re.sub(_SET_READ_TAIL, "", whole, flags=re.I).strip()',
       '    out = whole')]),
    ('F5', SR, 'over',
     '⛔⛔ BARE `but` GOES BACK INTO THE EXCLUSION VOCABULARY — a hole I opened and caught in my own test run. `hide my mac but also my pc` has its SECOND MACHINE blanked away as an "exclusion", leaving one target and an unconfirmed hide',
     [('                  r"rather\\s+than|instead\\s+of|but\\s+not|but\\s+leave|"\n                  r"but\\s+don\'?t)\\b[^,.;]*"',
       '                  r"rather\\s+than|instead\\s+of|but)\\b[^,.;]*"')]),
    ('F6', SR, 'under',
     '⛔ `but also` LEAVES THE CONJUNCTION LIST, so `hide my mac but also my pc` names two machines and nothing sees it',
     [('r"\\s+but\\s+also\\s+|\\s+along\\s+with\\s+|\\s+together\\s+with\\s+)"',
       'r"\\s+along\\s+with\\s+|\\s+together\\s+with\\s+)"')]),
    ('F7', SR, 'under',
     '⛔⛔ `but|except|apart` LEAVE THE PEOPLE-COLLECTIVE HEAD TEST IN BOTH COPIES, so `approve everyone but Sam` and `deny everyone except Sam` stop being sets — everyone MINUS ONE is still many people, and the consent surface captures nothing, so the sole waiting row is answered while the person believes they answered the queue. ⛔ TWO EDITS BECAUSE THERE ARE TWO COPIES: this file records adding a guard to the collective signal and then writing the totaliser without it, the same miss twice, so a one-copy mutant here would be killed by the surviving half',
     [('    rf"(?:everyone|everybody)(?=\\s*$|[,.;:!?]|\\s+(?:waiting|pending|who|in\\b|else|but|except|apart|other\\s+than))|"',
       '    rf"(?:everyone|everybody)(?=\\s*$|[,.;:!?]|\\s+(?:waiting|pending|who|in\\b|else))|"'),
      ('    r"(?:everyone|everybody)(?=\\s*$|[,.;:!?]|\\s+(?:waiting|pending|who|in\\b|else|but|except|apart|other\\s+than))|"',
       '    r"(?:everyone|everybody)(?=\\s*$|[,.;:!?]|\\s+(?:waiting|pending|who|in\\b|else))|"')]),

    # ---------------- POLARITY ----------------
    ('N1', SR, 'under',
     '⛔⛔⛔ THE NEGATION VETO GOES AND 81 OF 112 NEGATED FORMS EXECUTE AGAIN, across eight surfaces. `don\'t send the logs` SENDS THE LOGS to support; `don\'t hide my studio pc` and `no need to hide my studio pc` HIDE IT; `don\'t pause the run` PAUSES IT; `please don\'t switch to the office PC` SWITCHES',
     [('    if _negated_command(t):\n        return None, [_NL_CATCH_ALL]',
       '    if False:\n        return None, [_NL_CATCH_ALL]')]),
    ('N2', SR, 'over',
     '⛔⛔ THE VETO FORGETS THAT THE TWO DIRECTIONS ARE NOT SYMMETRIC — the thing I got wrong first, and the existing suite is what caught it. Negating a PUBLISH names a CONCRETE act, a hide: `no longer share my mac` and `I do not want my computer to be public anymore` are hide requests that two tests demand, and they land on the catch-all instead',
     [('    if _NEG_PUBLISH_SIDE.search(bare):\n        return False',
       '    if _NEG_BEFORE_POLARITY.search(bare):\n        return False')]),
    ('N3', SR, 'over',
     '⛔⛔ THE DOUBLE-NEGATION CONJUNCT GOES, AND A MUTATION SURVIVOR IS WHAT FOUND THIS DEFECT IN THE FIRST PLACE. `don\'t make my mac not private` and `never make my mac not private` negate the request AND the polarity, and with the bare inverted-polarity test they reached a PUBLISH CONFIRM — the opposite of the ask, on the surface where one yes makes a machine findable by strangers. ⭐ The first version of this mutant deleted the whole early return and was EQUIVALENT: removing it changes nothing, because the later guards already answer the single-negation case. Pointing it at the conjunct is what made it measure something',
     [('    if _NEG_BEFORE_POLARITY.search(bare) and not _NEG_BEFORE_VERB.search(bare):\n        return False',
       '    if _NEG_BEFORE_POLARITY.search(bare):\n        return False')]),
    ('N4', SR, 'over',
     '⛔⛔⛔ A NEGATOR INSIDE A MACHINE NAME STOPS BEING BLANKED, and `make my Now or Never Mac public` HIDES a machine whose own name says "Never" — the word is in the NAME, not in the request. This is the 7.9-4 lesson in a new place: a word list that cannot tell a name from a keyword eats real machines',
     [('    bare = _NEG_IN_NAME.sub(r"\\1", _outside_quoted_names(text or ""))',
       '    bare = _outside_quoted_names(text or "")')]),
    ('N5', SR, 'over',
     '⛔⛔ THE NAME-NEGATOR BLANKER LOSES ITS POLARITY LOOKAHEAD and eats a REAL negation: `make my mac not private` matches "determiner + one token + negator" exactly as a name does, so the `not` is blanked and the request goes back to EXECUTING A HIDE — the very defect the block exists to fix',
     [('    rf"{_NEG_WORDS}\\b(?!\\s+(?:be\\s+|being\\s+|stay\\s+|remain\\s+)?{_POLARITY_WORDS}\\b)",',
       '    rf"{_NEG_WORDS}\\b",')]),
    ('N6', SR, 'under',
     '⛔⛔ THE VETO MOVES BELOW THE PAIRING BRANCH, so `don\'t add device K7XQ-9B2M` PAIRS THE COMPUTER. The failure was never one branch missing a veto — it was eight — and a veto that is not above every act branch is a veto for whichever branches happen to sit under it',
     [('    if _negated_command(t):\n        return None, [_NL_CATCH_ALL]\n\n    # 1. An access code',
       '    # 1. An access code')]),
    ('N7', SR, 'over',
     '⛔ QUOTED NAMES STOP BEING BLANKED IN THE VETO, so a machine called "Don\'t Panic PC" vetoes its own request. Quoting is the escape every residue in this file offers and it has to work here too',
     [('    bare = _NEG_IN_NAME.sub(r"\\1", _outside_quoted_names(text or ""))',
       '    bare = _NEG_IN_NAME.sub(r"\\1", text or "")')]),
    ('N8', SR, 'under',
     '⛔ THE READ VERBS LEAVE THE NEGATION VOCABULARY, so `stop trying to fetch the podcast` FETCHES IT — the veto never fires and the message reaches the podcast branch',
     [('              rf"switch\\s+to|ask|request|borrow|apply)")',
       '              rf")")')]),
    ('N9', SR, 'over',
     '⛔ THE INTERVENING-WORD LIST BECOMES A WILDCARD, so a negation vetoes any verb later in the same clause — `I don\'t have an update on my machine`, a status ask, is refused on the word `update`. A free span here is how the OLD 40-character negation arm came to read a machine NAME as a negation',
     # ⛔⛔ RESTORED 2026-09-24 TO THE WILDCARD THESE WORDS DESCRIBE. When `keep`
     # joined the list in wave 1.2 the anchor was re-aimed and the replacement
     # swapped for a NARROWING — the opposite defect under an `over` label, which
     # nothing in this harness's own selection pins — so it survived the 10.10
     # close sweep while the wildcard went unmeasured for twelve days. The
     # narrowing is a real, unpinned defect of its own: it is N9b, directly below,
     # a survivor until its killing test lands from the owner's Windows session.
     [('_NEG_FILLER = r"(?:\\s+(?:you|i|we|it|to|please|ever|even|really|actually|just|bother(?:ing)?|keep|keeps|continue|carry\\s+on|want\\s+to|need\\s+to|try(?:ing)?\\s+to))*"',
       '_NEG_FILLER = r"(?:\\s+\\w+)*"')]),
    # ⛔⛔ N9's OLD NARROWING, KEPT AS ITS OWN MUTANT. ⛔ PENDING — its killing test
    # is being written in the owner's Windows session (agent/ is theirs), so N9b
    # SURVIVES until that lands; report it, never hide it.
    ('N9b', SR, 'under',
     '⛔⛔ THE INTERVENING WORDS SHRINK BACK TO THE PRONOUNS, so a negation with `even`, `need to` or `keep` between it and the verb stops vetoing: "don\'t even hide my studio pc" runs an unconfirmed hide and "i don\'t need to send the logs" sends the logs. Killing test PENDING in the owner\'s Windows session (agent/ is theirs); survives until it lands',
     [('_NEG_FILLER = r"(?:\\s+(?:you|i|we|it|to|please|ever|even|really|actually|just|bother(?:ing)?|keep|keeps|continue|carry\\s+on|want\\s+to|need\\s+to|try(?:ing)?\\s+to))*"',
       '_NEG_FILLER = r"(?:\\s+(?:you|i|we|it|to|please))*"')]),
    ('N10', SR, 'over',
     '⛔⛔ THE OFF-ARM GOES BACK TO ONE SHARED VERB LIST, and TURNING SHARING ON HIDES THE MACHINE. `off` belongs with the neutral verbs; the -ing words only ever mean a hide after a verb that is itself negative. `turn on sharing for my mac` executed a private',
     [('        or re.search(r"\\b(?:turn|switch|shut|toggle)\\b(?:(?!\\bon\\b)[^.?!]){0,20}"\n                     r"\\b(?:off|down)\\b", _pol_low)',
       '        or re.search(r"\\b(?:turn|switch|shut|toggle)\\b[^.?!]{0,20}"\n                     r"\\b(?:off|offering|sharing|listing|publishing)\\b", _pol_low)')]),
    ('N11', SR, 'under',
     '⛔ THE `un-` LOOKBEHIND GOES, and `un-hide the Studio PC` HIDES IT — a hyphen is a non-word character, so a word-boundaried `hide` sits inside `un-hide`. Same for `un-delist my mac`',
     [('        re.search(rf"(?<!un-)(?<!un )\\b(?:{_HIDE_POLARITY[3:-1]}|hidden|unlisted|"',
       '        re.search(rf"\\b(?:{_HIDE_POLARITY[3:-1]}|hidden|unlisted|"')]),
    ('N12', SR, 'under',
     '⛔ `un-hide` STOPS MEANING PUBLISH. Excluding it from the hide arm only got it as far as the catch-all; the request it actually makes is a publish, and a person who types the opposite of the word the refusal taught them gets nothing',
     [('                  or re.search(rf"\\bun[- ]?{_VIS_HIDE_ALL}\\b|\\bun-?conceal\\b",\n                               _pol_low))',
       '                  )')]),
    ('N13', SR, 'over',
     '⛔⛔ THE OLD 40-CHARACTER NEGATION ARM COMES BACK WITHOUT THE NAME BLANKING IN FRONT OF IT, which is the combination that hid `Now or Never Mac`: `never` reaches `public` across a machine noun and flips the request',
     [('    _neg_public_side = _NEG_PUBLISH_SIDE.search(_pol_src)',
       '    _neg_public_side = re.search(\n        r"\\b(?:don\'?t|do not|never|no longer|not)\\b[^.?!]{0,40}"\n        r"\\b(?:public|findable|discoverable|shared?|sharing)\\b",\n        _outside_quoted_names(low), re.I)')]),

    # ---------------- THE QUESTION GUARD, AND WHERE A VETO LANDS ----------------
    ('Q1', SR, 'under',
     '⛔⛔ THE QUESTION GUARD LEAVES THE RUN-CONTROL FAMILY and a QUESTION MUTATES A LIVE RUN: `why did it pause` PAUSES IT, `is it safe to try again` RETRIES IT, `did you pause the run` PAUSES IT. The guard existed for skip alone because "skip is not confirm-gated" — and these four are the same',
     [('    _runctl_ok = (not _runctl_question and bool(_names_a_run)',
       '    _runctl_ok = (bool(_names_a_run)')]),
    ('Q2', SR, 'under',
     '⛔⛔ THE RUN-SHAPE REQUIREMENT GOES AND A RESEARCH TOPIC REACHES A DESTRUCTIVE CONFIRM. This is a research product and people type topics: `i want to stop smoking` offered *Stop "smoking"?*, `how do i stop a run` offered *Stop "a"?*, `please stop bothering me` offered *Stop "bothering me"?*',
     [('    _runctl_ok = (not _runctl_question and bool(_names_a_run)',
       '    _runctl_ok = (not _runctl_question')]),
    ('Q3', SR, 'under',
     '⛔⛔ THE SWITCH BRANCH LOSES THE QUESTION GUARD — the one act branch on this surface that mutates with NO CONFIRM AT ALL. Once the run-control family started bailing on questions, every question mentioning a machine fell THROUGH to here: `what about pause the run on the shared machine` came out as `device-use`',
     [('    if m and (re.search(r"\\b(switch to|run (it |everything )?on)\\b", low) or _bare_use) \\\n            and not _q_start and not _runctl_dropped:',
       '    if m and (re.search(r"\\b(switch to|run (it |everything )?on)\\b", low) or _bare_use):')]),
    ('Q4', SR, 'under',
     '⛔ SKIP\'S SECOND BRANCH LOSES THE QUESTION GUARD, and it is the branch that actually fires for a bare `skip`: `should i skip it` SKIPPED A PHASE ON A LIVE RUN, and skip is not confirm-gated so there was no second chance',
     [('    if (re.fullmatch(r"(?:please\\s+|just\\s+|now\\s+|ok\\s+)*skip"\n                     r"(?:\\s+(?:it|this|that|the\\s+step|the\\s+blocker|"\n                     r"the\\s+current\\s+one|ahead|forward|please|now))*[.!]*", low)\n            or re.search(r"\\bskip (it|this|that|the step|the blocker)\\b", low)\n            or (_skip_run and re.match(rf"{_NL_LEAD_IN}skip\\b", low))) \\\n            and not _skip_question:',
       '    if True:')]),
    ('Q5', SR, 'over',
     "⛔⛔⛔ THE LESSON OF THIS WAVE. Skip's device-noun bail is applied to the run-control family WITHOUT the run check, and `pause the run on the shared machine` — which names a run in as many words — bails out of pause, FALLS THROUGH TO THE SWITCH BRANCH and EXECUTES `device-use`. Worse than the defect: it acts on the WRONG FEATURE instead of the right one. A veto in an ordered ladder is NOT inert",
     [('    _runctl_ok = (not _runctl_question and bool(_names_a_run)\n                  and not (_device_noun and not _names_a_run))',
       '    _runctl_ok = (not _runctl_question and bool(_names_a_run)\n                  and not _device_noun)')]),
    ('Q6', SR, 'over',
     '⛔⛔ THE SAME MISTAKE ON SKIP\'S SECOND BRANCH, and the existing suite caught this one. Branch 1 bails on a device noun BY DESIGN so a device message cannot extract a PHASE; branch 2 then catches it and returns a bare skip, which is right. Bailing here too sent `skip the podcast on my computer` on to the PODCAST BRANCH, WHICH FETCHED THE PODCAST',
     # ⛔ RE-AIMED 2026-09-23 (wave 10.10), TWICE WRONG BEFORE. The edit put an
     # `if False:` where a `\` continuation expected the rest of a condition, so
     # it never parsed — and the edit was not even the mistake its words
     # describe: it disabled the SET refusal, while the words are about giving
     # branch 2 branch 1's DEVICE-NOUN BAIL. It now makes exactly that mistake.
     [('            or (_skip_run and re.match(rf"{_NL_LEAD_IN}skip\\b", low))) \\\n'
       '            and not _skip_question:',
       '            or (_skip_run and re.match(rf"{_NL_LEAD_IN}skip\\b", low))) \\\n'
       '            and not _skip_question and not _device_noun:')]),
    ('Q7', SR, 'over',
     '⛔ A BARE VERB STOPS NAMING THE CURRENT RUN. `retry` on its own came back with the catch-all, and a test in the existing suite demands it work',
     [('    _names_a_run = _names_a_run or _runctl_bare',
       '    _names_a_run = _names_a_run')]),
    ('Q8', SR, 'under',
     '⛔⛔ SKIP LOSES ITS SET GATE AGAIN — it was the ONLY mutating act branch in the ladder with none. `skip all my runs`, `skip every run` and `skip both my runs` each executed the bare single-target form against whichever run it landed on, while pause, resume, retry and stop all refuse the same phrasing',
     # ⛔ RE-AIMED 2026-09-23 (wave 10.10). The replacement opened a string it
     # never closed, so the mutant never parsed. And once it parsed it was
     # EQUIVALENT: a later round put a set refusal in FRONT of branch 2 ("the set
     # refusal comes first and does not depend on the object"), so the gate
     # inside branch 2 can no longer be reached by any `skip` that names a set —
     # measured on 19 phrasings, 0 answers changed. Skip "loses its set gate"
     # now only if BOTH go, so both are disabled here.
     [('            and not _skip_question and _request_names_a_set(t, _skip_run):\n'
       '        return None, [_NL_SKIP_ONE_RUN]',
       '            and False:\n'
       '        return None, [_NL_SKIP_ONE_RUN]'),
      ('        if _request_names_a_set(t, _skip_run):\n            return None, [_NL_SKIP_ONE_RUN',
       '        if False:\n            return None, [_NL_SKIP_ONE_RUN')]),
    ('Q9', SR, 'over',
     '⛔⛔ `phones?` LEAVES THE SKIP BRANCH\'S DEVICE NOUN, and a PHONE stops counting as a device there: a machine called “video phone” has its unlink turned into a phase skip, and `remove claude from my phone` switches Claude off a LIVE run with no confirm. ⛔ RE-WORDED 2026-09-24: its old examples, `skip the video on my phone` and `skip the podcast on my phones`, come out the same with or without the edit since wave 1.2 made the phase the object and the set refusal reads its own list, so the words described a defect the edit no longer makes. ⭐ THE DESCRIPTION HERE WAS WRONG ON THE FIRST RUN — it claimed the mutant copied the question guard while the edit narrowed the noun list. A mutant whose words do not match its edit measures one thing and reports another, which is a harness fault',
     [('    _device_noun = re.search(rf"\\b({_MACHINE_NOUNS_SAID})\\b", low)\n    _runctl_question',
       '    _device_noun = re.search(rf"\\b({_MACHINE_NOUNS})\\b", low)\n    _runctl_question')]),

    # ---------------- PAIRING A COMPUTER NOBODY ASKED TO PAIR ----------------
    ('P1', SR, 'under',
     '⛔⛔ THE EXISTING-DEVICE VERB LIST GOES BACK TO BEING HAND-WRITTEN, naming no visibility verb and no read verb — so `hide device LABPC001` and `publish machine LABPC001` PAIR THE COMPUTER instead of changing its visibility. A derived allowlist, never a prose list',
     [('                              rf"|{_VIS_HIDE_ALL[3:-1]}|{_VIS_PUBLISH_ALL[3:-1]}"\n                              rf"|stop|end|abort|cancel|pause|resume|unpause|retry|skip"\n                              rf"|approve|accept|allow|grant|deny|refuse|reject|block"\n                              rf"|logs?|log\\s+files?|diagnostics|support"\n                              rf"|status|state|check|show|list|progress|which|what)\\b", low)',
       '                              rf")\\b", low)')]),
    ('P2', SR, 'under',
     '⛔ THE READ GUARD GOES AND A QUESTION PAIRS A COMPUTER. `status of support code AB12CD34` was answered by PAIRING it — the code shape matches any 8-character token and the message says "code", so the pairing arm won',
     [('        if _bare or (_pairing and not _reading) or (_kw and not _existing):',
       '        if _bare or _pairing or (_kw and not _existing):')]),
    ('P3', SR, 'over',
     '⛔⛔⛔ THE DOCUMENTED PAST MISTAKE, REPEATED — and my first version of this guard DID repeat it. This file says in as many words that a previous repair "BROKE PAIRING ITSELF" by excluding any message containing `use`, which is the word in `use this code K7XQ-9B2M`, the commonest way anybody types one. The client answered a pasted code with the catch-all',
     [('        if _bare or (_pairing and not _reading) or (_kw and not _existing):',
       '        if (_bare or (_pairing and not _reading) or (_kw and not _existing)) \\\n                and not (_existing and not _bare):')]),

    # ---------------- SHARED MACHINERY ----------------
    ('S1', SR, 'over',
     '⛔⛔ THE LEADING-NOUN STRIP LOSES ITS CONJUNCTION GUARD, and `switch to my Nodes and Bolts PC` EXECUTES `device-use` with the name "and Bolts PC" — a dangling conjunction welded onto the front of a machine name, because the name\'s own first word is a device noun and was read as a category word. ⭐ The A/B is what showed it, and only because the conjunction signal had just stopped refusing these names: the strip had ALWAYS been wrong here and the refusal was hiding it',
     [('        return whole if re.match(r"^(?:(?:and|or|plus|as\\s+well\\s+as)\\b|[&+])",\n                                 rest, re.I) else rest',
       '        return rest')]),
    ('S2', SR, 'over',
     '⛔⛝ THE TRIM IS ALLOWED TO RETURN AN EMPTY NAME, which sends the command to the PICKER — the unconfirmed-wrong-target outcome these branches exist to avoid. Measured on `Not My Mac` in 7.9-5b: a machine whose name opens with a trigger word came back empty',
     [('    return out or whole',
       '    return out')]),
    ('S3', SR, 'under',
     '⛔ THE CATCH-ALL SENTENCE IS DUPLICATED, so the negation veto lands on words that can drift away from the ladder\'s own fallback. A second copy of a user-facing sentence is how this file\'s guards have drifted before',
     [('    if _negated_command(t):\n        return None, [_NL_CATCH_ALL]',
       '    if _negated_command(t):\n        return None, ["I didn\'t catch a Super Research request in that."]')]),
    # ⭐⭐ THE RE-MUTATION ROUND — DERIVED FROM THE CROSS-VERIFY FINDINGS, NOT FROM
    # THE REPAIR LIST. That is the owner's rule of 09-09 and the 7.9-3 lesson,
    # where fourteen blockers were fixed WITHOUT being pinned and seventeen repair
    # mutants then survived. Five lenses drove 22,633 phrasings AFTER this harness
    # was 45/45 green and found 76 subjects, 35 of them regressions this wave
    # caused; thirteen were reproduced by hand and all thirteen were real.
    # ⛔⛔ THREE OF THE FIVE ROOT CAUSES ARE THE SAME LESSON THIS WAVE IS ABOUT —
    # a trim ate a real name, a veto handed its message to the wrong branch, and a
    # hand-written list went short. Knowing the lesson did not stop me writing it.
    ('X1', SR, 'over',
     "⛔⛔⛔ THE `everything` EXEMPTION GOES BACK INTO THE SHARED SIGNAL, WHERE IT IS VERB-BLIND — FIVE REGRESSIONS FROM ONE LOOKAHEAD, every one of them green on this harness. `pause everything on my mac` EXECUTED a pause on \"mac\", `retry everything on my mac` EXECUTED, `stop everything on my mac` confirmed Stop \"mac\", `pause everything to do with tesla` EXECUTED, and `hide everything in my devices list` EXECUTED an unconfirmed hide on a set. ⭐ THE WORD MEANS DIFFERENT THINGS TO DIFFERENT VERBS — all the RUNS, or the whole RESEARCH — so a signal both surfaces share cannot carry the exemption; only the branch whose own capture spells the wording can (see F1)",
     [('    r"\\b(?:everything|', '    r"\\b(?:everything\\b(?!\\s+(?:on|to|onto|in|into)\\b)|')]),
    ('X2', SR, 'over',
     "⛔⛔ THE READ-TAIL TRIM LOSES ITS QUESTION-OBJECT REQUIREMENT AND EATS REAL NAMES. `hide my Show and Tell PC` EXECUTED a hide on a machine called \"Show\"; `pause the Show and Tell research` paused a run called \"Show\"; `make my Show and Tell PC public` offered to publish \"Show\". This is the trim-eats-a-real-name class the whole wave exists to close, reintroduced by the wave's own new trim. ⭐ A follow-up question names WHO it is for — show ME, tell me THE REST — and a machine name never does",
     [('                  r"(?:show|list|tell|display|give|name)\\s+"\n                  r"(?:me|us|them|it|myself)\\b[^.?!]*$"',
       '                  r"(?:show|list|tell|display|give|name)\\b[^.?!]*$"')]),
    ('X3', SR, 'over',
     "⛔⛔ BARE `not` GOES BACK INTO THE EXCLUSION VOCABULARY AND COMPOSES WITH THE HEAD-TEST CHANGE INTO A LIVE DEFECT. `hide my computers and my Not Ready PC` had its SECOND MACHINE blanked away as an \"exclusion\", which left the plural without its head and EXECUTED an unconfirmed hide on a set. ⭐ Bare `not` was pre-existing and harmless; removing `and` from the head test was correct on its own; TOGETHER they were a hole, and neither edit looks wrong alone. An exclusion is a CLAUSE, so it has to open one",
     [('_SET_EXCLUSION = (r"(?:(?:(?<=,)|(?<=;)|(?<=\\band)|(?<=\\bbut)|(?<=^))\\s*\\bnot\\b[^,.;]*"',
       '_SET_EXCLUSION = (r"(?:\\bnot\\b[^,.;]*"')]),
    ('X4', SR, 'over',
     "⛔⛔⛔ THE DROPPED-RUN-CONTROL GUARD GOES, AND FOR THE THIRD AND FOURTH TIME IN ONE WAVE A VETO HANDS ITS MESSAGE TO THE WRONG FEATURE. `pause and skip the video` EXECUTES a phase skip and silently drops the pause; `stop and no email` turns the email off a live run and drops the stop. Both name TWO acts, and quietly doing the second one is worse than asking. ⛔ RE-WORDED 2026-09-24: the examples it was written on, `pause and switch to the Studio PC` and `stop and remove the video`, have a second guard now and come out the same with or without this edit. ⛔ A VETO IN AN ORDERED LADDER IS NOT INERT — it gives the message to whatever comes next, every single time, and this wave proved it four times",
     [('    _runctl_dropped = bool(_runctl_verb) and not _runctl_ok',
       '    _runctl_dropped = False')]),
    ('X5', SR, 'over',
     "⛔ THE COPULA LOOKBEHIND GOES AND A STATEMENT OF STATE EXECUTES A HIDE. `my computer is not listed` and `my mac is not public` came back running `device-visibility private` — the person was telling the client what they already see, or asking about it, and the answer was to act on it. The revision this wave started from showed them their devices instead, which is right",
     [('    rf"(?<!\\bis )(?<!\\bare )(?<!\\bwas )(?<!\\bwere )(?<!\\bisn\'t )(?<!\\baren\'t )"\n', '')]),
    ('X6', SR, 'under',
     "⛔⛔ THE ASK SURFACE LEAVES THE NEGATION VOCABULARY — the hand-written list going short, which this file already records happening TWICE. `don't ask to use the Lab Mac` and `never request access to LABPC001` still reached the ask confirm, and that is the ONE verb on this surface that hands the owner this person's name and email, spends one of five asks an hour, and arms a seven-day refusal if the answer is no",
     [('              rf"switch\\s+to|ask|request|borrow|apply)")', '              rf")")')]),
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
