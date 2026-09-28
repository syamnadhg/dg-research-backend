"""Mutation harness — wave 12 repair 4, single-site fixes in the chat's message
reading (2026-09-27).

⛔⛔ WHAT THIS CODE DECIDES. Whether a chat message switches Allow all, pairs a code,
asks a stranger for their computer, starts a paid research run, starts a sign-in
— or changes nothing. Round 4 of cross-verify found each of these on one wrong
reading (agent/tests/test_allow_all_repair4_0927.py names them); each mutant below
brings ONE of them back, and the test that kills it EXECUTES `sr._nl_resolve` or
`sr.py do` with the bridge stubbed.

  K2*  everyone / every request is OFF only with `myself`
  K3*  a code after an ask verb pairs only as the whole message, unquoted, in shape
  K4*, K5*, K17  a research verb: the setting's own words, beside or inside the
       person's own computer (never a phone), quoted names blanked first
  K6   the setting's name is not the computer's
  K7a  two computers are never one (`my` subject; the `the` subject is repair 2's
       W5, restored there)
  K8*  a quoted setting name is the setting; a message quoted whole is the message
  K13* the join's name: its tail, `called X`, one computer
  K14* the owner's Windows rule 2 across a comma or a `but`
  K18* a question that mentions a login is a question

⭐ K11 is repair 1's F21, RESTORED there (its retirement was false); K7's `the`
subject is repair 2's W5, RESTORED there. Older mutants whose anchors moved are
RE-AIMED in their own harnesses with a dated note (repair1 F14 F21, repair2 W5 W8
M7, repair3 E4, allow_all_agent R11 R12 R15 R19, mac_fixes R8 R9 R17, wave792 P7
P12, wave794 T5).

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  python .mutants/wave12_repair4_router_mutants.py
  python .mutants/wave12_repair4_router_mutants.py K2a K8c
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
CLI = "agent/facade/cli.py"

SUITES = {
    SR: (AGENT, "tests/test_allow_all_repair4_0927.py tests/test_allow_all_repair3_0927.py "
                "tests/test_allow_all_whole_message_0927.py tests/test_allow_all_router_repair_0927.py "
                "tests/test_allow_all_router_0926.py tests/test_chat_public_792.py "
                "tests/test_chat_owner_793.py tests/test_empty_state_794.py "
                "tests/test_router_codes_and_computers_0926.py tests/test_allow_all_clients_0926.py "
                "tests/test_public_devices_792.py"),
    CLI: (AGENT, "tests/test_allow_all_repair4_0927.py tests/test_empty_state_794.py "
                 "tests/test_public_devices_792.py tests/test_allow_all_clients_0926.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ K2 — everyone / every request is OFF only with `myself` ═══════════════
    ("K2a", SR, "⛔⛔ `approve everyone each time` / `approve every request going forward` "
     "switch Allow all OFF, unconfirmed — the ON wish read as its opposite",
     [('            r"|approve\\s+(?:people|each\\s+person)(?:{A}{T}|{T}{A})"\n',
       '            r"|approve\\s+(?:people|each\\s+person|everyone|everybody|every\\s+request)'
       '(?:{A}{T}|{T}{A})"\n')]),
    ("K2b", SR, "⛔ `go back to approving everyone` switches Allow all OFF with no `myself`",
     [('    ("off", r"(?:go\\s+back\\s+to\\s+approving\\s+(?:people|each\\s+person){A}?{T}{A}?"\n',
       '    ("off", r"(?:go\\s+back\\s+to\\s+approving\\s+(?:people|each\\s+person|everyone|'
       'every\\s+request){A}?{T}{A}?"\n')]),
    ("K2c", SR, "⛔ `approve everyone myself` — the one spelling that says by hand — is not "
     "the OFF command",
     [('            r"each\\s+request|every\\s+request)(?:\\s+myself{A}?{T}|{T}\\s+myself))"),',
       '            r"each\\s+request|every\\s+request)NEVER_K2C)"),')]),

    # ═══ K3 — a code after an ask verb ═════════════════════════════════════════
    ("K3a", SR, "⛔ a question pairs — `borrow K7XQ-9B2M?` POSTs /device/pair",
     [('    m = None if question else _ASK_CODE_WHOLE.fullmatch(s)\n',
       '    m = _ASK_CODE_WHOLE.fullmatch(s)\n')]),
    ("K3b", SR, "⛔⛔ the code is read from anywhere — `my friend wants to borrow K7XQ-9B2M` pairs",
     [('    m = None if question else _ASK_CODE_WHOLE.fullmatch(s)\n',
       '    m = None if question else _ASK_CODE_WHOLE.search(s)\n')]),
    ("K3c", SR, "⛔⛔ any 8 characters are a code — `ask to use Studio22` pairs a computer's name",
     [('    return tok if (_ASK_CODE_SHAPE.fullmatch(shape) or _NL_CONNECTION_CODE_RE.fullmatch(tok)) else ""\n',
       '    return tok if (_NL_CODE_RE.fullmatch(tok) or _NL_CONNECTION_CODE_RE.fullmatch(tok)) else ""\n')]),
    ("K3d", SR, "⛔ a quoted name is a code — `borrow “K7XQ-9B2M”` pairs",
     [('    s, question = _aa_bare(t)\n    m = None if question else _ASK_CODE_WHOLE',
       '    s, question = _aa_bare(re.sub(r\'[“”"]\', "", t))\n    m = None if question else _ASK_CODE_WHOLE')]),
    ("K3e", SR, "⛔ a dashed word in lower case is a code — `borrow tech-debt` pairs",
     [('    shape = tok.upper() if re.search(r"\\d", tok) else tok\n', '    shape = tok.upper()\n')]),

    # ═══ K4 / K5 / K17 — a research verb and the person's own Allow all ════════
    ("K4a", SR, "⛔⛔ every Allow-all mention counts — `research why my laptop keeps "
     "auto-joining public wifi` gets the Devices list, no run",
     [('               for m in _AA_OWN_WORDS.finditer(_aa_topic)):\n',
       '               for m in _AA_MENTION.finditer(_aa_topic)):\n')]),
    ("K4b", SR, "⛔ a phone counts as the person's computer — `research why my phone lets "
     "anyone join without approval` is refused",
     [('        _own_near = rf"\\b(?:my|our|this)\\s+(?:own\\s+)?(?:[\\w\'’-]+\\s+){{0,2}}?(?:{_MACHINE_NOUNS})\\b"\n',
       '        _own_near = rf"\\b(?:my|our|this)\\s+(?:own\\s+)?(?:[\\w\'’-]+\\s+){{0,2}}?(?:{_MACHINE_NOUNS_SAID})\\b"\n')]),
    ("K4c", SR, "⛔ joining the person's computer needs nobody doing it — `research how to "
     "join my laptop to a domain` is refused",
     [('    + rf"|\\b{_AA_WHO}\\b[^.?!,;]{{0,20}}?\\bjoin(?:s|ing|ed)?\\s+(?:my|our|this)\\s+(?:own\\s+)?"\n',
       '    + rf"|\\bjoin(?:s|ing|ed)?\\s+(?:my|our|this)\\s+(?:own\\s+)?"\n')]),
    ("K4d", SR, "⛔ auto-join / auto-accept are the setting's own words — the wifi topic is "
     "refused",
     [('    + r"|\\bauto(?:matic(?:ally)?)?[- ]?approv\\w*"\n',
       '    + r"|\\bauto(?:matic(?:ally)?)?[- ]?(?:approv|accept|admit|join)\\w*"\n')]),
    ("K5a", SR, "⛔⛔ the person's computer INSIDE the words is not seen — `look into why "
     "people join my mac` starts a PAID run",
     [('               or re.search(_own_near, m.group(0))\n', '')]),
    ("K5b", SR, "⛔ the computer counts across a comma — `research on my mac, how companies "
     "let anyone join Slack` is refused",
     [('        if any(re.search(rf"{_own_near}[^.?!,;]{{0,20}}$", _aa_topic[:m.start()])\n',
       '        if any(re.search(rf"{_own_near}.{{0,20}}$", _aa_topic[:m.start()])\n')]),
    ("K17", SR, "⛔ the topic's quotes come off before its names are blanked — `research EV "
     "batteries on my mac “Allow All Lab”` gets the Devices list",
     [('        _aa_topic = _outside_quoted_names(rm.group(1).lower())\n',
       '        _aa_topic = _outside_quoted_names(topic.lower())\n')]),

    # ═══ K6 — the setting's name is not the computer's ═════════════════════════
    ("K6", SR, "⛔ `turn off the auto-approve for my mac` looks for a computer called "
     "“auto-approve for my mac”",
     [('    subj = re.search(rf"\\b{_AA_SUBJ}\\b", re.sub(_AA_SETTING, lambda m: " " * len(m.group(0)), cmd))\n',
       '    subj = re.search(rf"\\b{_AA_SUBJ}\\b", cmd)\n')]),

    # ═══ K7 — two computers are never one (`my …`; `the …` is repair 2's W5) ══
    ("K7a", SR, "⛔ `turn off allow all on my laptop and mac` names ONE computer “laptop and mac”",
     [("(?:own\\s+)?(?:(?!(?:and|or|nor|plus)\\b)[\\w'’-]+\\s+){{0,2}}?\"",
       "(?:own\\s+)?(?:[\\w'’-]+\\s+){{0,2}}?\"")]),

    # ═══ K8 — a quoted setting name is the setting ═════════════════════════════
    ("K8a", SR, "⛔⛔ `turn off “Allow all”` — the catch-all's own suggestion, quoted — gets "
     "the catch-all again",
     [('        lambda q: f" {q.group(0)[1:-1]} " if _is_setting_quote(q.group(0)) else q.group(0),\n',
       '        lambda q: q.group(0),\n')]),
    ("K8b", SR, "⛔ a message quoted whole — `“turn on Allow all”`, pasted back — gets the "
     "catch-all again",
     [('                   if not re.sub(r"[\\s.!?]", "", s[:q.start()] + s[q.end():])\n',
       '                   if False\n')]),
    ("K8c", SR, "⛔ the setting's quoted name is taken as the computer's — `turn off “Allow "
     "all” on “Studio PC”` looks for “Allow all”",
     [('        name = next((_cap(q).strip() for q in _QUOTED_RE.finditer(t)\n'
       '                     if not _is_setting_quote(q.group(0))), "")\n',
       '        name = _cap(_QUOTED_RE.search(t)).strip()\n')]),
    ("K8d", SR, "⛔⛔ a quoted setting name is blanked in the read-only arm — `turn off “Allow "
     "all” for my mac but keep it listed` HIDES the computer, unconfirmed",
     [('    _aa_src = _outside_quoted_names(_unquote_setting(low))\n',
       '    _aa_src = _outside_quoted_names(low)\n')]),

    # ═══ K13 — the join's name ═════════════════════════════════════════════════
    ("K13a", SR, "⛔ `join the Studio PC again` asks about “Studio PC again”",
     [('    obj = _AA_TAIL.sub("", _JOIN_TAIL.sub("", m.group("obj").strip())).strip(" ,")\n',
       '    obj = m.group("obj").strip()\n')]),
    ("K13b", SR, "⛔ `join the computer called Studio PC` asks about “called Studio PC”",
     [('    obj = _JOIN_CALLED.sub("", obj)\n', '')]),
    ("K13c", SR, "⛔ `join your Studio PC` / `join these Studio PCs` ask about one computer",
     [('r"my|our|mine|me|us|you|this|your|yours|his|her|hers|their|"\n'
       '                           r"theirs|its|these|those)\\b")',
       'r"my|our|mine|me|us|you|this)\\b")')]),
    ("K13d", SR, "⛔ `join the Studio PCs` — a plural — asks about one computer",
     [('    if "qqname" in obj or _AA_PLURAL.search(obj):\n', '    if "qqname" in obj:\n')]),
    ("K13e", SR, "⛔ `join the Studio PC for today` asks about “Studio PC for”",
     [('r"(?:\\s+(?:again|tonight|tomorrow|instead|too|later|for(?:\\s+today)?|"',
       'r"(?:\\s+(?:again|tonight|tomorrow|instead|too|later|for\\s+today|"')]),

    # ═══ K14 — the owner's Windows rule 2 ══════════════════════════════════════
    ("K14a", SR, "⛔ `are you connected to my mac mini app, it says it's offline` answers "
     "“✓ Signed in as …” alone",
     [('        rf"|\\s*,?\\s+(?:(?:but|and|yet|though|tho)\\s+)?(?:(?:it|that|this|which|the\\s+{_app_words})\\s+)?"\n'
       '        rf"(?:says?|said|shows?|showed|showing)\\b))", low)',
       '        rf"))", low)')]),
    ("K14b", SR, "⛔ any second clause makes it the computer — `am I signed in to the desktop "
     "app, and is it fast?` lists the computers",
     [('        rf"(?:says?|said|shows?|showed|showing)\\b))", low)',
       '        rf"(?:says?|said|shows?|showed|showing|is|are|it)\\b))", low)')]),

    # ═══ K18 — a question that mentions a login ════════════════════════════════
    ("K18a", SR, "⛔ `can people join my mac without a login?` starts a sign-in",
     [('        if re.search(rf"\\b{_SIGN_IN_ASK}\\b", low) and not _aa_login_q:\n',
       '        if re.search(rf"\\b{_SIGN_IN_ASK}\\b", low):\n')]),
    ("K18b", SR, "⛔ a trailing `?` is not a question — `people can join my mac without a "
     "login?` starts a sign-in",
     [('        _aa_login_q = (_aa_bare(t)[1] or re.match(\n',
       '        _aa_login_q = (False or re.match(\n')]),
    ("K18c", SR, "⛔ a polite request is a question — `will you sign me in and let anyone "
     "join my mac` never signs in",
     [('(?:(?:can|could|would|will)\\b(?!\\s+you\\b)|', '(?:(?:can|could|would|will)\\b|')]),

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
                print(f"  {mid:5} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:5} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:5} ⛔ HARNESS FAULT — {e}")
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
