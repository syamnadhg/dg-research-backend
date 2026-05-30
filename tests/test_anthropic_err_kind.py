"""#703 — Anthropic error classification (`_anthropic_err_kind`).

The 2026-05-29 fix routes Anthropic API/SDK errors so a 429 rate-limit (and
401/cap/529) surfaces the paused 'load or switch your key, then Retry' card.
Previously a 429 fell through to a False ('not logged in') verdict during
Phase-0 CUA vision verification — the run showed a phantom login/key alert
that self-healed when the limit cleared (the appear-then-vanish bug).

These tests pin the classifier so a future tweak can't silently drop 429 out
of the "raise a key card" set again, and so the transient classes (403/5xx)
stay in the silent-retry lane.
"""
import pytest

import research


# The two CUA vision call sites raise CuaUnavailableError (→ paused Retry card)
# for exactly these kinds; everything else falls through to the silent lane.
RAISE_KINDS = ("rate_limit", "key", "overload")


@pytest.mark.parametrize("err", [
    "Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error'}}",
    "anthropic.RateLimitError: rate_limit_error",
    "Too Many Requests",
    "rate limit exceeded",
])
def test_rate_limit(err):
    assert research._anthropic_err_kind(err) == "rate_limit"


@pytest.mark.parametrize("err", [
    "Error code: 401 - {'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}}",
    "401 Unauthorized",
    "Workspace API usage limits exceeded",
    "Error code: 400 - usage limit reached for this workspace",
])
def test_key(err):
    assert research._anthropic_err_kind(err) == "key"


@pytest.mark.parametrize("err", [
    "Error code: 529 - overloaded_error",
    "Overloaded",
])
def test_overload(err):
    assert research._anthropic_err_kind(err) == "overload"


@pytest.mark.parametrize("err", [
    "Error code: 403 - forbidden",
    "500 Internal Server Error",
    "502 Bad Gateway",
    "503 Service Unavailable",
    "504 Gateway Timeout",
    "Read timed out",
    "Connection aborted",
])
def test_transient(err):
    assert research._anthropic_err_kind(err) == "transient"


def test_other():
    assert research._anthropic_err_kind("some unrelated parsing error") == "other"


def test_429_is_in_raise_set_regression():
    """The bug: a 429 fell through and did NOT raise the key card. Guard it."""
    assert research._anthropic_err_kind("Error code: 429 rate_limit_error") in RAISE_KINDS


def test_rate_limit_wins_over_overloaded_substring():
    """A 429 message that also mentions 'overloaded' must still be rate_limit
    (429 is checked first), not get bucketed as transient overload."""
    assert research._anthropic_err_kind("429 ... upstream also reported overloaded") == "rate_limit"


def test_transient_stays_silent():
    """403 / 5xx must NOT raise the key card — they're Tier-1 silent retries."""
    assert research._anthropic_err_kind("503 Service Unavailable") not in RAISE_KINDS
    assert research._anthropic_err_kind("Error code: 403 - forbidden") not in RAISE_KINDS
