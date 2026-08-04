"""Step-back fallback — when the newest model can't reach Deep Research.

If the LATEST model can't be verified into Deep Research, retry ONCE on an
OLDER model before the chat-mode gate fires, so a just-shipped release that
doesn't support DR yet degrades to a working model instead of a Skip.

Rewritten 2026-08-01. The old target was `p2_known_good() or p2_floor()` — and
with the floor literals removed that second half becomes None, so on a FRESH
install (nothing learned yet) there would be no target at all and the run would
park instead of stepping back. There are now two ways to name the target,
neither of them a literal: `pin` (the learned known-good, only when it is
genuinely older than what failed) and `below` (the highest row strictly beneath
the failed version, resolved from the live menu — needs no history).

Source-inspection guards (the pick is JS in a live page) + a behavioral check
that the fallback notice is an AMBER warning, never a red error.
"""
import inspect
from unittest import mock

import research
from conftest import code_only, code_only_deep


def test_setup_functions_accept_both_step_back_targets():
    for fn in (research.setup_claude_dr, research.setup_gemini_dr,
               research._gemini_select_flash_model):
        sig = str(inspect.signature(fn))
        assert "pin_model" in sig, f"{fn.__name__} must accept an exact pin"
        assert "step_below" in sig, (
            f"{fn.__name__} must accept a step-below target — without it a fresh "
            f"install (no learned known-good) has no way to step back at all"
        )


def test_pin_forces_exact_version_in_pickers():
    # Claude picker + Gemini ranker both branch on `pin` to target an EXACT
    # version, distinct from the default "highest offered" path.
    sc = code_only(inspect.getsource(research.setup_claude_dr))
    assert "Math.abs(v - pin)" in sc and "({pin, below, fam, triggerText})" in sc
    js = research._GEMINI_FLASH_RANK_JS
    assert "Math.abs(v - pin)" in js and "{below, doClick, pin, fam, reject, triggerText}" in js


def test_below_selects_strictly_older_in_both_pickers():
    """The no-history step-back. `>=` rather than `>` is the part that matters:
    with `>`, the row that just failed is still eligible and the retry re-picks
    the same model."""
    sc = code_only(inspect.getsource(research.setup_claude_dr))
    for src in (sc, research._GEMINI_FLASH_RANK_JS):
        assert "v >= bound - 0.001" in src, (
            "step-back must exclude the failed version itself, not just rank below it"
        )
        assert "v === null || v >= bound" in src, (
            "an un-versioned row cannot be proven older than what failed, so it "
            "must not be a step-back target"
        )


def test_a_retired_pin_falls_back_to_the_step_below():
    """⭐ FOUND IN REVIEW. A learned known-good never expires, so weeks later the
    platform may have retired it. Treating "exact pin absent" as "nothing to
    pick" threw away a perfectly usable older row and sent the leg to the
    chat-mode gate — losing the single retry this path exists to provide."""
    for src in (code_only(inspect.getsource(research.setup_claude_dr)),
                research._GEMINI_FLASH_RANK_JS):
        assert "const bound = below != null ? below : pin;" in src, (
            "when the pinned version is not on the menu the picker must fall "
            "back to the strictly-older rule, not give up"
        )
        assert "if (pin != null || below != null)" in src, (
            "the step-back filter must apply on the pin path too"
        )
    # …and the caller must actually SEND both, or the fallback is unreachable.
    # Pinned as a whole statement: `_below = _failed_f if _pin is None else None`
    # also starts with "_below = _failed_f", and that spelling is exactly the bug
    # (it withholds `below` on the pin path, so a retired pin has nothing to fall
    # back to).
    caller = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    stmts = [ln.strip() for ln in caller.splitlines() if ln.strip().startswith("_below =")]
    assert stmts == ["_below = _failed_f"], (
        f"`below` must ride along WITH the pin, unconditionally — got {stmts}"
    )


def test_an_unknown_failed_version_does_not_pin():
    """`_failed_f is None` is not "any pin will do": with the failed version
    unknown we cannot prove the learned value is older, so pinning could
    re-select the model that just failed and burn the one-shot retry."""
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    assert "_failed_f is not None and _kg < _failed_f - 0.001" in src


def test_a_malformed_overlay_cannot_kill_the_step_back():
    """p2_known_good reads a user-editable JSON file at exactly the recovery
    moment. A scalar where a dict belongs used to raise AttributeError straight
    through the agent launch."""
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    i = src.find("_kg = p2_known_good(platform_l)")
    assert i != -1
    assert "try:" in src[max(0, i - 60):i], "the read must be guarded at the call site"
    # …and the reader itself must not blow up on a non-dict platform entry.
    import json as _json
    import models as _m
    import tempfile
    import pathlib as _p
    with tempfile.TemporaryDirectory() as d:
        f = _p.Path(d) / "model_refresh.json"
        f.write_text(_json.dumps({"claude": 4.8}), encoding="utf-8")
        old = _m._MODEL_REFRESH_OVERLAY_PATH
        try:
            _m._MODEL_REFRESH_OVERLAY_PATH = f
            assert _m.p2_known_good("claude") is None
        finally:
            _m._MODEL_REFRESH_OVERLAY_PATH = old


