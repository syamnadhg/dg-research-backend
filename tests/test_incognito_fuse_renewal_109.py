"""The record of a run that keeps nothing does not burn down under the run.

⛔⛔ THE FUSE WAS LIT ONCE AND NEVER MOVED. The app stamps `expireAt` a day out
when it creates an incognito record, and until this change no write from the
research computer carried it forward. A run still alive a day later — parked at
a sign-in prompt nobody has answered yet, or waiting behind somebody else's run
— had its record swept by Firestore while it ran. After that every write here
failed, the reports piled up under a parent that was gone, and phase 5 found no
record to deliver. With the tab closed the machine is the only writer left, so
the machine is what has to keep a waiting run alive.

TWO HALVES, AND THE SECOND IS THE ONE THAT COVERS THE CASE:

  · every write this machine makes to the record carries the fuse forward —
    through BOTH seams, because nearly every status, phase and agent write goes
    through `_update_research_doc`, which never reached `_write_research_doc`;
  · and a WAIT WRITES NOTHING. `wait_if_paused` and `await_phase_decision` only
    sleep, and a queue does not move while the run ahead of it is waiting on a
    person. So each worker holds a lease: once an hour it re-lights the fuse on
    every incognito run it holds — the one it is running and the ones in its
    own queue — and on the reports it has written for them.

⭐ AN ORDINARY RUN WRITES EXACTLY WHAT IT WROTE BEFORE, and every section below
asserts that polarity first.

Every pin runs the real writer against a fake Firestore and reads what was
actually handed to it.
"""
import ast
import asyncio
import collections
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import research
from conftest import apply_firestore_update

UID = "uid-sharer"
OTHER = "uid-other-member"
INCOG = "incog_1758400000000_3"
INCOG2 = "incog_1758400000000_4"
CHAT = "chat_1758400000000_3"
NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)


def _assert_renewed(fuse, *, before, after):
    """A fuse written between `before` and `after`: a real timezone-aware
    timestamp, a day out, and under the rules' 48-hour ceiling."""
    assert isinstance(fuse, datetime), f"expireAt is a {type(fuse).__name__}"
    assert fuse.tzinfo is not None and fuse.utcoffset() is not None, "naive fuse"
    assert before + timedelta(hours=24) <= fuse <= after + timedelta(hours=24)
    assert fuse < after + timedelta(hours=48)


# ══ 1. the renewal itself ═════════════════════════════════════════════════

def test_an_ordinary_payload_comes_back_as_the_very_same_object():
    """⭐ ACCEPT POLARITY, and it is the compatibility claim: an ordinary record
    has no fuse and is written exactly as it was before this existed."""
    payload = {"status": "ongoing", "agents.claude.status": "running"}
    got = research._with_incognito_renewal(payload, CHAT, NOW)
    assert got is payload
    assert payload == {"status": "ongoing", "agents.claude.status": "running"}


def test_a_run_that_keeps_nothing_carries_its_fuse_a_day_out():
    payload = {"status": "ongoing"}
    got = research._with_incognito_renewal(payload, INCOG, NOW)
    assert got == {"status": "ongoing", "expireAt": NOW + timedelta(hours=24)}
    assert payload == {"status": "ongoing"}, "the caller's payload was changed"


def test_the_renewed_fuse_is_timezone_aware_and_under_the_ceiling():
    """⛔ Firestore TTL acts only on a timestamp, and the rules refuse anything
    past 48 hours — on the MERGED document, which after this write holds this."""
    before = datetime.now(timezone.utc)
    fuse = research._with_incognito_renewal({}, INCOG)["expireAt"]
    _assert_renewed(fuse, before=before, after=datetime.now(timezone.utc))


def test_a_caller_cannot_pull_the_fuse_out_of_the_write():
    """A payload that carries its own `expireAt` — a clear, or a stale value —
    is overruled: the record of a run that keeps nothing always leaves the
    write with a fuse a day out."""
    got = research._with_incognito_renewal({"expireAt": None}, INCOG, NOW)
    assert got["expireAt"] == NOW + timedelta(hours=24)


