"""Wave 8 step B — the lines a run's folder must NOT collect.

⛔⛔ WHAT THE PLAN ASKED FOR, AND WHY IT IS NOT WHAT WAS BUILT. The wave called
for tagging every line with its run so untagged lines went to the machine log —
on the premise that a machine runs two researches at once and one run's folder
therefore holds another's lines. MEASURED on the five real run folders on this
machine (1,821 well-formed lines): not one foreign researchId, topic, submitter
or queue line. `_job_worker` awaits ONE pipeline at a time and every worker is a
separate PROCESS, so two runs cannot share a sink stack at all.

⛔ And the tagging design would have cost two things it could not afford:
  • The per-run Firestore command listener runs on a thread the google SDK
    creates, which no context can reach. Every `Command received: STOP`, the
    child-process reap and the exit line would have left the folder — 25 lines
    across the five folders, and for one of them the ONLY record of how the run
    ended, since its meta still says "running".
  • `_clear_local_logs` runs on that same kind of thread and reads the global
    sink list to spare live folders. A context-scoped registry would make a
    clear-logs command arriving mid-run delete the folder of the run currently
    writing to it.

⭐ So the default is UNCHANGED — a line from any thread still reaches the armed
run — and what was added is an explicit opt-out for the standing loops whose
lines are the machine's or somebody else's. Measured share of that noise: 400 of
the 1,821 lines, 398 of them one repeated telemetry sentence.

The assertions below are grouped by the failure each prevents. The sharpest are
the ones about what is deliberately NOT excluded: a marking that spread to the
reconnect loop or the device-command listener would silence exactly the lines
that explain why a run died.
"""
import asyncio
import inspect
import json
import logging
from pathlib import Path

import pytest

import research


@pytest.fixture(autouse=True)
def _clean_stack():
    research._RUN_LOG_SINKS.clear()
    research._RUN_LOG_LAST_DIR = None
    yield
    research._RUN_LOG_SINKS.clear()


class _Sink:
    """Minimal stand-in for `_RunLogSink` — records what was written through."""

    def __init__(self):
        self.dir = Path("/tmp/does-not-exist")
        self.lines: "list[str]" = []

    def note_line(self, line, level):
        self.lines.append(line)


def _armed():
    sink = _Sink()
    research._RUN_LOG_SINKS.append(sink)
    return sink


# ══ 1. the effect, measured through the real writer ════════════════════
def test_an_ordinary_line_still_reaches_the_armed_run():
    """⭐ THE ACCEPT-POLARITY PIN, and it comes first on purpose. An exclusion
    that excludes everything ships a feature with no diagnostics at all, and
    every assertion below would still pass."""
    sink = _armed()
    research._log_write_through("[00:00:00] [INFO] hello", "INFO")
    assert sink.lines == ["[00:00:00] [INFO] hello"]


def test_a_line_written_inside_the_machine_scope_does_not():
    sink = _armed()
    with research._machine_log_scope():
        research._log_write_through("[00:00:00] [INFO] machine business", "INFO")
    assert sink.lines == []


def test_the_scope_ends_with_its_block():
    """⛔ A LEAKED SCOPE IS A SILENT, PERMANENT LOSS. The var is reset by TOKEN
    rather than set back to empty, so a nested marking cannot un-mark its
    parent — and neither can a sibling that happened to run first."""
    sink = _armed()
    with research._machine_log_scope():
        with research._machine_log_scope():
            research._log_write_through("inner", "INFO")
        research._log_write_through("still machine", "INFO")
    research._log_write_through("back to the run", "INFO")
    assert sink.lines == ["back to the run"]


def test_the_scope_does_not_reach_the_terminal():
    """The machine log IS stdout — the exclusion is about the run folder only.
    If it silenced `print` too, a marked loop would go dark everywhere and the
    machine's own log would lose the lines this scope exists to keep."""
    src = inspect.getsource(research.log)
    assert "print(line)" in src
    assert "_LOG_SCOPE" not in src, (
        "the scope belongs in the write-through, not in log() — putting it here "
        "would drop the line from backend.log as well")


def test_the_exclusion_is_checked_before_the_sink_is_even_looked_up():
    """Not a behaviour so much as a cost note: the marked loops are the chatty
    ones, so the cheap comparison goes first."""
    from conftest import code_only
    src = code_only(research._log_write_through)
    assert src.index("_LOG_SCOPE.get()") < src.index("_RUN_LOG_SINKS")


