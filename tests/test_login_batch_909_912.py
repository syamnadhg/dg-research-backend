"""#909-#912 login batch guards (2026-07-07 live-E2E fixes).

Covers, per tracker item:
  #909 — --login run-close speed: ONE process scan (_chrome_procs_for_profile)
         + ONE batched multi-/PID taskkill + psutil.wait_procs instead of a
         scan per signal and a full rescan every 0.5s; live spinner on every
         laggy step; honest ✓ line with elapsed. No result-saving on close —
         checkpoints already own run state.
  #910 — login interrupt covers ALL BE phases: the P3 audio poller detects a
         dead browser per cycle (pre-fix it swallowed every failure and
         looped "Audio still generating…" forever — live 2026-07-06);
         --login's run enumeration skips paused/terminal runs (phantom
         "1 ongoing run" on re-run); delivery.json paused↔ongoing lifecycle.
  #911 — short login card ("Paused by the login command" + Stop-button note)
         with force_mirror so the quiet card still gets the durable
         pendingDecision mirror (cold-open re-surface + agent-chat watchdog).
  #912 — Skip closes the browser side for agents that already left the poll
         set (fail/empty/timeout drops), not just in-pending agents.

Functional where the seam allows (fakes/monkeypatch), source-guards for the
inline paths — matching the repo's existing pinning style.
"""

import asyncio
import inspect
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import research  # noqa: E402

_SRC = Path(research.__file__).read_text(encoding="utf-8")


# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeProc:
    def __init__(self, pid, name="chrome.exe", cmdline=None, alive=True):
        self.pid = pid
        self.info = {"pid": pid, "name": name, "cmdline": cmdline or []}
        self._alive = alive
        self.terminated = 0
        self.killed = 0

    def terminate(self):
        self.terminated += 1
        self._alive = False

    def kill(self):
        self.killed += 1
        self._alive = False

    def is_running(self):
        return self._alive


def _fake_psutil(procs, alive_after_wait=()):
    class _FakePsutil:
        @staticmethod
        def process_iter(_attrs):
            return list(procs)

        @staticmethod
        def wait_procs(plist, timeout):
            alive = [p for p in plist if p in alive_after_wait]
            gone = [p for p in plist if p not in alive_after_wait]
            return gone, alive

        @staticmethod
        def pid_exists(pid):
            return True

    return _FakePsutil


# ── #909: one-scan proc collection ──────────────────────────────────────────

def test_chrome_procs_for_profile_matches_by_cmdline(monkeypatch, tmp_path):
    profile = tmp_path / "browser-profile-2"
    profile.mkdir()
    target = str(profile).replace("\\", "/")
    match = _FakeProc(11, cmdline=["chrome", f"--user-data-dir={target}"])
    other = _FakeProc(12, cmdline=["chrome", "--user-data-dir=C:/elsewhere/p"])
    not_chrome = _FakeProc(13, name="notepad.exe", cmdline=[target])
    monkeypatch.setitem(sys.modules, "psutil",
                        _fake_psutil([match, other, not_chrome]))
    got = research._chrome_procs_for_profile(str(profile))
    assert got == [match]


def test_close_profile_browser_neatly_no_procs_is_instant(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil([]))
    stats = asyncio.run(research._close_profile_browser_neatly(str(tmp_path)))
    assert stats["procs"] == 0 and stats["hard_killed"] == 0


def test_close_profile_browser_neatly_batches_one_taskkill(monkeypatch, tmp_path):
    profile = tmp_path / "browser-profile-1"
    profile.mkdir()
    target = str(profile).replace("\\", "/")
    procs = [_FakeProc(pid, cmdline=["chrome", f"--user-data-dir={target}"])
             for pid in (21, 22, 23)]
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(procs))
    calls = []
    monkeypatch.setattr(research.subprocess, "run",
                        lambda args, **kw: calls.append(list(args)))
    monkeypatch.setattr(research.sys, "platform", "win32")
    stats = asyncio.run(research._close_profile_browser_neatly(str(profile)))
    assert stats["procs"] == 3 and stats["hard_killed"] == 0
    # ONE spawn carrying every PID, graceful (no /F), tree-close (/T).
    (args,) = calls
    assert args[0] == "taskkill" and args.count("/PID") == 3
    assert "/T" in args and "/F" not in args


