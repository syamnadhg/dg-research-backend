"""Wave 16 — one log folder per research, however many times it runs.

The owner: logs grouped by research, not by how many times the browser opened.

⛔⛔ WHAT WAS MEASURED BEFORE THIS (10-02, read-only on this Mac). One research
was split across FOUR folders in five minutes — two Move-to-queue exits, a
cancel and a Stop — and another had a first folder plus `_retry1`. Two of the
four were attributed to nobody, because a Retry/Resume dropped the person; so
their logs never reached the app's Send Logs list. The support bundle's "1 run"
sent only the newest folder, i.e. the last attempt.

⭐ What holds now, each through the code that does it:
  · the browser-restart retry and the one-shot retry JOIN the folder they run
    in, with one line saying why — the REAL `run_pipeline` recursion;
  · a later pick-up (moved, resumed) continues the research's newest finished
    folder, carrying its events, counters and attempts; a different person, or
    a folder still being written, gets a new folder as before;
  · the dead-or-alive ceiling counts from the CURRENT attempt's start;
  · a reopened run.log keeps its newest tail segments and goes on numbering;
  · Retry and the login resume carry the person;
  · "1 run" in the bundle and the published list count researches;
  · Move to queue marks its folder "moved" while its process still lives;
  · a run that keeps nothing still loses its one folder exactly once.

Run:  pytest tests/test_one_log_folder_per_research_w16.py -v
"""
import asyncio
import json
import os
import time
import zipfile

import pytest

import research
# ⛔ Imported at collection: it reads `research.__file__` once, and tests below
# point that at a temporary directory.
import _run_server_closure  # noqa: F401
from _queue_listener import Listener

ALICE = "uid-alice-w16-000000000000001"
BOB = "uid-bob-w16-00000000000000002"
OWNER = "uid-owner-w16-000000000000003"
RID = "chat_1790000000016_1"
DEAD_PID = 999_999_999


@pytest.fixture(autouse=True)
def _clean_stack():
    research._RUN_LOG_SINKS.clear()
    research._RUN_LOG_LAST_DIR = None
    yield
    for sink in list(research._RUN_LOG_SINKS):
        try:
            sink.writer.close()
        except Exception:
            pass
    research._RUN_LOG_SINKS.clear()


def _folders():
    root = research._runs_log_root()
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []


def _meta(folder):
    return json.loads((folder / "meta.json").read_text(encoding="utf-8"))


def _log(folder):
    return (folder / "run.log").read_text(encoding="utf-8")


def _attempt(monkeypatch, *, line=None, event=None, inside=None, **kw):
    """One attempt through the REAL wrapper; the pipeline body is a stand-in
    that writes `line` (a WARN) and mirrors `event` into the armed folder."""
    async def _body(*_a, **_k):
        if line:
            research.log(line, "WARN")
        if event:
            research._run_sink_note_event(event, phase=2)
        if inside:
            inside()
        return "done"

    monkeypatch.setattr(research, "run_pipeline", _body)
    kw.setdefault("topic", "a topic")
    asyncio.run(research.run_pipeline_captured(**kw))


# ══ 1. the crash retry joins its folder — the REAL recursion ═════════════════

