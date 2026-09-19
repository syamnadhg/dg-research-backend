"""Wave 8: the agent survives the rename, refuses a machine that cannot run, and
four filed items nobody had scoped.

⛔⛔ EVERY DEFECT HERE IS SILENT. The rename turns public computers private with no
error; the pairing filter announces "Started" on a machine the browser refuses;
the online check never decays; the poller's truncated state file reads as a clean
first tick; and `agent disconnect` deletes a cron row by the script it runs rather
than the name we gave it. Not one of them reports anything.
"""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import bridge, cli, connect
from facade.firestore_rest import is_pair_confirmed, pair_state_usable


# ── the rename ──────────────────────────────────────────────────────────────

def test_the_new_name_is_read_when_the_old_one_is_gone():
    """⛔⛔ `visibility` IS BECOMING `joinPolicy` — the same answer under the name
    groups give it — and `firestore.rules` has admitted both since wave 7 so the
    changeover has a window. Every read site in this agent compared to the old
    literal and fell through to PRIVATE, so the day the migration removes it every
    public computer would read private in chat and in the terminal, with nothing
    anywhere to notice it by."""
    assert bridge._discovery_of({"joinPolicy": "public"}) == "public"
    assert bridge._discovery_of({"joinPolicy": "private"}) == "private"


def test_the_OLD_name_wins_while_it_is_still_there():
    """⛔⛔ RE-AIMED: THE FIRST BUILD PREFERRED THE NEW KEY AND THAT WAS WRONG.
    Nothing writes `joinPolicy` yet, and everything that ACTS on the setting reads
    `visibility` — the app's public list queries
    `where("visibility", "==", "public")`, `isListable` tests `source.visibility`,
    and this agent's own toggle writes `visibility`. A reader preferring the new
    key reports a state the product does not implement.

    ⛔ AND ON THE TOGGLE IT CLOSES NO DOOR. Turn a public machine private: the
    write lands on `visibility`, `joinPolicy` still says public, the next read says
    public — so an owner is answered "already public" and nothing ever changes."""
    assert bridge._discovery_of({"visibility": "private", "joinPolicy": "public"}) == "private"
    assert bridge._discovery_of({"visibility": "public", "joinPolicy": "private"}) == "public"


def _toggle_over_the_wire(monkeypatch, row, want):
    """POST /device/visibility against a REAL handler, with Firestore stubbed.

    Returns (json body, [values actually written]). ⛔ Driving the route is the
    point: the no-op branch is a comparison, and a test that re-did the comparison
    would assert that my copy of it agrees with itself."""
    import threading
    from http.server import ThreadingHTTPServer
    import requests as _rq

    written = []

    class FS:
        def __init__(self, tok):
            pass

        def list_devices(self, uid):
            return [dict(row)]

        def set_device_visibility(self, device_id, value):
            written.append(value)

    monkeypatch.setattr(bridge, "FirestoreRest", FS)
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: None)
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        r = _rq.post(f"http://127.0.0.1:{httpd.server_address[1]}/device/visibility",
                     json={"deviceId": row["id"], "visibility": want},
                     headers={"Origin": f"http://127.0.0.1:{httpd.server_address[1]}"},
                     timeout=10)
        return r.json(), written
    finally:
        httpd.shutdown()
        httpd.server_close()


PUBLIC_UNDER_NEW_NAME = {"id": "d1", "ownerUid": "u1", "joinPolicy": "public",
                         "pairConfirmedAt": True, "name": "Studio PC"}


def test_the_toggle_CLOSES_the_door_on_a_machine_public_under_either_name(monkeypatch):
    """⛔⛔ THE WORST PLACE TO READ THE RAW LITERAL. Read off `visibility` alone, a
    machine public under the NEW name reads private here — so an owner turning it
    private is answered "it is already private", no write goes out, and the machine
    stays discoverable. The one surface whose entire job is closing that door."""
    body, written = _toggle_over_the_wire(monkeypatch, PUBLIC_UNDER_NEW_NAME, "private")
    assert written == ["private"], body
    assert body.get("changed") is True, body


def test_the_toggle_still_does_nothing_when_it_really_is_a_no_op(monkeypatch):
    """The complement, so the fix cannot turn every press into a write."""
    row = {"id": "d1", "ownerUid": "u1", "visibility": "private",
           "pairConfirmedAt": True, "name": "Studio PC"}
    body, written = _toggle_over_the_wire(monkeypatch, row, "private")
    assert written == []
    assert body.get("changed") is False, body


