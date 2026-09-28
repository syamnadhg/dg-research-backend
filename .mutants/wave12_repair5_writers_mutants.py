"""Mutation harness — wave 12 repair 5, the Allow all writers' unconfirmed answers
on the research computer and the chat bridge (final verify rules-1, rules-2)
(2026-09-28).

The final focused review of wave 12 ("Allow all") found two answers in this lane
that said more than the code could know. Each repair has mutants here that put
that defect back, or a near miss of it, and each must die for the right reason.

⛔⛔ WHAT THIS CODE DECIDES.
  M* — research.py `run_visibility` (rules-1): on a private computer carrying an
       old tick, `--allow-all yes` clears it alone, then sends the ON patch.
       When the clear landed and the ON patch came back False, the screen says
       it could not confirm Allow all went on — it may or may not have been
       saved — and that an old tick, which opened nothing, was cleared before
       it. `_pair_patch_device` answers False for a refusal and for a lost reply
       alike, so "Could not turn Allow all on" (repair 4) was a claim it could
       not make, and the computer could be public with Allow all on under it.
  B* — bridge `/device/visibility` (rules-2): a transport error from
       `FirestoreRest` (a ReadTimeout, a dropped connection) is the unknown case,
       status None: the ordinary 502 "could not confirm", and after a landed
       clear the K1 502 that also names the cleared tick. Uncaught, it closed
       the socket with no reply and the chat said the bridge was not installed.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/wave12_repair5_writers_mutants.py
  .venv/bin/python .mutants/wave12_repair5_writers_mutants.py M1 B1
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
    # The machine's old `--visibility` pins run too: every other failure keeps
    # today's words.
    RESEARCH: (ROOT, "tests/test_allow_all_0926.py tests/test_visibility_0904.py "
                     "tests/test_terminal_words_0916.py"),
    BRIDGE: (AGENT, "tests/test_allow_all_bridge_0926.py tests/test_device_projection_795.py "
                    "tests/test_crossverify_fixes_795.py tests/test_fe_json_792.py "
                    "tests/test_app_plane_unchanged.py tests/test_owner_verbs_793.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── the machine (research.py) ────────────────────────────────────────────────
M_HEAD = ("            print(f\"  {_c(_WARN, '⚠')}  Could not confirm Allow all went on — "
          "it may or may not have been saved.\")\n")
M_TICK = ("            print(f\"  {_c(_DIM, '     Before it, an old Allow all tick was "
          "cleared, which did nothing')}\")\n")

# ── the chat bridge (bridge.py) ──────────────────────────────────────────────
B_CATCH = ('            except (FirestoreError, requests.RequestException) as e:\n'
           '                # ⛔ THE STATUS DECIDES WHICH SENTENCE IS HONEST')
B_REFUSED = '                refused = getattr(e, "status", None) == 403\n'
B_CLEARED = ('                if cleared:\n'
             '                    # ⛔ THE CLEAR LANDED AND ALLOW ALL DID NOT (K1).')

MUTANTS = [
    # ═══ M — the machine's unconfirmed ON after a landed clear (rules-1) ══════
    ("M1", RESEARCH, "⛔⛔ THE FINDING, PUT BACK: an ON patch whose reply was lost — "
     "possibly saved, the computer public with Allow all on — is reported as "
     "'Could not turn Allow all on'",
     [(M_HEAD, "            print(f\"  {_c(_WARN, '⚠')}  Could not turn Allow all on — "
               "the change was not confirmed.\")\n")]),
    ("M2", RESEARCH, "⛔ the screen says it could not confirm but drops 'it may or may "
     "not have been saved' — read as 'it did not happen'",
     [(M_HEAD, "            print(f\"  {_c(_WARN, '⚠')}  Could not confirm Allow all "
               "went on.\")\n")]),
    ("M3", RESEARCH, "⛔ repair 4's tick line comes back: the cleared tick is 'the only "
     "change for certain', which says nothing else may have landed",
     [(M_TICK, "            print(f\"  {_c(_DIM, '     Only an old Allow all tick was "
               "cleared for certain, and it did')}\")\n")]),

    # ═══ B — the chat bridge's transport errors (rules-2) ═════════════════════
    ("B1", BRIDGE, "⛔⛔ THE FINDING, PUT BACK: a ReadTimeout on the write escapes the "
     "handler, the socket closes with no reply, and the chat says the bridge is "
     "not installed",
     [(B_CATCH, B_CATCH.replace("(FirestoreError, requests.RequestException)",
                                "FirestoreError"))]),
    ("B2", BRIDGE, "⛔ only a timeout is caught — a connection reset after the request "
     "went out still drops the reply",
     [(B_CATCH, B_CATCH.replace("requests.RequestException", "requests.Timeout"))]),
    ("B3", BRIDGE, "⛔ only a dropped connection is caught — the ReadTimeout the finding "
     "measured still drops the reply",
     [(B_CATCH, B_CATCH.replace("requests.RequestException", "requests.ConnectionError"))]),
    ("B4", BRIDGE, "⛔⛔ a transport error is read as a REFUSAL — 'nothing changed' over a "
     "write that may have landed, the direction that lies about the machine",
     [(B_REFUSED, '                refused = (getattr(e, "status", None) == 403\n'
                  '                           or isinstance(e, requests.RequestException))\n')]),
    ("B5", BRIDGE, "⛔ a lost reply after a landed clear gets the plain 'could not "
     "confirm' — the cleared tick goes unmentioned",
     [(B_CLEARED, B_CLEARED.replace("if cleared:",
                                    "if cleared and isinstance(e, FirestoreError):"))]),
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
