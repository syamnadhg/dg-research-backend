"""Vision engine fixes (2026-06-23) — from the shadow-data verdict that Vision
was unreliable: a pixel-vs-ratio coordinate bug, an 8s timeout that mostly
TimeoutError'd, edge-guessing on low confidence, and thin per-hotspot context.

These guard the engine-level fixes:
  - _norm_ratio recovers raw-pixel coords into 0–1 ratios + clamps,
  - _parse_response applies it (the x_ratio=1238 → 0.967 recovery),
  - the per-call timeout is raised off the too-tight 8s,
  - the system prompt tells the model to escalate instead of edge-guessing,
  - research.py ships per-hotspot vision hints wired into the shadow flow_ctx.
"""
import inspect
import types

import vision


def test_norm_ratio_recovers_pixels_to_ratio():
    # The observed bug: model returns 1238 (pixels) on a 1280px viewport.
    assert abs(vision._norm_ratio(1238.0, 1280) - 0.9672) < 0.001
    assert abs(vision._norm_ratio(40.0, 800) - 0.05) < 0.001


def test_norm_ratio_passthrough_clamp_and_none():
    assert vision._norm_ratio(0.5, 1280) == 0.5          # normal ratio untouched
    assert vision._norm_ratio(0.0, 1280) == 0.0
    assert vision._norm_ratio(1.0, 1280) == 1.0
    assert vision._norm_ratio(1.2, 1280) == 1.0          # slight overshoot → clamp
    assert vision._norm_ratio(-0.1, 1280) == 0.0         # negative → clamp
    assert vision._norm_ratio(None, 1280) is None        # missing stays missing
    # No viewport dim known → can't divide; just clamp.
    assert vision._norm_ratio(1238.0, 0) == 1.0
    # Non-finite must NOT slip past the clamps (NaN beats every comparison) and
    # reach page.mouse.click(nan,nan) — they become a clean None.
    assert vision._norm_ratio(float("nan"), 1280) is None
    assert vision._norm_ratio(float("inf"), 1280) is None
    assert vision._norm_ratio(float("-inf"), 1280) is None


def _mock_resp(inp):
    block = types.SimpleNamespace(type="tool_use", name="propose_action", input=inp)
    usage = types.SimpleNamespace(input_tokens=11, output_tokens=22)
    return types.SimpleNamespace(content=[block], usage=usage)


def test_parse_response_normalizes_pixel_coords():
    vc = vision.VisionClient(api_key="test-key")  # no network at construction
    meta = vision.ImgMeta(width_css=1280, height_css=800, dpr=1.0, captured_at=0.0)
    res = vc._parse_response(
        _mock_resp({
            "action": "click", "x_ratio": 1238.0, "y_ratio": 40.0,
            "confidence": 0.8, "reason": "click the more-options button",
            "next_expected_state": "panel open",
        }),
        vision.MODEL_SONNET, 100.0, meta,
    )
    assert res.action == "click"
    assert abs(res.x_ratio - 0.9672) < 0.001   # 1238/1280 — the right-edge target
    assert abs(res.y_ratio - 0.05) < 0.001     # 40/800
    assert res.low_confidence is False         # 0.8 >= 0.6


def test_parse_response_no_tooluse_does_not_record():
    # Review [6]: the no-tool_use parse path must be side-effect-free (ask()'s
    # success branch records once). Previously it called self._failure which
    # ALSO recorded → the schema-invalid response double-burned the budget.
    vc = vision.VisionClient(api_key="test-key")
    empty = types.SimpleNamespace(content=[], usage=types.SimpleNamespace(
        input_tokens=5, output_tokens=0))
    res = vc._parse_response(empty, vision.MODEL_SONNET, 50.0, None)
    assert res.action == "declare_failure"
    assert "did not return" in res.reason
    assert vc.metrics.call_count == 0  # parse path recorded nothing


def test_failure_records_once():
    # The recording wrapper still records (used by ask()'s except paths).
    vc = vision.VisionClient(api_key="test-key")
    vc._failure("boom", vision.MODEL_SONNET, 10.0)
    assert vc.metrics.call_count == 1


def test_default_timeout_raised_off_8s():
    # 8s was too tight (CUA fallback takes 20–30s); the raise prevents the
    # timeout-dominated shadow telemetry.
    assert vision.DEFAULT_TIMEOUT_S >= 15.0


def test_system_prompt_prefers_escalation_over_edge_guess():
    sp = vision._SYSTEM_PROMPT
    assert "escalate_to_cua" in sp
    assert "pixel" in sp.lower()                # reinforces ratios-not-pixels
    # Tells the model to escalate rather than guess at the edge.
    assert "do NOT" in sp or "do not" in sp


def test_research_ships_per_hotspot_vision_hints():
    import research
    hints = research._HOTSPOT_VISION_HINTS
    for hid in ("7c-p1", "7c", "7d", "p2-share"):
        assert hid in hints, f"missing vision hint for hotspot {hid}"
        assert hints[hid].get("context_hint")
        assert isinstance(hints[hid].get("success_signals"), list)


def test_shadow_flow_ctx_uses_hints():
    import research
    src = inspect.getsource(research._shadow_observed_cua)
    assert "_HOTSPOT_VISION_HINTS" in src
    assert "success_signals" in src
