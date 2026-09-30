"""The Windows review of wave 13 (2026-09-30): defects the Mac could not see.

⛔⛔ 1. MOVE TO QUEUE WAS NEVER OFFERED ON WINDOWS. The machine publishes the
"requeue" capability — and obeys a requeue — only when `_supervisor_is_my_parent()`
says a daemon-loop started this worker. That asked `_enumerate_research_py_procs`,
whose Windows half ran WMIC inside `except Exception: return []`; current
Windows 11 (the owner's 10.0.26200 box) has no WMIC.exe, so the list was always
empty: no chip in the app, every requeue refused as "not supervised" — and the
older users of the same list (`--retire`, `--resurrect`, the daemon-loop's
pre-flight sweep) saw nothing running either. The list now comes from psutil
(the name first; a command line is read only for a python), then PowerShell's
CIM, and WMIC last.

⛔ 1b. A VENV'S LAUNCHER STANDS BETWEEN. On a pipx or venv install the
daemon-loop spawns each worker through `Scripts\\python.exe`, a launcher that
starts the real interpreter with the same arguments — so the worker's direct
parent is the launcher, the daemon-loop is one step up, and an update must not
stop the launcher (that ends the worker through the launcher's job).

⛔ 1c. RESET BACKEND ASKED ABOUT ANY SUPERVISOR. With the list now real on
Windows, "a daemon-loop runs somewhere" would exit a foreground --serve beside
the fleet for good; it asks about its own parent now, as reconnect does.

⛔ 2. THE COPY BACKUP'S BRIEF CAME BACK WITH CRLF. Chrome on Windows hands the
clipboard back with CRLF line ends; brief.md is written in text mode, which
makes each CR CR LF, and read back every line gains a blank line — a table's
rows fall apart before the brief reaches the Phase 2 agents.

⛔ 3. THE CLIPBOARD HOOKS NEED THE PAGE'S OWN SCRIPT WORLD. patchright 1.62+
(the new floor) runs `evaluate` isolated; a `writeText` hook installed there
never sees the page's own Copy. The hooks now run in the page's world.

Sections 1-4 run everywhere (fakes; section 4's browser test needs Chrome);
section 5 runs the real process table on Windows.
"""
import asyncio
import inspect
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
    """A process as `process_iter(["pid", "name"])` hands it out. Its command
    line is read only on request, and every read is recorded."""

    def __init__(self, pid, name, cmdline, reads):
        self.info = {"pid": pid, "name": name}
        self._cmdline, self._reads = cmdline, reads

    def cmdline(self):
        self._reads.append(self.info["pid"])
        if self._cmdline is None:
            raise PermissionError("access denied")     # psutil.AccessDenied
        return list(self._cmdline)


def _fake_psutil(procs=(), processes=None, me=None):
    """A psutil with `process_iter` over `procs` and `Process(pid)` answering
    from `processes` (pid → dict of cmd, ppid, ct, name, exe); `me` is Process()."""
    processes = dict(processes or {})

    class NoSuchProcess(Exception):
        pass

    class Process:
        def __init__(self, pid=None):
            self.pid = me if pid is None else pid
            if self.pid not in processes:
                raise NoSuchProcess(self.pid)
            self._p = processes[self.pid]

        def cmdline(self):
            return list(self._p["cmd"])

        def ppid(self):
            return self._p["ppid"]

        def create_time(self):
            return self._p["ct"]

        def name(self):
            return self._p["name"]

        def exe(self):
            return self._p["exe"]

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
    """⛔ psutil answers first: WMIC is not asked (it is gone), nor PowerShell.
    And only a python's command line is read — asking every process's costs
    about a second per protected one (LsaIso, NgcIso …) under an elevated
    token, about 5 s a scan."""
    reads = []
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil([
        _Proc(11, "pythonw.exe", ["C:\\Py\\pythonw.exe", "C:\\sr\\research.py", "--daemon-loop"], reads),
        _Proc(12, "python.exe", ["C:\\Py\\python.exe", "C:\\sr\\research.py", "--serve",
                                 "--worker-id", "2"], reads),
        _Proc(13, "Python.EXE", ["C:\\Py\\python.exe", "research.py", "a topic"], reads),
        _Proc(14, "chrome.exe", ["chrome.exe", "--flag", "research.py", "--serve"], reads),
        _Proc(15, "python.exe", ["C:\\Py\\python.exe", "other.py", "--serve"], reads),
        _Proc(16, "python.exe", None, reads),                 # refused its command line
        _Proc(17, "LsaIso.exe", None, reads),                 # protected: never asked
    ]))
    calls = _no_subprocess(monkeypatch)
    got = research._enumerate_research_py_procs_windows()
    assert [(pid, role) for pid, _c, role in got] == [
        (11, "daemon-loop"), (12, "serve"), (13, "other")]
    assert "research.py" in got[0][1] and "--daemon-loop" in got[0][1]
    assert calls == []
    assert sorted(reads) == [11, 12, 13, 15, 16], f"a non-python's command line was read: {reads}"


