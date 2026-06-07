#!/usr/bin/env python3
"""sr.py — the Super Research skill's thin client to the host bridge.

A chat runtime (Hermes / OpenClaw) runs this via `exec` and relays the output to
the user. It is intentionally STANDALONE and dependency-free (stdlib urllib
only) so it can live in the runtime's skills dir without the facade installed.

It only ever talks to the loopback bridge (127.0.0.1:<port>) that `agent serve`
runs; it never touches Firestore, tokens, or the network directly. Every
account action is the bridge's responsibility (single-owner session).

Commands (mirror the chat slash commands):
  login            start a remote sign-in → prints a code + link to relay
  login-wait       poll until the sign-in is approved / expires
  status-account   is the bridge up + signed in?
  devices          list reachable devices
  device-use <id>  choose the device runs go to
  research <topic> start a run (--device <id> to override the selected device)
  status [id]      a run's progress + links (no id = most recent)
  podcast [id]     download a run's audio → a local file to send as native audio
  updates          active runs + their current links (for the streaming cron)
  cancel <id>      stop a run
  logout           clear the account session
  help             this list

Add --json to print the raw bridge response (the streaming cron uses
`sr.py --json updates`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

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
        return 0, {"error": f"bridge unreachable ({e.reason}) — is `agent serve` running?"}


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


def _fmt_links(events: list) -> list[str]:
    out = []
    for e in events or []:
        label = e.get("label") or e.get("kind")
        out.append(f"  🔗 {label}: {e.get('url')}")
    return out


# ── commands ────────────────────────────────────────────────────────────────

def cmd_login(args) -> int:
    code, body = _post("/login/remote/start", {"runtime": args.runtime or "", "label": args.label or ""})
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't start sign-in: {body.get('error', code)}"], _fail_code(code))
    return _emit(body, args.json, [
        f"Open this link and sign in:  {body.get('verifyUrl')}",
        "(Sign in to Super Research on your phone, then tap Approve & connect.)",
        "Then run:  login-wait",
    ])


def cmd_login_wait(args) -> int:
    code, body = _post("/login/remote/poll")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    state = body.get("state")
    msg = {
        "connected": f"✓ Connected as {body.get('email') or body.get('uid')}.",
        "pending": "… still waiting for approval — run login-wait again.",
        "expired": "✗ The sign-in link expired — run login again.",
        "error": f"✗ Sign-in failed: {body.get('error', 'unknown')}",
    }.get(state, f"state: {state}")
    return _emit(body, args.json, [msg])


def cmd_status_account(args) -> int:
    code, body = _get("/status")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if body.get("authed"):
        return _emit(body, args.json, [f"✓ Signed in as {body.get('email') or body.get('uid')}"])
    return _emit(body, args.json, ["Not signed in — run login."])


def cmd_devices(args) -> int:
    code, body = _get("/devices")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    devices = body.get("devices", [])
    selected = body.get("selectedDeviceId")
    if not devices:
        return _emit(body, args.json, ["No devices reachable by this account."])
    lines = ["Devices:"]
    for d in devices:
        mark = "→" if d.get("selected") else " "
        kind = "owned" if d.get("owned") else "shared"
        lines.append(f"  {mark} {d.get('name') or d.get('id')}  ({kind})  id={d.get('id')}")
    if not selected:
        lines.append("Pick one:  device-use <id>")
    return _emit(body, args.json, lines)


def cmd_device_use(args) -> int:
    code, body = _post("/device/select", {"deviceId": args.deviceId})
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't select device: {body.get('error', code)}"], _fail_code(code))
    d = body.get("device", {})
    kind = "owned" if d.get("owned") else "shared"
    return _emit(body, args.json, [f"✓ Now running on {d.get('name') or d.get('id')} ({kind})."])


def cmd_research(args) -> int:
    payload: dict = {"topic": args.topic}
    if args.device:
        payload["deviceId"] = args.device
    cfg = {}
    if args.no_video:
        cfg["videoEnabled"] = False
    if args.no_email:
        cfg["emailEnabled"] = False
    if cfg:
        payload["config"] = cfg
    code, body = _post("/research", payload)
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't start: {body.get('error', code)}"], _fail_code(code))
    return _emit(body, args.json, [
        f"🚀 Started “{args.topic}” — run {body.get('runId')} on device {body.get('deviceId')}.",
        f"Track it:  status {body.get('runId')}",
    ])


def cmd_status(args) -> int:
    rid = args.runId
    if not rid:
        code, body = _get("/updates?limit=20")
        if code != 200:
            return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
        runs = body.get("runs", [])
        if not runs:
            return _emit(body, args.json, ["No runs yet."])
        active = [r for r in runs if r.get("status") in ("queued", "ongoing")]
        rid = (active[0] if active else runs[0]).get("runId")
    code, body = _get(f"/research/{urllib.parse.quote(rid, safe='')}")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    r = body.get("research", {})
    lines = [f"“{r.get('title') or r.get('topic') or rid}” — {r.get('status', '?')} (phase {r.get('phase', '?')})"]
    lines += _fmt_links(body.get("events", []))
    return _emit(body, args.json, lines)


def cmd_podcast(args) -> int:
    rid = args.runId
    if not rid:
        code, body = _get("/updates?limit=20")
        if code != 200:
            return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
        runs = body.get("runs", [])
        if not runs:
            return _emit(body, args.json, ["No runs yet."])
        # The podcast audio is a late-phase artifact — prefer the newest run that
        # already HAS audio over the newest active run (which usually has none yet).
        with_audio = [r for r in runs
                      if any(lk.get("kind") == "audio_file" for lk in r.get("links", []))]
        rid = (with_audio[0] if with_audio else runs[0]).get("runId")
    # The bridge downloads the audio to a local file (a long audio overview can
    # take a few seconds) → allow more time than the default request timeout.
    code, body = _get(f"/research/{urllib.parse.quote(rid, safe='')}/podcast", timeout=180)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    title = body.get("title") or "Podcast"
    name = body.get("filename") or f"{title}.m4a"
    return _emit(body, args.json, [
        f"🎧 Podcast ready: “{title}”",
        f"Send this file as a native audio / voice message named “{name}” "
        "(attach the file — don’t paste the path):",
        f"  {body.get('localPath')}",
    ])


def cmd_updates(args) -> int:
    path = "/updates?active=1" if args.active else "/updates"
    code, body = _get(path)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    runs = body.get("runs", [])
    lines = []
    for r in runs:
        lines.append(f"“{r.get('title') or r.get('topic')}” — {r.get('status')} (phase {r.get('phase')})")
        lines += _fmt_links(r.get("links", []))
    return _emit(body, args.json, lines or ["No active runs."])


def cmd_cancel(args) -> int:
    rid = urllib.parse.quote(args.runId, safe="")
    code, body = _post(f"/research/{rid}/cancel")
    if code != 200:
        return _emit(body, args.json, [f"✗ cancel failed: {body.get('error', code)}"], _fail_code(code))
    return _emit(body, args.json, [f"✓ Cancel requested for {args.runId}."])


_SKIP_NAMES = {"brief": 1, "podcast": 3, "audio": 3, "video": 4, "youtube": 4, "report": 5, "email": 5}


def cmd_skip(args) -> int:
    phases = []
    for p in args.phases:
        if p.isdigit():
            phases.append(int(p))
        elif p.lower() in _SKIP_NAMES:
            phases.append(_SKIP_NAMES[p.lower()])
        else:
            return _emit({}, args.json, [f"✗ unknown phase '{p}' (1/3/4/5 or brief/podcast/video/report)"], 1)
    rid = urllib.parse.quote(args.runId, safe="")
    code, body = _post(f"/research/{rid}/skip", {"phases": phases})
    if code != 200:
        return _emit(body, args.json, [f"✗ skip failed: {body.get('error', code)}"], _fail_code(code))
    return _emit(body, args.json, [f"✓ Will skip phase(s) {body.get('skipped')} when reached."])


def cmd_logout(args) -> int:
    code, body = _post("/logout")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    return _emit(body, args.json, ["✓ Logged out — account session cleared."])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sr", description="Super Research skill client")
    p.add_argument("--json", action="store_true", help="print the raw bridge JSON")
    sub = p.add_subparsers(dest="command", required=True)

    lg = sub.add_parser("login", help="start a remote sign-in")
    lg.add_argument("--runtime", default="")
    lg.add_argument("--label", default="")
    lg.set_defaults(func=cmd_login)

    sub.add_parser("login-wait", help="poll until sign-in completes").set_defaults(func=cmd_login_wait)
    sub.add_parser("status-account", help="bridge + session status").set_defaults(func=cmd_status_account)
    sub.add_parser("devices", help="list reachable devices").set_defaults(func=cmd_devices)

    du = sub.add_parser("device-use", help="select the target device")
    du.add_argument("deviceId")
    du.set_defaults(func=cmd_device_use)

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

    cn = sub.add_parser("cancel", help="cancel a run")
    cn.add_argument("runId")
    cn.set_defaults(func=cmd_cancel)

    sk = sub.add_parser("skip", help="skip phases of a run")
    sk.add_argument("runId")
    sk.add_argument("phases", nargs="+")
    sk.set_defaults(func=cmd_skip)

    sub.add_parser("logout", help="clear the account session").set_defaults(func=cmd_logout)
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
