"""Phoenix (model_refresh) Phase A — P2 model POLICY single-source-of-truth.

These guard the behavior-identical foundation: the central P2_MODEL_POLICY +
accessors must reproduce today's values EXACTLY (so routing the scattered
literals through them changes nothing), and the runtime overlay must be a safe
no-op until the kill-switch is armed and can never break selection.

Dep-free: imports only `models` (no research.py / playwright).
"""
import json

import models


# The byte-identity pin that used to live here is gone ON PURPOSE (2026-07-30).
# It existed to prove that routing two duplicated literals through
# p2_claude_setup_directive() changed nothing — a refactor guard, and it did its
# job. Keeping it would now pin a directive that is actively wrong: it named a
# single version and told the agent to "select" it, so on an account already
# running Opus 5 the agent reasoned "this is NOT Opus 4.8, so I need to fix it"
# and clicked into the model menu. What matters is no longer byte-identity but
# the CONTRACT below: derived from policy, floor stated as a floor, and an
# explicit instruction to leave a higher model alone.


def test_claude_setup_directive_is_derived_from_policy():
    d = models.p2_claude_setup_directive()
    cur = models.p2_claude_ver()
    fam = models.P2_MODEL_POLICY["claude"]["family"].capitalize()
    effort = models.P2_MODEL_POLICY["claude"]["effort"].capitalize()
    assert f"{fam} {cur}" in d, "the family + floor must come from the policy"
    assert f"{effort} effort" in d, "the effort label must come from the policy"
    assert models.P2_MODEL_POLICY["claude"]["tool"].capitalize() + " tool" in d


def test_claude_setup_directive_states_the_floor_as_a_minimum():
    """The regression this replaces: naming one version made a HIGHER model read
    as wrong, which is what sent the agent into the model menu needlessly."""
    d = models.p2_claude_setup_directive()
    cur = models.p2_claude_ver()
    assert "OR NEWER" in d, "the floor must be expressed as a minimum, not a target"
    assert "LEAVE THE MODEL ALONE" in d, (
        "an at-or-above model must be explicitly declared correct — without this "
        "the agent 'fixes' a model that is already right"
    )
    assert "do not open the model menu" in d.lower()
    # The leave-alone must be CONDITIONAL. An unconditional "leave the model
    # alone" reads as "never touch the model", which would strand an account on
    # Sonnet or a below-floor Opus forever — the opposite failure, and one that
    # the presence checks above cannot distinguish on their own.
    cond = d.find("If it already shows")
    leave = d.find("LEAVE THE MODEL ALONE")
    assert cond != -1, "the leave-alone instruction must carry its condition"
    assert cond < leave, "the condition must precede the instruction it guards"
    assert f"below {models.P2_MODEL_POLICY['claude']['family'].capitalize()} {cur}" in d, (
        "there must still be an explicit escape hatch for a genuinely wrong "
        "model, or a below-floor account can never be corrected"
    )


def test_claude_setup_directive_no_longer_asks_for_a_thinking_toggle():
    """Opus 5 removed it. Asking for a control that cannot be found is what made
    the DOM path fail every run and hand over to CUA."""
    d = models.p2_claude_setup_directive().lower()
    assert "thinking" not in d


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
    # FALSE on purpose since 2026-07-30: Opus 5 dropped the separate Thinking
    # toggle that Opus 4.x carried inside the Effort submenu — effort IS the
    # reasoning lever there now. While this was True, setup opened the model
    # popover on every run purely to reach a control that no longer exists.
    # Flipping it back must reopen that path, which test_claude_popover_skip.py
    # pins behaviourally.
    assert claude["thinking"] is False
    assert claude["tool"] == "research"
    gemini = models.p2_labels("gemini")
    assert gemini["thinking"] == "extended"   # Gemini still has one
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


# ── pick_highest_model / parse_family_version (the ranker algorithm) ──────


def test_parse_family_version_handles_concatenated_row_text():
    # Dropdown rows are title+description concatenated, no trailing boundary.
    assert models.parse_family_version("3.5 FlashAll-around help", "flash") == 3.5
    assert models.parse_family_version("Gemini 4.0 Flash · fast", "flash") == 4.0
    assert models.parse_family_version("Opus 4.8 Max", "opus") == 4.8
    assert models.parse_family_version("Sonnet 4.6", "opus") is None
    assert models.parse_family_version("", "flash") is None


def test_pick_highest_flash_picks_the_newest():
    rows = ["2.5 Flash", "3.5 FlashAll-around help", "4.0 Flash (new)"]
    best = models.pick_highest_model(rows, "flash", floor=3.5, reject=["lite", "deep think", "pro"])
    assert best["version"] == 4.0 and best["index"] == 2


