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
