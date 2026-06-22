"""#790 agent-session lifecycle: connect-write, heartbeat, revoke-consult, self-logout.

These exercise the module-level helpers directly (no HTTP server) with a
recording fake Firestore + a fake session, so every branch — label preservation,
the revoke→self-logout, the missing-doc re-create, and silent-self-heal on a
transient blip — is deterministic.
"""

import datetime as _dt
import threading
import time
from types import SimpleNamespace

import pytest

from facade import bridge, config


def _iso(ms: int) -> str:
    """A Firestore-style ISO-8601 UTC timestamp (…Z) for an epoch-ms value —
    mirrors how a serverTimestamp `revokedAt` reads back via FirestoreRest."""
    return (
        _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class RecFS:
    """Recording fake Firestore for the agent-session helpers."""

    doc = None  # what get_agent_session returns (a dict or None)
    upserts: list = []
    deletes: list = []
    uninstalls: list = []  # runtimes connect.uninstall was called with (revoke path)
    uninstall_homes: list = []  # the home= kwarg forwarded each time (WSL UNC vs None)
    runtime_cleared = False  # whether prefs.clear_runtime() fired (app-revoke teardown)
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
    RecFS.runtime_cleared = False
    RecFS.get_raises = None
    RecFS.upsert_raises = None
    monkeypatch.setattr(bridge, "FirestoreRest", RecFS)
    monkeypatch.setattr(bridge.prefs, "get_or_create_install_id", lambda: "iid-1")
    monkeypatch.setattr(bridge.prefs, "get_label", lambda: "Super Agent")
    monkeypatch.setattr(bridge.prefs, "get_runtime", lambda: "hermes")
    # Record (don't perform) the runtime-forget. Revoke is logout-only now, so it
    # must NOT fire on any revoke/logout path here — only `agent disconnect` (cli,
    # untested in this file) forgets the runtime; the guard asserts it stays False.
    monkeypatch.setattr(bridge.prefs, "clear_runtime",
                        lambda: setattr(RecFS, "runtime_cleared", True))
    # NB: the bridge no longer uninstalls the skill on revoke (revoke == self-logout),
    # so there is no connect.uninstall to patch — `uninstalls` stays empty and the
    # tests assert that, guarding against a regression that re-adds the teardown.
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
    # Revoke is now LOGOUT-ONLY: the skill stays installed and the runtime stays
    # recorded, so `/sr login` / `agent login` reconnects WITHOUT re-running connect.
    # (`agent disconnect` remains the only full teardown.)
    assert RecFS.uninstalls == []  # revoke does NOT uninstall the skill
    assert RecFS.runtime_cleared is False  # …nor forget the runtime


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
    # — keep the skill installed + the runtime recorded; the user may just re-login.
    assert RecFS.uninstalls == []
    assert RecFS.runtime_cleared is False


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
    assert RecFS.runtime_cleared is False  # …and the live reconnect's runtime is kept


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
    # Honoring a revoke on restart is still logout-only — skill + runtime are kept.
    assert RecFS.uninstalls == []
    assert RecFS.runtime_cleared is False


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


# ── #848 P2: stale-revoke guard (revokedAt ordering vs the capture epoch) ──────

def test_parse_firestore_ts_ms_int_and_iso():
    p = bridge._parse_firestore_ts_ms
    assert p(None) is None
    assert p(1782151690374) == 1782151690374
    assert p(1700.0) == 1700
    base = _dt.datetime(2026, 6, 10, 0, 10, 26, 123000, tzinfo=_dt.timezone.utc)
    want = int(base.timestamp() * 1000)
    assert p("2026-06-10T00:10:26.123Z") == want
    # Firestore nanosecond precision is TRUNCATED to micros (sub-ms floored), not rejected.
    assert p("2026-06-10T00:10:26.123456789Z") == want
    assert p("not-a-timestamp") is None
    assert p({"weird": 1}) is None


def test_should_honor_revoke_unknown_capture_honors():
    # A pre-change rehydrated session (no connected_at_ms) → honor the revoke (safe).
    sess = SimpleNamespace()
    assert bridge._should_honor_revoke({"revoked": True, "revokedAt": "2020-01-01T00:00:00Z"}, sess) is True


def test_should_honor_revoke_stale_predates_capture_is_ignored():
    now = int(time.time() * 1000)
    sess = SimpleNamespace(connected_at_ms=now)
    # A revoke from a week before this sign-in is stale → do NOT honor.
    assert bridge._should_honor_revoke({"revokedAt": _iso(now - 7 * 24 * 3600 * 1000)}, sess) is False


def test_should_honor_revoke_after_capture_is_honored():
    now = int(time.time() * 1000)
    sess = SimpleNamespace(connected_at_ms=now - 60_000)  # signed in a minute ago
    assert bridge._should_honor_revoke({"revokedAt": _iso(now)}, sess) is True


def test_should_honor_revoke_within_skew_margin_is_honored():
    now = int(time.time() * 1000)
    sess = SimpleNamespace(connected_at_ms=now)
    # A revoke 2 min "before" capture is within the 5-min skew margin → honor it
    # (clock drift between the host and Firestore must never drop a genuine revoke).
    assert bridge._should_honor_revoke({"revokedAt": _iso(now - 2 * 60 * 1000)}, sess) is True


def test_should_honor_revoke_no_revokedAt_with_known_capture_is_ignored():
    # A genuine revoke always carries a serverTimestamp; revoked:true with none,
    # when we DO know our capture time, is a stale/legacy row → ignore.
    sess = SimpleNamespace(connected_at_ms=int(time.time() * 1000))
    assert bridge._should_honor_revoke({"revoked": True}, sess) is False


def test_heartbeat_stale_revoke_reasserts_clear_not_logout(wired):
    # The exact #848 compounding case: a fresh sign-in, but a stale revoked row
    # lingers (a prior clear_revoked write failed). The heartbeat must NOT
    # self-logout the live session — it re-asserts the clear instead.
    now = int(time.time() * 1000)
    RecFS.doc = {"revoked": True, "revokedAt": _iso(now - 7 * 24 * 3600 * 1000)}
    st, sess = _state()
    sess.connected_at_ms = now  # signed in just now
    bridge._heartbeat_once(st)
    assert st.session is sess  # NOT logged out
    assert sess._logged_out["v"] is False
    assert any(u["fields"].get("revoked") is False for u in RecFS.upserts)  # re-asserted clear
    assert RecFS.deletes == []


def test_heartbeat_genuine_revoke_after_capture_logs_out(wired):
    # A revoke that post-dates this sign-in is the user disconnecting THIS live
    # agent → honor it (self-logout), leaving the revoked row in place.
    now = int(time.time() * 1000)
    RecFS.doc = {"revoked": True, "revokedAt": _iso(now)}
    st, sess = _state()
    sess.connected_at_ms = now - 10 * 60 * 1000  # signed in 10 min ago
    bridge._heartbeat_once(st)
    assert st.session is None  # honored → self-logout
    assert sess._logged_out["v"] is True
    assert RecFS.deletes == []  # revoke leaves the row (only a clean /logout deletes)


def test_startup_ignores_stale_revoke_and_reasserts(wired):
    now = int(time.time() * 1000)
    RecFS.doc = {"label": "X", "revoked": True, "revokedAt": _iso(now - 7 * 24 * 3600 * 1000)}
    st, sess = _state()
    sess.connected_at_ms = now
    bridge._arm_agent_session_on_start(st)
    assert st.session is sess  # not logged out
    assert any(u["fields"].get("revoked") is False for u in RecFS.upserts)  # re-asserted clear


def test_session_persists_and_rehydrates_capture_epoch(monkeypatch):
    # The capture epoch round-trips through the secret store so the guard works
    # across a bridge restart (load()).
    from facade import session as sess_mod
    mem: dict = {}
    monkeypatch.setattr(sess_mod.store, "load", lambda: mem.get("blob"))
    monkeypatch.setattr(sess_mod.store, "save", lambda blob: mem.__setitem__("blob", dict(blob)))
    s = sess_mod.AccountSession.from_capture(
        refresh_token="RT", id_token="ID", uid="u9", email="z@z.z", expires_in=3600,
    )
    assert isinstance(s.connected_at_ms, int)
    rehydrated = sess_mod.AccountSession.load()
    assert rehydrated is not None and rehydrated.connected_at_ms == s.connected_at_ms
