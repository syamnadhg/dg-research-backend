"""Mutation harness — disconnect removes every chat's watcher, and says so (2026-09-23).

⛔⛔ WHAT THIS CODE DECIDES. Whether a full `disconnect` on a computer that serves
several chats from one HERMES_HOME leaves any chat's watcher behind — an orphan
job that fires "Script not found" on every tick after the bridge it needed is
gone — and whether the person is told, before they say yes, that a full removal
takes EVERY chat's watcher and not only the one asking.

⭐ THE OWNER DECIDED THE BEHAVIOUR STAYS (host-wide, on purpose). So most of these
mutants NARROW the sweep, and each must be killed by a test that EXECUTES
`_remove_stream_cron` on a real jobs.json. The two clauses that identify a chat's
watcher — its NAME and its generated SHIM — are each load-bearing only because
the tests hold one job identified by name alone and one by shim alone; with both
jobs shaped the same, dropping either clause would be an equivalent mutant.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

    python .mutants/agent_disconnect_every_chat_0923_mutants.py
    python .mutants/agent_disconnect_every_chat_0923_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

CONNECT = "agent/facade/connect.py"
SR = "agent/facade/skill/scripts/sr.py"
SKILL = "agent/facade/skill/SKILL.md"
OURS = (CONNECT, SR, SKILL)

# ⭐ THE GUARDS THIS CHANGE ADDED OR RE-AIMED, and the only tests the score is about.
MINE = ("tests/test_disconnect_every_chat_0923.py "
        "tests/test_connect.py")
MIN_SELECTED = 60

ALL_SUITES = "tests/"

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    ("N1", CONNECT, "under",
     "⛔⛔ THE SWEEP NARROWS TO THE SHARED WATCHER ONLY — every chat's own "
     "watcher is left behind after a full teardown, firing 'Script not found' on "
     "every tick against a bridge that no longer exists",
     [('    return (name in _OUR_JOB_NAMES or name.startswith("sr-stream-")\n'
       '            or script == _STREAM_SCRIPT or script == "sr_update_notice.py"\n'
       '            or bool(_POLL_SHIM_RE.fullmatch(script)))',
       '    return (name in _OUR_JOB_NAMES or script == _STREAM_SCRIPT)')]),
    ("N2", CONNECT, "under",
     "⛔ THE NAME CLAUSE GOES, so a chat's watcher identified by its name alone "
     "survives disconnect",
     [('name in _OUR_JOB_NAMES or name.startswith("sr-stream-")',
       'name in _OUR_JOB_NAMES')]),
    ("N3", CONNECT, "under",
     "the SHIM clause goes, so a watcher whose name drifted but still runs our "
     "generated shim survives",
     [('\n            or bool(_POLL_SHIM_RE.fullmatch(script)))', ')')]),
    ("N4", CONNECT, "over",
     "⛔⛔ THE SWEEP TAKES A JOB THAT IS NOT OURS — any name at all, so another "
     "skill's cron entry is deleted by a Super Research disconnect",
     [('name.startswith("sr-stream-")', 'name.startswith("")')]),
    ("N5", SKILL, "under",
     "⛔ SKILL.md's CONFIRM GOES BACK TO 'fully remove skill + bridge?' — true of "
     "the calling chat and silent about every other chat on the computer",
     [("fully remove Super Research from this computer: skill, bridge and every "
       "chat's watcher?", "fully remove skill + bridge?")]),
    ("N6", SR, "under",
     "the ROUTER's confirm goes back to the old wording, so the two doors that ask "
     "this question disagree about what a full removal takes",
     [("computer — the skill, the bridge and every chat’s watcher? ", "machine? ")]),
    ("N7", CONNECT, "under",
     "the sweep's docstring goes back to calling it an open question, which invites "
     "the next reader to 'fix' the decided behaviour",
     [("(owner decision, 2026-09-23)", "(an owner question)")]),
]




def _py() -> str:
    """The interpreter to run the agent suite under.

    ⛔ THE MAC'S VENV WHEN IT EXISTS, OTHERWISE THIS INTERPRETER. The runner this
    was copied from hardcodes `agent/.venv/bin/python`, which does not exist on
    Windows (production here) or in a WSL test venv — there the harness could
    not run at all. The fallback is the interpreter that launched the harness,
    which already has pytest if it can run this file's baseline.
    """
    venv = AGENT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable

def _mark(mid: str, fname: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _refuse_if_a_previous_run_died() -> "str | None":
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _path_for(fname: str) -> Path:
    return ROOT / fname


def _digest() -> dict:
    """Content hash of every file this harness can touch.

    ⭐ CONTENT, NOT `git status`. Uncommitted work is the normal state mid-wave, so
    a git check would report dirty on every run and a real leftover mutant would
    be invisible inside that noise."""
    return {f: hashlib.sha256(_path_for(f).read_bytes()).hexdigest() for f in OURS}


def _pytest(args, cwd, env) -> str:
    """'green' | 'red' | 'nothing-collected'.

    ⛔⛔ EXIT 5 IS NOT A FAILURE. pytest returns 5 when nothing is collected, and a
    runner that only asks `returncode == 0` reads that as red — so one typo in the
    selection would score every mutant killed against zero tests."""
    code = sh(args, cwd=cwd, env=env).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(filtered: bool) -> bool:
    purge_pycache(AGENT)
    py = _py()
    suites = MINE.split() if filtered else [ALL_SUITES]
    out = _pytest([py, "-B", "-m", "pytest", *suites, "-q", "-p", "no:cacheprovider"],
                  AGENT, ENV)
    if out == "nothing-collected":
        raise AssertionError("the agent leg collected NO tests — check the selection")
    return out == "green"


def _selected_count() -> int:
    py = _py()
    out = sh([py, "-B", "-m", "pytest", *MINE.split(), "--collect-only", "-q",
              "-p", "no:cacheprovider"], cwd=AGENT, env=ENV).stdout
    # ⛔ THE SUMMARY LINE IS "N tests collected in 0.09s" — it does not END with
    # "collected", and a parser that assumed it did returned 0 and refused the run.
    # That refusal is the guard working; this is the parser it was guarding.
    import re as _re
    m = _re.search(r"^(\d+) tests? collected", out, _re.M)
    return int(m.group(1)) if m else 0


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — a spot check, not a score.")
    print("scope: THE WHOLE AGENT SUITE (--unfiltered)" if unfiltered
          else "scope: THIS WAVE'S OWN GUARDS ONLY — pass --unfiltered for the other number")

    stranded = _refuse_if_a_previous_run_died()
    if stranded:
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {stranded}\nRestore that file, then delete\n    {_INFLIGHT}")
        return 2

    if not unfiltered:
        n = _selected_count()
        print(f"the wave's own files collect {n} test(s)")
        if n < MIN_SELECTED:
            print(f"⛔⛔ TOO FEW (need >= {MIN_SELECTED}) — a selection that matches "
                  "nothing exits 5 and scores every mutant killed. Refusing to run.")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests(filtered=not unfiltered):
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green\n")

    survivors, faults = [], []
    for mid, fname, direction, why, edits in selected:
        path = _path_for(fname)
        original = path.read_text(encoding="utf-8")
        original_bytes = path.read_bytes()
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            # ⛔⛔ COMPILED BEFORE IT IS WRITTEN. A mis-indented anchor still
            # substring-matches and yields an unparseable file; the suite then goes
            # red on an import error and the mutant banks a kill it never earned.
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as syn:
                    raise AssertionError(
                        f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                        "check the anchor's indentation") from None
            _mark(mid, fname)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests(filtered=not unfiltered)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                again = not run_tests(filtered=not unfiltered)
                if again != killed:
                    flapped = True
                    killed = False
            mark = "✓ killed  " if killed and not flapped else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed or flapped:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            # ⛔ BYTES, NOT TEXT: on Windows a text restore turns LF into CRLF
            # and the leftover check below then cries wolf on a clean tree.
            path.write_bytes(original_bytes)
            _unmark()

    after = _digest()
    leftover = [f for f in before if before[f] != after[f]]
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the wave's score)" if only else ""
    scope = " [whole agent suite]" if unfiltered else " [own guards]"
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
