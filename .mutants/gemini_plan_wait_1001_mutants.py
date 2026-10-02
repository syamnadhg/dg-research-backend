"""Mutation harness — Gemini's plan wait: nothing raised for ten minutes, and a
quiet chat refreshed, always on the run's own chat (2026-10-01).

⛔⛔ WAVE 15 (10-02): THE REFRESH, THE CARD, THE RECOVERY AND THE SIX-MINUTE
HAND-OFF ARE GONE, and their rows with them. What is left: the ten-minute wait
(W2) and which chat is believed (W11-W39 that still stand). The new behaviour —
nothing reloaded, pressed or raised; Gemini handed on watched — is measured by
.mutants/w15_crash_gemini_1002_mutants.py.

⛔⛔ WHAT THIS CODE DECIDED (research.py, before wave 15).
  W1-W3   — the clock: no card before the wait is over (three spent re-drafts
            included), the wait is ten minutes, a refresh needs two quiet ones.
  W4-W10  — when the chat is refreshed: only after a window of nothing new — no
            moving part, no plan, no growing text, nothing the heartbeat sees
            moving, no re-draft of ours just pressed — and at most one load per
            window.
  W11-W26 — which chat: the address is taken only once the page proves it is
            ours; a tab anywhere else is not believed and goes back (side list
            first, address second), never refreshed in place; a page that cannot
            be proven after a load is never pressed — not by the wait, not by the
            recovery after it.
  W27-W39 — review round 1: a chat Gemini moves to a new address is followed
            (never an earlier attempt's finished one); a visible Stop is
            "still working" for the #953 hand-off; the alert follows the wait;
            the tile hears from the wait on an unproven tab; /u/<n>/app/ is a
            chat address; before the address is taken, a chat holding another
            brief is not believed (and "cannot tell" still is).

⛔ DELIBERATELY ABSENT: the alert default (600 → 240). The card predicate refuses
every arm before the wait is over, so an alert second at or under the wait
cannot change anything — that mutant is equivalent, and an equivalent mutant is
a harness bug.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔⛔ AN IN-FLIGHT MARKER, because Windows kills without running `finally:` or a
SIGTERM handler. Run this in a throwaway worktree, never in the checkout the
backend runs from.

  python .mutants/gemini_plan_wait_1001_mutants.py
  python .mutants/gemini_plan_wait_1001_mutants.py W1 W12
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

# `-x`: a kill needs one red test, and every run drives headless Chrome.
# Wave 15: + the file that measures the wait as it is now (it uses this file's
# fixture), so W2 and the hand-off it ends in are still measured.
SUITES = {
    RESEARCH: (ROOT, "tests/test_gemini_plan_wait_1001.py "
                     "tests/test_w15_gemini_waits_1002.py -x"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ── the clock ───────────────────────────────────────────────────────────
    # ⛔ W1, W3-W10, W13, W15-W22, W26, W28 and W31-W33 RETIRED in wave 15
    # (10-02), not re-anchored: they measured the quiet-chat refresh, the card,
    # the computer-use recovery and the six-minute hand-off, all removed by the
    # owner's decision ("wait for the research without refreshing").
    ("W2", RESEARCH, "⛔⛔ the wait is five minutes again — Gemini is handed on at "
     "~300 s instead of the owner's ten minutes",
     [('os.environ.get("GEMINI_PLAN_WAIT_SEC", str(10 * 60))',
       'os.environ.get("GEMINI_PLAN_WAIT_SEC", str(5 * 60))')]),
    # ── W4-W10: when ────────────────────────────────────────────────────────
    # ── W11-W26: which chat ─────────────────────────────────────────────────
    ("W11", RESEARCH, "⛔⛔ the address is taken from the address bar alone — a chat "
     "holding another brief becomes 'ours' and is refreshed",
     [("        if here and await _gemini_reload_identity_ok(page, here, brief, attempts=1):",
       "        if here:")]),
    ("W12", RESEARCH, "⛔⛔ a drift is not noticed — the other chat's 'Start research' "
     "is pressed",
     [('    else:\n        chat["trusted"] = False\n',
       '    else:\n        return True\n')]),
    ("W14", RESEARCH, "⛔⛔ a page that is not provably ours is still read and pressed "
     "by the wait",
     [("            if not _chat_ok:\n                # Not provably the run's chat",
       "            if False:\n                # Not provably the run's chat")]),
    ("W23", RESEARCH, "⛔⛔ a tab back on our address is believed without a proof — "
     "after a load that could not be proven, its plan is pressed",
     [('        if chat.get("trusted", True):\n            return True',
       '        if True:\n            return True')]),
    ("W24", RESEARCH, "⛔⛔ a drifted tab is read while it waits to go back — another "
     "chat's finished report is taken for this run's",
     [("                                           if _chat_ok else (False, _gemini_state))",
       "                                           if True else (False, _gemini_state))")]),
    # ── W27-W39: review round 1 ─────────────────────────────────────────────
    ("W27", RESEARCH, "⛔⛔ the owner's 10-01 run: Gemini moves the run's chat to a "
     "new address and it is called a drift — Start is never pressed",
     [("    elif await _gemini_plan_follow(page, chat, url, brief):\n"
       "        return True\n", "")]),
    ("W29", RESEARCH, "⛔⛔ an earlier attempt's FINISHED chat (same brief) is "
     "followed — its report taken for this run's",
     [("    if (await _gemini_done_read(page))[0]:\n        return False\n"
       '    chat["convo"], chat["url"], chat["trusted"] = here, url, True',
       '    chat["convo"], chat["url"], chat["trusted"] = here, url, True')]),
    ("W30", RESEARCH, "⛔⛔ any other address is followed without the proof — "
     "another chat's Start is pressed",
     [("    if not await _gemini_reload_identity_ok(page, here, brief):\n"
       "        return False\n", "")]),
    ("W34", RESEARCH, "⛔ the tile hears nothing while the tab is not provably ours",
     [("                if time.time() - _last_plan_emit >= 15:\n"
       "                    try:\n"
       '                        emit_event("agent_progress"',
       "                if False:\n"
       "                    try:\n"
       '                        emit_event("agent_progress"')]),
    ("W35", RESEARCH, "⛔ the log says nothing while the tab is not provably ours",
     [('                log(f"[2D] Still waiting for Gemini research plan... '
       '({_elapsed}s / "\n',
       '                (f"[2D] Still waiting for Gemini research plan... '
       '({_elapsed}s / "\n')]),
    ("W36", RESEARCH, "⛔ a chat under /u/<n>/app/ has no address — never refreshed",
     [("gemini\\.google\\.com/(?:u/\\d+/)?app/", "gemini\\.google\\.com/app/")]),
    ("W37", RESEARCH, "⛔⛔ before the address is taken, another brief's chat is "
     "believed — its Start is pressed",
     [("_gemini_conversation_ownership(txt, brief, from_turn=from_turn) is False:",
       "False:")]),
    ("W38", RESEARCH, "⛔⛔ 'cannot tell' is read as somebody else's chat — a page "
     "that has not painted its turn is not believed",
     [("_gemini_conversation_ownership(txt, brief, from_turn=from_turn) is False:",
       "_gemini_conversation_ownership(txt, brief, from_turn=from_turn) is not True:")]),
    ("W39", RESEARCH, "⛔ Gemini's own page text condemns a chat whose turn could "
     "not be read",
     [("_gemini_conversation_ownership(txt, brief, from_turn=from_turn) is False:",
       "_gemini_conversation_ownership(txt, brief, from_turn=True) is False:")]),
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
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
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
            _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")
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
            if _digest(path.read_bytes()) == DIGESTS[fname]:
                try:
                    _INFLIGHT.unlink()
                except FileNotFoundError:
                    pass

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
