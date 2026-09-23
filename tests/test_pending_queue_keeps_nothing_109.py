"""The queue snapshot at the root of `queues/`, for a run that keeps nothing.

Wave 10.9, #536. `queues/_pending_queue.json` is the Phoenix restore file: the
worker snapshots it at every boundary so a crash can put the queue back. It held
the CLAIMED job verbatim — the topic, the person's email address and their whole
brief — and it sits at the ROOT of `queues/`, where:

  · `_purge_incognito_run_dirs` never reaches (it removes `queues/<run>/` and
    the run's log folders, nothing above them);
  · `clear_local_storage`, the one control a person has to wipe this machine,
    deliberately keeps the top-level files;
  · and on a crash nothing rewrites it — the next boot ends the run, the enqueue
    funnel refuses a stopped run for ever, and the entry stays until some
    unrelated later job happens to be claimed.

So the content of a private research outlived the run on a computer its owner
may not be, in the one file none of the wave's other repairs looked at — the same
class already closed in the run id, the log lines and the log folder name.

WHAT THESE PIN

  1. What may be WRITTEN: the running job goes to disk as ids only when it keeps
     nothing, whole when it does not, and a job still waiting its turn is never
     redacted (the claim has already deleted its queue document — this snapshot
     is the only copy of the work left).
  2. What BOOT does with it: the entry is not re-offered to the enqueue funnel,
     and the file is left holding nothing of that run — gone entirely when it was
     the only thing in it — while every ordinary job boot could not restore THIS
     time stays, whole, for the next attempt.
  3. What a CANCEL does with it (a leave sends the same cancel): a waiting run
     that keeps nothing leaves the file at the press, not when the run in front
     of it happens to end.

⭐ EVERY PIN RUNS THE REAL FUNCTION AGAINST A REAL FILE and reads the bytes back.

Run:  pytest tests/test_pending_queue_keeps_nothing_109.py -v
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from _queue_listener import Listener  # noqa: E402

INCOG = "incog_1758400000000_4"
CHAT = "chat_1758400000000_4"
TOPIC = "whether my results came back positive"
EMAIL = "someone@example.com"
BRIEF = "I am asking for a friend and I do not want this on the machine"


def _job(rid, run_id="incognito_1758400000000_4_20260922_101500"):
    """The dict the start listener builds and the worker carries — the only
    thing that survives the hop from the listener thread to the pipeline."""
    return {
        "topic": TOPIC,
        "email": EMAIL,
        "config": {"mode": "deep"},
        "run_id": run_id,
        "uid": "uid-sharer",
        "research_id": rid,
        "brief_text": BRIEF,
        "user_sources": [],
        "user_links": [],
        "submitted_by": "uid-sharer",
    }


class _Queue:
    """What `_job_queue` looks like to both functions under test: `put_nowait`
    to accept a job, `_queue` to read what is waiting."""

    def __init__(self, jobs=()):
        self._queue = list(jobs)

    def put_nowait(self, job):
        self._queue.append(job)


def _written(path):
    return path.read_text(encoding="utf-8")


# ══ 1. what may be written ═══════════════════════════════════════════════

def test_the_claimed_job_of_a_run_that_keeps_nothing_is_written_as_ids(tmp_path):
    """⛔⛔ THE DEFECT, read off the disk. The claim wrote the job verbatim, so
    the topic, the address the report is going to and the entire brief sat in
    plaintext at the root of `queues/` for the whole run — and for ever after a
    crash. What boot needs of it is the pair of ids plus the run name, and the
    mint already keeps the topic out of that."""
    path = tmp_path / "_pending_queue.json"
    research._write_pending_queue_snapshot(path, _job(INCOG), [])

    raw = _written(path)
    assert TOPIC not in raw, "the private topic was written to the machine's disk"
    assert EMAIL not in raw, "the person's email address was written to disk"
    assert BRIEF not in raw, "the person's whole brief was written to disk"

    current = json.loads(raw)["current"]
    assert current["research_id"] == INCOG
    assert current["uid"] == "uid-sharer", "boot cannot read the record without it"
    assert current["run_id"].startswith("incognito_"), (
        "the `.stop` sentinel is found by this name")
    assert set(current) == {"uid", "research_id", "run_id"}, (
        "something other than an id reached the file")


def test_an_ordinary_claimed_job_is_still_written_whole(tmp_path):
    """⭐⭐ ACCEPT POLARITY, and the whole risk of this change: an ordinary run
    IS restored from this file after a crash, and it cannot be restored without
    the work it describes. A blanket redaction would look like a privacy fix and
    silently lose every interrupted run on the machine."""
    path = tmp_path / "_pending_queue.json"
    research._write_pending_queue_snapshot(path, _job(CHAT, run_id="cats_20260922"), [])

    current = json.loads(_written(path))["current"]
    assert current["topic"] == TOPIC
    assert current["email"] == EMAIL
    assert current["brief_text"] == BRIEF


def test_a_job_still_waiting_its_turn_is_not_redacted(tmp_path):
    """⛔ THE CLAIM DELETES THE QUEUE DOCUMENT IN FIRESTORE, so for a job that is
    waiting behind another run this file is the only description of the work that
    exists anywhere. Redacting it would lose a run somebody paid for and is
    watching — its content lives exactly as long as the wait, and the claim
    replaces it with the ids above."""
    path = tmp_path / "_pending_queue.json"
    research._write_pending_queue_snapshot(path, None, [_job(INCOG)])

    pending = json.loads(_written(path))["pending"]
    assert pending[0]["topic"] == TOPIC, (
        "a queued run lost the work it was waiting to do")


def test_the_snapshot_is_replaced_atomically(tmp_path):
    """⭐ The tmp sibling is not left behind, and the name the boot path reads is
    the one that ends up holding the payload."""
    path = tmp_path / "_pending_queue.json"
    research._write_pending_queue_snapshot(path, _job(CHAT), [])
    research._write_pending_queue_snapshot(path, None, [])

    assert not (tmp_path / "_pending_queue.json.tmp").exists()
    snap = json.loads(_written(path))
    assert snap["current"] is None and snap["pending"] == []
    assert isinstance(snap["ts_ms"], int)


# ══ 2. what boot does with it ════════════════════════════════════════════

def _snapshot(path, current=None, pending=()):
    path.write_text(json.dumps({"ts_ms": 1, "current": current,
                                "pending": list(pending)}, indent=2),
                    encoding="utf-8")
    return path


def _enqueue_recorder(monkeypatch, *, accept=True, running=None):
    """The enqueue funnel, recorded — plus the worker's live slot, set
    explicitly because the rewrite writes around whatever is running now."""
    offered = []

    def _fake(job_queue, job, source, allowed_statuses=None):
        offered.append(job)
        if accept:
            job_queue.put_nowait(job)
        return accept

    monkeypatch.setattr(research, "_safe_enqueue", _fake)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", running)
    return offered


def test_boot_does_not_re_offer_a_run_that_keeps_nothing(tmp_path, monkeypatch):
    """⛔⛔ THE CONSUMER. Boot recovery has just ended this run — there is no chat
    to reopen and no Resume anybody can press — so re-offering it could only
    start a research nobody is waiting for, on the browser profiles of a machine
    whose owner was told a run happened and nothing else."""
    path = _snapshot(tmp_path / "_pending_queue.json", current=_job(INCOG))
    offered = _enqueue_recorder(monkeypatch)

    restored, skipped = research._restore_pending_queue_snapshot(
        path, _Queue(), set())

    assert offered == [], "a run that keeps nothing was re-offered to the queue"
    assert (restored, skipped) == (0, 0)


def test_boot_leaves_nothing_of_it_on_the_disk(tmp_path, monkeypatch):
    """⛔⛔ THE HALF THAT MADE A CRASH PERMANENT. The boot path read this file and
    never wrote it, so the entry stayed — and because the run is ended and the
    enqueue funnel refuses a stopped run, nothing was ever going to claim it
    again. The last thing on the machine that knows a private run happened here
    goes with the run."""
    path = _snapshot(tmp_path / "_pending_queue.json", current=_job(INCOG))
    _enqueue_recorder(monkeypatch)

    research._restore_pending_queue_snapshot(path, _Queue(), set())

    assert not path.exists(), (
        "the snapshot of a run that keeps nothing outlived the boot that ended it")


def test_boot_keeps_the_other_jobs_it_restored(tmp_path, monkeypatch):
    """⭐⭐ ACCEPT POLARITY on the rewrite: dropping the entry must not drop
    everybody else's work with it. The ordinary job in the same snapshot is
    restored, and the file it is rewritten into still describes it."""
    path = _snapshot(tmp_path / "_pending_queue.json",
                     current=_job(INCOG), pending=[_job(CHAT, run_id="cats_1")])
    offered = _enqueue_recorder(monkeypatch)
    queue = _Queue()

    restored, _skipped = research._restore_pending_queue_snapshot(
        path, queue, set())

    assert [j["research_id"] for j in offered] == [CHAT]
    assert restored == 1
    raw = _written(path)
    assert json.loads(raw)["pending"][0]["research_id"] == CHAT
    assert INCOG not in raw, "the ended run was still named in the rewritten file"


def test_a_queued_incognito_job_boot_refuses_is_not_left_behind(tmp_path, monkeypatch):
    """⛔ THE SAME TAIL, one entry along. A job that was still waiting when the
    machine died is restorable — but when the funnel refuses it (its record is
    gone, or the fuse burned out) nothing else would ever rewrite the file, and
    its topic, address and brief would stay there exactly as before."""
    path = _snapshot(tmp_path / "_pending_queue.json", pending=[_job(INCOG)])
    offered = _enqueue_recorder(monkeypatch, accept=False)

    restored, skipped = research._restore_pending_queue_snapshot(
        path, _Queue(), set())

    assert [j["research_id"] for j in offered] == [INCOG], (
        "a queued run was not even offered — it was never started, so it is "
        "restorable")
    assert (restored, skipped) == (0, 1)
    assert not path.exists(), "the refused job's brief stayed on the disk"


def test_an_ordinary_boot_rewrites_nothing(tmp_path, monkeypatch):
    """⭐ THE FILE IS LEFT EXACTLY AS IT WAS when no run that keeps nothing was
    in it — the next worker boundary is what tidies an ordinary snapshot, and
    that has not changed."""
    path = _snapshot(tmp_path / "_pending_queue.json",
                     current=_job(CHAT, run_id="cats_1"))
    before = _written(path)
    _enqueue_recorder(monkeypatch)

    restored, _skipped = research._restore_pending_queue_snapshot(
        path, _Queue(), set())

    assert restored == 1
    assert _written(path) == before


def test_boot_still_skips_what_firestore_already_recovered(tmp_path, monkeypatch):
    """⭐ The dedupe the block was built around: a run rehydration already
    touched is not enqueued a second time from the disk."""
    path = _snapshot(tmp_path / "_pending_queue.json",
                     current=_job(CHAT, run_id="cats_1"),
                     pending=[_job("chat_1758400000000_9", run_id="dogs_1")])
    offered = _enqueue_recorder(monkeypatch)

    research._restore_pending_queue_snapshot(
        path, _Queue(), {CHAT, "chat_1758400000000_9"})

    assert offered == [], "a run Firestore had already recovered ran twice"


def test_a_job_claimed_while_boot_was_still_running_is_not_erased(
        tmp_path, monkeypatch):
    """⛔⛔ THE REWRITE MUST NOT OUTRUN THE WORKER. The worker task is created
    before boot reaches this file and boot awaits Firestore on the way, so a run
    rehydration auto-resumed can already be executing by the time the snapshot
    is tidied. Writing `current: null` on top of it would erase the only crash
    record of a run that had just started — one run's leftovers taking the next
    run's safety net with it."""
    path = _snapshot(tmp_path / "_pending_queue.json", current=_job(INCOG))
    claimed = _job(CHAT, run_id="cats_1")
    _enqueue_recorder(monkeypatch, running=claimed)

    research._restore_pending_queue_snapshot(path, _Queue(), set())

    current = json.loads(_written(path))["current"]
    assert current["research_id"] == CHAT, "the running run lost its snapshot"
    assert current["topic"] == TOPIC, "the running run lost the work it is doing"


