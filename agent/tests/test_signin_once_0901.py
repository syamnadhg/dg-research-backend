"""The sign-in announce: said ONCE, and never lost.

⛔⛔ WHAT THIS FILE IS FOR, and why it is not the item that was signed.

The owner signed *"an unaddressed note is TAKEN and announced once, deduped"*. Measured
first, that half turned out to have no beneficiary and one real cost:

  • The fleet's own client sends NO chat address ON PURPOSE, and says so in writing —
    *"this fleet's watcher asks with neither, so claiming an origin here would make the
    sign-in announceable to nobody"*. Its watcher is unscoped, so an unaddressed note is
    ALREADY taken and announced there.
  • On the backend client the address IS sent, so a note is unaddressed only when
    somebody signed in at the TERMINAL — where the terminal already told them. Letting a
    scoped chat watcher take that would announce a terminal sign-in in whichever chat
    polled first, which is the wrong-chat bug two existing tests were written to stop.

▶ So the addressing rule is deliberately UNTOUCHED here (and
`test_updates_originless_signin_not_claimed_by_scoped_watchdog` +
`test_a_SCOPED_watchdog_never_gets_a_re_mint` still stand). What was actually broken is
the OTHER half of the same sentence — said once, never lost — in five ways, all measured:

  1. The recovery disarmed itself at the one moment it was needed: the watermark moved
     BEFORE the response was written, so a reader that timed out gracefully lost the note
     AND the re-mint built for exactly that loss. The comment beside it claimed the
     opposite ("the half that actually closes the hole").
  2. The re-mint's exactly-once had NO mutual exclusion at all. Probed: 24 concurrent
     callers, 24 re-mints. The parked-note take, under one lock, gave 1 of 24.
  3. A HALF-FORMED address dead-lettered the note forever — neither addressed nor
     unaddressed, refused by every reader, and the re-mint could never run either.
  4. `login-done` told the person and left the note parked, so the watcher said it again
     — and the note is the only place holding what the bridge DID about their research.
  5. The watcher silently swallowed a note with no `ts` while `sr updates` rendered it.
"""

import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from facade import bridge, prefs


def _load(name: str, filename: str):
    path = (Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"
            / filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_once_0901", "sr.py")
poll = _load("sr_poll_once_0901", "sr_attention_poll.py")


class FakeFS:
    devices: list[dict] = []

    def __init__(self, _tok):
        pass

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]

    def list_researches(self, uid, page_size=20, **k):
        return []

    def get_user_settings(self, uid):
        return {}


def _sess(uid="u1", email="e@x.y", cap=7_000):
    return SimpleNamespace(uid=uid, email=email, connected_at_ms=cap,
                           id_token=lambda force=False: "tok")


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    FakeFS.devices = []
    state = bridge.BridgeState()
    state.set_session(_sess())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    monkeypatch.setenv("SUPER_AGENT_BRIDGE_PORT", str(port))
    try:
        yield f"http://127.0.0.1:{port}", state
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── 1. ONE SIGN-IN, ONE IDENTITY ─────────────────────────────────────────────

def _capture(monkeypatch, state, *, cap, origin=None):
    """Drive the REAL capture: broker says approved, the custom token is redeemed,
    `_advance_remote_flow` mints and parks the note itself."""
    flow = bridge.RemoteFlow("pt", "CODE", "https://x/y", 9e18)
    flow.origin = origin
    state.set_remote(flow)
    monkeypatch.setattr(bridge.devicelogin, "poll_once",
                        lambda tok, **k: {"status": bridge.devicelogin.APPROVED,
                                          "customToken": "ct"})
    monkeypatch.setattr(bridge.AccountSession, "from_custom_token",
                        staticmethod(lambda ct: _sess(cap=cap)))
    monkeypatch.setattr(bridge, "_write_agent_session_connected",
                        lambda sess, clear_revoked=False: None)
    with state.remote_lock:
        bridge._advance_remote_flow(state)
    return flow


