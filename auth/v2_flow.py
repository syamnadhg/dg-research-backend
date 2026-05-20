"""High-level BE-side helpers for the Track D pair flow (PR-D3).

This module owns:
- `generate_poll_secret` / `compute_poll_secret_hash` — the 256-bit secret
  that BE stores locally + the hash it sends to the FE Cloud Function so
  sharers can't read the customToken from the device doc.
- `initiate_pair_remote` — POST to /api/devices/initiate-pair (unauth).
- `poll_pending_token` — anonymous Firestore REST GET on
  `devices/{deviceId}/pending/{pollSecretHash}` to pick up the
  customToken once the owner has claimed the code from the FE.
- `do_pair_v2` — orchestrator that ties the above together: generate
  secret, call initiate-pair, render the code/QR, poll for customToken,
  exchange, bootstrap RefreshTokenCredentials.
- `init_firestore_user_scoped` — factory that returns a
  `google.cloud.firestore.Client` backed by `RefreshTokenCredentials`.
  Drop-in replacement for `firebase_admin.firestore.client()` in the
  Track-D-default code paths.

These functions are deliberately independent of `research.py` globals
so they're unit-testable + don't import the kitchen sink.

Public config — intentionally NOT secret. The Firebase Web API key is a
project identifier embedded in client builds; the project ID and the
production FE URL are public on superresearch.io. Override via env for
local development or staging.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets as _secrets
from typing import Any

import requests

from . import credentials, keystore, pairing

log = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "super-research-492814")
WEB_API_KEY = os.environ.get(
    "FIREBASE_WEB_API_KEY", "AIzaSyDTjXwU_uOwGrsuf7nuJTfQAZg4dTjSAMk"
)
FE_BASE_URL = os.environ.get("RESEARCH_FE_BASE_URL", "https://superresearch.io").rstrip(
    "/"
)

POLL_INTERVAL_SECONDS = 2.0
DEFAULT_POLL_TIMEOUT_SECONDS = 15 * 60  # Matches FE pendingCustomToken TTL


# ─── pollSecret ────────────────────────────────────────────────────────


def generate_poll_secret() -> str:
    """256 bits of randomness as a 64-char lowercase hex string.

    Stored in `research_config.json` (NOT keystore — survives Reset and
    re-pair, which wipe the refresh token). Sent ONLY as its SHA-256
    hash to the FE; the FE writes the customToken to a subdoc keyed by
    that hash. Sharers can read the device doc but never see the hash,
    so they can't construct the path to the JWT.
    """
    return _secrets.token_hex(32)


def compute_poll_secret_hash(poll_secret: str) -> str:
    return hashlib.sha256(poll_secret.encode("ascii")).hexdigest()


# ─── FE Cloud Function calls ───────────────────────────────────────────


class InitiatePairError(RuntimeError):
    """Raised when /api/devices/initiate-pair returns a non-2xx response."""


def initiate_pair_remote(
    *,
    poll_secret_hash: str,
    machine_name: str | None = None,
    hostname: str | None = None,
    os_string: str | None = None,
    timeout: float = 15.0,
) -> dict[str, str]:
    """POST to the FE Cloud Function. Returns `{deviceId, pairCode}`.

    Network error or non-2xx → InitiatePairError so the caller can
    surface a clean message instead of a stack trace.
    """
    url = f"{FE_BASE_URL}/api/devices/initiate-pair"
    body = {
        "pollSecretHash": poll_secret_hash,
        "machineName": machine_name,
        "hostname": hostname,
        "os": os_string,
    }
    try:
        resp = requests.post(url, json=body, timeout=timeout)
    except requests.RequestException as e:
        raise InitiatePairError(f"network error contacting {url}: {e}") from e
    if not resp.ok:
        try:
            body = resp.json()
        except Exception:
            body = {}
        err = body.get("error") if isinstance(body, dict) else None
        raise InitiatePairError(
            f"initiate-pair HTTP {resp.status_code}"
            + (f" — {err}" if err else f": {resp.text[:200]}")
        )
    data = resp.json()
    if "deviceId" not in data or "pairCode" not in data:
        raise InitiatePairError(f"initiate-pair response missing fields: {data}")
    return {"deviceId": data["deviceId"], "pairCode": data["pairCode"]}


# ─── Anonymous Firestore polling for the pending-token subdoc ──────────


class PollTimeout(TimeoutError):
    """Raised when the pending-customToken doc never materializes."""


def _firestore_rest_url(device_id: str, secret_hash: str) -> str:
    return (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}"
        f"/databases/(default)/documents/devices/{device_id}/pending/{secret_hash}"
    )


def _extract_custom_token(doc_payload: dict[str, Any]) -> str | None:
    """Unwrap Firestore REST's `{fields: {customToken: {stringValue: ...}}}`."""
    fields = doc_payload.get("fields", {}) if isinstance(doc_payload, dict) else {}
    ct_field = fields.get("customToken") if isinstance(fields, dict) else None
    if isinstance(ct_field, dict):
        val = ct_field.get("stringValue")
        if isinstance(val, str) and val:
            return val
    return None


