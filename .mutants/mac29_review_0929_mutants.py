"""Mutation harness — the Windows review of 58d705e (2026-09-29).

⛔⛔ WHAT THIS CODE DECIDES.
  R* — research.py: who shares this computer is read in ONE bounded attempt, once
       per boot restore (not once more per entry), and a job stood down as another
       account's writes nothing to that account's record in the worker's finally.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔⛔ AN IN-FLIGHT MARKER, because Windows kills without running `finally:` or a
SIGTERM handler. Run this in a throwaway worktree (or on Linux: the suite re-parses
research.py per lifted closure, about two minutes a pass on Windows), never in the
checkout the backend runs from.

  python .mutants/mac29_review_0929_mutants.py
  python .mutants/mac29_review_0929_mutants.py R1 R4
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

SUITES = {
    RESEARCH: (ROOT, "tests/test_stale_or_foreign_restore_0928.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    ("R1", RESEARCH, "⛔ who shares this computer is read with the client's five-minute "
     "retry again — at boot on the event loop",
     [("                .get(retry=None, timeout=_RESTART_RETRY_READ_TIMEOUT_S))\n",
       "                .get())\n")]),
    ("R2", RESEARCH, "⛔ the boot restore does not pass the members it read — one more "
     "device read per entry of another account",
     # ⚠ RE-ANCHORED 2026-09-29 (wave 13 repair): the restore keeps the record
     # the pickup read, for the "who holds it now" question after it.
     [("            members=_MEMBERS_UNREAD if members is None else members)\n        if withdrawn:\n",
       "            members=_MEMBERS_UNREAD)\n        if withdrawn:\n")]),
    ("R3", RESEARCH, "⛔ the members a caller passes are ignored — every pickup reads "
     "the device document again",
     [("    if members is _MEMBERS_UNREAD:\n        members = _device_members()\n",
       "    members = _device_members()\n")]),
    ("R4", RESEARCH, "⛔⛔ a job stood down as another account's still clears its queue "
     "fields — a doomed write, a force-refresh, a step toward the STRUCTURAL latch",
     [("                if _firebase_db and _cuid and _crid and not _account_gone:\n",
       "                if _firebase_db and _cuid and _crid:\n")]),
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
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
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
