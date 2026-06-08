"""#790 agent-session lifecycle: connect-write, heartbeat, revoke-consult, self-logout.

These exercise the module-level helpers directly (no HTTP server) with a
recording fake Firestore + a fake session, so every branch — label preservation,
the revoke→self-logout, the missing-doc re-create, and silent-self-heal on a
transient blip — is deterministic.
"""

import threading
import time
from types import SimpleNamespace

import pytest

from facade import bridge, config


class RecFS:
    """Recording fake Firestore for the agent-session helpers."""

    doc = None  # what get_agent_session returns (a dict or None)
    upserts: list = []
    deletes: list = []
    uninstalls: list = []  # runtimes connect.uninstall was called with (revoke path)
    uninstall_homes: list = []  # the home= kwarg forwarded each time (WSL UNC vs None)
    get_raises = None  # set to an Exception instance to raise on get
    upsert_raises = None

    def __init__(self, _token_provider):
        pass

    def get_agent_session(self, uid, sid):
        if RecFS.get_raises is not None:
            raise RecFS.get_raises
        return dict(RecFS.doc) if RecFS.doc else None

    def upsert_agent_session(self, uid, sid, fields):
        if RecFS.upsert_raises is not None:
            raise RecFS.upsert_raises
        RecFS.upserts.append({"uid": uid, "sid": sid, "fields": fields})
        merged = dict(RecFS.doc or {})
        merged.update(fields)
        RecFS.doc = merged  # reflect the write so a later get sees it

    def delete_agent_session(self, uid, sid):
        RecFS.deletes.append({"uid": uid, "sid": sid})


@pytest.fixture()
def wired(monkeypatch):
    RecFS.doc = None
    RecFS.upserts = []
    RecFS.deletes = []
    RecFS.uninstalls = []
    RecFS.uninstall_homes = []
    RecFS.get_raises = None
    RecFS.upsert_raises = None
    monkeypatch.setattr(bridge, "FirestoreRest", RecFS)
    monkeypatch.setattr(bridge.prefs, "get_or_create_install_id", lambda: "iid-1")
    monkeypatch.setattr(bridge.prefs, "get_label", lambda: "Super Agent")
    monkeypatch.setattr(bridge.prefs, "get_runtime", lambda: "hermes")
    # Record (don't perform) the skill uninstall so tests never touch a real
    # runtime dir; assert WHEN it fires (app revoke) vs not (logout / token revoke)
    # AND the home= kwarg forwarded (so a WSL install under a UNC home is removed).
    monkeypatch.setattr(bridge.connect, "uninstall",
                        lambda rt, **kw: (RecFS.uninstalls.append(rt)
                                          or RecFS.uninstall_homes.append(kw.get("home")) or True))
    cleared = {"v": False}
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: cleared.__setitem__("v", True))
    return cleared


def _state(uid="u1"):
    st = bridge.BridgeState()
    logged_out = {"v": False}
    sess = SimpleNamespace(
        uid=uid,
        email="e@x.y",
        id_token=lambda force=False: "tok",
        logout=lambda: logged_out.__setitem__("v", True),
    )
    sess._logged_out = logged_out  # type: ignore[attr-defined]
    st.set_session(sess)
    return st, sess


# ── connect-write ────────────────────────────────────────────────────────────

def test_connect_write_sets_full_row(wired):
    _st, sess = _state()
    bridge._write_agent_session_connected(sess, clear_revoked=True)
    assert len(RecFS.upserts) == 1
    up = RecFS.upserts[0]
    assert up["sid"] == "iid-1" and up["uid"] == "u1"
    f = up["fields"]
    assert f["label"] == "Super Agent" and f["runtime"] == "hermes"
    assert f["email"] == "e@x.y" and f["revoked"] is False
    assert "connectedAt" in f and "lastSeenAt" in f


def test_connect_write_preserves_renamed_label(wired):
    # The FE renamed the agent → the doc already carries "My Bot"; a reconnect
    # must NOT reset it to the prefs default.
    RecFS.doc = {"label": "My Bot"}
    _st, sess = _state()
    bridge._write_agent_session_connected(sess, clear_revoked=True)
    assert RecFS.upserts[0]["fields"]["label"] == "My Bot"


def test_connect_write_clear_revoked_true_unrevokes(wired):
    # Explicit human sign-in: revoked is cleared to False.
    RecFS.doc = {"label": "X", "revoked": True}
    _st, sess = _state()
    bridge._write_agent_session_connected(sess, clear_revoked=True)
    assert RecFS.upserts[0]["fields"]["revoked"] is False


