"""Wave 13 — "Move to queue": the research computer's side.

The owner long-presses a busy worker's pill in the Shared-with popup and picks
"Move to queue". The app puts that worker in `restingWorkerIds`, then writes a
device command `{action: "requeue", researchId, uid, workerId, submittedBy}`.
Decided with the owner:
  · the run goes to the FRONT of the queue (#1; whatever was already waiting
    moves down one), keeping everything it has done, and later goes on from
    the start of the step it was on;
  · the worker it ran on stays off; the next worker that is ON takes it, and
    if none is on it waits until one is turned on.

And three things the same wave settles about a run that waits:
  · a RESTING worker whose run a restart interrupted puts it at the front of
    the queue instead of resuming it (before, a rest only guarded NEW starts);
  · a waiting run keeps its folder however long it waits — the startup sweep
    and the boot restore's 7-day rule leave it alone;
  · "Clear Local Storage" never deletes the folder of a run running on ANY
    worker or waiting in any queue (before, the idle second worker deleted the
    busy one's folder).

⭐ EVERY TEST DRIVES THE REAL PATH — the device-command listener's callback,
the idle rescan and the worker loop lifted out of `run_server`
(`_run_server_closure`), the start listener (`_queue_listener`), boot
rehydration, the boot restore against a real snapshot file, the startup sweep
and the queue-order publisher — and every refusal sits BESIDE a case that
acts, so code that did nothing (the base) and code that did everything are
both red.

Run:  pytest tests/test_requeue_w13.py -v
"""
import ast
import asyncio
import collections
import json
import os
import threading
import time
import types
from datetime import datetime

import pytest

import research
# ⛔ IMPORTED HERE, AT COLLECTION: it reads `research.__file__` once, when it is
# first imported, and every test below points that at a temporary directory.
import _run_server_closure  # noqa: F401

OWNER = "owner-uid-requeue-000000000001"
SHARER = "sharer-uid-requeue-00000000002"
DEVICE = "dev-requeue-w13"
RID = "chat_1759100000000_moved"
OTHER_RID = "chat_1759100000001_other"
MARKER = ".waiting_for_worker"


# ══ a small machine ══════════════════════════════════════════════════════════

def _stamp(days=0.0):
    return datetime.fromtimestamp(time.time() - days * 86400).strftime("%Y%m%d_%H%M%S")


def _run_folder(tmp_path, rid, *, uid=SHARER, topic="Moved_Topic", days=0.0,
                delivery="ongoing"):
    """A run folder as a run in progress leaves it: its owner file, its
    delivery record, its checkpoint — and, when `days` is given, that old."""
    run_id = f"{topic}_{_stamp(days)}"
    d = tmp_path / "queues" / run_id
    (d / "documents").mkdir(parents=True)
    (d / "owner.json").write_text(json.dumps({"uid": uid, "researchId": rid}),
                                  encoding="utf-8")
    (d / "delivery.json").write_text(json.dumps({"status": delivery}), encoding="utf-8")
    (d / "checkpoint.json").write_text(json.dumps({"topic": topic.replace("_", " ")}),
                                       encoding="utf-8")
    (d / "documents" / "brief.md").write_text("# Research Brief\n\n" + "x" * 200,
                                              encoding="utf-8")
    if days:
        then = time.time() - days * 86400
        os.utime(d, (then, then))
    return run_id, d


def _job(uid, rid, run_id, **extra):
    job = {"uid": uid, "research_id": rid, "run_id": run_id, "topic": "a topic",
           "email": "someone@example.com", "config": {"skipPhases": [4]},
           "submitted_by": uid}
    job.update(extra)
    return job


def _moved_marker(folder, uid, rid, *, moved_at_ms=None, worker=None):
    """A run already waiting in the queue — the marker the move writes."""
    rec = {"uid": uid, "research_id": rid, "run_id": folder.name, "topic": "a topic",
           "email": "someone@example.com", "config": {}, "submitted_by": uid,
           "moved_at_ms": moved_at_ms if moved_at_ms is not None else int(time.time() * 1000),
           "from_worker": 1}
    name = MARKER if worker is None else f"{MARKER}.w{worker}"
    (folder / name).write_text(json.dumps(rec), encoding="utf-8")
    return folder / name


class _Snap:
    def __init__(self, data, doc_id=""):
        self._data = data
        self.exists = data is not None
        self.id = doc_id

    def to_dict(self):
        return dict(self._data or {})


class _QueueDoc(_Snap):
    def __init__(self, store, doc_id, data):
        super().__init__(data, doc_id)
        self.reference = self
        self._store = store

    def delete(self):
        self._store.queue_docs.pop(self.id, None)
        self._store.queue_deleted.append(self.id)

    def update(self, _payload):
        pass

    def get(self, **_kw):
        return _Snap(self._store.queue_docs.get(self.id), self.id)


class _Batch:
    def __init__(self, store):
        self._store = store

    def update(self, ref, payload):
        self._store.batched.append((ref.parts, dict(payload)))

    def commit(self):
        pass


class _Node:
    def __init__(self, store, parts):
        self._store, self.parts = store, parts

    def collection(self, name):
        return _Node(self._store, self.parts + (name,))

    document = collection

    def get(self, **_kw):
        p = self.parts
        if len(p) == 2 and p[0] == "devices":
            return _Snap(self._store.device)
        if len(p) == 4 and p[0] == "users" and p[2] == "researches":
            answer = self._store.records.get((p[1], p[3]))
            if isinstance(answer, BaseException):
                raise answer
            return _Snap(answer, p[3])
        if p[-1] == "researches":            # the rehydrate query
            return [_Snap(v, rid) for (uid, rid), v in self._store.records.items()
                    if uid == p[1] and isinstance(v, dict) and v.get("status") == "ongoing"]
        return _Snap(None)

    def where(self, *_a, **_k):
        return self

    def limit(self, _n):
        return self

    def stream(self):
        if self.parts[-1] == "queue":
            return [_QueueDoc(self._store, i, d) for i, d in list(self._store.queue_docs.items())]
        return []

    def on_snapshot(self, cb):
        self._store.callbacks[self.parts[-1]] = cb
        return object()

    def update(self, payload):
        if len(self.parts) == 2 and self.parts[0] == "devices":
            self._store.device_updates.append(dict(payload))


