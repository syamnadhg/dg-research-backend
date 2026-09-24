"""A restart's own recovery never loses a run to a read that failed once.

⛔⛔ WHAT WAS WRONG (wave 10.10 leftovers). Three places a restart recovers a
run gave up for good when Firestore blipped at boot — which is when blips
cluster: the network is coming up and the token is minutes old.

  (a) the BOOT RESTORE refused a snapshot entry whose record it could not read.
      That is right — #728: it must never relaunch a run on a status it could
      not see — but it "kept the entry for the next boot" by leaving it in the
      file, and the next worker boundary rewrote the file from the live queue.
      The claim had deleted the queue document before the crash, so that entry
      was the last description of the run, and its record said "queued" for
      ever.
  (b) the REHYDRATE's recovery mark — `paused_backend_restart`, or `stopped`
      for a run that keeps nothing — lost in the same blip left the run
      "ongoing" with nothing running it and no Resume card, until the next
      restart.
  (c) a RESUME with no usable run id in its payload, whose record read failed,
      deleted its queue document and wrote nothing: the card stayed up and the
      press did nothing.

⭐ WHAT EACH DOES NOW — silently, in the same process, on one short schedule:
  (a) the entry is HELD, carried by every snapshot rewrite, and offered again
      through the same funnel and the same whitelist until its record answers;
  (b) the mark is written again while the run is still "ongoing" and not
      running here;
  (c) the disk is asked, by owner, and a run found there is resumed — the
      dequeue's own read stands a deleted research down, as
      `test_deleted_research_never_runs_1010` pins for every job.

Every pin injects the failing read or write on the real path.

Run:  pytest tests/test_restart_recovery_retries_1010.py -v
"""
import asyncio
import collections
import json
import threading
import types

import pytest

import research
from _queue_listener import Listener
from _run_server_closure import lift

UID = "uid-alice"
RID = "chat_1758600000000_7"
RUN = "Alice_topic_20260923_101500"
INCOG = "incog_1758600000000_7"
INCOG_RUN = "incognito_1758600000000_7_20260923_101500"
TOPIC = "a paid research somebody is watching"

QUEUED = {"status": "queued", "topic": TOPIC}
ONGOING = {"status": "ongoing", "assignedWorker": 1, "deviceId": "dev-abcdef",
           "backendRunId": RUN, "topic": TOPIC}
PARKED = {"status": "paused_backend_restart", "topic": TOPIC}
STOPPED = {"status": "stopped", "topic": TOPIC}
ARCHIVED = {"status": "archived", "statusBeforeArchive": "queued", "topic": TOPIC}

#: Failures a real read throws that say nothing about the record.
BLIPS = [TimeoutError("DeadlineExceeded"),
         ConnectionError("UNAVAILABLE: failed to connect to all addresses"),
         RuntimeError("503 The service is currently unavailable")]
BLIP = BLIPS[0]
DENIED = PermissionError("403 Missing or insufficient permissions")


class _Answers:
    """The research record answering ONE read at a time, in order: the record,
    `None` for "read fine, no record", or an exception. The last repeats."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self.reads = 0

    def next(self):
        self.reads += 1
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _RecordDb:
    """Just `users/{uid}/researches/{rid}`, the way the funnel and the pickup
    rule read it."""

    def __init__(self, answers):
        self.answers = answers

    def collection(self, _name):
        return self

    def document(self, _name):
        return self

    def get(self):
        return _Snap(self.answers.next())


class _Q:
    def __init__(self, jobs=()):
        self._queue = collections.deque(jobs)

    def put_nowait(self, job):
        self._queue.append(job)


def _job(rid=RID, run_id=RUN):
    return {"uid": UID, "research_id": rid, "run_id": run_id, "topic": TOPIC,
            "email": "alice@example.com", "config": {}}


def _rids(jobs):
    return [j["research_id"] for j in jobs]


# ══ (a) the boot restore ══════════════════════════════════════════════════

def _machine(monkeypatch, tmp_path, answers):
    """A machine just booted: `answers` is its Firestore (None: no client)."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db",
                        None if answers is None else _RecordDb(answers))
    monkeypatch.setattr(research, "_RESTART_RETRY_DELAYS_S", (0, 0, 0))
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_lock", None)
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_in_progress", False)


