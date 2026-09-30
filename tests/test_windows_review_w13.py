"""The Windows review of wave 13 (2026-09-30): two defects the Mac could not see.

⛔⛔ 1. MOVE TO QUEUE WAS NEVER OFFERED ON WINDOWS. The machine publishes the
"requeue" capability — and obeys a requeue — only when `_supervisor_is_my_parent()`
says a daemon-loop started this worker. That asked `_enumerate_research_py_procs`,
whose Windows half ran WMIC inside `except Exception: return []`; current
Windows 11 (the owner's 10.0.26200 box) has no WMIC.exe, so the list was always
empty: no chip in the app, every requeue refused as "not supervised" — and the
older users of the same list (`--retire`, `--resurrect`, the daemon-loop's
pre-flight sweep) saw nothing running either. The list now comes from psutil,
then PowerShell's CIM, and WMIC last.

⛔ 1b. A VENV'S LAUNCHER STANDS BETWEEN. On a pipx or venv install the
daemon-loop spawns each worker through `Scripts\\python.exe`, a launcher that
starts the real interpreter with the very same command line — so the worker's
direct parent is the launcher, and the daemon-loop is one step up.

⛔ 2. THE COPY BACKUP'S BRIEF CAME BACK WITH CRLF. Chrome on Windows hands the
clipboard back with CRLF line ends; brief.md is written in text mode, which
makes each CR CR LF, and read back every line gains a blank line — a table's
rows fall apart before the brief reaches the Phase 2 agents.

Sections 1-3 run everywhere (fakes); section 4 runs the real thing on Windows.
"""
import asyncio
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

import research

REPO = Path(__file__).resolve().parent.parent
ON_WINDOWS = sys.platform == "win32"


# ══ 1. where the Windows list comes from ═════════════════════════════════════

class _Proc:
    def __init__(self, pid, name, cmdline):
        self.info = {"pid": pid, "name": name, "cmdline": cmdline}


def _fake_psutil(procs=(), processes=None, me=None):
    """A psutil with `process_iter` over `procs`, and `Process(pid)` answering
    from `processes` (pid → (cmdline, ppid, create_time)); `me` is Process()."""
    processes = dict(processes or {})

    class NoSuchProcess(Exception):
        pass

    class Process:
        def __init__(self, pid=None):
            self.pid = me if pid is None else pid
            if self.pid not in processes:
                raise NoSuchProcess(self.pid)

        def cmdline(self):
            return list(processes[self.pid][0])

        def ppid(self):
            return processes[self.pid][1]

        def create_time(self):
            return processes[self.pid][2]

    return types.SimpleNamespace(process_iter=lambda attrs=None: iter(list(procs)),
                                 Process=Process, NoSuchProcess=NoSuchProcess)


def _no_subprocess(monkeypatch):
    calls = []

    def _run(argv, *a, **k):
        calls.append(argv[0])
        raise AssertionError(f"no program should be run: {argv[0]}")

    monkeypatch.setattr(research.subprocess, "run", _run)
    return calls


def test_the_windows_list_comes_from_psutil_and_runs_no_program(monkeypatch):
    """⛔ psutil answers first: WMIC is not asked (it is gone), nor PowerShell."""
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil([
        _Proc(11, "pythonw.exe", ["C:\\Py\\pythonw.exe", "C:\\sr\\research.py", "--daemon-loop"]),
        _Proc(12, "python.exe", ["C:\\Py\\python.exe", "C:\\sr\\research.py", "--serve",
                                 "--worker-id", "2"]),
        _Proc(13, "Python.EXE", ["C:\\Py\\python.exe", "research.py", "a topic"]),
        _Proc(14, "chrome.exe", ["chrome.exe", "--flag", "research.py", "--serve"]),
        _Proc(15, "python.exe", ["C:\\Py\\python.exe", "other.py", "--serve"]),
        _Proc(16, "python.exe", None),                    # refused its command line
    ]))
    calls = _no_subprocess(monkeypatch)
    got = research._enumerate_research_py_procs_windows()
    assert [(pid, role) for pid, _c, role in got] == [
        (11, "daemon-loop"), (12, "serve"), (13, "other")]
    assert "research.py" in got[0][1] and "--daemon-loop" in got[0][1]
    assert calls == []


