"""Gemini "pick the newest Flash" ranker.

Gemini is the platform that already got this right: it opens the model dropdown
on EVERY run, so the highest offered Flash reaches the account with no probe
cadence (unlike Claude, whose popover-skip could strand it for a whole release).

Rewritten 2026-08-01. What changed here is only the removal of pinned versions:
the `floor` (3.5) is gone, the family word and reject list come from policy
instead of being baked into the JS, and the `/3\\.5\\s*flash/i` "legacy"
shadow-comparison — itself a frozen version, kept only for a log line — is
deleted. The ranking ALGORITHM is unit-tested against models.pick_highest_model
(test_model_policy.py); these are source-inspection guards that the JS is wired
correctly, because it can only run in a browser.
"""
import inspect

import models
import research
from conftest import code_only, code_only_deep, js_code_only


def test_ranker_rejects_siblings_before_parsing_the_version():
    js = research._GEMINI_FLASH_RANK_JS
    # Reject-list must be checked BEFORE the version parse (so Flash-Lite etc.
    # can never win even when numerically higher).
    rej = js.find("if (rejected(t)) continue;")
    ver = js.find("flashVer(t)")
    assert rej != -1 and ver != -1 and rej < ver, (
        "the ranker must reject lite/deep-think/pro BEFORE parsing the version."
    )
    # Highest-version-wins with shortest-text tie-break (prefer leaf over wrapper).
    # Version ORDER, not a float compare, since 2026-09-23 — executed in
    # test_model_selection_precision.py (test_the_gemini_ranker_takes_3_10_over_3_8).
    assert "cmpVer(rank[1], bestRank[1])" in js and "t.length < bestLen" in js


def test_reject_list_and_family_come_from_policy_not_the_js():
    """They used to be `t.includes('lite') || … || /\\bpro\\b/` hardcoded in the
    JS, and the family was the bare word 'flash' in two regexes. Both are policy
    now, so a family rename or a new sibling to exclude is one dict edit.

    ⛔ EXECUTED since wave 10.10, and that is the fix for the one failure in ten.
    This used to read the caller's source through `inspect.getsource`, which
    takes the line numbers from import time and re-reads the FILE — so any edit
    above the function after import (a harness, another builder's tree) shifted
    the slice and the assertions read the wrong lines. Reproduced by inserting
    three lines above it after import: FAIL; fifty quiet runs alone: 50/50.
    Now the real caller runs against a page double, with policy answers no
    literal could equal, and the ranker's own arguments are what is judged.
    (Imports are local so this edit stays inside this test's own lines.)"""
    import asyncio

    import pytest
    js =research._GEMINI_FLASH_RANK_JS
    assert "includes('lite')" not in js and "deep think" not in js, (
        "the reject list must be passed in, not baked into the ranker"
    )
    fam, rej = "sentinelfamily", ["sentinel-sibling*", "sentinelpro"]
    seen = {}

    class _Keyboard:
        async def press(self, key):
            seen.setdefault("keys", []).append(key)

    class _Page:
        keyboard = _Keyboard()

        async def evaluate(self, src, arg=None):
            if src == js:
                seen["ranker"] = arg
                return {}                   # no row: the proceed-on-default path
            if arg is None:
                return True                 # the dropdown opens
            seen["trigger"] = arg
            return ""                       # the trigger's own text

    async def _no_sleep(*_a, **_k):
        return None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(research, "p2_family", lambda p: fam if p == "gemini" else "wrong")
        mp.setattr(research, "reject_terms", lambda p: rej if p == "gemini" else [])
        mp.setattr(research.asyncio, "sleep", _no_sleep)
        picked = asyncio.run(research._gemini_select_flash_model(_Page()))
    assert picked is False and seen.get("keys") == ["Escape"], seen
    assert seen["ranker"]["fam"] == fam, seen["ranker"]
    assert seen["ranker"]["reject"] == rej, seen["ranker"]
    assert seen["trigger"] == fam, "the trigger read must look for the same family"


def test_reject_semantics_are_per_term_not_a_blanket_substring():
    """⭐ REGRESSION CAUGHT IN REVIEW. The first draft of the family-only change
    replaced the old per-term rule with a uniform `t.includes(r)`. Row text is
    title+description concatenated, so "pro" as a substring throws away any Flash
    row whose blurb says "productivity" / "improve" / "approve" — and if that
    eliminates every Flash row the run proceeds on whatever the dropdown
    defaulted to, which is the Gemini-Pro Deep-Research hang the Flash family
    choice exists to avoid.

    The rule is now one implementation (models.reject_matches) ported
    character-for-character into the JS, with a trailing `*` marking the terms
    that may match a glued prefix."""
    terms = models.reject_terms("gemini")
    assert "lite*" in terms and "pro" in terms
    # Must reject
    assert models.reject_matches("3.1 flash-litefastest answers", terms)
    assert models.reject_matches("3.1 pro", terms)
    assert models.reject_matches("2.5 deep think", terms)
    # Must NOT reject
    for keep in ("3.5 flash elite tier",
                 "3.5 flash — a productivity boost",
                 "3.5 flash, improved reasoning",
                 "3.5 flashall-around help"):
        assert not models.reject_matches(keep, terms), keep