class _Store:
    """`users/{uid}/researches/{rid}`, `devices/{id}` and its `queue`."""

    def __init__(self, records=None, device=None, queue_docs=None):
        self.records = dict(records or {})
        self.device = device if device is not None else {
            "ownerUid": OWNER, "sharedWith": [SHARER], "supervised": True}
        self.queue_docs = dict(queue_docs or {})
        self.queue_deleted: list = []
        self.device_updates: list = []
        self.batched: list = []
        self.callbacks: dict = {}

    def collection(self, name):
        return _Node(self, (name,))

    def batch(self):
        return _Batch(self)


class _Q:
    def __init__(self):
        self._queue = collections.deque()

    def put_nowait(self, job):
        self._queue.append(job)

    def qsize(self):
        return len(self._queue)


def _machine(monkeypatch, tmp_path, store, *, worker=1, fleet=2):
    """This computer: its disk under `tmp_path`, `store` as Firestore, research
    writes and exits RECORDED, never performed."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    (tmp_path / "queues").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(research, "_firebase_db", store)
    monkeypatch.setattr(research, "load_paired_uid", lambda: OWNER)
    monkeypatch.setattr(research, "load_device_id", lambda: DEVICE)
    monkeypatch.setattr(research, "WORKER_ID", worker)
    monkeypatch.setattr(research, "load_worker_count", lambda: fleet)
    monkeypatch.setattr(research, "_exit_scheduled", False)
    monkeypatch.setattr(research, "_RESTING_CACHE", {"at": 0.0, "ids": ()})
    monkeypatch.setattr(research, "_tracks_dir", None)
    monkeypatch.setitem(research._REST_DEFER_SEEN, "v", False)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    monkeypatch.setitem(research._QUEUE_STATE, "running", False)
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", None)
    monkeypatch.setitem(research._QUEUE_STATE, "recompute_deferred_fn", None)
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_lock", None)
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_in_progress", False)
    m = types.SimpleNamespace(writes=[], exits=[], lines=[], store=store,
                              published=threading.Event())
    # The queue order is re-published on a thread; recorded, not performed.
    monkeypatch.setattr(research, "_recompute_deferred_queue_positions", m.published.set)
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda u, r, p: m.writes.append((u, r, dict(p))) or True)
    monkeypatch.setattr(research, "_schedule_server_exit",
                        lambda source, *a, **k: m.exits.append(source))
    monkeypatch.setattr(research, "_wait_for_uploads_to_settle", lambda **k: 0)
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO": m.lines.append((level, str(msg))))
    return m


def _said(m, *parts):
    return [msg for _lvl, msg in m.lines if all(p in msg for p in parts)]


def _statuses(m, rid):
    return [p.get("status") for _u, r, p in m.writes if r == rid and "status" in p]


# ══ 1. the command, through the real device-command listener ════════════════

class _CmdRef:
    def __init__(self, sink):
        self._sink = sink

    def delete(self):
        self._sink.append("deleted")

    def update(self, payload):
        self._sink.append(("update", dict(payload)))


def _command(monkeypatch, m, data):
    """Hand the REAL device-command listener one live command. Returns what
    happened to the command document."""
    monkeypatch.setattr(research, "_device_cmd_watch", None)
    monkeypatch.setattr(research, "_fs_where",
                        lambda *a, **k: types.SimpleNamespace(stream=lambda: []))
    monkeypatch.setattr(research, "_guard_snapshot", lambda cb, _label: cb)
    research._start_device_command_listener(OWNER, DEVICE)
    cb = m.store.callbacks["commands"]
    fate: list = []
    doc = types.SimpleNamespace(id="cmd-requeue", to_dict=lambda: dict(data),
                                reference=_CmdRef(fate))
    change = types.SimpleNamespace(type=types.SimpleNamespace(name="ADDED"), document=doc)
    cb(None, [], None)            # the first attach: nothing waiting
    cb(None, [change], None)      # the owner presses Move to queue
    return fate


def _requeue(workerId=2, **over):
    data = {"action": "requeue", "researchId": RID, "uid": SHARER, "workerId": workerId,
            "submittedBy": OWNER, "timestamp": int(time.time() * 1000)}
    data.update(over)
    return data


def _running(monkeypatch, tmp_path, *, worker=2, supervised=True, rid=RID, uid=SHARER):
    """Worker `worker` running a sharer's run, halfway through, with its folder
    on disk and the pipeline's record globals naming it."""
    store = _Store(records={(uid, rid): {"status": "ongoing"}})
    m = _machine(monkeypatch, tmp_path, store, worker=worker)
    run_id, folder = _run_folder(tmp_path, rid, uid=uid)
    job = _job(uid, rid, run_id)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", job)
    monkeypatch.setattr(research, "_supervisor_is_my_parent", lambda: supervised)
    monkeypatch.setattr(research, "_fb_uid", uid)
    monkeypatch.setattr(research, "_fb_research_id", rid)
    return m, job, folder


def test_move_to_queue_keeps_the_run_puts_it_first_and_restarts_the_worker(
        monkeypatch, tmp_path):
    """⭐ THE FEATURE. The run's folder, finished steps and checkpoint stay; it
    waits at #1 with the whole job written down; its record says queued with no
    card left up; the worker is kept off and restarts — the one stop this
    machine already survives with everything kept. No stop is requested and no
    `.stop` is written: either would end the run instead."""
    m, job, folder = _running(monkeypatch, tmp_path)
    stops: list = []
    monkeypatch.setattr(research, "_controls",
                        types.SimpleNamespace(request_stop=lambda: stops.append(1)))

    fate = _command(monkeypatch, m, _requeue())

    marker = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    assert (marker["uid"], marker["research_id"], marker["run_id"]) == (
        SHARER, RID, folder.name), marker
    assert (marker["email"], marker["config"], marker["submitted_by"]) == (
        job["email"], job["config"], SHARER), "the job was not written down whole"
    assert marker["from_worker"] == 2
    queued = [p for u, r, p in m.writes if (u, r) == (SHARER, RID)]
    assert queued and queued[0]["status"] == "queued" and queued[0]["queuePosition"] == 1, (
        m.writes)
    assert "pendingDecision" in queued[0], "a decision card was left up on a queued run"
    assert m.exits == ["requeue"], "the worker did not restart to let the run go"
    assert stops == [], "a stop was requested — that writes 'stopped' over the run"
    assert not (folder / ".stop").exists(), "the run was ended for good"
    assert json.loads((folder / "delivery.json").read_text())["status"] == "ongoing"
    assert (folder / "checkpoint.json").exists() and (folder / "documents" / "brief.md").exists()
    rests = [u["restingWorkerIds"] for u in m.store.device_updates if "restingWorkerIds" in u]
    assert rests and list(rests[0].values) == [2], "the worker was not kept off"
    owners = [u["queueOwners"] for u in m.store.device_updates if "queueOwners" in u]
    assert owners and owners[-1][0] == {"uid": SHARER, "runId": RID, "position": 1}, owners
    assert fate == ["deleted"], "the command was not taken away by the worker it named"
    assert len(_said(m, "REQUEUE", RID[:8], "moved to the front of the queue")) == 1, m.lines


