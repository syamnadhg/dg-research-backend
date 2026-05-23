"""Unit tests for `_compute_global_queue_position` — the device-wide
FIFO position calculator that replaces the FE's per-user
`existingQueuedCount` (which only sees the submitter's own runs) and the
BE's per-worker `job_queue.qsize()+1` (which misses the sibling worker's
backlog).

Bug context (2026-05-22 5-run repro):
  - Owner: Golden, German, Husky, St Bernard
  - Sharer: Bull Dog
  - Both workers busy on Golden+German; Husky, Bull Dog, St Bernard
    arrive as deferred queue docs in that timestamp order.
  - Owner's FE displayed St Bernard as #2 (only saw Husky) — should
    have been #3.
  - Sharer's FE displayed Bull Dog as #1 (no own queue) — should have
    been #2.

The helper scans `devices/{id}/queue/` candidates, sorts by FIFO key
(timestamp ASC, doc-id tiebreaker), filters out claimed-by-sibling /
processed / non-start docs (matching the existing pre-claim filter at
research.py:4226), and returns the doc's 1-indexed position + the
immediately-prior doc's research-id/topic for the "behind X" label.

Run via:
    pytest tests/test_global_queue_position.py -v
"""
from __future__ import annotations

import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import (  # noqa: E402
    _compute_global_queue_position,
    _queue_doc_fifo_ms,
)


class _FakeServerTs:
    """Stand-in for a Firestore Timestamp / DatetimeWithNanoseconds —
    exposes `.timestamp()` returning unix seconds (float). Real returns
    a datetime subclass; we only depend on `.timestamp()` so the fake
    just needs that one method."""

    def __init__(self, epoch_ms: int):
        self._epoch_ms = epoch_ms

    def timestamp(self) -> float:
        return self._epoch_ms / 1000.0


# ── Fakes ──────────────────────────────────────────────────────────────

class _FakeSnap:
    """Minimal stand-in for a Firestore DocumentSnapshot. Carries an id +
    a payload dict; `to_dict()` returns the payload."""
    def __init__(self, doc_id: str, payload: "dict[str, Any]"):
        self.id = doc_id
        self._payload = payload

    def to_dict(self):
        return dict(self._payload)


class _FakeColRef:
    """Fake collection ref. `limit(N).stream()` returns the configured
    snaps. We don't need true Firestore-server-side ordering; the
    helper sorts client-side via `_fifo_key`."""
    def __init__(self, snaps: "list[_FakeSnap]", raise_on_stream: bool = False):
        self._snaps = snaps
        self._raise = raise_on_stream

    def limit(self, _n):
        return self

    def stream(self):
        if self._raise:
            raise RuntimeError("simulated Firestore unavailability")
        return iter(self._snaps)


def _q_doc(doc_id, *, timestamp_ms, topic, research_id, submitted_by="user",
           action="start", assigned_worker=None, processed=False,
           submitted_at_ms=None):
    """Helper to assemble a queue-doc payload. `submitted_at_ms` populates
    the Firestore `serverTimestamp()` field; legacy callers omit it and
    only carry the client-side `timestamp`. When set, it's the
    authoritative ordering key (matches production buildQueuePayload)."""
    p = {
        "timestamp": timestamp_ms,
        "topic": topic,
        "researchId": research_id,
        "submittedBy": submitted_by,
        "action": action,
        "processed": processed,
    }
    if submitted_at_ms is not None:
        p["submittedAt"] = _FakeServerTs(submitted_at_ms)
    if assigned_worker is not None:
        p["assignedWorker"] = assigned_worker
    return _FakeSnap(doc_id, p)


# ── The actual repro scenario ──────────────────────────────────────────

