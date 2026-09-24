"""Wave 10.10 — a research you deleted can never run again, even if its Resume
was already waiting.

⛔⛔ THE DEFECT, FOUND READING THE RESUME HANDLER. A Resume that names its run
was taken on the disk's word alone: `_resume_run_id` reads the research record
only when the payload carries no usable run id. Deleting a research whose
recovery card offered Resume sends a queue cancel to catch a Resume already
waiting — but with the computer offline the two documents arrive in no fixed
order, so about half the time the cancel found nothing, the Resume ran, and
the person was EMAILED about a research they had deleted. And the worker's
last check — the statuses that make a dequeued job stand down — never listed
"archived", so a research archived while queued under the old archive still ran
when its computer came back.

⭐ THE FIX IS ONE RULE, `_pickup_withdrawn`, asked by every pickup: the start
listener, the Resume, the idle rescan (which is where a Retry's start document
lands when every worker is busy), the worker's dequeue, the boot restore from
the disk snapshot, the boot rehydrate and the dead-worker reconcile. Deleted or
archived stands down and removes the stale queue job; anything else is taken.

⛔⛔ AND A READ THAT FAILS TAKES THE JOB. Standing down deletes the only copy of
the request and tells nobody, so it happens only on POSITIVE evidence — a read
that succeeded and said "no record" or "archived". Every path below is executed
with all four records: missing, archived, ordinary and unreadable.

⭐ THE CONSUMERS ARE RUN, NOT READ. The listener is driven through
`_queue_listener`; the worker loop and the idle rescan are `run_server`
closures, lifted out of the parse tree and executed by `_run_server_closure`.
"""
import asyncio
import collections
import json
import time

import pytest

import research
from _queue_listener import Listener
from _run_server_closure import lift, run_worker_once

UID = "uid-alice"
RID = "chat_1758600000000_1"
RUN = "Alice_topic_20260923_101500"
TOPIC = "a private topic nobody else may read"

#: The four records every path is executed against. `None` is a deleted
#: research: the read succeeds and there is no document.
ORDINARY_RESUME = {"status": "paused_backend_restart", "topic": TOPIC}
ARCHIVED = {"status": "archived", "statusBeforeArchive": "queued", "topic": TOPIC}

#: What a Firestore read that fails looks like. The 403 shape is the one the
#: enqueue funnel already trusts ("the queue write was authenticated FE-side"),
#: so it lets a taken job be seen all the way into the queue; the transient one
#: is what the funnel refuses on its own, and is used where that matters.
DENIED = PermissionError("403 Missing or insufficient permissions")
TRANSIENT = TimeoutError("DeadlineExceeded")


# ══ a small Firestore: the records, the device queue, one query ════════════

class _Snap:
    def __init__(self, data, doc_id=None):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _QueueRef:
    def __init__(self, store, doc_id):
        self._store, self.id = store, doc_id

    def delete(self):
        self._store.queue_deleted.append(self.id)
        self._store.queue_docs.pop(self.id, None)

    def update(self, payload):
        self._store.queue_docs.get(self.id, {}).update(payload)


class _QueueSnap(_Snap):
    def __init__(self, store, doc_id, data):
        super().__init__(data, doc_id)
        self.reference = _QueueRef(store, doc_id)


