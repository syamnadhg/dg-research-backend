"""Post-update restart: the step that was silently missing.

An update lands by ANY route — `superresearch --update`, a bare `pipx upgrade`, or
the superresearch.io installer — and the package on disk changes, but the RUNNING
backend keeps the old build in memory until it is cycled. Nothing told the user
that, so an update looked finished while the old code was still serving.

Two halves are pinned here:
  1. drift detection — installed version vs the version actually SERVING
  2. `--restart` — a real per-platform restart, replacing the `--retire` +
     `--resurrect` pairing (retire REMOVES On Startup; it's a teardown, not a
     restart) and the `--resurrect`-alone path that FAILED when the supervisor was
     already up (launchd bootout is async → bootstrap raced it).
"""
from __future__ import annotations

import json

import pytest

import research


# ── drift detection ──────────────────────────────────────────────────────────

def _mark(tmp_path, monkeypatch, *, version, pid):
    p = tmp_path / "running-version.json"
    p.write_text(json.dumps({"version": version, "pid": pid}), encoding="utf-8")
    monkeypatch.setattr(research, "_RUNNING_VERSION_PATH", p)
    return p


def test_running_version_reads_the_marker(tmp_path, monkeypatch):
    _mark(tmp_path, monkeypatch, version="0.1.7", pid=1234)
    monkeypatch.setattr(research, "_pid_alive", lambda pid: True)
    assert research._running_version() == "0.1.7"


def test_running_version_is_none_when_the_process_is_gone(tmp_path, monkeypatch):
    # A stale marker from a dead process must NOT be reported as "serving" —
    # otherwise every command would nag about restarting nothing.
    _mark(tmp_path, monkeypatch, version="0.1.7", pid=999999)
    monkeypatch.setattr(research, "_pid_alive", lambda pid: False)
    assert research._running_version() is None


def test_running_version_is_none_when_marker_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "_RUNNING_VERSION_PATH", tmp_path / "nope.json")
    assert research._running_version() is None


def test_running_version_survives_a_corrupt_marker(tmp_path, monkeypatch):
    p = tmp_path / "running-version.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(research, "_RUNNING_VERSION_PATH", p)
    assert research._running_version() is None


