"""Unit tests for the multi-worker claim sentinel (`.worker.{N}.lock`)
that prevents dual-spawn after a worker reboot.

Bug context (2026-05-22): user stopped Golden Retriever (worker 1
exited), fired a new submission while worker 1 was restarting. Worker 2
claimed via the start-listener and deleted the Firestore queue doc.
Worker 1 finished its restart cycle, rehydration saw the research as
status="ongoing" with on-disk queue_dir, and auto-resumed locally — two
workers ran the same pipeline (two browsers, two Doc/Email writes).

The on-disk lock files are the only cross-worker signal that survives
the queue-doc deletion both claim paths perform immediately. The scan
function checks PID liveness AND a started_at-age cap (8h) so a
crash-leftover lock whose PID was recycled by an unrelated process is
not falsely treated as a live sibling.

Run via:
    pytest tests/test_worker_lock.py -v
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import (  # noqa: E402
    _WORKER_LOCK_PID_REUSE_MAX_AGE_MS,
    _delete_worker_lock,
    _scan_sibling_locks_for_research,
    _worker_lock_path,
    _write_worker_lock,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _write_raw_lock(worker_id: int, payload: dict) -> Path:
    """Bypass the helper to inject crafted JSON for negative-path tests."""
    path = _worker_lock_path(worker_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clean_locks():
    """Wipe any stray .worker.*.lock files before AND after each test so
    cross-test pollution can't mask bugs."""
    lock_dir = Path(__file__).parent.parent / "queues"

    def _cleanup():
        if lock_dir.exists():
            for f in lock_dir.glob(".worker.*.lock"):
                try:
                    f.unlink()
                except Exception:
                    pass

    _cleanup()
    yield
    _cleanup()


# ── Write / delete roundtrip ───────────────────────────────────────────

def test_write_lock_creates_file_with_expected_fields():
    _write_worker_lock(1, "research-abc", "Topic_20260522_120000")
    path = _worker_lock_path(1)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["worker_id"] == 1
    assert data["research_id"] == "research-abc"
    assert data["run_id"] == "Topic_20260522_120000"
    assert data["pid"] == os.getpid()
    assert isinstance(data["started_at"], int)
    assert data["started_at"] > 0


def test_write_lock_overwrites_prior_for_same_worker():
    _write_worker_lock(1, "research-old", "old-run")
    _write_worker_lock(1, "research-new", "new-run")
    data = json.loads(_worker_lock_path(1).read_text(encoding="utf-8"))
    assert data["research_id"] == "research-new"
    assert data["run_id"] == "new-run"


def test_delete_lock_removes_file():
    _write_worker_lock(1, "r1", "run1")
    assert _worker_lock_path(1).exists()
    _delete_worker_lock(1)
    assert not _worker_lock_path(1).exists()


def test_delete_lock_when_missing_is_noop():
    # Should not raise.
    _delete_worker_lock(99)


# ── Scan: empty / no-sibling cases ─────────────────────────────────────

def test_scan_empty_when_no_locks():
    assert _scan_sibling_locks_for_research("research-x", 1) == []


def test_scan_excludes_self_lock():
    _write_worker_lock(1, "research-x", "run-x")
    # Caller is worker 1 — self-lock must not be returned.
    assert _scan_sibling_locks_for_research("research-x", 1) == []


def test_scan_skips_different_research_id():
    # Worker 2 owns a different research. Worker 1 rehydrating
    # research-x must not see worker 2's research-y lock as a blocker.
    _write_worker_lock(2, "research-y", "run-y")
    assert _scan_sibling_locks_for_research("research-x", 1) == []


# ── Scan: positive sibling-detection ───────────────────────────────────

def test_scan_detects_live_sibling_holding_research():
    """THE BUG: rehydration must see worker 2's claim and skip auto-resume."""
    _write_worker_lock(2, "research-x", "run-x")  # PID = current process, alive
    holders = _scan_sibling_locks_for_research("research-x", 1)
    assert len(holders) == 1
    assert holders[0]["worker_id"] == 2
    assert holders[0]["pid"] == os.getpid()


def test_scan_detects_multiple_siblings():
    _write_worker_lock(2, "research-x", "run-x")
    _write_worker_lock(3, "research-x", "run-x")
    holders = _scan_sibling_locks_for_research("research-x", 1)
    assert len(holders) == 2
    assert {h["worker_id"] for h in holders} == {2, 3}


# ── Scan: PID-liveness guard ───────────────────────────────────────────

def test_scan_skips_dead_pid():
    """Crash-leftover lock from a process that died without cleanup.
    The stale .worker.N.lock has a PID that no longer exists; rehydration
    must NOT treat it as a live sibling (would deadlock auto-resume
    forever)."""
    # PID 99999 is virtually never alive on a fresh system; if it
    # happens to be, the test's intent (dead PID) is preserved by the
    # additional check below.
    _write_raw_lock(2, {
        "worker_id": 2, "pid": 99999, "research_id": "research-x",
        "run_id": "run-x", "started_at": int(time.time() * 1000),
    })
    import psutil
    if psutil.pid_exists(99999):
        pytest.skip("PID 99999 happens to exist on this host — can't test dead-PID branch")
    assert _scan_sibling_locks_for_research("research-x", 1) == []


