"""A thread a run leaves behind writes to THAT run's record — never the next one's.

Wave 10.9, last repair. The title refresh and the summary are raw threads with
a model call in front of their write, and the phase-3 `save_meta` thread has an
ffprobe per podcast in front of its own. All three wrote through
`_update_firestore_research`, which picks its target from the pipeline globals
AT WRITE TIME. A run can end inside that window: teardown clears the globals,
the worker dequeues the next member's run at once, and setup points them at
that person's research — so the title and summary made from one person's topic
and findings, and one run's whole agents map, landed on somebody else's record,
in their sidebar and on their tile. A reviewer reproduced it with the real
functions.

⭐ Every pin below runs the REAL worker with the globals switched to another
member's run before its body runs — the model call's window, collapsed — and
records every document the fake Firestore is asked for. Nothing may land on the
other run, ordinary or incognito; and a run that keeps nothing starts neither
thread at all, because its record is purged and the model call on its topic
would only outlive it.

Run:  pytest tests/test_late_writers_name_their_run_109.py -v
"""
import types

import pytest

import research

A_UID, A_RID = "uid-member-a", "chat_1758400000000_1"
A_PRIVATE = "incog_1758400000000_1"
B_UID, B_RID = "uid-member-b", "chat_1758400999999_1"
TOPIC = "divorce settlement options"
TITLE = "Divorce Settlement Options Overview"
SUMMARY = "The research found that divorce settlement options include mediation."


class _Db:
    """Firestore, as far as these writers go: every document read and updated,
    by its full path."""

    def __init__(self):
        self.reads: list = []
        self.writes: list = []

    def collection(self, name):
        return _Ref(self, (name,))


class _Ref:
    def __init__(self, db, path):
        self._db, self.path = db, path

    def collection(self, name):
        return _Ref(self._db, self.path + (name,))

    def document(self, name):
        return _Ref(self._db, self.path + (name,))

    def get(self):
        self._db.reads.append(self.path)
        return types.SimpleNamespace(exists=True, to_dict=lambda: {"titleLocked": False})

    def update(self, payload):
        self._db.writes.append((self.path, dict(payload)))


def _record(uid, rid):
    return ("users", uid, "researches", rid)


class _NextRunFirst:
    """A raw thread whose body runs only after its run has ended and the next
    member's run has been set up — which is where the model call's answer, or
    the ffprobe's, arrives."""

    started: list = []
    switch = True

    def __init__(self, target=None, args=(), kwargs=None, **_kw):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        _NextRunFirst.started.append(self._target)
        if _NextRunFirst.switch:
            research._fb_uid, research._fb_research_id = B_UID, B_RID
        self._target(*self._args, **self._kwargs)


@pytest.fixture
def world(monkeypatch):
    db = _Db()
    events: list = []
    monkeypatch.setattr(research, "_firebase_db", db)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-1")
    monkeypatch.setattr(research, "_grpc_write_with_heal", lambda op, *, what: op())
    monkeypatch.setattr(research, "_threading", types.SimpleNamespace(Thread=_NextRunFirst))
    monkeypatch.setattr(_NextRunFirst, "started", [])
    monkeypatch.setattr(_NextRunFirst, "switch", True)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "_try_llm_title", lambda *a, **k: TITLE)
    monkeypatch.setattr(research, "_try_llm_summary", lambda *a, **k: SUMMARY)
    monkeypatch.setattr(research, "_fb_uid", A_UID)
    monkeypatch.setattr(research, "_fb_research_id", A_RID)
    return types.SimpleNamespace(db=db, events=events)


def _nothing_on_b(db):
    touched = db.reads + [path for path, _payload in db.writes]
    assert _record(B_UID, B_RID) not in touched, (
        f"a write or read for member A's run landed on member B's record: {touched}")


# ══ 1. the title ══════════════════════════════════════════════════════════

def test_a_late_title_lands_on_the_run_that_asked_for_it(world, monkeypatch):
    """⛔⛔ THE REVIEWER'S REPRODUCTION. The title — made from A's topic and
    findings — went onto B's record, into B's sidebar."""
    monkeypatch.setattr(research, "title_refusal_verdict", lambda *a, **k: "accept")

    research._refresh_research_title_async(TOPIC, "", "findings")

    _nothing_on_b(world.db)
    assert [(p, d["title"]) for p, d in world.db.writes] == [(_record(A_UID, A_RID), TITLE)], (
        "the title did not reach the run that asked for it")
    # ⭐ AND THE LOCK IT HONOURS IS A's: the user-rename guard reads the same
    # record it would overwrite.
    assert world.db.reads == [_record(A_UID, A_RID)]