class _FakeBrowser:
    def __init__(self, *a, **k):
        self.context = None

    async def start(self):
        return None

    async def close(self):
        return None


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """The real `run_pipeline_captured` → real `run_pipeline`, whose attempts
    fail as `failures` says, in order: the crash retry recurses for real."""
    queue_dir = tmp_path / "Topic_20261002_051554"
    (queue_dir / "documents").mkdir(parents=True)
    (queue_dir / "documents" / "brief.md").write_text("# Brief\n\n" + "x" * 300,
                                                      encoding="utf-8")
    cards = []
    monkeypatch.setattr(research, "resolve_api_key", lambda _k: "test-key")
    monkeypatch.setattr(research, "_capture_anthropic_attribution", lambda *a, **k: None)
    monkeypatch.setattr(research, "clear_clipboard", lambda *a, **k: None)
    monkeypatch.setattr(research, "init_tracks", lambda *a, **k: None)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    monkeypatch.setattr(research, "Browser", _FakeBrowser)
    monkeypatch.setattr(research, "_profile_dir", lambda *_a, **_k: tmp_path / "profile")
    monkeypatch.setattr(research, "_update_firestore_research", lambda *a, **k: None)

    async def _noop_dispatcher():
        return None
    monkeypatch.setattr(research, "run_input_dispatcher", _noop_dispatcher)
    monkeypatch.setattr(research, "fail_phase", lambda **kw: cards.append(kw))
    _real_sleep = asyncio.sleep

    async def _fast_sleep(*_a, **_k):
        return await _real_sleep(0)
    monkeypatch.setattr(research.asyncio, "sleep", _fast_sleep)

    def _run(failures, *, resume=True, crash_retries=0):
        left = list(failures)

        def _emit(name, phase=None, **_kw):
            if name == "phase_start" and phase == 0 and left:
                research._runtime.phase = 2
                research.log(f"attempt line {len(failures) - len(left) + 1}", "INFO")
                raise left.pop(0)
        monkeypatch.setattr(research, "emit_event", _emit)
        asyncio.run(research.run_pipeline_captured(
            topic="a topic", resume_dir=str(queue_dir) if resume else None,
            run_id=queue_dir.name, uid=None, email=None, api_key="test-key",
            research_id=RID, _crash_retries=crash_retries))
        return cards

    yield _run
    research._runtime.reset()
    research._controls.reset()


def _chrome_died():
    return RuntimeError("research browser died during phase 2 (browser crash)")


def test_a_browser_restart_writes_into_the_same_folder_with_one_line(pipeline):
    """⛔⛔ THE MEASURED SPLIT: each browser restart opened `<id>_<ts>_retryN`."""
    pipeline([_chrome_died(), RuntimeError("an ordinary failure")])
    folders = _folders()
    assert len(folders) == 1, [f.name for f in folders]
    text = _log(folders[0])
    assert "=== browser restarted — attempt 2 of 3 ===" in text
    assert text.index("attempt line 1") < text.index("attempt 2 of 3") < \
        text.index("attempt line 2")
    meta = _meta(folders[0])
    assert [(a["n"], a["why"]) for a in meta["attempts"]] == [
        (1, "start"), (2, "browser-restart")]
    assert meta["attempts"][0]["status"] == "browser-crashed"
    assert meta["attempts"][1]["status"] == "complete"
    assert meta["status"] == "complete" and meta["attempt"] == 1
    assert "retry" not in folders[0].name


def test_the_one_shot_retry_says_it_tried_again(pipeline, monkeypatch):
    """The ordinary failure's one retry joins the folder too, with its own line.
    The planner is stubbed only to open that door for the first attempt (it
    asks twice: once to hold the card back, once to retry); its gates have
    their own suite."""
    real = research._plan_pipeline_auto_retry
    calls = []

    def _once(*a, **k):
        calls.append(1)
        return (True, 2, False) if len(calls) <= 2 else real(*a, **k)
    monkeypatch.setattr(research, "_plan_pipeline_auto_retry", _once)
    pipeline([RuntimeError("the notebook upload was refused"),
              RuntimeError("and again")], resume=False)
    folders = _folders()
    assert len(folders) == 1, [f.name for f in folders]
    assert "=== tried again from where it got to ===" in _log(folders[0])
    assert "browser restarted" not in _log(folders[0])
    assert [a["status"] for a in _meta(folders[0])["attempts"]] == ["failed", "complete"]