def test_close_profile_browser_neatly_hard_kills_remnants(monkeypatch, tmp_path):
    profile = tmp_path / "browser-profile-1"
    profile.mkdir()
    target = str(profile).replace("\\", "/")
    stuck = _FakeProc(31, cmdline=["chrome", f"--user-data-dir={target}"])
    clean = _FakeProc(32, cmdline=["chrome", f"--user-data-dir={target}"])
    monkeypatch.setitem(sys.modules, "psutil",
                        _fake_psutil([stuck, clean], alive_after_wait=(stuck,)))
    monkeypatch.setattr(research.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(research.sys, "platform", "win32")
    stats = asyncio.run(research._close_profile_browser_neatly(str(profile)))
    assert stats["hard_killed"] == 1
    assert stuck.killed == 1 and clean.killed == 0


def test_close_profile_browser_neatly_posix_terminates(monkeypatch, tmp_path):
    profile = tmp_path / "browser-profile-1"
    profile.mkdir()
    target = str(profile).replace("\\", "/")
    p = _FakeProc(41, cmdline=["chrome", f"--user-data-dir={target}"])
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil([p]))
    monkeypatch.setattr(research.sys, "platform", "linux")
    stats = asyncio.run(research._close_profile_browser_neatly(str(profile)))
    assert p.terminated == 1 and stats["procs"] == 1


def test_run_login_shows_spinner_and_elapsed_on_close():
    src = inspect.getsource(research.run_login)
    # Spinner rides both laggy steps: the backend scan + each run close.
    assert "Checking for a running backend" in src
    assert 'f"Closing Run {_ri} — {_title}"' in src
    assert "_async_spinner_ctx" in src
    # ✓ line carries the honest elapsed; nothing prints mid-spinner.
    assert "elapsed_sec" in src
    assert "asyncio.to_thread(_backend_is_running)" in src


def test_close_profile_neatly_never_saves_results():
    # #909 user rule: --login only CLOSES — run state rides checkpoints.
    src = inspect.getsource(research._close_profile_browser_neatly)
    for forbidden in ("save_checkpoint", "update_delivery", "extract"):
        assert forbidden not in src


# ── #910: P3 audio poller detects the dead browser ──────────────────────────

def test_p3_audio_poll_unwinds_on_dead_browser():
    src = inspect.getsource(research.run_phase3_audio)
    assert "#910: dead-browser check per cycle" in src
    assert "closed by the login command (login interrupt)" in src
    assert "closed mid-audio-poll (browser crash)" in src
    # The check must precede the swallow-everything reload, inside the poll loop.
    assert src.index("dead-browser check per cycle") < src.index(
        "Refresh page every cycle")


def test_p3_audio_poll_sets_failure_kind_before_raise():
    src = inspect.getsource(research.run_phase3_audio)
    login_at = src.index('last_failure_kind = "login_interrupt"')
    crash_at = src.index('last_failure_kind = "browser_crash"')
    raise_login = src.index("(login interrupt)")
    raise_crash = src.index("(browser crash)")
    assert login_at < raise_login and crash_at < raise_crash


def test_enumerate_ongoing_runs_skips_paused_delivery(monkeypatch, tmp_path):
    qroot = tmp_path / "queues"
    qroot.mkdir()
    for name, wid, status in (("run_paused", 1, "paused"),
                              ("run_live", 2, "ongoing")):
        d = qroot / name
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"title": name}), encoding="utf-8")
        (d / "delivery.json").write_text(json.dumps({"status": status}),
                                         encoding="utf-8")
        (qroot / f".worker.{wid}.lock").write_text(json.dumps({
            "pid": 4242, "worker_id": wid, "research_id": "r", "run_id": name,
            "started_at": int(time.time() * 1000)}), encoding="utf-8")

    class _FakePsutil:
        @staticmethod
        def pid_exists(pid):
            return pid == 4242

    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil)
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    runs = research._enumerate_ongoing_runs()
    assert [r["run_id"] for r in runs] == ["run_live"]


def test_resume_reasserts_ongoing_over_stale_pause():
    # Narrow lifecycle: paused→ongoing on resume entry only (never touches
    # completed/stopped) so auto-retry Gate 2 stays healthy post-resume.
    assert "status paused → ongoing (stale pause cleared)" in _SRC
    _guard = _SRC[_SRC.index("stale pause cleared") - 900:
                  _SRC.index("stale pause cleared")]
    assert '== "paused"' in _guard and "if resume_dir:" in _guard


