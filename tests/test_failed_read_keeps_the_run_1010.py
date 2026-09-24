"""A Firestore read that fails never drops a run whose queue document is gone.

⛔⛔ WHAT WAS WRONG (wave 10.10). `_safe_enqueue` — the funnel every automatic
pickup goes through — refused a job on any read failure that was not a 403, and
on no Firestore client at all. The start listener and the idle rescan call it
AFTER they have deleted the job's queue document, so that refusal was the end of
the request: one DeadlineExceeded, or the heartbeat dropping the client in the
same second, and somebody's paid run was gone, its record left saying "ongoing"
or "queued", with nothing anywhere to start it and nobody told.

⭐ WHAT EACH PATH NOW DOES WITH A READ THAT FAILS:
  · start listener, idle rescan → TAKE the job. The record was read a moment
    earlier on the way in (`_pickup_withdrawn`), and the worker's dequeue reads
    it again before anything runs — that read stands a deleted research down
    and bails on every terminal status (`test_deleted_research_never_runs_1010`).
  · boot restore → REFUSE, and keep the entry for the next boot. Its snapshot
    is a stale local copy and this read is the #728 guard against relaunching a
    run worker 1 just parked for its person's Resume.
  · rehydrate's supervised auto-resume → REFUSE, and fall through to the
    `paused_backend_restart` mark: a Resume card, a slower run, not a lost one.

A read that SUCCEEDED and said no — the record gone, a status outside the
whitelist — is an answer, and every path still refuses on it. Each path below is
executed through its real code, in both polarities.

Run:  pytest tests/test_failed_read_keeps_the_run_1010.py -v
"""
import asyncio
import collections
import json
import time

import pytest

import _queue_listener
import research
from _queue_listener import Listener
from _run_server_closure import lift

UID = "uid-alice"
RID = "chat_1758600000000_3"
RUN = "Alice_topic_20260923_101500"
TOPIC = "a paid research somebody is watching"

QUEUED = {"status": "queued", "topic": TOPIC}
ONGOING = {"status": "ongoing", "assignedWorker": 1, "deviceId": "dev-abcdef",
           "backendRunId": RUN, "topic": TOPIC}

#: The failures a real read throws that say nothing about the record. None of
#: them is the 403 shape the funnel always trusted.
BLIPS = [TimeoutError("DeadlineExceeded"),
         ConnectionError("UNAVAILABLE: failed to connect to all addresses"),
         RuntimeError("503 The service is currently unavailable")]


