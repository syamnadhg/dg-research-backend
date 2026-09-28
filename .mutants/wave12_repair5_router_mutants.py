"""Mutation harness — wave 12 repair 5, the last repair to the chat's message
reading before the owner's E2E (2026-09-28).

⛔⛔ WHAT THIS CODE DECIDES. Whether a chat message starts a paid research run, pairs
an access code, asks a stranger for their computer, stops a run, switches Allow all
off, starts a sign-in — or changes nothing. The final focused review found seven
readings repair 4 over-reached or left half done (agent/tests/
test_allow_all_repair5_0928.py names them); each mutant below brings ONE of them
back, and the test that kills it EXECUTES `sr._nl_resolve` or `sr.py do` with the
bridge stubbed.

  R1*  a research topic: `permission` only after somebody who would join; people
       joining my/our/this <machine> only when the machine word ends there
  R2*  a code after an ask verb: every ask verb, a greeting, no dash with a digit,
       read outside the join gate; an unquoted code is never asked for
  R3*  somebody's computer is no ask (and the older capture stands down); a set
       still gets `one owner at a time`; the older capture's name drops its tail
  R4   what the app says counts for the computer only when it is about reaching it
  R5*  a quoted setting name ending the message after a run verb is a run's title
  R6*  `each request` is `each person`'s twin; `can u` is `can you`
  R7*  a research topic's quote comes off only with its partner

Older mutants whose anchors moved are RE-AIMED in their own harnesses with a dated
note (repair4 K2a K2b K3c K8a K13c K13d K14a K14b K18c, repair1 F14,
allow_all_agent R7 R15, mac_fixes R8 R9 R17).

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  python .mutants/wave12_repair5_router_mutants.py
  python .mutants/wave12_repair5_router_mutants.py R2a R5b
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
    SR: (AGENT, "tests/test_allow_all_repair5_0928.py tests/test_allow_all_repair4_0927.py "
                "tests/test_allow_all_repair3_0927.py tests/test_allow_all_whole_message_0927.py "
                "tests/test_allow_all_router_repair_0927.py tests/test_allow_all_router_0926.py "
                "tests/test_chat_public_792.py tests/test_chat_owner_793.py "
                "tests/test_empty_state_794.py tests/test_router_codes_and_computers_0926.py "
                "tests/test_bulk_gate_0910.py tests/test_public_devices_792.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

_LOOKAHEAD = ('      r"(?=\\s*(?:$|[.?!,;:]|without\\b|at\\s+once\\b|instantly\\b|straight\\s+away\\b|'
              'right\\s+away\\b))",\n')
_REACH = ('        rf"(?:says?|said|shows?|showed|showing)\\s+(?:that\\s+)?(?:(?:it[\'’]s|it\\s+is|it)\\s+)?'
          '(?:as\\s+)?"\n'
          '        rf"(?:offline|online|disconnected|not\\s+connected|unreachable|asleep)\\b))", low)')

MUTANTS = [
    # ═══ R1 — a research topic about people and computers ══════════════════════
    ("R1a", SR, "⛔⛔ a bare `without my permission` beside the person's computer is their "
     "Allow all — `research why my mac installs updates without my permission` never starts",
     [('    + r"|\\bwithout\\s+(?:my\\s+)?approval\\b"\n'
       '    + rf"|\\b{_AA_WHO}\\b[^.?!]{{0,40}}\\bwithout\\s+(?:my\\s+)?permission\\b"\n',
       '    + r"|\\bwithout\\s+(?:my\\s+)?(?:approval|permission)\\b"\n'
       '    + rf"|\\b{_AA_WHO}\\b[^.?!]{{0,40}}\\bwithout\\s+(?:my\\s+)?permission\\b"\n')]),
    ("R1b", SR, "⛔ somebody using the person's computer without their permission is a paid "
     "run — `research why people use my mac without my permission` starts one",
     [('    + rf"|\\b{_AA_WHO}\\b[^.?!]{{0,40}}\\bwithout\\s+(?:my\\s+)?permission\\b"\n',
       '    + rf"|\\bNEVER_R1B\\b"\n')]),
    ("R1c", SR, "⛔⛔ a machine word that opens a compound is the person's computer — `research "
     "why people join this computer science program` never starts",
     [(_LOOKAHEAD, '      r"",\n')]),
    ("R1d", SR, "⛔ a possessive machine word is the person's computer — `research how people "
     "join my mac's wifi network` never starts",
     [(_LOOKAHEAD, _LOOKAHEAD.replace("(?:$|", "(?:$|['’]s\\b|"))]),
    ("R1e", SR, "⛔ a model word after the machine hides it — `research why strangers join my "
     "mac mini` starts a paid run about the person's own computer",
     [('(?:[\\w\'’-]+\\s+){{0,2}}?(?:{_MACHINE_NOUNS})\\b(?:\\s+{_MODEL_WORDS})*"\n',
       '(?:[\\w\'’-]+\\s+){{0,2}}?(?:{_MACHINE_NOUNS})\\b"\n')]),

    # ═══ R2 — a code after an ask verb ═════════════════════════════════════════
    ("R2a", SR, "⛔⛔ an unquoted code in a question raises the ask confirm — `can I borrow "
     "K7XQ-9B2M?`; its yes posts the code as a device id (H17)",
     [('        if _is_ask_code(_ask_obj) and re.search(\n', '        if False and re.search(\n')]),
    ("R2b", SR, "⛔ a QUOTED code is refused too — `borrow “K7XQ-9B2M”`, a name, gets the "
     "catch-all",
     [('                _outside_quoted_names(t)):\n            return None, [_NL_CATCH_ALL]\n',
       '                t):\n            return None, [_NL_CATCH_ALL]\n')]),
    ("R2c", SR, "⛔⛔ `ask for access to K7XQ-9B2M` / `request K7XQ-9B2M` / `ask to borrow …` / "
     "`apply for …` never pair (repair 4's six verbs)",
     [('_ASK_CODE_WHOLE = re.compile(r"(?:let\\s+me\\s+)?(?:join|ask\\s+(?:to\\s+(?:join|use|borrow)|"\n'
       '                             r"for(?:\\s+access\\s+to)?)|request(?:\\s+access\\s+to)?|apply\\s+for|"\n'
       '                             r"borrow)\\s+(?P<code>\\S+)")\n',
       '_ASK_CODE_WHOLE = re.compile(r"(?:let\\s+me\\s+)?(?:join|ask\\s+(?:to\\s+(?:join|use)|for)|"\n'
       '                             r"request\\s+access\\s+to|borrow)\\s+(?P<code>\\S+)")\n')]),
    ("R2d", SR, "⛔ a greeting in front stops the pairing — `Hi! Borrow K7XQ-9B2M`",
     [('    t = _ASK_CODE_HEAD.sub("", " ".join((text or "").split()))\n',
       '    t = " ".join((text or "").split())\n')]),
    ("R2e", SR, "⛔ the code is read only inside the join gate — `join K7XQ–9B2M` (a phone's "
     "en dash) never pairs",
     [('    _ask_code = _asked_code(t)\n    _om = None if _join_not_one else (\n',
       '    _ask_code = ""\n    _om = None if _join_not_one else (\n'),
      ('        _ask_obj = _strip_leading_noun(_ask_obj)\n',
       '        _ask_code = _asked_code(t)\n        _ask_obj = _strip_leading_noun(_ask_obj)\n')]),
    ("R2f", SR, "⛔ a digit code without its dash is not a code — `join YGXU7WH2` never pairs "
     "and `borrow YGXU7WH2` asks for it as a computer",
     [('                             rf"|(?=\\D*\\d)[2-9{_ACCESS_LETTERS}]{{8}}")\n',
       '                             rf"")\n')]),
    ("R2g", SR, "⛔ eight capitals are a code — `borrow FEEDBACK` pairs a word",
     [('                             rf"|(?=\\D*\\d)[2-9{_ACCESS_LETTERS}]{{8}}")\n',
       '                             rf"|[2-9{_ACCESS_LETTERS}]{{8}}")\n')]),

    # ═══ R3 — somebody's computer; a set; the older capture's tail ═════════════
    ("R3a", SR, "⛔⛔ the older capture ignores the join's refusal — `borrow her laptop now` "
     "asks about a computer again",
     [('    _om = None if _join_not_one else (\n', '    _om = None if False else (\n')]),
    ("R3b", SR, "⛔⛔ the join's refusal of somebody's computer is not signalled — `borrow her "
     "laptop now` asks about a computer again",
     [('    if _JOIN_SOMEBODYS.search(obj):\n        return None\n',
       '    if _JOIN_SOMEBODYS.search(obj):\n        return ""\n')]),
    ("R3c", SR, "⛔ a set's possessive silences its refusal — `request access to all their "
     "computers` shows the public list instead of `one owner at a time`",
     [('    if _AA_PLURAL.search(obj):             # a set: the older capture refuses it by name\n'
       '        return ""\n    if _JOIN_SOMEBODYS.search(obj):\n        return None\n',
       '    if _JOIN_SOMEBODYS.search(obj):\n        return None\n'
       '    if _AA_PLURAL.search(obj):             # a set: the older capture refuses it by name\n'
       '        return ""\n')]),
    ("R3d", SR, "⛔ the older capture keeps its tail — `ask for the Studio PC now` asks about "
     "“Studio PC now”",
     [('            _ask_obj = _AA_TAIL.sub("", re.sub(_JOIN_TAIL.pattern, "", _ask_obj,\n'
       '                                                flags=re.I)).strip(" ,")\n',
       '            pass\n')]),
    ("R3e", SR, "⛔ the older capture drops only the thanks — `ask for the Studio PC again` asks "
     "about “Studio PC again”",
     [('            _ask_obj = _AA_TAIL.sub("", re.sub(_JOIN_TAIL.pattern, "", _ask_obj,\n'
       '                                                flags=re.I)).strip(" ,")\n',
       '            _ask_obj = _AA_TAIL.sub("", _ask_obj).strip(" ,")\n')]),

    # ═══ R4 — what the app says ════════════════════════════════════════════════
    ("R4", SR, "⛔ anything the app says after a comma is about the computer — `am I logged "
     "into the mac app, it says I need to log in` lists the computers",
     [(_REACH, '        rf"(?:says?|said|shows?|showed|showing)\\b))", low)')]),

    # ═══ R5 — a quoted setting name as a run's title ═══════════════════════════
    ("R5a", SR, "⛔⛔ `stop “auto-approve”` switches Allow all OFF, unconfirmed, and the run "
     "keeps going",
     [('                   if _is_setting_quote(q.group(0)) and not _is_run_title(q.string, q)\n',
       '                   if _is_setting_quote(q.group(0))\n')]),
    ("R5b", SR, "⛔ a run verb anywhere before the quote makes it a title — `stop “Allow all” "
     "on my mac` asks to stop a run",
     [('    return bool(_RUN_TITLE_BEFORE.search(text[:q.start()])\n'
       '                and not _AA_TAIL.sub("", text[q.end():].rstrip(" .!?")).strip(" ,.!?"))\n',
       '    return bool(_RUN_TITLE_BEFORE.search(text[:q.start()]))\n')]),
    ("R5c", SR, "⛔ a thank-you after the title makes it the setting — `stop “auto-approve” "
     "please` switches Allow all OFF",
     [('                and not _AA_TAIL.sub("", text[q.end():].rstrip(" .!?")).strip(" ,.!?"))\n',
       '                and not text[q.end():].rstrip(" .!?").strip(" ,.!?"))\n')]),
    ("R5d", SR, "⛔ a run's artefact is no run verb — `status of “allow all”` lists the "
     "computers",
     [('    r"|(?:status|progress|podcasts?|audio|videos?|reports?|briefs?|links?|"\n'
       '    r"skip\\s+(?:the\\s+)?[\\w\'’-]+)\\s+(?:of|for|on|from|in))(?:\\s+the)?\\s*$", re.I)\n',
       '    r")(?:\\s+the)?\\s*$", re.I)\n')]),

    # ═══ R6 — `each request`; `can u` ══════════════════════════════════════════
    ("R6a", SR, "⛔ `approve each request again` changes nothing",
     [('            r"|approve\\s+(?:people|each\\s+person|each\\s+request)(?:{A}{T}|{T}{A})"\n',
       '            r"|approve\\s+(?:people|each\\s+person)(?:{A}{T}|{T}{A})"\n')]),
    ("R6b", SR, "⛔ `go back to approving each request` changes nothing",
     [('    ("off", r"(?:go\\s+back\\s+to\\s+approving\\s+(?:people|each\\s+person|each\\s+request)'
       '{A}?{T}{A}?"\n',
       '    ("off", r"(?:go\\s+back\\s+to\\s+approving\\s+(?:people|each\\s+person){A}?{T}{A}?"\n')]),
    ("R6c", SR, "⛔ `can u sign me in and turn off allow all` never signs in",
     [('(?:(?:can|could|would|will)\\b(?!\\s+(?:you|u)\\b)|', '(?:(?:can|could|would|will)\\b(?!\\s+you\\b)|')]),
    ("R6d", SR, "⛔ `can u turn off allow all?` is a question, and nothing changes",
     [('                      r"|(?P<you>(?:can|could|would|will)\\s+(?:you|u)\\b)[\\s,]*(?:please\\b[\\s,]*)?"\n',
       '                      r"|(?P<you>(?:can|could|would|will)\\s+you\\b)[\\s,]*(?:please\\b[\\s,]*)?"\n')]),

    # ═══ R7 — a topic's quotes ═════════════════════════════════════════════════
    ("R7a", SR, "⛔⛔ the quotes come off one character at a time — `research EV batteries on "
     "my mac “Allow All Lab”` stores its title with one quote",
     [('        topic = _trim_topic_quotes(re.sub(r"[?.!]+$", "", rm.group(1)).strip())\n',
       '        topic = re.sub(r"[?.!]+$", "", rm.group(1)).strip().strip("\\"“”\'‘’")\n')]),
    ("R7b", SR, "⛔ nested quotes are not counted — a topic quoted whole around a quoted name "
     "keeps its outer quotes",
     [('        depth = 0\n        for j in range(i, len(s)):\n',
       '        return s.find("”", i + 1)\n        for j in range(i, len(s)):\n')]),
    ("R7c", SR, "⛔ a straight quote's partner is not counted — `research \"tesla\" and \"ford\"` "
     "loses its last quote",
     [('            return s[:-1].count(\'"\') % 2 == 1\n', '            return False\n')]),
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
