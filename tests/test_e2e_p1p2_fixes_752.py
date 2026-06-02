"""#752 — two P1/P2 ChatGPT E2E bug fixes from the 2026-06-02 ~05:05 / 06:35 run.

Grounded in backend.log (05:05:28, 06:31:01) + backend-2.log (06:35:24→06:37:08).
Source-inspection guards (the hot code lives in big async browser-driving
functions that aren't unit-callable without a live browser/CUA, matching the
existing convention in this suite — see test_e2e_p1p2_fixes_751.py).

ISSUE 1 (P1 canvas extraction) — the ChatGPT brief renders inside a canvas /
artifact card that did NOT auto-open. P1 calls extract_chatgpt_response WITHOUT
browser/cua_client, so only the Tier-2 DOM HTML→MD scrape runs (Tier 1 — the CUA
flow that physically OPENS the canvas and Exports to Markdown — and Tier 3 are
gated off). The closed canvas yields only the short inline preamble (294/474
chars) → "" → false "no brief generated". The #751 reload made it WORSE (a
reload collapses the canvas: 143 < 294 chars). FIX: when the DOM-only extract is
short, re-extract WITH browser+cua so the Tier-1 canvas-open ladder runs.

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


# ── ISSUE 1: P1 canvas-open re-extract (supersedes the #751 reload) ───────────
def test_1_phase1_reextracts_with_cua_canvas_ladder_on_short_brief():
    src = inspect.getsource(research.run_phase1)
    # Recovery is gated to a short DOM-only extract AND an available CUA client.
    assert "brief_len < 500 and cua_client is not None" in src, (
        "short-brief CUA re-extract guard missing/changed"
    )
    # The re-extract must pass browser+cua so Tier-1 (open canvas → Export MD)
    # actually runs — that is the whole point of the fix.
    assert "extract_chatgpt_response(" in src
    assert "browser=browser" in src and "cua_client=cua_client" in src, (
        "the short-brief re-extract no longer passes browser+cua — Tier-1 "
        "canvas-open won't run and the closed-canvas brief stays unreadable"
    )


def test_1_phase1_reextract_disables_whole_page_hijack():
    # Adversarial-review blocker (r4-2): the P1 re-extract MUST pass
    # allow_cua_hijack=False so Tier-3 (whole-page Ctrl+A copy) stays off — at
    # P1 there's no report artifact, so the hijack would capture the chat thread
    # and the length-only guard would let it poison the brief sent to P2.
    src = inspect.getsource(research.run_phase1)
    assert "allow_cua_hijack=False" in src, (
        "P1 re-extract no longer disables Tier-3 — a whole-page hijack can "
        "poison the brief"
    )


def test_1_extractor_tier3_gated_on_allow_cua_hijack():
    # The Tier-3 block must honour the allow_cua_hijack flag; default True keeps
    # P2 behaviour unchanged.
    sig = inspect.signature(research.extract_chatgpt_response)
    assert "allow_cua_hijack" in sig.parameters, "extractor lost the kill-switch param"
    assert sig.parameters["allow_cua_hijack"].default is True, (
        "allow_cua_hijack default must stay True so the many P2 callers are "
        "unaffected"
    )
    src = inspect.getsource(research.extract_chatgpt_response)
    assert "if browser and cua_client and allow_cua_hijack:" in src, (
        "Tier-3 (clipboard hijack) is no longer gated on allow_cua_hijack"
    )


def test_1_phase1_no_longer_reloads_the_page():
    # A reload collapses the canvas (made the extract shorter); it must be gone.
    src = inspect.getsource(research.run_phase1)
    assert "browser.page.reload" not in src, (
        "run_phase1 reloads again — that collapses the ChatGPT canvas and "
        "regresses #752"
    )


def test_1_phase1_reextract_only_replaces_when_strictly_longer():
    # Guard: a still-empty/wrong re-extract must NOT overwrite the original
    # (no regression vs. the genuinely-short/absent case).
    src = inspect.getsource(research.run_phase1)
    assert "_re_len > brief_len" in src
    # And the whole recovery is wrapped so a CUA failure is non-fatal.
    block = src.split("brief_len < 500 and cua_client is not None", 1)[1][:1400]
    assert "try:" in block and "except Exception" in block, (
        "the CUA re-extract isn't exception-guarded — a CUA error would crash P1"
    )


def test_1_extractor_tier1_opens_canvas_only_with_browser_and_cua():
    # The mechanism the fix relies on: Tier-1 (canvas-open CUA download) is
    # gated behind `if browser and cua_client`. Passing them re-enables it.
    src = inspect.getsource(research.extract_chatgpt_response)
    assert "if browser and cua_client:" in src
    assert "canvas may not have opened" in src  # the exact false-fail log we cure


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
