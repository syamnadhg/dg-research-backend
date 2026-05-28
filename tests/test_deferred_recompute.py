"""Unit tests for `_recompute_deferred_queue_positions` — the real-time
position renumber that runs after a deferred queue doc transitions out
of the Firestore queue (claimed by a worker, or cancelled mid-defer).

Bug context (2026-05-22): the 5-fire scenario showed that when Husky
got claimed, Bull Dog's queuePosition stayed at 2 and St Bernard's at 3
even though the actual queue head was now Bull Dog. Local-deque
`_recompute_queue_positions` (run_server closure ~line 27030) only sees
jobs that have already been claimed and put on `_job_queue._queue`; it
cannot see Firestore-deferred docs.

The new helper does ONE Firestore scan, applies the same FIFO sort +
filter as `_compute_global_queue_position` (so callers + pre-claim
agree on ordering), and commits a WriteBatch updating every remaining
deferred doc's research-doc.

Wired into:
  - Listener claim path (research.py:~4880)
  - Idle-rescan after claim (research.py:~27620)
  - _do_cancel deferred-cancel branch (research.py:~4230)

Run via:
    pytest tests/test_deferred_recompute.py -v
"""
from __future__ import annotations

import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research as research_mod  # noqa: E402


# ── Fakes ──────────────────────────────────────────────────────────────

class _FakeSnap:
    def __init__(self, doc_id: str, payload: "dict[str, Any]"):
        self.id = doc_id
        self._payload = payload

    def to_dict(self):
        return dict(self._payload)


class _FakeServerTs:
    def __init__(self, epoch_ms: int):
        self._epoch_ms = epoch_ms

    def timestamp(self) -> float:
        return self._epoch_ms / 1000.0


class _FakeBatch:
    """Captures `update` calls so tests can assert batch contents."""

    def __init__(self, sink: list, commit_should_raise: bool = False):
        self._sink = sink
        self._raise = commit_should_raise

    def update(self, ref, patch):
        # ref carries (uid, rid) via the fake research-doc ref pattern
        self._sink.append((ref.uid, ref.rid, dict(patch)))

    def commit(self):
        if self._raise:
            raise RuntimeError("simulated batch commit failure")


class _FakeResearchRef:
    def __init__(self, uid: str, rid: str):
        self.uid = uid
        self.rid = rid


class _FakeUserDoc:
    def __init__(self, uid: str):
        self._uid = uid

    def collection(self, name):
        assert name == "researches"

        class _ResearchCol:
            def __init__(_inner, uid):
                _inner._uid = uid

            def document(_inner, rid):
                return _FakeResearchRef(_inner._uid, rid)

        return _ResearchCol(self._uid)


class _FakeDeviceQueue:
    def __init__(self, store: dict, raise_on_stream: bool = False):
        self._store = store
        self._raise = raise_on_stream

    def limit(self, _n):
        return self

    def stream(self):
        if self._raise:
            raise RuntimeError("simulated Firestore unavailability")
        return iter(
            _FakeSnap(did, dict(p)) for did, p in self._store.items()
        )


class _FakeDevSnap:
    def __init__(self, exists: bool, payload: "dict | None" = None):
        self.exists = exists
        self._payload = payload or {}

    def to_dict(self):
        return dict(self._payload)


class _FakeDeviceDoc:
    def __init__(self, queue_store: dict, device_writes: list,
                 raise_on_stream: bool = False):
        self._queue = _FakeDeviceQueue(queue_store, raise_on_stream=raise_on_stream)
        self._device_writes = device_writes

    def collection(self, name):
        assert name == "queue"
        return self._queue

    def get(self):
        # Device-doc ETA inputs read. Return exists=False so the recompute
        # falls back to its phase/worker defaults — matches the behavior from
        # before the fake gained this method, keeping position assertions
        # stable while still letting the queueOwners .update() be captured.
        return _FakeDevSnap(False)

    def update(self, patch):
        # Captures the queueOwners device-doc write (and the empty-queue
        # clears) so tests can assert the per-sharer amber-badge summary.
        self._device_writes.append(dict(patch))


class _FakeDB:
    def __init__(self, queue_store: dict, raise_on_stream: bool = False,
                 commit_should_raise: bool = False):
        self._queue_store = queue_store
        self._raise = raise_on_stream
        self._commit_raise = commit_should_raise
        self.batch_writes: "list[tuple[str, str, dict]]" = []
        self.device_writes: "list[dict]" = []

    def collection(self, name):
        if name == "devices":
            store_ref = self  # capture for inner class

            class _DevicesCol:
                def document(_inner, _device_id):
                    return _FakeDeviceDoc(store_ref._queue_store,
                                          store_ref.device_writes,
                                          raise_on_stream=store_ref._raise)

            return _DevicesCol()
        if name == "users":
            class _UsersCol:
                def document(_inner, uid):
                    return _FakeUserDoc(uid)

            return _UsersCol()
        raise AssertionError(f"unexpected collection: {name}")

    def batch(self):
        return _FakeBatch(self.batch_writes, commit_should_raise=self._commit_raise)


