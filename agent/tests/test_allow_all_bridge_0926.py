"""Allow all, on the bridge (wave 12, 2026-09-26).

⛔⛔ WHAT THIS CODE DECIDES. Whether an owner's "let anyone join" lands as ONE
write that also makes the computer public; whether "stop letting anyone join" and
"make it private" actually close the door instead of answering "already public";
whether an old tick can come back unasked when a computer is re-published; and,
on the joiner's side, whether an instant join is announced once and puts the
research the person asked for onto the computer they just joined.

Every test here drives the real handler over HTTP against a stubbed Firestore and
web app — nothing reads the source to decide what the code does.
"""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge
from facade.firestore_rest import FirestoreError, FirestoreRest


class FakeFS:
    """Records every device write IN ORDER — the order is half the contract."""
    devices: list[dict] = []
    writes: list[tuple] = []
    raise_vis: Exception | None = None
    raise_all: Exception | None = None
    list_error: Exception | None = None

    def __init__(self, _token_provider):
        pass

    def list_devices(self, uid):
        if FakeFS.list_error is not None:
            raise FakeFS.list_error
        return [dict(d) for d in FakeFS.devices]

    def set_device_visibility(self, device_id, value):
        if FakeFS.raise_vis is not None:
            raise FakeFS.raise_vis
        FakeFS.writes.append(("visibility", device_id, value))

    def set_device_allow_all(self, device_id, value, *, publish=False):
        if FakeFS.raise_all is not None:
            raise FakeFS.raise_all
        FakeFS.writes.append(("allowAll", device_id, value, publish))


OWNED = {"id": "dev-a1", "name": "Studio PC", "ownerUid": "u1",
         "pairConfirmedAt": True, "lastHeartbeat": 0}
SHARED = {"id": "dev-b2", "name": "Their Mac", "ownerUid": "u9",
          "pairConfirmedAt": True, "lastHeartbeat": 0}
# The computer somebody joins at once — a stranger's, so not owned here.
JOINED = {"id": "dev-j9", "name": "DG shared research computer", "ownerUid": "u7",
          "pairConfirmedAt": True, "lastHeartbeat": 0}


@pytest.fixture()
def live(monkeypatch):
    FakeFS.devices = [dict(OWNED), dict(SHARED)]
    FakeFS.writes = []
    FakeFS.raise_vis = None
    FakeFS.raise_all = None
    FakeFS.list_error = None
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    box = {"sel": None, "ask": None, "held": None, "enq": [], "set_ask": 0}
    p = bridge.prefs
    monkeypatch.setattr(p, "get_selected_device", lambda uid: box["sel"])
    monkeypatch.setattr(p, "set_selected_device", lambda d, uid: box.__setitem__("sel", d))
    monkeypatch.setattr(p, "clear_selected_device", lambda: box.__setitem__("sel", None))

    def _set_ask(rec, uid):
        box["set_ask"] += 1
        box["ask"] = rec
    monkeypatch.setattr(p, "set_device_ask", _set_ask)
    monkeypatch.setattr(p, "get_device_ask", lambda uid: box["ask"])
    monkeypatch.setattr(p, "clear_device_ask", lambda: box.__setitem__("ask", None))
    monkeypatch.setattr(p, "get_held_research", lambda uid: box["held"])
    monkeypatch.setattr(p, "set_held_research", lambda rec, uid: box.__setitem__("held", rec))
    monkeypatch.setattr(p, "clear_held_research", lambda: box.__setitem__("held", None))
    monkeypatch.setattr(bridge, "_resolve_run_config", lambda fs, sess, cfg: {})

    def _enqueue(fs, sess, *, topic, device_id, cfg, origin):
        # What a watcher answering an older parked ask in the same second would
        # see: the hold, as it stands while this run is being enqueued.
        box["held_at_enqueue"] = box["held"]
        if box.get("enq_error") is not None:
            raise box["enq_error"]
        box["enq"].append({"topic": topic, "deviceId": device_id, "origin": origin})
        return "run-1", "q-1"
    monkeypatch.setattr(bridge, "_enqueue_research_run", _enqueue)
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    # A short poll, so `shutdown()` returns in 50 ms rather than the default half
    # second — this file runs once per mutant in the wave's harness.
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    try:
        yield SimpleNamespace(base=f"http://127.0.0.1:{port}", box=box)
    finally:
        httpd.shutdown()
        httpd.server_close()


