"""Centralized model constants for the BE.

Single source of truth for every LLM model used by the daemon, narrator,
vision tier, and pipeline. Override any value at runtime via env var
(defaults are the production-tuned current GA / latest-stable model per
provider). Bumping a model = edit one line here or set one env var; no
scatter-shot search-and-replace across research.py + vision.py +
narrate.py.

Refreshed 2026-05-28 against:
  - https://docs.claude.com (Claude model overview + Computer Use docs)
  - https://ai.google.dev (Gemini model release notes + deprecations)
"""
import json
import os
import re
import time
from pathlib import Path

# ── Anthropic Claude ────────────────────────────────────────────────────
# CUA — Computer Use Agent for browser automation. Sonnet 4.6 is the
# Anthropic-recommended model for Computer Use as of 2026: it posts the
# largest OSWorld jump in the 4.x lineup AND is ~40% cheaper than Opus
# per token, which compounds at our CUA call volume. The beta header
# `computer-use-2025-11-24` continues to work on Sonnet — only the model
# name changes vs. the prior Opus default.
CUA_MODEL = os.environ.get("CUA_MODEL", "claude-sonnet-4-6")

# Vision — light-weight panel/state extraction (login-wall detection,
# pro-tier detection, etc.). Used to follow CUA_MODEL by accident
# (those call sites read CUA_MODEL even though they don't drive the
# browser); now decoupled so CUA + vision can evolve independently.
# Bumped 2026-07-22 to Sonnet 5 (from 4.6) — current-gen Sonnet, better
# vision quality at the same tier for these moderate-stakes single-shot
# reads. Decoupled from CUA_MODEL, which stays on 4.6 (the Anthropic-
# recommended Computer-Use model); this is the vision light tier only.
VISION_LIGHT_MODEL = os.environ.get("VISION_LIGHT_MODEL", "claude-sonnet-5")

# Vision — high-stakes / retry-after-failure path. Opus 5 is the current
# Anthropic flagship (supersedes 4.8) with the highest-fidelity vision
# input. Reserved for the vision tier-2 verifier's escalation branch
# where we'd rather pay 5x to get the right answer than retry Sonnet
# repeatedly. Bumped 2026-07-26 (4.8 → 5), following the same hand-bump
# as VISION_LIGHT_MODEL; this constant is NOT auto-refreshed — the
# Phoenix model policy governs the P2 web-UI pick, not our API models.
VISION_HEAVY_MODEL = os.environ.get("VISION_HEAVY_MODEL", "claude-opus-5")

# Narrator — per-agent narration during pipeline runs. As of 2026-05-28
# Gemini 3.5 Flash (GEMINI_TEXT) is the primary; Haiku 4.5 here is the
# cross-vendor FALLBACK for Google regional blips. The swap aligned the
# narrator with every other BE text task (summary, title fallback, URL
# extractor) which already runs on Gemini 3.5 Flash. Set
# DG_NARRATOR_USE_GEMINI=0 to force the fallback path globally.
NARRATOR_HAIKU = os.environ.get("DG_NARRATOR_HAIKU_MODEL", "claude-haiku-4-5")

# Title generation + API-key-validation tests — short, cheap Haiku
# calls that just need a working response from the user's Anthropic
# key. Separate env var from the narrator so each surface can swap
# models independently.
TITLE_HAIKU = os.environ.get("TITLE_MODEL", "claude-haiku-4-5")

# ── Google Gemini ───────────────────────────────────────────────────────
# General-purpose text — research summary, URL extraction from Gemini
# Deep Research page, narrator fallback when Haiku is unavailable.
# `gemini-2.5-flash` hard-deprecates 2026-06-17 on the generativelanguage
# API path (Vertex extended to 2026-10-16). `gemini-3.6-flash` is the
# current GA Flash (verified against the live model list 2026-07-26 —
# 3.6 ships without a `-preview` suffix, unlike 3-flash / 3.1-flash-live)
# and a drop-in successor to 3.5 — same speed class, same multimodal
# support. Bumped 2026-07-26 (3.5 → 3.6).
GEMINI_TEXT = os.environ.get("GEMINI_TEXT_MODEL", "gemini-3.6-flash")

# Vision narrator (narrate.py) — agent-side screenshot panel reader.
# Multimodal Gemini call (image + structured-output schema). Same model
# family as GEMINI_TEXT but kept as its own env var so the narrator can
# be tuned independently from text-only summary/extractor sites.
GEMINI_NARRATE = os.environ.get("GEMINI_NARRATE_MODEL", "gemini-3.6-flash")

# Vision narrator fallback — Gemini Pro hedge against a Flash-specific
# outage. Kept on 2.5-pro pending 3.x-pro reaching GA (3.1-pro is still
# preview as of 2026-05-28); 2.5-pro deprecation is 2026-10-16, giving
# ample runway to migrate when the next Pro lands.
GEMINI_NARRATE_FALLBACK = os.environ.get("GEMINI_NARRATE_FALLBACK_MODEL", "gemini-2.5-pro")


# ── Phoenix (model_refresh) — P2 deep-research model POLICY ──────────────
# NB: "Phoenix" here is the model-FRESHNESS concept — a
# DISTINCT concept from research.py's unrelated daemon restart/resume/
# checkpoint "Phoenix". All symbols are namespaced `model_refresh` / `p2_*`
# to avoid grep-confusion with that subsystem.
#
# This is the SINGLE SOURCE OF TRUTH for the model + Deep-Research tool +
# thinking config that the P2 pipeline drives in the live Claude.ai /
# ChatGPT / Gemini WEB UIs (a separate concern from the API/harness model
# constants above — those drive SDK calls, this drives what the user gets in
# deep research). It de-duplicates the model literals that were previously
# scattered across research.py (the floor `>= 4.8` in ~3 page.evaluate JS
# sites + the byte-identical CUA directive at two call sites) and prompts.py.
#
# ⭐ (2026-08-01) NO VERSION LITERAL LIVES HERE ANY MORE — owner directive:
# "we don't need models hard coded… only model family is gonna be there and both
# dom and CUA (fallback) must auto heal on every model release."
#
# The old `floor` keys (claude 4.8 / gemini 3.5) are GONE. A frozen floor rotted
# in two directions at once: it stopped protecting anything once the family moved
# past it, and — because `model_ok` was `trigger >= floor` — it let setup decide
# the account was fine and skip opening the picker entirely, which is how P2 sat
# on Opus 4.8 for the whole Opus-5 rollout. The rule is now purely FAMILY +
# HIGHEST-OFFERED: among the rows the platform actually shows, take the highest
# member of the family. That cannot pick a downgrade (nothing offered is higher)
# and it needs no constant, so a new release needs no code change.
#
# Never-downgrade is now a LEARNED value, not a policy key: `p2_known_good()`
# records the last version that verified into Deep Research and is used ONLY as
# the pin target when the newest model fails (see record_known_good). It is
# deliberately NOT a picker floor — a learned floor above what an account is
# offered would strand a run that works today.
#
# Per-platform reality (do not assume symmetry):
#   • claude  — one model popover. Setup avoids opening it when the trigger
#               already reads the family + effort (the #744 / double-modal fix),
#               so the highest-offered upgrade needs the PROBE CADENCE below to
#               reach the account at all.
#   • gemini  — the dropdown is opened on EVERY run, so highest-offered already
#               reaches it; no cadence needed. `reject` shapes the family
#               (Flash, not Flash-Lite / Pro / Deep Think).
#   • chatgpt — NO model picker in P2 (only the Deep-Research toggle); `model`
#               is None and there is nothing to bump today.
P2_MODEL_POLICY = {
    "claude": {
        # (2026-07-30) `thinking` is FALSE on purpose, not an oversight. Opus 5
        # dropped the separate Thinking toggle that Opus 4.x carried inside the
        # Effort submenu — effort IS the reasoning lever now. While this stayed
        # True, setup opened the model popover on EVERY run purely to reach a
        # control that no longer exists, logged "Step 1D WARN: 'Thinking' toggle
        # not found", then handed the quality knobs to the CUA validate layer —
        # which is the second model-menu interaction users reported as "it opens
        # the model selector twice". Consumers read this key, never a literal:
        # research.py gates Step 1D on it and skips the advisory that would
        # otherwise report thinking as permanently unconfirmed.
        "family": "opus", "pick": "highest",
        "effort": "max", "thinking": False, "tool": "research",
        # ⭐ (2026-08-14) The family to use when the account's plan does not
        # include `family` at all. On a non-pro Claude account every Opus row in
        # the model menu is a sales chip, so the picker correctly refuses all of
        # them and setup FAILED — and the run then went out on whatever the menu
        # happened to be defaulting to, at whatever effort that model was left
        # on, with the CUA fallback still hunting for an Opus that does not
        # exist. Sonnet was already what those runs used; it just arrived by
        # accident instead of by choice, which is why the effort lever never ran.
        #
        # ⛔ A FAMILY, NOT A MODEL — the same standing rule as `family`. "Sonnet"
        # keeps pointing at the newest Sonnet forever; "Sonnet 4.6" is a floor
        # that rots in both directions. Everything downstream (highest-offered,
        # the weekly probe, effort=max) is family-generic and applies unchanged.
        #
        # ⚠ This is a FALLBACK, never a preference: it is reached only when the
        # DOM has proved the family is offered exclusively as sales prompts. A
        # pro account never touches it — see the `chips` signal in
        # research.py's _probe_opus_js for what "proved" means.
        "free_family": "sonnet",
    },
    "gemini": {
        "family": "flash", "pick": "highest",
        # ⚠ THE TRAILING `*` IS LOAD-BEARING, not decoration. Menu rows are
        # title+description CONCATENATED ("3.1 Flash-LiteFastest answers"), so
        # some terms must match a glued prefix while others must not:
        #   "lite*"  → left boundary + prefix. Catches "flash-litefastest";
        #              does NOT catch "elite" (no boundary before "lite").
        #   "pro"    → whole word. Catches " Pro "; does NOT catch
        #              "productivity" / "improve" / "approve", which is why it
        #              cannot be a prefix match — a Flash row whose description
        #              happens to say "productivity" would be thrown away, and
        #              if that eliminates every Flash row the run proceeds on
        #              whatever the dropdown defaulted to (the Gemini-Pro Deep
        #              Research hang this family choice exists to avoid).
        # `reject_matches()` is the single implementation; the JS ranker uses a
        # character-level port of it rather than a second set of regexes.
        "reject": ["lite*", "deep think", "pro"],
        "thinking": "extended", "tool": "deep research",
    },
    "chatgpt": {
        "model": None, "tool": "deep research",
    },
}