def test_pick_highest_flash_rejects_siblings():
    # Flash-Lite / Pro / Deep Think must never win even if numerically higher.
    rows = ["5.0 Flash-Lite", "9.9 Gemini Pro", "3.5 Flash Deep Think", "3.5 Flash"]
    best = models.pick_highest_model(rows, "flash", floor=3.5, reject=["lite", "deep think", "pro"])
    assert best["label"] == "3.5 Flash"


def test_pick_highest_floor_refuses_below():
    rows = ["3.0 Flash", "2.5 Flash"]
    assert models.pick_highest_model(rows, "flash", floor=3.5, reject=["lite", "deep think", "pro"]) is None


def test_pick_highest_tie_breaks_to_shortest_label():
    # A wrapper row concatenating several models loses to the leaf at the same version.
    rows = ["4.0 Flash — All-around help, fast responses, multimodal, etc.", "4.0 Flash"]
    best = models.pick_highest_model(rows, "flash", floor=3.5, reject=[])
    assert best["label"] == "4.0 Flash"


def test_pick_highest_reject_boundary_before_only():
    # A reject term buried INSIDE another word must NOT false-reject the row.
    rows = ["4.0 Flash — improved, enterprise-grade (approved)"]
    best = models.pick_highest_model(rows, "flash", floor=3.5, reject=["pro", "lite"])
    assert best is not None and best["version"] == 4.0


def test_pick_highest_rejects_glued_sibling():
    # A GLUED sibling row ('4.0 flash-litefastest answers') must still be
    # rejected (boundary-before match mirrors the JS ranker's includes()), so a
    # numerically-higher Lite/Pro variant can never win over the real Flash.
    rows = ["4.0 flash-litefastest answers", "3.5 flashall-around help"]
    best = models.pick_highest_model(rows, "flash", floor=3.5, reject=["lite", "deep think", "pro"])
    assert best["label"] == "3.5 flashall-around help"


def test_pick_highest_opus_family_for_canary_reuse():
    rows = ["Opus 4.7 Adaptive", "Opus 4.8 Max", "Sonnet 4.6", "Opus 5.0"]
    best = models.pick_highest_model(rows, "opus", floor=4.8, reject=[])
    assert best["version"] == 5.0


def test_pick_highest_none_when_no_candidate():
    assert models.pick_highest_model([], "flash", floor=3.5) is None
    assert models.pick_highest_model([None, "", "Ask Gemini"], "flash", floor=3.5) is None


# ── record_known_good / on-the-fly learning (revised Phase D) ─────────────


def test_record_known_good_is_noop_when_flag_off(monkeypatch, tmp_path):
    p = tmp_path / "model_refresh.json"
    monkeypatch.setattr(models, "DG_MODEL_REFRESH_ENABLED", False)
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH", p)
    assert models.record_known_good("claude", 4.8) is False
    assert not p.exists()  # nothing written when un-armed


def test_record_known_good_writes_and_reads_back_as_float(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    assert models.record_known_good("claude", 4.8) is True
    assert models.p2_known_good("claude") == 4.8
    assert isinstance(models.p2_known_good("claude"), float)
    # the overlay file is whole/valid JSON (atomic temp+replace)
    assert json.loads((tmp_path / "model_refresh.json").read_text(encoding="utf-8"))["claude"]["known_good"] == 4.8


def test_record_known_good_only_writes_on_change(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    assert models.record_known_good("claude", 4.8) is True
    assert models.record_known_good("claude", 4.8) is False  # unchanged → no churn
    assert models.record_known_good("claude", 5.0) is True   # advanced → write


def test_record_known_good_rejects_junk(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    assert models.record_known_good("claude", None) is False
    assert models.record_known_good("claude", "abc") is False
    assert models.record_known_good("claude", -1) is False
    assert models.record_known_good("claude", 0) is False


def test_record_known_good_preserves_other_platforms(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    models.record_known_good("claude", 4.8)
    models.record_known_good("gemini", 3.5)
    assert models.p2_known_good("claude") == 4.8
    assert models.p2_known_good("gemini") == 3.5


def test_p2_known_good_coerces_string_overlay_value(monkeypatch, tmp_path):
    # A stringly-typed overlay value must not break the float comparisons.
    _arm(monkeypatch, tmp_path, {"claude": {"known_good": "4.8"}})
    assert models.p2_known_good("claude") == 4.8
    _arm(monkeypatch, tmp_path, {"claude": {"known_good": "garbage"}})
    assert models.p2_known_good("claude") is None