def test_a_retry_after_a_long_first_attempt_still_reads_running(monkeypatch):
    """⛔⛔ The dead-or-alive ceiling, in-process: a first attempt that ran for
    five hours before Chrome died must not make its retry read dead an hour
    later. The joined attempt's start is the folder's `startedUtc` now."""
    import datetime as _dt
    long_ago = time.time() - research.RUN_LOG_DEAD_AFTER_SEC - 60
    old_iso = _dt.datetime.fromtimestamp(long_ago, _dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    real_iso = research._utc_iso
    monkeypatch.setattr(research, "_utc_iso", lambda when=None: old_iso)
    with research._RunLogCapture(research_id=RID) as outer:
        monkeypatch.setattr(research, "_utc_iso", real_iso)
        with research._RunLogCapture(research_id=RID, attempt=1, why="browser-restart"):
            meta = _meta(outer.dir)
            assert research._derive_run_status(meta) == "running"
            assert meta["firstStartedUtc"] == old_iso and meta["startedUtc"] != old_iso


def test_a_joined_attempt_ending_after_a_move_keeps_the_folder_moved():
    """The move said "moved"; an attempt that ends after it must not write
    "running" back over it — the folder would read live again and the pick-up
    would open a folder of its own. ⛔ (review) And the moved attempt itself
    stays "moved": the retry's "failed" and the folder's final "moved" are
    for the attempts still open, never one that has ended."""
    with research._RunLogCapture(research_id=RID) as sink:
        assert research._mark_run_log_moved(RID) is True
        with research._RunLogCapture(research_id=RID, attempt=1, why="retry"):
            pass
        assert _meta(sink.dir)["status"] == "moved"
        assert research._folder_is_live(sink.dir) is False
    assert [a["status"] for a in _meta(sink.dir)["attempts"]] == ["moved", "complete"]


def test_a_joined_attempt_counts_its_own_time(monkeypatch):
    """⛔ (review) A joined retry starts its own clock: an hour-long first
    attempt keeps its hour, and the retry's `durationSec` — its own and the
    folder's top-level one, which is the current attempt's — is its own."""
    with research._RunLogCapture(research_id=RID) as sink:
        sink.started_mono -= 3600            # the first attempt ran an hour
        with research._RunLogCapture(research_id=RID, attempt=1, why="browser-restart"):
            pass
    meta = _meta(sink.dir)
    first, second = meta["attempts"]
    assert first["durationSec"] >= 3600
    assert second["durationSec"] < 60 and meta["durationSec"] < 60


def test_a_different_research_nested_inside_keeps_a_folder_of_its_own():
    """Only the SAME research joins. Anything else nested inside a run (never
    seen, but possible) still gets its own folder, names its parent, and the
    outer run is armed again the moment it ends."""
    with research._RunLogCapture(research_id=RID) as outer:
        with research._RunLogCapture(research_id="chat_1790000000016_9") as inner:
            assert research._active_run_sink() is inner
        assert research._active_run_sink() is outer, "the outer run was disarmed"
    assert inner is not outer and inner.dir != outer.dir
    assert _meta(inner.dir)["parentResearchId"] == RID
    assert _meta(inner.dir)["status"] == "complete"
    assert len(_meta(outer.dir)["attempts"]) == 1


# ══ 2. a later pick-up continues the research's folder ═══════════════════════

def test_a_resume_continues_the_finished_folder_with_everything_carried(monkeypatch):
    _attempt(monkeypatch, line="first attempt line", event="phase_start",
             research_id=RID, uid=ALICE, _submitted_by=ALICE)
    (first,) = _folders()
    before = _meta(first)
    _attempt(monkeypatch, line="second attempt line", event="phase_complete",
             research_id=RID, uid=ALICE, _submitted_by=ALICE, resume_dir="/x",
             _log_reason="resumed")
    assert _folders() == [first], "the pick-up opened a folder of its own"
    text = _log(first)
    assert text.index("first attempt line") < \
        text.index("=== picked up again from where it stopped ===") < \
        text.index("second attempt line")
    meta = _meta(first)
    assert [(a["why"], a["status"]) for a in meta["attempts"]] == [
        ("start", "complete"), ("resumed", "complete")]
    assert meta["firstStartedUtc"] == before["startedUtc"]
    assert meta["counters"]["warns"] == 2 and meta["counters"]["lines"] >= 2
    events = json.loads((first / "events.json").read_text(encoding="utf-8"))
    assert [e["type"] for e in events] == ["phase_start", "phase_complete"]
    assert meta["submitterUid"] == ALICE


@pytest.mark.parametrize("reason,closed,line", [
    ("moved", "moved", "picked up again after a move to the queue"),
    (None, "process-died", "picked up again"),
])
def test_a_pick_up_after_the_process_died_closes_the_attempt_it_left(
        monkeypatch, reason, closed, line):
    """A worker that exited mid-run left its meta saying it runs. Once its
    process is gone the folder is continued, and that attempt is closed."""
    with monkeypatch.context() as mp:
        mp.setattr(research.os, "getpid", lambda: DEAD_PID)
        cap = research._RunLogCapture(research_id=RID, submitted_by=ALICE,
                                      claimed_by=ALICE)
        sink = cap.__enter__()
    sink.writer.close()
    research._RUN_LOG_SINKS.clear()          # that process is gone
    (folder,) = _folders()
    assert research._derive_run_status(_meta(folder)) == "process-died"
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE,
             _log_reason=reason)
    assert _folders() == [folder]
    assert f"=== {line} ===" in _log(folder)
    meta = _meta(folder)
    assert [a["status"] for a in meta["attempts"]] == [closed, "complete"]
    assert [a["pid"] for a in meta["attempts"]] == [DEAD_PID, os.getpid()]
    assert meta["pid"] == os.getpid()


