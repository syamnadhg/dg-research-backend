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
    SR: (AGENT, "tests/test_allow_all_router_repair_0927.py tests/test_allow_all_router_0926.py "
                "tests/test_chat_public_792.py tests/test_chat_owner_793.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ F5 — a code after `join` ═════════════════════════════════════════════
    ("F5", SR, "⛔⛔ `join K7XQ-9B2M` asks the owner of a computer called “K7XQ-9B2M” — the "
     "code posted as a device id, an ask spent, nothing paired",
     [('    if _join_kw and _ask_obj and (_NL_CODE_RE.fullmatch(_ask_obj)\n',
       '    if False and _join_kw and _ask_obj and (_NL_CODE_RE.fullmatch(_ask_obj)\n')]),

    # ═══ F7 — a hide or a publish beside Allow all ════════════════════════════
    ("F7a", SR, "⛔⛔ only the first arm's five hide words count — `take my mac off the public "
     "list and turn off allow all` switches Allow all off and leaves it LISTED",
     [('        if _aa_rest_argv[:2] == ["device-visibility", "private"]:\n',
       '        if _aa_rest_argv[:2] == ["device-visibility", "private"] and re.search(\n'
       '                rf"\\b{_HIDE_POLARITY}\\b|\\b(?:hide|hides|hiding|unlist\\w*|'
       'unpublish\\w*|delist\\w*)\\b",\n'
       '                _aa_rest, re.I):\n')]),
    ("F7b", SR, "⛔ the conjunction stays in what else the message asks — `publish my mac "
     "but ask me first` names a computer “mac but”",
     [('            for _i in range(_cj.start() if _cj else _s, _e):\n',
       '            for _i in range(_s, _e):\n')]),
    ("F7c", SR, "⛔ `turn allow all off` leaves “turn” behind — `stop offering my mac and turn "
     "allow all off` hides a computer called “mac and turn”",
     [('        nb = None if b else re.search(', '        nb = None and re.search(')]),
    ("F7d", SR, "⛔ `keep my mac public but turn off allow all` reads as a PUBLISH and "
     "raises the publish confirm instead of switching Allow all off",
     [('                r"\\bpublic(?:ly)?\\b", _aa_rest, re.I))',
       '                r"\\bNEVER_F7D\\b", _aa_rest, re.I))')]),

    # ═══ F8 / F11 / F15 — other people's computers ════════════════════════════
    ("F8a", SR, "⛔⛔ `list public computers that let anyone join` reaches the catch-all — "
     "a joiner's way in, answered with nothing",
     [('        if not _aa_own and _aa_others:\n            return ["devices-public"], None\n',
       '')]),
    ("F8b", SR, "⛔ `join a public computer that lets anyone in` loses the browse list",
     [('        if _aa_joiner:\n            if _aa_others:\n'
       '                return ["devices-public"], None\n',
       '        if _aa_joiner:\n')]),
    ("F8c", SR, "⛔⛔ THE REPORTED DEFECT: any subject is the owner's own — a list of "
     "strangers' computers raises the confirm that opens the asker's",
     [('        _aa_own = bool(\n', '        _aa_own = True or bool(\n')]),
    ("F11", SR, "⛔ `which public computers let anyone join` is not the browse list",
     [('            if _aa_joiner or (_aa_others and not _mine_kw):\n'
       '                return ["devices-public"], None\n', '')]),
    ("F15", SR, "⛔ `join one of the public computers` is refused as a set",
     [('        or re.match(r"(?:any\\s+|some\\s+|just\\s+)?one\\s+of\\b", _ask_obj, re.I))',
       '        )')]),

    # ═══ F9 — the stop word of a purpose clause ═══════════════════════════════
    ("F9", SR, "⛔⛔ THE REPORTED DEFECT: an OFF word ANYWHERE decides — `turn on allow all so "
     "I stop getting requests` switches Allow all OFF, unconfirmed",
     [('        said = {g for g in (("on" if b.group("on") else "off") if b else None,\n',
       '        said = ({"off"} if re.search(rf"\\b(?:{_AA_NEG}|{_AA_OFF_VERB})\\b", src, re.I)'
       ' else set()) or {g for g in (("on" if b.group("on") else "off") if b else None,\n')]),

    # ═══ F10 — `join` negated or asked about ═════════════════════════════════
    ("F10a", SR, "⛔⛔ `join` leaves the negation vocabulary — `don't join the Studio PC` "
     "reaches the ask confirm",
     [('                   rf"join)")', '                   rf"(?!x)x)")')]),
    ("F10b", SR, "⛔ `did I join the Studio PC` is read as a request to join",
     [('                and not re.match(_NL_LEAD_IN + r"(?:did|do|does|have|has|had|was|were|is|"\n'
       '                                 r"are|am|why|when|what|which|who|how|where)\\b", low))\n',
       '                )\n')]),

    # ═══ F12 — the subjects nothing else supplies ═════════════════════════════
    ("F12a", SR, "⛔⛔ THE REPORTED DEFECT: `make it public and allow all` misses the arm — "
     "neither the pronoun nor the publish counts as a subject",
     [('            _mine_kw or _pronoun_target or re.search(_QUOTED_SPAN, t) or _aa_bare\n',
       '            _mine_kw or re.search(_QUOTED_SPAN, t) or _aa_bare\n'),
      ('        if not (_aa_own or _aa_rest_publishes):\n', '        if not _aa_own:\n')]),
    ("F12b", SR, "⛔ the pronoun alone is not a subject — `keep it public and let anyone "
     "join` reaches the catch-all",
     [('            _mine_kw or _pronoun_target or re.search(_QUOTED_SPAN, t) or _aa_bare\n',
       '            _mine_kw or re.search(_QUOTED_SPAN, t) or _aa_bare\n')]),
    ("F12c", SR, "⛔ a publish of a named computer is not a subject — `publish LABPC001 and "
     "allow all` reaches the catch-all",
     [('        if not (_aa_own or _aa_rest_publishes):\n', '        if not _aa_own:\n')]),

    # ═══ F13 / F14 — the approval step, both ways ════════════════════════════
    ("F13", SR, "⛔⛔ `turn off approval for my mac` switches Allow all OFF — the approval "
     "step is read as the setting, not its opposite",
     [('            pol = "on" if said == {"off"} else "off"\n', '            pol = said.pop()\n')]),
    ("F14", SR, "⛔⛔ `I want to approve people on my mac again` raises the approve confirm, "
     "whose nameless yes admits the one waiting stranger",
     [('    r"|\\bapprov(?:e|ing)\\s+(?:people|each\\s+person|every\\s+person|everyone|everybody|"\n',
       '    r"|\\bNEVER_F14\\s+(?:people|each\\s+person|every\\s+person|everyone|everybody|"\n')]),

    # ═══ F19 — the OFF words ══════════════════════════════════════════════════
    ("F19a", SR, "⛔⛔ THE REPORTED DEFECT: `uncheck`, `clear`, `remove`, `drop` are not OFF "
     "words — `uncheck allow all for my mac` raises the ON confirm",
     [('                r"deactivat\\w*|uncheck\\w*|untick\\w*|clear\\w*|remov\\w*|drop\\w*|stop\\w*|"\n',
       '                r"deactivat\\w*|stop\\w*|"\n')]),
    ("F19b", SR, "⛔⛔ the command line's `no` / `to no` / `false` after the phrase is not "
     "read — `set allow all to no for my mac` raises the ON confirm",
     [('    r"(?:(?P<off>off|no(?!\\s+(?:need|more|longer|one|approvals?|questions?))|false|"\n',
       '    r"(?:(?P<off>off|"\n')]),
    ("F19c", SR, "⛔ the direction after a short object is not read — `turn allow all on my "
     "mac off` raises the ON confirm",
     [("    r\"^\\s*(?:(?:on|for|of)\\s+(?:my|the|this|our|that)\\s+(?:[\\w'’-]+\\s+){0,2}?\"\n",
       "    r\"^\\s*(?:(?:NEVER_F19C)\\s+(?:my|the|this|our|that)\\s+(?:[\\w'’-]+\\s+){0,2}?\"\n")]),
    ("F19d", SR, "⛔ a negated governing verb is a direction — `never enable allow all` "
     "raises the ON confirm",
     [('        doubled = bool(b and _AA_BEFORE.search(before[:b.start()]))\n',
       '        doubled = False\n')]),
    ("F19e", SR, "⛔ ON and OFF in one message ACT on one of them instead of asking",
     [('        _aa_pol = next(iter(_aa_pols)) if len(_aa_pols) == 1 else "?"\n',
       '        _aa_pol = next(iter(_aa_pols))\n')]),

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
    ("S1", SR, "⛔ a statement of state acts — `✓ Allow all is off (“Studio PC” is "
     "private)` raises the ON confirm",
     [('        if _aa_question or any(re.match(', '        if _aa_question or False and any(re.match(')]),
    ("S2", SR, "⛔ `joins at once` alone — a row of the list — raises the ON confirm",
     [('                 if p[0] not in ("off_machine", "joins")\n',
       '                 if p[0] not in ("off_machine",)\n')]),
    ("S3", SR, "⛔ a joiner naming a computer (`join the Studio PC, it lets anyone in`) "
     "reaches the catch-all instead of the ask",
     [('            if _aa_rest_argv[:1] == ["device-add"] or _aa_rest_line.startswith(\n'
       '                    _NL_CONFIRMS["device-ask"].split("{name}")[0]):\n'
       '                return _aa_rest_said\n', '')]),
    ("S3b", SR, "⛔ a joiner naming a CODE (`join K7XQ-9B2M, it lets anyone in`) is not paired",
     [('            if _aa_rest_argv[:1] == ["device-add"] or _aa_rest_line.startswith(\n',
       '            if _aa_rest_line.startswith(\n')]),
    ("S4", SR, "⛔ the pronoun after the comma stays in the name — the ask quotes “Studio "
     "PC, it”",
     [('                            r"(?:\\s*\\b(?:it|this|that|which)\\b)?\\s*$", t[:_s], re.I)\n',
       '                            r"\\s*$", t[:_s], re.I)\n')]),
    ("S5", SR, "⛔ `check allow all` — the checkbox's own verb — is read as a question",
     [('                             r"check\\s+(?:if|whether))\\b", low)\n',
       '                             r"check)\\b", low)\n')]),
    ("S6", SR, "⛔ `the office pc` is not a subject — `switch off allow all on the office pc` "
     "reaches the catch-all",
     [('            or re.search(rf"\\b(?:the|that)\\s+(?:(?!(?:public|shared|open|other|others|any|"\n',
       '            or re.search(rf"\\bNEVER_S6\\s+(?:(?!(?:public|shared|open|other|others|any|"\n')]),
    ("S7", SR, "⛔⛔ the joiner's verb is not read — `join the Studio PC, it lets anyone in` "
     "raises the confirm that opens the asker's OWN computer",
     [('        _aa_joiner = re.search(r"\\bjoin\\b|\\bask\\s+(?:to\\s+use|for|the\\s+owner)\\b"\n'
       '                               r"|\\bborrow\\b|\\brequest\\s+access\\b", _aa_rest_low)\n',
       '        _aa_joiner = None\n')]),
    ("S8", SR, "⛔ the ON verbs govern nothing — `turn on approval for my mac` is not read",
     [('_AA_ON_VERB = (r"(?:(?:turn|switch|flip|set|put)(?:s|ed|ing)?\\s+(?:back\\s+)?on|enabl\\w*|"\n',
       '_AA_ON_VERB = (r"(?:NEVER_S8|"\n')]),
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
