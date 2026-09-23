"""Everything a run that keeps nothing writes carries its own fuse.

⛔⛔ SOME RUNS ARE NEVER PURGED, and they are the ones the promise has to
survive: the tab was closed and the cloud hand-off never landed, or the research
computer died mid-run. For those, nothing on either side is left to delete the
reports — which are the whole content of the research — or the timeline written
under them. Firestore TTL is the last net, and it acts only on a
timestamp-typed value that has already passed.

⭐ THE RULES REFUSE THE WRITE WITHOUT IT. `documents` under an incognito id
demands `expireAt is timestamp` less than 48h out, which is also what stops a
wheel that predates this wave from writing a report it would then keep.

Every pin below runs the real writer against a fake Firestore and reads the
payload that was actually handed to it.
"""
import time
from datetime import datetime, timedelta, timezone

import pytest

import research

UID = "uid-sharer"
INCOG = "incog_1758400000000_5"
CHAT = "chat_1758400000000_5"


# ══ 1. the fuse itself ════════════════════════════════════════════════════

def test_an_ordinary_run_gets_no_fuse_at_all():
    """⭐ ACCEPT POLARITY, and it is the compatibility claim: every document
    already in the database keeps the policy it has, which is none."""
    assert research._incognito_expire_at(CHAT) is None
    assert research._incognito_expire_at(None) is None


def test_a_run_that_keeps_nothing_is_fused_a_day_out():
    now = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
    assert research._incognito_expire_at(INCOG, now) == now + timedelta(hours=24)


def test_the_fuse_is_timezone_aware():
    """⛔⛔ THE LOAD-BEARING HALF. Firestore stores a naive datetime by guessing,
    and the rules check `is timestamp` precisely because a value that merely
    looks like a time expires nothing, for ever."""
    got = research._incognito_expire_at(INCOG)
    assert got.tzinfo is not None and got.utcoffset() is not None


def test_the_fuse_stays_under_the_rules_ceiling():
    """⛔ `ephemeralExpiryOk()` refuses anything past 48 hours, and the gap
    between this and that ceiling is the room a long run has to renew. A wheel
    that stamped the ceiling would leave a run with none."""
    now = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
    assert research._incognito_expire_at(INCOG, now) < now + timedelta(hours=48)


# ══ 2. the reports ════════════════════════════════════════════════════════

class _Doc:
    def __init__(self, sink, path):
        self.sink, self.path = sink, path

    def collection(self, name):
        return _Doc(self.sink, f"{self.path}/{name}")

    def document(self, name):
        return _Doc(self.sink, f"{self.path}/{name}")

    def set(self, data, merge=False):
        self.sink.append(("set", self.path, dict(data), merge))

    def add(self, data):
        self.sink.append(("add", self.path, dict(data), False))


class _Db:
    def __init__(self, sink):
        self.sink = sink

    def collection(self, name):
        return _Doc(self.sink, name)


@pytest.fixture()
def db(monkeypatch):
    sink = []
    monkeypatch.setattr(research, "_firebase_db", _Db(sink))
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_be_payload", lambda d: dict(d))
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what=None, **k: op())
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    return sink


def _save(monkeypatch, rid):
    monkeypatch.setattr(research, "_fb_research_id", rid)
    return research.save_document_to_firestore("chatgpt", "# Report\n\nbody")


def test_an_ordinary_runs_report_is_written_with_no_expiry(db, monkeypatch):
    """⭐ ACCEPT POLARITY. Adding a fuse to every document in the product would
    quietly start deleting people's research."""
    assert _save(monkeypatch, CHAT) is True
    [(_kind, path, payload, _merge)] = db
    assert path.endswith(f"researches/{CHAT}/documents/chatgpt")
    assert "expireAt" not in payload
    assert payload["content"].startswith("# Report")


def test_a_run_that_keeps_nothings_report_carries_a_timestamp(db, monkeypatch):
    """⛔ THE RULE REFUSES THE WRITE WITHOUT IT, which is also what stops a wheel
    that predates this wave from writing a report it would then keep."""
    assert _save(monkeypatch, INCOG) is True
    [(_kind, _path, payload, _merge)] = db
    expire = payload["expireAt"]
    assert isinstance(expire, datetime), f"expireAt is a {type(expire).__name__}"
    assert expire.tzinfo is not None
    assert expire < datetime.now(timezone.utc) + timedelta(hours=48)
    assert expire > datetime.now(timezone.utc)


# ══ 3. the timeline ═══════════════════════════════════════════════════════

def _emit(monkeypatch, rid, *, last_seq=0):
    monkeypatch.setattr(research, "_fb_research_id", rid)
    monkeypatch.setattr(research, "_fb_seq", last_seq)
    return research._emit_to_firestore({"type": "phase_start", "phase": 2})


def test_an_ordinary_runs_events_still_live_a_month(db, monkeypatch):
    """⭐ ACCEPT POLARITY. Thirty days is what keeps an ordinary run's timeline
    readable for as long as the run is, and shortening it for everybody would
    quietly empty the phase dropdown of every older research."""
    assert _emit(monkeypatch, CHAT)
    [(kind, path, payload, _merge)] = db
    assert kind == "add" and path.endswith("pipeline_events")
    assert payload["expireAt"] > datetime.now(timezone.utc) + timedelta(days=29)


def test_a_run_that_keeps_nothings_events_burn_in_a_day(db, monkeypatch):
    """⛔ Thirty days of somebody's phase-by-phase history under a record that
    is already gone — and a late event written after the purge is an orphan no
    list can show and no sweep can find."""
    assert _emit(monkeypatch, INCOG)
    [(_kind, _path, payload, _merge)] = db
    assert payload["expireAt"] < datetime.now(timezone.utc) + timedelta(hours=48)
    assert payload["expireAt"] > datetime.now(timezone.utc)


def test_the_event_still_carries_everything_else_it_did(db, monkeypatch):
    """⛔ THE FUSE IS AN ADDITION — asserted in the SAME write as the fuse.

    The sequence number is what the app's `where("seq", ">", lastSeq)` filter
    reads, and losing it drops every event the chat has not seen yet.

    ⛔⛔ `assert payload["seq"] > 0` MEASURED NOTHING. Every seq this function
    can produce is a millisecond clock, so any code that ever ran satisfied it —
    including the code before this wave, and including a seq that went
    BACKWARDS. So the previous event's number is set ahead of the clock here:
    the only way past this assertion is the monotonic guard, and the fuse the
    same write carries is what makes it a fact about this branch rather than
    about the function it changed."""
    ahead = int(time.time() * 1000) + 5_000
    seq = _emit(monkeypatch, INCOG, last_seq=ahead)
    [(_kind, _path, payload, _merge)] = db
    assert payload["type"] == "phase_start" and payload["phase"] == 2
    assert payload["seq"] == ahead + 1 == seq == research._fb_seq, (
        f"an event landed with seq={payload['seq']} behind the last one the "
        f"chat saw ({ahead}) — the app's filter never shows it")
    assert payload["expireAt"] < datetime.now(timezone.utc) + timedelta(hours=48)