def _vis(live, **body):
    body.setdefault("deviceId", "dev-a1")
    return requests.post(live.base + "/device/visibility", json=body)


def _owned(**fields):
    FakeFS.devices = [dict(OWNED, **fields), dict(SHARED)]


# ── the owner's switch: /device/visibility with allowAll ─────────────────────

def test_allow_all_on_a_private_computer_is_one_write_that_also_publishes(live):
    """⛔⛔ THE OWNER'S "allow all would by default make it public". Before this
    wave the bridge ignored `allowAll`, so a private computer got a plain publish
    and no allow-all at all — or, split into two writes, a lagging ruleset could
    land one without the other."""
    _owned(visibility="private")
    r = _vis(live, visibility="public", allowAll=True)
    assert r.status_code == 200, r.text
    assert FakeFS.writes == [("allowAll", "dev-a1", True, True)]
    body = r.json()
    assert body["changed"] is True
    assert body["visibility"] == "public" and body["allowAll"] is True


def test_allow_all_on_an_already_public_computer_still_writes(live):
    """⛔⛔ THE NO-OP CHECK COMPARES BOTH FIELDS. Comparing visibility alone
    answered "already public" to "let anyone join" and never wrote anything."""
    _owned(visibility="public")
    r = _vis(live, allowAll=True)
    assert r.status_code == 200, r.text
    assert FakeFS.writes == [("allowAll", "dev-a1", True, True)]
    assert r.json()["changed"] is True and r.json()["allowAll"] is True


@pytest.mark.parametrize("body", [{"allowAll": False},
                                  {"visibility": "public", "allowAll": False}])
def test_allow_all_off_writes_only_allow_all_and_the_computer_stays_public(live, body):
    """⛔⛔ "Stop letting anyone join" on a public computer was answered "it is
    already public" and never written — the door stayed open. The narrowing write
    carries `allowAll` alone, so a lagging ruleset can only refuse, never widen."""
    _owned(visibility="public", allowAll=True)
    r = _vis(live, **body)
    assert r.status_code == 200, r.text
    assert FakeFS.writes == [("allowAll", "dev-a1", False, False)]
    got = r.json()
    assert got["changed"] is True
    assert got["visibility"] == "public" and got["allowAll"] is False


def test_going_private_is_its_own_write_first_then_clears_allow_all(live):
    """⛔⛔ A NARROWING WRITE IS NEVER BLOCKED BY THE FIELD IT DOES NOT NEED. The
    private write carries `visibility` alone and goes FIRST; the stored tick is
    cleared after it, so a Public-on later does not reopen the door unasked.
    Before this wave only the first write existed and the tick survived."""
    _owned(visibility="public", allowAll=True)
    r = _vis(live, visibility="private")
    assert r.status_code == 200, r.text
    assert FakeFS.writes == [("visibility", "dev-a1", "private"),
                             ("allowAll", "dev-a1", False, False)]
    assert r.json()["visibility"] == "private" and r.json()["allowAll"] is False


def test_going_private_with_no_stored_tick_makes_exactly_todays_write(live):
    _owned(visibility="public")
    r = _vis(live, visibility="private")
    assert r.status_code == 200, r.text
    assert FakeFS.writes == [("visibility", "dev-a1", "private")]


def test_a_failed_clear_after_going_private_does_not_fail_the_hide(live):
    """The door is shut by the first write — every reader gates on public — so a
    refused best-effort clear must not turn a hide that landed into a failure."""
    _owned(visibility="public", allowAll=True)
    FakeFS.raise_all = FirestoreError("denied", status=403)
    r = _vis(live, visibility="private")
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is True and r.json()["visibility"] == "private"
    assert FakeFS.writes == [("visibility", "dev-a1", "private")]


def test_republishing_clears_an_old_tick_in_the_same_patch(live):
    """⛔⛔ AN OLD TICK NEVER COMES BACK UNASKED. A private computer still
    carrying `allowAll: true` (left by an older writer) was re-published with a
    plain visibility write — and was instantly letting strangers in again."""
    _owned(visibility="private", allowAll=True)
    r = _vis(live, visibility="public")
    assert r.status_code == 200, r.text
    assert FakeFS.writes == [("allowAll", "dev-a1", False, True)]
    assert r.json()["visibility"] == "public" and r.json()["allowAll"] is False


