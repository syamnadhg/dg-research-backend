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


def _stage_fn():
    """`_flip_txn_stage` is a closure inside the worker factory; lift it out."""
    src = inspect.getsource(research)
    i = src.index("    def _flip_txn_stage(tx, root) -> str:")
    j = src.index("    def _flip_queued_to_ongoing(", i)
    body = "\n".join(ln[4:] if ln.startswith("    ") else ln
                     for ln in src[i:j].split("\n"))
    ns: dict = {}
    exec(compile(body, "<flip_stage>", "exec"), ns)
    return ns["_flip_txn_stage"]


STAGE = _stage_fn()


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


class _Tx:
    def __init__(self, tid=None):
        self._id = tid


class _Root:
    def __init__(self, dbg=""):
        self.debug_error_string = dbg


class TestTheStageIsNamed:

    def test_no_transaction_id_means_the_open_was_refused(self):
        out = STAGE(_Tx(None), None)
        assert "BeginTransaction" in out, out
        assert "not on the document read" in out, out

    def test_an_id_narrows_it_to_the_document(self):
        out = STAGE(_Tx(b"\x01\x02"), None)
        assert "read_or_commit" in out, out
        assert "BeginTransaction" not in out, out

    def test_the_grpc_detail_is_carried_when_there_is_one(self):
        out = STAGE(_Tx(b"\x01"), _Root("UNAUTHENTICATED: bad claim"))
        assert "grpc=" in out and "bad claim" in out, out

    def test_a_missing_grpc_detail_is_simply_absent(self):
        assert "grpc=" not in STAGE(_Tx(b"\x01"), _Root(""))

    def test_a_transaction_object_that_cannot_be_read_says_so(self):
        class _Hostile:
            @property
            def _id(self):
                raise RuntimeError("gone")
        out = STAGE(_Hostile(), None)
        assert "unknown" in out, out

    def test_none_is_treated_as_never_begun(self):
        # The except block may run before the transaction object exists.
        assert "BeginTransaction" in STAGE(None, None)


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


class TestTheDiagnosisIsRecordedWhereTheNextReaderWillLookFirst:

    def test_the_heal_comment_states_which_rpc_is_refused(self):
        src = inspect.getsource(research)
        i = src.index("def _flip_queued_to_ongoing(")
        block = src[i:i + 4000]
        assert "BeginTransaction RPC" in block
        assert "re-minting cannot help" in block

    def test_the_stage_is_appended_to_the_failure_line(self):
        # 2026-08-20: the line is DEBUG now and no longer calls a compensated
        # no-op a failure — it has failed on every run in the corpus while the
        # fallback read resolved the status every time. The STAGE still has to
        # ride it, which is what this test is actually for.
        src = inspect.getsource(research)
        i = src.index("could not open the queued→ongoing transaction")
        assert "_flip_txn_stage(" in src[i:i + 400]