# ── Phase 1 — ChatGPT Pro + thinking-mode word policy ────────────────────
# P1 has no version lever either: what it needs is the PRO TIER with a
# reasoning/thinking mode on. The words below are the only thing that can rot,
# so they live here (one dict, unit-tested) instead of as regex literals buried
# inside a page.evaluate string in research.py.
#
# ⚠ DELIBERATELY NOT LOOSENED. The confirm still requires a thinking word AND a
# tier word in the SAME short marker — dropping to "any thinking word" would
# make a future free-tier "Extended" mode read as success, which is the exact
# failure this is meant to catch. What changed is that the two words no longer
# have to appear in one frozen order ("Extended Pro"): any order matches, so a
# rename to "Pro Reasoning" or "Pro (extended)" keeps working.

# The sales verbs, in ONE place — read by `is_upsell` (which the P2 model
# rankers and their JS ports use), by the ChatGPT tier picker's
# `upgrade_verbs`, and by the CUA mission rendered from that key. Three
# surfaces, one list, so none of them can develop its own idea of what a sales
# prompt looks like.
# ⭐ "unlock" joined on 2026-08-14. Three other guards in research.py already
# treated it as a sales verb while this list did not, so "Unlock Opus 5.2" was a
# chip that PARSED a version and outranked every genuine row — finding 2's exact
# mechanism, using a word the codebase had already recognised elsewhere for
# months. A shared list that is missing a member the unshared copies have is
# worse than no sharing: it reads as settled.
UPSELL_VERBS = ("upgrade", "subscribe", "unlock", "get", "try")

# How far after the verb the noun may sit and still be the verb's object.
# "Get Opus with Max" is 4; "Upgrade your plan to get Opus" is 17. Wide enough
# for a preposition or two, far short of a sentence.
UPSELL_WINDOW = 24


# ── Reaching the pipeline core from a sibling module ────────────────────
#
# The pipeline lives in `research.py` in a source checkout and in
# `_sr_core.<abi>.pyd` in the compiled wheel, where `research.py` is replaced by
# a ~48-line launcher shim that exports only `main` (tools/build_compiled.py).
# So `from research import <helper>` — which vision.py and narrate.py both used
# to reach the canonical API-key resolvers — raises ImportError in every shipped
# build, and both call sites swallowed it, so the failure was invisible and each
# caller silently degraded to a bare `os.environ` read.
#
# Named in one place because the two names are one fact, and because a third
# module reaching for a core helper must not have to rediscover this.
CORE_MODULE_NAMES = ("research", "_sr_core")


def core_attr(name: str):
    """Return `name` from the pipeline core module, or None if it isn't there.

    ⚠ Prefers a module that is ALREADY imported. By the time any sibling
    module's runtime code asks for a core helper, the core is loaded, so this
    costs a dict lookup — where importing `_sr_core` cold is a ~3s
    native-extension load nobody should pay from inside a key lookup. The real
    import is the fallback, for a genuinely standalone caller.

    ⓘ Never raises and never reports failure: this is the same "best effort,
    fall through to the next key source" contract the callers already had. What
    changed is that the compiled build now HAS a next source that works.
    """
    import importlib
    import sys

    for mod_name in CORE_MODULE_NAMES:
        try:
            # ⚠ `getattr` is not safe by itself here. A module caught PARTWAY
            # through its own import is already in sys.modules, and a module-level
            # `__getattr__` (or a lazy-loader shim) can raise from it — which
            # would propagate out of a best-effort lookup and take the caller's
            # remaining key sources down with it.
            fn = getattr(sys.modules.get(mod_name), name, None)
        except Exception:
            continue
        if fn is not None:
            return fn
    for mod_name in CORE_MODULE_NAMES:
        try:
            fn = getattr(importlib.import_module(mod_name), name, None)
        except Exception:
            continue
        if fn is not None:
            return fn
    return None


def gemini_gen_config(*, temperature: float, max_tokens: int,
                      thinking_budget_env: bool = True, **extra) -> dict:
    """The shared `generationConfig` builder for every Gemini TEXT call.

    ⓘ "Every Gemini call" would be overstating it: the vision-URL extractor
    hand-builds its own, deliberately, and is pinned that way — it is the
    200-vs-400 differential that identified the rejected thinking field in the
    first place, so it has to stay an INDEPENDENT witness rather than share a
    builder with the code it exonerates.

    ⭐ WHY IT LIVES HERE and not in research.py. Four builders in research.py
    were consolidated on 2026-08-05; narrate.py kept a fifth hand-rolled copy
    and had to take the same fix by hand. It could not share the research.py
    one — a compiled sibling cannot import from the core (see `core_attr`) — so
    the shared home has to be a module both already import, which is this one.
    research.py's `_gemini_gen_config` now delegates here.

    ⚠ `thinking_budget_env=False` is the EXPLICIT OPT-OUT, and it exists
    because consolidating naively would undo a deliberate refusal. The panel
    narrator sends a `responseSchema`, and a truncated structured response is a
    worse failure there than a slow one, so that call site deliberately does NOT
    honour `DG_GEMINI_THINKING_BUDGET`. Silence would have made it honour it.

    ⛔ `thinkingConfig` is OMITTED by default on purpose — the live endpoint
    rejects `{"thinkingBudget": 0}` with HTTP 400 INVALID_ARGUMENT and names no
    field. The env var re-enables it for whoever wants to test a future model
    that accepts it. Thinking therefore being ON by default is why every caller
    of this builder needs a token ceiling sized for reasoning plus the answer.
    """
    cfg = {"temperature": temperature, "maxOutputTokens": int(max_tokens)}
    if thinking_budget_env:
        _tb = os.environ.get("DG_GEMINI_THINKING_BUDGET", "").strip()
        if _tb:
            try:
                cfg["thinkingConfig"] = {"thinkingBudget": int(_tb)}
            except ValueError:
                pass
    cfg.update(extra)
    return cfg