def test_repro_scenario_global_position_matches_user_expectation():
    """The 2026-05-22 5-run scenario. Husky (owner) is queue head, Bull
    Dog (sharer) is #2, St Bernard (owner) is #3. The FE was getting
    Bull Dog=1, St Bernard=2 because each FE only saw its own user's
    queue. With the global helper, both get the correct device-wide
    number.

    Golden + German have been claimed (assignedWorker set), so they're
    excluded from the queue (they're "running", not "queued").
    """
    snaps = [
        _q_doc("qd-golden", timestamp_ms=1_000, topic="Golden Retriever",
               research_id="rid-1", submitted_by="owner-uid",
               assigned_worker=2),  # claimed → excluded
        _q_doc("qd-german", timestamp_ms=2_000, topic="German Shepherd",
               research_id="rid-2", submitted_by="owner-uid",
               assigned_worker=1),  # claimed → excluded
        _q_doc("qd-husky", timestamp_ms=3_000, topic="Husky",
               research_id="rid-3", submitted_by="owner-uid"),
        _q_doc("qd-bulldog", timestamp_ms=4_000, topic="Bull Dog",
               research_id="rid-4", submitted_by="sharer-uid"),
        _q_doc("qd-stbernard", timestamp_ms=5_000, topic="St Bernard",
               research_id="rid-5", submitted_by="owner-uid"),
    ]
    col = _FakeColRef(snaps)

    # Husky perspective
    pos, behind_rid, behind_title = _compute_global_queue_position(col, "qd-husky")
    assert pos == 1
    assert behind_rid == ""  # head — no doc ahead
    assert behind_title == ""

    # Bull Dog perspective (was wrongly 1, should be 2)
    pos, behind_rid, behind_title = _compute_global_queue_position(col, "qd-bulldog")
    assert pos == 2, f"Bull Dog should be position 2, got {pos}"
    assert behind_rid == "rid-3"
    assert behind_title == "Husky"

    # St Bernard perspective (was wrongly 2, should be 3)
    pos, behind_rid, behind_title = _compute_global_queue_position(col, "qd-stbernard")
    assert pos == 3, f"St Bernard should be position 3, got {pos}"
    assert behind_rid == "rid-4"
    assert behind_title == "Bull Dog"


# ── Filter behavior ────────────────────────────────────────────────────

def test_processed_docs_excluded():
    snaps = [
        _q_doc("qd-a", timestamp_ms=1_000, topic="A", research_id="rid-a", processed=True),
        _q_doc("qd-b", timestamp_ms=2_000, topic="B", research_id="rid-b"),
    ]
    pos, behind_rid, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-b")
    # qd-a is processed → excluded → qd-b is head
    assert pos == 1
    assert behind_rid == ""


def test_sibling_claimed_docs_excluded():
    snaps = [
        _q_doc("qd-a", timestamp_ms=1_000, topic="A", research_id="rid-a",
               assigned_worker=99),
        _q_doc("qd-b", timestamp_ms=2_000, topic="B", research_id="rid-b"),
    ]
    pos, _, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-b")
    assert pos == 1


def test_self_claimed_doc_still_counted():
    """Post-claim, pre-delete window: my doc has assignedWorker = me.
    Helper must still include self so position calc works in the
    claim+queued path."""
    snaps = [
        _q_doc("qd-a", timestamp_ms=1_000, topic="A", research_id="rid-a"),
        _q_doc("qd-mine", timestamp_ms=2_000, topic="Mine", research_id="rid-mine",
               assigned_worker=1),  # self
    ]
    pos, behind_rid, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-mine")
    assert pos == 2
    assert behind_rid == "rid-a"


def test_non_start_actions_excluded():
    """Cancel/pause/resume have their own dispatch paths — they don't
    count against the queue position."""
    snaps = [
        _q_doc("qd-cancel", timestamp_ms=1_000, topic="X", research_id="rid-x",
               action="cancel"),
        _q_doc("qd-mine", timestamp_ms=2_000, topic="Mine", research_id="rid-mine"),
    ]
    pos, _, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-mine")
    assert pos == 1


# ── FIFO sort key ──────────────────────────────────────────────────────

def test_sort_by_timestamp_ascending():
    """Docs arrive in random order; helper sorts by client timestamp
    ASC so older docs land at lower positions."""
    snaps = [
        _q_doc("qd-newer", timestamp_ms=3_000, topic="Newer", research_id="rid-n"),
        _q_doc("qd-older", timestamp_ms=1_000, topic="Older", research_id="rid-o"),
        _q_doc("qd-middle", timestamp_ms=2_000, topic="Middle", research_id="rid-m"),
    ]
    pos, _, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-older")
    assert pos == 1
    pos, _, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-middle")
    assert pos == 2
    pos, _, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-newer")
    assert pos == 3