class _Answers:
    """`users/{uid}/researches/{rid}` answering ONE read at a time, in order.

    An answer is the record, `None` for "the read succeeded and there is no
    record", or an exception the read raises. The last answer repeats."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self.reads = 0

    def next(self):
        self.reads += 1
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    # the shape `_queue_listener.FakeDb` reads through
    def get(self, _key, _default=None):
        return self.next()


# ══ 0. the funnel itself ══════════════════════════════════════════════════

class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _RecordDb:
    """Just the research record, the way `_safe_enqueue` reads it."""

    def __init__(self, answers):
        self.answers = answers

    def collection(self, _name):
        return self

    def document(self, _name):
        return self

    def get(self):
        return _Snap(self.answers.next())


class _Q:
    def __init__(self):
        self._queue = collections.deque()

    def put_nowait(self, job):
        self._queue.append(job)


def _funnel(monkeypatch, tmp_path, answer, **kw):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db",
                        None if answer == "no-client" else _RecordDb(_Answers(answer)))
    q = _Q()
    ok = research._safe_enqueue(q, {"uid": UID, "research_id": RID, "run_id": RUN},
                                "test", **kw)
    assert ok == bool(q._queue), "the return value and the queue disagree"
    return ok


@pytest.mark.parametrize("answer", [*BLIPS, "no-client"],
                         ids=["deadline", "unavailable", "503", "no-client"])
def test_a_caller_whose_queue_doc_is_gone_takes_a_job_it_could_not_check(
        monkeypatch, tmp_path, answer):
    assert _funnel(monkeypatch, tmp_path, answer, take_unreadable=True) is True


@pytest.mark.parametrize("answer", [*BLIPS, "no-client"],
                         ids=["deadline", "unavailable", "503", "no-client"])
def test_every_other_caller_still_refuses_a_job_it_could_not_check(
        monkeypatch, tmp_path, answer):
    """⭐ THE DEFAULT IS UNCHANGED — the boot restore leans on it."""
    assert _funnel(monkeypatch, tmp_path, answer) is False


@pytest.mark.parametrize("take", [True, False], ids=["taking-caller", "default"])
@pytest.mark.parametrize("answer", [None, {"status": "stopped"}, {"status": "completed"}],
                         ids=["deleted", "stopped", "completed"])
def test_a_read_that_answered_no_refuses_for_every_caller(monkeypatch, tmp_path, take, answer):
    """⛔ TAKING IS FOR A READ THAT SAID NOTHING. A record that is gone, or a run
    that is over, is an answer — a rule that took those too would restart a run
    somebody stopped."""
    assert _funnel(monkeypatch, tmp_path, answer, take_unreadable=take) is False


@pytest.mark.parametrize("take", [True, False], ids=["taking-caller", "default"])
def test_a_readable_waiting_run_is_taken_by_every_caller(monkeypatch, tmp_path, take):
    assert _funnel(monkeypatch, tmp_path, QUEUED, take_unreadable=take) is True


# ══ 1. the start listener — deletes the queue doc, then enqueues ══════════

def _start(monkeypatch, tmp_path, answers, loop=None):
    monkeypatch.setitem(research._QUEUE_STATE, "running", False)
    if loop is not None:
        monkeypatch.setattr(_queue_listener, "_Loop", loop)
    lis = Listener(monkeypatch, tmp_path, owner=UID, research_docs=answers)
    lis.feed(action="start", uid=UID, submittedBy=UID, researchId=RID, topic=TOPIC)
    return lis


@pytest.mark.parametrize("blip", BLIPS, ids=["deadline", "unavailable", "503"])
def test_start_keeps_a_run_whose_record_blips_at_the_enqueue(monkeypatch, tmp_path, blip):
    """⛔⛔ THE DEFECT. The listener reads the record, writes it "ongoing",
    deletes the queue document — and the funnel's own read then fails. That
    refusal dropped the run for good."""
    answers = _Answers(QUEUED, blip)
    lis = _start(monkeypatch, tmp_path, answers)

    assert lis.incoming == ["incoming"], "the queue doc was not deleted — nothing was at stake"
    assert answers.reads >= 2, "the funnel never read the record"
    assert [j["research_id"] for j in lis.enqueued] == [RID], (
        "a run whose queue document was already deleted was dropped on a failed read")


def test_start_keeps_a_run_whose_record_cannot_be_read_at_all(monkeypatch, tmp_path):
    lis = _start(monkeypatch, tmp_path, _Answers(TimeoutError("DeadlineExceeded")))
    assert [j["research_id"] for j in lis.enqueued] == [RID]


def test_start_keeps_a_run_when_the_client_is_dropped_before_the_enqueue(monkeypatch, tmp_path):
    """⛔ THE HEARTBEAT DROPS THE CLIENT after enough failed writes, and the
    enqueue runs later, on the loop. "Firestore unavailable" is a read that
    could not happen — not an answer."""
    class _ClientDropped(_queue_listener._Loop):
        def call_soon_threadsafe(self, fn, *a):
            monkeypatch.setattr(research, "_firebase_db", None)
            fn(*a)

    lis = _start(monkeypatch, tmp_path, _Answers(QUEUED), loop=_ClientDropped)
    assert lis.incoming == ["incoming"]
    assert [j["research_id"] for j in lis.enqueued] == [RID]


@pytest.mark.parametrize("late", [None, {"status": "stopped"}], ids=["deleted", "stopped"])
def test_start_still_refuses_what_the_enqueue_read_answered(monkeypatch, tmp_path, late):
    """⭐ OTHER POLARITY. Deleted or stopped between the claim and the enqueue —
    the race the funnel was written for — still refuses."""
    lis = _start(monkeypatch, tmp_path, _Answers(QUEUED, late))
    assert lis.enqueued == []


# ── …but a failed read never runs a research twice ─────────────────────────
#
# ⛔⛔ THE PRICE OF TAKING ON A FAILED READ (cross-verify, wave 10.10). The
# duplicate guard — "a sibling worker already runs this research, so this start
# doc is a copy" — sat under `status == "ongoing"`, and a failed read has no
# status. Before this wave the funnel's own read, failing too, dropped the copy
# by accident; now the copy is taken and a second worker runs the same research
# on a second browser, billed twice. The sibling's lock is a local file, so the
# guard runs on it alone when the record cannot be read.

def _sibling_runs(tmp_path, research_id, worker_id=2):
    """A LIVE sibling claim: this process's pid, started just now."""
    research._write_worker_lock(worker_id, research_id, RUN)
    assert research._scan_sibling_locks_for_research(research_id, research.WORKER_ID), (
        "precondition: the scan sees the sibling — otherwise this measures nothing")


