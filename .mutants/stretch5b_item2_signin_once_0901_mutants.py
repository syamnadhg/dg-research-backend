"""Mutation harness — the sign-in announce is said ONCE, and never lost.

⛔⛔ WHAT THIS HARNESS IS NOT ABOUT. The owner signed *"an unaddressed note is TAKEN
and announced once, deduped"*, and measurement refuted the addressing half: the fleet's
own client omits the chat address ON PURPOSE (*"this fleet's watcher asks with neither,
so claiming an origin here would make the sign-in announceable to nobody"*) and its
watcher is unscoped, so an unaddressed note is already taken and announced there. On the
backend client the address IS sent, so a note is unaddressed only after a TERMINAL
sign-in — where the terminal already said so. The owner then chose the other half of the
same sentence. **The addressing rule is deliberately untouched, and there is no mutant
below that flips it** — the two tests guarding it stand.

⛔⛔ THE DANGEROUS DIRECTION HERE IS THE TIDY SIMPLIFICATION. Every defect this wave
fixes looks like redundancy:

  * two timestamps for one sign-in — "the note has its own clock, why reach into the
    session?" — and collapsing them is what lets the client's own de-dup recognise a
    re-mint as the announce it already showed. That de-dup is the ONLY thing that can
    tell a received announce from a lost one, because a reader that times out and closes
    gracefully is invisible to the server.
  * a lock around a read-modify-write that "obviously" cannot race. MEASURED: 24
    concurrent callers, 24 re-mints handed out, where the answer is one.
  * a rollback beside a restore that already exists — the note was put back and the
    watermark was not, so the two records of one fact disagreed and the recovery refused
    to run.
  * cleaning an address that "clients always send properly". A half-formed one is
    neither addressed nor unaddressed: refused by every reader, parked again, forever.
  * a `> 1` that looks like a `if note_lines`. The difference is the pair-a-computer
    steer for an account with no computer.

⛔ SO THE MUTANTS ARE WEIGHTED TOWARD OVER-CORRECTION AND TOWARD REVERSION: putting the
second clock back, dropping a lock, widening a guard, replacing a three-way outcome with
a two-way one.

⛔⛔ AND THE CONSUMER IS PINNED, NOT ONLY THE HELPER. `claim_signin_announce` is a
helper; `_remint_signin` and the `/updates` route are the product. Mutants C1/C5 leave
the helper perfect and cut the caller's use of it — those must die, or "the helper is
tested" is the only true statement here.

⛔ ANCHOR UNIQUENESS IS CHECKED, NOT ASSUMED, and an equivalent mutant is a harness bug
rather than coverage: `origin = _clean_origin(flow.origin)` occurs twice in bridge.py, so
F1/F2 anchor it together with the line that follows.

⛔ AND A SKIP IS NOT A PASS. pytest exits 0 for a run in which tests were skipped and for
a run that collected far fewer than it should. This runner reads the summary line and
REFUSES a verdict rather than guessing.

    .venv/bin/python .mutants/stretch5b_item2_signin_once_0901_mutants.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BRIDGE = "agent/facade/bridge.py"
PREFS = "agent/facade/prefs.py"
SR = "agent/facade/skill/scripts/sr.py"
POLL = "agent/facade/skill/scripts/sr_attention_poll.py"
MUTATED_FILES = (BRIDGE, PREFS, SR, POLL)

# The agent tree keeps its own pytest rootdir and imports `facade`, so this leg runs
# from `agent/`. The neighbouring route + client suites come along because several
# mutants edit shared seams (the capture path, the /updates row, sr.py's line builders)
# and a harness that ran only the new file would call collateral damage a kill.
AGENT_SUITES = (
    "tests/test_signin_once_0901.py "
    "tests/test_signin_announce_0826.py "
    "tests/test_bridge_device.py "
    "tests/test_bridge_routes.py "
    "tests/test_sr_client.py "
    "tests/test_sr_stream.py"
)
AGENT_FLOOR = 360

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# A survivor is re-run before it is believed: these suites start a real loopback HTTP
# server per test, and a port race would otherwise be reported as a suite gap that does
# not exist. C1/C5 also drop a lock, and a concurrency verdict deserves confirmation.
SURVIVOR_CONFIRMATIONS = 3

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ══ A — one sign-in, one identity ═══════════════════════════════════════
    ("A1", BRIDGE, "under",
     "⛔⛔ THE SECOND CLOCK COMES BACK. The note mints its own `time.time()` a few ms "
     "after the session's capture epoch, so the parked note and the re-mint that "
     "stands in for a lost one carry DIFFERENT identities for the same sign-in — and "
     "the watchdog de-dups by EQUALITY, so it can no longer recognise a re-mint as the "
     "announce it already showed. The person is greeted twice, or not at all",
     [('            "ts": int(getattr(sess, "connected_at_ms", 0) or 0) or int(time.time() * 1000),',
       '            "ts": int(time.time() * 1000),')]),

    ("A2", BRIDGE, "over",
     "⛔ THE FALLBACK IS DROPPED as defensive noise, so a session rehydrated from a "
     "pre-change blob (no capture epoch) mints `ts: 0` — which the watermark reads as "
     "'announced at the epoch' and every later re-mint for that account is suppressed, "
     "permanently",
     [('            "ts": int(getattr(sess, "connected_at_ms", 0) or 0) or int(time.time() * 1000),',
       '            "ts": int(getattr(sess, "connected_at_ms", 0) or 0),')]),

    # ══ B — the claim rolls back with the note ══════════════════════════════
    ("B1", BRIDGE, "under",
     "⛔⛔ THE ROLLBACK GOES AWAY AND THE RESTORE STAYS — the exact asymmetry this fix "
     "closed. The note is claimable again while the watermark says the announce went "
     "out, so the re-mint that exists to recover a lost one refuses to run",
     [('                if marked:\n                    _rollback_announced(sess, mark_prev)',
       '                if False:\n                    _rollback_announced(sess, mark_prev)')]),

    ("B2", BRIDGE, "under",
     "the parked path stops recording that it moved the mark, so the rollback is "
     "written, reachable, and never taken — a fix that exists only in the source",
     [('                        marked, mark_prev = _claim_announced(',
       '                        _ignored, mark_prev = _claim_announced(')]),

    ("B3", BRIDGE, "over",
     "⛔ THE ROLLBACK RESTORES A ZERO instead of what it displaced. Zero is not 'no "
     "mark' — it reads as 'announced at the epoch', so the account is left in exactly "
     "the state the rollback was supposed to undo",
     [('                if marked:\n                    _rollback_announced(sess, mark_prev)',
       '                if marked:\n                    _rollback_announced(sess, 0)')]),

    ("B4", BRIDGE, "under",
     "the re-mint path stops recording its claim, so a re-mint lost to a dropped "
     "connection leaves the watermark advanced and can never be re-derived",
     [('                        out["signedIn"] = remade\n                        taken = None\n'
       '                        marked = True',
       '                        out["signedIn"] = remade\n                        taken = None')]),

    # ══ C — the claim is atomic (measured 24/24 before the fix) ═════════════
    ("C1", PREFS, "under",
     "⛔⛔ THE LOCK COMES OFF THE READ-MODIFY-WRITE. This is the measured defect "
     "itself: 24 concurrent callers each read the same watermark, each pass the "
     "compare, each write — the same sign-in announced 24 times, in 24 chats",
     [('    if not uid:\n        return ("already", None)\n    with _lock:\n'
       '        prefs = load()\n        owner = prefs.get(_ANNOUNCED_SIGNIN_UID)',
       '    if not uid:\n        return ("already", None)\n    if True:\n'
       '        prefs = load()\n        owner = prefs.get(_ANNOUNCED_SIGNIN_UID)')]),

    ("C2", PREFS, "over",
     "⛔ THE COMPARE LOOSENS BY ONE OPERATOR, so a claim for the SAME epoch wins twice "
     "— the announce is repeated for a sign-in that has already been announced, which "
     "is precisely what a watermark is for",
     [('        if seen is not None and int(ms) <= seen:',
       '        if seen is not None and int(ms) < seen:')]),

    ("C3", PREFS, "over",
     "the uid binding is dropped from the read, so a re-login under a DIFFERENT "
     "account is suppressed by the previous owner's watermark and the new person is "
     "never greeted at all",
     [('        seen = (int(raw) if isinstance(raw, (int, float)) and owner == uid else None)',
       '        seen = (int(raw) if isinstance(raw, (int, float)) else None)')]),

    ("C4", PREFS, "over",
     "⛔ THE THREE-WAY OUTCOME COLLAPSES TO TWO: a FIRST observation now reports 'won', "
     "so every account already signed in is greeted once the moment this ships — a "
     "bridge signed in for a week saying hello on its next tick",
     [('        return (("won" if seen is not None else "first"), seen)',
       '        return ("won", seen)')]),

    ("C5", BRIDGE, "under",
     "⛔⛔ THE HELPER STAYS PERFECT AND THE CALLER STOPS USING IT — back to a lockless "
     "read, a compare, and a locked write with the race in between. The atomic claim is "
     "present, tested, and bypassed",
     [('        outcome, prev = prefs.claim_signin_announce(int(cap), sess.uid)',
       '        prev = prefs.get_announced_signin_ms(sess.uid)\n'
       '        outcome = "already" if (prev is not None and int(cap) <= prev) else (\n'
       '            "won" if prev is not None else "first")\n'
       '        prefs.set_announced_signin_ms(int(cap), sess.uid)')]),

    ("C6", BRIDGE, "over",
     "a FIRST observation is treated as a win, so the re-mint speaks for a sign-in that "
     "predates the record — the same greeting-a-week-old-sign-in defect as C4, entered "
     "from the caller instead of the helper",
     [('    if outcome != "won":', '    if outcome == "already":')]),

    # ══ D — `login-done` pays the debt it already claimed to pay ════════════
    ("D1", SR, "under",
     "⛔⛔ `login-done` STOPS TAKING THE NOTE, so it tells the person and leaves the "
     "announce parked for the watchdog to repeat a minute later — and the note is the "
     "only place holding what the bridge DID about their research. The owner's own "
     "fleet transcript is this shape: 'they are signed in' and nothing about the three "
     "computers the note was holding",
     [('        note = _claim_signed_in_announce()\n        note_lines = (_signed_in_lines(note)',
       '        note = {}\n        note_lines = (_signed_in_lines(note)')]),

    ("D2", SR, "under",
     "⛔ THE CHAT SCOPE IS DROPPED FROM THE CLAIM, so the read looks like the "
     "account-wide watchdog and the bridge (correctly) refuses it an ADDRESSED note — "
     "which is the ORDINARY case, because `login` posts this chat's address. The fix "
     "then takes nothing and the double announce survives it",
     [('    q = "/updates?via=agent&limit=1"\n    origin = _origin_from_env()\n    if origin:',
       '    q = "/updates?via=agent&limit=1"\n    origin = None\n    if origin:')]),

    ("D3", SR, "over",
     "⛔⛔ THE OUTCOME GATE WIDENS TO ANY NON-EMPTY NOTE — the tidy simplification, and "
     "it breaks two things at once. A PLAIN sign-in renders the note's one line instead "
     "of the device-aware greeting, so an account with no computer loses the "
     "paste-the-access-code steer; and a TOPIC-ONLY note renders *'Continue with X? Say "
     "go ahead'* — a question aimed at the person — where SKILL.md is written against "
     "*'Continuing your research on X…'* and treats it as the cue to start the run. The "
     "assistant then waits for a go-ahead that was already given",
     [('                      if isinstance(note, dict) and (note.get("autoStarted")\n'
       '                                                     or note.get("needsDevice")\n'
       '                                                     or note.get("needsDeviceChoice"))\n'
       '                      else [])',
       '                      if isinstance(note, dict) and note\n'
       '                      else [])')]),

    ("D5", SR, "under",
     "⛔⛔ `needsDeviceChoice` DROPS OUT OF THE GATE, so the one payload the owner's own "
     "fleet transcript proves was lost — *'you have 3 research computers, which should "
     "run this?'* — is taken and then not relayed. The exact defect, re-entered through "
     "the fix for it",
     [('                                                     or note.get("needsDeviceChoice"))',
       '                                                     or False)')]),

    ("D4", SR, "under",
     "the note is claimed and then not rendered — the debt is taken and not paid, which "
     "is the silent eater this whole line of work exists to end, one function further in",
     [('        note_lines = (_signed_in_lines(note)', '        note_lines = ([]')]),

    # ══ E — the two readers agree about a missing timestamp ═════════════════
    ("E1", POLL, "under",
     "⛔⛔ THE WATCHDOG GOES BACK TO SWALLOWING A NOTE WITH NO TIMESTAMP while `sr "
     "updates` renders the same payload — two readers of one field disagreeing about "
     "whether a timestamp is required to speak. The bridge has already cleared the note "
     "by then, so dropping it destroys the news outright",
     [('        if not new_ts or new_ts != si_ts:',
       '        if new_ts and new_ts != si_ts:')]),

    ("E2", POLL, "over",
     "the cross-tick de-dup is dropped, so the same announce is repeated on every tick "
     "— once a minute, forever, each time as if it were news",
     [('        if not new_ts or new_ts != si_ts:', '        if True:')]),

    ("E3", POLL, "over",
     "⛔ THE EMPTINESS TEST WIDENS, so `{}` — the ABSENCE of a note, not a note missing "
     "a timestamp — is announced as a bare '✓ Signed in' for a sign-in that never "
     "happened",
     [('    if isinstance(signed_in, dict) and signed_in:',
       '    if isinstance(signed_in, dict):')]),

    # ══ F — a half-formed address is not a dead letter ═════════════════════
    ("F1", BRIDGE, "under",
     "⛔⛔ THE ADDRESS IS STORED RAW AGAIN. A half-formed origin ({platform} with no "
     "chat_id) is then neither ADDRESSED (no chat to match) nor UNADDRESSED (the origin "
     "is truthy), so every reader takes it, fails the gate, and parks it again — a dead "
     "letter forever, and the re-mint never runs either because the note is still there",
     [('        origin = _clean_origin(flow.origin)\n        base_ev = {',
       '        origin = flow.origin if isinstance(flow.origin, dict) else None\n'
       '        base_ev = {')]),

    ("F2", BRIDGE, "over",
     "the cleaning flattens EVERY address to anonymous, so a chat-initiated sign-in is "
     "handed to whichever watcher polls first — the wrong-chat bug, arriving through "
     "the fix for the dead letter",
     [('        origin = _clean_origin(flow.origin)\n        base_ev = {',
       '        origin = None\n        base_ev = {')]),
]


def sh(args, **kw):
    return subprocess.run(args, cwd=kw.pop("cwd", ROOT), capture_output=True,
                          text=True, env=kw.pop("env", ENV), **kw)


def purge_pycache():
    """⛔ STALE BYTECODE HAS FAKED THREE ROUNDS OF MEASUREMENT IN THIS REPO BEFORE."""
    for d in (ROOT / "agent", ROOT / "tests"):
        if not d.exists():
            continue
        for p in d.rglob("__pycache__"):
            shutil.rmtree(p, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *MUTATED_FILES,
              "agent/tests", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERRORS = re.compile(r"(\d+) error")
_SKIPPED = re.compile(r"(\d+) skipped")


def _verdict(proc, floor: int, label: str):
    """(green, refusal). ⛔ A SKIP IS THE ABSENCE OF A MEASUREMENT, and pytest exits 0
    for a run that collected almost nothing. Refuse rather than guess."""
    tail = (proc.stdout or "")[-3000:] + (proc.stderr or "")[-1500:]
    passed, failed = _PASSED.search(tail), _FAILED.search(tail)
    errors, skipped = _ERRORS.search(tail), _SKIPPED.search(tail)
    if not passed and not failed:
        return None, f"{label}: pytest printed no counts — the run did not happen: {tail[-300:]!r}"
    if skipped:
        return None, f"{label}: {skipped.group(1)} test(s) SKIPPED — a skip is not a pass"
    n = int(passed.group(1) if passed else 0) + int(failed.group(1) if failed else 0)
    if n < floor:
        return None, (f"{label}: only {n} tests collected, expected at least {floor}"
                      " — the run measured something other than this suite")
    return proc.returncode == 0 and not failed and not errors, None


def run_tests(_files_touched=()):
    purge_pycache()
    agent_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
    proc = sh([sys.executable, "-B", "-m", "pytest", *AGENT_SUITES.split(),
               "-q", "-p", "no:cacheprovider"],
              cwd=ROOT / "agent", env=agent_env)
    green, refuse = _verdict(proc, AGENT_FLOOR, "agent")
    if refuse:
        return None, refuse
    return green, None


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    only = {a for a in sys.argv[1:] if not a.startswith("-")}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if only and len(selected) != len(only):
        print(f"unknown mutant id(s): {only - {m[0] for m in selected}}")
        return 2

    print("baseline… ", end="", flush=True)
    green, refuse = run_tests()
    if refuse:
        print(f"REFUSED: {refuse}")
        return 2
    if not green:
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    survivors = []
    for mid, fname, direction, why, edits in selected:
        path = ROOT / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                # ⛔ EXACTLY ONE. A stale anchor measured nothing and would still
                # report a kill; a duplicated one mutates a place nobody meant.
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                    "check the anchor's indentation") from None
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            green, refuse = run_tests()
            if refuse:
                raise AssertionError(f"verdict refused — {refuse}")
            killed = not green
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                green, refuse = run_tests()
                if refuse:
                    raise AssertionError(f"verdict refused — {refuse}")
                killed = not green
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}", flush=True)
            survivors.append((mid, direction, f"STALE ANCHOR — measured nothing ({exc})"))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed "
          f"({over} over-corrections)")
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
