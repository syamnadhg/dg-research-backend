"""Wave 15 (10-02) — a run moved to the queue goes back into its own chats.

The owner, 10-02: "all the crashes were opening their own new research, wasting
the usage … adapting the chat on reopen … is actually a required feature", and
yes to the same for "Move to queue": when a run that was moved to the queue is
picked up again by the SAME computer it re-adopts that run's chats; when a
different one picks it up, the phase starts fresh, because that one is signed in
to other accounts.

⭐ The mechanism is the crash rejoin's (tests/test_crash_rejoin_1001.py): Phase
2 notes the chat each agent was sent the brief in, and `run_pipeline(_p2_rejoin=)`
takes the first Phase-2 attempt back into them. What is new here is the trip
through the queue:

  1. the move keeps the run's chats in its marker, beside the worker it was
     moved off — only while the run is in Phase 2 or before it;
  2. whichever worker of this computer takes it back hands them to the run
     (review 10-02: the worker it was moved off stays off, so another one
     usually takes it; one signed in to other accounts cannot prove the chats
     are its own, and those agents start again — tests/test_crash_rejoin_1001.py);
  3. the worker loop passes them into the run.

⭐ EVERY STEP IS THE REAL CODE: the device-command listener's callback, the
idle rescan and the worker loop lifted out of `run_server`
(`_run_server_closure`), with test_requeue_w13's small machine for the disk and
Firestore.

Run:  pytest tests/test_w15_move_rejoin_1002.py -v
"""
import json
import types

import pytest

import research
import _run_server_closure  # noqa: F401  (imported at collection, as test_requeue_w13 says)
from _run_server_closure import run_worker_once
from test_requeue_w13 import (DEVICE, MARKER, RID, SHARER, _command, _job, _machine,
                              _requeue, _rescan, _run_folder, _running, _said, _Store)

CHATGPT = "https://chatgpt.com/c/6abf59c5-9654-83ea-9a90-22f795876408"
CLAUDE = "https://claude.ai/chat/2dbdf112-50d6-4351-b618-e91d68c381bc"
GEMINI_SENT = "https://gemini.google.com/app/3979dba4c0ffee01"
GEMINI_NOW = "https://gemini.google.com/app/58499e483bcc082c"
CHATS = {"chatgpt": CHATGPT, "claude": CLAUDE, "gemini": GEMINI_SENT}


#: When the run began: ten minutes before ChatGPT's chat id (hex seconds) was
#: minted. An older research chat of the same account: a day before that.
RUN_START = int("6abf59c5", 16) - 600
OLDER_CHATGPT = f"https://chatgpt.com/c/{int('6abf59c5', 16) - 86400:08x}-1111-82aa-b3cc-0123456789ab"
OLDER_CLAUDE = "https://claude.ai/chat/0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"


def _in_phase(monkeypatch, phase, chats=CHATS, *, gemini_tab=None, tabs=None):
    """The running pipeline's own record of its Phase-2 chats, as the move finds
    it: the address each agent was sent the brief at, and the tab it is in."""
    rt = research._runtime
    monkeypatch.setattr(rt, "phase", phase)
    monkeypatch.setattr(rt, "p2_chat_urls", dict(chats))
    monkeypatch.setattr(research, "_run_start_epoch", lambda: RUN_START)
    pages = {k: types.SimpleNamespace(url=u) for k, u in chats.items()}
    if gemini_tab is not None:
        pages["gemini"] = types.SimpleNamespace(url=gemini_tab)
    for k, u in (tabs or {}).items():
        pages[k] = types.SimpleNamespace(url=u)
    monkeypatch.setattr(rt, "p2_chat_pages", pages)
    monkeypatch.setattr(rt, "agent_modes", {})


def _marker(folder):
    return json.loads((folder / MARKER).read_text(encoding="utf-8"))


# ══ 1. the move keeps the chats ══════════════════════════════════════════════

