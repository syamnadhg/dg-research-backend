"""Mutation harness for the two false warnings and the zero-second phase.

All three changes make the log say less or say it differently, which is the most
dangerous kind of change to get wrong: the failure mode is silence, and silence
is indistinguishable from health right up until the day it isn't.

So the over-corrections dominate. Silencing Gemini or Claude's missing public
share would hide the exact regression that happened this morning. Silencing
NotebookLM's genuine access failures — a control never found, an option never
clicked, an access never changed — would hide real private links. And the phase
timeline must not start reporting a duration it did not measure.

Safety, learned from an earlier harness on this repo that adopted a mutant as its
own baseline: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/noise_and_durations_0811_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = ("tests/test_share_expectations_0811.py tests/test_phase_durations_0811.py "
          "tests/test_share_links_0811.py tests/test_notebooklm_access_logging.py "
          "tests/test_nlm_access_already_public.py")

MUTANTS = [
    # ── which agents we expect a public share from ──────────────────────────
    ("E1", "over", "Gemini is silenced — this morning's outage would have shipped quietly",
     [('_PUBLIC_SHARE_EXPECTED = ("gemini", "claude")',
       '_PUBLIC_SHARE_EXPECTED = ("claude",)')]),
    ("E2", "over", "Claude is silenced",
     [('_PUBLIC_SHARE_EXPECTED = ("gemini", "claude")',
       '_PUBLIC_SHARE_EXPECTED = ("gemini",)')]),
    ("E3", "over", "every agent is silenced",
     [('_PUBLIC_SHARE_EXPECTED = ("gemini", "claude")',
       '_PUBLIC_SHARE_EXPECTED = ()')]),
    ("E4", "under", "ChatGPT warns again on every run",
     [('_PUBLIC_SHARE_EXPECTED = ("gemini", "claude")',
       '_PUBLIC_SHARE_EXPECTED = ("gemini", "claude", "chatgpt")')]),
    ("E5", "under", "the check is case-sensitive, so a capitalised key never matches",
     [('    return (platform or "").strip().lower() in _PUBLIC_SHARE_EXPECTED',
       "    return platform in _PUBLIC_SHARE_EXPECTED")]),
    ("E6", "over", "an unknown agent is treated as expecting a share",
     [('    return (platform or "").strip().lower() in _PUBLIC_SHARE_EXPECTED',
       '    return (platform or "").strip().lower() not in ("chatgpt",)')]),
    ("E7", "under", "the quiet branch drops the reason, so a real breakage is undiagnosable",
     [('                        log(f"[{name}] using the conversation URL "\n'
       '                            f"({_elapsed_share:.1f}s) — no public share expected "\n'
       '                            f"from this agent ({_detail})", "DEBUG")',
       '                        log(f"[{name}] using the conversation URL "\n'
       '                            f"({_elapsed_share:.1f}s)", "DEBUG")')]),
    ("E8", "over", "the quiet branch warns anyway — the change accomplishes nothing",
     [('                            f"from this agent ({_detail})", "DEBUG")',
       '                            f"from this agent ({_detail})", "WARN")')]),
    ("E9", "over", "the expected branch stops warning",
     [('                            f"NOT viewable by anyone else.", "WARN")',
       '                            f"NOT viewable by anyone else.", "DEBUG")')]),
    ("E10", "over", "the agent is named at the log call again — the drift shape returns",
     [("                    if _public_share_is_expected(agent_key):",
       '                    if agent_key != "chatgpt":')]),

    # ── notebooklm read-back vs notebooklm real failures ────────────────────
    ("N1", "under", "the primary path calls a shared notebook maybe-private again",
     [('                        log(f"NotebookLM shared; could not read the sharing state back "\n'
       '                            f"(the confirmation control no longer matches — detector "\n'
       '                            f"gap, not evidence the link is private): {notebook_url}",\n'
       '                            "DEBUG")',
       '                        log(f"NotebookLM share link OK but public access NOT DOM-verified "\n'
       '                            f"— the link may be private: {notebook_url}", "WARN")')]),
    ("N2", "under", "only one of the two sites was changed",
     [('                            log("[NotebookLM] shared; sharing state could not be read "\n'
       '                                "back (detector gap, not evidence the link is private)",\n'
       '                                "DEBUG")',
       '                            log("[NotebookLM] URL-shape OK but public-share NOT DOM-verified — "\n'
       '                                "downstream link may be private", "WARN")')]),
    ("N3", "over", "the read-back failure goes completely unrecorded",
     [('                        log(f"NotebookLM shared; could not read the sharing state back "\n'
       '                            f"(the confirmation control no longer matches — detector "\n'
       '                            f"gap, not evidence the link is private): {notebook_url}",\n'
       '                            "DEBUG")',
       "                        pass")]),
    ("N4", "over", "⛔ a missing access control stops warning — a real private link goes quiet",
     [('f"[{label}] could not find the \'Notebook access\' control', 'f"[{label}] x')]),
    ("N5", "over", "⛔ an unchanged access setting stops warning",
     [('f"access was NOT changed; the link may be private", "WARN")',
       'f"access was NOT changed; the link may be private", "DEBUG")')]),

    # ── the phase that always took zero seconds ─────────────────────────────
    ("D1", "under", "createdAt is stamped now again — Phase 1 is instantaneous forever",
     [('        meta["createdAt"] = _run_started_ms(queue_dir)',
       '        meta["createdAt"] = int(time.time() * 1000)')]),
    ("D2", "under", "the run start falls back to now even when the files are there",
     [("    return min(stamps) if stamps else int(time.time() * 1000)",
       "    return int(time.time() * 1000)")]),
    ("D3", "under", "the LATER of the two creation files wins",
     [("    return min(stamps) if stamps else int(time.time() * 1000)",
       "    return max(stamps) if stamps else int(time.time() * 1000)")]),
    ("D4", "under", "only config.json is consulted, so an owner-only dir loses its start",
     [('    for name in ("config.json", "owner.json"):', '    for name in ("config.json",)')]),
    ("D5", "over", "seconds are used as milliseconds — every run starts in 1970",
     [("                stamps.append(int(p.stat().st_mtime * 1000))",
       "                stamps.append(int(p.stat().st_mtime))")]),
    # D6 removed as an EQUIVALENT mutant, deliberately and with the reasoning
    # left here rather than the mutant quietly deleted. It replaced the
    # once-only `if "id" not in meta:` guard with `if True:` — a real defect
    # while createdAt was `now`, because every later write dragged the run
    # start forward and with it every backfilled phase. Against the fix it
    # changes nothing: `_run_started_ms` reads file timestamps that do not
    # move, so re-stamping writes the same value. That idempotence is the
    # point, and it is pinned by `test_the_run_start_is_stable_when_asked_twice`
    # instead of by a mutant that can never die.
    ("D7", "over", "later phases stop chaining off the previous completion",
     [('        if p_idx > 0 and len(phases) > 0 and phases[-1].get("completedAt"):\n'
       '            start = phases[-1]["completedAt"]\n', "")]),
    ("D8", "over", "the helper raises on a half-built directory instead of falling back",
     [("        except Exception:\n            pass\n    return min(stamps)",
       "        except Exception:\n            raise\n    return min(stamps)")]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    return sh([sys.executable, "-m", "pytest", *SUITES.split(), "-q"]).returncode == 0


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

    path = ROOT / RESEARCH
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm not in mutated:
                    raise AssertionError(f"anchor not found: {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests()
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
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

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
