"""Mutation harness for the published worker capacity.

The device advertised two workers and ran one, so a second run was sent straight
through instead of queueing, nobody claimed it, and the app blamed the machine.

The OVER-corrections matter more than the under-corrections here and there are
more of them on purpose. Under-correcting reproduces one afternoon's confusion.
Over-correcting breaks the supervised multi-worker queue, which is the one thing
the owner said must not move — a fleet that publishes 1 makes every second run
on a genuinely 2-worker device queue behind an idle worker, and every fix in this
codebase that broke the pipeline broke it in exactly that direction.

So half these mutants do not touch the fix at all. They attack the protections
AROUND it: the defer gate's key, its busy signals, the settle window, the sibling
re-check, the FIFO sort, and both halves of the spawn discriminator. If those
survive, the protection is not tested and the fix is not safe to ship.

Safety, learned from an earlier harness on this repo that adopted a mutant as its
own baseline: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/worker_capacity_0811_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = "tests/test_worker_capacity_0811.py"

MUTANTS = [
    # ── the fix itself, reverted ────────────────────────────────────────────
    ("F1", "under", "the heartbeat publishes the configured profile count again — the bug",
     [("                _wc_payload = _running_worker_capacity()",
       "                _wc_payload = load_worker_count()")]),
    ("F2", "under", "capacity ignores fleet membership and always reports the config",
     [("    if not _FLEET_MEMBER:\n        return 1\n    return load_worker_count()",
       "    return load_worker_count()")]),
    ("F3", "under", "the flag's VALUE is used, so fleet member #1 reads as standalone",
     [("    _FLEET_MEMBER = args.worker_id is not None",
       "    _FLEET_MEMBER = bool(args.worker_id and args.worker_id > 1)")]),
    ("F4", "under", "argparse defaults to 1 again, erasing the presence signal",
     [('parser.add_argument("--worker-id", type=int, default=None, dest="worker_id",',
       'parser.add_argument("--worker-id", type=int, default=1, dest="worker_id",')]),
    ("F5", "under", "the global is not declared, so the stamp never leaves main()",
     [("    global WORKER_ID, _FLEET_MEMBER", "    global WORKER_ID")]),
    ("F6", "under", "the module default is True, so anything that never parsed args claims N",
     [("_FLEET_MEMBER: bool = False", "_FLEET_MEMBER: bool = True")]),
    ("F7", "under", "the payload is published as a literal instead of the computed value",
     [('                                "workerCount": _wc_payload,',
       '                                "workerCount": 1,')]),

    # ── ⛔ over-corrections: the supervised fleet must not lose capacity ─────
    ("O1", "over", "a fleet member publishes 1 — every supervised 2-worker device serialises",
     [("    if not _FLEET_MEMBER:\n        return 1\n    return load_worker_count()",
       "    return 1")]),
    ("O2", "over", "capacity is capped at 1 for everyone",
     [("    return load_worker_count()\n\n\ndef _owner_worker_of(assigned) -> int:",
       "    return min(1, load_worker_count())\n\n\ndef _owner_worker_of(assigned) -> int:")]),
    ("O3", "over", "the defer gate keys on RUNNING capacity — a 2-profile serve stops deferring",
     [("            _multi_worker_mode = load_worker_count() > 1",
       "            _multi_worker_mode = _running_worker_capacity() > 1")]),
    ("O4", "over", "the daemon-loop stops passing --worker-id, so its whole fleet reads standalone",
     [('                     "--port", str(w_port), "--worker-id", str(k)],',
       '                     "--port", str(w_port)],')]),
    ("O5", "over", "the supervised single-worker child is spawned WITH --worker-id",
     [('                    [python_exe, script_path, "--serve", "--port", str(port)],',
       '                    [python_exe, script_path, "--serve", "--port", str(port), "--worker-id", "1"],')]),
    ("O6", "over", "the fleet branch never triggers, so N profiles spawn one worker",
     [("    n_workers = load_worker_count()\n    if n_workers > 1:",
       "    n_workers = load_worker_count()\n    if False:")]),

    # ── ⛔ the queue protections around the fix ─────────────────────────────
    ("Q1", "over", "the settle window is gone — the 2-worker second fire flickers again",
     [("                        time.sleep(0.6)\n", "")]),
    ("Q2", "over", "the sibling re-check is gone, so a claimed run is overwritten as queued",
     [('                        if _q_data.get("assignedWorker"):',
       '                        if False:')]),
    ("Q3", "over", "the gate stops deferring on a non-empty local queue",
     [("                        or job_queue.qsize() > 0\n"
       "                        or _pending_enq_read() > 0):",
       "                        or _pending_enq_read() > 0):")]),
    ("Q4", "over", "the gate stops deferring on a claim in flight — the dual-claim race returns",
     [("                        or job_queue.qsize() > 0\n"
       "                        or _pending_enq_read() > 0):",
       "                        or job_queue.qsize() > 0):")]),
    ("Q5", "over", "the gate stops opening for a resting worker",
     [('            if _resting or _multi_worker_mode or _REST_DEFER_SEEN["v"]:',
       '            if _multi_worker_mode or _REST_DEFER_SEEN["v"]:')]),
    ("Q6", "over", "idle-rescan drops the FIFO sort — the oldest orphan sits under a newer one",
     [("        candidates.sort(key=_fifo_key)\n", "")]),
    ("Q7", "over", "the owner-pill helper keys on running capacity instead of the config",
     [("        if int(load_worker_count() or 1) > 1:\n            return []",
       "        if int(_running_worker_capacity() or 1) > 1:\n            return []")]),

    # ── the second publisher ────────────────────────────────────────────────
    ("W1", "over", "a second writer publishes workerCount and the two fight over the field",
     [('                                "workerCount": _wc_payload,',
       '                                "workerCount": _wc_payload,\n'
       '                                "workerCount": load_worker_count(),')]),
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
