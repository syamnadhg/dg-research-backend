"""Stop paying a dead vendor's timeout once per narration tick.

On the 6 August run every narration attempt to the primary read-timed-out and
narration carried on via the fallback — nothing was lost, so nothing looked
broken. What it cost: nothing remembered the failure, so each tick spent the
primary's whole share of the shared HTTP budget again before handing over. The
cadence in phases 1 and 2 is SIX seconds.

⚠ Two corrections this suite encodes, because both were stated wrongly first:

* "Four of four attempts failed" was four LOGGED lines. The downgrade warning is
  logged once per narrator loop, so the visible count is the number of loops, not
  the number of attempts. The real figure is on the order of a hundred per phase
  and is not recoverable from the log at all — which is itself why the trip line
  is logged outside that once-per-loop suppression.
* The 42 "phase budget 0 exhausted" lines are NOT this. They come from the
  retired VISION narrator, whose budget is deliberately zero, and they were being
  emitted on every call because the log-once guard compares a counter that is
  never incremented on that path. Unrelated fault, separate fix, tested below.
"""
import logging

import pytest

import research


# ── The breaker's decision, called directly ─────────────────────────────────

def test_a_fresh_holder_uses_the_primary():
    assert research._narrator_primary_should_skip(
        {"gemini_consecutive_fail": 0, "gemini_tripped": False}) is False


def test_no_holder_at_all_uses_the_primary():
    """`err_holder=None` is a documented caller mode (the one-shot upgrade path).
    It must not accidentally read as tripped."""
    assert research._narrator_primary_should_skip(None) is False


def test_a_tripped_holder_skips_the_primary():
    assert research._narrator_primary_should_skip({"gemini_tripped": True}) is True


def test_one_failure_does_not_trip():
    """A single blip must not cost the phase its preferred vendor."""
    h = {}
    tripped, detail = research._narrator_note_primary_failure(
        h, elapsed_s=10.0, exc_name="ReadTimeout")
    assert tripped is False
    assert research._narrator_primary_should_skip(h) is False
    assert "consecutive=1" in detail


def test_the_second_consecutive_failure_trips():
    h = {}
    research._narrator_note_primary_failure(h, elapsed_s=10.0, exc_name="ReadTimeout")
    tripped, detail = research._narrator_note_primary_failure(
        h, elapsed_s=10.0, exc_name="ReadTimeout")
    assert tripped is True
    assert research._narrator_primary_should_skip(h) is True
    assert "consecutive=2" in detail


def test_the_trip_is_reported_once_not_on_every_later_failure():
    """Otherwise the new line becomes the per-tick spam it replaced."""
    h = {}
    for _ in range(2):
        research._narrator_note_primary_failure(h, elapsed_s=1.0, exc_name="ReadTimeout")
    again, _ = research._narrator_note_primary_failure(
        h, elapsed_s=1.0, exc_name="ReadTimeout")
    assert again is False
    assert research._narrator_primary_should_skip(h) is True


def test_a_success_clears_the_consecutive_count():
    """Two failures minutes and many successes apart are not consecutive."""
    h = {}
    research._narrator_note_primary_failure(h, elapsed_s=1.0, exc_name="ReadTimeout")
    research._narrator_note_primary_success(h)
    tripped, _ = research._narrator_note_primary_failure(
        h, elapsed_s=1.0, exc_name="ReadTimeout")
    assert tripped is False, "an isolated failure accumulated across a success"
    assert research._narrator_primary_should_skip(h) is False


def test_a_success_does_not_un_trip():
    """Once written off, off for the loop. Re-arming inside the loop would bring
    back the retry cost this exists to remove; the phase boundary is the retry."""
    h = {}
    for _ in range(2):
        research._narrator_note_primary_failure(h, elapsed_s=1.0, exc_name="ReadTimeout")
    research._narrator_note_primary_success(h)
    assert research._narrator_primary_should_skip(h) is True


def test_the_detail_names_the_failure_kind_and_what_it_cost():
    """`ReadTimeout` vs `ConnectTimeout` is the whole diagnosis — accepted and
    never answered, versus never connected — and the elapsed time is what shows
    the budget was spent rather than a fast refusal."""
    _, detail = research._narrator_note_primary_failure(
        {}, elapsed_s=9.7, exc_name="ReadTimeout")
    assert "ReadTimeout" in detail
    assert "9.7s" in detail


def test_noting_a_failure_without_a_holder_is_harmless():
    tripped, detail = research._narrator_note_primary_failure(
        None, elapsed_s=1.0, exc_name="ReadTimeout")
    assert tripped is False and detail == ""
    research._narrator_note_primary_success(None)      # must not raise