def test_a_missing_snapshot_is_not_an_error(tmp_path, monkeypatch):
    _enqueue_recorder(monkeypatch)
    assert research._restore_pending_queue_snapshot(
        tmp_path / "_pending_queue.json", _Queue(), set()) == (0, 0)


@pytest.mark.parametrize("slot", ["current", "pending"])
def test_boot_keeps_an_ordinary_job_it_could_not_check_this_time(
        tmp_path, monkeypatch, slot):
    """⛔⛔ AN ORDINARY-RUN REGRESSION THE LAST REPAIR MADE. The rewrite that
    takes a run that keeps nothing off the disk was built from the live queue —
    so an ordinary job the funnel refused on THIS boot went with it. The funnel
    refuses on a transient Firestore error too (a DeadlineExceeded, an
    UNAVAILABLE), and the claim had already deleted that job's queue document:
    this file was its only description. Its record stayed "queued" and nothing
    would ever start it — somebody's paid research, silently gone, because a
    stranger's private run happened to share the snapshot.

    ⭐ Before that repair boot never wrote this file, so the job waited for the
    next boot or the next worker boundary. It still does."""
    ordinary = _job(CHAT, run_id="cats_1")
    path = _snapshot(tmp_path / "_pending_queue.json",
                     current=ordinary if slot == "current" else _job(INCOG),
                     pending=[_job(INCOG)] if slot == "current" else [ordinary])
    offered = _enqueue_recorder(monkeypatch, accept=False)

    research._restore_pending_queue_snapshot(path, _Queue(), set())

    assert CHAT in [j["research_id"] for j in offered], "it was never even offered"
    raw = _written(path)
    kept = json.loads(raw)["pending"]
    assert [j["research_id"] for j in kept] == [CHAT], (
        "an ordinary job the funnel could not check this time was dropped")
    assert kept[0]["topic"] == TOPIC and kept[0]["email"] == EMAIL, (
        "the job was kept without the work it describes")
    assert INCOG not in raw, "the run that keeps nothing came back with it"


