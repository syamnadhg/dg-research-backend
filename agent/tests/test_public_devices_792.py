"""The bridge's three public-computer routes and the terminal verbs on top of
them (wave 7.9-2, B2 / B3 / B4).

⛔⛔ WHAT THIS CODE DECIDES. Whether a person with no computer of their own can
find one at all from the agent; whether asking for one is honest about who is
told what; and whether a request that has been ANSWERED is reported as an answer
rather than as a silence a client is free to interpret.
"""

from __future__ import annotations

import inspect
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge, cli
from tests.conftest import code_only


class FakeFS:
    devices: list[dict] = []

    def __init__(self, _token_provider):
        pass

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]


@pytest.fixture()
def live(monkeypatch):
    FakeFS.devices = []
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    sel = {"v": None}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device", lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: sel.__setitem__("v", None))
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", sel
    finally:
        httpd.shutdown()
        httpd.server_close()


ROW = {"deviceId": "dev-a1", "label": "Studio PC", "osFamily": "macos",
       "online": True, "full": False}


# ── GET /devices/public ──────────────────────────────────────────────────────

def test_browse_forwards_to_the_web_route_and_relays_the_rows(live, monkeypatch):
    seen = {}

    def _get(sess, path, params=None, **_kw):
        seen["path"] = path
        return 200, {"devices": [ROW], "truncated": False}

    monkeypatch.setattr(bridge, "_fe_api_get", _get)
    body = requests.get(live[0] + "/devices/public").json()
    assert seen["path"] == "/api/devices/public"
    assert body["devices"] == [ROW] and body["truncated"] is False


def test_browse_relays_truncated(live, monkeypatch):
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda s, p, params=None, **_kw: (200, {"devices": [ROW], "truncated": True}))
    assert requests.get(live[0] + "/devices/public").json()["truncated"] is True


def test_browse_never_decorates_a_public_row(live, monkeypatch):
    # ⛔⛔ THE SHARPEST ONE. `_decorate_devices` answers three questions from
    # fields a public projection does not carry: `owned` from an absent ownerUid,
    # `selected` from an absent `id`, and `online` from an absent lastHeartbeat —
    # the last of which would OVERWRITE the liveness the route computed right.
    # Three wrong answers, every one shaped like a real one.
    live_base, sel = live
    sel["v"] = "dev-a1"
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda s, p, params=None, **_kw: (200, {"devices": [dict(ROW)],
                                                         "truncated": False}))
    row = requests.get(live_base + "/devices/public").json()["devices"][0]
    assert row["online"] is True, "the route's liveness must survive"
    assert "owned" not in row and "selected" not in row


def test_browse_coerces_a_missing_or_wrong_shaped_list(live, monkeypatch):
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda s, p, params=None, **_kw: (200, {"devices": "nope"}))
    body = requests.get(live[0] + "/devices/public").json()
    assert body == {"devices": [], "truncated": False}


@pytest.mark.parametrize("verb,path,body", [
    ("get", "/devices/public", None),
    ("get", "/devices/requests", None),
    ("post", "/device/ask", {"deviceId": "dev-a1"}),
])
def test_every_new_route_refuses_when_signed_out(monkeypatch, verb, path, body):
    # ⛔ SIGNED OUT IS ITS OWN ANSWER. `_account()` has to run BEFORE the web app
    # is called, or a signed-out person's request leaves this machine carrying no
    # token and comes back as somebody else's 401.
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)

    def _boom(*a, **kw):
        raise AssertionError("reached the web app with no session")

    monkeypatch.setattr(bridge, "_fe_api_get", _boom)
    monkeypatch.setattr(bridge, "_fe_api_post", _boom)
    # A fresh state with no session — `_no_real_account_session` in conftest
    # guarantees nothing is rehydrated from the developer's own keychain.
    state = bridge.BridgeState()
    assert state.session is None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        r = getattr(requests, verb)(f"http://127.0.0.1:{port}" + path, json=body)
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert r.status_code == 401 and "not signed in" in r.json()["error"]


# ── GET /devices/requests ────────────────────────────────────────────────────

