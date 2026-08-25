"""Mutation harness for Wave 8 step B — the lines a run's folder must not collect.

⛔⛔ THE PLAN'S PREMISE WAS MEASURED FALSE, so this is not the feature that was
asked for. The wave called for tagging every line with its run because "a machine
runs two researches at once, so run A's folder holds run B's lines". Across 1,821
lines in the five real run folders on this machine there is not one foreign
researchId, topic, submitter or queue line — `_job_worker` awaits ONE pipeline at
a time and every worker is a separate PROCESS.

⛔ And the design would have cost more than it bought:
  • The per-run Firestore command listener runs on a thread the google SDK
    creates, which no context reaches. Every `Command received: STOP`, the reap
    and the exit would have left the folder — and for one measured run those
    three lines are the ONLY record of how it ended.
  • `_clear_local_logs` runs on that kind of thread and reads the process-global
    sink list to spare live folders. A context-scoped registry would make a
    clear-logs command arriving mid-run delete the folder being written to.

⭐ So the default is UNCHANGED and what exists is an explicit opt-out for eight
standing machine-concern functions. The mutants split three ways:

    the mechanism   — a scope that leaks, never releases, or reaches too far
    the exclusions  — a marking removed, so the noise comes back
    the RESTRAINT   — a marking ADDED where it silences a run's own story

The third group is the one that matters. Every `over` mutant below is a marking
somebody could plausibly add "for consistency", and each one deletes the lines
that explain why a run died.

    python .mutants/wave8_machine_scope_0824_mutants.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "research.py"
MUTATED_FILES = [SRC]

T_NEW = "tests/test_machine_log_scope_0824.py"
# ⛔ THE SIBLING FILES WHOSE PROPERTIES THIS SOURCE OWNS. A scope-limited harness
# in this repo has three times reported "real suite gaps" that were only its own
# blindness. The write-through, the bridge and the capture are shared surfaces.
T_CAP = "tests/test_run_log_capture_0818.py"
T_NOISE = "tests/test_log_noise_0819.py"
T_BRIDGE = "tests/test_stdlib_log_bridge_0817.py"
ALL = [T_NEW, T_CAP, T_NOISE, T_BRIDGE]

# ⛔ EVERY NAME ABOVE IS CHECKED AGAINST THE DISK BELOW. A harness in this
# repo has already shipped a `tests:` list naming a file that does not exist:
# pytest treats a missing path as an error, the run goes red, and EVERY mutant
# reads as killed. A harness that cannot fail is worse than no harness.
for _t in ALL:
    if not (ROOT / _t).is_file():
        raise SystemExit(f"harness names a test file that does not exist: {_t}")

PY = str(ROOT / ".venv" / "bin" / "python")
_TEST_TIMEOUT_S = 600

_GATE = """    if _LOG_SCOPE.get() == _LOG_SCOPE_MACHINE:
        return"""

_SET = """    token = _LOG_SCOPE.set(_LOG_SCOPE_MACHINE)"""

# ⛔ WIDENED 2026-08-24: `_run_log_scope` (the escape hatch) has a byte-identical
# `finally`, so the narrow anchor started matching twice and measured nothing.
# Both anchors now carry the `set` line that tells the two scopes apart.
_RESET = """    token = _LOG_SCOPE.set(_LOG_SCOPE_MACHINE)
    try:
        yield
    finally:
        _LOG_SCOPE.reset(token)"""

_DEFAULT = """_LOG_SCOPE = _log_contextvars.ContextVar("sr_log_scope", default="")"""

_ASYNC_BRANCH = """    if _ins.iscoroutinefunction(fn):"""

_WRAPS_ASYNC = """        @_ft.wraps(fn)
        async def _async_scoped(*args, **kwargs):"""

_BRIDGE_SCOPE = """            scope = (_machine_log_scope()
                     if record.name.split(".")[0] in _MACHINE_ONLY_BRIDGED
                     else _log_contextlib.nullcontext())"""

_BRIDGED_TUPLE = """_MACHINE_ONLY_BRIDGED = ("telemetry",)"""

_MARK_QUEUE = """@_machine_logged
def _recompute_deferred_queue_positions() -> None:"""

_MARK_HEARTBEAT = """@_machine_logged
async def _heartbeat_loop():"""

_MARK_START_LISTENER = """    @_machine_logged
    def on_snapshot(_col_snapshot, changes, _read_time):
        for change in changes:"""

_MARK_SENDLOGS = """    @_machine_logged
    def _work() -> None:"""

_MARK_ORPHAN = """    @_machine_logged
    async def _orphan_sweep_loop():"""

_ESCAPE_SET = """    token = _LOG_SCOPE.set("")
    try:
        yield
    finally:
        _LOG_SCOPE.reset(token)"""

_ESCAPE_USE = """    with _run_log_scope():
        log(msg, level)"""

_CANCEL_RUNNING = """                    _log_about_the_armed_run(f"Cancel: target {target_rid[:8]}… is the running job — requesting stop + scheduling exit{' (owner '+_oc+')' if _oc else ''}")"""

_RECONNECT = """async def _firebase_reconnect_loop():"""

_JOB_WORKER = """    async def _job_worker():"""

# ⛔⛔ MIS-NAMED ON THE FIRST WRITING, 2026-08-24. This anchor was labelled the
# DEVICE-command listener; it is the PER-RUN one — the callback that carries
# every `Command received: STOP`. The mutant was therefore worse than advertised,
# and the test written against it named a third function entirely and could never
# fire. Both are now anchored, separately, under their real names.
_PER_RUN_CMD_CB = """    def on_snapshot(_col_snapshot, changes, _read_time):
        # Firestore delivers all pre-existing docs as ADDED in the FIRST"""

