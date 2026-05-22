"""Unit tests for `_try_claim_queue_doc` — the conditional-update replacement
for the prior `@firestore.transactional` claim path.

Why this exists: the TX-based claim masked `BeginTransaction` failures
(synth-user JWT refresh, gRPC channel hiccup) behind a misleading
`ValueError("...no transaction ID...")`. With workerCount=2 both workers'
listeners + their idle-rescans called the broken path concurrently and
identically-failed at the same instant, leaving the queue doc orphaned —
which surfaced FE-side as the false "VivobookPro appears to be off" alert
when `startPipelineViaFirestore` timed out waiting for `backendRunId`.

The helper replaces the TX with `doc_ref.update(..., option=
LastUpdateOption(snap.update_time))`. Same atomicity (Firestore
single-doc writes are linearized server-side), no decorator lifecycle,
no masking. `FailedPrecondition` = clean race-loss; transient errors
retry up to N times with exponential backoff; unexpected errors log
`__context__` so the root cause is visible.

Run via:
    pytest tests/test_try_claim_queue_doc.py -v
"""
from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

import google.api_core.exceptions as gax_exc  # noqa: E402


@pytest.fixture
def silent_log(monkeypatch):
    monkeypatch.setattr("research.log", lambda *a, **kw: None)


@pytest.fixture
def fast_sleep(monkeypatch):
    """Make `time.sleep` a no-op so retry backoff doesn't slow the suite."""
    monkeypatch.setattr("research.time.sleep", lambda *_a, **_kw: None)


def _make_snap(*, exists: bool, data: dict | None = None,
               update_time: str = "ut-stub"):
    """Minimal DocumentSnapshot stub with the three fields the helper reads."""
    snap = mock.MagicMock()
    snap.exists = exists
    snap.to_dict = mock.MagicMock(return_value=data or {})
    snap.update_time = update_time
    return snap


def _make_doc_ref(*, get_returns=None, get_raises=None,
                  update_raises_seq=None):
    """Build a DocumentReference stub.

    `get_returns`: snapshot to return from .get(). Single value or list
        (consumed in sequence — for retry tests).
    `get_raises`: exception(s) to raise from .get() instead of returning.
        Single exception or list for sequential raises.
    `update_raises_seq`: sequence of exceptions (or None for success) to
        raise from .update() per call.
    """
    ref = mock.MagicMock()
    # .get() side_effect — pytest's MagicMock supports a callable or
    # exception sequence via side_effect being a list/iterable.
    if get_raises is not None:
        if not isinstance(get_raises, list):
            get_raises = [get_raises]
        ref.get = mock.MagicMock(side_effect=get_raises)
    elif get_returns is not None:
        if not isinstance(get_returns, list):
            get_returns = [get_returns]
        ref.get = mock.MagicMock(side_effect=get_returns)
    else:
        ref.get = mock.MagicMock()
    if update_raises_seq is not None:
        # Convert None entries to a sentinel that returns successfully.
        ref.update = mock.MagicMock(
            side_effect=[
                exc if exc is not None else mock.DEFAULT
                for exc in update_raises_seq
            ]
        )
    else:
        ref.update = mock.MagicMock()
    return ref


@pytest.fixture
def stub_firebase_db(monkeypatch):
    """Stub the module-global `_firebase_db.write_option(...)` so the
    helper doesn't need a real Firestore client."""
    db = mock.MagicMock()
    db.write_option = mock.MagicMock(return_value="precond-stub")
    monkeypatch.setattr(research, "_firebase_db", db)
    return db


# ─────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────