def _snapshot(tmp_path, pending):
    path = tmp_path / "queues" / "_pending_queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts_ms": 1, "current": None, "pending": pending}),
                    encoding="utf-8")
    return path


def _in_file(path):
    return _rids(json.loads(path.read_text(encoding="utf-8"))["pending"])


def _boot_and_retry(path, q, before_retry=None):
    """Boot's restore on a running loop — as `run_server` calls it — then every
    retry it started, run to the end."""
    async def _go():
        research._restore_pending_queue_snapshot(path, q, set())
        if before_retry is not None:
            before_retry()
        await asyncio.gather(*list(research._RESTART_RETRIES))
    asyncio.run(_go())


def _worker_boundary(monkeypatch, path, q, running):
    """The REAL snapshot write at a worker boundary: `run_server`'s own
    `_persist_pending_queue`, with the job the worker just dequeued."""
    monkeypatch.setattr(research, "queues_root", path.parent, raising=False)
    monkeypatch.setattr(research, "_job_queue", q, raising=False)
    monkeypatch.setattr(research, "_pending_queue_path", path, raising=False)
    assert lift("_persist_pending_queue")(current_job=running) is True


def test_an_entry_boot_could_not_check_survives_the_next_worker_boundary(
        monkeypatch, tmp_path):
    """⛔⛔ THE DEFECT (a). Both reads fail, the restore rightly refuses — and
    the first time the worker takes somebody else's job, the rewrite from the
    live queue erased the entry. Nothing else on earth described that run."""
    _machine(monkeypatch, tmp_path, _Answers(BLIP))
    path = _snapshot(tmp_path, [_job()])
    q = _Q()

    research._restore_pending_queue_snapshot(path, q, set())
    assert list(q._queue) == [], (
        "the boot restore relaunched a run whose status it could not see (#728)")

    _worker_boundary(monkeypatch, path, q, running=_job("chat_bob_1", "Bob_20260923_1016"))
    assert _in_file(path) == [RID], (
        "the first worker boundary erased the only description of a run boot "
        "could not check")


@pytest.mark.parametrize("boot", ["both-reads-fail", "the-funnel-read-fails", "no-client"])
def test_a_held_entry_is_restored_once_its_record_can_be_read(monkeypatch, tmp_path, boot):
    """⭐ THE RECOVERY. Kept for the next boot and nothing more, it waited for a
    restart that might be days away. Now it is offered again, in this process,
    and runs as soon as a read SEES it waiting.

    ⛔ "the-funnel-read-fails" is the pickup rule's read answering and the
    funnel's own read, a moment later, failing: holding is decided by the read
    that refused, not by the one before it."""
    later = _RecordDb(_Answers(QUEUED))
    if boot == "no-client":
        _machine(monkeypatch, tmp_path, None)
        comes_back = lambda: monkeypatch.setattr(research, "_firebase_db", later)  # noqa: E731
    else:
        first = (BLIP, BLIP) if boot == "both-reads-fail" else (QUEUED, BLIP)
        _machine(monkeypatch, tmp_path, _Answers(*first, QUEUED))
        comes_back = None
    path = _snapshot(tmp_path, [_job()])
    q = _Q()

    _boot_and_retry(path, q, comes_back)

    assert _rids(q._queue) == [RID], "a run held on a failed read was never offered again"
    assert research._UNREAD_RESTORES == [], "a restored run is still held"


@pytest.mark.parametrize("answer", [PARKED, STOPPED, ARCHIVED, None],
                         ids=["parked-for-resume", "stopped", "archived", "deleted"])
