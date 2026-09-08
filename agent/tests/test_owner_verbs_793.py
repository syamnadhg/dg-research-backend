"""The owner verbs: answering somebody who asked, and deciding who can find a
machine at all (wave 7.9-3, B5 / B6 / B7).

⛔⛔ WHAT THIS CODE DECIDES. Whether a person is let onto somebody else's
computer; whether a refusal that costs that person a week is made knowingly; and
whether a machine's name is published to every signed-in stranger. Every one of
those is somebody ELSE's exposure decided by this account, which is why the
gate, the wording, and the honesty about what a reply proves all sit here.
"""

from __future__ import annotations

import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from facade import bridge
from facade.firestore_rest import FirestoreError, FirestoreRest
from tests.conftest import code_only


class FakeFS:
    devices: list[dict] = []
    writes: list[tuple] = []
    raise_on_write: Exception | None = None

    def __init__(self, _token_provider):
        pass

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]

    def set_device_visibility(self, device_id, value):
        if FakeFS.raise_on_write is not None:
            raise FakeFS.raise_on_write
        FakeFS.writes.append((device_id, value))


OWNED = {"id": "dev-a1", "name": "Studio PC", "ownerUid": "u1",
         "pairConfirmedAt": True, "lastHeartbeat": 0}
SHARED = {"id": "dev-b2", "name": "Their Mac", "ownerUid": "u9",
          "pairConfirmedAt": True, "lastHeartbeat": 0}


@pytest.fixture()
def live(monkeypatch):
    FakeFS.devices = [dict(OWNED), dict(SHARED)]
    FakeFS.writes = []
    FakeFS.raise_on_write = None
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
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(base, path, body):
    return requests.post(base + path, json=body)


# ── B7: the owned gate ───────────────────────────────────────────────────────

def test_a_shared_machine_is_refused_before_the_round_trip(live, monkeypatch):
    """⛔⛔ THE WHOLE REASON THE GATE IS LOCAL. The web app answers a non-owner
    with the SAME 404 it gives for a machine that does not exist, so an ungated
    verb tells a sharer that the computer in their own list is not there."""
    called = []
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda *a, **k: called.append(a) or (200, {"ok": True}))
    r = _post(live, "/device/decide", {"deviceId": "dev-b2", "requesterUid": "u7",
                                       "decision": "approve"})
    assert r.status_code == 403
    assert r.json()["reason"] == "not_owner"
    assert not called, "the web app was reached for a machine this account only shares"


def test_the_refusal_names_the_relationship_they_do_have(live):
    r = _post(live, "/device/decide", {"deviceId": "dev-b2", "requesterUid": "u7",
                                       "decision": "approve"})
    said = r.json()["error"]
    assert "only the owner" in said
    # ⛔ Naming only what they lack leaves somebody wondering whether the machine
    # is theirs to see at all.
    assert "given access" in said


def test_an_unreachable_id_is_a_permissions_sentence_not_a_network_one(live):
    r = _post(live, "/device/visibility", {"deviceId": "nope",
                                           "visibility": "public"})
    assert r.status_code == 404
    assert r.json()["reason"] == "not_linked"
    assert "linked to your account" in r.json()["error"]
    assert "reach" not in r.json()["error"]


def test_both_owner_verbs_share_one_not_linked_sentence():
    """⛔ ONE SENTENCE, ONE PLACE. Two routes refuse this fact now; a literal
    written twice is one that ends up written two ways."""
    src = code_only(open(bridge.__file__, encoding="utf-8").read())
    assert src.count('"no computer with that id is linked to your account"') == 1
    assert src.count("_NOT_LINKED_ERROR") == 3


def test_the_gate_never_picks_a_machine_for_you(live):
    """⛔ NO AUTO-PICK. `_resolve_device` falls back to the selected machine,
    which is right for starting a run and wrong for publishing one."""
    r = _post(live, "/device/visibility", {"visibility": "public"})
    assert r.status_code == 400
    assert "deviceId" in r.json()["error"]


def test_owned_is_recomputed_and_never_read_off_the_document(live):
    """⛔⛔ `owned` IS NOT PERSISTED. A document carrying a stale — or hostile —
    `owned` key must not be believed; the ownerUid compare is the only source."""
    FakeFS.devices = [dict(SHARED, owned=True)]
    r = _post(live, "/device/visibility", {"deviceId": "dev-b2",
                                           "visibility": "public"})
    assert r.status_code == 403, r.text


