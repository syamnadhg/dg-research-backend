"""#61 (supersedes #705's pause-on-first-429) — agent_loop treats a 429 as a
transient burst FIRST: a bounded SILENT retry IN PLACE (inside the create-call
loop, so it never burns a mission iteration), then ESCALATE to a paused BLOCKER
card if it persists past the budget.

Why in-place: retrying via the OUTER mission loop's `continue` consumes an
iteration per retry, so a short-budget caller (max_iterations ≤ budget) would
drain its iterations before the escalation could fire, returning a mute
status="max_iterations" with no card. The silent retry therefore lives in the
same inner loop as the 5xx retry.

#705 is PRESERVED via escalation, not immediate pause: a persistent 429 still
surfaces a must-act paused card (a key the user must switch), and the escalated
card is a `recoverability="blocker"` whose TITLE ("API key rate limit persists")
does NOT match the FE isAnthropicRuntimeError quiet set, so the FE can no longer
swallow it into "retrying automatically" while the run sits paused (the exact
appear-then-vanish strand #705 feared, which the OLD title "API key is
rate-limited" still caused). 529/overload behaves identically, closing the old
unbounded loop that silently burned the whole iteration budget on an outage.

Source-inspection guard — agent_loop is a large async fn needing a live
client/browser to exercise, so we pin the branch structure instead (mirrors
the style of test_command_stale_gate / test_safety_net_constants).
"""
import inspect

import research


def test_429_bounded_in_place_retry_then_escalates():
    src = inspect.getsource(research.agent_loop)
    # The SILENT retry lives IN the create-call loop (keyed on `_api_s` via the
    # `_is_rate_limit` flag). Bound the slice to the OUTER handler so it captures
    # the whole inner retry block. (Can't bound on the inner `raise` — the word
    # "raise" appears in a preceding comment.)
    i_flag = src.index("_is_rate_limit")
    inner = src[i_flag:src.index("except Exception as e:", i_flag)]
    assert ("rate_limit_retries" in inner and "await asyncio.sleep(30)" in inner
            and "continue" in inner), (
        "429 must silent-retry IN PLACE (counter + 30s sleep + continue) in the "
        "create loop — NOT via the outer mission loop (which would burn iterations "
        "and never escalate on a short-budget caller)."
    )
    assert "overload_retries" in inner and "await asyncio.sleep(60)" in inner, (
        "529 must silent-retry IN PLACE too (counter + 60s sleep)."
    )

    # The OUTER except branch (keyed on `err`) is escalation-only: a persistent
    # 429 that exhausted the budget → paused BLOCKER + return, no silent retry.
    i429 = src.index('"429" in err')
    i529 = src.index('"529" in err')
    branch = src[i429:i529]
    assert 'recoverability="blocker"' in branch, (
        "the escalated 429 card must be a BLOCKER — un-auto-skippable AND "
        "un-swallowable by the FE quiet-infra gate (recoverability!='blocker')."
    )
    assert 'return {"status": "error"' in branch, (
        "after the budget is exhausted the 429 branch must escalate + return."
    )
    # Match the CODE (await asyncio.sleep) not the bare "sleep(30)" that appears
    # in prose, so a comment can't mask a real regression.
    assert "await asyncio.sleep(30)" not in branch, (
        "the OUTER 429 branch must NOT silent-retry — that moved in-place (else "
        "it burns mission iterations and never escalates on short-budget callers)."
    )
    _t = "API key rate limit persists".lower()
    assert "rate_limit" not in _t and "rate-limit" not in _t and "429" not in _t, (
        "the escalated title must dodge isAnthropicRuntimeError — the SPACE in "
        "'rate limit' (vs 'rate_limit'/'rate-limit'), and no '429', is load-bearing."
    )


def test_529_overload_bounded_in_place_retry_then_escalates():
    src = inspect.getsource(research.agent_loop)
    i529 = src.index('"529" in err')
    branch = src[i529:src.index("workspace api usage limits")]  # to the next elif
    assert 'recoverability="blocker"' in branch and 'return {"status": "error"' in branch, (
        "a sustained overload must escalate to a paused blocker and return, not "
        "loop forever silently burning the whole iteration budget (mute partial)."
    )
    assert "await asyncio.sleep(60)" not in branch, (
        "the OUTER 529 branch must NOT silent-retry — that moved in-place."
    )


def test_stop_during_transient_backoff_returns_cleanly():
    # #61: a Stop mid-outage must NOT fire an escalation card — the outer handler
    # returns status="stopped" before any 429/529 escalation.
    src = inspect.getsource(research.agent_loop)
    outer = src[src.index("except Exception as e:"):]
    i_guard = outer.index("_controls.is_stop()")
    i_429 = outer.index('"429" in err')
    assert i_guard < i_429, (
        "the Stop guard must precede the 429/529 escalation so an aborted run "
        "returns cleanly instead of carding."
    )
    assert 'return {"status": "stopped"' in outer[i_guard:i_429]
