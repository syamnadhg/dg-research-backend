"""#64 — abandonment backstop for a PERMANENTLY-dead worker's run.

When the supervisor (run_daemon_loop) declares a worker (id>=2) permanently dead
after a crash loop it STOPS respawning it, so that worker never runs its own
rehydration and its owned "ongoing" runs freeze with no Resume CTA. The
supervisor has no Firestore client, so it drops a durable on-disk dead-marker;
worker-1 (always alive — k=1 is never marked dead) reads it in a periodic loop
and marks the abandoned runs `paused_backend_restart` (the FE then shows a
Resume banner) — reusing the exact mark the rehydrate owner/orphan paths use.

Unlike the reverted #58 lock-based backstop (which keyed on the transient
per-run worker-lock, released at BE-phase-end, so its ABSENCE couldn't tell a
dead worker from a healthy FE-tail run), this keys on the DEFINITIVE `_dead`
signal + persisted ownership, and additionally guards on the Cloud-Run P4/P5
tail (delivery.json status=="completed") so a run that is completing without any
worker is never falsely paused.

Run:  pytest tests/test_dead_worker_backstop_64.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from research import (  # noqa: E402
    DEAD_WORKER_MARKER_GRACE_MS,
    _clear_worker_dead_marker,
    _read_dead_worker_ids,
    _worker_dead_marker_path,
    _write_worker_dead_marker,
)

_QUEUES = Path(__file__).parent.parent / "queues"


@pytest.fixture(autouse=True)
def _clean_markers():
    """Wipe any stray .worker.*.dead markers before AND after each test so
    real dev-env markers or cross-test pollution can't mask a bug."""
    def _cleanup():
        if _QUEUES.exists():
            for f in _QUEUES.glob(".worker.*.dead"):
                try:
                    f.unlink()
                except Exception:
                    pass
            for f in _QUEUES.glob(".worker.*.dead.tmp"):
                try:
                    f.unlink()
                except Exception:
                    pass
    _cleanup()
    yield
    _cleanup()


def _write_raw_marker(worker_id: int, died_at_ms: int, *, worker_id_field=None) -> Path:
    """Bypass the helper to inject a crafted died_at for grace/range tests."""
    _QUEUES.mkdir(parents=True, exist_ok=True)
    path = _worker_dead_marker_path(worker_id)
    path.write_text(json.dumps({
        "worker_id": worker_id if worker_id_field is None else worker_id_field,
        "pid": 4242,
        "died_at": died_at_ms,
        "reason": "crash_loop",
        "crash_count": 3,
        "supervisor_pid": 99,
    }), encoding="utf-8")
    return path


# ── Marker helpers ─────────────────────────────────────────────────────────

def test_marker_write_read_clear_roundtrip(monkeypatch):
    monkeypatch.setattr(research, "load_worker_count", lambda: 9)
    # A SETTLED death (older than the grace window) is returned.
    _write_raw_marker(8, int(time.time() * 1000) - DEAD_WORKER_MARKER_GRACE_MS - 5000)
    assert 8 in _read_dead_worker_ids()
    _clear_worker_dead_marker(8)
    assert 8 not in _read_dead_worker_ids()
    assert not _worker_dead_marker_path(8).exists()


def test_fresh_death_within_grace_not_returned(monkeypatch):
    monkeypatch.setattr(research, "load_worker_count", lambda: 9)
    # The real writer stamps died_at=now → still inside the grace window.
    _write_worker_dead_marker(8, pid=123, crash_count=3)
    assert _worker_dead_marker_path(8).exists()          # written…
    assert 8 not in _read_dead_worker_ids()              # …but not yet acted on


def test_worker1_marker_is_ignored(monkeypatch):
    # k=1 is never marked dead; a stray worker-1 marker must never be honored.
    monkeypatch.setattr(research, "load_worker_count", lambda: 9)
    _write_raw_marker(1, int(time.time() * 1000) - DEAD_WORKER_MARKER_GRACE_MS - 5000)
    assert 1 not in _read_dead_worker_ids()


def test_out_of_fleet_marker_ignored(monkeypatch):
    # Fleet shrank to 2; a stale k=8 marker is out of range → ignored (those runs
    # are covered by the out-of-fleet orphan branch in rehydrate).
    monkeypatch.setattr(research, "load_worker_count", lambda: 2)
    _write_raw_marker(8, int(time.time() * 1000) - DEAD_WORKER_MARKER_GRACE_MS - 5000)
    assert _read_dead_worker_ids() == set()


def test_settled_in_fleet_marker_returned(monkeypatch):
    monkeypatch.setattr(research, "load_worker_count", lambda: 3)
    old = int(time.time() * 1000) - DEAD_WORKER_MARKER_GRACE_MS - 5000
    _write_raw_marker(2, old)
    _write_raw_marker(3, old)
    assert _read_dead_worker_ids() == {2, 3}


def test_corrupt_marker_skipped_not_fatal(monkeypatch):
    monkeypatch.setattr(research, "load_worker_count", lambda: 9)
    _QUEUES.mkdir(parents=True, exist_ok=True)
    _worker_dead_marker_path(8).write_text("{not json", encoding="utf-8")
    # Does not raise; the unparseable file is simply skipped.
    assert 8 not in _read_dead_worker_ids()


# ── Reconciler (fake Firestore) ─────────────────────────────────────────────

class _Snap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._d = data

    def to_dict(self):
        return self._d


class _Query:
    def __init__(self, snaps):
        self._snaps = snaps

    def where(self, *a, **k):
        return self

    def get(self):
        return list(self._snaps)


