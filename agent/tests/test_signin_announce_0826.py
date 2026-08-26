"""The sign-in announce: durable, one clearing point, and a fourth outcome.

⛔⛔ WHAT THIS FILE IS FOR, because four of the five things it pins were REFUTED as
originally described and one was not in the plan at all.

The announce ("you are signed in — and here is what I did about the research you
asked for") lived only in `BridgeState._signed_in`, a dict in process memory, taken
and cleared by the first `/updates?via=agent` read. So a bridge restart in the
window between the sign-in and the watchdog's next tick lost it permanently, while a
research COMPLETION in the same window lost nothing — `compute()` re-derives those
from the research store every tick. That asymmetry is fix 1.

⛔ AND CLEARING IT WAS SPREAD OVER FOUR PLACES, ONLY ONE OF WHICH WORKED:
`_login_remote_start` cleared (correct); `_login_callback` — the `agent login
--local` page — did not; `set_session(None)` did but has no non-test callers; and the
REAL sign-out path, `_self_logout` → `clear_session_if`, nulled the session under the
lock without touching the announce. Hence `test_a_re_login_through_the_local_page…`.

⛔ THE SCOPE PREDICATE IS DELIBERATELY NOT TOUCHED. An origin-less sign-in still
reaches only an unscoped watchdog, and `test_updates_originless_signin_not_claimed_
by_scoped_watchdog` in test_bridge_device.py still guards that. Measured before
building: a terminal `agent login` prints "Connected as …" itself, stashes no pending
topic, and `/login/remote/pending` sets `flow.origin` when a chat later attaches one
— so the undelivered origin-less announce carries no news, and delivering it to a
scoped watchdog would reintroduce the wrong-chat bug that test was written for.
"""

import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge, prefs


class FakeFS:
    """Only what these tests drive: the device list and a no-op enqueue."""

    devices: list[dict] = []
    enqueue_raises = False
    upserted: list = []

    def __init__(self, token):
        self.token = token

    def list_devices(self, uid):
        return list(FakeFS.devices)

    def list_researches(self, uid, page_size=20):
        return []

    def get_user_settings(self, uid):
        return {}

    def upsert_research(self, uid, rid, fields):
        FakeFS.upserted.append((uid, rid))

    def enqueue_start(self, device_id, **k):
        if FakeFS.enqueue_raises:
            raise RuntimeError("boom")
        return "qid-1"

    def delete_research(self, uid, rid):
        return None


def _sess(uid="u1", email="e@x.y"):
    return SimpleNamespace(uid=uid, email=email, id_token=lambda force=False: "tok")


def _live(monkeypatch, uid="u1"):
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    FakeFS.devices = []
    state = bridge.BridgeState()
    state.set_session(_sess(uid))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", state, httpd


# ── 1. the store is uid-bound, exactly like the device selection ──────────────

def test_a_parked_announce_is_invisible_to_another_account():
    """⛔ THE WHOLE REASON THE UID IS STORED. Without the binding, signing in as B
    hands B's watchdog A's email and A's research topic."""
    prefs.set_pending_announce({"ts": 1, "email": "a@x.y", "uid": "uA"}, "uA")
    assert prefs.get_pending_announce("uA")["email"] == "a@x.y"
    assert prefs.get_pending_announce("uB") is None


def test_clearing_the_announce_removes_both_keys():
    """A pop that short-circuits would orphan the uid key, leaving a file that says
    an announce belongs to an account while carrying no announce."""
    prefs.set_pending_announce({"ts": 1, "uid": "uA"}, "uA")
    prefs.clear_pending_announce()
    raw = prefs.load()
    assert "pendingAnnounce" not in raw and "pendingAnnounceUid" not in raw