# ══ 2. both seams every record write goes through ═════════════════════════

class _Ref:
    def __init__(self, world, path):
        self.world, self.path = world, path

    def collection(self, name):
        return _Ref(self.world, f"{self.path}/{name}")

    def document(self, name):
        return _Ref(self.world, f"{self.path}/{name}")

    def set(self, data, merge=False):
        self.world.writes.append(("set", self.path, dict(data)))

    def update(self, data):
        if self.path in self.world.gone:
            self.world.writes.append(("update-refused", self.path, dict(data)))
            raise RuntimeError("404 NOT_FOUND: no document to update")
        self.world.writes.append(("update", self.path, dict(data)))


class _World:
    def __init__(self):
        self.writes = []
        self.gone = set()

    def collection(self, name):
        return _Ref(self, name)


def _record(rid, uid=UID):
    return f"users/{uid}/researches/{rid}"


@pytest.fixture()
def world(monkeypatch):
    w = _World()
    monkeypatch.setattr(research, "_firebase_db", w)
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_be_payload", lambda d: dict(d))
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what=None, **k: op())
    monkeypatch.setattr(research, "_INCOGNITO_DOCS_WRITTEN", {})
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", None)
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", None)
    w.lines = []
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: w.lines.append((level, msg)))
    return w


def test_an_ordinary_status_write_is_exactly_what_it_was(world):
    """⭐ ACCEPT POLARITY FIRST."""
    assert research._update_research_doc(UID, CHAT, {"status": "ongoing"}) is True
    assert world.writes == [("update", _record(CHAT), {"status": "ongoing"})]


def test_a_status_write_carries_the_fuse_forward(world):
    """⛔⛔ THE SEAM THE SPEC DID NOT NAME. Status, phase, agent and decision
    writes all go through `_update_research_doc`, which never reached
    `_write_research_doc` — renewing only there would have ridden on the rare
    link and source writes and missed nearly every write a run makes."""
    before = datetime.now(timezone.utc)
    assert research._update_research_doc(UID, INCOG, {"status": "ongoing"}) is True
    [(verb, path, payload)] = world.writes
    assert (verb, path) == ("update", _record(INCOG))
    assert payload["status"] == "ongoing"
    _assert_renewed(payload["expireAt"], before=before, after=datetime.now(timezone.utc))


def test_the_running_pipelines_own_writes_renew_it(world, monkeypatch):
    """⛔ THE CONSUMER, NOT THE SEAM: `_update_firestore_research` is what the
    pipeline calls for every status and every sign-in card it raises."""
    monkeypatch.setattr(research, "_fb_research_id", INCOG)
    research._update_firestore_research({"pendingDecision": {"kind": "login_required"}})
    [(verb, path, payload)] = world.writes
    assert (verb, path) == ("update", _record(INCOG))
    assert payload["pendingDecision"] == {"kind": "login_required"}
    assert payload["expireAt"].tzinfo is not None


@pytest.mark.parametrize("rid,verb", [(CHAT, "set"), (INCOG, "update")])
def test_the_set_merge_seam_renews_only_the_run_that_keeps_nothing(world, rid, verb):
    before = datetime.now(timezone.utc)
    assert research._set_research_doc(UID, rid, {"backendRunId": "r_1"}) is True
    [(got_verb, path, payload)] = world.writes
    assert (got_verb, path) == (verb, _record(rid))
    if rid == CHAT:
        assert payload == {"backendRunId": "r_1"}, "an ordinary record was handed a fuse"
    else:
        assert payload["backendRunId"] == "r_1"
        _assert_renewed(payload["expireAt"], before=before,
                        after=datetime.now(timezone.utc))


