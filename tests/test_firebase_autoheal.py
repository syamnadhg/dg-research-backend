"""#717 — a transient DNS/network blip must self-heal on autopilot.

2026-05-31 incident: a `getaddrinfo` failure resolving securetoken.googleapis.com
broke the Firebase token refresh → the Firestore client (`_firebase_db`) went
None → the device sat OFFLINE. It did not self-heal because:

  1. `_firebase_db is None` was OVERLOADED — it meant both a transient net blip
     (token still valid) AND a genuine revoke (Reset Pair Code). The relink loop
     fired on bare None and spun on a stale customToken (INVALID_CUSTOM_TOKEN).
  2. The heartbeat's inline reinit was UNREACHABLE once the client was None (no
     write attempted → its except never ran again).
  3. The supervisor only respawned on process EXIT, never on a hang.

Fix (advisor-verified): classify revoked-vs-transient at the auth boundary; an
always-armed reconnect loop on every worker retries init on a tight backoff;
the relink loop only fires on a genuine revoke; a supervisor watchdog
force-respawns a wedged worker with its OWN damping window (never the
keystore-wipe crash path). Source-inspection guards on research.py.
"""
import inspect

import research


def test_down_reason_flag_exists():
    assert hasattr(research, "_firebase_down_reason"), (
        "BE must expose a module-level `_firebase_down_reason` so recovery can "
        "tell a transient blip apart from a genuine revoke (#717)."
    )
    assert hasattr(research, "_last_loop_tick_ms"), (
        "BE must expose `_last_loop_tick_ms` — the per-worker liveness pulse the "
        "watchdog reads via /api/health (#717)."
    )


def test_init_firebase_classifies_transient_vs_revoked():
    src = inspect.getsource(research.init_firebase)
    # The propagated-exception branch == transient (token intact, retry).
    assert "_firebase_down_reason = \"transient\"" in src, (
        "init_firebase must classify a propagated network error as transient "
        "(keystore intact → reconnect, not relink) (#717)."
    )
    # The None-client branch == genuine revoke (keystore wiped inside
    # init_firestore_user_scoped).
    assert "_firebase_down_reason = \"revoked\"" in src, (
        "init_firebase must classify a None client (RevokedError) as revoked "
        "(#717)."
    )
    # Success clears the reason.
    assert "_firebase_down_reason = None" in src, (
        "init_firebase must clear the reason on success (#717)."
    )
    # The transient classification must wrap the init call in try/except so a
    # propagated RequestException is caught (not crash the caller).
    assert "init_firestore_user_scoped" in src and "except Exception" in src, (
        "init_firebase must catch a propagated transient error from "
        "init_firestore_user_scoped and classify it (#717)."
    )


def test_reconnect_loop_exists_and_is_tight_and_gated():
    assert hasattr(research, "_firebase_reconnect_loop"), (
        "BE must expose _firebase_reconnect_loop — the always-armed transient "
        "reconnection watcher (#717)."
    )
    src = inspect.getsource(research._firebase_reconnect_loop)
    # Mutually exclusive with the relink loop: idle on a genuine revoke.
    assert '_firebase_down_reason == "revoked"' in src, (
        "the reconnect loop must stay idle on a genuine revoke so it doesn't "
        "double-drive recovery against the relink loop (#717)."
    )
    # Reconnect via init_firebase in a THREAD (its live refresh has a 10s
    # timeout that must not stall the loop cadence).
    assert "asyncio.to_thread(init_firebase)" in src, (
        "the reconnect loop must call init_firebase in a thread (its 10s live "
        "refresh would otherwise stall the loop) (#717)."
    )
    # TIGHT backoff — NOT the 30s/2m/8m agent-path schedule (FE flips offline at
    # ~15s, so recovery must be seconds).
    assert "(5, 5, 10, 30)" in src, (
        "the reconnect loop must use a tight seconds-scale backoff so a short "
        "blip clears before the FE offline threshold (#717)."
    )
    assert "_DNS_BACKOFF_SECS[" not in src, (
        "the reconnect loop must NOT borrow the 30s/2m/8m agent-path backoff — "
        "too slow for a device-liveness signal (#717)."
    )
    # Liveness pulse for the watchdog.
    assert "_last_loop_tick_ms" in src, (
        "the reconnect loop must bump _last_loop_tick_ms each iteration so the "
        "watchdog has a per-worker pulse (#717)."
    )
    # #718 — any reconnect schedules a CLEAN respawn so the fresh boot re-binds
    # the Firestore listeners. The in-process client swap restores the heartbeat
    # but leaves the old on_snapshot Watch streams dead on a sustained outage
    # ("online but deaf"); a respawn makes listener health deterministic.
    assert "_schedule_server_exit" in src, (
        "a reconnect must schedule a clean respawn to re-bind listeners (#718)."
    )
    # …but the respawn must NOT os._exit an ACTIVE run — it's deferred to idle.
    assert '_QUEUE_STATE.get("running")' in src and "pending_respawn" in src, (
        "the respawn must be deferred while a run is active so it never kills a "
        "mid-run worker (#718)."
    )


