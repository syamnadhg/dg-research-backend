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
import os

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
