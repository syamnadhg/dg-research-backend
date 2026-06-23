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
    # just ANY HTTP response — so a foreign server squatting :9876 isn't mistaken
    # for the bridge.
    res = _bridge_get("/healthz", timeout=3.0)
    return bool(res and isinstance(res[1], dict) and "version" in res[1])


def _bridge_authed() -> bool:
    """Whether the bridge currently holds a signed-in account session (the real
    auth state, per /status) — not merely 'a sign-in was started'."""
    res = _bridge_get("/status")
    return bool(res and res[1].get("authed"))


def _wait_bridge_up(timeout: float = 12.0, interval: float = 0.3) -> bool:
    """Poll /healthz until the bridge answers, or `timeout` elapses (→ False).

    `start_detached` only LAUNCHES the bridge; it needs a beat to bind its port, so
    an *immediate* `_bridge_up()` right after starting it false-negatives (the
    socket isn't listening yet → connection refused). A caller that just started it
    must WAIT, not glance — otherwise the next step wrongly reports it as down."""
    if _bridge_up():
        return True  # already listening — no wait, no spinner flash
    deadline = time.monotonic() + timeout
    with b.spinner("Waiting for the bridge to start"):
        while True:
            if _bridge_up():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)


# ── commands ──────────────────────────────────────────────────────────────

def cmd_serve(args: argparse.Namespace) -> int:
    # A WSL runtime's bridge must run IN the distro — delegate (the in-distro serve
    # blocks in this same terminal). Off-Windows / co-located → serve here.
    rc = _delegate_lifecycle("serve", [], label="Serve")
    if rc is not None:
        return rc
    # The long-running bridge writes the durable operational log; short CLI
    # commands stay console-only (configured in main()).
    logsetup.configure(verbose=getattr(args, "verbose", False), to_file=True)
    # Foreground serve — nudge toward the always-up background mode unless it's
    # already pinned. (When autostart launches serve windowless this is a no-op:
    # the task exists, so is_installed() is True and the tip is skipped.)
    if not autostart.is_installed():
        b.dim("Tip: run the bridge in the background + on every login instead  →  "
              "python research.py agent resurrect")
    bridge.serve()
    return 0


# Chat channels Super Research reaches, shown as a row under the header — the
# channel NAME in its exact brand color (no glyph: a terminal can't render the
# apps' real SVG logos like the web auth page does, and stand-in emoji look
# subpar). (name, (r,g,b)): WhatsApp green, Telegram blue, iMessage green, Twilio red.
_CHANNELS = [
    ("WhatsApp", (37, 211, 102)),
    ("Telegram", (34, 158, 217)),
    ("iMessage", (52, 199, 89)),
    ("Twilio", (242, 47, 70)),
]


def _decide(explicit: bool | None, assume_yes: bool, prompt: str, *, default: bool = True) -> bool:
    """Resolve a yes/no connect step. An explicit --flag wins; otherwise --yes
    assumes yes; otherwise ask interactively. So a chat-driven (non-interactive)
    connect never blocks on a prompt that would EOF to False — the caller passes
    --yes and/or the per-step flag, and only a real terminal reaches b.confirm."""
    if explicit is not None:
        return explicit
    if assume_yes:
        return True
    return b.confirm(prompt, default=default)


def _choose_target(targets: list[connect.Target], *, assume_yes: bool = False) -> connect.Target | None:
    """Step 1's chooser: pick a runtime (numbered, when >1) then CONFIRM it with a
    'Continue with X?' prompt — so even a single detected runtime is an explicit
    choice. Returns the chosen Target, or None to cancel (Ctrl-C / EOF /
    out-of-range / a 'no' at the confirm). With ``assume_yes`` a single target is
    auto-confirmed; multiple targets can't be disambiguated non-interactively, so
    the caller must pass --runtime (we refuse rather than guess)."""
    if len(targets) > 1:
        if assume_yes:
            b.no("Multiple runtimes detected — pass --runtime hermes|openclaw for a non-interactive connect.")
            return None
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
    if not _decide(None, assume_yes, f"Continue with {_runtime_mark(chosen)}?", default=True):
        return None
    return chosen


