"""PX-2 C5 guards — the heal ACTIVATION loop (heal_once / resolve_and_click /
record_heal / act_enabled) + the research.py wiring.

The loop is page-agnostic, so it's driven by a fake page that dispatches on the
JS string (probe vs resolve/click). Every act path is exercised: Tier-0 registry
hit + validity gate, Tier-1.5 heuristic, the #709 pre-act guard (skip/act/
ambiguous), verify-before-trust, registry health + eviction, and total isolation
(never raises). All state goes to tmp_path; default flags are OFF.
"""

from __future__ import annotations

import pytest

import selfheal


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("DG_SELFHEAL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DG_SELFHEAL_SELECTORS", str(tmp_path / "state" / "selectors.json"))
    monkeypatch.delenv("DG_SELFHEAL_ENABLED", raising=False)
    monkeypatch.delenv("DG_SELFHEAL_ACT", raising=False)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _el(role="button", name="deep research", text="Deep research"):
    return {"role": role, "accessible_name": name, "text": text,
            "attrs": {"testid": "", "haspopup": "", "placeholder": "", "cls": ""},
            "bounds": {"x": 0, "y": 0, "w": 10, "h": 10}, "visible": True}


class HealPage:
    """Dispatches page.evaluate by JS identity: probe → snap; resolve/click →
    validity (do_click False) or click (do_click True)."""

    def __init__(self, snap, validity=None, click=None, boom=False):
        self.snap = snap
        self.validity = validity if validity is not None else {"matched": 1}
        self.click = click if click is not None else {"matched": 1, "clicked": True}
        self.boom = boom
        self.clicks = 0

    async def evaluate(self, js, params=None):
        if self.boom:
            raise RuntimeError("dead page")
        if js is selfheal.PROBE_REGION_JS:
            return self.snap
        if js is selfheal._RESOLVE_CLICK_JS:
            if params and params.get("doClick"):
                self.clicks += 1
                return self.click
            return self.validity
        return None


def _seq(*vals):
    """A stateful check_active: yields vals in order, then repeats the last."""
    state = {"i": 0}

    def f():
        i = state["i"]
        state["i"] = i + 1
        return vals[i] if i < len(vals) else vals[-1]

    return f


_GEM = lambda: selfheal.load_intents()["gemini.enable_deep_research"]  # noqa: E731


# ── act_enabled flag ─────────────────────────────────────────────────────────
def test_act_enabled_requires_both_flags(monkeypatch):
    assert selfheal.act_enabled() is False
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "1")
    assert selfheal.act_enabled() is False  # master on, act off → still off
    monkeypatch.setenv("DG_SELFHEAL_ACT", "1")
    assert selfheal.act_enabled() is True
    monkeypatch.setenv("DG_SELFHEAL_ENABLED", "0")
    assert selfheal.act_enabled() is False  # act on but master off → off


# ── heal_once: the loop ───────────────────────────────────────────────────────
def test_heal_tier15_success_persists_selector():
    page = HealPage([_el()])
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(False, True), confirmed_off=True, do_act=True))
    assert res["tier"] == "heal" and res["acted"] and res["healed"]
    assert res["reason"] == "verified"
    # persisted under platform|intent|fingerprint with a success count
    reg = selfheal.load_selectors()
    assert len(reg) == 1
    entry = next(iter(reg.values()))
    assert entry["success_count"] == 1 and entry["fail_count"] == 0
    assert entry["strategy_rank"][0]["by"] == "role+name"


def test_heal_preact_guard_skips_when_already_active():
    page = HealPage([_el()])
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(True), confirmed_off=True, do_act=True))
    assert res["healed"] and res["reason"] == "already_active"
    assert page.clicks == 0  # never clicked an already-active control
    assert selfheal.load_selectors() == {}  # nothing persisted on a skip


def test_heal_preact_guard_ambiguous_never_clicks():
    page = HealPage([_el()])
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(False), confirmed_off=False, do_act=True))
    assert not res["healed"] and res["reason"] == "ambiguous_no_act"
    assert page.clicks == 0  # the #709 firewall: ambiguous read => no click


def test_heal_shadow_mode_does_not_act():
    page = HealPage([_el()])
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(False), confirmed_off=True, do_act=False))
    assert res["reason"] == "shadow_no_act" and not res["acted"] and page.clicks == 0
    assert selfheal.load_selectors() == {}


