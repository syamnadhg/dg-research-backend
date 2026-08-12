"""A repair that moved the budget and left the clock behind.

On 2026-08-11 the vision source-URL call was losing every URL in the panel: the
model ran out of output tokens mid-array and the JSON never closed. The fix
raised `maxOutputTokens` from 800 to 2400 and taught the handler to salvage the
whole URLs out of a clipped response.

Both halves were right, and the request still failed the next run — this time
with a read timeout instead of a truncated body. The clock was never touched:

    resp = _req.post(url, json=payload, timeout=10.0)

Ten seconds was not a guess. At 800 tokens the answer came back CLIPPED, which
is proof it came back inside ten seconds. Tripling what the model has to write
and leaving the wait where it was is what turned a truncated-but-delivered
response into no response at all — the same lost sources, a new cause, shipped
by the repair.

THE INVARIANT, NOT THE ARITHMETIC

The pair is now two named constants and one assumption: the Flash tier emits no
fewer than `_VISION_URL_MIN_TOKENS_PER_SEC`, so the timeout must cover the WHOLE
budget at that rate. It explains the history exactly — 800/100 = 8s, which is
why ten seconds worked; 2400/100 = 24s, which is why it stopped — and the test
below fails if either constant moves again without the other.

WHY THE TIMEOUT IS SIZED GENEROUSLY

The caller is one-shot per agent: `vision_urls_done` is set on the failure path
too, so there is no second attempt. A timeout costs the run every source in that
panel for good, while the cost of waiting is one stretched leg of a round-robin
whose poll interval is two minutes. Both properties are pinned here, because
either one changing changes what the right number is.
"""
import ast
import asyncio
import inspect
import re
import textwrap

import pytest

import research
from conftest import code_only


def vision_src() -> str:
    return code_only(research.extract_source_urls_via_vision)


class _Page:
    """Just enough page for the screenshot the call starts with."""

    async def screenshot(self, **_kw):
        return b"\x89PNG\r\n\x1a\n"


class _Resp:
    status_code = 200

    def json(self):
        return {"candidates": [{"content": {"parts": [{
            "text": '{"urls": ["https://example.com/a"], "confidence": 0.9}'}]}}]}


def call_with_recorded_post(monkeypatch, post):
    """Run the real extractor with `requests.post` replaced by `post`."""
    import sys
    import types
    monkeypatch.setattr(research, "resolve_gemini_api_key", lambda: "k")
    stub = types.ModuleType("requests")
    stub.post = post
    monkeypatch.setitem(sys.modules, "requests", stub)
    return asyncio.run(research.extract_source_urls_via_vision(_Page(), "chatgpt"))


# ------------------------------------------------- what the request actually is


def test_the_request_waits_on_the_constant_not_on_ten_seconds(monkeypatch):
    """⭐ THE BUG, read off the live call rather than the source."""
    seen = {}

    def _post(url, **kw):
        seen.update(kw)
        return _Resp()

    call_with_recorded_post(monkeypatch, _post)
    assert seen.get("timeout") == research._VISION_URL_TIMEOUT_S
    assert seen["timeout"] > 10.0, (
        f"the read timeout is still {seen['timeout']}s against a "
        f"{research._VISION_URL_MAX_TOKENS}-token budget — this is the 08-11 "
        f"pairing that timed out"
    )


def test_the_request_still_sends_the_budget_it_was_sized_for(monkeypatch):
    seen = {}

    def _post(url, **kw):
        seen.update(kw)
        return _Resp()

    call_with_recorded_post(monkeypatch, _post)
    gen = seen["json"]["generationConfig"]
    assert gen["maxOutputTokens"] == research._VISION_URL_MAX_TOKENS
    assert gen["responseSchema"] is research._VISION_URL_SCHEMA


def test_a_timeout_is_still_passed_at_all(monkeypatch):
    """⛔ Over-correction guard, and the worst possible one: `requests` with no
    timeout waits forever. This call is awaited inside the round-robin, so a
    hung socket would hold every other agent's polling with it — strictly worse
    than the ten seconds being fixed."""
    tree = ast.parse(textwrap.dedent(vision_src()))
    posts = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "post"]
    assert posts, "the vision-urls POST is gone"
    for call in posts:
        kw = {k.arg: k.value for k in call.keywords}
        assert "timeout" in kw, "the POST has no timeout — this one hangs forever"
        assert isinstance(kw["timeout"], ast.Name), (
            "the timeout is a literal again, which is how it drifted from the "
            "budget it is paired to"
        )


# ----------------------------------------------------- the invariant that binds


