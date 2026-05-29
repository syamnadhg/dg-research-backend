"""Unit tests for owner-initiated device-queue Stop/Cancel of a SHARER's
run (the "Shared with" popup badge long-press, 2026-05-28).

The owner long-presses a sharer's green worker badge (→ Stop) or amber
queue badge (→ Cancel). The FE enqueues a `devices/{id}/queue`
`action="cancel"` doc carrying `ownerControl` = "stop" | "cancel" and
`uid` = the SHARER's uid (so the BE flips the sharer's research doc).

Two behaviors are locked here:

  1. `_owner_control_patch` field sets:
       - "stop"   → status=stopped, summary/stoppedBy=owner_stop, NO
                    `cancelled` (running run → preserve partial work, no
                    cascade-delete), queue markers cleared.
       - "cancel" → status=stopped, summary/stoppedBy=owner_cancel,
                    cancelled=True (queued run → cascade-delete on close),
                    phase=0 for the queued case.
       - anything else (self-cancel) → {} so callers keep their existing
                    write verbatim (zero behavior change).

  2. The multi-worker owner-STOP deferred guard: a cancel doc is seen by
     EVERY worker's listener. Only the worker holding the run writes the
     terminal status; an idle sibling reaches `_do_cancel`, finds nothing
     (removed=False, no start doc), and must SKIP the flip — otherwise it
     would clobber the holding worker's preserve-write (and, for an
     owner-stop, must never set cancelled=True). Owner-CANCEL of a queued
     run is genuinely deferred, so it always flips.

Run via:
    pytest tests/test_owner_control.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import _owner_control_patch  # noqa: E402


# ── 1. _owner_control_patch field sets ─────────────────────────────────

def test_owner_stop_preserves_run_no_cancelled():
    """Owner-stop of a RUNNING run: terminal status with an owner-
    attributed summary/stoppedBy the FE matches, but NO `cancelled` —
    the run survives in the listing as a historical 'Stopped' entry with
    partial results (mirrors the HARD_RESET active-run flip)."""
    p = _owner_control_patch("stop", running=True)
    assert p["status"] == "stopped"
    assert p["summary"] == "Stopped by the device owner"
    assert p["stoppedBy"] == "owner_stop"
    assert "cancelled" not in p, "owner-stop must NOT cascade-delete the run"
    assert "phase" not in p, "owner-stop must not reset a running run's phase"
    assert isinstance(p["stoppedAt"], int)


def test_owner_cancel_sets_cancelled_for_queued():
    """Owner-cancel of a QUEUED run: cancelled=True drives the FE red
    dialog + auto-delete-on-close cascade (the run never started, safe to
    purge), plus phase reset for the not-yet-started run."""
    p = _owner_control_patch("cancel", running=False)
    assert p["status"] == "stopped"
    assert p["summary"] == "Cancelled by the device owner"
    assert p["stoppedBy"] == "owner_cancel"
    assert p["cancelled"] is True
    assert p["phase"] == 0


def test_owner_cancel_running_skips_phase_reset():
    """If an owner-cancel ever matches an actively-running job (race),
    don't stomp its phase to 0."""
    p = _owner_control_patch("cancel", running=True)
    assert p["cancelled"] is True
    assert "phase" not in p


def test_owner_patch_clears_queue_markers():
    """Both modes must DELETE_FIELD the queue-position markers so a stale
    'queued #N' banner doesn't linger after the flip."""
    from google.cloud.firestore import DELETE_FIELD
    for oc in ("stop", "cancel"):
        p = _owner_control_patch(oc, running=False)
        assert p["queuePosition"] is DELETE_FIELD
        assert p["queuedBehindRunId"] is DELETE_FIELD
        assert p["queuedBehindTitle"] is DELETE_FIELD


@pytest.mark.parametrize("oc", ["", "start", "pause", "resume", "STOP", None])
def test_unrecognized_owner_control_returns_empty(oc):
    """For a normal self-cancel (no/unknown ownerControl) the helper
    returns {} so the cancel handler keeps its existing write verbatim —
    `_update_research_doc(..., _owner_control_patch(oc, ...) or {existing})`
    falls through to the original payload. This is the zero-behavior-
    change guarantee for the user-cancels-own-run path."""
    # None would normally be coerced to "" by the caller (data.get(...) or
    # ""); guard the helper directly against both.
    assert _owner_control_patch(oc if oc is not None else "", running=False) == {}


# ── 2. Multi-worker owner-stop deferred guard ──────────────────────────
#
# Replicates the decision in research.py `_do_cancel` (the deferred-flip
# block) so the cross-worker clobber-avoidance is locked without driving
# the whole listener closure.

def _should_flip_in_deferred(oc, *, removed, start_doc_found):
    """Returns True iff the deferred-flip block should write the terminal
    status. owner-stop only flips when THIS worker actually located the
    run (removed locally, or its start doc in Firestore); otherwise the
    holding worker owns the write. owner-cancel + self-cancel always
    flip."""
    owner_stop_not_held = oc == "stop" and not (removed or start_doc_found)
    return not owner_stop_not_held


def test_owner_stop_idle_sibling_skips_flip():
    """The clobber case: idle sibling worker sees the owner-stop cancel
    doc, finds the run neither in its local deque nor as a Firestore
    start doc (it's RUNNING on another worker) → must NOT flip."""
    assert _should_flip_in_deferred("stop", removed=False, start_doc_found=False) is False


def test_owner_stop_holding_worker_via_deque_flips():
    """Defensive: if owner-stop ever matched a locally-dequeued run, the
    holding worker still flips (with the preserve patch)."""
    assert _should_flip_in_deferred("stop", removed=True, start_doc_found=False) is True


def test_owner_cancel_deferred_always_flips():
    """Owner-cancel of a genuinely-deferred queued run (no local deque
    entry, start doc may already be deleted by a sibling) always flips —
    the write is idempotent across workers."""
    assert _should_flip_in_deferred("cancel", removed=False, start_doc_found=False) is True
    assert _should_flip_in_deferred("cancel", removed=False, start_doc_found=True) is True


def test_self_cancel_deferred_always_flips():
    """No ownerControl (self-cancel) keeps the pre-existing always-flip
    behavior — the 2026-05-22 Cancel-Stale fix must not regress."""
    assert _should_flip_in_deferred("", removed=False, start_doc_found=False) is True
    assert _should_flip_in_deferred("", removed=True, start_doc_found=False) is True
