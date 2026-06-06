"""Bridge account routes (/researches, /devices, /research) with a fake session.

The bridge is the single owner of the session; these routes are what the CLI
and skill call instead of refreshing the token themselves.
"""

import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge


class FakeFS:
    last_enqueue = None
    last_upsert = None

    def __init__(self, _token_provider):
        pass

    def list_researches(self, uid):
        return [{"id": "r1", "title": "Alpha", "status": "completed"}]

    def list_devices(self, uid):
        return [{"id": "dev1", "name": "PC", "ownerUid": uid}]

    def upsert_research(self, uid, rid, fields):
        FakeFS.last_upsert = {"uid": uid, "rid": rid, "fields": fields}

    def enqueue_start(self, device_id, **kw):
        FakeFS.last_enqueue = {"device_id": device_id, **kw}
        return "Q-1"

    def delete_research(self, uid, rid):
        pass


@pytest.fixture()
def live(monkeypatch):
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    # Isolate the device-selection pref from the real ~/.super-agent/prefs.json.
    sel = {"v": None}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device", lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: sel.__setitem__("v", None))
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", state
    finally:
        httpd.shutdown()


def test_researches_route(live):
    base, _ = live
    r = requests.get(base + "/researches")
    assert r.status_code == 200
    assert r.json()["researches"][0]["id"] == "r1"


def test_devices_route(live):
    base, _ = live
    r = requests.get(base + "/devices")
    assert r.status_code == 200
    assert r.json()["devices"][0]["id"] == "dev1"


def test_research_enqueue_route(live):
    base, _ = live
    r = requests.post(base + "/research", json={"topic": "Tesla 2025", "deviceId": "dev1",
                                                "config": {"videoEnabled": False}})
    assert r.status_code == 200
    out = r.json()
    assert out["queueId"] == "Q-1" and out["runId"].startswith("agent-")
    # the enqueue carried the owner uid as submittedBy and the topic
    assert FakeFS.last_enqueue["uid"] == "u1"
    assert FakeFS.last_enqueue["topic"] == "Tesla 2025"
    # the research doc rendered as a real chat (phase 0, platforms, arrays)
    f = FakeFS.last_upsert["fields"]
    assert f["phase"] == 0 and f["viaAgent"] is True
    assert f["platforms"] and f["documents"] == [] and f["audios"] == []


def test_research_requires_topic(live):
    base, _ = live
    # topic is required; deviceId is now RESOLVED (P2), not required on the wire.
    assert requests.post(base + "/research", json={"deviceId": "d"}).status_code == 400
    # topic alone is fine — the sole fake device is auto-selected.
    assert requests.post(base + "/research", json={"topic": "x"}).status_code == 200


def test_account_routes_401_when_not_signed_in(monkeypatch):
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    state = bridge.BridgeState()
    state.set_session(None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert requests.get(base + "/researches").status_code == 401
        assert requests.post(base + "/research", json={"topic": "t", "deviceId": "d"}).status_code == 401
    finally:
        httpd.shutdown()
