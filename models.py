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
        # of it; these verbs disqualify a match.
        "upgrade_verbs": ["upgrade", "subscribe", "get", "try"],
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
    raw = str(p2_labels(platform).get("family") or "").lower().strip()
    if raw and not re.fullmatch(r"[a-z0-9 ]+", raw):
        raw = str(P2_MODEL_POLICY.get(platform, {}).get("family") or "").lower()
    return raw


def reject_terms(platform: str) -> list:
    """The platform's reject list, lowercased. See P2_MODEL_POLICY["gemini"] for
    what the trailing `*` means."""
    v = p2_labels(platform).get("reject")
    return [str(r).lower() for r in v] if isinstance(v, (list, tuple)) else []


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

    def _alnum(ch):
        # ⭐ ASCII, because the JS port is ASCII (`c >= 'a' && c <= 'z' || …`)
        # and this is supposed to be THE definition rather than a second
        # opinion. `str.isalnum()` is Unicode-aware, so on a CJK or accented
        # UI the two disagreed at exactly the boundary that decides a reject:
        # "…flash pro高度" is NOT rejected here (python: '高' is alnum, so the
        # right boundary fails) but IS rejected in the browser — and
        # "…flashélite" is the mirror image. Every unit test built on
        # pick_highest_model was therefore certifying accept/reject semantics
        # the browser never ran, which is the exact failure this docstring
        # claims was fixed. Both call sites lowercase first, so there is no
        # uppercase branch to mirror.
        return ("a" <= ch <= "z") or ("0" <= ch <= "9")

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


def p2_known_good(platform: str):
    """The last verified-working model version for a platform (the C1 fallback
    target when the latest can't be verified). None until a real run records
    one (see record_known_good). Coerced to float so a stringly-typed overlay
    value can't break the float comparisons in the picker JS."""
    # ⚠ isinstance, not `.get(platform, {})` and not `or {}`. The dict default
    # only fires when the KEY IS MISSING, and `or {}` only when the value is
    # FALSY — a hand-edited overlay whose platform maps to a truthy scalar
    # ({"claude": 4.8}) slips past both and `.get` raises AttributeError. This
    # reader's one caller is the step-back path, so the crash would land at
    # exactly the recovery moment and kill the agent instead of parking it.
    raw = _platform_entry(platform).get("known_good")
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


def record_known_good(platform: str, version) -> bool:
    """On-the-fly learning: record `version` as the last verified-working model
    for `platform` so the pin fallback tracks the latest PROVEN model as
    platforms advance.

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
    cur = _platform_entry(platform).get("known_good")
    try:
        if cur is not None and abs(float(cur) - v) < 0.001:
            return False  # unchanged — skip the write
    except (TypeError, ValueError):
        pass
    return _merge_overlay_entry(platform, known_good=v)


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


def pick_highest_model(labels, family: str, below=None, reject=()):
    """From candidate dropdown-row labels, pick the row with the HIGHEST
    <family> version, REJECTING (checked first) any label that hits a reject
    term per `reject_matches` — the same rule the JS ranker runs, so this is a
    real mirror rather than a second opinion. Tie-break: shortest label (prefer
    a leaf row over a wrapper that concatenates several models).

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
    or None. Mirror of the JS rankers in research.py, unit-tested here so the
    ranking ALGORITHM has real coverage (the live JS can't run without a
    browser)."""
    rej = [str(r).lower() for r in (reject or [])]
    best = None
    for i, raw in enumerate(labels):
        t = (raw or "").strip().lower()
        if not t:
            continue
        if reject_matches(t, rej):
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


def p2_claude_setup_directive() -> str:
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
    it runs after a DOM setup that already succeeded."""
    pol = p2_labels("claude")
    fam = str(pol.get("family", "opus")).capitalize()          # "Opus"
    effort = str(pol.get("effort", "max")).capitalize()        # "Max"
    tool = str(pol.get("tool", "research")).capitalize()       # "Research"
    return (
        f"Ensure the model is {fam} with {effort} effort and the {tool} tool ON. "
        f"Model rule: the model must be {fam} — the VERSION NUMBER DOES NOT MATTER "
        f"and a higher one is always correct. Open the model menu ONCE and select "
        f"the HIGHEST {fam} it offers; if the highest {fam} is already the selected "
        f"one, close the menu without clicking it. If the button already shows "
        f"{fam} and the menu will not open, that is fine — leave the model as it "
        f"is. Do NOT type — just set up and focus input. Say 'ready for paste'."
    )


def p2_claude_validate_directive() -> str:
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
    lines."""
    pol = p2_labels("claude")
    fam = str(pol.get("family", "opus")).capitalize()
    effort = str(pol.get("effort", "max")).capitalize()
    tool = str(pol.get("tool", "research")).capitalize()
    return (
        f"Verify Claude is on {fam} with {effort} effort and the {tool} tool ON. "
        f"THE VERSION NUMBER DOES NOT MATTER: if the model button reads {fam} "
        f"followed by any number — or by no number at all — the model is correct, "
        f"so leave it alone and do NOT open the model menu. Only touch the model "
        f"if it is not {fam} at all. Clear any stale attachments. Do not type."
    )
