"""Mutation harness for the backend's ASK — the seam that makes a phase
notification arrive with the app closed.

⭐ C1 IS THE FEATURE. Without the call in emit_event, every phase notice in the
product still needs an open browser tab, which is the whole thing the owner
asked to change on 2026-08-16.

⛔ THE OVER-CORRECTIONS ARE THE INTERESTING HALF, because this call crosses a
trust boundary — a machine causing its OWNER's inbox, push and email to fire:
  C4/C5  the seq. `_emit_to_firestore` bails without writing when Firestore is
         not configured, and the module global then still holds the PREVIOUS
         event's seq — which names a real document from an earlier phase. Both
         of these mutants make the ask point at the wrong event, and one of them
         (C5) does it by making the bail look successful.
  C6     a title in the request body. That single field turns this from "name an
         event" into a relay: a machine could announce whatever it liked, in the
         owner's inbox, over our sending domain.
  C2/C3  asking on every event, or on preflight. Phase 2 alone emits thousands
         of progress events.
  C7     the ask outside its try. emit_event is the critical path for every
         frontend state update; a notification must never be able to break it.

    .venv/bin/python .mutants/phase_notify_ask_0816_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_SUITES = ("tests/test_phase_notices_0816.py "
               "tests/test_brief_done_label_0811.py "
               "tests/test_p3_audio_and_retry_0806.py")

MUTATED_FILES = ("research.py",)

SURVIVOR_CONFIRMATIONS = 2

ENV = {**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "")}

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    ("C1", "research.py", "under",
     "⭐ THE FEATURE — nothing asks, so every phase notice needs an open browser "
     "tab again and a 90-minute run tells you nothing until you look",
     [('            _post_fe_phase_notice(\n                _fb_uid, _fb_research_id,\n                phase if isinstance(phase, int) else 0,\n                event_type, _emitted_seq,\n            )',
       "            pass")]),

    ("C2", "research.py", "over",
     "⛔ every event type asks — phase 2 alone emits thousands of progress events, "
     "so this is a notification per heartbeat",
     [('        (event_type in _NOTIFY_TERMINAL and isinstance(phase, int) and 1 <= phase <= 5)',
       '        (True)')]),

    ("C3", "research.py", "over",
     "⛔ preflight asks too — one pointless round trip per run, on every run, for "
     "a phase that produces nothing the user asked for",
     [("        (event_type in _NOTIFY_TERMINAL and isinstance(phase, int) and 1 <= phase <= 5)",
       "        (event_type in _NOTIFY_TERMINAL and isinstance(phase, int) and 0 <= phase <= 5)")]),

    ("C4", "research.py", "over",
     "⛔ the module global is used instead of the returned seq — when the write "
     "bailed, that global still holds the PREVIOUS event's seq, which names a "
     "real document from an earlier phase",
     [('            _post_fe_phase_notice(\n                _fb_uid, _fb_research_id,\n                phase if isinstance(phase, int) else 0,\n                event_type, _emitted_seq,\n            )',
       '            _post_fe_phase_notice(\n                _fb_uid, _fb_research_id,\n                phase if isinstance(phase, int) else 0,\n                event_type, _fb_seq,\n            )')]),

    ("C5", "research.py", "over",
     "⛔ a write that never happened reports a seq — the bail returns the stale "
     "global and the ask points at an event from an earlier phase",
     [("    if not _firebase_db or not _fb_uid or not _fb_research_id:\n        return None\n",
       "    if not _firebase_db or not _fb_uid or not _fb_research_id:\n        return _fb_seq\n")]),

    ("C5b", "research.py", "over",
     "⛔ a FAILED write reports a seq — the document does not exist, so the web "
     "app is asked to describe an event nobody wrote",
     [('        log(f"Firestore emit failed: {e}", "WARN")\n        return None',
       '        log(f"Firestore emit failed: {e}", "WARN")\n        return _fb_seq')]),

    ("C6", "research.py", "over",
     "⛔⛔ THE RELAY — the ask carries a title, so a machine composes what its "
     "OWNER reads in their inbox, their push and their email, over our sending "
     "domain. The whole security of this path is that it names an event and "
     "supplies no words.",
     [('                    "eventType": event_type,\n',
       '                    "eventType": event_type,\n                    "title": "Ready",\n')]),

    ("C7", "research.py", "over",
     "⛔ the ask is no longer wrapped — emit_event is the critical path for every "
     "frontend state update, and a notification failure would break it",
     [("        try:\n" + '            _post_fe_phase_notice(\n                _fb_uid, _fb_research_id,\n                phase if isinstance(phase, int) else 0,\n                event_type, _emitted_seq,\n            )' + "\n"
       "        except Exception as _pn_e:\n"
       '            log(f"phase-notify dispatch failed (non-fatal): {_pn_e}", "WARN")',
       '            _post_fe_phase_notice(\n                _fb_uid, _fb_research_id,\n                phase if isinstance(phase, int) else 0,\n                event_type, _emitted_seq,\n            )')]),

    # ⛔ Anchored on this thread's own NAME. `daemon=True,\n        ).start()`
    # occurs FOUR times in research.py — the first version of this mutant matched
    # one of the other three and the harness reported a survivor that had
    # measured nothing at all.
    ("C8", "research.py", "over",
     "⛔ the ask blocks the worker — a run with a slow or unreachable web app "
     "stalls on a notification instead of finishing",
     [('            name=f"phase-notify-{research_id[:8]}-{phase}",\n'
       "            daemon=True,\n        ).start()",
       '            name=f"phase-notify-{research_id[:8]}-{phase}",\n'
       "            daemon=True,\n        ).run()")]),

    ("C9", "research.py", "over",
     "⛔ a machine with revoked credentials fails the phase instead of skipping "
     "the ask — the browser's own notifier was always the backstop",
     [('        log("phase-notify: no synth id-token (creds revoked?) — skipping", "INFO")\n        return False',
       '        raise RuntimeError("no synth id-token")')]),

    ("C10", "research.py", "over",
     "⛔ the ask goes somewhere else — /api/uploadYouTube would re-drive P4/P5 "
     "from a phase-1 completion",
     [('f"{_FE_BASE_URL}/api/notify"', 'f"{_FE_BASE_URL}/api/uploadYouTube"')]),
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
                # ⛔⛔ UNIQUENESS, NOT MERE PRESENCE. A substring match once hit a
                # function 2,300 lines away and reported a gap that did not exist.
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
