#!/usr/bin/env python3
"""sr.py — the Super Research skill's thin client to the host bridge.

A chat runtime (Hermes / OpenClaw) runs this via `exec` and relays the output to
the user. It is intentionally STANDALONE and dependency-free (stdlib urllib
only) so it can live in the runtime's skills dir without the facade installed.

It only ever talks to the loopback bridge (127.0.0.1:<port>) that `agent serve`
runs; it never touches Firestore, tokens, or the network directly. Every
account action is the bridge's responsibility (single-owner session).

Commands (mirror the chat slash actions). A run is named by its TITLE (a word
or two from the topic) or run-id; omit it to mean the most recent / active run:
  login              start a remote sign-in → prints a code + link to relay
  login-done         poll until the sign-in is approved / expires (alias: login-wait)
  status-account     is the bridge up + signed in?
  devices            list reachable devices
  device-use <name>  choose the device runs go to (name or id)
  device-add <code>  pair a new device by the code on its screen
  device-remove <name>  unlink a device (owner keeps it re-pairable; sharer leaves)
  research <topic>   start a run (--device <id> to override the selected device)
  status [run]       a run's progress + links + any blocker (no run = most recent)
  podcast [run]      download a run's audio → a local file to send as native audio
  updates            active runs + their links + any that need you (streaming cron)
  stop [run]         gracefully stop a run, keeping the results so far + the chat
  retry [run]        resume a run that's waiting on a decision / hit an error
  skip [phases…]     skip the run's current blocker (no phases) or named phases
                       (--run <run> to target one; else the latest active run)
  arm-stream         prepare this chat's streaming watchdog → prints the cron
                       script + job name to arm via the runtime's cronjob tool
  version            show the Super Research skill version
  update             update the Super Research skill (this chat — scripts + bridge)
  logout             clear the account session
  help               this list

Add --json to print the raw bridge response (the streaming cron uses
`sr.py --json updates`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

try:
    import fcntl  # POSIX advisory file lock. The Hermes host is always POSIX;
except ImportError:  # None elsewhere (e.g. a Windows test import) → lock-free write.
    fcntl = None

# The version of the agent package THIS script copy shipped with. The runtime
# executes its own installed COPY of this file (HERMES_HOME/scripts), which a
# `pip install -U` on the host does NOT refresh — only `connect` / “update”
# redeploys it. cmd_version compares this against the live bridge's version so a
# stale chat-side copy names itself instead of misbehaving
# silently (live 2026-07-02: a stale copy predating the podcast MEDIA: fix
# kept sending bare audio paths). Bumped together with pyproject.toml —
# guarded by tests/test_sr_skip_agents.py::test_skill_build_matches_package_version.
_SKILL_BUILD = "0.1.32"

_TIMEOUT = 30
# By-title run resolution scans the newest N runs (status / podcast / list / the
# resume verbs). 20 was too shallow — a run a few weeks back (named, not active)
# fell outside the window, so `podcast "Rocky Port…"` silently found nothing and
# the agent improvised. 100 covers a deep history; it's a plain Firestore list
# (no per-phase minting — that's only the via=agent `updates` path, left at 20).
# Mirrors the bridge's /updates limit cap (bridge.py `_updates`).
_LOOKUP_LIMIT = 100

# The human setup page (full walkthrough + the pro-account note). A markdown
# hyperlink so it lands as a clickable label in chat, not a bare URL. Kept
# distinct from the install.ps1/.sh SCRIPT URLs below.
_INSTALL_PAGE_URL = "https://superresearch.io/install"
# Bare URL (auto-links on every channel — NO Markdown, which would hard-code a
# rich-text channel assumption). Conditional lead ("don't have one?") so it reads
# gracefully even where the caller already told a user WITH a backend to just
# paste their pair code (reason=no_devices = no *paired* device, which includes an
# installed-but-unpaired machine — that user pairs, they don't reinstall).
_INSTALL_PAGE_LINE = (
    f"Don't have your own Research Computer yet? Set one up — full walkthrough: {_INSTALL_PAGE_URL}"
)

# How to install Super Research on a fresh Research Computer (no backend yet):
# the SAME one-line installer the web app's "Set up your own Research Computer"
# tile uses (auto-installs Python + pipx + superresearch), then `--pair`. Kept in
# ONE place so the `devices`-empty and `research`-no-device prompts stay identical
# + in sync with the web app. (Older builds said `pipx install superresearch`.)
_SETUP_NODE_LINES = [
    _INSTALL_PAGE_LINE,
    "It runs the research on a machine of yours (your PC / Mac / Linux box).",
    "",
    "Quick start — run one line there (pick your OS):",
    # Indent (not ``` fences) so the commands stay readable on plain-text
    # channels too — an SMS/relay that can't render Markdown would otherwise show
    # literal backticks. Matches sr_attention_poll._signed_in_line's 6-space style.
    "      irm https://superresearch.io/install.ps1 | iex      # Windows",
    "      curl -fsSL https://superresearch.io/install.sh | sh  # macOS / Linux",
    "      superresearch --pair",
    "It installs Super Research and prints an 8-char access code — read it to me.",
]


def _base() -> str:
    # Read the port lazily so the env can be set per invocation. Always loopback;
    # the env only chooses the port (validated — never a host).
    raw = os.environ.get("SUPER_AGENT_BRIDGE_PORT", "9876")
    try:
        port = int(raw)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        print(f"(ignoring bad SUPER_AGENT_BRIDGE_PORT {raw!r}; using 9876)", file=sys.stderr)
        port = 9876
    return f"http://127.0.0.1:{port}"


def _request(method: str, path: str, body: dict | None = None,
             timeout: float | None = None) -> tuple[int, dict]:
    url = _base() + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
            raw = resp.read()
            status = resp.status
            try:
                return status, (json.loads(raw) if raw else {})
            except ValueError:
                # A non-JSON 200 (proxy/HTML error page, truncated body) would
                # otherwise escape as a raw traceback to the chat runtime.
                return status, {"error": f"HTTP {status} (unexpected non-JSON reply from the bridge)"}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, (json.loads(raw) if raw else {})
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return 0, {"error": f"bridge unreachable ({e.reason}) — the Super Research bridge "
                            "isn't running on this machine yet. Set it up with `pipx run "
                            "--no-cache superresearch-agent connect` (it starts the bridge + keeps it "
                            "on login), then sign in."}
    except OSError as e:
        # HTTPError/URLError are OSError subclasses handled above, so this last
        # clause absorbs read timeouts (socket.timeout is TimeoutError) and other
        # low-level socket/OS errors into the same friendly line instead of a
        # raw traceback.
        return 0, {"error": f"bridge unreachable ({e}) — the Super Research bridge "
                            "isn't running on this machine yet. Set it up with `pipx run "
                            "--no-cache superresearch-agent connect` (it starts the bridge + keeps it "
                            "on login), then sign in."}


def _get(path: str, timeout: float | None = None) -> tuple[int, dict]:
    return _request("GET", path, timeout=timeout)


def _post(path: str, body: dict | None = None) -> tuple[int, dict]:
    return _request("POST", path, body if body is not None else {})


def _emit(payload: dict, as_json: bool, lines: list[str], code: int = 0) -> int:
    """Print either the raw JSON (cron) or the friendly lines (chat relay).

    Returns the process exit code so the streaming cron can tell success (0)
    from a bridge/session failure (non-zero)."""
    if as_json:
        print(json.dumps(payload))
    else:
        print("\n".join(lines))
    return code


def _fail_code(http_code: int) -> int:
    # 2 = bridge unreachable (http_code 0); 1 = any other non-200.
    return 2 if http_code == 0 else 1


# A do-not-relay marker for handing the chat AI a TOOL directive (e.g. the
# streaming cronjob) without it leaking into the chat. SKILL.md defines the
# contract: relay everything ABOVE this line verbatim; act on everything BELOW it
# SILENTLY (call the tool, never quote it, never announce it) — which is what
# fixes both the cluttered "Started" message and the duplicate "signing you in"
# message (the AI narrated the arming twice because the directive was mixed into
# the user text). Nothing runtime-specific is baked in — a runtime with no such
# tool just ignores the block, so it works AGAINST no runtime.
_AGENT_ONLY_MARKER = "── for the assistant · do NOT relay to the user ──"


def _agent_directive_block(directive_lines: list[str]) -> list[str]:
    """Wrap assistant-only instruction lines under the do-not-relay marker."""
    return ["", _AGENT_ONLY_MARKER, *directive_lines]


_SR_LINK_LABELS = {
    "brief": "Brief", "chatgpt": "ChatGPT report", "gemini": "Gemini report",
    "claude": "Claude report", "podcast": "Podcast",
}


def _fmt_sr_links(sr_links: dict) -> list[str]:
    """The permanent Super Research share links (the ones in the delivered doc —
    they never expire or get revoked). These are what to hand out when the user
    asks for "the podcast link" / a doc link."""
    if not sr_links:
        return []
    out = ["  Permanent links (never expire — safe to share):"]
    for key in ("podcast", "brief", "chatgpt", "gemini", "claude"):
        url = sr_links.get(key)
        if url:
            # Channel-neutral (label + bare URL): the raw URL auto-links on every
            # channel (Telegram/WhatsApp/SMS/…), and the runtime is free to render
            # it as a clickable label where it can. We do NOT emit Markdown here —
            # that would hard-code a rich-text channel assumption into the skill.
            out.append(f"  🔒 {_SR_LINK_LABELS.get(key, key)}: {url}")
    return out


def _fmt_phase_updates(phase_updates: list) -> list[str]:
    """Per-phase links for a status snapshot — one block per DONE phase. Carries the
    SR permanent links (🔒: Brief + the agent reports + the Podcast) AND the real
    platform links (🔗: NotebookLM + YouTube + the Google Doc). Mirrors what the
    streaming watchdog posts so a manual `status` shows the SAME links. On-demand
    path: lists the links available SO FAR while a run is mid-flight (the proactive
    watchdog holds the full set until the end)."""
    out: list[str] = []
    for pu in phase_updates or []:
        p, name, st = pu.get("phase"), pu.get("name", "Phase"), pu.get("status")
        if st == "skipped":
            out.append(f"  ⏭ Phase {p} ({name}) skipped")
            continue
        out.append(f"  {'🎉' if pu.get('final') else '✓'} Phase {p} ({name}) complete")
        for lk in pu.get("links", []) or []:
            url = lk.get("url")
            if not url:
                continue
            glyph = "🔒" if lk.get("permanent") else "🔗"
            # Channel-neutral label + bare URL (no Markdown — see _fmt_sr_links).
            out.append(f"     {glyph} {lk.get('label') or 'link'}: {url}")
    return out


# Phase numbers match the web app's pipeline (P1 Brief · P2 Deep Research ·
# P3 Podcast · P4 Video · P5 Report/Email) so the agent can answer "is P4/P5
# skipped?" directly from this line.
def _fmt_pipeline_config(cfg: dict | None) -> list[str]:
    """One compact line of which phases are ON / OFF for a run, so the agent can
    answer "is video / podcast / email skipped?" from a status check. Reads the
    run doc's live ``pipelineConfig`` (the FE toggle + /sr skip both write here);
    tolerates the agent-start ``skipPhases`` alias of ``skippedPhases``. Returns
    [] when there's no config to report (a legacy doc) rather than inventing one."""
    if not isinstance(cfg, dict) or not cfg:
        return []
    skipped: set[int] = set()
    for key in ("skippedPhases", "skipPhases"):
        v = cfg.get(key)
        if isinstance(v, list):
            skipped.update(p for p in v if isinstance(p, int) and not isinstance(p, bool))
    raw_agents = cfg.get("agents") if isinstance(cfg.get("agents"), dict) else {}
    on_agents = [name for name, key in (("ChatGPT", "chatgpt"), ("Gemini", "gemini"), ("Claude", "claude"))
                 if raw_agents.get(key, True)]

    def _s(on: bool) -> str:
        return "on" if on else "OFF"

    research_on = (2 not in skipped) and bool(on_agents)
    research = f"P2 Research {_s(research_on)}"
    if research_on:
        research += f" ({', '.join(on_agents)})"
    return [
        f"  ⚙ Phases: P1 Brief {_s(1 not in skipped)} · {research} · "
        f"P3 Podcast {_s(3 not in skipped)} · "
        f"P4 Video {_s(cfg.get('videoEnabled', True) is not False)} · "
        f"P5 Email {_s(cfg.get('emailEnabled', True) is not False)}"
    ]


# ── run resolution (titles, not ids) ─────────────────────────────────────────

