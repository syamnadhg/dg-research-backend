"""DNS retry state machine tests (DGOPS-7367).

Covers Jason's PR-review test-coverage requirement on the DNS retry
state machine added in DGOPS-7367:
  - Predicate `_is_transient_net_error` (research.py:7485-7492)
  - Constants `_TRANSIENT_NET_ERRORS` + `_DNS_BACKOFF_SECS` (research.py:7467-7482)
  - State machine `_advance_dns_backoff` (research.py:~7495)

The retry block was originally inline in `poll_all_agents_round_robin`
(lines ~14013-14084); refactored to `_advance_dns_backoff` on 2026-05-18
for unit testability. Behavior unchanged — the helper preserves the
same dict mutations and emit_event calls.

Run via:
    pytest tests/test_dns_retry.py -v
"""
import asyncio
import os
import sys
import pytest

# Hack: make research.py importable. The script is at the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Replace asyncio.sleep with a no-op so the 3s post-reload settle
    delay in _advance_dns_backoff doesn't slow every test by 3s."""
    async def _noop(*a, **kw):
        return
    monkeypatch.setattr("asyncio.sleep", _noop)


@pytest.fixture
def silent_log(monkeypatch):
    """Silence module-level log() calls so verbose retry-attempt logs
    don't pollute pytest output."""
    monkeypatch.setattr("research.log", lambda *a, **kw: None)


@pytest.fixture
def capture_emit(monkeypatch):
    """Record emit_event calls so tests can assert on agent_progress
    emissions during backoff windows (watchdog feed)."""
    emitted = []
    def _fake(event_name, **kwargs):
        emitted.append({"event": event_name, **kwargs})
    monkeypatch.setattr("research.emit_event", _fake)
    return emitted


@pytest.fixture
def quiet_normalize(monkeypatch):
    """normalize_agent_key may not handle every agent name cleanly in
    unit-test isolation. Stub to identity so the helper's emit_event
    calls work regardless."""
    monkeypatch.setattr("research.normalize_agent_key", lambda x: x.lower())


class _MockPage:
    """Stand-in for a Playwright Page. Configure `reload` to return a
    value (success) or raise (failure). The real Page.reload is async
    and accepts wait_until / timeout kwargs."""

    def __init__(self, reload_side_effect=None):
        self._side_effect = reload_side_effect

    async def reload(self, wait_until=None, timeout=None):
        if isinstance(self._side_effect, BaseException):
            raise self._side_effect
        return self._side_effect


# ─────────────────────────────────────────────────────────────────────
# Predicate: _is_transient_net_error
# ─────────────────────────────────────────────────────────────────────

class TestIsTransientNetError:
    """The categorization predicate gates retry vs. immediate drop. Both
    directions matter — false negatives (transient miscategorized as
    drop) cost the user a recoverable agent; false positives (durable
    miscategorized as retryable) waste 10.5 min before the drop."""

    @pytest.mark.parametrize("code", [
        "ERR_NAME_NOT_RESOLVED",
        "ERR_CONNECTION_REFUSED",
        "ERR_TIMED_OUT",
        "ERR_NETWORK_CHANGED",
        "ERR_INTERNET_DISCONNECTED",
        "ERR_ADDRESS_UNREACHABLE",
        "ERR_NAME_NOT_RESOLVED.",  # trailing-period variant per recipe
        "ERR_CONNECTION_TIMED_OUT",
        "ERR_CONNECTION_RESET",
    ])
    def test_recognizes_all_transient_categories(self, code):
        from research import _is_transient_net_error
        # Naked code string
        assert _is_transient_net_error(code) is True
        # Wrapped in a typical Chromium error message
        assert _is_transient_net_error(f"net::{code} at https://claude.ai/chats/xyz") is True
        # Wrapped in an exception object
        assert _is_transient_net_error(Exception(f"page.reload failed: net::{code}")) is True

    @pytest.mark.parametrize("code", [
        "ERR_SSL_PROTOCOL_ERROR",
        "ERR_INVALID_RESPONSE",
        "ERR_BLOCKED_BY_CLIENT",
        "ERR_BLOCKED_BY_RESPONSE",
        "ERR_CERT_AUTHORITY_INVALID",
    ])
    def test_rejects_non_transient_errors(self, code):
        from research import _is_transient_net_error
        assert _is_transient_net_error(code) is False
        assert _is_transient_net_error(f"net::{code} at https://claude.ai/") is False

    def test_handles_none_and_empty(self):
        from research import _is_transient_net_error
        assert _is_transient_net_error(None) is False
        assert _is_transient_net_error("") is False


