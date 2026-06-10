"""Command-body + helper tests for the agent CLI: _disconnect_pairs (teardown
orchestration), _logout_session (the #790 bridge-down agent-row deletion), and
the resurrect/retire/disconnect bodies (incl. retire's no-task string heuristic).

All deps are module-level imports in facade.cli, so everything is monkeypatched
in-place — no HTTP server, no real runtime dirs, no schtasks.
"""

import contextlib
import io
from pathlib import Path
from types import SimpleNamespace

from facade import cli, connect


def _ns(**kw):
    return SimpleNamespace(runtime=None, dest=None, verbose=False, **kw)


# ── _disconnect_pairs ─────────────────────────────────────────────────────────

def test_disconnect_pairs_dedups_detect_and_prefs(monkeypatch):
    home = Path("C:/Users/me")
    monkeypatch.setattr(cli.connect, "detect_targets",
                        lambda: [connect.Target("hermes", "local",home)])
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "hermes")
    monkeypatch.setattr(cli.prefs, "get_runtime_home", lambda: str(home))
    pairs = cli._disconnect_pairs(None, None)
    assert pairs == [("hermes", home)]  # detect + prefs collapse to one pair


def test_disconnect_pairs_recovers_unmounted_wsl_from_prefs(monkeypatch):
    # detect finds nothing (distro not mounted) — prefs still recovers the UNC home.
    unc = r"\\wsl.localhost\Ubuntu-24.04\home\me"
    monkeypatch.setattr(cli.connect, "detect_targets", lambda: [])
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "openclaw")
    monkeypatch.setattr(cli.prefs, "get_runtime_home", lambda: unc)
    pairs = cli._disconnect_pairs(None, None)
    assert pairs == [("openclaw", Path(unc))]


def test_disconnect_pairs_explicit_filters_both_sources(monkeypatch):
    monkeypatch.setattr(cli.connect, "detect_targets",
                        lambda: [connect.Target("hermes", "local",Path("C:/h")),
                                 connect.Target("openclaw", "wsl", Path("/o"), distro="U")])
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "openclaw")
    monkeypatch.setattr(cli.prefs, "get_runtime_home", lambda: "/o")
    pairs = cli._disconnect_pairs("hermes", None)
    assert pairs == [("hermes", Path("C:/h"))]  # openclaw (detect + prefs) filtered out


def test_disconnect_pairs_dest_override_single(monkeypatch):
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "hermes")
    pairs = cli._disconnect_pairs(None, Path("C:/explicit"))
    assert pairs == [("hermes", None)]  # dest drives uninstall; home is None


# ── _logout_session (the load-bearing #790 ordering) ──────────────────────────

class _RecFS:
    last = None

    def __init__(self, token_provider):
        _RecFS.last = self
        self.deleted = None

    def delete_agent_session(self, uid, sid):
        self.deleted = (uid, sid)


def _fake_sess(logged):
    return SimpleNamespace(uid="u1", id_token=lambda force=False: "tok",
                           logout=lambda: logged.__setitem__("v", True))


def test_logout_session_bridge_down_deletes_row_then_logs_out(monkeypatch):
    _RecFS.last = None
    logged = {"v": False}
    cleared = {"v": False}
    monkeypatch.setattr(cli, "_bridge_post", lambda *a, **k: None)  # bridge DOWN
    monkeypatch.setattr(cli.AccountSession, "load", staticmethod(lambda: _fake_sess(logged)))
    monkeypatch.setattr(cli, "FirestoreRest", _RecFS)
    monkeypatch.setattr(cli.prefs, "get_or_create_install_id", lambda: "iid-1")
    monkeypatch.setattr(cli.prefs, "clear_selected_device", lambda: cleared.__setitem__("v", True))
    assert cli._logout_session() is True
    assert _RecFS.last.deleted == ("u1", "iid-1")  # row deleted ourselves (bridge down)
    assert logged["v"] is True  # then token blanked (delete BEFORE logout)
    assert cleared["v"] is True


