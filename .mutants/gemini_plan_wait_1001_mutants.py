"""Mutation harness — Gemini's plan wait: nothing raised for ten minutes, and a
quiet chat refreshed, always on the run's own chat (2026-10-01).

⛔⛔ WHAT THIS CODE DECIDES (research.py).
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
SUITES = {
    RESEARCH: (ROOT, "tests/test_gemini_plan_wait_1001.py -x"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ── W1-W3: the clock ────────────────────────────────────────────────────
    ("W1", RESEARCH, "⛔⛔ the floor goes — three spent re-drafts card about four "
     "minutes in again, before the owner's ten",
     [("    if elapsed < float(wait_max_sec):\n        return False\n", "")]),
    ("W2", RESEARCH, "⛔⛔ the wait is five minutes again — the card and the vision "
     "step at ~300 s",
     [('os.environ.get("GEMINI_PLAN_WAIT_SEC", str(10 * 60))',
       'os.environ.get("GEMINI_PLAN_WAIT_SEC", str(5 * 60))')]),
    ("W3", RESEARCH, "⛔ a refresh after one quiet minute, not two",
     [('os.environ.get("GEMINI_PLAN_REFRESH_SEC", "120")',
       'os.environ.get("GEMINI_PLAN_REFRESH_SEC", "60")')]),

    # ── W4-W10: when ────────────────────────────────────────────────────────
    ("W4", RESEARCH, "⛔⛔ the quiet chat is never refreshed — the 09-30 silent "
     "screen sits untouched to the card",
     [("            if _gemini_plan_refresh_due(time.time(), quiet_since=_quiet_since,",
       "            if False and _gemini_plan_refresh_due(time.time(), quiet_since=_quiet_since,")]),
    ("W5", RESEARCH, "⛔⛔ growing text reads as quiet — a reply still being written "
     "is refreshed",
     [("    return reply_len == last_reply_len\n", "    return True\n")]),
    ("W6", RESEARCH, "⛔⛔ the page reading is not asked — Gemini 'still working' "
     "(its hidden Stop) is refreshed",
     [('    if not str(state_reason or "").startswith("no_done_marker"):\n'
       '        return False\n', "")]),
    ("W7", RESEARCH, "⛔ a plan already on the page is refreshed",
     [("    if not reply_found or reply_len > _GEMINI_PLAN_FAIL_MAX_CHARS:",
       "    if not reply_found:")]),
    ("W8", RESEARCH, "⛔ a reply that could not be read reads as quiet",
     [("    if not reply_found or reply_len > _GEMINI_PLAN_FAIL_MAX_CHARS:",
       "    if reply_len > _GEMINI_PLAN_FAIL_MAX_CHARS:")]),
    ("W9", RESEARCH, "⛔⛔ no limit between loads — a tab that cannot be proven is "
     "loaded on every look",
     [("    return w > 0 and (now - quiet_since) >= w and (now - last_refresh_at) >= w",
       "    return w > 0 and (now - quiet_since) >= w")]),
    ("W10", RESEARCH, "⛔ a page quiet for exactly the window waits one more look",
     [("    return w > 0 and (now - quiet_since) >= w and (now - last_refresh_at) >= w",
       "    return w > 0 and (now - quiet_since) > w and (now - last_refresh_at) >= w")]),
    ("W20", RESEARCH, "⛔ what the heartbeat sees moving no longer holds the refresh off",
     [('                        _chat["quiet_since"] = _last_stream_seen_at\n', "")]),
    ("W21", RESEARCH, "⛔ a refresh can cut into a re-draft we pressed a moment ago",
     [('            _quiet_since = max(_chat["quiet_since"], _last_regen_at)',
       '            _quiet_since = _chat["quiet_since"]')]),

    # ── W11-W26: which chat ─────────────────────────────────────────────────
    ("W11", RESEARCH, "⛔⛔ the address is taken from the address bar alone — a chat "
     "holding another brief becomes 'ours' and is refreshed",
     [("        if here and await _gemini_reload_identity_ok(page, here, brief, attempts=1):",
       "        if here:")]),
    ("W12", RESEARCH, "⛔⛔ a drift is not noticed — the other chat's 'Start research' "
     "is pressed",
     [('    else:\n        chat["trusted"] = False\n',
       '    else:\n        return True\n')]),
    ("W13", RESEARCH, "⛔⛔ a loaded page is believed without the proof — another "
     "brief's plan is started",
     [("    ok = await _gemini_reload_identity_ok(page, ours, brief)\n",
       "    ok = True\n")]),
    ("W14", RESEARCH, "⛔⛔ a page that is not provably ours is still read and pressed "
     "by the wait",
     [("            if not _chat_ok:\n                # Not provably the run's chat",
       "            if False:\n                # Not provably the run's chat")]),
    ("W15", RESEARCH, "⛔ a refresh that could not be proven goes on to press on the "
     "same look",
     [("                    if not await _gemini_plan_refresh(\n",
       "                    if 0 * await _gemini_plan_refresh(\n")]),
    ("W16", RESEARCH, "⛔⛔ the recovery runs on a tab that is not provably ours — "
     "computer use and presses on somebody else's chat",
     [("                and not _finished_handoff and not _controls.is_stop()\n"
       "                and _chat_ok):",
       "                and not _finished_handoff and not _controls.is_stop()):")]),
    ("W17", RESEARCH, "⛔⛔ Gemini's bare /app is refreshed before the chat has an "
     "address — the chat is lost",
     [('                if _chat["convo"]:\n', "                if True:\n")]),
    ("W18", RESEARCH, "⛔ going back never uses Gemini's side list — always the "
     "address load the 2026-07 finding warns about",
     [("            pressed = bool(await page.evaluate(_GEMINI_OPEN_CHAT_JS, ours))",
       "            pressed = False")]),
    ("W19", RESEARCH, "⛔ with no side-list entry there is no way back",
     [('await page.goto(chat.get("url") or "",', 'await page.goto("",')]),
    ("W22", RESEARCH, "⛔⛔ a drifted tab is refreshed in place — the wrong chat is "
     "reloaded instead of going back to ours",
     [('    if _gemini_convo_url_id(here) == ours:\n        log(f"[2D] {why}',
       '    if True:\n        log(f"[2D] {why}')]),
    ("W23", RESEARCH, "⛔⛔ a tab back on our address is believed without a proof — "
     "after a load that could not be proven, its plan is pressed",
     [('        if chat.get("trusted", True):\n            return True',
       '        if True:\n            return True')]),
    ("W24", RESEARCH, "⛔⛔ a drifted tab is read while it waits to go back — another "
     "chat's finished report is taken for this run's",
     [("                                           if _chat_ok else (False, _gemini_state))",
       "                                           if True else (False, _gemini_state))")]),
    ("W26", RESEARCH, "⛔ the side-list press takes the first chat it sees, not ours",
     [(".endsWith('/app/' + id)) {", ".includes('/app/')) {")]),
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
