"""A run the login command paused continues by itself when the login finishes.

Owner, 2026-09-30: "hitting login during a run … Right after the login command,
the run must restart … even in the middle, if there is a Cloudflare, we can do a
login command, sort out the Cloudflare, and then the run continues again."

Before this, the run paused at its checkpoint with a "Paused by the login
command" card and stayed there until somebody pressed Retry.

▶ EXECUTED, NOT READ. The run is paused by the REAL `run_pipeline` catching the
REAL raise of a phase-2 site (the round-robin's dead-tab sweep), a phase-3 site
(`_p3_browser_gone`) and the human-check wait (`check_hv_gate`). The login
marker is written and cleared by the real `_write_login_marker` /
`_clear_login_marker`, under a HOME of the test's own. The resume goes through
the real `_resume_from_checkpoint`, and a Retry through the real start
listener. Only the machine's edges are fakes: Firestore, the browser, the
worker queue.
"""
import asyncio
import json
import os
import threading
import time

import pytest

import research
from _queue_listener import FakeDb, Listener

UID = "uid-alice"
RID = "chat_1759200000000_1"
RUN = "Grid_storage_20260930_120000"


class _FakeBrowser:
    """Never launched: the run is interrupted before phase 0 starts it."""

    def __init__(self, *a, **k):
        self.context = None

    async def start(self):
        return None

    async def close(self):
        return None


class _Jobs:
    """One worker's job queue — what the resume put on it. `timeline`, when
    given, is shared with the research's events, so a test can tell which
    reached the machine's outside first."""

    def __init__(self, timeline=None):
        self.put = []
        self._timeline = timeline

    def put_nowait(self, job):
        self.put.append(job)
        if self._timeline is not None:
            self._timeline.append(("job", job.get("run_id")))

    def qsize(self):
        return 0


class _EventsCol:
    """`users/{uid}/researches/{rid}/pipeline_events` — what was written there."""

    def __init__(self, db, path):
        self._db = db
        self._path = path

    def add(self, data):
        self._db.events.append({"uid": self._path[1], "rid": self._path[3], **data})
        self._db.timeline.append(("event", data.get("type")))


class _EventsDb(FakeDb):
    """The listener suite's fake Firestore, plus a research's event timeline."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.events: list = []
        self.timeline: list = []

    def _route(self, path):
        if len(path) == 5 and path[-1] == "pipeline_events":
            return _EventsCol(self, path)
        return super()._route(path)


class _ClosedTab:
    """A research tab after the login command closed Chrome."""

    def is_closed(self):
        return True


def _in_a_thread(coro_factory):
    """Run one of the pipeline's own coroutines to its end on a loop of its own
    (the caller is a sync hook inside `run_pipeline`); return what it raised."""
    out = {}

    def _t():
        try:
            out["ret"] = asyncio.run(coro_factory())
        except BaseException as e:  # noqa: BLE001 — the raise IS the result
            out["exc"] = e
    th = threading.Thread(target=_t)
    th.start()
    th.join(30)
    assert not th.is_alive(), "the pipeline site never returned"
    return out.get("exc")


def _p2_sweep_raise():
    """⭐ The REAL phase-2 round-robin, one agent whose tab the login closed."""
    return _in_a_thread(lambda: research.poll_all_agents_round_robin(
        {"ChatGPT": {"page": _ClosedTab(), "url": "https://chatgpt.com/c/x",
                     "verified": True}},
        browser=None, cua_client=None))


def _p3_site_raise():
    """⭐ The REAL phase-3 site: the podcast step found the browser gone."""
    return research._p3_browser_gone("before the podcast could be downloaded")


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """One computer: its HOME (where the login marker lives), its queues, a
    fake Firestore holding the research, and worker 1's job queue."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    box = {}
    db = _EventsDb(box, research_docs={(UID, RID): {"status": "ongoing",
                                                    "backendRunId": RUN}})
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setattr(research, "load_paired_uid", lambda: UID)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    writes = []

    def _record(uid, rid, updates):
        writes.append((uid, rid, dict(updates)))
        return True
    monkeypatch.setattr(research, "_update_research_doc", _record)
    jobs = _Jobs(db.timeline)
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", jobs)
    monkeypatch.setattr(research, "_LOGIN_RESUME_WAITERS", {})
    monkeypatch.setattr(research, "LOGIN_RESUME_POLL_SEC", 0.01)
    monkeypatch.setattr(research, "WORKER_ID", 1)
    # The run's own edges, as the crash-card suite stubs them.
    monkeypatch.setattr(research, "resolve_api_key", lambda _k: "test-key")
    monkeypatch.setattr(research, "_capture_anthropic_attribution", lambda *a, **k: None)
    monkeypatch.setattr(research, "clear_clipboard", lambda *a, **k: None)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "init_tracks", lambda *a, **k: None)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)
    monkeypatch.setattr(research, "Browser", _FakeBrowser)
    monkeypatch.setattr(research, "_profile_dir", lambda *_a, **_k: tmp_path / "profile")
    monkeypatch.setattr(research, "_update_firestore_research", lambda *a, **k: None)

    def _setup(uid, rid, _loop, run_id=None):
        research._fb_uid, research._fb_research_id = uid, rid
    monkeypatch.setattr(research, "setup_firestore_run", _setup)

    async def _noop_dispatcher():
        return None
    monkeypatch.setattr(research, "run_input_dispatcher", _noop_dispatcher)
    cards = []
    monkeypatch.setattr(research, "fail_phase", lambda **kw: cards.append(kw))
    persisted = []
    monkeypatch.setattr(research, "_persist_pending_decision",
                        lambda payload: persisted.append(dict(payload)))
    controls = research._controls      # a Listener swaps in a fake one
    yield _Machine(tmp_path, db, writes, jobs, cards, persisted, monkeypatch)
    research._clear_login_marker()
    controls.reset()


