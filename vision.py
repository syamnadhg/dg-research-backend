"""Vision tier-2 layer for Super Research.

Architecture: Playwright (primary, fast) → Vision (this file, smart) → CUA (fallback).

Vision is invoked when Playwright fails or hits a flaky DOM. It accepts a
`flow_context` describing what workflow we're in and what just failed, reads
a screenshot, and proposes the next browser action. Caller executes the
action and either resumes Playwright (if successful) or escalates to CUA.

Public surface:
    VisionClient          — stateful client (one Anthropic conn pool, metrics ledger)
    default_client()      — process-wide lazily-constructed singleton
    ImgMeta               — screenshot metadata (viewport + DPR)
    ActionResult          — typed return from ask()/act()
    VisionMetrics         — call counts, tokens, cost, p95 latency
    with_vision_fallback  — wrapper used by Playwright sites at hotspots
    execute_action        — runs an ActionResult against a Playwright page

Design source: scratch/vision_hotspots.md (8 hotspots + 4 generic capabilities)
              + V1 advisor `a29c1dcf8b2ec8059` (perfection-grade spec).

V1 = standalone, no production wiring. V2 = post-action gates. V3 = wire-in.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

import anthropic

# Central model registry — see research-automate/models.py for env-var
# overrides + rationale. Aliased locally so existing call sites continue
# to read `MODEL_SONNET` / `MODEL_OPUS` without churn, while bumps land
# centrally in models.py.
from models import VISION_LIGHT_MODEL, VISION_HEAVY_MODEL

logger = logging.getLogger("vision")


ActionVerb = Literal[
    "click", "type", "scroll", "key", "wait",
    "escalate_to_cua", "declare_success", "declare_failure",
]

# Sonnet is the default. Opus is the high-stakes / retry-after-failure model.
# Haiku confirmed too weak by V1 advisor — never used.
# Names kept as MODEL_SONNET / MODEL_OPUS for backwards-compat with all
# in-file references (cost dicts, call sites, etc.) — the actual model
# strings flow in from models.py and bumps land there.
MODEL_SONNET = VISION_LIGHT_MODEL
MODEL_OPUS = VISION_HEAVY_MODEL

# Per-call hard timeout (asyncio.wait_for around the SDK call). Vision is the
# smart tier-2 between Playwright and CUA; the CUA fallback routinely takes
# 20–30s, so an 8s ceiling was far too tight — it produced mostly TimeoutError
# in shadow telemetry (the model needs ~4s but the call also screenshots + b64s
# a multi-MB PNG). 20s gives real headroom while staying well under CUA. Tunable
# via DG_VISION_TIMEOUT_S for in-the-loop tuning without a redeploy.
try:
    DEFAULT_TIMEOUT_S = float(os.environ.get("DG_VISION_TIMEOUT_S") or 20.0)
except (TypeError, ValueError):
    DEFAULT_TIMEOUT_S = 20.0
# A fat-fingered 0 / negative would make every wait_for fire instantly →
# 100% TimeoutError (the exact failure this raise fixes). Floor it.
if DEFAULT_TIMEOUT_S <= 0:
    DEFAULT_TIMEOUT_S = 20.0

# Single transport retry on network/5xx/429. Two retries pushes p95 over budget.
TRANSPORT_RETRY_DELAY_S = 1.5

# Confidence below this is flagged for caller to escalate. NOT auto-retried —
# auto-retry on low confidence inflates cost without changing the model's mind.
LOW_CONFIDENCE_THRESHOLD = 0.6

# Pessimistic per-pipeline-run circuit breaker. Stops a flaky hotspot from
# burning the budget. Caller surfaces as pipeline_warning when raised.
DEFAULT_CALL_BUDGET = 50

# Cost coefficients for rough $/run estimates ($/Mtok). Used by
# VisionMetrics.estimated_cost_usd for surfacing in run analytics, not
# for billing. Refresh against the current Anthropic pricing page when
# the underlying MODEL_* constant changes — the figures below were set
# against Opus 4.7 / Sonnet 4.6; the dict keys flow from the imported
# constants (now Opus 4.8 default) so the lookup still works, but the
# coefficient values may drift from actuals until they get re-pinned.
_COST_PER_MTOK_INPUT = {MODEL_SONNET: 3.00, MODEL_OPUS: 15.00}
_COST_PER_MTOK_OUTPUT = {MODEL_SONNET: 15.00, MODEL_OPUS: 75.00}


# ─────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ImgMeta:
    """Captured at screenshot time. Coordinate ratios in ActionResult are
    multiplied by (width_css, height_css) before page.mouse.click() — that's
    why we use ratios end-to-end and never raw image pixels."""
    width_css: int
    height_css: int
    dpr: float
    captured_at: float


@dataclass(frozen=True)
class ActionResult:
    """Typed return from vision calls. Coordinates are 0–1 ratios — they
    survive image resize, DPR, and viewport changes. Convert to CSS pixels
    inside execute_action() right before the Playwright call."""
    action: ActionVerb
    reason: str
    confidence: float
    next_expected_state: str
    x_ratio: float | None = None
    y_ratio: float | None = None
    text: str | None = None
    key: str | None = None
    scroll_dy_ratio: float | None = None
    duration_ms: int | None = None
    # Internal flags — not part of the model's JSON schema. Caller-visible
    # but set by VisionClient based on call outcome.
    low_confidence: bool = False
    model_used: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class VisionMetrics:
    """Per-pipeline-run counters. Reset via reset() between runs.
    V3 wire-in dumps this into the run's status JSON for analytics."""
    call_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    failures_by_reason: Counter = field(default_factory=Counter)
    by_model: Counter = field(default_factory=Counter)

    def record(self, result: ActionResult) -> None:
        self.call_count += 1
        self.total_input_tokens += result.input_tokens
        self.total_output_tokens += result.output_tokens
        self.latencies_ms.append(result.latency_ms)
        if result.model_used:
            self.by_model[result.model_used] += 1
        if result.action == "declare_failure":
            self.failures_by_reason[result.reason[:80]] += 1

    def p95(self) -> float:
        if not self.latencies_ms:
            return 0.0
        s = sorted(self.latencies_ms)
        return s[max(0, int(len(s) * 0.95) - 1)]

    def estimated_cost_usd(self) -> float:
        # Aggregates across models. Approximate — pricing changes; treat as
        # an indicator, not an invoice.
        cost = 0.0
        for model, count in self.by_model.items():
            in_rate = _COST_PER_MTOK_INPUT.get(model, 5.0) / 1_000_000
            out_rate = _COST_PER_MTOK_OUTPUT.get(model, 25.0) / 1_000_000
            avg_in = self.total_input_tokens / max(self.call_count, 1)
            avg_out = self.total_output_tokens / max(self.call_count, 1)
            cost += count * (avg_in * in_rate + avg_out * out_rate)
        return cost

    def reset(self) -> None:
        self.call_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.latencies_ms.clear()
        self.failures_by_reason.clear()
        self.by_model.clear()


