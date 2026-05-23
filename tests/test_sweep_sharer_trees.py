"""Unit tests for `_sweep_stuck_research_docs_for_device` — the
multi-user wrapper that extends the stale-research sweep to cover
sharer trees on Reset BE + unpair.

Bug D context (2026-05-22): the per-user `_sweep_stuck_research_docs`
helper introduced in ab119b2 cleaned the paired owner's research
collection, but sharer-submitted runs on the same device persisted as
zombie "ongoing" tiles after Reset BE / unpair. User explicitly
requested: "Device unpair must remove all the runs associated to it.
Even sharers right? Please fix that too."

The wrapper reads `devices/{deviceId}.sharedWith[]` and iterates the
per-user sweep over [owner, *sharers]. Firestore rules
(firestore.rules:45-49 `deviceMemberOf`) allow the synth-device-user
to read/write any user-tree where `deviceOwnership` is satisfied
(device's ownerUid OR sharedWith[] includes the userId).

Run via:
    pytest tests/test_sweep_sharer_trees.py -v
"""
from __future__ import annotations

import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import _sweep_stuck_research_docs_for_device  # noqa: E402


# ── Fakes ──────────────────────────────────────────────────────────────

class _FakeRef:
    def __init__(self, doc_id, store, fail_on_update=False):
        self.id = doc_id
        self._store = store
        self._fail = fail_on_update

    def update(self, patch):
        if self._fail:
            raise RuntimeError(f"simulated update failure for {self.id}")
        if self.id not in self._store:
            raise RuntimeError(f"doc {self.id} disappeared")
        from google.cloud.firestore import DELETE_FIELD as _DF
        cur = self._store[self.id]
        for k, v in patch.items():
            if v is _DF:
                cur.pop(k, None)
            else:
                cur[k] = v


class _FakeSnap:
    def __init__(self, doc_id, payload, store=None, fail_on_update=False, exists=True):
        self.id = doc_id
        self._payload = payload
        self.exists = exists
        if store is not None:
            self.reference = _FakeRef(doc_id, store, fail_on_update=fail_on_update)

    def to_dict(self):
        return dict(self._payload)


class _FakeResearchQuery:
    def __init__(self, snaps):
        self._snaps = snaps

    def stream(self):
        return iter(self._snaps)


class _FakeResearchCol:
    def __init__(self, store, fail_query=False):
        self._store = store
        self._fail = fail_query

    def where(self, _field, _op, _value):
        if self._fail:
            raise RuntimeError("simulated PERMISSION_DENIED on query")
        snaps = [
            _FakeSnap(did, dict(p), self._store)
            for did, p in self._store.items()
        ]
        return _FakeResearchQuery(snaps)


class _FakeUserDoc:
    def __init__(self, research_col):
        self._col = research_col

    def collection(self, name):
        assert name == "researches"
        return self._col


class _FakeDeviceRef:
    def __init__(self, payload, exists=True):
        self._payload = payload
        self.exists = exists

    def get(self):
        # Returns a snap-like object with .exists + .to_dict()
        return _FakeSnap("device-doc", self._payload, exists=self.exists)


class _FakeDevicesCol:
    def __init__(self, device_payload, device_exists=True, device_get_raises=False):
        self._payload = device_payload
        self._exists = device_exists
        self._raise = device_get_raises

    def document(self, _device_id):
        if self._raise:
            class _RaisingRef:
                def get(_):
                    raise RuntimeError("simulated device-doc read failure")
            return _RaisingRef()
        return _FakeDeviceRef(self._payload, exists=self._exists)


class _FakeDB:
    """Routes `collection("users")` and `collection("devices")` to
    different fake collections."""
    def __init__(self, per_user_stores: "dict[str, dict]", device_payload: dict, *,
                 device_exists=True, device_get_raises=False,
                 failing_user_uids=None):
        self._per_user = per_user_stores  # {uid: {doc_id: payload}}
        self._device_payload = device_payload
        self._device_exists = device_exists
        self._device_get_raises = device_get_raises
        self._fail_user_set = set(failing_user_uids or [])

    def collection(self, name):
        if name == "devices":
            return _FakeDevicesCol(
                self._device_payload,
                device_exists=self._device_exists,
                device_get_raises=self._device_get_raises,
            )
        if name == "users":
            db = self

            class _UsersCol:
                def document(_inner, uid):
                    store = db._per_user.get(uid, {})
                    fail = uid in db._fail_user_set
                    return _FakeUserDoc(_FakeResearchCol(store, fail_query=fail))
            return _UsersCol()
        raise AssertionError(f"unexpected collection name: {name}")


# ── Tests ──────────────────────────────────────────────────────────────

