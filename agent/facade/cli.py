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

# ⛔⛔ NAMED, NOT `__name__`. The fleet starts the bridge as
# `python -m facade.cli serve` (dg-hermes-fleet/skills/super-research/scripts/sr.py),
# and under `-m` this module's `__name__` is `"__main__"` — not a child of the
# `facade` logger `logsetup.configure` installs the rotating file handler on. So
# on the ONE deployment that can actually produce a split home, the warning about
# it would have gone to a logger with no file handler and no console: the pinned
# launchers give the bridge no StandardOutput at all. It would have been emitted,
# and nowhere.
log = logging.getLogger("facade.cli")

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
    # ⛔⛔ THREE SOURCES, AND THE PREF IS THE ONLY ONE THAT REACHES A PINNED BRIDGE.
    # The flag needs a command line the generated launcher does not have; the
    # environment variable needs an environment `autostart.py` never writes — no
    # `EnvironmentVariables` in the plist, no `Environment=` in the unit — and a
    # LaunchAgent inherits no shell profile. Both were shipped as the fix for this
    # and both are inert on the recommended install. `agent verbose on` writes the
    # pref, and the bridge reads that file itself whoever started it.
    logsetup.configure(
        verbose=(getattr(args, "verbose", False) or config.VERBOSE
                 or prefs.get_verbose()),
        to_file=True)
    # ⛔⛔ RECORDED INTO THE FILE THAT GETS SENT, and immediately after the handler
    # that opens it — not printed. A split home is exactly the condition under which
    # somebody is later told their agent log was "empty", and the person who reads
    # that sentence is support, holding whichever file the handler wrote. A banner
    # line would not reach them: the pinned launchers give the bridge no
    # StandardOutPath, no StandardOutput and no console at all, so on the
    # recommended install every print here goes to /dev/null. The one channel that
    # survives to the place the question gets asked is the log itself.
    _split = config.home_split()
    if _split:
        log.warning(
            "the chat host's home is %s but this log is written under %s — "
            "--agent-log sends THIS file, and anything written under the other "
            "home will not reach support", _split, Path.home())
    # Foreground serve — nudge toward the always-up background mode unless it's
    # already pinned. (When autostart launches serve windowless this is a no-op:
    # the task exists, so is_installed() is True and the tip is skipped.)
    if not autostart.is_installed():
        b.dim("Tip: run the bridge in the background + on every login instead  →  "
              "superresearch-agent resurrect")
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
        # A runtime in a STOPPED WSL distro can't be detected — its \\wsl.localhost
        # mount is down (detect_wsl_targets now SKIPS stopped distros so it can't
        # wedge on an uninterruptible mount probe). Surface that as the likely cause
        # + the fix (start the distro) instead of a misleading "nothing installed".
        if _warn_unreachable_wsl("connect"):
            return 1
        b.no("No chat runtime found (looked for ~/.hermes, ~/.openclaw on this host and in WSL).")
        b.dim("Install Hermes or OpenClaw first, then re-run:  superresearch-agent connect")
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
    # later, on the first research with no device (the chat shows the no-computer
    # screen then).
    # ⭐ THE SAME ADD LINE THE CHAT PRINTS, WITH THE PAGE IN IT (owner, 2026-09-24).
    # This said "make sure one computer is running Super Research and paired", which
    # assumes one exists and names no way to get one.
    b.dim("Super Research runs on a paired computer — the agent drives it, it doesn't research in chat.")
    b.dim("Add a computer: set one up at https://superresearch.io/install, then send your "
          "chat the 8-character access code the computer shows (or one a computer's "
          "owner gave you).")
    b.next_grouped(_connect_next(runtime=chosen.runtime, logged_in=logged_in,
                                 startup_pinned=startup_pinned))
    return 0


def _record_runtime(chosen: connect.Target) -> None:
    """Persist the connected runtime + WHERE it landed, so revoke/disconnect can
    find the install. Only a co-located target reaches here (a WSL target is
    handed off to the in-distro connect, which records its own prefs there)."""
    prefs.set_runtime(chosen.runtime, home=str(chosen.home),
                      location=chosen.location)
    # Default the agent's app label to the runtime's OWN name (e.g. Hermes persona
    # "rocky" → "Rocky") so a user with several agents isn't staring at a wall of
    # identical "Super Agent" rows. Best-effort + never clobbers a label the user
    # set; an FE rename on the doc always wins.
    name = connect.runtime_display_name(chosen.runtime, chosen.home)
    if name:
        prefs.set_label_if_unset(name)


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


def _pin_startup() -> tuple[bool, str]:
    """Pin the login launcher, materialising a DURABLE install first if the only
    thing we could otherwise pin is pipx's evictable run cache.

    Every pin path goes through here. `pipx run superresearch-agent connect` — the
    documented from-chat install — runs from a venv pipx throws away, so a pin
    written straight from it works right up until the eviction and then resurrects
    an old bridge or none. `autostart.install()` refuses that; this is the step
    that makes the refusal actionable instead of a dead end."""
    if not autostart.pin_target_is_durable():
        from . import selfupdate
        with b.spinner("Installing Super Research Agent (so startup survives updates)"):
            ok, note = selfupdate.ensure_durable_install()
        if not ok:
            return False, f"couldn't install a permanent copy to pin to: {note}"
    return autostart.install()


def _startup_step(*, explicit: bool | None = None, assume_yes: bool = False) -> bool:
    """[3/4] Offer to pin + start the background bridge so it returns after a
    reboot — a Scheduled Task (Windows), systemd --user unit (Linux), or launchd
    LaunchAgent (macOS). Returns True if it ends up pinned. Degrades cleanly with a
    serve hint on an OS where pinning isn't implemented, so the flow never dead-ends.
    ``explicit`` (--startup/--no-startup) or ``assume_yes`` skip the prompt."""
    if not autostart.supported():
        b.warn(f"Run-on-startup pinning isn't available on this host ({connect.host_os_label()}).")
        b.dim("Start the bridge yourself:  superresearch-agent serve")
        return False
    b.dim(f"Pins a background bridge that starts on every login (a {autostart.kind_label()}).")
    if not _decide(explicit, assume_yes, "Run on startup? (background, every login)", default=True):
        b.dim("Skipped — start it yourself when ready (see Next).")
        return False
    ok, out = _pin_startup()
    if not ok:
        b.warn(f"Couldn't pin startup: {out}")
        b.dim("Start it yourself:  superresearch-agent serve")
        return False
    started, serr = autostart.start_detached()
    # WAIT for it to actually bind before claiming success — else the very next
    # step ([4/4] Sign in) checks _bridge_up() before the socket is listening and
    # falsely reports "Bridge isn't running yet".
    if started and _wait_bridge_up():
        b.ok(f"Pinned to startup ({autostart.kind_label()}) + started in the background.")
    elif started:
        b.warn(f"Pinned to startup ({autostart.kind_label()}) — launched, but it's not answering yet.")
        b.dim("Give it a few seconds; if sign-in says it's not running, run: superresearch-agent status")
    else:
        b.warn(f"Pinned to startup, but couldn't start it now: {serr}")
        b.dim("It starts at your next login (or run: superresearch-agent serve).")
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
        b.dim("  superresearch-agent serve   (or: agent resurrect)")
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
        b.dim(_local_signin_needs())
    else:
        b.dim("Finish sign-in later:  /sr login  in chat  (or: agent login).")
    return False


def _local_signin_needs() -> str:
    """The one line saying what `agent login --local` still depends on.

    ⛔ THE FALLBACK IS NOT INDEPENDENT OF THE WEB APP. The local page's Google
    window opens on ``config.AUTH_DOMAIN`` — superresearch.io, served by the same
    web app whose failed sign-in start is why --local gets offered at all. So
    --local helps when only the broker route is broken, not when the site is down,
    and a line offering it must say so rather than promise a way round an outage.
    Named from the value rather than spelled out, so a staging override keeps the
    line true."""
    return f"Its Google sign-in window opens on {config.AUTH_DOMAIN}, so that site must be up too."