def test_the_reader_agrees_with_the_only_writer_there_is():
    """⭐ STATED AS THE RULE, not as two examples. The key this agent WRITES must be
    the key it believes first, or the toggle and the reader disagree about the
    machine in front of them."""
    import inspect
    from facade import firestore_rest
    writer = inspect.getsource(firestore_rest.FirestoreRest.set_device_visibility)
    written = "visibility" if "updateMask.fieldPaths=visibility" in writer else None
    assert written is not None, "the writer's field is no longer recognisable"
    assert bridge._DISCOVERY_KEYS[0] == written


def test_the_old_name_still_answers_while_machines_still_write_it():
    assert bridge._discovery_of({"visibility": "public"}) == "public"
    assert bridge._discovery_of({"visibility": "private"}) == "private"


@pytest.mark.parametrize("row", [
    {}, {"visibility": ""}, {"joinPolicy": None},
    {"visibility": "PUBLIC"}, {"joinPolicy": "yes"}, {"visibility": 1},
])
def test_anything_unrecognised_reads_as_private(row):
    """⛔ ABSENT IS PRIVATE — a machine paired before 2026-09-04 carries neither
    key — and so is anything this cannot place. For a discovery setting the safe
    direction is the one that hides."""
    assert bridge._discovery_of(row) == "private"


def _devices_over_the_wire(monkeypatch, devs):
    """GET /devices against a REAL handler, with Firestore stubbed.

    ⛔⛔ THE FIRST VERSION OF THIS RE-IMPLEMENTED THE PROJECTION LOOP IN A LOCAL
    HELPER, so it asserted that MY COPY of the code did what my copy did — and the
    harness's own D5 mutant (delete `d["visibility"] = _discovery_of(d)` from
    bridge.py) survived the whole wave's guards. Cross-verification found it by
    applying the mutant and running the full list: 411 passed. A test written in
    terms of the thing under test measures nothing; this one drives the route."""
    import threading
    from http.server import ThreadingHTTPServer
    import requests as _rq

    class FS:
        def __init__(self, tok):
            pass

        def list_devices(self, uid):
            return [dict(d) for d in devs]

    monkeypatch.setattr(bridge, "FirestoreRest", FS)
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: None)
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        r = _rq.get(f"http://127.0.0.1:{httpd.server_address[1]}/devices", timeout=10)
        return r.json().get("devices", [])
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_bridge_RESOLVES_the_name_before_any_row_leaves_it(monkeypatch):
    """⭐ ONE LINE CARRIES ALL THREE SURFACES. Neither client talks to Firestore —
    both read `visibility` off the row the bridge returns — so resolving it there
    is what keeps them right without either of them learning the new name."""
    rows = _devices_over_the_wire(monkeypatch, [
        {"id": "d1", "ownerUid": "u1", "joinPolicy": "public",
         "lastHeartbeat": time.time() * 1000, "pairConfirmedAt": True,
         "pairCode": "SECRET"}])
    assert rows and rows[0]["visibility"] == "public"
    # ⛔ AND THE KEY SET IS UNCHANGED, which is why `test_app_plane_unchanged`
    # still holds and why no secret rode in behind the new reader.
    assert set(rows[0]) <= set(bridge._DEVICE_PUBLIC_KEYS)
    assert "joinPolicy" not in rows[0] and "pairCode" not in rows[0]


def test_the_old_name_still_reaches_the_clients_unchanged(monkeypatch):
    rows = _devices_over_the_wire(monkeypatch, [
        {"id": "d1", "ownerUid": "u1", "visibility": "public",
         "lastHeartbeat": time.time() * 1000, "pairConfirmedAt": True}])
    assert rows[0]["visibility"] == "public"


def test_a_row_under_NEITHER_name_reaches_the_clients_as_private(monkeypatch):
    """⛔ The safe direction, over the wire rather than in a local copy of the loop."""
    rows = _devices_over_the_wire(monkeypatch, [
        {"id": "d1", "ownerUid": "u1", "lastHeartbeat": time.time() * 1000,
         "pairConfirmedAt": True}])
    assert rows[0]["visibility"] == "private"