def cmd_connect(args: argparse.Namespace) -> int:
    """Connect a chat runtime (Hermes / OpenClaw): choose it, install the Super
    Research skill where it lives + make it reachable, optionally pin the
    background bridge, and optionally sign in. Branded, interactive 4-step flow."""
    # A WSL hand-off re-invokes connect INSIDE the distro as a continuation (the
    # SUPER_AGENT_CONNECT_CONTINUED env var): it's a seamless continuation of the
    # host's flow, so suppress the banner + the re-detect/choose (the host already
    # chose the runtime) and resume at Install.
    continued = connect.is_continued()
    if not continued:
        b.header("nexus", "link Super Research to chat", tagline_color=branding._BOLD + branding._ACCENT)
        b.channels(_CHANNELS)
        b.step_arc(["Detect + choose", "Install", "Run on startup", "Sign in"])

    explicit = args.runtime_opt or args.runtime
    # Non-interactive when --yes is passed OR there's no terminal (a chat exec, e.g.
    # a Hermes/OpenClaw agent running `pipx run superresearch-agent connect` on the user's
    # behalf). A non-TTY shell CAN'T answer a prompt, so it proceeds with the same
    # safe defaults --yes would (install + pin startup) and RELAYS the sign-in link
    # instead of opening a browser + block-polling. Explicit --no-startup/--no-login
    # still win (they flow through _decide's `explicit` arg), and >1 runtime still
    # refuses without --runtime rather than guessing. This is what makes
    # "install from chat" a single, hang-free command.
    noninteractive = args.yes or not sys.stdin.isatty()
    assume_yes = noninteractive
    if explicit and explicit not in connect.RUNTIMES:
        b.no(f"Unknown runtime '{explicit}'. Choose: {', '.join(connect.RUNTIMES)}")
        return 1

    # ── [1/4] Detect + choose ────────────────────────────────────────────────
    if not continued:
        b.step(1, 4, "Detect + choose")
    with b.spinner("Looking for chat runtimes (this host + WSL)"):
        targets = connect.detect_targets()
    if explicit:
        matches = [t for t in targets if t.runtime == explicit]
        targets = matches or [connect.Target(explicit, "local", Path.home())]
        if not matches and not continued:
            b.dim(f"{explicit} not detected — will install at the default path on this host.")
    if not targets:
        b.no("No chat runtime found (looked for ~/.hermes, ~/.openclaw on this host and in WSL).")
        b.dim("Install Hermes or OpenClaw first, then re-run:  python research.py agent connect")
        b.dim("A runtime inside a container or a separate VM isn't auto-detected — and a")
        b.dim("  loopback-only bridge needs host networking / a published port to reach it;")
        b.dim("  point connect at it explicitly with  --dest <path-to-skills-dir>  if so.")
        return 1
    if continued:
        # The host already detected + chose this runtime; auto-select silently.
        chosen = targets[0]
    else:
        for t in targets:
            b.ok(f"Found {_runtime_mark(t)}")
        chosen = _choose_target(targets, assume_yes=assume_yes)
        if chosen is None:
            b.dim("Cancelled — nothing was changed.")
            return 1

    # A WSL runtime co-locates its bridge IN WSL (Model A) — a Windows bridge
    # can't share WSL's loopback. Hand off to the in-distro connect instead of
    # installing on Windows + mirror-networking.
    if chosen.location == "wsl":
        if args.dest:
            b.dim("(--dest is ignored for a WSL runtime — the in-distro connect installs at its own path.)")
        return _connect_wsl_runtime(
            chosen, assume_yes=assume_yes, noninteractive=noninteractive,
            startup=args.startup, login=args.login,
        )

    # ── [2/4] Install the skill + make it reachable ──────────────────────────
    b.step(2, 4, "Install the skill")
    target = _install_step(chosen, Path(args.dest) if args.dest else None, assume_yes=assume_yes)
    if target is None:
        return 1  # _install_step already printed the reason (declined / failed)
    # Co-located reachability: the bridge shares this host's loopback, so this is
    # just the OK + an honest container/VM caveat (a WSL target never reaches here).
    print()
    _ensure_reachable(chosen)

    # ── [3/4] Run on startup ──────────────────────────────────────────────────
    b.step(3, 4, "Run on startup")
    startup_pinned = _startup_step(explicit=args.startup, assume_yes=assume_yes)

    # ── [4/4] Sign in ─────────────────────────────────────────────────────────
    reload_hint = connect.profile(chosen.runtime).reload_hint
    # In a chat/agent exec (non-TTY): do NOT start sign-in or print a sign-in link
    # here. Sign-in is a SEPARATE later step — `/sr login`, AFTER /reload-skills
    # registers the skill; showing the link in the install message strands the
    # user (pre-reload the skill can't act on it). Collapse to the install
    # confirmation (step 2) + the two-step next line — no link.
    if noninteractive:
        print()
        if reload_hint:
            b.line(f"{reload_hint}, then /sr login to auth a Super Research account and get started.")
        else:
            b.line("Open a new chat (the skill auto-loads), then /sr login to auth a Super "
                   "Research account and get started.")
        return 0

    b.step(4, 4, "Sign in")
    # Show 'logout' (switch account) in the closing card when sign-in was STARTED
    # here OR the bridge is already authed — never the redundant 'login' the user
    # just chose to do. (A browser sign-in completes async; choosing it counts.)
    started = _signin_step(explicit=args.login, assume_yes=assume_yes, noninteractive=noninteractive)
    logged_in = started or _bridge_authed()

    print()
    tail = (f"  One more step in chat: run  {reload_hint}  so  /sr  registers."
            if reload_hint
            else "  In chat the skill auto-loads — open a new chat, then use  /sr .")
    b.line(b.c(branding._BOLD + branding._ACCENT, "Connected.") + b.c(branding._DIM, tail))
    # Device prerequisite (soft heads-up): the agent DRIVES Super Research on a
    # paired computer — it doesn't run the research in chat. The hard prompt comes
    # later, on the first research with no device (the /sr skill walks them through
    # pairing then).
    b.dim("Super Research runs on a paired computer — the agent drives it, it doesn't research in chat.")
    b.dim('Make sure one computer is running Super Research and paired; say "add a device" in chat to pair.')
    b.next_grouped(_connect_next(runtime=chosen.runtime, logged_in=logged_in,
                                 startup_pinned=startup_pinned))
    return 0


