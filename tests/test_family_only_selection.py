"""Family-only model selection — P1 tier words, and what gets LEARNED.

Companion to test_model_policy.py (the policy itself) and
test_claude_popover_skip.py (the popover/probe decisions). This file covers the
two remaining halves of the 2026-08-01 change:

  • P1's Pro + thinking-mode confirm, whose word sets moved out of regexes
    buried in a page.evaluate string and into P1_MODEL_POLICY — ⚠ WITHOUT
    being loosened, which is the part most likely to be "fixed" wrongly later.
  • What the pipeline LEARNS. With the floor gone, the learned known-good is
    the step-back target, so a poisoned value outlives the run that recorded it.
"""
import ast
import asyncio
import inspect
import re
import textwrap

import pytest

import models
import research
from conftest import code_only, code_only_deep, js_code_only


# ── P1: the word sets ─────────────────────────────────────────────────────

def test_p1_policy_names_no_model_and_no_version():
    """ChatGPT renames its reasoning mode roughly every release ("o1 pro" →
    "GPT-5 Pro" → …). What is stable is the PLAN word and the family of
    reasoning words — never a product name."""
    pol = models.P1_MODEL_POLICY["chatgpt"]
    for key in ("tier_words", "thinking_words", "downgrade_words", "upgrade_verbs"):
        for word in pol[key]:
            assert not any(ch.isdigit() for ch in word), f"{key} has a version: {word!r}"
            assert "gpt" not in word.lower(), f"{key} names a product: {word!r}"


def test_p1_words_returns_a_lowercase_list_and_never_none():
    assert models.p1_words("chatgpt", "tier_words") == ["pro"]
    assert "reasoning" in models.p1_words("chatgpt", "thinking_words")
    # Unknown platform / key must give [] so a caller can splice straight into
    # JS without a None check (a None there becomes `null` and `.some` throws).
    assert models.p1_words("nope", "tier_words") == []
    assert models.p1_words("chatgpt", "nope") == []


def test_p1_confirm_takes_its_words_from_policy_not_from_regexes():
    src = code_only_deep(research._chatgpt_extended_pro_confirm)
    assert 'p1_words("chatgpt", k)' in src, "the word sets must come from policy"
    for gone in ("extended\\s*pro", "instant|auto|fast|standard", "(pro|plus)"):
        assert gone not in src, f"a hardcoded word regex survived: {gone!r}"


def test_p1_marker_still_requires_a_tier_word_AND_a_thinking_word():
    """⛔ THE ONE THING NOT TO LOOSEN. Accepting a bare thinking word would make
    a future free-tier "Extended" mode read as success — the exact silent
    downgrade this confirm exists to catch. Moving the words to policy must not
    become "match any of them"."""
    src = code_only_deep(research._chatgpt_extended_pro_confirm)
    assert "anyOf(s, P.thinking_words) && anyOf(s, P.tier_words)" in src, (
        "the high-effort marker must require BOTH word kinds in the same element"
    )


def test_p1_marker_order_no_longer_matters():
    """What DID change: the two words no longer have to appear in the frozen
    order "Extended Pro", so "Pro Reasoning" or "Pro (extended)" keeps working.
    An ordered regex is what would silently stop matching on a rename."""
    src = code_only_deep(research._chatgpt_extended_pro_confirm)
    assert "toks(s)" in src and "indexOf(w)" in src, (
        "matching must be token-set based, not a phrase in a fixed order"
    )


def test_p1_confirm_avoids_building_regexes_from_interpolated_words():
    """The #913 lesson: a lone backslash-b inside a non-raw Python string became
    a literal backspace and silently disabled a gate for months. This JS string
    is now interpolated with policy words, so it must not construct word-boundary
    regexes at all."""
    # ⚠ code_only_deep, not getsource: the comment RIGHT ABOVE this code quotes
    # the backslash-b it is warning about, so a raw-source check matches its own
    # explanation. Same trap the comment describes, one level up.
    src = code_only_deep(research._chatgpt_extended_pro_confirm)
    js = src[src.find('page.evaluate("""'):]
    assert "\\\\b" not in js, "no word-boundary escapes in the interpolated JS"


def test_p1_upgrade_cta_still_disqualifies_a_tier_match():
    """"Upgrade to Pro" contains the tier word while meaning the opposite."""
    src = code_only_deep(research._chatgpt_extended_pro_confirm)
    assert "hasVerb" in src and "!hasVerb(trig)" in src


