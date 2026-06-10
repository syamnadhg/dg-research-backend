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

from . import __version__, autostart, branding, bridge, config, connect, logsetup, prefs, runview
from . import branding as b
from .firestore_rest import FirestoreRest
from .session import AccountSession

log = logging.getLogger(__name__)

_OK = "✓"  # ✓
_NO = "✗"  # ✗


def _runtime_mark(target: connect.Target) -> str:
    """Branded chip for a detected runtime (icon + brand-tinted name + where)."""
    meta = connect.RUNTIME_META[target.runtime]
    return b.brand_mark(meta["icon"], meta["rgb"], meta["label"], f"· {target.where}")


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
    # Validate the /healthz body carries the bridge marker ({ok, version}) — not
    # just ANY HTTP response — so a foreign server squatting :9876 (possible under
    # WSL mirrored networking) isn't mistaken for the bridge.
    res = _bridge_get("/healthz", timeout=3.0)
    return bool(res and isinstance(res[1], dict) and "version" in res[1])


def _bridge_authed() -> bool:
    """Whether the bridge currently holds a signed-in account session (the real
    auth state, per /status) — not merely 'a sign-in was started'."""
    res = _bridge_get("/status")
    return bool(res and res[1].get("authed"))


# ── commands ──────────────────────────────────────────────────────────────

def cmd_serve(args: argparse.Namespace) -> int:
    # The long-running bridge writes the durable operational log; short CLI
    # commands stay console-only (configured in main()).
    logsetup.configure(verbose=getattr(args, "verbose", False), to_file=True)
    # Foreground serve — nudge toward the always-up background mode unless it's
    # already pinned. (When autostart launches serve windowless this is a no-op:
    # the task exists, so is_installed() is True and the tip is skipped.)
    if not autostart.is_installed():
        b.dim("Tip: keep it always-up (background + on login)  →  "
              "python research.py agent resurrect")
    bridge.serve()
    return 0


# Chat channels Super Research reaches, shown as a row under the header. The
# vector glyphs (✆ ✈ ☎) take the brand tint; 💬 is an emoji and stays native.
_CHANNELS = [
    ("WhatsApp", "✆", (37, 211, 102)),
    ("Telegram", "✈", (34, 158, 217)),
    ("iMessage", "💬", (52, 199, 89)),
    ("Twilio", "☎", (242, 47, 70)),
]


def _choose_target(targets: list[connect.Target]) -> connect.Target | None:
    """Step 1's chooser: pick a runtime (numbered, when >1) then CONFIRM it with a
    'Continue with X?' prompt — so even a single detected runtime is an explicit
    choice. Returns the chosen Target, or None to cancel (Ctrl-C / EOF /
    out-of-range / a 'no' at the confirm)."""
    if len(targets) > 1:
        for i, t in enumerate(targets, 1):
            print(f"     {b.c(branding._ACCENT + branding._BOLD, str(i))}  {_runtime_mark(t)}")
        ans = b.ask("Pick a runtime [1]:", cancel_on_interrupt=True)
        if ans is None:
            return None
        try:
            idx = int(ans or "1")
        except ValueError:
            return None
        if not (1 <= idx <= len(targets)):
            return None
        chosen = targets[idx - 1]
    else:
        chosen = targets[0]
    if not b.confirm(f"Continue with {_runtime_mark(chosen)}?", default=True):
        return None
    return chosen