def _connect_next(*, runtime: str, logged_in: bool, startup_pinned: bool) -> list[tuple[str, list[tuple[str, str]]]]:
    """Closing 'Next' actions, split into terminal commands vs in-chat slash
    commands, and varied by what the user chose (sign-in + startup state) and the
    runtime (the reload step only applies where skills don't auto-watch)."""
    p = "superresearch-agent "
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
    b.dim("  PyPI, install the agent from a backend checkout instead — INSIDE the distro:")
    b.dim("      pipx install ./agent   then   superresearch-agent connect")
    b.dim("  (install it — don't source-run: a pipx install pins a stable launcher.)")
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
        _print_wsl_manual(distro, "pipx run --no-cache superresearch-agent connect")
        return 0
    # pipx missing in the distro → install it autonomously (the WSL-side bootstrap),
    # then proceed. Only fall back to the manual command if that install can't finish.
    with b.spinner(f"Checking pipx inside WSL · {distro}"):
        _pipx_ok = connect.wsl_pipx_available(distro)
    if not _pipx_ok:
        b.dim(f"pipx isn't in WSL · {distro} yet — installing it there…")
        if not connect.ensure_wsl_pipx(distro):
            b.warn(f"Couldn't install pipx in WSL · {distro} automatically.")
            _print_wsl_manual(distro, "pipx run --no-cache superresearch-agent connect")
            return 0
    b.dim(f"Setting it up inside {distro}…")
    rc = connect.run_agent_in_wsl(distro, "connect", forwarded)
    if rc != 0:
        b.warn(f"The in-WSL setup didn't finish (exit {rc}).")
        _print_wsl_manual(distro, "pipx run --no-cache superresearch-agent connect")
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
    # Non-interactive (chat exec / --yes): do the FULL teardown — including the
    # background bridge — without prompting. This is what lets a chat "remove /
    # disconnect Super Research" actually take the bridge down (not just delete the
    # skill file, which the runtime's own skill-removal does).
    noninteractive = bool(getattr(args, "yes", False)) or not sys.stdin.isatty()
    # A WSL runtime's skill + bridge + session + prefs all live in the distro — run
    # the whole teardown there (mirror connect's hand-off), not on Windows. Forward
    # --yes so the in-distro disconnect is non-interactive too.
    rc = _delegate_lifecycle("disconnect",
                             (["--runtime", explicit] if explicit else [])
                             + (["--yes"] if getattr(args, "yes", False) else []),
                             label="Disconnect", explicit=explicit)
    if rc is not None:
        return rc
    if not connect.is_continued():
        b.header("solvo", "disconnect from chat", tagline_color=branding._BOLD + branding._RED)
    dest_override = Path(args.dest) if args.dest else None

    # ── [1/2] Remove the skill ────────────────────────────────────────────────
    b.step(1, 2, "Remove the skill")
    removed_any = False
    reload_hints: set[str] = set()
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
            # Hermes caches its skill scan, so /sr lingers until a reload — symmetric
            # with connect telling the user to reload so it registers. OpenClaw
            # auto-watches the skill dir (reload_hint None) → no prompt needed.
            hint = connect.profile(rt).reload_hint
            if hint:
                reload_hints.add(hint)
    if not removed_any:
        b.dim("No Super Research skill was installed (nothing to remove).")
    # The reload step (so /sr UNregisters) is surfaced in the grouped 'Next'
    # block at the end — symmetric with connect, where reload registers /sr.

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

    # Clear pipx's cached run-venv for the agent so a later reinstall pulls FRESH
    # from PyPI. `pipx run` reuses its cache for ~14 days, so without this a
    # post-disconnect `pipx run superresearch-agent connect` would replay the
    # stale build — a full teardown must leave nothing stale behind. Detached:
    # runs once THIS `pipx run … disconnect` exits and frees the venv. Best-effort.
    try:
        from . import selfupdate
        if selfupdate.spawn_detached_cache_clear():
            b.dim("Clearing the cached package so a reinstall pulls the latest.")
    except Exception:
        pass

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
        # _decide: --yes / non-TTY → True (stop it, the full-teardown intent);
        # a real terminal still gets the prompt.
        if _decide(None, noninteractive, "Also stop the background bridge + remove it from startup?", default=True):
            _retire_bridge()
        else:
            kept_bridge = True
            b.dim("Left the background bridge running (it returns on login).")

    # Suggest `retire` ONLY when a running bridge was deliberately kept — never when
    # it was just torn down, and never when there was nothing to tear down (a stale
    # 'retire' hint when the bridge is already gone reads as unfinished cleanup).
    terminal_nexts = [("superresearch-agent connect", "reconnect a runtime")]
    if kept_bridge:
        terminal_nexts.append(("superresearch-agent retire", "stop the background bridge + remove it from login startup"))
    # A removed skill still lingers in the runtime's chat until it reloads its
    # skill scan (Hermes caches it; OpenClaw auto-watches → reload_hint None → no
    # step). Show the reload in the same grouped 'Next' as connect, so the
    # unregister step is as visible as the register step was — grouped so the
    # user can tell the in-chat action apart from the terminal ones.
    chat_nexts = [(h, "run in chat so /sr unregisters") for h in sorted(reload_hints)]
    b.next_grouped([("in this terminal", terminal_nexts),
                    ("in your chat (Hermes / OpenClaw)", chat_nexts)])
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
        b.dim("Run the bridge in this terminal instead:  superresearch-agent serve")
        return 0
    ok, out = _pin_startup()
    if not ok:
        b.no(f"Couldn't pin startup: {out}")
        b.dim("Run it yourself:  superresearch-agent serve")
        return 1
    b.ok(f"Pinned to login ({autostart.kind_label()})")
    started, serr = autostart.start_detached()
    if started and _wait_bridge_up():
        b.ok("Bridge started in the background")
    elif started:
        b.warn("Bridge launched, but it's not answering yet — give it a few seconds.")
        b.dim("Check it: superresearch-agent status")
    else:
        b.warn(f"Pinned, but couldn't start it now: {serr}")
        b.dim("It starts at your next login (or run: superresearch-agent serve).")
    b.next_actions([
        ("superresearch-agent status", "check the bridge + session"),
        ("superresearch-agent retire", "stop the background bridge + remove it from login startup"),
    ])
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart the background bridge so it picks up an upgraded package (the agent
    twin of the backend `--restart`). The account session, skill, and login pin are
    left intact — this only cycles the running process onto the code on disk. The
    self-update flow calls this after a `pipx install --force`; it's also the manual
    fix when a bridge is stuck on an old build. WSL-aware."""
    rc = _delegate_lifecycle("restart", [], label="Restart")
    if rc is not None:
        return rc
    if not connect.is_continued():
        b.header("recursus", "restart the background bridge",
                 tagline_color=branding._BOLD + branding._ACCENT)
    if not autostart.is_installed():
        b.warn("Nothing to restart — the bridge isn't pinned to login.")
        b.dim("Pin + start it:  superresearch-agent resurrect")
        return 1
    ok, out = autostart.restart()
    if not ok:
        b.no(f"Couldn't restart the bridge: {out}")
        b.dim("Try: superresearch-agent retire   then   superresearch-agent resurrect")
        return 1
    if _wait_bridge_up():
        b.ok("Bridge restarted")
    else:
        b.warn("Restart issued, but the bridge isn't answering yet — give it a few seconds.")
        b.dim("Check it: superresearch-agent status")
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
        ("superresearch-agent resurrect", "run the bridge in the background + on every login"),
        ("superresearch-agent serve", "run the bridge here in this terminal (foreground)"),
    ])
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    b.header("ianua", "sign in your account", tagline_color=branding._BOLD + branding._ACCENT)
    print()
    rc = _redirect_if_wsl("Sign in from chat:  /sr login")
    if rc is not None:
        return rc
    if not _bridge_up():
        b.no("Bridge isn't running.  Start it:  superresearch-agent serve  "
             "(or: agent resurrect)")
        return 1
    if not getattr(args, "local", False):
        # Default: sign in on the SR web app (superresearch.io) — same page as /sr login.
        return _login_remote(args)
    # --local: host-local fallback (the bridge's own page, no broker round-trip —
    # but its Google window still opens on the web app's host; see config.AUTH_DOMAIN).
    url = config.login_origin() + "/login"
    runtime = prefs.get_runtime()
    if runtime:
        url += f"?runtime={runtime}"  # glow the connected runtime's watermark
    b.line(f"Opening {url}")
    b.dim("Sign in with your Super Research Google account (research-only).")
    b.dim(_local_signin_needs())
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
        b.dim(_local_signin_needs())
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
            b.warn("Account: last sign-in didn't complete  →  superresearch-agent login")
        else:
            b.warn("Account: not signed in  →  superresearch-agent login")
    else:
        b.no("Bridge: not running  →  superresearch-agent serve  (or: agent resurrect)")
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
        b.dim("Autostart: not pinned  →  superresearch-agent resurrect")
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
    # ⛔ AND THE PARKED ANNOUNCE, for the same reason and on the same path. With the
    # bridge UP its /logout handler clears it; with the bridge DOWN this is the only
    # code that runs, and it used to leave `pendingAnnounce` in prefs.json carrying
    # the account email and the research topic — immediately after telling the person
    # their session was cleared. Found by cross-verification.
    prefs.clear_pending_announce()
    return existed


def cmd_logout(_args: argparse.Namespace) -> int:
    rc = _redirect_if_wsl("Sign out from chat:  /sr logout")
    if rc is not None:
        return rc
    _logout_session()
    print("Logged out — account session cleared.")
    return 0


# ⛔⛔ ONE SENTENCE PER REFUSAL THE ASK ROUTE CAN GIVE, AND NOT THE PAIRING TABLE.
# Borrowing `_PAIR_ERRORS` is the obvious shortcut and it is wrong three times.
# Its `revoked_sharer` line ends "ask them to share it again" — which on THIS
# route is the one thing that cannot work, because being on that list is exactly
# what the refusal is; its `rate_limited` says "wait a few minutes" against a
# window that is an hour here; and its `share_cap_reached` describes a pairing
# that never started rather than a queue nobody can join.
#
# ⛔ NO DURATIONS EXCEPT THE ONE THE SERVER STATES. The cool-off after a refusal
# is a single fixed week and the route is the only thing that knows a request was
# ever refused, so naming it is honest. The per-hour ceiling is NOT named: the
# reply carries `retryAfterMs`, so the number is knowable and guessing beside it
# would be the thing this codebase has twice been bitten by.
#
# ⛔ AND `device_not_found` IS ONE ANSWER FOR FIVE STATES — no such machine, a
# private one, a half-paired one, one with no owner, one whose id was mistyped.
# It must not claim any single one of them.
_ASK_FAILURES = {
    "device_not_found":
        "that computer isn't offered publicly any more — it may have been made "
        "private, or the id may be wrong",
    "is_owner": "that one is already yours",
    "already_shared": "you can already use that computer",
    "revoked_sharer":
        "its owner removed your access to that computer before, so this is not "
        "something asking again can change",
    "share_cap_reached":
        "that computer is already shared with as many people as it can hold",
    "already_pending":
        "you have already asked for that one — it is waiting on its owner",
    "recently_denied":
        "its owner said no recently; asking again is refused for a week from "
        "the day they answered",
    "too_many_requests":
        "you have as many requests waiting as an account can have — one has to "
        "be answered or expire first",
    "device_queue_full":
        "that computer already has as many people waiting as it can queue",
    "invalid_json": "that request didn't reach the app in a form it could read",
    "device_id_required": "that isn't an id any computer could have",
    "unauthorized": "this agent's sign-in was refused — run login again",
    # ⛔ THE ROUTE'S OWN CATCH-ALL. It answers `internal_error` on any unhandled
    # throw, and with no row here both clients printed that word at the person.
    "internal_error": "the app hit a problem of its own answering that — nothing "
                      "was sent, so it is safe to try again",
}

# ⛔⛔ ANSWERING A REQUEST HAS ITS OWN TABLE AND IT IS NOT `_ASK_FAILURES`.
# Five codes appear on both routes and mean different things on each: on the ask
# route `device_not_found` means the computer is not offered publicly, here it
# means it is not YOURS any more; `is_owner` there means "already yours", here it
# means the person asking owns it; `revoked_sharer` there is about the caller,
# here it is about somebody else. A borrowed table would say the wrong true
# thing, which is worse than saying a code.
#
# ⭐ WORDED TO MATCH THE WEB APP where the web app has a sentence, because the
# same owner reads both surfaces about the same request and two descriptions of
# one refusal is how somebody concludes they are looking at two problems.
_DECIDE_FAILURES = {
    "device_not_found": "that computer isn't yours any more",
    "request_not_found":
        "there is no request from that person for that computer — it may have "
        "been answered already, or it may have run out",
    "request_mismatch":
        "that request doesn't belong to that computer — ask for the queue again "
        "and answer from what it prints",
    # ⛔⛔ THIS CODE COVERS THREE STATES, NOT ONE. The route throws it whenever
    # the row is not live, and `isLiveRequest` tests `status != "pending"` FIRST
    # — so an already-approved and an already-denied request arrive here too.
    # The old sentence said "expired" and "they are free to ask again", and both
    # are false for a denial: it landed, and a seven-day block is enforced from
    # the day it was answered. The honest sentence is the one true of all three.
    "request_not_pending":
        "that request isn't open any more — it was already answered, or it ran "
        "out. Ask for the queue again to see what is still waiting",
    "is_owner": "that person owns that computer, so there is nothing to answer",
    "revoked_sharer":
        "you removed this person from that computer before — resetting its access "
        "code is what lets them back in",
    "share_cap_reached":
        "that computer is already shared with as many people as it can hold — "
        "remove someone first",
    "invalid_json": "that answer didn't reach the app in a form it could read",
    "device_id_required": "that isn't an id any computer could have",
    "requester_required": "that isn't the id of a person who could have asked",
    "decision_required": "the app didn't get a yes or a no — nothing was answered",
    "unauthorized": "this agent's sign-in was refused — run login again",
    "internal_error": "the app hit a problem of its own answering that — nothing "
                      "about that request changed, so it is safe to try again",
}

# ⛔⛔ THE TWO LIST ROUTES NEEDED THEIR OWN TABLE AND DID NOT HAVE ONE. Every
# refusal they can give — `rate_limited` at thirty a five minutes on browse and
# sixty on the queue, `unauthorized`, `internal_error` — reached the person as
# the machine's own token, in a wave whose whole point was to stop exactly that.
# Cross-verify found it on all four surfaces at once.
# ⛔ THE PLAIN VERB FOR EACH CALLER PHRASE — see the chat client's twin table.
# ⛔⛔ FOUR SENTENCES THE PUBLIC LIST AND THE EMPTY STATE BOTH PRINT. They were
# hand-copied into the second site and the anchor sweep caught it immediately —
# three mutants that had measured one line each began matching two, which is a
# harness fault and was also a promise that the two screens would drift.
_PUBLIC_NONE_WHY_T = "     A computer is offered only when its owner switches that on."
_PUBLIC_TRUNCATED_NONE_T = ("     (There were more machines than one look can scan, "
                            "so this may not be the whole story.)")
_PUBLIC_TRUNCATED_SOME_T = ("  (there are more public computers than one look can "
                            "scan, so some may be missing)")
# ⛔ THE SAME CLAIM THE ASK ITSELF MAKES: the owner sees the NAME, and the email
# only when no name is set. This screen said "your name and email address", which
# is the phrasing the chat client's confirm was corrected away from in 7.9-2.
_PUBLIC_ASK_INVITE_T = ("     Its owner decides. They see your name — or your "
                        "email, if you have not set one.")

_PLAIN_VERBS = {
    "looked for public computers": "look for public computers",
    "asked for your requests": "ask for your requests",
}

_LIST_FAILURES = {
    "unauthorized": "this agent's sign-in was refused — run login again",
    "internal_error": "the app hit a problem of its own answering that — nothing "
                      "about your account changed",
}

# ⛔⛔ THE ROUTE WITH THE MOST WAYS TO FAIL HAD NO TABLE AT ALL. `device remove`
# printed `_err(res)` — the web app's own identifier, unwrapped — so somebody
# whose unlink was REFUSED to protect them read "couldn't remove device:
# rotation_failed". This file did not even borrow the wrong table, as the chat
# client did; it borrowed nothing.
#
# ⛔ `rotation_failed` IS NOT AN ERROR, IT IS A SAFETY REFUSAL, and it is the
# only one here that has to say why. Unlinking leaves the machine ownerless, and
# the claim route hands ownership to whoever presents a valid code against an
# ownerless machine — so if the code cannot be rotated first, going ahead would
# publish the computer to whoever already holds the old one. The route declines
# and writes nothing, which is the part worth telling somebody.
#
# `rate_limited` is absent on purpose: its wait comes from `retryAfterMs` on the
# reply, exactly as `_list_refusal` does it, and guessing a window beside a
# number the server already sent is the thing this file has twice been bitten by.
_UNLINK_FAILURES = {
    # ⛔⛔ NOT "nothing was changed", WHICH IS WHAT IT SAID. The route deletes the
    # device's pending customToken BEFORE it attempts the rotation and only then
    # returns this, so an unlink stopping here has already destroyed a handoff.
    # What is true and useful is narrower: the machine is still yours.
    "rotation_failed":
        "its access code would not change, and unlinking without a fresh one would "
        "leave the computer claimable by anyone holding the old one — so it is "
        "still linked to this account. Try again in a moment",
    "not_authorized": "that computer isn't linked to this account, so there is "
                      "nothing to unlink",
    "device_not_found": "that computer no longer exists — nothing to unlink",
    "unauthorized": "this agent's sign-in was refused — run login again",
    # ⛔ NOT "no id was given" — the bridge refuses an empty id itself, so the only
    # way this arrives is an id the app rejected as malformed.
    "deviceId_missing": "the app did not recognise that computer id — run:  "
                        "agent device list",
    "deviceId_mismatch": "that request named two different computers — run:  "
                         "agent device list",
    "auth_delete_failed": "the app could not finish retiring that computer — "
                          "nothing was changed, so it is safe to try again",
    "internal_error": "the app hit a problem of its own — nothing about your "
                      "account changed",
}


# The CLAIM route's twelve codes. `device add` printed `_err(res)` raw, so every
# one of them reached the terminal as an identifier — including the two that are
# recoverable and say how.
#
# ⭐ `pair_bootstrap_failed` EARNS ITS SENTENCE: the device DID pair; the machine
# just did not collect its token, and re-entering the SAME code finishes it. As
# a bare code it reads like a dead end, which would send somebody off to reset a
# code they do not need to reset.
_PAIR_FAILURES = {
    # ⛔ THE ALPHABET EXCLUDES I, L, O, 0 AND 1 — the five that get confused.
    "invalid_code_format": "access codes are 8 characters and never use I, L, O, 0 "
                           "or 1 — check those",
    # ⛔⛔ THE REPAIR IT NAMED MINTS A NEW COMPUTER AND LOSES ITS PEOPLE. Both of
    # these sentences sent somebody to `superresearch --pair`, which on a machine
    # that still exists does not refresh anything — it sets that machine up as a
    # NEW computer with a NEW id, and everybody it was shared with loses access.
    # The repair for a code that has run out is to press Reset again in the app,
    # which the web app's own table has said since wave 2 and this one did not.
    # ⛔ `--pair` IS STILL NAMED, and only where it is right: once the computer is
    # gone from that list there is nothing to reset and it IS a new setup.
    # ⭐ THE COMMONEST CAUSE COMES FIRST (2026-09-24): a mistyped code. A
    # first-timer who misread the code their new computer showed was sent straight
    # to reset emails they never got — re-reading the screen is the repair.
    "code_not_found": "no computer is waiting for that code — check it against the "
                      "code on that computer's screen. If it came from a "
                      "reset email, use the newest one, or press Reset again in "
                      "Settings -> Manage devices. Only if the computer is not "
                      "listed there, run:  superresearch --pair   on it — that "
                      "sets it up as a NEW computer with a new id, and nobody you "
                      "shared the old one with keeps access",
    "code_expired": "that code expired — press Reset again in Settings -> Manage "
                    "devices for a new one, and use only the newest email",
    "not_previous_owner": "that device is waiting for its previous owner to "
                          "re-pair — only they can",
    # ⛔⛔ ASKING AGAIN IS REFUSED ON EVERY PATH — the blocklist is consulted by
    # claim, by the ask route and by approve, and only a Reset or an owner-unlink
    # clears it. The remedy that used to stand here could not work.
    "revoked_sharer": "the owner removed your access to that computer, and re-using "
                      "a code or asking again cannot change that — only they can",
    "share_cap_reached": "that device is shared with as many people as it can hold "
                         "— ask the owner to remove someone first",
    # ⭐ RECOVERABLE, WITH ITS DEADLINE: the half-paired document carries a
    # five-minute TTL, after which the same code answers code_not_found.
    "pair_bootstrap_failed": "it paired, but the computer did not finish picking up "
                             "its token — run the same command again with the same "
                             "code within a few minutes; after that, run:  "
                             "superresearch --pair   on the machine",
    # ⛔ A FRESH CODE CANNOT RESTORE THE MISSING FIELD — only the handshake writes
    # it, so resetting loops forever on this same error.
    "device_secret_missing": "that machine did not finish its side of the handshake "
                             "— run:  superresearch --pair   on it again",
    "unauthorized": "this agent's sign-in was refused — run login again",
    "invalid_json": "that request didn't reach the app in one piece — try again",
    "internal_error": "the app hit a problem of its own — nothing was paired",
}


def _pair_refusal(err: str, retry_after_ms=None) -> str:
    """The sentence for one refusal from the claim route.

    `rate_limited` is not in the table above for the usual reason: the wait
    arrives on the reply as `retryAfterMs`, so it is read rather than guessed.
    """
    if err == "rate_limited":
        mins = _minutes_from_ms(retry_after_ms)
        if mins is None:
            return "too many attempts in a row — give it a minute"
        return ("too many attempts in a row — try again in about "
                f"{mins} minute{'' if mins == 1 else 's'}")
    said = _PAIR_FAILURES.get(err)
    if said is not None:
        return said
    if err.lower().startswith("not signed in"):
        return "not signed in — run:  agent login"
    if err.startswith("http_"):
        return (f"the app answered that with nothing this client can read "
                f"(HTTP {err[5:]})")
    return err or "no reason given"


def _unlink_refusal(err: str, retry_after_ms=None) -> str:
    """The sentence for one refusal from the unlink route."""
    if err == "rate_limited":
        # ⛔ "ATTEMPTS", NOT "UNLINKED". The route's limiter records an attempt
        # before it does any work, so five refusals then a sixth call hits this
        # on ZERO successful unlinks — and telling somebody they unlinked six
        # machines when they unlinked none is its own small lie.
        mins = _minutes_from_ms(retry_after_ms)
        if mins is None:
            return "too many unlink attempts in a row — give it a minute"
        return ("too many unlink attempts in a row — try again in about "
                f"{mins} minute{'' if mins == 1 else 's'}")
    said = _UNLINK_FAILURES.get(err)
    if said is not None:
        return said
    # The bridge's own refusals are SENTENCES, not codes, and key no row here —
    # the same fallback pair `_list_refusal` needs for the same reason.
    if err.lower().startswith("not signed in"):
        return "not signed in — run:  agent login"
    if err.startswith("http_"):
        return (f"the app answered that with nothing this client can read "
                f"(HTTP {err[5:]})")
    return err or "no reason given"


def _list_refusal(what: str, err: str, retry_after_ms=None) -> str:
    """The sentence for one refusal from a list route.

    ⛔ `rate_limited` CARRIES ITS OWN WAIT and it is not the ask's hourly one —
    browse allows thirty looks every five minutes — so the number has to come
    from the reply rather than from a habit.
    """
    if err == "rate_limited":
        mins = _minutes_from_ms(retry_after_ms)
        if mins is None:
            return f"you have {what} too many times in a row — give it a minute"
        return (f"you have {what} too many times in a row — try again in about "
                f"{mins} minute{'' if mins == 1 else 's'}")
    said = _LIST_FAILURES.get(err)
    if said is None:
        # ⛔⛔ THE SAME TWO DEFECTS AS THE CHAT CLIENT'S. The bridge answers a
        # signed-out caller with a SENTENCE, which keys no row here either; and
        # `what` is past tense for the rate-limit line above, so this fallback
        # printed "couldn't looked for public computers". This file did not even
        # have the one-word patch its sibling had.
        if err.lower().startswith("not signed in"):
            return "not signed in — run:  agent login"
        if err.startswith("http_"):
            return (f"the app answered that with nothing this client can read "
                    f"(HTTP {err[5:]})")
        return f"couldn't {_PLAIN_VERBS.get(what, what)}: {err or 'no reason given'}"
    return said


def _minutes_from_ms(retry_after_ms) -> "int | None":
    """Whole minutes to wait, rounded UP, or None when nothing usable came back.

    ⛔ ROUNDED UP AND AT LEAST ONE. Rounding down turns "fifty seconds" into
    "0 minutes", and "try again in 0 minutes" is a sentence that invites the
    retry it is refusing.
    """
    if isinstance(retry_after_ms, bool) or not isinstance(retry_after_ms, (int, float)):
        return None
    if retry_after_ms <= 0:
        return None
    return max(1, int((retry_after_ms + 59_999) // 60_000))


def _ask_refusal(err: str, retry_after_ms=None) -> str:
    """The sentence for one refusal code, with a wait ONLY when the reply gave one.

    ⛔ `rate_limited` IS NOT IN THE TABLE, because its honest sentence needs a
    number that lives in the reply rather than in this file. Asking is capped at
    five an hour, so the house habit of saying "a few minutes" would be wrong by
    up to fifty-five of them — and this is the first refusal in the product where
    the server actually hands over the wait.
    """
    if err == "rate_limited":
        mins = _minutes_from_ms(retry_after_ms)
        if mins is None:
            return ("you have asked for as many computers as an account may in "
                    "one hour")
        return (f"you have asked for as many computers as an account may in one "
                f"hour — the next one can go in about {mins} minute"
                f"{'' if mins == 1 else 's'}")
    said = _ASK_FAILURES.get(err)
    if said is None:
        # ⛔ THE BRIDGE HANDS OVER A STATUS, NOT A SENTENCE. It used to synthesise
        # the same phrase each client wraps it in, so an unworded failure read
        # "couldn't ask for that computer: could not ask for that computer
        # (HTTP 500)". A bare `http_<n>` is the code; this is the sentence.
        if err.startswith("http_"):
            return ("the app answered that with nothing this client can read "
                    f"(HTTP {err[5:]}) — nothing was sent")
        return f"couldn't ask for that computer: {err or 'no reason given'}"
    return said


def cmd_device(args: argparse.Namespace) -> int:
    """List the devices the account can reach, or switch the target device."""
    # ⛔ `/sr devices`, NOT `/sr device`. The singular resolves to nothing — chat
    # matches "devices" and "device list" and never the bare word — so this hint
    # sent every Windows user to the one phrasing that answers "I didn't catch a
    # Super Research request in that". Reproduced against the resolver.
    #
    # ⛔⛔ AND THE HINT HAS TO MATCH THE SUBCOMMAND. This redirect runs before the
    # dispatch below, so `agent device public|ask|requests` under WSL was answered
    # with a pointer at the OWNED device list — a different question, sent to
    # somebody who had just asked a public one. Cross-verify caught it.
    _WSL_HINTS = {
        "public": "Find a public computer from chat:  /sr are there any public computers",
        "ask": "Ask for a public computer from chat:  /sr ask for that computer",
        "requests": "See who is asking, and what you are waiting on, from chat:  "
                    "/sr who wants to use my computer",
        "approve": "Answer a request from chat:  /sr approve that request",
        "deny": "Answer a request from chat:  /sr say no to that request",
        "visibility": "Change who can find a computer from chat:  "
                      "/sr make my computer public",
    }
    rc = _redirect_if_wsl(_WSL_HINTS.get(getattr(args, "device_command", None) or "",
                                         "Manage devices from chat:  /sr devices"))
    if rc is not None:
        return rc
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1

    if getattr(args, "device_command", None) == "public":
        return _device_public()

    if getattr(args, "device_command", None) == "ask":
        return _device_ask(args.deviceId)

    if getattr(args, "device_command", None) == "requests":
        return _device_requests()

    if getattr(args, "device_command", None) in ("approve", "deny"):
        return _device_decide(args.deviceId, args.requesterUid,
                              args.device_command)

    if getattr(args, "device_command", None) == "visibility":
        return _device_visibility(args.deviceId, args.value)

    if getattr(args, "device_command", None) == "use":
        res = _bridge_post("/device/select", {"deviceId": args.deviceId})
        if res is None or res[0] != 200:
            # ⛔ `_err`, NOT `res[1].get("error")`. A reply with no body at all
            # printed the literal word None — the only branch here that reached
            # past the helper written for exactly this.
            print(f"{_NO} couldn't select device: {_err(res)}")
            return 1
        d = res[1].get("device", {})
        kind = "owned" if d.get("owned") else "shared"
        print(f"{_OK} Now running on: {d.get('name') or d.get('id')}  ({kind})")
        return 0

    if getattr(args, "device_command", None) == "add":
        with b.spinner("Pairing the device"):
            res = _bridge_post("/device/pair", {"code": args.code})
        if res is None or res[0] != 200:
            body = res[1] if res and isinstance(res[1], dict) else {}
            print(f"{_NO} couldn't add device: "
                  f"{_pair_refusal(_err(res), body.get('retryAfterMs'))}")
            return 1
        d = res[1]
        nm = d.get("deviceName") or d.get("deviceId") or "device"
        print(f"{_OK} Added {nm}{' (now selected)' if d.get('selected') else ''}.")
        return 0

    if getattr(args, "device_command", None) == "remove":
        # ⛔ 50s for the same reason the chat client waits 50: the bridge waits up
        # to 35 on this route plus a 10s refresh, and giving up first loses the
        # only copy of the rotated access code.
        res = _bridge_post("/device/remove", {"deviceId": args.deviceId},
                           timeout=50.0)
        if res is None or res[0] != 200:
            body = res[1] if res and isinstance(res[1], dict) else {}
            print(f"{_NO} couldn't remove device: "
                  f"{_unlink_refusal(_err(res), body.get('retryAfterMs'))}")
            return 1
        body = res[1] if isinstance(res[1], dict) else {}
        name = body.get("deviceName") or args.deviceId
        if body.get("action") == "left-shared":
            # ⛔ THE SHARER BRANCH CARRIES NO `deviceName` — the route omits it
            # (only the owner branch sends one), so `name` here is the raw device
            # id and the screen read "Left the shared device dev-a1c9f2." Say the
            # neutral thing rather than an id nobody recognises.
            if body.get("deviceName"):
                print(f"{_OK} Left the shared device {name}.")
            else:
                print(f"{_OK} Left that shared device.")
            return 0
        print(f"{_OK} Unlinked {name} from this account.")
        # ⛔⛔ THIS SCREEN SAID NOTHING ABOUT THE CODE AND THAT WAS THE WORSE
        # HALF. The chat client at least told the person something (which was
        # false); the terminal printed "Removed device dev-a1." and stopped, so
        # somebody who unlinked their own machine here was never told that its
        # access code had just been rotated out from under them, nor given the new
        # one — and the new one is the only thing that can re-link the machine.
        # ⛔ AND IT IS SPELLED OUT AS A CREDENTIAL. On a machine with no owner
        # the code does not merely let somebody in; it makes them the owner.
        # ⛔ `pairCode` IS THE WIRE FIELD AND STAYS. The route sends it under that
        # name; only the words on the screen move to the web app's "access code".
        code = body.get("pairCode")
        if code:
            print("  Its access code changed — the old one no longer works.")
            print(f"  New access code: {code}")
            print("  Anyone who has that code can claim this computer as its "
                  "owner. Keep it like a password.")
        else:
            # ⛔⛔ THIS USED TO SAY "the new one is on the device's own screen" AND
            # THAT WAS FALSE. `unpair-self/route.ts` says so itself: "the machine
            # cannot show it either, since the backend only ever learns a code
            # from the pairing response and cannot read the admin-only entry it
            # now lives in" — and the rotation has already removed the reader's
            # ownership, so the reveal refuses them too. There is no lookup to
            # point at, and inventing one sent people to read a dead code.
            print("  Its access code changed and the new one did not come back.")
            print("  That code cannot be looked up anywhere — this reply was the")
            print("  only copy. Run:  superresearch --pair   on the machine to use")
            print("  it again; it joins as a new computer.")
        return 0

    dr = _bridge_get("/devices")
    if dr is None or dr[0] != 200:
        # ⛔ `_err` HERE TOO. This branch printed the raw dict, so a signed-out
        # person read "list devices failed: {'error': 'not signed in — run
        # /login'}" — the repair was on screen wearing python punctuation.
        print(f"{_NO} list devices failed: {_err(dr)}")
        return 1
    devices = dr[1].get("devices", [])
    selected = dr[1].get("selectedDeviceId")
    if not devices:
        _print_no_devices()
        return 0
    print(f"Devices ({len(devices)}):")
    for d in devices:
        mark = "→" if d.get("selected") else " "
        kind = "owned" if d.get("owned") else "shared"
        # ⛔ THE BRIDGE HAS ALWAYS SENT `online` AND THIS LINE DROPPED IT.
        # "which of my computers is on?" is answered by this list and it did not
        # carry the answer, while the chat picker one file over prints it.
        state = "online" if d.get("online") else "offline"
        # ⛔⛔ ONLY ON THE ROWS IT IS TRUE OF, AND ABSENT MEANS PRIVATE. Only an
        # owner can change this and only an owner is being told anything by it,
        # so a shared row saying "private" would be reporting somebody else's
        # setting as if it were the reader's to change. And a machine paired
        # before 2026-09-04 carries no such field at all — the exact string is
        # the only value that reads as public.
        # ⛔⛔ THE SAME TWO WORDS THE COMMAND USES. This column said
        # "findable"/"hidden" while `agent device visibility` said
        # "public"/"private" and the web app's toggle says "Public computer" —
        # three vocabularies for one setting, in a file whose own comment two
        # hundred lines below says that is how somebody comes to believe there
        # are two settings.
        found = ""
        if d.get("owned"):
        # ⛔⛔ THIS READS THE BRIDGE'S ANSWER, NOT A FIRESTORE FIELD, AND THE
        # DIFFERENCE IS WHAT CARRIES IT THROUGH THE RENAME. `visibility` is
        # becoming `joinPolicy`; the bridge resolves both names into this one key
        # before any row leaves it (`_discovery_of`), so this line keeps working
        # without ever learning the new name. ⛔ Point it at a raw device document
        # and it goes silently wrong: every public computer would read private,
        # with no error anywhere.
            found = ", public" if d.get("visibility") == "public" else ", private"
        print(f"  {mark} {d.get('name') or d.get('id')}  ({kind}, {state}{found})  "
              f"id={d.get('id')}")
    if not selected:
        print("\nNo device selected — pick one:  agent device use <id>")
    return 0


def _print_no_devices() -> None:
    """THE terminal empty state.

    ⛔⛔ IT WAS ONE SENTENCE WITH NO NEXT STEP OF ANY KIND — no access-code line, no
    install link, no mention that somebody else's computer can be asked for. The
    chat client had seven wordings of this and the terminal had the shortest and
    emptiest of the lot, and nothing anywhere pinned it.

    ⭐ THE SAME THREE THINGS THE CHAT CLIENT SAYS, in this file's voice: no
    computer on this account · "Add a computer:" — the install page, then the
    access code that computer shows (or one its owner gave you) · or ask to use
    somebody else's, with the ones on offer LISTED. A guard compares the claims,
    not the punctuation — this file has no curly apostrophes and that one is full
    of them.

    ⛔ AND NOTHING AFTER THE PUBLIC SECTION (owner, 2026-09-24). The install link
    was a closing block of its own, owed by every exit; it is inside the add line
    now, printed before anything can return early.
    """
    # ⛔⛔ THE LOOK GOES FIRST AND NOTHING IS PRINTED UNTIL IT ANSWERS. Printing
    # three lines and then blocking for up to twenty seconds mid-message reads as
    # a hung command — the chat client returns its whole block at once and this
    # one stuttered. Measured by cross-verify.
    # ⛔ A FAILED LOOK MUST NOT EAT THE OFFER either: the option is true whether or
    # not the list could be read; only the list itself is conditional. A shorter
    # budget than `device public`'s own 40s, because this look is riding on a
    # command that was asked something else.
    res = _bridge_get("/devices/public", timeout=20.0)
    print("No research computer on this account yet.")
    # ⛔⛔ NOT NUMBERED, AND NOT COUNTED. An access code connects ANY computer
    # running Super Research, so this option already covers a machine of your own
    # and somebody else's private machine whose owner hands you the code — a third
    # way in that "two ways" silently denied (owner, 2026-09-20). What these
    # sections needed was NAMES, not ordinals: the defect was that the public half
    # had no noun to be recognised by, not that it had no number.
    # ⭐⭐ THE INSTALL PAGE IS THE FIRST THING THIS LINE SAYS (owner, 2026-09-24).
    # The chat client's `_ADD_A_COMPUTER`, in this file's voice: set one up at the
    # page (the commands live there, per OS, and stay current), then add the code
    # that computer shows — or one a computer's owner gave you. The page, never
    # `superresearch --pair`, and never a code "from the app".
    print("  Add a computer:      set one up at https://superresearch.io/install, then")
    print("                       add the 8-character access code the computer shows")
    print("                       (or one a computer's owner gave you) with:")
    print("                       agent device add <code>")
    # ⭐⭐ THE PUBLIC HALF IS A NAMED SECTION HERE TOO. This screen rendered the
    # list under "Or ask to use somebody else's — …" and never printed the noun,
    # exactly as the chat client did — where a relay, which preserves what the
    # client states and restructures what it leaves implicit, folded the nameless
    # section into the option above it and it vanished from the chat (owner,
    # 2026-09-20). A section with no name has nothing to survive on.
    # ⛔ AND IT IS THE LAST SECTION. The order is the chat client's — said, add a
    # computer (link first), ask — and nothing trails it: the closing install
    # block every exit used to owe is gone, because its link is already above.
    if res is None or res[0] != 200 or not isinstance(res[1], dict):
        print("  Public computers — ask to use somebody else's:  "
              "agent device public")
        return
    rows = [d for d in (res[1].get("devices") or []) if isinstance(d, dict)]
    if not rows:
        print("  Public computers — ask to use somebody else's. Nobody is "
              "offering one publicly right now.")
        print(_PUBLIC_NONE_WHY_T)
        if res[1].get("truncated"):
            print(_PUBLIC_TRUNCATED_NONE_T)
        return
    print("  Public computers — ask to use somebody else's; on offer right "
          "now:")
    for i, d in enumerate(rows, 1):
        print(_public_row(i, d))
    if res[1].get("truncated"):
        print(_PUBLIC_TRUNCATED_SOME_T)
    print("\nAsk for one by its id:  agent device ask <id>")
    print(_PUBLIC_ASK_INVITE_T)


def _public_row(i: int, d: dict) -> str:
    """One line of the public list.

    ⛔⛔ THE ID IS ON THE ROW BECAUSE THE ID IS WHAT THE NEXT COMMAND TAKES. Two
    public machines can carry the identical label — an unnamed one reads as the
    literal words "Research computer" for everybody — and the list is ordered
    online-first over a thirty-second window, so both the name and the number
    stop identifying a row the moment anything changes. The number is for
    reading; the id is for asking.
    """
    label = str(d.get("label") or "").strip() or "(unnamed)"
    state = "online" if d.get("online") else "offline"
    # ⛔⛔ `full` IS NOT DECORATION — IT IS A REFUSAL IN ADVANCE. The projection
    # sets it when the machine's people list is at its ceiling, and the ask route
    # is then guaranteed to answer `share_cap_reached`. Printing it as a quiet
    # word beside an invitation to ask spent one of five hourly asks on a certain
    # no; it says what it means now.
    full = "  (can't take anyone else)" if d.get("full") else ""
    return f"  {i:>2}  {label.ljust(34)}  {state.ljust(8)}{full}  id={d.get('deviceId')}"


def _device_public() -> int:
    """The computers other people have made discoverable."""
    # ⛔ AN EXPLICIT TIMEOUT. `_bridge_get`'s default is ten seconds, which is
    # right for the Firestore-backed routes it was written for; this one waits on
    # the bridge waiting on the WEB APP, and that call is allowed fifteen on its
    # own before a retry.
    res = _bridge_get("/devices/public", timeout=40.0)
    if res is None:
        print(f"{_NO} couldn't list public computers: {_err(res)}")
        return 1
    if res[0] != 200:
        body = res[1] if isinstance(res[1], dict) else {}
        print(f"{_NO} {_list_refusal('looked for public computers', body.get('error') or '', body.get('retryAfterMs'))}")
        return 1
    rows = res[1].get("devices") or []
    if not rows:
        print("No computers are being offered publicly right now.")
        print(_PUBLIC_NONE_WHY_T)
        # ⛔⛔ TRUNCATION MATTERS MOST ON THE EMPTY BRANCH, and it was reported
        # only on the other one. The flag is computed on the raw scan, so an
        # answer of zero rows can still mean "the scan was full and everything in
        # it was filtered" — printing a flat "nobody is offering" over that is
        # the one reading that is definitely wrong.
        if res[1].get("truncated"):
            print(_PUBLIC_TRUNCATED_NONE_T)
        return 0
    print(f"Public computers ({len(rows)}):")
    for i, d in enumerate(rows, 1):
        print(_public_row(i, d))
    if res[1].get("truncated"):
        # ⛔⛔ THIS IS NOT "YOUR LIST WAS CUT". `truncated` is computed on the raw
        # scan the app makes before it drops the ones you cannot ask for, so it
        # can be true beside a short list — and there is no next page to offer.
        print(_PUBLIC_TRUNCATED_SOME_T)
    print("\nAsk for one by its id:  agent device ask <id>")
    print(_PUBLIC_ASK_INVITE_T)
    return 0


def _device_ask(device_id: str) -> int:
    """Ask the owner of a public computer for access to it."""
    device_id = (device_id or "").strip()
    if not device_id:
        print(f"{_NO} name the computer by its id — the public list prints one "
              f"on every row.")
        return 1
    # ⛔ FORTY, LIKE ITS TWO SIBLINGS. This POST goes through the bridge to the
    # web app exactly as they do, and it was left on the thirty-second default
    # they were widened past — so the one verb that WRITES something was the one
    # most likely to report a failure on a request the app had already filed.
    res = _bridge_post("/device/ask", {"deviceId": device_id}, timeout=40.0)
    if res is None:
        print(f"{_NO} couldn't ask for that computer: {_err(res)}")
        return 1
    body = res[1] if isinstance(res[1], dict) else {}
    if res[0] != 200:
        print(f"{_NO} {_ask_refusal(body.get('error') or '', body.get('retryAfterMs'))}")
        return 1
    print(f"{_OK} Asked. Its owner decides — nothing happens on that computer "
          f"until they say yes.")
    # ⛔ SAID HERE TOO, AND NOT ONLY ON THE LIST. Somebody who already has an id
    # can run this without ever seeing the browse screen, and the disclosure was
    # printed only there — so the one path that reaches the route directly was
    # the one that never named what it discloses.
    print("     They see your name — or your email, if you have not set one.")
    # ⛔ NO POLLING ADVICE AND NO WAIT. Nothing tells this side when an owner
    # answers, and an answered request stops appearing in the list below rather
    # than turning into a "no" — so the honest next step names the list and says
    # what its silence means, which `agent device requests` then prints in full.
    print("     See what you are waiting on with:  agent device requests")
    return 0


def _decide_refusal(err: str, retry_after_ms=None) -> str:
    """One refusal from the answer-a-request route, in words.

    Same three-tier ladder as the ask: the rate limit first because only the
    server can say how long, then the table, then an unreadable reply, then the
    code itself rather than silence. ⛔ The bridge's OWN refusals — an id this
    account cannot reach, a machine somebody else owns — arrive as whole
    sentences and fall through to the last tier on purpose: they are already
    written for a person, and a table row would be a second wording of a
    sentence that has one.
    """
    if err == "rate_limited":
        mins = _minutes_from_ms(retry_after_ms)
        if mins is None:
            return ("the app is rate-limiting answers from this account just "
                    "now — nothing was answered")
        return (f"the app is rate-limiting answers from this account — try again "
                f"in about {mins} minute{'s' if mins != 1 else ''}")
    said = _DECIDE_FAILURES.get(err)
    if said is not None:
        return said
    if err.startswith("http_"):
        return ("the app answered that with nothing this client can read "
                f"(HTTP {err[5:]}) — nothing was answered")
    return f"couldn't answer that request: {err or 'no reason given'}"


def _device_decide(device_id: str, requester: str, decision: str) -> int:
    """Approve or deny one person waiting on one of this account's machines."""
    device_id = (device_id or "").strip()
    requester = (requester or "").strip()
    if not device_id or not requester:
        print(f"{_NO} name the computer and the person by their ids — "
              f"`agent device requests` prints both on every row.")
        return 1
    res = _bridge_post("/device/decide",
                       {"deviceId": device_id, "requesterUid": requester,
                        "decision": decision}, timeout=40.0)
    if res is None:
        print(f"{_NO} couldn't answer that request: {_err(res)}")
        return 1
    body = res[1] if isinstance(res[1], dict) else {}
    if res[0] != 200:
        print(f"{_NO} {_decide_refusal(body.get('error') or '', body.get('retryAfterMs'))}")
        return 1
    # ⛔ THE PERSON IS NAMED, AND THE TERMINAL IS WHERE IT MATTERS MOST — this
    # is the surface where they were identified only by an opaque id typed out
    # of a queue print that may already be stale. The chat client named them
    # from the start; this one did not, and its own resolver docstring promised
    # it would.
    name = body.get("deviceName") or device_id
    who = f"{requester}" if requester else "they"
    if body.get("decision") == "approved":
        # ⛔⛔ A STATE, NEVER AN EVENT. The route closes an already-shared request
        # as approved and writes nothing to the machine, so "you have just added
        # them" is false on one of the two branches that reach here. "They can
        # use it" is true on both.
        print(f"{_OK} {who} can use {name}.")
        print("     It shows up on their side as one of their computers.")
    else:
        print(f"{_OK} Said no to {who} for {name}.")
        # ⛔ THE COST, STATED WHERE THE PERSON CAN STILL SEE IT. The web app tells
        # the ASKER about the week and tells the owner nothing at all.
        # ⛔⛔ "THEY ARE TOLD" WAS STATED AS FACT AND THE PRODUCT CANNOT PROMISE
        # IT. The notice is best-effort — every failure is swallowed and the
        # result discarded — and delivery is gated on the asker's own User
        # updates preference, which they can switch off. The seven days ARE
        # enforced, so that half stays flat.
        print("     They cannot ask again for a week. The app tries to tell "
              "them, but")
        print("     that depends on their own notification settings. Giving "
              "them the")
        print("     access code still works if you change your mind.")
    return 0


