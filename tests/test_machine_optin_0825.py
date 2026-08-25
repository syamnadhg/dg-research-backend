"""Wave 8 step J — the machine's own logs are OPT-IN, and unticked.

⛔⛔ WHAT THIS CHANGED, AND WHY IT IS A BETTER DEFAULT THAN THE ONE SHIPPED FIRST.
Wave 8 gave an OWNER the machine-level material on every send automatically:
pairing and sign-in sessions, the raw device tails. The reasoning was that an
owner is entitled to their own machine's logs — which is true, and is not the
same as having ASKED for them. Defaulting to the larger bundle is the one
direction this whole wave is supposed to fail in. It is now a tick-box under the
run list, unticked, owner-only.

⭐ AND THE FLAG IS READ OFF THE COMMAND, which is the opposite of the call made
for `consent`. That one is a claim about what a person was shown, so a caller
could forge it and the sink must not trust it. This one can only ever make the
bundle SMALLER, because it is ANDed with ownership: a sharer who sets it gets
nothing extra. Failing closed here means collecting less, so the safe default and
the honest default are the same thing.

⛔ THE TERMINAL IS DELIBERATELY UNCHANGED. `--send-logs` still sends the machine
material by default — the person running it is physically at the machine, and the
founding incident was a pairing failure that produced no run at all, so that
material is the whole evidence there.
"""
import json

import pytest

import research

CODE = "7QK4M2XZ"


# ── the same fakes the command suite uses, kept local so this file's harness
#    does not depend on another file's private helpers ─────────────────────
class _FakeDoc:
    def __init__(self, sink, path):
        self.sink, self.path = sink, path

    def collection(self, name):
        return _FakeCol(self.sink, f"{self.path}/{name}")

    def get(self):
        outer = self

        class _Snap:
            def to_dict(self):
                return outer.sink.get(outer.path)
        return _Snap()

    def set(self, payload, **_kw):
        self.sink[self.path] = {**(self.sink.get(self.path) or {}), **payload}
        self.sink["_ops"].append(("set", self.path, payload))

    def update(self, payload):
        self.sink[self.path] = {**(self.sink.get(self.path) or {}), **payload}
        self.sink["_ops"].append(("update", self.path, payload))


class _FakeCol:
    def __init__(self, sink, path):
        self.sink, self.path = sink, path

    def document(self, name):
        return _FakeDoc(self.sink, f"{self.path}/{name}")


class _FakeDb:
    def __init__(self, sink):
        self.sink = sink

    def collection(self, name):
        return _FakeCol(self.sink, name)


@pytest.fixture()
def db(monkeypatch):
    sink = {"_ops": []}
    sink["devices/d-1"] = {"ownerUid": "user-rocky", "sharedWith": ["user-alice"]}
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(sink))
    monkeypatch.setattr(research, "_be_payload", lambda d: {**d, "deviceId": "d-1"})
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what=None, **k: op())
    monkeypatch.setattr(research, "WORKER_ID", 1)
    monkeypatch.setattr(research, "_send_logs_cooldown_remaining",
                        lambda *a, **k: 0)
    monkeypatch.setattr(research, "_stamp_send_logs_attempt", lambda *a, **k: None)
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: "logs/x/y/z/bundle.zip")
    research._send_logs_inflight = False
    return sink


def _inline_thread(monkeypatch):
    class _Inline:
        def __init__(self, target=None, **kw):
            self._target = target

        def start(self):
            self._target()
    monkeypatch.setattr(research._log_threading, "Thread", _Inline)


@pytest.fixture()
def built(monkeypatch):
    """Capture the keywords `_build_log_bundle` was actually called with."""
    seen = {}

    def _build(dest, **k):
        seen.update(k)
        return {"path": dest, "sizeBytes": 1, "runCount": len(k.get("only_runs") or []),
                "sessionCount": 0, "uncompressedBytes": 1, "maxRunsApplied": 30,
                "machineIncluded": bool(k.get("include_machine", True)),
                "droppedForSize": [], "sourcesRefused": []}

    monkeypatch.setattr(research, "_build_log_bundle", _build)
    return seen


def _selected(**over):
    base = {"action": research.SEND_LOGS_SELECTED_ACTION, "code": CODE,
            "requestId": "req-1", "submittedBy": "user-rocky", "consent": True,
            "runNames": ["chat_1_1_20260824T000000"]}
    base.update(over)
    return base


def _send(monkeypatch, data, selected=True):
    _inline_thread(monkeypatch)
    research._handle_send_logs_command(data, "d-1", selected=selected)


# ══ 1. the flag parser ═════════════════════════════════════════════════
@pytest.mark.parametrize("value,expect", [
    (True, True),
    (False, False),
    (None, False),
    ("true", False),
    ("True", False),
    (1, False),
    ([], False),
    ({}, False),
])
def test_only_a_literal_true_asks_for_the_machine(value, expect):
    """⛔ IDENTITY AGAINST `True`, like the consent check beside it. `1` and
    `"true"` are the shapes a hand-written or older client sends, and every one
    of them resolving to False means collecting LESS — which is the direction
    this must fail in. It also means an app build that predates the box gets
    runs-only rather than the whole machine."""
    assert research._parse_include_machine({"includeMachine": value}) is expect


