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

import datetime
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge
from facade.firestore_rest import FirestoreError, FirestoreRest

# The REAL helper, taken before conftest's autouse stub replaces it for every test
# (the pattern test_connection_code_0925 uses). The two F23 tests below drive it,
# with `config.FE_BASE` still pointed at conftest's dead port.
_REAL_FE_API_POST = bridge._fe_api_post


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
    # Held so a test can make the sign-in refresh fail (wave 12 repair).
    sess = SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "tok")
    state.set_session(sess)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    # A short poll, so `shutdown()` returns in 50 ms rather than the default half
    # second — this file runs once per mutant in the wave's harness.
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    try:
        yield SimpleNamespace(base=f"http://127.0.0.1:{port}", box=box, sess=sess)
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


@pytest.mark.parametrize("fields, was", [
    ({"visibility": "public", "allowAll": True}, True),
    ({"visibility": "public"}, False),
    ({"visibility": "public", "allowAll": "true"}, False),   # strict, as every reader
])
def test_going_private_says_whether_the_door_was_open(live, fields, was):
    """⛔ WAVE 12 REPAIR (cross-verify F26). Going private switches Allow all off
    as well, and an owner reads that as "everyone who joined is gone" — the
    machine says they keep access, the chat could not, because nothing in the
    reply said the door had been open. `allowAllWas` is the EFFECTIVE setting
    before the change, read from the row, not from what was asked."""
    _owned(**fields)
    r = _vis(live, visibility="private")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["changed"] is True and got["visibility"] == "private"
    assert got["allowAllWas"] is was


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


# ── wave 12 repair (cross-verify F3): a working default is never moved ───────
# ⛔⛔ "NOTHING SAVED" IS NOT "NOTHING ROUTABLE". Somebody who owns one computer
# has no saved choice because the sole-device rung sends every unnamed research
# there; selecting the joined computer moved all of it onto a stranger's machine.
# Executed against the wave's code: the router picked dev-a1 before the join and
# dev-j9 after it.

def _online(d):
    return dict(d, lastHeartbeat=int(time.time() * 1000))


def _routed_after_join(live):
    """Where the NEXT unnamed research goes: the router itself, run on the list as
    it stands after the join (the joined computer on it) and the choice the join
    left saved. The only pin that measures the outcome — see repair 2 below."""
    return bridge._pick_device_from([dict(d) for d in FakeFS.devices],
                                    live.box["sel"])[0]


def test_a_join_never_moves_research_off_the_joiners_own_sole_computer(live, monkeypatch):
    # RE-AIMED 2026-09-27 (repair 2, G8): this asserted `sel is None`, which the
    # broken routing satisfied — with nothing saved the joined computer is a
    # second runnable device and the router asked "which computer?". It now asks
    # the router where the next research goes.
    FakeFS.devices = [dict(OWNED), dict(JOINED)]
    r = _ask(live, monkeypatch)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "joined" and got["selected"] is False
    assert _routed_after_join(live) == "dev-a1"


def test_a_join_never_takes_the_one_online_computer_the_router_would_use(live, monkeypatch):
    """Two computers of the person's own, one switched on: the sole-online rung
    routes every unnamed research to it. That is a working default too."""
    # RE-AIMED 2026-09-27 (repair 2, G8): `sel is None` left the joined computer
    # as a second online one, so the router asked "which computer?" every time.
    FakeFS.devices = [_online(OWNED), dict(SHARED), _online(JOINED)]
    got = _ask(live, monkeypatch).json()
    assert got["selected"] is False and _routed_after_join(live) == "dev-a1"


def test_a_gone_selection_beside_a_computer_that_would_run_it_is_not_replaced(live, monkeypatch):
    """A saved choice that no longer exists is dropped by the run path, which then
    routes to the sole computer left — the person's own. The join must not step in
    between with a stranger's."""
    # RE-AIMED 2026-09-27 (repair 2, G8): `sel != "dev-j9"` held while the gone
    # choice stayed saved — and the router then dropped it and went to the only
    # computer ONLINE, the stranger's.
    FakeFS.devices = [dict(OWNED), _online(JOINED)]
    live.box["sel"] = "dev-gone"
    got = _ask(live, monkeypatch).json()
    assert got["selected"] is False and _routed_after_join(live) == "dev-a1"


