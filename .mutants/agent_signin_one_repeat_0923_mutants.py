"""Mutation harness — a lost "you're signed in" note gets ONE repeat (2026-09-23).

⛔⛔ WHAT THIS CODE DECIDES. Whether a person whose chat reader took the sign-in
announce and then died is ever told they are signed in; whether they are told it
exactly once and not on every tick; whether the repeat is dropped by a watcher that
already showed it; whether a note addressed to ONE chat can leak a repeat into a
DIFFERENT chat; whether a session that predates the capture epoch is greeted days
late; and whether a failed send still puts the watermark back.

⭐⭐ THE SHARPEST MUTANT HERE is R2 — "just stop claiming on the parked path". It
looks like the obvious simplification and it is the one the owner's brief warned
about by name: `claim_signin_announce` answers "first" (set, stay SILENT) when no
watermark exists, so a brand-new sign-in — the commonest case — never gets its
repeat. Only a test run as a FIRST-EVER sign-in can see it; a test run over an older
watermark passes it. That is why case (a) exists.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

    python .mutants/agent_signin_one_repeat_0923_mutants.py
    python .mutants/agent_signin_one_repeat_0923_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

BRIDGE = "agent/facade/bridge.py"
POLL = "agent/facade/skill/scripts/sr_attention_poll.py"
PREFS = "agent/facade/prefs.py"
OURS = (BRIDGE, POLL, PREFS)

# ⭐ THE GUARDS THIS CHANGE ADDED OR REPINNED, and the only tests the score is about.
MINE = ("tests/test_signin_one_repeat_0923.py "
        "tests/test_signin_once_0901.py "
        "tests/test_signin_announce_0826.py")
MIN_SELECTED = 90

ALL_SUITES = "tests/"

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    ("R1", BRIDGE, "under",
     "⛔⛔ THE CLAIM GOES BACK ONTO THE NOTE'S OWN ts, so the re-mint finds "
     "cap <= seen and a reader that took the bytes and died leaves the person signed "
     "in and never told — the loss this change exists to close",
     [('                        if not ev_origin and mark_ms > 0:\n'
       '                            mark_ms -= 1\n', '')]),
    ("R2", BRIDGE, "under",
     "⛔⛔ THE PARKED PATH STOPS CLAIMING AT ALL — the tempting simplification. With "
     "no watermark the claim answers 'first' and stays silent, so a BRAND-NEW sign-in "
     "never gets its repeat; only a first-ever test can see it",
     [('marked, mark_prev = _claim_announced(sess, mark_ms)',
       'marked, mark_prev = False, None')]),
    ("R3", BRIDGE, "over",
     "⛔⛔ AN ADDRESSED NOTE IS REPEATED TOO — and a re-mint only ever reaches an "
     "account-wide reader, so the repeat of chat A's sign-in surfaces in a DIFFERENT "
     "chat, from a watcher that never saw its ts and cannot drop it",
     [('if not ev_origin and mark_ms > 0:', 'if mark_ms > 0:')]),
    ("R4", BRIDGE, "under",
     "the failed-send rollback compares against the OLD claim value, finds a "
     "mismatch, refuses — and strands the mark one behind a note nobody received",
     [('_rollback_announced(sess, mark_prev, mark_ms)',
       '_rollback_announced(sess, mark_prev, mark_ms + 1)')]),
    ("R5", POLL, "over",
     "⛔⛔ THE WATCHDOG STOPS DROPPING A ts IT ALREADY SHOWED — and since every "
     "delivered sign-in now arrives twice, every person is greeted twice",
     [('if si_key != si_ts:', 'if True:')]),
    ("R6", BRIDGE, "over",
     "⛔ A SESSION FROM BEFORE THE CAPTURE EPOCH IS GREETED — somebody who signed in "
     "days ago is told 'signed in' now, because a missing epoch was papered over",
     [('    cap = getattr(sess, "connected_at_ms", None)\n'
       '    if not isinstance(cap, (int, float)) or not cap:\n'
       '        return (None, None)\n'
       '    try:\n'
       '        # ⛔⛔ ONE ATOMIC CLAIM',
       '    cap = getattr(sess, "connected_at_ms", None) or 9_000_000\n'
       '    try:\n'
       '        # ⛔⛔ ONE ATOMIC CLAIM')]),
    ("R7", BRIDGE, "over",
     "⛔⛔ THE RE-MINT NEVER SETTLES THE MARK, so the one repeat becomes a repeat on "
     "EVERY tick, forever",
     [('        outcome, prev = prefs.claim_signin_announce(int(cap), sess.uid)',
       '        outcome, prev = ("won", prefs.get_announced_signin_ms(sess.uid))')]),
    ("R8", PREFS, "under",
     "⛔ THE CLAIM LOSES ITS LOCK, so concurrent readers each read the old mark and "
     "each win — one sign-in announced once per reader",
     [('    with _lock:\n'
       '        prefs = load()\n'
       '        owner = prefs.get(_ANNOUNCED_SIGNIN_UID)\n'
       '        raw = prefs.get(_ANNOUNCED_SIGNIN)\n',
       '    if True:\n'
       '        prefs = load()\n'
       '        owner = prefs.get(_ANNOUNCED_SIGNIN_UID)\n'
       '        raw = prefs.get(_ANNOUNCED_SIGNIN)\n')]),
]




def _py() -> str:
    """The interpreter to run the agent suite under.

    ⛔ THE MAC'S VENV WHEN IT EXISTS, OTHERWISE THIS INTERPRETER. The runner this
    was copied from hardcodes `agent/.venv/bin/python`, which does not exist on
    Windows (production here) or in a WSL test venv — there the harness could
    not run at all. The fallback is the interpreter that launched the harness,
    which already has pytest if it can run this file's baseline.
    """
    venv = AGENT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable

def _mark(mid: str, fname: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _refuse_if_a_previous_run_died() -> "str | None":
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _path_for(fname: str) -> Path:
    return ROOT / fname


def _digest() -> dict:
    """Content hash of every file this harness can touch.

    ⭐ CONTENT, NOT `git status`. Uncommitted work is the normal state mid-wave, so
    a git check would report dirty on every run and a real leftover mutant would
    be invisible inside that noise."""
    return {f: hashlib.sha256(_path_for(f).read_bytes()).hexdigest() for f in OURS}


def _pytest(args, cwd, env) -> str:
    """'green' | 'red' | 'nothing-collected'.

    ⛔⛔ EXIT 5 IS NOT A FAILURE. pytest returns 5 when nothing is collected, and a
    runner that only asks `returncode == 0` reads that as red — so one typo in the
    selection would score every mutant killed against zero tests."""
    code = sh(args, cwd=cwd, env=env).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(filtered: bool) -> bool:
    purge_pycache(AGENT)
    py = _py()
    suites = MINE.split() if filtered else [ALL_SUITES]
    out = _pytest([py, "-B", "-m", "pytest", *suites, "-q", "-p", "no:cacheprovider"],
                  AGENT, ENV)
    if out == "nothing-collected":
        raise AssertionError("the agent leg collected NO tests — check the selection")
    return out == "green"


def _selected_count() -> int:
    py = _py()
    out = sh([py, "-B", "-m", "pytest", *MINE.split(), "--collect-only", "-q",
              "-p", "no:cacheprovider"], cwd=AGENT, env=ENV).stdout
    # ⛔ THE SUMMARY LINE IS "N tests collected in 0.09s" — it does not END with
    # "collected", and a parser that assumed it did returned 0 and refused the run.
    # That refusal is the guard working; this is the parser it was guarding.
    import re as _re
    m = _re.search(r"^(\d+) tests? collected", out, _re.M)
    return int(m.group(1)) if m else 0


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — a spot check, not a score.")
    print("scope: THE WHOLE AGENT SUITE (--unfiltered)" if unfiltered
          else "scope: THIS WAVE'S OWN GUARDS ONLY — pass --unfiltered for the other number")

    stranded = _refuse_if_a_previous_run_died()
    if stranded:
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {stranded}\nRestore that file, then delete\n    {_INFLIGHT}")
        return 2

    if not unfiltered:
        n = _selected_count()
        print(f"the wave's own files collect {n} test(s)")
        if n < MIN_SELECTED:
            print(f"⛔⛔ TOO FEW (need >= {MIN_SELECTED}) — a selection that matches "
                  "nothing exits 5 and scores every mutant killed. Refusing to run.")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests(filtered=not unfiltered):
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green\n")

    survivors, faults = [], []
    for mid, fname, direction, why, edits in selected:
        path = _path_for(fname)
        original = path.read_text(encoding="utf-8")
        original_bytes = path.read_bytes()
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            # ⛔⛔ COMPILED BEFORE IT IS WRITTEN. A mis-indented anchor still
            # substring-matches and yields an unparseable file; the suite then goes
            # red on an import error and the mutant banks a kill it never earned.
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as syn:
                    raise AssertionError(
                        f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                        "check the anchor's indentation") from None
            _mark(mid, fname)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests(filtered=not unfiltered)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                again = not run_tests(filtered=not unfiltered)
                if again != killed:
                    flapped = True
                    killed = False
            mark = "✓ killed  " if killed and not flapped else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed or flapped:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            # ⛔ BYTES, NOT TEXT: on Windows a text restore turns LF into CRLF
            # and the leftover check below then cries wolf on a clean tree.
            path.write_bytes(original_bytes)
            _unmark()

    after = _digest()
    leftover = [f for f in before if before[f] != after[f]]
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the wave's score)" if only else ""
    scope = " [whole agent suite]" if unfiltered else " [own guards]"
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
