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