def test_the_parked_note_carries_the_sessions_own_capture_epoch(monkeypatch):
    """⛔⛔ TWO NUMBERS FOR ONE SIGN-IN WAS THE ROOT OF FIX 1. The note minted its own
    `time.time()` a few ms after the session's `connected_at_ms`, so the parked note and
    the re-mint that stands in for a lost one carried DIFFERENT identities for the same
    event. The watchdog de-dups by EQUALITY on `ts`, so it could never recognise a
    re-mint as the announce it had already shown — the ONE mechanism that can tell a
    received announce from a lost one, because a graceful reader timeout is invisible to
    the server.

    ⭐ DRIVEN THROUGH THE REAL CAPTURE, not by parking a note this test built: a test
    that constructs the event it asserts on cannot see the mint at all."""
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    state = bridge.BridgeState()
    _capture(monkeypatch, state, cap=1_234_000)
    note = state.signed_in
    assert note is not None, "capture must park an announce"
    assert note["ts"] == 1_234_000, (
        f"the note's identity must BE the session's capture epoch, got {note['ts']}")


def test_a_re_mint_arrives_under_the_same_identity_the_note_carried(monkeypatch):
    """⭐⭐ THE POINT OF THE SINGLE IDENTITY, and it needs both paths in one test. A
    client that already showed the parked announce recorded its `ts`; a re-mint standing
    in for a LOST one must arrive under that same number, or the client's de-dup cannot
    recognise it and the person is greeted twice — which is exactly why the watermark was
    made to suppress the re-mint, which is what disarmed the recovery."""
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    state = bridge.BridgeState()
    _capture(monkeypatch, state, cap=4_242_000)
    parked_ts = state.signed_in["ts"]

    # The announce is lost (a reader that timed out gracefully): the note is gone and
    # nothing recorded it. The re-mint must speak under the SAME identity.
    state.set_signed_in(None)
    prefs.set_announced_signin_ms(1, "u1")
    note, _prev = bridge._remint_signin(_sess(cap=4_242_000))
    assert note is not None and note["ts"] == parked_ts, (
        "a re-mint must be recognisable as the announce it stands in for")


def test_a_session_with_no_capture_epoch_still_mints_a_usable_identity(monkeypatch):
    """⛔ THE FALLBACK IS LOAD-BEARING, not defensive noise. A session rehydrated from a
    pre-change blob carries NO `connected_at_ms`, and a note stamped `ts: 0` is a note
    the watermark reads as "announced at the epoch" — every later re-mint for that
    account suppressed, permanently."""
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    state = bridge.BridgeState()
    flow = bridge.RemoteFlow("pt", "CODE", "https://x/y", 9e18)
    state.set_remote(flow)
    monkeypatch.setattr(bridge.devicelogin, "poll_once",
                        lambda tok, **k: {"status": bridge.devicelogin.APPROVED,
                                          "customToken": "ct"})
    monkeypatch.setattr(
        bridge.AccountSession, "from_custom_token",
        staticmethod(lambda ct: SimpleNamespace(uid="u1", email="e@x.y",
                                                id_token=lambda force=False: "tok")))
    monkeypatch.setattr(bridge, "_write_agent_session_connected",
                        lambda sess, clear_revoked=False: None)
    with state.remote_lock:
        bridge._advance_remote_flow(state)
    assert state.signed_in["ts"] > 0, "a note with ts 0 poisons the watermark forever"


def test_a_send_that_raises_puts_the_note_AND_the_watermark_back(live, monkeypatch):
    """⛔⛔ THE NOTE WAS RESTORED AND THE MARK WAS NOT, so the restored note stayed
    claimable while the mark said the announce had gone out — and the re-mint then
    refused to recover it. Two records of one fact, disagreeing."""
    base, state = live
    state.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": None})
    assert prefs.get_announced_signin_ms("u1") is None

    # Make the response write blow up AFTER the announce has been claimed.
    real = bridge.BaseHTTPRequestHandler.send_response

    def boom(self, *a, **k):
        raise BrokenPipeError("reader vanished")

    monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", boom)
    try:
        requests.get(base + "/updates?via=agent", timeout=5)
    except Exception:
        pass
    monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", real)

    assert state.signed_in is not None, "the note must be back"
    assert prefs.get_announced_signin_ms("u1") is None, (
        "the watermark must be back too, or the re-mint refuses to recover this")