class _Machine:
    def __init__(self, tmp_path, db, writes, jobs, cards, persisted, monkeypatch):
        self.tmp = tmp_path
        self.db = db
        self.writes = writes
        self.jobs = jobs
        self.cards = cards
        self.persisted = persisted
        self._mp = monkeypatch

    def run_dir(self, name=RUN):
        d = self.tmp / "queues" / name
        (d / "documents").mkdir(parents=True, exist_ok=True)
        return d

    def delivery(self, name=RUN):
        return json.loads((self.run_dir(name) / "delivery.json").read_text(encoding="utf-8"))

    async def run_until_interrupted(self, site, *, name=RUN, rid=RID, uid=UID):
        """Drive the REAL `run_pipeline` (a resume of `name`) until `site`
        raises inside its main `try` — the first thing it does is announce
        phase 0, and the hook raises what the site raised."""
        qd = self.run_dir(name)
        raised = []

        def _emit(evname, phase=None, **_kw):
            if evname == "phase_start" and phase == 0:
                exc = site()
                raised.append(exc)
                raise exc
        self._mp.setattr(research, "emit_event", _emit)
        await research.run_pipeline(
            topic="Grid storage", resume_dir=str(qd), uid=uid, research_id=rid,
            run_id=name, email="alice@example.com", api_key="test-key")
        assert raised and isinstance(raised[0], RuntimeError), (
            f"the site did not raise a login interrupt: {raised!r}")
        return qd

    def waiter(self, name=RUN):
        task = research._LOGIN_RESUME_WAITERS.get(name)
        assert task is not None, "no waiter was started for the paused run"
        return task

    def status_writes(self, rid=RID):
        return [w[2] for w in self.writes if w[1] == rid and "status" in w[2]]


async def _settle():
    """Let a `call_soon_threadsafe` enqueue land."""
    for _ in range(3):
        await asyncio.sleep(0)


def _dead_pid():
    import psutil
    dead = 999_999
    while psutil.pid_exists(dead):
        dead += 1
    return dead


def _age_marker(minutes, **fields):
    """The login marker, stamped `minutes` ago (and any field changed)."""
    p = research._login_marker_path()
    d = json.loads(p.read_text(encoding="utf-8"))
    d["ts"] = int((time.time() - minutes * 60) * 1000)
    d.update(fields)
    p.write_text(json.dumps(d), encoding="utf-8")


