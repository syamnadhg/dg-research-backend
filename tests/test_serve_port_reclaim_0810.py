"""A busy port must be resolved, or explained. Never "binding anyway".

WHAT HAPPENED (2026-08-10)

Closing a terminal tab does not stop this backend. It loses its terminal,
reparents to init, and keeps the socket. The next `--serve` then could not bind,
and said so only through uvicorn's raw "[Errno 48] error while attempting to
bind" buried in the boot output — after a pre-bind probe that had ALREADY
noticed, logged "looks busy — binding anyway", and let the failure happen.

The operator's reasonable reading was that serve had shut itself down. The cure
— find and kill an invisible process with no terminal — was neither suggested
nor discoverable. It cost most of an afternoon across three separate boots, and
the second and third were the same person making the same correct assumption
about a machine that was telling them nothing.

Two properties matter here and they pull against each other:

  * a stale copy of OURSELVES should just be cleared, because the user should
    not have to know that a process outlived its window;
  * anything we cannot identify as ours must NEVER be touched. Taking a port
    from someone else's process is not ours to do, and "it was on my port" is
    not a justification anybody would accept afterwards.

The tests for the second property are the ones worth having.
"""
import ast
import re
import signal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research as R  # noqa: E402

RESEARCH = Path(__file__).resolve().parents[1] / "research.py"
SRC = RESEARCH.read_text(encoding="utf-8")


def _src_of(name: str) -> str:
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SRC, node) or ""
    raise AssertionError(f"{name} not found")


# ── which processes count as OURS ───────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "/usr/bin/python3 -u research.py --serve",
    "/opt/homebrew/bin/python3.13 -u research.py --serve --verbose",
    "/Users/x/.local/pipx/venvs/superresearch/bin/python -m superresearch --serve",
    "superresearch --serve",
    # ⭐ The REAL argv on macOS: the framework interpreter's basename is
    # "Python", capital P. A case-sensitive check read our own backend as a
    # stranger and refused to reclaim its own port.
    "/opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/"
    "Versions/3.14/Resources/Python.app/Contents/MacOS/Python -u research.py --serve",
])
def test_our_own_backend_is_recognised(cmd):
    assert R._looks_like_our_backend(cmd) is True, cmd


@pytest.mark.parametrize("cmd", [
    "",
    "python3 -m http.server 8000",
    "node server.js --serve",                 # --serve, but not ours
    "/usr/bin/python3 manage.py runserver",
    "docker-proxy -container-port 8000",
    "/usr/bin/python3 -u research.py --pair",  # ours, but NOT the serve command
    "grep --serve research.py",
])
def test_everything_else_is_NOT_ours(cmd):
    """The load-bearing half. Every false positive here is somebody's process
    being killed because it happened to be on port 8000."""
    assert R._looks_like_our_backend(cmd) is False, cmd


def test_argv_is_accepted_as_a_list_not_only_a_joined_string():
    """`psutil` hands back argv. Joining it first loses the token boundaries the
    moment any path contains a space — and this decides whether we signal."""
    assert R._looks_like_our_backend(
        ["/usr/bin/python3", "-u", "research.py", "--serve"]) is True
    assert R._looks_like_our_backend(
        ["/Applications/My App/bin/node", "server.js", "--serve"]) is False


def test_recognition_needs_BOTH_the_program_and_the_serve_flag():
    """`--serve` alone is a flag half the world uses, and `research.py` alone is
    also `--pair`, `--unpair` and `--doctor`. Only the pair identifies a backend
    that is actually holding a port."""
    assert R._looks_like_our_backend("node app.js --serve") is False
    assert R._looks_like_our_backend("python research.py --doctor") is False
    assert R._looks_like_our_backend("python research.py --serve") is True


# ── the four outcomes ───────────────────────────────────────────────────────

def _fake(monkeypatch, *, free_after=0, holders=(), activity=None):
    """Drive `_reclaim_port` without a real socket or real processes.

    `free_after` — how many probe calls until the port reads free (0 = already).
    `activity`   — what the holder reports it is doing; None means idle.
    Signals are recorded, never sent: a test that actually kills things is a test
    nobody dares run.

    ⛔ 2026-08-17 — THE ACTIVITY PROBE WAS NEVER FAKED, and these tests were
    quietly reading the developer's own machine. `_reclaim_port` asks the holder
    what it is doing over real HTTP on the real port, so with an actual serve up
    on 8000 the reclaim correctly answered "busy" and two tests failed — during a
    live end-to-end, which is exactly when a full suite gets run and exactly when
    a false failure is most expensive. They had only ever passed because port 8000
    happened to be free.

    ⭐ It also hid a coverage hole: "ours, but WORKING, so refuse" is the branch
    the code's own comment says was a reported bug (a second `--serve` ending a
    run that was mid-flight), and nothing exercised it. See the busy test below.
    """
    state = {"probes": 0, "signalled": []}

    def _probe(port, wait=0.0):
        state["probes"] += 1
        return state["probes"] > free_after

    monkeypatch.setattr(R, "_wait_for_port_free", _probe)
    monkeypatch.setattr(R, "_port_holders", lambda port: list(holders))
    monkeypatch.setattr(R, "_probe_backend_activity_until_settled",
                        lambda port, settle_s=0.0: activity)
    monkeypatch.setattr(R.os, "kill", lambda pid, sig: state["signalled"].append((pid, sig)))
    return state