def test_republishing_with_no_stored_field_writes_what_it_always_did(live):
    _owned(visibility="private")
    r = _vis(live, visibility="public")
    assert r.status_code == 200, r.text
    assert FakeFS.writes == [("visibility", "dev-a1", "public")]


def test_private_and_allow_all_together_is_refused_before_anything_is_read(live):
    """A private computer cannot let anyone join; saying both is a contradiction,
    and guessing which half was meant is worse than asking."""
    FakeFS.list_error = AssertionError("the row must not be read")
    r = _vis(live, visibility="private", allowAll=True)
    assert r.status_code == 400
    assert r.json()["reason"] == "allow_all_private"
    assert FakeFS.writes == []


@pytest.mark.parametrize("junk", ["yes", 1, 0, None, "true"])
def test_a_non_boolean_allow_all_is_refused(live, junk):
    """The rules refuse a non-bool and refuse the WHOLE update with it — so a typo
    would fail a write the owner believes they made. `None` is an explicit value
    here, not "absent": it carries the key."""
    FakeFS.list_error = AssertionError("the row must not be read")
    r = _vis(live, visibility="public", allowAll=junk)
    assert r.status_code == 400
    assert r.json()["reason"] == "allow_all_required"
    assert FakeFS.writes == []


def test_neither_field_is_still_refused(live):
    r = _vis(live)
    assert r.status_code == 400
    assert r.json()["reason"] == "visibility_required"


def test_allow_all_off_on_a_private_computer_clears_a_leftover_quietly(live):
    """Nothing to change in effect — a private computer lets nobody in — but a
    stored tick would come back with an old writer's re-publish, so it is cleared."""
    _owned(visibility="private", allowAll=True)
    r = _vis(live, allowAll=False)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["changed"] is False
    assert got["visibility"] == "private" and got["allowAll"] is False
    assert FakeFS.writes == [("allowAll", "dev-a1", False, False)]


def test_allow_all_off_on_a_private_computer_with_nothing_stored_writes_nothing(live):
    _owned(visibility="private")
    r = _vis(live, allowAll=False)
    assert r.status_code == 200 and r.json()["changed"] is False
    assert FakeFS.writes == []


def test_the_no_op_carries_allow_all(live):
    _owned(visibility="public", allowAll=True)
    r = _vis(live, visibility="public", allowAll=True)
    assert r.status_code == 200
    assert r.json()["changed"] is False and r.json()["allowAll"] is True
    assert FakeFS.writes == []


def test_a_flagless_public_on_an_allow_all_computer_leaves_it_alone(live):
    """⛔ "make it public" on a computer that already lets anyone join is not a
    request to switch allow-all off."""
    _owned(visibility="public", allowAll=True)
    r = _vis(live, visibility="public")
    assert r.status_code == 200
    assert r.json()["changed"] is False and r.json()["allowAll"] is True
    assert FakeFS.writes == []


def test_a_refused_allow_all_write_says_nothing_changed_and_reports_both(live):
    _owned(visibility="public")
    FakeFS.raise_all = FirestoreError("denied", status=403)
    r = _vis(live, allowAll=True)
    assert r.status_code == 403
    got = r.json()
    assert got["reason"] == "visibility_refused"
    assert got["visibility"] == "public" and got["allowAll"] is False


def test_an_unconfirmed_allow_all_write_promises_nothing(live):
    _owned(visibility="public")
    FakeFS.raise_all = FirestoreError("boom", status=503)
    r = _vis(live, allowAll=True)
    assert r.status_code == 502
    got = r.json()
    assert got["reason"] == "visibility_unconfirmed"
    assert got["visibility"] is None and got["allowAll"] is None


def test_a_sharer_cannot_switch_allow_all(live):
    r = _vis(live, deviceId="dev-b2", allowAll=True)
    assert r.status_code == 403 and r.json()["reason"] == "not_owner"
    assert FakeFS.writes == []


# ── rows: the effective allow-all rides on every own row ─────────────────────

