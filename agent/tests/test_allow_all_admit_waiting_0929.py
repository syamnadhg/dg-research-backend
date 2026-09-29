"""Everyone already waiting gets in when the owner turns Allow all on (2026-09-29).

⛔⛔ WHAT THIS CODE DECIDES. Until now, people who asked for a computer BEFORE its
owner ticked Allow all stayed waiting — only somebody who asked AFTER joined at
once. The owner's decisions (2026-09-29): turning Allow all on lets everyone
already waiting in too, oldest first up to 25 people, through ONE web-app route
called with the OWNER'S own sign-in —

    POST /api/devices/access-request/admit-waiting   {"deviceId": "<id>"}
    200 {"ok": true, "allowAll", "admitted", "stillWaiting", "full"}; anything
    else means "could not confirm the waiting people were let in", and NEVER
    that Allow all failed.

On the agent that means:
  bridge  `/device/visibility` asks the route after a CONFIRMED Allow-all ON
          write, and when "allow all yes" meets a computer that already has it on
          (the retry) — never on OFF, private, a plain public, or a write that was
          refused, unconfirmed or revoked. Its answer rides the reply as `waiting`.
  chat    the lines under "✓ … now lets anyone join at once" / "already lets…";
          the switch-on question says anyone already waiting joins too — with the
          count when one look at the owner's requests can give it, looked up in
          `do` and never in the router, which stays network-free.
  term    the same lines under `agent device allow-all <id> yes`.

Every test drives the real handler over HTTP, or the real command with the bridge
stubbed at its HTTP helper — nothing here reads the source to decide what the code
does. The mutants are in .mutants/admit_waiting_0929_mutants.py.
"""

from __future__ import annotations

import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from facade import bridge, cli
from facade.firestore_rest import FirestoreError
from facade.session import RevokedError

# The REAL helper, taken before conftest's autouse stub replaces it for every test
# (the pattern test_allow_all_bridge_0926 uses).
_REAL_FE_API_POST = bridge._fe_api_post

_SR_PATH = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_allow_all_admit_waiting_0929", _SR_PATH)

ADMIT = "/api/devices/access-request/admit-waiting"
# What the route answers when it let three people in and nobody is left.
THREE_IN = (200, {"ok": True, "allowAll": True, "admitted": 3, "stillWaiting": 0,
                  "full": False})
UNCONFIRMED = {"unconfirmed": True}


# ══ the bridge ═══════════════════════════════════════════════════════════════

class FakeFS:
    """Every device write, in order, on the same list the route calls land on — so
    a test can see the sweep came AFTER the write it depends on."""
    devices: list[dict] = []
    events: list[tuple] = []
    raise_on_allow: dict = {}     # the allowAll VALUE whose write raises → exception
    raise_vis: Exception | None = None

    def __init__(self, _token_provider):
        pass

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]

    def set_device_visibility(self, device_id, value):
        if FakeFS.raise_vis is not None:
            raise FakeFS.raise_vis
        FakeFS.events.append(("visibility", device_id, value))

    def set_device_allow_all(self, device_id, value, *, publish=False):
        if value in FakeFS.raise_on_allow:
            raise FakeFS.raise_on_allow[value]
        FakeFS.events.append(("allowAll", device_id, value, publish))


OWNED = {"id": "dev-a1", "name": "Studio PC", "ownerUid": "u1",
         "pairConfirmedAt": True, "lastHeartbeat": 0}
SHARED = {"id": "dev-b2", "name": "Their Mac", "ownerUid": "u9",
          "pairConfirmedAt": True, "lastHeartbeat": 0, "visibility": "public",
          "allowAll": True}


@pytest.fixture()
def live(monkeypatch):
    FakeFS.devices = [dict(OWNED), dict(SHARED)]
    FakeFS.events = []
    FakeFS.raise_on_allow = {}
    FakeFS.raise_vis = None
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: None)
    box = {"reply": THREE_IN, "calls": []}

    def _post(_sess, path, payload, **kw):
        box["calls"].append((path, payload, kw))
        FakeFS.events.append(("post", path))
        return box["reply"]
    monkeypatch.setattr(bridge, "_fe_api_post", _post)
    state = bridge.BridgeState()
    sess = SimpleNamespace(uid="u1", email="e@x.y", id_token=lambda force=False: "tok")
    state.set_session(sess)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
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