def test_logout_session_bridge_up_no_local_delete(monkeypatch):
    _RecFS.last = None
    logged = {"v": False}
    monkeypatch.setattr(cli, "_bridge_post", lambda *a, **k: (200, {"ok": True}))  # bridge UP
    monkeypatch.setattr(cli.AccountSession, "load", staticmethod(lambda: _fake_sess(logged)))
    monkeypatch.setattr(cli, "FirestoreRest", _RecFS)
    monkeypatch.setattr(cli.prefs, "clear_selected_device", lambda: None)
    # Bridge already deleted the row + cleared the store in its /logout handler.
    assert cli._logout_session() is True  # FIX: reports signed-out even though store now empty
    assert _RecFS.last is None  # we did NOT mint a token / delete locally
    assert logged["v"] is False  # bridge owns the logout when it's up


def test_logout_session_no_session_returns_false(monkeypatch):
    _RecFS.last = None
    monkeypatch.setattr(cli, "_bridge_post", lambda *a, **k: None)
    monkeypatch.setattr(cli.AccountSession, "load", staticmethod(lambda: None))
    monkeypatch.setattr(cli, "FirestoreRest", _RecFS)
    monkeypatch.setattr(cli.prefs, "clear_selected_device", lambda: None)
    assert cli._logout_session() is False
    assert _RecFS.last is None  # no token minted when nothing is signed in


# ── resurrect / retire / disconnect bodies ────────────────────────────────────

def test_cmd_resurrect_install_failure_returns_1(monkeypatch):
    monkeypatch.setattr(cli.autostart, "install", lambda: (False, "schtasks denied"))
    assert cli.cmd_resurrect(_ns()) == 1


def test_cmd_resurrect_success_returns_0_even_if_start_fails(monkeypatch):
    monkeypatch.setattr(cli.autostart, "install", lambda: (True, ""))
    monkeypatch.setattr(cli.autostart, "start_detached", lambda: (False, "boom"))
    assert cli.cmd_resurrect(_ns()) == 0  # pinned succeeded; immediate start is best-effort
    monkeypatch.setattr(cli.autostart, "start_detached", lambda: (True, ""))
    assert cli.cmd_resurrect(_ns()) == 0


def test_cmd_retire_no_task_is_clean(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_post", lambda *a, **k: None)  # nothing to stop
    monkeypatch.setattr(cli.autostart, "uninstall",
                        lambda: (False, "ERROR: The system cannot find the file specified."))
    assert cli.cmd_retire(_ns()) == 0  # 'cannot find' → no-task branch, not an error


def test_cmd_retire_success_and_other_error_both_return_0(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_post", lambda *a, **k: (200, {"ok": True}))
    monkeypatch.setattr(cli.autostart, "uninstall", lambda: (True, ""))
    assert cli.cmd_retire(_ns()) == 0
    monkeypatch.setattr(cli.autostart, "uninstall", lambda: (False, "access denied"))
    assert cli.cmd_retire(_ns()) == 0  # surfaces a warn but still returns 0


def test_cmd_disconnect_removes_skill_and_signs_out(monkeypatch):
    home = Path("C:/Users/me")
    removed = []
    monkeypatch.setattr(cli.connect, "detect_targets",
                        lambda: [connect.Target("hermes", "local",home)])
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "hermes")
    monkeypatch.setattr(cli.prefs, "get_runtime_home", lambda: str(home))
    monkeypatch.setattr(cli.connect, "uninstall",
                        lambda rt, **kw: (removed.append((rt, kw.get("home"))) or True))
    logged_out = {"v": False}
    monkeypatch.setattr(cli, "_logout_session", lambda: logged_out.__setitem__("v", True) or True)
    cleared = {"v": False}
    monkeypatch.setattr(cli.prefs, "clear_runtime", lambda: cleared.__setitem__("v", True))
    # nothing pinned/running → the optional bridge-teardown prompt is skipped
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: False)
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    assert cli.cmd_disconnect(_ns()) == 0
    assert removed == [("hermes", home)]  # step 1 removed the skill at the right home
    assert logged_out["v"] is True  # step 2 signed out
    assert cleared["v"] is True  # …and forgot the runtime → bare `agent` re-onboards