async def poll_pending_token(
    *,
    device_id: str,
    poll_secret_hash: str,
    timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
    interval_seconds: float = POLL_INTERVAL_SECONDS,
    on_tick: "callable | None" = None,
) -> str:
    """Wait for the FE claim flow to deposit a customToken at the pending
    subdoc. Returns the JWT string. Raises `PollTimeout` if the window
    closes without a hit.

    Polls the Firestore REST API anonymously (rule:
    `allow get: if true` on `devices/{deviceId}/pending/{secretHash}`).
    No Firebase auth required — the BE doesn't have any yet at this
    point in the pair flow.

    `on_tick(elapsed_seconds)` is invoked every poll cycle so callers
    can render a spinner / countdown without coupling here.
    """
    url = _firestore_rest_url(device_id, poll_secret_hash)
    loop = asyncio.get_running_loop()
    started = loop.time()
    while True:
        elapsed = loop.time() - started
        if elapsed >= timeout_seconds:
            raise PollTimeout(
                f"pending token not delivered within {timeout_seconds:.0f}s"
            )
        if on_tick is not None:
            try:
                on_tick(elapsed)
            except Exception:
                # Cosmetic callback — never let it abort the poll.
                pass
        try:
            resp = await asyncio.to_thread(requests.get, url, timeout=8.0)
        except requests.RequestException as e:
            log.debug("poll_pending_token: transient HTTP error %s", e)
            await asyncio.sleep(interval_seconds)
            continue
        if resp.status_code == 200:
            try:
                ct = _extract_custom_token(resp.json())
            except ValueError:
                ct = None
            if ct:
                return ct
        # 404 = subdoc doesn't exist yet (FE hasn't claimed). 403 = rule
        # mismatch (deploy lag). 5xx = transient. Keep polling; the
        # outer timeout is the safety net.
        await asyncio.sleep(interval_seconds)


# ─── High-level orchestrator ────────────────────────────────────────────