_DEVICE_CMD_CB = """    def _on_snap(_col_snapshot, changes, _read_time):"""

MUTANTS: list[tuple[str, str, str, list[tuple[str, str]], list[str]]] = [
    # ══ the mechanism ═════════════════════════════════════════════════
    ("M1", "under", "⛔⛔ the exclusion never fires — every marked loop's lines "
     "come back, including 398 copies of one telemetry sentence and the start "
     "listener's account of other people's submissions",
     [(_GATE, "    if False:\n        return")],
     [T_NEW]),
    ("M2", "over", "⛔⛔ THE POLARITY FLIP: only MACHINE lines reach the run "
     "folder and the run's own lines are dropped. Every capture on the machine "
     "goes silent about the thing it captures",
     [(_GATE, "    if _LOG_SCOPE.get() != _LOG_SCOPE_MACHINE:\n        return")],
     [T_NEW, T_CAP]),
    ("M3", "over", "the scope is never entered, so the context manager is "
     "decoration and the marking means nothing",
     [(_SET, '    token = _LOG_SCOPE.set("")')],
     [T_NEW]),
    ("M4", "over", "⛔ the scope LEAKS: reset by value rather than by token, so a "
     "nested marking's exit un-marks its parent and the parent's remaining "
     "lines land in whatever run is armed",
     [(_RESET, '    token = _LOG_SCOPE.set(_LOG_SCOPE_MACHINE)\n'
               '    try:\n        yield\n'
               '    finally:\n        _LOG_SCOPE.set("")')],
     [T_NEW]),
    ("M5", "under", "⛔ the scope is NEVER released — one marked call and the "
     "whole task writes nothing to any run folder for the rest of its life",
     [(_RESET, "    token = _LOG_SCOPE.set(_LOG_SCOPE_MACHINE)\n"
               "    try:\n        yield\n"
               "    finally:\n        pass")],
     [T_NEW]),
    ("M6", "over", "the default is the machine, so an unmarked line — every "
     "line a run writes — is excluded by omission",
     [(_DEFAULT,
       '_LOG_SCOPE = _log_contextvars.ContextVar("sr_log_scope", '
       'default=_LOG_SCOPE_MACHINE)')],
     [T_NEW, T_CAP]),
    ("M7", "under", "the async branch is skipped, so every marked LOOP is "
     "wrapped as a plain function: `create_task` receives a coroutine object "
     "from a non-coroutine function and the marking silently does nothing",
     [(_ASYNC_BRANCH, "    if False:")],
     [T_NEW]),
    ("M8", "under", "the wrapper stops carrying the wrapped name, so every "
     "standing loop appears in tracebacks and logs as `_async_scoped`",
     [(_WRAPS_ASYNC, "        async def _async_scoped(*args, **kwargs):")],
     [T_NEW]),

    # ══ the bridge ════════════════════════════════════════════════════
    ("B1", "under", "the telemetry flood is back — measured at 398 of one run "
     "folder's 911 lines, all of them one repeated sentence",
     [(_BRIDGE_SCOPE, "            scope = _log_contextlib.nullcontext()")],
     [T_NEW]),
    ("B2", "over", "⛔⛔ EVERY bridged logger is excluded, so `auth`, `vision`, "
     "`selfheal`, `narrate` and the bidi listener notice all vanish from run "
     "folders — undoing the wave that put them there to explain a dead listener",
     [(_BRIDGE_SCOPE, "            scope = _machine_log_scope()")],
     [T_NEW]),
    ("B3", "over", "the exclusion widens to the vendor logger, so the ONE line "
     "anywhere that says a Firestore listener thread died stops reaching the "
     "run whose Start and Stop just stopped arriving",
     [(_BRIDGED_TUPLE,
       '_MACHINE_ONLY_BRIDGED = ("telemetry", "google")')],
     [T_NEW]),
    ("B4", "under", "matching on the whole logger name lets `telemetry.flush` "
     "walk past the exclusion its parent is subject to",
     [(_BRIDGE_SCOPE,
       "            scope = (_machine_log_scope()\n"
       "                     if record.name in _MACHINE_ONLY_BRIDGED\n"
       "                     else _log_contextlib.nullcontext())")],
     [T_NEW]),

    # ══ the exclusions themselves ═════════════════════════════════════
    ("E1", "under", "⭐⭐ the shared queue-position publisher is unmarked, so all "
     "FOUR of its raw threads write other people's uid, runId and topic into "
     "whichever run happens to be armed",
     [(_MARK_QUEUE, "def _recompute_deferred_queue_positions() -> None:")],
     [T_NEW]),
    ("E2", "under", "⛔⛔ THE CROSS-PERSON ONE: the start listener is unmarked, so "
     "every submission to this device — with its topic and its submitter — lands "
     "in some other person's run folder, which a sharer may then send us",
     [(_MARK_START_LISTENER,
       "    def on_snapshot(_col_snapshot, changes, _read_time):\n"
       "        for change in changes:")],
     [T_NEW]),
    ("E3", "under", "the heartbeat is unmarked — quiet on a healthy machine and "
     "chatty on a failing one, which is exactly the machine that sends bundles",
     [(_MARK_HEARTBEAT, "async def _heartbeat_loop():")],
     [T_NEW]),
    ("E4", "under", "the send-logs builder thread is unmarked, so support codes "
     "and owner uids are written into the run folder of whoever is running",
     [(_MARK_SENDLOGS, "    def _work() -> None:")],
     [T_NEW]),
    ("E5", "under", "the orphan sweep is unmarked — its verdict about OTHER "
     "runs' queue directories lands in this one, which is where it was measured",
     [(_MARK_ORPHAN, "    async def _orphan_sweep_loop():")],
     [T_NEW]),

    # ══ the exception: lines that ARE about the armed run ═════════════
    # ⛔⛔ FOUND BY REVIEWING THE FIX, NOT THE CODE. Marking the start listener is
    # what keeps other people's topics out of a run folder — and the same
    # callback logs why the CURRENTLY RUNNING job is being cancelled. Without the
    # escape hatch the exclusion reintroduced, one function later, the exact harm
    # this wave was reframed to avoid.
    ("H1", "under", "⛔⛔ the escape hatch does nothing, so a cancel of the RUNNING "
     "job is machine business and its folder never says why it stopped",
     [(_ESCAPE_USE, "        log(msg, level)")],
     [T_NEW]),
    ("H2", "over", "the hatch does not restore the scope, so every line after a "
     "cancel in that callback — other people's topics included — lands in "
     "whatever run is armed",
     [(_ESCAPE_SET,
       '    _LOG_SCOPE.set("")\n'
       "    try:\n        yield\n    finally:\n        pass")],
     [T_NEW]),
    ("H3", "under", "the running-job cancel goes back to plain `log`, which the "
     "enclosing machine marking then swallows",
     [(_CANCEL_RUNNING,
       """                    log(f"Cancel: target {target_rid[:8]}… is the running job — requesting stop + scheduling exit{' (owner '+_oc+')' if _oc else ''}", "INFO")""")],
     [T_NEW]),

    # ══ the restraint — every one of these silences a run's own story ══
    ("X1", "over", "⛔⛔ the Firestore reconnect loop is excluded. An outage is "
     "WHY a run's commands stopped arriving, and its folder would no longer say "
     "so — the exact silence this capture exists to prevent",
     [(_RECONNECT, "@_machine_logged\nasync def _firebase_reconnect_loop():")],
     [T_NEW]),
    ("X2", "over", "⛔⛔ the job worker is excluded, taking the WATCHDOG's verdict "
     "about this very run out of this very run's folder",
     [(_JOB_WORKER, "    @_machine_logged\n    async def _job_worker():")],
     [T_NEW]),
    ("X3", "over", "⛔⛔ the PER-RUN command listener is excluded, so every "
     "`Command received: STOP`, the child-process reap and the exit line leave "
     "the run folder — and for one measured run those three lines are the ONLY "
     "record of how it ended",
     [(_PER_RUN_CMD_CB,
       "    @_machine_logged\n"
       "    def on_snapshot(_col_snapshot, changes, _read_time):\n"
       "        # Firestore delivers all pre-existing docs as ADDED in the FIRST")],
     [T_NEW]),
    # ⚠ A mutant for "the ratchet keys on the bare name" was written and REMOVED:
    # it edits the TEST file, and this harness mutates research.py only. It would
    # also have been redundant — a name-blind ratchet is precisely what let X3
    # survive its first run, so X3 measures that property already.
    ("X3b", "over", "⛔⛔ the DEVICE-command listener is excluded — the tempting "
     "one, because it sits beside the send-logs thread that IS marked. But "
     "`hard_reset` cancels the active run, so this deletes the only account of "
     "why that run stopped",
     [(_DEVICE_CMD_CB,
       "    @_machine_logged\n"
       "    def _on_snap(_col_snapshot, changes, _read_time):")],
     [T_NEW]),
    ("X4", "over", "the write-through's own gate is moved into `log()`, so a "
     "marked loop stops printing to stdout as well — the machine's OWN log loses "
     "the lines the exclusion exists to keep",
     [("    line = f\"[{ts}] [{level}] {msg}\"\n    print(line)",
       "    line = f\"[{ts}] [{level}] {msg}\"\n"
       "    if _LOG_SCOPE.get() == _LOG_SCOPE_MACHINE:\n        return\n"
       "    print(line)")],
     [T_NEW]),
]


def green(tests: list[str]) -> tuple[bool, bool]:
    try:
        # ⛔⛔ A stale `__pycache__/*.pyc` served OLD bytecode for three rounds of
        # measurement in this repo. In a harness that rewrites the source between
        # runs it is a kill or a survivor invented out of nothing.
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
        print(f"{'TIMED OUT' if timed_out else 'RED'}. "
              f"Nothing below would mean anything.")
        return 2
    print("green", flush=True)

    survivors: list[tuple] = []
    stale: list[tuple] = []
    for mid, direction, why, edits, tests in MUTANTS:
        target = ROOT / SRC
        original = target.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise ValueError(f"replacement equals anchor — mutates nothing: {frm[:60]}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise ValueError(f"anchor occurs {hits}x (needs exactly 1): {frm[:60]}")
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