def test_cmd_disconnect_keeps_unrelated_runtime_pref(monkeypatch):
    # `disconnect openclaw` while HERMES is the recorded runtime must not forget
    # hermes — only the covered runtime is cleared.
    monkeypatch.setattr(cli.connect, "detect_targets", lambda: [])
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "hermes")
    monkeypatch.setattr(cli.prefs, "get_runtime_home", lambda: None)
    monkeypatch.setattr(cli.connect, "uninstall", lambda rt, **kw: False)
    monkeypatch.setattr(cli, "_logout_session", lambda: False)
    cleared = {"v": False}
    monkeypatch.setattr(cli.prefs, "clear_runtime", lambda: cleared.__setitem__("v", True))
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: False)
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    ns = SimpleNamespace(runtime="openclaw", dest=None, verbose=False)
    assert cli.cmd_disconnect(ns) == 0
    assert cleared["v"] is False  # hermes pref left intact


def _disconnect_teardown_fixture(monkeypatch):
    # Common stubs for the optional bridge-teardown prompt: skill/session/runtime
    # all no-ops, and SOMETHING is pinned so the prompt fires.
    monkeypatch.setattr(cli.connect, "detect_targets", lambda: [])
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: None)
    monkeypatch.setattr(cli.prefs, "get_runtime_home", lambda: None)
    monkeypatch.setattr(cli.connect, "uninstall", lambda rt, **kw: False)
    monkeypatch.setattr(cli, "_logout_session", lambda: False)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: True)  # something to tear down
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    retired = {"v": False}
    monkeypatch.setattr(cli, "_retire_bridge", lambda: retired.__setitem__("v", True))
    return retired


def test_cmd_disconnect_full_teardown_when_confirmed(monkeypatch):
    # Default-Yes prompt accepted → disconnect ALSO stops the bridge + unpins it.
    retired = _disconnect_teardown_fixture(monkeypatch)
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    assert cli.cmd_disconnect(_ns()) == 0
    assert retired["v"] is True


def test_cmd_disconnect_keeps_bridge_when_declined(monkeypatch):
    # Decline (or Ctrl-C, which confirm() maps to False) → bridge left running.
    retired = _disconnect_teardown_fixture(monkeypatch)
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)
    assert cli.cmd_disconnect(_ns()) == 0
    assert retired["v"] is False


def test_cmd_disconnect_skips_teardown_prompt_when_nothing_pinned(monkeypatch):
    # No autostart + no running bridge → never even ask about teardown.
    _disconnect_teardown_fixture(monkeypatch)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: False)
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    asked = {"v": False}
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: asked.__setitem__("v", True) or True)
    rv, out = _cap(cli.cmd_disconnect, _ns())
    assert rv == 0
    assert asked["v"] is False        # prompt skipped entirely
    assert "retire" not in out        # …and no stale 'retire' hint (nothing to retire)


def test_cmd_disconnect_next_omits_retire_after_teardown(monkeypatch):
    # Tore the bridge down → `retire` is done, so don't suggest it again.
    _disconnect_teardown_fixture(monkeypatch)
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    _, out = _cap(cli.cmd_disconnect, _ns())
    assert "retire" not in out


def test_cmd_disconnect_next_shows_retire_only_when_bridge_kept(monkeypatch):
    # Declined teardown → a running bridge was kept → `retire` is the follow-up.
    _disconnect_teardown_fixture(monkeypatch)
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)
    _, out = _cap(cli.cmd_disconnect, _ns())
    assert "retire" in out


# ── reachability: _ensure_reachable / _ensure_wsl_networking ──────────────────