# ── B5: answering somebody ───────────────────────────────────────────────────

def test_decide_forwards_all_three_fields(live, monkeypatch):
    seen = {}

    def _p(sess, path, payload, **kw):
        seen["path"], seen["payload"] = path, payload
        return 200, {"ok": True, "decision": "approved"}

    monkeypatch.setattr(bridge, "_fe_api_post", _p)
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": "approve"})
    assert r.status_code == 200
    assert seen["path"] == "/api/devices/access-request/decide"
    assert seen["payload"] == {"deviceId": "dev-a1", "requesterUid": "abc123",
                               "decision": "approve"}


@pytest.mark.parametrize("uid", ["", "  ", "has space", "dash-es", "under_score",
                                 "a" * 129, "e@x.y"])
def test_a_uid_the_route_would_refuse_is_refused_here_with_a_sentence(live, uid,
                                                                      monkeypatch):
    """⛔ The route answers `requester_required` and nothing else; checked here so
    the refusal is about what somebody typed rather than a foreign token."""
    called = []
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda *a, **k: called.append(a) or (200, {"ok": True}))
    r = _post(live, "/device/decide", {"deviceId": "dev-a1", "requesterUid": uid,
                                       "decision": "approve"})
    assert r.status_code == 400, uid
    assert r.json()["reason"] == "requester_required"
    assert not called


@pytest.mark.parametrize("decision", ["", "yes", "no", "APPROVE", "maybe", "1"])
def test_only_the_two_words_decide_anything(live, decision, monkeypatch):
    """⛔ AN EXPLICIT PAIR, NOT A TRUTHY FLAG — approving by accident grants a
    stranger a machine and denying by accident spends the asker's week."""
    called = []
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda *a, **k: called.append(a) or (200, {"ok": True}))
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": decision})
    assert r.status_code == 400, decision
    assert r.json()["reason"] == "decision_required"
    assert not called


def test_the_askers_id_stays_out_of_the_uploadable_log(live, monkeypatch):
    """⛔⛔ SAME RULE AS THE ASK. This log is uploadable to support and the person
    deciding is not the person whose id that is. The machine is this account's
    own, so it is logged like every other device this bridge acts on.

    ⛔⛔ CAPTURED OFF THE LOGGER ITSELF, NOT THROUGH `caplog`. The first version
    used `caplog` and passed alone and FAILED in the full suite, because
    something earlier had turned propagation off — and the half that matters,
    "the stranger's id is absent", passes VACUOUSLY against an empty capture.
    A privacy assertion that an empty string satisfies is not an assertion.
    """
    import logging

    records: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Grab()
    bridge.log.addHandler(handler)
    old_level = bridge.log.level
    bridge.log.setLevel(logging.INFO)
    try:
        monkeypatch.setattr(bridge, "_fe_api_post",
                            lambda *a, **k: (200, {"ok": True,
                                                   "decision": "approved"}))
        _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "SECRETUID9",
                                       "decision": "approve"})
    finally:
        bridge.log.removeHandler(handler)
        bridge.log.setLevel(old_level)
    text = "\n".join(records)
    # ⛔ THE NON-EMPTY CHECK IS THE ONE THAT MAKES THE NEXT LINE MEAN ANYTHING.
    assert text, "nothing was logged at all — the absence check below is vacuous"
    assert "SECRETUID9" not in text
    assert "dev-a1" in text


def test_an_upstream_ok_false_is_not_reported_as_success(live, monkeypatch):
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda *a, **k: (200, {"ok": False, "error": "nope"}))
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": "approve"})
    assert r.status_code == 502


def test_a_revoked_session_is_a_401_not_an_outage(live, monkeypatch):
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda *a, **k: (0, {"reason": "revoked", "error": "gone"}))
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": "approve"})
    assert r.status_code == 401
    assert r.json()["reason"] == "revoked"


def test_the_decision_the_route_reports_is_the_one_relayed(live, monkeypatch):
    """⛔⛔ The route closes an ALREADY-SHARED request as approved and writes
    nothing to the machine, so this side must relay what it said rather than
    echo what was asked for."""
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda *a, **k: (200, {"ok": True, "decision": "approved"}))
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": "deny"})
    assert r.json()["decision"] == "approved"