def test_the_retry_never_starts_what_the_record_says_no_to(monkeypatch, tmp_path, answer):
    """⛔⛔ THE BOOT RESTORE'S REASON, KEPT (#728). A run rehydration parked for
    its person's Resume answers `paused_backend_restart` on the later read and
    is let go — as is one that is over, archived or gone. An answer ends the
    hold; it is not asked about again."""
    _machine(monkeypatch, tmp_path, _Answers(BLIP, BLIP, answer))
    path = _snapshot(tmp_path, [_job()])
    q = _Q()

    _boot_and_retry(path, q)

    assert list(q._queue) == [], "the retry relaunched a run its record said no to"
    assert research._UNREAD_RESTORES == [], "an entry that got its answer is still held"


def test_an_entry_that_stays_unreadable_is_asked_every_round_and_kept_for_the_next_boot(
        monkeypatch, tmp_path):
    """⭐ BOUNDED, AND NOTHING IS LOST WHEN IT RUNS OUT. Every try is a real
    read; none of them takes the job on a failure; and whatever is left is
    still held — so every rewrite carries it to the next boot."""
    answers = _Answers(BLIP)
    _machine(monkeypatch, tmp_path, answers)
    path = _snapshot(tmp_path, [_job()])
    q = _Q()

    _boot_and_retry(path, q)

    assert list(q._queue) == [], "a run nobody could see the status of was started"
    assert answers.reads == 2 + len(research._RESTART_RETRY_DELAYS_S), (
        "the schedule was not followed: each round is one read of the record")
    assert _rids(research._UNREAD_RESTORES) == [RID], "the entry was let go without an answer"
    _worker_boundary(monkeypatch, path, q, running=None)
    assert _in_file(path) == [RID]


def test_the_boot_rewrite_writes_a_held_entry_once_and_a_private_one_not_at_all(
        monkeypatch, tmp_path):
    """⛔ ONE ENTRY PER RESEARCH, AND NOTHING OF A RUN THAT KEEPS NOTHING. A
    snapshot holding a private run makes boot rewrite the file at once, and it
    hands its refused entries in too — so the held ordinary job is offered to
    the file twice. Two entries are two runs of it at the next boot. The private
    one is still asked about again, in memory; it is just never written down."""
    _machine(monkeypatch, tmp_path, _Answers(BLIP, BLIP, BLIP, BLIP, QUEUED))
    path = _snapshot(tmp_path, [_job(INCOG, INCOG_RUN), _job()])
    q = _Q()
    at_boot = {}

    _boot_and_retry(path, q, lambda: at_boot.update(raw=path.read_text(encoding="utf-8")))

    assert _rids(json.loads(at_boot["raw"])["pending"]) == [RID]
    assert INCOG not in at_boot["raw"], "a run that keeps nothing was written to the disk"
    assert sorted(_rids(q._queue)) == sorted([INCOG, RID]), (
        "a held run was not offered again once its record could be read")


def test_a_rewrite_with_nothing_queued_keeps_the_file_for_a_held_entry(monkeypatch, tmp_path):
    """⛔ THE OTHER REWRITE. A cancel that takes the last waiting run out of the
    queue rewrites the file — and with nothing queued and nothing running it
    DELETED the file, held entry and all."""
    _machine(monkeypatch, tmp_path, _Answers(BLIP))
    path = _snapshot(tmp_path, [_job()])
    q = _Q()
    research._restore_pending_queue_snapshot(path, q, set())

    research._shed_from_pending_snapshot(q)

    assert path.exists() and _in_file(path) == [RID], (
        "an empty queue's rewrite took the held entry away with the file")


