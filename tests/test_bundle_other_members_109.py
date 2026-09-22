"""Wave 10.9 (#539) — an owner's support bundle carries nobody else.

⛔⛔ WHAT WAS WRONG, MEASURED 2026-09-21 in three real owner bundles. The uid was
stripped from index.json and from nowhere else: a second member's run folder
shipped whole (their uid in `meta.json` and in the run.log header, their topic in
the queue path), and the sessions and raw tails carried every member's uid —
`users/<uid>/`, `audio/<uid>/`, `o/logs%2F<uid>%2F…`, `ownerUid='…'`,
`submittedBy=<prefix>` — and their topics as `topic='…'`, `queues/<slug>_<ts>`
and `run_id=<slug>_<ts>`. All of it reached support on the OWNER's consent.

⭐ THE SHAPE: another member's run is left out and counted; everything not
provably the kept person's own goes through one redactor; the zip is 0600. The
owner's own run ships byte-for-byte, and a sharer's scoped bundle is unchanged.

Every test below EXECUTES the decision — the pure helpers directly, and the
consumers through the real builder, the real device handler and the real
terminal command.
"""
import json
import os
import stat
import time
import zipfile

import pytest

import research

U28_BOB = "B0bXyzAAAAbbbbCCCCdddd123456"      # Firebase-shaped: 28, mixed
U28_ALICE = "A1iceXyzAAAAbbbbCCCCdddd9876"
HEX28 = "0123456789abcdef0123456789ab"        # a digest, not a uid
assert len(U28_BOB) == len(U28_ALICE) == len(HEX28) == 28


# ══ helpers ════════════════════════════════════════════════════════════
@pytest.fixture()
def machine(tmp_path, monkeypatch):
    root = tmp_path / "logs"
    for sub in ("runs", "sessions"):
        (root / sub).mkdir(parents=True)
    queues = tmp_path / "queues"
    queues.mkdir()
    monkeypatch.setattr(research, "_logs_root", lambda: root)
    monkeypatch.setattr(research, "_runs_log_root", lambda: root / "runs")
    monkeypatch.setattr(research, "_sessions_log_root", lambda: root / "sessions")
    return {"root": root, "queues": queues, "tmp": tmp_path}


def _run(m, name, uid, text, age=0.0):
    folder = m["root"] / "runs" / name
    folder.mkdir()
    started = time.time() - age
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
    (folder / "meta.json").write_text(json.dumps({
        "schema": 1, "status": "complete", "researchId": name.split("_")[0],
        "startedUtc": iso, "submitterUid": uid,
        "submitterSource": "queue" if uid else "unclaimed"}), encoding="utf-8")
    (folder / "run.log").write_text(text, encoding="utf-8")
    return folder


def _queue(m, name, uid):
    d = m["queues"] / name
    d.mkdir()
    (d / "owner.json").write_text(json.dumps({"uid": uid, "researchId": "r"}),
                                  encoding="utf-8")


def _build(m, name="b.zip", **kw):
    dest = m["tmp"] / name
    kw.setdefault("queues_root", m["queues"])
    summary = research._build_log_bundle(dest, support_code="ABCD2345", **kw)
    with zipfile.ZipFile(dest) as zf:
        blobs = {n: zf.read(n) for n in zf.namelist()}
    return summary, blobs


def _red(keep="U_ALICE", known=(), owned=()):
    return research._BundleRedactor(keep, known_uids=known, owned_queues=owned)


# ══ 1. the selection, pure ═════════════════════════════════════════════
def _names(rows):
    return [r["name"] for r in rows]


def test_another_members_run_is_left_out_and_counted():
    rows = [{"name": "mine", "submitterUid": "U1"},
            {"name": "theirs", "submitterUid": "U2"},
            {"name": "legacy", "submitterUid": None},
            {"name": "blank", "submitterUid": ""}]
    kept, others = research._split_other_members_runs(rows, "U1")
    assert _names(kept) == ["mine", "legacy", "blank"]
    assert others == 1


