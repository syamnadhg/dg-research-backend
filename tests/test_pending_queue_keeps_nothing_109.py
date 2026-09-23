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
     the only thing in it.

⭐ EVERY PIN RUNS THE REAL FUNCTION AGAINST A REAL FILE and reads the bytes back.

Run:  pytest tests/test_pending_queue_keeps_nothing_109.py -v
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

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
