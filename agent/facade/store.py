"""Secure storage for the bridge's account session.

Mirrors the proven pattern in research-automate/auth/keystore.py — OS keyring
with a chmod-0600 JSON file fallback — but in a SEPARATE namespace
(``config.STORE_SERVICE`` = "super-agent", dir ~/.super-agent) so it can never
touch the device daemon's "super-research" slots.

The stored blob is a single JSON object:

    {"uid": "...", "email": "...", "refresh_token": "..."}

The **bridge process is the single owner that REFRESHES** the refresh token
(rotating it on each securetoken exchange). The host CLI only ever READS it
(`status`) or CLEARS it (`logout`) — it never refreshes — so exactly one process
ever rotates the token and we don't need the three-slot rotation dance the
device daemon uses for multi-refresher safety. We still write atomically (temp
file + os.replace) and persist the new refresh token BEFORE updating in-memory
state so a kill mid-write is recoverable.

Storage backend: on Windows the keyring backend is the DPAPI-backed Credential
Locker (encrypted at rest, per-user). The chmod-0600 JSON file is a LAST-RESORT
fallback used only if no keyring backend is available; on that path the account
refresh token is at rest with only filesystem ACLs (a loud warning is logged).
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
from typing import Any

from . import config

log = logging.getLogger(__name__)

_KEYRING_ACCOUNT = "session"

_STORE_DIR = config.store_dir()
_FALLBACK_PATH = _STORE_DIR / "session.json"

# Warn about the unencrypted plaintext fallback once per process, not on every
# (hourly) token rotation.
_warned_plaintext = False


def _try_keyring() -> Any | None:
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.get_keyring()  # raises if no backend wired
        return keyring
    except Exception as e:  # pragma: no cover - environment-specific
        log.debug("keyring unavailable, falling back to file (%s)", e)
        return None


def _file_load() -> dict[str, str] | None:
    if not _FALLBACK_PATH.exists():
        return None
    try:
        data = json.loads(_FALLBACK_PATH.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        log.warning("session.json unreadable, treating as absent")
        return None


def _file_save(blob: dict[str, str]) -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(_STORE_DIR), prefix=".session.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(blob, fh)
        os.replace(tmp, _FALLBACK_PATH)
        try:
            os.chmod(_FALLBACK_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass  # Windows ignores POSIX mode bits (DPAPI via keyring is primary there)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _file_delete() -> None:
    try:
        _FALLBACK_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:  # pragma: no cover
        log.warning("could not delete session.json: %s", e)


def load() -> dict[str, str] | None:
    """Return the stored session blob, or None if not signed in."""
    kr = _try_keyring()
    if kr is not None:
        try:
            raw = kr.get_password(config.STORE_SERVICE, _KEYRING_ACCOUNT)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            log.warning("keyring read failed, trying file: %s", e)
    return _file_load()


def save(blob: dict[str, str]) -> None:
    """Persist the session blob (atomic; keyring primary, file fallback)."""
    raw = json.dumps(blob)
    kr = _try_keyring()
    if kr is not None:
        try:
            kr.set_password(config.STORE_SERVICE, _KEYRING_ACCOUNT, raw)
            return
        except Exception as e:
            log.warning("keyring write failed, using file: %s", e)
    global _warned_plaintext
    if not _warned_plaintext:
        log.warning(
            "No OS keyring backend — storing the account refresh token UNENCRYPTED "
            "at %s (filesystem ACLs only). Configure a keyring backend for at-rest "
            "encryption.",
            _FALLBACK_PATH,
        )
        _warned_plaintext = True
    _file_save(blob)


def clear() -> None:
    """Wipe the stored session (used by /logout)."""
    kr = _try_keyring()
    if kr is not None:
        try:
            kr.delete_password(config.STORE_SERVICE, _KEYRING_ACCOUNT)
        except Exception:
            pass  # already gone / backend complaint — fall through to file
    _file_delete()