# ══ 2. the propagation rules the design depends on ═════════════════════
def test_the_scope_follows_an_await_and_a_thread_hop():
    """⭐ THIS IS WHY IT IS A CONTEXT AND NOT A PARAMETER. A marked loop that
    awaits a helper, or hands blocking work to `asyncio.to_thread`, must not
    have its lines reappear in a run folder two frames down."""
    sink = _armed()

    async def _deep():
        research._log_write_through("from an awaited helper", "INFO")

    def _blocking():
        research._log_write_through("from a to_thread hop", "INFO")

    async def _main():
        with research._machine_log_scope():
            await _deep()
            await asyncio.to_thread(_blocking)

    asyncio.run(_main())
    assert sink.lines == []


def test_a_raw_thread_does_NOT_inherit_it():
    """⛔⛔ AND THAT IS THE CORRECT DEFAULT, not an oversight. A raw thread the
    PIPELINE spawns — title refresh, the phase notifier, the summary writer — is
    doing the run's work, and its line is the run's only account of a
    fire-and-forget handoff. Inheriting here would have deleted those.

    The consequence is that a machine-concern raw thread needs its own marking,
    which is exactly why the queue-position publisher is marked at the FUNCTION
    all four of its spawn sites share."""
    import threading

    sink = _armed()
    done = threading.Event()

    def _body():
        research._log_write_through("from a raw thread", "INFO")
        done.set()

    with research._machine_log_scope():
        threading.Thread(target=_body, daemon=True).start()
        done.wait(timeout=5)
    assert sink.lines == ["from a raw thread"]


# ══ 3. the decorator ═══════════════════════════════════════════════════
def test_the_decorator_marks_a_sync_function():
    sink = _armed()

    @research._machine_logged
    def _f():
        research._log_write_through("sync", "INFO")
        return 42

    assert _f() == 42
    assert sink.lines == []
    research._log_write_through("after", "INFO")
    assert sink.lines == ["after"]


def test_the_decorator_marks_an_async_function_and_stays_a_coroutine():
    """⛔ A decorator that quietly turned a coroutine function into a plain one
    would break every `create_task` call site — and `iscoroutinefunction` is the
    thing those sites are chosen by."""
    sink = _armed()

    @research._machine_logged
    async def _f():
        research._log_write_through("async", "INFO")
        return 7

    assert inspect.iscoroutinefunction(_f)
    assert asyncio.run(_f()) == 7
    assert sink.lines == []


def test_the_decorator_keeps_the_name_it_wrapped():
    """The loops are found in logs and tracebacks by name; a wrapper that
    renamed them all to `_async_scoped` would make every stack unreadable."""
    @research._machine_logged
    async def _some_named_loop():
        return None

    assert _some_named_loop.__name__ == "_some_named_loop"


def test_the_scope_is_released_even_when_the_body_raises():
    sink = _armed()

    @research._machine_logged
    def _boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        _boom()
    research._log_write_through("after the raise", "INFO")
    assert sink.lines == ["after the raise"]


# ══ 4. the bridged loggers ═════════════════════════════════════════════
def test_the_telemetry_flood_stops_reaching_the_run(caplog):
    """⭐⭐ THE MEASURED ONE. 398 of one folder's 911 lines were this sentence,
    emitted once per flush tick by a thread with nothing to do with the run."""
    sink = _armed()
    handler = research._StdlibLogBridge()
    rec = logging.LogRecord("telemetry", logging.DEBUG, __file__, 1,
                            "telemetry: no id-token accessor", None, None)
    handler.emit(rec)
    assert sink.lines == []


def test_the_other_bridged_loggers_still_reach_the_run():
    """⛔ THE HALF THAT MATTERS MORE. `auth`, `vision`, `selfheal` and `narrate`
    are things a RUN does, and `google.api_core.bidi` is bridged for the express
    purpose of letting a bundle explain a listener that died mid-run. A tuple
    that grew would undo the wave that put them there."""
    sink = _armed()
    handler = research._StdlibLogBridge()
    for name in ("auth", "vision", "selfheal", "narrate", "google.api_core.bidi"):
        handler.emit(logging.LogRecord(name, logging.WARNING, __file__, 1,
                                       f"{name} said something", None, None))
    assert len(sink.lines) == 5, sink.lines
    assert research._MACHINE_ONLY_BRIDGED == ("telemetry",)


