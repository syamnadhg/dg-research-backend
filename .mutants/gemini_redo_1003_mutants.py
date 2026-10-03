"""Mutation harness — wave 15 (10-03): Gemini's own Redo on a failed plan, never a
refresh while it plans; the research refresh sees the research on a real page.

THE OWNER, 10-03: "if the planning fails and if it shows some message and a redo
option, we will try redo, but we are not refreshing … refresh during the
research is going … and even after finishing the research … But only during
planning we are not refreshing."

⛔⛔ WHAT THIS CODE DECIDES (research.py) — the lines this change added.
  X*  the plan's Redo (`_gemini_plan_redo_tick`, the plan wait 2D, the
      round-robin's watch): only a plan that visibly failed (settled failure
      line, no research, no Start) is pressed; at most two presses, 45 s apart,
      a press spending one whatever came of it; a plan that came back or could
      not be read on the look is not pressed; the count goes from the plan wait
      to the round-robin; the card only after both presses (or with no Redo on
      the plan), in the same words; nothing else on the leg runs while a press
      has its 45 s; the tile and the log say what happened.
  S*  the research refresh: the research reads leave the person's turns out
      (the first 8,000 characters of a real page are the brief), so the refresh
      and the watch see the research card; the refresh window starts when the
      research is first seen; the log says the rule.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/gemini_redo_1003_mutants.py
  .venv/bin/python .mutants/gemini_redo_1003_mutants.py X1 S2
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
    "redo": (_T + "w15_gemini_redo_1003" + ".py", _T + "w15_gemini_waits_1002" + ".py"),
    "stale": (_T + "w15_gemini_redo_1003" + ".py", _T + "gemini_stale_reload_0918" + ".py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

#: The page's first 8,000 characters — the read this change replaced.
_OLD_READ = "str(await page.evaluate(\"() => (document.body.innerText || '').slice(0, 8000)\") or \"\")"

MUTANTS = [
    # ── X: the plan's Redo ──────────────────────────────────────────────────
    ("X1", RESEARCH, "redo", "⛔⛔ a plan that has not visibly failed is pressed — a streaming plan, a running research",
     [("        failed = await _gemini_watched_plan_failed(page)\n        if not failed:\n",
       "        failed = await _gemini_watched_plan_failed(page)\n        if False:\n")]),
    ("X2", RESEARCH, "redo", "⛔⛔ no time between presses — two Redos in a burst",
     [("                < _GEMINI_PLAN_REDO_COOLDOWN_SEC:\n",
       "                < 0:\n")]),
    ("X3", RESEARCH, "redo", "⛔ 20 seconds between presses, not the 45",
     [("_GEMINI_PLAN_REDO_COOLDOWN_SEC = 45\n", "_GEMINI_PLAN_REDO_COOLDOWN_SEC = 20\n")]),
    ("X4", RESEARCH, "redo", "⛔⛔ no ceiling — the Redo is pressed for ever",
     [("        if n >= _GEMINI_PLAN_REDO_MAX:\n            return \"spent\", failed\n",
       "        if False:\n            return \"spent\", failed\n")]),
    ("X5", RESEARCH, "redo", "⛔ three presses, not two",
     [("_GEMINI_PLAN_REDO_MAX = 2\n", "_GEMINI_PLAN_REDO_MAX = 3\n")]),
    ("X6", RESEARCH, "redo", "⛔ a plan that came back since the last read is carded",
     [("        if step == \"settled\":\n            return \"not_failed\", \"\"",
       "        if False:\n            return \"not_failed\", \"\"")]),
    ("X7", RESEARCH, "redo", "⛔ a plan that could not be read on the look is carded",
     [("        if step == \"no_turn\":\n            return \"hold\", failed",
       "        if False:\n            return \"hold\", failed")]),
    ("X8", RESEARCH, "redo", "⛔⛔ a plan with no Redo on it counts as pressed — the card never comes",
     [("    if not acted:\n        return \"no_redo\", failed",
       "    if False:\n        return \"no_redo\", failed")]),
    ("X9", RESEARCH, "redo", "⛔⛔ a press spends nothing — the Redo every 45 s for ever",
     [("    state[\"gemini_plan_redos\"] = n + 1\n", "    state[\"gemini_plan_redos\"] = n\n")]),
    ("X10", RESEARCH, "redo", "⛔ the time of a press is not kept — the second comes at once",
     [("    state[\"gemini_plan_redo_at\"] = time.time()\n",
       "    state[\"gemini_plan_redo_at\"] = 0.0\n")]),
    ("X11", RESEARCH, "redo", "⛔⛔ the plan wait never presses the Redo (10-02's rule)",
     [("            _redo, _redo_failed = await _gemini_plan_redo_tick(gemini_page, _plan_redo, \"2D\")\n",
       "            _redo, _redo_failed = \"not_failed\", \"\"\n")]),
    ("X12", RESEARCH, "redo", "the tile does not say the Redo was pressed",
     [("                               progress=(f\"Gemini's plan hit an error — pressed its Redo \"\n",
       "                               progress=(f\"Gemini drafting research plan \"\n")]),
    ("X13", RESEARCH, "redo", "⛔ the plan wait says 'did not bring it back' every ten seconds",
     [("            elif _redo in (\"spent\", \"no_redo\") and not _plan_redo_said:\n",
       "            elif _redo in (\"spent\", \"no_redo\") and True:\n")]),
    ("X14", RESEARCH, "redo", "the plan wait's log names the wrong reason",
     [("                       if _redo == \"spent\" else \"it shows no Redo to press\")\n",
       "                       if _redo != \"spent\" else \"it shows no Redo to press\")\n")]),
    ("X15", RESEARCH, "redo", "⛔⛔ the plan wait's presses are not handed on — two more in the round-robin",
     [("                                **_plan_redo,\n", "")]),
    ("X16", RESEARCH, "redo", "⛔⛔ the round-robin forgets the presses it was handed — a third and fourth",
     [("            \"gemini_plan_redos\": int(agent.get(\"gemini_plan_redos\", 0) or 0),\n",
       "            \"gemini_plan_redos\": 0,\n")]),
    ("X17", RESEARCH, "redo", "⛔ the round-robin forgets when the last press was — the card before its 45 s",
     [("            \"gemini_plan_redo_at\": float(agent.get(\"gemini_plan_redo_at\", 0.0) or 0.0),\n",
       "            \"gemini_plan_redo_at\": 0.0,\n")]),
    ("X18", RESEARCH, "redo", "⛔⛔ the round-robin's presses are not kept — the Redo for ever, never the card",
     [("                _redo, _ws_failed = await _gemini_plan_redo_tick(p[\"page\"], p, name)\n",
       "                _redo, _ws_failed = await _gemini_plan_redo_tick(p[\"page\"], {}, name)\n")]),
    ("X19", RESEARCH, "redo", "⛔⛔ while a press has its 45 s the leg reads the failed plan as a finished report",
     [("                if _redo in (\"pressed\", \"hold\"):\n",
       "                if _redo == \"pressed\":\n")]),
    ("X20", RESEARCH, "redo", "⛔⛔ a failed plan with no Redo on it never gets the card",
     [("                if _redo in (\"spent\", \"no_redo\"):\n",
       "                if _redo == \"spent\":\n")]),
    ("X21", RESEARCH, "redo", "the card's log line names the wrong reason",
     [("                           if _redo == \"spent\" else \"Gemini shows no Redo to press\")\n",
       "                           if _redo != \"spent\" else \"Gemini shows no Redo to press\")\n")]),

    # ── S: the research refresh, on a real page ─────────────────────────────
    ("S1", RESEARCH, "stale", "⛔ the person's turns stay in the read — a brief can fake or hide the research",
     [("    \"   t = t.replace(q.innerText || '', '');\"\n", "    \"   t = t;\"\n")]),
    ("S2", RESEARCH, "stale", "⛔⛔ the refresh reads the page's first 8,000 characters again — all brief: never refreshed",
     [("    body = await _gemini_replies_text(page)\n    if not body:\n        return False, False\n",
       "    body = " + _OLD_READ + "\n    if not body:\n        return False, False\n")]),
    ("S3", RESEARCH, "stale", "⛔⛔ the watch reads the first 8,000 characters again — it never lets go, nothing refreshes",
     [("    body = await _gemini_replies_text(page)\n    if not body:\n        return False\n",
       "    body = " + _OLD_READ + "\n    if not body:\n        return False\n")]),
    ("S4", RESEARCH, "stale", "⛔ the moment the research is first seen is not kept — refreshed the moment it shows",
     [("                        p[\"gemini_research_seen_at\"] = time.time()\n",
       "                        pass\n")]),
    ("S5", RESEARCH, "stale", "⛔ the refresh window counts from the hand-off — refreshed the moment it shows",
     [("            research_started_at=max(float(p.get(\"start_time\", 0.0) or 0.0),\n"
       "                                    float(p.get(\"gemini_research_seen_at\", 0.0) or 0.0)),\n",
       "            research_started_at=float(p.get(\"start_time\", 0.0) or 0.0),\n")]),
    ("S6", RESEARCH, "stale", "the refresh's log line does not say what it is doing in plain words",
     [("        f\"(research showing, no finished report) — refreshing it, \"\n",
       "        f\"— bounded stale reload \"\n")]),
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
