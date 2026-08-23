"""Mutation harness for wave 5 fix 5 — a background failure with no reader.

⛔ WHAT THIS IS FOR. "Enable On Startup?" defaults to yes, so the common install
has no terminal. When the supervised process dies at SPAWN, it dies before our
own logging exists, so the only record is what launchd or systemd captured on
the way down — and that record reached nobody: macOS wrote it to a directory the
bundle does not collect, Linux wrote it inside site-packages where every update
deleted it, and the doctor read neither.

⭐⭐ THE SHARPEST MUTANTS HERE:
  L1  — the supervisor logs somewhere the collector does not look. Every line is
        still written, every test about its contents still passes, and no
        support bundle ever contains one.
  L3  — Linux goes back to logging inside the install, which an `--update`
        erases — the evidence for the failure the update was meant to fix.
  E5  — an empty log counts as evidence. launchd creates the file at load, so
        that prints a finding on every machine that has ever been supervised.
  E7  — the read is unbounded, on a crash-looping machine's stderr.
  D2  — the doctor reads the evidence and does not print it, which is the same
        dead end in a more expensive form.

⭐ Over-corrections:
  E8  — the first line is dropped even when the whole file was read, so a
        two-line crash report loses half of itself.
  A1  — the collector reaches into the legacy directories, which widens the
        allowlist the consent screen's promise is gated on.

    python .mutants/background_reach_0822_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_REACH = "tests/test_background_failure_reach_0822.py"
# ⛔ The bundle's own file owns the collector these mutants reach through.
T_BUNDLE = "tests/test_log_bundle_0818.py"
ALL = [T_REACH, T_BUNDLE]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ where it is written ═════════════════════════════════════════════
    ("L1", "under", "⛔⛔ the supervisor logs where the collector does not look, "
     "so every line is written and no bundle ever contains one",
     [('def _supervisor_log_dir() -> "Path":',
       'def _supervisor_log_dir() -> "Path":\n'
       '    return Path.home() / "Library" / "Logs" / "SuperResearch"')],
     [T_REACH]),
    ("L2", "under", "macOS goes back to its own directory",
     [('    log_dir = _supervisor_log_dir()\n'
       '    # Python-attributed ops',
       '    log_dir = Path.home() / "Library" / "Logs" / "SuperResearch"\n'
       '    # Python-attributed ops')],
     [T_REACH]),
    ("L3", "under", "⛔⛔ Linux goes back to logging inside the install, which "
     "every `--update` erases",
     [('    log_dir = _supervisor_log_dir()\n'
       '    try:\n'
       '        log_dir.mkdir(parents=True, exist_ok=True)\n'
       '        _SUPERVISOR_UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)',
       '    log_dir = script_dir / "logs"\n'
       '    try:\n'
       '        log_dir.mkdir(parents=True, exist_ok=True)\n'
       '        _SUPERVISOR_UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)')],
     [T_REACH]),
    ("L4", "under", "the directory is not created, so launchd's own open fails "
     "before exec — exit 78, empty logs, a ten-second respawn",
     [('        log_dir.mkdir(parents=True, exist_ok=True)\n'
       '        _SUPERVISOR_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)',
       '        _SUPERVISOR_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)')],
     [T_REACH]),
    ("L5", "under", "the file names drift from the pattern the collector "
     "matches, so the bundle is silently empty again",
     [(r'               re.match(r"^supervisor.*\.log(\.1)?$", name):',
       r'               re.match(r"^supervisord.*\.log(\.1)?$", name):')],
     [T_REACH, T_BUNDLE]),

    # ══ the allowlist stays where it is ═════════════════════════════════
    ("A1", "over", "⛔ the collector reaches into the legacy directories, which "
     "widens the allowlist the consent promise is gated on",
     [('    base = Path(root) if root is not None else _logs_root()\n    wanted = []',
       '    base = Path(root) if root is not None else _logs_root()\n'
       '    wanted = [d / "supervisor.err.log" for d in _legacy_supervisor_log_dirs()\n'
       '              if (d / "supervisor.err.log").is_file()]')],
     [T_REACH]),
    ("A2", "under", "the allowlist stops resolving against the log root at all",
     [('        Path(path).resolve().relative_to(_logs_root().resolve())',
       '        Path(path).resolve().relative_to(Path.home().resolve())')],
     [T_REACH, T_BUNDLE]),

    # ══ reading the last words ══════════════════════════════════════════
    ("E1", "under", "the current location is never looked at, so a migrated "
     "machine reports its evidence as an old build's",
     [('    dirs = [(Path(log_dir) if log_dir is not None else _supervisor_log_dir(), False)]',
       '    dirs = []')],
     [T_REACH]),
    ("E2", "under", "the old locations are never looked at, so every install "
     "that predates this fix is undiagnosable",
     [('    for d in (legacy_dirs if legacy_dirs is not None else _legacy_supervisor_log_dirs()):\n'
       '        dirs.append((Path(d), True))',
       '    pass')],
     [T_REACH]),
    ("E3", "under", "an old location is not reported as one, so the person is "
     "never told why their bundle will not carry it",
     [('        out["legacy"] = is_legacy', '        out["legacy"] = False')],
     [T_REACH]),
    ("E4", "under", "the old location wins over the current one, so a machine "
     "is diagnosed from a log it stopped writing to",
     [('    for d, is_legacy in dirs:', '    for d, is_legacy in dirs[::-1]:')],
     [T_REACH]),
    ("E5", "under", "⛔⛔ an empty log counts as evidence — and launchd creates "
     "that file at load, so this prints a finding on every supervised machine",
     [('        if not rows:\n            continue', '        if False:\n            continue')],
     [T_REACH]),
    ("E6", "under", "it takes the START of the file, so the diagnosis is from "
     "whenever this machine was set up rather than from the last exit",
     [('        out["lines"] = rows[-int(max_lines):]', '        out["lines"] = rows[:int(max_lines)]')],
     [T_REACH]),
    ("E7", "under", "⛔ the read is unbounded, on the stderr of a machine that "
     "has been respawning every ten seconds",
     [('                fh.seek(max(0, size - int(max_bytes)))', '                fh.seek(0)')],
     [T_REACH]),
    ("E8", "over", "the first line is dropped even when the whole file was "
     "read, so a two-line crash report loses half of itself",
     [('        rows = text.splitlines()[1 if size > int(max_bytes) else 0:]',
       '        rows = text.splitlines()[1:]')],
     [T_REACH]),
    ("E9", "under", "a record cut in half by the byte bound is kept, so the "
     "reader is shown an error that did not happen",
     [('        rows = text.splitlines()[1 if size > int(max_bytes) else 0:]',
       '        rows = text.splitlines()')],
     [T_REACH]),
    ("E10", "under", "an unreadable log raises inside the one command a stuck "
     "person was told to run",
     [('        except OSError:\n            continue\n        text = blob.decode',
       '        except ValueError:\n            continue\n        text = blob.decode')],
     [T_REACH]),
    ("E11", "under", "undecodable bytes take the diagnostic down",
     [('        text = blob.decode("utf-8", errors="replace")',
       '        text = blob.decode("utf-8")')],
     [T_REACH]),
    ("E12", "under", "blank lines count as content, so a log of newlines reads "
     "as a crash report",
     [('        rows = [r.rstrip() for r in rows if r.strip()]',
       '        rows = [r.rstrip() for r in rows]')],
     [T_REACH]),

    # ══ the doctor ══════════════════════════════════════════════════════
    ("D1", "under", "the doctor stops reading it, and points back at a section "
     "that reports a crash-looping machine as healthy",
     [('        _ev = _supervisor_evidence()',
       '        _ev = {"path": "", "legacy": False, "lines": []}')],
     [T_REACH]),
    ("D2", "under", "⛔⛔ it reads the evidence and never prints it — the same "
     "dead end in a more expensive form",
     [('            for _evl in _ev["lines"]:\n'
       '                print(f"       {_c(_DIM, _evl[:160])}")',
       '            pass')],
     [T_REACH]),
    ("D3", "under", "a supervised backend that starts and exits is a warning "
     "rather than a failure",
     [('            _fail("daemon-loop not running",\n'
       '                  "the supervisor started it and it exited — its own last words:")',
       '            _warn("daemon-loop not running",\n'
       '                  "the supervisor started it and it exited — its own last words:")')],
     [T_REACH]),
    ("D4", "under", "an old location is not named, so the person is never told "
     "why their bundle will not carry the answer",
     [('            if _ev["legacy"]:', '            if False:')],
     [T_REACH]),
    ("D5", "under", "the old location is named with no way to move it",
     [('                manual_actions.append(_remedy_resurrect())\n        else:\n'
       '            _warn("daemon-loop not running",',
       '        else:\n'
       '            _warn("daemon-loop not running",')],
     [T_REACH]),
    ("D6", "under", "with no evidence it stops naming the file it looked in, so "
     '"nothing there" is not a fact the reader can use',
     [('                  f"nothing in {_supervisor_log_dir() / \'supervisor.err.log\'} either")',
       '                  "supervisor inactive")')],
     [T_REACH]),
    ("D7", "under", "a single enormous line is printed whole, redrawing the "
     "terminal of the person trying to read it",
     [('                print(f"       {_c(_DIM, _evl[:160])}")',
       '                print(f"       {_c(_DIM, _evl)}")')],
     [T_REACH]),
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
