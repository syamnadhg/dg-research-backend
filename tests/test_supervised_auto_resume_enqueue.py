"""The supervised boot auto-resume actually enqueues — DGOPS-9508.

This is the path `_rehydrate_ongoing_for_tree` takes when a supervised device
comes back after a restart with its run's artifacts still on disk: re-enqueue
with `resume_dir` so the run picks up from its checkpoint, no user action.

**It was dead code, and the existing tests could not see it.** The enqueue read
the bare name `_job_queue`, which is a LOCAL of `run_server` and not in scope in
this module-level helper, so it raised NameError — and because the argument is
evaluated before the call, monkeypatching `_safe_enqueue` does not help. The
caller's broad `except Exception` logged one "Queue rehydration failed" WARN and
abandoned the whole block, which took the `paused_backend_restart` fallback down
with it: the run came back `ongoing` with no Resume affordance at all.

Why 2094 passing tests missed it — the two existing files between them cover
every combination EXCEPT the one that reaches the enqueue:

    test_sharer_rehydration.py
        unsupervised                        -> asserts enqueues == []
        supervised, NO disk artifacts       -> asserts enqueues == []
        sibling-held / no ongoing runs      -> asserts enqueues == []
    test_per_worker_rehydration_966.py
        ownership routing only — and its docstring says "the supervised auto-
        resume enqueue itself is covered by test_sharer_rehydration.py", which
        is exactly the file that only ever asserts the enqueue does NOT happen.

So the happy path had no test, and a claim that it did. That is what this file
fixes. `test_the_enqueue_receives_the_queue_from_queue_state` is the regression
lock proper: it pins the mechanism (`_QUEUE_STATE["queue_ref"]`) rather than just
"something got enqueued", because the bug was about WHERE the queue came from.

The Firestore fakes are duplicated from test_sharer_rehydration.py rather than
imported, following the precedent test_per_worker_rehydration_966.py set — test
modules importing each other's private fakes couples their refactors together.

Run:  pytest tests/test_supervised_auto_resume_enqueue.py -v
"""
import asyncio
import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

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


class _FakeQueue:
    """Stands in for the asyncio.Queue that run_server owns."""


@pytest.fixture
def run_dir():
    """A real queues/<run_id> directory, because `queue_dir.exists()` is the gate.

    Created under the module's own queues/ root since the helper derives the path
    from `Path(research.__file__).parent`, not from anything injectable.
    """
    run_id = f"dgops9508-test-{uuid.uuid4().hex[:12]}"
    path = Path(research.__file__).resolve().parent / "queues" / run_id
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield run_id, path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _setup(monkeypatch, *, researches, devices=None, siblings=None,
           queue_ref=_FakeQueue()):
    db = _FakeDB()
    db.researches = researches
    db.devices = devices or {}
    monkeypatch.setattr(research, "_firebase_db", db, raising=False)

    updates, enqueues = [], []
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda uid, rid, patch: (updates.append((uid, rid, patch)) or True))
    # Records the QUEUE it was handed, not just the job — the defect was about
    # which object reached this call, and a job-only spy cannot see that.
    monkeypatch.setattr(research, "_safe_enqueue",
                        lambda q, job, source=None: (enqueues.append((q, job, source)) or True))
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research",
                        lambda rid, wid: (siblings or {}).get(rid, []))
    monkeypatch.setattr(research, "load_checkpoint",
                        lambda qd: {"topic": "resumed topic"})
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", queue_ref)
    return updates, enqueues


def _ongoing(run_id, **extra):
    data = {"deviceId": "dev1", "status": "ongoing", "backendRunId": run_id}
    data.update(extra)
    return [_Snap("rid-auto", data)]


_SUPERVISED = {"dev1": _DevSnap(True, {"supervised": True})}


def test_supervised_with_disk_artifacts_auto_resumes(monkeypatch, run_dir):
    """The happy path that had no test — and therefore raised NameError in prod.

    Asserts the run is RESUMED (counted in the first return value) and NOT marked
    paused: before the fix both were false at once, because the exception took the
    fallback down with the enqueue.
    """
    run_id, path = run_dir
    updates, enqueues = _setup(monkeypatch, researches={"u1": _ongoing(run_id)},
                               devices=_SUPERVISED)

    resumed, paused = asyncio.run(
        research._rehydrate_ongoing_for_tree("u1", "owner-uid", set()))

    assert (resumed, paused) == (1, 0), (
        "a supervised device with intact on-disk artifacts must auto-resume and "
        "must NOT also be marked paused"
    )
    assert len(enqueues) == 1, f"expected exactly one enqueue, got {enqueues!r}"
    _q, job, source = enqueues[0]
    assert source == "rehydrate-supervised-auto-resume"
    assert job["run_id"] == run_id
    assert job["resume_dir"] == str(path), (
        "resume_dir must point at the on-disk queue dir — it is what makes "
        "run_pipeline resume from the checkpoint instead of starting over"
    )
    assert job["topic"] == "resumed topic"
    assert job["uid"] == "u1"
    assert job["research_id"] == "rid-auto"
    assert updates == [], f"auto-resumed run must not be patched paused: {updates!r}"


