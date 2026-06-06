"""POST /shutdown stops the bridge (the host `agent stop`)."""

import threading
from http.server import ThreadingHTTPServer

import requests

from facade import bridge
from facade import store as store_mod


def test_shutdown_stops_the_server(monkeypatch):
    monkeypatch.setattr(store_mod, "load", lambda: None)  # no real session loaded
    state = bridge.BridgeState()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        r = requests.post(f"http://127.0.0.1:{port}/shutdown", timeout=5)
        assert r.status_code == 200 and r.json()["ok"] is True
        t.join(timeout=5)  # serve_forever should exit shortly after the response
        assert not t.is_alive()
    finally:
        httpd.shutdown()
        httpd.server_close()
