"""Wave 2 step 4 — the device command behind the app's Send Logs button.

⭐ CONSENT AND RATE LIMITING LIVE AT THE SINK, not in the app's modal. A modal
is a property of one caller; the refusal here is a property of the machine, and
"any future command writer" includes the next person who adds a button.

⛔⛔ THE TWO MEASURED FAILURE MODES OF THE WORKER GATE, both described in that
block's own comments: without `send-logs` in the skip tuple every non-1 worker
races the archive build, AND a sibling's tail-delete of the command doc can be
coalesced away inside a stream-resync window, dropping the command with no
replay. So the tuple and the dispatch branch land together, and this file pins
that they still are together.
"""
import ast
import inspect
import json
import os
import re
import time
from pathlib import Path

import pytest

import research


class _FakeDoc:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data)


# ⛔⛔ THE FAKE ENFORCES WHAT THE RULES ENFORCE, and it is derived FROM the rules
# file rather than hand-copied beside it.
#
# On 2026-08-18 the live emulator refused three writes this backend really makes
# — both refusal rows and every terminal-initiated send — while this suite stayed
# green, because the fake below was a plain dict that accepted anything. The
# rules suite proved the GUARD, this suite proved the WRITER, and nothing ran the
# writer against the rule. A hand-copied allowlist here would have the same
# failure mode one release later, so the constraints are PARSED out of
# firestore.rules: add a key there and this follows; write a key here that is not
# there and this refuses, exactly as production would.
_RULES_PATH = (Path(__file__).resolve().parents[2] / "dg-research" / "firestore.rules")


def _rules_contract():
    """(allowed keys, the status a CREATE must carry) read from firestore.rules."""
    if not _RULES_PATH.exists():
        return None, None
    text = _RULES_PATH.read_text(encoding="utf-8")
    block = text[text.index("match /logBundles/{code}"):]
    block = block[:block.index("// Researches")] if "// Researches" in block else block
    keys = re.search(r"hasOnly\(\[(.*?)\]\)", block, re.S)
    status = re.search(r"allow create:.*?status == '(\w+)'", block, re.S)
    return (
        set(re.findall(r"'([A-Za-z]+)'", keys.group(1))) if keys else None,
        status.group(1) if status else None,
    )


class _RulesDenied(RuntimeError):
    """What Firestore raises, so a swallowed denial reads the same as production."""


class _FakeRef:
    def __init__(self, sink, path):
        self.sink = sink
        self.path = path

    def _enforce(self, payload, creating):
        allowed, create_status = _rules_contract()
        if allowed is None or not self.path.startswith("users/"):
            return
        unknown = set(payload) - allowed
        if unknown:
            raise _RulesDenied(f"PERMISSION_DENIED: keys not in hasOnly: {sorted(unknown)}")
        if creating and payload.get("status") != create_status:
            raise _RulesDenied(
                f"PERMISSION_DENIED: create must carry status "
                f"{create_status!r}, got {payload.get('status')!r}")

    def set(self, payload):
        self._enforce(payload, creating=self.path not in self.sink)
        self.sink.setdefault(self.path, {}).update(payload)
        self.sink["_ops"].append(("set", self.path, payload))

    def update(self, payload):
        if self.path not in self.sink:
            raise _RulesDenied("PERMISSION_DENIED: update before create")
        self._enforce(payload, creating=False)
        self.sink[self.path].update(payload)
        self.sink["_ops"].append(("update", self.path, payload))

    def get(self):
        return _FakeDoc(self.sink.get(self.path, {}))


class _FakeCollection:
    def __init__(self, sink, prefix):
        self.sink = sink
        self.prefix = prefix

    def document(self, name):
        return _FakeDocRef(self.sink, f"{self.prefix}/{name}")


class _FakeDocRef(_FakeRef):
    def collection(self, name):
        return _FakeCollection(self.sink, f"{self.path}/{name}")


class _FakeDb:
    def __init__(self, sink):
        self.sink = sink

    def collection(self, name):
        return _FakeCollection(self.sink, name)


@pytest.fixture
def db(monkeypatch):
    sink = {"_ops": []}
    sink["devices/d-1"] = {"ownerUid": "user-rocky"}
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(sink))
    monkeypatch.setattr(research, "_be_payload", lambda d: {**d, "deviceId": "d-1"})
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what=None, **k: op())
    monkeypatch.setattr(research, "WORKER_ID", 1)
    research._send_logs_inflight = False
    return sink


def _run_sync(monkeypatch):
    """Run the daemon thread's body inline so a test can assert on the result."""
    started = []

    class _Inline:
        def __init__(self, target=None, **kw):
            self._target = target
            started.append(kw.get("name"))

        def start(self):
            self._target()

    monkeypatch.setattr(research._log_threading, "Thread", _Inline)
    return started


CODE = "7QK4M2XZ"


def _cmd(**over):
    base = {"action": "send-logs", "code": CODE, "requestId": "req-1",
            "submittedBy": "user-rocky", "consent": True}
    base.update(over)
    return base


# ══ 1. the worker gate and the dispatch land together ══════════════════
# Every send-logs action name, by CONSTANT. A literal here would go stale the
# moment the contract file renames one and the test would still read as passing.
_SEND_LOGS_ACTION_CONSTANTS = (
    "SEND_LOGS_ACTION",
    "SEND_LOGS_LIMITED_ACTION",
    "SEND_LOGS_SELECTED_ACTION",
)


def _worker_skip_tuple() -> str:
    src = inspect.getsource(research._start_device_command_listener)
    m = re.search(r'elif action in \(([^)]*)\) and WORKER_ID != 1:', src, re.S)
    assert m, "the worker-1 gate moved — re-anchor this pin"
    return m.group(1)


