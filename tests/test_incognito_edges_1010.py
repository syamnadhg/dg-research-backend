"""Two loose ends an incognito run left on the research computer (wave 10.10).

⛔⛔ 1. A TERMINAL `--resume` RAN IT WITH NOTHING KEEPING ITS RECORD ALIVE. An
incognito run's record carries a fuse, and the only thing that renews it while
the run waits is the lease — which runs inside `--serve` and nowhere else. A run
resumed from the terminal could lose its record halfway through and write into
nothing for hours. Boot recovery already ends such a run instead of parking it;
the terminal now refuses it in one plain sentence.

⛔⛔ 2. A CANCELLED INCOGNITO RUN WAITING IN THIS WORKER'S QUEUE WARNED EVERY
HOUR. The lease kept renewing a record the web had already deleted, and every
renewal failed with a WARN. Worse, the job stayed in the queue: when its turn
came, the flip found no record and the worker would "proceed, as before" into a
paid run writing into nothing. A not-found record is now said once, its waiting
job leaves the queue, and a running one is not written to again.

Both are EXECUTED: `main()` runs with only its machine-wide side effects faked,
and the lease runs against a fake Firestore that answers the way the real one
does — `google.api_core.exceptions.NotFound`.
"""
import asyncio
import collections
import json
import sys

import pytest

import research

INCOG = "incog_1758400000000_2"
INCOG2 = "incog_1758400000001_3"
CHAT = "chat_1758400000000_2"
UID = "uid-owner"


# ══ 1. `--resume` of an incognito folder ══════════════════════════════════

def _main(monkeypatch, tmp_path, folder):
    """Run the real `main()` for `--resume <folder>`. Returns (exit code or
    None, the pipeline calls made, what was printed)."""
    calls = []

    async def _pipeline(**kw):
        calls.append(kw)
        return "done"

    for name in ("_install_stdlib_log_bridge", "_install_crash_log_hook",
                 "_migrate_state_to_home", "_warn_if_restart_pending",
                 "_harden_owner_only_paths", "_migrate_legacy_api_keys"):
        monkeypatch.setattr(research, name, lambda *a, **k: None)
    monkeypatch.setattr(research.tm, "flush_in_background", lambda *a, **k: None)
    monkeypatch.setattr(research, "_SUPERVISOR_ENV_FILE_DEFAULT_PATH",
                        tmp_path / "no-such.env")
    monkeypatch.setattr(research, "run_pipeline_captured", _pipeline)
    monkeypatch.setattr(research, "_cli_mode", research._cli_mode)
    monkeypatch.setattr(sys, "argv", ["research.py", "--resume", str(folder)])
    code = None
    try:
        research.main()
    except SystemExit as e:
        code = e.code
    return code, calls


def _queue(tmp_path, name, rid=None):
    d = tmp_path / "queues" / name
    d.mkdir(parents=True)
    (d / "delivery.json").write_text(json.dumps({"status": "paused"}), encoding="utf-8")
    if rid:
        (d / "owner.json").write_text(json.dumps({"uid": UID, "researchId": rid}),
                                      encoding="utf-8")
    return d


def test_a_terminal_resume_of_an_incognito_run_is_refused(monkeypatch, tmp_path, capsys):
    """⛔⛔ THE FIX, through the real dispatcher: nothing runs, the command
    fails, and the reason is one sentence."""
    folder = _queue(tmp_path, "incognito_1758400000000_2_20260923_101500", INCOG)
    code, calls = _main(monkeypatch, tmp_path, folder)
    out = capsys.readouterr().out
    assert calls == [], "an incognito run was resumed from the terminal"
    assert code == 1
    said = [ln for ln in out.splitlines() if "incognito" in ln]
    assert len(said) == 1 and "can't be resumed from the terminal" in said[0], out


def test_an_ordinary_terminal_resume_still_runs(monkeypatch, tmp_path, capsys):
    """⭐ ACCEPT POLARITY: the refusal is for runs that keep nothing only."""
    folder = _queue(tmp_path, "a_topic_20260923_101500", CHAT)
    code, calls = _main(monkeypatch, tmp_path, folder)
    assert code is None
    assert len(calls) == 1 and calls[0]["resume_dir"] == str(folder)


