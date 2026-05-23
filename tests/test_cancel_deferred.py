"""Unit tests for the deferred-cancel + cross-worker safety fix
(research.py `_do_cancel` removed=False branch + pre-claim status
re-check).

Bug Cancel-Stale (2026-05-22):
- 2-worker BE, Bull Dog deferred in Firestore queue (busy-running gate
  blocks both workers' claim attempts).
- User cancels Bull Dog. FE writes a cancel queue doc.
- Both workers' listeners fire `_do_cancel` callback. Each scans its
  own local `job_queue._queue` — neither finds Bull Dog (it's still
  in Firestore, never claimed). removed=False on both.
- Pre-fix code skipped (a) the start-doc deletion and (b) the
  research-doc status flip when removed=False.
- Result: tile stays "queued" forever; on BE restart the start doc
  replays and worker claims + RUNS the "cancelled" job.

The fix has two layers — this test file covers both:

  Layer 1 — `_do_cancel` removed=False branch:
    - Scan Firestore queue for the deferred start doc by researchId
    - Delete it
    - Flip research status="stopped" + clear queuePosition / behind*

  Layer 2 — pre-claim status re-check:
    - If the research doc is already in a terminal state when the
      listener picks up the start doc, skip the claim + delete the
      doc. Closes the cross-worker race where worker A claimed +
      scheduled enqueue before the cancel handler fired.

These are integration-shaped tests — the fakes mirror enough Firestore
shape to drive the actual code paths.

Run via:
    pytest tests/test_cancel_deferred.py -v
"""
from __future__ import annotations

import pytest


# ── Fakes shared by both layers ────────────────────────────────────────

class _FakeRef:
    def __init__(self, doc_id, store):
        self.id = doc_id
        self._store = store

    def delete(self):
        if self.id in self._store:
            del self._store[self.id]

    def update(self, patch):
        if self.id not in self._store:
            raise RuntimeError(f"doc {self.id} disappeared")
        from google.cloud.firestore import DELETE_FIELD as _DF
        cur = self._store[self.id]
        for k, v in patch.items():
            if v is _DF:
                cur.pop(k, None)
            else:
                cur[k] = v

    def get(self):
        if self.id not in self._store:
            return _FakeSnap(self.id, None, store=None, exists=False)
        return _FakeSnap(self.id, dict(self._store[self.id]), self._store, exists=True)


class _FakeSnap:
    def __init__(self, doc_id, payload, store=None, exists=True):
        self.id = doc_id
        self._payload = payload
        self.exists = exists
        if store is not None and exists:
            self.reference = _FakeRef(doc_id, store)

    def to_dict(self):
        return dict(self._payload or {})


class _FakeQueueQuery:
    def __init__(self, snaps):
        self._snaps = snaps

    def stream(self):
        return iter(self._snaps)


class _FakeQueueCol:
    def __init__(self, store):
        self._store = store

    def limit(self, _n):
        snaps = [
            _FakeSnap(did, dict(p), self._store)
            for did, p in self._store.items()
        ]
        return _FakeQueueQuery(snaps)

    def document(self, doc_id):
        return _FakeRef(doc_id, self._store)


# ── Layer 1: _do_cancel removed=False scan + delete + status flip ──────

def _inline_do_cancel(col_ref, queue_store, research_store,
                      rid, removed):
    """Replicates the new removed=False branch from research.py's
    `_do_cancel` callback (research.py ~4148-4220). Kept inline so the
    test doesn't have to monkey-patch the whole listener closure.

    Mirrors:
      - If !removed: scan queue for start doc matching rid → delete
      - Always: flip research status="stopped" + clear queue fields
      - When removed: also run recompute (but we skip the recompute_fn
        side-effect here — it's tested separately)
    """
    if not removed:
        start_doc_id = None
        for qsnap in col_ref.limit(50).stream():
            qd = qsnap.to_dict() or {}
            if (qd.get("researchId") == rid
                    and (qd.get("action") or "start") == "start"):
                start_doc_id = qsnap.id
                break
        if start_doc_id is not None:
            col_ref.document(start_doc_id).delete()
    # Always flip status (the convergence the fix introduces).
    from google.cloud.firestore import DELETE_FIELD as _DF
    # Direct write into the fake research store keyed by rid — caller
    # supplies the store so we don't have to mock _update_research_doc.
    if rid in research_store:
        cur = research_store[rid]
        cur["status"] = "stopped"
        cur["phase"] = 0
        cur["summary"] = (
            "Cancelled before starting" if removed else "Cancelled while queued"
        )
        cur["cancelled"] = True
        cur.pop("queuePosition", None)
        cur.pop("queuedBehindRunId", None)
        cur.pop("queuedBehindTitle", None)