def cmd_connect(args: argparse.Namespace) -> int:
    """Connect a chat runtime (Hermes / OpenClaw): choose it, install the Super
    Research skill where it lives + make it reachable, optionally pin the
    background bridge, and optionally sign in. Branded, interactive 4-step flow."""
    b.header("nexus", "link Super Research to chat", tagline_color=branding._BOLD + branding._ACCENT)
    b.channels(_CHANNELS)
    b.step_arc(["Detect + choose", "Install", "Run on startup", "Sign in"])

    explicit = args.runtime
    if explicit and explicit not in connect.RUNTIMES:
        b.no(f"Unknown runtime '{explicit}'. Choose: {', '.join(connect.RUNTIMES)}")
        return 1

    # ── [1/4] Detect + choose ────────────────────────────────────────────────
    b.step(1, 4, "Detect + choose")
    b.dim(f"Bridge runs here · {connect.host_os_label()}  (alongside the Super Research backend).")
    targets = connect.detect_targets()
    if explicit:
        matches = [t for t in targets if t.runtime == explicit]
        targets = matches or [connect.Target(explicit, "local", Path.home())]
        if not matches:
            b.dim(f"{explicit} not detected — will install at the default path on this host.")
    if not targets:
        b.no("No chat runtime found (looked for ~/.hermes, ~/.openclaw on this host and in WSL).")
        b.dim("Install Hermes or OpenClaw first, then re-run:  python research.py agent connect")
        b.dim("A runtime inside a container or a separate VM isn't auto-detected — and a")
        b.dim("  loopback-only bridge needs host networking / a published port to reach it;")
        b.dim("  point connect at it explicitly with  --dest <path-to-skills-dir>  if so.")
        return 1
    for t in targets:
        b.ok(f"Found {_runtime_mark(t)}")
    chosen = _choose_target(targets)
    if chosen is None:
        b.dim("Cancelled — nothing was changed.")
        return 1

    # ── [2/4] Install the skill + make it reachable ──────────────────────────
    b.step(2, 4, "Install the skill")
    target = _install_step(chosen, Path(args.dest) if args.dest else None)
    if target is None:
        return 1  # _install_step already printed the reason (declined / failed)
    # Reachability runs AFTER the copy: a WSL `wsl --shutdown` would unmount
    # \\wsl.localhost and corrupt an in-flight install.
    print()
    _ensure_reachable(chosen)

    # ── [3/4] Run on startup ──────────────────────────────────────────────────
    b.step(3, 4, "Run on startup")
    startup_pinned = _startup_step()

    # ── [4/4] Sign in ─────────────────────────────────────────────────────────
    b.step(4, 4, "Sign in")
    # Show 'logout' (switch account) in the closing card when sign-in was STARTED
    # here OR the bridge is already authed — never the redundant 'login' the user
    # just chose to do. (A browser sign-in completes async; choosing it counts.)
    started = _signin_step()
    logged_in = started or _bridge_authed()

    print()
    b.line(b.c(branding._BOLD + branding._ACCENT, "Connected.")
           + b.c(branding._DIM, "  One more step in chat: run  /reload-skills  so  /sr  registers."))
    b.next_grouped(_connect_next(logged_in=logged_in, startup_pinned=startup_pinned))
    return 0


def _record_runtime(chosen: connect.Target) -> None:
    """Persist the connected runtime + WHERE it landed, so revoke/disconnect can
    target a WSL install precisely."""
    prefs.set_runtime(chosen.runtime, home=str(chosen.home),
                      location=chosen.location, distro=chosen.distro)


def _install_step(chosen: connect.Target, dest_override: Path | None) -> Path | None:
    """[2/4] Install (or keep) the skill. Returns the installed dir, or None if the
    user declined an install that isn't already present (→ caller aborts)."""
    existing = dest_override or chosen.dest
    if connect.verify(existing):
        b.dim(f"A Super Research skill is already installed at:\n     {existing}")
        if not b.confirm("Reinstall (refresh to the latest)?", default=False):
            b.dim("Kept the existing skill.")
            _record_runtime(chosen)
            return existing
    elif not b.confirm(f"Install the skill into {_runtime_mark(chosen)}?", default=True):
        b.warn("Skipped — without the skill the chat runtime won't have the /sr- commands.")
        return None
    try:
        target = connect.install(chosen.runtime, dest=dest_override, home=chosen.home)
    except OSError as e:
        b.no(f"Install failed: {e}")
        return None
    if not connect.verify(target):
        b.no(f"Install verification failed at {target}")
        return None
    _record_runtime(chosen)
    b.ok("Skill installed")
    b.dim(f"  {target}")
    return target


def _startup_step() -> bool:
    """[3/4] Offer to pin + start the background bridge so it returns after a
    reboot — a Scheduled Task (Windows), systemd --user unit (Linux), or launchd
    LaunchAgent (macOS). Returns True if it ends up pinned. Degrades cleanly with a
    serve hint on an OS where pinning isn't implemented, so the flow never dead-ends."""
    if not autostart.supported():
        b.warn(f"Run-on-startup pinning isn't available on this host ({connect.host_os_label()}).")
        b.dim("Start the bridge yourself:  python research.py agent serve")
        return False
    b.dim(f"Pins a background bridge that starts on every login (a {autostart.kind_label()}).")
    if not b.confirm("Run on startup? (background, every login)", default=True):
        b.dim("Skipped — start it yourself when ready (see Next).")
        return False
    ok, out = autostart.install()
    if not ok:
        b.warn(f"Couldn't pin startup: {out}")
        b.dim("Start it yourself:  python research.py agent serve")
        return False
    started, serr = autostart.start_detached()
    if started:
        b.ok(f"Pinned to startup ({autostart.kind_label()}) + started in the background.")
    else:
        b.warn(f"Pinned to startup, but couldn't start it now: {serr}")
        b.dim("It starts at your next login (or run: python research.py agent serve).")
    return True


