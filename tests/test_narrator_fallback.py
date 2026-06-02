"""#729 — narrator fallback-chain hardening: Tier-3 realistic narration must
not silently collapse to a canned Tier-4 template when Gemini is down.

Incident shape (grounded in backend.log / backend-2.log): the per-agent
narrator runs Gemini 3.5 Flash primary with a Haiku 4.5 cross-vendor hedge.
On this machine Gemini's `generativelanguage.googleapis.com` endpoint fails
chronically (recurring SSLError / ReadTimeout / ConnectionAborted), so a large
fraction of ticks route to the Haiku fallback. That is fine for Tier-2
(event-based) narration — it passes a non-empty user message. But the Tier-3
"realistic timeline" fallback (`_realistic_fallback`) called the brain with an
EMPTY user message ("") — every bit of context lived in the system prompt.
Gemini tolerates an empty user turn; Anthropic rejects it with a 400
("messages.0: user messages must have non-empty content"). The current Haiku
branch swallows that 400 (`except Exception: return None, 0`) SILENTLY, so
whenever Gemini was down AND Tier-3 fired (sparse-data windows: P1 extended
thinking, P2 planning gaps) the chain fell through to the canned Tier-4
deterministic template — the "stale / shallow" narration the user reported.

Fix (BE-only, two layers):
  (1) `_realistic_fallback` now passes a concise, NON-EMPTY user nudge so the
      call succeeds on BOTH brains.
  (2) `_call_narrator` gained a defensive top-of-function guard that
      substitutes a non-empty placeholder if any (future) caller passes an
      empty user_msg, so the Haiku hedge can never again 400 into silence.

Both narrator brains are nested closures inside `_narrator_loop`, so these are
source-inspection guards over that function plus a logic check on the guard
predicate.
"""
import inspect
import re

import research


_SRC = inspect.getsource(research._narrator_loop)


def test_tier3_no_longer_passes_empty_user_msg():
    """The Tier-3 fallback must NOT call the brain with a literal "" user
    message — that was the exact line that 400'd the Haiku hedge."""
    assert '_call_narrator, fb_system, "", 200' not in _SRC, (
        "Tier-3 _realistic_fallback still passes an empty user message to "
        "_call_narrator — Anthropic will 400 and the chain collapses to a "
        "canned Tier-4 template whenever Gemini is down."
    )


def test_tier3_builds_and_passes_a_nonempty_user_nudge():
    """Tier-3 must build a non-empty `fb_user` and hand it to the brain."""
    assert "fb_user" in _SRC, "Tier-3 no longer constructs an fb_user nudge"
    assert "_call_narrator, fb_system, fb_user" in _SRC, (
        "Tier-3 must pass the non-empty fb_user (not \"\") to _call_narrator"
    )


def test_call_narrator_has_empty_content_guard():
    """`_call_narrator` must defensively substitute a non-empty user_msg so a
    future caller can never silently 400 the Anthropic hedge."""
    assert "user_msg and user_msg.strip()" in _SRC, (
        "_call_narrator is missing the empty-user-content guard that protects "
        "the Haiku cross-vendor fallback from a 400"
    )


def test_no_empty_string_literal_passed_as_narrator_user_msg():
    """Belt-and-suspenders: no _call_narrator invocation anywhere in the loop
    may pass an empty-string literal as the user_msg positional arg."""
    # Matches `_call_narrator, <system>, ""` — the empty-user-turn anti-pattern.
    bad = re.search(r'_call_narrator,\s*[A-Za-z_][A-Za-z0-9_]*,\s*""', _SRC)
    assert bad is None, (
        f"An _call_narrator call still passes an empty user_msg: {bad.group(0)!r}"
    )


def test_empty_content_guard_predicate_logic():
    """Pin the guard's boolean semantics: empty / whitespace-only inputs are
    treated as empty (→ substituted), real text passes through unchanged.
    Mirrors the `if not (user_msg and user_msg.strip())` guard."""
    def _is_empty(user_msg: str) -> bool:
        return not (user_msg and user_msg.strip())

    assert _is_empty("") is True
    assert _is_empty("   ") is True
    assert _is_empty("\n\t ") is True
    assert _is_empty("Recent events (newest last):\n- agent_progress") is False
    assert _is_empty("Narrate what the CHATGPT agent is doing right now.") is False
