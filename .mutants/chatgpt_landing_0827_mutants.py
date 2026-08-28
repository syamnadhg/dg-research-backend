"""Mutation harness for the 2026-08-27 ChatGPT `WEB:` landing fix.

The defect being fixed was an UNDER-correction: an id we could not date was read
as "somebody else's conversation" and a healthy leg died seven seconds after Send.

⛔⛔ BUT THE OVER-CORRECTIONS CARRY MORE WEIGHT HERE, and they have a name: the
2026-08-05 incident. A warm tab parked in the previous evening's finished thread
was harvested as that run's output — 121KB about golden retrievers, delivered as
research, uploaded to NotebookLM and narrated. Every cheap way to "just accept the
conversation" re-opens it. C7, C8, C9, C10 and C11 below are each one line, each
looks like a simplification, and each brings that run back.

    .venv/bin/python .mutants/chatgpt_landing_0827_mutants.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_chatgpt_landing_0827.py "
          "tests/test_chatgpt_conversation_identity.py "
          "tests/test_chatgpt_row_scope_0805.py "
          "tests/test_drift_review_0805.py "
          "tests/test_skip_reporting.py")

ENV = {**os.environ,
       "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": os.pathsep.join(
           [str(ROOT)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}

SURVIVOR_CONFIRMATIONS = 3
SUMMARY_RE = re.compile(r"^=*\s*(?:\d+\s+\w+(?:,\s*)?)+\s+in\s+[\d.]+s", re.M)
SKIP_RE = re.compile(r"(\d+)\s+skipped")

MUTANTS = [
    # ══════════ under-corrections: the fix stops working ══════════
    ("C1", "under",
     "⭐ THE ORIGINAL DEFECT — an undatable id collapses back into 'not a "
     "conversation', so every caller reads it as a refusal",
     [('    if _chatgpt_convo_id(url) is None:\n        return "no_conversation"',
       '    if _chatgpt_convo_epoch(url) is None:\n        return "no_conversation"')]),
    ("C2", "under",
     "⭐⭐ THE DEFECT ITSELF, RESTORED — an id we cannot date is called foreign "
     "again and the WEB: leg dies 7s after Send",
     [('    if _chatgpt_convo_epoch(url) is None:\n        return "undatable"',
       '    if _chatgpt_convo_epoch(url) is None:\n        return "foreign"')]),
    ("C3", "under",
     "the loop stops keeping the budget running on an undatable id, so the "
     "fallback can never have anything to fall back to",
     [('                if _verdict == "undatable":\n'
       '                    # Present, new, and not datable → keep the budget running.\n'
       '                    _undatable = _last',
       '                if _verdict == "undatable":\n'
       '                    # Present, new, and not datable → keep the budget running.\n'
       '                    pass')]),
    ("C4", "under",
     "⭐⭐ the fallback never fires — the budget is spent and the leg is failed "
     "anyway. THE HEADLINE OF THE FIX, and it SURVIVED the first round: the only "
     "thing watching it was a source pin on its `return` line, and a return "
     "inside an unenterable branch is still in the file",
     [('    if undatable_url:\n'
       '        return True, undatable_url, "undatable_id_transition_observed"',
       '    if False:\n'
       '        return True, undatable_url, "undatable_id_transition_observed"')]),
    ("C13", "over",
     "⛔⛔ the fallback fires with NOTHING remembered — a tab that never moved is "
     "confirmed as this run's conversation, and `no_conversation_url` dies",
     [('    if undatable_url:\n'
       '        return True, undatable_url, "undatable_id_transition_observed"',
       '    if True:\n'
       '        return True, undatable_url, "undatable_id_transition_observed"')]),
    ("C14", "under",
     "the fallback confirms the LAST url instead of the conversation we actually "
     "watched — they differ when the tab moves again after the id we noted",
     [('        return True, undatable_url, "undatable_id_transition_observed"\n'
       '    return False, last_url, "no_conversation_url"',
       '        return True, last_url, "undatable_id_transition_observed"\n'
       '    return False, last_url, "no_conversation_url"')]),
    ("C5", "under",
     "the poll-path predicate condemns an undatable conversation again, so a "
     "leg that survives setup is killed on the next tick instead",
     [('    if _chatgpt_convo_epoch(url) is None:\n        return False\n'
       '    return not _chatgpt_conversation_is_ours(url)',
       '    return not _chatgpt_conversation_is_ours(url)')]),
    ("C6", "under",
     "the crashed-page status folds back in with the lost-tab copy, so the user "
     "is told we mislaid a run the platform dropped",
     [('    if st == "browser_crashed":\n'
       '        return ("auto_skip_platform_crashed", "platform_crashed",',
       '    if st == "never_happens_xyz":\n'
       '        return ("auto_skip_platform_crashed", "platform_crashed",')]),

    # ══════════ over-corrections: 2026-08-05 comes back ══════════
    ("C7", "over",
     "⛔⛔ A CONVERSATION OLDER THAN THE RUN IS ACCEPTED — the golden-retriever "
     "incident, restored in one word",
     [('    return "ours" if _chatgpt_conversation_is_ours(url, run_start) else "foreign"',
       '    return "ours"')]),
    ("C8", "over",
     "⛔⛔ the undatable test moves ABOVE the datable one, so a readable, OLD "
     "conversation is never even dated — it reaches the fallback and is accepted",
     [('    if url.split("?", 1)[0] == (pre_send_url or "").split("?", 1)[0]:\n'
       '        return "unchanged"\n'
       '    if _chatgpt_convo_epoch(url) is None:\n'
       '        return "undatable"',
       '    if url.split("?", 1)[0] == (pre_send_url or "").split("?", 1)[0]:\n'
       '        return "unchanged"\n'
       '    if True:\n'
       '        return "undatable"')]),
    ("C9", "over",
     "⛔ a send that created nothing reads as landed — the composer never moved "
     "and we poll a dead conversation for the full run",
     [('    if url.split("?", 1)[0] == (pre_send_url or "").split("?", 1)[0]:\n'
       '        return "unchanged"',
       '    if False:\n'
       '        return "unchanged"')]),
    ("C10", "over",
     "⛔⛔ every observation is 'ours' — the identity check is deleted outright "
     "while every reason string stays in place",
     [('    if _chatgpt_convo_id(url) is None:\n        return "no_conversation"',
       '    if _chatgpt_convo_id(url) is not None:\n        return "ours"')]),
    ("C11", "over",
     "⛔⛔ the fallback fires WITHOUT having watched a transition — a tab that "
     "never moved is confirmed as this run's conversation",
     [('            return _chatgpt_landing_result(_undatable, _last)',
       '            return True, _last, "undatable_id_transition_observed"')]),
    ("C12", "over",
     "⛔ the weak route stops announcing itself — the fallback silently becomes "
     "the only check and nobody learns the format changed again",
     [('        if _cg_why == "undatable_id_transition_observed":',
       '        if False:')]),
]


def sh(cmd, *, env=None):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env or ENV)


def purge_pycache():
    for d in (ROOT / "tests").rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def tracked_dirty():
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests():
    """(green, skipped). ⛔ Summary line only — see the 08-27 guard note in
    `review_blockers_0813_mutants.py`: scanning all output makes the suite's own
    fixtures look like skips."""
    purge_pycache()
    proc = sh([sys.executable, "-B", "-m", "pytest", *SUITES.split(), "-q",
               "-p", "no:cacheprovider"])
    line = None
    for m in SUMMARY_RE.finditer(proc.stdout + proc.stderr):
        line = m.group(0)
    hits = SKIP_RE.findall(line) if line else []
    return proc.returncode == 0, (int(hits[-1]) if hits else 0)


def missing_tooling():
    return [exe for exe in ("git",) if shutil.which(exe) is None]


def main():
    absent = missing_tooling()
    if absent:
        print("Missing from PATH: " + ", ".join(absent) + ". Refusing to score.")
        return 2
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    ok, skipped = run_tests()
    if not ok:
        print("RED. Nothing below would mean anything.")
        return 2
    if skipped:
        print(f"green but {skipped} SKIPPED — refusing to score. A skip is the "
              f"absence of a measurement.")
        return 2
    print("green")

    path = ROOT / "research.py"
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                n = mutated.count(frm)
                if n != 1:
                    raise AssertionError(
                        f"anchor matched {n}x (must be exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            green, sk = run_tests()
            if sk:
                raise AssertionError(f"{sk} test(s) skipped — verdict refused")
            killed = not green
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                green, sk = run_tests()
                if sk:
                    raise AssertionError(f"{sk} test(s) skipped — verdict refused")
                killed = not green
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            print(f"{mark} {mid} [{direction}] {why}{'  ⚠ FLAPPED' if flapped else ''}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, why))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN:\n" + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
