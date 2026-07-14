"""#755 — Gemini plan-fail auto-regenerate in the [2D] Start-research wait loop.

Observed (4 E2Es, 2026-06-02): Gemini sometimes FAILS to draft the research
plan and shows "I'm sorry, it looks like something went wrong." with a
Regenerate/Retry button instead of "Start research". The old [2D] loop only
polled for a "Start research" button for the full 10 minutes — it never clicked
Regenerate — so the user had to manually hit Retry ~3 times to get the plan and
the "Start research" button. With no manual help the loop dwelled the full
window and then escalated to a needless human-intervention alert.

Fix: inside the [2D] loop, after the "Start research" check (still preferred and
still breaks on success), call the existing _try_inpage_retry_on_research_fail
to auto-click Gemini's Regenerate/Retry — BOUNDED (cap _GEMINI_MAX_PLAN_REGEN=3)
and STOP-aware. The helper only clicks when the page actually shows failure text
AND finds a retry-labeled button in the assistant area, so a healthy "still
drafting" plan is never touched; the 30s loop sleep spaces attempts so each
re-draft can finish. The loop also now honors Stop/Pause (a 10-min wait must).

The icon-only / silent-stall case (failure with NO retry-labeled button, or a
stall with no failure text) still NEEDS a live E2E to pin the exact Regenerate
selector — so instead of blind-clicking an unidentified control (misclick risk)
the loop logs a ONE-TIME read-only dump of the assistant-area buttons after 90s.

These are source-inspection guards (the loop lives inline in the large
run_phase2 coroutine), matching the suite convention.

Run:  pytest tests/test_gemini_plan_regen_755.py -v
"""
import inspect

import research


def _phase2_src():
    return inspect.getsource(research.run_phase2)


def _2d_loop():
    # Scope to the [2D] plan-wait loop: from its init to the CUA recovery.
    # (#776/#755 renamed the boundary comment "CUA fallback" → "CUA recovery";
    # this marker tracks the live comment.)
    src = _phase2_src()
    return src.split("start_clicked = False", 1)[1].split(
        '# CUA recovery for "Start research"', 1)[0]


def test_regen_is_bounded():
    loop = _2d_loop()
    assert "_GEMINI_MAX_PLAN_REGEN = 3" in loop, (
        "the Gemini plan-regen cap is gone or changed — an unbounded auto-retry "
        "could loop on a hard Gemini failure"
    )
    assert "_regen_count < _GEMINI_MAX_PLAN_REGEN" in loop, (
        "the regen is no longer gated on the cap — it can exceed the bound"
    )
    assert "_regen_count += 1" in loop, "the regen counter is never incremented"


def test_regen_wires_the_existing_retry_clicker():
    loop = _2d_loop()
    assert "_try_inpage_retry_on_research_fail(" in loop, (
        "the [2D] loop no longer calls _try_inpage_retry_on_research_fail — the "
        "plan-fail auto-regenerate is not wired in"
    )


def test_loop_is_stop_aware():
    loop = _2d_loop()
    assert "_controls.is_stop()" in loop, (
        "the [2D] plan-wait loop no longer honors Stop — a 10-min wait must be "
        "stop-aware so the user can cancel"
    )
    # And the regen itself must be gated on not-stopped.
    assert "not _controls.is_stop()" in loop, (
        "the regen click is no longer gated on not-stopped"
    )


def test_start_research_click_is_preferred_over_regen():
    # A freshly-appeared "Start research" must be clicked BEFORE we consider a
    # regenerate, so a healthy plan kicks off research immediately.
    # (#953: the finder JS was hoisted to module scope — anchor on the click
    # call site `_click_start_js`, not the predicate's literal text.)
    loop = _2d_loop()
    i_start = loop.find("evaluate(_click_start_js)")
    i_regen = loop.find("_try_inpage_retry_on_research_fail(")
    assert i_start != -1 and i_regen != -1, "loop markers missing"
    assert i_start < i_regen, (
        "the regenerate path now precedes the 'Start research' click — a healthy "
        "plan could get needlessly regenerated instead of started"
    )


def test_regen_has_inter_attempt_cooldown():
    # A slow-but-healthy re-draft must not burn the 3-cap: successive regen
    # attempts are spaced by a cooldown gate.
    loop = _2d_loop()
    assert "_GEMINI_REGEN_COOLDOWN_SEC" in loop, (
        "the inter-regen cooldown constant is gone — 3 regens could fire in ~90s "
        "and exhaust the cap before a slow re-draft finishes"
    )
    assert "_last_regen_at" in loop and "(time.time() - _last_regen_at)" in loop, (
        "the regen gate no longer enforces the cooldown via _last_regen_at"
    )


def test_cap_exhaustion_is_surfaced_once():
    # When auto-regenerate is exhausted with still no plan, emit ONCE so the FE
    # shows a known repeated failure instead of a silent stall.
    loop = _2d_loop()
    assert "_regen_cap_emitted" in loop, (
        "the one-time cap-exhaustion emit was removed — an eventual not-verified "
        "Gemini reads as a silent stall in the FE"
    )


def test_post_loop_skips_cua_and_verify_on_stop():
    # After the loop, a Stop must skip the CUA Start-research fallback AND the
    # ~45s DOM-verify churn (both would just no-op/fail on a stopped run).
    src = _phase2_src()
    post = src.split('# CUA recovery for "Start research"', 1)[1].split(
        "# ── Verify all launched agents", 1)[0]
    assert "not _controls.is_stop()" in post, (
        "the post-loop CUA Start-research fallback no longer skips on Stop"
    )
    assert 'if _controls.is_stop():' in post and "verified_b = False" in post, (
        "the post-loop Gemini verify no longer short-circuits to not-verified on "
        "Stop — a stopped run burns ~45s in DOM-verify retries"
    )


def test_silent_stall_diag_is_read_only_no_blind_click():
    # The stall diagnostic must be capture-only. The ONLY click pathway in the
    # loop is the deterministic 'Start research' finder (#953: hoisted to
    # module scope as _GEMINI_CLICK_START_JS, aliased _click_start_js) — the
    # diag dump and the regen path must not introduce a blind click on an
    # unidentified control.
    loop = _2d_loop()
    assert "_logged_stall_diag" in loop, (
        "the one-time silent-stall diagnostic was removed — we lose the data "
        "needed to pin the icon-only Regenerate selector"
    )
    # No inline b.click() remains in the loop (the vetted click lives in the
    # module-level finder); the loop clicks ONLY via evaluate(_click_start_js).
    assert loop.count("b.click()") == 0, (
        "an inline .click() appeared in the [2D] loop — the silent-stall "
        "path must stay read-only (no blind clicks on unidentified controls)"
    )
    assert loop.count("evaluate(_click_start_js)") >= 1
    # And the module-level finder still carries the single vetted b.click().
    assert research._GEMINI_CLICK_START_JS.count("b.click()") == 1