def test_a_path_with_a_space_keeps_its_quotes(monkeypatch):
    """The command line is rebuilt the way Windows writes it, as WMIC gave it."""
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil([
        _Proc(21, "python.exe", ["C:\\Program Files\\Py\\python.exe",
                                 "C:\\My Code\\research.py", "--serve"], [])]))
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
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(processes={
        77: {"cmd": [], "ppid": 1, "ct": time.time() - 120.0, "name": "python.exe", "exe": ""}}))
    _no_subprocess(monkeypatch)
    age = research._proc_age_seconds_windows(77)
    assert age is not None and 119.0 <= age <= 125.0


# ══ 2. the supervisor above a venv launcher, and what an update stops ═════════

DAEMON, LAUNCHER, ME, SIBLING, ONE_OFF = 500, 600, 700, 800, 900
BASE = "C:\\Py\\python.exe"
ARGS = ["C:\\sr\\research.py", "--serve", "--worker-id", "2"]


def _world(monkeypatch, tmp_path, *, parent_argv0=None, parent_args=ARGS,
           parent_name="python.exe", in_venv=True, platform="Windows", my_argv0=None):
    """This worker (ME) under a parent at LAUNCHER, under the daemon-loop at
    DAEMON. The parent's exe sits in <tmp>/venv/Scripts — a venv when
    `in_venv` (its pyvenv.cfg is there). argv[0]s default to the 3.13+ shape
    (the launcher's own path in both)."""
    venv = tmp_path / "venv"
    (venv / "Scripts").mkdir(parents=True, exist_ok=True)
    if in_venv:
        (venv / "pyvenv.cfg").write_text("home = C:\\Py\n", encoding="utf-8")
    launcher = str(venv / "Scripts" / "python.exe")
    parent_cmd = [parent_argv0 or launcher, *parent_args]
    my_cmd = [my_argv0 or launcher, *ARGS]
    monkeypatch.setattr(research, "_supervisor_platform", lambda: platform)
    monkeypatch.setattr(research.os, "getppid", lambda: LAUNCHER)
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(processes={
        ME: {"cmd": my_cmd, "ppid": LAUNCHER, "ct": 0.0, "name": "python.exe", "exe": BASE},
        LAUNCHER: {"cmd": parent_cmd, "ppid": DAEMON, "ct": 0.0, "name": parent_name,
                   "exe": launcher},
        DAEMON: {"cmd": ["pythonw.exe", "research.py", "--daemon-loop"], "ppid": 4, "ct": 0.0,
                 "name": "pythonw.exe", "exe": "C:\\Py\\pythonw.exe"},
    }, me=ME))
    monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [
        (DAEMON, "pythonw.exe research.py --daemon-loop", "daemon-loop"),
        (LAUNCHER, " ".join(parent_cmd), "serve" if "--serve" in parent_cmd else "other"),
        (ME, " ".join(my_cmd), "serve"),
        (SIBLING, "python.exe research.py --serve --worker-id 3", "serve"),
        (ONE_OFF, "python.exe research.py a topic", "other")])