def gemini_empty_reason(payload: dict) -> str:
    """Why a 200 came back with no text: the finish reason, or a block reason.

    A refusal and an empty success are different faults with different fixes — a
    blocked prompt is ours to change, a token budget spent on thinking is a
    config value — and a single "no text" message describes neither.

    ⓘ Here rather than in research.py for the same reason `gemini_gen_config` is:
    narrate.py needs it, and a compiled sibling cannot import from the core.
    research.py's `_gemini_empty_reason` delegates."""
    try:
        cand = ((payload or {}).get("candidates") or [{}])[0] or {}
        finish = str(cand.get("finishReason") or "").strip()
        block = str(((payload or {}).get("promptFeedback") or {})
                    .get("blockReason") or "").strip()
    except Exception:
        finish = block = ""
    parts = [p for p in (f"finishReason={finish}" if finish else "",
                         f"blockReason={block}" if block else "") if p]
    return ", ".join(parts) or "no finishReason and no blockReason"

P1_MODEL_POLICY = {
    "chatgpt": {
        # ⭐ (2026-08-03) ChatGPT has NO separate thinking control — effort and
        # model are ONE menu. The captured menu is `Instant 5.5 / Medium / High /
        # Extra High / Pro`, all `menuitemradio` in a single list: choosing the
        # tier IS choosing the reasoning level. While this was unstated, the CUA
        # mission ended with "if a thinking / extended-thinking / reasoning
        # toggle is visible, enable it" and the vision hint repeated it, so both
        # surfaces spent steps hunting a control that does not exist — the same
        # waste Claude's `thinking: False` (P2) was added to stop. Consumers read
        # `has_thinking_control()`, never this key directly.
        "thinking_control": False,
        # The subscription tier. Stable — this is the plan name, not a model.
        #
        # ⚠ These words are ALSO the P2 selection target for ChatGPT. The pill
        # that opens the model menu is the same control in both phases and the
        # menu is the same list, so P2_MODEL_POLICY deliberately does NOT carry a
        # second copy — a second copy is what let the Gemini hover helper freeze
        # its own private model policy and drift from the ranker.
        "tier_words": ["pro"],
        # Reasoning-mode words, any one of which (WITH a tier word) marks the
        # high-effort mode. Add to this list on a rename; never remove "pro".
        "thinking_words": ["extended", "thinking", "reasoning"],
        # Names of the LOW-effort default modes. A closed list by necessity —
        # there is no shape to test for "this mode is the cheap one" — but a
        # miss here only produces 'unsure', which proceeds (fail-open).
        "downgrade_words": ["instant", "auto", "fast", "standard"],
        # An "Upgrade to Pro" CTA contains the tier word without being evidence
        # of it; these verbs disqualify a match. ⚠ Not a second list — this IS
        # `UPSELL_VERBS`, which `is_upsell` and the P2 model rankers also use,
        # so the tier picker, the CUA mission rendered from these words, and the
        # model rankers cannot drift apart on what a sales prompt looks like.
        "upgrade_verbs": UPSELL_VERBS,
        # ⭐⭐ (2026-08-17, from a live capture) THE MENU IS TWO LEVELS NOW.
        # The tier rows did not disappear and they did not become a slider — they
        # moved one level down. The picker opens the pill and sees three rows,
        # `Advanced / Model … / Effort …`, none of which names a tier, so it
        # correctly reports "no row names 'pro'" and stops at the front door.
        #
        # Two words get it the rest of the way. `effort_row_words` names the row
        # whose submenu holds `Instant / Medium / High / Extra High / Pro`;
        # `advanced_words` names the toggle that reveals that row when the menu
        # opens in its compact state. Both live here rather than in the page
        # script for the same reason every other word does: a rename is then one
        # policy edit with a test behind it, not a regex buried in a JS string.
        #
        # ⚠ The compact/expanded state PERSISTS PER ACCOUNT, so neither entry
        # state is the "normal" one and both have to work. Matching is by the
        # row's own leading label, never by the whole row text — the row reads
        # "EffortInstant" (label plus current value concatenated), so a whole-text
        # equality test would break the moment the effort changes, which is
        # precisely the thing this path exists to change.
        "effort_row_words": ["effort"],
        "advanced_words": ["advanced"],
    },
}


def p1_words(platform: str, key: str) -> list:
    """A P1 word list as a lowercase list of strings. Empty list for an unknown
    platform/key so a caller can splice it into JS without a None check."""
    v = (P1_MODEL_POLICY.get(platform, {}) or {}).get(key)
    return [str(w).lower() for w in v] if isinstance(v, (list, tuple)) else []


def has_thinking_control(platform: str, phase: int = 2) -> bool:
    """⭐ THE ONE ANSWER to "does this platform expose a SEPARATE thinking /
    extended-reasoning control that has to be switched on after the model is
    chosen?" — read by the DOM tier, the vision hint and the CUA mission alike.

    Three surfaces used to answer it three ways and only one of them was right.
    Claude's P2 entry has said `thinking: False` since Opus 5 dropped the toggle,
    and research.py gates its Step 1D on that — but P1's ChatGPT mission still
    told the agent to "enable the thinking toggle if visible" and the vision
    hotspot hint said the same, so on a platform where effort and model are one
    menu both surfaces burned steps looking for a control that does not exist.
    A per-surface literal is exactly what rots; this is the single reader.

    The answer is derived from the policy each phase already keeps, so there is
    no third dict to drift:
      * phase 1 → P1_MODEL_POLICY[platform]["thinking_control"]
      * phase 2 → the merged (overlay-aware) `thinking` label

    Truthiness is normalised, not assumed: P2 stores a bool for Claude and the
    control's NAME for Gemini ("extended"), and a blank/whitespace string is not
    a control. An unknown platform or a missing key answers False — the safe
    direction, because the cost of a wrong False is one un-set quality knob while
    the cost of a wrong True is every surface hunting a phantom control.
    """
    if int(phase) == 1:
        raw = (P1_MODEL_POLICY.get(platform, {}) or {}).get("thinking_control")
    else:
        raw = p2_labels(platform).get("thinking")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return bool(raw.strip())
    return False


def p1_select_pro_directive() -> str:
    """The CUA/vision mission that drives ChatGPT's Phase-1 tier selection.

    Rendered from P1_MODEL_POLICY the way the two Claude directives are, for the
    same reason: the thinking-toggle sentence was a literal, ChatGPT has no such
    control, and a literal cannot be switched off by a policy edit. The sentence
    now appears only when `has_thinking_control` says the platform actually has
    one, so a future ChatGPT that grows a separate toggle re-enables it with one
    policy edit and a test — and today's agent stops hunting.

    ⚠ The tier word comes from `tier_words[0]`, never a hardcoded "Pro", and the
    upgrade verbs are the same list the confirm uses — so the mission and the
    post-select DOM check can never disagree about what an upsell looks like.
    """
    tiers = p1_words("chatgpt", "tier_words") or ["pro"]
    tier = tiers[0].capitalize()
    verbs = p1_words("chatgpt", "upgrade_verbs") or ["upgrade"]
    cta = " / ".join(f'"{v.capitalize()} to {tier}"' for v in verbs[:2])
    parts = [
        f'Task: In the model selector, choose the option whose label contains the '
        f'word "{tier}" (it will look like "<model name> {tier}" or "{tier} mode" — '
        f'the model name and version number change over time and DO NOT matter; '
        f'match on "{tier}"). If more than one {tier} option is offered, take the '
        f'highest-numbered one. Ignore any {cta} button — that is a sales prompt, '
        f'not the model.',
    ]
    if has_thinking_control("chatgpt", 1):
        parts.append(
            "If a separate thinking / extended-thinking / reasoning toggle is "
            "visible, enable it."
        )
    else:
        # Stated positively rather than omitted: an agent told only "select Pro"
        # still goes looking for a reasoning switch, because every other platform
        # in its context has one.
        parts.append(
            f"There is NO separate thinking / reasoning toggle on this platform — "
            f"the effort level and the model are the SAME menu, so selecting "
            f"{tier} is all that is needed. Do not go looking for one."
        )
    parts.append(
        "Do NOT type a message. After the tier is selected, make sure the "
        f"model-selector menu/popover is CLOSED (it usually closes itself on "
        f"selection; if it's still open, press Escape or click empty space once) "
        f"so it can't sit over the message composer. When it is confirmed "
        f"selected and the picker is closed, say \"{tier} mode selected\"."
    )
    return " ".join(parts)