def test_a_failed_read_never_starts_a_research_a_sibling_is_running(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    _sibling_runs(tmp_path, RID)
    lis = _start(monkeypatch, tmp_path, _Answers(TimeoutError("DeadlineExceeded")))
    assert lis.enqueued == [], "a duplicate start doc ran the sibling's research twice"
    assert lis.incoming == ["incoming"], "the duplicate's queue doc must go, or it replays"
    assert lis.writes == [], "the duplicate wrote over the running record"


def test_a_failed_read_still_takes_a_run_no_sibling_is_running(monkeypatch, tmp_path):
    """⭐ OTHER POLARITY — the lock must be for THIS research. A sibling busy
    with somebody else's run is no reason to drop this one."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    _sibling_runs(tmp_path, "chat_someone_else")
    lis = _start(monkeypatch, tmp_path, _Answers(TimeoutError("DeadlineExceeded")))
    assert [j["research_id"] for j in lis.enqueued] == [RID]


def test_a_readable_waiting_run_is_not_second_guessed_by_a_lock(monkeypatch, tmp_path):
    """⭐ NO WIDER THAN THE HOLE. A record that READ as queued is not a duplicate
    by status — a sibling may still be closing an earlier run of it — so a lock
    alone never refuses it."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    _sibling_runs(tmp_path, RID)
    lis = _start(monkeypatch, tmp_path, _Answers(QUEUED))
    assert [j["research_id"] for j in lis.enqueued] == [RID]


# ══ 2. the idle rescan — the same, from `run_server`'s own closure ════════

class _QueueRef:
    def __init__(self, db, doc_id):
        self._db, self.id = db, doc_id

    def delete(self):
        self._db.queue_deleted.append(self.id)
        self._db.queue_docs.pop(self.id, None)

    def update(self, payload):
        self._db.queue_docs.get(self.id, {}).update(payload)


class _QueueSnap:
    def __init__(self, db, doc_id, data):
        self.id = doc_id
        self._data = data
        self.reference = _QueueRef(db, doc_id)

    def to_dict(self):
        return dict(self._data)


class _Node:
    def __init__(self, db, parts):
        self._db, self._parts = db, parts

    def collection(self, name):
        return _Node(self._db, self._parts + (name,))

    document = collection

    def limit(self, *_a, **_k):
        return self

    def stream(self):          # devices/{id}/queue
        return iter([_QueueSnap(self._db, i, d) for i, d in list(self._db.queue_docs.items())])

    def get(self):             # users/{uid}/researches/{rid}
        assert self._parts[0] == "users" and self._parts[2] == "researches", self._parts
        record = self._db.answers.next()
        if self._db.drop_client_after_first_read:
            self._db.drop_client()
        return _Snap(record)


class _RescanDb:
    def __init__(self, answers, drop_client=None):
        self.answers = answers
        self.drop_client = drop_client
        self.drop_client_after_first_read = drop_client is not None
        self.queue_docs = {"q1": {
            "action": "start", "uid": UID, "submittedBy": UID, "researchId": RID,
            "topic": TOPIC, "timestamp": int(time.time() * 1000) - 1000}}
        self.queue_deleted: list = []
        self.writes: list = []

    def collection(self, name):
        return _Node(self, (name,))

    def update_research(self, uid, rid, updates):
        self.writes.append((uid, rid, dict(updates)))
        return True


def _rescan(monkeypatch, tmp_path, answers, *, drop_client=False):
    db = _RescanDb(answers, (lambda: monkeypatch.setattr(research, "_firebase_db", None))
                   if drop_client else None)
    jobs = _Q()
    jobs.qsize = lambda: len(jobs._queue)
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setattr(research, "load_worker_count", lambda: 2)
    monkeypatch.setitem(research._REST_DEFER_SEEN, "v", False)
    monkeypatch.setattr(research, "_exit_scheduled", False)
    monkeypatch.setitem(research._QUEUE_STATE, "running", False)
    monkeypatch.setitem(research._QUEUE_STATE, "recompute_deferred_fn", None)
    monkeypatch.setattr(research, "_job_queue", jobs, raising=False)
    monkeypatch.setattr(research, "_worker_is_resting", lambda *a, **k: False)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    monkeypatch.setattr(research, "_try_claim_queue_doc", lambda *a, **k: True)
    monkeypatch.setattr(research, "_update_research_doc", db.update_research)
    asyncio.run(lift("_rescan_queue_for_unclaimed")())
    return db, [j["research_id"] for j in jobs._queue]


@pytest.mark.parametrize("blip", BLIPS, ids=["deadline", "unavailable", "503"])
def test_the_rescan_keeps_a_run_whose_record_blips_at_the_enqueue(monkeypatch, tmp_path, blip):
    """⛔⛔ THE SAME DEFECT ON THE SECOND CLAIM SITE — where a Retry lands when
    every worker is busy. It had written "ongoing" and deleted the claimed doc."""
    db, taken = _rescan(monkeypatch, tmp_path, _Answers(QUEUED, blip))

    assert db.queue_deleted == ["q1"], "the claimed doc was not deleted — nothing was at stake"
    assert [w[2]["status"] for w in db.writes] == ["ongoing"]
    assert taken == [RID], "a run whose queue document was already deleted was dropped"


def test_the_rescan_keeps_a_run_whose_record_cannot_be_read_at_all(monkeypatch, tmp_path):
    _db, taken = _rescan(monkeypatch, tmp_path, _Answers(TimeoutError("DeadlineExceeded")))
    assert taken == [RID]


def test_the_rescan_keeps_a_run_when_the_client_is_dropped_mid_claim(monkeypatch, tmp_path):
    db, taken = _rescan(monkeypatch, tmp_path, _Answers(QUEUED), drop_client=True)
    assert db.queue_deleted == ["q1"]
    assert taken == [RID]


@pytest.mark.parametrize("late", [None, {"status": "stopped"}], ids=["deleted", "stopped"])
def test_the_rescan_still_refuses_what_the_enqueue_read_answered(monkeypatch, tmp_path, late):
    _db, taken = _rescan(monkeypatch, tmp_path, _Answers(QUEUED, late))
    assert taken == []


# ══ 3. the two callers that keep the refusal, run through the real funnel ═

def _restore(monkeypatch, tmp_path, db):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    path = tmp_path / "queues" / "_pending_queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    job = {"uid": UID, "research_id": RID, "run_id": RUN, "topic": TOPIC,
           "email": "alice@example.com", "config": {}}
    path.write_text(json.dumps({"ts_ms": 1, "current": None, "pending": [job]}),
                    encoding="utf-8")
    q = _Q()
    research._restore_pending_queue_snapshot(path, q, set())
    kept = json.loads(path.read_text(encoding="utf-8"))["pending"]
    return [j["research_id"] for j in q._queue], [j["research_id"] for j in kept]


