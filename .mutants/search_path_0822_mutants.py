"""Mutation harness for wave 5 fix 4 — seeing the supervisor's search path.

⛔ WHAT THIS IS FOR. The supervisor bakes the tool homes FIRST, deliberately, and
that trades away a guarantee: anything in a user-writable directory shadows the
OS copy for every supervised child. The trade stands. What did not exist was any
way to see it afterwards — the baked value appeared in no log, and the doctor
looked only at DISPLAY. A shadowed audio binary was a phase-3 failure that
happened only under the supervisor and was undiagnosable from a support bundle.

⭐⭐ THE SHARPEST MUTANTS HERE:
  W2  — `_which_all` returns only the winner, i.e. `shutil.which` again. Every
        line still prints; the one fact that explains the failure is gone.
  I1  — the doctor reads what THIS build would bake instead of what is installed,
        so a machine still running an older build's path reports as correct.
  D2  — the doctor resolves against its own login shell, which is a different
        path from the one a supervised child gets. The section still renders and
        answers the wrong question.
  B1  — the boot line goes, and the support bundle is blind again.

⭐ Over-corrections:
  R4  — the "would install" line prints even when it agrees, so every healthy
        boot carries a difference that is not one.
  D6  — a missing optional tool is counted as a fault, putting an issue on the
        summary line of a machine with nothing wrong with it.
  P1  — the baked value goes back to a literal, which is the bug the ordering
        was written to end.

    python .mutants/search_path_0822_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_PATH = "tests/test_search_path_visibility_0822.py"
# ⛔ The doctor's own files own the sections this one is inserted between.
T_DOC = "tests/test_doctor_network_truth_0817.py"
T_HAND = "tests/test_doctor_handover_0822.py"
ALL = [T_PATH, T_DOC, T_HAND]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ every match, not just the winner ════════════════════════════════
    ("W1", "under", "the walk stops at the first directory, so a tool later on "
     "the path reads as absent",
     [('    for d in (path or "").split(os.pathsep):',
       '    for d in (path or "").split(os.pathsep)[:1]:')],
     [T_PATH]),
    ("W2", "under", "⛔⛔ only the winner is returned — `shutil.which` again, and "
     "the one fact that explains the failure is gone",
     [('                found.append(c)\n                break',
       '                return [c]')],
     [T_PATH]),
    ("W3", "under", "a file that is not executable counts as a match, so the "
     "report sends someone after something that never ran",
     [('            if os.path.isfile(c) and os.access(c, os.X_OK) and c not in seen:',
       '            if os.path.isfile(c) and c not in seen:')],
     [T_PATH]),
    ("W4", "under", "a directory of that name counts as a match",
     [('            if os.path.isfile(c) and os.access(c, os.X_OK) and c not in seen:',
       '            if os.access(c, os.X_OK) and c not in seen:')],
     [T_PATH]),
    # ⛔ W5 REMOVED 2026-08-22, AND SO WAS ITS SUBJECT. It mutated a
    # `try/except OSError` around the two stat calls, and it survived — because
    # `os.path.isfile` and `os.access` both absorb OSError and ValueError
    # internally and answer False. The guard COULD NOT FIRE. The surviving
    # mutant proved the code unreachable, so the code was deleted rather than
    # the mutant weakened.
    ("W6", "under", "the same directory twice is reported as a shadow of itself",
     [('            if os.path.isfile(c) and os.access(c, os.X_OK) and c not in seen:',
       '            if os.path.isfile(c) and os.access(c, os.X_OK):')],
     [T_PATH]),
    ("W7", "under", "empty entries are walked, so the current directory is "
     "treated as part of the search path",
     [('        if not d:\n            continue\n        cand = os.path.join(d, tool)',
       '        cand = os.path.join(d, tool)')],
     [T_PATH]),

    # ══ what is actually installed ══════════════════════════════════════
    ("I1", "under", "⛔⛔ the installed entry is not read at all — the doctor "
     "reports what THIS build would bake, so a machine still on an older "
     "build's path says it is correct",
     [('def _installed_supervisor_path() -> str:',
       'def _installed_supervisor_path() -> str:\n    return _supervisor_path_value()')],
     [T_PATH]),
    ("I2", "under", "a corrupt or missing entry raises instead of answering, "
     "inside the one command a stuck person was told to run",
     [('    except Exception:\n        return ""\n    return ""',
       '    except ValueError:\n        return ""\n    return ""')],
     [T_PATH]),
    ("I3", "under", "the plist is read under the wrong key, so every machine "
     "reports no baked path",
     [('            return str((data.get("EnvironmentVariables") or {}).get("PATH") or "")',
       '            return str((data.get("Environment") or {}).get("PATH") or "")')],
     [T_PATH]),
    ("I4", "under", "the unit-file pattern loses its anchor, so a PATH inside a "
     "comment or another value is read as the real one",
     [(r"""            m = re.search(r'^Environment="PATH=([^"]*)"', text, re.MULTILINE)""",
       r"""            m = re.search(r'PATH=([^"]*)"', text, re.MULTILINE)""")],
     [T_PATH]),

    # ══ the report ══════════════════════════════════════════════════════
    ("R1", "under", "an empty path prints as nothing at all, so the reader "
     "cannot tell it from a line that failed to render",
     [("""    lines = [f"[path] this process searches: {env_path or '(nothing — PATH is empty)'}"]""",
       '    lines = [f"[path] this process searches: {env_path}"]')],
     [T_PATH]),
    ("R2", "under", "a shadow is reported as a plain resolution, which is the "
     "state of the world before this fix",
     [('            lines.append(f"[path] {tool}: {hits[0]}  (shadows {\', \'.join(hits[1:])})")',
       '            lines.append(f"[path] {tool}: {hits[0]}")')],
     [T_PATH]),
    ("R3", "under", "a missing tool is reported as found, with an empty path "
     "behind it",
     [('            lines.append(f"[path] {tool}: not on this path")',
       '            lines.append(f"[path] {tool}: ")')],
     [T_PATH]),
    ("R4", "over", "the would-install line prints even when it agrees, so every "
     "healthy boot carries a difference that is not one",
     [('    if env_path != would_bake:', '    if True:')],
     [T_PATH]),
    ("R5", "under", "the difference is never mentioned, so a machine running an "
     "older build's path looks identical to one that is current",
     [('    if env_path != would_bake:', '    if False:')],
     [T_PATH]),
    ("R6", "under", "the report becomes one multi-line string, so every line "
     "after the first loses its timestamp and its level",
     [('    return lines\n\n\ndef _search_path_findings',
       '    return ["\\n".join(lines)]\n\n\ndef _search_path_findings')],
     [T_PATH]),
    ("R7", "under", "it reports on a fixed path instead of the one this process "
     "is really using",
     [('    env_path = os.environ.get("PATH", "") if env_path is None else env_path',
       '    env_path = "/usr/bin:/bin" if env_path is None else env_path')],
     [T_PATH]),
    ("R8", "under", "the audio binaries drop off the reported list, which is "
     "the exact finding this fix answers",
     [('_PATH_SENSITIVE_TOOLS = ("ffmpeg", "ffprobe", "uv", "pipx")',
       '_PATH_SENSITIVE_TOOLS = ("uv", "pipx")')],
     [T_PATH]),

    # ══ where it is written down ════════════════════════════════════════
    ("B1", "under", "⛔⛔ a worker no longer writes its search path at boot, and "
     "the support bundle is blind again",
     [('        for _pl in _search_path_report():\n            log(_pl)',
       '        pass')],
     [T_PATH]),
    ("B2", "under", "arming a LaunchAgent no longer says what it baked in",
     [('    log(f"[resurrect] baking search path into the LaunchAgent: "\n'
       '        f"{_supervisor_path_value()}")',
       '    pass')],
     [T_PATH]),
    ("B3", "under", "arming a systemd unit no longer says what it baked in",
     [('    log(f"[resurrect] baking search path into the systemd unit: "\n'
       '        f"{_supervisor_path_value()}")',
       '    pass')],
     [T_PATH]),
    ("P1", "over", "the baked value goes back to a literal, which is the bug "
     "the tool-home ordering was written to end",
     [('    system = ["/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]\n'
       '    parts: list[str] = []',
       '    return "/usr/local/bin:/usr/bin:/bin"\n'
       '    system = ["/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]\n'
       '    parts: list[str] = []')],
     [T_PATH]),

    # ══ the decision the doctor renders ════════════════════════════════
    #
    # ⛔⛔ THESE ALL SURVIVED THE FIRST TIME. The section was written inline in
    # `run_doctor`, which cannot be executed in a test, so it was pinned by
    # reading its source — and five mutants gutted the branches one at a time
    # while every one of those pins still passed, because the strings they
    # searched for survived the gutting. The decisions moved into
    # `_search_path_findings`, where a test can call them.
    ("D1", "under", "the doctor loses the section entirely",
     [("    print(f\"  {_c(_BOLD, 'Search path')}\")", '    pass')],
     [T_PATH, T_HAND]),
    ("D2", "under", "⛔⛔ it resolves against the doctor's own login shell, which "
     "is not the path a supervised child gets — the section renders and answers "
     "a different question",
     [('    effective = supervisor_path or shell_path', '    effective = shell_path')],
     [T_PATH]),
    ("D3", "under", "the two answers are never compared, so a tool that "
     "resolves differently under the supervisor passes silently",
     [('        elif supervisor_path and shell_hits and hits[0] != shell_hits[0]:',
       '        elif False:')],
     [T_PATH]),
    ("D4", "under", "a shadow is reported as healthy",
     [('        elif len(hits) > 1:', '        elif False:')],
     [T_PATH]),
    ("D5", "under", "an out-of-date supervisor entry is reported as current, so "
     "every supervised run keeps using the old path and nothing says so",
     [('    if supervisor_path and supervisor_path != would_bake:', '    if False:')],
     [T_PATH]),
    ("D6", "over", "a missing optional tool is counted as a fault, putting an "
     "issue on the summary line of a healthy machine",
     [('            rows.append(("note", f"{tool}: not on this path "\n'
       '                                 f"(optional — only used when it is)", ""))',
       '            rows.append(("warn", f"{tool}: not on this path", ""))')],
     [T_PATH]),
    ("D7", "under", "the out-of-date entry is named with no way to fix it",
     [('        actions.append(_remedy_resurrect())', '        pass')],
     [T_PATH]),
    ("D8", "under", "a healthy machine is handed a remedy anyway, so --resurrect "
     "appears in a list of steps nobody needs to take",
     [('    if supervisor_path and supervisor_path != would_bake:', '    if True:')],
     [T_PATH]),
    ("D9", "over", "a shadow AND a difference produce two warnings about one "
     "binary, which reads as two faults",
     [('        elif len(hits) > 1:\n'
       '            rows.append(("warn", f"{tool} is shadowed",',
       '        if len(hits) > 1:\n'
       '            rows.append(("warn", f"{tool} is shadowed",')],
     [T_PATH]),
    # ⛔ D10 REWRITTEN 2026-08-22. Its first version replaced the findings with
    # an empty dict, so the section rendered nothing — a real defect, but one
    # only an executed `run_doctor` could observe, and this file exists BECAUSE
    # `run_doctor` cannot be executed. A mutant that asks for something no test
    # can reach is a harness fault. This one stays inside the renderer, where a
    # source pin genuinely settles it: a warning that falls through to the
    # `else` prints as a dim note and never counts as an issue.
    ("D10", "under", "a warning renders as a dim note, so a shadowed binary "
     "never reaches the issue count or the summary",
     [('        elif _lvl == "warn":', '        elif False:')],
     [T_PATH]),
    ("D11", "under", "the findings produce actions that never reach the summary",
     [('    manual_actions.extend(_spf["actions"])', '    pass')],
     [T_PATH]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def snapshot() -> dict[str, str]:
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before: dict[str, str]) -> list[str]:
    return [f for f, text in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != text]


def main() -> int:
    before = snapshot()

    print("baseline… ", end="", flush=True)
    ok, timed_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if timed_out else 'RED'}. Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, direction, why, edits, tests in MUTANTS:
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            if not tests:
                raise ValueError("no tests declared")
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:70]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, timed_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed, fix it)" if timed_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif timed_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}")
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in "
              "your source:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (harness faults — these measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
