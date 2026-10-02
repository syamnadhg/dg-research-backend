"""Mutation harness — computer use only where it helps (the 09-30 run, round 1).

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  S* — computer-use scrolling goes in the direction and by the amount the model
       asks for (`scroll_direction` / `scroll_amount`).
  P* — Phase 2: while the page shows Stop, ChatGPT and Claude get no computer-use
       completion check, and the check clock moves forward; Gemini keeps it.
  G* — Gemini's plan wait: Skip stops the vision step at once; a reply with
       nothing to click gets no vision step (the Start watch still runs); the log
       says what the page shows about Gemini, and the landing line names the chat
       and the seconds after Send.
  C* — the end-of-run summary counts every computer-use session and vision read
       by phase, platform and purpose — Phase 0's sign-in and subscription-tier
       screen checks included.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔⛔ AN IN-FLIGHT MARKER, because Windows kills without running `finally:` or a
SIGTERM handler. Run this in a throwaway worktree, never in the checkout the
backend runs from.

  python .mutants/cua_general_e2e0930_mutants.py
  python .mutants/cua_general_e2e0930_mutants.py S1 G3
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

SUITES = {
    RESEARCH: (ROOT, "tests/test_cua_scroll_e2e0930.py "
                     "tests/test_p2_stop_skips_cua_e2e0930.py "
                     "tests/test_gemini_2d_cua_e2e0930.py "
                     "tests/test_cua_summary_e2e0930.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ── S: scrolling ────────────────────────────────────────────────────────
    ("S1", RESEARCH, "⛔⛔ the tool's own direction key is not read — every scroll goes "
     "down again (all 71 logged scrolls)",
     [('            d = params.get("scroll_direction") or params.get("direction") or "down"\n',
       '            d = params.get("direction") or "down"\n')]),
    ("S2", RESEARCH, "⛔ the tool's own amount key is not read — every scroll moves 3",
     [('            a = params.get("scroll_amount") or params.get("amount") or 3\n',
       '            a = params.get("amount") or 3\n')]),

    # ── P: Phase 2, Stop decides ────────────────────────────────────────────
    ("P1", RESEARCH, "⛔⛔ a Stop read no longer skips the check — one screenshot per "
     "five minutes per agent that only ever says 'still going'",
     [('                    and str(dom_reason or "").startswith("stop_btn_present")):\n',
       '                    and False):\n')]),
    ("P2", RESEARCH, "⛔ the clock is not moved forward — the first read without Stop "
     "gets a screenshot at once",
     [('                    and str(dom_reason or "").startswith("stop_btn_present")):\n'
       '                p["last_cua_check"] = time.time()\n',
       '                    and str(dom_reason or "").startswith("stop_btn_present")):\n')]),
    ("P3", RESEARCH, "⛔ Gemini loses its five-minute check too",
     [('            if (detect_fn is not None and name in ("ChatGPT", "Claude")\n',
       '            if (detect_fn is not None and name in ("ChatGPT", "Claude", "Gemini")\n')]),

    # ── G: Gemini's plan wait ───────────────────────────────────────────────
    # G1-G6 measured the computer-use recovery after the plan wait (its
    # Skip tripwire, its 'nothing to click' rule, its Start watch);
    # removed with it in wave 15 (10-02).
    ("G7", RESEARCH, "⛔ what the page shows about Gemini is never logged",
     [('            if _gemini_state.split(" (", 1)[0] != _gemini_state_logged:\n',
       '            if False:\n')]),
    # G8 (the stall line) went with the stall line in wave 15.
    ("G9", RESEARCH, "⛔ a hidden 'Stop response' reads as 'unknown', not 'still working'",
     [('    ("running_hidden_stop_btn",\n',
       '    ("running_hidden_stop_btn_x",\n')]),
    ("G10", RESEARCH, "⛔ the Send stamp moves after the 3 s pause — the landing time "
     "under-reads",
     [("    _sent_at = time.time()\n    await asyncio.sleep(3)\n",
       "    await asyncio.sleep(3)\n    _sent_at = time.time()\n")]),
    ("G11", RESEARCH, "⛔ the confirmed line names no chat and no landing time",
     [('        log(f"[{label}] Gemini submission confirmed ✓ (conversation started)"\n'
       '            + _gemini_landing_note())\n',
       '        log(f"[{label}] Gemini submission confirmed ✓ (conversation started)")\n')]),

    # ── C: the computer-use count ───────────────────────────────────────────
    ("C1", RESEARCH, "⛔ sessions are counted with no steps",
     [('        _cua_rec["steps"] = iteration\n', '')]),
    ("C2", RESEARCH, "⛔⛔ the call site's step name is not passed down — every session "
     "reads 'other'",
     [("    cua_coro_factory = _cua_tagged(cua_coro_factory, phase=phase, platform=platform,\n"
       "                                   purpose=current_step)\n",
       "    cua_coro_factory = cua_coro_factory\n")]),
    ("C3", RESEARCH, "⛔ a call site's step name leaks onto the next session",
     [("            _CUA_TAG.reset(token)\n", "            pass\n")]),
    ("C4", RESEARCH, "⛔⛔ the end-of-run summary prints no count",
     [('    _cua_summary(tag)\n    return {"total": total, "ok": len(ok), "missed": len(missed)}\n',
       '    return {"total": total, "ok": len(ok), "missed": len(missed)}\n')]),
    ("C5", RESEARCH, "⛔ a run with no DOM attempts prints no count",
     [('        _cua_summary(tag)\n        return {"total": 0, "ok": 0, "missed": 0}\n',
       '        return {"total": 0, "ok": 0, "missed": 0}\n')]),
    ("C6", RESEARCH, "⛔ a new run carries the last run's count",
     [("    _DOM_ATTEMPTS.clear()\n    _cua_reset()\n", "    _DOM_ATTEMPTS.clear()\n")]),
    ("C7", RESEARCH, "⛔ the source-link screen read is not counted",
     [('    _cua_open("vision", platform=agent_key, purpose="read source links off the screen")\n',
       '')]),
    ("C8", RESEARCH, "⛔ a vision step that acts is not counted",
     [('            _cua_open("vision", phase=phase, platform=platform, purpose=current_step)\n',
       '')]),
    ("C9", RESEARCH, "⛔ Phase 0's sign-in screen checks are not counted",
     [('    _cua_open("vision", phase=0, platform=platform, purpose="check sign-in")\n',
       '')]),
    ("C10", RESEARCH, "⛔ Phase 0's subscription-tier screen checks are not counted",
     [('    _cua_open("vision", phase=0, platform=platform, purpose="check subscription tier")\n',
       '')]),
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
