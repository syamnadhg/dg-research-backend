"""Mutation harness for the backend half of the notification-reliability wave.

⭐ THREE FIXES, AND ALL THREE ARE ABOUT A PROCESS THAT MUST NOT DISAPPEAR OUT
FROM UNDER ITS OWN WORK.

  A* — the log line. It said "delivered ✓" for any HTTP 200 and then printed the
       dedup keys the route had BUILT, so a call that reached zero devices and
       sent zero mail printed a tick. That line is the ONLY view anyone has of
       this path, and it is what sent the investigation to the wrong place.
  B* — the retry. A single fire-and-forget POST with no replay path behind it.
  C* — the respawn. `os._exit(0)` after a Firestore blip is right under a
       supervisor and fatal without one, and the existing probe answers a
       machine-wide question rather than "is MY supervisor alive".
  D* — the handoff gate. Idle is not finished: the worker goes idle while the
       two POSTs that hand the run to the web app are still in flight, and
       killing the P4/P5 one aborts the request, SIGTERMs ffmpeg and
       terminalises the research as stopped.

⛔ THE OVER-CORRECTIONS ARE THE HALF THAT MATTER. C2/C4/C6 are all ways to make
the recovery MORE eager and lose the session it was protecting; D2/D3 are ways to
make it more patient and leave a worker permanently deaf.

    .venv/bin/python .mutants/notify_reliability_0816_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_SUITES = ("tests/test_notify_reliability_0816.py "
               "tests/test_firebase_autoheal.py "
               "tests/test_phase_notices_0816.py")

MUTATED_FILES = ("research.py",)

SURVIVOR_CONFIRMATIONS = 2

ENV = {**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "")}

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ── the log line ────────────────────────────────────────────────────────
    ("A1", "research.py", "under",
     "⭐ a 200 is logged as delivery again — the tick that made a call reaching "
     "zero devices look successful, on the one channel anybody can see",
     [('log(f"phase-notify: P{phase} {event_type} → {_summarize_notify_reply(_resp.text)}")',
       'log(f"phase-notify: P{phase} {event_type} delivered ✓")')]),

    ("A2", "research.py", "over",
     "⛔ an UNPARSEABLE reply reports success — a 200 the caller does not "
     "understand is exactly the shape a changed route produces, and that is the "
     "moment the log must stop claiming delivery",
     [('        return f"HTTP 200, unparsed reply ({str(body_text)[:80]})"',
       '        return "delivered"')]),

    ("A3", "research.py", "over",
     "⛔ a reply with no delivery detail reports success for the same reason",
     [('        return f"HTTP 200, no delivery detail ({str(body_text)[:80]})"\n'
       '    if not rows:',
       '        return "delivered"\n'
       '    if not rows:')]),

    # ── the retry ───────────────────────────────────────────────────────────
    ("B1", "research.py", "under",
     "⭐ the ask is tried once — one network blip is that phase's notification "
     "gone for good, and nothing behind it replays",
     [("        for _attempt in range(1, 4):", "        for _attempt in range(1, 2):")]),

    ("B2", "research.py", "over",
     "⛔ a 4xx is retried — an unauthorised device or a malformed body hammered "
     "three times, which changes nothing except the load and the limiter",
     [("                if _resp.status_code < 500:\n"
       '                    log(f"phase-notify: P{phase} HTTP {_resp.status_code} ({_resp.text[:160]})", "WARN")\n'
       "                    return\n", "")]),

    ("B3", "research.py", "over",
     "⛔ a SUCCESS is retried — the same notice delivered three times, and a log "
     "line that says so three times",
     [('                    log(f"phase-notify: P{phase} {event_type} → {_summarize_notify_reply(_resp.text)}")\n'
       "                    return\n",
       '                    log(f"phase-notify: P{phase} {event_type} → {_summarize_notify_reply(_resp.text)}")\n')]),

    ("B4", "research.py", "over",
     "⛔ no backoff — three immediate retries against a web app that is "
     "restarting is a hammer, not a retry",
     [("            time.sleep(_delay)", "            pass")]),

    # ── the supervisor probe ────────────────────────────────────────────────
    ("C1", "research.py", "over",
     "⛔⛔ THE OLD PROBE — machine-wide rather than parent. On a laptop running "
     "the supervised fleet AND a foreground --serve at once (the owner's own "
     "setup) it says 'supervised' for the foreground session and os._exit()s the "
     "very session it was meant to protect",
     [("            if pid == ppid and role == \"daemon-loop\":",
       "            if role == \"daemon-loop\":")]),

    ("C2", "research.py", "over",
     "⛔ a re-parented process (ppid 1, the real parent already dead) counts as "
     "supervised — the one case where a supervisor is definitely NOT coming back",
     [("    if ppid <= 1:\n        return False\n", "")]),

    ("C3", "research.py", "over",
     "⛔ a failed probe assumes SUPERVISED — guessing that way costs an "
     "unrecoverable exit, guessing the other way costs a stale listener that "
     "logs loudly; only one of those is survivable",
     [('        log(f"[reconnect] supervisor probe failed ({_e}) — assuming foreground", "DEBUG")\n'
       "    return False",
       '        log(f"[reconnect] supervisor probe failed ({_e})", "DEBUG")\n'
       "        return True\n"
       "    return False")]),

    # ── the recovery ────────────────────────────────────────────────────────
    ("C4", "research.py", "over",
     "⭐⭐ THE ORIGINAL DEFECT — every reconnect os._exit()s, so a FOREGROUND "
     "serve ends the session the user is watching and the device tile ages into "
     "offline with no auto-recovery",
     [("    if _supervisor_is_my_parent():\n"
       '        log(f"[reconnect] {reason} — supervised, clean respawn to re-bind listeners", "INFO")',
       "    if True:\n"
       '        log(f"[reconnect] {reason} — supervised, clean respawn to re-bind listeners", "INFO")')]),

    ("C5", "research.py", "under",
     "⛔ a SUPERVISED worker stops respawning — the clean boot that makes "
     "listener health deterministic never happens, and the worker stays deaf",
     [('        _schedule_server_exit("firestore-reconnect", delay_sec=3.0 + (max(1, WORKER_ID) - 1) * 8.0)\n'
       "        return\n"
       "    if _watch_rebinder is None:",
       "        return\n"
       "    if _watch_rebinder is None:")]),

    ("C6", "research.py", "over",
     "⛔⛔ a FAILED rebind exits — reintroducing the exact defect this function "
     "exists to remove, on the rarer path where it is hardest to reproduce",
     [('        log(f"[reconnect] listener re-bind failed ({_e}) — staying up; restart this "\n'
       '            "serve if new runs are not picked up", "WARN")',
       '        _schedule_server_exit("firestore-reconnect", delay_sec=3.0)')]),

    ("C7", "research.py", "over",
     "⛔ the rebind runs INLINE on the event loop — unsubscribe() joins a "
     "background consumer thread, so this stalls the heartbeat and the frontend "
     "reports the device offline during the very recovery meant to keep it online",
     [("        await asyncio.to_thread(_watch_rebinder)", "        _watch_rebinder()")]),

    ("C8", "research.py", "under",
     "⛔ only ONE of the two watches is re-bound — 'online but deaf' with a "
     "reassuring log line, which is the condition this whole path exists to clear",
     [("    if uid and device_id:\n"
       "        _start_device_command_listener(uid, device_id, loop=loop)",
       "    if False:\n"
       "        _start_device_command_listener(uid, device_id, loop=loop)")]),

    ("C9", "research.py", "under",
     "⛔ the handles are not nulled between drop and re-attach, so a failure part "
     "way through leaves a handle to a stream that is already dead and shutdown "
     "unsubscribes it a second time",
     [("    _start_listener = None\n    _device_cmd_watch = None\n", "")]),

    ("C10", "research.py", "under",
     "⭐ nothing registers the rebinder at boot, so a foreground serve has no "
     "recovery at all and simply says so forever",
     [("            _watch_rebinder = lambda: _rebind_firestore_watches(  # noqa: E731",
       "            _unused_rebinder = lambda: _rebind_firestore_watches(  # noqa: E731")]),

    # ── the handoff gate ────────────────────────────────────────────────────
    ("D1", "research.py", "under",
     "⭐ the respawn stops looking before it exits — it lands on top of the two "
     "POSTs that hand the run to the web app, and killing the P4/P5 one aborts "
     "the request, SIGTERMs ffmpeg and terminalises the research as stopped",
     [("        if pending and supervised:\n            return \"hold\", now + budget",
       "        if False:\n            return \"hold\", now + budget")]),

    ("D1b", "research.py", "under",
     "⛔ the loop stops consulting the gate at all — a perfectly tested decision "
     "that nothing asks",
     [('                    if _action == "hold":', '                    if False:')]),

    ("D2", "research.py", "over",
     "⛔⛔ the wait is UNBOUNDED — one wedged thread leaves this worker "
     "permanently deaf, which is the condition the respawn exists to clear",
     [('    if pending and now < wait_until:\n        return "hold", wait_until',
       '    if pending:\n        return "hold", wait_until')]),

    ("D2b", "research.py", "over",
     "⛔ the deadline RESTARTS on every poll, so a handoff that keeps looking "
     "busy holds for ever — the unbounded case by another road",
     [('    if pending and now < wait_until:\n        return "hold", wait_until',
       '    if pending and now < wait_until:\n        return "hold", now + budget')]),

    ("D8", "research.py", "over",
     "⛔ the supervisor probe is re-run on every poll — it shells out to `ps`, "
     "and this branch is re-entered every two seconds for up to an hour",
     [("                        False if _was_waiting else _supervisor_is_my_parent(),",
       "                        _supervisor_is_my_parent(),")]),

    ("D3", "research.py", "over",
     "⛔ the P4/P5 drive gets the BRIEF budget — ninety seconds lands squarely "
     "in the middle of a long video encode, and the abort kills it",
     [("        return _FE_DRIVE_WAIT_SEC if _fe_drive_inflight else _FE_HANDOFF_WAIT_SEC",
       "        return _FE_HANDOFF_WAIT_SEC")]),

    ("D4", "research.py", "over",
     "⛔ the non-destructive in-place rebind is deferred too — a foreground serve "
     "has nothing to wait for, and delaying its recovery buys nothing",
     [("        if pending and supervised:", "        if pending:")]),

    ("D5", "research.py", "under",
     "⛔ the notice thread is not counted, so the respawn cannot see it",
     [("        _fe_handoff_begin()\n        try:\n            _ask_with_retries()\n        finally:\n            _fe_handoff_end()",
       "        _ask_with_retries()")]),

    ("D6", "research.py", "under",
     "⛔ the P4/P5 drive is not counted — the one whose death costs the user an "
     "entire run",
     [("        _fe_handoff_begin(drive=True)\n        try:\n            _drive_once()\n        finally:\n            _fe_handoff_end(drive=True)",
       "        _drive_once()")]),

    ("D7", "research.py", "over",
     "⛔ the counter can go negative, so a stray end() makes a genuine handoff "
     "invisible to the gate",
     [("                _fe_drive_inflight = max(0, _fe_drive_inflight - 1)\n"
       "            else:\n"
       "                _fe_handoff_inflight = max(0, _fe_handoff_inflight - 1)",
       "                _fe_drive_inflight -= 1\n"
       "            else:\n"
       "                _fe_handoff_inflight -= 1")]),
]


def run_tests() -> bool:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *ROOT_SUITES.split(), "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, env=ENV,
    )
    return r.returncode == 0


def tracked_dirty() -> list[str]:
    r = subprocess.run(
        ["git", "status", "--porcelain", "--", *MUTATED_FILES],
        cwd=ROOT, capture_output=True, text=True,
    )
    return [ln for ln in r.stdout.strip().split("\n") if ln.strip()]


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