def _flag_on(name: str, default: str = "0") -> bool:
    """Codebase DG_* boolean idiom (mirrors vision.py / research.py)."""
    return (os.environ.get(name, default) or "").strip().lower() not in ("0", "false", "no", "")


def model_refresh_enabled() -> bool:
    """Kill-switch for the learned-model layer (overlay reads + writes + the
    probe cadence). Default ON as of 2026-08-01: with the floor literals gone,
    the learned known-good IS the fallback machinery, and leaving it dark meant
    nothing was ever learned. Set DG_MODEL_REFRESH_ENABLED=0 to go back to
    pure family+highest-offered with no persistence.

    ⚠ A LIVE env read, not an import-time constant. The old module constant
    could not be flipped without restarting the daemon, and a test that set the
    env var saw nothing (it had to reach in and monkeypatch the constant)."""
    return _flag_on("DG_MODEL_REFRESH_ENABLED", "1")


def model_probe_days() -> float:
    """How stale the last model-menu probe may get before setup opens the
    popover to look for a newer family member. Live env read; default 7 days
    (this is the 'weekly canary', run on the pipeline's own authenticated page
    rather than as a separate scheduled process)."""
    try:
        v = float(os.environ.get("DG_MODEL_PROBE_DAYS", "7") or 7)
    except (TypeError, ValueError):
        return 7.0
    return v if v > 0 else 7.0


# Runtime overlay: the LEARNED half of model selection — per-platform
# `known_good` (the pin target when the newest model fails) and `last_probe`
# (the cadence stamp). Read/written only when the kill-switch is on. Path is
# env-overridable.
_MODEL_REFRESH_OVERLAY_PATH = Path(
    os.environ.get("DG_MODEL_REFRESH_OVERLAY")
    or (Path.home() / ".super-research" / "model_refresh.json")
)

# The only policy keys an overlay may override, with the type each must have.
# ⛔ WHITELISTED ON PURPOSE. `p2_labels` used to `update()` straight from the
# file, so any stale or hand-edited overlay became live config: flipping
# `thinking` back to True re-arms the every-run popover hunt Opus 5 made
# pointless, and changing `effort` breaks the trigger read that lets setup skip
# the popover at all. Unknown keys and wrong types are dropped silently — the
# code default always wins over a malformed override.
_OVERLAY_LABEL_SCHEMA = {
    "family": str,
    # Retunable for the same reason `family` is: the day a vendor renames its
    # mid-tier the fallback has to follow without a release, or a non-pro
    # account loses its only working model choice until one ships.
    "free_family": str,
    "effort": str,
    "tool": str,
    "reject": list,
    "thinking": (bool, str),
}


