"""Wave 8L — asking a research computer for logs, from the agent.

⛔⛔ WHAT MAKES THIS DIFFERENT FROM THE APP'S BUTTON. The web app is used by the
person who owns the computer. A fleet box is not: one research computer can be
shared by many people at once (``DG_SUPER_RESEARCH_DEFAULT_DEVICE_CODE``), so
the agent's user is USUALLY a sharer, and every one of them is a co-tenant of
the same disk. This is the first surface where that boundary faces real
co-tenants rather than one owner and one guest, so the tests that matter most
here are the ones about what a request may ASK FOR, not the ones about it
working.

Three things are pinned harder than the rest:

  1. ⛔ ONE ACTION NAME, EVER. `send-logs` means "this machine's own cap" and
     `send-logs-limited` means "the newest N" — neither is scoped to a person,
     so either one is a whole-machine bundle. The Firestore rule keeps both
     owner-only and opens only `send-logs-selected` to a sharer. A regression
     that widened this would read as a working feature on the owner's own box
     and as a privacy breach on a fleet.
  2. ⛔ ASKING FOR SOMETHING YOU CANNOT HAVE IS A REFUSAL, NOT A SMALLER
     BUNDLE. The machine ANDs the machine-logs flag with ownership regardless,
     so a sharer gets nothing extra either way — what this layer decides is
     whether they are TOLD. On a shared box that case is the normal one.
  3. ⛔⛔ "NEVER PUBLISHED" IS NOT "HOLDS NOTHING". The first is a sentence
     about us and must not be printed; the second is a sentence about the
     machine and is worth printing. Collapsing them accuses a computer of
     having lost logs it may be holding right now.
"""

from __future__ import annotations

import re
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from facade import bridge
from facade.firestore_rest import FirestoreRest

BRIDGE_SRC = Path(bridge.__file__).read_text(encoding="utf-8")

UID = "u1"
OWNED = {"id": "dev1", "name": "Studio PC", "ownerUid": UID, "sharedWith": []}
SHARED = {"id": "dev2", "name": "Fleet Box", "ownerUid": "someone-else",
          "sharedWith": [UID]}


class FakeFS:
    """Only the calls these routes make. Every write is recorded so a test can
    assert that a REFUSAL wrote nothing — a route that answers 403 and posts the
    command anyway is the failure this fake is shaped to catch."""

    devices: list = []
    held: dict | None = None
    researches: list = []
    bundle_row: dict | None = None
    commands: list = []
    raise_on_held: Exception | None = None

    def __init__(self, _token_provider):
        pass

    @classmethod
    def reset(cls) -> None:
        cls.devices = [dict(OWNED), dict(SHARED)]
        cls.held = None
        cls.researches = []
        cls.bundle_row = None
        cls.commands = []
        cls.raise_on_held = None

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]

    def list_researches(self, uid):
        return [dict(r) for r in FakeFS.researches]

    def held_runs(self, uid, device_id):
        if FakeFS.raise_on_held is not None:
            raise FakeFS.raise_on_held
        return dict(FakeFS.held) if FakeFS.held is not None else None

    def get_log_bundle(self, uid, code):
        return dict(FakeFS.bundle_row) if FakeFS.bundle_row is not None else None

    def write_device_command(self, device_id, action, *, uid, extra=None):
        FakeFS.commands.append({"deviceId": device_id, "action": action,
                                "uid": uid, "extra": dict(extra or {})})
        return f"cmd-{len(FakeFS.commands)}"


@pytest.fixture()
def live(monkeypatch):
    FakeFS.reset()
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    monkeypatch.setattr(bridge.prefs, "get_or_create_install_id", lambda: "iid-test")
    sel = {"v": "dev1"}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device",
                        lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device",
                        lambda: sel.__setitem__("v", None))
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(
        uid=UID, email="e@x.y", id_token=lambda force=False: "tok",
        logout=lambda: None,
    ))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", sel
    finally:
        httpd.shutdown()


def _send(base, **body):
    payload = {"consent": True, "runNames": [], "includeMachine": False}
    payload.update(body)
    return requests.post(base + "/logs/send", json=payload)


# ── the support code ────────────────────────────────────────────────────────

