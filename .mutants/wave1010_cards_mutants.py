"""Wave 10.10, lane machine-cards — can the tests see these going back?

  C — the terminal crash card names Chrome when Chrome is what kept closing,
      says how many times, says what to change before Retry, and leaves every
      other kind of failure with today's sentence.

Every mutant reverts ONE decision. The ones that matter most are the quiet ones:

  C1  — the branch is never taken. Nothing else breaks and the card is back to
        "The run kept hitting errors" for a Chrome that closed three times.
  C2  — the branch is taken for EVERY kind, so an ordinary failure sends the
        person off to update a browser that was fine.
  C7/C8 — the copy is computed and the card ignores it: the consumer-ignores-
        the-rule shape, which a test of the words alone cannot see.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED, from the checkout you want
measured — `-m pytest` puts this checkout first on sys.path.

  <venv>/bin/python -u .mutants/wave1010_cards_mutants.py
  <venv>/bin/python -u .mutants/wave1010_cards_mutants.py C1 C2
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_crash_card_chrome_1010.py "
          "tests/test_stop_is_not_a_crash_108.py "
          "tests/test_analytics_times_1010.py "
          "tests/test_phase_durations_0811.py "
          "tests/test_phase1_status_order_0811.py")
RESEARCH = "research.py"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the terminal crash card ────────────────────────────────────────
C_BRANCH = '            if _captured_failure_kind == "browser_crash":'
C_COUNT = "                _closes = _crash_retries + 1"
C_TITLE = '                _card_error = ("Chrome kept closing" if _closes > 1'
C_STREAK = ('                     f"computer, so we stopped reopening it. " '
            'if _closes > 1')
C_ADVICE = ('                    + "Quit other Chrome windows there, update Chrome, or "\n'
            '                      "restart that computer, then Retry to start again from "\n'
            '                      "the last checkpoint — or Skip to stop here.")')
C_USE_ERROR = "                error=_card_error,"
C_USE_REASON = "                reason=_card_reason,"

# ── anchors: phase rows (save_meta) ─────────────────────────────────────────
P_GATE = ('    if (isinstance(_began, int) and meta.get("createdAt", 0) <= _began <= now_ms\n'
          '            and 0 < phase < len(phases) and phases[phase]["completedAt"] is None):')
P_OPEN = '        phases[phase]["startedAt"] = _began'
P_ONLY_ZERO = '        if phase == 1 and _prev.get("completedAt") is None:'
P_CLOSE_AT = '            _prev["completedAt"] = _began'
P_SITE_FILE = ('                          started_ms=int(_p1_start * 1000))\n'
               '                emit_event("phase_complete", phase=1,\n')
P_SITE_GEN = ('                          started_ms=int(_p1_start * 1000))\n'
              '                emit_event("phase_complete", phase=1, durationSec=')

# ── anchors: each agent's time (save_meta + the phase-2 save) ───────────────
A_LOOP = '    for _name, _r in (extra.get("agent_results") or {}).items():'
A_KEY = '        _key = str(_name).lower().replace(" ", "")'
A_WHO = '        if (_key in ("chatgpt", "gemini", "claude")'
A_BOOL = ('                and isinstance(_secs, (int, float)) and not isinstance(_secs, bool)\n'
          '                and _secs > 0):')
A_ZERO = '                and _secs > 0):'
A_SET = '            agents.setdefault(_key, {})["completionTimeSec"] = int(_secs)'
A_SITE = '            save_meta(queue_dir, topic, 2, agent_results=results)'

MUTANTS = [
    # ── C: the terminal crash card ─────────────────────────────────────────
    ("C1", "under", "⛔⛔ THE DEFECT, RESTORED — the Chrome branch is never "
     "taken, so a Chrome that closed three times in a row is 'The run kept "
     "hitting errors' again, with a Retry into the same Chrome",
     [(C_BRANCH, "            if False:")]),
    ("C2", "over", "⛔⛔ THE OVER-CORRECTION — every failure is called Chrome, "
     "and somebody whose notebook upload was refused is told to update a "
     "browser that was fine",
     [(C_BRANCH, "            if True:")]),
    ("C3", "under", "⛔ the count forgets the first close, so the card says "
     "Chrome closed twice when it closed three times",
     [(C_COUNT, "                _closes = _crash_retries")]),
    ("C4", "over", "⛔ a single close is called a streak in the title — "
     "'Chrome kept closing' about one death the planner refused to retry",
     [(C_TITLE, '                _card_error = ("Chrome kept closing" if _closes > 0')]),
    ("C5", "over", "⛔ a single close is called a streak in the details — "
     "'Chrome closed 1 times in a row', the sentence this wave removes",
     [(C_STREAK, '                     f"computer, so we stopped reopening it. " '
                 'if _closes > 0')]),
    ("C6", "under", "⛔ the advice goes, so the card names Chrome and offers "
     "the same Retry into the same Chrome — half the point of the card",
     [(C_ADVICE, '                    + "Retry to start again from the last '
                 'checkpoint, or Skip to stop here.")')]),
    ("C7", "under", "⛔⛔ THE CONSUMER IGNORES THE RULE — the title is computed "
     "and the card still shows today's, so every test of the helper-shaped half "
     "would pass while the person reads 'errors'",
     [(C_USE_ERROR, '                error="The run kept hitting errors",')]),
    ("C8", "under", "⛔ the consumer ignores the details — the card says "
     "Chrome in the title and today's generic sentence underneath",
     [(C_USE_REASON, '                reason="We tried to recover a couple of '
                     'times and it didn\'t take. Retry to start again from the '
                     'last checkpoint, or Skip to stop here.",')]),

    # ── P: a phase ends when the next one starts ───────────────────────────
    ("P1", "under", "⛔⛔ THE DEFECT, RESTORED — save_meta ignores the start it "
     "is handed, so phase 0 never ends and phase 1 carries its span again",
     [(P_GATE, "    if False:")]),
    ("P2", "under", "⛔ phase 0 is never closed although phase 1 now opens at "
     "its real start — a gap of 'nothing' between the two on every timeline",
     [(P_CLOSE_AT, "            pass")]),
    ("P3", "under", "⛔ phase 0 closes but phase 1 still opens at the run's "
     "start, so phase 1's duration includes phase 0's twice over in the total",
     [(P_OPEN, "        pass")]),
    ("P4", "over", "⛔⛔ THE INVENTION — any open row before the saved phase is "
     "closed at its start, so a skipped or never-saved phase is given phase "
     "0's span as a duration it never ran",
     [(P_ONLY_ZERO, '        if _prev.get("completedAt") is None:')]),
    ("P5", "over", "⛔ phase 0 is closed at NOW rather than at phase 1's start, "
     "which swaps one wrong span for another",
     [(P_CLOSE_AT, "            _prev[\"completedAt\"] = now_ms")]),
    ("P6", "over", "⛔ a start before the run began is believed — a clock "
     "disagreement printed as a negative-looking boundary",
     [(P_GATE, '    if (isinstance(_began, int) and _began <= now_ms\n'
               '            and 0 < phase < len(phases) and phases[phase]["completedAt"] is None):')]),
    ("P7", "over", "⛔ a start in the future is believed — phase 0 is closed "
     "after phase 1 has finished",
     [(P_GATE, '    if (isinstance(_began, int) and meta.get("createdAt", 0) <= _began\n'
               '            and 0 < phase < len(phases) and phases[phase]["completedAt"] is None):')]),
    ("P8", "over", "⛔ a closed row is rewritten — a stop right after phase 1 "
     "re-saves phase 1 and moves boundaries already recorded",
     [(P_GATE, '    if (isinstance(_began, int) and meta.get("createdAt", 0) <= _began <= now_ms\n'
               '            and 0 < phase < len(phases)):')]),
    ("P9", "under", "⛔⛔ THE CONSUMER IGNORES THE RULE — the brief-from-file "
     "save stops saying when phase 1 began, and every save_meta test still "
     "passes while that branch's runs never close phase 0",
     [(P_SITE_FILE, '                          )\n'
                    '                emit_event("phase_complete", phase=1,\n')]),
    ("P10", "under", "⛔⛔ THE CONSUMER IGNORES THE RULE — the generated-brief "
     "save, the one nearly every run takes",
     [(P_SITE_GEN, '                          )\n'
                   '                emit_event("phase_complete", phase=1, durationSec=')]),
    ("P11", "under", "⛔ the start is passed in seconds, not milliseconds — "
     "before the run began by 55 years, so it is ignored and nothing closes",
     [(P_SITE_GEN, '                          started_ms=int(_p1_start))\n'
                   '                emit_event("phase_complete", phase=1, durationSec=')]),

    # ── A: each agent's time reaches the cloud ─────────────────────────────
    ("A1", "under", "⛔⛔ THE DEFECT, RESTORED — save_meta ignores the results, "
     "so the cloud row of every unwatched run says 0 for every agent",
     [(A_LOOP, "    for _name, _r in {}.items():")]),
    ("A2", "under", "⛔⛔ THE CONSUMER IGNORES THE RULE — the phase-2 save stops "
     "handing over the results, and every save_meta test still passes",
     [(A_SITE, "            save_meta(queue_dir, topic, 2)")]),
    ("A3", "under", "⛔ the display name is not normalised, so 'ChatGPT' never "
     "matches 'chatgpt' and no time lands anywhere",
     [(A_KEY, "        _key = str(_name)")]),
    ("A4", "over", "⛔ a zero overwrites — the agent a resume KEPT loses the "
     "time it earned last attempt, and an agent that never ran gets a row",
     [(A_ZERO, "                and _secs >= 0):")]),
    ("A5", "over", "⛔ any name is accepted, so a stray key in the results "
     "invents an agent the analytics page then tries to draw",
     [(A_WHO, "        if (True")]),
    ("A6", "over", "⛔ a bool is taken as a number of seconds",
     [(A_BOOL, "                and isinstance(_secs, (int, float))\n"
               "                and _secs > 0):")]),
    ("A7", "under", "⛔ only an agent that already has an entry gets its time, "
     "so the one that ran 25 minutes and died with no report says nothing",
     [(A_SET, '            if _key in agents: agents[_key]["completionTimeSec"] = int(_secs)')]),
]


def _path(fname: str) -> Path:
    return ROOT / fname


#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 300


def green():
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITES.split(), "-q",
             "-p", "no:cacheprovider", "-rs"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it.
    return " failed" not in out and " error" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    # Normalised to five columns — the shape the two sweeps in `.mutants/_*.py`
    # read — with the file defaulting to research.py.
    MUTANTS = [(*m, RESEARCH)[:5] for m in MUTANTS]
    files = sorted({m[4] for m in MUTANTS})
    ORIGINALS = {f: _path(f).read_text(encoding="utf-8") for f in files}

    def restore():
        for f, t in ORIGINALS.items():
            _path(f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    if not green():
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    faults = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, why, edits, fname in selected:
        path = ROOT / fname
        original = ORIGINALS[fname]
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as e:
                raise AssertionError(f"mutant does not parse: {e}")
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}", flush=True)
            else:
                print(f"  {mid}  ✓ killed", flush=True)
        except AssertionError as e:
            faults.append(mid)
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}", flush=True)
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if _path(f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed")
    if faults:
        print("⚠ HARNESS FAULT(S) — measured nothing, counted out: " + ", ".join(faults))
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if survivors or faults:
        sys.exit(1)
    print("clean.\n")