def test_an_announce_parked_under_no_account_is_readable_by_nobody():
    """⛔ A MUTATION SURVIVED HERE, and closing it needed the file written directly.

    `set_signed_in` refuses to park an event with no uid, so nothing this code
    writes can ever leave an empty `pendingAnnounceUid` — which made a mutant that
    ALSO accepted `owner == ""` unobservable through the normal path. It is still a
    hole: a truncated write, a hand-edited file, or a future writer could leave
    one, and an announce readable by whoever asks with an empty uid is the same
    cross-account leak the binding exists to prevent. So the file is written
    directly and the read is asserted from both sides."""
    raw = prefs.load()
    raw["pendingAnnounce"] = {"ts": 1, "email": "a@x.y"}
    raw["pendingAnnounceUid"] = ""
    prefs.save(raw)
    assert prefs.get_pending_announce("") is None
    assert prefs.get_pending_announce("uA") is None


def test_a_fresh_announce_supersedes_an_undelivered_one():
    prefs.set_pending_announce({"ts": 1, "uid": "uA", "topic": "old"}, "uA")
    prefs.set_pending_announce({"ts": 2, "uid": "uA", "topic": "new"}, "uA")
    assert prefs.get_pending_announce("uA")["topic"] == "new"


# ── 2. durability: it survives the process that minted it ─────────────────────

def test_the_announce_survives_a_bridge_restart():
    """⭐ THE HEADLINE FIX. A brand-new BridgeState — the same thing a restarted
    bridge builds — must still find the announce. Before this it was gone."""
    minted = bridge.BridgeState()
    minted.set_signed_in({"ts": 77, "email": "e@x.y", "uid": "u1", "topic": "EVs"})
    restarted = bridge.BridgeState()
    assert restarted.peek_signed_in("u1")["ts"] == 77


def test_a_restarted_bridge_does_not_serve_another_accounts_announce():
    minted = bridge.BridgeState()
    minted.set_signed_in({"ts": 77, "email": "a@x.y", "uid": "uA"})
    assert bridge.BridgeState().peek_signed_in("uB") is None


def test_peek_does_not_consume():
    """At-least-once delivery: peek twice, get it twice. Exactly-once was the bug —
    any failure after the read destroyed the announce."""
    state = bridge.BridgeState()
    state.set_signed_in({"ts": 5, "uid": "u1", "email": "e@x.y"})
    assert state.peek_signed_in("u1")["ts"] == 5
    assert state.peek_signed_in("u1")["ts"] == 5


def test_peek_does_not_consume_even_with_nothing_parked(monkeypatch):
    """⛔⛔ A MUTATION SURVIVED BECAUSE THE DISK COPY MASKED THE MEMORY ONE.
    `test_peek_does_not_consume` passes against a `peek` that clears as it reads,
    because the second call simply rehydrates from `prefs.json`. So at-least-once
    was proven only for the case where the park SUCCEEDED — and the case that
    matters most is the other one: a disk that refused the write leaves memory as
    the only copy, and a consuming read would destroy the announce outright."""
    monkeypatch.setattr(prefs, "set_pending_announce", lambda ev, uid: None)
    monkeypatch.setattr(prefs, "get_pending_announce", lambda uid: None)
    state = bridge.BridgeState()
    state.set_signed_in({"ts": 5, "uid": "u1", "email": "e@x.y"})
    assert state.peek_signed_in("u1")["ts"] == 5
    assert state.peek_signed_in("u1")["ts"] == 5, (
        "the in-memory copy was consumed by reading it")


def test_clearing_reaches_the_disk_not_just_the_attribute():
    """A clear that only nulled the attribute would leave the parked copy to be
    rehydrated by the next peek — the announce would come back from the dead."""
    state = bridge.BridgeState()
    state.set_signed_in({"ts": 5, "uid": "u1"})
    state.clear_signed_in()
    assert state.peek_signed_in("u1") is None
    assert bridge.BridgeState().peek_signed_in("u1") is None


