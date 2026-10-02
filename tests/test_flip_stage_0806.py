"""The run-start denial that survived its own fix, and the guard it switched off.

    [12:15:50] [grpc-heal] flip queued→ongoing …: synth-user 403 — re-minting
      token + retrying once … token+config deviceId AGREE …
    [12:15:50] [grpc-heal] … the re-minted token did NOT clear the denial
      (ValueError) — so a stale credential was not the cause
    [12:15:50] Failed to flip queued→ongoing …: PermissionDenied: 403 Missing or
      insufficient permissions. | surfaced as: The transaction has no
      transaction ID, so it cannot be rolled back.

Twenty occurrences across the corpus, zero successes, and the heal correctly
reports that the cause it was built for is not the cause.

⭐ WHICH RPC. `_Transactional._pre_commit` calls `transaction._begin(...)`
EAGERLY; `Transaction._begin` issues a real BeginTransaction RPC and only then
sets `self._id`; `Transaction._rollback` opens with
`if not self.in_progress: raise ValueError(_CANT_ROLLBACK)`, and `in_progress` is
`self._id is not None`. A denied read, a denied commit and a denied rollback all
leave `_id` set and surface as a bare PermissionDenied. So the ValueError can
only mean BeginTransaction itself was refused — before any document was touched,
and therefore upstream of every rule predicate about deviceId or ownership. That
is exactly why re-minting the token cannot help, and the log never said it.

⭐ AND THE CONSEQUENCE NOBODY HAD NOTICED. The failure path returned `None`,
documented at the call site as "legacy success — proceed". So on every run in
this corpus the terminal-status bail below it was switched off: a run cancelled,
watchdog-stopped or discarded between dequeue and pickup would have launched a
browser regardless. That guard has never once run.
"""

import inspect
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402


class _OneRecord:
    """`users/{uid}/researches/{rid}` for the worker's fallback read: a dict is
    the record, None is no record, an exception is a read that fails."""

    def __init__(self, record):
        self._record = record

    def collection(self, _name):
        return self

    document = collection

    def get(self):
        if isinstance(self._record, Exception):
            raise self._record
        rec = self._record
        return type("Snap", (), {"exists": rec is not None,
                                 "to_dict": lambda _s: dict(rec or {})})()


def _worker(monkeypatch, tmp_path, flip, record):
    """Run the real dequeue over one job; the pipelines it started."""
    from _run_server_closure import run_worker_once
    job = {"topic": "t", "email": "", "run_id": "T_20260806_101500",
           "uid": "uid-a", "research_id": "chat_1754400000000_1"}
    return run_worker_once(monkeypatch, tmp_path, job, flip=flip,
                           db=_OneRecord(record),
                           update_research=lambda *a, **k: True)


# ⛔⛔ WAVE 15 (10-02): THE FLIP IS NO LONGER A TRANSACTION. The stage this
# file named — BeginTransaction, refused before any document is touched — is
# exactly why: the rules deny this machine a transaction on the user tree, so
# the flip is now a read plus a compare-and-set update
# (tests/test_w15_lows_1002.py). The tests of `_flip_txn_stage` went with it.


class TestTheFailurePathNoLongerReadsAsSuccess:

    def test_the_flip_returns_a_distinct_error_outcome(self):
        src = inspect.getsource(research)
        i = src.index("def _flip_queued_to_ongoing(")
        j = src.index("def _recompute_queue_positions(", i)
        body = src[i:j]
        assert 'return "error"' in body, (
            "returning None here is what silently disabled the caller's "
            "terminal-status bail on every run in the corpus"
        )
        assert "return None" not in body

    # ⛔⛔ THE THREE PINS BELOW READ THE WORKER'S SOURCE UNTIL WAVE 10.10, and
    # the third held a defect in place: it required "proceeding, as before" to
    # appear TWICE in the fallback, and one of the two was the arm a record that
    # had been DELETED fell into — so the worker ran a job whose research was
    # gone, and the pin said so was correct. A read that finds no record is an
    # answer, not a failure. The worker loop is a `run_server` closure; it is
    # now lifted out and RUN (`_run_server_closure`), which the character
    # windows these used could never do.

    def test_the_caller_re_asks_instead_of_assuming(self, monkeypatch, tmp_path):
        """The flip was refused; a plain read says `stopped` — so it bails."""
        assert _worker(monkeypatch, tmp_path, "error", {"status": "stopped"}) == []

    def test_the_bail_statuses_are_still_consulted_after_the_fallback_read(
            self, monkeypatch, tmp_path):
        # Order matters: the fallback must REWRITE flip_outcome before the
        # skipped() branch reads it, or the bail still never runs — and an
        # active status read the same way still runs.
        for status in ("completed", "stopped_by_watchdog", "cancelled"):
            assert _worker(monkeypatch, tmp_path, "error", {"status": status}) == [], status
        assert len(_worker(monkeypatch, tmp_path, "error", {"status": "ongoing"})) == 1

    def test_an_unreadable_document_still_proceeds(self, monkeypatch, tmp_path):
        # Failing closed here would wedge every run behind a Firestore outage:
        # a read that RAISES, and a record with no status, both still run.
        assert len(_worker(monkeypatch, tmp_path, "error", RuntimeError("503"))) == 1
        assert len(_worker(monkeypatch, tmp_path, "error", {})) == 1

    def test_a_record_that_is_gone_is_not_an_unreadable_one(self, monkeypatch, tmp_path):
        """⛔⛔ Wave 10.10: the read succeeded and found nothing — the research
        was deleted — and that must never run."""
        assert _worker(monkeypatch, tmp_path, "error", None) == []
