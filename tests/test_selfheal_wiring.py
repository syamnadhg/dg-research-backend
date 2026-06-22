"""PX-0 C2 wiring guards — the flag-gated, shadow-only wiring of the 6 P2 intents
into research.py.

The setup_*_dr / ensure_deep_mode_active functions need a live browser, so the
wiring is pinned with source-inspection guards (the codebase's established style:
test_command_stale_gate / test_cua_availability_probe). The one piece that IS
unit-testable — the _selfheal_shadow_observe helper — is exercised against a fake
page. The load-bearing invariant: with DG_SELFHEAL_ENABLED OFF (default) every
observe call is skipped, so C2 changes zero pipeline behaviour.
"""

from __future__ import annotations

import asyncio
import inspect
import re

import pytest

import research
import selfheal


# the 6 P2 intents that must be shadow-observed
_INTENTS = [
    "chatgpt.enable_deep_research",
    "gemini.enable_deep_research",
    "claude.enable_deep_research",
    "chatgpt.select_model",
    "gemini.select_model",
    "claude.select_model",
]


# ── helper: _selfheal_shadow_observe (the only unit-testable wiring piece) ──────
class FakePage:
    def __init__(self, ret):
        self.ret = ret
        self.evaluated = 0

    async def evaluate(self, js, params=None):
        self.evaluated += 1
        return self.ret


@pytest.fixture(autouse=True)
def _shadow_to_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("DG_SELFHEAL_SHADOW_LOG", str(tmp_path / "shadow.jsonl"))
    monkeypatch.setenv("DG_SELFHEAL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("DG_SELFHEAL_ENABLED", raising=False)


def _read_shadow():
    import json
    from pathlib import Path

    import os

    p = Path(os.environ["DG_SELFHEAL_SHADOW_LOG"])
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_shadow_observe_writes_a_record_with_outcome_and_probe(monkeypatch):
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "1")
    page = FakePage([{"role": "button", "text": "Deep research"}])
    asyncio.run(research._selfheal_shadow_observe(page, "gemini.enable_deep_research", outcome_pass=True))
    recs = _read_shadow()
    assert len(recs) == 1
    r = recs[0]
    assert r["platform"] == "gemini" and r["intent"] == "gemini.enable_deep_research"
    assert r["outcome_pass"] is True and r["would_heal"] is False
    assert r["tier"] == "builtin" and r["resolved_by"] == "shadow"
    assert r["probe_count"] == 1 and r["selector_or_box"] is None


def test_shadow_observe_failing_predicate_flags_would_heal(monkeypatch):
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "1")
    asyncio.run(research._selfheal_shadow_observe(FakePage([]), "claude.select_model", outcome_pass=False))
    r = _read_shadow()[-1]
    assert r["outcome_pass"] is False and r["would_heal"] is True


def test_shadow_observe_resolves_and_acts_nothing(monkeypatch):
    # The helper must only probe + log — it records selector_or_box=None and
    # never resolves a selector or performs an action (PX-2 owns acting).
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "1")
    asyncio.run(research._selfheal_shadow_observe(FakePage([]), "chatgpt.select_model", outcome_pass=True))
    assert _read_shadow()[-1]["selector_or_box"] is None
    src = inspect.getsource(research._selfheal_shadow_observe)
    for forbidden in (".click(", "setup_", "persist_selectors", "decide_toggle"):
        assert forbidden not in src, f"shadow observe must not act — found {forbidden!r}"


def test_shadow_observe_never_raises_on_probe_failure(monkeypatch):
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "1")

    class Boom:
        async def evaluate(self, js, params=None):
            raise RuntimeError("dead page")

    # must swallow — a shadow failure can never perturb a run
    asyncio.run(research._selfheal_shadow_observe(Boom(), "gemini.select_model", outcome_pass=True))


def test_shadow_observe_never_raises_even_if_log_fails(monkeypatch):
    # Bulletproof: even if BOTH the probe AND the error-path log() raise, nothing
    # escapes — else a raise would land in ensure_deep_mode_active's outer except
    # and flip a genuine active=False to the active=True fallback (flag-ON).
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "1")

    class Boom:
        async def evaluate(self, js, params=None):
            raise RuntimeError("dead page")

    def _boom_log(*a, **k):
        raise RuntimeError("stdout is gone")

    monkeypatch.setattr(research, "log", _boom_log)
    # No exception may escape.
    asyncio.run(research._selfheal_shadow_observe(Boom(), "claude.enable_deep_research", outcome_pass=False))


def test_shadow_observe_uses_each_intents_declared_region(monkeypatch):
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "1")
    intents = selfheal.load_intents()
    for iid in _INTENTS:
        assert iid in intents  # every wired intent has a contract


# ── source guards: all 6 intents are wired, each behind the kill-switch ─────────
def _setup_sources():
    return "\n".join(
        inspect.getsource(fn)
        for fn in (
            research.setup_chatgpt_dr,
            research.setup_gemini_dr,
            research.setup_claude_dr,
            research.ensure_deep_mode_active,
            research._gemini_select_flash_model,
        )
    )


@pytest.mark.parametrize("intent_id", _INTENTS)
def test_every_intent_has_a_flag_gated_shadow_call(intent_id):
    src = _setup_sources()
    # the observe call exists for this intent
    call = f'_selfheal_shadow_observe(page, "{intent_id}"'
    assert call in src, f"no shadow-observe call wired for {intent_id}"
    # ...and it is gated by the kill-switch (the nearest preceding gate within a
    # few lines must be `if selfheal and selfheal.is_enabled():`)
    idx = src.index(call)
    window = src[max(0, idx - 400):idx]
    assert "if selfheal and selfheal.is_enabled():" in window, (
        f"{intent_id} shadow call is not behind the DG_SELFHEAL_ENABLED gate"
    )


def test_no_shadow_call_is_ungated():
    # Every _selfheal_shadow_observe invocation (not the def) must sit under a
    # `selfheal.is_enabled()` guard — there must be no bare/unconditional call.
    src = _setup_sources()
    for m in re.finditer(r"_selfheal_shadow_observe\(", src):
        i = m.start()
        # skip the helper definition itself if it appeared
        if src[max(0, i - 12):i].strip().endswith("def"):
            continue
        window = src[max(0, i - 400):i]
        assert "selfheal.is_enabled()" in window, "found an ungated shadow-observe call"


def test_observe_calls_match_intent_count():
    # exactly the 6 intents wired (claude has 2 in one branch, gemini/chatgpt
    # split across hub + setup) → at least one call site per intent, no orphans.
    src = _setup_sources()
    called = set(re.findall(r'_selfheal_shadow_observe\(page, "([^"]+)"', src))
    assert called == set(_INTENTS), f"wired intents {called} != expected {set(_INTENTS)}"


def test_helper_degrades_when_module_missing():
    # _selfheal_shadow_observe must tolerate selfheal is None (guarded import).
    src = inspect.getsource(research._selfheal_shadow_observe)
    assert "if selfheal is None:" in src and "return" in src
