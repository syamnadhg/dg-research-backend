"""Non-secret local state for the bridge.

Distinct from `store.py` (which holds the account refresh token in the OS
keyring): these are the default device, the connected runtime, the install id, the
agent label, the parked sign-in announce, the sign-in epoch and the support-log
requests still being watched — kept in a small JSON file at
``~/.super-agent/prefs.json`` so they survive a bridge restart.

Deliberately NOT in the keyring: no credential lives here, and mixing mutable
state into the credential slot would churn the secret store. Written atomically
(temp file + os.replace), best-effort 0600.

⛔ "Non-secret" is not the same as "impersonal", and the sign-in announce is where
that stops being a distinction without a difference: it carries the account EMAIL
and the RESEARCH TOPIC the person asked for. Both are the file owner's own, both
already sit in the same home directory in `bridge.log`, and 0600 is the whole
protection — but nothing broader than the account's own email and topic may be
parked here, and no token ever.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
import time as _time
import uuid
from typing import Any

from . import config

log = logging.getLogger(__name__)

_SELECTED_DEVICE = "selectedDeviceId"
_SELECTED_UID = "selectedUid"
_RUNTIME = "runtime"
_RUNTIME_HOME = "runtimeHome"          # where the skill was installed (str path)
_RUNTIME_LOCATION = "runtimeLocation"  # "local" (this host) | "wsl"
_RUNTIME_DISTRO = "runtimeDistro"      # LEGACY: a WSL distro name written by the
#                                        pre-Model-A connect; no longer written
#                                        (a WSL runtime now connects in-distro),
#                                        only swept by clear_runtime for old prefs.
_ANNOUNCED_SIGNIN = "announcedSignInMs"
_ANNOUNCED_SIGNIN_UID = "announcedSignInUid"
_VERBOSE = "verbose"
_INSTALL_ID = "installId"
_LABEL = "agentLabel"
# The one-shot "just signed in" announce, parked on DISK so a bridge restart
# between the sign-in and the watchdog's next tick can no longer lose it. Bound to
# the uid that signed in, exactly like the device selection above: an announce
# belonging to a different account must never be delivered to this one.
_PENDING_ANNOUNCE = "pendingAnnounce"
_PENDING_ANNOUNCE_UID = "pendingAnnounceUid"

# ⭐⭐ THE TWO THINGS A PERSON IS WAITING ON WHEN THEY HAVE NO COMPUTER YET.
# Somebody asks for research, has no research computer, asks to use a public one,
# and then — nothing. The approval lands in Firestore where this agent cannot see
# it (`deviceAccessRequests` is `allow read, write: if false` to every credential,
# so the web route is the only door), and until 2026-09-20 nothing on this side
# ever knocked on that door unprompted. The owner approved, and the person found
# out twenty minutes later by asking "done?".
#
# ⛔ ON DISK, BECAUSE THE WAIT IS LONG. An approval can arrive hours after the
# ask; in memory it would not survive one bridge restart, and a restart inside a
# multi-hour wait is the normal case rather than the edge one.
#
# ⛔ UID-BOUND, exactly like the announce above and for the same reason: a
# re-login as a different account must not inherit the previous one's pending ask
# or its parked topic.
#
# ⚠ AND ON WHAT MAY BE PARKED HERE. The header's rule is the account's own email
# and topic — the topic is explicitly in scope. The device id of a STRANGER'S
# machine is new, and it is deliberate: it is the only handle the transition can
# be detected on. Note the distinction from `bridge.log`, which keeps a stranger's
# id OUT precisely because that file is uploadable to support; this file is not,
# and 0600 is its protection.
_DEVICE_ASK = "deviceAsk"
_DEVICE_ASK_UID = "deviceAskUid"
_HELD_RESEARCH = "heldResearch"
_HELD_RESEARCH_UID = "heldResearchUid"

# ⛔ THE ASK'S OWN LIFETIME. A refusal blocks asking again for a week, so a row
# that has neither been approved nor refused in that time is not coming back —
# and a record polled forever is a Firestore read a minute, for nothing.
_DEVICE_ASK_TTL = 7 * 24 * 3600
# ⛔ SHORTER FOR THE TOPIC, because starting research somebody asked for hours ago
# without being asked again is a surprise, not a convenience.
_HELD_RESEARCH_TTL = 6 * 3600

# ⭐⭐ A NUMBER THAT MOVES EVERY TIME "WHO IS SIGNED IN HERE" CHANGES (owner,
# 2026-09-25). A reader that saw "signed in" at epoch N and sees N+1 now knows the
# answer changed in between — a logout, a revoke, or a different sign-in — without
# having to compare emails or guess from timing. The 2026-09-24 incident was a
# true "✓ Signed in" delivered 19 s after the person logged out; nothing any
# reader held could tell it the fact had gone stale.
# ⛔ ON DISK, NOT IN MEMORY, because a counter that restarts at zero with the
# bridge would hand two different sessions the same number.
# ⛔ HOST-WIDE, NOT UID-BOUND: it counts changes to this computer's sign-in, and a
# switch from account A to B is exactly such a change.
_SIGNIN_EPOCH = "signinEpoch"

# ⭐⭐ THE SUPPORT-LOG REQUESTS STILL BEING WATCHED (owner, 2026-09-25). They lived
# in a dict in bridge memory, so a bridge restart — the ordinary case across a
# packaging wait, not the edge one — silently dropped the one message that says
# the logs arrived. Same shape as the parked announce and the device ask above.
# ⚠ WHAT IS PARKED: the support code, the account's OWN (or shared) computer id
# and name, the command/request ids and the chat that asked. All of it already
# sits in `bridge.log` for the same request; 0600 is the protection. Each record
# carries its uid, exactly like every other account-bearing key here.
_LOG_REQUESTS = "logRequests"
_LOG_REQUESTS_MAX = 20
# ⛔ A DAY, THEN FORGOTTEN. Long past the half hour the watcher cares about, so a
# `--status <code>` asked the next morning still gets the device name and age; not
# forever, because a code nobody will ever quote again is not worth a record.
_LOG_REQUEST_TTL = 24 * 3600

# Default display name for the agent session in the app's "Shared with" popup;
# renamable from the FE (the rename writes the label onto the agentSessions doc,
# and the bridge preserves an FE rename across reconnects — see bridge.py).
_DEFAULT_LABEL = "Super Agent"

# Serialize read-modify-write so concurrent bridge worker threads don't clobber.
# ⛔ RE-ENTRANT, AND `load()` TAKES IT TOO (2026-09-25): on Windows a read and a
# replace of the same file refuse each other (see `_retrying`), so inside this
# process the two are simply never allowed to overlap — and a writer, which calls
# `load()` while holding the lock, must be able to take it again. The retry stays
# for the one overlap a lock cannot see: another process (the CLI) reading.
_lock = threading.RLock()


def _path():
    return config.store_dir() / "prefs.json"


# ⛔⛔ ON WINDOWS A READ AND A REPLACE COLLIDE, IN BOTH DIRECTIONS (measured
# 2026-09-25: one thread reading prefs.json while another saved it, for three
# seconds — 576 reads and 879 replaces failed with PermissionError). Python opens
# files without FILE_SHARE_DELETE, so `os.replace` onto a file somebody is reading
# is refused, and a read that lands mid-replace is refused too. The reader then
# saw `{}` — a parked sign-in note or device ask briefly "did not exist" — and the
# writer's change was LOST (a note not parked, a delivered notice not marked). It
# was always possible; the news peek (2026-09-25) reads this file every few
# seconds, which made it likely. Both sides now retry, briefly and boundedly; the
# collision window is microseconds wide. POSIX never raises here.
_IO_RETRIES = 8
_IO_RETRY_STEP = 0.01   # seconds; linear backoff, ~0.36 s worst case in total


def _retrying(op):
    for attempt in range(_IO_RETRIES):
        try:
            return op()
        except PermissionError:
            if attempt == _IO_RETRIES - 1:
                raise
            _time.sleep(_IO_RETRY_STEP * (attempt + 1))
    return None  # pragma: no cover - the loop always returns or raises


def load() -> dict[str, Any]:
    """Return the prefs dict (empty if absent/unreadable)."""
    p = _path()
    if not p.exists():
        return {}
    try:
        with _lock:
            raw = _retrying(p.read_bytes)
        data = json.loads(raw.decode("utf-8"))
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
        with _lock:   # re-entrant: every locked writer already holds it
            _retrying(lambda: os.replace(tmp, _path()))
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


def get_announced_signin_ms(uid: str) -> int | None:
    """The sign-in (by its capture epoch) whose announce was last handed out.

    ⛔⛔ THIS IS THE HALF THAT MAKES THE ANNOUNCE RECOVERABLE, and the stretch
    shipped without it. The plan asked for "durable, RE-DERIVABLE state like runs
    have"; parking the event on disk delivered the DURABLE half and nothing more.
    Durable is not the same as recoverable: once the event is handed to a reader it
    is gone, and HTTP cannot tell you whether the reader received it. A poller that
    times out and closes GRACEFULLY takes the bytes into its socket buffer and dies
    — `wfile.write` raises nothing, so no restore fires, and the announce is lost
    exactly as the take-and-clear this replaced lost it. Measured by review, not
    reasoned about.

    ⭐ A WATERMARK CLOSES IT PERMANENTLY. The session already records WHEN the human
    signed in (`AccountSession.connected_at_ms`, persisted and rehydrated), so "this
    account signed in at T and nothing has announced T" is derivable from state that
    outlives any single request. A lost announce is re-minted on the next tick — as
    a plain "you are signed in", because the auto-start hints are the one part that
    cannot be re-derived. Degrading to less news beats degrading to silence.
    """
    data = load()
    ms = data.get(_ANNOUNCED_SIGNIN)
    owner = data.get(_ANNOUNCED_SIGNIN_UID)
    if not uid or not owner or owner != uid:
        return None
    return int(ms) if isinstance(ms, (int, float)) else None


def set_announced_signin_ms(ms: int, uid: str) -> None:
    """Record that the sign-in captured at ``ms`` has been announced."""
    if not uid:
        return
    with _lock:
        prefs = load()
        prefs[_ANNOUNCED_SIGNIN] = int(ms)
        prefs[_ANNOUNCED_SIGNIN_UID] = uid
        save(prefs)


def claim_signin_announce(ms: int, uid: str) -> tuple[str, int | None]:
    """Atomically claim the right to announce the sign-in captured at ``ms``.

    Returns ``(outcome, previous)`` where outcome is one of:
      • ``"won"``    — this caller owns the announce; the watermark has moved to ``ms``
      • ``"already"`` — ``ms`` is at or behind the watermark; say nothing
      • ``"first"``  — no watermark existed for this account; it has been set to
        ``ms`` and the caller must stay SILENT (the sign-in predates the record,
        so announcing it would greet somebody who signed in days ago)
    ``previous`` is the watermark before the call, for a rollback when the send
    that this claim authorised never reaches anybody.

    ⛔⛔ THIS EXISTS BECAUSE THE READ-MODIFY-WRITE IT REPLACES HAD NO MUTUAL
    EXCLUSION AT ALL, AND I MEASURED IT: 24 concurrent callers, 24 re-mints handed
    out, where the correct answer is one. `get_announced_signin_ms` reads OUTSIDE
    `_lock` (only the setter takes it), so the compare sat between a lockless read
    and a locked write — exactly the clobber `_lock`'s own comment says it is here
    to prevent. The parked-note take was already atomic under one lock and
    measured 1 of 24, so the durable half was right and only the RECOVERABLE half,
    added in the same stretch, was unguarded.

    ⭐ A PROCESS-LOCAL LOCK IS THE RIGHT SCOPE, not a file lock. The watchdog is a
    separate process but reaches this watermark only over loopback HTTP, so every
    reader and writer of it runs inside the one bridge process.
    """
    if not uid:
        return ("already", None)
    with _lock:
        prefs = load()
        owner = prefs.get(_ANNOUNCED_SIGNIN_UID)
        raw = prefs.get(_ANNOUNCED_SIGNIN)
        # A watermark belonging to a DIFFERENT account is not this account's
        # watermark — same rule the getter applies, so a re-login under another uid
        # can neither inherit nor be suppressed by the previous owner's mark.
        seen = (int(raw) if isinstance(raw, (int, float)) and owner == uid else None)
        if seen is not None and int(ms) <= seen:
            return ("already", seen)
        prefs[_ANNOUNCED_SIGNIN] = int(ms)
        prefs[_ANNOUNCED_SIGNIN_UID] = uid
        save(prefs)
        return (("won" if seen is not None else "first"), seen)


def restore_announced_signin_ms(ms: int | None, uid: str, *,
                                expected: int | None = None) -> bool:
    """Put the watermark back where a claim found it, after a send that raised.

    Returns whether it was restored. ``expected`` is the value this caller's own
    claim INSTALLED: the restore only happens while that is still what the file
    holds, so a rollback cannot undo somebody else's newer, delivered claim.

    ⛔ The note itself is already restored on that path and the watermark was not,
    so the restored note stayed claimable while the mark said it had gone out —
    two records of the same fact disagreeing.

    ⛔⛔ AND THE FIRST VERSION WAS A BLIND WRITE, which cross-verification measured
    into two separate losses. Watermark 1000; request A claims 2000; request B
    claims 3000 and its response is DELIVERED; A's send then raises and writes 1000
    back — so B's delivered 3000 is unmarked and gets re-announced. And when the
    stored mark belongs to ANOTHER account the claim reports no previous value, so
    the rollback's ``None`` branch deleted that account's watermark outright. A
    compare-and-swap closes both: a rollback is only ever allowed to undo itself.

    ``None`` means there was no mark to begin with, so both keys are removed. ⚠ And
    NOT because a zero would "suppress" anything — cross-verification measured that
    claim wrong: the compare is `ms <= seen`, so a stored 0 still lets any later
    sign-in win. Removing the keys is right for a plainer reason: a 0 asserts this
    account was announced at the epoch, which never happened.
    """
    if not uid:
        return False
    with _lock:
        prefs = load()
        raw = prefs.get(_ANNOUNCED_SIGNIN)
        owner = prefs.get(_ANNOUNCED_SIGNIN_UID)
        current = (int(raw) if isinstance(raw, (int, float)) and owner == uid else None)
        if expected is not None and current != int(expected):
            # Somebody else moved it after our claim — theirs is newer and, unlike
            # ours, may have been delivered. Leave it alone.
            return False
        if ms is None:
            popped = [prefs.pop(k, None)
                      for k in (_ANNOUNCED_SIGNIN, _ANNOUNCED_SIGNIN_UID)]
            if any(v is not None for v in popped):
                save(prefs)
            return True
        prefs[_ANNOUNCED_SIGNIN] = int(ms)
        prefs[_ANNOUNCED_SIGNIN_UID] = uid
        save(prefs)
        return True


def seal_signin_announce(ms: int, uid: str) -> int | None:
    """Move the watermark to AT LEAST ``ms`` for ``uid``; never backwards.

    Returns the watermark after the call (None when nothing could be recorded).

    ⭐⭐ WHAT "THE PERSON HAS BEEN TOLD, OR THE SIGN-IN IS OVER" LOOKS LIKE ON DISK
    (owner, 2026-09-25). Two callers, one meaning:
      • a chat reply that said "signed in" (`POST /signin/ack`) — the person was
        told, so no re-mint and no "one repeat" may follow it;
      • a logout or revoke — the sign-in has ENDED, so nothing may re-announce it.
        Before this, logout left the mark where it was and a `/updates` that had
        captured the session before the logout could still win the re-mint claim
        and hand out "signed in" for a session that no longer existed.

    ⛔ A MAX, NOT A SET, and not `claim_signin_announce`: a claim answers "already"
    at or behind the mark and "first" with no mark, and both callers want the same
    outcome in every case — the mark at least here — without a result to misread.

    ⛔ A MARK OWNED BY ANOTHER ACCOUNT IS REPLACED, not compared against — the same
    rule the claim applies: another account's mark is not this account's mark.
    """
    if not uid:
        return None
    with _lock:
        prefs = load()
        mark, mark_uid = prefs.get(_ANNOUNCED_SIGNIN), prefs.get(_ANNOUNCED_SIGNIN_UID)
        seen = int(mark) if isinstance(mark, (int, float)) and mark_uid == uid else None
        if seen is not None and seen >= int(ms):
            return seen
        prefs[_ANNOUNCED_SIGNIN] = int(ms)
        prefs[_ANNOUNCED_SIGNIN_UID] = uid
        save(prefs)
        return int(ms)


def get_signin_epoch() -> int:
    """How many times "who is signed in here" has changed on this computer."""
    raw = load().get(_SIGNIN_EPOCH)
    return int(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else 0


def bump_signin_epoch() -> int:
    """Advance the sign-in epoch by one and return the new value."""
    with _lock:
        prefs = load()
        raw = prefs.get(_SIGNIN_EPOCH)
        cur = int(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else 0
        prefs[_SIGNIN_EPOCH] = cur + 1
        save(prefs)
        return cur + 1


def get_verbose() -> bool:
    """Whether the bridge should log at DEBUG.

    ⛔⛔ THIS EXISTS BECAUSE THE ENVIRONMENT VARIABLE COULD NOT REACH THE BRIDGE,
    and that was found by cross-verification AFTER `SUPER_AGENT_VERBOSE` shipped as
    the fix for exactly this problem. The always-on bridge is started by launchd, by
    systemd, or by a scheduled task — and `autostart.py` writes NO environment into
    any of them: the generated plist has no `EnvironmentVariables` key and the unit
    has no `Environment=`. A LaunchAgent does not inherit a shell profile, so
    `export SUPER_AGENT_VERBOSE=1` reaches a foreground `agent serve` and nothing
    else. The switch was real, documented, printed by `agent doctor` — and inert on
    the recommended install, which is the only one that matters.

    ⭐ A PREF REACHES IT BECAUSE THE BRIDGE READS THIS FILE ITSELF, whoever started
    it. `agent verbose on` writes it; the next bridge start picks it up. The env var
    is kept as well: it is the right tool for a one-off foreground run, and on
    Windows a user-level variable does reach a scheduled task.
    """
    return bool(load().get(_VERBOSE))


def set_verbose(on: bool) -> None:
    """Turn detailed logging on or off for the next bridge start."""
    with _lock:
        prefs = load()
        if on:
            prefs[_VERBOSE] = True
        elif prefs.pop(_VERBOSE, None) is None:
            return
        save(prefs)


def get_pending_announce(uid: str) -> dict[str, Any] | None:
    """The not-yet-delivered "just signed in" announce for THIS account, or None.

    ⭐ WHY THIS IS ON DISK AT ALL. The announce used to live only in
    ``BridgeState._signed_in``, so any bridge restart between the sign-in capture
    and the watchdog's next tick lost it permanently — while a research COMPLETION
    in the same window lost nothing, because ``compute()`` re-derives those from the
    research store every tick. This is the durable half of that asymmetry.

    ⛔ UID-BOUND, for the same reason ``get_selected_device`` is: a re-login as a
    DIFFERENT account must not inherit the previous one's announce. Without the
    binding, signing in as B would hand B's watchdog A's email and A's topic.
    """
    # ⛔ AN EMPTY UID MATCHES AN EMPTY UID, and that was a real hole rather than a
    # theoretical one — found by a mutation that survived, then by the test written
    # to kill it. `set_pending_announce` is never CALLED with an empty uid, but a
    # truncated write or a hand-edited file can leave `pendingAnnounceUid: ""`, and
    # then `owner == uid` was satisfied by any caller asking with an empty uid. An
    # announce readable by whoever asks with nothing is the same cross-account leak
    # the binding exists to prevent, so neither side may be empty.
    if not uid:
        return None
    data = load()
    ev = data.get(_PENDING_ANNOUNCE)
    owner = data.get(_PENDING_ANNOUNCE_UID)
    if isinstance(ev, dict) and ev and owner and owner == uid:
        return ev
    return None


def set_pending_announce(event: dict[str, Any], uid: str) -> None:
    """Park the announce for ``uid``. Overwrites any earlier one — a fresh sign-in
    supersedes a stale, undelivered announce rather than queueing behind it."""
    with _lock:
        prefs = load()
        prefs[_PENDING_ANNOUNCE] = event
        prefs[_PENDING_ANNOUNCE_UID] = uid
        save(prefs)


def has_pending_announce() -> bool:
    """Whether ANY announce is parked, whoever it belongs to — for a clear that
    wants to say in the log that it actually removed something (owner,
    2026-09-25: the logout that should have closed the 2026-09-24 incident left
    no line at all). Never an answer to "may I deliver it" — that is
    `get_pending_announce`, uid-bound."""
    ev = load().get(_PENDING_ANNOUNCE)
    return isinstance(ev, dict) and bool(ev)


def clear_pending_announce() -> None:
    """Drop the parked announce (delivered, superseded, or signed out)."""
    with _lock:
        prefs = load()
        # Pop EAGERLY (a list, not a generator): a short-circuiting any() would
        # stop at the first non-None key and orphan the other one.
        popped = [prefs.pop(k, None) for k in (_PENDING_ANNOUNCE, _PENDING_ANNOUNCE_UID)]
        if any(v is not None for v in popped):
            save(prefs)


def _get_uid_bound(key: str, uid_key: str, uid: str,
                   ttl: int) -> dict[str, Any] | None:
    """One uid-bound, time-bounded record, or None.

    ⛔ AN EMPTY UID MATCHES AN EMPTY UID and that is a real hole, not a
    theoretical one — see the long note on `get_pending_announce`, where a
    truncated write left an empty owner readable by any caller asking with
    nothing. Neither side may be empty.

    ⛔ AND EXPIRY IS READ-SIDE, not swept. Nothing here runs on a timer, so a
    record that outlives its window has to stop answering rather than wait to be
    collected.
    """
    if not uid:
        return None
    data = load()
    rec = data.get(key)
    owner = data.get(uid_key)
    if not (isinstance(rec, dict) and rec and owner and owner == uid):
        return None
    try:
        age = _time.time() - float(rec.get("at") or 0)
    except (TypeError, ValueError):
        return None
    if age < 0 or age > ttl:
        return None
    return rec


def _set_uid_bound(key: str, uid_key: str, rec: dict[str, Any], uid: str) -> None:
    with _lock:
        prefs = load()
        prefs[key] = {**rec, "at": rec.get("at") or _time.time()}
        prefs[uid_key] = uid
        save(prefs)


def _clear_uid_bound(key: str, uid_key: str) -> None:
    with _lock:
        prefs = load()
        # Pop EAGERLY (a list, not a generator) — a short-circuiting any() would
        # stop at the first non-None key and orphan the other one.
        popped = [prefs.pop(k, None) for k in (key, uid_key)]
        if any(v is not None for v in popped):
            save(prefs)


def get_device_ask(uid: str) -> dict[str, Any] | None:
    """The public computer this account is waiting on an answer about, or None."""
    return _get_uid_bound(_DEVICE_ASK, _DEVICE_ASK_UID, uid, _DEVICE_ASK_TTL)


def set_device_ask(rec: dict[str, Any], uid: str) -> None:
    """Park the outstanding ask. A newer ask SUPERSEDES an older one rather than
    queueing behind it — one person can have several asks outstanding, but only
    the most recent is the one a chat is plausibly still waiting on."""
    _set_uid_bound(_DEVICE_ASK, _DEVICE_ASK_UID, rec, uid)


def clear_device_ask() -> None:
    """Answered, expired, superseded, or signed out."""
    _clear_uid_bound(_DEVICE_ASK, _DEVICE_ASK_UID)


def get_held_research(uid: str) -> dict[str, Any] | None:
    """A topic that had nowhere to run when it was asked for, or None."""
    return _get_uid_bound(_HELD_RESEARCH, _HELD_RESEARCH_UID, uid,
                          _HELD_RESEARCH_TTL)


def set_held_research(rec: dict[str, Any], uid: str) -> None:
    """Park a topic that had no computer to run on.

    ⛔ FIRST ONE WINS IS *NOT* THE RULE HERE — the newest is. Somebody who asks
    for two things with no computer meant the second one at least as much as the
    first, and silently starting the older one when a computer arrives is the
    surprise. The caller refuses the overwrite where it matters; this is the
    store, not the policy.
    """
    _set_uid_bound(_HELD_RESEARCH, _HELD_RESEARCH_UID, rec, uid)


def clear_held_research() -> None:
    """Started, superseded, expired, or signed out."""
    _clear_uid_bound(_HELD_RESEARCH, _HELD_RESEARCH_UID)


def _log_request_live(rec: Any, now: float) -> bool:
    """A stored support-log record that is well-formed and inside its TTL."""
    if not isinstance(rec, dict) or not rec:
        return False
    try:
        age = now - float(rec.get("at") or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= age <= _LOG_REQUEST_TTL


def put_log_request(code: str, rec: dict[str, Any]) -> None:
    """Remember one support-log request (``rec`` carries its own ``uid``).

    ⛔ BOUNDED, OLDEST OUT FIRST — a diagnostic memory, not a store, exactly as the
    in-memory dict it replaces was. Expired records are swept on the same write.
    """
    if not code or not isinstance(rec, dict) or not rec.get("uid"):
        return
    with _lock:
        prefs = load()
        cur = prefs.get(_LOG_REQUESTS)
        cur = cur if isinstance(cur, dict) else {}
        now = _time.time()
        kept = {c: r for c, r in cur.items() if _log_request_live(r, now) and c != code}
        kept[code] = {**rec, "at": rec.get("at") or now}
        while len(kept) > _LOG_REQUESTS_MAX:
            oldest = min(kept, key=lambda c: float(kept[c].get("at") or 0))
            kept.pop(oldest)
        prefs[_LOG_REQUESTS] = kept
        save(prefs)


def get_log_requests(uid: str) -> dict[str, dict[str, Any]]:
    """Every live support-log request of THIS account, keyed by code.

    ⛔ UID-BOUND PER RECORD, and an empty uid matches nothing — the same hole the
    long note on `get_pending_announce` records."""
    if not uid:
        return {}
    cur = load().get(_LOG_REQUESTS)
    if not isinstance(cur, dict):
        return {}
    now = _time.time()
    return {c: dict(r) for c, r in cur.items()
            if isinstance(c, str) and _log_request_live(r, now) and r.get("uid") == uid}


def get_log_request(code: str, uid: str) -> dict[str, Any] | None:
    """One support-log request, but ONLY if it belongs to ``uid``."""
    return get_log_requests(uid).get(code)


def update_log_request(code: str, uid: str, fields: dict[str, Any]) -> bool:
    """Merge ``fields`` into this account's record for ``code``. Returns whether
    the record existed (a record that expired or belongs to another account is
    left alone)."""
    if not uid or not code:
        return False
    with _lock:
        prefs = load()
        cur = prefs.get(_LOG_REQUESTS)
        rec = cur.get(code) if isinstance(cur, dict) else None
        if not (_log_request_live(rec, _time.time()) and rec.get("uid") == uid):
            return False
        cur[code] = {**rec, **fields}
        prefs[_LOG_REQUESTS] = cur
        save(prefs)
        return True


def get_runtime() -> str | None:
    """The chat runtime the skill was connected into (hermes/openclaw), or None.

    A host setting (not account-scoped): which runtime label to show on the
    sign-in page watermark + default for a remote-login approval page.
    """
    v = load().get(_RUNTIME)
    return v if isinstance(v, str) and v else None


def set_runtime(runtime: str, *, home: str | None = None,
                location: str | None = None) -> None:
    """Record the connected runtime and (optionally) WHERE its skill was
    installed. The home/location let the bridge's revoke-consult and `agent
    disconnect` find the install. Under Model A only a CO-LOCATED install is
    recorded here (a WSL runtime connects in-distro and records its own prefs
    there), so location is always "local". Passing only ``runtime`` keeps the
    back-compat behavior."""
    with _lock:
        prefs = load()
        prefs[_RUNTIME] = runtime
        if home is not None:
            prefs[_RUNTIME_HOME] = home
        if location is not None:
            prefs[_RUNTIME_LOCATION] = location
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
    # Normalize legacy values on read so old prefs.json files behave: native
    # installs were once "windows", and a pre-Model-A WSL install recorded "wsl"
    # — both now render as the co-located host ("local").
    return "local" if v in ("windows", "wsl") else v


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


def set_label_if_unset(label: str) -> bool:
    """Seed the agent's display label ONLY if the user hasn't already chosen one
    (the pref is absent/empty). Returns True if it wrote. Lets `connect` default the
    label to the runtime's own name (e.g. "Rocky") without ever clobbering a label
    the user set — and an FE rename lives on the Firestore doc, which always wins
    regardless (see bridge._write_agent_session_connected)."""
    if not (isinstance(label, str) and label.strip()):
        return False
    with _lock:
        prefs = load()
        cur = prefs.get(_LABEL)
        if isinstance(cur, str) and cur.strip():
            return False
        prefs[_LABEL] = label.strip()
        save(prefs)
        return True