def _device_visibility(device_id: str, value: str) -> int:
    """Make one of this account's machines findable by strangers, or hide it."""
    device_id = (device_id or "").strip()
    if not device_id:
        print(f"{_NO} name the computer by its id — `agent device` prints one on "
              f"every row.")
        return 1
    res = _bridge_post("/device/visibility",
                       {"deviceId": device_id, "visibility": value}, timeout=40.0)
    if res is None:
        print(f"{_NO} couldn't change that: {_err(res)}")
        return 1
    body = res[1] if isinstance(res[1], dict) else {}
    if res[0] != 200:
        # ⛔⛔ NOT `_list_refusal`. Its last tier is "couldn't {what}: {err}",
        # which is ungrammatical here ("couldn't changed that computer") and —
        # far worse — asserts that nothing happened OVER a payload that exists
        # to say the opposite. The bridge went to deliberate trouble to separate
        # a rules refusal from an unconfirmed write; wrapping both in "couldn't"
        # threw that distinction away one line before the person read it.
        said = body.get("error") or ""
        mins = _minutes_from_ms(body.get("retryAfterMs"))
        if not said:
            said = "the app gave no reason"
        print(f"{_NO} {said}" + (f" — try again in about {mins} minute"
                                 f"{'s' if mins != 1 else ''}" if mins else ""))
        return 1
    name = body.get("deviceName") or device_id
    state = body.get("visibility")
    # ⛔ `.get`, NOT `[]`. A 200 whose body failed to parse arrives as `{}` and
    # this was the only raw index on a server-supplied value in the file — a
    # KeyError traceback where a sentence belonged.
    word = _VISIBILITY_WORDS.get(state)
    if word is None:
        print(f"{_OK} {name} was changed, but the app did not say to what.")
        print("     Run `agent device` to see where it stands.")
        return 0
    if not body.get("changed"):
        print(f"{_OK} {name} is already {word}. Nothing to change.")
        _print_visibility_meaning(state, body.get("publicLabel"))
        return 0
    print(f"{_OK} {name} is now {word}.")
    _print_visibility_meaning(state, body.get("publicLabel"))
    return 0