class BudgetExceeded(RuntimeError):
    """Raised when VisionMetrics.call_count exceeds the per-run budget.
    Caller should surface as pipeline_warning and stop trying Vision for
    the rest of this run (fall through to CUA)."""


# ─────────────────────────────────────────────────────────────────────────
# Tool schema — forced output via Anthropic tool-use
# ─────────────────────────────────────────────────────────────────────────

# We force the model to call this tool. Guarantees valid JSON without a
# parse-retry loop. Anthropic's response_format=json is less strict; tool-use
# enforces the input_schema.
_PROPOSE_ACTION_TOOL = {
    "name": "propose_action",
    "description": (
        "Propose the next browser action to advance the workflow described "
        "in the user message. Choose ONE action. Coordinates are 0–1 ratios "
        "of the viewport width/height. Confidence is your honest assessment "
        "from 0 (guessing) to 1 (certain)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "click", "type", "scroll", "key", "wait",
                    "escalate_to_cua", "declare_success", "declare_failure",
                ],
                "description": (
                    "click: click at (x_ratio, y_ratio). "
                    "type: type `text` into the currently focused field. "
                    "scroll: scroll by `scroll_dy_ratio` viewport heights. "
                    "key: press `key` (e.g. Tab, Enter, Escape). "
                    "wait: wait `duration_ms` milliseconds. "
                    "escalate_to_cua: page is unreadable / captcha / unknown — "
                    "let the CUA fallback take over. "
                    "declare_success: workflow goal is met (read it from the screen). "
                    "declare_failure: workflow definitely failed; no further action would help."
                ),
            },
            "x_ratio": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "y_ratio": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "text": {"type": "string"},
            "key": {"type": "string"},
            "scroll_dy_ratio": {"type": "number"},
            "duration_ms": {"type": "integer", "minimum": 0},
            "reason": {
                "type": "string",
                "description": (
                    "WHY this action — a short sentence. Used for logs and "
                    "becomes the next call's last_action breadcrumb."
                ),
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "next_expected_state": {
                "type": "string",
                "description": (
                    "What the screen should look like AFTER your action. V2 "
                    "post-action gates use this to verify the action landed."
                ),
            },
        },
        "required": ["action", "reason", "confidence", "next_expected_state"],
    },
}


