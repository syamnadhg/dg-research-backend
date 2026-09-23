"""The research computer never brings back a research that was taken away.

⛔⛔ A `set(…, merge=True)` TO A MISSING DOCUMENT IS A CREATE. Three writers on
this machine use one — the links map, the userSources append, and the
`backendRunId` / agents seam — and so does `saveResearch` in the app. A
research that was purged (somebody left the chat, the P5 chain finished, or its
own fuse burned out) therefore comes back on the very next write as a fragment
carrying only the fields that write mentioned. It has no `createdAt`, and every
list in the app orders by `createdAt`, so the fragment is invisible to every
screen, every sweep and the TTL itself: a permanent orphan holding whatever the
write carried — a link, a source, a whole agents map.

⛔ AND THE ORDINARY SET-MERGE IS LOAD-BEARING. The machine writes
`backendRunId` on first arrival, sometimes before the app has finished creating
the record; an update would lose that race every single time. So the accept
polarity is asserted first here, before any refusal.
"""
import time

import pytest

import research
from _queue_listener import Listener

UID = "uid-sharer"
INCOG = "incog_1758400000000_9"
CHAT = "chat_1758400000000_9"


# ══ 1. the dotted field paths an update needs ═════════════════════════════

def test_a_flat_payload_is_left_exactly_as_it_is():
    payload = {"status": "ongoing", "backendRunId": "r_1", "assignedWorker": 2}
    assert research._merge_field_paths(payload) == payload


def test_a_nested_map_becomes_a_field_path():
    """⛔⛔ AN UPDATE WITH A NESTED MAP AS ONE VALUE REPLACES THAT MAP, deleting
    every key the new one omits — the trap that erased `needsRestart` when
    `updateStatus` was written whole. `agents.chatgpt` leaves `agents.gemini`
    alone; `agents` as a map does not.

    ⛔⛔ AND ONE LEVEL WAS NOT ENOUGH, which is what this assertion used to say.
    `{"agents.chatgpt": {"status": …}}` is a map as one value all over again,
    one step lower, so the write that said an agent had FINISHED deleted that
    agent's sources, findings and progress curve. The document that proves it is
    in tests/test_incognito_live_progress_109.py; this is the shape it needs."""
    out = research._merge_field_paths({"agents": {"chatgpt": {"status": "complete"}}})
    assert out == {"agents.chatgpt.status": "complete"}


def test_two_keys_under_one_map_each_get_their_own_path():
    out = research._merge_field_paths({"links": {"brief": {"url": "a"},
                                                 "audio_file": {"url": "b"}}})
    assert out == {"links.brief.url": "a", "links.audio_file.url": "b"}


def test_a_sentinel_is_never_descended_into():
    """A `DELETE_FIELD` or an `ArrayUnion` is not a dict, so it passes through
    and an update appends or clears exactly the way the merge did."""
    class _Sentinel:
        pass
    sentinel = _Sentinel()
    assert research._merge_field_paths({"userSources": sentinel}) == {
        "userSources": sentinel}


@pytest.mark.parametrize("name", ["a.b", "audio-file", "2x", "a b", "a`b"])
def test_a_name_that_would_need_quoting_keeps_its_whole_map_form(name):
    """⛔ A field name with a dot in it has to be back-quoted in a path, and
    splicing it in unquoted would write to a DIFFERENT field. Rather than build
    that quoting, such a payload stays a whole-map value — the pre-existing
    behaviour, which is at worst a replace and never a wrong address.

    ⛔⛔ AND THE SET IS THE CLIENT'S, NOT A GUESS. `parse_field_path` accepts
    `[A-Za-z_][A-Za-z0-9_]*` unquoted and RAISES on anything else, so a hyphen
    or a leading digit is not "at worst a replace" — it is an exception thrown
    inside the write, swallowed by the caller as a WARN, and the write an
    ordinary run lands with a set-merge simply never happens."""
    payload = {"links": {name: {"url": "x"}}}
    assert research._merge_field_paths(payload) == payload
    assert research._merge_field_paths({name: {"c": 1}}) == {name: {"c": 1}}


def test_an_empty_map_is_not_expanded_into_nothing():
    """`{"agents": {}}` expanded to zero paths would be a write that says
    nothing, silently — worse than the whole-map write it replaced."""
    assert research._merge_field_paths({"agents": {}}) == {"agents": {}}


# ══ 2. the three writers ══════════════════════════════════════════════════

class _Ref:
    def __init__(self, calls):
        self.calls = calls

    def set(self, data, merge=False):
        self.calls.append(("set", dict(data), merge))

    def update(self, data):
        self.calls.append(("update", dict(data), None))


def test_an_ordinary_run_still_writes_a_set_merge():
    """⭐ ACCEPT POLARITY FIRST, and it is the whole compatibility claim: the
    machine writes `backendRunId` before the app has always finished creating
    the record, and an update would lose that race every time."""
    calls = []
    research._write_research_doc(_Ref(calls), {"backendRunId": "r_1"}, CHAT)
    assert calls == [("set", {"backendRunId": "r_1"}, True)]


def test_a_run_that_keeps_nothing_writes_an_update():
    calls = []
    research._write_research_doc(_Ref(calls), {"backendRunId": "r_1"}, INCOG)
    assert calls == [("update", {"backendRunId": "r_1"}, None)]


def test_a_run_that_keeps_nothing_keeps_its_other_agents():
    """⛔ THE HALF THAT MAKES THE UPDATE SAFE. Without the dotted path, writing
    one agent's terminal status would delete the other two."""
    calls = []
    research._write_research_doc(
        _Ref(calls), {"agents": {"claude": {"status": "complete"}}}, INCOG)
    assert calls[0][1] == {"agents.claude.status": "complete"}


