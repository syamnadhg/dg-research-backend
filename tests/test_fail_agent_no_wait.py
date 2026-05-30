"""#705 — fail_agent Decision card is [Retry] [Skip] only (no [Wait]).

The locked alert spec excludes Poke/Wait. The [Wait] button (include_wait /
wait_longer_agent) was removed from fail_agent; the no-growth stall site already
gets a 20-min silent grace before it fires, so a budget-extension affordance is
redundant. Source-inspection guard pins the action set.
"""
import inspect

import research


def test_fail_agent_has_no_wait_button():
    src = inspect.getsource(research.fail_agent)
    assert '"label": "Wait"' not in src and "wait_longer_agent" not in src, (
        "fail_agent must NOT offer a [Wait] button (#705 spec = [Retry] [Skip] only)."
    )
    assert "include_wait" not in src, (
        "the include_wait param was removed — its only caller (the no-growth "
        "stall) no longer passes it (#705)."
    )
    # The two intended actions are still present.
    assert '"action": "retry_agent"' in src, "Retry action missing from fail_agent"
    assert '"action": "skip_agent"' in src, "Skip action missing from fail_agent"


def test_fail_agent_signature_dropped_include_wait():
    sig = inspect.signature(research.fail_agent)
    assert "include_wait" not in sig.parameters, (
        "fail_agent signature must no longer accept include_wait (#705)."
    )
