"""#755 — the [2D] Start-research wait: Stop-aware, and it presses only Start.

⛔⛔ WAVE 15 (10-02): THE PLAN RE-DRAFT THIS FILE WAS WRITTEN FOR IS GONE. #755
(2026-06-02) taught the [2D] loop to press Gemini's Regenerate/Redo on a failed
plan, bounded at three with a cooldown; on 09-10 that was rewired to
`_gemini_redraft_plan`. Gemini now starts its research by itself on a timer, and
the owner: "wait for the research without refreshing and then let the research
finish … keep it simple without making it complicated and causing alerts". So
the loop presses no Redo at all; the bound, the cooldown and the cap's one-time
notice went with the re-draft, and so did their tests
(tests/test_w15_gemini_waits_1002.py measures the wait as it is now).

What stays true, and is pinned here: the wait honours Stop and Pause; the only
thing it presses is the vetted 'Start research' finder; and after a Stop the
verify is skipped.

These are source-inspection guards (the loop lives inline in the large
run_phase2 coroutine), read with comments BLANKED where they are about code.

Run:  pytest tests/test_gemini_plan_regen_755.py -v
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research  # noqa: E402
from conftest import code_only  # noqa: E402

#: The wait's own boundaries: the start of the loop's state and the verify after it.
_LOOP_FROM = "        start_clicked = False\n"
_LOOP_TO = "        # Verify Gemini is actually researching."


def _phase2_src():
    return inspect.getsource(research.run_phase2)


def _2d_loop_code():
    """The [2D] plan wait, from its init to the verify after it, with `#`
    comments blanked (in place, so offsets stay valid)."""
    raw = _phase2_src()
    assert raw.count(_LOOP_FROM) == 1 and raw.count(_LOOP_TO) == 1, "the wait moved"
    i = raw.index(_LOOP_FROM)
    j = raw.index(_LOOP_TO, i)
    return code_only(raw)[i:j]


def test_loop_is_stop_and_pause_aware():
    loop = _2d_loop_code()
    assert "if _controls.is_stop():\n" in loop, (
        "the [2D] plan-wait loop no longer honors Stop — a 10-min wait must be "
        "stop-aware so the user can cancel")
    assert "if _controls.is_pause():\n" in loop and "await _controls.wait_if_paused()" in loop


def test_the_only_press_is_the_vetted_start_research_finder():
    """No Redo, no Stop, no blind click: the loop presses through the module's
    one vetted 'Start research' finder and nothing else."""
    loop = _2d_loop_code()
    assert loop.count("b.click()") == 0
    assert "_gemini_redraft_plan(" not in loop, "the wait re-drafts a plan again"
    assert "_shadow_observed_cua(" not in loop and "agent_loop(" not in loop, (
        "computer use is pointed at Gemini's plan again")
    assert "evaluate(_click_start_js)" in loop
    assert research._GEMINI_CLICK_START_JS.count("b.click()") == 1


def test_post_loop_skips_verify_on_stop():
    """After the loop, a Stop skips the ~45s DOM-verify churn."""
    raw = _phase2_src()
    i = raw.index(_LOOP_TO)
    post = code_only(raw)[i:raw.index("# ── Verify all launched agents", i)]
    assert "elif _controls.is_stop():\n" in post and "verified_b = False" in post
