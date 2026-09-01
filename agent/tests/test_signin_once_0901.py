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
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert "Research Computer" in out and "Macbook" in out, out
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


def test_login_done_keeps_the_cue_to_act_for_a_topic_only_note(live, capsys):
    """⛔⛔ A DEFECT I FOUND IN MY OWN FIX. The note's FOURTH case is the legacy fallback,
    *"Continue with X? Say go ahead and I'll start it."* — a question aimed at the
    PERSON. SKILL.md step 2 is written against *"Continuing your research on X…"* and
    treats it as the cue to run `research` at once, so preferring the note here swaps a
    cue-to-act for a question and the topic is stranded: the assistant waits for a "go
    ahead" that was already given.

    ⭐ The note is STILL taken — that is what stops the watchdog repeating the news."""
    base, state = live
    flow = bridge.RemoteFlow("pt", "CODE", "https://x/y", 9e18)
    flow.state = "connected"
    flow.pending_topic = "quantum error correction"
    state.set_remote(flow)
    state.set_signed_in({"ts": 7_000, "uid": "u1", "email": "e@x.y", "origin": None,
                         "pendingTopic": "quantum error correction"})
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert "Continuing your research" in out, out
    assert "go ahead" not in out, f"a cue to act must not become a question: {out!r}"
    assert state.signed_in is None, "the note must still be taken"


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
    assert sr.main(["login-done"]) == 0
    out = capsys.readouterr().out
    assert "Research Computer" in out, out
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
