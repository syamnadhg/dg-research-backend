"""#708 — ensure_deep_mode_active no longer false-fires a re-activation.

The pre-send "is Claude still in the right mode?" check scanned the page body
for the literal word "extended". The 2026-05-28 claude.ai UI dropped that word
(the model button reads "Opus 4.8 Max"; Adaptive is a "Thinking" toggle), so
the scan was ALWAYS false and triggered a needless setup_claude_dr re-run on
EVERY Claude send (backend.log 49728) — one of the "opens the model selector
multiple times" symptoms. The detector must read the model-selector button's
Opus version instead. Source-inspection guard.
"""
import inspect

import research


def test_extended_detector_reads_model_button_not_body_extended():
    src = inspect.getsource(research.ensure_deep_mode_active)
    # The brittle body-wide "extended" scan must be gone.
    assert "txt.includes('extended')" not in src, (
        "ensure_deep_mode_active must NOT detect the model via a body-wide "
        "'extended' text scan — the UI dropped that word (#708)."
    )
    # It must read the model-selector button's Opus version (>= 4.8).
    assert "verOf" in src and ">= 4.8" in src, (
        "the high-tier-model check must parse the model button's Opus version "
        "and treat >= 4.8 as active (#708)."
    )


def test_extended_detector_excludes_open_dropdown_options():
    """Review blocker: a stale 'Opus 4.8' option inside an OPEN dropdown (while
    the current model is 4.7) must not false-positive the high-tier check. The
    scan must exclude buttons inside an open menu/listbox/dialog popover."""
    src = inspect.getsource(research.ensure_deep_mode_active)
    assert ".closest('[role=\"menu\"], [role=\"listbox\"], [role=\"dialog\"]')" in src, (
        "the high-tier-model check must exclude Opus options rendered inside an "
        "open popover so a stale menu item can't false-positive (#708 review)."
    )