def test_ensure_reachable_local_is_noop_ok(monkeypatch):
    # A co-located (local) runtime on a non-containerized host shares the bridge's
    # loopback — no WSL path, just the OK + an honest container caveat.
    calls = []
    monkeypatch.setattr(cli, "_ensure_wsl_networking", lambda: calls.append("wsl"))
    monkeypatch.setattr(cli.connect, "looks_containerized", lambda: False)
    _, out = _cap(cli._ensure_reachable, connect.Target("hermes", "local", Path("C:/Users/me")))
    assert calls == []
    assert "loopback" in out.lower()
    assert "container" in out.lower()  # honest caveat present, not a bare all-clear


def test_ensure_reachable_containerized_host_warns(monkeypatch):
    # If the bridge host itself looks containerized, don't promise loopback.
    monkeypatch.setattr(cli, "_ensure_wsl_networking", lambda: None)
    monkeypatch.setattr(cli.connect, "looks_containerized", lambda: True)
    _, out = _cap(cli._ensure_reachable, connect.Target("hermes", "local", Path("/root")))
    assert "container" in out.lower()
    assert "host networking" in out.lower() or "published port" in out.lower()


def test_ensure_reachable_wsl_delegates(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_ensure_wsl_networking", lambda: calls.append("wsl"))
    cli._ensure_reachable(connect.Target("openclaw", "wsl", Path("/o"), distro="U"))
    assert calls == ["wsl"]


def test_ensure_wsl_networking_already_on_skips_write(monkeypatch):
    monkeypatch.setattr(cli.connect, "mirrored_networking_enabled", lambda: True)
    wrote = []
    monkeypatch.setattr(cli.connect, "enable_mirrored_networking",
                        lambda *a, **k: wrote.append(1) or (True, Path("x")))
    cli._ensure_wsl_networking()
    assert wrote == []  # already mirrored → nothing to write, no restart nudge


def test_ensure_wsl_networking_decline_write_does_nothing(monkeypatch):
    monkeypatch.setattr(cli.connect, "mirrored_networking_enabled", lambda: False)
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {})
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)  # decline the write
    wrote = []
    monkeypatch.setattr(cli.connect, "enable_mirrored_networking",
                        lambda *a, **k: wrote.append(1) or (True, Path("x")))
    cli._ensure_wsl_networking()
    assert wrote == []


def test_ensure_wsl_networking_write_then_decline_restart(monkeypatch):
    monkeypatch.setattr(cli.connect, "mirrored_networking_enabled", lambda: False)
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {})
    answers = iter([True, False])  # Y write, N shutdown
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(cli.connect, "enable_mirrored_networking",
                        lambda *a, **k: (True, Path("C:/Users/me/.wslconfig")))
    shut = []
    monkeypatch.setattr(cli.connect, "wsl_shutdown", lambda: shut.append(1) or (True, ""))
    cli._ensure_wsl_networking()
    assert shut == []  # declined → we never shut WSL down out from under the user


def test_ensure_wsl_networking_write_then_accept_restart(monkeypatch):
    monkeypatch.setattr(cli.connect, "mirrored_networking_enabled", lambda: False)
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {})
    answers = iter([True, True])  # Y write, Y shutdown
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(cli.connect, "enable_mirrored_networking",
                        lambda *a, **k: (True, Path("C:/Users/me/.wslconfig")))
    shut = []
    monkeypatch.setattr(cli.connect, "wsl_shutdown", lambda: shut.append(1) or (True, ""))
    cli._ensure_wsl_networking()
    assert shut == [1]  # accepted → wsl --shutdown invoked


