"""The `--serve` local API's caller check — a shared secret on disk, 0600.

⛔⛔ WHAT WAS WRONG, open since 2026-08-31 and skipped by two waves. The HTTP API
`--serve` runs had NO authentication of any kind. Loopback binding (2026-09-05)
narrowed WHO could reach it to this machine and nothing more; the routes
themselves still asked nobody who was calling:

  GET  /api/runs                        every run folder on the machine, across
                                        every account that shares it
  GET  /api/runs/{id}/documents/{type}  the brief, the agent markdown, the report
  GET  /api/runs/{id}/audio/{name}      the podcast
  POST /api/runs                        START a run, billing the `uid` IT WAS
                                        HANDED IN THE REQUEST BODY
  POST /api/runs/{id}/stop|pause|resume steer or kill somebody's research
  DELETE /api/runs/{id}                 delete the run and its queued commands

Any process on the machine — any installer, any script, any other user's login
on a shared Mac — could do all of that. So could any web page, for the subset a
browser can send cross-origin.

⭐ THE SHAPE: ONE GATE, NOT FOURTEEN. `ServeTokenMiddleware` sits at the ASGI
layer, so a route is protected by EXISTING rather than by somebody remembering
to decorate it. `research.py` has fourteen routes today (the wave's plan said
four, then thirteen — the start-of-wave cross-check found the real number), and
the fifteenth is covered the moment it is written. The exempt set is the only
list anyone has to maintain, and it holds exactly one path.

⭐ WHY `/api/health` IS EXEMPT, and it is not convenience. FOUR CALLERS, NAMED,
because the exempt set is the only list anyone has to maintain and the next
person to question it deserves the evidence rather than a summary:

  research.py  `_local_api_health`       — `--doctor`'s local API check
  research.py  `_port_answers_health`    — is the port held by one of ours
  research.py  `_port_backend_activity`  — what is that backend doing
  research.py  the supervisor watchdog's per-worker probe (inside `_sup_audit`'s
                                           enclosing loop), which FORCE-RESPAWNS
                                           a worker whose health goes unreachable

That last one is the reason. A liveness probe that can fail for an
authentication reason is a liveness probe that can kill a perfectly healthy
worker over an unreadable file. The endpoint answers process-liveness counters
and nothing about anybody's research.

⚠ KNOWN AND ACCEPTED: `/api/health` reports `running` and `pending`, the same
two integers `/api/queue` carries, so gating `/api/queue` buys nothing for
those fields. They are not removable — `_port_backend_activity` reads them to
tell a person which backend is holding their port, and that message is the
reason the port-reclaim refusal is legible. Two integers about the machine's own
busyness are not somebody's research.

⛔ THE TOKEN NEVER TRAVELS IN A URL. Only the `X-Super-Research-Token` header is
read. A query parameter would land in uvicorn's access log, in shell history and
in any proxy in between; `?token=…` therefore does not authenticate, and a test
says so. A custom header also cannot be sent cross-origin by a browser without a
preflight, which the loopback-only CORS policy refuses.

⛔ IT FAILS CLOSED. No token file, an empty one, or one we cannot read means
every non-exempt request is refused — never "allow, we could not check". The
fail-safe direction is the whole point of the wave.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Final

# ⭐ IMPORTED, NOT RESTATED. "Beside the keystore" is the requirement, so the
# directory is the keystore's own constant — a second literal could drift and
# nobody would notice until a token sat in a directory nothing else protects.
from .keystore import _FALLBACK_DIR as _KEYSTORE_DIR

#: The file, beside `auth.json` and the install UUID in `~/.super-research/`.
TOKEN_FILENAME: Final = "serve-api.token"

#: The ONE header that authenticates. See the module docstring on why there is
#: no query-parameter form and no second header name.
HEADER: Final = "x-super-research-token"

#: Paths that answer without a token. ⛔ EXACTLY ONE, and adding to it is a
#: decision about what a stranger on this machine may read.
EXEMPT_PATHS: Final[frozenset[str]] = frozenset({"/api/health"})

#: 32 bytes of `secrets` → 43 url-safe characters.
_TOKEN_BYTES: Final = 32

#: Mint retries for the multi-worker boot race (see `ensure_token`).
_MINT_ATTEMPTS: Final = 40
_MINT_BACKOFF_SEC: Final = 0.05


def token_path() -> Path:
    """Where the shared secret lives — beside the keystore, by construction."""
    return _KEYSTORE_DIR / TOKEN_FILENAME


def _harden(path: Path) -> None:
    """Re-assert 0600 if anything widened it. Best-effort: Windows ignores
    POSIX mode bits, exactly as `keystore._file_save` documents."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return
    if mode & 0o077:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass


def read_token() -> str | None:
    """The stored secret, or None if there is not one we can read.

    ⛔ None is the answer for "missing", "empty" and "unreadable" alike, and
    every caller treats all three as "refuse". Distinguishing them here would
    only give a caller somewhere the chance to treat one of them as permission.
    """
    try:
        raw = token_path().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        # ⛔⛔ `UnicodeDecodeError` IS NOT AN `OSError`. Catching only OSError
        # let a token file that is not valid UTF-8 — Windows Notepad's legacy
        # "Unicode" save writes UTF-16LE with a BOM, and a truncated restore
        # does it too — raise straight out of the middleware, so every request
        # answered 500 with a traceback instead of the designed 401. A file we
        # cannot read is a file we do not have; that is the same answer.
        return None
    return raw or None


