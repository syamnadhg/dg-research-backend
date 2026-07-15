"""#705 — fail_agent Decision card is [Retry] [Skip] only (no [Wait]).

The locked alert spec excludes Poke/Wait. The [Wait] button (include_wait /
wait_longer_agent) was removed from fail_agent; the no-growth stall site already
gets a 20-min silent grace before it fires, so a budget-extension affordance is
redundant. Source-inspection guard pins the action set.
"""
import inspect

import research


def test_fail_agent_has_no_wait_button():
    # #955: the action dicts moved into the intent catalog's expander —
    # the no-Wait spec must hold across BOTH fail_agent and the expander.
    src = inspect.getsource(research.fail_agent)
    exp = inspect.getsource(research._alert_actions_for)
    for s in (src, exp):
        assert '"label": "Wait"' not in s and "wait_longer_agent" not in s, (
            "fail_agent must NOT offer a [Wait] button (#705 spec = [Retry] [Skip] only)."
        )
    assert "include_wait" not in src, (
        "the include_wait param was removed — its only caller (the no-growth "
        "stall) no longer passes it (#705)."
    )
    # The two intended actions are still authored (now via the catalog).
    assert "_alert_actions_for" in src, "fail_agent must route through the catalog"
    assert '"action": "retry_agent"' in exp, "Retry action missing from the expander"
    assert '"action": "skip_agent"' in exp, "Skip action missing from the expander"


def test_fail_agent_signature_dropped_include_wait():
    sig = inspect.signature(research.fail_agent)
    assert "include_wait" not in sig.parameters, (
        "fail_agent signature must no longer accept include_wait (#705)."
    )
