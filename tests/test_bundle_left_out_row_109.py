"""Wave 10.9 (W9) — the person who sent their logs is told what was left out.

⛔⛔ WHAT WAS WRONG. The bundle builder has always counted what it cut: older
items dropped to stay under the size cap, ticked runs it would not attribute to
the asker, and — since #539 — runs another member started, kept out of an
owner's bundle. All three reached the machine's own log line and the terminal.
The row the app reads carried `runCount` and `runsApplied` and nothing else, so
somebody who ticked five runs saw "Sent" and support received three.

⭐ THE SHAPE: the `done` write carries the three COUNTS — never names, since a
run folder's name is a research id — and a rules DENIAL of a write carrying them
is retried once without them, because the rules deploy separately from this code
and a lost `done` write is worse than a lost count: it leaves the pathless row
Clear logs has to hold back.

Every test below EXECUTES the writer — the pure helper directly, and the
consumers through the real device handler, the real terminal command and the real
row writer against a fake Firestore that captures what it is sent.
"""
import re
from pathlib import Path

import pytest

import research
from conftest import web_file

CODE = "7QK4M2XZ"
LEFT_OUT = ("droppedForSize", "runsNotAttributed", "runsOtherMembers")


# ══ helpers ════════════════════════════════════════════════════════════
class PermissionDenied(Exception):
    """Named like google.api_core's, which is what `_is_synth_permission_denied`
    recognises by type name — the shape a real rules refusal arrives in."""


class _Ref:
    def __init__(self, sink, path):
        self.sink, self.path = sink, path

    def _write(self, kind, payload):
        self.sink["_attempts"].append((kind, self.path, dict(payload)))
        refuse = self.sink.get("refuse")
        if refuse is not None:
            err = refuse(payload)
            if err is not None:
                raise err
        self.sink[self.path] = {**(self.sink.get(self.path) or {}), **payload}
        self.sink["_ops"].append((kind, self.path, dict(payload)))

    def set(self, payload, **_kw):
        self._write("set", payload)

    def update(self, payload):
        self._write("update", payload)

    def collection(self, name):
        return _Col(self.sink, f"{self.path}/{name}")

    def get(self):
        data = self.sink.get(self.path) or {}

        class _Snap:
            def to_dict(self_inner):
                return dict(data)
        return _Snap()


class _Col:
    def __init__(self, sink, path):
        self.sink, self.path = sink, path

    def document(self, name):
        return _Ref(self.sink, f"{self.path}/{name}")


class _Db:
    def __init__(self, sink):
        self.sink = sink

    def collection(self, name):
        return _Col(self.sink, name)


@pytest.fixture()
def db(monkeypatch, tmp_path):
    sink = {"_ops": [], "_attempts": []}
    sink["devices/d-1"] = {"ownerUid": "U_ALICE", "sharedWith": ["U_BOB"]}
    monkeypatch.setattr(research, "_firebase_db", _Db(sink))
    monkeypatch.setattr(research, "_be_payload", lambda d: {**d, "deviceId": "d-1"})
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what=None, **k: op())
    monkeypatch.setattr(research, "_send_logs_cooldown_remaining", lambda *a, **k: 0)
    monkeypatch.setattr(research, "_stamp_send_logs_attempt", lambda *a, **k: None)
    monkeypatch.setattr(research, "_logs_root", lambda: tmp_path)
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: f"logs/U_ALICE/d-1/{CODE}/bundle.zip")

    class _Inline:
        def __init__(self, target=None, **kw):
            self._target = target

        def start(self):
            self._target()
    monkeypatch.setattr(research._log_threading, "Thread", _Inline)
    research._send_logs_inflight = False
    return sink


def _summary(**over):
    base = {"path": Path("x"), "sizeBytes": 10, "runCount": 3, "sessionCount": 1,
            "maxRunsApplied": 30, "machineIncluded": True, "uncompressedBytes": 20,
            "droppedForSize": ["chat_old_1", "sessions/pair-2026.log", "system/backend.log"],
            "sourcesRefused": [], "runsNotAttributed": 2, "runsOtherMembers": 4,
            "runsOnDisk": 9, "supportCode": CODE}
    base.update(over)
    return base


