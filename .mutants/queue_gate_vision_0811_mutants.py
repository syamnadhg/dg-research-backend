"""Mutation harness for the truncated vision read.

⛔⛔ THE QUEUE-GATE HALF OF THIS HARNESS IS GONE (wave 10.9, N8). Thirteen
mutants (G1-G4, X1-X9) aimed at `_wait_for_prior_fe_completion` — its deadline,
its branch order and its six separately root-caused release paths. The function
has been DELETED: it held the next run's start behind the PREVIOUS run's cloud
tail, and phases 4 and 5 run on Cloud Run, so the contention it existed for was
with a machine that is idle. Its guards were all guards against itself.

⭐ AN ANCHOR THAT CANNOT APPLY IS A GUARD THAT HAS SILENTLY STOPPED GUARDING,
which is why they are removed rather than left to go stale. What replaces them
is `.mutants/wave109_handoff_mutants.py`, aimed at the rule that took the gate's
place: after `beDone` the run is the cloud's, and the machine re-kicks rather
than stamps.

On the vision side the danger is the salvage letting a HALF-read URL into the
report — a truncated link is worse than a missing one, and the prompt already
tells the model the same thing about truncated text on screen.

Safety, learned from an earlier harness on this repo that adopted a mutant as its
own baseline: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/queue_gate_vision_0811_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = "tests/test_queue_gate_and_vision_urls_0811.py"

MUTANTS = [
    # ── the vision read ─────────────────────────────────────────────────────
    # Re-anchored 2026-08-12: the call site's literal became a named constant when
    # the read timeout was bound to it, so this mutant stopped applying at all —
    # and an anchor that cannot apply is a guard that has silently stopped guarding.
    ("V1", "under", "the token ceiling goes back under narrate's — the truncation returns",
     [('_VISION_URL_MAX_TOKENS = int(os.environ.get("DG_VISION_URL_MAX_TOKENS", "2400"))',
       '_VISION_URL_MAX_TOKENS = int(os.environ.get("DG_VISION_URL_MAX_TOKENS", "800"))')]),
    ("V2", "under", "a truncated response is called a parse error again",
     [('                log(f"[{agent_key}] vision-urls response was not complete JSON "\n'
       '                    f"(finishReason={_finish or \'unset\'}, {len(text)} chars): {_je} — "\n'
       '                    f"salvaged {len(_salvaged)} whole URLs from it", "WARN")',
       '                log(f"[{agent_key}] vision-urls call/parse error: {_je}", "WARN")')]),
    ("V3", "under", "finishReason is never read, so a ceiling looks like a safety stop",
     [('            _finish = _cand.get("finishReason") or ""\n', "            _finish = \"\"\n")]),
    ("V4", "under", "nothing is salvaged — one clipped URL discards the whole panel",
     [("                _salvaged = _salvage_urls_from_truncated_json(text)",
       "                _salvaged = []")]),
    ("V5", "under", "the salvage confidence sits under the gate that admits it",
     [("_VISION_URL_SALVAGE_CONFIDENCE = 0.5", "_VISION_URL_SALVAGE_CONFIDENCE = 0.3")]),

    # ── ⛔ over-corrections: never publish half a URL ────────────────────────
    ("S1", "over", "the closing quote is optional — the clipped last URL comes through",
     [("_VISION_URL_SALVAGE_RE = re.compile(r'\"(https?://[^\"\\\\\\s]{4,500})\"')",
       "_VISION_URL_SALVAGE_RE = re.compile(r'\"?(https?://[^\"\\\\\\s]{4,500})')")]),
    ("S2", "over", "the length cap is dropped, so the salvage outruns the parsed path",
     [("_VISION_URL_SALVAGE_RE = re.compile(r'\"(https?://[^\"\\\\\\s]{4,500})\"')",
       "_VISION_URL_SALVAGE_RE = re.compile(r'\"(https?://[^\"\\\\\\s]+)\"')")]),
    ("S3", "over", "any quoted string counts as a URL",
     [("_VISION_URL_SALVAGE_RE = re.compile(r'\"(https?://[^\"\\\\\\s]{4,500})\"')",
       "_VISION_URL_SALVAGE_RE = re.compile(r'\"([^\"]{4,500})\"')")]),
    ("S4", "over", "an empty salvage is still handed a confidence",
     [("                return _salvaged, (_VISION_URL_SALVAGE_CONFIDENCE if _salvaged else 0.0)",
       "                return _salvaged, _VISION_URL_SALVAGE_CONFIDENCE")]),
    ("S5", "over", "the salvage claims the clean-read confidence it never observed",
     [("_VISION_URL_SALVAGE_CONFIDENCE = 0.5", "_VISION_URL_SALVAGE_CONFIDENCE = 0.9")]),
    ("S6", "over", "every exception takes the salvage branch, so a network error reads as truncation",
     [("            except ValueError as _je:", "            except Exception as _je:")]),
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
