#!/usr/bin/env python3
"""sr_attention_poll.py — the Super Research streaming watchdog (chat push).

Runs as a Hermes `no_agent` cron job (created by the /sr skill via the gateway's
`cronjob` tool, bound to the originating chat via deliver="origin"). Each tick it
asks the loopback bridge for the AGENT-started runs (`/updates?via=agent` — so
web-app runs never clutter the chat) and prints — VERBATIM, for the chat — only
what is NEW since the last tick:

  • one clean message per PHASE as it completes, carrying that phase's permanent,
    non-revocable Super Research link(s) — the same ones embedded in the delivered
    Google Doc (Brief → reports → NotebookLM+Podcast → YouTube → final Doc), NOT
    the raw platform links (which aren't openable when you're not logged in),
  • a run that needs the user (login / verification / a snag / an error), with how
    to act from chat ("retry" / "skip").

It prints NOTHING when there's nothing new — the `no_agent` contract treats empty
stdout as silent, so the user is never spammed. State lives in a sibling file so
de-dup (which phases were already announced) survives across the fresh, contextless
cron sessions. Stdlib only, loopback only (same contract as sr.py); it never
touches Firestore, tokens, or the network.

Why a script (not the agent): a cron LLM session is fresh each tick with no chat
history, so it can't remember what it already posted — only a stateful script can
de-dup. Why cron at all: there is no timer that re-invokes a skill; the gateway's
cron scheduler is the only periodic engine, and a deliver="origin" job posts back
to the chat it was created from. The bridge does the phase→link mapping + lazily
mints each phase's permanent share; this script just renders + de-dups.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_TIMEOUT = 30  # the bridge may mint a phase's SR share on this call (FE round-trip)
_STATE_FILE = Path(__file__).with_name(".sr_stream_state.json")

# Statuses that are genuinely "stuck mid-flight" — the only blockers worth raising
# on the BASELINE tick. A long-dead errored run is history the user already saw.
_LIVE_STUCK = ("queued", "ongoing", "paused_backend_restart", "paused_backend_restart_failed")


def _base() -> str:
    raw = os.environ.get("SUPER_AGENT_BRIDGE_PORT", "9876")
    try:
        port = int(raw)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        port = 9876
    return f"http://127.0.0.1:{port}"


def _origin_slug(origin: dict) -> str:
    """A short, filesystem-safe id for a chat origin: a readable platform prefix
    plus a hash of the full (platform, chat, thread) tuple. MUST stay identical
    to sr._origin_slug so a generated shim (sr_poll_<slug>.py) and the state file
    main() derives below (.sr_poll_<slug>.state.json) carry the same slug."""
    platform = re.sub(r"[^A-Za-z0-9]", "", (origin.get("platform") or "")).lower()[:16] or "chat"
    key = "\x00".join((origin.get("platform") or "", origin.get("chat_id") or "",
                       origin.get("thread_id") or ""))
    return f"{platform}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


def _state_path(origin: dict | None) -> Path:
    """The de-dup state file: the shared default for the account-wide watchdog,
    or a per-chat file when scoped (so two chats' watchdogs never share state)."""
    if not origin:
        return _STATE_FILE
    return Path(__file__).with_name(f".sr_poll_{_origin_slug(origin)}.state.json")


def _get_updates(origin: dict | None = None) -> list:
    q = "/updates?via=agent&limit=20"
    if origin:
        q += "&platform=" + urllib.parse.quote(origin.get("platform", ""), safe="")
        q += "&chat=" + urllib.parse.quote(origin.get("chat_id", ""), safe="")
    req = urllib.request.Request(_base() + q, method="GET")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = json.loads(resp.read() or b"{}")
    return body.get("runs", []) if isinstance(body, dict) else []


def _load_state(path: Path | None = None) -> dict | None:
    """The persisted last-seen state, or None when there is none (first tick
    after arming, or an unreadable/corrupt file). None signals compute() to
    BASELINE silently instead of replaying every already-done phase into chat."""
    try:
        data = json.loads((path or _STATE_FILE).read_text("utf-8"))
        if not isinstance(data, dict):
            return None
        # Migration: a PRE-phaseUpdates state (keyed by links/announced_terminal,
        # no "announced") would make the new phase-completion compute() treat every
        # done phase as new and re-announce the lot. Treat any old-format state as
        # no-state → a silent baseline tick, which then re-persists the new shape.
        for v in data.values():
            if isinstance(v, dict) and "announced" not in v and ("announced_terminal" in v or "links" in v):
                return None
        return data
    except Exception:
        return None


def _save_state(state: dict, path: Path | None = None) -> None:
    try:
        (path or _STATE_FILE).write_text(json.dumps(state), "utf-8")
    except Exception:
        pass  # best-effort; a missed save just re-announces next tick (rare)


def _title(run: dict) -> str:
    t = (run.get("title") or run.get("topic") or run.get("runId") or "your run").strip()
    return t if len(t) <= 60 else t[:60].rstrip() + "…"


def _phase_lines(run: dict, pu: dict) -> list[str]:
    """The chat message for one completed/skipped phase."""
    t = _title(run)
    p, name, st = pu.get("phase"), pu.get("name", "Phase"), pu.get("status")
    if st == "skipped":
        return [f"⏭ “{t}” · Phase {p} ({name}) skipped"]
    if pu.get("final"):
        head = f"🎉 “{t}” · pipeline complete — results have been emailed."
    else:
        head = f"✓ “{t}” · Phase {p} ({name}) complete"
    lines = [head]
    for lk in pu.get("links", []) or []:
        url = lk.get("url")
        if not url:
            continue
        icon = "🔒" if lk.get("permanent") else ("📄" if pu.get("final") else "🔗")
        lines.append(f"   {icon} {lk.get('label') or 'link'}: {url}")
    return lines


def _attention_line(run: dict) -> str:
    t = _title(run)
    reason = run.get("attention") or "a decision is needed"
    return (f"⚠ “{t}” needs you: {reason} — "
            "reply “retry” to resume or “skip” to move past it (or open the app).")


def compute(runs: list, prior_state: dict, *, baseline: bool = False) -> tuple[list[str], dict]:
    """Pure core (unit-tested): (chat lines to post, new state to persist).

    Phase-completion driven: each run carries `phaseUpdates` (the bridge's
    per-phase plan with permanent SR links); we post each phase once, then a
    needs-attention blocker. ``baseline=True`` (first tick after arming) records
    every already-done phase SILENTLY so pre-existing runs aren't replayed — but
    still raises a blocker on a run that is stuck RIGHT NOW."""
    out: list[str] = []
    new_state: dict = {}
    for run in runs:
        rid = run.get("runId")
        if not rid:
            continue
        prior = prior_state.get(rid, {})
        announced = set(prior.get("announced", []))
        for pu in run.get("phaseUpdates", []) or []:
            p = pu.get("phase")
            if p is None or p in announced:
                continue
            if not baseline:
                out.extend(_phase_lines(run, pu))
            announced.add(p)

        needs = bool(run.get("needsAttention"))
        attention = run.get("attention") or ""
        prior_needs = bool(prior.get("needs"))
        prior_attn = prior.get("attention") or ""
        if needs and (not prior_needs or prior_attn != attention):
            live_stuck = run.get("status") in _LIVE_STUCK
            if not baseline or live_stuck:
                out.append(_attention_line(run))

        new_state[rid] = {
            "announced": sorted(announced),
            "needs": needs,
            "attention": attention,
        }
    return out, new_state


def main(origin: dict | None = None) -> int:
    """One watchdog tick. ``origin`` (passed by a generated per-chat shim) scopes
    the bridge query + the de-dup state file to one chat; None = the shared,
    account-wide watchdog (single-chat correct, the legacy behavior)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        runs = _get_updates(origin)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        # Bridge down / unreachable — stay SILENT (exit 0). A non-zero exit would
        # trip the cron error alert every minute while the host bridge is off.
        return 0
    state_file = _state_path(origin)
    prior = _load_state(state_file)
    lines, new_state = compute(runs, prior or {}, baseline=prior is None)
    _save_state(new_state, state_file)
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