def test_the_pipeline_cannot_write_over_the_queued_record_in_its_last_second(
        monkeypatch, tmp_path):
    """⛔ The worker has a second or two before it exits, and its pipeline
    writes "ongoing" at every step boundary. After the move those writes land
    nowhere; the queued record stands."""
    m, _job_, _folder = _running(monkeypatch, tmp_path)
    _command(monkeypatch, m, _requeue())
    before = list(m.writes)

    research._update_firestore_research({"status": "ongoing", "phase": 2})

    assert m.writes == before, f"the pipeline wrote over the queued record: {m.writes[len(before):]}"


def test_a_command_for_another_worker_is_left_for_it(monkeypatch, tmp_path):
    """⛔ Every worker is its own process on the same stream. A worker the
    command does not name must not take it away — the one it names might not
    have seen it yet. Beside it, the named worker takes it."""
    m, _job_, folder = _running(monkeypatch, tmp_path, worker=1)
    fate = _command(monkeypatch, m, _requeue(workerId=2))
    assert fate == [], "worker 1 deleted a command meant for worker 2"
    assert not (folder / MARKER).exists() and m.exits == []
    assert len(_said(m, "REQUEUE", "for worker 2", "not this one (1)")) == 1, m.lines

    m2, _j2, folder2 = _running(monkeypatch, tmp_path / "w2", worker=2)
    assert _command(monkeypatch, m2, _requeue(workerId=2)) == ["deleted"]
    assert (folder2 / MARKER).exists()


@pytest.mark.parametrize("workerId", [0, 7, "x", None, True],
                         ids=["zero", "out-of-fleet", "text", "missing", "bool"])
def test_a_command_naming_no_worker_is_answered_by_worker_one(monkeypatch, tmp_path, workerId):
    """A workerId that names no worker of this computer would otherwise sit in
    the collection for ever, since every worker leaves what is not its own.
    Worker 1 takes it away with one line — and moves nothing."""
    m, _job_, folder = _running(monkeypatch, tmp_path, worker=1)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    fate = _command(monkeypatch, m, _requeue(workerId=workerId))
    assert fate == ["deleted"]
    assert not (folder / MARKER).exists() and m.exits == []
    assert len(_said(m, "REQUEUE: ignored", "is not running on worker 1")) == 1, m.lines


REFUSALS = [
    ("not-owner", dict(submittedBy=SHARER), "only this computer's owner"),
    ("unsigned", dict(submittedBy=""), "only this computer's owner"),
    ("other-research", dict(researchId=OTHER_RID), "is not running on worker 2"),
    ("other-account", dict(uid=OWNER), "is not running on worker 2"),
]


@pytest.mark.parametrize("over, why", [(o, w) for _i, o, w in REFUSALS],
                         ids=[i for i, _o, _w in REFUSALS])
def test_a_refused_move_does_nothing_and_says_why_in_one_line(monkeypatch, tmp_path, over, why):
    """⛔ Only the owner may move a run, and only the run the command names —
    the research AND its account, since research ids are on the device document
    every member reads. Refused: no marker, no record write, no restart, one
    plain line."""
    m, _job_, folder = _running(monkeypatch, tmp_path)
    fate = _command(monkeypatch, m, _requeue(**over))
    assert not (folder / MARKER).exists(), "a refused move put the run in the queue"
    assert m.writes == [] and m.exits == [], (m.writes, m.exits)
    assert fate == ["deleted"], "the named worker left its refused command behind"
    assert len(_said(m, "REQUEUE: ignored", why)) == 1, m.lines


def test_a_run_that_keeps_nothing_is_not_moved(monkeypatch, tmp_path):
    """An incognito run cannot wait anywhere: a restart ends it, and a waiting
    one would keep its folder. It keeps running; the line says so."""
    rid = f"incog_{int(time.time() * 1000)}_7"
    m, _job_, folder = _running(monkeypatch, tmp_path, rid=rid)
    _command(monkeypatch, m, _requeue(researchId=rid))
    assert not (folder / MARKER).exists() and m.exits == [] and m.writes == []
    assert len(_said(m, "REQUEUE: ignored", "keeps nothing")) == 1, m.lines