def _signin_step() -> bool:
    """[4/4] Optional sign-in on the SR web app (superresearch.io) — the SAME page
    `/sr login` uses, so it's consistent and works from any device. Blocks until
    approved, so it returns True only when the account is ACTUALLY signed in. Needs
    the bridge up (it brokers the session); if it isn't, point at starting it first."""
    if not _bridge_up():
        b.dim("Bridge isn't running yet — start it first, then sign in:")
        b.dim("  python research.py agent serve   (or: agent resurrect)")
        b.dim("then:  agent login   (or  /sr login  from your chat).")
        return False
    if not b.confirm("Sign in now? (opens Super Research in your browser)", default=True):
        b.dim("Skipped — sign in later with  /sr login  in chat  (or: agent login).")
        return False
    state = _remote_signin(open_browser=True)
    if state == "connected":
        return True
    if state == "start-failed":
        b.dim("Web sign-in unreachable right now — host-local fallback:  agent login --local")
    else:
        b.dim("Finish sign-in later:  /sr login  in chat  (or: agent login).")
    return False


def _connect_next(*, logged_in: bool, startup_pinned: bool) -> list[tuple[str, list[tuple[str, str]]]]:
    """Closing 'Next' actions, split into terminal commands vs in-chat slash
    commands, and varied by what the user chose (sign-in + startup state)."""
    p = "python research.py agent "
    terminal: list[tuple[str, str]] = []
    if logged_in:
        terminal.append((p + "logout", "sign out / switch the account the agent uses"))
    else:
        terminal.append((p + "login", "sign in your account (local browser)"))
    if not startup_pinned:
        terminal.append((p + "serve", "start the bridge in this terminal"))
        terminal.append((p + "resurrect", "start it + run on startup"))
    terminal.append((p + "status", "check the bridge + session"))
    terminal.append((p + "retire", "stop + unpin the startup bridge"))
    terminal.append((p + "disconnect", "remove the skill + sign out"))
    terminal.append((p + "--help", "all agent commands"))

    chat: list[tuple[str, str]] = [
        ("/reload-skills", "run ONCE in chat so the new /sr command registers"),
    ]
    if not logged_in:
        chat.append(("/sr login", "sign in (approve on your phone)"))
    chat.append(("/sr", "welcome + everything you can do"))
    return [("in this terminal", terminal), ("in your chat (Hermes / OpenClaw)", chat)]


def _ensure_reachable(target: connect.Target) -> None:
    """Make sure the chosen runtime can reach the bridge over loopback.

    One rule, every platform: the runtime must share the bridge's loopback.
      • co-located (same OS as the bridge) → shares loopback, nothing to do.
      • WSL runtime + Windows bridge → separate net namespace → offer the
        mirrored-networking auto-fix.
    (A runtime on a *different machine* can't reach a loopback-only bridge at all
    — unsupported by design; detect_targets only ever finds local/WSL installs.)"""
    if target.location == "wsl":
        _ensure_wsl_networking()
        return
    label = connect.RUNTIME_META[target.runtime]["label"]
    # "local" means same host filesystem — which USUALLY means same network
    # namespace (shared loopback), but not always: a runtime in a container/VM
    # that bind-mounts this home looks local yet can't reach the host loopback.
    # Don't over-promise. If the bridge host itself is containerized, say so plainly.
    if connect.looks_containerized():
        b.warn(f"This bridge host looks containerized — its loopback (127.0.0.1:{config.BRIDGE_PORT}) "
               "is scoped to the container.")
        b.dim(f"{label} can reach it only if it shares this container's network "
              "(host networking / a published port).")
        return
    b.ok(f"{label} is on this {connect.host_os_label()} host — it shares the bridge's "
         "loopback, no network setup needed.")
    b.dim(f"(If {label} actually runs in a container or VM, it needs host networking or a")
    b.dim(f" published port to reach 127.0.0.1:{config.BRIDGE_PORT} — same-OS alone isn't enough.)")


def _warn_shared_localhost() -> None:
    """Informed consent before enabling mirrored networking: it SHARES localhost
    between Windows and WSL, so a Windows process on a port blocks a WSL service
    from that same port (the #225 WhatsApp break), and applying it bounces all WSL
    apps. Names any common service port a Windows process is already squatting so
    the user can resolve it BEFORE a WSL chat service silently fails to bind."""
    b.dim("Heads up — mirrored networking SHARES localhost between Windows and WSL:")
    b.dim("  • a Windows process on a port then BLOCKS a WSL service from that same")
    b.dim("    port (a stray Windows :3000 dev server can knock out a WSL chat bridge);")
    b.dim("  • applying it needs  wsl --shutdown , which briefly stops ALL your WSL")
    b.dim("    apps (Hermes / WhatsApp / etc.) — they reconnect afterwards.")
    # Scan the common service ports AND the bridge's OWN port — under mirrored
    # networking a Windows holder of :9876 would block the bridge's bind too.
    owners = connect.windows_port_owners(connect.COMMON_SHARED_PORTS + (config.BRIDGE_PORT,))
    if owners:
        b.warn("Windows is already holding these ports — a WSL service can't share them once mirrored:")
        for port, pid in sorted(owners.items()):
            tag = "  ← the bridge's own port" if port == config.BRIDGE_PORT else ""
            b.dim(f"    • port {port}  →  Windows PID {pid}   "
                  f"(identify:  tasklist /FI \"PID eq {pid}\"){tag}")
        b.dim("  If your chat runtime uses one of these, free it on Windows or move that")
        b.dim("  WSL service to another port first.")


