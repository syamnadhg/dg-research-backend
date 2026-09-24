"""Drive the REAL start listener's snapshot callback against fakes.

⛔⛔ WHY THIS EXISTS (wave 10.9). The deferred-cancel tests exercised a COPY of
the scan — a function in the test file that "replicates" the branch — so a
change to the production scan, including the fix for a member deleting another
member's queued run, left them green. The resume tests read the listener's
parse tree for names. Neither measured what the branch DOES.

⭐ So this registers `start_firestore_start_listener` against a fake Firestore,
hands its callback ONE queue document, and records what it did: the research
writes, the queue documents it deleted, and the jobs it enqueued. Shared by the
files that need it, because a private copy per file is the drift this replaces.

⛔ `_guard_snapshot` IS REPLACED WITH THE IDENTITY. In production it swallows a
raise so the listener survives; here that would turn a crashing branch into one
that looks like it refused — the exact false pass a security pin must not have.
"""
import collections
import time

import research


class _Snap:
    """A queue document as `col_ref.limit(n).stream()` yields it."""

    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _QueueDocRef:
    def __init__(self, col, doc_id):
        self._col = col
        self.id = doc_id

    def delete(self):
        self._col.deleted.append(self.id)
        self._col.docs.pop(self.id, None)


class QueueCol:
    """`devices/{id}/queue` — the queued documents, and a record of deletes."""

    def __init__(self, box, docs):
        self._box = box
        self.docs = dict(docs or {})
        self.deleted: list = []

    def on_snapshot(self, cb):
        self._box["cb"] = cb
        return object()

    def where(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def stream(self):
        return iter([_Snap(i, d) for i, d in list(self.docs.items())])

    def document(self, doc_id):
        return _QueueDocRef(self, doc_id)


class _ResearchSnap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _Chain:
    """One step of `collection(...).document(...)...`, remembering the path."""

    def __init__(self, db, path):
        self._db = db
        self._path = path

    def collection(self, name):
        return self._db._route(self._path + (name,))

    def document(self, name):
        return self._db._route(self._path + (name,))

    def get(self, **_options):
        # users/{uid}/researches/{rid} — a restart retry's read passes the
        # client's `retry`/`timeout` options, taken here and answered at once.
        if len(self._path) == 4 and self._path[0] == "users" and self._path[2] == "researches":
            key = (self._path[1], self._path[3])
            self._db.reads.append(key)
            if isinstance(self._db.research_docs, Exception):
                raise self._db.research_docs
            return _ResearchSnap(self._db.research_docs.get(key))
        return _ResearchSnap(None)


class FakeDb:
    def __init__(self, box, queue_docs=None, research_docs=None):
        self.queue = QueueCol(box, queue_docs)
        self.research_docs = research_docs if research_docs is not None else {}
        self.reads: list = []

    def collection(self, name):
        return self._route((name,))

    def _route(self, path):
        if len(path) == 3 and path[0] == "devices" and path[2] == "queue":
            return self.queue
        return _Chain(self, path)


class _IncomingRef:
    def __init__(self, sink):
        self._sink = sink

    def delete(self):
        self._sink.append("incoming")


class _IncomingDoc:
    def __init__(self, data, sink):
        self._data = data
        self.reference = _IncomingRef(sink)
        self.id = "incoming-doc"

    def to_dict(self):
        return dict(self._data)

    @property
    def exists(self):
        return True


class _Change:
    def __init__(self, data, sink):
        self.type = type("T", (), {"name": "ADDED"})()
        self.document = _IncomingDoc(data, sink)


class _JobQueue:
    def __init__(self, jobs):
        self._queue = collections.deque(jobs or ())
        self.put: list = []

    def put_nowait(self, job):
        self.put.append(job)

    def qsize(self):
        return len(self._queue)


class _Loop:
    def call_soon_threadsafe(self, fn, *a):
        fn(*a)


class _Controls:
    def __init__(self):
        self.stops = 0

    def request_stop(self):
        self.stops += 1


class Listener:
    """One registered listener over one fake machine. `feed` hands it a doc."""

    # ⛔ A `gate_pending` SLOT WAS ACCEPTED HERE AND IS GONE (wave 10.9, N8).
    # It stood for the job a worker held while it waited on the PREVIOUS run's
    # cloud tail; that wait, and the `_QUEUE_STATE["gate_pending_job"]` slot it
    # registered itself in, no longer exist. A worker now sets `current_job` in
    # the same breath as the dequeue, so `current_job` and the deque are the
    # whole of what this process can be holding.
    def __init__(self, monkeypatch, tmp_path, *, owner="uid-owner",
                 queue_docs=None, research_docs=None, current_job=None,
                 deque_jobs=None, real_terminal_check=False,
                 last_completed=None):
        box: dict = {}
        self.db = FakeDb(box, queue_docs, research_docs)
        self.writes: list = []
        self.incoming: list = []
        self.jobs = _JobQueue(deque_jobs)
        # The run directories live under tmp_path/queues.
        monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
        monkeypatch.setattr(research, "_firebase_db", self.db)
        monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
        monkeypatch.setattr(research, "load_paired_uid", lambda: owner)
        monkeypatch.setattr(research, "_worker_is_resting", lambda *a, **k: False)
        # ⛔ THE MACHINE'S OWN CONFIG IS NOT TEST INPUT. `load_worker_count`
        # reads this developer's `config.json` (2 on the box this was written
        # on), and `_REST_DEFER_SEEN` is a module global that an earlier test
        # can leave set — between them they decide whether the start branch
        # takes the multi-worker claim path. Pinned to the single-worker shape
        # so a start doc behaves the same everywhere.
        monkeypatch.setattr(research, "load_worker_count", lambda: 1)
        monkeypatch.setitem(research._REST_DEFER_SEEN, "v", False)
        monkeypatch.setattr(research, "_guard_snapshot", lambda cb, _label: cb)
        monkeypatch.setattr(research, "_try_claim_queue_doc", lambda *a, **k: True)
        monkeypatch.setattr(research, "load_checkpoint", lambda _qd: {"topic": "t"})
        # ⛔ `real_terminal_check=True` LEAVES THE REAL ONE IN PLACE, for a test
        # whose subject IS whether a run counts as over. Stubbed by default
        # because a refusal test would otherwise have to state a status for
        # every research document it never asks about.
        if not real_terminal_check:
            monkeypatch.setattr(research, "_research_is_terminal", lambda *a, **k: False)

        def _record(uid, rid, updates):
            self.writes.append((uid, rid, dict(updates)))
            return True

        monkeypatch.setattr(research, "_update_research_doc", _record)
        # ⛔ THE STOP AND THE EXIT ARE RECORDED, NEVER PERFORMED. The cancel
        # branch's running-job path schedules a process exit; left real, a test
        # that reaches it would take the test runner down with it.
        self.controls = _Controls()
        self.exits: list = []
        monkeypatch.setattr(research, "_controls", self.controls)
        monkeypatch.setattr(research, "_schedule_server_exit",
                            lambda reason, *a, **k: self.exits.append(reason))
        monkeypatch.setitem(research._QUEUE_STATE, "current_job", current_job)
        # ⭐ `last_completed` PUTS THE RETIRED QUEUE GATE'S POINTER BACK, as a
        # test of the listener's INDIFFERENCE to it. The three keys are the ones
        # `_wait_for_prior_fe_completion` was fed from; a listener that still
        # predicted a gate from them would answer a submission differently
        # depending on what somebody else's run was doing (wave 10.9, N8).
        for _k, _v in (last_completed or {}).items():
            monkeypatch.setitem(research._QUEUE_STATE, _k, _v)
        monkeypatch.setitem(research._QUEUE_STATE, "recompute_fn", None)
        monkeypatch.setitem(research._QUEUE_STATE, "recompute_deferred_fn", None)
        research.start_firestore_start_listener(self.jobs, _Loop())
        self._cb = box.get("cb")
        assert self._cb is not None, "the listener did not register a callback"

    def feed(self, **data):
        data.setdefault("timestamp", int(time.time() * 1000) - 1000)
        self._cb(object(), [_Change(data, self.incoming)], None)
        return self

    # ── what it did ──────────────────────────────────────────────────────
    @property
    def enqueued(self):
        return list(self.jobs.put)

    @property
    def deleted_queue_ids(self):
        return list(self.db.queue.deleted)

    def writes_to(self, uid):
        return [w for w in self.writes if w[0] == uid]