def test_a_run_already_handed_to_the_cloud_is_not_moved(monkeypatch, tmp_path):
    m, _job_, folder = _running(monkeypatch, tmp_path)
    (folder / "delivery.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    _command(monkeypatch, m, _requeue())
    assert not (folder / MARKER).exists() and m.exits == [] and m.writes == []
    assert len(_said(m, "REQUEUE: ignored", "finished its part")) == 1, m.lines


def test_a_backend_started_by_hand_does_not_move_the_run(monkeypatch, tmp_path):
    """⛔ The move restarts the worker, and nothing restarts a backend started
    by hand in a terminal — it would simply be gone. Refused, with the reason."""
    m, _job_, folder = _running(monkeypatch, tmp_path, supervised=False)
    _command(monkeypatch, m, _requeue())
    assert not (folder / MARKER).exists() and m.exits == [] and m.writes == []
    assert len(_said(m, "REQUEUE: ignored", "not running on startup")) == 1, m.lines


def test_a_run_with_nothing_saved_yet_is_not_moved(monkeypatch, tmp_path):
    """A run whose folder does not exist yet has nothing to go on from. No
    folder is made up for it, it is not put in the queue and the worker does
    not restart; the line says why."""
    m, job, folder = _running(monkeypatch, tmp_path)
    import shutil
    shutil.rmtree(folder)
    _command(monkeypatch, m, _requeue())
    assert not folder.exists(), "a folder was made up for a run that had none"
    assert m.exits == [] and m.writes == []
    assert len(_said(m, "REQUEUE: ignored", "nothing saved")) == 1, m.lines


def test_a_second_move_of_the_same_run_is_a_no_op(monkeypatch, tmp_path):
    """Idempotent: once the worker is leaving, a repeated press moves nothing
    and restarts nothing again."""
    m, _job_, folder = _running(monkeypatch, tmp_path)
    _command(monkeypatch, m, _requeue())
    monkeypatch.setattr(research, "_exit_scheduled", True)
    first = (list(m.writes), list(m.exits), (folder / MARKER).read_text())
    _command(monkeypatch, m, _requeue())
    assert (m.writes, m.exits, (folder / MARKER).read_text()) == first
    assert len(_said(m, "REQUEUE: ignored", "already restarting")) == 1, m.lines


# ══ 2. the next worker that is ON takes it — first ══════════════════════════

def _rescan(monkeypatch, m, *, resting=False, fleet=2):
    """Run the REAL idle rescan once. Returns the jobs it queued."""
    from _run_server_closure import lift
    jobs = _Q()
    monkeypatch.setattr(research, "load_worker_count", lambda: fleet)
    monkeypatch.setattr(research, "_job_queue", jobs, raising=False)
    monkeypatch.setattr(research, "_worker_is_resting", lambda *a, **k: resting)
    monkeypatch.setattr(research, "_rest_keepalive_pass", lambda: None)
    monkeypatch.setattr(research, "_try_claim_queue_doc", lambda *a, **k: True)
    asyncio.run(lift("_rescan_queue_for_unclaimed")())
    return list(jobs._queue)


def _deferred_start(ts_ago_s=60):
    return {"q-later": {"action": "start", "uid": OWNER, "submittedBy": OWNER,
                        "researchId": OTHER_RID, "topic": "Later",
                        "timestamp": int((time.time() - ts_ago_s) * 1000)}}


def _waiting(monkeypatch, tmp_path, *, worker=1, fleet=2, record="queued", days=0.0):
    store = _Store(records={(SHARER, RID): {"status": record},
                            (OWNER, OTHER_RID): {"status": "queued"}},
                   queue_docs=_deferred_start())
    m = _machine(monkeypatch, tmp_path, store, worker=worker, fleet=fleet)
    _run_id, folder = _run_folder(tmp_path, RID, days=days)
    _moved_marker(folder, SHARER, RID)
    return m, folder


def test_the_next_awake_worker_takes_the_moved_run_before_anything_deferred(
        monkeypatch, tmp_path):
    """⭐ THE FRONT OF THE QUEUE. An idle worker that is on takes the moved run
    — ahead of a start document that waited longer — resumes it from its own
    folder, and says so on the record: running, on this worker."""
    m, folder = _waiting(monkeypatch, tmp_path, worker=1)
    queued = _rescan(monkeypatch, m)

    assert [j["research_id"] for j in queued] == [RID], queued
    job = queued[0]
    assert (job["resume_dir"], job["run_id"], job["uid"]) == (str(folder), folder.name, SHARER)
    assert (job["email"], job["submitted_by"], job.get("moved_run")) == (
        "someone@example.com", SHARER, True)
    assert "q-later" in m.store.queue_docs, "a deferred start was claimed past the moved run"
    assert not (folder / MARKER).exists() and (folder / f"{MARKER}.w1").exists(), (
        "the run was queued here but is still up for grabs")
    ongoing = [p for u, r, p in m.writes if (u, r) == (SHARER, RID)]
    assert ongoing and ongoing[0]["status"] == "ongoing" and ongoing[0]["assignedWorker"] == 1
    assert m.published.wait(5), "the rest of the queue did not move up"


def test_a_resting_worker_never_takes_it_and_an_awake_one_does(monkeypatch, tmp_path):
    """⛔ The worker it was moved off — or any worker the owner turned off —
    leaves it waiting. The same worker turned back on takes it."""
    m, folder = _waiting(monkeypatch, tmp_path, worker=2)
    assert _rescan(monkeypatch, m, resting=True) == []
    assert (folder / MARKER).exists() and m.writes == []

    assert [j["research_id"] for j in _rescan(monkeypatch, m, resting=False)] == [RID]


def test_a_single_worker_computer_takes_it_when_its_worker_is_back_on(monkeypatch, tmp_path):
    """⛔ One worker: the rescan used to stand down entirely unless a rest had
    deferred a start document, so a moved run would have waited for ever after
    the owner turned the worker back on."""
    m, _folder = _waiting(monkeypatch, tmp_path, worker=1, fleet=1)
    m.store.queue_docs.clear()
    assert [j["research_id"] for j in _rescan(monkeypatch, m, fleet=1)] == [RID]


def test_a_run_its_old_worker_still_holds_is_put_back_and_keeps_its_place(
        monkeypatch, tmp_path):
    """⛔⛔ The worker it was moved off has a few seconds of exit left. Taking
    the run then is two browsers on one run. Put back — and no deferred start
    is claimed past it in the meantime."""
    m, folder = _waiting(monkeypatch, tmp_path, worker=1)
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research",
                        lambda rid, _w: [{"worker_id": 2, "pid": 1, "research_id": rid,
                                          "started_at": 1}] if rid == RID else [])
    assert _rescan(monkeypatch, m) == []
    assert (folder / MARKER).exists(), "the run lost its place in the queue"
    assert "q-later" in m.store.queue_docs, "a deferred start jumped the moved run"
    assert m.writes == []


@pytest.mark.parametrize("record", ["stopped", "completed", "paused_backend_restart", None],
                         ids=["stopped", "completed", "offered-a-resume", "deleted"])
def test_a_moved_run_nobody_is_waiting_for_any_more_stops_waiting(monkeypatch, tmp_path, record):
    """Stopped while it waited, over, or deleted: it is not run, its marker goes
    (so it holds no folder for ever), and its record is not written. Beside it,
    a record the move's "queued" write never reached — still "ongoing", nobody
    holding it — is TAKEN: dropping it would lose the run."""
    m, folder = _waiting(monkeypatch, tmp_path, worker=1, record=record)
    if record is None:
        m.store.records.pop((SHARER, RID))
    assert _rescan(monkeypatch, m) == []
    assert not (folder / MARKER).exists() and not list(folder.glob(f"{MARKER}.w*"))
    assert [w for w in m.writes if w[1] == RID] == []

    m2, _folder2 = _waiting(monkeypatch, tmp_path / "never-landed", worker=1, record="ongoing")
    assert [j["research_id"] for j in _rescan(monkeypatch, m2)] == [RID]


