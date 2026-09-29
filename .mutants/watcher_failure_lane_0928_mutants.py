"""Mutation harness — Hermes' own notices about our watcher jobs go nowhere (2026-09-28).

⛔⛔ WHAT THIS CODE DECIDES.
  F* — sr.py's watcher rows: every row this client writes carries the failure lane
       `failure_deliver: "local"`, so Hermes' "was interrupted" / script-failed /
       timeout notices never reach the chat while the messages still follow
       `deliver`; rows armed before get it once, a lane somebody set is left alone,
       and the assistant-only fallback asks the cronjob tool for it.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔⛔ AN IN-FLIGHT MARKER, because Windows kills without running `finally:` or a
SIGTERM handler: a run that dies leaves `<this file>.inflight` naming the file that
still holds a mutant, and the next run refuses to start until it is restored. Run
this in a throwaway worktree, never in the tree the agent is installed from.

  python .mutants/watcher_failure_lane_0928_mutants.py
  python .mutants/watcher_failure_lane_0928_mutants.py F1 F4
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

SR = "agent/facade/skill/scripts/sr.py"

SUITES = {
    SR: (AGENT, "tests/test_watcher_failure_lane_0928.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    ("F1", SR, "⛔⛔ a NEW watcher row has no failure lane — Hermes posts 'was interrupted' "
     "to the chat on the next restart that lands mid-tick",
     [('        "failure_deliver": _WATCHER_FAILURE_LANE,\n', '')]),
    ("F2", SR, "⛔⛔ rows armed before are never carried over — every existing chat keeps "
     "getting the notice",
     [('        laned = _migrate_failure_lane(data["jobs"])\n', '        laned = []\n')]),
    ("F3", SR, "⛔ the carry-over is computed but a runnable row returns before the write — "
     "nothing is saved",
     [('                if not moved and not laned:\n', '                if not moved:\n')]),
    ("F4", SR, "⛔ a lane somebody set (by hand, or with Hermes' cronjob tool) is overwritten",
     [('        if (not isinstance(job, dict) or not _is_watcher_job_name(job.get("name"))\n'
       '                or "failure_deliver" in job):\n',
       '        if not isinstance(job, dict) or not _is_watcher_job_name(job.get("name")):\n')]),
    ("F5", SR, "⛔ the daily update notice's row is not carried over — it still gets the notice",
     [('    return _is_stream_job_name(name) or name == "sr-update-notice"\n',
       '    return _is_stream_job_name(name)\n')]),
    ("F6", SR, "⛔ the lane is the chat after all — the notice still goes to the person",
     [('_WATCHER_FAILURE_LANE = "local"\n', '_WATCHER_FAILURE_LANE = "origin"\n')]),
    ("F7", SR, "⛔ the fallback's watcher row, created by the cronjob tool, has no lane",
     [("        f'script=\"{script_name}\" name=\"{job_name}\" '\n"
       "        f'failure_deliver=\"{_WATCHER_FAILURE_LANE}\"',\n",
       "        f'script=\"{script_name}\" name=\"{job_name}\"',\n")]),
    ("F8", SR, "⛔ the fallback's daily-notice row, created by the cronjob tool, has no lane",
     [("        'script=\"sr_update_notice.py\" name=\"sr-update-notice\" '\n"
       "        f'failure_deliver=\"{_WATCHER_FAILURE_LANE}\"',\n",
       "        'script=\"sr_update_notice.py\" name=\"sr-update-notice\"',\n")]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    for cwd, suites in sorted({SUITES[f] for f in files}, key=str):
        if not green(cwd, suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
        path = ROOT / fname
        raw = ORIGINALS[fname]
        crlf = b"\r\n" in raw
        try:
            mutated = raw.decode("utf-8").replace("\r\n", "\n")
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as se:
                    raise AssertionError(f"mutant does not compile: {se}")
            _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            if green(*SUITES[fname]):
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:4} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_bytes(raw)
            if _digest(path.read_bytes()) == DIGESTS[fname]:
                try:
                    _INFLIGHT.unlink()
                except FileNotFoundError:
                    pass

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