def test_requests_forwards_and_keeps_the_two_halves_apart(live, monkeypatch):
    """⛔⛔ REWRITTEN IN 7.9-3, NOT DELETED, AND ITS PREMISE IS REVERSED.

    Until 7.9-3 this test pinned the owner's half being DROPPED, and that was
    right: nothing on this surface could answer one, so naming people whose
    request had no verb was a dead end wearing a list's clothes. `/device/decide`
    is that verb, so the reason expired — and a test still demanding the old
    behaviour would have been a test demanding the wrong advice, which this
    project has shipped before.

    What it pins now is the invariant that outlives the change: both halves
    cross the wire and they stay APART. Merged, an owner is told that somebody
    else's request for their machine is something THEY are waiting on.
    """
    seen = {}

    def _get(sess, path, params=None, **_kw):
        seen["path"] = path
        return 200, {
            "incoming": [{"deviceId": "dev-mine", "deviceLabel": "My Mac",
                          "requesterUid": "u9", "requesterLabel": "Someone Else",
                          "createdAt": 7}],
            "outgoing": [{"deviceId": "dev-a1", "deviceLabel": "Studio PC",
                          "createdAt": 5}],
        }

    monkeypatch.setattr(bridge, "_fe_api_get", _get)
    body = requests.get(live[0] + "/devices/requests").json()
    assert seen["path"] == "/api/devices/access-request"
    assert body["requests"] == [{"deviceId": "dev-a1", "deviceLabel": "Studio PC",
                                 "createdAt": 5}]
    assert body["incoming"] == [{"deviceId": "dev-mine", "deviceLabel": "My Mac",
                                 "requesterUid": "u9",
                                 "requesterLabel": "Someone Else",
                                 "createdAt": 7}]
    # The two lists never share a member — that is the whole point of two names.
    assert not [r for r in body["requests"] if r in body["incoming"]]


def test_requests_reports_each_half_absent_as_empty_not_missing(live, monkeypatch):
    """A reply carrying neither half answers with two empty lists, never with a
    missing key: a client that has to tell "nobody is waiting" from "this bridge
    does not report that" would be reading the difference out of a KeyError."""
    monkeypatch.setattr(bridge, "_fe_api_get", lambda *a, **k: (200, {}))
    body = requests.get(live[0] + "/devices/requests").json()
    assert body == {"requests": [], "incoming": []}


def test_requests_refuses_a_non_list_half(live, monkeypatch):
    """Neither half is trusted to be a list. A string would otherwise be
    iterated character by character by both clients."""
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda *a, **k: (200, {"outgoing": "nope",
                                               "incoming": {"a": 1}}))
    body = requests.get(live[0] + "/devices/requests").json()
    assert body == {"requests": [], "incoming": []}


# ── POST /device/ask ─────────────────────────────────────────────────────────

def test_ask_forwards_the_device_id(live, monkeypatch):
    seen = {}

    def _post(sess, path, payload, **_kw):
        seen.update(path=path, payload=payload)
        return 200, {"ok": True, "status": "pending"}

    monkeypatch.setattr(bridge, "_fe_api_post", _post)
    body = requests.post(live[0] + "/device/ask", json={"deviceId": "dev-a1"}).json()
    assert seen["path"] == "/api/devices/access-request"
    assert seen["payload"] == {"deviceId": "dev-a1"}
    assert body["ok"] is True and body["status"] == "pending"


def test_ask_refuses_an_empty_device_id(live):
    r = requests.post(live[0] + "/device/ask", json={})
    assert r.status_code == 400 and "deviceId" in r.json()["error"]


def test_ask_relays_a_refusal_with_its_code_and_wait(live, monkeypatch):
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda s, p, b, **_kw: (429, {"error": "rate_limited",
                                               "retryAfterMs": 900_000}))
    r = requests.post(live[0] + "/device/ask", json={"deviceId": "dev-a1"})
    assert r.status_code == 429
    assert r.json() == {"error": "rate_limited", "retryAfterMs": 900_000}