def _serve_resume(tmp_path, name):
    """The serve API's resume route — the real closure `run_server` builds."""
    import types
    code = next(c for c in research.run_server.__code__.co_consts
                if isinstance(c, types.CodeType) and c.co_name == "resume_run")

    async def _go():
        q = asyncio.Queue()
        cells = {"queues_root": tmp_path / "queues", "_job_queue": q,
                 "JSONResponse": lambda body, status=200: ("json", status, body)}
        route = types.FunctionType(code, research.__dict__, "resume_run", None,
                                   tuple(types.CellType(cells[v]) for v in code.co_freevars))
        return await route(name, {}), list(q._queue)
    return asyncio.run(_go())


def test_the_serve_apis_resume_of_an_incognito_run_is_refused_too(tmp_path):
    """⛔ THE SAME DOOR BY ANOTHER NAME: the route enqueues a job with no
    account on it, so no lease would keep the record alive either."""
    name = "incognito_1758400000000_2_20260923_101500"
    _queue(tmp_path, name, INCOG)
    answer, queued = _serve_resume(tmp_path, name)
    assert queued == [], "an incognito run was queued to resume"
    assert answer[:2] == ("json", 409)
    assert "can't be resumed here" in answer[2]["error"]


def test_the_serve_apis_ordinary_resume_still_queues(tmp_path):
    _queue(tmp_path, "a_topic_20260923_101500", CHAT)
    answer, queued = _serve_resume(tmp_path, "a_topic_20260923_101500")
    assert answer["status"] == "queued_resume"
    assert len(queued) == 1 and queued[0]["resume_dir"].endswith("a_topic_20260923_101500")


def test_the_folder_is_known_by_its_record_or_by_its_name(tmp_path):
    """Two witnesses, either enough — because the answer only ever HOLDS
    SOMETHING BACK. The record is `owner.json`; the name covers a run whose
    `owner.json` write failed."""
    by_record = _queue(tmp_path, "renamed_by_hand", INCOG)
    by_name = _queue(tmp_path, "incognito_1758400000000_2_20260923_101500")
    ordinary = _queue(tmp_path, "a_topic_20260923_101500", CHAT)
    nothing = _queue(tmp_path, "a_topic_20260923_101501")
    assert research._queue_dir_keeps_nothing(by_record)
    assert research._queue_dir_keeps_nothing(by_name)
    assert not research._queue_dir_keeps_nothing(ordinary)
    assert not research._queue_dir_keeps_nothing(nothing)
    assert not research._queue_dir_keeps_nothing(None)


def test_the_name_rule_is_the_mint_s_own_shape():
    """⛔ PARITY WITH `_mint_run_id`: if the mint changes shape, the name
    witness must not silently stop matching."""
    from datetime import datetime
    name = research._mint_run_id("a private subject", INCOG,
                                 now=datetime(2026, 9, 23, 10, 15, 0))
    assert research._INCOGNITO_RUN_DIR_RE.fullmatch(name), name
    ordinary = research._mint_run_id("incognito", CHAT,
                                     now=datetime(2026, 9, 23, 10, 15, 0))
    assert not research._INCOGNITO_RUN_DIR_RE.fullmatch(ordinary), ordinary


# ══ 2. the lease forgets a record the web deleted ═════════════════════════

class _NotFoundRef:
    def __init__(self, world, path):
        self.world, self.path = world, path

    def collection(self, name):
        return _NotFoundRef(self.world, f"{self.path}/{name}")

    def document(self, name):
        return _NotFoundRef(self.world, f"{self.path}/{name}")

    def update(self, data):
        import google.api_core.exceptions as gax
        self.world.writes.append(self.path)
        self.world.payloads.append(dict(data))
        if self.path in self.world.gone:
            raise gax.NotFound("No document to update: " + self.path)
        if self.path in self.world.down:
            raise gax.ServiceUnavailable("the network blinked")


class _World:
    def __init__(self):
        self.writes, self.payloads, self.gone, self.down = [], [], set(), set()

    def collection(self, name):
        return _NotFoundRef(self, name)


def _record(rid, uid=UID):
    return f"users/{uid}/researches/{rid}"


def _job(rid, uid=UID):
    return {"uid": uid, "research_id": rid, "run_id": "r", "topic": "t"}


