"""#754 — P1 extraction is HTML→MD only, with an extraction-FAIL auto-retry.

User-directed (2026-06-02): the ChatGPT P1 brief is inline extended-thinking
text — there is NO result panel / download button — so #752's canvas-open
re-extract had nothing to act on (it fired 4× across the 05:05/06:31/09:08/09:10
E2E and recovered a brief ZERO times). It and the allow_cua_hijack flag were
removed. HTML→MD is P1's sole, sufficient extractor.

The replacement handles a DIFFERENT failure than a wedged brief:
  • Brief GENERATION fails (wedge) → poll_until_done raises _BriefStreamStalled
    → the user is alerted to retry the whole run. NOT this code's job.
  • Brief generated fine (completed=True) but the HTML→MD pull came back EMPTY
    (a transient DOM-render / selector miss) → re-pull HTML→MD up to 2×, 3 min
    apart, STOP the instant text appears. Only on a failed pull, never on
    success, never on a wedge — so no false retries.

Source-inspection guards (the loop lives in the big async run_phase1, matching
the suite convention). Run: pytest tests/test_p1_extract_retry_754.py -v
"""
import inspect

import research


def _src():
    return inspect.getsource(research.run_phase1)


def _retry_block():
    # Exactly the extraction-fail retry loop (from the while to the brief-short guard).
    return _src().split("while completed and brief_len < 100", 1)[1].split("Brief-short guard", 1)[0]


def test_extract_retry_gated_on_completed_and_empty():
    # Fires ONLY when the brief generated (completed) AND the pull is empty
    # (<100). A wedge is completed=False → no retry (the stall path owns it);
    # a successful pull is brief_len>=100 → no retry.
    src = _src()
    assert "while completed and brief_len < 100 and _extract_attempt < P1_EXTRACT_RETRY_MAX:" in src, (
        "the extraction-fail retry is no longer gated on completed + empty-pull "
        "+ the attempt cap"
    )


def test_extract_retry_cap_is_two_and_gap_is_three_minutes():
    src = _src()
    assert "P1_EXTRACT_RETRY_MAX = 2" in src, "retry cap changed from 2"
    assert "P1_EXTRACT_RETRY_GAP_SEC = 180" in src, "retry gap changed from 3 min"
    body = _retry_block()
    # 3-min wait, bounded by the gap constant.
    assert "_waited < P1_EXTRACT_RETRY_GAP_SEC" in body, (
        "the inter-attempt wait isn't bounded by the 3-min gap"
    )


def test_extract_retry_wait_is_stop_aware():
    # A Stop during the 3-min gap must be honored promptly (not after the full
    # sleep + another pull) — the wait polls is_stop and aborts (return None).
    body = _retry_block()
    assert "_controls.is_stop()" in body, "the retry wait isn't stop-aware"
    assert "return None" in body, "a Stop during the retry doesn't abort the phase"


def test_extract_retry_repulls_html_md_only_no_cua():
    # The re-pull must be the DOM-only HTML→MD path: extract_chatgpt_response on
    # the page with NO browser/cua (so no Tier-1/Tier-3 — the brief has no canvas).
    body = _retry_block()
    assert "extract_chatgpt_response(browser.page)" in body, (
        "the re-pull isn't the plain HTML→MD path"
    )
    assert "browser=browser" not in body and "cua_client=cua_client" not in body, (
        "the re-pull passes browser/cua — that re-enables the removed canvas tiers"
    )


def test_extract_retry_stops_on_success_and_updates_brief():
    # Recovered text replaces the empty brief; the loop condition (brief_len<100)
    # then exits — so it stops the instant a real brief appears.
    body = _retry_block()
    assert "_retry_len > brief_len" in body and "brief_text = _retry_text" in body, (
        "a successful re-pull no longer replaces the empty brief"
    )


def test_extract_retry_is_exception_guarded():
    # A re-pull error must not crash P1 — it's caught and the loop continues/ends.
    body = _retry_block()
    assert "except Exception" in body, "the re-pull isn't exception-guarded"


def test_canvas_fallback_and_hijack_flag_removed():
    # The stale canvas-open re-extract + allow_cua_hijack flag are gone.
    src = _src()
    assert "allow_cua_hijack" not in src
    assert "canvas-open ladder" not in src and "CUA canvas re-extract" not in src
    assert "browser.page.reload" not in src  # the older reload remedy stays gone
    assert "allow_cua_hijack" not in inspect.getsource(research.extract_chatgpt_response)