def test_a_move_in_phase_2_keeps_each_agents_chat_beside_the_worker_it_ran_on(
        monkeypatch, tmp_path):
    """⭐ Through the real device-command listener. Gemini moved its run to a new
    chat after the brief went in (09-30, 10-02): the chat kept is the one its
    tab is on, as at a crash."""
    m, _job_, folder = _running(monkeypatch, tmp_path, worker=2)
    _in_phase(monkeypatch, 2, gemini_tab=GEMINI_NOW)
    _command(monkeypatch, m, _requeue(workerId=2))
    rec = _marker(folder)
    assert rec["from_worker"] == 2
    assert rec["p2_chats"] == {"chatgpt": CHATGPT, "claude": CLAUDE, "gemini": GEMINI_NOW}


def test_a_move_keeps_the_chats_chatgpt_and_claude_were_sent_the_brief_in(
        monkeypatch, tmp_path):
    """⛔⛔ Review 10-02. ChatGPT's and Claude's tabs wandered to older research
    chats of the same account before the move: the marker keeps the chats their
    brief went into, never the older ones — the run would otherwise go back into
    an older chat and collect its report as this run's. Before: it kept the
    older chats."""
    m, _job_, folder = _running(monkeypatch, tmp_path, worker=2)
    _in_phase(monkeypatch, 2, tabs={"chatgpt": OLDER_CHATGPT, "claude": OLDER_CLAUDE})
    _command(monkeypatch, m, _requeue(workerId=2))
    assert _marker(folder)["p2_chats"] == CHATS
    assert m.exits == ["requeue"], "the move itself did not go through"


@pytest.mark.parametrize("phase", [0, 1])
def test_a_move_before_phase_2_keeps_the_chats_a_crash_retry_was_handed(
        monkeypatch, tmp_path, phase):
    """A crash retry carries its chats from its start (`run_pipeline` puts them
    back in `p2_chat_urls`), so a move before it reaches Phase 2 keeps them."""
    m, _job_, folder = _running(monkeypatch, tmp_path, worker=2)
    _in_phase(monkeypatch, phase)
    _command(monkeypatch, m, _requeue(workerId=2))
    assert _marker(folder)["p2_chats"] == CHATS


@pytest.mark.parametrize("phase", [3, 4])
def test_a_move_after_phase_2_keeps_no_chats(monkeypatch, tmp_path, phase):
    """After Phase 2 there is nothing to go back into."""
    m, _job_, folder = _running(monkeypatch, tmp_path, worker=2)
    _in_phase(monkeypatch, phase)
    _command(monkeypatch, m, _requeue(workerId=2))
    rec = _marker(folder)
    assert "p2_chats" not in rec, rec
    assert m.exits == ["requeue"]


def test_a_move_with_no_chats_noted_writes_none(monkeypatch, tmp_path):
    m, _job_, folder = _running(monkeypatch, tmp_path, worker=2)
    _in_phase(monkeypatch, 2, chats={})
    _command(monkeypatch, m, _requeue(workerId=2))
    assert "p2_chats" not in _marker(folder)


def test_a_chat_the_move_cannot_read_does_not_stop_the_move(monkeypatch, tmp_path):
    """⛔ A move must never fail over its chats: an unreadable record is no
    chats, and the run still goes to the queue."""
    m, _job_, folder = _running(monkeypatch, tmp_path, worker=2)
    _in_phase(monkeypatch, 2)

    def _boom():
        raise RuntimeError("the record could not be read")
    monkeypatch.setattr(research, "_p2_chats_to_rejoin", _boom)
    _command(monkeypatch, m, _requeue(workerId=2))
    assert "p2_chats" not in _marker(folder)
    assert m.exits == ["requeue"]


# ══ 2. the worker that takes it back ═════════════════════════════════════════

def _moved_with_chats(monkeypatch, tmp_path, *, taker, from_worker=2, chats=CHATS):
    """A run moved off `from_worker` with its chats kept; this computer's
    worker `taker` is idle and awake."""
    store = _Store(records={(SHARER, RID): {"status": "queued"}})
    m = _machine(monkeypatch, tmp_path, store, worker=taker)
    _run_id, folder = _run_folder(tmp_path, RID)
    rec = {"uid": SHARER, "research_id": RID, "run_id": folder.name, "topic": "a topic",
           "email": "someone@example.com", "config": {}, "submitted_by": SHARER,
           "moved_at_ms": 1, "from_worker": from_worker}
    if chats is not None:
        rec["p2_chats"] = dict(chats)
    (folder / MARKER).write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda *_a: [])
    return m, folder