@pytest.mark.parametrize("shape", ["3.13+", "3.11/3.12"])
def test_a_worker_started_through_its_venvs_launcher_is_supervised(monkeypatch, tmp_path, shape):
    """⛔ The launcher carries the worker's arguments (3.13+ keeps argv[0] too —
    measured on the owner's box; 3.11/3.12 rewrite the child's to the base
    interpreter): the daemon-loop above it is the supervisor."""
    _world(monkeypatch, tmp_path, my_argv0=BASE if shape == "3.11/3.12" else None)
    assert research._supervisor_is_my_parent() is True
    assert research._requeue_capability_patch() == {"capabilities": [research.REQUEUE_CAPABILITY]}


@pytest.mark.parametrize("case", ["another-worker", "not-a-venv", "another-program", "a-shell"])
def test_a_parent_that_is_not_this_workers_launcher_is_not_stepped_over(monkeypatch, tmp_path, case):
    """A sibling worker, a python outside any venv with the same arguments, a
    different program, a shell: none is this worker's launcher, so the
    daemon-loop above it is not this worker's supervisor."""
    kw = {"another-worker": {"parent_args": ["C:\\sr\\research.py", "--serve", "--worker-id", "3"]},
          "not-a-venv": {"in_venv": False},
          "another-program": {"parent_name": "py.exe"},
          "a-shell": {"parent_argv0": "C:\\Windows\\System32\\cmd.exe", "parent_args": []}}[case]
    _world(monkeypatch, tmp_path, **kw)
    assert research._supervisor_is_my_parent() is False


def test_the_launcher_step_is_windows_only(monkeypatch, tmp_path):
    """A POSIX venv's python is a symlink: a parent with this worker's command
    line there is a fork, and is never stepped over."""
    _world(monkeypatch, tmp_path, platform="Darwin")
    assert research._supervisor_is_my_parent() is False


def test_a_direct_daemon_loop_parent_is_supervised_as_before(monkeypatch, tmp_path):
    _world(monkeypatch, tmp_path)
    monkeypatch.setattr(research.os, "getppid", lambda: DAEMON)
    assert research._supervisor_is_my_parent() is True


def test_an_update_never_stops_this_worker_or_its_own_launcher(monkeypatch, tmp_path):
    """⛔ The update's "free the venv" list: every daemon-loop and --serve but
    this worker — and not its own launcher either, whose job would end this
    worker part-way through the list. A sibling worker and the daemon-loop are
    stopped; a one-off run is not."""
    _world(monkeypatch, tmp_path)
    monkeypatch.setattr(research.os, "getpid", lambda: ME)
    assert research._backend_procs_holding_the_venv() == [DAEMON, SIBLING]


def test_an_update_from_a_worker_with_no_launcher_stops_everything_else(monkeypatch, tmp_path):
    _world(monkeypatch, tmp_path, in_venv=False)
    monkeypatch.setattr(research.os, "getpid", lambda: ME)
    assert research._backend_procs_holding_the_venv() == [DAEMON, LAUNCHER, SIBLING]


def test_reset_backend_asks_about_its_own_supervisor():
    """⛔ HARD_RESET's exit-or-stay asks whether ITS parent is a daemon-loop, as
    reconnect and relink do — not whether one runs anywhere on the machine."""
    src = inspect.getsource(research._start_device_command_listener)
    assert "_supervisor_alive = _supervisor_is_my_parent()" in src
    assert 'if pid != self_pid and role == "daemon-loop"' not in src


# ══ 3. the Copy backup's line ends ════════════════════════════════════════════

class _ClipPage:
    def __init__(self, reads):
        self.reads = list(reads)

    async def evaluate(self, _js, *a):
        return self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]


def test_the_copy_is_read_back_with_lf_line_ends():
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


# ══ 4. the clipboard hooks run in the page's own world ════════════════════════

class _PatchrightTarget:
    def __init__(self):
        self.worlds = []

    async def evaluate(self, js, arg=None, *, isolated_context=True):
        self.worlds.append("isolated" if isolated_context else "page")
        return arg


class _PlainTarget:
    def __init__(self):
        self.calls = []

    async def evaluate(self, js, *args):
        self.calls.append(args)
        return args[0] if args else None


