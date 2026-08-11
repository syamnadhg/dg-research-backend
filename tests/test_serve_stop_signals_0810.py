"""Ctrl+C must stop the server, say that it did, and never hang.

WHAT HAPPENED (2026-08-10)

The serve banner has always printed "Stop: Ctrl+C", and the code relied entirely
on uvicorn's own handler to make that true. On the owner's machine it was not:
Ctrl+C did nothing, repeatedly, and neither did a direct SIGINT to the process.

The cause was never found, and this suite does not pretend otherwise. What was
established, by measurement, is that the identical build honours a real Ctrl+C
everywhere it can be reproduced — under a controlling tty and without one, with
and without the logging pipeline, on this build and on the one running before it
(both exit 130). So the failure was never the handler being wrong.

What it WAS, every time, is SILENT. Not one line was printed anywhere when the
signal was sent, so there was no way to tell "the signal never arrived" from "it
arrived and something swallowed it". That is the part this fixes and the part
worth testing: a stop path that leaves no evidence cannot be debugged by anyone,
including the next person.

So the contract here is three things — it announces, it uses the ordinary
graceful path, and it cannot hang.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

RESEARCH = Path(__file__).resolve().parents[1] / "research.py"
SRC = RESEARCH.read_text(encoding="utf-8")


def _fn(name: str) -> ast.FunctionDef:
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in research.py")


def _src_of(name: str) -> str:
    node = _fn(name)
    return ast.get_source_segment(SRC, node) or ""


# ── it announces ────────────────────────────────────────────────────────────

def test_the_signal_is_logged_the_moment_it_arrives():
    """THE point of the change. An afternoon went into "did the signal arrive?"
    and nothing in the process could answer it. One line settles it forever."""
    body = _src_of("_arm_stop_signals")
    assert "stop requested" in body, body[:400]


def test_the_log_line_names_which_signal():
    """SIGINT and SIGTERM reach here by different routes — a keystroke through a
    terminal's line discipline, and kill(2). Which one arrived is the first thing
    you need to know, and conflating them is what made this hard to chase."""
    body = _src_of("_arm_stop_signals")
    assert re.search(r"Signals\(signum\)\.name", body), body[:400]
    # Scoped to the ARRIVAL line. `{name}` also appears in the second-press line,
    # so asserting it anywhere in the function passed against a mutant that had
    # stripped it from exactly the line under test.
    assert re.search(r"stop requested \(\{name\}\)", body), body[:600]


def test_the_announcement_comes_BEFORE_the_shutdown_is_started():
    """If the graceful path stalls, a line printed after it would never appear —
    which is exactly the state that produced no evidence."""
    body = _src_of("_arm_stop_signals")
    said = body.index("stop requested")
    flagged = body.index("server.should_exit = True")
    assert said < flagged, "the log must precede setting the exit flag"


# ── it uses the ordinary graceful path ──────────────────────────────────────

def test_it_sets_the_same_flag_uvicorn_would():
    """Not a private shutdown. Setting `should_exit` is precisely what uvicorn's
    own handler does, so the existing drain, lifespan shutdown and cleanup all
    still run — this adds evidence and a backstop, it does not replace anything."""
    assert "server.should_exit = True" in _src_of("_arm_stop_signals")


def test_the_conventional_exit_code_survives():
    """Handling the signal ourselves made the shutdown graceful and the exit code
    0, where uvicorn's handler had produced 130. That is a different statement to
    anything watching — a supervisor keyed on SuccessfulExit reads 0 as "it meant
    to stop". Behaviour nobody asked to change does not change."""
    server = _src_of("run_server")
    # The DEBUG line above it also renders `128 + _sig_n`, so the substring alone
    # survived a mutant that deleted the raise. Assert the statement itself.
    assert re.search(r"raise SystemExit\(128 \+ _sig_n\)", server), (
        "must RAISE 128+signum after a signal stop, not just log it"
    )
    assert "_server_stop_signal" in _src_of("_arm_stop_signals")


def test_the_signal_number_is_recorded_not_just_the_fact_of_it():
    """130 and 143 are different answers. A boolean here would collapse Ctrl+C and
    a supervisor's SIGTERM into one exit code."""
    body = _src_of("_arm_stop_signals")
    assert '_server_stop_signal["n"] = signum' in body


# ── it cannot hang ──────────────────────────────────────────────────────────

def test_a_stalled_graceful_shutdown_is_forced():
    """The failure mode this must never have: a stop that is accepted, logged,
    and then never completes. That is indistinguishable from the original bug."""
    body = _src_of("_arm_stop_signals")
    assert "_STOP_GRACE_S" in body
    assert "forcing exit" in body
    assert "_schedule_server_exit" in body


def test_the_forced_exit_reaps_the_browser_first():
    """`_schedule_server_exit` is the Stop button's path, and it exists because a
    bare os._exit left the patchright driver and Chromium orphaned holding the
    profile lock — so the next worker started against a wedged profile. A forced
    stop must not reintroduce that."""
    helper = _src_of("_schedule_server_exit")
    assert "reap" in helper.lower() or "_reap_child_processes" in helper