def test_a_different_person_gets_a_folder_of_their_own(monkeypatch):
    """⛔ Attribution decides the merge: one person's attempt is never written
    into a folder attributed to someone else (or to nobody)."""
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE)
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=None,
             _log_reason="resumed")
    assert len(_folders()) == 2
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE,
             _log_reason="resumed")
    assert len(_folders()) == 2, "the person's own folder was not found again"
    owned = [f for f in _folders() if _meta(f)["submitterUid"] == ALICE]
    assert len(owned) == 1 and len(_meta(owned[0])["attempts"]) == 2


def test_a_folder_another_process_still_writes_is_never_continued(monkeypatch):
    """⛔⛔ Two writers on one run.log. A folder that reads live — its process
    alive and inside the ceiling — means a new folder, today's behaviour."""
    cap = research._RunLogCapture(research_id=RID, submitted_by=ALICE, claimed_by=ALICE)
    sink = cap.__enter__()
    research._RUN_LOG_SINKS.clear()          # armed by "another process"
    try:
        assert research._folder_is_live(sink.dir)
        _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE,
                 _log_reason="resumed")
        assert len(_folders()) == 2
        assert len(_meta(sink.dir)["attempts"]) == 1
    finally:
        sink.writer.close()


def test_after_a_split_the_pick_up_continues_the_newest_folder(monkeypatch):
    """⛔ (review) A research CAN still have two folders: a pick-up while
    another process still wrote the first (expected on Windows, where an exited
    worker reads alive for a while) opens a second. The next pick-up continues
    the one started LAST — even though the first, finishing after it, was
    touched last."""
    import datetime as _dt
    ten_min_ago = _dt.datetime.fromtimestamp(time.time() - 600, _dt.timezone.utc) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    real_iso = research._utc_iso
    monkeypatch.setattr(research, "_utc_iso", lambda when=None: ten_min_ago)
    cap = research._RunLogCapture(research_id=RID, submitted_by=ALICE, claimed_by=ALICE)
    first = cap.__enter__()
    monkeypatch.setattr(research, "_utc_iso", real_iso)
    research._RUN_LOG_SINKS.clear()          # still being written "elsewhere"
    try:
        _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE,
                 _log_reason="resumed")
    finally:
        cap.__exit__(None, None, None)       # the first finishes after the second
    (second,) = [f for f in _folders() if f != first.dir]
    os.utime(first.dir, (time.time() + 100, time.time() + 100))
    os.utime(second, (time.time() - 100, time.time() - 100))
    _attempt(monkeypatch, line="THIRD-ATTEMPT-MARK", research_id=RID, uid=ALICE,
             _submitted_by=ALICE, _log_reason="moved")
    assert len(_folders()) == 2
    assert "THIRD-ATTEMPT-MARK" in _log(second)
    assert "THIRD-ATTEMPT-MARK" not in _log(first.dir)
    assert len(_meta(second)["attempts"]) == 2 and len(_meta(first.dir)["attempts"]) == 1


def test_a_carried_event_list_over_the_cap_keeps_the_newest_and_counts_the_rest(
        monkeypatch):
    """⛔ (review) A continued folder's events.json longer than the cap keeps
    its NEWEST events, and the ones it drops are counted."""
    monkeypatch.setattr(research, "RUN_LOG_EVENT_CAP", 10)
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE)
    (folder,) = _folders()
    (folder / "events.json").write_text(json.dumps(
        [{"t": i, "type": f"e{i}", "phase": None, "agent": None} for i in range(15)]),
        encoding="utf-8")
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE,
             _log_reason="resumed")
    events = json.loads((folder / "events.json").read_text(encoding="utf-8"))
    assert [e["type"] for e in events] == [f"e{i}" for i in range(5, 15)]
    assert _meta(folder)["counters"]["eventsDropped"] == 5