def _ensure_wsl_networking() -> None:
    """WSL runtime prerequisite: the bridge runs on Windows and binds loopback, so
    a WSL chat reaches it ONLY with WSL "mirrored" networking. If it's off, WARN
    about the shared-localhost consequence (+ flag Windows port-squatters), then
    offer to write it into %USERPROFILE%\\.wslconfig (Y), then — since the change
    needs a WSL restart — offer to run `wsl --shutdown` (default NO: it closes
    every WSL session, including the runtime just connected). Consent-gated."""
    if connect.mirrored_networking_enabled():
        b.ok("WSL mirrored networking is on — your WSL chat can reach the bridge.")
        return
    b.warn("WSL chat reaches this Windows bridge over loopback ONLY with mirrored networking.")
    _warn_shared_localhost()
    if not b.confirm("Enable mirrored networking now? (writes  %USERPROFILE%\\.wslconfig )", default=True):
        b.dim("Skipped. Enable later: add  networkingMode=mirrored  under [wsl2] in")
        b.dim("  %USERPROFILE%\\.wslconfig , then  wsl --shutdown   (or re-run agent connect).")
        return
    try:
        changed, path = connect.enable_mirrored_networking()
    except OSError as e:
        b.no(f"Couldn't write .wslconfig: {e}")
        b.dim("Add  networkingMode=mirrored  under [wsl2] manually, then  wsl --shutdown .")
        return
    b.ok(f"{'Enabled' if changed else 'Already set'} networkingMode=mirrored   ({path})")
    if not changed:
        # Configured but a prior enable hasn't been applied yet — still nudge the
        # restart (mirrored_networking_enabled() read False to get us here).
        b.dim("Configured already; WSL just needs to restart to apply it.")
    else:
        b.dim("WSL must restart for this to take effect.")
    if b.confirm("Run  wsl --shutdown  now? (closes all WSL sessions)", default=False):
        ok, msg = connect.wsl_shutdown()
        if ok:
            b.ok("WSL is shutting down — it comes back with mirrored networking on next use.")
            b.dim("Relaunch your chat runtime in WSL, then sign in with  /sr-login .")
        else:
            b.warn(f"Couldn't run wsl --shutdown: {msg}")
            b.dim("Run it yourself, then verify:  python research.py agent doctor")
    else:
        b.dim("Run  wsl --shutdown  yourself, then verify:  python research.py agent doctor")
    # Diagnostic breadcrumb for the exact #225 failure mode.
    b.dim("If a WSL chat service doesn't reconnect after the restart, a Windows process may")
    b.dim("  be holding its port (mirrored shares localhost) — check:  netstat -ano | findstr :<port>")


def _disconnect_pairs(explicit: str | None,
                      dest_override: Path | None) -> list[tuple[str, Path | None]]:
    """The (runtime, home) pairs `disconnect` should clean.

    With ``--dest`` it's a single explicit dir. Otherwise: every detected install
    (Windows + WSL), plus the prefs-recorded install (covers a WSL home that
    isn't currently mounted/detected), deduped. ``home=None`` means the Windows
    default path."""
    if dest_override:
        rt = explicit or prefs.get_runtime() or next(iter(connect.RUNTIMES))
        return [(rt, None)]
    pairs: list[tuple[str, Path | None]] = []
    seen: set[tuple[str, str]] = set()

    def _add(rt: str, home: Path | None) -> None:
        key = (rt, str(home) if home else "")
        if key not in seen:
            seen.add(key)
            pairs.append((rt, home))

    for t in connect.detect_targets():
        if explicit and t.runtime != explicit:
            continue
        _add(t.runtime, t.home)
    rec_rt, rec_home = prefs.get_runtime(), prefs.get_runtime_home()
    if rec_rt and rec_rt in connect.RUNTIMES and (not explicit or rec_rt == explicit):
        _add(rec_rt, Path(rec_home) if rec_home else None)
    return pairs


