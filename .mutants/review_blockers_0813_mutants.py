"""Mutation harness for the three blocking findings of the 2026-08-12 review.

All three are missing-guard findings, and for every one of them the cheapest
wrong fix is a guard that refuses everything — which looks like caution and
silently deletes the feature. So the OVER-corrections carry most of the weight
here, and three of them are the reviewer's own suggested fixes:

  * gating the port reclaim on `_port_answers_health` (R7), which would refuse
    every reclaim because `/api/health` answers ok unconditionally;
  * requiring a version before a click counts as a pick (M7), which would empty
    the model menu on the day a vendor ships a version-less label;
  * merging on EVERY status write (S6), which would leave a previous attempt's
    verdict underneath a newer one.

Two files are mutated, so each mutant names its own.

Safety, learned from an earlier harness on this repo that adopted a mutant as
its own baseline: refuses to start on a dirty tree, holds originals in memory
only, restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/review_blockers_0813_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_review_blockers_0813.py "
          "tests/test_device_update_command.py "
          "tests/test_update_never_silent.py "
          "tests/test_claude_model_pick.py "
          "tests/test_claude_popover_skip.py "
          "tests/test_known_good_fallback.py "
          "tests/test_serve_port_reclaim_0810.py")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ finding 1 — a second --serve must not end a live run ═══════
    ("R1", "research.py", "under",
     "⭐ the busy guard is gone — the finding, restored verbatim",
     [("    _activity = _port_backend_activity(port)\n"
       "    if _backend_activity_is_work(_activity):", "    if False:")]),
    ("R2", "research.py", "under",
     "`running` no longer counts as work — only a queued job would refuse",
     [('    return bool(activity.get("running")) or (activity.get("pending") or 0) > 0',
       '    return (activity.get("pending") or 0) > 0')]),
    ("R3", "research.py", "under",
     "`pending` no longer counts — a queued job is destroyed between runs",
     [('    return bool(activity.get("running")) or (activity.get("pending") or 0) > 0',
       '    return bool(activity.get("running"))')]),
    ("R4", "research.py", "under",
     "the probe reads the status line again, so every holder looks idle",
     [("            if not 200 <= getattr(r, \"status\", 200) < 300:\n"
       "                return None\n"
       "            body = json.loads(r.read().decode(\"utf-8\"))",
       "            body = {\"status\": \"ok\"} if r else {}")]),
    ("R5", "research.py", "under",
     "a non-2xx answer is trusted, so an error page decides whether we kill",
     [("            if not 200 <= getattr(r, \"status\", 200) < 300:\n"
       "                return None\n", "")]),
    ("R6", "research.py", "over",
     "⛔ silence is read as work — the terminal-less orphan is never cleared "
     "and the unexplained EADDRINUSE comes back",
     [("    if not activity:\n        return False", "    if not activity:\n        return True")]),
    ("R7", "research.py", "over",
     "⛔ THE REVIEW'S LITERAL SUGGESTION — gate on the liveness probe. Health "
     "answers ok unconditionally, so this refuses EVERY reclaim",
     [("    _activity = _port_backend_activity(port)\n"
       "    if _backend_activity_is_work(_activity):",
       "    _activity = _port_backend_activity(port)\n"
       "    if _port_answers_health(port):")]),
    ("R8", "research.py", "over",
     "⛔ every holder we recognise is refused — reclaim disabled outright",
     [("    if _backend_activity_is_work(_activity):", "    if True:")]),
    ("R9", "research.py", "under",
     "the caller no longer refuses the bind, so a live run is bound over",
     [('    if _port_state == "busy":', '    if False:')]),
    ("R10", "research.py", "under",
     "the busy verdict is reported as free, so the guard never reaches the caller",
     [('        return "busy", ours', '        return "free", []')]),
    ("R11", "research.py", "over",
     "⛔ identity stops outranking activity — a foreign holder is probed and, "
     "if quiet, killed",
     [("    if foreign:\n        return \"foreign\", foreign\n", "")]),

    # ═══════════ finding 2 — a billing chip is not a model ══════════════════
    ("M1", "research.py", "under",
     "⭐ the browser no longer excludes chips — the finding, restored",
     [("                if (isUpsell(t)) continue;\n", "")]),
    ("M2", "research.py", "under",
     "the exclusion moves after the version parse and only fires on "
     "version-less rows — the narrow triage that missed the versioned chip",
     [("                if (isUpsell(t)) continue;\n"
       "                const v = verOf(t);\n"
       "                const isFam = v !== null || famRe.test(t);",
       "                const v = verOf(t);\n"
       "                const isFam = v !== null || (famRe.test(t) && !isUpsell(t));")]),
    ("M3", "research.py", "under",
     "the verb boundary is dropped, so 'regetopus' reads as a sales prompt",
     [("                        const leftOk = i === 0 || !isAlnum(s[i - 1]);\n"
       "                        const rightOk = end >= s.length || !isAlnum(s[end]);\n"
       "                        if (leftOk && rightOk) {\n"
       "                            const j = s.indexOf(n, end);",
       "                        if (true) {\n"
       "                            const j = s.indexOf(n, end);")]),
    ("M4", "research.py", "under",
     "the proximity window is unbounded — any verb anywhere bins a real row",
     [("                            if (j !== -1 && j - end <= upsellWindow) return true;",
       "                            if (j !== -1) return true;")]),
    ("M5", "research.py", "under",
     "the probe stops excluding chips — 'offered but not clickable', forever",
     [("                const raw = (el.textContent || '').trim();\n"
       "                if (isUpsell(raw)) continue;\n"
       "                const v = verOf(raw);",
       "                const raw = (el.textContent || '').trim();\n"
       "                const v = verOf(raw);")]),
    ("M6", "research.py", "over",
     "⛔ the family word alone disqualifies a row — the menu is always empty",
     [("            const isUpsell = (raw) => {", "            const isUpsell = (raw) => { return true;")]),
    ("M7", "research.py", "over",
     "⛔ THE REVIEW'S SECOND SUGGESTION — a version-less row can no longer be "
     "picked, so a rename empties the menu",
     [("                const isFam = v !== null || famRe.test(t);",
       "                const isFam = v !== null;")]),
    ("M8", "research.py", "over",
     "⛔ a bare verb test — a genuine row whose blurb says 'try' is binned",
     [("                            const j = s.indexOf(n, end);\n"
       "                            if (j !== -1 && j - end <= upsellWindow) return true;",
       "                            return true;")]),
    ("M9", "research.py", "under",
     "the verb list is never passed, so the browser excludes nothing",
     [('                          "verbs": list(UPSELL_VERBS), "upsellWindow": UPSELL_WINDOW}',
       '                          "verbs": [], "upsellWindow": UPSELL_WINDOW}')]),
    ("M10", "models.py", "under",
     "the python mirror stops excluding chips",
     [("        if drop_upsell and is_upsell(t, family):\n            continue\n", "")]),
    ("M11", "models.py", "under",
     "the mirror's boundary check is dropped",
     [("            left_ok = i == 0 or not _ascii_alnum(t[i - 1])\n"
       "            right_ok = end >= len(t) or not _ascii_alnum(t[end])\n"
       "            if left_ok and right_ok:", "            if True:")]),
    ("M12", "models.py", "under",
     "the mirror's window is unbounded",
     [("                if j != -1 and j - end <= window:", "                if j != -1:")]),
    ("M13", "models.py", "under",
     "the mirror requires the noun BEFORE the verb — inverted, so real rows "
     "are binned and chips pass",
     [("                j = t.find(n, end)", "                j = t.find(n)")]),
    ("M14", "models.py", "over",
     "⛔ the exclusion becomes default-on, so the un-ported Gemini ranker and "
     "this mirror answer differently",
     [("def pick_highest_model(labels, family: str, below=None, reject=(), drop_upsell=False):",
       "def pick_highest_model(labels, family: str, below=None, reject=(), drop_upsell=True):")]),
    ("M15", "models.py", "under",
     "the verb list forks from the one the tier picker and the mission read",
     [('        "upgrade_verbs": UPSELL_VERBS,', '        "upgrade_verbs": ["upgrade"],')]),
    ("M16", "models.py", "under",
     "whitespace is no longer collapsed, so a row split across lines escapes",
     [('    t = " ".join((text or "").split()).lower()', '    t = (text or "").lower()')]),

    # ═══════════ finding 3 — a refusal must not lower needsRestart ══════════
    ("S1", "research.py", "under",
     "⭐ merge does nothing — the whole map is replaced again, the finding",
     [("        if merge:\n            # Keys here are in-tree literals",
       "        if False:\n            # Keys here are in-tree literals")]),
    ("S2", "research.py", "under",
     "the busy restart refusal replaces again — the exact branch reported",
     [('                        "reason": "a research run is in progress"}, merge=True)',
       '                        "reason": "a research run is in progress"})')]),
    ("S3", "research.py", "under",
     "the not-the-owner restart refusal replaces — a sharer erases the owner's flag",
     [('                        "reason": "not the device owner"}, merge=True)',
       '                        "reason": "not the device owner"})')]),
    ("S4", "research.py", "under",
     "the no-identity restart refusal replaces",
     [('                        "reason": "could not verify device ownership"}, merge=True)',
       '                        "reason": "could not verify device ownership"})')]),
    ("S5", "research.py", "under",
     "a refusal writes `latest` again — under dotted paths that nulls it exactly "
     "as before, so the fix is undone one key at a time",
     [('                        "state": "deferred", "current": _sr_version(),\n'
       '                        "reason": "a research run is in progress"}, merge=True)',
       '                        "state": "deferred", "current": _sr_version(),\n'
       '                        "latest": None,\n'
       '                        "reason": "a research run is in progress"}, merge=True)')]),
    ("S6", "research.py", "over",
     "⛔ EVERY write merges — a completed verdict inherits the previous "
     "attempt's evidence and can never clear needsRestart",
     [("def _write_update_status(device_id: str, status: dict, *, merge: bool = False) -> bool:",
       "def _write_update_status(device_id: str, status: dict, *, merge: bool = True) -> bool:")]),
    ("S7", "research.py", "over",
     "⛔ a refusal re-asserts needsRestart itself, so the button outlives the "
     "restart that satisfied it",
     [('            payload = {f"updateStatus.{k}": v for k, v in status.items()}',
       '            payload = {f"updateStatus.{k}": v for k, v in status.items()}\n'
       '            payload["updateStatus.needsRestart"] = True')]),
    ("S8", "research.py", "under",
     "the merge branch drops its stamp, so the app never sees the refusal",
     [('            payload["updateStatus.at"] = _at\n', "")]),
    ("S9", "research.py", "under",
     "the update handler's mid-run defer replaces again",
     [('        _write_update_status(device_id, {"state": "deferred", "current": cur,\n'
       '                                         "reason": "a research run is in progress"},\n'
       '                             merge=True)',
       '        _write_update_status(device_id, {"state": "deferred", "current": cur,\n'
       '                                         "reason": "a research run is in progress"})')]),
]


# ⛔ 2026-08-13 — THIS HARNESS LIED ONCE, AND THE LIE IS THE DANGEROUS DIRECTION.
# The first run reported nine survivors; six of them were killed the moment the
# same mutant was applied by hand. The results were not even stable between
# runs of the harness itself.
#
# The cause is cached bytecode. `research.py` is 3.5 MB, so its `__pycache__`
# entry is worth a lot of wall-clock, and CPython decides whether to reuse it
# from the source's mtime IN WHOLE SECONDS plus its size. A harness rewrites
# one file repeatedly, in place, in quick succession — which is precisely the
# pattern that pair cannot separate. When the stale `.pyc` won, the test process
# imported the ORIGINAL code, every test passed, and the mutant was recorded as
# surviving: a report that the suite has a hole where it does not.
#
# ⭐ A false SURVIVOR wastes an afternoon. A false KILL is worse — it certifies
# coverage that does not exist. Both are possible here, so bytecode is disabled
# outright (`-B` plus the env var, because the flag governs only the child) and
# every `__pycache__` under the tree is removed before each run. The cost is
# about a second per run; the alternative is a harness whose output cannot be
# trusted in either direction.
# ⛔ AND THE BYTECODE WAS NOT THE WHOLE STORY. After disabling it the verdicts
# were still unstable — different mutants "survived" on each run, and every one
# of them died when applied by hand. The dev venv carries an EDITABLE INSTALL of
# the PERSONAL checkout, so `import research` has two possible answers on this
# machine and the loser is whichever `sys.path` entry lost the race. A test
# process that resolved `dg-research-backend` read UNMUTATED source, passed
# everything, and the mutant was recorded as surviving.
#
# PYTHONPATH pins this worktree ahead of the editable finder, and
# `test_the_suite_is_testing_THIS_tree` fails loudly if it is ever not the one
# imported. The re-run below is the backstop: a SURVIVED verdict is the
# expensive, misleading one, so it is never believed on a single observation.
ENV = {**os.environ,
       "PYTHONDONTWRITEBYTECODE": "1",
       "PYTHONPATH": os.pathsep.join(
           [str(ROOT)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}

# How many times a claimed survivor must survive before it is reported as one.
SURVIVOR_CONFIRMATIONS = 3


def sh(cmd: list[str], *, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          env=env or ENV)


def purge_pycache() -> None:
    for d in ROOT.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--",
              "research.py", "models.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    purge_pycache()
    return sh([sys.executable, "-B", "-m", "pytest", *SUITES.split(), "-q",
               "-p", "no:cacheprovider"]).returncode == 0


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    survivors = []
    for mid, fname, direction, why, edits in MUTANTS:
        path = ROOT / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found in {fname}: {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            # Belt and braces after the stale-bytecode incident: prove the edit
            # is on disk before crediting anything to the suite.
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests()
            flapped = False
            # Only a survivor needs confirming: a kill is one failing assertion
            # and cannot be produced by importing the wrong copy.
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                killed = not run_tests()
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, why))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[2] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
