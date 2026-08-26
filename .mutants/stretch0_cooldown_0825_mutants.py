"""Mutation harness for stretch 0 — the cooldown refusal, in the agents.

⛔ WHAT THIS CODE DECIDES. Not whether a refusal is delivered — 8L already
proved that — but whether the SENTENCE it is delivered in is true. The machine
keeps two waits and reports neither: the whole per-person window when the same
account asks twice, and a much shorter unkeyed floor when anybody else who uses
that computer went first. Every client named the long one. On a research
computer several people share, the short one is the ordinary case, so the copy
overstated the wait roughly tenfold for the audience the wave had just admitted.

⭐⭐ THE SHARPEST MUTANTS HERE:
  CD1/CD2 — the duration comes back, in ONE client. Nothing used to notice:
            the cross-file test compared error-class KEYS and never the words,
            so the two clients could describe the same refusal differently and
            stay green. CD2 is the one that would have shipped.
  CD4     — the OTHER number. "wait a minute" is exactly as wrong as "ten
            minutes", in the opposite direction and for the opposite person,
            which is why the fix bans durations rather than correcting one.
  R1/R2   — the two windows are made equal. The copy's whole premise is that
            they differ; nothing anywhere pinned it, and `SEND_LOGS_MACHINE_
            FLOOR_SEC` had zero test references in either suite.
  R3      — the floor is dropped. A co-tenant is never refused at all, which
            reads as a FIX until N sharers each build a bundle at once.
  W1      — the skill document goes back to telling the assistant that "give it
            ten minutes" is the honest answer, so the wrong number reaches a
            person through the document even with both clients corrected.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor.

⚠ TWO SUITES, AND BOTH MUST BE GREEN FOR A MUTANT TO COUNT AS SURVIVING. The
copy lives in the agent package and the constants it depends on live in
`research.py`, which is a different program with a different pytest rootdir.
A harness that ran only one leg would call every `research.py` mutant a kill.

    .venv/bin/python .mutants/stretch0_cooldown_0825_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The agent leg: the three send-logs suites, which between them hold the refusal
# copy, the cross-client parity and the duration ban.
AGENT_SUITES = ("tests/test_send_logs_cli_0825.py "
                "tests/test_send_logs_skill_0825.py "
                "tests/test_send_logs_agent_0825.py")

# The backend leg: the cooldown's own behaviour. Narrow on purpose — the root
# suite is 6k tests and none of the rest can see these edits.
ROOT_SUITES = ("tests/test_send_logs_command_0818.py "
               "tests/test_machine_optin_0825.py "
               "tests/test_send_logs_summary_0825.py "
               # ⭐ The nested-checkout exclusion, which is what stopped the root
               # suite being red on any machine that had staged an org snapshot.
               # Its implementation lives in the test file with the assertion
               # that kills it — same file, but not the same function.
               "tests/test_stdlib_log_bridge_0817.py")

CLI = "agent/facade/cli.py"
SR = "agent/facade/skill/scripts/sr.py"
SKILL = "agent/facade/skill/SKILL.md"
BE = "research.py"
LOG = "tests/test_stdlib_log_bridge_0817.py"
MUTATED_FILES = (CLI, SR, SKILL, BE, LOG)

SURVIVOR_CONFIRMATIONS = 2

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ CD — the duration comes back ═══════════════════════════════
    ("CD1", CLI, "over",
     "⛔⛔ the terminal client names ten minutes again — the long wait, said to "
     "somebody whose real wait is a minute because a co-tenant went first",
     [('    "CooldownActive": "that computer built a bundle very recently, perhaps "\n'
       '                      "for someone else who uses it — try again shortly",',
       '    "CooldownActive": "that computer built a bundle very recently — give it "\n'
       '                      "ten minutes and ask again",')]),
    ("CD2", SR, "over",
     "⛔⛔ THE ONE THAT WOULD HAVE SHIPPED. Only the CHAT client regresses, and "
     "the cross-file test compared error-class keys rather than words, so two "
     "clients describing one refusal differently was green",
     [('    "CooldownActive": "that computer built a bundle very recently, perhaps "\n'
       '                      "for someone else who uses it — try again shortly",',
       '    "CooldownActive": "that computer built a bundle very recently — give it "\n'
       '                      "ten minutes and ask again",')]),
    ("CD3", CLI, "under",
     "the sentence stops saying what to do — a person is told a bundle went "
     "recently and left to guess whether asking again is worth trying",
     [('"for someone else who uses it — try again shortly",',
       '"for someone else who uses it",')]),
    ("CD4", CLI, "over",
     "⛔ THE OTHER NUMBER, AND IT IS EXACTLY AS WRONG. A minute is the floor, "
     "so this understates by ten for the person who pressed twice — which is "
     "why the fix bans durations instead of correcting one",
     [('"for someone else who uses it — try again shortly",',
       '"for someone else who uses it — wait a minute and ask again",')]),
    ("CD5", SR, "over",
     "the two clients drift apart in wording without either naming a duration: "
     "same machine, same refusal, two different accounts of it",
     [('    "CooldownActive": "that computer built a bundle very recently, perhaps "\n'
       '                      "for someone else who uses it — try again shortly",',
       '    "CooldownActive": "that computer is busy — try again shortly",')]),

    # ═══════════ W — the document the assistant reads ═══════════════════════
    ("W1", SKILL, "over",
     "⛔⛔ the document goes back to calling \"give it ten minutes\" the honest "
     "answer, so the wrong number reaches a person through the assistant even "
     "with both client tables corrected",
     [('- **A cooldown is not always ten minutes.** That is the window for the same\n'
       '  person asking twice; somebody refused because another user of that computer\n'
       '  asked first waits about a minute. The machine tells us only that it refused,\n'
       '  never how long is left — so say "shortly", never a number, and never retry\n'
       '  on a loop.',
       '- One bundle per ten minutes per person. "Give it ten minutes" is the honest\n'
       '  answer to a cooldown, not a retry loop.')]),
    ("W2", SKILL, "under",
     "the instruction not to quote a duration goes, leaving only the two "
     "windows described — from which a model reconstructs a single number",
     [('never how long is left — so say "shortly", never a number, and never retry\n',
       'never how long is left — so answer plainly, and never retry\n')]),
    ("W3", SKILL, "under",
     "the second window is dropped, so the document describes one wait again "
     "and the co-tenant case disappears from what the assistant knows",
     [('  person asking twice; somebody refused because another user of that computer\n'
       '  asked first waits about a minute. The machine tells us only that it refused,\n',
       '  person asking twice. The machine tells us only that it refused,\n')]),

    # ═══════════ R — the constants the copy depends on ══════════════════════
    ("R1", BE, "over",
     "⛔⛔ the floor is widened to the whole window, which recreates the shared "
     "lockout the split exists to fix — one co-tenant's press holds everybody "
     "else out for ten minutes",
     [("SEND_LOGS_MACHINE_FLOOR_SEC = 60", "SEND_LOGS_MACHINE_FLOOR_SEC = 10 * 60")]),
    ("R2", BE, "over",
     "the per-person window shrinks to the floor, so one account can rebuild "
     "and re-upload a 64 MB archive every minute, all day",
     [("SEND_LOGS_COOLDOWN_SEC = 10 * 60", "SEND_LOGS_COOLDOWN_SEC = 60")]),
    ("R3", BE, "under",
     "⛔ THE FLOOR IS DROPPED ENTIRELY. It reads as a fix — nobody is refused "
     "for somebody else's press any more — right up until N sharers build N "
     "archives at once on one machine",
     [("    remaining = max(0, int(float(floor) - (at - machine_last)))",
       "    remaining = 0")]),
    ("R4", BE, "under",
     "the per-person branch holds people for the FLOOR instead of the window, "
     "so hammering the button is bounded at a minute rather than at ten",
     [("        remaining = max(remaining, int(float(cooldown) - (at - mine)))",
       "        remaining = max(remaining, int(float(floor) - (at - mine)))")]),
    ("R5", BE, "under",
     "a submitter with no recorded press is given the OWNER's window off the "
     "machine stamp, so a co-tenant's first ever attempt waits ten minutes — "
     "the overstatement the copy used to make, made true in the wrong direction",
     [("    per_uid = stamp.get(\"perUid\")\n    key = str(uid or \"\")",
       "    per_uid = stamp.get(\"perUid\")\n    key = \"\"")]),
    # ═══════════ L — the guard that made the whole suite red ════════════════
    ("L1", LOG, "under",
     "⛔⛔ the nested-checkout exclusion goes, so a staging worktree inside the "
     "repo is scanned as shipped code and the ENTIRE root suite goes red on any "
     "machine that has staged an org snapshot — green on a clean checkout",
     [("        if _inside_a_nested_checkout(path):\n            continue\n", "")]),
    ("L2", LOG, "over",
     "⛔ the walk stops at the FIRST `.git` it finds going up, which is this "
     "repository's own — so every file is treated as foreign and the scan "
     "returns nothing at all while reporting no missing loggers",
     [("        if parent == ROOT:\n            return False\n", "")]),
    ("L3", LOG, "under",
     "a nested checkout is detected and then scanned anyway — the check runs, "
     "costs its stat calls, and decides nothing",
     [('        if (parent / ".git").exists():\n            return True',
       '        if (parent / ".git").exists():\n            return False')]),
]

def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache() -> None:
    for d in ROOT.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *MUTATED_FILES,
              "agent/tests", "tests"], cwd=ROOT).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    """Both legs, and both must pass.

    ⛔ The agent package and `research.py` are separate programs with separate
    rootdirs. A single-leg harness would report every constant mutant as killed
    while never having run the suite that could see it."""
    purge_pycache()
    agent_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
    agent = sh([sys.executable, "-B", "-m", "pytest", *AGENT_SUITES.split(),
                "-q", "-p", "no:cacheprovider"],
               cwd=ROOT / "agent", env=agent_env)
    if agent.returncode != 0:
        return False
    backend = sh([sys.executable, "-B", "-m", "pytest", *ROOT_SUITES.split(),
                  "-q", "-p", "no:cacheprovider"],
                 cwd=ROOT, env=ENV)
    return backend.returncode == 0


def main() -> int:
    only = {a.strip() for a in sys.argv[1:] if a.strip()}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — this is a spot check, "
              f"not a score for the stretch.")

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
    for mid, fname, direction, why, edits in selected:
        path = ROOT / fname
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
            # ⛔⛔ COMPILED BEFORE IT IS WRITTEN. A mis-indented anchor still
            # substring-matches and yields an unparseable file; the suite then
            # goes red on an import error and the mutant reports a kill it
            # never earned.
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as syn:
                    raise AssertionError(
                        f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                        "check the anchor's indentation") from None
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

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the stretch's score)" if only else ""
    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed "
          f"({over} over-corrections){label}")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
