"""Unit tests for `_sweep_stuck_research_docs` — the shared Firestore
sweep used by HARD_RESET (FE Reset BE button) and run_unpair (CLI
`--unpair`) to mark stale BE-self-set research statuses as `stopped`.

Bug C context (2026-05-22 St Bernard repro):
  - User ran 5 chats; St Bernard got claimed-but-never-run by worker 1
    due to the listener-replay dual-claim race (fixed in Bug B).
  - User stopped, BE rehydrated → St Bernard marked
    `paused_backend_restart`.
  - User clicked Reset BE — HARD_RESET sweep used a stuck_set of
    {ongoing, running, paused} which DID NOT include
    `paused_backend_restart`. St Bernard stayed stuck.
  - Resolution: extend the stuck_set + extract the loop into a shared
    helper so `--unpair` can use it too (user req: unpair must also
    clean stale stuff).

Run via:
    pytest tests/test_sweep_stuck_research.py -v
"""
from __future__ import annotations

import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import _sweep_stuck_research_docs  # noqa: E402


# ── Fakes ──────────────────────────────────────────────────────────────

class _FakeRef:
    def __init__(self, doc_id, store, fail_on_update=False):
        self.id = doc_id
        self._store = store  # shared dict of {doc_id: payload}
        self._fail = fail_on_update

    def update(self, patch):
        if self._fail:
            raise RuntimeError(f"simulated update failure for {self.id}")
        if self.id not in self._store:
            raise RuntimeError(f"doc {self.id} disappeared")
        # Apply patch — handle DELETE_FIELD sentinel (just remove key)
        from google.cloud.firestore import DELETE_FIELD as _DF
        cur = self._store[self.id]
        for k, v in patch.items():
            if v is _DF:
                cur.pop(k, None)
            else:
                cur[k] = v


class _FakeSnap:
    def __init__(self, doc_id, payload, store, fail_on_update=False):
        self.id = doc_id
        self._payload = payload
        self.reference = _FakeRef(doc_id, store, fail_on_update=fail_on_update)

    def to_dict(self):
        return dict(self._payload)


class _FakeQuery:
    def __init__(self, snaps):
        self._snaps = snaps

    def stream(self):
        return iter(self._snaps)


class _FakeCol:
    def __init__(self, store, fail_doc_ids=None):
        # store = {doc_id: payload}
        self._store = store
        self._fail_set = set(fail_doc_ids or [])

    def where(self, _field, _op, _value):
        # Return all docs (test fixtures pre-filter by deviceId).
        snaps = [
            _FakeSnap(did, dict(p), self._store, fail_on_update=(did in self._fail_set))
            for did, p in self._store.items()
        ]
        return _FakeQuery(snaps)


class _FakeDoc:
    def __init__(self, col):
        self._col = col

    def collection(self, _name):
        return self._col


class _FakeDB:
    def __init__(self, store, fail_doc_ids=None):
        self._col = _FakeCol(store, fail_doc_ids=fail_doc_ids)

    def collection(self, _name):
        # `users` → returns a doc factory; `users/{uid}/researches` chain
        return self  # passes through to .document().collection()

    def document(self, _uid):
        return _FakeDoc(self._col)


# ── Tests ──────────────────────────────────────────────────────────────