# ⛔ THE WORDS ARE THE MACHINE'S OWN. `superresearch --visibility` calls these
# states Public and Private and describes them in these sentences; a second
# vocabulary for one setting is how somebody ends up believing there are two.
_VISIBILITY_WORDS = {"public": "public", "private": "private"}


def _print_visibility_meaning(state: str, public_label) -> None:
    """What the state actually means, under the line that reports it."""
    if state == "public":
        print("     Other people can find it and ask to use it. You still "
              "approve every")
        print("     person yourself.")
        # ⛔⛔ THE PUBLISHED LABEL IS NAMED, and this is not decoration. A Mac
        # nobody has renamed reports a hostname carrying its owner's own name,
        # so switching this on can publish that to every signed-in stranger.
        # The web app's toggle names it for the same reason.
        if public_label:
            print(f"     They see it as “{public_label}”.")
    else:
        print("     Nobody can find it. An access code still lets someone in "
              "without asking you.")


def _device_requests() -> int:
    """Both halves of the access-request queue: people waiting on THIS account's
    machines, and what this account is waiting on from other people.

    ⛔ The two are printed apart and never summed. They are answered by different
    people and only one of them is anybody's to act on from here.
    """
    res = _bridge_get("/devices/requests", timeout=40.0)
    if res is None:
        print(f"{_NO} couldn't list your requests: {_err(res)}")
        return 1
    if res[0] != 200:
        body = res[1] if isinstance(res[1], dict) else {}
        print(f"{_NO} {_list_refusal('asked for your requests', body.get('error') or '', body.get('retryAfterMs'))}")
        return 1
    rows = res[1].get("requests") or []
    incoming = res[1].get("incoming") or []
    # ⛔⛔ THE OWNER'S QUEUE GOES FIRST, because it is the only half anybody can
    # ACT on from here. What you are waiting on is somebody else's decision.
    if not incoming:
        # ⛔ SAID, NOT LEFT OUT. Silence about the owner's half reads as "this
        # screen does not cover that" — which is what it USED to mean, and the
        # habit is the thing being replaced.
        print("Nobody is waiting on your computers.")
        print()
    else:
        print(f"People asking to use your computers ({len(incoming)}):")
        for d in incoming:
            who = str(d.get("requesterLabel") or "").strip() or "Someone"
            what = str(d.get("deviceLabel") or "").strip() or "(unnamed)"
            print(f"     {who.ljust(28)}  wants {what}")
            # ⛔ BOTH IDS, BECAUSE BOTH ARE WHAT THE NEXT COMMAND TAKES, and
            # neither name identifies a row: a label is a snapshot from the day
            # of the ask, an unnamed machine is the identical string for
            # everybody, and a person with no display name shows as their email
            # or as a neutral word shared with anyone the lookup failed on.
            print(f"       answer with:  agent device approve "
                  f"{d.get('deviceId')} {d.get('requesterUid')}")
        # ⛔⛔ WHAT A YES MEANS AND WHAT A NO COSTS, BOTH BEFORE THE DECISION.
        # The web app puts the first on the screen beside the buttons and never
        # states the second to the owner at all — it tells the ASKER about the
        # week and leaves the person spending it uninformed.
        print("\n     Anyone you say yes to can run research on that computer — "
              "the same as")
        print("     somebody you gave an access code to. Saying no stops them "
              "asking again")
        print("     for a week; the app tries to tell them, but that depends on "
              "their own")
        print("     notification settings.")
        print("     Say no with:  agent device deny <computer id> <person id>")
        print()
    if not rows:
        print("You are not waiting on any computer.")
    else:
        print(f"Waiting on ({len(rows)}):")
        for d in rows:
            label = str(d.get("deviceLabel") or "").strip() or "(unnamed)"
            print(f"     {label.ljust(34)}  id={d.get('deviceId')}")
    # ⛔⛔ SAID ON BOTH BRANCHES, AND IT IS THE WHOLE POINT OF THE SCREEN. A row
    # here means one thing only: still waiting. A row that is GONE means answered
    # — yes or no — or seven days passed, or that computer changed hands or was
    # retired. The list carries no status at all, so reading an absence as a
    # refusal would be inventing a field that never crossed the wire.
    # ⛔⛔ IT SAYS WHICH HALF IT IS ABOUT. This sentence was written when the
    # asker's list was the only thing on the screen, and 7.9-3 put the owner's
    # queue above it without qualifying it — so every clause read as a claim
    # about people waiting on YOU as well, and every clause is false of them: an
    # incoming row also vanishes when the machine changes hands, and "a yes
    # shows up as the computer appearing in `agent device`" means nothing for a
    # machine already in your own list. The chat client was fixed and the
    # terminal was not, which is also how the two came to disagree.
    print("\n     Of the ones YOU asked for: only unanswered requests appear "
          "here. Once a")
    print("     request is answered it")
    # ⛔⛔ THE FIRST VERSION SAID "ask again and you will be told which it was",
    # and that is false for the one answer people care about. An APPROVAL makes
    # the machine one of yours, and the browse list drops machines you are
    # already on — so asking again cannot report a yes. It reports a yes by the
    # machine simply being in your own list.
    print("     leaves that half either way. A yes shows up as the computer "
          "appearing in")
    print("     `agent device`; for a no, ask for that computer again and you "
          "will be told.")
    return 0