def test_missing_timestamp_legacy_docs_sort_last():
    """Legacy docs missing `timestamp` get tiebreaker key (1, 0, id) —
    sorted after all well-formed docs. Mirrors the pre-claim FIFO
    sort behavior at research.py:4226."""
    snaps = [
        _q_doc("qd-modern", timestamp_ms=2_000, topic="Modern", research_id="rid-m"),
        _FakeSnap("qd-legacy", {"topic": "Legacy", "researchId": "rid-l",
                                "action": "start"}),  # no timestamp
    ]
    pos, _, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-modern")
    assert pos == 1
    pos, behind_rid, behind_title = _compute_global_queue_position(_FakeColRef(snaps), "qd-legacy")
    assert pos == 2
    assert behind_rid == "rid-m"
    assert behind_title == "Modern"


# ── Edge cases ─────────────────────────────────────────────────────────

def test_my_doc_not_in_collection_returns_fallback():
    """Cancel landed between caller's read and helper's scan — my doc
    is gone. Safe fallback: (1, '', '')."""
    snaps = [
        _q_doc("qd-a", timestamp_ms=1_000, topic="A", research_id="rid-a"),
    ]
    pos, behind_rid, behind_title = _compute_global_queue_position(_FakeColRef(snaps), "qd-missing")
    assert pos == 1
    assert behind_rid == ""
    assert behind_title == ""


def test_firestore_unavailable_returns_fallback():
    """Best-effort: on Firestore error, return head semantics (safer
    than a stale large number)."""
    col = _FakeColRef([], raise_on_stream=True)
    pos, behind_rid, behind_title = _compute_global_queue_position(col, "qd-mine")
    assert pos == 1
    assert behind_rid == ""
    assert behind_title == ""


def test_topic_truncated_to_60_chars():
    """Long topics get sliced — matches existing FE/BE banner truncation."""
    long_topic = "A" * 200
    snaps = [
        _q_doc("qd-ahead", timestamp_ms=1_000, topic=long_topic, research_id="rid-a"),
        _q_doc("qd-mine", timestamp_ms=2_000, topic="Mine", research_id="rid-mine"),
    ]
    pos, behind_rid, behind_title = _compute_global_queue_position(_FakeColRef(snaps), "qd-mine")
    assert pos == 2
    assert behind_title == "A" * 60
    assert behind_rid == "rid-a"


# ── Server-timestamp ordering (clock-skew immunity) ────────────────────

def test_submitted_at_overrides_client_timestamp():
    """When both submittedAt + timestamp are set, submittedAt wins. The
    FE writes both via buildQueuePayload (legacy `timestamp` is kept for
    BE stale-queue defense at research.py:~2658); ordering MUST use the
    server-side value for clock-skew immunity."""
    snaps = [
        # Client says A is older (1_000ms) but server says it landed
        # LATER (10_000ms). Server-side ordering must put A second.
        _q_doc("qd-a", timestamp_ms=1_000, submitted_at_ms=10_000,
               topic="A", research_id="rid-a"),
        _q_doc("qd-b", timestamp_ms=2_000, submitted_at_ms=2_000,
               topic="B", research_id="rid-b"),
    ]
    pos, behind_rid, behind_title = _compute_global_queue_position(_FakeColRef(snaps), "qd-a")
    assert pos == 2, (
        "submittedAt should override the client `timestamp` — "
        "qd-a's server timestamp (10s) is later than qd-b's (2s)"
    )
    assert behind_rid == "rid-b"
    assert behind_title == "B"


