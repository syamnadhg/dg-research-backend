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

⭐ AND WHAT THE REVIEW OF 2026-09-29 ADDED. People left out when the computer is
NOT full are people the owner removed — the web app says "people you removed stay
out", and so do both clients now, with no pointer to a phrase the router does not
read. The route's `allowAll` rides `waiting`: not in effect says nobody was let in,
never "Nothing to change"; a retry that found nobody says "Nobody is waiting now.".
`device requests` names the yes that lets the people waiting on an Allow-all
computer in. The admit call runs on what is left of a deadline counted from the
start of the switch, so the bridge answers before either client gives up; its 401
re-mint is executed here. SKILL.md's turn-on row gets its question from `do`.

Every test drives the real handler over HTTP, or the real command with the bridge
stubbed at its HTTP helper — nothing here reads the source to decide what the code
does. The mutants are in .mutants/admit_waiting_0929_mutants.py.
"""

from __future__ import annotations

import importlib.util
import json
import re
import threading
import time
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
# …and what rides the reply for it: the route's `allowAll` is carried (review).
THREE_WAITING = {"admitted": 3, "stillWaiting": 0, "full": False, "allowAll": True}
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
    assert got["waiting"] == THREE_WAITING


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
    assert got["waiting"] == THREE_WAITING


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
     {"admitted": 25, "stillWaiting": 4, "full": True, "allowAll": True}),
    ((200, {"ok": True, "allowAll": True, "admitted": 0, "stillWaiting": 0,
            "full": False}),
     {"admitted": 0, "stillWaiting": 0, "full": False, "allowAll": True}),
    # ⛔ the route's no-op (Allow all not in effect on its live read) is CARRIED
    # (review, 2026-09-29): dropped, it read as "nobody was waiting"
    ((200, {"ok": True, "allowAll": False, "admitted": 0, "stillWaiting": 0,
            "full": False}),
     {"admitted": 0, "stillWaiting": 0, "full": False, "allowAll": False}),
    # `full` and `allowAll` are strict, as every reader of a server flag here is
    ((200, {"ok": True, "allowAll": True, "admitted": 1, "stillWaiting": 2,
            "full": "true"}),
     {"admitted": 1, "stillWaiting": 2, "full": False, "allowAll": True}),
    ((200, {"ok": True, "allowAll": "true", "admitted": 0, "stillWaiting": 0,
            "full": False}),
     {"admitted": 0, "stillWaiting": 0, "full": False, "allowAll": False}),
    ((200, {"ok": True, "admitted": 0, "stillWaiting": 0, "full": False}),
     {"admitted": 0, "stillWaiting": 0, "full": False, "allowAll": False}),
], ids=["full", "nobody-waiting", "route-no-op", "full-not-a-bool",
        "allow-all-not-a-bool", "allow-all-missing"])
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


def _fe_reply(status: int, body: dict) -> requests.Response:
    """A real `requests.Response`, so the real `_fe_json_body` decodes it."""
    r = requests.models.Response()
    r.status_code = status
    r._content = json.dumps(body).encode("utf-8")
    r.headers["Content-Type"] = "application/json"
    return r


@pytest.fixture()
def remint(monkeypatch):
    """The REAL `_fe_api_post` against a web app that refuses the first token it
    is shown (401) and answers the next — the stale cached ID token the helper's
    docstring measures at up to fifty-five minutes past a dead refresh token."""
    monkeypatch.setattr(bridge, "_fe_api_post", _REAL_FE_API_POST)
    real_post = requests.post
    box = {"sent": [], "minted": []}

    def _post(url, *a, **kw):
        # ⛔ `/api/` too: the conftest FE_BASE is a prefix of any 127.0.0.1:9xxx
        # port the bridge under test may be listening on.
        if not str(url).startswith(bridge.config.FE_BASE + "/api/"):
            return real_post(url, *a, **kw)
        box["sent"].append((url, kw.get("json"), kw["headers"]["Authorization"]))
        if len(box["sent"]) == 1:
            return _fe_reply(401, {"error": "unauthorized"})
        return _fe_reply(*THREE_IN)
    monkeypatch.setattr(requests, "post", _post)

    def _id_token(force=False):
        box["minted"].append(force)
        return "fresh" if force else "stale"
    box["id_token"] = _id_token
    box["real_post"] = real_post
    return box


def test_a_refused_sign_in_is_reminted_once_and_the_sweep_is_confirmed(live, remint):
    """⛔⛔ THE 401 RETRY, EXECUTED (review, 2026-09-29). No test reached it: the
    only one on the real helper raised a timeout, and a `retry_401=False` mutant
    survived. A cached token the web app's `checkRevoked` refuses is re-minted
    with force and sent once more — and that second answer is the one relayed."""
    live.sess.id_token = remint["id_token"]
    _owned(visibility="public")
    r = remint["real_post"](live.base + "/device/visibility",
                            json={"deviceId": "dev-a1", "allowAll": True})
    assert r.status_code == 200, r.text
    assert r.json()["waiting"] == THREE_WAITING
    url = bridge.config.FE_BASE + ADMIT
    assert remint["sent"] == [(url, {"deviceId": "dev-a1"}, "Bearer stale"),
                              (url, {"deviceId": "dev-a1"}, "Bearer fresh")]
    assert remint["minted"] == [False, True]


def test_without_room_for_a_second_leg_a_refused_sign_in_is_unconfirmed(remint):
    """⛔ …BUT ONLY WHILE TWO FULL LEGS STILL FIT THE DEADLINE. Late in the switch
    the 401 is "could not confirm" at once — the same yes again is the retry, and
    it starts with a whole budget."""
    sess = SimpleNamespace(uid="u1", id_token=remint["id_token"])
    got = bridge._admit_waiting(sess, "dev-a1", time.monotonic() - 10)
    assert got == UNCONFIRMED
    assert [auth for _u, _j, auth in remint["sent"]] == ["Bearer stale"]
    assert remint["minted"] == [False]


# ── the admit call has a deadline, counted from the start of the switch ─────────

@pytest.fixture()
def admit_kw(monkeypatch):
    seen: list = []

    def _post(_sess, path, payload, **kw):
        seen.append(kw)
        return THREE_IN
    monkeypatch.setattr(bridge, "_fe_api_post", _post)
    return seen


_SESS = SimpleNamespace(uid="u1", id_token=lambda force=False: "tok")


@pytest.mark.parametrize("spent, wait, retry", [
    # a quick owner read and write: the route's whole wait, and room for the retry
    (0, 30, True),
    # fifty-five left: one full leg fits, a second would not
    (10, 30, False),
    # fifteen left: the wait is what is left, never the whole thirty
    (50, 15, False),
], ids=["fresh", "one-leg-left", "short"])
def test_the_route_is_asked_on_what_is_left_of_the_budget(admit_kw, spent, wait, retry):
    """⛔⛔ THE BRIDGE ANSWERS BEFORE THE CLIENTS GIVE UP (review, 2026-09-29).
    The owner read is two queries (fifteen each), the write fifteen, a clear-first
    fifteen more — with the route's thirty and a re-mint on top the handler could
    pass the clients' seventy-five, and a switch that landed read "no response".
    So the route gets what is left of the budget, and the 401 leg only when both
    legs fit."""
    got = bridge._admit_waiting(_SESS, "dev-a1", time.monotonic() - spent)
    assert got == THREE_WAITING
    [kw] = admit_kw
    assert kw["retry_401"] is retry
    assert wait - 2 <= kw["timeout"] <= wait


def test_with_too_little_left_the_route_is_not_asked(admit_kw):
    """Under the floor there is no wait worth giving a sweep of 25 people: the
    answer is "could not confirm" and the retry starts with a whole budget."""
    got = bridge._admit_waiting(_SESS, "dev-a1",
                                time.monotonic() - bridge._ADMIT_BUDGET + 2)
    assert got == UNCONFIRMED
    assert admit_kw == []


def test_the_budget_fits_inside_both_clients_wait():
    """Ten seconds under the clients' seventy-five — the reply, and a re-mint."""
    assert bridge._ADMIT_BUDGET + 10 <= 75
    assert bridge._ADMIT_BUDGET >= 2 * bridge._FE_ADMIT_TIMEOUT
    assert 0 < bridge._ADMIT_MIN_WAIT < bridge._FE_ADMIT_TIMEOUT