@pytest.mark.parametrize("db", [_RecordDb(_Answers(TimeoutError("DeadlineExceeded"))), None],
                         ids=["blip", "no-client"])
def test_boot_restore_still_refuses_a_run_it_could_not_check_and_keeps_its_entry(
        monkeypatch, tmp_path, db):
    """⛔⛔ THE BOOT RESTORE'S REASON, KEPT. It cannot tell a run worker 1 just
    parked for its person's Resume from one still waiting unless the read
    answers — so it does not act, and the entry stays for the next boot."""
    restored, kept = _restore(monkeypatch, tmp_path, db)
    assert restored == [], "the boot restore relaunched a run whose status it could not see"
    assert kept == [RID], "the entry was thrown away instead of kept for the next boot"


class _SupervisedDb:
    """A supervised machine whose run was mid-flight: the rehydrate query finds
    it ongoing and owned by this worker; the record read answers in order."""

    def __init__(self, answers):
        self.answers = answers
        self.writes: list = []

    def collection(self, name):
        return _SupNode(self, (name,))

    def update_research(self, uid, rid, updates):
        self.writes.append((uid, rid, dict(updates)))
        return True


class _SupNode:
    def __init__(self, db, parts):
        self._db, self._parts = db, parts

    def collection(self, name):
        return _SupNode(self._db, self._parts + (name,))

    document = collection

    def where(self, *_a, **_k):
        return self

    def get(self):
        p = self._parts
        if p == ("users", UID, "researches"):                       # the query
            snap = _Snap(ONGOING)
            snap.id = RID
            return [snap]
        if len(p) == 4 and p[0] == "users" and p[2] == "researches":
            return _Snap(self._db.answers.next())
        if p[0] == "devices":
            return _Snap({"supervised": True})
        return _Snap(None)