def _admits(live):
    return [(path, payload) for path, payload, _kw in live.box["calls"] if path == ADMIT]


def _writes():
    return [e for e in FakeFS.events if e[0] != "post"]


# ── when the owner's yes lands, everyone waiting is asked in — once ────────────

_ON_WRITES = [
    # (stored fields, request, the writes that must land BEFORE the sweep)
    ({"visibility": "public"}, {"allowAll": True},
     [("allowAll", "dev-a1", True, True)]),
    ({"visibility": "private"}, {"visibility": "public", "allowAll": True},
     [("allowAll", "dev-a1", True, True)]),
    # a private computer with an old tick: the clear goes first, alone (K1)
    ({"visibility": "private", "allowAll": True}, {"allowAll": True},
     [("allowAll", "dev-a1", False, False), ("allowAll", "dev-a1", True, True)]),
]


@pytest.mark.parametrize("fields, body, writes", _ON_WRITES,
                         ids=["public", "private", "private-old-tick"])
def test_allow_all_on_lets_everyone_already_waiting_in(live, fields, body, writes):
    """⛔⛔ THE FEATURE. At 08fba3a nobody who asked before the tick was ever let
    in — the bridge wrote the tick and said nothing about them. Now the route is
    asked EXACTLY once, with the owner's sign-in and this computer's id, and only
    AFTER every write the switch needed has landed."""
    _owned(**fields)
    r = _vis(live, **body)
    assert r.status_code == 200, r.text
    assert _admits(live) == [(ADMIT, {"deviceId": "dev-a1"})]
    assert FakeFS.events == writes + [("post", ADMIT)]
    got = r.json()
    assert got["changed"] is True and got["allowAll"] is True
    assert got["waiting"] == {"admitted": 3, "stillWaiting": 0, "full": False}


@pytest.mark.parametrize("body", [{"allowAll": True},
                                  {"visibility": "public", "allowAll": True}])
def test_allow_all_yes_on_a_computer_already_on_is_the_retry(live, body):
    """⛔⛔ OWNER DECISION 4 — saying "allow all yes" again runs the sweep again.
    It is how anyone left waiting by a lost answer gets in, and how a computer
    ticked before this shipped gets its waiting people in from chat. Nothing is
    written: the setting already holds."""
    _owned(visibility="public", allowAll=True)
    r = _vis(live, **body)
    assert r.status_code == 200, r.text
    assert _writes() == []
    assert _admits(live) == [(ADMIT, {"deviceId": "dev-a1"})]
    got = r.json()
    assert got["changed"] is False and got["allowAll"] is True
    assert got["waiting"] == {"admitted": 3, "stillWaiting": 0, "full": False}


# ── nothing else lets anybody in ────────────────────────────────────────────────

_NEVER = [
    # (id, stored fields, request)
    ("plain-public-on-an-open-computer", {"visibility": "public", "allowAll": True},
     {"visibility": "public"}),
    ("off", {"visibility": "public", "allowAll": True}, {"allowAll": False}),
    ("off-with-public", {"visibility": "public", "allowAll": True},
     {"visibility": "public", "allowAll": False}),
    ("off-already-off", {"visibility": "public"}, {"allowAll": False}),
    ("private", {"visibility": "public", "allowAll": True}, {"visibility": "private"}),
    ("plain-public-from-private", {"visibility": "private"}, {"visibility": "public"}),
    ("plain-public-old-tick", {"visibility": "private", "allowAll": True},
     {"visibility": "public"}),
    ("off-on-private-old-tick", {"visibility": "private", "allowAll": True},
     {"allowAll": False}),
    ("already-private-old-tick", {"visibility": "private", "allowAll": True},
     {"visibility": "private"}),
]