def test_a_path_with_a_space_keeps_its_quotes(monkeypatch):
    """The command line is rebuilt the way Windows writes it, as WMIC gave it."""
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil([
        _Proc(21, "python.exe", ["C:\\Program Files\\Py\\python.exe",
                                 "C:\\My Code\\research.py", "--serve"])]))
    _no_subprocess(monkeypatch)
    (pid, cmd, role), = research._enumerate_research_py_procs_windows()
    assert cmd == '"C:\\Program Files\\Py\\python.exe" "C:\\My Code\\research.py" --serve'


def _cim_run(payload, *, rc=0, wmic_out=None, seen=None):
    def _run(argv, *a, **k):
        if seen is not None:
            seen.append(argv[0])
        if argv[0] == "powershell.exe":
            assert k.get("creationflags") == research._PS_NO_WINDOW
            if payload is None:
                raise FileNotFoundError("powershell.exe")
            out = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=b"")
        if argv[0] == "wmic":
            if wmic_out is None:
                raise FileNotFoundError("wmic")
            return subprocess.CompletedProcess(argv, 0, stdout=wmic_out, stderr="")
        raise AssertionError(argv)
    return _run


@pytest.mark.parametrize("payload", [
    [{"ProcessId": 31, "CommandLine": "pythonw.exe research.py --daemon-loop"},
     {"ProcessId": 32, "CommandLine": "python.exe research.py --serve"},
     {"ProcessId": 33, "CommandLine": None}],
    {"ProcessId": 31, "CommandLine": "pythonw.exe research.py --daemon-loop"},
], ids=["many", "one-is-an-object"])
def test_without_psutil_powershells_cim_answers(monkeypatch, payload):
    """⛔ No psutil (an install that lost it): PowerShell's Get-CimInstance, which
    every Windows without WMIC has. ConvertTo-Json gives ONE process as an
    object, not a list."""
    monkeypatch.setitem(sys.modules, "psutil", None)
    seen = []
    monkeypatch.setattr(research.subprocess, "run", _cim_run(payload, seen=seen))
    got = research._enumerate_research_py_procs_windows()
    assert got[0][0] == 31 and got[0][2] == "daemon-loop"
    if isinstance(payload, list):
        assert [(p, r) for p, _c, r in got] == [(31, "daemon-loop"), (32, "serve")]
    assert seen == ["powershell.exe"]                       # WMIC not asked


def test_with_no_python_running_cim_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(research.subprocess, "run", _cim_run(b""))
    assert research._enumerate_research_py_procs_windows() == []


WMIC_OUT = ("\n\nCommandLine=pythonw.exe research.py --daemon-loop\n\nProcessId=41\n\n\n\n"
            "CommandLine=python.exe research.py --serve\n\nProcessId=42\n\n\n\n")


@pytest.mark.parametrize("cim", [None, "refused"], ids=["no-powershell", "cim-failed"])
def test_wmic_is_still_read_on_a_box_with_neither(monkeypatch, cim):
    """An old Windows with WMIC and without psutil or a working CIM: the old
    parser still reads it (blank lines between one entry's fields)."""
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(research.subprocess, "run",
                        _cim_run(None if cim is None else b"x", rc=0 if cim is None else 1,
                                 wmic_out=WMIC_OUT))
    assert [(p, r) for p, _c, r in research._enumerate_research_py_procs_windows()] == [
        (41, "daemon-loop"), (42, "serve")]


def test_with_no_source_at_all_the_list_is_empty(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(research.subprocess, "run", _cim_run(None))
    assert research._enumerate_research_py_procs_windows() == []


def test_a_processs_age_comes_from_psutil(monkeypatch):
    """`_proc_age_seconds_windows` read WMIC's CreationDate only — None on a box
    without WMIC, for every process."""
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(
        processes={77: ([], 1, time.time() - 120.0)}))
    _no_subprocess(monkeypatch)
    age = research._proc_age_seconds_windows(77)
    assert age is not None and 119.0 <= age <= 125.0


