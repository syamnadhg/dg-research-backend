"""Mutation harness — one "Add a computer" line, install link first, everywhere (2026-09-24).

⛔⛔ WHAT THIS CODE DECIDES. Whether a person with no Research Computer is told the
one true way to get one — the install page — in the sentence a relaying model keeps
anyway, or is left with a trailing aside it drops. Measured on the owner's Telegram
(2026-09-19..24, gpt-5.6-luna): the `devices` screen lost the link in 3 of 3 relays;
twice the model filled the gap itself, once with `superresearch --pair` and once with
"the 8-character access code from the Super Research app" — neither is true.

  A* — the chat client (sr.py): the shared line, the screen's order, the relay rule,
       the populated list, the sign-in line, the updates announce, the router.
  W* — the watcher, which reaches the person word for word.
  T* — the terminal. B* — the bridge refusal. K* — SKILL.md.
  R* — the backend's own pairing screen (research.py), where the code is first shown.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT. These files are checked out CRLF on Windows (autocrlf); a text
restore would flip every line ending and the tree would not come back clean.

  python .mutants/add_computer_line_0924_mutants.py
  python .mutants/add_computer_line_0924_mutants.py A1 R3
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
BRIDGE = "agent/facade/bridge.py"
SKILL = "agent/facade/skill/SKILL.md"
RESEARCH = "research.py"

AGENT_SUITES = ("tests/test_add_computer_line_0924.py tests/test_empty_state_794.py "
                "tests/test_empty_state_relay_0922.py tests/test_skill_description_0921.py "
                "tests/test_bridge_device.py tests/test_sr_stream.py")
ROOT_SUITES = "tests/test_pairing_screen_handover_0924.py"
# (cwd, suites) per mutated file — the agent's tests run from agent/, the backend's
# from the repo root, and each tree has its own conftest.
SUITES = {f: (AGENT, AGENT_SUITES) for f in (SR, POLL, CLI, BRIDGE, SKILL)}
SUITES[RESEARCH] = (ROOT, ROOT_SUITES)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

_ADD_TAIL = ('    lines.append(_ADD_A_COMPUTER)\n    pub = _public_offer_lines()\n'
             '    if pub:\n        lines.append("")\n        lines += pub\n    return lines')

MUTANTS = [
    # ═══ A — the chat client ═══════════════════════════════════════════════════
    ("A1", SR, "⛔⛔ THE LINK LEAVES THE ADD LINE — the sentence a relay keeps no "
     "longer carries the one route a person with no computer has",
     [('f"Add a computer: set one up at {_INSTALL_PAGE_URL}, then send "',
       'f"Add a computer: send "')]),
    ("A2", SR, "⛔⛔ THE ADD LINE GOES BACK BELOW THE PUBLIC LIST — a tail again, which "
     "is exactly what a condensing model drops",
     [(_ADD_TAIL,
       '    pub = _public_offer_lines()\n    if pub:\n        lines += pub\n'
       '        lines.append("")\n    lines.append(_ADD_A_COMPUTER)\n    return lines')]),
    ("A3", SR, "⛔ THE RETIRED TRAILING PARAGRAPH RETURNS, with the 'It gives you' line "
     "whose 'It' reads as the web page handing out the code",
     [(_ADD_TAIL,
       _ADD_TAIL.replace("    return lines",
                         '    lines += ["", "Don\'t have your own Research Computer yet? '
                         'Set one up: https://superresearch.io/install", "It gives you an '
                         '8-char access code — send it to me and I’ll connect it."]\n'
                         '    return lines'))]),
    ("A4", SR, "⛔ THE RELAY RULE LOSES THE URL — it can no longer put back a link the "
     "model dropped",
     [('    f"{_INSTALL_PAGE_URL} inside the “Add a computer” sentence and keep the "',
       '    "the link inside the “Add a computer” sentence and keep the "')]),
    ("A5", SR, "the relay rule stops forbidding the invented origin — the exact sentence "
     "the 09-24 relay made up is allowed again",
     [('never say it comes from the "\n    "app, and add',
       'say it comes from the "\n    "app, and add')]),
    ("A6", SR, "the populated device list loses the add line, so somebody whose only "
     "computer is shared asks 'add a device' and gets no link",
     [('    lines.append(_ADD_A_COMPUTER)\n'
       '    lines.append("You can remove or switch computers anytime — just ask.")',
       '    lines.append("You can remove or switch computers anytime — just ask.")')]),
    ("A7", SR, "⛔ THE FIRST LINE AFTER SIGN-IN on an account with no computer loses the "
     "link — the commonest first contact",
     [('    return (f"✓ Connected as {who}. {_ADD_A_COMPUTER} Or ask me for a public "',
       '    return (f"✓ Connected as {who}. Or ask me for a public "')]),
    ("A8", SR, "⛔ 'install / set up Super Research' goes back to installing the backend on "
     "the chat's own host (owner: those phrasings get the page)",
     [('            return None, [_NL_CONFIRMS["install"]]\n'
       '        return None, [_ADD_A_COMPUTER]',
       '            return None, [_NL_CONFIRMS["install"]]\n'
       '        return None, [_NL_CONFIRMS["install"]]')]),
    ("A9", SR, "the explicit-machine check is untied from the verb, so 'I'm new here, how "
     "do I set up super research' reaches the install-here confirm",
     [(r'r"\b(?:install|set ?up|host)\b[^.?!,]*"', r'r".*"')]),
    ("A10", SR, "the web app's own paste-to-agent message (skills.md) is answered with the "
     "add-a-computer line instead of the account check",
     [(r'        if re.search(r"\bskills?\.md\b|\b(?:skill|agent|bridge)\b", low):' + "\n"
       '            return ["status-account"], None\n', "")]),
    ("A11", SR, "⛔ 'where do I get an access code' falls to the catch-all again — the gap "
     "a model filled with 'from the Super Research app'",
     [(r'            r"|give|share|sharing|into)\b", low):' + "\n"
       '        return None, [_ADD_A_COMPUTER]',
       r'            r"|give|share|sharing|into)\b", low):' + "\n"
       '        pass')]),
    ("A12", SR, "a person who LOST a code for a computer they already have is told to set "
     "up a new one",
     # ⚠ RE-ANCHORED 2026-09-24: rule 6d reuses 6c's exclusion list as its trigger,
     # so the list alone matched twice; the 6c line above it pins which one.
     [(r'            r"(?:access|pair(?:ing)?)[ -]?codes?\b", low) and not re.search(' + "\n"
       r'            r"\b(?:new|another|again|expired?|lost|lose|forgot(?:ten)?|reset|wrong"',
       r'            r"(?:access|pair(?:ing)?)[ -]?codes?\b", low) and not re.search(' + "\n"
       r'            r"\b(?:zzqq|lose|forgot(?:ten)?|reset|wrong"')]),
    ("A13", SR, "the updates path shows a needsDevice sign-in announce with no relay rule",
     [('    if (isinstance(signed_in, dict) and signed_in.get("needsDevice")\n'
       '            and not signed_in.get("autoStarted")):',
       '    if False and (isinstance(signed_in, dict) and signed_in.get("needsDevice")\n'
       '            and not signed_in.get("autoStarted")):')]),
    ("A14", SR, "⛔ the install-here reply hands a brand-new person `superresearch --pair` "
     "again",
     [('        "this device then shows an 8-character access code; send it to me and "\n'
       '        "I’ll connect it.",',
       '        "run superresearch --pair on it — it shows an 8-character access code; "\n'
       '        "send it to me and I’ll connect it.",')]),
    # ═══ W — the watcher (reaches the person with no model turn) ═══════════════
    ("W1", POLL, "⛔ THE WATCHER'S ADD LINE LOSES THE LINK — and nothing relays this text, "
     "so nothing could put it back",
     [('            f"Add a computer: set one up at https://superresearch.io/install, then "\n',
       '            f"Add a computer: then "\n')]),
    ("W2", POLL, "the watcher names a button that does not render for a first computer",
     [('            f"Connection)\\n\\n"\n',
       '            f"Connection → Add Device)\\n\\n"\n')]),
    # ═══ T — the terminal ══════════════════════════════════════════════════════
    ("T1", CLI, "the terminal's empty state loses the link",
     [('    print("  Add a computer:      set one up at https://superresearch.io/install, then")',
       '    print("  Add a computer:      then")')]),
    ("T2", CLI, "the connect closing card loses the link, so a first-time connect ends with "
     "no route to a computer",
     [('b.dim("Add a computer: set one up at https://superresearch.io/install, then send your "',
       'b.dim("Add a computer: send your "')]),
    # ═══ B — the bridge refusal (printed word for word by `agent research`) ══════
    ("B1", BRIDGE, "the no_devices refusal loses the link",
     [('                                          "https://superresearch.io/install, then "\n',
       '                                          "then "\n')]),
    # ═══ K — SKILL.md ══════════════════════════════════════════════════════════
    ("K1", SKILL, "⛔⛔ THE DESCRIPTION STOPS NAMING SIGN-IN AND DEVICES — the reason a "
     "self-written note beat this skill in both failed relays",
     [('"do a Super Research", or deep-dive a subject, and to sign in or out ("Login to\n'
       '  Super Research") or list or add devices / Research Computers ("List devices",\n'
       '  "Add device") — an 8-char',
       '"do a Super Research", or deep-dive a subject — an 8-char')]),
    ("K2", SKILL, "⛔ asked how to set up a machine, the model is handed the pair command "
     "again instead of the page",
     [('https://superresearch.io/install — nothing else: no install commands, no\n'
       '`superresearch --pair`.',
       'run `superresearch --pair` on it.')]),
    # ═══ R — the backend's pairing screen ══════════════════════════════════════
    ("R1", RESEARCH, "⛔ the pairing screen says 'Enter this code in the Super Research "
     "app' again — the nearest product wording to the invented origin",
     [("'Send this code to your chat assistant, or enter it in the'",
       "'Enter this code in the Super Research app:'")]),
    ("R2", RESEARCH, "the pairing screen names the '+ add device' button, which does not "
     "render for a first computer",
     [("'Super Research web app under Account → Pipeline Connection.'",
       "'Super Research web app under Account → Pipeline Connection → Add Device.'")]),
    ("R3", RESEARCH, "the timeout blames only the web app, unsaying the chat handover the "
     "screen above offers first",
     [('never sent to a chat assistant or entered in the "',
       'never entered in the "')]),
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
