"""Gemini Flash narrator for the agent side-panel.

A standalone OBSERVING module — reads screenshots of the research panel
(ChatGPT, Claude, or Gemini) via Gemini Flash and reports what the agent
is doing right now. Sits next to vision.py (Anthropic Sonnet, ACTING tier
that clicks/scrolls/types) and is intentionally separate so the
narrate-vs-act split is unambiguous in logs and call sites.

Public surface:
  narrate_panel(page, *, agent, phase, last_dom_progress=None) -> dict | None
  reset_phase_budget()                       -- call on phase_start
  get_metrics() -> dict                      -- for telemetry
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger("gemini_narrate")


GEMINI_MODEL_PRIMARY = os.environ.get("GEMINI_NARRATE_MODEL", "gemini-2.5-flash")
# 2.0-flash was the prior fallback but was deprecated for new users (404).
# Use 2.5-pro as the fallback so we hedge against flash-specific outages
# with a different model family rather than retrying the same one.
GEMINI_MODEL_FALLBACK = "gemini-2.5-pro"
GEMINI_TIMEOUT_S = float(os.environ.get("GEMINI_NARRATE_TIMEOUT", "8.0"))
# Vision narrator retired 2026-04-30 — per-agent narrator (Anthropic
# Haiku 4.5 primary, Gemini 2.5 Flash fallback) fully covers the
# agent-card narration slot via DOM-derived events. The vision tier
# duplicated narration output (last writer wins on FE; per-agent
# narrator fired 5× more often) and burned Gemini Flash budget for
# overlap with no marginal value. Set DG_VISION_NARRATE=1 to re-enable
# the prior 80-call/phase budget if narrator flame-outs surface a
# coverage gap that DOM events alone don't fill.
PHASE_BUDGET = int(os.environ.get(
    "GEMINI_NARRATE_BUDGET",
    "80" if os.environ.get("DG_VISION_NARRATE", "0").lower() in ("1", "true", "yes") else "0"
))
MIN_GAP_S = float(os.environ.get("GEMINI_NARRATE_MIN_GAP_S", "30"))
PANEL_CROP_RIGHT_FRACTION = float(os.environ.get("GEMINI_NARRATE_CROP", "0.45"))


_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "narration": {"type": "STRING"},
        "progress": {"type": "STRING"},
        "steps":     {"type": "ARRAY", "items": {"type": "STRING"}},
        "sections":  {"type": "ARRAY", "items": {"type": "STRING"}},
        "sources_observed": {"type": "INTEGER"},
        "phase_signal": {
            "type": "STRING",
            "enum": ["thinking", "searching", "reading", "synthesizing", "done", "unknown"],
        },
        "confidence": {"type": "NUMBER"},
    },
    "required": ["narration", "progress", "steps", "phase_signal", "confidence"],
}


_SYSTEM_PROMPT = (
    "You read screenshots of an AI agent's research side panel (ChatGPT, "
    "Claude, or Gemini) and report what the agent is doing.\n"
    "RULES:\n"
    "1. Return verbatim panel text in `steps`. Do NOT paraphrase row text.\n"
    "2. `progress` = the single in-progress row (spinner) if visible; else "
    "the most recent row.\n"
    "3. `narration` = ONE human sentence summarizing what the agent is "
    "doing RIGHT NOW. Maximum 110 characters. Start with the verb. No "
    "em-dashes. Cite real specifics (query, source, section) from the "
    "screenshot.\n"
    "4. If the panel is closed/empty/loading, set confidence < 0.4 and "
    "narration='Panel loading, no activity visible.'\n"
    "5. Never invent step text. If you can't read it clearly, drop the row.\n"
    "6. If you see 'Research complete' or a duration card, set "
    "phase_signal='done'."
)


@dataclass
class _Metrics:
    calls_total: int = 0
    calls_this_phase: int = 0
    last_call_ts: float = 0.0
    successes: int = 0
    failures: int = 0
    skipped_cooldown: int = 0
    skipped_budget: int = 0
    by_model: dict[str, int] = field(default_factory=dict)
    last_latency_ms: float = 0.0
    last_error: str = ""


_M = _Metrics()


def reset_phase_budget() -> None:
    """Call from phase_start hook so budget resets per phase."""
    _M.calls_this_phase = 0
    _M.skipped_cooldown = 0
    _M.skipped_budget = 0


def get_metrics() -> dict:
    return {
        "calls_total": _M.calls_total,
        "calls_this_phase": _M.calls_this_phase,
        "successes": _M.successes,
        "failures": _M.failures,
        "skipped_cooldown": _M.skipped_cooldown,
        "skipped_budget": _M.skipped_budget,
        "by_model": dict(_M.by_model),
        "last_latency_ms": _M.last_latency_ms,
        "last_error": _M.last_error,
    }


async def narrate_panel(
    page: Any,
    *,
    agent: str,
    phase: int,
    workflow_name: str = "",
    last_dom_progress: str = "",
    last_dom_sources: int = 0,
    last_dom_steps_n: int = 0,
) -> dict | None:
    """Take a screenshot of the agent page, ask Gemini Flash to extract
    panel state. Returns a dict matching the JSON schema, or None on
    skip/failure (caller treats None as "narrator didn't help, fall through").

    Throttling rules (in order):
      1. cooldown -- never within MIN_GAP_S of the last call.
      2. budget   -- never more than PHASE_BUDGET per phase.
    """
    # Prefer the user's Account-page key (Firestore apiKeys.gemini) over
    # any env. Late import to dodge the research↔gemini_narrate cycle —
    # gemini_narrate is imported by research.py, so by the time
    # narrate_panel runs, research.resolve_gemini_api_key is fully defined.
    api_key = ""
    try:
        from research import resolve_gemini_api_key as _resolve
        api_key = _resolve() or ""
    except Exception:
        api_key = ""
    if not api_key:
        api_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or _read_user_scope_env_safe("GEMINI_API_KEY")
        )
    if not api_key:
        return None

    now = time.time()
    if now - _M.last_call_ts < MIN_GAP_S:
        _M.skipped_cooldown += 1
        return None
    if _M.calls_this_phase >= PHASE_BUDGET:
        _M.skipped_budget += 1
        if _M.calls_this_phase == PHASE_BUDGET:
            logger.warning("gemini_narrate: phase budget %d exhausted", PHASE_BUDGET)
        return None

    try:
        png = await page.screenshot(type="png", full_page=False)
    except Exception as e:
        _M.last_error = f"screenshot: {e}"
        return None

    if PANEL_CROP_RIGHT_FRACTION < 1.0:
        png = _crop_right_fraction(png, PANEL_CROP_RIGHT_FRACTION)

    user_msg = (
        f"Agent: {agent}  Phase: {phase}  Workflow: {workflow_name or '?'}\n"
        f"Last known DOM scrape: progress=\"{last_dom_progress[:140]}\" "
        f"sources={last_dom_sources} steps_count={last_dom_steps_n}\n"
        "The side panel is on the right of the screenshot. Extract panel "
        "state and produce the JSON."
    )

    _M.last_call_ts = now
    _M.calls_this_phase += 1
    _M.calls_total += 1

    for model in (GEMINI_MODEL_PRIMARY, GEMINI_MODEL_FALLBACK):
        result = await asyncio.to_thread(
            _call_gemini, api_key, model, png, user_msg
        )
        if result.get("ok"):
            _M.successes += 1
            _M.by_model[model] = _M.by_model.get(model, 0) + 1
            _M.last_latency_ms = result.get("latency_ms", 0.0)
            data = result["data"]
            # _source is the technique tag (visual-scrape vs DOM-scrape) read
            # by research.py to label the analytics payload — not the module
            # name. Kept as "vision" intentionally; downstream consumers
            # branch on this string.
            data["_source"] = "vision"
            data["_model"] = model
            return data
        if result.get("status") == 429 and model == GEMINI_MODEL_PRIMARY:
            logger.info("gemini_narrate: 429 on primary, retrying on fallback")
            continue
        _M.failures += 1
        _M.last_error = result.get("error", "unknown")
        return None

    _M.failures += 1
    return None


def _call_gemini(api_key: str, model: str, png: bytes, user_msg: str) -> dict:
    """Synchronous Gemini call (run in to_thread). Returns
    {"ok": bool, "data": {...}, "status": int, "latency_ms": float, "error": str}."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inlineData": {
                    "mimeType": "image/png",
                    "data": base64.standard_b64encode(png).decode("ascii"),
                }},
                {"text": user_msg},
            ],
        }],
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 600,
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
            # Disable thinking — for narration we want all 600 tokens to go
            # to the structured JSON output, not internal reasoning. With
            # thinking ON (Gemini 2.5 default), JSON output sometimes gets
            # truncated mid-field, returning partial responses.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    t0 = time.time()
    try:
        resp = requests.post(url, json=payload, timeout=GEMINI_TIMEOUT_S)
    except requests.RequestException as e:
        return {"ok": False, "status": 0, "error": f"requests: {e}",
                "latency_ms": (time.time() - t0) * 1000}
    latency_ms = (time.time() - t0) * 1000.0
    if resp.status_code != 200:
        return {"ok": False, "status": resp.status_code,
                "error": f"http {resp.status_code}: {resp.text[:200]}",
                "latency_ms": latency_ms}
    try:
        j = resp.json()
        text = (j.get("candidates", [{}])[0]
                  .get("content", {}).get("parts", [{}])[0]
                  .get("text", ""))
        data = json.loads(text)
    except Exception as e:
        return {"ok": False, "status": resp.status_code,
                "error": f"parse: {e}", "latency_ms": latency_ms}

    data["narration"] = (data.get("narration") or "").strip()[:140]
    data["progress"]  = (data.get("progress") or "").strip()[:200]
    data["steps"]     = [s.strip()[:220] for s in (data.get("steps") or [])][:15]
    data["sections"]  = [s.strip()[:80]  for s in (data.get("sections") or [])][:10]
    try:
        data["sources_observed"] = int(data.get("sources_observed") or 0)
    except Exception:
        data["sources_observed"] = 0
    try:
        data["confidence"] = float(data.get("confidence") or 0.0)
    except Exception:
        data["confidence"] = 0.0
    return {"ok": True, "data": data, "status": 200, "latency_ms": latency_ms}


def _crop_right_fraction(png: bytes, frac: float) -> bytes:
    """Crop the rightmost `frac` of the PNG (where the panel is). Pillow
    is already a dep. Best-effort -- return original on failure."""
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(png))
        w, h = img.size
        left = max(0, int(w * (1.0 - frac)))
        cropped = img.crop((left, 0, w, h))
        out = BytesIO()
        cropped.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return png


def _read_user_scope_env_safe(name: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import subprocess
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"[System.Environment]::GetEnvironmentVariable('{name}','User')"],
            capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ""