def test_every_code_this_bridge_can_mint_is_one_the_machine_accepts() -> None:
    """⛔ The alphabet and the machine's pattern are two copies of one decision,
    in two repositories. A character in one that the other rejects produces a
    request the machine refuses with `no valid support code`, at a rate of one
    send in a few — which reads as a flaky computer, not as a typo in a string.
    Driven over the generator rather than eyeballed, because the failure is a
    single character and eyes are what let it through the first time."""
    machine_side = re.compile(r"^[0-9A-HJKMNP-TV-Z]{8}$")
    for _ in range(400):
        code = bridge._mint_support_code()
        assert machine_side.match(code), f"minted a code the machine refuses: {code}"


def test_the_code_alphabet_excludes_the_letters_people_misread() -> None:
    """I/L/O/U are out on purpose: a support code is read aloud on a call."""
    for ch in "ILOU":
        assert ch not in bridge._SUPPORT_CODE_ALPHABET


def test_codes_differ_between_requests(live) -> None:
    base, _ = live
    first = _send(base, runNames=["run-a"]).json()["code"]
    second = _send(base, runNames=["run-a"]).json()["code"]
    assert first != second, "two sends sharing a code would overwrite one bundle"


# ── the action name ─────────────────────────────────────────────────────────

def test_the_only_log_command_written_is_the_person_scoped_one(live) -> None:
    base, _ = live
    assert _send(base, runNames=["run-a"]).status_code == 200
    assert [c["action"] for c in FakeFS.commands] == ["send-logs-selected"]


def test_the_whole_machine_action_names_appear_nowhere_as_a_command() -> None:
    """A source pin, and it earns its place: the two legacy names are what a
    well-meaning change reaches for when someone wants "all the logs". Both are
    owner-only at the rule, so on the owner's own machine such a change would
    work perfectly and would only fail — silently, as a refusal nobody sees —
    for every sharer on a fleet box."""
    assert bridge._SEND_LOGS_ACTION == "send-logs-selected"
    # Every send-logs action name that exists in this file as a STRING, in
    # either quote style. Prose mentions of the legacy names use backticks and
    # are deliberately not caught — the point is what can reach the wire.
    quoted = set(re.findall(r"""["'](send-logs[a-z-]*)["']""", BRIDGE_SRC))
    assert quoted == {"send-logs-selected"}, (
        f"a whole-machine action name is writable from this file: {sorted(quoted)}")


# ── consent ─────────────────────────────────────────────────────────────────

def test_a_request_without_recorded_consent_is_refused_and_writes_nothing(live) -> None:
    base, _ = live
    r = requests.post(base + "/logs/send",
                      json={"runNames": ["run-a"], "includeMachine": False})
    assert r.status_code == 400
    assert r.json()["reason"] == "no_consent"
    assert FakeFS.commands == []


def test_consent_is_not_manufactured_from_a_truthy_value(live) -> None:
    """Identity against True, like the machine's own check: `1` and `"true"`
    are not a person having been shown anything."""
    base, _ = live
    for forged in (1, "true", "yes", [True]):
        r = requests.post(base + "/logs/send",
                          json={"consent": forged, "runNames": ["run-a"]})
        assert r.status_code == 400, f"{forged!r} was accepted as consent"
    assert FakeFS.commands == []


def test_an_accepted_request_carries_consent_on_the_wire(live) -> None:
    base, _ = live
    _send(base, runNames=["run-a"])
    assert FakeFS.commands[0]["extra"]["consent"] is True


# ── the sharer boundary ─────────────────────────────────────────────────────

def test_a_sharer_asking_for_the_machines_own_logs_is_told_no(live) -> None:
    base, sel = live
    sel["v"] = "dev2"
    r = _send(base, runNames=["run-a"], includeMachine=True)
    assert r.status_code == 403
    assert r.json()["reason"] == "machine_logs_owner_only"
    assert FakeFS.commands == [], (
        "refused and sent anyway — the person would be told no and get a bundle")


def test_the_refusal_says_their_own_runs_still_come(live) -> None:
    """⛔ A bare "you may not" reads as "you cannot send logs at all", and the
    person stops. Every run of theirs on that machine is still available and the
    sentence has to say so, or the refusal costs us the report."""
    base, sel = live
    sel["v"] = "dev2"
    body = _send(base, runNames=["run-a"], includeMachine=True).json()
    assert "every run of yours" in body["error"]