def test_the_merged_record_holds_the_new_fuse_not_the_old_one():
    """⛔ `ephemeralExpiryOk()` reads the MERGED document. A record created 20
    hours ago holds a fuse four hours out; after one ordinary-looking write from
    this machine it must hold one a day out, as a timestamp, under the ceiling."""
    created = datetime.now(timezone.utc) - timedelta(hours=20)
    record = {"status": "ongoing", "createdAt": 1, "expireAt": created + timedelta(hours=24)}
    calls = []

    class _Doc:
        def update(self, data):
            calls.append(dict(data))
            apply_firestore_update(record, data)

    before = datetime.now(timezone.utc)
    research._write_research_doc(_Doc(), {"agents": {"claude": {"status": "complete"}}}, INCOG)
    assert record["agents"]["claude"]["status"] == "complete"
    assert record["createdAt"] == 1
    _assert_renewed(record["expireAt"], before=before, after=datetime.now(timezone.utc))


def test_a_purged_record_is_still_not_brought_back(world):
    """⛔⛔ THE RENEWAL RIDES AN UPDATE, NEVER A CREATE. A record that is gone
    stays gone, fuse or no fuse."""
    world.gone.add(_record(INCOG))
    assert research._update_research_doc(UID, INCOG, {"status": "ongoing"}) is False
    assert research._set_research_doc(UID, INCOG, {"status": "ongoing"}) is False
    assert [verb for verb, _p, _d in world.writes] == ["update-refused", "update-refused"]


# ══ 3. what keeps a WAITING run alive: the lease ══════════════════════════

def _hold(monkeypatch, current=None, queued=()):
    """This worker running `current` with `queued` claimed into its own queue —
    the shape `_QUEUE_STATE` has in `--serve`."""
    q = asyncio.Queue()
    q._queue = collections.deque(queued)
    monkeypatch.setitem(research._QUEUE_STATE, "current_job", current)
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", q)


def _job(rid, uid=UID):
    return {"uid": uid, "research_id": rid, "run_id": "r"}


def test_what_a_worker_holds_is_its_running_run_then_its_queue(monkeypatch):
    _hold(monkeypatch, current=_job(INCOG),
          queued=[_job(CHAT), _job(INCOG2, OTHER), _job(INCOG)])
    assert research._incognito_runs_held() == [(UID, INCOG), (OTHER, INCOG2)]


def test_an_ordinary_run_is_never_held(monkeypatch):
    _hold(monkeypatch, current=_job(CHAT), queued=[_job(CHAT, OTHER)])
    assert research._incognito_runs_held() == []


def test_a_job_that_names_no_account_is_not_held(monkeypatch):
    """A resume-directory job carries no uid, so there is no record to write."""
    _hold(monkeypatch, current={"research_id": INCOG, "resume_dir": "/x"})
    assert research._incognito_runs_held() == []


def test_the_run_parked_at_a_sign_in_prompt_is_renewed(world, monkeypatch):
    """⛔⛔ THE CASE THIS EXISTS FOR. The pipeline is sleeping in a wait that
    writes nothing; the lease is the only write its record gets."""
    _hold(monkeypatch, current=_job(INCOG))
    before = datetime.now(timezone.utc)
    res = research._renew_incognito_leases()
    [(verb, path, payload)] = world.writes
    assert (verb, path) == ("update", _record(INCOG))
    assert set(payload) == {"expireAt"}, f"the lease wrote more than the fuse: {payload}"
    _assert_renewed(payload["expireAt"], before=before, after=datetime.now(timezone.utc))
    assert res == {"renewed": 1, "documents": 0, "failed": 0}


def test_a_run_waiting_in_this_workers_queue_is_renewed(world, monkeypatch):
    """⛔⛔ THE OTHER CASE: claimed, queue document already deleted, waiting
    behind an ordinary run — its record is the only thing left that says it
    exists, and nothing else writes it until the queue moves."""
    _hold(monkeypatch, current=_job(CHAT), queued=[_job(INCOG2, OTHER)])
    research._renew_incognito_leases()
    assert [(v, p) for v, p, _d in world.writes] == [("update", _record(INCOG2, OTHER))]


def test_an_ordinary_run_gets_no_lease_write_at_all(world, monkeypatch):
    """⭐ ACCEPT POLARITY: not an empty write, not a fuse — nothing."""
    _hold(monkeypatch, current=_job(CHAT), queued=[_job(CHAT, OTHER)])
    assert research._renew_incognito_leases() == {"renewed": 0, "documents": 0, "failed": 0}
    assert world.writes == []


