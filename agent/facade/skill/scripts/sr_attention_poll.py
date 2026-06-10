#!/usr/bin/env python3
"""sr_attention_poll.py — the Super Research streaming watchdog (chat push).

Runs as a Hermes `no_agent` cron job (created by the /sr skill via the gateway's
`cronjob` tool, bound to the originating chat via deliver="origin"). Each tick it
asks the loopback bridge for the recent runs and prints — VERBATIM, for the chat —
only what is NEW since the last tick:

  • a phase link the user hasn't been sent,
  • a run that just started needing the user (login / verification / a snag / an
    error), with how to act from chat ("retry" / "skip"),
  • a run that just finished / stopped / errored.

It prints NOTHING when there's nothing new — the `no_agent` contract treats empty
stdout as silent, so the user is never spammed. State lives in a sibling file so
de-dup survives across the fresh, contextless cron sessions. Stdlib only, loopback
only (same contract as sr.py); it never touches Firestore, tokens, or the network.

Why a script (not the agent): a cron LLM session is fresh each tick with no chat
history, so it can't remember what it already posted — only a stateful script can
de-dup. Why cron at all: there is no timer that re-invokes a skill; the gateway's
cron scheduler is the only periodic engine, and a deliver="origin" job posts back
to the chat it was created from.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_TIMEOUT = 15
_STATE_FILE = Path(__file__).with_name(".sr_stream_state.json")

# Terminal statuses → the final chat line. error / watchdog-stop point at `retry`
# (they're recoverable from chat); a clean finish / user-stop just confirms.
_TERMINAL_MSG = {
    "completed": "✓ “{t}” finished.",
    "archived": "✓ “{t}” finished.",
    "stopped": "⏹ “{t}” stopped — the results so far are kept.",
    "error": "✗ “{t}” hit an error — reply “retry” to resume, or open the app.",
    "stopped_by_watchdog": "⏹ “{t}” stalled and was stopped — reply “retry”, or open the app.",
    "terminated_by_user_discard": "⏹ “{t}” was discarded.",
}


def _base() -> str:
    raw = os.environ.get("SUPER_AGENT_BRIDGE_PORT", "9876")
    try:
        port = int(raw)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        port = 9876
    return f"http://127.0.0.1:{port}"


def _get_updates() -> list:
    req = urllib.request.Request(_base() + "/updates?limit=20", method="GET")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = json.loads(resp.read() or b"{}")
    return body.get("runs", []) if isinstance(body, dict) else []


def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text("utf-8")) or {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state), "utf-8")
    except Exception:
        pass  # best-effort; a missed save just re-announces next tick (rare)


def _run_lines(run: dict, prior: dict) -> list[str]:
    """The NEW chat lines for one run vs its last-seen state (`prior`)."""
    title = run.get("title") or run.get("topic") or run.get("runId") or "your run"
    lines: list[str] = []

    # New phase links (dedup by kind).
    prior_kinds = set(prior.get("links", []))
    for lk in run.get("links", []) or []:
        kind = lk.get("kind")
        if kind and kind not in prior_kinds:
            label = lk.get("label") or kind
            lines.append(f"🔗 “{title}”: {label} — {lk.get('url')}")

    # Newly needs the user (or the reason changed).
    needs = bool(run.get("needsAttention"))
    attention = run.get("attention") or ""
    if needs and (not prior.get("needs") or prior.get("attention") != attention):
        lines.append(
            f"⚠ “{title}” needs you: {attention or 'a decision'} — "
            "reply “retry” to resume or “skip” to move past it (or open the app)."
        )

    # Just reached a terminal state (announce once).
    status = run.get("status")
    if status in _TERMINAL_MSG and not prior.get("announced_terminal"):
        lines.append(_TERMINAL_MSG[status].format(t=title))
    return lines


def compute(runs: list, prior_state: dict) -> tuple[list[str], dict]:
    """Pure core (unit-tested): (chat lines to post, new state to persist)."""
    out: list[str] = []
    new_state: dict = {}
    for run in runs:
        rid = run.get("runId")
        if not rid:
            continue
        prior = prior_state.get(rid, {})
        out.extend(_run_lines(run, prior))
        status = run.get("status")
        new_state[rid] = {
            "status": status,
            "needs": bool(run.get("needsAttention")),
            "attention": run.get("attention") or "",
            "links": [lk.get("kind") for lk in (run.get("links") or []) if lk.get("kind")],
            "announced_terminal": bool(prior.get("announced_terminal")) or status in _TERMINAL_MSG,
        }
    return out, new_state


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        runs = _get_updates()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        # Bridge down / unreachable — stay SILENT (exit 0). A non-zero exit would
        # trip the cron error alert every minute while the host bridge is off.
        return 0
    lines, new_state = compute(runs, _load_state())
    _save_state(new_state)
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