@pytest.mark.parametrize("read,expected", [
    ({"hasExtended": True, "hasPro": False, "hasInstant": True}, "extended"),
    ({"hasExtended": False, "hasPro": True, "hasInstant": True}, "pro"),
    ({"hasExtended": False, "hasPro": False, "hasInstant": True}, "downgrade"),
    ({"hasExtended": False, "hasPro": False, "hasInstant": False}, "unsure"),
])
def test_p1_verdict_mapping_is_unchanged(read, expected):
    """The verdict table is the CONTRACT the caller acts on, and only
    'downgrade' costs anything (one silent selector re-run). Moving the words
    must not have shifted a single cell — including that an Extended/Pro marker
    beats a downgrade word, so a Pro account is never re-run needlessly."""
    class _P:
        async def evaluate(self, script, arg=None):
            return {"trigText": "x", "extText": "", "extTag": "", "extCls": "", **read}
    assert asyncio.run(research._chatgpt_extended_pro_confirm(_P())) == expected


def test_p1_confirm_still_fails_open_on_a_dom_error():
    class _P:
        async def evaluate(self, script, arg=None):
            raise RuntimeError("detached frame")
    assert asyncio.run(research._chatgpt_extended_pro_confirm(_P())) == "unsure"


def test_p1_confirm_fails_open_on_a_non_dict_result():
    class _P:
        async def evaluate(self, script, arg=None):
            return "surprise"
    assert asyncio.run(research._chatgpt_extended_pro_confirm(_P())) == "unsure"


# ── What gets LEARNED ─────────────────────────────────────────────────────

def test_learned_version_comes_from_the_pick_not_the_page_scan():
    """⭐ The trigger read takes the MAX version across every visible button, so
    an upsell chip naming a model the account cannot use ("Try Opus 6") can win
    it. That used to only mis-LOG. Now the value is persisted and later pinned
    to, so a poisoned read outlives its run — the pin then targets a version
    that is not in the menu and the step-back retry is wasted."""
    src = code_only_deep(research.setup_claude_dr)
    assert "_picked_version" in src, "the version actually clicked must be tracked"
    assert '_P2_PICKED_VERSION["claude"] = (\n            _picked_version' in src, (
        "the learned value must prefer the clicked version over the page scan"
    )


def test_trigger_read_rejects_upsell_chips():
    src = code_only_deep(research.setup_claude_dr)
    assert "verbRe" in src and "!verbRe.test(b.textContent" in src, (
        "an upsell chip names the family and a version without being the "
        "selected model"
    )


def test_learning_is_still_a_pure_side_channel():
    """It may only update the step-back TARGET. If a record call ever gates
    anything, a disk failure or a flag flip changes what a run does."""
    src = code_only(inspect.getsource(research.start_agent_no_gemini_wait))
    for line in src.splitlines():
        if "record_known_good(" in line:
            before = line.split("record_known_good")[0]
            assert "if " not in before and "=" not in before, (
                f"record_known_good must be fire-and-forget, not gating: {line!r}"
            )


def test_probe_stamp_result_only_drives_a_warning():
    """The stamp's return value may reach a LOG and nothing else. A silent
    failure turns the periodic check into a per-run popover, so it has to be
    visible — but if it ever gated setup, an unwritable state dir would start
    failing runs outright."""
    src = code_only(inspect.getsource(research.setup_claude_dr))
    lines = src.splitlines()
    idx = [i for i, ln in enumerate(lines) if "record_probe(" in ln]
    assert len(idx) == 1, "exactly one stamp call"
    i = idx[0]
    assert "_PROBE_STAMP_WARNED" in lines[i], (
        "the stamp result must be latched to the once-per-process warning"
    )
    # Everything the branch does is log — no return, no raise, no state change
    # that setup reads back.
    body = "\n".join(lines[i:i + 10])
    for forbidden in ("return ", "raise ", "research_enabled", "opus_selected"):
        assert forbidden not in body, (
            f"a failed stamp must not change what the run does ({forbidden!r})"
        )
    assert "log(" in body


def test_a_failed_stamp_is_not_silent():
    """Fable review: record_probe swallows every write error and returns False,
    so on a read-only home the check is due again every run — the #744 popover
    behaviour, reintroduced invisibly on exactly the machines nobody can see."""
    src = code_only(inspect.getsource(research.setup_claude_dr))
    assert "could not record the model-check timestamp" in src
    assert "overlay_path()" in src, "the message must name the path that failed"