@pytest.mark.parametrize("fields, body", [c[1:] for c in _NEVER],
                         ids=[c[0] for c in _NEVER])
def test_nothing_but_allow_all_yes_asks_anyone_in(live, fields, body):
    """⛔⛔ ONLY THE OWNER'S YES TO ALLOW ALL. Going private, switching it off, and a
    plain "make it public" — even on a computer that already lets anyone join —
    are not a yes to letting the waiting people in, and must never become one."""
    _owned(**fields)
    r = _vis(live, **body)
    assert r.status_code == 200, r.text
    assert _admits(live) == []
    assert "waiting" not in r.json()


_NOT_LANDED = [
    # (id, stored fields, what the write raises, the reply's status)
    ("refused", {"visibility": "public"},
     {True: FirestoreError("denied", status=403)}, 403),
    ("unconfirmed", {"visibility": "public"},
     {True: FirestoreError("boom", status=503)}, 502),
    ("lost-reply", {"visibility": "public"},
     {True: requests.ReadTimeout("slow")}, 502),
    ("revoked", {"visibility": "public"}, {True: RevokedError("gone")}, 401),
    ("cleared-then-refused", {"visibility": "private", "allowAll": True},
     {True: FirestoreError("denied", status=403)}, 403),
    ("cleared-then-unconfirmed", {"visibility": "private", "allowAll": True},
     {True: FirestoreError("boom", status=503)}, 502),
]


@pytest.mark.parametrize("fields, raises, status", [c[1:] for c in _NOT_LANDED],
                         ids=[c[0] for c in _NOT_LANDED])
def test_a_yes_that_did_not_land_lets_nobody_in(live, fields, raises, status):
    """⛔⛔ AFTER A CONFIRMED WRITE, NEVER BEFORE. A refused, unconfirmed or revoked
    switch is reported exactly as before, and nobody is asked in on its back."""
    _owned(**fields)
    FakeFS.raise_on_allow = raises
    r = _vis(live, allowAll=True)
    assert r.status_code == status, r.text
    assert _admits(live) == []
    assert "waiting" not in r.json()


def test_a_sharer_saying_yes_lets_nobody_in(live):
    """The route would refuse a caller who is not the owner; the bridge never asks."""
    r = _vis(live, deviceId="dev-b2", allowAll=True)
    assert r.status_code == 403 and r.json()["reason"] == "not_owner"
    assert _admits(live) == []


# ── whatever the route answers, Allow all is on ─────────────────────────────────

_ROUTE_FAILS = [
    ("no-answer", (0, {"error": "could not reach http://127.0.0.1:9 (ReadTimeout)"})),
    ("signed-out", (0, {"reason": "revoked", "error": "session revoked"})),
    ("not-deployed-or-not-owner", (404, {"error": "device_not_found"})),
    ("rate-limited", (429, {"error": "rate_limited", "retryAfterMs": 60000})),
    ("server-error", (500, {})),
    ("transaction-failed", (503, {"error": "internal_error"})),
]


@pytest.mark.parametrize("already_on", [False, True], ids=["switched-on", "already-on"])
@pytest.mark.parametrize("reply", [c[1] for c in _ROUTE_FAILS],
                         ids=[c[0] for c in _ROUTE_FAILS])
def test_a_route_that_failed_never_fails_allow_all(live, reply, already_on):
    """⛔⛔ THE TICK IS SAVED BEFORE THE ROUTE IS ASKED. A 0, 404, 429 or 5xx from
    it says only that the people waiting could not be confirmed let in — the
    reply is still a 200 saying Allow all is on."""
    _owned(visibility="public", allowAll=already_on)
    live.box["reply"] = reply
    r = _vis(live, allowAll=True)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["ok"] is True and got["allowAll"] is True
    assert got["visibility"] == "public"
    assert got["changed"] is (not already_on)
    assert got["waiting"] == UNCONFIRMED


