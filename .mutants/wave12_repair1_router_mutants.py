"""Mutation harness — wave 12 repair 1, the chat router's Allow-all arm (2026-09-27).

⛔⛔ WHAT THIS CODE DECIDES. Whether a message about Allow all OPENS the owner's
computer to anyone, CLOSES it, hides it, publishes it, lists other people's
computers, asks a stranger, or pairs a code. Cross-verify round 1 found the first
arm doing each of those on the wrong words, because it read the whole message.
The repair acts only on an allow-all phrase + the person's OWN computer + one
direction from the words GOVERNING the phrase; each mutant below reverts or
breaks exactly one piece of that.

  F5   `join <code>` pairs                F7a-d  hide / publish beside Allow all
  F8a-c, F11, F15  other people's computers → the browse list
  F9   a purpose clause's stop word       F10a-b `join` negated or asked about
  F12a-c  the pronoun / publish subjects  F13  approval off = allow all on
  F14  approve people again = off         F19a-e  the OFF words, doubled, clarify
  F20  the OFF picker's example           F21  sign in to join = sign-in
  S*   the narrowing's own pieces: statement, "joins at once", joiner's ask,
       the pronoun after a comma, `check if`, a named computer, the joiner verb,
       the ON verbs.

⛔⛔ RE-AIMED 2026-09-27 (wave 12 repair 2). The arm these mutants were written on —
`_allow_all_read`, the governing-word polarity, the "rest" re-resolved through the
router, the ask-back — was REBUILT on whole-message commands (cross-verify round 2:
it still misrouted fault reports, joiners and two-computer messages). Each mutant
below is re-aimed at the new code for the SAME defect where that defect can still
happen, with a dated note; where the machinery that could produce it is gone, the
entry is RETIRED as a comment saying why. The new policy's own mutants are in
wave12_repair2_router_mutants.py, and the suites now include its pins.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  python .mutants/wave12_repair1_router_mutants.py
  python .mutants/wave12_repair1_router_mutants.py F9 F19a
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

SUITES = {
    # ⛔ + the repair-2 pins (2026-09-27): the re-aimed mutants are measured there.
    SR: (AGENT, "tests/test_allow_all_router_repair_0927.py tests/test_allow_all_router_0926.py "
                "tests/test_chat_public_792.py tests/test_chat_owner_793.py "
                "tests/test_allow_all_whole_message_0927.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ F5 — a code after `join` ═════════════════════════════════════════════
    ("F5", SR, "⛔⛔ `join K7XQ-9B2M` asks the owner of a computer called “K7XQ-9B2M” — the "
     "code posted as a device id, an ask spent, nothing paired",
     [('    if _join_kw and _ask_obj and (_NL_CODE_RE.fullmatch(_ask_obj)\n',
       '    if False and _join_kw and _ask_obj and (_NL_CODE_RE.fullmatch(_ask_obj)\n')]),

    # ═══ F7 — a hide or a publish beside Allow all ════════════════════════════
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2): the arm hands a hide to the
    # visibility clause when the message says WHAT is hidden. Same defect — only a
    # few hide words count — on the list that now decides it.
    ("F7a", SR, "⛔⛔ only a handful of hide words count — `take my mac off the public list and "
     "turn off allow all` loses the hide and the computer stays LISTED",
     [('                r"\\b(?:public(?:ly)?|private(?:ly)?|hid(?:e|es|den|ing)|unlist\\w*|delist\\w*|"\n'
       '                r"unpublish\\w*|list(?:ed|ing)?|directory|shar(?:e|ed|es|ing)|unshar\\w*|"\n'
       '                r"visib\\w*|invisible|findable|discoverable|find|finding|see|seeing|"\n'
       '                r"discover\\w*|offer\\w*)\\b"\n',
       '                r"\\b(?:private(?:ly)?|hid(?:e|es|den|ing)|unlist\\w*|delist\\w*|"\n'
       '                r"unpublish\\w*)\\b"\n')]),
    # ⛔ F7b RETIRED 2026-09-27 (wave 12 repair 2): it kept the conjunction in "what
    # else the message asks" — the blanked rest the arm re-resolved through the
    # router. Nothing is re-resolved any more (a message with a second clause is not
    # a command), so there is no rest for a conjunction to stay in.
    # ⛔ F7c RETIRED 2026-09-27 (wave 12 repair 2): it left "turn" behind when the
    # phrase was blanked out of the rest — the same removed re-resolution. The name a
    # hide captures beside Allow all is measured by repair2 M14.
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2): "keep it public" used to guard the
    # publish reading; it guards the hide hand-off now, and without it the same words
    # are read the other wrong way.
    ("F7d", SR, "⛔ `keep my mac public but turn off allow all` HIDES the computer the person "
     "said to keep public (it read as a PUBLISH before repair 2)",
     [('                and not re.search(r"\\b(?:keep|keeps|keeping|leave|leaves|stay|stays|remain|"\n',
       '                and not re.search(r"\\bNEVER_F7D\\b(?:keep|keeps|keeping|leave|leaves|stay|stays|remain|"\n')]),

    # ═══ F8 / F11 / F15 — other people's computers ════════════════════════════
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2) onto `_aa_about_others` and the
    # join route; each keeps its defect.
    ("F8a", SR, "⛔⛔ `list public computers that let anyone join` reaches the catch-all — a "
     "joiner's way in, answered with nothing",
     [('        elif _aa_about_others(_aa_rest):\n            _aa_route = (["devices-public"], None)\n',
       '')]),
    ("F8b", SR, "⛔ `join a public computer that lets anyone in` loses the browse list — it asks "
     "the owner of “a public computer”",
     [('    if (not obj or re.match(r"(?:a|an|any|some|another|public|shared|one|ones|all|every)\\b",\n',
       '    if (not obj or re.match(r"NEVER_F8B\\b",\n')]),
    ("F8c", SR, "⛔⛔ THE REPORTED DEFECT (round 2's G4 cause): the person's own computer wins "
     "over other people's — `since my mac is offline, list computers that let anyone join` "
     "is answered as the owner's",
     [('        elif _aa_about_others(_aa_rest):\n',
       '        elif _aa_about_others(_aa_rest) and not _mine_kw:\n')]),
    ("F11", SR, "⛔ `which public computers let anyone join` — a QUESTION about other people's "
     "computers — is not the browse list",
     [('        elif _aa_about_others(_aa_rest):\n',
       '        elif _aa_about_others(_aa_rest) and not _aa_asking:\n')]),
    ("F15", SR, "⛔ `join one of the public computers` is refused as a set",
     [('        or re.match(r"(?:any\\s+|some\\s+|just\\s+)?one\\s+of\\b", _ask_obj, re.I))',
       '        )')]),

    # ═══ F9 — a stop word anywhere ════════════════════════════════════════════
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2): the direction is a grammar row read
    # over the WHOLE message. Same defect class — a command read from words anywhere.
    ("F9", SR, "⛔⛔ THE REPORTED DEFECT'S CLASS: a command is read from words ANYWHERE in the "
     "message — `it won't let anyone join my mac` (a fault report) raises the ON confirm",
     [('    direction = next((d for d, rx in _AA_GRAMMAR if rx.fullmatch(cmd)), None)\n',
       '    direction = next((d for d, rx in _AA_GRAMMAR if rx.search(cmd)), None)\n')]),

    # ═══ F10 — `join` negated or asked about ═════════════════════════════════
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2): `join` left `_MUTATING_VERBS` (it
    # vetoed research topics, cross-verify G12); its negation is read in `_join_kw`.
    ("F10a", SR, "⛔⛔ a negated `join` is a join — `don't join the Studio PC` reaches the ask "
     "confirm",
     [('                and not re.search(rf"\\b{_NEG_WORDS}\\b{_NEG_FILLER}\\s+(?:ask\\s+to\\s+)?join\\b",\n'
       '                                  low)\n', '')]),
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2): the lines moved above the capture.
    ("F10b", SR, "⛔ `did I join the Studio PC` is read as a request to join",
     [('                and not re.match(_NL_LEAD_IN + r"(?:did|do|does|have|has|had|was|were|is|"\n'
       '                                 r"are|am|why|when|what|which|who|how|where)\\b", low)\n', '')]),

    # ═══ F12 — the subjects nothing else supplies ═════════════════════════════
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2): the pronoun is a grammar subject now.
    ("F12a", SR, "⛔⛔ THE REPORTED DEFECT: `make it public and allow all` is not a command — the "
     "pronoun is not a subject",
     [("rf\"setting|allow)\\b)[\\w'’-]+\\s+){{0,3}}?{_MACHINE_SINGULAR}|it|that)\")",
       "rf\"setting|allow)\\b)[\\w'’-]+\\s+){{0,3}}?{_MACHINE_SINGULAR})\")")]),
    ("F12b", SR, "⛔ the pronoun alone is not a subject — `keep it public and let anyone join` "
     "reaches the catch-all instead of the person's own list",
     [('              or _pronoun_target\n', '')]),
    # ⛔ F12c RETIRED 2026-09-27 (wave 12 repair 2): it measured that `publish LABPC001
    # and allow all` reached the ON confirm through the publish the arm handed on.
    # That road is gone with the re-resolution: two requests in one message are not
    # a command, and the catch-all — the "defect" it named — is now the intended,
    # pinned route (test_allow_all_router_repair_0927 FLIPPED, same date).

    # ═══ F13 / F14 — the approval step, both ways ════════════════════════════
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2) onto the grammar rows.
    ("F13", SR, "⛔⛔ `turn off approval for my mac` switches Allow all OFF — the approval step "
     "is read as the setting, not its opposite",
     [('    ("on", r"(?:turn|switch)\\s+off\\s+(?:the\\s+)?approvals?(?:\\s+step)?{T}"),',
       '    ("off", r"(?:turn|switch)\\s+off\\s+(?:the\\s+)?approvals?(?:\\s+step)?{T}"),')]),
    ("F14", SR, "⛔⛔ `I want to approve people on my mac again` raises the approve confirm, "
     "whose nameless yes admits the one waiting stranger",
     [('            r"|approve\\s+(?:people|each\\s+person|every\\s+person|everyone|everybody|each\\s+request|"\n',
       '            r"|NEVER_F14\\s+(?:people|each\\s+person|every\\s+person|everyone|everybody|each\\s+request|"\n'),
      ('    + r"|\\bapprov(?:e|ing)\\s+(?:people|each\\s+person|every\\s+person|everyone|everybody|"\n',
       '    + r"|\\bNEVER_F14B\\s+(?:people|each\\s+person|every\\s+person|everyone|everybody|"\n')]),

    # ═══ F19 — the OFF words ══════════════════════════════════════════════════
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2) onto the grammar. An ON confirm now
    # needs an ON row, so a lost OFF word changes nothing instead of opening the
    # door; the defect measured is the OFF request going unmet.
    ("F19a", SR, "⛔⛔ `uncheck`, `untick`, `remove`, `clear`, `drop` are not OFF words — "
     "`uncheck allow all for my mac` changes nothing",
     [('_AA_OFF_VERB = (r"(?:disable|deactivate|untick|uncheck|remove|clear|drop|kill|end|pause|stop|"',
       '_AA_OFF_VERB = (r"(?:disable|deactivate|kill|end|pause|stop|"')]),
    ("F19b", SR, "⛔⛔ the command line's `no` / `to no` / `false` after the setting is not read — "
     "`set allow all to no for my mac` changes nothing",
     [('    ("off", r"{SET}\\s*[:=]?\\s+(?:off|no|false)(?:\\s+(?:for|on)\\s+{S})?"),',
       '    ("off", r"{SET}\\s*[:=]?\\s+(?:off)(?:\\s+(?:for|on)\\s+{S})?"),'),
      ('    ("off", r"set\\s+{SET}\\s+(?:back\\s+)?to\\s+(?:off|no|false){T}"),',
       '    ("off", r"set\\s+{SET}\\s+(?:back\\s+)?to\\s+(?:off){T}"),')]),
    ("F19c", SR, "⛔ the direction after a short object is not read — `turn allow all on my "
     "mac off` changes nothing",
     [('    ("off", r"(?:{TURN}|shut)\\s+{SET}\\s+(?:for|on)\\s+{S}\\s+(?:back\\s+)?off"),',
       '    ("off", r"NEVER_F19C"),')]),
    ("F19d", SR, "⛔ a negation in front is not read — `never enable allow all for my mac` "
     "raises the ON confirm",
     [('_AA_HEAD = re.compile(r"(?:(?:please|pls|hey|hi|ok|okay|so|now|just)\\b[\\s,]*"',
       '_AA_HEAD = re.compile(r"(?:(?:please|pls|hey|hi|ok|okay|so|now|just|never)\\b[\\s,]*"')]),
    ("F19e", SR, "⛔ ON and OFF in one message ACT on one of them — `turn on allow all for my "
     "mac and turn off auto approve` raises the ON confirm",
     [('_AA_PURPOSE = re.compile(r"\\s*,?\\s+(?:so|because|since)\\b")',
       '_AA_PURPOSE = re.compile(r"\\s*,?\\s+(?:so|because|since|and)\\b")')]),

    # ═══ F20 / F21 ═══════════════════════════════════════════════════════════
    ("F20", SR, "⛔⛔ the OFF picker suggests `let anyone join “X”` — said back, the ON "
     "confirm, whose yes opens the door being closed",
     [('    return _set_device_visibility(args, payload, "let anyone join “{name}”" if value == "yes"\n'
       '                                  else "stop letting anyone join “{name}”")',
       '    return _set_device_visibility(args, payload, "let anyone join “{name}”")')]),
    ("F21", SR, "⛔ `sign in to join the Studio PC` raises the ask confirm, overriding "
     "e567704's sign-in rule",
     [('                and not re.search(rf"\\b{_SIGN_IN_ASK}\\b", low)\n', '')]),

    # ═══ S — the narrowing's own pieces ══════════════════════════════════════
    # ⛔ S1 RETIRED 2026-09-27 (wave 12 repair 2): it removed the copula test that
    # stopped `✓ Allow all is off (“Studio PC” is private)` raising the ON confirm.
    # There is no copula test: a statement is not a whole-message command, so no row
    # reads it — the class is measured by F9 (a command read from words anywhere).
    # ⛔ S2 RETIRED 2026-09-27 (wave 12 repair 2): it measured the filter that
    # dropped `joins at once` unless a machine was in view. `joins at once` is in no
    # grammar row, so it can never raise the ON confirm; the filter only chose
    # between two read-only answers, and repair 2 measured removing it: six corpus
    # messages moved, every one to the browse list a joiner wanted.
    # ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2) onto the whole-message join route.
    ("S3", SR, "⛔ a joiner naming a computer (`join the Studio PC, it lets anyone in`) gets the "
     "browse list instead of the ask",
     [('        _aa_join = _aa_join_route(t)\n', '        _aa_join = None\n')]),
    ("S3b", SR, "⛔ a joiner naming a CODE (`join K7XQ-9B2M, it lets anyone in`) is not paired",
     [('    if (_NL_CODE_RE.fullmatch(obj) or _NL_CONNECTION_CODE_RE.fullmatch(obj)\n',
       '    if False and (_NL_CODE_RE.fullmatch(obj) or _NL_CONNECTION_CODE_RE.fullmatch(obj)\n')]),
    ("S4", SR, "⛔ the comma stays in the name — the ask quotes “Studio PC,”",
     [('    obj = re.split(r"\\s*[,;:(—–]\\s*|', '    obj = re.split(r"\\s*[;:(—–]\\s*|')]),
    ("S5", SR, "⛔ `check allow all` — the checkbox's own verb — is not a command",
     [('    ("on", r"(?:enable|tick|check|activate)\\s+{SET}{T}"),',
       '    ("on", r"(?:enable|tick|activate)\\s+{SET}{T}"),')]),
    ("S6", SR, "⛔ `the office pc` is not a subject — `switch off allow all on the office pc` "
     "is not a command",
     [('                rf"|the\\s+(?:(?!(?:public|shared|open|other|others|any|some|same|one|ones|whole|"',
       '                rf"|NEVER_S6\\s+(?:(?!(?:public|shared|open|other|others|any|some|same|one|ones|whole|"')]),
    ("S7", SR, "⛔⛔ the joiner's verb is not read — `can I borrow the studio pc, it lets anyone "
     "in` is answered with the asker's OWN computers",
     [('_AA_JOINER = re.compile(r"\\b(?:join|borrow|ask\\s+(?:to\\s+(?:use|join)|for)|request\\s+access)\\b"\n',
       '_AA_JOINER = re.compile(r"\\bNEVER_S7\\b"\n')]),
    ("S8", SR, "⛔ approval ON is not read — `turn on approval for my mac` changes nothing",
     [('    ("off", r"(?:(?:turn|switch)\\s+(?:back\\s+)?on\\s+(?:the\\s+)?approvals?(?:\\s+step)?|"',
       '    ("off", r"(?:(?:turn|switch)\\s+(?:back\\s+)?NEVER_S8\\s+(?:the\\s+)?approvals?(?:\\s+step)?|"')]),
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