def test_ensure_wsl_networking_write_failure_is_handled(monkeypatch, capsys):
    # The OSError path (couldn't write .wslconfig) must degrade gracefully and
    # never reach the restart offer.
    monkeypatch.setattr(cli.connect, "mirrored_networking_enabled", lambda: False)
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {})
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)  # accept the write
    def _boom(*a, **k):
        raise OSError("Access is denied")
    monkeypatch.setattr(cli.connect, "enable_mirrored_networking", _boom)
    shut = []
    monkeypatch.setattr(cli.connect, "wsl_shutdown", lambda: shut.append(1) or (True, ""))
    cli._ensure_wsl_networking()
    assert "Couldn't write" in capsys.readouterr().out
    assert shut == []  # returned before offering the restart


def test_ensure_wsl_networking_shutdown_failure_is_handled(monkeypatch, capsys):
    monkeypatch.setattr(cli.connect, "mirrored_networking_enabled", lambda: False)
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {})
    answers = iter([True, True])  # Y write, Y shutdown
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(cli.connect, "enable_mirrored_networking",
                        lambda *a, **k: (True, Path("C:/Users/me/.wslconfig")))
    monkeypatch.setattr(cli.connect, "wsl_shutdown", lambda: (False, "wsl.exe not found"))
    cli._ensure_wsl_networking()
    assert "Couldn't run wsl --shutdown" in capsys.readouterr().out


def test_ensure_wsl_networking_already_configured_unapplied(monkeypatch, capsys):
    # enable_mirrored_networking can return changed=False (value already present) —
    # the message must say "Already set", not falsely claim a fresh enable.
    monkeypatch.setattr(cli.connect, "mirrored_networking_enabled", lambda: False)
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {})
    answers = iter([True, False])  # Y write, N shutdown
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(cli.connect, "enable_mirrored_networking",
                        lambda *a, **k: (False, Path("C:/Users/me/.wslconfig")))
    monkeypatch.setattr(cli.connect, "wsl_shutdown", lambda: (True, ""))
    cli._ensure_wsl_networking()
    assert "Already set" in capsys.readouterr().out


# _warn_shared_localhost — informed consent + the #225 port-squatter guard.

def test_warn_shared_localhost_flags_windows_port_squatters(monkeypatch):
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {3000: "37292"})
    _, out = _cap(cli._warn_shared_localhost)
    assert "shares localhost" in out.lower()      # informed consent
    assert "3000" in out and "37292" in out        # names the squatter + PID
    assert "tasklist" in out.lower()               # actionable identify hint


def test_warn_shared_localhost_clean_when_no_squatters(monkeypatch):
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {})
    _, out = _cap(cli._warn_shared_localhost)
    assert "shares localhost" in out.lower()       # still warns about the consequence
    assert "PID" not in out                        # but no squatter list


def test_ensure_wsl_networking_breadcrumb_on_enable(monkeypatch):
    # The post-restart diagnostic breadcrumb (netstat hint) must be emitted.
    monkeypatch.setattr(cli.connect, "mirrored_networking_enabled", lambda: False)
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {})
    answers = iter([True, False])  # Y write, N shutdown
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(cli.connect, "enable_mirrored_networking",
                        lambda *a, **k: (True, Path("C:/Users/me/.wslconfig")))
    _, out = _cap(cli._ensure_wsl_networking)
    assert "netstat -ano" in out and "findstr" in out


# ── cmd_status runtime-location rendering ─────────────────────────────────────
# (capture via redirect_stdout: capsys flakes on the branded multi-line header
#  output for some of these, while redirect_stdout captures it deterministically.)

def _status_out(monkeypatch, *, loc, distro="Ubuntu-24.04"):
    monkeypatch.setattr(cli, "_bridge_get", lambda *a, **k: None)  # bridge down (simplest)
    monkeypatch.setattr(cli.AccountSession, "load", staticmethod(lambda: None))
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "hermes")
    monkeypatch.setattr(cli.prefs, "get_runtime_location", lambda: loc)
    monkeypatch.setattr(cli.prefs, "get_runtime_distro", lambda: distro)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: False)
    monkeypatch.setattr(cli.connect, "host_os_label", lambda: "TestOS")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_status(_ns())
    return buf.getvalue()