def test_a_dotted_child_logger_is_matched_by_its_root():
    """`telemetry.flush` is telemetry. Matching the whole name would let a child
    logger walk straight past the exclusion."""
    sink = _armed()
    research._StdlibLogBridge().emit(
        logging.LogRecord("telemetry.flush", logging.DEBUG, __file__, 1,
                          "child", None, None))
    assert sink.lines == []


def test_a_multi_line_bridged_record_is_excluded_as_a_whole():
    """The bridge splits a traceback into one `log()` call per line; the scope
    has to cover the loop, not one call inside it."""
    sink = _armed()
    research._StdlibLogBridge().emit(
        logging.LogRecord("telemetry", logging.ERROR, __file__, 1,
                          "line one\nline two\nline three", None, None))
    assert sink.lines == []


# ══ 5. the set of exclusions IS the policy ═════════════════════════════
_EXPECTED_MARKED = {
    "_recompute_deferred_queue_positions",
    "_heartbeat_loop",
    "_handle_send_logs_command._work",
    "start_firestore_start_listener.on_snapshot",
    "run_server._orphan_sweep_loop",
    "run_server._dead_worker_reconcile_loop",
    "run_server._aegis_pulse_loop",
    "run_server._idle_rescan_loop",
}

# ⛔⛔ THE MORE IMPORTANT LIST. Each of these logs while a run is armed and each
# explains that run's fate; marking any of them would produce a folder that says
# nothing about why its run ended, which is the failure the whole capture exists
# to prevent.
_MUST_NOT_BE_MARKED = {
    "_firebase_reconnect_loop",              # an outage is why commands stopped
    "_revoked_recovery_loop",                # a revoke is why writes failed
    "run_server._job_worker",                # the watchdog's verdict on THIS run
    "_start_command_listener.on_snapshot",   # every `Command received: STOP`
    "_start_device_command_listener._on_snap",  # a hard reset is why a run died
    "run_pipeline",
    "run_pipeline_captured",
    "log",
    "_log_write_through",
}


def _marked_function_names() -> "set[str]":
    """Every function carrying `@_machine_logged`, QUALIFIED by its enclosing
    functions, read from the source tree.

    ⭐ AST, not a grep: a decorator named in a comment, a docstring or a string
    literal must not count as a marking, and this file's own module docstring
    mentions the name.

    ⛔⛔ QUALIFIED, AND MUTATION IS WHY. The first version keyed on the bare
    function name and a mutant that marked the PER-RUN command listener SURVIVED
    — because that callback is also called `on_snapshot`, so the set was
    unchanged and the ratchet saw nothing. Two closures sharing a name is normal
    in this file; a policy keyed on the name is not a policy."""
    import ast
    tree = ast.parse(Path(research.__file__).read_text(encoding="utf-8"))
    out: "set[str]" = set()

    def walk(node, chain):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = chain + [child.name]
                if any(isinstance(d, ast.Name) and d.id == "_machine_logged"
                       for d in child.decorator_list):
                    out.add(".".join(qualified))
                walk(child, qualified)
            else:
                walk(child, chain)

    walk(tree, [])
    return out


def test_exactly_these_functions_are_excluded():
    """⛔ A RATCHET ON THE POLICY. Every marking silences lines in a support
    bundle, which is a change nobody sees until a bundle is missing the answer.
    Adding one has to be a deliberate edit here, with its reason written down."""
    assert _marked_function_names() == _EXPECTED_MARKED


def test_the_paths_that_explain_a_run_are_never_excluded():
    assert _marked_function_names() & _MUST_NOT_BE_MARKED == set()


def test_a_line_about_the_armed_run_escapes_a_machine_scope():
    """⛔⛔ THE EXCEPTION THE START LISTENER NEEDS. Marking that callback is what
    keeps other people's topics out of a run folder — but the SAME callback
    handles `cancel`, and four of its branches log the reason the currently
    RUNNING job is being stopped. Without this seam the exclusion would have
    taken those lines out of the folder of the run they explain, which is the
    exact harm the reframe of this wave was written to avoid."""
    sink = _armed()
    with research._machine_log_scope():
        research.log("machine business")
        research._log_about_the_armed_run("Cancel: target … is the running job")
        research.log("machine business again")
    # `log()` formats before it writes through, so the sink holds whole lines.
    # A `[date]` marker may ride along on the first line of a new day.
    kept = [ln for ln in sink.lines if research.LOG_DATE_PREFIX not in ln]
    assert len(kept) == 1, kept
    assert "Cancel: target … is the running job" in kept[0]
    assert not any("machine business" in ln for ln in sink.lines)