def test_an_older_builds_split_folder_is_left_alone(monkeypatch):
    """No `attempts` in its meta: made before this wave. It ages out as it is."""
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE)
    (old,) = _folders()
    meta = _meta(old)
    del meta["attempts"]
    (old / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE,
             _log_reason="resumed")
    assert len(_folders()) == 2


# ══ 3. the dead-or-alive ceiling counts from the CURRENT attempt ═════════════

def test_a_research_first_run_long_ago_reads_running_while_it_runs_again(monkeypatch):
    """⛔⛔ Counted from the first start, a research picked up days later would
    read dead while it runs — and a sibling's prune would delete its folder."""
    long_ago = time.time() - research.RUN_LOG_DEAD_AFTER_SEC - 3600
    import datetime as _dt
    old_iso = _dt.datetime.fromtimestamp(long_ago, _dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    real_iso = research._utc_iso
    monkeypatch.setattr(research, "_utc_iso", lambda when=None: old_iso)
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE)
    monkeypatch.setattr(research, "_utc_iso", real_iso)
    (folder,) = _folders()
    seen = {}

    def _inside():
        meta = _meta(folder)
        seen["status"] = research._derive_run_status(meta)
        seen["live"] = research._folder_is_live(folder)
        seen["first"] = meta["firstStartedUtc"]
        seen["now"] = meta["startedUtc"]
        seen["pruned"] = research._prune_local_logs(runs_keep=0)
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE,
             _log_reason="moved", inside=_inside)
    assert seen["status"] == "running" and seen["live"] is True
    assert seen["first"] == old_iso and seen["now"] != old_iso
    assert str(folder) not in seen["pruned"]


# ══ 4. a reopened run.log keeps its tail ═════════════════════════════════════

def test_a_reopened_capped_log_keeps_the_newest_segments_and_goes_on_numbering(tmp_path):
    primary = tmp_path / "run.log"
    first = research._CappedLogWriter(primary, max_bytes=200, segment_bytes=100, keep=2)
    for i in range(40):
        first.write_line(f"first writer line {i:03d}")
    first.close()
    before = sorted(p.name for p in tmp_path.iterdir())
    assert before == ["run.log", "run.log.overflow7", "run.log.overflow8"], before
    second = research._CappedLogWriter(primary, max_bytes=200, segment_bytes=100, keep=2)
    second.write_line("second writer line")
    assert [p.name for p in second.paths()] == [
        "run.log", "run.log.overflow7", "run.log.overflow8"]
    assert (tmp_path / "run.log.overflow8").read_text(
        encoding="utf-8").endswith("second writer line\n")
    for i in range(10):
        second.write_line(f"second writer line {i:03d}")
    second.close()
    after = sorted(p.name for p in tmp_path.iterdir())
    assert after == ["run.log", "run.log.overflow10", "run.log.overflow11"], after
    assert "second writer" not in primary.read_text(encoding="utf-8")


def test_a_reopened_log_with_more_segments_than_it_keeps_drops_the_oldest(tmp_path):
    primary = tmp_path / "run.log"
    primary.write_text("head\n", encoding="utf-8")
    for n in (3, 4, 5):
        (tmp_path / f"run.log.overflow{n}").write_text(f"seg {n}\n", encoding="utf-8")
    (tmp_path / "run.log.overflowX").write_text("not a segment\n", encoding="utf-8")
    w = research._CappedLogWriter(primary, max_bytes=200, segment_bytes=100, keep=2)
    w.write_line("tail line")
    w.close()
    assert not (tmp_path / "run.log.overflow3").exists()
    assert (tmp_path / "run.log.overflowX").exists()
    assert (tmp_path / "run.log.overflow5").read_text(encoding="utf-8") == "seg 5\ntail line\n"
    assert w.dropped_segments == 1