_SYSTEM_PROMPT = (
    "You guide browser automation as the smart tier-2 layer. Playwright "
    "(tier-1) already tried and failed at the current step; CUA (tier-3) "
    "is the fallback if you can't make sense of the screen. "
    "\n\n"
    "RULES:\n"
    "1. Coordinates are 0–1 ratios of the viewport, NOT pixels — the center is "
    "(0.5, 0.5) and the far-right edge is x≈1.0. NEVER return a pixel value like "
    "1238; if you're thinking in pixels, divide by the viewport size first.\n"
    "2. If you can CLEARLY see the target, click its CENTER and report high "
    "confidence. If you CANNOT locate it, return action='escalate_to_cua' — do "
    "NOT emit a low-confidence guess at the screen edge. A clean escalation beats "
    "a wrong click (and below 0.6 confidence the caller escalates anyway).\n"
    "3. If you see a captcha (reCAPTCHA, hCaptcha, Cloudflare), return "
    "action='escalate_to_cua' immediately. Never attempt to solve.\n"
    "4. If the workflow goal is already visible on screen (e.g. the share "
    "URL is rendered), return action='declare_success' with the URL or key "
    "info in `reason`.\n"
    "5. One action per response. Sequencing across multiple screens is the "
    "caller's job.\n"
    "6. Always populate next_expected_state — it's how V2 verifies your "
    "action worked.\n"
    "\n"
    "Use the propose_action tool for your response. Do not write prose."
)


# ─────────────────────────────────────────────────────────────────────────
# VisionClient
# ─────────────────────────────────────────────────────────────────────────