class _Statuses:
    """`users/{uid}/researches/{rid}` for the REAL enqueue funnel: each record
    answers with the status named for it."""

    def __init__(self, by_rid):
        self._by_rid = by_rid
        self._rid = None

    def collection(self, _name):
        return self

    def document(self, name):
        self._rid = name
        return self

    def get(self):
        status = self._by_rid.get(self._rid)
        return type("Snap", (), {"exists": status is not None,
                                 "to_dict": lambda _s: {"status": status}})()


def test_boot_does_not_relaunch_a_run_parked_for_somebodys_resume(
        tmp_path, monkeypatch):
    """⛔⛔ #728, AND UNTIL NOW NOTHING RAN IT THROUGH THE CALLER. The boot
    restore hands the funnel a TIGHTER whitelist than its default — no
    `paused_backend_restart` — because worker 1's rehydration has just parked
    that run for its person's Resume, and relaunching it from a sibling's stale
    snapshot is the double-handling #728 closed. The tests above fake the funnel
    and discard the argument, so deleting it left them green.

    ⭐ THE REAL FUNNEL, against records that answer. Both polarities: the run
    that is genuinely ongoing still comes back."""
    parked = {**_job("chat_1758400000000_5", run_id="parked_1"),
              "resume_dir": str(tmp_path / "parked_1")}
    ongoing = {**_job("chat_1758400000000_6", run_id="ongoing_1"),
               "resume_dir": str(tmp_path / "ongoing_1")}
    for job in (parked, ongoing):
        os.makedirs(job["resume_dir"])
    path = _snapshot(tmp_path / "_pending_queue.json", pending=[parked, ongoing])
    monkeypatch.setattr(research, "_firebase_db", _Statuses({
        parked["research_id"]: "paused_backend_restart",
        ongoing["research_id"]: "ongoing"}))
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    queue = _Queue()

    restored, skipped = research._restore_pending_queue_snapshot(path, queue, set())

    assert [j["research_id"] for j in queue._queue] == [ongoing["research_id"]], (
        "a run parked for its person's Resume was relaunched from the disk")
    assert (restored, skipped) == (1, 1)


