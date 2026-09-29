"""A serve that starts never re-runs a job that is stale or not this computer's.

⛔⛔ WHAT HAPPENED (serve log 2026-09-29 03:32Z). The boot restore read
`queues/_pending_queue.json` and put back a chat-assistant research queued EIGHT
days earlier by an account this computer was no longer shared with. Its record
read was refused (403); the pickup rule took the job anyway — "a read that fails
is not a deletion" — and the enqueue funnel "trusted the FE-side queue write".
The run went ahead with every Firestore write refused, on the owner's ChatGPT and
Anthropic key, and nobody could see it. Then the heal latched "re-pair required",
which was false: re-pairing this computer changes nothing about another account.

⭐ WHAT THE BOOT RESTORE DOES NOW, each on positive evidence and with one line:
  · a 403 on the record is an ANSWER: not run, and its entry leaves the snapshot;
  · a job whose owner is neither this computer's account nor one it is shared
    with is dropped the same way, BEFORE any read;
  · a job older than the startup sweep's 7-day horizon is not restored.
A read that FAILED — timeout, dropped connection, 5xx — still takes the job, the
old guarantee.

⭐ EVERY TEST SETS A DISCRIMINATION, not just one side: the job that must go sits
BESIDE one that must stay, so a restore that took both (the old code) and one
that dropped both (an over-reach) are each red. The consumers are executed, not
read: the real `_restore_pending_queue_snapshot` against a real file, the real
re-offer on a running loop, the real `_emit_to_firestore` and
`_update_research_doc` through the real heal.

Run:  pytest tests/test_stale_or_foreign_restore_0928.py -v
"""
import asyncio
import base64
import collections
import json
import os
import time
from datetime import datetime, timedelta

import pytest

import research

OWNER = "An1NfSXiroOpNXA4km9sINFerps2"      # the account this computer is paired to
SHARER = "sharer-uid-bob-0000000000000"     # an account it is shared with today
FORMER = "LQwUbFUpmdORiOeonJTJW88cupz2"     # an account it USED to be shared with
STRANGER = "stranger-uid-mallory-000000"    # an account it never ran for
DEVICE = "7cbb146dd2034770810bfc8ab1210bd3"

#: The clear line, word for word — the owner reads this in the serve log.
NOT_OPENABLE = ("not run: this computer can no longer open that research — it "
                "belongs to an account it is not paired to or no longer shared with")


class PermissionDenied(Exception):
    """Stands in for google.api_core.exceptions.PermissionDenied: the class name
    and the message are what the real one carries."""


DENIED = PermissionDenied("403 Missing or insufficient permissions.")
BLIPS = [TimeoutError("DeadlineExceeded"),
         ConnectionError("UNAVAILABLE: failed to connect to all addresses"),
         RuntimeError("503 The service is currently unavailable")]
QUEUED = {"status": "queued"}


# ══ a small Firestore: research records, the device document ═══════════════

class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _Node:
    def __init__(self, fs, parts):
        self._fs, self._parts = fs, parts

    def collection(self, name):
        return _Node(self._fs, self._parts + (name,))

    document = collection

    def get(self, **_options):
        p = self._parts
        self._fs.reads.append(p)
        if len(p) == 2 and p[0] == "devices":
            answer = self._fs.device
        elif len(p) == 4 and p[0] == "users" and p[2] == "researches":
            queue = self._fs.records.get((p[1], p[3]))
            if queue is None:
                answer = None
            else:
                answer = queue.popleft() if len(queue) > 1 else queue[0]
        else:
            answer = None
        if isinstance(answer, BaseException):
            raise answer
        return _Snap(answer)

    def where(self, **_filter):
        """`users/{uid}/researches` asked for its "ongoing" records — boot
        rehydration's one query."""
        return _Ongoing(self._fs, self._parts[1])


class _DocSnap(_Snap):
    def __init__(self, doc_id, data):
        super().__init__(data)
        self.id = doc_id


class _Ongoing:
    def __init__(self, fs, uid):
        self._fs, self._uid = fs, uid

    def get(self):
        return [_DocSnap(rid, answers[0]) for (uid, rid), answers in self._fs.records.items()
                if uid == self._uid and isinstance(answers[0], dict)
                and answers[0].get("status") == "ongoing"]