def test_the_timeout_covers_the_whole_budget_at_the_assumed_rate():
    """⭐ THE POINT OF THE FIX. This is the assertion that would have failed on
    08-11, before the run did."""
    floor = research._VISION_URL_MAX_TOKENS / research._VISION_URL_MIN_TOKENS_PER_SEC
    assert research._VISION_URL_TIMEOUT_S >= floor, (
        f"{research._VISION_URL_MAX_TOKENS} tokens needs at least {floor:.0f}s at "
        f"{research._VISION_URL_MIN_TOKENS_PER_SEC} tok/s, but the request gives up "
        f"after {research._VISION_URL_TIMEOUT_S}s — the budget was raised and the "
        f"clock was left behind, again"
    )


def test_the_old_pairing_would_have_failed_this_invariant():
    """The invariant has to be the one that discriminates, not one that happens
    to hold. 800 tokens at 10s passed; 2400 at 10s does not."""
    rate = research._VISION_URL_MIN_TOKENS_PER_SEC
    assert 800 / rate <= 10.0, "the invariant rejects the pairing that demonstrably worked"
    assert 2400 / rate > 10.0, "the invariant accepts the pairing that demonstrably timed out"


def test_the_budget_was_not_quietly_lowered_to_satisfy_the_invariant():
    """⛔ Over-correction guard. Dropping back to 800 tokens also satisfies the
    relation above — and re-breaks the truncation the 08-11 fix was for."""
    assert research._VISION_URL_MAX_TOKENS >= 2400


def test_the_timeout_stays_well_inside_the_poll_interval():
    """⛔ Over-correction guard the other way. This await sits inside the P2
    round-robin leg, so an enormous timeout would stall every sibling agent's
    poll behind one slow screenshot read."""
    poll = int(re.search(r'POLL_DEEP_RESEARCH = int\(os\.environ\.get\("POLL_DEEP_RESEARCH", "(\d+)"\)\)',
                         code_only(inspect.getsource(research))).group(1))
    assert research._VISION_URL_TIMEOUT_S <= poll / 2, (
        f"a {research._VISION_URL_TIMEOUT_S}s wait inside a {poll}s poll interval "
        f"delays every other agent's tick"
    )


@pytest.mark.parametrize("const", ["_VISION_URL_MAX_TOKENS", "_VISION_URL_TIMEOUT_S"])
def test_both_halves_are_tunable_live(const):
    """They are one decision and they move together, which is exactly why both
    must be reachable without a redeploy — the alternative on the next slow
    model is another run that loses its sources."""
    src = code_only(inspect.getsource(research))
    at = src.index(f"{const} = ")
    assert "os.environ.get(" in src[at:at + 120]


# --------------------------------- the two properties that justify the sizing


def test_the_call_is_one_shot_per_agent_on_success_and_on_failure():
    """⭐ The reason to be generous rather than tight. If this ever starts
    retrying, a shorter timeout becomes the better trade and this file's
    reasoning needs rewriting — so the property is asserted, not assumed."""
    src = code_only(research.poll_all_agents_round_robin)
    at = src.index("extract_source_urls_via_vision(")
    block = src[at:src.index("# Emit agent_progress", at)] if "# Emit agent_progress" in src \
        else src[at:at + 1600]
    assert block.count('p["vision_urls_done"] = True') == 2, (
        "the vision-urls call no longer marks itself done on both paths"
    )
    assert "except Exception" in block


def test_the_gate_still_requires_an_open_panel():
    """A screenshot of a closed panel costs the same timeout and can contain no
    sources at all."""
    src = code_only(research.poll_all_agents_round_robin)
    # Anchored from the vision-urls guard, not from `_gate_ok` — the poller
    # binds that name more than once and the FIRST one belongs to Claude's
    # artifact scrape, several hundred lines earlier.
    at = src.index('not p.get("vision_urls_done")')
    window = src[at:src.index("extract_source_urls_via_vision(", at)]
    assert "chatgpt_activity_panel_open" in window
    assert "artifact_panel_open" in window


def test_the_extractor_can_still_be_switched_off_entirely():
    src = code_only(research.poll_all_agents_round_robin)
    assert 'os.environ.get("DG_VISION_URL_EXTRACT", "1") == "1"' in src


# ------------------------------------------- the 08-11 salvage is still in place


def test_a_truncated_body_is_still_salvaged(monkeypatch):
    """⛔ The timeout fix must not have displaced the truncation fix: a clipped
    response still yields its whole URLs rather than nothing."""
    class _Clipped(_Resp):
        def json(self):
            return {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{
                "text": '{"urls": ["https://example.com/a", "https://example.com/b'}]}}]}

    urls = call_with_recorded_post(monkeypatch, lambda url, **kw: _Clipped())
    assert urls == ["https://example.com/a"], (
        "a response that ran out of tokens returned nothing — the salvage is gone"
    )


def test_a_timeout_still_costs_the_call_and_not_the_run(monkeypatch):
    """The socket raising must stay contained: an empty list, a WARN, and the
    poll loop carries on. It is the one behaviour that made this defect a lost
    panel rather than a lost run."""
    def _boom(url, **kw):
        raise TimeoutError("read timed out")

    assert call_with_recorded_post(monkeypatch, _boom) == []