def test_the_run_moved_most_recently_is_first(monkeypatch, tmp_path):
    """The owner's rule: a moved run goes to #1 and what already waited moves
    down one — so of two moved runs, the later move is taken first."""
    store = _Store(records={(SHARER, RID): {"status": "queued"},
                            (OWNER, OTHER_RID): {"status": "queued"}})
    m = _machine(monkeypatch, tmp_path, store, worker=1)
    _r1, earlier = _run_folder(tmp_path, OTHER_RID, uid=OWNER, topic="Earlier")
    _r2, later = _run_folder(tmp_path, RID, uid=SHARER, topic="Later")
    now = int(time.time() * 1000)
    _moved_marker(earlier, OWNER, OTHER_RID, moved_at_ms=now - 60_000)
    _moved_marker(later, SHARER, RID, moved_at_ms=now)
    assert [j["research_id"] for j in _rescan(monkeypatch, m)] == [RID]
    assert (earlier / MARKER).exists()


def test_a_run_a_sibling_took_first_is_skipped_and_the_next_one_taken(monkeypatch, tmp_path):
    """⛔ Two idle workers can reach the same run at once. The rename is the
    arbiter: the one that loses gets nothing for that run and goes on to the
    next waiting one, instead of giving up."""
    store = _Store(records={(SHARER, RID): {"status": "queued"},
                            (OWNER, OTHER_RID): {"status": "queued"}})
    m = _machine(monkeypatch, tmp_path, store, worker=1)
    _a, gone = _run_folder(tmp_path, RID, topic="Gone")
    _b, next_ = _run_folder(tmp_path, OTHER_RID, uid=OWNER, topic="Next")
    _moved_marker(next_, OWNER, OTHER_RID)
    real = research._waiting_runs
    # Listed a moment ago; a sibling has renamed its marker away since.
    snapshot = [{"uid": SHARER, "research_id": RID, "moved_at_ms": 2, "_dir": gone}] + real()
    monkeypatch.setattr(research, "_waiting_runs", lambda: list(snapshot))
    assert [j["research_id"] for j in _rescan(monkeypatch, m)] == [OTHER_RID]


def test_a_moved_run_ended_for_good_is_not_taken_and_stops_waiting(monkeypatch, tmp_path):
    """A run somebody ended for good (`.stop`) while it waited is refused by
    the queue's own funnel: not run, not left half-taken, and its record is
    not told it is running."""
    m, folder = _waiting(monkeypatch, tmp_path, worker=1)
    (folder / ".stop").touch()
    assert _rescan(monkeypatch, m) == []
    assert not (folder / MARKER).exists() and not (folder / f"{MARKER}.w1").exists()
    assert [w for w in m.writes if w[1] == RID] == []


def test_a_damaged_marker_never_stops_the_queue(monkeypatch, tmp_path):
    """⛔ Every start and every rescan reads these markers. One that is not
    JSON, not an object, or carries a time that is not a number must not stop
    the reader — or no start would be taken on this computer again. The good
    run is still taken; the odd time sorts last."""
    m, folder = _waiting(monkeypatch, tmp_path, worker=1)
    for name, body in (("Broken", "{not json"), ("Listy", "[]"),
                       ("Odd", json.dumps({"uid": SHARER, "research_id": "chat_odd",
                                           "moved_at_ms": "soon"}))):
        _r, d = _run_folder(tmp_path, f"chat_{name}", topic=name)
        (d / MARKER).write_text(body, encoding="utf-8")
    ranked = [r["research_id"] for r in research._waiting_runs()]
    assert ranked == [RID, "chat_odd"], ranked
    assert [j["research_id"] for j in _rescan(monkeypatch, m)] == [RID]


def test_a_worker_that_died_before_starting_it_puts_it_back_at_boot(monkeypatch, tmp_path):
    """A taken run is in one worker's memory only. If that worker dies before
    starting it, its next boot puts the run back for any worker — its own
    taken markers only."""
    m = _machine(monkeypatch, tmp_path, _Store(), worker=2)
    _r1, mine = _run_folder(tmp_path, RID)
    _r2, theirs = _run_folder(tmp_path, OTHER_RID, topic="Theirs")
    _moved_marker(mine, SHARER, RID, worker=2)
    _moved_marker(theirs, SHARER, OTHER_RID, worker=3)
    assert research._release_waiting_claims(2) == 1
    assert m.published.wait(5), "the queue order was not re-published"
    assert (mine / MARKER).exists() and not (mine / f"{MARKER}.w2").exists()
    assert (theirs / f"{MARKER}.w3").exists() and not (theirs / MARKER).exists()
    assert len(_said(m, "worker 2", "back in the queue")) == 1, m.lines


def test_the_run_stops_waiting_once_the_worker_that_took_it_starts_it(monkeypatch, tmp_path):
    """⭐ Through the REAL dequeue: once the taking worker's lock names the
    run, the taken marker goes — nothing may take it again, and it no longer
    holds its folder as a waiting run."""
    from _run_server_closure import run_worker_once
    store = _Store(records={(SHARER, RID): {"status": "ongoing"}})
    m = _machine(monkeypatch, tmp_path, store, worker=1)
    _run_id, folder = _run_folder(tmp_path, RID)
    _moved_marker(folder, SHARER, RID, worker=1)
    job = _job(SHARER, RID, folder.name, resume_dir=str(folder), moved_run=True)
    started = run_worker_once(monkeypatch, tmp_path, job, flip="skipped(ongoing)", db=store,
                              update_research=lambda *a, **k: True, device_id=DEVICE)
    assert len(started) == 1 and started[0]["resume_dir"] == str(folder), m.lines
    assert not (folder / f"{MARKER}.w1").exists(), "the run still reads as waiting after it started"


# ══ 3. a new start waits behind it ═══════════════════════════════════════════

def test_a_new_start_waits_behind_a_moved_run(monkeypatch, tmp_path):
    """⛔ An idle worker that is on used to claim a brand-new start document on
    the spot, putting it ahead of the run the owner had just moved to #1. It
    is deferred now, as it would be behind a busy worker. Beside it: with
    nothing waiting, the same start runs at once."""
    from _queue_listener import Listener
    monkeypatch.setitem(research._QUEUE_STATE, "running", False)
    monkeypatch.setattr(research, "_recompute_deferred_queue_positions", lambda: None)
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(OWNER, OTHER_RID): {"status": "queued"}})
    lis.feed(action="start", uid=OWNER, submittedBy=OWNER, researchId=OTHER_RID,
             topic="Brand new")
    assert [j["research_id"] for j in lis.enqueued] == [OTHER_RID], "precondition"

    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(OWNER, OTHER_RID): {"status": "queued"}})
    _r, folder = _run_folder(tmp_path, RID)
    _moved_marker(folder, SHARER, RID)
    lis.feed(action="start", uid=OWNER, submittedBy=OWNER, researchId=OTHER_RID,
             topic="Brand new")
    assert lis.enqueued == [], "a new start ran ahead of the moved run"
    assert [p.get("status") for u, r, p in lis.writes if r == OTHER_RID] == ["queued"]