class _Fs:
    """`users/{uid}/researches/{rid}` answering one read at a time, in order
    (the last answer repeats), and `devices/{id}`."""

    def __init__(self, records=None, device=None):
        self.records = {k: collections.deque(v if isinstance(v, list) else [v])
                        for k, v in (records or {}).items()}
        self.device = device
        self.reads: list = []

    def collection(self, name):
        return _Node(self, (name,))

    def record_reads(self, uid):
        return [p for p in self.reads if p[:2] == ("users", uid)]


class _Q:
    def __init__(self):
        self._queue = collections.deque()

    def put_nowait(self, job):
        self._queue.append(job)


#: A device document read that blips: who the computer is shared with cannot be
#: told, so only the record read can decide.
DEVICE_UNREADABLE = TimeoutError("DeadlineExceeded")
SHARED = {"ownerUid": OWNER, "sharedWith": [SHARER]}


def _job(uid, rid, *, days=0.0, topic="Topic", **extra):
    stamp = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d_%H%M%S")
    job = {"uid": uid, "research_id": rid, "run_id": f"{topic}_{stamp}",
           "topic": "a topic", "email": "someone@example.com", "config": {}}
    job.update(extra)
    return job


def _machine(monkeypatch, tmp_path, fs, *, paired=OWNER):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", fs)
    monkeypatch.setattr(research, "load_paired_uid", lambda: paired)
    monkeypatch.setattr(research, "load_device_id", lambda: DEVICE)
    monkeypatch.setattr(research, "WORKER_ID", 1)
    monkeypatch.setattr(research, "load_worker_count", lambda: 1)
    monkeypatch.setattr(research, "_RESTART_RETRY_DELAYS_S", (0, 0))
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_lock", None)
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_in_progress", False)
    lines: list = []
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO": lines.append((level, str(msg))))
    return lines


def _snapshot(tmp_path, pending, current=None):
    path = tmp_path / "queues" / "_pending_queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts_ms": 1, "current": current, "pending": pending}),
                    encoding="utf-8")
    return path


def _rids(jobs):
    return [(j or {}).get("research_id") for j in jobs]


def _in_file(path):
    if not path.exists():
        return []
    return _rids(json.loads(path.read_text(encoding="utf-8"))["pending"])


def _boot(path, q):
    research._restore_pending_queue_snapshot(path, q, set())
    return _rids(q._queue)


def _said(lines, rid, text):
    return [m for _lvl, m in lines if rid[:8] in m and text in m]


# ══ 1. the rules refuse this computer the record ════════════════════════════

def test_a_job_whose_record_is_refused_is_not_run_and_leaves_the_snapshot(
        monkeypatch, tmp_path):
    """⛔⛔ THE 09-28 JOB. A former sharer's research; who the computer is shared
    with cannot be read this boot, so only the 403 can stop it. Beside it, the
    owner's own job whose reads both blip — held and kept, exactly as before."""
    gone, mine = "agent-82bb870dba1140ed", "chat_1759000000000_1"
    fs = _Fs(records={(FORMER, gone): DENIED, (OWNER, mine): BLIPS[0]},
             device=DEVICE_UNREADABLE)
    lines = _machine(monkeypatch, tmp_path, fs)
    path = _snapshot(tmp_path, [_job(FORMER, gone, topic="St_Bernard"),
                                _job(OWNER, mine)])
    q = _Q()

    assert _boot(path, q) == [], "a job whose record the rules refused was run"
    assert _in_file(path) == [mine], (
        "the refused job stayed in the snapshot to come back at the next boot — "
        "or the owner's held job was thrown out with it")
    assert _rids(research._UNREAD_RESTORES) == [mine], "the refused job is held for a retry"
    assert len(_said(lines, gone, NOT_OPENABLE)) == 1, (
        f"the one clear line was not written exactly once: {lines}")
    assert not _said(lines, gone, "taking the job"), "the refused job was still 'taken'"
    assert not [m for _l, m in lines if "trusting FE-side" in m], "the 403 was trusted"

    # …and it never comes back: a second boot from what is on disk runs nothing
    # of it, and does not even read its record again.
    fs.reads.clear()
    assert _boot(path, _Q()) == []
    assert fs.record_reads(FORMER) == []