def test_ask_keeps_the_strangers_id_out_of_the_uploadable_log(live, monkeypatch):
    # ⛔⛔ THIS LOG GOES TO SUPPORT. What somebody agrees to before it goes says
    # it holds "the ids of the computers and runs this agent has touched" — a
    # machine this account merely asked about, and may be refused, is not one of
    # those, and nothing here masks a machine's LABEL either.
    #
    # ⛔ ITS OWN HANDLER, NOT `caplog`. This module's logger does not always
    # propagate to the root by the time the whole suite has run — the first
    # version of this test passed alone and was empty in the full run, which is
    # the shape of a guard that quietly stops guarding.
    import logging

    seen: list[str] = []

    class _Sink(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    sink = _Sink()
    logger = logging.getLogger("facade.bridge")
    logger.addHandler(sink)
    old = logger.level
    logger.setLevel(logging.INFO)
    try:
        monkeypatch.setattr(bridge, "_fe_api_post", lambda s, p, b, **_kw: (200, {"ok": True}))
        requests.post(live[0] + "/device/ask", json={"deviceId": "dev-secret-99"})
    finally:
        logger.removeHandler(sink)
        logger.setLevel(old)
    text = "\n".join(seen)
    assert "device ask" in text, "the ask must still leave a trace"
    assert "dev-secret-99" not in text


# ── a dead session is a 401, on every route that reaches the web app ─────────

@pytest.mark.parametrize("verb,path,body", [
    ("get", "/devices/public", None),
    ("get", "/devices/requests", None),
    ("post", "/device/ask", {"deviceId": "dev-a1"}),
    ("post", "/device/pair", {"code": "K7XQ9B2M"}),
    ("post", "/device/remove", {"deviceId": "dev-a1"}),
])
def test_a_revoked_session_is_401_not_502(live, monkeypatch, verb, path, body):
    # ⛔⛔ `_fe_api_*` RETURNS 0 FOR BOTH A DEAD SESSION AND AN UNREACHABLE APP,
    # and every device route mapped 0 to 502 — reporting the one failure the
    # person can fix as the one they cannot. The discriminator was always on the
    # wire and nothing read it.
    dead = (0, {"reason": "revoked",
                "error": "this agent's session was rejected — run login again"})
    monkeypatch.setattr(bridge, "_fe_api_get", lambda s, p, params=None, **_kw: dead)
    monkeypatch.setattr(bridge, "_fe_api_post", lambda s, p, b, **_kw: dead)
    r = getattr(requests, verb)(live[0] + path, json=body)
    assert r.status_code == 401, path
    assert r.json()["reason"] == "revoked"


@pytest.mark.parametrize("verb,path,body", [
    ("get", "/devices/public", None),
    ("get", "/devices/requests", None),
    ("post", "/device/ask", {"deviceId": "dev-a1"}),
])
def test_an_unreachable_web_app_is_still_502(live, monkeypatch, verb, path, body):
    down = (0, {"error": "could not reach https://app.test (ConnectionError)"})
    monkeypatch.setattr(bridge, "_fe_api_get", lambda s, p, params=None, **_kw: down)
    monkeypatch.setattr(bridge, "_fe_api_post", lambda s, p, b, **_kw: down)
    r = getattr(requests, verb)(live[0] + path, json=body)
    assert r.status_code == 502, path


# ── selecting a machine you have only asked for ──────────────────────────────

def test_selecting_an_unlinked_machine_says_so_in_permission_words(live):
    # ⛔ "not reachable by this account" described a NETWORK. Browsing prints ids
    # of computers this account has not been given, and selecting one is the
    # first thing anybody tries — so the refusal is read in the one moment its
    # old wording was most misleading.
    r = requests.post(live[0] + "/device/select", json={"deviceId": "dev-a1"})
    assert r.status_code == 404
    said = r.json()["error"]
    assert "linked to your account" in said
    assert "reachable" not in said


# ── the terminal ─────────────────────────────────────────────────────────────

@pytest.fixture()
def term(monkeypatch, capsys):
    calls: list[tuple] = []
    box: dict = {"get": {}, "post": {}}

    def _bridge_get(path, timeout=10.0):
        calls.append(("GET", path, timeout))
        return box["get"].get(path)

    def _bridge_post(path, body=None, timeout=30.0):
        calls.append(("POST", path, body))
        return box["post"].get(path)

    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _msg: None)
    monkeypatch.setattr(cli, "_bridge_get", _bridge_get)
    monkeypatch.setattr(cli, "_bridge_post", _bridge_post)
    return SimpleNamespace(box=box, calls=calls, out=lambda: capsys.readouterr().out)


