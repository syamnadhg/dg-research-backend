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
detects an active Deep Research composer tool and turns it OFF, called in
run_phase1 right before the brief prompt is submitted. Deep Research belongs to
Phase 2 ONLY.

#952 (2026-07-13): the removal strategy changed. ChatGPT's tools menu no longer
TOGGLES Deep Research — clicking the already-selected 'Deep research' item (DOM
or CUA vision) ADDS a SECOND Deep Research instead of removing it (user-observed:
'trying to click deep research again adds 2 instead of removing'). The primary
strategy is now BACKSPACE-delete of the inline composer token (the platform's
real remove affordance), then the pill ✕, then a Backspace-oriented CUA fallback
that FORBIDS clicking the tool. See test_p1_dr_backspace_952.py.
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


def test_clear_uses_backspace_then_pill_then_cua():
    # #952 (2026-07-13): the PRIMARY strategy is now Backspace-delete of the
    # composer token — ChatGPT's tools menu no longer toggles DR off; CLICKING
    # the item adds a SECOND Deep Research (see the regression guard below).
    src = inspect.getsource(research._chatgpt_clear_deep_research)
    # Strategy A — Backspace-delete the inline token (the platform's real remove).
    assert "_CHATGPT_FOCUS_COMPOSER_END_JS" in src
    assert 'press("Backspace")' in src
    # Strategy B — composer pill ✕ (remove/close control on the DR chip).
    assert "remove" in src and "close" in src
    # Strategy C — bounded CUA fallback (DR-off is correctness-critical for P1).
    assert "PROMPT_CHATGPT_DISABLE_DR" in src
    assert "1a-disable-dr" in src


def test_backspace_never_eats_typed_prose():
    """The Backspace strategy must refuse to press when the composer already
    holds typed text (guarding the brief) — it keys off a textLen probe."""
    src = inspect.getsource(research._chatgpt_clear_deep_research)
    assert "textLen" in src and "skipping Backspace" in src
    # The focus JS reports the char count the guard reads.
    js = research._CHATGPT_FOCUS_COMPOSER_END_JS
    assert "textLen" in js and "collapse(false)" in js, (
        "the caret must collapse to the END of the composer (right after the "
        "inline token) so Backspace deletes the token, and it must report the "
        "text length so the caller never backspaces over prose"
    )


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


def test_no_click_toggle_that_adds_a_second_dr():
    """#952 regression guard: the clear helper must NOT open the '+'/tools menu
    and click the 'Deep research' item to 'deselect' it. In the current ChatGPT
    UI the tools menu no longer toggles — clicking the already-selected item ADDS
    a SECOND Deep Research (user-observed 2026-07-13: 'trying to click deep
    research again adds 2 instead of removing'). Backspace is the only remove."""
    src = inspect.getsource(research._chatgpt_clear_deep_research)
    assert 'composer-plus-btn' not in src, (
        "the clear helper must not open the tools '+' menu to toggle DR"
    )
    # The kept diagnostic dump queries menuitemradio in a selector but never
    # clicks it, so pin the tools-menu OPEN signatures instead.
    assert 'Use a tool' not in src, (
        "opening the tools menu to click 'Deep research' adds a second DR — removed"
    )
    assert "menu toggle" not in src


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
