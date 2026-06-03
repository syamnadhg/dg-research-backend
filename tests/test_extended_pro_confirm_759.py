"""#759 — ChatGPT post-select Extended-Pro DOM confirm (FAIL-OPEN).

Phase 1 used to infer Pro + Extended Thinking success purely from the CUA
selector's prose ("no 'no pro' in the verdict"). If ChatGPT silently reverted to
Instant/Auto — or never applied Extended Thinking — the brief was generated on a
far shallower model with no signal. #759 adds a read-only DOM cross-check after
the selector: _chatgpt_extended_pro_confirm(page) -> extended|pro|downgrade|unsure.

Hard requirement: FAIL-OPEN. Only a CONFIRMED downgrade (a non-Pro thinking mode
active AND no Pro/Extended marker) triggers ONE silent selector re-run. It must
NEVER raise a pro_required card / pause / badge — this is a quality knob like
Claude's Effort/Thinking, WARN-only. extended/pro/unsure all proceed silently.

The confirm also runs ONLY when the selector CLAIMED Pro (_pro_select_claimed),
never on a user-opted-Free path, and excludes open-menu/overlay descendants so a
model picker listing 'Instant'/'Pro' OPTIONS can't be misread as the active mode.

Source-inspection guards (the call site lives inline in the large run_phase1
coroutine; the helper is a standalone async def), matching the suite convention.

Run:  pytest tests/test_extended_pro_confirm_759.py -v
"""
import inspect

import research


def _confirm_src():
    return inspect.getsource(research._chatgpt_extended_pro_confirm)


def _phase1_src():
    return inspect.getsource(research.run_phase1)


def _call_block():
    # The #759 confirm block: from its marker comment to "Attach PDFs".
    src = _phase1_src()
    return src.split("post-select DOM confirm that Pro + Extended Thinking", 1)[1].split(
        "# Attach PDFs", 1)[0]


# ── The helper ────────────────────────────────────────────────────────────────

def test_helper_exists_and_is_async():
    assert inspect.iscoroutinefunction(research._chatgpt_extended_pro_confirm), (
        "_chatgpt_extended_pro_confirm must be an async read-only DOM probe"
    )


def test_helper_returns_the_four_verdicts():
    src = _confirm_src()
    for verdict in ('"extended"', '"pro"', '"downgrade"', '"unsure"'):
        assert f"return {verdict}" in src, (
            f"_chatgpt_extended_pro_confirm no longer returns {verdict}"
        )


def test_helper_excludes_open_menu_overlays():
    # An open model picker listing Instant/Pro/Auto OPTIONS must not be read as
    # the active mode — overlays are excluded.
    src = _confirm_src()
    assert "inOverlay" in src and 'role="menu"' in src and 'role="listbox"' in src, (
        "the helper no longer excludes menu/listbox/dialog overlays — an open "
        "picker's option list can be misread as the active mode"
    )


def test_helper_is_fail_open_never_raises():
    # Both the DOM-read failure and the non-dict result must degrade to 'unsure'
    # (fail-open), never propagate an exception.
    src = _confirm_src()
    assert 'return "unsure"' in src
    assert "except Exception" in src, "the helper's DOM read is no longer guarded"


def test_helper_extended_and_pro_win_over_downgrade():
    # Order matters: an Extended/Pro marker returns before the downgrade branch,
    # so a Pro account is never flagged as a downgrade.
    src = _confirm_src()
    i_ext = src.find('return "extended"')
    i_pro = src.find('return "pro"')
    i_down = src.find('return "downgrade"')
    assert -1 < i_ext < i_down and -1 < i_pro < i_down, (
        "the downgrade branch now precedes extended/pro — a Pro/Extended state "
        "could be misclassified as a downgrade"
    )


# ── The call site ─────────────────────────────────────────────────────────────

def test_confirm_gated_on_claimed_pro_and_cua():
    block_pre = _phase1_src().split("post-select DOM confirm", 1)[0]
    # The flag is initialized and set on the Pro-claimed break.
    assert "_pro_select_claimed = False" in block_pre
    assert "_pro_select_claimed = True" in block_pre, (
        "the Pro-claimed flag is no longer set on the successful-select break"
    )
    block = _call_block()
    assert "if cua_client and _pro_select_claimed:" in block, (
        "the confirm no longer gates on (cua_client AND claimed-Pro) — it could "
        "run on a user-opted-Free path"
    )


def test_only_downgrade_triggers_one_silent_rerun():
    block = _call_block()
    assert 'if _epc == "downgrade":' in block, (
        "the re-run is no longer gated strictly on a confirmed downgrade"
    )
    # Exactly one selector re-run (PROMPT_SELECT_PRO), bounded by wait_for — not a loop.
    assert "PROMPT_SELECT_PRO" in block and "asyncio.wait_for(" in block
    assert block.count("agent_loop(") == 1, (
        "the downgrade re-run is not a single bounded selector run (expected "
        "exactly one agent_loop call in the confirm block)"
    )
    assert "while " not in block, (
        "the downgrade re-run introduced a while-loop — it must be a single re-run"
    )


def test_confirm_is_fail_open_no_card_or_pause():
    # The whole block must be WARN-only: no pro_required card, no pause, no
    # fail_phase/fail_agent — a downgrade is a quality knob, not a hard stop.
    block = _call_block()
    for forbidden in ("fail_phase", "fail_agent", "request_pause",
                      "pro_required", "_emit_pro_required_alert"):
        assert forbidden not in block, (
            f"the #759 confirm block calls {forbidden!r} — it must be fail-open "
            f"(WARN-only), never escalate a downgrade to a card/pause/badge"
        )