def test_restart_pending_when_installed_is_newer(tmp_path, monkeypatch):
    _mark(tmp_path, monkeypatch, version="0.1.7", pid=1)
    monkeypatch.setattr(research, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.8")
    assert research._restart_pending() == ("0.1.7", "0.1.8")


def test_no_restart_pending_when_versions_match(tmp_path, monkeypatch):
    _mark(tmp_path, monkeypatch, version="0.1.8", pid=1)
    monkeypatch.setattr(research, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.8")
    assert research._restart_pending() is None


def test_no_restart_pending_when_nothing_is_running(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "_RUNNING_VERSION_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.8")
    assert research._restart_pending() is None


def test_no_restart_pending_in_a_source_checkout(tmp_path, monkeypatch):
    # A source checkout reports "(source checkout)" as its version — comparing that
    # to a running version would nag forever on dev machines.
    _mark(tmp_path, monkeypatch, version="0.1.7", pid=1)
    monkeypatch.setattr(research, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(research, "_sr_version", lambda: "(source checkout)")
    assert research._restart_pending() is None


def test_write_running_version_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(research, "_RUNNING_VERSION_PATH", tmp_path / "running-version.json")
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.8")
    research._write_running_version()
    data = json.loads((tmp_path / "running-version.json").read_text(encoding="utf-8"))
    assert data["version"] == "0.1.8" and isinstance(data["pid"], int)


def test_warn_if_restart_pending_is_silent_when_nothing_pending(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(research, "_restart_pending", lambda: None)
    research._warn_if_restart_pending()
    assert capsys.readouterr().out == ""


def test_warn_if_restart_pending_names_both_versions(monkeypatch, capsys):
    monkeypatch.setattr(research, "_restart_pending", lambda: ("0.1.7", "0.1.8"))
    monkeypatch.setattr(research, "_supervisor_installed", lambda: True)
    research._warn_if_restart_pending()
    out = capsys.readouterr().out
    assert "0.1.7" in out and "0.1.8" in out and "--restart" in out


# ── the restart hint adapts to how the backend is run ────────────────────────

def test_restart_hint_uses_restart_when_supervised(monkeypatch):
    monkeypatch.setattr(research, "_supervisor_installed", lambda: True)
    blob = "\n".join(research._restart_hint_lines())
    assert "--restart" in blob and "--serve" not in blob


def test_restart_hint_uses_serve_without_a_supervisor(monkeypatch):
    # No always-on installed → there is nothing supervised to cycle; pointing at
    # --restart there would just fail.
    monkeypatch.setattr(research, "_supervisor_installed", lambda: False)
    blob = "\n".join(research._restart_hint_lines())
    assert "--serve" in blob


# ── _restart_supervisor: real per-platform restart ───────────────────────────

def test_restart_supervisor_refuses_when_not_installed(monkeypatch):
    monkeypatch.setattr(research, "_supervisor_installed", lambda: False)
    ok, msg = research._restart_supervisor()
    assert ok is False and "not installed" in msg


# _supervisor_platform() returns the capitalized platform.system() values
# ("Darwin"/"Linux"/"Windows") — the restart code branches on exactly those, so
# the test must monkeypatch the SAME convention (a lowercase stub silently
# matched no branch and gave false-green coverage for a dead --restart).
@pytest.mark.parametrize("plat,expect_any", [
    ("Darwin", ["kickstart"]),         # -k force-restarts an already-loaded job
    ("Linux", ["restart"]),            # `enable --now` is a NO-OP when running
    ("Windows", ["/Run"]),             # /Create never touches the live process
])
def test_restart_supervisor_uses_a_real_restart_verb(monkeypatch, plat, expect_any):
    monkeypatch.setattr(research, "_supervisor_installed", lambda: True)
    monkeypatch.setattr(research, "_supervisor_platform", lambda: plat)
    seen = []

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, *a, **kw):
        seen.append(list(cmd))
        return _R()

    import subprocess
    monkeypatch.setattr(subprocess, "run", _fake_run)
    if plat == "Darwin":
        monkeypatch.setattr(research.os, "getuid", lambda: 501, raising=False)
    ok, msg = research._restart_supervisor()
    flat = " ".join(" ".join(c) for c in seen)
    assert ok is True, msg
    assert any(tok in flat for tok in expect_any), flat


def test_restart_supervisor_reports_failure(monkeypatch):
    monkeypatch.setattr(research, "_supervisor_installed", lambda: True)
    monkeypatch.setattr(research, "_supervisor_platform", lambda: "Linux")

    class _R:
        returncode = 1
        stdout = ""
        stderr = "Unit not found"

    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _R())
    ok, msg = research._restart_supervisor()
    assert ok is False and "Unit not found" in msg


def test_restart_supervisor_never_raises(monkeypatch):
    monkeypatch.setattr(research, "_supervisor_installed", lambda: True)
    monkeypatch.setattr(research, "_supervisor_platform", lambda: "Linux")

    import subprocess

    def _boom(*a, **kw):
        raise OSError("launchctl exploded")

    monkeypatch.setattr(subprocess, "run", _boom)
    ok, msg = research._restart_supervisor()
    assert ok is False and "OSError" in msg


# ── the macOS bootout/bootstrap race that broke --resurrect ──────────────────

def test_macos_arm_waits_for_bootout_before_bootstrap():
    """`launchctl bootout` is ASYNC. Firing `bootstrap` immediately raced it and
    hard-failed, which is why --resurrect blew up when On Startup was already
    running. The arm must poll until the job is gone, and must not treat an
    'already bootstrapped' bootstrap as fatal when the job IS loaded."""
    import inspect
    src = inspect.getsource(research._arm_supervisor_macos)
    assert "_job_loaded" in src, "no post-bootout wait — the race is back"
    assert "kickstart" in src
    # the bootstrap failure path must be conditional on the job NOT being loaded
    assert "if not _job_loaded():" in src


def test_restart_is_wired_as_a_cli_flag():
    """--restart must be a registered flag that dispatches to run_restart, and must
    be documented in the hand-written help (argparse's auto list isn't shown)."""
    import inspect
    src = inspect.getsource(research)
    assert hasattr(research, "run_restart")
    assert 'parser.add_argument("--restart"' in src, "flag not registered"
    assert "if args.restart:\n        run_restart()" in src, "flag not dispatched"
    assert "python research.py --restart" in src, "missing from the custom help text"


def test_restart_is_not_retire():
    """--retire REMOVES On Startup (a teardown). --restart must keep it — that
    distinction is the whole reason this command exists."""
    import inspect
    src = inspect.getsource(research.run_restart)
    assert "_restart_supervisor()" in src
    for destructive in ("schtasks\", \"/Delete", "bootout", "disable"):
        assert destructive not in src, f"run_restart must not tear down: {destructive}"