def test_connect_write_clear_revoked_false_preserves_revoked(wired):
    # Automatic re-arm (restart / heartbeat re-create) must NOT touch revoked —
    # the field is omitted, so a masked merge leaves a pending revoke intact.
    RecFS.doc = {"label": "X", "revoked": True}
    _st, sess = _state()
    bridge._write_agent_session_connected(sess, clear_revoked=False)
    assert "revoked" not in RecFS.upserts[0]["fields"]


def test_connect_write_is_best_effort(wired):
    # A Firestore failure must NEVER propagate — login can't fail because the
    # identity-row write failed.
    RecFS.upsert_raises = RuntimeError("boom")
    _st, sess = _state()
    bridge._write_agent_session_connected(sess, clear_revoked=True)  # does not raise


# ── heartbeat + revoke-consult ────────────────────────────────────────────────

def test_heartbeat_bumps_only_last_seen(wired):
    RecFS.doc = {"label": "Super Agent", "revoked": False}
    st, sess = _state()
    bridge._heartbeat_once(st)
    assert RecFS.upserts and list(RecFS.upserts[-1]["fields"].keys()) == ["lastSeenAt"]
    assert st.session is sess  # still connected


def test_heartbeat_revoked_self_logs_out_and_leaves_row(wired):
    RecFS.doc = {"revoked": True}
    st, sess = _state()
    bridge._heartbeat_once(st)
    assert st.session is None  # self-logged-out
    assert sess._logged_out["v"] is True  # token blanked
    assert wired["v"] is True  # device selection cleared
    assert RecFS.deletes == []  # revoke LEAVES the row (only a clean /logout deletes)
    assert RecFS.uninstalls == ["hermes"]  # app revoke ALSO uninstalls the skill


def test_revoke_uninstall_forwards_recorded_wsl_home(wired, monkeypatch):
    # The bridge.py change: revoke must remove a WSL install under its recorded
    # \\wsl.localhost UNC home, not just the Windows default path.
    from pathlib import Path
    unc = r"\\wsl.localhost\Ubuntu-24.04\home\me"
    monkeypatch.setattr(bridge.prefs, "get_runtime_home", lambda: unc)
    RecFS.doc = {"revoked": True}
    st, _sess = _state()
    bridge._heartbeat_once(st)
    assert RecFS.uninstalls == ["hermes"]
    assert RecFS.uninstall_homes == [Path(unc)]  # home= forwarded to connect.uninstall


def test_revoke_uninstall_windows_default_when_no_home(wired, monkeypatch):
    # No recorded home (older connect) → no home kwarg → Windows-default path.
    monkeypatch.setattr(bridge.prefs, "get_runtime_home", lambda: None)
    RecFS.doc = {"revoked": True}
    st, _sess = _state()
    bridge._heartbeat_once(st)
    assert RecFS.uninstalls == ["hermes"]
    assert RecFS.uninstall_homes == [None]


def test_heartbeat_recreates_missing_doc_fully(wired):
    RecFS.doc = None  # connect-write never landed / row cleared out-of-band
    st, sess = _state()
    bridge._heartbeat_once(st)
    f = RecFS.upserts[-1]["fields"]
    assert f["label"] == "Super Agent" and "connectedAt" in f  # full re-create, not bare
    assert st.session is sess


def test_heartbeat_transient_read_error_keeps_session(wired):
    from facade.firestore_rest import FirestoreError
    RecFS.get_raises = FirestoreError("GET ... -> HTTP 503")
    st, sess = _state()
    bridge._heartbeat_once(st)
    assert st.session is sess  # silent self-heal — keep looping, never logout on a blip


def test_heartbeat_token_revoked_self_logs_out(wired):
    from facade.session import RevokedError
    RecFS.get_raises = RevokedError("refresh token rejected")
    st, _sess = _state()
    bridge._heartbeat_once(st)
    assert st.session is None  # the account token itself was rejected → self-logout
    # A token-level revoke (e.g. "sign out everywhere") is NOT an app agent-revoke
    # — keep the skill installed; the user may just re-login.
    assert RecFS.uninstalls == []


def test_heartbeat_revoke_with_reconnect_swap_does_not_uninstall(wired, monkeypatch):
    # The app revoked session A, but a reconnect swapped in session B (clearing
    # revoked) before the tick's _self_logout — the CAS must skip teardown AND the
    # skill must NOT be uninstalled (the agent is freshly, legitimately connected).
    RecFS.doc = {"revoked": True}
    st, _sess_a = _state()
    sess_b = SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "tok",
                             logout=lambda: (_ for _ in ()).throw(AssertionError("B logged out!")))
    real_get = RecFS.get_agent_session

    def get_then_swap(self, uid, sid):
        st.set_session(sess_b)  # reconnect lands right after the revoked read
        return real_get(self, uid, sid)

    monkeypatch.setattr(RecFS, "get_agent_session", get_then_swap)
    bridge._heartbeat_once(st)
    assert st.session is sess_b  # B survived the CAS
    assert RecFS.uninstalls == []  # CAS skipped → no uninstall