def _fetch_runs(active: bool = False, limit: int = 20,
                via_agent: bool = False) -> tuple[int, dict, list]:
    """GET /updates → (http_code, body, runs). Runs are newest-first. With
    ``via_agent`` the bridge restricts to agent-started runs AND computes
    per-phase updates (lazily minting the permanent SR links) — used by the
    `updates` command so it streams the same clean per-phase links the watchdog
    does. The plain (resolution) calls leave it off to avoid needless minting."""
    q = "/updates?active=1" if active else f"/updates?limit={limit}"
    if via_agent:
        q += "&via=agent"
    code, body = _get(q)
    runs = body.get("runs", []) if isinstance(body, dict) else []
    return code, body, runs


def _pick_run(runs: list, arg: str | None, *, prefer_active: bool = False) -> dict | None:
    """Resolve an optional run arg to a run row. None → newest (active-first when
    prefer_active); else the newest case-insensitive match on runId / title /
    topic (runs are newest-first, so the first match is the most recent)."""
    if not runs:
        return None
    if arg:
        a = arg.strip().lower()
        for r in runs:  # exact id wins
            if a == (r.get("runId") or "").lower():
                return r
        for r in runs:  # else newest title/topic match
            if a in (r.get("title") or "").lower() or a in (r.get("topic") or "").lower():
                return r
        return None
    if prefer_active:
        for r in runs:
            if r.get("status") in ("queued", "ongoing"):
                return r
    return runs[0]


def _device_names() -> dict:
    """{deviceId: friendly name} from /devices (name → hostname → id). Empty on failure."""
    code, body = _get("/devices")
    if code != 200 or not isinstance(body, dict):
        return {}
    return {d.get("id"): (d.get("name") or d.get("hostname") or d.get("id"))
            for d in body.get("devices", [])}


def _dev_label(d: dict) -> str:
    return d.get("name") or d.get("hostname") or d.get("id") or "device"


def _resolve_device_arg(arg: str) -> tuple[dict | None, list[str]]:
    """A device NAME (or id) → the device dict. Exact id wins; else exact
    case-insensitive name/hostname; else a unique substring match. Returns
    (device, chat-lines-to-print-on-failure) — exactly one is set."""
    code, body = _get("/devices")
    if code != 200 or not isinstance(body, dict):
        return None, [f"✗ {body.get('error', code)}"]
    devices = body.get("devices", [])
    if not devices:
        return None, ["No devices connected yet — paste the access code from the computer "
                      "running Super Research and I’ll connect it.",
                      "", _INSTALL_PAGE_LINE]
    a = arg.strip().lower()
    for d in devices:
        if a == (d.get("id") or "").lower():
            return d, []
    exact = [d for d in devices
             if a == (d.get("name") or "").lower() or a == (d.get("hostname") or "").lower()]
    if len(exact) == 1:
        return exact[0], []
    sub = exact or [d for d in devices
                    if a in (d.get("name") or "").lower() or a in (d.get("hostname") or "").lower()]
    if len(sub) == 1:
        return sub[0], []
    if sub:
        names = ", ".join(f"“{_dev_label(d)}”" for d in sub)
        return None, [f"That matches more than one device ({names}) — tell me the full name."]
    return None, [f"No device matching “{arg}” — ask to see your devices."]


def _attention_lines(r: dict) -> list[str]:
    """Chat lines for a run that needs the user (C1). `r` is a run row (/updates)
    or a full research doc (/research/{id}); both may carry pendingDecision /
    attention / needsAttention."""
    pd = r.get("pendingDecision")
    text = r.get("attention")
    if not text and isinstance(pd, dict) and pd:
        text = pd.get("title") or pd.get("message") or pd.get("reason")
    if not text and not r.get("needsAttention"):
        return []
    lines = [f"  ⚠ Needs you: {text or 'a decision is needed'}"]
    kind = pd.get("kind") if isinstance(pd, dict) else None
    if kind == "login_required":
        lines.append("  → sign in on the device, then tell me to retry.")
    elif kind == "human_verification_required":
        lines.append("  → finish the check on the device, then tell me to retry.")
    else:
        lines.append("  → tell me to retry to resume, or skip to move past it (or open the app).")
    return lines


# ── per-chat streaming watchdog (arm-stream) ─────────────────────────────────

def _origin_from_env() -> dict | None:
    """The chat this skill subprocess was invoked from, from the gateway's
    per-session env (HERMES_SESSION_PLATFORM / _CHAT_ID / _THREAD_ID). The
    gateway bridges those contextvars into a FOREGROUND skill subprocess's env
    (tools/environments/local.py _make_run_env); a background / cron subprocess
    does NOT get them — which is exactly why the per-chat watchdog bakes its
    origin into a generated shim instead of reading the env. Returns {platform,
    chat_id[, thread_id]} only when both platform and chat are known, else None."""
    platform = (os.environ.get("HERMES_SESSION_PLATFORM") or "").strip()
    chat_id = (os.environ.get("HERMES_SESSION_CHAT_ID") or "").strip()
    thread_id = (os.environ.get("HERMES_SESSION_THREAD_ID") or "").strip()
    if not platform or not chat_id:
        return None
    out = {"platform": platform, "chat_id": chat_id}
    if thread_id:
        out["thread_id"] = thread_id
    return out


def _origin_slug(origin: dict) -> str:
    """A short, filesystem-safe id for a chat origin: a readable platform prefix
    plus a hash of the full (platform, chat, thread) tuple — so two chats never
    collide and odd chat-id characters (negative group ids, etc.) never reach a
    filename. MUST stay identical to sr_attention_poll._origin_slug so a shim
    (sr_poll_<slug>.py) and its de-dup state (.sr_poll_<slug>.state.json) pair up."""
    platform = re.sub(r"[^A-Za-z0-9]", "", (origin.get("platform") or "")).lower()[:16] or "chat"
    key = "\x00".join((origin.get("platform") or "", origin.get("chat_id") or "",
                       origin.get("thread_id") or ""))
    return f"{platform}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


def _scripts_dir() -> Path:
    """The HERMES_HOME/scripts dir where the watchdog + its shims live (the
    cronjob tool requires scripts there). Derived from this file's install
    location (<HERMES_HOME>/skills/research/sr/scripts/sr.py → <HERMES_HOME>/
    scripts) so a shim lands beside sr_attention_poll.py and can import it.

    The derivation is AUTHORITATIVE for the deployed Hermes layout REGARDLESS of
    whether the watchdog copy has landed yet: if it hasn't, _write_poll_shim then
    surfaces a clean "re-run agent connect" error — rather than this silently
    returning the skill BUNDLE's own scripts dir (which also holds a watchdog copy
    but is a path the cron tool rejects, masking the real failure with a confusing
    cron error). $HERMES_HOME and a local dir only cover a non-standard layout the
    derivation can't recognize."""
    here = Path(__file__).resolve()
    if len(here.parents) >= 5 and here.parents[1].name == "sr":
        return here.parents[4] / "scripts"  # deployed Hermes layout (authoritative)
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env) / "scripts"
    return here.parent  # unrecognized layout — best effort


# A tiny generated shim: the cron `no_agent` runner can't pass args or see the
# session env, so the chat origin is baked in here and the shared watchdog does
# the work. {origin!r} renders a plain Python dict literal (only safe str values).
_SHIM_TEMPLATE = '''#!/usr/bin/env python3
"""Per-chat Super Research streaming watchdog (auto-generated by `sr.py arm-stream`).

Bakes in one chat's origin so the gateway cron job — which can neither take args
nor read the session env — streams ONLY that chat's runs, then delegates to the
shared sr_attention_poll watchdog. Safe to delete; `agent disconnect` cleans it
up along with its .sr_poll_*.state.json de-dup file."""
import sr_attention_poll

ORIGIN = {origin!r}

if __name__ == "__main__":
    raise SystemExit(sr_attention_poll.main(origin=ORIGIN))
'''


def _write_poll_shim(scripts_dir: Path, name: str, origin: dict) -> str | None:
    """Write the per-chat shim next to sr_attention_poll.py. Returns an error
    message on failure (so arm-stream can relay it), else None on success."""
    try:
        scripts_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"couldn't reach the scripts dir ({type(e).__name__})"
    if not (scripts_dir / "sr_attention_poll.py").is_file():
        return "the watchdog script isn't installed — re-run `agent connect` on the host"
    try:
        (scripts_dir / name).write_text(_SHIM_TEMPLATE.format(origin=origin), encoding="utf-8")
    except OSError as e:
        return f"couldn't write the watchdog shim ({type(e).__name__})"
    return None


# ── deterministic watchdog arming ─────────────────────────────────────────────
# The watchdog cron USED to be armed by the chat AI acting on a `cronjob: create`
# directive this skill printed. That was the recurring failure: a non-deterministic
# LLM armed it inconsistently, so run progress + the 🎉 completion + the "✓ signed
# in" announce (all ride this one cron) silently never posted. But this skill runs
# as a FOREGROUND chat subprocess, so it knows the chat origin (_origin_from_env)
# AND can reach the runtime's cron store — it arms the job ITSELF by writing the row
# straight into <HERMES_HOME>/cron/jobs.json, the exact shape the runtime's own
# cronjob tool produces. Verified against the live Hermes engine: the scheduler
# re-reads jobs.json every tick (no in-memory registry), a hand-written no_agent +
# schedule row is picked up and fires, and deliver="origin" with a baked origin
# routes each tick's output to the arming chat. No LLM in the arming loop.


def _cron_jobs_file() -> Path:
    """<HERMES_HOME>/cron/jobs.json — the runtime's durable cron store, a sibling of
    the scripts dir where this skill's watchdog + shims live."""
    return _scripts_dir().parent / "cron" / "jobs.json"


