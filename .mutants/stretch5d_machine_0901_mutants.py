#!/usr/bin/env python3
"""Mutation harness for stretch 5D's machine half (2026-09-01).

Two fixes, both of them about code that CLAIMED to do something it could not.

── The release twin sync ────────────────────────────────────────────────────

⛔⛔ `sync_fe_twin` shells out to the frontend's sync script, which takes the
skill bundle's path as its first positional argument. This tool passed NONE, so
the FE script fell back to a hardcoded sibling layout that does not exist in this
checkout, printed its own "not found", and exited 1. `bump()` renders that as a
WARNING and carries on — so the hosted skill twin has only ever been current
because somebody re-ran the script by hand after every release.

⭐ The mutants here are written against the ARGV, never the message. A guard on
the warning text would have passed throughout the entire period the sync did
nothing at all.

── The cascades that were never allowed to run ──────────────────────────────

⛔⛔ Two cascades walked five subcollections under a research document and
deleted every document in each. Under Track D this process is a SYNTHETIC DEVICE
user and four of those five are OWNER-ONLY in `firestore.rules`, so every delete
returned PERMISSION_DENIED into a bare `except: pass` underneath it. The comment
inside the loop already SAID the other four were "denied by design" — the
knowledge was written down at #720 and the loop kept running anyway.

⛔ The `commands` sweep is the one that works, and it is real work: queued
commands for a run being torn down. Deleting the dead four by deleting the whole
loop would strand those, which is a worse bug than the no-op — so it gets its own
mutant in the OVER direction.

⚠ Does NOT demand a clean git tree — the wave is deliberately unpushed. It
snapshots the CONTENT of what it mutates and verifies a byte-identical restore.

    python .mutants/stretch5d_machine_0901_mutants.py
"""
from __future__ import annotations

import atexit
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"
BUMP = "tools/bump_version.py"

T_5D = "tests/test_stretch5d_0901.py"
T_BUMP = "tests/test_bump_version.py"
T_HEAL = "tests/test_grpc_synth_403_heal.py"