def _record_runtime(chosen: connect.Target) -> None:
    """Persist the connected runtime + WHERE it landed, so revoke/disconnect can
    find the install. Only a co-located target reaches here (a WSL target is
    handed off to the in-distro connect, which records its own prefs there)."""
    prefs.set_runtime(chosen.runtime, home=str(chosen.home),
                      location=chosen.location)


def _install_step(chosen: connect.Target, dest_override: Path | None, *,
                  assume_yes: bool = False) -> Path | None:
    """[2/4] Install (or keep) the skill. Returns the installed dir, or None if the
    user declined an install that isn't already present (→ caller aborts). With
    ``assume_yes`` a fresh install proceeds and an existing one is refreshed
    (non-interactive connect always lands the latest skill)."""
    existing = dest_override or chosen.dest
    if connect.verify(existing):
        b.dim(f"A Super Research skill is already installed at:\n     {existing}")
        if not _decide(None, assume_yes, "Reinstall (refresh to the latest)?", default=False):
            b.dim("Kept the existing skill.")
            _record_runtime(chosen)
            return existing
    elif not _decide(None, assume_yes, f"Install the skill into {_runtime_mark(chosen)}?", default=True):
        b.warn("Skipped — without the skill the chat runtime won't have the /sr commands.")
        return None
    try:
        with b.spinner("Installing the skill"):
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


def _startup_step(*, explicit: bool | None = None, assume_yes: bool = False) -> bool:
    """[3/4] Offer to pin + start the background bridge so it returns after a
    reboot — a Scheduled Task (Windows), systemd --user unit (Linux), or launchd
    LaunchAgent (macOS). Returns True if it ends up pinned. Degrades cleanly with a
    serve hint on an OS where pinning isn't implemented, so the flow never dead-ends.
    ``explicit`` (--startup/--no-startup) or ``assume_yes`` skip the prompt."""
    if not autostart.supported():
        b.warn(f"Run-on-startup pinning isn't available on this host ({connect.host_os_label()}).")
        b.dim("Start the bridge yourself:  python research.py agent serve")
        return False
    b.dim(f"Pins a background bridge that starts on every login (a {autostart.kind_label()}).")
    if not _decide(explicit, assume_yes, "Run on startup? (background, every login)", default=True):
        b.dim("Skipped — start it yourself when ready (see Next).")
        return False
    ok, out = autostart.install()
    if not ok:
        b.warn(f"Couldn't pin startup: {out}")
        b.dim("Start it yourself:  python research.py agent serve")
        return False
    started, serr = autostart.start_detached()
    # WAIT for it to actually bind before claiming success — else the very next
    # step ([4/4] Sign in) checks _bridge_up() before the socket is listening and
    # falsely reports "Bridge isn't running yet".
    if started and _wait_bridge_up():
        b.ok(f"Pinned to startup ({autostart.kind_label()}) + started in the background.")
    elif started:
        b.warn(f"Pinned to startup ({autostart.kind_label()}) — launched, but it's not answering yet.")
        b.dim("Give it a few seconds; if sign-in says it's not running, run: python research.py agent status")
    else:
        b.warn(f"Pinned to startup, but couldn't start it now: {serr}")
        b.dim("It starts at your next login (or run: python research.py agent serve).")
    return True


def _signin_step(*, explicit: bool | None = None, assume_yes: bool = False,
                 noninteractive: bool = False) -> bool:
    """[4/4] Optional sign-in on the SR web app (superresearch.io) — the SAME page
    `/sr login` uses, so it's consistent and works from any device. Needs the
    bridge up (it brokers the session); if it isn't, point at starting it first.

    ``explicit`` (--login/--no-login) or ``assume_yes`` skip the prompt. When
    ``noninteractive`` (a chat exec / --yes) it RELAYS the sign-in link instead of
    opening a host browser + block-polling — the user approves in the browser and
    the bridge's auto-poller captures the session automatically (#848; `/sr
    login-done` is an optional confirmation, no longer required). Returns True
    only when ACTUALLY signed in here (so a relayed link returns 'started')."""
    if not _bridge_up():
        b.dim("Bridge isn't running yet — start it first, then sign in:")
        b.dim("  python research.py agent serve   (or: agent resurrect)")
        b.dim("then:  agent login   (or  /sr login  from your chat).")
        return False
    prompt = ("Sign in now? (relays a link to approve)" if noninteractive
              else "Sign in now? (opens Super Research in your browser)")
    if not _decide(explicit, assume_yes, prompt, default=True):
        b.dim("Skipped — sign in later with  /sr login  in chat  (or: agent login).")
        return False
    state = _remote_signin(open_browser=not noninteractive, poll=not noninteractive)
    if state == "connected":
        return True
    if state == "started":   # non-interactive: link relayed, approval pending in chat
        return False
    if state == "start-failed":
        b.dim("Web sign-in unreachable right now — host-local fallback:  agent login --local")
    else:
        b.dim("Finish sign-in later:  /sr login  in chat  (or: agent login).")
    return False


