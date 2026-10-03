"""Mutation harness — the wave 17 review repair: Phase 3 says "Shared" and "Named"
only when they happened.

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  A*  "Shared: anyone with the link can view" is sent only when the share
      dialog itself set "Anyone with the link". The extractor hands that out on
      its result (`access_set`); a notebook address alone never says so — the
      extractor falls back to the tab's own address when sharing failed, and a
      link copied by computer use was never read back.
  N*  "Named “…”" is sent only when the rename worked: the page's own rename, or
      computer use answering "done" / "vision_success". Computer use is asked
      only when the page's rename failed.

  (A4 is the lane's U2, moved here: the review's gate nested its anchor one
  level deeper, so it lives where it is run.)

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/p3_activity_w17_review_mutants.py
  .venv/bin/python .mutants/p3_activity_w17_review_mutants.py A1 N2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

#: The tests the mutants are measured by (a name, never a path: the anchor sweep
#: reads any "*.py" string in a mutant's row as its target file).
SUITES = {RESEARCH: (ROOT, "tests/test_p3_activity_steps_w17" + ".py")}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
       "PYTHONPATH": str(ROOT)}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ── A: "Shared" only when access was set ────────────────────────────────
    ('A1', RESEARCH, '⛔⛔ the extractor keeps access_set to itself — a real share is never shown',
     [('                      verified=verified, error=_err, access_set=access_set)',
       '                      verified=verified, error=_err)')]),
    ('A2', RESEARCH, '⛔⛔ any notebook address counts as shared — the tab fallback says "public"',
     [('                      verified=verified, error=_err, access_set=access_set)',
       '                      verified=verified, error=_err, access_set=is_notebooklm_url(url))')]),
    ('A3', RESEARCH, '⛔ a result built without the flag claims access by default',
     [('                 access_set=False):\n',
       '                 access_set=True):\n')]),
    ('A4', RESEARCH, '⛔ the share is never shown (the lane\'s U2)',
     [('                        _p3_step("shared", "Shared: anyone with the link can view",\n'
       '                                 stage="notebook", url=notebook_url)\n',
       '                        pass\n')]),
    ('A5', RESEARCH, '⛔⛔ the gate is gone — "Shared" for any notebook-shaped link',
     [('                    if getattr(nlm_share_res, "access_set", False):\n',
       '                    if True:\n')]),

    # ── N: "Named" only when the rename worked ──────────────────────────────
    ('N1', RESEARCH, '⛔⛔ the notebook is "Named" however the rename ended',
     [('            if _renamed:\n                _p3_step("renamed"',
       '            if True:\n                _p3_step("renamed"')]),
    ('N2', RESEARCH, '⛔ the page\'s own rename is ignored — computer use is asked every time',
     [('            _renamed = bool(await _nlm_dom_rename(page, title))\n',
       '            _renamed = bool(await _nlm_dom_rename(page, title)) and False\n')]),
    ('N3', RESEARCH, '⛔⛔ a failed page rename counts as renamed',
     [('            _renamed = bool(await _nlm_dom_rename(page, title))\n',
       '            _renamed = bool(await _nlm_dom_rename(page, title)) or True\n')]),
    ('N4', RESEARCH, 'a rename Vision did is not counted',
     [('                            and _rename_cua.get("status") in ("done", "vision_success"))',
       '                            and _rename_cua.get("status") in ("done",))')]),
    ('N5', RESEARCH, '⛔ computer use running out of turns counts as a rename',
     [('                            and _rename_cua.get("status") in ("done", "vision_success"))',
       '                            and _rename_cua.get("status") != "failed")')]),
    ('N6', RESEARCH, '⛔ any answer from computer use counts as a rename',
     [('                _renamed = (isinstance(_rename_cua, dict)\n'
       '                            and _rename_cua.get("status") in ("done", "vision_success"))',
       '                _renamed = True')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 600


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too, and a
    # skipped test is not a measurement.
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
