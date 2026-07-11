"""#751 — five P1/P2 E2E bug fixes from the 2026-06-02 ~04:51 run.

Grounded in backend.log/backend-2.log + the 5:30 AM FE screenshot. Source-
inspection guards (the hot code lives in big async functions / JS-in-Python
evaluate strings that aren't unit-callable without a live browser, matching the
existing test convention in this suite).

A) ChatGPT Pro/Free tier detector false-reads Pro as "Free" → pro_required false
   alarm (it lacked the DOM cross-check Gemini got in #743). Fix: new
   _chatgpt_dom_tier + the vision-FREE cross-check now covers chatgpt too,
   failing OPEN unless a real upsell CTA is present.
B) P1 brief falsely "no brief generated" though it completed: stuck browser →
   Tier-2 DOM scrape flat/empty → false failure. Fix: run_phase1 reloads the
   page once + re-extracts before the short/empty guard.
C) P2 Claude Research-tool Step 3B DOM selector missed role=menuitemcheckbox →
   failed every run. Fix: broadened roles + normalized text + row-with-switch
   fallback.
D) P2 Claude model picker left open after Max/Thinking (single Escape closed
   only the inner Effort submenu). Fix: double Escape.
E) Retry on a pipeline_error didn't retract the durable pendingDecision (emit
   path phase_restart wasn't in the _clear_pending_decision whitelist). Fix: add
   phase_restart.
"""
import inspect

import research


# ── A: ChatGPT DOM tier parity ────────────────────────────────────────────────
def test_A_chatgpt_dom_tier_helper_exists():
    assert hasattr(research, "_chatgpt_dom_tier"), (
        "_chatgpt_dom_tier helper missing — ChatGPT never got the Gemini #743 "
        "DOM tier cross-check"
    )


def test_A_chatgpt_dom_tier_biases_to_pro_failing_open():
    src = inspect.getsource(research._chatgpt_dom_tier)
    # Pro marker (chip or model-trigger) wins; only an upsell CTA → free; else unsure.
    assert 'return "pro"' in src and 'return "free"' in src and 'return "unsure"' in src
    assert "proMark" in src and "modelPro" in src and "upsell" in src
    # Must never raise — exception path returns unsure (fail-open).
    assert 'return "unsure"' in src.split("except")[-1]


def test_A_cua_pro_tier_call_crosschecks_chatgpt_on_free():
    src = inspect.getsource(research._cua_pro_tier_call)
    # The vision-FREE cross-check now covers chatgpt (not just gemini).
    assert 'pname in ("gemini", "chatgpt")' in src, (
        "the FREE cross-check still only fires for gemini — chatgpt will keep "
        "false-alarming pro_required"
    )
    assert "_chatgpt_dom_tier(page)" in src


# ── B: P1 brief short-extract recovery ────────────────────────────────────────
# SUPERSEDED by #752 — see tests/test_e2e_p1p2_fixes_752.py. The #751 reload was
# the WRONG remedy (a reload COLLAPSES the canvas, making the extract shorter):
# the brief lives in an un-opened ChatGPT canvas, so the recovery must OPEN the
# canvas (re-extract WITH browser+cua so Tier-1 runs), not reload. This test now
# guards the corrected contract so the harmful reload can't creep back.
def test_B_run_phase1_recovers_short_brief_without_reload():
    # #751-B's reload was the wrong remedy and is gone; #752's canvas re-extract
    # is also gone (#754 — P1 has no canvas). The durable invariant guarded here:
    # run_phase1 NEVER reloads the page to recover a brief (a reload collapses
    # the ChatGPT view and made the extract worse). The current extraction-fail
    # recovery (HTML→MD auto-retry) is covered by test_p1_extract_retry_754.py.
    src = inspect.getsource(research.run_phase1)
    assert "browser.page.reload" not in src, (
        "run_phase1 reloads to recover a brief again — that collapses the "
        "ChatGPT view and regressed extraction (removed in #752/#754)"
    )


# ── C: Claude Research-tool selector broadened ────────────────────────────────
def test_C_research_selector_includes_menuitemcheckbox_and_fallback():
    src = inspect.getsource(research.setup_claude_dr)
    assert 'role="menuitemcheckbox"' in src, (
        "Step 3B selector still omits menuitemcheckbox — the role claude.ai now "
        "uses for the Research toggle"
    )
    # The row-CONTAINS-a-switch fallback (mirrors the Step 1D Thinking pattern).
    assert "row.querySelector(" in src or "el.querySelector(" in src


# ── D: model picker double-Escape ─────────────────────────────────────────────
def test_D_model_popover_double_escape():
    src = inspect.getsource(research.setup_claude_dr)
    # The "Dismiss the model popover" block must press Escape twice (close the
    # inner Effort submenu, then the parent model popover).
    anchor = "Dismiss the model popover so the tools menu"
    assert anchor in src
    # Window past the (long) explanatory comment to the actual try-block.
    tail = src.split(anchor, 1)[1][:1100]
    assert tail.count('press("Escape")') >= 2, (
        "model-popover dismissal still presses Escape once — the popover stays "
        "open over the composer (the #745 regression)"
    )


# ── E: phase_restart clears the pending decision ──────────────────────────────
def test_E_emit_event_clears_pending_decision_on_phase_restart():
    src = inspect.getsource(research.emit_event)
    # The _clear_pending_decision whitelist must include phase_restart so a
    # Retry-after-error retracts the durable snag card. (2026-07-11: the seam
    # call is agent-scoped for agent_skipped; phase_restart rides the
    # unconditional None arm — same behavior.)
    assert "phase_restart" in src and "_clear_pending_decision(" in src
    # Be specific: phase_restart appears in the same tuple as the other resolve
    # signals (guard against an unrelated phase_restart mention).
    assert 'phase_skipped", "phase_restart"' in src or '"phase_restart"' in (
        src.split("_clear_pending_decision(")[0].split("event_type in")[-1]
    )
