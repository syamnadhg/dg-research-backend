"""#708 — ensure_deep_mode_active no longer false-fires a re-activation.

The pre-send "is Claude still in the right mode?" check scanned the page body
for the literal word "extended". The 2026-05-28 claude.ai UI dropped that word
(the model button reads "Opus 5 Max"; Adaptive is a "Thinking" toggle), so the
scan was ALWAYS false and triggered a needless setup_claude_dr re-run on EVERY
Claude send (backend.log 49728) — one of the "opens the model selector multiple
times" symptoms. The detector must read the model-selector button instead.

Rewritten 2026-08-01: it read the button's VERSION and compared it to a policy
floor. That is the same class of bug one level down — a pre-send gate keyed on a
number treats a platform rollback, an A-B bucket, or a version-less label as
"mode regressed", and the re-setup it triggers opens the model popover seconds
before the brief is sent. It now reads the FAMILY word, which cannot age out.

Re-pointed 2026-08-03 (Wave 4): the detector was hoisted out of the function
into `_CLAUDE_MODE_STATE_JS` so the setup ladder's outcome probe can read the
SAME one instead of re-typing it. These guards follow it — and one of them had
to, for a reason worth recording: the old visible-buttons test sliced the
function source from `_claude_state_js` to the next `\"\"\"` and, once the JS was
no longer inline, that slice ran on past the detector into the #744 diagnostic
dump, which happens to contain the same `getClientRects()` idiom. It kept
passing while testing nothing.
"""
import research
from conftest import code_only_deep, js_code_only

DETECTOR = js_code_only(research._CLAUDE_MODE_STATE_JS)


def test_the_detector_is_one_constant_with_the_ladder_probe():
    """The pre-send check and the ladder probe must read the same text. Two
    copies of a detector is how the ChatGPT Step-3 verify drifted away from the
    shared composer detector and started failing runs that had succeeded."""
    caller = code_only_deep(research.ensure_deep_mode_active)
    assert "_claude_state_js = _CLAUDE_MODE_STATE_JS" in caller
    assert "_CLAUDE_MODE_STATE_JS" in code_only_deep(research._dr_outcome_state)


def test_detector_reads_the_model_button_not_a_body_scan():
    assert "txt.includes('extended')" not in DETECTOR, (
        "the detector must NOT read the model via a body-wide 'extended' text "
        "scan — the UI dropped that word (#708)."
    )
    assert "famRe.test(t)" in DETECTOR, (
        "the high-tier-model check must test the model button for the family word"
    )
    # ⭐ `_p2_active_family` IS the central policy read — it returns
    # `p2_family(platform)` unless THIS RUN proved the account's plan excludes
    # that family, in which case it returns the policy's own fallback word. What
    # this assertion exists to forbid is a LITERAL, and it still does; asking for
    # the un-scoped reader by name would instead force the one shape that reads
    # "mode regressed" on every pass of a correct fallback run.
    assert "_p2_active_family" in code_only_deep(research.ensure_deep_mode_active), (
        "the family word must come from the central P2_MODEL_POLICY"
    )


def test_detector_does_not_compare_a_version():
    """⭐ The pre-send gate is the WORST place for a version comparison: its
    failure mode is a full re-setup, which opens the model popover with a live
    composer underneath."""
    for banned in (">= floor", "< floor", "p2_floor", "verOf"):
        assert banned not in DETECTOR, (
            f"{banned!r} is a version comparison in the pre-send gate — a "
            f"rollback or a version-less label would read as 'mode regressed'"
        )


def test_detector_excludes_open_dropdown_options():
    """Review blocker: a stale option inside an OPEN dropdown (while a different
    model is current) must not false-positive the high-tier check. The scan must
    exclude buttons inside an open menu/listbox/dialog popover."""
    assert ".closest('[role=\"menu\"], [role=\"listbox\"], [role=\"dialog\"]')" in DETECTOR, (
        "the high-tier-model check must exclude options rendered inside an open "
        "popover so a stale menu item can't false-positive (#708 review)."
    )


def test_detector_only_reads_visible_buttons():
    """The version check that used to sit here made a hidden element harmless —
    it needed a NUMBER too. The family word alone does not, so an off-screen or
    display:none marketing chip on a Sonnet account would now pass the gate and
    the run would go out in chat mode believing the model was right.

    ⚠ Scoped to the `hasExtended` clause. The whole-constant read would also be
    satisfied by any other visibility filter in the file, which is exactly how
    the previous version of this test went vacuous."""
    clause = DETECTOR[DETECTOR.index("const hasExtended"):DETECTOR.index("const researchOn")]
    assert "b.getClientRects().length > 0" in clause, (
        "the family read must be restricted to visible buttons"
    )


def test_detector_excludes_upsell_chips():
    """With the version comparison gone, the family word alone decides — so a
    chip that merely NAMES the family ("Upgrade to Opus", "Try Opus") would read
    as the model being selected on a free account."""
    assert "upsellRe" in DETECTOR and "!upsellRe.test(t)" in DETECTOR, (
        "an upsell chip names the family without being evidence it is selected"
    )


def test_the_detector_still_reports_both_halves():
    """The ladder probe requires BOTH — the rung it can skip (the CUA validator)
    checks the model and the Research tool, so a probe that answered from one
    would drop the other half of a surface doing two jobs."""
    assert "return { hasExtended, researchOn };" in DETECTOR
