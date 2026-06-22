"""Phoenix (model_refresh) Phase A — P2 model POLICY single-source-of-truth.

These guard the behavior-identical foundation: the central P2_MODEL_POLICY +
accessors must reproduce today's values EXACTLY (so routing the scattered
literals through them changes nothing), and the runtime overlay must be a safe
no-op until the kill-switch is armed and can never break selection.

Dep-free: imports only `models` (no research.py / playwright).
"""
import json

import models


# The CUA directive that was previously duplicated byte-for-byte at
# research.py:18555 (2C-retry) and :26894 (2B main). p2_claude_setup_directive()
# MUST reproduce it exactly so de-duplicating the two call sites is a no-op.
_LEGACY_CLAUDE_DIRECTIVE = (
    "Select Opus 4.8 + Max effort + Adaptive Thinking + Research tool "
    "(if Opus 4.8 isn't offered, pick the highest Opus available — never "
    "downgrade to 4.7 when 4.8 exists). Do NOT type — just set up and focus "
    "input. Say 'ready for paste'."
)


def test_claude_setup_directive_byte_identical():
    assert models.p2_claude_setup_directive() == _LEGACY_CLAUDE_DIRECTIVE


def test_floors_match_code_defaults():
    assert models.p2_floor("claude") == 4.8
    assert models.p2_floor("gemini") == 3.5
    assert models.p2_floor("chatgpt") is None  # no model lever
    assert models.p2_floor("nonexistent") is None


def test_version_helpers_render_like_the_ui():
    assert models.p2_claude_ver() == "4.8"
    assert models.p2_claude_prev_ver() == "4.7"  # 4.8 - 0.1, float-dust safe
    assert models.p2_claude_major() == "4"


def test_labels_carry_the_thinking_and_tool_policy():
    claude = models.p2_labels("claude")
    assert claude["effort"] == "max"
    assert claude["thinking"] is True
    assert claude["tool"] == "research"
    gemini = models.p2_labels("gemini")
    assert gemini["thinking"] == "extended"
    assert "pro" in gemini["reject"] and "lite" in gemini["reject"]


def _arm(monkeypatch, tmp_path, payload):
    """Arm the kill-switch and point the overlay at a temp file with `payload`
    (None = no file written)."""
    p = tmp_path / "model_refresh.json"
    if payload is not None:
        p.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(models, "DG_MODEL_REFRESH_ENABLED", True)
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH", p)


def test_overlay_ignored_when_flag_off(monkeypatch, tmp_path):
    # Flag OFF (default) → overlay is never read even if present.
    p = tmp_path / "model_refresh.json"
    p.write_text(json.dumps({"claude": {"floor": 9.9, "known_good": 4.8}}), encoding="utf-8")
    monkeypatch.setattr(models, "DG_MODEL_REFRESH_ENABLED", False)
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH", p)
    assert models.p2_floor("claude") == 4.8
    assert models.p2_known_good("claude") is None


def test_overlay_can_only_raise_the_floor(monkeypatch, tmp_path):
    # A higher discovered floor wins (canary raised it)…
    _arm(monkeypatch, tmp_path, {"claude": {"floor": 5.0}})
    assert models.p2_floor("claude") == 5.0
    # …but a lower overlay floor can NEVER downgrade below the code default.
    _arm(monkeypatch, tmp_path, {"claude": {"floor": 4.0}})
    assert models.p2_floor("claude") == 4.8


def test_known_good_from_overlay_when_armed(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, {"claude": {"known_good": 4.8}})
    assert models.p2_known_good("claude") == 4.8


def test_corrupt_overlay_falls_back_to_defaults(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, "{ this is not valid json :::")
    assert models.p2_floor("claude") == 4.8
    assert models.p2_known_good("claude") is None


def test_missing_overlay_falls_back_to_defaults(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)  # no file on disk
    assert models.p2_floor("claude") == 4.8
    assert models.p2_known_good("claude") is None


def test_non_dict_overlay_is_rejected(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, "[1, 2, 3]")  # valid json, wrong shape
    assert models.p2_floor("claude") == 4.8