@pytest.mark.parametrize("blip", BLIPS, ids=["deadline", "unavailable", "503"])
def test_a_read_that_blips_still_takes_the_job_while_a_refusal_does_not(
        monkeypatch, tmp_path, blip):
    """⭐ THE OLD GUARANTEE, KEPT. A read that FAILED says nothing about the
    record: the pickup rule takes the job and the funnel's own read, answering
    this time, queues it. Beside it a refused job is dropped — so a restore
    that treated every failure as a refusal is red here too."""
    mine, gone = "chat_1759000000000_2", "agent-refused-000000"
    fs = _Fs(records={(OWNER, mine): [blip, QUEUED], (FORMER, gone): DENIED},
             device=DEVICE_UNREADABLE)
    lines = _machine(monkeypatch, tmp_path, fs)
    path = _snapshot(tmp_path, [_job(OWNER, mine), _job(FORMER, gone, topic="Other")])

    assert _boot(path, _Q()) == [mine]
    assert _said(lines, mine, "taking the job"), (
        "precondition: the pickup rule's read of the owner's job really failed")
    assert _in_file(path) == [mine]


def test_a_refusal_on_the_funnels_own_read_is_the_same_answer(monkeypatch, tmp_path):
    """⛔ TWO READS, A MOMENT APART. The pickup rule's read answers "queued" and
    the funnel's, a moment later, is refused — the funnel used to "trust the
    FE-side queue write" and take it. It is dropped and shed like any refusal;
    the owner's job beside it is restored."""
    gone, mine = "chat_1759000000000_a", "chat_1759000000000_b"
    fs = _Fs(records={(FORMER, gone): [QUEUED, DENIED], (OWNER, mine): QUEUED},
             device=DEVICE_UNREADABLE)
    lines = _machine(monkeypatch, tmp_path, fs)
    path = _snapshot(tmp_path, [_job(FORMER, gone, topic="Gone"), _job(OWNER, mine)])

    assert _boot(path, _Q()) == [mine]
    assert _in_file(path) == [mine], "a job refused on the funnel's read was kept"
    assert research._UNREAD_RESTORES == [], "a refused job is held for a retry"
    assert len(_said(lines, gone, NOT_OPENABLE)) == 1, lines


def test_a_held_entry_whose_later_read_is_refused_is_let_go_not_run(monkeypatch, tmp_path):
    """⛔ THE RE-OFFER ASKED THE SAME FUNNEL AND TRUSTED THE SAME 403. An entry
    held on a blip at boot, refused when the retry reads it: not queued, no
    longer held, the clear line written. Beside it an entry that answers
    "queued" on the retry is restored — a retry that refused everything is red."""
    gone, mine = "chat_1759000000000_3", "chat_1759000000000_4"
    fs = _Fs(records={(SHARER, gone): [BLIPS[0], BLIPS[0], DENIED],
                      (OWNER, mine): [BLIPS[0], BLIPS[0], QUEUED]},
             device=SHARED)
    lines = _machine(monkeypatch, tmp_path, fs)
    path = _snapshot(tmp_path, [_job(SHARER, gone), _job(OWNER, mine, topic="Mine")])
    q = _Q()

    async def _go():
        research._restore_pending_queue_snapshot(path, q, set())
        assert _rids(research._UNREAD_RESTORES) == [gone, mine], "precondition: both held"
        await asyncio.gather(*list(research._RESTART_RETRIES))
    asyncio.run(_go())

    assert _rids(q._queue) == [mine], "the retry ran a job the rules refused"
    assert research._UNREAD_RESTORES == [], "a refused entry is still held"
    assert len(_said(lines, gone, NOT_OPENABLE)) == 1, lines


# ══ 2. the job's owner is not one of this computer's accounts ═══════════════