def test_the_owner_may_ask_for_the_machines_own_logs(live) -> None:
    base, sel = live
    sel["v"] = "dev1"
    assert _send(base, runNames=["run-a"], includeMachine=True).status_code == 200
    assert FakeFS.commands[0]["extra"]["includeMachine"] is True


def test_a_sharer_sending_their_own_runs_is_ordinary(live) -> None:
    """The boundary is about the MACHINE-level material, not about sharers."""
    base, sel = live
    sel["v"] = "dev2"
    assert _send(base, runNames=["run-a", "run-b"]).status_code == 200
    assert FakeFS.commands[0]["extra"]["runNames"] == ["run-a", "run-b"]


def test_the_machine_flag_is_always_on_the_wire_even_when_false(live) -> None:
    """⛔ An absent field and an explicit False are indistinguishable to the
    machine, and the row it writes is meant to record what a person CHOSE. A
    choice we cannot tell from a default is a choice we cannot show back."""
    base, _ = live
    _send(base, runNames=["run-a"])
    assert FakeFS.commands[0]["extra"]["includeMachine"] is False


def test_the_machine_flag_is_not_manufactured_from_a_truthy_value(live) -> None:
    base, _ = live
    _send(base, runNames=["run-a"], includeMachine="yes")
    assert FakeFS.commands[0]["extra"]["includeMachine"] is False


# ── the selection ───────────────────────────────────────────────────────────

def test_nothing_chosen_and_no_machine_logs_is_refused(live) -> None:
    """A zip of three JSON files handed back under a support code is worse than
    a refusal: the person believes they have sent something."""
    base, _ = live
    r = _send(base, runNames=[])
    assert r.status_code == 400
    assert r.json()["reason"] == "nothing_selected"
    assert FakeFS.commands == []


def test_the_owner_with_no_runs_may_still_send_the_machines_own_logs(live) -> None:
    """The pairing-failure case: nothing has run, so there is nothing to tick,
    and the machine's own logs are the entire point of the send."""
    base, _ = live
    assert _send(base, runNames=[], includeMachine=True).status_code == 200
    assert FakeFS.commands[0]["extra"]["runNames"] == []


def test_a_name_that_is_not_a_run_name_refuses_rather_than_dropping(live) -> None:
    """⛔ A dropped name is a run the person ticked, did not get, and was told
    they had sent. Refusing is the only failure direction that cannot lie."""
    base, _ = live
    for bad in ("../etc", "run a", "", 7, None, "-leading"):
        FakeFS.commands = []
        r = _send(base, runNames=["run-a", bad])
        assert r.status_code == 400, f"{bad!r} was accepted as a run name"
        assert FakeFS.commands == [], f"{bad!r} was refused and sent anyway"


@pytest.mark.parametrize("text", ["run-a", "abc"])
def test_runnames_must_be_a_list_not_a_string(live, text) -> None:
    """A string is iterable, so a missing check turns it into one name PER
    CHARACTER — none of which match anything on the far side.

    ⛔⛔ BOTH CASES, AND THE SECOND IS THE ONE THAT MATTERS. `"run-a"` refuses
    even without the list check, because its `-` fails the per-name shape and
    the loop rejects it — so a test using only that string passes against a
    broken check and proves nothing. Mutation caught exactly that here. An
    all-alphanumeric string has no such accident: every character is a valid
    name on its own, so it reaches the wire as three names the person never
    chose."""
    base, _ = live
    r = _send(base, runNames=text)
    assert r.status_code == 400, f"{text!r} was accepted where a list belongs"
    assert FakeFS.commands == []


def test_a_selection_larger_than_the_machine_publishes_is_refused(live) -> None:
    base, _ = live
    r = _send(base, runNames=[f"run-{i}" for i in range(61)])
    assert r.status_code == 400
    assert FakeFS.commands == []


def test_a_selection_at_the_bound_is_accepted(live) -> None:
    """The bound is the machine's published maximum, so the whole list has to
    fit through it — an off-by-one here hides the oldest run from every send."""
    base, _ = live
    assert _send(base, runNames=[f"run-{i}" for i in range(60)]).status_code == 200