def test_an_unread_list_selects_nothing_even_with_nothing_saved(live, monkeypatch):
    """⛔ UNKNOWN IS NOT EMPTY. A list that could not be read cannot say whether
    the person had a computer of their own, so the join answers — and selects
    nothing."""
    FakeFS.list_error = FirestoreError("boom", status=503)
    r = _ask(live, monkeypatch)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "joined" and r.json()["selected"] is False
    assert live.box["sel"] is None


def test_a_saved_choice_part_way_through_a_reset_is_kept(live, monkeypatch):
    """Still the person's machine and still their choice (the picker's own rule),
    even though it cannot take work this minute."""
    FakeFS.devices = [dict(OWNED, pairState="awaiting-re-pair"), dict(JOINED)]
    live.box["sel"] = "dev-a1"
    got = _ask(live, monkeypatch).json()
    assert got["selected"] is False and live.box["sel"] == "dev-a1"


def test_a_fleet_box_with_no_computer_gets_the_joined_one_and_its_topic(live, monkeypatch):
    """⭐ THE SPEC'S FLEET CASE, UNCHANGED: nothing was routable, so the joined
    computer is selected and the topic held for it starts there."""
    FakeFS.devices = [dict(JOINED)]
    live.box["held"] = {"topic": "Mars", "origin": ORIGIN, "at": 1.0}
    got = _ask(live, monkeypatch).json()
    assert got["selected"] is True and live.box["sel"] == "dev-j9"
    assert got["autoStarted"] is True
    assert live.box["enq"][0]["deviceId"] == "dev-j9"


# ── wave 12 repair 2 (cross-verify G8): the router's answer after the join ───
# ⛔⛔ REPAIR 1 STOPPED THE JOIN SAVING A STRANGER'S COMPUTER, AND ITS TESTS
# ASSERTED EXACTLY THAT — `sel is None`, which the broken routing satisfied. With
# nothing saved the joined computer is a SECOND runnable device, so the sole-
# device rung stops: asleep at home, the next unnamed research ran on the
# stranger's computer and AI accounts; both awake, every one asked "which
# computer?". Executed against repair 1: before the join the router picked
# dev-a1, after it dev-j9 (or nothing). So the join now SAVES the computer the
# router was already using, and each row below asks the router itself where the
# next research goes — nothing else can make these pass.
#
# Rows: (who is on the list, each marked online or not; what was saved; where
# the next research must go; whether the reply says the joined one is selected).
# Built inside the test: a heartbeat stamped at collection could age out of the
# online window before a long suite reached it.

# The person's own computer part-way through a Reset (awaiting its re-pair), with
# no deadline on the record — which the web app reads as a window still open.
OWNED_RESET = dict(OWNED, pairState="awaiting-re-pair")
# A second computer of the person's own, ready to run.
OWNED_TWO = {"id": "dev-a3", "name": "Old laptop", "ownerUid": "u1",
             "pairConfirmedAt": True, "lastHeartbeat": 0}

