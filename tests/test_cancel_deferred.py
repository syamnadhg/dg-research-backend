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
      (and, as of wave 10.9, by the start doc's own uid)
    - Delete it
    - Flip research status="stopped" + clear queuePosition / behind*

  Layer 2 — pre-claim status re-check:
    - If the research doc is already in a terminal state when the
      listener picks up the start doc, skip the claim + delete the
      doc. Closes the cross-worker race where worker A claimed +
      scheduled enqueue before the cancel handler fired.

⛔⛔ LAYER 1 USED TO TEST A COPY OF THE CODE (found 2026-09-21, wave 10.9).
Every Layer-1 test called `_inline_do_cancel`, a function in THIS file that
"replicated" the branch, and none of them called into research.py at all — so
any change to the production scan, including a member's cancel deleting
another member's queued run, left all five green. They now drive the REAL
listener callback through `_queue_listener.Listener`: a fake Firestore, one
cancel document, and a record of what the listener deleted and wrote.

⛔⛔ AND SO WAS LAYER 2, disclosed when Layer 1 was repaired and left standing
because it was out of that item's scope. Round two of cross-verify came back
for it: its ten parametrised tests called a copy of the terminal-status tuple
kept in this file, so no change to research.py could turn them red. They drive
the real start branch now, and the gate reads the module's one
`TERMINAL_RESEARCH_STATUSES` instead of keeping a second copy of the words.

Run via:
    pytest tests/test_cancel_deferred.py -v
"""
from __future__ import annotations

import pytest
from google.cloud.firestore import DELETE_FIELD

from _queue_listener import Listener

SHARER = "sharer-uid"
OWNER = "owner-uid"


def _start(rid, uid, topic):
    return {"researchId": rid, "action": "start", "topic": topic,
            "uid": uid, "submittedBy": uid}


def _cancel(rid, uid):
    return {"action": "cancel", "researchId": rid, "uid": uid, "submittedBy": uid}


# ── Layer 1: _do_cancel removed=False scan + delete + status flip ──────
#
# Every test below EXECUTES `start_firestore_start_listener`'s cancel branch.

def test_deferred_cancel_deletes_start_doc_and_flips_status(tmp_path, monkeypatch):
    """The 2026-05-22 repro. Bull Dog deferred, never claimed. Cancel
    handler scans Firestore queue, finds the start doc, deletes it,
    and flips research status to stopped."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, queue_docs={
        "qd-bulldog": _start("rid-bulldog", SHARER, "Bull Dog"),
    }).feed(**_cancel("rid-bulldog", SHARER))
    assert lis.deleted_queue_ids == ["qd-bulldog"], "start doc should be deleted"
    [(uid, rid, patch)] = lis.writes
    assert (uid, rid) == (SHARER, "rid-bulldog")
    assert patch["status"] == "stopped"
    assert patch["cancelled"] is True
    assert patch["summary"] == "Cancelled while queued"
    assert patch["queuePosition"] is DELETE_FIELD
    assert patch["queuedBehindRunId"] is DELETE_FIELD
    assert patch["queuedBehindTitle"] is DELETE_FIELD
    assert lis.incoming == ["incoming"], "the cancel doc itself is consumed"


def test_cancel_when_start_doc_already_gone_still_flips_status(tmp_path, monkeypatch):
    """Idempotency: another worker already deleted the start doc.
    Status flip must still happen so the FE banner clears even when
    the queue-scan finds nothing."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, queue_docs={}).feed(
        **_cancel("rid-bulldog", SHARER))
    assert lis.deleted_queue_ids == []
    [(uid, rid, patch)] = lis.writes
    assert (uid, rid) == (SHARER, "rid-bulldog")
    assert patch["status"] == "stopped"
    assert patch["cancelled"] is True


def test_cancel_skips_cancel_action_docs(tmp_path, monkeypatch):
    """A cancel queue doc for the same rid sitting in the collection
    must NOT be deleted by the start-doc scan (we only target action ==
    'start'). The cancel handler deletes the cancel doc itself elsewhere."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, queue_docs={
        "qd-cancel": _cancel("rid-bulldog", SHARER),
    }).feed(**_cancel("rid-bulldog", SHARER))
    # Cancel doc untouched
    assert "qd-cancel" in lis.db.queue.docs
    assert lis.deleted_queue_ids == []
    # Status still flipped
    assert lis.writes[0][2]["status"] == "stopped"


def test_removed_true_path_preserves_pre_fix_summary(tmp_path, monkeypatch):
    """The pre-existing removed=True case used to say 'Cancelled before
    starting'. Don't regress its summary phrasing — only the
    removed=False path uses the new 'Cancelled while queued'."""
    mine = {"research_id": "rid-mine", "uid": SHARER, "run_id": "Mine_run"}
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, deque_jobs=[mine],
                   queue_docs={"qd-mine": _start("rid-mine", SHARER, "Mine")}).feed(
        **_cancel("rid-mine", SHARER))
    assert list(lis.jobs._queue) == [], "the job was not taken off the local queue"
    assert lis.writes[0][2]["summary"] == "Cancelled before starting"
    # removed=True skips the Firestore scan entirely
    assert lis.deleted_queue_ids == []