def cmd_disconnect(args: argparse.Namespace) -> int:
    """Full teardown — the CLI twin of the app's Revoke: remove the skill from
    the runtime AND sign out. (A session with no skill is dead weight, so the two
    go together.) The background bridge is left installed — use `agent retire` to
    also stop + unpin it."""
    b.header("solvo", "disconnect from chat", tagline_color=branding._BOLD + branding._RED)
    explicit = args.runtime
    if explicit and explicit not in connect.RUNTIMES:
        b.no(f"Unknown runtime '{explicit}'. Choose: {', '.join(connect.RUNTIMES)}")
        return 1
    dest_override = Path(args.dest) if args.dest else None

    # ── [1/2] Remove the skill ────────────────────────────────────────────────
    b.step(1, 2, "Remove the skill")
    removed_any = False
    for rt, home in _disconnect_pairs(explicit, dest_override):
        try:
            removed = connect.uninstall(rt, dest=dest_override, home=home)
        except (OSError, ValueError) as e:
            b.warn(f"{rt}: couldn't remove skill ({e})")
            continue
        if removed:
            where = f"  ({home})" if home else ""
            b.ok(f"Removed the Super Research skill from {rt}{where}")
            removed_any = True
    if not removed_any:
        b.dim("No Super Research skill was installed (nothing to remove).")

    # ── [2/2] Sign out ────────────────────────────────────────────────────────
    b.step(2, 2, "Sign out")
    if _logout_session():
        b.ok("Signed out — account session cleared.")
    else:
        b.dim("No account session was signed in.")

    # Forget the recorded runtime so status stops claiming a now-skill-less runtime
    # and a bare `agent` re-onboards via connect — but only when THIS disconnect
    # covered it (a `disconnect openclaw` while hermes is recorded leaves hermes).
    rec_rt = prefs.get_runtime()
    if rec_rt and (not explicit or explicit == rec_rt):
        prefs.clear_runtime()

    # Offer to also tear down the background bridge (the `retire` axis) so a single
    # `disconnect` is a complete "I'm done" cleanup. Consent-gated + default Yes:
    # stopping a process + removing an OS autostart entry is heavier than deleting a
    # skill file (the user should SEE it happen), and a re-`connect` rebuilds it
    # anyway (install + pin + sign-in) — so keeping it serves only an immediate
    # re-connect (the `n` path). Ctrl-C → confirm() is False → bridge left running
    # (safe). Skip the prompt entirely when there's nothing to tear down.
    kept_bridge = False  # set only if the user DECLINED tearing down a running bridge
    if autostart.is_installed() or _bridge_up():
        print()
        if b.confirm("Also stop the background bridge + remove it from startup?", default=True):
            _retire_bridge()
        else:
            kept_bridge = True
            b.dim("Left the background bridge running (it returns on login).")

    # Suggest `retire` ONLY when a running bridge was deliberately kept — never when
    # it was just torn down, and never when there was nothing to tear down (a stale
    # 'retire' hint when the bridge is already gone reads as unfinished cleanup).
    nexts = [("python research.py agent connect", "reconnect a runtime")]
    if kept_bridge:
        nexts.append(("python research.py agent retire", "stop + unpin the background bridge"))
    b.next_actions(nexts)
    return 0


def cmd_resurrect(args: argparse.Namespace) -> int:
    """Pin the bridge to login + start it in the background now (the agent twin of
    the backend `--resurrect`) — a Scheduled Task (Windows), systemd --user unit
    (Linux), or launchd LaunchAgent (macOS)."""
    b.header("resurgam", "rise + run on every login", tagline_color=branding._BOLD + branding._BRIGHT)
    # Graceful on an OS where pinning isn't implemented: don't dead-end — point at
    # `agent serve` instead of erroring out under a "run on every login" banner.
    if not autostart.supported():
        b.warn(f"Run-on-startup pinning isn't available on this host ({connect.host_os_label()}).")
        b.dim("Run the bridge in this terminal instead:  python research.py agent serve")
        return 0
    ok, out = autostart.install()
    if not ok:
        b.no(f"Couldn't pin startup: {out}")
        b.dim("Run it yourself:  python research.py agent serve")
        return 1
    b.ok(f"Pinned to login ({autostart.kind_label()})")
    started, serr = autostart.start_detached()
    if started:
        b.ok("Bridge started in the background")
    else:
        b.warn(f"Pinned, but couldn't start it now: {serr}")
        b.dim("It starts at your next login (or run: python research.py agent serve).")
    b.next_actions([
        ("python research.py agent status", "check the bridge + session"),
        ("python research.py agent retire", "stop + unpin the background bridge"),
    ])
    return 0