# ══ 3. a cancel takes a waiting run that keeps nothing off the disk ═══════

RUNNING_TOPIC = "the history of the printing press"


def _running():
    """Somebody else's ordinary run, on the worker, with its crash record."""
    return {**_job(CHAT, run_id="printing_20260922"), "uid": "uid-owner",
            "submitted_by": "uid-owner", "topic": RUNNING_TOPIC,
            "email": "owner@example.com", "brief_text": ""}


class _Lock:
    """The hard-reset lock, recording that the shed waited its turn."""

    def __init__(self):
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *exc):
        return False


def _cancel_while_it_waits(monkeypatch, tmp_path, waiting, *, resetting=False):
    """The REAL start listener, holding `waiting` in its deque behind a running
    job, with the snapshot the worker wrote when it claimed that job — then the
    person's cancel (which is also what leaving their chat sends)."""
    lis = Listener(monkeypatch, tmp_path, owner="uid-owner",
                   current_job=_running(), deque_jobs=[waiting])
    lock = _Lock()
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_lock", lock)
    monkeypatch.setitem(research._QUEUE_STATE, "_hard_reset_in_progress", resetting)
    path = tmp_path / "queues" / "_pending_queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    research._write_pending_queue_snapshot(path, _running(), [waiting])
    before = _written(path)
    lis.feed(action="cancel", researchId=waiting["research_id"],
             uid="uid-sharer", submittedBy="uid-sharer")
    assert not lis.jobs._queue, "the cancel did not reach the waiting job"
    return path, before, lock