# ── No version literal reaches the browser ────────────────────────────────

def test_no_selection_javascript_carries_a_version_literal():
    """The end-state of the directive: every string the browser executes for
    model selection is family-driven, so a release needs no code change."""
    import re
    versioned = re.compile(
        r"(?:opus|sonnet|haiku|flash|gpt)\s*[-–]?\s*\d|\d+\.\d+\s*(?:pro|flash|opus)", re.I)
    targets = {
        "setup_claude_dr": code_only_deep(research.setup_claude_dr),
        "_gemini_select_flash_model": code_only_deep(research._gemini_select_flash_model),
        "ensure_deep_mode_active": code_only_deep(research.ensure_deep_mode_active),
        "_chatgpt_extended_pro_confirm": code_only_deep(research._chatgpt_extended_pro_confirm),
        # A bare JS constant, so `code_only_deep` can't take it (its tokenizer
        # rejects non-Python) — but the `//` comments inside it must still be
        # stripped, or this guard passes/fails on PROSE. Same rule as everywhere
        # else, applied one layer down.
        "_GEMINI_FLASH_RANK_JS": js_code_only(research._GEMINI_FLASH_RANK_JS),
    }
    offenders = {k: versioned.findall(v) for k, v in targets.items() if versioned.search(v)}
    assert not offenders, f"version literals reaching the browser: {offenders}"


# The test above matches a digit only where it sits NEXT TO a family word, which
# is how a version is written in prose ("Opus 4.8", "3.5 flash"). It is blind to
# the way a floor is actually written in code — `if (v < 4.8) continue;` — and so
# is everything else in the wave: the Claude page double mirrors the picker's
# contract in Python instead of running the script, so a re-added floor strands an
# account whose menu tops out below it while every test stays green. The two
# checks below close that, one on the literals and one on the comparisons.

_JS_MARKERS = ("=>", "document.", "querySelector", "getBoundingClientRect", "window.")

# Every float the selection JS is allowed to contain, with what it is for. A
# model version is a float; so is an epsilon. Only an explicit list tells them
# apart, and adding to it is meant to be a decision someone makes on purpose.
_ALLOWED_FLOATS = {
    "0.001": "float-compare epsilon for an exact pin (Math.abs(v - pin) <= 0.001)",
    "0.95":  "viewport fraction in a Gemini on-screen test "
             "(r.top < window.innerHeight * 0.95) — read off the JS, not guessed",
}

# A version-bearing operand compared against a number. Catches the whole-number
# form the float list cannot see — `v < 5` strands an Opus 4.x account exactly as
# `v < 4.8` does, and families ship whole numbers.
#
# `rank[1]` and not `rank[\d]`: index 0 is the match TIER (exact pin / family /
# fallback) and comparing it to a literal is the correct pattern, so widening
# this to any index would fire on `bestRank[0] === 0` — a false positive is how a
# guard like this gets deleted.
_VERSION_OPERANDS = r"v|ver|vers|version|bestV|verOf\([^)]*\)|(?:best)?[Rr]ank\[1\]"
_VERSION_VS_NUMBER = re.compile(
    rf"(?:\b(?:{_VERSION_OPERANDS})\s*(?:<=|>=|<|>|===|!==|==)\s*-?\d+(?:\.\d+)?)"
    rf"|(?:-?\d+(?:\.\d+)?\s*(?:<=|>=|<|>|===|!==|==)\s*\b(?:{_VERSION_OPERANDS}))"
)


def _js_payloads(fn) -> dict:
    """Every embedded JS string in `fn`, keyed by an excerpt, comments stripped.

    Taken from the AST rather than by scanning the function text, so the numeric
    checks below run on what the BROWSER executes and not on Python's own
    timeouts, sleeps and slice widths — which are numbers too, and would drown
    the signal.
    """
    src = textwrap.dedent(inspect.getsource(fn))
    out = {}
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if not any(m in node.value for m in _JS_MARKERS):
            continue
        out[f"{fn.__name__}:{node.lineno}"] = js_code_only(node.value)
    return out


def _all_selection_js() -> dict:
    out = {}
    for fn in (research.setup_claude_dr, research._gemini_select_flash_model,
               research.ensure_deep_mode_active, research._chatgpt_extended_pro_confirm):
        out.update(_js_payloads(fn))
    out["_GEMINI_FLASH_RANK_JS"] = js_code_only(research._GEMINI_FLASH_RANK_JS)
    return out