def _ours(pid=4242):
    return {"pid": pid, "name": "python", "cmd": "python research.py --serve", "ours": True}


def _theirs(pid=777):
    return {"pid": pid, "name": "node", "cmd": "node server.js", "ours": False}


def test_a_free_port_is_left_alone(monkeypatch):
    st = _fake(monkeypatch, free_after=0)
    assert R._reclaim_port(8000)[0] == "free"
    assert st["signalled"] == [], "nothing to stop, so nothing may be signalled"


def test_a_stale_copy_of_ours_is_stopped_and_the_port_reclaimed(monkeypatch):
    """The case that cost the afternoon."""
    st = _fake(monkeypatch, free_after=1, holders=[_ours(4242)])
    state, holders = R._reclaim_port(8000)
    assert state == "reclaimed"
    assert [p for p, _ in st["signalled"]] == [4242]
    assert holders[0]["pid"] == 4242


def test_a_FOREIGN_holder_is_refused_and_NEVER_signalled(monkeypatch):
    """⛔ THE invariant. A false positive here kills somebody's work because it
    was on our port. Refusing costs one clear error message; being wrong costs
    them whatever they were running."""
    st = _fake(monkeypatch, free_after=99, holders=[_theirs(777)])
    state, holders = R._reclaim_port(8000)
    assert state == "foreign"
    assert st["signalled"] == [], "a process that is not ours must never be signalled"
    assert holders[0]["pid"] == 777


def test_a_MIXED_set_is_refused_whole_and_nothing_is_signalled(monkeypatch):
    """If anything on the port is not ours, the whole thing is refused. Stopping
    "just our half" leaves the port held anyway and has killed a process for no
    gain — the worst of both outcomes."""
    st = _fake(monkeypatch, free_after=99, holders=[_ours(4242), _theirs(777)])
    state, _ = R._reclaim_port(8000)
    assert state == "foreign"
    assert st["signalled"] == []


def test_ours_but_WORKING_is_refused_and_never_signalled(monkeypatch):
    """⛔⛔ The branch nothing covered until 2026-08-17, and the one the source
    says was a reported bug: every holder matching by name was signalled with no
    test of whether it was doing anything, so a second `--serve` — the command
    this product's own "Start it yourself" hint prints — ended a run that was
    mid-flight and took its partial output with it.

    It went uncovered because the activity probe was never faked: these tests read
    the real port, so this branch only ever fired by accident, on a machine that
    happened to have a live serve. Then it fired in the two tests that did NOT
    want it, and in neither case did anything assert this behaviour.
    """
    st = _fake(monkeypatch, free_after=99, holders=[_ours(4242)],
               activity={"running": True, "pending": 0})
    state, holders = R._reclaim_port(8000)

    assert state == "busy"
    assert st["signalled"] == [], "a backend that is WORKING must never be signalled"
    assert holders[0]["pid"] == 4242


def test_a_working_holder_is_recognised_by_QUEUED_work_too(monkeypatch):
    """Not just a live run — a backend with jobs waiting is also working, and
    stopping it loses the queue."""
    st = _fake(monkeypatch, free_after=99, holders=[_ours(4242)],
               activity={"running": False, "pending": 3})
    state, _ = R._reclaim_port(8000)
    assert state == "busy"
    assert st["signalled"] == []


def test_an_IDLE_holder_is_still_reclaimed(monkeypatch):
    """The polarity check for the two above. A holder that answers and says it is
    doing nothing is the terminal-less orphan this feature exists to clear —
    refusing there would delete the feature while reading like a safety fix."""
    st = _fake(monkeypatch, free_after=1, holders=[_ours(4242)],
               activity={"running": False, "pending": 0})
    state, _ = R._reclaim_port(8000)
    assert state == "reclaimed"
    assert [p for p, _ in st["signalled"]] == [4242]