def test_send_logs_is_in_the_worker_skip_tuple():
    """⛔ Without this, every non-1 worker races the build AND can tail-delete
    the command doc into a stream-resync coalesce.

    ⛔⛔ AND THIS USED TO BE A CONTAINMENT CHECK ON TWO NAMES, which is a guard
    that cannot notice the mistake it exists for. The mistake is one of OMISSION:
    a new action added to the dispatch and forgotten here ships dead on every
    multi-worker host with nothing failing anywhere — and a test that asks "are
    these two present?" passes happily with a third one missing. It now walks the
    action vocabulary, so adding a name to the contract and not to this tuple is
    what goes red."""
    tuple_src = _worker_skip_tuple()
    for name in _SEND_LOGS_ACTION_CONSTANTS:
        assert name in tuple_src, (
            f"{name} is missing from the worker-1 skip tuple, so every non-primary "
            f"worker DELETES that command before worker 1 can see it")


def test_every_send_logs_action_constant_is_covered_by_that_check():
    """⛔ The guard above is only as complete as its list. This is what makes a
    FOURTH action name fail rather than quietly sit outside both."""
    live = {n for n in dir(research)
            if n.startswith("SEND_LOGS_") and n.endswith("_ACTION")}
    assert live == set(_SEND_LOGS_ACTION_CONSTANTS), (
        f"the action vocabulary changed: {sorted(live)}. Add the new name to "
        f"_SEND_LOGS_ACTION_CONSTANTS, to the worker skip tuple and to the "
        f"dispatch tuple — all three, or it ships dead.")


def _dispatch_tuple() -> str:
    src = inspect.getsource(research._start_device_command_listener)
    m = re.search(r'if action in \(([^)]*?)\):\n\s+# App-driven support bundle',
                  src, re.S)
    assert m, "the send-logs dispatch branch moved — re-anchor this pin"
    return m.group(1)


def test_the_dispatch_branch_runs_on_worker_one_only():
    tuple_src = _dispatch_tuple()
    for name in _SEND_LOGS_ACTION_CONSTANTS:
        assert name in tuple_src, (
            f"{name} reaches no dispatch branch, so the command is deleted and "
            f"the app reads the silence as a build too old to understand it")
    src = inspect.getsource(research._start_device_command_listener)
    i = src.index("# App-driven support bundle")
    branch = src[i:i + 1800]
    assert "if WORKER_ID == 1:" in branch
    assert "_handle_send_logs_command(" in branch


def test_the_handler_does_not_block_the_snapshot_callback():
    """A synchronous upload here queues restart/hard_reset behind it and into
    the 30-second stale reaper."""
    src = inspect.getsource(research._handle_send_logs_command)
    assert "Thread(" in src and "daemon=True" in src


# ══ 2. the support code is a path segment and a capability ═════════════
def test_a_minted_code_is_eight_crockford_characters():
    for _ in range(200):
        code = research._mint_support_code()
        assert research._SUPPORT_CODE_RE.match(code), code
        for banned in "ILOU":
            assert banned not in code, code


def test_minted_codes_are_not_predictable():
    codes = {research._mint_support_code() for _ in range(500)}
    assert len(codes) > 490, "the code generator is not drawing from the CSPRNG"


def test_the_code_comes_from_the_system_csprng():
    """⛔ A source pin, because 500 draws from `random` are unique too — the
    property is unpredictability, and no black-box test can see it. The code IS
    the read capability for an unpaired bundle nobody's account owns yet."""
    src = inspect.getsource(research._mint_support_code)
    assert "secrets" in src, src
    assert "random" not in src


def test_a_command_with_no_valid_code_is_refused(db, monkeypatch):
    _run_sync(monkeypatch)
    for bad in ("", "short", "7qk4m2xz-lower", "../../etc", "7QK4M2XI"):
        research._handle_send_logs_command(_cmd(code=bad), "d-1")
    assert db["_ops"] == [], db["_ops"]


# ══ 3. owner-only, refusing on doubt ══════════════════════════════════
def test_a_device_read_failure_refuses_rather_than_proceeds(db, monkeypatch):
    """⛔ Found by mutation. The first version broke the WHOLE fake database, so
    the mutant that proceeds on a read failure — taking the ownership answer
    from the command itself — wrote nothing either, and the test passed. Only
    the device read fails here; everything else works."""
    _run_sync(monkeypatch)

    class _OnlyDeviceReadFails(_FakeDb):
        def collection(self, name):
            if name == "devices":
                raise RuntimeError("firestore unreachable")
            return _FakeCollection(self.sink, name)

    monkeypatch.setattr(research, "_firebase_db", _OnlyDeviceReadFails(db))
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: {"path": dest, "sizeBytes": 1,
                                           "runCount": 0, "sessionCount": 0,
                                           "maxRunsApplied": 30,
                                           "machineIncluded": True,
                                           "uncompressedBytes": 1,
                                           "droppedForSize": [],
                                           "sourcesRefused": []})
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: "logs/x")
    monkeypatch.setattr(research, "load_paired_uid", lambda: "user-rocky")
    research._handle_send_logs_command(_cmd(), "d-1")
    assert not any(op[1].startswith("logs/") for op in db["_ops"]), (
        "it took the ownership answer from the command it was meant to check")
    # ⭐ 08-21: it must still SAY SO. A bare return here is what the app reads as
    # "this machine's software is out of date", so the refusal has to reach the
    # one tree we still know — the uid stored locally at pair time.
    row = db[f"users/user-rocky/logBundles/{CODE}"]
    assert row["status"] == "failed"
    assert row["errorClass"] == "DeviceReadFailed"


