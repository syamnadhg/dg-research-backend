"""Autostart (Windows Scheduled Task) — windowless launcher + detached start,
the schtasks argv builders, and the non-Windows guards."""

from pathlib import Path

from facade import autostart


def test_run_command_quotes_interpreter_and_launcher():
    cmd = autostart.run_command(exe="C:\\py\\pythonw.exe", launcher=Path("C:\\s\\bridge_launcher.py"))
    # Both the interpreter and the launcher path are double-quoted.
    assert cmd == '"C:\\py\\pythonw.exe" "C:\\s\\bridge_launcher.py"'


def test_launcher_source_injects_agent_dir_and_calls_serve():
    src = autostart.launcher_source(agentdir=Path("C:\\proj\\agent"))
    assert "sys.path.insert(0, 'C:\\\\proj\\\\agent')" in src  # repr-quoted, escaped
    assert "from facade.cli import main" in src
    assert "main(['serve'])" in src


def test_write_launcher_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart.config, "store_dir", lambda: tmp_path)
    p = autostart.write_launcher(agentdir=Path("C:\\proj\\agent"))
    assert p == tmp_path / "bridge_launcher.py"
    assert "main(['serve'])" in p.read_text(encoding="utf-8")


def test_pythonw_exe_prefers_windowless_sibling(tmp_path, monkeypatch):
    (tmp_path / "python.exe").write_text("", encoding="utf-8")
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(autostart.sys, "executable", str(tmp_path / "python.exe"))
    assert autostart.pythonw_exe() == str(tmp_path / "pythonw.exe")


def test_pythonw_exe_falls_back_when_no_sibling(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart.sys, "executable", str(tmp_path / "python.exe"))
    # no pythonw.exe sibling on disk → fall back to the current interpreter
    assert autostart.pythonw_exe() == str(tmp_path / "python.exe")


def test_install_argv_shape():
    argv = autostart.install_argv("MyTask", command='"pw" "launch.py"')
    assert argv[0] == "schtasks"
    assert "/Create" in argv and "/F" in argv
    assert argv[argv.index("/TN") + 1] == "MyTask"
    assert "ONLOGON" in argv
    assert argv[argv.index("/TR") + 1] == '"pw" "launch.py"'


def test_install_argv_carries_interactive_token():
    # /IT is load-bearing: without it the S4U logon token can't read the DPAPI
    # Credential Locker, so the rehydrated bridge comes up unauthenticated.
    assert "/IT" in autostart.install_argv("MyTask")


def test_install_argv_defaults_to_run_command():
    argv = autostart.install_argv("MyTask")
    assert argv[argv.index("/TR") + 1] == autostart.run_command()


def test_uninstall_and_status_argv():
    assert autostart.uninstall_argv("T")[:2] == ["schtasks", "/Delete"]
    assert autostart.status_argv("T")[:2] == ["schtasks", "/Query"]


def test_is_installed_reflects_status(monkeypatch):
    monkeypatch.setattr(autostart, "status", lambda task_name=autostart.TASK_NAME: (True, "ok"))
    assert autostart.is_installed() is True
    monkeypatch.setattr(autostart, "status", lambda task_name=autostart.TASK_NAME: (False, "not found"))
    assert autostart.is_installed() is False


# ── cross-platform: supported / kind_label / unsupported ─────────────────────

def test_supported_and_kind_label_per_os(monkeypatch):
    for plat, label in (("win32", "Scheduled Task"),
                        ("linux", "systemd --user service"),
                        ("darwin", "launchd LaunchAgent")):
        monkeypatch.setattr(autostart.sys, "platform", plat)
        assert autostart.supported() is True
        assert autostart.kind_label() == label
    monkeypatch.setattr(autostart.sys, "platform", "sunos5")
    assert autostart.supported() is False


def test_install_unsupported_platform_reports_live_platform(monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "sunos5")
    ok, msg = autostart.install()
    assert ok is False and "sunos5" in msg  # message reflects the live platform


# ── Linux systemd dispatch ────────────────────────────────────────────────────

