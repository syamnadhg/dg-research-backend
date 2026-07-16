"""#921 (2026-07-08): P2 alert/retry consistency + three stale-run incidents.

User E2E 2026-07-08 surfaced three ways a real problem became INVISIBLE
instead of becoming a card, plus inconsistent alert mechanics:

  Incident #1 — Skip left an already-errored agent's tile RED (and took two
    clicks). The round-robin skip consumer's "agent already left `pending`"
    branch (an earlier fail_agent dropped it) only closed the tab; it never
    emitted agent_skipped nor wrote status="skipped", so the FE tile (which
    binds to the persisted agents[key].status) stayed on the fail_agent
    "errored" write forever.

  Incident #2 — Claude sat 36 min on an empty "Research plan created"
    placeholder with a stale complete-marker; detect_completion_claude
    confirmed done on a {0,0,0} snapshot → a 0-char extraction → churn, and
    the no-growth watchdog (gated behind `_cua_check_age > 1200`, never true)
    never raised a card.

  Incident #3 — Gemini answered the brief as plain chat; no research plan /
    no "Start research" ever rendered. The honest [Retry][Skip] card lived
    only after the full 300s plan-wait + a 3x CUA recovery ladder (~17 min),
    so the run sat with no card until a manual Stop.

Fixes verified here:
  - skip elif emits agent_skipped (+ guards a complete agent);
  - chat-mode Skip no longer double-fires fail_agent("was skipped");
  - detect_completion_claude rejects a done-marker on an empty snapshot;
  - Layer-1 CUA-arbitrated stuck detector (replaces the dead recency gate) +
    Layer-3 auto-skip (unacted card / 90-min hard cap);
  - Gemini submit retries standardized to 3; 2D raises an early card.
"""

import inspect
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import research  # noqa: E402

_SRC = Path(research.__file__).read_text(encoding="utf-8")
_POLL = inspect.getsource(research.poll_all_agents_round_robin)
_GEM = inspect.getsource(research.start_agent_no_gemini_wait)
_P2 = inspect.getsource(research.run_phase2)


class _FakePage:
    """Minimal page whose evaluate() returns a fixed dict (detectors read it)."""
    def __init__(self, result):
        self._result = result

    async def evaluate(self, js):
        return self._result


# ── Incident #1: Skip greys an already-errored agent ────────────────────────

def test_skip_elif_emits_agent_skipped():
    # The "agent left `pending`" branch must now emit agent_skipped with a
    # reason (the emit_event hook flips persisted errored→skipped → tile greys)
    # + retract the durable card — not merely close the tab.
    assert 'reason="user_skip_after_leaving_poll"' in _POLL
    assert "user left the poll" not in _POLL.lower() or "agent_skipped" in _POLL
    # Emitted inside the skip-consumer's elif (near _close_skipped_agent_tab).
    assert _POLL.count('emit_event("agent_skipped"') >= 2, (
        "both the in-pending IF and the already-left elif must emit agent_skipped"
    )


def test_skip_elif_guards_completed_agent():
    # A stale/duplicate skip must never grey a genuinely-COMPLETE agent.
    assert '_recorded_status != "complete"' in _POLL
    assert "_agent_status_by_rid" in _POLL


# ── Consistency: no chat-mode skip → fail_agent double-fire ──────────────────

def test_chat_mode_skip_no_double_fire():
    # Gap #1: chat_mode is non-blocking now — the inline blocking gate branches
    # (which carried the fail_agent double-fire risk) are gone from start_agent.
    # Keep/skip is resolved by the round-robin parked-decision resolver via a
    # single _finalize_agent_autoskip (agent_skipped greys + retracts the card;
    # no second RED fail card). The old double-fire call must stay gone.
    assert 'f"{_agent_name} was skipped"' not in _GEM, (
        "the fail_agent('<name> was skipped') double-fire must be gone"
    )
    # the inline blocking skip branches are gone from start_agent.
    assert "retry_on_chat_mode_alert_unsupported" not in _GEM
    assert 'request_pause(f"{platform_l}_chat_mode")' not in _GEM
    # resolution moved to the resolver: a single finalize, no red fail_agent.
    _res = inspect.getsource(research._resolve_parked_agent_decision)
    assert 'if kind == "chat_mode":' in _res
    assert "_finalize_agent_autoskip(" in _res


