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


def test_non_windows_is_guarded(monkeypatch):
    monkeypatch.setattr(autostart, "is_windows", lambda: False)
    for fn in (autostart.install, autostart.uninstall, autostart.status, autostart.start_detached):
        ok, msg = fn()
        assert ok is False and "Windows-only" in msg


def test_is_installed_reflects_status(monkeypatch):
    monkeypatch.setattr(autostart, "status", lambda task_name=autostart.TASK_NAME: (True, "ok"))
    assert autostart.is_installed() is True
    monkeypatch.setattr(autostart, "status", lambda task_name=autostart.TASK_NAME: (False, "not found"))
    assert autostart.is_installed() is False