# ── B6: who can find it ──────────────────────────────────────────────────────

@pytest.mark.parametrize("typed", ["PUBLIC ", " Public", "Private", "PRIVATE"])
def test_case_and_spacing_are_normalised_before_the_value_is_judged(live, typed):
    """⛔ NORMALISE, THEN VALIDATE, THEN SEND THE CANONICAL WORD — in that order.
    The rules accept the two lowercase strings and nothing else, so a person who
    types "Public" must not be refused, and the wire must not carry what they
    typed."""
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": typed})
    assert r.status_code == 200, typed
    want = typed.strip().lower()
    assert r.json()["visibility"] == want
    if want == "public":
        assert FakeFS.writes == [("dev-a1", "public")]
    else:
        # Absent already reads as private, so there is nothing to write.
        assert FakeFS.writes == []


@pytest.mark.parametrize("value", ["", "hidden", "yes", "true", "0", "publicly",
                                   "public private"])
def test_a_value_the_rules_would_reject_never_reaches_firestore(live, value):
    """⛔⛔ THIS IS THE ONLY FIELD ON THE DEVICE DOCUMENT WHOSE VALUE THE RULES
    CHECK, and a value they reject refuses the WHOLE update — so an unchecked
    typo would not write a strange setting, it would fail a write the person
    believes they made."""
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": value})
    assert r.status_code == 400, value
    assert r.json()["reason"] == "visibility_required"
    assert FakeFS.writes == []


def test_a_public_switch_writes_the_field(live):
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "public"})
    assert r.status_code == 200
    assert FakeFS.writes == [("dev-a1", "public")]
    assert r.json()["changed"] is True
    assert r.json()["visibility"] == "public"


def test_absent_means_private_so_hiding_an_unset_machine_changes_nothing(live):
    """⛔⛔ A machine paired before 2026-09-04 carries no such field and nothing
    backfills one — the exact string is the only value that reads as public."""
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "private"})
    assert r.status_code == 200
    assert r.json()["changed"] is False
    assert r.json()["visibility"] == "private"
    assert FakeFS.writes == [], "a no-op wrote to the document anyway"


def test_a_rules_refusal_says_nothing_changed_and_a_server_fault_does_not(live):
    """⛔⛔ "NOTHING CHANGED" IS NOT ALWAYS SAYABLE. A 403 proves the write did
    not land. A 5xx happened after the request went out and proves nothing, so
    it must not promise the machine is as it was."""
    FakeFS.raise_on_write = FirestoreError("denied", status=403)
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "public"})
    assert r.status_code == 403
    assert r.json()["reason"] == "visibility_refused"
    assert "nothing changed" in r.json()["error"]

    FakeFS.raise_on_write = FirestoreError("boom", status=503)
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "public"})
    assert r.status_code == 502
    assert r.json()["reason"] == "visibility_unconfirmed"
    assert "nothing changed" not in r.json()["error"]
    assert "may or may not" in r.json()["error"]


def test_a_failure_with_no_status_is_read_as_the_unknown_case(live):
    """⛔ UNKNOWN IS THE DIRECTION THAT DOES NOT LIE. A transport error, or a
    double raising this by hand, carries no status — and must not be reported as
    a refusal that promises the machine is untouched."""
    FakeFS.raise_on_write = FirestoreError("no status here")
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "public"})
    assert r.status_code == 502
    assert r.json()["reason"] == "visibility_unconfirmed"


def test_the_reply_names_the_label_strangers_will_see(live):
    FakeFS.devices = [dict(OWNED, name="", machineName="",
                           hostname="Jane Smith's MacBook Pro")]
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "public"})
    assert r.json()["publicLabel"] == "Jane Smith's MacBook Pro"