def _hard_reset(monkeypatch, tmp_path, held):
    """Drive the REAL Reset Backend through the device-command listener, on a
    foreground serve, with `held` entries boot could not check."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    path = tmp_path / "queues" / "_pending_queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    q = _Q()
    writes: list = []
    captured: dict = {}

    class _Col:
        def on_snapshot(self, cb):
            captured["cb"] = cb
            return object()

        def stream(self):
            return iter(())

    class _Chain:
        def collection(self, name):
            return _Col() if name in ("commands", "queue") else self

        def document(self, _name):
            return self

    research._UNREAD_RESTORES.extend(held)
    monkeypatch.setattr(research, "_firebase_db", _Chain())
    monkeypatch.setattr(research, "_device_cmd_watch", None)
    monkeypatch.setattr(research, "_fs_where",
                        lambda *a, **k: types.SimpleNamespace(stream=lambda: []))
    monkeypatch.setattr(research, "_guard_snapshot", lambda cb, _label: cb)
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setattr(research, "_wait_for_uploads_to_settle", lambda **k: 0)
    monkeypatch.setattr(research, "_sweep_stuck_research_docs_for_device",
                        lambda *a, **k: (0, 0))
    monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [])
    monkeypatch.setattr(research, "load_paired_uid", lambda: UID)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda u, r, p: writes.append((r, dict(p))) or True)
    monkeypatch.setattr(research, "_schedule_server_exit", lambda *a, **k: None)
    monkeypatch.setattr(research, "queues_root", path.parent, raising=False)
    monkeypatch.setattr(research, "_job_queue", q, raising=False)
    monkeypatch.setattr(research, "_pending_queue_path", path, raising=False)
    monkeypatch.setitem(research._QUEUE_STATE, "persist_fn", lift("_persist_pending_queue"))
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_lock", threading.Lock())
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_in_progress", False)
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", q)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    research._start_device_command_listener(UID, "dev-abcdef")
    doc = types.SimpleNamespace(
        id="cmd-1", to_dict=lambda: {"action": "hard_reset", "submittedBy": UID},
        reference=types.SimpleNamespace(delete=lambda: None, update=lambda _d: None))
    change = types.SimpleNamespace(type=types.SimpleNamespace(name="ADDED"), document=doc)
    captured["cb"](None, [], None)          # the first attach: nothing waiting
    captured["cb"](None, [change], None)    # the person presses Reset Backend
    return writes, path


def test_reset_backend_drains_what_boot_is_holding(monkeypatch, tmp_path):
    """⛔⛔ THE ACCIDENT THIS FIX REMOVED WAS PROTECTING THE RESET. Before the
    carry, the reset's own snapshot rewrite dropped a held entry by the same
    mistake that lost it at a worker boundary. Carried, it would come back after
    "stop everything on this device", and run the moment a read saw "queued"."""
    writes, path = _hard_reset(monkeypatch, tmp_path, [_job()])

    assert (RID, "hard_reset_drained") in [(r, p.get("stoppedBy")) for r, p in writes], (
        "a run boot was holding was not stopped with the rest of the queue")
    assert research._UNREAD_RESTORES == [], "the reset left a held entry to be retried"
    assert RID not in _in_file(path), "the reset's clean snapshot carried the held entry"


# ══ (b) the rehydrate's recovery mark ═════════════════════════════════════

class _TreeDb:
    """A machine whose run was mid-flight when it restarted. The rehydrate query
    finds `rid` ongoing and owned by this worker; every read of the record
    answers from `answers`, in order."""

    def __init__(self, rid, answers, supervised):
        self.rid = rid
        self.answers = answers
        self.supervised = supervised

    def collection(self, name):
        return _TreeNode(self, (name,))


class _TreeNode:
    def __init__(self, db, parts):
        self._db, self._parts = db, parts

    def collection(self, name):
        return _TreeNode(self._db, self._parts + (name,))

    document = collection

    def where(self, *_a, **_k):
        return self

    def get(self):
        p = self._parts
        if p == ("users", UID, "researches"):                       # the query
            snap = _Snap(ONGOING)
            snap.id = self._db.rid
            return [snap]
        if len(p) == 4 and p[0] == "users" and p[2] == "researches":
            return _Snap(self._db.answers.next())
        if p[0] == "devices":
            return _Snap({"supervised": self._db.supervised})
        return _Snap(None)


class _Writes:
    """`_update_research_doc`, answering each attempt in order; the last repeats."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.attempts: list = []

    def __call__(self, _uid, rid, patch):
        self.attempts.append((rid, dict(patch)))
        return self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]

    @property
    def statuses(self):
        return [p.get("status") for _r, p in self.attempts]