def test_heartbeat_hands_off_instead_of_unreachable_reinit():
    src = inspect.getsource(research._heartbeat_loop)
    # The heartbeat must hand off by flagging transient + nulling the client…
    assert "_firebase_down_reason = \"transient\"" in src, (
        "the heartbeat must flag transient + hand reconnection to the reconnect "
        "loop, not reinit inline (#717)."
    )
    # …and must NOT call init_firebase inline anymore (that path was unreachable
    # once the client went None — the root of the wedge).
    assert "init_firebase()" not in src, (
        "the heartbeat must NOT call init_firebase inline — the reconnect loop "
        "owns rebuilds now (the inline reinit was unreachable once None) (#717)."
    )


def test_relink_loop_gated_on_revoked():
    src = inspect.getsource(research._revoked_recovery_loop)
    assert '_firebase_down_reason != "revoked"' in src, (
        "the relink loop must idle unless the drop was classified a genuine "
        "revoke — entering the customToken poll on a transient blip is what "
        "caused the stale-token INVALID_CUSTOM_TOKEN spin (#717)."
    )


def test_health_exposes_watchdog_signals():
    mod_src = inspect.getsource(research)
    assert '"lastTickAt": _last_loop_tick_ms' in mod_src, (
        "/api/health must expose lastTickAt (per-worker liveness) for the "
        "watchdog (#717)."
    )
    assert '"relinking": _firebase_down_reason == "revoked"' in mod_src, (
        "/api/health must expose `relinking` so the watchdog exempts a worker "
        "in a legit 15-min relink poll (#717)."
    )


def test_supervisor_watchdog_present_and_safe():
    mod_src = inspect.getsource(research)
    # Helpers exist.
    for fn in ("_watchdog_check", "_watchdog_respawn", "_probe_worker_health"):
        assert f"def {fn}(" in mod_src, (
            f"the supervisor must define {fn} for the liveness watchdog (#717)."
        )
    # Separate damping window — NOT crash_window (which wipes the keystore).
    assert "watchdog_window" in mod_src, (
        "the watchdog must damp with its OWN window so it never feeds the "
        "crash tracker / keystore-wipe path (#717)."
    )
    # A watchdog terminate must be intercepted BEFORE the crash/keystore-wipe
    # branch on the next poll.
    assert 'state.pop("watchdog_killing", False)' in mod_src, (
        "a watchdog-initiated exit must be handled before crash tracking so it "
        "can't trip the worker-1 keystore wipe (#717)."
    )
    # Idle-only backstops — exempt active-run + relink.
    assert "if running or relinking:" in mod_src, (
        "the watchdog must exempt active-run and relinking workers from the "
        "idle backstops (#717)."
    )
    # Device-heartbeat backstop is worker-1 only (only w1 writes it) so it never
    # perpetually kills the heartbeat-silent worker 2.
    assert "if k == 1:" in mod_src and "lastHeartbeatAt" in mod_src, (
        "the device-heartbeat staleness backstop must be worker-1-only so the "
        "watchdog never false-kills the heartbeat-silent worker 2 (#717)."
    )
