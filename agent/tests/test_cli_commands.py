"""Command-body + helper tests for the agent CLI: _disconnect_pairs (teardown
orchestration), _logout_session (the #790 bridge-down agent-row deletion), and
the resurrect/retire/disconnect bodies (incl. retire's no-task string heuristic).

All deps are module-level imports in facade.cli, so everything is monkeypatched
in-place — no HTTP server, no real runtime dirs, no schtasks.
"""

from pathlib import Path
from types import SimpleNamespace

from facade import cli, connect


def _ns(**kw):
    return SimpleNamespace(runtime=None, dest=None, verbose=False, **kw)


# ── _disconnect_pairs ─────────────────────────────────────────────────────────

def test_disconnect_pairs_dedups_detect_and_prefs(monkeypatch):
    home = Path("C:/Users/me")
    monkeypatch.setattr(cli.connect, "detect_targets",
                        lambda: [connect.Target("hermes", "windows", home)])
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
                        lambda: [connect.Target("hermes", "windows", Path("C:/h")),
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
                        lambda: [connect.Target("hermes", "windows", home)])
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "hermes")
    monkeypatch.setattr(cli.prefs, "get_runtime_home", lambda: str(home))
    monkeypatch.setattr(cli.connect, "uninstall",
                        lambda rt, **kw: (removed.append((rt, kw.get("home"))) or True))
    logged_out = {"v": False}
    monkeypatch.setattr(cli, "_logout_session", lambda: logged_out.__setitem__("v", True) or True)
    assert cli.cmd_disconnect(_ns()) == 0
    assert removed == [("hermes", home)]  # step 1 removed the skill at the right home
    assert logged_out["v"] is True  # step 2 signed out
