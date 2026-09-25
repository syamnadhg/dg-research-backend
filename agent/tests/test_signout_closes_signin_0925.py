"""A sign-out closes every source of "signed in"; one record says who told them (2026-09-25).

⛔⛔ THE INCIDENT (2026-09-24, owner's Telegram). A TRUE "✓ Signed in" was printed by
the watcher, sat 59 s in Hermes's delivery queue and reached the chat 19 s AFTER the
person had logged out. The investigation then found every other way the bridge
itself could say "signed in" about a session that had ended:
  • logout left the remote sign-in flow reading "connected", so `login-done` after a
    logout answered "✓ Connected as None — you're all set";
  • logout did not advance the announce watermark, so a `/updates` that captured the
    session before the logout could still win the re-mint claim — and its take,
    put-back and restore never re-checked the session either;
  • logout wrote no log line at all, so bridge.log could not say when it happened;
  • the watcher and `login-done` each announced the same sign-in, in contradicting
    words, because nothing recorded that the person had already been told.

⭐ WHAT THIS FILE PINS (owner, 2026-09-25): (a) logout and revoke clear the flow, the
note and seal the watermark, move the epoch and log it; (b) `/updates` never hands
out a note after a logout — including one landing mid-request — and refuses a note
from another sign-in; (c) `POST /signin/ack` consumes this chat's note, seals the
watermark and returns who told them before; (g) every step of the announce leaves an
INFO line.
"""

import contextlib
import logging
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import requests

from facade import bridge, prefs

CAP = 7_000
TG = {"platform": "telegram", "chat_id": "111"}


class _FS:
    """Only what these routes drive."""

    rows: list = []

    def __init__(self, _tok):
        pass

    def list_devices(self, uid):
        return []

    def list_researches(self, uid, page_size=20, **k):
        return list(_FS.rows)

    def get_user_settings(self, uid):
        return {}

    def delete_agent_session(self, uid, sid):
        return None

    def get_log_bundle(self, uid, code):
        return None


def _sess(cap=CAP, uid="u1", email="erin@example.com"):
    s = SimpleNamespace(uid=uid, email=email, id_token=lambda force=False: "tok",
                        logout=lambda: None)
    if cap is not None:
        s.connected_at_ms = cap
    return s


@contextlib.contextmanager
def _bridge(monkeypatch, sess):
    monkeypatch.setattr(bridge, "FirestoreRest", _FS)
    _FS.rows = []
    state = bridge.BridgeState()
    state.set_session(sess)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    finally:
        httpd.shutdown()
        httpd.server_close()


def _park(state, origin=None, ts=CAP, **extra):
    state.set_signed_in({"ts": ts, "uid": "u1", "email": "erin@example.com",
                         "origin": origin, **extra})


def _updates(base, **scope):
    q = "/updates?via=agent" + "".join(f"&{k}={v}" for k, v in scope.items())
    return requests.get(base + q, timeout=10)


def _connected_flow():
    f = bridge.RemoteFlow(poll_token="PT", code="AB", verify_url="https://x", expires_at=9e12)
    f.state = "connected"
    return f


# ── (a) logout and revoke close every source ──────────────────────────────────

def test_logout_clears_the_flow_the_note_and_seals_the_watermark(monkeypatch):
    """⛔⛔ THE THREE SOURCES, ONE CALL. The connected flow is what answered
    "✓ Connected as None"; the note is what a watcher would take; the watermark is
    what a re-mint claims against."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        prefs.set_announced_signin_ms(1_000, "u1")
        state.set_remote(_connected_flow())
        _park(state, TG)
        epoch = state.signin_epoch
        assert requests.post(base + "/logout", timeout=10).json() == {"ok": True}
        assert state.session is None
        assert state.remote is None, "a finished flow must not outlive the session"
        assert state.peek_signed_in("u1") is None
        assert "pendingAnnounce" not in prefs.load()
        assert prefs.get_announced_signin_ms("u1") == CAP, "sealed at the ended sign-in"
        assert state.signin_epoch > epoch


def test_the_seal_never_moves_the_watermark_backwards():
    prefs.set_announced_signin_ms(CAP + 50, "u1")
    assert prefs.seal_signin_announce(CAP, "u1") == CAP + 50
    assert prefs.get_announced_signin_ms("u1") == CAP + 50
    # a mark owned by another account is not this account's mark
    prefs.set_announced_signin_ms(99_999, "uOther")
    assert prefs.seal_signin_announce(CAP, "u1") == CAP
    assert prefs.get_announced_signin_ms("u1") == CAP


def test_a_sign_in_in_progress_survives_a_logout():
    """⭐ A PENDING flow can only be a sign-in started AFTER the ending session was
    captured — somebody signing in right now. Killing it would strand the link they
    are about to approve."""
    state = bridge.BridgeState()
    sess = _sess()
    state.set_session(sess)
    pending = bridge.RemoteFlow(poll_token="PT", code="AB", verify_url="u", expires_at=9e12)
    state.set_remote(pending)
    assert bridge._self_logout(state, sess) is True
    assert state.remote is pending


def test_a_revoke_closes_the_same_sources_and_says_which_route(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="facade")
    state = bridge.BridgeState()
    sess = _sess()
    state.set_session(sess)
    state.set_remote(_connected_flow())
    _park(state, TG)
    assert bridge._self_logout(state, sess, route="revoke") is True
    assert state.remote is None
    assert state.peek_signed_in("u1") is None
    assert prefs.get_announced_signin_ms("u1") == CAP
    assert "signed out: route=revoke" in caplog.text


def test_a_logout_is_logged_with_its_route_and_a_masked_email(monkeypatch, caplog):
    """⛔ bridge.log had NO line for the 2026-09-24 logout — the whole reason the
    incident could only be reconstructed from Hermes's ledgers."""
    caplog.set_level(logging.INFO, logger="facade")
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG)
        requests.post(base + "/logout", timeout=10)
    assert "signed out: route=logout" in caplog.text
    assert "e***@example.com" in caplog.text
    assert "erin@example.com" not in caplog.text, "the full email never goes to the log"
    assert "sign-in note cleared: ts=7000 — signed out" in caplog.text