def test_the_js_payload_scan_actually_finds_the_pickers():
    """Guard the guard: an AST walk that returns nothing passes both tests below.

    Anchored on the two scripts that DO the selecting, so a rename that moves the
    picker out of reach fails here rather than quietly emptying the scan.
    """
    payloads = _all_selection_js()
    assert len(payloads) >= 15, f"only {len(payloads)} JS payloads found — the scan broke"
    assert any(k.startswith("setup_claude_dr:") and "bestRank" in v
               for k, v in payloads.items()), "the Claude picker is not in the scanned set"
    gemini = payloads.get("_GEMINI_FLASH_RANK_JS", "")
    assert "bestRank" in gemini and "isAlnum" in gemini, (
        "the Gemini ranker is not in the scanned set")


_FLOAT_LITERAL = re.compile(r"(?<![\w.])\d+\.\d+(?![\w.])")


def _unexplained_floats(js: str) -> list:
    """Floats in a JS payload that are not on the allowlist.

    A function, not an inline comprehension, so the guard-the-guard below runs
    the same code the guard does — the alternative restates the logic and then
    passes no matter what the real check became.
    """
    return sorted({f for f in _FLOAT_LITERAL.findall(js) if f not in _ALLOWED_FLOATS})


def test_every_float_in_the_selection_js_is_an_allowed_epsilon():
    """A model version is a float. So is an epsilon. Nothing else may be either.

    `if (v !== null && v < 4.8) continue;` inside the Claude picker is the exact
    line this catches: on an account whose menu tops out at Opus 4.7 the picker
    then selects nothing, Step 1B fails and setup returns False — the stranding
    the family-only change existed to remove, reintroduced in one line.
    """
    offenders = {}
    for name, js in _all_selection_js().items():
        bad = _unexplained_floats(js)
        if bad:
            offenders[name] = bad
    assert not offenders, (
        f"unexplained float literals in the selection JS: {offenders}. If one of "
        f"these is a threshold rather than a model version, add it to "
        f"_ALLOWED_FLOATS with what it is for; if it is a version, it strands "
        f"every account whose menu tops out below it."
    )


def test_no_selection_javascript_compares_a_version_against_a_number():
    """The whole-number half — `v < 5`, `verOf(t) >= 6`, `rank[1] > 4`.

    A family ships whole numbers ("Opus 5"), so the float list above cannot be
    the only check. Legitimate comparisons here are against values passed IN
    (`pin`, `below`, `bound`, `bestV`), which is the point: the browser is told
    what to aim for, it never decides from a literal.
    """
    offenders = {name: _VERSION_VS_NUMBER.findall(js)
                 for name, js in _all_selection_js().items()
                 if _VERSION_VS_NUMBER.search(js)}
    assert not offenders, (
        f"a version is compared against a hardcoded number: {offenders}. The "
        f"bound must arrive as an argument (pin/below/bound), never as a literal."
    )


def test_the_float_check_would_catch_a_version_written_as_a_float():
    """Guard the guard, through `_unexplained_floats` itself."""
    assert _unexplained_floats("if (v < 4.8) continue;") == ["4.8"]
    assert _unexplained_floats("if (v === 3.5) return;") == ["3.5"]
    for allowed in _ALLOWED_FLOATS:
        assert _unexplained_floats(f"Math.abs(v - pin) <= {allowed}") == [], (
            f"{allowed} is on the allowlist and must not be reported")
    assert _unexplained_floats("t.slice(0, 40)") == [], "an integer is not a version"


def test_the_version_comparison_check_would_catch_a_real_floor():
    """Guard the guard, through the same regex the check uses.

    Each of these is a floor someone would plausibly write; each must register.
    The last two must not, or the guard fires on the argument-driven comparisons
    that are the correct pattern and gets deleted for being noisy.
    """
    for floor in ("if (v !== null && v < 4.8) continue;",
                  "if (v < 5) continue;",
                  "if (verOf(t) < 4.8) continue;",
                  "if (rank[1] >= 6) return;",
                  "if (4.8 > v) continue;"):
        assert _VERSION_VS_NUMBER.search(floor), f"no longer caught: {floor!r}"
    for ok in ("if (pin != null && Math.abs(v - pin) <= 0.001) {",
               "if (below != null && v >= below) continue;"):
        assert not _VERSION_VS_NUMBER.search(ok), f"false positive on: {ok!r}"
