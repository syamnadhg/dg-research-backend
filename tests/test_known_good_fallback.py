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

⭐ 2026-09-23 — the step-back's TARGET DECISION is now EXECUTED, not read. The
block is lifted verbatim out of `start_agent_no_gemini_wait` (comments blanked)
and run with the real `version_key`/`p2_known_good` against a real overlay file;
only the browser-facing calls are doubles. It had been pinned by source text
alone, which is how a numbers-only gate could sit in front of it: once versions
travel as text ("5.10"), that gate left BOTH targets None and the one retry
silently never ran — while every substring this file asserted was still present.
The ranking inside the pickers is executed in test_model_selection_precision.py.
"""
import asyncio
import inspect
import json
import textwrap
from unittest import mock

import models
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
    # Claude picker + Gemini ranker both take `pin` and `below`. What they DO
    # with them — the exact-version tier, the strictly-older bound, a retired
    # pin falling back — is executed in test_model_selection_precision.py
    # (test_the_pin_outranks_…, test_a_retired_pin_…, test_an_exact_pin_on_x_10_…,
    # test_a_step_back_below_a_failed_x_10_…); asserting their source text here
    # is what let a float comparison stand for a version one.
    sc = code_only(inspect.getsource(research.setup_claude_dr))
    assert "({pin, below, fam, triggerText, verbs, upsellWindow})" in sc
    js = research._GEMINI_FLASH_RANK_JS
    # ⚠ The PARAMETERS, not the frozen parameter LIST. This used to assert the
    # exact destructuring literal, so adding an argument to the ranker failed a
    # test about `pin` with a diff about something else entirely (2026-08-22,
    # the advert nouns). What matters is that each named input reaches the
    # ranker.
    for _param in ("below", "doClick", "pin", "fam", "reject", "triggerText"):
        assert _param in js.split("=>")[0], _param


# ── the step-back's target decision, EXECUTED ─────────────────────────────

def _step_back_source() -> str:
    """The `if not research_ok and platform_l in (…)` block, verbatim, wrapped as
    a coroutine that returns its locals. Sliced on the two block headers (each
    occurs once), with comments blanked in place by `code_only`."""
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    head = '        if not research_ok and platform_l in ("claude", "gemini"):'
    tail = '        if research_ok and platform_l in ("claude", "gemini"):'
    assert src.count(head) == 1 and src.count(tail) == 1, "the block headers moved"
    i = src.index(head)
    block = textwrap.dedent(src[i:src.index(tail, i)])
    return ("async def __step_back__(research_ok):\n"
            + textwrap.indent(block, "    ") + "    return locals()\n")


def _run_step_back(monkeypatch, tmp_path, *, platform="claude", failed,
                   stored=None, picks_to=None, dr_after=False):
    """Run the REAL block. `stored` is the overlay's `known_good` exactly as a
    computer holds it (a JSON number from before 2026-09-23, or text since);
    `failed` is what the ranker reported for the model that did not verify.
    Returns (setup calls as (pin_model, step_below), the block's locals, alerts)."""
    overlay = tmp_path / "model_refresh.json"
    if stored is not None:
        overlay.write_text(json.dumps({platform: {"known_good": stored}}), encoding="utf-8")
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH", overlay)
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "1")
    picked = {platform: failed}
    calls, alerts = [], []

    async def _setup(page, pin_model=None, step_below=None):
        calls.append((pin_model, step_below))
        picked.pop(platform, None)          # the real selectors clear at entry
        if picks_to is not None:
            picked[platform] = picks_to

    async def _ensure(*a, **k):
        return {"researchOn": dr_after, "active": dr_after}

    ns = dict(vars(research))               # every other name resolves as production's
    ns.update({
        "_P2_PICKED_VERSION": picked, "platform_l": platform, "platform": platform,
        "label": "leg", "page": object(), "setup_confirmed": False,
        "_agent_name": platform.capitalize(), "log": lambda *a, **k: None,
        "setup_claude_dr": _setup, "setup_gemini_dr": _setup,
        "ensure_deep_mode_active": _ensure,
        "_emit_model_drift_alert": lambda *a, **k: alerts.append(a),
    })
    exec(compile(_step_back_source(), "<step-back>", "exec"), ns)
    loc = asyncio.run(ns["__step_back__"](False))
    return calls, loc, alerts


def test_a_stored_5_0_and_a_failed_5_5_retry_on_pin_5(monkeypatch, tmp_path):
    """⭐ THE TRANSLATOR, AT ITS CONSUMER. Every installed computer holds its
    known-good as the JSON number 5.0; the ranker now reports the failed model as
    the text "5.5". The retry must pin "5" — the text the "Opus 5" row matches —
    and send "5.5" as the bound. A numbers-only gate here made BOTH None and the
    retry never ran."""
    calls, loc, _ = _run_step_back(monkeypatch, tmp_path, failed="5.5", stored=5.0)
    assert calls == [("5", "5.5")], f"the step-back retried with {calls}"