async def do_pair_v2(
    *,
    poll_secret_hash: str,
    machine_name: str,
    hostname: str,
    os_string: str,
    on_code: "callable",
    on_waiting: "callable | None" = None,
    poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the BE side of Stage 1 (Track D opt-in).

    Caller (run_pair) is responsible for the surrounding CLI UX —
    printing the code, rendering the QR, drawing a spinner. This
    function returns the materialized credentials + deviceId so the
    caller can persist them and continue with Stages 2-5.

    `on_code(device_id, pair_code)` fires once initiate-pair returns,
    BEFORE the polling loop starts. `on_waiting(elapsed_seconds)` fires
    on every poll tick so the caller can update a countdown.

    Returns:
        {
          "device_id": str,
          "pair_code": str,
          "uid": str,                 # synthetic device user uid
          "credentials": RefreshTokenCredentials,  # ready for Firestore
        }
    """
    init_resp = await asyncio.to_thread(
        initiate_pair_remote,
        poll_secret_hash=poll_secret_hash,
        machine_name=machine_name,
        hostname=hostname,
        os_string=os_string,
    )
    device_id = init_resp["deviceId"]
    pair_code = init_resp["pairCode"]

    on_code(device_id, pair_code)

    custom_token = await poll_pending_token(
        device_id=device_id,
        poll_secret_hash=poll_secret_hash,
        timeout_seconds=poll_timeout_seconds,
        on_tick=on_waiting,
    )

    exchange = await asyncio.to_thread(
        pairing.exchange_custom_token, custom_token, WEB_API_KEY
    )
    refresh_token = exchange["refreshToken"]
    id_token = exchange["idToken"]
    uid = exchange["localId"]
    expires_in = int(exchange.get("expiresIn") or "3600")

    creds = credentials.RefreshTokenCredentials.bootstrap(
        install_uuid=keystore.install_uuid(),
        web_api_key=WEB_API_KEY,
        refresh_token=refresh_token,
        id_token=id_token,
        uid=uid,
        expires_in=expires_in,
    )

    return {
        "device_id": device_id,
        "pair_code": pair_code,
        "uid": uid,
        "credentials": creds,
    }


async def do_redeem_reset(
    *,
    device_id: str,
    poll_secret_hash: str,
    on_waiting: "callable | None" = None,
    poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """BE-side of post-Reset re-pair (PR-D3 supervisor path).

    When the BE's refresh-token gets revoked (owner clicked Reset),
    `credentials.RefreshTokenCredentials.refresh` raises RevokedError.
    The caller clears the keystore and invokes this function: we keep
    polling the SAME pending subdoc the initial pair used (keyed by the
    persistent pollSecretHash in research_config.json). The owner
    enters the new code emailed by the Reset flow into Account → Add
    Device; the claim Cloud Function writes a fresh customToken to the
    pending subdoc; we pick it up and re-bootstrap the keystore.

    Different from do_pair_v2 in that we don't call /initiate-pair —
    the device doc already exists, only the customToken under the
    existing path needs to be polled.
    """
    custom_token = await poll_pending_token(
        device_id=device_id,
        poll_secret_hash=poll_secret_hash,
        timeout_seconds=poll_timeout_seconds,
        on_tick=on_waiting,
    )
    exchange = await asyncio.to_thread(
        pairing.exchange_custom_token, custom_token, WEB_API_KEY
    )
    creds = credentials.RefreshTokenCredentials.bootstrap(
        install_uuid=keystore.install_uuid(),
        web_api_key=WEB_API_KEY,
        refresh_token=exchange["refreshToken"],
        id_token=exchange["idToken"],
        uid=exchange["localId"],
        expires_in=int(exchange.get("expiresIn") or "3600"),
    )
    return {
        "device_id": device_id,
        "uid": exchange["localId"],
        "credentials": creds,
    }


# ─── Firestore client factory ───────────────────────────────────────────


def init_firestore_user_scoped(install_uuid: str | None = None):
    """Return a `google.cloud.firestore.Client` backed by the keystore's
    refresh token. Drop-in for `firebase_admin.firestore.client()` in
    Track-D-default code paths.

    Returns None when the keystore has no refresh token (the user
    hasn't paired yet, or just got Reset). Callers should fall back to
    the legacy Admin SDK path or prompt for re-pair.
    """
    from google.cloud import firestore as _gcf

    iuid = install_uuid or keystore.install_uuid()
    if keystore.try_recover(iuid) is None:
        return None
    creds = credentials.RefreshTokenCredentials(iuid, WEB_API_KEY)
    try:
        client = _gcf.Client(project=PROJECT_ID, credentials=creds)
        # Force a refresh so we surface RevokedError NOW instead of on the
        # first real query. Cheap — the caller is about to do work anyway.
        creds.refresh(None)  # type: ignore[arg-type]
        return client
    except credentials.RevokedError:
        log.warning(
            "refresh token rejected — keystore wiped, caller should prompt re-pair"
        )
        keystore.clear_all(iuid)
        return None