def test_set_signed_in_with_no_uid_parks_nothing():
    """An event with no uid cannot be bound to an account, so it must not be parked
    under someone else's name — memory only, and the file is left clean."""
    state = bridge.BridgeState()
    state.set_signed_in({"ts": 5, "email": "e@x.y"})
    assert "pendingAnnounce" not in prefs.load()


def test_an_unwritable_prefs_file_does_not_break_the_sign_in(monkeypatch):
    """⛔ An announce is a courtesy. A disk that refuses the park must not take the
    sign-in down with it."""
    monkeypatch.setattr(prefs, "set_pending_announce",
                        lambda ev, uid: (_ for _ in ()).throw(OSError("read-only")))
    state = bridge.BridgeState()
    state.set_signed_in({"ts": 5, "uid": "u1", "email": "e@x.y"})
    assert state.signed_in["ts"] == 5  # memory still has it


# ── 3. one clearing point: every sign-out and re-login path ───────────────────

def test_the_real_sign_out_path_clears_the_announce():
    """⛔⛔ `_self_logout` goes through `clear_session_if`, NOT `set_session(None)`
    — which has no non-test callers. This is the path a /logout and an app Revoke
    actually take, and it used to leave the announce alive."""
    state = bridge.BridgeState()
    sess = _sess()
    state.set_session(sess)
    state.set_signed_in({"ts": 9, "uid": "u1", "email": "e@x.y"})
    assert state.clear_session_if(sess) is True
    assert state.peek_signed_in("u1") is None


def test_a_compare_and_swap_miss_leaves_the_announce_alone():
    """The CAS exists so a heartbeat deciding to log out the OLD session cannot tear
    down a NEW one a reconnect swapped in. It must not clear that new session's
    announce either."""
    state = bridge.BridgeState()
    old, new = _sess(), _sess()
    state.set_session(new)
    state.set_signed_in({"ts": 9, "uid": "u1", "email": "e@x.y"})
    assert state.clear_session_if(old) is False
    assert state.peek_signed_in("u1")["ts"] == 9


def test_a_re_login_through_the_local_page_drops_the_previous_announce(monkeypatch):
    """⛔⛔ THE REACHABLE STALE ANNOUNCE. Sign in from chat → announce parked →
    revoke or log out → `agent login --local` → the chat was told "Starting <the old
    topic> on <the old device> now" for a run that no longer existed."""
    base, state, httpd = _live(monkeypatch)
    try:
        state.set_signed_in({"ts": 1, "uid": "u1", "email": "e@x.y",
                            "autoStarted": True, "topic": "stale topic",
                            "deviceName": "Old PC", "origin": None})
        token = state.login_token
        r = requests.post(base + "/login/callback", json={
            "loginToken": token, "refreshToken": "rt", "idToken": "it",
            "uid": "u1", "email": "e@x.y", "expiresIn": 3600,
        })
        assert r.status_code == 200, r.text
        assert state.peek_signed_in("u1") is None
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── 4. the shared device decision ────────────────────────────────────────────

def _dev(did, *, online=None, name=None):
    """⛔⛔ CALL THIS INSIDE A TEST BODY, NEVER IN A `parametrize` LIST. An "online"
    device is one whose `lastHeartbeat` is within `bridge._DEVICE_ONLINE_MS` (30s)
    of NOW, and pytest evaluates parametrize arguments at COLLECTION time. The
    first version of this file built them there: every case passed when the file
    ran alone in six seconds, and the two online-rung cases FAILED inside the
    195-second full suite, because by the time they executed the heartbeat they
    were built with was three minutes old and read as offline. A fixture whose
    truth expires is worse than no fixture."""
    d = {"id": did}
    if name:
        d["name"] = name
    if online is not None:
        import time as _t
        d["lastHeartbeat"] = int(_t.time() * 1000) if online else 0
    return d


