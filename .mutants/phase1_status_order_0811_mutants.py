"""Mutation harness for the phase that succeeded and was recorded as errored.

The 2026-08-11 run shipped a 64 KB brief with `phases[1].status = "errored"` and
`durationSec: 0` in meta.json. `save_meta` rebuilds the phases array from the
recorded terminal statuses, and it ran BEFORE the "complete" was recorded — so a
phase that had surfaced a stall card earlier kept `fail_phase`'s "errored" on
disk while Firestore said complete. Both P1 and P2 restore that ordering, one
per branch, because the first version of the fix corrected only one of the two.

⛔ FIFTEEN MUTANTS LEFT THIS FILE ON 2026-08-28 (stretch 6.6B), and it was
called `share_links_0811_mutants.py` until then. H1-H4, M1-M6, A1-A2 and E1-E3
all anchored on the P2 platform share gate — the rotted host literals, the
shared `_is_public_share_url` authority, the two extractors that delegated to
it, and the fallback's log lines. That whole step was removed from Phase 2, so
every one of those anchors is gone. ⛔ A vanished anchor is a HARNESS FAULT, not
a survivor; they are deleted rather than left to report `anchor occurs 0x`.

P1 and P2 were never about share links. They are here because the same e2e found
both faults on the same day.

Safety, learned from an earlier harness on this repo that adopted a mutant as its
own baseline: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/phase1_status_order_0811_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

# ⛔ 2026-08-28: two of the three suites this harness ran were DELETED with the
# P2 share step, and the third was renamed. The one file left is the only one
# that ever pinned P1/P2 — the original three were here for the fifteen H/M/A/E
# mutants that went with them. A mutant can only die against a suite that is
# run, and a suite that pins nothing this harness mutates is pure cost.
SUITES = "tests/test_phase1_status_order_0811.py"

MUTANTS = [
    # ── the phase that succeeded but was recorded errored ───────────────────
    ("P1", "under", "save_meta runs before the status again (extract branch)",
     [('                _write_phase_terminal_status(1, "complete")\n'
       '                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())\n'
       '                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),',
       '                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())\n'
       '                _write_phase_terminal_status(1, "complete")\n'
       '                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),')]),
    ("P2", "under", "save_meta runs before the status again (brief-from-file branch)",
     [('                _write_phase_terminal_status(1, "complete")\n'
       '                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())\n'
       '                emit_event("phase_complete", phase=1,\n'
       '                    durationSec=int(time.time() - _p1_start), links=_p1_links,',
       '                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())\n'
       '                _write_phase_terminal_status(1, "complete")\n'
       '                emit_event("phase_complete", phase=1,\n'
       '                    durationSec=int(time.time() - _p1_start), links=_p1_links,')]),
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
