"""#709 — Gemini DR "active" detection uses the composer placeholder, and the
verify step NEVER toggles a working DR pill off.

Last E2E (backend-2.log): setup_gemini_dr's DOM path missed DR on every worker;
the run only succeeded when the CUA fallback recovered it. Worse, the pill's
class (`mdc-button mat-mdc-button-base mat-badge mat-tonal-button …`) carries
NONE of aria-pressed / --selected / .active even when DR is ON, so the prior
pressed-class-only verify FALSE-NEGATIVED an ALREADY-ACTIVE pill → the CUA
fallback then clicked that active pill and TOGGLED DEEP RESEARCH OFF ("why was
the working DR removed?").

The authoritative, cross-version signal is the COMPOSER PLACEHOLDER:
DR ON → "What do you want to research?"; chat → "Ask Gemini". A single shared
constant (_GEMINI_DR_STATE_JS) computes it for both setup_gemini_dr's verify
and the pre-send ensure_deep_mode_active check. The toggle-to-activate fires
ONLY when we are CONFIDENT DR is OFF (placeholder explicitly "Ask Gemini"), so
a working pill can never be clicked off. Source-inspection guards.
"""
import inspect

import research


def test_shared_state_constant_keys_on_placeholder():
    js = research._GEMINI_DR_STATE_JS
    assert "what do you want to" in js.lower(), (
        "_GEMINI_DR_STATE_JS must key DR-active on the 'What do you want to "
        "research?' placeholder (#709)."
    )
    assert "placeholderResearch" in js and "placeholderChat" in js, (
        "_GEMINI_DR_STATE_JS must expose both a research-mode and an explicit "
        "chat-mode ('Ask Gemini') placeholder signal (#709)."
    )
    # Composer-anchored — must NOT fall back to a page-wide [data-placeholder]
    # scan that could read a stale dialog/modal placeholder.
    assert "rich-textarea" in js, (
        "the placeholder read must anchor to the Gemini composer "
        "(rich-textarea), not scan the whole page (#709)."
    )


def test_verify_only_toggles_when_confidently_off():
    src = inspect.getsource(research.setup_gemini_dr)
    # The pill-click guard must require the explicit chat-mode signal — never
    # click on an ambiguous read (which could toggle a working pill OFF).
    assert 'st.get("placeholderChat")' in src, (
        "the toggle-to-activate must fire ONLY when the composer is confidently "
        "in chat mode ('Ask Gemini'), so a working DR pill is never clicked off "
        "(#709 — 'why was the working DR removed?')."
    )
    assert "arm Deep Research" in src, (
        "the click should arm DR from a confirmed-off state, logged as such "
        "(#709)."
    )


def test_verify_dumps_pill_state_on_failure():
    src = inspect.getsource(research.setup_gemini_dr)
    assert "Verify FAIL: DR not active — dump" in src, (
        "on verify failure setup_gemini_dr must dump the pill state + "
        "placeholder so the next E2E pins the real active class (#709)."
    )


def test_ensure_deep_mode_gemini_returns_real_state():
    """The pre-send re-check must report the MEASURED active state for Gemini
    (it was hard-coded active=True, so the send gate could never fire) and must
    reuse the SAME shared constant as setup_gemini_dr's verify."""
    src = inspect.getsource(research.ensure_deep_mode_active)
    assert "_GEMINI_DR_STATE_JS" in src, (
        "ensure_deep_mode_active must reuse the shared _GEMINI_DR_STATE_JS so "
        "its pre-send check agrees with setup_gemini_dr's verify (#709)."
    )
    assert 'return {"platform": "gemini", "active": active}' in src, (
        "ensure_deep_mode_active must return Gemini's real measured active "
        "state, not a hard-coded True (#709)."
    )
