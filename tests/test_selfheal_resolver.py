"""PX-2 C4 guards — the heuristic heal resolver (semantic_match / selector_inference
/ ui_fingerprint / shadow_heal_decision) + a golden-corpus eval.

All pure functions, so this is hermetic. The corpus eval is the real bar: for
each seed, semantic_match must re-find the intended control from durable signals
and selector_inference must reproduce the seed's known_good_selector — the
scaffolding for the resolver-eval (eval_resolver) pass-bar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import selfheal

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "selfheal_golden"


def _el(role="button", name="", text="", cls="", haspopup="", testid="", placeholder="", w=100, h=30, visible=True):
    return {
        "role": role, "accessible_name": name, "text": text,
        "attrs": {"testid": testid, "haspopup": haspopup, "pressed": "", "checked": "",
                  "selected": "", "state": "", "placeholder": placeholder, "cls": cls},
        "bounds": {"x": 0, "y": 0, "w": w, "h": h}, "visible": visible,
    }


# ── semantic_match ─────────────────────────────────────────────────────────────
def test_match_prefers_aria_exact_over_text():
    snap = [_el(name="deep research", text="other"), _el(name="", text="deep research")]
    m = selfheal.semantic_match(snap, {"accessible_name": "deep research", "role": ["button"]})
    assert m["element"]["accessible_name"] == "deep research"
    assert m["confidence"] == pytest.approx(0.7)  # aria-exact(1.0)+role(0.4)=1.4, /2.0 → 0.7


def test_match_falls_back_to_text_when_aria_empty():
    snap = [_el(role="menuitemradio", text="Web search"), _el(role="menuitemradio", text="Deep research")]
    m = selfheal.semantic_match(snap, {"accessible_name": "deep research",
                                        "role": ["button", "menuitem", "menuitemradio"]})
    assert m["element"]["text"] == "Deep research"


def test_match_uses_value_tokens_for_model_triggers():
    snap = [_el(name="research", text="Research"), _el(text="Opus 4.8 Max", haspopup="menu")]
    m = selfheal.semantic_match(snap, {"accessible_name": "model", "role": ["button"], "value_matches": "opus"})
    assert m["element"]["text"] == "Opus 4.8 Max"


def test_match_never_scores_css_class():
    # an element matching ONLY by class must not be selected (the #709 failure)
    snap = [_el(text="unrelated", cls="deep-research-pill mat-tonal-button")]
    m = selfheal.semantic_match(snap, {"accessible_name": "deep research", "role": ["button"]})
    # the class contains "deep-research" but it is never a signal → role-only (0.4) still scores
    assert m is not None and "aria" not in m["reason"] and "text" not in m["reason"]
    assert m["reason"] == "role"  # only the role hint matched; class ignored


def test_value_hints_do_not_double_count():
    # both value_contains and value_matches present + matching the same element →
    # only ONE 0.6 contributes (raw role 0.4 + value 0.6 = 1.0 → conf 0.5), so a
    # future both-hints intent can't exceed the confidence ceiling.
    snap = [_el(role="button", text="Opus Flash")]
    m = selfheal.semantic_match(snap, {"role": ["button"], "value_contains": "flash", "value_matches": "opus"})
    assert m["confidence"] == pytest.approx(0.5)
    assert m["reason"].count("value") == 1


def test_match_returns_none_when_nothing_scores():
    assert selfheal.semantic_match([_el(role="div", text="hello")],
                                   {"accessible_name": "deep research", "role": ["button"]}) is None


def test_match_skips_invisible_and_breaks_ties_by_shorter_text():
    snap = [
        _el(name="deep research", text="Deep research and more context blah"),
        _el(name="deep research", text="Deep research"),
        _el(name="deep research", text="hidden", visible=False),
    ]
    m = selfheal.semantic_match(snap, {"accessible_name": "deep research", "role": ["button"]})
    assert m["element"]["text"] == "Deep research"  # shorter leaf wins the tie


def test_match_confidence_in_unit_range():
    m = selfheal.semantic_match([_el(name="deep research")], {"accessible_name": "deep research"})
    assert 0.0 < m["confidence"] <= 1.0


# ── selector_inference ─────────────────────────────────────────────────────────
def test_inference_prefers_role_name_then_text_then_attrs_never_class():
    s = selfheal.selector_inference(_el(role="button", name="Deep research", text="Deep research",
                                        haspopup="menu", testid="dr-btn", cls="x-pill"))
    bys = [st["by"] for st in s]
    assert bys[0] == "role+name"
    assert "testid" in bys and "role+text" in bys and "role+haspopup" in bys
    # CSS class is never emitted
    assert all("class" not in st["by"] and "cls" not in st["by"] for st in s)
    for st in s:
        assert "x-pill" not in st["value"]


def test_inference_text_when_no_aria():
    s = selfheal.selector_inference(_el(role="menuitemradio", name="", text="Deep research"))
    assert s[0] == {"by": "role+text", "value": "menuitemradio|deep research"}


def test_inference_role_only_last_resort():
    s = selfheal.selector_inference(_el(role="button", name="", text="", cls="just-a-class"))
    assert s == [{"by": "role", "value": "button"}]


# ── ui_fingerprint ─────────────────────────────────────────────────────────────
def test_fingerprint_is_order_independent_and_ignores_volatile():
    a = [_el(name="deep research", w=10, h=10, cls="v1"), _el(role="textbox", text="ask")]
    b = [_el(role="textbox", text="ask", w=999, h=999, cls="v2"), _el(name="deep research")]
    assert selfheal.ui_fingerprint(a) == selfheal.ui_fingerprint(b)  # order + bounds + class ignored


def test_fingerprint_changes_on_durable_anchor_change():
    a = [_el(name="deep research")]
    b = [_el(name="advanced research")]
    assert selfheal.ui_fingerprint(a) != selfheal.ui_fingerprint(b)
    assert len(selfheal.ui_fingerprint(a)) == 12


# ── shadow_heal_decision ────────────────────────────────────────────────────────
def test_shadow_heal_decision_hit():
    intent = selfheal.load_intents()["gemini.enable_deep_research"]
    snap = [_el(name="deep research"), _el(role="textbox", placeholder="what do you want to research?")]
    d = selfheal.shadow_heal_decision(snap, intent)
    assert d["match_found"] is True
    assert d["inferred_selector"]["by"] == "role+name"
    assert d["match_confidence"] > 0 and len(d["ui_fingerprint"]) == 12
    assert d["strategy_rank"][0] == d["inferred_selector"]


def test_shadow_heal_decision_miss_still_reports_fingerprint():
    intent = selfheal.load_intents()["gemini.enable_deep_research"]
    d = selfheal.shadow_heal_decision([_el(role="div", text="nope")], intent)
    assert d["match_found"] is False and "ui_fingerprint" in d


# ── golden-corpus eval (the real bar) ────────────────────────────────────────────
def _golden_files():
    return sorted(_GOLDEN.glob("*.json"))


@pytest.mark.parametrize("path", _golden_files(), ids=lambda p: p.name)
def test_resolver_matches_golden_seed(path):
    seed = json.loads(path.read_text(encoding="utf-8"))
    intent = selfheal.load_intents()[f"{seed['platform']}.{seed['intent_id']}"]
    m = selfheal.semantic_match(seed["a11y_snapshot"], intent["signal_hints"])
    assert m is not None, f"{path.name}: resolver found no candidate"
    # the resolver's preferred selector must reproduce the seed's known-good one
    inferred = selfheal.selector_inference(m["element"])[0]
    assert inferred == seed["known_good_selector"], (
        f"{path.name}: inferred {inferred} != known_good {seed['known_good_selector']}"
    )
