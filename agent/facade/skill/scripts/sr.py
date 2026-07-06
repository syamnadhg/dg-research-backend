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
  version            show the agent + Super Research backend versions
  update-agent       update the chat agent itself (skill + bridge) to the latest
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
from pathlib import Path

# The version of the agent package THIS script copy shipped with. The runtime
# executes its own installed COPY of this file (HERMES_HOME/scripts), which a
# `pip install -U` on the host does NOT refresh — only `agent connect` /
# “update the agent” redeploys it. cmd_version compares this against the live
# bridge's version so a stale chat-side copy names itself instead of misbehaving
# silently (live 2026-07-02: a stale copy predating the podcast MEDIA: fix
# kept sending bare audio paths). Bumped together with pyproject.toml —
# guarded by tests/test_sr_skip_agents.py::test_skill_build_matches_package_version.
_SKILL_BUILD = "0.1.22"

_TIMEOUT = 30
# By-title run resolution scans the newest N runs (status / podcast / list / the
# resume verbs). 20 was too shallow — a run a few weeks back (named, not active)
# fell outside the window, so `podcast "Rocky Port…"` silently found nothing and
# the agent improvised. 100 covers a deep history; it's a plain Firestore list
# (no per-phase minting — that's only the via=agent `updates` path, left at 20).
# Mirrors the bridge's /updates limit cap (bridge.py `_updates`).
_LOOKUP_LIMIT = 100