# ── Incident #2: detect_completion_claude rejects an empty done-marker ───────

def _detect(**kw):
    data = {"hasStop": False, "liveActive": False, "researchDone": False,
            "researchCardDone": False, "textLen": 0, "sources": 0, "steps": 0}
    data.update(kw)
    return asyncio.run(research.detect_completion_claude(_FakePage(data)))


def test_detect_claude_rejects_empty_done_marker():
    done, reason, snap = _detect(researchCardDone=True, textLen=0, sources=0, steps=0)
    assert done is False, "a done-marker on a {0,0,0} snapshot is a false-done"
    assert "empty_snapshot" in reason
    assert snap == {"text_len": 0, "sources": 0, "steps": 0}


def test_detect_claude_confirms_nonempty_done():
    done, reason, _ = _detect(researchDone=True, textLen=5000, sources=40, steps=8)
    assert done is True
    assert "research_complete_marker" in reason


def test_detect_claude_confirms_done_with_only_sources():
    # Not fully empty (has sources) → still a real completion.
    done, _, _ = _detect(researchCardDone=True, textLen=0, sources=12, steps=0)
    assert done is True


def test_detect_claude_stop_button_still_wins():
    # Regression: an existing hard gate — a visible Stop button always means
    # generating, regardless of a stale marker.
    done, reason, _ = _detect(hasStop=True, researchDone=True, textLen=9000)
    assert done is False and "stop_btn" in reason


# ── Incident #2 + core: Layer-1 stuck arbiter replaces the dead recency gate ─

def test_dead_cua_recency_gate_removed():
    # The variable is no longer COMPUTED (only referenced in explanatory
    # comments) — so the never-true gate that silenced genuine stalls is gone.
    assert "_cua_check_age =" not in _POLL, (
        "the never-true recency gate that silenced genuine stalls must be gone"
    )


def test_stuck_detector_is_growth_and_cua_arbitrated():
    # A CUA arbiter decides stuck-vs-slow at the no-growth point, distinguishing
    # an empty/frozen placeholder (stuck) from a working-but-scrape-blind agent
    # (the 2026-04-28 1,289-source false-positive class).
    assert "STUCK_NO_GROWTH_SEC" in _POLL
    assert "poll-stuck-arbiter" in _POLL
    assert "CONCLUSION: stuck" in _POLL or r"conclusion\s*:\s*(stuck|working)" in _POLL
    # Conservative default — never a false card/auto-skip on doubt.
    assert "conservative" in _POLL.lower()


def test_stuck_constants_defaults():
    # #929 (2026-07-09): 600→900 / 1200→1800 after a live false alarm on a
    # healthy >10-min Gemini plan (carded at 10 min, auto-skipped at +20).
    assert 'DG_STUCK_NO_GROWTH_SEC", "900"' in _POLL
    assert 'DG_AUTO_SKIP_UNACTED_SEC", "1800"' in _POLL
    assert 'DG_PER_AGENT_HARD_CAP_SEC", "5400"' in _POLL


# ── Layer-3 auto-skip backstop ───────────────────────────────────────────────

def test_layer3_auto_skip_present():
    assert "PER_AGENT_HARD_CAP_SEC" in _POLL
    assert "AUTO_SKIP_UNACTED_SEC" in _POLL
    assert "auto_skip_hard_cap" in _POLL
    assert "auto_skip_stuck_no_response" in _POLL


def test_stuck_alert_cancelled_on_recovery():
    # False-positive guard: if a stuck-flagged agent RESUMES producing output,
    # the auto-skip countdown (stuck_alerted_at) must be cancelled + the card
    # retracted — never auto-skip a recovered agent on a stale alert.
    assert 'p["stuck_alerted_at"] = 0.0' in _POLL
    assert "growth resumed" in _POLL
    assert "Recovered after a stuck alert" in _POLL