_NOT_COUNTS = [
    ("no-counts", (200, {"ok": True})),
    ("string-count", (200, {"ok": True, "admitted": "3", "stillWaiting": 0})),
    ("bool-count", (200, {"ok": True, "admitted": True, "stillWaiting": 0})),
    ("negative-count", (200, {"ok": True, "admitted": -1, "stillWaiting": 0})),
    ("no-still-waiting", (200, {"ok": True, "admitted": 2, "stillWaiting": None})),
    ("bool-still-waiting", (200, {"ok": True, "admitted": 2, "stillWaiting": False})),
    ("negative-still-waiting", (200, {"ok": True, "admitted": 2, "stillWaiting": -4})),
    ("accepted-not-ok", (202, {"ok": True, "admitted": 2, "stillWaiting": 0})),
    ("error-with-counts", (500, {"ok": True, "admitted": 2, "stillWaiting": 0})),
]


@pytest.mark.parametrize("reply", [c[1] for c in _NOT_COUNTS],
                         ids=[c[0] for c in _NOT_COUNTS])
def test_only_a_200_with_real_counts_is_a_confirmation(live, reply):
    """⛔ ANYTHING BUT 200 IS "COULD NOT CONFIRM", per the contract — and a 200 whose
    counts are not counts is the same unknown, never a zero: "nobody was waiting"
    over people left waiting would send the owner nowhere."""
    _owned(visibility="public")
    live.box["reply"] = reply
    r = _vis(live, allowAll=True)
    assert r.status_code == 200, r.text
    assert r.json()["waiting"] == UNCONFIRMED


@pytest.mark.parametrize("reply, want", [
    ((200, {"ok": True, "allowAll": True, "admitted": 25, "stillWaiting": 4,
            "full": True}),
     {"admitted": 25, "stillWaiting": 4, "full": True}),
    ((200, {"ok": True, "allowAll": True, "admitted": 0, "stillWaiting": 0,
            "full": False}),
     {"admitted": 0, "stillWaiting": 0, "full": False}),
    # the route's no-op (Allow all not in effect on its live read): nothing to say
    ((200, {"ok": True, "allowAll": False, "admitted": 0, "stillWaiting": 0,
            "full": False}),
     {"admitted": 0, "stillWaiting": 0, "full": False}),
    # `full` is strict, as every reader of a server flag here is
    ((200, {"ok": True, "allowAll": True, "admitted": 1, "stillWaiting": 2,
            "full": "true"}),
     {"admitted": 1, "stillWaiting": 2, "full": False}),
], ids=["full", "nobody-waiting", "route-no-op", "full-not-a-bool"])
def test_the_counts_ride_the_reply(live, reply, want):
    _owned(visibility="public")
    live.box["reply"] = reply
    assert _vis(live, allowAll=True).json()["waiting"] == want


def test_the_real_helper_gets_the_long_wait_and_a_timeout_is_unconfirmed(
        live, monkeypatch):
    """Through the REAL `_fe_api_post` and the real `requests`: the route is asked
    with the owner's Bearer token and its own longer wait (it grants up to 25 people
    and sends their notices), and a reply that never came back is "could not
    confirm" — the web app may well have let them in."""
    monkeypatch.setattr(bridge, "_fe_api_post", _REAL_FE_API_POST)
    real_post = requests.post
    seen: list = []

    def _slow(url, *a, **kw):
        if str(url).startswith(bridge.config.FE_BASE):
            seen.append((url, kw.get("json"), kw.get("headers"), kw.get("timeout")))
            raise requests.ReadTimeout("slow")
        return real_post(url, *a, **kw)
    monkeypatch.setattr(requests, "post", _slow)
    _owned(visibility="public")
    r = real_post(live.base + "/device/visibility",
                  json={"deviceId": "dev-a1", "allowAll": True})
    assert r.status_code == 200, r.text
    assert r.json()["allowAll"] is True and r.json()["waiting"] == UNCONFIRMED
    assert seen == [(bridge.config.FE_BASE + ADMIT, {"deviceId": "dev-a1"},
                     {"Authorization": "Bearer tok"}, bridge._FE_ADMIT_TIMEOUT)]
    assert bridge._FE_ADMIT_TIMEOUT > bridge._FE_JSON_TIMEOUT