def _doctor_row(label: str, ok_flag: bool, detail: str, warn_only: bool = False) -> None:
    mark = (branding.MARK_OK if ok_flag else (branding.MARK_WARN if warn_only else branding.MARK_NO))
    color = branding._OK if ok_flag else (branding._WARN if warn_only else branding._RED)
    print(f"  {b.c(color, mark)}  {label.ljust(10)}{detail}")


def cmd_verbose(args: argparse.Namespace) -> int:
    """Turn detailed logging on or off for the next bridge start.

    ⛔ A COMMAND AND NOT AN ENVIRONMENT VARIABLE, because the variable cannot reach
    the bridge people actually run. See `prefs.get_verbose` for the measurement.
    """
    want = (getattr(args, "state", "") or "").strip().lower()
    if want not in ("on", "off"):
        b.no("Say which:  agent verbose on   |   agent verbose off")
        return 1
    # ⛔⛔ DELEGATED LIKE THE LIFECYCLE COMMANDS, because the prefs file this writes
    # lives WHERE THE BRIDGE RUNS. On a WSL runtime the bridge and its
    # ~/.super-agent are inside the distro, so writing the pref on the Windows side
    # sets a switch the bridge will never read — the command would report success
    # and change nothing, which is the whole defect it was built to fix.
    rc = _delegate_lifecycle("verbose", [want], label="Verbose")
    if rc is not None:
        return rc
    prefs.set_verbose(want == "on")
    # ⛔ `restart`, NOT `resurrect`. Resurrect PINS the bridge to start at login and
    # starts it if it is down; it does not cycle one that is already running, and
    # the level is read once at start. So the instruction printed here used to be
    # unactionable in exactly the case it matters: a healthy pinned bridge.
    cycle = "superresearch-agent restart"
    if want == "on":
        b.ok("Detailed logging is ON for the next bridge start.")
        b.dim(f"    It writes to {config.log_path()}")
        b.dim(f"    Pick it up now:  {cycle}")
        b.dim("    Turn it off again with:  superresearch-agent verbose off")
    else:
        b.ok("Detailed logging is OFF for the next bridge start.")
        b.dim(f"    Pick it up now:  {cycle}")
    return 0


def _doctor_log_row() -> None:
    """Where the agent's own log lives, whether anything is in it, and how to make
    it say more.

    ⛔⛔ BEFORE THIS, THE PATH WAS EFFECTIVELY UNREACHABLE. Its only surface was one
    `print` in `serve()`'s startup banner, and three things make that print nothing
    a person sees: the pinned launcher runs the bridge under a launchd plist with no
    `StandardOutPath`, a systemd unit with no `StandardOutput`, or Windows
    windowless — so on the RECOMMENDED install it goes to /dev/null; the banner is
    on the BIND-SUCCESS path only, so somebody whose port is squatted or whose
    bridge is already running never reaches it; and it scrolls once before
    `serve_forever` blocks. The only other mention of the path in the whole package
    is a warning emitted when the file cannot be opened — i.e. the one case where
    reading it is not an option.

    ⛔ SO IT GOES BEFORE THE BRIDGE CHECK, deliberately. `cmd_doctor` returns early
    when the bridge is down, and a bridge that will not start is exactly when
    somebody needs this file.

    ⚠ AND IT SAYS THE LOG IS NOT IN A SUPPORT BUNDLE, because it is not and cannot
    be: the collector refuses anything outside the research computer's own log root,
    and that refusal is what the consent screen's promise is gated on. Sending it is
    a separate, opt-in step.

    ⛔⛔ AND THAT IS WHERE THIS LINE USED TO STOP BEING TRUE. It went on to say the
    file "stays on this host", which was true when it was written and stopped being
    true the day `--agent-log` shipped: that flag reads THIS EXACT PATH — one
    function, one file, no inference — and posts its tail to the app, where it lands
    beside the bundle under the same support code. So the sentence told somebody the
    opposite of what the product does, on the one screen they open because something
    has already gone wrong, and the reasoning above is exactly how it survived: the
    zip half is true, and the true half made the false half sound checked.

    ⛔ THE ZIP AND THE SEND ARE DIFFERENT CLAIMS, and only saying both keeps either
    honest. "Not in the bundle" is about what the research computer packages. "Only
    if you ask" is about this host. A reader given one of them fills in the other,
    and both directions of that guess are wrong.
    """
    # ⛔⛔ EVERY FILE THAT LEAVES, NOT JUST THE ACTIVE ONE. Since wave 8 the rotated
    # backups go up with it — up to four files — and this row stated one path and
    # one size and then said that file is what `--agent-log` sends. Somebody
    # weighing whether to send it was shown a fraction of what would go.
    from .bridge import _agent_log_paths, _file_size
    files = [(p, _file_size(p)) for p in _agent_log_paths()]
    present = [(p, n) for p, n in files if n > 0]
    total = sum(n for _p, n in present)
    path = config.log_path()
    size = total if present else None
    if size is None:
        detail = f"{path}  (nothing written yet)"
    else:
        shown = f"{size} B" if size < 1024 else f"{size // 1024} KB"
        # ⭐ The count is named only when there IS more than one, so the ordinary
        # single-file host reads exactly as it did.
        extra = f" + {len(present) - 1} rotated" if len(present) > 1 else ""
        detail = f"{path}  ({shown}{extra})"
    _doctor_row("log", size is not None, detail, warn_only=size is None)
    b.dim("              not sent with a support bundle — that archive is built on the")
    b.dim("              research computer and cannot reach this file")
    # ⛔ NAMED AS THE FLAG, NOT AS THE COMMAND. A sibling guard bans the word
    # "send-logs" from this block, because the reverse rule — no send-logs refusal
    # may point at `doctor` — was written against a sentence that pointed the wrong
    # way. The flag is the actionable half and it collides with nothing.
    b.dim("              it goes only when you ask for it, with  --agent-log")
    # ⛔⛔ AND THAT ROUTE NEEDS NO RESEARCH COMPUTER SINCE WAVE 8, which is the one
    # fact this screen's reader is most likely to need: doctor is opened when
    # something is already wrong, and "cannot reach my computer" is the commonest
    # thing that is. Until this wave the only way to send this file was beside a
    # bundle from a machine, so the person reading this had nothing they could do.
    # ⛔ FLAGS ONLY, NEVER THE COMMAND'S NAME — the sibling guard three lines above
    # bans it from this block, and the flags are the precise half anyway.
    b.dim("              add  --none  and it goes on its own, with no computer "
          "involved")
    # ⛔⛔ ONLY WHEN THEY DISAGREE. On every ordinary host HERMES_HOME is unset and
    # this row does not exist; on the fleet it is set to the SAME directory and the
    # row still does not exist. A row that printed either way would be one more line
    # to scroll past on the one screen whose whole job is to show what is wrong.
    split = config.home_split()
    if split:
        _doctor_row("homes", False, f"the chat host's home is {split}", warn_only=True)
        b.dim(f"              this log is written under {Path.home()} instead, and "
              "that is")
        b.dim("              the file --agent-log sends — anything written under the "
              "other")
        b.dim("              home does not reach support")
    # ⛔ THE COMMAND, NOT THE VARIABLE. This line used to name SUPER_AGENT_VERBOSE,
    # which is unactionable on the recommended install: the launcher writes no
    # environment, so a variable set in a shell profile never reaches the bridge it
    # starts. Telling somebody to do a thing that cannot work is worse than telling
    # them nothing, because they stop looking for the real answer.
    if not (config.VERBOSE or prefs.get_verbose()):
        b.dim("              for more detail:  superresearch-agent verbose on")
    else:
        b.dim("              detailed logging is ON (superresearch-agent verbose off)")


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

    _doctor_log_row()

    # ⛔ SAY IT BEFORE THE BRIDGE ROW, because it is the reason the bridge row is
    # about to be wrong. A refused SUPER_AGENT_BRIDGE_PORT sends this command and
    # the bridge to two different ports, and every symptom of that is
    # indistinguishable from "the bridge is down".
    if config.BRIDGE_PORT_REJECTED:
        # ⚠ NINE CHARACTERS OR FEWER. `_doctor_row` pads with `ljust(10)`, so an
        # eleven-character label renders welded to its own text
        # ("bridge portignoring SUPER_AGENT_BRIDGE_PORT ...").
        _doctor_row("port", False,
                    f"ignoring SUPER_AGENT_BRIDGE_PORT {config.BRIDGE_PORT_REJECTED!r} "
                    f"— using {config.BRIDGE_PORT}")
    health = _bridge_get("/healthz")
    if health is None:
        # ⛔⛔ NAME THE ORIGIN IT ACTUALLY PROBED. The incident this stretch came
        # from was an inherited SUPER_AGENT_BRIDGE_PORT=9 — numeric, in range, and
        # therefore ACCEPTED, so the refused-port row above never prints for it.
        # Without the origin here, `doctor` answers a person whose client and
        # bridge are on two different ports with a bare "down", which is exactly
        # what it says when nothing is wrong with the port at all.
        _doctor_row("bridge", False,
                    f"down at {config.bridge_origin()} "
                    f"(run: superresearch-agent serve)")
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
        _doctor_row("account", False, "not signed in (run: superresearch-agent login)")
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
    if out.get("tooLarge"):
        # Past every chat platform's upload ceiling even re-encoded — there is no
        # local file to print, so show the permanent link instead of "→ None".
        print(f"{_OK} Podcast “{out.get('title')}” is too large to send as a file "
              f"({out.get('sizeBytes', 0):,} bytes).")
        share = out.get("shareUrl")
        print(f"     Listen here: {share}" if share
              else "     Ask for the run's links to get the podcast link.")
        return 0
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
                # A redacted media marker (e.g. audio_file, whose tokenized Storage
                # URL the bridge strips) has no url — it's not a shareable link, so
                # skip it. Use .get throughout: never assume every event has a url.
                url = e.get("url")
                if not url:
                    continue
                key = (e.get("kind"), url)
                if key not in seen:
                    seen.add(key)
                    print(f"  🔗 {e.get('label') or e.get('kind')}: {url}")
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
                  "(remove the pin with: superresearch-agent retire).")
        return 0
    print(f"{_NO} couldn't stop the bridge: {_err(res)}")
    return 1