def _run(**kw):
    import argparse
    return cli.cmd_device(argparse.Namespace(**kw))


def test_the_terminal_lists_public_computers_with_their_ids(term):
    term.box["get"]["/devices/public"] = (200, {"devices": [
        dict(ROW), {"deviceId": "dev-b2", "label": "Research computer",
                    "osFamily": "linux", "online": False, "full": True}],
        "truncated": False})
    assert _run(device_command="public") == 0
    out = term.out()
    assert "Public computers (2):" in out
    assert "id=dev-a1" in out and "id=dev-b2" in out
    assert "online" in out and "offline" in out
    # ⛔⛔ `full` SAYS WHAT IT MEANS NOW. It was printed as the bare word beside
    # an invitation to ask, and the route refuses these with certainty — so the
    # row invited an ask that spent one of five an hour on a guaranteed no.
    assert "can't take anyone else" in out
    # ⛔ THE DISCLOSURE IS ON THE SCREEN THAT OFFERS THE ASK, not buried in the
    # ask's own output — a person decides here whether to ask at all.
    # ⛔⛔ AND IT SAYS WHAT THE ASK ITSELF SAYS. This file's own
    # `test_the_terminal_ask_names_what_the_owner_sees` pins "or your email, if
    # you have not set one" forty lines below; this screen said "your name and
    # email address", which is the phrasing the chat client's confirm was
    # corrected away from in 7.9-2.
    assert "or your email, if you have not set one" in out
    assert "name and email address" not in out


def test_the_terminal_says_truncation_is_about_the_scan(term):
    term.box["get"]["/devices/public"] = (200, {"devices": [ROW], "truncated": True})
    _run(device_command="public")
    out = term.out()
    # ⛔⛔ NOT "your list was cut". The flag is set on the raw scan BEFORE the app
    # drops the ones you cannot ask for, so it can be true beside a short list —
    # and there is no next page to offer, so nothing may promise one.
    assert "scan" in out
    assert "next page" not in out and "more of them" not in out


def test_the_terminal_browse_waits_longer_than_a_firestore_read(term):
    term.box["get"]["/devices/public"] = (200, {"devices": []})
    _run(device_command="public")
    timeout = next(c[2] for c in term.calls if c[1] == "/devices/public")
    # ⛔ `_bridge_get`'s DEFAULT IS TEN SECONDS, right for the Firestore-backed
    # routes it was written for. This one waits on the bridge waiting on the WEB
    # APP, which is allowed fifteen on its own before a retry.
    assert timeout > 25


def test_the_terminal_empty_browse_explains_why_it_is_empty(term):
    term.box["get"]["/devices/public"] = (200, {"devices": [], "truncated": False})
    assert _run(device_command="public") == 0
    assert "switches that on" in term.out()


def test_the_terminal_ask_sends_the_id_and_says_who_decides(term):
    term.box["post"]["/device/ask"] = (200, {"ok": True, "status": "pending"})
    assert _run(device_command="ask", deviceId="dev-a1") == 0
    assert ("POST", "/device/ask", {"deviceId": "dev-a1"}) in term.calls
    out = term.out()
    assert "owner decides" in out
    assert "agent device requests" in out


@pytest.mark.parametrize("err", ["revoked_sharer", "recently_denied", "is_owner",
                                 "already_shared", "share_cap_reached",
                                 "already_pending", "device_not_found",
                                 "too_many_requests", "device_queue_full"])
def test_every_ask_refusal_has_words_of_its_own(term, err):
    term.box["post"]["/device/ask"] = (403, {"error": err})
    assert _run(device_command="ask", deviceId="dev-a1") == 1
    out = term.out()
    assert err not in out, "the machine's code must not be the sentence"
    assert len(out.strip()) > 20


def test_a_permanent_refusal_does_not_invite_a_retry(term):
    # ⛔⛔ BORROWING `_PAIR_ERRORS` WAS THE SHORTCUT AND IT IS WRONG HERE. Its
    # `revoked_sharer` line ends "ask them to share it again" — on this route
    # being on that list is exactly what the refusal IS.
    term.box["post"]["/device/ask"] = (403, {"error": "revoked_sharer"})
    _run(device_command="ask", deviceId="dev-a1")
    out = term.out().lower()
    assert "ask them" not in out and "try again" not in out
    assert "not something asking again can change" in out


