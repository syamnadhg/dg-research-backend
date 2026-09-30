"""Mutation harness — Move to queue in the chat (wave 13, owner's ask 2026-09-30).

⛔⛔ WHAT THIS CODE DECIDES.
  B* — bridge.py: the /updates row carries a move (movedToQueueAt, never a bool) and
       the owner's note cut to one clean line; the news peek pushes "run-moved" and
       "run-running-again" once each, and only for a run that is queued; the
       login-pause card that continues by itself says so, and Retry still works.
  P* — sr_attention_poll.py: ONE "moved" message per stay in the queue (not per
       stamp, not per place in line), with the note; ONE "running again", only
       with the stamp gone; a first tick tells only a recent move.
  S* — sr.py: status, updates and list say a run was moved back, with the note.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔⛔ AN IN-FLIGHT MARKER, because Windows kills without running `finally:` or a
SIGTERM handler. Run this in a throwaway worktree, never in the tree the agent is
installed from.

  python .mutants/move_to_queue_0930_mutants.py
  python .mutants/move_to_queue_0930_mutants.py B1 P2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

BRIDGE = "agent/facade/bridge.py"
POLL = "agent/facade/skill/scripts/sr_attention_poll.py"
SR = "agent/facade/skill/scripts/sr.py"

SUITES = {f: (AGENT, "tests/test_move_to_queue_0930.py") for f in (BRIDGE, POLL, SR)}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    ('B1', BRIDGE, '⛔⛔ the /updates row drops the move — the watcher never sees one',
     [('                    "movedToQueueAt": _moved_stamp(r.get("movedToQueueAt")),\n',
       '                    "movedToQueueAt": None,\n')]),
    ('B2', BRIDGE, "⛔⛔ the owner's note goes out raw — lines, length, the agent-only marker",
     [('                    "moveNote": _one_line_note(r.get("moveNote")),\n',
       '                    "moveNote": r.get("moveNote"),\n')]),
    ('B3', BRIDGE, '⛔ a bool stamp is taken for a move',
     [('    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:\n        return None\n    return v\n',
       '    if not isinstance(v, (int, float)) or v <= 0:\n        return None\n    return v\n')]),
    ('B4', BRIDGE, '⛔ a stamp left on a running run is taken for a move — a push for nothing',
     [('    return (status == "queued" and isinstance(doc, dict)\n',
       '    return (isinstance(doc, dict)\n')]),
    ('B5', BRIDGE, "⛔ the peek never pushes a move — it waits for the watcher's own tick",
     [('            reason = "run-moved"\n',
       '            reason = None\n')]),
    ('B6', BRIDGE, '⛔ running again pushed while the stamp is still on (the last-second write)',
     [('        elif (reason is None and status == "ongoing" and e.get("moved")\n              and _moved_stamp(doc.get("movedToQueueAt")) is None):\n',
       '        elif (reason is None and status == "ongoing" and e.get("moved")):\n')]),
    ('B7', BRIDGE, "⛔⛔ the login card that continues by itself still says 'reply retry'",
     [('        if _LOGIN_CONTINUES_MARK in str(plan.get("details") or "").lower():\n',
       '        if False:\n')]),
    ('B8', BRIDGE, '⛔⛔ every login card says it continues by itself — an older computer never will',
     [('        if _LOGIN_CONTINUES_MARK in str(plan.get("details") or "").lower():\n',
       '        if True:\n')]),
    ('B9', BRIDGE, '⛔ the note keeps the agent-only marker',
     [('    s = " ".join(v.replace(_AGENT_ONLY_MARKER_TEXT, " ").replace("──", " ").split())\n    return s[:_MOVE_NOTE_MAX].rstrip() or None\n',
       '    s = " ".join(v.split())\n    return s[:_MOVE_NOTE_MAX].rstrip() or None\n')]),
    ('B10', BRIDGE, '⛔ the note is not cut to 280',
     [('    s = " ".join(v.replace(_AGENT_ONLY_MARKER_TEXT, " ").replace("──", " ").split())\n    return s[:_MOVE_NOTE_MAX].rstrip() or None\n',
       '    s = " ".join(v.replace(_AGENT_ONLY_MARKER_TEXT, " ").replace("──", " ").split())\n    return s.rstrip() or None\n')]),
    ('P1', POLL, '⛔⛔ a move is never told',
     [('                    out.extend(_moved_lines(run))\n',
       '                    pass\n')]),
    ('P2', POLL, '⛔⛔ one message per stamp or place in line, not per stay — a re-stamp repeats it',
     [('            if not prior_moved:\n                quiet = ',
       '            if True:\n                quiet = ')]),
    ('P3', POLL, '⛔ a first tick tells an old move',
     [('                quiet = ((baseline or "moved" not in prior)\n                         and now_ms - stamp > _RECENT_COMPLETION_MS)\n',
       '                quiet = False\n')]),
    ('P4', POLL, '⛔ a sign-in tick replays an untracked move',
     [('                if not quiet and not (suppress_replay and not prior):\n                    out.extend(_moved_lines(run))\n',
       '                if not quiet:\n                    out.extend(_moved_lines(run))\n')]),
    ('P5', POLL, '⛔ running again told while the stamp is still on (the last-second write)',
     [('            if run.get("movedToQueueAt") is None:\n                out.append(_running_again_line(run))\n',
       '            if True:\n                out.append(_running_again_line(run))\n')]),
    ('P6', POLL, '⛔⛔ running again is never told',
     [('                out.append(_running_again_line(run))\n',
       '                pass\n')]),
    ('P7', POLL, '⛔ a run that ended keeps its move — a later move is never told',
     [('        elif not _is_active(run):\n            moved = False\n',
       '        elif False:\n            moved = False\n')]),
    ('P8', POLL, '⛔⛔ the stay is not remembered — the move is told every tick',
     [('            "moved": moved,\n',
       '            "moved": False,\n')]),
    ('P9', POLL, '⛔ a stamp on a run that is not queued is taken for a move',
     [('    if run.get("status") != "queued" or isinstance(v, bool) or not isinstance(v, (int, float)):\n',
       '    if isinstance(v, bool) or not isinstance(v, (int, float)):\n')]),
    ('P10', POLL, "⛔⛔ the owner's note is not sent",
     [('        lines.append(f"   Their note: \\"{note}\\"")\n',
       '        pass\n')]),
    ('P11', POLL, '⛔ a bool stamp is taken for a move',
     [('    if run.get("status") != "queued" or isinstance(v, bool) or not isinstance(v, (int, float)):\n',
       '    if run.get("status") != "queued" or not isinstance(v, (int, float)):\n')]),
    ('P12', POLL, '⛔ the note keeps the agent-only marker',
     [('    s = " ".join(v.replace(_AGENT_ONLY_MARKER_TEXT, " ").replace("──", " ").split())\n',
       '    s = " ".join(v.split())\n')]),
    ('S1', SR, '⛔⛔ status never says the run was moved back',
     [('        stat += ", moved back to the queue by the computer\'s owner"\n',
       '        pass\n')]),
    ('S2', SR, "⛔⛔ status leaves out the owner's note",
     [('        lines.append(f"  Their note: \\"{note}\\"")\n',
       '        pass\n')]),
    ('S3', SR, "⛔ status's move lines are never added",
     [('    lines += _moved_lines(r)\n    lines += _fmt_pipeline_config(r.get("pipelineConfig"))\n',
       '    lines += _fmt_pipeline_config(r.get("pipelineConfig"))\n')]),
    ('S4', SR, "⛔ updates' move lines are never added",
     [('        lines += _moved_lines(r)\n        lines += _fmt_pipeline_config(r.get("pipelineConfig"))\n',
       '        lines += _fmt_pipeline_config(r.get("pipelineConfig"))\n')]),
    ('S5', SR, '⛔ list never marks a moved run',
     [('        moved = " — moved back to the queue by the computer\'s owner" if _moved_to_queue(r) else ""\n',
       '        moved = ""\n')]),
    ('S6', SR, '⛔ a stamp on a running run is shown as a move',
     [('    return (r.get("status") == "queued" and not isinstance(v, bool)\n',
       '    return (not isinstance(v, bool)\n')]),
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