def _connect_next(*, runtime: str, logged_in: bool, startup_pinned: bool) -> list[tuple[str, list[tuple[str, str]]]]:
    """Closing 'Next' actions, split into terminal commands vs in-chat slash
    commands, and varied by what the user chose (sign-in + startup state) and the
    runtime (the reload step only applies where skills don't auto-watch)."""
    p = "python research.py agent "
    terminal: list[tuple[str, str]] = []
    if logged_in:
        terminal.append((p + "logout", "sign out / switch the account the agent uses"))
    else:
        terminal.append((p + "login", "sign in your account (local browser)"))
    if not startup_pinned:
        terminal.append((p + "serve", "run the bridge here in this terminal (foreground)"))
        terminal.append((p + "resurrect", "run the bridge in the background + on every login"))
    terminal.append((p + "status", "check the bridge + session"))
    terminal.append((p + "retire", "stop the background bridge + remove it from login startup"))
    terminal.append((p + "disconnect", "uninstall the skill + sign out + forget the runtime (full reset)"))
    terminal.append((p + "--help", "all agent commands"))

    chat: list[tuple[str, str]] = []
    reload_hint = connect.profile(runtime).reload_hint
    if reload_hint:  # runtimes that auto-watch the skill dir (OpenClaw) need no reload step
        chat.append((reload_hint, "run ONCE in chat so the new /sr command registers"))
    if not logged_in:
        chat.append(("/sr login", "sign in (approve on your phone)"))
    chat.append(("/sr", "welcome + everything you can do"))
    return [("in this terminal", terminal), ("in your chat (Hermes / OpenClaw)", chat)]


def _ensure_reachable(target: connect.Target) -> None:
    """Make sure the chosen (co-located) runtime can reach the bridge over loopback.

    Model A co-locates the bridge with the runtime, so a same-host runtime shares
    the bridge's loopback and needs no setup. (A WSL runtime never reaches here —
    cmd_connect hands it off to the in-distro connect before this step.) The only
    caveat left is a container/VM whose loopback is scoped away from the host."""
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


def _print_wsl_manual(distro: str, cmd: str) -> None:
    """Print the command to run INSIDE a WSL distro to set Super Research up there,
    with its prerequisites + a pre-PyPI backend-checkout fallback."""
    b.dim(f"Run this inside WSL · {distro}:")
    b.line("    " + b.c(branding._BOLD + branding._ACCENT, f"wsl -d {distro}"))
    b.line("    " + b.c(branding._BOLD + branding._ACCENT, cmd))
    b.dim("  Needs uv in the distro (https://astral.sh/uv). Before the package is on")
    b.dim("  PyPI, a backend checkout works too — run INSIDE the distro:")
    b.dim("      python research.py agent connect")
    b.dim("  The bridge then runs in WSL with your runtime.")


def _connect_wsl_runtime(target: connect.Target, *, assume_yes: bool, noninteractive: bool,
                         startup: bool | None, login: bool | None) -> int:
    """The chosen runtime lives in WSL, so its bridge has to run INSIDE the distro
    (a bridge on Windows can't reach WSL's loopback). Continue setup there by
    re-running connect inside the distro (``--continued`` so it picks up as one
    seamless flow), forwarding the connect flags. Choosing the WSL runtime is the
    consent, so this proceeds automatically — falling back to printing the command
    only when there's no way to run it: a non-TTY without --yes, uv missing in the
    distro, or the in-distro run exits non-zero (e.g. the package isn't on PyPI)."""
    distro = target.distro or ""
    label = connect.RUNTIME_META[target.runtime]["label"]
    # The in-distro connect is a continuation of THIS flow: pre-select the same
    # runtime (run_agent_in_wsl sets the continuation env var so it suppresses
    # its banner/re-detect) → the user sees one clean flow.
    forwarded: list[str] = ["--runtime", target.runtime]
    if assume_yes or noninteractive:
        forwarded.append("--yes")
    if startup is True:
        forwarded.append("--startup")
    elif startup is False:
        forwarded.append("--no-startup")
    if login is True:
        forwarded.append("--login")
    elif login is False:
        forwarded.append("--no-login")

    b.dim(f"{label} runs inside WSL · {distro}, so Super Research installs there too —")
    b.dim("the bridge runs right next to it (same machine, shared loopback).")

    # No TTY and no --yes → can't drive the interactive in-distro setup; print it.
    if noninteractive and not assume_yes:
        _print_wsl_manual(distro, "pipx run superresearch-agent connect")
        return 0
    # pipx missing in the distro → install it autonomously (the WSL-side bootstrap),
    # then proceed. Only fall back to the manual command if that install can't finish.
    with b.spinner(f"Checking pipx inside WSL · {distro}"):
        _pipx_ok = connect.wsl_pipx_available(distro)
    if not _pipx_ok:
        b.dim(f"pipx isn't in WSL · {distro} yet — installing it there…")
        if not connect.ensure_wsl_pipx(distro):
            b.warn(f"Couldn't install pipx in WSL · {distro} automatically.")
            _print_wsl_manual(distro, "pipx run superresearch-agent connect")
            return 0
    b.dim(f"Setting it up inside {distro}…")
    rc = connect.run_agent_in_wsl(distro, "connect", forwarded)
    if rc != 0:
        b.warn(f"The in-WSL setup didn't finish (exit {rc}).")
        _print_wsl_manual(distro, "pipx run superresearch-agent connect")
    return rc


