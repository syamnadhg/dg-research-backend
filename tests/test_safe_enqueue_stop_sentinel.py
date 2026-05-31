"""Regression: a STOPPED run must never be re-enqueued — even when the BE
can't read its Firestore status.

Incident (2026-05-31): the user stopped a "German Shepherd" run; a Firestore
reconnect then fired the #718 clean-respawn, whose boot-time disk-restore /
rehydrate funnels through `_safe_enqueue`. That helper only skips a stopped run
if it can READ the research-doc status — but the synth-device-user gets a 403
on the user-tree read, and the 403 branch FAILS OPEN ("trust the FE-side queue
write") → the stopped run was re-enqueued and re-fired all the way into P2.

Fix: `_safe_enqueue` checks the local, permission-independent `.stop` sentinel
(written by the STOP command handler + HARD_RESET) FIRST — before the Firestore
read — so a terminally-stopped run is skipped regardless of the read outcome.
These tests pin: (1) .stop wins over a readable "queued", (2) .stop wins over a
403 fail-open (THE bug), (3) no-.stop + 403 still trusts-FE-open for a fresh
submission, (4) no-.stop + readable "queued" enqueues normally.
"""
import asyncio

import research


class _FakeFirestore:
    """Chainable stand-in for _firebase_db: .collection().document()…get()."""
    def __init__(self, status=None, raise_exc=None):
        self._status = status
        self._raise = raise_exc

    def collection(self, *_):
        return self

    def document(self, *_):
        return self

    def get(self):
        if self._raise is not None:
            raise self._raise
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


def test_stop_sentinel_wins_over_readable_queued(monkeypatch, tmp_path):
    run_dir = tmp_path / "Run_A"
    run_dir.mkdir()
    (run_dir / ".stop").touch()
    monkeypatch.setattr(research, "_firebase_db", _FakeFirestore(status="queued"))
    q = asyncio.Queue()
    assert research._safe_enqueue(q, _job(run_dir), "disk-restore") is False
    assert q.qsize() == 0


def test_stop_sentinel_wins_over_403_fail_open(monkeypatch, tmp_path):
    # THE incident path: status read 403s (synth user), which fails open —
    # but the .stop sentinel must still block the re-enqueue.
    run_dir = tmp_path / "Run_B"
    run_dir.mkdir()
    (run_dir / ".stop").touch()
    monkeypatch.setattr(
        research, "_firebase_db",
        _FakeFirestore(raise_exc=Exception("403 Missing or insufficient permissions")),
    )
    q = asyncio.Queue()
    assert research._safe_enqueue(q, _job(run_dir), "disk-restore") is False
    assert q.qsize() == 0


def test_403_without_stop_still_trusts_fe(monkeypatch, tmp_path):
    # Preserve the intended trust-FE-open behavior: a fresh submission with NO
    # .stop and a 403 read must still enqueue (the start-listener case).
    run_dir = tmp_path / "Run_C"
    run_dir.mkdir()  # no .stop
    monkeypatch.setattr(
        research, "_firebase_db",
        _FakeFirestore(raise_exc=Exception("403 PERMISSION_DENIED")),
    )
    q = asyncio.Queue()
    assert research._safe_enqueue(q, _job(run_dir), "start-listener") is True
    assert q.qsize() == 1


def test_readable_queued_without_stop_enqueues(monkeypatch, tmp_path):
    run_dir = tmp_path / "Run_D"
    run_dir.mkdir()  # no .stop
    monkeypatch.setattr(research, "_firebase_db", _FakeFirestore(status="queued"))
    q = asyncio.Queue()
    assert research._safe_enqueue(q, _job(run_dir), "disk-restore") is True
    assert q.qsize() == 1


def test_readable_stopped_status_still_skips(monkeypatch, tmp_path):
    # The pre-existing status-whitelist guard still works when the read succeeds.
    run_dir = tmp_path / "Run_E"
    run_dir.mkdir()  # no .stop, but Firestore says stopped
    monkeypatch.setattr(research, "_firebase_db", _FakeFirestore(status="stopped"))
    q = asyncio.Queue()
    assert research._safe_enqueue(q, _job(run_dir), "disk-restore") is False
    assert q.qsize() == 0


def test_stop_sentinel_via_run_id_when_no_resume_dir(monkeypatch, tmp_path):
    # Jobs that carry run_id but no resume_dir (start-listener / rehydrate
    # auto-resume) derive the run dir as queues/<run_id>. Point __file__'s
    # parent queues/ at a temp run by monkeypatching the queues root.
    run_id = "Run_F_20260531"
    queues_root = tmp_path / "queues"
    (queues_root / run_id).mkdir(parents=True)
    (queues_root / run_id / ".stop").touch()
    # _safe_enqueue derives Path(__file__).parent / "queues" / run_id — redirect
    # by monkeypatching research.__file__ to a sibling of our temp queues root.
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", _FakeFirestore(status="queued"))
    q = asyncio.Queue()
    job = {"research_id": "chat_y", "uid": "u2", "run_id": run_id}
    assert research._safe_enqueue(q, job, "rehydrate") is False
    assert q.qsize() == 0