def test_a_RE_MINT_lost_to_a_dropped_connection_also_rolls_its_claim_back(
        live, monkeypatch):
    """⛔⛔ THE OTHER HALF OF THE SAME ROLLBACK, AND MY FIRST TEST ONLY COVERED THE
    PARKED PATH — mutation caught it (B4 survived). A re-mint has no note to restore, so
    the watermark is the ONLY thing standing between a dropped connection and permanent
    silence: leave it advanced and this sign-in can never be re-derived by anybody."""
    base, state = live
    prefs.set_announced_signin_ms(1_000, "u1")      # cap is 7_000 → a re-mint is due
    assert state.signed_in is None, "this path needs NOTHING parked"

    real = bridge.BaseHTTPRequestHandler.send_response

    def boom(self, *a, **k):
        raise BrokenPipeError("reader vanished")

    monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", boom)
    try:
        requests.get(base + "/updates?via=agent", timeout=5)
    except Exception:
        pass
    monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", real)

    assert prefs.get_announced_signin_ms("u1") == 1_000, (
        "a re-mint nobody received must leave the watermark where it found it")
    # …and the proof that it is recoverable: the very next read re-mints it.
    got = requests.get(base + "/updates?via=agent", timeout=5).json()
    assert got.get("signedIn", {}).get("ts") == 7_000


# ── 2. THE CLAIM IS ATOMIC (measured 24/24 before the fix) ───────────────────

