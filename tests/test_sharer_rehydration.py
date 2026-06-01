"""Tests for #724 item 3 — sharer-tree rehydration helper.

`_rehydrate_ongoing_for_tree(tree_uid, owner_uid, rehydrated_rids)` recovers
status=="ongoing" runs in users/{tree_uid}/researches on worker reboot: mark
paused_backend_restart (unsupervised) or auto-resume (supervised). It's the
factored-out core that the flag-gated sharer loop calls per sharer uid, so the
key contracts to lock are: writes target tree_uid (the SHARER, not the owner),
a sibling-held run is skipped (no dual-spawn), and rehydrated_rids accumulates.

Run:  pytest tests/test_sharer_rehydration.py -v
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


# ── Minimal Firestore fakes ────────────────────────────────────────────
class _Snap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._d = data

    def to_dict(self):
        return self._d


class _DevSnap:
    def __init__(self, exists, data=None):
        self.exists = exists
        self._d = data or {}

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


class _MissingDocRef:
    """A users/{uid}/devices/{id} ref — always a clean miss (legacy fallback)."""
    def get(self):
        return _DevSnap(False)


class _UserDevicesCol:
    def document(self, _id):
        return _MissingDocRef()


class _UserDocRef:
    def __init__(self, db, uid):
        self._db = db
        self._uid = uid

    def collection(self, name):
        if name == "researches":
            return _ResearchesCol(self._db.researches.get(self._uid, []))
        return _UserDevicesCol()  # "devices" (legacy) — clean miss


class _DeviceDocRef:
    def __init__(self, db, device_id):
        self._db = db
        self._id = device_id

    def get(self):
        return self._db.devices.get(self._id, _DevSnap(False))


class _UsersCol:
    def __init__(self, db):
        self._db = db

    def document(self, uid):
        return _UserDocRef(self._db, uid)


class _DevicesCol:
    def __init__(self, db):
        self._db = db

    def document(self, device_id):
        return _DeviceDocRef(self._db, device_id)


class _FakeDB:
    def __init__(self):
        self.researches = {}   # uid -> [_Snap]
        self.devices = {}      # device_id -> _DevSnap

    def collection(self, name):
        if name == "users":
            return _UsersCol(self)
        if name == "devices":
            return _DevicesCol(self)
        raise AssertionError(f"unexpected collection {name}")


def _setup(monkeypatch, *, researches, devices=None, siblings=None):
    db = _FakeDB()
    db.researches = researches
    db.devices = devices or {}
    monkeypatch.setattr(research, "_firebase_db", db, raising=False)
    updates = []
    enqueues = []
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda uid, rid, patch: (updates.append((uid, rid, patch)) or True))
    monkeypatch.setattr(research, "_safe_enqueue",
                        lambda q, job, source=None: (enqueues.append(job) or True))
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research",
                        lambda rid, wid: (siblings or {}).get(rid, []))
    return updates, enqueues


def test_unsupervised_marks_paused_on_sharer_tree(monkeypatch):
    updates, enqueues = _setup(
        monkeypatch,
        researches={"sharer-uid": [_Snap("rid1", {"deviceId": "dev1", "status": "ongoing"})]},
        devices={"dev1": _DevSnap(True, {"supervised": False})},
    )
    seen = set()
    r, o = asyncio.run(research._rehydrate_ongoing_for_tree("sharer-uid", "owner-uid", seen))
    assert (r, o) == (0, 1)
    assert len(updates) == 1
    uid, rid, patch = updates[0]
    assert uid == "sharer-uid"          # writes target the SHARER tree, not the owner
    assert rid == "rid1"
    assert patch["status"] == "paused_backend_restart"
    assert enqueues == []               # unsupervised → no auto-resume
    assert "rid1" in seen               # rehydrated_rids accumulates


def test_sibling_held_run_is_skipped(monkeypatch):
    updates, enqueues = _setup(
        monkeypatch,
        researches={"sharer-uid": [_Snap("rid2", {"deviceId": "dev1", "status": "ongoing"})]},
        devices={"dev1": _DevSnap(True, {"supervised": False})},
        siblings={"rid2": [{"worker_id": 2, "pid": 999, "started_at": 0}]},
    )
    seen = set()
    r, o = asyncio.run(research._rehydrate_ongoing_for_tree("sharer-uid", "owner-uid", seen))
    assert (r, o) == (0, 0)             # sibling owns it — no mark, no resume
    assert updates == []
    assert enqueues == []
    assert "rid2" in seen               # still tracked so disk-restore won't re-enqueue


def test_supervised_without_disk_artifacts_falls_back_to_paused(monkeypatch):
    # Supervised device but the on-disk queue_dir for this run_id doesn't exist
    # → can't auto-resume → mark paused_backend_restart instead.
    updates, enqueues = _setup(
        monkeypatch,
        researches={"sharer-uid": [_Snap("rid3", {
            "deviceId": "dev1", "status": "ongoing",
            "backendRunId": "nonexistent-run-id-xyz",
        })]},
        devices={"dev1": _DevSnap(True, {"supervised": True})},
    )
    seen = set()
    r, o = asyncio.run(research._rehydrate_ongoing_for_tree("sharer-uid", "owner-uid", seen))
    assert (r, o) == (0, 1)
    assert enqueues == []
    assert updates[0][2]["status"] == "paused_backend_restart"


def test_no_ongoing_runs_is_noop(monkeypatch):
    updates, enqueues = _setup(monkeypatch, researches={"sharer-uid": []})
    seen = set()
    r, o = asyncio.run(research._rehydrate_ongoing_for_tree("sharer-uid", "owner-uid", seen))
    assert (r, o) == (0, 0)
    assert updates == [] and enqueues == [] and seen == set()
