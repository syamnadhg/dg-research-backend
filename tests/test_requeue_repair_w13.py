"""Wave 13 — the machine's half of the integrated review's repair (09-29).

Four things the research computer did wrong around runs waiting in its queue:

  1. A removed sharer's waiting run (or a start document they left behind) is
     in every queue renumber, and each renumber sent that account's batch
     through the full heal. The rules refuse it for good, so it spent the one
     re-mint every research write shares — the owner's own next write was
     dropped — and three in a row latched STRUCTURAL for every account.
  2. The run's own person cancelling a waiting run that KEPT WORK (moved, or
     put back at boot with work done) had it written as a cancel —
     `cancelled: true`, the app's delete-on-close — where it is a stop.
  3. A waiting run dropped at pickup (a removed sharer's, or one whose record
     ended) stayed #1 in the published order until something else published.
  4. The boot restore's "one publish after the last park" ran a whole renumber
     on the event loop, before the server was listening.

⭐ EVERY TEST DRIVES THE REAL PATH: the real renumbers (the queue publisher and
`run_server`'s own), the real heal, the real record writer, the real move, the
real boot put-back, the real start listener, the real idle rescan and the real
boot restore — against one fake Firestore whose user-tree writes follow the
rules: a write into the tree of an account the device document no longer lists
is refused, and a stale credential refuses every user-tree write until a
re-mint. Each defect case sits beside a control that must not change.

Run:  pytest tests/test_requeue_repair_w13.py -v
"""
import base64
import collections
import json
import threading
import time as _real_time
import types

import pytest

import research
import test_requeue_w13 as T
# ⛔ IMPORTED HERE, AT COLLECTION: it reads `research.__file__` once, when it is
# first imported, and every test below points that at a temporary directory.
import _run_server_closure  # noqa: F401

OWNER = "owner-uid-repair-00000000000001"
SHARER = "sharer-uid-repair-0000000000002"
FORMER = "former-uid-repair-0000000000003"
DEVICE = "dev-repair-w13"
MARKER = ".waiting_for_worker"


class PermissionDenied(Exception):
    pass