def test_login_done_after_a_logout_is_never_told_connected(monkeypatch):
    """⛔⛔ THE SECOND FALSE "SIGNED IN" ROUTE. With the flow gone, the poll answers
    with a reason a chat can act on — and never "connected"."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        state.set_remote(_connected_flow())
        requests.post(base + "/logout", timeout=10)
        r = requests.post(base + "/login/remote/poll", timeout=10)
    body = r.json()
    assert r.status_code == 400
    assert body["reason"] == "no_flow" and body["authed"] is False
    assert "connected" not in r.text.lower()
    assert "POST /login/remote/start" not in r.text, "no developer-speak for a chat to relay"


# ── (b) /updates never hands out a note after a logout ────────────────────────

def test_updates_after_a_logout_hands_out_nothing(monkeypatch):
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG)
        requests.post(base + "/logout", timeout=10)
        r = _updates(base, platform="telegram", chat="111", watchdog=1)
    assert r.status_code == 401
    assert "signedIn" not in r.json()


def test_a_logout_landing_mid_request_after_the_take_hands_out_nothing(monkeypatch):
    """⛔⛔ THE RACE THE INVESTIGATION FOUND. The request captured the session, took
    the note — and then the logout landed. The final look must withhold it, and the
    note must NOT be put back for a session that has ended."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        sess = state.session
        _park(state, TG)
        real_take = state.take_signed_in

        def take_then_logout(uid, **kw):
            ev = real_take(uid, **kw)
            bridge._self_logout(state, sess)
            return ev

        monkeypatch.setattr(state, "take_signed_in", take_then_logout)
        r = _updates(base, platform="telegram", chat="111", watchdog=1)
        assert r.status_code == 401, r.text
        assert "signedIn" not in r.json()
        assert state.peek_signed_in("u1") is None, "never restored after a logout"
        assert prefs.get_announced_signin_ms("u1") == CAP


def test_a_note_put_back_after_a_mid_request_logout_is_not_parked_again(monkeypatch):
    """⛔ The other chat's reader took the note to look at it, the logout landed,
    and the put-back must be refused — or the note of a session that has ended
    sits on disk waiting for its watcher."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        sess = state.session
        _park(state, TG)
        real_take = state.take_signed_in

        def take_then_logout(uid, **kw):
            ev = real_take(uid, **kw)
            bridge._self_logout(state, sess)
            return ev

        monkeypatch.setattr(state, "take_signed_in", take_then_logout)
        r = _updates(base, platform="telegram", chat="222", watchdog=1)   # not its chat
        assert r.status_code == 401
        assert state.peek_signed_in("u1") is None
        assert "pendingAnnounce" not in prefs.load()


def test_a_logout_landing_after_the_re_mint_claim_hands_out_nothing(monkeypatch):
    """⛔ The account-wide re-mint path: the claim won against an older watermark,
    then the logout landed before the send. Nothing may leave, and the watermark is
    left where the logout sealed it — a rollback here would re-open the re-mint for
    the session that ended."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        sess = state.session
        prefs.set_announced_signin_ms(1_000, "u1")
        real = prefs.claim_signin_announce

        def claim_then_logout(ms, uid):
            out = real(ms, uid)
            bridge._self_logout(state, sess)
            return out

        monkeypatch.setattr(prefs, "claim_signin_announce", claim_then_logout)
        r = _updates(base)
        assert r.status_code == 401, r.text
        assert "signedIn" not in r.json()
        assert prefs.get_announced_signin_ms("u1") == CAP