def _retire_bridge() -> None:
    """Stop a running background bridge + remove its logon autostart pin — the core
    of `agent retire`, shared with `disconnect`'s optional full-teardown step.
    Best-effort + idempotent: a None /shutdown = already down; a 'cannot find'
    uninstall = nothing was pinned. Prints its own progress; never raises."""
    # Stop a running bridge first (best-effort; None = already down).
    if _bridge_post("/shutdown") is not None:
        b.ok("Bridge stopping")
    ok, out = autostart.uninstall()
    if ok:
        b.ok("Autostart removed — the bridge will not start on login")
    elif "cannot find" in (out or "").lower() or "does not exist" in (out or "").lower():
        b.dim("No autostart was installed.")
    else:
        b.warn(f"Autostart teardown: {out or 'unknown'}")


def cmd_retire(args: argparse.Namespace) -> int:
    """Stop the background bridge + remove the logon pin (the agent twin of the
    backend `--retire`). The account session + skill are left alone."""
    b.header("requiescat", "rest — no longer on login", tagline_color=branding._BOLD + branding._RED)
    _retire_bridge()
    b.dim("Your account session + the chat skill are untouched "
          "(use agent disconnect to remove those).")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    b.header("ianua", "sign in your account", tagline_color=branding._BOLD + branding._ACCENT)
    print()
    if not _bridge_up():
        b.no("Bridge isn't running.  Start it:  python research.py agent serve  "
             "(or: agent resurrect)")
        return 1
    if not getattr(args, "local", False):
        # Default: sign in on the SR web app (superresearch.io) — same page as /sr login.
        return _login_remote(args)
    # --local: host-local fallback (the bridge's own page; no SR web app needed).
    url = config.login_origin() + "/login"
    runtime = prefs.get_runtime()
    if runtime:
        url += f"?runtime={runtime}"  # glow the connected runtime's watermark
    b.line(f"Opening {url}")
    b.dim("Sign in with your Super Research Google account (research-only).")
    try:
        webbrowser.open(url)
    except Exception:
        b.warn(f"Couldn't open a browser automatically — visit {url} manually.")
    return 0


def _remote_signin(*, open_browser: bool, runtime: str = "", label: str = "") -> str:
    """Shared sign-in via the SR web app (superresearch.io) — the SAME page
    `/sr login` uses, so sign-in is consistent everywhere and works from any device
    (no host-local page; approve on phone or this PC). Starts the broker flow, opens
    the verify link, polls until approved. Returns the final state: 'connected' /
    'expired' / 'error' / 'timeout' / 'cancelled' / 'start-failed'."""
    res = _bridge_post("/login/remote/start",
                       {"runtime": runtime or prefs.get_runtime() or "", "label": label or ""})
    if res is None or res[0] != 200:
        b.no(f"Couldn't start sign-in: {_err(res)}")
        return "start-failed"
    out = res[1]
    url = out.get("verifyUrl") or ""
    b.line(f"Sign in here:  {url}")
    b.dim("Sign in with your Super Research Google account, then tap Approve & connect.")
    if open_browser and url:
        try:
            webbrowser.open(url)
        except Exception:
            b.warn("Couldn't open a browser automatically — open the link above.")
    b.dim("Waiting for approval… (Ctrl-C to stop)")
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
                b.ok(f"Connected as {st.get('email') or st.get('uid')}.")
                return "connected"
            if state == "expired":
                b.no("Sign-in link expired before approval.")
                return "expired"
            if state == "error":
                b.no(f"Sign-in failed: {st.get('error', 'unknown error')}")
                return "error"
    except KeyboardInterrupt:
        b.dim("\n  Stopped waiting. The link may still be valid; re-run to resume.")
        return "cancelled"
    b.no("Timed out waiting for approval.")
    return "timeout"


def _login_remote(args: argparse.Namespace) -> int:
    """`agent login` (default): sign in on the SR web app (superresearch.io)."""
    state = _remote_signin(open_browser=True,
                           runtime=getattr(args, "runtime", "") or "",
                           label=getattr(args, "label", "") or "")
    if state == "connected":
        b.dim("Try:  agent verify")
        return 0
    if state in ("expired", "timeout"):
        b.dim("Re-run:  agent login")
    elif state == "start-failed":
        b.dim("Web sign-in unreachable — host-local fallback:  agent login --local")
    return 1