# ══ 4. the order everybody sees ══════════════════════════════════════════════

def test_moved_runs_are_published_first_and_everything_else_moves_down(monkeypatch, tmp_path):
    """⭐ "#1; runs already waiting become #2, #3". The amber pill on the
    person's row comes from `queueOwners`; their own app reads its record's
    position. Two moved runs and one deferred start: newest move #1, the
    earlier move #2, the start #3 — and no `status` in the renumber, because a
    worker can take a run between the scan and the commit."""
    store = _Store(queue_docs=_deferred_start())
    m = _machine(monkeypatch, tmp_path, store)
    monkeypatch.setattr(research, "_local_pending_owner_entries", lambda: [])
    _a, earlier = _run_folder(tmp_path, "chat_earlier_move", uid=OWNER, topic="Earlier")
    _b, later = _run_folder(tmp_path, RID, uid=SHARER, topic="Later")
    now = int(time.time() * 1000)
    _moved_marker(earlier, OWNER, "chat_earlier_move", moved_at_ms=now - 5000)
    _moved_marker(later, SHARER, RID, moved_at_ms=now)

    research._recompute_deferred_queue_positions_locked()

    owners = [u["queueOwners"] for u in store.device_updates if "queueOwners" in u][-1]
    assert [(o["runId"], o["position"]) for o in owners] == [
        (RID, 1), ("chat_earlier_move", 2), (OTHER_RID, 3)], owners
    assert owners[0]["uid"] == SHARER
    pos = {parts[3]: p for parts, p in store.batched}
    assert pos[RID]["queuePosition"] == 1 and pos["chat_earlier_move"]["queuePosition"] == 2
    assert pos["chat_earlier_move"]["queuedBehindRunId"] == RID
    assert pos[OTHER_RID]["queuePosition"] == 3
    assert pos[OTHER_RID]["queuedBehindRunId"] == "chat_earlier_move"
    assert pos[OTHER_RID]["queueTotalAhead"] == 2
    assert (pos[OTHER_RID]["queueAheadFromSelf"], pos[OTHER_RID]["queueAheadFromOthers"]) == (
        1, 1), "the runs waiting ahead were not counted by whose they are"
    assert (pos["chat_earlier_move"]["queueAheadFromSelf"],
            pos["chat_earlier_move"]["queueAheadFromOthers"]) == (0, 1)
    assert all("status" not in p for p in pos.values()), pos
    del m


@pytest.mark.parametrize("queue_docs", [{}, {"q-claimed": {
    "action": "start", "uid": OWNER, "submittedBy": OWNER, "researchId": OTHER_RID,
    "topic": "Claimed", "timestamp": 1, "assignedWorker": 1}}], ids=["empty", "all-claimed"])
def test_a_moved_run_is_published_when_nothing_else_waits(monkeypatch, tmp_path, queue_docs):
    """Both "nothing else waits" branches publish it — no queue documents at
    all, or only ones a worker already claimed. It is the common case right
    after a move on a computer with nothing else queued."""
    store = _Store(queue_docs=queue_docs)
    _machine(monkeypatch, tmp_path, store)
    monkeypatch.setattr(research, "_local_pending_owner_entries", lambda: [])
    _r, folder = _run_folder(tmp_path, RID)
    _moved_marker(folder, SHARER, RID)
    research._recompute_deferred_queue_positions_locked()
    owners = [u["queueOwners"] for u in store.device_updates if "queueOwners" in u]
    assert owners == [[{"uid": SHARER, "runId": RID, "position": 1}]], owners
    assert [(parts[3], p["queuePosition"]) for parts, p in store.batched] == [(RID, 1)]


# ══ 5. boot: a resting worker does not resume its interrupted run ════════════

def _boot_rehydrate(monkeypatch, tmp_path, *, resting, waiting=False, record="ongoing"):
    store = _Store(records={(OWNER, RID): None})
    m = _machine(monkeypatch, tmp_path, store, worker=1)
    run_id, folder = _run_folder(tmp_path, RID, uid=OWNER)
    store.records[(OWNER, RID)] = {"status": record, "backendRunId": run_id,
                                   "deviceId": DEVICE, "assignedWorker": 1,
                                   "submittedBy": OWNER}
    if waiting:
        _moved_marker(folder, OWNER, RID)
    q = _Q()
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", q)
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda *_a: [])
    monkeypatch.setattr(research, "_worker_is_resting", lambda *a, **k: resting)
    counts = asyncio.run(research._rehydrate_ongoing_for_tree(OWNER, OWNER, set()))
    return m, q, folder, counts


def test_a_resting_worker_puts_its_interrupted_run_first_in_the_queue(monkeypatch, tmp_path):
    """⭐⭐ BEFORE: an update or a crash on a worker the owner had turned off
    brought its run straight back up on it — a rest only ever guarded NEW
    start documents. Now it waits at the front of the queue, as queued, for a
    worker that is on. Beside it, an awake worker resumes it as before."""
    m, q, folder, counts = _boot_rehydrate(monkeypatch, tmp_path, resting=True)
    assert list(q._queue) == [], "a resting worker resumed its run"
    assert (folder / MARKER).exists(), "the run is not waiting in the queue"
    assert _statuses(m, RID) == ["queued"], m.writes
    assert counts == (0, 0)
    assert m.published.wait(5), "the queue order was not re-published"

    m2, q2, folder2, counts2 = _boot_rehydrate(monkeypatch, tmp_path / "awake", resting=False)
    assert [j["research_id"] for j in q2._queue] == [RID] and counts2 == (1, 0)
    assert not (folder2 / MARKER).exists() and _statuses(m2, RID) == []
    assert not m2.published.is_set()


def test_a_run_waiting_in_the_queue_is_left_there_even_by_an_awake_worker(
        monkeypatch, tmp_path):
    """⛔ The worker a run was moved off can write "ongoing" in its last second.
    Boot must not resume it on the spot, nor put a Resume card over it: it is
    put back to queued and left for the queue to hand out."""
    m, q, folder, counts = _boot_rehydrate(monkeypatch, tmp_path, resting=False, waiting=True)
    assert list(q._queue) == [] and counts == (0, 0)
    assert (folder / MARKER).exists()
    assert _statuses(m, RID) == ["queued"], m.writes
    assert _said(m, RID[:24], "waiting in the queue")
    assert m.published.wait(5), "the queue order was not re-published"