def _wsl_distro_for(explicit: str | None = None) -> str | None:
    """If this Windows host's runtime lives in WSL (and not ALSO natively on
    Windows), return its distro — the signal that a bridge-/skill-touching command
    must delegate INTO that distro (the bridge co-locates with the runtime there,
    unreachable from Windows). None when there's no WSL runtime, a co-located one
    also exists, or we're not on Windows. Mirrors connect's detection."""
    if sys.platform != "win32":
        return None
    try:
        with b.spinner("Checking for a WSL runtime"):
            targets = connect.detect_targets()
    except Exception:
        return None
    def _match(loc: str) -> list[connect.Target]:
        return [t for t in targets if t.location == loc and (not explicit or t.runtime == explicit)]
    wsl, local = _match("wsl"), _match("local")
    return wsl[0].distro if (wsl and not local) else None


def _unreachable_wsl_distros() -> list[str]:
    """Distros that are INSTALLED but not RUNNING while NOTHING is reachable here.

    When a WSL distro is stopped its ``\\wsl.localhost`` mount is down, so
    ``detect_targets`` can't see a runtime inside it and a Windows-side command
    would silently no-op (or query a non-existent local bridge). Those stopped
    distros are exactly the ones we *couldn't look in* — distinct from a running
    distro we DID inspect and found empty. Returns [] when something IS reachable
    locally / in a running distro (no ambiguity to warn about), or off-Windows."""
    if sys.platform != "win32":
        return []
    try:
        if connect.detect_targets():        # a runtime is reachable → nothing hidden
            return []
        installed = connect.wsl_distros()
        running = set(connect.wsl_running_distros())
    except Exception:
        return []
    return [d for d in installed if d not in running]


def _warn_unreachable_wsl(action_hint: str) -> bool:
    """If the runtime may live in a stopped WSL distro we couldn't inspect, say so
    (clear message instead of a confusing no-op) and return True. Else False."""
    stopped = _unreachable_wsl_distros()
    if not stopped:
        return False
    names = ", ".join(stopped)
    b.warn(f"Nothing is reachable here, but WSL is installed and stopped ({names}).")
    b.dim("If your runtime lives in WSL, its distro is asleep so I can't reach it.")
    b.dim(f"  Start it and retry:  wsl -d {stopped[0]}     then re-run this command")
    b.dim(f"  …or {action_hint} inside the distro:  wsl -d {stopped[0]}   then   pipx run superresearch-agent <command>")
    return True


def _delegate_lifecycle(subcommand: str, extra_args: list[str], *, label: str,
                        explicit: str | None = None) -> int | None:
    """A lifecycle command (disconnect/retire/resurrect/serve) whose runtime is in
    WSL must run INSIDE the distro — the bridge/autostart/prefs live there, not on
    Windows. Returns the in-distro exit code, or None to proceed locally (a
    co-located runtime / no WSL runtime / off-Windows)."""
    distro = _wsl_distro_for(explicit)
    if distro is None:
        # No WSL runtime detected — but if a distro is stopped we may simply not
        # have been able to look. Surface that instead of a silent local no-op.
        if _warn_unreachable_wsl("run it"):
            return 1
        return None
    with b.spinner(f"Checking pipx inside WSL · {distro}"):
        _pipx_ok = connect.wsl_pipx_available(distro)
    if not _pipx_ok:
        b.warn(f"This runtime is in WSL · {distro}, but pipx isn't installed there.")
        b.dim(f"Run it inside the distro:  wsl -d {distro}   then   pipx run superresearch-agent {subcommand}")
        return 1
    b.dim(f"{label} runs inside WSL · {distro} — doing it there…")
    return connect.run_agent_in_wsl(distro, subcommand, extra_args)