def _cron_now() -> str:
    """An ISO timestamp for cron bookkeeping. Used as ``next_run_at`` so the job is
    due on the very next tick — NOT a time in the past, which the runtime would
    fast-forward (skip) once it falls outside the catch-up grace window."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _build_stream_cron_job(script_name: str, job_name: str, origin: dict | None,
                           schedule: dict) -> dict:
    """A well-formed Hermes cron-job row (mirrors cron.jobs.create_job's shape).
    ``deliver="origin"`` + the baked ``origin`` routes each tick's output to the
    chat that armed it (resolved at fire time from ``job["origin"]``); no origin →
    ``"local"`` (the caller only writes directly when an origin is present, so this
    branch stays correct). ``next_run_at`` ≈ now so it's due within the scheduler's
    grace window and fires on the very next tick; ``repeat.times=None`` = forever,
    so mark_job_run never auto-removes it."""
    now = _cron_now()
    return {
        "id": uuid.uuid4().hex[:12],   # REQUIRED — subscripted in Hermes' due-scan
        "name": job_name,
        "prompt": "",
        "skills": [],
        "skill": None,
        "model": None,
        "provider": None,
        "base_url": None,
        "script": script_name,
        "no_agent": True,              # the script IS the job — no LLM, no tokens
        "context_from": None,
        "schedule": schedule,
        "schedule_display": schedule.get("display", ""),
        "repeat": {"times": None, "completed": 0},
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
        "created_at": now,
        "next_run_at": now,
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
        "last_delivery_error": None,
        "deliver": "origin" if origin else "local",
        "origin": origin,
        "enabled_toolsets": None,
        "workdir": None,
    }


def _arm_stream_cron(script_name: str, job_name: str, origin: dict | None,
                     schedule: dict) -> bool:
    """Write the watchdog cron row into <HERMES_HOME>/cron/jobs.json deterministically
    — no dependence on the chat AI issuing cronjob:create. Idempotent BY NAME: a
    RUNNABLE job of this name is left untouched, and a disabled/paused one is revived
    in place rather than duplicated (create has no dedupe, so a blind re-append would
    accumulate duplicates → the runtime's later name lookups raise
    AmbiguousJobReference). Serialized against the gateway via the
    same advisory flock (<cron>/.jobs.lock) and written atomically (temp + replace),
    mirroring cron.jobs. Returns True when the job is present after the call (added
    or already there); False on any failure, so the caller can fall back to the AI
    directive."""
    jobs_file = _cron_jobs_file()
    cron_dir = jobs_file.parent
    lock_fd = None
    try:
        cron_dir.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = open(cron_dir / ".jobs.lock", "a+", encoding="utf-8")
        except OSError:
            lock_fd = None  # best-effort; proceed without the cross-process lock
        if lock_fd is not None and fcntl is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            except OSError:
                pass
        try:
            data = json.loads(jobs_file.read_text("utf-8"))
        except FileNotFoundError:
            data = {"jobs": []}
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            return False
        existing = next((j for j in data["jobs"]
                         if isinstance(j, dict) and j.get("name") == job_name), None)
        if existing is not None:
            # Present — but "present" only counts as ARMED if it can actually run. A
            # disabled/paused row is skipped by the runtime's due-scan before any
            # next-run recovery, so treating it as armed would leave the chat silent
            # with no way back (a re-arm would keep finding it). Revive it in place
            # instead of appending a duplicate (duplicates break name lookups).
            if existing.get("enabled", True) and existing.get("state") != "paused":
                return True  # genuinely armed — idempotent no-op
            existing.update({"enabled": True, "state": "scheduled", "paused_at": None,
                             "paused_reason": None,
                             "next_run_at": _cron_now()})  # due now, inside the grace window
        else:
            data["jobs"].append(_build_stream_cron_job(script_name, job_name, origin, schedule))
        # Per-process temp name. Several writers touch this file — this arming
        # path on every send, plus the watchdog's and update-notice teardowns —
        # and a single shared temp name lets two of them interleave write and
        # rename, so one publishes the other's half-written jobs list.
        tmp = jobs_file.with_suffix(".json.sr-tmp.%d" % os.getpid())
        tmp.write_text(json.dumps(data), "utf-8")
        try:
            os.chmod(tmp, 0o600)  # the cron store is owner-only; os.replace carries
        except OSError:           # the temp file's mode onto jobs.json
            pass
        os.replace(tmp, jobs_file)  # atomic; Hermes re-reads jobs.json each tick
        return True
    except OSError:
        return False
    finally:
        if lock_fd is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            lock_fd.close()


# INTERVAL, deliberately — not a cron expression. Both persist identically (the
# runtime stores whatever we write and re-reads it each tick), but a cron-expr
# schedule needs the runtime's OPTIONAL croniter dependency: without it, next-run
# computation returns None, so the job would fire ONCE and then go permanently
# silent — the exact failure this fix exists to eliminate, in an unrecoverable form
# (a re-arm is idempotent, so it would find the broken row and leave it). An
# interval schedule never touches croniter, so it ticks forever either way.
_STREAM_SCHEDULE = {"kind": "interval", "minutes": 1, "display": "every 1m"}
_UPDATE_NOTICE_SCHEDULE = {"kind": "interval", "minutes": 1440, "display": "every 1440m"}


# ── commands ────────────────────────────────────────────────────────────────

def cmd_login(args) -> int:
    payload = {"runtime": args.runtime or "", "label": args.label or ""}
    origin = _origin_from_env()
    if origin:
        payload["origin"] = origin
    code, body = _post("/login/remote/start", payload)
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't start sign-in: {body.get('error', code)}"], _fail_code(code))
    lines = [
        "Log in here:",
        f"  {body.get('verifyUrl')}",
        "Tap Authenticate when the page opens — you'll connect automatically.",
    ]
    # Arm THIS chat's watchdog so the moment the browser approval is captured the
    # bridge's "✓ signed in" lands here on its own — no need to poll for completion.
    arm_lines, _payload, arm_rc = _prepare_stream_arm()
    if arm_rc == 0 and arm_lines:
        lines += _agent_directive_block(arm_lines)
    return _emit(body, args.json, lines)


def cmd_login_wait(args) -> int:
    code, body = _post("/login/remote/poll")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    state = body.get("state")
    if state == "connected":
        who = body.get("email") or body.get("uid")
        topic = (body.get("pendingTopic") or "").strip()
        if topic:
            # The user asked to research this before signing in. Confirm + name the
            # topic; per SKILL.md "After a sign-in link" the assistant now runs
            # `research "<topic>"`, which starts it (or surfaces the pair-a-device
            # prompt if there's no device). Don't also print _connected_msg's
            # no-device prompt here — running the research handles that once.
            return _emit(body, args.json, [
                f"✓ Connected as {who}.",
                f"Continuing your research on “{topic}”…",
            ])
        return _emit(body, args.json, [_connected_msg(who)])
    msg = {
        "pending": "… not approved yet — approve it in your browser; you'll connect automatically.",
        "expired": "✗ The sign-in link expired — ask me to send a fresh sign-in link.",
        "error": f"✗ Sign-in failed: {body.get('error', 'unknown')}",
    }.get(state, f"state: {state}")
    return _emit(body, args.json, [msg])


def _update_notices(body: dict) -> list[str]:
    """Proactive "a newer SKILL version is available" prompt from a /status (or
    /version) body — so the user is nudged on the welcome without having to ask.
    Backend updates are NOT nudged here anymore: the app surfaces those and the
    user updates from the app / `superresearch --update` on the host (the skill no
    longer updates the backend)."""
    out = []
    if body.get("agentUpdate"):
        out.append(f"⬆️ Super Research skill v{body['agentUpdate']} is available — say “update”.")
    return out


def _has_device() -> bool:
    """Does the signed-in account have at least one usable device? A device is the
    prerequisite to run research. On a transient /devices error, assume YES so we
    never wrongly nag a paired user to pair again."""
    try:
        code, body = _get("/devices")
        if code == 200:
            return bool((body or {}).get("devices"))
    except Exception:
        pass
    return True


def _connected_msg(who) -> str:
    """Post-sign-in confirmation, device-aware: steer a deviceless account to connect
    one (research can't run without a device) instead of saying 'fire your research'.
    Natural language only — no command syntax (the user just talks to the assistant)."""
    if _has_device():
        return f"✓ Connected as {who} — you’re all set."
    return (f"✓ Connected as {who}. To get started, paste the access code from your "
            "Research Computer and I’ll connect it.")


def cmd_status_account(args) -> int:
    code, body = _get("/status")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if body.get("authed"):
        lines = [f"✓ Signed in as {body.get('email') or body.get('uid')}"]
        if not _has_device():
            lines.append("No device connected yet — paste the access code from your "
                         "Research Computer and I’ll connect it.")
            lines += ["", _INSTALL_PAGE_LINE]
    elif body.get("remoteLogin") == "pending":
        # A sign-in is mid-flight: approve it in the browser and the bridge
        # captures it automatically (no second command needed) — #848.
        lines = ["A sign-in is in progress — approve it in your browser; you'll connect automatically."]
    elif body.get("remoteLogin") in ("error", "expired"):
        lines = ["The last sign-in didn't complete — just ask me to log you in again."]
    else:
        lines = ["Not signed in — tell me to log you in and I'll send a link."]
    lines += _update_notices(body)
    return _emit(body, args.json, lines)


def cmd_devices(args) -> int:
    code, body = _get("/devices")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    devices = body.get("devices", [])
    selected = body.get("selectedDeviceId")
    if not devices:
        return _emit(body, args.json, [
            "No devices connected yet.",
            "Paste the access code from your Research Computer and I’ll connect it.",
            "",
            *_SETUP_NODE_LINES,
        ])
    lines = ["Devices:"]
    for d in devices:
        mark = "→" if d.get("selected") else " "
        kind = "owned" if d.get("owned") else "shared"
        lines.append(f"  {mark} {_dev_label(d)}  ({kind})")
    if not selected:
        lines.append("Tell me which one you’d like to use.")
    lines.append("You can add, remove, or switch devices anytime — just ask.")
    return _emit(body, args.json, lines)


def cmd_device_use(args) -> int:
    dev, fail = _resolve_device_arg(args.device)
    if dev is None:
        return _emit({}, args.json, fail, 1)
    code, body = _post("/device/select", {"deviceId": dev.get("id")})
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't select device: {body.get('error', code)}"], _fail_code(code))
    d = body.get("device", {})
    kind = "owned" if d.get("owned") else "shared"
    return _emit(body, args.json, [f"✓ Now running on {_dev_label(d)} ({kind})."])


# Friendly wording for the web app's claim/unpair error codes.
_PAIR_ERRORS = {
    "invalid_code_format": "Pair codes are 8 letters/digits (like K7XQ-9B2M) — check the device's screen.",
    "code_not_found": "That code didn’t match any device — re-check it on the device’s screen.",
    "code_expired": "That code expired — reset the pair code on the device and try the fresh one.",
    "not_previous_owner": "That device is waiting for its previous owner to re-pair — only they can.",
    "revoked_sharer": "The owner removed your access to that device — ask them to share it again.",
    "share_cap_reached": "That device has reached its sharer limit.",
    "rate_limited": "Too many attempts — wait a few minutes and try again.",
}


def cmd_device_add(args) -> int:
    """Pair a device to this account by the code shown on its screen."""
    code, body = _post("/device/pair", {"code": args.code})
    if code != 200:
        err = body.get("error", "")
        msg = _PAIR_ERRORS.get(err, f"couldn’t add the device: {err or code}")
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    action = body.get("action")
    name = body.get("deviceName") or "the new device"
    if action in ("already-owner", "already-shared"):
        return _emit(body, args.json, [f"“{name}” is already on your account."])
    kind = "yours" if action in ("initial-pair", "re-pair") else "shared with you"
    if body.get("selected"):
        lines = [f"✓ Added “{name}” — it’s {kind} and selected."]
        lines.append("You can start researching whenever you like.")
    else:
        lines = [f"✓ Added “{name}” — it’s {kind} now."]
    lines.append("You can add, remove, or switch devices anytime — just ask.")
    return _emit(body, args.json, lines)


def cmd_device_remove(args) -> int:
    """Unlink a device (owner: device stays installed + re-pairable; sharer: leaves it)."""
    dev, fail = _resolve_device_arg(args.device)
    if dev is None:
        return _emit({}, args.json, fail, 1)
    code, body = _post("/device/remove", {"deviceId": dev.get("id")})
    if code != 200:
        err = body.get("error", "")
        msg = _PAIR_ERRORS.get(err, f"couldn’t remove the device: {err or code}")
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    label = _dev_label(dev)
    if body.get("action") == "left-shared":
        return _emit(body, args.json, [f"✓ Left the shared device “{label}”."])
    return _emit(body, args.json, [
        f"✓ Unlinked “{label}” from your account.",
        "(Nothing was deleted — the device keeps running and can be re-paired with its code.)",
    ])


def _pick_device_lines(body: dict, reason: str) -> list[str]:
    """Chat lines for the 'which computer should run this?' ask — the account HAS
    research computers, it just needs to be told which (a multi-device account with
    no single online default). Renders the device list the bridge attached to the
    error; falls back to a /devices fetch for an older bridge that didn't. The user
    replies "use <name>" (→ device-use, which persists the choice)."""
    devices = body.get("devices")
    if not isinstance(devices, list) or not devices:
        code, b2 = _get("/devices")
        devices = b2.get("devices", []) if (code == 200 and isinstance(b2, dict)) else []
    devices = [d for d in devices if isinstance(d, dict) and (d.get("name") or d.get("hostname") or d.get("id"))]
    if not devices:
        # No reachable devices after all → the pair/install step (older bridge path).
        return ["Paste the access code from your Research Computer first.", "", *_SETUP_NODE_LINES]
    if reason == "stale_selection":
        lead = "The computer you last used isn’t reachable anymore — pick another:"
    else:
        lead = f"You have {len(devices)} research computers — which should run this?"
    lines = [lead]
    for d in devices:
        online = d.get("online")
        dot = " · online" if online is True else (" · offline" if online is False else "")
        lines.append(f"  • {_dev_label(d)}{dot}")
    lines.append(f'Just say: use “{_dev_label(devices[0])}”.')
    return lines


def cmd_research(args) -> int:
    payload: dict = {"topic": args.topic}
    if args.device:
        payload["deviceId"] = args.device
    # Tag the run with the chat it was fired from, so a per-chat watchdog can
    # scope its updates to this chat only (Telegram→Telegram, WhatsApp→WhatsApp).
    origin = _origin_from_env()
    if origin:
        payload["origin"] = origin
    cfg = {}
    if args.no_video:
        cfg["videoEnabled"] = False
    if args.no_email:
        cfg["emailEnabled"] = False
    if cfg:
        payload["config"] = cfg
    code, body = _post("/research", payload)
    if code != 200:
        # Not signed in (401): give an ACTIONABLE next step, not a dead end. A
        # prior login link expires (~10 min), so steering back to "the link I
        # sent" strands the user — point at a FRESH `login` instead. If a sign-in
        # is already mid-flight, say so (the bridge auto-captures on approval —
        # #848, no `login-done` needed).
        if code == 401:
            # Remember the topic + this chat so that, once the user signs in, the
            # watchdog can offer to continue THIS research (confirm-first, never a
            # silent auto-start). Arm the watchdog so the "✓ signed in — continue
            # with '…'?" lands here on its own.
            stash = {"pending_topic": args.topic}
            if origin:
                stash["origin"] = origin
            arm_lines, _ap, arm_rc = _prepare_stream_arm()
            sc, sbody = _get("/status")
            if sc == 200 and sbody.get("remoteLogin") == "pending":
                # A sign-in is already in flight — attach the topic to it (don't mint
                # a fresh flow, which would void the link they're about to approve).
                _post("/login/remote/pending", stash)
                lines = ["You're almost signed in — finish in your browser and I'll pick this up."]
                if arm_rc == 0 and arm_lines:
                    lines += _agent_directive_block(arm_lines)
                return _emit(body, args.json, lines, _fail_code(code))
            # No flow yet: start one carrying the topic, hand back the click-to-approve
            # link, and the bridge captures it automatically on approval (#848).
            lc, lbody = _post("/login/remote/start", stash)
            link = lbody.get("verifyUrl") if lc == 200 else None
            if link:
                lines = [
                    "You're not signed in yet. Log in here and I'll pick this up:",
                    f"  {link}",
                ]
                if arm_rc == 0 and arm_lines:
                    lines += _agent_directive_block(arm_lines)
                return _emit({**body, "verifyUrl": link}, args.json, lines, _fail_code(code))
            return _emit(body, args.json, [
                "You're not signed in yet — tell me to log you in and I'll send a link.",
            ], _fail_code(code))
        # Signed in but the run couldn't be routed to a device. Tell the two cases
        # apart by the bridge's machine-readable `reason` (NOT an English substring —
        # "no device selected" and "no devices yet" both contain "no device", so the
        # old substring test mis-sent a MULTI-device account to the "install a backend
        # here" prompt). no_devices → pair/install one; no_selection/stale_selection →
        # the account HAS computers, ask which. Older bridge (no reason): infer from text.
        err = str(body.get("error", "")).lower()
        reason = body.get("reason")
        if not reason:
            reason = ("no_devices" if ("no devices yet" in err or "grab the pair code" in err)
                      else ("no_selection" if "no device" in err else ""))
        if reason == "no_devices":
            return _emit(body, args.json, [
                "Paste the access code from your Research Computer first.",
                "",
                *_SETUP_NODE_LINES,
            ], _fail_code(code))
        if reason in ("no_selection", "stale_selection"):
            return _emit(body, args.json, _pick_device_lines(body, reason), _fail_code(code))
        return _emit(body, args.json, [f"✗ couldn't start: {body.get('error', code)}"], _fail_code(code))
    dev = _device_names().get(body.get("deviceId") or "", body.get("deviceId") or "")
    where = f" on {dev}" if dev else ""
    lines = [
        f"🚀 Started “{args.topic}”{where}.",
        "I’ll post here when it’s done — and if it ever needs you. Ask how it’s going anytime.",
    ]
    # Auto-arm THIS chat's run-scoped streaming watchdog so progress posts without
    # the user asking — _prepare_stream_arm writes the cron row into jobs.json itself
    # (idempotent), so nothing needs the AI here; arm_lines is empty on success and
    # only carries a fallback directive if the direct write couldn't run. On a prep
    # error, skip silently: the run is fine and `status` still works.
    arm_lines, _payload, arm_rc = _prepare_stream_arm()
    if arm_rc == 0 and arm_lines:
        lines += _agent_directive_block(arm_lines)
    return _emit(body, args.json, lines)


def cmd_status(args) -> int:
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    run = _pick_run(runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "yet"
        return _emit(body, args.json, [f"No runs {which}."])
    rid = run.get("runId")
    code, b2 = _get(f"/research/{urllib.parse.quote(rid, safe='')}")
    if code != 200:
        return _emit(b2, args.json, [f"✗ {b2.get('error', code)}"], _fail_code(code))
    r = b2.get("research", {})
    title = r.get("title") or r.get("topic") or rid
    dev = _device_names().get(r.get("deviceId") or "", "")
    where = f"  ·  {dev}" if dev else ""
    # A queued run has no phase yet (the BE stamps it at start) — show the
    # place in line instead of a confusing "queued (phase ?)".
    if r.get("status") == "queued":
        qp = r.get("queuePosition")
        stat = f"queued — #{qp} in line" if qp else "queued — waiting for a free worker"
    else:
        stat = f"{r.get('status', '?')} (phase {r.get('phase', '?')})"
    lines = [f"“{title}” — {stat}{where}"]
    lines += _fmt_pipeline_config(r.get("pipelineConfig"))
    lines += _attention_lines(r)
    # Per-phase plan = the curated links (🔒 SR for Brief/reports/Podcast, 🔗 platform
    # for NotebookLM/YouTube/Doc). If the bridge supplied none yet (no phase done, or
    # an older build), fall back to the minted permanent SR links — never the raw,
    # tokenized Storage audio URL.
    phase_updates = b2.get("phaseUpdates")
    if phase_updates:
        lines += _fmt_phase_updates(phase_updates)
    else:
        lines += _fmt_sr_links(b2.get("srLinks") or {})
    # Watchdog self-heal: if an agent run is live but this chat's watchdog
    # isn't ticking, re-emit the arming directive (see _stream_health_lines).
    lines += _stream_health_lines(runs)
    return _emit(b2, args.json, lines)


def cmd_podcast(args) -> int:
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if args.runId:
        run = _pick_run(runs, args.runId)
    else:
        # The podcast audio is a late-phase artifact — prefer the newest run that
        # already HAS audio over the newest active run (which usually has none yet).
        with_audio = [r for r in runs
                      if any(lk.get("kind") == "audio_file" for lk in r.get("links", []))]
        run = with_audio[0] if with_audio else (runs[0] if runs else None)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "yet"
        return _emit(body, args.json, [f"No runs {which}."])
    rid = run.get("runId")
    # The bridge downloads the audio to a local file (a long audio overview can
    # take a few seconds) → allow more time than the default request timeout.
    # Tell the bridge which chat this is headed to: upload ceilings are the
    # PLATFORM's and differ by an order of magnitude (Telegram 50 MB vs WhatsApp
    # ~16 MB), so a file that is fine here is refused there.
    origin = _origin_from_env() or {}
    platform = (origin.get("platform") or "").strip()
    q = f"?platform={urllib.parse.quote(platform, safe='')}" if platform else ""
    code, b2 = _get(f"/research/{urllib.parse.quote(rid, safe='')}/podcast{q}", timeout=180)
    if code != 200:
        return _emit(b2, args.json, [f"✗ {b2.get('error', code)}"], _fail_code(code))
    title = b2.get("title") or "Podcast"
    if b2.get("tooLarge"):
        # Past the chat platform's upload ceiling even after re-encoding. Sending a
        # path here would be worse than useless: the platform refuses the upload and
        # the runtime degrades to printing the path as text (live 2026-07-26 — an
        # 89-minute overview came back as a dead file path). Hand over the permanent
        # link instead, which plays in the browser and never expires.
        share = b2.get("shareUrl") or ""
        lines = [f"🎧 {title}"]
        if share:
            lines += ["It's too long to send as a file here — listen at:", f"  {share}"]
        else:
            lines.append("It's too long to send as a file here — ask for the links "
                         "and I'll get you the podcast link.")
        return _emit(b2, args.json, lines)
    # Emit a short caption + an explicit MEDIA:<path> tag on its own line. The
    # runtime's gateway extracts MEDIA: tags into its AUDIO partition, which
    # delivers the file as native PLAYABLE audio (Telegram sendAudio for
    # mp3/m4a; other platforms' voice/audio sender) and strips the tag from
    # the visible text — so the user sees the title + an inline player. A BARE
    # path is NOT equivalent: bare paths route to document delivery (a "📎
    # File" attachment, not playable — the 2026-07-02 live failure). Do NOT
    # add [[audio_as_voice]]: it suppresses the text body (voice-reply dedup)
    # and only matters for .ogg/.opus voice bubbles.
    # The MEDIA contract keeps breaking on AI paraphrase (live 2026-07-06: the
    # assistant rewrote the MEDIA: line to "🔊 Audio: <path>", which routes to
    # document delivery instead of the native player, and the user had to ask
    # "make it playable" a second time). Ship the instruction WITH the output
    # under the do-not-relay marker so it's in front of the model at the exact
    # moment it relays — not buried in SKILL.md's per-command notes.
    return _emit(b2, args.json, [
        f"🎧 {title}",
        f"MEDIA:{b2.get('localPath')}",
        *_agent_directive_block([
            "Reply with the TWO lines above EXACTLY as printed — the MEDIA: line",
            "verbatim on its own line. Do NOT decorate, relabel, or rewrite it",
            "(no emoji prefix, no speaker/label word before the path, no code",
            "block, no bare path): the gateway converts the exact MEDIA: line",
            "into a native playable audio message in this chat; any rewrite",
            "turns it into a non-playable file path.",
        ]),
    ])


def cmd_updates(args) -> int:
    # via_agent → agent-only runs + per-phase SR-link minting (same clean links
    # the streaming watchdog posts).
    code, body, runs = _fetch_runs(active=args.active, via_agent=True)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    lines = []
    for r in runs:
        # A queued run has no phase yet — show its place in line (mirrors status).
        if r.get("status") == "queued":
            _qp = r.get("queuePosition")
            _stat = f"queued — #{_qp} in line" if _qp else "queued — waiting for a free worker"
        else:
            _stat = f"{r.get('status')} (phase {r.get('phase')})"
        lines.append(f"“{r.get('title') or r.get('topic')}” — {_stat}")
        lines += _fmt_pipeline_config(r.get("pipelineConfig"))
        lines += _attention_lines(r)
        phase_updates = r.get("phaseUpdates")
        if phase_updates:
            lines += _fmt_phase_updates(phase_updates)
        else:
            # Fallback (older build / no phaseUpdates): the minted permanent SR links.
            lines += _fmt_sr_links(r.get("srLinks") or {})
    # Watchdog self-heal: re-emit the arming directive when a live agent run
    # has no ticking watchdog in this chat (see _stream_health_lines).
    return _emit(body, args.json, (lines or ["No active runs."]) + _stream_health_lines(runs))


# ── send logs ────────────────────────────────────────────────────────────────
#
# ⛔⛔ THIS IS A CONFIRM-FIRST VERB AND THE REASON IS NOT POLITENESS. The
# research computer refuses a request that does not carry recorded consent, and
# that flag is a claim that a person was SHOWN what leaves their machine. In the
# app a modal makes the claim true. Here the FIRST call prints what would be
# sent and sends nothing; only `--confirm` puts the flag on the wire. A single
# call that showed the person nothing and claimed consent anyway would be
# forging the one thing the machine cannot check for itself.
#
# ⭐ A SECOND COPY OF THE CLI'S SENTENCES, AND THE DUPLICATION IS FORCED. This
# script is stdlib-only by contract — it runs inside somebody else's chat
# runtime and may not import `facade` — so it cannot share the table.
# `test_send_logs_cli_0825.py` reads both files and fails if either grows a case
# the other lacks.
_SEND_LOGS_FAILURES = {
    "CooldownActive": "that computer built a bundle very recently — give it "
                      "ten minutes and ask again",
    "AlreadyBuilding": "that computer is already packaging a bundle — wait for "
                       "it to finish and ask again",
    "NotDeviceMember": "that computer no longer counts you as one of its "
                       "people, so it will not package anything for you",
    "NotDeviceOwner": "only the person who owns that computer can ask for its "
                      "own logs",
    "NothingSelected": "nothing was chosen to send",
    "ConsentMissing": "that computer was not told the request had been agreed "
                      "to — this is a bug on our side, please report it",
    "RunsInvalid": "that computer could not read the selection — this is a bug "
                   "on our side, please report it",
    "SubmitterMissing": "that computer could not tell who was asking — this is "
                        "a bug on our side, please report it",
    "DeviceReadFailed": "that computer could not look itself up, which usually "
                        "means it has lost its connection",
    "UploadFailed": "the bundle was built but could not be uploaded — it is "
                    "still on that computer, and running “superresearch "
                    "--doctor” there prints where",
}

_SEND_LOGS_UNKNOWN = ("that computer refused the request and gave a reason we "
                      "do not have a sentence for")


def _send_logs_failure(error_class: str) -> str:
    """A refusal in words a person can act on. ⛔ Never empty and never the bare
    class name — an error nobody can read is the same as no error at all."""
    known = _SEND_LOGS_FAILURES.get(str(error_class or ""))
    if known:
        return known
    return f"{_SEND_LOGS_UNKNOWN} ({error_class})" if error_class else _SEND_LOGS_UNKNOWN


def _size_words(n) -> str:
    try:
        size = float(n or 0)
    except (TypeError, ValueError):
        return "unknown size"
    for unit, step in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if size >= step:
            return f"{size / step:.1f} {unit}"
    return f"{int(size)} bytes"


def _log_run_label(row: dict) -> str:
    """⭐ The title if this account still holds one, otherwise the date. A run
    whose research is gone from the app keeps its row — those logs are still on
    that disk, and are often exactly the ones worth sending."""
    title = (row.get("title") or "").strip()
    if title:
        return title
    started = (row.get("startedUtc") or "").strip()
    return f"a run from {started[:10]}" if started else "an unnamed run"


def cmd_send_logs(args) -> int:
    """Ask the research computer to package its logs for support.

    Two steps by design — see the block comment above. Without ``--confirm``
    this prints what would be sent and sends nothing.
    """
    if args.status:
        want = str(args.status).strip().upper()
        code, body = _get(f"/logs/bundle?code={want}")
        if code != 200:
            return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
        row = body.get("row")
        if not row:
            return _emit(body, args.json, [
                f"Nothing has come back for {want} yet. That computer may still "
                "be packaging it, or may not have picked the request up."])
        status = str(row.get("status") or "")
        if status == "failed":
            return _emit(body, args.json,
                         [f"✗ {want} didn’t send: {_send_logs_failure(row.get('errorClass'))}."], 1)
        if status == "done":
            return _emit(body, args.json, [
                f"✓ {want} was sent — {int(row.get('runCount') or 0)} run(s), "
                f"{_size_words(row.get('sizeBytes'))}.",
                f"Quote {want} when you report the problem."])
        return _emit(body, args.json, [f"{want} is still being packaged."])

    path = "/logs/runs"
    device_arg = getattr(args, "device", "") or ""
    if device_arg:
        dev, fail = _resolve_device_arg(device_arg)
        if dev is None:
            return _emit({}, args.json, fail, 1)
        path += f"?deviceId={dev.get('id')}"
    code, body = _get(path)
    if code != 200:
        if body.get("reason") in ("no_selection", "stale_selection", "no_devices"):
            return _emit(body, args.json,
                         _pick_device_lines(body, body.get("reason", "")), _fail_code(code))
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))

    rows = body.get("runs") or []
    # ⛔⛔ THE MACHINE THE LIST CAME FROM, CARRIED ONTO THE SEND. Showing and
    # sending are two separate calls, and with no deviceId the bridge picks the
    # selected machine each time — so a selection that changes in between would
    # show one computer's runs and send from another. The person agreed to what
    # they were shown.
    device_id = str(body.get("deviceId") or "")
    name = body.get("deviceName") or "your Research Computer"
    owned = bool(body.get("owned"))
    machine = bool(getattr(args, "machine", False))

    if machine and not owned:
        # Said here rather than after a round trip. The computer would refuse
        # this anyway; what this decides is whether the person is TOLD, and on
        # a shared computer that is the ordinary case rather than the odd one.
        return _emit(body, args.json, [
            f"“{name}”’s own logs belong to whoever owns it, so I can’t include "
            "them. Ask again without them and you’ll still get every run of "
            "yours it’s holding."], 1)

    names = [r.get("name") for r in rows]
    if getattr(args, "none", False):
        names = []
    if not names and not machine:
        if not body.get("published"):
            # ⛔⛔ NOT "it isn't holding any of your runs". The list is absent,
            # which means we cannot see it — a computer that hasn't published
            # one yet, or one on an older build. The other sentence tells
            # somebody their logs are gone while that machine may hold them all.
            return _emit(body, args.json, [
                f"“{name}” hasn’t told me which runs it’s still holding, so I "
                "can’t offer you a list yet."] + ([
                    "If you own it, I can still send the computer’s own logs — "
                    "that’s the right choice when the problem is with connecting "
                    "it at all."] if owned else []), 1)
        return _emit(body, args.json, [
            f"“{name}” isn’t holding logs for any of your runs."] + ([
                "If the problem is with connecting it at all, I can send the "
                "computer’s own logs instead — just ask."] if owned else []), 1)

    total = sum(int(r.get("sizeBytes") or 0) for r in rows if r.get("name") in names)

    if not getattr(args, "confirm", False):
        lines = [f"I can send Super Research support the logs from “{name}”:"]
        for row in rows:
            if row.get("name") in names:
                lines.append(f"  • {_log_run_label(row)} — "
                             f"{_size_words(row.get('sizeBytes'))}")
        if body.get("truncated"):
            lines.append("  (only the most recent are listed — it’s holding more)")
        if machine:
            lines.append("Plus that computer’s own logs: its pairing and sign-in "
                         "records and its raw activity trail, which cover every "
                         "run it has ever done, for everyone who uses it.")
        else:
            lines.append("That computer’s own logs are not included.")
        # ⛔⛔ NO "kept for 30 days" HERE EITHER. The web app refuses that
        # sentence for a measured reason (`sendLogsCopy.ts`, twice): no bucket
        # lifecycle rule exists, so it is a promise nothing keeps. It arrives
        # with the rule — wave 8M.
        lines.append(f"That’s {len(names)} run(s), about {_size_words(total)}. "
                     "Only Super Research support can read them.")
        lines.append("Say yes and I’ll send them.")
        return _emit({**body, "wouldSend": names, "includeMachine": machine},
                     args.json, lines)

    payload = {"runNames": names, "includeMachine": machine,
               # ⛔ Set on this branch ONLY. It claims the person was shown what
               # leaves their computer, and the branch above is where that
               # happened. Moving it up would make the claim false.
               "consent": True,
               # Always the machine the list came from — see above.
               "deviceId": device_id}
    code, sent = _post("/logs/send", payload)
    if code != 200:
        return _emit(sent, args.json,
                     [f"✗ couldn’t send the logs: {sent.get('error', code)}"], _fail_code(code))
    support = sent.get("code", "")
    return _emit(sent, args.json, [
        f"✓ Asked “{name}” for the logs. Your support code is {support}.",
        "It takes a moment to package. Ask me to check on it and I’ll look.",
        *_agent_directive_block([
            f"To check on it later, run: sr send-logs --status {support}",
            "Do not poll on a timer — only when the user asks.",
        ]),
    ])


def cmd_list(args) -> int:
    """List the account's recent researches (newest first), so the user can ask for
    any one's links or podcast BY NAME. Account-wide — EVERY research, not just the
    agent-started ones (that's `updates`, the active-only streaming view). The
    per-run links/podcast are then fetched on demand via `status` / `podcast`,
    which already resolve any of these by title."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if not runs:
        return _emit(body, args.json,
                     ["You don't have any researches yet — just name a topic to start one."])
    lines = ["Your researches (newest first):"]
    for r in runs:
        title = r.get("title") or r.get("topic") or r.get("runId")
        lines.append(f"  • “{title}” — {r.get('status', '?')}")
    lines.append("Ask for any one’s results, a specific link (brief / a report / podcast), or its podcast.")
    return _emit(body, args.json, lines)


def cmd_stop(args) -> int:
    """Graceful stop (the chat /sr stop) — keeps the results so far + the chat."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    run = _pick_run(runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "to stop"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    code, b2 = _post(f"/research/{urllib.parse.quote(rid, safe='')}/stop")
    if code != 200:
        return _emit(b2, args.json, [f"✗ stop failed: {b2.get('error', code)}"], _fail_code(code))
    if b2.get("alreadyDone"):
        return _emit(b2, args.json, [f"“{title}” already finished ({b2.get('status')}) — nothing to stop."])
    return _emit(b2, args.json, [
        f"✓ Stopped “{title}”.",
        "Your results so far are kept.",
    ])


def cmd_pause(args) -> int:
    """Pause a running run — it stays RESUMABLE (unlike stop, which ends it)."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    run = _pick_run(runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "to pause"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    code, b2 = _post(f"/research/{urllib.parse.quote(rid, safe='')}/pause")
    if code != 200:
        return _emit(b2, args.json, [f"✗ couldn't pause: {b2.get('error', code)}"], _fail_code(code))
    return _emit(b2, args.json, [
        f"⏸ Paused “{title}”.",
        "Tell me to resume it whenever you’re ready.",
    ])


def cmd_resume(args) -> int:
    """Resume a paused run."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    # Prefer a PAUSED run (that's what resume targets) before the generic newest pick,
    # so a bare "resume" doesn't grab a newer ongoing/terminal run.
    paused = [r for r in runs if (r.get("status") or "") == "paused"]
    run = _pick_run(paused or runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "to resume"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    code, b2 = _post(f"/research/{urllib.parse.quote(rid, safe='')}/resume")
    if code != 200:
        return _emit(b2, args.json, [f"✗ couldn't resume: {b2.get('error', code)}"], _fail_code(code))
    return _emit(b2, args.json, [f"▶ Resumed “{title}”."])


def cmd_retry(args) -> int:
    """Resume a run that's waiting on a decision / hit an error (C1)."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    run = _pick_run(runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "to retry"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    code, b2 = _post(f"/research/{urllib.parse.quote(rid, safe='')}/resolve", {"intent": "retry"})
    if code != 200:
        return _emit(b2, args.json, [f"✗ couldn’t retry “{title}”: {b2.get('error', code)}"], _fail_code(code))
    return _emit(b2, args.json, [f"↻ Retrying “{title}” — resuming the run."])


_SKIP_NAMES = {"brief": 1, "podcast": 3, "audio": 3, "video": 4, "youtube": 4, "report": 5, "email": 5}

# P2 agents skippable BY NAME — parity with the web app's per-agent Research
# toggles ("skip Claude in P2" was un-doable from chat, live 2026-07-02).
_SKIP_AGENTS = {"chatgpt": "chatgpt", "gpt": "chatgpt", "openai": "chatgpt",
                "claude": "claude", "anthropic": "claude", "gemini": "gemini"}
_AGENT_DISPLAY = {"chatgpt": "ChatGPT", "gemini": "Gemini", "claude": "Claude"}


def cmd_skip(args) -> int:
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    run = _pick_run(runs, args.run or None, prefer_active=True)
    if run is None:
        which = f"matching “{args.run}”" if args.run else "to skip in"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    q = urllib.parse.quote(rid, safe="")
    if not args.phases:
        # No phases → skip whatever the run is BLOCKED on (resolve the decision).
        code, b2 = _post(f"/research/{q}/resolve", {"intent": "skip"})
        if code != 200:
            return _emit(b2, args.json,
                         [f"✗ couldn’t skip the blocker on “{title}”: {b2.get('error', code)}"],
                         _fail_code(code))
        return _emit(b2, args.json, [f"⏭ Skipping the current blocker on “{title}”."])
    # Phases and/or P2 agents given → tune the run's config (skip whole phases
    # when reached; turn named agents off — the app's per-agent toggle write).
    phases = []
    agents = []
    for p in args.phases:
        lp = p.lower()
        if p.isdigit():
            phases.append(int(p))
        elif lp in _SKIP_NAMES:
            phases.append(_SKIP_NAMES[lp])
        elif lp in _SKIP_AGENTS:
            agents.append(_SKIP_AGENTS[lp])
        else:
            return _emit({}, args.json,
                         [f"✗ unknown phase '{p}' (1/3/4/5, brief/podcast/video/report, "
                          f"or a Research agent: chatgpt/gemini/claude)"], 1)
    payload: dict = {}
    if phases:
        payload["phases"] = phases
    if agents:
        payload["agents"] = sorted(set(agents))
    code, b2 = _post(f"/research/{q}/skip", payload)
    if code != 200:
        return _emit(b2, args.json, [f"✗ skip failed: {b2.get('error', code)}"], _fail_code(code))
    parts = []
    if b2.get("skipped"):
        parts.append(f"phase(s) {b2.get('skipped')}")
    if b2.get("agentsOff"):
        parts.append(" + ".join(_AGENT_DISPLAY.get(a, a) for a in b2["agentsOff"])
                     + " in Research (P2)")
    what = " and ".join(parts) or "that"
    # commandSent = the run is ongoing and the mid-run config command landed —
    # the change applies NOW, not just at the next phase boundary.
    tail = " — applied to the running pipeline too." if b2.get("commandSent") else " when reached."
    return _emit(b2, args.json, [f"✓ Will skip {what} of “{title}”{tail}"])


def cmd_logout(args) -> int:
    # Capture WHO we're logging out first (the /logout response only returns ok),
    # so we can name the account in the confirmation.
    who = ""
    try:
        sc, sb = _get("/status")
        if sc == 200 and sb.get("authed"):
            who = sb.get("email") or sb.get("uid") or ""
    except Exception:
        pass
    code, body = _post("/logout")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    msg = f"✓ Logged out of {who}." if who else "✓ Logged out — account session cleared."
    return _emit(body, args.json, [msg])


def cmd_version(args) -> int:
    """Show the Super Research skill's version (+ a "newer available" nudge for
    the SKILL when one is published). SKILL-ONLY (2026-07-06, user): the backend
    line ("Backend: not installed on the connected device" — the runtime host,
    not the Research computer) only confused; the backend's version lives in the
    app's Settings → About and `superresearch --version` on the Research
    computer."""
    # Explicit ask ⇒ FRESH PyPI read (2026-07-06, user: "any update found?"
    # right after a publish must see it — a stale 24h-cached "no" is a lie).
    code, body = _get("/version?fresh=1")
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't read versions: {body.get('error', code)}"],
                     _fail_code(code))
    agent = body.get("agent") or "?"
    a_new = body.get("agentLatest")
    lines = [f"Super Research skill  v{agent}"
             + (f"   ⬆️ v{a_new} available — say “update”" if a_new else "")]
    # Stale chat-side copy tell: the runtime executes its own installed COPY of
    # these scripts, which only `connect` / “update” redeploys — a host pip
    # upgrade alone leaves the chat side on old behavior (live 2026-07-02: a
    # stale copy predated the podcast MEDIA: fix). Name it.
    if agent not in ("?", _SKILL_BUILD):
        lines.append(f"⚠ This chat's scripts are v{_SKILL_BUILD} but the skill is v{agent} — "
                     "say “update” to redeploy them.")
    return _emit(body, args.json, lines)


def cmd_update(args) -> int:
    """Update the Super Research SKILL — this chat runtime (its /sr scripts +
    bridge) — to the latest published version (the bridge reconnects from the
    latest in the background). The skill is the ONLY thing this updates; backend
    updates are done in the app / with `superresearch --update` on the host."""
    code, body = _post("/agent-install")
    if code != 200:
        err = body.get("error", "")
        if err == "agent_unavailable":
            msg = ("can't reach the latest skill right now — the device may be offline, "
                   "or this version isn't published yet. (Nothing changed; the skill is still running.)")
        elif err == "update_helper_failed":
            msg = "couldn't start the update (is pipx available on the connected device?)"
        else:
            msg = f"couldn't start the update: {err or code}"
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    if body.get("already"):
        cur = body.get("current") or ""
        return _emit(body, args.json,
                     [f"✓ The skill is already up to date{(' (v' + cur + ')') if cur else ''}."])
    # Seamless finish: the bridge restarts on the new version in the background;
    # hand the assistant a DETERMINISTIC verify→reload→confirm script so it doesn't
    # improvise multi-step recovery (the reported friction) and the user gets ONE
    # clean confirmation. The reload step runs the runtime's OWN skill-reload (Hermes
    # /reload-skills) — the one thing the skill can't self-trigger — so it cooperates
    # with the runtime instead of fighting it.
    finish = [
        "The Super Research update is now running: a detached helper is upgrading the "
        "package and restarting the bridge on the new version. Finish it cleanly, in "
        "THIS order — act SILENTLY, do not narrate these steps:",
        "1. Wait ~30 seconds for the new bridge to come up (the package upgrade can "
        "briefly leave the bridge unreachable — that's expected).",
        "2. Run the Super Research `version` command. If it errors (bridge still "
        "restarting / unreachable) or still reports the OLD version, wait ~15s and "
        "retry — up to 6 times (~90s total) before giving up.",
        "3. Once `version` reports the NEW version, run your runtime's skill-reload "
        "command ONCE (Hermes: /reload-skills) so the refreshed /sr scripts are picked "
        "up. Skip this if your runtime has no reload command. NOTE: before the reload, "
        "`version` may warn that “this chat's scripts are older” — that is EXPECTED and "
        "the reload fixes it; do NOT run “update” again (no update loop).",
        "4. Then post ONE line to the user: “✓ Super Research updated to v<version> and "
        "reloaded.” If after the retries it still shows the old version, tell the user "
        "the update didn’t take and to say “update” again.",
    ]
    return _emit(body, args.json,
                 ["⬆️ Updating Super Research to the latest version — the bridge restarts on "
                  "the new version in a few seconds. I’ll confirm here once it’s live."]
                 + _agent_directive_block(finish))


def cmd_install(args) -> int:
    """Install the Super Research BACKEND on the connected device — turns that PC
    into a research host (`pipx install superresearch`). The install runs in the
    background; pairing afterwards is done on the host."""
    code, body = _post("/install-backend")
    if code != 200:
        err = body.get("error", "")
        if err == "install_helper_failed":
            msg = "couldn't start the install (is pipx available on the connected device?)"
        else:
            msg = f"couldn't start the install: {err or code}"
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    if body.get("already"):
        return _emit(body, args.json, [
            "Super Research is already installed on this device.",
            "To update it, run “superresearch --update” on that computer or update "
            "it from the app (Settings → About); say “devices” to see/pair it.",
        ])
    return _emit(body, args.json, [
        "⬇️ Installing Super Research on this device in the background.",
        "When it finishes, pair it — run this on that PC:",
        # Indent (not ``` fences) — plain-text/SMS relays can't render Markdown
        # and would show literal backticks. Matches _SETUP_NODE_LINES' style.
        "      superresearch --pair",
        "It shows an 8-char code; read it to me and I’ll add it.",
        "(Then finish the API-key + browser-login steps on the PC and it’s ready.)",
    ])


def _stream_arm_directive_lines(script_name: str, job_name: str) -> list[str]:
    """ASSISTANT-ONLY fallback directive: ask the runtime's cronjob tool to arm the
    watchdog. Only used when the deterministic jobs.json write can't run (legacy
    no-origin gateway) or fails (unusual layout / permissions) — the caller wraps
    these under the do-not-relay marker so the user never sees the cronjob syntax."""
    return [
        "Arm this chat's live-progress watchdog NOW with your cronjob tool so run "
        "progress and the 🎉 completion post here on their own:",
        f'  cronjob: create no_agent=true schedule="every 1m" '
        f'script="{script_name}" name="{job_name}"',
        "Create it now. Skip ONLY if your cronjob tool already lists a job with this "
        "exact name (then leave that one — do not duplicate) or if your runtime has "
        "no cronjob tool. Do NOT skip just because no run looks active yet — a "
        "just-started run isn't visible for a few seconds; once armed the watchdog "
        "persists and streams every run until `agent disconnect`.",
        "Arm the once-daily skill-update notice the same way (skip only if a job "
        "named sr-update-notice is already listed):",
        '  cronjob: create no_agent=true schedule="every 1d" '
        'script="sr_update_notice.py" name="sr-update-notice"',
    ]


def _prepare_stream_arm() -> tuple[list[str], dict, int]:
    """Arm THIS chat's run-scoped streaming watchdog and return ``(lines, payload,
    rc)``. On the modern path (a chat origin is known) this WRITES the cron job row
    straight into jobs.json (``_arm_stream_cron`` — idempotent, deterministic) and
    returns EMPTY ``lines`` (nothing for the AI to do). ``lines`` are non-empty only
    on the fallback paths: a legacy no-origin gateway, or a failed direct write —
    then they're ASSISTANT-ONLY cronjob directives the caller wraps via
    ``_agent_directive_block``. Writes a shim that bakes in this chat's origin (the
    cron can't take args or read the session env). The watchdog PERSISTS once armed
    (removed only by `agent disconnect`); arming is idempotent, so re-running on every
    research start / login is a safe no-op. A shim-write error → a single ✗ line +
    rc=1 (the caller drops it on the auto-arm paths)."""
    origin = _origin_from_env()
    if origin is None:
        # Legacy gateway with no chat origin: can't write a delivering job (an
        # origin-less job drops / mis-routes), so fall back to the AI cronjob
        # directive for the shared account-wide watchdog.
        payload = {"script": "sr_attention_poll.py", "name": "sr-stream",
                   "schedule": _STREAM_SCHEDULE["display"], "scoped": False,
                   "armed": False}
        return (_stream_arm_directive_lines("sr_attention_poll.py", "sr-stream"),
                payload, 0)
    slug = _origin_slug(origin)
    script_name = f"sr_poll_{slug}.py"
    job_name = f"sr-stream-{slug}"
    err = _write_poll_shim(_scripts_dir(), script_name, origin)
    if err:
        return ([f"✗ {err}"], {"error": err}, 1)
    # Deterministic arm: write the cron rows straight into jobs.json. This skill runs
    # in-chat so it has the origin + reach to the cron store — no dependence on the AI
    # calling cronjob:create (the recurring miss). Idempotent by name.
    armed = _arm_stream_cron(script_name, job_name, origin, _STREAM_SCHEDULE)
    # The once-daily update notice rides the same deterministic arm (best-effort: its
    # result doesn't gate the fallback below — only the watchdog's does, since a missed
    # update NOTICE is cosmetic while a missed watchdog is the bug we're fixing).
    _arm_stream_cron("sr_update_notice.py", "sr-update-notice", origin,
                     _UPDATE_NOTICE_SCHEDULE)
    payload = {"script": script_name, "name": job_name,
               "schedule": _STREAM_SCHEDULE["display"],
               "scoped": True, "origin": origin, "armed": armed}
    if armed:
        return ([], payload, 0)  # armed silently — nothing for the AI to do
    # Couldn't write jobs.json (unusual layout / permissions) → fall back to asking
    # the AI to arm via its cronjob tool (the legacy, less-reliable path).
    return (_stream_arm_directive_lines(script_name, job_name), payload, 0)


def cmd_arm_stream(args) -> int:
    """Arm THIS chat's streaming watchdog. Normally the skill arms it itself (a direct
    jobs.json write); research / login auto-arm the same way. This is the explicit
    standalone form."""
    lines, payload, rc = _prepare_stream_arm()
    if rc == 0 and not lines:
        # Armed deterministically (direct jobs.json write) — nothing for the AI to do.
        lines = ["✓ Live updates are on for this chat — run progress and the "
                 "completion will post here on their own."]
    elif rc == 0:
        lines = _agent_directive_block(lines)
    return _emit(payload, args.json, lines, rc)


# Statuses that mean "the watchdog should be ticking for this run" — mirrors
# sr_attention_poll._LIVE_STUCK (+ ongoing/queued are its _ACTIVE core).
_LIVE_RUN_STATUSES = ("queued", "ongoing", "paused_backend_restart",
                      "paused_backend_restart_failed")
# An armed watchdog rewrites its state file EVERY 1-min tick; older than this
# (or missing) while an agent run is live = the watchdog is NOT ticking.
_STREAM_STALE_SEC = 180


def _stream_health_lines(runs: list) -> list[str]:
    """Deterministic watchdog self-heal. The streaming watchdog — the thing that
    posts '⚠ needs you' / '🎉 done' WITHOUT being asked — is armed by the skill
    writing the cron row into jobs.json (see _prepare_stream_arm); if that job is
    somehow removed out-of-band, the chat goes silent and a blocked run just sits
    until the user happens to ask for status (live 2026-07-02: 'ChatGPT stopped
    responding' surfaced only on a manual ask, ~50 min late). Every armed tick
    rewrites the watchdog's state file, so a missing/stale file while an agent-fired
    run is live == not ticking → re-run the (idempotent) arm right from this
    status/updates reply. Silent on any doubt — never nag a healthy chat.

    Review catch: only counts runs THIS chat's watchdog would actually stream
    (chatOrigin matches this chat — the same platform+chat scope the per-chat
    shim queries with). Without that, a status ask from a DIFFERENT chat would
    arm a scoped watchdog that can never see the run — it posts nothing and,
    per the poll's never-tear-down-on-empty rule, never removes itself."""
    try:
        origin = _origin_from_env()

        def _mine(r: dict) -> bool:
            if not (r.get("viaAgent")
                    and (r.get("status") in _LIVE_RUN_STATUSES or r.get("needsAttention"))):
                return False
            if origin is None:
                return True  # account-wide watchdog streams every agent run
            co = r.get("chatOrigin")
            return (isinstance(co, dict)
                    and (co.get("platform") or "").strip().lower()
                    == (origin.get("platform") or "").strip().lower()
                    and (co.get("chat_id") or "").strip()
                    == (origin.get("chat_id") or "").strip())

        if not any(_mine(r) for r in runs):
            return []
        name = (f".sr_poll_{_origin_slug(origin)}.state.json" if origin
                else ".sr_stream_state.json")
        state = _scripts_dir() / name
        if state.exists() and (time.time() - state.stat().st_mtime) < _STREAM_STALE_SEC:
            return []  # ticking — healthy, say nothing
        # Re-arm deterministically (idempotent — a no-op if the cron is already
        # present). Only the fallback paths return directive lines to relay.
        arm_lines, _payload, rc = _prepare_stream_arm()
        return _agent_directive_block(arm_lines) if (rc == 0 and arm_lines) else []
    except Exception:
        return []


# ── `do` — deterministic natural-language fallback (#891) ───────────────────
# SKILL.md sends any message the AI can't confidently map to a command here
# VERBATIM. The text→command mapping then lives in CODE (ordered, unit-tested
# rules) instead of the chat AI's judgment — the live failures were exactly
# mis-picks ("Status of the Super Research?" → account status; "add device
# <code>" → refused). Contract: every printed line is USER-SAFE (sr.py output
# is relayed verbatim). Non-destructive intents run immediately; destructive
# ones print the confirm question and the AI runs the real command on "yes".

# Both alternatives REQUIRE a digit — every real access code has one, and
# without it ordinary hyphenated words ("real-time", "high-tech") match the
# dashed form and hijack the message into device-add.
_NL_CODE_RE = re.compile(
    r"\b((?=[A-Z0-9-]*\d)[A-Z0-9]{4}-[A-Z0-9]{4})\b|\b((?=[A-Z]*\d)[A-Z0-9]{8})\b", re.I)
# Double quotes only (straight + curly). Apostrophes are NOT delimiters — a
# contraction + possessive ("what's … Tesla's …") would otherwise extract the
# garbage between them as a run title.
_NL_QUOTED_RE = re.compile(r"[\"“]([^\"“”]+)[\"”]")
# The research-verb pattern, anchored at message start. Checked EARLY (before
# the control/status rules) so a research request whose TOPIC contains words
# like stop/pause/status/podcast ("research how to stop smoking") can never be
# hijacked into a run-control or status command.
_NL_RESEARCH_RE = re.compile(
    r"^(?:please |can you |could you |would you |hey |ok |okay |go |now )*"
    r"(?:(?:do|run|start|fire|kick ?off|launch|begin) (?:a |another |the )?)?"
    r"(?:super ?research|deep[- ]?research|deep[- ]?dive|research|look into|"
    r"investigate|dig into|analy[sz]e)\b(?: on| into| about| for| of)?\s*(.*)$",
    re.I)
# Words that mean "the current run", not a run name — drop, don't pass as title.
_NL_GENERIC_RUN = {"it", "that", "this", "them", "run", "the run", "this run",
                   "that run", "the current run", "current run", "the research",
                   "research", "the last one", "everything",
                   # the product's own name is never a run title
                   "super", "super research", "the super research"}
_NL_PHASE_WORDS = ("brief", "podcast", "video", "report", "email")
# P2 agent nouns for skip asks ("skip Claude in P2"). Ordered longest-first so
# "chatgpt" wins its substring "gpt" when rendering back into skip args.
_NL_AGENT_WORDS = ("chatgpt", "claude", "gemini", "gpt")
# Destructive verbs → the user-facing confirm question (AI runs the real
# command on "yes"; mirrors the SKILL.md Safety confirm-first list).
_NL_CONFIRMS = {
    "stop": "Stop {name}? It ends the run — everything finished so far is kept. Say yes and I’ll stop it.",
    "logout": "Sign out of Super Research? (The skill stays installed — you can sign back in anytime.) Say yes and I’ll sign you out.",
    "device-remove": "Unlink {name}? Nothing gets deleted — an owner’s device can re-pair with its code. Say yes and I’ll remove it.",
    "update": "Update the Super Research skill (this chat runtime)? The bridge restarts briefly. Say yes and I’ll update it.",
    "install": "Install the Super Research backend on the connected device? Say yes and I’ll set it up.",
}

# Info-only reply (NOT a confirm — there's no action for me to take): the skill
# only updates itself. A backend-update ask is redirected to where it happens —
# `superresearch --update` on the Research computer OR the app's update surface.
_NL_BACKEND_UPDATE_MOVED = (
    "I only update the Super Research skill (this chat) from here. To update Super "
    "Research on your Research computer, run “superresearch --update” there, or update "
    "it from the app (Settings → About, or the update notification). "
    "(Say “update” to update this skill.)"
)


def _nl_run_name(t: str, verb_tail: str = "") -> "str | None":
    """A run name from free text: a quoted title wins; else the words after
    of/for/on/about (minus articles + 'run/one/research' tails). Generic
    references ('it', 'the run') → None → the command defaults to the
    most-recent run."""
    m = _NL_QUOTED_RE.search(t)
    name = None
    if m:
        name = m.group(1)
    else:
        src = verb_tail if verb_tail else t
        m2 = re.search(r"\b(?:of|for|on|about)\s+(?:the\s+|my\s+)?(.+)$", src, re.I) or \
            (re.search(r"^(?:the\s+|my\s+)?(.+)$", verb_tail, re.I) if verb_tail else None)
        if m2:
            name = m2.group(1)
    if not name:
        return None
    name = re.sub(r"[?.!,]+$", "", name).strip()
    name = re.sub(r"\s+(run|one|research|research run)$", "", name, flags=re.I).strip()
    if not name or name.lower() in _NL_GENERIC_RUN:
        return None
    return name


def _nl_resolve(text: str) -> "tuple[list[str] | None, list[str] | None]":
    """Map a verbatim user message to (argv, None) to execute, or
    (None, user-safe lines) to relay. Ordered — most specific first."""
    t = " ".join((text or "").split())
    low = t.lower().rstrip("?!. ")
    if not low:
        return None, ["What would you like? I can research a topic, check a run’s "
                      "status, fetch its podcast or links, or manage your devices."]

    # 1. An access code = pair a device (never a secret — see SKILL.md). Wins
    #    only when the message IS the code, or says device/pair/add/code — a
    #    code-shaped token inside a sentence ("research iphone17 pricing")
    #    must not hijack the request into a bogus pairing attempt.
    code_m = _NL_CODE_RE.search(t)
    if code_m:
        tok = code_m.group(1) or code_m.group(2)
        _kw = re.search(r"\b(device|node|pair|add|code|machine|pc|computer)\b", low)
        _bare = re.fullmatch(r"[^A-Za-z0-9]*" + re.escape(tok) + r"[^A-Za-z0-9]*", t, re.I)
        if _kw or _bare:
            return ["device-add", tok], None
    if re.search(r"\b(add|pair|connect)\b.*\b(device|node|machine|pc|computer)\b", low) or \
            re.search(r"\bpair (my|a|the|this)\b", low):
        return None, ["Paste the access code shown on the computer running Super "
                      "Research (8 characters — dashes optional) and I’ll add it."]

    # 2. Sign-in / connection questions — always a FRESH account check.
    if re.search(r"\b(am i|are we|is (it|this|the agent))\b.*\b(signed?[ -]?in|logg?ed[ -]?in|connected|authenticated)\b", low) or \
            re.search(r"\b(which|what) account\b", low) or "account status" in low or \
            "connection status" in low:
        return ["status-account"], None

    # 2b. A message that STARTS with a research verb is a research request —
    #     resolved before every remaining rule so control/status/phase words in
    #     the TOPIC ("research how to stop smoking", "research the history of
    #     the podcast industry") can't hijack it. A trailing "without/no video|
    #     email" clause maps to the run flags; a bare "research status" tail
    #     falls through (that's a progress ask, not a topic).
    rm = _NL_RESEARCH_RE.match(t)
    if rm:
        topic = re.sub(r"[?.!]+$", "", rm.group(1)).strip().strip("\"“”'‘’")
        if topic and not re.fullmatch(r"(?:the |my )?(?:status|progress|updates?)", topic, re.I):
            flags: list[str] = []
            ex = re.search(
                r"[,;\s]*\b(?:without|minus|skip(?:ping)?|drop(?:ping)?|leave out|no)\s+"
                r"(?:the\s+|a\s+|any\s+)?(?:video|email|podcast|brief|report|chatgpt|gpt|claude|gemini)s?\b",
                topic, re.I)
            if ex:
                clause = topic[ex.start():].lower()
                topic = topic[:ex.start()].rstrip(" ,;.")
                hard = []
                for p in _NL_PHASE_WORDS:
                    if p not in clause:
                        continue
                    if p == "video":
                        flags.append("--no-video")
                    elif p == "email":
                        flags.append("--no-email")
                    else:
                        hard.append("the " + p)
                # P2 agents have no research-time flag either — same honest
                # two-step (skip them right after the run starts).
                for a in _NL_AGENT_WORDS:
                    if a in clause:
                        disp = _AGENT_DISPLAY.get(_SKIP_AGENTS.get(a, a), a)
                        if disp not in hard:
                            hard.append(disp)
                if hard and topic:
                    # No research-time flag exists for these — offer the
                    # honest two-step instead of silently ignoring the ask.
                    return None, [
                        f"I can start “{topic}” right away — {', '.join(hard)} "
                        "can be trimmed once the run starts (just ask me to skip "
                        "it then). Say yes to start."]
            if topic:
                return ["research", topic] + flags, None
            return None, ["Happy to fire a Super Research — what topic?"]
        if not topic:
            return None, ["Happy to fire a Super Research — what topic?"]

    # 2c. Sending logs to support. AFTER the research rule on purpose — "research
    #     how log shipping works" is a topic, not a request to send anything —
    #     and it needs BOTH a giving verb and the word logs, so "check the logs"
    #     and "what do the logs say" fall through to the status rules where they
    #     belong. The bare command only SHOWS what would go, so resolving this
    #     eagerly cannot send anything by mistake.
    if re.search(r"\b(logs?|log ?files?|diagnostics?)\b", low) and re.search(
            r"\b(send|share|upload|submit|report|give|email|hand)\b", low):
        argv = ["send-logs"]
        # ⛔⛔ ONLY AN EXPLICIT ASK FOR THE COMPUTER'S OWN LOGS REACHES THE FLAG,
        # and "everything" / "all of them" deliberately do NOT. That material is
        # every run the machine has ever done for everyone who uses it, and a
        # person saying "send all the logs" means all of THEIRS — reading it the
        # other way turns a broad word into a request they did not make. The
        # narrow phrasing is reachable because the no-runs branch offers it in
        # those words, so the one case that genuinely needs it has a route.
        if re.search(r"\b(computer|machine|device)(?:’s|'s)?\s+own\b", low) or \
                re.search(r"\bown\s+(logs?|log ?files?|diagnostics?)\b", low):
            argv.append("--machine")
        return argv, None

    # 3. Run controls (before the broad status rules).
    if re.search(r"\b(stop|end|abort|cancel)\b", low) or re.search(r"\bthat.?s enough\b", low):
        name = _nl_run_name(t, re.sub(r"^.*?\b(?:stop|end|abort|cancel)\b", "", t, flags=re.I).strip())
        return None, [_NL_CONFIRMS["stop"].format(name=f"“{name}”" if name else "the current run")]
    if re.search(r"\bpause\b|\bhold (on|it)\b", low):
        name = _nl_run_name(t, re.sub(r"^.*?\bpause\b", "", t, flags=re.I).strip())
        return ["pause"] + ([name] if name else []), None
    if re.search(r"\b(resume|unpause)\b|\bcontinue the paused\b", low):
        name = _nl_run_name(t, re.sub(r"^.*?\b(?:resume|unpause)\b", "", t, flags=re.I).strip())
        return ["resume"] + ([name] if name else []), None
    if re.search(r"\b(retry|try again)\b", low):
        name = _nl_run_name(t, re.sub(r"^.*?\b(?:retry|try again)\b", "", t, flags=re.I).strip())
        return ["retry"] + ([name] if name else []), None
    # skip / drop phases or P2 agents ("skip the video and the report",
    # "remove the video", "no email", "skip Claude in P2"). Guards (review
    # catches — skip is NOT confirm-gated, so a mis-route silently
    # reconfigures a live run):
    #   • questions bail ("did claude skip anything?" is not an order);
    #   • device nouns bail ("remove claude's laptop" = device-remove, which
    #     keeps its confirm);
    #   • agent nouns need the verb ADJACENT ("skip claude"), never bare
    #     co-occurrence, never a possessive/compound ("claude's", "claude-pc"),
    #     and never when folded into a phase noun ("the gemini video" is the
    #     video, not the agent);
    #   • a research ask in the same message bails ("no gpt needed, research
    #     solar panels" must not eat the research and drop ChatGPT).
    _q_start = re.match(
        r"\s*(why|is|are|did|does|has|have|what|when|where|who|how"
        # Modal-verb yes/no questions are ASKS, not orders: "can/could/should/
        # would/will/shall/may/do I skip the podcast?" must bail to a relay, not
        # silently skip a phase on the live run (skip is not confirm-gated).
        r"|can|could|should|would|will|shall|may|do|don't|dont)\b",
        low,
    )
    _device_noun = re.search(r"\b(device|node|laptop|pc|computer|machine|phone|desktop)\b", low)
    if not _q_start and not _device_noun and \
            re.search(r"\b(skip|drop|remove|cut|leave out|without|no)\b", low):
        phases = [p for p in _NL_PHASE_WORDS if p in low]
        agents: list = []
        _agent_adjacent = re.search(
            r"\b(?:skip(?:ping)?|drop(?:ping)?|remove|cut|leave\s+out|without|minus|no)\s+"
            r"(?:the\s+|a\s+|any\s+)?(?:chatgpt|gpt|claude|gemini)\b(?!['’-])"
            r"(?!\s+(?:video|podcast|report|brief|email)\b)", low)
        if _agent_adjacent and not re.search(r"\b(?:research|look into|deep dive on|investigate)\s+\w+", low):
            agents = [a for a in _NL_AGENT_WORDS
                      if re.search(rf"\b{a}\b(?!['’-])(?!\s+(?:video|podcast|report|brief|email)\b)", low)]
        if phases or agents:
            return ["skip"] + phases + agents, None
    if re.search(r"^skip\b|\bskip (it|this|that|the step|the blocker)\b", low):
        return ["skip"], None

    # 4. Devices.
    if re.search(r"\b(which|what|list|show|my)\b.*\b(devices?|nodes?)\b", low) or \
            low in ("devices", "device list") or "what am i running on" in low:
        return ["devices"], None
    m = re.search(r"\b(?:switch to|run (?:it |everything )?on|use)\s+(?:the\s+|my\s+)?(.+)$", t, flags=re.I)
    if m and re.search(r"\b(switch to|run (it |everything )?on)\b", low):
        name = re.sub(r"[?.!,]+$", "", m.group(1)).strip()
        return (["device-use", name] if name else ["devices"]), None
    if re.search(r"\b(remove|unlink|forget|delete)\b", low) and \
            re.search(r"\b(device|node|laptop|pc|computer|machine|phone|desktop)\b", low):
        m = re.search(r"\b(?:remove|unlink|forget|delete)\s+(?:the\s+|my\s+)?(.+)$", t, flags=re.I)
        name = re.sub(r"[?.!,]+$", "", m.group(1)).strip() if m else ""
        name = re.sub(r"^(old|other)\s+", "", name, flags=re.I)
        return None, [_NL_CONFIRMS["device-remove"].format(name=f"“{name}”" if name else "that device")]

    # 5. Session + maintenance.
    if re.search(r"\b(uninstall|tear ?down)\b", low) or \
            re.search(r"\b(remove|disconnect)\b.*\b(entirely|completely|fully|everything)\b", low):
        return None, ["Just sign out, or fully remove the skill + bridge from this "
                      "machine? (Sign-out keeps everything installed.)"]
    if re.search(r"\b(sign|log)\s?(me\s)?out\b|\blogout\b", low):
        return None, [_NL_CONFIRMS["logout"]]
    if re.search(r"\b(sign|log)\s?(me\s)?in\b|\blogin\b|\bauthenticate\b", low):
        return ["login"], None
    if re.search(r"\b(i('m| am)? (signed|logged) in|i did it|signed in now)\b", low):
        return ["login-done"], None
    if re.search(r"\b(update|upgrade)\b", low):
        # "update me / any update on X / give me an update" is a PROGRESS ask,
        # not software maintenance — routing it to the update confirm made a
        # reflexive "yes" restart the backend mid-run.
        if re.search(r"\bupdates? (me|on|about|regarding|for)\b|\bany updates?\b"
                     r"|\b(give|got|have|send)\b.*\bupdates?\b|\blatest updates?\b", low):
            name = _nl_run_name(t)
            return ["status"] + ([name] if name else []), None
        # A backend-named ask that is NOT also a skill ask (e.g. "update super
        # research", "update the backend", "update the research computer") →
        # redirect: the skill doesn't update the backend (the app / the host CLI
        # does). Checked BEFORE the skill default so "update the super research
        # SKILL/agent" still self-updates the skill (the 'agent' token is still
        # accepted colloquially even though the skill no longer calls itself that).
        if not re.search(r"\b(skill|agent|bridge|chat|yourself)\b", low) and \
                re.search(r"\b(backend|super ?research|research (pc|computer|machine))\b", low):
            return None, [_NL_BACKEND_UPDATE_MOVED]
        # Everything else — "update", "upgrade", "update the skill/yourself", and
        # colloquial "update the agent" — updates the Super Research SKILL (the
        # only thing this updates now). No agent-vs-backend split → no misroute to
        # a backend that isn't on this host (the old default hit "Super Research
        # isn't installed on the connected device" for a plain "update").
        return None, [_NL_CONFIRMS["update"]]
    if re.search(r"\bversions?\b", low):
        return ["version"], None
    if re.search(r"\b(install|host|set ?up)\b.*\b(backend|super research|here|this (pc|machine|computer))\b", low):
        return None, [_NL_CONFIRMS["install"]]

    # 6. Listing + progress (before research — "results of X" is a status ask).
    if re.search(r"\bwhat('s| is) (running|active)\b|\bactive runs?\b|\banything running\b", low):
        return ["updates"], None
    if re.search(r"\b(list|show|what)\b.*\b(researches|research history|past research(es)?)\b", low) or \
            low in ("list", "my researches", "researches"):
        return ["list"], None
    if re.search(r"\bpodcast\b|\baudio( overview)?\b", low):
        name = _nl_run_name(t)
        return ["podcast"] + ([name] if name else []), None
    if re.search(r"\bstatus\b|\bprogress\b|\bhow('s| is) (it|that|the .{1,40}) (going|coming|doing)\b"
                 r"|\bhow far\b|\bwhere('s| is) .{1,40} at\b|\bresults? (of|for)\b"
                 r"|\b(any|latest) updates?\b", low):
        name = _nl_run_name(t)
        return ["status"] + ([name] if name else []), None

    # 7. Nothing matched — user-safe capabilities line (never guess a command).
    #    (Research phrasings were resolved at 2b, before the control rules.)
    return None, ["I didn’t catch a Super Research request in that. I can research "
                  "a topic, check a run’s status, fetch its podcast or links, list "
                  "your researches, or manage your devices — what would you like?"]


# The only option flags _nl_resolve ever emits — everything else in a resolved
# argv is a positional. cmd_do uses this to place the `--` separator.
_DO_FLAGS = frozenset({"--no-video", "--no-email"})


def cmd_do(args) -> int:
    """Resolve a verbatim user message to a command and run it (or print the
    one confirm/clarify question). The AI relays whatever this prints."""
    argv, lines = _nl_resolve(" ".join(args.text))
    if argv is None:
        return _emit({}, args.json, lines or [])
    # `--` before the free-text positionals: a topic/name that happens to start
    # with a dash ("research --help") must reach the command as a literal value,
    # never dump argparse usage into the chat relay.
    cmd, rest = argv[0], argv[1:]
    flags = [a for a in rest if a in _DO_FLAGS]
    pos = [a for a in rest if a not in _DO_FLAGS]
    final = (["--json"] if args.json else []) + [cmd] + flags + (["--"] + pos if pos else [])
    try:
        ns = build_parser().parse_args(final)
    except SystemExit:
        # A resolved arg the parser refused (shouldn't happen) — never crash the
        # chat turn; fall back to the ask-what-you-want line.
        return _emit({}, args.json, ["I didn’t catch a Super Research request in "
                                     "that — name a topic, a run, or a device."])
    return ns.func(ns)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sr", description="Super Research skill client")
    p.add_argument("--json", action="store_true", help="print the raw bridge JSON")
    sub = p.add_subparsers(dest="command", required=True)

    lg = sub.add_parser("login", help="start a remote sign-in")
    lg.add_argument("--runtime", default="")
    lg.add_argument("--label", default="")
    lg.set_defaults(func=cmd_login)

    sub.add_parser("login-done", aliases=["login-wait"],
                   help="poll until sign-in completes").set_defaults(func=cmd_login_wait)
    sub.add_parser("status-account", help="bridge + session status").set_defaults(func=cmd_status_account)
    sub.add_parser("devices", help="list reachable devices").set_defaults(func=cmd_devices)

    du = sub.add_parser("device-use", help="select the target device (by name or id)")
    du.add_argument("device")
    du.set_defaults(func=cmd_device_use)

    da = sub.add_parser("device-add", help="pair a device by the code on its screen")
    da.add_argument("code")
    da.set_defaults(func=cmd_device_add)

    dr = sub.add_parser("device-remove", help="unlink a device (by name or id)")
    dr.add_argument("device")
    dr.set_defaults(func=cmd_device_remove)

    rs = sub.add_parser("research", help="start a run")
    rs.add_argument("topic")
    rs.add_argument("--device", default="")
    rs.add_argument("--no-video", action="store_true")
    rs.add_argument("--no-email", action="store_true")
    rs.set_defaults(func=cmd_research)

    st = sub.add_parser("status", help="a run's progress (no id = most recent)")
    st.add_argument("runId", nargs="?")
    st.set_defaults(func=cmd_status)

    pod = sub.add_parser("podcast", help="a run's audio as a local file to send as native audio")
    pod.add_argument("runId", nargs="?")
    pod.set_defaults(func=cmd_podcast)

    up = sub.add_parser("updates", help="active runs + current links (streaming cron)")
    up.add_argument("--active", action="store_true")
    up.set_defaults(func=cmd_updates)

    sub.add_parser("list", aliases=["researches"],
                   help="list ALL recent researches (any status) to pick one by name") \
        .set_defaults(func=cmd_list)

    # Graceful stop (keeps results + chat). `cancel` is an alias for the same
    # graceful behavior so an old habit never triggers a destructive delete.
    for _name, _help in (("stop", "gracefully stop a run (no run = most recent active)"),
                         ("cancel", "alias for stop (graceful — keeps results + chat)")):
        sp = sub.add_parser(_name, help=_help)
        sp.add_argument("runId", nargs="?")
        sp.set_defaults(func=cmd_stop)

    pa = sub.add_parser("pause", help="pause a running run (stays resumable)")
    pa.add_argument("runId", nargs="?")
    pa.set_defaults(func=cmd_pause)

    rsm = sub.add_parser("resume", help="resume a paused run")
    rsm.add_argument("runId", nargs="?")
    rsm.set_defaults(func=cmd_resume)

    rt = sub.add_parser("retry", help="resume a run waiting on a decision / error")
    rt.add_argument("runId", nargs="?")
    rt.set_defaults(func=cmd_retry)

    # No args → skip whatever the run is blocked on; phases → trim those
    # phases; agent names (chatgpt/gemini/claude) → turn those P2 agents off.
    sk = sub.add_parser("skip", help="skip a run's current blocker, named phases, or P2 agents")
    sk.add_argument("phases", nargs="*")
    sk.add_argument("--run", default="", help="run title or id (default: newest active run)")
    sk.set_defaults(func=cmd_skip)

    # Confirm-first: the bare form SHOWS what would be sent and sends nothing.
    sl = sub.add_parser("send-logs", aliases=["logs", "send-log"],
                        help="send Super Research support the logs from the connected computer")
    sl.add_argument("--confirm", action="store_true",
                    help="actually send (the bare command only shows what would go)")
    sl.add_argument("--machine", action="store_true",
                    help="also send that computer's own logs (its owner only)")
    sl.add_argument("--none", action="store_true",
                    help="send no runs — for connection problems, with --machine")
    sl.add_argument("--device", default="", help="which computer (name or id)")
    sl.add_argument("--status", default="", metavar="CODE",
                    help="report on a support code instead of sending")
    sl.set_defaults(func=cmd_send_logs)

    sub.add_parser("logout", help="clear the account session").set_defaults(func=cmd_logout)

    sub.add_parser("version", aliases=["versions"],
                   help="show the Super Research skill version (+ update notice)").set_defaults(func=cmd_version)
    sub.add_parser("install", aliases=["install-backend", "setup-backend"],
                   help="install the Super Research backend on the connected device (host a BE)"
                   ).set_defaults(func=cmd_install)
    # `update` updates the Super Research SKILL (this chat runtime — /sr scripts +
    # bridge), the ONLY thing the runtime updates. Backend updates are done in the
    # app / with `superresearch --update` on the host — there is no backend-update
    # subcommand here. `install` (host a backend) is unaffected. NL ("upgrade",
    # "update the skill", etc.) resolves through `do`, so `update-skill` is the
    # only alias kept.
    sub.add_parser("update", aliases=["update-skill"],
                   help="update the Super Research skill (this chat — scripts + bridge) to the latest"
                   ).set_defaults(func=cmd_update)

    sub.add_parser(
        "arm-stream",
        help="prepare this chat's streaming watchdog (prints the cron script + name to arm)",
    ).set_defaults(func=cmd_arm_stream)

    do = sub.add_parser("do", aliases=["nl"],
                        help="resolve a verbatim user message to a command and run it")
    # REMAINDER: capture the whole message even when a token starts with "-"
    # ("do research --help") — the message is data, never options of `do`.
    do.add_argument("text", nargs=argparse.REMAINDER)
    do.set_defaults(func=cmd_do)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