@pytest.mark.parametrize("from_worker, taker", [(2, 2), (1, 2), (None, 2)],
                         ids=["the-worker-it-left", "another-worker", "not-recorded"])
def test_any_worker_of_this_computer_takes_the_chats_back(monkeypatch, tmp_path,
                                                          from_worker, taker):
    """⭐ Review 10-02, the owner's words: "picked up again by the SAME computer
    re-adopts that run's chats". The worker it was moved off stays off, so
    another worker usually takes it — and before, that worker sent every brief
    again. Each worker tries the chats; one signed in to other accounts cannot
    prove them, and those agents start again (the rejoin's proof)."""
    m, _folder = _moved_with_chats(monkeypatch, tmp_path, taker=taker, from_worker=from_worker)
    [job] = _rescan(monkeypatch, m)
    assert job["research_id"] == RID and job["p2_rejoin"] == CHATS, job
    assert _said(m, f"comes back to worker {taker}", "goes back into its chats"), m.lines

    # Beside it: a run whose marker kept no chats is taken as before, saying
    # nothing about chats.
    m2, _folder2 = _moved_with_chats(monkeypatch, tmp_path / "none", taker=taker,
                                     from_worker=from_worker, chats=None)
    [job2] = _rescan(monkeypatch, m2)
    assert job2["research_id"] == RID and "p2_rejoin" not in job2
    assert not _said(m2, "goes back into its chats")


# ══ 3. the worker loop passes them into the run ══════════════════════════════

def test_the_worker_loop_hands_a_moved_runs_chats_to_the_run(monkeypatch, tmp_path):
    """⭐ Through the REAL dequeue: `_p2_rejoin` is what `run_pipeline` takes the
    first Phase-2 attempt back into the chats with."""
    store = _Store(records={(SHARER, RID): {"status": "ongoing"}})
    _machine(monkeypatch, tmp_path, store, worker=2)
    _run_id, folder = _run_folder(tmp_path, RID)
    job = _job(SHARER, RID, folder.name, resume_dir=str(folder), moved_run=True,
               p2_rejoin=dict(CHATS))
    started = run_worker_once(monkeypatch, tmp_path, job, flip="skipped(ongoing)", db=store,
                              update_research=lambda *a, **k: True, device_id=DEVICE)
    assert len(started) == 1 and started[0]["_p2_rejoin"] == CHATS


def test_a_job_with_no_chats_hands_the_run_none(monkeypatch, tmp_path):
    store = _Store(records={(SHARER, RID): {"status": "ongoing"}})
    _machine(monkeypatch, tmp_path, store, worker=1)
    _run_id, folder = _run_folder(tmp_path, RID)
    job = _job(SHARER, RID, folder.name, resume_dir=str(folder))
    started = run_worker_once(monkeypatch, tmp_path, job, flip="skipped(ongoing)", db=store,
                              update_research=lambda *a, **k: True, device_id=DEVICE)
    assert len(started) == 1 and started[0]["_p2_rejoin"] is None


@pytest.mark.parametrize("taker", [2, 1], ids=["same-worker", "another-worker"])
def test_move_then_pickup_then_run_end_to_end(monkeypatch, tmp_path, taker):
    """⭐ The whole trip on one disk: worker 2 is moved off mid-Phase 2; then
    `taker` takes the run from the queue and its worker loop starts it — back
    into the run's chats, whichever worker of this computer it is."""
    m, _job_, folder = _running(monkeypatch, tmp_path, worker=2)
    _in_phase(monkeypatch, 2)
    _command(monkeypatch, m, _requeue(workerId=2))
    assert (folder / MARKER).exists()

    monkeypatch.setattr(research, "WORKER_ID", taker)
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda *_a: [])
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    [job] = _rescan(monkeypatch, m)
    started = run_worker_once(monkeypatch, tmp_path, job, flip="skipped(ongoing)",
                              db=m.store, update_research=lambda *a, **k: True,
                              device_id=DEVICE)
    assert len(started) == 1 and started[0]["resume_dir"] == str(folder)
    assert started[0]["_p2_rejoin"] == CHATS, started[0]