# ══ 6. boot: the disk snapshot ════════════════════════════════════════════════

def _snapshot(tmp_path, current, pending=()):
    path = tmp_path / "queues" / "_pending_queue.json"
    path.write_text(json.dumps({"ts_ms": 1, "current": current, "pending": list(pending)}),
                    encoding="utf-8")
    return path


def _in_file(path):
    if not path.exists():
        return []
    s = json.loads(path.read_text(encoding="utf-8"))
    return [j.get("research_id") for j in ([s.get("current")] + s.get("pending", [])) if j]


def test_the_moved_run_is_not_restored_from_the_snapshot_however_old(monkeypatch, tmp_path):
    """⛔⛔ The run the owner moved is the job this worker was running, so it is
    in the snapshot as `current`. Restored, it would run on the worker that was
    turned off; dropped as stale after a week, it would be lost. It is the
    queue's: not restored, the snapshot lets go of its copy, and its folder and
    marker stay. Beside it an ordinary waiting job is restored."""
    store = _Store(records={(SHARER, RID): {"status": "queued"},
                            (OWNER, OTHER_RID): {"status": "queued"}})
    m = _machine(monkeypatch, tmp_path, store, worker=2)
    monkeypatch.setattr(research, "_worker_is_resting", lambda *a, **k: True)
    run_id, folder = _run_folder(tmp_path, RID, days=10)
    _moved_marker(folder, SHARER, RID)
    other = _job(OWNER, OTHER_RID, f"Other_{_stamp()}")
    path = _snapshot(tmp_path, _job(SHARER, RID, run_id), [other])
    q = _Q()

    research._restore_pending_queue_snapshot(path, q, set())

    assert [j["research_id"] for j in q._queue] == [OTHER_RID], m.lines
    assert RID not in _in_file(path), "the snapshot still carries the moved run"
    assert folder.is_dir() and (folder / MARKER).exists()
    assert not _said(m, RID[:8], "waited 10 days"), "the moved run was judged by its age"


def test_a_resting_workers_interrupted_run_in_the_snapshot_waits_in_the_queue(
        monkeypatch, tmp_path):
    """⭐ The runs boot rehydration cannot see (a sharer's, while sharer
    rehydration is off) come back through the snapshot. On a resting worker
    the one it was RUNNING goes to the front of the queue; a job it had merely
    queued is restored as before. Beside it, an awake worker restores both."""
    for resting, expect in ((True, [OTHER_RID]), (False, [RID, OTHER_RID])):
        base = tmp_path / ("resting" if resting else "awake")
        store = _Store(records={(SHARER, RID): {"status": "ongoing"},
                                (OWNER, OTHER_RID): {"status": "queued"}})
        m = _machine(monkeypatch, base, store, worker=2)
        monkeypatch.setattr(research, "_worker_is_resting", lambda *a, _r=resting, **k: _r)
        run_id, folder = _run_folder(base, RID)
        path = _snapshot(base, _job(SHARER, RID, run_id),
                         [_job(OWNER, OTHER_RID, f"Other_{_stamp()}")])
        q = _Q()
        research._restore_pending_queue_snapshot(path, q, set())
        assert [j["research_id"] for j in q._queue] == expect, (resting, m.lines)
        assert (folder / MARKER).exists() is resting
        assert _statuses(m, RID) == (["queued"] if resting else []), m.writes
        assert m.published.wait(5) if resting else not m.published.is_set()


# ══ 7. a waiting run keeps its folder ═════════════════════════════════════════

def test_the_startup_sweep_keeps_a_waiting_runs_folder_however_old(monkeypatch, tmp_path):
    """⛔ A moved run's delivery still says "ongoing" and nobody touches its
    folder while it waits, so a week of resting workers made it look like a
    failed run left behind — and the sweep deleted the checkpoint it waits to
    resume from. Waiting, or taken and not started: kept. Beside them, a
    genuinely abandoned folder of the same age still goes."""
    _machine(monkeypatch, tmp_path, _Store())
    monkeypatch.setattr(research, "_firebase_db", None)
    _a, waiting = _run_folder(tmp_path, RID, topic="Waiting", days=30)
    _b, taken = _run_folder(tmp_path, OTHER_RID, topic="Taken", days=30)
    _c, left = _run_folder(tmp_path, "chat_left_behind", topic="Left", days=30)
    _moved_marker(waiting, SHARER, RID)
    _moved_marker(taken, SHARER, OTHER_RID, worker=2)
    for d in (waiting, taken, left):
        then = time.time() - 30 * 86400
        os.utime(d, (then, then))

    research._startup_sweep_stale_runs(tmp_path / "queues")

    assert waiting.is_dir() and taken.is_dir()
    assert not left.exists(), "the sweep stopped sweeping"


