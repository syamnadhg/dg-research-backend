"""A probe that could not run is not a port that is free.

WHAT WAS WRONG (wave 9, 2026-09-16)

`_free_port` — the blunt clear-the-port helper on the install and crash-respawn
paths — ran `lsof -ti :<port>` as its ONLY POSIX probe, inside a bare
`except Exception: return []`. Plenty of Linux images ship without lsof. On one
of those the function reclaimed nothing and said nothing, because `[]` was the
same value it returns for a genuinely free port.

Three callers finished that sentence, each in the kinder direction:

  * the multi-worker supervisor had ALREADY proved the port was occupied, logged
    "freed nothing", and respawned into the identical EADDRINUSE — forever, since
    a port conflict is deliberately exempt from the crash tracker;
  * the installer printed its "Cleared port 8000" line only on success, so a
    probe that never ran left no line at all;
  * `--doctor` reported "Port 8000 not bound — API unreachable" about a port it
    had never managed to look at. The handler written for "could not look" sat
    one call away and could not fire, because `_port_holders` swallowed every
    exception and returned `[]` too.

And the two lsof invocations were not the same query. `_port_holders` asked
`lsof -nP -iTCP:<port> -sTCP:LISTEN -t` — listeners only. `_free_port` asked
`lsof -ti :<port>`, which matches any socket whose LOCAL **or REMOTE** port is
that number, with no LISTEN filter: it would force-kill a process that merely
held an outbound connection to somebody else's port 8000.

WHAT THESE TESTS PIN

Every one of them drives the real functions with the real probes made to fail,
because the happy path was never the bug. The shape that matters throughout is a
COMPARISON: the same call, once with a probe that could not run and once with a
probe that ran and found nothing, must not give the same answer. An hour ago
both gave `[]`.

⛔ The kill policy is deliberately NOT changed here — see
`test_the_blunt_path_still_kills_what_it_finds`.
"""
import ast
import subprocess
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


# ── the two worlds every test below compares ────────────────────────────────

class _Conn:
    """One row of psutil.net_connections, shaped as psutil shapes it."""

    def __init__(self, pid, port, status="LISTEN"):
        self.pid = pid
        self.status = status
        self.laddr = type("addr", (), {"port": port})()


class _FakePsutil:
    CONN_LISTEN = "LISTEN"

    def __init__(self, conns=()):
        self._conns = list(conns)

    def net_connections(self, kind="inet"):
        return list(self._conns)

    def Process(self, pid):  # noqa: N802 — psutil's own casing
        raise RuntimeError("not inspectable")


def _no_psutil(monkeypatch):
    """Make `import psutil` fail the way a source checkout without it fails."""
    monkeypatch.setitem(sys.modules, "psutil", None)


def _psutil_seeing(monkeypatch, *conns):
    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil(conns))


def _no_shell_tool(monkeypatch, exc=FileNotFoundError("lsof")):
    """Make the shell fallback fail the way a missing binary fails."""
    calls = []

    def _run(cmd, *a, **kw):
        calls.append(list(cmd))
        raise exc

    monkeypatch.setattr(subprocess, "run", _run)
    return calls


def _shell_tool_finding(monkeypatch, stdout):
    calls = []

    def _run(cmd, *a, **kw):
        calls.append(list(cmd))
        return type("r", (), {"stdout": stdout, "returncode": 0})()

    monkeypatch.setattr(subprocess, "run", _run)
    return calls


@pytest.fixture(autouse=True)
def _never_actually_kill(monkeypatch):
    """⛔ `_free_port` force-kills. Nothing in this file may reach a real signal."""
    killed = []
    monkeypatch.setattr(R, "_kill_pids", lambda pids: killed.append(list(pids)) or len(pids))
    monkeypatch.setattr(R, "_supervisor_platform", lambda: "Linux")
    return killed


# ── _listening_pids: the one probe ──────────────────────────────────────────

def test_a_probe_that_could_not_run_raises_instead_of_answering_empty(monkeypatch):
    """⛔⛔ THE DEFECT. Both sources gone is not "nothing is listening", and the
    only way a caller can act on the difference is if it is not spelled `[]`."""
    _no_psutil(monkeypatch)
    _no_shell_tool(monkeypatch)
    with pytest.raises(R._PortProbeUnavailable):
        R._listening_pids(8000)


def test_a_probe_that_ran_and_found_nothing_is_a_real_empty(monkeypatch):
    """The control for the test above. Without this pair, "raises on failure"
    could be satisfied by a function that raises whenever it finds nothing."""
    _psutil_seeing(monkeypatch)                      # psutil answers: no listeners
    _shell_tool_finding(monkeypatch, "")             # and the fallback agrees
    assert R._listening_pids(8000) == set()


def test_psutil_answering_survives_a_missing_shell_tool(monkeypatch):
    """psutil said the port is free; lsof being absent does not unsay it."""
    _psutil_seeing(monkeypatch)
    _no_shell_tool(monkeypatch)
    assert R._listening_pids(8000) == set()