# ─────────────────────────────────────────────────────────────────────
# Constants: _DNS_BACKOFF_SECS
# ─────────────────────────────────────────────────────────────────────

class TestDnsBackoffSchedule:
    """The 30s → 2m → 8m schedule is load-bearing for the recovery
    promise: cumulative window must fit inside Phase 2's typical 90-min
    budget. Hardens against accidental tuning."""

    def test_schedule_is_30s_2m_8m(self):
        from research import _DNS_BACKOFF_SECS
        assert _DNS_BACKOFF_SECS == (30, 120, 480), \
            "DNS backoff schedule changed — update tests AND verify with " \
            "Phase 2 budget (Track A) before merging."

    def test_cumulative_window_under_phase2_budget(self):
        from research import _DNS_BACKOFF_SECS
        # Total recovery window = sum of backoffs ≈ 10.5 min. Must be well
        # under Phase 2's typical budget (~90 min) so retries don't eat
        # the agent's time budget.
        total_seconds = sum(_DNS_BACKOFF_SECS)
        assert total_seconds == 630  # 30 + 120 + 480
        assert total_seconds / 60 < 15, "Recovery window > 15 min eats too much Phase 2 budget"

    def test_schedule_monotonically_increases(self):
        from research import _DNS_BACKOFF_SECS
        for i in range(1, len(_DNS_BACKOFF_SECS)):
            assert _DNS_BACKOFF_SECS[i] > _DNS_BACKOFF_SECS[i - 1]


# ─────────────────────────────────────────────────────────────────────
# State machine: _advance_dns_backoff
# ─────────────────────────────────────────────────────────────────────

