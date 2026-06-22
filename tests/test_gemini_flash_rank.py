"""Phoenix (model_refresh) Phase B — Gemini "pick highest Flash" ranker.

B1 (shadow): the version-ranker runs READ-ONLY alongside the legacy frozen
/3.5 flash/ pick (which still does the click), logging would-pick vs legacy.
Behavior is unchanged. The ranking ALGORITHM is unit-tested separately against
models.pick_highest_model (test_model_policy.py); these are source-inspection
guards that the JS ranker is wired correctly and is still shadow-only.
"""
import inspect

import research


def test_ranker_constant_rejects_siblings_before_version():
    js = research._GEMINI_FLASH_RANK_JS
    # Reject-list must be checked BEFORE the version parse (so Flash-Lite etc.
    # can never win even when numerically higher).
    rej = js.find("includes('lite')")
    ver = js.find("flashVer(t)")
    assert rej != -1 and ver != -1 and rej < ver, (
        "the ranker must reject lite/deep-think/pro BEFORE parsing the version."
    )
    assert "deep think" in js and "\\bpro\\b" in js
    # Highest-version-wins with shortest-text tie-break (prefer leaf over wrapper).
    assert "v > bestV" in js and "t.length < bestLen" in js


def test_b1_is_shadow_only():
    src = inspect.getsource(research._gemini_select_flash_model)
    # The ranker runs read-only (doClick False); activation (doClick True) is B2.
    assert '"doClick": False' in src, "B1 must run the ranker read-only (doClick False)."
    assert '"doClick": True' not in src, "B1 must NOT activate the ranker click yet (that's B2)."
    # The legacy frozen pick must still be the one that clicks in B1.
    assert "picked = await page.evaluate" in src, "the frozen /3.5 flash/ pick must still click in B1."
    # A shadow comparison line is logged for the E2E confidence trail.
    assert "SHADOW" in src and "DIVERGES from legacy" in src


def test_post_pick_predicate_is_read_only():
    src = inspect.getsource(research._gemini_select_flash_model)
    # The post-pick trigger re-read confirms the model took, and must NOT reopen
    # the menu (read-only) — it runs after the final Escape.
    assert "model-pick verify" in src
    vi = src.find("model-pick verify")
    esc = src.rfind('press("Escape")', 0, vi)
    assert esc != -1, "the post-pick verify must run AFTER the menu-closing Escape (read-only)."


def test_ranker_floor_comes_from_policy():
    src = inspect.getsource(research._gemini_select_flash_model)
    assert 'p2_floor(\'gemini\')' in src or 'p2_floor("gemini")' in src, (
        "the Flash floor must come from the central policy (p2_floor)."
    )
