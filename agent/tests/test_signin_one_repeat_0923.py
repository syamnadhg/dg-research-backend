"""A lost "you're signed in" note gets ONE repeat, and never a second (2026-09-23).

⛔⛔ THE LOSS THIS CLOSES. On the parked-delivery path the announce watermark was
claimed at the note's own `ts`. A chat reader that receives the bytes and then dies
(a graceful timeout) is indistinguishable, at every layer the server can see, from
one that acted on them — so the note was gone, `_remint_signin` found `cap <= seen`,
and it never re-sent. The person was signed in and never told.

⭐⭐ THE OWNER'S DECISION: allow ONE repeat. The parked claim sits at `ts - 1`, the next
account-wide tick's re-mint wins exactly once and moves the mark to `ts`, every tick
after answers "already". The repeat carries the SAME `ts` — the session's capture
epoch, the identity the watchdog records in `__signed_in_ts__` — so a watcher that
already showed it drops it.

⛔ NOT "stop claiming". `claim_signin_announce` answers "first" (set, stay SILENT) when
no watermark exists, so a brand-new sign-in — the commonest case — would never get
its repeat, and a test run on a machine that had signed in before would pass anyway.
Case (a) below is a FIRST-EVER sign-in for exactly that reason.

⛔ AND ONLY FOR AN ACCOUNT-WIDE DELIVERY. A re-mint carries no chat address and only an
account-wide reader takes it, so for a note addressed to one chat the repeat could
never reach that chat — only surface in another, from a watcher that never saw the
`ts` and so could not drop it. An addressed delivery keeps its claim at `ts`.
"""

import contextlib
import importlib.util
import io
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import requests

from facade import bridge, prefs

_SCRIPTS = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"
_spec = importlib.util.spec_from_file_location("poll_one_repeat_0923",
                                               _SCRIPTS / "sr_attention_poll.py")
poll = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(poll)

CAP = 7_000


class _FS:
    def __init__(self, _tok):
        pass

    def list_devices(self, uid):
        return []

    def list_researches(self, uid, page_size=20, **k):
        return []

    def get_user_settings(self, uid):
        return {}


def _sess(cap=CAP):
    s = SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "tok")
    if cap is not None:
        s.connected_at_ms = cap
    return s


@contextlib.contextmanager
def _bridge(monkeypatch, sess):
    monkeypatch.setattr(bridge, "FirestoreRest", _FS)
    state = bridge.BridgeState()
    state.set_session(sess)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    finally:
        httpd.shutdown()
        httpd.server_close()


def _tick(base, **scope):
    q = "/updates?via=agent" + "".join(f"&{k}={v}" for k, v in scope.items())
    return requests.get(base + q, timeout=5).json()


def _park(state, origin=None):
    state.set_signed_in({"ts": CAP, "uid": "u1", "email": "e@x.y", "origin": origin})


# ── (a) a FIRST-EVER sign-in, reader dies → exactly one repeat ─────────────────

def test_a_first_ever_sign_in_whose_reader_died_is_re_minted_exactly_once(monkeypatch):
    """⭐ THE CASE THE WHOLE CHANGE IS FOR, and deliberately the one with NO prior
    watermark: this computer has never announced a sign-in. The reader takes the
    parked note and dies — from the server's side, a perfectly delivered 200."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        assert prefs.get_announced_signin_ms("u1") is None, "precondition: first ever"
        _park(state)
        assert _tick(base)["signedIn"]["ts"] == CAP          # …and the reader dies
        repeat = _tick(base)
        assert repeat.get("signedIn", {}).get("ts") == CAP, repeat
        assert "signedIn" not in _tick(base), "exactly ONE repeat"
        assert "signedIn" not in _tick(base)


# ── (b) the same, over an OLDER watermark ──────────────────────────────────────

def test_an_older_watermark_still_yields_exactly_one_repeat(monkeypatch):
    with _bridge(monkeypatch, _sess()) as (base, state):
        prefs.set_announced_signin_ms(1_000, "u1")            # an earlier sign-in
        _park(state)
        assert _tick(base)["signedIn"]["ts"] == CAP
        assert _tick(base).get("signedIn", {}).get("ts") == CAP
        assert "signedIn" not in _tick(base)
        assert prefs.get_announced_signin_ms("u1") == CAP     # settled on the note


# ── (c) the repeat carries the same ts, and the watchdog drops it ──────────────

def test_the_repeat_carries_the_same_ts_and_the_watchdog_drops_it(monkeypatch, tmp_path):
    """⛔⛔ EVERY DELIVERED SIGN-IN NOW ARRIVES TWICE. That is only acceptable if the
    watchdog shipped in the same wheel shows it once. Driven through the REAL poller
    tick, fed the delivery and then the repeat."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state)
        first = _tick(base)["signedIn"]
        repeat = _tick(base)["signedIn"]
    assert first["ts"] == repeat["ts"] == CAP

    feed = iter([([], first, None, None), ([], repeat, None, None)])
    monkeypatch.setattr(poll, "_get_updates", lambda origin=None: next(feed))
    monkeypatch.setattr(poll, "_state_path", lambda origin: tmp_path / "state.json")

    def tick():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            poll.main(None)
        return buf.getvalue()

    shown = tick()
    assert "Signed in" in shown, shown
    assert tick().strip() == "", "the repeat must be dropped: its ts is already shown"


