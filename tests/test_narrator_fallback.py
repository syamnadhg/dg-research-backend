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
  (2) The narrator brain gained a defensive top-of-function guard that
      substitutes a non-empty placeholder if any (future) caller passes an
      empty user_msg, so the Haiku hedge can never again 400 into silence.

#955 Phase 3′ — the narrator brain (was the `_call_narrator` closure nested
inside `_narrator_loop`) is HOISTED to a module-level `_call_text_narrator` so
the async alert-copy upgrade can reuse the exact same Gemini→Haiku fallback
chain. `gemini_key`/`use_gemini` are passed in and the once-per-loop
downgrade-log dedup rides a caller-owned mutable `err_holder` dict (was a
`nonlocal _gemini_err_logged` flag). The call-site / fb_user pins now live on
`_narrator_loop`'s source; the empty-content guard + fallback-chain pins move
to `_call_text_narrator`'s source.
"""
import inspect
import re

import research


_LOOP_SRC = inspect.getsource(research._narrator_loop)
_NARR_SRC = inspect.getsource(research._call_text_narrator)


def test_tier3_no_longer_passes_empty_user_msg():
    """The Tier-3 fallback must NOT call the brain with a literal "" user
    message — that was the exact line that 400'd the Haiku hedge."""
    assert '_call_text_narrator, fb_system, "", 200' not in _LOOP_SRC, (
        "Tier-3 _realistic_fallback still passes an empty user message to "
        "_call_text_narrator — Anthropic will 400 and the chain collapses to "
        "a canned Tier-4 template whenever Gemini is down."
    )


def test_tier3_builds_and_passes_a_nonempty_user_nudge():
    """Tier-3 must build a non-empty `fb_user` and hand it to the brain."""
    assert "fb_user" in _LOOP_SRC, "Tier-3 no longer constructs an fb_user nudge"
    assert "_call_text_narrator, fb_system, fb_user" in _LOOP_SRC, (
        "Tier-3 must pass the non-empty fb_user (not \"\") to _call_text_narrator"
    )


def test_call_narrator_has_empty_content_guard():
    """The narrator brain must defensively substitute a non-empty user_msg so a
    future caller can never silently 400 the Anthropic hedge."""
    assert "user_msg and user_msg.strip()" in _NARR_SRC, (
        "_call_text_narrator is missing the empty-user-content guard that "
        "protects the Haiku cross-vendor fallback from a 400"
    )


def test_no_empty_string_literal_passed_as_narrator_user_msg():
    """Belt-and-suspenders: no narrator invocation anywhere in the loop may
    pass an empty-string literal as the user_msg positional arg."""
    # Matches `_call_text_narrator, <system>, ""` — the empty-user-turn anti-pattern.
    bad = re.search(r'_call_text_narrator,\s*[A-Za-z_][A-Za-z0-9_]*,\s*""', _LOOP_SRC)
    assert bad is None, (
        f"A _call_text_narrator call still passes an empty user_msg: {bad.group(0)!r}"
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


# ── #955 Phase 3′ — narrator hoist parity ────────────────────────────────────

def test_narrator_brain_is_module_level_and_callable():
    """The brain is hoisted to module scope (no longer a closure) so the async
    alert-copy upgrade can reuse it. The old closure name is gone entirely."""
    assert callable(research._call_text_narrator)
    # Old nested closure was REMOVED (replaced, not shadowed) — no live def left.
    assert "def _call_narrator(" not in _LOOP_SRC, (
        "the old _call_narrator closure must be deleted, not shadowed"
    )


def test_narrator_brain_signature_takes_key_and_err_holder():
    """gemini_key / use_gemini / err_holder are passed in — the brain closes
    over NOTHING from the narrator loop, so alert-copy (with its own key) can
    call it safely."""
    sig = inspect.signature(research._call_text_narrator)
    params = sig.parameters
    assert "gemini_key" in params
    assert "use_gemini" in params
    assert "err_holder" in params
    assert "max_tokens" in params
    # gemini_key / use_gemini / err_holder / max_tokens are keyword-only (after *).
    for kw in ("gemini_key", "use_gemini", "err_holder", "max_tokens"):
        assert params[kw].kind is inspect.Parameter.KEYWORD_ONLY, kw
    # err_holder defaults to None (best-effort callers with no loop to dedupe).
    assert params["err_holder"].default is None


def test_narrator_brain_keeps_the_gemini_to_haiku_fallback_chain():
    """The hoisted brain must preserve every rung: Gemini primary, 429 surfaced
    (not fallback), non-429 failures fall through to Haiku, empty key → skip
    Gemini, missing requests/anthropic → (None, 0)."""
    # 429 surfaced so the outer loop backs off (not absorbed by Haiku).
    assert 'return "", 429' in _NARR_SRC
    # Haiku 4.5 fallback still present as the cross-vendor hedge.
    assert "anthropic" in _NARR_SRC and "NARRATOR_HAIKU" in _NARR_SRC
    # Guarded requests import → (None, 0) rather than crashing at module scope.
    assert "import requests" in _NARR_SRC
    assert "return None, 0" in _NARR_SRC
    # Gemini is only attempted when a key is actually present.
    assert "use_gemini and gemini_key" in _NARR_SRC


def test_downgrade_log_dedups_on_caller_owned_err_holder():
    """The once-per-loop Gemini→Haiku downgrade log rides a mutable err_holder
    dict (was `nonlocal _gemini_err_logged`). None-holder → suppressed (no
    crash) for best-effort callers."""
    assert 'err_holder.get("gemini_downgrade_logged")' in _NARR_SRC
    assert 'err_holder["gemini_downgrade_logged"] = True' in _NARR_SRC
    # None guard so a holder-less caller doesn't blow up on .get.
    assert "err_holder is not None" in _NARR_SRC


def test_loop_threads_key_and_holder_into_every_call_site():
    """All three narrator call sites (phase / per-agent / Tier-3 fallback) pass
    the resolved gemini_key + the shared err_holder."""
    # The kwargs only appear at genuine call sites (the bare name also shows up
    # in a comment), so they are the authoritative count of the 3 sites.
    assert _LOOP_SRC.count("err_holder=_narrator_err_holder") == 3, (
        "expected exactly 3 narrator call sites threading the shared err_holder"
    )
    assert _LOOP_SRC.count("gemini_key=gemini_key") == 3
    assert _LOOP_SRC.count("use_gemini=_USE_GEMINI") == 3


def test_loop_resets_downgrade_flag_on_recovery_anti_latch():
    """On a recovered narration the loop resets the err_holder downgrade flag so
    a later regression re-logs (anti-latch — the old _gemini_err_logged reset)."""
    assert '_narrator_err_holder = {"gemini_downgrade_logged": False}' in _LOOP_SRC
    assert '_narrator_err_holder["gemini_downgrade_logged"] = False' in _LOOP_SRC