def test_a_pick_up_of_an_overflowed_folder_writes_into_its_tail(monkeypatch):
    """The consumer: the capture reopens the folder's run.log through the sink."""
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE)
    (folder,) = _folders()
    for n in (1, 2, 3):
        (folder / f"run.log.overflow{n}").write_text(f"seg {n}\n", encoding="utf-8")
    _attempt(monkeypatch, line="after the pick-up", research_id=RID, uid=ALICE,
             _submitted_by=ALICE, _log_reason="resumed")
    assert not (folder / "run.log.overflow1").exists()
    assert "after the pick-up" in (folder / "run.log.overflow3").read_text(encoding="utf-8")
    assert "after the pick-up" not in _log(folder)


# ══ 5. a resumed run keeps the person ════════════════════════════════════════

def test_a_retry_carries_the_person_who_pressed_it(tmp_path, monkeypatch):
    """Through the REAL start listener's resume branch."""
    run = "Alice_topic_20261002_051554"
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    d = tmp_path / "queues" / run
    d.mkdir(parents=True)
    (d / "owner.json").write_text(json.dumps({"uid": ALICE, "researchId": RID}),
                                  encoding="utf-8")
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(ALICE, RID): {"status": "paused_backend_restart"}}).feed(
        action="resume", uid=ALICE, submittedBy=ALICE, researchId=RID, backendRunId=run)
    assert len(lis.enqueued) == 1
    assert lis.enqueued[0]["submitted_by"] == ALICE


def test_the_login_resume_carries_the_person_it_was_paused_for(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(research, "_firebase_db", object())
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", object())

    def _inside():
        seen["plan"] = research._login_auto_resume_plan(
            tmp_path / "Run_20261002_051554", uid=ALICE, research_id=RID, email="")
    _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE, inside=_inside)
    plan = seen["plan"]
    assert plan["submitted_by"] == ALICE
    monkeypatch.setattr(research, "_login_still_running", lambda: False)

    async def _no_chrome(*_a):
        return False
    monkeypatch.setattr(research, "_login_left_chrome_open", _no_chrome)
    monkeypatch.setattr(research, "_login_resume_verdict", lambda _p: "go")
    calls = []
    monkeypatch.setattr(research, "_resume_from_checkpoint",
                        lambda *a, **k: calls.append(k) or True)
    assert asyncio.run(research._resume_after_login(plan)) == "resumed"
    assert calls[0]["submitted_by"] == ALICE


# ══ 6. the worker says why it picked a run up ════════════════════════════════

class _Record:
    def collection(self, _name):
        return self

    document = collection

    def get(self):
        return type("Snap", (), {"exists": True,
                                 "to_dict": lambda _s: {"status": "queued"}})()


@pytest.mark.parametrize("extra,why", [
    ({"moved_run": True, "resume_dir": "/q/run"}, "moved"),
    ({"resume_dir": "/q/run"}, "resumed"),
    ({}, None),
])
def test_the_worker_tells_the_capture_why_it_picked_the_run_up(
        monkeypatch, tmp_path, extra, why):
    from _run_server_closure import run_worker_once
    job = {"topic": "t", "email": "", "run_id": "T_20261002_051554",
           "uid": ALICE, "research_id": RID, "submitted_by": ALICE, **extra}
    started = run_worker_once(monkeypatch, tmp_path, job, flip="flipped",
                              db=_Record(), update_research=lambda *a, **k: True)
    assert len(started) == 1
    assert started[0]["_log_reason"] == why


# ══ 7. the bundle and the published list count researches ════════════════════

def test_one_run_in_the_bundle_is_the_whole_research(monkeypatch, tmp_path):
    _attempt(monkeypatch, line="FIRST-ATTEMPT-MARK", research_id=RID, uid=ALICE,
             _submitted_by=ALICE)
    _attempt(monkeypatch, line="SECOND-ATTEMPT-MARK", research_id=RID, uid=ALICE,
             _submitted_by=ALICE, _log_reason="moved")
    dest = tmp_path / "b.zip"
    research._build_log_bundle(dest, support_code="ABCD2345", max_runs=1,
                               keep_uid=ALICE, include_machine=False)
    with zipfile.ZipFile(dest) as zf:
        logs = [zf.read(n).decode("utf-8") for n in zf.namelist()
                if n.endswith("run.log")]
    assert len(logs) == 1, logs
    assert "FIRST-ATTEMPT-MARK" in logs[0] and "SECOND-ATTEMPT-MARK" in logs[0]