def _tok(claims):
    def b(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
    return f"{b({'alg': 'RS256'})}.{b(claims)}.sig"


class Clock:
    def __init__(self):
        self.t = float(int(_real_time.time()))

    def time(self):
        return self.t

    def __getattr__(self, name):
        return getattr(_real_time, name)


class Creds:
    def __init__(self, fs):
        self.fs = fs
        self.token = _tok({"deviceId": DEVICE, "ownerUid": OWNER})
        self.refresh_calls = 0

    def refresh(self, _req):
        self.refresh_calls += 1
        self.fs.stale = False


class Snap:
    def __init__(self, data, doc_id=""):
        self._d, self.id = data, doc_id
        self.exists = data is not None

    def to_dict(self):
        return dict(self._d or {})


class Batch:
    def __init__(self, fs):
        self.fs, self.ops = fs, []

    def update(self, ref, payload):
        self.ops.append((ref.parts, dict(payload)))

    def commit(self):
        for parts, _p in self.ops:
            self.fs.check_user_write(parts[1])
        for parts, p in self.ops:
            self.fs.records.setdefault((parts[1], parts[3]), {}).update(p)
            self.fs.landed.append(("batch", parts[1], parts[3]))


class Node:
    def __init__(self, fs, parts):
        self.fs, self.parts = fs, parts

    def collection(self, name):
        return Node(self.fs, self.parts + (name,))

    document = collection

    def get(self, **kw):
        p = self.parts
        if len(p) == 2 and p[0] == "devices":
            if "timeout" in kw:
                self.fs.member_reads += 1
            if self.fs.device_unreadable:
                raise TimeoutError("DeadlineExceeded")
            return Snap(self.fs.device)
        if len(p) == 4 and p[2] == "researches":
            return Snap(self.fs.records.get((p[1], p[3])), p[3])
        return Snap(None)

    def update(self, payload):
        p = self.parts
        if len(p) == 2 and p[0] == "devices":
            self.fs.device_updates.append(dict(payload))
            return
        self.fs.check_user_write(p[1])
        if len(p) == 4 and p[2] == "researches":
            self.fs.records.setdefault((p[1], p[3]), {}).update(payload)
        self.fs.landed.append(("update", p[1], p[-1]))

    def set(self, payload, merge=False):
        self.fs.check_user_write(self.parts[1])
        self.fs.landed.append(("set", self.parts[1], self.parts[-1]))

    def limit(self, _n):
        return self

    def stream(self):
        if self.parts[-1] == "queue":
            return [Snap(d, f"q{i}") for i, d in enumerate(self.fs.start_docs)]
        return []


class FS:
    """Firestore as the rules answer this computer: the device document names
    its members, and a user-tree write for anybody else is refused."""

    def __init__(self, shared):
        self._credentials = Creds(self)
        self.device = {"ownerUid": OWNER, "sharedWith": list(shared)}
        self.device_unreadable = False
        self.member_reads = 0
        self.records: dict = {}
        self.start_docs: list = []
        self.device_updates: list = []
        self.landed: list = []
        self.refused: list = []
        self.stale = False

    def collection(self, name):
        return Node(self, (name,))

    def batch(self):
        return Batch(self)

    def members(self):
        return {self.device["ownerUid"], *self.device["sharedWith"]}

    def check_user_write(self, uid):
        if uid not in self.members() or self.stale:
            self.refused.append(uid)
            raise PermissionDenied("403 Missing or insufficient permissions.")


class SyncThread:
    """A background publish, run where it is started — so a test sees it."""

    def __init__(self, target=None, daemon=None, name=None, args=(), kwargs=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def machine(monkeypatch, tmp_path):
    def make(shared, worker=1, fleet=2):
        fs = FS(shared)
        clock = Clock()
        lines: list = []
        (tmp_path / "queues").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
        monkeypatch.setattr(research, "_firebase_db", fs)
        monkeypatch.setattr(research, "time", clock)
        monkeypatch.setattr(research, "log",
                            lambda msg, level="INFO", *a, **k: lines.append((level, str(msg))))
        monkeypatch.setattr(research, "load_device_id", lambda: DEVICE)
        monkeypatch.setattr(research, "load_paired_uid", lambda: OWNER)
        monkeypatch.setattr(research, "_config_device_id_uncached", lambda: DEVICE)
        monkeypatch.setattr(research, "_grpc_heal_last_ts", 0.0)
        monkeypatch.setattr(research, "_grpc_heal_consec_fail", 0)
        monkeypatch.setattr(research, "_grpc_heal_structural", False)
        monkeypatch.setattr(research, "WORKER_ID", worker)
        monkeypatch.setattr(research, "load_worker_count", lambda: fleet)
        monkeypatch.setattr(research, "_exit_scheduled", False)
        monkeypatch.setattr(research, "_RESTING_CACHE", {"at": 0.0, "ids": ()})
        monkeypatch.setattr(research, "_supervisor_is_my_parent", lambda: True)
        monkeypatch.setattr(research, "_wait_for_uploads_to_settle", lambda **k: 0)
        exits: list = []
        monkeypatch.setattr(research, "_schedule_server_exit",
                            lambda source, *a, **k: exits.append(source))
        monkeypatch.setattr(research, "_threading",
                            types.SimpleNamespace(Thread=SyncThread, Lock=threading.Lock))
        monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
        monkeypatch.setitem(research._QUEUE_STATE, "running", False)
        monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", None)
        monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_lock", None)
        monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_in_progress", False)
        return types.SimpleNamespace(fs=fs, clock=clock, lines=lines, exits=exits,
                                     root=tmp_path / "queues")
    return make


def _waiting(root, uid, rid, name, *, worker=None, moved_at_ms=None):
    """A run waiting in this computer's queue — the marker the move writes
    (`worker`: taken by that worker and not started)."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "checkpoint.json").write_text("{}", encoding="utf-8")
    rec = {"uid": uid, "research_id": rid, "run_id": name, "topic": "t", "email": "",
           "config": {}, "submitted_by": uid,
           "moved_at_ms": moved_at_ms or int(_real_time.time() * 1000), "from_worker": 2}
    marker = MARKER if worker is None else f"{MARKER}.w{worker}"
    (d / marker).write_text(json.dumps(rec), encoding="utf-8")
    return d


def _owner_write_needing_the_remint(m):
    """The owner's next research write, on a credential that needs re-minting —
    what every run's first user-tree write is, several seconds on."""
    m.clock.t += 5
    m.fs.stale = True
    return research._update_research_doc(OWNER, "chat_1759200000001_o", {"status": "ongoing"})


# ══ 1. a removed sharer's run in a renumber ═══════════════════════════════════

WAITING_RID = "chat_1759200000000_w"


def _renumber_waiting_run(monkeypatch, m, who):
    _waiting(m.root, who, WAITING_RID, "Waiting_20260929_120000")
    research._recompute_deferred_queue_positions_locked()


def _renumber_start_doc(monkeypatch, m, who):
    m.fs.start_docs = [{"uid": who, "submittedBy": who, "researchId": WAITING_RID,
                        "action": "start", "timestamp": 1759200000020}]
    research._recompute_deferred_queue_positions_locked()


def _renumber_local_line(monkeypatch, m, who):
    """`run_server`'s own renumber, over this worker's line."""
    from _run_server_closure import lift
    jq = types.SimpleNamespace(_queue=collections.deque(
        [{"uid": who, "research_id": WAITING_RID}]))
    monkeypatch.setattr(research, "_job_queue", jq, raising=False)
    lift("_recompute_queue_positions")()


def _renumber_boot_put_back(monkeypatch, m, who):
    """Boot: a run this worker took and never started goes back in the queue,
    and the order is published."""
    _waiting(m.root, who, WAITING_RID, "Waiting_20260929_120000", worker=1)
    assert research._release_waiting_claims(1) == 1


RENUMBERS = {
    "waiting-run": _renumber_waiting_run,
    "start-doc": _renumber_start_doc,
    "local-line": _renumber_local_line,
    "boot-put-back": _renumber_boot_put_back,
}

#: whose run is in the renumber, whether the device document can be read, and
#: whether that account's batch is written (through the heal, as always).
WHOSE = [
    (FORMER, True, False),     # ⛔ the defect: removed, and the document says so
    (SHARER, True, True),      # a member's positions are written as ever
    (FORMER, False, True),     # can't tell who shares it: as today
]
WHOSE_IDS = ["removed-sharer", "member", "membership-unreadable"]


@pytest.mark.parametrize("who, readable, written", WHOSE, ids=WHOSE_IDS)
@pytest.mark.parametrize("renumber", list(RENUMBERS))
def test_a_removed_sharers_run_in_a_renumber_leaves_the_remint_for_the_next_write(
        machine, monkeypatch, renumber, who, readable, written):
    """⛔⛔ THE DEFECT. A removed sharer's batch went through the full heal at
    every renumber: refused, re-minted (the one re-mint, with its 30-second
    cooldown), refused again. The owner's own write a few seconds later needed
    that re-mint and was dropped. The device document says the account is gone,
    so its batch is not written at all now — and the owner's write lands.
    ⭐ A member's batch is written, and a membership nobody could read is as
    today: its batch goes through the heal, and spends the re-mint."""
    m = machine(shared=[SHARER])
    m.fs.device_unreadable = not readable
    RENUMBERS[renumber](monkeypatch, m, who)

    attempted = who in m.fs.refused or ("batch", who, WAITING_RID) in m.fs.landed
    assert attempted is written, (m.fs.refused, m.fs.landed)
    if who == SHARER:
        assert ("batch", SHARER, WAITING_RID) in m.fs.landed, m.fs.landed
    lands = _owner_write_needing_the_remint(m)
    assert lands is (who == SHARER or readable), (
        m.fs._credentials.refresh_calls, [s for _l, s in m.lines if "grpc-heal" in s])


def test_three_renumbers_with_a_removed_sharers_run_never_latch_structural(machine):
    """⛔⛔ Three such renumbers 30 s apart with no research write landing in
    between — every worker resting while the member's run waits — latched
    STRUCTURAL: the re-mint switched off for every account, and "re-pair" or
    "another account" printed as the machine's fault."""
    m = machine(shared=[SHARER])
    _waiting(m.root, FORMER, WAITING_RID, "Waiting_20260929_120000")
    for _ in range(research._GRPC_HEAL_STRUCTURAL_AFTER):
        research._recompute_deferred_queue_positions_locked()
        m.clock.t += research._GRPC_HEAL_COOLDOWN_S + 1
    assert not [s for _l, s in m.lines if "STRUCTURAL" in s], m.lines
    assert research._grpc_heal_structural is False
    assert m.fs._credentials.refresh_calls == 0
    assert _owner_write_needing_the_remint(m) is True


@pytest.mark.parametrize("waiting_uid", [FORMER, SHARER], ids=["removed-sharer", "member"])
def test_the_move_right_after_a_renumber_still_writes_queued_at_1(machine, waiting_uid):
    """⛔⛔ THE OWNER'S NEXT MOVE. A renumber with a removed sharer's run in it
    spent the re-mint; the move ten seconds later returned "moved" and restarted
    the worker, and its "queued at #1" write was dropped — the record went on
    saying the run was running, on a worker that was now off."""
    m = machine(shared=[SHARER], worker=2)
    _waiting(m.root, waiting_uid, WAITING_RID, "Waiting_20260929_120000", moved_at_ms=1)
    rid = "chat_1759200000009_moved"
    run = m.root / "Moved_20260929_130000"
    (run / "documents").mkdir(parents=True)
    (run / "checkpoint.json").write_text("{}", encoding="utf-8")
    m.fs.records[(SHARER, rid)] = {"status": "ongoing", "assignedWorker": 2}
    research._QUEUE_STATE["current_job"] = {
        "uid": SHARER, "research_id": rid, "run_id": run.name, "topic": "t",
        "email": "", "config": {}, "submitted_by": SHARER}
    research._recompute_deferred_queue_positions_locked()   # a claim a moment before
    m.clock.t += 10
    m.fs.stale = True
    out = research._handle_requeue_command({
        "action": "requeue", "researchId": rid, "uid": SHARER, "workerId": 2,
        "submittedBy": OWNER})
    assert out == "moved" and m.exits == ["requeue"]
    rec = m.fs.records[(SHARER, rid)]
    assert rec.get("status") == "queued" and rec.get("queuePosition") == 1, rec


@pytest.mark.parametrize("waiting, reads", [
    ([OWNER], 0),                  # the paired account costs no read
    ([SHARER, FORMER], 1),         # read once per renumber, not once per account
], ids=["only-the-owners", "two-other-accounts"])
def test_the_device_document_is_read_once_and_only_for_another_account(
        machine, waiting, reads):
    m = machine(shared=[SHARER])
    for i, uid in enumerate(waiting):
        _waiting(m.root, uid, f"chat_17592000000{i:02d}_w", f"Waiting{i}_20260929_120000",
                 moved_at_ms=i + 1)
    research._recompute_deferred_queue_positions_locked()
    assert m.fs.member_reads == reads
    assert FORMER not in m.fs.refused


# ══ 2. the run's own person ends a waiting run that kept work: a stop ═════════

def _queued_resume_marker(folder, *, worker=None, resume=True):
    """A job a resting worker had only QUEUED, put back at boot (`queued_job`):
    a Resume of a run with work done (`resume_dir`), or a new run."""
    job = T._job(T.SHARER, T.RID, folder.name,
                 **({"resume_dir": str(folder)} if resume else {}))
    name = T.MARKER if worker is None else f"{T.MARKER}.w{worker}"
    (folder / name).write_text(json.dumps({
        "uid": T.SHARER, "research_id": T.RID, "run_id": folder.name, "moved_at_ms": 1,
        "queued_job": job}), encoding="utf-8")
    return job


def _queued_resume_waiting(folder):
    _queued_resume_marker(folder)
    return None


def _queued_resume_taken(folder):
    job = _queued_resume_marker(folder, worker=1)
    return [dict(job, moved_run=True, kept_work=True)]


def _moved_run_taken_marker_gone(folder):
    """This worker took a moved run into its line; its marker is not on disk
    any more — the job itself says it had work done."""
    return [T._job(T.SHARER, T.RID, folder.name, resume_dir=str(folder),
                   moved_run=True, kept_work=True)]


KEPT_WORK = {
    "queued-resume-waiting": _queued_resume_waiting,
    "queued-resume-taken": _queued_resume_taken,
    "moved-run-taken-marker-gone": _moved_run_taken_marker_gone,
}


@pytest.mark.parametrize("case", list(KEPT_WORK))
def test_the_runs_own_person_ending_a_waiting_run_with_work_done_stops_it(
        monkeypatch, tmp_path, case):
    """⛔⛔ THE PERSON'S CHAT SAYS "queued — Cancel" for every queued run, and
    the cancel it sends was written as a cancel: `cancelled: true` — the app's
    delete-on-close — and, for a Resume a resting worker put back, `phase: 0`
    as well. The research and its reports went when the chat closed. Every
    waiting run with work done is written as a stop now: `stopped`, and nothing
    about its steps or its summary touched."""
    _r, folder = T._run_folder(tmp_path, T.RID, uid=T.SHARER)
    (folder / "phase2_complete.marker").write_text("x", encoding="utf-8")
    line = KEPT_WORK[case](folder)
    lis, published = T._cancel_listener(monkeypatch, tmp_path, deque_jobs=line)

    lis.feed(action="cancel", uid=T.SHARER, submittedBy=T.SHARER, researchId=T.RID)

    mine = [p for _u, r, p in lis.writes if r == T.RID]
    assert [T._as_written(p) for p in mine] == [{"status": "stopped"}], mine
    assert "movedToQueueAt" in mine[0] and "queuePosition" in mine[0], "it still reads as queued"
    assert list(lis.jobs._queue) == [], "the stopped run is still in this worker's line"
    assert research._waiting_runs() == []
    if case != "moved-run-taken-marker-gone":
        assert (folder / ".stop").exists(), "it could still be taken and run"
    assert published.wait(5), "the queue order was not re-published"
    assert lis.incoming == ["incoming"], "the command was not taken away"


def test_a_new_run_taken_from_the_queue_is_still_cancelled_before_starting(
        monkeypatch, tmp_path):
    """The control: a NEW run a resting worker had only queued, taken into this
    worker's line and not started, has nothing to keep. Its own person's cancel
    stays the ordinary one."""
    folder = tmp_path / "queues" / f"Queued_{T._stamp()}"
    folder.mkdir(parents=True)
    job = _queued_resume_marker(folder, worker=1, resume=False)
    lis, _p = T._cancel_listener(monkeypatch, tmp_path,
                                 deque_jobs=[dict(job, moved_run=True, kept_work=False)])
    lis.feed(action="cancel", uid=T.SHARER, submittedBy=T.SHARER, researchId=T.RID)
    assert [T._as_written(p) for _u, r, p in lis.writes if r == T.RID] == [
        {"status": "stopped", "phase": 0, "summary": "Cancelled before starting",
         "cancelled": True}]


# ══ 3. a waiting run dropped at pickup leaves the published order ════════════

def _kicks(monkeypatch, m):
    """Every queue publish, with how many jobs were in this worker's line and
    how many records had been written when it was asked for."""
    kicks: list = []
    monkeypatch.setattr(research, "_kick_queue_publish",
                        lambda: kicks.append((len(research._job_queue._queue),
                                              len(m.writes))) or m.published.set())
    return kicks


DROPPED = ["removed-sharer", "stopped", "deleted"]


@pytest.mark.parametrize("why", DROPPED)
def test_a_waiting_run_dropped_at_pickup_leaves_the_published_order(
        monkeypatch, tmp_path, why):
    """⛔ A removed sharer's waiting run, or one whose record ended or went,
    is dropped by the next awake idle worker — and stayed the amber #1 in the
    device's `queueOwners`, every other run one place lower and the dropped
    run's record "queued #1" for good, until something else published."""
    m, folder = T._waiting(monkeypatch, tmp_path, worker=1)
    m.store.queue_docs.clear()
    if why == "removed-sharer":
        m.store.device = {"ownerUid": T.OWNER, "sharedWith": []}
    elif why == "stopped":
        m.store.records[(T.SHARER, T.RID)] = {"status": "stopped"}
    else:
        m.store.records.pop((T.SHARER, T.RID))
    assert T._rescan(monkeypatch, m) == []
    assert not (folder / T.MARKER).exists() and not list(folder.glob(f"{T.MARKER}.w*"))
    assert m.published.wait(5), "the dropped run is still published as waiting"


def test_a_run_the_funnel_refuses_at_pickup_leaves_the_published_order(monkeypatch, tmp_path):
    """The claim took the run and the funnel refused it: it no longer waits
    anywhere, and the order is published — not only when the run had used up
    its automatic attempts."""
    m, folder = T._waiting(monkeypatch, tmp_path, worker=1)
    m.store.queue_docs.clear()
    monkeypatch.setattr(research, "_safe_enqueue", lambda *a, **k: False)
    assert T._rescan(monkeypatch, m) == []
    assert not list(folder.glob(f"{T.MARKER}*"))
    assert m.published.wait(5), "the refused run is still published as waiting"


def test_a_drop_before_a_take_publishes_once_the_taken_run_is_in_the_line(
        monkeypatch, tmp_path):
    """⛔ The race a publish at the drop would open: started while the next run
    is being taken, it finds that run neither waiting nor in the line, and the
    publish after the take — finding one running — is skipped. So a pass that
    takes a run publishes once, after the run is in the line and its record
    says running."""
    m, folder = T._waiting(monkeypatch, tmp_path, worker=1)
    m.store.queue_docs.clear()
    m.store.device = {"ownerUid": T.OWNER, "sharedWith": [T.SHARER]}
    gone = tmp_path / "queues" / f"Former_{T._stamp()}"
    (gone / "documents").mkdir(parents=True)
    T._moved_marker(gone, "former-uid-requeue-0000000003", "chat_1759100000002_gone",
                    moved_at_ms=int(_real_time.time() * 1000) + 60_000)
    assert [w["research_id"] for w in research._waiting_runs()][0] == (
        "chat_1759100000002_gone"), "precondition: the removed sharer's run is first"
    kicks = _kicks(monkeypatch, m)

    assert [j["research_id"] for j in T._rescan(monkeypatch, m)] == [T.RID]
    assert not list(gone.glob(f"{T.MARKER}*")), "the removed sharer's run was not dropped"
    assert kicks == [(1, 1)], kicks
