#!/usr/bin/env python3
"""sr_attention_poll.py — the Super Research streaming watchdog (chat push).

Runs as a Hermes `no_agent` cron job (created by the /sr skill via the gateway's
`cronjob` tool, bound to the originating chat via deliver="origin"). Each tick it
asks the loopback bridge for the AGENT-started runs (`/updates?via=agent` — so
web-app runs never clutter the chat) and prints — VERBATIM, for the chat — only
what is NEW since the last tick. It is deliberately QUIET: it does NOT narrate
per-phase progress. The only things it posts on its own are:

  • ONE completion message when a run finishes — the 🎉 banner + every phase's
    permanent, non-revocable Super Research link (Brief, the three Deep-Research
    reports, the Podcast) + "results have been emailed". Platform links
    (NotebookLM / YouTube / final Google Doc) are never sent (revocable / not
    openable when signed out),
  • a run that needs the user (login / verification / a snag / an error), with how
    to act from chat ("retry" / "skip"),
  • a run that was stopped / cancelled (from chat or the web app).

Per-phase progress + the links available SO FAR are ON-DEMAND only: the user asks
"status" and sr.py returns the current phase + each finished phase's SR link. The
watchdog never pushes those — so the chat isn't spammed phase by phase.

It prints NOTHING when there's nothing new — the `no_agent` contract treats empty
stdout as silent, so the user is never spammed. State lives in a sibling file so
de-dup (which phases were already seen, whether the completion was posted) survives
across the fresh, contextless cron sessions. Stdlib only, loopback only (same
contract as sr.py); it never touches Firestore, tokens, or the network.

Why a script (not the agent): a cron LLM session is fresh each tick with no chat
history, so it can't remember what it already posted — only a stateful script can
de-dup. Why cron at all: there is no timer that re-invokes a skill; the gateway's
cron scheduler is the only periodic engine, and a deliver="origin" job posts back
to the chat it was created from. The bridge does the phase→link mapping + lazily
mints each phase's permanent share; this script just renders + de-dups.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_TIMEOUT = 30  # the bridge may mint a phase's SR share on this call (FE round-trip)
_STATE_FILE = Path(__file__).with_name(".sr_stream_state.json")

# On the BASELINE tick (watchdog just armed) a completion is announced only when
# it's this recent — so arming while an OLD finished run sits in the /updates
# window doesn't replay a stale 🎉, but a run that finished just before the first
# tick (watchdog armed late — e.g. after an update/restart) still gets announced.
_RECENT_COMPLETION_MS = 6 * 3600 * 1000  # 6h


def _now_ms() -> float:
    return time.time() * 1000


def _run_epoch_ms(run: dict) -> "float | None":
    """`updatedAt` as epoch millis. Firestore hands it back as an ISO-8601 string
    (timestampValue); a numeric millis is also accepted. None when absent/unparseable
    (→ callers treat it as NOT recent, the safe/quiet direction)."""
    v = run.get("updatedAt")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str) and v:
        try:
            return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000
        except Exception:
            return None
    return None


def _is_recent_completion(run: dict, now_ms: float) -> bool:
    ms = _run_epoch_ms(run)
    return ms is not None and (now_ms - ms) < _RECENT_COMPLETION_MS

# Statuses that are genuinely "stuck mid-flight" — the only blockers worth raising
# on the BASELINE tick. A long-dead errored run is history the user already saw.
_LIVE_STUCK = ("queued", "ongoing", "paused_backend_restart", "paused_backend_restart_failed")

# A login-listener watchdog (armed at /sr login or a signed-out research) polls
# before the user has signed in → the bridge returns 401. Stay silent + alive so we
# can announce the instant they do, but give up after this many minute-ticks (well
# past the ~15-min sign-in TTL) so a sign-in that never completes can't poll forever.
_LOGIN_WAIT_LIMIT = 18


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


def _get_updates(origin: dict | None = None) -> tuple[list, dict | None]:
    """``(runs, signedIn)`` from the bridge. ``signedIn`` is the one-shot
    "just signed in" event (or None) the bridge delivers once after a remote-login
    capture — so an armed watchdog announces the sign-in (and any pending topic)
    proactively. Raises on HTTP/transport error (main() handles a 401 specially)."""
    q = "/updates?via=agent&limit=20"
    if origin:
        q += "&platform=" + urllib.parse.quote(origin.get("platform", ""), safe="")
        q += "&chat=" + urllib.parse.quote(origin.get("chat_id", ""), safe="")
    req = urllib.request.Request(_base() + q, method="GET")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = json.loads(resp.read() or b"{}")
    if not isinstance(body, dict):
        return [], None
    si = body.get("signedIn")
    return body.get("runs", []), (si if isinstance(si, dict) else None)


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


# ── strict run-linked teardown ───────────────────────────────────────────────
# The watchdog is a recurring Hermes cron job (`sr-stream-<slug>`, every 1m). It
# must STOP — and clean up its own cron entry + shim + state — once this chat has
# no live work left, so it never lingers polling forever or, worse, fires after
# `disconnect` deleted its script (the "Script not found" chat spam). We can't
# call Hermes's agent-only `cronjob` tool from here, so we remove our OWN entry
# from the cron's data file (`<HERMES_HOME>/cron/jobs.json`, which Hermes re-reads
# every tick) — only the entry we created, matched by name; never touching others.

# Runs still in flight (or stuck awaiting the user) — work the watchdog must keep
# streaming. Everything else (completed / errored-and-done / cancelled) is terminal.
_ACTIVE = ("queued", "ongoing", "paused_backend_restart", "paused_backend_restart_failed")


def _is_active(run: dict) -> bool:
    return run.get("status") in _ACTIVE or bool(run.get("needsAttention"))


def _hermes_home() -> Path:
    """<HERMES_HOME> — this watchdog lives at <HERMES_HOME>/scripts/<this file>."""
    return Path(__file__).resolve().parent.parent


def _remove_cron_entry(job_name: str) -> bool:
    """Remove the job named ``job_name`` from <HERMES_HOME>/cron/jobs.json (atomic,
    best-effort). Only ever drops the entry we created; leaves every other job
    untouched. Returns True if an entry was removed. No-op (False) if the file is
    absent / unreadable / has no such job — so an already-clean state is harmless."""
    path = _hermes_home() / "cron" / "jobs.json"
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:
        return False
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        return False
    kept = [j for j in jobs if not (isinstance(j, dict) and j.get("name") == job_name)]
    if len(kept) == len(jobs):
        return False
    data["jobs"] = kept
    try:
        tmp = path.with_suffix(".json.sr-tmp")
        tmp.write_text(json.dumps(data), "utf-8")
        os.replace(tmp, path)  # atomic; Hermes re-reads jobs.json each tick
        return True
    except Exception:
        return False


def _teardown(origin: dict) -> None:
    """Stop this chat's watchdog for good: drop its cron entry, then delete its
    generated shim + de-dup state. Scoped (per-chat) only — never the shared,
    account-wide watchdog (its sr_attention_poll.py is used by every chat)."""
    slug = _origin_slug(origin)
    _remove_cron_entry(f"sr-stream-{slug}")
    for p in (_hermes_home() / "scripts" / f"sr_poll_{slug}.py", _state_path(origin)):
        try:
            p.unlink()
        except OSError:
            pass


def _title(run: dict) -> str:
    t = (run.get("title") or run.get("topic") or run.get("runId") or "your run").strip()
    return t if len(t) <= 60 else t[:60].rstrip() + "…"


def _final_lines(run: dict) -> list[str]:
    """The single end-of-run message: the pipeline-complete banner + EVERY phase's
    link, gathered across all phaseUpdates, de-duped, in phase order — the SR
    permanent links (🔒: Brief, the three reports, the Podcast) AND the real platform
    links (🔗: NotebookLM, YouTube, the Google Doc). Results were also emailed."""
    lines = [f"🎉 “{_title(run)}” · pipeline complete — results have been emailed."]
    seen: set[str] = set()
    for pu in run.get("phaseUpdates", []) or []:
        for lk in pu.get("links", []) or []:
            url = lk.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            glyph = "🔒" if lk.get("permanent") else "🔗"
            lines.append(f"   {glyph} {lk.get('label') or 'link'}: {url}")
    return lines


def _attention_line(run: dict) -> str:
    t = _title(run)
    reason = run.get("attention") or "a decision is needed"
    return (f"⚠ “{t}” needs you: {reason} — "
            "reply “retry” to resume or “skip” to move past it (or open the app).")


def _ended_line(run: dict) -> str:
    return (f"⏹ “{_title(run)}” stopped — the partial results so far are kept. "
            "Say “retry” to resume, or start a new research.")


def compute(runs: list, prior_state: dict, *, baseline: bool = False,
            now_ms: "float | None" = None) -> tuple[list[str], dict]:
    """Pure core (unit-tested): (chat lines to post, new state to persist).

    Quiet by design: per-phase progress is NEVER pushed (that's on-demand via
    `status`). The only run-progress message posted proactively is the ONE
    completion banner + all SR links, emitted when the run reaches its terminal
    ``completed`` STATUS — NOT off a single phase's ``final`` flag: a run with its
    last phase disabled (e.g. email off) still completes and must announce, and a
    phase seen earlier as non-final must still trigger the banner when the run
    finishes. Completion is tracked via the per-run ``completed`` flag so it fires
    exactly once and survives across ticks (the state file outlives a bridge
    restart). A needs-attention blocker and an ended-early notice are the other two
    proactive messages. ``baseline=True`` (first tick after arming) stays SILENT for
    pre-existing progress — but STILL announces a RECENT completion (a run that
    finished right before a late/first tick, e.g. the watchdog armed after an
    update/restart) and still raises a blocker on a run stuck RIGHT NOW."""
    if now_ms is None:
        now_ms = _now_ms()
    out: list[str] = []
    new_state: dict = {}
    for run in runs:
        rid = run.get("runId")
        if not rid:
            continue
        prior = prior_state.get(rid, {})
        # Track seen phases silently (per-phase progress is on-demand only); kept so
        # a manual `status` and the state shape stay stable, not used to gate the
        # completion announce anymore.
        announced = set(prior.get("announced", []))
        for pu in run.get("phaseUpdates", []) or []:
            p = pu.get("phase")
            if p is not None:
                announced.add(p)

        # ONE proactive completion announce, driven by the run's terminal status.
        # Fires exactly once (tracked via `completed`); on a baseline tick only a
        # RECENT completion posts (an old finished run in the window on first arm
        # stays quiet, but is still marked so it never replays later).
        completed_announced = bool(prior.get("completed"))
        run_completed = run.get("status") == "completed"
        if run_completed and not completed_announced:
            if not baseline or _is_recent_completion(run, now_ms):
                out.extend(_final_lines(run))
            completed_announced = True

        needs = bool(run.get("needsAttention"))
        attention = run.get("attention") or ""
        prior_needs = bool(prior.get("needs"))
        prior_attn = prior.get("attention") or ""
        if needs and (not prior_needs or prior_attn != attention):
            live_stuck = run.get("status") in _LIVE_STUCK
            if not baseline or live_stuck:
                out.append(_attention_line(run))

        # Ended early — stopped / cancelled from the app or chat (NOT a normal
        # finish, which is status=="completed" → the 🎉 banner above). Announce ONCE
        # so a chat user who stops from the web app isn't left hanging. Gated on
        # `prior` (we tracked this run while it was live, so this is a real
        # transition, not an old terminal run surfacing) and never on baseline.
        ended = (not _is_active(run)) and not run_completed
        prior_ended = bool(prior.get("ended"))
        if ended and not prior_ended and not baseline and prior:
            out.append(_ended_line(run))

        new_state[rid] = {
            "announced": sorted(announced),
            "needs": needs,
            "attention": attention,
            "ended": ended,
            "completed": completed_announced,
        }
    return out, new_state


def _signed_in_line(signed_in: dict) -> str:
    """The proactive sign-in announce. When a research was fired while signed out,
    the BRIDGE starts it server-side at sign-in and reports it here — no fragile
    "reply yes" round-trip that depends on the assistant interpreting a bare "yes".
    If the account has no research node, this surfaces the pair-a-node step. Only
    when the bridge couldn't auto-start (older bridge / ambiguous device) does it
    fall back to OFFERING to continue ("reply yes"). With no pending research it
    just confirms the connection."""
    who = signed_in.get("email") or "your account"
    # Full topic (bounded to 500 chars at ingest), never a truncated preview.
    topic = (signed_in.get("topic") or signed_in.get("pendingTopic") or "").strip()
    quoted = f"“{topic}”" if topic else "your research"
    if signed_in.get("autoStarted"):
        dev = (signed_in.get("deviceName") or "").strip()
        on_dev = f" on {dev}" if dev else ""
        return (
            f"✓ Signed in.\n\n"
            f"Starting {quoted}{on_dev} now — I'll post progress here as each phase finishes."
        )
    if signed_in.get("needsDevice"):
        # Multi-line + a Rocky-free path FIRST (scan the QR), then the exact one-line
        # chat form (code + command together — the reliable shape for the gateway).
        return (
            f"✓ Signed in as {who}.\n\n"
            f"There's no Research Computer on your account yet, so {quoted} has nowhere to run.\n\n"
            f"On a computer with Super Research, run:\n"
            f"      superresearch --pair\n"
            f"It shows an 8-char code. Then add the Research Computer either way:\n\n"
            f"1) In the web app (most reliable):\n"
            f"      superresearch.io → Account → Pipeline Connection → Add Device\n\n"
            f"2) Or from here — send the code with the command, in ONE message:\n"
            f"      /sr device-add YOUR-CODE\n\n"
            f"No Super Research on any computer yet? Install it first:\n"
            f"  • Windows:      irm https://superresearch.io/install.ps1 | iex\n"
            f"  • macOS/Linux:  curl -fsSL https://superresearch.io/install.sh | sh"
        )
    # Fallback: bridge couldn't auto-start — OFFER to continue (legacy handoff).
    if (signed_in.get("pendingTopic") or "").strip():
        return f"✓ Signed in as {who}.\n\nContinue with “{topic}”? Reply “yes” to start."
    return f"✓ Signed in as {who}.\n\nJust tell me what to research."


def _tick_unauthed(origin: dict | None, state_file: Path) -> int:
    """A 401 while a login-listener is armed: the user hasn't signed in yet. Stay
    SILENT + alive so we can announce the moment they do — but bound the wait
    (``_LOGIN_WAIT_LIMIT`` ticks) so a sign-in that never completes can't poll
    forever. Bounds SCOPED watchdogs only; the shared account-wide watchdog
    (origin=None) is never self-removed (its script serves every chat), so it just
    no-ops here and keeps polling — acceptable since the modern gateway always
    supplies an origin (so login-listeners are scoped + bounded)."""
    if not origin:
        return 0
    prior = _load_state(state_file) or {}
    waited = int(prior.get("__login_wait__", 0) or 0) + 1
    if waited > _LOGIN_WAIT_LIMIT:
        _teardown(origin)
        return 0
    prior["__login_wait__"] = waited
    _save_state(prior, state_file)
    return 0


def main(origin: dict | None = None) -> int:
    """One watchdog tick. ``origin`` (passed by a generated per-chat shim) scopes
    the bridge query + the de-dup state file to one chat; None = the shared,
    account-wide watchdog (single-chat correct, the legacy behavior)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    state_file = _state_path(origin)
    try:
        fetched = _get_updates(origin)
    except urllib.error.HTTPError as e:
        # 401 = a login-listener armed before the user signed in: wait quietly.
        # Any other HTTP error → silent (a non-zero exit would trip the cron error
        # alert every minute while the host bridge is off).
        if getattr(e, "code", None) == 401:
            return _tick_unauthed(origin, state_file)
        return 0
    except (urllib.error.URLError, OSError, ValueError):
        return 0
    # Back-compat unpack: real fetch returns (runs, signedIn); a test/monkeypatch or
    # an older shim may hand back just the runs list.
    runs, signed_in = fetched if isinstance(fetched, tuple) else (fetched, None)
    prior = _load_state(state_file)
    pdict = prior or {}

    out: list[str] = []
    # Proactive "signed in" announce — one-shot. The bridge already clears it after
    # one delivery; __signed_in_ts__ is a belt-and-suspenders de-dup across ticks.
    announced_login = False
    si_ts = pdict.get("__signed_in_ts__")
    if isinstance(signed_in, dict) and signed_in.get("ts") and signed_in.get("ts") != si_ts:
        out.append(_signed_in_line(signed_in))
        si_ts = signed_in.get("ts")
        announced_login = True

    # Baseline = we've never recorded this chat's RUNS before. A state file that
    # holds only reserved keys (e.g. __login_wait__ written by unauthed login-wait
    # ticks) is NOT a real run-baseline — without this, the first authed tick after
    # sign-in would replay an OLD finished/stuck run as if it just happened.
    seen_runs_before = any(not str(k).startswith("__") for k in pdict)
    run_lines, new_state = compute(runs, pdict, baseline=not seen_runs_before)
    out += run_lines
    # compute() rebuilds new_state from runs only, so re-stamp the de-dup key (and
    # drop __login_wait__ now that we're authed).
    if si_ts is not None:
        new_state["__signed_in_ts__"] = si_ts
    _save_state(new_state, state_file)
    if out:
        print("\n".join(out))

    # Strict teardown (scoped only): a login-listener stops once it has made its one
    # announce and nothing is running (a later research re-arms a fresh watchdog);
    # a run watchdog stops once this chat has runs but NONE are live and there's
    # nothing new to post. Never tear down on an empty window or while still posting.
    #
    # RACE GUARD: do NOT tear down on the same tick we announced a sign-in that
    # AUTO-STARTED a run — the new run is often not visible in /updates yet
    # (Firestore lag), so no_active is a false "nothing to do" that would delete the
    # very watchdog that must stream (and announce completion for) that run. Keep it
    # alive; the `runs and not out` path below tears it down once the run is observed
    # and finishes.
    if origin:
        no_active = not any(_is_active(r) for r in runs)
        login_autostarted = bool(signed_in.get("autoStarted")) if isinstance(signed_in, dict) else False
        login_done_idle = announced_login and no_active and not login_autostarted
        if login_done_idle or (runs and not out and no_active):
            _teardown(origin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
