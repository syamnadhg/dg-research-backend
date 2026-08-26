"""The Super Agent host bridge — a loopback HTTP server.

It is the always-up local process that OWNS the account session: it is the ONLY
process that ever refreshes the token or touches Firestore, so the single-owner
invariant holds and an out-of-band CLI refresh can never strand it. The host
CLI and the chat skill both call it over HTTP — they never refresh themselves.

  * serves the Google sign-in page and captures the account session (`/login`),
  * holds the live ``AccountSession`` in memory and refreshes it,
  * exposes the account operations: /status /researches /devices /research.

Bound to 127.0.0.1 only; every request is Host- and (for writes) Origin-checked.

TRUST MODEL — stated rather than implied, because the implication is easy to
read the wrong way. The complete write-authorization model is:

    loopback bind  +  Host allow-list (``_host_ok``)  +  Origin check (``_origin_ok``)

There is NO per-caller authentication on any route. Every process running as
any user on this host can therefore POST to all of them, including the
privileged ones — ``/device/remove``, ``/shutdown``, ``/install-backend`` and
``/agent-install`` (which reaches ``selfupdate``'s install-and-exec path). That
is a deliberate choice for the single-user Research computer this runs on: the
two callers are the host CLI and the chat skill, and requiring a key exchange
would mean a bare ``superresearch-agent status`` could not work.

Two things this model is NOT, so nobody over-trusts it:

  * ``secrets.compare_digest`` on ``loginToken`` (``_login_callback``) is not a
    caller credential. It is a one-shot CSRF nonce for the browser sign-in page,
    and ``GET /login/config`` hands it to any local caller that asks. It stops a
    cross-origin page replaying a capture; it authenticates nobody.
  * Loopback is not a user boundary. On a shared or multi-user host every local
    account reaches this port, so the assumption above stops holding — gating the
    privileged routes behind a 0600 token file is tracked in DGOPS-9504.

``_origin_ok`` returning True for an ABSENT Origin is intentional and required:
non-browser callers (the CLI) send no Origin header, while any browser write
carries one and is checked against the actual bound port.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from . import __version__, config, devicelogin, prefs, runview, selfupdate
from .devicelogin import DeviceLoginError
from .firestore_rest import FirestoreError, FirestoreRest
from .session import AccountSession, CustomTokenError, RevokedError

log = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent / "web"

_ICON_FILES = frozenset({"chatgpt.png", "claude.png", "notebooklm.png"})

_DEFAULT_AGENTS = ["chatgpt", "gemini", "claude"]

# Upper bound on how long the bridge will keep a remote-login flow alive, no
# matter what TTL the broker reports (defense against an unbounded expiresIn).
_REMOTE_MAX_TTL_SECONDS = 900

# A run id must be a single Firestore document-id segment. Validated at the URL
# boundary so a crafted rid (../, %2f, embedded /) can never be interpolated into
# a Firestore path and steer a request out of the caller's own tree. Admits our
# agent-<hex> ids and Firestore push ids ([A-Za-z0-9_-]).
_RID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# These JSON bodies are tiny (topic / deviceId / a token). Cap how much we'll
# buffer so a lying/oversized Content-Length can't pin a worker thread reading
# into memory before the Host/Origin checks even run.
_MAX_BODY_BYTES = 1 << 20  # 1 MiB

# ── send logs ────────────────────────────────────────────────────────────────
# A support code is a path segment AND a capability: it names the object under
# `logs/{uid}/{deviceId}/{code}/` that the storage rule pins to one owner and
# one device. The alphabet drops I, L, O and U so a person reading one off a
# screen to somebody on a call cannot turn it into a different code.
_SUPPORT_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_SUPPORT_CODE_LENGTH = 8
_SUPPORT_CODE_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{8}$")

# ⛔⛔ THE ONLY DEVICE COMMAND THIS BRIDGE MAY EVER WRITE FOR LOGS, and the
# reason is the whole shape of this feature on a fleet box.
#
# `send-logs` means "this machine's own cap" and `send-logs-limited` means "the
# newest N". Neither is scoped to a PERSON, so either one asks for a
# whole-machine bundle — every run the computer has ever done, for everyone who
# uses it. The Firestore rule keeps both owner-only for exactly that reason, and
# opens only this third name to a sharer.
#
# A fleet box is the case that makes this concrete rather than theoretical: one
# research computer can be shared by many people (DG_SUPER_RESEARCH_DEFAULT_
# DEVICE_CODE), so the agent's user is USUALLY a sharer and never assumed to be
# the owner. Naming the action here — a constant, not a parameter — means no
# future caller in this file can pick a different one by passing a flag.
_SEND_LOGS_ACTION = "send-logs-selected"

# The machine publishes at most this many runs per person; a selection larger
# than the list it published cannot be honest, and the machine refuses one
# outright. Bounded here so a malformed request never reaches the wire.
_SEND_LOGS_MAX_NAMES = 60
_RUN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,95}$")


def _mint_support_code() -> str:
    """A fresh support code from the OS CSPRNG.

    ⭐ Minted HERE rather than by the machine, for the same reason the web app
    mints it in the browser: the code names the document the caller then
    watches, so it has to exist before the request is sent. A collision can
    only ever affect this user's own bundles — the path it names is already
    scoped to this uid and this device.
    """
    return "".join(secrets.choice(_SUPPORT_CODE_ALPHABET)
                   for _ in range(_SUPPORT_CODE_LENGTH))

# Podcast audio (the chat /sr-podcast → a native audio FILE the runtime attaches).
# The audio is downloaded host-side to ~/.super-agent/podcasts and only the LOCAL
# PATH is handed back — the long-lived Storage download token never leaves the
# host (it is not in the response, so it can't land in chat history).
_PODCAST_DIR_NAME = "podcasts"
_PODCAST_MAX_BYTES = 200 * 1024 * 1024  # 200 MiB — generous for a long audio overview
_PODCAST_MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # prune cached audio older than a week
# A chat platform rejects an upload past its own ceiling (Telegram's bot API caps a
# single file at 50 MB). When that happens the runtime does NOT surface an error —
# it quietly falls back to printing the file PATH as text, so the user is handed a
# dead path instead of audio (live 2026-07-26: an 89 MB, 48-minute overview; the
# same failure sat in the logs on 07-22 and 07-24). Stay under the smallest common
# ceiling with room for multipart overhead, and shrink anything above it.
_DELIVERY_MAX_BYTES = 45 * 1024 * 1024
# Per-channel upload ceilings — the limit belongs to the PLATFORM, not to us, and
# they differ by an order of magnitude. Using one global number means a file that is
# fine on Telegram is silently refused on WhatsApp (and the runtime then degrades to
# printing the path). Values sit under each platform's documented cap with room for
# the multipart envelope. 0 = never attach: an MMS carrier cannot carry an overview
# at any bitrate, so those always get the permanent link instead.
_DELIVERY_LIMITS = {
    "telegram": 45 * 1024 * 1024,   # bot API: 50 MB per upload
    "whatsapp": 14 * 1024 * 1024,   # ~16 MB media cap
    "imessage": 45 * 1024 * 1024,   # relays vary; stay at the conservative end
    "discord": 7 * 1024 * 1024,     # 8 MB on an unboosted server
    "sms": 0,
    "twilio": 0,
}
# Re-encode targets for an oversized overview. The source is a two-voice CONVERSATION
# carried at music-grade settings, so mono speech bitrates are transparent here. The
# rate is derived from the channel's ceiling and the actual duration (below); these
# just bound it — 64k is indistinguishable for speech, and below 32k a two-voice mix
# starts to smear, so anything that would need less than the floor gets the link.
_SHRINK_MAX_KBPS = 64
_SHRINK_MIN_KBPS = 32
_SHRINK_HEADROOM = 0.90  # container overhead + the platform's multipart envelope
_SHRINK_SUFFIX = "-small.mp3"
# ffmpeg/ffprobe are NOT hard dependencies of the agent (the podcast normally arrives
# already encoded). Probe the usual install roots too: a launchd/systemd child can
# inherit a minimal PATH that omits /usr/local/bin and Homebrew's prefix.
_FFMPEG_FALLBACK_DIRS = ("/usr/local/bin", "/opt/homebrew/bin", "/usr/bin")
_AUDIO_EXT_MIME = {
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
}
# Strip only filesystem-hostile chars (Windows-reserved + control); keep unicode
# letters/digits so a non-Latin run title still yields a meaningful filename.
_FILENAME_BAD_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
# The fetch target is read from the (account-scoped) research doc, so this is at
# most self-SSRF — but we still gate the host-side download to the expected
# Firebase/GCS Storage hosts (and refuse redirects) as defense-in-depth.
_ALLOWED_AUDIO_HOSTS = frozenset({"firebasestorage.googleapis.com", "storage.googleapis.com"})
_ALLOWED_AUDIO_HOST_SUFFIXES = (".storage.googleapis.com",)


# The chat a run was fired from — {platform, chat_id[, thread_id]} — captured by
# sr.py from the gateway's per-session env and tagged onto the run doc. It scopes
# the streaming watchdog so a run started in one chat only streams back to THAT
# chat (Telegram→Telegram, WhatsApp→WhatsApp), never leaking across chats.
_ORIGIN_MAX = 128


def _mask_email(who: str) -> str:
    """Mask an email for LOGS — keep the first char + domain (``a***@gmail.com``) so
    a line still identifies the account at a glance without writing the full address
    to disk. A bare uid (no ``@``) passes through unchanged — a Firebase uid isn't
    PII. LOGS ONLY; the loopback JSON responses still carry the real email (the
    client needs it to show "signed in as …")."""
    who = who or ""
    if "@" not in who:
        return who
    local, _, domain = who.partition("@")
    return f"{local[:1]}***@{domain}" if local else f"***@{domain}"


def _clean_origin(raw: Any) -> dict[str, str] | None:
    """Normalize a chat origin to short trimmed strings, or None unless BOTH
    platform and chat_id are present (the minimum to scope updates to one chat).
    thread_id is kept for fidelity but not required and not used for scoping."""
    if not isinstance(raw, dict):
        return None

    def _s(key: str) -> str:
        v = raw.get(key)
        return str(v).strip()[:_ORIGIN_MAX] if v not in (None, "") else ""

    platform, chat_id = _s("platform"), _s("chat_id")
    if not platform or not chat_id:
        return None
    out: dict[str, str] = {"platform": platform, "chat_id": chat_id}
    thread = _s("thread_id")
    if thread:
        out["thread_id"] = thread
    return out


def _same_origin(a: Any, b: Any) -> bool:
    """Whether two chat origins address the same conversation.

    Compares on the SAME two fields delivery scopes on — platform (case-folded)
    and chat_id — so "is this the chat that asked?" gets one answer everywhere.
    thread_id is deliberately not compared: a reply in a thread is still the same
    chat, and `/updates` scoping ignores it too."""
    ca, cb = _clean_origin(a), _clean_origin(b)
    if ca is None or cb is None:
        return False
    return (ca["platform"].lower() == cb["platform"].lower()
            and ca["chat_id"] == cb["chat_id"])


def _config_from_settings(pipe: dict[str, Any] | None) -> dict[str, Any]:
    """Map the account's saved pipeline Settings into the run-config the backend
    pipeline reads, so an agent-fired run honors the same defaults the web app
    applies. ``pipe`` is the ``pipeline`` map of ``users/{uid}/settings/prefs``.

    Mirrors the web app's Settings→config derivation (ChatInput.tsx): which
    agents run, which phases are skipped (brief; podcast+video when NotebookLM is
    off), whether video/email run, the podcast length, and skipInitVerify (from
    the opt-in ``verifyLogins`` toggle — verification is OFF by default since
    2026-07-02). Field defaults match the app's DEFAULT_SETTINGS, so an absent
    field behaves exactly as it does in the app (a settings-less account →
    skip verification + all agents)."""
    p = pipe if isinstance(pipe, dict) else {}
    agents = {
        "chatgpt": bool(p.get("agentChatGPT", True)),
        "gemini": bool(p.get("agentGemini", True)),
        "claude": bool(p.get("agentClaude", True)),
    }
    generate_podcast = bool(p.get("generatePodcast", True))
    skip_phases: set[int] = set()
    if p.get("skipBrief"):
        skip_phases.add(1)
    if not generate_podcast:            # NotebookLM off → podcast (3) + video (4) both skipped
        skip_phases.update((3, 4))
    if not any(agents.values()):        # all agents off → skip the whole research phase
        skip_phases.add(2)
    # Video runs unless the podcast is off OR the user set the video link to "off".
    video_enabled = generate_podcast and p.get("videoLink", "youtube") != "off"
    return {
        "skipPhases": sorted(skip_phases),
        "agents": agents,
        "videoEnabled": bool(video_enabled),
        "emailEnabled": bool(p.get("sendEmail", True)),
        "podcastLength": p.get("podcastLength") or "long",
        # 2026-07-02: verification is OPT-IN. The Settings field is now
        # `verifyLogins` (renamed+inverted from skipInitVerify so stale
        # auto-saved falses stop applying); the BE payload keeps the legacy
        # skipInitVerify key. Absent/off → skip verification.
        "skipInitVerify": not bool(p.get("verifyLogins", False)),
    }


def _new_research_fields(
    topic: str, device_id: str, uid: str, cfg: dict[str, Any] | None,
    chat_origin: dict[str, str] | None = None,
    display_name: str = "",
) -> dict[str, Any]:
    """The research (chat) doc a fresh agent run creates.

    Mirrors the web app's fresh-chat shape (research-app/web saveResearch /
    usePipeline) so it renders as a normal chat immediately — the platform
    list, empty doc/audio arrays — rather than a sparse placeholder. The BE
    backfills the rest as the pipeline runs.

    NO ``phase`` field on purpose (#890): the web app strips it before every
    write (saveResearch — "phase is BE-owned"), and the FE's list-page
    hydration reads it into the pipeline's currentPhase. A bridge-stamped
    ``phase: 0`` on a still-QUEUED run made the chat flip to "run started"
    (Stop/Pause controls up) before the run ever left the queue. The BE
    stamps phase itself the moment the run really starts.
    """
    now_ms = int(time.time() * 1000)
    agents = cfg.get("agents") if isinstance(cfg, dict) else None
    if isinstance(agents, dict):
        platforms = [a for a in _DEFAULT_AGENTS if agents.get(a, True)]
    else:
        platforms = list(_DEFAULT_AGENTS)
    fields: dict[str, Any] = {
        "topic": topic,
        "title": topic,
        "summary": "",
        "status": "queued",
        "deviceId": device_id,
        "submittedBy": uid,
        "submittedByDisplayName": display_name,
        "viaAgent": True,
        "platforms": platforms,
        "documents": [],
        "audios": [],
        "createdAt": now_ms,
        "updatedAt": now_ms,
    }
    if cfg:
        fields["pipelineConfig"] = cfg
    if chat_origin:
        fields["chatOrigin"] = chat_origin
    return fields


class _EnqueueFailed(Exception):
    """``enqueue_start`` failed AFTER the research doc was created (the orphan doc
    has been best-effort deleted). Carries the original error so an HTTP caller can
    map it to the right response."""

    def __init__(self, original: Exception):
        super().__init__(str(original))
        self.original = original
        self.revoked = isinstance(original, RevokedError)


class _NoResearchNode(Exception):
    """The account has no research node — a run has nowhere to go (→ pair-a-node)."""


def _device_label(d: dict[str, Any]) -> str:
    """Friendly device name (mirrors sr.py `_dev_label`): name → hostname → id."""
    return d.get("name") or d.get("hostname") or d.get("id") or "your Research Computer"


# A device is "online right now" if its last heartbeat is within this window.
# Mirrors the web app's single source of truth (firestore.ts
# DEVICE_OFFLINE_THRESHOLD_MS = 30_000; the BE heartbeats every ~5s, so 30s =
# 6× cadence — absorbs jitter, still flags a genuine kill within one window).
_DEVICE_ONLINE_MS = 30_000


def _device_is_online(d: dict[str, Any]) -> bool:
    """Whether a pair-confirmed device is heartbeating RIGHT NOW (recent
    lastHeartbeat), not merely paired-but-powered-off. `lastHeartbeat` is epoch
    millis written by the BE heartbeat loop. Missing/zero/non-numeric → offline."""
    hb = d.get("lastHeartbeat")
    if not isinstance(hb, (int, float)) or isinstance(hb, bool) or hb <= 0:
        return False
    return (time.time() * 1000 - hb) < _DEVICE_ONLINE_MS


def _device_descriptor(d: dict[str, Any]) -> dict[str, Any]:
    """A minimal, chat-safe device descriptor for a 'pick one' error body — id +
    friendly name + online flag (never tokens/heartbeat internals)."""
    return {"id": d.get("id"), "name": _device_label(d), "online": _device_is_online(d)}


def _resolve_run_config(fs: FirestoreRest, sess: AccountSession,
                        chat_cfg: dict[str, Any] | None) -> dict[str, Any]:
    """The run-config for an agent-fired run: the account's saved pipeline Settings
    (resolved HERE because sr.py can't read Firestore), overlaid by any explicit
    chat flags. An advisory settings read — never blocks the run."""
    pipe: dict[str, Any] = {}
    try:
        _settings = fs.get_user_settings(sess.uid)
        if isinstance(_settings, dict) and isinstance(_settings.get("pipeline"), dict):
            pipe = _settings["pipeline"]
    except Exception as e:  # advisory — never block a run on it
        # Log the type only (not the value) — this file's convention, so an
        # upstream body never lands in logs.
        log.warning("agent run: couldn't read account settings (%s) — using defaults",
                    type(e).__name__)
    return {**_config_from_settings(pipe), **(chat_cfg or {})}


def _notify_device_owner_of_run(sess: "AccountSession", device_id: str,
                                research_id: str, topic: str) -> None:
    """Tell the machine's OWNER that a sharer just started a run on it.

    ⛔⛔ THE GAP THIS CLOSES. The notice exists and is correct — the web app
    composes every word of it and re-checks membership itself — and until now its
    only caller was the sharer's BROWSER, at submit time. So a sharer starting a
    run from chat, from a terminal, or from a fleet box notified nobody, and a
    fleet box is exactly where a co-tenant is most likely to be a sharer. The
    backend does not send it either: there is no second dispatcher to fall back
    on, unlike phase notices.

    ⭐⭐ AND THE REASON THE AGENT CAN SEND IT IS THE PERSON'S IDENTITY. This
    process is signed in as the ACTUAL HUMAN, so the route sees a genuine caller,
    re-reads ``devices/{id}`` for itself, and can name them without trusting
    anything a machine supplied. The machine-side alternative covers strictly
    more paths and was rejected for that reason: a machine has no name or email
    of its own, so the notice would read "Someone started a research" unless the
    route began trusting an identity a machine handed it, on the one path that
    writes into somebody ELSE's inbox.

    ⛔⛔ NO OWNERSHIP CHECK HERE, AND THE PLAN ASKED FOR ONE. It said "the agent
    already knows: ``owned`` comes back on the device row it just read. Skip the
    call when the person owns the machine." That premise is measured FALSE.
    ``_enqueue_research_run`` receives ``device_id: str`` and nothing else;
    ``_resolve_device`` returns the explicit id before reading anything and
    discards every row on the branch that does list them, and ``owned`` is not a
    Firestore field at all — ``_decorate_devices`` grafts it on, and no run-start
    path calls it.

    ⛔ AND THE COST HALF OF THIS ARGUMENT IS STRUCK, 2026-08-26. A first version
    added "buying it here costs a Firestore read per run start", which review
    showed is self-refuting: firing unconditionally costs the route's own
    ``devices/{id}`` read ANYWAY, plus a rate-limiter transaction (one read and
    one write) and a WAN POST. The read is moved and doubled, not avoided — and
    on the branches that resolve a device by listing, rows carrying ``ownerUid``
    are already in hand and thrown away. What survives, and is the whole reason,
    is the TRUST half below.

    ⭐ It is also the wrong place. The route re-reads the device document and
    answers ``self`` for an owner precisely because a machine's claim about who
    owns it cannot be trusted; duplicating that rule in the least trustworthy
    process, to save one request, trades a real authority for a cached guess.
    The concern the plan actually had — that an owner's own runs burn the owner's
    own 20/hour ``sharer-run-notify`` budget — is a fault in the ROUTE's
    ordering, where the increment is charged before the self-check, and it is
    fixed there. That fix covers every present and future caller.

    ⚠ Best-effort, exactly like the browser's copy: an agent that dies between
    the enqueue and this call tells nobody, with nothing behind it.
    """
    try:
        _notify_device_owner_of_run_inner(sess, device_id, research_id, topic)
    except Exception as e:  # noqa: BLE001 — a courtesy notice, never a failure
        # ⛔⛔ ITS OWN GUARD, NOT THE THREAD'S. Caught by a test on 2026-08-26: the
        # only thing standing between a raising notice and a failed run was
        # `_spawn` putting it on a daemon thread — and `_spawn` exists precisely
        # as a seam for tests to run the work inline, so the guarantee held
        # everywhere except where it was measured. A safety property that depends
        # on its dispatcher is not a property.
        log.info("owner-notify %s: not sent (%s)", research_id, type(e).__name__)


def _notify_device_owner_of_run_inner(sess: "AccountSession", device_id: str,
                                      research_id: str, topic: str) -> None:
    """The POST itself. Split out so the guard above owns every exit."""
    status, body = _fe_api_post(sess, "/api/notify", {
        "onBehalf": {
            "kind": "sharerRunStarted",
            "deviceId": device_id,
            "researchId": research_id,
            # ⭐ SENT, because the browser sends it and the same event must not
            # read differently depending on which client started the run. The
            # route sanitises it and caps it at 80 characters; omitting it
            # selects a body with no subject in it.
            "topic": topic,
        },
    })
    # ⛔ `skipped` IS THE NORMAL ANSWER FOR AN OWNER and it arrives as a 200:
    # the route answers `{ok: true, skipped: "self"}` when the caller owns the
    # machine, which is the common case for this caller. Logging that as a
    # failure would fill the log with the healthy path.
    if status == 200:
        why = body.get("skipped")
        log.info("owner-notify %s: %s", research_id,
                 f"skipped ({why})" if why else "delivered")
    else:
        # ⛔⛔ BOTH KEYS, found by review 2026-08-26. This read `error` alone — and
        # the route answers a DECISION refusal as `{ok:…, skipped:<reason>}` with
        # no `error` at all. So `not_a_sharer`, `bad_ids` and `unsupported_kind`
        # each printed `HTTP 403 ()`: the log gave the status and withheld the one
        # word that says why. `error` is carried by the two rate-limit refusals
        # and the auth 401; `skipped` by everything the decision itself refuses.
        detail = body.get("skipped") or body.get("error") or ""
        log.info("owner-notify %s: HTTP %s (%s)", research_id, status,
                 str(detail)[:120])


def _enqueue_research_run(fs: FirestoreRest, sess: AccountSession, *, topic: str,
                          device_id: str, cfg: dict[str, Any],
                          origin: dict[str, str] | None) -> tuple[str, str]:
    """Create the research (chat) doc, enqueue the start on ``device_id``, and seed
    the chat bubbles. Returns ``(research_id, queue_id)``.

    The SINGLE Firestore write path shared by the HTTP ``/research`` route AND the
    sign-in auto-start, so an agent run and an auto-started run are byte-identical
    on the wire (viaAgent=True, same doc shape, same queue doc). Raises
    ``RevokedError`` / ``FirestoreError`` if the doc create fails; ``_EnqueueFailed``
    if the enqueue fails (the orphan doc is cleaned up first)."""
    rid = "agent-" + uuid.uuid4().hex[:16]
    # The web app stamps submittedByDisplayName (displayName || email local-
    # part) on both docs; the bridge only knows the email — mirror the FE's
    # local-part fallback so owner-side surfaces label the sharer identically.
    display_name = (sess.email or "").split("@")[0]
    fs.upsert_research(sess.uid, rid,
                       _new_research_fields(topic, device_id, sess.uid, cfg, origin,
                                            display_name=display_name))
    try:
        qid = fs.enqueue_start(
            device_id, uid=sess.uid, research_id=rid,
            topic=topic, email=sess.email, config_obj=cfg or {},
            display_name=display_name,
        )
    except (RevokedError, FirestoreError) as e:
        # The chat doc is already created; the enqueue failed (e.g. the device isn't
        # a member / went away). Best-effort delete so we don't orphan a chat with
        # no run behind it.
        try:
            fs.delete_research(sess.uid, rid)
        except Exception:
            log.debug("orphan research %s cleanup failed", rid)
        raise _EnqueueFailed(e) from e
    # Seed the topic + "Researching …" bubbles the web app writes client-side at
    # run start, so an agent-started run's chat opens like a web-started one (the
    # BE pipeline only writes pipeline_events). Best-effort — never fail the run.
    try:
        fs.seed_chat_messages(sess.uid, rid, topic=topic, title=topic)
    except Exception as e:
        log.debug("chat-message seed for %s failed (non-fatal): %s", rid, type(e).__name__)
    log.info("enqueued run %s on device %s", rid, device_id)
    # ⭐⭐ TELL THE MACHINE'S OWNER, if this person is not the machine's owner —
    # the route decides which, because this side cannot be trusted to. Owner,
    # 2026-08-25: "I'm not getting notified in spite of being the owner." The
    # notice was fine; its only caller was a browser.
    #
    # ⛔ ON A THREAD, AND AFTER THE QUEUE WRITE HAS LANDED. The POST carries a
    # 20-second timeout, and a courtesy notice may not add that to the latency
    # of starting a run — nor may it turn a started run into an error. Placed
    # after the enqueue so it can only ever describe a run that is real.
    #
    # ⛔⛔ AND `_spawn` ITSELF IS GUARDED, found by review 2026-08-26. Its body is
    # `threading.Thread(...).start()`, which raises `RuntimeError` on thread
    # exhaustion or at interpreter shutdown — outside every guard, two lines under
    # the promise above. `_research` catches only RevokedError / FirestoreError /
    # _EnqueueFailed and `do_POST` wraps nothing, so this would have dropped the
    # connection on a run ALREADY QUEUED; on the sign-in path the catch-all turns
    # it into `{}`, the chat falls back to "reply yes", and the person starts a
    # SECOND real run. Same defect class as the notice's own guard being one level
    # too deep in the two web routes, found in the same review.
    try:
        _spawn(_notify_device_owner_of_run, sess, device_id, rid, topic)
    except Exception as e:  # noqa: BLE001 — a courtesy notice, never a failure
        log.info("owner-notify %s: not dispatched (%s)", rid, type(e).__name__)
    return rid, qid


def _pick_device_from(devs: list[dict[str, Any]],
                     selected: str | None) -> tuple[str | None, str, bool]:
    """THE device-routing decision, as one pure function: ``(device_id, reason,
    stale)``. ``reason`` is "" when it resolved, else ``no_devices`` /
    ``stale_selection`` / ``no_selection``. ``stale`` says the caller should drop a
    saved selection that is no longer a member.

    ⭐⭐ WHY THIS EXISTS. There were TWO device pickers with DIFFERENT rungs, and
    the sign-in one was the poorer of them. The run path (`_resolve_device`) went
    selection → drop a STALE selection → sole device → **the sole ONLINE device**
    → ask which. The sign-in auto-start went selection → sole device → give up. So
    on the shape most accounts actually have — several computers, one powered on —
    firing a research routed it seamlessly while signing in with that same research
    pending announced "reply yes to start". The two rungs the sign-in path was
    missing are the two that matter most, and they were sitting in the other picker.

    ⛔ NO I/O AND NO SIDE EFFECTS, deliberately: the stale-selection CLEAR belongs
    to the caller (one of them answers over HTTP, the other from a worker thread),
    and a picker that writes prefs cannot be tested as a table.
    """
    ids = {d.get("id") for d in devs}
    if selected and selected in ids:
        return selected, "", False
    stale = bool(selected)
    if not devs:
        return None, "no_devices", stale
    if len(devs) == 1:
        did = devs[0].get("id")
        if did:
            return did, "", stale
        # A sole device with no id is not a target — fall through to the ask
        # rather than enqueueing to an empty string (the run path does the same).
    online = [d for d in devs if _device_is_online(d) and d.get("id")]
    if len(online) == 1:
        return online[0].get("id"), "", stale
    return None, ("stale_selection" if stale else "no_selection"), stale


def _autostart_pick_device(fs: FirestoreRest,
                           sess: AccountSession) -> tuple[str | None, str | None,
                                                          list[dict[str, Any]], str]:
    """Pick the device for a sign-in auto-start WITHOUT a chat round-trip, on the
    SAME rungs a fired research gets (`_pick_device_from`). Returns ``(device_id, label,
    devices, reason)``; ``(None, None, devices, reason)`` when the account has
    several usable computers and none is the obvious one — and then the descriptors come back so
    the announce can NAME them instead of saying "reply yes". Raises
    ``_NoResearchNode`` when the account has NO device (→ the pair-a-node prompt)."""
    devs = fs.list_devices(sess.uid)
    by_id = {d.get("id"): d for d in devs if d.get("id")}
    device_id, reason, stale = _pick_device_from(devs, prefs.get_selected_device(sess.uid))
    if stale:
        # The saved selection is no longer a member — drop it here too, exactly as
        # the run path does, or every later sign-in re-derives the same dead pick.
        prefs.clear_selected_device()
    if reason == "no_devices":
        raise _NoResearchNode()
    if device_id:
        return device_id, _device_label(by_id.get(device_id) or {}), [], ""
    # ⛔ THE REASON RIDES ALONG NOW. `reason` was bound and then read only by a guard
    # that could not fire, so a person whose saved computer had been removed was
    # asked "which should run this?" with no hint that their last choice was gone —
    # while the run path has told them exactly that since 0.1.27. Same event, same
    # account, two different explanations depending which door they came through.
    return None, None, [_device_descriptor(d) for d in devs], reason


def _autostart_enabled() -> bool:
    """``DG_AGENT_AUTOSTART`` (default ON) — in-field kill-switch for sign-in
    auto-start. Off → fully reverts to the legacy confirm-then-run ("reply yes")."""
    return os.environ.get("DG_AGENT_AUTOSTART", "1").strip().lower() in ("1", "true", "yes", "on")


def _spawn(target, *args) -> None:
    """Start a daemon thread. Indirected through one helper so tests can run the
    work synchronously (monkeypatch ``bridge._spawn``)."""
    threading.Thread(target=target, args=args, daemon=True).start()


def _run_autostart(sess: AccountSession, topic: str,
                   origin: dict[str, str] | None) -> dict[str, Any]:
    """Start a pending research server-side (device-resolve → enqueue) so a run no
    longer depends on the chat agent correctly interpreting a "yes" (the fragile
    handoff that kept misfiring live). Returns announce hints:

      {autoStarted: True, runId, deviceName, topic}     — started; watchdog will stream
      {needsDevice: True, topic}                        — no research node yet (pair prompt)
      {needsDeviceChoice: True, topic, devices: [...]}  — several usable computers,
                                                          none obvious → NAME them and ask
      {}                                                — an ERROR, and only an error
                                                          → caller falls back to "reply yes"

    ⛔⛔ THE FOURTH OUTCOME IS THE FIX, AND WHAT IT REPLACED WAS A GUARD THAT COULD
    NOT FIRE. "ambiguous device" and "Firestore threw" both returned ``{}``, so
    nothing downstream could tell them apart — a hint in the shape of a guard, with
    the two cases collapsed into one. The comment said "let the chat choose" while
    the empty dict told the chat nothing to choose BETWEEN.

    ⛔ AND THE OLD CLAIM THAT THE FALLBACK "CANNOT BE HONOURED" IS REFUTED. Replying
    "yes" DOES work: the run path answers `no_selection` with a `devices` array and
    sr.py already renders "You have N research computers — which should run this?".
    What this saves is an avoidable round-trip and the conflation above — not a dead
    end. Said plainly here because the plan said otherwise.

    Pure I/O, takes the topic BY VALUE (never touches the remote flow), and NEVER
    raises — so it is safe to run in a worker thread off the remote_lock."""
    try:
        fs = FirestoreRest(sess.id_token)
        try:
            device_id, label, choices, why = _autostart_pick_device(fs, sess)
        except _NoResearchNode:
            return {"needsDevice": True, "topic": topic}
        if not device_id:
            return {"needsDeviceChoice": True, "topic": topic, "devices": choices,
                    "staleSelection": why == "stale_selection"}
        cfg = _resolve_run_config(fs, sess, None)
        rid, _qid = _enqueue_research_run(fs, sess, topic=topic, device_id=device_id,
                                          cfg=cfg, origin=_clean_origin(origin))
    except Exception as e:
        log.warning("sign-in auto-start failed (%s) — falling back to confirm-then-run",
                    type(e).__name__)
        return {}
    log.info("sign-in auto-started research %s on device %s", rid, device_id)
    return {"autoStarted": True, "runId": rid, "deviceName": label or "", "topic": topic}


def _autostart_worker(state: BridgeState, sess: AccountSession, topic: str,
                      origin: dict[str, str] | None, base_ev: dict[str, Any]) -> None:
    """Run the auto-start I/O OFF the remote_lock, then publish the final one-shot
    announce. Runs in a daemon thread so a concurrent sign-in poll is never stalled
    behind ~1-2s of Firestore I/O. The topic was already CLAIMED (nulled on the
    flow) under the lock before this was spawned, so this can't double-start. A
    failure degrades to the confirm-then-run announce; a sign-out before completion
    suppresses the (now stale) announce."""
    result = _run_autostart(sess, topic, origin)
    ev = dict(base_ev)
    # The "reply yes" offer rides along ONLY in the fallback case; started / no-node
    # carry their own rendered message. The topic always rides along for the renderer.
    # The "reply yes" offer rides along ONLY when we genuinely do not know what
    # happened (the error fallback). started / no-node / pick-one each render their
    # own message, and offering "reply yes" beside "which computer?" would ask two
    # different questions in one breath.
    ev["pendingTopic"] = "" if (result.get("autoStarted") or result.get("needsDevice")
                                or result.get("needsDeviceChoice")) else topic
    ev.update(result)
    # ⛔ THE SAME SESSION, NOT MERELY A SESSION. This was `state.session is not
    # None`, an existence test — so a sign-out and a DIFFERENT account signing in
    # during the ~1-2s this worker spends in Firestore left the new person's
    # announce silently replaced by the old one's. `is_current` is the identity test
    # the same file already uses for exactly this concern.
    if state.is_current(sess):
        state.set_signed_in(ev)


def _audio_file_url(links: Any) -> str:
    """The DIRECT podcast media URL — ``links.audio_file`` (a public Storage
    audio file: .mp3 for runs from 2026-07-23 on, .m4a for older ones).

    NOT ``links.audio`` / ``links.notebooklm``: those hold the NotebookLM notebook
    WEB PAGE, not a media file (verified against research.py + firestore.ts).
    Tolerant of object-valued ({url,…}) and bare-string link entries.
    """
    if not isinstance(links, dict):
        return ""
    v = links.get("audio_file")
    if isinstance(v, dict):
        url = v.get("url")
        return url if isinstance(url, str) else ""
    return v if isinstance(v, str) else ""


def _audio_ext_and_mime(url: str) -> tuple[str, str]:
    """Pick a file extension + MIME for a podcast audio URL.

    The Storage object name carries the real extension before the query string
    (…/audio_overview.mp3?alt=media&token=… for current runs, .m4a for older
    ones); default to .m4a (NotebookLM's native Audio Overview format) when
    none is recognizable.
    """
    path = urlsplit(url).path.lower()
    for ext, mime in _AUDIO_EXT_MIME.items():
        if path.endswith(ext):
            return ext, mime
    return ".m4a", _AUDIO_EXT_MIME[".m4a"]


def _safe_filename(title: str, ext: str) -> str:
    """A human, filesystem-safe audio filename from the run title — the name the
    user sees on the forwarded audio message. Keeps unicode letters/digits and
    strips only Windows-reserved / control characters."""
    cleaned = _FILENAME_BAD_RE.sub("", " ".join((title or "").split())).strip(" .")
    return (cleaned[:80] or "Podcast") + ext


# Link kinds whose value is a tokenized Storage download URL (…?alt=media&token=…).
# The token must NEVER leave the host or land in chat history — _research_podcast
# fetches the media host-side and hands back only a local path. So the bridge never
# emits it in ANY client response either. But sr.py / cli.py's `podcast` run-picker
# keys off the mere PRESENCE of an audio_file entry (to prefer a run that already
# has audio), so responses KEEP the kind marker and drop only the url value.
_TOKENIZED_LINK_KINDS = frozenset({"audio_file"})


def _redact_media_urls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy a flattened-links list with the tokenized Storage URL removed from any
    media entry (kind in ``_TOKENIZED_LINK_KINDS``), keeping the kind marker — the
    podcast run-pick needs it — and every other link untouched."""
    out: list[dict[str, Any]] = []
    for e in events:
        if isinstance(e, dict) and e.get("kind") in _TOKENIZED_LINK_KINDS:
            e = {k: v for k, v in e.items() if k != "url"}
        out.append(e)
    return out


def _redact_doc_media(doc: dict) -> dict:
    """A shallow copy of a run doc safe to return to a client: the tokenized
    Storage audio URL (``links.audio_file``) dropped. ``links.audio`` /
    ``links.notebooklm`` stay — those hold the PUBLIC NotebookLM page, not a media
    file. Returns the doc unchanged when there's nothing to redact."""
    if not isinstance(doc, dict):
        return doc
    links = doc.get("links")
    if not isinstance(links, dict) or not any(k in links for k in _TOKENIZED_LINK_KINDS):
        return doc
    clean = dict(doc)
    clean["links"] = {k: v for k, v in links.items() if k not in _TOKENIZED_LINK_KINDS}
    return clean


def _is_allowed_audio_url(url: str) -> bool:
    """True only for an https Firebase/GCS Storage URL. The audio URL comes from
    the (account-scoped) research doc, so a doctored value is at most self-SSRF —
    but the host-side fetch is still gated to the expected Storage hosts."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return host in _ALLOWED_AUDIO_HOSTS or host.endswith(_ALLOWED_AUDIO_HOST_SUFFIXES)


def _prune_podcast_dir(dest_dir: Path, *, keep_name: str) -> None:
    """Bound the on-disk podcast cache: drop any file — or title-named delivery
    SUBDIR (see ``_podcast_delivery_copy``) — older than
    ``_PODCAST_MAX_AGE_SECONDS`` (age-only — pruning by run prefix could delete a
    concurrent download's just-finished file). Best-effort — never raises."""
    now = time.time()
    try:
        entries = list(dest_dir.iterdir())
    except OSError:
        return
    for p in entries:
        try:
            # Never touch the keep file or an in-flight .part.
            if p.name == keep_name or p.suffix == ".part":
                continue
            if (now - p.stat().st_mtime) <= _PODCAST_MAX_AGE_SECONDS:
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)  # aged delivery-copy subdir
            elif p.is_file():
                p.unlink(missing_ok=True)
        except OSError:
            continue


def _download_podcast_audio(url: str, dest_dir: Path, rid: str) -> tuple[Path, int]:
    """Download a public Storage audio URL to ``dest_dir``; return (path, size).

    Cached by (rid, hash-of-url): the URL fully determines the bytes, so an
    identical URL is an instant cache hit and a regenerated audio (new URL)
    writes a fresh file. Streams to a ``.part`` temp then renames, so a partial
    download is never served. Raises ``ValueError`` if the URL host isn't an
    allowed Storage host or the response exceeds the size cap, and
    ``requests.RequestException`` on a transport failure.
    """
    if not _is_allowed_audio_url(url):
        raise ValueError("audio url host not allowed")
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext, _ = _audio_ext_and_mime(url)
    tag = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    final = dest_dir / f"{rid}-{tag}{ext}"
    if final.exists() and final.stat().st_size > 0:
        return final, final.stat().st_size  # cache hit — same URL ⇒ same bytes
    _prune_podcast_dir(dest_dir, keep_name=final.name)
    # A per-attempt unique .part so two concurrent downloads of the SAME run
    # never write the same temp file (each atomically renames onto `final`).
    tmp = final.with_name(f"{final.name}.{uuid.uuid4().hex[:8]}.part")
    size = 0
    try:
        with requests.get(url, stream=True, timeout=30, allow_redirects=False) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > _PODCAST_MAX_BYTES:
                        raise ValueError("podcast audio exceeds the size cap")
                    fh.write(chunk)
        tmp.replace(final)
    except BaseException:
        tmp.unlink(missing_ok=True)  # never leave a partial .part behind
        raise
    return final, size


def _media_tool_bin(name: str) -> str | None:
    """Path to an ffmpeg-family binary, or None when it isn't installed.

    Both are OPTIONAL here (the podcast normally arrives already encoded), so every
    caller must degrade rather than fail. Probes the usual install roots as well as
    PATH: a launchd/systemd child can inherit a minimal PATH that omits /usr/local/bin
    and Homebrew's prefix."""
    found = shutil.which(name)
    if found:
        return found
    for root in _FFMPEG_FALLBACK_DIRS:
        cand = os.path.join(root, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _ffmpeg_bin() -> str | None:
    return _media_tool_bin("ffmpeg")


def _ffprobe_bin() -> str | None:
    return _media_tool_bin("ffprobe")


def _delivery_ceiling(platform: str | None) -> int:
    """The upload ceiling for the chat platform this podcast is headed to.

    An unknown / absent platform keeps the historical Telegram-shaped default rather
    than the strictest one: over-shrinking every unknown caller would cost quality on
    the common path, and the post-encode size check still guarantees we never hand
    back something the platform will refuse."""
    key = (platform or "").strip().lower()
    if key in _DELIVERY_LIMITS:
        return _DELIVERY_LIMITS[key]
    return _DELIVERY_MAX_BYTES


def _audio_duration_seconds(path: Path) -> float | None:
    """Length of an audio file via ffprobe, or None when it can't be determined."""
    probe = _ffprobe_bin()
    if probe is None:
        return None
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return None
        seconds = float((out.stdout or "").strip())
        return seconds if seconds > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _shrink_bitrate_kbps(ceiling: int, duration_s: float | None) -> int | None:
    """The mono bitrate that fits ``ceiling``, or None if even the floor won't.

    Derived from the real duration so a tight channel (WhatsApp) gets a rate that
    actually fits rather than a fixed guess that still overshoots. Without a duration
    probe, try the transparent default and let the post-encode size check decide."""
    if not duration_s or duration_s <= 0:
        return _SHRINK_MAX_KBPS
    kbps = int((ceiling * _SHRINK_HEADROOM * 8) / duration_s / 1000)
    if kbps < _SHRINK_MIN_KBPS:
        return None  # would have to go below speech-usable quality — send the link
    return min(kbps, _SHRINK_MAX_KBPS)


def _shrink_for_delivery(cache_path: Path, ceiling: int) -> Path | None:
    """Re-encode an oversized overview to a mono MP3 that fits ``ceiling``.

    Returns the smaller file, or None when it can't be produced (no ffmpeg, the encode
    failed, the required bitrate would fall below the speech floor, or the result is
    STILL over the ceiling) — the caller then hands back the permanent link instead of
    a file the platform will refuse.

    Cached beside the original as ``<stem>-<kbps>k-small.mp3``; the bitrate is in the
    name so two channels with different ceilings never serve each other's file. The
    original is KEPT — it is the download cache's dedup key and remains the full-quality
    answer for every other consumer (the web app streams the untouched Storage object).
    """
    ff = _ffmpeg_bin()
    if ff is None:
        return None
    kbps = _shrink_bitrate_kbps(ceiling, _audio_duration_seconds(cache_path))
    if kbps is None:
        return None
    small = cache_path.with_name(f"{cache_path.stem}-{kbps}k{_SHRINK_SUFFIX}")
    if small.exists() and 0 < small.stat().st_size <= ceiling:
        return small  # cache hit
    # The temp MUST keep the `.part` suffix — that is `_prune_podcast_dir`'s in-flight
    # guard. ffmpeg picks its muxer from the output EXTENSION, and nothing claims
    # `.part`, so the container has to be named explicitly with `-f mp3`; without it
    # every encode aborts with "Unable to choose an output format" and the shrink
    # silently degrades to link-only.
    tmp = small.with_name(f"{small.name}.{uuid.uuid4().hex[:8]}.part")
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [ff, "-y", "-nostdin", "-i", str(cache_path), "-vn", "-map_metadata", "0",
             "-ac", "1", "-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-f", "mp3", str(tmp)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900,
            creationflags=no_window,
        )
        if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            # Surface WHY: a silent None here is indistinguishable from "no ffmpeg",
            # and the failure only shows up as a podcast that never plays.
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            log.warning("podcast shrink failed (rc=%s): %s", proc.returncode,
                        tail[-1][:200] if tail else "no stderr")
            return None
        if tmp.stat().st_size > ceiling:
            return None  # even re-encoded it won't fit — fall back to the link
        tmp.replace(small)
        return small
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)  # no-op once renamed
        except OSError:
            pass


def _podcast_delivery_copy(cache_path: Path, title: str, ext: str) -> Path:
    """Return a DELIVERY path whose basename is the research title.

    A forwarded audio message shows the file's basename, and the on-disk cache
    name is the ugly ``<rid>-<url-hash>.mp3`` (keyed that way so an identical URL
    is an instant cache hit). Copy the cached bytes into a SUBDIR keyed by the
    unique cache stem (``<rid>-<url-hash>/<Title>.mp3``) and hand that back — the
    chat then shows the clean title, while the enclosing dir keeps deliveries for
    DIFFERENT runs that happen to share a title from ever colliding on one path
    (two same-titled runs would otherwise race on a single shared file, and the
    gateway reads ``localPath`` only later — so the loser's bytes could be sent).
    The cache file is left untouched (dedup + re-ask speed preserved); the subdir
    is age-pruned like any podcast file. Best-effort: on any copy failure fall
    back to the cache path itself, so the podcast is never broken for a cosmetic
    reason.
    """
    try:
        stem_dir = cache_path.parent / cache_path.stem  # unique per (rid, url)
        target = stem_dir / _safe_filename(title, ext)
        if target == cache_path:
            return cache_path
        stem_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cache_path, target)
        return target
    except OSError:
        return cache_path


class RemoteFlow:
    """A pending remote-login (device-flow) attempt, §11a.

    Holds the broker handle (``poll_token`` — kept server-side, never returned
    to the chat client) plus the user-facing ``code``/``verify_url`` and a
    coarse lifecycle ``state``: pending → connected | expired | error.
    """

    def __init__(self, poll_token: str, code: str, verify_url: str, expires_at: float) -> None:
        self.poll_token = poll_token
        self.code = code
        self.verify_url = verify_url
        self.expires_at = expires_at  # epoch seconds
        self.state = "pending"
        self.error = ""
        # A research topic the user fired while signed out (so we can offer to
        # continue it once they sign in) + the chat origin that started this flow
        # (so the proactive "signed in" announce is delivered to the right chat).
        self.pending_topic = ""
        self.origin: dict | None = None


class BridgeState:
    """Shared, thread-safe bridge state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: AccountSession | None = AccountSession.load()
        # CSRF nonce embedded in the sign-in page and required back on the
        # callback. The LOAD-BEARING anti-session-fixation control is the Origin
        # allow-list (_origin_ok) + the Host allow-list (_host_ok); this nonce
        # is a secondary guard (a normal cross-origin page can't read it because
        # /login/config carries no CORS headers). It is rotated after every
        # successful capture so a leaked value can't be replayed.
        self.login_token: str = secrets.token_urlsafe(32)
        # Pending remote-login flow + a dedicated lock so a poll's network call
        # serializes polls (no double-redeem of the one-shot custom token)
        # without blocking /status or other reads.
        self._remote: RemoteFlow | None = None
        self.remote_lock = threading.Lock()
        # The "just signed in" announce for the chat watchdog to post proactively
        # (set on remote-login capture, delivered by a /updates read). Carries the
        # email + any pending research topic. Mirrored to prefs.json so a bridge
        # restart between the sign-in and the watchdog's next tick cannot lose it;
        # this attribute is the in-process cache of that file.
        self._signed_in: dict | None = None

    @property
    def session(self) -> AccountSession | None:
        with self._lock:
            return self._session

    def set_session(self, sess: AccountSession | None) -> None:
        with self._lock:
            self._session = sess
        if sess is None:
            # ⛔⛔ THIS USED TO NULL THE ATTRIBUTE AND NOTHING ELSE, while a comment
            # beside it said a sign-out "invalidates any not-yet-delivered announce".
            # It did not: the very next `peek_signed_in` rehydrates the event off
            # disk and re-warms the cache, so the announce came straight back.
            # Cross-verification measured it. A partial clear is worse than none,
            # because the comment made it look handled.
            self.clear_signed_in()

    @property
    def signed_in(self) -> dict | None:
        with self._lock:
            return self._signed_in

    def set_signed_in(self, event: dict | None) -> None:
        """Park the announce, in memory AND on disk.

        ⛔ The disk write is the point. Before it, a bridge restart in the window
        between the sign-in capture and the watchdog's next tick lost the announce
        for good — while a research COMPLETION in the same window lost nothing,
        because the watchdog re-derives those from the research store every tick.
        That asymmetry was the whole defect."""
        with self._lock:
            self._signed_in = event
        uid = (event or {}).get("uid") if isinstance(event, dict) else None
        try:
            if isinstance(event, dict) and isinstance(uid, str) and uid:
                prefs.set_pending_announce(event, uid)
            else:
                prefs.clear_pending_announce()
        except Exception as e:  # noqa: BLE001 — an announce must never fail a sign-in
            log.warning("could not park the sign-in announce (%s) — memory only",
                        type(e).__name__)

    def take_signed_in(self, uid: str) -> dict | None:
        """Atomically remove and return the pending announce for ``uid``.

        ⭐⭐ THE THIRD SHAPE OF THIS, AND THE FIRST CORRECT ONE. It went:
          1. take-and-clear — exactly-once, and ANY failure after the read
             destroyed the announce. That was the original defect.
          2. peek, send, then clear — no loss on a failed send, but delivery
             became racy: this is a THREADING server, so a second poll could read
             the event between the send and the clear and announce it twice.
             Cross-verification found the ordering was ALSO wrong way round in the
             shipped code, and the flake found the race.
          3. take atomically HERE, and restore it in the caller's `except` if the
             send fails. Exactly-once under concurrency AND no loss on failure.

        ⛔ AND IT NO LONGER LEANS ON A DE-DUP I HAD NOT MEASURED. Shape 2's safety
        rested on both watchdogs de-duplicating on `ts` — which the BE one does,
        end to end, and which the FORK's does only when its cursor writes: on an
        unwritable home it prints the note and never records the stamp. That guard
        also has no test at all (proved by mutation: gutting it leaves the whole
        fleet suite green). Depending on it while knowing that would not have been
        honest.
        """
        # ⛔⛔ THE WHOLE TAKE IS UNDER THE LOCK, INCLUDING THE DISK HALF — and the
        # first version of this held it only across the in-memory read. Eight
        # concurrent polls then had ONE clear memory and the other SEVEN fall
        # through to the parked copy and all return it: measured, 4 of 8 announced.
        # An "atomic" take with a read outside the lock is not atomic; it just has a
        # narrower window. `prefs` takes its own lock and never calls back in here,
        # so nesting is safe.
        with self._lock:
            ev = self._signed_in
            if isinstance(ev, dict):
                if ev.get("uid") not in (None, uid):
                    return None
                self._signed_in = None
            else:
                ev = None
                try:
                    parked = prefs.get_pending_announce(uid)
                except Exception as e:  # noqa: BLE001
                    log.warning("could not read the parked sign-in announce (%s)",
                                type(e).__name__)
                    return None
                if isinstance(parked, dict):
                    ev = parked
            if ev is None:
                return None
            try:
                prefs.clear_pending_announce()
            except Exception as e:  # noqa: BLE001
                log.warning("could not clear the parked sign-in announce (%s)",
                            type(e).__name__)
            return ev

    def peek_signed_in(self, uid: str) -> dict | None:
        """The pending announce for ``uid`` WITHOUT consuming it — memory first,
        then the parked copy on disk (which is how it survives a restart).

        ⭐ WHY PEEK REPLACED TAKE. ``take_signed_in`` was atomic read-and-clear:
        exactly-once delivery, so ANY failure after the read — a dropped response, a
        crash while rendering — destroyed the announce. Delivery is now
        at-least-once: peek, write the response, then clear. That is safe because
        BOTH consumers already de-duplicate on the event's ``ts``
        (``__signed_in_ts__`` in our watchdog's state file and in the fork's), so a
        repeat is swallowed rather than announced twice. Measured in both copies
        before this changed — it is not an assumption about them.

        ⛔ And it removed the re-stash write entirely: a scope that does not own the
        event now simply leaves it alone, instead of taking it and putting it back."""
        with self._lock:
            ev = self._signed_in
        if isinstance(ev, dict):
            return ev if ev.get("uid") in (None, uid) else None
        try:
            ev = prefs.get_pending_announce(uid)
        except Exception as e:  # noqa: BLE001 — an unreadable file is not an error
            log.warning("could not read the parked sign-in announce (%s)",
                        type(e).__name__)
            return None
        if isinstance(ev, dict):
            with self._lock:
                self._signed_in = ev  # warm the cache so the next tick skips the read
            return ev
        return None

    def clear_signed_in(self) -> None:
        """Drop the announce from memory AND disk.

        ⛔ THE ONLY CLEARING POINT, and it did not use to be. Clearing was spread
        over four places and only one of them worked: ``_login_remote_start`` cleared
        (correct), ``_login_callback`` — the ``agent login --local`` page — did NOT,
        ``set_session(None)`` did but has no non-test callers, and the REAL sign-out
        path (``_self_logout`` → ``clear_session_if``) nulled the session under the
        lock without touching the announce at all. The reachable consequence was a
        STALE announce: sign in from chat, revoke or log out, sign in again through
        the local page, and the chat was told "Starting <the old topic> on <the old
        device> now" for a run that no longer existed."""
        with self._lock:
            self._signed_in = None
        try:
            prefs.clear_pending_announce()
        except Exception as e:  # noqa: BLE001
            log.warning("could not clear the parked sign-in announce (%s)",
                        type(e).__name__)

    def rotate_login_token(self) -> None:
        with self._lock:
            self.login_token = secrets.token_urlsafe(32)

    @property
    def remote(self) -> RemoteFlow | None:
        with self._lock:
            return self._remote

    def set_remote(self, flow: RemoteFlow | None) -> None:
        with self._lock:
            self._remote = flow

    def is_current(self, sess: AccountSession) -> bool:
        """True iff `sess` is still the live session (identity, lock-guarded)."""
        with self._lock:
            return self._session is sess

    def clear_session_if(self, sess: AccountSession) -> bool:
        """Compare-and-swap teardown: clear the session ONLY if it is still
        `sess`. Returns True if it cleared. This closes the revoke-vs-reconnect
        race — a heartbeat that decided to self-logout based on the OLD session's
        revoked read must not tear down a NEW session a concurrent reconnect
        swapped in (which legitimately cleared revoked)."""
        with self._lock:
            if self._session is sess:
                self._session = None
                cleared = True
            else:
                cleared = False
        if cleared:
            # ⛔ THE REAL SIGN-OUT PATH. `set_session(None)` also drops the pending
            # announce, but nothing outside the tests ever calls it — every
            # production sign-out (the /logout route and the revoke self-logout)
            # arrives here instead. Without this line a not-yet-delivered announce
            # outlived the session that produced it.
            self.clear_signed_in()
        return cleared


# ── Agent session (#790): the renamable identity row in the app's "Shared with"
# popup, plus the heartbeat that proves the agent is live and the revoke-consult
# that lets a user disconnect it from the app. The doc lives at
# users/{uid}/agentSessions/{installId}; the bridge writes it AS THE ACCOUNT USER
# (owner branch), so the FE reading its own rows and this write share one
# owner-only rules line (mirrors users/{uid}/sessions). ────────────────────────


def _write_agent_session_connected(sess: AccountSession, *, clear_revoked: bool) -> None:
    """Create/refresh the agent-session doc.

    Best-effort: a Firestore failure here must NEVER block the login response —
    the live session is already set in memory. GET-first so an FE rename of the
    label survives a reconnect (we only stamp the default label when the doc has
    none).

    ``clear_revoked`` is the load-bearing authorization gate. Set it True ONLY on
    an explicit human sign-in (the two /login handlers) — that is the sole event
    permitted to un-revoke a previously-revoked agent. On any AUTOMATIC re-arm
    (serve() startup after restart, the heartbeat's missing-doc re-create) pass
    False: we then OMIT the ``revoked`` field entirely, preserving whatever the
    user set (so a revoke that landed while the bridge was down is NOT silently
    undone by a restart).
    """
    try:
        sid = prefs.get_or_create_install_id()
        fs = FirestoreRest(sess.id_token)
        label = ""
        try:
            existing = fs.get_agent_session(sess.uid, sid)
        except Exception:
            existing = None
        if isinstance(existing, dict):
            lv = existing.get("label")
            if isinstance(lv, str) and lv:
                label = lv
        if not label:
            label = prefs.get_label()
        now_ms = int(time.time() * 1000)
        fields: dict[str, Any] = {
            "label": label,
            "runtime": prefs.get_runtime() or "",
            "email": sess.email or "",
            "connectedAt": now_ms,
            "lastSeenAt": now_ms,
        }
        if clear_revoked:
            # Only an explicit human sign-in clears the flag (masked merge, so
            # omitting it on the automatic paths leaves the stored value intact).
            fields["revoked"] = False
        fs.upsert_agent_session(sess.uid, sid, fields)
        log.info("agent session %s connected for %s", sid, _mask_email(sess.email or sess.uid))
    except Exception as e:  # never logs the exception value (token-leak safe)
        log.warning("agent session connect-write failed (non-fatal): %s", type(e).__name__)


# Run statuses that need the user to open the app and act (mirror the FE's
# paused / watchdog cards). Surfaced on /updates so a chat poller can tell the
# user a run is stuck — see _attention_text. A pendingDecision map on the doc
# (login/verify/snag card) also counts, regardless of status.
_ATTENTION_STATUSES = (
    "errored", "stopped_by_watchdog",
    "paused_backend_restart", "paused_backend_restart_failed",
)


def _sr_links(doc: dict) -> dict:
    """Permanent superresearch.io share links for a run, from the ``srShares``
    map the FE mints at Phase-5 delivery (#741): docType→shareId for the brief +
    each agent report, plus ``podcast``. These are denormalized SNAPSHOT shares
    marked permanent — exempt from "Revoke All Shares" — i.e. the same
    never-breaking links embedded in the delivered Google Doc, and the ones safe
    to hand out in chat (unlike platform share links, which the user can revoke,
    or the tokenized Storage audio URL, which must never reach chat at all)."""
    shares = doc.get("srShares")
    if not isinstance(shares, dict):
        return {}
    out: dict[str, str] = {}
    for doc_type, share_id in shares.items():
        if not share_id or not isinstance(share_id, str):
            continue
        page = "podcast" if doc_type == "podcast" else "doc"
        out[doc_type] = f"{config.FE_BASE}/shared/{page}/{share_id}"
    return out


def _fe_api_post(sess: "AccountSession", path: str, payload: dict) -> tuple[int, dict]:
    """POST a web-app API route (`{FE_BASE}{path}`) as the signed-in USER —
    the same Bearer-ID-token calls the browser makes. Used for the device
    pair/unpair routes, which MUST go through the app's admin-SDK handlers
    (Firestore rules deliberately block owner/sharer writes to ownerUid /
    sharedWith). Returns (status, decoded-json|{}); never raises — transport
    failures come back as (0, {"error": …}) for the caller to surface."""
    try:
        r = requests.post(
            f"{config.FE_BASE}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {sess.id_token()}"},
            timeout=20,
        )
        try:
            body = r.json() if r.content else {}
        except ValueError:
            body = {}
        return r.status_code, body if isinstance(body, dict) else {}
    except requests.RequestException as e:
        return 0, {"error": f"could not reach {config.FE_BASE} ({type(e).__name__})"}


# The most of the agent's own log we will ever send. The file rotates at 1 MB with
# 3 backups, so 4 MB can exist and only the ACTIVE file is ever read — but the cap
# is stated here as well, because the route on the other side enforces its own and
# a body it refuses is a wasted upload.
_AGENT_LOG_MAX_BYTES = 8 * 1024 * 1024


def _fe_api_post_bytes(sess: "AccountSession", path: str, blob: bytes,
                       content_type: str, headers: dict[str, str]) -> tuple[int, dict]:
    """POST raw BYTES to a web-app API route as the signed-in user.

    ⭐ The sibling of `_fe_api_post`, and it exists for the same reason that one
    does: some writes must go through the app's admin-SDK handlers because the
    rules deliberately refuse them. This one carries a body that is not JSON.

    ⛔ THE AGENT CANNOT WRITE TO STORAGE DIRECTLY, which is why this is the shape.
    `storage.rules` gates every write under `logs/**` on a `deviceId` custom claim
    equal to the path segment, and this session's token has NO custom claims at all
    — `/api/agent/login/approve` mints `createCustomToken(user.uid)` with no
    developer claims, deliberately, so that an agent can only ever be connected to
    its own account. Measured before building.
    """
    try:
        r = requests.post(
            f"{config.FE_BASE}{path}",
            data=blob,
            headers={"Authorization": f"Bearer {sess.id_token()}",
                     "Content-Type": content_type, **headers},
            timeout=60,
        )
        try:
            body = r.json() if r.content else {}
        except ValueError:
            body = {}
        return r.status_code, body if isinstance(body, dict) else {}
    except requests.RequestException as e:
        return 0, {"error": f"could not reach {config.FE_BASE} ({type(e).__name__})"}


def _read_agent_log_tail(cap: int = _AGENT_LOG_MAX_BYTES) -> bytes:
    """The last ``cap`` bytes of the agent's own log, or b"" if there is none.

    ⛔ THE TAIL, NOT THE HEAD. If the file is over the cap the interesting part is
    what happened most recently — the thing the person is reporting — so a head
    read would send the least useful bytes and call it done.

    ⛔ AND THE ACTIVE FILE ONLY, not the rotated backups. Sending four files under
    one name is not something the receiving route or a reader would understand, and
    the active file is where a just-reproduced problem is.
    """
    path = config.log_path()
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > cap:
                fh.seek(size - cap)
                # A mid-line start is inevitable when tailing; drop the partial
                # first line so the upload begins at a real record.
                fh.readline()
            return fh.read()
    except OSError as e:
        log.info("agent log not readable (%s) — nothing to send", type(e).__name__)
        return b""


# Phase → (display name, ordered link specs). A spec is (label, source) where
# source is "sr:<docType>" (the permanent, non-revocable share) or "pf:<kind>"
# (a platform link with no SR equivalent — NotebookLM / YouTube / final Doc).
# Mirrors what the delivered Phase-5 Google Doc embeds, grouped by phase.
_PHASE_PLAN: dict[int, tuple[str, tuple[tuple[str, str], ...]]] = {
    1: ("Research Brief", (("Brief", "sr:brief"),)),
    2: ("Deep Research", (("ChatGPT", "sr:chatgpt"), ("Gemini", "sr:gemini"), ("Claude", "sr:claude"))),
    3: ("Audio Overview", (("NotebookLM", "pf:notebooklm"), ("Podcast", "sr:podcast"))),
    4: ("Video", (("YouTube", "pf:youtube"),)),
    5: ("Delivery", (("Google Doc", "pf:gdocs"),)),
}
# The platform-link kind whose PRESENCE proves a phase's artifact exists (so its
# SR snapshot can be minted). audio_file is the podcast's Storage source.
_SR_PROOF_KIND = {"brief": "brief", "chatgpt": "chatgpt", "gemini": "gemini",
                  "claude": "claude", "podcast": "audio_file"}


def _completed_phases(doc: dict) -> dict:
    """{phase: "complete"|"skipped"} for every phase that is DONE — from the
    per-phase status array, plus phases the run advanced past, plus the final
    phase on a clean completion."""
    out: dict[int, str] = {}
    phases = doc.get("phases")
    if isinstance(phases, list):
        for ph in phases:
            if isinstance(ph, dict):
                pn, st = ph.get("phase"), ph.get("status")
                if isinstance(pn, int) and st in ("complete", "skipped"):
                    out.setdefault(pn, st)
    cur = doc.get("phase")
    if isinstance(cur, int):
        for p in range(cur):
            out.setdefault(p, "complete")  # advanced past it
        if doc.get("status") == "completed":
            out.setdefault(cur, "complete")  # clean end → current phase done
    return out


def _platform_links(doc: dict) -> dict:
    """{kind: url} from the run's flattened (platform) links."""
    return {e["kind"]: e["url"] for e in runview.flatten_links(doc.get("links")) if e.get("url")}


def _sr_mint_gap(sr_links: dict, platform: dict, done: dict) -> bool:
    """True if a COMPLETE phase has an artifact (platform proof) but its
    permanent SR share isn't minted yet — i.e. minting would fill a real gap."""
    for p, st in done.items():
        if st != "complete":
            continue
        for _label, src in _PHASE_PLAN.get(p, ("", ()))[1]:
            if src.startswith("sr:"):
                dt = src[3:]
                if dt not in sr_links and _SR_PROOF_KIND.get(dt, dt) in platform:
                    return True
    return False


# pf: source → the platform link kind(s) to resolve (first hit wins). The final
# Google Doc is stored under kind "doc" (runview.KIND_ORDER); accept "gdocs" too
# defensively. NotebookLM/YouTube map 1:1.
_PF_KIND_ALIASES: dict[str, tuple[str, ...]] = {"gdocs": ("doc", "gdocs")}


def _phase_updates(doc: dict, sr_links: dict) -> list:
    """Ordered per-phase chat updates: one entry per DONE phase (1-5) carrying that
    phase's link(s). Link policy:
      • Brief (P1), the Deep-Research reports (P2), the Podcast (P3 audio overview)
        → the PERMANENT Super Research share links (🔒) — they never expire and
        survive "Revoke All Shares".
      • the NotebookLM notebook (P3), the YouTube video (P4) and the final Google
        Doc (P5) → their REAL platform links — NotebookLM is public, the upload is
        unlisted, and the Doc is shareable, so all open fine even signed out (and
        there is no SR snapshot for them).
    The tokenized Storage audio URL (kind audio/audio_file) is NOT in any phase's
    plan, so it never reaches chat. Skipped phases carry no links."""
    done = _completed_phases(doc)
    platform = _platform_links(doc)
    # The completion (🎉) marker is the LAST done phase of a run that has actually
    # completed — NOT hard-coded P5: a run with its last phase disabled (e.g. email
    # off) finishes at P4/P3, and pinning `final` to P5 would leave such a run with
    # no completion marker at all. Display-only here (the streaming watchdog now
    # announces completion off the run's terminal status, not this flag).
    completed = doc.get("status") == "completed"
    last_done = max(done) if done else None
    out = []
    for p in (1, 2, 3, 4, 5):
        st = done.get(p)
        if not st:
            continue
        name, specs = _PHASE_PLAN[p]
        links = []
        if st == "complete":
            for label, src in specs:
                if src.startswith("sr:"):
                    url = sr_links.get(src[3:])
                    permanent = True
                else:  # pf:* — a real platform link (NotebookLM / YouTube / Doc)
                    kind = src[3:]
                    url = next(
                        (platform[k] for k in _PF_KIND_ALIASES.get(kind, (kind,)) if k in platform),
                        None,
                    )
                    permanent = False
                if url:
                    links.append({"label": label, "url": url, "permanent": permanent})
        out.append({"phase": p, "name": name, "status": st, "links": links,
                    "final": completed and p == last_done})
    return out


def _mint_sr(sess: "AccountSession", rid: str, title: str) -> dict | None:
    """Trigger per-phase SR minting via the web app (POST /api/mintSrLinks as the
    user) — idempotent, mints only the docTypes whose content already exists.
    Returns the fresh {docType: url} map, or None on failure (callers fall back
    to whatever's already minted)."""
    status, body = _fe_api_post(sess, "/api/mintSrLinks", {"research_id": rid, "title": title or ""})
    sr = body.get("srLinks") if status == 200 else None
    return sr if isinstance(sr, dict) else None


def _attention_text(r: dict) -> str | None:
    """A short, human reason a run needs the user — or None if it's fine.
    Prefers the durable pendingDecision (the snag/login/verify card the BE
    mirrors onto the research doc), else maps a stuck status to plain words."""
    pd = r.get("pendingDecision")
    if isinstance(pd, dict) and pd:
        return (pd.get("title") or pd.get("message") or pd.get("reason")
                or "a decision is needed")
    status = r.get("status")
    if status == "errored":
        return "the run hit an error"
    if status in ("paused_backend_restart", "paused_backend_restart_failed"):
        return "paused after a backend restart"
    if status == "stopped_by_watchdog":
        return "stopped by the watchdog"
    return None


# Per-run command "actions" that resume vs skip a blocked run (the FE decision
# card writes these verbatim) — used to classify a pendingDecision's own actions.
_RESUME_ACTIONS = frozenset({
    "retry_phase", "retry_agent", "resume", "retry_init_verify", "continue_anyway",
})
_SKIP_ACTIONS = frozenset({
    "skip_phase", "skip_agent", "skip_init_verify", "continue_partial_agent",
})


def _decision_command(pd: dict | None, intent: str) -> dict | None:
    """The per-run command that resolves a blocked run for ``intent`` — "retry"
    resumes, "skip" moves past. Prefers the pendingDecision's OWN actions (the
    exact commands the FE offers — present on BE-authored pipeline_error cards),
    and falls back to a kind→command mapping for the FE-synthesized kinds
    (login_required / human_verification_required / agent_link_failed). Returns
    None when there's nothing to act on. Every action it emits is handled by
    research.py's per-run command listener."""
    if not isinstance(pd, dict) or not pd:
        return None
    want_resume = intent == "retry"
    # 1) Honor the decision's own actions verbatim when present.
    actions = pd.get("actions")
    if isinstance(actions, list):
        for a in actions:
            cmd = a.get("command") if isinstance(a, dict) else None
            if not isinstance(cmd, dict):
                continue
            act = cmd.get("action")
            if act == "agent_decision":
                if cmd.get("decision") == ("retry" if want_resume else "skip"):
                    return dict(cmd)
            elif act in (_RESUME_ACTIONS if want_resume else _SKIP_ACTIONS):
                return dict(cmd)
    # 2) Fall back to the kind for the FE-synthesized cards (no actions array).
    kind = pd.get("kind")
    agent = pd.get("agent")
    phase = pd.get("phase")
    if kind == "agent_link_failed" and agent:
        return {"action": "agent_decision", "agent": agent,
                "decision": "retry" if want_resume else "skip"}
    if kind == "human_verification_required":
        if want_resume:
            return {"action": "resume"}
        return {"action": "skip_agent", "agent": agent} if agent else {"action": "skip_init_verify"}
    if kind == "login_required" and not want_resume:
        return {"action": "skip_init_verify"}
    # login_required(retry) / pipeline_error / pro_required / generic.
    cmd2: dict = {"action": "retry_phase" if want_resume else "skip_phase"}
    if isinstance(phase, int):
        cmd2["phase"] = phase
    return cmd2


def _self_logout(state: BridgeState, sess: AccountSession | None) -> bool:
    """In-memory teardown shared by the /logout route and the revoke-consult.

    Compare-and-swap on ``sess``: tears down ONLY if it is still the live session
    (so a heartbeat deciding to self-logout against the OLD session can't undo a
    reconnect that swapped a NEW one in). Returns True iff it actually tore down.
    Clears the live session + the account-bound device selection. Both an app
    Revoke and a clean logout are pure sign-outs — they KEEP the installed skill
    + the recorded runtime, so a later `/sr login` / `agent login` reconnects
    without re-running connect (`agent disconnect` is the only full teardown).
    Does NOT touch the agentSessions doc — the route deletes it (clean logout),
    while the revoke path leaves the ``revoked: true`` row in place so the app
    shows the disconnect and a re-login can clear it.
    """
    if sess is None:
        prefs.clear_selected_device()
        return False
    if not state.clear_session_if(sess):
        return False  # a concurrent reconnect already swapped the session in — leave it
    sess.logout()
    prefs.clear_selected_device()
    return True


# Tolerate clock skew between THIS host's clock (connected_at_ms, from time.time()
# at capture) and Firestore's serverTimestamp (revokedAt) when deciding whether a
# revoke post-dates the current sign-in. Generous: a genuine revoke of a LIVE
# agent lands minutes-to-days after capture, so a 5-min margin never mis-ignores
# one; a stale revoke (the #848 case) predates capture by far more, so it is still
# correctly ignored. Errs toward HONORING a revoke (security) on the boundary.
_REVOKE_SKEW_MARGIN_MS = 5 * 60 * 1000


def _parse_firestore_ts_ms(v: Any) -> int | None:
    """Best-effort epoch-ms from a value read back via FirestoreRest: a plain int
    (the bridge writes connectedAt/lastSeenAt as ms ints) or an ISO-8601 string
    (a serverTimestamp, e.g. revokedAt='2026-06-10T00:10:26.123456789Z'). None on
    anything unparseable."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if not isinstance(v, str):
        return None
    s = v.strip().replace("Z", "+00:00")
    # Firestore may emit nanosecond precision; datetime.fromisoformat accepts at
    # most microseconds — truncate any longer fractional part to 6 digits.
    m = re.match(r"^(.*\.\d{6})\d+(.*)$", s)
    if m:
        s = m.group(1) + m.group(2)
    try:
        return int(dt.datetime.fromisoformat(s).timestamp() * 1000)
    except ValueError:
        return None


def _should_honor_revoke(doc: dict, sess: AccountSession) -> bool:
    """Whether a ``revoked: true`` agent-row should self-logout this session.

    Honor it ONLY when the revoke post-dates this sign-in — i.e. the user revoked
    THIS live agent — so a stale revoked row left from before the current capture
    can't tear down a freshly-signed-in session (#848). Conservative on the edges:
      * unknown capture epoch (a pre-change rehydrated session) ⇒ honor;
      * a genuine revoke always carries a serverTimestamp ``revokedAt``, so a
        ``revoked: true`` with no resolvable revokedAt is a stale/legacy row ⇒
        ignore (the heartbeat re-asserts the clear instead of self-logging-out).
    The skew margin absorbs host-vs-Firestore clock drift, erring toward honoring.
    """
    cap = getattr(sess, "connected_at_ms", None)
    if cap is None:
        return True  # we don't know when we signed in → honor the revoke (safe)
    revoked_at = _parse_firestore_ts_ms(doc.get("revokedAt"))
    if revoked_at is None:
        return False  # revoked:true with no resolvable revokedAt → stale row
    return revoked_at >= (int(cap) - _REVOKE_SKEW_MARGIN_MS)


def _arm_agent_session_on_start(state: BridgeState) -> None:
    """At serve() startup with a session rehydrated from disk: honor a revoke
    that landed while the bridge was DOWN, otherwise re-arm the row.

    A restart is an AUTOMATIC reconnect (no human present), so it must not
    un-revoke a genuine revoke. But a STALE revoke (one that predates this
    session's sign-in — see _should_honor_revoke) must NOT strand a valid
    session, so we re-assert the clear for it (#848).
    """
    sess = state.session
    if sess is None:
        return
    try:
        doc = FirestoreRest(sess.id_token).get_agent_session(
            sess.uid, prefs.get_or_create_install_id()
        )
    except Exception as e:
        log.warning("startup agent-session check failed (non-fatal): %s", type(e).__name__)
        doc = None
    if isinstance(doc, dict) and doc.get("revoked") is True:
        if _should_honor_revoke(doc, sess):
            log.info("startup: agent was revoked while the bridge was down — honoring revoke (skill + runtime kept)")
            _self_logout(state, sess)
            return
        log.info("startup: ignoring a stale revoke that predates this sign-in — re-asserting the agent row")
        _write_agent_session_connected(sess, clear_revoked=True)
        return
    _write_agent_session_connected(sess, clear_revoked=False)


def _heartbeat_once(state: BridgeState) -> None:
    """One heartbeat tick: consult ``revoked`` then bump ``lastSeenAt``.

    Transient Firestore/network errors are swallowed and the loop keeps running
    (silent self-heal); only a definitive ``revoked == true`` — or a token-level
    RevokedError (the account's refresh token itself was rejected) — triggers the
    self-logout. The reads/writes also keep the account token warm (refresh is
    otherwise purely lazy/on-demand).
    """
    sess = state.session
    if sess is None:
        return
    sid = prefs.get_or_create_install_id()
    try:
        fs = FirestoreRest(sess.id_token)
        doc = fs.get_agent_session(sess.uid, sid)
    except RevokedError:
        log.info("heartbeat: account token revoked — self-logout")
        _self_logout(state, sess)
        return
    except Exception as e:
        log.debug("heartbeat read transient failure: %s", type(e).__name__)
        return
    if isinstance(doc, dict) and doc.get("revoked") is True:
        if _should_honor_revoke(doc, sess):
            log.info("agent session %s revoked from the app — self-logout (skill + runtime kept)", sid)
            _self_logout(state, sess)
            return
        # Stale revoke (predates THIS sign-in): a prior capture's clear_revoked
        # write may have failed (best-effort). Re-assert the clear rather than
        # self-logging-out a freshly-captured session (#848) — but only if we're
        # still the current session (a concurrent /logout/reconnect could have
        # swapped it out between the GET and here).
        log.info("heartbeat: ignoring a stale revoke on %s (predates this sign-in) — re-asserting clear", sid)
        if state.is_current(sess):
            _write_agent_session_connected(sess, clear_revoked=True)
        return
    # A concurrent /logout or reconnect may have swapped the session out from
    # under us between the GET and here — don't write (would resurrect a just-
    # deleted row, or stamp lastSeenAt onto a different account's row).
    if not state.is_current(sess):
        return
    if doc is None:
        # The connect-write never landed (or the row was cleared out-of-band):
        # re-create it FULLY so the agent shows up — never resurrect a bare row,
        # and never un-revoke (clear_revoked=False).
        _write_agent_session_connected(sess, clear_revoked=False)
        return
    try:
        fs.upsert_agent_session(sess.uid, sid, {"lastSeenAt": int(time.time() * 1000)})
    except RevokedError:
        log.info("heartbeat: account token revoked — self-logout")
        _self_logout(state, sess)
    except Exception as e:
        log.debug("heartbeat write transient failure: %s", type(e).__name__)


def _heartbeat_loop(state: BridgeState, stop: threading.Event) -> None:
    """The single background tick. First fire after one interval (the connect
    handlers + serve() startup already wrote the doc, so the agent row appears
    immediately — the loop only sustains liveness + consults `revoked`)."""
    interval = config.HEARTBEAT_INTERVAL_SECONDS
    if interval <= 0:  # guard a misconfigured env from a Firestore-hammering busy loop
        interval = 60.0
    while not stop.wait(interval):
        try:
            _heartbeat_once(state)
        except Exception as e:  # defensive — a tick must never kill the thread
            log.debug("heartbeat tick error: %s", type(e).__name__)


def _advance_remote_flow(state: BridgeState) -> str | None:
    """Advance the pending remote-login (device-flow) by ONE broker poll.

    MUST be called holding ``state.remote_lock``. Reads ``state.remote`` FRESH
    (never a by-arg reference captured across the long poll), so a flow a
    concurrent /login/remote/start superseded can't be redeemed, and mutates
    ``flow.state`` in place. On the broker's APPROVED it redeems the one-time
    custom token, sets the live session, and writes the #790 agent-session row
    (clear_revoked=True — an explicit human sign-in). A NO-OP — no broker call —
    on an absent / terminal / past-TTL flow, so it is safe to call every tick.

    Returns a transient note for the HTTP payload (the auto-poll loop ignores
    it), else None. This is the exact transition `_login_remote_poll` used to run
    inline; it now lives here so the serve()-owned auto-poll loop shares it
    byte-for-byte (and the same lock), keeping the one-time token single-use.
    """
    flow = state.remote
    if flow is None or flow.state in ("connected", "expired", "error"):
        return None
    if time.time() >= flow.expires_at:
        # ⛔ THE ORDINARY FAILURE, AND IT USED TO BE SILENT. A person who never
        # finishes in the browser expires HERE, before the broker is asked — so the
        # INFO on the broker-reported branch below never fires, and the most common
        # unsuccessful sign-in left no trace in the log at all. That is precisely
        # the outcome somebody would be sending the log to explain.
        flow.state = "expired"
        log.info("remote login expired before approval (never confirmed in the browser)")
        return None
    try:
        res = devicelogin.poll_once(flow.poll_token)
    except DeviceLoginError as e:
        # Stay pending and keep polling: from here every one of these is
        # indistinguishable from a blip, and the flow's own TTL bounds the waiting.
        #
        # ⛔⛔ BUT IT IS NOT ALL BLIPS, AND THE OLD LINE SAID IT WAS. This catch also
        # takes a persistent HTTP 500 from the broker and "broker reported approved
        # but sent no custom token" — a sign-in that CANNOT succeed, retried until
        # the TTL runs out and then reported as an expiry. Calling that a "transient
        # transport blip" at DEBUG meant the default level recorded nothing and the
        # verbose level mislabelled it. The client still gets a fixed message, never
        # the upstream body.
        log.info("remote poll failed, still waiting: %s", e)
        return "sign-in service temporarily unreachable"
    status = res.get("status")
    if status == devicelogin.APPROVED:
        try:
            sess = AccountSession.from_custom_token(res["customToken"])
        except CustomTokenError as e:
            flow.state = "error"
            flow.error = "sign-in could not be completed"  # non-reflective
            log.warning("remote login custom-token exchange failed: %s", e)
            return None
        # Capture. We hold remote_lock for the whole call, so `flow` is still the
        # current state.remote here — no superseded-flow capture is possible.
        state.set_session(sess)
        flow.state = "connected"
        # Intentionally LEAVE state.remote in place (do NOT null it on capture):
        # a later `login-done` (/login/remote/poll) must still find the flow to
        # return state==connected + pendingTopic so chat can continue the topic
        # the user asked before signing in (the reliable, scheduler-independent
        # path). Token reuse is already prevented by the connected/expired/error
        # state-guard at the top of _advance_remote_flow — leaving the flow is safe.
        # #790 identity row — explicit human sign-in, so clear any prior revoke.
        _write_agent_session_connected(sess, clear_revoked=True)
        # One-shot event for the chat watchdog: announce the moment approval is
        # captured (delivered + cleared by a single /updates read; the FE/poll never
        # sees the token). ``origin`` scopes delivery to the chat that started sign-in.
        origin = flow.origin if isinstance(flow.origin, dict) else None
        base_ev = {
            "ts": int(time.time() * 1000),
            "email": sess.email or "",
            "uid": sess.uid,
            "origin": origin,
        }
        topic = (flow.pending_topic or "").strip()
        if topic and _autostart_enabled():
            # A research was fired while signed out → START it server-side rather
            # than asking the chat to interpret a "yes" (the fragile handoff that
            # kept misfiring live). CLAIM the topic atomically under remote_lock
            # (null it so a racing login-done can't double-start), then run the
            # ~1-2s of Firestore I/O OFF the lock in a worker thread so a concurrent
            # sign-in poll isn't stalled. The worker publishes the final announce
            # (started / pair-a-node / fallback "reply yes") when it's done.
            flow.pending_topic = None
            _spawn(_autostart_worker, state, sess, topic, origin, base_ev)
        else:
            # No pending research (or auto-start disabled) → announce immediately,
            # exactly as before. With a topic + autostart off, OFFER to continue.
            base_ev["pendingTopic"] = topic
            state.set_signed_in(base_ev)
        log.info("remote login connected as %s", _mask_email(sess.email or sess.uid))
    elif status == devicelogin.EXPIRED:
        flow.state = "expired"
        log.info("remote login expired before approval")
    return None


def _remote_autopoll_loop(state: BridgeState, stop: threading.Event) -> None:
    """serve()-owned daemon that drives a pending remote-login flow to capture the
    instant the user approves in the browser — so chat ``/sr login`` no longer
    needs a second ``login-done`` to complete the sign-in (the #848 fix; the
    browser's /approve only PARKS the token, the bridge must poll to redeem it).

    Mirrors `_heartbeat_loop`: one periodic tick, daemon, stop-event for
    deterministic shutdown. Each tick advances the CURRENT flow by one broker poll
    UNDER ``remote_lock`` (shared with the /login/remote/poll route + the PC
    ``agent login`` poller, so the one-time token is redeemed exactly once). It is
    a NO-OP — no network call — when no flow is pending, and the flow
    self-terminates at its TTL, so a finished or idle bridge does no broker
    traffic. Spawned from serve() (NOT a request handler), so handler-only unit
    tests never start it and can drive the flow by explicit polls as before.
    """
    interval = config.REMOTE_POLL_INTERVAL_SECONDS
    if interval <= 0:  # guard a misconfigured env from a broker-hammering busy loop
        interval = 3.0
    while not stop.wait(interval):
        try:
            with state.remote_lock:
                flow = state.remote
                if flow is not None and flow.state == "pending":
                    _advance_remote_flow(state)
        except Exception as e:  # defensive — a tick must never kill the thread
            log.debug("remote autopoll tick error: %s", type(e).__name__)


def _backend_cli() -> "str | None":
    """Path to the Super Research backend CLI co-located with this bridge, or
    None if it isn't on the host's PATH. The bridge runs on the same machine as
    the backend (the standard setup), so the chat `version` / `update` actions
    drive the LOCAL backend through it."""
    import shutil
    return shutil.which("superresearch")


def _backend_version() -> "str | None":
    """Version of the co-located Super Research backend, parsed from
    `superresearch --version` (the compiled build answers this on its fast lazy
    path — no heavy import). None if the backend CLI is absent or doesn't answer."""
    exe = _backend_cli()
    if not exe:
        return None
    import re
    import subprocess
    try:
        out = subprocess.run([exe, "--version"], capture_output=True,
                             text=True, timeout=15).stdout or ""
    except Exception:
        return None
    m = re.search(r"(\d+\.\d+\.\d+\S*)", out)
    # On a regex miss return None (version unknown) rather than raw CLI text — a
    # non-version string would be a misleading version display.
    return m.group(1) if m else None


# NOTE: no backend-update helper here. The runtime no longer updates the Super
# Research BACKEND — the app surfaces backend updates (the BE self-reports its
# version + update signal on its device-doc heartbeat) and the user runs
# `superresearch --update` on the Research computer. The agent only self-updates
# (see /agent-install → selfupdate.spawn_detached_reconnect). Backend INSTALL
# (turning a fresh PC into a research host) is a separate, still-supported action.


def _make_handler(state: BridgeState) -> type[BaseHTTPRequestHandler]:

    class Handler(BaseHTTPRequestHandler):
        server_version = f"SuperAgentBridge/{__version__}"

        # ── helpers ──
        def _json(self, code: int, body: Any) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _text(self, code: int, body: str, ctype: str = "text/plain") -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            # The sign-in page is read fresh from disk per request; never let the
            # browser serve a stale cached copy while we iterate on it.
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict[str, Any]:
            # Parse the body already drained at do_POST entry (see do_POST).
            raw = getattr(self, "_body", b"")
            if not raw:
                return {}
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def log_message(self, fmt: str, *args: Any) -> None:  # quieter logging
            log.debug("bridge %s - %s", self.address_string(), fmt % args)

        def _allowed_authorities(self) -> tuple[str, str]:
            port = self.server.server_address[1]
            return (f"localhost:{port}", f"127.0.0.1:{port}")

        def _host_ok(self) -> bool:
            """Reject any request whose Host isn't our loopback authority.

            Closes DNS-rebinding: a rebound hostname (evil.com -> 127.0.0.1)
            would carry Host: evil.com:port and is refused on EVERY route, so a
            rebind page can't even read /login/config or /status.
            """
            return self.headers.get("Host", "") in self._allowed_authorities()

        def _origin_ok(self) -> bool:
            """Reject cross-origin browser writes. Absent Origin (host CLI) is OK.

            Derived from the ACTUAL bound port so our own sign-in page (same
            port) is accepted while a cross-origin attacker is rejected.
            """
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            return origin in tuple(f"http://{a}" for a in self._allowed_authorities())

        def _account(self) -> tuple[AccountSession, FirestoreRest] | None:
            """Return (session, firestore-client) or send 401 and return None."""
            sess = state.session
            if sess is None:
                self._json(401, {"error": "not signed in — run /login"})
                return None
            return sess, FirestoreRest(sess.id_token)

        def _firestore_502(self, e: FirestoreError) -> None:
            """Upstream Firestore failure → log the detail, hand the client a
            fixed message (never echo the resolved path / upstream body back)."""
            log.warning("firestore error: %s", e)
            self._json(502, {"error": "could not reach the research store — try again"})

        # ── routes ──
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if not self._host_ok():
                self._json(403, {"error": "bad host"})
                return
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._json(200, {"ok": True, "version": __version__,
                                 "authed": state.session is not None})
            elif path == "/login":
                html = (_WEB_DIR / "login.html").read_text(encoding="utf-8")
                self._text(200, html, "text/html; charset=utf-8")
            elif path == "/login/config":
                cfg = config.web_config()
                cfg["loginToken"] = state.login_token
                cfg["runtime"] = prefs.get_runtime() or ""  # glow the connected runtime's symbol
                self._json(200, cfg)
            elif path == "/status":
                self._status()
            elif path == "/researches":
                self._researches()
            elif path == "/devices":
                self._devices()
            elif path == "/device":
                self._device_current()
            elif path == "/logs/runs":
                self._log_runs()
            elif path == "/logs/bundle":
                self._log_bundle()
            elif path == "/updates":
                self._updates()
            elif path == "/version":
                self._version(fresh="fresh=1" in (self.path.split("?", 1) + [""])[1])
            elif path.startswith("/research/") and path.endswith("/podcast"):
                self._research_podcast(path[len("/research/"):-len("/podcast")])
            elif path.startswith("/research/"):
                self._research_status(path[len("/research/"):])
            elif path.startswith("/icons/"):
                self._icon(path)
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            # Drain the request body up-front, BEFORE any early return — an
            # undrained body when the connection closes triggers a TCP RST that
            # the client sees as ConnectionAborted (Windows WinError 10053). Some
            # routes (cancel/logout/poll) take no body; clients (sr.py) may still
            # send "{}". Handlers parse this via _read_json (reads self._body).
            try:
                clen = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                clen = 0
            if clen > _MAX_BODY_BYTES:
                # Drain-and-discard in bounded chunks (no multi-MB buffer; a lying
                # length can't pin a worker on a huge in-memory read) then refuse —
                # draining keeps the 413 response clean (no TCP RST).
                remaining = clen
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                self._json(413, {"error": "request body too large"})
                return
            self._body = self.rfile.read(clen) if clen > 0 else b""
            if not self._host_ok():
                self._json(403, {"error": "bad host"})
                return
            if not self._origin_ok():
                self._json(403, {"error": "cross-origin POST rejected"})
                return
            path = self.path.split("?", 1)[0]
            if path == "/login/callback":
                self._login_callback()
            elif path == "/login/remote/start":
                self._login_remote_start()
            elif path == "/login/remote/poll":
                self._login_remote_poll()
            elif path == "/login/remote/pending":
                self._login_remote_pending()
            elif path == "/logout":
                self._logout()
            elif path == "/device/select":
                self._device_select()
            elif path == "/device/pair":
                self._device_pair()
            elif path == "/device/remove":
                self._device_remove()
            elif path == "/logs/send":
                self._log_send()
            elif path == "/logs/agent-log":
                self._log_agent_log()
            elif path == "/research":
                self._research()
            elif path.startswith("/research/") and path.endswith("/stop"):
                self._research_stop(path[len("/research/"):-len("/stop")])
            elif path.startswith("/research/") and path.endswith("/pause"):
                self._research_pause(path[len("/research/"):-len("/pause")])
            elif path.startswith("/research/") and path.endswith("/resume"):
                self._research_resume(path[len("/research/"):-len("/resume")])
            elif path.startswith("/research/") and path.endswith("/resolve"):
                self._research_resolve(path[len("/research/"):-len("/resolve")])
            elif path.startswith("/research/") and path.endswith("/cancel"):
                self._research_cancel(path[len("/research/"):-len("/cancel")])
            elif path.startswith("/research/") and path.endswith("/skip"):
                self._research_skip(path[len("/research/"):-len("/skip")])
            elif path == "/shutdown":
                self._shutdown()
            elif path == "/agent-install":
                self._agent_install()
            elif path == "/install-backend":
                self._install_backend()
            else:
                self._json(404, {"error": "not found"})

        # ── handlers ──
        def _login_callback(self) -> None:
            body = self._read_json()
            if not secrets.compare_digest(str(body.get("loginToken", "")), state.login_token):
                self._json(403, {"error": "bad or missing login token"})
                return
            rt = body.get("refreshToken")
            uid = body.get("uid")
            if not rt or not uid:
                self._json(400, {"error": "missing refreshToken/uid"})
                return
            try:
                sess = AccountSession.from_capture(
                    refresh_token=rt,
                    id_token=body.get("idToken", ""),
                    uid=uid,
                    email=body.get("email", ""),
                    expires_in=int(body.get("expiresIn", 3600) or 3600),
                )
            except Exception as e:  # pragma: no cover - defensive
                log.exception("login capture failed")
                self._json(500, {"error": f"capture failed: {e}"})
                return
            state.set_session(sess)
            # ⛔ MIRRORS `_login_remote_start`, AND DID NOT. A fresh sign-in
            # supersedes any prior, undelivered announce. The remote flow cleared it;
            # this host-local page did not — so a revoke (or /logout) followed by
            # `agent login --local` handed the chat the PREVIOUS session's announce:
            # "Starting <the old topic> on <the old device> now", for a run that no
            # longer existed.
            state.clear_signed_in()
            state.rotate_login_token()  # one-shot: the captured nonce can't be replayed
            # #790 identity row — explicit human sign-in, so clear any prior revoke.
            _write_agent_session_connected(sess, clear_revoked=True)
            log.info("account session captured (local page) for %s", _mask_email(sess.email or sess.uid))
            self._json(200, {"ok": True, "uid": sess.uid, "email": sess.email})

        # ── remote login (device flow, §11a) ──
        def _remote_payload(self, flow: RemoteFlow) -> dict[str, Any]:
            """Public flow status — never includes poll_token or the custom token."""
            sess = state.session
            out: dict[str, Any] = {
                "state": flow.state,
                "authed": sess is not None,
                "code": flow.code,
                "verifyUrl": flow.verify_url,
            }
            if flow.state == "connected" and sess is not None:
                out["email"] = sess.email
                out["uid"] = sess.uid
                # Surface any research topic the user asked before signing in, so a
                # `login-done` follow-up can continue it even when the proactive
                # watchdog never armed (the reliable, scheduler-independent path).
                if flow.pending_topic:
                    out["pendingTopic"] = flow.pending_topic
            if flow.error:
                out["error"] = flow.error
            return out

        def _login_remote_start(self) -> None:
            body = self._read_json()
            # ⛔⛔ THE OTHER DOOR, AND IT WAS UNCOVERED. Cross-verification found that
            # closing the theft on /login/remote/pending left this one open: a start
            # mints a fresh flow and replaces the held topic AND origin outright, so
            # chat B firing a research while chat A's link is unapproved voids A's
            # request and A's destination together.
            #
            # ⚠ THE RULE HERE IS DELIBERATELY WEAKER THAN /pending's, and the
            # asymmetry is the point rather than an oversight. This route is ALSO
            # the recovery door — "send me a fresh sign-in link" — and the terminal
            # reaches it with no origin at all. So /pending demands proof of
            # identity and refuses without it; this one refuses only when the caller
            # PROVES it is somebody else. An origin-less start still replaces the
            # flow, because that is a person starting over on their own machine and
            # there is no way to tell them from themselves.
            incoming = body.get("origin")
            if isinstance(incoming, dict):
                with state.remote_lock:
                    held = state.remote
                    if (held is not None and held.state == "pending"
                            and (held.pending_topic or "").strip()
                            and isinstance(held.origin, dict)
                            and not _same_origin(held.origin, incoming)):
                        self._json(409, {"reason": "topic_taken",
                                         "error": "another chat is already signing in "
                                                  "with a research waiting — ask again "
                                                  "once that finishes"})
                        return
            try:
                flow = devicelogin.start(
                    label=str(body.get("label", "")), runtime=str(body.get("runtime", ""))
                )
            except DeviceLoginError as e:
                # Log the detail; hand the client a fixed, non-reflective message
                # (don't echo an upstream/proxy body back through the chat).
                log.warning("remote login start failed: %s", e)
                self._json(502, {"error": "could not reach the sign-in service — try again"})
                return
            # Clamp the FE-supplied TTL so the bridge's own polling window is
            # bounded no matter what the broker claims.
            ttl = max(1, min(int(flow["expiresIn"]), _REMOTE_MAX_TTL_SECONDS))
            rf = RemoteFlow(
                poll_token=flow["pollToken"],
                code=flow["code"],
                verify_url=flow["verifyUrl"],
                expires_at=time.time() + ttl,
            )
            # Optional: a topic fired while signed out (offer to continue post-login)
            # + the chat origin (scope the proactive "signed in" announce to it).
            pt = body.get("pending_topic")
            if isinstance(pt, str):
                rf.pending_topic = pt[:500]
            og = body.get("origin")
            if isinstance(og, dict):
                rf.origin = og
            # Take remote_lock so a start can't swap the flow out from under an
            # in-flight poll (and vice-versa); start/poll are mutually exclusive.
            with state.remote_lock:
                state.set_remote(rf)
            # A fresh sign-in supersedes any prior, not-yet-delivered "signed in"
            # announce (e.g. a re-login) so the watchdog can't replay a stale one.
            state.clear_signed_in()
            log.info("remote login started — code shown to user, expires in %ss", ttl)
            self._json(200, {"code": flow["code"], "verifyUrl": flow["verifyUrl"], "expiresIn": ttl})

        def _login_remote_poll(self) -> None:
            # Hold remote_lock across the whole transition: it serializes polls so
            # two in-flight requests (or the serve()-owned auto-poller) can't
            # double-redeem the one-shot custom token, and (paired with
            # _login_remote_start taking the same lock) guarantees we operate on the
            # current flow, not one a concurrent start superseded. The transition
            # itself is the module fn _advance_remote_flow, shared with the auto-poll
            # loop so both drive the flow identically.
            with state.remote_lock:
                if state.remote is None:
                    self._json(400, {"error": "no remote login in progress — POST /login/remote/start first"})
                    return
                transient = _advance_remote_flow(state)
                payload = self._remote_payload(state.remote)
                if transient:
                    payload["transient"] = transient
                self._json(200, payload)

        def _login_remote_pending(self) -> None:
            """Attach a pending research topic (+ chat origin) to a sign-in that is
            ALREADY in flight — for the case where the user started login, then fired
            a research before approving. Unlike /login/remote/start it never mints a
            new flow (which would invalidate the link they're about to approve); it
            just decorates the current pending flow so the post-login announce can
            offer to continue. A no-op 409 when nothing is pending.

            ⛔⛔ AND IT USED TO LET A SECOND CHAT STEAL THE FIRST ONE'S RESEARCH.
            Both fields were overwritten unconditionally, so: chat A fires a topic
            while signed out → chat B fires one before A's link is approved → B's
            post replaced A's topic AND A's origin. After sign-in only B's research
            ran, the announce went to B, and A's watchdog — armed, and told "I'll
            pick this up" — heard nothing, ever. A's research was simply gone, with
            no error anywhere: two 200s and one lost request.

            ⭐ SO OWNERSHIP IS FIRST-COME, and only against a DIFFERENT chat. The
            same chat re-posting is a person correcting themselves and still
            overwrites. A different chat is told plainly that this sign-in already
            carries somebody's research — which is true, and actionable (ask again
            once signed in). Losing a request in silence is the one outcome that is
            not available.
            """
            body = self._read_json()
            topic = body.get("pending_topic")
            origin = body.get("origin")
            with state.remote_lock:
                flow = state.remote
                if flow is None or flow.state != "pending":
                    self._json(409, {"error": "no sign-in in progress"})
                    return
                # ⛔⛔ REPLACING A HELD TOPIC REQUIRES PROVING YOU ARE THE CHAT
                # THAT SET IT, and the first version of this guard asked for far
                # less — it wanted an incoming origin AND a held origin AND a
                # mismatch. Cross-verification broke it in two ways, and the first
                # was worse than the bug it was written for:
                #
                #   • B posts with NO origin -> `isinstance(origin, dict)` is
                #     false, the guard is skipped, and B's TOPIC lands on A's
                #     ORIGIN. The announce then goes to chat A carrying chat B's
                #     research, and B's research is what starts. Reproduced
                #     against the live route, not reasoned about.
                #   • A held a topic with no origin (the legacy origin-less
                #     gateway) -> `isinstance(flow.origin, dict)` is false and B
                #     took both fields.
                #
                # So the test is the other way round now: something is held, and
                # the caller cannot PROVE it is the same conversation. Absent
                # proof, refuse. That costs an origin-less chat the ability to
                # correct its own topic — a real cost, and a smaller one than
                # handing somebody else's request to the wrong person in silence.
                if ((flow.pending_topic or "").strip()
                        and not _same_origin(flow.origin, origin)):
                    self._json(409, {"reason": "topic_taken",
                                     "error": "this sign-in is already carrying a "
                                              "research request from another chat — "
                                              "ask again once you're signed in"})
                    return
                if isinstance(topic, str):
                    flow.pending_topic = topic[:500]
                if isinstance(origin, dict):
                    flow.origin = origin
                self._json(200, {"ok": True})

        def _status(self) -> None:
            # Carry the pip-style AGENT update notice so the welcome / a bare /sr
            # can PROACTIVELY prompt "a newer agent is available" (cached 24h —
            # cheap). Backend updates are NOT surfaced here anymore: the app owns
            # that (the BE self-reports its update signal on its device-doc
            # heartbeat; the user runs `superresearch --update` on the Research PC).
            updates = {
                "agentUpdate": selfupdate.agent_update_available(),
            }
            sess = state.session
            if sess is None:
                body = {"authed": False, **updates}
                # Surface an in-flight remote sign-in so `agent status` / `/sr status`
                # can say "approve it in your browser — you'll connect automatically"
                # instead of a bare "not signed in" during the brief approve→capture
                # window the auto-poller closes (#848).
                flow = state.remote
                if flow is not None and flow.state in ("pending", "error", "expired"):
                    body["remoteLogin"] = flow.state
                self._json(200, body)
                return
            self._json(200, {"authed": True, "uid": sess.uid, "email": sess.email, **updates})

        def _icon(self, path: str) -> None:
            # Serve the bundled brand PNGs for the sign-in page's phase row.
            name = path.rsplit("/", 1)[-1]
            if name not in _ICON_FILES:
                self._json(404, {"error": "not found"})
                return
            f = _WEB_DIR / "icons" / name
            if not f.exists():
                self._json(404, {"error": "not found"})
                return
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(data)

        def _logout(self) -> None:
            sess = state.session
            if sess is not None:
                # Delete the #790 agent-session row BEFORE sess.logout() blanks
                # the token (we still need to mint one for the DELETE). Best-
                # effort — a failure just leaves a row that goes stale and the
                # app hides it. A clean logout removes the row entirely (unlike
                # the revoke path, which leaves a revoked row in place).
                try:
                    FirestoreRest(sess.id_token).delete_agent_session(
                        sess.uid, prefs.get_or_create_install_id()
                    )
                except Exception as e:
                    log.debug("agent session delete on logout failed (non-fatal): %s", type(e).__name__)
            # The device selection belongs to the account being logged out — drop
            # it so a later (possibly different) account doesn't inherit a stale
            # target it can't reach.
            _self_logout(state, sess)
            self._json(200, {"ok": True})

        def _researches(self) -> None:
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                rows = fs.list_researches(sess.uid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            # Drop the tokenized Storage audio URL from every row (same class as the
            # /updates + /research redaction) so the bridge never emits it anywhere.
            # cli's run list/podcast-pick read only title/status/phase (podcast-pick
            # goes through /updates), so this has zero consumer impact.
            self._json(200, {"researches": [_redact_doc_media(r) for r in rows]})

        def _decorate_devices(self, devs: list[dict[str, Any]], uid: str, selected: str | None):
            """Add the authoritative owned/selected flags the client can't infer.

            `owned` is computed against THIS session's uid (the CLI/skill route
            through the bridge and can't see sess.uid) — owner vs shared-to.
            """
            for d in devs:
                d["owned"] = d.get("ownerUid") == uid
                d["selected"] = d.get("id") == selected and selected is not None
                # Same freshness rule the run-routing path already applies to
                # these very rows. Without it every client shows a device list
                # with no indication of which machine is actually on, so a user
                # picks a sleeping one and their research silently never starts.
                d["online"] = _device_is_online(d)
            return devs

        def _devices(self) -> None:
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                devs = fs.list_devices(sess.uid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            selected = prefs.get_selected_device(sess.uid)
            self._decorate_devices(devs, sess.uid, selected)
            self._json(200, {"devices": devs, "selectedDeviceId": selected})

        def _device_current(self) -> None:
            """The currently-selected target device (decorated), or null."""
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            selected = prefs.get_selected_device(sess.uid)
            if not selected:
                self._json(200, {"device": None, "selectedDeviceId": None})
                return
            try:
                devs = fs.list_devices(sess.uid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            self._decorate_devices(devs, sess.uid, selected)
            match = next((d for d in devs if d.get("id") == selected), None)
            # Selection persisted but no longer reachable (un-shared/removed):
            # report it as stale rather than pretending it's live.
            self._json(200, {"device": match, "selectedDeviceId": selected,
                             "stale": match is None})

        def _device_select(self) -> None:
            body = self._read_json()
            device_id = (body.get("deviceId") or "").strip()
            if not device_id:
                self._json(400, {"error": "deviceId is required"})
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                devs = fs.list_devices(sess.uid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            match = next((d for d in devs if d.get("id") == device_id), None)
            if match is None:
                # Don't persist a device this account can't reach.
                self._json(404, {"error": "device not reachable by this account"})
                return
            prefs.set_selected_device(device_id, sess.uid)
            self._decorate_devices([match], sess.uid, device_id)
            log.info("selected device %s", device_id)
            self._json(200, {"ok": True, "device": match})

        def _device_pair(self) -> None:
            """Pair a device to this account by its PAIR CODE (the chat
            `device add <code>`). Forwards to the web app's /api/devices/claim
            as the signed-in user — identical security to pairing in the web
            app: the 8-char code only exists on the new device's screen, so
            possession of a valid code IS the authorization. First claim of a
            fresh device → this account becomes the OWNER; claiming an
            already-owned device → this account becomes a SHARER. The app
            route enforces format, rate limits, expiry, and the revoked-sharer
            blocklist — errors are relayed for the chat client to word."""
            code = (self._read_json().get("code") or "").strip()
            if not code:
                self._json(400, {"error": "code is required"})
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            status, body = _fe_api_post(sess, "/api/devices/claim", {"code": code})
            if status == 0:
                self._json(502, body)
                return
            if status != 200 or not body.get("ok"):
                self._json(status if status >= 400 else 502,
                           {"error": body.get("error") or f"claim failed (HTTP {status})",
                            "retryAfterMs": body.get("retryAfterMs")})
                return
            device_id = body.get("deviceId") or ""
            # Auto-select the new device when nothing is selected yet, so a
            # zero-device user can fire research immediately after pairing.
            auto_selected = False
            if device_id and not prefs.get_selected_device(sess.uid):
                prefs.set_selected_device(device_id, sess.uid)
                auto_selected = True
            # Name it for the chat reply (best-effort — a just-paired device
            # may take a heartbeat to appear in the list).
            name = None
            try:
                devs = fs.list_devices(sess.uid)
                match = next((d for d in devs if d.get("id") == device_id), None)
                if match:
                    name = match.get("name") or match.get("hostname")
            except Exception:
                pass
            log.info("device pair: %s (%s)", device_id, body.get("action"))
            self._json(200, {"ok": True, "action": body.get("action"),
                             "deviceId": device_id, "deviceName": name,
                             "selected": auto_selected})

        def _device_remove(self) -> None:
            """Unlink a device from this account (the chat `device remove`).
            Forwards to the web app's /api/devices/unpair-self, which branches
            on the caller's relationship: OWNER → owner-unlink (the device doc
            + its install stay alive; re-pairable with its code — nothing is
            destroyed), SHARER → removes themself from sharedWith. The chat
            client confirms with the user BEFORE calling this."""
            device_id = (self._read_json().get("deviceId") or "").strip()
            if not device_id:
                self._json(400, {"error": "deviceId is required"})
                return
            acct = self._account()
            if acct is None:
                return
            sess, _fs = acct
            status, body = _fe_api_post(sess, "/api/devices/unpair-self", {"deviceId": device_id})
            if status == 0:
                self._json(502, body)
                return
            if status != 200 or not body.get("ok"):
                self._json(status if status >= 400 else 502,
                           {"error": body.get("error") or f"unlink failed (HTTP {status})",
                            "retryAfterMs": body.get("retryAfterMs")})
                return
            # Don't leave a dangling selection pointing at the removed device.
            if prefs.get_selected_device(sess.uid) == device_id:
                prefs.clear_selected_device()
            log.info("device remove: %s (%s)", device_id, body.get("action"))
            self._json(200, {"ok": True, "action": body.get("action"), "deviceId": device_id})

        def _resolve_device(self, body: dict[str, Any], sess: AccountSession,
                            fs: FirestoreRest) -> str | None:
            """Resolve the target device for a run: explicit body.deviceId →
            persisted selection (re-validated reachable) → the sole device → the
            sole ONLINE device when there are several. Sends an error and returns
            None when it genuinely can't resolve (so the caller just returns).

            Every error body carries a machine-readable ``reason`` so the client
            (sr.py) can tell the cases apart WITHOUT parsing English — the run
            path routes a `no_devices` to the pair/install prompt, but a
            `no_selection`/`stale_selection` to a 'pick which computer' ask
            (the account HAS computers; it just needs to be told which). The old
            single "no device …" substring collided across these, so a
            multi-device account got the wrong "install a backend here" prompt."""
            device_id = (body.get("deviceId") or "").strip()
            if device_id:
                return device_id  # explicit wins; membership enforced at enqueue
            # No explicit device — list once to validate the selection / auto-pick.
            try:
                devs = fs.list_devices(sess.uid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return None
            except FirestoreError as e:
                self._firestore_502(e)
                return None
            # ⭐ ONE DECISION, TWO CONSUMERS: `_pick_device_from` holds the rungs
            # (selection → drop a STALE selection → sole device → the sole ONLINE
            # device → ask which). This branch's only job is turning the verdict
            # into an HTTP body; the sign-in auto-start turns the same verdict into
            # announce hints. They used to be two pickers with different rungs.
            #
            # A saved selection that's no longer a pair-confirmed member
            # (removed/unlinked in the app) is STALE: drop it so we never enqueue to
            # a phantom device, then fall THROUGH to the same auto-pick a fresh run
            # gets. Only ask "pick another" when there's genuinely more than one
            # candidate — a single remaining device or a sole online one is routed
            # seamlessly, and zero devices routes to pairing (not a "pick from an
            # empty list" dead end). Pre-0.1.27 this returned stale_selection
            # immediately, so a single-device account was told to "pick another" from
            # a list of one.
            device_id, reason, stale = _pick_device_from(
                devs, prefs.get_selected_device(sess.uid))
            if stale:
                prefs.clear_selected_device()
            if reason == "no_devices":
                # Relayed verbatim into chat — make it the next step, not a dead end.
                self._json(400, {"reason": "no_devices",
                                 "error": "no devices yet — on the computer running "
                                          "Super Research, grab the pair code from its "
                                          "screen and add it here (device add <code>)"})
                return None
            if device_id:
                return device_id
            # Ask which. A stale selection keeps its own reason + message so the user
            # knows WHY they're being asked (their last computer isn't reachable); a
            # never-selected multi-device account gets the plain no_selection ask.
            if reason == "stale_selection":
                self._json(409, {"reason": "stale_selection",
                                 "error": "the computer you last used isn't reachable "
                                          "anymore — pick another from the device list",
                                 "devices": [_device_descriptor(d) for d in devs]})
                return None
            self._json(400, {"reason": "no_selection",
                             "error": "no device selected — pick one from the device list",
                             "devices": [_device_descriptor(d) for d in devs]})
            return None

        # ── send logs ────────────────────────────────────────────────────
        def _log_device(self, body: dict[str, Any], sess: AccountSession,
                        fs: FirestoreRest) -> dict[str, Any] | None:
            """The machine a log request is aimed at, as a decorated row.

            Reuses `_resolve_device` so "which computer?" reads identically to
            the run path — the same `reason` codes, the same auto-picks.

            ⛔ THEN IT INSISTS ON THE ROW, which the run path deliberately does
            not: there, an explicit deviceId is passed through and membership is
            enforced when the queue write lands. Here the write is a device
            command, and a non-member's create is refused by the rule as a bare
            403 — which reaches the person as "could not reach the research
            store", a sentence about US when the truth is about THEM. And the
            row is needed anyway: ownership decides what may be asked for.
            """
            device_id = self._resolve_device(body, sess, fs)
            if device_id is None:
                return None  # _resolve_device already answered
            try:
                devs = fs.list_devices(sess.uid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return None
            except FirestoreError as e:
                self._firestore_502(e)
                return None
            match = next((d for d in devs if d.get("id") == device_id), None)
            if match is None:
                self._json(404, {"reason": "not_a_member",
                                 "error": "that computer isn't on your account — "
                                          "add it, or pick one from the device list"})
                return None
            self._decorate_devices([match], sess.uid,
                                   prefs.get_selected_device(sess.uid))
            return match

        def _log_runs(self) -> None:
            """The runs a machine still holds logs for, FOR THIS PERSON, with
            the titles joined from this account's own research documents.

            ⭐⭐ THE MACHINE SENDS IDS AND WE SUPPLY THE WORDS. No topic and no
            title exists anywhere in a run folder, on purpose — so the list
            arrives as folder names plus a researchId, and the words come from
            documents this account already holds. Nothing about what anybody
            researched has to leave that computer for this list to read like a
            list of researches.
            """
            acct = self._account()
            if acct is None:
                return
            qs = parse_qs((self.path.split("?", 1) + [""])[1])
            body = {"deviceId": (qs.get("deviceId") or [""])[0].strip()}
            sess, fs = acct
            dev = self._log_device(body, sess, fs)
            if dev is None:
                return
            device_id = str(dev.get("id") or "")
            try:
                held = fs.held_runs(sess.uid, device_id)
                researches = fs.list_researches(sess.uid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            # ⛔⛔ NEVER PUBLISHED IS NOT NONE HELD, and the whole value of this
            # route is that a caller can tell them apart. `published: false`
            # means the document is absent — a machine on an older build, a rule
            # that has not reached it, or one that has simply never run anything
            # of this person's. `published: true` with an empty list is the
            # machine saying "I hold nothing of yours", which is a sentence
            # worth printing. Printing the first one as the second accuses a
            # computer of having lost logs it may be holding right now.
            titles = {r.get("id"): (r.get("title") or r.get("topic") or "")
                      for r in researches}
            rows = []
            for item in (held or {}).get("runs", []) or []:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    continue
                rid = item.get("researchId") if isinstance(item.get("researchId"), str) else ""
                rows.append({
                    "name": name,
                    "researchId": rid,
                    # ⭐ A run whose research document is gone from this tree
                    # KEEPS ITS ROW. The logs are still on that disk and still
                    # worth sending; it simply reads by its date instead.
                    "title": titles.get(rid, ""),
                    "startedUtc": item.get("startedUtc") or "",
                    "status": item.get("status") or "unknown",
                    "sizeBytes": item.get("sizeBytes") or 0,
                    "attempt": item.get("attempt") or 0,
                })
            self._json(200, {
                "deviceId": device_id,
                "deviceName": dev.get("name") or dev.get("hostname") or device_id,
                "owned": bool(dev.get("owned")),
                "online": dev.get("online"),
                "published": held is not None,
                "runs": rows,
                "truncated": bool((held or {}).get("truncated")),
                "updatedAt": (held or {}).get("updatedAt") or "",
            })

        def _log_send(self) -> None:
            """Ask a machine to package logs and upload them under a support code.

            ⛔⛔ CONSENT IS CARRIED, NOT MANUFACTURED. The machine refuses a
            request that does not claim it, and this route refuses to make the
            claim on a caller's behalf — the flag has to arrive in the body,
            because it is a statement that a person was SHOWN what leaves the
            computer, and this file has shown them nothing. The surface that
            printed the list is the only place that can honestly set it.
            """
            body = self._read_json()
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            if body.get("consent") is not True:
                self._json(400, {"reason": "no_consent",
                                 "error": "logs are only sent after the person has been "
                                          "shown what leaves the computer"})
                return
            raw = body.get("runNames")
            if not isinstance(raw, list) or len(raw) > _SEND_LOGS_MAX_NAMES:
                self._json(400, {"reason": "bad_selection",
                                 "error": "runNames must be a list of run names "
                                          f"(at most {_SEND_LOGS_MAX_NAMES})"})
                return
            names: list[str] = []
            for item in raw:
                # ⛔ REFUSE, NEVER DROP. A name this bridge quietly discarded
                # would be a run the person ticked and did not get, reported as
                # a success — the one direction a log request must not fail in.
                if not isinstance(item, str) or not _RUN_NAME_RE.match(item):
                    self._json(400, {"reason": "bad_selection",
                                     "error": "one of the run names isn't a run name"})
                    return
                names.append(item)
            include_machine = body.get("includeMachine") is True
            dev = self._log_device(body, sess, fs)
            if dev is None:
                return
            device_id = str(dev.get("id") or "")
            # ⛔⛔ REFUSED HERE RATHER THAN QUIETLY DOWNGRADED, and the machine
            # still ANDs it with ownership regardless. That material — the
            # pairing and sign-in sessions, the raw device tails — is every run
            # the computer has ever done for everyone who uses it, so a sharer
            # asking for it gets nothing extra no matter what this bridge does.
            # What this bridge decides is whether they are TOLD. A fleet box is
            # shared by design, so silently sending a smaller bundle than the
            # one someone asked for would be the normal case, not the edge one.
            if include_machine and not dev.get("owned"):
                self._json(403, {"reason": "machine_logs_owner_only",
                                 "error": "that computer's own logs belong to whoever "
                                          "owns it — ask again without them, and you "
                                          "will still get every run of yours it holds"})
                return
            # ⛔ NOBODY MAY BUILD AN EMPTY ARCHIVE. The machine refuses this too,
            # and refusing here as well is what turns a round trip plus a row
            # nobody is watching into an immediate sentence. A zip of three JSON
            # files handed back under a support code is worse than a refusal,
            # because the person believes they have sent something.
            if not names and not include_machine:
                self._json(400, {"reason": "nothing_selected",
                                 "error": "nothing was chosen to send"})
                return
            code = _mint_support_code()
            request_id = uuid.uuid4().hex
            try:
                command_id = fs.write_device_command(
                    device_id, _SEND_LOGS_ACTION, uid=sess.uid,
                    extra={"code": code, "requestId": request_id,
                           "consent": True, "runNames": names,
                           # ⛔ ALWAYS ON THE WIRE, never omitted when false. The
                           # machine reads a missing field as "not asked for" —
                           # the safe direction — but an absent field and an
                           # explicit False would then be indistinguishable, and
                           # the row this produces records what was chosen.
                           "includeMachine": include_machine})
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            log.info("send-logs requested on %s (%d runs, machine=%s)",
                     device_id, len(names), include_machine)
            self._json(200, {"ok": True, "code": code, "requestId": request_id,
                             "commandId": command_id, "deviceId": device_id,
                             "deviceName": dev.get("name") or dev.get("hostname") or device_id,
                             "runCount": len(names),
                             "includeMachine": include_machine})

        def _log_bundle(self) -> None:
            """One support bundle's row — what the machine has done with a code.

            ⛔ ABSENT IS REPORTED AS ABSENT. Worker 1 deletes the command before
            dispatching it, so there is a real window in which the request is
            gone and the row has not appeared; on a machine too old to
            understand the request that window never closes. `row: null` is that
            state, and a caller decides it has waited long enough — this route
            never guesses on its behalf by calling it a failure.
            """
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            qs = parse_qs((self.path.split("?", 1) + [""])[1])
            code = (qs.get("code") or [""])[0].strip().upper()
            if not _SUPPORT_CODE_RE.match(code):
                self._json(400, {"error": "that isn't a support code"})
                return
            try:
                row = fs.get_log_bundle(sess.uid, code)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            self._json(200, {"code": code, "row": row})

        def _log_agent_log(self) -> None:
            """Send THIS host's own agent log up beside a bundle already on its way.

            ⛔⛔ THE ORDER IS NOT NEGOTIABLE, and this route enforces it rather than
            trusting the caller. The app's Clear-logs button finds objects by listing
            each ROW's support-code folder — it does not scan the bucket — so an
            object written before the machine's row lands, or under a code no row
            names, is a readable log the privacy button can never reach. The
            receiving route re-checks the row for the same reason; this check is here
            so a caller gets a sentence instead of a 404 from somewhere else.

            ⛔ AND IT IS NEVER FATAL TO THE SEND IT ACCOMPANIES. The machine's
            bundle is already gone by the time this runs. A failure here is reported
            and nothing else: the person is told the agent's log did not go, which
            is true and actionable, and the support code they were given still works.
            """
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            body = self._read_json()
            code = str(body.get("code") or "").strip().upper()
            if not _SUPPORT_CODE_RE.match(code):
                self._json(400, {"error": "that isn't a support code"})
                return
            try:
                row = fs.get_log_bundle(sess.uid, code)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            if not isinstance(row, dict):
                # The machine has not answered yet. Not an error state — the caller
                # waits and asks again, exactly as it does for the bundle itself.
                self._json(409, {"reason": "bundle_not_landed",
                                 "error": "that computer hasn't confirmed its own "
                                          "logs yet — try again in a moment"})
                return
            device_id = str(row.get("deviceId") or "")
            if not device_id:
                self._json(409, {"reason": "bundle_not_landed",
                                 "error": "that bundle has no computer recorded "
                                          "against it yet"})
                return
            blob = _read_agent_log_tail()
            if not blob:
                # ⭐ Reported as a fact, not a failure. An agent whose log is empty
                # has nothing to say, and inventing a zero-byte file would leave
                # something claiming otherwise.
                self._json(200, {"ok": True, "sent": False, "reason": "empty",
                                 "path": str(config.log_path())})
                return
            status, reply = _fe_api_post_bytes(
                sess, "/api/logs/agent-log", blob, "text/plain; charset=utf-8",
                {"x-support-code": code, "x-device-id": device_id},
            )
            if status != 200:
                log.warning("agent-log upload for %s failed: HTTP %s %s",
                            code, status, reply.get("error", ""))
                self._json(502, {"reason": "agent_log_not_sent",
                                 "error": "your computer's own agent log could not "
                                          "be sent — the rest of the bundle is "
                                          "unaffected"})
                return
            log.info("agent log sent for %s (%s bytes)", code, len(blob))
            self._json(200, {"ok": True, "sent": bool(reply.get("stored")),
                             "bytes": len(blob)})

        def _research(self) -> None:
            body = self._read_json()
            topic = (body.get("topic") or "").strip()
            if not topic:
                self._json(400, {"error": "topic is required"})
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            device_id = self._resolve_device(body, sess, fs)
            if device_id is None:
                return  # _resolve_device already sent the error
            # Honor the account's saved pipeline Settings; explicit chat flags
            # (--no-video / --no-email) override. The chat origin (sr.py reads it
            # from the gateway's per-session env) tags the doc so the streaming
            # watchdog can scope updates to this chat. Same write path as the
            # sign-in auto-start (`_enqueue_research_run`), so the two can't drift.
            chat_cfg = body.get("config") if isinstance(body.get("config"), dict) else {}
            cfg = _resolve_run_config(fs, sess, chat_cfg)
            origin = _clean_origin(body.get("origin"))
            try:
                rid, qid = _enqueue_research_run(fs, sess, topic=topic,
                                                 device_id=device_id, cfg=cfg, origin=origin)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            except _EnqueueFailed as ef:
                if ef.revoked:
                    self._json(401, {"error": "session revoked — run /login again"})
                else:
                    self._firestore_502(ef.original)
                return
            self._json(200, {"runId": rid, "queueId": qid, "deviceId": device_id})

        def _research_status(self, rid: str) -> None:
            """Point-in-time status of one run (the chat /sr-status). Streaming is P4."""
            rid = rid.strip("/")
            if not _RID_RE.match(rid):
                self._json(404, {"error": "run not found"})  # rejects ../, %2f, etc.
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                doc = fs.get_research(sess.uid, rid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            if doc is None:
                self._json(404, {"error": "run not found"})
                return
            # Mint the permanent SR shares for any COMPLETE phase whose artifact
            # exists but isn't minted yet, so a MANUAL `status` returns the same
            # per-phase links the streaming watchdog does — the 🔒 SR shares for the
            # brief / reports / podcast (never the raw chatgpt/gemini/claude pages),
            # alongside the 🔗 NotebookLM / YouTube / Doc platform links. Idempotent +
            # best-effort (mints only docTypes whose content already exists; falls
            # back to whatever's already minted on failure).
            sr = _sr_links(doc)
            done = _completed_phases(doc)
            if _sr_mint_gap(sr, _platform_links(doc), done):
                fresh = _mint_sr(sess, rid, doc.get("title") or doc.get("topic") or "")
                if fresh:
                    sr = {**sr, **fresh}
            # `events` = the flattened, ordered per-phase links a streamer dedups
            # by kind (the raw `links` map is also returned for full fidelity).
            # `srLinks` = the permanent share links (the ones in the delivered doc).
            # `phaseUpdates` = the per-phase plan (permanent SR links + platform-only
            # links for NotebookLM/YouTube/final Doc) — what `status` should render.
            self._json(200, {
                # Redact the tokenized Storage audio URL from both the raw doc and
                # the flattened events — it must never reach a chat client (the
                # media itself is served by /research/<rid>/podcast as a local file).
                "research": _redact_doc_media(doc),
                "events": _redact_media_urls(runview.flatten_links(doc.get("links"))),
                "srLinks": sr,
                "phaseUpdates": _phase_updates(doc, sr),
            })

        def _research_podcast(self, rid: str) -> None:
            """Resolve a run's NotebookLM audio → a local FILE the runtime sends as
            a native, forwardable audio message (the chat /sr-podcast).

            Native-audio delivery is FILE-based on purpose: every chat channel can
            attach a local file, and (unlike handing back the URL) the long-lived
            Storage download token never leaves the host — it is not in the
            response, so it can't leak into chat history. sr.py stays loopback-only;
            the bridge (which already owns the network + the session) does the fetch.
            """
            rid = rid.strip("/")
            if not _RID_RE.match(rid):
                self._json(404, {"error": "run not found"})  # rejects ../, %2f, etc.
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                doc = fs.get_research(sess.uid, rid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            if doc is None:
                self._json(404, {"error": "run not found"})
                return
            audio_url = _audio_file_url(doc.get("links"))
            if not audio_url:
                # No media file yet: tell apart "still cooking" from "this run will
                # never make one" (audio phase skipped / already terminal).
                if runview.is_terminal(doc.get("status")):
                    self._json(409, {"error": "this run has no podcast audio (the audio phase didn't produce one)"})
                else:
                    self._json(409, {"error": "the podcast audio isn't ready yet — try again once the audio phase finishes"})
                return
            title = doc.get("title") or doc.get("topic") or rid
            ext, mime = _audio_ext_and_mime(audio_url)
            try:
                path, size = _download_podcast_audio(
                    audio_url, config.store_dir() / _PODCAST_DIR_NAME, rid
                )
            except (requests.RequestException, ValueError, OSError) as e:
                # Never log `e`: a requests error message embeds the full tokenized
                # Storage URL (…?alt=media&token=…). Log only the exception type.
                log.warning("podcast download failed for %s (%s)", rid, type(e).__name__)
                self._json(502, {"error": "couldn't fetch the podcast audio — try again"})
                return
            # A file past the platform ceiling is REFUSED at send time and the
            # runtime silently degrades to printing the path as text — so shrink it
            # here rather than hand back something that can't be delivered. The
            # ceiling belongs to the destination chat (?platform=…), not to us.
            ceiling = _delivery_ceiling(
                (parse_qs(urlsplit(self.path).query).get("platform") or [""])[0])
            if size > ceiling:
                smaller = _shrink_for_delivery(path, ceiling) if ceiling > 0 else None
                if smaller is None:
                    # Can't be made deliverable — answer with the permanent link so
                    # the user still gets the podcast, instead of a dead path. MINT it
                    # if it isn't on the doc yet: `_sr_links` only READS what's already
                    # there, and the podcast share is written by the P5 delivery step —
                    # so a run asked about before P5 (or started from the web app) would
                    # otherwise hand back an empty link, i.e. nothing at all.
                    sr = _sr_links(doc)
                    if not sr.get("podcast"):
                        fresh = _mint_sr(sess, rid, title)
                        if fresh:
                            sr = {**sr, **fresh}
                    log.info("podcast too large to send for %s (%d bytes) — link only",
                             rid, size)
                    self._json(200, {
                        "ready": True,
                        "runId": rid,
                        "title": title,
                        "tooLarge": True,
                        "sizeBytes": size,
                        "shareUrl": sr.get("podcast") or "",
                    })
                    return
                log.info("podcast shrunk for delivery for %s (%d → %d bytes)",
                         rid, size, smaller.stat().st_size)
                path, ext, mime = smaller, ".mp3", "audio/mpeg"
                size = smaller.stat().st_size
            # Serve under a human, title-based basename (the chat shows a
            # forwarded file's basename, not the ugly rid-hashed cache name).
            delivery = _podcast_delivery_copy(path, title, ext)
            log.info("podcast audio ready for %s (%d bytes)", rid, size)
            self._json(200, {
                "ready": True,
                "runId": rid,
                "title": title,
                "localPath": str(delivery),
                "filename": _safe_filename(title, ext),
                "mime": mime,
                "sizeBytes": size,
            })

        def _updates(self) -> None:
            """Account-wide streaming snapshot: recent runs + their current
            flattened links, for a cron to diff per (runId, kind). ?active=1
            restricts to in-flight runs; ?limit=N bounds the window (default 20)."""
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            qs = parse_qs(urlsplit(self.path).query)
            active_only = qs.get("active", ["0"])[0] in ("1", "true", "yes")
            # ?via=agent (the streaming watchdog): restrict to runs STARTED via
            # the agent (viaAgent) so web-app runs don't clutter the chat, and
            # compute per-phase updates (lazily minting the permanent SR links).
            via_agent = qs.get("via", [""])[0] == "agent"
            # ?platform=…&chat=… (a PER-CHAT watchdog): further restrict to runs
            # fired FROM that chat (matched on the doc's chatOrigin) so a run
            # started in one chat streams back only to that chat. Both must be
            # present to scope; otherwise via=agent returns every agent run (the
            # single-chat / account-wide case — already correct for one chat).
            want_platform = (qs.get("platform", [""])[0] or "").strip().lower()
            want_chat = (qs.get("chat", [""])[0] or "").strip()
            scope_chat = bool(via_agent and want_platform and want_chat)
            try:
                limit = max(1, min(int(qs.get("limit", ["20"])[0]), 100))
            except ValueError:
                limit = 20
            try:
                rows = fs.list_researches(sess.uid, page_size=limit)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            # NOTE: the active filter is applied AFTER the newest-`limit` window,
            # so active=1 scans only the newest `limit` runs. That's fine in
            # practice — runs are createdAt-desc and an in-flight run is among the
            # newest — but a long-buried still-active run could fall outside it.
            runs = []
            for r in rows:
                status = r.get("status")
                # Watchdog scope: only runs the user started via the agent.
                if via_agent and not r.get("viaAgent"):
                    continue
                # Per-chat scope: only runs fired FROM this watchdog's chat.
                # Skip BEFORE the phase-update minting below so we never mint a
                # permanent SR link on behalf of another chat's run.
                if scope_chat:
                    co = r.get("chatOrigin")
                    if not (isinstance(co, dict)
                            and (co.get("platform") or "").strip().lower() == want_platform
                            and (co.get("chat_id") or "").strip() == want_chat):
                        continue
                attention = _attention_text(r)
                needs = attention is not None or status in _ATTENTION_STATUSES
                # active=1 keeps the in-flight runs AND any run that needs the
                # user — an errored/paused run isn't "ongoing" but is exactly what
                # a chat poller must surface, so it must not be filtered out.
                if active_only and status not in ("queued", "ongoing") and not needs:
                    continue
                sr = _sr_links(r)
                phase_updates: list = []
                if via_agent:
                    done = _completed_phases(r)
                    if _sr_mint_gap(sr, _platform_links(r), done):
                        fresh = _mint_sr(sess, r.get("id"), r.get("title") or r.get("topic") or "")
                        if fresh:
                            sr = {**sr, **fresh}
                    phase_updates = _phase_updates(r, sr)
                runs.append({
                    "runId": r.get("id"),
                    "title": r.get("title") or r.get("topic"),
                    "topic": r.get("topic"),
                    "status": status,
                    "phase": r.get("phase"),
                    # A queued run's place in line — sr.py renders "queued —
                    # #N in line" from this (#890; absent once the run starts).
                    "queuePosition": r.get("queuePosition"),
                    "updatedAt": r.get("updatedAt"),
                    # Tokenized Storage audio URL redacted (kind marker kept for the
                    # podcast run-pick); it must never reach a chat client.
                    "links": _redact_media_urls(runview.flatten_links(r.get("links"))),
                    "srLinks": sr,
                    "phaseUpdates": phase_updates,
                    # The live pipeline config (which phases are on/off) so a chat
                    # client can answer "is video/email/podcast skipped?" — the FE
                    # toggle writes these under pipelineConfig on the run doc.
                    "pipelineConfig": r.get("pipelineConfig"),
                    "chatOrigin": r.get("chatOrigin"),
                    # Agent-fired flag — sr.py's watchdog self-heal only re-arms
                    # for runs the watchdog would actually stream (via-agent).
                    "viaAgent": bool(r.get("viaAgent")),
                    "needsAttention": needs,
                    "attention": attention,
                })
            out: dict[str, Any] = {"runs": runs}
            # The event this request took, if any — restored on a failed send.
            taken: dict | None = None
            # One-shot "just signed in" announce for the chat watchdog. Only the
            # watchdog reads it (it always sets ?via=agent) — so an ordinary client
            # /updates call can't silently consume it. Take-and-clear is atomic; if
            # this query's scope doesn't own the event, put it back for the watchdog
            # that does. Delivered to the chat that started the sign-in (origin
            # match), or to any agent watchdog if it carried no origin.
            if via_agent:
                # TAKE, atomically — and the caller puts it back if the send fails.
                # See `take_signed_in` for why this is the third shape of this and
                # the first that is both exactly-once and lossless.
                ev = state.take_signed_in(sess.uid)
                if isinstance(ev, dict):
                    ev_origin = ev.get("origin")
                    # An ORIGIN-LESS sign-in event (a connect-CLI / --pair login that
                    # confirms in the TERMINAL, started from no chat) must NOT be handed
                    # to a SCOPED chat watchdog: with several channels armed
                    # (telegram/whatsapp/sms), whichever polled first would announce
                    # "signed in" in the WRONG chat. Deliver it only to the legacy
                    # account-wide (unscoped) watchdog; a scoped watchdog announces ONLY
                    # the sign-in its own chat initiated (origin match).
                    deliver = (
                        (not ev_origin and not scope_chat)
                        or (scope_chat and isinstance(ev_origin, dict)
                            and (ev_origin.get("platform") or "").strip().lower() == want_platform
                            and (ev_origin.get("chat_id") or "").strip() == want_chat)
                    )
                    if deliver:
                        out["signedIn"] = {
                            "ts": ev.get("ts"),
                            "email": ev.get("email") or "",
                            "pendingTopic": ev.get("pendingTopic") or "",
                            # Sign-in auto-start hints (the bridge started/blocked the
                            # pending research server-side; the watchdog renders the
                            # right line). Absent on a plain sign-in.
                            "autoStarted": bool(ev.get("autoStarted")),
                            "needsDevice": bool(ev.get("needsDevice")),
                            "runId": ev.get("runId") or "",
                            "deviceName": ev.get("deviceName") or "",
                            "topic": ev.get("topic") or "",
                            # The FOURTH outcome: the account has several usable
                            # computers and the sign-in auto-start could not choose.
                            # Distinct from `needsDevice` (which means there is no
                            # research computer at all) and — the point of it —
                            # distinct from an ERROR, which the old empty-dict hint
                            # made indistinguishable from this.
                            "needsDeviceChoice": bool(ev.get("needsDeviceChoice")),
                            "devices": ev.get("devices") or [],
                            # WHY it is asking: the computer they last used is gone,
                            # or they simply never picked one. The run path has told
                            # those apart since 0.1.27; this one could not.
                            "staleSelection": bool(ev.get("staleSelection")),
                        }
                        # ⛔⛔ CLEARED AFTER THE RESPONSE IS WRITTEN, NOT BEFORE.
                        # This was the wrong way round on the first pass, and it
                        # quietly voided the whole point of replacing take with
                        # peek: `peek_signed_in`'s own docstring promises "peek,
                        # write the response, then clear", and the code cleared and
                        # THEN wrote. Anything that killed the tick in between — a
                        # dropped connection, the poller's 30-second timeout — lost
                        # the announce exactly as the take-and-clear it replaced
                        # did. Found by cross-verification, and it is the same
                        # commit-before-you-speak shape this stretch fixed in the
                        # watchdog, reintroduced one layer up while fixing it there.
                        taken = ev
                    else:
                        # Not this chat's — put it straight back for the watchdog
                        # that owns it.
                        state.set_signed_in(ev)
            try:
                self._json(200, out)
            except Exception:
                # ⛔ THE SEND FAILED, SO THE ANNOUNCE WAS NOT DELIVERED. Put it back
                # rather than let a dropped connection destroy it — that loss is the
                # whole defect this stretch set out to fix.
                if taken is not None:
                    state.set_signed_in(taken)
                raise

        def _research_cancel(self, rid: str) -> None:
            """Cancel a run (the chat /sr-cancel): one action:"cancel" to the run's
            device queue — the BE drops it if queued, or stops it if running."""
            rid = rid.strip("/")
            if not _RID_RE.match(rid):
                self._json(404, {"error": "run not found"})  # rejects ../, %2f, etc.
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                doc = fs.get_research(sess.uid, rid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            if doc is None:
                self._json(404, {"error": "run not found"})
                return
            device_id = (doc.get("deviceId") or "").strip()
            if not device_id:
                self._json(409, {"error": "run has no device — nothing to cancel"})
                return
            try:
                qid = fs.enqueue_cancel(device_id, uid=sess.uid, research_id=rid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            log.info("cancel requested for run %s on device %s", rid, device_id)
            self._json(200, {"ok": True, "runId": rid, "queueId": qid, "deviceId": device_id})

        def _research_stop(self, rid: str) -> None:
            """Gracefully STOP a run (the chat /sr stop) — the loopback twin of the
            web app's Stop button. A RUNNING run gets a per-run action:"stop"
            command (stops at the current phase, KEEPS partial results + the chat);
            a still-QUEUED run gets a device-queue cancel carrying ownerControl:"stop"
            (the BE flips it to a preserved "stopped" entry, no cascade-delete). It
            NEVER sets `cancelled` — that flag (the legacy /cancel) is what deletes
            the chat on close, which is exactly what we avoid here."""
            rid = rid.strip("/")
            if not _RID_RE.match(rid):
                self._json(404, {"error": "run not found"})
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                doc = fs.get_research(sess.uid, rid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            if doc is None:
                self._json(404, {"error": "run not found"})
                return
            status = (doc.get("status") or "").strip()
            if runview.is_terminal(status):
                self._json(200, {"ok": True, "runId": rid, "status": status, "alreadyDone": True})
                return
            device_id = (doc.get("deviceId") or "").strip()
            if not device_id:
                self._json(409, {"error": "run has no device — nothing to stop"})
                return
            try:
                if status == "queued":
                    # Not started yet → no per-run command listener is attached.
                    # Route through the always-on device-queue listener with
                    # ownerControl:"stop" so the run is PRESERVED (kept in the
                    # listing, chat intact), not purged like a destructive cancel.
                    fs.enqueue_cancel(device_id, uid=sess.uid, research_id=rid, owner_control="stop")
                    mode = "queued"
                else:
                    # Running/paused → also signal the per-run command listener so the
                    # BE tears the browser down + exits cleanly when it consumes it.
                    fs.write_command(sess.uid, rid, "stop", device_id=device_id)
                    mode = "running"
                # AUTHORITATIVE terminal flip — the loopback twin of the web app's Stop
                # button, which writes status:"stopped" to the doc DIRECTLY. The command
                # alone is fragile: a run paused at a decision gate (or a per-run listener
                # whose cursor is burned / on another worker) may never consume it, so it
                # stays PAUSED — that was the bug ("Stopped" in chat, still paused in the
                # app). NON-destructive: status:"stopped" with NO `cancelled`, so partial
                # results + the chat survive (mirrors _owner_control_patch oc="stop").
                # Clearing pendingDecision dismisses the gate banner so the run reads
                # terminal even if the gate coroutine is wedged.
                fs.update_research(sess.uid, rid, {
                    "status": "stopped",
                    "stoppedAt": int(time.time() * 1000),
                    # "agent_stop" (not "owner_stop") so the web app attributes
                    # this as the user's OWN stop from their agent chat and shows
                    # "Stopped from your agent" — distinct from the device-owner
                    # "owner_stop"/"owner_cancel" sharer-popup case. Both still
                    # flip the run terminal; only the chat copy differs.
                    "stoppedBy": "agent_stop",
                    "summary": "Stopped",
                }, delete_fields=["queuePosition", "queuedBehindRunId",
                                  "queuedBehindTitle", "pendingDecision"])
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            log.info("authoritative stop for run %s on device %s (%s → stopped)", rid, device_id, mode)
            self._json(200, {"ok": True, "runId": rid, "deviceId": device_id, "status": "stopped", "mode": mode})

        def _write_run_command(self, rid: str, action: str) -> None:
            """Shared: write a per-run command (pause/resume) for a non-terminal run.
            Unlike stop, pause/resume are best-effort + RESUMABLE — the BE owns the
            paused state (it writes status:"paused" on consume), so we do NOT write the
            doc authoritatively here. 404 unknown run, 409 if already finished."""
            rid = rid.strip("/")
            if not _RID_RE.match(rid):
                self._json(404, {"error": "run not found"})
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                doc = fs.get_research(sess.uid, rid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            if doc is None:
                self._json(404, {"error": "run not found"})
                return
            if runview.is_terminal((doc.get("status") or "").strip()):
                self._json(409, {"error": "run already finished"})
                return
            device_id = (doc.get("deviceId") or "").strip()
            if not device_id:
                self._json(409, {"error": "run has no device"})
                return
            try:
                fs.write_command(sess.uid, rid, action, device_id=device_id)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            log.info("%s requested for run %s on device %s", action, rid, device_id)
            self._json(200, {"ok": True, "runId": rid, "deviceId": device_id})

        def _research_pause(self, rid: str) -> None:
            """Pause a RUNNING run (resumable). BE action:"pause" → request_pause."""
            self._write_run_command(rid, "pause")

        def _research_resume(self, rid: str) -> None:
            """Resume a PAUSED run. BE action:"resume" → request_resume."""
            self._write_run_command(rid, "resume")

        def _research_resolve(self, rid: str) -> None:
            """Resolve a BLOCKED run from chat (C1): read its pendingDecision and
            write the matching per-run command for the body's ``intent`` — "retry"
            resumes (retry_phase / agent_decision:retry / resume), "skip" moves
            past it (skip_phase / skip_agent / skip_init_verify) — the same writes
            the FE decision card does. 409 if there's nothing to act on (→ the chat
            tells the user to open the app)."""
            rid = rid.strip("/")
            if not _RID_RE.match(rid):
                self._json(404, {"error": "run not found"})
                return
            intent = str(self._read_json().get("intent") or "retry").strip().lower()
            if intent not in ("retry", "skip"):
                self._json(400, {"error": "intent must be 'retry' or 'skip'"})
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                doc = fs.get_research(sess.uid, rid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            if doc is None:
                self._json(404, {"error": "run not found"})
                return
            cmd = _decision_command(doc.get("pendingDecision"), intent)
            if cmd is None:
                self._json(409, {"error": "nothing to resolve — this run isn't waiting on a decision"})
                return
            device_id = (doc.get("deviceId") or "").strip()
            if not device_id:
                self._json(409, {"error": "run has no device"})
                return
            action = cmd.pop("action")
            try:
                fs.write_command(sess.uid, rid, action, device_id=device_id, extra=cmd or None)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            log.info("resolve(%s) run %s on device %s (%s)", intent, rid, device_id, action)
            self._json(200, {"ok": True, "runId": rid, "deviceId": device_id,
                             "intent": intent, "action": action})

        def _research_skip(self, rid: str) -> None:
            """Skip phases and/or P2 agents of a run (the chat /sr-skip). Writes
            pipelineConfig so the BE's reload_config overlay applies it at the
            next phase boundary: phases 1 (Brief) / 3 (Podcast) → skippedPhases
            (additive); 4 → video off; 5 → email off; agents
            (chatgpt/gemini/claude) → pipelineConfig.agents[k]=False — the SAME
            write the web app's per-agent P2 toggles make; all three off also
            adds phase 2 to skippedPhases (FE parity, researches/page.tsx
            syncConfigToStore). An ONGOING run additionally gets the FE tile's
            {action:"config"} command so the BE applies the change mid-run, and
            a run already IN P2 gets a skip_agent command per named agent so a
            RUNNING agent is dropped now (config alone only gates P2 entry).
            Phase 2 itself isn't whole-phase-skippable by number → name agents."""
            rid = rid.strip("/")
            if not _RID_RE.match(rid):
                self._json(404, {"error": "run not found"})
                return
            body = self._read_json()
            raw = body.get("phases")
            raw_agents = body.get("agents")
            # Only genuine integers (JSON true/1.0 are not phase numbers — bool is
            # an int subclass, so exclude it explicitly).
            phases = ({p for p in raw if isinstance(p, int) and not isinstance(p, bool)
                       and p in (1, 3, 4, 5)} if isinstance(raw, list) else set())
            agents_off = ({str(a).strip().lower() for a in raw_agents
                           if isinstance(a, str)
                           and str(a).strip().lower() in _DEFAULT_AGENTS}
                          if isinstance(raw_agents, list) else set())
            if not phases and not agents_off:
                self._json(400, {"error": "nothing skippable — choose phases "
                                          "(1=brief, 3=podcast, 4=video, 5=report) "
                                          "and/or agents (chatgpt/gemini/claude)"})
                return
            acct = self._account()
            if acct is None:
                return
            sess, fs = acct
            try:
                doc = fs.get_research(sess.uid, rid)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            if doc is None:
                self._json(404, {"error": "run not found"})
                return
            pc = doc.get("pipelineConfig") if isinstance(doc.get("pipelineConfig"), dict) else {}
            updates: dict[str, Any] = {}
            # Review catch (major): fire-time config stores skips under the BE
            # alias `skipPhases` (_config_from_settings), while this handler
            # historically wrote `skippedPhases`. The mid-run config command
            # below is a FULL snapshot the BE merges wholesale — reading only
            # one key would ERASE the other's fire-time skips (e.g. Settings'
            # podcast-off). Union BOTH keys so the snapshot is actually full.
            skipped_existing: set[int] = set()
            for _sp_key in ("skippedPhases", "skipPhases"):
                _raw_sp = pc.get(_sp_key)
                if isinstance(_raw_sp, list):
                    skipped_existing |= {int(x) for x in _raw_sp
                                         if isinstance(x, (int, float)) and not isinstance(x, bool)}
            skipped_new = set(skipped_existing) | (phases & {1, 3})
            if 4 in phases:
                updates["videoEnabled"] = False
            if 5 in phases:
                updates["emailEnabled"] = False
            merged_agents: dict[str, bool] | None = None
            if agents_off:
                cur = pc.get("agents") if isinstance(pc.get("agents"), dict) else {}
                # Absent key = ON (an older doc without `agents` runs all three).
                merged_agents = {k: (False if k in agents_off else bool(cur.get(k, True)))
                                 for k in _DEFAULT_AGENTS}
                updates["agents"] = merged_agents
                # FE parity: all three agents off = the whole research phase off.
                if not any(merged_agents.values()):
                    skipped_new.add(2)
            if skipped_new != skipped_existing:
                updates["skippedPhases"] = sorted(skipped_new)
            try:
                fs.patch_pipeline_config(sess.uid, rid, updates)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            # Mid-run parity with the FE tile: an ongoing run also gets the
            # {action:"config"} command (same shape researches/page.tsx writes)
            # so the BE applies the change NOW — the doc write alone is only
            # re-read at a queue pickup / serve restart. Best-effort: the doc
            # write above already landed, so a command failure isn't fatal.
            command_sent = False
            device_id = (doc.get("deviceId") or "").strip()
            if doc.get("status") == "ongoing" and device_id:
                cur_agents = pc.get("agents") if isinstance(pc.get("agents"), dict) else {}
                cfg_cmd = {
                    "skipPhases": sorted(skipped_new),
                    "agents": merged_agents or {k: bool(cur_agents.get(k, True))
                                                for k in _DEFAULT_AGENTS},
                    "videoEnabled": False if 4 in phases else pc.get("videoEnabled") is not False,
                    "emailEnabled": False if 5 in phases else pc.get("emailEnabled") is not False,
                }
                try:
                    fs.write_command(sess.uid, rid, "config", device_id=device_id,
                                     extra={"config": cfg_cmd})
                    command_sent = True
                except (RevokedError, FirestoreError):
                    pass
                # Already inside P2 → config gates only P2 ENTRY; a running
                # agent needs the decision card's skip_agent command (the same
                # write the FE's Skip button does) to be dropped mid-flight.
                if agents_off and doc.get("phase") == 2:
                    for a in sorted(agents_off):
                        try:
                            fs.write_command(sess.uid, rid, "skip_agent",
                                             device_id=device_id, extra={"agent": a})
                        except (RevokedError, FirestoreError):
                            pass
            log.info("skip requested for run %s: phases %s agents %s (cmd=%s)",
                     rid, sorted(phases), sorted(agents_off), command_sent)
            self._json(200, {"ok": True, "runId": rid, "skipped": sorted(phases),
                             "agentsOff": sorted(agents_off), "commandSent": command_sent})

        def _shutdown(self) -> None:
            """Stop the bridge (the host `agent stop`). Loopback + Host/Origin
            gated like every write. Shutdown runs in a separate thread because
            ThreadingHTTPServer.shutdown() must not be called from a request
            thread's own serve loop — we respond first, then stop serving."""
            log.info("shutdown requested")
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def _version(self, fresh: bool = False) -> None:
            """The agent version (+ a pip-style "newer agent on PyPI" notice) and
            the co-located Super Research backend version for DISPLAY (read-only;
            no account needed — loopback + Host gated like every route). No backend
            update notice: the runtime doesn't update the backend anymore (the app
            surfaces that; the user runs `superresearch --update` on the Research
            computer). Lets `version` work from chat the same as the agent CLI."""
            self._json(200, {
                "agent": __version__,
                "backend": _backend_version(),
                # fresh=1 (explicit user ask / the daily notice job) bypasses
                # the 24h cache — an "any update?" right after a publish must
                # see it, not a stale cached "no".
                "agentLatest": selfupdate.agent_update_available(force=fresh),
            })

        def _agent_install(self) -> None:
            """Update the AGENT itself (package + skill + bridge) to the latest
            published version. The detached reconnect upgrades the PERSISTENT
            install (`pipx install --force`) and reconnects from it — so the ONLOGON
            launcher pins to a durable venv and a reboot comes back on the NEW
            version (see selfupdate.spawn_detached_reconnect; it falls back to the
            ephemeral `pipx run --no-cache` path if the persistent venv can't be
            resolved). It redeploys the skill + re-pins the launcher + starts the new
            bridge once THIS process exits, then we shut down — freeing the loopback
            port so the new bridge can bind it. Host/Origin gated like every write;
            this is a local maintenance action on the host user's own agent (no
            account needed)."""
            # Already on (or ahead of) the latest published agent → say so instead of
            # a pointless reconnect + bridge restart (fresh check, not the 24h cache).
            latest = selfupdate.latest_on_pypi(selfupdate.AGENT_PKG, force=True)
            if latest and not selfupdate.version_gt(latest, __version__):
                self._json(200, {"ok": True, "already": True, "current": __version__})
                return
            # Pre-flight: only tear the running bridge down if the update can ACTUALLY
            # proceed (online, package published, pipx healthy). Otherwise refuse and
            # keep the current bridge alive — never strand the user with no chat.
            if not selfupdate.agent_resolvable():
                self._json(502, {"error": "agent_unavailable"})
                return
            if not selfupdate.spawn_detached_reconnect():
                self._json(502, {"error": "update_helper_failed"})
                return
            log.info("agent self-update requested — reconnecting from latest")
            self._json(200, {"ok": True, "started": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def _install_backend(self) -> None:
            """Install the Super Research BACKEND on this host (`pipx install
            superresearch`) — turns this PC into a research host, all from chat.
            Detached (the bridge keeps running; this is a separate package). If the
            backend is already present, say so (it updates via `superresearch
            --update` on the host / the app's update prompt — not the agent).
            Host/Origin gated; pairing (API keys + browser logins) on the host after."""
            if _backend_cli():
                self._json(200, {"ok": True, "already": True})
                return
            if not selfupdate.spawn_detached_backend_install():
                self._json(502, {"error": "install_helper_failed"})
                return
            log.info("backend install requested (pipx install superresearch)")
            self._json(200, {"ok": True, "started": True})

    return Handler


def _port_holder_is_bridge(host: str, port: int) -> bool:
    """Probe http://host:port/healthz and return True only if the responder is
    actually a Super Agent bridge (its /healthz returns {"ok": true, "version": …}).
    Lets serve() tell a benign 'another bridge already running' apart from a FOREIGN
    process squatting the port. Stdlib only.

    Retries briefly: when our bind just failed, the holder may be a sibling bridge
    still coming up (idempotent ONLOGON re-fire / restart) that hasn't started
    answering /healthz yet — a single timed-out probe would wrongly brand it a
    foreign squatter. A few attempts give a real bridge time to respond; a holder
    that never returns the marker is treated as foreign."""
    import json as _json
    import time as _time
    import urllib.request
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=2) as r:
                data = _json.loads(r.read().decode("utf-8", "ignore"))
            if isinstance(data, dict) and data.get("ok") is True and "version" in data:
                return True
        except Exception:
            pass
        if attempt < 2:
            _time.sleep(0.5)
    return False


def serve(host: str | None = None, port: int | None = None) -> None:
    """Start the bridge and serve forever (blocking)."""
    host = host or config.BRIDGE_HOST
    port = port or config.BRIDGE_PORT
    state = BridgeState()
    # Idempotent start. The detached bridge from `agent connect`/`resurrect` can
    # still be alive when the ONLOGON Scheduled Task re-fires (a log-off/log-on
    # without a full reboot). Binding the port is the atomic ownership check: if
    # it's already taken, exit cleanly BEFORE arming the #790 agent row or the
    # heartbeat, so we never get two owners racing one account session (the
    # single-owner-refresher invariant). BridgeState() above is a read-only
    # session load, so constructing it on the loser is harmless.
    try:
        httpd = ThreadingHTTPServer((host, port), _make_handler(state))
    except OSError as e:
        # Port taken. Distinguish a benign already-running bridge (idempotent
        # re-fire) from a FOREIGN process squatting the port — the latter would
        # otherwise be silently mis-reported as "already running" and leave the
        # bridge mysteriously unreachable.
        if _port_holder_is_bridge(host, port):
            log.info("bridge port %s:%d already serving a bridge — nothing to start", host, port)
            print(f"Super Agent bridge already running on http://{host}:{port} — nothing to start.")
        else:
            log.warning("bridge port %s:%d held by a NON-bridge process (%s)", host, port, e)
            print(f"Port {port} is held by another process that isn't a Super Agent bridge.")
            print("  Free it, or set SUPER_AGENT_BRIDGE_PORT to another port, then retry.")
            print(f"  (find the holder:  netstat -ano | findstr :{port} )")
        return
    authed = state.session is not None
    # If we restarted with a live session (rehydrated via AccountSession.load(),
    # which doesn't fire either connect handler), re-arm the #790 agent row — but
    # HONOR a revoke that landed while the bridge was down (a restart is an
    # automatic reconnect, not a human sign-in, so it must NOT un-revoke).
    if authed:
        _arm_agent_session_on_start(state)
    # ONE background heartbeat thread (the single periodic owner-process tick):
    # bumps lastSeenAt + consults `revoked` to self-logout. daemon so it dies
    # with the process; stop event makes shutdown deterministic.
    hb_stop = threading.Event()
    hb_thread = threading.Thread(
        target=_heartbeat_loop, args=(state, hb_stop), name="agent-heartbeat", daemon=True
    )
    hb_thread.start()
    # serve()-owned remote-login auto-poller (#848): once a /sr login (or PC
    # `agent login`) starts a flow, drive it to capture the instant the user
    # approves in the browser — no second `login-done`. Daemon + stop event so
    # shutdown is deterministic (same pattern as the heartbeat thread above).
    rp_stop = threading.Event()
    rp_thread = threading.Thread(
        target=_remote_autopoll_loop, args=(state, rp_stop), name="agent-remote-autopoll", daemon=True
    )
    rp_thread.start()
    log.info("Super Agent bridge on http://%s:%d (authed=%s)", host, port, authed)
    print(f"Super Agent bridge listening on http://{host}:{port}")
    print(f"  sign in:  {config.login_origin()}/login   (local page; or remote via chat /sr-login)")
    print(f"  status:   {config.bridge_origin()}/status")
    print(f"  log:      {config.log_path()}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        hb_stop.set()
        rp_stop.set()
        httpd.shutdown()
