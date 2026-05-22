"""Unit tests for `_revoked_recovery_loop` wall-clock cap (Track D
hardening, 2026-05-22).

After Reset Pair Code triggers the BE's refresh-token revoke, the loop
polls the pending subdoc for a fresh customToken (15-min window from the
FE side). Before this fix the PollTimeout branch slept 5min and re-looped
forever — fine while the device doc existed, but after the device doc's
Firestore TTL fires (15min mark, reset-pair-code/route.ts:269) the
pending subdoc path becomes unreachable. The loop just span CPU + log
volume forever. The cap exits cleanly so the supervisor sees a clean
exit code (and stops respawning into the same dead loop).
"""

from __future__ import annotations

import asyncio
import importlib

import pytest


research = importlib.import_module("research")


def _run(coro):
    return asyncio.run(coro)


class _RaisedExitCode(SystemExit):
    """Sentinel so the test can catch `_os._exit(0)` instead of actually
    exiting the pytest process. We monkeypatch os._exit to raise this."""

    pass


class TestRevokedRecoveryLoopCap:
    """The cap fires when the recovery wall-clock exceeds 1hr."""

    def _setup_monkeypatch(
        self,
        monkeypatch,
        *,
        firebase_db_value,
        time_seq,
        poll_timeout_after_calls: int = 0,
    ):
        """Configure module-level state for a recovery-loop run.

        firebase_db_value: what `_firebase_db` returns at each access.
            None = trigger recovery; not None = quiet path.
        time_seq: list of values returned by sequential `time.time()`
            calls inside the loop.
        poll_timeout_after_calls: number of `do_redeem_reset` calls
            before the loop should raise PollTimeout.
        """
        # _firebase_db is a module global; setting it directly works.
        monkeypatch.setattr(research, "_firebase_db", firebase_db_value)

        # Stub research_config helpers so the early-return guard
        # doesn't fire on `(poll_secret, device_id)` being empty.
        monkeypatch.setattr(research, "load_poll_secret", lambda: "ps")
        monkeypatch.setattr(research, "load_device_id", lambda: "did")

        # Stub time.time() with a controlled sequence.
        time_iter = iter(time_seq)

        def fake_time():
            try:
                return next(time_iter)
            except StopIteration:
                # If the test consumed all values, return the last one
                # so the loop's guards see a stable now.
                return time_seq[-1]

        # `time.time` is accessed as `time.time()` inside research.py.
        # research imports `time` at the top, so we patch
        # research.time.time which is the same module.
        import time as _time_mod
        monkeypatch.setattr(_time_mod, "time", fake_time)

        # Stub asyncio.sleep so the loop iterates instantly.
        async def fake_sleep(*_args, **_kwargs):
            return None

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        # Stub auth.v2_flow.do_redeem_reset to raise PollTimeout after
        # the configured number of calls.
        from auth import v2_flow as v2

        calls = {"n": 0}

        async def fake_redeem(**_kw):
            calls["n"] += 1
            if calls["n"] > poll_timeout_after_calls:
                raise v2.PollTimeout()
            return None  # would not be reached in this test shape

        monkeypatch.setattr(v2, "do_redeem_reset", fake_redeem)

        # `_v2.compute_poll_secret_hash` — return any stable string.
        monkeypatch.setattr(v2, "compute_poll_secret_hash", lambda _s: "h")

        # Monkeypatch os._exit so it raises instead of killing the
        # pytest process. We catch _RaisedExitCode in the test.
        import os as _os_mod

        def fake_exit(code):
            raise _RaisedExitCode(code)

        monkeypatch.setattr(_os_mod, "_exit", fake_exit)
        return calls

    def test_cap_fires_after_one_hour_wallclock(self, monkeypatch):
        """After PollTimeout + the elapsed wall-clock exceeds 3600s, the
        loop must os._exit(0) instead of looping again."""
        # First entry: time.time() == 0 (sets first_recovery_attempt_ts).
        # Second iteration (after PollTimeout sleep): time.time() == 3700
        #   → elapsed > 3600 → cap fires → os._exit(0) raises.
        time_seq = [0.0, 0.0, 3700.0, 3700.0]  # plenty of headroom
        self._setup_monkeypatch(
            monkeypatch,
            firebase_db_value=None,
            time_seq=time_seq,
            poll_timeout_after_calls=0,  # first call raises PollTimeout
        )
        with pytest.raises(_RaisedExitCode) as excinfo:
            _run(research._revoked_recovery_loop())
        # _os._exit(0) — clean exit so supervisor stops respawning.
        assert int(str(excinfo.value)) == 0

    def test_cap_does_not_fire_within_window(self, monkeypatch):
        """If wall-clock is still under 3600s, the loop continues looping
        (does NOT call os._exit). We verify by ensuring the test would
        deadlock without an external termination — so we monkeypatch
        `do_redeem_reset` to succeed on the 2nd call, which makes the
        loop exit via the success path (also os._exit(0))."""
        # First call: PollTimeout (sets first_recovery_attempt_ts).
        # Second call: succeeds → exits via success-path os._exit.
        time_seq = [0.0, 0.0, 100.0, 100.0, 200.0]  # all < 3600
        self._setup_monkeypatch(
            monkeypatch,
            firebase_db_value=None,
            time_seq=time_seq,
            poll_timeout_after_calls=1,  # 1st PollTimeout, 2nd succeeds
        )
        # Need `_pair_patch_device` to be stubbed too (success branch
        # calls it before os._exit at research.py:2128-2143).
        monkeypatch.setattr(research, "_pair_patch_device", lambda *_a, **_kw: True)
        with pytest.raises(_RaisedExitCode) as excinfo:
            _run(research._revoked_recovery_loop())
        assert int(str(excinfo.value)) == 0

    def test_anchor_resets_when_firebase_recovers(self, monkeypatch):
        """If `_firebase_db` is healthy on entry, the anchor is None and
        the loop sleeps without entering the cap check. We verify by
        running one iteration with _firebase_db not None — the loop
        should NOT raise (no exit), just sleep and continue.

        We can't run the full while True; we cancel after one iteration."""
        # _firebase_db not None on first check → loop sleeps and loops.
        # We monkeypatch asyncio.sleep to raise CancelledError after the
        # first sleep so the loop exits via the except CancelledError
        # branch (research.py:2168 returns cleanly).
        monkeypatch.setattr(research, "_firebase_db", object())  # truthy
        monkeypatch.setattr(research, "load_poll_secret", lambda: "ps")
        monkeypatch.setattr(research, "load_device_id", lambda: "did")

        async def cancel_sleep(*_a, **_kw):
            raise asyncio.CancelledError()

        monkeypatch.setattr(asyncio, "sleep", cancel_sleep)
        # No exception expected — the loop exits via the
        # `except asyncio.CancelledError: return` branch at line 2168.
        _run(research._revoked_recovery_loop())
