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
# Sonnet 4.6 supports vision and is the right cost/quality balance for
# moderate-stakes single-shot reads.
VISION_LIGHT_MODEL = os.environ.get("VISION_LIGHT_MODEL", "claude-sonnet-4-6")

# Vision — high-stakes / retry-after-failure path. Opus 4.8 is the
# current Anthropic flagship (supersedes 4.7) with the highest-fidelity
# vision input. Reserved for the vision tier-2 verifier's escalation
# branch where we'd rather pay 5x to get the right answer than retry
# Sonnet repeatedly.
VISION_HEAVY_MODEL = os.environ.get("VISION_HEAVY_MODEL", "claude-opus-4-8")

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
# API path (Vertex extended to 2026-10-16). `gemini-3.5-flash` is GA
# (released Google I/O 2026) and the drop-in successor — same speed
# class, same multimodal support, frontier-class agentic performance.
GEMINI_TEXT = os.environ.get("GEMINI_TEXT_MODEL", "gemini-3.5-flash")

# Vision narrator (narrate.py) — agent-side screenshot panel reader.
# Multimodal Gemini call (image + structured-output schema). Same model
# family as GEMINI_TEXT but kept as its own env var so the narrator can
# be tuned independently from text-only summary/extractor sites.
GEMINI_NARRATE = os.environ.get("GEMINI_NARRATE_MODEL", "gemini-3.5-flash")

# Vision narrator fallback — Gemini Pro hedge against a Flash-specific
# outage. Kept on 2.5-pro pending 3.x-pro reaching GA (3.1-pro is still
# preview as of 2026-05-28); 2.5-pro deprecation is 2026-10-16, giving
# ample runway to migrate when the next Pro lands.
GEMINI_NARRATE_FALLBACK = os.environ.get("GEMINI_NARRATE_FALLBACK_MODEL", "gemini-2.5-pro")


# ── Phoenix (model_refresh) — P2 deep-research model POLICY ──────────────
# NB: "Phoenix" here is the model-FRESHNESS slice of PhoenixRecipe.md §6 — a
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
# Per-platform reality (do not assume symmetry):
#   • claude  — the runtime ALREADY auto-picks the highest Opus available;
#               `floor` is the never-downgrade guard, the only frozen value.
#   • gemini  — runtime picks the highest *Flash* (rejecting Pro/Lite/Deep
#               Think); `floor` is advisory (the ranker picks highest≥floor).
#   • chatgpt — NO model picker in P2 (only the Deep-Research toggle); `model`
#               is None and there is nothing to bump today.
P2_MODEL_POLICY = {
    "claude": {
        "family": "opus", "floor": 4.8, "pick": "highest",
        "effort": "max", "thinking": True, "tool": "research",
    },
    "gemini": {
        "family": "flash", "floor": 3.5, "pick": "highest",
        "reject": ["lite", "deep think", "pro"],
        "thinking": "extended", "tool": "deep research",
    },
    "chatgpt": {
        "model": None, "tool": "deep research",
    },
}


def _flag_on(name: str, default: str = "0") -> bool:
    """Codebase DG_* boolean idiom (mirrors vision.py / research.py)."""
    return (os.environ.get(name, default) or "").strip().lower() not in ("0", "false", "no", "")


# Kill-switch: default OFF → the weekly canary AND the runtime overlay are
# fully dark until armed. With it off, every p2_* accessor returns the code
# defaults above, so an un-armed install behaves exactly as before Phoenix.
DG_MODEL_REFRESH_ENABLED = _flag_on("DG_MODEL_REFRESH_ENABLED")

# Runtime overlay (canary-discovered floor/labels + per-platform known_good),
# written by the weekly canary (Phase D) and loaded OVER the code defaults —
# but ONLY when the kill-switch is on. Path is env-overridable; reconciled
# with the repo's data-dir convention when the canary writer lands.
_MODEL_REFRESH_OVERLAY_PATH = Path(
    os.environ.get("DG_MODEL_REFRESH_OVERLAY")
    or (Path.home() / ".super-research" / "model_refresh.json")
)


