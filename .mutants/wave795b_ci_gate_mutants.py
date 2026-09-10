"""Mutation harness — THE CI GATE NOBODY WAS READING
(wave 7.9-5 tail, 2026-09-10. The four failures that surfaced the moment the
lint floor stopped short-circuiting the job.)

⛔⛔ WHAT THIS IS ABOUT. 7.9-5 fixed a PEP 701 f-string that had CI's "Lint —
correctness floor" step red since 09-05, and I recorded that as "CI red for six
waves". It was worse than that. The lint step runs FIRST in the same job, so
while it was failing the `Run tests` and `Run agent tests` steps reported
`skipped` — and once lint went green they ran for the first time since
**2026-08-26** and came back with FOUR failures, none of which reproduce on this
machine. Fifteen days, ~26 runs, two suites, and the red looked like one problem.

⛔⛔ ALL FOUR WERE GUARDS THAT ONLY WORK WHERE THEY WERE WRITTEN:
  · the anchor sweep reads THREE checkouts — this repo, the app repo and the
    fork — and CI has one, so 84 anchors reported "target file(s) not found",
    i.e. as STALE, on a runner that never had those files.
  · a bump-version test asserted against the REAL sibling app checkout, on
    purpose, with a docstring explaining that a fixture would prove less. It
    proved nothing at all on a runner that has no sibling.
  · TWO retention tests back-dated a file's mtime and expected the prune to
    retire it. macOS CLAMPS `st_birthtime` to a back-dated mtime (measured), so
    the fallback answered "40 days" here; Linux has no birthtime, seeds the
    clock, and KEEPS the file. `research.py`'s own comment on that branch says
    it "is the one that matters" because the fleet is Linux. The tests pinned a
    kernel accident and the fleet's path was never asserted at all.

⭐⭐ SO THE MUTANTS COME FROM THE FAILURES, not from my repair list — same rule
as the wave this is the tail of, and the same reason: the fixes and their guards
would otherwise be written from one mental model and scored by it.

⛔⛔ THE SHARPEST ONES:
  S2 — the concession is keyed on the FILE being missing instead of the ROOT
       being absent. That is "missing files are fine", which is the failure this
       whole tool exists to catch, and on a full checkout it is INVISIBLE: with
       nothing missing, "excuse everything" and "excuse only what an absent repo
       explains" look identical. It needs a file hidden deliberately.
  S3 — excused anchors keep counting as COMPARED, so the >400 floor that is
       supposed to stop a one-checkout run going vacuous is satisfied by anchors
       nobody looked at.
  S4 — a mutant naming two files needs BOTH gone before it reports as missing.
       With one present it sums hits across whatever is there and reports
       `matches 0x` — drift, in a file that is perfectly fine. 48 mutants
       declare more than one target file today.
  R1 — the fallback reads mtime instead of the marker: the macOS accident made
       law. Green on this machine, red on the fleet.
  R2 — an undated tail is aged from the epoch instead of the clock, so the first
       boot after an upgrade deletes every tail on the machine.
  B1 — the probe prefers the `research-app/web` layout that never existed, which
       is the original defect with the fix's own candidate list in place.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⛔⛔ ONE LEG. Every file here is read by the ROOT suite; `_leg_for` sends them
all to it. The agent constants below are kept only so the shared runner keeps
its shape — nothing in this wave routes to that leg.

    .venv/bin/python .mutants/wave795b_ci_gate_mutants.py
    .venv/bin/python .mutants/wave795b_ci_gate_mutants.py --unfiltered
"""
from __future__ import annotations

import hashlib
import os
import re as _re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

SWEEP = ".mutants/_anchor_sweep.py"
BUMP = "tools/bump_version.py"
RESEARCH = "research.py"
OURS = (SWEEP, BUMP, RESEARCH)

MINE_AGENT = "tests/"
MINE_ROOT = ("tests/test_mutation_harness_anchors.py "
             "tests/test_bump_version.py "
             "tests/test_retention_0901.py")
MIN_SELECTED_AGENT = 1
MIN_SELECTED_ROOT = 70

ALL_AGENT = "tests/"
ALL_ROOT = "tests/"

# ⛔ EVERY file in this wave is root-read. `.mutants/_anchor_sweep.py` is a tool
# rather than a source file, and it is the ROOT suite that imports it.
ROOT_LEG_FILES = (SWEEP, BUMP, RESEARCH)