def test_rehydrate_refuses_a_run_it_could_not_check_and_offers_a_resume_instead(
        monkeypatch, tmp_path):
    """⭐ REFUSED, NOT LOST. The supervised auto-resume keeps the funnel's
    refusal; what follows it is the recovery mark, which gives the person a
    Resume card for the run."""
    db = _SupervisedDb(_Answers(ONGOING, TimeoutError("DeadlineExceeded")))
    (tmp_path / "queues" / RUN).mkdir(parents=True)
    q = _Q()
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setattr(research, "load_worker_count", lambda: 1)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda *a: [])
    monkeypatch.setattr(research, "_corroborated_run_id", lambda *a, **k: RUN)
    monkeypatch.setattr(research, "load_checkpoint", lambda _qd: {"topic": TOPIC})
    monkeypatch.setattr(research, "_update_research_doc", db.update_research)
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", q)

    asyncio.run(research._rehydrate_ongoing_for_tree(UID, UID, set()))

    assert db.answers.reads == 2, "the funnel never read the record — nothing was measured"
    assert list(q._queue) == [], "a run whose status could not be seen was auto-resumed"
    assert [(w[1], w[2]["status"]) for w in db.writes] == [(RID, "paused_backend_restart")], (
        "the refused run was left with no Resume card")


def test_rehydrate_still_auto_resumes_a_run_it_could_check(monkeypatch, tmp_path):
    """⭐ ACCEPT POLARITY for the fixture above: with the read answering, the
    same machine auto-resumes — so the refusal above is the read's doing."""
    db = _SupervisedDb(_Answers(ONGOING))
    (tmp_path / "queues" / RUN).mkdir(parents=True)
    q = _Q()
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setattr(research, "load_worker_count", lambda: 1)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda *a: [])
    monkeypatch.setattr(research, "_corroborated_run_id", lambda *a, **k: RUN)
    monkeypatch.setattr(research, "load_checkpoint", lambda _qd: {"topic": TOPIC})
    monkeypatch.setattr(research, "_update_research_doc", db.update_research)
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", q)

    asyncio.run(research._rehydrate_ongoing_for_tree(UID, UID, set()))

    assert [j["research_id"] for j in q._queue] == [RID]
    assert db.writes == []