def test_a_logout_landing_during_the_firestore_read_stops_the_re_mint(monkeypatch):
    """The earliest window: the logout lands while `/updates` is still listing runs.
    Both locks hold — the re-mint refuses (session not current) and the final look
    answers 401."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        sess = state.session
        prefs.set_announced_signin_ms(1_000, "u1")

        class _FSLogsOut(_FS):
            def list_researches(self, uid, page_size=20, **k):
                bridge._self_logout(state, sess)
                return []

        monkeypatch.setattr(bridge, "FirestoreRest", _FSLogsOut)
        r = _updates(base)
        assert r.status_code == 401
        assert prefs.get_announced_signin_ms("u1") == CAP


def test_take_put_back_and_re_mint_each_refuse_an_ended_session():
    state = bridge.BridgeState()
    old = _sess()
    state.set_session(old)
    _park(state, TG)
    assert state.clear_session_if(old) is True
    ev = {"ts": CAP, "uid": "u1", "email": "erin@example.com", "origin": TG}
    assert state.set_signed_in(ev, why="put back", sess=old) is False
    assert state.peek_signed_in("u1") is None
    assert "pendingAnnounce" not in prefs.load()
    state.set_signed_in(ev)                       # a parked note the take must refuse
    assert state.take_signed_in("u1", sess=old) is None
    prefs.set_announced_signin_ms(1_000, "u1")
    assert bridge._remint_signin(old, state) == (None, None)
    assert prefs.get_announced_signin_ms("u1") == 1_000, "no claim for an ended session"


def test_a_note_from_another_sign_in_is_refused_and_not_put_back(monkeypatch):
    """⛔ ONE NOTE, ONE SIGN-IN. A note whose ts is not the live session's capture
    epoch belongs to a sign-in that ended — its email and its topic never go out."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, None, ts=CAP - 5, topic="OLD TOPIC")
        body = _updates(base).json()
        assert "signedIn" not in body
        assert "OLD TOPIC" not in str(body)
        assert state.peek_signed_in("u1") is None


def test_a_note_for_this_sign_in_is_still_delivered(monkeypatch):
    """The refusal must not over-reach: the ordinary note, ts == capture epoch."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG)
        hit = _updates(base, platform="telegram", chat="111", watchdog=1).json()
    assert hit["signedIn"]["ts"] == CAP


# ── the epoch ─────────────────────────────────────────────────────────────────

def test_status_and_updates_carry_an_epoch_that_moves_on_every_sign_in_change(monkeypatch):
    with _bridge(monkeypatch, _sess()) as (base, state):
        e1 = requests.get(base + "/status", timeout=10).json()["signinEpoch"]
        assert _updates(base).json()["signinEpoch"] == e1
        requests.post(base + "/logout", timeout=10)
        e2 = requests.get(base + "/status", timeout=10).json()["signinEpoch"]
        assert e2 > e1
        state.set_session(_sess(cap=CAP + 1))
        e3 = requests.get(base + "/status", timeout=10).json()["signinEpoch"]
        assert e3 > e2
    assert prefs.get_signin_epoch() == e3, "on disk, so a restart cannot reuse a number"


# ── (c) POST /signin/ack — the one "already told" record ──────────────────────

def _ack(base, **body):
    return requests.post(base + "/signin/ack", json=body, timeout=10)


def test_ack_takes_this_chats_note_and_seals_so_the_watcher_stays_silent(monkeypatch):
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG)
        r = _ack(base, platform="telegram", chat="111", reader="login-done").json()
        assert r["consumed"] is True and r["signedIn"]["ts"] == CAP
        assert r["email"] == "erin@example.com" and r["told"] is None
        assert prefs.get_announced_signin_ms("u1") == CAP
        assert "signedIn" not in _updates(base, platform="telegram", chat="111",
                                          watchdog=1).json()
        assert state.told["reader"] == "login-done"


def test_ack_leaves_another_chats_note_for_that_chat(monkeypatch):
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG)
        r = _ack(base, platform="telegram", chat="222").json()
        assert r["consumed"] is False
        hit = _updates(base, platform="telegram", chat="111", watchdog=1).json()
        assert hit["signedIn"]["ts"] == CAP


def test_ack_does_not_swallow_news_unless_the_caller_will_relay_it(monkeypatch):
    """⛔ "Started “X” on Y" must still be said by somebody. A plain "✓ Signed in"
    reply that took the note would have destroyed it."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG, autoStarted=True, topic="EVs", deviceName="Mac", runId="r1")
        r = _ack(base, platform="telegram", chat="111").json()
        assert r["consumed"] is False and r["newsPending"] is True
        assert state.peek_signed_in("u1")["autoStarted"] is True
        r2 = _ack(base, platform="telegram", chat="111", withNews=True).json()
        assert r2["consumed"] is True and r2["signedIn"]["autoStarted"] is True


