"""Guard: every Anthropic call on a 5-series model must declare `thinking`.

The trap this pins, which cost us a real regression:

On Sonnet 4.6 / Opus 4.8, OMITTING the `thinking` parameter meant "no thinking".
On the 5-series models it means ADAPTIVE THINKING IS ON, and `max_tokens` is a
hard cap on thinking tokens PLUS reply text together. So the moment the model
constants were bumped to the 5-series, every small-budget call silently became
able to spend its whole budget on reasoning and return no usable content:

  - the login verdict and pro-tier reads (max_tokens=8) parse ONE WORD, so an
    empty read is indistinguishable from a negative answer -> fails closed and
    blocks a signed-in user behind a login card;
  - the vision tier (max_tokens=512) FORCES a propose_action tool call, so a
    partly-spent budget returns no tool_use block, which reads as
    declare_failure while still consuming a per-run budget slot.

None of that raises. It degrades silently, which is why it needs a test rather
than a comment. A future model bump that adds a call site without an explicit
`thinking` should fail here, not in production.
"""
from __future__ import annotations

import re
from pathlib import Path

import models

REPO = Path(__file__).parent.parent

# The constants that resolve to a model whose thinking default is "on".
FIVE_SERIES_CONSTANTS = ("VISION_LIGHT_MODEL", "VISION_HEAVY_MODEL")


def _create_call_blocks(src: str):
    """Yield (line_number, text) for each messages.create(...) call.

    Both call shapes must match: the `asyncio.to_thread(client.messages.create,`
    form used in research.py and the direct `client.messages.create(` form used
    in vision.py. Matching only one silently halves the coverage."""
    for match in re.finditer(r"messages\.create[,(]\n(.{0,2000}?)\n\s*\)", src, re.S):
        yield src[: match.start()].count("\n") + 1, match.group(1)


def _five_series_call_sites():
    """Call sites that resolve to a 5-series model.

    The rule differs per file, deliberately:

    - vision.py is the vision tier and every call in it routes through
      _pick_model(), which returns only MODEL_SONNET / MODEL_OPUS (aliases of
      the two 5-series constants) — so EVERY create there qualifies, even
      though the call itself just says `model=model`.
    - research.py mixes model families, so match the constant by name. Matching
      a bare `model=model` there would wrongly catch the CUA loop, whose every
      caller passes CUA_MODEL (not 5-series — pinned separately below)."""
    sites = []
    for line, block in _create_call_blocks((REPO / "vision.py").read_text(encoding="utf-8")):
        sites.append(("vision.py", line, block))
    src = (REPO / "research.py").read_text(encoding="utf-8")
    for line, block in _create_call_blocks(src):
        if any(c in block for c in FIVE_SERIES_CONSTANTS):
            sites.append(("research.py", line, block))
    return sites


def test_the_model_constants_are_still_five_series():
    """If this fails the guard below may no longer be needed — but check the new
    model's thinking default before deleting it, don't just assume."""
    assert models.VISION_LIGHT_MODEL.startswith("claude-sonnet-5")
    assert models.VISION_HEAVY_MODEL.startswith("claude-opus-5")


def test_every_five_series_call_declares_thinking():
    sites = _five_series_call_sites()
    # Vacuous-pass guard: if the regex stops matching, fail loudly rather than
    # reporting green over zero call sites.
    assert len(sites) >= 4, f"found only {len(sites)} call sites (expected >= 4)"
    missing = [
        f"{name}:{line}" for name, line, block in sites if "thinking=" not in block
    ]
    assert not missing, (
        "Anthropic calls on a 5-series model without an explicit `thinking`: "
        f"{missing}. Omitting it turns adaptive thinking ON and max_tokens then "
        "caps thinking + reply together, so a small budget can return no content "
        "at all. Pass thinking={'type': 'disabled'} (valid at the default `high` "
        "effort; rejected only at xhigh/max) or raise max_tokens deliberately."
    )


def test_small_budget_calls_disable_thinking_rather_than_merely_setting_it():
    """A tiny budget shared with reasoning is the actual failure — these sites
    must disable thinking, not just mention the parameter."""
    for name, line, block in _five_series_call_sites():
        budget = re.search(r"max_tokens=(\d+)", block)
        if budget and int(budget.group(1)) <= 512:
            assert '"type": "disabled"' in block, (
                f"{name}:{line} has max_tokens={budget.group(1)} — too small to "
                "share with reasoning; disable thinking or raise the budget."
            )


def test_cua_model_is_not_five_series():
    """The CUA loop passes `model=model` (defaulting to CUA_MODEL) and shares a
    4096-token budget between reasoning and a tool-use turn. That is safe only
    while CUA_MODEL predates the thinking-on-by-default change. If this fails,
    add an explicit `thinking` to agent_loop's create call before bumping."""
    assert not re.match(r"claude-(opus|sonnet)-5", models.CUA_MODEL), models.CUA_MODEL


def test_no_api_effort_is_set_anywhere():
    """`thinking: disabled` is rejected at xhigh/max API effort. We rely on the
    default (`high`), so a future output_config must be reconciled with the
    disabled-thinking call sites above.

    NB: P2_MODEL_POLICY's "effort" is the claude.ai WEB-UI setting the browser
    drives, NOT this API parameter — they are different layers."""
    for name in ("research.py", "vision.py"):
        src = (REPO / name).read_text(encoding="utf-8")
        assert "output_config" not in src, (
            f"{name} now sets output_config; if it sets effort to xhigh/max, the "
            "thinking={'type': 'disabled'} call sites will start returning 400."
        )
