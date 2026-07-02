"""#890 — devices/{id}.queueOwners must cover LOCALLY-claimed queued jobs.

A busy SINGLE-worker install claims every submit immediately (research doc
stamped status="queued", queue doc deleted at claim), so locally-queued runs
never appear in the devices/{id}/queue scan — pre-fix, the owner's
"Shared with" popup showed no amber #N badge for them (the agent-fired-run
symptom; web-fired sharer runs on a busy single-worker device had the same
gap). The fix publishes the UNION: local pending deque first (positions
1..N), Firestore-deferred docs after (offset by N).
"""
import re
import inspect
import types
from collections import deque

import research


# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeSnap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _FakeQueueCol:
    def __init__(self, docs):
        self._docs = docs

    def limit(self, _n):
        return self

    def stream(self):
        return list(self._docs)


class _FakeDeviceGet:
    exists = False


class _FakeDeviceDoc:
    def __init__(self, db, queue_docs):
        self._db = db
        self._queue_docs = queue_docs

    def collection(self, name):
        assert name == "queue"
        return _FakeQueueCol(self._queue_docs)

    def get(self):
        return _FakeDeviceGet()

    def update(self, payload):
        self._db.device_updates.append(payload)


class _FakeUserDoc:
    def collection(self, _name):
        return self

    def document(self, _rid):
        return self


class _FakeBatch:
    def __init__(self, db):
        self._db = db

    def update(self, _ref, payload):
        self._db.batch_payloads.append(payload)

    def commit(self):
        pass


class _FakeDB:
    def __init__(self, queue_docs):
        self._queue_docs = queue_docs
        self.device_updates = []
        self.batch_payloads = []

    def collection(self, name):
        if name == "devices":
            return self
        return _FakeUserDoc()  # users tree — patches recorded via batch

    def document(self, _did):
        return _FakeDeviceDoc(self, self._queue_docs)

    def batch(self):
        return _FakeBatch(self)


def _local_job(uid, rid, topic):
    return {"uid": uid, "research_id": rid, "topic": topic}


def _deferred_doc(doc_id, uid, rid, topic, ts):
    return _FakeSnap(doc_id, {
        "uid": uid, "submittedBy": uid, "researchId": rid, "topic": topic,
        "action": "start", "timestamp": ts,
    })


def _run_locked(monkeypatch, *, local_jobs, queue_docs, worker_count=1):
    db = _FakeDB(queue_docs)
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-1")
    monkeypatch.setattr(research, "load_worker_count", lambda: worker_count)
    monkeypatch.setitem(
        research._QUEUE_STATE, "queue_ref",
        types.SimpleNamespace(_queue=deque(local_jobs)),
    )
    research._recompute_deferred_queue_positions_locked()
    return db


# ── _local_pending_owner_entries ─────────────────────────────────────────────

def test_local_entries_positions_and_skips(monkeypatch):
    jobs = [
        _local_job("uA", "r1", "Alpha " * 30),   # long title → truncated to 60
        {"topic": "resume-only", "resume_dir": "/x"},  # resume job — no uid/rid
        _local_job("uB", "r2", "Beta"),
    ]
    monkeypatch.setattr(research, "load_worker_count", lambda: 1)
    monkeypatch.setitem(
        research._QUEUE_STATE, "queue_ref",
        types.SimpleNamespace(_queue=deque(jobs)),
    )
    entries = research._local_pending_owner_entries()
    assert [e["runId"] for e in entries] == ["r1", "r2"]
    assert [e["position"] for e in entries] == [1, 2]  # resume job skipped, no gap
    assert entries[0]["uid"] == "uA" and len(entries[0]["title"]) == 60


def test_local_entries_empty_without_queue_ref(monkeypatch):
    monkeypatch.setattr(research, "load_worker_count", lambda: 1)
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", None)
    assert research._local_pending_owner_entries() == []


def test_local_entries_gated_off_on_multiworker(monkeypatch):
    # Multi-worker: every worker full-array-overwrites queueOwners, and sibling
    # deques are per-process — including local entries would let one worker's
    # publish erase another's. Deferred-only there (pre-#890 behavior).
    monkeypatch.setattr(research, "load_worker_count", lambda: 2)
    monkeypatch.setitem(
        research._QUEUE_STATE, "queue_ref",
        types.SimpleNamespace(_queue=deque([_local_job("uA", "r1", "Alpha")])),
    )
    assert research._local_pending_owner_entries() == []


