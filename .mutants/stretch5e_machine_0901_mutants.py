#!/usr/bin/env python3
"""Mutation harness for stretch 5E's machine half (2026-09-01).

⭐⭐ ONE SENTENCE: things happened on this computer and nobody was told.

── The only thing the machine could ever say ───────────────────────────────

G* — MEASURED: the research computer had exactly ONE server-side notify ask and
it was gated to two event types, both of them good news. A run waiting on a
sign-in at 02:00, a quota exhaustion that then waits, a stop at the five-hour
ceiling, a backend restart mid-run — all written to Firestore and to nothing
else, while the settings screen promised "a research finished, hit an error,
went offline mid-run, or needs you". Only "finished" had a sender.

⭐ A run started VIA THE AGENT was already covered by a five-minute watcher, and
the tracker did not know that. The gap was runs started in the web app.

── The pause the watchdog cannot see ───────────────────────────────────────

P* — `wait_if_paused` had NO timeout: the only wait in the pipeline with no
bound. And the worker watchdog EXCLUDES paused time from its active-time
ceiling on purpose, so a run parked there accrued nothing, tripped nothing, and
sat forever having spoken exactly once.

── The outage notice that could not be sent during an outage ───────────────

F* — one branch of indentation. The telemetry flush sat inside
`if _firebase_db is not None:`, so FIRESTORE_OUTAGE_STARTED — the one event whose
entire purpose is to report that Firestore is unreachable — was unsendable for
exactly as long as the thing it describes was true. Telemetry does not use
Firestore; it POSTs to the web app over HTTPS.

── The sweep that re-dated the dead ────────────────────────────────────────

S* — owner-reported the same day: the agent announced a research "stopped early"
for a run from weeks earlier. The stuck-run sweep stamps `updatedAt = now` with
no age bound, and `updatedAt` is the ONLY timestamp the run reaches the watcher
on. Reset Backend made a month-old corpse look freshly finished.

⛔ THE OVER-CORRECTIONS MATTER AS MUCH AS THE FIXES: S2 stops the sweep doing its
job, S4 refuses to sweep a doc that simply has no timestamp (which is every one
of the sweep's own existing fixtures), G3 wakes somebody for an infra retry the
run recovered from by itself, and P4 kills a run the person was about to resume.

⚠ Does NOT demand a clean git tree — the wave is deliberately unpushed. It
snapshots the CONTENT of what it mutates and verifies a byte-identical restore.

    python .mutants/stretch5e_machine_0901_mutants.py
"""
from __future__ import annotations

import atexit
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

T_5E = "tests/test_stretch5e_0901.py"
T_SWEEP = "tests/test_sweep_stuck_research.py"
BOTH = f"{T_5E} {T_SWEEP}"

