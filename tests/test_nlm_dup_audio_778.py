"""#778 — NotebookLM duplicate-audio: PREVENT + duplication-RESILIENT download.

Root cause (settled, user-confirmed 2026-06-03): NotebookLM's "Audio Overview"
control has a separate Customise ARROW; clicking the card BODY (which the CUA
agent did while hunting for the open-affordance) fires NLM's one-click DEFAULT
audio = a 2nd card. The #757-A fix only hardened the POST-Generate click, so the
OPEN-step body-misclick still produced dups (seen in the post-ealc E2E). And once
2 cards existed, the no-delete dup fail_phase wedged the no-audio retry loop, and
a user Skip was ignored.

Three cooperating parts, all guarded here (BE-only; NO-DELETE throughout):

  A) PREVENT — DOM-click the confirmed Customise arrow
     (button[aria-label="Customise Audio Overview"]) to open the panel without
     ever touching the card body; CUA then configures Format/Length + clicks the
     terminal Generate from the already-open panel (panel_already_open=True).
     A once-per-process read-only `customize-open` canary pins the un-supplied
     Generate/length controls.

  B) RESILIENT DOWNLOAD — a read-only `_pick_nlm_audio_card` resolves WHICH card
     is the user-requested one (format + DOM order; duration is absent from the
     card) and the download prompt is told to target ONLY that ordinal. The
     post-generate + mid-poll dup fail_phases are demoted to log+continue; the
     post-cleanup invariant relaxes to total_count >= 1. A dup never blocks
     delivery — and nothing is ever deleted.

  C) BOUND + SKIP — a fresh invocation Generates at most once; prefer_existing
     retries are download-only; and the no-audio auto-retry loop now honors a
     user SKIP_PHASE(3) (loop top + the 5-min interruptible_sleep).

Run:  pytest tests/test_nlm_dup_audio_778.py -v
"""
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prompts
import research


def _src(fn):
    return inspect.getsource(fn)


# ══ Part A — PREVENTION (DOM arrow-click, never the card body) ═══════════════

def test_open_customize_helper_exists_and_is_async():
    assert inspect.iscoroutinefunction(research._open_nlm_audio_customize), (
        "_open_nlm_audio_customize must be an async DOM helper"
    )


def test_open_customize_uses_confirmed_arrow_selector():
    src = _src(research._open_nlm_audio_customize)
    assert 'button[aria-label="Customise Audio Overview"]' in src, (
        "the confirmed arrow selector (user console dump 2026-06-03) is gone"
    )
    assert "data-edit-button-type" in src, (
        "the defensive data-edit-button-type fallback for the arrow is gone"
    )


def test_open_customize_never_clicks_card_body_or_deletes():
    # It may click ONLY a button (the arrow). It must never open a menu / delete
    # / run a CUA loop (all of which are how a dup or a no-delete violation would
    # happen). Every selector it clicks is a <button>. (Check for actual CALLS,
    # not the prose word "deletes" in the docstring.)
    src = _src(research._open_nlm_audio_customize)
    low = src.lower()
    assert "agent_loop" not in low, "the arrow-opener must be pure DOM, not CUA"
    assert ".delete(" not in low, "the arrow-opener must never call delete (no-delete)"
    assert "menuitem" not in low, "the arrow-opener must not open/click a menu"
    # Only button selectors are clicked — never the card body container
    # (basic-create-artifact-button itself / div[aria-label="Audio Overview"]).
    assert "el.click()" in src or "b.click()" in src, (
        "the helper no longer clicks the arrow button"
    )
    assert "querySelectorAll('button" in src or "button[" in src, (
        "the helper must target BUTTON controls (the arrow), not the card body"
    )


def test_generate_prompt_default_is_unchanged_shape():
    # panel_already_open defaults to False → BYTE-IDENTICAL to the prior
    # full-CUA flow (the fail-open path), so #757-A hardening + its tests hold.
    a = prompts.make_prompt_audio_generate("long")
    b = prompts.make_prompt_audio_generate("long", panel_already_open=False)
    assert a == b, "the default (panel_already_open=False) prompt changed shape"
    assert "ALREADY DONE FOR YOU" not in a, (
        "the default prompt leaked the panel-already-open note"
    )
    assert "FINAL click" in a, "the default prompt lost the #757-A terminal Generate"


def test_generate_prompt_panel_open_variant_forbids_card_body_keeps_terminal():
    p = prompts.make_prompt_audio_generate("long", panel_already_open=True)
    assert "ALREADY DONE FOR YOU" in p and "panel is OPEN" in p, (
        "the panel-already-open variant lost its 'panel is open' framing"
    )
    low = p.lower()
    assert "do not" in low and "card body" in low, (
        "the panel-open variant no longer forbids re-clicking the card body "
        "(the open-step misclick that fires a duplicate)"
    )
    # The terminal Generate (steps 5-7) survive the injection.
    assert "FINAL click" in p and "STOP" in p, (
        "the panel-open variant dropped the terminal-Generate hardening"
    )


