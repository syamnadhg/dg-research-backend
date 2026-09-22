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
shape, atomic via `os.replace`. A slot whose keyring write was REFUSED lands
there too, beside an `<account>@fallbackAt` stamp, and `get` returns that
stamped copy before asking the keyring (see `_refused_write_copy`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
import sys
import tempfile
import traceback
import uuid
from datetime import datetime, timezone
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
# Durable, append-only audit of the two keystore ops that destroy a credential
# nothing else holds: `clear_all`, and the keychain delete a FAILED write makes
# before rewriting. Survives os._exit / pythonw (no stdout) / taskkill — written
# BEFORE deletion so a wipe always names its culprit even if the supervisor's
# console log is lost. ⛔ NOT every delete: `delete()` is also the routine tail
# of every rotation (`pending` after promotion), and a line per refresh in a log
# nothing rotates would bury the two that matter. ⛔ And not a delete that is
# never attempted: a LOCKED keychain refuses every op, so the failed write below
# tries no delete there and writes no record — otherwise every refresh, on every
# slot, left a stack trace here for something that destroyed nothing.
_WIPE_LOG = _FALLBACK_DIR / "keystore-audit.log"
# Cross-process lock file serialising refresh-token rotation across the N
# separate `--serve` worker processes (a per-process threading.Lock can't —
# see auth/credentials.py). Co-located with the keystore it guards.
_REFRESH_LOCK_PATH = _FALLBACK_DIR / ".refresh.lock"


def _write_wipe_audit(install_id: str, reason: str, *, event: str = "clear_all",
                      slot: str | None = None) -> None:
    """Durable, append-only, fsync'd record of a destructive keystore op.

    Written BEFORE the deletion — from `clear_all` (every slot, `slot=None`) and
    from `set()`'s failure path (one slot, the keychain item it removes so the
    rewrite can own it) — so a wipe is always attributable, even when the
    calling process is a console-attached supervisor whose own log() is lost, a
    pythonw daemon with no stdout, or a worker about to `os._exit`. The
    traceback names the exact caller (a crash-loop wipe vs a genuine-revoke wipe
    vs an --unpair are otherwise indistinguishable post-hoc). Best-effort: never
    raises, never blocks the operation it audits.
    """
    try:
        _FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,  # clear_all | keyring-delete-before-rewrite
            # clear_all: unpair | retire | revoke | crash-loop | ...
            # keyring-delete-before-rewrite: the refused write's OSStatus hint
            "reason": reason,
            "slot": slot,  # None = every slot
            "install": (install_id or "")[:8],
            "pid": os.getpid(),
            "worker_id": os.environ.get("DG_WORKER_ID", os.environ.get("SR_WORKER_ID", "?")),
            "exe": Path(sys.executable).name,  # python.exe vs pythonw.exe
            "argv": " ".join(sys.argv[:6]),
            # Last frames of the call stack → WHO destroyed it and why.
            "stack": [ln.strip() for ln in traceback.format_stack()[-8:-1]],
        }
        with open(_WIPE_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            try:
                os.fsync(fh.fileno())  # survive an immediate os._exit
            except OSError:
                pass
    except Exception:
        pass  # an audit failure must never stop (or crash) the real op


@contextlib.contextmanager
def cross_process_refresh_lock(timeout: float = 15.0):
    """Serialise refresh-token rotation ACROSS the N separate `--serve` worker
    processes. The in-process `threading.Lock` in credentials.py only serialises
    threads within ONE interpreter; N worker processes each get their own and so
    can POST the same `current` refresh token concurrently. This OS-level
    advisory lock (msvcrt.locking on Windows / fcntl.flock on POSIX) closes that
    gap. Best-effort: if the platform lock primitive is unavailable or the wait
    times out, we proceed UNLOCKED rather than block a refresh forever — the
    re-read-before-POST + re-read-before-wipe guards still prevent a spurious
    revoke; the lock is the primary defence, those are the safety net.
    """
    import time as _time

    # --- Acquire (all acquisition errors handled HERE, before the single yield;
    # we must never yield twice — a body exception thrown back into the generator
    # at the yield would otherwise be masked by a second yield). ---
    fh = None
    locked = False
    try:
        _FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
        fh = open(_REFRESH_LOCK_PATH, "a+")
    except Exception:
        fh = None  # can't even create the lock file → degrade to unlocked
    if fh is not None:
        try:
            start = _time.monotonic()
            if sys.platform == "win32":
                import msvcrt
                while True:
                    try:
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError:
                        if _time.monotonic() - start > timeout:
                            break
                        _time.sleep(0.1)
            else:
                import fcntl
                while True:
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except OSError:
                        if _time.monotonic() - start > timeout:
                            break
                        _time.sleep(0.1)
        except Exception:
            locked = False  # lock primitive unusable → degrade to unlocked

    # --- The ONE yield. The body runs here; its exceptions propagate normally. ---
    try:
        yield locked
    finally:
        if fh is not None:
            try:
                if locked:
                    if sys.platform == "win32":
                        import msvcrt
                        try:
                            fh.seek(0)
                            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                        except OSError:
                            pass
                    else:
                        import fcntl
                        try:
                            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            pass
            finally:
                try:
                    fh.close()
                except OSError:
                    pass


def _keyring_account(slot: Slot, install_uuid: str) -> str:
    return f"{slot}:{install_uuid}"


def _try_keyring() -> "object | None":
    """Lazy import keyring so the module loads even on systems without it.

    Returns the keyring module ONLY when a real secret-store backend is wired.
    `keyring.get_keyring()` never raises on a headless host — it returns the
    `fail.Keyring` sentinel (and `chainer.ChainerBackend` with no usable
    children), whose every get/set/delete THROWS. Treating that sentinel as a
    live backend made every keystore op throw + log a WARNING on file-fallback
    hosts (headless Linux / WSL). Detect the sentinel and fall back to the file
    store cleanly instead. (cross-platform parity)
    """
    try:
        import keyring  # type: ignore[import-not-found]
        from keyring.backends import fail as _fail  # type: ignore[import-not-found]

        kr = keyring.get_keyring()
        if isinstance(kr, _fail.Keyring):
            log.debug("keyring has no real backend (fail.Keyring) — using file fallback")
            return None
        # A ChainerBackend with no usable children is equivalent to no backend.
        children = getattr(kr, "backends", None)
        if children is not None and not list(children):
            log.debug("keyring chainer has no usable backend — using file fallback")
            return None
        return keyring
    except Exception as e:  # pragma: no cover - environment-specific
        log.debug("keyring unavailable, falling back to file (%s)", e)
        return None


def _file_load() -> dict[str, str]:
    if not _FALLBACK_PATH.exists():
        return {}
    import time as _time
    # Retry ONLY transient OS read failures: a sibling worker mid-`os.replace`
    # can briefly make the read hit a Windows sharing violation or catch a
    # half-written file. Without the retry, a transient error would falsely
    # report "not signed in" under multi-worker contention.
    #
    # A ValueError (corrupt/incomplete JSON) on a STABLE file is NOT transient —
    # retrying it just burns ~1.4s of blocking sleeps on the file-fallback hot
    # path (headless Linux) before returning {} anyway. Read once; on persistent
    # ValueError treat as empty immediately. (A torn half-write also raises
    # ValueError, but the OSError-retry loop already re-reads across the
    # os.replace window, so a genuinely mid-write file is caught there.)
    for i in range(8):
        try:
            return json.loads(_FALLBACK_PATH.read_text())
        except ValueError:
            log.warning("auth.json contained invalid JSON, treating as empty")
            return {}
        except OSError:
            if i < 7:
                _time.sleep(0.05 * (i + 1))
                continue
            log.warning("auth.json unreadable after retries, treating as empty")
            return {}
    return {}


def _replace_with_retry(src: str, dst) -> None:
    """`os.replace` with retry for the Windows sharing-violation race. On Windows,
    replacing auth.json fails with PermissionError (WinError 5) or WinError 32 if
    a sibling process (e.g. another multi-worker `--serve`) has it open at that
    instant. The holder releases in milliseconds, so retry with a short backoff
    rather than failing the keystore write — an unretried failure cascaded into a
    transient Firestore-init error and a cross-worker reconnect-respawn loop that
    left the device perpetually offline under workerCount > 1. POSIX rename is
    atomic and never hits this (first attempt succeeds)."""
    import time as _time
    for i in range(15):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            transient = isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32)
            if not transient or i == 14:
                raise
            _time.sleep(min(0.4, 0.05 * (i + 1)))