# ══ 2. the supervisor above a venv launcher ═══════════════════════════════════

DAEMON, LAUNCHER, ME = 500, 600, 700
WORKER_CMD = ["C:\\venv\\Scripts\\python.exe", "C:\\sr\\research.py", "--serve", "--worker-id", "2"]


def _world(monkeypatch, *, parent_cmd, platform="Windows", parent_ppid=DAEMON):
    monkeypatch.setattr(research, "_supervisor_platform", lambda: platform)
    monkeypatch.setattr(research.os, "getppid", lambda: LAUNCHER)
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(
        processes={ME: (WORKER_CMD, LAUNCHER, 0.0),
                   LAUNCHER: (parent_cmd, parent_ppid, 0.0),
                   DAEMON: (["pythonw.exe", "research.py", "--daemon-loop"], 4, 0.0)},
        me=ME))
    monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [
        (DAEMON, "pythonw.exe research.py --daemon-loop", "daemon-loop"),
        (LAUNCHER, " ".join(parent_cmd), "serve" if "--serve" in parent_cmd else "other"),
        (ME, " ".join(WORKER_CMD), "serve")])


def test_a_worker_started_through_its_venvs_launcher_is_supervised(monkeypatch):
    """⛔ The launcher's command line is the worker's own, argv[0] included (as
    measured on the owner's box): the daemon-loop above it is the supervisor."""
    _world(monkeypatch, parent_cmd=list(WORKER_CMD))
    assert research._supervisor_is_my_parent() is True
    assert research._requeue_capability_patch() == {"capabilities": [research.REQUEUE_CAPABILITY]}


def test_a_parent_with_another_command_line_is_not_a_launcher(monkeypatch):
    """A `--serve` parent that is not this worker's launcher (another worker, a
    foreground session) is not stepped over."""
    _world(monkeypatch, parent_cmd=["C:\\venv\\Scripts\\python.exe", "C:\\sr\\research.py",
                                    "--serve", "--worker-id", "3"])
    assert research._supervisor_is_my_parent() is False


def test_a_foreground_serve_under_a_shell_is_not_supervised(monkeypatch):
    _world(monkeypatch, parent_cmd=["C:\\Windows\\System32\\cmd.exe"], parent_ppid=DAEMON)
    assert research._supervisor_is_my_parent() is False


def test_the_launcher_step_is_windows_only(monkeypatch):
    """A POSIX venv's python is a symlink: a parent with this worker's command
    line there is a fork, and is never stepped over."""
    _world(monkeypatch, parent_cmd=list(WORKER_CMD), platform="Darwin")
    assert research._supervisor_is_my_parent() is False


def test_a_direct_daemon_loop_parent_is_supervised_as_before(monkeypatch):
    _world(monkeypatch, parent_cmd=list(WORKER_CMD))
    monkeypatch.setattr(research.os, "getppid", lambda: DAEMON)
    assert research._supervisor_is_my_parent() is True


# ══ 3. the Copy backup's line ends ════════════════════════════════════════════

class _ClipPage:
    def __init__(self, reads):
        self.reads = list(reads)

    async def evaluate(self, _js, *a):
        return self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]


def test_the_copy_is_read_back_with_lf_line_ends(monkeypatch):
    """⛔ Chrome on Windows hands the clipboard back with CRLF. The copy is LF, as
    the page read gives it — so brief.md is not written CR CR LF."""
    got = asyncio.run(research._chatgpt_read_copied(
        _ClipPage(["m", "## Brief\r\n\r\n| a | b |\r\n|---|---|\r\n| 1 | 2 |\r\nold mac\rend"]), "m"))
    assert got == "## Brief\n\n| a | b |\n|---|---|\n| 1 | 2 |\nold mac\nend"


