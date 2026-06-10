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
import uuid
from typing import Any

from . import config

log = logging.getLogger(__name__)

_SELECTED_DEVICE = "selectedDeviceId"
_SELECTED_UID = "selectedUid"
_RUNTIME = "runtime"
_RUNTIME_HOME = "runtimeHome"          # where the skill was installed (str path)
_RUNTIME_LOCATION = "runtimeLocation"  # "local" (this host) | "wsl"
_RUNTIME_DISTRO = "runtimeDistro"      # WSL distro name (None for a local install)
_INSTALL_ID = "installId"
_LABEL = "agentLabel"

# Default display name for the agent session in the app's "Shared with" popup;
# renamable from the FE (the rename writes the label onto the agentSessions doc,
# and the bridge preserves an FE rename across reconnects — see bridge.py).
_DEFAULT_LABEL = "Super Agent"

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
        # Pop EAGERLY (list, not a generator): a short-circuiting any() would stop
        # at the first non-None key and orphan the rest.
        popped = [prefs.pop(k, None) for k in (_SELECTED_DEVICE, _SELECTED_UID)]
        if any(v is not None for v in popped):
            save(prefs)


def get_runtime() -> str | None:
    """The chat runtime the skill was connected into (hermes/openclaw), or None.

    A host setting (not account-scoped): which runtime label to show on the
    sign-in page watermark + default for a remote-login approval page.
    """
    v = load().get(_RUNTIME)
    return v if isinstance(v, str) and v else None


def set_runtime(runtime: str, *, home: str | None = None,
                location: str | None = None, distro: str | None = None) -> None:
    """Record the connected runtime and (optionally) WHERE its skill was
    installed. The home/location/distro let the bridge's revoke-consult and
    `agent disconnect` remove a WSL install precisely (the skill lives under a
    \\\\wsl.localhost UNC home, not the Windows home). Passing only ``runtime``
    keeps the back-compat behavior."""
    with _lock:
        prefs = load()
        prefs[_RUNTIME] = runtime
        if home is not None:
            prefs[_RUNTIME_HOME] = home
        if location is not None:
            prefs[_RUNTIME_LOCATION] = location
        # distro is meaningful only for WSL; clear it for a Windows install so a
        # later Windows connect doesn't inherit a stale distro from a WSL one.
        if location == "wsl" and distro:
            prefs[_RUNTIME_DISTRO] = distro
        elif location is not None:
            prefs.pop(_RUNTIME_DISTRO, None)
        save(prefs)


def get_runtime_home() -> str | None:
    """The home dir the skill was installed under (a \\\\wsl.localhost UNC path
    for a WSL install), or None for an older/Windows-default connect."""
    v = load().get(_RUNTIME_HOME)
    return v if isinstance(v, str) and v else None


def get_runtime_location() -> str | None:
    v = load().get(_RUNTIME_LOCATION)
    if not (isinstance(v, str) and v):
        return None
    # Migrate the pre-rename value: native installs were once "windows", now
    # "local" (host-agnostic). Normalize on read so old prefs.json files behave.
    return "local" if v == "windows" else v


def get_runtime_distro() -> str | None:
    v = load().get(_RUNTIME_DISTRO)
    return v if isinstance(v, str) and v else None


def clear_runtime() -> None:
    """Forget the connected chat runtime + where its skill lived.

    Called by `agent disconnect` once the skill has been removed: the connection
    is gone, so status must stop claiming a now-skill-less runtime and a bare
    `agent` should re-onboard via `connect`. Mirrors `clear_selected_device`;
    idempotent (a no-op when nothing is recorded). Leaves the install id + label
    alone — those identify the host/agent across re-connects."""
    with _lock:
        prefs = load()
        keys = (_RUNTIME, _RUNTIME_HOME, _RUNTIME_LOCATION, _RUNTIME_DISTRO)
        # Pop EAGERLY (list, not a generator): a short-circuiting any() would stop
        # at the first non-None key and orphan the rest (e.g. leave runtimeHome).
        popped = [prefs.pop(k, None) for k in keys]
        if any(v is not None for v in popped):
            save(prefs)


def get_or_create_install_id() -> str:
    """A STABLE per-install id, minted once and persisted in prefs.json.

    Used as the ``users/{uid}/agentSessions/{id}`` doc id so the agent shows as
    one stable row in the app's "Shared with" popup. It lives in prefs (NOT the
    keyring store blob, which `store.clear()` wipes on /logout) precisely so the
    id survives logout/login and bridge restarts — re-login overwrites the same
    row rather than accreting a new one. It is account-agnostic (one per host
    install): pills follow the run's uid, so this id only identifies the agent,
    never the account.
    """
    with _lock:
        prefs = load()
        iid = prefs.get(_INSTALL_ID)
        if isinstance(iid, str) and iid:
            return iid
        iid = uuid.uuid4().hex
        prefs[_INSTALL_ID] = iid
        save(prefs)
        return iid


def get_label() -> str:
    """The agent's display label for the "Shared with" popup (default "Super Agent")."""
    v = load().get(_LABEL)
    return v if isinstance(v, str) and v else _DEFAULT_LABEL


def set_label(label: str) -> None:
    with _lock:
        prefs = load()
        prefs[_LABEL] = label
        save(prefs)
