"""#905/#906/#907/#908 batch guards (2026-07-06 live-E2E fixes).

Covers, per tracker item:
  #905 — Gemini "Start research" finder hardening ([role=button] + disabled/
         visibility guards, one shared finder), cycle-1 rotation order
         (panels first, Gemini last), per-platform 60s dwell, deferred
         Gemini start-verify, ChatGPT activity-strip new-UI anchors
         ("Pro thinking" status line, "Research completed" strip, citations).
  #906 — Skip means skip: the tier-5 HV skip KEEPS the skipped_agents marker
         (callers use membership to suppress the duplicate fail card), the
         skipped platform's tab is CLOSED (with main/last-tab guards), the
         skip consumer never runs the extraction ladder against an
         HV-walled tab, and Cloudflare fail cards are Skip-only.
  #907 — --login ↔ serve coordination marker (freshness + staleness cap),
         auto-retry stand-down, crash-banner suppression, sweep raise, and
         the neat run-close terminal path.
  #908 — fail_phase never persists "errored" onto a phase the pipeline
         hasn't reached (future-phase demotion to a quiet card).

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


# ── helpers ──────────────────────────────────────────────────────────────────

def _capture_emits(monkeypatch):
    emitted = []

    def _fake_emit(event_type, **kw):
        emitted.append({"type": event_type, **kw})

    monkeypatch.setattr(research, "emit_event", _fake_emit)
    return emitted


class _FakeContext:
    def __init__(self, n_pages=2):
        self.pages = [object() for _ in range(n_pages)]


class _FakePage:
    def __init__(self, n_pages_in_context=2, closed=False):
        self.context = _FakeContext(n_pages_in_context)
        self._closed = closed
        self.close_calls = 0

    def is_closed(self):
        return self._closed

    async def close(self):
        self.close_calls += 1
        self._closed = True


class _FakeBrowser:
    def __init__(self, main_page=None):
        self.page = main_page


# ── #906: fail_agent skip_only ───────────────────────────────────────────────

def test_fail_agent_default_offers_retry_and_skip(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    research.fail_agent("claude", "t", "d")
    (evt,) = emitted
    ids = [a["id"] for a in evt["actions"]]
    assert ids == ["retry", "skip"]
    assert evt["actions"][0]["label"] == "Retry (hard)"


def test_fail_agent_skip_only_has_no_retry(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    research.fail_agent("claude", "t", "d", skip_only=True)
    (evt,) = emitted
    ids = [a["id"] for a in evt["actions"]]
    assert ids == ["skip"], "hands-off Cloudflare card must be Skip-ONLY"
    assert evt["actions"][0]["style"] == "primary"


def test_hv_fail_copy_cloudflare_never_mentions_retry():
    _title, details = research._hv_fail_copy("claude", "Cloudflare challenge")
    assert "retry" not in details.lower(), (
        "CF copy invites the click loop the hands-off directive forbids")
    assert "untouched" in details.lower()


def test_hv_setup_fail_card_wires_skip_only_for_cloudflare():
    src = inspect.getsource(research._hv_setup_fail_card)
    assert "skip_only=" in src and "cloudflare" in src


# ── #906: _close_skipped_agent_tab guards ────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def test_skip_close_closes_a_normal_tab(monkeypatch):
    page = _FakePage(n_pages_in_context=3)
    unregs = []
    monkeypatch.setattr(research._runtime, "unregister_page",
                        lambda k, final_status="done": unregs.append((k, final_status)))
    _run(research._close_skipped_agent_tab(_FakeBrowser(), page, "claude", "T"))
    assert page.close_calls == 1
    assert unregs == [("claude", "skipped")]


def test_skip_close_spares_the_main_tab(monkeypatch):
    page = _FakePage(n_pages_in_context=3)
    monkeypatch.setattr(research._runtime, "unregister_page", lambda *a, **k: None)
    _run(research._close_skipped_agent_tab(_FakeBrowser(main_page=page), page, "chatgpt", "T"))
    assert page.close_calls == 0, "closing browser.page drops the main handle"


def test_skip_close_spares_the_last_context_page(monkeypatch):
    page = _FakePage(n_pages_in_context=1)
    monkeypatch.setattr(research._runtime, "unregister_page", lambda *a, **k: None)
    _run(research._close_skipped_agent_tab(_FakeBrowser(), page, "claude", "T"))
    assert page.close_calls == 0, "headful Chrome exits with its last window"


def test_skip_close_spares_a_preserved_tab(monkeypatch):
    page = _FakePage(n_pages_in_context=3)
    monkeypatch.setattr(research._runtime, "unregister_page", lambda *a, **k: None)
    _run(research._close_skipped_agent_tab(_FakeBrowser(), page, "chatgpt", "T",
                                           preserve_tab=True))
    assert page.close_calls == 0


def test_skip_close_noops_on_already_closed_page(monkeypatch):
    page = _FakePage(closed=True)
    monkeypatch.setattr(research._runtime, "unregister_page", lambda *a, **k: None)
    _run(research._close_skipped_agent_tab(_FakeBrowser(), page, "claude", "T"))
    assert page.close_calls == 0


# ── #906: source-guards for the inline skip paths ────────────────────────────

def test_tier5_skip_branch_keeps_marker_and_closes_tab():
    src = inspect.getsource(research.wait_for_verification_clearance)
    # The skip branch must NOT consume the marker (callers check membership
    # to suppress the duplicate card) and MUST close the walled tab.
    skip_branch = src.split("Skip agent during human verification")[0]
    assert "skipped_agents.discard" not in skip_branch, (
        "tier-5 skip must keep the marker — discarding it re-created the "
        "second 'hit Cloudflare's human check' card")
    assert "_close_skipped_agent_tab" in src


def test_hv_callers_suppress_fail_card_on_user_skip():
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    assert src.count("in _controls.skipped_agents") >= 2, (
        "both HV-clearance callers (Layer-0 + mid-setup) must check skip "
        "membership before emitting the fail card")
    assert "no failure card" in src


def test_skip_consumer_hands_off_walled_tabs_and_closes():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert "_ag_key in _controls.hv_blocked" in src, (
        "skip-extract must never drive the extraction ladder (DOM+CUA) "
        "against a verification-walled tab")
    assert "_close_skipped_agent_tab" in src
    # A tab closed by a user skip must not read as a browser crash.
    assert "_crash_key in _controls.skipped_agents" in src


def test_phase2_outer_paths_respect_prior_skip():
    src = inspect.getsource(research.run_phase2)
    assert src.count("after a user Skip") >= 3, (
        "2A/2B/2C failure branches must all suppress the failure card/"
        "status when the user already skipped the agent")


def test_phase2_entry_clears_stale_skip_markers():
    # The tier-5 skip keeps its marker and the round-robin consumer only
    # runs when polling starts — without the entry-clear, a marker
    # surviving a phase-2 restart (P3 gate "Retry Phase 2") would instantly
    # auto-skip the relaunched agent at its next HV wait or silently
    # suppress a legit failure card. Skip = per-attempt decision.
    src = inspect.getsource(research.run_phase2)
    assert "clearing stale skip marker" in src
    assert src.index("clearing stale skip marker") < src.index("2A: ChatGPT"), (
        "the stale-marker clear must run BEFORE any agent launches")


# ── #905: source-guards ──────────────────────────────────────────────────────

def test_gemini_start_finder_matches_role_button_and_skips_disabled():
    src = inspect.getsource(research.run_phase2)
    assert "[role=\\\"button\\\"]" in src or "[role=\\'button\\']" in src or (
        "role=" in src and "aria-disabled" in src)
    assert "aria-disabled" in src
    # The CUA recovery must reuse the SAME finder — no second, divergent
    # `<button>`-only redefinition (the live run's finder went blind while
    # its own diagnostic dumped a visible aria="Start research" control).
    assert src.count("_click_start_js = ") == 1


def test_round_robin_cycle1_is_insertion_order_with_dwell():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert "(_tick_counter - 1) %" in src, (
        "cycle 1 must run ChatGPT→Claude→Gemini (panels first, Gemini last)")
    assert "P2_AGENT_DWELL_SEC" in src, "per-platform ~60s dwell knob"
    assert "needs_start_verify" in src, "deferred Gemini start-verify"


def test_agents_stamp_research_started_at_submit_time():
    src = inspect.getsource(research.run_phase2)
    assert src.count("research_started_at") >= 3, (
        "ChatGPT/Claude/Gemini must all stamp research start so MIN_WAIT "
        "doesn't ignore an agent that finished during the plan-wait")


def test_chatgpt_strip_walker_knows_new_ui_states():
    src = inspect.getsource(research._open_chatgpt_activity_panel)
    assert "citations?" in src
    assert "research\\\\s+completed" in src or "research\\s+completed" in src
    assert "STATUS_LINE" in src and "hasStatusLine" in src, (
        "the 2026-07 'Pro thinking' shimmer line must be a click candidate")
    assert "hasCompleted" in src


# ── #907: login marker + gates ───────────────────────────────────────────────

def _marker_to_tmp(monkeypatch, tmp_path):
    p = tmp_path / "login_in_progress.json"
    monkeypatch.setattr(research, "_login_marker_path", lambda: p)
    return p


def test_login_marker_roundtrip(monkeypatch, tmp_path):
    p = _marker_to_tmp(monkeypatch, tmp_path)
    assert research._login_interrupt_active() is False
    research._write_login_marker()
    assert p.exists()
    assert research._login_interrupt_active() is True
    research._clear_login_marker()
    assert research._login_interrupt_active() is False


def test_login_marker_staleness_cap(monkeypatch, tmp_path):
    p = _marker_to_tmp(monkeypatch, tmp_path)
    stale_ms = int((time.time() - 31 * 60) * 1000)
    p.write_text(json.dumps({"ts": stale_ms, "pid": 1}), encoding="utf-8")
    assert research._login_interrupt_active() is False, (
        "a hard-killed --login must not classify crashes forever")


def test_login_marker_corrupt_is_inactive(monkeypatch, tmp_path):
    p = _marker_to_tmp(monkeypatch, tmp_path)
    p.write_text("not json", encoding="utf-8")
    assert research._login_interrupt_active() is False


def test_auto_retry_stands_down_during_login(monkeypatch, tmp_path):
    qdir = tmp_path / "run"
    qdir.mkdir()
    monkeypatch.setattr(research, "_login_interrupt_active", lambda *a, **k: True)
    will, _ph, _crash = research._plan_pipeline_auto_retry(qdir, None, "browser_crash", 0)
    assert will is False, "retrying would relaunch Chrome onto the login's profile"


def test_auto_retry_unchanged_without_login(monkeypatch, tmp_path):
    qdir = tmp_path / "run"
    qdir.mkdir()
    monkeypatch.setattr(research, "_login_interrupt_active", lambda *a, **k: False)
    monkeypatch.setattr(research, "detect_resume_phase", lambda _q: (2, None))
    will, ph, is_crash = research._plan_pipeline_auto_retry(qdir, None, "browser_crash", 0)
    assert will is True and ph == 2 and is_crash is True


def test_crash_banner_suppressed_during_login(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda *a, **k: True)
    research.emit_browser_recovery_status(2, agent="chatgpt")
    assert emitted == [], "no 'tab crashed — auto-retrying' banner on a login kill"


def test_crash_banner_normal_without_login(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda *a, **k: False)
    research.emit_browser_recovery_status(2, agent="chatgpt")
    assert len(emitted) == 1 and emitted[0]["type"] == "pipeline_warning"


def test_round_robin_sweep_raises_on_login_interrupt():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    assert "closed by the login command (login interrupt)" in src
    assert "login_interrupt" in src


def test_run_pipeline_emits_login_interrupt_card():
    # inspect.getsource on run_pipeline is huge — pin via the module source.
    # #911 rewrote the card copy short ("Paused by the login command") with a
    # Stop-button note + durable force_mirror — see test_login_batch_909_912.
    assert "Paused by the login command" in _SRC
    assert "resume_from_checkpoint" in _SRC


def test_enumerate_ongoing_runs_reads_live_locks(monkeypatch, tmp_path):
    qroot = tmp_path / "queues"
    qroot.mkdir()
    run_dir = qroot / "run_a"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps({"title": "Golden Retriever"}),
                                       encoding="utf-8")
    lock = qroot / ".worker.1.lock"
    lock.write_text(json.dumps({
        "pid": 4242, "worker_id": 1, "research_id": "r1", "run_id": "run_a",
        "started_at": int(time.time() * 1000),
    }), encoding="utf-8")

    class _FakePsutil:
        @staticmethod
        def pid_exists(pid):
            return pid == 4242

    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil)
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    runs = research._enumerate_ongoing_runs()
    assert runs == [{"worker": 1, "run_id": "run_a", "title": "Golden Retriever"}]


def test_enumerate_ongoing_runs_skips_dead_pid_and_stopped(monkeypatch, tmp_path):
    qroot = tmp_path / "queues"
    qroot.mkdir()
    for name, pid, stopped in (("run_dead", 999, False), ("run_stop", 4242, True)):
        d = qroot / name
        d.mkdir()
        if stopped:
            (d / ".stop").write_text("stop", encoding="utf-8")
    (qroot / ".worker.1.lock").write_text(json.dumps({
        "pid": 999, "worker_id": 1, "research_id": "r", "run_id": "run_dead",
        "started_at": int(time.time() * 1000)}), encoding="utf-8")
    (qroot / ".worker.2.lock").write_text(json.dumps({
        "pid": 4242, "worker_id": 2, "research_id": "r", "run_id": "run_stop",
        "started_at": int(time.time() * 1000)}), encoding="utf-8")

    class _FakePsutil:
        @staticmethod
        def pid_exists(pid):
            return pid == 4242

    monkeypatch.setitem(sys.modules, "psutil", _FakePsutil)
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    assert research._enumerate_ongoing_runs() == []


def test_login_flow_writes_marker_and_neat_close():
    src = inspect.getsource(research.run_login)
    assert "_write_login_marker" in src
    assert "_enumerate_ongoing_runs" in src
    assert "Closing Run" in src and "Browser closed" in src
    src_probe = inspect.getsource(research._probe_profile_logins)
    assert "_BROWSER_SWEEP_QUIET" in src_probe, (
        "the login pre-probe must silence the per-PID orphan-sweep flood")


# ── #908: fail_phase future-phase demotion ───────────────────────────────────

def test_fail_phase_demotes_future_phase_to_quiet(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    writes = []
    monkeypatch.setattr(research, "_write_phase_terminal_status",
                        lambda ph, st: writes.append((ph, st)))
    monkeypatch.setattr(research._runtime, "phase", 2)
    research.fail_phase(phase=3, error="No research to turn into a notebook",
                        reason="r")
    assert writes == [], "phase 3 never started — no persistent errored write"
    (evt,) = emitted
    assert evt.get("quiet") is True, "volatile tile badge must be demoted too"


def test_fail_phase_current_phase_still_marks(monkeypatch):
    emitted = _capture_emits(monkeypatch)
    writes = []
    monkeypatch.setattr(research, "_write_phase_terminal_status",
                        lambda ph, st: writes.append((ph, st)))
    monkeypatch.setattr(research._runtime, "phase", 3)
    research.fail_phase(phase=3, error="e", reason="r")
    assert writes == [(3, "errored")]
    (evt,) = emitted
    assert evt.get("quiet") is not True


def test_p3_no_output_gate_is_explicitly_quiet():
    # Belt-and-suspenders on top of the generic demotion: the two gate cards
    # pass mark_phase_errored=False explicitly.
    gate = _SRC.split("No research output (attempt")[1][:4000]
    assert gate.count("mark_phase_errored=False") >= 2
