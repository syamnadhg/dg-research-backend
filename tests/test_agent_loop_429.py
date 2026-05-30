"""#705 — agent_loop must PAUSE immediately on a 429 (key card), not silent-retry.

A 429 rate-limit is a key/quota problem the user must act on (switch keys).
Silent-retrying it (the old 'Rate limited — waiting 30s; continue') hid a
persistent limit and made the alert appear-then-vanish. 529/overload stay
silent Tier-1.

Source-inspection guard — agent_loop is a large async fn needing a live
client/browser to exercise, so we pin the branch structure instead (mirrors
the style of test_command_stale_gate / test_safety_net_constants).
"""
import inspect

import research


def test_429_pauses_immediately_in_agent_loop():
    src = inspect.getsource(research.agent_loop)
    i429 = src.index('"429" in err')
    i529 = src.index('"529" in err')
    branch = src[i429:i529]  # just the 429 branch body

    assert "fail_agent" in branch and "fail_phase" in branch, (
        "agent_loop's 429 branch must escalate via fail_agent/fail_phase "
        "(immediate Retry-only key card), not silent-retry (#705)."
    )
    assert 'return {"status": "error"' in branch, (
        "agent_loop's 429 branch must return an error after escalating "
        "(end the loop), not `continue`."
    )
    assert "sleep(30)" not in branch and "continue" not in branch, (
        "agent_loop's 429 branch must NOT silent-retry (no 30s sleep / continue) "
        "— that was the appear-then-vanish bug (#705 regression)."
    )


def test_529_overload_still_silent_retries():
    src = inspect.getsource(research.agent_loop)
    i529 = src.index('"529" in err')
    branch = src[i529:i529 + 220]
    assert "sleep(60)" in branch and "continue" in branch, (
        "agent_loop's 529/overload branch must stay Tier-1 silent "
        "(sleep 60s; continue) — overload is server-side, not a key problem."
    )
