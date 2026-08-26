"""Shared pytest fixtures."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from facade import config


@pytest.fixture(autouse=True)
def _no_real_fe_posts(monkeypatch):
    """⛔⛔ NO TEST IN THIS SUITE MAY POST TO THE REAL WEB APP.

    Added 2026-08-26, when `_enqueue_research_run` gained a courtesy notice to
    the machine's owner. `config.FE_BASE` defaults to `https://superresearch.io`,
    so from that commit on every existing run-start test — none of which had any
    reason to know about a notification — would have fired a live POST at
    production carrying a fake Bearer token. The notice is best-effort and
    swallows its own failures, so nothing would have gone red: the suite would
    simply have started talking to the internet, silently.

    So the seam is stubbed for the WHOLE suite by default rather than per test.
    A test that cares scripts its own reply by monkeypatching the same attribute
    (several already do) — monkeypatch applies in order, so a test's own
    `setattr` wins over this one. `bridge._fe_calls` is where the default lands
    them, for the tests that want to assert on a call they did not script.
    """
    from facade import bridge

    calls: list[tuple[str, dict]] = []

    def _stub(_sess, path: str, payload: dict) -> tuple[int, dict]:
        calls.append((path, payload))
        return 200, {"ok": True}

    monkeypatch.setattr(bridge, "_fe_api_post", _stub)
    monkeypatch.setattr(bridge, "_fe_calls", calls, raising=False)

    # ⛔⛔ AND THE BASE URL TOO, because the sentence above was a RACE, not a
    # guarantee — found by review 2026-08-26. Patching `_fe_api_post` only covers
    # calls made while the patch is live. The owner-notice rides a daemon thread
    # (`_spawn`), and only two suites make `_spawn` synchronous:
    # `test_bridge_routes.py` drives `POST /research` seven times and does not.
    # CPython schedules the thread promptly, so in practice it resolves the patched
    # global — but "in practice" is not what the sentence claims, and a thread that
    # loses that race would POST to the real host with a fake Bearer token.
    #
    # ⭐ So the host is neutralised as well: even a call that escapes the patch
    # goes to a port nothing is listening on and fails in `requests`, which
    # `_fe_api_post` turns into `(0, …)`. Two independent guards, because the
    # failure mode is silent by construction — the notice swallows its own errors.
    monkeypatch.setattr(config, "FE_BASE", "http://127.0.0.1:9", raising=False)


@pytest.fixture(autouse=True)
def _isolate_prefs_dir(monkeypatch, tmp_path):
    """Point ``config.store_dir()`` at a per-test tmp so prefs.json — including
    the #790 agent install id (minted lazily by get_or_create_install_id) — never
    touches the real ~/.super-agent. prefs.py resolves the dir dynamically, so
    this isolates it; store.py freezes its own paths at import and its tests
    override those module attrs directly, so they're unaffected. test_prefs
    re-sets store_dir itself (same effect)."""
    monkeypatch.setattr(config, "store_dir", lambda: tmp_path)


@pytest.fixture(autouse=True)
def _no_real_account_session(monkeypatch, tmp_path):
    """⛔⛔ NO TEST MAY INHERIT THE DEVELOPER'S OWN SIGNED-IN ACCOUNT.

    `BridgeState.__init__` calls `AccountSession.load()`, so every `BridgeState()`
    a test builds rehydrates whatever session is stored on the machine running the
    suite. On macOS that store is the **Keychain**, and `_isolate_prefs_dir` above
    says so in its own docstring — "store.py freezes its own paths at import" — so
    redirecting `config.store_dir()` never covered it, and no path override could
    cover a keyring anyway.

    ⛔ THE RESULT WAS A SUITE WHOSE ANSWER DEPENDED ON WHO RAN IT. Measured
    2026-08-26 on the owner's Mac, at commit `e5a4ec7`, with nothing modified:
    THREE tests were red purely because the developer happened to be signed in —
    `test_advance_past_ttl_expires_without_broker_call` and
    `test_advance_transient_stays_pending` both assert `state.session is None`
    after building a fresh state, and `test_every_log_route_refuses_when_signed_out`
    got 400 instead of 401 because the routes were, in fact, signed in. All three
    pass in CI, where there is no keyring backend and no stored session — which is
    exactly why this survived. The tests were right; the isolation was not.

    ⭐ THE SEAM IS WHAT THE STORE READS FROM, and finding it took two wrong
    guesses that are worth recording, because each broke a legitimate test:
      · `AccountSession.load` — one level too high. It broke
        `test_session_persists_and_rehydrates_capture_epoch`, which is a proper
        already-isolated test OF that classmethod.
      · `store.load` — still too high. `store` is a MODULE, so patching its
        attribute is global, and it broke `test_store.py`'s own round-trip.
    The right level is the one `test_store.py` was already using: no keyring, and
    the file fallback pointed at a per-test tmp. Then the real `load()` runs, finds
    an empty store, and returns None — and `test_store.py` re-applies the identical
    overrides, so its round-trip writes and reads its own tmp file as before.

    ⛔ `config.store_dir()` could never have covered this: `store.py` freezes
    `_STORE_DIR` / `_FALLBACK_PATH` at import, which the fixture above says in its
    own docstring — and no path override reaches a keyring at all.

    A test that wants a live session sets one (`state.set_session(...)`), which is
    what every existing one already does.
    """
    from facade import store

    monkeypatch.setattr(store, "_try_keyring", lambda: None)
    monkeypatch.setattr(store, "_STORE_DIR", tmp_path)
    monkeypatch.setattr(store, "_FALLBACK_PATH", tmp_path / "session.json")


class _FEHandler(BaseHTTPRequestHandler):
    """A scriptable stand-in for the SR web app's remote-login broker routes."""

    def log_message(self, *a: Any) -> None:  # silence
        pass

    def _drain_body(self) -> None:
        # Consume the request body before responding. Without this, closing an
        # HTTP/1.0 connection with an undrained body buffered triggers a TCP RST
        # on Windows → the client sees an intermittent ConnectionAbortedError.
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)

    def _send(self, code: int, body: Any) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        self._drain_body()
        cfg = self.server.cfg  # type: ignore[attr-defined]
        path = self.path.split("?", 1)[0]
        if path == "/api/agent/login/start":
            self._send(cfg["start_status"], cfg["start_resp"])
        elif path == "/identitytoolkit":
            # Stands in for accounts:signInWithCustomToken (the custom-token exchange).
            self._send(cfg["exchange_status"], cfg["exchange_resp"])
        else:
            self._send(404, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        cfg = self.server.cfg  # type: ignore[attr-defined]
        if self.path.split("?", 1)[0] == "/api/agent/login/poll":
            script = cfg["poll_script"]
            i = min(cfg["_i"], len(script) - 1)
            cfg["_i"] += 1
            status_code, body = script[i]
            self._send(status_code, body)
        else:
            self._send(404, {"error": "not found"})


@pytest.fixture()
def mock_fe():
    """Spin up a mock FE broker. Returns a factory → base URL.

    poll_script is a list of (http_status, json_body) tuples returned on
    successive /poll calls; the last entry repeats.
    """
    servers: list[ThreadingHTTPServer] = []

    def _make(*, start_resp: dict | None = None, start_status: int = 200,
              poll_script: list[tuple[int, dict]] | None = None,
              exchange_resp: dict | None = None, exchange_status: int = 200) -> str:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FEHandler)
        httpd.cfg = {  # type: ignore[attr-defined]
            "start_resp": start_resp or {},
            "start_status": start_status,
            "poll_script": poll_script or [(200, {"status": "pending"})],
            "exchange_resp": exchange_resp or {},
            "exchange_status": exchange_status,
            "_i": 0,
        }
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{port}"

    yield _make
    for s in servers:
        s.shutdown()
        s.server_close()  # release the listening socket so ports aren't reused mid-flight
