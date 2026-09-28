"""Mutation harness — wave 12 repair 1, the chat assistant's half (2026-09-27).

The cross-verify of wave 12 ("Allow all") found seven things on the chat
assistant's side and the machine's words. Each repair has a mutant here that
puts that defect back, and each must die for the right reason.

⛔⛔ WHAT THIS CODE DECIDES.
  B* — bridge `_instant_join` (F3): the joined computer is selected ONLY when
       nothing was routable before the join — the router's own question, asked of
       the list with the joined computer taken out. Never over a live selection,
       never over the computer an unnamed research already went to (the sole
       device, the sole online one), never on a list that could not be read.
  C* — bridge `/device/ask` (F23): `ask_unconfirmed` only when the request LEFT;
       a sign-in refresh that failed first (`sent: False` from `_mint_bearer`) is
       `ask_not_sent`, worded by both clients as "nothing was sent"; and the
       unconfirmed sentence points at the requests list, where an ask waits.
  D* — the canonical disclosure (F24 + F6): "They run research on your AI
       accounts and can see your email, who else is on it, and what's running on
       it." — the chat confirm, the agent terminal and the machine, word for word.
  E* — going private on an allow-all computer (F26): the bridge returns
       `allowAllWas`, and both clients add the machine's "keeps access" line only
       when the door WAS open.
  K* — SKILL.md (F17): each confirm list names `device-allow-all yes` and never
       `device-allow-all no` — the direction is the whole point.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/wave12_repair1_agent_mutants.py
  .venv/bin/python .mutants/wave12_repair1_agent_mutants.py B1 C2 K6
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

BRIDGE = "agent/facade/bridge.py"
SR = "agent/facade/skill/scripts/sr.py"
CLI = "agent/facade/cli.py"
SKILL = "agent/facade/skill/SKILL.md"
RESEARCH = "research.py"

SUITES = {
    BRIDGE: (AGENT, "tests/test_allow_all_bridge_0926.py tests/test_device_projection_795.py "
                    "tests/test_crossverify_fixes_795.py tests/test_fe_json_792.py"),
    SR: (AGENT, "tests/test_allow_all_clients_0926.py tests/test_allow_all_router_0926.py "
                "tests/test_chat_owner_793.py"),
    CLI: (AGENT, "tests/test_allow_all_clients_0926.py tests/test_chat_owner_793.py"),
    SKILL: (AGENT, "tests/test_chat_owner_793.py tests/test_chat_public_792.py"),
    RESEARCH: (ROOT, "tests/test_allow_all_0926.py tests/test_visibility_0904.py "
                     "tests/test_terminal_words_0916.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ⛔ RE-AIMED 2026-09-27 (wave 12 repair 2, cross-verify G8) — `_SELECT`, B1 AND
# B4. Repair 2 made the join SAVE the router's own pick when nothing usable was
# saved and one of the person's computers routed, so the rule is now
# `if not kept:` + `pick = device_id if routed is None else routed`. B1 and B4
# keep their original defects on the new lines; the new rule's own mutants are
# R1-R3 in wave12_repair2_agent_mutants.
_SELECT = ('                if not kept:\n'
           '                    pick = device_id if routed is None else routed\n')
_UNREAD = ('            if devs is not None:\n'
           '                before = [d for d in devs if d.get("id") != device_id]\n')

MUTANTS = [
    # ═══ B — the instant join's selection (F3) ════════════════════════════════
    ("B1", BRIDGE, "⛔⛔ THE FINDING, PUT BACK: nothing SAVED reads as nothing ROUTABLE — "
     "a person who owns one computer joins a stranger's and every unnamed research "
     "moves onto it",
     [(_SELECT, _SELECT.replace("pick = device_id if routed is None else routed",
                                "pick = device_id"))]),
    ("B2", BRIDGE, "⛔⛔ the router is asked about the list AFTER the join — the joined "
     "computer makes a sole own computer one of two, and the join takes over",
     [('                before = [d for d in devs if d.get("id") != device_id]\n',
       '                before = list(devs)\n')]),
    ("B3", BRIDGE, "⛔ a list that could not be READ, with nothing saved, selects the "
     "joined computer — unknown read as empty",
     [(_UNREAD,
       '            if devs is None and not saved:\n'
       '                prefs.set_selected_device(device_id, sess.uid)\n'
       '                saved = device_id\n' + _UNREAD)]),
    ("B4", BRIDGE, "⛔ a saved choice part-way through a Reset is replaced — still the "
     "person's machine and still their choice",
     [(_SELECT, _SELECT.replace("if not kept:", "if True:"))]),

    # ═══ C — sent or not (F23) ════════════════════════════════════════════════
    ("C1", BRIDGE, "⛔⛔ a sign-in refresh that failed before anything left is answered "
     "'that may have gone through'",
     [('                if body.get("sent") is False:\n', '                if False:\n')]),
    ("C2", BRIDGE, "⛔⛔ the mint failure no longer says nothing went out — the ask cannot "
     "tell it from a timeout",
     [('                               f"({type(e).__name__})", "sent": False}',
       '                               f"({type(e).__name__})"}')]),
    ("C3", BRIDGE, "⛔⛔ ABSENT read as 'not sent' — a timeout that may sit on a committed "
     "join is told nothing was sent, and the retry answers already_shared",
     [('                if body.get("sent") is False:\n',
       '                if not body.get("sent"):\n')]),
    ("C4", SR, "⛔ ask_not_sent has no chat sentence — the machine token reaches the person",
     [('    "ask_not_sent": "This agent couldn’t refresh its sign-in, so nothing was sent. "\n'
       '                    "It’s safe to ask again in a moment.",\n', '')]),
    ("C5", CLI, "⛔ ask_not_sent has no terminal sentence",
     [('    "ask_not_sent": "this agent could not refresh its sign-in, so nothing was "\n'
       '                    "sent — it is safe to ask again in a moment",\n', '')]),
    ("C6", SR, "⛔ an unconfirmed ask sends the person to 'your computers' — an ordinary "
     "ask that went through is waiting in the requests list",
     [('                       "Ask me for your requests before asking again: it’s either "\n'
       '                       "waiting there, or it let you in and it’s one of your "\n'
       '                       "computers.",\n',
       '                       "Ask me for your computers before asking again.",\n')]),
    ("C7", CLI, "⛔ the terminal's unconfirmed ask points only at `agent device`",
     [('                       "through; check `agent device requests` (still waiting) "\n'
       '                       "and `agent device` (let straight in) before asking again",\n',
       '                       "through; check `agent device` before asking again",\n')]),

    # ═══ D — the canonical disclosure (F24 + F6) ══════════════════════════════
    ("D1", SR, "⛔⛔ the chat's ON confirm asks consent to less than the web and the "
     "machine disclose — no email, no members, nothing about what is running",
     [('                    "without asking you. They run research on your AI accounts and "\n'
       '                    "can see your email, who else is on it, and what\'s running on "\n'
       '                    "it. People you removed stay out.")',
       '                    "without asking you, and run research on your AI accounts. "\n'
       '                    "People you removed stay out.")')]),
    ("D2", CLI, "⛔⛔ the terminal says only that joiners run research",
     [('                      "     They run research on your AI accounts and can see your "\n'
       '                      "email, who else is on it, and what\'s running on it.\\n"\n',
       '                      "     and run research on your AI accounts.\\n"\n')]),
    ("D3", RESEARCH, "⛔ the machine's sentence stops at 'who else is on it' — what is "
     "running on it goes unsaid, and the surfaces disagree again",
     [('_ALLOW_ALL_SEES = ("They run research on your AI accounts and can see your email, "\n'
       '                   "who else is on it, and what\'s running on it.")',
       '_ALLOW_ALL_SEES = ("They run research on your AI accounts and can see your email "\n'
       '                   "and who else is on it.")')]),

    # ═══ E — going private on an open computer (F26) ══════════════════════════
    ("E1", BRIDGE, "⛔⛔ the reply never says the door WAS open — no client can say the "
     "people who joined keep access",
     [('"allowAll": want_all, "allowAllWas": current_all,', '"allowAll": want_all,')]),
    ("E2", BRIDGE, "⛔ `allowAllWas` reports the NEW state — false on every close",
     [('"allowAllWas": current_all,', '"allowAllWas": want_all,')]),
    ("E3", SR, "⛔⛔ the chat never says who keeps access after going private",
     [('        if changed and body.get("allowAllWas") is True:\n',
       '        if False:\n')]),
    ("E4", SR, "⛔ 'keeps access' is said over a computer nobody could join",
     [('        if changed and body.get("allowAllWas") is True:\n',
       '        if changed:\n')]),
    ("E5", CLI, "⛔⛔ the terminal never says who keeps access after going private",
     [('    if state == "private" and changed and body.get("allowAllWas") is True:\n',
       '    if False:\n')]),
    ("E6", CLI, "⛔ the terminal says 'keeps access' over a computer nobody could join",
     [('    if state == "private" and changed and body.get("allowAllWas") is True:\n',
       '    if state == "private" and changed:\n')]),

    # ═══ K — SKILL.md: the direction in each confirm list (F17) ════════════════
    ("K6", SKILL, "⛔⛔ the handoff list says to run `device-allow-all no` after a yes to "
     "the ON confirm — the door the owner agreed to open stays shut, and every test "
     "was green",
     [('device-approve/device-deny/device-visibility/device-allow-all yes/update/install/',
       'device-approve/device-deny/device-visibility/device-allow-all no/update/install/')]),
    ("K7", SKILL, "⛔ the safe-defaults list confirms OFF and licenses ON unconfirmed",
     [('`device-visibility public`, `device-allow-all yes`, `update`, and `install`**',
       '`device-visibility public`, `device-allow-all no`, `update`, and `install`**')]),
    ("K8", SKILL, "⛔ the Safety list confirms OFF and licenses ON unconfirmed",
     [('  `device-deny`, `device-visibility public`, `device-allow-all yes`, `install`',
       '  `device-deny`, `device-visibility public`, `device-allow-all no`, `install`')]),
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
    selected = [m for m in MUTANTS if not only or m[0] in only]
    print("baseline… ", end="", flush=True)
    for cwd, suites in sorted({SUITES[m[1]] for m in selected}, key=str):
        if not green(cwd, suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
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