def test_a_cancelled_run_that_keeps_nothing_leaves_the_snapshot_at_the_press(
        tmp_path, monkeypatch):
    """⛔⛔ THE PERSON WAS TOLD NOTHING IS KEPT, AND THE FILE KEPT IT. A job
    waiting behind somebody else's run is written whole — it has to be, the
    claim deleted its queue document — and a Cancel or a leave took it out of
    the queue without touching the file. Its topic, address and brief then sat
    at the root of `queues/` until the running job ended, hours later."""
    path, _before, lock = _cancel_while_it_waits(monkeypatch, tmp_path, _job(INCOG))

    raw = _written(path)
    assert TOPIC not in raw, "the cancelled run's topic outlived the press"
    assert EMAIL not in raw, "the cancelled run's address outlived the press"
    assert BRIEF not in raw, "the cancelled run's brief outlived the press"
    snap = json.loads(raw)
    # ⭐ AND THE RUNNING JOB KEEPS ITS CRASH RECORD — tidying one person's
    # leftovers must not take another person's safety net with it.
    assert snap["current"]["research_id"] == CHAT
    assert snap["current"]["topic"] == RUNNING_TOPIC
    assert lock.entered == 1, (
        "the rewrite did not wait for Reset Backend's own write of this file")


def test_an_ordinary_cancel_leaves_the_snapshot_as_it_was(tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY. An ordinary cancelled job left in the file is harmless
    — boot re-offers it and the funnel refuses a stopped run — and the next
    worker boundary tidies it, exactly as before this repair."""
    ordinary = {**_job("chat_1758400000000_8", run_id="cats_2"),
                "uid": "uid-sharer"}
    path, before, _lock = _cancel_while_it_waits(monkeypatch, tmp_path, ordinary)

    assert _written(path) == before


def test_a_cancel_during_reset_backend_leaves_the_resets_snapshot_alone(
        tmp_path, monkeypatch):
    """⛔ THE SAME RULE THE WORKER'S OWN BOUNDARY FOLLOWS. Reset Backend writes
    this file itself, under the lock, and then drains the queue; a rewrite from
    memory landing inside that would put back what the reset is clearing."""
    path, before, _lock = _cancel_while_it_waits(
        monkeypatch, tmp_path, _job(INCOG), resetting=True)

    assert _written(path) == before
