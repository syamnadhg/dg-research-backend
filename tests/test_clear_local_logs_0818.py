"""Clear logs — the LOCAL half, 2026-08-18 owner wave.

⛔⛔ WHY THIS EXISTS AT ALL. The app's "Clear Shared Logs" deleted the bundles
already uploaded and left every log file on the machine untouched. That is not a
naming quibble: a person pressing a control called "clear logs" for privacy
reasons was told the logs were cleared while the whole payload — topics, result
links, the account email, the agent screens — sat on their own disk waiting for
the next `--send-logs`. The owner's instruction was to make the short label true.

── The property that defines this function ──────────────────────────────────

⭐⭐ "NOTHING LEFT TO SEND" IS PROVED BY BUILDING A BUNDLE, not by re-reading the
clear's own inventory. `_build_log_bundle` reads exactly three places, and a test
that listed those three itself would agree with the code by construction and
would keep agreeing after the collector grew a fourth source. So the defining
test clears, then builds, then asserts the archive holds only its own manifest
and index. That test fails if either side changes without the other.

── The two hazards that shaped the implementation ───────────────────────────

⛔ THE RAW TAILS ARE TRUNCATED, NEVER UNLINKED. The supervisor holds backend.log
open in APPEND mode (`open(log_out_path, "ab")` in `_spawn_worker`). Unlinking it
leaves a live process writing to an inode with no name — the bytes stay on the
disk until the next restart and every line after the press is unreachable. Append
mode is what makes truncation correct rather than merely tidier: the next write
goes to the current end, which is now zero.

⛔ THE PARKED ROWS GO FIRST. `_drain_queued_log_bundle_rows()` runs on every tick
of every worker's reconnect watcher, and a drain RE-CREATES the cloud row it
publishes. The app deletes the cloud rows itself, so a drain landing after that
sweep resurrects a bundle the person just cleared. Emptying that file before the
slow rmtree is what shrinks the window to nothing this process controls.
"""
import io
import os
import zipfile

import pytest

import research

from conftest import code_only, code_only_deep


# ── fixtures ────────────────────────────────────────────────────────────

def _run_folder(name, status="complete", pid=None, started=None):
    """One run-log folder, with the meta `_folder_is_live` actually reads."""
    folder = research._runs_log_root() / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.log").write_text("a log line\n", encoding="utf-8")
    research._atomic_write_json(folder / "meta.json", {
        "schema": 1, "status": status,
        "pid": os.getpid() if pid is None else pid,
        "researchId": None, "attempt": 0,
        "startedUtc": research._utc_iso() if started is None else started,
        "counters": {"lines": 1, "warns": 0, "errors": 0},
    })
    return folder


def _session(name="doctor_20260818T161823.log", body="pairing failed\n"):
    root = research._sessions_log_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def _tail(name="backend.log", body="22758 lines of stderr\n"):
    root = research._logs_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def _outgoing(code="7QK4M2XZ"):
    root = research._logs_root() / "outgoing"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"support-{code}{research.BUNDLE_SUFFIX}"
    path.write_bytes(b"PK\x03\x04 a whole bundle")
    return path


def _pending():
    path = research._logs_root() / "pending-bundle-rows.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"ownerUid":"u1","code":"AAAA1111","patch":{}}\n', encoding="utf-8")
    return path


# ══ 1. the defining property: a cleared machine has nothing to send ════

def test_a_cleared_machine_builds_an_empty_bundle(tmp_path):
    """⭐⭐ THE ONE THAT CANNOT AGREE WITH THE CODE BY CONSTRUCTION.

    Clear, then BUILD. If `_clear_local_logs` ever stops covering a source the
    collector reads — or the collector grows a fourth one — this fails, and it is
    the only test here that can notice."""
    _run_folder("chat_1787103759476_1_20260818T120000")
    _run_folder("chat_1787103759476_2_20260818T130000")
    _session()
    _session("login_20260819T024152.log")
    _tail()
    _tail("backend.err.log")

    before = tmp_path / "before.zip"
    research._build_log_bundle(before)
    with zipfile.ZipFile(before) as zf:
        assert any(n.startswith("runs/") for n in zf.namelist())

    research._clear_local_logs()

    after = tmp_path / "after.zip"
    summary = research._build_log_bundle(after)
    with zipfile.ZipFile(after) as zf:
        names = zf.namelist()
    # Only the archive's own description of ITSELF is left. Named exhaustively
    # rather than filtered by prefix: a fourth payload source added to the
    # collector has to fail here, and a prefix filter would let it through.
    assert sorted(names) == ["collected.json", "index.json", "manifest.json"], names
    # ⭐ And the manifest agrees, from the collector's own count rather than from
    # the member list — a truncated tail contributes no member either way, so the
    # namelist alone cannot tell "nothing to collect" from "collected nothing".
    assert summary["runsOnDisk"] == 0
    assert summary["runCount"] == 0
    assert summary["sessionCount"] == 0