# ── send logs ────────────────────────────────────────────────────────────────
#
# ⛔⛔ WHY THERE IS A CONFIRMATION STEP AT ALL, when this is a terminal and the
# person typed the command themselves. The machine refuses a request that does
# not carry `consent: true`, and that flag is a claim that somebody was SHOWN
# what leaves their computer. On the web app the modal is what makes the claim
# true. Here the printed plan is — so the plan is printed BEFORE the flag is
# ever set, and `--yes` skips the prompt, never the printing. A surface that
# sets the flag without showing the words is forging it.

# ⭐ TWO TABLES, ONE CONTRACT. The chat skill (`skill/scripts/sr.py`) must be
# stdlib-only and cannot import this module, so it carries its own copy of these
# sentences. `test_send_logs_cli_0825.py` reads both files and fails if either
# grows a case the other lacks — a person told nothing at all is the failure
# this feature is least able to survive, and it is the one duplication invites.
_SEND_LOGS_FAILURES = {
    # ⛔⛔ NO DURATION, AND THAT IS THE FIX. The refusal row names the class and
    # nothing about time — the seconds are computed on the machine, logged
    # there, and never written — so no client can know which of its TWO
    # windows fired. Somebody refused for their own second press waits up to
    # SEND_LOGS_COOLDOWN_SEC (600s); somebody refused because a CO-TENANT went
    # first waits only SEND_LOGS_MACHINE_FLOOR_SEC (60s). "Give it ten minutes"
    # was written for the first and said to both, overstating by ten times on
    # the one surface whose normal caller is a sharer on a shared computer.
    #
    # ⭐ AND IT STATES THE RULE RATHER THAN GUESSING THE INSTANCE. An earlier
    # draft said "perhaps for someone else who uses it", which is a claim
    # about WHO — and on a machine nobody else uses, refusing an owner's own
    # second press, it is simply wrong. What is true in every case is that
    # the limit is the machine's, not the account's.
    "CooldownActive": "that computer built a bundle very recently, and its "
                      "limit counts everyone who uses it — so it may not have "
                      "been you. Try again shortly",
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
    # ⛔ NOT `--doctor`. Measured: `run_doctor` prints no bundle path anywhere;
    # its closing line points at `--send-logs`, and the path is printed only by
    # `--send-logs` itself, after building a NEW bundle — never the one this
    # sentence is about. The fork's copy stopped honestly at "still on that
    # computer", so the wave shipped two contradictory sentences for one error.
    "UploadFailed": "the bundle was built but could not be uploaded — it is "
                    "still on that computer, under its Super Research logs "
                    "folder",
}

_SEND_LOGS_UNKNOWN = ("that computer refused the request and gave a reason we "
                      "do not have a sentence for")


def _send_logs_failure(error_class: str) -> str:
    """A refusal in words. ⛔ NEVER an empty string and never the bare class
    name: an error nobody can read is the same as no error at all, and this is
    the surface a person reaches only because something else already went
    wrong."""
    known = _SEND_LOGS_FAILURES.get(str(error_class or ""))
    if known:
        return known
    return f"{_SEND_LOGS_UNKNOWN} ({error_class})" if error_class else _SEND_LOGS_UNKNOWN


def _size_words(n) -> str:
    """Bytes as something a person can weigh a decision against."""
    try:
        size = float(n or 0)
    except (TypeError, ValueError):
        return "unknown size"
    for unit, step in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if size >= step:
            return f"{size / step:.1f} {unit}"
    return f"{int(size)} bytes"


def _run_label(row: dict) -> str:
    """⭐ The title if this account still holds one, otherwise the date. A run
    whose research document is gone keeps its row — those logs are still on
    that disk and are often exactly the ones worth sending."""
    title = (row.get("title") or "").strip()
    if title:
        return title
    started = (row.get("startedUtc") or "").strip()
    return f"a run from {started[:10]}" if started else "an unnamed run"


# ⭐ THE ONE NUMBER THAT IS NOT A RUN. The list is printed 1..n, so zero has
# never addressed anything — and unlike a word it cannot collide with a run name,
# which is why it is the slot the agent's own log gets rather than a keyword.
_AGENT_LOG_TOKEN = "0"

# ⭐ AND THE ONE WORD. `--runs all` used to fail with "isn't holding a run called
# “all”" — a sentence naming a run that never existed — while the flag's own help
# said the default was all of them. Somebody who types the obvious word deserves
# the obvious answer, and "all" is not a legal run name (`_RUN_NAME_RE` on the
# bridge, and every name the machine mints carries a timestamp).
_ALL_TOKEN = "all"


def _resolve_selection(rows: list, spec: str | None) -> "tuple[list[str], bool] | None":
    """Turn `--runs` into (run names, whether the agent's own log was asked for),
    or None with a printed reason.

    Accepts the numbers printed beside the list AND the names themselves,
    because both are things a person will reasonably type — the numbers are on
    screen and the names are what the machine calls them. Plus two tokens that
    are not runs at all: `0`, this host's own agent log, and `all`.

    ⛔ REFUSES ON ANYTHING IT CANNOT PLACE. Silently dropping an entry would
    send fewer runs than were asked for and report success, which is the one
    direction this must not fail in.

    ⛔⛔ AND `0` IS NOT A RUN, SO IT IS NOT COUNTED AS ONE. It comes back in the
    second slot rather than in the list of names, because everything downstream
    of the names — the size total, the "N run(s)" sentence, the machine's own
    refusal to build an empty archive — is about material on the RESEARCH
    computer, and this is a file on the host running the command. Folding it in
    would overstate what that computer was asked for by exactly one."""
    known = {r.get("name") for r in rows}
    picked: list[str] = []
    wants_agent_log = False
    for token in (spec or "").split(","):
        token = token.strip()
        if not token:
            continue
        if token == _AGENT_LOG_TOKEN:
            wants_agent_log = True
            continue
        if token.lower() == _ALL_TOKEN:
            # ⛔ EVERY LISTED RUN, not every run the computer holds — the list is
            # the published index and it says so itself when it is short of the
            # whole ("only the most recent are listed"). Promising more than the
            # rows in hand would be a claim about material nobody has seen.
            for row in rows:
                if row.get("name") not in picked:
                    picked.append(row.get("name"))
            continue
        # ⛔ A LEADING SIGN IS STILL A NUMBER TO A PERSON. `"-1".isdigit()` is
        # False, so a negative fell through to the name branch and was refused
        # with "isn't holding a run called “-1”" — a sentence about a run name
        # nobody typed. It is out of range, and that is what it should say.
        # ⛔ `isdecimal`, NOT `isdigit`. "²".isdigit() is True and int("²")
        # raises, so a superscript reached `int()` and left a traceback on the
        # screen instead of the sentence this function exists to print. And at
        # most ONE sign: `lstrip("+-")` accepted "+-1", which `int()` also
        # refuses. Everything that is not a plain signed integer falls to the
        # name branch, which already has a sentence for it.
        body = token[1:] if token[:1] in "+-" else token
        if body.isdecimal() and body.isascii():
            index = int(token)
            if not 1 <= index <= len(rows):
                # ⛔ `0` REACHES HERE ONLY SPELLED SOME OTHER WAY — "00", "-0",
                # "+0". The bare token was taken above as the agent's log; these
                # are not that token and are not runs either, so the ordinary
                # out-of-range sentence is the true one. No special case: a
                # second sentence for a typo nobody types is a branch no test
                # can justify.
                print(f"{_NO} There is no run {index} in that list.")
                return None
            name = rows[index - 1].get("name")
        elif token in known:
            name = token
        else:
            print(f"{_NO} That computer isn't holding a run called “{token}”.")
            return None
        if name not in picked:
            picked.append(name)
    return picked, wants_agent_log


def _print_agent_log_choice() -> None:
    """The one numbered choice that is not on the research computer.

    ⛔⛔ ON SCREEN, OR IT IS NOT AN OFFER. `--agent-log` has existed since
    2026-08-26 and reaches only somebody who already knows it does: it is in
    `--help` and nowhere a person doing this task is looking. The list is what
    they read while deciding, so the choice is numbered and printed beside it.

    ⛔⛔ OUTSIDE THE MACHINE'S TABLE, AND THAT IS THE WHOLE REASON THIS IS A
    SEPARATE FUNCTION. Every row in that table is material on the RESEARCH
    computer; this file is on the host running the command, and the two are
    routinely not the same machine. A row indented into that table would say the
    research computer holds it — the exact confusion a sibling guard already
    polices in the consent copy.

    ⚠ IT USED TO SAY "BELOW THE LIST" AND IT NOW PRINTS ABOVE IT (2026-09-20).
    The rationale did not change and is not weakened — it is strengthened: row 0
    now sits above the `Research computer: <name>` header entirely, so it is not
    merely un-indented from that machine's table, it is outside the scope of the
    line that names the machine at all. What changed is the reason for the
    position. Printing 0 LAST handed a relay a list that counts down (1, 2, 0),
    which no assistant will show a person; one renumbered it into its own scheme
    and the person then answered in numbers that were not this command's. Reading
    order now matches numbering order, so a relay that preserves order is correct
    by construction. The chat twin made the same move for the same reason.

    ⛔ AND IT PRINTS ON EVERY BRANCH, including the two where the list is empty.
    The no-runs cases are when somebody is most likely to want this — the trouble
    is reaching the computer at all — and they are precisely the branches that
    print no list to hang a row off. Offering it only when there is something
    else to offer is how the flag became invisible in the first place."""
    # ⛔ "MAY NOT BE", NOT "IS NOT". The recommended install puts the agent and
    # the backend on the SAME machine — `_local_superresearch()` exists because
    # that is the standard setup — so asserting they differ is false for most
    # people reading it, and a claim that is plainly wrong on your own screen
    # teaches you to discount the rest of the plan.
    # ⭐ "Run 0", NOT A BARE DIGIT — the same label the chat twin prints, for a
    # reason that is the chat's and not this screen's (a relay cannot re-wrap a
    # number that rides inside the text). It is carried here anyway because the
    # two clients share one selection vocabulary: `_resolve_log_selection` takes
    # the same tokens on both, and a person who reads "Run 0" in one place and
    # "0" in the other has been shown two names for one row.
    print("  Run 0  the log from the agent on THIS host — the machine you are "
          "typing on,")
    print("         which may not be that computer")


def _print_held_runs(rows: list) -> None:
    for i, row in enumerate(rows, 1):
        started = (row.get("startedUtc") or "")[:16].replace("T", " ")
        print(f"  Run {str(i).ljust(2)}  {_run_label(row)[:40].ljust(40)}  "
              f"{started.ljust(16)}  {str(row.get('status') or '?').ljust(10)}  "
              f"{_size_words(row.get('sizeBytes'))}")


def _await_bundle(code: str, seconds: int) -> "tuple[int, bool]":
    """Poll the row until the machine finishes, or say what is still unknown.

    Returns (exit code, whether the bundle actually LANDED).

    ⛔⛔ TWO ANSWERS, BECAUSE ZERO MEANS TWO THINGS. A timeout exits 0 on purpose
    — running out of patience is not a failure and saying so would be a lie about
    somebody else's computer — so the exit code alone cannot tell "the bundle
    arrived" from "we stopped waiting for it". The agent-log upload may only
    follow a bundle that arrived, and the caller had nothing but the exit code to
    ask; it uploaded on both.

    ⛔⛔ RUNNING OUT OF PATIENCE IS NOT A FAILURE, and saying so would be a lie
    about somebody else's computer. Worker 1 deletes the command before acting
    on it, so between the request and the row there is a window in which
    neither exists; on a machine that is asleep that window is however long it
    stays asleep. The support code is already valid and the bundle may still
    land — so the timeout prints how to look again, not an error."""
    deadline = time.time() + max(0, seconds)
    seen_any = False
    while time.time() < deadline:
        res = _bridge_get(f"/logs/bundle?code={code}", timeout=15.0)
        row = res[1].get("row") if (res and res[0] == 200) else None
        if row:
            seen_any = True
            status = str(row.get("status") or "")
            if status == "done":
                # ⛔ "THAT computer", not "this" — the machine is the research
                # computer, which is usually NOT the one this command is typed on.
                # Every other sentence in this command says "that"; the one line
                # reporting what actually left said "this", and the test pinning
                # it was named for the research machine, so the harness enshrined
                # the slip rather than catching it.
                machine = " plus that computer's own logs" if row.get("machineIncluded") else ""
                print(f"{_OK} Sent — {int(row.get('runCount') or 0)} run(s){machine}, "
                      f"{_size_words(row.get('sizeBytes'))}.")
                print(f"    Quote {code} when you report the problem.")
                return 0, True
            if status == "failed":
                print(f"{_NO} That computer couldn't send: "
                      f"{_send_logs_failure(row.get('errorClass'))}.")
                return 1, False
        time.sleep(2)
    if seen_any:
        print(f"  Still packaging. Check again with:  agent send-logs --status {code}")
    else:
        # ⛔ Distinguished on purpose. No row at all after the wait means the
        # request may never have been picked up — an asleep machine, or a build
        # too old to understand it — and telling somebody "still packaging"
        # when nothing is packaging sends them away to wait for nothing.
        print("  That computer hasn't picked the request up yet — it may be "
              "asleep or offline.")
        print(f"  Check again with:  agent send-logs --status {code}")
    return 0, False


