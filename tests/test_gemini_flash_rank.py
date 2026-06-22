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


def test_b2_ranker_is_activated_and_clicks():
    src = inspect.getsource(research._gemini_select_flash_model)
    # B2: the ranker now does the click (doClick True); the read-only shadow
    # (doClick False) and the frozen /3.5 flash/ block are gone.
    assert '"doClick": True' in src, "B2 must activate the ranker click (doClick True)."
    assert '"doClick": False' not in src, "the read-only shadow eval must be removed in B2."
    assert 'Step 2: click the "3.5 Flash" model row' not in src, (
        "the frozen /3.5 flash/ literal pick must be superseded by the ranker."
    )
    # The legacy comparison is still logged on success for the E2E trail.
    assert "DIVERGES from legacy" in src and "legacy /3.5 flash/" in src
    # A ranker miss degrades to the same proceed-on-default path as the old
    # frozen miss (WARN + Escape + return False), not a hard break.
    assert "no Flash >= floor found" in src and "return False" in src


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