def test_the_agent_still_writes_the_OLD_name_only():
    """⛔⛔ READING BOTH IS COMPATIBLE; WRITING THE NEW ONE IS NOT. Every installed
    wheel in the field keeps reading `visibility`, and nothing forces an upgrade —
    so the old key comes off when a FLEET READING says nobody is writing it, not
    when a wave number says so. Its own suite hard-pins that write."""
    import inspect
    src = inspect.getsource(bridge.FirestoreRest.set_device_visibility)
    body = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "joinPolicy" not in body.split('"""')[-1]
    assert "updateMask.fieldPaths=visibility" in body


# ── the machine that cannot run ─────────────────────────────────────────────

MID_RESET = {"id": "d-reset", "pairConfirmedAt": True,
             "lastHeartbeat": 1_730_000_000_000, "pairState": "awaiting-re-pair"}
ACTIVE = {"id": "d-ok", "pairConfirmedAt": True,
          "lastHeartbeat": 1_730_000_000_000, "pairState": "active"}


def test_a_machine_mid_reset_cannot_take_a_run():
    """⛔⛔ IT WAS CHOSEN AS THE RUN TARGET AND ANNOUNCED AS "Started" while the
    browser refused the identical machine on the identical account. A Reset leaves
    `pairState: "awaiting-re-pair"` on a machine that is still heartbeating and
    still carries `pairConfirmedAt`, so it passed every test this agent had. No
    clock problem and no outage needed."""
    assert not pair_state_usable(MID_RESET)
    assert not pair_state_usable({"pairState": "awaiting-initial-claim"})


def test_it_is_STILL_LISTED_and_the_selection_is_NOT_dropped():
    """⛔⛔ RE-AIMED AFTER CROSS-VERIFICATION, WHICH FOUND THE FIRST FIX WORSE THAN
    THE DEFECT. Folding this into `is_pair_confirmed` filtered the machine out of
    `list_devices` — so the person's saved selection stopped being a member, read
    as STALE, was cleared, and the run went to a DIFFERENT computer without a word.
    The old bug announced "Started" on a machine that would not run; that one ran
    the research somewhere nobody chose.

    ⭐ The browser keeps the machine in the list (`isPairConfirmed`) and refuses at
    the submit (`isDeviceEligible`). This is that, in this agent's two places."""
    assert is_pair_confirmed(MID_RESET), "the machine is still theirs and still listed"
    device_id, reason, stale = bridge._pick_device_from([MID_RESET, ACTIVE], "d-reset")
    assert device_id is None
    assert reason == "selection_not_ready"
    assert stale is False, "their selection must survive — the machine is still theirs"


def test_it_is_never_silently_swapped_for_another_computer():
    """⛔ THE SECOND SURPRISE. Re-routing would put somebody's research on a
    computer they did not choose, on top of the refusal they were never shown."""
    device_id, reason, _ = bridge._pick_device_from([MID_RESET, ACTIVE], "d-reset")
    assert device_id != "d-ok"
    assert device_id is None


def test_an_auto_pick_skips_a_machine_that_cannot_run():
    """Choosing one FOR somebody and then having it refuse is the same broken
    promise, arrived at without them even naming it."""
    device_id, reason, _ = bridge._pick_device_from([MID_RESET, ACTIVE], None)
    assert device_id == "d-ok", reason


def test_when_none_can_run_it_says_so_rather_than_asking_which():
    device_id, reason, _ = bridge._pick_device_from([MID_RESET], None)
    assert device_id is None
    assert reason == "selection_not_ready"


def test_an_active_machine_is_unaffected():
    assert is_pair_confirmed(ACTIVE)
    assert bridge._pick_device_from([ACTIVE], "d-ok")[0] == "d-ok"


def test_a_legacy_record_with_no_pair_state_is_still_usable():
    """⛔ ABSENT IS USABLE, deliberately. A pre-cutover record under
    `users/{uid}/devices` carries no `pairState`, and the web app admits those for
    exactly that reason — a stricter rule here would refuse machines the app runs
    on."""
    assert pair_state_usable({})
    assert is_pair_confirmed({"pairConfirmedAt": True})
    legacy = {"id": "d-legacy", "pairConfirmedAt": True}
    assert bridge._pick_device_from([legacy], "d-legacy")[0] == "d-legacy"


