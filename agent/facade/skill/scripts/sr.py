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
  update             update the Super Research backend on the connected device
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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_TIMEOUT = 30


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
    """Proactive "a newer version is available" prompts from a /status (or /version)
    body — so the user is nudged on the welcome without having to ask."""
    out = []
    if body.get("backendUpdate"):
        out.append(f"⬆️ Super Research v{body['backendUpdate']} is available — say “update”.")
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
            "research node and I’ll connect it.")


def cmd_status_account(args) -> int:
    code, body = _get("/status")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if body.get("authed"):
        lines = [f"✓ Signed in as {body.get('email') or body.get('uid')}"]
        if not _has_device():
            lines.append("No device connected yet — paste the access code from your "
                         "research node and I’ll connect it.")
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
            "Paste the access code from your research node and I’ll connect it.",
            "",
            "No backend yet? On that machine, run:",
            "```",
            "pipx install superresearch",
            "superresearch --pair",
            "```",
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
                "Paste the access code from your research node first.",
                "If it isn’t set up yet, run this on that machine:",
                "```",
                "pipx install superresearch",
                "superresearch --pair",
                "```",
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
    code, body, runs = _fetch_runs()
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
    lines = [f"“{title}” — {r.get('status', '?')} (phase {r.get('phase', '?')}){where}"]
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
    return _emit(b2, args.json, lines)


def cmd_podcast(args) -> int:
    code, body, runs = _fetch_runs()
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
    # Emit a short caption + the audio file's BARE path on its own line. The runtime
    # auto-detects a bare on-disk media path, delivers the file as a native audio /
    # voice message, and STRIPS the path from the visible text — so the user sees the
    # caption + the audio, never the path. Do NOT decorate or wrap the path (no 🔊 /
    # "Audio:" label, no backticks, no [[audio]] markup) — that defeats the auto-attach.
    return _emit(b2, args.json, [
        f"🎧 {title}",
        f"{b2.get('localPath')}",
    ])


def cmd_updates(args) -> int:
    # via_agent → agent-only runs + per-phase SR-link minting (same clean links
    # the streaming watchdog posts).
    code, body, runs = _fetch_runs(active=args.active, via_agent=True)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    lines = []
    for r in runs:
        lines.append(f"“{r.get('title') or r.get('topic')}” — {r.get('status')} (phase {r.get('phase')})")
        lines += _fmt_pipeline_config(r.get("pipelineConfig"))
        lines += _attention_lines(r)
        phase_updates = r.get("phaseUpdates")
        if phase_updates:
            lines += _fmt_phase_updates(phase_updates)
        else:
            # Fallback (older build / no phaseUpdates): the minted permanent SR links.
            lines += _fmt_sr_links(r.get("srLinks") or {})
    return _emit(body, args.json, lines or ["No active runs."])


def cmd_list(args) -> int:
    """List the account's recent researches (newest first), so the user can ask for
    any one's links or podcast BY NAME. Account-wide — EVERY research, not just the
    agent-started ones (that's `updates`, the active-only streaming view). The
    per-run links/podcast are then fetched on demand via `status` / `podcast`,
    which already resolve any of these by title."""
    code, body, runs = _fetch_runs(limit=30)
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
    code, body, runs = _fetch_runs()
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
    code, body, runs = _fetch_runs()
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
    code, body, runs = _fetch_runs()
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
    code, body, runs = _fetch_runs()
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


def cmd_skip(args) -> int:
    code, body, runs = _fetch_runs()
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
    # Phases given → tune the run's config (skip whole phases when reached).
    phases = []
    for p in args.phases:
        if p.isdigit():
            phases.append(int(p))
        elif p.lower() in _SKIP_NAMES:
            phases.append(_SKIP_NAMES[p.lower()])
        else:
            return _emit({}, args.json, [f"✗ unknown phase '{p}' (1/3/4/5 or brief/podcast/video/report)"], 1)
    code, b2 = _post(f"/research/{q}/skip", {"phases": phases})
    if code != 200:
        return _emit(b2, args.json, [f"✗ skip failed: {b2.get('error', code)}"], _fail_code(code))
    return _emit(b2, args.json, [f"✓ Will skip phase(s) {b2.get('skipped')} of “{title}” when reached."])


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
    """Show the chat agent's version AND the Super Research backend's version, each
    with a "newer available" nudge when one is published (the backend, co-located
    with the bridge, is the thing that runs research)."""
    code, body = _get("/version")
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't read versions: {body.get('error', code)}"],
                     _fail_code(code))
    agent = body.get("agent") or "?"
    backend = body.get("backend")
    a_new = body.get("agentLatest")
    b_new = body.get("backendLatest")
    lines = [f"Super Research agent    v{agent}"
             + (f"   ⬆️ v{a_new} available — say “update the agent”" if a_new else "")]
    if backend:
        lines.append(f"Super Research backend  v{backend}"
                     + (f"   ⬆️ v{b_new} available — say “update”" if b_new else ""))
    else:
        lines.append("Super Research backend  (not installed on the connected device)")
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


def cmd_update(args) -> int:
    """Update the Super Research backend on the connected device (delegates to
    `superresearch --update` there). The backend's updater runs in the
    background, so this returns right away."""
    code, body = _post("/update")
    if code != 200:
        err = body.get("error", "")
        if err == "backend_not_installed":
            msg = "Super Research isn't installed on the connected device — update it where it runs."
        else:
            msg = f"couldn't start the update: {err or code}"
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    if body.get("already"):
        cur = body.get("current") or ""
        return _emit(body, args.json,
                     [f"✓ Super Research is already up to date{(' (v' + cur + ')') if cur else ''}."])
    return _emit(body, args.json, [
        "⬆️ Updating Super Research in the background.",
        "It restarts on the new version shortly — say “version” in a bit to confirm.",
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
            "Say “update” to upgrade it, or “devices” to see/pair it.",
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

    # No phases → skip whatever the run is blocked on; phases → trim those phases.
    sk = sub.add_parser("skip", help="skip a run's current blocker, or named phases")
    sk.add_argument("phases", nargs="*")
    sk.add_argument("--run", default="", help="run title or id (default: newest active run)")
    sk.set_defaults(func=cmd_skip)

    sub.add_parser("logout", help="clear the account session").set_defaults(func=cmd_logout)

    sub.add_parser("version", aliases=["versions"],
                   help="show the agent + Super Research backend versions (+ update notices)").set_defaults(func=cmd_version)
    sub.add_parser("install", aliases=["install-backend", "setup-backend"],
                   help="install the Super Research backend on the connected device (host a BE)"
                   ).set_defaults(func=cmd_install)
    sub.add_parser("update", aliases=["upgrade"],
                   help="update the Super Research backend on the connected device").set_defaults(func=cmd_update)
    sub.add_parser("agent-update",
                   aliases=["agent-install", "update-agent", "update-skill", "upgrade-agent"],
                   help="update the chat agent itself (package + skill + bridge) to the latest"
                   ).set_defaults(func=cmd_agent_update)

    sub.add_parser(
        "arm-stream",
        help="prepare this chat's streaming watchdog (prints the cron script + name to arm)",
    ).set_defaults(func=cmd_arm_stream)
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