# ── (d) concurrency: still ONE re-mint ─────────────────────────────────────────

def test_twenty_four_concurrent_readers_still_yield_one_repeat():
    """The mark sits one behind the note after a parked delivery; 24 readers race
    the re-mint. The claim is one atomic read-compare-write, so exactly one wins."""
    prefs.set_announced_signin_ms(CAP - 1, "u1")
    sess = _sess()
    won: list = []
    lk = threading.Lock()
    bar = threading.Barrier(24)

    def reader():
        bar.wait()
        note, _prev = bridge._remint_signin(sess)
        if note is not None:
            with lk:
                won.append(note["ts"])

    ts = [threading.Thread(target=reader) for _ in range(24)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert won == [CAP], won


# ── (e) a session older than the capture epoch is never greeted ────────────────

def test_a_session_with_no_capture_epoch_is_never_greeted(monkeypatch):
    """A rehydrated session from before the capture epoch carries no
    `connected_at_ms`. It predates the record, and greeting somebody who signed in
    days ago is worse than silence — the one-repeat change must not open that door.
    ⛔ An OLDER watermark is present on purpose: with none, the claim would answer
    "first" and stay silent for the wrong reason, and this would prove nothing."""
    with _bridge(monkeypatch, _sess(cap=None)) as (base, _state):
        prefs.set_announced_signin_ms(1_000, "u1")
        for _ in range(3):
            assert "signedIn" not in _tick(base)


# ── (f) an ADDRESSED delivery keeps its claim at ts ────────────────────────────

def test_an_addressed_delivery_is_not_repeated_into_another_chat(monkeypatch):
    """⛔⛔ THE REPEAT CAN ONLY GO WHERE A RE-MINT GOES — an account-wide reader. For
    a note addressed to one chat it could never reach that chat, only surface in a
    different one from a watcher that never saw this ts. So the claim stays at ts."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        _park(state, origin={"platform": "telegram", "chat_id": "111"})
        hit = _tick(base, platform="telegram", chat="111")
        assert hit["signedIn"]["ts"] == CAP
        assert prefs.get_announced_signin_ms("u1") == CAP
        # the account-wide reader must NOT be handed a repeat of chat 111's sign-in
        assert "signedIn" not in _tick(base)


# ── (g) the failed-send rollback agrees with the new claim ─────────────────────

def test_a_failed_send_puts_the_mark_back_under_the_new_claim(monkeypatch):
    """The rollback is a compare-and-swap against what OUR claim installed. The claim
    now installs ts - 1; a rollback still comparing against ts would find a mismatch,
    refuse, and strand the mark one behind a note nobody received."""
    with _bridge(monkeypatch, _sess()) as (base, state):
        prefs.set_announced_signin_ms(1_000, "u1")
        _park(state)
        real = bridge.BaseHTTPRequestHandler.send_response

        def boom(self, *a, **k):
            raise BrokenPipeError("reader vanished")

        monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", boom)
        try:
            _tick(base)
        except Exception:
            pass
        monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", real)
        assert prefs.get_announced_signin_ms("u1") == 1_000, "the mark must be back"
        assert state.signed_in is not None, "and the note with it"
