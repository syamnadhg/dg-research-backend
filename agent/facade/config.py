"""Static configuration for the Super Agent bridge.

Everything here is either a *public* Firebase project identifier (the Web API
key is intentionally non-secret — it just routes REST calls to the right
project) or a local-only setting (bridge host/port, secret-store namespace).
No secrets live in this file.

All values are overridable via environment variables so the bridge can point
at a staging project without code edits.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Firebase project (public client config; mirrors research-app/web/.env.local) ──
PROJECT_ID: str = os.environ.get("SUPER_AGENT_PROJECT_ID", "super-research-492814")

# Public Web API key. NOT a secret — it is the same value shipped in the web
# app's client bundle and in research-automate/auth/v2_flow.py. It only
# identifies the project to securetoken.googleapis.com / identitytoolkit.
#
# What actually protects the data this key can address is FIRESTORE RULES, and
# nothing else — App Check is NOT enforced on any of these paths, so do not
# reason about this key as if it were. The relevant guarantees, in the FE repo's
# `firestore.rules` (super-research-frontend):
#
#   devices/{deviceId}          read requires auth AND owner/sharer/synthetic-uid
#                               membership; create + delete are admin-SDK only.
#   .../pending/{secretHash}    `allow get: if true` but `allow list: if false`,
#                               and the path segment is sha256(pollSecret) whose
#                               source lives admin-only under _internal/ — so the
#                               custom-token inbox can be fetched only by someone
#                               who already knows the secret, and never enumerated.
#                               All writes are admin-SDK only.
#   _internal/{document=**}     read+write denied to every client unconditionally.
#
# i.e. holding this key gets an unauthenticated caller no reads, no writes, and
# no enumeration. If App Check is ever actually turned on, say so here; until
# then this comment is the whole story.
WEB_API_KEY: str = os.environ.get(
    "SUPER_AGENT_WEB_API_KEY", "AIzaSyDTjXwU_uOwGrsuf7nuJTfQAZg4dTjSAMk"
)
# The host the local sign-in page's Google window opens on
# (https://<this>/__/auth/handler), and so the name Google's account picker shows.
# It matches the web app's own value (apphosting.yaml), so the picker names
# superresearch.io rather than the project's firebaseapp.com host. That works
# only because the web app proxies the whole /__/auth/ prefix to the Firebase
# helper (next.config.ts) and the Google OAuth web client lists
# https://superresearch.io/__/auth/handler as a redirect URI. Firebase's
# authorized-domains check reads the PAGE's origin, which stays localhost.
# ⛔ THE TRADE-OFF: the window is now served by the web app itself, so
# `agent login --local` no longer works while superresearch.io is down. That is
# accepted, not retried on a second host; `cli._local_signin_needs` says so wherever
# --local is offered. ⛔ Never remove the firebaseapp.com redirect URI while an
# agent older than this default is installed: those still sign in through it.
AUTH_DOMAIN: str = os.environ.get("SUPER_AGENT_AUTH_DOMAIN", "superresearch.io")
APP_ID: str = os.environ.get(
    "SUPER_AGENT_APP_ID", "1:441214203201:web:40d757e9d940d70fb71dc0"
)
MESSAGING_SENDER_ID: str = os.environ.get(
    "SUPER_AGENT_MESSAGING_SENDER_ID", "441214203201"
)
STORAGE_BUCKET: str = os.environ.get(
    "SUPER_AGENT_STORAGE_BUCKET", "super-research-492814.firebasestorage.app"
)

# ── Google REST endpoints ──
SECURE_TOKEN_URL: str = "https://securetoken.googleapis.com/v1/token"
# Identity Toolkit: exchange a custom token (minted by the SR web app for the
# approver's own uid in the remote-login device flow, §11a) for an id+refresh
# token pair — the REST equivalent of the Web SDK's signInWithCustomToken.
SIGN_IN_WITH_CUSTOM_TOKEN_URL: str = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"
)
FIRESTORE_BASE: str = (
    f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}"
    "/databases/(default)/documents"
)

# ── Super Research web app (the remote-login broker, §11a) ──
# The bridge makes only OUTBOUND calls to {FE_BASE}/api/agent/login/{start,poll}
# during a remote /login. Code-defaults to the public origin (mirrors the web
# app's appOrigin() default in p5-handlers.ts); overridable for staging.
FE_BASE: str = os.environ.get("SUPER_AGENT_FE_BASE", "https://superresearch.io").rstrip("/")

# ── Local bridge ──
# Loopback only — the bridge is never exposed off-host. It BINDS to 127.0.0.1
# (explicit IPv4 loopback, no DNS / no IPv6 surprises). The host CLI and skill
# call it at 127.0.0.1. The browser sign-in page, however, must be opened at
# `localhost` because Firebase Auth's default authorized-domains list contains
# `localhost` (not the bare 127.0.0.1 literal) — otherwise signInWithPopup
# raises auth/unauthorized-domain. Browsers fall back ::1 → 127.0.0.1, so the
# localhost URL reaches the 127.0.0.1-bound server fine.
# ⛔⛔ AND THIS VARIABLE IS NOT THE ANSWER, WHICH THIS COMMENT USED TO CLAIM. It
# said it was "THE ONLY WAY TO GET A VERBOSE PRODUCTION BRIDGE" and that "`agent
# doctor` now prints how to set this". Both were refuted afterwards and the prose
# was left behind: `autostart.py` writes NO environment into any of the three
# launchers, so this reaches a foreground `agent serve` and nothing else — see
# `prefs.get_verbose`, which records the measurement — and `doctor` now points at
# `superresearch-agent verbose on` precisely because naming a variable that cannot
# reach the bridge is unactionable. Keep it for a one-off foreground run; the pref
# is what the always-on bridge reads, whoever started it.
VERBOSE: bool = os.environ.get("SUPER_AGENT_VERBOSE", "").strip().lower() in (
    "1", "true", "yes", "on",
)

BRIDGE_HOST: str = os.environ.get("SUPER_AGENT_BRIDGE_HOST", "127.0.0.1")

DEFAULT_BRIDGE_PORT = 9876

# The raw value that was refused, verbatim, or "" when the port was taken as
# given. Recorded rather than printed: this module is imported at the top of
# `cli.py`, long before `logsetup.configure` has run and on EVERY subcommand, so
# a print here would be noise on nine commands and a log line would go nowhere.
# `serve` says it where the person starting a bridge is looking, and `doctor`
# says it where somebody hunting an unreachable bridge is looking.
BRIDGE_PORT_REJECTED: str = ""


def _read_bridge_port() -> int:
    """The bridge port, validated the same way all five clients validate it.

    ⛔⛔ THIS USED TO BE A BARE ``int(os.environ.get(...))`` AT MODULE SCOPE, and
    the blast radius was not the bridge. ``cli.py`` imports this module at import
    time, so a non-numeric ``SUPER_AGENT_BRIDGE_PORT`` raised ValueError before
    argparse ever ran and took down ``doctor``, ``version``, ``status`` and
    ``connect`` together — including the two commands a person would reach for to
    find out what was wrong.

    ⭐ AND THE POINT IS AGREEMENT, NOT SURVIVAL. The fleet's watcher spawns the
    bridge with ``Popen([python, "-m", "facade.cli", "serve"])`` and no ``env=``,
    so the child inherits this variable. With the clients falling back to 9876 on
    a value this module accepted or died on, the client and the bridge it just
    started could aim at two different ports — and the only symptom is "the
    bridge is unreachable", forever, with nothing anywhere saying why. Five
    copies of this rule now land on the same answer for the same input.

    ⚠ 1..65535 IS THE WHOLE RANGE, PRIVILEGED PORTS INCLUDED, and that is
    deliberate. It is the range the clients already accept and two fleet tests
    already rely on (they use port 9 as a nothing-answers port); narrowing it
    here would make this module the one copy that disagrees, which is the defect.
    A port a non-root user cannot bind is caught at bind time, by `serve`, which
    can say so from the errno instead of guessing here.
    """
    global BRIDGE_PORT_REJECTED
    raw = os.environ.get("SUPER_AGENT_BRIDGE_PORT", "").strip()
    if not raw:
        return DEFAULT_BRIDGE_PORT
    try:
        port = int(raw)
    except ValueError:
        BRIDGE_PORT_REJECTED = raw
        return DEFAULT_BRIDGE_PORT
    if not (1 <= port <= 65535):
        BRIDGE_PORT_REJECTED = raw
        return DEFAULT_BRIDGE_PORT
    return port


BRIDGE_PORT: int = _read_bridge_port()

# How often the bridge polls the FE for a remote-login approval, and how long it
# keeps polling before giving up if the FE never reports an expiry. Both kept
# small + overridable so tests can drive the flow fast.
REMOTE_POLL_INTERVAL_SECONDS: float = float(
    os.environ.get("SUPER_AGENT_REMOTE_POLL_INTERVAL", "3")
)

# How often `agent watch` (and a runtime streaming cron) re-polls a run for new
# per-phase links. Overridable so tests can drive it fast.
STREAM_POLL_INTERVAL_SECONDS: float = float(
    os.environ.get("SUPER_AGENT_STREAM_POLL_INTERVAL", "5")
)

# How often the bridge's background heartbeat thread bumps the agentSessions
# doc's lastSeenAt (which doubles as keeping the account token warm) and reads
# back the `revoked` flag to self-logout if the user revoked the agent from the
# app's "Shared with" popup. Overridable so E2E/unit tests can drive it fast.
HEARTBEAT_INTERVAL_SECONDS: float = float(
    os.environ.get("SUPER_AGENT_HEARTBEAT_INTERVAL", "60")
)


def bridge_origin() -> str:
    """Origin the host CLI / skill use to call the bridge (reliable IPv4)."""
    return f"http://127.0.0.1:{BRIDGE_PORT}"


def login_origin() -> str:
    """Origin the browser opens for Google sign-in (Firebase-authorized)."""
    return f"http://localhost:{BRIDGE_PORT}"


# ── Secret store namespace ──
# DISTINCT from the device daemon's keystore ("super-research"). This isolation
# is load-bearing: the bridge holds the *account* refresh token, the device
# daemon holds the *device* refresh token; they are different Firebase users
# with different tokens, and they must never share a slot.
STORE_SERVICE: str = "super-agent"

# Local config / fallback-secret directory (separate from ~/.super-research).
STORE_DIR_NAME: str = ".super-agent"


def store_dir() -> Path:
    """The bridge's local state directory (~/.super-agent). Single source of
    truth shared by the secret-store fallback and the operational log."""
    return Path.home() / STORE_DIR_NAME


def log_path() -> Path:
    """Operational log file (~/.super-agent/bridge.log)."""
    return store_dir() / "bridge.log"


# ── the fleet's two homes ──
# The environment variable the fleet gives its gateway its own home directory in.
HERMES_HOME_ENV: str = "HERMES_HOME"


def home_split() -> "str | None":
    """The fleet's home when it is NOT the home this agent writes its log under,
    else None.

    ⛔⛔ WHY THIS IS A GUARD AND NOT A FIX. On the fleet the two are the same
    directory today — `provision-user-helper.sh` sets HERMES_HOME=/sandbox/.hermes
    and, nine lines later and for an unrelated reason (dg-cli's token surviving a
    nightly recreate), HOME to the same literal. Nothing ties them. The comment
    beside the HOME line even records the reasoning that they are independent:
    "Hermes itself keys off HERMES_HOME, not HOME, so this is inert for the
    gateway". So the equality this agent depends on is a coincidence of two
    unrelated decisions, and the fleet's OTHER profile — the systemd unit — sets
    HERMES_HOME to /home/u-%i/.hermes and no HOME at all, where they differ by a
    whole segment. That layout carries no agent today. Nothing says it never will.

    ⛔⛔ AND WHAT BREAKS IS SILENT — THOUGH NOT IN THE WAY THIS NOTE FIRST SAID.
    An earlier version of it claimed a split would make the upload answer "the
    agent's log on this host was empty". It would not: the handler and the
    uploader BOTH call this module's `log_path()`, in the same process, so they
    move together and always agree. Cross-verification caught that, and the real
    failure is the other half of the pair. The fleet's own client starts the
    bridge with the child's stdout/stderr redirected to
    $HERMES_HOME/.super-agent/bridge.log — a path built in the OTHER repository,
    from the OTHER variable. Split the two and that redirect collects a second
    copy of everything the bridge writes to its console, in a file nothing ever
    uploads, while `--agent-log` sends the handler's file and reports success. A
    crash that only ever reaches stderr — anything that kills the process before
    a handler runs — lands solely in the file support will never see.

    ⭐ SO IT REPORTS, IT DOES NOT RECONCILE. Choosing a root here would move the
    log out from under the fleet's redirect, or out from under `store_dir()` which
    every other piece of local state also derives from — a bigger change than the
    problem, made blind, on a machine nobody is watching. Saying which two
    directories disagree is what a person needs and all this can honestly do.

    Returns the raw HERMES_HOME value (what the operator set), never the
    resolved one — the value they can go and look at is the one worth printing.
    """
    raw = (os.environ.get(HERMES_HOME_ENV) or "").strip()
    if not raw:
        return None
    try:
        # ⛔ RESOLVED ON BOTH SIDES, so a symlink, a trailing slash or a "." does
        # not read as a split. The fleet's roots are bind mounts and its HOME is
        # written by a shell; comparing the strings would cry wolf on a layout
        # that is in fact identical, and a guard that fires when nothing is wrong
        # is one people learn to scroll past.
        theirs = Path(raw).expanduser().resolve()
        ours = Path.home().resolve()
    except (OSError, RuntimeError):
        # An unreadable or cycle-linked path cannot be compared. Do not guess a
        # split — an alarm nobody can act on is worse than the silence it breaks.
        return None
    return None if theirs == ours else raw


def web_config() -> dict[str, str]:
    """The Firebase client config injected into the local sign-in page."""
    return {
        "apiKey": WEB_API_KEY,
        "authDomain": AUTH_DOMAIN,
        "projectId": PROJECT_ID,
        "appId": APP_ID,
        "messagingSenderId": MESSAGING_SENDER_ID,
        "storageBucket": STORAGE_BUCKET,
    }