def test_heartbeat_skips_when_signed_out(wired):
    st = bridge.BridgeState()
    st.set_session(None)
    bridge._heartbeat_once(st)
    assert RecFS.upserts == [] and RecFS.deletes == []


# ── startup re-arm: must NOT silently un-revoke (the confirmed blocker) ───────

def test_startup_honors_pending_revoke(wired):
    # A Revoke landed while the bridge was DOWN; on restart the bridge must honor
    # it (self-logout), NOT re-attach by writing revoked:False.
    RecFS.doc = {"label": "X", "revoked": True}
    st, sess = _state()
    bridge._arm_agent_session_on_start(st)
    assert st.session is None  # honored the revoke — did NOT re-attach
    # crucially, it never wrote a revoked:False (no un-revoke)
    assert all(u["fields"].get("revoked") is not False for u in RecFS.upserts)
    assert RecFS.uninstalls == ["hermes"]  # a revoke honored on restart also uninstalls


def test_startup_rearms_when_not_revoked(wired):
    RecFS.doc = {"label": "My Bot"}  # no revoked → still connected
    st, sess = _state()
    bridge._arm_agent_session_on_start(st)
    assert st.session is sess  # still connected
    f = RecFS.upserts[-1]["fields"]
    assert f["label"] == "My Bot" and "revoked" not in f  # re-arm preserves revoked-absence


# ── compare-and-swap teardown (the revoke-vs-reconnect race) ──────────────────

def test_self_logout_cas_skips_when_session_swapped(wired):
    # A heartbeat decided to self-logout against session A, but a reconnect
    # swapped in session B (clearing revoked) first — the CAS must NOT tear down B.
    st = bridge.BridgeState()
    sess_a = SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "t",
                             logout=lambda: None)
    sess_b = SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "t",
                             logout=lambda: (_ for _ in ()).throw(AssertionError("B logged out!")))
    st.set_session(sess_a)
    st.set_session(sess_b)  # reconnect swapped B in
    bridge._self_logout(st, sess_a)  # heartbeat acts on the STALE A
    assert st.session is sess_b  # B survived — not torn down


def test_self_logout_tears_down_current_session(wired):
    st, sess = _state()
    bridge._self_logout(st, sess)
    assert st.session is None and wired["v"] is True


def test_heartbeat_skips_write_when_session_swapped(wired, monkeypatch):
    # doc present + not revoked → would PATCH lastSeenAt, BUT a concurrent logout
    # swapped the session out after the GET — the is_current guard skips the write
    # so a just-deleted row can't be resurrected.
    RecFS.doc = {"label": "X", "revoked": False}
    st, sess = _state()
    real_get = RecFS.get_agent_session

    def get_then_swap(self, uid, sid):  # noqa: ANN001
        st.set_session(None)  # simulate a /logout landing right after the GET
        return real_get(self, uid, sid)

    monkeypatch.setattr(RecFS, "get_agent_session", get_then_swap)
    bridge._heartbeat_once(st)
    assert RecFS.upserts == []  # is_current(sess) False → no write


# ── the loop wrapper ──────────────────────────────────────────────────────────

def test_heartbeat_loop_ticks_then_stops(monkeypatch):
    monkeypatch.setattr(config, "HEARTBEAT_INTERVAL_SECONDS", 0.02)
    ticks = {"n": 0}
    monkeypatch.setattr(bridge, "_heartbeat_once", lambda st: ticks.__setitem__("n", ticks["n"] + 1))
    stop = threading.Event()
    t = threading.Thread(target=bridge._heartbeat_loop, args=(bridge.BridgeState(), stop), daemon=True)
    t.start()
    time.sleep(0.15)
    stop.set()
    t.join(timeout=2)
    assert not t.is_alive()  # the stop event ends the loop deterministically
    assert ticks["n"] >= 1


def test_heartbeat_loop_survives_a_throwing_tick(monkeypatch):
    monkeypatch.setattr(config, "HEARTBEAT_INTERVAL_SECONDS", 0.02)
    calls = {"n": 0}

    def boom(_st):
        calls["n"] += 1
        raise RuntimeError("tick blew up")

    monkeypatch.setattr(bridge, "_heartbeat_once", boom)
    stop = threading.Event()
    t = threading.Thread(target=bridge._heartbeat_loop, args=(bridge.BridgeState(), stop), daemon=True)
    t.start()
    time.sleep(0.15)
    stop.set()
    t.join(timeout=2)
    assert not t.is_alive()  # a throwing tick must not kill the thread
    assert calls["n"] >= 2  # it kept ticking past the first exception