def test_clock_skew_repro_owner_vs_sharer():
    """The 2026-05-22 follow-up scenario: sharer's browser clock is 5s
    BEHIND the owner's. Without the server-timestamp fix, the helper
    would have sorted Bull Dog (sharer, client-ts=995_000) ahead of
    Husky (owner, client-ts=1_000_000) and assigned Bull Dog=1.

    With submittedAt as the authoritative key (server stamps in actual
    arrival order: Husky at 1_001_500ms, Bull Dog at 1_002_000ms), the
    correct order is restored: Husky=1, Bull Dog=2."""
    snaps = [
        # Owner submits Husky first. Owner's clock = correct (~ms 1_000_000).
        # Husky reaches Firestore server at server-ms 1_001_500.
        _q_doc("qd-husky", timestamp_ms=1_000_000, submitted_at_ms=1_001_500,
               topic="Husky", research_id="rid-husky",
               submitted_by="owner-uid"),
        # Sharer submits Bull Dog second. Sharer's clock is 5s behind so
        # client-ms reads 995_000 — earlier than owner's. Doc still
        # reaches Firestore AFTER Husky (server-ms 1_002_000).
        _q_doc("qd-bulldog", timestamp_ms=995_000, submitted_at_ms=1_002_000,
               topic="Bull Dog", research_id="rid-bulldog",
               submitted_by="sharer-uid"),
    ]
    pos, behind_rid, behind_title = _compute_global_queue_position(_FakeColRef(snaps), "qd-husky")
    assert pos == 1, "Husky should be head despite owner's later client clock"
    pos, behind_rid, behind_title = _compute_global_queue_position(_FakeColRef(snaps), "qd-bulldog")
    assert pos == 2, "Bull Dog should be #2 — sharer's lagging clock must not push it ahead"
    assert behind_rid == "rid-husky"
    assert behind_title == "Husky"


def test_legacy_doc_without_submitted_at_falls_back_to_timestamp():
    """A queue doc that pre-dates the server-timestamp rollout has only
    `timestamp`. The helper must still order it relative to modern docs
    via the client-ms field (not last-place)."""
    snaps = [
        _q_doc("qd-legacy", timestamp_ms=500, topic="Legacy", research_id="rid-l"),
        _q_doc("qd-modern", timestamp_ms=2_000, submitted_at_ms=2_000,
               topic="Modern", research_id="rid-m"),
    ]
    pos, _, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-legacy")
    assert pos == 1  # legacy ts=500 < modern submittedAt=2000
    pos, behind_rid, behind_title = _compute_global_queue_position(_FakeColRef(snaps), "qd-modern")
    assert pos == 2
    assert behind_rid == "rid-l"


def test_missing_both_timestamp_fields_sorts_last():
    """An anomalous doc with neither field set sinks to the bottom —
    same as the pre-fix behavior. Matches `_fifo_key` returning the
    (1, 0, id) tier."""
    snaps = [
        _q_doc("qd-modern", timestamp_ms=2_000, submitted_at_ms=2_000,
               topic="Modern", research_id="rid-m"),
        _FakeSnap("qd-broken", {"topic": "Broken", "researchId": "rid-b",
                                "action": "start"}),
    ]
    pos, _, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-modern")
    assert pos == 1
    pos, behind_rid, _ = _compute_global_queue_position(_FakeColRef(snaps), "qd-broken")
    assert pos == 2
    assert behind_rid == "rid-m"


# ── _queue_doc_fifo_ms helper (extracted, also used by FIFO pre-query) ─

def test_helper_prefers_submitted_at():
    assert _queue_doc_fifo_ms({"submittedAt": _FakeServerTs(5_000),
                               "timestamp": 1_000}) == 5_000


def test_helper_falls_back_to_timestamp():
    assert _queue_doc_fifo_ms({"timestamp": 1_500}) == 1_500


def test_helper_returns_none_for_missing_or_invalid():
    assert _queue_doc_fifo_ms({}) is None
    assert _queue_doc_fifo_ms({"timestamp": 0}) is None  # invalid
    assert _queue_doc_fifo_ms({"timestamp": -1}) is None  # invalid
    assert _queue_doc_fifo_ms({"timestamp": "not-a-number"}) is None


def test_helper_handles_submitted_at_without_timestamp_method():
    """Defensive: if submittedAt is some other type that doesn't expose
    `.timestamp()`, fall through to the client timestamp without
    raising."""
    class _BadServerTs:
        pass

    d = {"submittedAt": _BadServerTs(), "timestamp": 2_000}
    assert _queue_doc_fifo_ms(d) == 2_000