def test_the_agent_mirrors_the_web_apps_two_rules_in_its_two_places():
    """⭐ STATED, because the whole defect was one rule standing in for two. The
    browser draws the list with `isPairConfirmed` and accepts a submit with
    `isDeviceEligible`; neither does the other's job."""
    import inspect
    from facade import firestore_rest
    body = inspect.getsource(firestore_rest.is_pair_confirmed)
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))
    code = code.split('"""')[-1]
    assert "pair_state_usable" not in code, (
        "the list filter took the run gate back — that drops a machine mid-Reset "
        "out of the list and silently re-routes the run")
    assert "pair_state_usable" in inspect.getsource(bridge._pick_device_from)


# ── the clock ───────────────────────────────────────────────────────────────

def test_a_heartbeat_dated_far_in_the_future_is_not_fresh():
    """⛔⛔ THE ONLINE CHECK NEVER DECAYED. The heartbeat is stamped with the
    MACHINE's clock and aged against this host's, so a machine whose clock runs
    ahead produces a NEGATIVE age — and `age < 30_000` is true of every negative
    number there is. A computer switched off with a fast clock read online here
    for as long as the skew lasted, while the web app called it offline."""
    now_ms = time.time() * 1000
    assert not bridge._device_is_online({"lastHeartbeat": now_ms + 10 * 60_000})


def test_a_clock_a_little_fast_still_reads_online():
    """⛔ LOPSIDED ON PURPOSE, and the web learned this in wave 3: one threshold
    both ways made a working machine 45 s fast read offline everywhere and had
    every run refused."""
    now_ms = time.time() * 1000
    assert bridge._device_is_online({"lastHeartbeat": now_ms + 45_000})


def test_the_two_bounds_are_the_web_app_s_two_bounds():
    """Stated rather than derived — deriving it from the other side is exactly how
    a test stops being able to see a change."""
    assert bridge._DEVICE_ONLINE_MS == 30_000
    assert bridge._HEARTBEAT_FUTURE_TOLERANCE_MS == 5 * 60_000


def test_a_quiet_machine_is_still_offline():
    """The complement, so the future bound cannot swallow the past one."""
    assert not bridge._device_is_online({"lastHeartbeat": time.time() * 1000 - 60_000})


# ── the queue relay's allow-list ────────────────────────────────────────────

def test_the_two_request_halves_carry_different_fields():
    """⛔ `requesterUid` IS THE OWNER'S HALF AND ONLY THERE. `/device/decide` takes
    it as the argument naming who is answered; on the outgoing half there is no
    requester but the caller, so carrying one would publish a uid nobody needs."""
    assert "requesterUid" in bridge._INCOMING_REQUEST_KEYS
    assert "requesterUid" not in bridge._OUTGOING_REQUEST_KEYS
    assert set(bridge._OUTGOING_REQUEST_KEYS) < set(bridge._INCOMING_REQUEST_KEYS)


def _requests_over_the_wire(monkeypatch, upstream):
    """GET /devices/requests against a REAL handler, with the app route stubbed.

    ⛔⛔ THE FIRST VERSION OF THIS REBUILT THE PROJECTION FROM THE KEY LISTS, so it
    asserted that a dict comprehension does what a dict comprehension does — the
    route itself was never executed, and the harness's own Q1 and Q2 could not be
    killed by anything. Cross-verification found it."""
    import threading
    from http.server import ThreadingHTTPServer
    import requests as _rq

    class FS:
        def __init__(self, tok):
            pass

    monkeypatch.setattr(bridge, "FirestoreRest", FS)
    # ⛔ ARBITRARY KEYWORDS, because this helper has grown an argument twice and
    # broken the suite both times — `test_every_stub_of_the_json_helpers_tolerates
    # _a_new_argument` enforces it, and it caught this stub the day it was written.
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda sess, path, *a, **kw: (200, upstream))
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        r = _rq.get(f"http://127.0.0.1:{httpd.server_address[1]}/devices/requests",
                    timeout=10)
        return r.json()
    finally:
        httpd.shutdown()
        httpd.server_close()


UPSTREAM_ROW = {"deviceId": "d1", "deviceLabel": "Studio PC", "createdAt": 1,
                "requesterUid": "u9", "requesterLabel": "Sam",
                "pairCode": "SECRET", "ownerUid": "u1", "sharedWith": ["u2"],
                "pollSecretHash": "h"}