def test_a_strangers_job_is_dropped_before_any_read_and_a_sharers_is_restored(
        monkeypatch, tmp_path):
    """⛔⛔ BEFORE ANY READ. The stranger's record would even read "queued" —
    so only the owner check can stop it — and it is never read at all. The
    sharer's job beside it, and the owner's, are restored."""
    theirs, bobs, mine = "chat_1759000000000_5", "chat_1759000000000_6", "chat_1759000000000_7"
    fs = _Fs(records={(STRANGER, theirs): QUEUED, (SHARER, bobs): QUEUED,
                      (OWNER, mine): QUEUED},
             device=SHARED)
    lines = _machine(monkeypatch, tmp_path, fs)
    path = _snapshot(tmp_path, [_job(STRANGER, theirs, topic="A"),
                                _job(SHARER, bobs, topic="B"),
                                _job(OWNER, mine, topic="C")])

    assert _boot(path, _Q()) == [bobs, mine]
    assert fs.record_reads(STRANGER) == [], "the stranger's record was read before the drop"
    assert theirs not in _in_file(path), "the stranger's job stays to come back"
    assert len(_said(lines, theirs, NOT_OPENABLE)) == 1, lines


@pytest.mark.parametrize("device", [DEVICE_UNREADABLE, None],
                         ids=["device-read-blips", "no-device-document"])
def test_a_sharers_job_is_not_dropped_when_who_shares_cannot_be_read(
        monkeypatch, tmp_path, device):
    """⭐ "DON'T KNOW" IS NEVER "NOBODY". With the device document unreadable or
    missing, the owner check has no evidence — a sharer's job whose record reads
    "queued" is restored, and only the record read can drop one: the former
    sharer's, refused, beside it."""
    bobs, gone = "chat_1759000000000_c", "chat_1759000000000_d"
    fs = _Fs(records={(SHARER, bobs): QUEUED, (FORMER, gone): DENIED}, device=device)
    _machine(monkeypatch, tmp_path, fs)
    path = _snapshot(tmp_path, [_job(SHARER, bobs), _job(FORMER, gone, topic="Gone")])

    assert _boot(path, _Q()) == [bobs]
    assert _in_file(path) == [bobs]


def test_the_run_folders_owner_file_names_a_job_the_entry_does_not(monkeypatch, tmp_path):
    """⭐ THE OTHER PLACE A JOB'S OWNER IS WRITTEN: `queues/<run>/owner.json`.
    An entry that carries no uid of its own was refused by the funnel and KEPT —
    re-offered at every boot for ever. Its folder says whose it is, and that
    account is not this computer's: dropped, and its entry goes."""
    theirs, mine = "chat_1759000000000_8", "chat_1759000000000_9"
    fs = _Fs(records={(OWNER, mine): QUEUED}, device=SHARED)
    lines = _machine(monkeypatch, tmp_path, fs)
    orphan = _job(STRANGER, theirs, topic="Orphan")
    orphan.pop("uid")
    run_dir = tmp_path / "queues" / orphan["run_id"]
    run_dir.mkdir(parents=True)
    (run_dir / "owner.json").write_text(
        json.dumps({"uid": STRANGER, "researchId": theirs}), encoding="utf-8")
    path = _snapshot(tmp_path, [orphan, _job(OWNER, mine, topic="Mine")])

    assert _boot(path, _Q()) == [mine]
    assert _in_file(path) == [mine], "a job whose folder names a stranger was kept"
    assert len(_said(lines, theirs, NOT_OPENABLE)) == 1, lines


def test_an_owner_file_about_another_research_says_nothing_about_this_job(
        monkeypatch, tmp_path):
    """⭐ A FOLDER IS NOT ALWAYS THE JOB'S. Run folders are named for a topic and
    a second, so two members can land on one; an `owner.json` that names a
    DIFFERENT research is not evidence about this job, and the sharer's job is
    restored. Beside it, a folder that does name its own job for a stranger —
    the case the file is read for — still drops that job."""
    bobs, theirs = "chat_1759000000000_e", "chat_1759000000000_f"
    fs = _Fs(records={(SHARER, bobs): QUEUED, (SHARER, theirs): QUEUED}, device=SHARED)
    _machine(monkeypatch, tmp_path, fs)
    shared_folder, strangers_folder = _job(SHARER, bobs, topic="Same"), _job(
        SHARER, theirs, topic="Stranger")
    for job, about in ((shared_folder, "chat_someone_elses_research"),
                       (strangers_folder, theirs)):
        d = tmp_path / "queues" / job["run_id"]
        d.mkdir(parents=True)
        (d / "owner.json").write_text(
            json.dumps({"uid": STRANGER, "researchId": about}), encoding="utf-8")
    path = _snapshot(tmp_path, [shared_folder, strangers_folder])

    assert _boot(path, _Q()) == [bobs]
    assert _in_file(path) == [bobs]