def test_multiple_deferred_only_targeted_rid_deleted(tmp_path, monkeypatch):
    """Several deferred docs in the queue from different sharers — only
    the cancel target's start doc is deleted; others persist for their
    own claim path."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, queue_docs={
        "qd-bulldog": _start("rid-bulldog", SHARER, "Bull Dog"),
        "qd-stbernard": _start("rid-stbernard", OWNER, "St Bernard"),
    }).feed(**_cancel("rid-bulldog", SHARER))
    assert lis.deleted_queue_ids == ["qd-bulldog"]
    assert "qd-stbernard" in lis.db.queue.docs
    assert [w[1] for w in lis.writes] == ["rid-bulldog"]  # St Bernard untouched


def test_a_cancel_naming_another_persons_deferred_run_leaves_it(tmp_path, monkeypatch):
    """⛔⛔ wave 10.9, and the reason these tests had to stop testing a copy.
    The owner's St Bernard is deferred; a sharer signs a cancel honestly as
    themselves and names St Bernard's research id, which `queueOwners`
    publishes. The scan used to match on researchId alone and delete it."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, queue_docs={
        "qd-stbernard": _start("rid-stbernard", OWNER, "St Bernard"),
    }).feed(**_cancel("rid-stbernard", SHARER))
    assert lis.deleted_queue_ids == [], "a sharer's cancel deleted the owner's queued run"
    assert "qd-stbernard" in lis.db.queue.docs
    assert all(w[0] != OWNER for w in lis.writes)


# ── Layer 2: pre-claim status re-check ─────────────────────────────────
#
# ⛔⛔ LAYER 2 WAS A REPLICA TOO (found 2026-09-21 by wave 10.9's second
# cross-verify). `_inline_pre_claim_status_check` was a copy of the terminal
# tuple living in this file, and all ten parametrised tests called only that
# copy — so dropping `stopped_by_watchdog` from the real gate, or adding
# `paused` to it, left every one of them green. The Layer-1 repair in this wave
# did not reach them, and the commit that made it said so.
#
# ⭐ They drive the real start branch now — one start document, one research
# document carrying the status under test — and the gate itself was changed to
# read the module's single `TERMINAL_RESEARCH_STATUSES` instead of keeping a
# second copy of the words. `_research_is_terminal` is NOT stubbed here; this
# file's subject is exactly whether a run counts as over.

BULLDOG = "rid-bulldog"


def _start_with_status(tmp_path, monkeypatch, status):
    return Listener(monkeypatch, tmp_path, owner=OWNER, real_terminal_check=True,
                    research_docs={(SHARER, BULLDOG): {"status": status}}).feed(
        **_start(BULLDOG, SHARER, "Bull Dog"))


@pytest.mark.parametrize("terminal_status", [
    "stopped", "completed", "archived",
    "terminated_by_user_discard", "stopped_by_watchdog",
])
def test_pre_claim_skips_terminal_status(terminal_status, tmp_path, monkeypatch):
    """The cross-worker race window: worker A claimed + scheduled
    enqueue; cancel handler flipped research to terminal; worker A's
    listener now picks up the queue doc again on replay and must drop
    it instead of running the cancelled job.

    ⛔ THE WRITE IS THE MEASUREMENT, not the empty queue. `_safe_enqueue` keeps
    a whitelist of its own that refuses these statuses as well, so "nothing was
    enqueued" would stay true with this gate deleted. Only the gate stops the
    run BEFORE the branch stamps `backendRunId` on a finished run's document."""
    lis = _start_with_status(tmp_path, monkeypatch, terminal_status)
    assert lis.writes == [], f"a {terminal_status} run's document was written to"
    assert lis.enqueued == [], f"a {terminal_status} run was enqueued anyway"
    assert lis.incoming == ["incoming"], (
        "the queue doc was left to replay on the next listener attach")


@pytest.mark.parametrize("active_status", [
    "queued", "ongoing", "paused_backend_restart", "paused", None,
])
def test_pre_claim_proceeds_for_active_status(active_status, tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY, and the whole product: live and recovery states must
    still get past this gate. It is a narrow drop, not a broad one — widened by
    one word it would refuse a status the machine sees every day."""
    lis = _start_with_status(tmp_path, monkeypatch, active_status)
    assert [w[:2] for w in lis.writes] == [(SHARER, BULLDOG)], (
        f"a {active_status} run was dropped by the pre-claim gate")
    assert lis.writes[0][2]["backendRunId"]


@pytest.mark.parametrize("enqueueable_status", [
    "queued", "ongoing", "paused_backend_restart",
])
def test_an_active_run_reaches_the_queue(enqueueable_status, tmp_path, monkeypatch):
    """⭐ AND ALL THE WAY THROUGH, for the three statuses `_safe_enqueue` admits.
    `paused` and a missing status pass the gate above and are then refused by
    that whitelist — a distinction the replica these tests replace could not
    make, because it only ever described the gate's own tuple."""
    lis = _start_with_status(tmp_path, monkeypatch, enqueueable_status)
    assert [j["research_id"] for j in lis.enqueued] == [BULLDOG]
    assert lis.writes[0][2]["status"] == "ongoing"