def test_ours_but_immovable_is_reported_stuck_not_silently_ignored(monkeypatch):
    """A stop that neither works nor says so is the original bug wearing a new
    hat. It must escalate, and then admit it lost."""
    st = _fake(monkeypatch, free_after=99, holders=[_ours(4242)])
    state, _ = R._reclaim_port(8000)
    assert state == "stuck"
    sigs = [s for _, s in st["signalled"]]
    assert len(sigs) == 2, f"expected a stop then a forced stop, got {sigs}"
    if hasattr(signal, "SIGKILL"):
        assert sigs[0] != sigs[1], "escalation must be a different signal, not a repeat"
    else:
        # ⛔ WINDOWS. There is no signal harder than the first one: os.kill()
        # maps everything except CTRL_*_EVENT onto TerminateProcess, so the
        # forced stop IS SIGTERM again and "a different signal" cannot exist.
        # What still must hold -- and what actually broke -- is that a SECOND,
        # deliberate attempt happens at all. Naming _sig.SIGKILL raised
        # AttributeError into a blanket except, so the escalation loop sent
        # NOTHING while logging that it was escalating.
        assert sigs[1] == signal.SIGTERM, (
            f"the forced stop must still be sent on a platform with no "
            f"SIGKILL, got {sigs}")


def test_an_unidentifiable_holder_is_waited_out_not_killed(monkeypatch):
    """A socket in TIME_WAIT after a hard kill has no owning process. There is no
    pid to signal, and guessing at one is how the foreign case gets violated."""
    st = _fake(monkeypatch, free_after=1, holders=[])
    state, _ = R._reclaim_port(8000)
    assert state == "free"
    assert st["signalled"] == []


def test_an_unidentifiable_holder_that_never_clears_is_stuck(monkeypatch):
    st = _fake(monkeypatch, free_after=99, holders=[])
    assert R._reclaim_port(8000)[0] == "stuck"


# ── the boot path acts on the answer ────────────────────────────────────────

def test_boot_no_longer_binds_anyway():
    """The exact string of the old behaviour. It knew the port was busy and
    proceeded to fail confusingly."""
    assert "binding anyway" not in SRC


def test_boot_refuses_on_a_foreign_holder():
    server = _src_of("run_server")
    assert '_port_state == "foreign"' in server
    at = server.index('_port_state == "foreign"')
    assert "SystemExit(3)" in server[at:at + 900]


def test_boot_refuses_when_the_port_stays_stuck():
    server = _src_of("run_server")
    assert '_port_state == "stuck"' in server
    at = server.index('_port_state == "stuck"')
    assert "SystemExit(3)" in server[at:at + 900]


def test_the_refusal_names_the_holder():
    """"Port in use" without a pid leaves the operator exactly where they were —
    hunting an invisible process. The pid IS the fix."""
    server = _src_of("run_server")
    assert "h['pid']" in server or 'h["pid"]' in server


def test_the_refusal_tells_them_how_to_look():
    server = _src_of("run_server")
    assert "lsof" in server, "give the command, not just the diagnosis"


def test_a_port_check_that_itself_fails_does_not_block_boot():
    """psutil and lsof are both allowed to be missing or refused. A convenience
    that can prevent the backend from starting is not a convenience."""
    server = _src_of("run_server")
    at = server.index("_reclaim_port")
    window = server[at - 200:at + 400]
    assert "except Exception" in window
    assert '"free", []' in window, "a failed check must fall through to binding"


def test_the_reclaim_runs_off_the_event_loop():
    """It sleeps for up to two settle windows. On the loop that stalls every
    heartbeat and listener the server has already started."""
    server = _src_of("run_server")
    assert "asyncio.to_thread(_reclaim_port" in server


# ── the helper's own robustness ─────────────────────────────────────────────

def test_the_signal_module_is_imported_where_it_is_used():
    """It is not module-level in research.py. Missing it failed as a swallowed
    NameError — the stale backend was never signalled, and the reclaim reported
    "stuck" while the real cause was a typo-grade omission."""
    body = _src_of("_reclaim_port")
    assert "import signal as _sig" in body
    assert not re.search(r"[^_]signal\.SIG", body), "must use the local alias"


def test_holder_lookup_survives_both_sources_failing():
    """psutil raises AccessDenied on macOS without root; lsof is absent on many
    Linux images. Neither may take the boot down."""
    body = _src_of("_port_holders")
    assert body.count("except Exception") >= 2


def test_a_process_that_vanishes_mid_stop_is_not_an_error():
    """It exiting on its own is the outcome we wanted."""
    body = _src_of("_reclaim_port")
    assert "ProcessLookupError" in body


def test_we_never_signal_ourselves():
    """The current process is listening on that port by the time this matters in
    some restart paths; signalling it would be the backend killing itself during
    boot."""
    body = _src_of("_port_holders")
    assert "getpid" in body and "== me" in body