def cmd_send_logs(args: argparse.Namespace) -> int:
    """Ask a research computer to package its logs and upload them.

    ⛔ WHAT THIS SENDS IS DECIDED BY THAT COMPUTER, NOT BY THIS COMMAND. A
    request names runs; the machine matches them against what it holds FOR THE
    PERSON ASKING and refuses anything else. On a shared box — a fleet
    especially — that is the difference between sending your own logs and
    sending everyone's."""
    if not _bridge_up():
        print(f"{_NO} Bridge isn't running. Run:  agent serve   then   agent login")
        return 1
    # ⛔ READ BEFORE THE STATUS BRANCH, which now honours it. Reading it only in
    # the send path is how the flag came to parse and do nothing here.
    agent_log = bool(getattr(args, "agent_log", False))
    if args.status:
        code = str(args.status).strip().upper()
        res = _bridge_get(f"/logs/bundle?code={code}", timeout=15.0)
        if res is None or res[0] != 200:
            print(f"{_NO} {_err(res)}")
            return 1
        row = res[1].get("row")
        if not row:
            print(f"Nothing recorded for {code} yet.")
            return 0
        status = str(row.get("status") or "?")
        if status == "failed":
            print(f"{_NO} {code}: {_send_logs_failure(row.get('errorClass'))}.")
            return 1
        if status == "done":
            print(f"{_OK} {code}: sent — {int(row.get('runCount') or 0)} run(s), "
                  f"{_size_words(row.get('sizeBytes'))}.")
            # ⛔⛔ THE SECOND STEP, AND THE TERMINAL HAD NONE. The chat client has
            # always had it — it is the command that client PRINTS to the
            # assistant — but here the flag parsed, did nothing, said nothing and
            # exited 0. Both routes out of a wait that did not finish dead-ended
            # because of it: the timeout sentence has nothing to offer, and
            # `--no-wait`'s "re-run without --no-wait" mints a NEW request that
            # the machine refuses for ten minutes.
            if agent_log:
                # ⛔⛔ THE PLAN WAS PRINTED BY A DIFFERENT COMMAND, AND NOTHING
                # CHECKED THAT IT EVER WAS. This is the second step, reached with
                # a support code and a flag — so an assistant that never showed
                # the person what is in this file can upload it from here, and the
                # only thing standing in the way is a directive it is asked to
                # follow. The facts are cheap; they travel with the flag instead.
                for _fact in _agent_log_fact_lines():
                    print(_fact)
                _send_agent_log(code)
            return 0
        if agent_log:
            # ⛔ SAID, NOT SILENTLY DROPPED. The upload is refused until the row
            # lands, by design; a person who asked for it deserves to know this
            # call was not the one that did it.
            # ⛔⛔ "CAN ONLY FOLLOW A BUNDLE" STOPPED BEING TRUE IN WAVE 8, and
            # this fires in exactly the state the standalone route exists for: the
            # bundle has not landed, so the thing they asked for is stuck behind a
            # machine they may not be able to reach at all. The attached route is
            # still the one that puts it BESIDE this bundle; it is no longer the
            # only way to send the file.
            print("    The agent's own log hasn't gone yet — attaching it to this "
                  "bundle needs")
            print("    the bundle to land first. Ask again with the same code once "
                  "this shows done,")
            print("    or send the log on its own now:  agent send-logs "
                  "--agent-log --none")
        print(f"{code}: {status}.")
        return 0

    # ⛔⛔ BEFORE THE RUN LIST, AND THAT IS THE POINT. `/logs/runs` resolves a
    # selected computer and refuses without one, so asking it first would make the
    # one request that needs no machine impossible for the people who have none.
    if _agent_log_only_request(args):
        owned_hint, hint_name = _agent_log_machine_hint(args)
        return _send_agent_log_alone(args, offer_machine=owned_hint, name=hint_name)

    path = "/logs/runs" + (f"?deviceId={args.device}" if args.device else "")
    res = _bridge_get(path, timeout=30.0)
    if res is None or res[0] != 200:
        print(f"{_NO} {_err(res)}")
        return 1
    body = res[1]
    rows = body.get("runs") or []
    # ⛔⛔ THE MACHINE THE LIST CAME FROM, CARRIED ONTO THE SEND — never resolved
    # a second time. Showing and sending are two round trips, and with no
    # deviceId the bridge picks the selected machine each time: a selection that
    # changes in between (in the app, or because the old one stopped being
    # reachable) would print one computer's runs and then send from another. The
    # person consented to what they were shown, so what they were shown is what
    # has to be sent.
    device_id = str(body.get("deviceId") or "") or (args.device or "")
    name = body.get("deviceName") or device_id or "that computer"
    owned = bool(body.get("owned"))

    # ⛔ ROW 0 FIRST, THEN THE LINE THAT NAMES THE MACHINE. The header scopes
    # everything below it to the research computer, and row 0 is not on it.
    _print_agent_log_choice()
    print(f"Research computer: {name}")
    if not body.get("published"):
        # ⛔⛔ NOT "it holds none of your runs". The document is absent, which
        # means we cannot see the list — a machine that has not published one
        # yet, or one on a build that never does. Saying the other thing
        # accuses a computer of having lost logs it may be holding right now.
        print("  That computer hasn't told us which runs it still holds.")
    elif not rows:
        print("  It isn't holding logs for any of your runs.")
    else:
        _print_held_runs(rows)
        if body.get("truncated"):
            print("  (only the most recent are listed — it holds more)")

    if args.list:
        return 0

    picked_agent_log = False
    names: list[str] = [r.get("name") for r in rows]
    if args.runs:
        picked = _resolve_selection(rows, args.runs)
        if picked is None:
            return 1
        names, picked_agent_log = picked
    # ⛔⛔ AFTER THE SELECTION, NOT INSTEAD OF IT. `--none` used to take the whole
    # branch, so `--none --runs 0` never ran the resolver at all: the agent-log
    # token was dropped, the plan printed "The agent's own log on this host is NOT
    # included", and a spec the resolver would have refused (`--none --runs 99`)
    # was accepted in silence. The chat client already had this order, so the two
    # clients answered the same words differently — on the surface whose whole
    # claim is that they do not.
    #
    # ⛔ AND IT STILL WINS OVER THE RUNS, which is what `--none` has always meant
    # and what its help says. What it must not clear is a choice that is not a run
    # and not on that computer.
    if args.none:
        names = []

    machine = bool(args.machine)
    # ⛔ EITHER ROUTE, NEVER ONE OVERRIDING THE OTHER. `--agent-log` is the flag
    # this shipped with and `--runs 0` is the row now printed in the list; they say
    # the same thing, and a person who does both must not be silently answered
    # "no" by whichever the code happened to read second.
    agent_log = agent_log or picked_agent_log
    if machine and not owned:
        # Refused here as well as at the bridge, so the sentence arrives before
        # a round trip rather than after one.
        print(f"{_NO} That computer's own logs belong to whoever owns it.")
        print("    Ask again without --machine and you will still get every "
              "run of yours it holds.")
        return 1
    if not names and not machine:
        # ⛔⛔ IT USED TO BE REFUSED HERE, AND WAVE 8 TURNED THAT INTO A SEND. The
        # old sentence — "can only go up beside a bundle from that computer" — was
        # true about the transport and useless to the person reading it: this
        # branch is reached when that computer is holding nothing of theirs, which
        # is one of the two states in which no bundle can be built at all. The log
        # has a route of its own and a support code of its own now, so the thing
        # they asked for happens instead of being explained away.
        if agent_log:
            # ⛔ THE MACHINE OFFER SURVIVES AND IS STILL OWNER-ONLY. `--machine` is
            # refused for a non-owner a few lines above, so offering it to one
            # sends them round the circle an earlier wave closed here.
            return _send_agent_log_alone(args, offer_machine=owned, name=name)
        print(f"{_NO} There's nothing to send.")
        if owned:
            print("    To send that computer's own logs instead, add --machine.")
        return 1

    total = sum(int(r.get("sizeBytes") or 0) for r in rows if r.get("name") in names)
    print()
    print(f"This will send {len(names)} run(s) ({_size_words(total)}) from {name}.")
    if machine:
        print("It will ALSO include that computer's own logs — its pairing and "
              "sign-in records and its raw activity trail, which cover every "
              "run it has ever done, for everyone who uses it.")
    else:
        print("That computer's own logs are NOT included.")
    # ⛔⛔ A DIFFERENT COMPUTER, WHICH IS WHY IT IS ITS OWN SENTENCE AND NOT AN ITEM
    # IN THE LIST BELOW. Every other line in this plan is about material leaving the
    # RESEARCH computer; the agent's log is on the host running this command, and
    # the two are frequently not the same machine. The app deliberately keeps
    # retention out of its `consentIncluded` list for the same structural reason —
    # every entry in that list is read as another thing leaving the same place.
    #
    # ⛔ AND THE WORDING AVOIDS "this computer's own logs" ON PURPOSE. A guard bans
    # that exact phrase across this file, sr.py and bridge.py, because it reads as
    # the RESEARCH computer to somebody running the command from a third machine.
    # ⛔⛔ --no-wait CANNOT SEND IT, SO IT MUST NOT CLAIM TO. The upload may only
    # follow the machine's row, and `--no-wait` is the choice not to wait for
    # that row — so the plan used to describe three things about a file this
    # invocation would then decline to send, and only mention that after the
    # person had already agreed.
    if agent_log and args.no_wait:
        print("The agent's own log will NOT go on this run: attaching it needs "
              "that computer's bundle to land, and --no-wait does not wait for it. "
              "Finish it later with:  agent send-logs --status <CODE> --agent-log — "
              "or send it on its own:  agent send-logs --agent-log --none")
    elif agent_log:
        print("It will ALSO include the log from the agent on THIS host — the "
              "program running this command. That is a connection and sign-in "
              "record, not research content, and it never leaves unless asked for.")
        # ⛔⛔ WHOSE, NOT ONLY WHAT. The machine-log sentence four lines above
        # names the people its material covers — "for everyone who uses it" — and
        # this one named nobody, on the surface where that fact is LESS obvious,
        # not more: a research computer is understood to be shared, and the host
        # somebody happens to be typing on is not. A second person who signed in
        # here is in this file, and nothing gates the upload on who owns the host,
        # because an agent host has no owner to ask. So it is said instead.
        # ⛔⛔ ONE SOURCE WITH THE STANDALONE PLAN, which prints the same three
        # sentences. A second hand-written copy is how one of them quietly stops
        # being said on one of the two paths — see `_agent_log_fact_lines`.
        for _fact in _agent_log_fact_lines():
            print(_fact)
    else:
        print("The agent's own log on this host is NOT included.")
    # ⛔⛔ THE THREE FACTS THE APP'S MODAL NAMES AND THIS PLAN DID NOT. The header
    # of this section claims the printed plan makes `consent: true` as true as
    # the modal does. It did not: `consentIncluded` in the web app names four
    # things that always leave, and only the first — topics and titles — was
    # conveyed here, by the run list itself. A claim of equivalence that is not
    # equivalent is the forging this file exists to prevent.
    print("Also going, from the runs you picked: links that open those results — "
          "anyone holding one can read them; the email address on your account; "
          "and what the agent screens showed while those runs were working.")
    # ✅ THE RETENTION LINE ARRIVED 2026-08-26, WITH THE RULE AND NOT BEFORE IT.
    # This surface printed it when it was first written, in three places, while
    # no bucket lifecycle rule existed anywhere — an untrue retention claim in
    # the one screen whose whole job is to be true about what leaves a computer.
    # It was removed, and held out until the rule was applied AND read back by
    # two tools (the ship-time runbook, §1 `verified:`). That gap is the whole
    # point: the sentence is identical, and only one version of it was honest.
    #
    # ⛔ IT IS ABOUT THE LOGS, NOT ABOUT THE RECORD. The rule deletes the bundle
    # in the bucket. The index row that names it survives — its own TTL was
    # never deployed — but the rules bound that row to a code, a device, a
    # status, counts and timestamps, so it carries nothing from the logs. Say
    # the material goes; do not extend it to "we keep no record".
    print("It is deleted automatically 30 days after it arrives.")
    print("Only Super Research support can read them.")

    # ⛔ The plan above is printed unconditionally; only the ASKING is skipped.
    if not _decide(None, bool(args.yes), "Send these logs?", default=False):
        print("Nothing was sent.")
        return 1

    with b.spinner("Asking the computer"):
        sent = _bridge_post("/logs/send", {
            # Always the machine the list came from — see above.
            "deviceId": device_id,
            "runNames": names,
            "includeMachine": machine,
            # ⛔ Set HERE and nowhere else — this is the line that claims a
            # person was shown what leaves their computer, and it sits directly
            # under the printing and the prompt that make the claim true.
            "consent": True,
        }, timeout=30.0)
    if sent is None or sent[0] != 200:
        print(f"{_NO} {_err(sent)}")
        return 1
    code = sent[1].get("code", "")
    print(f"{_OK} Asked. Support code: {code}")
    if args.no_wait:
        print(f"    Check with:  agent send-logs --status {code}")
        if agent_log:
            # ⛔ NOT SENT ON THIS PATH, AND SAID SO. The agent's log may only go up
            # after the machine's row lands, and --no-wait is the choice not to wait
            # for that. Sending it anyway would put an object in a folder no row
            # names yet, where the app's Clear-logs could never find it.
            print("    The agent's own log was not sent — attaching it needs "
                  "that computer's")
            print(f"    bundle to land. Finish it with:  agent send-logs "
                  f"--status {code} --agent-log")
            print("    Or send it on its own, with no computer involved:  agent "
                  "send-logs --agent-log --none")
        return 0
    rc, landed = _await_bundle(code, args.wait)
    if agent_log:
        # ⛔⛔ ONLY BESIDE A BUNDLE THAT ARRIVED. This call used to be
        # unconditional on `rc`, and the machine's refusals do not stop it: the
        # row exists and carries a deviceId before it is patched to `failed`, so
        # the bridge's ordering check passes and the log goes up ALONE, into a
        # support-code folder with no bundle in it. That is exactly what the
        # refusal fifty lines above tells a person cannot happen — and the
        # commonest refusal here, the machine's unkeyed 60-second floor, is
        # tripped by whoever else uses that computer, so it is the ordinary case
        # on a shared box rather than the edge one.
        if landed:
            _send_agent_log(code)
        else:
            # ⛔ `landed`, NOT `rc == 0`. A timeout also exits 0, and uploading
            # then puts an object under a code whose row nobody has confirmed —
            # the folder the app's Clear-logs lists may not exist yet.
            print("    The agent's own log was not sent — attaching it needs a "
                  "bundle that")
            print(f"    arrived. Finish it with:  agent send-logs --status "
                  f"{code} --agent-log")
            print("    Or send it on its own, with no computer involved:  agent "
                  "send-logs --agent-log --none")
    return rc