def test_ack_reports_that_the_watcher_already_told_them(monkeypatch):
    """⭐ THE 2026-09-24 DOUBLE: the watcher spoke, then `login-done` spoke again in
    other words. The reply can now see who spoke first."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG)
        assert _updates(base, platform="telegram", chat="111", watchdog=1).json()["signedIn"]
        r = _ack(base, platform="telegram", chat="111", reader="login-done").json()
    assert r["consumed"] is False
    assert r["told"]["reader"] == "watchdog" and r["told"]["ts"] == CAP


def test_ack_follows_the_same_gate_as_updates_for_an_account_wide_note(monkeypatch):
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, None)
        assert _ack(base, platform="telegram", chat="111").json()["consumed"] is False
        assert _ack(base).json()["consumed"] is True


def test_ack_blocks_the_one_repeat_after_an_account_wide_delivery(monkeypatch):
    """An account-wide delivery claims at ts-1 so ONE repeat can follow a reader that
    died (owner, 2026-09-23). Once a chat reply has SAID it, that repeat is a double."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        prefs.set_announced_signin_ms(1_000, "u1")
        _park(state, None)
        assert _updates(base).json()["signedIn"]["ts"] == CAP
        _ack(base)
        assert "signedIn" not in _updates(base).json()


def test_ack_signed_out_is_401_and_says_nothing_is_signed_in(monkeypatch):
    with _bridge(monkeypatch, _sess()) as (base, state):
        requests.post(base + "/logout", timeout=10)
        r = _ack(base, platform="telegram", chat="111")
    assert r.status_code == 401 and r.json()["authed"] is False


def test_a_logout_landing_mid_ack_hands_out_nothing(monkeypatch):
    """⛔⛔ THE ACK'S OWN LAST LOOK. `login-done` and `status-account` print
    "✓ Signed in" on the ack's 200. Here the ack took the note and THEN the logout
    landed: the answer must be the signed-out 401 — a 200 would become "signed in"
    in the chat after the person logged out, the 2026-09-24 shape one route over —
    and no "told" may stay recorded for a sign-in nobody was told about. Found by
    mutation (2026-09-25): only the ack's ENTRY check was tested."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        sess = state.session
        _park(state, TG)
        real_take = state.take_signed_in

        def take_then_logout(uid, **kw):
            ev = real_take(uid, **kw)
            bridge._self_logout(state, sess)
            return ev

        monkeypatch.setattr(state, "take_signed_in", take_then_logout)
        r = _ack(base, platform="telegram", chat="111", reader="login-done")
        assert r.status_code == 401, r.text
        body = r.json()
        assert body["authed"] is False and "signedIn" not in body
        assert state.told is None, "nobody was told"
        assert state.peek_signed_in("u1") is None, "never restored after a logout"


def test_ack_refuses_a_note_from_another_sign_in(monkeypatch):
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG, ts=CAP - 5)
        r = _ack(base, platform="telegram", chat="111").json()
    assert r["consumed"] is False and "signedIn" not in r


# ── (g) every step of the announce leaves a line ──────────────────────────────

def test_the_announce_lifecycle_is_logged_at_info(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="facade")
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG)
        _updates(base, platform="telegram", chat="222", watchdog=1)     # not its chat
        _updates(base, platform="telegram", chat="111", watchdog=1)     # its chat
    text = caplog.text
    slug = bridge.push.origin_slug(TG)
    assert f"sign-in note parked: ts=7000 for {slug}" in text
    assert "sign-in note put back: ts=7000" in text
    assert f"sign-in note ts=7000 taken by watchdog for {slug}" in text
    assert f"sign-in note ts=7000 delivered to watchdog for {slug} — committed" in text
    assert "111" not in text.replace("7000", ""), "the raw chat id never goes to the log"


def test_a_failed_send_is_logged_as_rolled_back(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="facade")
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, TG)
        real = bridge.BaseHTTPRequestHandler.send_response

        def boom(self, *a, **k):
            raise BrokenPipeError("reader vanished")

        monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", boom)
        try:
            _updates(base, platform="telegram", chat="111", watchdog=1)
        except Exception:
            pass
        monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", real)
        assert state.peek_signed_in("u1")["ts"] == CAP, "restored for the live session"
    assert "sign-in note ts=7000 NOT delivered to watchdog (the send failed) — rolled back" in caplog.text
    assert "sign-in note restored: ts=7000" in caplog.text