class VisionClient:
    """One client per process. Holds the AsyncAnthropic connection pool, the
    metrics ledger, and the model-routing logic. Stateless across calls —
    flow state lives in the caller's flow_context."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = MODEL_SONNET,
        call_budget: int = DEFAULT_CALL_BUDGET,
        on_action: Callable[[ActionResult, dict], Awaitable[None]] | None = None,
    ) -> None:
        key = api_key
        if not key:
            # Lazy import — research imports vision, so vision must import
            # research lazily to avoid a circular import at module-load.
            # Routes through the canonical precedence chain (Firestore →
            # user-scope env → os.environ). Eliminates the two-ladder split
            # with research.py:25404 (which now also uses resolve_api_key).
            try:
                from research import resolve_api_key as _resolve_api_key
                key = _resolve_api_key()
            except Exception:
                pass
        if not key:
            # Last-resort flat read — covers standalone callers (e.g.
            # vision_test.py) where the research module isn't loaded.
            # Single canonical name only (CUA_API_KEY retired 2026-05-23).
            key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "VisionClient: no API key. Pass api_key= or set ANTHROPIC_API_KEY."
            )
        self._client = anthropic.AsyncAnthropic(api_key=key)
        self._default_model = default_model
        self._call_budget = call_budget
        self._on_action = on_action
        self.metrics = VisionMetrics()

    # ── Step 1: screenshot + ImgMeta ────────────────────────────────────
    async def screenshot(self, page: Any, *, full_page: bool = False) -> tuple[bytes, ImgMeta]:
        """Capture a viewport screenshot + the metadata needed to map
        action ratios back to CSS pixels."""
        png = await page.screenshot(full_page=full_page, type="png")
        try:
            dpr = float(await page.evaluate("window.devicePixelRatio") or 1.0)
        except Exception:
            dpr = 1.0
        viewport = page.viewport_size or {"width": 1280, "height": 800}
        return png, ImgMeta(
            width_css=int(viewport["width"]),
            height_css=int(viewport["height"]),
            dpr=dpr,
            captured_at=time.time(),
        )

    # ── Step 2: ask (forced tool-use, Sonnet/Opus routing) ──────────────
    async def ask(
        self,
        image: bytes,
        img_meta: ImgMeta,
        flow_context: dict,
        *,
        prompt: str | None = None,
        high_stakes: bool = False,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport_retry: bool = True,
    ) -> ActionResult:
        """Send screenshot + flow_context to the vision model, force tool-use,
        return a typed ActionResult. Never raises — failures return action=
        'declare_failure'. Callers can chain into CUA without try/except.

        ``transport_retry=False`` does a SINGLE attempt (no 1.5s+retry on a
        transport error) — used by shadow mode, which doesn't need Vision to
        succeed (CUA carries) and must stay self-bounded so a caller's outer
        timeout can't mask the retry and mislabel transport churn as a timeout."""
        if self.metrics.call_count >= self._call_budget:
            raise BudgetExceeded(
                f"Vision call budget {self._call_budget} exceeded — escalate to CUA"
            )

        model = self._pick_model(flow_context, high_stakes)
        user_text = self._build_user_message(flow_context, prompt, img_meta)
        t0 = time.time()

        for attempt in range(2 if transport_retry else 1):  # 1 try + optional transport retry
            try:
                resp = await asyncio.wait_for(
                    self._client.messages.create(
                        model=model,
                        max_tokens=512,
                        system=_SYSTEM_PROMPT,
                        tools=[_PROPOSE_ACTION_TOOL],
                        tool_choice={"type": "tool", "name": "propose_action"},
                        messages=[{
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": _b64(image),
                                    },
                                },
                                {"type": "text", "text": user_text},
                            ],
                        }],
                    ),
                    timeout=timeout_s,
                )
                latency_ms = (time.time() - t0) * 1000.0
                result = self._parse_response(resp, model, latency_ms, img_meta)
                self.metrics.record(result)
                if self._on_action:
                    try:
                        await self._on_action(result, flow_context)
                    except Exception as e:
                        logger.warning("on_action hook raised: %s", e)
                self._log_call(result, flow_context)
                return result
            except asyncio.TimeoutError:
                # Timeout doesn't retry — already over budget on latency.
                latency_ms = (time.time() - t0) * 1000.0
                logger.warning(
                    "vision: timeout after %.0fms (model=%s, workflow=%s)",
                    latency_ms, model, flow_context.get("workflow_name", "?"),
                )
                return self._failure(
                    f"vision timeout after {timeout_s}s",
                    model, latency_ms,
                )
            except (anthropic.APIConnectionError, anthropic.RateLimitError,
                    anthropic.InternalServerError) as e:
                if attempt == 0 and transport_retry:
                    logger.info("vision: transport error, retrying once: %s", e)
                    await asyncio.sleep(TRANSPORT_RETRY_DELAY_S)
                    continue
                latency_ms = (time.time() - t0) * 1000.0
                return self._failure(
                    f"transport error: {type(e).__name__}: {e}",
                    model, latency_ms,
                )
            except Exception as e:
                # Anything else (auth, schema) → failure. Don't raise.
                latency_ms = (time.time() - t0) * 1000.0
                logger.exception("vision: unexpected error")
                return self._failure(
                    f"unexpected error: {type(e).__name__}: {e}",
                    model, latency_ms,
                )

        # Unreachable — both attempt branches return. Defensive.
        return self._failure("unreachable retry branch exhausted", model, 0.0)

    # ── Step 3: act (screenshot + ask, the common path) ──────────────────
    async def act(
        self,
        page: Any,
        flow_context: dict,
        *,
        prompt: str | None = None,
        high_stakes: bool = False,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> ActionResult:
        """Convenience: screenshot the page then ask the model. The bread-
        and-butter call from with_vision_fallback()."""
        image, meta = await self.screenshot(page)
        # Inject viewport into flow_context — vision needs this to reason
        # about coords. Caller doesn't have to remember.
        ctx = dict(flow_context)
        ctx.setdefault("viewport", {
            "w": meta.width_css, "h": meta.height_css, "dpr": meta.dpr,
        })
        return await self.ask(
            image, meta, ctx,
            prompt=prompt, high_stakes=high_stakes, timeout_s=timeout_s,
        )

    # ── Internals ────────────────────────────────────────────────────────

    def _pick_model(self, flow_context: dict, high_stakes: bool) -> str:
        """Sonnet by default. Opus when login flow, captcha, retry-after-
        failure, or caller forces high_stakes."""
        if high_stakes:
            return MODEL_OPUS
        if flow_context.get("phase") == 0:
            return MODEL_OPUS
        wf = flow_context.get("workflow_name", "")
        if wf in ("phase0_login_verify", "captcha_detect"):
            return MODEL_OPUS
        if int(flow_context.get("attempts") or 0) >= 2:
            return MODEL_OPUS
        return self._default_model

    def _build_user_message(
        self, flow_context: dict, prompt: str | None, img_meta: ImgMeta,
    ) -> str:
        """Pack the flow_context as YAML-style for token efficiency, then
        the explicit task prompt, then a viewport reminder."""
        # YAML is denser than JSON for prompts. We don't use a yaml lib —
        # this is a hand-rolled flat dump good enough for the model.
        parts: list[str] = ["# Workflow context"]
        for k in (
            "workflow_name", "phase", "current_step", "last_action",
            "expected_outcome", "attempts", "platform", "context_hint",
            "forbidden_actions", "success_signals",
        ):
            if k in flow_context and flow_context[k] not in (None, "", [], {}):
                v = flow_context[k]
                if isinstance(v, (list, dict)):
                    v = json.dumps(v)
                parts.append(f"{k}: {v}")
        parts.append("")
        parts.append(
            f"# Viewport\n"
            f"{img_meta.width_css}×{img_meta.height_css} CSS pixels (DPR {img_meta.dpr:.1f})"
        )
        parts.append("")
        parts.append("# Task")
        if prompt:
            parts.append(prompt)
        else:
            parts.append(
                f"Advance the {flow_context.get('workflow_name', 'workflow')} "
                f"workflow. Current step: {flow_context.get('current_step', 'unknown')}. "
                f"Goal: {flow_context.get('expected_outcome', 'see workflow_name above')}."
            )
        return "\n".join(parts)

    def _parse_response(
        self, resp: Any, model: str, latency_ms: float, img_meta: ImgMeta | None = None,
    ) -> ActionResult:
        """Extract the propose_action tool call from the response.
        Forced tool-use guarantees this exists, but we defend anyway."""
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0
        vw = img_meta.width_css if img_meta else 0
        vh = img_meta.height_css if img_meta else 0

        for block in (resp.content or []):
            if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == "propose_action":
                inp = block.input or {}
                conf = float(inp.get("confidence", 0.0))
                return ActionResult(
                    action=inp.get("action", "declare_failure"),
                    reason=str(inp.get("reason", "")),
                    confidence=conf,
                    next_expected_state=str(inp.get("next_expected_state", "")),
                    x_ratio=_norm_ratio(inp.get("x_ratio"), vw),
                    y_ratio=_norm_ratio(inp.get("y_ratio"), vh),
                    text=_opt_str(inp.get("text")),
                    key=_opt_str(inp.get("key")),
                    scroll_dy_ratio=_opt_float(inp.get("scroll_dy_ratio")),
                    duration_ms=_opt_int(inp.get("duration_ms")),
                    low_confidence=(conf < LOW_CONFIDENCE_THRESHOLD),
                    model_used=model,
                    latency_ms=latency_ms,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                )
        # No tool_use block — schema-invalid response. Failure.
        return self._failure(
            "model did not return propose_action tool call",
            model, latency_ms,
            in_tok=in_tok, out_tok=out_tok,
        )

    def _failure(
        self, reason: str, model: str, latency_ms: float,
        in_tok: int = 0, out_tok: int = 0,
    ) -> ActionResult:
        result = ActionResult(
            action="declare_failure",
            reason=reason,
            confidence=0.0,
            next_expected_state="",
            model_used=model,
            latency_ms=latency_ms,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
        self.metrics.record(result)
        return result

    def _log_call(self, result: ActionResult, flow_context: dict) -> None:
        logger.info(
            "vision: action=%s confidence=%.2f workflow=%s phase=%s "
            "model=%s latency_ms=%.0f tokens=%d/%d reason=%s",
            result.action, result.confidence,
            flow_context.get("workflow_name", "?"),
            flow_context.get("phase", "?"),
            result.model_used, result.latency_ms,
            result.input_tokens, result.output_tokens,
            result.reason[:80],
        )


# ─────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────

_default: VisionClient | None = None


def default_client() -> VisionClient:
    """Lazy process-wide singleton. Constructed from env on first call.
    V3 wire-in uses this so callers don't have to plumb the client through."""
    global _default
    if _default is None:
        _default = VisionClient()
    return _default


# ─────────────────────────────────────────────────────────────────────────
# execute_action — runs an ActionResult against a Playwright page.
# Lives in vision.py (not the caller) so V3 wire-in is one import.
# ─────────────────────────────────────────────────────────────────────────

async def execute_action(page: Any, result: ActionResult, img_meta: ImgMeta) -> None:
    """Translate an ActionResult into a Playwright operation. Coords are
    ratios → CSS pixels via img_meta. No-op for declare_success /
    declare_failure / escalate_to_cua — those signal the caller, not the page.
    Raises only on Playwright errors; vision failures already short-circuited."""
    a = result.action
    if a in ("declare_success", "declare_failure", "escalate_to_cua"):
        return
    if a == "click":
        if result.x_ratio is None or result.y_ratio is None:
            raise ValueError("click action requires x_ratio + y_ratio")
        x = result.x_ratio * img_meta.width_css
        y = result.y_ratio * img_meta.height_css
        await page.mouse.click(x, y)
    elif a == "type":
        if result.text is None:
            raise ValueError("type action requires text")
        await page.keyboard.type(result.text, delay=20)
    elif a == "scroll":
        dy_ratio = result.scroll_dy_ratio or 0.5
        dy = dy_ratio * img_meta.height_css
        await page.mouse.wheel(0, dy)
    elif a == "key":
        if result.key is None:
            raise ValueError("key action requires key")
        await page.keyboard.press(result.key)
    elif a == "wait":
        ms = result.duration_ms or 500
        await asyncio.sleep(ms / 1000.0)


# ─────────────────────────────────────────────────────────────────────────
# with_vision_fallback — the V3 wire-in pattern. Lives here for caller ease.
# ─────────────────────────────────────────────────────────────────────────

def is_vision_enabled() -> Literal["off", "shadow", "tier2", "tier3"]:
    """Process-wide env flag for Vision wiring mode.

    - "off"    — Vision module not invoked at any wire-in site (default).
    - "shadow" — Vision runs in PARALLEL with CUA at tier-2 escalation
                 sites; logs Vision's proposed action but CUA's output is
                 what acts. Used for promotion-criterion telemetry.
    - "tier2"  — Vision runs BEFORE CUA at escalation sites (with_vision_
                 fallback semantics). For per-hotspot promotion after
                 shadow proves agreement.
    - "tier3"  — Vision runs only AFTER CUA also fails. Reserved.
    """
    val = (os.environ.get("DG_VISION_TIER") or "off").strip().lower()
    if val in ("off", "shadow", "tier2", "tier3"):
        return val  # type: ignore[return-value]
    return "off"


def _shadow_log_path() -> str:
    """Per-run shadow-eval JSONL log path. Honors DG_VISION_SHADOW_LOG env
    or falls back to logs/vision_shadow.jsonl in the cwd."""
    return os.environ.get("DG_VISION_SHADOW_LOG") or os.path.join(
        "logs", "vision_shadow.jsonl"
    )


def _append_shadow_record(rec: dict) -> None:
    """Append a single shadow-eval record to the JSONL log. Lockless,
    crash-safe: each line is its own JSON object so partial writes are
    skippable. Caller never raises out of this — telemetry must not break
    the pipeline."""
    try:
        path = _shadow_log_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("shadow log append failed: %s", exc)


async def _harvest_fixture(
    image_bytes: bytes, hotspot_id: str, run_id: str | None
) -> str | None:
    """Optionally save the shadow-eval screenshot as a fixture for the
    smoke harness. Off by default (set DG_VISION_FIXTURE_AUTO=1 to enable).
    Returns the saved path or None."""
    if (os.environ.get("DG_VISION_FIXTURE_AUTO") or "").strip() not in ("1", "true", "yes"):
        return None
    try:
        base = os.path.join("tests", "fixtures", "vision", "auto", hotspot_id)
        name = f"{run_id or 'run'}_{int(time.time())}.png"
        full = os.path.join(base, name)
        # File I/O off the event loop — `image_bytes` can be several MB.
        # Sync write was defeating shadow-mode's parallel-with-CUA property
        # when fixture-auto is on.
        def _write():
            os.makedirs(base, exist_ok=True)
            with open(full, "wb") as f:
                f.write(image_bytes)
        await asyncio.to_thread(_write)
        return full
    except Exception as exc:
        logger.debug("fixture harvest failed: %s", exc)
        return None


async def shadow_observe_then_cua(
    page: Any,
    cua_fn: Callable[[], Awaitable[Any]],
    *,
    flow_context: dict,
    hotspot_id: str,
    vision: VisionClient | None = None,
    run_id: str | None = None,
    high_stakes: bool = False,
) -> Any:
    """Tier-3 SHADOW MODE: run Vision in parallel with CUA, log Vision's
    proposed action for offline comparison, but ONLY return CUA's result.
    Vision NEVER touches the page. Zero risk to pipeline.

    Promotion criterion (per scratch/vision_v3_plan.md): a hotspot flips
    from this helper to with_vision_fallback() once N >= 10 events show
    >= 80% action-class agreement and >= 70% coord proximity within 0.10.

    Caller must enable via DG_VISION_TIER=shadow. Default off — caller
    should check is_vision_enabled() before calling.

    Failure modes (Vision side) are silently logged, never raised:
    - Vision exception:    log {"vision": {"error": "..."}}
    - Vision timeout:      log {"vision": {"timeout": true}}
    - asyncio.gather throw: caught via return_exceptions=True
    """
    vc = vision or default_client()

    async def _vision_observe() -> dict:
        t0 = time.time()
        try:
            # ONE screenshot, reused for fixture harvest AND the model call —
            # ask() takes the image directly, so no second capture (the old
            # path screenshotted twice, both inside the timed window). Shadow
            # uses a SINGLE attempt (transport_retry=False): it doesn't need
            # Vision to succeed (CUA carries), and a self-bounded single ask()
            # means the outer wait_for below can't mask the inner timeout/retry
            # and mislabel transport churn as a model-latency timeout. The outer
            # is just a safety net for a hung screenshot, sized above ask()'s
            # own inner timeout so it never races it.
            async def _shot_and_ask() -> ActionResult:
                img, meta = await vc.screenshot(page)
                await _harvest_fixture(img, hotspot_id, run_id)
                return await vc.ask(
                    img, meta, flow_context,
                    high_stakes=high_stakes, transport_retry=False,
                )
            result = await asyncio.wait_for(
                _shot_and_ask(), timeout=DEFAULT_TIMEOUT_S + 8,
            )
            # ask() never raises — engine failures come back as declare_failure
            # with a known reason. Preserve the {"timeout"}/{"error"} record
            # shapes (so the report keeps categorising + the SOURCE is distinct),
            # while a GENUINE model declare_failure stays a full action record.
            if result.action == "declare_failure":
                r = (result.reason or "").lower()
                if "timeout" in r:
                    return {"timeout": True, "elapsed_ms": int(result.latency_ms),
                            "reason": result.reason}
                if (r.startswith("transport error") or r.startswith("unexpected error")
                        or "did not return" in r):
                    return {"error": result.reason,
                            "elapsed_ms": int(result.latency_ms)}
            return {
                "action": result.action,
                "reason": result.reason,
                "confidence": result.confidence,
                "next_expected_state": result.next_expected_state,
                "x_ratio": result.x_ratio,
                "y_ratio": result.y_ratio,
                "model": result.model_used,
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "low_confidence": result.low_confidence,
            }
        except asyncio.TimeoutError:
            return {"timeout": True, "elapsed_ms": int((time.time() - t0) * 1000)}
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "elapsed_ms": int((time.time() - t0) * 1000)}

    async def _cua_run() -> tuple[Any, float]:
        t0 = time.time()
        result = await cua_fn()
        return result, (time.time() - t0) * 1000.0

    # Run both in parallel. return_exceptions=True so one branch's failure
    # doesn't take down the other; the cua-fn returns whatever the caller
    # wants (typically the agent_loop dict).
    results = await asyncio.gather(
        _vision_observe(), _cua_run(), return_exceptions=True,
    )

    vision_record = results[0] if not isinstance(results[0], Exception) else {
        "error": f"gather: {type(results[0]).__name__}: {str(results[0])[:200]}",
    }

    cua_result: Any
    cua_latency_ms: float
    if isinstance(results[1], Exception):
        # CUA broke — propagate, but log it anyway.
        _append_shadow_record({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": run_id, "hotspot_id": hotspot_id,
            "phase": flow_context.get("phase"),
            "agent": flow_context.get("platform"),
            "vision": vision_record,
            "cua": {"error": f"{type(results[1]).__name__}: {str(results[1])[:200]}"},
        })
        raise results[1]
    cua_result, cua_latency_ms = results[1]

    # Best-effort outcome inference: caller (research.py) parses cua_result
    # for "panel: open" / "panel: already_open" — record those as outcome.
    cua_text = ""
    try:
        if isinstance(cua_result, dict):
            cua_text = str(cua_result.get("text") or "")[:400]
    except Exception:
        pass

    _append_shadow_record({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": run_id, "hotspot_id": hotspot_id,
        "phase": flow_context.get("phase"),
        "agent": flow_context.get("platform"),
        "vision": vision_record,
        "cua": {"latency_ms": int(cua_latency_ms),
                "text_head": cua_text[:200]},
    })

    return cua_result


async def observe_only(
    page: Any,
    *,
    flow_context: dict,
    hotspot_id: str,
    vision: VisionClient | None = None,
    run_id: str | None = None,
    high_stakes: bool = False,
    dom_ground_truth: dict | None = None,
) -> dict:
    """DOM-SUCCESS observer: run Vision PURELY as an observer on a step the DOM
    path ALREADY completed successfully, log its proposed action for offline
    comparison, and NEVER touch the page. There is NO CUA leg and NO gather —
    this is the success-path sibling of ``shadow_observe_then_cua`` (which only
    fires on a DOM MISS, so DOM-robust hotspots like 7d / p2-share almost never
    log). Every record carries ``source: "dom_success"`` to keep this always-on
    population separate from the legacy miss-path records (which have a ``cua``
    block and no ``source``).

    Outcome-neutral and never-raise: ONE screenshot + ONE ask()
    (transport_retry=False, self-bounded by an outer wait_for), NO execute_action,
    and every failure (incl. timeout / BudgetExceeded / a dead page after the run
    ends) is swallowed into an {error}/{timeout} record. Safe to fire-and-forget
    from inside a synchronous poll loop.

    Caller enables via the success-path flag (research.py DG_VISION_OBSERVE_SUCCESS)
    and should gate on it before calling — this helper does not read it.
    ``dom_ground_truth`` is the caller-supplied truth the report scores Vision
    against: ``{true_x_ratio, true_y_ratio, label, clickedTag, scope, url}``
    (coords None where the DOM helper doesn't surface a bbox). Returns the
    appended record (handy for tests); the append itself never raises.
    """
    vc = vision or default_client()
    t0 = time.time()

    async def _shot_and_ask() -> ActionResult:
        img, meta = await vc.screenshot(page)
        await _harvest_fixture(img, hotspot_id, run_id)
        return await vc.ask(
            img, meta, flow_context,
            high_stakes=high_stakes, transport_retry=False,
        )

    try:
        result = await asyncio.wait_for(_shot_and_ask(), timeout=DEFAULT_TIMEOUT_S + 8)
        # Mirror shadow_observe_then_cua's record shapes so the report categorises
        # observe-only samples the same way (timeout / transport-error / full action).
        if result.action == "declare_failure":
            r = (result.reason or "").lower()
            if "timeout" in r:
                vision_record: dict = {"timeout": True, "elapsed_ms": int(result.latency_ms),
                                       "reason": result.reason}
            elif (r.startswith("transport error") or r.startswith("unexpected error")
                  or "did not return" in r):
                vision_record = {"error": result.reason, "elapsed_ms": int(result.latency_ms)}
            else:
                vision_record = _observe_action_record(result)
        else:
            vision_record = _observe_action_record(result)
    except asyncio.TimeoutError:
        vision_record = {"timeout": True, "elapsed_ms": int((time.time() - t0) * 1000)}
    except Exception as exc:  # incl. BudgetExceeded, a closed page/context post-run
        vision_record = {"error": f"{type(exc).__name__}: {str(exc)[:200]}",
                         "elapsed_ms": int((time.time() - t0) * 1000)}

    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": run_id,
        "hotspot_id": hotspot_id,
        "phase": flow_context.get("phase"),
        "agent": flow_context.get("platform"),
        "source": "dom_success",
        "vision": vision_record,
        "dom_ground_truth": dom_ground_truth or {},
    }
    _append_shadow_record(rec)
    return rec