# (devs_spec, selected, want_id, want_reason, want_stale) — devs_spec is a list of
# (id, online, name) built INSIDE the test, for the reason in `_dev`'s docstring.
@pytest.mark.parametrize("spec,selected,want_id,want_reason,want_stale", [
    # the selection wins when it is still a member
    ([("a", None), ("b", None)], "a", "a", "", False),
    # no devices at all → pair one
    ([], None, None, "no_devices", False),
    # the sole device, selected or not
    ([("only", None)], None, "only", "", False),
    # ⭐ THE RUNG THE SIGN-IN PATH WAS MISSING: several devices, exactly one awake
    ([("a", False), ("b", True)], None, "b", "", False),
    # two awake → genuinely ambiguous
    ([("a", True), ("b", True)], None, None, "no_selection", False),
    # ⭐ AND NONE awake is ambiguous too — you cannot route to a machine that is off
    ([("a", False), ("b", False)], None, None, "no_selection", False),
    # ⭐ THE OTHER MISSING RUNG: a stale selection is dropped and the pick continues
    ([("a", False), ("b", True)], "gone", "b", "", True),
    # stale, and still ambiguous after dropping it → its own reason, so the person
    # is told WHY they are being asked
    ([("a", True), ("b", True)], "gone", None, "stale_selection", True),
])
def test_the_device_decision_table(spec, selected, want_id, want_reason, want_stale):
    devs = [_dev(did, online=online) for did, online in spec]
    got_id, reason, stale = bridge._pick_device_from(devs, selected)
    assert (got_id, reason, stale) == (want_id, want_reason, want_stale)


def test_an_online_device_is_one_that_beat_within_the_window():
    """The sole-online rung rests entirely on this, so pin the window.

    ⛔⛔ AND THE FIRST VERSION OF THIS TEST COULD NOT. It built its stale heartbeat
    as `now - bridge._DEVICE_ONLINE_MS - 1000` — DERIVED FROM THE CONSTANT IT WAS
    MEANT TO PIN — so widening the window moved the test's own boundary with it and
    the assertion stayed true. A mutation that stretched the window to half an hour
    SURVIVED, which would auto-pick a machine that went to sleep twenty minutes ago
    and enqueue a run to nothing.

    ⭐ The fixture is an ABSOLUTE age now. Five minutes is far outside any window
    this constant should ever hold — the backend heartbeats every ~5 s and the
    shipped threshold is six times that — so a mutant has to be absurd to pass,
    and an absurd one is exactly what needs catching.
    """
    import time as _t
    now = int(_t.time() * 1000)
    five_minutes_ago = now - 5 * 60 * 1_000
    devs = [{"id": "a", "lastHeartbeat": five_minutes_ago},
            {"id": "b", "lastHeartbeat": five_minutes_ago}]
    assert bridge._pick_device_from(devs, None) == (None, "no_selection", False)
    devs[1]["lastHeartbeat"] = now
    assert bridge._pick_device_from(devs, None) == ("b", "", False)
    # And the shipped window itself, stated as a number rather than derived:
    # 30 s is six times the ~5 s heartbeat, matching the web app's threshold.
    assert bridge._DEVICE_ONLINE_MS == 30_000


def test_a_sole_device_with_no_id_is_not_a_target():
    """It must fall THROUGH to the ask rather than enqueueing to an empty string —
    the run path has always done this and the shared helper must not lose it."""
    got_id, reason, _ = bridge._pick_device_from([{"name": "nameless"}], None)
    assert got_id is None and reason == "no_selection"


def test_autostart_hands_back_descriptors_when_it_cannot_choose(monkeypatch):
    """The ambiguous case must return the DEVICES, not just a None — naming them is
    the whole point of the fourth outcome."""
    monkeypatch.setattr(prefs, "get_selected_device", lambda uid: None)
    FakeFS.devices = [_dev("a", online=True, name="Desk"), _dev("b", online=True, name="Loft")]
    did, label, choices = bridge._autostart_pick_device(FakeFS("t"), _sess())
    assert did is None and label is None
    assert sorted(c["name"] for c in choices) == ["Desk", "Loft"]
    assert all(set(c) == {"id", "name", "online"} for c in choices), "no internals leak"


