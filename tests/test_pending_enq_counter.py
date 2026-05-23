"""Unit tests for the listener-replay `_pending_listener_enqueues` counter
that prevents back-to-back dual-claim during Firestore on_snapshot replay.

Bug context (2026-05-22 St Bernard repro): on worker boot, Firestore
replays every unprocessed queue doc as ADDED in a single callback
batch. The busy-gate at research.py:~4106 read `job_queue.qsize()` to
decide whether to claim, but the enqueue runs via
`loop.call_soon_threadsafe(...)` — asynchronous, hasn't landed on the
event loop yet by the time the listener iterates to the next change.
So both docs claimed, second job sat un-run in worker 1's local queue
until the user stopped, then went stale as `paused_backend_restart`.

The fix is a lock-protected counter incremented by the listener thread
after a successful `_try_claim_queue_doc` and decremented by the
asyncio main thread at the worker's `running=True` flip (or on
`_safe_enqueue` failure). The gate is extended to consult the counter.

Run via:
    pytest tests/test_pending_enq_counter.py -v
"""
from __future__ import annotations

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import (  # noqa: E402
    _QUEUE_STATE,
    _pending_enq_dec,
    _pending_enq_inc,
    _pending_enq_read,
)


# ── Test isolation ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_counter():
    """Reset counter + lock before AND after each test so prior-state
    can't mask a bug. The lock is opt-in (initialised by run_server in
    production); tests cover both lock-present + lock-absent paths."""
    _QUEUE_STATE["_pending_listener_enqueues"] = 0
    _QUEUE_STATE["_pending_enq_lock"] = None
    yield
    _QUEUE_STATE["_pending_listener_enqueues"] = 0
    _QUEUE_STATE["_pending_enq_lock"] = None


# ── Basic roundtrip ────────────────────────────────────────────────────

def test_initial_counter_is_zero():
    assert _pending_enq_read() == 0


def test_inc_then_read():
    _pending_enq_inc()
    assert _pending_enq_read() == 1
    _pending_enq_inc()
    assert _pending_enq_read() == 2


def test_inc_then_dec_returns_to_zero():
    _pending_enq_inc()
    _pending_enq_inc()
    _pending_enq_dec()
    _pending_enq_dec()
    assert _pending_enq_read() == 0


# ── Defensive floor ────────────────────────────────────────────────────

def test_dec_floors_at_zero():
    """A stray decrement (e.g., a crashed worker's resumed sibling sees
    an empty counter but the call_soon_threadsafe callback still fires
    _safe_enqueue == False → dec) must not drive the counter negative.
    Negative counter would never compare > 0 in the gate → no fix, but
    risk of int-wrap or surprising future arithmetic. Defensive max(0,
    ...) is cheap insurance."""
    assert _pending_enq_read() == 0
    _pending_enq_dec()
    _pending_enq_dec()
    assert _pending_enq_read() == 0


# ── Lock-absent path (tests / pre-init) ────────────────────────────────

def test_helpers_tolerate_missing_lock():
    """run_server initialises `_pending_enq_lock` during startup. If a
    test or pre-init code path calls the helpers before that, they
    should fall back to direct dict access — same final value, just
    no concurrency protection (acceptable: tests run single-threaded)."""
    assert _QUEUE_STATE["_pending_enq_lock"] is None
    _pending_enq_inc()
    assert _pending_enq_read() == 1
    _pending_enq_dec()
    assert _pending_enq_read() == 0


# ── Lock-present path (production) ─────────────────────────────────────

def test_helpers_use_lock_when_initialised():
    """When `_pending_enq_lock` is set (production), the inc/dec/read
    take the lock. Verify by injecting a lock and checking the value
    is consistent under serial use."""
    _QUEUE_STATE["_pending_enq_lock"] = threading.Lock()
    _pending_enq_inc()
    _pending_enq_inc()
    _pending_enq_inc()
    assert _pending_enq_read() == 3
    _pending_enq_dec()
    assert _pending_enq_read() == 2


# ── Cross-thread atomicity ─────────────────────────────────────────────

def test_concurrent_inc_dec_under_lock_is_consistent():
    """Increment runs on Firestore listener thread; decrement runs on
    asyncio main thread. Without a lock, the read-modify-write in
    `_pending_enq_inc` could race with `_pending_enq_dec` and lose an
    update. With the lock, the final count must exactly equal
    (#incs − #decs), assuming all decs land while the counter is
    positive (we pre-seed so the dec floor doesn't mask lost updates).

    Pre-seeding 3N means N decs never hit the floor and the bug
    (lost-update) would surface as a non-2N final count."""
    _QUEUE_STATE["_pending_enq_lock"] = threading.Lock()
    N = 500
    # Pre-seed counter to 3N (well above N decs) so the max(0, ...)
    # floor never engages; this isolates "lost-update under race"
    # from "floor-clipping".
    for _ in range(3 * N):
        _pending_enq_inc()
    assert _pending_enq_read() == 3 * N
    barrier = threading.Barrier(2)

    def _hammer_inc():
        barrier.wait()
        for _ in range(N):
            _pending_enq_inc()

    def _hammer_dec():
        barrier.wait()
        for _ in range(N):
            _pending_enq_dec()

    t_i = threading.Thread(target=_hammer_inc, daemon=True)
    t_d = threading.Thread(target=_hammer_dec, daemon=True)
    t_i.start()
    t_d.start()
    t_i.join(timeout=10)
    t_d.join(timeout=10)
    # Pre-seed 3N + N incs - N decs = 3N. Under a lock-protected
    # counter, this is exact. Without a lock, the lost-update race
    # would land somewhere in 3N-50 to 3N (typically a few off on
    # Windows/CPython with GIL release between bytecodes).
    assert _pending_enq_read() == 3 * N, (
        f"lost-update under race: expected {3 * N}, got {_pending_enq_read()} "
        f"(diff {3 * N - _pending_enq_read()})"
    )


# ── Gate-semantic test (the bug being fixed) ───────────────────────────

def test_gate_check_after_inc_blocks_subsequent_claim():
    """The bug being fixed: between listener iteration N (claim → inc →
    schedule enqueue) and iteration N+1 (gate check), the
    call_soon_threadsafe hasn't landed on the asyncio queue yet —
    `qsize() == 0`. Without the counter, the gate sees idle and N+1
    also claims. With the counter, the gate sees `read() > 0` and
    defers N+1. Simulate the gate's read here."""
    _QUEUE_STATE["_pending_enq_lock"] = threading.Lock()
    # Initial state: idle worker, no scheduled enqueues.
    assert _pending_enq_read() == 0
    # Listener iter 1: claim succeeded, counter bumped synchronously.
    # (call_soon_threadsafe scheduled; the put_nowait hasn't landed.)
    _pending_enq_inc()
    # Listener iter 2 gate check: counter > 0 → defer (the fix).
    assert _pending_enq_read() > 0, "gate would falsely accept a second concurrent claim"


def test_gate_check_after_full_roundtrip_allows_claim():
    """Worker dequeue → flip `running=True` decrements the counter.
    Now the gate at iter 3 sees counter=0 again; but `running=True`
    also defers, so the test only validates that the counter wouldn't
    spuriously persist. The actual gate has 3 clauses (OR)."""
    _QUEUE_STATE["_pending_enq_lock"] = threading.Lock()
    _pending_enq_inc()
    _pending_enq_dec()  # simulate worker's running-flag flip
    assert _pending_enq_read() == 0