_SOLO: "set[str]" = set()

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")


_CLASSIFY = """                    if missing:
                        unreachable.append(
                            (name, mid, why + f" — not this checkout's call, "
                                              f"missing root(s): {missing}"))
                    else:
                        bad.append((name, mid, why))"""

MUTANTS = [
    ("S1", SWEEP, "under",
     "⛔⛔ THE SPLIT GOES. A target file that resolves nowhere is STALE again "
     "whatever the reason, which is the state that had 84 healthy anchors "
     "reported as drift on every runner for fifteen days",
     [(_CLASSIFY, "                    bad.append((name, mid, why))")]),

    ("S2", SWEEP, "over",
     "⛔⛔ THE CONCESSION IS KEYED ON THE FILE, NOT THE ROOT — so every missing "
     "file is excused and a fork file somebody renamed is excused with them. "
     "INVISIBLE on a full checkout: nothing is missing, so this and the correct "
     "rule behave identically until a file is hidden on purpose",
     [(_CLASSIFY, "                    unreachable.append((name, mid, why))")]),

    ("S3", SWEEP, "over",
     "⛔⛔ AN EXCUSED ANCHOR STILL COUNTS AS COMPARED, so the floor that stops a "
     "one-checkout run going vacuous is satisfied by anchors nobody read",
     [("                gone = [f for f, t in zip(files, texts) if t is None]",
       "                checked += 1\n"
       "                gone = [f for f, t in zip(files, texts) if t is None]"),
      ("                checked += 1\n"
       "                hits = sum((t or \"\").count(frm) for t in texts)",
       "                hits = sum((t or \"\").count(frm) for t in texts)")]),

    ("S4", SWEEP, "under",
     "⛔ A PARTIAL FILE SET IS SUMMED AROUND AGAIN: a mutant naming two files "
     "needs BOTH gone before it reports missing, so with one present its anchor "
     "reports `matches 0x` — drift, in a file that is fine. 48 mutants declare "
     "more than one target file",
     [("                gone = [f for f, t in zip(files, texts) if t is None]",
       "                gone = files if all(t is None for t in texts) else []")]),

    ("S5", SWEEP, "over",
     "the sweep claims every target checkout is present, so the concession never "
     "fires and CI is red exactly as before — the fix reverted from the other end",
     [("    return [name for name, path in ROOTS if not os.path.isdir(path)]",
       "    return []")]),

    ("R1", RESEARCH, "under",
     "⛔⛔ THE MARKER IS IGNORED AND mtime DECIDES — the macOS accident made law. "
     "`utime` drags birthtime back on this machine so it reads 40 days; on the "
     "fleet's Linux boxes it reads the last append and nothing is ever retired",
     [("        stamp = float(marker.read_text(encoding=\"utf-8\").strip())",
       "        stamp = float(Path(path).stat().st_mtime)")]),

    ("R2", RESEARCH, "over",
     "⛔⛔ AN UNDATED TAIL IS AGED FROM THE EPOCH instead of the clock, so the "
     "first boot after an upgrade decides every existing tail is infinitely old "
     "and deletes all of them — the outcome the code says is worse than keeping "
     "them too long",
     [("    seeded = now_t\n    try:\n        st = Path(path).stat()",
       "    seeded = 0.0\n    try:\n        st = Path(path).stat()")]),

    ("R3", RESEARCH, "under",
     "the marker outlives the file it dates, so the next generation inherits a "
     "deadline belonging to a tail nobody can read any more",
     [("                _raw_tail_marker(path).unlink()",
       "                pass")]),

    ("B1", BUMP, "over",
     "⛔⛔ THE PROBE PREFERS THE LAYOUT THAT NEVER EXISTED. The candidate list is "
     "in place and ordered wrong, so the release sync targets `research-app/web` "
     "again wherever both are on disk — the original defect, wearing its fix",
     [("        root.parent / \"dg-research\",\n"
       "        root.parent / \"research-app\" / \"web\",",
       "        root.parent / \"research-app\" / \"web\",\n"
       "        root.parent / \"dg-research\",")]),

    ("B2", BUMP, "under",
     "the app repo is not a candidate at all, which is the state that made "
     "`sync_fe_twin` short-circuit before it reached the argument fix",
     [("        root.parent / \"dg-research\",\n"
       "        root.parent / \"research-app\" / \"web\",",
       "        root.parent / \"research-app\" / \"web\",")]),

    ("B3", BUMP, "over",
     "the probe stops probing and returns the first candidate whether or not it "
     "holds the sync script, so a checkout using the old layout silently syncs "
     "nothing",
     [("        if (c / \"scripts\" / \"sync-agent-skill.mjs\").is_file():",
       "        if True:")]),
]

