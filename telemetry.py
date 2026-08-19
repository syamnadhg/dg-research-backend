"""The content-free telemetry tier: what the owner can see without being sent anything.

⛔⛔ WHY THIS EXISTS. On 2026-08-17 a new owner's machine lost DNS for
firestore.googleapis.com. The reconnect ladder retried forever, the aegis pulse
kept saying "standing watch", and the only account of the failure anybody ever
received was a photograph of a terminal. Nothing on that machine could tell us
it was in trouble, because nothing on any machine ever tells us anything.

⭐⭐ AND WHY IT IS SHAPED LIKE THIS. The obvious design is "send a small JSON blob
and scrub the sensitive parts on the way out". A scrubber leaks the first time
somebody adds a line — and somebody always adds a line. So there is no free text
at all: every field is an int, a bool, or an enum. `research_id` is the single
string parameter in the module, and it is regex-guarded to the shape the frontend
actually mints. A research topic is not a scrubbing miss here; it is a TypeError.

⛔ THE ONE CORRECTION THAT MATTERS MOST. The first draft of the id guard was
`^[A-Za-z0-9]{20}$`, which rejects EVERY real id — a guard that fires on every
honest input, i.e. a feature that silently never works. Real ids are minted
`chat_${Date.now()}_${counter}`. `test_a_real_id_is_accepted` is the polarity
that would have caught it, and it is why that test exists alongside the rejections.

⛔ AND THE TRANSPORT. No transport works during the outage it is meant to
report, so the PRIMARY mechanism is a disk spool: append first, deliver later.
The flusher claims a spool file by atomic rename rather than reading and
truncating it — read-POST-truncate loses events appended by a concurrent
`--doctor` during a serve flush, and that collision IS the flagship recovery
flow. Every POST runs on a daemon thread joined against a hard wall-clock
deadline, because `requests`' own timeout does not bound `getaddrinfo`, and
DNS-dead is the incident.
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
import time
import uuid
from enum import Enum, IntEnum
from pathlib import Path

log = logging.getLogger("telemetry")

CATALOGUE_VERSION = 1

# ── The one string shape allowed anywhere in this module ────────────────
# Frontend mints `chat_${Date.now()}_${counter}`: 13 digits of epoch millis and
# a small counter. ⛔ The run_id tail is denied EXPLICITLY as well, because
# `run_id` is `safe_name(topic)_YYYYMMDD_HHMMSS` and a one-word topic survives
# `safe_name` as bare alphanumerics — two independent guards, so a topic cannot
# arrive by looking id-shaped.
RESEARCH_ID_RE = re.compile(r"^chat_[0-9]{13}_[0-9]{1,6}$")
RUN_ID_SUFFIX_RE = re.compile(r"_[0-9]{8}_[0-9]{6}$")


class TelemetryFieldError(TypeError):
    """A field carried something that is not an int, a bool or an enum.

    Deliberately a TypeError: passing a topic into this module is a programming
    error, not a runtime condition to be handled."""


class Ev(IntEnum):
    """Every event this product can report. Numbers are the wire format and are
    append-only — renumbering silently reinterprets every stored batch."""

    # pairing
    # ⛔⛔ FIVE EVENTS WERE DELETED FROM HERE ON 2026-08-18, and the reason is the
    # repo's own rule applied to vocabulary rather than to code. PAIR_INITIATED,
    # PAIR_CLAIMED, PAIR_API_KEY_VERIFIED, PAIR_PLATFORM_VERIFIED and
    # PAIR_PROFILES_CHOSEN each had NO moment in the real flow that could emit
    # them: initiate and code-shown are one instant, claim and exchange are one
    # instant, and the key/platform/profile outcomes are all visible through the
    # stage they belong to. A declared event that nothing emits is worse than an
    # absent one — at read time it is indistinguishable from an event that never
    # happens, so it invites the conclusion "nobody ever completes stage 3".
    # `test_every_event_has_a_call_site` is what found them and what keeps the
    # catalogue honest. The surviving numbers are unchanged, because renumbering
    # silently reinterprets every stored batch.
    PAIR_STARTED = 1
    PAIR_CODE_SHOWN = 3
    PAIR_TOKEN_EXCHANGED = 5
    # Reaching a stage, not the stage's verdict — that verdict is what the stage
    # itself prints, and this tier cannot carry prose.
    PAIR_STAGE_REACHED = 6
    PAIR_COMPLETED = 10
    PAIR_FAILED = 11
    PAIR_CANCELLED = 12
    # serve lifecycle
    SERVE_STARTED = 20
    FIRESTORE_OUTAGE_STARTED = 21
    FIRESTORE_OUTAGE_ENDED = 22
    TOKEN_REFRESH_FAILED = 23
    # runs
    RUN_STARTED = 40
    PHASE_START = 41
    PHASE_COMPLETE = 42
    PHASE_SKIPPED = 43
    AGENT_SKIPPED = 44
    RUN_PAUSED = 45
    RUN_RESUMED = 46
    RUN_STOPPED = 47
    PIPELINE_ERROR = 48
    RUN_FINISHED = 49
    # commands a person ran
    DOCTOR_RUN = 60
    LOGIN_STARTED = 61
    LOGIN_FINISHED = 62
    SEND_LOGS_RESULT = 63
    # the module talking about itself
    TELEMETRY_INVALID = 90
    TELEMETRY_DROPPED = 91


class ErrorClass(IntEnum):
    """What KIND of failure. Derived from exception TYPES only — see
    `classify_exception`."""

    UNKNOWN = 0
    DNS = 1
    CONNECT_REFUSED = 2
    TLS = 3
    TIMEOUT = 4
    HTTP_4XX = 5
    HTTP_5XX = 6
    PERMISSION = 7
    NOT_FOUND = 8
    DISK_FULL = 9
    CANCELLED = 10
    BROWSER_CRASH = 11
    RATE_LIMITED = 12
    AUTH_REVOKED = 13
    CONFIG = 14


class Platform(IntEnum):
    """⛔ Fails CLOSED. `normalize_agent_key` passes through anything it does not
    recognise, so an unmapped agent name must become OTHER rather than reaching
    the wire as itself."""

    OTHER = 0
    CHATGPT = 1
    CLAUDE = 2
    GEMINI = 3
    NOTEBOOKLM = 4
    YOUTUBE = 5
    GOOGLE_DOCS = 6


class VerifyStatus(IntEnum):
    """⛔ CORRECTED. An earlier draft used {COOKIE, DOM, CUA}, which describes
    how a check is PERFORMED and is not what any call site knows. What a call
    site actually knows is whether a key verified, whether the account is on a
    free plan, whether the key is absent, or whether nothing was checked."""

    NO_CHECK = 0
    OK = 1
    FREE = 2
    MISSING = 3


class Provider(IntEnum):
    OTHER = 0
    ANTHROPIC = 1
    GEMINI = 2
    OPENAI = 3


class KeystoreBackend(IntEnum):
    OTHER = 0
    OS_KEYCHAIN = 1
    FILE_FALLBACK = 2


class NetVerdict(IntEnum):
    UNKNOWN = 0
    OK = 1
    DNS_DEAD = 2
    BLOCKED = 3
    PARTIAL = 4


class RunOutcome(IntEnum):
    UNKNOWN = 0
    COMPLETE = 1
    ERRORED = 2
    STOPPED = 3


# ── The field vocabulary ────────────────────────────────────────────────
# The names `tm_emit` accepts, and what each one may carry. ⭐ The catalogue JSON
# shipped in both repos is DERIVED from this, and a test asserts the two agree —
# a fork between the repos makes the newest events 400 and drop silently, and
# absence reads as health.
FIELD_TYPES: "dict[str, type]" = {
    "phase": int,
    "duration_ms": int,
    "count": int,
    "attempt": int,
    "worker": int,
    "stage": int,
    "profiles": int,
    "ok": bool,
    "verified": bool,
    "supervised": bool,
    "platform": Platform,
    "error_class": ErrorClass,
    "verify": VerifyStatus,
    "provider": Provider,
    "keystore": KeystoreBackend,
    "net": NetVerdict,
    "outcome": RunOutcome,
    "research_id": str,
}

# Which fields each event is allowed to carry. An unexpected field is not a
# crash — it becomes TELEMETRY_INVALID naming only the FIELD, never its value.
EVENT_FIELDS: "dict[Ev, tuple[str, ...]]" = {
    Ev.PAIR_STARTED: ("supervised",),
    Ev.PAIR_CODE_SHOWN: (),
    Ev.PAIR_TOKEN_EXCHANGED: ("ok", "error_class"),
    Ev.PAIR_STAGE_REACHED: ("stage",),
    Ev.PAIR_COMPLETED: ("duration_ms", "profiles", "supervised"),
    Ev.PAIR_FAILED: ("stage", "error_class", "net"),
    Ev.PAIR_CANCELLED: ("stage",),
    Ev.SERVE_STARTED: ("worker", "supervised"),
    Ev.FIRESTORE_OUTAGE_STARTED: ("worker", "error_class"),
    Ev.FIRESTORE_OUTAGE_ENDED: ("worker", "duration_ms", "attempt"),
    Ev.TOKEN_REFRESH_FAILED: ("error_class",),
    Ev.RUN_STARTED: ("research_id", "worker"),
    Ev.PHASE_START: ("research_id", "phase", "platform"),
    Ev.PHASE_COMPLETE: ("research_id", "phase", "platform", "duration_ms"),
    Ev.PHASE_SKIPPED: ("research_id", "phase", "platform"),
    Ev.AGENT_SKIPPED: ("research_id", "phase", "platform"),
    Ev.RUN_PAUSED: ("research_id", "phase"),
    Ev.RUN_RESUMED: ("research_id", "phase"),
    Ev.RUN_STOPPED: ("research_id", "phase"),
    Ev.PIPELINE_ERROR: ("research_id", "phase", "platform", "error_class"),
    Ev.RUN_FINISHED: ("research_id", "outcome", "duration_ms"),
    Ev.DOCTOR_RUN: ("count", "net", "supervised"),
    Ev.LOGIN_STARTED: (),
    Ev.LOGIN_FINISHED: ("ok", "error_class", "count"),
    Ev.SEND_LOGS_RESULT: ("ok", "error_class", "count"),
    Ev.TELEMETRY_INVALID: ("count",),
    Ev.TELEMETRY_DROPPED: ("count",),
}


def classify_exception(exc: BaseException) -> ErrorClass:
    """Map an exception to a class, from its TYPE alone.

    ⛔⛔ NEVER `str(exc)`. An exception message carries filesystem paths (and
    therefore the operating-system account name), hostnames, URLs with query
    strings, and on this codebase a Firebase Web API key — measured 5,047 times
    in one log. Types carry none of that.

    Optional dependencies are matched by type NAME rather than imported, which is
    still type-based: `requests` may not be importable in every process this runs
    in, and importing it here to classify an error would be a new failure mode
    inside the error path."""
    if isinstance(exc, socket.gaierror):
        return ErrorClass.DNS
    if isinstance(exc, ConnectionRefusedError):
        return ErrorClass.CONNECT_REFUSED
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return ErrorClass.TIMEOUT
    if isinstance(exc, PermissionError):
        return ErrorClass.PERMISSION
    if isinstance(exc, FileNotFoundError):
        return ErrorClass.NOT_FOUND
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return ErrorClass.DISK_FULL
    name = type(exc).__name__
    if name in ("CancelledError", "KeyboardInterrupt"):
        return ErrorClass.CANCELLED
    if name in ("SSLError", "SSLCertVerificationError", "CertificateError"):
        return ErrorClass.TLS
    if name in ("ConnectTimeout", "ReadTimeout", "Timeout"):
        return ErrorClass.TIMEOUT
    if name in ("ConnectionError", "NewConnectionError", "ProtocolError"):
        return ErrorClass.CONNECT_REFUSED
    if name in ("TargetClosedError", "BrowserClosedError"):
        return ErrorClass.BROWSER_CRASH
    if name in ("PermissionDenied", "Unauthenticated"):
        return ErrorClass.PERMISSION
    if name in ("ResourceExhausted", "TooManyRequests"):
        return ErrorClass.RATE_LIMITED
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        if 400 <= status < 500:
            return ErrorClass.HTTP_4XX
        if 500 <= status < 600:
            return ErrorClass.HTTP_5XX
    return ErrorClass.UNKNOWN


def _valid_research_id(value: object) -> bool:
    text = str(value)
    return bool(RESEARCH_ID_RE.match(text)) and not RUN_ID_SUFFIX_RE.search(text)


def coerce_field(name: str, value: object) -> "int | bool | str | None":
    """One field, on its way to the wire, or an exception.

    ⭐ THE STRUCTURAL PROPERTY IS THE ORDER. A `str` reaches the id branch ONLY
    when the field is literally named `research_id`. So monkeypatching the id
    regex to match anything still cannot get a string into `phase` — the
    no-free-text guarantee does not rest on a validator being correct."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return int(value.value)
    if isinstance(value, int):
        return int(value)
    if name == "research_id" and isinstance(value, str):
        if _valid_research_id(value):
            return value
        raise TelemetryFieldError(name)
    raise TelemetryFieldError(name)