def test_the_published_list_has_one_row_per_research(monkeypatch):
    for reason in (None, "moved", "resumed"):
        _attempt(monkeypatch, research_id=RID, uid=ALICE, _submitted_by=ALICE,
                 _log_reason=reason)
    docs = research._run_index_by_submitter(research._scan_run_folders())
    rows = docs[ALICE]["runs"]
    assert [r["researchId"] for r in rows] == [RID]
    assert set(rows[0]) == {"name", "researchId", "startedUtc", "status",
                            "sizeBytes", "attempt"}


# ══ 8. Move to queue marks its folder ════════════════════════════════════════

def test_a_moved_run_reads_finished_while_its_process_still_lives(monkeypatch, tmp_path):
    """⛔⛔ On Windows a worker that has exited can still read alive. The move
    writes "moved" itself, so the pick-up never waits on the old process —
    through the REAL device-command listener."""
    from test_requeue_w13 import _command, _requeue, _running
    import test_requeue_w13 as rq
    m, _job, _folder = _running(monkeypatch, tmp_path)
    cap = research._RunLogCapture(research_id=rq.RID, submitted_by=rq.SHARER,
                                  claimed_by=rq.SHARER)
    sink = cap.__enter__()
    try:
        assert research._folder_is_live(sink.dir)
        _command(monkeypatch, m, _requeue())
        assert m.exits == ["requeue"]
        meta = _meta(sink.dir)
        assert meta["status"] == "moved" and meta["pid"] == os.getpid()
        assert research._folder_is_live(sink.dir) is False
        assert meta["attempts"][-1]["status"] == "moved"
        # The sink stays armed: this process's last lines still land there.
        assert research._active_run_sink() is sink
        cap.__exit__(asyncio.CancelledError, None, None)
        assert _meta(sink.dir)["status"] == "moved", "the exit wrote over the move"
    finally:
        sink.writer.close()
        research._RUN_LOG_SINKS.clear()


def test_a_move_names_only_its_own_research(monkeypatch):
    with research._RunLogCapture(research_id=RID) as sink:
        assert research._mark_run_log_moved("chat_1790000000016_9") is False
        assert _meta(sink.dir)["status"] == "running"
        assert research._mark_run_log_moved(RID) is True
        assert _meta(sink.dir)["status"] == "moved"


# ══ 9. a run that keeps nothing loses its one folder once ════════════════════

def test_a_joined_retry_of_a_private_run_keeps_the_live_folder_until_the_end(
        tmp_path, monkeypatch):
    """The inner attempt's purge runs while the outer still writes the folder:
    it must leave it, and the outer's purge then removes it."""
    incog = "incog_1790831743868_4"
    run = tmp_path / "queues" / "incog_run_20261002_051554"
    run.mkdir(parents=True)
    (run / "owner.json").write_text(json.dumps({"uid": ALICE, "researchId": incog}),
                                    encoding="utf-8")
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    seen = {}

    async def _body(*_a, research_id=None, _crash_retries=0, **_k):
        if _crash_retries == 0:
            research.log("outer attempt line", "INFO")
            await research.run_pipeline_captured(
                topic="t", run_id=run.name, research_id=research_id,
                _crash_retries=1, _log_reason="browser-restart")
            seen["after_inner"] = [f.name for f in _folders()]
            seen["text"] = _log(_folders()[0]) if _folders() else ""
            seen["run_kept"] = run.exists()
            return "done"
        research.log("inner attempt line", "INFO")
        (run / "delivery.json").write_text(json.dumps({"status": "completed"}),
                                           encoding="utf-8")
        return "done"

    monkeypatch.setattr(research, "run_pipeline", _body)
    asyncio.run(research.run_pipeline_captured(topic="t", run_id=run.name,
                                               research_id=incog))
    assert len(seen["after_inner"]) == 1, seen["after_inner"]
    assert "outer attempt line" in seen["text"] and "inner attempt line" in seen["text"]
    assert seen["run_kept"], "the joined attempt purged the run under the outer one"
    assert _folders() == [], "the private run's folder outlived the run"
    assert not run.exists()
