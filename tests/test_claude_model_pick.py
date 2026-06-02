"""#708 — Claude Step 1B model-pick never downgrades to Opus 4.7.

Two prod runs (backend.log 48681/49653) had setup_claude_dr select
"Opus 4.7 Extra" instead of "Opus 4.8 Max" because (1) the model-selector
trigger button (which shows the CURRENT model) was a candidate and (2) the
4.8 menu item hadn't rendered when the old "any Opus 4.x" priority ran.

The hardened Step 1B must: scope candidates to the open popover, version-gate
to Opus >= 4.8 (never downgrade), and poll for the option. Source-inspection
guards (the JS runs in a live page; no live browser in unit tests).
"""
import inspect

import research


def test_step1b_version_gates_to_4_8_or_higher():
    src = inspect.getsource(research.setup_claude_dr)
    # The numeric guard that forbids picking sub-4.8 Opus must be present.
    assert "< 4.8" in src, (
        "Step 1B must version-gate candidates to Opus >= 4.8 so it never "
        "silently selects Opus 4.7 (#708)."
    )
    # Version is parsed from the option text, not a brittle '4.8' substring,
    # so a future Opus 4.9/5 is still picked as the strongest.
    assert "verOf" in src, "Step 1B should parse the Opus version, not substring-match."


def test_step1b_scopes_to_open_popover_excluding_trigger():
    src = inspect.getsource(research.setup_claude_dr)
    assert '[role="menu"], [role="listbox"], [role="dialog"]' in src, (
        "Step 1B must scope candidates to the OPEN popover so the model-"
        "selector trigger button (which shows the current model) is excluded."
    )


def test_step1b_polls_for_the_option():
    src = inspect.getsource(research.setup_claude_dr)
    assert "_pick_opus_js" in src and "for _attempt in range(8)" in src, (
        "Step 1B must poll for the 4.8 option to render rather than reading the "
        "dropdown once at a fixed 0.8s mark (#708)."
    )


def test_step1b_no_legacy_any_opus_4x_fallback():
    """The old 'any Opus 4.x' / 'any Opus at all' fallbacks are what grabbed
    the trigger's 4.7 — they must be gone."""
    src = inspect.getsource(research.setup_claude_dr)
    assert "Priority 3: any Opus at all" not in src, (
        "the unconditional 'any Opus' fallback must be removed — it could "
        "select Opus 4.7 (#708)."
    )


# ── #744 — re-click loop / P2-stuck fixes ─────────────────────────────


def test_step1_skips_dropdown_when_model_already_4_8():
    """#744: setup_claude_dr must read the model-selector TRIGGER first and
    SKIP opening the dropdown when the model is already Opus >= 4.8. Opening it
    unconditionally was the re-click loop that wedged P2 (the picker couldn't
    see the already-selected option, returned False, and left the dropdown open)."""
    src = inspect.getsource(research.setup_claude_dr)
    assert "model_trigger_ver" in src, (
        "Step 1 must read the model-selector trigger version before deciding "
        "whether to open the dropdown (#744)."
    )
    assert "model_trigger_ver >= 4.8" in src and "skipping model dropdown" in src, (
        "when the trigger already shows Opus >= 4.8, Step 1 must skip the "
        "dropdown entirely (#744)."
    )


def test_step1b_escapes_before_bailing():
    """#744: a Step 1B miss must dismiss the OPEN popover (Escape) before
    returning False — never strand an open dropdown over the composer."""
    src = inspect.getsource(research.setup_claude_dr)
    # The fail path between the FAIL log and `return False` must press Escape.
    fail_idx = src.find("Step 1B FAIL")
    assert fail_idx != -1
    tail = src[fail_idx:fail_idx + 700]
    assert 'press("Escape")' in tail and "return False" in tail, (
        "Step 1B FAIL must Escape the dropdown before `return False` (#744)."
    )


def test_step1b_selector_handles_menuitemradio_and_fixed_popover():
    """#744: the option picker must see role=menuitemradio/div options (the
    #709 lesson) and use getClientRects() so a fixed-position popover (whose
    offsetParent is null) is not filtered out."""
    src = inspect.getsource(research.setup_claude_dr)
    assert "menuitemradio" in src, (
        "the picker must include role=menuitemradio options (#744)."
    )
    assert "getClientRects()" in src, (
        "the picker/trigger-read must use getClientRects() for visibility so "
        "fixed-position popovers aren't filtered by offsetParent (#744)."
    )