def test_the_queue_relay_prunes_like_the_browse_relay_beside_it(monkeypatch):
    """⛔⛔ IT RELAYED THE APP'S ARRAYS BYTE FOR BYTE — the last device-shaped
    emitter in the file with no allow-list of its own, four lines below the one
    that got one after cross-verification found a whole device row coming through
    a trusting relay, plaintext pair code included."""
    body = _requests_over_the_wire(
        monkeypatch, {"incoming": [dict(UPSTREAM_ROW)], "outgoing": [dict(UPSTREAM_ROW)]})
    for row in (body["incoming"][0], body["requests"][0]):
        assert "pairCode" not in row and "ownerUid" not in row
        assert "sharedWith" not in row and "pollSecretHash" not in row
    assert body["incoming"][0]["requesterUid"] == "u9"
    assert body["incoming"][0]["deviceLabel"] == "Studio PC"


def test_the_outgoing_half_carries_no_requester(monkeypatch):
    """⛔ `requesterUid` IS THE OWNER'S HALF AND ONLY THERE. On the outgoing half
    there is no requester but the caller, so carrying one publishes a uid nobody
    needs to the person who filed the request."""
    body = _requests_over_the_wire(
        monkeypatch, {"incoming": [], "outgoing": [dict(UPSTREAM_ROW)]})
    assert "requesterUid" not in body["requests"][0]
    assert "requesterLabel" not in body["requests"][0]


def test_a_half_that_is_not_a_list_comes_back_empty(monkeypatch):
    body = _requests_over_the_wire(monkeypatch, {"incoming": {"x": 1}, "outgoing": None})
    assert body["incoming"] == [] and body["requests"] == []


# ── the access-code copy ────────────────────────────────────────────────────

