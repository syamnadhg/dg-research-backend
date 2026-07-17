"""#966 — per-worker rehydration ownership.

Before #966, `_rehydrate_ongoing_for_tree` ran on worker 1 ONLY. In a multi-
worker fleet, a fleet-wide respawn left worker-2-owned runs marked
`paused_backend_restart` by worker 1 (worker 1 can't auto-resume them onto its
own profile) while worker 2 never scanned Firestore to recover its own — so the
user saw a needless Resume CTA for a run the fleet could self-heal.

The fix: EVERY worker rehydrates, keyed on per-run ownership (`_owner_worker_of`
of the `assignedWorker` field):
  • I own it            → auto-resume (supervised) or mark paused.
  • a live sibling owns → LEAVE IT (that worker recovers its own run).
  • orphan (owner ∉ fleet) → worker 1 ALONE marks it paused (safety net).

These lock the ownership routing. The supervised auto-resume enqueue itself is
covered by test_sharer_rehydration.py (identical helper, worker-1/legacy owner).

Run:  pytest tests/test_per_worker_rehydration_966.py -v
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


# ── Minimal Firestore fakes (mirrors test_sharer_rehydration.py) ───────────
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
        return _UserDevicesCol()


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
        self.researches = {}
        self.devices = {}

    def collection(self, name):
        if name == "users":
            return _UsersCol(self)
        if name == "devices":
            return _DevicesCol(self)
        raise AssertionError(f"unexpected collection {name}")


def _setup(monkeypatch, *, worker_id, fleet, researches, devices=None, siblings=None):
    db = _FakeDB()
    db.researches = researches
    db.devices = devices or {}
    monkeypatch.setattr(research, "_firebase_db", db, raising=False)
    monkeypatch.setattr(research, "WORKER_ID", worker_id, raising=False)
    monkeypatch.setattr(research, "load_worker_count", lambda: fleet)
    updates = []
    enqueues = []
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda uid, rid, patch: (updates.append((uid, rid, patch)) or True))
    monkeypatch.setattr(research, "_safe_enqueue",
                        lambda q, job, source=None: (enqueues.append(job) or True))
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research",
                        lambda rid, wid: (siblings or {}).get(rid, []))
    return updates, enqueues


def _run(tree="owner-uid"):
    seen = set()
    r, o = asyncio.run(research._rehydrate_ongoing_for_tree(tree, "owner-uid", seen))
    return r, o, seen


def _ongoing(rid, assigned, *, device="dev1"):
    d = {"deviceId": device, "status": "ongoing"}
    if assigned is not None:
        d["assignedWorker"] = assigned
    return _Snap(rid, d)


# ── _owner_worker_of unit table ────────────────────────────────────────────
def test_owner_worker_of_maps_field_to_worker():
    ow = research._owner_worker_of
    assert ow(None) == 1          # unstamped → legacy primary
    assert ow("") == 1            # blank → legacy primary
    assert ow(0) == 1             # 0 is not a valid worker id → primary
    assert ow(-4) == 1            # negative → primary
    assert ow(1) == 1
    assert ow(2) == 2
    assert ow(7) == 7
    assert ow("2") == 2           # numeric string coerces
    assert ow(3.0) == 3           # float coerces
    assert ow("garbage") == 1     # non-numeric → primary (fail-safe)
    assert ow({}) == 1            # wrong type → primary (fail-safe)


# ── worker 1 leaves an in-fleet sibling's run alone (THE #966 bug) ─────────
def test_worker1_leaves_in_fleet_sibling_run(monkeypatch):
    updates, enqueues = _setup(
        monkeypatch, worker_id=1, fleet=2,
        researches={"owner-uid": [_ongoing("rid1", 2)]},
        devices={"dev1": _DevSnap(True, {"supervised": True})},
    )
    r, o, seen = _run()
    assert (r, o) == (0, 0)            # NOT marked paused — worker 2 recovers it
    assert updates == []
    assert enqueues == []
    assert "rid1" in seen             # still tracked so disk-restore won't re-enqueue


# ── worker 2 now recovers its OWN run (pre-#966 it skipped scanning) ───────
def test_worker2_recovers_its_own_run(monkeypatch):
    updates, enqueues = _setup(
        monkeypatch, worker_id=2, fleet=2,
        researches={"owner-uid": [_ongoing("rid2", 2)]},
        devices={"dev1": _DevSnap(True, {"supervised": False})},  # unsupervised → mark paused
    )
    r, o, seen = _run()
    assert (r, o) == (0, 1)            # worker 2 handles its own run
    assert len(updates) == 1
    assert updates[0][1] == "rid2"
    assert updates[0][2]["status"] == "paused_backend_restart"


# ── worker 1 does NOT touch a worker-2-owned run even when it's THIS worker's
#    sibling (only worker 2 should) ─────────────────────────────────────────
def test_worker1_ignores_worker2_owned_run_no_double_write(monkeypatch):
    updates, _ = _setup(
        monkeypatch, worker_id=1, fleet=3,
        researches={"owner-uid": [_ongoing("rid3", 2)]},
        devices={"dev1": _DevSnap(True, {"supervised": False})},
    )
    r, o, _ = _run()
    assert (r, o) == (0, 0)
    assert updates == []


# ── orphan: owner ∉ fleet → worker 1 marks it paused (safety net) ──────────
def test_worker1_marks_orphan_out_of_fleet(monkeypatch):
    updates, _ = _setup(
        monkeypatch, worker_id=1, fleet=2,
        researches={"owner-uid": [_ongoing("rid4", 3)]},  # owner 3, fleet only 1-2
        devices={"dev1": _DevSnap(True, {"supervised": True})},
    )
    r, o, _ = _run()
    assert (r, o) == (0, 1)
    assert updates[0][1] == "rid4"
    assert updates[0][2]["status"] == "paused_backend_restart"


# ── orphan: a non-worker-1 must NOT mark it (worker 1 is the sole marker) ──
def test_worker2_leaves_orphan_for_worker1(monkeypatch):
    updates, _ = _setup(
        monkeypatch, worker_id=2, fleet=2,
        researches={"owner-uid": [_ongoing("rid5", 3)]},  # orphan owner 3
        devices={"dev1": _DevSnap(True, {"supervised": True})},
    )
    r, o, seen = _run()
    assert (r, o) == (0, 0)
    assert updates == []
    assert "rid5" in seen


# ── fleet shrank to 1 → a worker-2-owned run is now an orphan; worker 1 marks
def test_worker1_marks_orphan_when_fleet_shrank(monkeypatch):
    updates, _ = _setup(
        monkeypatch, worker_id=1, fleet=1,
        researches={"owner-uid": [_ongoing("rid6", 2)]},  # owner 2 no longer in a 1-worker fleet
        devices={"dev1": _DevSnap(True, {"supervised": True})},
    )
    r, o, _ = _run()
    assert (r, o) == (0, 1)
    assert updates[0][2]["status"] == "paused_backend_restart"


# ── legacy (unstamped assignedWorker) belongs to worker 1 ─────────────────
def test_legacy_unstamped_owner_is_worker1(monkeypatch):
    # worker 1 owns + marks it (unsupervised)
    updates, _ = _setup(
        monkeypatch, worker_id=1, fleet=2,
        researches={"owner-uid": [_ongoing("rid7", None)]},
        devices={"dev1": _DevSnap(True, {"supervised": False})},
    )
    r, o, _ = _run()
    assert (r, o) == (0, 1)
    assert updates[0][2]["status"] == "paused_backend_restart"


def test_worker2_leaves_legacy_run_for_worker1(monkeypatch):
    # worker 2 must LEAVE an unstamped (owner==1) run for worker 1
    updates, _ = _setup(
        monkeypatch, worker_id=2, fleet=2,
        researches={"owner-uid": [_ongoing("rid8", None)]},
        devices={"dev1": _DevSnap(True, {"supervised": False})},
    )
    r, o, seen = _run()
    assert (r, o) == (0, 0)
    assert updates == []
    assert "rid8" in seen


# ── sibling-lock guard still wins over ownership (no dual-spawn) ───────────
def test_sibling_lock_guard_precedes_ownership(monkeypatch):
    # worker 1 owns rid9 by field, but a live sibling holds the lock → skip.
    updates, enqueues = _setup(
        monkeypatch, worker_id=1, fleet=2,
        researches={"owner-uid": [_ongoing("rid9", 1)]},
        devices={"dev1": _DevSnap(True, {"supervised": True})},
        siblings={"rid9": [{"worker_id": 2, "pid": 999, "started_at": 0}]},
    )
    r, o, seen = _run()
    assert (r, o) == (0, 0)
    assert updates == [] and enqueues == []
    assert "rid9" in seen