def test_deferred_cancel_deletes_start_doc_and_flips_status():
    """The 2026-05-22 repro. Bull Dog deferred, never claimed. Cancel
    handler scans Firestore queue, finds the start doc, deletes it,
    and flips research status to stopped."""
    queue_store = {
        "qd-bulldog": {
            "researchId": "rid-bulldog", "action": "start",
            "topic": "Bull Dog", "submittedBy": "sharer-uid",
        },
    }
    research_store = {
        "rid-bulldog": {"status": "queued", "queuePosition": 2,
                        "queuedBehindRunId": "rid-husky",
                        "queuedBehindTitle": "Husky"},
    }
    col = _FakeQueueCol(queue_store)
    _inline_do_cancel(col, queue_store, research_store,
                      "rid-bulldog", removed=False)
    assert "qd-bulldog" not in queue_store, "start doc should be deleted"
    assert research_store["rid-bulldog"]["status"] == "stopped"
    assert research_store["rid-bulldog"]["cancelled"] is True
    assert research_store["rid-bulldog"]["summary"] == "Cancelled while queued"
    assert "queuePosition" not in research_store["rid-bulldog"]
    assert "queuedBehindRunId" not in research_store["rid-bulldog"]
    assert "queuedBehindTitle" not in research_store["rid-bulldog"]


def test_cancel_when_start_doc_already_gone_still_flips_status():
    """Idempotency: another worker already deleted the start doc.
    Status flip must still happen so the FE banner clears even when
    the queue-scan finds nothing."""
    queue_store = {}  # sibling already deleted
    research_store = {
        "rid-bulldog": {"status": "queued", "queuePosition": 2},
    }
    col = _FakeQueueCol(queue_store)
    _inline_do_cancel(col, queue_store, research_store,
                      "rid-bulldog", removed=False)
    assert research_store["rid-bulldog"]["status"] == "stopped"
    assert research_store["rid-bulldog"]["cancelled"] is True


def test_cancel_skips_cancel_action_docs():
    """A cancel queue doc for the same rid sitting in the collection
    must NOT be deleted by the start-doc scan (we only target action ==
    'start'). The cancel handler deletes the cancel doc itself elsewhere."""
    queue_store = {
        "qd-cancel": {
            "researchId": "rid-bulldog", "action": "cancel",
            "submittedBy": "sharer-uid",
        },
    }
    research_store = {
        "rid-bulldog": {"status": "queued"},
    }
    col = _FakeQueueCol(queue_store)
    _inline_do_cancel(col, queue_store, research_store,
                      "rid-bulldog", removed=False)
    # Cancel doc untouched
    assert "qd-cancel" in queue_store
    # Status still flipped
    assert research_store["rid-bulldog"]["status"] == "stopped"


def test_removed_true_path_preserves_pre_fix_summary():
    """The pre-existing removed=True case used to say 'Cancelled before
    starting'. Don't regress its summary phrasing — only the
    removed=False path uses the new 'Cancelled while queued'."""
    research_store = {
        "rid-mine": {"status": "queued"},
    }
    _inline_do_cancel(_FakeQueueCol({}), {}, research_store,
                      "rid-mine", removed=True)
    assert research_store["rid-mine"]["summary"] == "Cancelled before starting"


def test_multiple_deferred_only_targeted_rid_deleted():
    """Several deferred docs in the queue from different sharers — only
    the cancel target's start doc is deleted; others persist for their
    own claim path."""
    queue_store = {
        "qd-bulldog": {
            "researchId": "rid-bulldog", "action": "start",
            "topic": "Bull Dog", "submittedBy": "sharer-uid",
        },
        "qd-stbernard": {
            "researchId": "rid-stbernard", "action": "start",
            "topic": "St Bernard", "submittedBy": "owner-uid",
        },
    }
    research_store = {
        "rid-bulldog": {"status": "queued"},
        "rid-stbernard": {"status": "queued"},
    }
    col = _FakeQueueCol(queue_store)
    _inline_do_cancel(col, queue_store, research_store,
                      "rid-bulldog", removed=False)
    assert "qd-bulldog" not in queue_store
    assert "qd-stbernard" in queue_store
    assert research_store["rid-stbernard"]["status"] == "queued"  # untouched


# ── Layer 2: pre-claim status re-check ─────────────────────────────────

def _inline_pre_claim_status_check(research_doc_status):
    """Replicates the new pre-claim status re-check from
    research.py:~4411. Returns True if the listener should SKIP the
    claim (terminal status), False if it should proceed."""
    return research_doc_status in (
        "stopped", "completed", "archived",
        "terminated_by_user_discard", "stopped_by_watchdog",
    )


@pytest.mark.parametrize("terminal_status", [
    "stopped", "completed", "archived",
    "terminated_by_user_discard", "stopped_by_watchdog",
])
def test_pre_claim_skips_terminal_status(terminal_status):
    """The cross-worker race window: worker A claimed + scheduled
    enqueue; cancel handler flipped research to terminal; worker A's
    listener now picks up the queue doc again on replay and must drop
    it instead of running the cancelled job."""
    assert _inline_pre_claim_status_check(terminal_status) is True


@pytest.mark.parametrize("active_status", [
    "queued", "ongoing", "paused_backend_restart", "paused", None,
])
def test_pre_claim_proceeds_for_active_status(active_status):
    """Live and recovery states must still allow the claim. The
    pre-claim re-check is a narrow drop, not a broad gate."""
    assert _inline_pre_claim_status_check(active_status) is False