class TestTryClaimQueueDocHappyPath:
    """Vacant doc → conditional update succeeds → returns True. The
    update payload must contain exactly assignedWorker + claimedAt
    (rule enforces this via diff.hasOnly)."""

    def test_vacant_doc_claimed_returns_true(
            self, stub_firebase_db, silent_log, fast_sleep):
        snap = _make_snap(exists=True, data={}, update_time="t0")
        ref = _make_doc_ref(get_returns=snap, update_raises_seq=[None])
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is True
        # Exactly one read + one update — no transaction RPCs.
        assert ref.get.call_count == 1
        assert ref.update.call_count == 1

    def test_update_payload_includes_required_fields(
            self, stub_firebase_db, silent_log, fast_sleep):
        snap = _make_snap(exists=True, data={}, update_time="t0")
        ref = _make_doc_ref(get_returns=snap, update_raises_seq=[None])
        research._try_claim_queue_doc(ref, worker_id=7)
        # First positional arg to .update() is the patch dict.
        patch = ref.update.call_args[0][0]
        assert set(patch.keys()) == {"assignedWorker", "claimedAt"}
        assert patch["assignedWorker"] == 7
        assert isinstance(patch["claimedAt"], int)

    def test_precondition_uses_snapshot_update_time(
            self, stub_firebase_db, silent_log, fast_sleep):
        """The LastUpdateOption must be built from snap.update_time so
        Firestore rejects the write if a sibling beat us."""
        snap = _make_snap(exists=True, data={}, update_time="t-special")
        ref = _make_doc_ref(get_returns=snap, update_raises_seq=[None])
        research._try_claim_queue_doc(ref, worker_id=1)
        stub_firebase_db.write_option.assert_called_once_with(
            last_update_time="t-special")
        # And the precondition object is passed to .update().
        assert ref.update.call_args.kwargs.get("option") == "precond-stub"


# ─────────────────────────────────────────────────────────────────────
# Race-loss paths (all return False, no error)
# ─────────────────────────────────────────────────────────────────────

class TestTryClaimQueueDocRaceLoss:
    """Sibling beat us / doc gone / already-claimed → return False
    cleanly. No retry, no warn log — these are expected paths."""

    def test_already_assigned_returns_false_no_update(
            self, stub_firebase_db, silent_log, fast_sleep):
        snap = _make_snap(exists=True, data={"assignedWorker": 2})
        ref = _make_doc_ref(get_returns=snap)
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is False
        ref.update.assert_not_called()  # short-circuit before update

    def test_already_processed_returns_false_no_update(
            self, stub_firebase_db, silent_log, fast_sleep):
        snap = _make_snap(exists=True, data={"processed": True})
        ref = _make_doc_ref(get_returns=snap)
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is False
        ref.update.assert_not_called()

    def test_doc_not_exists_returns_false(
            self, stub_firebase_db, silent_log, fast_sleep):
        snap = _make_snap(exists=False)
        ref = _make_doc_ref(get_returns=snap)
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is False
        ref.update.assert_not_called()

    def test_failed_precondition_on_update_returns_false(
            self, stub_firebase_db, silent_log, fast_sleep):
        """Sibling updated the doc between our read and write — Firestore
        rejects with FailedPrecondition. That's the expected race-loss
        path; return False without retry."""
        snap = _make_snap(exists=True, data={}, update_time="t0")
        ref = _make_doc_ref(
            get_returns=snap,
            update_raises_seq=[gax_exc.FailedPrecondition("doc changed")],
        )
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is False
        # NO retry on FailedPrecondition — single update attempt.
        assert ref.update.call_count == 1

    def test_not_found_on_update_returns_false(
            self, stub_firebase_db, silent_log, fast_sleep):
        """Owner deleted the doc between our read and write. Not an
        error — just race-loss to the owner's cancel."""
        snap = _make_snap(exists=True, data={}, update_time="t0")
        ref = _make_doc_ref(
            get_returns=snap,
            update_raises_seq=[gax_exc.NotFound("gone")],
        )
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is False

    def test_get_not_found_returns_false(
            self, stub_firebase_db, silent_log, fast_sleep):
        """Doc deleted before we read. Race-loss."""
        ref = _make_doc_ref(get_raises=gax_exc.NotFound("gone"))
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is False


