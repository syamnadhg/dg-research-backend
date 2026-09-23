"""A run that keeps nothing takes its folders off this computer when it ends.

⛔⛔ THE SWEEP WAS NEVER GOING TO BE THE ANSWER. `_orphan_sweep_loop` removes a
queue directory only once its research is GONE from Firestore, and since
2026-09-20 it memoises a research it has confirmed for a full hour — so a run
folder holding the documents, the delivery record and the topic could sit on
the research computer for about sixty-five minutes after the run ended. On a
shared computer that is somebody else's subject on the owner's disk, long after
the app has said nothing is kept.

⛔ BUT ONLY WHEN NOBODY HERE IS COMING BACK. A crash card offers Retry and a
login interrupt offers Resume, and both resume from the checkpoint inside that
very directory — deleting it would turn a recoverable paid run into a lost one.
Those are left to the sweep, which for an incognito folder now re-checks every
tick instead of hourly.
"""
import asyncio
import json
import os
import types

import pytest

import research

INCOG = "incog_1758400000000_2"
CHAT = "chat_1758400000000_2"


@pytest.fixture()
def disk(tmp_path, monkeypatch):
    """A queue directory and a matching run-log folder, as a finished run
    leaves them."""
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    runs = tmp_path / "logs" / "runs"
    runs.mkdir(parents=True)
    monkeypatch.setattr(research, "_runs_log_root", lambda: runs)
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [])
    monkeypatch.setattr(research, "_folder_is_live", lambda f: False)

    def make(rid, status="completed"):
        queue = tmp_path / "queues" / f"run_{rid}"
        (queue / "documents").mkdir(parents=True)
        (queue / "documents" / "chatgpt.md").write_text("the whole report", encoding="utf-8")
        (queue / "delivery.json").write_text(
            json.dumps({"topic": "a private subject", "status": status}), encoding="utf-8")
        folder = runs / f"{rid}_20260922T101500"
        folder.mkdir()
        (folder / "meta.json").write_text(json.dumps({"researchId": rid}), encoding="utf-8")
        (folder / "run.log").write_text("lines", encoding="utf-8")
        return queue, folder
    return make


# ══ 1. what it removes, and what it refuses to ════════════════════════════

def test_a_finished_run_that_keeps_nothing_leaves_no_folder(disk):
    queue, folder = disk(INCOG)
    assert research._purge_incognito_run_dirs(queue, INCOG) is True
    assert not queue.exists(), "the queue directory survived the run"
    assert not folder.exists(), "the run's log folder survived the run"


def test_an_ordinary_finished_run_keeps_everything_it_always_did(disk):
    """⭐ ACCEPT POLARITY, and it is the whole risk of this commit: local
    retention is sixty runs and thirty days, and the support bundle is built
    from exactly these folders."""
    queue, folder = disk(CHAT)
    assert research._purge_incognito_run_dirs(queue, CHAT) is False
    assert queue.exists() and folder.exists()


def test_a_stopped_run_is_over_too(disk):
    queue, _folder = disk(INCOG, status="stopped")
    assert research._purge_incognito_run_dirs(queue, INCOG) is True
    assert not queue.exists()


@pytest.mark.parametrize("status", ["ongoing", "paused"])
def test_a_run_somebody_can_still_resume_keeps_its_checkpoint(disk, status):
    """⛔⛔ THE RETRY AND THE RESUME BOTH READ THIS DIRECTORY. A crash card and a
    login interrupt each offer to continue from the checkpoint inside it, and
    purging it would turn a recoverable paid run into a lost one."""
    queue, folder = disk(INCOG, status=status)
    assert research._purge_incognito_run_dirs(queue, INCOG) is False
    assert (queue / "documents" / "chatgpt.md").exists()
    assert folder.exists()


def test_a_run_with_no_delivery_record_is_left_alone(disk):
    """⛔ UNREADABLE MEANS LEAVE IT — the orphan sweep's own defensive default.
    A missing or broken delivery.json is the shape of a run that died mid
    construction, and that run may still be recoverable."""
    queue, _folder = disk(INCOG)
    (queue / "delivery.json").unlink()
    assert research._purge_incognito_run_dirs(queue, INCOG) is False
    assert queue.exists()


