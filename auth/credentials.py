"""RefreshTokenCredentials — per-user Firebase auth for google-cloud-firestore.

Implements `google.auth.credentials.Credentials` so it slots into the same
`firestore.Client(credentials=...)` constructor that the rest of the BE
already calls. ID tokens are 1-hour Firebase tokens minted by exchanging
the long-lived refresh token at `securetoken.googleapis.com`. Every refresh
rotates the refresh token (Firebase issues a new one) and the new value is
persisted to the OS keystore via the three-slot rotation in `keystore.py`.

Lifecycle:
1. Caller constructs RefreshTokenCredentials(install_uuid, web_api_key).
2. Caller passes to `firestore.Client(credentials=creds)`.
3. google-auth calls `creds.refresh(request)` whenever `creds.expired` is True.
4. We POST grant_type=refresh_token to securetoken, parse id_token + new
   refresh_token + expires_in, write the new refresh_token to keystore
   pending → promote to current → clear pending, update in-memory token + expiry.
5. On `INVALID_REFRESH_TOKEN` from securetoken we raise RevokedError; the
   caller is expected to clear all keystore slots and prompt re-pair.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import google.auth.credentials
import requests

from . import keystore

log = logging.getLogger(__name__)

_SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"

# Refresh proactively a few minutes before expiry to absorb clock skew + the
# round-trip latency to securetoken.googleapis.com. Per PairingRecipe §3.3.
_REFRESH_MARGIN_SECONDS = 300


class RevokedError(RuntimeError):
    """Raised when the refresh token is no longer valid (revoked / expired).

    Signals to the caller that the user must re-pair. Catch this at the
    BE auth boundary, clear the keystore, prompt re-pair, exit.
    """


class RefreshTokenCredentials(google.auth.credentials.Credentials):
    """Credentials backed by a Firebase refresh token in the OS keystore.

    Construct with the install_uuid that owns the keystore slots, plus the
    Firebase project's public Web API key (intentionally non-secret — it's
    just a project identifier for the securetoken endpoint).

    `seed_refresh_token` is the one-time bootstrap: when `cmd_pair_v2()`
    completes the initial custom-token exchange, it writes the refresh
    token returned by `accounts:signInWithCustomToken` into the keystore
    pending slot via `bootstrap()` and then calls `keystore.promote_pending`.
    From that point on the credentials object reads from `current`.
    """

    def __init__(self, install_uuid: str, web_api_key: str) -> None:
        super().__init__()
        self._install_uuid = install_uuid
        self._web_api_key = web_api_key
        self._uid: str | None = None  # set after first successful refresh

    @property
    def uid(self) -> str | None:
        return self._uid

    @classmethod
    def bootstrap(
        cls,
        install_uuid: str,
        web_api_key: str,
        *,
        refresh_token: str,
        id_token: str,
        uid: str,
        expires_in: int,
    ) -> "RefreshTokenCredentials":
        """Construct from a fresh signInWithCustomToken response + persist."""
        keystore.set("pending", install_uuid, refresh_token)
        keystore.promote_pending(install_uuid)
        creds = cls(install_uuid, web_api_key)
        creds.token = id_token  # google.auth attribute
        creds.expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            seconds=max(0, expires_in - _REFRESH_MARGIN_SECONDS)
        )
        creds._uid = uid
        return creds

    # -- google.auth.credentials.Credentials interface ------------------------

    def refresh(self, request: Any) -> None:  # noqa: ARG002 - signature dictated by base class
        refresh_token = keystore.get("current", self._install_uuid)
        if not refresh_token:
            raise RevokedError("no refresh token in keystore")
        try:
            resp = requests.post(
                _SECURE_TOKEN_URL,
                params={"key": self._web_api_key},
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                timeout=10,
            )
        except requests.RequestException as e:
            log.warning("refresh: network error %s — leaving keystore intact", e)
            raise

        if resp.status_code == 400:
            body = resp.json() if resp.content else {}
            err = body.get("error", "")
            if "INVALID_REFRESH_TOKEN" in err or "TOKEN_EXPIRED" in err:
                raise RevokedError(f"refresh token rejected: {err}")
        if not resp.ok:
            raise RuntimeError(f"refresh HTTP {resp.status_code}: {resp.text}")

        body = resp.json()
        new_refresh = body["refresh_token"]
        new_id = body["id_token"]
        expires_in = int(body["expires_in"])
        self._uid = body.get("user_id") or self._uid

        # Persist BEFORE updating in-memory state so a kill mid-write leaves
        # the keystore consistent.
        keystore.set("pending", self._install_uuid, new_refresh)
        keystore.promote_pending(self._install_uuid)

        self.token = new_id
        self.expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            seconds=max(0, expires_in - _REFRESH_MARGIN_SECONDS)
        )