def test_the_published_label_follows_the_web_apps_chain():
    """name → machineName → hostname → the fallback, each trimmed and skipped
    when it empties, then bounded to forty characters."""
    assert bridge._public_label_of({"name": " Studio ", "hostname": "h"}) == "Studio"
    assert bridge._public_label_of({"name": "  ", "machineName": "M"}) == "M"
    assert bridge._public_label_of({"hostname": "H"}) == "H"
    assert bridge._public_label_of({}) == "Research computer"
    assert bridge._public_label_of({"name": "x" * 60}) == "x" * 40
    # ⛔⛔ THIS ASSERTION PINNED THE WRONG ANSWER AND BLOCKED THE MUTANT THAT
    # WOULD HAVE CAUGHT IT. It claimed an all-strippable name "falls through to
    # the next link, exactly as the web app does" — the web app does the
    # opposite: `deviceDisplayName` chooses on the UNSTRIPPED value, so a name
    # that sanitises away returns the FALLBACK and never reaches the hostname.
    # Cross-verify found it by executing both implementations side by side.
    # Every expected value below was produced by running the real rule.
    assert bridge._public_label_of({"name": "\u202e", "hostname": "H"}) == \
        "Research computer"
    assert bridge._public_label_of({"name": "\u0001", "hostname": "H"}) == \
        "Research computer"
    # ⛔ Two characters were missing from the class, and the byte-order mark is
    # in it because Python's strip() keeps what JavaScript's trim() removes.
    assert bridge._public_label_of({"name": "\u200e"}) == "Research computer"
    assert bridge._public_label_of({"name": "\ufeff", "hostname": "H"}) == \
        "Research computer"
    assert bridge._public_label_of({"name": "\u200eMac"}) == "Mac"
    # ⛔ A BLANK name is different from an all-strippable one: it is never chosen
    # in the first place, so the ladder DOES continue past it.
    assert bridge._public_label_of({"name": "   ", "machineName": "M"}) == "M"
    # A non-string is skipped rather than coerced into a label.
    assert bridge._public_label_of({"name": 7, "hostname": "H"}) == "H"


def test_the_write_names_one_field_and_one_document():
    calls = []

    class _Resp:
        status_code = 200
        ok = True
        content = b"{}"

        @staticmethod
        def json():
            return {}

    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda method, url, token, body: (
        calls.append((method, url, body)) or _Resp())
    c.set_device_visibility("dev-a1", "public")
    method, url, body = calls[0]
    assert method == "PATCH"
    assert url.endswith("/devices/dev-a1?updateMask.fieldPaths=visibility")
    assert body == {"fields": {"visibility": {"stringValue": "public"}}}


def test_the_write_refuses_a_value_the_rules_would_reject():
    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda *a: pytest.fail("a bad value reached the wire")
    for bad in ("", "PUBLIC", "hidden", None, 1):
        with pytest.raises(ValueError):
            c.set_device_visibility("dev-a1", bad)


def test_the_raise_site_attaches_the_real_response_status():
    """⛔⛔ THE CONSTRUCTOR TAKING A STATUS PROVES NOTHING ABOUT THE ONE PLACE
    THAT RAISES. A mutant dropped `status=` at the raise site and every test
    stayed green, because they all built the error by hand — so the sentence
    that distinguishes a refusal from an outage was decided by a field nothing
    checked was ever populated."""

    class _Resp:
        status_code = 403
        ok = False
        text = "PERMISSION_DENIED"
        content = b"x"

    c = FirestoreRest(lambda force=False: "tok")
    c._send = lambda *a: _Resp()
    with pytest.raises(FirestoreError) as caught:
        c.set_device_visibility("dev-a1", "public")
    assert caught.value.status == 403

    class _Boom(_Resp):
        status_code = 503

    c._send = lambda *a: _Boom()
    with pytest.raises(FirestoreError) as caught:
        c.set_device_visibility("dev-a1", "public")
    assert caught.value.status == 503


def test_a_revoked_session_during_the_write_is_a_sign_in_problem(live):
    """⛔ It is the one failure the person can actually fix, and reporting it as
    an outage points them at a service that is answering fine."""
    from facade.session import RevokedError

    FakeFS.raise_on_write = RevokedError("gone")
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "public"})
    assert r.status_code == 401
    assert "revoked" in r.json()["error"]


def test_the_bridge_relays_the_owner_half_of_the_queue(live, monkeypatch):
    """⛔⛔ PINNED IN THIS WAVE'S OWN FILE. The guard for this lived in the
    previous wave's tests, so a mutant that dropped the owner's half scored a
    BORROWED kill — which is no evidence at all that the guard this wave wrote
    works."""
    monkeypatch.setattr(bridge, "_fe_api_get", lambda *a, **k: (200, {
        "incoming": [{"deviceId": "dev-a1", "requesterUid": "abc123",
                      "requesterLabel": "Sam Jones"}],
        "outgoing": [{"deviceId": "dev-z9"}]}))
    body = requests.get(live + "/devices/requests").json()
    assert body["incoming"] == [{"deviceId": "dev-a1", "requesterUid": "abc123",
                                 "requesterLabel": "Sam Jones"}]
    assert body["requests"] == [{"deviceId": "dev-z9"}]