def test_a_device_read_failure_PARKS_the_row_when_the_write_fails_too(
        db, monkeypatch, tmp_path):
    """⛔⛔ THE ONE THE FIRST DRAFT OF THIS FIX COULD NOT DELIVER, and the test
    above could not see it.

    `DeviceReadFailed` means a Firestore READ just raised. The row that is
    supposed to break the silence goes out through THE SAME client, channel and
    credential — so it fails for the same reason, and both writers are
    best-effort: they WARN and return False. The refusal was then dropped
    forever and the app was back to guessing "your software is out of date".

    ⛔ AND THE SIBLING TEST ABOVE IS BLIND TO IT BY CONSTRUCTION: its fake raises
    only for `collection("devices")` and hands back a working collection for
    `users`. Production has no per-collection dispatch — when Firestore is
    unreachable, it is unreachable for both. This one fails EVERY collection,
    which is the shape production actually has, and asserts the write is PARKED
    for the reconnect watcher to replay."""
    _run_sync(monkeypatch)

    class _EverythingFails(_FakeDb):
        def collection(self, name):
            raise RuntimeError("firestore unreachable")

    monkeypatch.setattr(research, "_firebase_db", _EverythingFails(db))
    monkeypatch.setattr(research, "load_paired_uid", lambda: "user-rocky")
    parked = []
    monkeypatch.setattr(research, "_queue_log_bundle_row",
                        lambda owner, code, patch, device_id="":
                        parked.append((owner, code, patch, device_id)))
    research._handle_send_logs_command(_cmd(), "d-1")
    assert parked, (
        "the refusal was dropped: the row write goes through the same client "
        "whose read just failed, so it has to be parked for the drain")
    owner, code, patch, device_id = parked[0]
    assert owner == "user-rocky"
    assert code == CODE
    assert patch["status"] == "failed"
    assert patch["errorClass"] == "DeviceReadFailed"
    assert device_id == "d-1"


def test_a_refusal_that_lands_first_time_is_NOT_parked(db, monkeypatch):
    """Accept polarity. Parking every refusal would make the reconnect watcher
    replay writes that already succeeded, and the drain replays create-then-patch
    — so a row that is already `failed` would be re-created and refused, warning
    on every tick forever."""
    _run_sync(monkeypatch)
    parked = []
    monkeypatch.setattr(research, "_queue_log_bundle_row",
                        lambda *a, **k: parked.append(a))
    research._send_logs_inflight = True
    try:
        research._handle_send_logs_command(_cmd(), "d-1")
    finally:
        research._send_logs_inflight = False
    assert db[f"users/user-rocky/logBundles/{CODE}"]["status"] == "failed"
    assert parked == [], "a write that landed was parked as well"


def test_a_device_read_failure_with_no_local_pairing_stays_silent(
        db, monkeypatch, capsys):
    """⚠ Stated rather than papered over: with the device read down AND no uid on
    disk there is no tree to write into, so this one case keeps the old silence.
    Pinned so nobody later "fixes" it by inventing an owner.

    ⭐ AND IT HAS TO SAY SO LOCALLY. This is the only path that refuses with
    nothing the app can read, so the machine's own log is the only place the
    reason survives. Without the line, the guard is unobservable — the
    downstream writer rejects an empty uid too, so nothing distinguishes a
    working guard from a redundant one."""
    _run_sync(monkeypatch)

    class _OnlyDeviceReadFails(_FakeDb):
        def collection(self, name):
            if name == "devices":
                raise RuntimeError("firestore unreachable")
            return _FakeCollection(self.sink, name)

    monkeypatch.setattr(research, "_firebase_db", _OnlyDeviceReadFails(db))
    monkeypatch.setattr(research, "load_paired_uid", lambda: None)
    research._handle_send_logs_command(_cmd(), "d-1")
    assert db["_ops"] == []
    out = capsys.readouterr().out
    assert "NO row" in out, out
    assert "DeviceReadFailed" in out, out


def test_a_command_naming_no_submitter_is_refused(db, monkeypatch, capsys):
    """⭐ Found by mutation. The inequality check below refuses this case too, so
    the only thing this guard changes is WHICH failure gets named — and after
    wave 1, naming the actual failure is the point rather than a nicety."""
    _run_sync(monkeypatch)
    research._handle_send_logs_command(_cmd(submittedBy=None), "d-1")
    assert not any(op[1].startswith("logs/") for op in db["_ops"])
    out = capsys.readouterr().out
    assert "names no submitter" in out, out
    row = db[f"users/user-rocky/logBundles/{CODE}"]
    assert row["status"] == "failed"
    assert row["errorClass"] == "SubmitterMissing"


def test_a_device_with_no_owner_says_THAT_rather_than_blaming_the_submitter(
        db, monkeypatch, capsys):
    """Same shape as above: an unpaired-looking device is a different problem
    from a sharer pressing a button, and the log has to say which."""
    _run_sync(monkeypatch)
    db["devices/d-1"] = {}
    research._handle_send_logs_command(_cmd(), "d-1")
    out = capsys.readouterr().out
    assert "no recorded owner" in out, out
    assert "not the device owner" not in out


def test_a_sharer_is_refused_even_if_the_rules_let_the_doc_through(db, monkeypatch):
    """⛔ Defense in depth: rules lag deploy, and this one hands over the
    contents of somebody else's machine.

    ⚠ AND THE ROW LANDS IN THE OWNER'S TREE, not the submitter's — the create
    rule pins the tree to the device's ownerUid. So this refusal is a record for
    the machine's owner, NOT a message to the sharer. Pinned here because
    "the sharer now gets a truthful message" would be a false claim."""
    _run_sync(monkeypatch)
    research._handle_send_logs_command(_cmd(submittedBy="user-alice"), "d-1")
    assert not any(op[1].startswith("logs/") for op in db["_ops"])
    assert f"users/user-alice/logBundles/{CODE}" not in db
    row = db[f"users/user-rocky/logBundles/{CODE}"]
    assert row["status"] == "failed"
    assert row["errorClass"] == "NotDeviceOwner"