def test_the_reports_it_wrote_are_renewed_with_the_record(world, monkeypatch):
    """⛔⛔ THE RECORD IS NOT THE WHOLE RUN. Reports carry fuses of their own, so
    on a run past a day the brief from its first hour burns under a live record
    and phase 5 mails a research without it. The SAVE is what remembers them —
    the rules do not let a shared machine read a sharer's reports back."""
    monkeypatch.setattr(research, "_fb_research_id", INCOG)
    assert research.save_document_to_firestore("brief", "# Brief\n\nbody")
    assert research.save_document_to_firestore("chatgpt", "# Report\n\nbody")
    world.writes.clear()
    _hold(monkeypatch, current=_job(INCOG))

    before = datetime.now(timezone.utc)
    res = research._renew_incognito_leases()
    paths = [p for _v, p, _d in world.writes]
    assert paths == [_record(INCOG),
                     f"{_record(INCOG)}/documents/brief",
                     f"{_record(INCOG)}/documents/chatgpt"]
    for verb, _p, payload in world.writes[1:]:
        assert verb == "update", "a report was re-created rather than renewed"
        assert set(payload) == {"expireAt"}
        _assert_renewed(payload["expireAt"], before=before,
                        after=datetime.now(timezone.utc))
    assert res == {"renewed": 1, "documents": 2, "failed": 0}


def test_an_ordinary_runs_reports_are_never_remembered(world, monkeypatch):
    """⭐ ACCEPT POLARITY. An ordinary report has no fuse and must never be
    handed one."""
    monkeypatch.setattr(research, "_fb_research_id", CHAT)
    assert research.save_document_to_firestore("brief", "# Brief\n\nbody")
    assert research._INCOGNITO_DOCS_WRITTEN == {}


def test_a_report_that_did_not_land_is_not_remembered(world, monkeypatch):
    monkeypatch.setattr(research, "_fb_research_id", INCOG)

    def _refuse(op, what=None, **k):
        raise RuntimeError("PERMISSION_DENIED")
    monkeypatch.setattr(research, "_grpc_write_with_heal", _refuse)
    assert research.save_document_to_firestore("brief", "# Brief\n\nbody") is False
    assert research._INCOGNITO_DOCS_WRITTEN == {}


def test_a_record_that_is_gone_leaves_its_reports_to_burn(world, monkeypatch):
    """⛔ RENEWING A REPORT UNDER A PARENT THAT WAS TAKEN AWAY would keep the
    content of a research somebody removed. The record's refusal ends the tick
    for that run."""
    research._INCOGNITO_DOCS_WRITTEN[(UID, INCOG)] = {"brief"}
    world.gone.add(_record(INCOG))
    _hold(monkeypatch, current=_job(INCOG))
    res = research._renew_incognito_leases()
    assert [v for v, _p, _d in world.writes] == ["update-refused"]
    assert res == {"renewed": 0, "documents": 0, "failed": 1}


def test_one_report_that_will_not_renew_does_not_stop_the_rest(world, monkeypatch):
    research._INCOGNITO_DOCS_WRITTEN[(UID, INCOG)] = {"brief", "chatgpt"}
    world.gone.add(f"{_record(INCOG)}/documents/brief")
    _hold(monkeypatch, current=_job(INCOG))
    res = research._renew_incognito_leases()
    assert ("update", f"{_record(INCOG)}/documents/chatgpt") in [
        (v, p) for v, p, _d in world.writes]
    assert res == {"renewed": 1, "documents": 1, "failed": 1}


def test_a_run_this_worker_no_longer_holds_is_forgotten(world, monkeypatch):
    """Once the run has left this worker nothing here renews it, and its fuse
    burns a day after the last write — the promise for a run that is over."""
    research._INCOGNITO_DOCS_WRITTEN[(UID, INCOG)] = {"brief"}
    _hold(monkeypatch, current=None)
    research._renew_incognito_leases()
    assert world.writes == []
    assert research._INCOGNITO_DOCS_WRITTEN == {}