# ─────────────────────────────────────────────────────────────────────
# Retry on transient errors
# ─────────────────────────────────────────────────────────────────────

class TestTryClaimQueueDocRetry:
    """Transient gRPC errors retry up to max_attempts with backoff. After
    exhaustion, return None (not False — caller distinguishes race-loss
    from system error)."""

    def test_transient_on_get_then_success(
            self, stub_firebase_db, silent_log, fast_sleep):
        """First .get() raises ServiceUnavailable, second succeeds."""
        snap = _make_snap(exists=True, data={}, update_time="t0")
        ref = _make_doc_ref(
            get_raises=[gax_exc.ServiceUnavailable("blip"), snap],
            update_raises_seq=[None],
        )
        result = research._try_claim_queue_doc(ref, worker_id=1, max_attempts=3)
        assert result is True
        assert ref.get.call_count == 2

    def test_unauthenticated_on_get_retries(
            self, stub_firebase_db, silent_log, fast_sleep):
        """The exact failure pattern we observed: synth-user JWT blip
        produces UNAUTHENTICATED on the read RPC."""
        snap = _make_snap(exists=True, data={}, update_time="t0")
        ref = _make_doc_ref(
            get_raises=[gax_exc.Unauthenticated("auth blip"), snap],
            update_raises_seq=[None],
        )
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is True
        assert ref.get.call_count == 2

    def test_all_transient_attempts_fail_returns_none(
            self, stub_firebase_db, silent_log, fast_sleep):
        """3 attempts, all ServiceUnavailable on read → return None so
        caller logs + skips + lets idle-rescan retry on the next loop."""
        ref = _make_doc_ref(
            get_raises=[
                gax_exc.ServiceUnavailable("blip 1"),
                gax_exc.ServiceUnavailable("blip 2"),
                gax_exc.ServiceUnavailable("blip 3"),
            ],
        )
        result = research._try_claim_queue_doc(ref, worker_id=1, max_attempts=3)
        assert result is None
        assert ref.get.call_count == 3

    def test_transient_on_update_retries(
            self, stub_firebase_db, silent_log, fast_sleep):
        """Read succeeds, first update gets DeadlineExceeded, second
        succeeds. Both attempts re-read the doc to re-establish a fresh
        update_time precondition."""
        snap = _make_snap(exists=True, data={}, update_time="t0")
        ref = _make_doc_ref(
            get_returns=[snap, snap],
            update_raises_seq=[
                gax_exc.DeadlineExceeded("timeout"),
                None,
            ],
        )
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is True
        assert ref.get.call_count == 2
        assert ref.update.call_count == 2


# ─────────────────────────────────────────────────────────────────────
# Unexpected error surfacing
# ─────────────────────────────────────────────────────────────────────

class TestTryClaimQueueDocUnexpectedErrors:
    """Errors that aren't transient + aren't race-loss must surface
    __context__ in the log so the root cause is visible (the prior
    TX path masked it as 'no transaction ID' ValueError)."""

    def test_unexpected_exception_returns_none_logs_root(
            self, stub_firebase_db, monkeypatch, fast_sleep):
        """A non-transient, non-race-loss error returns None and logs
        the message — including __context__ when chained."""
        captured: list[str] = []
        monkeypatch.setattr(
            "research.log",
            lambda msg, *_a, **_kw: captured.append(str(msg)),
        )
        # Build an exception with a chained __context__ to verify the
        # helper surfaces both.
        try:
            try:
                raise ValueError("real root cause: JWT expired mid-RPC")
            except ValueError:
                raise RuntimeError("masking outer")
        except RuntimeError as e:
            chained_exc = e
        ref = _make_doc_ref(get_raises=chained_exc)
        result = research._try_claim_queue_doc(ref, worker_id=1)
        assert result is None
        # Log must include both the outer name AND the root context name.
        combined = "\n".join(captured)
        assert "RuntimeError" in combined
        assert "ValueError" in combined
        assert "real root cause" in combined