def _agent_log_fact_lines() -> "list[str]":
    """What a person is told before this file leaves.

    ⛔⛔ ONE SOURCE, BECAUSE IT IS PRINTED FROM TWO PLACES NOW — beside a machine's
    bundle and on its own. A guard compares these CLAIMS against the chat client's
    twin (the two files punctuate differently on purpose, so the comparison is of
    the fact and never of the string); a second hand-written copy is how one of
    them quietly stops being said on one of the paths.
    """
    return [
        # ⛔⛔ WHOSE, NOT ONLY WHAT. A second person who signed in here is in this
        # file, and nothing gates the upload on who owns the host, because an agent
        # host has no owner to ask.
        "It covers everyone who signed in through this agent, not only you — "
        "there is no owner to ask on a machine like this, so nothing checks.",
        # ⛔⛔ THE ROTATED COPIES GO TOO, SINCE WAVE 8, and this sentence moved with
        # the material rather than after it. It said "since that file last rotated"
        # while the reader sent the active file alone; that understates what leaves
        # now, on the one screen whose whole job is to be true about it.
        "The rotated copies go too, not only the newest file, so it reaches back "
        "further than the problem you are reporting.",
        # ⛔⛔ NAMED, BECAUSE "NOT RESEARCH CONTENT" IS WHAT IT IS NOT. ⛔ "AMONG"
        # AND "WHEN A LOOKUP FAILS", because the list is neither exhaustive nor
        # unconditional: the account id reaches the file only through a FAILED
        # lookup's document path.
        "Among what is in it: a masked form of your email address, the ids of the "
        "computers and runs this agent has touched, file paths on this machine, "
        "and — when a lookup fails — your account id.",
    ]


def _agent_log_machine_hint(args) -> "tuple[bool, str]":
    """(may we offer --machine, what to call that computer) — BEST EFFORT ONLY.

    ⛔⛔ A FAILURE HERE COSTS THE HINT AND NOTHING ELSE, and that is the whole
    distinction this branch turns on. It exists so somebody with no research
    computer can send the agent's log, and `/logs/runs` is precisely the call that
    refuses those people — so its answer is used when it arrives and ignored when
    it does not. It may never decide whether the send happens.

    ⛔ AND THE OFFER STAYS OWNER-ONLY. `--machine` is refused for anybody else, so
    offering it to a sharer walks them into a refusal an earlier wave closed on
    this exact branch.

    ⛔ NO HINT AT ALL WHEN A COMPUTER WAS NAMED. Resolving `--device` costs another
    round trip, and naming the SELECTED machine in a sentence about the one they
    asked for would be a wrong statement rather than a missing one.
    """
    if getattr(args, "device", "") or "":
        return False, ""
    res = _bridge_get("/logs/runs", timeout=30.0)
    if res is None or res[0] != 200 or not res[1].get("owned"):
        return False, ""
    body = res[1]
    return True, str(body.get("deviceName") or body.get("deviceId") or "that computer")


def _agent_log_only_request(args) -> bool:
    """True when the ONLY thing being asked for is this host's own agent log.

    ⛔⛔ IT DECIDES WHETHER A RESEARCH COMPUTER IS NEEDED AT ALL, which is why it
    is read before `/logs/runs`. That route resolves a selected machine and
    refuses without one — so asking it first makes the single request that needs
    no machine impossible for precisely the people who have none.

    ⛔⛔ `--list` DISQUALIFIES IT TOO, AND ITS ABSENCE WAS A LIVE REGRESSION.
    `--list` means "show me what it is holding and send nothing" — the one flag on
    this command that promises no side effect at all. The early return sits above
    the `if args.list: return 0` short-circuit, so `send-logs --list --runs 0 -y`
    printed the standalone plan and UPLOADED. Found by cross-verification, which
    ran it.

    ⛔ BARE `--agent-log` IS NOT THIS: it means "everything that computer holds,
    and the agent's log as well". Only an explicit "and nothing else" — `--none`,
    or a `--runs` spec naming just the 0 — makes the log the whole request. And
    `--machine` disqualifies it outright, because that IS a computer's material.

    ⭐ THE TWIN OF THE CHAT CLIENT'S FUNCTION OF THE SAME NAME, and a guard drives
    both over the same specs. `sr.py` cannot import this module — it is stdlib-only
    by contract — so the duplication is structural, not laziness.
    """
    if bool(getattr(args, "machine", False)):
        return False
    # ⛔ SEE THE NOTE ABOVE — `--list` sends nothing, ever.
    if bool(getattr(args, "list", False)):
        return False
    spec = [t.strip() for t in
            str(getattr(args, "runs", "") or "").replace(" ", ",").split(",")
            if t.strip()]
    if not (bool(getattr(args, "agent_log", False)) or _AGENT_LOG_TOKEN in spec):
        return False
    if [t for t in spec if t != _AGENT_LOG_TOKEN]:
        return False
    return bool(getattr(args, "none", False)) or bool(spec)


def _send_agent_log_alone(args, offer_machine: bool = False, name: str = "") -> int:
    """Send this host's agent log with NO bundle behind it, under its own code.

    ⛔⛔ THIS IS WHAT THE REFUSAL USED TO BE. Until wave 8 the answer here was "the
    agent's own log can only go up beside a bundle from that computer" — true
    about the transport and useless to the person reading it, because the two
    commonest reasons to be sending an agent log are having no research computer
    and having one you cannot reach, and neither can produce a bundle. The app
    mints a support code for it now, so this is a send like any other.

    ⛔ STILL TWO STEPS, AND THE PLAN IS STILL WHAT MAKES CONSENT TRUE. Nothing
    leaves before the prompt below is answered.
    """
    print()
    print("This will send the log from the agent on THIS host — the program "
          "running this command.")
    print("No research computer is involved, and nothing from one is included.")
    print("It is a connection and sign-in record, not research content.")
    for line in _agent_log_fact_lines():
        print(line)
    print("It is deleted automatically 30 days after it arrives.")
    print("You will get a support code of its own to quote.")
    if offer_machine:
        # ⛔ ONLY TO AN OWNER. `--machine` is refused for anybody else, so offering
        # it to a sharer walks them into a refusal — the circle an earlier wave
        # closed on this very branch.
        print(f"If the trouble is reaching {name} at all, add --machine and that "
              "computer's own logs go as well.")
    if not _decide(None, bool(getattr(args, "yes", False)),
                   "Send the agent's own log?", default=False):
        print("Nothing was sent.")
        return 1
    with b.spinner("Sending the agent's log"):
        res = _bridge_post("/logs/agent-log", {"standalone": True}, timeout=90.0)
    if res is None or res[0] != 200:
        print(f"{_NO} The agent's own log did not go: {_err(res)}")
        return 1
    payload = res[1]
    if not payload.get("sent"):
        # ⭐ Stated as a fact and not dressed up as a problem — and there is no
        # code, because nothing was stored.
        print(f"{_OK} The agent's log on this host was empty — there was nothing "
              "to send.")
        return 0
    print(f"{_OK} Sent. Support code: {payload.get('code', '')}")
    print(f"    {_size_words(int(payload.get('bytes') or 0))}. Quote that code "
          "when you report the problem.")
    return 0


def _send_agent_log(code: str) -> None:
    """Hand up this host's own agent log, after the machine's bundle has landed.

    ⛔ NEVER CHANGES THE EXIT CODE, and never retries. The machine's bundle is
    already sent by the time this runs and the support code the person was given
    already works, so a failure here is one more sentence rather than a failed
    command. The person is told plainly that this one piece did not go.
    """
    res = _bridge_post("/logs/agent-log", {"code": code}, timeout=90.0)
    if res is None or res[0] != 200:
        print(f"{_NO} The agent's own log did not go: {_err(res)}")
        print(f"    The rest of the bundle is unaffected — support code {code}.")
        return
    payload = res[1]
    if not payload.get("sent"):
        # An empty log is the ordinary case on a healthy machine, so it is stated
        # as a fact and not dressed up as a problem.
        print(f"{_OK} The agent's log on this host was empty — nothing to add.")
        return
    print(f"{_OK} The agent's log on this host went too "
          f"({_size_words(int(payload.get('bytes') or 0))}).")


def _local_superresearch() -> "str | None":
    """Path to the Super Research backend CLI on THIS machine, if installed (the
    agent + backend are co-located in the standard setup). None if absent."""
    import shutil as _sh
    return _sh.which("superresearch")


def cmd_version(_args: argparse.Namespace) -> int:
    """Show the agent version (+ a pip-style "newer on PyPI" nudge for the AGENT)
    alongside the Super Research backend version. The agent no longer prompts to
    update the backend — that's the app's job (the user runs `superresearch
    update` on the Research computer) — so the backend line is display-only."""
    from . import selfupdate
    b.header("versio", "versions", tagline_color=branding._BOLD + branding._ACCENT)
    print(f"\n  {b.c(branding._BOLD, 'Skill')} (superresearch-agent)   {b.c(branding._BOLD, 'v' + __version__)}")
    a_new = selfupdate.agent_update_available()
    if a_new:
        # --no-cache is required: `pipx run` reuses its cached run-venv and would
        # otherwise re-run the STALE build (the same trap the self-update path
        # fixes). Matches connect.py:run_agent_in_wsl.
        print(f"     {b.c(branding._ACCENT, '⬆ v' + a_new + ' available')} — update with  "
              f"{b.c(branding._BOLD, 'pipx run --no-cache superresearch-agent connect')}")
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
    else:
        print(f"  {b.c(branding._BOLD, 'Super Research')} (backend)   {b.c(branding._DIM, 'not installed on this machine')}")
    print()
    return 0


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
    dc.add_argument("--yes", "-y", action="store_true",
                    help="non-interactive: assume yes AND stop the background bridge "
                         "(full teardown) without asking — for chat-driven disconnect")
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
    dvadd = dvsub.add_parser("add", parents=[common], help="pair a new device by its on-screen access code")
    # ⛔ THE POSITIONAL'S NAME IS THE PARSED ATTRIBUTE — only the help text moves.
    dvadd.add_argument("code", help="the access code shown on the new device's screen")
    dvadd.set_defaults(func=cmd_device)
    dvrm = dvsub.add_parser("remove", parents=[common], help="unlink a device from your account")
    dvrm.add_argument("deviceId", help="deviceId to remove (from `agent device`)")
    dvrm.set_defaults(func=cmd_device)
    dvsub.add_parser("public", parents=[common],
                     help="list the computers other people offer publicly"
                     ).set_defaults(func=cmd_device)
    dvask = dvsub.add_parser("ask", parents=[common],
                             help="ask the owner of a public computer for access")
    dvask.add_argument("deviceId", help="deviceId to ask for (from `agent device public`)")
    dvask.set_defaults(func=cmd_device)
    dvsub.add_parser("requests", parents=[common],
                     help="show who is asking for your computers, and what you "
                          "are waiting on"
                     ).set_defaults(func=cmd_device)
    # ⛔⛔ TWO POSITIONALS AND BOTH ARE IDS. A person is named by their id, not
    # their name: the queue's label is a snapshot taken the day they asked and
    # falls back to a word shared by everybody the app could not look up, so it
    # identifies nobody. `agent device requests` prints the whole command.
    dvap = dvsub.add_parser("approve", parents=[common],
                            help="let somebody use one of your computers")
    dvap.add_argument("deviceId", help="your computer's id (from `agent device`)")
    dvap.add_argument("requesterUid",
                      help="the asker's id (from `agent device requests`)")
    dvap.set_defaults(func=cmd_device)
    dvdn = dvsub.add_parser("deny", parents=[common],
                            help="refuse somebody asking for one of your computers")
    dvdn.add_argument("deviceId", help="your computer's id (from `agent device`)")
    dvdn.add_argument("requesterUid",
                      help="the asker's id (from `agent device requests`)")
    dvdn.set_defaults(func=cmd_device)
    # ⛔ NOT `device public`. That name is already the BROWSE list — the machines
    # other people offer — and one word meaning both "show me theirs" and "give
    # them mine" is a mistake somebody makes once and cannot undo. The machine's
    # own terminal calls this setting visibility for the same reason.
    dvvis = dvsub.add_parser("visibility", parents=[common],
                             help="set who can find one of your computers")
    dvvis.add_argument("deviceId", help="your computer's id (from `agent device`)")
    dvvis.add_argument("value", choices=("public", "private"),
                       help="public = other people can find it and ask")
    dvvis.set_defaults(func=cmd_device)

    sl = sub.add_parser("send-logs", parents=[common],
                        help="ask a research computer to package its logs for support "
                             "(shows what would be sent, then asks)")
    sl.add_argument("--device", help="deviceId to ask (else your selected/sole device)")
    sl.add_argument("--runs", help="which runs, by the numbers shown or by name, "
                                   "comma-separated; 0 is the agent's own log on "
                                   "this host and all is every run listed "
                                   "(default: every run listed)")
    sl.add_argument("--none", action="store_true",
                    help="send no runs — for pairing problems, with --machine")
    sl.add_argument("--machine", action="store_true",
                    help="also send that computer's own logs (its owner only)")
    # ⛔ A FLAG AND NOT A PROMPT, matching --machine. This surface prints the whole
    # plan and then asks ONE yes/no over all of it — `_decide` takes exactly "y" or
    # "yes" — so there is no per-item reader to hang a question off, and inventing
    # one here would make this the only screen in the product that asks twice.
    sl.add_argument("--agent-log", dest="agent_log", action="store_true",
                    help="also send the log from the agent on THIS host; "
                         "--runs 0 names the same log, but --runs also REPLACES "
                         "the run selection")
    sl.add_argument("--list", action="store_true",
                    help="just show what it's holding, send nothing")
    sl.add_argument("--status", metavar="CODE",
                    help="report on a support code instead of sending")
    sl.add_argument("-y", "--yes", action="store_true",
                    help="don't ask before sending (the plan is still printed)")
    sl.add_argument("--no-wait", dest="no_wait", action="store_true",
                    help="don't wait for the computer to finish packaging")
    sl.add_argument("--wait", type=int, default=180, metavar="SECONDS",
                    help="how long to wait for it to finish (default 180)")
    sl.set_defaults(func=cmd_send_logs)

    sub.add_parser("logout", parents=[common], help="clear the account session").set_defaults(func=cmd_logout)
    sub.add_parser("doctor", parents=[common], help="run health + connectivity diagnostics").set_defaults(func=cmd_doctor)
    vb = sub.add_parser("verbose", parents=[common],
                        help="turn detailed bridge logging on or off")
    vb.add_argument("state", nargs="?", default="",
                    help="on | off")
    vb.set_defaults(func=cmd_verbose)

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
    sub.add_parser("restart", parents=[common],
                   help="restart the background bridge (pick up an upgraded package; keeps the login pin)"
                   ).set_defaults(func=cmd_restart)

    sub.add_parser("version", parents=[common],
                   help="show the agent + Super Research backend versions"
                   ).set_defaults(func=cmd_version)
    # No `update` subcommand: the agent doesn't update the backend anymore. To
    # update the backend, run `superresearch --update` on the Research computer (the
    # app notifies when one's available); update the agent with `connect`.

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
