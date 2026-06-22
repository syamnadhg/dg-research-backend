"""The Super Agent host bridge — a loopback HTTP server.

It is the always-up local process that OWNS the account session: it is the ONLY
process that ever refreshes the token or touches Firestore, so the single-owner
invariant holds and an out-of-band CLI refresh can never strand it. The host
CLI and the chat skill both call it over HTTP — they never refresh themselves.

  * serves the Google sign-in page and captures the account session (`/login`),
  * holds the live ``AccountSession`` in memory and refreshes it,
  * exposes the account operations: /status /researches /devices /research.

Bound to 127.0.0.1 only; every request is Host- and (for writes) Origin-checked.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
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

# Podcast audio (the chat /sr-podcast → a native audio FILE the runtime attaches).
# The audio is downloaded host-side to ~/.super-agent/podcasts and only the LOCAL
# PATH is handed back — the long-lived Storage download token never leaves the
# host (it is not in the response, so it can't land in chat history).
_PODCAST_DIR_NAME = "podcasts"
_PODCAST_MAX_BYTES = 200 * 1024 * 1024  # 200 MiB — generous for a long audio overview
_PODCAST_MAX_AGE_SECONDS = 24 * 60 * 60  # prune cached audio older than a day
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


def _config_from_settings(pipe: dict[str, Any] | None) -> dict[str, Any]:
    """Map the account's saved pipeline Settings into the run-config the backend
    pipeline reads, so an agent-fired run honors the same defaults the web app
    applies. ``pipe`` is the ``pipeline`` map of ``users/{uid}/settings/prefs``.

    Mirrors the web app's Settings→config derivation (ChatInput.tsx): which
    agents run, which phases are skipped (brief; podcast+video when NotebookLM is
    off), whether video/email run, the podcast length, and skipInitVerify. Field
    defaults match the app's DEFAULT_SETTINGS, so an absent field behaves exactly
    as it does in the app (e.g. a settings-less account → verify + all agents)."""
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
        "skipInitVerify": bool(p.get("skipInitVerify", False)),
    }


def _new_research_fields(
    topic: str, device_id: str, uid: str, cfg: dict[str, Any] | None,
    chat_origin: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The research (chat) doc a fresh agent run creates.

    Mirrors enough of the web app's fresh-chat shape (research-app/web
    saveResearch / usePipeline) that it renders as a normal chat immediately —
    phase 0, the platform list, empty doc/audio arrays — rather than a sparse
    placeholder. The BE backfills the rest as the pipeline runs.
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
        "phase": 0,
        "deviceId": device_id,
        "submittedBy": uid,
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


def _audio_file_url(links: Any) -> str:
    """The DIRECT podcast media URL — ``links.audio_file`` (a public Storage .m4a).

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
    (…/audio_overview.m4a?alt=media&token=…); default to .m4a (NotebookLM's Audio
    Overview format) when none is recognizable.
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
    """Bound the on-disk podcast cache: drop any file older than
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
            if p.name == keep_name or p.suffix == ".part" or not p.is_file():
                continue
            if (now - p.stat().st_mtime) > _PODCAST_MAX_AGE_SECONDS:
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

    @property
    def session(self) -> AccountSession | None:
        with self._lock:
            return self._session

    def set_session(self, sess: AccountSession | None) -> None:
        with self._lock:
            self._session = sess

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
                return True
            return False


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
        log.info("agent session %s connected for %s", sid, sess.email or sess.uid)
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


def _phase_updates(doc: dict, sr_links: dict) -> list:
    """Ordered per-phase chat updates the watchdog streams: one entry per DONE
    phase (1-5) with its permanent SR link(s) + the platform-only links
    (NotebookLM / YouTube / final Doc). Skipped phases carry no links."""
    done = _completed_phases(doc)
    platform = _platform_links(doc)
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
                elif src == "pf:gdocs":
                    url = platform.get("gdocs") or platform.get("doc")
                else:
                    url = platform.get(src[3:])
                if url:
                    links.append({"label": label, "url": url, "permanent": src.startswith("sr:")})
        out.append({"phase": p, "name": name, "status": st, "links": links, "final": p == 5})
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


def _arm_agent_session_on_start(state: BridgeState) -> None:
    """At serve() startup with a session rehydrated from disk: honor a revoke
    that landed while the bridge was DOWN, otherwise re-arm the row.

    A restart is an AUTOMATIC reconnect (no human present), so it must not
    un-revoke. If the stored row is already revoked, self-logout (the bridge does
    not re-attach); else (re)write the row WITHOUT clearing revoked.
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
        log.info("startup: agent was revoked while the bridge was down — honoring revoke (skill + runtime kept)")
        _self_logout(state, sess)
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
        log.info("agent session %s revoked from the app — self-logout (skill + runtime kept)", sid)
        _self_logout(state, sess)
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
        flow.state = "expired"
        return None
    try:
        res = devicelogin.poll_once(flow.poll_token)
    except DeviceLoginError as e:
        # Transient transport blip — stay pending, keep polling. Log the detail;
        # the client gets a fixed message, not the upstream body.
        log.debug("remote poll transient error: %s", e)
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
        # #790 identity row — explicit human sign-in, so clear any prior revoke.
        _write_agent_session_connected(sess, clear_revoked=True)
        log.info("remote login connected as %s", sess.email or sess.uid)
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
    # non-version string would make backend_update_available() compare garbage and
    # falsely report an upgrade.
    return m.group(1) if m else None


