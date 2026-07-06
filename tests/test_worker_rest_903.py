"""#903 worker rest — _worker_is_resting + gate wiring guards (2026-07-06).

The owner parks workers via the device doc's restingWorkerIds; a resting
worker takes NO new runs. These tests pin the helper's contract (fail-open,
type-guarded coercion, TTL cache) and the gate wiring the adversarial review
locked in (listener claims while _REST_DEFER_SEEN is set; rescan clears the
flag level-triggered; rest checks run off-loop in the rescan).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import research  # noqa: E402


class _FakeDB:
    def __init__(self, doc):
        self._doc = doc
        self.reads = 0

    def collection(self, name):
        return self

    def document(self, _id):
        return self

    def get(self):
        self.reads += 1
        outer = self

        class _Snap:
            def to_dict(self):
                return outer._doc
        return _Snap()


def _fresh(monkeypatch, doc, worker_id=1):
    monkeypatch.setattr(research, "_RESTING_CACHE", {"at": 0.0, "ids": ()})
    monkeypatch.setattr(research, "load_device_id", lambda: "dev1")
    monkeypatch.setattr(research, "WORKER_ID", worker_id)
    db = _FakeDB(doc)
    monkeypatch.setattr(research, "_firebase_db", db)
    return db


def test_resting_true_for_listed_worker(monkeypatch):
    _fresh(monkeypatch, {"restingWorkerIds": [1, 2]}, worker_id=1)
    assert research._worker_is_resting() is True


def test_awake_for_unlisted_worker(monkeypatch):
    _fresh(monkeypatch, {"restingWorkerIds": [1, 2]}, worker_id=3)
    assert research._worker_is_resting() is False


def test_missing_or_empty_field_is_awake(monkeypatch):
    _fresh(monkeypatch, {})
    assert research._worker_is_resting() is False
    _fresh(monkeypatch, {"restingWorkerIds": []})
    assert research._worker_is_resting() is False


def test_fails_open_on_read_error(monkeypatch):
    # A Firestore blip must NEVER pause the device — treat as awake.
    monkeypatch.setattr(research, "_RESTING_CACHE", {"at": 0.0, "ids": ()})
    monkeypatch.setattr(research, "load_device_id", lambda: "dev1")

    class _Boom:
        def collection(self, *_a):
            raise RuntimeError("offline")
    monkeypatch.setattr(research, "_firebase_db", _Boom())
    assert research._worker_is_resting() is False


def test_garbage_types_count_nobody_resting(monkeypatch):
    # Review: never char-iterate a scalar string; bools must not coerce to 1.
    for garbage in ("12", {"1": True}, [True], 7):
        _fresh(monkeypatch, {"restingWorkerIds": garbage})
        assert research._worker_is_resting() is False, repr(garbage)
    # Float + numeric-string entries DO coerce (FE writes numbers).
    _fresh(monkeypatch, {"restingWorkerIds": [1.0, "2"]}, worker_id=2)
    assert research._worker_is_resting() is True


def test_ttl_cache_one_read_per_window(monkeypatch):
    db = _fresh(monkeypatch, {"restingWorkerIds": [1]})
    assert research._worker_is_resting() is True
    assert research._worker_is_resting() is True
    assert db.reads == 1  # second call inside the TTL window = cached
    # Expire the window → fresh read.
    research._RESTING_CACHE["at"] = time.time() - 10
    assert research._worker_is_resting() is True
    assert db.reads == 2


# ── gate wiring (source-inspection — the gates live in closures) ────────────

def test_listener_claims_while_rest_flag_set():
    import inspect
    src = inspect.getsource(research.start_firestore_listener) if hasattr(
        research, "start_firestore_listener") else open(
        research.__file__, encoding="utf-8").read()
    assert 'if _resting or _multi_worker_mode or _REST_DEFER_SEEN["v"]:' in src, (
        "the start listener must enter the claim path while _REST_DEFER_SEEN "
        "is set — the armed single-worker rescan would otherwise race the "
        "non-claiming listener into a duplicate run (review MAJOR)."
    )
    assert '"worker-resting"' in src  # honest defer reason
    assert "restDeferredAt" in src   # 12h-sweep keep-alive stamp


def test_rescan_clears_flag_level_triggered():
    src = open(research.__file__, encoding="utf-8").read()
    assert '_REST_DEFER_SEEN["v"] = False' in src, (
        "the rescan must clear the flag once the worker is awake and the "
        "queue has no unclaimed start docs — a latched flag would leave the "
        "claim RTT + rescan armed forever on single-worker installs."
    )
    # Rest checks in the async rescan run OFF the event loop.
    assert "await asyncio.to_thread(_worker_is_resting)" in src


def test_abandoned_sweep_exempts_rest_deferred_docs():
    src = open(research.__file__, encoding="utf-8").read()
    assert "not _worker_is_resting()" in src
    assert 'data["restDeferredAt"]' in src, (
        "the 12h ABANDONED sweep must measure a rest-deferred doc's age from "
        "the keep-alive stamp — parking >12h + a BE restart must not drop "
        "the queued run (review MAJOR)."
    )


# ── #904: resting keep-alive + status self-heal ─────────────────────────────
#
# Live repro 2026-07-06 ("Yo", all workers rested): BE Gate 1 deferred + wrote
# status="queued" correctly, but the class of failure it guards against — a
# doc left status="ongoing" with no claim (FE mispredict / #720 race) — had no
# healer while resting, and restDeferredAt was stamped exactly once (Gate 1),
# so a weekend park woke up to the 12h stale-skip. The keep-alive pass runs
# from the rescan's resting branch and fixes both.

class _KeepaliveQueueDoc:
    exists = True  # doubles as its own pre-write re-read snapshot

    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.reference = self
        self.updates = []

    def to_dict(self):
        return dict(self._data)

    def get(self):
        return self  # TOCTOU re-read (review fold) sees live state

    def update(self, patch):
        self.updates.append(patch)
        self._data.update(patch)


class _KeepaliveDB:
    """Fake Firestore: devices/{id}/queue stream + users/{uid}/researches get.

    `research_seq` (optional) serves successive research-doc reads from a
    list — lets a test flip the doc between the pass's initial read and its
    pre-write TOCTOU re-read (the cancel-mid-window race)."""

    def __init__(self, queue_docs, research_doc, research_seq=None):
        self._queue_docs = queue_docs
        self._research_doc = research_doc
        self._research_seq = list(research_seq) if research_seq else None
        self._path = []

    def collection(self, name):
        self._path.append(name)
        return self

    def document(self, _id):
        return self

    def limit(self, _n):
        return self

    def stream(self):
        return list(self._queue_docs)

    def get(self):
        doc = (self._research_seq.pop(0) if self._research_seq
               else self._research_doc)

        class _Snap:
            exists = doc is not None

            def to_dict(self):
                return dict(doc or {})
        return _Snap()


def _keepalive_env(monkeypatch, queue_docs, research_doc, *, healed_into=None,
                   research_seq=None):
    monkeypatch.setattr(research, "_REST_KEEPALIVE_STATE", {"last_ms": 0})
    monkeypatch.setattr(research, "load_device_id", lambda: "dev1")
    monkeypatch.setattr(research, "WORKER_ID", 1)
    monkeypatch.setattr(research, "_firebase_db",
                        _KeepaliveDB(queue_docs, research_doc, research_seq))
    monkeypatch.setattr(research, "_compute_queue_enrichment", lambda col, i, u: {
        "position": 1, "behind_rid": "", "behind_title": "",
        "total_ahead": 0, "ahead_from_self": 0, "ahead_from_others": 0,
    })
    monkeypatch.setattr(research, "_read_eta_inputs_and_compute", lambda p: (-1, 0))
    calls = healed_into if healed_into is not None else []

    def _fake_update(uid, rid, updates):
        calls.append((uid, rid, updates))
        return True
    monkeypatch.setattr(research, "_update_research_doc", _fake_update)
    return calls


def test_keepalive_restamps_stale_and_skips_fresh(monkeypatch):
    now_ms = int(time.time() * 1000)
    stale = _KeepaliveQueueDoc("q1", {
        "action": "start", "researchId": "chat_stale", "submittedBy": "u1",
        "restDeferredAt": now_ms - 2 * 60 * 60 * 1000,   # 2h old → refresh
    })
    fresh = _KeepaliveQueueDoc("q2", {
        "action": "start", "researchId": "chat_fresh", "submittedBy": "u1",
        "restDeferredAt": now_ms - 60 * 1000,            # 1min old → leave
    })
    _keepalive_env(monkeypatch, [stale, fresh], {"status": "queued"})
    research._rest_keepalive_pass()
    assert any("restDeferredAt" in u for u in stale.updates), (
        "a stamp older than the refresh window must be re-written — a weekend "
        "park otherwise wakes into the 12h ABANDONED stale-skip and the run "
        "is silently dropped."
    )
    assert fresh.updates == []  # fresh stamp untouched (write economy)


def test_keepalive_heals_drifted_ongoing_doc(monkeypatch):
    qdoc = _KeepaliveQueueDoc("q1", {
        "action": "start", "researchId": "chat_yo", "submittedBy": "u1",
        "restDeferredAt": int(time.time() * 1000),
    })
    healed = _keepalive_env(monkeypatch, [qdoc], {"status": "ongoing"})
    research._rest_keepalive_pass()
    assert len(healed) == 1
    uid, rid, updates = healed[0]
    assert (uid, rid) == ("u1", "chat_yo")
    assert updates["status"] == "queued"
    assert updates["queuePosition"] == 1


def test_keepalive_never_touches_terminal_claimed_or_started(monkeypatch):
    now_ms = int(time.time() * 1000)
    # Claimed queue doc → skipped entirely (Gate 2 owns claimed docs).
    claimed = _KeepaliveQueueDoc("q1", {
        "action": "start", "researchId": "chat_a", "submittedBy": "u1",
        "assignedWorker": 2, "restDeferredAt": now_ms - 9 * 60 * 60 * 1000,
    })
    healed = _keepalive_env(monkeypatch, [claimed], {"status": "ongoing"})
    research._rest_keepalive_pass()
    assert healed == [] and claimed.updates == []
    # status != "ongoing" (stopped / completed / already queued) → never healed:
    # re-asserting queued on a cancelled run would resurrect it.
    for status in ("stopped", "completed", "queued", "failed"):
        qdoc = _KeepaliveQueueDoc("q1", {
            "action": "start", "researchId": "chat_b", "submittedBy": "u1",
        })
        healed = _keepalive_env(monkeypatch, [qdoc], {"status": status})
        research._rest_keepalive_pass()
        assert healed == [], status
    # backendRunId present (claimed at some point) → never healed.
    qdoc = _KeepaliveQueueDoc("q1", {
        "action": "start", "researchId": "chat_c", "submittedBy": "u1",
    })
    healed = _keepalive_env(monkeypatch, [qdoc],
                            {"status": "ongoing", "backendRunId": "run_1"})
    research._rest_keepalive_pass()
    assert healed == []


def test_keepalive_stamp_skips_cancel_orphaned_queue_docs(monkeypatch):
    # Review fold: a queue doc whose research is terminal (cancel wrote
    # status=stopped but the queue-doc delete failed) must NOT be kept
    # alive — the 12h ABANDONED sweep is what bounds the pre-existing
    # wake-claims-a-cancelled-run hole.
    now_ms = int(time.time() * 1000)
    for research_doc in ({"status": "stopped"}, None):   # terminal / deleted
        orphan = _KeepaliveQueueDoc("q1", {
            "action": "start", "researchId": "chat_dead", "submittedBy": "u1",
            "restDeferredAt": now_ms - 9 * 60 * 60 * 1000,  # ancient stamp
        })
        healed = _keepalive_env(monkeypatch, [orphan], research_doc)
        research._rest_keepalive_pass()
        assert orphan.updates == [], research_doc   # no stamp refresh
        assert healed == []                          # and no heal


def test_keepalive_heal_aborts_when_cancelled_mid_window(monkeypatch):
    # Review fold (TOCTOU): user cancels the paused run between the initial
    # read and the write — the pre-write re-read must abort the heal, or a
    # stopped→queued clobber would resurrect the cancelled run as a zombie
    # banner with no queue doc behind it.
    qdoc = _KeepaliveQueueDoc("q1", {
        "action": "start", "researchId": "chat_yo", "submittedBy": "u1",
        "restDeferredAt": int(time.time() * 1000),
    })
    healed = _keepalive_env(
        monkeypatch, [qdoc], None,
        research_seq=[{"status": "ongoing"}, {"status": "stopped"}],
    )
    research._rest_keepalive_pass()
    assert healed == []


def test_keepalive_throttles_to_once_per_minute(monkeypatch):
    qdoc = _KeepaliveQueueDoc("q1", {
        "action": "start", "researchId": "chat_yo", "submittedBy": "u1",
    })
    healed = _keepalive_env(monkeypatch, [qdoc], {"status": "ongoing"})
    research._rest_keepalive_pass()
    research._rest_keepalive_pass()   # inside the 60s window → no-op
    assert len(healed) == 1


def test_rescan_resting_branch_runs_keepalive():
    src = open(research.__file__, encoding="utf-8").read()
    assert "await asyncio.to_thread(_rest_keepalive_pass)" in src, (
        "the rescan's resting branch must run the keep-alive/self-heal pass "
        "before returning — it is the only actor alive while every worker "
        "rests, so without it a drifted doc stays stuck at Init forever."
    )