# ══ the chat (sr.py) ═════════════════════════════════════════════════════════

CHAT_OWNED = {"id": "dev-a1", "name": "Studio PC", "owned": True, "online": True,
              "visibility": "public", "allowAll": False}
CHAT_OWNED_2 = {"id": "dev-c3", "name": "Office PC", "owned": True, "online": True,
                "visibility": "public", "allowAll": False}
CHAT_SHARED = {"id": "dev-b2", "name": "Their Mac", "owned": False, "online": True,
               "visibility": "public", "allowAll": True}


def _ns(**kw):
    kw.setdefault("json", False)
    return SimpleNamespace(**kw)


@pytest.fixture()
def chat(monkeypatch, capsys):
    calls: list = []
    box: dict = {"get": {}, "post": {}}

    def _get(path, timeout=None):
        calls.append(("GET", path, None, timeout))
        return box["get"].get(path, (200, {}))

    def _post(path, body=None, timeout=None):
        calls.append(("POST", path, body, timeout))
        return box["post"].get(path, (200, {}))

    monkeypatch.setattr(sr, "_get", _get)
    monkeypatch.setattr(sr, "_post", _post)
    monkeypatch.setattr(sr, "_origin_from_env", lambda: None)
    monkeypatch.setattr(sr, "_prepare_stream_arm", lambda: ([], {}, 0))
    box["get"]["/devices"] = (200, {"devices": [dict(CHAT_OWNED), dict(CHAT_SHARED)]})
    return SimpleNamespace(box=box, calls=calls,
                           out=lambda: capsys.readouterr().out)


def _switched(waiting=None, changed=True):
    body = {"ok": True, "changed": changed, "visibility": "public", "allowAll": True,
            "deviceName": "Studio PC", "publicLabel": "Studio PC"}
    if waiting is not None:
        body["waiting"] = waiting
    return (200, body)


ON_HEAD = "✓ “Studio PC” now lets anyone join at once."
ALREADY_HEAD = "✓ “Studio PC” already lets anyone join at once."

_CHAT_LINES = [
    ("three-in", {"admitted": 3, "stillWaiting": 0, "full": False},
     ["3 people who were already waiting joined too."]),
    ("one-in", {"admitted": 1, "stillWaiting": 0, "full": False},
     ["1 person who was already waiting joined too."]),
    ("full", {"admitted": 25, "stillWaiting": 4, "full": True},
     ["25 people who were already waiting joined too.",
      "4 people are still waiting — it’s full (25 people), so they stay in your "
      "requests."]),
    ("full-one-left", {"admitted": 0, "stillWaiting": 1, "full": True},
     ["1 person is still waiting — it’s full (25 people), so they stay in your "
      "requests."]),
    ("left-to-decide", {"admitted": 2, "stillWaiting": 2, "full": False},
     ["2 people who were already waiting joined too.",
      "2 people are still waiting for you to decide — ask me who’s waiting."]),
    ("one-left-to-decide", {"admitted": 0, "stillWaiting": 1, "full": False},
     ["1 person is still waiting for you to decide — ask me who’s waiting."]),
    ("unconfirmed", {"unconfirmed": True},
     ["Allow all is on, but I couldn’t confirm that anyone already waiting was let "
      "in — say “allow all yes” again to retry."]),
]


@pytest.mark.parametrize("waiting, want", [c[1:] for c in _CHAT_LINES],
                         ids=[c[0] for c in _CHAT_LINES])
def test_the_chat_says_who_joined_right_under_the_switch(chat, waiting, want):
    """⛔⛔ THE OWNER'S ANSWER TO "WHAT DID THAT DO?". The lines sit directly under
    "now lets anyone join at once", above what Allow all means — and an unconfirmed
    sweep says Allow all IS on and names the retry, never that it failed."""
    chat.box["post"]["/device/visibility"] = _switched(waiting)
    assert sr.cmd_device_allow_all(_ns(value="yes", device="")) == 0
    lines = chat.out().splitlines()
    assert lines[0] == ON_HEAD
    assert lines[1:1 + len(want)] == want
    assert lines[1 + len(want)].startswith("Anyone signed in can join “Studio PC”")


