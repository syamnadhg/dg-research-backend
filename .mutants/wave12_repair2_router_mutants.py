"""Mutation harness — wave 12 repair 2, the chat's Allow-all arm on WHOLE-MESSAGE
commands (2026-09-27).

⛔⛔ WHAT THIS CODE DECIDES. Whether a chat message SWITCHES Allow all (off at once,
on after a confirm), hides the computer, lists other people's computers, asks a
stranger, or changes nothing. Round 2 of cross-verify found the repair-1 arm reading
direction and subject from phrases INSIDE longer messages — a fault report switched
Allow all off, a joiner's message raised the confirm that opens the joiner's own
computer, a leading clause picked the wrong computer. The rebuild acts only when the
WHOLE message is one command from a small grammar; each mutant below breaks one
rule of that policy, and the test that kills it EXECUTES `sr._nl_resolve`.

  G*   the ON grammar, one row each        H*   the OFF grammar, one row each
  D*   a row's direction flipped            W*   what may surround a command, and
                                                 how its one computer is named
  M*   everything that is NOT a command — the hide hand-off, other people's
       computers, the read-only fallback, the words that count as a mention
  J*   `join`: the negation, past tense, capture gate, the `public computer` name
  T*   the words: the catch-all's phrasings (G25), the publish promise (G28), the
       ask's disclosure (G24)
  K*   SKILL.md's two Allow-all rows

⭐ The repair-1 machinery's own mutants are RE-AIMED onto this code where their
defect can still happen (wave12_repair1_router_mutants.py, wave12_allow_all_agent
_mutants.py R*), or retired with a dated note where it cannot. Nothing here repeats
one of those.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  python .mutants/wave12_repair2_router_mutants.py
  python .mutants/wave12_repair2_router_mutants.py G1 M8 K1
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

SR = "agent/facade/skill/scripts/sr.py"
SKILL = "agent/facade/skill/SKILL.md"

SUITES = {
    SR: (AGENT, "tests/test_allow_all_whole_message_0927.py tests/test_allow_all_router_repair_0927.py "
                "tests/test_allow_all_router_0926.py tests/test_chat_public_792.py "
                "tests/test_chat_owner_793.py tests/test_empty_state_794.py"),
    SKILL: (AGENT, "tests/test_allow_all_whole_message_0927.py tests/test_chat_public_792.py "
                   "tests/test_chat_owner_793.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ G — the ON grammar: each row is the only reader of its phrasing ══════
    ("G1", SR, "⛔ `turn on allow all for my mac` is not a command",
     [('    ("on", r"{TURN}\\s+on\\s+{SET}{T}"),', '    ("on", r"NEVER_G1"),')]),
    ("G2", SR, "⛔ `turn allow all on` is not a command",
     [('    ("on", r"{TURN}\\s+{SET}\\s+(?:back\\s+)?on{T}"),', '    ("on", r"NEVER_G2"),')]),
    ("G3", SR, "⛔ `turn allow all for my mac on` is not a command",
     [('    ("on", r"{TURN}\\s+{SET}\\s+(?:for|on)\\s+{S}\\s+(?:back\\s+)?on"),',
       '    ("on", r"NEVER_G3"),')]),
    ("G4", SR, "⛔ `allow all on` / `allow all yes for my mac` is not a command",
     [('    ("on", r"{SET}\\s*[:=]?\\s+(?:on|yes)(?:\\s+(?:for|on)\\s+{S})?"),',
       '    ("on", r"NEVER_G4"),')]),
    ("G5", SR, "⛔ `set allow all to yes` is not a command",
     [('    ("on", r"set\\s+{SET}\\s+(?:back\\s+)?to\\s+(?:on|yes|true){T}"),',
       '    ("on", r"NEVER_G5"),')]),
    ("G6", SR, "⛔ `enable allow all` / `tick allow all` — the checkbox's own verbs — are not "
     "commands",
     [('    ("on", r"(?:enable|tick|check|activate)\\s+{SET}{T}"),', '    ("on", r"check\\s+{SET}{T}"),')]),
    ("G7", SR, "⛔ `set my mac to allow all` is not a command",
     [('    ("on", r"(?:set|switch|put|turn)\\s+{S}\\s+(?:to|on|onto)\\s+{SET}"),',
       '    ("on", r"NEVER_G7"),')]),
    ("G8", SR, "⛔⛔ `let anyone join my mac` — the plainest ON there is — is not a command",
     [('    ("on", r"let\\s+{W}\\s+(?:join|use)\\s+{S}{X}"),', '    ("on", r"NEVER_G8"),')]),
    ("G9", SR, "⛔ `let anyone join` said alone is not a command",
     [('    ("on", r"let\\s+{W}\\s+join{X}"),', '    ("on", r"NEVER_G9"),')]),
    ("G10", SR, "⛔ `let everyone in` is not a command",
     [('    ("on", r"let\\s+{W}\\s+(?:in|into|onto|on)(?:\\s+(?:to\\s+)?{S})?{X}"),',
       '    ("on", r"NEVER_G10"),')]),
    ("G11", SR, "⛔ `allow everyone to join my computer` is not a command",
     [('    ("on", r"allow\\s+{W}\\s+to\\s+(?:join|use)(?:\\s+{S})?{X}"),', '    ("on", r"NEVER_G11"),')]),
    ("G12", SR, "⛔ `auto-approve requests for my mac` is not a command",
     [('    ("on", r"auto[- ]?(?:approve|accept|admit)(?:\\s+(?:everyone|everybody|anyone|anybody|people|"',
       '    ("on", r"NEVER_G12(?:\\s+(?:everyone|everybody|anyone|anybody|people|"')]),
    ("G13", SR, "⛔ `automatically approve everyone` is not a command",
     [('    ("on", r"(?:automatically\\s+(?:approve|accept)\\s+(?:everyone|everybody|anyone|anybody|people|"',
       '    ("on", r"(?:NEVER_G13\\s+(?:approve|accept)\\s+(?:everyone|everybody|anyone|anybody|people|"')]),
    ("G13b", SR, "⛔ `approve everyone automatically` is not a command",
     [('           r"(?:all\\s+)?requests)|(?:approve|accept)\\s+(?:everyone|everybody|anyone|anybody|people|"',
       '           r"(?:all\\s+)?requests)|(?:NEVER_G13B)\\s+(?:everyone|everybody|anyone|anybody|people|"')]),
    ("G14", SR, "⛔ `turn off approval for my mac` — approval OFF is Allow all ON — is not a command",
     [('    ("on", r"(?:turn|switch)\\s+off\\s+(?:the\\s+)?approvals?(?:\\s+step)?{T}"),',
       '    ("on", r"NEVER_G14"),')]),
    ("G15", SR, "⛔ `turn approvals off` is not a command",
     [('    ("on", r"(?:turn|switch)\\s+(?:the\\s+)?approvals?\\s+off{T}"),', '    ("on", r"NEVER_G15"),')]),
    ("G16", SR, "⛔ `no approval needed` is not a command",
     [('    ("on", r"no\\s+(?:approvals?\\s+needed|more\\s+approvals?){T}"),', '    ("on", r"NEVER_G16"),')]),
    ("G17", SR, "⛔ `stop requiring approval on my mac` (cross-verify G11) is not a command",
     [('r"(?:(?:stop|quit)\\s+requiring|', 'r"(?:(?:NEVER_G17)\\s+requiring|')]),
    ("G18", SR, "⛔ `make my mac public and allow all` — SKILL.md's own example — is not a command",
     [('    ("on", r"(?:make|set)\\s+{S}\\s+public\\s+(?:and|with)\\s+(?:{SET}|let\\s+{W}\\s+join)"),',
       '    ("on", r"NEVER_G18"),')]),
    ("G19", SR, "⛔ `publish my mac with allow all` is not a command",
     [('    ("on", r"publish\\s+{S}\\s+(?:and|with)\\s+{SET}"),', '    ("on", r"NEVER_G19"),')]),

    # ═══ H — the OFF grammar ══════════════════════════════════════════════════
    # ⛔ H1 RE-AIMED 2026-09-27 (first run): its own grammar row SURVIVED removal —
    # the `{OFF}` row already reads turn/switch/shut … off — so the row was an
    # equivalent duplicate and is gone from the code; H1 breaks the words that read it.
    ("H1", SR, "⛔⛔ `turn off allow all for my mac` is not a command",
     [('                r"(?:turn|switch|shut|flip)\\s+off)")', '                r"NEVER_H1)")')]),
    ("H2", SR, "⛔ `turn allow all (back) off` — cross-verify G6 — is not a command",
     [('    ("off", r"(?:{TURN}|shut)\\s+{SET}\\s+(?:back\\s+)?off{T}"),', '    ("off", r"NEVER_H2"),')]),
    ("H4", SR, "⛔ `allow all off` is not a command",
     [('    ("off", r"{SET}\\s*[:=]?\\s+(?:off|no|false)(?:\\s+(?:for|on)\\s+{S})?"),',
       '    ("off", r"NEVER_H4"),')]),
    ("H5", SR, "⛔ `set allow all back to off for my mac` (G6) is not a command",
     [('    ("off", r"set\\s+{SET}\\s+(?:back\\s+)?to\\s+(?:off|no|false){T}"),', '    ("off", r"NEVER_H5"),')]),
    ("H6", SR, "⛔⛔ `disable / uncheck / remove / take off allow all` is not a command",
     [('    ("off", r"{OFF}\\s+{SET}{T}"),', '    ("off", r"NEVER_H6"),')]),
    ("H7", SR, "⛔⛔ `stop letting anyone join my mac` — SKILL.md's own OFF example — is not a "
     "command",
     [('r"(?:stop\\s+letting|don', 'r"(?:NEVER_H7|don')]),
    ("H8", SR, "⛔ `stop allowing anyone to join my mac` is not a command",
     [('    ("off", r"stop\\s+allowing\\s+{WO}\\s+to\\s+join(?:\\s+{S})?"),', '    ("off", r"NEVER_H8"),')]),
    ("H12", SR, "⛔ `make everyone ask before joining my mac` is not a command",
     [('    ("off", r"(?:make|have)\\s+(?:everyone|everybody|people|anyone|them)\\s+ask(?:\\s+first|\\s+again)?"',
       '    ("off", r"NEVER_H12(?:\\s+first|\\s+again)?"')]),
    ("H13", SR, "⛔ an OFF command names nobody but `anyone` — `stop letting strangers onto my "
     "mac` is not one",
     [('_AA_ANYONE_OFF = r"(?:anyone|anybody|everyone|everybody|people|strangers|others)"',
       '_AA_ANYONE_OFF = r"(?:anyone|anybody|everyone|everybody)"')]),

    # ═══ D — a row's direction ════════════════════════════════════════════════
    ("D1", SR, "⛔⛔ `turn on allow all` switches it OFF, unconfirmed",
     [('    ("on", r"{TURN}\\s+on\\s+{SET}{T}"),', '    ("off", r"{TURN}\\s+on\\s+{SET}{T}"),')]),
    ("D2", SR, "⛔⛔ `turn off allow all` / `disable allow all` raise the ON confirm — a yes "
     "opens the door being closed",
     [('    ("off", r"{OFF}\\s+{SET}{T}"),', '    ("on", r"{OFF}\\s+{SET}{T}"),')]),
    ("D3", SR, "⛔⛔ `stop letting anyone join my mac` raises the ON confirm",
     [('    ("off", r"(?:stop\\s+letting|don', '    ("on", r"(?:stop\\s+letting|don')]),

    # ═══ W — what may surround a command, and its one computer ════════════════
    ("W1", SR, "⛔ politeness in front makes it not a command — `please turn off allow all` "
     "changes nothing",
     [('    head = _AA_HEAD.match(s)\n    polite = bool(head and head.group("you"))\n',
       '    head = None\n    polite = False\n')]),
    ("W2", SR, "⛔ thanks behind makes it not a command — `turn off allow all for my mac please`",
     [('    s = _AA_TAIL.sub("", s).strip(" ,")\n', '    s = s.strip(" ,")\n')]),
    ("W3", SR, "⛔ a full stop or an emoji makes it not a command — `turn off allow all 🙏`",
     [('    s = " ".join(_AA_END.sub("", s).split())\n', '    s = " ".join(s.split())\n')]),
    ("W4", SR, "⛔⛔ a purpose clause makes it not a command — `turn on allow all so I stop "
     "getting requests` (cross-verify F9) changes nothing",
     [('_AA_PURPOSE = re.compile(r"\\s*,?\\s+(?:so|because|since)\\b")',
       '_AA_PURPOSE = re.compile(r"NEVER_W4")')]),
    ("W5", SR, "⛔⛔ a purpose clause naming ANOTHER computer still acts — `turn off allow all "
     "on my mac since the lab pc is set up` (G5: two computers, one guess)",
     [('    if subj and _AA_MACHINE_REF.search(rest):\n        return None\n', '')]),
    ("W6", SR, "⛔ a named computer loses its capitals — `the Lab PC` is looked up as “lab pc”",
     [('            name = hit.group(0) if hit else words\n', '            name = words\n')]),
    ("W7", SR, "⛔⛔ a bare machine word is sent as a NAME — `turn off allow all for my mac` "
     "looks for a computer called “mac” instead of the picker",
     [('        if not _is_bare_machine_noun(words):\n', '        if True:\n')]),
    ("W8", SR, "⛔ a quoted name is not taken verbatim — the placeholder is sent as the name",
     [('        name = _cap(_QUOTED_RE.search(t)).strip()\n', '        name = "qqname"\n')]),
    ("W10", SR, "⛔⛔ `the public computer` is the OWNER's subject — `let anyone join the public "
     "computer` raises the confirm that opens the asker's own computer",
     [('(?!(?:public|shared|open|other|others|any|some|same|one|ones|whole|"',
       '(?!(?:NEVER_W10|"')]),

    # ═══ M — everything that is not a command ═════════════════════════════════
    ("M1", SR, "⛔⛔ THE NEVER-WRITE RULE: a message about the person's own computer that is "
     "not a command SWITCHES ALLOW ALL OFF — `my mac won't let anyone join` (G2)",
     [('            _aa_route = (["devices"], None)\n        else:',
       '            _aa_route = (["device-allow-all", "no"], None)\n        else:')]),
    ("M3a", SR, "⛔ `is there anything that lets anyone join` is not the browse list",
     [('    r"|\\b(?:is|are)\\s+there\\b", re.I)', '    r"|\\bNEVER_M3A\\b", re.I)')]),
    ("M3b", SR, "⛔ `pick one of them that lets anyone join` is not the browse list",
     [('|\\bone\\s+of\\s+(?!(?:my|our)\\b)', '|\\bNEVER_M3B\\s+of\\s+(?!(?:my|our)\\b)')]),
    ("M3c", SR, "⛔ `the one that joins at once on the lab pc` is the asker's own computer",
     [('    r"|\\bones?\\s+(?:that|which|where|who)\\b', '    r"|\\bNEVER_M3C\\s+(?:that|which|where|who)\\b')]),
    ("M3d", SR, "⛔ a plural the person OWNS is somebody else's — `which of my computers let "
     "anyone join?` lists strangers' computers",
     [('        if not re.search(r"\\b(?:my|our|these|mine)\\b(?:\\s+\\S+){0,2}\\s*$", src[:m.start()]):\n',
       '        if True:\n')]),
    ("M3e", SR, "⛔ a plural nobody owns is not other people's — `list computers that let "
     "anyone join` (G4) is not the browse list",
     [('    for m in _AA_PLURAL.finditer(src):\n', '    for m in []:\n')]),
    ("M3f", SR, "⛔ `which of my computers …` reads as `which <computer>` — the person's own "
     "computers answered with strangers'",
     [('rf"(?:(?!(?:my|our|mine|this)\\b)', 'rf"(?:(?!(?:NEVER_M3F)\\b)')]),
    ("M4", SR, "⛔ a NEGATED joiner verb is a joiner — `don't join the studio pc that lets "
     "anyone in` lists strangers' computers",
     [('        if not re.search(rf"\\b{_NEG_WORDS}\\b{_NEG_FILLER}\\s*$", src[:m.start()], re.I):\n',
       '        if True:\n')]),
    ("M5", SR, "⛔ a joiner verb aimed at the person's OWN computer is a joiner — `so friends "
     "can join my mac, is allow all on` lists strangers' computers",
     [('                        r"(?!\\s+(?:to\\s+)?(?:my|our|mine|this)\\b)", re.I)',
       '                        r"", re.I)')]),
    ("M6", SR, "⛔⛔ THE REPORTED G29 DEFECT: the name runs into the clause about it — `join the "
     "studio pc that lets anyone in` asks the owner of “studio pc that lets anyone in”",
     [('\\s+(?:that|which|who|where|since|because|so|as|"', '\\s+(?:NEVER_M6|"')]),
    ("M7", SR, "⛔ e567704: `sign in and join the studio pc that lets anyone in` asks a stranger "
     "instead of signing in",
     [('        if re.search(rf"\\b{_SIGN_IN_ASK}\\b", low) and re.search(r"\\bjoin\\b", _aa_rest):\n',
       '        if False:\n')]),
    ("M7b", SR, "⛔ `join my mac, it lets anyone in` asks the owner of “my mac” — the person's own "
     "computer",
     [('    if re.match(r"(?:my|our|mine)\\b", obj, re.I):\n        return ["devices"], None\n', '')]),
    ("M8", SR, "⛔ the person's own computer is not a subject — `my mac won't let anyone join` "
     "gets the catch-all instead of their list",
     [('        elif (_mine_kw or re.search(r"\\bmy own\\b", low) or re.search(_QUOTED_SPAN, t)\n',
       '        elif (re.search(r"\\bmy own\\b", low) or re.search(_QUOTED_SPAN, t)\n')]),
    ("M8b", SR, "⛔ a quoted computer is not a subject — `anyone can join “Studio PC” now` gets "
     "the catch-all",
     [('        elif (_mine_kw or re.search(r"\\bmy own\\b", low) or re.search(_QUOTED_SPAN, t)\n',
       '        elif (_mine_kw or re.search(r"\\bmy own\\b", low)\n')]),
    ("M8c", SR, "⛔ `the office pc lets anyone join` gets the catch-all — `the <name> <machine>` "
     "is not a subject",
     [('              or re.search(rf"\\b(?:the|that)\\s+(?:(?!(?:public|shared|open|other|others|any|"\n',
       '              or re.search(rf"\\bNEVER_M8C\\s+(?:(?!(?:public|shared|open|other|others|any|"\n')]),
    ("M9", SR, "⛔ a question about the setting (`is allow all on?`, G26) gets the catch-all, "
     "never the list whose rows answer it",
     [('                  and (_aa_asking or re.search(r"\\b(?:status|state)\\b", _aa_src)))):\n',
       '                  and False)):\n')]),
    ("M9b", SR, "⛔ `allow all status` (G26) is not a question about the setting",
     [('                  and (_aa_asking or re.search(r"\\b(?:status|state)\\b", _aa_src)))):\n',
       '                  and _aa_asking)):\n')]),
    ("M9c", SR, "⛔ `can you make my mac private and turn off allow all` — a polite imperative — "
     "is read as a question, and the hide is dropped",
     [('        _aa_asking = (not re.match(r"(?:please\\s+)?(?:can|could|would|will)\\s+you\\b", low)\n',
       '        _aa_asking = (True\n')]),
    ("M11", SR, "⛔ `stop letting anyone join or use my mac` — a hide since 7.9-3 — loses the hide",
     [('                rf"|\\b(?:letting|allowing|let|allow)\\s+{_AA_WHO}\\s+(?:(?:join|in)\\s+"\n'
       '                rf"(?:or|and)\\s+)?(?:to\\s+)?use\\b", _aa_src)\n',
       '                , _aa_src)\n')]),
    ("M22", SR, "⛔⛔ G16: a hide needs no hide words — `allow all on my mac, turn it off` (the "
     "`it` is Allow all) HIDES the computer, unconfirmed",
     [('                r"\\b(?:public(?:ly)?|private(?:ly)?|hid(?:e|es|den|ing)|unlist\\w*|delist\\w*|"\n',
       '                r"|\\b(?:public(?:ly)?|private(?:ly)?|hid(?:e|es|den|ing)|unlist\\w*|delist\\w*|"\n')]),
    ("M13", SR, "⛔⛔ a QUESTION or a STATEMENT hides the computer — `why is my mac private if "
     "allow all is on` ran an unconfirmed hide",
     [('        if _aa_asking or re.search(', '        if False and re.search(')]),
    ("M13b", SR, "⛔ a statement of state hides the computer — `since my mac is private, list "
     "computers that let anyone join`",
     [('        if _aa_asking or re.search(', '        if _aa_asking or False and re.search(')]),
    ("M14", SR, "⛔⛔ THE REPORTED G3 DEFECT'S NAME HALF: the allow-all words weld onto the hide's "
     "name (“allow all and make my mac”) through a conjunction and the hide REFUSES",
     [('                    r"\\b(?:and|or)\\b|,|^(?:off|on|down|out)$", _vis_obj, flags=re.I):\n',
       '                    r",|^(?:off|on|down|out)$", _vis_obj, flags=re.I):\n')]),
    ("M14b", SR, "⛔ a second clause welded on through a COMMA — `hide my mac, no more letting "
     "anyone join` hides a computer called “mac, no more letting anyone join”",
     [('                    r"\\b(?:and|or)\\b|,|^(?:off|on|down|out)$", _vis_obj, flags=re.I):\n',
       '                    r"\\b(?:and|or)\\b|^(?:off|on|down|out)$", _vis_obj, flags=re.I):\n')]),
    ("M14c", SR, "⛔ a lone particle is a name — `turn off public and allow all for my mac` "
     "hides a computer called “off”",
     [('                    r"\\b(?:and|or)\\b|,|^(?:off|on|down|out)$", _vis_obj, flags=re.I):\n',
       '                    r"\\b(?:and|or)\\b|,", _vis_obj, flags=re.I):\n')]),
    ("M15", SR, "⛔⛔ `let strangers use my computer` raises the APPROVE confirm, whose nameless "
     "yes admits the one waiting stranger",
     [('    + rf"|\\b(?:let|lets|allow|allows)\\s+{_AA_WHO}\\s+(?:to\\s+)?use\\b"\n', '')]),
    ("M15b", SR, "⛔⛔ `approve anyone who asks for my mac` asks \"Say yes to “anyone who”?\"",
     [('    + r"|\\b(?:approve|accept|admit)\\s+(?:anyone|anybody|whoever)\\b"\n', '')]),
    ("M15c", SR, "⛔⛔ `accept everyone on my mac` raises the nameless approve confirm",
     [('    + r"|\\b(?:accept|admit)\\s+(?:everyone|everybody)\\b"\n', '')]),
    ("M15d", SR, "⛔⛔ `…let them in automatically` raises the nameless approve confirm",
     [('    + r"|\\b(?:let|lets|letting)\\s+(?:them|people|everyone|everybody|anyone|anybody)\\s+"\n'
       '      r"(?:all\\s+)?(?:in|join)\\s+automatically\\b"\n', '')]),
    ("M15e", SR, "⛔ `let me approve each person for my mac` asks \"Say yes to “each person”?\"",
     [('    + r"|\\bapprov(?:e|ing)\\s+(?:each|every)\\s+(?:person|request)\\b"\n', '')]),
    ("M16", SR, "⛔ `allow all requests` counts as the setting — `podcast: allow all requests` "
     "loses the podcast",
     [('cookies?|requests?|"', 'cookies?|"')]),
    ("M18", SR, "⛔ the allow-all phrase's own `join` reads as a joiner's — `let people join the "
     "call` is answered with strangers' computers",
     [('            _aa_rest = _aa_rest[:_m.start()] + " " * (_m.end() - _m.start()) + _aa_rest[_m.end():]\n',
       '            pass\n')]),
    ("M19", SR, "⛔ a quoted name in a whole-message join is not taken verbatim — the ask "
     "quotes the quote marks",
     [('    q = _quoted_name(obj)\n    if q:\n', '    q = _quoted_name(obj)\n    if False:\n')]),
    ("M20", SR, "⛔ `join the computer that lets anyone in` asks the owner of “computer” — a "
     "bare machine word names no row",
     [('    if not obj or _is_bare_machine_noun(obj):\n        return ["devices-public"], None\n',
       '    if not obj:\n        return ["devices-public"], None\n')]),
    ("M21", SR, "⛔ the determiner stays on the joined name — `join the studio pc that lets "
     "anyone in` asks the owner of “the studio pc”, and `the one` is not the list",
     [('    obj = re.sub(r"^(?:the|that|this)\\s+", "", obj, flags=re.I).strip()\n', '')]),
    ("M17", SR, "⛔⛔ G15: `stop the Mars run and turn off allow all` — two commands — raises a "
     "stop confirm for a run called “Mars run and turn off allow all”",
     [('                         and not _AA_SETTING_NAME.search(_aa_src)):\n', '                         ):\n')]),

    # ═══ J — `join` ═══════════════════════════════════════════════════════════
    ("J1", SR, "⛔⛔ G12: `join` goes back into the negation vocabulary — `research why people "
     "don't join unions` is refused as a negated command",
     [('                   rf"switch\\s+to|ask|request|borrow|apply)")',
       '                   rf"switch\\s+to|ask|request|borrow|apply|join)")')]),
    ("J2", SR, "⛔ G13: `I asked to join the Studio PC` asks the owner again",
     [('                and not re.search(r"\\b(?:asked|requested|applied)\\s+to\\s+join\\b", low))\n',
       '                )\n')]),
    ("J3", SR, "⛔⛔ G13: the join capture ignores `_join_kw` — `sign in and ask to join the Studio "
     "PC` asks a stranger instead of signing in, `my friend asked to join my mac` asks the "
     "owner of “mac”",
     [('           or (_join_kw and re.search(r"\\bjoin\\s+(.+)$", t, flags=re.I)))',
       '           or re.search(r"\\bjoin\\s+(.+)$", t, flags=re.I))')]),
    ("J4", SR, "⛔ G20: `join public computer Studio PC` asks the owner of “public computer "
     "Studio PC”, a name no row carries",
     [('        _ask_obj = re.sub(rf"^(?:public|shared)\\s+(?=(?:{_MACHINE_NOUNS})\\s+\\S)", "",\n'
       '                          _ask_obj, flags=re.I)\n', '')]),

    # ═══ T — the words ════════════════════════════════════════════════════════
    ("T1", SR, "⛔ G25: the catch-all never tells a person the two phrasings that work",
     [('                 "anyone who asks join at once (say “turn on Allow all” or “turn "\n'
       '                 "off Allow all”) — what would you like?")',
       '                 "anyone who asks join at once — what would you like?")')]),
    ("T2", SR, "⛔ G28: the publish confirm promises approval on a computer that lets anyone "
     "join",
     [('                         "you would still approve every person yourself, unless "\n'
       '                         "Allow all is already on. Say yes and I’ll switch it on.",',
       '                         "you would still approve every person yourself. Say yes "\n'
       '                         "and I’ll switch it on.",')]),
    ("T3", SR, "⛔ G24: the ask confirm says the owner sees the name OR the email — they see both",
     [('                  "account. The owner sees your name and email. "\n',
       '                  "account. They see your name — or your email, if you haven’t set one. "\n')]),

    # ═══ K — SKILL.md ═════════════════════════════════════════════════════════
    ("K1", SKILL, "⛔⛔ the ON row teaches an OFF phrasing — the model asks to OPEN the door on "
     "`require approval again`",
     [('"stop requiring approval", "make my mac public and allow all" |',
       '"stop requiring approval", "require approval again", "make my mac public and allow all" |')]),
    ("K2", SKILL, "⛔⛔ the OFF row teaches an ON phrasing — `turn on allow all` is run as "
     "`device-allow-all no`",
     [('| "turn off allow all", "turn allow all off",', '| "turn off allow all", "turn on allow all", "turn allow all off",')]),
    ("K4", SKILL, "⛔ G28: the publishing row promises the model the user approves each person "
     "on a computer that already lets anyone join",
     [('the user still approves each person unless Allow all is already on)',
       'the user still approves each person)')]),
    ("K3", SKILL, "⛔⛔ G2: the OFF row no longer says a problem report is not an order — the "
     "model runs OFF on `my mac won't let anyone join`",
     [('⛔ Only a request in ONE direction for ONE computer: "my mac won\'t let anyone join" is a '
       'problem report, not an order — run `sr.py devices`. ', '')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    # ⛔ A SIGTERM MUST RESTORE TOO: Python's default SIGTERM skips `finally:`.
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    for cwd, suites in sorted({SUITES[f] for f in files}, key=str):
        if not green(cwd, suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
        path = ROOT / fname
        raw = ORIGINALS[fname]
        crlf = b"\r\n" in raw
        try:
            mutated = raw.decode("utf-8").replace("\r\n", "\n")
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as se:
                    raise AssertionError(f"mutant does not compile: {se}")
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            if green(*SUITES[fname]):
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:4} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_bytes(raw)

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