_G8_ROWS = [
    # ⛔⛔ wave 12 repair 3 (cross-verify H9): the sole owner mid-Reset routes to
    # nothing before the join, and the join saved the stranger's computer — which
    # stayed their choice after the re-pair. Their own is held, as the web app's
    # `heldThroughReset` holds it: until the re-pair the next research is refused
    # by name (None), never sent to the joined computer.
    ("sole-owner-mid-reset", [(OWNED_RESET, True), (JOINED, True)], None, None, False),
    ("sole-owner-mid-reset-both-asleep", [(OWNED_RESET, False), (JOINED, False)], None,
     None, False),
    # …and the hold is only for when nothing routed: a computer of theirs that CAN
    # run is the router's pick, and is saved, over the one waiting on its re-pair
    ("own-mid-reset-beside-own-ready", [(OWNED_RESET, False), (OWNED_TWO, False),
                                        (JOINED, True)], None, "dev-a3", False),
    # the sole owner — the case the finding names, in every power state
    ("sole-owner-online", [(OWNED, True), (JOINED, True)], None, "dev-a1", False),
    ("sole-owner-asleep-joined-online", [(OWNED, False), (JOINED, True)], None,
     "dev-a1", False),
    ("sole-owner-both-asleep", [(OWNED, False), (JOINED, False)], None, "dev-a1", False),
    # two of the person's own, one switched on: the sole-online rung's pick is kept
    ("two-own-one-online", [(OWNED, True), (SHARED, False), (JOINED, True)], None,
     "dev-a1", False),
    # a saved choice that is gone, beside the person's own computer
    ("gone-choice-beside-own", [(OWNED, False), (JOINED, True)], "dev-gone",
     "dev-a1", False),
    # a working saved choice is never touched — not even by the router's own pick
    ("working-choice-kept", [(OWNED, True), (SHARED, False), (JOINED, True)],
     "dev-b2", "dev-b2", False),
    # ⭐ UNCHANGED: nothing routed before, so the joined computer is selected
    ("fleet-no-own-computer", [(JOINED, True)], None, "dev-j9", True),
    ("fleet-no-own-computer-asleep", [(JOINED, False)], None, "dev-j9", True),
    ("two-own-asleep-nothing-saved", [(OWNED, False), (SHARED, False), (JOINED, True)],
     None, "dev-j9", True),
    ("two-own-online-nothing-saved", [(OWNED, True), (SHARED, True), (JOINED, True)],
     None, "dev-j9", True),
]


@pytest.mark.parametrize("devices,saved,want,selected",
                         [r[1:] for r in _G8_ROWS], ids=[r[0] for r in _G8_ROWS])
def test_after_a_join_the_router_sends_research_where_it_went_before(
        live, monkeypatch, devices, saved, want, selected):
    FakeFS.devices = [_online(d) if on else dict(d) for d, on in devices]
    live.box["sel"] = saved
    r = _ask(live, monkeypatch)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "joined"
    assert _routed_after_join(live) == want
    assert got["selected"] is selected


# ── wave 12 repair 3 (cross-verify H9): a join inside the person's own Reset ─
# ⛔⛔ THE FINDING'S OWN MEASUREMENT IS AFTER THE RE-PAIR. Executed against repair
# 2: with no join the router went to dev-a1 once the re-pair landed; with the
# join it went to dev-j9, because the join had saved the stranger's computer.

def test_a_join_during_the_owners_reset_leaves_their_research_on_their_computer(
        live, monkeypatch):
    FakeFS.devices = [dict(OWNED_RESET), _online(JOINED)]
    got = _ask(live, monkeypatch).json()
    assert got["status"] == "joined" and got["selected"] is False
    assert live.box["sel"] == "dev-a1"
    # Until the re-pair, an unnamed research is refused by name — never moved.
    assert bridge._pick_device_from([dict(d) for d in FakeFS.devices],
                                    live.box["sel"]) == (None, "selection_not_ready", False)
    # The re-pair lands: the person's computer is active again, and both are awake.
    FakeFS.devices = [_online(OWNED), _online(JOINED)]
    assert _routed_after_join(live) == "dev-a1"


def test_a_saved_shared_choice_part_way_through_a_reset_is_kept(live, monkeypatch):
    """The saved choice is kept whoever owns it — a computer somebody shared, being
    Reset by its owner, is still the one this person chose. (Keeps wave 12 repair
    1's B4 measurable: the hold below finds only the person's OWN computers.)"""
    FakeFS.devices = [dict(SHARED, pairState="awaiting-re-pair"), _online(JOINED)]
    live.box["sel"] = "dev-b2"
    got = _ask(live, monkeypatch).json()
    assert got["selected"] is False and live.box["sel"] == "dev-b2"


def _rfc3339(offset_ms):
    """A Firestore REST timestamp `offset_ms` from now, as `from_value` hands it
    over: the RFC 3339 string."""
    at = datetime.datetime.fromtimestamp(time.time() + offset_ms / 1000,
                                         tz=datetime.timezone.utc)
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