@pytest.mark.parametrize("waiting", [None, {"admitted": 0, "stillWaiting": 0,
                                            "full": False}],
                         ids=["older-bridge", "nobody-waiting"])
def test_nobody_waiting_adds_nothing(chat, waiting):
    chat.box["post"]["/device/visibility"] = _switched(waiting)
    sr.cmd_device_allow_all(_ns(value="yes", device=""))
    lines = chat.out().splitlines()
    assert lines[0] == ON_HEAD
    assert lines[1].startswith("Anyone signed in can join “Studio PC”")
    assert lines[2:] == ["They see it as “Studio PC”."]


def test_already_on_says_who_joined_instead_of_nothing_to_change(chat):
    """The retry on a computer that already lets anyone join: "Nothing to change"
    over two people who just got in would be false."""
    chat.box["post"]["/device/visibility"] = _switched(
        {"admitted": 2, "stillWaiting": 0, "full": False}, changed=False)
    sr.cmd_device_allow_all(_ns(value="yes", device=""))
    lines = chat.out().splitlines()
    assert lines[:2] == [ALREADY_HEAD, "2 people who were already waiting joined too."]


def test_already_on_with_nobody_waiting_still_says_nothing_to_change(chat):
    chat.box["post"]["/device/visibility"] = _switched(
        {"admitted": 0, "stillWaiting": 0, "full": False}, changed=False)
    sr.cmd_device_allow_all(_ns(value="yes", device=""))
    assert chat.out().splitlines()[0] == ALREADY_HEAD + " Nothing to change."


@pytest.mark.parametrize("run", [
    lambda: sr.cmd_device_allow_all(_ns(value="yes", device="")),
    lambda: sr.cmd_device_visibility(_ns(value="public", device="", allow_all=True)),
], ids=["allow-all-yes", "public-allow-all"])
def test_the_chat_waits_for_the_write_and_the_sweep(chat, run):
    """⛔⛔ AT 40s A SLOW SWEEP READ AS A LOST SWITCH. The bridge now writes AND asks
    the web app, so the chat waits for the owner read, the write, the route's own
    wait and a re-minted sign-in — or it says "could not confirm that change" about
    a switch that landed."""
    chat.box["post"]["/device/visibility"] = _switched()
    run()
    waits = [c[3] for c in chat.calls if c[0] == "POST" and c[1] == "/device/visibility"]
    assert waits == [75]
    assert waits[0] >= 15 + 15 + bridge._FE_ADMIT_TIMEOUT + 10


# ── the question before the switch ──────────────────────────────────────────────

WAITING_ANY = "Anyone already waiting to use it joins too."


def _row(device_id, who="Sam"):
    return {"deviceId": device_id, "requesterUid": f"uid{who}", "requesterLabel": who,
            "deviceLabel": "x", "createdAt": 1}


def _do(text):
    ns = sr.build_parser().parse_args(["do", text])
    return ns.func(ns)


@pytest.mark.parametrize("text", ["turn on allow all", "let anyone join my mac",
                                  "allow all yes", "turn on allow all for “Studio PC”"])
def test_the_question_says_anyone_waiting_joins_too_without_a_look(monkeypatch, text):
    """⛔ THE ROUTER STAYS NETWORK-FREE: the sentence is in the question it builds
    from the words alone, and any look happens in `do`, after it."""
    def _no_network(*_a, **_kw):
        raise AssertionError("the router made a network call")
    monkeypatch.setattr(sr, "_get", _no_network)
    monkeypatch.setattr(sr, "_post", _no_network)
    argv, lines = sr._nl_resolve(text)
    assert argv is None, argv
    said = " ".join(lines or [])
    assert said.startswith("Anyone signed in can join"), said
    assert WAITING_ANY in said and said.endswith("Say yes and I’ll switch it on.")