def _boot_calls(*names):
    """The lines where `run_server` calls each of `names`, in one parse."""
    from _run_server_closure import _SOURCE
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    server = next(n for n in tree.body
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_server")
    calls = [n for n in ast.walk(server) if isinstance(n, ast.Call)]
    return [[c.lineno for c in calls if getattr(c.func, "id", "") == name] for name in names]


def test_boot_runs_the_sweep_and_puts_taken_runs_back_before_rehydrating():
    """⛔ `run_server` cannot be run by a test, so its two new calls are pinned
    by where they sit: the startup sweep (lifted out to be RUN above) is still
    called, and a worker's taken-but-unstarted runs go back in the queue
    BEFORE rehydration looks — which must see them as waiting, not as this
    worker's to resume."""
    sweep, release, rehydrate = _boot_calls(
        "_startup_sweep_stale_runs", "_release_waiting_claims", "_rehydrate_ongoing_for_tree")
    assert len(sweep) == 1
    assert len(release) == 1 and rehydrate, (release, rehydrate)
    assert release[0] < min(rehydrate), "taken runs are put back after rehydration ran"


# ══ 8. Clear Local Storage ═══════════════════════════════════════════════════

def test_clear_local_storage_keeps_every_run_running_or_waiting(monkeypatch, tmp_path):
    """⛔⛔ REPRODUCED ON 58d705e AND 40c9655: the idle second worker took the
    command, kept only ITS OWN run's folder — it had none — and deleted the
    busy worker's run mid-flight. Kept now: a run any live worker's lock names,
    a run waiting for a worker, and every job in any worker's snapshot. Beside
    them a leftover folder, and one named only by a dead worker's lock, go."""
    store = _Store()
    m = _machine(monkeypatch, tmp_path, store, worker=2)
    q = tmp_path / "queues"
    _a, busy = _run_folder(tmp_path, "chat_busy_on_w1", topic="Busy")
    _b, waiting = _run_folder(tmp_path, RID, topic="Waiting")
    _c, snap_pending = _run_folder(tmp_path, "chat_pending_w1", topic="Pending")
    _d, snap_current = _run_folder(tmp_path, "chat_current_w3", topic="Current")
    _e, dead = _run_folder(tmp_path, "chat_dead_lock", topic="Dead")
    _f, leftover = _run_folder(tmp_path, "chat_leftover", topic="Leftover")
    (q / ".worker.1.lock").write_text(json.dumps({
        "pid": os.getpid(), "worker_id": 1, "research_id": "chat_busy_on_w1",
        "run_id": busy.name, "started_at": int(time.time() * 1000)}), encoding="utf-8")
    (q / ".worker.4.lock").write_text(json.dumps({
        "pid": 2 ** 22 + 12345, "worker_id": 4, "research_id": "chat_dead_lock",
        "run_id": dead.name, "started_at": int(time.time() * 1000)}), encoding="utf-8")
    _moved_marker(waiting, SHARER, RID)
    (q / "_pending_queue.json").write_text(json.dumps({
        "current": None, "pending": [_job(OWNER, "chat_pending_w1", snap_pending.name)]}),
        encoding="utf-8")
    (q / "_pending_queue_worker_3.json").write_text(json.dumps({
        "current": _job(OWNER, "chat_current_w3", snap_current.name), "pending": []}),
        encoding="utf-8")

    fate = _command(monkeypatch, m, {"action": "clear_local_storage", "submittedBy": OWNER,
                                     "timestamp": int(time.time() * 1000)})

    assert fate == ["deleted"]
    for kept in (busy, waiting, snap_pending, snap_current):
        assert kept.is_dir(), f"{kept.name} was deleted while running or waiting"
    assert not leftover.exists() and not dead.exists(), "the clear stopped clearing"
    assert (q / "_pending_queue.json").exists() and (q / ".worker.1.lock").exists()
    assert _said(m, "CLEAR_LOCAL_STORAGE", "wiped 2 dir(s)", "kept 4 run(s)"), m.lines


# ══ 9. Reset Backend ends the waiting runs too ═══════════════════════════════

def test_reset_backend_ends_the_runs_waiting_for_a_worker(monkeypatch, tmp_path):
    """⛔ Reset Backend is "stop everything on this computer". A waiting run
    lives on this disk, in no list the reset drained, so it came back after the
    reset and ran on the first awake worker. It is ended for good now and kept
    in the person's list as stopped — not purged: it had real work in it."""
    from _run_server_closure import lift
    store = _Store()
    m = _machine(monkeypatch, tmp_path, store, worker=1)
    _r, folder = _run_folder(tmp_path, RID)
    _moved_marker(folder, SHARER, RID)
    q = _Q()
    path = tmp_path / "queues" / "_pending_queue.json"
    monkeypatch.setattr(research, "_sweep_stuck_research_docs_for_device", lambda *a, **k: (0, 0))
    monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [])
    monkeypatch.setattr(research, "queues_root", path.parent, raising=False)
    monkeypatch.setattr(research, "_job_queue", q, raising=False)
    monkeypatch.setattr(research, "_pending_queue_path", path, raising=False)
    monkeypatch.setitem(research._QUEUE_STATE, "persist_fn", lift("_persist_pending_queue"))
    import threading
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_lock", threading.Lock())
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", q)

    _command(monkeypatch, m, {"action": "hard_reset", "submittedBy": OWNER,
                              "timestamp": int(time.time() * 1000)})

    assert not (folder / MARKER).exists(), "the run is still waiting after the reset"
    assert (folder / ".stop").exists(), "the run could still be picked up again"
    ended = [p for u, r, p in m.writes if (u, r) == (SHARER, RID)]
    assert ended and ended[0]["status"] == "stopped" and ended[0]["stoppedBy"] == "hard_reset_drained"
    assert "cancelled" not in ended[0], "a run with real work in it was marked for purge"


# ══ 10. the app learns this computer can do it ════════════════════════════════

def _one_heartbeat(monkeypatch, tmp_path, *, supervised):
    """Run the REAL heartbeat loop for exactly one tick."""
    store = _Store()
    m = _machine(monkeypatch, tmp_path, store, worker=1)

    class _Tick(Exception):
        pass

    async def _stop(_s):
        raise _Tick()

    monkeypatch.setattr(research, "_supervisor_is_my_parent", lambda: supervised)
    monkeypatch.setattr(research, "_device_version_fields",
                        lambda **k: {"version": "9.9.9", "servingVersion": "9.9.9"})
    monkeypatch.setattr(research, "_last_published_version_fields", None)
    monkeypatch.setattr(research, "_last_published_requeue_patch", None, raising=False)
    monkeypatch.setattr(research, "_version_publish_next_ms", 0)
    monkeypatch.setattr(research, "_publish_run_log_index", lambda: None)
    monkeypatch.setattr(research, "_prune_due", lambda *_a: False, raising=False)
    monkeypatch.setattr(research, "_spawn_maintenance", lambda *a, **k: None)
    monkeypatch.setattr(research.asyncio, "sleep", _stop)
    with pytest.raises(_Tick):
        asyncio.run(research._heartbeat_loop())
    return m, [u for u in store.device_updates if "requeueRuns" in u]


def test_the_heartbeat_tells_the_app_move_to_queue_works_here(monkeypatch, tmp_path):
    """⭐ The app shows "Move to queue" only where this key is on the device
    document: this build, running under its startup supervisor. Its OWN write
    — a rules deploy that has not admitted it must cost the chip, never the
    version row. Beside it, a backend started by hand clears the key."""
    m, sent = _one_heartbeat(monkeypatch, tmp_path, supervised=True)
    assert sent == [{"requeueRuns": 1}], sent
    assert [u for u in m.store.device_updates if "version" in u] == [
        {"version": "9.9.9", "servingVersion": "9.9.9"}], (
        "the version patch changed — or the capability joined it, where one "
        "unadmitted key refuses both")

    _m2, sent2 = _one_heartbeat(monkeypatch, tmp_path / "by-hand", supervised=False)
    from google.cloud.firestore import DELETE_FIELD
    assert sent2 == [{"requeueRuns": DELETE_FIELD}], sent2
