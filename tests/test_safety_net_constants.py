"""Lightweight smoke tests for the 2026-05-25 P1 safety-net + diagnostic
additions in poll_until_done.

The Python side of these changes is:
  1. _verify_chatgpt_generating_diag — async helper that runs JS in
     Playwright; we don't have a Playwright runtime in unit tests, so
     we just verify the function is defined and async.
  2. SAFETY_NET_CUA_SEC constant + safety_net_cua_asked state — these
     live as locals inside poll_until_done; we sanity-check the literal
     value matches what we ship via source inspection.

Behavior testing of the full async loop belongs in E2E, not unit tests.
What we CAN catch here cheaply:
  - Diagnostic helper is exported and async.
  - SAFETY_NET_CUA_SEC literal is set to 300 (5 min) — guards against an
    accidental tweak to a value that's too low (would fire CUA on every
    pause between token bursts) or too high (defeats the point).
"""

import asyncio
import inspect
import re
from pathlib import Path

import pytest


_RESEARCH_PY = Path(__file__).resolve().parent.parent / "research.py"


def test_diag_helper_is_async():
    """The diagnostic helper must be async — poll_until_done awaits it."""
    import research

    fn = getattr(research, "_verify_chatgpt_generating_diag", None)
    assert fn is not None, (
        "_verify_chatgpt_generating_diag missing — safety-net diagnostic "
        "logging relies on this helper. If renamed, update the call site "
        "inside poll_until_done at the 'Safety-net diag:' log line."
    )
    assert inspect.iscoroutinefunction(fn), (
        "_verify_chatgpt_generating_diag must be `async def` — poll_until_done "
        "awaits the result. A sync function here would deadlock or raise."
    )


def test_safety_net_constants_present():
    """Lock the 5-minute safety-net threshold + state-var name in source.

    Hardcoded literals in poll_until_done are hard to import at test
    time (they're function-locals), so we read the file and grep. This
    fires if someone renames SAFETY_NET_CUA_SEC or accidentally bumps
    the value down to <60s (which would CUA-spam every poll) or up to
    >900s (which approaches the existing 1200s stall threshold and
    defeats the early-escalation point).
    """
    src = _RESEARCH_PY.read_text(encoding="utf-8")

    # Constant declared
    m = re.search(r"^\s*SAFETY_NET_CUA_SEC\s*=\s*(\d+)\s*$", src, re.MULTILINE)
    assert m, "SAFETY_NET_CUA_SEC literal not found in research.py — was it renamed?"
    val = int(m.group(1))
    assert 60 <= val <= 900, (
        f"SAFETY_NET_CUA_SEC = {val} is outside the sane range [60, 900]. "
        f"Too low CUA-spams every poll; too high defeats the early-escalation "
        f"point (existing STALL_THRESHOLD_SEC is 1200)."
    )

    # State var declared near the constant
    assert "safety_net_cua_asked = False" in src, (
        "safety_net_cua_asked state-var init missing. The safety-net branch "
        "in poll_until_done gates on this; without it the block is unreachable."
    )

    # safety_net_cua_asked must appear at least TWICE in the source:
    # once at the initial-state declaration (top of poll_until_done) and
    # again as a reset in the content-growth branch. Without the reset,
    # a single safety-net trigger early in the run suppresses re-checks
    # if a real stall hits later. Counting occurrences is more robust
    # than a positional regex (which trips on comment blocks between).
    occurrences = src.count("safety_net_cua_asked = False")
    assert occurrences >= 2, (
        f"safety_net_cua_asked = False appears {occurrences} time(s); "
        f"expected at least 2 (init + content-growth reset). The growth "
        f"reset lives in the `if _grew:` branch around the existing "
        f"`stall_window_start = None` line."
    )


def test_diag_helper_returns_str_when_uncallable_target():
    """Smoke: calling the helper with a stub that lacks .evaluate returns
    a string starting with 'diag_error:' rather than raising.

    The safety-net branch logs the result; a raised exception there would
    have to be wrapped in another try/except. By having the helper
    swallow exceptions and return a string we keep the call site clean.
    """
    import research

    class Stub:
        # Intentionally no .evaluate — accessing it triggers AttributeError
        pass

    out = asyncio.run(research._verify_chatgpt_generating_diag(Stub()))
    assert isinstance(out, str), (
        f"Helper must always return a string; got {type(out).__name__}"
    )
    assert out.startswith("diag_error:"), (
        f"Helper must tag exceptions with 'diag_error:' prefix; got {out!r}"
    )