def _chat_pair_errors():
    import importlib.util
    import sys
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
    spec = importlib.util.spec_from_file_location("sr_wave8_0916", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sr_wave8_0916"] = mod
    spec.loader.exec_module(mod)
    return mod._PAIR_ERRORS


@pytest.mark.parametrize("table_name", ["chat", "terminal"])
def test_a_dead_code_no_longer_sends_somebody_to_mint_a_new_computer(table_name):
    """⛔⛔ THE REPAIR IT NAMED LOSES THE MACHINE'S IDENTITY AND EVERYONE IT WAS
    SHARED WITH. Both tables sent a person with an expired code to `superresearch
    --pair`, which on a computer that still exists does not refresh anything — it
    sets that computer up as a NEW one with a new id. The repair is Reset, which
    the web app's own table has said since wave 2."""
    table = _chat_pair_errors() if table_name == "chat" else cli._PAIR_FAILURES
    expired = table["code_expired"].lower()
    assert "--pair" not in expired, expired
    assert "reset" in expired, expired


@pytest.mark.parametrize("table_name", ["chat", "terminal"])
def test_the_not_found_line_puts_reset_first_and_pair_last(table_name):
    """⛔ `--pair` IS STILL NAMED, and only where it is right: once the computer is
    gone from Manage devices there is nothing to reset and it IS a new setup. What
    changed is the ORDER and the warning that goes with it."""
    table = _chat_pair_errors() if table_name == "chat" else cli._PAIR_FAILURES
    line = table["code_not_found"]
    low = line.lower()
    assert "reset" in low, line
    assert "--pair" in low, line
    assert low.index("reset") < low.index("--pair"), line
    assert "new id" in low and "keeps access" in low, line


@pytest.mark.parametrize("table_name", ["chat", "terminal"])
def test_the_removed_sharer_line_was_already_right_and_stays_right(table_name):
    """⭐ NOT PORTED FROM THE WEB — the web's is the defect. Its line said "ask
    them to share a new code with you", which the blocklist refuses on every
    door."""
    table = _chat_pair_errors() if table_name == "chat" else cli._PAIR_FAILURES
    line = table["revoked_sharer"].lower()
    assert "removed your access" in line
    assert "only they can" in line
    assert "share a new code" not in line


# ── the poller's state file ─────────────────────────────────────────────────

def _poller():
    import importlib.util
    import sys
    path = (Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"
            / "sr_attention_poll.py")
    spec = importlib.util.spec_from_file_location("srpoll_wave8_0916", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["srpoll_wave8_0916"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_failed_save_leaves_the_OLD_state_readable(monkeypatch, tmp_path):
    """⛔⛔ A BARE `write_text` TRUNCATES BEFORE IT WRITES, and what a reader finds
    in that window is not a missed save — it is a file that parses as nothing.
    `_load_state` answers None for anything unreadable, and None means "first tick
    after arming", which BASELINES SILENTLY. So an interrupted write did not cost
    one announcement; it cost every phase that completed while it was happening,
    with nothing to notice it by."""
    poll = _poller()
    state = tmp_path / ".sr_stream_state.json"
    poll._save_state({"r1": {"announced": ["p1"]}}, state)
    assert poll._load_state(state) == {"r1": {"announced": ["p1"]}}

    monkeypatch.setattr(poll.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no space")))
    poll._save_state({"r1": {"announced": ["p1", "p2"]}}, state)
    # ⭐ THE OLD STATE SURVIVES INTACT — the run is announced from where it was,
    # not baselined into silence.
    assert poll._load_state(state) == {"r1": {"announced": ["p1"]}}


def test_a_failed_save_leaves_no_temp_file_behind(monkeypatch, tmp_path):
    poll = _poller()
    state = tmp_path / ".sr_stream_state.json"
    poll._save_state({"a": {"announced": []}}, state)
    monkeypatch.setattr(poll.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no space")))
    poll._save_state({"b": {"announced": []}}, state)
    assert [p.name for p in tmp_path.iterdir()] == [".sr_stream_state.json"]


def test_disconnect_sweeps_the_atomic_writes_leftovers(monkeypatch, tmp_path):
    """⛔⛔ THE NEW TEMP NAME MATCHED NEITHER GLOB. `_uninstall_stream_script` names
    the exact `.json` files and globs for names ENDING in `.state.json` or `.py` —
    and a tick killed between the write and the replace leaves a temp file that
    ends in neither. `agent disconnect` would leave it in HERMES_HOME/scripts
    forever, one per killed tick.

    ⛔⛔ AND THE NAME IS PRODUCED BY THE WRITER, NEVER TYPED HERE. Hardcoding
    `.sr_stream_state.json.sr-tmp.4242` let the writer's temp-name shape change out
    from under the sweep with the whole suite green — the wave's own A2 mutant
    (drop the per-process `%d`) SURVIVED the first mutation run for exactly that
    reason. A sweep test that invents its own debris is testing its own invention.
    """
    poll = _poller()
    scripts = tmp_path / ".hermes" / "scripts"
    scripts.mkdir(parents=True)

    # A save interrupted between the write and the replace, with the cleanup also
    # failing — which is how the debris survives in the first place.
    monkeypatch.setattr(poll.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no space")))
    monkeypatch.setattr(poll.Path, "unlink",
                        lambda self, **k: (_ for _ in ()).throw(OSError("read-only")))
    for name in (".sr_stream_state.json", ".sr_poll_openclaw_abc.state.json"):
        poll._save_state({"r": {"announced": []}}, scripts / name)

    debris = sorted(q.name for q in scripts.iterdir())
    assert debris, "the writer left nothing to sweep — this test cannot see its subject"
    keep = "someone_elses_notes.txt"
    (scripts / keep).write_text("x", encoding="utf-8")

    monkeypatch.undo()
    connect._uninstall_stream_script(tmp_path)
    left = sorted(q.name for q in scripts.iterdir())
    assert left == [keep], f"{left} — the sweep missed {debris}"


def test_the_save_is_a_replace_and_not_a_truncating_write():
    """Pinned on the mechanism, because the failure it prevents is invisible in
    any single-process test: the window only exists when something interrupts."""
    poll = _poller()
    import inspect
    body = inspect.getsource(poll._save_state)
    body = body.split('"""')[-1]
    assert "os.replace(" in body
    assert ".write_text(" in body and "target.write_text" not in body


# ── the disconnect matcher ──────────────────────────────────────────────────

def test_a_row_that_only_LOOKS_like_a_shim_is_not_claimed():
    """⛔⛔ IT MATCHED A PREFIX, AND A PREFIX IS NOT A FILENAME.
    `script.startswith("sr_poll_")` is true of `sr_poll_notes.txt`, of
    `sr_poll_x.py.bak` and of anything else beginning with those eight characters —
    so `agent disconnect` would delete a cron row pointing at a file that is not
    one of our generated shims and could not be. `_POLL_SHIM_RE` has sat beside the
    function since the shims existed and describes exactly the right shape; it was
    simply never used here."""
    assert not connect._is_stream_job({"script": "sr_poll_abc.py.bak"})
    assert not connect._is_stream_job({"script": "sr_poll_notes.txt"})
    assert not connect._is_stream_job({"script": "sr_poll_.py"})
    assert not connect._is_stream_job({"script": "sr_poller.py"})
    assert not connect._is_stream_job({"script": "my_sr_poll_abc.py"})


def test_our_own_jobs_are_still_ours():
    assert connect._is_stream_job({"name": "sr-stream", "script": "sr_attention_poll.py"})
    assert connect._is_stream_job({"name": "sr-stream-abc", "script": "sr_poll_abc.py"})
    assert connect._is_stream_job({"name": "sr-update-notice", "script": "sr_update_notice.py"})


def test_a_renamed_job_of_ours_is_still_ours():
    """⭐ THE SCRIPT FALLBACK IS DELIBERATE AND IT STAYS. It catches a job of OURS
    whose NAME drifted — a real state, because the arming writer and the teardown
    edit the same file — and `test_remove_stream_cron_drops_per_chat_jobs` has
    pinned that case since the shims shipped. Narrowing it to nameless rows only
    would have reversed a tested decision on my own initiative.

    ⚠ IT IS STILL HOST-WIDE, and that is an owner question rather than a defect
    this function can settle: on a fleet-shaped machine a shared `HERMES_HOME`
    holds every chat's cron entries, so one chat's disconnect sweeps every chat's
    watchdog — by NAME exactly as much as by script."""
    assert connect._is_stream_job({"name": "custom-name", "script": "sr_poll_abc.py"})
    assert connect._is_stream_job({"script": "sr_attention_poll.py"})
    assert connect._is_stream_job({"name": "", "script": "sr_poll_abc.py"})


def test_a_row_that_is_not_a_dict_is_not_a_job():
    assert not connect._is_stream_job("sr-stream")
    assert not connect._is_stream_job(None)


# ── the "unlock command" confirm ────────────────────────────────────────────

def test_there_is_no_access_code_for_an_unlock_to_gate():
    """⭐ THE ANSWER TO A CONFIRM ITEM, PINNED SO IT STAYS THE ANSWER. The filed
    item asks whether the agent's unlock command is "wired like the rest, natural
    language included". There is no such command, and there is nothing for one to
    do: the web app's lock guards REVEALING a machine's access code, and this agent
    never has one to reveal — `_DEVICE_PUBLIC_KEYS` is an allow-list that does not
    contain `pairCode`, and every emitter in the bridge is pruned to it.

    ⛔ SO THE ITEM CLOSES BY MEASUREMENT RATHER THAN BY WORK, and this is the
    measurement. If a future wave puts an access code on the wire, the item
    re-opens here rather than in somebody's memory."""
    assert "pairCode" not in bridge._DEVICE_PUBLIC_KEYS
    assert "pairCode" not in bridge._PUBLIC_DEVICE_KEYS
    assert "pairCode" not in bridge._INCOMING_REQUEST_KEYS
    assert "pairCode" not in bridge._OUTGOING_REQUEST_KEYS


def test_the_agent_log_facts_travel_with_the_flag_on_the_check_route():
    """⛔⛔ THE CONSENT SCREEN IS PRINTED BY A DIFFERENT COMMAND, AND NOTHING
    CHECKED THAT IT EVER WAS. The second step is reached with a support code and a
    flag — `send-logs --status <CODE> --agent-log` — so an assistant arriving
    straight there could upload this file having shown the person nothing about
    what is in it. Nothing on the wire records that the plan was ever seen, and the
    bridge cannot know. The facts are three sentences; they ride the flag instead
    of resting on a directive somebody is asked to follow."""
    import inspect
    body = inspect.getsource(cli.cmd_send_logs)
    status_half = body[:body.index("path = \"/logs/runs\"")]
    assert "_agent_log_fact_lines()" in status_half, status_half[-600:]