# ── Where events wait ───────────────────────────────────────────────────
def _telemetry_dir() -> Path:
    """Where events wait.

    ⛔⛔ THE ENV OVERRIDE IS ISOLATION, NOT CONFIGURATION. Measured 2026-08-18 on
    the developer's own machine: the suite had written 8,025 test events into the
    REAL `~/.super-research/telemetry/`, and three were sitting in the pending
    spool waiting to be POSTed to PRODUCTION the next time a human ran any
    command — a fake install id and a synthetic research id, indistinguishable at
    the sink from a real machine reporting real activity.

    The suite's isolation fixture redirects the backend's state dir; this module
    imports nothing from the backend (on purpose — a telemetry failure must never
    sit in the path of the thing it measures), so that fixture could not see it.
    A monkeypatch would not have been enough either: several tests spawn a real
    second interpreter, and a patched function does not cross a process boundary.
    An env var does."""
    override = os.environ.get("SR_TELEMETRY_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".super-research" / "telemetry"


def spool_path(worker: "int | None" = None) -> Path:
    """One spool file per PROCESS, never a shared one.

    ⛔ A shared file plus read-POST-truncate loses whatever a concurrent process
    appended mid-flush, and "a --doctor running while serve flushes" is exactly
    the recovery flow this exists for. Per-process files plus the rename claim
    below make that collision unrepresentable."""
    if worker is None:
        return _telemetry_dir() / "pending-cli.jsonl"
    return _telemetry_dir() / f"pending-w{int(worker)}.jsonl"


def sent_log_path() -> Path:
    return _telemetry_dir() / "sent.log"


SPOOL_MAX_LINES = 2000
EVENT_MAX_AGE_SEC = 30 * 86400
FLUSH_DEADLINE_SEC = 5.0
BATCH_MAX_EVENTS = 500

_SESSION_ID = uuid.uuid4().hex[:16]
_seq_lock = threading.Lock()
_seq = 0
_dropped = 0


def session_id() -> str:
    return _SESSION_ID


def _next_seq() -> int:
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def _install_uuid() -> str:
    """The stable per-install id. ⭐ Written before any pairing and SURVIVING
    pairing, which is the only reason an event emitted while pairing was broken
    can be attributed to an account once pairing works."""
    try:
        from auth.keystore import install_uuid
        return str(install_uuid())
    except Exception:
        return ""


def _build() -> str:
    try:
        from importlib.metadata import version
        return str(version("superresearch"))
    except Exception:
        return ""


def enabled() -> bool:
    """The kill switch. Env var only, deliberately not surfaced in the app: a
    control in the UI implies a per-account setting, and this tier carries no
    account content to gate."""
    return os.environ.get("SR_TELEMETRY", "1").strip().lower() not in (
        "0", "off", "false", "no")


def tm_emit(event: Ev, *,
            phase: "int | None" = None,
            duration_ms: "int | None" = None,
            count: "int | None" = None,
            attempt: "int | None" = None,
            worker: "int | None" = None,
            stage: "int | None" = None,
            profiles: "int | None" = None,
            ok: "bool | None" = None,
            verified: "bool | None" = None,
            supervised: "bool | None" = None,
            platform: "Platform | None" = None,
            error_class: "ErrorClass | None" = None,
            verify: "VerifyStatus | None" = None,
            provider: "Provider | None" = None,
            keystore: "KeystoreBackend | None" = None,
            net: "NetVerdict | None" = None,
            outcome: "RunOutcome | None" = None,
            research_id: "str | None" = None) -> bool:
    """Record ONE event. Returns whether it reached the spool.

    ⛔ NO `**kwargs`, and every parameter is named and typed. That is the whole
    privacy mechanism, and `test_the_signature_admits_no_free_text` asserts it by
    reading this signature rather than by reading the body — a body can be
    audited once; a signature is checked on every commit."""
    if not enabled():
        return False
    supplied = {
        "phase": phase, "duration_ms": duration_ms, "count": count,
        "attempt": attempt, "worker": worker, "stage": stage,
        "profiles": profiles, "ok": ok, "verified": verified,
        "supervised": supervised, "platform": platform,
        "error_class": error_class, "verify": verify, "provider": provider,
        "keystore": keystore, "net": net, "outcome": outcome,
        "research_id": research_id,
    }
    try:
        ev = Ev(event)
    except Exception:
        return _spool({"ev": int(Ev.TELEMETRY_INVALID), "d": {"count": 1}})

    allowed = EVENT_FIELDS.get(ev, ())
    data: "dict[str, int | bool | str]" = {}
    for name, value in supplied.items():
        if value is None:
            continue
        if name not in allowed:
            # ⛔ Names the FIELD, never the value. An "unexpected field" report
            # that quoted the value would be the leak it is reporting.
            log.debug("telemetry: %s does not carry %s", ev.name, name)
            _spool({"ev": int(Ev.TELEMETRY_INVALID), "d": {"count": 1}})
            continue
        try:
            coerced = coerce_field(name, value)
        except TelemetryFieldError:
            log.warning("telemetry: %s rejected field %s (wrong type)", ev.name, name)
            _spool({"ev": int(Ev.TELEMETRY_INVALID), "d": {"count": 1}})
            continue
        if coerced is not None:
            data[name] = coerced
    return _spool({"ev": int(ev), "d": data})


def _envelope(body: dict) -> dict:
    return {
        "v": CATALOGUE_VERSION,
        "iuid": _install_uuid(),
        "sid": _SESSION_ID,
        "seq": _next_seq(),
        "t": int(time.time() * 1000),
        "b": _build(),
        "os": os.name if os.name != "posix" else __import__("sys").platform,
        **body,
    }


def _spool(body: dict, worker: "int | None" = None) -> bool:
    """Append one event. Never raises, never blocks on the network."""
    global _dropped
    record = _envelope(body)
    try:
        path = spool_path(worker if worker is not None else _worker_id())
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        _mirror(record)
        _trim_spool(path)
        return True
    except Exception as exc:
        log.debug("telemetry: spool write failed (%s)", type(exc).__name__)
        return False


def _worker_id() -> "int | None":
    """Which spool file this process owns. Read from the env rather than
    imported, so this module never imports research.py."""
    raw = os.environ.get("SR_WORKER_ID", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _mirror(record: dict) -> None:
    """A local copy of everything that will be sent.

    ⭐ The transparency claim — "you can see exactly what leaves" — has to hold
    for `--pair` too, and under `--pair` the process's own logger reaches no
    file at all. So the mirror is a FILE, not a log line."""
    try:
        path = sent_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _trim_spool(path: Path) -> None:
    """Bound one spool file: drop the OLDEST half and say so.

    ⭐ Oldest-half rather than newest, because the newest events are the ones
    describing whatever is going wrong right now."""
    global _dropped
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= SPOOL_MAX_LINES:
        return
    keep = lines[len(lines) // 2:]
    dropped = len(lines) - len(keep)
    _dropped += dropped
    keep.append(json.dumps(
        _envelope({"ev": int(Ev.TELEMETRY_DROPPED), "d": {"count": dropped}}),
        separators=(",", ":")))
    try:
        path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except OSError:
        pass


# ── Delivery ────────────────────────────────────────────────────────────
def _pid_alive(pid: int) -> bool:
    """Local, because this module never imports research.py."""
    try:
        if os.name == "nt":
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x00100000, 0, int(pid))
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _claimed_pid(path: Path) -> "int | None":
    """The pid out of `pending-x.sending.<pid>.jsonl`, or None."""
    match = re.search(r"\.sending\.(\d+)\.jsonl$", path.name)
    return int(match.group(1)) if match else None


def _adoptable(path: Path) -> bool:
    """Is this claimed file abandoned rather than in flight?

    ⛔ Found by mutation. Two processes flushing at once: A claims a file, and
    B's glob sees the claimed name and posts it too. Not data loss — the sink
    collapses byte-identical resends — but it doubles the traffic of the quietest
    thing in the product, for no reason. A file is adopted only once its owner is
    gone."""
    pid = _claimed_pid(path)
    if pid is None:
        return False
    if pid == os.getpid():
        return True
    return not _pid_alive(pid)


def _claim(path: Path) -> "Path | None":
    """Take ownership of a spool file by ATOMIC RENAME.

    ⛔⛔ NOT read-then-truncate. Between the read and the truncate, another
    process appends — and the append that gets destroyed belongs to whichever
    command the user ran to recover. `os.rename` is atomic on POSIX and Windows
    within a directory, so after this call the claimed file is ours alone and new
    appends land in a fresh `pending-*.jsonl`."""
    claimed = path.with_name(f"{path.stem}.sending.{os.getpid()}{path.suffix}")
    try:
        os.replace(str(path), str(claimed))
        return claimed
    except OSError:
        return None


def _read_batch(claimed: Path,
                now: "float | None" = None) -> "tuple[list[dict], list[str]]":
    """(events to send now, lines still owed) from a claimed file.

    ⛔⛔ THE LEFTOVER IS RETURNED, not discarded. Found by mutation: capping the
    batch at 500 while the caller deletes the whole claimed file loses every
    event past the cap — and an offline machine's spool is exactly where a batch
    hits that cap. Age-expired lines are dropped from BOTH halves; they are the
    one thing this is allowed to throw away."""
    cutoff = (time.time() if now is None else float(now)) - EVENT_MAX_AGE_SEC
    fresh: "list[tuple[dict, str]]" = []
    try:
        for line in claimed.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            if float(record.get("t", 0)) / 1000.0 < cutoff:
                continue
            fresh.append((record, line))
    except OSError:
        return [], []
    batch = [r for r, _l in fresh[:BATCH_MAX_EVENTS]]
    owed = [l for _r, l in fresh[BATCH_MAX_EVENTS:]]
    return batch, owed


def _unclaimed_name(path: Path) -> Path:
    """`pending-cli.sending.8538.jsonl` -> `pending-cli.jsonl`.

    A stranded file is adopted UNDER ITS OWN NAME — nothing renames it, because
    it is already claimed. So the place its events belong on a failed delivery is
    the live spool, not the name they are sitting in."""
    return path.with_name(re.sub(r"\.sending\.\d+(?=\.jsonl$)", "", path.name))


def _merge_back(claimed: Path, path: Path) -> None:
    """Delivery failed: put the claimed events back in front of anything that
    arrived while we were trying."""
    # ⛔⛔ MEASURED 2026-08-18, nine real events destroyed in one call. The caller
    # passed `path if ".sending." not in path.name else path` — both arms of that
    # ternary are `path`, so for an ADOPTED file, where `claimed` and `path` are
    # the same file, this read the events, wrote them back into themselves, and
    # then unlinked the file it had just written. Every stranded batch was
    # destroyed by its first failed delivery.
    #
    # ⭐⭐ And it destroyed exactly the events worth having: a stranded file
    # belongs to a process that DIED, and the trigger is delivery failing — which
    # is the outage this system exists to report. The one guard that has to hold
    # here is that a file is never merged into itself.
    if claimed.resolve() == path.resolve():
        return
    try:
        owed = claimed.read_text(encoding="utf-8")
    except OSError:
        return
    try:
        newer = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        newer = ""
    try:
        path.write_text(owed + newer, encoding="utf-8")
        claimed.unlink()
    except OSError:
        pass


def _write_back(lines: "list[str]", path: Path) -> None:
    """Put owed lines back in front of anything newer that has arrived."""
    try:
        newer = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        newer = ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n" + newer, encoding="utf-8")
    except OSError:
        pass


def flush(post=None, deadline_sec: float = FLUSH_DEADLINE_SEC,
          now: "float | None" = None) -> int:
    """Deliver every claimable spool file. Returns how many events landed.

    `post(batch) -> bool` is injectable so the whole path can be exercised
    against a fake sink; the default posts to our own host.

    ⛔ THE DEADLINE IS WALL-CLOCK, ON A DAEMON THREAD. `requests`' timeout does
    not bound `getaddrinfo`, and a machine with dead DNS can sit inside a name
    lookup far longer than any command should wait. So the POST runs on a thread
    this function JOINS with a timeout — if it is still going, we abandon it and
    the events stay owed. A telemetry flush must never be the reason a command
    feels broken."""
    if not enabled():
        return 0
    sender = post or _post_batch
    landed = 0
    directory = _telemetry_dir()
    try:
        everything = sorted(directory.glob("pending-*.jsonl"))
    except OSError:
        return 0
    unclaimed = [p for p in everything if ".sending." not in p.name]
    # Resume anything a process claimed and died holding — and ONLY that; a file
    # a LIVE sibling is mid-POST on is left alone.
    stranded = [p for p in everything if ".sending." in p.name and _adoptable(p)]
    candidates = unclaimed + stranded

    for path in candidates:
        claimed = path if ".sending." in path.name else _claim(path)
        if claimed is None:
            continue
        batch, owed = _read_batch(claimed, now=now)
        if not batch:
            try:
                claimed.unlink()
            except OSError:
                pass
            continue
        ok = _post_with_deadline(sender, batch, deadline_sec)
        if ok:
            # Anything past the batch cap goes back in front of whatever arrived
            # while we were delivering, rather than dying with the claimed file.
            if owed:
                _write_back(owed, path)
            # ⛔ A crash between the 2xx and this unlink re-sends the batch. The
            # route's document id is a hash of the events, so a byte-identical
            # resend collapses onto the same document — at-least-once delivery
            # with an idempotent sink, which is the honest guarantee.
            try:
                claimed.unlink()
            except OSError:
                pass
            landed += len(batch)
        else:
            _merge_back(claimed, _unclaimed_name(path))
    return landed


def _post_with_deadline(sender, batch: "list[dict]", deadline_sec: float) -> bool:
    result: "list[bool]" = []

    def _run() -> None:
        try:
            result.append(bool(sender(batch)))
        except BaseException as exc:
            # ⭐ BaseException, not Exception. A Ctrl+C landing while a flush is
            # in flight would otherwise escape this daemon thread and print a
            # traceback from telemetry during the user's own clean exit — noise
            # from the quietest thing in the process. Recording the failure is
            # enough: the events stay owed and go out next time.
            log.debug("telemetry: post failed (%s)", type(exc).__name__)
            result.append(False)

    thread = threading.Thread(target=_run, name="telemetry-post", daemon=True)
    thread.start()
    thread.join(max(0.1, float(deadline_sec)))
    if thread.is_alive():
        log.debug("telemetry: post abandoned at the %.1fs deadline", deadline_sec)
        return False
    return bool(result and result[0])


def _post_batch(batch: "list[dict]") -> bool:
    import requests
    try:
        from auth.v2_flow import FE_BASE_URL as base
    except Exception:
        base = "https://superresearch.io"
    url = f"{str(base).rstrip('/')}/api/telemetry"
    headers = {"Content-Type": "application/json"}
    token = _id_token()
    if token:
        headers["Authorization"] = f"Firebase {token}"
    resp = requests.post(url, headers=headers,
                         data=json.dumps({"v": CATALOGUE_VERSION, "events": batch}),
                         timeout=20)
    return 200 <= resp.status_code < 300


def _id_token() -> "str | None":
    """An ID token if one happens to be available. ⭐ Optional by design: the
    events worth having most exist precisely when no credential does."""
    try:
        from auth.credentials import current_id_token
        return current_id_token()
    except Exception:
        return None


def flush_in_background(post=None, deadline_sec: float = FLUSH_DEADLINE_SEC):
    """Start a flush that cannot hold up whatever the user actually ran."""
    thread = threading.Thread(
        target=lambda: flush(post=post, deadline_sec=deadline_sec),
        name="telemetry-flush", daemon=True)
    thread.start()
    return thread


def catalogue() -> dict:
    """The wire vocabulary, as data. Written to a JSON file in BOTH repos, and a
    test on each side asserts the file matches its own source of truth — a fork
    makes the newest events 400 and drop silently, and absence reads as health."""
    return {
        "version": CATALOGUE_VERSION,
        "events": {e.name: int(e.value) for e in Ev},
        "fields": {name: (t.__name__ if t in (int, bool, str) else t.__name__)
                   for name, t in FIELD_TYPES.items()},
        "eventFields": {e.name: list(EVENT_FIELDS.get(e, ()))
                        for e in Ev},
        "enums": {
            cls.__name__: {m.name: int(m.value) for m in cls}
            for cls in (ErrorClass, Platform, VerifyStatus, Provider,
                        KeystoreBackend, NetVerdict, RunOutcome)
        },
    }