# ══ 3. older than the startup sweep's horizon ═══════════════════════════════

def test_a_job_older_than_the_sweep_horizon_is_not_restored(monkeypatch, tmp_path):
    """⛔⛔ EIGHT DAYS. The owner's own job, whose record still reads "queued" —
    only its age can stop it. Beside it: an hour old and six days old, both
    restored; and an entry an OLDER build wrote — no clock of its own — for a
    run in a folder minted ten days ago that has been worked in today, judged by
    its folder, not its name. (A Resume does not move its folder's time; the job
    it queues carries its own clock — see section 4.)"""
    old, fresh, six, resumed = ("chat_old_0000000001", "chat_fresh_00000001",
                                "chat_six_0000000001", "chat_resumed_000001")
    fs = _Fs(records={(OWNER, old): QUEUED, (OWNER, fresh): QUEUED,
                      (OWNER, six): QUEUED, (OWNER, resumed): {"status": "ongoing"}},
             device=SHARED)
    lines = _machine(monkeypatch, tmp_path, fs)
    folder = tmp_path / "queues" / _job(OWNER, resumed, days=10, topic="Resumed")["run_id"]
    folder.mkdir(parents=True)
    now = time.time()
    os.utime(folder, (now, now))
    path = _snapshot(tmp_path, [
        _job(OWNER, old, days=8, topic="Old"),
        _job(OWNER, fresh, days=1 / 24, topic="Fresh"),
        _job(OWNER, six, days=6, topic="Six"),
        _job(OWNER, resumed, days=10, topic="Resumed", resume_dir=str(folder)),
    ])

    assert _boot(path, _Q()) == [fresh, six, resumed]
    assert old not in _in_file(path), "the stale job stays to come back"
    said = _said(lines, old, "not run: it has waited 8 days, past the 7-day limit")
    assert len(said) == 1, lines
    assert fs.record_reads(OWNER).count(("users", OWNER, "researches", old)) == 0, (
        "the stale job's record was read — the age is decided before any read")


def test_the_horizon_is_the_startup_sweeps_one_number(monkeypatch, tmp_path):
    """⭐ ONE NUMBER. The restore reads `_STALE_RUN_S` — the constant the startup
    sweep uses — so moving it moves the restore: at a two-day horizon a
    three-day-old job goes and a one-day-old one stays."""
    monkeypatch.setattr(research, "_STALE_RUN_S", 2 * 86400)
    three, one = "chat_three_00000001", "chat_one_0000000001"
    fs = _Fs(records={(OWNER, three): QUEUED, (OWNER, one): QUEUED})
    _machine(monkeypatch, tmp_path, fs)
    path = _snapshot(tmp_path, [_job(OWNER, three, days=3, topic="Three"),
                                _job(OWNER, one, days=1, topic="One")])

    assert _boot(path, _Q()) == [one]


# ══ 4. a job queued for an OLD run carries its own clock ══════════════════════

def _old_run_folder(tmp_path, rid, *, days, uid=OWNER, topic="Old_Topic"):
    """A run parked `days` ago, as the startup sweep keeps it for a Resume: its
    owner file, its config, its paused meta — and the folder's time that old."""
    run_id = _job(uid, rid, days=days, topic=topic)["run_id"]
    folder = tmp_path / "queues" / run_id
    folder.mkdir(parents=True)
    (folder / "owner.json").write_text(json.dumps({"uid": uid, "researchId": rid}),
                                       encoding="utf-8")
    (folder / "config.json").write_text("{}", encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({"status": "paused"}), encoding="utf-8")
    then = time.time() - days * 86400
    os.utime(folder, (then, then))
    return run_id, folder


def _days_old(folder):
    return (time.time() - folder.stat().st_mtime) / 86400


def _crash_with(tmp_path, jobs):
    """The worker boundary's own write of what waits in the queue — then the PC
    dies, so this file is all the next boot has."""
    path = tmp_path / "queues" / "_pending_queue.json"
    research._write_pending_queue_snapshot(path, None, jobs)
    return path