# (id, file, direction, why, [(from, to), ...], tests)
MUTANTS = [
    # ══ the release twin sync ════════════════════════════════════════════
    ("B1", BUMP, "under",
     "⛔⛔ THE DEFECT ITSELF — the source path is not passed, so the FE script "
     "guesses a layout that does not exist, exits 1, and the bump reports a "
     "warning. Every release syncs nothing.",
     [('proc = subprocess.run([node, str(script), str(src)], cwd=str(web),',
       'proc = subprocess.run([node, str(script)], cwd=str(web),')],
     T_BUMP),
    ("B2", BUMP, "under",
     "the bundle path points somewhere that is not the bundle, so the FE script "
     "is handed a directory with no skill in it",
     [('    src = root / "agent" / "facade" / "skill"',
       '    src = root / "agent" / "facade"')],
     T_BUMP),
    ("B3", BUMP, "under",
     "⛔ a missing bundle runs the sync anyway rather than refusing — which is "
     "the silent no-op again, one level down",
     [('    if not src.is_dir():\n        return False, f"FE sync skipped — no skill bundle at {src}"\n', '')],
     T_BUMP),
    ("B4", BUMP, "over",
     "the refusal reports SUCCESS, so a release that synced nothing prints OK",
     [('        return False, f"FE sync skipped — no skill bundle at {src}"',
       '        return True, f"FE sync skipped — no skill bundle at {src}"')],
     T_BUMP),

    # ══ the cascades ═════════════════════════════════════════════════════
    ("C1", RESEARCH, "over",
     "⛔⛔ the four denied subcollections come back in the startup sweep — a walk "
     "over every document to issue deletes that return PERMISSION_DENIED into a "
     "bare except, which reads like cleanup and is not",
     [('                                for sd in ref.collection("commands").stream():',
       '                                for sub in ("documents", "audios", "messages",\n'
       '                                            "pipeline_events", "commands"):\n'
       '                                 for sd in ref.collection(sub).stream():')],
     f"{T_5D} {T_HEAL}"),
    ("C2", RESEARCH, "over",
     "⛔⛔ the same four come back in delete_run",
     [('                        for sd in research_ref.collection("commands").stream():',
       '                        for sub in ("documents", "audios", "messages",\n'
       '                                    "pipeline_events", "commands"):\n'
       '                         for sd in research_ref.collection(sub).stream():')],
     f"{T_5D} {T_HEAL}"),
    ("C3", RESEARCH, "under",
     "⛔ OVER-CORRECTION — the commands sweep goes too, stranding real queued "
     "work for a run being torn down. The one delete that could ever land.",
     [('                            for sd in ref.collection("commands").stream():\n'
       '                                    try:\n'
       '                                        _grpc_write_with_heal(\n'
       '                                            lambda sd=sd: sd.reference.delete(),\n'
       '                                            what="cascade-sweep cmd delete")\n'
       '                                    except Exception: pass',
       '                            for sd in []:\n'
       '                                    try:\n'
       '                                        _grpc_write_with_heal(\n'
       '                                            lambda sd=sd: sd.reference.delete(),\n'
       '                                            what="cascade-sweep cmd delete")\n'
       '                                    except Exception: pass')],
     f"{T_5D} {T_HEAL}"),
    ("C4", RESEARCH, "under",
     "the surviving commands delete loses its heal wrapper, so a stale-token 403 "
     "stops being repairable and the denial goes back to being invisible",
     [('                                        _grpc_write_with_heal(\n'
       '                                            lambda sd=sd: sd.reference.delete(),\n'
       '                                            what="cascade-sweep cmd delete")',
       '                                        sd.reference.delete()')],
     f"{T_5D} {T_HEAL}"),
    ("C5", RESEARCH, "over",
     "⛔ the log line claims a cascade again — the real cost of the dead loop, "
     "because it told anyone checking that the cleanup had run",
     [('                    log(f"[delete_run] cleared queued commands for "',
       '                    log(f"[delete_run] cascaded Firestore for "')],
     T_5D),
    ("C6", RESEARCH, "under",
     "the note naming who DOES delete the rest is dropped, so the removal reads "
     "as a gap and the next person re-adds the dead loop",
     [("                        f\"documents/audios/messages/pipeline_events are the app's \"\n"
       "                        f\"to delete (owner-only rule)\")",
       '                        f"")')],
     T_5D),
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


ORIGINALS = {rel: _read(rel) for rel in {m[1] for m in MUTANTS}}


def restore() -> None:
    for rel, text in ORIGINALS.items():
        _write(rel, text)


atexit.register(restore)
signal.signal(signal.SIGINT, lambda *_a: (restore(), sys.exit(130)))
signal.signal(signal.SIGTERM, lambda *_a: (restore(), sys.exit(143)))


def main() -> int:
    killed = 0
    survivors: list[str] = []
    print(f"\n{len(MUTANTS)} mutants — stretch 5D (the machine half)\n")

    for mid, rel, _dir, why, edits, tests in MUTANTS:
        text = ORIGINALS[rel]
        ok = True
        for frm, to in edits:
            hits = text.count(frm)
            if hits != 1:
                print(f"  {mid}  ⛔ ANCHOR matched {hits}x — HARNESS FAULT, not a survivor")
                ok = False
                break
            text = text.replace(frm, to, 1)
        if not ok:
            survivors.append(f"{mid} (anchor)")
            restore()
            continue

        _write(rel, text)
        proc = subprocess.run(
            ["uv", "run", "pytest", "-x", "-q", *tests.split()],
            cwd=str(ROOT), capture_output=True, text=True)
        restore()

        if proc.returncode != 0:
            killed += 1
            print(f"  {mid}  ✓ killed")
        else:
            survivors.append(mid)
            print(f"  {mid}  ✗ SURVIVED — {why}")

    # ⛔ A byte-identical restore is CHECKED, not assumed. A harness that leaves
    # a mutant in the tree poisons every measurement taken after it, and this
    # repo has been bitten by exactly that three times.
    for rel, text in ORIGINALS.items():
        if _read(rel) != text:
            print(f"\n⛔⛔ RESTORE FAILED for {rel} — fix the tree before trusting anything above")
            return 2

    print(f"\n{killed}/{len(MUTANTS)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        return 1
    print("clean.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
