"""AccountSession — the bridge's headless Super Research account session.

Holds the account's Firebase refresh token (captured once via the `/login`
Google sign-in page) and mints short-lived ID tokens on demand by exchanging it
at securetoken.googleapis.com — the same mechanism research-automate uses in
auth/credentials.py, reimplemented here so this package stays self-contained.

The captured credential is the *real user's* Firebase refresh token, distinct
from any device's refresh token. Refreshing it issues a new refresh token
(Firebase rotates on every exchange) which we persist; it does NOT invalidate
the web app's separate session or any device's token (Firebase allows many
concurrent refresh tokens per user).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import threading
import time
from typing import Any

import requests

from . import config, store

log = logging.getLogger(__name__)

# Refresh a few minutes before expiry to absorb clock skew + round-trip latency.
_REFRESH_MARGIN_SECONDS = 300


class RevokedError(RuntimeError):
    """The refresh token is no longer valid — the user must `/login` again."""


class NotSignedInError(RuntimeError):
    """No account session is stored / loaded."""


class CustomTokenError(RuntimeError):
    """signInWithCustomToken rejected the token (bad/expired custom token)."""


def _decode_jwt_claims(id_token: str) -> dict[str, Any]:
    """Best-effort decode of a JWT payload (no signature verification).

    We just minted this id token via Google's Identity Toolkit, so we trust it
    enough to read the uid (`user_id`/`sub`) and `email` claims for display +
    persistence. The refresh token — not these claims — is the actual
    credential. Returns {} if the token is malformed.
    """
    try:
        payload_b64 = id_token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + padding)
        claims = json.loads(raw)
        return claims if isinstance(claims, dict) else {}
    except (IndexError, ValueError, binascii.Error):
        return {}


class AccountSession:
    """A live account session backed by a stored Firebase refresh token."""

    def __init__(
        self,
        *,
        uid: str,
        email: str,
        refresh_token: str,
        id_token: str | None = None,
        expires_at: float = 0.0,
        connected_at_ms: int | None = None,
    ) -> None:
        self._uid = uid
        self._email = email
        self._refresh_token = refresh_token
        self._id_token = id_token
        self._expires_at = expires_at  # epoch seconds; 0 ⇒ unknown ⇒ refresh now
        # Epoch-ms of the human sign-in that captured this session (set by
        # from_capture, persisted, rehydrated by load). The bridge heartbeat
        # compares the agent row's `revokedAt` against this to IGNORE a revoke
        # that predates this sign-in — a stale revoked row must not self-logout a
        # freshly-captured session (#848). None ⇒ unknown (a pre-change
        # rehydrated session) ⇒ the heartbeat conservatively honors the revoke.
        self.connected_at_ms = connected_at_ms
        self._lock = threading.Lock()

    # ── identity ──
    @property
    def uid(self) -> str:
        return self._uid

    @property
    def email(self) -> str:
        return self._email

    # ── construction ──
    @classmethod
    def from_capture(
        cls,
        *,
        refresh_token: str,
        id_token: str,
        uid: str,
        email: str,
        expires_in: int,
    ) -> "AccountSession":
        """Build from a fresh sign-in capture and persist it."""
        sess = cls(
            uid=uid,
            email=email,
            refresh_token=refresh_token,
            id_token=id_token,
            expires_at=time.time() + max(0, expires_in - _REFRESH_MARGIN_SECONDS),
            # Stamp the capture instant HERE (every fresh human sign-in flows
            # through from_capture) so the #848 stale-revoke guard has an
            # authoritative epoch even if the agent-row write fails downstream.
            connected_at_ms=int(time.time() * 1000),
        )
        sess._persist()
        return sess

    @classmethod
    def from_custom_token(cls, custom_token: str, *, email: str = "") -> "AccountSession":
        """Exchange a one-time custom token (remote device-flow, §11a) for a
        session and persist it.

        The SR web app mints ``createCustomToken(uid)`` for the *approver's own*
        uid; here we redeem it via Identity Toolkit's signInWithCustomToken REST
        endpoint to obtain the id+refresh token pair, then read the uid/email
        from the returned id token's claims.
        """
        try:
            resp = requests.post(
                config.SIGN_IN_WITH_CUSTOM_TOKEN_URL,
                params={"key": config.WEB_API_KEY},
                json={"token": custom_token, "returnSecureToken": True},
                timeout=15,
            )
        except requests.RequestException as e:
            raise CustomTokenError(f"custom-token exchange network error: {e}") from e

        if not resp.ok:
            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                body = {}
            err = body.get("error") if isinstance(body, dict) else None
            msg = err.get("message", "") if isinstance(err, dict) else str(err or resp.text[:200])
            raise CustomTokenError(f"custom-token rejected: {msg}")

        # Guard the success-body decode too: a non-JSON or non-object 2xx (e.g. an
        # HTML response from a proxy) must surface as CustomTokenError so the
        # bridge's `except CustomTokenError` can flip the flow to a clean error
        # state — not escape as a raw ValueError/AttributeError and wedge the poll.
        try:
            data = resp.json()
        except ValueError as e:
            raise CustomTokenError("custom-token exchange returned a non-JSON response") from e
        if not isinstance(data, dict):
            raise CustomTokenError("custom-token exchange returned a non-object response")
        id_token = data.get("idToken", "")
        refresh_token = data.get("refreshToken", "")
        if not id_token or not refresh_token:
            raise CustomTokenError("custom-token exchange returned no tokens")
        claims = _decode_jwt_claims(id_token)
        uid = claims.get("user_id") or claims.get("sub") or ""
        if not uid:
            raise CustomTokenError("could not determine uid from exchanged token")
        return cls.from_capture(
            refresh_token=refresh_token,
            id_token=id_token,
            uid=uid,
            email=email or claims.get("email", ""),
            expires_in=int(data.get("expiresIn", 3600) or 3600),
        )

    @classmethod
    def load(cls) -> "AccountSession | None":
        """Reconstruct from the secret store, or None if not signed in."""
        blob = store.load()
        if not blob:
            return None
        rt = blob.get("refresh_token")
        uid = blob.get("uid")
        if not rt or not uid:
            return None
        cap = blob.get("connected_at_ms")
        return cls(
            uid=uid,
            email=blob.get("email", ""),
            refresh_token=rt,
            id_token=None,  # force a refresh on first use → validates the token
            expires_at=0.0,
            # Rehydrate the original capture epoch (absent on pre-change blobs →
            # None → the heartbeat conservatively honors a revoke until re-signin).
            connected_at_ms=int(cap) if isinstance(cap, (int, float)) else None,
        )

    # ── token access ──
    def id_token(self, force: bool = False) -> str:
        """Return a valid ID token, refreshing if expired/unknown (or forced).

        ``force=True`` is used by the Firestore client on a 401 to mint a fresh
        token before retrying, rather than re-sending the cached one.
        """
        with self._lock:
            if force or self._id_token is None or time.time() >= self._expires_at:
                self._refresh_locked()
            assert self._id_token is not None
            return self._id_token

    def _refresh_locked(self) -> None:
        try:
            resp = requests.post(
                config.SECURE_TOKEN_URL,
                params={"key": config.WEB_API_KEY},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                timeout=10,
            )
        except requests.RequestException as e:
            log.warning("refresh: network error %s — keeping stored token", e)
            raise

        if resp.status_code == 400:
            body = resp.json() if resp.content else {}
            err = body.get("error")
            msg = err.get("message", "") if isinstance(err, dict) else str(err or "")
            if any(
                k in msg
                for k in (
                    "INVALID_REFRESH_TOKEN",
                    "TOKEN_EXPIRED",
                    "USER_DISABLED",
                    "USER_NOT_FOUND",
                )
            ):
                raise RevokedError(f"refresh token rejected: {msg}")
        if not resp.ok:
            raise RuntimeError(f"refresh HTTP {resp.status_code}: {resp.text}")

        data: dict[str, Any] = resp.json()
        new_refresh = data["refresh_token"]
        self._refresh_token = new_refresh
        self._id_token = data["id_token"]
        self._uid = data.get("user_id") or self._uid
        self._expires_at = time.time() + max(
            0, int(data["expires_in"]) - _REFRESH_MARGIN_SECONDS
        )
        # Persist the rotated refresh token BEFORE returning so a crash can't
        # strand us on a token Firebase already invalidated.
        self._persist()

    # ── persistence ──
    def _persist(self) -> None:
        blob: dict[str, Any] = {
            "uid": self._uid,
            "email": self._email,
            "refresh_token": self._refresh_token,
        }
        if self.connected_at_ms is not None:
            blob["connected_at_ms"] = int(self.connected_at_ms)
        store.save(blob)

    def logout(self) -> None:
        store.clear()
        self._id_token = None
        self._refresh_token = ""
        self._expires_at = 0.0