def test_an_absent_flag_is_a_no():
    assert research._parse_include_machine({}) is False


# ══ 2. what reaches the builder ════════════════════════════════════════
def test_an_owner_who_ticked_the_box_gets_the_machine(db, built, monkeypatch):
    _send(monkeypatch, _selected(includeMachine=True))
    assert built["include_machine"] is True
    assert built["only_runs"] == ["chat_1_1_20260824T000000"]


def test_an_owner_who_did_NOT_tick_it_gets_ONLY_their_runs(db, built, monkeypatch):
    """⭐⭐ THE CHANGE. This used to be unconditionally True for an owner."""
    _send(monkeypatch, _selected())
    assert built["include_machine"] is False
    assert built["only_runs"] == ["chat_1_1_20260824T000000"]


def test_a_SHARER_who_ticks_it_still_gets_nothing_extra(db, built, monkeypatch):
    """⛔⛔ THE FLAG IS ANDED WITH OWNERSHIP, so reading it off the command is safe
    in a way the consent flag is not: the worst a forged one can do is ask for
    something the machine refuses to give."""
    _send(monkeypatch, _selected(submittedBy="user-alice", includeMachine=True))
    assert built["include_machine"] is False
    assert built["requester_uid"] == "user-alice"


def test_the_legacy_actions_are_UNCHANGED(db, built, monkeypatch):
    """⛔ `send-logs` MEANS "this machine's own cap" — a build sending it is asking
    for the whole machine by definition, and there is no box on that path to
    consult. Changing it would alter what every older app build collects."""
    _send(monkeypatch, {"action": research.SEND_LOGS_ACTION, "code": CODE,
                        "requestId": "req-1", "submittedBy": "user-rocky",
                        "consent": True}, selected=False)
    assert built["include_machine"] is True
    assert built["only_runs"] is None


# ══ 3. nothing to send is a refusal, not an empty archive ══════════════
def _rows(sink):
    return [p for p in sink if p.startswith("users/")]


def test_an_owner_with_no_runs_and_no_box_is_REFUSED(db, built, monkeypatch):
    """⛔⛔ THIS USED TO BE ALLOWED, and it was right while the machine material
    rode along automatically — an owner ticking nothing meant "the machine's own
    logs", the pairing-failure case. With the box unticked there is genuinely
    nothing to send, and an archive of three JSON files handed back with a
    support code is worse than a refusal: the person believes they sent."""
    _send(monkeypatch, _selected(runNames=[]))
    assert built == {}, "it built an empty archive"
    row = db["users/user-rocky/logBundles/" + CODE]
    assert row["status"] == "failed"
    assert row["errorClass"] == "NothingSelected"


def test_an_owner_with_no_runs_but_the_BOX_TICKED_may_send(db, built, monkeypatch):
    """⭐ THE PAIRING-FAILURE CASE, and how it reads on screen now: no runs to
    tick, so the person ticks the box. A deliberate act rather than a default,
    which is the whole change."""
    _send(monkeypatch, _selected(runNames=[], includeMachine=True))
    assert built["include_machine"] is True
    assert built["only_runs"] == []
    assert db["users/user-rocky/logBundles/" + CODE]["status"] == "done"


def test_a_sharer_with_no_runs_is_still_refused(db, built, monkeypatch):
    _send(monkeypatch, _selected(submittedBy="user-alice", runNames=[],
                                 includeMachine=True))
    assert built == {}
    assert db["users/user-alice/logBundles/" + CODE]["errorClass"] == "NothingSelected"


# ══ 4. the row records what actually happened ══════════════════════════
def test_the_row_states_the_scope_it_was_built_with(db, built, monkeypatch):
    """⛔ The Firestore rule reads this field: a row in a tree the device does not
    OWN is accepted only when it says it carries no machine-level material. A row
    that disagreed with the archive would be the one lie that matters."""
    _send(monkeypatch, _selected())
    assert db["users/user-rocky/logBundles/" + CODE]["machineIncluded"] is False

    research._send_logs_inflight = False
    db["_ops"].clear()
    _send(monkeypatch, _selected(includeMachine=True))
    assert db["users/user-rocky/logBundles/" + CODE]["machineIncluded"] is True


def test_a_refusal_row_also_states_it(db, built, monkeypatch):
    """Every write to a non-owner tree is shape-checked, refusals included — a
    refusal row missing the field is a refusal the sharer never sees."""
    _send(monkeypatch, _selected(submittedBy="user-alice", consent=False,
                                 includeMachine=True))
    row = db["users/user-alice/logBundles/" + CODE]
    assert row["errorClass"] == "ConsentMissing"
    assert row["machineIncluded"] is False, (
        "a sharer's refusal row claimed machine material, which the rule refuses")


# ══ 5. the decision is made once ═══════════════════════════════════════
def test_the_scope_is_derived_once_and_reused():
    """⛔ Six call sites read it — the builder, the row opener, four refusals. A
    second copy of the expression is a second chance to get it wrong, and the
    two would disagree in exactly the case nobody tests."""
    from conftest import code_only
    src = code_only(research._handle_send_logs_command)
    assert src.count("_parse_include_machine(") == 1
    assert src.count("machine_wanted") >= 6