def test_a_copy_that_never_came_is_still_the_marker(monkeypatch):
    monkeypatch.setattr(research, "_CG_COPY_READ_S", 0.3)
    assert asyncio.run(research._chatgpt_read_copied(_ClipPage(["m"]), "m")) == "m"


def test_a_crlf_brief_written_the_way_phase_1_writes_it_keeps_its_table(tmp_path):
    """What the fix is FOR, on this platform's own text mode: the brief as the
    copy now gives it, written as run_phase1 writes brief.md, reads back with
    its table's rows still together."""
    clip = "| a | b |\r\n|---|---|\r\n| 1 | 2 |"
    brief = asyncio.run(research._chatgpt_read_copied(_ClipPage([clip]), "m"))
    p = tmp_path / "brief.md"
    p.write_text(f"# Research Brief\n\n{brief}", encoding="utf-8")
    assert p.read_text(encoding="utf-8") == "# Research Brief\n\n| a | b |\n|---|---|\n| 1 | 2 |"


# ══ 4. the real thing, on Windows ═════════════════════════════════════════════

#: A process shaped like the daemon-loop (its command line names research.py
#: and --daemon-loop) that starts one child shaped like a worker and prints
#: what the child printed.
_PARENT = r"""
import subprocess, sys
child = [sys.argv[1], "-c", sys.argv[2], "research.py", "--serve"]
r = subprocess.run(child, capture_output=True, text=True, cwd=sys.argv[3], timeout=240)
print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "no output: " + r.stderr[-400:])
"""
_CHILD = r"""
import sys
sys.path.insert(0, ".")
import research
print("SUPERVISED" if research._supervisor_is_my_parent() else "FOREGROUND")
"""


def _as_daemon_loop(child_python):
    r = subprocess.run([sys.executable, "-c", _PARENT, child_python, _CHILD, str(REPO),
                        "research.py", "--daemon-loop"],
                       capture_output=True, text=True, timeout=300, cwd=str(REPO))
    return (r.stdout or "").strip().splitlines()[-1] if (r.stdout or "").strip() else r.stderr[-600:]


@pytest.mark.skipif(not ON_WINDOWS, reason="the real Windows process table")
def test_on_windows_a_real_worker_under_a_real_daemon_loop_is_supervised():
    """⛔⛔ The regression itself, on this machine's own process table: before
    the fix, on a Windows without WMIC, this printed FOREGROUND."""
    assert _as_daemon_loop(sys.executable) == "SUPERVISED"


@pytest.mark.skipif(not ON_WINDOWS, reason="a Windows venv's launcher")
def test_on_windows_a_worker_started_through_a_venv_launcher_is_supervised(tmp_path):
    """⛔ The pipx/venv shape: the child is started by a venv's Scripts\\python.exe,
    which runs the real interpreter as ITS child with the same command line."""
    venv = tmp_path / "venv"
    made = subprocess.run([sys.executable, "-m", "venv", "--system-site-packages",
                           "--without-pip", str(venv)], capture_output=True, text=True,
                          timeout=180)
    launcher = venv / "Scripts" / "python.exe"
    if made.returncode != 0 or not launcher.exists():
        pytest.skip(f"could not make a venv here: {made.stderr[-300:]}")
    assert _as_daemon_loop(str(launcher)) == "SUPERVISED"


@pytest.mark.skipif(not ON_WINDOWS, reason="the real Windows process table")
def test_on_windows_the_list_names_a_real_daemon_loop():
    """`--retire` and `--resurrect` read this list; on a Windows without WMIC it
    was empty, so neither saw the supervisor that was running."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                          "research.py", "--daemon-loop"])
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if any(pid == p.pid and role == "daemon-loop"
                   for pid, _c, role in research._enumerate_research_py_procs_windows()):
                break
            time.sleep(0.5)
        else:
            pytest.fail("the running daemon-loop-shaped process was not listed")
        age = research._proc_age_seconds_windows(p.pid)
        assert age is not None and 0 <= age < 120
    finally:
        p.kill()
        p.wait(timeout=30)
