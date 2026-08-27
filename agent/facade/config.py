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
AUTH_DOMAIN: str = os.environ.get(
    "SUPER_AGENT_AUTH_DOMAIN", "super-research-492814.firebaseapp.com"
)
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
# ⛔⛔ THE ONLY WAY TO GET A VERBOSE PRODUCTION BRIDGE, and until this there was
# none at all. `agent serve` takes `-v`, but the always-on bridge is started by a
# GENERATED launcher: `autostart.py` writes the literal
# `raise SystemExit(main(['serve']))`, with no flag, and refreshes that file — so a
# hand-edit does not survive. There was no environment variable for verbosity
# anywhere in this package either, though this module uses `SUPER_AGENT_*` in ten
# other places. So the support loop every other surface assumes — "turn verbose on,
# reproduce it, send us the log" — was not awkward, it was IMPOSSIBLE on a
# correctly-installed agent. `agent doctor` now prints how to set this.
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