@pytest.fixture()
def lease(monkeypatch):
    w = _World()
    w.lines = []
    w.shed = []
    monkeypatch.setattr(research, "_firebase_db", w)
    monkeypatch.setattr(research, "_be_payload", lambda d: dict(d))
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what=None, **k: op())
    monkeypatch.setattr(research, "_INCOGNITO_DOCS_WRITTEN", {})
    monkeypatch.setattr(research, "_INCOGNITO_LEASE_GONE", set())
    monkeypatch.setattr(research, "_shed_from_pending_snapshot",
                        lambda q: w.shed.append(list(q._queue)))
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: w.lines.append((level, msg)))

    def hold(current=None, queued=()):
        q = asyncio.Queue()
        q._queue = collections.deque(queued)
        monkeypatch.setitem(research._QUEUE_STATE, "current_job", current)
        monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", q)
        return q
    w.hold = hold
    return w


def test_a_waiting_run_whose_record_is_gone_leaves_the_queue(lease):
    """⛔⛔ THE FIX. Its record deleted by the web, the waiting job goes — and
    everyone else's work stays, in order."""
    lease.gone.add(_record(INCOG2))
    q = lease.hold(current=_job(CHAT),
                   queued=[_job(CHAT, "other"), _job(INCOG2), _job(INCOG)])
    res = research._renew_incognito_leases()
    assert [j["research_id"] for j in q._queue] == [CHAT, INCOG], (
        "the gone job stayed queued, or somebody else's work went with it")
    assert res == {"renewed": 1, "documents": 0, "failed": 1}
    assert lease.shed and all(j["research_id"] != INCOG2 for j in lease.shed[-1]), (
        "the snapshot on disk still describes the removed job")


def test_it_is_said_once_not_every_hour(lease):
    """⛔⛔ THE NOISE: one INFO line on the tick that finds it, and nothing —
    no write, no WARN — on every tick after."""
    lease.gone.add(_record(INCOG))
    lease.hold(current=_job(INCOG))
    research._renew_incognito_leases()
    research._renew_incognito_leases()
    research._renew_incognito_leases()
    assert lease.writes == [_record(INCOG)], f"asked again: {lease.writes}"
    said = [m for _lv, m in lease.lines if "gone" in m]
    assert len(said) == 1, said
    assert not [m for lv, m in lease.lines if lv == "WARN"], lease.lines


def test_the_running_run_is_not_touched_only_forgotten(lease):
    """The job in hand is the pipeline's to end; the lease only stops writing
    to its record."""
    lease.gone.add(_record(INCOG))
    q = lease.hold(current=_job(INCOG), queued=[_job(CHAT)])
    research._renew_incognito_leases()
    assert research._QUEUE_STATE["current_job"]["research_id"] == INCOG
    assert [j["research_id"] for j in q._queue] == [CHAT]
    assert lease.shed == [], "nothing left the queue, so the snapshot is not rewritten"


def test_a_network_failure_is_still_retried_next_hour(lease):
    """⭐ ACCEPT POLARITY. An unreachable record is not a deleted one: it keeps
    its job, keeps its WARN, and is asked again on the next tick."""
    lease.down.add(_record(INCOG2))
    q = lease.hold(current=None, queued=[_job(INCOG2)])
    research._renew_incognito_leases()
    research._renew_incognito_leases()
    assert [j["research_id"] for j in q._queue] == [INCOG2]
    assert lease.writes == [_record(INCOG2)] * 2
    assert len([m for lv, m in lease.lines if lv == "WARN"]) == 2


def test_the_memory_does_not_outlive_the_run(lease):
    """⛔ Bounded: once the run is no longer held, it is forgotten — the set
    must not grow for the life of the process."""
    lease.gone.add(_record(INCOG))
    lease.hold(current=_job(INCOG))
    research._renew_incognito_leases()
    assert research._INCOGNITO_LEASE_GONE == {(UID, INCOG)}
    lease.hold(current=None)
    research._renew_incognito_leases()
    assert research._INCOGNITO_LEASE_GONE == set()


def test_a_live_record_is_still_renewed_with_its_fuse(lease):
    """⭐ The renewal itself did not change: an update that carries the fuse
    and nothing else."""
    lease.hold(current=_job(INCOG))
    res = research._renew_incognito_leases()
    assert res["renewed"] == 1
    assert lease.writes == [_record(INCOG)]
    assert [set(p) for p in lease.payloads] == [{"expireAt"}]
