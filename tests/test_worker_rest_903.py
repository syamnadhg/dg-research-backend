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
