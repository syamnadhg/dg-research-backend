"""OS keystore wrapper with three-slot rotation for refresh-token atomicity.

The slots — `current`, `previous`, `pending` — exist because Windows DPAPI
(via the `keyring` library) does NOT expose atomic rename. A refresh-token
rotation is a multi-step sequence (POST to securetoken, persist new value,
discard old). If the BE process is killed between persisting the new value
and overwriting the old one, we need to recover without forcing a re-pair.

The slot dance:
1. Refresh starts → write new refresh_token to `pending` slot first.
2. Then promote: `previous = current`, `current = pending`, clear `pending`.
3. On startup self-heal (`try_recover`), try `pending` → `current` → `previous`
   in that order. The first slot that produces a valid token wins.

If `keyring` is unavailable (headless Linux without secret-service), fall
back to a chmod-0600 file at `~/.super-research/auth.json` — same three-slot
shape, atomic via `os.replace`.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Final, Literal

log = logging.getLogger(__name__)

SERVICE: Final = "super-research"
Slot = Literal["current", "previous", "pending"]
SLOTS: Final[tuple[Slot, ...]] = ("current", "previous", "pending")
RECOVER_ORDER: Final[tuple[Slot, ...]] = ("pending", "current", "previous")

# File fallback location. Created only if keyring access fails.
_FALLBACK_DIR = Path.home() / ".super-research"
_FALLBACK_PATH = _FALLBACK_DIR / "auth.json"
_INSTALL_UUID_PATH = _FALLBACK_DIR / "install_uuid"


def _keyring_account(slot: Slot, install_uuid: str) -> str:
    return f"{slot}:{install_uuid}"


def _try_keyring() -> "object | None":
    """Lazy import keyring so the module loads even on systems without it."""
    try:
        import keyring  # type: ignore[import-not-found]

        # Touch the backend; `keyring.get_keyring()` raises if no backend is wired.
        keyring.get_keyring()
        return keyring
    except Exception as e:  # pragma: no cover - environment-specific
        log.debug("keyring unavailable, falling back to file (%s)", e)
        return None


def _file_load() -> dict[str, str]:
    if not _FALLBACK_PATH.exists():
        return {}
    try:
        return json.loads(_FALLBACK_PATH.read_text())
    except Exception:
        log.warning("auth.json unreadable, treating as empty")
        return {}


def _file_save(blob: dict[str, str]) -> None:
    _FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    # Write to tmp + os.replace for atomicity on POSIX (best effort on Windows).
    fd, tmp = tempfile.mkstemp(dir=str(_FALLBACK_DIR), prefix=".auth.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(blob, fh)
        os.replace(tmp, _FALLBACK_PATH)
        try:
            os.chmod(_FALLBACK_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass  # Windows ignores POSIX mode bits
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install_uuid() -> str:
    """Get-or-create a stable per-install UUID, persisted to disk.

    Each install has one UUID for the life of `~/.super-research/`. It scopes
    the keyring accounts so multiple installs on the same user account don't
    clobber each other.
    """
    if _INSTALL_UUID_PATH.exists():
        try:
            val = _INSTALL_UUID_PATH.read_text().strip()
            if val:
                return val
        except OSError:
            pass
    _FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    val = uuid.uuid4().hex
    _INSTALL_UUID_PATH.write_text(val)
    try:
        os.chmod(_INSTALL_UUID_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return val


def get(slot: Slot, install_id: str) -> str | None:
    kr = _try_keyring()
    if kr is not None:
        try:
            val = kr.get_password(SERVICE, _keyring_account(slot, install_id))  # type: ignore[attr-defined]
            if val:
                return val
        except Exception as e:
            log.warning("keyring read of slot=%s failed: %s", slot, e)
    blob = _file_load()
    return blob.get(_keyring_account(slot, install_id))


def set(slot: Slot, install_id: str, value: str) -> None:  # noqa: A001 - dict-ish API
    kr = _try_keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, _keyring_account(slot, install_id), value)  # type: ignore[attr-defined]
            return
        except Exception as e:
            log.warning("keyring write of slot=%s failed, using file: %s", slot, e)
    blob = _file_load()
    blob[_keyring_account(slot, install_id)] = value
    _file_save(blob)


def delete(slot: Slot, install_id: str) -> None:
    kr = _try_keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, _keyring_account(slot, install_id))  # type: ignore[attr-defined]
        except Exception:
            pass  # Already gone or backend complaint — fall through to file
    blob = _file_load()
    blob.pop(_keyring_account(slot, install_id), None)
    _file_save(blob)


def promote_pending(install_id: str) -> None:
    """Atomic-ish slot rotation: previous <- current, current <- pending, pending cleared.

    Used at the tail of a successful refresh-token rotation. Read pending
    first; if it's absent, no-op (caller didn't actually persist a new
    token).
    """
    new_token = get("pending", install_id)
    if not new_token:
        return
    old_current = get("current", install_id)
    if old_current:
        set("previous", install_id, old_current)
    set("current", install_id, new_token)
    delete("pending", install_id)


def try_recover(install_id: str) -> tuple[Slot, str] | None:
    """Startup self-heal: probe slots in recovery order, return first usable.

    Returns (slot, token) so the caller knows which slot a recovered token
    came from. Caller is responsible for testing it against securetoken and
    deciding whether to promote or discard.
    """
    for slot in RECOVER_ORDER:
        try:
            val = get(slot, install_id)
        except Exception as e:
            log.warning("recover: slot=%s read failed: %s", slot, e)
            continue
        if val:
            return slot, val
    return None


def clear_all(install_id: str) -> None:
    """Wipe all slots. Used on `--unpair` and on detected refresh-token revoke."""
    for slot in SLOTS:
        try:
            delete(slot, install_id)
        except Exception:
            pass
