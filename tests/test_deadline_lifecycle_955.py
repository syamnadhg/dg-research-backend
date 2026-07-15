"""#955 Phase 2 — the auto-skip deadline lifecycle (arm / fire / disarm).

Phase 2 gives the round-robin stuck card ONE deadline SOURCE (emit_decision
stamps `auto_skip_deadline`, the FE <AutoSkipCountdown> counts down to it) and
fires it from the tick (_fire_due_autoskips) off that same value — no drift
between the shown countdown and the real fire. These tests exercise the
registry primitives directly (arming, the per-agent + clear-all disarm, the
blocker guard, the one-live-entry invariant, and the two-card-orphan case that
motivated disarming BEFORE the mirror keep-guard), plus the central resolve
seam (agent-scoped vs whole-run clears — the pause→resume→no-fire path).

The firer itself is a closure inside poll_all_agents_round_robin (needs a live
browser to drive), so its structure is pinned in test_alert_consistency_921's
rewritten test_layer3_auto_skip_is_single_agent_and_notifies; here we pin the
epoch-ms unit + comparison so BE-fire and FE-render can never disagree.

Run: pytest tests/test_deadline_lifecycle_955.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

_POLL = inspect.getsource(research.poll_all_agents_round_robin)


def _reset():
    research._pending_decisions.clear()
    research._active_decisions.clear()


def _arm_stub(monkeypatch):
    """Silence emit_event's side effects so an emit_decision arm is a pure
    registry write we can inspect (mirrors test_alert_intents._capture)."""
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_phase_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    monkeypatch.setattr(research, "_persist_pending_decision", lambda *a, **k: None)


def _seam_stub(monkeypatch):
    """Keep the REAL emit_event (so its central resolve seam runs) but stub the
    external I/O it drives — Firestore writes + terminal-status persistence.
    emit_event no-ops when `_tracks_dir` is falsy (no active run), so give it a
    truthy dummy to make it run the seam in a bare test process."""
    monkeypatch.setattr(research, "_tracks_dir", object(), raising=False)
    monkeypatch.setattr(research, "_emit_to_firestore", lambda *a, **k: None)
    monkeypatch.setattr(research, "_update_firestore_research", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_phase_terminal_status", lambda *a, **k: None)


# ── Arming (emit_decision) ───────────────────────────────────────────────────

def test_recoverable_deadline_arms_registry(monkeypatch):
    _reset()
    _arm_stub(monkeypatch)
    did = research.emit_decision(
        phase=2, agent="Gemini", title="stuck", actions=[{"id": "x"}],
        recoverability="recoverable", alert_id="a1",
        auto_skip_deadline=1_700_000_000_000)
    assert did in research._pending_decisions
    e = research._pending_decisions[did]
    assert e["agent"] == "gemini"            # normalized lower
    assert e["deadline"] == 1_700_000_000_000
    assert e["recoverability"] == "recoverable"
    assert e["alert_id"] == "a1"
    assert did in research._active_decisions


def test_no_deadline_does_not_arm(monkeypatch):
    _reset()
    _arm_stub(monkeypatch)
    did = research.emit_decision(
        phase=2, agent="Gemini", title="t", actions=[{"id": "x"}],
        recoverability="recoverable", alert_id="a1")
    assert did not in research._pending_decisions
    assert research._pending_decisions == {}
    # still tracked as a live decision (for the Phase-3 copy upgrade), just
    # never arms a countdown.
    assert did in research._active_decisions


@pytest.mark.parametrize("klass", ["blocker", "infra"])
def test_blocker_and_infra_refuse_a_deadline(monkeypatch, klass):
    _reset()
    _arm_stub(monkeypatch)
    with pytest.raises(ValueError, match="never auto-fire"):
        research.emit_decision(
            phase=1, agent="chatgpt", title="log in", actions=[{"id": "x"}],
            recoverability=klass, alert_id="a1",
            auto_skip_deadline=1_700_000_000_000)
    # A refused arm must not have half-written the registry.
    assert research._pending_decisions == {}


def test_no_deadline_recard_supersedes_armed_entry(monkeypatch):
    # Adversarial findings #5/#6: a stuck-armed agent that then reports an error
    # / hits session-expiry / a login wall is re-carded with NO deadline. That
    # re-card MUST drop the stale stuck deadline (the supersede purge runs even
    # for a no-deadline card) — else it outlives the card it was armed for and
    # later auto-skips the agent off wrong copy, even while parked for the user.
    _reset()
    _arm_stub(monkeypatch)
    research.emit_decision(
        phase=2, agent="gemini", title="stuck", actions=[{"id": "x"}],
        recoverability="recoverable", alert_id="a1", auto_skip_deadline=111)
    assert any(e["agent"] == "gemini" for e in research._pending_decisions.values())
    # Re-card as a no-deadline recoverable "reported an error" card.
    research.emit_decision(
        phase=2, agent="gemini", title="Gemini reported an error",
        actions=[{"id": "x"}], recoverability="recoverable", alert_id="a2")
    assert not any(e["agent"] == "gemini" for e in research._pending_decisions.values()), (
        "a no-deadline re-card must drop the agent's stale armed deadline"
    )


def test_one_live_entry_per_agent(monkeypatch):
    _reset()
    _arm_stub(monkeypatch)
    d1 = research.emit_decision(
        phase=2, agent="gemini", title="t", actions=[{"id": "x"}],
        recoverability="recoverable", alert_id="a1", auto_skip_deadline=111)
    d2 = research.emit_decision(
        phase=2, agent="gemini", title="t", actions=[{"id": "x"}],
        recoverability="recoverable", alert_id="a2", auto_skip_deadline=222)
    # The re-armed deadline supersedes the first — never two live entries for
    # one agent (the firer would otherwise act on whichever it hit first).
    live = [e for e in research._pending_decisions.values() if e["agent"] == "gemini"]
    assert len(live) == 1
    assert live[0]["deadline"] == 222
    assert d1 not in research._pending_decisions and d2 in research._pending_decisions
    assert d1 not in research._active_decisions   # stale id retired


# ── fail_agent passthrough ───────────────────────────────────────────────────

def test_fail_agent_arms_when_deadline_passed(monkeypatch):
    _reset()
    _arm_stub(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_agent("gemini", "Gemini seems stuck", "…",
                        auto_skip_deadline=999)
    live = [e for e in research._pending_decisions.values() if e["agent"] == "gemini"]
    assert len(live) == 1
    assert live[0]["deadline"] == 999
    assert live[0]["recoverability"] == "recoverable"


def test_fail_agent_default_does_not_arm(monkeypatch):
    _reset()
    _arm_stub(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_agent("gemini", "Gemini failed", "…")
    assert research._pending_decisions == {}


def test_fail_agent_skip_only_never_arms(monkeypatch):
    # hands_off (Cloudflare) fires loop-locally from its own HV wait, NEVER via
    # this registry — so even with a deadline passed, skip_only must not arm.
    _reset()
    _arm_stub(monkeypatch)
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_agent("gemini", "wall", "…", skip_only=True,
                        auto_skip_deadline=999)
    assert research._pending_decisions == {}


# ── _disarm_registry ─────────────────────────────────────────────────────────

def _seed_two():
    _reset()
    research._pending_decisions["d_g"] = {
        "phase": 2, "agent": "gemini", "alert_id": "g",
        "deadline": 1, "recoverability": "recoverable"}
    research._pending_decisions["d_c"] = {
        "phase": 2, "agent": "chatgpt", "alert_id": "c",
        "deadline": 1, "recoverability": "recoverable"}
    research._active_decisions.update({"d_g", "d_c"})


def test_disarm_agent_scoped_keeps_siblings():
    _seed_two()
    research._disarm_registry("gemini")
    assert "d_g" not in research._pending_decisions
    assert "d_c" in research._pending_decisions          # sibling untouched
    assert "d_g" not in research._active_decisions
    assert "d_c" in research._active_decisions


def test_disarm_is_case_insensitive():
    _seed_two()
    research._disarm_registry("GEMINI")
    assert "d_g" not in research._pending_decisions
    assert "d_c" in research._pending_decisions


def test_disarm_all_clears_everything():
    _seed_two()
    research._disarm_registry("__all__")
    assert research._pending_decisions == {}
    assert research._active_decisions == set()


def test_disarm_none_is_noop():
    _seed_two()
    research._disarm_registry(None)
    assert set(research._pending_decisions) == {"d_g", "d_c"}


# ── two-card orphan: disarm BEFORE the mirror keep-guard ─────────────────────

def test_clear_pending_decision_disarms_before_keep_guard(monkeypatch):
    # The scenario the pre-guard disarm exists for: agent A (gemini) has a stuck
    # deadline armed; agent B (chatgpt) owns the single durable-mirror slot. A
    # recovers → growth-recovery calls _clear_pending_decision("gemini"). The
    # mirror keep-guard MUST leave B's card intact (it isn't A's) — but A's
    # deadline MUST still be dropped, else the firer auto-skips a recovered A.
    monkeypatch.setattr(research, "_update_firestore_research", lambda *a, **k: None)
    _reset()
    research._pending_decisions["d_g"] = {
        "phase": 2, "agent": "gemini", "alert_id": "g",
        "deadline": 1, "recoverability": "recoverable"}
    research._active_decisions.add("d_g")
    # B (chatgpt) owns the live mirror.
    research._pending_decision_active = True
    research._pending_decision_agent = "chatgpt"

    research._clear_pending_decision("gemini")

    assert "d_g" not in research._pending_decisions      # A disarmed …
    assert research._pending_decision_agent == "chatgpt"  # … B's mirror kept


# ── central resolve seam (real emit_event) ───────────────────────────────────

def test_seam_agent_skipped_scoped(monkeypatch):
    _seam_stub(monkeypatch)
    _seed_two()
    research.emit_event("agent_skipped", phase=2, agent="gemini",
                        reason="user_skip")
    assert "d_g" not in research._pending_decisions
    assert "d_c" in research._pending_decisions          # sibling survives a skip


def test_seam_agent_carrying_resume_scoped(monkeypatch):
    _seam_stub(monkeypatch)
    _seed_two()
    research.emit_event("pipeline_resumed", phase=2, agent="gemini",
                        reason="retry")
    assert "d_g" not in research._pending_decisions
    assert "d_c" in research._pending_decisions


def test_seam_whole_run_resume_clears_all(monkeypatch):
    # pause→resume→no-fire: the whole-run pause emits an AGENT-LESS
    # pipeline_resumed (research.py ~24122); its rebuilt `pending` carries no
    # stuck bookkeeping, so the module-global registry MUST be cleared or a
    # stale deadline fires on the first post-resume tick.
    _seam_stub(monkeypatch)
    _seed_two()
    research.emit_event("pipeline_resumed", phase=2)
    assert research._pending_decisions == {}


def test_seam_pipeline_stopped_clears_all(monkeypatch):
    _seam_stub(monkeypatch)
    _seed_two()
    research.emit_event("pipeline_stopped", phase=2, reason="stopped")
    assert research._pending_decisions == {}


@pytest.mark.parametrize("evt", ["phase_skipped", "phase_restart"])
def test_seam_phase_level_signals_clear_all(monkeypatch, evt):
    _seam_stub(monkeypatch)
    _seed_two()
    research.emit_event(evt, phase=2)
    assert research._pending_decisions == {}


# ── unit consistency: epoch-ms SOURCE == firer comparison == FE countdown ────

def test_arm_and_fire_share_epoch_ms_units():
    # The stuck site arms `int((now + AUTO_SKIP_UNACTED_SEC) * 1000)` (epoch-ms,
    # exactly what the FE <AutoSkipCountdown> subtracts from Date.now()); the
    # firer compares `time.time() * 1000` against it. Both in ms ⇒ the shown
    # countdown and the real fire land on the SAME instant.
    assert "int((time.time() + AUTO_SKIP_UNACTED_SEC) * 1000)" in _POLL
    assert "_now_ms = time.time() * 1000" in _POLL
    assert "_now_ms < _dl" in _POLL          # not-yet-due ⇒ skip
    # The countdown is armed ONLY when auto-skip is ON — else the FE would count
    # down to a fire the (gated) firer never performs.
    assert "if _runtime.auto_skip_stuck else None)" in _POLL
    # 90-min hard cap stays OFF the registry (silent backstop, no countdown).
    assert "_hit_hard_cap = elapsed >= PER_AGENT_HARD_CAP_SEC" in _POLL


def test_all_disarm_sites_present_in_the_poll_loop():
    # The armed deadline must be dropped at every recovery / resolution point in
    # the loop, or a recovered agent is auto-skipped off a stale deadline.
    assert _POLL.count("_disarm_registry(agent_key_stuck)") >= 4   # growth/WORKING/poke/wait
    assert "_disarm_registry(_pk_key)" in _POLL                    # parked hard-cap
    assert "_disarm_registry(_agent_key)" in _POLL                 # hard-retry restart
    assert "_disarm_registry(_key)" in _POLL                       # the firer's own purge
    assert "_disarm_registry(_crash_key)" in _POLL                 # browser-crash sweep (finding #1)


def test_firer_skips_parked_agents():
    # Adversarial finding #6: a parked agent (awaiting a user decision) must be
    # governed by the parked-decision resolver, never auto-skipped by the stuck
    # firer off a stale deadline.
    _fs = _POLL.index("async def _fire_due_autoskips")
    _fire = _POLL[_fs:_POLL.index("if not pending:", _fs)]
    assert 'if _p.get("awaiting_decision"):' in _fire


def test_firer_revalidates_after_salvage_await():
    # Adversarial finding #4 (TOCTOU): a user Retry/Skip landing during the
    # multi-second salvage-extract await must win — the firer re-checks LIVE
    # state before committing the auto-skip.
    _fs = _POLL.index("async def _fire_due_autoskips")
    _fire = _POLL[_fs:_POLL.index("if not pending:", _fs)]
    assert "if _did not in _pending_decisions or _nm not in pending:" in _fire
    # The re-check sits AFTER the salvage await and BEFORE the finalize.
    _await = _fire.index("extract_fns[_nm]")
    _revalidate = _fire.index("if _did not in _pending_decisions")
    _finalize = _fire.index("_finalize_agent_autoskip(")
    assert _await < _revalidate < _finalize


def test_firer_runs_at_end_of_tick_and_bails_on_stop_pause():
    # Adversarial re-verify regression: the fire must run AFTER the per-agent
    # rotation (so this tick's growth-recovery / arbiter / poke / wait-longer
    # disarms precede it) — NOT before it (which raced those disarms and
    # auto-skipped a just-resumed agent one cycle early).
    _rot = _POLL.index("for name in _pending_keys:")
    _fire_call = _POLL.rindex("await _fire_due_autoskips()")
    assert _fire_call > _rot, "the fire call must sit after the rotation loop (end-of-tick)"
    # And the firer bails under stop/pause (it does real page I/O).
    _fs = _POLL.index("async def _fire_due_autoskips")
    _fire = _POLL[_fs:_POLL.index("if not pending:", _fs)]
    assert "_controls.is_stop() or _controls.is_pause()" in _fire


def test_run_pipeline_wipes_registry_at_entry():
    # Adversarial findings #1/#2/#3/#5: the module-global registry survives
    # across in-process runs; run_pipeline entry must clear it so a stranded
    # deadline can't auto-skip a healthy same-key agent in the NEXT run.
    _rp = inspect.getsource(research.run_pipeline)
    _reset_at = _rp.index("_runtime.reset()")
    assert '_disarm_registry("__all__")' in _rp[_reset_at:_reset_at + 900]