def test_a_failed_5_10_steps_back_to_a_learned_5_9(monkeypatch, tmp_path):
    """As floats a failed 5.10 was 5.1, and a known-good 5.9 was 'not older', so
    the proven model was never pinned."""
    calls, _, _ = _run_step_back(monkeypatch, tmp_path, failed="5.10", stored="5.9")
    assert calls == [("5.9", "5.10")]


def test_gemini_steps_back_from_3_10_to_a_stored_3_8(monkeypatch, tmp_path):
    calls, _, _ = _run_step_back(monkeypatch, tmp_path, platform="gemini",
                                 failed="3.10", stored=3.8)
    assert calls == [("3.8", "3.10")]


def test_a_known_good_that_is_not_older_is_not_pinned(monkeypatch, tmp_path):
    """Re-pinning the version that just failed can't help and re-clicks an
    already-correct model; a NEWER learned value is no retreat at all. `below`
    still rides along, so the retry happens without a pin."""
    for stored in ("5.5", 5.5, "5.10"):
        calls, _, _ = _run_step_back(monkeypatch, tmp_path, failed="5.5", stored=stored)
        assert calls == [(None, "5.5")], f"stored {stored!r}: {calls}"


def test_an_unknown_failed_version_does_not_pin(monkeypatch, tmp_path):
    """An unknown failed version is not "any pin will do": we cannot prove the
    learned value is older, so pinning could re-select the model that just failed
    and burn the one-shot retry. With nothing to bound on, there is no retry."""
    calls, loc, _ = _run_step_back(monkeypatch, tmp_path, failed=None, stored="5")
    assert calls == [] and loc["_pin"] is None and loc["_below"] is None


def test_a_proven_retreat_off_5_10_is_announced(monkeypatch, tmp_path):
    """The notice is gated on `stepped_back_to(picked, failed)`. As floats a
    retreat from 5.10 to 5.9 read as 5.9 > 5.1 — 'no step-back happened' — and
    the drift notice was withheld for the one retreat that did happen."""
    calls, _, alerts = _run_step_back(monkeypatch, tmp_path, failed="5.10",
                                      stored="5.9", picks_to="5.9", dr_after=True)
    assert calls == [("5.9", "5.10")]
    assert len(alerts) == 1 and "v5.9" in alerts[0][1], alerts


def test_a_retry_that_moved_nothing_claims_no_retreat(monkeypatch, tmp_path):
    calls, _, alerts = _run_step_back(monkeypatch, tmp_path, failed="5.10",
                                      stored=None, picks_to=None, dr_after=True)
    assert calls == [(None, "5.10")] and alerts == []


def test_a_malformed_overlay_cannot_kill_the_step_back():
    """p2_known_good reads a user-editable JSON file at exactly the recovery
    moment. A scalar where a dict belongs used to raise AttributeError straight
    through the agent launch."""
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    # ⭐ The read is family-scoped now — a version is meaningless without the
    # family it belongs to, and this call sits on the recovery path where a
    # cross-family pin would spend the one-shot retry on a row that was never on
    # the menu. Matched on the prefix so the family argument can be spelled
    # however the caller needs; the guard below is what this test is about.
    i = src.find("_kg = p2_known_good(platform_l")
    assert i != -1
    assert "_kg = p2_known_good(platform_l)" not in src, (
        "the step-back pin must name the family it is pinning within"
    )
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
    # Prefix-matched: the read carries the family it is pinning WITHIN (see
    # test_a_malformed_overlay_cannot_kill_the_step_back), and what this line is
    # asserting is that a learned value is consulted at all.
    assert "_kg = p2_known_good(platform_l" in src
    # (What the targets ARE is executed above — test_a_stored_5_0_… and friends.)
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


def test_a_fresh_install_can_still_step_back(monkeypatch, tmp_path):
    """⭐ THE REGRESSION THIS FILE EXISTS TO CATCH after the floor removal. With
    no learned known-good the old expression was `None or p2_floor()` = None, so
    the very first run after an install could not step back at all — exactly the
    "brand-new model breaks Deep Research" case the fallback was built for.
    (Executed now; it used to look for the guard's source line.)"""
    calls, loc, _ = _run_step_back(monkeypatch, tmp_path, failed="5", stored=None)
    assert loc["_pin"] is None and calls == [(None, "5")], (
        "the fallback must fire when EITHER target resolves; gating on the "
        "learned value alone strands a fresh install")


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