@pytest.mark.parametrize("fields, want", [
    ({"visibility": "public", "allowAll": True}, True),
    ({"joinPolicy": "public", "allowAll": True}, True),     # the new name reads too
    ({"visibility": "private", "allowAll": True}, False),   # a leftover does nothing
    ({"visibility": "public", "allowAll": "true"}, False),  # strict: only True
    ({"visibility": "public", "allowAll": 1}, False),
    ({"visibility": "public"}, False),
    ({}, False),
])
def test_own_rows_carry_the_effective_allow_all(live, fields, want):
    """⛔⛔ THE ROW IS PRUNED TO AN ALLOW-LIST, so a raw `allowAll` never reached
    either client and "is my computer letting anyone in?" had no answer. Effective
    means public AND strictly true — a private computer's leftover reads false."""
    _owned(**fields)
    rows = requests.get(live.base + "/devices").json()["devices"]
    row = next(d for d in rows if d["id"] == "dev-a1")
    assert row["allowAll"] is want


@pytest.mark.parametrize("row, want", [
    ({"joinPolicy": "public", "allowAll": True}, True),
    ({"visibility": "private", "joinPolicy": "public", "allowAll": True}, False),
    ({"visibility": "public", "allowAll": "true"}, False),
])
def test_the_reader_itself_goes_through_discovery(row, want):
    """⛔⛔ The contract every reader shares: public by `_discovery_of` (the OLD
    name first), never the literal `visibility` field. The own-row decorator
    happens to resolve `visibility` before it asks, so the row test above cannot
    see a reader that reads the literal field — this asks the reader directly, on
    a RAW row: a computer public under `joinPolicy` alone is allow-all, and one
    whose old name says private is not, whatever the new name says."""
    assert bridge._allow_all_of(dict(row)) is want


# ── the public list: allowAll passes the prune ───────────────────────────────

def test_the_public_list_passes_allow_all_through(live, monkeypatch):
    """⛔⛔ `_PUBLIC_DEVICE_KEYS` IS A STRICT ALLOW-LIST. Without the new key the
    web app's bit was pruned silently and every row read as "ask the owner"."""
    rows = [{"deviceId": "dev-j9", "label": "DG shared", "osFamily": "linux",
             "online": True, "full": False, "allowAll": True},
            {"deviceId": "dev-k1", "label": "Lab Mac", "osFamily": "macos",
             "online": True, "full": False, "allowAll": False}]
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda s, p, params=None, **kw: (200, {"devices": rows,
                                                               "truncated": False}))
    got = requests.get(live.base + "/devices/public").json()["devices"]
    assert [d["allowAll"] for d in got] == [True, False]


# ── the joiner's side: /device/ask answered "joined" ──────────────────────────

ORIGIN = {"platform": "telegram", "chat_id": "42"}


def _ask(live, monkeypatch, reply=None, origin=True, seen=None):
    reply = reply if reply is not None else (200, {"ok": True, "status": "joined",
                                                   "deviceId": "dev-j9",
                                                   "deviceName": "DG shared"})

    def _post(sess, path, payload, retry_401=True, timeout=None, **_kw):
        if seen is not None:
            seen.update(path=path, payload=payload, timeout=timeout)
        return reply
    monkeypatch.setattr(bridge, "_fe_api_post", _post)
    body = {"deviceId": "dev-j9"}
    if origin:
        body["origin"] = ORIGIN
    return requests.post(live.base + "/device/ask", json=body)


def test_a_join_is_never_parked_for_the_watcher(live, monkeypatch):
    """⛔⛔ PARKED LIKE A PENDING ASK, THE WATCHER SAW THE ROW GONE PLUS A
    MEMBERSHIP and announced "You're in" a second time about a minute later."""
    FakeFS.devices.append(dict(JOINED))
    r = _ask(live, monkeypatch)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "joined"
    assert live.box["set_ask"] == 0 and live.box["ask"] is None


def test_a_pending_ask_is_still_parked(live, monkeypatch):
    r = _ask(live, monkeypatch, reply=(200, {"ok": True, "status": "pending"}))
    assert r.json()["status"] == "pending"
    assert live.box["ask"]["deviceId"] == "dev-j9"


def test_a_join_clears_a_parked_ask_for_that_computer_only(live, monkeypatch):
    FakeFS.devices.append(dict(JOINED))
    live.box["ask"] = {"deviceId": "dev-j9", "origin": ORIGIN, "at": 1.0}
    _ask(live, monkeypatch)
    assert live.box["ask"] is None
    live.box["ask"] = {"deviceId": "dev-other", "origin": ORIGIN, "at": 1.0}
    _ask(live, monkeypatch)
    assert live.box["ask"]["deviceId"] == "dev-other"