def _redirect_if_wsl(chat_hint: str) -> int | None:
    """A bridge-query command (status/login/logout/device) can't reach a WSL
    bridge from Windows, so when the runtime is in WSL and there's no local bridge,
    point the user at chat / the in-distro CLI instead of querying a non-existent
    Windows bridge. Returns 0 (redirected) or None (a local bridge is here →
    proceed)."""
    if _bridge_up():
        return None
    distro = _wsl_distro_for()
    if distro is None:
        # A stopped WSL distro could be hiding the runtime → say so rather than
        # query a Windows bridge that was never here.
        if _warn_unreachable_wsl("run it"):
            return 0
        return None
    b.dim(f"Your runtime lives in WSL · {distro} — its bridge runs there, not on Windows.")
    b.dim(f"  {chat_hint}")
    b.dim(f"  …or inside the distro:  wsl -d {distro}   then   pipx run superresearch-agent <command>")
    return 0


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
    explicit = args.runtime
    if explicit and explicit not in connect.RUNTIMES:
        b.no(f"Unknown runtime '{explicit}'. Choose: {', '.join(connect.RUNTIMES)}")
        return 1
    # A WSL runtime's skill + bridge + session + prefs all live in the distro — run
    # the whole teardown there (mirror connect's hand-off), not on Windows.
    rc = _delegate_lifecycle("disconnect", (["--runtime", explicit] if explicit else []),
                             label="Disconnect", explicit=explicit)
    if rc is not None:
        return rc
    if not connect.is_continued():
        b.header("solvo", "disconnect from chat", tagline_color=branding._BOLD + branding._RED)
    dest_override = Path(args.dest) if args.dest else None

    # ── [1/2] Remove the skill ────────────────────────────────────────────────
    b.step(1, 2, "Remove the skill")
    removed_any = False
    for rt, home in _disconnect_pairs(explicit, dest_override):
        try:
            with b.spinner(f"Removing the skill from {rt}"):
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
        nexts.append(("python research.py agent retire", "stop the background bridge + remove it from login startup"))
    b.next_actions(nexts)
    return 0