@pytest.mark.parametrize("rows, want", [
    ([_row("dev-a1", "Sam"), _row("dev-a1", "Kim"), _row("dev-a1", "Lee"),
      _row("dev-z9", "Ann")],
     "3 people are already waiting to use it — they join too."),
    ([_row("dev-a1")], "1 person is already waiting to use it — they join too."),
], ids=["three", "one"])
def test_do_counts_the_people_waiting_on_that_computer(chat, rows, want):
    """⛔⛔ OWNER DECISION 1 — the count, when it is cheap to know. One look at the
    owner's requests, counting only the rows for the computer the question is
    about; the switch itself still waits for the yes."""
    chat.box["get"]["/devices/requests"] = (200, {"incoming": rows})
    _do("turn on allow all")
    out = chat.out()
    assert want in out and WAITING_ANY not in out
    assert out.startswith("Anyone signed in can join that computer")
    assert [c for c in chat.calls if c[0] == "POST"] == []


def test_do_counts_for_the_computer_that_was_named(chat):
    chat.box["get"]["/devices"] = (200, {"devices": [dict(CHAT_OWNED),
                                                     dict(CHAT_OWNED_2)]})
    chat.box["get"]["/devices/requests"] = (200, {"incoming": [
        _row("dev-c3", "Sam"), _row("dev-c3", "Kim"), _row("dev-a1", "Lee")]})
    _do("turn on allow all for “Office PC”")
    assert "2 people are already waiting to use it — they join too." in chat.out()


@pytest.mark.parametrize("setup", [
    # nobody waiting: nothing to count, the sentence stays true
    lambda box: box["get"].__setitem__("/devices/requests", (200, {"incoming": []})),
    # the look failed
    lambda box: box["get"].__setitem__("/devices/requests",
                                       (502, {"error": "could not reach"})),
    lambda box: box["get"].__setitem__("/devices/requests", (0, {"error": "down"})),
    # two computers and none named: the picker would ask, so there is no "it"
    lambda box: (box["get"].__setitem__("/devices", (200, {"devices": [
        dict(CHAT_OWNED), dict(CHAT_OWNED_2)]})),
        box["get"].__setitem__("/devices/requests", (200, {"incoming": [
            _row("dev-a1")]}))),
], ids=["nobody", "look-refused", "bridge-down", "no-one-computer"])
def test_do_keeps_the_uncounted_sentence_when_it_cannot_count(chat, setup):
    setup(chat.box)
    _do("turn on allow all")
    out = chat.out()
    assert WAITING_ANY in out and "already waiting to use it —" not in out


def test_no_other_question_looks_at_the_requests(chat):
    """Only the switch-on question carries the waiting sentence, so only it may
    cost a look at the owner's requests."""
    chat.box["get"]["/devices/requests"] = (200, {"incoming": [_row("dev-a1")]})
    _do("make my mac public")
    _do("stop the mars run")
    assert [c for c in chat.calls if c[1] == "/devices/requests"] == []


# ══ the terminal (cli.py) ════════════════════════════════════════════════════

@pytest.fixture()
def term(monkeypatch, capsys):
    calls: list = []
    box: dict = {"get": {}, "post": {}}
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _m: None)
    monkeypatch.setattr(cli, "_bridge_get",
                        lambda p, timeout=10.0: (calls.append(("GET", p, None, timeout)),
                                                 box["get"].get(p))[1])
    monkeypatch.setattr(cli, "_bridge_post",
                        lambda p, body=None, timeout=30.0: (
                            calls.append(("POST", p, body, timeout)),
                            box["post"].get(p))[1])
    return SimpleNamespace(box=box, calls=calls, out=lambda: capsys.readouterr().out)


def _cli(argv):
    ns = cli.build_parser().parse_args(argv)
    return ns.func(ns)


T_HEAD = "✓ Studio PC now lets anyone join at once."