def test_paused_backend_restart_now_in_stuck_set():
    """The 2026-05-22 bug. St Bernard was stuck in
    paused_backend_restart and the previous sweep ignored it.
    Extended stuck_set must catch it."""
    store = {
        "rid-stbernard": {
            "status": "paused_backend_restart",
            "deviceId": "dev-1",
            "topic": "St Bernard",
        },
    }
    db = _FakeDB(store)
    n, fail = _sweep_stuck_research_docs(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    assert n == 1
    assert fail == 0
    # Post-sweep status reflects the patch
    assert store["rid-stbernard"]["status"] == "stopped"
    # 2026-05-26: `cancelled` is set ONLY for queued (pre-claim) runs. A
    # paused_backend_restart run has partial work (browser state, emitted
    # phase events), so the sweep leaves it as a historical "Stopped" entry
    # — cancelled unset — rather than triggering the FE cascade-delete that
    # cancelled=true fires. (Was asserting the pre-2026-05-26 behavior.)
    assert "cancelled" not in store["rid-stbernard"]
    assert store["rid-stbernard"]["stoppedBy"] == "hard_reset_sweep"
    assert store["rid-stbernard"]["summary"] == "Cancelled by Reset Backend"
    # Position fields removed
    assert "queuePosition" not in store["rid-stbernard"]
    assert "queuedBehindRunId" not in store["rid-stbernard"]


def test_queued_status_now_swept():
    """Pre-claim queued docs the BE never got to. User req: 'unpair
    must be able to clean queue stuff'."""
    store = {
        "rid-queued": {"status": "queued", "deviceId": "dev-1", "topic": "Q"},
    }
    db = _FakeDB(store)
    n, _ = _sweep_stuck_research_docs(
        db, "owner-uid", "dev-1",
        stopped_by="unpair_sweep", summary="Cancelled by Unpair",
    )
    assert n == 1
    assert store["rid-queued"]["status"] == "stopped"
    # Queued (pre-claim) runs DO get cancelled=true — no partial work to
    # preserve, so the FE cascade-delete is the desired outcome (2026-05-26).
    assert store["rid-queued"]["cancelled"] is True
    assert store["rid-queued"]["stoppedBy"] == "unpair_sweep"
    assert store["rid-queued"]["summary"] == "Cancelled by Unpair"


def test_paused_backend_restart_failed_also_swept():
    store = {
        "rid-failed": {"status": "paused_backend_restart_failed", "deviceId": "dev-1"},
    }
    db = _FakeDB(store)
    n, _ = _sweep_stuck_research_docs(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    assert n == 1


def test_ongoing_running_paused_still_swept():
    """Existing behavior preserved — extending stuck_set must not
    REMOVE prior coverage."""
    store = {
        "rid-ongoing": {"status": "ongoing", "deviceId": "dev-1"},
        "rid-running": {"status": "running", "deviceId": "dev-1"},
        "rid-paused": {"status": "paused", "deviceId": "dev-1"},
    }
    db = _FakeDB(store)
    n, _ = _sweep_stuck_research_docs(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    assert n == 3


# ── Statuses that must NOT be swept (audit-trail) ──────────────────────

def test_user_terminal_states_not_swept():
    """User-driven terminal states are audit trail. Don't touch them
    — even on Reset BE, the user's "stopped" or "completed" should
    not become "cancelled by reset"."""
    store = {
        "rid-stopped": {"status": "stopped", "deviceId": "dev-1"},
        "rid-completed": {"status": "completed", "deviceId": "dev-1"},
        "rid-discard": {"status": "terminated_by_user_discard", "deviceId": "dev-1"},
        "rid-watchdog": {"status": "stopped_by_watchdog", "deviceId": "dev-1"},
    }
    db = _FakeDB(store)
    n, _ = _sweep_stuck_research_docs(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    assert n == 0
    # Original statuses preserved
    assert store["rid-stopped"]["status"] == "stopped"
    assert store["rid-completed"]["status"] == "completed"
    assert store["rid-discard"]["status"] == "terminated_by_user_discard"
    assert store["rid-watchdog"]["status"] == "stopped_by_watchdog"


# ── Per-doc failure path ───────────────────────────────────────────────

def test_per_doc_update_failure_counted_continues():
    """If one doc's update fails, sweep continues + reports
    `(swept, fail)` accurately. The failure shouldn't abort
    remaining docs."""
    store = {
        "rid-ok": {"status": "ongoing", "deviceId": "dev-1"},
        "rid-bad": {"status": "ongoing", "deviceId": "dev-1"},
        "rid-also-ok": {"status": "paused_backend_restart", "deviceId": "dev-1"},
    }
    db = _FakeDB(store, fail_doc_ids=["rid-bad"])
    n, fail = _sweep_stuck_research_docs(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    assert n == 2
    assert fail == 1
    assert store["rid-ok"]["status"] == "stopped"
    assert store["rid-also-ok"]["status"] == "stopped"
    assert store["rid-bad"]["status"] == "ongoing"  # update failed → unchanged


# ── Guard clauses ──────────────────────────────────────────────────────

def test_missing_db_returns_zero():
    n, fail = _sweep_stuck_research_docs(
        None, "owner-uid", "dev-1",
        stopped_by="x", summary="y",
    )
    assert (n, fail) == (0, 0)


def test_missing_uid_returns_zero():
    n, fail = _sweep_stuck_research_docs(
        _FakeDB({}), "", "dev-1",
        stopped_by="x", summary="y",
    )
    assert (n, fail) == (0, 0)


def test_missing_device_id_returns_zero():
    n, fail = _sweep_stuck_research_docs(
        _FakeDB({}), "owner-uid", "",
        stopped_by="x", summary="y",
    )
    assert (n, fail) == (0, 0)


# ── stopped_by + summary parametrization (HARD_RESET vs unpair) ────────

def test_audit_trail_distinguishes_hard_reset_from_unpair():
    """Both contexts use the same helper but write different
    stoppedBy/summary so post-incident audits can tell which path
    cancelled a given run."""
    store_a = {"rid-a": {"status": "ongoing", "deviceId": "dev-1"}}
    db_a = _FakeDB(store_a)
    _sweep_stuck_research_docs(
        db_a, "uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    assert store_a["rid-a"]["stoppedBy"] == "hard_reset_sweep"
    assert store_a["rid-a"]["summary"] == "Cancelled by Reset Backend"

    store_b = {"rid-b": {"status": "queued", "deviceId": "dev-1"}}
    db_b = _FakeDB(store_b)
    _sweep_stuck_research_docs(
        db_b, "uid", "dev-1",
        stopped_by="unpair_sweep", summary="Cancelled by Unpair",
    )
    assert store_b["rid-b"]["stoppedBy"] == "unpair_sweep"
    assert store_b["rid-b"]["summary"] == "Cancelled by Unpair"