def _q_doc(*, timestamp_ms=None, submitted_at_ms=None, topic, rid, uid,
           assigned_worker=None, processed=False, action="start"):
    """Helper to build a queue-doc payload dict for the fake store."""
    p = {
        "topic": topic,
        "researchId": rid,
        "uid": uid,
        "submittedBy": uid,
        "action": action,
        "processed": processed,
    }
    if timestamp_ms is not None:
        p["timestamp"] = timestamp_ms
    if submitted_at_ms is not None:
        p["submittedAt"] = _FakeServerTs(submitted_at_ms)
    if assigned_worker is not None:
        p["assignedWorker"] = assigned_worker
    return p


# ── Test fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def stub_module(monkeypatch):
    """Stub module-level globals the helper reads. Restored after each
    test by monkeypatch."""
    # Force a known device_id so load_device_id returns something stable
    monkeypatch.setattr(research_mod, "load_device_id", lambda: "test-device-id")
    # Capture _be_payload calls — verify deviceId injection happens. For
    # tests we just want the patch dict as-is, no actual deviceId injection
    # interfering with assertions.
    monkeypatch.setattr(research_mod, "_be_payload", lambda d: dict(d))
    yield


# ── Tests ──────────────────────────────────────────────────────────────

def test_no_firestore_is_noop(stub_module, monkeypatch):
    """Helper bails cleanly when Firestore isn't initialised."""
    monkeypatch.setattr(research_mod, "_firebase_db", None)
    # Should not raise
    research_mod._recompute_deferred_queue_positions()


def test_no_device_id_is_noop(stub_module, monkeypatch):
    """Helper bails when load_device_id returns empty (unpaired BE)."""
    monkeypatch.setattr(research_mod, "load_device_id", lambda: "")
    monkeypatch.setattr(research_mod, "_firebase_db",
                        _FakeDB({"qd-a": _q_doc(timestamp_ms=1000, topic="A",
                                                rid="rid-a", uid="owner")}))
    research_mod._recompute_deferred_queue_positions()
    # The fake DB shouldn't have been touched — no device_id, no scan
    assert research_mod._firebase_db.batch_writes == []


def test_empty_queue_is_noop(stub_module, monkeypatch):
    db = _FakeDB({})
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    assert db.batch_writes == []
    # An empty queue clears queueOwners ([]) on the device doc so stale amber
    # badges from a drained queue don't linger in the "Shared with" popup.
    assert any(w.get("queueOwners") == [] for w in db.device_writes)


def test_scan_failure_logs_and_returns(stub_module, monkeypatch):
    """Best-effort: a Firestore error during scan logs at DEBUG and
    returns without raising."""
    db = _FakeDB({"qd-a": _q_doc(timestamp_ms=1000, topic="A",
                                 rid="rid-a", uid="owner")},
                 raise_on_stream=True)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    assert db.batch_writes == []


# ── The repro scenario ────────────────────────────────────────────────

def test_five_fire_repro_after_husky_claim(stub_module, monkeypatch):
    """The 2026-05-22 repro: after Husky got claimed (its queue doc
    deleted), Bull Dog and St Bernard remain deferred. The helper must
    renumber them so Bull Dog becomes #1 (clears behind fields — FE
    falls back to currentRunTitle for "behind running") and St Bernard
    becomes #2 (behind Bull Dog)."""
    queue_store = {
        # Husky's doc is gone (just claimed + deleted)
        "qd-bulldog": _q_doc(submitted_at_ms=2_000, topic="Bull Dog",
                             rid="rid-bulldog", uid="sharer-uid"),
        "qd-stbernard": _q_doc(submitted_at_ms=3_000, topic="St Bernard",
                               rid="rid-stbernard", uid="owner-uid"),
    }
    db = _FakeDB(queue_store)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()

    # Two writes — one per remaining deferred doc
    assert len(db.batch_writes) == 2
    by_rid = {rid: (uid, patch) for uid, rid, patch in db.batch_writes}

    # Bull Dog is now #1 — behind fields cleared
    bd_uid, bd_patch = by_rid["rid-bulldog"]
    assert bd_uid == "sharer-uid"
    assert bd_patch["queuePosition"] == 1
    # DELETE_FIELD sentinel for behind fields
    from google.cloud.firestore import DELETE_FIELD
    assert bd_patch["queuedBehindRunId"] is DELETE_FIELD
    assert bd_patch["queuedBehindTitle"] is DELETE_FIELD

    # St Bernard is now #2 — behind = Bull Dog
    sb_uid, sb_patch = by_rid["rid-stbernard"]
    assert sb_uid == "owner-uid"
    assert sb_patch["queuePosition"] == 2
    assert sb_patch["queuedBehindRunId"] == "rid-bulldog"
    assert sb_patch["queuedBehindTitle"] == "Bull Dog"

    # queueOwners device-doc summary published for the owner's "Shared with"
    # popup (amber #N badges, joined by sharer uid). FIFO order, 1-indexed.
    qo_writes = [w["queueOwners"] for w in db.device_writes if "queueOwners" in w]
    assert qo_writes, "expected a queueOwners device-doc write"
    assert [(o["uid"], o["runId"], o["title"], o["position"]) for o in qo_writes[-1]] == [
        ("sharer-uid", "rid-bulldog", "Bull Dog", 1),
        ("owner-uid", "rid-stbernard", "St Bernard", 2),
    ]


