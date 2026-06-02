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


# ── B: P1 brief stuck-DOM reload + re-extract ─────────────────────────────────
def test_B_run_phase1_reloads_and_reextracts_on_short_brief():
    src = inspect.getsource(research.run_phase1)
    assert "brief_len < 500" in src, "reload-recovery guard threshold missing"
    assert "browser.page.reload" in src, (
        "run_phase1 no longer reloads to clear a stuck DOM before failing"
    )
    # Re-extraction happens after the reload and can replace the short brief.
    assert src.count("extract_chatgpt_response(browser.page)") >= 2, (
        "expected an initial extract AND a post-reload re-extract"
    )
    assert "_reextract" in src and "_re_len > brief_len" in src


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
    # Retry-after-error retracts the durable snag card.
    assert "phase_restart" in src and "_clear_pending_decision()" in src
    # Be specific: phase_restart appears in the same tuple as the other resolve
    # signals (guard against an unrelated phase_restart mention).
    assert 'phase_skipped", "phase_restart"' in src or '"phase_restart"' in (
        src.split("_clear_pending_decision()")[0].split("event_type in")[-1]
    )
