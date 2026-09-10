"""Every device row this bridge emits is pruned to `_DEVICE_PUBLIC_KEYS`.

⛔⛔ WHY THIS FILE EXISTS. `firestore_rest.list_devices` sends no field mask, so
a device row arrives WHOLE — and three routes handed a caller the whole thing:
`GET /devices`, `GET /device`, `POST /device/select`. A never-rotated machine's
row still carries a plaintext `pairCode`, which is the credential that CLAIMS
it: `/api/devices/claim` grants ownership on `ownerUid == null`, and unlink
leaves exactly that state. So the leak was not "some internals" — it was the
key to the machine, on three routes both clients call routinely.

⛔⛔ NO ASSERTION IN THE SUITE COULD HAVE FAILED. Not one agent fixture carried
`pairCode`, `pollSecretHash`, `syntheticDeviceUid`, `people`, `ownerEmail` or
any of the rest — grep count zero for each — and the only exact-key-set
assertion in the whole agent suite (`test_signin_announce_0826.py`, on the
"pick one" descriptor) covered a DIFFERENT function. A projection with no
fixture to project is green by construction. So the fixture here carries the
full measured shape FIRST, and the assertions are exact-set, not subset: a
`pairCode` that starts riding along again turns this file red.

The field names below were read out of the writers, not invented —
`unpair-self`, `claim`, `pair-code`, `reset-pair-code` and `firestore.ts`'s
`DeviceInfo`. `currentRunTitle` is deliberately absent: 7.7E deleted it, and a
fixture that pins a field nobody writes is decoration.
"""

import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge


def _hb_now() -> int:
    """A lastHeartbeat that reads as ONLINE (within bridge._DEVICE_ONLINE_MS)."""
    return int(time.time() * 1000)


# ⛔ THE CREDENTIAL-BEARING FIELDS ARE NAMED SEPARATELY so a test can say which
# one it is protecting. `pairCode` claims the machine; `pollSecretHash` is the
# poll credential's hash; `syntheticDeviceUid` is the identity the read rule
# grants over the WHOLE document.
_SECRETS = ("pairCode", "pollSecretHash", "syntheticDeviceUid")


def _raw_device(did: str = "dev-a1", *, owner: str = "u1", **over) -> dict:
    """One device document as Firestore actually returns it — every field a real
    row carries, not just the ones a client wants."""
    row = {
        "id": did,
        "name": "Studio PC",
        "hostname": "studio.local",
        "machineName": "Studio PC",
        "visibility": "private",
        # —— everything below must never reach a client ——
        "ownerUid": owner,
        "sharedWith": ["u2", "u3"],
        "revokedSharers": ["u9"],
        "preResetUids": ["u9"],
        "people": {"u2": {"role": "sharer"}},
        "ownerEmail": "owner@example.com",
        "ownerDisplayName": "The Owner",
        "pairCode": "SR-PLAINTEXT-CODE",
        "pollSecretHash": "sha256:deadbeef",
        "syntheticDeviceUid": "synthetic-dev-a1",
        "pairState": "paired",
        "pairConfirmedAt": 1_700_000_000_000,
        "lastHeartbeat": _hb_now(),
        "currentRunId": "r-1",
        "workers": {"1": {"uid": "u1", "runId": "r-1", "phase": 2, "totalPhases": 5}},
        "queueOwners": [{"uid": "u2", "runId": "r-2", "position": 1}],
        "feFifoCurrent": {"holder": "tab-7", "acquiredAt": 1_700_000_000_000},
        "logins": {"chatgpt": True, "claude": False},
        "setupState": "ready",
        "mutSeq": 41,
    }
    row.update(over)
    return row


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
    monkeypatch.setattr(bridge.prefs, "set_selected_device",
                        lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device",
                        lambda: sel.__setitem__("v", None))

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


# ── the three emitters, exact key sets ────────────────────────────────────────