def _load_model_refresh_overlay() -> dict:
    """Read the runtime overlay; never raise. Returns {} when the kill-switch
    is off, the file is absent, or the JSON is corrupt — so the code defaults
    in P2_MODEL_POLICY are always a safe fallback (a bad/missing overlay can
    never break model selection)."""
    if not DG_MODEL_REFRESH_ENABLED:
        return {}
    try:
        with open(_MODEL_REFRESH_OVERLAY_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def p2_floor(platform: str) -> float | None:
    """The never-downgrade version floor for a platform's P2 model. Returns
    max(code floor, overlay floor) so the canary can only ever RAISE it (never
    silently lower it). None for platforms with no model lever (chatgpt)."""
    pol = P2_MODEL_POLICY.get(platform, {})
    base = pol.get("floor")
    ov = _load_model_refresh_overlay().get(platform, {})
    ov_floor = ov.get("floor")
    if isinstance(base, (int, float)) and isinstance(ov_floor, (int, float)):
        return max(base, ov_floor)
    return ov_floor if isinstance(ov_floor, (int, float)) else base


def p2_labels(platform: str) -> dict:
    """Merged label policy (family / reject-list / effort / thinking / tool),
    code defaults overlaid by any canary-refreshed values."""
    merged = dict(P2_MODEL_POLICY.get(platform, {}))
    merged.update(_load_model_refresh_overlay().get(platform, {}).get("labels", {}))
    return merged


def p2_known_good(platform: str):
    """The last canary-verified-working model version for a platform (the
    fallback target when the latest can't be verified). None until the canary
    records one. Validated-present each canary tick, so it can't outlive a
    retired model."""
    return _load_model_refresh_overlay().get(platform, {}).get("known_good")


def _fmt_ver(v) -> str:
    """Render a version float the way the UI/prompts spell it: 4.8 → '4.8',
    4.0 → '4.0', 5 → '5'. Used so the model literals derive from the floor
    instead of being hand-typed in multiple places."""
    if not isinstance(v, (int, float)):
        return str(v)
    # round() kills float dust (4.8 - 0.1 == 4.6999…); keep one decimal place
    # unless the value is a whole number with no fractional part recorded.
    r = round(float(v), 2)
    return ("%g" % r)


def p2_claude_ver() -> str:
    """The current Claude floor as a UI string, e.g. '4.8'."""
    return _fmt_ver(p2_floor("claude"))


def p2_claude_prev_ver() -> str:
    """The minor below the Claude floor, e.g. '4.7' — for the 'never downgrade
    to X when Y exists' guidance that mirrors today's literal."""
    f = p2_floor("claude")
    return _fmt_ver(round(float(f) - 0.1, 2)) if isinstance(f, (int, float)) else ""


def p2_claude_major() -> str:
    """The major component of the Claude floor, e.g. '4' (for 'any Opus 4.x')."""
    f = p2_floor("claude")
    return str(int(f)) if isinstance(f, (int, float)) else ""


def p2_claude_setup_directive() -> str:
    """The CUA user-instruction that drives Claude's P2 setup (model + effort +
    thinking + Research tool). Single source replacing the byte-identical
    literal previously duplicated at two research.py call sites. Derives the
    version numbers from the policy floor so a floor bump updates one place."""
    fam = P2_MODEL_POLICY["claude"]["family"].capitalize()  # "Opus"
    cur, prev = p2_claude_ver(), p2_claude_prev_ver()
    return (
        f"Select {fam} {cur} + Max effort + Adaptive Thinking + Research tool "
        f"(if {fam} {cur} isn't offered, pick the highest {fam} available — never "
        f"downgrade to {prev} when {cur} exists). Do NOT type — just set up and "
        f"focus input. Say 'ready for paste'."
    )