# ── who it is aimed at ──────────────────────────────────────────────────────

def test_a_device_not_on_this_account_is_named_as_such(live) -> None:
    """⛔ Without this the rule refuses the create as a bare 403 and the person
    reads "could not reach the research store" — a sentence about us, when the
    truth is about which computers they can reach."""
    base, _ = live
    r = _send(base, runNames=["run-a"], deviceId="dev-nobody")
    assert r.status_code == 404
    assert r.json()["reason"] == "not_a_member"
    assert FakeFS.commands == []


def test_the_command_names_its_submitter(live) -> None:
    """The rule requires it and the machine reads it to decide whose runs may
    be in the bundle and whose tree the row lands in."""
    base, _ = live
    _send(base, runNames=["run-a"])
    assert FakeFS.commands[0]["uid"] == UID
    assert FakeFS.commands[0]["extra"].get("requestId")


# ── the run list ────────────────────────────────────────────────────────────

def test_never_published_is_reported_as_never_published(live) -> None:
    base, _ = live
    FakeFS.held = None
    body = requests.get(base + "/logs/runs").json()
    assert body["published"] is False
    assert body["runs"] == []


def test_published_and_empty_is_a_different_answer(live) -> None:
    base, _ = live
    FakeFS.held = {"runs": [], "truncated": False, "updatedAt": "2026-08-25T00:00:00Z"}
    body = requests.get(base + "/logs/runs").json()
    assert body["published"] is True, (
        "a machine that says 'I hold nothing of yours' must not read as silent")
    assert body["runs"] == []


def test_titles_are_joined_from_this_accounts_own_documents(live) -> None:
    """⭐⭐ The machine sends ids because no topic exists in a run folder at all.
    The words come from documents this account already holds, so nothing about
    what anybody researched has to leave that computer for the list to read."""
    base, _ = live
    FakeFS.held = {"runs": [{"name": "run-a", "researchId": "r1",
                             "startedUtc": "2026-08-24T10:00:00Z",
                             "status": "completed", "sizeBytes": 12, "attempt": 1}]}
    FakeFS.researches = [{"id": "r1", "title": "Tidal power"}]
    row = requests.get(base + "/logs/runs").json()["runs"][0]
    assert row["title"] == "Tidal power"
    assert row["name"] == "run-a"


def test_a_run_whose_research_document_is_gone_keeps_its_row(live) -> None:
    """The logs are still on that disk and still worth sending; it reads by its
    date instead. Dropping it would hide the runs most likely to need sending —
    the ones from a research the person already deleted in frustration."""
    base, _ = live
    FakeFS.held = {"runs": [{"name": "run-orphan", "researchId": "gone",
                             "startedUtc": "2026-08-01T10:00:00Z"}]}
    FakeFS.researches = []
    rows = requests.get(base + "/logs/runs").json()["runs"]
    assert [r["name"] for r in rows] == ["run-orphan"]
    assert rows[0]["title"] == ""


def test_an_entry_with_no_usable_name_is_dropped_from_the_list(live) -> None:
    """⛔ The opposite direction from the SEND path, and deliberately so. A row
    offered here is a row a person can tick, and a name that is not a string
    would be sent as "undefined" and match nothing — which reads to them as the
    machine ignoring their choice. Nothing is lost by omitting a row that could
    never have been honoured."""
    base, _ = live
    FakeFS.held = {"runs": [{"name": 7}, {"researchId": "r1"}, {"name": "run-ok"}]}
    rows = requests.get(base + "/logs/runs").json()["runs"]
    assert [r["name"] for r in rows] == ["run-ok"]


def test_the_list_says_whether_the_machine_truncated_it(live) -> None:
    base, _ = live
    FakeFS.held = {"runs": [{"name": "run-a"}], "truncated": True}
    assert requests.get(base + "/logs/runs").json()["truncated"] is True