def _press(monkeypatch, summary):
    monkeypatch.setattr(research, "_build_log_bundle", lambda dest, **k: summary)
    research._handle_send_logs_command(
        {"action": research.SEND_LOGS_ACTION, "code": CODE, "requestId": "req-1",
         "submittedBy": "U_ALICE", "consent": True},
        "d-1", selected=False)


def _row_writes(sink):
    return [p for _k, path, p in sink["_ops"] if path.endswith(f"logBundles/{CODE}")]


# ══ the counts ══════════════════════════════════════════════════════════
def test_the_counts_are_the_builders_numbers_and_never_its_names():
    out = research._log_bundle_left_out(_summary())
    assert out == {"droppedForSize": 3, "runsNotAttributed": 2, "runsOtherMembers": 4}
    # Every value is an int — the row must not be able to carry a folder name.
    assert all(type(v) is int for v in out.values())


def test_absent_counts_read_as_zero_so_the_row_stays_typed():
    """`runsNotAttributed` exists only on a selection, and a builder that
    predates #539 reports no `runsOtherMembers`. Zero is what both mean there."""
    out = research._log_bundle_left_out({"droppedForSize": [], "runCount": 1})
    assert out == {"droppedForSize": 0, "runsNotAttributed": 0, "runsOtherMembers": 0}


# ══ the consumers ═══════════════════════════════════════════════════════
def test_the_app_done_write_carries_all_three_counts(db, monkeypatch):
    _press(monkeypatch, _summary())
    done = [p for p in _row_writes(db) if p.get("status") == "done"]
    assert len(done) == 1, _row_writes(db)
    assert done[0]["droppedForSize"] == 3
    assert done[0]["runsNotAttributed"] == 2
    assert done[0]["runsOtherMembers"] == 4
    # ⛔ The path still lands with them — the counts ride the SAME write.
    assert done[0]["objectPath"].endswith(f"{CODE}/bundle.zip")


def test_no_name_the_builder_dropped_reaches_the_row(db, monkeypatch):
    _press(monkeypatch, _summary())
    blob = repr(_row_writes(db))
    for name in ("chat_old_1", "pair-2026", "backend.log"):
        assert name not in blob


def test_only_the_done_write_carries_them(db, monkeypatch):
    """The `uploading` write goes out before the upload; what was left out is a
    fact about a SENT bundle, and a failed send has no "Sent" to sit beside."""
    _press(monkeypatch, _summary())
    for payload in _row_writes(db):
        if payload.get("status") != "done":
            assert not set(LEFT_OUT) & set(payload), payload


def test_the_terminal_done_row_carries_them_too(monkeypatch):
    rows = []
    monkeypatch.setattr(research, "_build_log_bundle", lambda dest, **k: _summary())
    monkeypatch.setattr(research, "load_paired_uid", lambda: "U_ALICE")
    monkeypatch.setattr(research, "load_device_id", lambda: "d-1")
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok")
    monkeypatch.setattr(research, "_decode_jwt_claims",
                        lambda t: {"ownerUid": "U_ALICE", "deviceId": "d-1"})
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda p, o, d, c: f"logs/{o}/{d}/{c}/bundle.zip")
    monkeypatch.setattr(research, "_open_log_bundle_row", lambda *a, **k: True)
    monkeypatch.setattr(research, "_write_log_bundle_status",
                        lambda o, c, patch, create=False: rows.append(patch) or True)
    research.cmd_send_logs(assume_yes=True)
    assert rows and rows[-1]["status"] == "done"
    assert {k: rows[-1][k] for k in LEFT_OUT} == {
        "droppedForSize": 3, "runsNotAttributed": 2, "runsOtherMembers": 4}


