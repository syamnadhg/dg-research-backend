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

import pytest

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

    def test_the_caller_re_asks_instead_of_assuming(self):
        src = inspect.getsource(research)
        i = src.index("flip_outcome = _flip_queued_to_ongoing(")
        block = src[i:i + 2600]
        assert 'if flip_outcome == "error":' in block
        assert "a plain read says" in block

    def test_the_bail_statuses_are_still_consulted_after_the_fallback_read(self):
        src = inspect.getsource(research)
        i = src.index("flip_outcome = _flip_queued_to_ongoing(")
        block = src[i:i + 3200]
        # Order matters: the fallback must REWRITE flip_outcome before the
        # skipped() branch reads it, or the bail still never runs.
        assert block.index('if flip_outcome == "error":') < block.index(
            'if flip_outcome and flip_outcome.startswith("skipped(")')

    def test_an_unreadable_document_still_proceeds(self):
        # Failing closed here would wedge every run behind a Firestore outage.
        # Both arms of the fallback — doc missing, and read raised — must say so.
        src = inspect.getsource(research)
        i = src.index('if flip_outcome == "error":')
        # Whitespace collapsed: the two messages are wrapped differently across
        # source lines, and a raw count would find only the unwrapped one.
        block = " ".join(src[i:i + 1400].split())
        assert block.count("proceeding, as before") == 2, block


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
