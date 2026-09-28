"""Mutation harness — wave 12 repair 3, the chat's Allow-all handling stripped to
the bare minimum (2026-09-27).

⛔⛔ WHAT THIS CODE DECIDES. Whether a chat message switches Allow all (off at once,
on after a confirm), asks a stranger for their computer, pairs a code, starts a
paid research run — or changes nothing. Round 3 of cross-verify found repair 2's
own additions misrouting: its reason tail let a JOINER raise the confirm that opens
their own computer (H3), and its hand-off to the hide ran an unconfirmed hide on
`…but keep it listed` (H1). Both are gone; what is left is one rule per mutant
below, and the test that kills it EXECUTES `sr._nl_resolve` or `sr.py do` with the
bridge stubbed (agent/tests/test_allow_all_repair3_0927.py).

  A*   R1 — the subject: model words after the machine noun, and the one list
  B*   R1 — what may follow a command: time words; no reason
  C*   R2 — the arm OWNS every message with Allow-all words (no hide, no exemption)
  D*   R2 — a research verb: research, unless it is the person's own Allow all
  E*   R3 — the whole-message join; a code after any ask verb
  F*   the words: the hide picker's example (H16), the join reply (H21)
  K*   SKILL.md

⭐ The rules repair 2 already measured keep their mutants, RE-AIMED where their
anchors moved (wave12_repair2_router_mutants.py M1/M6/M7/M8/M18/M19/J3/W2/W7,
wave12_repair1_router_mutants.py F5/F8a/F8c/F11/F12a/F19e/S4/S7,
wave12_allow_all_agent_mutants.py R1/R6/R12/R14/R15/R16/R17). Nothing here repeats
one of those; the machinery repair 3 removed has its mutants RETIRED there with a
dated note.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  python .mutants/wave12_repair3_router_mutants.py
  python .mutants/wave12_repair3_router_mutants.py A1 C1 K1
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
    # ⛔ + the repair-4 pins (2026-09-27): the re-described E4 is measured there too.
    SR: (AGENT, "tests/test_allow_all_repair3_0927.py tests/test_allow_all_whole_message_0927.py "
                "tests/test_allow_all_router_repair_0927.py tests/test_allow_all_router_0926.py "
                "tests/test_chat_public_792.py tests/test_chat_owner_793.py "
                "tests/test_empty_state_794.py tests/test_router_codes_and_computers_0926.py "
                "tests/test_allow_all_repair4_0927.py"),
    SKILL: (AGENT, "tests/test_allow_all_repair3_0927.py tests/test_allow_all_whole_message_0927.py "
                   "tests/test_chat_public_792.py tests/test_chat_owner_793.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ A — the subject (H6) ════════════════════════════════════════════════
    ("A1", SR, "⛔⛔ H6: the subject ends on the machine noun — `turn off allow all for my Mac "
     "mini` changes nothing and strangers keep joining",
     [('                rf"(?:\\s+{_MODEL_WORDS})*"\n                rf"|the\\s+',
       '                rf"|the\\s+')]),
    ("A2", SR, "⛔ H6: a named computer loses its model words — `turn off allow all on the office "
     "Mac mini` is not a command",
     [('{_MACHINE_SINGULAR}(?:\\s+{_MODEL_WORDS})*"\n                rf"|it|that)")',
       '{_MACHINE_SINGULAR}"\n                rf"|it|that)")')]),
    ("A3", SR, "⛔⛔ H6: the model words are read as a NAME — `turn off allow all for my Mac mini` "
     "looks for a computer called “Mac mini” instead of the picker, and on an account whose "
     "one computer is “My Mac” nothing is written",
     [('        if not _is_bare_machine_noun(re.sub(rf"(?:\\s+{_MODEL_WORDS})+$", "", words)):\n',
       '        if not _is_bare_machine_noun(words):\n')]),
    ("A4", SR, "⛔ the two model-word lists drift apart — the sign-in reader (9ac9abf) loses "
     "“the MacBook Pro app”",
     [('    _model_words = _MODEL_WORDS\n', '    _model_words = r"(?:NEVER_A4)"\n')]),

    # ═══ B — what may follow a command (H6, H14, H3) ═════════════════════════
    ("B1", SR, "⛔ H6: `turn off allow all for now` is not a command",
     [('                      r"for\\s+now|today|for\\s+me|at\\s+once|instantly|right\\s+away|"',
       '                      r"today|for\\s+me|at\\s+once|instantly|right\\s+away|"')]),
    ("B2", SR, "⛔ H14: `join the Studio PC today` asks about “Studio PC today”",
     [('                      r"for\\s+now|today|for\\s+me|at\\s+once|instantly|right\\s+away|"',
       '                      r"for\\s+now|for\\s+me|at\\s+once|instantly|right\\s+away|"')]),
    ("B3", SR, "⛔ H14: `join the Studio PC at once` asks about “Studio PC at once”",
     [('                      r"for\\s+now|today|for\\s+me|at\\s+once|instantly|right\\s+away|"',
       '                      r"for\\s+now|today|for\\s+me|"')]),
    ("B4", SR, "⛔⛔ H3 BROUGHT BACK: a reason after a command is read past — `turn on allow all so "
     "I can join the Studio PC` (a JOINER) raises the confirm that opens their OWN computer",
     [('    return _AA_TAIL.sub("", s).strip(" ,"), question and not polite\n',
       '    return re.sub(r"\\s*,?\\s+(?:so|because|since)\\b.*$", "", _AA_TAIL.sub("", s))'
       '.strip(" ,"), question and not polite\n')]),

    # ═══ C — the arm owns every message with Allow-all words (H1, H4, H5) ═════
    ("C1", SR, "⛔⛔ H1 BROUGHT BACK: a message with hide words falls to the visibility clause — "
     "`turn off allow all on my mac but keep it listed` HIDES the computer, unconfirmed",
     # ⭐ RE-AIMED 2026-09-28 (last check): the gate carries `and not _aa_runctl`.
     [('    if _AA_MENTION.search(_aa_src) and not _aa_runctl:\n',
       '    if _AA_MENTION.search(_aa_src) and not _aa_runctl and not _hiding_kw:\n')]),
    ("C2", SR, "⛔⛔ H4/H5 BROUGHT BACK: a run control, an artefact or an unlink beside the words "
     "keeps its own route — `forget it, go back to approving people` raises the nameless "
     "approve, `pause the Mars run when anyone can join` PAUSES",
     # ⭐ RE-AIMED 2026-09-28 (last check): the gate carries `and not _aa_runctl`.
     [('    if _AA_MENTION.search(_aa_src) and not _aa_runctl:\n',
       '    if _AA_MENTION.search(_aa_src) and not _aa_runctl and not (_unlink_kw or _control_kw or _artefact_kw):\n')]),
    ("C3", SR, "⛔ H7: `ask for` is a joiner's verb again — the owner's `ask for approval before "
     "anyone can join my mac` gets the list of strangers' computers",
     [('_AA_JOINER = re.compile(r"\\b(?:join|borrow|ask\\s+to\\s+(?:use|join)|request\\s+access)\\b"',
       '_AA_JOINER = re.compile(r"\\b(?:join|borrow|ask\\s+(?:to\\s+(?:use|join)|for)|request\\s+access)\\b"')]),

    # ═══ D — a research verb (H13) ════════════════════════════════════════════
    ("D1", SR, "⛔⛔ H13: `investigate why my mac won't let anyone join` starts a PAID run about "
     "the person's own setting",
     [('        if any(re.search(rf"{_own_near}[^.?!,;]{{0,20}}$", _aa_topic[:m.start()])\n',
       '        if False and any(re.search(rf"{_own_near}[^.?!,;]{{0,20}}$", _aa_topic[:m.start()])\n')]),
    ("D2", SR, "⛔ H13 overshoots: no own computer is needed — `research why companies let anyone "
     "join their Slack`, a real topic, is refused",
     [('        if any(re.search(rf"{_own_near}[^.?!,;]{{0,20}}$", _aa_topic[:m.start()])\n',
       '        if any(True or re.search(rf"{_own_near}[^.?!,;]{{0,20}}$", _aa_topic[:m.start()])\n')]),
    ("D3", SR, "⛔ H13 overshoots: the person's computer anywhere in the topic counts — `research "
     "how to let anyone join a Slack workspace from my laptop` is refused",
     [('        if any(re.search(rf"{_own_near}[^.?!,;]{{0,20}}$", _aa_topic[:m.start()])\n'
       '               or re.match(rf"[^.?!,;]{{0,20}}?{_own_near}", _aa_topic[m.end():])\n',
       '        if any(re.search(rf"{_own_near}[^.?!,;]*$", _aa_topic[:m.start()])\n'
       '               or re.match(rf"[^.?!,;]*?{_own_near}", _aa_topic[m.end():])\n')]),

    # ═══ E — the whole-message join; a code after any ask verb (H7, H14, H17) ══
    ("E1", SR, "⛔ `let me join the Studio PC` / `please let me join K7XQ-9B2M` are not asks",
     [('    r"(?:let\\s+me\\s+)?(?:join|ask\\s+to\\s+(?:join|use)|request\\s+access\\s+to|borrow)\\s+"',
       '    r"(?:join|ask\\s+to\\s+(?:join|use)|request\\s+access\\s+to|borrow)\\s+"')]),
    ("E2", SR, "⛔ a question is an ask — `join the Studio PC?` raises the confirm whose yes can "
     "join at once",
     [('    m = None if question else _JOIN_WHOLE.fullmatch(s)\n', '    m = _JOIN_WHOLE.fullmatch(s)\n')]),
    ("E3", SR, "⛔ a quoted name after a whole-message join is no computer — `join “DG shared”` "
     "asks nothing",
     [('        or (_join_obj and _SET_QUOTED_SPAN.fullmatch(_join_obj)))',
       '        )')]),
    # ⛔ E4 RE-DESCRIBED 2026-09-27 (wave 12 repair 4, cross-verify K3): `borrow` is a
    # whole-message join verb too, so the only ask verb this gate drops is `ask for`
    # — the rows that kill it are the `ask for <code>` ones. Same anchor.
    ("E4", SR, "⛔⛔ H17: a code after `ask for` is not read — `ask for K7XQ-9B2M` asks the "
     "owner of a computer called “K7XQ-9B2M” and never pairs",
     [('    if _ask_code:\n        return ["device-add", _ask_code], None\n',
       '    if _ask_code and _join_obj:\n        return ["device-add", _ask_code], None\n')]),
    ("E5", SR, "⛔ the code is read AFTER the machine word comes off — `request access to "
     "computer LABPC001` PAIRS a machine whose id looks like a code",
     [('        _ask_obj = _strip_leading_noun(_ask_obj)\n',
       '        _ask_obj = _strip_leading_noun(_ask_obj)\n'
       '        _ask_code = _ask_obj if _NL_CODE_RE.fullmatch(_ask_obj) else _ask_code\n')]),
    ("E6", SR, "⛔ H20: the machine word stays in the joined name — `join computer Studio PC` "
     "asks about “computer Studio PC”, which no row is called",
     [('        _ask_obj = _strip_leading_noun(_ask_obj)\n', '        pass\n')]),

    # ═══ F — the words ════════════════════════════════════════════════════════
    ("F1", SR, "⛔ H16: the hide picker's example is the PUBLISH — said back, the publish confirm",
     [('    return _set_device_visibility(args, payload, f"make “{{name}}” {value}")',
       '    return _set_device_visibility(args, payload, "make “{name}” public")')]),
    ("F2", SR, "⛔ H21: a join that keeps research on the person's own computer never says so, "
     "nor how to move it",
     [('        lines.append(f"Your research stays on your current computer — say “use {name}” "\n'
       '                     f"to run it there.")\n',
       '        pass\n')]),

    # ═══ K — SKILL.md ═════════════════════════════════════════════════════════
    ("K1", SKILL, "⛔⛔ the OFF row tells the model `do` takes a reason — the tail H3 measured",
     [('and nothing else, not even a reason;', 'and one "so …" reason;')]),
    ("K2", SKILL, "⛔ the ask row stops saying `do` asks only on a whole message",
     [(' `sr.py do` asks only when the WHOLE message is the ask ("join the Studio PC", "join '
       '“DG shared” now"); "my friend wants to join…" or "I tried to join… but it failed" asks '
       'nothing |', ' |')]),
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