# How to install Super Research on a fresh Research Computer (no backend yet):
# the SAME one-line installer the web app's "Set up your own Research Computer"
# tile uses (auto-installs Python + pipx + superresearch), then `--pair`. Kept in
# ONE place so the `devices`-empty and `research`-no-device prompts stay identical
# + in sync with the web app. (Older builds said `pipx install superresearch`.)
_SETUP_NODE_LINES = [
    "No backend on that machine yet? Run one line there (pick your OS):",
    "```",
    "irm https://superresearch.io/install.ps1 | iex      # Windows",
    "curl -fsSL https://superresearch.io/install.sh | sh  # macOS / Linux",
    "superresearch --pair",
    "```",
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
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, (json.loads(raw) if raw else {})
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return 0, {"error": f"bridge unreachable ({e.reason}) — the Super Research bridge "
                            "isn't running on this machine yet. Set it up with `pipx run "
                            "superresearch-agent connect` (it starts the bridge + keeps it "
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
                      "running Super Research and I’ll connect it."]
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
    if arm_rc == 0:
        lines += arm_lines
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
    """Proactive "a newer AGENT version is available" prompt from a /status (or
    /version) body — so the user is nudged on the welcome without having to ask.
    Backend updates are NOT nudged here anymore: the app surfaces those and the
    user runs `superresearch --update` on the Research computer (the runtime no
    longer updates the backend)."""
    out = []
    if body.get("agentUpdate"):
        out.append(f"⬆️ Agent v{body['agentUpdate']} is available — say “update the agent”.")
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
                if arm_rc == 0:
                    lines += arm_lines
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
                if arm_rc == 0:
                    lines += arm_lines
                return _emit({**body, "verifyUrl": link}, args.json, lines, _fail_code(code))
            return _emit(body, args.json, [
                "You're not signed in yet — tell me to log you in and I'll send a link.",
            ], _fail_code(code))
        # Signed in but no device on the account yet → guide connecting one, plainly.
        err = str(body.get("error", "")).lower()
        if "no device" in err:
            return _emit(body, args.json, [
                "Paste the access code from your Research Computer first.",
                "",
                *_SETUP_NODE_LINES,
            ], _fail_code(code))
        return _emit(body, args.json, [f"✗ couldn't start: {body.get('error', code)}"], _fail_code(code))
    dev = _device_names().get(body.get("deviceId") or "", body.get("deviceId") or "")
    where = f" on {dev}" if dev else ""
    lines = [
        f"🚀 Started “{args.topic}”{where}.",
        "I’ll post here when it’s done — and if it ever needs you. Ask how it’s going anytime.",
    ]
    # Auto-arm THIS chat's run-scoped streaming watchdog so progress posts without
    # the user asking — emit the cronjob directive inline (the gateway dedups by the
    # fixed job name; the watchdog self-removes when the run finishes). On a prep
    # error, skip silently: the run is fine and `status` still works.
    arm_lines, _payload, arm_rc = _prepare_stream_arm()
    if arm_rc == 0:
        lines += arm_lines
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
    code, b2 = _get(f"/research/{urllib.parse.quote(rid, safe='')}/podcast", timeout=180)
    if code != 200:
        return _emit(b2, args.json, [f"✗ {b2.get('error', code)}"], _fail_code(code))
    title = b2.get("title") or "Podcast"
    # Emit a short caption + an explicit MEDIA:<path> tag on its own line. The
    # runtime's gateway extracts MEDIA: tags into its AUDIO partition, which
    # delivers the file as native PLAYABLE audio (Telegram sendAudio for
    # mp3/m4a; other platforms' voice/audio sender) and strips the tag from
    # the visible text — so the user sees the title + an inline player. A BARE
    # path is NOT equivalent: bare paths route to document delivery (a "📎
    # File" attachment, not playable — the 2026-07-02 live failure). Do NOT
    # add [[audio_as_voice]]: it suppresses the text body (voice-reply dedup)
    # and only matters for .ogg/.opus voice bubbles.
    return _emit(b2, args.json, [
        f"🎧 {title}",
        f"MEDIA:{b2.get('localPath')}",
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
    """Show the chat agent's version (+ a "newer available" nudge for the AGENT
    when one is published) alongside the Super Research backend's version. The
    agent no longer prompts to update the backend — the app surfaces that and the
    user runs `superresearch --update` on the Research computer — so the backend
    line is display-only here."""
    code, body = _get("/version")
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't read versions: {body.get('error', code)}"],
                     _fail_code(code))
    agent = body.get("agent") or "?"
    backend = body.get("backend")
    a_new = body.get("agentLatest")
    lines = [f"Super Research agent    v{agent}"
             + (f"   ⬆️ v{a_new} available — say “update the agent”" if a_new else "")]
    if backend:
        lines.append(f"Super Research backend  v{backend}")
    else:
        lines.append("Super Research backend  (not installed on the connected device)")
    # Stale chat-side copy tell: the runtime executes its own installed COPY of
    # these scripts, which only `agent connect` / “update the agent” redeploys —
    # a host pip upgrade alone leaves the chat side on old behavior (live
    # 2026-07-02: a stale copy predated the podcast MEDIA: fix). Name it.
    if agent not in ("?", _SKILL_BUILD):
        lines.append(f"⚠ This chat's scripts are v{_SKILL_BUILD} but the agent is v{agent} — "
                     "say “update the agent” to redeploy them.")
    return _emit(body, args.json, lines)


def cmd_agent_update(args) -> int:
    """Update the chat AGENT itself — its package + skill + bridge — to the latest
    published version (the bridge reconnects from the latest in the background).
    Distinct from `update`, which updates the Super Research backend."""
    code, body = _post("/agent-install")
    if code != 200:
        err = body.get("error", "")
        if err == "agent_unavailable":
            msg = ("can't reach the latest agent right now — the device may be offline, "
                   "or this version isn't published yet. (Nothing changed; the agent is still running.)")
        elif err == "update_helper_failed":
            msg = "couldn't start the agent update (is pipx available on the connected device?)"
        else:
            msg = f"couldn't start the agent update: {err or code}"
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    if body.get("already"):
        cur = body.get("current") or ""
        return _emit(body, args.json,
                     [f"✓ The agent is already up to date{(' (v' + cur + ')') if cur else ''}."])
    return _emit(body, args.json, [
        "⬆️ Updating the Super Research agent (skill + bridge) to the latest version.",
        "The bridge briefly restarts on the new version — say “agent version” in a bit to confirm.",
    ])


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
            "To update it, run “superresearch --update” on that computer; say "
            "“devices” to see/pair it.",
        ])
    return _emit(body, args.json, [
        "⬇️ Installing Super Research on this device in the background.",
        "When it finishes, pair it — run this on that PC:",
        "```",
        "superresearch --pair",
        "```",
        "It shows an 8-char code; read it to me and I’ll add it.",
        "(Then finish the API-key + browser-login steps on the PC and it’s ready.)",
    ])