def test_claimed_docs_excluded_from_recount(stub_module, monkeypatch):
    """Docs with assignedWorker set are in transition (worker claimed,
    queue doc not yet deleted) — exclude them from the deferred count.
    The local-deque recompute handles them via the worker's local
    queue."""
    queue_store = {
        "qd-husky": _q_doc(submitted_at_ms=1_000, topic="Husky",
                           rid="rid-husky", uid="owner-uid",
                           assigned_worker=1),
        "qd-bulldog": _q_doc(submitted_at_ms=2_000, topic="Bull Dog",
                             rid="rid-bulldog", uid="sharer-uid"),
    }
    db = _FakeDB(queue_store)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    # Only Bull Dog renumbered — Husky's assignedWorker excludes it
    assert len(db.batch_writes) == 1
    uid, rid, patch = db.batch_writes[0]
    assert rid == "rid-bulldog"
    assert patch["queuePosition"] == 1


def test_processed_docs_excluded(stub_module, monkeypatch):
    queue_store = {
        "qd-stale": _q_doc(submitted_at_ms=500, topic="Stale",
                           rid="rid-stale", uid="owner-uid",
                           processed=True),
        "qd-active": _q_doc(submitted_at_ms=1000, topic="Active",
                            rid="rid-active", uid="owner-uid"),
    }
    db = _FakeDB(queue_store)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    assert len(db.batch_writes) == 1
    uid, rid, patch = db.batch_writes[0]
    assert rid == "rid-active"
    assert patch["queuePosition"] == 1


def test_non_start_actions_excluded(stub_module, monkeypatch):
    """Cancel/resume docs have their own dispatch paths — don't include
    them in queue numbering."""
    queue_store = {
        "qd-cancel": _q_doc(submitted_at_ms=500, topic="cancel-target",
                            rid="rid-x", uid="owner-uid", action="cancel"),
        "qd-resume": _q_doc(submitted_at_ms=600, topic="resume-target",
                            rid="rid-y", uid="owner-uid", action="resume"),
        "qd-start": _q_doc(submitted_at_ms=700, topic="Start",
                           rid="rid-z", uid="owner-uid"),
    }
    db = _FakeDB(queue_store)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    assert len(db.batch_writes) == 1
    uid, rid, patch = db.batch_writes[0]
    assert rid == "rid-z"
    assert patch["queuePosition"] == 1


# ── FIFO ordering ──────────────────────────────────────────────────────

def test_fifo_sort_by_submitted_at(stub_module, monkeypatch):
    """Ordering uses server timestamp (matches the C1 fix)."""
    queue_store = {
        # Intentionally insert in wrong order
        "qd-c": _q_doc(submitted_at_ms=3_000, topic="C",
                       rid="rid-c", uid="owner-uid"),
        "qd-a": _q_doc(submitted_at_ms=1_000, topic="A",
                       rid="rid-a", uid="owner-uid"),
        "qd-b": _q_doc(submitted_at_ms=2_000, topic="B",
                       rid="rid-b", uid="owner-uid"),
    }
    db = _FakeDB(queue_store)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    by_rid = {rid: patch for _, rid, patch in db.batch_writes}
    assert by_rid["rid-a"]["queuePosition"] == 1
    assert by_rid["rid-b"]["queuePosition"] == 2
    assert by_rid["rid-c"]["queuePosition"] == 3


