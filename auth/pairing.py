"""Pair-code generation + Firebase REST helpers used at pair / re-pair time.

The 8-char pair code is the only thing the user types between the BE
terminal and the FE Account page (or between the Reset email and the FE
Account page). It is the device's permanent identifier from the moment of
first claim until a Reset Pair Code event rotates it.

Alphabet: 31 characters — digits 2-9 (8) + uppercase A-Z minus I, L, O (23).
Excludes 0 (zero) and 1 (one) so they can't be confused with O and I/L
when typed by a human reading their phone.
"""

from __future__ import annotations

import secrets
from typing import Final

import requests

ALPHABET: Final = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH: Final = 8


def generate_code() -> str:
    """Cryptographically random 8-char code drawn from ALPHABET."""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str | None:
    """Strip dashes/whitespace + uppercase; return None if not a valid code shape.

    Accepts `k7xq-9b2m`, `K7XQ 9B2M`, `K7XQ9B2M`, etc. Rejects anything
    that doesn't land on exactly 8 characters from ALPHABET.
    """
    if not raw:
        return None
    cleaned = "".join(c for c in raw.upper() if c.isalnum())
    if len(cleaned) != CODE_LENGTH:
        return None
    if any(c not in ALPHABET for c in cleaned):
        return None
    return cleaned


def format_for_display(code: str) -> str:
    """Insert a dash at position 4 for terminal/email display: K7XQ-9B2M."""
    if len(code) != CODE_LENGTH:
        return code
    return f"{code[:4]}-{code[4:]}"


# --- Firebase REST endpoints ---------------------------------------------------
# https://firebase.google.com/docs/reference/rest/auth#section-sign-in-with-custom-token
_SIGN_IN_CUSTOM_TOKEN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"
)


class CustomTokenExchangeError(RuntimeError):
    """Raised when accounts:signInWithCustomToken returns a non-200."""


def exchange_custom_token(
    custom_token: str, web_api_key: str, *, timeout: float = 10.0
) -> dict:
    """Trade a Firebase custom token for an ID + refresh token pair.

    Returns the raw response dict containing at least `idToken`,
    `refreshToken`, `expiresIn`, `localId` (the Firebase uid). Raises on
    HTTP error so the caller surfaces a clear pair failure to the user.
    """
    resp = requests.post(
        _SIGN_IN_CUSTOM_TOKEN_URL,
        params={"key": web_api_key},
        json={"token": custom_token, "returnSecureToken": True},
        timeout=timeout,
    )
    if not resp.ok:
        raise CustomTokenExchangeError(
            f"signInWithCustomToken HTTP {resp.status_code}: {resp.text}"
        )
    return resp.json()
