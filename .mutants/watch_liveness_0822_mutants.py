"""Mutation harness for wave 5 fix 1 — the listeners that carry Start and Stop.

⛔ WHAT THIS IS FOR. A Firestore snapshot callback runs on the library's own
consumer thread. Anything that escapes it is caught THERE, logged once, and the
thread returns — the watch stops delivering, the bidi RPC is never closed, and
nothing in this process is told. The machine keeps answering every health check
while Start and Stop go nowhere. Four such deaths sit in this machine's
`backend.err.log`, one of them raised inside our own callback.

⭐⭐ THE SHARPEST MUTANTS HERE:
  G4  — the guard logs and then RE-RAISES. Every test about the message still
        passes; the listener still dies. A guard that reports and does not hold
        is the defect wearing the fix's clothes.
  G6  — the guard narrows to one exception class. The death in the corpus was a
        TypeError and the one Fable found was an AttributeError.
  W1  — a handle we never attached reads as dead, so an idle machine tears down
        and re-attaches its listeners forever.
  R4  — the dead command handle is never unsubscribed before the new one
        attaches. Two watches on one collection means every Stop runs twice.
  R5  — the torn-down-run guard goes, so a listener that stops AS a run ends
        re-subscribes to a research that is over.
  P1  — the re-arm loses its floor, on a loop that runs every five seconds.
  V1  — the vendor logger goes unbridged again: the ONLY notice that a listener
        died goes back to the half of the logs nobody is asked to send.

⭐ Over-corrections:
  P2  — the gap becomes a delay before the FIRST attempt, so a dead Start button
        stays dead for a minute after we knew.
  R6  — an unsubscribe that raises aborts the re-arm. A stream torn down by the
        fault raises there; that is the ordinary case, not a reason to leave a
        run with no Stop.
  V5  — our own loggers inherit the vendor level, which re-hides the DEBUG line
        the stdlib bridge was written for.

    python .mutants/watch_liveness_0822_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_WATCH = "tests/test_watch_liveness_0822.py"
# ⛔ The stdlib-bridge file owns the installer these mutants also reach. A
# harness scoped to its own file would call every one of its assertions a gap.
T_BRIDGE = "tests/test_stdlib_log_bridge_0817.py"
ALL = [T_WATCH, T_BRIDGE]

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [

    # ══ the guard ═══════════════════════════════════════════════════════
    ("G1", "under", "⛔ the start listener is attached bare, so one throw ends "
     "the only thing that receives a Start",
     [('    _start_listener = col_ref.on_snapshot(_guard_snapshot(on_snapshot, "start"))',
       '    _start_listener = col_ref.on_snapshot(on_snapshot)')],
     [T_WATCH]),
    ("G2", "under", "the device-command listener is attached bare",
     [('        _device_cmd_watch = col_ref.on_snapshot(_guard_snapshot(_on_snap, "device-cmds"))',
       '        _device_cmd_watch = col_ref.on_snapshot(_on_snap)')],
     [T_WATCH]),
    ("G3", "under", "⛔ the per-run command listener is attached bare — that is "
     "the Stop button",
     [('    _fb_listener = col_ref.on_snapshot(_guard_snapshot(on_snapshot, "commands"))',
       '    _fb_listener = col_ref.on_snapshot(on_snapshot)')],
     [T_WATCH]),
    ("G4", "under", "⛔⛔ the guard logs and RE-RAISES. Every assertion about the "
     "message still passes and the listener still dies",
     [('            for _line in "".join(_tb.format_exc()).rstrip().splitlines():\n'
       '                log(f"[watch:{label}] {_line}", "ERROR")\n    return _guarded',
       '            for _line in "".join(_tb.format_exc()).rstrip().splitlines():\n'
       '                log(f"[watch:{label}] {_line}", "ERROR")\n            raise\n    return _guarded')],
     [T_WATCH]),
    ("G5", "under", "the guard swallows in silence, so a listener that stops "
     "handling anything leaves no line anywhere",
     [('        except Exception:\n            import traceback as _tb\n'
       '            log(f"[watch:{label}] handler raised',
       '        except Exception:\n            return\n            import traceback as _tb\n'
       '            log(f"[watch:{label}] handler raised')],
     [T_WATCH]),
    ("G6", "under", "⛔⛔ the guard narrows to one class — the death in the "
     "corpus was a TypeError",
     [('    def _guarded(*args):\n        try:\n            callback(*args)\n        except Exception:',
       '    def _guarded(*args):\n        try:\n            callback(*args)\n        except ValueError:')],
     [T_WATCH]),
    ("G7", "over", "a dropped Start is logged at WARN, which is what a routine "
     "scan failure looks like",
     [('            log(f"[watch:{label}] {_line}", "ERROR")',
       '            log(f"[watch:{label}] {_line}", "WARN")')],
     [T_WATCH]),
    ("G8", "under", "the traceback goes out as ONE multi-line write, so a log "
     "grows records with no timestamp and no level",
     [('            for _line in "".join(_tb.format_exc()).rstrip().splitlines():\n'
       '                log(f"[watch:{label}] {_line}", "ERROR")',
       '            log(f"[watch:{label}] " + "".join(_tb.format_exc()).rstrip(), "ERROR")')],
     [T_WATCH]),
    ("G9", "under", "the label is dropped, so three listeners share one line "
     "and a reader cannot tell which one stopped",
     [('            log(f"[watch:{label}] handler raised', '            log("[watch] handler raised')],
     [T_WATCH]),
    ("G10", "under", "the arguments are not passed through, so the guard "
     "breaks every callback it protects",
     [('            callback(*args)', '            callback()')],
     [T_WATCH]),
    # ⛔ G11 REWRITTEN 2026-08-22. The first version cut the phrase mid-sentence
    # and the words "still attached" survived in the next fragment — so it broke
    # the grammar and changed nothing a reader or a test could act on. An
    # equivalent mutant surviving says nothing about the suite; it is a fault in
    # the harness. This one removes the reassurance outright, which is the
    # premise that was meant.
    ("G11", "under", "the line no longer says the listener survived, so it "
     "reads exactly like the outage it prevents",
     [('            log(f"[watch:{label}] handler raised — this update was dropped, but the "\n'
       '                f"listener is still attached. Runs and commands that arrived with it "\n'
       '                f"are replayed on the next re-attach:", "ERROR")',
       '            log(f"[watch:{label}] handler raised — this update was dropped:", "ERROR")')],
     [T_WATCH]),

    # ══ spotting a watch that stopped ═══════════════════════════════════
    ("W1", "under", "⛔⛔ a handle we never attached reads as dead, so an idle "
     "machine re-attaches its listeners forever",
     [('    if handle is None:\n        return False', '    if handle is None:\n        return True')],
     [T_WATCH]),
    ("W2", "under", "anything without an `is_active` reads as dead, so a "
     "future library shape drives an endless re-arm",
     [('        if active is None:\n            return False',
       '        if active is None:\n            return True')],
     [T_WATCH]),
    ("W3", "under", "⛔ the read is outside the try again — `is_active` is a "
     "PROPERTY, and one that raises takes down the loop that asked",
     [('    try:\n        active = getattr(handle, "is_active", None)',
       '    active = getattr(handle, "is_active", None)\n    try:')],
     [T_WATCH]),
    ("W4", "under", "the answer is inverted: a live watch reads dead and a dead "
     "one reads live",
     [('        return not bool(active)', '        return bool(active)')],
     [T_WATCH]),

    # ══ which watches ═══════════════════════════════════════════════════
    ("D1", "under", "⛔ the per-run command listener is not looked at, so the "
     "Stop button is the one thing that never comes back",
     [('                                      ("commands", _fb_listener))',
       '                                      )')],
     [T_WATCH]),
    ("D2", "under", "the start listener is not looked at, so a run submitted "
     "from the web app is never picked up",
     [('    return [name for name, handle in (("start", _start_listener),',
       '    return [name for name, handle in ((')],
     [T_WATCH]),
    ("D3", "under", "the device-command listener is not looked at",
     [('                                      ("device-cmds", _device_cmd_watch),',
       '')],
     [T_WATCH]),

    # ══ putting it back ═════════════════════════════════════════════════
    ("R1", "under", "⛔ with no rebinder it reports the pair as re-attached "
     "anyway, so the log says repaired and nothing was",
     [('            log("[watch] a long-lived listener has stopped and no rebinder is "\n'
       '                "registered — restart the backend to pick up new runs", "WARN")',
       '            done.extend(n for n in ("start", "device-cmds") if n in names)')],
     [T_WATCH]),
    ("R2", "under", "a rebinder that raises propagates into the loop that keeps "
     "this machine reachable",
     [('            try:\n                _watch_rebinder()\n                done.extend',
       '            if True:\n                _watch_rebinder()\n                done.extend')],
     [T_WATCH]),
    ("R3", "under", "the stale command handle is left in place while the new "
     "one attaches, so a failure part way through leaves a dead handle held",
     [('            _old, _fb_listener = _fb_listener, None',
       '            _old = _fb_listener')],
     [T_WATCH]),
    ("R4", "under", "⛔⛔ the dead command handle is never unsubscribed — two "
     "watches on one collection means every Stop runs twice",
     [('                if _old is not None:\n                    _old.unsubscribe()',
       '                if _old is None:\n                    _old.unsubscribe()')],
     [T_WATCH]),
    ("R5", "under", "⛔⛔ the torn-down-run guard goes, so a command listener "
     "that stops as a run ends re-subscribes to a research that is over",
     [('        if not (_uid and _rid and _controls):',
       '        if False:')],
     [T_WATCH]),
    ("R6", "over", "an unsubscribe that raises aborts the re-arm — and a stream "
     "torn down by the fault raising there is the ORDINARY case",
     [('            try:\n                if _old is not None:\n                    _old.unsubscribe()\n'
       '            except Exception as _e:',
       '            if True:\n                if _old is not None:\n                    _old.unsubscribe()\n'
       '            except Exception as _e:')],
     [T_WATCH]),
    ("R7", "under", "a failed command attach is reported as re-attached",
     [('                _start_command_listener(_uid, _rid, loop)\n                done.append("commands")',
       '                done.append("commands")\n                _start_command_listener(_uid, _rid, loop)')],
     [T_WATCH]),
    ("R8", "under", "a missing rebinder also costs the run its Stop button, "
     "because the two halves stop being independent",
     [('    if "commands" in names:\n        # The per-run listener is not part',
       '    if "commands" in names and done:\n        # The per-run listener is not part')],
     [T_WATCH]),

    # ══ the per-pass check ══════════════════════════════════════════════
    ("P1", "under", "⛔⛔ the floor on retries is gone, on a loop that runs every "
     "five seconds",
     [('    if now - _watch_rearm_last_at < _WATCH_REARM_MIN_GAP_SEC:\n        return []',
       '    if False:\n        return []')],
     [T_WATCH]),
    ("P2", "over", "the gap becomes a delay before the FIRST attempt, so a dead "
     "Start button stays dead for a minute after we knew",
     [('_watch_rearm_last_at = 0.0', '_watch_rearm_last_at = time.time()')],
     [T_WATCH]),
    ("P3", "under", "the check runs inline, so unsubscribing — which stops and "
     "JOINS a thread — stalls the heartbeat and the device reads offline",
     [('        back = await asyncio.to_thread(_rearm_dead_watches, dead,\n'
       '                                       asyncio.get_running_loop())',
       '        back = _rearm_dead_watches(dead, asyncio.get_running_loop())')],
     [T_WATCH]),
    ("P4", "under", "the incident line moves AFTER the repair, so the one "
     "sentence explaining a silent machine is written only if the repair works",
     [('    log(f"[watch] {\', \'.join(dead)} stopped delivering while this computer stayed "\n'
       '        f"online — re-attaching so Start and Stop work again", "WARN")\n    try:',
       '    try:')],
     [T_WATCH]),
    ("P5", "under", "a re-arm that raises takes down the loop that keeps this "
     "machine reachable",
     [('    try:\n        back = await asyncio.to_thread(_rearm_dead_watches, dead,',
       '    if True:\n        back = await asyncio.to_thread(_rearm_dead_watches, dead,')],
     [T_WATCH]),
    ("P6", "under", "⛔⛔ the check is dropped from the branch that runs while "
     "Firestore is HEALTHY — which is the only case with no other cover",
     [('                await _rearm_dead_watches_if_any()\n', '')],
     [T_WATCH]),
    ("P7", "under", "a healthy machine logs the repair line on every pass",
     [('    dead = _dead_watch_names()\n    if not dead:\n        return []',
       '    dead = _dead_watch_names()\n    if dead is None:\n        return []')],
     [T_WATCH]),

    # ══ the only logger that says a listener died ═══════════════════════
    ("V1", "under", "⛔⛔ the vendor logger goes unbridged, so the ONLY notice "
     "that a listener stopped returns to the half of the logs nobody sends",
     [('_BRIDGED_VENDOR_LOGGERS = {"google.api_core.bidi": logging.WARNING}',
       '_BRIDGED_VENDOR_LOGGERS = {}')],
     [T_WATCH, T_BRIDGE]),
    ("V2", "under", "it is bridged at DEBUG, so `waiting for recv.` is written "
     "once per received message into the file a person is asked to send",
     [('_BRIDGED_VENDOR_LOGGERS = {"google.api_core.bidi": logging.WARNING}',
       '_BRIDGED_VENDOR_LOGGERS = {"google.api_core.bidi": logging.DEBUG}')],
     [T_WATCH]),
    ("V3", "under", "the installer ignores the vendor map entirely",
     [('    for name, level in [*((n, logging.DEBUG) for n in names), *vendor.items()]:',
       '    for name, level in [*((n, logging.DEBUG) for n in names)]:')],
     [T_WATCH, T_BRIDGE]),
    ("V4", "under", "the bridged name is the parent package, which quietly "
     "captures every other api_core logger as well",
     [('_BRIDGED_VENDOR_LOGGERS = {"google.api_core.bidi": logging.WARNING}',
       '_BRIDGED_VENDOR_LOGGERS = {"google.api_core": logging.WARNING}')],
     [T_WATCH]),
    ("V5", "over", "our own loggers inherit the vendor level, re-hiding the "
     "DEBUG line the stdlib bridge was written for",
     [('    for name, level in [*((n, logging.DEBUG) for n in names), *vendor.items()]:',
       '    for name, level in [*((n, logging.WARNING) for n in names), *vendor.items()]:')],
     [T_WATCH, T_BRIDGE]),
    ("V6", "under", "the vendor logger keeps propagating, so a future root "
     "config prints the death notice twice",
     [('        lg.propagate = False\n        installed.append(name)',
       '        lg.propagate = name in names\n        installed.append(name)')],
     [T_WATCH, T_BRIDGE]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ A stale `__pycache__/*.pyc` serves OLD bytecode for a source file
        # the harness has already rewritten, and the measurement then disagrees
        # with the file. In a harness that edits the source between every run a
        # cached module is not a nuisance — it is a kill or a survivor invented
        # out of nothing.
        rc = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *tests], cwd=ROOT, capture_output=True,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            timeout=_TEST_TIMEOUT_S).returncode
        return rc == 0, False
    except subprocess.TimeoutExpired:
        return False, True


def snapshot() -> dict[str, str]:
    return {f: (ROOT / f).read_text(encoding="utf-8") for f in MUTATED_FILES}


def drifted(before: dict[str, str]) -> list[str]:
    return [f for f, text in before.items()
            if (ROOT / f).read_text(encoding="utf-8") != text]


def main() -> int:
    before = snapshot()

    print("baseline… ", end="", flush=True)
    ok, timed_out = green(ALL)
    if not ok:
        print(f"{'TIMED OUT' if timed_out else 'RED'}. Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, direction, why, edits, tests in MUTANTS:
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            if not tests:
                raise ValueError("no tests declared")
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:70]}")
                mutated = mutated.replace(frm, to)
            target.write_text(mutated, encoding="utf-8")
            passed, timed_out = green(tests)
            killed = not passed
            note = " (via TIMEOUT — a test hung rather than failed, fix it)" if timed_out else ""
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} "
                  f"[{direction}] {why}{note}", flush=True)
            if not killed:
                survivors.append((mid, direction, why))
            elif timed_out:
                stale.append((mid, direction, f"{why} — KILLED ONLY BY TIMEOUT"))
        except ValueError as exc:
            print(f"! ERROR    {mid} {exc}")
            stale.append((mid, direction, why))
        finally:
            target.write_text(original, encoding="utf-8")

    left = drifted(before)
    if left:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in "
              "your source:\n" + "\n".join(left))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors) - len(stale)}/{len(MUTANTS)} killed "
          f"({over} over-corrections)")
    if stale:
        print("⚠ STALE ANCHORS (harness faults — these measured NOTHING):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w in stale))
    if survivors:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w in survivors))
    return 1 if (survivors or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