# ⛔⛔ THE EXPECTED SET IS A LITERAL, AND IT HAS TO BE. These three assertions used
# to compare the emitted row against `bridge._DEVICE_PUBLIC_KEYS` itself, so both
# sides moved together and the guard was BLIND IN THE WIDENING DIRECTION — the one
# direction that leaks. Cross-verify measured it: appending
# `("logins", "workers", "queueOwners", "currentRunId", "feFifoCurrent",
#   "setupState", "pairState", "mutSeq")` to the tuple left 16/16 GREEN while all
# three routes published which AI accounts are signed in on the machine plus other
# people's uids and run ids. The comment in bridge.py claiming these assertions
# "make that decision loud" was false because of exactly this.
#
# ⭐ IT IS THE FIXTURE-DERIVED-FROM-THE-CONSTANT SHAPE THIS REPO HAS RECORDED
# BEFORE: a test whose expectation is computed from its subject cannot see the
# subject move. Widening the allow-list must now require editing this line, which
# is the point — the edit is the decision.
_EXPECTED_KEYS = {"id", "name", "hostname", "machineName",
                  "owned", "selected", "online", "visibility"}


def test_the_allow_list_is_exactly_what_this_file_expects():
    """The one place the two are compared, so a widening is a visible edit here."""
    assert set(bridge._DEVICE_PUBLIC_KEYS) == _EXPECTED_KEYS


def test_devices_list_emits_exactly_the_allowed_keys(live):
    base, _ = live
    FakeFS.devices = [_raw_device()]
    row = requests.get(base + "/devices").json()["devices"][0]
    assert set(row) == _EXPECTED_KEYS


def test_device_current_emits_exactly_the_allowed_keys(live):
    base, sel = live
    FakeFS.devices = [_raw_device()]
    sel["v"] = "dev-a1"
    row = requests.get(base + "/device").json()["device"]
    assert set(row) == _EXPECTED_KEYS


def test_device_select_emits_exactly_the_allowed_keys(live):
    base, _ = live
    FakeFS.devices = [_raw_device()]
    row = requests.post(base + "/device/select",
                        json={"deviceId": "dev-a1"}).json()["device"]
    assert set(row) == _EXPECTED_KEYS


@pytest.mark.parametrize("secret", _SECRETS)
def test_no_emitter_ships_a_credential(live, secret):
    """The three routes, one credential at a time, named in the failure."""
    base, sel = live
    FakeFS.devices = [_raw_device()]
    sel["v"] = "dev-a1"
    bodies = [
        requests.get(base + "/devices").text,
        requests.get(base + "/device").text,
        requests.post(base + "/device/select", json={"deviceId": "dev-a1"}).text,
    ]
    for text in bodies:
        assert secret not in text, f"{secret} reached a client"
        assert "SR-PLAINTEXT-CODE" not in text


# ── the prune is in place, and that is the load-bearing part ──────────────────

def test_decorate_prunes_the_callers_own_row_in_place():
    """⛔⛔ THREE CALLERS PASS A ONE-ELEMENT LITERAL LIST AND THEN READ THE
    ORIGINAL VARIABLE — `{"device": match}`, `row.get("owned")`, `return match`.
    A `_decorate_devices` that built fresh dicts and returned them would compile,
    pass a test written against its return value, and leave all three routes
    emitting the row they still held a reference to. So this asserts on the
    variable that was passed IN, exactly as those callers do."""
    # `_make_handler` returns the handler CLASS, so `_decorate_devices` comes
    # back as a plain function — call it unbound (`self` is unused) and no HTTP
    # machinery is needed to exercise the projection.
    handler = bridge._make_handler(bridge.BridgeState())
    row = _raw_device()
    handler._decorate_devices(None, [row], "u1", "dev-a1")
    assert set(row) == set(bridge._DEVICE_PUBLIC_KEYS)


