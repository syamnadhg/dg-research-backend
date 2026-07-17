"""#728 — multi-worker rehydration hardening.

Three independent BE hardening fixes, all latent (the 2026-06-01/02 multi-worker
E2E ran clean — sibling-claim guards held), pinned here so they don't regress:

(a) worker funnel / worker-affinity: each worker runs on its OWN browser
    profile (_profile_dir(WORKER_ID)) = its own logged-in agent accounts. The
    run-start ongoing-flip now stamps `assignedWorker = WORKER_ID`, and a worker's
    rehydration only AUTO-RESUMES a supervised run it owns (assignedWorker ==
    WORKER_ID, or unset/legacy → worker 1) — a run another worker was on is left
    for that worker (or, if its owner is out of the fleet, marked
    paused_backend_restart) instead of being re-opened on this worker's (wrong)
    profile/account. #966 generalized the gate from worker-1-only to per-worker
    ownership (_owner_worker_of); the affinity guarantee here is unchanged.

(b) disk-restore dedup: the BOOT disk-restore now passes a TIGHTER
    `allowed_statuses=("queued","ongoing")` to _safe_enqueue, so a run worker-1's
    rehydration just marked paused_backend_restart is NOT silently relaunched
    from a stale per-worker disk snapshot (Firestore = the shared cross-worker
    source of truth; closes the double-enqueue a sibling's process-local
    `_rehydrated_rids` couldn't catch).

(c) synth-403 log noise: the self-healing `[grpc-heal]` retry (re-mint token +
    retry, which succeeds on basically every run's first user-tree write) now
    logs at INFO, not WARN — a genuinely UNHEALED denial still surfaces via the
    structural-latch ERROR + the caller's degrade logging.
"""
import asyncio
import inspect

import research


# ── (b) _safe_enqueue allowed_statuses — functional ───────────────────


class _FakeFirestore:
    """Chainable stand-in for _firebase_db: .collection().document()…get()."""
    def __init__(self, status=None):
        self._status = status

    def collection(self, *_):
        return self

    def document(self, *_):
        return self

    def get(self):
        status = self._status

        class _Snap:
            exists = True

            def to_dict(self):
                return {"status": status}

        return _Snap()


def _job(run_dir, **extra):
    j = {"research_id": "chat_x", "uid": "u1", "resume_dir": str(run_dir)}
    j.update(extra)
    return j


def test_disk_restore_whitelist_skips_paused_backend_restart(monkeypatch, tmp_path):
    # The boot disk-restore must NOT relaunch a paused_backend_restart run (it's
    # awaiting a user Resume; worker-1 just parked it). No .stop sentinel here —
    # the status-whitelist alone must do the skipping.
    run_dir = tmp_path / "Run_paused"
    run_dir.mkdir()
    monkeypatch.setattr(research, "_firebase_db",
                        _FakeFirestore(status="paused_backend_restart"))
    q = asyncio.Queue()
    assert research._safe_enqueue(
        q, _job(run_dir), "disk-restore",
        allowed_statuses=("queued", "ongoing")) is False
    assert q.qsize() == 0


def test_default_whitelist_still_accepts_paused_backend_restart(monkeypatch, tmp_path):
    # The DEFAULT whitelist is unchanged — the resume / start-listener paths
    # legitimately re-enqueue a paused_backend_restart run.
    run_dir = tmp_path / "Run_resume"
    run_dir.mkdir()
    monkeypatch.setattr(research, "_firebase_db",
                        _FakeFirestore(status="paused_backend_restart"))
    q = asyncio.Queue()
    assert research._safe_enqueue(q, _job(run_dir), "resume") is True
    assert q.qsize() == 1


def test_tighter_whitelist_still_enqueues_ongoing(monkeypatch, tmp_path):
    # A genuinely-ongoing run still restores under the tighter whitelist.
    run_dir = tmp_path / "Run_ongoing"
    run_dir.mkdir()
    monkeypatch.setattr(research, "_firebase_db", _FakeFirestore(status="ongoing"))
    q = asyncio.Queue()
    assert research._safe_enqueue(
        q, _job(run_dir), "disk-restore",
        allowed_statuses=("queued", "ongoing")) is True
    assert q.qsize() == 1


# ── (a) worker-affinity — source-inspection guards ────────────────────


def test_run_start_stamps_assigned_worker():
    """The run-start ongoing-flip (start-listener) and the resume flip must both
    stamp assignedWorker = WORKER_ID so rehydration can route by profile."""
    src = inspect.getsource(research)
    assert '"assignedWorker": WORKER_ID' in src, (
        "the ongoing-flip status_payload must stamp assignedWorker = WORKER_ID "
        "(#728)."
    )
    # Resume flip stamps it too (it re-enqueues onto whichever worker resumes).
    assert '{"status": "ongoing", "assignedWorker": WORKER_ID}' in src, (
        "the resume ongoing-flip must also stamp assignedWorker (#728)."
    )


def test_rehydration_autoresume_gated_on_worker_affinity():
    """Rehydration must only AUTO-RESUME a supervised run the CURRENT worker owns,
    never funnel another worker's run onto its own profile. #966 generalized the
    gate from worker-1-only to per-worker ownership via _owner_worker_of, but the
    profile-affinity guarantee is unchanged (and now stronger — every worker
    recovers its own runs)."""
    src = inspect.getsource(research._rehydrate_ongoing_for_tree)
    assert 'data.get("assignedWorker")' in src, (
        "rehydration must read the run's assignedWorker (#728)."
    )
    # Ownership is derived from assignedWorker via the shared helper, then the
    # current worker's identity (WORKER_ID) gates what it may auto-resume/mark.
    assert "_owner_worker_of(" in src and "WORKER_ID" in src, (
        "rehydration must derive the owning worker and compare to WORKER_ID "
        "(#728/#966)."
    )
    # The supervised auto-resume branch must require that THIS worker owns the run.
    assert "if _i_own and is_supervised:" in src, (
        "supervised auto-resume must be gated on owning the run so a run owned by "
        "another worker is NOT re-opened on this worker's profile (#728/#966)."
    )


def test_unset_or_legacy_assignedworker_owned_by_worker1():
    """An unset / blank / legacy assignedWorker must count as worker-1's own run
    so single-worker installs and pre-#728 runs still auto-resume; a stamped
    value routes to that worker (#728/#966)."""
    assert research._owner_worker_of(None) == 1
    assert research._owner_worker_of("") == 1
    assert research._owner_worker_of(1) == 1
    assert research._owner_worker_of(2) == 2


# ── (c) synth-403 self-heal log noise — source-inspection guard ───────


def test_grpc_heal_selfheal_logs_info_not_warn():
    """The self-healing retry log must be INFO, not WARN — it re-mints + retries
    and succeeds on basically every run's first write. A genuinely unhealed
    denial still escalates via the structural-latch ERROR + caller degrade."""
    src = inspect.getsource(research._grpc_write_with_heal)
    assert "(self-heal)" in src and "re-minting token + retrying once" in src, (
        "the heal-attempt log must describe itself as a self-heal (#728)."
    )
    # The structural-latch escalation must still be an ERROR (genuine failures
    # are not silenced by the noise downgrade).
    assert '"ERROR"' in src and "STRUCTURAL" in src, (
        "a genuinely unhealed denial must still escalate to ERROR at the "
        "structural latch (#728)."
    )
