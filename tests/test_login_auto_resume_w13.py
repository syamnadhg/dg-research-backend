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
import threading

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
    """One worker's job queue — what the resume put on it."""

    def __init__(self):
        self.put = []

    def put_nowait(self, job):
        self.put.append(job)

    def qsize(self):
        return 0


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
    db = FakeDb(box, research_docs={(UID, RID): {"status": "ongoing",
                                                 "backendRunId": RUN}})
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setattr(research, "load_paired_uid", lambda: UID)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-abcdef")
    writes = []

    def _record(uid, rid, updates):
        writes.append((uid, rid, dict(updates)))
        return True
    monkeypatch.setattr(research, "_update_research_doc", _record)
    jobs = _Jobs()
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
    the run paused; without the token it resumes it a second time."""
    jobs_2 = _Jobs()

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
        w2 = machine.waiter()
        research._clear_login_marker()
        return await asyncio.wait_for(asyncio.gather(w1, w2), 5)
    verdicts = asyncio.run(main())
    assert verdicts == ["moved_on", "resumed"]
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