def test_the_rate_limit_uses_the_number_the_server_sent(term):
    term.box["post"]["/device/ask"] = (429, {"error": "rate_limited",
                                             "retryAfterMs": 900_000})
    _run(device_command="ask", deviceId="dev-a1")
    assert "15 minutes" in term.out()


def test_the_rate_limit_names_no_wait_when_none_was_sent(term):
    term.box["post"]["/device/ask"] = (429, {"error": "rate_limited"})
    _run(device_command="ask", deviceId="dev-a1")
    out = term.out()
    assert "minute" not in out and "hour" in out


def test_a_sub_minute_wait_never_rounds_down_to_zero(term):
    term.box["post"]["/device/ask"] = (429, {"error": "rate_limited",
                                             "retryAfterMs": 50_000})
    _run(device_command="ask", deviceId="dev-a1")
    out = term.out()
    assert "0 minutes" not in out and "1 minute" in out


def test_the_terminal_requests_list_says_what_a_missing_row_means(term):
    term.box["get"]["/devices/requests"] = (200, {"requests": [
        {"deviceId": "dev-a1", "deviceLabel": "Studio PC", "createdAt": 1}]})
    assert _run(device_command="requests") == 0
    out = term.out()
    assert "Waiting on (1):" in out and "Studio PC" in out
    # ⛔⛔ QUALIFIED IN 7.9-3, AND THIS ASSERTION WAS PART OF THE DEFECT. The
    # sentence was written when the asker's list was the only thing on screen;
    # the owner's queue now prints above it and every clause is false of that
    # half. Two tests demanded the unqualified string, so the copy could not be
    # corrected without going red — they were enshrining it.
    out = " ".join(out.split())
    assert "Of the ones YOU asked for" in out
    assert "leaves that half either way" in out


def test_the_empty_requests_list_says_it_too(term):
    # ⛔⛔ ON BOTH BRANCHES. Empty is exactly when somebody is most likely to
    # decide for themselves that the silence means no.
    term.box["get"]["/devices/requests"] = (200, {"requests": []})
    _run(device_command="requests")
    out = term.out()
    assert "not waiting on any computer" in out
    # ⛔ Same correction as above, and said on the empty branch too — empty is
    # exactly when somebody decides for themselves what the silence means.
    out = " ".join(out.split())
    assert "Of the ones YOU asked for" in out
    assert "leaves that half either way" in out


def test_no_client_calls_a_missing_request_a_refusal():
    for src in (code_only(inspect.getsource(cli._device_requests)),):
        low = src.lower()
        assert "denied" not in low and "refused" not in low and "said no" not in low


# ── the three defects this surface was already shipping ─────────────────────

def test_the_owned_list_shows_whether_a_machine_is_on(term):
    # ⛔ THE BRIDGE HAS ALWAYS SENT `online` AND THIS LINE DROPPED IT — while the
    # chat picker one file over prints it.
    term.box["get"]["/devices"] = (200, {"devices": [
        {"id": "dev-a1", "name": "Studio PC", "owned": True, "online": True},
        {"id": "dev-b2", "name": "Mac mini", "owned": False, "online": False}],
        "selectedDeviceId": "dev-a1"})
    assert _run(device_command=None) == 0
    out = term.out()
    assert "online" in out and "offline" in out


def test_a_bodyless_failure_never_prints_the_word_none(term):
    term.box["post"]["/device/select"] = (500, {})
    assert _run(device_command="use", deviceId="dev-a1") == 1
    assert "None" not in term.out()


def test_a_signed_out_list_prints_the_repair_not_a_python_dict(term):
    term.box["get"]["/devices"] = (401, {"error": "not signed in — run /login"})
    assert _run(device_command=None) == 1
    out = term.out()
    assert "not signed in — run /login" in out
    assert "{'error'" not in out