@pytest.mark.parametrize("fields", [{"visibility": "public"},
                                    {"visibility": "public", "allowAll": True}],
                         ids=["switched-on", "already-on"])
def test_the_deadline_counts_from_the_start_of_the_switch(live, monkeypatch, fields):
    """⛔ THE CLOCK STARTS WHEN THE REQUEST DOES, not when the route is asked: the
    owner read (slow here) is part of what the client is waiting through. With a
    budget a hair over the route's thirty, a read that took longer than that hair
    must leave the route less than thirty."""
    _owned(**fields)
    monkeypatch.setattr(bridge, "_ADMIT_BUDGET", bridge._FE_ADMIT_TIMEOUT + 0.3)

    def _slow_read(self, uid):
        time.sleep(0.6)
        return [dict(d) for d in FakeFS.devices]
    monkeypatch.setattr(FakeFS, "list_devices", _slow_read)
    r = _vis(live, allowAll=True)
    assert r.status_code == 200, r.text
    [kw] = [kw for path, _p, kw in live.box["calls"] if path == ADMIT]
    assert kw["timeout"] < bridge._FE_ADMIT_TIMEOUT - 0.2
    assert kw["retry_401"] is False


@pytest.mark.parametrize("fields", [{"visibility": "public"},
                                    {"visibility": "public", "allowAll": True}],
                         ids=["switched-on", "already-on"])