# ══ 2. the raw tails: truncated, never unlinked ════════════════════════

def test_the_raw_tails_are_truncated_in_place_not_deleted():
    """⛔ The supervisor holds these open in append mode. Unlinking one leaves a
    live process writing to an inode with no name — space never reclaimed, every
    later line unreachable. So the file must still EXIST, at zero bytes."""
    live = _tail("backend.log")
    err = _tail("backend.err.log")
    rolled = _tail("backend.log.1")

    out = research._clear_local_logs()

    for path in (live, err, rolled):
        assert path.exists(), f"{path.name} was unlinked — the supervisor's handle"
        assert path.stat().st_size == 0, path.name
    assert out["tails"] == 3


def test_a_file_that_is_not_a_recognised_tail_is_left_alone():
    """The collector reads `backend*`/`supervisor*` and nothing else, so this
    clear does not get to decide what other files in the directory are for. A
    developer's own e2e capture is not the product's log."""
    keep = research._logs_root() / "e2e-0817.log"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("my own capture\n", encoding="utf-8")
    _tail("backend.log")

    research._clear_local_logs()

    assert keep.read_text(encoding="utf-8") == "my own capture\n"


def test_an_append_write_after_the_truncate_lands_at_the_start():
    """⭐ The reason truncation is CORRECT here and not just tidier. A handle
    opened `ab` before the clear keeps working and writes from offset zero — no
    NUL hole, no lost lines. This is the property the whole choice rests on, so
    it is measured rather than reasoned about."""
    path = _tail("backend.log", "old line\n" * 500)
    with open(path, "ab") as held:
        research._clear_local_logs()
        held.write(b"a line written after the clear\n")
        held.flush()
    assert path.read_bytes() == b"a line written after the clear\n"


# ══ 3. a run still being written into survives ═════════════════════════

def test_a_live_run_folder_survives_and_a_dead_one_does_not():
    """⛔ Mirrors `clear_local_storage`'s in-flight guard. A running pipeline is
    appending into that folder through an open handle and its checkpoint lives
    there."""
    live = _run_folder("chat_live_20260818T120000", status="running")
    dead = _run_folder("chat_done_20260818T110000", status="complete")

    out = research._clear_local_logs()

    assert live.exists()
    assert not dead.exists()
    assert out["runs"] == 1
    assert out["kept"] == 1


def test_a_corpse_claiming_to_run_is_still_removed():
    """⛔ `_derive_run_status` is what makes the meta a cross-process answer: a
    pid that is gone means dead however loudly the file says "running". Without
    that, one crashed run would pin its folder on the disk forever and no button
    in the app could remove it."""
    corpse = _run_folder("chat_crash_20260818T090000", status="running", pid=2_147_483_6)

    out = research._clear_local_logs()

    assert not corpse.exists()
    assert out["runs"] == 1
    assert out["kept"] == 0


def test_a_folder_armed_by_THIS_process_survives_even_with_no_meta(monkeypatch):
    """The in-process sink list is the other half of the guard, and it is the
    half that covers a folder whose meta has not been written yet."""
    folder = research._runs_log_root() / "chat_fresh_20260818T140000"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.log").write_text("first line\n", encoding="utf-8")

    class _Sink:
        dir = folder

    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [_Sink()])
    out = research._clear_local_logs()

    assert folder.exists()
    assert out["kept"] == 1
    assert out["runs"] == 0


# ══ 4. sessions, and the machine's own copies of the bundle ════════════

def test_session_files_go():
    """⭐ The founding incident produced NO RUN — a paired machine whose Google
    DNS died — so its whole evidence is a pairing session. Leaving sessions
    behind would leave exactly the payload this feature was built to collect."""
    a = _session("doctor_20260818T161823.log")
    b = _session("login_20260819T024152.log")

    out = research._clear_local_logs()

    assert not a.exists() and not b.exists()
    assert out["sessions"] == 2


def test_the_machines_own_finished_bundle_and_its_parked_rows_go():
    """⛔ Same payload, different name, same directory. `--send-logs` leaves a
    finished archive so a person with no network can attach it to an email."""
    bundle = _outgoing()
    pending = _pending()

    out = research._clear_local_logs()

    assert not bundle.exists()
    assert not pending.exists()
    assert out["bundles"] == 2