def test_twenty_four_concurrent_re_mints_produce_exactly_one():
    """⛔⛔ MEASURED, NOT REASONED: before the fix this handed out 24 of 24 — the same
    sign-in announced 24 times, in 24 chats. `get_announced_signin_ms` read OUTSIDE the
    prefs lock while only the setter took it, so the compare sat between a lockless read
    and a locked write: exactly the clobber the lock's own comment says it prevents."""
    sess = _sess(cap=5_000)
    prefs.set_announced_signin_ms(1_000, "u1")

    n = 24
    got: list = []
    lk = threading.Lock()
    bar = threading.Barrier(n)

    def worker():
        bar.wait()
        note, _prev = bridge._remint_signin(sess)
        if note is not None:
            with lk:
                got.append(note["ts"])

    ts = [threading.Thread(target=worker) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(got) == 1, f"{len(got)} callers were each told to announce the same sign-in"


def test_the_parked_take_was_already_atomic_and_still_is():
    """The other half of the same measurement — 1 of 24 — so the fix is aimed at the
    half that was actually unguarded and this one is pinned against regressing."""
    state = bridge.BridgeState()
    state.set_signed_in({"ts": 9_000, "uid": "u1", "email": "e@x.y", "origin": None})
    n = 24
    got: list = []
    lk = threading.Lock()
    bar = threading.Barrier(n)

    def worker():
        bar.wait()
        ev = state.take_signed_in("u1")
        if ev is not None:
            with lk:
                got.append(ev["ts"])

    ts = [threading.Thread(target=worker) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(got) == 1


def test_claim_reports_first_won_and_already_apart():
    """The three outcomes are not interchangeable: "first" must stay SILENT (the
    sign-in predates the record, and greeting somebody who signed in days ago is worse
    than saying nothing), "won" speaks, "already" stays quiet."""
    assert prefs.claim_signin_announce(5_000, "u1") == ("first", None)
    assert prefs.claim_signin_announce(6_000, "u1") == ("won", 5_000)
    assert prefs.claim_signin_announce(6_000, "u1") == ("already", 6_000)
    assert prefs.claim_signin_announce(5_999, "u1") == ("already", 6_000)


def test_a_claim_with_no_account_never_reports_a_win():
    """⛔ MEASURED UNCOVERED by cross-verification: turning this gate into a win left the
    whole suite green. A caller with no session would be told it owns the announce, and
    the watermark it "moved" belongs to nobody — so the real account's next claim reads a
    mark it never made."""
    assert prefs.claim_signin_announce(5_000, "")[0] == "already"
    raw = prefs.load()
    assert "announcedSignInMs" not in raw, "an account-less claim must write nothing"


def test_the_rollback_holds_the_lock_while_it_reads_and_writes():
    """⛔ MEASURED UNCOVERED: replacing the rollback's `with _lock:` with `if True:` left
    the suite green. It is a read-compare-write like the claim, so it needs the same
    mutual exclusion — and this pins it the only way a single-threaded test can: by
    driving it concurrently and checking the outcome is consistent."""
    prefs.set_announced_signin_ms(1_000, "u1")
    prefs.claim_signin_announce(2_000, "u1")
    results: list = []
    lk = threading.Lock()
    bar = threading.Barrier(16)

    def worker():
        bar.wait()
        ok = prefs.restore_announced_signin_ms(1_000, "u1", expected=2_000)
        with lk:
            results.append(ok)

    ts = [threading.Thread(target=worker) for _ in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(1 for r in results if r) == 1, (
        f"exactly one rollback may fire for one claim, got {sum(1 for r in results if r)}")
    assert prefs.get_announced_signin_ms("u1") == 1_000


def test_the_announce_identity_falls_back_to_the_capture_epoch():
    """⛔ MEASURED UNCOVERED: dropping the fallback half of the claim's argument left the
    suite green, because no suite ever parked a note without a `ts`. Without it, such a
    note claims 0 — which the watermark reads as "announced at the epoch"."""
    assert bridge._announce_ms({"ts": 9_000}, _sess(cap=7_000)) == 9_000
    assert bridge._announce_ms({}, _sess(cap=7_000)) == 7_000
    assert bridge._announce_ms({"ts": 0}, _sess(cap=7_000)) == 7_000
    assert bridge._announce_ms({"ts": "nope"}, _sess(cap=7_000)) == 7_000
    assert bridge._announce_ms({"ts": True}, _sess(cap=7_000)) == 7_000, (
        "a bool is an int subclass — it must not become an identity of 1")


def test_a_claim_never_inherits_another_accounts_watermark():
    """⛔ Same rule the getter applies. Without it a re-login under a different account
    is suppressed by the previous owner's mark — the new person is never greeted."""
    prefs.set_announced_signin_ms(9_000, "uA")
    assert prefs.claim_signin_announce(1_000, "uB")[0] == "first"


def test_a_first_observation_says_nothing_and_still_records_where_we_are():
    """Otherwise every existing session is greeted once the moment this ships."""
    sess = _sess(cap=8_000)
    note, _prev = bridge._remint_signin(sess)
    assert note is None
    assert prefs.get_announced_signin_ms("u1") == 8_000


def test_a_rollback_never_undoes_a_NEWER_claim_that_was_delivered():
    """⛔⛔ THE BLIND WRITE, measured by cross-verification. Watermark 1000; request A
    claims 2000; request B claims 3000 and its response IS delivered; A's send then
    raises. A blind restore writes 1000 back — so B's delivered 3000 is unmarked and gets
    announced all over again. A rollback may only ever undo ITSELF."""
    prefs.set_announced_signin_ms(1_000, "u1")
    _oa, prev_a = prefs.claim_signin_announce(2_000, "u1")     # request A
    _ob, _prev_b = prefs.claim_signin_announce(3_000, "u1")    # request B, delivered
    restored = prefs.restore_announced_signin_ms(prev_a, "u1", expected=2_000)
    assert restored is False, "A must not be allowed to undo B's newer claim"
    assert prefs.get_announced_signin_ms("u1") == 3_000


def test_the_ROUTE_rollback_leaves_a_newer_delivered_claim_alone(live, monkeypatch):
    """⛔⛔ THE FOURTH TIME I PINNED THE HELPER AND NOT THE CALLER, and mutation caught it
    again: `test_a_rollback_never_undoes_a_NEWER_claim_that_was_delivered` calls
    `restore_announced_signin_ms` itself and passes `expected=` by hand, so the route was
    free to pass None and degrade the compare-and-swap back to a blind write.

    This drives the ROUTE. A newer sign-in is claimed and delivered inside the window
    between our claim and our failed send — the rollback must not touch it."""
    base, state = live
    state.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": None})

    real = bridge.BaseHTTPRequestHandler.send_response

    def boom(self, *a, **k):
        # Another request claims a NEWER sign-in and its response goes out fine.
        prefs.set_announced_signin_ms(9_000, "u1")
        raise BrokenPipeError("reader vanished")

    monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", boom)
    try:
        requests.get(base + "/updates?via=agent", timeout=5)
    except Exception:
        pass
    monkeypatch.setattr(bridge.BaseHTTPRequestHandler, "send_response", real)

    assert prefs.get_announced_signin_ms("u1") == 9_000, (
        "the rollback undid a newer claim that had already been delivered")


def test_a_rollback_never_deletes_another_accounts_watermark():
    """⛔ The claim reports NO previous value when the stored mark belongs to a different
    account, so the rollback's `None` branch used to delete that account's mark outright
    — no race required."""
    prefs.set_announced_signin_ms(9_000, "uA")
    outcome, prev = prefs.claim_signin_announce(1_000, "uB")
    assert (outcome, prev) == ("first", None)
    # uA's row was legitimately replaced by uB's claim; a rollback of uB's own claim is
    # allowed, but one carrying a stale expectation must not touch it.
    assert prefs.restore_announced_signin_ms(None, "uB", expected=5_555) is False
    assert prefs.get_announced_signin_ms("uB") == 1_000


def test_a_parked_ts_that_is_not_a_number_does_not_destroy_the_announce(live):
    """⛔ THE `int()` SAT OUTSIDE EVERY try, AND THE NOTE IS ALREADY TAKEN BY THEN. A
    hand-edited prefs.json or a note from a future writer raised there, so the announce
    was destroyed AND the reader got no response at all — the worst of both."""
    base, state = live
    state.set_signed_in({"ts": "not-a-number", "uid": "u1", "email": "e@x.y",
                         "origin": None})
    got = requests.get(base + "/updates?via=agent", timeout=5).json()
    assert got.get("signedIn", {}).get("email") == "e@x.y", got
    # and the identity falls back to the session's capture epoch, not to a crash
    assert prefs.get_announced_signin_ms("u1") == 7_000


def test_a_half_address_an_OLDER_bridge_parked_on_DISK_is_still_delivered(live):
    """⛔ THE SKEW FIX 4 MISSED. prefs.json SURVIVES the upgrade — that is the whole point
    of parking it — so a half-formed origin written by an older bridge is read back
    verbatim and stays exactly the dead letter cleaning-at-the-mint was meant to end."""
    base, state = live
    # Write the note the way an older bridge would have: straight to disk, uncleaned.
    prefs.set_pending_announce({"ts": 7_000, "uid": "u1", "email": "e@x.y",
                                "origin": {"platform": "telegram"}}, "u1")
    state.set_signed_in(None)          # memory empty; only the parked copy exists
    prefs.set_pending_announce({"ts": 7_000, "uid": "u1", "email": "e@x.y",
                                "origin": {"platform": "telegram"}}, "u1")
    got = requests.get(base + "/updates?via=agent", timeout=5).json()
    assert got.get("signedIn", {}).get("email") == "e@x.y", (
        f"a half-address already on disk must not stay a dead letter: {got}")


def test_the_rollback_removes_the_keys_when_there_was_no_mark():
    """⛔ NOT a zero. A watermark of 0 reads as "announced at the epoch", which would
    suppress every later re-mint for this account."""
    prefs.claim_signin_announce(4_000, "u1")
    prefs.restore_announced_signin_ms(None, "u1")
    raw = prefs.load()
    assert "announcedSignInMs" not in raw and "announcedSignInUid" not in raw


# ── 3. A HALF-FORMED ADDRESS IS NOT A DEAD LETTER ────────────────────────────

def test_a_half_formed_address_is_treated_as_anonymous_not_as_undeliverable(monkeypatch):
    """⛔⛔ THE DEAD LETTER. `{"platform": "telegram"}` with no chat_id is neither
    ADDRESSED (no chat to match) nor UNADDRESSED (the origin is truthy), so every reader
    took it, failed the gate, and parked it again — forever. And because the note stayed
    parked, the re-mint that recovers a lost announce never ran either.

    `_same_origin` already treats an unusable half-origin as anonymous; cleaning at the
    mint makes the note agree with it.

    ⛔⛔ AND THIS TEST'S FIRST VERSION CALLED `_clean_origin` ITSELF and parked the
    result — so it pinned the HELPER and left the MINT free to store the address raw.
    Mutation caught it: both F-mutants survived. Third time this shape has cost me a
    round; the subject has to be the CALLER."""
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    state = bridge.BridgeState()
    _capture(monkeypatch, state, cap=7_000, origin={"platform": "telegram"})
    note = state.signed_in
    assert note is not None, "capture must park an announce"
    assert note["origin"] is None, (
        f"an unusable half-address must be stored as anonymous, got {note['origin']!r}")


def test_the_mint_keeps_a_whole_address(monkeypatch):
    """The cleaning must not flatten a USABLE address into anonymous — that would hand
    every chat-initiated sign-in to whichever watcher polled first, which is the
    wrong-chat bug arriving through the fix for the dead letter."""
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    state = bridge.BridgeState()
    _capture(monkeypatch, state, cap=7_000,
             origin={"platform": "telegram", "chat_id": "111"})
    note = state.signed_in
    assert note["origin"] == {"platform": "telegram", "chat_id": "111"}, (
        f"a usable address must survive the mint, got {note['origin']!r}")


def test_a_whole_address_is_still_routed_to_its_own_chat_only(live):
    """The routing half, at the gate rather than the mint — so a change to either end is
    visible."""
    base, state = live
    state.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y",
                         "origin": {"platform": "telegram", "chat_id": "111"}})
    assert "signedIn" not in requests.get(base + "/updates?via=agent", timeout=5).json()
    hit = requests.get(base + "/updates?via=agent&platform=telegram&chat=111",
                       timeout=5).json()
    assert hit["signedIn"]["email"] == "e@x.y"


# ── 4. `login-done` PAYS THE DEBT IT ALREADY CLAIMED TO PAY ──────────────────

def _connect_flow(state, *, origin=None):
    flow = bridge.RemoteFlow("pt", "CODE", "https://x/y", 9e18)
    flow.state = "connected"
    flow.origin = origin
    state.set_remote(flow)


def test_login_done_relays_the_device_question_the_note_was_holding(live, capsys):
    """⛔⛔ THE OWNER'S OWN FLEET TRANSCRIPT. 78 seconds of silence, the person asks
    "started the super research?", and `login-done` answered "they are signed in" and
    nothing else — while the note it left parked was holding *"you have 3 research
    computers — which should run this?"*. That question then had to be worked out by
    hand from a separate command."""
    base, state = live
    _connect_flow(state)
    state.set_signed_in({
        "ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": None,
        "needsDeviceChoice": True, "topic": "quantum error correction",
        "devices": [{"id": "d1", "name": "Research Computer"},
                    {"id": "d2", "name": "Macbook"}],
    })
    # ⛔ A DEVICE IS SEEDED ON PURPOSE. With none, `_connected_msg`'s fallback says
    # "paste the access code from your Research Computer" — so a bare
    # `"Research Computer" in out` passes even when the relay is GONE. Cross-verification
    # measured that: under the mutant that stops login-done taking the note, the loose
    # assertion still held. Seed a device so the fallback cannot contain the name, and
    # assert on the QUESTION rather than on a device name alone.
    FakeFS.devices = [{"id": "d1", "name": "Research Computer", "ownerUid": "u1"}]
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert "Macbook" in out, out
    assert "which should run" in out.lower() or "use " in out.lower(), out
    assert "access code" not in out, f"this is the relay, not the fallback: {out!r}"
    assert state.signed_in is None, "the note must be TAKEN, or the watcher repeats it"


def test_login_done_takes_a_plain_note_but_keeps_the_device_aware_greeting(live, capsys):
    """⛔ A QUIET REGRESSION I ALMOST SHIPPED. Preferring the note unconditionally loses
    the pair-a-computer steer: for a PLAIN sign-in `_connected_msg` is device-aware and
    the note's single line is not. Take it either way — that is the half that stops the
    double announce — but keep the better sentence."""
    base, state = live
    FakeFS.devices = []
    _connect_flow(state)
    state.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": None})
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert "access code" in out, out
    assert state.signed_in is None, "the note must still be taken"


def test_login_done_still_names_the_topic_when_the_auto_start_FAILED(live, capsys):
    """⛔⛔⛔ THE BLOCKER CROSS-VERIFICATION FOUND IN MY OWN FIX — and my first test for
    this case pinned a state the live path cannot produce, which is why the test passed
    while the code was broken.

    The real path: a person asks for research while signed out, approves, and the
    auto-start worker's Firestore I/O FAILS. The worker then parks the note's FOURTH
    shape — a topic and none of the three outcome flags — and by then `flow.pending_topic`
    has ALREADY been nulled (it is claimed under the lock before the worker is spawned),
    so the poll reply carries NO topic.

    My first gate relayed the note only for the three flags, so: note TAKEN, gate says
    nothing, poll reply has no topic → a plain "you're all set" and the person's research
    request GONE. Before any of this work the note simply stayed parked and the watchdog
    said it. **A fix that loses news the bug did not.**

    ⭐ My first test set BOTH `flow.pending_topic` and a topic-only note — mutually
    exclusive on the real path — so it proved nothing. This one drives the capture."""
    base, state = live
    monkeypatch_free_topic = "quantum error correction"

    # The real capture, with a pending topic and an auto-start that fails.
    flow = bridge.RemoteFlow("pt", "CODE", "https://x/y", 9e18)
    flow.pending_topic = monkeypatch_free_topic
    flow.state = "connected"
    state.set_remote(flow)
    # What `_autostart_worker` parks when `_run_autostart` returns {} (its documented
    # failure fallback): the topic rides along, no outcome flag is set.
    base_ev = {"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": None}
    base_ev["pendingTopic"] = monkeypatch_free_topic
    state.set_signed_in(base_ev)
    flow.pending_topic = None          # claimed under the lock before the worker ran
    assert not (flow.pending_topic or "")

    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert monkeypatch_free_topic in out, (
        f"the topic must survive — it exists nowhere else once the note is taken: {out!r}")
    assert "Continuing your research" in out, out
    assert "go ahead" not in out, f"a cue to act must not become a question: {out!r}"
    assert state.signed_in is None, "the note must still be taken"


def test_login_done_json_carries_the_note_it_consumed(live, capsys):
    """⛔ THE `--json` PAYLOAD WAS THE POLL BODY, so a caller reading JSON got
    `state: connected` and none of the news the command had just destroyed."""
    base, state = live
    flow = bridge.RemoteFlow("pt", "CODE", "https://x/y", 9e18)
    flow.state = "connected"
    state.set_remote(flow)
    state.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": None,
                         "autoStarted": True, "deviceName": "Research Computer",
                         "topic": "quantum error correction"})
    assert sr.main(["--json", "login-done"]) == 0   # --json is a GLOBAL flag
    import json as _json
    payload = _json.loads(capsys.readouterr().out)
    assert payload.get("signedIn", {}).get("autoStarted") is True, payload