def test_with_firestore_down_the_lease_does_nothing(world, monkeypatch):
    _hold(monkeypatch, current=_job(INCOG))
    monkeypatch.setattr(research, "_firebase_db", None)
    assert research._renew_incognito_leases() == {"renewed": 0, "documents": 0, "failed": 0}


# ══ 4. the beat that calls it ═════════════════════════════════════════════

def _run_loop(monkeypatch, renew, ticks):
    """Run the real loop for `ticks` sleeps, then cancel it the way asyncio
    does. Returns the sleep durations it asked for."""
    slept = []

    async def _sleep(sec):
        slept.append(sec)
        if len(slept) > ticks:
            raise asyncio.CancelledError

    monkeypatch.setattr(research.asyncio, "sleep", _sleep)
    monkeypatch.setattr(research, "_renew_incognito_leases", renew)
    assert asyncio.run(research._incognito_lease_loop()) is None
    return slept


def test_every_tick_renews_at_the_lease_interval(world, monkeypatch):
    calls = []

    def _renew():
        calls.append(1)
        return {"renewed": 2, "documents": 3, "failed": 0}

    slept = _run_loop(monkeypatch, _renew, ticks=2)
    assert slept == [research._INCOGNITO_LEASE_INTERVAL_SEC] * 3
    assert len(calls) == 2, "the loop slept without renewing"
    assert ("INFO", "[incognito-lease] renewed the fuse on 2 run(s) and 3 report(s) "
                    "this worker holds") in world.lines


def test_a_tick_that_raises_does_not_end_the_lease(world, monkeypatch):
    """⛔ One failed tick ending the loop would leave every later wait on this
    worker unrenewed until the next restart."""
    calls = []

    def _renew():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("blip")
        return {"renewed": 0, "documents": 0, "failed": 0}

    _run_loop(monkeypatch, _renew, ticks=2)
    assert len(calls) == 2


def test_a_quiet_tick_says_nothing(world, monkeypatch):
    _run_loop(monkeypatch, lambda: {"renewed": 0, "documents": 0, "failed": 0}, ticks=1)
    assert [m for _l, m in world.lines if "incognito-lease" in m] == []


def test_a_failed_renewal_is_said_in_the_line():
    line = research._incognito_lease_report({"renewed": 0, "documents": 0, "failed": 2})
    assert line and "2 write(s) did not land" in line


def test_the_interval_leaves_most_of_a_fuse_in_hand():
    """A lease that renewed once a day would race the fuse it exists to keep
    ahead of; four renewals inside one fuse is the floor."""
    assert 0 < research._INCOGNITO_LEASE_INTERVAL_SEC * 4 <= (
        research._INCOGNITO_EXPIRE_HOURS * 3600)


# ══ 5. wired where it runs ════════════════════════════════════════════════

def _run_server():
    tree = ast.parse(Path(research.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_server":
            return node
    raise AssertionError("run_server not found")


def test_every_worker_starts_the_lease_unconditionally():
    """⛔⛔ THE CONSUMER OF EVERYTHING ABOVE. The loop is only a lease if the
    server starts it — on EVERY worker, since each holds its own runs in its own
    process, and whether or not Firestore was up at boot, since the reconnect
    loop can bring it back later.

    ⭐ STRUCTURAL, OVER THE PARSE TREE: the call has to be a statement of
    `run_server`'s own body — not in a comment, not under a `WORKER_ID == 1`
    gate, not under `if _firebase_db:`."""
    def _starts_lease(stmt):
        return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr == "create_task"
                and stmt.value.args
                and isinstance(stmt.value.args[0], ast.Call)
                and isinstance(stmt.value.args[0].func, ast.Name)
                and stmt.value.args[0].func.id == "_incognito_lease_loop")

    server = _run_server()
    top_level = [s for s in server.body if _starts_lease(s)]
    anywhere = [s for s in ast.walk(server) if _starts_lease(s)]
    assert len(top_level) == 1, (
        f"run_server starts the lease {len(anywhere)} time(s), "
        f"{len(top_level)} of them unconditionally — it must be exactly one, "
        f"on every worker")
    assert len(anywhere) == 1
