"""#951 — four fixes from the 2026-07-13 E2E (Bugs dir screenshots).

1) ChatGPT extraction/completion "stuck scrolling": the DOM completion
   detector's docPanelAffordances required a download AND an expand button,
   but ChatGPT's finished-canvas header is download + SHARE — so the detector
   logged "doc-panel affordances all missing" at the SAME tick the CUA
   screenshot read "download (↓) and share/expand buttons — no stop button",
   and the poller burned 17+ min scroll-checking a document that was DONE.
   Fix: the DOWNLOAD button ALONE (in a large right-anchored panel header,
   no stop button) is the done signal; also drop the r.left>=22%vw right-dock
   floor that excluded the near-full-width canvas layout.

2.1) Gemini "not selecting Extended": _gemini_select_flash_model trusted the
   Extended CLICK (_gem_ext_confirmed=True from a non-empty click return) but
   never verified the mode button and never retried — every recent run logged
   "trigger now reads 'Flash'" (not 'FlashExtended') yet proceeded on Standard
   thinking. Fix: the mode button reading 'Extended' is AUTHORITATIVE; on a
   miss, reopen + re-hover + re-click Extended up to _EXT_TRIES times.

2.5) Auto-skip inconsistency: a setup-failed agent (2A/2B/2C fail_agent → red
   'errored' tile + Retry/Skip card + internal skip marker) was dropped WITHOUT
   being greyed or having its tab closed, while the run proceeded — leaving a
   red tile, an open browser tab, and a lying "Completed in X min" stepper.
   Fix: at the round-robin's natural exit, an auto-skip FINALIZER greys the
   tile (agent_skipped), closes the tab (_close_skipped_agent_tab), and drops
   an informational notice — one shape for every auto-skip, matching a normal
   skip and the Layer-3 stuck auto-skip. Gemini (unlike ChatGPT/Claude) wasn't
   even registered in `agents` on failure, so the finalizer couldn't reach its
   tab — now it is.

Run: pytest tests/test_bugs_951.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


# ── Bug 1: ChatGPT download-icon completion signal ───────────────────────────

def test_doc_panel_fires_on_download_alone_not_download_and_expand():
    src = inspect.getsource(research.detect_completion_chatgpt)
    i = src.index("let docPanelAffordances")
    block = src[i:i + 1600]
    # The download button ALONE flips the signal (no more AND-expand).
    assert "if (hasDl) { docPanelAffordances = true; break; }" in block, (
        "the finished-canvas download button alone must be the done signal — "
        "ChatGPT's header is download + SHARE, so requiring an expand button "
        "missed every finished canvas"
    )
    # The expand/enlarge requirement is gone.
    assert "hasExpand" not in block, (
        "the expand/enlarge requirement was the false-negative: drop it"
    )


def test_doc_panel_geometry_drops_the_right_dock_left_floor():
    src = inspect.getsource(research.detect_completion_chatgpt)
    i = src.index("let docPanelAffordances")
    block = src[i:i + 1600]
    # The near-full-width canvas layout has the document starting just right of
    # the thin icon rail — a r.left >= 22%vw floor excluded exactly that layout.
    assert "r.left < vw * 0.22" not in block, (
        "the right-dock left floor excluded the near-full-width finished canvas"
    )
    # Still anchored to the right edge + tall (specific to a document surface).
    assert "r.right < vw - 40" in block and "r.height < vh * 0.5" in block, (
        "keep the right-edge anchor + min-height so this stays specific to a "
        "finished document panel, not any wide div"
    )


def test_doc_panel_still_gated_on_no_stop_button():
    # done is decided AFTER the stop-button veto — a download button that
    # appears mid-generation (it doesn't, but defensively) can't false-fire.
    src = inspect.getsource(research.detect_completion_chatgpt)
    i_stop = src.index("if has_stop:")
    i_done = src.index("if not has_done_marker:")
    assert i_stop < i_done, "stop-button veto must precede the done-marker check"


# ── Bug 2.1: Gemini Extended thinking must actually stick ────────────────────

def test_extended_verify_is_authoritative_mode_button_not_the_click():
    src = inspect.getsource(research._gemini_select_flash_model)
    # The authoritative signal is the mode button reading 'extended'.
    assert "_mode_shows_extended" in src and '"extended" in (_m or "").lower()' in src, (
        "verification must read the mode button, not trust the click's return"
    )


def test_extended_telemetry_reflects_verified_state_not_the_click():
    # #951 review: the advisory _P2_THINKING_STATE must record the FINAL
    # verified state (_ext_ok), never the seeded-True click return — else a
    # definitive Extended FAILURE is logged as a confirmed success.
    src = inspect.getsource(research._gemini_select_flash_model)
    i_bind = src.index("_gem_ext_confirmed = _ext_ok")
    i_record = src.index('_P2_THINKING_STATE["gemini"] = {"thinking": _gem_ext_confirmed}')
    assert i_bind < i_record, (
        "_gem_ext_confirmed must be re-bound to the authoritative _ext_ok "
        "BEFORE it's recorded into _P2_THINKING_STATE"
    )


def test_extended_retries_until_it_sticks():
    src = inspect.getsource(research._gemini_select_flash_model)
    assert "DG_GEMINI_EXTENDED_TRIES" in src, "the retry count must be env-tunable"
    assert "for _et in range(1, _EXT_TRIES + 1):" in src, (
        "a bounded verify+retry loop must re-pick Extended when the mode button "
        "still doesn't show it"
    )
    # The retry reopens the menu, re-hovers the Flash row (row-nested submenus
    # only render on hover), then re-clicks Extended.
    for anchor in ("_reopen_js", "_hover_flash_row_js", "_click_ext_radio_js"):
        assert anchor in src, f"retry must re-drive the pick via {anchor}"
    # A confirmed stick breaks the loop; exhaustion is logged honestly.
    assert "after retry" in src and "extended-retry-exhausted" in src


def test_extended_miss_is_never_fatal_to_the_agent():
    # DR still runs on Standard thinking — the function must still return True
    # after an Extended miss (DR-placeholder-gated upstream, not thinking-level).
    src = inspect.getsource(research._gemini_select_flash_model)
    i_exhaust = src.index("extended-retry-exhausted")
    tail = src[i_exhaust:]
    assert "NOT Flash Extended" in tail and "return True" in tail, (
        "an Extended miss is logged but must not fail the whole Gemini agent"
    )


# ── Bug 2.5: auto-skip finalization (grey + close tab, consistent) ───────────

def test_failed_gemini_is_registered_in_agents_for_finalization():
    # ChatGPT/Claude are already in `agents` on failure; Gemini wasn't, so the
    # round-robin finalizer couldn't reach its tab handle to close it.
    mod = inspect.getsource(research)
    assert 'agents["Gemini"] = {"page": gemini_page, "verified": False,' in mod, (
        "the FAILED Gemini must be registered in `agents` so the auto-skip "
        "finalizer can close its tab (bug 2.5)"
    )
    assert '"setup_failed": True' in mod


def test_round_robin_finalizes_unresolved_failures_as_clean_skips():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    block = src[src.index("async def _finalize_unresolved_autoskips"):]
    # Respects the user's auto-skip setting (OFF → leave the card up).
    assert "if not _runtime.auto_skip_stuck:" in block
    # Greys the tile (agent_skipped clears the card + persists 'skipped') +
    # closes the tab + drops an informational notice — the Layer-3 shape.
    assert 'emit_event("agent_skipped", phase=2, agent=_fin_key' in block
    assert 'reason="auto_skip_setup_failed"' in block
    assert "await _close_skipped_agent_tab(browser, _fin_agent.get(\"page\")" in block
    assert 'emit_event("pipeline_warning"' in block and "_autoskip" in block


def test_finalizer_runs_at_both_exits_including_empty_pending():
    # #951 review coverage gap: if EVERY enabled agent fails setup with a null
    # page handle, `pending` is empty at entry and the early `return results`
    # would bypass the finalizer — leaving red tiles. The finalizer helper must
    # be awaited at BOTH the empty-pending early return AND the natural exit.
    src = inspect.getsource(research.poll_all_agents_round_robin)
    calls = src.count("await _finalize_unresolved_autoskips()")
    assert calls >= 2, (
        "finalizer must run on the empty-pending early return AND the natural exit"
    )
    # The early-return call sits right at the `if not pending:` guard.
    i_guard = src.index("if not pending:")
    assert "await _finalize_unresolved_autoskips()" in src[i_guard:i_guard + 300]


def test_finalizer_targets_only_unresolved_failures():
    src = inspect.getsource(research.poll_all_agents_round_robin)
    block = src[src.index("Auto-skip finalization"):]
    # Never re-touch a completed ✓ or an existing grey skip.
    assert 'if _fin_persisted in ("complete", "skipped"):' in block
    # Never auto-skip a failed-then-retried-to-completion agent (its persisted
    # 'errored' may not be flipped to 'complete' until phase_complete, AFTER
    # this returns) — the output guard protects it.
    assert "_produced_output" in block and 'bool(_fin_r.get("text"))' in block
    # The actual target: fail_agent's persisted 'errored' or a start-failure
    # status with no output.
    assert '_fin_persisted == "errored"' in block
    assert '_fin_st in ("failed_setup", "not_verified")' in block


def test_finalizer_result_buckets_as_skipped_not_errored():
    # results[name].status = "auto_skipped" (no text) → phase_complete buckets
    # it into skippedAgents, not erroredAgents (no phantom "Read report" link).
    src = inspect.getsource(research.poll_all_agents_round_robin)
    block = src[src.index("Auto-skip finalization"):]
    assert '"status": "auto_skipped", "text": ""' in block


# ── Bug 2.2: adopt the existing Gemini conversation via a REFRESHED sidebar ───

def test_lost_send_recovery_refreshes_only_on_empty_home_then_clicks_sidebar():
    # User-directed: Gemini does NOT restore a conversation from a direct URL
    # (page.goto /app/<id> → empty home). The ONLY reliable adoption is to
    # refresh ONCE on the empty home (freshen the stale Recent list), then CLICK
    # the most-recent owned sidebar entry — never a direct URL nav.
    src = inspect.getsource(research._gemini_adopt_lost_conversation)
    # No direct-CONVERSATION URL nav (Gemini won't restore /app/<id> from a URL
    # — it'd land on the home). The only goto is the back-out to the bare home
    # after a FAILED adoption, which is fine.
    assert "_abs" not in src and "_HREF_OR_CLICK_BY_TITLE_JS" not in src, (
        "never navigate to a conversation by URL — it lands on the empty home"
    )
    assert 'page.goto("https://gemini.google.com/app"' in src, (
        "the only goto is the back-out to the bare home on a failed adoption"
    )
    # ...and there is no goto of a per-conversation href.
    assert "page.goto(_abs" not in src
    # Refresh is gated to the EMPTY HOME (never reload in a conversation).
    assert "await page.reload(" in src, "must refresh to freshen the sidebar"
    i_reload = src.index("await page.reload(")
    guard = src[max(0, i_reload - 300):i_reload]
    assert 'gemini.google.com/app' in guard and "_cur" in guard, (
        "the refresh must be gated on being on the empty home — never in-chat"
    )
    # Adoption is a sidebar CLICK on the real anchor, not a URL nav.
    assert "_CLICK_ENTRY_BY_TITLE_JS" in src and "a.click();" in src
    assert 'a[href*="/app/"]' in src


def test_lost_send_recovery_checks_top_one_or_two_recent_entries():
    src = inspect.getsource(research._gemini_adopt_lost_conversation)
    # Reads the top 1-2 recent entries (a concurrent chat could sit above ours).
    assert "_SIDEBAR_LIST_JS, 2" in src
    assert "_owned = [_t for _t in _titles if _gemini_owns_candidate(_t, pasted_head)]" in src, (
        "collect ALL owned entries among the top two"
    )
    # #951 re-review: must LOOP over the owned candidates (click → body-verify →
    # try next), not commit to the first title-match — a concurrent worker's
    # similar-titled chat above ours would otherwise abandon our slot-#2 chat.
    assert "for _ci, _cand_title in enumerate(_owned):" in src
    # conv→conv clicks are detected by URL CHANGE, not just "/app/" presence.
    assert "_before_u" in src and '_u != _before_u' in src


def test_lost_send_recovery_still_verifies_ownership_before_adopting():
    # The refresh+click rework must NOT weaken the anti-hijack guard: only adopt
    # a conversation that provably holds THIS run's brief, and back out of a
    # completed report (a prior run of the same brief).
    src = inspect.getsource(research._gemini_adopt_lost_conversation)
    assert "_gemini_owns_candidate(_t, pasted_head)" in src           # BEFORE the click
    assert "_conversation_matches(page)" in src                       # AFTER routing
    assert "never routed to a new /app/<id>" in src
    assert "report_present" in src and "trying next" in src