def test_systemd_unit_source_shape():
    # Pass the launcher as a plain str: on a Linux host launcher_path() is a
    # PosixPath (forward slashes); building a Path here on Windows would flip the
    # separators and isn't what the generator sees on its real (Linux) host.
    src = autostart.systemd_unit_source(
        exe="/usr/bin/python3", launcher="/home/u/.super-agent/bridge_launcher.py")
    assert "[Service]" in src and "[Install]" in src
    assert 'ExecStart="/usr/bin/python3" "/home/u/.super-agent/bridge_launcher.py"' in src
    assert "Restart=always" in src and "WantedBy=default.target" in src


def test_systemd_unit_exports_the_runtime_dir_self_update_depends_on():
    """selfupdate._cgroup_escape_prefix() returns [] with no XDG_RUNTIME_DIR, and a
    unit's environment is not the login shell's. Losing this line puts the update
    waiter back in the bridge's cgroup, where KillMode=control-group reaps it as
    the bridge exits — an empty self-update.log and a bridge stuck on the old
    version, with nothing in CI to notice."""
    src = autostart.systemd_unit_source(exe="/usr/bin/python3", launcher="/home/u/l.py")
    assert 'Environment="XDG_RUNTIME_DIR=/run/user/%U"' in src
    # Must sit under [Service]; systemd ignores Environment= in [Unit]/[Install].
    service_block = src.split("[Service]", 1)[1].split("[Install]", 1)[0]
    assert "Environment=" in service_block


def test_systemd_unit_source_quotes_paths_with_spaces():
    # systemd splits ExecStart on whitespace unless quoted — a spaced venv/home
    # path must stay one argument.
    src = autostart.systemd_unit_source(
        exe="/home/a b/venv/bin/python", launcher="/home/a b/.super-agent/bridge_launcher.py")
    assert 'ExecStart="/home/a b/venv/bin/python" "/home/a b/.super-agent/bridge_launcher.py"' in src


def test_linux_uninstall_surfaces_daemon_reload_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    monkeypatch.setattr(autostart, "systemd_unit_path", lambda: tmp_path / "u.service")
    monkeypatch.setattr(autostart, "_rm_launcher", lambda: None)
    results = iter([(True, "disabled"), (False, "reload failed")])  # disable ok, reload fails
    monkeypatch.setattr(autostart, "_exec", lambda argv: next(results))
    ok, out = autostart.uninstall()
    assert ok is False and "reload failed" in out  # not silently swallowed


def test_install_routes_to_systemd_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    monkeypatch.setattr(autostart, "_write_systemd_unit", lambda: tmp_path / "u.service")
    calls = []
    monkeypatch.setattr(autostart, "_exec", lambda argv: calls.append(argv) or (True, ""))
    ok, _ = autostart.install()
    assert ok is True
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert ["systemctl", "--user", "enable", autostart.SYSTEMD_UNIT] in calls