def test_login_done_asks_with_this_chats_address_so_an_addressed_note_is_claimable(
        live, capsys, monkeypatch):
    """⛔ WITHOUT THE SCOPE THE FIX DOES NOTHING IN THE ORDINARY CASE. `login` posts this
    chat's address, so the note is ADDRESSED — and an unscoped read is correctly refused
    it. `login-done` would take nothing and the double announce would survive."""
    base, state = live
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "111")
    _connect_flow(state, origin={"platform": "telegram", "chat_id": "111"})
    state.set_signed_in({
        "ts": 7_000, "uid": "u1", "email": "e@x.y",
        "origin": {"platform": "telegram", "chat_id": "111"},
        "autoStarted": True, "deviceName": "Research Computer",
        "topic": "quantum error correction",
    })
    # Same reason as the device-question test: seed a device so the deviceless fallback
    # cannot supply the string this assertion looks for.
    FakeFS.devices = [{"id": "d1", "name": "Research Computer", "ownerUid": "u1"}]
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert "Started" in out and "Research Computer" in out, out
    assert "access code" not in out, f"this is the relay, not the fallback: {out!r}"
    assert state.signed_in is None


def test_login_done_leaves_another_chats_note_alone(live, capsys, monkeypatch):
    """The scope is a scope, not a licence: a note addressed to another chat must be put
    straight back, or `login-done` becomes the wrong-chat leak with extra steps."""
    base, state = live
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "999")
    _connect_flow(state, origin={"platform": "telegram", "chat_id": "111"})
    state.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y",
                         "origin": {"platform": "telegram", "chat_id": "111"},
                         "autoStarted": True, "deviceName": "Research Computer"})
    assert sr.main(["login-done"]) == 0
    assert state.signed_in is not None, "another chat's note must be put back"