def test_another_researchs_log_folder_is_never_taken(disk):
    """⛔ MATCHED ON meta.json's researchId, never on the folder name. The name
    is sanitised, so a prefix match would either miss the folder or take
    somebody else's diagnostics."""
    queue, folder = disk(INCOG)
    _other_queue, other = disk(CHAT)
    assert research._purge_incognito_run_dirs(queue, INCOG) is True
    assert not folder.exists()
    assert other.exists(), "another research's diagnostics were deleted"


def test_a_directory_that_cannot_be_removed_does_not_end_the_run(disk, monkeypatch):
    """This runs on the way out of a pipeline. A cleanup that can raise is a
    cleanup that can end a run, which is worse than a leftover directory."""
    queue, _folder = disk(INCOG)
    import shutil
    monkeypatch.setattr(shutil, "rmtree",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("busy")))
    assert research._purge_incognito_run_dirs(queue, INCOG) is False


def test_a_run_with_no_log_folder_still_loses_its_queue_directory(disk):
    """The two halves are independent: a run whose diagnostics were already
    pruned by local retention still has its queue directory taken."""
    queue, folder = disk(INCOG)
    import shutil
    shutil.rmtree(folder)
    assert research._purge_incognito_run_dirs(queue, INCOG) is True
    assert not queue.exists()


# ══ 2. the statuses that mean "nobody here is coming back" ════════════════

def test_only_the_two_terminal_statuses_count_as_over():
    """⛔ `ongoing` is a run still executing and `paused` is one waiting for a
    person. Widening this set is how a live run's checkpoint gets deleted."""
    assert research._RUN_DELIVERY_OVER == {"completed", "stopped"}


# ══ 3. the consumer: the wrapper every pipeline attempt goes through ══════

def _wrapper_world(tmp_path, monkeypatch, rid, *, raises=False, status="completed"):
    """`run_pipeline_captured` with the pipeline body replaced, so the purge is
    reached exactly as it is in production — through the wrapper's finally,
    after the log capture has closed."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    queue = tmp_path / "queues" / "incognito_1758400000000_2_20260922_101500"
    queue.mkdir(parents=True)
    (queue / "delivery.json").write_text(
        json.dumps({"topic": "a private subject", "status": status}), encoding="utf-8")

    async def _body(*a, **k):
        if raises:
            raise RuntimeError("the pipeline blew up")
        return "done"
    monkeypatch.setattr(research, "run_pipeline", _body)
    monkeypatch.setattr(research, "_RunLogCapture", lambda **kw: _Noop())
    monkeypatch.setattr(research, "_run_log_folders_for_research", lambda r: [])
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    return queue


class _Noop:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


def test_the_wrapper_purges_a_finished_run_that_keeps_nothing(tmp_path, monkeypatch):
    """⛔⛔ THE CONSUMER. The helper is perfect and unreachable unless something
    calls it on the way out of every attempt."""
    import asyncio
    queue = _wrapper_world(tmp_path, monkeypatch, INCOG)
    out = asyncio.run(research.run_pipeline_captured(
        "a topic", research_id=INCOG, run_id=queue.name))
    assert out == "done", "the wrapper must still answer its caller"
    assert not queue.exists()


def test_the_wrapper_purges_even_when_the_pipeline_raised(tmp_path, monkeypatch):
    """⛔ A run that died is the one most likely to be left behind, and the
    `finally` is why this reaches it at all."""
    import asyncio
    queue = _wrapper_world(tmp_path, monkeypatch, INCOG, raises=True, status="stopped")
    with pytest.raises(RuntimeError):
        asyncio.run(research.run_pipeline_captured(
            "a topic", research_id=INCOG, run_id=queue.name))
    assert not queue.exists()


def test_the_wrapper_leaves_an_ordinary_runs_folder_alone(tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY on the consumer: local retention and the support
    bundle are both built from these folders."""
    import asyncio
    queue = _wrapper_world(tmp_path, monkeypatch, CHAT)
    asyncio.run(research.run_pipeline_captured(
        "a topic", research_id=CHAT, run_id=queue.name))
    assert queue.exists()


# ── the directory a call will work in ─────────────────────────────────────

