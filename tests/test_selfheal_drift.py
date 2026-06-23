"""PX-4 drift-canary tests (selfheal.drift_canary / drift_baseline).

Pure functions over shadow records — no live page, no disk state. Verifies the
verdict logic: a heal rests on the durable anchor semantic_match found, and the
STRENGTH of that anchor (heal_confidence) is the drift signal — robust to the
noisy ui_fingerprint.
"""
import selfheal


def _rec(intent, found=True, conf=0.6, fp="fp", reason="aria~name,role"):
    return {
        "intent": intent,
        "heal_match_found": found,
        "heal_confidence": conf,
        "ui_fingerprint": fp,
        "heal_reason": reason,
    }


def test_drift_canary_stable_on_strong_anchor():
    recs = [_rec("gemini.enable_deep_research", conf=0.55) for _ in range(4)]
    v = selfheal.drift_canary(recs)["gemini.enable_deep_research"]
    assert v["verdict"] == "stable"
    assert v["found_rate"] == 1.0 and v["n"] == 4 and v["mean_confidence"] == 0.55


def test_drift_canary_weak_on_low_confidence():
    # chatgpt.select_model in the real corpus: 0.20, role-only. Benign but weak.
    recs = [_rec("chatgpt.select_model", conf=0.20, reason="role") for _ in range(4)]
    out = selfheal.drift_canary(recs)["chatgpt.select_model"]
    assert out["verdict"] == "weak" and out["top_reason"] == "role"


def test_drift_canary_drift_when_resolver_loses_element():
    recs = [
        _rec("gemini.select_model", found=True, conf=0.5),
        _rec("gemini.select_model", found=False, conf=0.0),
    ]
    assert selfheal.drift_canary(recs)["gemini.select_model"]["verdict"] == "drift"


def test_drift_canary_drift_on_confidence_drop_vs_baseline():
    good = [_rec("claude.select_model", conf=0.85) for _ in range(3)]
    base = selfheal.drift_baseline(good)
    assert base["claude.select_model"] == 0.85
    now = [_rec("claude.select_model", conf=0.55) for _ in range(3)]  # 0.30 drop > margin
    assert selfheal.drift_canary(now, baseline=base)["claude.select_model"]["verdict"] == "drift"


def test_drift_canary_fingerprint_noise_is_not_drift():
    # 4 DISTINCT fingerprints but a strong, consistent anchor → stable (the canary
    # keys on anchor strength, not the noisy fingerprint).
    recs = [_rec("chatgpt.enable_deep_research", conf=0.55, fp=f"fp{i}") for i in range(4)]
    v = selfheal.drift_canary(recs)["chatgpt.enable_deep_research"]
    assert v["fingerprints"] == 4 and v["verdict"] == "stable"


def test_drift_canary_ignores_non_resolver_and_empty():
    assert selfheal.drift_canary([]) == {}
    assert selfheal.drift_canary([{"intent": "x"}]) == {}  # no heal_match_found → skipped


def test_drift_baseline_roundtrip_no_false_drift():
    recs = [_rec("gemini.enable_deep_research", conf=0.55) for _ in range(4)]
    base = selfheal.drift_baseline(recs)
    # same window vs its own baseline → stable (a small/zero drop is not drift)
    assert selfheal.drift_canary(recs, baseline=base)["gemini.enable_deep_research"]["verdict"] == "stable"