def test_a_device_with_no_recorded_owner_is_refused(db, monkeypatch):
    _run_sync(monkeypatch)
    db["devices/d-1"] = {}
    research._handle_send_logs_command(_cmd(), "d-1")
    assert db["_ops"] == []


# ══ 4. consent at the sink ════════════════════════════════════════════
def test_a_request_with_no_consent_is_refused_and_says_so(db, monkeypatch):
    _run_sync(monkeypatch)
    research._handle_send_logs_command(_cmd(consent=None), "d-1")
    row = db[f"users/user-rocky/logBundles/{CODE}"]
    assert row["status"] == "failed"
    assert row["errorClass"] == "ConsentMissing"


def test_consent_must_be_exactly_true(db, monkeypatch):
    """A truthy string is what a hand-written command carries."""
    _run_sync(monkeypatch)
    for value in ("true", 1, "yes", {}):
        db["_ops"].clear()
        db.pop(f"users/user-rocky/logBundles/{CODE}", None)
        research._handle_send_logs_command(_cmd(consent=value), "d-1")
        row = db.get(f"users/user-rocky/logBundles/{CODE}", {})
        assert row.get("errorClass") == "ConsentMissing", value


# ══ 5. the cooldown, read from disk ═══════════════════════════════════
def test_the_cooldown_never_reads_firestore():
    """⛔ The machine this exists for cannot reach Firestore. A rate limit that
    needs the network stops working exactly when the button starts being
    pressed."""
    src = inspect.getsource(research._send_logs_cooldown_remaining)
    assert "_firebase_db" not in src and "collection(" not in src


def test_a_second_request_inside_the_window_is_refused(db, monkeypatch, tmp_path):
    _run_sync(monkeypatch)
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: {"path": dest, "sizeBytes": 100,
                                           "runCount": 1, "sessionCount": 0,
                                           "maxRunsApplied": 30,
                                           "machineIncluded": True,
                                           "uncompressedBytes": 100,
                                           "droppedForSize": [],
                                           "sourcesRefused": []})
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: "logs/user-rocky/d-1/x/bundle.zip")
    research._handle_send_logs_command(_cmd(), "d-1")
    assert db[f"users/user-rocky/logBundles/{CODE}"]["status"] == "done"

    second = "MJ72K62P"
    research._handle_send_logs_command(_cmd(code=second), "d-1")
    assert db[f"users/user-rocky/logBundles/{second}"]["errorClass"] == "CooldownActive"


def test_a_process_killed_mid_bundle_still_refuses_the_next_one(db, monkeypatch):
    """⭐ The stamp is written BEFORE the work, so 'kill it and press again' is
    not an unlimited loop."""
    _run_sync(monkeypatch)

    def _die(dest, **k):
        raise KeyboardInterrupt("killed mid-build")

    monkeypatch.setattr(research, "_build_log_bundle", _die)
    with pytest.raises(KeyboardInterrupt):
        research._handle_send_logs_command(_cmd(), "d-1")
    assert research._send_logs_cooldown_remaining() > 0, (
        "the attempt was not recorded, so pressing again would build another")


def test_the_cooldown_expires():
    research._stamp_send_logs_attempt(now=time.time() - research.SEND_LOGS_COOLDOWN_SEC - 1)
    assert research._send_logs_cooldown_remaining() == 0


def test_a_co_tenant_waits_the_short_floor_and_not_the_whole_window():
    """⛔⛔ THE FACT EVERY CLIENT'S REFUSAL SENTENCE DEPENDS ON, AND NOTHING PINNED
    IT. `SEND_LOGS_MACHINE_FLOOR_SEC` had zero test references anywhere in either
    suite while four clients told people the wait was ten minutes.

    Two windows, deliberately different sizes: the per-person one stops somebody
    hammering the button, the floor stops N co-tenants turning one bundle per ten
    minutes into N. Making them equal recreates the shared lockout the split
    exists to fix — so this asserts the SHAPE, not just the numbers.

    ⭐ The person here has never sent anything. On a shared research computer
    that is the ordinary caller, and the whole reason no client may name a
    number: the same refusal reaches them after a minute and reaches the person
    who pressed twice after ten."""
    owner, other = "user-rocky", "user-someone-else"
    now = time.time()
    research._stamp_send_logs_attempt(now=now, uid=owner)

    # The owner's own second press: the whole window.
    mine = research._send_logs_cooldown_remaining(now=now + 1, uid=owner)
    assert mine > research.SEND_LOGS_MACHINE_FLOOR_SEC, (
        "the person who just pressed is held only as long as a bystander")
    assert mine <= research.SEND_LOGS_COOLDOWN_SEC

    # Somebody else on the same machine, who has never pressed: the floor only.
    theirs = research._send_logs_cooldown_remaining(now=now + 1, uid=other)
    assert 0 < theirs <= research.SEND_LOGS_MACHINE_FLOOR_SEC, (
        "a co-tenant is being held for the per-person window, which is the "
        "shared lockout the split exists to prevent")

    # And once the floor has passed they are not refused at all, while the
    # owner still is — the two windows running side by side.
    past = now + research.SEND_LOGS_MACHINE_FLOOR_SEC + 1
    assert research._send_logs_cooldown_remaining(now=past, uid=other) == 0
    assert research._send_logs_cooldown_remaining(now=past, uid=owner) > 0