def test_run_phase3_dom_clicks_arrow_and_passes_panel_flag():
    src = _src(research.run_phase3_audio)
    assert "await _open_nlm_audio_customize(browser.page)" in src, (
        "run_phase3_audio no longer DOM-clicks the Customise arrow before Generate"
    )
    assert "panel_already_open=_panel_opened" in src, (
        "the generate prompt is no longer told the panel was DOM-opened"
    )


def test_customize_open_canary_is_gated_once_per_process():
    src = _src(research.run_phase3_audio)
    assert 'if "customize-open" not in _NLM_CANARY_STATE:' in src, (
        "the customize-open canary is no longer gated once-per-process — it "
        "would WARN on every healthy run"
    )
    assert '_dump_nlm_audio_dom(browser.page, "customize-open")' in src, (
        "the read-only customize-open canary dump is missing"
    )
    assert isinstance(research._NLM_CANARY_STATE, set), (
        "_NLM_CANARY_STATE must be a module-level set used as the canary gate"
    )


# ══ Part B — RESILIENT DOWNLOAD (pick the right card; never fail / delete) ════

def test_pick_helper_exists_async_and_read_only():
    assert inspect.iscoroutinefunction(research._pick_nlm_audio_card), (
        "_pick_nlm_audio_card must be an async read-only picker"
    )
    src = _src(research._pick_nlm_audio_card)
    low = src.lower()
    # Check for actual CALLS (the docstring contains the prose words "clicks"
    # and "deletes"); the picker is a pure page.evaluate read.
    for forbidden in (".click(", ".delete(", "agent_loop", ".press(", ".fill("):
        assert forbidden not in low, (
            f"_pick_nlm_audio_card uses {forbidden!r} — it MUST be read-only "
            f"(picking a card can never click or delete one)"
        )


def test_pick_helper_scopes_to_real_audio_markup():
    src = _src(research._pick_nlm_audio_card)
    assert "artifact-library-item" in src and "audio_magic_eraser" in src, (
        "the picker drifted off the repaired #767 audio-card markup"
    )


class _FakePage:
    def __init__(self, result):
        self._result = result

    async def evaluate(self, _js):
        return self._result


class _ThrowingPage:
    async def evaluate(self, _js):
        raise RuntimeError("boom")


def _cards(*specs):
    """specs: (isDeepDive, isBrief, generating) tuples → card dicts in DOM order."""
    out = []
    for i, (dd, brief, gen) in enumerate(specs):
        out.append({"ordinal": i + 1, "isDeepDive": dd, "isBrief": brief,
                    "generating": gen, "snippet": f"c{i+1}"})
    return {"count": len(out), "cards": out}


@pytest.mark.asyncio
async def test_pick_long_targets_last_complete_deep_dive():
    # The misclick default fires first (completes first) → the requested Long is
    # typically the LATER deep-dive card.
    page = _FakePage(_cards((True, False, False), (True, False, False)))
    res = await research._pick_nlm_audio_card(page, "long")
    assert res["target_ordinal"] == 2 and res["count"] == 2
    assert res["ambiguous"] is True, "two deep-dive cards must be flagged ambiguous"


@pytest.mark.asyncio
async def test_pick_short_targets_brief_card():
    # short → the Brief card (the non-deep-dive one), even if it's first.
    page = _FakePage(_cards((False, True, False), (True, False, False)))
    res = await research._pick_nlm_audio_card(page, "short")
    assert res["target_ordinal"] == 1, "short must pick the Brief (non-deep-dive) card"


@pytest.mark.asyncio
async def test_pick_prefers_complete_over_generating():
    # An in-flight (generating) deep-dive must not be chosen over a complete one.
    page = _FakePage(_cards((True, False, True), (True, False, False)))
    res = await research._pick_nlm_audio_card(page, "long")
    assert res["target_ordinal"] == 2 and res["complete"] is True


@pytest.mark.asyncio
async def test_pick_single_card_not_ambiguous():
    page = _FakePage(_cards((True, False, False)))
    res = await research._pick_nlm_audio_card(page, "long")
    assert res["target_ordinal"] == 1 and res["count"] == 1 and res["ambiguous"] is False


@pytest.mark.asyncio
async def test_pick_is_exception_safe():
    res = await research._pick_nlm_audio_card(_ThrowingPage(), "long")
    assert res["count"] == 0 and res["target_ordinal"] == 1, (
        "the picker must degrade safely (count 0, usable ordinal) on a DOM error"
    )


@pytest.mark.asyncio
async def test_pick_flags_all_generating_as_not_complete():
    # Cross-check hardening: if NO card is complete (a CUA-visual false-complete
    # broke the poll loop early), the picker must report complete=False so the
    # caller WARNs — it must never silently present an in-flight card as done.
    page = _FakePage(_cards((True, False, True), (True, False, True)))
    res = await research._pick_nlm_audio_card(page, "long")
    assert res["complete"] is False, "all-generating pool must be flagged not-complete"
    assert "all-generating" in res["reason"], "the all-generating reason tag is missing"