def test_the_list_says_whether_this_person_owns_the_machine(live) -> None:
    """The caller needs it to decide whether to OFFER the machine's own logs at
    all — a tick-box that is refused when ticked is a worse surface than one
    that was never shown."""
    base, sel = live
    assert requests.get(base + "/logs/runs").json()["owned"] is True
    sel["v"] = "dev2"
    assert requests.get(base + "/logs/runs").json()["owned"] is False


def test_the_list_can_be_aimed_at_a_named_machine(live) -> None:
    base, _ = live
    body = requests.get(base + "/logs/runs?deviceId=dev2").json()
    assert body["deviceId"] == "dev2"
    assert body["owned"] is False


# ── the row ─────────────────────────────────────────────────────────────────

def test_a_row_that_has_not_appeared_yet_is_null_not_a_failure(live) -> None:
    """Worker 1 deletes the command before dispatching it, so there is a real
    window with neither a request nor a row. Calling that a failure would make
    every successful send report one."""
    base, _ = live
    FakeFS.bundle_row = None
    r = requests.get(base + "/logs/bundle?code=ABCD2345")
    assert r.status_code == 200
    assert r.json()["row"] is None


def test_a_row_is_handed_back_as_the_machine_wrote_it(live) -> None:
    base, _ = live
    FakeFS.bundle_row = {"status": "done", "runCount": 2, "sizeBytes": 4096,
                         "machineIncluded": False}
    body = requests.get(base + "/logs/bundle?code=ABCD2345").json()
    assert body["row"]["status"] == "done"
    assert body["row"]["runCount"] == 2


def test_something_that_is_not_a_support_code_is_refused(live) -> None:
    """The code is a path segment in the storage rule's own pattern. Checked at
    this boundary so a crafted one can never be interpolated into a request."""
    base, _ = live
    for bad in ("", "short", "ABCD234", "ABCD2345X", "ABCD/345", "ABCDI345"):
        r = requests.get(base + "/logs/bundle?code=" + bad)
        assert r.status_code == 400, f"{bad!r} was accepted as a support code"


def test_a_lowercase_code_is_accepted_as_the_same_code(live) -> None:
    """People type the code back from a chat message, and the machine upper-cases
    before matching. Refusing here would make a correct code look wrong."""
    base, _ = live
    FakeFS.bundle_row = {"status": "done"}
    r = requests.get(base + "/logs/bundle?code=abcd2345")
    assert r.status_code == 200
    assert r.json()["code"] == "ABCD2345"


# ── what actually goes on the wire ──────────────────────────────────────────
#
# The routes above run against a fake Firestore client, so nothing there sees
# the document the machine will read. These drive the real encoder.

class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._p = payload or {}
        self.content = b"x"
        self.text = ""

    def json(self):
        return self._p


def _capture(payload=None, status=200):
    """A FirestoreRest whose sends are recorded rather than made."""
    sent: list = []
    client = FirestoreRest(lambda force=False: "tok")

    def fake_send(method, url, token, json_body):
        sent.append({"method": method, "url": url, "body": json_body})
        return _Resp(status, payload or {"name": "p/commands/cmd1"})

    client._send = fake_send  # type: ignore[method-assign]
    return client, sent


def test_the_command_lands_in_the_device_scoped_collection() -> None:
    """⛔ `users/{uid}/devices/…` is the LEGACY path and the machine does not
    subscribe to it. A command written there leaves the person watching a
    spinner that can never resolve — there is no error, because nothing was
    wrong with the write."""
    from facade import config

    client, sent = _capture()
    client.write_device_command("dev1", "send-logs-selected", uid=UID,
                                extra={"code": "ABCD2345"})
    # ⛔⛔ ANCHORED AT THE BASE, NOT AT THE TAIL. The legacy path ALSO ends
    # `/devices/dev1/commands` — it just has `/users/{uid}` in front of it — so
    # an `endswith` here matches both and cannot see the difference between the
    # collection the machine listens to and the one it does not. Mutation caught
    # this test passing against exactly that swap.
    assert sent[0]["url"] == f"{config.FIRESTORE_BASE}/devices/dev1/commands"
    assert "/users/" not in sent[0]["url"]
    assert sent[0]["method"] == "POST"