def test_start_detached_routes_to_systemctl_start_on_linux(monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(autostart, "_exec", lambda argv: calls.append(argv) or (True, ""))
    autostart.start_detached()
    assert calls[-1] == ["systemctl", "--user", "start", autostart.SYSTEMD_UNIT]


def test_uninstall_routes_to_systemctl_disable_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    monkeypatch.setattr(autostart, "systemd_unit_path", lambda: tmp_path / "u.service")
    monkeypatch.setattr(autostart, "_rm_launcher", lambda: None)
    calls = []
    monkeypatch.setattr(autostart, "_exec", lambda argv: calls.append(argv) or (True, ""))
    autostart.uninstall()
    assert ["systemctl", "--user", "disable", "--now", autostart.SYSTEMD_UNIT] in calls


# ── macOS launchd dispatch ────────────────────────────────────────────────────

def test_launchd_plist_source_shape():
    src = autostart.launchd_plist_source(
        exe="/usr/bin/python3", launcher=Path("/Users/u/.super-agent/bridge_launcher.py"))
    assert autostart.LAUNCHD_LABEL in src
    assert "<key>ProgramArguments</key>" in src
    assert "<key>RunAtLoad</key><true/>" in src
    assert "/usr/bin/python3" in src and "bridge_launcher.py" in src


def test_xml_escape():
    assert autostart._xml_escape("a&b<c>d") == "a&amp;b&lt;c&gt;d"


def test_install_routes_to_launchd_on_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    monkeypatch.setattr(autostart, "write_launcher", lambda *a, **k: tmp_path / "l.py")
    monkeypatch.setattr(autostart, "launchd_plist_path", lambda: tmp_path / "a.plist")
    calls = []
    monkeypatch.setattr(autostart, "_exec", lambda argv: calls.append(argv) or (True, ""))
    ok, _ = autostart.install()
    assert ok is True
    assert calls and calls[0][0] == "launchctl" and "load" in calls[0]
    assert (tmp_path / "a.plist").is_file()  # plist actually written


def test_start_detached_routes_to_launchctl_start_on_macos(monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    calls = []
    monkeypatch.setattr(autostart, "_exec", lambda argv: calls.append(argv) or (True, ""))
    autostart.start_detached()
    assert calls[-1] == ["launchctl", "start", autostart.LAUNCHD_LABEL]


# ── restart(): the post-update cycle (mirrors the backend's _restart_supervisor) ─

def test_restart_refuses_when_not_installed(monkeypatch):
    monkeypatch.setattr(autostart, "is_installed", lambda task_name=autostart.TASK_NAME: False)
    ok, msg = autostart.restart()
    assert ok is False and "not installed" in msg


def test_restart_uses_systemctl_restart_on_linux(monkeypatch):
    # `start` is a no-op on a running unit — a real restart is the ONLY thing that
    # swaps the live code after an upgrade.
    monkeypatch.setattr(autostart, "is_installed", lambda task_name=autostart.TASK_NAME: True)
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(autostart, "_exec", lambda argv: calls.append(argv) or (True, ""))
    ok, _ = autostart.restart()
    assert ok is True
    assert calls[-1] == ["systemctl", "--user", "restart", autostart.SYSTEMD_UNIT]


def test_restart_uses_kickstart_on_macos(monkeypatch):
    monkeypatch.setattr(autostart, "is_installed", lambda task_name=autostart.TASK_NAME: True)
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    monkeypatch.setattr(autostart.os, "getuid", lambda: 501, raising=False)
    calls = []
    monkeypatch.setattr(autostart, "_exec", lambda argv: calls.append(argv) or (True, ""))
    ok, _ = autostart.restart()
    assert ok is True
    flat = " ".join(calls[-1])
    assert "launchctl" in flat and "kickstart" in flat and "-k" in flat
    assert f"gui/501/{autostart.LAUNCHD_LABEL}" in flat


# ── Windows restart ───────────────────────────────────────────────────────────
# These are stubbed and platform-monkeypatched, which is the only thing runnable
# off Windows — and they therefore CANNOT prove anything about real `schtasks`
# behaviour. The gate for that is the manual procedure in the handoff doc: watch
# the port owner's PID across a restart. What these pin is the decision logic:
# who gets asked to stop, in what order, and when success may be claimed.
#
# The shape calls four things the old single test didn't stub; leaving any of them
# live would sleep ~90s and spawn a real detached bridge, so `_win_env` stubs all
# of them by default and each test overrides only what it is about.

def _win_env(monkeypatch, *, healthz, run_ok=True, start_ok=True):
    """Put `restart()` on the Windows branch with every side effect stubbed.

    `healthz` is called with no args and returns the /healthz body (or None) — a
    list lets a test script "answers, then stops answering". Returns the recorded
    schtasks argv list plus a dict of what else was called."""
    monkeypatch.setattr(autostart, "is_installed", lambda task_name=autostart.TASK_NAME: True)
    monkeypatch.setattr(autostart.sys, "platform", "win32")
    seen = {"shutdown": 0, "start": 0, "launcher": 0, "launcher_before_run": None}
    calls = []

    def _exec(argv):
        calls.append(argv)
        if "/End" in argv:
            return False, "no running instance"   # idle task — must not decide the result
        if "/Run" in argv:
            if seen["launcher_before_run"] is None:
                seen["launcher_before_run"] = seen["launcher"] > 0
            return run_ok, "" if run_ok else "access denied"
        return True, ""

    def _start(exe=None, launcher=None):
        seen["start"] += 1
        return start_ok, "" if start_ok else "spawn failed"

    monkeypatch.setattr(autostart, "_exec", _exec)
    monkeypatch.setattr(autostart, "_healthz", lambda timeout=2.0: healthz())
    monkeypatch.setattr(autostart, "_post_shutdown",
                        lambda timeout=10.0: seen.__setitem__("shutdown", seen["shutdown"] + 1))
    monkeypatch.setattr(autostart, "_win_start", _start)
    monkeypatch.setattr(autostart, "write_launcher",
                        lambda agentdir=None: seen.__setitem__("launcher", seen["launcher"] + 1))
    # The waits stay REAL functions over the stubbed _healthz — that's the ordering
    # logic under test. Shrink their deadlines rather than stubbing them out, and
    # drop the sleeps; with the deadlines still at 45s a give-up path would spin for
    # 90 wall-clock seconds per test.
    monkeypatch.setattr(autostart, "_STOP_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(autostart, "_START_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(autostart.time, "sleep", lambda s: None)
    return calls, seen


def _scripted(*bodies):
    """A `_healthz` stub that returns each body in turn, then repeats the last."""
    seq = list(bodies)

    def _next():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return _next


_LIVE = {"ok": True, "version": "0.1.29"}
_NEW = {"ok": True, "version": "0.1.30"}


def test_win_restart_stops_the_listener_then_confirms_a_new_one(monkeypatch):
    # The happy path: our bridge is up, so it's asked to stop, and success is only
    # claimed once something is answering /healthz again.
    calls, seen = _win_env(monkeypatch, healthz=_scripted(_LIVE, None, _NEW))
    ok, msg = autostart.restart()
    assert (ok, msg) == (True, "restarted")
    assert seen["shutdown"] == 1, "the live bridge must be asked to shut down"
    verbs = [c[1] for c in calls]  # schtasks <verb> ...
    assert "/End" in verbs and "/Run" in verbs
    assert verbs.index("/End") < verbs.index("/Run"), "End before Run"
    assert ok is True, "restart must not report /End's non-zero as the result"


def test_win_restart_never_posts_shutdown_at_a_foreign_port_holder(monkeypatch):
    # /healthz without our marker = someone else owns the port. Firing /shutdown at
    # an unrelated local service would be the worst possible bug here, so the POST
    # is gated on having PROVEN it's ours. Starting is still attempted.
    calls, seen = _win_env(monkeypatch, healthz=_scripted(None, None, _NEW))
    ok, _ = autostart.restart()
    assert seen["shutdown"] == 0, "must not POST /shutdown at a non-bridge holder"
    assert ok is True
    assert any("/Run" in c for c in calls)


def test_win_restart_does_not_run_while_the_old_bridge_still_answers(monkeypatch):
    # The core of the old bug: /Run against a still-owned port launches an instance
    # that sees the port taken and exits, leaving the OLD code serving while
    # schtasks exits 0. So /Run must not be issued until the port is free.
    calls, seen = _win_env(monkeypatch, healthz=lambda: _LIVE)   # never goes away
    ok, msg = autostart.restart()
    assert ok is False
    assert "did not stop" in msg
    assert seen["shutdown"] == 1
    assert not any("/Run" in c for c in calls), "/Run must wait for the port to free"


def test_win_restart_falls_back_to_detached_start_when_the_scheduler_declines(monkeypatch):
    # /Run reports "attempted" and can still start nothing (an /IT task needs an
    # interactive session). Rather than leave the host bridgeless, fall back to the
    # same detached start connect/resurrect use.
    # Nothing answers after /Run until the fallback start has actually run.
    state = {"started": False, "first": True}

    def _healthz():
        if state["started"]:
            return _NEW
        if state["first"]:              # the pre-existing bridge, once
            state["first"] = False
            return _LIVE
        return None                     # stopped, and /Run brings nothing up

    calls, seen = _win_env(monkeypatch, healthz=_healthz)

    def _start(exe=None, launcher=None):
        state["started"] = True
        seen["start"] += 1
        return True, ""
    monkeypatch.setattr(autostart, "_win_start", _start)
    ok, msg = autostart.restart()
    assert (ok, msg) == (True, "restarted")
    assert state["started"] is True, "must fall back to the detached start"
    assert any("/Run" in c for c in calls)


def test_win_restart_reports_failure_when_no_bridge_comes_back(monkeypatch):
    # Never claim success without a live listener — not even when both the
    # scheduler and the fallback were "issued" without error.
    _calls, seen = _win_env(monkeypatch, healthz=_scripted(_LIVE, None), start_ok=True)
    ok, msg = autostart.restart()
    assert ok is False
    assert "no bridge came back" in msg
    assert seen["start"] == 1, "the fallback start must have been attempted"


def test_win_restart_surfaces_a_failed_run(monkeypatch):
    _calls, _seen = _win_env(monkeypatch, healthz=_scripted(_LIVE, None), run_ok=False)
    ok, msg = autostart.restart()
    assert ok is False
    assert "access denied" in msg


def test_win_restart_refreshes_the_launcher_before_running_the_task(monkeypatch):
    # A pipx upgrade moves the agent dir, and the launcher bakes that path in at
    # write time — so /Run would re-exec a stale launcher. Writing it BEFORE the
    # stop also means an unwritable store dir aborts with the old bridge intact.
    calls, seen = _win_env(monkeypatch, healthz=_scripted(_LIVE, None, _NEW))
    autostart.restart()
    assert seen["launcher"] >= 1, "the launcher must be refreshed"
    assert seen["launcher_before_run"] is True, "refresh must precede /Run"
    run_at = [i for i, c in enumerate(calls) if "/Run" in c]
    assert run_at, "/Run should have been issued"


def test_win_restart_aborts_without_stopping_when_the_launcher_cannot_be_written(monkeypatch):
    calls, seen = _win_env(monkeypatch, healthz=_scripted(_LIVE))

    def _boom(agentdir=None):
        raise OSError("read-only store")
    monkeypatch.setattr(autostart, "write_launcher", _boom)
    ok, msg = autostart.restart()
    assert ok is False
    assert "launcher" in msg
    assert seen["shutdown"] == 0, "must not stop a working bridge it can't replace"
    assert calls == [], "must not touch the scheduler either"


def test_win_restart_same_version_is_still_success(monkeypatch):
    # Restarting onto identical code is legitimate (config change, operator cycle).
    _calls, _seen = _win_env(monkeypatch, healthz=_scripted(_LIVE, None, _LIVE))
    ok, msg = autostart.restart()
    assert (ok, msg) == (True, "restarted")


def test_healthz_requires_the_bridge_marker(monkeypatch):
    # Same rule as cli._bridge_up / bridge._port_holder_is_bridge: a foreign server
    # answering 200 on the port is NOT our bridge.
    import io

    bodies = {}
    monkeypatch.setattr(autostart.urllib.request, "urlopen",
                        lambda url, timeout=None: io.BytesIO(bodies["b"]))
    for raw, want in ((b'{"ok": true, "version": "1"}', True),
                      (b'{"ok": true}', False),            # no version
                      (b'{"version": "1"}', False),        # no ok
                      (b'["not", "a", "dict"]', False),
                      (b'<html>nginx</html>', False)):     # not even JSON
        bodies["b"] = raw
        assert (autostart._healthz() is not None) is want, raw


def test_post_shutdown_uses_post_not_get(monkeypatch):
    # A bare urlopen(url) sends GET, which /shutdown answers 404 — the restart
    # would then always time out waiting for a bridge nobody asked to stop.
    seen = {}

    def _urlopen(req, timeout=None):
        seen["method"] = req.get_method()
        seen["url"] = req.full_url
        raise OSError("connection refused")   # best-effort: must be swallowed
    monkeypatch.setattr(autostart.urllib.request, "urlopen", _urlopen)
    autostart._post_shutdown()
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/shutdown")
