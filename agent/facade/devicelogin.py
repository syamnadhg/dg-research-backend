"""Remote-login device-flow CLIENT (recipe §11a).

`/login` from any channel (WhatsApp/phone) without exposing the bridge or its
localhost. The bridge brokers an OAuth-device-style flow through the existing
Super Research web app and makes only OUTBOUND calls:

  1. start  → POST {FE}/api/agent/login/start  → {code, pollToken, verifyUrl, expiresIn}
              the bridge shows the user: "open {verifyUrl}, enter {code}".
  2. (user approves on their phone — signs in to SR, taps Approve; the FE mints
     createCustomToken for THEIR OWN uid and parks it on the pending record.)
  3. poll   → GET {FE}/api/agent/login/poll?pollToken=…
              → {status: pending|approved|expired, customToken?}
              on `approved` the bridge redeems the one-time custom token via
              AccountSession.from_custom_token and stores the session.

This module is ONLY the HTTP client half. The FE routes themselves are built
under paired review (Admin-SDK custom-token mint = security-sensitive) and are
NOT part of the /goal loop. Tests drive this client against a mock FE server.

The custom token never leaves the host: it is read from the FE and immediately
redeemed locally. We never log it.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from . import config

# ⛔ DELIBERATELY UNUSED, AND THAT IS WORTH SAYING. Every failure in this module
# raises `DeviceLoginError` carrying its own detail — the HTTP status, the body
# prefix, "returned a non-JSON response", "approved but sent no custom token" — and
# the CALLERS log that text. Logging here as well would double every line.
#
# ⚠ What made that arrangement look broken until 2026-08-26 was the consumer, not
# this file: the poll path logged the exception at DEBUG and called it a "transient
# transport blip", so at the default level a persistent broker 500 left nothing
# behind and a verbose run mislabelled it. That is fixed where it was wrong
# (`bridge.py:_advance_remote_flow`). Do not add duplicate logging here.
log = logging.getLogger(__name__)

# Flow status values the FE poll endpoint reports.
PENDING = "pending"
APPROVED = "approved"
EXPIRED = "expired"

_START_TIMEOUT = 15
_POLL_TIMEOUT = 15


class DeviceLoginError(RuntimeError):
    """The remote-login broker (FE) returned an error or unusable response."""


def _login_url(path: str, fe_base: str | None = None) -> str:
    base = (fe_base or config.FE_BASE).rstrip("/")
    return f"{base}/api/agent/login/{path}"


def start(*, fe_base: str | None = None, label: str = "", runtime: str = "") -> dict[str, Any]:
    """Begin a remote-login flow. Returns {code, pollToken, verifyUrl, expiresIn}.

    `label`/`runtime` are advisory hints the FE may surface on the approval page
    (e.g. "Approve Super Agent on Hermes?"); they carry no authority.
    """
    body = {k: v for k, v in (("label", label), ("runtime", runtime)) if v}
    try:
        resp = requests.post(_login_url("start", fe_base), json=body, timeout=_START_TIMEOUT)
    except requests.RequestException as e:
        raise DeviceLoginError(f"could not reach the sign-in broker: {e}") from e
    if not resp.ok:
        raise DeviceLoginError(f"sign-in broker start failed: HTTP {resp.status_code} {resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError as e:
        raise DeviceLoginError("sign-in broker returned a non-JSON response") from e
    code = data.get("code")
    poll_token = data.get("pollToken")
    verify_url = data.get("verifyUrl")
    if not code or not poll_token or not verify_url:
        raise DeviceLoginError("sign-in broker start response missing code/pollToken/verifyUrl")
    return {
        "code": code,
        "pollToken": poll_token,
        "verifyUrl": verify_url,
        "expiresIn": int(data.get("expiresIn", 600) or 600),
    }


def poll_once(poll_token: str, *, fe_base: str | None = None) -> dict[str, Any]:
    """One poll of the broker. Returns {status, customToken?}.

    Raises DeviceLoginError on transport / HTTP / malformed-response errors so
    the caller can decide whether to keep polling or surface a failure.
    """
    try:
        resp = requests.get(
            _login_url("poll", fe_base), params={"pollToken": poll_token}, timeout=_POLL_TIMEOUT
        )
    except requests.RequestException as e:
        # Never interpolate `e`: a requests transport error embeds the prepared URL,
        # which carries ?pollToken=… — so only the exception TYPE is safe to surface.
        # `from None` (not `from e`) so a traceback can't leak the tokened URL via the
        # chained __cause__/__context__ either.
        raise DeviceLoginError(f"poll could not reach the sign-in broker: {type(e).__name__}") from None
    # The FE returns 410 Gone for an expired/unknown pollToken — treat as expired.
    if resp.status_code == 410:
        return {"status": EXPIRED}
    if not resp.ok:
        raise DeviceLoginError(f"sign-in broker poll failed: HTTP {resp.status_code} {resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError as e:
        raise DeviceLoginError("sign-in broker poll returned a non-JSON response") from e
    status = data.get("status", PENDING)
    out: dict[str, Any] = {"status": status}
    if status == APPROVED:
        token = data.get("customToken")
        if not token:
            raise DeviceLoginError("broker reported approved but sent no custom token")
        out["customToken"] = token
    return out
