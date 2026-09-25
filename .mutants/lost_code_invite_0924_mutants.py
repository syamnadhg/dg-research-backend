"""Mutation harness — a lost code gets its own answer; every public list says the chat's words (2026-09-24).

⛔⛔ WHAT THIS CODE DECIDES.
  L* — "I lost my access code" / "I need a new one" / "share my code" come from
       somebody whose computer ALREADY EXISTS. They get the owner-approved answer
       (reveal it in Account, Reset for a new one, or the screen of a computer
       still being set up) — never the set-up-a-computer line, and a question about
       ENTERING a code is not mistaken for a lost one.
  I* — every LIST of public computers says the chat invite's words ("They see your
       name."), and the email half ("or your email, if you haven't set one") is
       said where an email is sent: the ask's own confirmation, on both clients.
  K* — SKILL.md's row that sends a lost code to `do`.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT (see add_computer_line_0924_mutants.py for why).

  python .mutants/lost_code_invite_0924_mutants.py
  python .mutants/lost_code_invite_0924_mutants.py L1 I2
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
POLL = "agent/facade/skill/scripts/sr_attention_poll.py"
CLI = "agent/facade/cli.py"
SKILL = "agent/facade/skill/SKILL.md"

AGENT_SUITES = ("tests/test_add_computer_line_0924.py tests/test_empty_state_794.py "
                "tests/test_public_devices_792.py tests/test_chat_public_792.py")
SUITES = {f: (AGENT, AGENT_SUITES) for f in (SR, POLL, CLI, SKILL)}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ L — the lost-code answer ══════════════════════════════════════════════
    ("L1", SR, "⛔⛔ A LOST CODE FALLS TO THE CATCH-ALL AGAIN — the gap the assistant "
     "filled by improvising where a code lives",
     [("        return None, [_LOST_CODE_REPLY]", "        pass")]),
    ("L2", SR, "a question about ENTERING a code is answered as a lost one",
     [(r'            r"|give|share|sharing)\b", low) and not re.search(' + "\n"
       r'            r"\b(?:into|enter|entering|paste|pasting|type|typing|put|use|using)\b", low):',
       r'            r"|give|share|sharing)\b", low):')]),
    ("L3", SR, "the answer stops offering Reset, so somebody who needs a NEW code is "
     "told only where the old one was",
     [('"(you\'ll enter your PIN). For a new one, use Reset in Settings → "\n'
       '                    "Manage devices and we\'ll email it to you. If you were still "',
       '"(you\'ll enter your PIN). If you were still "')]),
    ("L4", SR, "⛔⛔ THE ANSWER SENDS AN EXISTING COMPUTER'S OWNER TO SET UP A NEW ONE — "
     "whose pairing step drops everybody it was shared with",
     [('_LOST_CODE_REPLY = ("If the computer\'s already on your account, open Account in the "',
       '_LOST_CODE_REPLY = (f"{_ADD_A_COMPUTER} If the computer\'s already on your account, '
       'open Account in the "')]),
    # ═══ I — the invite on every list, the email half at the ask ════════════════
    ("I1", POLL, "the sign-in note's public list carries the email half again, unlike "
     "every other list (owner: one wording)",
     [('            f"They see your name."\n        )',
       '            f"They see your name — or your email, if you have not set one."\n        )')]),
    ("I2", CLI, "the terminal's public list says 'Its owner decides' again",
     [('_PUBLIC_ASK_INVITE_T = ("     Once the request is accepted you can use that computer. "',
       '_PUBLIC_ASK_INVITE_T = ("     Its owner decides. Once the request is accepted you can '
       'use that computer. "')]),
    ("I3", CLI, "⛔ the terminal's ASK drops the email half — the one moment an email is "
     "actually sent, and now the only place the terminal says it",
     [('    print("     They see your name — or your email, if you have not set one.")',
       '    print("     They see your name.")')]),
    ("I4", SR, "⛔ the chat's ask confirmation drops the email half, where it is sent",
     [('        "They see your name — or your email, if you haven’t set one.",',
       '        "They see your name.",')]),
    # ═══ K — SKILL.md ══════════════════════════════════════════════════════════
    ("K1", SKILL, "the table loses the lost-code row, so the model guesses where a code "
     "lives before it ever runs `do`",
     [('| "I lost my access code", "I need a new access code"', '| "zzqq"')]),
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