def cmd_status(_args: argparse.Namespace) -> int:
    b.header("status", "bridge + session", tagline_color=branding._BOLD + branding._ACCENT)
    print()
    res = _bridge_get("/status")
    bridge_up = res is not None
    if bridge_up:
        b.ok("Bridge: up")
        st = res[1]
        if st.get("authed"):
            b.ok(f"Account: signed in as {st.get('email') or st.get('uid')}")
        else:
            b.warn("Account: not signed in  →  python research.py agent login")
    else:
        b.no("Bridge: not running  →  python research.py agent serve  (or: agent resurrect)")
        sess = AccountSession.load()
        if sess:
            b.dim(f"Account: stored session for {sess.email or sess.uid} (start the bridge to validate)")
        else:
            b.dim("Account: no stored session")

    rt = prefs.get_runtime()
    if rt:
        loc = prefs.get_runtime_location()
        where = (f" · WSL · {prefs.get_runtime_distro()}" if loc == "wsl"
                 else (f" · {connect.host_os_label()}" if loc else ""))
        b.dim(f"Runtime: {rt}{where}")
    if autostart.is_installed():
        b.ok(f"Autostart: pinned to login ({autostart.TASK_NAME})")
    else:
        b.dim("Autostart: not pinned  →  python research.py agent resurrect")
    print()
    return 0 if bridge_up else 1


def _logout_session() -> bool:
    """Sign out: tell the bridge (if up) AND clear the local store, so it works
    whether or not the bridge is running. Returns True if a session was present.
    Shared by `agent logout` (sign-out only) and `agent disconnect` (full
    teardown)."""
    # Load BEFORE POSTing /logout: the bridge clears the store synchronously
    # before it responds, so a post-/logout load would always read empty — the
    # caller would then misreport "no session" even when one was just signed out.
    sess = AccountSession.load()
    existed = sess is not None
    res = _bridge_post("/logout")
    # #790: the agent-session row must be deleted on logout. When the bridge is UP
    # its /logout handler already did the delete + store.clear() before replying,
    # so there's nothing local to do. When the bridge is DOWN (res is None) we do
    # it ourselves: delete the row BEFORE logout() blanks the token (else the row
    # orphans — no token could ever mint to delete it — and lingers as a stale
    # agent until it ages out in the app). Safe re: the single-owner invariant:
    # the bridge is down, so this one-off token mint can't race a live refresher.
    if existed and res is None:
        try:
            FirestoreRest(sess.id_token).delete_agent_session(
                sess.uid, prefs.get_or_create_install_id()
            )
        except Exception:
            pass  # network/auth blip — the app hides it via lastSeenAt staleness
        sess.logout()
    prefs.clear_selected_device()  # also drop the target-device pref (bridge-down path)
    return existed


def cmd_logout(_args: argparse.Namespace) -> int:
    _logout_session()
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


def _doctor_row(label: str, ok_flag: bool, detail: str, warn_only: bool = False) -> None:
    mark = (branding.MARK_OK if ok_flag else (branding.MARK_WARN if warn_only else branding.MARK_NO))
    color = branding._OK if ok_flag else (branding._WARN if warn_only else branding._RED)
    print(f"  {b.c(color, mark)}  {label.ljust(10)}{detail}")


def cmd_doctor(_args: argparse.Namespace) -> int:
    b.header("medicus", "diagnose + connect", tagline_color=branding._BOLD + branding._ACCENT)
    print(f"\n  {b.c(branding._DIM, f'facade v{__version__}')}\n")

    _doctor_row("python", True, sys.version.split()[0])
    for mod in ("requests", "keyring"):
        try:
            __import__(mod)
            _doctor_row(mod, True, "importable")
        except Exception as e:
            _doctor_row(mod, False, str(e))

    try:
        requests.get("https://securetoken.googleapis.com", timeout=5)
        _doctor_row("google", True, "reachable")
    except requests.RequestException as e:
        _doctor_row("google", False, str(e))

    # The remote-login broker (SR web app). Any HTTP response = reachable.
    try:
        requests.get(config.FE_BASE, timeout=5)
        _doctor_row("sr web", True, f"reachable ({config.FE_BASE})")
    except requests.RequestException as e:
        _doctor_row("sr web", False, f"{config.FE_BASE} — {e}")

    # WSL mirrored networking — only relevant when a WSL runtime is in play, but
    # surfaced whenever WSL is present (a WSL chat can't reach the loopback bridge
    # without it). Reads %USERPROFILE%\.wslconfig (no need to start WSL).
    distros = connect.wsl_distros()
    if distros or prefs.get_runtime_location() == "wsl":
        mirrored = connect.mirrored_networking_enabled()
        if mirrored:
            _doctor_row("wsl net", True, "mirrored — WSL chat can reach the bridge")
        else:
            _doctor_row("wsl net", False,
                        "not mirrored — WSL chat can't reach the loopback bridge", warn_only=True)
            b.dim("           fix:  python research.py agent connect   (offers to enable it for you)")

    health = _bridge_get("/healthz")
    if health is None:
        _doctor_row("bridge", False, "down (run: python research.py agent serve)")
        sess = AccountSession.load()
        _doctor_row("account", bool(sess),
                    "stored session present — start the bridge to validate" if sess
                    else "not signed in", warn_only=bool(sess))
        print()
        return 1
    _doctor_row("bridge", True, "up")
    res = _bridge_get("/status")
    st = res[1] if res else {}
    if st.get("authed"):
        _doctor_row("account", True, str(st.get("email") or st.get("uid")))
    else:
        _doctor_row("account", False, "not signed in (run: python research.py agent login)")
    print()
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
    """Start a run (chat /sr-research). Returns a run id immediately."""
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
    """List recent runs (chat /sr-status with no id lists; here we list)."""
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
    """Show one run's status (chat /sr-status [id]). No id → the most recent run."""
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


