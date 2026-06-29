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

import pytest

from facade import cli, connect


@pytest.fixture(autouse=True)
def _no_wsl_by_default(monkeypatch):
    """Default runtime detection to 'nothing here' so command tests take the LOCAL
    path. The WSL delegation calls connect.detect_targets(), which on a real
    Windows dev box finds the actual WSL Hermes and would delegate into it —
    tests that exercise WSL detection/delegation override this explicitly."""
    monkeypatch.setattr(cli.connect, "detect_targets", lambda *a, **k: [])
    # The unreachable-WSL guard also probes installed/running distros directly —
    # default both to 'no WSL at all' so the local path stays clean.
    monkeypatch.setattr(cli.connect, "wsl_distros", lambda *a, **k: [])
    monkeypatch.setattr(cli.connect, "wsl_running_distros", lambda *a, **k: [])


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
    monkeypatch.setattr(cli, "_wait_bridge_up", lambda *a, **k: True)
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
    # Default to a real terminal so the bridge-teardown PROMPT path runs (the tests
    # below mock b.confirm). The non-TTY / --yes auto-teardown has its own test.
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
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


def test_cmd_disconnect_yes_auto_tears_down_bridge(monkeypatch):
    # Non-interactive (--yes, e.g. chat-driven "remove Super Research"): stop the
    # bridge WITHOUT prompting, so a chat disconnect actually takes the bridge down.
    retired = _disconnect_teardown_fixture(monkeypatch)
    asked = {"v": False}
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: asked.__setitem__("v", True) or False)
    _, out = _cap(cli.cmd_disconnect, _ns(yes=True))
    assert asked["v"] is False        # never prompted
    assert retired["v"] is True       # bridge torn down anyway (full teardown)
    assert "retire" not in out        # nothing left to retire


# ── reachability: _ensure_reachable (co-located only; WSL is delegated) ───────

def test_ensure_reachable_local_is_noop_ok(monkeypatch):
    # A co-located (local) runtime on a non-containerized host shares the bridge's
    # loopback — just the OK + an honest container caveat.
    monkeypatch.setattr(cli.connect, "looks_containerized", lambda: False)
    _, out = _cap(cli._ensure_reachable, connect.Target("hermes", "local", Path("C:/Users/me")))
    assert "loopback" in out.lower()
    assert "container" in out.lower()  # honest caveat present, not a bare all-clear


def test_ensure_reachable_containerized_host_warns(monkeypatch):
    # If the bridge host itself looks containerized, don't promise loopback.
    monkeypatch.setattr(cli.connect, "looks_containerized", lambda: True)
    _, out = _cap(cli._ensure_reachable, connect.Target("hermes", "local", Path("/root")))
    assert "container" in out.lower()
    assert "host networking" in out.lower() or "published port" in out.lower()


# ── WSL delegation: _connect_wsl_runtime (Model A — connect runs in the distro) ─

def _wsl_target(distro="Ubuntu-24.04"):
    return connect.Target("hermes", "wsl", Path("/home/u"), distro=distro)


def test_connect_wsl_assume_yes_runs_in_distro(monkeypatch):
    monkeypatch.setattr(cli.connect, "wsl_pipx_available", lambda d: True)
    ran = {}
    monkeypatch.setattr(cli.connect, "run_agent_in_wsl",
                        lambda d, sub, extra=None: ran.update(distro=d, extra=extra) or 0)
    rc = cli._connect_wsl_runtime(_wsl_target(), assume_yes=True, noninteractive=True,
                                  startup=None, login=None)
    assert rc == 0
    # pre-selects the runtime; the continuation marker rides the env var (set by
    # run_agent_in_wsl), so it's NOT a forwarded flag (version-safe).
    assert ran == {"distro": "Ubuntu-24.04", "extra": ["--runtime", "hermes", "--yes"]}


