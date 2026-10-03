"""Mutation harness — wave 15 (10-03), the review's two repairs to Gemini's
plan Redo and research refresh.

⛔⛔ WHAT THIS CODE DECIDES (research.py) — the lines the repair added.
  C*  the research card is a LINE OF ITS OWN (`_GEMINI_RESEARCH_CARD_LINE_RE`):
      a plan that says "researching sources" mid-sentence is still a plan, so
      the watch presses its 'Start research', the refresh never reloads it, a
      crash rejoin reads 'plan' and a person's Retry presses Start. Both
      research reads (`_gemini_research_started`, `_gemini_research_surface`)
      use it; spaces before the card are allowed.
  B*  one budget of two Redo presses per chat: the send step's press
      (`_gemini_retry_failed_turn`, noted by the chat's tab) counts in the plan
      wait and the round-robin, with its time for the 45 s between presses; a
      new chat on the same tab starts at zero; the plan wait hands on only its
      own presses; the tile says the total.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/gemini_redo_review_1003_mutants.py
  .venv/bin/python .mutants/gemini_redo_review_1003_mutants.py C1 B4
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

#: Each group's measuring tests (names, never paths with a ".py" the anchor
#: sweep would read as a target: it reads any "*.py" string in a ROW).
_T = "tests/test_"
SUITES = {
    "card": (_T + "w15_gemini_redo_1003" + ".py", _T + "gemini_stale_reload_0918" + ".py"),
    "budget": (_T + "w15_gemini_redo_1003" + ".py",),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ── C: the research card is a line of its own ───────────────────────────
    ("C1", RESEARCH, "card", "⛔⛔ the card's words anywhere — a plan that says 'researching sources' reads as started",
     [("    r\"^[^\\S\\n]*(?:\" + _GEMINI_RESEARCH_CARD_RE.pattern + r\")\",\n",
       "    r\"(?:\" + _GEMINI_RESEARCH_CARD_RE.pattern + r\")\",\n")]),
    ("C2", RESEARCH, "card", "⛔⛔ only the first line of the page counts — the card is never seen",
     [("    re.IGNORECASE | re.MULTILINE)\n", "    re.IGNORECASE)\n")]),
    ("C3", RESEARCH, "card", "⛔ a card line with spaces before it is missed",
     [("    r\"^[^\\S\\n]*(?:\" + _GEMINI_RESEARCH_CARD_RE.pattern + r\")\",\n",
       "    r\"^(?:\" + _GEMINI_RESEARCH_CARD_RE.pattern + r\")\",\n")]),
    ("C4", RESEARCH, "card", "⛔⛔ the watch, a Retry and a rejoin take the plan's words for the card",
     [("    return bool(_GEMINI_RESEARCH_CARD_LINE_RE.search(body)\n",
       "    return bool(_GEMINI_RESEARCH_CARD_RE.search(body)\n")]),
    ("C5", RESEARCH, "card", "⛔⛔ the refresh takes the plan's words for the card — a planning chat reloaded",
     [("    return (bool(_GEMINI_RESEARCH_CARD_LINE_RE.search(body)),\n",
       "    return (bool(_GEMINI_RESEARCH_CARD_RE.search(body)),\n")]),

    # ── B: one budget of two Redo presses per chat ──────────────────────────
    ("B1", RESEARCH, "budget", "⛔⛔ the send step's press is not noted — three presses on one chat",
     [("                _gemini_send_redo_note(page)\n", "                pass\n")]),
    ("B2", RESEARCH, "budget", "⛔⛔ the send step's press is noted as nothing — three presses",
     [("        _GEMINI_SEND_REDOS[page] = (n + 1, time.time())\n",
       "        _GEMINI_SEND_REDOS[page] = (n, time.time())\n")]),
    ("B3", RESEARCH, "budget", "⛔ the send step's press has no time — the next press at once, not 45 s later",
     [("        _GEMINI_SEND_REDOS[page] = (n + 1, time.time())\n",
       "        _GEMINI_SEND_REDOS[page] = (n + 1, 0.0)\n")]),
    ("B4", RESEARCH, "budget", "⛔ a new chat on a reused tab inherits the last chat's presses",
     [("            _gemini_send_redos_new_chat(page)\n"
       "            retried = await _gemini_retry_failed_turn(page, label, max_wait_s=90)\n",
       "            retried = await _gemini_retry_failed_turn(page, label, max_wait_s=90)\n")]),
    ("B5", RESEARCH, "budget", "⛔ the new chat's clear clears nothing",
     [("        _GEMINI_SEND_REDOS.pop(page, None)\n", "        _GEMINI_SEND_REDOS.get(page, None)\n")]),
    ("B6", RESEARCH, "budget", "⛔⛔ the count leaves out the send step's press — three presses",
     [("    return (int(state.get(\"gemini_plan_redos\", 0) or 0) + sent,\n",
       "    return (int(state.get(\"gemini_plan_redos\", 0) or 0),\n")]),
    ("B7", RESEARCH, "budget", "⛔ the 45 s leave out the send step's press — the second press at once",
     [("            max(float(state.get(\"gemini_plan_redo_at\", 0.0) or 0.0), sent_at))\n",
       "            float(state.get(\"gemini_plan_redo_at\", 0.0) or 0.0))\n")]),
    ("B8", RESEARCH, "budget", "⛔⛔ the plan's Redo look counts only its own presses — three presses",
     [("        n, last_at = _gemini_plan_redos_spent(page, state)\n",
       "        n, last_at = _gemini_plan_redos_spent(None, state)\n")]),
    ("B9", RESEARCH, "budget", "the plan wait hands on the send step's press as its own — counted twice",
     [("    state[\"gemini_plan_redos\"] = int(state.get(\"gemini_plan_redos\", 0) or 0) + 1\n",
       "    state[\"gemini_plan_redos\"] = n + 1\n")]),
    ("B10", RESEARCH, "budget", "the tile says '1 of 2' for the chat's second press",
     [("{_gemini_plan_redos_spent(gemini_page, _plan_redo)[0]} of ",
       "{_plan_redo['gemini_plan_redos']} of ")]),
]


def green(tests) -> bool:
    try:
        r = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-x",
                            "-p", "no:cacheprovider", *tests],
                           cwd=str(ROOT), env=ENV, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
    except subprocess.TimeoutExpired:
        return False
    out = r.stdout + r.stderr
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too, and a
    # skipped test is not a measurement.
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
    for group in sorted({m[2] for m in MUTANTS}):
        suites = SUITES[group]
        if not green(suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, group, why, edits in selected:
        suites = SUITES[group]
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
            if green(suites):
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}", flush=True)
            else:
                print(f"  {mid:4} ✓ killed", flush=True)
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}", flush=True)
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