def test_a_resume_names_its_directory_by_its_last_segment(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    (tmp_path / "queues" / "r_1").mkdir(parents=True)
    got = research._run_pipeline_queue_dir(
        (), {"topic": "t", "resume_dir": str(tmp_path / "queues" / "r_1")})
    assert got == tmp_path / "queues" / "r_1"


def test_a_claim_that_would_land_outside_queues_resolves_to_nothing(tmp_path,
                                                                    monkeypatch):
    """⛔ A RUN ID IS A NAME, NOT A PATH — this file's own rule, and the reason
    a resume once merged a sender's config into somebody else's run folder."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    assert research._run_pipeline_queue_dir((), {"topic": "t", "run_id": "../etc"}) is None
    assert research._run_pipeline_queue_dir((), {"topic": "t", "run_id": "/tmp"}) is None


def test_a_call_that_mints_its_own_id_resolves_to_nothing():
    """The CLI's local runs have no Firestore record, so they can never be
    incognito — and the wrapper cannot know a name the body has not minted yet."""
    assert research._run_pipeline_queue_dir((), {"topic": "t"}) is None


# ══ 4. the sweep's memo does not hold an incognito folder for an hour ═════

HOUR = 3600.0
NOW = 1758400000.0  # a real epoch, because the memo's default is 0.0


def test_an_ordinary_research_confirmed_a_minute_ago_is_not_re_read():
    """⭐ ACCEPT POLARITY, and it is the reason the memo exists: the sweep billed
    one Firestore read per finished directory every five minutes, for ever —
    288 reads a day for one old run, always answering "still there"."""
    assert research._orphan_recheck_due(NOW - 60, NOW, CHAT, HOUR) is False


def test_an_ordinary_research_is_re_read_once_the_hour_is_up():
    assert research._orphan_recheck_due(NOW - HOUR, NOW, CHAT, HOUR) is True


def test_a_directory_never_seen_before_is_checked_on_the_very_next_tick():
    """⛔ A genuine orphan must be found exactly as fast as it was before the
    memo existed — the memo's own stated contract. The sweep passes `0.0` for a
    key it has never written, which is why this reads as an epoch and not as a
    small number."""
    assert research._orphan_recheck_due(0.0, NOW, CHAT, HOUR) is True


def test_a_run_that_keeps_nothing_is_never_held_by_the_memo():
    """⛔⛔ AN HOUR OF LATENCY WAS "a cleanup path with no user-visible surface".
    For this run the surface is a promise the app has already made, and the
    folder holds the documents, the delivery record and the topic."""
    assert research._orphan_recheck_due(NOW, NOW + 0.1, INCOG, HOUR) is True


# ══ 5. …and the sweep actually ASKS it ════════════════════════════════════
#
# ⛔⛔ A TESTED HELPER IS NOT A TESTED CONSUMER. The four assertions above pin
# `_orphan_recheck_due`'s truth table perfectly and not one of them touches the
# single line that calls it. Put that line back the way it was — an inline
# `if (now - _orphan_verified.get(key, 0.0)) < ORPHAN_RECHECK_SEC: continue` —
# and every test in this branch still passes and the harness still reports a
# clean score, while the folder holding the documents, the delivery record and
# the topic sits on somebody else's computer for up to sixty-five minutes after
# the app said nothing was kept. Measured: with the call site reverted the
# directory below survives the tick and costs zero Firestore reads.
#
# ⭐ THE LOOP IS A CLOSURE INSIDE `run_server`, SO IT IS RECONSTRUCTED, NOT
# COPIED. The code object is the real one; only the values `run_server` would
# have closed over are supplied here. A test that re-implemented the loop would
# be a second opinion about what it does, which is worth nothing.

INTERVAL = 300.0


class _SweepStopped(BaseException):
    """⛔ NOT AN `Exception`: the loop swallows those to survive a bad tick."""


class _FakeAsyncio:
    """`asyncio` as the loop uses it — one tick, then out."""
    CancelledError = asyncio.CancelledError

    def __init__(self):
        self.ticks = 0

    async def sleep(self, seconds):
        # The interval sleep is the top of the loop; the 0.25 is the pause
        # between the two existence reads and must be allowed through.
        if seconds == INTERVAL:
            self.ticks += 1
            if self.ticks > 1:
                raise _SweepStopped
        return None


class _Firestore:
    """Answers `exists` for every research, and counts what it was asked."""

    def __init__(self, exists):
        self.exists, self.reads = exists, 0

    def collection(self, _name):
        return self

    def document(self, _name):
        return self

    def get(self):
        self.reads += 1
        return types.SimpleNamespace(exists=self.exists)


def _sweep_tick(tmp_path, rid, *, verified_at, record_exists):
    """Run ONE tick of the real `_orphan_sweep_loop` over one finished run
    directory. Returns (the directory is still there, Firestore reads)."""
    code = next((c for c in research.run_server.__code__.co_consts
                 if isinstance(c, types.CodeType)
                 and c.co_name == "_orphan_sweep_loop"), None)
    assert code is not None, "the orphan sweep is no longer a closure of run_server"

    root = tmp_path / "queues"
    folder = root / f"run_{rid}"
    (folder / "documents").mkdir(parents=True)
    (folder / "delivery.json").write_text(json.dumps({"status": "completed"}),
                                          encoding="utf-8")
    (folder / "owner.json").write_text(
        json.dumps({"uid": "u1", "researchId": rid}), encoding="utf-8")
    os.utime(folder, (NOW - 100_000, NOW - 100_000))   # older than the age bound

    db = _Firestore(record_exists)
    cells = {
        "ORPHAN_RECHECK_SEC": HOUR,
        "ORPHAN_SWEEP_INTERVAL_SEC": INTERVAL,
        "ORPHAN_SWEEP_IN_FLIGHT_STATUSES": frozenset({"ongoing", "queued"}),
        "ORPHAN_SWEEP_MIN_AGE_SEC": 300,
        "_orphan_verified": {f"u1/{rid}": verified_at},
        "queues_root": root,
    }
    env = dict(research.__dict__)
    env.update(asyncio=_FakeAsyncio(),
               time=types.SimpleNamespace(time=lambda: NOW),
               _firebase_db=db,
               _run_log_folders_for_research=lambda _rid: [],
               log=lambda *a, **k: None)
    loop = types.FunctionType(
        code, env, "_orphan_sweep_loop", None,
        tuple(types.CellType(cells[name]) for name in code.co_freevars))
    try:
        asyncio.run(loop())
    except _SweepStopped:
        pass
    return folder.exists(), db.reads


def test_the_sweep_re_reads_a_run_that_keeps_nothing_on_the_very_next_tick(
        tmp_path):
    """⛔⛔ THE CONSUMER. Confirmed present one second ago, and the sweep asks
    again anyway — finds the record gone and takes the folder with it."""
    still_there, reads = _sweep_tick(tmp_path, INCOG, verified_at=NOW - 1.0,
                                     record_exists=False)
    assert not still_there, "the folder outlived the run the app said kept nothing"
    assert reads == 2, f"the sweep did not re-read the record: {reads} read(s)"


def test_the_sweep_still_trusts_the_memo_for_an_ordinary_research(tmp_path):
    """⭐ ACCEPT POLARITY, and it is the whole reason the memo exists: 288
    Firestore reads a day for one finished run, always answering 'still there'.
    A consumer that asked on every tick for everybody would pass the test above
    and undo that."""
    still_there, reads = _sweep_tick(tmp_path, CHAT, verified_at=NOW - 1.0,
                                     record_exists=False)
    assert still_there and reads == 0, (
        f"an ordinary folder confirmed a second ago cost {reads} read(s)")


def test_an_ordinary_research_is_swept_once_its_hour_is_up(tmp_path):
    """The memo delays the ordinary case; it does not cancel it."""
    still_there, reads = _sweep_tick(tmp_path, CHAT, verified_at=NOW - 2 * HOUR,
                                     record_exists=False)
    assert not still_there and reads == 2


def test_a_run_that_keeps_nothing_is_left_alone_while_its_record_lives(tmp_path):
    """⛔ THE SWEEP REMOVES ORPHANS, NOT RUNS. Asking every tick must not turn
    into deleting every tick — this folder belongs to a research that is still
    there, and the run may still be resumable from it."""
    still_there, reads = _sweep_tick(tmp_path, INCOG, verified_at=NOW - 1.0,
                                     record_exists=True)
    assert still_there and reads == 1
