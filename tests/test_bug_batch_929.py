"""#929 (2026-07-09): bug batch — phase-restart FE reset, Gemini planning
false alarm, grey-fade-on-skip everywhere, single-alert architecture.

Live E2E surfaced four bugs (screenshots + Golden_Retriever_20260709_172158
log forensics):

  Bug 0 — a checkpoint resume relaunches ALL enabled agents (a pre-pause
    user skip is per-attempt), but nothing told the FE to restart the
    phase's UI: a Claude skipped before a --login pause stayed grey
    "Skipped" through the whole fresh attempt.

  Bug 1 — a healthy Gemini took >10 min on its research plan and was
    carded (~10 min) then auto-skipped (+20 min): the scraper never
    reports status="planning" (planning rides the separate `phase`
    field), the arbiter prompt itself called a zero-source plan page
    "stuck", and three disarm gaps kept the auto-skip clock armed after
    WORKING re-verdicts / pokes / recovery.

  Bug 2 — skip paths outside the round-robin (the 2D plan wait, the
    Claude hard-fail auto-skip marker) never emitted agent_skipped, so
    the persisted "errored" tile never flipped to grey.

  Bug 3 — --login teardown killed Gemini's paste mid-flight; the setup
    path carded agent_gemini_error at 17:34:09, the login card landed at
    17:34:10, and nothing retracted either: two conflicting cards.

Fixes verified here (BE side):
  - timers: L1 600→900s, L3 unacted 1200→1800s;
  - planning counts as active (scrape `phase`=="planning" gates L1);
  - arbiter prompt: plan generation = WORKING;
  - disarm: arbiter WORKING re-verdict / poke / wait-longer clear
    stuck_alerted_at; 2D CUA-recovery successes retract the early card;
  - 2D consumes mid-wait skips (agent_skipped + tab close) + streaming
    hold-off (GEMINI_PLAN_STREAM_MAX_SEC) on the early card;
  - L3 + Claude hard-fail salvage respect hv_blocked (hands-off);
  - Claude hard-fail auto-skip finalizes with an honest reason;
  - fail_agent suppressed during --login teardown;
  - resume emits phase_restart(full=True); run_phase2 entry resets
    persisted agent statuses to "running";
  - fail_agent brief copy uses the platform display name, not "2C".
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import research  # noqa: E402

_SRC = Path(research.__file__).read_text(encoding="utf-8")
_POLL = inspect.getsource(research.poll_all_agents_round_robin)
_GEM = inspect.getsource(research.start_agent_no_gemini_wait)
_P2 = inspect.getsource(research.run_phase2)
_RUNPIPE = inspect.getsource(research.run_pipeline)
_FAIL_AGENT = inspect.getsource(research.fail_agent)


# ── B1: timers ───────────────────────────────────────────────────────────────

def test_l1_stuck_threshold_is_15_min():
    assert '"DG_STUCK_NO_GROWTH_SEC", "900"' in _POLL


def test_l3_unacted_grace_is_30_min():
    assert '"DG_AUTO_SKIP_UNACTED_SEC", "1800"' in _POLL


# ── B2: planning counts as active ────────────────────────────────────────────

def test_planning_phase_gates_l1():
    # The scraper's separate `phase` field (Gemini planning states read
    # status='generating' + phase='planning') must feed status_is_active.
    assert '_scrape_phase == "planning"' in _POLL


def test_only_planning_phase_gates_never_researching():
    # phase='researching' can persist from stale panel steps on a frozen
    # page — gating on it would silence L1 entirely. Only "planning" gates.
    assert '_scrape_phase in _active_statuses' not in _POLL


# ── B3: arbiter prompt treats plan generation as WORKING ────────────────────

def test_arbiter_prompt_planning_is_working():
    assert "planning is NOT stuck" in _POLL
    assert "Generating research plan" in _POLL
    # The old wording that instructed STUCK on a plan page must be gone.
    assert "research plan with no actual findings" not in _POLL


# ── B4: disarm gaps ──────────────────────────────────────────────────────────

def test_working_reverdict_disarms_auto_skip():
    assert "WORKING re-verdict after a stuck alert" in _POLL
    # growth-recovery + arbiter-else + poke + wait-longer all zero the clock.
    assert _POLL.count('p["stuck_alerted_at"] = 0.0') >= 4


def test_poke_and_wait_longer_disarm_auto_skip():
    poke_idx = _POLL.index("consume_poke_agent")
    wait_idx = _POLL.index("consume_wait_longer_agent")
    dedupe_idx = _POLL.index("progress_key = json.dumps")
    poke_block = _POLL[poke_idx:wait_idx]
    wait_block = _POLL[wait_idx:dedupe_idx]
    assert 'p["stuck_alerted_at"] = 0.0' in poke_block
    assert 'p["stuck_alerted_at"] = 0.0' in wait_block


def test_2d_cua_recovery_retracts_early_card():
    # The shared retraction helper runs on the main-loop click AND both
    # CUA-recovery success paths (pre-fix only the main loop retracted).
    assert _P2.count("_retract_plan_alert(") >= 4  # def + 3 call sites
    assert '_retract_plan_alert("CUA recovery")' in _P2
    assert '_retract_plan_alert("CUA recovery re-draft")' in _P2


# ── B5: 2D streaming hold-off ────────────────────────────────────────────────

def test_2d_streaming_holdoff_exists():
    assert "GEMINI_PLAN_STREAM_MAX_SEC" in _P2
    assert "_last_stream_seen_at" in _P2
    # The early card must wait out fresh streaming evidence.
    assert "not _streaming_recent" in _P2


def test_2d_streaming_clock_feeds_only_on_raw_generating():
    # A failed scrape must NOT fake streaming (the emit path defaults
    # missing status to "generating"; the clock reads the RAW value).
    assert '(_gm.get("status") or "") == "generating"' in _P2


# ── C1: skip finalization in every path ──────────────────────────────────────

def test_2d_plan_wait_consumes_mid_wait_skip():
    assert "User skipped Gemini during the plan wait" in _P2
    assert "_gemini_2d_skipped" in _P2
    # Finalize = emit + close, exactly like the round-robin consumer.
    idx = _P2.index("User skipped Gemini during the plan wait")
    block = _P2[idx:idx + 700]
    assert 'emit_event("agent_skipped", phase=2, agent="gemini", reason="user_skip")' in block
    assert "_close_skipped_agent_tab" in block


def test_2d_cua_recovery_consumes_skip():
    assert "User skipped Gemini during CUA recovery" in _P2
    assert "User skipped Gemini at the end of CUA recovery" in _P2


def test_2d_skipped_agent_not_registered_for_round_robin():
    # A finalized mid-2D skip must never hand a closed tab to the pollers.
    idx = _P2.index('agents["Gemini"] = {"page": gemini_page')
    guard_region = _P2[max(0, idx - 400):idx]
    assert "_gemini_2d_skipped" in guard_region


def test_claude_hard_fail_auto_skip_finalizes():
    # Pre-fix: bare `skipped_agents.add` → the consumer stamped
    # reason="user_skip" on a skip nobody chose.
    assert 'reason="auto_skip_unanswered_timeout"' in _POLL
    idx = _POLL.index('reason="auto_skip_unanswered_timeout"')
    block = _POLL[idx - 2200:idx + 900]
    assert '"status": "auto_skipped"' in block
    assert "_close_skipped_agent_tab" in block
    assert "del pending[name]" in block


# ── C2: hands-off salvage guards ─────────────────────────────────────────────

def test_l3_auto_skip_salvage_respects_hv_blocked():
    idx = _POLL.index("Auto-skip salvage extract failed")
    block = _POLL[idx - 1600:idx]
    assert "hv_blocked" in block


def test_hard_fail_salvage_respects_hv_blocked():
    idx = _POLL.index('reason="auto_skip_unanswered_timeout"')
    block = _POLL[idx - 2200:idx]
    assert "hv_blocked" in block


# ── D1: fail_agent suppressed during --login teardown ────────────────────────

def test_fail_agent_login_guard_in_source():
    assert "_login_interrupt_active()" in _FAIL_AGENT
    assert "fail_agent suppressed" in _FAIL_AGENT


def test_fail_agent_noops_during_login_teardown(monkeypatch):
    calls = []
    monkeypatch.setattr(research, "_login_interrupt_active", lambda *a, **k: True)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: calls.append(("emit", a, k)))
    monkeypatch.setattr(research, "_write_agent_terminal_status",
                        lambda *a, **k: calls.append(("status", a, k)))
    research.fail_agent("gemini", "Couldn't send the brief to Gemini", "details")
    assert calls == [], "fail_agent must emit nothing during --login teardown"


def test_login_marker_with_dead_pid_is_not_active(tmp_path, monkeypatch):
    # #929 (review-hardened): a hard-killed --login (taskkill /F, power
    # loss) skips the atexit marker clear. With only the 30-min age check,
    # fail_agent's teardown suppression would swallow every REAL error card
    # on a healthy run for up to 30 minutes. A recorded-but-dead pid must
    # read as NOT active.
    import json as _json
    import time as _time
    marker = tmp_path / "login_in_progress.json"
    monkeypatch.setattr(research, "_login_marker_path", lambda: marker)
    # Fresh marker, dead pid (pid 2^22+ is far above any real Windows pid
    # in a normal session; if it happens to exist the test still holds via
    # a second definitely-dead pid probe below).
    import psutil
    dead_pid = 4194000
    while psutil.pid_exists(dead_pid):
        dead_pid += 1
    marker.write_text(_json.dumps({"ts": int(_time.time() * 1000), "pid": dead_pid}),
                      encoding="utf-8")
    assert research._login_interrupt_active() is False
    # Same marker with OUR (alive) pid → active.
    import os as _os
    marker.write_text(_json.dumps({"ts": int(_time.time() * 1000), "pid": _os.getpid()}),
                      encoding="utf-8")
    assert research._login_interrupt_active() is True
    # Legacy pid-less marker keeps the pure age semantics.
    marker.write_text(_json.dumps({"ts": int(_time.time() * 1000)}), encoding="utf-8")
    assert research._login_interrupt_active() is True
    # Stale marker (age cap) stays inactive regardless of pid.
    marker.write_text(_json.dumps({"ts": int((_time.time() - 3600) * 1000),
                                   "pid": _os.getpid()}), encoding="utf-8")
    assert research._login_interrupt_active() is False


def test_fail_agent_works_when_no_login_in_flight(monkeypatch):
    calls = []
    monkeypatch.setattr(research, "_login_interrupt_active", lambda *a, **k: False)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: calls.append(("emit", a, k)))
    monkeypatch.setattr(research, "_write_agent_terminal_status",
                        lambda *a, **k: calls.append(("status", a, k)))
    research.fail_agent("gemini", "Couldn't send the brief to Gemini", "details")
    kinds = [c[0] for c in calls]
    assert "emit" in kinds and "status" in kinds
    emit_call = next(c for c in calls if c[0] == "emit")
    assert emit_call[1][0] == "pipeline_error"
    status_call = next(c for c in calls if c[0] == "status")
    assert status_call[1] == ("gemini", "errored")


# ── A1/A2: phase restart signal + persisted status reset ─────────────────────

def test_resume_emits_full_phase_restart():
    idx = _RUNPIPE.index('resumeReason=reason')
    block = _RUNPIPE[idx:idx + 1400]
    assert 'emit_event("phase_restart", phase=start_phase' in block
    assert 'reason="resume_from_checkpoint", full=True' in block


def test_full_flag_only_on_resume_path():
    # Soft-retry phase_restart emits must NOT carry full=True (the FE wipes
    # phase UI on that flag — a soft retry keeps its agents running).
    # Count call sites (`full=True)`), not comments.
    assert _SRC.count("full=True)") == 1


def test_launch_sites_reset_persisted_agent_status():
    # #929 (review-hardened): the "running" reset lives at each agent's
    # LAUNCH site — a phase-entry write stranded never-launched agents on a
    # persisted "running" when the user stopped during the sequential
    # launch window.
    assert '_write_agent_terminal_status("chatgpt", "running")' in _P2
    assert '_write_agent_terminal_status("claude", "running")' in _P2
    assert '_write_agent_terminal_status("gemini", "running")' in _P2
    assert '_write_agent_terminal_status(_stale_ag, "running")' not in _P2


# ── E: copy — platform display name, never the internal step label ──────────

def test_brief_fail_copy_uses_platform_not_label():
    # 2026-07-13 (#949): 2 -> 3 — the pre-send attachment re-check added a
    # third fail site (chip lost at send time), same platform-name rule.
    assert _GEM.count('f"Couldn\'t send the brief to {platform}"') == 3
    assert "brief to {label}" not in _GEM
