"""Non-secret local preferences for the bridge.

Distinct from `store.py` (which holds the account refresh token in the OS
keyring): prefs are plain, non-sensitive settings — currently just which device
the agent runs on by default — kept in a small JSON file at
``~/.super-agent/prefs.json`` so a selection survives a bridge restart.

Deliberately NOT in the keyring: there is no secret here, and mixing a mutable
UI preference into the credential slot would churn the secret store. Written
atomically (temp file + os.replace), best-effort 0600.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
from typing import Any

from . import config

log = logging.getLogger(__name__)

_SELECTED_DEVICE = "selectedDeviceId"
_SELECTED_UID = "selectedUid"
_RUNTIME = "runtime"

# Serialize read-modify-write so concurrent bridge worker threads don't clobber.
_lock = threading.Lock()


def _path():
    return config.store_dir() / "prefs.json"


def load() -> dict[str, Any]:
    """Return the prefs dict (empty if absent/unreadable)."""
    p = _path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        log.warning("prefs.json unreadable, treating as empty")
        return {}


def save(prefs: dict[str, Any]) -> None:
    """Persist the prefs dict atomically (best-effort 0600)."""
    d = config.store_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".prefs.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(prefs, fh)
        os.replace(tmp, _path())
        try:
            os.chmod(_path(), stat.S_IRUSR | stat.S_IWUSR)  # 0600 (POSIX; no-op on Windows)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_selected_device(uid: str) -> str | None:
    """The deviceId the agent runs on by default for THIS account, or None.

    The selection is bound to the uid that made it: a selection belonging to a
    different account (e.g. a re-login that skipped /logout, or a selection that
    survived a restart) is invisible — so one account can never inherit
    another's target device.
    """
    data = load()
    dev = data.get(_SELECTED_DEVICE)
    owner = data.get(_SELECTED_UID)
    if isinstance(dev, str) and dev and owner == uid:
        return dev
    return None


def set_selected_device(device_id: str, uid: str) -> None:
    with _lock:
        prefs = load()
        prefs[_SELECTED_DEVICE] = device_id
        prefs[_SELECTED_UID] = uid
        save(prefs)


def clear_selected_device() -> None:
    with _lock:
        prefs = load()
        changed = any(prefs.pop(k, None) is not None for k in (_SELECTED_DEVICE, _SELECTED_UID))
        if changed:
            save(prefs)


def get_runtime() -> str | None:
    """The chat runtime the skill was connected into (hermes/openclaw), or None.

    A host setting (not account-scoped): which runtime label to show on the
    sign-in page watermark + default for a remote-login approval page.
    """
    v = load().get(_RUNTIME)
    return v if isinstance(v, str) and v else None


def set_runtime(runtime: str) -> None:
    with _lock:
        prefs = load()
        prefs[_RUNTIME] = runtime
        save(prefs)