def _observe_action_record(result: ActionResult) -> dict:
    """The full Vision action record (same shape the shadow path logs) — used by
    observe_only(). Kept as a module helper so the success-path and the existing
    shadow path stay byte-identical in what they record."""
    return {
        "action": result.action,
        "reason": result.reason,
        "confidence": result.confidence,
        "next_expected_state": result.next_expected_state,
        "x_ratio": result.x_ratio,
        "y_ratio": result.y_ratio,
        "model": result.model_used,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "low_confidence": result.low_confidence,
    }


async def with_vision_fallback(
    page: Any,
    primary_fn: Callable[[], Awaitable[Any]],
    *,
    flow_context: dict,
    cua_fallback: Callable[[Any, dict, str], Awaitable[Any]] | None = None,
    vision: VisionClient | None = None,
    high_stakes: bool = False,
) -> Any:
    """Run `primary_fn` (Playwright). On failure, ask Vision; if Vision
    proposes an action, execute it then re-enter `primary_fn` once. If
    Vision escalates or `primary_fn` fails again, fall through to CUA.

    `primary_fn` MUST be re-entrant (idempotent reads OK; idempotent writes
    handled by the underlying workflow's resume logic). The existing
    extract_share_link_* extractors satisfy this.
    """
    vc = vision or default_client()
    try:
        return await primary_fn()
    except Exception as e:
        flow_context = dict(flow_context)
        flow_context["context_hint"] = (
            f"playwright failed: {type(e).__name__}: {str(e)[:200]}"
        )
        result = await vc.act(page, flow_context, high_stakes=high_stakes)
        if result.action == "declare_success":
            return result
        if result.action in ("escalate_to_cua", "declare_failure") or result.low_confidence:
            if cua_fallback:
                return await cua_fallback(page, flow_context, result.reason)
            raise  # no CUA — re-raise the original Playwright error
        # Vision proposed a concrete action — execute and resume primary.
        _, meta = await vc.screenshot(page)  # refresh meta in case viewport changed
        await execute_action(page, result, meta)
        return await primary_fn()  # one resume attempt; further failures re-raise


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _b64(data: bytes) -> str:
    import base64
    return base64.standard_b64encode(data).decode("ascii")


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_ratio(v: Any, dim: int) -> float | None:
    """Normalise a coordinate to a 0–1 ratio. The model is told to return
    ratios, but in practice it sometimes returns RAW PIXELS (observed:
    x_ratio=1238 on a 1280px viewport → execute_action would then multiply by
    width again and click far off-screen). Recovery: a value clearly above the
    ratio range (>1.5) with a known viewport dim is treated as pixels and
    divided back to a ratio (1238/1280 = 0.967 — the right-edge target it
    actually meant); everything is then clamped to [0,1] so a stray value can
    never click outside the viewport. None stays None."""
    f = _opt_float(v)
    if f is None:
        return None
    # NaN/inf would slip past the >/< clamps below (every comparison with NaN is
    # False) and reach page.mouse.click(nan, nan). Reject up front → None, which
    # makes execute_action's "click requires x_ratio/y_ratio" guard fire instead.
    if not math.isfinite(f):
        return None
    if f > 1.5 and dim and dim > 0:
        f = f / dim
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _opt_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_str(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)