def test_autostart_clears_a_stale_selection(monkeypatch):
    """⛔ Or every later sign-in re-derives the same dead pick. The run path already
    cleared it; the sign-in path did not even look."""
    cleared = {"n": 0}
    monkeypatch.setattr(prefs, "get_selected_device", lambda uid: "gone")
    monkeypatch.setattr(prefs, "clear_selected_device",
                        lambda: cleared.__setitem__("n", cleared["n"] + 1))
    FakeFS.devices = [_dev("a", online=True), _dev("b", online=True)]
    bridge._autostart_pick_device(FakeFS("t"), _sess())
    assert cleared["n"] == 1


def test_autostart_raises_no_research_node_for_an_empty_account(monkeypatch):
    monkeypatch.setattr(prefs, "get_selected_device", lambda uid: None)
    FakeFS.devices = []
    with pytest.raises(bridge._NoResearchNode):
        bridge._autostart_pick_device(FakeFS("t"), _sess())


# ── 5. the fourth outcome, end to end ────────────────────────────────────────

def test_run_autostart_distinguishes_an_ambiguous_pick_from_an_error(monkeypatch):
    """⛔⛔ THE GUARD THAT COULD NOT FIRE. Both cases returned `{}`, so "you have
    three computers, pick one" and "Firestore threw" were the same value. The
    comment said "let the chat choose" while the hint named nothing to choose
    between."""
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    monkeypatch.setattr(prefs, "get_selected_device", lambda uid: None)
    FakeFS.devices = [_dev("a", online=True, name="Desk"), _dev("b", online=True, name="Loft")]

    ambiguous = bridge._run_autostart(_sess(), "EV market", None)
    assert ambiguous["needsDeviceChoice"] is True
    assert ambiguous["topic"] == "EV market"
    assert [d["name"] for d in ambiguous["devices"]] == ["Desk", "Loft"]

    monkeypatch.setattr(bridge, "_autostart_pick_device",
                        lambda fs, sess: (_ for _ in ()).throw(RuntimeError("firestore")))
    assert bridge._run_autostart(_sess(), "EV market", None) == {}


def test_the_choice_outcome_does_not_also_offer_reply_yes(monkeypatch):
    """Two different questions in one breath. "Which computer?" and "reply yes to
    start" cannot both be the next thing the person does."""
    monkeypatch.setattr(bridge, "_run_autostart",
                        lambda sess, topic, origin: {"needsDeviceChoice": True,
                                                     "topic": topic, "devices": []})
    state = bridge.BridgeState()
    state.set_session(_sess())
    bridge._autostart_worker(state, _sess(), "EVs", None,
                             {"ts": 1, "uid": "u1", "email": "e@x.y"})
    assert state.signed_in["pendingTopic"] == ""
    assert state.signed_in["needsDeviceChoice"] is True


