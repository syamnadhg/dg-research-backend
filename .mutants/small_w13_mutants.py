"""Mutation harness — Wave 13's smaller fixes from the 0.1.13 logs (2026-09-29).

⛔⛔ WHAT THIS CODE DECIDES.
  E* — the vision step never sends an empty picture. A busy page's screenshot
       timed out twice, the "" went to Anthropic as an image, the whole request
       came back 400 ("image cannot be empty") and the step ended. Every picture
       after the first now goes through one helper: an empty one is taken once
       more, then the model is told in words. Five places send a picture; each
       is driven by the real agent_loop.

⛔ NO SOURCE PIN SITS IN THE TEST SET. Every mutant here must die on behaviour:
the real agent_loop, Browser.screenshot and execute_action.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  .venv/bin/python .mutants/small_w13_mutants.py
  .venv/bin/python .mutants/small_w13_mutants.py E1 E4
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

TESTS = ["tests/test_cua_empty_screenshot_0929.py"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

_IMG_OLD = ('{"type": "image", "source": {"type": "base64", "media_type": "image/png", '
            '"data": await _anchored_screenshot()}}')

MUTANTS = [
    # ═══ E — never an empty picture ═════════════════════════════════════════
    ("E1", RESEARCH, "⛔ no second try — a screenshot that would have worked the "
     "second time is replaced by words",
     [("        if not ss:\n            ss = await _anchored_screenshot()\n", "")]),
    ("E2", RESEARCH, "⛔⛔ the empty picture is sent anyway — Anthropic refuses the "
     "request and the step ends",
     [("        if ss:\n            return {\"type\": \"image\", \"source\": {\"type\": "
       "\"base64\", \"media_type\": \"image/png\",\n"
       "                                                \"data\": ss}}",
       "        if True:\n            return {\"type\": \"image\", \"source\": {\"type\": "
       "\"base64\", \"media_type\": \"image/png\",\n"
       "                                                \"data\": ss}}")]),
    ("E3", RESEARCH, "a fresh picture is never taken first — the places that need a new "
     "screenshot get only one try",
     [("        if ss is None:\n            ss = await _anchored_screenshot()\n", "")]),
    ("E4", RESEARCH, "⛔ the 'you seem stuck' hint sends the raw screenshot again",
     [("                    {\"type\": \"text\", \"text\": \"You seem stuck. Try a different "
       "approach.\"},\n                    await _screen_block(),\n",
       "                    {\"type\": \"text\", \"text\": \"You seem stuck. Try a different "
       "approach.\"},\n                    " + _IMG_OLD + ",\n")]),
    ("E5", RESEARCH, "⛔ a screenshot the model asked for is sent raw",
     [("                    \"content\": [await _screen_block()]})",
       "                    \"content\": [" + _IMG_OLD + "]})")]),
    ("E6", RESEARCH, "⛔ the picture after a refused action is sent raw",
     [("f\"may only use: {_may}. Do not type or press Enter.\"},\n"
       "                    await _screen_block(),\n",
       "f\"may only use: {_may}. Do not type or press Enter.\"},\n"
       "                    " + _IMG_OLD + ",\n")]),
    ("E7", RESEARCH, "⛔ the picture after a refused click on Send is sent raw",
     [("\"clicked Send. Click inside the message box itself, never on Send.\"},\n"
       "                    await _screen_block(),\n",
       "\"clicked Send. Click inside the message box itself, never on Send.\"},\n"
       "                    " + _IMG_OLD + ",\n")]),
    ("E8", RESEARCH, "⛔⛔ the picture after an action is sent raw — the 09-29 site",
     [("                    await _screen_block(ss),\n",
       "                    {\"type\": \"image\", \"source\": {\"type\": \"base64\", "
       "\"media_type\": \"image/png\", \"data\": ss}},\n")]),
    ("E9", RESEARCH, "OVER-REACH: every picture is taken twice — a good screenshot "
     "costs a second capture on every step",
     [("        if not ss:\n            ss = await _anchored_screenshot()\n",
       "        if True:\n            ss = await _anchored_screenshot()\n")]),
    ("E10", RESEARCH, "the missing picture leaves no line in the log",
     [("        log(\"[cua] The page did not give a screenshot twice in a row (it is busy) — \"\n"
       "            \"telling the vision model in words instead of sending an empty picture\", "
       "\"WARN\")\n", "")]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, tests):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider", "-rs"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    ok = (re.search(r"\b\d+ (failed|errors?)\b", out) is None
          and re.search(r"\b\d+ passed\b", out) is not None)
    return ok, out


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    # ⛔ UTF-8 OUT (Windows review, 2026-09-29): a redirected run on Windows has a
    # cp1252 stdout, and the first "✓ killed" raised UnicodeEncodeError.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # ⛔⛔ AN IN-FLIGHT MARKER (Windows review, 2026-09-29). Windows ends a process
    # with TerminateProcess — no SIGTERM handler, no `finally:` — so a killed run
    # left a mutant in research.py silently. Now it leaves this file naming the
    # file that holds one, and the next run refuses to start until it is restored.
    # Run harnesses in a throwaway worktree, never in the live checkout.
    _INFLIGHT = Path(__file__).with_suffix(".inflight")
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    # ⛔ A SIGTERM MUST RESTORE TOO: Python's default SIGTERM skips `finally:`.
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    unknown = only - {m[0] for m in MUTANTS}
    if unknown:
        print(f"no such mutant: {', '.join(sorted(unknown))}")
        sys.exit(2)
    print("baseline… ", end="", flush=True)
    ok, out = green(ROOT, TESTS)
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.\n" + out[-2000:])
        sys.exit(2)
    if re.search(r"\b\d+ skipped\b", out):
        print("⛔ BASELINE SKIPPED TESTS — the real-Chrome tests did not run here, so "
              "no kill below would mean anything.\n" + out[-1500:])
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
            ok, _out = green(ROOT, TESTS)
            if ok:
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