_MIN = 60_000

# ⭐ THE WEB APP'S HOLD, RULE FOR RULE (`heldThroughReset` / `isResetWindowOpen`):
# only a computer the person OWNS, only `awaiting-re-pair`, only while the window
# is open — two minutes' grace past the deadline for a fast clock, and a missing
# or unreadable deadline counts as open. Past it, a Reset nobody re-paired is not
# held, and the joined computer is chosen as it would be with nothing routable.
# Rows: (the person's computer, its pairState, its deadline or None, what the
# join must save, whether the reply says the joined one is selected).
_RESET_HOLD_ROWS = [
    ("deadline-ahead", OWNED, "awaiting-re-pair", 10 * _MIN, "dev-a1", False),
    ("deadline-passed-inside-the-grace", OWNED, "awaiting-re-pair", -1 * _MIN,
     "dev-a1", False),
    ("deadline-passed", OWNED, "awaiting-re-pair", -10 * _MIN, "dev-j9", True),
    ("unreadable-deadline-counts-open", OWNED, "awaiting-re-pair", "not a time",
     "dev-a1", False),
    ("someone-elses-computer-mid-reset", SHARED, "awaiting-re-pair", None,
     "dev-j9", True),
    ("first-pairing-is-not-a-reset", OWNED, "awaiting-initial-claim", None,
     "dev-j9", True),
]


@pytest.mark.parametrize("base,pair_state,deadline,want,selected",
                         [r[1:] for r in _RESET_HOLD_ROWS],
                         ids=[r[0] for r in _RESET_HOLD_ROWS])
def test_the_join_holds_a_reset_exactly_as_the_web_app_does(
        live, monkeypatch, base, pair_state, deadline, want, selected):
    mine = dict(base, pairState=pair_state)
    if deadline is not None:
        mine["pairCodeExpiresAt"] = (_rfc3339(deadline) if isinstance(deadline, int)
                                     else deadline)
    FakeFS.devices = [mine, _online(JOINED)]
    got = _ask(live, monkeypatch).json()
    assert got["status"] == "joined"
    assert live.box["sel"] == want
    assert got["selected"] is selected


# ── wave 12 repair (cross-verify F23): unconfirmed only if something was sent ─

def test_a_sign_in_that_could_not_refresh_sent_nothing_and_says_so(live, monkeypatch):
    """⛔⛔ THE REAL HELPERS, NOTHING STUBBED BUT THE SIGN-IN. A refresh that fails
    before the request leaves came back from `_fe_api_post` as status 0 — the same
    status as a timeout — and was answered "that may have gone through", sending
    somebody to look for an ask that was never made. It is an ordinary failure
    now, with its own code, and nothing reaches the web app."""
    monkeypatch.setattr(bridge, "_fe_api_post", _REAL_FE_API_POST)

    def _boom(force=False):
        raise ConnectionError("token endpoint unreachable")
    live.sess.id_token = _boom
    to_app: list = []
    real_post = requests.post

    def _spy(url, *a, **kw):
        if str(url).startswith(bridge.config.FE_BASE):
            to_app.append(url)
        return real_post(url, *a, **kw)
    monkeypatch.setattr(requests, "post", _spy)
    r = real_post(live.base + "/device/ask", json={"deviceId": "dev-j9",
                                                   "origin": ORIGIN})
    assert r.status_code == 502, r.text
    assert r.json() == {"reason": "ask_not_sent", "error": "ask_not_sent"}
    assert to_app == []
    assert live.box["ask"] is None


def test_a_timeout_after_the_request_left_is_still_unconfirmed(live, monkeypatch):
    """The other half, through the same real helper: the request went out and the
    answer did not come back, so it may sit on a committed join."""
    monkeypatch.setattr(bridge, "_fe_api_post", _REAL_FE_API_POST)
    real_post = requests.post

    def _timeout(url, *a, **kw):
        if str(url).startswith(bridge.config.FE_BASE):
            raise requests.ReadTimeout("slow")
        return real_post(url, *a, **kw)
    monkeypatch.setattr(requests, "post", _timeout)
    r = real_post(live.base + "/device/ask", json={"deviceId": "dev-j9"})
    assert r.status_code == 502, r.text
    assert r.json()["reason"] == "ask_unconfirmed"