def _rehydrate(monkeypatch, tmp_path, answers, writes, *, rid=RID, supervised=True,
               before_retry=None):
    """Boot rehydration over one run, then every retry it started, to the end."""
    (tmp_path / "queues" / RUN).mkdir(parents=True, exist_ok=True)
    q = _Q()
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", _TreeDb(rid, answers, supervised))
    monkeypatch.setattr(research, "_RESTART_RETRY_DELAYS_S", (0, 0, 0))
    monkeypatch.setattr(research, "load_worker_count", lambda: 1)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda *a: [])
    monkeypatch.setattr(research, "_corroborated_run_id", lambda *a, **k: RUN)
    monkeypatch.setattr(research, "load_checkpoint", lambda _qd: {"topic": TOPIC})
    monkeypatch.setattr(research, "_update_research_doc", writes)
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", q)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)

    async def _go():
        await research._rehydrate_ongoing_for_tree(UID, UID, set())
        if before_retry is not None:
            before_retry(q)
        await asyncio.gather(*list(research._RESTART_RETRIES))
    asyncio.run(_go())
    return q


def test_a_recovery_mark_lost_to_the_boot_blip_is_written_on_a_later_try(
        monkeypatch, tmp_path):
    """⛔⛔ THE DEFECT (b). A supervised machine: the auto-resume's read fails,
    so it rightly falls through to the Resume card — and the card's write fails
    in the same blip. The run sat "ongoing", with nothing running it and nothing
    to press, until the next restart."""
    writes = _Writes(False, True)
    q = _rehydrate(monkeypatch, tmp_path, _Answers(BLIP, BLIP, ONGOING), writes)

    assert list(q._queue) == [], "a run whose status could not be seen was auto-resumed"
    assert writes.statuses == ["paused_backend_restart", "paused_backend_restart"], (
        "the recovery mark lost to the blip was never written again")


def test_a_private_runs_stop_mark_is_written_on_a_later_try(monkeypatch, tmp_path):
    """⛔ THE SAME FOR A RUN THAT KEEPS NOTHING, whose mark is `stopped`. Left
    "ongoing" it holds its documents until its fuse burns out."""
    writes = _Writes(False, True)
    _rehydrate(monkeypatch, tmp_path, _Answers(BLIP, ONGOING), writes, rid=INCOG)

    assert writes.statuses == ["stopped", "stopped"], (
        "the stop mark lost to the blip was never written again, or was written "
        "as an offer of a Resume nobody can reach")


def test_the_retry_marks_a_record_it_still_cannot_read(monkeypatch, tmp_path):
    """⭐ THE SCAN'S OWN RULE: unreadable is taken. A read that keeps failing
    while writes get through must not keep the run unmarked."""
    writes = _Writes(False, True)
    _rehydrate(monkeypatch, tmp_path, _Answers(BLIP), writes)

    assert writes.statuses == ["paused_backend_restart", "paused_backend_restart"]


@pytest.mark.parametrize("answer", [STOPPED, None], ids=["stopped-since", "deleted-since"])
def test_the_retry_leaves_a_run_that_moved_on(monkeypatch, tmp_path, answer):
    """⛔⛔ MINUTES PASS BETWEEN TRIES. A person who pressed Stop in the meantime
    would have their run moved back to an offer of a Resume; a research deleted
    in the meantime is the pickup rule's to stand down."""
    writes = _Writes(False, True)
    _rehydrate(monkeypatch, tmp_path, _Answers(BLIP, BLIP, answer), writes)

    assert len(writes.attempts) == 1, "the retry wrote over a run that had moved on"