# ── 5. THE TWO READERS AGREE ABOUT A MISSING TIMESTAMP ──────────────────────

def _tick(monkeypatch, tmp_path, note, *, prior=None):
    """One REAL watcher tick against a fixed payload, with its state file in tmp."""
    state_file = tmp_path / "state.json"
    if prior is not None:
        poll._save_state(prior, state_file)
    monkeypatch.setattr(poll, "_state_path", lambda origin: state_file)
    monkeypatch.setattr(poll, "_get_updates", lambda origin=None: ([], note))
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        poll.main()
    return buf.getvalue(), (poll._load_state(state_file) or {})


def test_the_watcher_no_longer_swallows_a_note_with_no_timestamp(monkeypatch, tmp_path):
    """⛔⛔ THE SILENT EATER, IN THE ONE READER THAT IS SUPPOSED TO BE RELIABLE. The
    bridge has already TAKEN and cleared the note by the time the watcher sees it, so
    dropping it destroys the news outright — and `sr updates`, reading the same payload,
    rendered it. Two readers of one field disagreeing about whether a timestamp is
    required to speak."""
    out, _state = _tick(monkeypatch, tmp_path, {"email": "e@x.y"})
    assert "e@x.y" in out, f"a note with no ts must still be announced, got {out!r}"


def test_a_ts_less_note_leaves_a_record_so_the_watchdog_is_not_torn_down(
        monkeypatch, tmp_path):
    """⛔⛔ THE WORSE HALF OF THE WIDENING, found by cross-verification.
    `__signed_in_ts__` is also the watcher's ONLY record that a sign-in was ever SEEN —
    `_tick_unauthed` reads it as `signed_in_before`. Announcing a ts-less note while
    recording nothing meant a person who was told "✓ Signed in" left no trace, so a later
    401 counted toward `_LOGIN_WAIT_LIMIT` and TORE THE WATCHDOG DOWN."""
    out, state = _tick(monkeypatch, tmp_path, {"email": "e@x.y"})
    assert "e@x.y" in out
    assert state.get("__signed_in_ts__"), (
        f"a ts-less announce must still leave a record: {state!r}")