@pytest.mark.parametrize("junk", ["nope", {"a": 1}, 7, None])
def test_neither_half_is_trusted_to_be_a_list(live, monkeypatch, junk):
    """A string would be iterated character by character by both clients."""
    monkeypatch.setattr(bridge, "_fe_api_get",
                        lambda *a, **k: (200, {"outgoing": junk, "incoming": junk}))
    body = requests.get(live + "/devices/requests").json()
    assert body == {"requests": [], "incoming": []}


def test_the_no_rules_change_evidence_still_names_one_field_and_one_document():
    """⛔⛔ A META-GUARD, AND IT NEEDS ONE. `test_app_plane_unchanged.py` is the
    single test standing in for "no security rule moved for this wave" — and a
    mutant that DELETES an assertion inside it cannot be caught by running it.
    Both of those mutants survived until this existed.

    ⛔ The path clause is checked as the exact quoted-document form. Widened to
    a bare prefix it would admit every subcollection under a device, which is
    the whole tree this evidence is about.
    """
    src = (Path(__file__).resolve().parent / "test_app_plane_unchanged.py"
           ).read_text(encoding="utf-8")
    assert 'p.startswith("/devices/{device_id}\\"")' in src, (
        "the device-document clause must stay quoted — a bare prefix admits "
        "every subcollection under it")
    assert "def test_this_client_can_never_choose_which_device_field_it_writes" in src
    assert 'body.count("updateMask.fieldPaths=visibility") == 1' in src, (
        "the field-name guard is gone — the path check cannot tell eight "
        "writable keys apart")
    for forbidden in ("name", "priority", "supervised", "restingWorkerIds",
                      "restNote"):
        assert f'"{forbidden}"' in src, f"{forbidden} dropped from the field guard"


def test_a_firestore_error_carries_the_status_that_decides_the_sentence():
    e = FirestoreError("x", status=403)
    assert e.status == 403
    # ⛔ Constructed without one — as every test double in this repo does — it
    # must read as unknown, never as a refusal.
    assert FirestoreError("x").status is None


# ── the branches cross-verify found untested ─────────────────────────────────

def test_a_non_string_body_field_is_refused_and_never_crashes(live):
    """⛔⛔ AN EXCEPTION OUT OF A HANDLER IS NOT A 500 — `http.server` drops the
    socket, so the caller gets NO reply and the traceback lands in the log that
    gets uploaded to support. `(body.get(k) or "").strip()` does exactly that on
    a number, and both new routes had refusals written for a bad id that could
    never be reached. Measured against a live handler before this was fixed."""
    for payload in ({"deviceId": 7, "visibility": "public"},
                    {"deviceId": True, "visibility": "public"},
                    {"deviceId": ["a"], "visibility": "public"},
                    {"deviceId": "dev-a1", "visibility": 9}):
        r = _post(live, "/device/visibility", payload)
        assert r.status_code == 400, payload
    for payload in ({"deviceId": 7, "requesterUid": "u", "decision": "approve"},
                    {"deviceId": "dev-a1", "requesterUid": 1,
                     "decision": "approve"},
                    {"deviceId": "dev-a1", "requesterUid": "abc123",
                     "decision": {"x": 1}}):
        r = _post(live, "/device/decide", payload)
        assert r.status_code == 400, payload


def test_a_decision_that_never_got_an_answer_says_so(live, monkeypatch):
    """⛔⛔ THE SAME HONESTY THE VISIBILITY WRITE ALREADY HAD. The route declares
    thirty seconds and this side gives up at fifteen, so a transport failure can
    sit on a decision that COMMITTED — and a deny that landed has already spent
    somebody's week. Reporting that as a plain failure invites the retry that
    then meets `request_not_pending`."""
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda *a, **k: (0, {"error": "could not reach (ReadTimeout)"}))
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": "deny"})
    assert r.status_code == 502
    assert r.json()["reason"] == "decide_unconfirmed"
    said = r.json()["error"]
    assert "may or may not" in said
    # ⛔ It must NOT claim nothing happened.
    assert "nothing" not in said.lower()