async def _verdict_within(task, seconds):
    """What the waiter decided within `seconds`, or "still waiting"."""
    try:
        return await asyncio.wait_for(asyncio.shield(task), seconds)
    except asyncio.TimeoutError:
        task.cancel()
        return "still waiting"


async def _continued_by_itself(machine):
    """The login pauses the run; the login finishes; the waiter resumes it."""
    research._write_login_marker()
    qd = await machine.run_until_interrupted(_p3_site_raise)
    research._clear_login_marker()
    assert await asyncio.wait_for(machine.waiter(), 5) == "resumed"
    await _settle()
    return qd


def _retry(monkeypatch, tmp_path, **held):
    """The card's Retry, through the REAL start listener. Its queue is a
    process of its own — a sibling worker's — unless `held` says what that
    process already holds (`deque_jobs`, `current_job`)."""
    lst = Listener(monkeypatch, tmp_path, owner=UID,
                   research_docs={(UID, RID): {"status": "ongoing",
                                               "backendRunId": RUN}}, **held)
    lst.feed(action="resume", uid=UID, submittedBy=UID, researchId=RID,
             backendRunId=RUN, email="alice@example.com")
    return lst


# ══ 1. the run continues by itself when the login finishes ═════════════
@pytest.mark.parametrize("site", [_p2_sweep_raise, _p3_site_raise],
                         ids=["phase2-sweep", "phase3-podcast"])
def test_a_run_the_login_paused_continues_when_the_login_finishes(machine, site):
    """⛔⛔ THE CHANGE. Against the code before it, the run stayed paused for
    good: nothing was started, and only a Retry put it back on the queue."""
    async def main():
        research._write_login_marker()          # --login is running
        qd = await machine.run_until_interrupted(site)
        assert machine.delivery()["status"] == "paused"
        task = machine.waiter()
        # While the login is still running, the run waits.
        for _ in range(20):
            await asyncio.sleep(0.01)
        assert not task.done() and machine.jobs.put == [], (
            "the run went back on the queue while the login still had the browser")
        research._clear_login_marker()          # --login exits
        assert await asyncio.wait_for(task, 5) == "resumed"
        await _settle()
        return qd
    qd = asyncio.run(main())
    assert len(machine.jobs.put) == 1
    job = machine.jobs.put[0]
    # ⭐ THE SAME JOB A RETRY PUTS ON THE QUEUE: from this run's checkpoint,
    # under this research, with the run's own email.
    assert job["resume_dir"] == str(qd)
    assert job["run_id"] == RUN and job["uid"] == UID and job["research_id"] == RID
    assert job["email"] == "alice@example.com"
    assert machine.delivery()["status"] == "ongoing"
    assert "loginPause" not in machine.delivery()
    assert machine.status_writes()[-1]["status"] == "ongoing"
    assert machine.status_writes()[-1]["assignedWorker"] == 1


def test_a_login_that_was_killed_lets_the_run_go_on(machine):
    """⭐ A --login killed before it could clear its marker: the marker names a
    process that is gone, so the login is over (`_login_interrupt_active`)."""
    async def main():
        research._write_login_marker()
        await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        p = research._login_marker_path()
        data = json.loads(p.read_text(encoding="utf-8"))
        import psutil
        dead = 999_999
        while psutil.pid_exists(dead):
            dead += 1
        data["pid"] = dead
        p.write_text(json.dumps(data), encoding="utf-8")
        assert await asyncio.wait_for(task, 5) == "resumed"
        await _settle()
    asyncio.run(main())
    assert len(machine.jobs.put) == 1


# ══ 1b. a login left open a long time ══════════════════════════════════
def test_a_login_still_open_after_30_minutes_keeps_the_run_waiting(machine):
    """⛔⛔ Found in review (09-30). The marker's 30-minute cap is for a login
    that was killed and left its marker behind, and it applied even while the
    login's process was alive. So a login left open longer — a Cloudflare loop
    worked through by hand, a terminal left at "add another profile?" — counted
    as finished, and the run was started again on the profile the login window
    still had open."""
    async def main():
        research._write_login_marker()          # it names this live process
        await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        _age_marker(31)
        return await _verdict_within(task, 1)
    assert asyncio.run(main()) == "still waiting"
    assert machine.jobs.put == []