def test_login_interrupt_card_marks_delivery_paused():
    # The card block writes the durable local pause marker the enumeration
    # + Gate 2 read.
    _blk_at = _SRC.index("Paused by the login command")
    _blk = _SRC[_blk_at - 1800:_blk_at]
    assert 'update_delivery(status="paused")' in _blk


# ── #911: short card + durable mirror for the quiet login card ──────────────

def test_login_card_copy_is_short_with_stop_note():
    _at = _SRC.index('error="Paused by the login command"')
    _card = _SRC[_at:_at + 900]
    assert "Note: the Stop button ends the run instead." in _card
    assert "force_mirror=True" in _card
    assert "_login_interrupt" in _card  # distinct alert_id
    assert "mark_phase_errored=False" in _card
    # Old long copy is gone everywhere.
    assert "Interrupted by the Research computer's login command" not in _SRC


def test_force_mirror_persists_quiet_card(monkeypatch, tmp_path):
    persisted = []
    monkeypatch.setattr(research, "_tracks_dir", tmp_path)
    monkeypatch.setattr(research, "_persist_pending_decision",
                        lambda pd: persisted.append(pd))
    fire = []
    monkeypatch.setattr(research, "_emit_to_firestore",
                        lambda evt: fire.append(evt))
    research.emit_event(
        "pipeline_error", phase=3,
        error="Paused by the login command", details="d",
        actions=[{"id": "retry"}], dismissible=True,
        alert_id="phase3_login_interrupt", quiet=True, force_mirror=True)
    (pd,) = persisted
    assert pd["title"] == "Paused by the login command"
    assert pd["alert_id"] == "phase3_login_interrupt"
    # The override flag never leaks into the Firestore event payload.
    (evt,) = fire
    assert "force_mirror" not in (evt.get("data") or {})


def test_quiet_without_force_mirror_stays_unmirrored(monkeypatch, tmp_path):
    persisted = []
    monkeypatch.setattr(research, "_tracks_dir", tmp_path)
    monkeypatch.setattr(research, "_persist_pending_decision",
                        lambda pd: persisted.append(pd))
    monkeypatch.setattr(research, "_emit_to_firestore", lambda evt: None)
    research.emit_event(
        "pipeline_error", phase=3, error="quiet preflight", details="d",
        actions=[{"id": "retry"}], quiet=True)
    assert persisted == []


def test_fail_phase_forwards_force_mirror_and_alert_id(monkeypatch):
    emitted = []
    monkeypatch.setattr(research, "emit_event",
                        lambda t, **kw: emitted.append({"type": t, **kw}))
    monkeypatch.setattr(research, "_write_phase_terminal_status",
                        lambda *a, **k: None)
    research.fail_phase(
        phase=2, error="Paused by the login command", reason="r",
        mark_phase_errored=False, force_mirror=True,
        alert_id="phase2_login_interrupt",
        actions=[{"id": "retry", "label": "Retry", "style": "primary",
                  "command": {"action": "resume_from_checkpoint"}}])
    (evt,) = emitted
    assert evt["force_mirror"] is True
    assert evt["alert_id"] == "phase2_login_interrupt"
    assert evt["quiet"] is True  # still a quiet card — no red tile


# ── #912: skip closes the browser side for post-drop agents ──────────────────

def test_skip_consumer_closes_leftover_tab_for_dropped_agents():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    _at = src.index("#912")
    _blk = src[_at:_at + 900]
    assert "_runtime.active_pages.get(_ag_key)" in _blk
    assert 'agents.get(_agent_name) or {}).get("page")' in _blk
    assert "_close_skipped_agent_tab" in _blk
    # Fallback rides the SAME consumer, after the in-pending branch.
    assert src.index("#906: Skip means skip") < _at


def test_close_skipped_agent_tab_tolerates_closed_handle():
    # The fallback can hand over a page an earlier path already closed.
    class _Ctx:
        pages = [object(), object()]

    class _Pg:
        context = _Ctx()

        def is_closed(self):
            return True

        async def close(self):  # pragma: no cover - must not be reached
            raise AssertionError("closed page must not be re-closed")

    class _Br:
        page = None

    asyncio.run(research._close_skipped_agent_tab(_Br(), _Pg(), "claude", "Claude"))