class _ResearchesCol:
    def __init__(self, snaps):
        self._snaps = snaps

    def where(self, *a, **k):
        return _Query(self._snaps)


class _UserDocRef:
    def __init__(self, db, uid):
        self._db = db
        self._uid = uid

    def collection(self, name):
        assert name == "researches"
        return _ResearchesCol(self._db.researches.get(self._uid, []))


class _UsersCol:
    def __init__(self, db):
        self._db = db

    def document(self, uid):
        return _UserDocRef(self._db, uid)


class _FakeDB:
    def __init__(self):
        self.researches = {}

    def collection(self, name):
        assert name == "users"
        return _UsersCol(self)


def _ongoing(rid, assigned, *, run_id=None):
    d = {"status": "ongoing"}
    if assigned is not None:
        d["assignedWorker"] = assigned
    if run_id is not None:
        d["backendRunId"] = run_id
    return _Snap(rid, d)


def _setup_reconcile(monkeypatch, *, researches, siblings=None):
    db = _FakeDB()
    db.researches = researches
    monkeypatch.setattr(research, "_firebase_db", db, raising=False)
    monkeypatch.setattr(research, "WORKER_ID", 1, raising=False)
    updates = []
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda uid, rid, patch: (updates.append((uid, rid, patch)) or True))
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research",
                        lambda rid, wid: (siblings or {}).get(rid, []))
    return updates


def _reconcile(tree="owner-uid", dead=None):
    return asyncio.run(research._reconcile_dead_worker_runs(tree, dead or set()))


def test_dead_owner_run_marked(monkeypatch):
    updates = _setup_reconcile(monkeypatch, researches={"owner-uid": [_ongoing("r1", 2)]})
    n = _reconcile(dead={2})
    assert n == 1
    assert len(updates) == 1
    uid, rid, patch = updates[0]
    assert (uid, rid) == ("owner-uid", "r1")
    assert patch["status"] == "paused_backend_restart"
    assert "Resume" in patch["summary"]


def test_live_owner_not_marked(monkeypatch):
    # Owner 3 is NOT in the dead set → the run is left alone.
    updates = _setup_reconcile(monkeypatch, researches={"owner-uid": [_ongoing("r1", 3)]})
    assert _reconcile(dead={2}) == 0
    assert updates == []


def test_worker1_owned_run_never_marked(monkeypatch):
    updates = _setup_reconcile(monkeypatch, researches={"owner-uid": [_ongoing("r1", 1)]})
    assert _reconcile(dead={2}) == 0
    assert updates == []


def test_legacy_unstamped_owner_not_marked(monkeypatch):
    # Unstamped assignedWorker → owner 1 (legacy) → never in a >=2 dead set.
    updates = _setup_reconcile(monkeypatch, researches={"owner-uid": [_ongoing("r1", None)]})
    assert _reconcile(dead={2}) == 0
    assert updates == []


def test_live_sibling_lock_skips_reclaimed_run(monkeypatch):
    # A LIVE worker holds the lock (the run was re-claimed) → leave it.
    updates = _setup_reconcile(
        monkeypatch,
        researches={"owner-uid": [_ongoing("r1", 2)]},
        siblings={"r1": [{"worker_id": 2, "pid": 555}]},
    )
    assert _reconcile(dead={2}) == 0
    assert updates == []


def test_empty_dead_ids_is_noop(monkeypatch):
    updates = _setup_reconcile(monkeypatch, researches={"owner-uid": [_ongoing("r1", 2)]})
    assert _reconcile(dead=set()) == 0
    assert updates == []


def test_mixed_runs_only_dead_owned_marked(monkeypatch):
    updates = _setup_reconcile(monkeypatch, researches={"owner-uid": [
        _ongoing("r_dead", 2),
        _ongoing("r_live", 3),
        _ongoing("r_mine", 1),
    ]})
    assert _reconcile(dead={2}) == 1
    assert [u[1] for u in updates] == ["r_dead"]


def test_be_tail_completed_run_skipped(monkeypatch):
    # delivery.json status=="completed" ⇒ BE handed off to the autonomous
    # Cloud-Run P4/P5 tail (research.status stays "ongoing" meanwhile) ⇒ the run
    # is completing without any worker ⇒ must NOT be falsely paused.
    run_id = "test_dead_reconcile_betail_64"
    rdir = _QUEUES / run_id
    try:
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "delivery.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        updates = _setup_reconcile(
            monkeypatch, researches={"owner-uid": [_ongoing("r1", 2, run_id=run_id)]})
        assert _reconcile(dead={2}) == 0
        assert updates == []
    finally:
        shutil.rmtree(rdir, ignore_errors=True)


def test_be_incomplete_run_marked(monkeypatch):
    # delivery.json still in-flight ("ongoing") ⇒ BE genuinely mid-run ⇒ mark.
    run_id = "test_dead_reconcile_inflight_64"
    rdir = _QUEUES / run_id
    try:
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "delivery.json").write_text(json.dumps({"status": "ongoing"}), encoding="utf-8")
        updates = _setup_reconcile(
            monkeypatch, researches={"owner-uid": [_ongoing("r1", 2, run_id=run_id)]})
        assert _reconcile(dead={2}) == 1
        assert updates[0][1] == "r1"
    finally:
        shutil.rmtree(rdir, ignore_errors=True)


def test_missing_delivery_json_marks(monkeypatch):
    # No delivery.json (BE never reached handoff) ⇒ recoverable ⇒ mark.
    updates = _setup_reconcile(
        monkeypatch,
        researches={"owner-uid": [_ongoing("r1", 2, run_id="nonexistent_run_dir_64")]})
    assert _reconcile(dead={2}) == 1
    assert updates[0][1] == "r1"