def test_a_switch_past_its_budget_still_answers_allow_all_on(live, monkeypatch, fields):
    """Nothing left: the route is not asked, and the reply is still a 200 saying
    Allow all is on, with the people waiting unconfirmed — the retry line."""
    _owned(**fields)
    monkeypatch.setattr(bridge, "_ADMIT_BUDGET", 0)
    r = _vis(live, allowAll=True)
    assert r.status_code == 200, r.text
    assert r.json()["allowAll"] is True and r.json()["waiting"] == UNCONFIRMED
    assert _admits(live) == []


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


def _w(admitted=0, still=0, full=False, allow_all=True):
    """A confirmed `waiting`, as the bridge relays the route's 200."""
    return {"admitted": admitted, "stillWaiting": still, "full": full,
            "allowAll": allow_all}


NOT_IN_EFFECT = ("Nobody who was waiting was let in — Allow all isn’t in effect for "
                 "it right now.")

_CHAT_LINES = [
    ("three-in", _w(3), ["3 people who were already waiting joined too."]),
    ("one-in", _w(1), ["1 person who was already waiting joined too."]),
    ("full", _w(25, 4, True),
     ["25 people who were already waiting joined too.",
      "4 people are still waiting — it’s full (25 people), so they stay in your "
      "requests."]),
    ("full-one-left", _w(0, 1, True),
     ["1 person is still waiting — it’s full (25 people), so they stay in your "
      "requests."]),
    # ⛔ NOT FULL, SO THESE ARE PEOPLE THE OWNER REMOVED (review, 2026-09-29) — the
    # planner leaves nobody else out, the decide route refuses to approve them,
    # and the web app says it in these words. "For you to decide — ask me who’s
    # waiting" sent the owner to approve people they cannot, by a phrase the
    # router does not read.
    ("removed-stay-out", _w(2, 2),
     ["2 people who were already waiting joined too.",
      "2 people are still waiting — people you removed stay out."]),
    ("one-removed-stays-out", _w(0, 1),
     ["1 person is still waiting — people you removed stay out."]),
    ("unconfirmed", {"unconfirmed": True},
     ["Allow all is on, but I couldn’t confirm that anyone already waiting was let "
      "in — say “allow all yes” again to retry."]),
    # ⛔ THE ROUTE FOUND ALLOW ALL NOT IN EFFECT (review, 2026-09-29) — a computer
    # part-way through a Reset, say. Nobody was let in, and the owner is told.
    ("not-in-effect", _w(allow_all=False), [NOT_IN_EFFECT]),
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


@pytest.mark.parametrize("waiting", [None, _w()],
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
    chat.box["post"]["/device/visibility"] = _switched(_w(2), changed=False)
    sr.cmd_device_allow_all(_ns(value="yes", device=""))
    lines = chat.out().splitlines()
    assert lines[:2] == [ALREADY_HEAD, "2 people who were already waiting joined too."]


def test_a_retry_that_found_nobody_says_nobody_is_waiting_now(chat):
    """⭐ THE ROUTE ANSWERED 0/0, SO THAT IS WHAT THE OWNER HEARS (review,
    2026-09-29) — the web app's button says the same. "Nothing to change" says
    nothing about the people the owner said yes again to let in."""
    chat.box["post"]["/device/visibility"] = _switched(_w(), changed=False)
    sr.cmd_device_allow_all(_ns(value="yes", device=""))
    lines = chat.out().splitlines()
    assert lines[0] == ALREADY_HEAD + " Nobody is waiting now."
    assert lines[1].startswith("Anyone signed in can join “Studio PC”")


def test_an_older_bridge_that_found_it_on_still_says_nothing_to_change(chat):
    """No `waiting` at all: nobody was asked, so nothing is claimed about them."""
    chat.box["post"]["/device/visibility"] = _switched(changed=False)
    sr.cmd_device_allow_all(_ns(value="yes", device=""))
    assert chat.out().splitlines()[0] == ALREADY_HEAD + " Nothing to change."


@pytest.mark.parametrize("changed, head", [(True, ON_HEAD), (False, ALREADY_HEAD)],
                         ids=["switched-on", "already-on"])
def test_allow_all_not_in_effect_on_the_web_is_said_never_nothing_to_change(
        chat, changed, head):
    """⛔⛔ THE WEB APP'S LIVE READ SAID NO (review, 2026-09-29). The bridge reads
    public + the tick; the route also needs the computer fully paired, so a
    computer part-way through a Reset lets nobody in. "Already lets anyone join
    at once. Nothing to change." was the whole reply — the owner never heard it."""
    chat.box["post"]["/device/visibility"] = _switched(_w(allow_all=False),
                                                       changed=changed)
    sr.cmd_device_allow_all(_ns(value="yes", device=""))
    out = chat.out()
    assert out.splitlines()[:2] == [head, NOT_IN_EFFECT]
    assert "Nothing to change" not in out and "Nobody is waiting now" not in out


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


# ── the requests screen names the yes that lets them in ─────────────────────────

CHAT_ON = dict(CHAT_OWNED, allowAll=True)


def _let_in(n_phrase: str) -> str:
    return (f"“Studio PC” lets anyone join at once, and {n_phrase} waiting for it — "
            f"to let them in too, say: allow all yes for “Studio PC”.")


def _requests_out(chat, devices, rows):
    chat.box["get"]["/devices"] = (200, {"devices": devices})
    chat.box["get"]["/devices/requests"] = (200, {"incoming": rows, "requests": []})
    assert sr.cmd_device_requests(_ns()) == 0
    return chat.out().splitlines()


@pytest.mark.parametrize("rows, n_phrase", [
    ([_row("dev-a1", "Sam"), _row("dev-a1", "Kim"), _row("dev-z9", "Ann")],
     "2 people are"),
    ([_row("dev-a1", "Sam")], "1 person is"),
], ids=["two", "one"])
def test_device_requests_names_the_yes_that_lets_the_people_waiting_in(
        chat, rows, n_phrase):
    """⛔⛔ THE CHAT'S "LET THEM IN (N)" (review, 2026-09-29). The web app shows the
    button on an Allow-all computer with people waiting; the chat's way is "allow
    all yes" again (owner decision 4) — and nothing told the owner so. A computer
    ticked before this shipped, or whose sweep was unconfirmed, kept its people
    waiting on the one screen that lists them."""
    lines = _requests_out(chat, [CHAT_ON, dict(CHAT_SHARED)], rows)
    assert _let_in(n_phrase) in lines
    assert not any("nobody waits here" in ln for ln in lines)


@pytest.mark.parametrize("devices, rows", [
    # approval mode: Approve is the answer, and the screen already says so
    ([dict(CHAT_OWNED)], [_row("dev-a1")]),
    # somebody else's computer is never this account's to switch
    ([dict(CHAT_SHARED)], [_row("dev-b2")]),
    # the people waiting are on another computer
    ([CHAT_ON], [_row("dev-z9")]),
], ids=["approval-mode", "not-owned", "waiting-elsewhere"])
def test_device_requests_names_it_only_for_an_owned_allow_all_computer_with_people(
        chat, devices, rows):
    lines = _requests_out(chat, devices, rows)
    assert not any("allow all yes" in ln for ln in lines)


def test_the_yes_it_names_is_the_switch_on_question_for_that_computer(chat):
    """⛔ A PHRASE THE ROUTER READS, EXECUTED — the line this replaced pointed at
    "who’s waiting", which reaches the catch-all. This one is the switch-on
    question for the named computer, counted by `do`."""
    lines = _requests_out(chat, [CHAT_ON], [_row("dev-a1")])
    [said] = [ln for ln in lines if "allow all yes" in ln]
    phrase = said.split("say: ", 1)[1].rstrip(".")
    argv, asked = sr._nl_resolve(phrase)
    assert argv is None
    assert asked == [sr._NL_CONFIRMS["device-allow-all"].format(name="“Studio PC”")]


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

T_NOT_IN_EFFECT = ("     Nobody who was waiting was let in — Allow all isn't in effect "
                   "for it right now.")

_TERM_LINES = [
    ("three-in", _w(3), ["     3 people who were already waiting joined too."]),
    ("one-in", _w(1), ["     1 person who was already waiting joined too."]),
    ("full", _w(25, 1, True),
     ["     25 people who were already waiting joined too.",
      "     1 person is still waiting — it's full (25 people), so they stay in "
      "your requests."]),
    # ⛔ not full: people the owner removed (review, 2026-09-29) — never "decide"
    ("removed-stay-out", _w(0, 2),
     ["     2 people are still waiting — people you removed stay out."]),
    ("unconfirmed", {"unconfirmed": True},
     ["     Allow all is on, but it couldn't be confirmed that anyone already "
      "waiting was let in —",
      "     run `agent device allow-all dev-a1 yes` again to retry."]),
    ("not-in-effect", _w(allow_all=False), [T_NOT_IN_EFFECT]),
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
    term.box["post"]["/device/visibility"] = _switched(_w())
    _cli(["device", "allow-all", "dev-a1", "yes"])
    lines = term.out().splitlines()
    assert lines[1].startswith("     Anyone signed in can join it")
    assert not any("waiting" in ln for ln in lines)


T_ALREADY = "✓ Studio PC already lets anyone join at once."


def test_the_terminal_already_on_says_who_joined_instead_of_nothing_to_change(term):
    term.box["post"]["/device/visibility"] = _switched(_w(2), changed=False)
    _cli(["device", "allow-all", "dev-a1", "yes"])
    lines = term.out().splitlines()
    assert lines[0].replace(cli._OK, "✓") == T_ALREADY
    assert lines[1] == "     2 people who were already waiting joined too."


@pytest.mark.parametrize("waiting, head", [
    # ⭐ the route answered 0/0: what it found, not "Nothing to change" (review)
    (_w(), T_ALREADY + " Nobody is waiting now."),
    # an older bridge asked nobody, and claims nothing about them
    (None, T_ALREADY + " Nothing to change."),
], ids=["nobody-waiting", "older-bridge"])
def test_the_terminal_retry_that_found_nobody_says_so(term, waiting, head):
    term.box["post"]["/device/visibility"] = _switched(waiting, changed=False)
    _cli(["device", "allow-all", "dev-a1", "yes"])
    assert term.out().splitlines()[0].replace(cli._OK, "✓") == head


@pytest.mark.parametrize("changed", [True, False], ids=["switched-on", "already-on"])
def test_the_terminal_says_allow_all_is_not_in_effect_never_nothing_to_change(
        term, changed):
    term.box["post"]["/device/visibility"] = _switched(_w(allow_all=False),
                                                       changed=changed)
    _cli(["device", "allow-all", "dev-a1", "yes"])
    out = term.out()
    assert out.splitlines()[1] == T_NOT_IN_EFFECT
    assert "Nothing to change" not in out and "Nobody is waiting now" not in out


def _t_requests(term, devices, rows):
    term.box["get"]["/devices"] = (200, {"devices": devices})
    term.box["get"]["/devices/requests"] = (200, {"incoming": rows, "requests": []})
    assert _cli(["device", "requests"]) == 0
    return term.out().splitlines()


@pytest.mark.parametrize("rows, n_phrase", [
    ([_row("dev-a1", "Sam"), _row("dev-a1", "Kim"), _row("dev-z9", "Ann")],
     "2 people are"),
    ([_row("dev-a1")], "1 person is"),
], ids=["two", "one"])
def test_the_terminal_requests_name_the_command_that_lets_them_in(term, rows, n_phrase):
    """The terminal's "Let them in (N)" (review, 2026-09-29): the whole command,
    with the computer's id, as every other row on this screen prints one."""
    lines = _t_requests(term, [CHAT_ON, dict(CHAT_SHARED)], rows)
    assert (f"     Studio PC lets anyone join at once, and {n_phrase} waiting for it "
            f"— let them in with:  agent device allow-all dev-a1 yes") in lines
    assert not any("nobody waits here" in ln for ln in lines)


@pytest.mark.parametrize("devices, rows", [
    ([dict(CHAT_OWNED)], [_row("dev-a1")]),
    ([dict(CHAT_SHARED)], [_row("dev-b2")]),
    ([CHAT_ON], [_row("dev-z9")]),
], ids=["approval-mode", "not-owned", "waiting-elsewhere"])
def test_the_terminal_requests_name_it_only_for_an_owned_allow_all_computer_with_people(
        term, devices, rows):
    lines = _t_requests(term, devices, rows)
    assert not any("allow-all" in ln for ln in lines)


@pytest.mark.parametrize("argv, value_help", [
    (["device", "allow-all", "--help"], "yes = anyone who asks joins at once"),
    (["device", "visibility", "--help"], "with public: anyone who asks joins at once"),
], ids=["allow-all", "visibility-allow-all"])
def test_the_terminal_help_says_anyone_already_waiting_joins_too(capsys, argv,
                                                                 value_help):
    """⛔ THE TERMINAL HAS NO CONFIRM STEP (review, 2026-09-29): its help is the only
    place a CLI owner reads what the yes does before it does it — and the web app
    and the chat both say the people waiting join too."""
    with pytest.raises(SystemExit) as done:
        _cli(argv)
    assert done.value.code == 0
    said = " ".join(capsys.readouterr().out.split())
    start = said.index(value_help)
    assert "anyone already waiting joins too (up to 25 people)" in said[start:start + 220]


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


def _skill_row(first_example: str) -> "tuple[str, str]":
    """(what the user says, what you run) — the routing-table row that opens with
    this example."""
    text = _SKILL.read_bytes().decode("utf-8").replace("\r\n", "\n")
    rows = [ln for ln in text.split("\n") if ln.startswith(f'| "{first_example}"')]
    assert len(rows) == 1, rows
    cells = [c.strip() for c in rows[0].strip().strip("|").split(" | ")]
    assert len(cells) == 2, cells
    return cells[0], cells[1]


def test_the_turn_on_row_gets_its_question_from_the_client():
    """⛔⛔ THE ROW IS THE MAIN PATH, AND IT WAS THE OLD QUESTION (review,
    2026-09-29). The host maps "turn on allow all" straight from this row and
    reaches `do` only when no row fits — so the count `do` puts in never reached
    the owner, and the parenthetical the host relayed said nothing about the
    people waiting. Now the row asks `do` for the question, and says what it
    holds, pinned against the question itself so the two cannot drift again."""
    says, runs = _skill_row("turn on allow all")
    question = sr._NL_CONFIRMS["device-allow-all"]
    assert sr._AA_WAITING_JOIN in question
    assert runs.startswith('**confirm** — run `sr.py do "<the user\'s message, '
                           'verbatim>"` and relay the client\'s question verbatim (')
    held = runs[runs.index("verbatim ("):runs.index(") — then `sr.py device-allow-all yes`")]
    assert sr._AA_WAITING_JOIN.rstrip(".").lower() in held.lower()
    # …and every example in the row reaches that very question through `do`
    examples = re.findall(r'"([^"]+)"', says)
    assert len(examples) >= 10, examples
    for said in examples:
        argv, asked = sr._nl_resolve(said)
        assert argv is None, (said, argv)
        assert asked == [question.format(name="that computer")], said


_README = Path(__file__).resolve().parents[1] / "README.md"


def test_the_readme_row_says_anyone_already_waiting_joins_too():
    text = _README.read_bytes().decode("utf-8").replace("\r\n", "\n")
    rows = [ln for ln in text.split("\n") if ln.startswith("/sr device-allow-all yes|no")]
    assert len(rows) == 1, rows
    assert "anyone already waiting joins too" in rows[0]
