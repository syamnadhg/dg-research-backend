"""#705 — vision VERDICT retries escalate to the heavy model (Opus 4.8).

Auto-retry should use the most powerful model for vision verdicts (login/tier
reads) — a stronger reader is worth it on a hard second look. The computer-use
loop stays on Sonnet 4.6 (Anthropic's recommended Computer Use model); only the
vision verdict escalates. Source-inspection guards (these call cua_client
directly; no live client in unit tests).
"""
import inspect

import research


def test_login_call_selects_heavy_model_when_heavy():
    src = inspect.getsource(research._cua_login_call)
    assert "VISION_HEAVY_MODEL if heavy" in src, (
        "_cua_login_call must select VISION_HEAVY_MODEL when heavy=True (#705)."
    )


def test_pro_tier_call_can_select_heavy_model():
    src = inspect.getsource(research._cua_pro_tier_call)
    assert "VISION_HEAVY_MODEL if heavy" in src, (
        "_cua_pro_tier_call must be able to select VISION_HEAVY_MODEL when "
        "heavy=True (param wired for future retry escalation) (#705)."
    )


def test_verify_login_retry_escalates_to_heavy_first_strike_stays_light():
    src = inspect.getsource(research.verify_login_cua)
    assert "heavy=True" in src, (
        "verify_login_cua's retry pass must call _cua_login_call(..., heavy=True)."
    )
    # Two _cua_login_call invocations (first strike + retry); only the retry
    # escalates — so exactly ONE heavy=True.
    assert src.count("heavy=True") == 1, (
        "only the RETRY pass escalates to the heavy model; the first strike "
        "must stay on the light model (#705)."
    )
    assert src.count("_cua_login_call(") == 2, (
        "verify_login_cua should make exactly two login-verdict calls "
        "(first strike + one retry)."
    )