def test_a_stamp_from_an_older_build_still_holds_the_floor():
    """⭐ BACK-COMPAT IS FLOOR-DEEP, AND THAT IS WORTH SAYING OUT LOUD. A stamp
    written before the per-submitter split carries only `at`, so the person who
    just sent is held for a minute rather than ten. The direction is safe — a
    shorter wait, never a longer one — but it is a real case, and the copy that
    says "very recently" is true for it while "ten minutes" was not."""
    now = time.time()
    _atomic = research._send_logs_stamp_path()
    _atomic.parent.mkdir(parents=True, exist_ok=True)
    _atomic.write_text('{"at": %r}' % now, encoding="utf-8")
    held = research._send_logs_cooldown_remaining(now=now + 1, uid="user-rocky")
    assert 0 < held <= research.SEND_LOGS_MACHINE_FLOOR_SEC


def test_a_missing_or_corrupt_stamp_is_not_a_lockout():
    """A rate limit that fails CLOSED here would make one bad write permanent."""
    path = research._send_logs_stamp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")
    assert research._send_logs_cooldown_remaining() == 0


# ══ 6. single-flight ══════════════════════════════════════════════════
def test_a_second_press_while_one_is_building_is_refused(db, monkeypatch):
    """⚠ A RACE, NOT A DOUBLE-PRESS, and I had this wrong at first. `_work`
    stamps the cooldown as its first act and the cooldown check runs BEFORE this
    one, so a person pressing again seconds later is refused as CooldownActive —
    which always wrote a row. This branch is reachable by two tabs inside that
    millisecond window, and PERMANENTLY on a machine that cannot write the stamp
    file, because `_stamp_send_logs_attempt` swallows its own failure and leaves
    single-flight as the only guard. Either way a silent refusal here is the pair
    the app reads as "this machine's software is older than this setting"."""
    _run_sync(monkeypatch)
    research._send_logs_inflight = True
    try:
        research._handle_send_logs_command(_cmd(), "d-1")
    finally:
        research._send_logs_inflight = False
    assert not any(op[1].startswith("logs/") for op in db["_ops"]), (
        "the second press built a bundle anyway")
    row = db[f"users/user-rocky/logBundles/{CODE}"]
    assert row["status"] == "failed"
    assert row["errorClass"] == "AlreadyBuilding"


def test_the_refusal_never_steals_the_other_thread_s_claim(db, monkeypatch):
    """⛔ The single-flight branch must not clear a flag it did not set. The
    tempting shape — refuse inside the `with`, then fall through to the reset in
    `_work`'s finally — would release the FIRST press's claim."""
    _run_sync(monkeypatch)
    research._send_logs_inflight = True
    try:
        research._handle_send_logs_command(_cmd(), "d-1")
        assert research._send_logs_inflight is True, (
            "the refused second press released the running build's claim")
    finally:
        research._send_logs_inflight = False


def test_a_refusal_row_is_CREATED_at_collecting_then_patched_to_failed(
        db, monkeypatch):
    """⛔⛔ THE RULE ONLY PERMITS A CREATE AT 'collecting'
    (firestore.rules: `request.resource.data.status == 'collecting'`). A refusal
    written as one `set(status='failed')` is refused by the server, the write is
    best-effort, and the app is back to the silence this whole fix removes — and
    the fake database here would accept it happily. So the ORDER is the property,
    and it has to be asserted, not assumed."""
    _run_sync(monkeypatch)
    research._send_logs_inflight = True
    try:
        research._handle_send_logs_command(_cmd(), "d-1")
    finally:
        research._send_logs_inflight = False
    path = f"users/user-rocky/logBundles/{CODE}"
    mine = [op for op in db["_ops"] if op[1] == path]
    assert [op[0] for op in mine] == ["set", "update"], mine
    assert mine[0][2]["status"] == "collecting"
    assert mine[1][2]["status"] == "failed"


def test_the_single_flight_row_is_written_outside_the_lock(db, monkeypatch):
    """⛔ A Firestore round-trip held under _SEND_LOGS_LOCK serialises the fast
    path behind a network call. A source pin, because no black-box test can see
    which side of a `with` a call sits on."""
    src = inspect.getsource(research._handle_send_logs_command)
    body = src.split("with _SEND_LOGS_LOCK:", 1)[1]
    guarded = body.split("if _already_building:", 1)[0]
    assert "_refuse_log_bundle_with_row" not in guarded, (
        "the row write moved back inside the lock")


def test_the_inflight_flag_is_released_even_when_the_build_explodes(db, monkeypatch):
    _run_sync(monkeypatch)

    def _boom(dest, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(research, "_build_log_bundle", _boom)
    research._handle_send_logs_command(_cmd(), "d-1")
    assert research._send_logs_inflight is False, (
        "one failure would wedge the button for the life of the process")
    assert db[f"users/user-rocky/logBundles/{CODE}"]["errorClass"] == "RuntimeError"


# ══ 7. the row the app watches ════════════════════════════════════════
def test_the_row_walks_collecting_uploading_done(db, monkeypatch):
    _run_sync(monkeypatch)
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: {"path": dest, "sizeBytes": 712345,
                                           "runCount": 3, "sessionCount": 1,
                                           "maxRunsApplied": 30,
                                           "machineIncluded": True,
                                           "uncompressedBytes": 9_000_000,
                                           "droppedForSize": [],
                                           "sourcesRefused": []})
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: "logs/user-rocky/d-1/7QK4M2XZ/bundle.zip")
    research._handle_send_logs_command(_cmd(), "d-1")
    statuses = [p.get("status") for _op, path, p in db["_ops"]
                if path.endswith(CODE) and "status" in p]
    assert statuses == ["collecting", "uploading", "done"], statuses
    row = db[f"users/user-rocky/logBundles/{CODE}"]
    assert row["runCount"] == 3 and row["sizeBytes"] == 712345
    assert row["objectPath"].endswith(f"{CODE}/bundle.zip")
    assert row["requestId"] == "req-1"