def test_the_windows_hint_names_a_phrase_chat_actually_routes(monkeypatch):
    # ⛔ `/sr device` RESOLVES TO NOTHING — chat matches "devices" and
    # "device list" and never the bare word, so this hint sent every Windows
    # user to the one phrasing answered with "I didn't catch a Super Research
    # request in that".
    said = {}
    monkeypatch.setattr(cli, "_redirect_if_wsl",
                        lambda msg: said.setdefault("msg", msg) or 0)
    import argparse
    cli.cmd_device(argparse.Namespace(device_command=None))
    assert "/sr devices" in said["msg"]


# ── the terminal repairs cross-verify found after green ─────────────────────

def test_the_terminal_refuses_a_full_row_before_spending_an_ask(term):
    term.box["get"]["/devices/public"] = (200, {"devices": [
        {"deviceId": "dev-f", "label": "Busy PC", "online": True, "full": True}]})
    _run(device_command="public")
    out = term.out()
    assert "can't take anyone else" in out


def test_the_terminal_says_what_it_discloses_on_the_ask_itself(term):
    # ⛔ SOMEBODY WITH AN ID NEVER SEES THE BROWSE SCREEN, and the disclosure was
    # printed only there — so the one path that reaches the route directly was
    # the one that never named what it discloses.
    term.box["post"]["/device/ask"] = (200, {"ok": True})
    _run(device_command="ask", deviceId="dev-a1")
    out = term.out()
    assert "or your email, if you have not set one" in out


def test_the_terminal_requests_screen_does_not_promise_to_read_back_a_yes(term):
    term.box["get"]["/devices/requests"] = (200, {"requests": []})
    _run(device_command="requests")
    out = term.out()
    # ⛔⛔ AN APPROVAL CANNOT BE READ BACK BY ASKING AGAIN: the machine leaves the
    # public list once this account is on it. It reports itself by appearing in
    # the account's own list.
    assert "told which it was" not in out
    assert "agent device" in out


def test_the_terminal_empty_browse_still_reports_a_truncated_scan(term):
    # ⛔⛔ THE FLAG WAS REPORTED ONLY ON THE NON-EMPTY BRANCH. It is computed on
    # the raw scan, so zero rows can mean "the scan filled and everything in it
    # was filtered" — over which a flat "nobody is offering" is the one reading
    # that is definitely wrong.
    term.box["get"]["/devices/public"] = (200, {"devices": [], "truncated": True})
    _run(device_command="public")
    out = term.out()
    assert "not be the whole story" in out


def test_the_terminal_ask_waits_as_long_as_its_siblings(term):
    # ⛔ THE ONE VERB THAT WRITES was left on the 30s default its two read
    # siblings were widened past, so it was the most likely to report a failure
    # on a request the app had already filed.
    term.box["post"]["/device/ask"] = (200, {"ok": True})
    _run(device_command="ask", deviceId="dev-a1")
    sent = next(c for c in term.calls if c[1] == "/device/ask")
    assert sent[2] == {"deviceId": "dev-a1"}
    import inspect
    src = inspect.getsource(cli._device_ask)
    assert "timeout=40.0" in src


@pytest.mark.parametrize("sub,phrase", [
    ("public", "public computers"),
    ("ask", "ask for"),
    ("requests", "waiting on"),
])
def test_the_windows_hint_matches_the_subcommand(monkeypatch, sub, phrase):
    # ⛔⛔ THE REDIRECT RUNS BEFORE THE DISPATCH, so all three new verbs were
    # answered under WSL with a pointer at the OWNED device list — a different
    # question, given to somebody who had just asked a public one.
    said = {}
    monkeypatch.setattr(cli, "_redirect_if_wsl",
                        lambda msg: said.setdefault("msg", msg) or 0)
    import argparse
    cli.cmd_device(argparse.Namespace(device_command=sub, deviceId="x"))
    assert phrase in said["msg"], said


def test_the_relay_hands_over_a_status_not_a_sentence(live, monkeypatch):
    # ⛔ BOTH SIDES USED TO WRITE THE SENTENCE, so an unworded failure read
    # "couldn't ask for that computer: could not ask for that computer (HTTP
    # 500)". The bridge names the status; the client words it.
    monkeypatch.setattr(bridge, "_fe_api_post", lambda s, p, b, **kw: (500, {}))
    r = requests.post(live[0] + "/device/ask", json={"deviceId": "dev-a1"})
    assert r.status_code == 500
    assert r.json()["error"] == "http_500"
    assert "could not ask" not in r.text