def test_the_shell_tool_answering_survives_a_missing_psutil(monkeypatch):
    """The lsof-less Linux box's mirror image: a SOURCE checkout with no psutil.
    Every `import psutil` in research.py is function-local and guarded, so this
    is the ordinary case there, not an exotic one."""
    _no_psutil(monkeypatch)
    _shell_tool_finding(monkeypatch, "4242\n")
    assert R._listening_pids(8000) == {4242}


def test_an_unprobeable_platform_is_not_a_free_port(monkeypatch):
    """`_supervisor_platform` answers "Unsupported" for anything that is not
    Windows/Darwin/Linux, and NEITHER shell branch matched it — so the old code
    fell through to `return []` and a platform nobody probed read as free."""
    monkeypatch.setattr(R, "_supervisor_platform", lambda: "Unsupported")
    _no_psutil(monkeypatch)
    with pytest.raises(R._PortProbeUnavailable):
        R._listening_pids(8000)


def test_we_are_never_in_our_own_answer(monkeypatch):
    """In some restart paths this process is the one listening. Reporting it is
    how the backend gets a signal sent to itself during boot."""
    _psutil_seeing(monkeypatch, _Conn(R.os.getpid(), 8000), _Conn(4242, 8000))
    assert R._listening_pids(8000) == {4242}


def test_only_LISTENERS_count(monkeypatch):
    """A socket in another state on the same port is not a holder of it."""
    _psutil_seeing(monkeypatch, _Conn(777, 8000, status="ESTABLISHED"),
                   _Conn(4242, 8000))
    assert R._listening_pids(8000) == {4242}


# ── _free_port: the blunt path ──────────────────────────────────────────────

def test_free_port_tells_the_two_empties_apart(monkeypatch):
    """⛔⛔ THE PIN. The same call, one probe that could not run and one that ran
    and found nothing. An hour ago both were `[]` and no caller could act."""
    _no_psutil(monkeypatch)
    _no_shell_tool(monkeypatch)
    could_not_look = R._free_port(8000)

    _psutil_seeing(monkeypatch)
    _shell_tool_finding(monkeypatch, "")
    really_free = R._free_port(8000)

    assert could_not_look != really_free, (
        "a probe that could not run must not answer the same as a free port")
    assert could_not_look == ([], False)
    assert really_free == ([], True)


def test_the_back_compat_alias_carries_the_same_two_facts(monkeypatch):
    """`_free_port_8000` is what the installer calls. An alias that drops the
    probe flag would put the whole defect back on the path that shows it least."""
    _no_psutil(monkeypatch)
    _no_shell_tool(monkeypatch)
    assert R._free_port_8000() == ([], False)


def test_the_blunt_path_still_kills_what_it_finds(monkeypatch, _never_actually_kill):
    """⛔ THE SCOPE LIMIT, PINNED. `_free_port` shares a probe with
    `_port_holders` but NOT its `ours` flag: this is the install/respawn
    instrument and it clears the port whoever is on it. Routing it through
    `_port_holders` would inherit the ownership refusal for free and silently
    change the kill policy of two paths nobody reviewed for it."""
    _psutil_seeing(monkeypatch, _Conn(777, 8000))   # a total stranger
    pids, probed = R._free_port(8000)
    assert (pids, probed) == ([777], True)
    assert _never_actually_kill == [[777]], "the stranger is still killed"


def test_free_port_no_longer_kills_an_OUTBOUND_connection(monkeypatch):
    """⛔⛔ THE SECOND DEFECT. `lsof -ti :8000` matches any socket whose LOCAL
    **or REMOTE** port is 8000 and applies no LISTEN filter, so this force-killed
    a process that merely held a connection TO somebody else's port 8000. The
    query is now the listener one `_port_holders` always used."""
    _no_psutil(monkeypatch)
    calls = _shell_tool_finding(monkeypatch, "")
    R._free_port(8000)
    assert calls, "the fallback must actually be reached"
    argv = calls[0]
    assert "-sTCP:LISTEN" in argv, (
        f"no LISTEN filter — this kills outbound connections too: {argv}")
    assert "-ti" not in argv, f"the old unfiltered query is back: {argv}"


def test_every_caller_reads_the_probe_flag():
    """⛔ HELPER PINNED, CONSUMER NOT is how this repo loses fixes. A call site
    that still binds `_free_port(...)` to one name has the whole defect back,
    and would read a `(pids, probed)` tuple as permanently truthy."""
    tree = ast.parse(SRC)
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        if call.func.id not in ("_free_port", "_free_port_8000"):
            continue
        sites.append((node.lineno, node.targets))
    assert sites, "no call site found — the AST walk has stopped seeing them"
    for lineno, targets in sites:
        assert len(targets) == 1 and isinstance(targets[0], ast.Tuple), (
            f"research.py:{lineno} binds _free_port to one name again")
        assert len(targets[0].elts) == 2, (
            f"research.py:{lineno} does not unpack (pids, probed)")