# (id, file, direction, why, [(from, to), ...], tests)
MUTANTS = [
    # ══ the sender the machine never had ═════════════════════════════════
    ("G1", RESEARCH, "under",
     "⛔⛔⛔ THE DEFECT ITSELF — nothing but a finished phase can be announced "
     "again, so every blocker, stall and stop dies on the machine and the person "
     "is told nothing until they happen to open a tab",
     [('        or data.get("recoverability") == "blocker"', '        or False')],
     T_5E),
    ("G2", RESEARCH, "under",
     "the terminal branch is dropped instead — the notices that already worked "
     "are the ones that stop, which is the cost this fix must not have",
     [('        (event_type in _NOTIFY_TERMINAL and isinstance(phase, int) and 1 <= phase <= 5)',
       '        (False)')],
     T_5E),
    ("G3", RESEARCH, "over",
     "⛔ EVERY card notifies, including the recoverable ones the run heals by "
     "itself. Waking somebody for an infra retry is how a person turns the whole "
     "category off, which then costs them the real blockers.",
     [('        or data.get("recoverability") == "blocker"',
       '        or bool(data.get("recoverability"))')],
     T_5E),
    ("G4", RESEARCH, "under",
     "⛔⛔ THE MISS CROSS-VERIFY FOUND, restored — the gate keys on the EVENT "
     "NAME again. `emit_decision` takes an `event_name` override and every "
     "overnight blocker uses one, so this matches none of them and the 02:00 "
     "sign-in in the comment above it is silent once more.",
     [('        or data.get("recoverability") == "blocker"',
       '        or event_type == "pipeline_error"')],
     T_5E),
    ("G5", RESEARCH, "over",
     "⛔ the `quiet` exclusion comes back — and quiet means 'do not paint the "
     "tile red for a phase never reached', so this silences precisely the "
     "preflight blockers that strand a run before it starts",
     [('        or data.get("recoverability") == "blocker"',
       '        or (data.get("recoverability") == "blocker" and not data.get("quiet"))')],
     T_5E),
    ("G6", RESEARCH, "over",
     "⛔⛔ a user-pressed Stop notifies again — every pipeline_stopped emit site "
     "is the person's own action, so this pushes 'your research stopped' at "
     "somebody who just pressed Stop",
     [('        or data.get("recoverability") == "blocker"',
       '        or data.get("recoverability") == "blocker"\n        or event_type == "pipeline_stopped"')],
     T_5E),
    ("G7", RESEARCH, "under",
     "⛔ a blocker is held to the phase range, so one raised in preflight — "
     "exactly the kind that strands a run overnight — is dropped",
     [('        or data.get("recoverability") == "blocker"',
       '        or (data.get("recoverability") == "blocker" and isinstance(phase, int) and 1 <= phase <= 5)')],
     T_5E),
    ("G8", RESEARCH, "over",
     "a write that never landed is announced anyway, naming a seq that points at "
     "an earlier phase's document",
     [('    _notify_ok = bool(_emitted_seq) and (', '    _notify_ok = True and (')],
     T_5E),

    # ══ the pause with no bound ══════════════════════════════════════════
    ("P1", RESEARCH, "under",
     "⛔⛔ the wait goes back to having no timeout at all — and the watchdog is "
     "blind to this state by design, so the run sits forever with nothing "
     "watching it and nothing said",
     [('                timeout=PAUSE_HEARTBEAT_S,\n', '')],
     T_5E),
    ("P2", RESEARCH, "under",
     "the heartbeat is gone — it speaks once at the start and then goes silent "
     "for as long as the pause lasts, which for an unanswered blocker is forever",
     [('            log(f"[pause] still waiting on {self.pause_reason or \'a decision\'} after "\n'
       '                f"{int(_paused_for // 60)}m — this run cannot continue until it is answered",\n'
       '                "WARN")\n', '')],
     T_5E),
    ("P3", RESEARCH, "under",
     "the bound never ends the wait — the clock runs, the log says it is waiting, "
     "and nothing ever stops it",
     [('                self.request_stop()\n                break', '                break')],
     T_5E),
    ("P4", RESEARCH, "over",
     "⛔ the bound collapses to the heartbeat, so a run is killed ten minutes "
     "into a pause the person was about to answer — a login takes longer than "
     "that to walk to the other room for",
     [('PAUSE_MAX_WAIT_S = 86400.0', 'PAUSE_MAX_WAIT_S = 600.0')],
     T_5E),
    ("P5", RESEARCH, "over",
     "the heartbeat is as long as the bound, so it speaks once and gives up — "
     "the silence being fixed, wearing a timer",
     [('PAUSE_HEARTBEAT_S = 600.0', 'PAUSE_HEARTBEAT_S = 86400.0')],
     T_5E),

    # ══ the outage notice ════════════════════════════════════════════════
    ("F1", RESEARCH, "under",
     "⛔⛔ THE ONE BRANCH OF INDENTATION — the flush goes back behind the "
     "Firestore check, so the event whose whole purpose is to report a Firestore "
     "outage cannot be sent for as long as the outage is happening",
     [('            tm.flush_in_background()\n            if _firebase_db is not None:',
       '            if _firebase_db is not None:\n                tm.flush_in_background()')],
     T_5E),
    ("F2", RESEARCH, "under",
     "the flush is gated to worker 1, so a worker-2 spool never goes out at all — "
     "the reason it was moved off the heartbeat loop in the first place",
     [('            tm.flush_in_background()\n            if _firebase_db is not None:',
       '            if WORKER_ID == 1:\n                tm.flush_in_background()\n            if _firebase_db is not None:')],
     T_5E),

    # ══ the sweep that re-dated the dead ═════════════════════════════════
    ("S1", RESEARCH, "under",
     "⛔⛔ THE OWNER'S REPORT — every swept run is re-dated to NOW again, so a "
     "month-old corpse looks freshly finished to the watcher and is announced as "
     "having stopped early",
     [('            "updatedAt": _prior_ms if _stale else now_ms,',
       '            "updatedAt": now_ms,')],
     BOTH),
    ("S2", RESEARCH, "over",
     "⛔ the bound is a minute, so an ordinary stuck run is left stuck — the "
     "sweep stops doing the job it exists for",
     [('SWEEP_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000', 'SWEEP_MAX_AGE_MS = 60 * 1000')],
     BOTH),
    ("S3", RESEARCH, "under",
     "⛔⛔ PINNED AT THE CALLER — the wrapper stops passing the bound, so the "
     "rule is perfectly correct and never applied, and every unit test of the "
     "sweep itself still passes",
     [('                max_age_ms=SWEEP_MAX_AGE_MS,\n', '')],
     T_5E),
    ("S4", RESEARCH, "over",
     "⛔⛔ THE OVER-CORRECTION CROSS-VERIFY FOUND — an old doc is SKIPPED rather "
     "than swept-without-re-dating, which makes Reset Backend and Unpair "
     "permanent no-ops for exactly the runs a person pressed the button to "
     "clear, while both callers still report 'no stale runs found'",
     [('        if _stale:\n            skipped_old += 1',
       '        if _stale:\n            skipped_old += 1\n            continue')],
     BOTH),
    ("S7", RESEARCH, "over",
     "⛔ a document with NO timestamp is treated as ancient, so its updatedAt is "
     "frozen to None — unknown age is not old age, and every one of the sweep's "
     "own fixtures is timestamp-free",
     [('        _stale = (max_age_ms is not None and _prior_ms is not None\n'
       '                  and now_ms - _prior_ms > max_age_ms)',
       '        _stale = (max_age_ms is not None\n'
       '                  and now_ms - (_prior_ms or 0) > max_age_ms)')],
     BOTH),
    ("S5", RESEARCH, "under",
     "⛔ `stoppedAt` goes back to NOW for a run that died a week ago — the field "
     "anything asking when it ended should be reading, lying by exactly the "
     "amount that matters",
     [('            "stoppedAt": int(_prior_ms) if _prior_ms is not None else now_ms,',
       '            "stoppedAt": now_ms,')],
     T_5E),
    ("S6", RESEARCH, "under",
     "the skip is silent, which is how a bound becomes the next mystery",
     [('    if skipped_old:', '    if False:')],
     T_5E),
    ("P6", RESEARCH, "under",
     "⛔⛔ the pause flag is left SET when the bound gives up, so the worker "
     "watchdog — which excludes paused time from its ceiling by design — stays "
     "blind for the rest of the process",
     [('                self.pause_event.clear()\n                self._pause_gave_up = True',
       '                self._pause_gave_up = True')],
     T_5E),
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
    print(f"\n{len(MUTANTS)} mutants — stretch 5E (the machine half)\n")

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
    # repo has been bitten by exactly that.
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