def test_the_parked_rows_are_gone_BEFORE_the_slow_work_starts(monkeypatch):
    """⛔⛔ ORDER IS THE POINT. The reconnect watcher drains that file on every
    tick of every worker and a drain RE-CREATES the cloud row. The app deletes
    the cloud rows itself, so any window where the file still exists is a window
    where a bundle the person just cleared can come back — and the rmtree below
    is the slow part of this function."""
    pending = _pending()
    _run_folder("chat_slow_20260818T100000")

    seen = {}
    real_rmtree = research.shutil.rmtree

    def _watching(path, *a, **kw):
        seen["pending_existed"] = pending.exists()
        return real_rmtree(path, *a, **kw)

    monkeypatch.setattr(research.shutil, "rmtree", _watching)
    research._clear_local_logs()

    assert seen["pending_existed"] is False


# ══ 5. a partial clear says so ═════════════════════════════════════════

def test_a_failure_is_COUNTED_not_swallowed(monkeypatch):
    """⛔ A privacy action that reports a whole clear after a partial one is the
    same lie as the button that says "cleared 4" while four files survive."""
    _run_folder("chat_stuck_20260818T100000")

    def _boom(path, *a, **kw):
        raise OSError("device busy")

    monkeypatch.setattr(research.shutil, "rmtree", _boom)
    out = research._clear_local_logs()

    assert out["runs"] == 0
    assert out["failed"] == 1


def test_an_empty_log_root_is_zeroes_rather_than_an_exception():
    """Nothing to clear is the common case on a fresh install, and this runs
    inside a Firestore snapshot callback where a raise would queue every later
    command behind it."""
    out = research._clear_local_logs()
    # ⭐ Exact on purpose, and `telemetry` joined it on 2026-08-19: the spool and
    # the sent-mirror live OUTSIDE `_logs_root()`, so the collector-defined clear
    # structurally could not see them and 2.5 MB survived the button.
    assert out == {"runs": 0, "sessions": 0, "tails": 0, "bundles": 0,
                   "telemetry": 0, "kept": 0, "failed": 0}


def test_a_root_that_does_not_exist_at_all_is_survivable(tmp_path):
    out = research._clear_local_logs(root=tmp_path / "nope")
    assert out["failed"] == 0
    assert out["runs"] == 0


# ══ 6. the command is wired, and only worker 1 acts ════════════════════

def test_clear_logs_is_in_the_worker_one_gate():
    """⛔⛔ THE TUPLE IS THE WHOLE FEATURE ON A MULTI-WORKER HOST. An action
    outside it falls to the `else` and every non-primary worker DELETES the
    command — so worker 2 destroys it before worker 1's Firestore stream ever
    delivers the ADDED, and the feature ships dead with nothing failing
    anywhere. Exactly the trap `send-logs-limited` documented."""
    src = code_only_deep(research._start_device_command_listener)
    gate = src[src.index('elif action in ("update", "check-update", "restart"'):]
    gate = gate[:gate.index("and WORKER_ID != 1")]
    assert '"clear-logs"' in gate


def test_the_dispatch_branch_calls_the_clear_on_worker_one_only():
    src = code_only_deep(research._start_device_command_listener)
    at = src.index('if action == "clear-logs":')
    body = src[at:src.index('if action == "update":', at)]
    assert "if WORKER_ID == 1:" in body
    assert "_clear_local_logs()" in body
    # Never raises into the snapshot callback — see the empty-root test above.
    assert "except Exception" in body


def test_the_handler_reports_every_counter_it_was_given():
    """⛔ A log line that names three of six counters is how a partial clear
    looks total in the only record anybody reads afterwards."""
    src = code_only_deep(research._start_device_command_listener)
    at = src.index('if action == "clear-logs":')
    body = src[at:src.index('if action == "update":', at)]
    for key in ("runs", "sessions", "tails", "bundles", "kept", "failed"):
        assert f"cleared['{key}']" in body, key


def test_the_truncate_is_a_truncate_and_not_an_unlink():
    """⛔ Source-pinned because the behavioural test above cannot distinguish
    "unlinked, then recreated empty" from "truncated" — and only one of those
    keeps the supervisor's handle pointed at a file anyone can read."""
    src = code_only_deep(research._clear_local_logs)
    tails = src[src.index("_system_log_tails(base)"):]
    assert 'open(path, "r+b")' in tails
    assert "fh.truncate(0)" in tails
    assert ".unlink()" not in tails


def test_the_liveness_guard_is_the_PRUNES_guard_and_not_a_new_one():
    """⛔ `_prune_local_logs` uses the sink list PLUS `_folder_is_live`, and the
    second half is there because the sink list only covers runs THIS worker
    armed — mutation found that hole. This command runs on worker 1 while worker
    2 may own the live run, so a third notion of "active" here would reopen it."""
    src = code_only(research._clear_local_logs)
    assert "_RUN_LOG_SINKS" in src
    assert "_folder_is_live(folder)" in src
    prune = code_only(research._prune_local_logs)
    assert "_RUN_LOG_SINKS" in prune and "_folder_is_live(" in prune