def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


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


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _path_for(fname: str) -> Path:
    return ROOT / fname


def _digest() -> dict:
    """Content hash of every file this harness can touch.

    ⭐ CONTENT, NOT `git status`. Uncommitted work is the normal state mid-wave,
    so a git check would report dirty on every run and a real leftover mutant
    would be invisible inside that noise."""
    return {f: hashlib.sha256(_path_for(f).read_bytes()).hexdigest() for f in OURS}


def _pytest(args, cwd, env) -> str:
    """'green' | 'red' | 'nothing-collected'.

    ⛔⛔ EXIT 5 IS NOT A FAILURE. pytest returns 5 when nothing is collected, and
    a runner that only asks `returncode == 0` reads that as red — so one typo in
    the selection would score every mutant killed against zero tests."""
    code = sh(args, cwd=cwd, env=env).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def _leg_for(fname: str) -> str:
    """Which suite can SEE a repair to this file.

    ⛔⛔ THE REASON THIS EXISTS. Every harness before this one ran the agent
    suite only, which was right while every wave was agent-only. This wave
    repaired `research.py` (the f-string that had CI's lint floor red for six
    pushes) and a ROOT-suite harness guard — and an agent-only runner would have
    scored both as killed without running one test that could see them. A score
    is only a score if the tests it ran could have failed."""
    return "root" if fname in ROOT_LEG_FILES else "agent"


def _leg_conf(leg: str):
    if leg == "root":
        return (ROOT, str(ROOT / ".venv" / "bin" / "python"),
                MINE_ROOT.split(), [ALL_ROOT], MIN_SELECTED_ROOT)
    return (AGENT, str(AGENT / ".venv" / "bin" / "python"),
            MINE_AGENT.split(), [ALL_AGENT], MIN_SELECTED_AGENT)


def run_tests(filtered: bool, leg: str = "agent") -> bool:
    cwd, py, mine, allsuites, _floor = _leg_conf(leg)
    purge_pycache(cwd if leg == "root" else AGENT)
    suites = mine if filtered else allsuites
    out = _pytest([py, "-B", "-m", "pytest", *suites, "-q", "-p", "no:cacheprovider"],
                  cwd, ENV)
    if out == "nothing-collected":
        raise AssertionError(f"the {leg} leg collected NO tests — check the selection")
    return out == "green"


def _selected_count(leg: str) -> int:
    cwd, py, mine, _all, _floor = _leg_conf(leg)
    out = sh([py, "-B", "-m", "pytest", *mine, "--collect-only", "-q",
              "-p", "no:cacheprovider"], cwd=cwd, env=ENV).stdout
    m = _re.search(r"^(\d+) tests? collected", out, _re.M)
    return int(m.group(1)) if m else 0


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if not only:
        selected = [m for m in selected if m[0] not in _SOLO]

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

    legs = sorted({_leg_for(m[1]) for m in selected})
    if not unfiltered:
        for leg in legs:
            n = _selected_count(leg)
            floor = _leg_conf(leg)[4]
            print(f"the wave's own {leg} files collect {n} test(s)")
            if n < floor:
                print(f"⛔⛔ TOO FEW on the {leg} leg (need >= {floor}) — a selection "
                      "that matches nothing exits 5 and scores every mutant killed. "
                      "Refusing to run.")
                return 2

    before = _digest()
    for leg in legs:
        print(f"baseline [{leg}]… ", end="", flush=True)
        if not run_tests(filtered=not unfiltered, leg=leg):
            print("RED — fix the tree before mutating")
            return 2
        print("green")

    survivors, faults = [], []
    for mid, fname, direction, why, edits in selected:
        path = _path_for(fname)
        original = path.read_text(encoding="utf-8")
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
            # substring-matches and yields an unparseable file; the suite then
            # goes red on an import error and the mutant banks a kill it never
            # earned.
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
            leg = _leg_for(fname)
            killed = not run_tests(filtered=not unfiltered, leg=leg)
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                again = not run_tests(filtered=not unfiltered, leg=leg)
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
            path.write_text(original, encoding="utf-8")
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
