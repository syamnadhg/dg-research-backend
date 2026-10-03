"""Mutation harness — Phase 3 tells the NotebookLM pop-up what it is doing (wave 17).

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  D*  the DOM upload: the notebook made is announced once it is reached; each
      source as it lands, once, by its name.
  S*  a source is named by OUR file list — an agent's report by its agent, the
      person's own file by its own name — and a failed one never says "added".
  R*  a source added again says so; it ends done only on a healthy verdict, and
      failed when the last census still cannot see it.
  O*  a resumed run going back to its notebook says so, then shows the sources
      the notebook actually holds.
  U*  the upload phase: named, shared with its link; the computer-use fallback
      confirms each source and announces the notebook once.
  P*  the podcast: the setting only as the page READ IT BACK, made, ticking,
      ready, saved where the app plays it from.
  H*  the row and the event: only the fields given, bounded, the stage explicit,
      the label on the line.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/p3_activity_steps_w17_mutants.py
  .venv/bin/python .mutants/p3_activity_steps_w17_mutants.py D1 P4
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
    # ── D: the DOM upload ───────────────────────────────────────────────────
    ('D1', RESEARCH, '⛔⛔ the notebook made is never announced — the walkthrough has no notebook card',
     [('            _p3_step("notebook", "Notebook created")\n',
       '            pass\n')]),
    ('D2', RESEARCH, '⛔⛔ the census sees each source land and says nothing',
     [('                _p3_send([row], progress=row["label"])\n',
       '                pass\n')]),
    ('D3', RESEARCH, '⛔ a source is announced again on every census that sees it',
     [('                shown.add(name)\n',
       '                pass\n')]),

    # ── S: the source's name ────────────────────────────────────────────────
    ('S1', RESEARCH, '⛔ a report is named by its file ("chatgpt.md added"), not its agent',
     [('    thing = f"{who} report" if who else name\n',
       '    thing = name\n')]),
    ('S2', RESEARCH, "⛔ the person's own file is called somebody's report",
     [('    who = _P3_REPORT_NAMES.get(Path(name).stem.lower())\n',
       '    who = _P3_REPORT_NAMES.get(Path(name).stem.lower(), "Agent")\n')]),
    ('S3', RESEARCH, '⛔⛔ a source that never went in reads "added"',
     [('        "failed": f"{thing} didn\'t go in",\n',
       '        "failed": f"{thing} added",\n')]),

    # ── R: the repair rounds ────────────────────────────────────────────────
    ('R1', RESEARCH, '⛔ a missing source is re-added with no row saying so',
     [('                           timeline=[_p3_source_step(n, "active") for n in sorted(missing)])',
       '                           timeline=[])')]),
    ('R2', RESEARCH, '⛔⛔ a re-added source is never closed — its row spins for ever',
     [('            repairing.update(missing)\n',
       '            pass\n')]),
    ('R3', RESEARCH, '⛔ a red source re-uploaded by computer use is never closed',
     [('        repairing.update(failed)\n',
       '        pass\n')]),
    ('R4', RESEARCH, '⛔⛔ the healthy verdict closes nothing',
     [('            _p3_send([_p3_source_step(n, "done") for n in sorted(repairing)])\n',
       '            pass\n')]),
    ('R5', RESEARCH, '⛔⛔ a source the last census cannot see ends "added"',
     [('        _p3_send([_p3_source_step(n, "failed" if n in still else "done")',
       '        _p3_send([_p3_source_step(n, "done")')]),
    ('R6', RESEARCH, '⛔ a red source being re-uploaded has no row saying so',
     [('                       timeline=[_p3_source_step(n, "active") for n in failed])',
       '                       timeline=[])')]),

    # ── O: going back to the notebook ───────────────────────────────────────
    ('O1', RESEARCH, '⛔ going back to the notebook sends no row — the card appears only if it works',
     [('               progress="Going back to the notebook this research already made…",\n'
       '               timeline=',
       '               progress="Going back to the notebook this research already made…",\n'
       '               _unused=')]),
    ('O2', RESEARCH, '⛔⛔ carrying on in the notebook never closes its card',
     [('    _p3_send([_p3_timeline_step("notebook", "Went back to this research\'s notebook")]\n',
       '    _p3_send([]\n')]),
    ('O3', RESEARCH, '⛔⛔ every source is shown as in the notebook, whether it is there or not',
     [('             + [_p3_source_step(n) for n in names if n in present],',
       '             + [_p3_source_step(n) for n in names],')]),

    # ── U: the upload phase ─────────────────────────────────────────────────
    ('U1', RESEARCH, '⛔ the notebook is named and the pop-up never says so',
     [('            _p3_step("renamed", f"Named “{title}”", stage="notebook")\n',
       '            pass\n')]),
    # U2 ("the share is never shown") moved to p3_activity_w17_review_mutants
    # as A4: the review's access gate nested its line one level deeper.
    ('U3', RESEARCH, 'the share row carries no link to the notebook',
     [('                             stage="notebook", url=notebook_url)\n',
       '                             stage="notebook")\n')]),
    ('U4', RESEARCH, '⛔⛔ a source computer use added never lands on the pop-up',
     [('                    _p3_send(([] if _nb_sent else [_p3_timeline_step("notebook", "Notebook created")])\n'
       '                             + [_row], progress=_row["label"])\n',
       '                    pass\n')]),
    ('U5', RESEARCH, '⛔ the fallback announces the notebook again with every source',
     [('                    _nb_sent = True\n',
       '                    pass\n')]),
    ('U6', RESEARCH, '⛔ the fallback announces a notebook the DOM path already announced',
     [('            _nb_sent = bool(_dom_uploaded)\n',
       '            _nb_sent = False\n')]),

    # ── P: the podcast ──────────────────────────────────────────────────────
    ('P1', RESEARCH, '⛔⛔ the setting NotebookLM read back is never shown',
     [('                if _dom_gen.get("pressed") and _dom_gen.get("format"):\n',
       '                if False:\n')]),
    ('P2', RESEARCH, '⛔⛔ a setting the page never read back is shown as if it had',
     [('                if _dom_gen.get("pressed") and _dom_gen.get("format"):\n',
       '                if _dom_gen.get("format"):\n')]),
    ('P3', RESEARCH, 'the setting reads "Deep dive + Long", not the chip "Deep dive · Long"',
     [('                             detail=" · ".join(x for x in (_dom_gen.get("format"),\n',
       '                             detail=" + ".join(x for x in (_dom_gen.get("format"),\n')]),
    ('P4', RESEARCH, '⛔ the podcast being made is never shown until the first tick',
     [('        _p3_step("podcast", "Making the podcast", "active", stage="podcast")\n',
       '        pass\n')]),
    ('P5', RESEARCH, '⛔⛔ a podcast already in the notebook is shown as being made',
     [('    elif not _reuse_existing:\n',
       '    elif True:\n')]),
    ('P6', RESEARCH, '⛔ the poll tick carries no row — the walkthrough never moves while it generates',
     [('                       expectedMinutes=_typ_high,\n'
       '                       timeline=[_p3_timeline_step(\n',
       '                       expectedMinutes=_typ_high,\n'
       '                       _unused=[_p3_timeline_step(\n')]),
    ('P7', RESEARCH, 'the tick loses the typical range',
     [('detail=f"{elapsed_min} min so far · usually {_typ_low}–{_typ_high} min")])',
       'detail=f"{elapsed_min} min so far")])')]),
    ('P8', RESEARCH, '⛔⛔ the podcast finishing is never shown',
     [('        _p3_step("podcast", "Podcast ready", stage="podcast")\n',
       '        pass\n')]),
    ('P9', RESEARCH, '⛔⛔ the podcast saved is never shown',
     [('            _p3_step("podcast_saved", "Podcast saved to your research", stage="podcast")\n',
       '            pass\n')]),

    # ── H: the row and its event ────────────────────────────────────────────
    ('H1', RESEARCH, '⛔ every row carries an empty detail — an update wipes the setting the row showed',
     [('    if detail:\n        step["detail"] = str(detail)[:160]\n',
       '    step["detail"] = str(detail)[:160]\n')]),
    ('H2', RESEARCH, 'labels are not bounded',
     [('    step = {"id": str(step_id)[:100], "label": str(label)[:160], "state": state,',
       '    step = {"id": str(step_id)[:100], "label": str(label), "state": state,')]),
    ('H3', RESEARCH, '⛔ the stage is left off — the stepper guesses the milestone from the words',
     [('        data = {"stage": stage, "timeline": list(rows)}\n',
       '        data = {"timeline": list(rows)}\n')]),
    ('H4', RESEARCH, '⛔ an app that does not know the list yet sees nothing on the line',
     [('        if progress:\n            data["progress"] = str(progress)[:160]\n',
       '        if False:\n            data["progress"] = str(progress)[:160]\n')]),
    ('H5', RESEARCH, '⛔ every row lands on the Uploading milestone',
     [('             stage=stage, progress=label)\n',
       '             stage="uploading", progress=label)\n')]),
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