def ensure_token(_clear_empty: bool = True) -> str:
    """Get-or-create the secret. Called once at `--serve` boot.

    ⛔⛔ O_CREAT | O_EXCL, NOT "check then write". `--serve` starts N worker
    PROCESSES (`workerCount`), and they boot together. A read-then-write would
    have every worker mint its own and the last one to land would silently
    invalidate the token the others had already handed out — a 401 storm on a
    machine where nothing is wrong. The exclusive create makes exactly one
    worker the minter; every other worker loses the race and reads the winner's
    file, which is the correct outcome and needs no coordination.

    The retry loop is for the window between create and write: a loser can open
    a file that exists and is still empty. It backs off rather than minting.
    """
    path = token_path()
    for _ in range(_MINT_ATTEMPTS):
        existing = read_token()
        if existing:
            _harden(path)
            return existing
        try:
            _KEYSTORE_DIR.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # Another worker got there first and may still be writing.
            time.sleep(_MINT_BACKOFF_SEC)
            continue
        minted = secrets.token_urlsafe(_TOKEN_BYTES)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(minted)
            fh.flush()
            os.fsync(fh.fileno())
        _harden(path)
        return minted
    # ⛔⛔ AN EMPTY LEFTOVER IS NOT A REASON TO GIVE UP FOREVER. A crash or a
    # full disk between the exclusive create and the write leaves a zero-byte
    # file, and every boot after that found it, lost the create race to it, and
    # refused every request — while `/api/health` kept answering 200, so the
    # watchdog reported the worker perfectly well. Nothing on the machine could
    # get out of that state without a human deleting a file they had no reason
    # to suspect. An empty file holds no secret anybody could be using, so
    # removing it costs nothing and is the only exit.
    # ⛔ ONE retry, never a recursion that could spin: if the clear-and-remint
    # also ends empty, something is wrong that deleting a file will not fix.
    if _clear_empty:
        try:
            if path.exists() and not path.read_bytes().strip():
                path.unlink()
                return ensure_token(_clear_empty=False)
        except OSError:
            pass
    raise RuntimeError(
        f"could not establish the local API token at {path} — it exists but "
        "stayed empty. Delete it and restart the backend.")


def token_ok(presented: "str | None") -> bool:
    """Does `presented` match the stored secret?

    ⛔ CONSTANT TIME. `==` on a secret leaks its prefix to anything that can
    time a request, and a local attacker can time a local request very well.
    """
    if not presented:
        return False
    stored = read_token()
    if not stored:
        return False  # ⛔ FAIL CLOSED — no secret means no access, not free access.
    # ⛔⛔ ENCODED FIRST. `compare_digest` on two `str` objects REQUIRES both to
    # be ASCII-only and raises TypeError otherwise — so a header value with any
    # non-ASCII byte in it (`curl -H 'X-Super-Research-Token: café'`) came out
    # of the middleware as a 500 and a traceback rather than a 401. A refusal
    # must never depend on what the refused caller sent.
    return hmac.compare_digest(presented.encode("utf-8"), stored.encode("utf-8"))


def is_exempt(path: str) -> bool:
    """⛔ EQUALITY, NEVER A PREFIX. `startswith("/api/health")` would also let
    `/api/healthcheck-runs` through, and the whole gate is then one route name
    away from being off."""
    return (path.rstrip("/") or "/") in EXEMPT_PATHS


def _unauthorized_body() -> bytes:
    """⭐ NAMES THE FILE, NEVER THE VALUE, AND NEVER THE ABSOLUTE PATH.

    The token is a secret and obviously never goes in here. ⛔ Neither does
    `token_path()`: it is `~/.super-research/…` EXPANDED, so it carries the OS
    username and the home directory to a caller we are in the middle of
    refusing. A page doing DNS rebinding onto 127.0.0.1 gets a 401 it can read
    — the refusal is correct, handing it the machine's account name is not.

    The person who is meant to find the file is the one at the terminal, and
    the `--serve` banner and `--help` both print the full path for them.
    """
    return json.dumps({
        "error": "unauthorized",
        "detail": (f"send the {HEADER} header; its value is in "
                   f"{TOKEN_FILENAME}, beside the keystore — the --serve "
                   "banner prints the full path"),
    }).encode("utf-8")


class ServeTokenMiddleware:
    """Refuse every non-exempt request that does not carry the secret.

    ⛔⛔ PLAIN ASGI, NOT `BaseHTTPMiddleware`, AND THAT IS THE POINT. It runs
    before routing, so it covers paths no route claims and protocols no route
    speaks. A websocket is refused by the same rule as a GET — the `/ws/{id}`
    route was deleted in April, and if one ever comes back it arrives already
    gated instead of arriving open.

    ⛔ ORDER MATTERS AT THE CALL SITE, NOT HERE. Starlette's `add_middleware`
    makes the LAST-added the OUTERMOST, so `research.py` adds this one FIRST and
    CORS second — otherwise this gate would answer the browser's preflight
    (which carries no headers to authenticate with) and the CORS policy would
    never run.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            # `lifespan` — startup/shutdown, not a caller. Pass it through.
            await self.app(scope, receive, send)
            return
        if is_exempt(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        if token_ok(_header_value(scope)):
            await self.app(scope, receive, send)
            return
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = _unauthorized_body()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


def _header_value(scope) -> "str | None":
    """The presented secret, from the one header that carries it.

    ASGI header names arrive lowercased and as bytes. Anything undecodable is
    not our token, so it answers None rather than raising into the gate.
    """
    wanted = HEADER.encode("ascii")
    for name, value in scope.get("headers") or ():
        if name == wanted:
            try:
                return value.decode("utf-8").strip() or None
            except UnicodeDecodeError:
                return None
    return None