@pytest.mark.parametrize("keep", [None, "", "   "])
def test_no_owner_keeps_no_attributed_run_but_every_unattributed_one(keep):
    """⛔ An unpaired machine has nobody to spare. Unattributed runs stay — that
    is every fleet run until the attributing wheel is published."""
    rows = [{"name": "a", "submitterUid": "U1"}, {"name": "b", "submitterUid": "U2"},
            {"name": "legacy", "submitterUid": None}]
    kept, others = research._split_other_members_runs(rows, keep)
    assert _names(kept) == ["legacy"]
    assert others == 2


# ══ 2. the selection, through the real builder ═════════════════════════
def test_the_owner_still_gets_N_runs_of_their_own(machine):
    """⛔ Other members' runs leave BEFORE the count bound. Dropping them after it
    would hand the owner N minus everyone else's — here, nothing at all."""
    _run(machine, "bob1_x", "U_BOB", "b1\n", age=10)
    _run(machine, "bob2_x", "U_BOB", "b2\n", age=20)
    _run(machine, "alice1_x", "U_ALICE", "a1\n", age=30)
    _run(machine, "alice2_x", "U_ALICE", "a2\n", age=40)
    summary, blobs = _build(machine, keep_uid="U_ALICE", max_runs=2)
    assert summary["runCount"] == 2
    assert "runs/alice1_x/run.log" in blobs and "runs/alice2_x/run.log" in blobs
    assert summary["runsOtherMembers"] == 2


def test_a_ticked_foreign_run_at_the_terminal_is_counted_never_named(machine):
    """`--send-logs --select` lists every folder, so the owner can tick bob's.
    It is left out, counted, and NOT reported as missing from the disk (that
    list names folders)."""
    _run(machine, "bob_x", "U_BOB", "users/U_BOB/researches/rB\n")
    _run(machine, "alice_x", "U_ALICE", "a\n")
    summary, blobs = _build(machine, keep_uid="U_ALICE",
                            only_runs=["bob_x", "alice_x"])
    assert "runs/alice_x/run.log" in blobs
    assert not any(n.startswith("runs/bob_x") for n in blobs)
    assert summary["runsOtherMembers"] == 1
    assert summary["runsNotOnDisk"] == []
    assert b"bob_x" not in blobs["collected.json"]


def test_a_sharers_scoped_bundle_is_unchanged(machine):
    """⭐ The requester is the kept person on a scoped bundle, so a sharer's own
    run ships byte-for-byte even though the device's owner is somebody else."""
    source = "Firestore bridge active: users/U_BOB/researches/rB\ntopic='bobs'\n"
    _run(machine, "bob_x", "U_BOB", source)
    summary, blobs = _build(machine, keep_uid="U_ALICE", only_runs=["bob_x"],
                            requester_uid="U_BOB", include_machine=False)
    assert blobs["runs/bob_x/run.log"] == source.encode()
    assert summary["runCount"] == 1
    assert summary["runsOtherMembers"] == 0


# ══ 3. what goes through the redactor, through the real builder ════════
def test_an_unattributed_run_ships_redacted(machine):
    """⛔⛔ Unattributed stays — and could be anybody's. Every fleet run is
    unattributed today and its run.log header names its submitter."""
    _run(machine, "legacy_x", None,
         "Firestore bridge active: users/U_BOB/researches/rB\n"
         "Queue: /srv/queues/bobs_secret_topic_20260920_000847\n")
    summary, blobs = _build(machine, keep_uid="U_ALICE")
    log = blobs["runs/legacy_x/run.log"]
    assert b"U_BOB" not in log and b"bobs_secret_topic" not in log
    assert b"users/member-1/researches/rB" in log
    assert b"queues/20260920_000847" in log
    assert summary["runCount"] == 1
    collected = json.loads(blobs["collected.json"])
    assert "runs/legacy_x/run.log" in collected["filesRedacted"]