def test_updates_carries_the_choice_and_the_devices(monkeypatch):
    base, state, httpd = _live(monkeypatch)
    try:
        state.set_signed_in({"ts": 3, "uid": "u1", "email": "e@x.y", "origin": None,
                             "needsDeviceChoice": True, "topic": "EVs",
                             "devices": [{"id": "a", "name": "Desk", "online": True}]})
        got = requests.get(base + "/updates?via=agent").json()["signedIn"]
        assert got["needsDeviceChoice"] is True
        assert got["devices"] == [{"id": "a", "name": "Desk", "online": True}]
        # delivered → cleared, from disk too
        assert "signedIn" not in requests.get(base + "/updates?via=agent").json()
        assert bridge.BridgeState().peek_signed_in("u1") is None
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_plain_announce_reports_no_choice_and_no_devices(monkeypatch):
    """The two new keys must be present and FALSY on an ordinary sign-in — a client
    that has to test for their absence is a client that will get it wrong."""
    base, state, httpd = _live(monkeypatch)
    try:
        state.set_signed_in({"ts": 3, "uid": "u1", "email": "e@x.y", "origin": None})
        got = requests.get(base + "/updates?via=agent").json()["signedIn"]
        assert got["needsDeviceChoice"] is False and got["devices"] == []
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_mismatched_scope_leaves_the_announce_parked_on_disk(monkeypatch):
    """Peek replaced take, so there is no re-stash write any more. The event must
    still be there — in memory AND on disk — for the watchdog that owns it."""
    base, state, httpd = _live(monkeypatch)
    try:
        state.set_signed_in({"ts": 4, "uid": "u1", "email": "e@x.y",
                             "origin": {"platform": "telegram", "chat_id": "111"}})
        r = requests.get(base + "/updates?via=agent&platform=telegram&chat=999").json()
        assert "signedIn" not in r
        assert bridge.BridgeState().peek_signed_in("u1")["ts"] == 4
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── 6. the run path still behaves, because sharing a helper is not a test ─────

