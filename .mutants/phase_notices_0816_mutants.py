"""Mutation harness for the backend half of the per-phase notification wave.

Two one-line changes, and both are the kind that a green suite has no opinion
about: an event kwarg that nothing in this repo reads. The consumer is in the
other repo, so the ONLY thing standing between "the field is emitted" and "the
field is not" is the test suite next to these mutants.

⭐ B1 AND B5 ARE THE ORIGINAL BUGS. B1 is a phase-1 Skip that emitted a plain
phase_complete and had the web app announce a brief that is an empty string. B5
is a phase 3 that gave up on the Audio Overview after three retries, delivered
the notebook it had built in the report and the email, and emitted a terminal
event that mentioned neither.

⭐ THE OVER-CORRECTIONS ARE WHERE THE REAL DAMAGE IS:
  B2  marks a REAL phase-1 completion as skipped — every genuine brief in the
      installed base stops announcing itself. Silence in place of a false
      notice is not a fix, it is the same bug pointed the other way.
  B3  deletes the emit instead of marking it. Passes any "no false
      notification" test perfectly and hangs the phase-1 tile forever — the
      exact trade phase 5's twin carries a comment warning against.
  B4  emits a truthy 1 rather than a literal True. The frontend tests `=== true`
      on a value read back off Firestore, so this reads as "not skipped" and
      the false notification is straight back with the fix apparently in place.
  B6  hands `links` to a phase_skipped:3 that is NOT the give-up. Link presence
      is the whole gate on the frontend, so a config skip or a Flow-C run —
      where the notebook URL was pasted BY THE USER — announces a notebook the
      pipeline never made.

    .venv/bin/python .mutants/phase_notices_0816_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The suite that pins these two emits, plus the neighbours that own the code
# around them — a mutant that moved the phase-1 skip or the phase-3 give-up
# should fail their tests too, and if it does not, that is worth seeing.
ROOT_SUITES = ("tests/test_phase_notices_0816.py "
               "tests/test_brief_done_label_0811.py "
               "tests/test_p3_audio_and_retry_0806.py "
               "tests/test_skip_reporting.py "
               "tests/test_card_lifetime.py "
               "tests/test_worktab_preflight_899.py")

MUTATED_FILES = ("research.py",)

SURVIVOR_CONFIRMATIONS = 2

ENV = {**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "")}

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ 1 — the brief that was skipped ═════════════════════════════
    ("B1", "research.py", "under",
     "⭐ THE ORIGINAL BUG — the phase-1 skip emits a plain phase_complete again, "
     "so the web app pushes 'Brief ready' for a brief that is an empty string",
     [('                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),\n'
       '                    skipped=True,\n',
       '                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),\n')]),

    ("B2", "research.py", "over",
     "⛔ a REAL phase-1 completion is marked skipped — every genuine brief stops "
     "announcing itself, which is the same defect inverted",
     [('                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),\n'
       '                    links=_p1_links,\n',
       '                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),\n'
       '                    links=_p1_links, skipped=True,\n')]),

    ("B3", "research.py", "over",
     "⛔ the emit is DELETED rather than marked — passes any 'no false notice' "
     "test and hangs the phase-1 tile, the exact trade phase 5's twin warns against",
     [('                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),\n'
       '                    skipped=True,\n'
       '                    summary="Phase 1 skipped after error — no brief generated")\n',
       '')]),

    ("B4", "research.py", "over",
     "⛔ a truthy 1 instead of a literal True — the frontend tests `=== true` on a "
     "value read back off Firestore, so this reads as 'not skipped' and the false "
     "notification returns with the fix apparently in place",
     [("                    skipped=True,\n", "                    skipped=1,\n")]),

    ("B7", "research.py", "over",
     "⛔ the durable tile status disagrees with the event — the tile says complete "
     "while the notification stays silent, which is the inconsistency inverted",
     [('                _write_phase_terminal_status(1, "skipped")',
       '                _write_phase_terminal_status(1, "complete")')]),

    # ═══════════ 2 — the notebook on the give-up path ═══════════════════════
    ("B5", "research.py", "under",
     "⭐ THE ORIGINAL BUG — the audio give-up drops the notebook it built, so the "
     "only notice the user gets says the phase was skipped",
     [('                    emit_event("phase_skipped", phase=3, reason="audio_unavailable_after_auto_retries",\n'
       '                               links=_p3_links)',
       '                    emit_event("phase_skipped", phase=3, reason="audio_unavailable_after_auto_retries")')]),

    ("B6", "research.py", "over",
     "⛔ the CONFIG skip carries links too — link presence is the entire gate on "
     "the frontend, so a run with phase 3 switched off, or a Flow-C run whose "
     "notebook URL the USER pasted, announces a notebook nobody made",
     [('            emit_event("phase_skipped", phase=3, reason=_reason)',
       '            emit_event("phase_skipped", phase=3, reason=_reason, '
       'links=[{"label": "NotebookLM Notebook", "url": notebook_url}])')]),

    ("B8", "research.py", "over",
     "⛔ the give-up sends an empty list — 'carries a links kwarg' and 'carries the "
     "notebook' are different guarantees, and only the second one notifies",
     [("                               links=_p3_links)", "                               links=[])")]),

    # ⛔ Anchored on the two lines ABOVE it. `skipped_phases.add(4)` alone occurs
    # NINE times in research.py — the first version of this mutant matched one of
    # the other eight and the harness reported a survivor that had measured
    # nothing at all.
    ("B9", "research.py", "over",
     "⛔ phase 4 is no longer stood down — the notebook notice must not cost the "
     "behaviour around it: no audio means there is nothing to upload",
     [("                               links=_p3_links)\n"
       "                    _p3_audio_user_skipped = True\n"
       "                    _controls.skipped_phases.add(4)\n",
       "                               links=_p3_links)\n"
       "                    _p3_audio_user_skipped = True\n")]),

    ("B10", "research.py", "over",
     "⛔ the notebook row is relabelled — the frontend tells the notebook from the "
     "Audio Overview by LABEL, because NotebookLM serves the SAME url for both "
     "share dialogs. A rename silently ends the notice.",
     [('{"label": "NotebookLM Notebook", "url": notebook_url, "verified": True}',
       '{"label": "Research Source", "url": notebook_url, "verified": True}')]),
]


def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=kw.pop("cwd", ROOT), env=kw.pop("env", ENV),
                          capture_output=True, text=True, **kw)


def purge_pycache():
    for p in ROOT.rglob("__pycache__"):
        if ".venv" in p.parts:
            continue
        for f in p.glob("*.pyc"):
            try:
                f.unlink()
            except OSError:
                pass


def run_tests() -> bool:
    purge_pycache()
    return sh([sys.executable, "-B", "-m", "pytest", *ROOT_SUITES.split(),
               "-q", "-p", "no:cacheprovider"]).returncode == 0


def tracked_dirty():
    out = sh(["git", "status", "--porcelain", "--", *MUTATED_FILES]).stdout.strip()
    return [ln for ln in out.split("\n") if ln]


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

    survivors = []
    for mid, fname, direction, why, edits in MUTANTS:
        path = ROOT / fname
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                # ⛔⛔ UNIQUENESS, NOT MERE PRESENCE. `str.replace` takes the
                # FIRST match, and an anchor that also occurs elsewhere mutates
                # code the mutant was never about — reporting a suite gap that
                # does not exist while hiding the one that does. A substring
                # match once hit a function 2,300 lines away.
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor — this mutates nothing")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
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
            survivors.append((mid, direction, f"HARNESS FAULT — measured nothing: {why}"))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[2] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    if survivors:
        print("SURVIVORS:\n" + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