def _file_save(blob: dict[str, str]) -> None:
    _FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    # Write to tmp + atomic replace; _replace_with_retry absorbs the Windows
    # multi-worker sharing-violation race on auth.json.
    fd, tmp = tempfile.mkstemp(dir=str(_FALLBACK_DIR), prefix=".auth.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(blob, fh)
        _replace_with_retry(tmp, _FALLBACK_PATH)
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


#: Suffix of the auth.json key that marks a slot's file copy as written because
#: the keyring REFUSED that write. `acct + _FALLBACK_STAMP` holds the UTC time.
_FALLBACK_STAMP: Final = "@fallbackAt"


def _file_peek() -> object:
    """One QUIET read of auth.json, for `get`'s stamp check only.

    ⛔ Not `_file_load`: that one retries an unreadable file for ~1.4s and warns,
    which is right on the path that NEEDS the file and wrong on this one, which
    runs before every keyring read. An auth.json left unreadable (a one-off sudo
    run owns it) would have added both to every `get` on a machine whose keyring
    works. Any failure here means "no stamp", which is today's read order.
    """
    try:
        return json.loads(_FALLBACK_PATH.read_text())
    except (OSError, ValueError):
        return None


def _refused_write_copy(blob: object, acct: str) -> str | None:
    """The file's copy of `acct` if a REFUSED keyring write left it, else None.

    ⭐ Why that copy outranks the keyring: the file-shadow purge has run after
    every GOOD keyring write since 2026-06-19, so a stamped file entry exists
    only when the last write for the slot could not reach the keyring (or a
    purge failed, which `_purge_file_shadow` now says out loud) — the file
    copy is the newer one, and whatever the keychain still answers is older.
    Unstamped (legacy) copies are NOT promoted: nothing older is re-routed,
    and they keep the keyring-first order they always had.
    """
    if not isinstance(blob, dict):
        return None
    return blob.get(acct) if blob.get(acct + _FALLBACK_STAMP) else None


def get(slot: Slot, install_id: str) -> str | None:
    acct = _keyring_account(slot, install_id)
    # ⛔⛔ THE STAMPED COPY FIRST. When a write is refused AND the old keychain
    # entry cannot be removed (a locked keychain, an item another binary owns
    # that also refuses deletion), the keyring still answers — with the value
    # the rotation replaced. Asking it first made the fresh token unreachable:
    # the 2026-09-20 defect, still live on those two paths after its first fix.
    refused = _refused_write_copy(_file_peek(), acct)
    if refused:
        return refused
    kr = _try_keyring()
    if kr is not None:
        try:
            val = kr.get_password(SERVICE, acct)  # type: ignore[attr-defined]
            if val:
                return val
        except Exception as e:
            log.warning("keyring read of slot=%s failed: %s", slot, e)
    blob = _file_load()
    return blob.get(acct)


#: The macOS Security codes a keystore write actually meets, spelled out.
#:
#: ⛔ `keyring` renders an unmapped OSStatus as the literal string "Unknown
#: Error", so the log line that finally surfaced this said
#: `(-25244, 'Unknown Error')` — a number with no meaning attached, which is
#: why it read as noise for as long as it did. These are the ones that mean
#: something to us; anything else still gets its raw text.
_OSSTATUS_NAMES: Final[dict[int, str]] = {
    -25244: "errSecInvalidOwnerEdit: the item exists but belongs to a different binary",
    -25243: "errSecNoAccessForItem: the item has no access control entry for us",
    -25293: "errSecAuthFailed: the keychain refused authentication",
    -25308: "errSecInteractionNotAllowed: the keychain is locked and cannot prompt",
    -25300: "errSecItemNotFound",
    -25299: "errSecDuplicateItem",
}


def _oserror_hint(e: BaseException) -> str:
    """The exception's own text, plus what its OSStatus actually means.

    Keeps the raw message — a hint that replaced the evidence would be the same
    mistake in the other direction.
    """
    text = str(e)
    for code, name in _OSSTATUS_NAMES.items():
        if str(code) in text:
            return f"{text} — {name}"
    return text


#: errSecInteractionNotAllowed — the keychain is LOCKED and cannot prompt.
_INTERACTION_NOT_ALLOWED: Final[int] = -25308


def _refusal_forbids_deleting(e: BaseException) -> bool:
    """True when the refusal that stopped a write stops a DELETE just as surely.

    Only errSecInteractionNotAllowed (-25308): the keychain is locked, so every
    operation on it — read, write, delete — is refused until somebody unlocks
    it. Matched on the OSStatus in the message, the way `_oserror_hint` reads it
    (`keyring` hands us "Unknown Error" and the number, nothing typed).

    ⛔ Not -25244 and not -25243: those are about ONE item's ownership or ACL,
    the item deletes cleanly, and deleting it is the whole cure.
    """
    return str(_INTERACTION_NOT_ALLOWED) in str(e)


def _delete_before_rewrite(kr, acct: str, slot: str, install_id: str,
                           refusal: BaseException) -> str:
    """Remove the keychain item a refused `set` is about to rewrite.

    Returns "deleted", "failed", or "skipped" — what the closing log line says
    about the old entry has to be what actually happened to it.

    ⛔⛔ A LOCKED KEYCHAIN IS NOT AUDITED, BECAUSE NOTHING IS DELETED. The audit
    log is the durable record of the ops that destroy a credential nothing else
    holds, and nothing rotates it. With the login keychain locked, every `set`
    on every slot takes this path, so each token refresh wrote THREE records —
    measured 2026-09-21: 24 refreshes left 71 records and 79 KB, one worker,
    about 70 KB a day — each one a stack trace for a delete that then raised
    -25308 and destroyed nothing. That buries the `clear_all` wipes the log
    exists to attribute. A delete that cannot happen is not attempted and not
    recorded; every delete that IS attempted still gets its record first.
    """
    if _refusal_forbids_deleting(refusal):
        return "skipped"
    # The only destructive op on an error path, so it is audited like
    # `clear_all`: BEFORE the delete, naming the refusal that caused it.
    _write_wipe_audit(install_id, _oserror_hint(refusal),
                      event="keyring-delete-before-rewrite", slot=slot)
    try:
        kr.delete_password(SERVICE, acct)  # type: ignore[attr-defined]
    except Exception as de:
        log.warning("keyring slot=%s: could not delete the old entry "
                    "before rewriting (%s)", slot, _oserror_hint(de))
        return "failed"
    return "deleted"


def _purge_file_shadow(acct: str) -> None:
    """Drop `acct` (and its refused-write stamp) from auth.json so the file
    cannot answer with a stale token.

    Called after a good keyring write. Only rewrites the file when a shadow
    actually exists, so the hot path does no write.
    """
    stamp = acct + _FALLBACK_STAMP
    try:
        blob = _file_load()
        if acct in blob or stamp in blob:
            blob.pop(acct, None)
            blob.pop(stamp, None)
            _file_save(blob)
    except Exception as e:
        # Best-effort; never fail a good keyring write. ⛔ But never silent
        # either: a stamped copy left behind OUTRANKS the keyring in `get`, so
        # this is the one failure that can make a newer keychain value lose.
        log.warning(
            "keyring write of slot=%s succeeded but its file copy could not be "
            "removed (%s); reads may return that OLDER copy until a later write "
            "clears it", acct.partition(":")[0], e)


def _keyring_answers(kr, acct: str) -> Literal["value", "empty", "unknown"]:
    """What would `get()` get out of the keyring for this account, right now?

    ⭐ ASKED, NOT INFERRED. The first version of this repair decided the same
    thing from whether a delete had raised — which is a different question and
    got it wrong in both directions: a delete that failed with "not found" was
    read as a stale entry surviving, and a delete that succeeded before a failed
    rewrite was read as a clean store when the rewrite might have left one.
    `get()` is the thing that matters; ask `get()`.

    ⛔⛔ THREE ANSWERS, NOT TWO. A read that RAISES (a locked keychain,
    errSecInteractionNotAllowed) is not a read that found nothing: the old
    entry may be sitting right there. Folding "unknown" into "empty" is what
    let the log call a keychain it could not open silent.
    """
    try:
        val = kr.get_password(SERVICE, acct)
    except Exception:
        return "unknown"
    # Mirrors `get`'s `if val:` — an empty string does not win a read.
    return "value" if val else "empty"


def set(slot: Slot, install_id: str, value: str) -> None:  # noqa: A001 - dict-ish API
    kr = _try_keyring()
    acct = _keyring_account(slot, install_id)
    if kr is not None:
        try:
            kr.set_password(SERVICE, acct, value)  # type: ignore[attr-defined]
            # Keyring is the live store → purge any file-fallback shadow for
            # this slot so auth.json can never hold a STALE token that a later
            # get() would return on a transient keyring read miss.
            _purge_file_shadow(acct)
            return
        except Exception as e:
            # ⛔⛔ A FAILED WRITE USED TO BUILD THE EXACT SHADOW THE LINE ABOVE
            # EXISTS TO DESTROY, and it was not hypothetical: on 2026-09-20 this
            # machine held `previous:<install>` in BOTH stores at once — the
            # keychain copy from 18:39:51Z, the file copy written fifty minutes
            # later by this very fallback. `get()` asked the keyring FIRST and
            # returned its value when non-empty, so the fresher file copy was
            # unreachable and the rotation had written to a store nobody reads.
            # On the `current` slot that is every refresh presenting a dead
            # token until the machine has to be paired again.
            #
            # ⭐ ONE DELETE DOES BOTH JOBS, WHICH IS WHY THERE IS ONLY ONE.
            # macOS answers errSecInvalidOwnerEdit (-25244) when the item EXISTS
            # but was created by a different binary — a new venv, a new wheel, a
            # reinstalled interpreter — because `set_password` MODIFIES in place
            # and the item's ACL does not trust us. Removing the item both lets
            # the rewrite below take ownership (curing it for every future
            # rotation) and, if that rewrite still fails, stops the stale value
            # answering reads. An earlier draft had two deletes for those two
            # jobs; the second could never fire usefully, and its test passed on
            # the first one's work.
            #
            # ⛔⛔ BUT THE NEW TOKEN IS MADE DURABLE BEFORE ANYTHING IS DELETED.
            # The delete destroys the keychain's copy; if the rewrite then fails
            # as well, the file is the only place the credential exists. So it
            # goes there FIRST, stamped as a refused write so `get` prefers it
            # over whatever the keychain still answers — and if even that
            # raises, nothing has been deleted and the old entry survives.
            blob = _file_load()
            blob[acct] = value
            blob[acct + _FALLBACK_STAMP] = datetime.now(timezone.utc).isoformat()
            _file_save(blob)
            # Audited, and skipped when the keychain is locked and no delete
            # can happen at all — see `_delete_before_rewrite`.
            fate = _delete_before_rewrite(kr, acct, slot, install_id, e)
            try:
                kr.set_password(SERVICE, acct, value)  # type: ignore[attr-defined]
                if fate == "deleted":
                    log.info(
                        "keyring slot=%s belonged to another binary (%s) — "
                        "recreated it under this one", slot, _oserror_hint(e))
                else:
                    # Nothing was removed, so nothing was re-created: the
                    # keychain simply took the second write (it was locked for
                    # the first). Saying otherwise would name a cure that never
                    # ran as the reason this worked.
                    log.info(
                        "keyring slot=%s refused the first write (%s) and took "
                        "the second, with the old entry left as it was",
                        slot, _oserror_hint(e))
                _purge_file_shadow(acct)
                return
            except Exception:
                pass
            # The new token is in the file and `get` reads it first; what is
            # left to say is what the KEYCHAIN still holds, for anything that
            # reads it directly — an older install, the binary that owns it.
            answer = _keyring_answers(kr, acct)
            if answer == "value":
                # Two stores, disagreeing, and the old one cannot be silenced.
                # ERROR, and name the remedy — a WARNING is what hid this for
                # as long as it hid. What happened to the old entry is said
                # exactly: a delete that was refused, one a locked keychain
                # never let us try, and — a race — one that is back.
                became = {"failed": "that could not be removed",
                          "skipped": "that the locked keychain would not let "
                                     "us remove",
                          "deleted": "that is there again after being removed",
                          }[fate]
                log.error(
                    "keyring write of slot=%s failed (%s) and an OLDER entry is "
                    "still readable there %s. This install now reads the new "
                    "token from the file store; anything else reading the "
                    "keychain gets the old one. "
                    "Clear it with: security delete-generic-password -s %s -a %s",
                    slot, _oserror_hint(e), became, SERVICE, acct)
            elif answer == "unknown":
                # ⛔ Not "silent": a keychain we cannot read may still hold the
                # old entry. Say only what is known.
                log.error(
                    "keyring write of slot=%s failed (%s) and the keychain could "
                    "not be read back to check for an older entry. This install "
                    "now reads the new token from the file store; if an older "
                    "entry is there, anything else reading the keychain gets it. "
                    "Clear it with: security delete-generic-password -s %s -a %s",
                    slot, _oserror_hint(e), SERVICE, acct)
            else:
                log.warning(
                    "keyring write of slot=%s failed (%s); it holds nothing "
                    "readable for that slot, so the new token is kept in the "
                    "file store and read from there", slot, _oserror_hint(e))
            return
    blob = _file_load()
    blob[acct] = value
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
    blob.pop(_keyring_account(slot, install_id) + _FALLBACK_STAMP, None)
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


def clear_all(install_id: str, *, reason: str) -> None:
    """Wipe all slots. De-authenticates the WHOLE install (slots are keyed by
    install_uuid, NOT per-worker), so this is only ever correct on a PROVEN
    refresh-token revoke or an explicit user action (--unpair / --retire).

    `reason` is REQUIRED and recorded to the durable wipe-audit log BEFORE any
    deletion — so a future forensic can tell a genuine-revoke wipe from a
    user-intent wipe (and never again has to reconstruct an unattributed wipe
    from absence-of-evidence). Pass one of: "unpair", "retire", "revoke",
    "crash-loop", or a precise short tag.
    """
    _write_wipe_audit(install_id, reason)
    for slot in SLOTS:
        try:
            delete(slot, install_id)
        except Exception:
            pass
