"""#953 (2026-07-13, 18:16 E2E run): four bugs from one Gemini auto-start incident
+ a Claude interactive question card.

THE RUN (backend.log wk1 18:16–19:09): Gemini drafted its plan by ~95s and
AUTO-STARTED the research — the plan bubble's 'Start research' button rendered
already-DISABLED and no click was ever needed. Four failures cascaded:

1. SPAM — the [2D] wait misread the running research as "plan still streaming"
   (the heartbeat can't tell them apart), dwelt to the 900s hard cap, then the
   CUA recovery ladder spent ~7 min clicking the grayed Start button 3× (the
   user-visible "spamming Start Research").
2. STUCK AT GEMINI — the focused 2D dwell blocked the round-robin for 22 min
   (18:37→18:59); ChatGPT/Claude went unpolled the whole time.
3. CLAUDE QUESTIONS — Claude answered the brief with an interactive question
   card ("1 of 2" pager, numbered options, a Skip button) instead of starting
   research. The 2026-05-18 text-clarification path can't see the card (one
   '?', no sign-off) and its 180–900s window had EXPIRED before the round-robin
   first polled Claude at ~1500s.
4. FALSE ALARM + DESTROYED RESULT — the ladder's exhaustion fired a false
   "couldn't start" card on the healthy agent (research finished at 98k chars
   4 min later, extraction recorded 101,387 chars — but nothing retracted the
   card). The user's Retry(hard) click was consumed at 19:03:47, the very
   second extraction completed: the consumer closed the COMPLETED agent's tab,
   re-ran setup with an EMPTY brief (original_inputs carries no 'brief' on the
   full-pipeline path → "Paste verify: 1/0 chars" → an honest-at-the-time
   "couldn't send the brief" card = the user's screenshot), and the eventual
   Skip clobbered the recorded result with skipped_by_user/0 chars.

THE FIXES:
  A. Streaming hand-off: past GEMINI_PLAN_STREAM_HANDOFF_SEC (360s) of fresh
     streaming, 2D hands Gemini to the round-robin (a PLAN never streams that
     long) — no CUA ladder, no card. The ladder + card remain for the truly
     dead (non-streaming) plan only, with streaming re-probes guarding both.
  B. Late-Start watch leg: the round-robin's Gemini leg clears the watch once
     research is verified running (auto-start) or clicks a late-appearing
     ENABLED Start (slow plan) — the finder JS is hoisted to module scope so
     both call sites share the #905-hardened predicate.
  C. Patient click (user directive): click ONCE → 15s watch → at most ONE
     re-click → 15s watch. CUA prompt/hint/mission all forbid clicking a
     grayed Start ("research already running") and forbid double-clicks.
  D. Claude question card: _claude_skip_question_cards clicks Skip per question
     (conservative card-signature match), wired into the round-robin Claude leg
     (presence-driven, every tick) AND a 30s background sweep during the 2D
     dwell; the old text-clarification window widened 900→2700s.
  E. Completion retracts a stale failure card (extract_and_record success +
     _AGENT_ERROR_CARD_TS guard).
  F. Hard retry on a completed agent is dropped (card retracted instead);
     the retry brief falls back to the on-disk brief.md; a Skip can never
     clobber a recorded "done" result.

Run: pytest tests/test_bugs_953.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

P2_SRC = inspect.getsource(research.run_phase2)
POLL_SRC = inspect.getsource(research.poll_all_agents_round_robin)
EXTRACT_SRC = inspect.getsource(research.extract_and_record_agent)


# ── A: streaming hand-off ─────────────────────────────────────────────────────

def test_streaming_handoff_env_and_flag_exist():
    assert "GEMINI_PLAN_STREAM_HANDOFF_SEC" in P2_SRC
    assert "_streaming_handoff = True" in P2_SRC


def test_streaming_handoff_breaks_before_hard_cap():
    # The hand-off check must precede the 900s hard-cap check in the wait loop
    # (else a streaming Gemini dwells the full cap first — the 22-min bug).
    i_handoff = P2_SRC.index("_elapsed >= _stream_handoff_sec and _streaming_recent")
    i_cap = P2_SRC.index("_elapsed >= _stream_max_sec")
    assert i_handoff < i_cap


def test_cua_ladder_gated_off_on_streaming_handoff():
    # The ladder must not run for a streaming hand-off — pointing the CUA at a
    # healthy streaming Gemini is what produced the click spam.
    i_gate = P2_SRC.index("not start_clicked and not _streaming_handoff\n"
                          "                and not _controls.is_stop()")
    assert i_gate > 0


def test_ladder_reprobes_streaming_before_each_attempt():
    # Even in the dead-plan ladder, a page that resumed generating must stand
    # the ladder down (research may auto-start late).
    assert "streaming again mid-recovery" in P2_SRC
    i_probe = P2_SRC.index("streaming again mid-recovery")
    i_click = P2_SRC.index("CUA recovery: clicked 'Start research' via JS", i_probe)
    assert i_probe < i_click, "the re-probe runs before the ladder touches the page"


def test_fail_agent_guarded_by_final_streaming_probe():
    # The false "couldn't start" card fired on an agent that was mid-research.
    # A final scrape must veto the card when Gemini is actively generating.
    i_final = P2_SRC.index("_final_streaming")
    # #63: couldn't-start copy centralized in the _GEMINI_CANT_START constant.
    i_card = P2_SRC.index('fail_agent("gemini", *_GEMINI_CANT_START)', i_final)
    assert i_final < i_card
    assert "elif not _controls.is_stop():" in P2_SRC


def test_handoff_registers_watch_flag_not_failure():
    # The hand-off is healthy: agent registered with gemini_watch_start=True,
    # plan alert retracted, and NO scary "may not be running" warn.
    assert '"gemini_watch_start": bool(_streaming_handoff)' in P2_SRC
    assert '_retract_plan_alert("streaming hand-off")' in P2_SRC
    assert "streaming hand-off — round-robin takes it from here" in P2_SRC


# ── B: round-robin late-Start watch leg ──────────────────────────────────────

def test_watch_leg_exists_and_uses_shared_finder():
    assert 'p.get("gemini_watch_start")' in POLL_SRC
    assert "_GEMINI_CLICK_START_JS" in POLL_SRC
    # And the pending construction threads the flag through.
    assert '"gemini_watch_start": bool(agent.get("gemini_watch_start"))' in POLL_SRC


def test_watch_leg_clears_on_research_specific_evidence_not_verify_alone():
    # Audit #953-1: branch (a) must clear on RESEARCH-specific evidence
    # (_gemini_research_started / done_count), NEVER verify_gemini_generating
    # alone — that green-lights a plan still DRAFTING, which would clear the
    # watch on a slow plan and orphan its late Start.
    i = POLL_SRC.index('p.get("gemini_watch_start")')
    blk = POLL_SRC[i:i + 2600]
    assert "_gemini_research_started" in blk
    assert 'p.get("done_count", 0) > 0' in blk
    assert "auto-started" in blk
    # The ambiguous verify must NOT be the clear condition in this leg.
    assert "verify_gemini_generating" not in blk


def test_gemini_research_started_uses_research_regex_not_verify():
    src = inspect.getsource(research._gemini_research_started)
    assert "_GEMINI_RESEARCH_CARD_RE" in src
    assert "_GEMINI_COMPLETION_RE" in src
    # It must not CALL the ambiguous verifier (docstring may name it).
    assert "await verify_gemini_generating" not in src


def test_watch_leg_click_is_bounded_and_keeps_watch_armed():
    # Audit #953-4: the click keeps the watch ARMED (next leg is the took-check)
    # and is bounded (enabled-only, ≤3) so it can never spam the grayed button.
    i = POLL_SRC.index("Watch-start: late 'Start research' appeared")
    blk = POLL_SRC[i - 400:i + 900]
    assert 'p["start_time"] = _now_ws' in blk
    assert 'p["gemini_watch_click_count"] = _wc + 1' in blk
    assert "_wc < 3" in blk
    # It clicks only the ENABLED-Start finder, never a raw text match.
    pre = POLL_SRC[i - 1200:i]
    assert "_GEMINI_START_PRESENT_JS" in pre  # enabled-present probe gates the click


def test_shared_finder_is_module_scoped_and_hardened():
    pred = research._GEMINI_START_PREDICATE_JS
    assert "aria-disabled" in pred, "disabled Start buttons must never be clicked"
    assert "start research" in pred
    assert research._GEMINI_CLICK_START_JS.endswith("return false; }")
    assert research._GEMINI_START_PRESENT_JS.endswith("return false; }")


# ── C: patient click + CUA never clicks a grayed Start ───────────────────────

def test_click_once_then_patient_watch():
    # User directive: "send Start Research and wait, only retry if it doesn't
    # fire" — a 15s watch before the single re-click, not 2s-spaced triples.
    assert "_reclicks == 0" in P2_SRC
    assert "one re-click, then waiting again" in P2_SRC
    i = P2_SRC.index("for _vi in range(10):")
    blk = P2_SRC[i:i + 700]
    assert "asyncio.sleep(3)" in blk


def test_cua_prompt_forbids_grayed_click_and_double_click():
    p = research.PROMPT_GEMINI_START_RESEARCH.lower()
    assert "grayed" in p
    assert "research already running" in p
    assert "once" in p
    assert "never click a grayed/disabled button" in p


def test_gemini_start_hotspot_hint_matches():
    hint = research._HOTSPOT_VISION_HINTS["gemini-start"]["context_hint"].lower()
    assert "grayed" in hint and "research already running" in hint
    assert "never click a grayed button" in hint


# ── D: Claude question card → Skip ───────────────────────────────────────────

def test_skip_helper_exists_and_is_conservative():
    js = research._CLAUDE_QUESTION_CARD_JS
    # Exact-text Skip button…
    assert "'skip'" in js
    # …inside a container showing a question-card signature.
    assert "something else" in js
    assert "optionRows" in js
    # Never a disabled button.
    assert "aria-disabled" in js
    # Audit #953-7: compact-card altitude guard — oversized ancestors (prose)
    # can never bind a Skip.
    assert "txt.length > 1500" in js
    # Probe/click split: doClick param gates the actual click.
    assert "doClick" in js


def test_skip_helper_is_effect_verified_and_failsafe():
    # Audit #953-2: probe → click → settle → re-probe; a click that doesn't
    # advance the card (same pager still present) is NOT counted, so the
    # round-robin leg can't livelock re-skipping + rebasing forever.
    src = inspect.getsource(research._claude_skip_question_cards)
    assert "max_skips" in src
    assert "except Exception" in src
    assert 'after.get("present") and after.get("pager") == before.get("pager")' in src
    assert "ineffective" in src.lower()


def test_round_robin_claude_skip_has_cumulative_cap():
    # Audit #953-2: even effective skips are bounded cumulatively so a
    # pathological ever-questioning card can't rebase the watchdogs forever.
    assert "_Q_SKIP_TOTAL_CAP" in POLL_SRC
    assert 'p.get("question_card_skips", 0) < _Q_SKIP_TOTAL_CAP' in POLL_SRC
    assert 'p["question_card_skips"] = p.get("question_card_skips", 0) + _q_skips' in POLL_SRC


def test_round_robin_claude_leg_skips_cards_every_tick():
    # Presence-driven — no time window (the 2026-05-18 block's 180–900s window
    # expired before Claude's first poll in the incident run).
    i = POLL_SRC.index("_claude_skip_question_cards")
    blk = POLL_SRC[max(0, i - 1200):i + 1400]
    assert 'name == "Claude"' in blk
    assert "skipped them so the research starts" in blk
    # Wall-clock rebases after skipping (research starts now).
    assert 'p["start_time"] = _now' in blk


def test_2d_dwell_sweeps_claude_cards_in_background():
    # The card can render while 2D dwells on Gemini — a JS-only background
    # sweep (~30s cadence) must handle it without switching foreground.
    assert "_last_claude_q_probe" in P2_SRC
    i = P2_SRC.index("_last_claude_q_probe >= 30")
    blk = P2_SRC[i:i + 900]
    assert "_claude_skip_question_cards" in blk
    assert "switch_to_page" not in blk, "background sweep must not steal foreground"


def test_text_clarification_window_widened():
    assert "180 <= elapsed <= 2700" in POLL_SRC, (
        "the 900s upper bound expired before the round-robin's first Claude "
        "poll (22-min 2D dwell) — widened to 2700s"
    )


# ── E: completion retracts a stale failure card ──────────────────────────────

def test_extract_success_retracts_stale_card():
    i = EXTRACT_SRC.index('_write_agent_terminal_status(agent_key, "complete")')
    blk = EXTRACT_SRC[i:i + 1600]
    assert "_AGENT_ERROR_CARD_TS.get(agent_key)" in blk
    # 2026-07-14: retract id is now phase-tokened via the shared helper so it
    # matches the (now phase-qualified) fail_agent card it clears.
    assert "_agent_error_alert_id(agent_key, 2)" in blk
    assert "_clear_pending_decision(agent_key)" in blk
    assert "auto_clear_on_resume=True" in blk


def test_retraction_only_when_a_card_was_stamped():
    # Guarded on the #950 monotonic stamp — no spurious clearing emits for
    # agents that never had a card.
    i = EXTRACT_SRC.index('_write_agent_terminal_status(agent_key, "complete")')
    blk = EXTRACT_SRC[i:i + 1600]
    assert "if _AGENT_ERROR_CARD_TS.get(agent_key):" in blk


# ── F: hard retry / skip cannot destroy a completed agent ────────────────────

def test_hard_retry_dropped_for_completed_agent():
    i = POLL_SRC.index("consume_retry_agent_hard")
    blk = POLL_SRC[i:i + 4800]   # #955 P2: widened — the loop-top registry disarm added lines
    assert "Hard retry ignored" in blk
    assert '_rec_done.get("status") == "done"' in blk
    assert '== "complete"' in blk
    # The stale card is retracted, not left dangling. Re-anchored (#955 P2):
    # pin the clear right where the "already finished" retraction is emitted,
    # not by an absolute window offset (which flakes when nearby code shifts).
    assert "already finished" in blk
    _j = POLL_SRC.index('error=f"{_agent_name} already finished"')
    assert "_clear_pending_decision(_agent_key)" in POLL_SRC[_j:_j + 600]


def test_hard_retry_guard_precedes_stub_seeding():
    # The guard must run BEFORE the pre-pending stub seeding that re-opens
    # tabs / re-runs setup (that seeding destroyed the completed Gemini).
    i_guard = POLL_SRC.index("Hard retry ignored")
    i_seed = POLL_SRC.index("seeding pending stub")
    assert i_guard < i_seed


def test_hard_retry_brief_falls_back_to_disk():
    # original_inputs carries no 'brief' on the full-pipeline path — the retry
    # pasted a 0-char brief ("Paste verify: 1/0 chars"). Fall back to brief.md.
    assert "brief text recovered from disk" in POLL_SRC
    i = POLL_SRC.index("brief text recovered from disk")
    blk = POLL_SRC[max(0, i - 700):i]
    assert "not _brief_text_hr and _brief_path_hr" in blk


def test_skip_never_clobbers_a_recorded_done_result():
    i = POLL_SRC.index("Skip on an already-completed agent")
    blk = POLL_SRC[max(0, i - 900):i + 1200]
    assert '_prior_done.get("status") == "done"' in blk
    assert "del pending[_agent_name]" in blk
    # The good result and persisted status stay untouched — no results
    # overwrite, no agent_skipped emit in this branch.
    assert 'results[_agent_name] = {' not in blk.split("Skip on an already-completed agent")[1]


# ── AUDIT FOLD-INS (adversarial workflow, 2026-07-14) ────────────────────────

def test_running_status_cannot_overwrite_complete():
    # ROOT of the retry-then-skip destruction (audit #953-3/#953-5): the retry
    # intake's transient 'running' write must never poison a completed agent's
    # persisted status — that shared map is what two guards read. The guard also
    # protects a terminal "skipped" (org-PR#3 review): a stale Retry on a
    # hands-off HV auto-skip would otherwise re-navigate the walled surface and
    # revert the greyed tile.
    src = inspect.getsource(research._write_agent_terminal_status)
    assert 'if status == "running" and not force:' in src
    assert '_cur in ("complete", "skipped")' in src
    assert "return" in src.split('if status == "running" and not force:')[1][:400]


def test_running_write_refused_over_terminal_status(monkeypatch):
    # Behavioral: a transient "running" write must not poison a terminal
    # "complete" OR "skipped" in the shared _agent_status_by_rid map (the guard
    # returns before recording), while a legitimate "errored"->"running"
    # badge-clear still lands. Stub the Firebase globals so the function gets
    # past its no-Firestore early-return (8315), and neuter the async write.
    monkeypatch.setattr(research, "_firebase_db", object(), raising=False)
    monkeypatch.setattr(research, "_fb_uid", "uid-test", raising=False)
    monkeypatch.setattr(research, "_fb_research_id", "rid-test", raising=False)
    monkeypatch.setattr(research, "_set_research_doc", lambda *a, **k: None, raising=False)
    for terminal in ("complete", "skipped"):
        research._agent_status_by_rid.clear()
        research._record_terminal_status(
            research._agent_status_by_rid, "rid-test", "gemini", terminal)
        research._write_agent_terminal_status("gemini", "running")
        assert research._agent_status_by_rid["rid-test"]["gemini"] == terminal
    # errored -> running is still allowed (the badge-clear the guard was built for)
    research._agent_status_by_rid.clear()
    research._record_terminal_status(
        research._agent_status_by_rid, "rid-test", "gemini", "errored")
    research._write_agent_terminal_status("gemini", "running")
    assert research._agent_status_by_rid["rid-test"]["gemini"] == "running"
    # force=True (the #929 launch-site relaunch reset) MUST override a stale
    # "skipped"/"errored" — else a resumed/re-run agent stays grey (#929 bug 0).
    for terminal in ("skipped", "errored", "complete"):
        research._agent_status_by_rid.clear()
        research._record_terminal_status(
            research._agent_status_by_rid, "rid-test", "gemini", terminal)
        research._write_agent_terminal_status("gemini", "running", force=True)
        assert research._agent_status_by_rid["rid-test"]["gemini"] == "running"
    research._agent_status_by_rid.clear()


def test_hard_retry_guard_catches_inflight_completion():
    # Audit retry-race: a Retry consumed DURING the multi-minute completion
    # window (done-marker sighted, not yet recorded) must still be dropped.
    i = POLL_SRC.index("Hard retry ignored")
    blk = POLL_SRC[max(0, i - 1800):i + 200]
    assert "done_marker_first_at" in blk
    assert "_inflight_done" in blk


def test_skip_elif_branch_has_results_done_defense():
    i = POLL_SRC.index("Skip after leaving poll")
    blk = POLL_SRC[max(0, i - 700):i + 300]
    assert "_left_done" in blk
    assert '_left_results.get("status") == "done"' in blk


def test_scrape_gate_requires_visible_enabled_start():
    # Root conflation (audit): the planning-gate must not force status
    # 'generating' on a hidden/disabled skeleton Start (which fed the false
    # 2D streaming clock + gated off the L1 arbiter for the whole auto-run).
    src = inspect.getsource(research.scrape_progress_gemini)
    i = src.index("Planning-gate")
    blk = src[i:i + 1800]
    assert "offsetParent === null" in blk
    assert "aria-disabled" in blk and "b.disabled" in blk


def test_restart_gemini_uses_hardened_finder():
    # Audit (high): _restart_phase2_agent's Gemini leg must reuse the module
    # finder (not the old <button>-only match) and honor auto-start.
    src = inspect.getsource(research._restart_phase2_agent)
    assert "_GEMINI_CLICK_START_JS" in src
    assert "_gemini_research_started" in src
    assert "_auto_started" in src
    # The old raw text-match click JS must be gone from this helper.
    assert "b.textContent.trim().toLowerCase()" not in src


def test_error_card_stamp_popped_on_user_resolution():
    # Audit #953-8: a user Retry/Skip drops the fail_agent stamp so a much-later
    # completion can't spuriously retract an unrelated live decision.
    src = inspect.getsource(research)  # command intakes are module-level
    # All three intakes (skip, retry-hard, retry-soft) pop the stamp.
    assert src.count("_AGENT_ERROR_CARD_TS.pop") >= 3


def test_no_blocking_await_agent_decision_inside_round_robin():
    # Audit (user-flagged): a per-agent decision must NEVER block the whole
    # round-robin. poll_all_agents_round_robin must contain ZERO
    # `await ...await_agent_decision` — every decision is parked + resolved
    # non-blockingly so the other agents keep polling.
    assert "await _controls.await_agent_decision" not in POLL_SRC
    # The four former blocking sites now PARK instead.
    for kind in ("session_expiry", "extract_empty_pw",
                 "claude_2artifact_hf", "extract_empty_cua"):
        assert f'"kind": "{kind}"' in POLL_SRC, f"{kind} site must park, not block"


def test_parked_decision_resolver_is_nonblocking():
    # The resolver at the leg top checks the decision ONCE per tick (no await
    # on a decision), and continues (releases the loop) while still pending.
    assert "poll_agent_decision" in POLL_SRC
    assert 'p.get("awaiting_decision")' in POLL_SRC
    i = POLL_SRC.index('_parked = p.get("awaiting_decision")')
    blk = POLL_SRC[i:i + 3400]
    assert 'if _pk_dec == "pending" and not _pk_expired:' in blk
    assert "continue" in blk  # still-waiting path releases the loop


def test_poll_agent_decision_is_nonblocking_single_check():
    src = inspect.getsource(research.PipelineControls.poll_agent_decision)
    # No actual await statement (the docstring may NAME await_agent_decision);
    # it must also not be a coroutine (def, not async def).
    code = "".join(l for l in src.splitlines(keepends=True)
                   if not l.lstrip().startswith(('"', "#")))
    assert "await " not in code, "poll_agent_decision must not await (non-blocking)"
    assert "async def poll_agent_decision" not in src
    assert 'return "pending"' in src
    assert "consume_retry_agent_hard" in src


def test_resolver_preserves_hard_fail_autoskip_after_two_timeouts():
    src = inspect.getsource(research._resolve_parked_agent_decision)
    assert 'kind == "claude_2artifact_hf"' in src
    assert 'p["hf_timeouts"]' in src
    assert '>= 2' in src
    assert 'reason="auto_skip_unanswered_timeout"' in src
    # #955: finalize (results + agent_skipped + notice + close) rides the ONE
    # _finalize_agent_autoskip helper — pin the routing, not the inline copy
    # (a bare _close_skipped_agent_tab match here used to hit the separate
    # empty-accept path, a different site).
    assert "_finalize_agent_autoskip(" in src


def test_resolver_empty_cua_timeout_accepts_empty():
    # Parity with the pre-#953 fall-through: an unanswered empty-CUA card
    # finalizes the agent as 'empty', it doesn't poll forever.
    src = inspect.getsource(research._resolve_parked_agent_decision)
    i = src.index('kind == "extract_empty_cua"')
    blk = src[i:i + 2800]
    assert '"status": "empty"' in blk
    assert 'final_status="empty"' in blk
    assert "del pending[name]" in blk


def test_poll_agent_decision_ignores_global_continue_anyway():
    # Review fold-in #1: parking allows MULTIPLE simultaneous parks, so a stray
    # GLOBAL continue_anyway must NOT be consumable here (a parked agent would
    # steal it and wrongly finalize). No park card offers "Continue anyway".
    src = inspect.getsource(research.PipelineControls.poll_agent_decision)
    assert "consume_continue_anyway" not in src.replace("do NOT consume", "")


def test_skip_supersedes_coqueued_retry_race_safe():
    # Review fold-in #2 (race-safe rev): a Skip supersedes a co-queued Retry so
    # a skipped parked agent isn't resurrected. This must NOT be done inside
    # consume_skip_marker (that races the command thread's deferred
    # request_retry_agent_hard and could drop a legit pre-failed retry) — it is
    # done at the loop-thread hard-retry guard, which drops a retry when the
    # agent already has a terminal SKIP outcome.
    csm = inspect.getsource(research.PipelineControls.consume_skip_marker)
    assert "retry_agents_hard.discard" not in csm, (
        "must not drain retry markers in consume_skip_marker — cross-thread race"
    )
    i = POLL_SRC.index("Hard retry ignored")
    blk = POLL_SRC[max(0, i - 700):i + 200]
    assert "_terminal_skip" in blk
    assert 'in ("skipped_by_user", "auto_skipped")' in blk
    assert '_persisted_st == "skipped"' in blk


def test_empty_cua_timeout_retracts_card_and_closes_tab():
    # Review fold-in #3/#4: accept-empty must retract its own card + close the
    # tab + null the page handle (not leave a red tile + leaked live tab).
    src = inspect.getsource(research._resolve_parked_agent_decision)
    i = src.index('kind == "extract_empty_cua"')
    blk = src[i:i + 2800]
    assert "agent_skipped" in blk and "accept_empty_unanswered_timeout" in blk
    assert "_close_skipped_agent_tab" in blk
    assert '"page": None' in blk


def test_parked_hard_cap_still_bites():
    # Review fold-in #5: the 90-min per-agent ceiling must fire even while
    # parked (a re-parking kind must not ride past it).
    i = POLL_SRC.index('_parked = p.get("awaiting_decision")')
    blk = POLL_SRC[i:i + 2000]
    assert "PER_AGENT_HARD_CAP_SEC" in blk
    assert "auto_skip_hard_cap" in blk


def test_resolver_salvage_threads_verbose():
    # Review fold-in #6: the Claude auto-skip salvage extraction must use the
    # real verbose flag, not a hard-coded False.
    src = inspect.getsource(research._resolve_parked_agent_decision)
    assert "verbose=False) -> str" in src or "verbose=False)" in src  # the param default
    # The salvage call uses verbose=verbose, not a literal.
    i = src.index("Auto-skip salvage extract failed")
    pre = src[i - 400:i]
    assert "verbose=verbose" in pre


def test_hard_retry_consumer_skips_parked_agents():
    # Critical interaction (audit): the FE Retry button restarts the agent
    # (#955: a mode-less retry_agent, which the dispatcher routes to the restart
    # via request_retry_agent_hard). The loop-top restart consumer must NOT drain
    # a PARKED agent's marker (that would do a full setup restart instead of the
    # resolver's reload/re-extract/nudge) — it skips parked agents WITHOUT
    # consuming.
    i = POLL_SRC.index('for _agent_key in ("chatgpt", "gemini", "claude"):')
    blk = POLL_SRC[i:i + 1500]
    assert '.get("awaiting_decision")' in blk
    # The park check must precede the consume so the marker survives.
    i_park = blk.index('awaiting_decision')
    i_consume = blk.index("consume_retry_agent_hard")
    assert i_park < i_consume


def test_session_expiry_resolver_reloads_on_retry():
    src = inspect.getsource(research._resolve_parked_agent_decision)
    i = src.index('kind == "session_expiry"')
    blk = src[i:i + 900]
    assert "_gemini_mounted" in blk  # never reload a mounted Gemini conversation
    assert ".reload(" in blk


def test_clobber_guard_tab_close_preserves_done_status():
    i = POLL_SRC.index("Skip on an already-completed agent")
    blk = POLL_SRC[i:i + 900]
    assert 'final_status="done"' in blk
    # And the helper accepts the param.
    sig = inspect.getsource(research._close_skipped_agent_tab)
    assert 'final_status: str = "skipped"' in sig
    assert "final_status=final_status" in sig
