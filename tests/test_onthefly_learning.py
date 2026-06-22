"""Phoenix (model_refresh) revised Phase D — ON-THE-FLY learning (no weekly cron).

User steering 2026-06-22: the weekly canary was dropped because the runtime
already adapts every run. Instead, a verified run records the selected model as
the known-good fallback target, folded into the normal run path. The recording
ALGORITHM (record_known_good) is unit-tested in test_model_policy.py; these are
source-inspection guards that the wiring is correct and pure-side-channel.
"""
import inspect

import research


def test_setup_records_selected_model_version():
    sc = inspect.getsource(research.setup_claude_dr)
    sg = inspect.getsource(research._gemini_select_flash_model)
    assert '_P2_PICKED_VERSION["claude"]' in sc
    assert '_P2_PICKED_VERSION["gemini"]' in sg


def test_caller_records_known_good_only_on_verified_run():
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    rec = src.find("record_known_good(platform_l, _P2_PICKED_VERSION.get(platform_l))")
    assert rec != -1, "the caller must record the verified model as known-good."
    # It must sit inside the `if research_ok …` block (only record a PROVEN
    # model), never on the failure/Skip path.
    guard = src.rfind('if research_ok and platform_l in ("claude", "gemini")', 0, rec)
    assert guard != -1, "record_known_good must be gated on research_ok (a verified run)."


def test_no_weekly_cron_or_canary_loop_exists():
    # The weekly cadence was intentionally dropped for on-the-fly learning.
    src = inspect.getsource(research)
    assert "_model_refresh_weekly_loop" not in src, (
        "there must be NO weekly canary loop — learning is folded into real runs."
    )


def test_record_known_good_is_pure_side_channel():
    # The recorder lives in models.py and is the only writer; the caller never
    # gates the run on its result.
    assert hasattr(research, "record_known_good")
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    # The call is a bare statement (its return value is not used in a condition).
    for line in src.splitlines():
        if "record_known_good(" in line:
            assert "if " not in line and "=" not in line.split("record_known_good")[0], (
                "record_known_good must be a fire-and-forget side effect, not gating."
            )
