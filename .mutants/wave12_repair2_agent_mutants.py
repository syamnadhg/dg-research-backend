"""Mutation harness — wave 12 repair 2, the chat bridge, the agent terminal and the
backend docs (2026-09-27).

The second cross-verify of wave 12 ("Allow all") found three things in this lane.
Each repair has mutants here that put that defect back, and each must die for the
right reason.

⛔⛔ WHAT THIS CODE DECIDES.
  R* — bridge `_instant_join` (G8): when nothing usable was saved and the router
       picked one of the person's OWN computers on the list as it was before the
       join, THAT pick is saved — or the joined computer, a second runnable
       device, takes their unnamed research (own asleep) or makes every one ask
       "which computer?" (both awake). Only when nothing routed is the joined one
       saved. The tests ask the router itself where the next research goes.
  W* — agent terminal `cmd_device` (G27): the WSL redirect's chat phrase points
       the SAME way as the command given — `allow-all <id> no` at a phrase the
       chat acts on as OFF, `visibility <id> private` at one it acts on as
       private, `visibility <id> public --allow-all` at the Allow-all confirm.
       The tests hand the printed phrase to the chat's own router.
  X* — the backend and agent docs (G30): every passage on turning Allow all off
       or going private says nobody is removed and where people ARE removed; the
       §5a-bis paragraph names Reset as the one that does remove everyone; the
       agent README's join paragraph says what G8 now does.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/wave12_repair2_agent_mutants.py
  .venv/bin/python .mutants/wave12_repair2_agent_mutants.py R1 W1 X1
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
CLI = "agent/facade/cli.py"
README = "README.md"
ARCH = "ARCHITECTURE.md"
AGENT_README = "agent/README.md"

SUITES = {
    BRIDGE: (AGENT, "tests/test_allow_all_bridge_0926.py tests/test_device_projection_795.py "
                    "tests/test_crossverify_fixes_795.py tests/test_fe_json_792.py"),
    CLI: (AGENT, "tests/test_allow_all_clients_0926.py tests/test_chat_owner_793.py"),
    README: (ROOT, "tests/test_allow_all_docs_0927.py"),
    ARCH: (ROOT, "tests/test_allow_all_docs_0927.py"),
    AGENT_README: (AGENT, "tests/test_allow_all_docs_0927.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

_SELECT = ('                if not kept:\n'
           '                    pick = device_id if routed is None else routed\n')

MUTANTS = [
    # ═══ R — the instant join saves the router's own pick (G8) ════════════════
    ("R1", BRIDGE, "⛔⛔ THE FINDING, PUT BACK: with nothing saved, the router's pick is "
     "NOT written down — the joined computer becomes a second runnable device, so a "
     "sole owner's research goes to the stranger's (own asleep) or asks 'which "
     "computer?' (both awake)",
     [(_SELECT, _SELECT.replace("if not kept:", "if not kept and routed is None:"))]),
    ("R2", BRIDGE, "⛔ when NOTHING routed, the person's first computer is saved instead of "
     "the joined one — a two-computer owner the router would have asked is silently "
     "pinned, against the spec's rule",
     [(_SELECT, _SELECT.replace(
         "pick = device_id if routed is None else routed",
         'pick = routed or next((d.get("id") for d in before if d.get("id")), device_id)'))]),
    ("R3", BRIDGE, "⛔ the person's own computer is saved but the reply says the JOINED one "
     "is selected — the chat tells them their research will run on a stranger's",
     [('                    prefs.set_selected_device(pick, sess.uid)\n'
       '                    saved = pick\n',
       '                    prefs.set_selected_device(pick, sess.uid)\n'
       '                    saved = device_id\n')]),

    # ═══ W — the WSL hint's direction (G27) ═══════════════════════════════════
    ("W1", CLI, "⛔⛔ THE FINDING, PUT BACK: `allow-all <id> no` under WSL points at 'let "
     "anyone join my computer' — the chat's confirm for OPENING the door",
     [('        ("allow-all", "no"): "Stop letting anyone join a computer from chat:  "\n'
       '                             "/sr turn off allow all",\n', '')]),
    ("W2", CLI, "⛔ `visibility <id> private` under WSL points at 'make my computer public'",
     [('        ("visibility", "private"): "Hide a computer from chat:  "\n'
       '                                   "/sr make my computer private",\n', '')]),
    ("W3", CLI, "⛔ `visibility <id> public --allow-all` under WSL points at the plain "
     "public confirm — a yes publishes it and leaves the door shut",
     [('    if _hint is None and _sub == "visibility" and getattr(args, "allow_all", False):\n',
       '    if False:\n')]),
    ("W4", CLI, "⛔ the OFF hint names an ON phrase — the table entry exists and says the "
     "wrong thing",
     [('                             "/sr turn off allow all",\n',
       '                             "/sr let anyone join my computer",\n')]),

    # ═══ X — the docs say closing the door removes nobody (G30) ════════════════
    ("X1", README, "⛔⛔ THE FINDING, PUT BACK: §5a-bis says private / Reset / hand-off "
     "clear the tick and never that nobody is removed",
     [('**Turning Allow all off, or making the machine private, removes nobody. Anyone '
       'who already joined keeps access — remove people in the web app (Shared with).** ',
       '')]),
    ("X2", README, "⛔ §5a-bis stops naming Reset as the one that removes everyone — "
     "'keeps access' reads as true of Reset too",
     [('Reset is the one that does remove everyone. The web', 'The web')]),
    ("X3", README, "⛔ the pairing step's 'change it any time' block says nothing of who "
     "keeps access",
     [(' Neither `--visibility private` nor `--allow-all no` removes anybody: anyone who '
       'already joined keeps access — remove people in the web app (Shared with).', '')]),
    ("X4", README, "⛔ the agent's owner-verbs bullet sets Allow all off with no word "
     "about who keeps access",
     [('  Going private or turning Allow all off removes nobody: anyone who already\n'
       '  joined keeps access — remove people in the web app (Shared with).\n', '')]),
    ("X5", ARCH, "⛔ ARCHITECTURE's writer paragraph describes `--allow-all no` and "
     "`--visibility private` and never says `sharedWith[]` is untouched",
     [(' Neither `--allow-all no` nor\n`--visibility private` touches `sharedWith[]`: '
       'anyone who already joined keeps\naccess — remove people in the web app '
       '(Shared with).', '')]),
    ("X6", AGENT_README, "⛔ the agent README's going-private line says nothing of who "
     "keeps access",
     [(', and anyone\nwho already joined keeps access — remove people in the web app '
       '(Shared with)). From the', '). From the')]),
    ("X7", AGENT_README, "⛔ the agent README's Allow-all-off line says who keeps access "
     "but not where people are removed",
     [('Neither removes anybody: anyone who already joined keeps access — remove people\n'
       'in the web app (Shared with).\n', 'Anyone who already joined keeps access.\n')]),
    ("X8", AGENT_README, "⛔ the agent README's join paragraph never says the person's own "
     "computer is saved — the G8 behaviour goes undocumented",
     [(' When one of yours would have, and you had not chosen\none, the join saves THAT '
       'one as your choice, so your research never moves off a\ncomputer of your own and '
       'you are not asked "which computer?" afterwards.', '')]),
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