def test_the_owners_own_run_ships_byte_for_byte(machine):
    """⭐ ACCEPT POLARITY. The kept person's own folder is theirs, topic and all
    — a redactor run over it would strip a topic nobody else owns."""
    source = ("Firestore bridge active: users/U_ALICE/researches/rA\n"
              "Phase 1 topic='alice private topic'\n"
              "Queue: /srv/queues/alices_unlisted_20260920_000002\n")
    _run(machine, "alice_x", "U_ALICE", source)
    summary, blobs = _build(machine, keep_uid="U_ALICE")
    assert blobs["runs/alice_x/run.log"] == source.encode()
    assert "runs/alice_x/run.log" not in json.loads(blobs["collected.json"])["filesRedacted"]


def test_sessions_and_tails_are_redacted_and_still_shipped(machine):
    line = ("[00:08:47] Firestore start: uid=U_BOB... topic=Bobs Secret run_id="
            "bobs_secret_topic_20260920_000847\n"
            "[00:08:48] owner ok users/U_ALICE/researches/rA\n")
    (machine["root"] / "backend.log").write_text(line, encoding="utf-8")
    (machine["root"] / "sessions" / "serve_20260920T000000.log").write_text(
        line, encoding="utf-8")
    _summary, blobs = _build(machine, keep_uid="U_ALICE")
    for name in ("system/backend.log", "sessions/serve_20260920T000000.log"):
        data = blobs[name]
        assert b"U_BOB" not in data and b"Bobs Secret" not in data, name
        assert b"bobs_secret_topic" not in data, name
        assert b"run_id=20260920_000847" in data, name
        assert b"users/U_ALICE/researches/rA" in data, name
    assert set(json.loads(blobs["collected.json"])["filesRedacted"]) >= {
        "system/backend.log", "sessions/serve_20260920T000000.log"}


def test_the_owners_queue_keeps_its_name_and_nobody_elses_does(machine):
    """⭐ owner.json decides. The owner's queue keeps its slug; bob's loses it;
    a swept queue with no owner.json loses it too — unknown is not the owner's."""
    _queue(machine, "alices_topic_20260920_000001", "U_ALICE")
    _queue(machine, "bobs_secret_topic_20260920_000847", "U_BOB")
    (machine["root"] / "backend.log").write_text(
        "Queue: /q/queues/alices_topic_20260920_000001\n"
        "Queue: /q/queues/bobs_secret_topic_20260920_000847\n"
        "Queue: C:\\sr\\queues\\swept_topic_20260919_101010\n", encoding="utf-8")
    _summary, blobs = _build(machine, keep_uid="U_ALICE")
    tail = blobs["system/backend.log"]
    assert b"queues/alices_topic_20260920_000001" in tail
    assert b"bobs_secret_topic" not in tail and b"queues/20260920_000847" in tail
    assert b"swept_topic" not in tail and b"queues\\20260919_101010" in tail


def test_a_uid_known_only_from_a_run_meta_is_scrubbed_in_any_shape(machine):
    """No pattern catches `"U_BOB"` after a key that is not a uid key — the
    run metas are how the builder knows it is a person."""
    _run(machine, "bob_x", "U_BOB", "b\n")
    (machine["root"] / "backend.log").write_text('sharer "U_BOB" listed\n',
                                                 encoding="utf-8")
    _summary, blobs = _build(machine, keep_uid="U_ALICE")
    assert b"U_BOB" not in blobs["system/backend.log"]
    assert b'sharer "member-1" listed' in blobs["system/backend.log"]


def test_a_uid_known_only_from_a_queue_owner_is_scrubbed_in_any_shape(machine):
    _queue(machine, "carols_topic_20260920_010101", "U_CAROL")
    (machine["root"] / "backend.log").write_text('sharer "U_CAROL" listed\n',
                                                 encoding="utf-8")
    _summary, blobs = _build(machine, keep_uid="U_ALICE")
    assert b"U_CAROL" not in blobs["system/backend.log"]


def test_the_count_is_in_the_zip(machine):
    _run(machine, "bob_x", "U_BOB", "b\n")
    _run(machine, "carl_x", "U_CARL", "c\n")
    _summary, blobs = _build(machine, keep_uid="U_ALICE")
    assert json.loads(blobs["collected.json"])["runsOtherMembers"] == 2