_TERM_LINES = [
    ("three-in", {"admitted": 3, "stillWaiting": 0, "full": False},
     ["     3 people who were already waiting joined too."]),
    ("one-in", {"admitted": 1, "stillWaiting": 0, "full": False},
     ["     1 person who was already waiting joined too."]),
    ("full", {"admitted": 25, "stillWaiting": 1, "full": True},
     ["     25 people who were already waiting joined too.",
      "     1 person is still waiting — it's full (25 people), so they stay in "
      "your requests."]),
    ("left-to-decide", {"admitted": 0, "stillWaiting": 2, "full": False},
     ["     2 people are still waiting for you to decide — see "
      "`agent device requests`."]),
    ("unconfirmed", {"unconfirmed": True},
     ["     Allow all is on, but it couldn't be confirmed that anyone already "
      "waiting was let in —",
      "     run `agent device allow-all dev-a1 yes` again to retry."]),
]


@pytest.mark.parametrize("waiting, want", [c[1:] for c in _TERM_LINES],
                         ids=[c[0] for c in _TERM_LINES])
def test_the_terminal_says_who_joined_right_under_the_switch(term, waiting, want):
    term.box["post"]["/device/visibility"] = _switched(waiting)
    assert _cli(["device", "allow-all", "dev-a1", "yes"]) == 0
    lines = term.out().splitlines()
    assert lines[0].replace(cli._OK, "✓") == T_HEAD
    assert lines[1:1 + len(want)] == want
    assert lines[1 + len(want)].startswith("     Anyone signed in can join it")


def test_the_terminal_says_nothing_extra_when_nobody_was_waiting(term):
    term.box["post"]["/device/visibility"] = _switched(
        {"admitted": 0, "stillWaiting": 0, "full": False})
    _cli(["device", "allow-all", "dev-a1", "yes"])
    lines = term.out().splitlines()
    assert lines[1].startswith("     Anyone signed in can join it")
    assert not any("waiting" in ln for ln in lines)


def test_the_terminal_already_on_says_who_joined_instead_of_nothing_to_change(term):
    term.box["post"]["/device/visibility"] = _switched(
        {"admitted": 2, "stillWaiting": 0, "full": False}, changed=False)
    _cli(["device", "allow-all", "dev-a1", "yes"])
    lines = term.out().splitlines()
    assert lines[0].replace(cli._OK, "✓") == "✓ Studio PC already lets anyone join at once."
    assert lines[1] == "     2 people who were already waiting joined too."


@pytest.mark.parametrize("argv", [["device", "allow-all", "dev-a1", "yes"],
                                  ["device", "visibility", "dev-a1", "public",
                                   "--allow-all"]],
                         ids=["allow-all-yes", "public-allow-all"])
def test_the_terminal_waits_for_the_write_and_the_sweep(term, argv):
    term.box["post"]["/device/visibility"] = _switched()
    _cli(argv)
    waits = [c[3] for c in term.calls if c[0] == "POST" and c[1] == "/device/visibility"]
    assert waits == [75.0]


# ══ SKILL.md ═════════════════════════════════════════════════════════════════

_SKILL = Path(__file__).resolve().parents[1] / "facade" / "skill" / "SKILL.md"


def test_the_confirm_rule_says_a_yes_lets_the_waiting_people_in_and_names_the_retry():
    """⛔ THE ASSISTANT IS THE CONSENT STEP, so the rule it confirms by has to say
    what the yes now does — and what to do when the reply could not confirm it:
    the same yes again, confirmed again (owner decision 4). Read inside the
    paragraph that lists the confirms, not anywhere in the file."""
    text = _SKILL.read_bytes().decode("utf-8").replace("\r\n", "\n")
    paras = [" ".join(p.split()) for p in text.split("\n\n")]
    hits = [p for p in paras
            if "`device-allow-all yes` lets ANY of them on with no step between" in p]
    assert len(hits) == 1, len(hits)
    para = hits[0]
    assert "also lets in everyone already waiting on that computer" in para
    assert "up to 25 people in all" in para
    assert ("when the reply could not confirm them the retry is the same "
            "`device-allow-all yes`, confirmed again") in para