def test_the_row_carries_an_expiry_and_a_build(db, monkeypatch):
    _run_sync(monkeypatch)
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: {"path": dest, "sizeBytes": 1,
                                           "runCount": 0, "sessionCount": 0,
                                           "maxRunsApplied": 30,
                                           "machineIncluded": True,
                                           "uncompressedBytes": 1,
                                           "droppedForSize": [],
                                           "sourcesRefused": []})
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: None)
    research._handle_send_logs_command(_cmd(), "d-1")
    row = db[f"users/user-rocky/logBundles/{CODE}"]
    assert row["expireAt"] is not None
    assert row["buildId"] == research._sr_version()
    assert row["status"] == "failed" and row["errorClass"] == "UploadFailed"


def test_a_failed_status_write_does_not_abort_a_working_upload(db, monkeypatch):
    """The tool has to be diagnosable, but a diagnostic must not break delivery."""
    _run_sync(monkeypatch)
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what=None, **k: (_ for _ in ()).throw(
                            RuntimeError("403")))
    uploaded = []
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: {"path": dest, "sizeBytes": 1,
                                           "runCount": 0, "sessionCount": 0,
                                           "maxRunsApplied": 30,
                                           "machineIncluded": True,
                                           "uncompressedBytes": 1,
                                           "droppedForSize": [],
                                           "sourcesRefused": []})
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: uploaded.append(1) or "logs/x")
    research._handle_send_logs_command(_cmd(), "d-1")
    assert uploaded, "a status-write failure stopped the upload"


# ══ 8. the upload itself ══════════════════════════════════════════════
class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


@pytest.fixture
def rest(monkeypatch, tmp_path):
    calls = []

    class _Requests:
        RequestException = RuntimeError

        @staticmethod
        def post(url, headers=None, data=None, timeout=None):
            calls.append({"url": url, "headers": dict(headers or {})})
            return _Resp(200)

    import sys
    monkeypatch.setitem(sys.modules, "requests", _Requests)
    monkeypatch.setattr(research, "_resolve_storage_bucket", lambda: "b.appspot.com")
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-1")
    bundle = tmp_path / "b.zip"
    bundle.write_bytes(b"PK\x03\x04payload")
    return calls, bundle


def test_the_content_type_is_always_sent(rest):
    """⛔ `requests` sends no content type for a raw file body, and the storage
    rule pins it — so an omitted header 403s our own honest upload, and the
    ladder retries a terminal error as a transient one."""
    calls, bundle = rest
    out = research._upload_log_bundle_via_storage_rest(bundle, "user-rocky", "d-1", CODE)
    assert out == f"logs/user-rocky/d-1/{CODE}/bundle.zip"
    assert calls[0]["headers"]["Content-Type"] == research.BUNDLE_CONTENT_TYPE
    assert calls[0]["headers"]["Authorization"] == "Firebase tok-1"


def test_an_oversized_bundle_is_refused_locally_not_by_a_403(rest, monkeypatch):
    """⛔ A cap-403 would be retried as claim-propagation and then reported as a
    transient failure. Making it unreachable is the fix."""
    calls, bundle = rest
    monkeypatch.setattr(research, "BUNDLE_UPLOAD_MAX_BYTES", 4)
    assert research._upload_log_bundle_via_storage_rest(
        bundle, "user-rocky", "d-1", CODE) is None
    assert calls == [], "it went to the network anyway"


def test_the_upload_ceiling_matches_the_storage_rule():
    """⛔ The local pre-check only makes a cap-403 unreachable if it is the SAME
    number the rule enforces. Cross-repo, a test is the only mechanism."""
    from pathlib import Path as _P
    rules = _P(__file__).resolve().parents[2] / "dg-research" / "storage.rules"
    if not rules.exists():
        pytest.skip("sibling app repo not checked out")
    text = rules.read_text(encoding="utf-8")
    block = text[text.index("match /logs/{userId}"):]
    block = block[:block.index("match /{allPaths")]
    m = re.search(r"request\.resource\.size < (\d+) \* (\d+) \* (\d+)", block)
    assert m, "the logs block no longer pins a size — a cap-403 became reachable"
    assert int(m.group(1)) * int(m.group(2)) * int(m.group(3)) == \
        research.BUNDLE_UPLOAD_MAX_BYTES


def test_the_content_type_matches_the_storage_rule_too():
    from pathlib import Path as _P
    rules = _P(__file__).resolve().parents[2] / "dg-research" / "storage.rules"
    if not rules.exists():
        pytest.skip("sibling app repo not checked out")
    text = rules.read_text(encoding="utf-8")
    block = text[text.index("match /logs/{userId}"):]
    block = block[:block.index("match /{allPaths")]
    assert f"contentType == '{research.BUNDLE_CONTENT_TYPE}'" in block


def test_a_bad_code_never_reaches_the_network(rest):
    calls, bundle = rest
    for bad in ("", "7qk4m2xz", "../../x", "TOOLONGCODE"):
        assert research._upload_log_bundle_via_storage_rest(
            bundle, "user-rocky", "d-1", bad) is None
    assert calls == []


def test_no_token_means_no_upload_rather_than_an_anonymous_one(rest, monkeypatch):
    calls, bundle = rest
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    assert research._upload_log_bundle_via_storage_rest(
        bundle, "user-rocky", "d-1", CODE) is None
    assert calls == []