def _load_model_refresh_overlay() -> dict:
    """Read the runtime overlay; never raise. Returns {} when the kill-switch
    is off, the file is absent, or the JSON is corrupt — so the code defaults
    in P2_MODEL_POLICY are always a safe fallback (a bad/missing overlay can
    never break model selection)."""
    if not model_refresh_enabled():
        return {}
    try:
        with open(_MODEL_REFRESH_OVERLAY_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _platform_entry(platform: str) -> dict:
    """One platform's overlay entry, guaranteed to be a dict.

    ⛔ The single guarded door to overlay data. The file is user-editable and
    the kill-switch now defaults ON, so every reader must survive a platform key
    mapping to a scalar, a list, or null. `.get(platform, {})` does not (the
    default only applies to a MISSING key) and neither does `or {}` (only to a
    FALSY value) — `{"claude": 4.8}` defeats both."""
    v = _load_model_refresh_overlay().get(platform)
    return v if isinstance(v, dict) else {}


def p2_labels(platform: str) -> dict:
    """Merged label policy (family / reject-list / effort / thinking / tool),
    code defaults overlaid by any overlay values that pass _OVERLAY_LABEL_SCHEMA."""
    merged = dict(P2_MODEL_POLICY.get(platform, {}))
    raw = _platform_entry(platform).get("labels")
    if isinstance(raw, dict):
        for key, want in _OVERLAY_LABEL_SCHEMA.items():
            if key in raw and isinstance(raw[key], want):
                merged[key] = raw[key]
    return merged


def p2_family(platform: str) -> str:
    """The model FAMILY word for a platform ('opus' / 'flash'), lowercase.
    Empty string for a platform with no model lever (chatgpt). This is the only
    model identity the code carries — there is deliberately no version.

    ⛔ Restricted to letters/digits/spaces. The family word is interpolated into
    four `new RegExp(...)` sites in research.py's page.evaluate strings, and the
    overlay may supply any string for `family` — one metacharacter would throw
    inside the browser and take model selection down. Rejecting the value here
    (falling back to the code default) removes that whole class at the source,
    which is better than escaping it correctly at four call sites forever."""
    return _family_word(platform, "family")


def _family_word(platform: str, key: str) -> str:
    """The shared read+sanitize behind `p2_family` and `p2_free_family`.

    ⛔ ONE implementation on purpose. Both words are interpolated into
    `new RegExp(...)` inside page.evaluate strings, so both need the identical
    metacharacter rejection — and a second copy of that rule is exactly how the
    fallback family ends up as the one unescaped path into the browser."""
    raw = str(p2_labels(platform).get(key) or "").lower().strip()
    if raw and not re.fullmatch(r"[a-z0-9 ]+", raw):
        raw = str(P2_MODEL_POLICY.get(platform, {}).get(key) or "").lower()
    return raw


def p2_free_family(platform: str) -> str:
    """The family to fall back to when the account's plan does not include
    `p2_family(platform)`. Empty string when the platform has no fallback.

    ⛔ EMPTY WHEN IT EQUALS THE PRIMARY FAMILY, and that is not a formality. The
    fallback's only trigger is "every row of family X is a sales chip"; if the
    fallback IS X, the retry re-runs the same picker over the same refused rows
    and the only thing that changes is that the failure takes two passes and
    logs a family switch that did not happen. The overlay is user-editable, so
    that configuration is one typo away and has to resolve to "no fallback".

    ⚠ Sanitized exactly like `p2_family` — it reaches the same `new RegExp`
    sites, so it carries the same injection surface."""
    free = _family_word(platform, "free_family")
    return "" if not free or free == p2_family(platform) else free


def reject_terms(platform: str) -> list:
    """The platform's reject list, lowercased. See P2_MODEL_POLICY["gemini"] for
    what the trailing `*` means."""
    v = p2_labels(platform).get("reject")
    return [str(r).lower() for r in v] if isinstance(v, (list, tuple)) else []


def _ascii_alnum(ch) -> bool:
    """The word-character test every mirrored matcher in this module uses.

    ⭐ ASCII, because the JS port is ASCII (`c >= 'a' && c <= 'z' || …`) and
    these are meant to be THE definition rather than a second opinion.
    `str.isalnum()` is Unicode-aware, so on a CJK or accented UI the two
    disagreed at exactly the boundary that decides a match: "…flash pro高度" is
    NOT rejected in python ('高' is alnum, so the right boundary fails) but IS
    rejected in the browser — and "…flashélite" is the mirror image. Every unit
    test built on `pick_highest_model` was therefore certifying accept/reject
    semantics the browser never ran.

    Module level rather than nested, so `reject_matches` and `is_upsell` cannot
    grow two answers to the same question. Every caller lowercases first, so
    there is no uppercase branch to mirror."""
    return bool(ch) and (("a" <= ch <= "z") or ("0" <= ch <= "9"))


def reject_matches(text: str, terms) -> bool:
    """Does `text` (a lowercased menu-row label) hit any reject term?

    ⭐ THE SINGLE DEFINITION of reject semantics, ported character-for-character
    into the JS ranker. Before this existed the two had drifted: the JS used
    `includes('lite') || includes('deep think') || /\\bpro\\b/` while this Python
    "mirror" used a left-boundary match for every term — so the unit suite was
    certifying behaviour the browser never ran.

    A term matches when it starts at a word boundary AND, unless it ends in `*`,
    also ends at one:
      • "lite*"      matches "flash-litefastest", not "elite"
      • "pro"        matches "3.1 pro", not "productivity"
      • "deep think" matches "deep think", not "deep thinking" (whole word)

    Deliberately regex-free: this is mirrored into a non-raw Python string
    holding JS, where a lone \\b once became a literal backspace and silently
    disabled a gate for months (the #913 note).
    """
    t = (text or "").lower()
    _alnum = _ascii_alnum

    for raw in terms or []:
        term = str(raw).lower()
        prefix = term.endswith("*")
        if prefix:
            term = term[:-1]
        if not term:
            continue
        i = t.find(term)
        while i != -1:
            left_ok = i == 0 or not _alnum(t[i - 1])
            end = i + len(term)
            right_ok = prefix or end >= len(t) or not _alnum(t[end])
            if left_ok and right_ok:
                return True
            i = t.find(term, i + 1)
    return False


def has_term(text: str, terms) -> bool:
    """The SAME word-boundary term match as `reject_matches`, named for POSITIVE
    use ("does this row name the tier?") instead of negative ("is this row
    rejected?").

    A thin alias on purpose. ChatGPT's tier word is `pro`, and a bare `in` test —
    which is what `has_family` does, correctly, for a family word like `opus` —
    would accept "great for productivity" and "Improve your writing". The
    boundary rule that keeps "3.1 pro" apart from "productivity" already exists
    and is character-for-character mirrored into the JS ranker; a second
    implementation of it is how the two drifted the first time.
    """
    return reject_matches(text, terms)


def pick_effort_tier(labels, tier_words, upgrade_verbs=()):
    """From ChatGPT's model-menu row labels, pick the row naming the target
    EFFORT TIER. Returns {'index', 'version', 'label'} or None.

    ⭐ A DIFFERENT SELECTION RULE FROM `pick_highest_model`, and the difference is
    the platform's, not a preference. Claude and Gemini list MODELS, every row
    carries a version, and "highest offered member of the family" is decidable
    from the numbers alone. ChatGPT lists EFFORT AND MODEL IN ONE MENU —
    `Instant 5.5 / Medium / High / Extra High / Pro` — where only the cheapest row
    carries a number at all. Ranking that menu by version would pick `Instant 5.5`
    over `Pro`: the highest number is the LOWEST tier. So the target here is a
    NAMED tier, and a version only ever breaks a tie BETWEEN rows that already
    name it.

    ⛔ NO FALLBACK TO A LOWER TIER. If nothing names the tier this returns None,
    and the caller escalates exactly as it does today. Quietly settling for the
    next tier down is precisely the silent downgrade the post-select confirm
    exists to catch — it would mask a lapsed subscription as a successful pick.

    Ranking among rows that DO name the tier: highest adjacent version first
    (`Pro 5.5` beats `Pro`), then SHORTEST label. The tie-break is the leaf rule
    from the Claude/Gemini rankers: a container that concatenates several rows
    carries the tier word too, and clicking an ancestor never reaches the row's
    handler while the caller happily reports success.

    Rows carrying an upgrade verb are dropped first — "Upgrade to Pro" is a sales
    prompt that names the tier without being evidence of it.
    """
    # ⚠ No `if not tiers: return None` guard. It looked like the safe thing to
    # write and was DEAD: `has_term(t, [])` is False for every row, so an empty
    # tier list already selects nothing. An early return that cannot change an
    # answer is a line that will be read as load-bearing by the next person and
    # tested by nobody — a mutation that deleted it survived, which is how it was
    # found. The caller's own "no tier words configured" guard is real, because
    # it distinguishes `unsure` from `no_target` BEFORE opening any menu.
    tiers = [str(t).lower() for t in (tier_words or [])]
    verbs = [str(v).lower() for v in (upgrade_verbs or [])]
    best = None
    for i, raw in enumerate(labels or []):
        t = (raw or "").strip().lower()
        if not t:
            continue
        if verbs and has_term(t, verbs):
            continue
        if not has_term(t, tiers):
            continue
        v = None
        for term in tiers:
            v = parse_family_version(t, term)
            if v is not None:
                break
        rank = (0, 0.0) if v is None else (1, v)
        if best is None or rank > best["_rank"] or (rank == best["_rank"] and len(t) < best["_len"]):
            best = {"index": i, "version": v, "label": (raw or "").strip(),
                    "_rank": rank, "_len": len(t)}
    if best is not None:
        best.pop("_rank", None)
        best.pop("_len", None)
    return best


def _known_good_key(platform: str, family: str = "") -> str:
    """Which overlay field holds the known-good version for this family.

    ⭐ THE VERSION IS ONLY MEANINGFUL INSIDE ITS FAMILY. "4.6" names a real
    Sonnet and, on the same account, an Opus that may never have existed —
    yet the overlay had ONE `known_good` slot per platform. Once a non-pro run
    could verify and record, a later pro run's step-back would pin Opus to a
    number learned from Sonnet, the picker would find no row within 0.001 of it,
    and the single retry the step-back exists to provide would be spent looking
    for a model that was never on the menu.

    The primary family keeps the bare `known_good` key, so nothing already on
    disk is stranded and no migration is needed; only additional families get a
    suffix. `family` is already restricted to [a-z0-9 ] by `_family_word`, so
    the only transform needed is spaces → underscore."""
    fam = (family or "").strip().lower()
    if not fam or fam == p2_family(platform):
        return "known_good"
    return "known_good_" + fam.replace(" ", "_")


def p2_known_good(platform: str, family: str = ""):
    """The last verified-working model version for a platform+family (the C1
    fallback target when the latest can't be verified). None until a real run
    records one (see record_known_good). Coerced to float so a stringly-typed
    overlay value can't break the float comparisons in the picker JS."""
    # ⚠ isinstance, not `.get(platform, {})` and not `or {}`. The dict default
    # only fires when the KEY IS MISSING, and `or {}` only when the value is
    # FALSY — a hand-edited overlay whose platform maps to a truthy scalar
    # ({"claude": 4.8}) slips past both and `.get` raises AttributeError. This
    # reader's one caller is the step-back path, so the crash would land at
    # exactly the recovery moment and kill the agent instead of parking it.
    raw = _platform_entry(platform).get(_known_good_key(platform, family))
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _write_model_refresh_overlay(data: dict) -> bool:
    """Atomically persist the overlay: write a temp file then os.replace() it,
    so a reader always sees a whole file (never a torn write) and no lock is
    needed. No-op unless the kill-switch is on. Never raises — a write failure
    just means the overlay isn't updated (the run is unaffected).

    ⚠ The temp name carries the PID. With a FIXED temp name two processes (the
    daemon plus a CLI run, or two daemons) can interleave their writes into the
    same partial file and os.replace() a TORN document into place — which the
    reader then throws away, silently losing every learned value. Per-PID temps
    make the worst case a lost update, never a corrupt file."""
    if not model_refresh_enabled():
        return False
    try:
        _MODEL_REFRESH_OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _MODEL_REFRESH_OVERLAY_PATH.with_name(
            f"{_MODEL_REFRESH_OVERLAY_PATH.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, _MODEL_REFRESH_OVERLAY_PATH)
        return True
    except Exception:
        return False


def _merge_overlay_entry(platform: str, **fields) -> bool:
    """Read-modify-write one platform's overlay entry, leaving every other
    platform untouched. Returns True iff it wrote."""
    merged = dict(_load_model_refresh_overlay())
    entry = dict(_platform_entry(platform))
    entry.update(fields)
    merged[platform] = entry
    return _write_model_refresh_overlay(merged)


def overlay_path() -> str:
    """Where the learned state lives — for error messages, so a failed write is
    diagnosable without the reader having to know the default location."""
    return str(_MODEL_REFRESH_OVERLAY_PATH)


def model_probe_due(platform: str) -> bool:
    """Should setup open the model menu this run to look for a newer family
    member? True when the cadence stamp is missing or older than
    `model_probe_days()`.

    ⛔ FALSE WHENEVER THE KILL-SWITCH IS OFF. With the flag off nothing can be
    read OR written, so `last_probe` would be permanently absent — 'due' would
    then be permanently true and the OFF switch would open the model popover on
    every single run, which is precisely the #744 behaviour the switch exists to
    avoid. Off means off: no persistence, no cadence, family+highest-offered
    only (the picker still runs whenever the popover opens for another reason)."""
    if not model_refresh_enabled():
        return False
    last = _platform_entry(platform).get("last_probe")
    try:
        last_f = float(last)
    except (TypeError, ValueError):
        return True          # never probed (or junk) → probe now
    if last_f <= 0:
        return True
    return (time.time() - last_f) >= model_probe_days() * 86400.0


def record_probe(platform: str, *, saw_menu: bool) -> bool:
    """Stamp the cadence clock for `platform`.

    ⚠ Stamped whether or not the probe actually SAW a mounted menu. If a UI
    rotation makes the popover unreadable, a success-only stamp would leave the
    probe due forever and re-open the popover every run — turning one dead
    canary into a per-run regression. Recording the attempt caps the cost at one
    popover per platform per interval no matter how badly the probe is broken.
    `saw_menu` is kept as telemetry so a run of blind probes is visible."""
    return _merge_overlay_entry(
        platform, last_probe=time.time(), last_probe_saw_menu=bool(saw_menu))


def record_known_good(platform: str, version, family: str = "") -> bool:
    """On-the-fly learning: record `version` as the last verified-working model
    for `platform` (within `family`) so the pin fallback tracks the latest
    PROVEN model as platforms advance. See `_known_good_key` for why the family
    is part of the identity and not a detail.

    ⛔ THIS IS NOT A PICKER FLOOR. It is only the target the pipeline pins to
    when the newest model fails to enter Deep Research. Using it as a floor
    would let one learned value strand a run on an account that is no longer
    offered that version.

    Pure side-channel: it can never change what a run does. Coerces to float,
    ignores junk, and writes ONLY when the value actually changes (no per-run
    disk churn). Never raises. Returns True iff it wrote."""
    if not model_refresh_enabled():
        return False
    try:
        v = float(version)
    except (TypeError, ValueError):
        return False
    if v <= 0:
        return False
    key = _known_good_key(platform, family)
    cur = _platform_entry(platform).get(key)
    try:
        if cur is not None and abs(float(cur) - v) < 0.001:
            return False  # unchanged — skip the write
    except (TypeError, ValueError):
        pass
    return _merge_overlay_entry(platform, **{key: v})


def parse_family_version(text: str, family: str):
    """Parse a version adjacent to the family word out of a model-dropdown row
    label, in EITHER order:
      • num-before-family (Gemini): '3.5 flash' → 3.5, 'gemini 4.0 flash' → 4.0
      • family-before-num (Claude): 'opus 4.8 max' → 4.8
    Row text is often title+description CONCATENATED ('3.5 FlashAll-around
    help'), so there is no trailing boundary after the family word. Returns a
    float or None.

    ⭐ Both orders at BOTH sites. Each JS ranker used to parse only its own
    platform's order, which is correct right up until that vendor renames — at
    which point every row reads as version-less, ranking collapses to the
    shortest-label tie-break, and the picker DOWNGRADES while reporting success.
    The rankers now run these same two patterns in this same precedence.

    ⚠ `[0-9]`, not `\\d`: `\\d` is Unicode-aware in python and ASCII in the JS
    port, and a mirror that parses a row the browser cannot is not a mirror.

    ⭐⭐ ADJACENCY IS THE WHOLE RULE, and the ORDER matters. A menu WRAPPER's
    textContent concatenates every row — claude.ai renders `Fable 5Opus 5Sonnet
    5Haiku 4.5` — so a loose pattern lets a SIBLING FAMILY's number attach to our
    family word. Two constraints keep that out:

      • family-first is tried FIRST. Number-first would read `Fable 5.1Opus 5` as
        5.1 (the `5.1` sits immediately before `opus` once the labels are glued),
        so the wrapper would outrank the real `Opus 5` leaf, get clicked — which
        changes nothing, because a click on an ancestor never reaches the row —
        and be reported as a successful upgrade to a version no Opus row ever had.
      • the separator may span neither another WORD nor a sentence break: only
        a few plain separators are allowed (`[ ._/()-]{0,3}`). A letter-only
        exclusion is not enough — `3.6 Flash, 2x faster` would read as 2,
        because the comma is not a letter. `flash-litefastest` must not reach
        across the description either.

    Order alone is not enough and adjacency alone is not enough; both are load-
    bearing, and both JS rankers run the identical pair."""
    t = (text or "").lower()
    fam = re.escape(family.lower())
    m = (re.search(fam + r"[ ._/()-]{0,3}([0-9]+(?:\.[0-9]+)?)", t)
         or re.search(r"([0-9]+(?:\.[0-9]+)?)[ ._/()-]{0,3}" + fam, t))
    return float(m.group(1)) if m else None


def stepped_back_to(picked, failed) -> bool:
    """Did the step-back retry actually move the platform to an OLDER model?

    ⛔ "Deep Research worked on the retry" is a DIFFERENT claim, and conflating
    the two is how a literal "vNone" reached a user-facing amber notice. The
    selectors pop `_P2_PICKED_VERSION` on entry and write it only after a row is
    clicked, so when the menu offers nothing strictly older than the version that
    just failed — the normal shape for a platform showing one current family
    member plus rejected siblings — the re-pick early-returns, Deep Research is
    enabled anyway and succeeds, and `picked` is None. The run then told the user
    the agent "used an older model (vNone)" while it sat on exactly the model
    that had failed.

    A named predicate rather than an inline `and`, for the same reason as the
    auto-skip window helpers: this is the boolean that was wrong, and a boolean
    can only be tested by calling it.

    Booleans are rejected explicitly — `isinstance(True, int)` is True in Python,
    so a truthy flag arriving here would otherwise compare as version 1.
    """
    if isinstance(picked, bool) or isinstance(failed, bool):
        return False
    if not isinstance(picked, (int, float)) or not isinstance(failed, (int, float)):
        return False
    return float(picked) < float(failed) - 0.001


def has_family(text: str, family: str) -> bool:
    """Does this row/trigger label name the family AT ALL, with or without a
    version? 'Opus 5 Max' → True, plain 'Opus' → True, 'Sonnet 4.6' → False.

    This is what makes the selection family-only rather than version-only: every
    version parser here needs a digit next to the family word, so the day a
    platform ships a version-LESS label ('Opus', 'Opus Max' — the endpoint of the
    very naming trend this work responds to) a version-only check reports "no
    model found" and the picker dies. Callers treat a family match with no
    version as a valid but LOWEST-ranked candidate."""
    return bool(family) and family.lower() in (text or "").lower()


# The one character JS calls whitespace and Python does not. `str.isspace()`
# covers everything else JS's `\s` matches, and then some.
# ⚠ Spelled as an ESCAPE deliberately — a literal BOM here is invisible in every
# editor and diff, which is how a character like this survives review.
_WS_EXTRA = "\ufeff"


def _collapse_ws(s: str) -> str:
    """Runs of whitespace → one space, over a set the JS ports match EXACTLY.

    ⛔ `" ".join(s.split())` is NOT that set, and the difference is measurable.
    Python treats `\\x1c`-`\\x1f` and `\\x85` as whitespace and JS does not; JS
    treats `\\ufeff` (a BOM, which does turn up in page text) as whitespace and
    Python does not. Since the upsell window is counted in CHARACTERS on the
    collapsed string, a label padded with either class is an upsell to one
    implementation and a model row to the other — so the mirror and the shipped
    JS disagree about whether to click it. Measured, on the real ported code,
    before this existed.

    The union is the safe direction for both: `isspace()` here plus the BOM, and
    JS's own `\\s` plus the separators and NEL it lacks. Character-level rather
    than a regex, like everything else this file mirrors into embedded JS.
    """
    out: list = []
    prev_ws = True                      # leading run is dropped, like .strip()
    for ch in s or "":
        if ch.isspace() or ch in _WS_EXTRA:
            if not prev_ws:
                out.append(" ")
            prev_ws = True
        else:
            out.append(ch)
            prev_ws = False
    return "".join(out).rstrip()


def is_upsell(text: str, noun: str, window: int = UPSELL_WINDOW) -> bool:
    """Is this row a SALES PROMPT for `noun` rather than an offer of it?

    ⭐ "Upgrade to Opus" and "Get Opus with Max" name the family exactly the way
    a real menu row does, so every rule that decides a row is a candidate —
    `has_family`, `parse_family_version` — says yes to both. Without this the
    ranker treats a billing chip as a model and CLICKS it: the upsell surface
    opens over the composer, the click returns truthy, and the caller reports a
    successful model selection while the phase types into a page sitting behind
    a modal. A version-less chip wins the shortest-label tie-break outright, and
    a VERSIONED one ("Upgrade to Opus 5.2") is worse — it parses, so it competes
    on rank with the real rows and can beat every one of them.

    ⭐ VERB-THEN-NOUN WITHIN A WINDOW, not a bare verb test, and the difference
    is what keeps this from emptying the menu. Row text here is title and
    description CONCATENATED (`parse_family_version` documents that shape), so a
    blurb reading "try our most capable model" would disqualify a genuine row
    under a bare verb rule — the same silent-empty-menu failure the version-less
    fallback exists to prevent. Requiring the noun to FOLLOW the verb also
    leaves "Opus 5 — upgrade for more usage" selectable, which is correct: that
    row is the model, with a sales tail.

    ⚠ Residual, stated rather than papered over: a verb-less upsell ("Opus 5 ·
    Max plan only") is not caught. Nothing in that text distinguishes it from a
    row, so the verb is the honest boundary.

    Deliberately regex-free, like `reject_matches`, and for the same reason —
    this is mirrored into a non-raw Python string holding JS, where a lone \\b
    once became a literal backspace and silently disabled a gate for months
    (the #913 note).

    ⚠ Whitespace is collapsed INSIDE this function rather than by its callers,
    because the window is measured in characters: a row rendered across three
    lines puts newlines and indentation between the verb and the noun, and the
    same chip would be an upsell in one DOM and not in another. The JS port
    collapses in the same place, over `_collapse_ws`'s character set rather than
    each language's own idea of whitespace — see there.

    ⭐⭐ A "FAMILY NAMED FIRST" EXEMPTION WAS TRIED AND REVERTED, 2026-08-14.
    The idea was that a verb AFTER the first mention of the family describes a
    row rather than selling one, so "Opus 5 — try Opus with extended thinking"
    would stay selectable. It was written to answer a review concern that this
    guard could discard a genuine row whose blurb happens to read
    verb-then-family.

    It was reverted because it demonstrably re-opened the blocking finding.
    Driven through the SHIPPED picker JS, a menu of

        ["Opus 5 · Upgrade to Opus Max for more usage", "Opus 4.5", "Sonnet 4.6"]

    clicked the first row and returned it as a confirmed pick at version 5 — a
    billing surface over the composer plus a FALSE SUCCESS, which the review
    called the failure mode hardest to notice, and a poisoned version feeding
    the known-good machinery. The concern it was answering was hypothetical; the
    failure it caused was reproduced. Confirmed beats plausible.

    ⚠ THE RESIDUAL THIS ACCEPTS, stated rather than papered over: a genuine row
    whose description re-names the family within 24 characters after a sales
    verb IS excluded, and if a lower row is present the picker takes it. What
    makes that the better side of the trade is direction — excluding costs a
    downgrade to a model that still works, while including costs a modal over
    the composer and a run reporting success into it. Claude's observed row
    copy ("Our most capable model") does not re-name the family, so the shape
    is unattested; the one this prevents is the shipped defect.

    ⚠ Other residuals: a verb-less upsell ("Opus 5 · Max plan only") is not
    caught. Nothing in that text distinguishes it from a row, so the verb is
    the honest boundary."""
    t = _collapse_ws(text).lower()
    n = _collapse_ws(noun).lower()
    if not t or not n:
        return False
    for raw in UPSELL_VERBS:
        verb = str(raw).lower()
        if not verb:
            continue
        i = t.find(verb)
        while i != -1:
            end = i + len(verb)
            left_ok = i == 0 or not _ascii_alnum(t[i - 1])
            right_ok = end >= len(t) or not _ascii_alnum(t[end])
            if left_ok and right_ok:
                j = t.find(n, end)
                if j != -1 and j - end <= window:
                    return True
            i = t.find(verb, i + 1)
    return False


def pick_highest_model(labels, family: str, below=None, reject=(), drop_upsell=False):
    """From candidate dropdown-row labels, pick the row with the HIGHEST
    <family> version, REJECTING (checked first) any label that hits a reject
    term per `reject_matches` — the same rule the JS ranker runs, so this is a
    real mirror rather than a second opinion. Tie-break: shortest label (prefer
    a leaf row over a wrapper that concatenates several models).

    `drop_upsell=True` additionally discards sales prompts for the family per
    `is_upsell` — see there for why a billing chip is otherwise indistinguishable
    from a model row, and why the exclusion runs regardless of whether the chip
    carries a version.

    ⚠ IT IS OPT-IN BECAUSE THE TWO RANKERS IT MIRRORS DO NOT AGREE — and NOTHING
    CALLS THIS FROM THE BROWSER. A ranker is a JS string run through
    `page.evaluate`, so the rule is hand-PORTED, never shared: `_pick_opus_js` in
    research.py carries a character-level port of `is_upsell` and is handed this
    module's `UPSELL_VERBS`/`UPSELL_WINDOW`, while the Gemini Flash ranker has no
    upsell rule at all. Default-on would put the no-flag answer HERE at odds with
    the browser on the un-ported path — exactly how the reject rule drifted the
    first time — so the flag is what lets one function mirror either ranker.
    (2026-08-21: this paragraph used to say "every JS ranker that calls it: the
    Claude ranker ports the rule and passes it". Both halves were false. No JS
    can call a Python function, and no production Python calls this at all.)

    ⭐ NO FLOOR PARAMETER. "Highest offered" already cannot pick a downgrade —
    nothing else on the menu is higher — so a floor could only ever REJECT the
    one row that should have won. `below` is the opposite tool: the fallback
    path passes the version that just failed and gets the best row STRICTLY
    beneath it, which is how the pipeline steps back a release without any
    hardcoded "previous version".

    A row that names the family with NO parseable version is a valid candidate
    ranked BELOW every versioned row (version None), so a version-less rename
    still selects something instead of emptying the menu.

    Returns {'index', 'version', 'label'} of the winner (version may be None),
    or None.

    ⚠ NO PRODUCTION CALLER — selection happens in the browser. This is the
    executable SPEC the JS rankers are ported from, unit-tested here so the
    ranking ALGORITHM has real coverage (the live JS can't run without a
    browser); `drop_upsell=True` is exercised only by tests. Read it as the
    reference implementation, not as a code path a run goes through."""
    rej = [str(r).lower() for r in (reject or [])]
    best = None
    for i, raw in enumerate(labels):
        t = (raw or "").strip().lower()
        if not t:
            continue
        if reject_matches(t, rej):
            continue
        # BEFORE the version parse, deliberately. A versioned upsell
        # ("Upgrade to Opus 5.2") parses, so a check placed after — or one
        # reached only on the version-less branch — would let the worst case
        # through: a chip that competes on rank with the real rows.
        if drop_upsell and is_upsell(t, family):
            continue
        v = parse_family_version(t, family)
        if v is None and not has_family(t, family):
            continue
        if below is not None:
            # Un-versioned rows can't be proven below the failed version, so the
            # step-back path skips them rather than risk re-picking what failed.
            if v is None or v >= float(below) - 0.001:
                continue
        # Rank: any version beats no version; higher version wins; tie → shorter.
        rank = (0, 0.0) if v is None else (1, v)
        if best is None or rank > best["_rank"] or (rank == best["_rank"] and len(t) < best["_len"]):
            best = {"index": i, "version": v, "label": (raw or "").strip(),
                    "_rank": rank, "_len": len(t)}
    if best is not None:
        best.pop("_rank", None)
        best.pop("_len", None)
    return best


def upsell_warning(noun: str) -> str:
    """The sentence that tells a browser-driving agent a sales chip is not a model.

    ⭐ WHY THIS EXISTS. The DOM picker learned to refuse upsell chips; the CUA
    missions did not, and CUA is what runs AFTER the DOM tier fails — which, on
    an account whose plan does not include the family, is EVERY run. So the
    mission that said "open the model menu and select the HIGHEST Opus it offers"
    was pointing the agent at the only Opus-shaped things on the page: the chips.
    Refusing them in the selectors and then instructing an agent to click them is
    not a fix, it is a relocation.

    ⛔ The second half is the part that is easy to leave out and the reason the
    first half is not enough. Told only "ignore the chips", an agent that finds
    NOTHING else matching the family keeps hunting — and the most Opus-looking
    thing on the page is still the chip. It has to be told what the absence
    MEANS: the plan does not include this family, so stop looking.

    Rendered from `UPSELL_VERBS`, like the ChatGPT tier mission's own warning, so
    the missions and the selectors can never develop separate ideas of what a
    sales prompt looks like.
    """
    cta = " / ".join(f'"{v.capitalize()} to {noun}"' for v in UPSELL_VERBS[:2])
    return (
        f"Ignore any {cta} button or menu row — that is a sales prompt for a paid "
        f"plan, NOT a model, and clicking it opens a billing page over the "
        f"composer. If the only {noun} rows on offer are sales prompts like that, "
        f"this account's plan does not include {noun}: leave the model exactly as "
        f"it is and move on."
    )


def free_family_note(excluded: str, use_instead: str) -> str:
    """The sentence a CUA mission needs when the run has DELIBERATELY switched to
    the fallback family.

    ⛔ NOT `upsell_warning(excluded)`, and the difference is the whole point.
    That sentence ends "leave the model exactly as it is and move on", which is
    correct when the mission's target IS the family being sold — and flatly
    contradicts a mission whose job is to go select a different family. Handing
    an agent two instructions that disagree about whether to touch the model is
    how a setup pass ends in neither.
    """
    return (
        f"This account's plan does not include {excluded}: every {excluded} row in "
        f"the model menu is a sales prompt that opens a billing page, not a model. "
        f"Do not click one and do not read one as {excluded} being available — "
        f"{use_instead} is the correct model on this account."
    )


def p2_claude_setup_directive(family: str = "") -> str:
    """The CUA user-instruction that drives Claude's P2 setup (model + effort +
    Research tool). Single source replacing the byte-identical literal
    previously duplicated at two research.py call sites.

    ⭐ FAMILY ONLY — there is no version in this string and there must never be
    one again. Naming a version and asking the agent to "select" it made a HIGHER
    model read as wrong: on an account already on Opus 5, a directive built
    around 4.8 led the agent to conclude "this is NOT Opus 4.8, so I need to fix
    it" and click into the model menu before self-correcting (the "model selector
    opens twice" report).

    ⚠ This is the CUA path, which runs ONLY AFTER the DOM setup FAILED — so
    unlike the validate string it must keep an upgrade lever: opening the menu
    here is the whole point of the fallback. The validate string
    (research.py's user_msg_map) is the one that says "leave it alone", because
    it runs after a DOM setup that already succeeded.

    `family` overrides the target family for THIS call. It is passed the run's
    active family, which is the primary one on every pro account and the
    fallback on an account whose plan excludes it. ⛔ Defaulting to "" rather
    than to the policy word is deliberate: the caller must be able to say
    "whatever policy says" without knowing what that is, and the default render
    stays byte-identical to the pre-fallback text."""
    pol = p2_labels("claude")
    primary = str(pol.get("family", "opus"))
    fam = (str(family) or primary).capitalize()                # "Opus" / "Sonnet"
    effort = str(pol.get("effort", "max")).capitalize()        # "Max"
    tool = str(pol.get("tool", "research")).capitalize()       # "Research"
    # Only on the fallback path, and only about the family we are NOT using.
    swapped = "" if fam.lower() == primary.lower() else \
        f"{free_family_note(primary.capitalize(), fam)} "
    return (
        f"{swapped}Ensure the model is {fam} with {effort} effort and the {tool} tool ON. "
        f"Model rule: the model must be {fam} — the VERSION NUMBER DOES NOT MATTER "
        f"and a higher one is always correct. Open the model menu ONCE and select "
        f"the HIGHEST {fam} it offers; if the highest {fam} is already the selected "
        f"one, close the menu without clicking it. {upsell_warning(fam)} If the "
        f"button already shows {fam} and the menu will not open, that is fine — "
        f"leave the model as it is. Do NOT type — just set up and focus input. "
        f"Say 'ready for paste'."
    )


def p2_claude_validate_directive(family: str = "", effort_ok: bool = True) -> str:
    """The CUA user-instruction for the POST-SETUP validation pass on Claude.

    ⚠ The mirror image of p2_claude_setup_directive, and the difference is
    load-bearing. That one runs after the DOM path FAILED, so it must open the
    menu and upgrade. This one runs after the DOM path SUCCEEDED — the highest
    offered model has already been selected — so its job is to LEAVE THE MODEL
    ALONE. Opening the model menu here is what users saw as "the selector opens
    twice".

    ⭐ FAMILY ONLY. "Verify Opus 4.8" on an account already running Opus 5 made
    the validator reason "this is NOT Opus 4.8, so I need to fix it" and click
    into the menu before self-correcting a step later. Lives here, beside the
    setup directive, so both CUA strings render from one policy and a test can
    read the FINAL text rather than grepping an f-string split across source
    lines.

    ⛔⛔ `family` MATTERS MOST HERE, more than in the setup string. This mission
    fires after a successful setup and its rule is "only touch the model if it
    is not <fam> at all" — with <fam> frozen to Opus, a run that deliberately
    selected the fallback family satisfies that trigger on EVERY pass, and the
    validator is then pointed at a menu whose only Opus rows are the sales chips
    the DOM layer just finished refusing. The correct model would be undone by
    the pass whose job is to confirm it."""
    pol = p2_labels("claude")
    primary = str(pol.get("family", "opus"))
    fam = (str(family) or primary).capitalize()
    effort = str(pol.get("effort", "max")).capitalize()
    tool = str(pol.get("tool", "research")).capitalize()
    swapped = "" if fam.lower() == primary.lower() else \
        f"{free_family_note(primary.capitalize(), fam)} "
    # ⭐ Matches the system prompt's `effort_ok`. The two strings go to ONE CUA
    # call, so a permission granted in one and withheld in the other leaves the
    # agent holding instructions that disagree — the same failure the family word
    # was moved here to prevent.
    if not effort_ok:
        return (
            f"{swapped}Claude is on {fam} with the {tool} tool, but the effort is "
            f"NOT {effort} and the automated pass could not set it. Open the model "
            f"popover, open the Effort submenu, choose {effort}, and close both. "
            f"Leave the model alone — it is already correct. If the submenu will "
            f"not open on the first try, say so and stop rather than retrying. "
            f"Do not type.")
    return (
        f"{swapped}Verify Claude is on {fam} with {effort} effort and the {tool} tool ON. "
        f"THE VERSION NUMBER DOES NOT MATTER: if the model button reads {fam} "
        f"followed by any number — or by no number at all — the model is correct, "
        f"so leave it alone and do NOT open the model menu. Only touch the model "
        f"if it is not {fam} at all. {upsell_warning(fam)} Clear any stale "
        f"attachments. Do not type."
    )