def test_scan_skips_pid_reuse_aged_out():
    """PID-reuse defense: even if the PID is alive (we use our own PID
    here, guaranteed alive), a lock whose started_at is older than 8h
    is treated as stale + recycled PID, not as a live sibling.

    Without this guard, a long-dead worker's lock + a freshly-recycled
    PID coincidence would falsely block rehydration forever."""
    aged_ms = int(time.time() * 1000) - (_WORKER_LOCK_PID_REUSE_MAX_AGE_MS + 60_000)
    _write_raw_lock(2, {
        "worker_id": 2, "pid": os.getpid(), "research_id": "research-x",
        "run_id": "run-x", "started_at": aged_ms,
    })
    assert _scan_sibling_locks_for_research("research-x", 1) == []


def test_scan_accepts_fresh_lock_just_under_threshold():
    """Belt-and-braces around the boundary: a lock at 7h59m is still
    considered live."""
    fresh_ms = int(time.time() * 1000) - (_WORKER_LOCK_PID_REUSE_MAX_AGE_MS - 60_000)
    _write_raw_lock(2, {
        "worker_id": 2, "pid": os.getpid(), "research_id": "research-x",
        "run_id": "run-x", "started_at": fresh_ms,
    })
    holders = _scan_sibling_locks_for_research("research-x", 1)
    assert len(holders) == 1


# ── Scan: malformed lock files ─────────────────────────────────────────

def test_scan_skips_malformed_json():
    """A truncated or corrupted lock file must not crash the scan; it's
    treated as if absent (safe — sibling will be detected on next scan
    after a fresh write, or auto-resume proceeds for a truly dead
    sibling)."""
    lock_dir = Path(__file__).parent.parent / "queues"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / ".worker.2.lock").write_text("{not valid json", encoding="utf-8")
    assert _scan_sibling_locks_for_research("research-x", 1) == []


def test_scan_skips_missing_pid_field():
    _write_raw_lock(2, {
        "worker_id": 2, "research_id": "research-x",
        "run_id": "run-x", "started_at": int(time.time() * 1000),
    })
    assert _scan_sibling_locks_for_research("research-x", 1) == []


def test_scan_skips_missing_started_at():
    _write_raw_lock(2, {
        "worker_id": 2, "pid": os.getpid(), "research_id": "research-x",
        "run_id": "run-x",
    })
    assert _scan_sibling_locks_for_research("research-x", 1) == []


def test_scan_skips_missing_worker_id():
    _write_raw_lock(2, {
        "pid": os.getpid(), "research_id": "research-x",
        "run_id": "run-x", "started_at": int(time.time() * 1000),
    })
    # File on disk (named .worker.2.lock) but JSON missing worker_id —
    # we don't try to recover from the filename; treat as malformed.
    assert _scan_sibling_locks_for_research("research-x", 1) == []


# ── Atomic-write guard (tmp+os.replace, never observed empty) ──────────

def test_write_is_atomic_concurrent_scan_never_empty():
    """`_write_worker_lock` uses tmp+os.replace so a scanner running
    concurrently with an overwrite either sees the prior content or the
    new content — never a zero-byte file (the bug `Path.write_text`'s
    open(O_TRUNC) would expose).

    We assert two things: (a) intermediate `.tmp` files are NOT picked
    up by the scanner's `.worker.*.lock` glob, and (b) after the write
    completes, the final lock matches the new content."""
    import threading

    _write_worker_lock(2, "research-old", "run-old")
    errors: "list[str]" = []
    stop = threading.Event()

    def _hammer_writes():
        i = 0
        while not stop.is_set() and i < 200:
            _write_worker_lock(2, f"research-{i}", f"run-{i}")
            i += 1

    def _hammer_scans():
        while not stop.is_set():
            # Scanner must never raise / never crash on partial writes.
            try:
                _scan_sibling_locks_for_research("research-x", 1)
            except Exception as e:
                errors.append(str(e))
                return

    t_w = threading.Thread(target=_hammer_writes, daemon=True)
    t_s = threading.Thread(target=_hammer_scans, daemon=True)
    t_w.start()
    t_s.start()
    t_w.join(timeout=5)
    stop.set()
    t_s.join(timeout=2)

    assert not errors, f"scanner saw exceptions during concurrent writes: {errors}"
    # Final state: lock exists, parses, has the expected shape.
    final = json.loads(_worker_lock_path(2).read_text(encoding="utf-8"))
    assert final["worker_id"] == 2
    assert final["research_id"].startswith("research-")
    # No leftover .tmp file (os.replace cleaned up).
    tmp_path = _worker_lock_path(2).with_suffix(".lock.tmp")
    assert not tmp_path.exists(), f"leftover .tmp file: {tmp_path}"


def test_scanner_glob_excludes_tmp_files():
    """Sanity: even if a `.worker.2.lock.tmp` exists (e.g., a crashed
    write that didn't complete), the scanner's glob must not pick it up
    as a lock — it would carry no useful content."""
    lock_dir = Path(__file__).parent.parent / "queues"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / ".worker.2.lock.tmp").write_text(json.dumps({
        "worker_id": 2, "pid": os.getpid(), "research_id": "research-x",
        "run_id": "run-x", "started_at": int(time.time() * 1000),
    }), encoding="utf-8")
    try:
        # No `.worker.2.lock` exists, only the `.tmp`. Scanner sees zero
        # siblings — `.tmp` is correctly excluded from the glob.
        assert _scan_sibling_locks_for_research("research-x", 1) == []
    finally:
        try:
            (lock_dir / ".worker.2.lock.tmp").unlink()
        except Exception:
            pass