def test_a_join_selects_the_computer_when_nothing_is_selected(live, monkeypatch):
    """Without a selection, the next "research X" asked "which computer?" of
    somebody who had just been let onto one."""
    FakeFS.devices.append(dict(JOINED))
    r = _ask(live, monkeypatch)
    assert r.json()["selected"] is True
    assert live.box["sel"] == "dev-j9"


def test_a_join_replaces_a_selection_that_no_longer_exists(live, monkeypatch):
    """A fleet box whose code-shared computer was taken away still pointed at it."""
    FakeFS.devices.append(dict(JOINED))
    live.box["sel"] = "dev-gone"
    r = _ask(live, monkeypatch)
    assert r.json()["selected"] is True and live.box["sel"] == "dev-j9"


def test_a_join_never_replaces_a_live_selection(live, monkeypatch):
    FakeFS.devices.append(dict(JOINED))
    live.box["sel"] = "dev-a1"
    r = _ask(live, monkeypatch)
    assert r.json()["selected"] is False and live.box["sel"] == "dev-a1"


def test_a_failed_list_never_replaces_a_saved_selection(live, monkeypatch):
    """Unknown is not stale: a list that could not be read proves nothing about
    the saved choice."""
    FakeFS.list_error = FirestoreError("boom", status=503)
    live.box["sel"] = "dev-a1"
    r = _ask(live, monkeypatch)
    assert r.status_code == 200
    assert r.json()["selected"] is False and live.box["sel"] == "dev-a1"


def test_a_join_starts_the_held_topic_on_the_joined_computer(live, monkeypatch):
    """⛔⛔ THE WATCHER WAS THE ONLY CODE THAT STARTED A HELD TOPIC, and a join
    never parks the watcher — so "research Mars" asked with no computer would sit
    held for six hours on a computer the person could already use."""
    FakeFS.devices.append(dict(JOINED))
    held_origin = {"platform": "telegram", "chat_id": "7"}
    live.box["held"] = {"topic": "Mars habitats", "origin": held_origin, "at": 1.0}
    r = _ask(live, monkeypatch)
    got = r.json()
    assert live.box["enq"] == [{"topic": "Mars habitats", "deviceId": "dev-j9",
                                "origin": held_origin}]
    assert got["autoStarted"] is True and got["runId"] == "run-1"
    assert got["topic"] == "Mars habitats"
    assert live.box["held"] is None


def test_a_join_keeps_the_topic_when_the_computer_is_not_ready(live, monkeypatch):
    FakeFS.devices.append(dict(JOINED, pairState="awaiting-re-pair"))
    live.box["held"] = {"topic": "Mars", "origin": ORIGIN, "at": 1.0}
    got = _ask(live, monkeypatch).json()
    assert live.box["enq"] == []
    assert got["autoStarted"] is False and got["usable"] is False
    assert got["topic"] == "Mars" and live.box["held"]["topic"] == "Mars"


def test_the_hold_is_claimed_before_the_run_is_enqueued(live, monkeypatch):
    """⛔⛔ get → enqueue → clear is not atomic. With the hold still standing while
    the run is enqueued, a watcher announcing an older parked ask in that same
    second finds the topic and starts it a SECOND time, on the same computer."""
    FakeFS.devices.append(dict(JOINED))
    live.box["held"] = {"topic": "Mars", "origin": ORIGIN, "at": 1.0}
    got = _ask(live, monkeypatch).json()
    assert got["autoStarted"] is True
    assert live.box["held_at_enqueue"] is None


def test_a_failed_start_puts_the_hold_back(live, monkeypatch):
    """The hold is claimed before the enqueue so a racing watcher cannot start it
    twice — and a failed enqueue must give it back, or the topic is lost."""
    FakeFS.devices.append(dict(JOINED))
    live.box["held"] = {"topic": "Mars", "origin": ORIGIN, "at": 1.0}
    live.box["enq_error"] = FirestoreError("boom", status=503)
    got = _ask(live, monkeypatch).json()
    assert got["autoStarted"] is False
    assert live.box["held"] == {"topic": "Mars", "origin": ORIGIN, "at": 1.0}


def test_a_terminal_join_never_starts_a_chat_held_topic(live, monkeypatch):
    """Same rule as the watcher: only an ask a chat is waiting on carries the
    topic that chat held."""
    FakeFS.devices.append(dict(JOINED))
    live.box["held"] = {"topic": "Mars", "origin": ORIGIN, "at": 1.0}
    got = _ask(live, monkeypatch, origin=False).json()
    assert live.box["enq"] == [] and live.box["held"]["topic"] == "Mars"
    assert got["autoStarted"] is False and "topic" not in got


