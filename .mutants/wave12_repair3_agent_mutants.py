"""Mutation harness — wave 12 repair 3, the chat bridge and the agent terminal's
words (2026-09-27).

The third cross-verify of wave 12 ("Allow all") found three things in this lane.
Each repair has mutants here that put that defect back, and each must die for the
right reason.

⛔⛔ WHAT THIS CODE DECIDES.
  H* — bridge `_instant_join` + `_own_reset_hold` (H9): a person whose only own
       computer is part-way through a Reset routes to NOTHING before the join, and
       the join saved the stranger's computer — which stayed their choice after the
       re-pair. Their own computer inside its Reset window is saved instead, by the
       web app's `heldThroughReset` rules: owned, `awaiting-re-pair`, the window
       open (two minutes' grace; a missing or unreadable deadline is open), and
       only when the router found nothing.
  S* — bridge `_left_nothing` + `_fe_api_post` (H18): a refused connection, a name
       that did not resolve and a connect timeout sent nothing and answer
       `ask_not_sent`; a read timeout, or a server that took the request and hung
       up, stay `ask_unconfirmed`.
  T* — the agent terminal (cli.py, H22 and H18's wording): the ask and the join
       both print "The owner sees your name and email."; `ask_not_sent` names both
       causes.
  D* — the agent README (H22, H9): the ask and the join paragraphs say the same
       sentence; the join paragraph says a computer mid-Reset is kept.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/wave12_repair3_agent_mutants.py
  .venv/bin/python .mutants/wave12_repair3_agent_mutants.py H1 S1 T1 D1
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
AGENT_README = "agent/README.md"

SUITES = {
    # ⛔ test_app_plane_unchanged.py IS IN THE BRIDGE'S SET: the first draft of the
    # H18 fix imported urllib3, which that file forbids, and this harness's baseline
    # could not see it — wave12_allow_all_agent's did.
    BRIDGE: (AGENT, "tests/test_allow_all_bridge_0926.py tests/test_device_projection_795.py "
                    "tests/test_crossverify_fixes_795.py tests/test_fe_json_792.py "
                    "tests/test_app_plane_unchanged.py"),
    CLI: (AGENT, "tests/test_allow_all_clients_0926.py tests/test_public_devices_792.py "
                 "tests/test_empty_state_794.py tests/test_chat_owner_793.py"),
    AGENT_README: (AGENT, "tests/test_allow_all_docs_0927.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ⛔ RE-ANCHORED 2026-09-27 (wave 12 repair 4, K9): the hold now also outranks a
# pick that is not the person's own (a friend's code-shared computer), so the
# gate is `routed not in mine` rather than `routed is None`. H1 still removes the
# hold; H7 still lets it beat every pick. K9's own mutants are in
# wave12_repair4_writers_mutants.
_HOLD = ('                if routed not in mine:\n'
         '                    routed = _own_reset_hold(before, sess.uid) or routed\n')
_WINDOW = '        if deadline is None or now < deadline + _RESET_HOLD_CLOCK_GRACE_MS:\n'

MUTANTS = [
    # ═══ H — a join inside the person's own Reset (H9) ════════════════════════
    ("H1", BRIDGE, "⛔⛔ THE FINDING, PUT BACK: a sole owner mid-Reset routes to nothing, "
     "so the join saves the stranger's computer — and it is still their choice after "
     "the re-pair",
     [(_HOLD, '')]),
    ("H2", BRIDGE, "⛔ a Reset nobody re-paired is held forever — every run refused for a "
     "day while the joined computer sits unused",
     [(_WINDOW, '        if True:\n')]),
    ("H3", BRIDGE, "⛔ no clock grace — a host clock a minute fast ends the hold inside the "
     "window and hands the choice to the stranger's computer",
     [(_WINDOW, _WINDOW.replace(" + _RESET_HOLD_CLOCK_GRACE_MS", ""))]),
    ("H4", BRIDGE, "⛔ a missing or unreadable deadline reads as a closed window — the web "
     "app reads it as open, so the two disagree on the same record",
     [(_WINDOW, _WINDOW.replace("if deadline is None or now <",
                                "if deadline is not None and now <"))]),
    ("H5", BRIDGE, "⛔ somebody ELSE's computer mid-Reset is held as this person's choice — "
     "a machine they never picked",
     [('        if d.get("pairState") != "awaiting-re-pair" or d.get("ownerUid") != uid:\n',
       '        if d.get("pairState") != "awaiting-re-pair":\n')]),
    ("H6", BRIDGE, "⛔ any machine that cannot run is held — a first pairing is not a Reset",
     [('        if d.get("pairState") != "awaiting-re-pair" or d.get("ownerUid") != uid:\n',
       '        if pair_state_usable(d) or d.get("ownerUid") != uid:\n')]),
    ("H7", BRIDGE, "⛔ the hold beats the router's own pick — a computer of theirs that "
     "can run is passed over for the one waiting on its re-pair, and every run is "
     "refused until then",
     [(_HOLD, '                if True:\n'
              '                    routed = _own_reset_hold(before, sess.uid) or routed\n')]),

    # ═══ S — sent or not, on the wire (H18) ═══════════════════════════════════
    ("S1", BRIDGE, "⛔⛔ THE FINDING, PUT BACK: a refused connection, a DNS failure and a "
     "connect timeout are answered 'that may have gone through'",
     [('            if _left_nothing(e):\n'
       '                failed["sent"] = False\n', '')]),
    ("S2", BRIDGE, "⛔ a connect timeout is not recognised — it may have gone through, "
     "says the reply, over a connection that never opened",
     [('    if isinstance(e, requests.ConnectTimeout):\n'
       '        return True\n', '')]),
    ("S3", BRIDGE, "⛔⛔ EVERY ConnectionError reads as 'not sent' — a server that took the "
     "ask and hung up may sit on a committed join, and the retry answers "
     "already_shared",
     [('    return any(c.__name__ == "NewConnectionError" for c in type(reason).__mro__)\n',
       '    return True\n')]),
    ("S5", BRIDGE, "⛔ the name test matches only the exact class — a DNS failure "
     "(urllib3 2's NameResolutionError, a subclass) is 'may have gone through' again",
     [('    return any(c.__name__ == "NewConnectionError" for c in type(reason).__mro__)\n',
       '    return type(reason).__name__ == "NewConnectionError"\n')]),
    ("S4", BRIDGE, "⛔⛔ a READ timeout reads as 'not sent' — the request left, and the "
     "join may have landed",
     [('    if isinstance(e, requests.ConnectTimeout):\n',
       '    if isinstance(e, requests.Timeout):\n')]),

    # ═══ T — the terminal's words (H22, H18) ══════════════════════════════════
    ("T1", CLI, "⛔⛔ THE FINDING, PUT BACK: the ask says 'your name — or your email', the "
     "join 'name and email' — one exchange, two claims",
     [('    print(f"     {_OWNER_SEES_T}")\n',
       '    print("     They see your name — or your email, if you have not set one.")\n')]),
    ("T2", CLI, "⛔ the join says it in its own words again — the one sentence is two",
     [('        print(f"     {_OWNER_SEES_T} Your research runs on their AI accounts.")\n',
       '        print("     Its owner sees your name and email, and your research runs on "\n'
       '              "their AI accounts.")\n')]),
    ("T3", CLI, "⛔ the shared sentence itself says the old half",
     [('_OWNER_SEES_T = "The owner sees your name and email."\n',
       '_OWNER_SEES_T = "They see your name — or your email, if you have not set one."\n')]),
    ("T4", CLI, "⛔ ask_not_sent blames the sign-in when the app could not be reached",
     [('    "ask_not_sent": "this agent could not reach the app or refresh its sign-in, so "\n'
       '                    "nothing was sent — it is safe to ask again in a moment",\n',
       '    "ask_not_sent": "this agent could not refresh its sign-in, so nothing was "\n'
       '                    "sent — it is safe to ask again in a moment",\n')]),

    # ═══ D — the agent README (H22, H9) ═══════════════════════════════════════
    ("D1", AGENT_README, "⛔⛔ THE FINDING, PUT BACK: the ask paragraph says 'your name, or "
     "your email if you haven't set one'",
     [('that owner\'s queue, and nothing happens on their machine until they say yes.\n'
       'The owner sees your name and email.\n',
       'that owner\'s queue — they see your name, or your email if you haven\'t set one,\n'
       'and nothing happens on their machine until they say yes.\n')]),
    ("D2", AGENT_README, "⛔ the join paragraph never says what the owner sees",
     [('choice, so your research comes back to it once the re-pair is done.\n'
       'The owner sees your name and email.\n',
       'choice, so your research comes back to it once the re-pair is done.\n')]),
    ("D3", AGENT_README, "⛔ the join paragraph says nothing of a computer mid-Reset — the "
     "H9 behaviour goes undocumented",
     [('A computer of yours part-way through a Reset counts too: it is saved as your\n'
       'choice, so your research comes back to it once the re-pair is done.\n', '')]),
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
