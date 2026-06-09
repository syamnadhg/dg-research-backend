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

from . import __version__, config, connect, devicelogin, prefs, runview
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


def _new_research_fields(
    topic: str, device_id: str, uid: str, cfg: dict[str, Any] | None
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


def _self_logout(state: BridgeState, sess: AccountSession | None) -> bool:
    """In-memory teardown shared by the /logout route and the revoke-consult.

    Compare-and-swap on ``sess``: tears down ONLY if it is still the live session
    (so a heartbeat deciding to self-logout against the OLD session can't undo a
    reconnect that swapped a NEW one in). Returns True iff it actually tore down —
    the revoke path gates the skill-uninstall on this so it never uninstalls when
    a concurrent reconnect won the CAS. Clears the live session + the account-
    bound device selection. Does NOT touch the agentSessions doc — the route
    deletes it (clean logout), while the revoke path leaves the ``revoked: true``
    row in place so the app shows the disconnect and a re-login can clear it.
    """
    if sess is None:
        prefs.clear_selected_device()
        return False
    if not state.clear_session_if(sess):
        return False  # a concurrent reconnect already swapped the session in — leave it
    sess.logout()
    prefs.clear_selected_device()
    return True


def _uninstall_skill_on_revoke() -> None:
    """App Revoke = sign out + UNINSTALL the skill from the runtime, so the agent
    is fully torn down (re-adding is then a deliberate `agent connect`). Only the
    explicit app revoke does this — a clean /logout or a token-level RevokedError
    keeps the skill installed. Best-effort + bounded to the recorded runtime's
    own skill dir; a failure must never break the self-logout."""
    rt = prefs.get_runtime()
    if not rt:
        return
    # Target the home the skill was actually installed under — for a WSL runtime
    # that's a \\wsl.localhost UNC path, NOT the Windows home. (Older connects
    # that didn't record a home fall back to the Windows default.)
    home = prefs.get_runtime_home()
    kwargs = {"home": Path(home)} if home else {}
    try:
        if connect.uninstall(rt, **kwargs):
            log.info("revoke: uninstalled the %s skill bundle", rt)
    except Exception as e:
        log.warning("revoke: skill uninstall failed (non-fatal): %s", type(e).__name__)


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
        log.info("startup: agent was revoked while the bridge was down — honoring revoke + uninstall")
        if _self_logout(state, sess):
            _uninstall_skill_on_revoke()
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
        log.info("agent session %s revoked from the app — self-logout + uninstall", sid)
        if _self_logout(state, sess):
            _uninstall_skill_on_revoke()
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
            elif path == "/research":
                self._research()
            elif path.startswith("/research/") and path.endswith("/cancel"):
                self._research_cancel(path[len("/research/"):-len("/cancel")])
            elif path.startswith("/research/") and path.endswith("/skip"):
                self._research_skip(path[len("/research/"):-len("/skip")])
            elif path == "/shutdown":
                self._shutdown()
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
            # two in-flight requests can't double-redeem the one-shot custom token,
            # and (paired with _login_remote_start taking the same lock) guarantees
            # we operate on the current flow, not one a concurrent start superseded.
            with state.remote_lock:
                flow = state.remote
                if flow is None:
                    self._json(400, {"error": "no remote login in progress — POST /login/remote/start first"})
                    return
                if flow.state in ("connected", "expired", "error"):
                    self._json(200, self._remote_payload(flow))  # terminal — just report
                    return
                if time.time() >= flow.expires_at:
                    flow.state = "expired"
                    self._json(200, self._remote_payload(flow))
                    return
                try:
                    res = devicelogin.poll_once(flow.poll_token)
                except DeviceLoginError as e:
                    # Transient transport blip — stay pending, keep polling. Log the
                    # detail; the client gets a fixed message, not the upstream body.
                    log.debug("remote poll transient error: %s", e)
                    payload = self._remote_payload(flow)
                    payload["transient"] = "sign-in service temporarily unreachable"
                    self._json(200, payload)
                    return
                status = res.get("status")
                if status == devicelogin.APPROVED:
                    try:
                        sess = AccountSession.from_custom_token(res["customToken"])
                    except CustomTokenError as e:
                        flow.state = "error"
                        flow.error = "sign-in could not be completed"  # non-reflective
                        log.warning("remote login custom-token exchange failed: %s", e)
                        self._json(200, self._remote_payload(flow))
                        return
                    state.set_session(sess)
                    flow.state = "connected"
                    # #790 identity row — explicit human sign-in, so clear any prior revoke.
                    _write_agent_session_connected(sess, clear_revoked=True)
                    log.info("remote login connected as %s", sess.email or sess.uid)
                elif status == devicelogin.EXPIRED:
                    flow.state = "expired"
                    log.info("remote login expired before approval")
                self._json(200, self._remote_payload(flow))

        def _status(self) -> None:
            sess = state.session
            if sess is None:
                self._json(200, {"authed": False})
                return
            self._json(200, {"authed": True, "uid": sess.uid, "email": sess.email})

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
                self._json(409, {"error": "selected device no longer reachable — re-select with /device"})
                return None
            if len(devs) == 1:
                did = devs[0].get("id")
                if did:
                    return did
            if not devs:
                self._json(400, {"error": "no devices reachable by this account"})
                return None
            self._json(400, {"error": "no device selected — choose one with /device"})
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
            cfg = body.get("config") if isinstance(body.get("config"), dict) else None
            try:
                fs.upsert_research(sess.uid, rid, _new_research_fields(topic, device_id, sess.uid, cfg))
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
            # `events` = the flattened, ordered per-phase links a streamer dedups
            # by kind (the raw `links` map is also returned for full fidelity).
            self._json(200, {"research": doc, "events": runview.flatten_links(doc.get("links"))})

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
                if active_only and status not in ("queued", "ongoing"):
                    continue
                runs.append({
                    "runId": r.get("id"),
                    "title": r.get("title") or r.get("topic"),
                    "topic": r.get("topic"),
                    "status": status,
                    "phase": r.get("phase"),
                    "updatedAt": r.get("updatedAt"),
                    "links": runview.flatten_links(r.get("links")),
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

    return Handler


def _port_holder_is_bridge(host: str, port: int) -> bool:
    """Probe http://host:port/healthz and return True only if the responder is
    actually a Super Agent bridge (its /healthz returns {"ok": true, "version": …}).
    Lets serve() tell a benign 'another bridge already running' apart from a FOREIGN
    process squatting the port (possible under WSL mirrored networking). Stdlib
    only.

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
        # bridge mysteriously unreachable (esp. under WSL mirrored networking).
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
        httpd.shutdown()