def test_the_submitter_is_encoded_on_the_document() -> None:
    """The create rule requires it, and the machine reads it to decide whose
    runs may be in the bundle and whose tree the row lands in. Without it the
    write is denied and the person is told the store is unreachable."""
    client, sent = _capture()
    client.write_device_command("dev1", "send-logs-selected", uid=UID)
    fields = sent[0]["body"]["fields"]
    assert fields["submittedBy"] == {"stringValue": UID}


def test_the_timestamp_is_wall_clock_milliseconds() -> None:
    """⛔ The machine's listener drops a command older than 30 seconds on its
    first snapshot. A server-timestamp sentinel resolves after that comparison
    and a zero is ancient — either one makes every send silently vanish, and
    the only symptom is a bundle that never arrives."""
    import time as _time
    client, sent = _capture()
    before = int(_time.time() * 1000)
    client.write_device_command("dev1", "send-logs-selected", uid=UID)
    after = int(_time.time() * 1000)
    raw = sent[0]["body"]["fields"]["timestamp"]
    assert "integerValue" in raw, f"timestamp is not a number: {raw}"
    assert before <= int(raw["integerValue"]) <= after


def test_a_fresh_command_is_not_pre_marked_processed() -> None:
    """`processed` is the machine's own idempotency marker. Arriving already
    true is a command that reconnects are meant to skip — so it would be."""
    client, sent = _capture()
    client.write_device_command("dev1", "send-logs-selected", uid=UID)
    assert sent[0]["body"]["fields"]["processed"] == {"booleanValue": False}


def test_the_extra_fields_reach_the_document() -> None:
    client, sent = _capture()
    client.write_device_command("dev1", "send-logs-selected", uid=UID,
                                extra={"code": "ABCD2345", "consent": True,
                                       "runNames": ["run-a"], "includeMachine": False})
    fields = sent[0]["body"]["fields"]
    assert fields["consent"] == {"booleanValue": True}
    assert fields["includeMachine"] == {"booleanValue": False}
    assert fields["runNames"]["arrayValue"]["values"] == [{"stringValue": "run-a"}]


def test_a_machine_that_never_published_reads_as_missing_not_empty() -> None:
    """⛔⛔ The 404 has to survive as `None` all the way to the caller. Turning
    it into `{}` here is how "we cannot see this machine's list" becomes "that
    machine holds none of your runs" — an accusation, made in our own words,
    about a computer that may be holding them right now."""
    client, _ = _capture(status=404)
    assert client.held_runs(UID, "dev1") is None


def test_a_bundle_row_that_does_not_exist_yet_reads_as_missing() -> None:
    client, _ = _capture(status=404)
    assert client.get_log_bundle(UID, "ABCD2345") is None


def test_a_bundle_row_decodes_its_fields() -> None:
    client, _ = _capture(payload={
        "name": "users/u1/logBundles/ABCD2345",
        "fields": {"status": {"stringValue": "done"},
                   "runCount": {"integerValue": "2"},
                   "machineIncluded": {"booleanValue": False}}})
    row = client.get_log_bundle(UID, "ABCD2345")
    assert row["status"] == "done"
    assert row["runCount"] == 2
    assert row["machineIncluded"] is False
    assert row["code"] == "ABCD2345"


def test_the_held_list_is_read_from_this_persons_own_tree() -> None:
    """⛔ A field on the shared device document would be readable by every
    sharer of that machine, so one co-tenant would learn every other one's run
    history. The path is what scopes this, not a rule."""
    client, sent = _capture(payload={"name": "x", "fields": {}})
    client.held_runs(UID, "dev1")
    assert sent[0]["url"].endswith(f"/users/{UID}/deviceRunLogs/dev1")


# ── signed out ──────────────────────────────────────────────────────────────

def test_every_log_route_refuses_when_signed_out(monkeypatch) -> None:
    FakeFS.reset()
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    monkeypatch.setattr(bridge.prefs, "get_or_create_install_id", lambda: "iid-test")
    state = bridge.BridgeState()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        assert requests.get(base + "/logs/runs").status_code == 401
        assert requests.get(base + "/logs/bundle?code=ABCD2345").status_code == 401
        assert requests.post(base + "/logs/send",
                             json={"consent": True, "runNames": []}).status_code == 401
    finally:
        httpd.shutdown()
    assert FakeFS.commands == []