def cmd_resurrect(args: argparse.Namespace) -> int:
    """Pin the bridge to login + start it in the background now (the agent twin of
    the backend `--resurrect`) — a Scheduled Task (Windows), systemd --user unit
    (Linux), or launchd LaunchAgent (macOS)."""
    rc = _delegate_lifecycle("resurrect", [], label="Resurrect")
    if rc is not None:
        return rc
    if not connect.is_continued():
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
    if started and _wait_bridge_up():
        b.ok("Bridge started in the background")
    elif started:
        b.warn("Bridge launched, but it's not answering yet — give it a few seconds.")
        b.dim("Check it: python research.py agent status")
    else:
        b.warn(f"Pinned, but couldn't start it now: {serr}")
        b.dim("It starts at your next login (or run: python research.py agent serve).")
    b.next_actions([
        ("python research.py agent status", "check the bridge + session"),
        ("python research.py agent retire", "stop the background bridge + remove it from login startup"),
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
    rc = _delegate_lifecycle("retire", [], label="Retire")
    if rc is not None:
        return rc
    if not connect.is_continued():
        b.header("requiescat", "rest — no longer on login", tagline_color=branding._BOLD + branding._RED)
    b.dim("Stops the background bridge (agent serve) + removes it from login startup.")
    _retire_bridge()
    b.dim("Your account session + the chat skill are untouched "
          "(use agent disconnect to remove those).")
    b.next_actions([
        ("python research.py agent resurrect", "run the bridge in the background + on every login"),
        ("python research.py agent serve", "run the bridge here in this terminal (foreground)"),
    ])
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    b.header("ianua", "sign in your account", tagline_color=branding._BOLD + branding._ACCENT)
    print()
    rc = _redirect_if_wsl("Sign in from chat:  /sr login")
    if rc is not None:
        return rc
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


def _remote_signin(*, open_browser: bool, poll: bool = True, runtime: str = "", label: str = "") -> str:
    """Shared sign-in via the SR web app (superresearch.io) — the SAME page
    `/sr login` uses, so sign-in is consistent everywhere and works from any device
    (no host-local page; approve on phone or this PC). Starts the broker flow, opens
    the verify link, polls until approved. Returns the final state: 'connected' /
    'expired' / 'error' / 'timeout' / 'cancelled' / 'start-failed'.

    With ``poll=False`` (a chat-driven / headless connect) it STARTS the flow and
    prints the link, then returns 'started' WITHOUT opening a browser or blocking —
    the user approves and finishes in chat with `/sr login-wait`, which polls the
    same pending flow."""
    res = _bridge_post("/login/remote/start",
                       {"runtime": runtime or prefs.get_runtime() or "", "label": label or ""})
    if res is None or res[0] != 200:
        b.no(f"Couldn't start sign-in: {_err(res)}")
        return "start-failed"
    out = res[1]
    url = out.get("verifyUrl") or ""
    b.line(f"Sign in here:  {url}")
    b.dim("Sign in with your Super Research Google account, then tap Approve & connect.")
    if not poll:
        b.dim("Approve it in your browser — the bridge connects you automatically.")
        b.dim("(Confirm any time in chat:  /sr login-done.)")
        return "started"
    if open_browser and url:
        try:
            webbrowser.open(url)
        except Exception:
            b.warn("Couldn't open a browser automatically — open the link above.")
    deadline = time.monotonic() + float(out.get("expiresIn", 600) or 600)
    interval = config.REMOTE_POLL_INTERVAL_SECONDS
    # Spin during the (possibly long) wait so it never looks hung; collect the
    # outcome and print it AFTER the spinner clears so the line stays clean.
    final: tuple[str, dict] = ("timeout", {})
    try:
        with b.spinner("Waiting for approval — Ctrl-C to stop"):
            while time.monotonic() < deadline:
                time.sleep(interval)
                pr = _bridge_post("/login/remote/poll")
                if pr is None or pr[0] != 200:
                    continue  # transient — keep waiting
                state = pr[1].get("state")
                if state in ("connected", "expired", "error"):
                    final = (state, pr[1])
                    break
    except KeyboardInterrupt:
        b.dim("\n  Stopped waiting. The link may still be valid; re-run to resume.")
        return "cancelled"
    state, st = final
    if state == "connected":
        b.ok(f"Connected as {st.get('email') or st.get('uid')}.")
        return "connected"
    if state == "expired":
        b.no("Sign-in link expired before approval.")
        return "expired"
    if state == "error":
        b.no(f"Sign-in failed: {st.get('error', 'unknown error')}")
        return "error"
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
    rc = _redirect_if_wsl("Check it from chat:  /sr status")
    if rc is not None:
        return rc
    res = _bridge_get("/status")
    bridge_up = res is not None
    if bridge_up:
        b.ok("Bridge: up")
        st = res[1]
        if st.get("authed"):
            b.ok(f"Account: signed in as {st.get('email') or st.get('uid')}")
        elif st.get("remoteLogin") == "pending":
            # A sign-in is mid-flight; the bridge auto-captures on approval (#848).
            b.warn("Account: sign-in in progress — approve it in your browser; you'll connect automatically.")
        elif st.get("remoteLogin") in ("error", "expired"):
            b.warn("Account: last sign-in didn't complete  →  python research.py agent login")
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
        where = f" · {connect.host_os_label()}" if loc else ""
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
    rc = _redirect_if_wsl("Sign out from chat:  /sr logout")
    if rc is not None:
        return rc
    _logout_session()
    print("Logged out — account session cleared.")
    return 0


def cmd_device(args: argparse.Namespace) -> int:
    """List the devices the account can reach, or switch the target device."""
    rc = _redirect_if_wsl("Manage devices from chat:  /sr device")
    if rc is not None:
        return rc
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

    if getattr(args, "device_command", None) == "add":
        with b.spinner("Pairing the device"):
            res = _bridge_post("/device/pair", {"code": args.code})
        if res is None or res[0] != 200:
            print(f"{_NO} couldn't add device: {_err(res)}")
            return 1
        d = res[1]
        nm = d.get("deviceName") or d.get("deviceId") or "device"
        print(f"{_OK} Added {nm}{' (now selected)' if d.get('selected') else ''}.")
        return 0

    if getattr(args, "device_command", None) == "remove":
        res = _bridge_post("/device/remove", {"deviceId": args.deviceId})
        if res is None or res[0] != 200:
            print(f"{_NO} couldn't remove device: {_err(res)}")
            return 1
        print(f"{_OK} Removed device {args.deviceId}.")
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
        with b.spinner("Checking google reachability"):
            requests.get("https://securetoken.googleapis.com", timeout=5)
        _doctor_row("google", True, "reachable")
    except requests.RequestException as e:
        _doctor_row("google", False, str(e))

    # The remote-login broker (SR web app). Any HTTP response = reachable.
    try:
        with b.spinner("Checking sr web reachability"):
            requests.get(config.FE_BASE, timeout=5)
        _doctor_row("sr web", True, f"reachable ({config.FE_BASE})")
    except requests.RequestException as e:
        _doctor_row("sr web", False, f"{config.FE_BASE} — {e}")

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
    with b.spinner("Enqueuing the run"):
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
    with b.spinner("Starting the run"):
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
    with b.spinner("Fetching the podcast audio"):
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
    """Stop the running host bridge (this stops the BRIDGE process — not a research
    run; use `agent cancel <id>` / `/sr stop` in chat to stop a run)."""
    res = _bridge_post("/shutdown")
    if res is None:
        print("Bridge isn't running (nothing to stop).")
        return 0
    if res[0] == 200:
        print(f"{_OK} Bridge stopping.")
        if autostart.is_installed():
            b.dim("It's pinned to startup, so it returns on your next login "
                  "(remove the pin with: python research.py agent retire).")
        return 0
    print(f"{_NO} couldn't stop the bridge: {_err(res)}")
    return 1


def _local_superresearch() -> "str | None":
    """Path to the Super Research backend CLI on THIS machine, if installed (the
    agent + backend are co-located in the standard setup). None if absent."""
    import shutil as _sh
    return _sh.which("superresearch")


def cmd_version(_args: argparse.Namespace) -> int:
    """Show the agent version AND the Super Research backend version (the backend
    is the thing that runs research; the agent just drives it), each with a
    pip-style "newer on PyPI" nudge when one is available."""
    from . import selfupdate
    b.header("versio", "versions", tagline_color=branding._BOLD + branding._ACCENT)
    print(f"\n  {b.c(branding._BOLD, 'Agent')} (superresearch-agent)   {b.c(branding._BOLD, 'v' + __version__)}")
    a_new = selfupdate.agent_update_available()
    if a_new:
        print(f"     {b.c(branding._ACCENT, '⬆ v' + a_new + ' available')} — update with  "
              f"{b.c(branding._BOLD, 'pipx run superresearch-agent connect')}")
    sr = _local_superresearch()
    backend_ver = None
    if sr:
        import subprocess as _sp
        try:
            out = _sp.run([sr, "--version"], capture_output=True, text=True, timeout=15).stdout.strip()
        except Exception:
            out = ""
        import re as _re
        m = _re.search(r"(\d+\.\d+\.\d+\S*)", out)
        backend_ver = m.group(1) if m else None
        print(f"  {b.c(branding._BOLD, 'Super Research')} (backend)   {b.c(branding._BOLD, ('v' + backend_ver) if backend_ver else '(version unknown)')}")
        b_new = selfupdate.backend_update_available(backend_ver)
        if b_new:
            print(f"     {b.c(branding._ACCENT, '⬆ v' + b_new + ' available')} — update with  "
                  f"{b.c(branding._BOLD, 'superresearch --update')}")
    else:
        print(f"  {b.c(branding._BOLD, 'Super Research')} (backend)   {b.c(branding._DIM, 'not installed on this machine')}")
    print()
    return 0


def cmd_update(_args: argparse.Namespace) -> int:
    """Update the Super Research backend (delegates to `superresearch --update`).
    The backend is the package that does the research; update the chat agent
    itself separately with `pipx upgrade superresearch-agent`."""
    b.header("renovatio", "update Super Research", tagline_color=branding._BOLD + branding._ACCENT)
    sr = _local_superresearch()
    if not sr:
        print(f"\n  {_NO} Super Research isn't installed on this machine.")
        print(f"     {b.c(branding._DIM, 'The backend runs on the paired device — update it there.')}")
        print()
        return 1
    import subprocess as _sp
    print("\n  Updating Super Research (the backend) …")
    try:
        rc = _sp.call([sr, "--update"])
    except KeyboardInterrupt:
        return 130
    print(f"  {b.c(branding._DIM, 'Update the chat agent itself with:')}  {b.c(branding._BOLD, 'pipx upgrade superresearch-agent')}")
    print()
    return rc


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

    cn = sub.add_parser("connect", parents=[common], aliases=["install"],
                        help="connect a chat runtime (this host or WSL) — install the skill "
                             "+ optionally pin the bridge (a WSL runtime connects in-distro). "
                             "Alias: install — so an agent asked to 'install superresearch' lands here.")
    cn.add_argument("runtime", nargs="?", help="hermes or openclaw (auto-detected if omitted)")
    cn.add_argument("--runtime", dest="runtime_opt",
                    help="hermes or openclaw (flag form — for non-interactive / chat-driven connect)")
    cn.add_argument("--dest", help="explicit install dir (default: the runtime's skills dir)")
    cn.add_argument("-y", "--yes", action="store_true",
                    help="non-interactive: assume yes to prompts without an explicit flag "
                         "(install + the steps below) — for chat-driven connect")
    cn.add_argument("--startup", dest="startup", action="store_true", default=None,
                    help="pin run-on-startup without asking")
    cn.add_argument("--no-startup", dest="startup", action="store_false",
                    help="skip run-on-startup without asking")
    cn.add_argument("--login", dest="login", action="store_true", default=None,
                    help="start sign-in without asking (non-interactive: prints the link to relay in chat)")
    cn.add_argument("--no-login", dest="login", action="store_false",
                    help="skip sign-in without asking")
    cn.set_defaults(func=cmd_connect)

    dc = sub.add_parser("disconnect", parents=[common],
                        help="full reset — uninstall the skill, sign out, AND forget the runtime "
                             "(the app's Revoke now only signs out; this is the only full teardown)")
    dc.add_argument("runtime", nargs="?", help="hermes or openclaw (defaults to every connected one)")
    dc.add_argument("--dest", help="explicit install dir (default: the runtime's skills dir)")
    dc.set_defaults(func=cmd_disconnect)

    sub.add_parser("serve", parents=[common],
                   help="run the host bridge here in this terminal (foreground, blocking)").set_defaults(func=cmd_serve)
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
    dvadd = dvsub.add_parser("add", parents=[common], help="pair a new device by its on-screen pair code")
    dvadd.add_argument("code", help="the pair code shown on the new device's screen")
    dvadd.set_defaults(func=cmd_device)
    dvrm = dvsub.add_parser("remove", parents=[common], help="unlink a device from your account")
    dvrm.add_argument("deviceId", help="deviceId to remove (from `agent device`)")
    dvrm.set_defaults(func=cmd_device)

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

    sub.add_parser("stop", parents=[common],
                   help="stop the bridge process NOW (it returns on next login if it's pinned)"
                   ).set_defaults(func=cmd_stop)

    sub.add_parser("resurrect", parents=[common],
                   help="run the bridge in the background + on every login (windowless)"
                   ).set_defaults(func=cmd_resurrect)
    sub.add_parser("retire", parents=[common],
                   help="stop the bridge AND unpin it from login startup (won't return until 'resurrect')"
                   ).set_defaults(func=cmd_retire)

    sub.add_parser("version", parents=[common],
                   help="show the agent + Super Research backend versions"
                   ).set_defaults(func=cmd_version)
    sub.add_parser("update", parents=[common],
                   help="update the Super Research backend to the latest published version"
                   ).set_defaults(func=cmd_update)

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