class _Node:
    def __init__(self, store, parts):
        self._store, self._parts = store, parts

    def collection(self, name):
        return _Node(self._store, self._parts + (name,))

    document = collection

    def where(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def stream(self):
        # devices/{id}/queue
        return iter([_QueueSnap(self._store, i, d)
                     for i, d in list(self._store.queue_docs.items())])

    def get(self):
        p = self._parts
        if len(p) == 4 and p[0] == "users" and p[2] == "researches":
            key = (p[1], p[3])
            self._store.reads.append(key)
            if key in self._store.unreadable:
                raise self._store.error
            return _Snap(self._store.records.get(key))
        if len(p) == 3 and p[0] == "users" and p[2] == "researches":
            # the status == "ongoing" query the boot paths make
            return [_Snap(d, i) for i, d in self._store.query_rows]
        return _Snap(None)  # devices/{id}: not supervised


class Store:
    """`users/{uid}/researches/{rid}` and `devices/{id}/queue`, for the real code."""

    def __init__(self, record="absent", *, error=TRANSIENT, query_rows=None,
                 queue_docs=None):
        self.records: dict = {}
        self.unreadable: set = set()
        self.error = error
        if record == "unreadable":
            self.unreadable.add((UID, RID))
        elif record is not None and record != "absent":
            self.records[(UID, RID)] = dict(record)
        self.query_rows = list(query_rows or [])
        self.queue_docs = dict(queue_docs or {})
        self.queue_deleted: list = []
        self.reads: list = []
        self.writes: list = []

    def collection(self, name):
        return _Node(self, (name,))

    def update_research(self, uid, rid, updates):
        """`_update_research_doc`: an UPDATE — a record that is gone stays gone."""
        self.writes.append((uid, rid, dict(updates)))
        key = (uid, rid)
        if key in self.unreadable:
            return True
        if key not in self.records:
            return False
        self.records[key].update(updates)
        return True


class JobQ:
    """The asyncio queue as the enqueue funnel and the boot restore touch it."""

    def __init__(self):
        self._queue = collections.deque()
        self.put: list = []

    def put_nowait(self, job):
        self.put.append(job)
        self._queue.append(job)

    def qsize(self):
        return len(self._queue)


#: Each record, by the name its test ids carry.
RECORDS = {
    "deleted": None,
    "archived": ARCHIVED,
    "ordinary": ORDINARY_RESUME,
    "unreadable": "unreadable",
}


def _listener_docs(record):
    """The same four records, in the shape `_queue_listener` takes."""
    if record == "unreadable":
        return DENIED
    return {} if record is None else {(UID, RID): dict(record)}


# ══ 0. the rule itself ═════════════════════════════════════════════════════

def _rule(monkeypatch, record, error=TRANSIENT):
    monkeypatch.setattr(research, "_firebase_db", Store(record, error=error))
    return research._pickup_withdrawn(UID, RID, "test")


def test_a_deleted_research_is_withdrawn(monkeypatch):
    assert _rule(monkeypatch, None) == ("deleted", None)


def test_an_archived_research_is_withdrawn(monkeypatch):
    reason, record = _rule(monkeypatch, ARCHIVED)
    assert reason == "archived"
    assert record["status"] == "archived"


def test_an_ordinary_research_is_taken_and_its_record_handed_back(monkeypatch):
    assert _rule(monkeypatch, ORDINARY_RESUME) == (None, ORDINARY_RESUME)


@pytest.mark.parametrize("error", [TRANSIENT, DENIED, RuntimeError("503")])
def test_a_read_that_fails_is_never_a_deletion(monkeypatch, error):
    """⛔⛔ THE FAIL-SAFE DIRECTION. A failed read says nothing about the record,
    and standing down would delete the only copy of somebody's request."""
    assert _rule(monkeypatch, "unreadable", error) == (None, None)


@pytest.mark.parametrize("status", ["stopped_by_watchdog", "terminated_by_user_discard",
                                    "stopped", "completed", "paused_backend_restart_failed"])
def test_a_run_that_is_over_is_not_withdrawn(monkeypatch, status):
    """⭐ OVER IS NOT WITHDRAWN. The recovery card offers Resume for a
    watchdog-stopped and a discarded run, so the rule cannot be the terminal
    set — each pickup keeps its own answer about those."""
    assert _rule(monkeypatch, {"status": status})[0] is None


def test_the_stand_down_is_the_machines_line_and_names_no_topic(monkeypatch):
    """⛔ A job that is not running belongs to no run — on a shared computer the
    armed run is somebody else's — so the line is written in the machine scope,
    and it carries the research id, never the person's topic."""
    lines = []
    monkeypatch.setattr(research, "log", lambda msg, level="INFO": lines.append(
        (msg, research._LOG_SCOPE.get())))
    for record in (None, ARCHIVED, "unreadable"):
        monkeypatch.setattr(research, "_firebase_db", Store(record))
        research._pickup_withdrawn(UID, RID, "test")
    ours = [(m, s) for m, s in lines if m.startswith("[pickup:test]")]
    assert len(ours) == 3, lines
    assert all(s == research._LOG_SCOPE_MACHINE for _m, s in ours), ours
    assert all(RID[:8] in m and TOPIC not in m for m, _s in ours), ours


def test_no_firestore_takes_the_job(monkeypatch):
    monkeypatch.setattr(research, "_firebase_db", None)
    assert research._pickup_withdrawn(UID, RID, "test") == (None, None)


# ══ 1. the start listener ══════════════════════════════════════════════════

def _start(monkeypatch, tmp_path, record):
    monkeypatch.setitem(research._QUEUE_STATE, "running", False)
    return Listener(monkeypatch, tmp_path, owner=UID,
                    research_docs=_listener_docs(record)).feed(
        action="start", uid=UID, submittedBy=UID, researchId=RID, topic=TOPIC)


@pytest.mark.parametrize("name", ["deleted", "archived"])
def test_start_stands_down_for_a_withdrawn_research(monkeypatch, tmp_path, name):
    lis = _start(monkeypatch, tmp_path, RECORDS[name])
    assert lis.enqueued == [], f"a {name} research was started"
    assert lis.writes == [], f"a {name} research's record was written"
    assert lis.incoming == ["incoming"], "the stale start doc was left to replay"


@pytest.mark.parametrize("name", ["ordinary", "unreadable"])
def test_start_takes_an_ordinary_or_unreadable_research(monkeypatch, tmp_path, name):
    record = {"status": "queued"} if name == "ordinary" else "unreadable"
    lis = _start(monkeypatch, tmp_path, record)
    assert [j["research_id"] for j in lis.enqueued] == [RID], (
        f"an {name} research was not started")


# ══ 2. the Resume — the path the defect was on ═════════════════════════════

@pytest.fixture
def paused_run(tmp_path, monkeypatch):
    """The run a recovery card offers Resume for, with every marker a Resume
    that proceeds clears — so a Resume that stood down leaves them all."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    d = tmp_path / "queues" / RUN
    d.mkdir(parents=True)
    (d / "owner.json").write_text(json.dumps({"uid": UID, "researchId": RID}),
                                  encoding="utf-8")
    (d / ".pause").write_text("", encoding="utf-8")
    (d / research.NO_AUTO_RETRY_MARKER).write_text("", encoding="utf-8")
    return d


def _resume(monkeypatch, tmp_path, record):
    return Listener(monkeypatch, tmp_path, owner=UID,
                    research_docs=_listener_docs(record)).feed(
        action="resume", uid=UID, submittedBy=UID, researchId=RID,
        backendRunId=RUN, email="alice@example.com")


@pytest.mark.parametrize("name", ["deleted", "archived"])
def test_a_resume_naming_its_run_stands_down_for_a_withdrawn_research(
        paused_run, monkeypatch, tmp_path, name):
    """⛔⛔ THE DEFECT. The payload names the run and the disk agrees, so the
    record used to go unread — and a deleted research was resumed and emailed."""
    lis = _resume(monkeypatch, tmp_path, RECORDS[name])
    assert lis.enqueued == [], f"a {name} research was resumed"
    assert lis.writes == [], f"a {name} research's record was written"
    assert lis.incoming == ["incoming"], "the stale Resume was left to replay"
    assert (paused_run / ".pause").exists(), "the run was un-paused anyway"
    assert (paused_run / research.NO_AUTO_RETRY_MARKER).exists()


@pytest.mark.parametrize("name", ["ordinary", "unreadable"])
def test_a_resume_is_taken_for_an_ordinary_or_unreadable_research(
        paused_run, monkeypatch, tmp_path, name):
    """⭐ ACCEPT POLARITY, and the fail-safe: an unreadable record resumes on the
    run the payload named, exactly as it did before the rule existed."""
    lis = _resume(monkeypatch, tmp_path, RECORDS[name])
    assert [(j["research_id"], j["run_id"]) for j in lis.enqueued] == [(RID, RUN)], (
        f"an {name} research's Resume was dropped")
    assert not (paused_run / ".pause").exists()


def test_a_resume_of_a_watchdog_stopped_run_still_resumes(paused_run, monkeypatch, tmp_path):
    """⭐ The card offers Resume here; a rule that meant 'over' would refuse it."""
    lis = _resume(monkeypatch, tmp_path, {"status": "stopped_by_watchdog"})
    assert [j["run_id"] for j in lis.enqueued] == [RUN]


@pytest.mark.parametrize("cancel_first", [True, False], ids=["cancel-first", "resume-first"])
def test_deleting_a_research_stops_its_waiting_resume_in_either_order(
        paused_run, monkeypatch, tmp_path, cancel_first):
    """⛔⛔ THE SCENARIO. The person deletes the research while its computer is
    offline; the web removes the record and sends a cancel. When the computer
    returns, the Resume and the cancel arrive in either order — and neither
    order may run it."""
    lis = Listener(monkeypatch, tmp_path, owner=UID, research_docs={})
    resume = dict(action="resume", uid=UID, submittedBy=UID, researchId=RID,
                  backendRunId=RUN, email="alice@example.com")
    cancel = dict(action="cancel", uid=UID, submittedBy=UID, researchId=RID)
    for doc in ((cancel, resume) if cancel_first else (resume, cancel)):
        lis.feed(**doc)
    assert lis.enqueued == [], "a deleted research was resumed"
    assert (paused_run / ".pause").exists()


# ══ 3. the idle rescan — where a Retry lands when every worker is busy ═════

def _rescan(monkeypatch, tmp_path, record):
    store = Store(record, error=DENIED, queue_docs={"q1": {
        "action": "start", "uid": UID, "submittedBy": UID, "researchId": RID,
        "topic": TOPIC, "timestamp": int(time.time() * 1000) - 1000}})
    jobs = JobQ()
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", store)
    monkeypatch.setattr(research, "load_worker_count", lambda: 2)
    monkeypatch.setitem(research._REST_DEFER_SEEN, "v", False)
    monkeypatch.setattr(research, "_exit_scheduled", False)
    monkeypatch.setitem(research._QUEUE_STATE, "running", False)
    monkeypatch.setitem(research._QUEUE_STATE, "recompute_deferred_fn", None)
    monkeypatch.setattr(research, "_job_queue", jobs, raising=False)
    monkeypatch.setattr(research, "_worker_is_resting", lambda *a, **k: False)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    monkeypatch.setattr(research, "_try_claim_queue_doc", lambda *a, **k: True)
    monkeypatch.setattr(research, "_update_research_doc", store.update_research)
    asyncio.run(lift("_rescan_queue_for_unclaimed")())
    return store, jobs


@pytest.mark.parametrize("name", ["deleted", "archived"])
def test_the_rescan_stands_down_for_a_withdrawn_research(monkeypatch, tmp_path, name):
    """⛔⛔ The rescan wrote `status: "ongoing"` before anything read the record,
    so an archived research was UN-archived here and then passed the funnel's
    whitelist as an ordinary run. The real funnel is in place below."""
    store, jobs = _rescan(monkeypatch, tmp_path, RECORDS[name])
    assert jobs.put == [], f"a {name} research was picked up"
    assert store.writes == [], f"a {name} research's record was written"
    assert store.queue_deleted == ["q1"], "the claimed start doc was left behind"
    if name == "archived":
        assert store.records[(UID, RID)]["status"] == "archived"


@pytest.mark.parametrize("name", ["ordinary", "unreadable"])
def test_the_rescan_takes_an_ordinary_or_unreadable_research(monkeypatch, tmp_path, name):
    record = {"status": "queued"} if name == "ordinary" else "unreadable"
    store, jobs = _rescan(monkeypatch, tmp_path, record)
    assert [j["research_id"] for j in jobs.put] == [RID], (
        f"an {name} research was not picked up")
    assert [w[2]["status"] for w in store.writes] == ["ongoing"]


# ══ 4. the dequeue — the last pickup every job passes ═════════════════════

def _dequeue(monkeypatch, tmp_path, flip, record="absent"):
    """Run the real worker loop over one job. Returns the pipelines it started."""
    store = Store(record)
    job = {"topic": TOPIC, "email": "", "run_id": RUN, "uid": UID, "research_id": RID,
           "resume_dir": str(tmp_path / "queues" / RUN)}
    return run_worker_once(monkeypatch, tmp_path, job, flip=flip, db=store,
                           update_research=store.update_research)


@pytest.mark.parametrize("flip,record", [
    ("missing", "absent"),                 # the flip's own read found no record
    ("skipped(archived)", ARCHIVED),       # the flip read "archived"
    ("error", None),                       # the flip was refused; a plain read finds nothing
    ("error", ARCHIVED),                   # ...or finds it archived
], ids=["flip-missing", "flip-archived", "fallback-missing", "fallback-archived"])
def test_the_dequeue_never_runs_a_withdrawn_research(monkeypatch, tmp_path, flip, record):
    """⛔⛔ The worker's last check. "missing" was a WARN and a run; "archived"
    was "active"; and a fallback read that found nothing fell into the arm
    written for a read that FAILED, and ran."""
    assert _dequeue(monkeypatch, tmp_path, flip, record) == [], (
        f"a withdrawn research ran ({flip})")


@pytest.mark.parametrize("flip,record", [
    ("flipped", "absent"),
    ("skipped(ongoing)", "absent"),
    ("error", {"status": "ongoing"}),
    ("error", "unreadable"),               # both reads failed: proceed, as ever
    (None, "absent"),                      # no Firestore / a local HTTP resume
], ids=["flipped", "pre-flipped", "fallback-ongoing", "fallback-unreadable", "no-flip"])
def test_the_dequeue_runs_an_ordinary_or_unreadable_research(monkeypatch, tmp_path, flip, record):
    started = _dequeue(monkeypatch, tmp_path, flip, record)
    assert [kw["research_id"] for kw in started] == [RID], f"an ordinary job did not run ({flip})"


def test_the_dequeue_still_bails_on_a_status_it_always_bailed_on(monkeypatch, tmp_path):
    """The fallback read still feeds the bail list it fed before."""
    assert _dequeue(monkeypatch, tmp_path, "error", {"status": "stopped"}) == []


# ══ 5. the boot restore from the disk snapshot ═════════════════════════════

def _job(rid=RID, run=RUN):
    return {"uid": UID, "research_id": rid, "run_id": run, "topic": TOPIC,
            "email": "alice@example.com", "config": {}}


def _restore(monkeypatch, tmp_path, store, pending):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", store)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    path = tmp_path / "queues" / "_pending_queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts_ms": 1, "current": None, "pending": pending}),
                    encoding="utf-8")
    jobs = JobQ()
    research._restore_pending_queue_snapshot(path, jobs, set())
    kept = json.loads(path.read_text(encoding="utf-8"))["pending"] if path.exists() else []
    return [j["research_id"] for j in jobs.put], [j["research_id"] for j in kept]


@pytest.mark.parametrize("name", ["deleted", "archived"])
def test_boot_restore_sheds_a_withdrawn_research(monkeypatch, tmp_path, name):
    restored, kept = _restore(monkeypatch, tmp_path, Store(RECORDS[name]), [_job()])
    assert restored == [], f"a {name} research was restored"
    assert kept == [], f"a {name} research's entry stayed to be re-offered at every boot"


def test_boot_restore_takes_an_ordinary_research(monkeypatch, tmp_path):
    restored, _kept = _restore(monkeypatch, tmp_path, Store({"status": "queued"}), [_job()])
    assert restored == [RID]


def test_boot_restore_takes_an_unreadable_research_the_funnel_trusts(monkeypatch, tmp_path):
    restored, _kept = _restore(monkeypatch, tmp_path, Store("unreadable", error=DENIED), [_job()])
    assert restored == [RID]


def test_boot_restore_keeps_an_unreadable_research_the_funnel_refuses(monkeypatch, tmp_path):
    """⛔⛔ NOT A DELETION. The funnel refuses a transient failure on its own, and
    that refusal is kept for the next boot — beside a deleted research's entry,
    which is shed, so the file is really rewritten and the difference shows."""
    store = Store("unreadable", error=TRANSIENT)
    other = "chat_1758600000000_2"
    restored, kept = _restore(monkeypatch, tmp_path, store,
                              [_job(), _job(other, "Other_topic_20260923_101600")])
    assert restored == []
    assert kept == [RID], "an entry whose record could not be read was thrown away"


# ══ 6. the boot rehydrate and the dead-worker reconcile ════════════════════

def _boot_store(record, assigned):
    """The query says "ongoing"; the record may have moved since."""
    return Store(record, query_rows=[(RID, {"status": "ongoing", "assignedWorker": assigned})])


def _rehydrate(monkeypatch, tmp_path, record):
    store = _boot_store(record, 1)
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", store)
    monkeypatch.setattr(research, "load_worker_count", lambda: 1)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda *a: [])
    monkeypatch.setattr(research, "_update_research_doc", store.update_research)
    asyncio.run(research._rehydrate_ongoing_for_tree(UID, UID, set()))
    return store


def _reconcile(monkeypatch, tmp_path, record):
    store = _boot_store(record, 2)
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", store)
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda *a: [])
    monkeypatch.setattr(research, "_update_research_doc", store.update_research)
    asyncio.run(research._reconcile_dead_worker_runs(UID, {2}))
    return store


@pytest.mark.parametrize("path", [_rehydrate, _reconcile], ids=["rehydrate", "reconcile"])
@pytest.mark.parametrize("name", ["deleted", "archived"])
def test_boot_recovery_leaves_a_withdrawn_research_alone(monkeypatch, tmp_path, path, name):
    """⛔ The recovery mark is `paused_backend_restart`: written over an archive
    it undoes it and offers a Resume for a research the person put away."""
    store = path(monkeypatch, tmp_path, RECORDS[name])
    assert store.writes == [], f"a {name} research was marked for a Resume"
    if name == "archived":
        assert store.records[(UID, RID)]["status"] == "archived"


@pytest.mark.parametrize("path", [_rehydrate, _reconcile], ids=["rehydrate", "reconcile"])
@pytest.mark.parametrize("name", ["ordinary", "unreadable"])
def test_boot_recovery_still_recovers_an_ordinary_or_unreadable_research(
        monkeypatch, tmp_path, path, name):
    record = {"status": "ongoing"} if name == "ordinary" else "unreadable"
    store = path(monkeypatch, tmp_path, record)
    assert [(w[1], w[2]["status"]) for w in store.writes] == [
        (RID, "paused_backend_restart")], f"an {name} run was not recovered"