def test_the_trip_threshold_is_above_one():
    """Pinning the intent, not the number: at 1 a single blip writes the vendor
    off for the whole phase."""
    assert research.NARRATOR_PRIMARY_TRIP_AFTER >= 2


# ── The wiring: the request path must consult and feed the breaker ───────────

def test_the_request_path_consults_the_breaker():
    """A breaker nothing asks about is decoration. Asserted on the guard's own
    condition, in code with comments stripped."""
    from conftest import code_only
    src = code_only(research._call_text_narrator)
    assert "_narrator_primary_should_skip(err_holder)" in src
    assert "_narrator_note_primary_failure(" in src
    assert "_narrator_note_primary_success(err_holder)" in src


def test_the_holder_the_loop_creates_carries_the_breaker_keys():
    """The helpers tolerate missing keys, so a holder without them would work and
    hide the contract. The loop states it."""
    from conftest import code_only
    src = code_only(research._narrator_loop)
    assert "gemini_consecutive_fail" in src
    assert "gemini_tripped" in src


def test_the_downgrade_rearm_cannot_clear_the_trip():
    """The re-arm is gated on the primary having ANSWERED. A tripped primary is
    never called, so it can never answer — if that gate were dropped, the trip
    would be wiped on the next tick and the retries would resume."""
    from conftest import code_only
    src = code_only(research._narrator_loop)
    assert 'get("last_vendor") == "gemini"' in src
    assert 'gemini_tripped"] = False' not in src


# ── The unrelated fault the 42 lines actually came from ─────────────────────

def test_a_retired_vision_narrator_is_silent_not_alarming(monkeypatch, caplog):
    """Budget zero means switched off. It logged an exhaustion WARNING on every
    call for a feature nobody enabled, and the log-once guard could not suppress
    it because the counter it compares is never incremented on that path.

    ⚠⚠ Two drafts of this test were DECORATIVE and both passed against the bug:

    1. The first reproduced the guard inline in the test, which says nothing about
       the shipped branch.
    2. The second called the real entry point but got no further than its FIRST
       gate — an API-key check — so it never reached the budget logic at all.
       "No warning was logged" was true because nothing ran. Caught only by
       checking that the mutant which re-breaks this actually fails it.

    So: supply a key to get past that gate, and assert `skipped_budget` moved,
    which is positive evidence that execution reached the branch under test. A
    silence assertion is worthless without proof of arrival.

    `page=None` is safe because the budget check returns before anything touches
    the page; were that order ever reversed, this raises AttributeError, which is
    the correct failure.
    """
    import asyncio

    import narrate
    assert narrate.PHASE_BUDGET == 0, (
        "this test describes the retired-by-default state; "
        f"budget is {narrate.PHASE_BUDGET}")
    monkeypatch.setenv("GEMINI_API_KEY", "probe-key-not-used-for-a-request")
    monkeypatch.setattr(narrate._M, "skipped_budget", 0, raising=False)
    with caplog.at_level(logging.WARNING, logger=narrate.logger.name):
        for _ in range(5):
            narrate._M.last_call_ts = 0.0       # defeat the cooldown gate
            narrate._M.calls_this_phase = 0
            got = asyncio.run(narrate.narrate_panel(None, agent="chatgpt", phase=2))
            assert got is None
    assert narrate._M.skipped_budget == 5, (
        f"the budget branch was never reached (skipped_budget="
        f"{narrate._M.skipped_budget}) — this test proves nothing")
    assert "exhausted" not in caplog.text, caplog.text


def test_the_disabled_branch_precedes_the_exhaustion_branch():
    """Order is the fix. With the exhaustion check first, a zero budget still
    takes the warning path."""
    from conftest import code_only
    import narrate
    src = code_only(narrate.maybe_narrate) if hasattr(narrate, "maybe_narrate") \
        else code_only(open(narrate.__file__, encoding="utf-8").read())
    disabled_at = src.find("PHASE_BUDGET <= 0")
    exhausted_at = src.find("phase budget %d exhausted")
    assert disabled_at != -1, "the disabled branch is gone"
    assert exhausted_at != -1
    assert disabled_at < exhausted_at


def test_a_real_budget_still_warns_when_it_runs_out():
    """The exhaustion warning must survive for anyone who enables the feature."""
    from conftest import code_only
    import narrate
    src = code_only(open(narrate.__file__, encoding="utf-8").read())
    assert "phase budget %d exhausted" in src