def test_the_join_reply_keeps_the_keys_the_fleet_branches_on(live, monkeypatch):
    """⭐ THE DG HERMES FLEET READS THESE UNDER --json. Stable keys, stable types."""
    FakeFS.devices.append(dict(JOINED))
    got = _ask(live, monkeypatch).json()
    for key in ("ok", "status", "deviceId", "deviceName", "selected", "online",
                "usable", "autoStarted", "runId"):
        assert key in got, key
    assert got["deviceId"] == "dev-j9" and got["deviceName"] == "DG shared"
    assert got["online"] is False and got["usable"] is True and got["runId"] is None


def test_the_join_names_the_computer_from_its_row_when_the_app_does_not(live, monkeypatch):
    FakeFS.devices.append(dict(JOINED))
    got = _ask(live, monkeypatch,
               reply=(200, {"ok": True, "status": "joined"})).json()
    assert got["deviceName"] == "DG shared research computer"


def test_the_ask_gets_the_long_wait(live, monkeypatch):
    """⛔⛔ AN ASK IS NOW A GRANT — a transaction, a claims sync and a notice, the
    decide route's work. At the shared fifteen seconds a join that committed came
    back as a failure."""
    seen: dict = {}
    _ask(live, monkeypatch, reply=(200, {"ok": True, "status": "pending"}), seen=seen)
    assert seen["timeout"] == bridge._FE_ASK_TIMEOUT
    assert bridge._FE_ASK_TIMEOUT > bridge._FE_JSON_TIMEOUT


def test_a_timed_out_ask_is_unconfirmed_not_unreachable(live, monkeypatch):
    """A timeout may sit on a committed join; "couldn't reach the app" would send
    somebody to ask again, and the retry answers already_shared."""
    r = _ask(live, monkeypatch, reply=(0, {"error": "could not reach x (ReadTimeout)"}))
    assert r.status_code == 502
    assert r.json()["reason"] == "ask_unconfirmed"
    assert r.json()["error"] == "ask_unconfirmed"
    assert live.box["ask"] is None


def test_a_dead_session_on_the_ask_is_still_a_401(live, monkeypatch):
    r = _ask(live, monkeypatch, reply=(0, {"reason": "revoked", "error": "revoked"}))
    assert r.status_code == 401


# ── the Firestore writer: literal masks, checked values ──────────────────────

class _Rec(FirestoreRest):
    def __init__(self):
        self.calls = []

    def _request(self, method, url, json_body=None, **_kw):
        self.calls.append((method, url, json_body))
        return {}


@pytest.mark.parametrize("value, publish, masks, fields", [
    (True, False, ["visibility", "allowAll"], {"visibility": "public", "allowAll": True}),
    (True, True, ["visibility", "allowAll"], {"visibility": "public", "allowAll": True}),
    (False, True, ["visibility", "allowAll"], {"visibility": "public", "allowAll": False}),
    (False, False, ["allowAll"], {"allowAll": False}),
])
def test_the_allow_all_writer_sends_one_patch_with_literal_masks(value, publish,
                                                                 masks, fields):
    """⛔⛔ ALLOW ALL ON ALWAYS PUBLISHES, IN THE SAME PATCH — the one place that
    can make the two land atomically is the request itself."""
    fs = _Rec()
    fs.set_device_allow_all("dev-a1", value, publish=publish)
    assert len(fs.calls) == 1
    method, url, body = fs.calls[0]
    assert method == "PATCH"
    assert url.split("?", 1)[1].split("&") == [f"updateMask.fieldPaths={m}" for m in masks]
    got = {k: (v.get("booleanValue") if "booleanValue" in v else v.get("stringValue"))
           for k, v in body["fields"].items()}
    assert got == fields


@pytest.mark.parametrize("junk", ["yes", 1, None])
def test_the_allow_all_writer_refuses_a_non_boolean(junk):
    fs = _Rec()
    with pytest.raises(ValueError):
        fs.set_device_allow_all("dev-a1", junk)
    with pytest.raises(ValueError):
        fs.set_device_allow_all("dev-a1", False, publish=junk)
    assert fs.calls == []
