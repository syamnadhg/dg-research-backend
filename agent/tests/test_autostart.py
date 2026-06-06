"""Autostart (Windows Scheduled Task) command-building + the non-Windows guard."""

from facade import autostart


def test_run_command_quotes_interpreter_and_runs_serve():
    cmd = autostart.run_command()
    assert cmd.startswith('"') and "-m facade serve" in cmd


def test_install_argv_shape():
    argv = autostart.install_argv("MyTask")
    assert argv[0] == "schtasks"
    assert "/Create" in argv and "/F" in argv
    assert argv[argv.index("/TN") + 1] == "MyTask"
    assert "ONLOGON" in argv
    assert argv[argv.index("/TR") + 1] == autostart.run_command()


def test_uninstall_and_status_argv():
    assert autostart.uninstall_argv("T")[:2] == ["schtasks", "/Delete"]
    assert autostart.status_argv("T")[:2] == ["schtasks", "/Query"]


def test_non_windows_is_guarded(monkeypatch):
    monkeypatch.setattr(autostart, "is_windows", lambda: False)
    for fn in (autostart.install, autostart.uninstall, autostart.status):
        ok, msg = fn()
        assert ok is False and "Windows-only" in msg