def cmd_podcast(args: argparse.Namespace) -> int:
    """Get a run's audio as a local file (chat /sr-podcast). Prints the path the
    runtime would attach as a native audio message; no id = the most recent run."""
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
        # Prefer the newest run that already HAS audio (a late-phase artifact)
        # over the newest active run, which usually has none yet.
        with_audio = [r for r in runs
                      if any(lk.get("kind") == "audio_file" for lk in r.get("links", []))]
        rid = (with_audio[0] if with_audio else runs[0]).get("runId")
    # The bridge downloads the audio file (can take a few seconds) → longer wait.
    res = _bridge_get(f"/research/{rid}/podcast", timeout=180.0)
    if res is None or res[0] != 200:
        print(f"{_NO} {_err(res)}")
        return 1
    out = res[1]
    print(f"{_OK} Podcast “{out.get('title')}” → {out.get('localPath')}")
    print(f"     {out.get('sizeBytes', 0):,} bytes · {out.get('mime')} · send as a native audio message")
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
    """Cancel a run (chat /sr-cancel <id>)."""
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
    """Skip phases of a run (chat /sr-skip). Accepts phase numbers or names
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


def cmd_home(args: argparse.Namespace) -> int:
    """Bare `agent` / `--agent` (no subcommand): smart entry — show status when the
    agent is set up (a chat runtime is connected OR the bridge holds a signed-in
    session), else drop straight into the interactive connect flow so a first run —
    or a post-`disconnect` clean slate — onboards you.

    Note it keys off the runtime/session, NOT a bare `_bridge_up()`: after
    `disconnect` the background bridge is intentionally left running, so a
    still-up-but-idle bridge with no runtime + no session must onboard, not park on
    an empty status."""
    if prefs.get_runtime() or _bridge_authed():
        return cmd_status(args)
    # cmd_connect reads args.runtime/.dest; the bare namespace lacks them (they're
    # defined only on the `connect` subparser) — supply the omitted defaults.
    if not hasattr(args, "runtime"):
        args.runtime = None
    if not hasattr(args, "dest"):
        args.dest = None
    return cmd_connect(args)


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
    # Bare `agent` (no subcommand) is allowed → cmd_home (smart entry). A chosen
    # subcommand's own set_defaults(func=…) overrides this default.
    p.set_defaults(func=cmd_home)
    sub = p.add_subparsers(dest="command")

    cn = sub.add_parser("connect", parents=[common],
                        help="connect a chat runtime — branded flow: install the skill "
                             "(Windows or WSL) + optionally pin the bridge")
    cn.add_argument("runtime", nargs="?", help="hermes or openclaw (auto-detected if omitted)")
    cn.add_argument("--dest", help="explicit install dir (default: the runtime's skills dir)")
    cn.set_defaults(func=cmd_connect)

    dc = sub.add_parser("disconnect", parents=[common],
                        help="full teardown — remove the skill from the runtime AND sign out "
                             "(the app's Revoke twin)")
    dc.add_argument("runtime", nargs="?", help="hermes or openclaw (defaults to every connected one)")
    dc.add_argument("--dest", help="explicit install dir (default: the runtime's skills dir)")
    dc.set_defaults(func=cmd_disconnect)

    sub.add_parser("serve", parents=[common], help="start the host bridge (blocking)").set_defaults(func=cmd_serve)
    lg = sub.add_parser("login", parents=[common],
                        help="sign in your account on the SR web app (or --local for the host page)")
    lg.add_argument("--remote", action="store_true",
                    help="(default) sign in via the SR web app — approve on phone or this PC")
    lg.add_argument("--local", action="store_true",
                    help="sign in on the host's local bridge page instead of the SR web app")
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

    pod = sub.add_parser("podcast", parents=[common],
                         help="get a run's audio as a local file (no id = most recent)")
    pod.add_argument("runId", nargs="?", help="run id (default: most recent)")
    pod.set_defaults(func=cmd_podcast)

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

    sub.add_parser("resurrect", parents=[common],
                   help="run the bridge in the background + on every login (windowless)"
                   ).set_defaults(func=cmd_resurrect)
    sub.add_parser("retire", parents=[common],
                   help="stop the background bridge + remove the login pin"
                   ).set_defaults(func=cmd_retire)

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