def test_stuck_arbiter_defaults_working_on_probe_error():
    # A CUA probe failure must NOT fire a card / auto-skip (conservative).
    assert "_confirmed_stuck = False" in _POLL
    assert 'if unsure' in _POLL.lower() or "If unsure" in _POLL


def test_auto_skip_is_user_controllable():
    # Settings → Pipeline "Auto-skip stuck agents" (default ON). EVERY auto-skip
    # is gated on _runtime.auto_skip_stuck; the Layer-1 stuck card is NOT gated
    # (it always surfaces so the user knows).
    # #955 Phase 2: the unacted-card auto-skip moved to the registry firer
    # (_fire_due_autoskips), which early-returns when auto-skip is OFF; the
    # in-loop branch keeps ONLY the 90-min hard cap, still behind the same gate.
    assert "if not _runtime.auto_skip_stuck:" in _POLL              # firer's gate
    assert "_runtime.auto_skip_stuck and _hit_hard_cap" in _POLL    # in-loop hard cap
    # Default True on the runtime object + primed per-run from config.json.
    assert "self.auto_skip_stuck: bool = True" in _SRC
    assert 'pipeline_config.get("autoSkipStuck", True)' in _SRC


def test_layer3_auto_skip_is_single_agent_and_notifies():
    # Auto-skip drops ONLY this agent (others keep output), greys its tile
    # (agent_skipped) and posts an informational notice. #955: the emit +
    # notice + tab-close collapsed into the ONE _finalize_agent_autoskip helper.
    # #955 Phase 2: the UNACTED-card L3 auto-skip moved OUT of the per-agent leg
    # into the registry firer _fire_due_autoskips (fires off the armed deadline
    # the FE counts down to). Pin THAT firer — single agent, stuck copy, honest
    # reason, drops from pending, disarms the registry, hands-off on a walled tab.
    assert "async def _fire_due_autoskips" in _POLL
    _fs = _POLL.index("async def _fire_due_autoskips")
    _fire = _POLL[_fs:_POLL.index("if not pending:", _fs)]   # the closure body
    assert 'reason="auto_skip_stuck_no_response"' in _fire
    assert 'copy_key="stuck"' in _fire
    assert "_finalize_agent_autoskip(" in _fire
    assert "del pending[_nm]" in _fire          # this agent, not a sibling
    assert "_disarm_registry(_key)" in _fire    # deadline purged on fire
    assert "_controls.hv_blocked" in _fire      # hands-off: no extract from a walled tab
    # The in-loop branch keeps the independent 90-min hard cap — also per-agent,
    # routed through the same helper, dropping just this agent from pending.
    _hc = _POLL.index('copy_key="stuck", why=_as_why')
    _hcblk = _POLL[_hc - 500:_hc + 400]
    assert "_finalize_agent_autoskip(" in _hcblk
    assert "del pending[name]" in _hcblk
    # The finalize helper greys the tile + posts the notice (single source).
    _fin = inspect.getsource(research._finalize_agent_autoskip)
    assert 'emit_event("agent_skipped", phase=phase, agent=key' in _fin
    assert 'alert_id=f"agent_{key}_autoskip"' in _fin
    assert 'emit_event("pipeline_warning"' in _fin


# ── Incident #3: Gemini submit retries = 3 + early 2D card ───────────────────

def test_gemini_submit_retries_standardized_to_3():
    assert "_max_attempts = 3" in _GEM


def test_gemini_2d_raises_early_card():
    assert "_plan_alert_emitted" in _P2
    assert "_PLAN_ALERT_SEC" in _P2
    assert "Gemini couldn't start Deep Research" in _P2
    # Non-blocking + retracted if the plan recovers.
    assert "Retracted the early plan-stall card" in _P2


def test_gemini_2d_early_card_fires_once():
    # Guarded by _plan_alert_emitted so the loop can't spam the card each tick.
    assert "not _plan_alert_emitted" in _P2


# ── syntax / import sanity ───────────────────────────────────────────────────

def test_module_imports_and_functions_exist():
    for nm in ("poll_all_agents_round_robin", "start_agent_no_gemini_wait",
               "run_phase2", "detect_completion_claude", "fail_agent",
               "emit_event"):
        assert callable(getattr(research, nm))
