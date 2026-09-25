"""A support-log request survives a bridge restart, and never ends in silence (2026-09-25).

⛔⛔ TWO WAYS THE ONE MESSAGE THAT SAYS "THE LOGS ARRIVED" WAS LOST:
  1. the request lived in a dict in bridge memory, so a restart — the ordinary case
     across a packaging wait, not the edge one — dropped it with no notice at all;
  2. past `_BUNDLE_WATCH_SECONDS` the record was dropped WITHOUT A WORD, so a person
     who had been told "asked" never heard anything again.

⭐ THE FIX (owner, 2026-09-25): the record is parked in prefs.json (bounded, uid-bound,
a day's TTL); past the watch the row is read ONE more time — a late landing is still
announced as what it is — and only if there is still no answer is the chat told so,
once, under its own key `supportLogsLate`; then the watch ends.

⛔ A NEW KEY, NEVER A NEW `supportLogs` STATUS. A watcher from before this change
renders every `supportLogs` that is not "failed" as "✓ Support has the logs", so a
"late" status under the old key would reach it as a false success.
"""

import contextlib
import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import requests

from facade import bridge, prefs

TG = {"platform": "telegram", "chat_id": "111"}


class _FS:
    bundles: dict = {}

    def __init__(self, _tok):
        pass

    def list_researches(self, uid, page_size=20, **k):
        return []

    def get_log_bundle(self, uid, code):
        return _FS.bundles.get(code)


def _sess():
    return SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "tok",
                           connected_at_ms=7_000, logout=lambda: None)


@contextlib.contextmanager
def _bridge(monkeypatch):
    monkeypatch.setattr(bridge, "FirestoreRest", _FS)
    _FS.bundles = {}
    state = bridge.BridgeState()
    state.set_session(_sess())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    finally:
        httpd.shutdown()
        httpd.server_close()


def _tick(base, chat="111"):
    return requests.get(base + "/updates?via=agent&watchdog=1&platform=telegram"
                        f"&chat={chat}", timeout=10).json()


def _settled(code, uid="u1"):
    """Wait for the post-send commit. ⛔ It runs AFTER the response is written — that
    is the whole point of commit-after-send — so a test that fires the next tick the
    instant the bytes arrive can beat it. The watcher's next tick is a minute away."""
    deadline = time.time() + 5
    while time.time() < deadline:
        if (prefs.get_log_request(code, uid) or {}).get("announced"):
            return True
        time.sleep(0.02)
    return False


def _ask(code, age=0.0, **extra):
    bridge._remember_log_request(code, {"uid": "u1", "deviceId": "d1",
                                        "deviceName": "Mac", "at": time.time() - age,
                                        "origin": TG, "runCount": 2, "announced": False,
                                        **extra})


def test_a_request_survives_a_bridge_restart(monkeypatch):
    """⛔⛔ THE FIRST LOSS. Nothing about the request lives in process memory any
    more: a brand-new bridge (new state, new handler) still announces it."""
    _ask("AAAA1111")
    assert "logRequests" in prefs.load()
    with _bridge(monkeypatch) as (base, _state):        # "after the restart"
        assert "supportLogs" not in _tick(base)
        _FS.bundles["AAAA1111"] = {"status": "done", "runCount": 2}
        hit = _tick(base)
        assert hit["supportLogs"]["code"] == "AAAA1111"
        assert hit["supportLogs"]["deviceName"] == "Mac"
        assert _settled("AAAA1111")
        assert "supportLogs" not in _tick(base), "announced exactly once"
    rec = prefs.get_log_request("AAAA1111", "u1")
    assert rec["announced"] is True and rec["outcome"] == "done"


def test_no_answer_past_the_watch_is_said_once_not_dropped(monkeypatch):
    """⛔⛔ THE SECOND LOSS. Past the watch the chat hears "no answer yet" ONCE, under
    its own key — never as a `supportLogs` an older watcher would call a success."""
    _ask("BBBB2222", age=bridge._BUNDLE_WATCH_SECONDS + 60)
    with _bridge(monkeypatch) as (base, _state):
        first = _tick(base)
        assert "supportLogs" not in first
        late = first["supportLogsLate"]
        assert late["code"] == "BBBB2222" and late["deviceName"] == "Mac"
        assert late["ageSeconds"] >= bridge._BUNDLE_WATCH_SECONDS
        assert _settled("BBBB2222")
        assert "supportLogsLate" not in _tick(base), "said once, then the watch ends"
    rec = prefs.get_log_request("BBBB2222", "u1")
    assert rec is not None, "kept, so `--status` still knows the device and the age"
    assert rec["outcome"] == "late"


def test_a_late_landing_is_announced_as_what_it_is(monkeypatch):
    _ask("CCCC3333", age=bridge._BUNDLE_WATCH_SECONDS + 60)
    with _bridge(monkeypatch) as (base, _state):
        _FS.bundles["CCCC3333"] = {"status": "done", "runCount": 2}
        hit = _tick(base)
    assert hit["supportLogs"]["status"] == "done"
    assert "supportLogsLate" not in hit


def test_the_late_notice_goes_only_to_the_chat_that_asked(monkeypatch):
    _ask("DDDD4444", age=bridge._BUNDLE_WATCH_SECONDS + 60)
    with _bridge(monkeypatch) as (base, _state):
        assert "supportLogsLate" not in _tick(base, chat="999")
        assert _tick(base)["supportLogsLate"]["code"] == "DDDD4444"


def test_a_failed_send_does_not_mark_it(monkeypatch):
    """Commit-after-send, like every other proactive note."""
    _ask("EEEE5555")
    with _bridge(monkeypatch) as (base, _state):
        _FS.bundles["EEEE5555"] = {"status": "failed"}
        real = bridge.BaseHTTPRequestHandler.send_response

        def boom(self, *a, **k):
            raise BrokenPipeError("reader vanished")

        monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", boom)
        try:
            _tick(base)
        except Exception:
            pass
        monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", real)
        assert _tick(base)["supportLogs"]["status"] == "failed"


def test_the_store_is_uid_bound_bounded_and_expires():
    now = time.time()
    for i in range(25):
        prefs.put_log_request(f"CODE{i:04d}", {"uid": "u1", "at": now - 100 + i})
    got = prefs.get_log_requests("u1")
    assert len(got) == prefs._LOG_REQUESTS_MAX
    assert "CODE0024" in got and "CODE0000" not in got, "oldest out first"
    assert prefs.get_log_requests("u2") == {}
    assert prefs.get_log_requests("") == {}
    prefs.put_log_request("OLDCODE1", {"uid": "u1", "at": now - prefs._LOG_REQUEST_TTL - 5})
    assert prefs.get_log_request("OLDCODE1", "u1") is None
    assert prefs.update_log_request("CODE0024", "u2", {"announced": True}) is False
    assert prefs.update_log_request("CODE0024", "u1", {"announced": True}) is True
    assert prefs.get_log_request("CODE0024", "u1")["announced"] is True


def test_the_status_check_still_knows_the_device_after_a_restart(monkeypatch):
    """`GET /logs/bundle` enriches a missing row from the parked record — which a
    restart used to wipe, collapsing it back to the old non-answer."""
    _ask("FFFF6666")

    class _BFS(_FS):
        def get_device_command(self, device_id, command_id):
            return None

        def list_devices(self, uid):
            return []

    with _bridge(monkeypatch) as (base, _state):
        monkeypatch.setattr(bridge, "FirestoreRest", _BFS)
        body = requests.get(base + "/logs/bundle?code=FFFF6666", timeout=10).json()
    assert body["deviceName"] == "Mac" and "ageSeconds" in body