def test_a_marker_that_names_no_process_keeps_the_30_minute_cap(machine):
    """⭐ ACCEPT POLARITY. A marker no process vouches for (an older login
    command wrote no pid) is believed for 30 minutes, as before."""
    async def main():
        research._write_login_marker()
        await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        _age_marker(31, pid=0)
        return await _verdict_within(task, 5)
    assert asyncio.run(main()) == "resumed"


def test_a_live_login_is_believed_for_12_hours_not_for_ever(machine):
    """⭐ The bound on a live process: after 12 hours the number more likely
    belongs to another program (a killed login's pid given out again), and the
    run must not wait on it for good."""
    async def main():
        research._write_login_marker()
        await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        _age_marker(13 * 60)
        return await _verdict_within(task, 5)
    assert asyncio.run(main()) == "resumed"


# ══ 2. the card says so ════════════════════════════════════════════════
def test_the_card_says_the_run_continues_by_itself(machine):
    """⛔ The card used to say "Tap Retry after login". Retry and Stop stay:
    the intent still carries the Retry, and the Stop note is kept."""
    async def main():
        research._write_login_marker()
        await machine.run_until_interrupted(_p3_site_raise)
    asyncio.run(main())
    assert len(machine.cards) == 1
    card = machine.cards[0]
    assert card["error"] == "Paused by the login command"
    assert card["reason"] == research.LOGIN_PAUSE_CONTINUES_COPY
    assert "continues by itself" in card["reason"]
    assert "When the login command finishes" in card["reason"]
    assert "Note: the Stop button ends the run instead." in card["reason"]
    assert card["intent"] == "crash_login_interrupt"
    assert any(a.get("id") == "retry" or a.get("command", {}).get("action")
               == "resume_from_checkpoint"
               for a in research._alert_actions_for("crash_login_interrupt", 3, None))


def test_a_run_with_no_record_keeps_asking_for_retry(machine):
    """⭐ ACCEPT POLARITY. A run with nothing to resume it under (no research
    record — a run from the terminal) has no waiter, so its card must not
    promise one."""
    async def main():
        research._write_login_marker()
        await machine.run_until_interrupted(_p3_site_raise, uid=None, rid=None)
    asyncio.run(main())
    assert machine.cards[0]["reason"].startswith(
        "Login closed the research browser. Tap Retry after login")
    assert research._LOGIN_RESUME_WAITERS == {}


# ══ 3. every worker resumes its own run ════════════════════════════════
def test_each_worker_resumes_its_own_run(machine, monkeypatch):
    """⛔⛔ Two workers, each with a run the login paused. The queue and the
    worker id are each worker's own and are taken at the pause; a waiter that
    read them when the login finished would put both runs on one worker."""
    run_b, rid_b = "Tidal_power_20260930_120500", "chat_1759200000000_2"
    machine.db.research_docs[(UID, rid_b)] = {"status": "ongoing", "backendRunId": run_b}
    jobs_2 = _Jobs()

    async def main():
        research._write_login_marker()
        await machine.run_until_interrupted(_p2_sweep_raise)            # worker 1
        monkeypatch.setattr(research, "WORKER_ID", 2)
        monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", jobs_2)
        await machine.run_until_interrupted(_p3_site_raise, name=run_b, rid=rid_b)
        t1, t2 = machine.waiter(), machine.waiter(run_b)
        research._clear_login_marker()
        assert await asyncio.wait_for(asyncio.gather(t1, t2), 5) == ["resumed", "resumed"]
        await _settle()
    asyncio.run(main())
    assert [j["run_id"] for j in machine.jobs.put] == [RUN]
    assert [j["run_id"] for j in jobs_2.put] == [run_b]
    assert machine.status_writes(RID)[-1]["assignedWorker"] == 1
    assert machine.status_writes(rid_b)[-1]["assignedWorker"] == 2


