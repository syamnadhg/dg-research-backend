"""#923 (2026-07-08): Phase 1 ChatGPT must NOT run in Deep Research mode.

User-captured screenshot: P1's brief prompt was submitted while the ChatGPT
composer still had the Deep Research tool active (placeholder "Get a detailed
report", a "📣 Deep research" badge on the sent brief, and ChatGPT answered with
a "Golden Retriever Deep Research" plan card gated behind Edit/Cancel/Start-46)
— the WRONG output type, gated behind a Start click, burning a deep-research
slot. Root cause: ChatGPT persists the last-used composer tool per account, so a
PRIOR run's Phase-2 'Deep research' selection is sticky-on for the next run's
Phase-1, and run_phase1 never cleared it (it only drives the model picker).

Fix (verified here): a fail-safe `_chatgpt_clear_deep_research` helper that
detects an active Deep Research composer tool and turns it OFF (DOM '+' menu
toggle → composer-pill ✕ → bounded CUA fallback), called in run_phase1 right
before the brief prompt is submitted. Deep Research belongs to Phase 2 ONLY.
"""

import inspect

import research


def test_helper_exists_and_is_failsafe():
    assert hasattr(research, "_chatgpt_clear_deep_research"), (
        "P1 needs a helper that clears a persisted Deep Research tool off the "
        "ChatGPT composer before the brief is submitted."
    )
    src = inspect.getsource(research._chatgpt_clear_deep_research)
    # Must be fail-safe — a probe/removal miss can never block Phase 1.
    assert "try:" in src and "except Exception" in src


def test_detects_the_detailed_report_placeholder():
    """The DR-mode composer placeholder is 'Get a detailed report' — it contains
    'report', NOT 'research'. The detector must catch that (the prior
    placeholder.includes('research') check would MISS it)."""
    src = inspect.getsource(research)
    assert "_CHATGPT_DR_ACTIVE_JS" in src
    js = research._CHATGPT_DR_ACTIVE_JS
    assert "detailed report" in js, (
        "the DR-mode placeholder 'Get a detailed report' must be a detection "
        "signal — matching only 'research' misses it (user-captured #923)."
    )


def test_detector_scoped_to_composer_form_not_sent_message():
    # A 'Deep research' badge on an already-SENT message lives OUTSIDE the
    # composer <form>; scoping to the form prevents a false-positive.
    js = research._CHATGPT_DR_ACTIVE_JS
    assert "querySelector('form')" in js
    assert "deep research" in js.lower()


def test_clear_uses_dom_menu_toggle_then_pill_then_cua():
    src = inspect.getsource(research._chatgpt_clear_deep_research)
    # Strategy A — reuse the same '+'/tools-menu control setup_chatgpt_dr uses.
    assert 'button[data-testid="composer-plus-btn"]' in src
    assert '[role="menuitemradio"]' in src
    # Strategy B — composer pill ✕ (remove/close control on the DR chip).
    assert "remove" in src and "close" in src
    # Strategy C — bounded CUA fallback (DR-off is correctness-critical for P1).
    assert "PROMPT_CHATGPT_DISABLE_DR" in src
    assert "1a-disable-dr" in src


def test_clear_never_enables_a_tool():
    """The helper must only ever turn Deep Research OFF — it must never call the
    P2 setup (which turns DR ON) or otherwise enable a tool."""
    src = inspect.getsource(research._chatgpt_clear_deep_research)
    # It must never CALL the ON-setup (a comment may reference it by name).
    assert "await setup_chatgpt_dr(" not in src
    assert "await setup_gemini_dr(" not in src


def test_diagnostic_dump_on_failure():
    src = inspect.getsource(research._chatgpt_clear_deep_research)
    assert "composer dump" in src, (
        "on a total clear failure the helper must dump the composer's "
        "research/report controls so the next E2E pins the real selector."
    )


def test_menu_open_dump_pins_the_menuitemradio_control():
    """Adversarial-review fold (#923): the 'Deep research' menuitemradio lives in
    a body-level popover only observable WHILE the '+' menu is open. Strategy A
    must dump the menu items (with data-testid) at that moment on a toggle miss —
    the final form-scoped dump can only ever see the Strategy-B pill."""
    src = inspect.getsource(research._chatgpt_clear_deep_research)
    assert "Strategy-A menu dump" in src
    # Both dumps must capture data-testid (ChatGPT uses testid-based controls).
    assert src.count("data-testid") >= 2


def test_called_in_run_phase1_before_submit():
    src = inspect.getsource(research.run_phase1)
    assert "_chatgpt_clear_deep_research(" in src, (
        "run_phase1 must actually invoke the clear-DR helper."
    )
    clear_at = src.index("_chatgpt_clear_deep_research(")
    submit_at = src.index("submit_chatgpt_direct(browser, prompt)")
    assert clear_at < submit_at, (
        "the Deep Research tool must be cleared BEFORE the brief prompt is "
        "submitted — otherwise the brief still runs in Deep Research mode."
    )


def test_clear_is_after_model_select_and_pdf_attach():
    # It sits after the Pro-model selection + PDF attach so it operates on the
    # final pre-submit composer (nothing between the clear and submit re-enables
    # DR; P1 never turns DR on).
    src = inspect.getsource(research.run_phase1)
    assert src.index("PROMPT_SELECT_PRO") < src.index("_chatgpt_clear_deep_research(")


def test_prompt_disables_dr_and_forbids_other_tools():
    assert hasattr(research, "PROMPT_CHATGPT_DISABLE_DR")
    p = research.PROMPT_CHATGPT_DISABLE_DR.lower()
    assert "deep research" in p and "off" in p
    # Must not accidentally instruct enabling a different tool or sending.
    assert "do not enable any other tool" in p
    assert "do not press send" in p or "do not send" in p


def test_hotspot_registered():
    assert "1a-disable-dr" in research._HOTSPOT_VISION_HINTS