@pytest.mark.asyncio
async def test_pick_short_falls_back_to_non_deepdive_when_no_brief_label():
    # An unlabeled (neither Brief nor Deep Dive) card alongside a Deep Dive: for
    # short, the non-Deep-Dive card is the Brief target even without the literal
    # "Brief" label.
    page = _FakePage(_cards((True, False, False), (False, False, False)))
    res = await research._pick_nlm_audio_card(page, "short")
    assert res["target_ordinal"] == 2, "short must pick the non-deep-dive card as the Brief"


def test_download_prompt_default_omits_ordinal():
    base = prompts.make_prompt_audio_download("long")
    assert base == prompts.make_prompt_audio_download("long", target_ordinal=None), (
        "the default download prompt (no ordinal) changed shape"
    )
    assert "MULTIPLE AUDIO ENTRIES EXIST" not in base, (
        "the happy-path download prompt leaked the multi-entry ordinal note"
    )


def test_download_prompt_with_ordinal_targets_that_entry():
    p = prompts.make_prompt_audio_download("long", target_ordinal=2)
    assert "MULTIPLE AUDIO ENTRIES EXIST" in p and "#2" in p, (
        "the ordinal download prompt no longer restates the target entry #N"
    )
    assert "download ONLY entry" in p.lower() or "download only entry" in p.lower(), (
        "the ordinal prompt no longer constrains the download to that one entry"
    )


def test_run_phase3_wires_picker_into_download():
    src = _src(research.run_phase3_audio)
    assert "_pick_nlm_audio_card(browser.page, podcast_length)" in src, (
        "the resilient picker is no longer called before the download"
    )
    assert "target_ordinal=_target_ord" in src, (
        "the picked ordinal is no longer passed into the download prompt"
    )


# ══ Part C — BOUND accumulation + SKIP fix ════════════════════════════════════

def test_preflight_no_fail_phase_no_delete():
    src = _src(research.run_phase3_audio)
    # The dup fail_phase copy (the wedge) is gone; the active deleter stays
    # uncalled.
    for gone in ("Extra audio in your notebook", "Old audio in your notebook"):
        assert gone not in src, f"the pre-flight dup fail_phase ({gone!r}) is back"
    assert "await _cleanup_nlm_keep_requested_audio(" not in src, (
        "the auto-delete cleanup is called again — violates the no-delete rule"
    )


def test_retry_with_zero_cards_does_not_regenerate():
    src = _src(research.run_phase3_audio)
    assert "elif prefer_existing_audio:" in src and "NOT regenerating" in src, (
        "a prefer_existing_audio retry with 0 cards must NOT regenerate "
        "(download-only retry policy bounds accumulation)"
    )


def test_interruptible_sleep_accepts_skip_phase():
    sig = inspect.signature(research.PipelineControls.interruptible_sleep)
    assert "skip_phase" in sig.parameters, (
        "interruptible_sleep no longer accepts a skip_phase kwarg"
    )
    assert sig.parameters["skip_phase"].default is None, (
        "skip_phase must default to None so existing callers are unaffected"
    )


@pytest.mark.asyncio
async def test_interruptible_sleep_returns_skip_when_phase_skipped():
    ctrl = research.PipelineControls()
    ctrl.skipped_phases.add(3)
    res = await ctrl.interruptible_sleep(0.06, check_interval=0.01, skip_phase=3)
    assert res == "skip"


@pytest.mark.asyncio
async def test_interruptible_sleep_ignores_unrelated_phase_skip():
    ctrl = research.PipelineControls()
    ctrl.skipped_phases.add(2)  # a different phase
    res = await ctrl.interruptible_sleep(0.03, check_interval=0.01, skip_phase=3)
    assert res is None


@pytest.mark.asyncio
async def test_interruptible_sleep_default_has_no_skip_behavior():
    ctrl = research.PipelineControls()
    ctrl.skipped_phases.add(3)
    res = await ctrl.interruptible_sleep(0.03, check_interval=0.01)
    assert res is None, "without skip_phase the helper must never return 'skip'"


def test_no_audio_loop_honors_skip_phase_3():
    # The no-audio auto-retry loop lives in the orchestrator (run_pipeline),
    # not in run_phase3_audio.
    src = _src(research.run_pipeline)
    assert "if 3 in _controls.skipped_phases:" in src, (
        "the no-audio retry loop top no longer honors a user SKIP_PHASE(3)"
    )
    assert "skip_phase=3" in src, (
        "the no-audio retry 5-min wait no longer passes skip_phase=3 — a Skip "
        "click would be ignored until the wait elapses (the user's 'skip "
        "didn't work')"
    )