def test_a_resume_pressed_today_on_a_ten_day_old_run_is_restored(monkeypatch, tmp_path):
    """⛔⛔ THE REAL RESUME, THEN THE CRASH, THEN THE BOOT (09-29 verify). The
    person presses Resume on a run parked ten days ago. The start listener's
    Resume branch rewrites the folder's files in place, so the folder is still
    ten days old, and so is the run id it names. The job waits behind another
    run and the PC dies; at boot the rehydration query failed, so the disk
    restore is what brings it back — and it dropped it as "waited 10 days",
    leaving the record "ongoing" with nothing running it. Beside it, an entry
    that really was queued eight days ago, by its own clock, still goes."""
    from _queue_listener import Listener
    rid, stale = "chat_1759000000000_r", "chat_1759000000000_s"
    run_id, folder = _old_run_folder(tmp_path, rid, days=10)
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, research_docs={
        (OWNER, rid): {"status": "paused_backend_restart", "topic": "t"}})
    lis.feed(action="resume", uid=OWNER, submittedBy=OWNER, researchId=rid,
             backendRunId=run_id, email="", config={"x": 1})
    [resumed] = lis.enqueued
    assert _days_old(folder) > 9.9, "precondition: the Resume left the folder's time alone"

    fs = _Fs(records={(OWNER, rid): {"status": "ongoing"}, (OWNER, stale): QUEUED},
             device=SHARED)
    lines = _machine(monkeypatch, tmp_path, fs)
    eight_days_ago_ms = int((time.time() - 8 * 86400) * 1000)
    path = _crash_with(tmp_path, [resumed, _job(OWNER, stale, days=8, topic="Stale",
                                                queued_at_ms=eight_days_ago_ms)])

    assert _boot(path, _Q()) == [rid], (
        f"a Resume pressed minutes ago was dropped as stale: {lines}")
    assert len(_said(lines, stale, "not run: it has waited 8 days")) == 1, lines


def test_a_supervised_auto_resume_of_an_old_run_keeps_its_own_clock(monkeypatch, tmp_path):
    """⛔ THE OTHER PATH THAT QUEUES AN OLD RUN. Boot rehydration auto-resumes a
    supervised run whose run id and folder are ten days old — the REAL scan and
    the real funnel. The job waits, the PC dies again, and at the next boot the
    rehydration query fails: the disk restore brings it back instead of dropping
    it as stale."""
    rid = "chat_1759000000000_u"
    run_id, folder = _old_run_folder(tmp_path, rid, days=10)
    fs = _Fs(records={(OWNER, rid): {"status": "ongoing", "backendRunId": run_id,
                                     "deviceId": DEVICE}},
             device={**SHARED, "supervised": True})
    lines = _machine(monkeypatch, tmp_path, fs)
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda *_a: [])
    monkeypatch.setattr(research, "load_checkpoint", lambda _qd: {"topic": "t"})
    q = _Q()
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", q)

    assert asyncio.run(research._rehydrate_ongoing_for_tree(OWNER, OWNER, set())) == (1, 0), (
        f"precondition: the scan auto-resumed the run: {lines}")
    assert _days_old(folder) > 9.9, "precondition: the auto-resume left the folder's time alone"
    path = _crash_with(tmp_path, list(q._queue))

    assert _boot(path, _Q()) == [rid], (
        f"an auto-resume queued at the last boot was dropped as stale: {lines}")


# ══ 5. the heal's structural line ═══════════════════════════════════════════

def _token(claims):
    def _b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.sig"


class _Creds:
    def __init__(self, claims):
        self.token = _token(claims)

    def refresh(self, _request):
        pass


class _DenyingDb:
    """Every write refused; the credential carries this computer's claims."""

    def __init__(self, claims):
        self._credentials = _Creds(claims)
        self.writes = 0

    def collection(self, _name):
        return self

    document = collection

    def _deny(self, *_a, **_k):
        self.writes += 1
        raise PermissionDenied("403 Missing or insufficient permissions.")

    add = update = set = get = _deny