# ── the consumers ─────────────────────────────────────────────────────────

class _DocRef:
    def __init__(self, sink, path):
        self.sink, self.path = sink, path

    def collection(self, name):
        return _DocRef(self.sink, f"{self.path}/{name}")

    def document(self, name):
        return _DocRef(self.sink, f"{self.path}/{name}")

    def set(self, data, merge=False):
        self.sink.append(("set", dict(data)))

    def update(self, data):
        self.sink.append(("update", dict(data)))


class _Db:
    def __init__(self, sink):
        self.sink = sink

    def collection(self, name):
        return _DocRef(self.sink, name)


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


@pytest.mark.parametrize("rid,verb", [(CHAT, "set"), (INCOG, "update")])
def test_the_links_writer_asks_the_same_question(db, monkeypatch, rid, verb):
    monkeypatch.setattr(research, "_fb_research_id", rid)
    research.update_link_in_firestore("brief", "https://x/1", label="Brief")
    [(kind, payload)] = db
    assert kind == verb
    if verb == "update":
        assert payload == {"links.brief.url": "https://x/1", "links.brief.label": "Brief"}
    else:
        assert payload == {"links": {"brief": {"url": "https://x/1", "label": "Brief"}}}


@pytest.mark.parametrize("rid,verb", [(CHAT, "set"), (INCOG, "update")])
def test_the_user_sources_writer_asks_the_same_question(db, monkeypatch, rid, verb):
    """⛔ THE APPEND MUST STILL APPEND. `ArrayUnion` is a sentinel, so it rides
    an update untouched — a field-path rewrite that descended into it would
    have turned the append into something else entirely."""
    monkeypatch.setattr(research, "_fb_research_id", rid)
    research.append_user_source_in_firestore("doc", "https://x/2", label="A doc")
    [(kind, payload)] = db
    assert kind == verb
    assert list(payload) == ["userSources"]
    assert type(payload["userSources"]).__name__ == "ArrayUnion"


@pytest.mark.parametrize("rid,verb", [(CHAT, "set"), (INCOG, "update")])
def test_the_agents_writer_asks_the_same_question(db, monkeypatch, rid, verb):
    monkeypatch.setattr(research, "_fb_research_id", rid)
    assert research._set_research_doc(UID, rid, {"agents": {"gemini": {"status": "x"}}})
    [(kind, payload)] = db
    assert kind == verb
    assert payload == ({"agents.gemini.status": "x"} if verb == "update"
                       else {"agents": {"gemini": {"status": "x"}}})


def test_a_write_that_cannot_land_answers_false_rather_than_raising(db, monkeypatch):
    """An update to a document that is gone raises NotFound. The machine must
    record that and carry on — this is a best-effort seam, and a raise here
    would take the run down instead of the write."""
    monkeypatch.setattr(research, "_fb_research_id", INCOG)

    def boom(op, what=None, **k):
        raise RuntimeError("404 NOT_FOUND")
    monkeypatch.setattr(research, "_grpc_write_with_heal", boom)
    assert research._set_research_doc(UID, INCOG, {"status": "ongoing"}) is False


# ══ 3. the claim: an abort, not a resurrection ════════════════════════════

def _claim_world(monkeypatch, tmp_path, rid):
    """The start listener with its research-doc write REFUSED — a record that
    is gone, which is what the fallback was written to survive."""
    lis = Listener(monkeypatch, tmp_path, owner="uid-owner",
                   research_docs={(UID, rid): {"status": "queued"}})
    monkeypatch.setattr(research, "_update_research_doc", lambda *a, **k: False)
    recreated = []
    monkeypatch.setattr(research, "_set_research_doc",
                        lambda *a, **k: (recreated.append(a) or True))
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    return lis, recreated


def _start(rid):
    return {"action": "start", "researchId": rid, "uid": UID,
            "submittedBy": UID, "topic": "a topic",
            "timestamp": int(time.time() * 1000) - 1000}


def test_an_ordinary_start_still_falls_back_to_creating_the_record(
        tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY. For an ordinary research this fallback covers a real
    race — the app is still creating the record — and removing it would lose
    the `backendRunId` of every start that arrived a beat early."""
    lis, recreated = _claim_world(monkeypatch, tmp_path, CHAT)
    lis.feed(**_start(CHAT))
    assert len(recreated) == 1, "the create-on-race fallback stopped firing"
    assert lis.enqueued, "an ordinary run must still be handed to the worker"


def test_a_start_whose_record_is_gone_is_abandoned_not_recreated(
        tmp_path, monkeypatch):
    """⛔⛔ THE PIN THE SPEC NAMED. For an incognito run a failed write does not
    mean "the record is not there yet" — it means it was DELETED, by somebody
    leaving the chat or by the fuse burning out in a queue. Recreating it leaves
    a fragment with no `createdAt`, invisible to every list, every sweep and the
    TTL itself."""
    lis, recreated = _claim_world(monkeypatch, tmp_path, INCOG)
    lis.feed(**_start(INCOG))
    assert recreated == [], "a purged incognito record was recreated"
    assert lis.enqueued == [], "the run was started anyway"


def test_the_abandoned_start_takes_its_queue_document_with_it(
        tmp_path, monkeypatch):
    """⛔ LEFT BEHIND, the idle-rescan claims it on the next pass and arrives
    here again, for ever."""
    lis, _ = _claim_world(monkeypatch, tmp_path, INCOG)
    lis.feed(**_start(INCOG))
    assert lis.incoming == ["incoming"], "the queue document was left to be re-claimed"