# ── wave 12 repair 3 (cross-verify H18): a connection that never opened ──────
# ⛔⛔ A REFUSED PORT, A NAME THAT DID NOT RESOLVE AND A CONNECT TIMEOUT SEND
# NOTHING, and all three were answered "that may have gone through". Executed
# against repair 2: the real `_fe_api_post` at conftest's dead port gave 502
# ask_unconfirmed. Everything below goes through the REAL helper, the real
# `requests` and the real urllib3; where the network's answer cannot be had
# deterministically (a DNS failure, a connect timeout) only the OS call urllib3
# makes is answered, for the web app's host alone, so the library builds the
# exception exactly as it would in the field.

_NOT_SENT = {"reason": "ask_not_sent", "error": "ask_not_sent"}


def _real_ask(live, monkeypatch, fe_base=None):
    monkeypatch.setattr(bridge, "_fe_api_post", _REAL_FE_API_POST)
    if fe_base is not None:
        monkeypatch.setattr(bridge.config, "FE_BASE", fe_base)
    return requests.post(live.base + "/device/ask",
                         json={"deviceId": "dev-j9", "origin": ORIGIN})


def _answer_connect_for(monkeypatch, host, exc):
    """urllib3's own connect call raises `exc` for `host` only — the bridge's
    loopback port keeps working."""
    import urllib3.util.connection as u3conn
    real = u3conn.create_connection

    def _fake(address, *a, **kw):
        if address[0] == host:
            raise exc
        return real(address, *a, **kw)
    monkeypatch.setattr(u3conn, "create_connection", _fake)


def test_a_refused_connection_sent_nothing_and_says_so(live, monkeypatch):
    """Conftest's dead port, a real refusal from this machine's own stack."""
    r = _real_ask(live, monkeypatch)
    assert r.status_code == 502, r.text
    assert r.json() == _NOT_SENT
    assert live.box["ask"] is None


def test_a_name_that_did_not_resolve_sent_nothing_and_says_so(live, monkeypatch):
    _answer_connect_for(monkeypatch, "sr-app.invalid",
                        socket.gaierror(8, "nodename nor servname provided"))
    r = _real_ask(live, monkeypatch, fe_base="http://sr-app.invalid")
    assert r.status_code == 502, r.text
    assert r.json() == _NOT_SENT


def test_a_connect_timeout_sent_nothing_and_says_so(live, monkeypatch):
    _answer_connect_for(monkeypatch, "sr-app.invalid", socket.timeout("timed out"))
    r = _real_ask(live, monkeypatch, fe_base="http://sr-app.invalid")
    assert r.status_code == 502, r.text
    assert r.json() == _NOT_SENT


def test_a_server_that_took_the_ask_and_hung_up_is_still_unconfirmed(live, monkeypatch):
    """⛔⛔ THE OTHER SIDE OF THE LINE, WITH A REAL SOCKET. `requests` calls this a
    ConnectionError too — but the request LEFT, and on a computer that lets
    anyone join it may sit on a committed join. Only a connection that never
    opened is "not sent"."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(10)
    got: list = []

    def _take_and_hang_up():
        try:
            conn, _ = srv.accept()
            with conn:
                conn.settimeout(10)
                got.append(conn.recv(65536))
        except OSError:
            pass
    t = threading.Thread(target=_take_and_hang_up, daemon=True)
    t.start()
    try:
        r = _real_ask(live, monkeypatch,
                      fe_base=f"http://127.0.0.1:{srv.getsockname()[1]}")
    finally:
        t.join(10)
        srv.close()
    assert got and got[0].startswith(b"POST /api/devices/access-request"), got
    assert r.status_code == 502, r.text
    assert r.json()["reason"] == "ask_unconfirmed"


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