def _runtime_line(out):
    return next(line for line in out.splitlines() if "Runtime:" in line)


def test_cmd_status_renders_wsl_location(monkeypatch):
    assert "Runtime: hermes · WSL · Ubuntu-24.04" in _status_out(monkeypatch, loc="wsl")


def test_cmd_status_renders_local_as_host(monkeypatch):
    line = _runtime_line(_status_out(monkeypatch, loc="local"))
    assert "hermes · TestOS" in line and "WSL" not in line


def test_cmd_status_renders_no_location(monkeypatch):
    line = _runtime_line(_status_out(monkeypatch, loc=None))
    assert "hermes" in line and "·" not in line  # no host/WSL suffix when unknown


# ── connect flow helpers ──────────────────────────────────────────────────────

def _t(runtime="hermes", loc="local", home=Path("C:/Users/me"), distro=None):
    return connect.Target(runtime, loc, home, distro)


def _cap(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rv = fn(*a, **k)
    return rv, buf.getvalue()


# _choose_target — single confirms, multiple pick + confirm, cancels.

def test_choose_target_single_confirms(monkeypatch):
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    t = _t()
    assert cli._choose_target([t]) is t


def test_choose_target_single_decline_cancels(monkeypatch):
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)
    assert cli._choose_target([_t()]) is None


def test_choose_target_multiple_pick_then_confirm(monkeypatch):
    monkeypatch.setattr(cli.b, "ask", lambda *a, **k: "2")
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    first, second = _t("hermes"), _t("openclaw", "wsl", Path("/o"), "U")
    assert cli._choose_target([first, second]) is second


def test_choose_target_interrupt_cancels(monkeypatch):
    monkeypatch.setattr(cli.b, "ask", lambda *a, **k: None)  # Ctrl-C / EOF
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    assert cli._choose_target([_t("hermes"), _t("openclaw")]) is None


def test_choose_target_out_of_range_cancels(monkeypatch):
    monkeypatch.setattr(cli.b, "ask", lambda *a, **k: "9")
    assert cli._choose_target([_t("hermes"), _t("openclaw")]) is None


# _install_step — fresh install, decline-when-absent aborts, keep-existing.

def test_install_step_fresh_install(monkeypatch):
    seq = iter([False, True])  # not present, then verified after install
    monkeypatch.setattr(cli.connect, "verify", lambda p: next(seq))
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(cli.connect, "install", lambda rt, **kw: Path("C:/dest"))
    monkeypatch.setattr(cli, "_record_runtime", lambda c: None)
    assert cli._install_step(_t(), None) == Path("C:/dest")


def test_install_step_decline_when_absent_aborts(monkeypatch):
    monkeypatch.setattr(cli.connect, "verify", lambda p: False)
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)  # decline install
    called = []
    monkeypatch.setattr(cli.connect, "install", lambda *a, **k: called.append(1))
    assert cli._install_step(_t(), None) is None
    assert called == []  # never installed


def test_install_step_already_installed_keep(monkeypatch):
    monkeypatch.setattr(cli.connect, "verify", lambda p: True)
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)  # don't reinstall
    monkeypatch.setattr(cli, "_record_runtime", lambda c: None)
    t = _t()
    assert cli._install_step(t, None) == t.dest


# _startup_step — Windows-only guard (cross-platform), pin, decline, pin-fail.

def test_startup_step_unsupported_os_is_graceful(monkeypatch):
    monkeypatch.setattr(cli.autostart, "supported", lambda: False)
    installed = []
    monkeypatch.setattr(cli.autostart, "install", lambda: installed.append(1) or (True, ""))
    rv, out = _cap(cli._startup_step)
    assert rv is False
    assert installed == []          # never attempts to pin on an unsupported OS
    assert "isn't available" in out and "agent serve" in out