def test_owned_survives_the_prune_that_removes_ownerUid():
    """`owned` is DERIVED from `ownerUid`, which the prune deletes — so the flags
    have to be set before the narrowing, not after. Both answers, one call."""
    handler = bridge._make_handler(bridge.BridgeState())
    mine, theirs = _raw_device("d-mine", owner="u1"), _raw_device("d-theirs", owner="u2")
    handler._decorate_devices(None, [mine, theirs], "u1", "d-mine")
    assert mine["owned"] is True and theirs["owned"] is False
    assert "ownerUid" not in mine and "ownerUid" not in theirs
    assert mine["selected"] is True and theirs["selected"] is False


def test_online_survives_the_prune_that_removes_lastHeartbeat():
    """Same shape as `owned`: computed from a field that does not survive."""
    handler = bridge._make_handler(bridge.BridgeState())
    on = _raw_device("d-on", lastHeartbeat=_hb_now())
    off = _raw_device("d-off", lastHeartbeat=1)
    handler._decorate_devices(None, [on, off], "u1", None)
    assert on["online"] is True and off["online"] is False
    assert "lastHeartbeat" not in on and "lastHeartbeat" not in off


def test_visibility_survives_the_prune(live):
    """The publish surfaces read `visibility` back off the decorated row, so it
    is on the allow-list on purpose — a prune that dropped it would break the
    "it is already public" reply rather than leak anything.

    ⛔ IT ALSO HAS TO CARRY THE VALUE THROUGH, not merely the key: the earlier
    version of this test passed with the prune removed entirely, because all it
    proved was that `visibility` is in the allow-list — which the line above
    already covers."""
    base, _ = live
    FakeFS.devices = [_raw_device(visibility="public"),
                      _raw_device("dev-b2", visibility="private")]
    rows = {d["id"]: d for d in requests.get(base + "/devices").json()["devices"]}
    assert rows["dev-a1"]["visibility"] == "public"
    assert rows["dev-b2"]["visibility"] == "private"
    assert set(rows["dev-b2"]) == _EXPECTED_KEYS


# ── the descriptor stays narrower than the list ───────────────────────────────

def test_descriptor_is_a_subset_of_the_allow_list():
    """⛔ NOT REBUILT FROM THE TUPLE — pinned as a SUBSET. An error body that
    says "pick one of these" needs a label and a power state, nothing more, and
    widening the allow-list for a device-list consumer must never widen a chat
    error body behind anyone's back."""
    keys = set(bridge._device_descriptor(_raw_device()))
    assert keys <= set(bridge._DEVICE_PUBLIC_KEYS)
    assert keys == {"id", "name", "online"}


@pytest.mark.parametrize("secret", _SECRETS)
def test_descriptor_drops_credentials_too(secret):
    assert secret not in bridge._device_descriptor(_raw_device())


# ── the allow-list itself ─────────────────────────────────────────────────────

def test_allow_list_holds_no_credential_and_no_membership():
    """A guard on the DECISION, not the mechanism: these are the field names it
    must never be legal to add. Membership (`sharedWith`, `people`) is on the
    list because who else uses a machine is not the asking account's business."""
    # ⛔ EVERY FIELD THE FIXTURE CARRIES THAT IS NOT ON THE ALLOW-LIST, derived so
    # it cannot go short. The hand-written version named nine and omitted
    # `logins`, `workers`, `queueOwners`, `currentRunId`, `feFifoCurrent`,
    # `setupState`, `pairState` and `mutSeq` — which is how a widening that
    # published other people's uids and run ids stayed green.
    banned = set(_raw_device()) - _EXPECTED_KEYS
    assert banned, "the fixture must carry fields the allow-list excludes"
    assert not (set(bridge._DEVICE_PUBLIC_KEYS) & banned), (
        f"these must never be shareable: {sorted(set(bridge._DEVICE_PUBLIC_KEYS) & banned)}")


def test_allow_list_covers_the_whole_label_ladder():
    """`_device_label` walks name → hostname → id and `_public_label_of` adds
    `machineName`. A prune that dropped a rung would rename people's computers
    to their device id — which is what the label ladder exists to avoid."""
    assert {"id", "name", "hostname", "machineName"} <= set(bridge._DEVICE_PUBLIC_KEYS)