def test_connect_wsl_forwards_startup_login_flags(monkeypatch):
    monkeypatch.setattr(cli.connect, "wsl_pipx_available", lambda d: True)
    ran = {}
    monkeypatch.setattr(cli.connect, "run_agent_in_wsl",
                        lambda d, sub, extra=None: ran.update(extra=extra) or 0)
    cli._connect_wsl_runtime(_wsl_target(), assume_yes=True, noninteractive=True,
                             startup=False, login=True)
    assert ran["extra"] == ["--runtime", "hermes", "--yes", "--no-startup", "--login"]


def test_connect_wsl_interactive_auto_proceeds_no_prompt(monkeypatch):
    # No "Run connect inside WSL?" prompt anymore — choosing the WSL runtime IS
    # the consent, so an interactive (TTY, no --yes) hand-off runs automatically.
    monkeypatch.setattr(cli.connect, "wsl_pipx_available", lambda d: True)
    monkeypatch.setattr(cli.b, "confirm",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not prompt")))
    ran = {}
    monkeypatch.setattr(cli.connect, "run_agent_in_wsl",
                        lambda d, sub, extra=None: ran.update(distro=d, extra=extra) or 0)
    rc = cli._connect_wsl_runtime(_wsl_target(), assume_yes=False, noninteractive=False,
                                  startup=None, login=None)
    assert rc == 0
    assert ran["distro"] == "Ubuntu-24.04"
    assert ran["extra"] == ["--runtime", "hermes"]   # interactive → no --yes; continuation via env


def test_connect_wsl_pipx_bootstrap_fails_falls_back_to_manual(monkeypatch, capsys):
    # pipx missing AND the autonomous install can't finish → manual fallback.
    monkeypatch.setattr(cli.connect, "wsl_pipx_available", lambda d: False)  # pipx missing
    monkeypatch.setattr(cli.connect, "ensure_wsl_pipx", lambda d: False)     # can't install it
    ran = []
    monkeypatch.setattr(cli.connect, "run_agent_in_wsl", lambda *a, **k: ran.append(1) or 0)
    rc = cli._connect_wsl_runtime(_wsl_target(), assume_yes=True, noninteractive=True,
                                  startup=None, login=None)
    out = capsys.readouterr().out
    assert rc == 0 and ran == []                        # didn't attempt the in-WSL run
    assert "Couldn't install pipx" in out
    assert "research.py agent connect" in out           # backend-checkout fallback


def test_connect_wsl_bootstraps_pipx_then_runs(monkeypatch):
    # pipx absent but the autonomous bootstrap installs it → proceed with the in-WSL run.
    monkeypatch.setattr(cli.connect, "wsl_pipx_available", lambda d: False)
    bootstrapped = []
    monkeypatch.setattr(cli.connect, "ensure_wsl_pipx",
                        lambda d: bootstrapped.append(d) or True)
    ran = {}
    monkeypatch.setattr(cli.connect, "run_agent_in_wsl",
                        lambda d, sub, extra=None: ran.update(distro=d, sub=sub) or 0)
    rc = cli._connect_wsl_runtime(_wsl_target(), assume_yes=True, noninteractive=True,
                                  startup=None, login=None)
    assert rc == 0
    assert bootstrapped == ["Ubuntu-24.04"]          # tried to install pipx in the distro
    assert ran == {"distro": "Ubuntu-24.04", "sub": "connect"}


def test_connect_wsl_nonzero_rc_shows_fallback(monkeypatch, capsys):
    monkeypatch.setattr(cli.connect, "wsl_pipx_available", lambda d: True)
    monkeypatch.setattr(cli.connect, "run_agent_in_wsl", lambda *a, **k: 3)  # didn't finish
    rc = cli._connect_wsl_runtime(_wsl_target(), assume_yes=True, noninteractive=True,
                                  startup=None, login=None)
    out = capsys.readouterr().out
    assert rc == 3
    assert "didn't finish" in out
    assert "pipx run superresearch-agent connect" in out     # fallback printed


def test_connect_wsl_noninteractive_without_yes_prints_manual(monkeypatch, capsys):
    # Non-TTY and no --yes → no channel to consent to running in WSL → print it.
    monkeypatch.setattr(cli.connect, "wsl_pipx_available", lambda d: True)
    ran = []
    monkeypatch.setattr(cli.connect, "run_agent_in_wsl", lambda *a, **k: ran.append(1) or 0)
    rc = cli._connect_wsl_runtime(_wsl_target(), assume_yes=False, noninteractive=True,
                                  startup=None, login=None)
    assert rc == 0 and ran == []
    assert "pipx run superresearch-agent connect" in capsys.readouterr().out


# ── lifecycle/query delegation to WSL (Option A — symmetric with connect) ─────

def test_wsl_distro_for_returns_distro_when_only_wsl(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.connect, "detect_targets",
                        lambda: [connect.Target("hermes", "wsl", Path("/h"), distro="Ubuntu-24.04")])
    assert cli._wsl_distro_for() == "Ubuntu-24.04"


def test_wsl_distro_for_none_when_local_also_present(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.connect, "detect_targets", lambda: [
        connect.Target("hermes", "wsl", Path("/h"), distro="U"),
        connect.Target("hermes", "local", Path("C:/x")),
    ])
    assert cli._wsl_distro_for() is None  # a co-located one exists → act locally


def test_wsl_distro_for_off_windows(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli.connect, "detect_targets",
                        lambda: [connect.Target("hermes", "wsl", Path("/h"), distro="U")])
    assert cli._wsl_distro_for() is None


def test_delegate_lifecycle_runs_in_wsl(monkeypatch):
    monkeypatch.setattr(cli, "_wsl_distro_for", lambda explicit=None: "Ubuntu-24.04")
    monkeypatch.setattr(cli.connect, "wsl_pipx_available", lambda d: True)
    seen = {}
    monkeypatch.setattr(cli.connect, "run_agent_in_wsl",
                        lambda d, sub, extra=None: seen.update(distro=d, sub=sub, extra=extra) or 0)
    rc = cli._delegate_lifecycle("retire", [], label="Retire")
    assert rc == 0 and seen == {"distro": "Ubuntu-24.04", "sub": "retire", "extra": []}


def test_delegate_lifecycle_none_when_co_located(monkeypatch):
    monkeypatch.setattr(cli, "_wsl_distro_for", lambda explicit=None: None)
    assert cli._delegate_lifecycle("retire", [], label="Retire") is None


def test_delegate_lifecycle_refuses_when_pipx_missing(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_wsl_distro_for", lambda explicit=None: "U")
    monkeypatch.setattr(cli.connect, "wsl_pipx_available", lambda d: False)
    ran = []
    monkeypatch.setattr(cli.connect, "run_agent_in_wsl", lambda *a, **k: ran.append(1) or 0)
    rc = cli._delegate_lifecycle("retire", [], label="Retire")
    assert rc == 1 and ran == []  # neither delegated nor silently ran locally
    assert "pipx isn't installed" in capsys.readouterr().out


def test_redirect_if_wsl_redirects_when_no_local_bridge(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    monkeypatch.setattr(cli, "_wsl_distro_for", lambda explicit=None: "Ubuntu-24.04")
    assert cli._redirect_if_wsl("Sign in from chat:  /sr login") == 0
    out = capsys.readouterr().out
    assert "WSL · Ubuntu-24.04" in out and "/sr login" in out


def test_redirect_if_wsl_none_when_local_bridge_up(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    assert cli._redirect_if_wsl("x") is None


# ── unreachable (stopped) WSL guard ───────────────────────────────────────────

def test_unreachable_wsl_distros_lists_stopped_when_nothing_reachable(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.connect, "detect_targets", lambda: [])
    monkeypatch.setattr(cli.connect, "wsl_distros", lambda: ["Ubuntu-24.04", "kali"])
    monkeypatch.setattr(cli.connect, "wsl_running_distros", lambda: ["kali"])
    assert cli._unreachable_wsl_distros() == ["Ubuntu-24.04"]  # stopped one we couldn't inspect


def test_unreachable_wsl_distros_empty_when_a_runtime_is_reachable(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.connect, "detect_targets",
                        lambda: [connect.Target("hermes", "local", Path("C:/x"))])
    monkeypatch.setattr(cli.connect, "wsl_distros", lambda: ["Ubuntu-24.04"])
    monkeypatch.setattr(cli.connect, "wsl_running_distros", lambda: [])
    assert cli._unreachable_wsl_distros() == []  # don't warn — we found something


def test_unreachable_wsl_distros_empty_when_all_running(monkeypatch):
    # A running distro WAS inspected (and found empty) → not "couldn't look".
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.connect, "detect_targets", lambda: [])
    monkeypatch.setattr(cli.connect, "wsl_distros", lambda: ["Ubuntu-24.04"])
    monkeypatch.setattr(cli.connect, "wsl_running_distros", lambda: ["Ubuntu-24.04"])
    assert cli._unreachable_wsl_distros() == []


def test_delegate_lifecycle_warns_on_stopped_wsl(monkeypatch, capsys):
    # No WSL runtime detected, but a stopped distro could be hiding it → block with
    # a clear message rather than silently no-op'ing locally.
    monkeypatch.setattr(cli, "_wsl_distro_for", lambda explicit=None: None)
    monkeypatch.setattr(cli, "_unreachable_wsl_distros", lambda: ["Ubuntu-24.04"])
    rc = cli._delegate_lifecycle("disconnect", [], label="Disconnect")
    assert rc == 1
    out = capsys.readouterr().out
    assert "stopped" in out and "Ubuntu-24.04" in out


def test_delegate_lifecycle_proceeds_local_when_no_wsl_at_all(monkeypatch):
    monkeypatch.setattr(cli, "_wsl_distro_for", lambda explicit=None: None)
    monkeypatch.setattr(cli, "_unreachable_wsl_distros", lambda: [])
    assert cli._delegate_lifecycle("disconnect", [], label="Disconnect") is None


def test_redirect_if_wsl_warns_on_stopped_wsl(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    monkeypatch.setattr(cli, "_wsl_distro_for", lambda explicit=None: None)
    monkeypatch.setattr(cli, "_unreachable_wsl_distros", lambda: ["Ubuntu-24.04"])
    assert cli._redirect_if_wsl("Sign in from chat:  /sr login") == 0
    assert "stopped" in capsys.readouterr().out


def test_cmd_retire_delegates_to_wsl(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_delegate_lifecycle", lambda sub, extra, **k: seen.update(sub=sub) or 0)
    monkeypatch.setattr(cli, "_retire_bridge",
                        lambda: (_ for _ in ()).throw(AssertionError("must not retire locally when delegated")))
    assert cli.cmd_retire(cli.build_parser().parse_args(["retire"])) == 0
    assert seen["sub"] == "retire"


def test_cmd_connect_routes_wsl_target_to_delegation(monkeypatch):
    # cmd_connect must hand a chosen WSL target to _connect_wsl_runtime and NOT
    # install on Windows.
    monkeypatch.setattr(cli.connect, "detect_targets", lambda: [_wsl_target()])
    monkeypatch.setattr(cli, "_choose_target", lambda targets, **k: targets[0])
    captured = {}
    monkeypatch.setattr(cli, "_connect_wsl_runtime",
                        lambda target, **k: captured.update(target=target, **k) or 0)

    def _no_install(*a, **k):
        raise AssertionError("must not install on Windows for a WSL target")

    monkeypatch.setattr(cli, "_install_step", _no_install)
    args = cli.build_parser().parse_args(["connect", "--runtime", "hermes", "--yes"])
    assert cli.cmd_connect(args) == 0
    assert captured["target"].location == "wsl"


def test_cmd_connect_continued_suppresses_banner_and_autoselects(monkeypatch):
    # The in-WSL continuation (CONTINUED env var): no banner, and it auto-selects
    # the explicit runtime (no re-detect/choose prompt), resuming at Install.
    monkeypatch.setenv(connect.CONTINUED_ENV, "1")
    monkeypatch.setattr(cli.connect, "detect_targets",
                        lambda: [connect.Target("hermes", "local", Path("/home/u"))])
    monkeypatch.setattr(cli.b, "header",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("banner must be suppressed")))
    monkeypatch.setattr(cli, "_choose_target",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not re-choose")))
    seen = {}
    monkeypatch.setattr(cli, "_install_step",
                        lambda chosen, dest, **k: seen.update(installed=chosen.runtime) or Path("/x"))
    monkeypatch.setattr(cli, "_ensure_reachable", lambda t: None)
    monkeypatch.setattr(cli, "_startup_step", lambda **k: False)
    monkeypatch.setattr(cli, "_signin_step", lambda **k: False)
    monkeypatch.setattr(cli, "_bridge_authed", lambda: False)
    args = cli.build_parser().parse_args(["connect", "--runtime", "hermes"])
    assert cli.cmd_connect(args) == 0
    assert seen["installed"] == "hermes"   # auto-selected + installed, no banner/choose


def test_install_is_alias_for_connect():
    # An agent asked to "install superresearch" reaches cmd_connect via the alias.
    args = cli.build_parser().parse_args(["install", "--runtime", "hermes"])
    assert args.func is cli.cmd_connect


def test_connect_non_tty_proceeds_with_defaults(monkeypatch, capsys):
    # A chat exec (no TTY, no --yes) must NOT route step prompts to b.confirm/EOF —
    # it proceeds with the install defaults and DEFERS sign-in: it must NOT start
    # sign-in or print a link here (that's the separate `/sr login` step, after
    # /reload-skills), just point the user at /reload-skills → /sr login.
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli.connect, "detect_targets",
                        lambda: [connect.Target("hermes", "local", Path("/home/u"))])
    monkeypatch.setattr(cli.b, "header", lambda *a, **k: None)
    monkeypatch.setattr(cli.b, "confirm",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not prompt in a non-TTY exec")))
    monkeypatch.setattr(cli.b, "ask",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not prompt in a non-TTY exec")))
    seen = {}
    monkeypatch.setattr(cli, "_install_step",
                        lambda chosen, dest, *, assume_yes: seen.update(installed=chosen.runtime, ay=assume_yes) or Path("/x"))
    monkeypatch.setattr(cli, "_ensure_reachable", lambda t: None)
    monkeypatch.setattr(cli, "_startup_step", lambda **k: seen.update(startup_ay=k.get("assume_yes")) or True)
    monkeypatch.setattr(cli, "_signin_step",
                        lambda **k: seen.update(signin_ni=k.get("noninteractive")) or False)
    monkeypatch.setattr(cli, "_bridge_authed", lambda: False)
    args = cli.build_parser().parse_args(["connect"])  # no --yes, no --runtime
    assert cli.cmd_connect(args) == 0
    assert seen["installed"] == "hermes"
    assert seen["ay"] is True and seen["startup_ay"] is True   # defaults assumed
    assert "signin_ni" not in seen                              # sign-in DEFERRED, no link in chat
    out = capsys.readouterr().out
    assert "/reload-skills" in out and "/sr login" in out       # the two-step next line
    assert "Sign in here" not in out                            # the link is NOT shown here


# ── cmd_status runtime-location rendering ─────────────────────────────────────
# (capture via redirect_stdout: capsys flakes on the branded multi-line header
#  output for some of these, while redirect_stdout captures it deterministically.)

def _status_out(monkeypatch, *, loc):
    monkeypatch.setattr(cli, "_bridge_get", lambda *a, **k: None)  # bridge down (simplest)
    monkeypatch.setattr(cli.AccountSession, "load", staticmethod(lambda: None))
    monkeypatch.setattr(cli.prefs, "get_runtime", lambda: "hermes")
    monkeypatch.setattr(cli.prefs, "get_runtime_location", lambda: loc)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: False)
    monkeypatch.setattr(cli.connect, "host_os_label", lambda: "TestOS")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_status(_ns())
    return buf.getvalue()


def _runtime_line(out):
    return next(line for line in out.splitlines() if "Runtime:" in line)


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
    monkeypatch.setattr(cli, "_wait_bridge_up", lambda *a, **k: True)  # bound promptly
    rv, out = _cap(cli._startup_step)
    assert rv is True
    assert "started in the background" in out


def test_startup_step_started_but_not_answering_warns(monkeypatch):
    # Pinned + launched, but the socket isn't listening yet → honest warning, not a
    # false "started" (and crucially not a silent claim the next step then refutes).
    monkeypatch.setattr(cli.autostart, "supported", lambda: True)
    monkeypatch.setattr(cli.autostart, "kind_label", lambda: "Scheduled Task")
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(cli.autostart, "install", lambda: (True, ""))
    monkeypatch.setattr(cli.autostart, "start_detached", lambda: (True, ""))
    monkeypatch.setattr(cli, "_wait_bridge_up", lambda *a, **k: False)  # didn't bind in time
    rv, out = _cap(cli._startup_step)
    assert rv is True
    assert "not answering" in out.lower()


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


# ── non-interactive connect: --yes / --runtime / --startup / --login (Phase 2) ──

def test_decide_explicit_flag_wins_over_assume_yes(monkeypatch):
    # An explicit --no-X (False) must win even under --yes; confirm never consulted.
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    assert cli._decide(False, True, "x") is False
    assert cli._decide(True, False, "x") is True


def test_decide_assume_yes_skips_prompt(monkeypatch):
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    assert cli._decide(None, True, "x") is True


def test_decide_falls_through_to_confirm(monkeypatch):
    seen = []
    monkeypatch.setattr(cli.b, "confirm", lambda p, default=True: seen.append((p, default)) or True)
    assert cli._decide(None, False, "Proceed?", default=False) is True
    assert seen == [("Proceed?", False)]


def test_choose_target_assume_yes_single_skips_confirm(monkeypatch):
    # assume_yes auto-confirms a single target — confirm must NOT be reached.
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    t = _t()
    assert cli._choose_target([t], assume_yes=True) is t


def test_choose_target_assume_yes_multiple_refuses(monkeypatch):
    # Can't disambiguate >1 runtime non-interactively → refuse, tell them --runtime.
    rv, out = _cap(cli._choose_target, [_t("hermes"), _t("openclaw")], assume_yes=True)
    assert rv is None
    assert "--runtime" in out


def test_install_step_assume_yes_installs_without_prompt(monkeypatch):
    seq = iter([False, True])  # absent, then verified after install
    monkeypatch.setattr(cli.connect, "verify", lambda p: next(seq))
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    monkeypatch.setattr(cli.connect, "install", lambda rt, **kw: Path("C:/dest"))
    monkeypatch.setattr(cli, "_record_runtime", lambda c: None)
    assert cli._install_step(_t(), None, assume_yes=True) == Path("C:/dest")


def test_startup_step_explicit_false_skips(monkeypatch):
    # --no-startup → skip without asking, even on a supported OS.
    monkeypatch.setattr(cli.autostart, "supported", lambda: True)
    monkeypatch.setattr(cli.autostart, "kind_label", lambda: "Scheduled Task")
    monkeypatch.setattr(cli.b, "confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    installed = []
    monkeypatch.setattr(cli.autostart, "install", lambda: installed.append(1) or (True, ""))
    assert cli._startup_step(explicit=False) is False
    assert installed == []


def test_signin_step_noninteractive_relays_link(monkeypatch):
    # Chat exec: relay the link (no host browser, no block-poll) → not yet signed in.
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    called = []
    monkeypatch.setattr(cli, "_remote_signin", lambda **k: called.append(k) or "started")
    assert cli._signin_step(assume_yes=True, noninteractive=True) is False
    assert called[0].get("open_browser") is False and called[0].get("poll") is False


def test_connect_flags_parse():
    a = cli.build_parser().parse_args(
        ["connect", "--runtime", "hermes", "--yes", "--startup", "--login"])
    assert a.runtime_opt == "hermes" and a.yes is True
    assert a.startup is True and a.login is True
    b2 = cli.build_parser().parse_args(["connect", "--no-startup", "--no-login"])
    assert b2.startup is False and b2.login is False and b2.yes is False
    c = cli.build_parser().parse_args(["connect"])  # nothing given → ask interactively
    assert c.startup is None and c.login is None and c.runtime_opt is None


# _connect_next — terminal vs chat split, varied by login + startup state.

def test_connect_next_logged_in_and_pinned(monkeypatch):
    groups = cli._connect_next(runtime="hermes", logged_in=True, startup_pinned=True)
    assert [lbl for lbl, _ in groups] == ["in this terminal", "in your chat (Hermes / OpenClaw)"]
    term = [c for c, _ in groups[0][1]]
    chat = [c for c, _ in groups[1][1]]
    assert any(c.endswith("agent logout") for c in term)      # switch account
    assert not any(c.endswith("agent login") for c in term)
    assert not any("serve" in c or "resurrect" in c for c in term)  # already pinned
    assert any(c.endswith("--help") for c in term)            # help always
    assert "/reload-skills" in chat                           # register the skill (Hermes caches its scan)
    assert "/sr" in chat                                       # single-command entry
    assert "/sr login" not in chat                            # already signed in


def test_connect_next_fresh_and_unpinned(monkeypatch):
    groups = cli._connect_next(runtime="hermes", logged_in=False, startup_pinned=False)
    term = [c for c, _ in groups[0][1]]
    chat = [c for c, _ in groups[1][1]]
    assert any(c.endswith("agent login") for c in term)
    assert not any(c.endswith("agent logout") for c in term)
    assert any("serve" in c for c in term) and any("resurrect" in c for c in term)
    assert any(c.endswith("--help") for c in term)            # help always
    assert "/reload-skills" in chat and "/sr login" in chat and "/sr" in chat


def test_connect_next_openclaw_omits_reload_skills(monkeypatch):
    # OpenClaw auto-watches the skill dir (no /reload-skills command). The chat
    # group must NOT advertise a reload step there, but /sr must still appear.
    groups = cli._connect_next(runtime="openclaw", logged_in=True, startup_pinned=True)
    chat = [c for c, _ in groups[1][1]]
    assert "/reload-skills" not in chat
    assert "/sr" in chat


# Cross-platform reachability: a co-located (local) runtime on a non-Windows host
# needs no setup and must NOT touch any WSL machinery.

def test_ensure_reachable_local_on_linux(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "linux")
    monkeypatch.setattr(connect, "host_os_label", lambda: "Linux")
    monkeypatch.setattr(cli.connect, "looks_containerized", lambda: False)
    _, out = _cap(cli._ensure_reachable, connect.Target("hermes", "local", Path("/home/x")))
    assert "loopback" in out.lower()


def test_bridge_up_requires_version_marker(monkeypatch):
    # Only a /healthz body carrying the bridge marker counts as "up".
    monkeypatch.setattr(cli, "_bridge_get", lambda p, **k: (200, {"ok": True, "version": "1"}))
    assert cli._bridge_up() is True
    monkeypatch.setattr(cli, "_bridge_get", lambda p, **k: (200, {"hello": "i am not a bridge"}))
    assert cli._bridge_up() is False   # foreign HTTP server on :9876 is NOT the bridge
    monkeypatch.setattr(cli, "_bridge_get", lambda p, **k: None)
    assert cli._bridge_up() is False


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


# _wait_bridge_up — a freshly-detached bridge needs a beat to bind; poll, don't glance.

def test_wait_bridge_up_polls_until_ready(monkeypatch):
    calls = {"n": 0}
    def up():
        calls["n"] += 1
        return calls["n"] >= 3  # down for the first two polls, then up
    monkeypatch.setattr(cli, "_bridge_up", up)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)  # don't actually wait
    assert cli._wait_bridge_up(timeout=5.0, interval=0.01) is True
    assert calls["n"] == 3


def test_wait_bridge_up_times_out(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_up", lambda: False)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    assert cli._wait_bridge_up(timeout=0.0, interval=0.01) is False  # never comes up → False


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