def _heal_machine(monkeypatch, *, token_device=DEVICE, config_device=DEVICE):
    db = _DenyingDb({"deviceId": token_device, "ownerUid": OWNER})
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setattr(research, "_GRPC_HEAL_COOLDOWN_S", -1.0)
    monkeypatch.setattr(research, "_grpc_heal_last_ts", 0.0)
    monkeypatch.setattr(research, "_grpc_heal_consec_fail", 0)
    monkeypatch.setattr(research, "_grpc_heal_structural", False)
    monkeypatch.setattr(research, "_config_device_id_uncached", lambda: config_device)
    monkeypatch.setattr(research, "load_paired_uid", lambda: OWNER)
    lines: list = []
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO": lines.append((level, str(msg))))
    return db, lines


def _structural(lines):
    return [m for lvl, m in lines if lvl == "ERROR" and "STRUCTURAL" in m]


def _deny_three_times(write):
    for _ in range(research._GRPC_HEAL_STRUCTURAL_AFTER):
        write()


@pytest.mark.parametrize("uid, another_account", [(FORMER, True), (OWNER, False)],
                         ids=["another-accounts-research", "own-research"])
def test_the_structural_line_names_whose_research_it_was(
        monkeypatch, uid, another_account):
    """⛔⛔ "RE-PAIR REQUIRED" ONLY FOR THIS COMPUTER'S OWN TREE. A write into
    another account's research that the rules keep refusing says that the job
    belongs to another account; the owner's own research still says re-pair."""
    db, lines = _heal_machine(monkeypatch)

    def _write():
        with pytest.raises(PermissionDenied):
            research._grpc_write_with_heal(lambda: db.add({}), what="emit_event", uid=uid)
    _deny_three_times(_write)

    [line] = _structural(lines)
    if another_account:
        assert "the job belongs to another account" in line, line
        assert FORMER[:8] in line and OWNER[:8] in line, line
        assert "re-pair required" not in line, line
    else:
        assert "re-pair required" in line, line
        assert "another account" not in line, line


def test_a_device_id_mismatch_still_says_re_pair_whoever_the_research_belongs_to(
        monkeypatch):
    """⭐ THE ONE EXCEPTION. The token and the config disagree about this
    computer's own device id — that is this computer's pairing, and re-pairing
    is the fix whoever's research the write was for."""
    db, lines = _heal_machine(monkeypatch, token_device="old-device-id")

    def _write():
        with pytest.raises(PermissionDenied):
            research._grpc_write_with_heal(lambda: db.add({}), what="emit_event", uid=FORMER)
    _deny_three_times(_write)

    [line] = _structural(lines)
    assert "re-pair required" in line and "another account" not in line, line


RUN_RID = "agent-82bb870dba1140ed"

#: The research writers a run makes, each driven through its real code. The
#: first is the one the 09-28 log latched on — `emit_event`'s write.
WRITERS = {
    "emit_event": lambda: research._emit_to_firestore({"type": "phase_start"}),
    "update-record": lambda: research._update_research_doc(
        FORMER, RUN_RID, {"status": "ongoing"}),
    "set-record": lambda: research._set_research_doc(
        FORMER, RUN_RID, {"backendRunId": "Topic_20260920_181415"}),
    "link": lambda: research.update_link_in_firestore("brief", "https://example.com/b"),
    "document": lambda: research.save_document_to_firestore("brief", "# Brief\n\nbody"),
    "phase-status": lambda: research._do_phase_terminal_status_write(1, "complete"),
    "cloud-kick-refusal": lambda: research._record_cloud_kick_refusal(
        FORMER, RUN_RID, "the cloud said no"),
}


@pytest.mark.parametrize("writer", list(WRITERS))
def test_every_research_writer_names_the_research_owners_account(monkeypatch, writer):
    """⛔⛔ THE CONSUMERS. The heal can only say whose research it was if the
    writer hands it the uid of the tree it writes into. With the job's owner
    armed as the run's uid (and passed where the writer takes it), the
    structural line must name another account — never re-pairing."""
    _db, lines = _heal_machine(monkeypatch)
    monkeypatch.setattr(research, "_fb_uid", FORMER)
    monkeypatch.setattr(research, "_fb_research_id", RUN_RID)
    monkeypatch.setattr(research, "_fb_seq", 0)
    monkeypatch.setattr(research, "_be_payload", lambda p: dict(p))
    _deny_three_times(WRITERS[writer])

    [line] = _structural(lines)
    assert "the job belongs to another account" in line, line
    assert "re-pair required" not in line, line