def test_no_picker_takes_a_floor_any_more():
    """A floor could only ever reject the highest offered row — the one that
    should have won. Its old job (never downgrade) is structural now.

    ⚠ Matches on the CODE CONSTRUCTS, not on the word "floor". These functions
    carry long comments explaining why the floor was removed, and a bare
    substring check would fail on its own explanation — the same trap that let
    a mutation survive last wave, in reverse."""
    banned = ("< floor", ">= floor", "v < floor", "p2_floor", "{floor", "floor,", "floor)")
    for name, src in (("setup_claude_dr", code_only_deep(research.setup_claude_dr)),
                      ("gemini ranker", research._GEMINI_FLASH_RANK_JS),
                      ("ensure_deep_mode_active",
                       code_only_deep(research.ensure_deep_mode_active))):
        for tok in banned:
            assert tok not in src, f"a floor came back in {name}: {tok!r}"


def test_step_back_forces_repick_even_when_model_already_ok():
    # The #744 "don't re-pick a correct model" guard must be BYPASSED on EITHER
    # step-back route (the model sitting there is the one that just failed DR).
    sc = code_only(inspect.getsource(research.setup_claude_dr))
    assert "model_ok = (pin_model is None and step_below is None)" in sc, (
        "a step_below retry with model_ok still true would skip the picker and "
        "leave the failed model selected"
    )


def test_fallback_runs_before_the_chat_mode_gate_and_is_single_shot():
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    fb = src.find("known-good fallback")
    # The park itself now lives in _park_chat_mode_decision (shared with the
    # dropped-send re-submit recovery); the CALL SITE is what has to sit after the
    # fallback, so anchor the ordering on that.
    gate = src.find("_park_chat_mode_decision(")
    assert fb != -1 and gate != -1 and fb < gate, (
        "the known-good fallback must run BEFORE the chat-mode gate fires."
    )
    # ChatGPT (no model lever) is not eligible.
    assert 'platform_l in ("claude", "gemini")' in src
    # Fallback target: the learned known-good, else "the highest below the one
    # that failed". Never a literal, and never nothing.
    assert "_kg = p2_known_good(platform_l)" in src
    assert "_below = _failed_f" in src
    # Single-shot: the fallback block must not introduce a retry LOOP construct
    # (it's a straight-line `if`). Guard on actual loop syntax, not the English
    # word "for" that appears in the log strings.
    block = src[fb:gate]
    assert "range(" not in block and "while True" not in block, (
        "the known-good fallback must be straight-line (single attempt), not a loop."
    )
    # It routes the target through the same invariant-safe setup functions.
    assert "setup_claude_dr(page, pin_model=_pin, step_below=_below)" in src
    assert "setup_gemini_dr(page, pin_model=_pin, step_below=_below)" in src


def test_known_good_is_only_used_when_it_is_older_than_what_failed():
    # Re-pinning the SAME version that just failed can't help and would
    # needlessly re-click an already-correct model. When known-good is not
    # strictly older, the `below` route takes over rather than the whole
    # fallback becoming a no-op.
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    assert "_P2_PICKED_VERSION.get(platform_l)" in src
    assert "_kg < _failed_f - 0.001" in src, (
        "known-good must be compared against the failed version and rejected "
        "when it is not strictly older"
    )


def test_a_fresh_install_can_still_step_back():
    """⭐ THE REGRESSION THIS FILE EXISTS TO CATCH after the floor removal. With
    no learned known-good the old expression was `None or p2_floor()` = None, so
    the very first run after an install could not step back at all — exactly the
    "brand-new model breaks Deep Research" case the fallback was built for."""
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    guard = src.find("if _pin is not None or _below is not None:")
    assert guard != -1, (
        "the fallback must fire when EITHER target resolves; gating on the "
        "learned value alone strands a fresh install"
    )


def test_fallback_holds_the_pin_via_measure_only_reactivate():
    # Capstone review fix: the fallback measures with reactivate=False so the
    # un-pinned re-activation can't re-pick the highest (= the failed model) and
    # silently undo the pin.
    src = inspect.getsource(research.start_agent_no_gemini_wait)
    assert "ensure_deep_mode_active(page, platform, label, reactivate=False)" in src


def test_ensure_deep_mode_active_reactivate_param_gates_resetup():
    # reactivate=True (default) preserves today's behavior; False = measure-only.
    ed = inspect.getsource(research.ensure_deep_mode_active)
    assert "reactivate=True" in ed
    assert ed.count("reactivate and") == 3, (
        "all three platform re-activation blocks must be gated on `reactivate`."
    )


def test_drift_alert_is_amber_warning_not_red_error():
    # Badge philosophy: a "fell back / FYI" notice is a pipeline_warning
    # (alertType warn), NEVER a red pipeline_error.
    with mock.patch.object(research, "emit_event") as em:
        research._emit_model_drift_alert("gemini", "msg", "details")
    assert em.call_count == 1
    args, kwargs = em.call_args
    assert args[0] == "pipeline_warning", "must use pipeline_warning, not pipeline_error"
    assert kwargs.get("alertType") == "warn"
    assert kwargs.get("dismissible") is True
    assert kwargs.get("actions") == []  # informational, no decision buttons