def test_multiworker_publish_is_deferred_only(monkeypatch):
    db = _run_locked(
        monkeypatch,
        local_jobs=[_local_job("uL", "r-local", "Local Job")],
        queue_docs=[_deferred_doc("q1", "uD", "r-deferred", "Deferred Job", 1000)],
        worker_count=2,
    )
    owners = db.device_updates[-1]["queueOwners"]
    assert [(o["runId"], o["position"]) for o in owners] == [("r-deferred", 1)]


# ── the union publish ────────────────────────────────────────────────────────

def test_local_only_union_published_when_subcollection_empty(monkeypatch):
    # The core #890 case: single-worker busy claims → subcollection empty,
    # queued runs live only in the local deque. Pre-fix this published [].
    db = _run_locked(
        monkeypatch,
        local_jobs=[_local_job("sharer-1", "agent-abc", "EV Market")],
        queue_docs=[],
    )
    assert db.device_updates == [{
        "queueOwners": [
            {"uid": "sharer-1", "runId": "agent-abc", "title": "EV Market", "position": 1},
        ],
    }]


def test_union_orders_local_first_and_offsets_deferred(monkeypatch):
    db = _run_locked(
        monkeypatch,
        local_jobs=[_local_job("uL", "r-local", "Local Job")],
        queue_docs=[_deferred_doc("q1", "uD", "r-deferred", "Deferred Job", 1000)],
    )
    owners = db.device_updates[-1]["queueOwners"]
    assert [(o["runId"], o["position"]) for o in owners] == \
        [("r-local", 1), ("r-deferred", 2)]
    # The deferred doc's research-doc patch carries the OFFSET position and
    # points "behind" at the local tail (not the currently-running run).
    patch = db.batch_payloads[-1]
    assert patch["queuePosition"] == 2 and patch["queueTotalAhead"] == 1
    assert patch["queuedBehindRunId"] == "r-local"
    assert patch["queueAheadFromOthers"] == 1  # the local job, different uid


def test_empty_everything_clears_owners(monkeypatch):
    db = _run_locked(monkeypatch, local_jobs=[], queue_docs=[])
    assert db.device_updates == [{"queueOwners": []}]


def test_deferred_only_unchanged_semantics(monkeypatch):
    # No local jobs (the multi-worker defer case) — behavior identical to
    # pre-fix: positions 1..M, head has no behind fields pointing at local.
    db = _run_locked(
        monkeypatch,
        local_jobs=[],
        queue_docs=[
            _deferred_doc("q1", "uA", "rA", "A", 1000),
            _deferred_doc("q2", "uB", "rB", "B", 2000),
        ],
    )
    owners = db.device_updates[-1]["queueOwners"]
    assert [(o["runId"], o["position"]) for o in owners] == [("rA", 1), ("rB", 2)]
    head_patch = db.batch_payloads[0]
    assert head_patch["queuePosition"] == 1 and head_patch["queueTotalAhead"] == 0


# ── wiring source-guards (closures inside run_server) ────────────────────────

def test_local_recompute_kicks_owner_publish_even_when_drained():
    src = inspect.getsource(research)
    m = re.search(r"def _recompute_queue_positions\(\):(.*?)\n    # Expose the recompute",
                  src, re.S)
    assert m, "local recompute body not found"
    body = m.group(1)
    # Fired on the drained-deque early return AND after the renumber batches —
    # a stale amber badge would otherwise outlive the last pickup.
    assert body.count("_kick_owner_publish()") >= 2
    assert "_recompute_deferred_queue_positions" in body


def test_job_worker_pickup_refreshes_owner_union():
    src = inspect.getsource(research)
    m = re.search(r"async def _job_worker\(\):(.*?)Starting queued job", src, re.S)
    assert m, "_job_worker head not found"
    assert "_recompute_deferred_queue_positions" in m.group(1), (
        "job pickup must refresh the queueOwners union (the picked job just "
        "left the amber #N badge for the green workers.{id} pill)"
    )