# ══ 4. a person's word wins ════════════════════════════════════════════
def test_a_stop_while_it_waits_wins(machine):
    """⛔⛔ Stop on a paused run writes the record's status; the waiter must
    read it and leave the run stopped — never flip it back to ongoing."""
    async def main():
        research._write_login_marker()
        await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        machine.db.research_docs[(UID, RID)]["status"] = "stopped"   # Stop pressed
        research._clear_login_marker()
        assert await asyncio.wait_for(task, 5) == "stopped"
        await _settle()
    asyncio.run(main())
    assert machine.jobs.put == []
    assert machine.status_writes() == []
    assert machine.delivery()["status"] == "paused"


def test_a_stop_sentinel_on_disk_wins(machine):
    async def main():
        research._write_login_marker()
        qd = await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        (qd / ".stop").touch()
        research._clear_login_marker()
        assert await asyncio.wait_for(task, 5) == "stopped"
    asyncio.run(main())
    assert machine.jobs.put == []


def test_a_pause_the_person_asked_for_wins(machine):
    async def main():
        research._write_login_marker()
        qd = await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        (qd / ".pause").write_text("pause", encoding="utf-8")
        research._clear_login_marker()
        assert await asyncio.wait_for(task, 5) == "paused"
    asyncio.run(main())
    assert machine.jobs.put == []


def test_a_research_deleted_while_it_waits_is_not_resumed(machine):
    async def main():
        research._write_login_marker()
        await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        del machine.db.research_docs[(UID, RID)]
        research._clear_login_marker()
        assert await asyncio.wait_for(task, 5) == "deleted"
    asyncio.run(main())
    assert machine.jobs.put == []
    assert machine.status_writes() == []


def test_a_retry_before_the_login_finishes_is_the_only_resume(machine, monkeypatch, tmp_path):
    """⛔⛔ Retry pressed while the login still runs goes through the REAL start
    listener and resumes the run. When the login then finishes, the waiter
    must not resume it a second time."""
    async def main():
        research._write_login_marker()
        await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        # The Retry: the web writes an action:"resume" queue document.
        lst = Listener(monkeypatch, tmp_path, owner=UID,
                       research_docs={(UID, RID): {"status": "ongoing",
                                                   "backendRunId": RUN}})
        lst.feed(action="resume", uid=UID, submittedBy=UID, researchId=RID,
                 backendRunId=RUN, email="alice@example.com")
        assert len(lst.enqueued) == 1, "the Retry itself did not resume the run"
        research._clear_login_marker()
        assert await asyncio.wait_for(task, 5) == "moved_on"
        await _settle()
        return lst
    lst = asyncio.run(main())
    assert len(lst.enqueued) + len(machine.jobs.put) == 1


def test_a_waiter_does_not_take_a_later_pause_that_is_not_its_own(machine, monkeypatch):
    """⛔⛔ THE TOKEN. On a machine with two workers the Retry can be taken by
    the OTHER worker, and if the login closes that attempt's browser too, the
    run pauses again — with that worker's waiter. The first waiter then finds
    the run paused; without the token it resumes it a second time.

    ⭐ THE ORDER IS FIXED, not left to two pollers: worker 1's waiter checks
    first, alone, and worker 2's waiter is started after it (from the plan its
    pause made — the real `_login_auto_resume_plan`, observed, not replaced)."""
    jobs_2 = _Jobs()
    plans = []
    real_plan = research._login_auto_resume_plan

    def _observed(*a, **k):
        plans.append(real_plan(*a, **k))
        return plans[-1]
    monkeypatch.setattr(research, "_login_auto_resume_plan", _observed)

    async def main():
        research._write_login_marker()
        qd = await machine.run_until_interrupted(_p3_site_raise)
        # Worker 1's waiter lives in worker 1's process: its registry, not ours.
        w1 = research._LOGIN_RESUME_WAITERS.pop(RUN)
        # The Retry, taken by worker 2 — the listener's own helper.
        assert research._resume_from_checkpoint(
            qd, uid=UID, research_id=RID, run_id=RUN, email="", job_queue=jobs_2,
            loop=asyncio.get_running_loop(), worker_id=2)
        await _settle()
        # Worker 2 runs it; the login closes its browser as well.
        monkeypatch.setattr(research, "WORKER_ID", 2)
        monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", jobs_2)
        await machine.run_until_interrupted(_p3_site_raise)
        research._LOGIN_RESUME_WAITERS.pop(RUN).cancel()   # started again below
        research._clear_login_marker()
        v1 = await asyncio.wait_for(w1, 5)
        await _settle()
        assert machine.jobs.put == [] and len(jobs_2.put) == 1, (
            "worker 1's waiter resumed a pause that was worker 2's")
        v2 = await asyncio.wait_for(research._arm_login_auto_resume(plans[-1]), 5)
        await _settle()
        return v1, v2
    assert asyncio.run(main()) == ("moved_on", "resumed")
    assert machine.jobs.put == []
    assert len(jobs_2.put) == 2      # the Retry, then the resume after the login