def test_the_js_reject_port_mirrors_the_python_rule():
    """The two used to disagree — the JS matched `pro` as a substring while the
    Python "mirror" used a left-boundary match, so the unit suite certified
    semantics the browser never ran. Neither can be executed against the other
    here (no browser), so pin the shared shape: the JS must carry the same
    boundary + `*`-prefix logic, expressed without regexes."""
    js = research._GEMINI_FLASH_RANK_JS
    assert "endsWith('*')" in js, "the glue marker must be honoured in the JS"
    assert "leftOk && rightOk" in js, "both boundaries, per term"
    assert "isAlnum" in js
    # Regex-free, for the #913 reason (a lone \\b in a non-raw Python string
    # became a literal backspace and silently killed a gate).
    assert "\\\\b" not in js


def test_ranker_is_activated_and_clicks():
    src = code_only(inspect.getsource(research._gemini_select_flash_model))
    assert '"doClick": True' in src, "the ranker must do the click."
    assert '"doClick": False' not in src, "there is no read-only shadow eval any more."
    # A ranker miss degrades to the same proceed-on-default path as before
    # (WARN + Escape + return False), not a hard break.
    assert "row found in the dropdown" in src and "return False" in src


def test_the_frozen_legacy_comparison_is_gone():
    """`legacy` re-matched a hardcoded /3.5 flash/ on every run purely to print
    a divergence line. It was log-only AND it was a pinned version — the exact
    thing this change removes — so it goes."""
    js = research._GEMINI_FLASH_RANK_JS
    src = code_only_deep(research._gemini_select_flash_model)
    assert "legacy" not in js, "the ranker must not carry a frozen legacy match"
    assert "legacy" not in src
    assert "3.5" not in js, "no version literal may remain in the ranker"


def test_no_version_literal_survives_in_the_ranker_or_its_caller():
    import re
    versioned = re.compile(r"\d+\.\d+\s*(?:flash|pro)|(?:flash|pro)\s*\d+\.\d+", re.I)
    # js_code_only, not the raw constant: the ranker's own `//` comments are
    # prose, and a guard that reads prose is not guarding the code.
    for name, src in (("ranker", js_code_only(research._GEMINI_FLASH_RANK_JS)),
                      ("caller", code_only_deep(research._gemini_select_flash_model))):
        assert not versioned.search(src), f"version literal in the {name}"


def test_the_ranker_never_clicks_the_dropdown_trigger():
    """⭐ THE RENAME-DAY BUG. With version-less family rows now acceptable, on
    the day the platform drops numbers there are no numbered rows anywhere — and
    the shortest visible element containing the family word is plausibly the
    dropdown TRIGGER itself. Clicking it merely shuts the menu, while the ranker
    reports a successful pick. That is precisely the day this fallback exists
    for. Claude's picker got this guard; Gemini's did not."""
    js = research._GEMINI_FLASH_RANK_JS
    assert "never click the trigger" in js
    assert "=== trig) continue;" in js, (
        "the row whose text matches the trigger must be skipped"
    )
    # The guard is inert unless the caller actually resolves and sends the text.
    src = code_only(inspect.getsource(research._gemini_select_flash_model))
    assert "_gm_trigger" in src and '"triggerText": _gm_trigger' in src
    # …and resolving it must not itself throw the whole pick away.
    i = src.find("_gm_trigger = await page.evaluate")
    assert i != -1 and "try:" in src[max(0, i - 40):i], (
        "a failed trigger read must degrade to 'no exclusion', not abort the pick"
    )


def test_post_pick_predicate_is_read_only():
    src = inspect.getsource(research._gemini_select_flash_model)
    # The post-pick trigger re-read confirms the model took, and must NOT reopen
    # the menu (read-only) — it runs after the final Escape.
    assert "model-pick verify" in src
    vi = src.find("model-pick verify")
    esc = src.rfind('press("Escape")', 0, vi)
    assert esc != -1, "the post-pick verify must run AFTER the menu-closing Escape (read-only)."


def test_gemini_opens_the_dropdown_every_run_so_it_needs_no_probe_cadence():
    """⭐ Why the weekly probe is Claude-only. If Gemini ever gains a
    skip-when-already-correct shortcut it inherits Claude's stranding bug and
    will need the same cadence — this pins the assumption the design rests on."""
    src = code_only_deep(research._gemini_select_flash_model)
    assert "model_probe_due" not in src, (
        "Gemini has no cadence because it opens the dropdown unconditionally"
    )
    # No early return that skips the open when the model already looks right.
    open_at = src.find("opened = await page.evaluate")
    assert open_at != -1
    before = src[:open_at]
    assert "return True" not in before, (
        "an early success return before the dropdown opens would strand Gemini "
        "on its current Flash the way Claude's popover-skip stranded Opus"
    )