def _prepare_stream_arm() -> tuple[list[str], dict, int]:
    """Prepare THIS chat's run-scoped streaming watchdog and return
    ``(lines, payload, rc)`` — ``lines`` carry the gateway ``cronjob: create …``
    directive that arms it. Writes a shim that bakes in this chat's origin (the
    cron can't take args or read the session env). The watchdog SELF-REMOVES once
    the chat's runs finish, so it's safe to (re-)emit on every research start — the
    gateway dedups by the fixed job name. No chat origin (older gateway) → the
    shared account-wide watchdog. A shim-write error → a single ✗ line + rc=1."""
    origin = _origin_from_env()
    if origin is None:
        payload = {"script": "sr_attention_poll.py", "name": "sr-stream",
                   "schedule": "every 1m", "scoped": False}
        return ([
            "To stream progress here, arm the watchdog with the cronjob tool "
            "(it auto-removes when the run finishes):",
            '  cronjob: create no_agent=true schedule="every 1m" '
            'script="sr_attention_poll.py" name="sr-stream"',
        ], payload, 0)
    slug = _origin_slug(origin)
    script_name = f"sr_poll_{slug}.py"
    job_name = f"sr-stream-{slug}"
    err = _write_poll_shim(_scripts_dir(), script_name, origin)
    if err:
        return ([f"✗ {err}"], {"error": err}, 1)
    payload = {"script": script_name, "name": job_name, "schedule": "every 1m",
               "scoped": True, "origin": origin}
    return ([
        "To stream progress here, arm the watchdog with the cronjob tool — first "
        "check it isn't already armed; it streams only THIS chat's runs and "
        "auto-removes when they finish:",
        f'  cronjob: create no_agent=true schedule="every 1m" '
        f'script="{script_name}" name="{job_name}"',
    ], payload, 0)


def cmd_arm_stream(args) -> int:
    """Prepare THIS chat's streaming watchdog and tell the agent how to arm it.
    (Research auto-emits the same directive; this is the explicit/standalone form.)"""
    lines, payload, rc = _prepare_stream_arm()
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
    posts '⚠ needs you' / '🎉 done' WITHOUT being asked — is armed by the chat
    AI acting on a directive printed at research-fire; if that one message is
    missed (or the cron job was removed), the chat goes silent and a blocked
    run just sits until the user happens to ask for status (live 2026-07-02:
    'ChatGPT stopped responding' surfaced only on a manual ask, ~50 min late).
    Every armed tick rewrites the watchdog's state file, so a missing/stale
    file while an agent-fired run is live == not ticking → re-emit the arming
    directive so the AI re-arms right from this status/updates reply. Silent
    on any doubt — never nag a healthy chat.

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
        arm_lines, _payload, rc = _prepare_stream_arm()
        return arm_lines if rc == 0 else []
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
    "agent-update": "Update the chat agent itself? The bridge restarts briefly. Say yes and I’ll update it.",
    "install": "Install the Super Research backend on the connected device? Say yes and I’ll set it up.",
}

# Info-only reply (NOT a confirm — there's no action for me to take): the runtime
# no longer updates the Super Research backend. A backend-update ask is redirected
# to where it happens now — the app notifies + the user runs it on the Research PC.
_NL_BACKEND_UPDATE_MOVED = (
    "I only update the chat agent from here now. To update Super Research itself, "
    "run “superresearch --update” on the Research computer — the app also notifies "
    "you when a backend update is available. (Say “update the agent” to update this chat agent.)"
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
    _q_start = re.match(r"\s*(why|is|are|did|does|has|have|what|when|where|who|how)\b", low)
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
        # A backend-named ask that is NOT also an agent ask (e.g. "update super
        # research", "update the backend", "update the research computer") →
        # redirect: the runtime doesn't update the backend anymore (the app does).
        # Checked BEFORE the agent default so "update the super research AGENT"
        # still self-updates the agent.
        if not re.search(r"\b(agent|skill|bridge|chat|yourself)\b", low) and \
                re.search(r"\b(backend|super ?research|research (pc|computer|machine))\b", low):
            return None, [_NL_BACKEND_UPDATE_MOVED]
        # Everything else — "update", "upgrade", "update the agent/skill/yourself"
        # — updates the CHAT AGENT (the only thing the runtime updates now). No
        # agent-vs-backend split → no misroute to a backend that isn't on this host
        # (the old default hit "Super Research isn't installed on the connected
        # device" for a plain "update").
        return None, [_NL_CONFIRMS["agent-update"]]
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

    sub.add_parser("logout", help="clear the account session").set_defaults(func=cmd_logout)

    sub.add_parser("version", aliases=["versions"],
                   help="show the agent + Super Research backend versions (+ update notices)").set_defaults(func=cmd_version)
    sub.add_parser("install", aliases=["install-backend", "setup-backend"],
                   help="install the Super Research backend on the connected device (host a BE)"
                   ).set_defaults(func=cmd_install)
    # NOTE: no `update`/`upgrade` subcommand — the runtime no longer updates the
    # Super Research BACKEND (the app surfaces that; the user runs `superresearch
    # update` on the Research computer). `update-agent`/`upgrade-agent` below
    # update the chat AGENT itself. `install` (host a backend) is unaffected.
    sub.add_parser("agent-update",
                   aliases=["agent-install", "update-agent", "update-skill",
                            "upgrade-agent", "update", "upgrade"],
                   help="update the chat agent itself (package + skill + bridge) to the latest"
                   ).set_defaults(func=cmd_agent_update)

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