def test_clock_skew_immunity(stub_module, monkeypatch):
    """Server timestamp ordering — sharer's lagging client clock can't
    push their doc ahead in the FIFO. Mirrors the C1 clock-skew test
    from test_global_queue_position.py."""
    queue_store = {
        # Owner's clock at ms 1_000_000, server stamps Husky at 1_001_500
        "qd-husky": _q_doc(timestamp_ms=1_000_000, submitted_at_ms=1_001_500,
                           topic="Husky", rid="rid-husky", uid="owner-uid"),
        # Sharer's clock is 5s behind (995_000), but server stamps Bull
        # Dog LATER at 1_002_000
        "qd-bulldog": _q_doc(timestamp_ms=995_000, submitted_at_ms=1_002_000,
                             topic="Bull Dog", rid="rid-bulldog",
                             uid="sharer-uid"),
    }
    db = _FakeDB(queue_store)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    by_rid = {rid: patch for _, rid, patch in db.batch_writes}
    assert by_rid["rid-husky"]["queuePosition"] == 1
    assert by_rid["rid-bulldog"]["queuePosition"] == 2


# ── Head-of-deferred behind-fields cleared ─────────────────────────────

def test_head_deferred_clears_behind_fields(stub_module, monkeypatch):
    """Head of the deferred queue has no doc ahead in queue. Behind
    fields must be cleared so a stale value from a prior position can't
    render as "behind a deleted run." FE falls back to
    device.currentRunTitle for the actual running blocker."""
    queue_store = {
        "qd-only": _q_doc(submitted_at_ms=1_000, topic="Lonely",
                          rid="rid-only", uid="owner-uid"),
    }
    db = _FakeDB(queue_store)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    from google.cloud.firestore import DELETE_FIELD
    assert len(db.batch_writes) == 1
    _, _, patch = db.batch_writes[0]
    assert patch["queuePosition"] == 1
    assert patch["queuedBehindRunId"] is DELETE_FIELD
    assert patch["queuedBehindTitle"] is DELETE_FIELD


# ── Defensive: missing uid/rid skipped ─────────────────────────────────

def test_doc_missing_uid_or_rid_skipped(stub_module, monkeypatch):
    """A queue doc missing the uid or researchId field can't be
    updated — skip it instead of raising."""
    queue_store = {
        "qd-bad": {
            "submittedAt": _FakeServerTs(1_000),
            "topic": "Bad",
            "action": "start",
            # uid + researchId missing
        },
        "qd-good": _q_doc(submitted_at_ms=2_000, topic="Good",
                          rid="rid-g", uid="owner-uid"),
    }
    db = _FakeDB(queue_store)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    # Only good doc patched. Note that bad doc still occupies a slot in
    # the FIFO sort, so good ends up at position 2.
    assert len(db.batch_writes) == 1
    _, rid, patch = db.batch_writes[0]
    assert rid == "rid-g"
    # Position 2 because qd-bad sorted first (earlier ts) but couldn't
    # be patched. The remaining slot for good is 2 — acceptable since
    # qd-bad's research doc isn't updated, no FE confusion.
    assert patch["queuePosition"] == 2


# ── Batch commit failure ───────────────────────────────────────────────

def test_batch_commit_failure_logged_not_raised(stub_module, monkeypatch):
    """Best-effort: a Firestore batch.commit error is logged at WARN
    but doesn't raise (callers fire-and-forget via to_thread)."""
    queue_store = {
        "qd-a": _q_doc(submitted_at_ms=1_000, topic="A",
                       rid="rid-a", uid="owner-uid"),
    }
    db = _FakeDB(queue_store, commit_should_raise=True)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    # Should not raise
    research_mod._recompute_deferred_queue_positions()


# ── Be-payload deviceId injection ──────────────────────────────────────

def test_be_payload_called_for_each_patch(monkeypatch):
    """Each patch must go through `_be_payload` so the deviceId is
    injected for the `deviceUpdatingFor` Firestore rule check."""
    monkeypatch.setattr(research_mod, "load_device_id",
                        lambda: "test-device-id")

    calls: list = []

    def _capturing_be_payload(d):
        calls.append(dict(d))
        return {**d, "deviceId": "test-device-id"}

    monkeypatch.setattr(research_mod, "_be_payload", _capturing_be_payload)
    queue_store = {
        "qd-a": _q_doc(submitted_at_ms=1_000, topic="A",
                       rid="rid-a", uid="owner-uid"),
        "qd-b": _q_doc(submitted_at_ms=2_000, topic="B",
                       rid="rid-b", uid="sharer-uid"),
    }
    db = _FakeDB(queue_store)
    monkeypatch.setattr(research_mod, "_firebase_db", db)
    research_mod._recompute_deferred_queue_positions()
    # _be_payload invoked once per patch
    assert len(calls) == 2
    # Resulting batch writes carry the deviceId
    for _uid, _rid, patch in db.batch_writes:
        assert patch["deviceId"] == "test-device-id"
