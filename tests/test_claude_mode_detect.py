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

    ⚠ Scoped to the candidate list the family read draws from. The whole-constant
    read would also be satisfied by any other visibility filter in the file,
    which is exactly how the previous version of this test went vacuous.

    ⚠ RE-ANCHORED 2026-08-17. The detector now KEEPS the winning button instead
    of answering yes/no from a `.some(...)`, because the trigger's own label
    carries the effort as well as the family. The filter therefore moved from the
    `hasExtended` expression onto the `btns` list it selects from — the property
    is unchanged, its home is not, and a pin on the old location would have gone
    green against a detector that had stopped filtering."""
    clause = DETECTOR[DETECTOR.index("const btns"):DETECTOR.index("const hasExtended")]
    assert "b.getClientRects().length > 0" in clause, (
        "the family read must be restricted to visible buttons"
    )
    assert '!b.closest(\'[role="menu"]' in clause, (
        "and must still exclude options rendered inside an open popover"
    )


def test_detector_excludes_upsell_chips():
    """With the version comparison gone, the family word alone decides — so a
    chip that merely NAMES the family ("Upgrade to Opus", "Try Opus") would read
    as the model being selected on a free account."""
    assert "upsellRe" in DETECTOR and "!upsellRe.test(t)" in DETECTOR, (
        "an upsell chip names the family without being evidence it is selected"
    )


def test_the_detector_reports_all_THREE_halves():
    """The ladder probe requires every knob the rung it can skip would have
    checked. The CUA validator looks at the model, the Research tool AND the
    effort tier, so a probe answering from fewer drops one of them silently.

    ⚠ RE-ANCHORED 2026-08-17: effort was the missing third. Its absence is why a
    run could log `select_effort_tier: missed` and, one line later, `outcome
    satisfied at 'builtin' — skipping vision_cua, cua_validate`.
    """
    assert "return { hasExtended, researchOn, effortOk };" in DETECTOR


def _detect(trigger_label, *, elsewhere=(), effort_word="max", fam="opus"):
    """Run the real detector against a composer, through the node shim."""
    from _domshim import el, run_js
    kids = [el("button", {"data-testid": "model-selector-dropdown",
                          "aria-label": f"Model: {trigger_label}"}, trigger_label)]
    kids.extend(el("div", {}, t) for t in elsewhere)
    return run_js(el("body", {}, kids=kids), DETECTOR,
                  {"fam": fam, "effortWord": effort_word,
                   "trigTestid": "model-selector-dropdown"})["ret"]


def test_the_effort_is_read_off_the_TRIGGER_and_nowhere_else():
    """⛔⛔ This account's PLAN CHIP also says "Max". A page-wide scan for the word
    would report effort-is-set on every page — worse than not reading it at all,
    because it re-arms the exact false confirmation the third term was added to
    prevent, while looking like a working check.

    ⚠ REWRITTEN after a mutation survivor. The first version asserted that
    `document.querySelectorAll` did NOT appear in the clause — and the mutant
    reached for `document.body.innerText` instead, so the guard never fired. A
    blocklist of ways to read the page cannot be complete; running the detector
    against a page that HAS the decoy can.
    """
    out = _detect("Opus 5", elsewhere=["Max", "Your plan: Max", "Max effort"])
    assert out["hasExtended"] is True, "the family is still on the trigger"
    assert out["effortOk"] is False, (
        "the effort was read from somewhere other than the trigger"
    )


def test_the_effort_reads_true_when_the_TRIGGER_carries_it():
    out = _detect("Opus 5 Max")
    assert out["hasExtended"] is True and out["effortOk"] is True


def test_a_missing_trigger_cannot_report_an_effort():
    # No family, no trigger, so nothing to read the tier off — and the answer must
    # be False rather than inherited from the page.
    out = _detect("Sonnet 5 Max", fam="opus", elsewhere=["Max"])
    assert out["hasExtended"] is False
    assert out["effortOk"] is False


def test_an_upsell_chip_naming_the_family_is_not_a_trigger():
    # The test id is a NAME, not evidence of the family — so the word is still
    # demanded, and an upsell still disqualifies.
    out = _detect("Upgrade to Opus", elsewhere=["Max"])
    assert out["hasExtended"] is False
    assert out["effortOk"] is False


def test_no_effort_word_configured_reports_False_rather_than_guessing():
    out = _detect("Opus 5 Max", effort_word="")
    assert out["hasExtended"] is True
    assert out["effortOk"] is False


def test_a_trailing_ICON_GLYPH_cannot_make_an_empty_word_read_as_set():
    """⛔ What the `&& ew` guard on the effort read is actually for.

    The live trigger ends in a chevron ICON — the capture shows an icon span
    inside the button, and icon fonts render into the Unicode private-use area.
    A trailing non-alphanumeric makes the token split emit an EMPTY token, and
    `indexOf('')` finds it. Without the guard, an unconfigured effort word would
    read as a SET tier: a false confirmation, and the one direction this term
    must never fail in.

    ⚠ HONEST HISTORY, because the first version of this comment overclaimed. A
    `.filter(Boolean)` was added here as a "fix" and announced as a real bug
    found by mutation. It was not a bug: the guard already covered it, and the
    two were redundant — which is exactly why NEITHER could be killed while the
    other stood. Measured: the false reading needs BOTH removed. The filter is
    gone and this test pins the remaining guard.
    """
    out = _detect("Opus 5 ", effort_word="")
    assert out["hasExtended"] is True, "the family is still readable"
    assert out["effortOk"] is False, (
        "an unconfigured effort word must never read as a set tier"
    )


def test_the_glyph_does_not_break_a_REAL_effort_word_either():
    # The control: stripping the empty token must not cost a genuine match.
    out = _detect("Opus 5 Max ", effort_word="max")
    assert out["effortOk"] is True


def test_the_effort_term_is_reported_not_self_gated():
    """One detector, two policies. The PRE-SEND check must not gate on effort —
    doing so re-runs the whole Claude setup, model popover and all, seconds
    before the brief is submitted — while the setup LADDER must. So the script
    reports the term and each caller decides."""
    import inspect
    src = inspect.getsource(research)
    ladder = src[src.index("async def _dr_outcome_state"):]
    ladder = ladder[:ladder.index("async def _run_intent_ladder")]
    assert 'st.get("effortOk")' in ladder, "the ladder must require the effort term"

    presend = src.index("Claude mode regressed before send")
    window = src[presend - 1200:presend]
    assert "effortOk" not in window, (
        "the pre-send gate must NOT require effort — see the note in the detector"
    )
