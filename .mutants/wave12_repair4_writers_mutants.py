"""Mutation harness — wave 12 repair 4, the machine's and the chat bridge's
Allow all writers (K1) and the join during the person's own Reset (K9)
(2026-09-27).

The fourth cross-verify of wave 12 ("Allow all") found two things in this lane.
Each repair has mutants here that put that defect back, or a near miss of it, and
each must die for the right reason.

⛔⛔ WHAT THIS CODE DECIDES.
  M* — research.py `run_visibility` (K1, the machine's writer): the rules now
       refuse a write that makes a non-public computer public while a stored
       `allowAll: true` is left out of it, so `--allow-all yes` (and the
       one-step `--visibility public --allow-all`) on a PRIVATE computer that
       carries an old tick first writes `{allowAll: false}` alone, then the ON
       patch — only there. A failed clear sends nothing after it and says
       today's "could not confirm"; a failed ON after a landed clear says it
       could not confirm Allow all went on and that an (ineffective) tick was
       cleared before it (wave 12 repair 5 took back "Could not turn Allow all
       on" — the writer cannot tell a refusal from a lost reply).
  B* — bridge `/device/visibility` (K1, the chat's writer): the same sequence
       through the real `FirestoreRest` writers, with its own replies for a
       refused, unconfirmed or revoked ON after a landed clear.
  R* — bridge `_instant_join` (K9): during the person's own Reset window the
       hold outranks the router's pick unless that pick is a computer they own,
       so a friend's code-shared computer is never saved as their choice.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/wave12_repair4_writers_mutants.py
  .venv/bin/python .mutants/wave12_repair4_writers_mutants.py M1 B1 R1
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

RESEARCH = "research.py"
BRIDGE = "agent/facade/bridge.py"

SUITES = {
    # The machine's old `--visibility` pins run too: every other request's writes
    # must stay exactly what they were.
    RESEARCH: (ROOT, "tests/test_allow_all_0926.py tests/test_visibility_0904.py "
                     "tests/test_terminal_words_0916.py"),
    BRIDGE: (AGENT, "tests/test_allow_all_bridge_0926.py tests/test_device_projection_795.py "
                    "tests/test_crossverify_fixes_795.py tests/test_fe_json_792.py "
                    "tests/test_app_plane_unchanged.py tests/test_owner_verbs_793.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── the machine (research.py) ────────────────────────────────────────────────
M_CLEAR_FIRST = '    clear_first = want and current != "public" and leftover\n'
M_CLEARED = '    cleared = clear_first and _pair_patch_device(device_id, {"allowAll": False})\n'
M_WRITE = ('    if patch and (clear_first and not cleared\n'
           '                  or not _pair_patch_device(device_id, patch)):')
M_SECOND = ('        if cleared:\n'
            '            # ⛔ THE CLEAR LANDED AND THE ON PATCH DID NOT')
# ⛔ RE-AIMED 2026-09-28 (wave 12 repair 5, final verify rules-1): the lines now
# say the tick was cleared BEFORE an unconfirmed ON. Same mutation — both gone.
M_CERTAIN = ("            print(f\"  {_c(_DIM, '     Before it, an old Allow all tick was "
             "cleared, which did nothing')}\")\n"
             "            print(f\"  {_c(_DIM, '     while this computer was private. "
             "Run this again with no value')}\")\n")
M_EXIT = ('            print()\n'
          '            return 1\n'
          '        # ⛔⛔ "NOTHING CHANGED" IS A CLAIM THIS CANNOT MAKE')

# ── the chat bridge (bridge.py) ──────────────────────────────────────────────
B_CLEAR_FIRST = '            clear_first = want_all is True and current != "public" and stored\n'
B_SEND = ('                    fs.set_device_allow_all(device_id, False)\n'
          '                    cleared = True\n')
B_CLEARED = ('                if cleared:\n'
             '                    # ⛔ THE CLEAR LANDED AND ALLOW ALL DID NOT (K1).')
B_REFUSED_AA = '                                "allowAll": False if refused else None})\n'
B_REVOKED = ('                                          + (". Allow all did not go on; "\n'
             '                                             + _TICK_CLEARED if cleared else "")})\n')
B_TICK = ('_TICK_CLEARED = ("an old Allow all tick was cleared, which did nothing while the "\n'
          '                 "computer was private")\n')

# ── the join during a Reset (bridge.py) ──────────────────────────────────────
R_MINE = ('                mine = {d["id"] for d in before\n'
          '                        if d.get("id") and d.get("ownerUid") == sess.uid}\n')
R_GATE = '                if routed not in mine:\n'
R_HOLD = '                    routed = _own_reset_hold(before, sess.uid) or routed\n'

MUTANTS = [
    # ═══ M — the machine's writer (K1) ════════════════════════════════════════
    ("M1", RESEARCH, "⛔⛔ THE FINDING'S NEW-WRITER HALF, PUT BACK: `--allow-all yes` on a "
     "private computer carrying an old tick sends the ON patch alone — which the "
     "rules now refuse, so the owner can never switch Allow all on there",
     [(M_CLEAR_FIRST, '    clear_first = False\n')]),
    ("M2", RESEARCH, "⛔ the clear goes out on every private computer with a tick, even "
     "for a plain `--visibility public` that already clears it in its own patch",
     [(M_CLEAR_FIRST, '    clear_first = current != "public" and leftover\n')]),
    ("M3", RESEARCH, "⛔ a truthy tick counts — the STRING \"true\", which no reader "
     "honours, costs a second write the rules never needed",
     [(M_CLEAR_FIRST,
       '    clear_first = want and current != "public" and bool(meta.get("allowAll"))\n')]),
    ("M4", RESEARCH, "⛔ the clear publishes too — the computer is public with approval "
     "before Allow all is written, and a failed ON leaves it listed while the screen "
     "says only a tick was cleared",
     [(M_CLEARED, '    cleared = clear_first and _pair_patch_device(device_id, '
                  '{"visibility": "public", "allowAll": False})\n')]),
    ("M5", RESEARCH, "⛔⛔ the ON patch goes out behind a clear that did not land — a "
     "change the screen, reporting 'could not confirm', then never mentions",
     [(M_WRITE, '    if patch and not _pair_patch_device(device_id, patch):')]),
    ("M6", RESEARCH, "⛔ a failed ON after a landed clear gets today's 'could not confirm "
     "that change' — hiding that something DID change",
     [(M_SECOND, '        if False:\n'
                 '            # ⛔ THE CLEAR LANDED AND THE ON PATCH DID NOT')]),
    ("M7", RESEARCH, "⛔ the second-failure screen never says what was cleared, or that it "
     "opened nothing",
     [(M_CERTAIN, "")]),
    ("M8", RESEARCH, "⛔ a failed ON after a landed clear exits 0 — the answer a script "
     "reads says it worked",
     [(M_EXIT, M_EXIT.replace("return 1", "return 0"))]),

    # ═══ B — the chat bridge's writer (K1) ════════════════════════════════════
    ("B1", BRIDGE, "⛔⛔ THE FINDING'S NEW-WRITER HALF, PUT BACK: Allow all ON from the "
     "chat on a private computer carrying an old tick sends the ON patch alone — "
     "refused by the rules, every time",
     [(B_CLEAR_FIRST, '            clear_first = False\n')]),
    ("B2", BRIDGE, "⛔ the clear goes out before every ON from private, tick or no tick — "
     "a write a lagging ruleset can refuse, on documents that never had the field",
     [(B_CLEAR_FIRST, '            clear_first = want_all is True and current != "public"\n')]),
    ("B3", BRIDGE, "⛔ the clear goes out whenever a tick is stored on a private computer — "
     "a plain publish, which already clears it in its own patch, now writes twice",
     [(B_CLEAR_FIRST, '            clear_first = current != "public" and stored\n')]),
    ("B4", BRIDGE, "⛔ the clear publishes too — public with approval before Allow all "
     "lands, and a failed ON leaves it listed while the reply says nothing changed",
     [(B_SEND, B_SEND.replace("(device_id, False)", "(device_id, False, publish=True)"))]),
    ("B5", BRIDGE, "⛔ the clear is never recorded as landed, so a failed ON after it says "
     "'nothing changed' over a tick that was cleared",
     [(B_SEND, '                    fs.set_device_allow_all(device_id, False)\n')]),
    ("B6", BRIDGE, "⛔ a failed ON after a landed clear falls through to today's words",
     [(B_CLEARED, B_CLEARED.replace("if cleared:", "if False:"))]),
    ("B7", BRIDGE, "⛔ a refused ON after the clear stops saying Allow all is off",
     [(B_REFUSED_AA, '                                "allowAll": None})\n')]),
    ("B8", BRIDGE, "⛔ a revoked sign-in after the clear says only 'session revoked' — "
     "never that Allow all did not go on",
     [(B_REVOKED, '                                          + ""})\n')]),
    ("B9", BRIDGE, "⛔ the cleared tick is named without saying it opened nothing — read as "
     "a door that was open",
     [(B_TICK, '_TICK_CLEARED = "an old Allow all tick was cleared"\n')]),

    # ═══ R — a join during the person's own Reset (K9) ════════════════════════
    ("R1", BRIDGE, "⛔⛔ THE FINDING, PUT BACK: with their own computer mid-Reset, the "
     "router's pick of a friend's code-shared computer is saved — and every unnamed "
     "research goes there after the re-pair",
     [(R_GATE, '                if routed is None:\n')]),
    ("R2", BRIDGE, "⛔⛔ every computer on the list counts as their own, so a friend's pick "
     "beats the hold again",
     [(R_MINE, '                mine = {d["id"] for d in before\n'
               '                        if d.get("id")}\n')]),
    ("R3", BRIDGE, "⛔ an id-less row of their own counts as a pick, so 'nothing routed' "
     "reads as 'their own routed' and the hold is skipped",
     [(R_MINE, '                mine = {d.get("id") for d in before\n'
               '                        if d.get("ownerUid") == sess.uid}\n')]),
    ("R4", BRIDGE, "⛔ with no Reset to hold, the router's pick of a computer they were "
     "given is thrown away and the stranger's joined computer is saved instead",
     [(R_HOLD, '                    routed = _own_reset_hold(before, sess.uid)\n')]),
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