def test_a_later_pause_of_another_kind_is_not_the_login_pause(machine):
    """⭐ A resume ends the login pause, token and all. A later pause of the
    run (the person's Pause at a phase boundary writes `paused` again) is not
    one an old waiter may take."""
    async def main():
        research._write_login_marker()
        qd = await machine.run_until_interrupted(_p3_site_raise)
        task = machine.waiter()
        # The Retry resumes it (worker 1, the listener's own helper)…
        assert research._resume_from_checkpoint(
            qd, uid=UID, research_id=RID, run_id=RUN, email="", job_queue=machine.jobs,
            loop=asyncio.get_running_loop(), worker_id=1)
        await _settle()
        # …and the run later pauses at a phase boundary: `update_delivery`
        # merges the new status into the file it finds.
        d = machine.delivery()
        d.update({"status": "paused"})
        (qd / "delivery.json").write_text(json.dumps(d), encoding="utf-8")
        research._clear_login_marker()
        return await asyncio.wait_for(task, 5)
    assert asyncio.run(main()) == "moved_on"
    assert len(machine.jobs.put) == 1


# ══ 4b. a Retry after the run already continued by itself ══════════════
def test_a_retry_after_the_run_continued_by_itself_is_not_a_second_resume(
        machine, monkeypatch, tmp_path):
    """⛔⛔ Found in review (09-30). The login finished and the run went back on
    worker 1's queue — where it can wait hours behind another run — while its
    card and Retry stayed up. A Retry pressed then went to an idle sibling (the
    listener below has a queue of its own), which started the run at once, and
    worker 1 later ran its own copy too: two browsers on one run folder."""
    async def main():
        await _continued_by_itself(machine)
        return _retry(monkeypatch, tmp_path)
    lst = asyncio.run(main())
    assert len(machine.jobs.put) == 1
    assert lst.enqueued == [], "the same run was put on a queue a second time"
    assert lst.writes == [], "the refused Retry must leave the record alone"
    assert lst.incoming == ["incoming"], "the refused Retry must not replay at the next start"


def test_a_retry_while_this_worker_already_has_the_run_queued_is_refused(
        machine, monkeypatch, tmp_path):
    """⛔ The same on the worker that holds the waiting job, whatever the disk
    says: a second resume of a run already on its queue is a second browser."""
    qd = machine.run_dir()
    (qd / "delivery.json").write_text(json.dumps({"status": "paused"}), encoding="utf-8")
    waiting = {"run_id": RUN, "uid": UID, "research_id": RID, "resume_dir": str(qd)}
    lst = _retry(monkeypatch, tmp_path, deque_jobs=[waiting])
    assert lst.enqueued == []


def test_a_retry_while_this_worker_is_letting_go_of_the_run_goes_through(
        machine, monkeypatch, tmp_path):
    """⭐ ACCEPT POLARITY. A run that has just paused is still its worker's
    `current_job` for up to ten seconds (the worker looks in on its run every
    ten). A Retry on its card then is the only resume and must go through."""
    qd = machine.run_dir()
    (qd / "delivery.json").write_text(json.dumps({"status": "paused"}), encoding="utf-8")
    just_paused = {"run_id": RUN, "uid": UID, "research_id": RID, "resume_dir": str(qd)}
    lst = _retry(monkeypatch, tmp_path, current_job=just_paused)
    assert len(lst.enqueued) == 1


