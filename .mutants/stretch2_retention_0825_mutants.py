"""Mutation harness for stretch 2B — the retention sentence, in four programs.

⛔ WHAT THIS CODE DECIDES. Not whether a bundle is deleted — a GCS lifecycle rule
does that, and no test can see it — but whether the four programs that describe
the deletion describe the same one. "Deleted automatically after 30 days" was
held out of every client for months because no bucket lifecycle rule existed
anywhere, so the sentence was a promise nothing kept. One was applied to the
`logs/` prefix on 2026-08-26 (action Delete, age 30) and read back by
`gcloud storage buckets describe` and `gsutil lifecycle get` independently; the
gate flipped and the copy landed in the same change.

⭐⭐ THE SHARPEST MUTANTS HERE:
  B4 — ONE client goes silent. Three programs promise a retention and the fourth
       says nothing, which is exactly the drift the cross-client value test was
       written for after the cooldown wave — and that test covers only the two
       backend tables, not the plans they print.
  B6 — the FORK goes silent. It is in NO cross-client test at all: nothing in
       either repo reads it, so its agreement with the others is luck.
  B2 — the promise is widened from the FILES to the RECORD. The rule deletes the
       object; the index row naming it is not covered by the rule, and its own
       TTL was measured undeployed the same day. That row carries no log content,
       which is what makes the sentence honest — and is not what would make "we
       keep no record" honest.
  B8 — the wrong CLOCK. The rule counts from the object's creation, i.e. the
       upload. The row's `expireAt` is stamped when the row opens, before a byte
       moves, and is never refreshed. "After 30 days" describes the half that
       does no deleting.
  B9 — the fork's duration ban loses its abbreviations, so "10 min" would pass a
       guard whose entire subject is durations. It was in that state until today
       while the backend's twin was not, and both read green.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor — it never reached the file, so it says
nothing about the suite in either direction.

⚠ THREE LEGS, AND ALL THREE MUST BE GREEN. The copy lives in the agent package,
the gate lives in `research.py` at the repo root, and the fourth client lives in
a DIFFERENT REPOSITORY with its own virtualenv. A harness that ran fewer legs
would report every mutant outside its own leg as killed.

    .venv/bin/python .mutants/stretch2_retention_0825_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORK = ROOT.parent / "dg-hermes-fleet"

AGENT_SUITES = ("tests/test_send_logs_cli_0825.py "
                "tests/test_send_logs_skill_0825.py")

ROOT_SUITES = ("tests/test_send_logs_cli_0818.py "
               "tests/test_send_logs_command_0818.py")

FORK_SUITES = "skills/tests/test_super_research_skill.py"

CLI = "agent/facade/cli.py"
SR = "agent/facade/skill/scripts/sr.py"
BE = "research.py"
# ⚠ RELATIVE TO THE FORK, not to this repo. Kept in its own tuple so a path
# mix-up cannot silently write into the wrong tree.
FORK_SR = "skills/super-research/scripts/sr.py"
FORK_TEST = "skills/tests/test_super_research_skill.py"

OURS = (CLI, SR, BE)
THEIRS = (FORK_SR, FORK_TEST)

SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ B — the sentence itself, in each program ═══════════════════
    ("B1", CLI, "over",
     "⚠ the terminal plan names the wrong clock — the rule counts from the "
     "upload, so \"after 30 days\" describes the row's stamp, which does no "
     "deleting and is written before a byte moves",
     [('    print("It is deleted automatically 30 days after it arrives.")',
       '    print("It is deleted automatically after 30 days.")')]),
    ("B2", CLI, "over",
     "⛔⛔ the promise is widened from the FILES to the RECORD. The rule deletes "
     "the object; the index row naming it is not covered by it and its own TTL "
     "was measured undeployed, so a receipt outlives the bundle",
     [('    print("It is deleted automatically 30 days after it arrives.")',
       '    print("It is deleted automatically 30 days after it arrives, and we '
       'keep no record of it.")')]),
    ("B3", CLI, "under",
     "the terminal plan says nothing about how long the logs are kept, so the "
     "one screen whose whole job is to be true about what leaves a computer is "
     "silent on what happens to it afterwards",
     [('    print("It is deleted automatically 30 days after it arrives.")\n', '')]),
    ("B4", SR, "under",
     "⛔⛔ THE ONE THAT WOULD HAVE SHIPPED. Only the CHAT client goes silent, so "
     "three programs promise a retention and the fourth does not — and the "
     "cross-client value test covers the two refusal TABLES, never the plans "
     "these clients print",
     [('        lines.append("It’s deleted automatically 30 days after it arrives.")\n', '')]),
    ("B5", SR, "over",
     "the chat client names the wrong clock while the terminal client names the "
     "right one: same machine, same rule, two accounts of when it fires",
     [('        lines.append("It’s deleted automatically 30 days after it arrives.")',
       '        lines.append("It’s deleted automatically after 30 days.")')]),
    ("B8", BE, "over",
     "⛔ the machine's OWN consent screen names the wrong clock. This is the "
     "screen a person sees when the app cannot reach the computer at all, which "
     "is the case the whole feature exists for",
     [('        lines.append("and it is deleted automatically 30 days after it arrives")',
       '        lines.append("and it is deleted automatically after 30 days")')]),

    # ═══════════ F — the copy furthest from the code ════════════════════════
    ("B6", FORK_SR, "under",
     "⛔⛔ THE FORK GOES SILENT, AND NOTHING BINDS IT. No test in either backend "
     "repo reads this file, so its agreement with the other three is luck — this "
     "is the copy an operator on a fleet box actually reads",
     [('        _say("It is deleted automatically 30 days after it arrives.")\n', '')]),
    ("B7", FORK_SR, "under",
     "⛔ the three facts this plan was MISSING until today go missing again — "
     "result links, the account email, what the agent screens showed. Every "
     "other consent surface names them; a plan that claims to be what somebody "
     "agreed to has to say what actually leaves",
     [('        _say("Also going, from the research picked: links that open those "\n'
       '             "results — anyone holding one can read them; the email address on "\n'
       '             "the account; and what the agent screens showed while that "\n'
       '             "research was working.")\n', '')]),
    ("B9", FORK_TEST, "over",
     "⛔⛔ the fork's duration ban loses its ABBREVIATIONS, so \"10 min\" and "
     "\"1 hr\" would pass a guard whose entire subject is durations. It was in "
     "exactly this state until today while the backend's twin was not, and both "
     "read green — two guards that were never equivalent",
     [('_DURATION_STEMS = ("second", "minute", "hour", " day", "week",\n'
       '                   "sec", "min", "hr", "wk")',
       '_DURATION_STEMS = ("second", "minute", "hour", " day", "week")')]),
    ("B10", FORK_SR, "over",
     "a duration reaches the fork's refusal table in abbreviated form — the "
     "concrete regression B9 makes invisible",
     [('"That computer put something together very recently. Its limit counts "\n'
       '        "everyone who uses it, so it may not have been them. Ask again shortly."',
       '"That computer put something together very recently. Ask again in 10 min."')]),
]


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *OURS, "agent/tests", "tests"],
             cwd=ROOT).stdout
    ours = [f"[be] {ln}" for ln in out.splitlines() if ln and not ln.startswith("?? ")]
    out2 = sh(["git", "status", "--porcelain", "--", *THEIRS], cwd=FORK).stdout
    theirs = [f"[fork] {ln}" for ln in out2.splitlines() if ln and not ln.startswith("?? ")]
    return ours + theirs


def run_tests() -> bool:
    """Three legs, and all three must pass.

    ⛔ The agent package, `research.py` and the fork are three separate programs
    with three separate rootdirs — and the fork has its own virtualenv, because
    its suite imports modules this repo does not have. A harness that ran fewer
    legs would report every mutant outside its own leg as killed."""
    purge_pycache(ROOT)
    agent_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
    agent = sh([sys.executable, "-B", "-m", "pytest", *AGENT_SUITES.split(),
                "-q", "-p", "no:cacheprovider"],
               cwd=ROOT / "agent", env=agent_env)
    if agent.returncode != 0:
        return False
    backend = sh([sys.executable, "-B", "-m", "pytest", *ROOT_SUITES.split(),
                  "-q", "-p", "no:cacheprovider"], cwd=ROOT, env=ENV)
    if backend.returncode != 0:
        return False
    purge_pycache(FORK)
    fork_py = FORK / ".venv" / "bin" / "python"
    if not fork_py.exists():
        raise AssertionError(
            f"the fork's virtualenv is missing at {fork_py} — this harness "
            "cannot measure the fourth client without it, and skipping that leg "
            "would report every fork mutant as killed")
    fork = sh([str(fork_py), "-B", "-m", "pytest", FORK_SUITES,
               "-q", "-p", "no:cacheprovider"], cwd=FORK, env=ENV)
    # ⚠ THIRTEEN PRE-EXISTING FAILURES IN THIS SUITE, and they are not ours: ten
    # environment (a skills-ban helper that needs a real install tree) and three
    # pin gaps. So the fork leg cannot be judged on the exit code — it is judged
    # on the COUNT, which must not grow.
    return _fork_failures(fork.stdout) <= FORK_BASELINE_FAILURES


FORK_BASELINE_FAILURES = 13


def _fork_failures(out: str) -> int:
    for line in reversed(out.splitlines()):
        if " failed" in line and " passed" in line:
            for part in line.replace(",", " ").split():
                if part.isdigit():
                    return int(part)
    return 0 if " passed" in out else 999


def main() -> int:
    only = {a.strip() for a in sys.argv[1:] if a.strip()}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — a spot check, not a score.")

    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    # ⛔ DRY RUN FIRST, AND EVERY PYTHON MUTANT IS COMPILED. A mis-indented
    # anchor still substring-matches and yields an unparseable file; the suite
    # then goes red on an import error and the mutant reports a kill it never
    # earned. Found in seconds here instead of at minute forty.
    faults = []
    for mid, fname, _d, _w, edits in selected:
        base = (FORK if fname in THEIRS else ROOT) / fname
        text = base.read_text(encoding="utf-8")
        for frm, to in edits:
            if frm == to:
                faults.append((mid, "replacement is identical to the anchor")); break
            hits = text.count(frm)
            if hits != 1:
                faults.append((mid, f"anchor occurs {hits}x in {fname} "
                                    f"(needs exactly 1): {frm[:70]!r}")); break
            text = text.replace(frm, to, 1)
        else:
            if fname.endswith(".py"):
                try:
                    compile(text, fname, "exec")
                except SyntaxError as syn:
                    faults.append((mid, f"the mutant does not parse "
                                        f"({syn.lineno}: {syn.msg})"))
    if faults:
        print("⛔ DRY RUN FAILED — these would measure NOTHING:")
        for mid, why in faults:
            print(f"  {mid} {why}")
        return 2
    print(f"dry run: all {len(selected)} anchors resolve and every mutant parses")

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    survivors, broken = [], []
    for mid, fname, direction, why, edits in selected:
        path = (FORK if fname in THEIRS else ROOT) / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(f"anchor occurs {hits}x (needs exactly 1)")
                mutated = mutated.replace(frm, to, 1)
            if fname.endswith(".py"):
                compile(mutated, fname, "exec")
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests()
            flapped = False
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
        except (AssertionError, SyntaxError) as exc:
            # ⛔⛔ A HARNESS FAULT IS NOT A SURVIVOR. The mutant never reached the
            # file, so the suite was never asked — filing it under SURVIVORS
            # reads as "the tests have a gap" and sends you to write an assertion
            # for a defect that was never tested. That cost a round of diagnosis
            # once, on 2026-08-25.
            print(f"! FAULT    {mid} {exc}")
            broken.append((mid, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")

    left = tracked_dirty()
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your "
              "source:\n" + "\n".join(left))
        return 3

    measured = len(selected) - len(broken)
    over = sum(1 for m in selected if m[2] == "over")
    print(f"\n{measured - len(survivors)}/{measured} killed ({over} over-corrections, "
          f"{len(broken)} harness faults counted OUT)")
    if broken:
        print("⚠ HARNESS FAULTS (these measured NOTHING — not suite gaps):")
        for mid, why in broken:
            print(f"  {mid} {why}")
    if survivors:
        print("SURVIVORS (real suite gaps):")
        for mid, direction, why in survivors:
            print(f"  {mid} [{direction}] {why}")
    return 1 if (survivors or broken) else 0


if __name__ == "__main__":
    raise SystemExit(main())