def test_a_late_off_topic_card_is_not_raised_on_somebody_elses_chat(world, monkeypatch):
    """⛔⛔ THE CARD QUOTES THE GENERATED TITLE, and `emit_event` writes to
    whatever research the globals name when it runs. After A has ended that is
    B's chat. A card about a run that is over is read by nobody, so it is not
    raised."""
    monkeypatch.setattr(research, "title_refusal_verdict", lambda *a, **k: "refuse_loud")

    research._refresh_research_title_async(TOPIC, "", "findings")

    assert world.events == [], "A's off-topic card was raised while B was running"
    assert world.db.writes == []


def test_the_off_topic_card_still_reaches_the_run_while_it_is_running(world, monkeypatch):
    """⭐ ACCEPT POLARITY. The card exists for a run that is still going — phase
    3 is thirty minutes of podcast — and it must still arrive there."""
    monkeypatch.setattr(research, "title_refusal_verdict", lambda *a, **k: "refuse_loud")
    monkeypatch.setattr(_NextRunFirst, "switch", False)

    research._refresh_research_title_async(TOPIC, "", "findings")

    assert [a[0] for a, _k in world.events] == ["pipeline_warning"]


def test_a_run_that_keeps_nothing_starts_no_title_refresh(world, monkeypatch):
    """⛔⛔ ITS RECORD IS PURGED WHEN IT ENDS, and the worker is a model call on
    its private topic and findings that outlives it."""
    monkeypatch.setattr(research, "_fb_research_id", A_PRIVATE)

    research._refresh_research_title_async(TOPIC, "", "findings")

    assert _NextRunFirst.started == [], "a run that keeps nothing started a title refresh"
    assert world.db.reads == [] and world.db.writes == [] and world.events == []


# ══ 2. the summary ════════════════════════════════════════════════════════

def test_a_late_summary_lands_on_the_run_that_asked_for_it(world):
    """⛔⛔ "What the research found", on the wrong person's /researches tile."""
    research._generate_research_summary_async(TOPIC, "", "findings")

    _nothing_on_b(world.db)
    assert [(p, d["summary"]) for p, d in world.db.writes] == [(_record(A_UID, A_RID), SUMMARY)]


def test_a_run_that_keeps_nothing_starts_no_summary(world, monkeypatch):
    monkeypatch.setattr(research, "_fb_research_id", A_PRIVATE)

    research._generate_research_summary_async(TOPIC, "", "findings")

    assert _NextRunFirst.started == [], "a run that keeps nothing started a summary"
    assert world.db.writes == []


# ══ 3. the phase-3 meta thread ═════════════════════════════════════════════

def test_the_phase_three_meta_thread_lands_on_the_run_that_dispatched_it(
        world, monkeypatch, tmp_path):
    """⛔⛔ THE SAME SHAPE, AND THE BIGGER PAYLOAD. Phase 3 hands `save_meta` to
    a thread so the ffprobe per podcast does not hold up `phase_complete`, and
    the run hands phases 4 and 5 to the cloud and returns moments later. The
    thread's write is the whole agents map — every agent's sources and
    findings — and the phase timeline, stamped with the statuses the runtime
    recorded for the run it names."""
    queue_dir = tmp_path / "divorce_20260922_101500"
    (queue_dir / "documents").mkdir(parents=True)
    monkeypatch.setitem(research._phase_status_by_rid, A_RID, {3: "complete"})
    monkeypatch.setitem(research._phase_status_by_rid, B_RID, {3: "errored"})
    monkeypatch.setitem(research._agent_status_by_rid, A_RID, {"claude": "complete"})
    monkeypatch.setitem(research._agent_status_by_rid, B_RID, {"claude": "errored"})

    research._save_meta_in_background(queue_dir, TOPIC, 3)

    _nothing_on_b(world.db)
    [(path, payload)] = world.db.writes
    assert path == _record(A_UID, A_RID), f"the meta write went to {path}"
    # ⭐ AND WHAT IT CARRIES IS A's — not B's statuses stamped onto A's record.
    [phase3] = [p for p in payload["phases"] if p.get("phase") == 3]
    assert phase3["status"] == "complete", payload["phases"]
    assert payload["agents"]["claude"]["status"] == "complete", payload["agents"]