@pytest.mark.parametrize("gone", ["pid-gone", "pid-reused"])
def test_a_note_left_by_a_worker_that_is_gone_does_not_block_a_retry(
        machine, monkeypatch, tmp_path, gone):
    """⭐ ACCEPT POLARITY. The queued job lives in the memory of the worker that
    queued it; after a restart it is gone, and the note on disk must not keep
    the run's Retry refused. A number now held by a process younger than the
    note is not that worker either."""
    async def main():
        qd = await _continued_by_itself(machine)
        d = machine.delivery()
        note = d["loginResumeQueued"]
        assert note["pid"] == os.getpid()
        if gone == "pid-gone":
            note["pid"] = _dead_pid()
        else:
            note["at"] = 1000                   # 1970: before this process began
        (qd / "delivery.json").write_text(json.dumps(d), encoding="utf-8")
        return _retry(monkeypatch, tmp_path)
    lst = asyncio.run(main())
    assert len(lst.enqueued) == 1


def test_the_resumed_run_spends_the_note(machine, monkeypatch, tmp_path):
    """⭐ ACCEPT POLARITY. Once worker 1 starts the queued job (the REAL
    `run_pipeline`, resuming), the note is spent: when the login closes this
    attempt's browser too, a Retry on the new card must go through."""
    async def main():
        await _continued_by_itself(machine)
        research._write_login_marker()
        await machine.run_until_interrupted(_p3_site_raise)
        assert "loginResumeQueued" not in machine.delivery()
        lst = _retry(monkeypatch, tmp_path)
        research._clear_login_marker()
        assert await asyncio.wait_for(machine.waiter(), 5) == "moved_on"
        return lst
    lst = asyncio.run(main())
    assert len(lst.enqueued) == 1
    assert len(machine.jobs.put) == 1


def test_the_card_comes_down_when_the_run_continues_by_itself(machine, monkeypatch):
    """⛔ Found in review (09-30). The login card, Retry and all, stayed up
    until the resumed job started — hours, if the worker was busy — over a run
    already queued. It comes down as the job is queued: the record's copy of
    the card goes in the same write that says "ongoing", and the research's
    timeline gets what the resumed start sends (resumed, then the phase
    starting over), BEFORE the job reaches the queue. ⛔ Written to the run's
    own research, not to whichever run this worker's globals name by then."""
    from google.cloud.firestore import DELETE_FIELD

    async def main():
        research._write_login_marker()
        qd = await machine.run_until_interrupted(_p3_site_raise)
        # The worker has meanwhile started somebody else's run.
        monkeypatch.setattr(research, "_fb_uid", "uid-bob")
        monkeypatch.setattr(research, "_fb_research_id", "chat_1759200000000_9")
        research._clear_login_marker()
        assert await asyncio.wait_for(machine.waiter(), 5) == "resumed"
        await _settle()
        return qd
    qd = asyncio.run(main())
    flip = machine.status_writes()[-1]
    assert flip["status"] == "ongoing" and flip["pendingDecision"] is DELETE_FIELD
    phase = research.detect_resume_phase(qd)[0]
    assert 0 <= phase <= 3
    assert [(e["type"], e.get("phase"), e["uid"], e["rid"]) for e in machine.db.events] == [
        ("pipeline_resumed", phase, UID, RID), ("phase_restart", phase, UID, RID)]
    assert machine.db.events[1]["data"]["full"] is True
    assert machine.db.events[0]["seq"] < machine.db.events[1]["seq"]
    assert machine.db.timeline == [("event", "pipeline_resumed"),
                                   ("event", "phase_restart"), ("job", RUN)]


# ══ 5. a human check the login clears ══════════════════════════════════
class _HvTab:
    def __init__(self):
        self.closed = False

    def is_closed(self):
        return self.closed


class _HvBrowser:
    def __init__(self):
        self.page = _HvTab()
        self.context = None