@pytest.mark.parametrize("where", ["running", "waiting"])
def test_the_retry_leaves_a_run_this_process_holds_again(monkeypatch, tmp_path, where):
    """⛔ A CRASH CARD'S RETRY LANDS ON THE RESUME PATH, which writes "ongoing"
    and queues the run — so the status alone cannot tell. A Resume card over a
    live run is the wave-10.7 shape of lie."""
    def _picked_up_again(q):
        job = _job()
        if where == "running":
            research._QUEUE_STATE["current_job"] = job
        else:
            q._queue.append(job)

    writes = _Writes(False, True)
    _rehydrate(monkeypatch, tmp_path, _Answers(BLIP, BLIP, ONGOING), writes,
               before_retry=_picked_up_again)

    assert len(writes.attempts) == 1, "a Resume card was written over a run this process holds"


def test_the_retry_ends_after_its_schedule(monkeypatch, tmp_path):
    """⭐ BOUNDED. One try per round, then it stops; the next boot's rehydration
    finds the record still "ongoing" and marks it then."""
    writes = _Writes(False)
    _rehydrate(monkeypatch, tmp_path, _Answers(BLIP, BLIP, ONGOING), writes)

    assert len(writes.attempts) == 1 + len(research._RESTART_RETRY_DELAYS_S)


# ══ (c) the Resume ════════════════════════════════════════════════════════

def _run_on_disk(tmp_path, owner_uid):
    d = tmp_path / "queues" / RUN
    d.mkdir(parents=True)
    (d / "owner.json").write_text(json.dumps({"uid": owner_uid, "researchId": RID}),
                                  encoding="utf-8")
    return d


def _resume(monkeypatch, tmp_path, failure):
    """A Resume whose payload carries no run id — the web copies the record's,
    so the record had none — fed to the REAL start listener, with every read of
    the record raising `failure`."""
    return Listener(monkeypatch, tmp_path, owner=UID, research_docs=failure).feed(
        action="resume", uid=UID, submittedBy=UID, researchId=RID,
        email="alice@example.com")


@pytest.mark.parametrize("failure", [*BLIPS, DENIED],
                         ids=["deadline", "unavailable", "503", "denied"])
def test_a_resume_whose_record_cannot_be_read_resumes_the_run_on_its_disk(
        monkeypatch, tmp_path, failure):
    """⛔⛔ THE DEFECT (c). The press did nothing: the queue doc was deleted, no
    job was queued and nothing was written back, while the card stayed up. The
    run it names is on this computer, and the disk says whose it is."""
    run_dir = _run_on_disk(tmp_path, UID)
    lis = _resume(monkeypatch, tmp_path, failure)

    assert [(j["run_id"], j["resume_dir"]) for j in lis.enqueued] == [(RUN, str(run_dir))], (
        "a Resume for a run on this computer did nothing because a read failed")
    assert lis.incoming == ["incoming"], "the taken Resume was left to replay"
    assert not any("lastError" in w[2] for w in lis.writes), (
        "a run being resumed was told it could not be")
    assert not any("backendRunId" in w[2] for w in lis.writes), (
        "a run id was written into a record nobody could read")


@pytest.mark.parametrize("failure", [BLIP, DENIED], ids=["blip", "denied"])
def test_with_nothing_on_the_disk_a_failed_read_still_says_nothing(
        monkeypatch, tmp_path, failure):
    """⭐ OTHER POLARITY. No run of this person's for this research on the disk:
    a failed read is not the machine's to call a failed run, and a doc left in
    place replays at the next attach — possibly after the run finished — into a
    path that writes "ongoing". The card stays; the web's own wait speaks."""
    lis = _resume(monkeypatch, tmp_path, failure)

    assert lis.enqueued == []
    assert lis.writes == [], "a read that merely failed was reported as a failed run"
    assert lis.incoming == ["incoming"], "the Resume doc was left to replay later"


def test_a_failed_read_never_resumes_somebody_elses_run_for_that_research(
        monkeypatch, tmp_path):
    """⛔⛔ THE DISK IS ASKED ABOUT A PERSON. Research ids are published to every
    member, so a directory for this research that is another member's must not
    answer for the sender."""
    _run_on_disk(tmp_path, "uid-mallory")
    lis = _resume(monkeypatch, tmp_path, BLIP)

    assert lis.enqueued == [], "another person's run was resumed on a failed read"