class TestAdvanceDnsBackoff:
    """The full state machine — extracted from poll_all_agents_round_robin
    on 2026-05-18 for unit testability. Same behavior as the inline block.

    Tests pass a deterministic `now` value so dns_retry_at + last_cua_check
    assertions are exact."""

    def test_no_op_when_dns_retry_at_unset(self, silent_log, capture_emit, quiet_normalize):
        """If no retry is scheduled, advance returns False (caller proceeds
        with normal scrape, doesn't skip the tick)."""
        from research import _advance_dns_backoff
        p = {"page": _MockPage()}  # no dns_retry_at
        result = asyncio.run(_advance_dns_backoff(p, "Claude", now=1000.0, elapsed=120))
        assert result is False
        # State untouched.
        assert "dns_retry_at" not in p or not p["dns_retry_at"]

    def test_no_op_when_retry_not_yet_due(self, silent_log, capture_emit, quiet_normalize):
        """Retry scheduled but backoff hasn't elapsed → no-op."""
        from research import _advance_dns_backoff
        p = {"page": _MockPage(), "dns_retry_at": 2000.0, "dns_retry_attempts": 1}
        result = asyncio.run(_advance_dns_backoff(p, "Claude", now=1500.0, elapsed=120))
        assert result is False
        assert p["dns_retry_at"] == 2000.0  # untouched

    def test_success_clears_state(self, silent_log, capture_emit, quiet_normalize):
        """Successful reload clears retry state, rejoins the agent in rotation."""
        from research import _advance_dns_backoff
        p = {
            "page": _MockPage(reload_side_effect=None),
            "dns_retry_at": 1000.0,
            "dns_retry_attempts": 1,
            "error_source": "network",
            "dns_last_error": "net::ERR_NAME_NOT_RESOLVED",
        }
        result = asyncio.run(_advance_dns_backoff(p, "Claude", now=1500.0, elapsed=120))
        assert result is True  # caller should `continue`
        assert p["dns_retry_at"] == 0
        assert p["dns_retry_attempts"] == 0
        assert p["error_source"] is None
        assert p["dns_last_error"] == ""
        assert p["claude_refreshed_once"] is True
        assert p["last_cua_check"] == 1500.0  # uses `now` param (deterministic)

    def test_transient_fail_schedules_next_attempt(self, silent_log, capture_emit, quiet_normalize):
        """Reload raises transient error + attempts left → schedule next
        backoff window (attempt 1 → 2, dns_retry_at = now + _DNS_BACKOFF_SECS[1])."""
        from research import _advance_dns_backoff, _DNS_BACKOFF_SECS
        transient_err = Exception("page.reload failed: net::ERR_NAME_NOT_RESOLVED")
        p = {
            "page": _MockPage(reload_side_effect=transient_err),
            "dns_retry_at": 1000.0,
            "dns_retry_attempts": 1,
        }
        result = asyncio.run(_advance_dns_backoff(p, "Claude", now=1500.0, elapsed=120))
        assert result is True
        # Next backoff window = _DNS_BACKOFF_SECS[1] = 120s
        assert p["dns_retry_at"] == 1500.0 + _DNS_BACKOFF_SECS[1]
        assert p["dns_retry_attempts"] == 2
        assert "ERR_NAME_NOT_RESOLVED" in p["dns_last_error"]

    def test_exhaustion_falls_through_to_drop_path(self, silent_log, capture_emit, quiet_normalize):
        """After max attempts, transient failure flips error_source to
        'network_exhausted' so the is_error gate drops the agent next tick."""
        from research import _advance_dns_backoff, _DNS_BACKOFF_SECS
        transient_err = Exception("net::ERR_NAME_NOT_RESOLVED")
        p = {
            "page": _MockPage(reload_side_effect=transient_err),
            "dns_retry_at": 1000.0,
            "dns_retry_attempts": len(_DNS_BACKOFF_SECS),  # already at max (3)
        }
        result = asyncio.run(_advance_dns_backoff(p, "Claude", now=1500.0, elapsed=120))
        assert result is True
        assert p["dns_retry_at"] == 0
        assert p["error_source"] == "network_exhausted"
        assert p["claude_refreshed_once"] is True

    def test_non_transient_error_falls_through_immediately(self, silent_log, capture_emit, quiet_normalize):
        """If reload raises a NON-transient error mid-retry (e.g. SSL),
        flip to network_exhausted so drop path fires."""
        from research import _advance_dns_backoff
        ssl_err = Exception("net::ERR_SSL_PROTOCOL_ERROR")
        p = {
            "page": _MockPage(reload_side_effect=ssl_err),
            "dns_retry_at": 1000.0,
            "dns_retry_attempts": 1,  # attempts left, but non-transient
        }
        result = asyncio.run(_advance_dns_backoff(p, "Claude", now=1500.0, elapsed=120))
        assert result is True
        assert p["dns_retry_at"] == 0
        assert p["error_source"] == "network_exhausted"

    def test_emits_progress_during_backoff_window(self, silent_log, capture_emit, quiet_normalize):
        """During transient-fail retry, agent_progress must emit so the
        FE silence watchdog + BE no-growth watchdog don't false-flag the
        agent as stalled during the long 480s wait."""
        from research import _advance_dns_backoff
        transient_err = Exception("net::ERR_CONNECTION_RESET")
        p = {
            "page": _MockPage(reload_side_effect=transient_err),
            "dns_retry_at": 1000.0,
            "dns_retry_attempts": 1,
        }
        asyncio.run(_advance_dns_backoff(p, "Claude", now=1500.0, elapsed=240))
        progress_emits = [e for e in capture_emit if e["event"] == "agent_progress"]
        assert len(progress_emits) == 1
        assert progress_emits[0].get("phase") == 2
        assert "retrying" in progress_emits[0].get("progress", "").lower()
        # Watchdog feed: must include elapsedSec so the BE no-growth
        # watchdog sees a fresh tick (not just status).
        assert progress_emits[0].get("elapsedSec") == 240

    def test_emits_progress_on_success(self, silent_log, capture_emit, quiet_normalize):
        """On successful reload, agent_progress emits a recovery message
        so the FE chip flips from 'waiting' to 'generating'."""
        from research import _advance_dns_backoff
        p = {
            "page": _MockPage(reload_side_effect=None),
            "dns_retry_at": 1000.0,
            "dns_retry_attempts": 2,
        }
        asyncio.run(_advance_dns_backoff(p, "Claude", now=1500.0, elapsed=300))
        progress_emits = [e for e in capture_emit if e["event"] == "agent_progress"]
        assert len(progress_emits) == 1
        assert "recovered" in progress_emits[0].get("progress", "").lower()