def test_a_second_press_does_not_wait():
    """What every user expects the second Ctrl+C to mean, and the escape hatch if
    the grace window is ever too generous."""
    body = _src_of("_arm_stop_signals")
    # The backstop's stand-down check spells the same condition, so an unscoped
    # substring survived a mutant that disabled the handler's own guard. Anchor
    # on the branch that leads to the immediate exit.
    m = re.search(r'if _pressed\["n"\] >= 2:\s*\n\s*log\(', body)
    assert m, body[:900]
    after = body[m.start():m.start() + 400]
    assert "again" in after and "delay_sec=0" in after, after


def test_the_backstop_runs_off_the_signal_handler_thread():
    """Real work inside a signal handler is how you deadlock — it can interrupt
    the interpreter anywhere, including mid-allocation while another thread holds
    the lock it needs. The handler only flips a flag and starts a thread."""
    body = _src_of("_arm_stop_signals")
    assert "daemon=True" in body
    assert "Thread(" in body


def test_the_backstop_stands_down_when_the_graceful_path_wins():
    """Otherwise it force-exits a server that already stopped cleanly, turning a
    tidy shutdown into a killed one every single time."""
    body = _src_of("_arm_stop_signals")
    at = body.index("def _backstop")
    branch = body[at:at + 700]
    assert "force_exit" in branch or '_pressed["n"] >= 2' in branch
    assert "return" in branch


# ── ordering: it must outlive uvicorn's own install ─────────────────────────

def test_the_handlers_are_armed_AFTER_uvicorn_is_serving():
    """uvicorn assigns its handlers when `serve()` begins, so anything installed
    earlier is silently overwritten and this whole file would be decorative.
    Waiting on `server.started` makes the ordering deterministic — a fixed sleep
    would be a race that passes on a fast machine."""
    body = _src_of("_arm_stop_signals")
    assert 'getattr(server, "started", False)' in body
    at = body.index('getattr(server, "started", False)')
    # 2026-08-11: the install moved into `_assert_stop_handlers` so it could be
    # re-run on a timer and, more importantly, CALLED by a test. Anchor on the
    # call, not on the `signal.signal(...)` line that no longer lives here.
    armed = body.index("_assert_stop_handlers(")
    assert at < armed, "the wait must come before the install"


def test_the_wait_for_startup_is_bounded():
    """A server that never reports started must not leave the arming coroutine
    spinning for the life of the process."""
    body = _src_of("_arm_stop_signals")
    assert re.search(r"for _ in range\(\d+\)", body), body[:600]


def test_both_stop_signals_are_armed():
    body = _src_of("_arm_stop_signals")
    assert "_sig.SIGINT" in body and "_sig.SIGTERM" in body


def test_arming_failure_is_survivable():
    """`signal.signal` raises off the main thread. A serve that refuses to start
    because it could not arm a convenience is worse than one you stop with kill.

    2026-08-11: the install moved into `_assert_stop_handlers`, so this reads the
    helper now. The behaviour — including that the failure is a WARN rather than
    the DEBUG whisper that hid it for three attempts — is asserted for real by
    calling the function in test_serve_stop_rearm_0811.py."""
    body = _src_of("_assert_stop_handlers")
    at = body.index("sig_mod.signal(_s, handler)")
    assert "except Exception" in body[at - 100:at + 300]


def test_it_is_actually_wired_into_run_server():
    """The whole thing is inert unless the server starts it."""
    server = _src_of("run_server")
    assert "_arm_stop_signals(server, port)" in server
    # Anchored on the CODE, not the words. A comment 800 lines up quotes
    # "await server.serve()" verbatim, and a plain .index() finds that first —
    # the same trap that has broken a line-number search in this repo before.
    at = server.index("_arm_stop_signals(server, port)")
    serve_at = re.search(r"^\s+await server\.serve\(\)\s*$", server, re.M)
    assert serve_at, "the serve call itself must be findable"
    assert at < serve_at.start(), "must be scheduled before the server loop is awaited"


def test_the_arming_task_is_cleaned_up():
    """A pending task left behind on shutdown logs a 'Task was destroyed but it is
    pending' warning on every single stop."""
    server = _src_of("run_server")
    assert "_stop_arm_task.cancel()" in server


# ── the banner's promise ────────────────────────────────────────────────────

def test_the_banner_still_promises_ctrl_c():
    """Kept deliberately. The promise is now backed by the code above rather than
    by hoping the environment cooperates — if this ever has to become conditional,
    that is a product decision, not a silent edit."""
    assert "Stop:" in SRC and "Ctrl+C" in SRC


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal names")
def test_the_grace_window_is_a_sane_length():
    """Long enough for a real drain, short enough that nobody reaches for kill -9
    and orphans a browser — which is the outcome the reap exists to prevent."""
    m = re.search(r"_STOP_GRACE_S = ([\d.]+)", SRC)
    assert m, "the grace window must be a named constant, not a literal in the loop"
    assert 3.0 <= float(m.group(1)) <= 30.0, m.group(1)
