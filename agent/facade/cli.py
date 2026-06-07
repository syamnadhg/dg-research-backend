"""`agent` — the Super Agent host CLI.

P0 surface: serve / login / status / logout / doctor / verify.

IMPORTANT: account operations (read researches, list devices, enqueue) go
THROUGH the running bridge, never directly. The bridge is the single owner of
the account session and the only process that refreshes the token — so a CLI
command can never rotate the refresh token out from under the live bridge.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import webbrowser
from pathlib import Path

import requests

from . import __version__, autostart, bridge, config, connect, logsetup, prefs, runview
from .session import AccountSession

log = logging.getLogger(__name__)

_OK = "✓"  # ✓
_NO = "✗"  # ✗


def _bridge_get(path: str, timeout: float = 10.0) -> tuple[int, dict] | None:
    try:
        r = requests.get(config.bridge_origin() + path, timeout=timeout)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    except requests.RequestException:
        return None


def _bridge_post(path: str, body: dict | None = None, timeout: float = 30.0) -> tuple[int, dict] | None:
    try:
        r = requests.post(config.bridge_origin() + path, json=body, timeout=timeout)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    except requests.RequestException:
        return None


def _bridge_up() -> bool:
    return _bridge_get("/healthz", timeout=3.0) is not None


# ── commands ──────────────────────────────────────────────────────────────

def cmd_serve(args: argparse.Namespace) -> int:
    # The long-running bridge writes the durable operational log; short CLI
    # commands stay console-only (configured in main()).
    logsetup.configure(verbose=getattr(args, "verbose", False), to_file=True)
    bridge.serve()
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    """Install the Super Research skill into a chat runtime (Hermes / OpenClaw)."""
    runtime = args.runtime
    if not runtime:
        found = connect.detect_runtimes()
        if len(found) == 1:
            runtime = found[0]
        elif not found:
            print(f"{_NO} No runtime detected (~/.hermes or ~/.openclaw).")
            print(f"    Specify one:  agent connect {{{'|'.join(connect.RUNTIMES)}}}")
            return 1
        else:
            print(f"{_NO} Multiple runtimes found ({', '.join(found)}) — specify one:")
            print("    agent connect <runtime>")
            return 1
    if runtime not in connect.RUNTIMES:
        print(f"{_NO} Unknown runtime '{runtime}'. Choose: {', '.join(connect.RUNTIMES)}")
        return 1
    try:
        target = connect.install(runtime, dest=Path(args.dest) if args.dest else None)
    except OSError as e:
        print(f"{_NO} install failed: {e}")
        return 1
    if not connect.verify(target):
        print(f"{_NO} install verification failed at {target}")
        return 1
    prefs.set_runtime(runtime)
    print(f"{_OK} Super Research skill installed for {runtime}:")
    print(f"     {target}")
    print("Next: start the bridge (agent serve), then run /login in your chat.")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Start it first:  agent serve")
        return 1
    if getattr(args, "remote", False):
        return _login_remote(args)
    url = config.login_origin() + "/login"
    runtime = prefs.get_runtime()
    if runtime:
        url += f"?runtime={runtime}"  # glow the connected runtime's watermark
    print(f"Opening {url} — sign in with your Super Research Google account.")
    print("(Your agent is research-only; it can never control devices.)")
    try:
        webbrowser.open(url)
    except Exception:
        print(f"Couldn't open a browser automatically — visit {url} manually.")
    return 0


def _login_remote(args: argparse.Namespace) -> int:
    """Remote device-flow sign-in (§11a): the bridge brokers via the SR web app;
    the user approves on their phone. Works without any localhost access."""
    res = _bridge_post("/login/remote/start",
                       {"runtime": (getattr(args, "runtime", "") or prefs.get_runtime() or ""),
                        "label": getattr(args, "label", "") or ""})
    if res is None or res[0] != 200:
        print(f"{_NO} couldn't start remote sign-in: {res[1] if res else 'no response'}")
        return 1
    out = res[1]
    print(f"Open this link and sign in:  {out.get('verifyUrl')}")
    print("(Sign in to Super Research on your phone, then tap Approve & connect.)")
    print("Waiting for approval… (Ctrl-C to stop)")
    deadline = time.monotonic() + float(out.get("expiresIn", 600) or 600)
    interval = config.REMOTE_POLL_INTERVAL_SECONDS
    try:
        while time.monotonic() < deadline:
            time.sleep(interval)
            pr = _bridge_post("/login/remote/poll")
            if pr is None or pr[0] != 200:
                continue  # transient — keep waiting
            st = pr[1]
            state = st.get("state")
            if state == "connected":
                print(f"{_OK} Connected as {st.get('email') or st.get('uid')}.  Try:  agent verify")
                return 0
            if state == "expired":
                print(f"{_NO} Sign-in link expired before approval. Run:  agent login --remote")
                return 1
            if state == "error":
                print(f"{_NO} Sign-in failed: {st.get('error', 'unknown error')}")
                return 1
    except KeyboardInterrupt:
        print("\nStopped waiting. The link may still be valid; re-run to resume.")
        return 1
    print(f"{_NO} Timed out waiting for approval. Run:  agent login --remote")
    return 1


def cmd_status(_args: argparse.Namespace) -> int:
    res = _bridge_get("/status")
    if res is None:
        sess = AccountSession.load()
        if sess:
            print(f"Bridge: not running.  Stored session: {sess.email or sess.uid}")
        else:
            print("Bridge: not running.  No stored session.")
        return 1
    _, st = res
    if st.get("authed"):
        print(f"Bridge: up.  Signed in as {st.get('email') or st.get('uid')}")
    else:
        print("Bridge: up.  Not signed in — run:  agent login")
    return 0


def cmd_logout(_args: argparse.Namespace) -> int:
    # Tell the bridge (if up) AND clear the store directly, so logout works
    # whether or not the bridge is running. Neither path refreshes the token.
    _bridge_post("/logout")
    sess = AccountSession.load()
    if sess:
        sess.logout()
    prefs.clear_selected_device()  # also drop the target-device pref (bridge-down path)
    print("Logged out — account session cleared.")
    return 0


def cmd_device(args: argparse.Namespace) -> int:
    """List the devices the account can reach, or switch the target device."""
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1

    if getattr(args, "device_command", None) == "use":
        res = _bridge_post("/device/select", {"deviceId": args.deviceId})
        if res is None or res[0] != 200:
            print(f"{_NO} couldn't select device: {res[1].get('error') if res else 'no response'}")
            return 1
        d = res[1].get("device", {})
        kind = "owned" if d.get("owned") else "shared"
        print(f"{_OK} Now running on: {d.get('name') or d.get('id')}  ({kind})")
        return 0

    dr = _bridge_get("/devices")
    if dr is None or dr[0] != 200:
        print(f"{_NO} list devices failed: {dr[1] if dr else 'no response'}")
        return 1
    devices = dr[1].get("devices", [])
    selected = dr[1].get("selectedDeviceId")
    if not devices:
        print("No devices reachable by this account.")
        return 0
    print(f"Devices ({len(devices)}):")
    for d in devices:
        mark = "→" if d.get("selected") else " "
        kind = "owned" if d.get("owned") else "shared"
        print(f"  {mark} {d.get('name') or d.get('id')}  ({kind})  id={d.get('id')}")
    if not selected:
        print("\nNo device selected — pick one:  agent device use <id>")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    print(f"Super Agent doctor (facade v{__version__})\n")

    print(f"  python:   {_OK} {sys.version.split()[0]}")
    for mod in ("requests", "keyring"):
        try:
            __import__(mod)
            print(f"  {mod}:{' ' * (9 - len(mod))}{_OK} importable")
        except Exception as e:
            print(f"  {mod}:{' ' * (9 - len(mod))}{_NO} {e}")

    try:
        requests.get("https://securetoken.googleapis.com", timeout=5)
        print(f"  google:   {_OK} reachable")
    except requests.RequestException as e:
        print(f"  google:   {_NO} {e}")

    # The remote-login broker (SR web app). Any HTTP response = reachable.
    try:
        requests.get(config.FE_BASE, timeout=5)
        print(f"  sr web:   {_OK} reachable ({config.FE_BASE})")
    except requests.RequestException as e:
        print(f"  sr web:   {_NO} {config.FE_BASE} — {e}")

    health = _bridge_get("/healthz")
    if health is None:
        print(f"  bridge:   {_NO} down (run: agent serve)")
        sess = AccountSession.load()
        print(f"  account:  {'stored session present — start the bridge to validate' if sess else 'not signed in'}")
        return 1
    print(f"  bridge:   {_OK} up")
    res = _bridge_get("/status")
    st = res[1] if res else {}
    if st.get("authed"):
        print(f"  account:  {_OK} {st.get('email') or st.get('uid')}")
    else:
        print(f"  account:  {_NO} not signed in (run: agent login)")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """P0 gate proof — via the bridge: read the account's researches + list
    reachable devices, and (with --enqueue) create a run a device will execute."""
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1

    rr = _bridge_get("/researches")
    if rr is None or rr[0] != 200:
        print(f"{_NO} read researches failed: {rr[1] if rr else 'no response'}")
        return 1
    researches = rr[1].get("researches", [])
    print(f"{_OK} read researches — {len(researches)} doc(s)")
    for r in researches[:5]:
        print(f"     • {r.get('title') or r.get('topic') or r.get('id')}  [{r.get('status','?')}]")

    dr = _bridge_get("/devices")
    if dr is None or dr[0] != 200:
        print(f"{_NO} list devices failed: {dr[1] if dr else 'no response'}")
        return 1
    devices = dr[1].get("devices", [])
    print(f"{_OK} reachable devices — {len(devices)}")
    for d in devices:
        owned = "owned" if d.get("owned") else "shared"
        print(f"     • {d.get('name') or d.get('id')}  ({owned})  id={d.get('id')}")

    if not args.enqueue:
        print("\nRead proof complete. To prove a device executes a run, re-run with:")
        print('  agent verify --enqueue --device <deviceId> --topic "<topic>" --yes')
        return 0

    if not args.device or not args.topic:
        print(f"{_NO} --enqueue needs --device <id> and --topic \"<topic>\"")
        return 1
    if not args.yes:
        print(f"{_NO} --enqueue starts a REAL pipeline run (P1–P3, LLM spend).")
        print("    Re-run with --yes to confirm. (Video + email are skipped for this smoke.)")
        return 1
    # Smoke config: real P1–P3 run, but skip video (P4, scarce YouTube quota)
    # and email so a verification run is light. Remove for a full run later.
    cfg = {"videoEnabled": False, "emailEnabled": False}
    res = _bridge_post("/research", {"topic": args.topic, "deviceId": args.device, "config": cfg})
    if res is None or res[0] != 200:
        print(f"{_NO} enqueue failed: {res[1] if res else 'no response'}")
        return 1
    out = res[1]
    print(f"{_OK} created run {out.get('runId')} + enqueued start (queue doc {out.get('queueId')})")
    print("     Watch it appear as an app chat and run on the device (no video/email).")
    return 0


def _err(res: tuple[int, dict] | None) -> str:
    if res and isinstance(res[1], dict):
        return res[1].get("error", str(res[1]))
    return "no response (is the bridge running?)"


def _link_url(v) -> str:
    """Links land as {url, ...} maps or bare strings — normalize to a URL."""
    if isinstance(v, dict):
        return v.get("url", "")
    return v if isinstance(v, str) else ""


def _print_run(r: dict) -> None:
    title = r.get("title") or r.get("topic") or r.get("id")
    print(f"{title}   [{r.get('status', '?')}]  phase {r.get('phase', '?')}  id={r.get('id')}")
    if r.get("summary"):
        print(f"  {r['summary']}")
    links = r.get("links")
    if isinstance(links, dict):
        for kind, v in links.items():
            url = _link_url(v)
            if url:
                print(f"  🔗 {kind}: {url}")
    for kind in ("documents", "audios"):
        items = r.get(kind)
        if isinstance(items, list) and items:
            print(f"  {kind}: {len(items)}")


def cmd_research(args: argparse.Namespace) -> int:
    """Start a run (chat /research). Returns a run id immediately."""
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1
    body: dict = {"topic": args.topic}
    if args.device:
        body["deviceId"] = args.device
    cfg: dict = {}
    if args.no_video:
        cfg["videoEnabled"] = False
    if args.no_email:
        cfg["emailEnabled"] = False
    if cfg:
        body["config"] = cfg
    res = _bridge_post("/research", body)
    if res is None or res[0] != 200:
        print(f"{_NO} couldn't start: {_err(res)}")
        return 1
    out = res[1]
    print(f"{_OK} Started run {out.get('runId')} on device {out.get('deviceId')}")
    print(f"     status:  agent run {out.get('runId')}     cancel:  agent cancel {out.get('runId')}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    """List recent runs (chat /status with no id lists; here we list)."""
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1
    rr = _bridge_get("/researches")
    if rr is None or rr[0] != 200:
        print(f"{_NO} couldn't list runs: {_err(rr)}")
        return 1
    runs = rr[1].get("researches", [])
    if not runs:
        print("No runs yet.")
        return 0
    for r in sorted(runs, key=lambda x: x.get("createdAt", 0), reverse=True)[:15]:
        print(f"  {r.get('title') or r.get('topic') or r.get('id')}  "
              f"[{r.get('status', '?')}]  phase {r.get('phase', '?')}  id={r.get('id')}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Show one run's status (chat /status [id]). No id → the most recent run."""
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1
    rid = args.runId
    if not rid:
        rr = _bridge_get("/researches")
        if rr is None or rr[0] != 200:
            print(f"{_NO} couldn't find a run: {_err(rr)}")
            return 1
        runs = rr[1].get("researches", [])
        if not runs:
            print("No runs yet.")
            return 0
        rid = max(runs, key=lambda x: x.get("createdAt", 0)).get("id")
    res = _bridge_get(f"/research/{rid}")
    if res is None or res[0] != 200:
        print(f"{_NO} {_err(res)}")
        return 1
    _print_run(res[1].get("research", {}))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Stream a run's per-phase links to the console until it finishes.

    This is the operator-facing view of the streaming a runtime cron drives:
    poll, print each NEW link + status transition, stop at a terminal status.
    """
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1
    rid = args.runId
    if not rid:
        rr = _bridge_get("/updates?limit=20")
        if rr is None or rr[0] != 200:
            print(f"{_NO} couldn't find a run: {_err(rr)}")
            return 1
        runs = rr[1].get("runs", [])
        if not runs:
            print("No runs yet.")
            return 0
        # newest active run if any, else the newest run
        active = [r for r in runs if r.get("status") in ("queued", "ongoing")]
        rid = (active[0] if active else runs[0]).get("runId")

    print(f"Watching run {rid} … (Ctrl-C to stop)")
    seen: set[tuple[str, str]] = set()  # (kind, url) — re-surface a corrected link
    last_status = None
    interval = config.STREAM_POLL_INTERVAL_SECONDS
    try:
        while True:
            res = _bridge_get(f"/research/{rid}")
            if res is None or res[0] != 200:
                print(f"{_NO} {_err(res)}")
                return 1
            r = res[1].get("research", {})
            status = r.get("status")
            if status != last_status:
                print(f"  • [{status}]  phase {r.get('phase', '?')}")
                if isinstance(status, str) and status.startswith("paused"):
                    print("    (paused — watching idles until it resumes; Ctrl-C to stop)")
                last_status = status
            for e in res[1].get("events", []):
                key = (e["kind"], e["url"])
                if key not in seen:
                    seen.add(key)
                    print(f"  🔗 {e.get('label') or e['kind']}: {e['url']}")
            if runview.is_terminal(status):
                print(f"{_OK} run {rid} {status}.")
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped watching (the run keeps going).")
        return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    """Cancel a run (chat /cancel <id>)."""
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1
    res = _bridge_post(f"/research/{args.runId}/cancel")
    if res is None or res[0] != 200:
        print(f"{_NO} cancel failed: {_err(res)}")
        return 1
    print(f"{_OK} Cancel requested for {args.runId} (device {res[1].get('deviceId')}).")
    return 0


_SKIP_NAMES = {"brief": 1, "podcast": 3, "audio": 3, "video": 4, "youtube": 4, "report": 5, "email": 5}


def cmd_skip(args: argparse.Namespace) -> int:
    """Skip phases of a run (chat /skip). Accepts phase numbers or names
    (brief=1, podcast=3, video=4, report=5)."""
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1
    phases = []
    for p in args.phases:
        if p.isdigit():
            phases.append(int(p))
        elif p.lower() in _SKIP_NAMES:
            phases.append(_SKIP_NAMES[p.lower()])
        else:
            print(f"{_NO} unknown phase '{p}' (use 1/3/4/5 or brief/podcast/video/report)")
            return 1
    res = _bridge_post(f"/research/{args.runId}/skip", {"phases": phases})
    if res is None or res[0] != 200:
        print(f"{_NO} skip failed: {_err(res)}")
        return 1
    print(f"{_OK} Will skip phase(s) {res[1].get('skipped')} on {args.runId} when reached.")
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    """Stop the running host bridge."""
    res = _bridge_post("/shutdown")
    if res is None:
        print("Bridge isn't running (nothing to stop).")
        return 0
    if res[0] == 200:
        print(f"{_OK} Bridge stopping.")
        return 0
    print(f"{_NO} couldn't stop the bridge: {_err(res)}")
    return 1


def cmd_autostart(args: argparse.Namespace) -> int:
    """Install / remove / check the logon autostart (Windows Scheduled Task)."""
    action = args.action
    fn = {"install": autostart.install, "uninstall": autostart.uninstall,
          "status": autostart.status}[action]
    ok, out = fn()
    mark = _OK if ok else _NO
    verb = {"install": "installed", "uninstall": "removed", "status": "status"}[action]
    print(f"{mark} autostart {verb}" + (f":\n{out}" if out else ""))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    # -v/--verbose must work both before and after the subcommand
    # (agent -v serve  ==  agent serve -v). argparse stores a sub-parser flag and
    # a top-level flag of the same dest into ONE attribute, and the sub-parser's
    # default would clobber a value parsed at the top level — so the top-level
    # copy uses a DISTINCT dest and main() ORs the two together.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true",
                        help="verbose (DEBUG) logging")

    p = argparse.ArgumentParser(prog="agent", description="Super Agent host bridge CLI")
    p.add_argument("-v", "--verbose", dest="verbose_global", action="store_true",
                   help="verbose (DEBUG) logging (also accepted after the subcommand)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    cn = sub.add_parser("connect", parents=[common],
                        help="install the SR skill into a chat runtime (hermes/openclaw)")
    cn.add_argument("runtime", nargs="?", help="hermes or openclaw (auto-detected if omitted)")
    cn.add_argument("--dest", help="explicit install dir (default: the runtime's skills dir)")
    cn.set_defaults(func=cmd_connect)

    sub.add_parser("serve", parents=[common], help="start the host bridge (blocking)").set_defaults(func=cmd_serve)
    lg = sub.add_parser("login", parents=[common],
                        help="connect your account (local page, or --remote device flow)")
    lg.add_argument("--remote", action="store_true",
                    help="remote sign-in via the SR web app (approve on your phone)")
    lg.add_argument("--runtime", help="runtime hint shown on the approval page (hermes/openclaw)")
    lg.add_argument("--label", help="agent label shown on the approval page")
    lg.set_defaults(func=cmd_login)
    sub.add_parser("status", parents=[common], help="show bridge + session status").set_defaults(func=cmd_status)

    dv = sub.add_parser("device", parents=[common],
                        help="list / switch the devices your account can reach")
    dv.set_defaults(func=cmd_device, device_command=None)
    dvsub = dv.add_subparsers(dest="device_command")
    dvsub.add_parser("list", parents=[common], help="list reachable devices").set_defaults(func=cmd_device)
    use = dvsub.add_parser("use", parents=[common], help="select the device to run on")
    use.add_argument("deviceId", help="deviceId to run on (from `agent device`)")
    use.set_defaults(func=cmd_device)

    sub.add_parser("logout", parents=[common], help="clear the account session").set_defaults(func=cmd_logout)
    sub.add_parser("doctor", parents=[common], help="run health + connectivity diagnostics").set_defaults(func=cmd_doctor)

    rs = sub.add_parser("research", parents=[common], help="start a research run")
    rs.add_argument("topic", help="the research topic")
    rs.add_argument("--device", help="deviceId to run on (else your selected/sole device)")
    rs.add_argument("--no-video", action="store_true", help="skip the video phase")
    rs.add_argument("--no-email", action="store_true", help="skip the email delivery")
    rs.set_defaults(func=cmd_research)

    sub.add_parser("runs", parents=[common], help="list recent runs").set_defaults(func=cmd_runs)

    rn = sub.add_parser("run", parents=[common], help="show a run's status (no id = most recent)")
    rn.add_argument("runId", nargs="?", help="run id (default: most recent)")
    rn.set_defaults(func=cmd_run)

    wt = sub.add_parser("watch", parents=[common],
                        help="stream a run's per-phase links until it finishes")
    wt.add_argument("runId", nargs="?", help="run id (default: newest active run)")
    wt.set_defaults(func=cmd_watch)

    cn = sub.add_parser("cancel", parents=[common], help="cancel a run")
    cn.add_argument("runId", help="run id to cancel")
    cn.set_defaults(func=cmd_cancel)

    sk = sub.add_parser("skip", parents=[common],
                        help="skip phases of a run (1/3/4/5 or brief/podcast/video/report)")
    sk.add_argument("runId")
    sk.add_argument("phases", nargs="+", help="phase numbers or names to skip")
    sk.set_defaults(func=cmd_skip)

    sub.add_parser("stop", parents=[common], help="stop the running host bridge").set_defaults(func=cmd_stop)

    au = sub.add_parser("autostart", parents=[common],
                        help="manage logon autostart (Windows Scheduled Task)")
    au.add_argument("action", choices=["install", "uninstall", "status"])
    au.set_defaults(func=cmd_autostart)

    v = sub.add_parser("verify", parents=[common],
                       help="P0 gate proof: read researches + list devices (+ optional enqueue)")
    v.add_argument("--enqueue", action="store_true", help="actually create + enqueue a run (starts a real pipeline)")
    v.add_argument("--yes", action="store_true", help="confirm the real enqueue (required with --enqueue)")
    v.add_argument("--device", help="deviceId to run on (with --enqueue)")
    v.add_argument("--topic", help="research topic (with --enqueue)")
    v.set_defaults(func=cmd_verify)
    return p


def _force_utf8_output() -> None:
    # Windows consoles default to cp1252, which can't encode ✓/✗/— and would
    # crash with UnicodeEncodeError. Reconfigure to UTF-8 (errors='replace' so
    # a legacy terminal degrades gracefully instead of crashing).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)
    # Merge the before- and after-subcommand -v positions into args.verbose so
    # every command (incl. cmd_serve, which re-configures with to_file=True)
    # sees one truth.
    args.verbose = getattr(args, "verbose", False) or getattr(args, "verbose_global", False)
    # Short CLI commands log to console only; `serve` adds the durable file log.
    logsetup.configure(verbose=args.verbose, to_file=False)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
