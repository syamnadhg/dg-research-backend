"""Shared pytest fixtures."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


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
