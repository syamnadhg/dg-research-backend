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
import json

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