# ══ 4. the archive's own mode ══════════════════════════════════════════
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_zip_is_written_0600(machine):
    """Under the ordinary 022 umask the old archive was 0644 — readable by every
    account on the computer."""
    old = os.umask(0o022)
    try:
        dest = machine["tmp"] / "fresh.zip"
        research._build_log_bundle(dest, queues_root=machine["queues"])
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_zip_is_private_from_its_first_byte(machine, monkeypatch):
    """⛔ FOUND BY MUTATION: with the chmod right behind it, creating the file
    0644 looked identical. It is not — anybody who opens the file in that window
    keeps a readable handle after the chmod. So the chmod is taken away here and
    the create mode has to stand on its own."""
    monkeypatch.setattr(research.os, "chmod", lambda *a, **k: None)
    old = os.umask(0o022)
    try:
        dest = machine["tmp"] / "first.zip"
        research._build_log_bundle(dest, queues_root=machine["queues"])
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_an_existing_file_is_narrowed_too(machine):
    """`O_CREAT`'s mode does nothing to a file that already exists."""
    dest = machine["tmp"] / "again.zip"
    dest.write_bytes(b"old")
    os.chmod(dest, 0o644)
    research._build_log_bundle(dest, queues_root=machine["queues"])
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600
    with zipfile.ZipFile(dest) as zf:
        assert "manifest.json" in zf.namelist()


# ══ 5. the redactor, pure ══════════════════════════════════════════════
def test_a_firestore_path_names_member_n_whatever_the_uid_looks_like():
    r = _red()
    assert r.text("users/U_DAVE/researches/x") == "users/member-1/researches/x"
    assert r.text("documents/users%2FU_DAVE%2Fx") == "documents/users%2Fmember-1%2Fx"
    assert r.text("users/U_ALICE/researches/x") == "users/U_ALICE/researches/x"


def test_a_person_key_is_scrubbed_and_a_machine_key_is_not():
    r = _red()
    assert r.text("submittedBy=abcd1234 x") == "submittedBy=member-1 x"
    assert r.text("ownerUid='U_EVE'") == "ownerUid='member-2'"
    assert r.text('"submitterUid": "U_EVE"') == '"submitterUid": "member-2"'
    assert r.text("path_owner=QwErTy12…") == "path_owner=member-3…"
    # not people:
    assert r.text("uid=None ok") == "uid=None ok"
    assert r.text("installUuid=9f8e7d6c5b4a") == "installUuid=9f8e7d6c5b4a"
    # the kept person, whole or as the printed prefix:
    assert r.text("uid=U_ALICE submittedBy=U_ALIC") == "uid=U_ALICE submittedBy=U_ALIC"


def test_a_firebase_shaped_token_is_scrubbed_anywhere():
    r = _red(keep=U28_ALICE)
    out = r.text(f"audio/{U28_BOB}/x.mp3 o/logs%2F{U28_BOB}%2Fd owner {U28_ALICE}")
    assert U28_BOB not in out
    assert out == f"audio/member-1/x.mp3 o/logs%2Fmember-1%2Fd owner {U28_ALICE}"


def test_a_digest_is_not_a_uid():
    """⭐ ACCEPT POLARITY for the shape rule: a 28-character hex string has no
    capitals, and a support log full of `member-N` for commit hashes is noise."""
    r = _red()
    assert r.text(f"sha {HEX28} done") == f"sha {HEX28} done"


def test_a_known_uid_is_scrubbed_in_any_shape():
    r = _red(known=["U_BOB"])
    assert r.text('sharer "U_BOB", again U_BOB') == 'sharer "member-1", again member-1'
    assert r.text("U_BOBBY stays") == "U_BOBBY stays"


def test_one_person_is_one_alias_in_every_shape_and_file():
    """A printed prefix of a known uid is the same person as the uid."""
    r = _red(known=["U_BOB_FULLUID"])
    a = r.text("users/U_BOB_FULLUID/researches/x")
    b = r.text("submittedBy=U_BOB_FU claimed")
    c = r.text("uid=U_FRANK")
    assert a == "users/member-1/researches/x"
    assert b == "submittedBy=member-1 claimed"
    assert c == "uid=member-2"