def test_the_run_route_still_routes_to_the_sole_online_device(monkeypatch):
    """⛔ EXTRACTING A HELPER DOES NOT TEST ITS CONSUMERS. This drives the actual
    /research route, which is the half that could silently change behaviour."""
    base, state, httpd = _live(monkeypatch)
    try:
        monkeypatch.setattr(prefs, "get_selected_device", lambda uid: None)
        FakeFS.devices = [_dev("a", online=False), _dev("b", online=True)]
        r = requests.post(base + "/research", json={"topic": "EVs"})
        assert r.status_code == 200, r.text
        assert r.json()["deviceId"] == "b"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_run_route_still_asks_which_with_the_devices_attached(monkeypatch):
    base, state, httpd = _live(monkeypatch)
    try:
        monkeypatch.setattr(prefs, "get_selected_device", lambda uid: None)
        FakeFS.devices = [_dev("a", online=True, name="Desk"),
                          _dev("b", online=True, name="Loft")]
        r = requests.post(base + "/research", json={"topic": "EVs"})
        assert r.status_code == 400
        assert r.json()["reason"] == "no_selection"
        assert [d["name"] for d in r.json()["devices"]] == ["Desk", "Loft"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_run_route_still_says_stale_when_the_selection_died(monkeypatch):
    base, state, httpd = _live(monkeypatch)
    try:
        monkeypatch.setattr(prefs, "get_selected_device", lambda uid: "gone")
        monkeypatch.setattr(prefs, "clear_selected_device", lambda: None)
        FakeFS.devices = [_dev("a", online=True, name="Desk"),
                          _dev("b", online=True, name="Loft")]
        r = requests.post(base + "/research", json={"topic": "EVs"})
        assert r.status_code == 409
        assert r.json()["reason"] == "stale_selection"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_run_route_still_sends_to_pairing_with_no_devices(monkeypatch):
    base, state, httpd = _live(monkeypatch)
    try:
        monkeypatch.setattr(prefs, "get_selected_device", lambda uid: None)
        FakeFS.devices = []
        r = requests.post(base + "/research", json={"topic": "EVs"})
        assert r.status_code == 400 and r.json()["reason"] == "no_devices"
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── 7. a second chat may not silently take the first one's research ──────────

def _arm_pending(state, *, topic, origin):
    flow = SimpleNamespace(state="pending", pending_topic=topic, origin=origin,
                           code="C", verifyUrl="u", poll_token="p")
    state.set_remote(flow)
    return flow


def test_a_different_chat_cannot_overwrite_a_held_topic(monkeypatch):
    """⛔⛔ Chat A fires a topic while signed out, chat B fires one before A's link
    is approved, and B's post replaced A's topic AND A's destination. A's watchdog —
    armed, and told "I'll pick this up" — then heard nothing, ever."""
    base, state, httpd = _live(monkeypatch)
    try:
        a = {"platform": "telegram", "chat_id": "111"}
        flow = _arm_pending(state, topic="A's research", origin=a)
        r = requests.post(base + "/login/remote/pending", json={
            "pending_topic": "B's research",
            "origin": {"platform": "whatsapp", "chat_id": "222"}})
        assert r.status_code == 409
        assert r.json()["reason"] == "topic_taken"
        assert flow.pending_topic == "A's research"
        assert flow.origin == a
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_same_chat_may_still_correct_itself(monkeypatch):
    """First-come is about a DIFFERENT chat. The same person re-asking in the same
    conversation is a correction, and refusing it would be the new bug."""
    base, state, httpd = _live(monkeypatch)
    try:
        a = {"platform": "telegram", "chat_id": "111"}
        flow = _arm_pending(state, topic="first try", origin=a)
        r = requests.post(base + "/login/remote/pending", json={
            "pending_topic": "what I actually meant",
            "origin": {"platform": "Telegram", "chat_id": "111"}})
        assert r.status_code == 200
        assert flow.pending_topic == "what I actually meant"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_chat_may_attach_to_a_flow_that_holds_no_topic(monkeypatch):
    """The terminal starts a flow with no topic at all. A chat attaching the first
    one is the ordinary case and must still work — this is how a terminal sign-in
    becomes origin-BEARING and reaches its scoped watchdog."""
    base, state, httpd = _live(monkeypatch)
    try:
        flow = _arm_pending(state, topic=None, origin=None)
        r = requests.post(base + "/login/remote/pending", json={
            "pending_topic": "EVs",
            "origin": {"platform": "telegram", "chat_id": "111"}})
        assert r.status_code == 200
        assert flow.pending_topic == "EVs"
        assert flow.origin == {"platform": "telegram", "chat_id": "111"}
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_flow_with_an_origin_but_no_topic_still_accepts_one(monkeypatch):
    """⛔ A MUTATION SURVIVED HERE. `test_a_chat_may_attach_to_a_flow_that_holds_no
    _topic` uses a flow with origin=None, so a mutant that dropped the
    "is a topic even held?" half of the guard was invisible to it — the
    `isinstance(flow.origin, dict)` clause refused on its own.

    This is the observable case: a sign-in STARTED from one chat (so the flow
    carries an origin) that never named a topic. A second chat naming one must be
    accepted, because nothing is being taken from anybody."""
    base, state, httpd = _live(monkeypatch)
    try:
        flow = _arm_pending(state, topic="",
                            origin={"platform": "telegram", "chat_id": "111"})
        r = requests.post(base + "/login/remote/pending", json={
            "pending_topic": "EVs",
            "origin": {"platform": "whatsapp", "chat_id": "222"}})
        assert r.status_code == 200, r.text
        assert flow.pending_topic == "EVs"
        assert flow.origin == {"platform": "whatsapp", "chat_id": "222"}
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("a,b,same", [
    ({"platform": "telegram", "chat_id": "1"}, {"platform": "TELEGRAM", "chat_id": "1"}, True),
    ({"platform": "telegram", "chat_id": "1"}, {"platform": "telegram", "chat_id": "2"}, False),
    ({"platform": "telegram", "chat_id": "1"}, {"platform": "whatsapp", "chat_id": "1"}, False),
    # a thread is still the same chat — /updates scoping ignores thread_id too
    ({"platform": "telegram", "chat_id": "1"},
     {"platform": "telegram", "chat_id": "1", "thread_id": "9"}, True),
    # an unusable origin is never "the same" as anything
    ({"platform": "telegram"}, {"platform": "telegram"}, False),
    (None, None, False),
])
def test_same_origin_compares_what_delivery_scopes_on(a, b, same):
    assert bridge._same_origin(a, b) is same