def test_a_revoked_session_still_beats_the_unconfirmed_branch(live, monkeypatch):
    """⛔ A dead session is status 0 too, and it is the one failure the person
    can actually fix — it must not be swallowed by the unknown-outcome branch."""
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda *a, **k: (0, {"reason": "revoked", "error": "gone"}))
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": "deny"})
    assert r.status_code == 401
    assert r.json()["reason"] == "revoked"


def test_the_decide_reply_falls_back_to_the_decision_it_asked_for(live, monkeypatch):
    """The `or` arm was never exercised: every stub supplied a decision, so an
    inverted fallback would have printed the deny sentence for an approval."""
    monkeypatch.setattr(bridge, "_fe_api_post", lambda *a, **k: (200, {"ok": True}))
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": "approve"})
    assert r.json()["decision"] == "approved"
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": "deny"})
    assert r.json()["decision"] == "denied"


def test_decide_refuses_a_missing_device_id(live):
    r = _post(live, "/device/decide", {"requesterUid": "abc123",
                                       "decision": "approve"})
    assert r.status_code == 400
    assert "deviceId" in r.json()["error"]


def test_the_gate_reports_a_dead_session_and_an_outage_differently(live,
                                                                   monkeypatch):
    """Only the write-time revoke was covered; the gate reads the device list
    first, and that read can fail both ways too."""
    from facade.session import RevokedError

    def _boom(exc):
        class _FS(FakeFS):
            def list_devices(self, uid):
                raise exc
        return _FS

    monkeypatch.setattr(bridge, "FirestoreRest", _boom(RevokedError("gone")))
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "public"})
    assert r.status_code == 401

    monkeypatch.setattr(bridge, "FirestoreRest",
                        _boom(FirestoreError("down", status=503)))
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "public"})
    assert r.status_code == 502


def test_a_no_op_still_reports_the_published_label(live):
    """The changed:False reply carries it too — an owner asking twice is owed
    the same answer as one asking once."""
    FakeFS.devices = [dict(OWNED, visibility="public")]
    r = _post(live, "/device/visibility", {"deviceId": "dev-a1",
                                           "visibility": "public"})
    assert r.json()["changed"] is False
    assert r.json()["publicLabel"] == "Studio PC"


def test_the_decide_reply_names_the_machine_the_way_its_siblings_do(live,
                                                                    monkeypatch):
    """⛔ `name` alone returns null for a machine nobody renamed, and the
    terminal then prints a device id where a label belongs."""
    FakeFS.devices = [dict(OWNED, name="", hostname="Loft Mac")]
    monkeypatch.setattr(bridge, "_fe_api_post",
                        lambda *a, **k: (200, {"ok": True, "decision": "approved"}))
    r = _post(live, "/device/decide", {"deviceId": "dev-a1",
                                       "requesterUid": "abc123",
                                       "decision": "approve"})
    assert r.json()["deviceName"] == "Loft Mac"


def test_the_no_rules_change_guard_reads_code_not_prose():
    """⛔ `code_only` is called MANDATORY by its own docstring for any assertion
    about what the code does, and the new app-plane assertions read raw source —
    so a docstring sentence could satisfy the field-name guard, and the `== 1`
    count could be broken by prose."""
    src = (Path(__file__).resolve().parent / "test_app_plane_unchanged.py"
           ).read_text(encoding="utf-8")
    body = src[src.index("def test_this_client_can_never_choose_which_device_field"):]
    assert "code_only(" in body, (
        "the field guard must read code, not comments and docstrings")


def test_the_forbidden_field_list_covers_every_other_writable_key():
    """⛔ The owner rule admits EIGHT keys and the guard listed five of the other
    seven, so a method that grew a `restEtaMs` write would pass it."""
    src = (Path(__file__).resolve().parent / "test_app_plane_unchanged.py"
           ).read_text(encoding="utf-8")
    for key in ("name", "priority", "supervised", "restingWorkerIds",
                "restEtaMs", "restEtaSetAt", "restNote"):
        assert f'"{key}"' in src, f"{key} is writable by that rule and unguarded"