def test_the_enqueue_receives_the_queue_from_queue_state(monkeypatch, run_dir):
    """Regression lock on the MECHANISM, not just the outcome.

    The bug was not "nothing got enqueued" — it was that the queue was fetched by
    a bare name belonging to another scope. Asserting object identity against
    `_QUEUE_STATE["queue_ref"]` is what pins the fix: any future edit back to a
    module-global or a re-derived queue fails here even if an enqueue still
    happens.
    """
    run_id, _path = run_dir
    sentinel = _FakeQueue()
    _updates, enqueues = _setup(monkeypatch, researches={"u1": _ongoing(run_id)},
                                devices=_SUPERVISED, queue_ref=sentinel)

    asyncio.run(research._rehydrate_ongoing_for_tree("u1", "owner-uid", set()))

    assert len(enqueues) == 1
    queue_passed = enqueues[0][0]
    assert queue_passed is sentinel, (
        "the enqueue must receive the exact object held in "
        '_QUEUE_STATE["queue_ref"] — that indirection exists because the worker '
        "queue is a local of run_server and unreachable by name from here"
    )


def test_missing_queue_ref_falls_back_to_paused(monkeypatch, run_dir):
    """A boot race must degrade to a Resume CTA, never to a lost run.

    `_QUEUE_STATE["queue_ref"]` is populated inside run_server, so it can in
    principle still be None. The old code would have raised here; the guard has to
    fall through to `paused_backend_restart` so the user still gets the affordance.
    """
    run_id, _path = run_dir
    updates, enqueues = _setup(monkeypatch, researches={"u1": _ongoing(run_id)},
                               devices=_SUPERVISED, queue_ref=None)

    resumed, paused = asyncio.run(
        research._rehydrate_ongoing_for_tree("u1", "owner-uid", set()))

    assert enqueues == [], "cannot enqueue without a queue"
    assert (resumed, paused) == (0, 1), (
        "with no queue_ref the run must be marked paused_backend_restart, not "
        "silently dropped"
    )
    assert updates and updates[0][2]["status"] == "paused_backend_restart"


def test_stop_sentinel_still_blocks_auto_resume(monkeypatch, run_dir):
    """A terminally-stopped run must not be resurrected by rehydration.

    Adjacent invariant on the same branch: now that the branch actually executes,
    its guards are reachable for the first time and worth pinning.
    """
    run_id, path = run_dir
    (path / ".stop").write_text("", encoding="utf-8")
    updates, enqueues = _setup(monkeypatch, researches={"u1": _ongoing(run_id)},
                               devices=_SUPERVISED)

    resumed, paused = asyncio.run(
        research._rehydrate_ongoing_for_tree("u1", "owner-uid", set()))

    assert enqueues == [], "a .stop sentinel means the user ended this run"
    assert (resumed, paused) == (0, 1)
    assert updates[0][2]["status"] == "paused_backend_restart"


def test_stale_pause_sentinel_is_cleared_so_the_resumed_run_drains(monkeypatch, run_dir):
    """Leaving `.pause` in place would re-enqueue a run that immediately stalls."""
    run_id, path = run_dir
    pause = path / ".pause"
    pause.write_text("", encoding="utf-8")
    _updates, enqueues = _setup(monkeypatch, researches={"u1": _ongoing(run_id)},
                                devices=_SUPERVISED)

    asyncio.run(research._rehydrate_ongoing_for_tree("u1", "owner-uid", set()))

    assert len(enqueues) == 1
    assert not pause.exists(), (
        "the stale .pause signal must be cleared on auto-resume, or the run is "
        "enqueued only to park itself again"
    )


def test_skippedphases_is_normalised_to_skipphases(monkeypatch, run_dir):
    """The FE's legacy key name must not silently drop the skip config on resume."""
    run_id, _path = run_dir
    _updates, enqueues = _setup(
        monkeypatch,
        researches={"u1": _ongoing(run_id, pipelineConfig={"skippedPhases": [3, 4]})},
        devices=_SUPERVISED,
    )

    asyncio.run(research._rehydrate_ongoing_for_tree("u1", "owner-uid", set()))

    assert len(enqueues) == 1
    cfg = enqueues[0][1]["config"]
    assert cfg.get("skipPhases") == [3, 4]
    assert "skippedPhases" not in cfg, "the legacy key must be renamed, not duplicated"