def test_heal_no_candidate():
    page = HealPage([{"role": "div", "accessible_name": "", "text": "nope",
                      "attrs": {}, "bounds": {"w": 1, "h": 1}, "visible": True}])
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(False), confirmed_off=True, do_act=True))
    assert res["reason"] == "no_candidate" and not res["acted"]


def test_heal_act_but_predicate_still_false_records_fail():
    page = HealPage([_el()])
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(False, False), confirmed_off=True, do_act=True))
    assert res["acted"] and not res["healed"]
    assert res["reason"] == "act_did_not_satisfy_predicate"
    entry = next(iter(selfheal.load_selectors().values()))
    assert entry["fail_count"] == 1 and entry["success_count"] == 0


def test_heal_refuses_ambiguous_match():
    page = HealPage([_el()], click={"matched": 2, "clicked": False, "ambiguous": True})
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(False), confirmed_off=True, do_act=True))
    assert not res["healed"] and res["reason"] == "ambiguous_match" and not res["acted"]


def test_heal_async_check_active_is_awaited():
    page = HealPage([_el()])

    calls = {"n": 0}

    async def _ca():
        calls["n"] += 1
        return calls["n"] > 1  # False on guard, True on verify

    res = _run(selfheal.heal_once(page, _GEM(), check_active=_ca, confirmed_off=True, do_act=True))
    assert res["healed"] and calls["n"] == 2


def test_heal_never_raises_on_dead_page():
    # probe_region swallows the dead-page error → [] → graceful no_candidate
    # (never raises, never acts, never heals).
    page = HealPage([_el()], boom=True)
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(False, True), confirmed_off=True, do_act=True))
    assert res["healed"] is False and not res["acted"] and res["reason"] == "no_candidate"


def test_heal_swallows_a_raising_predicate():
    # if the injected predicate itself raises, heal_once catches it (the generic
    # except) and returns gracefully — never propagates into the verify path.
    page = HealPage([_el()])

    def _boom():
        raise RuntimeError("predicate exploded")

    res = _run(selfheal.heal_once(page, _GEM(), check_active=_boom, confirmed_off=True, do_act=True))
    assert res["healed"] is False and res["reason"].startswith("error:")


# ── Tier-0 registry path ─────────────────────────────────────────────────────
def test_heal_tier0_registry_hit_when_validity_passes():
    snap = [_el()]
    fp = selfheal.ui_fingerprint(snap)
    key = selfheal._registry_key("gemini.enable_deep_research", fp)
    selfheal.persist_selectors(lambda cur: {**cur, key: {
        "strategy_rank": [{"by": "role+name", "value": "button|deep research"}],
        "success_count": 3, "fail_count": 0}})
    page = HealPage(snap, validity={"matched": 1})  # persisted selector still resolves
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(False, True), confirmed_off=True, do_act=True))
    assert res["tier"] == "registry" and res["healed"]


def test_heal_tier0_stale_evicts_and_falls_through():
    snap = [_el()]
    fp = selfheal.ui_fingerprint(snap)
    key = selfheal._registry_key("gemini.enable_deep_research", fp)
    selfheal.persist_selectors(lambda cur: {**cur, key: {
        "strategy_rank": [{"by": "role+name", "value": "button|old label"}],
        "success_count": 1, "fail_count": 0, "consecutive_fails": 2}})
    # validity probe returns no match → stale → record fail (3rd consecutive → evict),
    # then fall through to Tier-1.5 semantic_match (which succeeds).
    page = HealPage(snap, validity={"matched": 0}, click={"matched": 1, "clicked": True})
    res = _run(selfheal.heal_once(page, _GEM(), check_active=_seq(False, True), confirmed_off=True, do_act=True))
    assert res["tier"] == "heal" and res["healed"]


# ── record_heal: health + eviction ───────────────────────────────────────────
def test_record_heal_success_then_fail_counts():
    rank = [{"by": "role+name", "value": "button|deep research"}]
    selfheal.record_heal("gemini.enable_deep_research", "abc123", rank, success=True)
    out = selfheal.record_heal("gemini.enable_deep_research", "abc123", rank, success=False)
    entry = out[selfheal._registry_key("gemini.enable_deep_research", "abc123")]
    assert entry["success_count"] == 1 and entry["fail_count"] == 1
    assert entry["consecutive_fails"] == 1 and entry["confidence"] == 0.5
    assert "last_used" in entry