def test_startup_step_pins_when_supported(monkeypatch):
    monkeypatch.setattr(cli.autostart, "supported", lambda: True)
    monkeypatch.setattr(cli.autostart, "kind_label", lambda: "systemd --user service")
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(cli.autostart, "install", lambda: (True, ""))
    monkeypatch.setattr(cli.autostart, "start_detached", lambda: (True, ""))
    assert cli._startup_step() is True


def test_startup_step_decline(monkeypatch):
    monkeypatch.setattr(cli.autostart, "supported", lambda: True)
    monkeypatch.setattr(cli.autostart, "kind_label", lambda: "Scheduled Task")
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)
    assert cli._startup_step() is False


def test_startup_step_pin_failure(monkeypatch):
    monkeypatch.setattr(cli.autostart, "supported", lambda: True)
    monkeypatch.setattr(cli.autostart, "kind_label", lambda: "Scheduled Task")
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(cli.autostart, "install", lambda: (False, "schtasks denied"))
    assert cli._startup_step() is False


# _signin_step — bridge-down, decline, web-app sign-in (delegates to _remote_signin).

def test_signin_step_bridge_down(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    rv, out = _cap(cli._signin_step)
    assert rv is False and "start it first" in out.lower()


def test_signin_step_decline(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: False)
    monkeypatch.setattr(cli, "_remote_signin", lambda **k: "connected")  # must NOT be reached
    assert cli._signin_step() is False


def test_signin_step_connected_via_web_app(monkeypatch):
    # Step 4 now uses the SR web app (superresearch.io) flow, not the local page.
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    called = []
    monkeypatch.setattr(cli, "_remote_signin", lambda **k: called.append(k) or "connected")
    assert cli._signin_step() is True
    assert called and called[0].get("open_browser") is True


def test_signin_step_not_connected_returns_false(monkeypatch):
    # If the web sign-in doesn't complete (timeout/cancel/start-failed) → False
    # (so the closing card honestly shows 'login', not 'logout').
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(cli, "_remote_signin", lambda **k: "timeout")
    assert cli._signin_step() is False


# _connect_next — terminal vs chat split, varied by login + startup state.

def test_connect_next_logged_in_and_pinned(monkeypatch):
    groups = cli._connect_next(logged_in=True, startup_pinned=True)
    assert [lbl for lbl, _ in groups] == ["in this terminal", "in your chat (Hermes / OpenClaw)"]
    term = [c for c, _ in groups[0][1]]
    chat = [c for c, _ in groups[1][1]]
    assert any(c.endswith("agent logout") for c in term)      # switch account
    assert not any(c.endswith("agent login") for c in term)
    assert not any("serve" in c or "resurrect" in c for c in term)  # already pinned
    assert any(c.endswith("--help") for c in term)            # help always
    assert "/reload-skills" in chat                           # register the skill
    assert "/sr" in chat                                       # single-command entry
    assert "/sr login" not in chat                            # already signed in


def test_connect_next_fresh_and_unpinned(monkeypatch):
    groups = cli._connect_next(logged_in=False, startup_pinned=False)
    term = [c for c, _ in groups[0][1]]
    chat = [c for c, _ in groups[1][1]]
    assert any(c.endswith("agent login") for c in term)
    assert not any(c.endswith("agent logout") for c in term)
    assert any("serve" in c for c in term) and any("resurrect" in c for c in term)
    assert any(c.endswith("--help") for c in term)            # help always
    assert "/reload-skills" in chat and "/sr login" in chat and "/sr" in chat


# Cross-platform reachability: a co-located (local) runtime on a non-Windows host
# needs no setup and must NOT touch any WSL machinery.

def test_ensure_reachable_local_on_linux(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "linux")
    monkeypatch.setattr(connect, "host_os_label", lambda: "Linux")
    monkeypatch.setattr(cli.connect, "looks_containerized", lambda: False)
    wsl = []
    monkeypatch.setattr(cli, "_ensure_wsl_networking", lambda: wsl.append(1))
    _, out = _cap(cli._ensure_reachable, connect.Target("hermes", "local", Path("/home/x")))
    assert wsl == [] and "loopback" in out.lower()


def test_bridge_up_requires_version_marker(monkeypatch):
    # Only a /healthz body carrying the bridge marker counts as "up".
    monkeypatch.setattr(cli, "_bridge_get", lambda p, **k: (200, {"ok": True, "version": "1"}))
    assert cli._bridge_up() is True
    monkeypatch.setattr(cli, "_bridge_get", lambda p, **k: (200, {"hello": "i am not a bridge"}))
    assert cli._bridge_up() is False   # foreign HTTP server on :9876 is NOT the bridge
    monkeypatch.setattr(cli, "_bridge_get", lambda p, **k: None)
    assert cli._bridge_up() is False


def test_warn_shared_localhost_flags_bridge_own_port(monkeypatch):
    # The bridge's own port (config.BRIDGE_PORT) is now scanned + specially tagged.
    monkeypatch.setattr(cli.connect, "windows_port_owners", lambda *a, **k: {cli.config.BRIDGE_PORT: "55"})
    _, out = _cap(cli._warn_shared_localhost)
    assert str(cli.config.BRIDGE_PORT) in out and "the bridge's own port" in out


# _bridge_authed — the closing card's 'logged_in' must reflect REAL auth, not
# 'a browser was opened'.

def test_bridge_authed_true(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_get", lambda p, **k: (200, {"authed": True, "email": "me@x"}))
    assert cli._bridge_authed() is True


def test_bridge_authed_false_when_not_signed_in(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_get", lambda p, **k: (200, {"authed": False}))
    assert cli._bridge_authed() is False


def test_bridge_authed_false_when_bridge_down(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_get", lambda p, **k: None)
    assert cli._bridge_authed() is False


# ── cmd_home (bare `agent` / `--agent` smart entry) ───────────────────────────

def _route_home(monkeypatch):
    routed = []
    monkeypatch.setattr(cli, "cmd_status", lambda args: routed.append("status") or 0)
    monkeypatch.setattr(cli, "cmd_connect", lambda args: routed.append("connect") or 0)
    return routed


def test_cmd_home_when_runtime_connected_shows_status(monkeypatch):
    # A connected chat runtime = set up → status (even before signing in).
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "hermes")
    monkeypatch.setattr(cli, "_bridge_authed", lambda: False)
    routed = _route_home(monkeypatch)
    assert cli.cmd_home(_ns()) == 0
    assert routed == ["status"]


def test_cmd_home_when_signed_in_shows_status(monkeypatch):
    # Signed in but no runtime recorded (e.g. CLI-only `agent login`) → still status.
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: None)
    monkeypatch.setattr(cli, "_bridge_authed", lambda: True)
    routed = _route_home(monkeypatch)
    assert cli.cmd_home(_ns()) == 0
    assert routed == ["status"]


def test_cmd_home_idle_bridge_no_runtime_runs_connect(monkeypatch):
    # The post-`disconnect` case: the background bridge is still UP, but with no
    # runtime + no session it's idle → onboard via connect, don't park on status.
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: None)
    monkeypatch.setattr(cli, "_bridge_authed", lambda: False)
    routed = _route_home(monkeypatch)
    ns = SimpleNamespace(verbose=False)  # bare namespace lacks runtime/dest
    assert cli.cmd_home(ns) == 0
    assert routed == ["connect"]


def test_cmd_home_when_fresh_runs_connect(monkeypatch):
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: None)  # nothing connected yet
    monkeypatch.setattr(cli, "_bridge_authed", lambda: False)    # bridge down / not signed in
    routed = _route_home(monkeypatch)
    ns = SimpleNamespace(verbose=False)  # bare namespace lacks runtime/dest
    assert cli.cmd_home(ns) == 0
    assert routed == ["connect"]
    assert ns.runtime is None and ns.dest is None  # cmd_home supplied the omitted defaults