@pytest.fixture
def cloudflare(machine, monkeypatch):
    """NotebookLM behind Cloudflare's check; the person runs --login once the
    card is up (the login closes Chrome)."""
    browser = _HvBrowser()

    async def _detect(page, platform, label):
        return (False, "") if page.is_closed() else (True, "Cloudflare challenge")
    monkeypatch.setattr(research, "detect_human_verification", _detect)
    _real_sleep = asyncio.sleep

    async def _fast(_s, *a, **k):
        await _real_sleep(0.001)
    monkeypatch.setattr(research.asyncio, "sleep", _fast)

    def _card_up(payload):
        machine.persisted.append(dict(payload))
        research._write_login_marker()      # the person runs --login …
        browser.page.closed = True          # … which closes Chrome
    monkeypatch.setattr(research, "_persist_pending_decision", _card_up)
    return browser


def test_the_human_check_wait_gives_way_to_the_login(machine, cloudflare):
    """⛔⛔ Before this, the wait sat out its ten minutes on a page the login had
    closed, then skipped NotebookLM. Now it raises the login interrupt, and
    the gate's own retry does not swallow it."""
    exc = _in_a_thread(lambda: research.check_hv_gate(
        cloudflare, object(), "notebooklm", "NotebookLM", phase=3))
    assert isinstance(exc, research.LoginInterrupted), exc
    assert "(login interrupt)" in str(exc)
    assert research._runtime.last_failure_kind == "login_interrupt"


def test_a_run_parked_on_the_human_check_continues_after_the_login(machine, cloudflare):
    """⭐ The owner's case end to end: parked on Cloudflare's card, --login,
    and the run continues by itself when the login finishes."""
    def _hv_site():
        return _in_a_thread(lambda: research.check_hv_gate(
            cloudflare, object(), "notebooklm", "NotebookLM", phase=3))

    async def main():
        await machine.run_until_interrupted(_hv_site)
        task = machine.waiter()
        research._clear_login_marker()
        assert await asyncio.wait_for(task, 5) == "resumed"
        await _settle()
    asyncio.run(main())
    assert machine.cards[0]["reason"] == research.LOGIN_PAUSE_CONTINUES_COPY
    assert len(machine.jobs.put) == 1


def test_the_human_check_card_says_the_login_clears_it(machine, cloudflare):
    """The wait's own card (Cloudflare, Skip-only) adds the one line."""
    _in_a_thread(lambda: research.check_hv_gate(
        cloudflare, object(), "notebooklm", "NotebookLM", phase=3))
    msg = machine.persisted[0]["message"]
    assert msg.endswith(research.HV_LOGIN_LINE)
    assert "run superresearch --login" in msg
    assert "the run continues by itself when you finish" in msg
    # The owner's wording before it is kept.
    assert "It can't be cleared from here — trying only makes Cloudflare ask harder." in msg
    assert "if it clears on its own, the run resumes automatically." in msg


@pytest.mark.parametrize("reason", ["Cloudflare challenge", "reCAPTCHA"])
def test_every_hands_off_human_check_card_adds_the_line(reason):
    title, details = research._hv_fail_copy("claude", reason)
    assert details.endswith(" Or run superresearch --login, clear it in the window "
                            "that opens, and the run continues by itself when you finish.")
    assert "Skip Claude for this run" in details


# ══ 6. a login that is not run changes nothing ═════════════════════════
def test_a_login_aborted_at_continue_anyway_touches_nothing(machine, monkeypatch, capsys):
    """⭐ "Continue anyway? No" — no marker, no browser closed, as today. And
    the warning before the question says what now happens to the runs."""
    closed = []
    monkeypatch.setattr(research, "_backend_is_running", lambda: True)

    async def _no(*_a, **_k):
        return False
    monkeypatch.setattr(research, "_ask_yes_no", _no)

    async def _close(*a, **k):
        closed.append(a)
        return {}
    monkeypatch.setattr(research, "_close_profile_browser_neatly", _close)
    monkeypatch.setattr(research.tm, "tm_emit", lambda *a, **k: None)
    asyncio.run(research.run_login())
    assert not research._login_marker_path().exists()
    assert closed == []
    out = capsys.readouterr().out
    assert "continues by itself" in out
    assert "Retry on the alert" not in out