def test_redacting_twice_changes_nothing_more():
    """An alias is never re-aliased — `users/member-1/` stays itself."""
    r = _red()
    once = r.text("users/U_DAVE/researches/x uid=U_EVE")
    assert r.text(once) == once


def test_topic_fields_are_removed_in_both_shapes():
    r = _red()
    assert (r.text("claimed abc… topic='Bobs secret' submittedBy=U_ALIC")
            == "claimed abc… topic=<topic removed> submittedBy=U_ALIC")
    assert (r.text('check ABSTAINED, topic "it\'s bobs" yields')
            == "check ABSTAINED, topic <topic removed> yields")
    assert (r.text("start: topic=Bobs Secret Topic run_id=20260920_000847")
            == "start: topic=<topic removed> run_id=20260920_000847")
    assert r.text("fields: topic=Bobs Secret\nnext") == "fields: topic=<topic removed>\nnext"
    assert r.text("the off-topic sweep") == "the off-topic sweep"


def test_queue_names_lose_their_topic_unless_owned():
    r = _red(owned=["alices_topic_20260920_000001"])
    assert (r.text("queues/bobs_secret_20260920_000847 run_id=bobs_secret_20260920_000847")
            == "queues/20260920_000847 run_id=20260920_000847")
    assert r.text("queues/alices_topic_20260920_000001") == "queues/alices_topic_20260920_000001"
    assert r.text("popover_20260806_080407_r1.html") == "popover_20260806_080407_r1.html"


def test_no_keep_uid_keeps_nobody():
    r = research._BundleRedactor(None)
    assert r.text("users/U_ALICE/x uid=U_ALICE") == "users/member-1/x uid=member-1"


def test_bytes_nothing_matches_come_back_identical():
    """surrogateescape: a byte that is not UTF-8 must survive untouched."""
    raw = b"plain \xff\xfe line\n\xe2\x9c\x93 ok\n"
    assert _red().data(raw) == raw
    assert _red().data(b"users/U_DAVE/\xff") == b"users/member-1/\xff"


def test_the_queue_dir_owner_map_reads_owner_json(tmp_path):
    (tmp_path / "a_20260920_000001").mkdir()
    (tmp_path / "a_20260920_000001" / "owner.json").write_text(
        json.dumps({"uid": " U1 ", "researchId": "r"}), encoding="utf-8")
    (tmp_path / "no_owner_20260920_000002").mkdir()
    (tmp_path / "bad_20260920_000003").mkdir()
    (tmp_path / "bad_20260920_000003" / "owner.json").write_text("{", encoding="utf-8")
    (tmp_path / "list_20260920_000004").mkdir()
    (tmp_path / "list_20260920_000004" / "owner.json").write_text("[1]", encoding="utf-8")
    assert research._queue_dir_owner_map(tmp_path) == {"a_20260920_000001": "U1"}
    assert research._queue_dir_owner_map(tmp_path / "nope") == {}


# ══ 6. the callers ═════════════════════════════════════════════════════
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
def device(machine, monkeypatch):
    sink = {"_ops": []}
    sink["devices/d-1"] = {"ownerUid": "U_ALICE", "sharedWith": ["U_BOB"]}
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(sink))
    monkeypatch.setattr(research, "_be_payload", lambda d: {**d, "deviceId": "d-1"})
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what=None, **k: op())
    monkeypatch.setattr(research, "WORKER_ID", 1)
    monkeypatch.setattr(research, "_send_logs_cooldown_remaining", lambda *a, **k: 0)
    monkeypatch.setattr(research, "_stamp_send_logs_attempt", lambda *a, **k: None)
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda *a, **k: "logs/x/y/z/bundle.zip")
    # The real builder, pointed at this fixture's queues.
    real = research._build_log_bundle
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: real(dest, queues_root=machine["queues"], **k))

    class _Inline:
        def __init__(self, target=None, **kw):
            self._target = target

        def start(self):
            self._target()
    monkeypatch.setattr(research._log_threading, "Thread", _Inline)
    research._send_logs_inflight = False
    return sink