def test_record_heal_evicts_after_three_consecutive_fails():
    rank = [{"by": "role+text", "value": "button|x"}]
    k = "gemini.enable_deep_research"
    for _ in range(3):
        selfheal.record_heal(k, "fp9", rank, success=False)
    assert selfheal.load_selectors() == {}  # evicted
    # eviction is audited
    audit = selfheal._audit_log_path().read_text(encoding="utf-8")
    assert "evict" in audit


# ── record_heal: PX-5 trusted-selector promotion ─────────────────────────────
def test_record_heal_promotes_to_trusted_after_threshold():
    rank = [{"by": "role+name", "value": "button|deep research"}]
    k = "gemini.enable_deep_research"
    out = {}
    for _ in range(selfheal._PROMOTE_THRESHOLD):
        out = selfheal.record_heal(k, "fpP", rank, success=True)
    entry = out[selfheal._registry_key(k, "fpP")]
    assert entry["consecutive_oks"] == selfheal._PROMOTE_THRESHOLD
    assert entry.get("trusted") is True and entry.get("promoted_ts")


def test_record_heal_untrusts_and_resets_oks_on_fail():
    rank = [{"by": "role+name", "value": "button|deep research"}]
    k = "gemini.enable_deep_research"
    for _ in range(selfheal._PROMOTE_THRESHOLD):
        selfheal.record_heal(k, "fpQ", rank, success=True)  # → trusted
    out = selfheal.record_heal(k, "fpQ", rank, success=False)
    entry = out[selfheal._registry_key(k, "fpQ")]
    assert entry.get("trusted") is False
    assert entry["consecutive_oks"] == 0 and entry["consecutive_fails"] == 1


def test_promotion_candidates_returns_only_trusted_sorted():
    sel = {
        "gemini|enable_deep_research|fp1": {"strategy_rank": [{"by": "role+name", "value": "a"}],
                                            "trusted": True, "success_count": 5, "promoted_ts": "t"},
        "claude|select_model|fp2": {"strategy_rank": [{"by": "role+name", "value": "b"}],
                                    "trusted": True, "success_count": 9},
        "chatgpt|enable_deep_research|fp3": {"strategy_rank": [{"by": "role", "value": "c"}],
                                             "success_count": 2},  # not trusted
    }
    cands = selfheal.promotion_candidates(sel)
    assert [c["key"] for c in cands] == ["claude|select_model|fp2", "gemini|enable_deep_research|fp1"]
    assert cands[0]["strategy"] == {"by": "role+name", "value": "b"}
    assert selfheal.promotion_candidates({}) == []


def test_record_heal_normalizes_countless_entry_and_still_evicts():
    # A hand-edited / partially-written on-disk entry carrying only strategy_rank
    # (valid per _valid_selector_entry) must still be health-tracked + EVICTABLE —
    # not KeyError-swallowed and stranded forever.
    k, fp = "gemini.enable_deep_research", "fpC"
    rk = selfheal._registry_key(k, fp)
    selfheal.persist_selectors(lambda cur: {**cur, rk: {"strategy_rank": [{"by": "role", "value": "x"}]}})
    assert rk in selfheal.load_selectors()
    rank = [{"by": "role", "value": "x"}]
    for _ in range(3):
        selfheal.record_heal(k, fp, rank, success=False)
    assert rk not in selfheal.load_selectors()  # evicted despite missing counts


# ── resolve_and_click JS guards ──────────────────────────────────────────────
def test_resolve_click_js_is_read_only_unless_doclick():
    js = selfheal._RESOLVE_CLICK_JS
    # exactly one click site, guarded by params.doClick; refuses ambiguous (>1)
    assert "params.doClick" in js and "el.click()" in js
    assert "hits.length > 1" in js  # anti-ambiguity guard
    # never matches on CSS class
    assert "className" not in js and "classList" not in js


def test_resolve_and_click_builds_scope_and_returns_result():
    class P:
        def __init__(self):
            self.params = None

        async def evaluate(self, js, params=None):
            self.params = params
            return {"matched": 1, "clicked": params["doClick"]}

    p = P()
    out = _run(selfheal.resolve_and_click(p, "composer", {"by": "role+name", "value": "button|x"}, do_click=True))
    assert out["clicked"] is True
    assert p.params["scopeClimb"] == 5 and "contenteditable" in p.params["scopeSel"]
    assert p.params["by"] == "role+name"


def test_resolve_and_click_never_raises():
    class Boom:
        async def evaluate(self, js, params=None):
            raise RuntimeError("x")

    assert _run(selfheal.resolve_and_click(Boom(), "composer", {"by": "role", "value": "button"}, do_click=False)) == {}