def test_a_non_200_is_reported_as_a_failure(rest, monkeypatch):
    calls, bundle = rest
    import sys

    class _Requests:
        RequestException = RuntimeError

        @staticmethod
        def post(url, headers=None, data=None, timeout=None):
            calls.append(url)
            return _Resp(403, "permission denied")

    monkeypatch.setitem(sys.modules, "requests", _Requests)
    monkeypatch.setattr(research, "_STORAGE_REST_RETRY_DELAYS", ())
    assert research._upload_log_bundle_via_storage_rest(
        bundle, "user-rocky", "d-1", CODE) is None


def test_the_object_path_is_the_locator_the_rules_pin(rest):
    _calls, bundle = rest
    out = research._upload_log_bundle_via_storage_rest(bundle, "user-rocky", "d-1", CODE)
    assert out == f"logs/user-rocky/d-1/{CODE}/bundle.zip", out


# ══ 9. the local copy is the floor ════════════════════════════════════
def test_the_local_bundle_survives_a_failed_upload(db, monkeypatch):
    """⭐ If nothing could be uploaded the user still has a file to attach by
    hand — the whole design rests on that floor."""
    _run_sync(monkeypatch)
    built = {}

    def _build(dest, **k):
        Pathdest = dest
        Pathdest.parent.mkdir(parents=True, exist_ok=True)
        Pathdest.write_bytes(b"PK-bundle")
        built["path"] = Pathdest
        return {"path": Pathdest, "sizeBytes": 9, "runCount": 0,
                "sessionCount": 0, "uncompressedBytes": 9, "maxRunsApplied": 30,
                "machineIncluded": True,
                "droppedForSize": [], "sourcesRefused": []}

    monkeypatch.setattr(research, "_build_log_bundle", _build)
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: None)
    research._handle_send_logs_command(_cmd(), "d-1")
    assert built["path"].exists(), "the local copy was deleted on upload failure"
    assert str(built["path"]).endswith(f"support-{CODE}{research.BUNDLE_SUFFIX}")