def test_the_device_handler_keeps_the_owner_and_nobody_else(machine, device):
    """⛔ THE CONSUMER, end to end: the app's Send Logs press, the real builder,
    the real archive. The owner's run ships; bob's does not, anywhere."""
    _run(machine, "alice_x", "U_ALICE", "users/U_ALICE/researches/rA\n")
    _run(machine, "bob_x", "U_BOB", "users/U_BOB/researches/rB\n")
    (machine["root"] / "backend.log").write_text(
        "users/U_ALICE/researches/rA\nusers/U_BOB/researches/rB\n", encoding="utf-8")
    research._handle_send_logs_command(
        {"action": research.SEND_LOGS_ACTION, "code": "7QK4M2XZ",
         "requestId": "req-1", "submittedBy": "U_ALICE", "consent": True},
        "d-1", selected=False)
    dest = machine["root"] / "outgoing" / f"support-7QK4M2XZ{research.BUNDLE_SUFFIX}"
    with zipfile.ZipFile(dest) as zf:
        blobs = {n: zf.read(n) for n in zf.namelist()}
    assert "runs/alice_x/run.log" in blobs, "the owner's own run was left out"
    assert not any(n.startswith("runs/bob_x") for n in blobs)
    assert not any(b"U_BOB" in v for v in blobs.values())
    assert b"users/U_ALICE/researches/rA" in blobs["system/backend.log"]


def test_the_count_never_reaches_the_bundle_row(machine, device):
    """⛔⛔ NOT UNTIL THE RULES ALLOW IT. The row's `hasOnly` refuses an unknown
    key and refuses the whole write with it — the row would stall at
    'collecting'. The count lives in the zip until the rules deploy."""
    _run(machine, "bob_x", "U_BOB", "b\n")
    research._handle_send_logs_command(
        {"action": research.SEND_LOGS_ACTION, "code": "7QK4M2XZ",
         "requestId": "req-1", "submittedBy": "U_ALICE", "consent": True},
        "d-1", selected=False)
    writes = [op for op in device["_ops"] if "logBundles" in op[1]]
    assert writes, "no row was written — this proves nothing"
    assert any(op[2].get("status") == "done" for op in writes)
    for _kind, _path, payload in writes:
        assert "runsOtherMembers" not in payload


def test_the_terminal_keeps_the_paired_uid(monkeypatch, capsys):
    """`--send-logs` has no Firestore to ask who owns the device; the paired uid
    in this machine's config is what it has. And it SAYS what it left out."""
    seen, rows = {}, []

    def _build(dest, **k):
        seen.update(k)
        return {"path": dest, "sizeBytes": 1, "runCount": 1, "sessionCount": 0,
                "maxRunsApplied": 30, "uncompressedBytes": 1,
                "droppedForSize": [], "sourcesRefused": [], "runsOtherMembers": 2}

    monkeypatch.setattr(research, "_build_log_bundle", _build)
    monkeypatch.setattr(research, "load_paired_uid", lambda: "U_PAIRED")
    monkeypatch.setattr(research, "load_device_id", lambda: "d-1")
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok")
    monkeypatch.setattr(research, "_decode_jwt_claims",
                        lambda t: {"ownerUid": "U_PAIRED", "deviceId": "d-1"})
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest",
                        lambda p, o, d, c: f"logs/{o}/{d}/{c}/bundle.zip")
    monkeypatch.setattr(research, "_open_log_bundle_row", lambda *a, **k: True)
    monkeypatch.setattr(research, "_write_log_bundle_status",
                        lambda o, c, patch, create=False: rows.append(patch) or True)
    research.cmd_send_logs(assume_yes=True)
    assert seen["keep_uid"] == "U_PAIRED"
    assert "2 run(s) left out — another member ran them" in capsys.readouterr().out
    assert rows and all("runsOtherMembers" not in p for p in rows)