def test_a_hook_runs_in_the_pages_world_where_patchright_can_say_so():
    t = _PatchrightTarget()
    assert asyncio.run(research._page_world_evaluate(t, "js", {"a": 1})) == {"a": 1}
    assert asyncio.run(research._page_world_evaluate(t, "js")) is None
    assert t.worlds == ["page", "page"]


def test_a_target_without_worlds_is_called_as_before():
    """A test double, or plain Playwright: no `isolated_context` to pass."""
    t = _PlainTarget()
    assert asyncio.run(research._page_world_evaluate(t, "js", 5)) == 5
    asyncio.run(research._page_world_evaluate(t, "js"))
    assert t.calls == [(5,), ()]


@pytest.mark.parametrize("fn", ["_copy_via_hijack", "_run_with_clipboard_hijack"])
def test_every_evaluate_in_the_clipboard_hooks_is_in_the_pages_world(fn):
    """Install, click, the reads of what was captured, and the unhook: one world,
    or the reads look at a window the hook never wrote."""
    src = inspect.getsource(getattr(research, fn))
    assert "_page_world_evaluate(" in src
    assert "page.evaluate(" not in src and "tgt.evaluate(" not in src, fn


HOOK_URL = "http://127.0.0.1:9/hook"             # the Copy tests' granted origin
REPLY = " ".join(f"word{n}" for n in range(200))


@pytest.fixture
def hook_page(request):
    """A page whose own Copy button writes its reply with navigator.clipboard.writeText,
    in headless Chrome with the clipboard granted (the Copy tests' browser)."""
    ch = request.getfixturevalue("chrome")
    page = ch.run(ch.ctx.new_page())
    body = ("<!doctype html><html><body><div id='t'>" + REPLY + "</div>"
            "<button id='copy' aria-label='Copy' onclick=\"navigator.clipboard.writeText("
            "document.getElementById('t').textContent)\">Copy</button></body></html>")

    async def _serve(route):
        if route.request.url == HOOK_URL:
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)
        else:
            await route.abort()

    async def _go():
        await page.route("**/*", _serve)
        await page.goto(HOOK_URL)

    ch.run(_go())
    yield ch, page
    ch.run(page.close())


# The Copy tests' module-scoped Chrome, shared here.
from test_chatgpt_copy_fallback_w13 import chrome  # noqa: E402,F401


def test_live_the_copy_hijack_catches_the_pages_own_copy(hook_page, monkeypatch):
    """⛔⛔ On patchright 1.62+ (the new floor, and every Mac) the hook sat in the
    isolated world and caught nothing — the Claude chat-mode Copy tier returned
    "" with no word why."""
    ch, page = hook_page
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    got = ch.run(research._copy_via_hijack(
        page, "T", direct_copy_selectors=["#copy"], wait_ms=2000, min_chars=100))
    assert got == REPLY


def test_live_the_tier_3_hijack_catches_the_pages_own_copy(hook_page, monkeypatch):
    """The CUA-copy tiers' hook: the Copy button the CUA presses writes through
    the page's own writeText."""
    ch, page = hook_page
    monkeypatch.setattr(research, "log", lambda *a, **k: None)

    async def _press():
        await page.click("#copy")

    got = ch.run(research._run_with_clipboard_hijack(
        page, "T", _press, timeout_ms=5000, min_chars=100))
    assert got == REPLY


# ══ 5. the real thing, on Windows ═════════════════════════════════════════════

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
    which runs the real interpreter as ITS child with the same arguments."""
    venv = tmp_path / "venv"
    made = subprocess.run([sys.executable, "-m", "venv", "--system-site-packages",
                           "--without-pip", str(venv)], capture_output=True, text=True,
                          timeout=180)
    launcher = venv / "Scripts" / "python.exe"
    if made.returncode != 0 or not launcher.exists():
        pytest.skip(f"could not make a venv here: {made.stderr[-300:]}")
    probe = subprocess.run([str(launcher), "-c", "import psutil, patchright"],
                           capture_output=True, text=True, timeout=120)
    if probe.returncode != 0:
        pytest.skip("the venv cannot see this interpreter's packages (pytest runs from a venv)")
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