def _start_backend_update() -> "dict[str, object]":
    """Kick `superresearch --update` on this host. The backend's updater detaches
    (waits for its own short-lived process to exit, then runs the upgrade) and
    returns promptly, so this does not block on the actual install. Raises
    FileNotFoundError when the backend CLI is absent so the route can 404."""
    exe = _backend_cli()
    if not exe:
        raise FileNotFoundError("backend_not_installed")
    import subprocess
    r = subprocess.run([exe, "--update"], capture_output=True, text=True, timeout=180)
    return {"rc": r.returncode, "output": (r.stdout or r.stderr or "").strip()[-1500:]}


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
            elif path == "/updates":
                self._updates()
            elif path == "/version":
                self._version()
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
            elif path == "/logout":
                self._logout()
            elif path == "/device/select":
                self._device_select()
            elif path == "/device/pair":
                self._device_pair()
            elif path == "/device/remove":
                self._device_remove()
            elif path == "/research":
                self._research()
            elif path.startswith("/research/") and path.endswith("/stop"):
                self._research_stop(path[len("/research/"):-len("/stop")])
            elif path.startswith("/research/") and path.endswith("/resolve"):
                self._research_resolve(path[len("/research/"):-len("/resolve")])
            elif path.startswith("/research/") and path.endswith("/cancel"):
                self._research_cancel(path[len("/research/"):-len("/cancel")])
            elif path.startswith("/research/") and path.endswith("/skip"):
                self._research_skip(path[len("/research/"):-len("/skip")])
            elif path == "/shutdown":
                self._shutdown()
            elif path == "/update":
                self._update_backend()
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
            state.rotate_login_token()  # one-shot: the captured nonce can't be replayed
            # #790 identity row — explicit human sign-in, so clear any prior revoke.
            _write_agent_session_connected(sess, clear_revoked=True)
            log.info("account session captured (local page) for %s", sess.email or sess.uid)
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
            if flow.error:
                out["error"] = flow.error
            return out

        def _login_remote_start(self) -> None:
            body = self._read_json()
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
            # Take remote_lock so a start can't swap the flow out from under an
            # in-flight poll (and vice-versa); start/poll are mutually exclusive.
            with state.remote_lock:
                state.set_remote(rf)
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

        def _status(self) -> None:
            # Carry the pip-style update notices so the welcome / a bare /sr can
            # PROACTIVELY prompt "a newer version is available" (cached 24h — cheap).
            updates = {
                "agentUpdate": selfupdate.agent_update_available(),
                "backendUpdate": selfupdate.backend_update_available(_backend_version()),
            }
            sess = state.session
            if sess is None:
                self._json(200, {"authed": False, **updates})
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
            self._json(200, {"researches": rows})

        def _decorate_devices(self, devs: list[dict[str, Any]], uid: str, selected: str | None):
            """Add the authoritative owned/selected flags the client can't infer.

            `owned` is computed against THIS session's uid (the CLI/skill route
            through the bridge and can't see sess.uid) — owner vs shared-to.
            """
            for d in devs:
                d["owned"] = d.get("ownerUid") == uid
                d["selected"] = d.get("id") == selected and selected is not None
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
            persisted selection (re-validated reachable) → the sole reachable
            device. Sends an error and returns None when it can't resolve (so the
            caller just returns)."""
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
            ids = {d.get("id") for d in devs}
            selected = prefs.get_selected_device(sess.uid)
            if selected:
                if selected in ids:
                    return selected
                self._json(409, {"error": "selected device no longer reachable — "
                                          "pick another from the device list"})
                return None
            if len(devs) == 1:
                did = devs[0].get("id")
                if did:
                    return did
            if not devs:
                # Relayed verbatim into chat — make it the next step, not a dead end.
                self._json(400, {"error": "no devices yet — on the computer running "
                                          "Super Research, grab the pair code from its "
                                          "screen and add it here (device add <code>)"})
                return None
            self._json(400, {"error": "no device selected — pick one from the device list"})
            return None

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
            rid = "agent-" + uuid.uuid4().hex[:16]
            # Honor the account's saved pipeline Settings (which agents, skip
            # brief/podcast/video/email, podcast length, skipInitVerify) — the
            # web app ships these in its start config, but sr.py (the chat client)
            # can't read Firestore, so resolve the account's settings doc HERE.
            # Explicit chat flags (--no-video / --no-email) override the defaults.
            chat_cfg = body.get("config") if isinstance(body.get("config"), dict) else {}
            pipe: dict[str, Any] = {}
            try:
                _settings = fs.get_user_settings(sess.uid)
                if isinstance(_settings, dict) and isinstance(_settings.get("pipeline"), dict):
                    pipe = _settings["pipeline"]
            except Exception as e:  # advisory read — never block a run on it
                # Log the type only (not the value) — this file's convention,
                # so an upstream body never lands in logs.
                log.warning("agent run: couldn't read account settings (%s) — using defaults",
                            type(e).__name__)
            cfg = {**_config_from_settings(pipe), **chat_cfg}
            # The chat this run was fired from (sr.py reads it from the gateway's
            # per-session env) — tags the doc so the streaming watchdog can scope
            # updates to this chat only. Absent for a CLI / older-gateway fire.
            origin = _clean_origin(body.get("origin"))
            try:
                fs.upsert_research(sess.uid, rid,
                                   _new_research_fields(topic, device_id, sess.uid, cfg, origin))
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            try:
                qid = fs.enqueue_start(
                    device_id, uid=sess.uid, research_id=rid,
                    topic=topic, email=sess.email, config_obj=cfg or {},
                )
            except (RevokedError, FirestoreError) as e:
                # The chat doc is already created; the enqueue failed (e.g. the
                # device isn't a member / went away). Best-effort delete so we
                # don't leave an orphan chat with no run behind it.
                try:
                    fs.delete_research(sess.uid, rid)
                except Exception:
                    log.debug("orphan research %s cleanup failed", rid)
                if isinstance(e, RevokedError):
                    self._json(401, {"error": "session revoked — run /login again"})
                else:
                    self._firestore_502(e)
                return
            # Seed the topic + "Researching …" chat bubbles the web app writes
            # client-side at run start — so an agent-started run's in-app chat
            # opens consistently with a web-started one (the BE pipeline only
            # writes pipeline_events, never the messages subcollection). The
            # title at creation == topic (_new_research_fields); the FE refines
            # it later. Best-effort — a seed failure must not fail the run.
            try:
                fs.seed_chat_messages(sess.uid, rid, topic=topic, title=topic)
            except Exception as e:
                log.debug("chat-message seed for %s failed (non-fatal): %s", rid, type(e).__name__)
            log.info("enqueued run %s on device %s", rid, device_id)
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
            # clean, never-revoked per-phase links the streaming watchdog does —
            # not the raw, revocable platform links. Idempotent + best-effort
            # (mints only docTypes whose content already exists; falls back to
            # whatever's already minted on failure).
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
                "research": doc,
                "events": runview.flatten_links(doc.get("links")),
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
            log.info("podcast audio ready for %s (%d bytes)", rid, size)
            self._json(200, {
                "ready": True,
                "runId": rid,
                "title": title,
                "localPath": str(path),
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
                limit = max(1, min(int(qs.get("limit", ["20"])[0]), 50))
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
                    "updatedAt": r.get("updatedAt"),
                    "links": runview.flatten_links(r.get("links")),
                    "srLinks": sr,
                    "phaseUpdates": phase_updates,
                    "chatOrigin": r.get("chatOrigin"),
                    "needsAttention": needs,
                    "attention": attention,
                })
            self._json(200, {"runs": runs})

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
                    # Running/paused → the per-run command listener is attached;
                    # a fresh action:"stop" command stops it at the next phase
                    # boundary and preserves partial results (the FE Stop button).
                    fs.write_command(sess.uid, rid, "stop", device_id=device_id)
                    mode = "running"
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            log.info("graceful stop requested for run %s on device %s (%s)", rid, device_id, mode)
            self._json(200, {"ok": True, "runId": rid, "deviceId": device_id, "status": status, "mode": mode})

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
            """Skip phases of a run (the chat /sr-skip). Writes pipelineConfig so the
            BE's reload_config overlay applies it at the next phase boundary:
            phases 1 (Brief) / 3 (Podcast) → skippedPhases (additive); 4 → video
            off; 5 → email off. Phases 0/2 aren't whole-phase-skippable → 400."""
            rid = rid.strip("/")
            if not _RID_RE.match(rid):
                self._json(404, {"error": "run not found"})
                return
            body = self._read_json()
            raw = body.get("phases")
            if not isinstance(raw, list):
                self._json(400, {"error": "phases (a list of phase numbers) is required"})
                return
            # Only genuine integers (JSON true/1.0 are not phase numbers — bool is
            # an int subclass, so exclude it explicitly).
            phases = {p for p in raw if isinstance(p, int) and not isinstance(p, bool)
                      and p in (1, 3, 4, 5)}
            if not phases:
                self._json(400, {"error": "no skippable phases — choose 1=brief, 3=podcast, 4=video, 5=report"})
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
            phase_skips = phases & {1, 3}
            if phase_skips:
                raw_sp = pc.get("skippedPhases")
                existing = ({int(x) for x in raw_sp
                             if isinstance(x, (int, float)) and not isinstance(x, bool)}
                            if isinstance(raw_sp, list) else set())
                updates["skippedPhases"] = sorted(existing | phase_skips)
            if 4 in phases:
                updates["videoEnabled"] = False
            if 5 in phases:
                updates["emailEnabled"] = False
            try:
                fs.patch_pipeline_config(sess.uid, rid, updates)
            except RevokedError:
                self._json(401, {"error": "session revoked — run /login again"})
                return
            except FirestoreError as e:
                self._firestore_502(e)
                return
            log.info("skip requested for run %s: phases %s", rid, sorted(phases))
            self._json(200, {"ok": True, "runId": rid, "skipped": sorted(phases)})

        def _shutdown(self) -> None:
            """Stop the bridge (the host `agent stop`). Loopback + Host/Origin
            gated like every write. Shutdown runs in a separate thread because
            ThreadingHTTPServer.shutdown() must not be called from a request
            thread's own serve loop — we respond first, then stop serving."""
            log.info("shutdown requested")
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def _version(self) -> None:
            """The agent version + the co-located Super Research backend version,
            each with a pip-style "newer on PyPI" notice (read-only; no account
            needed — loopback + Host gated like every route). Lets `version` work
            from chat the same as the agent CLI."""
            backend = _backend_version()
            self._json(200, {
                "agent": __version__,
                "backend": backend,
                "agentLatest": selfupdate.agent_update_available(),
                "backendLatest": selfupdate.backend_update_available(backend),
            })

        def _update_backend(self) -> None:
            """Update the co-located Super Research backend (delegates to
            `superresearch --update`, which detaches its own updater). Host/Origin
            gated like every write; the backend that runs here is the host user's
            own, so this is a local maintenance action (no account needed)."""
            backend = _backend_version()
            if backend is None:
                self._json(404, {"error": "backend_not_installed"})
                return
            # Already on (or ahead of) the latest published version → say so instead
            # of a pointless reinstall (fresh check; an explicit "update now" must not
            # be decided off the 24h cache).
            latest = selfupdate.latest_on_pypi(selfupdate.BACKEND_PKG, force=True)
            if latest and not selfupdate.version_gt(latest, backend):
                self._json(200, {"ok": True, "already": True, "current": backend})
                return
            try:
                res = _start_backend_update()
            except FileNotFoundError:
                self._json(404, {"error": "backend_not_installed"})
                return
            except Exception as e:  # subprocess/timeout — report, don't crash the worker
                log.warning("backend update failed to start: %s", e)
                self._json(502, {"error": f"update_failed: {type(e).__name__}"})
                return
            self._json(200, {"ok": True, "started": True, **res})

        def _agent_install(self) -> None:
            """Update the AGENT itself (package + skill + bridge) to the latest
            published version. `pipx run superresearch-agent` is always-latest, so we
            spawn a DETACHED reconnect (redeploy skill + re-pin launcher + start the
            new bridge) that fires once THIS process exits, then shut down — freeing
            the loopback port so the new bridge can bind it. Host/Origin gated like
            every write; this is a local maintenance action on the host user's own
            agent (no account needed). Mirrors the backend's detached self-update."""
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
            backend is already present, say so (use `/update` to upgrade). Host/Origin
            gated; pairing (API keys + browser logins) is done on the host after."""
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
