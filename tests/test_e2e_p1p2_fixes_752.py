"""#752 — two P1/P2 ChatGPT E2E bug fixes from the 2026-06-02 ~05:05 / 06:35 run.

Grounded in backend.log (05:05:28, 06:31:01) + backend-2.log (06:35:24→06:37:08).
Source-inspection guards (the hot code lives in big async browser-driving
functions that aren't unit-callable without a live browser/CUA, matching the
existing convention in this suite — see test_e2e_p1p2_fixes_751.py).

ISSUE 1 (P1 canvas extraction) — SUPERSEDED by #754
(tests/test_p1_extract_retry_754.py). The canvas-open re-extract this section
guarded never recovered a brief in practice (the P1 brief is inline
extended-thinking text — no result panel / download button — so there is no
canvas to open; it fired 4× in E2E and recovered 0 briefs). #754 removed it and
the allow_cua_hijack flag, leaving P1 on HTML→MD with an extraction-fail
auto-retry. Those tests were deleted to avoid asserting removed behaviour.

ISSUE 2 (P2 ChatGPT send) — after a brief FILE is attached the send button stays
DISABLED for several seconds while the upload processes. The old code checked the
send selectors ONCE ~1s after typing → found it disabled → "Playwright can't
find Send" → slow non-deterministic CUA fallback + a ~90s decision wait with the
typed brief sitting unsent in the composer ("stuck stale, text in box"). FIX:
poll for an ENABLED send button (~20s) before falling to CUA; the healthy
paste/Gemini case still fires on the first iteration.
"""
import inspect

import research


# ── ISSUE 1: P1 canvas-open re-extract — REMOVED by #754 ──────────────────────
# The canvas-open re-extract + allow_cua_hijack flag were removed (never
# recovered a brief; P1 has no canvas). Guards for the replacement (HTML→MD
# extraction-fail auto-retry) live in tests/test_p1_extract_retry_754.py.
def test_1_canvas_reextract_and_hijack_flag_fully_removed():
    src = inspect.getsource(research.run_phase1)
    assert "allow_cua_hijack" not in src, "P1 still references the removed allow_cua_hijack flag"
    assert "canvas-open ladder" not in src, "P1 still references the removed canvas-open re-extract"
    import inspect as _i
    assert "allow_cua_hijack" not in str(_i.signature(research.extract_chatgpt_response)), (
        "extract_chatgpt_response still carries the vestigial allow_cua_hijack param"
    )


# ── ISSUE 2: P2 send-button enable poll ───────────────────────────────────────
def test_2_send_polls_for_enabled_button():
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    # A bounded poll loop replaces the one-shot selector scan.
    assert "while not sent:" in src, (
        "send no longer polls — a disabled (attachment-processing) send button "
        "will again trigger the premature CUA fallback"
    )
    assert "_send_deadline" in src and "is_enabled()" in src
    # The poll backs off and is bounded (won't spin forever).
    assert "_send_waited" in src
    body = src.split("while not sent:", 1)[1][:900]
    assert "await asyncio.sleep(1.5)" in body, "poll has no inter-attempt sleep"
    assert "_send_waited >= _send_deadline" in body, "poll isn't bounded"


def test_2_healthy_send_still_clicks_first_iteration():
    # Regression guard: when the button is enabled immediately the click fires
    # on the first pass (no behavioural change for Gemini/paste), and the JS +
    # CUA fallbacks are still reachable when the poll exhausts.
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    assert 'log(f"[{label}] Send clicked ✓"' in src
    # The CUA fallback path is preserved AFTER the poll/JS attempts.
    assert "Playwright can't find Send — CUA clicking" in src
    assert "PROMPT_CLICK_SEND" in src


def test_2_send_selectors_unchanged_set():
    # The poll iterates the SAME proven selector set (we only changed WHEN, not
    # WHICH, we click) — guard against an accidental selector drop.
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    for sel in ('data-testid="send-button"', 'aria-label="Send prompt"',
                'aria-label="Send"'):
        assert sel in src, f"send selector {sel!r} dropped from the poll set"