# ══ 10. how many runs — the slider's sink ══════════════════════════════
class TestRunCount:
    """⛔⛔ THE DEFAULT IS DECIDED BY THE ACTION NAME, not by the field.

    On the FULL action an absent `runs` means "this machine's own cap", because
    that is what the action means. On the LIMITED action the whole point is a
    number, so anything unreadable REFUSES — falling back would resolve every
    malformed request toward MORE collection than was agreed to, and that is the
    one direction this must never fail in."""

    def test_the_full_action_means_the_machines_own_cap(self):
        assert research._parse_bundle_runs({}, False) == research.BUNDLE_MAX_RUNS
        # Even if a number rides along, the full action is not a limit.
        assert research._parse_bundle_runs({"runs": 3}, False) == research.BUNDLE_MAX_RUNS

    def test_the_limited_action_refuses_anything_it_cannot_read(self):
        for bad in (None, "5", 2.5, [], {}, float("nan")):
            assert research._parse_bundle_runs({"runs": bad}, True) is None, bad
        assert research._parse_bundle_runs({}, True) is None

    def test_a_boolean_is_refused_rather_than_read_as_one(self):
        """⭐ `True` IS an `int` in Python. Checked in the wrong order, a command
        carrying `runs: true` becomes "1 run" — a number nobody chose."""
        assert research._parse_bundle_runs({"runs": True}, True) is None
        assert research._parse_bundle_runs({"runs": False}, True) is None

    def test_below_the_floor_refuses_and_above_the_cap_clamps_DOWN(self):
        assert research._parse_bundle_runs({"runs": 0}, True) is None
        assert research._parse_bundle_runs({"runs": -1}, True) is None
        assert research._parse_bundle_runs({"runs": 9999}, True) == research.BUNDLE_MAX_RUNS

    def test_an_honest_number_survives(self):
        for n in (1, 7, 30):
            assert research._parse_bundle_runs({"runs": n}, True) == n

    def test_the_bound_reaches_the_builder(self, db, monkeypatch):
        _run_sync(monkeypatch)
        seen = {}

        def _build(dest, **k):
            seen.update(k)
            return {"path": dest, "sizeBytes": 1, "runCount": 2, "sessionCount": 0,
                    "maxRunsApplied": k.get("max_runs"), "uncompressedBytes": 1,
                    "machineIncluded": k.get("include_machine", True),
                    "droppedForSize": [], "sourcesRefused": []}

        monkeypatch.setattr(research, "_build_log_bundle", _build)
        monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                            lambda *a, **k: "logs/x")
        research._handle_send_logs_command(_cmd(runs=5), "d-1", limited=True)
        assert seen["max_runs"] == 5

    def test_the_row_reports_the_bound_the_BUILDER_applied(self, db, monkeypatch):
        """⭐ Sourced from the builder's return, not from the caller's variable.
        A value copied from the caller would still read as 5 if the `max_runs=`
        kwarg were ever dropped — leaving the row truthful-looking while 30 runs
        shipped against a request for 5."""
        _run_sync(monkeypatch)
        # ⛔ The two numbers are deliberately DIFFERENT. Asking for 5 while the
        # builder reports 4 is the only shape that can tell the two sources
        # apart — with both at 5 the row looks right no matter which one it read,
        # which is exactly how a dropped `max_runs=` would hide.
        monkeypatch.setattr(research, "_build_log_bundle",
                            lambda dest, **k: {"path": dest, "sizeBytes": 1,
                                               "runCount": 2, "sessionCount": 0,
                                               "maxRunsApplied": 4,
                                               "machineIncluded": True,
                                               "uncompressedBytes": 1,
                                               "droppedForSize": [],
                                               "sourcesRefused": []})
        monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                            lambda *a, **k: "logs/x")
        research._handle_send_logs_command(_cmd(runs=5), "d-1", limited=True)
        row = db[f"users/user-rocky/logBundles/{CODE}"]
        assert row["runsApplied"] == 4, (
            "the row echoed the request instead of reporting what the builder "
            "actually applied")
        assert row["runCount"] == 2
        # ⛔ EVERY write that carries it, not just the last one. The status walks
        # collecting → uploading → done, and a later write overwriting an earlier
        # wrong value hides the defect at the earlier site — which is where a
        # reader watching progress would have seen it.
        applied = [p.get("runsApplied") for _op, path, p in db["_ops"]
                   if path.endswith(CODE) and "runsApplied" in p]
        assert applied == [4, 4], applied

    def test_the_builder_reports_the_bound_it_really_used(self, tmp_path):
        out = research._build_log_bundle(tmp_path / "b.zip", max_runs=4)
        assert out["maxRunsApplied"] == 4

    def test_an_unreadable_count_refuses_and_says_which_refusal(self, db, monkeypatch):
        _run_sync(monkeypatch)
        built = []
        monkeypatch.setattr(research, "_build_log_bundle",
                            lambda *a, **k: built.append(1))
        research._handle_send_logs_command(_cmd(runs="lots"), "d-1", limited=True)
        assert built == [], "it built a bundle for a request it could not read"
        assert db[f"users/user-rocky/logBundles/{CODE}"]["errorClass"] == "RunsInvalid"

    def test_the_limited_action_is_in_the_worker_gate(self):
        """⛔⛔ An action outside that tuple falls to the `else` and is DELETED by
        every non-primary worker — so on a multi-worker host worker 2 destroys
        the command before worker 1 sees it, and the feature ships dead with
        nothing failing anywhere."""
        assert "SEND_LOGS_LIMITED_ACTION" in _worker_skip_tuple()

    def test_each_action_reaches_the_handler_under_its_own_flag(self):
        """⛔ Exactly one flag per action, and neither flag true for the full one.
        Two flags true at once would be a selection carried on an action whose
        older handler ignores it — the over-collection this vocabulary exists to
        make unreachable."""
        src = inspect.getsource(research._start_device_command_listener)
        assert "limited=(action == SEND_LOGS_LIMITED_ACTION)" in src
        assert "selected=(action == SEND_LOGS_SELECTED_ACTION)" in src
        assert research.SEND_LOGS_LIMITED_ACTION != research.SEND_LOGS_SELECTED_ACTION

    def test_the_two_repos_agree_on_the_cap_and_the_action_names(self):
        """⛔ The maximum slider position sends the FULL action, which means
        "this machine's own cap" — so if the two repos disagree about that
        number, the control's default states one thing and the machine does
        another, and nothing anywhere fails."""
        mine = json.loads(Path("bundle-contract.json").read_text(encoding="utf-8"))
        theirs_path = (Path(__file__).resolve().parents[2] / "dg-research"
                       / "src" / "lib" / "bundle-contract.json")
        assert mine["maxRuns"] == research.BUNDLE_MAX_RUNS
        assert mine["minRuns"] == research.BUNDLE_MIN_RUNS
        assert mine["actions"]["full"] == research.SEND_LOGS_ACTION
        assert mine["actions"]["limited"] == research.SEND_LOGS_LIMITED_ACTION
        if not theirs_path.exists():
            pytest.skip("sibling app repo not checked out")
        assert json.loads(theirs_path.read_text(encoding="utf-8")) == mine


# ══ 11. the consent copy is honest about what the number governs ═══════
class TestConsentScope:
    def test_the_first_line_names_the_number_and_the_age_bound(self):
        for n in (1, 5, 30):
            first = research._send_logs_consent_lines(n)[0]
            assert f"at most {n} run" in first
            assert "last 30 days" in first
        assert "at most 1 run " in research._send_logs_consent_lines(1)[0]
        assert "1 runs" not in research._send_logs_consent_lines(1)[0]

    def test_it_says_plainly_that_the_number_governs_ONE_line(self):
        """⛔⛔ The sessions are age-bound only and the raw tails have no bound at
        all — and those tails carry the same topics, links and account email for
        the machine's whole history. Without this, moving the number down reads
        as "less of everything leaves"."""
        lines = research._send_logs_consent_lines(1)
        assert any("only the first line" in l for l in lines), lines
        assert any("whatever number you pick" in l for l in lines)

    def test_the_lines_the_number_does_not_govern_never_change(self):
        """⛔⛔ SELECTED BY CONTENT, NOT BY POSITION — and it used to be `[1:-1]`,
        which broke the day a line was appended. The slice was a positional
        guess about which entries vary with the count: the first (the run line)
        and the last (the ⚠ note, which quotes the number). When the retention
        line arrived at the end on 2026-08-26, the ⚠ note moved to -2 and got
        compared, so the test failed on a line that has always varied — a
        correct assertion made wrong by arithmetic. Naming what varies is the
        only version of this that survives the list growing."""
        def fixed(runs: int) -> "list[str]":
            lines = research._send_logs_consent_lines(runs)
            # The run line always leads; the ⚠ note names the number wherever it
            # sits. Everything else must be identical for any count.
            return [l for l in lines[1:] if "only the first line" not in l]

        assert fixed(3) == fixed(17)
        # ⛔ And the filter must not have eaten the whole list, which would make
        # the comparison above pass by comparing nothing.
        assert len(fixed(3)) >= 6, fixed(3)