# ══ older rules: the counts give way, the path does not ═════════════════
def _old_rules(payload):
    """A ruleset that predates the three keys: `hasOnly` refuses the write."""
    if set(LEFT_OUT) & set(payload):
        return PermissionDenied("Missing or insufficient permissions.")
    return None


def test_a_denied_done_write_lands_WITHOUT_the_counts(db, monkeypatch, capsys):
    """⛔⛔ THE ORDERING HAZARD, made harmless. Against rules that do not know
    the counts, the whole `done` write — objectPath included — was refused, and
    the row sat at 'uploading' naming nothing."""
    db["refuse"] = _old_rules
    _press(monkeypatch, _summary())
    row = db[f"users/U_ALICE/logBundles/{CODE}"]
    assert row["status"] == "done"
    assert row["objectPath"].endswith(f"{CODE}/bundle.zip")
    assert not set(LEFT_OUT) & set(row)
    assert "predate them" in capsys.readouterr().out


def test_the_retry_happens_once_and_only_on_a_denial(db):
    """Polarity: a network failure is not retried here (the heal ladder already
    did that), and a denial of a write WITHOUT the counts has nothing to drop."""
    attempts = db["_attempts"]
    db[f"users/U_ALICE/logBundles/{CODE}"] = {"status": "uploading"}

    db["refuse"] = lambda p: ConnectionError("unreachable")
    assert research._write_log_bundle_status(
        "U_ALICE", CODE, {"status": "done", "droppedForSize": 1}) is False
    assert len(attempts) == 1

    attempts.clear()
    db["refuse"] = lambda p: PermissionDenied("Missing or insufficient permissions.")
    assert research._write_log_bundle_status(
        "U_ALICE", CODE, {"status": "done"}) is False
    assert len(attempts) == 1

    # A denial of a write carrying them: exactly two attempts, the second bare.
    attempts.clear()
    db["refuse"] = lambda p: PermissionDenied("Missing or insufficient permissions.")
    assert research._write_log_bundle_status(
        "U_ALICE", CODE, {"status": "done", "runsOtherMembers": 2}) is False
    assert len(attempts) == 2
    assert "runsOtherMembers" not in attempts[1][2]
    assert attempts[1][2]["status"] == "done"


def test_the_retry_keeps_everything_but_the_counts(db):
    db[f"users/U_ALICE/logBundles/{CODE}"] = {"status": "uploading"}
    db["refuse"] = _old_rules
    ok = research._write_log_bundle_status("U_ALICE", CODE, {
        "status": "done", "objectPath": "p", "runCount": 3,
        "droppedForSize": 1, "runsNotAttributed": 0, "runsOtherMembers": 2})
    assert ok is True
    landed = db["_ops"][-1][2]
    assert landed["objectPath"] == "p" and landed["runCount"] == 3
    assert not set(LEFT_OUT) & set(landed)


# ══ the rules name exactly what the machine writes ═════════════════════
def test_the_web_rules_allow_each_count_as_an_int():
    """⛔ THE HOLD, MADE MECHANICAL. This commit writes three keys the rules'
    `hasOnly` must name. Against a web checkout without them this FAILS — which
    is the signal that the rules have not landed yet, and the reason this commit
    waits for their deploy.

    Found through conftest's one finder: its own used to read a mistyped
    `SR_WEB_REPO` as "no web checkout here" and skip."""
    rules = web_file("the logBundles left-out counts", "firestore.rules")
    text = rules.read_text(encoding="utf-8")
    block = text[text.index("match /logBundles/{code}"):]
    block = block[:block.index("allow create:")]
    keys = re.search(r"hasOnly\(\[(.*?)\]\)", block, re.S)
    assert keys, "the logBundles hasOnly list moved — re-anchor this pin"
    named = set(re.findall(r"'([A-Za-z]+)'", keys.group(1)))
    for key in research._LOG_BUNDLE_LEFT_OUT_KEYS:
        assert key in named, f"{key} is not in the logBundles hasOnly list"
        assert re.search(rf"request\.resource\.data\.{key} is int", block), key