def test_the_supervisor_stops_saying_freed_nothing_when_it_could_not_look():
    """The crash-respawn path had ALREADY proved the port was occupied. "freed
    nothing" was never the fact; "nothing here could look" is."""
    body = _src_of("run_daemon_loop")
    at = body.index("_free_port(_w_port)")
    window = body[at:at + 2000]
    assert "if _probed:" in window, "the flag is fetched and not consulted"
    assert "_port_holder_hint(_w_port)" in window, (
        "say how to look, with the tool that exists on THIS platform")


def test_the_installer_says_something_when_it_could_not_check():
    """It printed on success only, so a probe that never ran was invisible — on
    the one path where the very next thing is a daemon-loop that will crash-loop
    on the bind we could not clear."""
    body = _src_of("run_resurrect")
    at = body.index("_free_port_8000()")
    window = body[at:at + 900]
    assert "elif not _port_probed:" in window, (
        "an unprobed port still prints nothing at install time")
    assert "_port_holder_hint(8000)" in window


# ── _port_holders and _reclaim_port: the careful path ───────────────────────

def test_port_holders_tells_the_two_empties_apart(monkeypatch):
    """The same comparison one layer up. `[]` from here is read as "unbound" by
    the doctor's verdict and as "nothing identifiable" by the reclaim — two
    different confident wrong answers from one missing binary."""
    _psutil_seeing(monkeypatch)
    _shell_tool_finding(monkeypatch, "")
    assert R._port_holders(8000) == []

    _no_psutil(monkeypatch)
    _no_shell_tool(monkeypatch)
    with pytest.raises(R._PortProbeUnavailable):
        R._port_holders(8000)


def test_the_doctors_could_not_look_handler_can_finally_fire(monkeypatch):
    """⛔⛔ THAT HANDLER WAS DEAD CODE FOR THE FAILURE IT WAS WRITTEN FOR. The
    doctor wraps `_port_holders(8000)` in `except Exception` and warns "Port 8000
    unknown — could not look". `_port_holders` swallowed everything and returned
    `[]`, so the row said "Port 8000 not bound — API unreachable" about a port it
    never examined: the defect that block's own comment says it exists to
    prevent, restated one layer down. This pins that something now arrives."""
    _no_psutil(monkeypatch)
    _no_shell_tool(monkeypatch)
    with pytest.raises(Exception) as caught:      # the doctor catches Exception
        R._port_holders(8000)
    assert isinstance(caught.value, R._PortProbeUnavailable)
    assert "8000" in str(caught.value), "the message names the port it could not look at"


def test_reclaim_says_unknown_not_stuck_when_nothing_could_look(monkeypatch):
    """⛔⛔ It used to come out "stuck", whose refusal reads "still held after
    stopping the earlier backend". Nothing was stopped. Nothing was even seen."""
    _no_psutil(monkeypatch)
    _no_shell_tool(monkeypatch)
    monkeypatch.setattr(R, "_wait_for_port_free", lambda port, wait=0.0: False)
    state, holders = R._reclaim_port(8000, settle_s=0.0)
    assert state == "unknown", f"a probe that could not run reported {state!r}"
    assert holders == []


def test_a_TIME_WAIT_socket_still_clears_itself_when_the_probe_failed(monkeypatch):
    """The kindness in the old path was real and is kept: a socket left in
    TIME_WAIT clears on its own, and that is true whether or not we could see who
    left it. "unknown" is only for a port that is STILL held after the wait."""
    probes = {"n": 0}

    def _free(port, wait=0.0):
        probes["n"] += 1
        return probes["n"] > 1          # busy on the first look, free on the settle

    _no_psutil(monkeypatch)
    _no_shell_tool(monkeypatch)
    monkeypatch.setattr(R, "_wait_for_port_free", _free)
    assert R._reclaim_port(8000, settle_s=0.0)[0] == "free"


def test_an_identifiable_holder_is_unaffected_by_all_of_this(monkeypatch):
    """The refusal that matters most must not have moved: something that is not
    ours is still named and never signalled."""
    monkeypatch.setattr(R, "_wait_for_port_free", lambda port, wait=0.0: False)
    monkeypatch.setattr(R, "_listening_pids", lambda port: {777})
    monkeypatch.setattr(R, "_looks_like_our_backend", lambda argv: False)
    _psutil_seeing(monkeypatch)
    state, holders = R._reclaim_port(8000, settle_s=0.0)
    assert state == "foreign"
    assert [h["pid"] for h in holders] == [777]


def test_serve_refuses_with_its_own_words_when_it_could_not_look():
    """⛔ POSITION, not just mechanism. A new state that `run_server` has no
    branch for falls straight through and binds anyway — and the one refusal a
    person reads would still be the one that says we stopped something."""
    server = _src_of("run_server")
    assert '_port_state == "unknown"' in server, (
        "the new state has no branch; it falls through to binding")
    at = server.index('_port_state == "unknown"')
    window = server[at:at + 1200]
    assert "_port_holder_hint(port)" in window, "name the tool that exists here"
    assert "SystemExit(3)" in window, "an unclearable port must still refuse the bind"
    assert "still held after stopping" not in window, (
        "the stuck copy claims we stopped something; here we saw nothing")
