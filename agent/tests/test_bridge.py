"""Bridge serve() port-holder probe — distinguishes a real Super Agent bridge
already on the port from a FOREIGN process squatting it (so serve() can report the
right thing instead of a misleading 'already running')."""

import urllib.request

import pytest

from facade import bridge


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # _port_holder_is_bridge retries with time.sleep between attempts; skip the
    # real waits so the negative cases stay fast.
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)


class _FakeResp:
    def __init__(self, body: bytes):
        self._b = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self) -> bytes:
        return self._b


def test_port_holder_is_bridge_true_on_bridge_healthz(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=2: _FakeResp(b'{"ok": true, "version": "1.2.3"}'))
    assert bridge._port_holder_is_bridge("127.0.0.1", 9876) is True


def test_port_holder_is_bridge_false_on_foreign_server(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=2: _FakeResp(b"<html>some dev server</html>"))
    assert bridge._port_holder_is_bridge("127.0.0.1", 9876) is False


def test_port_holder_is_bridge_false_on_missing_marker(monkeypatch):
    # Valid JSON but not the bridge's {ok, version} shape.
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=2: _FakeResp(b'{"status": "ok"}'))
    assert bridge._port_holder_is_bridge("127.0.0.1", 9876) is False


def test_port_holder_is_bridge_false_on_connection_error(monkeypatch):
    def _boom(url, timeout=2):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert bridge._port_holder_is_bridge("127.0.0.1", 9876) is False
