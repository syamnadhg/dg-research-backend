"""Mutation harness — the Mac fixes to the Windows sync (2026-09-26).

⛔⛔ WHAT THIS CODE DECIDES.
  C* — sr.py's code pattern and rule 1: a code with no digit (~1 in 11 access codes,
       and every connection code) is read, in the shapes no word takes; a pasted
       connection code reaches the bridge's check and never `login`; words shaped
       like a code are never paired.
  R* — sr.py rule 2: connected / logged in TO a computer lists the computers; a
       question about the account keeps the account answer, and so does one about
       the chat's app on a computer, in every spelling.
  D* — sr.py devices: every row says online or offline.
  S* — sr.py device-add: a connection code the bridge no longer knows is called one.
  A* — sr.py login: a session that ends mid-answer gets a sign-in link.
  P* — prefs.py: a colliding read or replace is retried.
  T* — conftest: the terminal client, too, is pointed at a port nobody listens on.

The lost-access-code reply's three facts are L5-L7 in lost_code_invite_0924.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  python .mutants/mac_fixes_0926_mutants.py
  python .mutants/mac_fixes_0926_mutants.py C4 R1 P2
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
PREFS = "agent/facade/prefs.py"
CONFTEST = "agent/tests/conftest.py"

SUITES = {
    SR: (AGENT, "tests/test_router_codes_and_computers_0926.py tests/test_connection_code_0925.py "
                "tests/test_login_answers_login_only_0925.py"),
    PREFS: (AGENT, "tests/test_prefs_windows_io_0926.py tests/test_prefs.py"),
    CONFTEST: (AGENT, "tests/test_prefs_windows_io_0926.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
ENV.pop("SUPER_AGENT_BRIDGE_PORT", None)   # T1 must see the port config froze at import

MUTANTS = [
    # ═══ C — codes with no digit (`_digitless_code`) ═══════════════════════════
    ("C1", SR, "⛔⛔ an access code with no digit and a vowel, pasted alone, is not read — "
     "~1 in 11 real codes reaches the catch-all",
     [("    if _NL_CAPS_CODE_RE.fullmatch(whole) and len(set(_nl_code_key(whole))) >= 5:\n"
       "        return whole\n", "")]),
    ("C2", SR, "⛔ a connection code in lower case, pasted alone, is not read",
     [('_NL_CONNECTION_CODE_RE = re.compile(rf"\\b({_CONN})\\b", re.I)',
       '_NL_CONNECTION_CODE_RE = re.compile(rf"\\b({_CONN})\\b")')]),
    ("C3", SR, "⛔ a sign-in phrase next to the code only counts in one case — 'wdjb-mjht "
     "please sign me in' and 'LOG ME IN WITH …' start a new sign-in",
     [('(?:to\\s+(?:sign|log)\\s?in|(?:sign|log)\\s+me\\s+in)\\b",\n    re.I)\n',
       '(?:to\\s+(?:sign|log)\\s?in|(?:sign|log)\\s+me\\s+in)\\b",\n    0)\n')]),
    ("C4", SR, "⛔⛔ THE REPORTED BUG: 'sign in with WDJB-MJHT' goes to `login`, whose new "
     "sign-in voids the page already open",
     [("    m = _NL_CODE_NEAR_RE.search(plain)\n    if m:\n        return m.group(1) or m.group(2)\n",
       "")]),
    ("C5", SR, "⛔⛔ a digitless code is read BEFORE the digit code — 'access code "
     "K7XQ-9B2M — not the connection code WDJB-MJHT' pairs the connection code",
     [("    code_m = _NL_CODE_RE.search(t)\n    if code_m:\n",
       "    _pre = _digitless_code(t, low)\n    if _pre:\n        return [\"device-add\", _pre], None\n"
       "    code_m = _NL_CODE_RE.search(t)\n    if code_m:\n")]),
    ("C6", SR, "⛔ a research request with a sign-in phrase and a code pairs it",
     [("    if _NL_RESEARCH_RE.match(t):\n        return None\n    if re.match(r\"^(?:\\W*)(?:status",
       "    if re.match(r\"^(?:\\W*)(?:status")]),
    ("C7", SR, "⛔⛔ a report that the sign-in is done ('I signed in with the code WDJB-MJHT') "
     "pairs the code instead of running login-done",
     [("    if _NL_SIGNED_IN_ALREADY_RE.search(low):                  # a report, not an ask\n"
       "        return None\n", "")]),
    ("C8", SR, "⛔ `add` without a machine noun pairs a code-shaped token ('add WDJB-MJHT to "
     "my notes')",
     [('            and re.search(rf"\\b(?:{_MACHINE_NOUNS})\\b", low)\n'
       '            and not re.search(r"\\b(?:public|',
       '            and not re.search(r"\\b(?:public|')]),
    ("C9", SR, "⛔ a publish request carrying a code-shaped token is paired instead of "
     "publishing",
     [('            and not re.search(r"\\b(?:public|findable|discoverable|ask|request|borrow|"\n'
       '                              r"use|switch)\\b", low)):',
       '            ):')]),
    ("C10", SR, "⛔⛔ a machine name in capitals is paired — 'add my Mac STARGATE back' "
     "(capitals need a dash on this path)",
     [('rf"\\b([{_ACCESS_LETTERS}]{{4}}[{_DASHES}][{_ACCESS_LETTERS}]{{4}})\\b",',
       'rf"\\b([{_ACCESS_LETTERS}]{{4}}[{_DASHES}]?[{_ACCESS_LETTERS}]{{4}})\\b",')]),
    ("C11", SR, "⛔ 'hmmmmmmm', 'zzzzzzzz' alone are paired (no four-different-letters rule)",
     [("    if (_NL_CONNECTION_CODE_RE.fullmatch(whole) and len(set(_nl_code_key(whole))) >= 4\n",
       "    if (_NL_CONNECTION_CODE_RE.fullmatch(whole) and len(set(_nl_code_key(whole))) >= 1\n")]),
    ("C12", SR, "⛔ two lower-case words of consonants alone ('psst hmmm') are paired",
     [('            and (" " not in whole or whole.isupper())):\n', "            ):\n")]),
    ("C13", SR, "⛔ 'HAHA-HAHA', 'YESS-SSSS' alone are paired (no five-different-letters rule; "
     "re-aimed 2026-09-26: without a dash they can no longer pair at all)",
     [("    if _NL_CAPS_CODE_RE.fullmatch(whole) and len(set(_nl_code_key(whole))) >= 5:\n",
       "    if _NL_CAPS_CODE_RE.fullmatch(whole) and len(set(_nl_code_key(whole))) >= 1:\n")]),
    ("C14", SR, "⛔ a code inside a QUOTED run title is paired — 'pause \"sign in with "
     "WDJB-MJHT\"'",
     [("    plain = _NL_QUOTED_RE.sub(\" \", t)\n", "    plain = t\n")]),
    ("C15", SR, "⛔ a question about a code pairs it — 'what is code KXMHWRTQ for?'",
     [("    if re.match(r\"^(?:\\W*)(?:status|state|check|show|list|progress|what|which|who|\"\n"
       "                r\"where|why|how|is|are|did|does|has|have)\\b\", low):\n        return None\n"
       "    if re.search(r\"\\b(?:support|logs|diagnostics)",
       "    if re.search(r\"\\b(?:support|logs|diagnostics)")]),
    ("C16", SR, "⛔ a support code in a send-logs message is paired as an access code",
     [('    if re.search(r"\\b(?:support|logs|diagnostics)\\b", low):   # not "log me in"\n'
       '        return None\n', "")]),
    ("C17", SR, "⛔⛔ 'code'/'pair' before an ORDINARY dashed word pairs it — 'the code "
     "tech-debt', 'pair hand-made gifts' (re-aimed 2026-09-26: undashed words need the "
     "dash now)",
     [('[{_ACCESS_LETTERS}]{{4}})\\b")\n_NL_SIGNED_IN_ALREADY_RE',
       '[{_ACCESS_LETTERS}]{{4}})\\b", re.I)\n_NL_SIGNED_IN_ALREADY_RE')]),
    ("C18", SR, "⛔ the access code's letters take an L, so hyphenated words in capitals "
     "('SELF-HELP') are paired",
     [('_ACCESS_LETTERS = "A-HJKMNP-Z"', '_ACCESS_LETTERS = "A-HJ-NP-Z"')]),
    ("C19", SR, "⛔⛔ an ordinary word alone in lower case ('whatever', 'database') is paired "
     "— the capitals-only guard",
     # ⚠ RE-ANCHORED 2026-09-26: the dash is required now (Windows review).
     [('_NL_CAPS_CODE_RE = re.compile(rf"\\b([{_ACCESS_LETTERS}]{{4}}[{_DASHES}][{_ACCESS_LETTERS}]{{4}})\\b")',
       '_NL_CAPS_CODE_RE = re.compile(rf"\\b([{_ACCESS_LETTERS}]{{4}}[{_DASHES}][{_ACCESS_LETTERS}]{{4}})\\b", re.I)')]),
    ("C25", SR, "⛔⛔ the dash turns optional again, so words in capitals — RESEARCH, "
     "REJECTED, WHATEVER — are paired (Windows review, 2026-09-26)",
     [('_NL_CAPS_CODE_RE = re.compile(rf"\\b([{_ACCESS_LETTERS}]{{4}}[{_DASHES}][{_ACCESS_LETTERS}]{{4}})\\b")',
       '_NL_CAPS_CODE_RE = re.compile(rf"\\b([{_ACCESS_LETTERS}]{{4}}[{_DASHES}]?[{_ACCESS_LETTERS}]{{4}})\\b")')]),
    ("C26", SR, "⛔ after 'code is', the dash turns optional again — 'MY CODE IS "
     "REJECTED' pairs REJECTED",
     [('    rf"\\b(?i:code)(?:\\s+(?i:is))?\\s*[:=]?\\s*([{_ACCESS_LETTERS}]{{4}}[{_DASHES}]"',
       '    rf"\\b(?i:code)(?:\\s+(?i:is))?\\s*[:=]?\\s*([{_ACCESS_LETTERS}]{{4}}[{_DASHES}]?"')]),
    ("C20", SR, "⛔ an en dash or a non-breaking hyphen between the halves — what phones "
     "substitute — is not read",
     [('_DASHES = "-‐‑‒–—―−"', '_DASHES = "-"')]),
    ("C21", SR, "⛔ 'login' AFTER a code-shaped pair counts as signing in — 'stop the HTTP "
     "SMTP login research' is paired",
     [('(?:to\\s+(?:sign|log)\\s?in|(?:sign|log)\\s+me\\s+in)\\b",\n    re.I)\n',
       '(?:to\\s+(?:sign|log)\\s?in|(?:sign|log)\\s*(?:me\\s+)?in)\\b",\n    re.I)\n')]),

    ("C22", SR, "⛔⛔ a sign-in message carrying the connection code in any other shape "
     "('WDJB-MJHT sign in', 'sign in again with …') starts a new sign-in again",
     [("        if _conn:\n            return [\"device-add\", _conn.group(1)], None\n", "")]),
    ("C23", SR, "⛔ the sign-in branch reads two acronyms split by a space as a code — 'log "
     "me in to the HTTP SMTP research' pairs 'HTTP SMTP'",
     [('rf"\\b([{_CONNECTION_LETTERS}]{{4}}(?:\\s*[{_DASHES}]\\s*)?"',
       'rf"\\b([{_CONNECTION_LETTERS}]{{4}}(?:\\s*[{_DASHES}]\\s*|\\s)?"')]),
    ("C24", SR, "⛔ 'pair STARGATE' — a machine's name — is paired (capitals after 'pair' "
     "need a dash)",
     [('    rf"|\\b(?i:pair)\\s+([{_ACCESS_LETTERS}]{{4}}[{_DASHES}][{_ACCESS_LETTERS}]{{4}})\\b")',
       '    rf"|\\b(?i:pair)\\s+([{_ACCESS_LETTERS}]{{4}}[{_DASHES}]?[{_ACCESS_LETTERS}]{{4}})\\b")')]),

    # ═══ R — connected TO a computer ═══════════════════════════════════════════
    ("R1", SR, "⛔⛔ THE REPORTED BUG: 'are you connected to my mac?' is answered with the "
     "account line alone",
     [("    if _to_a_computer:\n        return [\"devices\"], None\n",
       "    if False:\n        return [\"devices\"], None\n")]),
    ("R2", SR, "⛔⛔ the object need not be a computer — 'are you connected to my account?' "
     "and 'am I signed in with the right account?' list the computers",
     [('        rf"(?:{_MACHINE_NOUNS})\\b"\n        rf"(?!',
       '        rf"\\S"\n        rf"(?!')]),
    ("R8", SR, "⛔ a machine noun that names an ACCOUNT ('my laptop's Google account') "
     "lists the computers",
     # ⚠ RE-ANCHORED 2026-09-26: the lookahead now also excludes the app words;
     # and 2026-09-27, when they became `_app_words`, reached past model words.
     [("        rf\"(?!\\s*['’]s\\b|\\s+(?:account|email|google|gmail|login|profile)\\b\"\n"
       "        rf\"|(?:\\s+(?:{_MACHINE_NOUNS}|{_model_words}))*\\s+{_app_words}\\b\"\n"
       "        rf\"(?!\\s+(?:says?|said|shows?|showed|showing|is|are|was|keeps?|it|its|it['’]s)\\b))\", low)",
       "        rf\"\", low)")]),
    ("R9", SR, "⛔ 'am I signed in to the desktop APP?' lists the computers again — a "
     "sign-in question about this chat (Windows review, 2026-09-26)",
     [("|login|profile)\\b\"\n        rf\"|(?:\\s+(?:{_MACHINE_NOUNS}|{_model_words}))*\\s+{_app_words}\\b\"\n"
       "        rf\"(?!\\s+(?:says?|said|shows?|showed|showing|is|are|was|keeps?|it|its|it['’]s)\\b))\", low)",
       "|login|profile)\\b)\", low)")]),
    ("R15", SR, "⛔⛔ the lookahead reads one word past the machine noun again — 'am I "
     "signed in to the Mac desktop app?' lists the computers (Windows review r2)",
     [("|(?:\\s+(?:{_MACHINE_NOUNS}|{_model_words}))*\\s+{_app_words}\\b\"",
       "|\\s+{_app_words}\\b\"")]),
    ("R17", SR, "⛔⛔ an app word that opens the next clause declines the computer — 'are "
     "you connected to my mac mini app says its offline?' answers the account line alone",
     [("\"\n        rf\"(?!\\s+(?:says?|said|shows?|showed|showing|is|are|was|keeps?|it|its|it['’]s)\\b))\", low)",
       ")\", low)")]),
    ("R10", SR, "⛔⛔ the app question in another spelling misses again — 'am I logged "
     "into the mac app?' reaches the catch-all, '…into the Mac version?' prints the "
     "version (Windows review r2, 2026-09-27)",
     [("    if _to_its_app:\n        return [\"status-account\"], None\n",
       "    if False:\n        return [\"status-account\"], None\n")]),
    ("R11", SR, "⛔⛔ the app is asked before the computers — 'are you connected to the "
     "client pc?' and '…to my laptop cuz app says offline?' answer the account line "
     "alone, which reads as 'yes, connected' (the first cut of r2)",
     [("    if _to_a_computer:\n        return [\"devices\"], None\n"
       "    if _to_its_app:\n        return [\"status-account\"], None\n",
       "    if _to_its_app:\n        return [\"status-account\"], None\n"
       "    if _to_a_computer:\n        return [\"devices\"], None\n")]),
    ("R12", SR, "⛔ the app by another name is a computer again — 'the desktop "
     "application', 'the laptop program', 'the mac extension' list the computers",
     [("(?:apps?|applications?|programs?|software|extensions?|version|client|\"",
       "(?:apps?|version|client|\"")]),
    ("R14", SR, "⛔ any three words describe the app — 'are u connected to my imac via "
     "the app?' (a computer this router cannot name) and '…to my mac's wifi cuz app says "
     "offline?' answer the account line alone",
     [("(?!(?:the|a|an|my|your|our|his|her|its|their|this|that|which|where|on|in|at|\"\n"
       "        rf\"from|of|for|with|via|to|into|onto|by|through|thru|over|using|and|or|but|nor|so|\"\n"
       "        rf\"if|as|because|cuz|coz|cos|bc|since|while|when|tho|though|although|unless|until)\\b)\"",
       "\"")]),
    ("R16", SR, "⛔⛔ the app question is read across a machine noun — 'are u able to "
     "see which computers are logged into the app' answers the account line alone",
     [("_asker + rf\"(?:(?!\\b(?:{_MACHINE_NOUNS})\\b)[^.?!])*?\" + _to_it",
       "_asker + r\"[^.?!]*?\" + _to_it")]),
    ("R18", SR, "⛔ the app question stops at three words again — 'am I logged into the Mac "
     "mini M4 Pro version?' prints the VERSION",
     [("{{0,3}}?(?:(?:{_MACHINE_NOUNS}|{_model_words})\\s+)*{_app_words}\\b\", low)",
       "{{0,3}}?{_app_words}\\b\", low)")]),
    ("R13", SR, "⛔ 'are u' is not asked — 'are u signed in to the desktop app?' "
     "reaches the catch-all",
     [("(?:are (?:you|u|we)|am i|is it|is this|is super ?research)",
       "(?:are (?:you|we)|am i|is it|is this|is super ?research)")]),
    ("R3", SR, "⛔ 'signed in ON this computer' — a question about this chat's sign-in — "
     "lists the computers",
     [('(?:\\s+(?:to|into|with)|to)\\s+"', '(?:\\s+(?:to|into|with|on)|to)\\s+"')]),
    ("R5", SR, "⛔ the words before the machine noun may be a preposition again — 'am I "
     "signed in with google on this laptop?' lists the computers",
     [("        rf\"(?:(?!(?:on|in|at|from|of|for|with|to|account|email|app)\\b)[\\w'’-]+\\s+){{0,3}}?\"",
       "        rf\"(?:[\\w'’-]+\\s+){{0,3}}?\"")]),
    ("R6", SR, "⛔ a greeting first ('hey, are you connected to my Mac?') gets the account "
     "line alone",
     [('        rf"^\\W*(?:(?:hi|hey|hello|btw|wait|um|so|ok|okay|and)\\W+)*{_NL_LEAD_IN}"',
       '        rf"{_NL_LEAD_IN}"')]),
    ("R7", SR, "⛔ 'is it signed INTO the office PC?' gets the account line alone",
     [('(?:\\s+(?:to|into|with)|to)\\s+"', '\\s+(?:to|into|with)\\s+"')]),

    # ═══ S — the connection code the bridge no longer knows ════════════════════
    ("S1", SR, "⛔ a connection code the bridge no longer knows gets 'No computer is "
     "waiting for that code' again",
     [("            msg = _STALE_CONNECTION_CODE\n", "            pass\n")]),
    ("S2", SR, "⛔ …and only when typed with no dash or space — 'WDJB-MJHT' gets the claim "
     "route's sentence",
     [('    return re.fullmatch(rf"[{_CONNECTION_LETTERS}]{{8}}", _nl_code_key(tok), re.I) is not None',
       '    return re.fullmatch(rf"[{_CONNECTION_LETTERS}]{{8}}", tok, re.I) is not None')]),

    ("S3", SR, "⛔ signed out with the sign-in's own code, the ended sign-in is not said — "
     "only 'tell me to log you in'",
     [("            msg = _SIGN_IN_ENDED\n", "            pass\n")]),

    # ═══ D — the computers screen says online or offline ═══════════════════════
    ("D1", SR, "⛔⛔ a row never says online or offline — an offline Mac reads as connected",
     [('        lines.append(f"  {mark} {_dev_label(d)}  ({kind}{state}){presence}")',
       '        lines.append(f"  {mark} {_dev_label(d)}  ({kind}{state})")')]),

    # ═══ A — `login` believes the ack's 401 ═══════════════════════════════════════
    ("A1", SR, "⛔ 'log me in' as the session ends says 'You're already signed in' and "
     "sends no link — killed by 'log me in as the session ends starts a sign-in'",
     [("    acode, ack = _ack_signed_in(\"login\")\n    if acode == 401:\n"
       "        return None, {}  # it ended between the two reads — sign in afresh\n",
       "    acode, ack = _ack_signed_in(\"login\")\n")]),

    # ═══ P — prefs.json under Windows file locking ═════════════════════════════
    ("P1", PREFS, "⛔⛔ a colliding read or replace is tried once — a reader sees {} and a "
     "write is lost",
     [("_IO_RETRIES = 8", "_IO_RETRIES = 1")]),

    # ═══ T — the tests never reach a real bridge ═══════════════════════════════
    ("T1", CONFTEST, "⛔⛔ the terminal client is left on 9876 — a developer's live bridge",
     [('    monkeypatch.setattr(_config, "BRIDGE_PORT", _nobody_listens_port)\n', "")]),
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