def test_a_ts_less_note_is_not_repeated_on_every_tick(monkeypatch, tmp_path):
    """⛔ AND THE UNBOUNDED REPEAT. With nothing recorded, the next tick's falsy-ts branch
    fired again — once a minute, forever, each time as if it were news."""
    note = {"email": "e@x.y"}
    first, state = _tick(monkeypatch, tmp_path, note)
    assert "e@x.y" in first
    again, _ = _tick(monkeypatch, tmp_path, note, prior=state)
    assert "e@x.y" not in again, f"a ts-less note must not repeat: {again!r}"


def test_an_empty_announce_says_nothing(monkeypatch, tmp_path):
    """⛔ WIDENING THE FALSY-TS CASE MUST NOT WIDEN THIS ONE. `{}` is not a note with a
    missing timestamp — it is the absence of a note, and announcing it produces a bare
    "✓ Signed in" for a sign-in that never happened."""
    out, _state = _tick(monkeypatch, tmp_path, {})
    assert "Signed in" not in out, f"an empty announce must stay silent, got {out!r}"


def test_a_note_with_a_timestamp_is_still_deduped_across_ticks(monkeypatch, tmp_path):
    """The cross-tick de-dup is what stops a repeat being heard as new news, so widening
    the falsy case must not widen this one."""
    note = {"email": "e@x.y", "ts": 7_000}
    first, state = _tick(monkeypatch, tmp_path, note)
    assert "e@x.y" in first
    assert state.get("__signed_in_ts__") == 7_000
    again, _ = _tick(monkeypatch, tmp_path, note, prior=state)
    assert "e@x.y" not in again, f"the same ts twice must stay silent, got {again!r}"