def test_no_sharers_falls_back_to_owner_only():
    """device.sharedWith is empty — wrapper behaves exactly like the
    original owner-only sweep."""
    owner_store = {
        "rid-1": {"status": "ongoing", "deviceId": "dev-1"},
    }
    db = _FakeDB(
        per_user_stores={"owner-uid": owner_store},
        device_payload={"sharedWith": []},
    )
    n, fail = _sweep_stuck_research_docs_for_device(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    assert n == 1
    assert fail == 0
    assert owner_store["rid-1"]["status"] == "stopped"


def test_one_sharer_with_stale_run_swept():
    """The 2026-05-22 Bug D case. Sharer's research is in
    paused_backend_restart on this device; wrapper sweeps it."""
    owner_store = {
        "rid-owner": {"status": "ongoing", "deviceId": "dev-1"},
    }
    sharer_store = {
        "rid-sharer": {"status": "paused_backend_restart", "deviceId": "dev-1",
                       "topic": "Sharer's run"},
    }
    db = _FakeDB(
        per_user_stores={
            "owner-uid": owner_store,
            "sharer-uid-1": sharer_store,
        },
        device_payload={"sharedWith": ["sharer-uid-1"]},
    )
    n, fail = _sweep_stuck_research_docs_for_device(
        db, "owner-uid", "dev-1",
        stopped_by="unpair_sweep", summary="Cancelled by Unpair",
    )
    assert n == 2
    assert fail == 0
    assert owner_store["rid-owner"]["status"] == "stopped"
    assert sharer_store["rid-sharer"]["status"] == "stopped"
    assert sharer_store["rid-sharer"]["stoppedBy"] == "unpair_sweep"


def test_multiple_sharers():
    """Device has owner + 2 sharers, all with runs. All swept."""
    db = _FakeDB(
        per_user_stores={
            "owner-uid": {"rid-o": {"status": "ongoing", "deviceId": "dev-1"}},
            "sharer-a": {"rid-a": {"status": "queued", "deviceId": "dev-1"}},
            "sharer-b": {"rid-b": {"status": "paused", "deviceId": "dev-1"}},
        },
        device_payload={"sharedWith": ["sharer-a", "sharer-b"]},
    )
    n, fail = _sweep_stuck_research_docs_for_device(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    assert n == 3
    assert fail == 0


def test_sharer_with_no_runs_skipped():
    """Sharer is listed in sharedWith but has no runs on this device.
    No-op for that sharer (sweep returns 0); other trees still
    processed."""
    db = _FakeDB(
        per_user_stores={
            "owner-uid": {"rid-o": {"status": "ongoing", "deviceId": "dev-1"}},
            "sharer-empty": {},  # no runs
        },
        device_payload={"sharedWith": ["sharer-empty"]},
    )
    n, fail = _sweep_stuck_research_docs_for_device(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    assert n == 1
    assert fail == 0


def test_device_doc_read_fails_falls_back_to_owner_only():
    """If reading devices/{id} raises (e.g., revoked token mid-unpair),
    wrapper falls back to owner-only sweep instead of bailing
    entirely."""
    owner_store = {
        "rid-1": {"status": "ongoing", "deviceId": "dev-1"},
    }
    db = _FakeDB(
        per_user_stores={"owner-uid": owner_store},
        device_payload={},
        device_get_raises=True,
    )
    n, fail = _sweep_stuck_research_docs_for_device(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    # Owner still swept; sharedWith unreachable so 0 sharers processed
    assert n == 1
    assert fail == 0


def test_per_sharer_sweep_failure_continues():
    """One sharer's sweep raises (PERMISSION_DENIED simulation). Other
    sharers + owner still processed."""
    db = _FakeDB(
        per_user_stores={
            "owner-uid": {"rid-o": {"status": "ongoing", "deviceId": "dev-1"}},
            "sharer-bad": {"rid-x": {"status": "ongoing", "deviceId": "dev-1"}},
            "sharer-good": {"rid-y": {"status": "queued", "deviceId": "dev-1"}},
        },
        device_payload={"sharedWith": ["sharer-bad", "sharer-good"]},
        failing_user_uids=["sharer-bad"],
    )
    n, fail = _sweep_stuck_research_docs_for_device(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    # Owner (1) + sharer-good (1) succeed; sharer-bad raises and is
    # logged + skipped. n counts only successful sweeps.
    assert n == 2


def test_owner_listed_in_shared_with_not_double_swept():
    """Defensive: a mis-configured device doc with the owner listed in
    sharedWith[] must not cause double-sweep of the owner's tree."""
    owner_store = {
        "rid-1": {"status": "ongoing", "deviceId": "dev-1"},
    }
    db = _FakeDB(
        per_user_stores={"owner-uid": owner_store},
        device_payload={"sharedWith": ["owner-uid", "sharer-x"]},  # owner in shared
    )
    # No sharer-x store, so just owner gets swept once
    n, fail = _sweep_stuck_research_docs_for_device(
        db, "owner-uid", "dev-1",
        stopped_by="hard_reset_sweep", summary="Cancelled by Reset Backend",
    )
    # Owner gets swept ONCE despite appearing in sharedWith too
    assert n == 1
    # Verify doc was actually only patched once (status flipped to stopped, not re-stopped)
    assert owner_store["rid-1"]["status"] == "stopped"


def test_guard_clauses_still_apply():
    """Inherited from _sweep_stuck_research_docs: missing args → (0, 0)."""
    db = _FakeDB({}, {})
    assert _sweep_stuck_research_docs_for_device(
        None, "uid", "dev", stopped_by="x", summary="y"
    ) == (0, 0)
    assert _sweep_stuck_research_docs_for_device(
        db, "", "dev", stopped_by="x", summary="y"
    ) == (0, 0)
    assert _sweep_stuck_research_docs_for_device(
        db, "uid", "", stopped_by="x", summary="y"
    ) == (0, 0)