def test_the_escape_hatch_puts_the_scope_back():
    """⛔ It is an EXCEPTION, not an exit. If it left the block unmarked, every
    line after it in a marked loop would land in the run folder."""
    sink = _armed()
    with research._machine_log_scope():
        research._log_about_the_armed_run("about the run")
        research.log("after the exception")
    kept = [ln for ln in sink.lines if research.LOG_DATE_PREFIX not in ln]
    assert len(kept) == 1, kept
    assert "about the run" in kept[0]
    assert not any("after the exception" in ln for ln in sink.lines)


def test_every_cancel_of_a_running_job_uses_the_escape_hatch():
    """The four branches that name the running or gate-pending job. A fifth
    `Cancel:` line about a QUEUED run is correctly machine business — it is not
    about anything armed — so this counts the branches, not the word."""
    from conftest import code_only
    src = code_only(research.start_firestore_start_listener)
    assert src.count("_log_about_the_armed_run(") == 4, (
        "expected exactly the four cancel branches that stop a live run")
    for phrase in ("is the running job", "is in gate wait",
                   "moved to gate wait", "popped to current_job"):
        idx = src.index(phrase)
        head = src.rfind("\n", 0, src.rfind("(", 0, idx))
        assert "_log_about_the_armed_run" in src[head:idx], (
            f"the {phrase!r} branch still logs as machine business")


def test_the_two_command_listeners_are_not_excluded():
    """⛔⛔ THE TWO TEMPTING ONES, and the reason the ratchet above is qualified.

    The PER-RUN command listener carries every `Command received: STOP`, the
    child-process reap and the exit line — for one run measured on this machine
    those three lines are the ONLY record of how it ended, because its meta still
    says "running". The DEVICE command listener carries `hard_reset`, which
    cancels the active run, so it is that run's only account of why it stopped.

    ⛔ An earlier version of this test asserted against
    `_start_device_command_listener`'s source and would have passed forever: the
    callback a mutant marks lives in `_start_command_listener`, a different
    function, so the assertion was looking at a file region the mutation never
    touched. A guard that cannot fire."""
    marked = _marked_function_names()
    assert "_start_command_listener.on_snapshot" not in marked, (
        "the per-run command listener carries every STOP a bundle can report")
    assert "_start_device_command_listener._on_snap" not in marked, (
        "a hard reset is why the active run died — that belongs in its folder")
    # …and the one that IS marked is the START listener's same-named twin.
    assert "start_firestore_start_listener.on_snapshot" in marked


def test_the_queue_publisher_is_marked_at_the_function_not_the_spawn_sites(monkeypatch):
    """⭐⭐ Four raw threads share one target. A marking repeated at four call
    sites is a marking that will be at three of them after the next edit.

    ⛔ ASSERTED BY CALLING IT. The first version of this test checked that the
    function's own source mentioned its own name — which it does, in its
    docstring — and would have passed with the decorator removed. Marked-ness is
    a behaviour: drive the real function with a real armed sink and see whether
    the line lands."""
    from conftest import code_only
    server = code_only(research.run_server)
    listener = code_only(research.start_firestore_start_listener)
    spawns = (server + listener).count("target=_recompute_deferred_queue_positions")
    assert spawns >= 3, "expected the shared publisher to have several spawn sites"

    sink = _armed()
    # The publisher's first act inside the lock is to log if Firestore is down;
    # force that branch so the function emits without touching the network.
    monkeypatch.setattr(research, "_firebase_db", None)
    monkeypatch.setattr(
        research, "_recompute_deferred_queue_positions_locked",
        lambda: research.log("[queue-pos] a line about somebody else's run"))
    research._recompute_deferred_queue_positions()
    assert sink.lines == [], (
        "the shared publisher's line reached an armed run folder — the marking "
        "is on a spawn site rather than on the function")
