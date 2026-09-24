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
import ast
import builtins
import json
import os
import re
import stat
import time
import zipfile
from pathlib import Path

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


def _spy_on_chunks(monkeypatch):
    """(pieces per call, the real cutter) — how many pieces the redactor
    actually asked the cutter for.

    ⛔ THE CONSUMER, NOT THE HELPER. `_bundle_line_chunks` was pinned directly
    while `text()` was free to stop calling it, and `pieces = [s]` then passed
    every test in this file. The real cutter comes back too, so an expectation
    can be computed without the spy counting its own call."""
    real = research._bundle_line_chunks
    seen = []

    def _counted(*a, **k):
        out = real(*a, **k)
        seen.append(len(out))
        return out

    monkeypatch.setattr(research, "_bundle_line_chunks", _counted)
    return seen, real


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


def test_an_unpaired_machines_unattributed_run_is_still_redacted(machine):
    """⛔⛔ `keep_uid=None` KEEPS NOBODY, AT THE BUILDER, NOT ONLY IN THE
    REDACTOR. That rule was tested on the pure redactor and on ATTRIBUTED runs,
    and the one line that carries it for unattributed folders — `own_uid and
    row.get("submitterUid") == own_uid` — had nothing on it. Drop the `own_uid
    and` guard and `None == None` marks every unattributed folder as the kept
    person's own, so it ships byte for byte: that is the terminal's
    `--send-logs` on an unpaired machine, where every fleet run is unattributed.
    Measured: the mutant passed 353 tests across eight bundle suites.

    ⭐ ACCEPT POLARITY is `test_the_owners_own_run_ships_byte_for_byte` next
    door: a folder with a uid that matches still ships whole, so "redact
    everything" is not what makes this pass."""
    _run(machine, "legacy_x", None,
         "Firestore bridge active: users/U_BOB/researches/rB\n"
         "Queue: /srv/queues/bobs_secret_topic_20260920_000847\n")
    summary, blobs = _build(machine, keep_uid=None)
    log = blobs["runs/legacy_x/run.log"]
    assert b"U_BOB" not in log, "an unattributed run shipped a member verbatim"
    assert b"bobs_secret_topic" not in log
    assert b"users/member-1/researches/rB" in log
    assert summary["runCount"] == 1, "the run itself must still be collected"
    assert "runs/legacy_x/run.log" in json.loads(blobs["collected.json"])["filesRedacted"]


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
    """⭐ A QUOTED VALUE KEEPS ITS QUOTES — the line was `topic=<topic removed>`
    until a JSON run.log proved that a string replaced by a bare token leaves
    the reader of the archive holding a file that no longer parses."""
    r = _red()
    assert (r.text("claimed abc… topic='Bobs secret' submittedBy=U_ALIC")
            == "claimed abc… topic='<topic removed>' submittedBy=U_ALIC")
    assert (r.text('check ABSTAINED, topic "it\'s bobs" yields')
            == 'check ABSTAINED, topic "<topic removed>" yields')
    assert (r.text("start: topic=Bobs Secret Topic run_id=20260920_000847")
            == "start: topic=<topic removed> run_id=20260920_000847")
    assert r.text("fields: topic=Bobs Secret\nnext") == "fields: topic=<topic removed>\nnext"
    assert r.text("the off-topic sweep") == "the off-topic sweep"


def test_a_topic_in_json_repr_or_after_a_colon_is_removed_too():
    """⛔⛔ THE REDACTOR KNEW `topic=` AND `topic '…'` AND NOTHING ELSE. An
    unattributed run.log — every fleet run until the attributing wheel ships —
    carries the subject as JSON, as a Python repr and after a plain colon, and
    all three went to support verbatim. EXECUTED against a real bundle in
    `test_no_other_members_uid_or_topic_in_any_bundle_member` as well.

    ⭐ The JSON and the repr must still PARSE afterwards, so the rewritten value
    is round-tripped through `json.loads` / `ast.literal_eval` here rather than
    compared as text."""
    r = _red()
    out = r.text('{"topic": "Bobs divorce shortlist", "uid": "U_ALICE"}')
    assert json.loads(out) == {"topic": "<topic removed>", "uid": "U_ALICE"}
    out = r.text("{'topic': 'Bobs divorce shortlist'}")
    assert ast.literal_eval(out) == {"topic": "<topic removed>"}
    assert r.text("Topic: Bobs divorce shortlist") == "Topic:<topic removed>"
    assert r.text("topic: Bobs divorce shortlist\nnext") == "topic:<topic removed>\nnext"
    # ⭐ ACCEPT POLARITY: a word that merely ends in "topic", and a key that only
    # looks like one, are not somebody's subject.
    assert r.text("the off-topic sweep: fine") == "the off-topic sweep: fine"
    assert r.text('{"topics": 3}') == '{"topics": 3}'
    assert r.text("topical: yes") == "topical: yes"


def test_the_topic_bearing_log_lines_lose_their_subject():
    """⛔⛔ THE LINES THIS PROGRAM ITSELF WROTE, with no key to find them by.
    `backend.log` is the machine's, so every member's pickups are in the owner's
    copy, and the tail ships. Measured on a real owner bundle: 9 of 9
    `Starting queued job` topics, 1 of 1 orphan lines and 5 of 5 notebook
    renames survived the redactor.

    ⭐ THE LINES THE FIX NOW WRITES MUST SURVIVE IT, which is why they are here
    too: they are deliberately not of these shapes, so the research id they
    carry instead is still readable in a bundle."""
    r = _red()
    assert (r.text("[00:08:47] [INFO] Starting queued job: Bobs divorce shortlist")
            == "[00:08:47] [INFO] Starting queued job: <topic removed>")
    assert (r.text("[idle-rescan] worker 1: picking up orphan rB123456… "
                   "(Bobs divorce shortlist) submittedBy=U_ALIC")
            == "[idle-rescan] worker 1: picking up orphan rB123456… "
               "(<topic removed>) submittedBy=U_ALIC")
    assert (r.text("Renaming notebook to 'Bobs Divorce Shortlist'...")
            == "Renaming notebook to <topic removed>")
    assert (r.text("[nlm] DOM rename OK (read-back verified): 'Bobs Divorce'")
            == "[nlm] DOM rename OK (read-back verified): <topic removed>")
    for now_written in (
            f"Starting queued job {research._log_job_ref({'research_id': 'rB1234567'})}",
            "[idle-rescan] worker 1: picking up orphan rB123456… submittedBy=U_ALIC",
            "Renaming notebook (smart title, 47 chars)...",
            "[nlm] DOM rename OK (read-back verified, 47 chars)"):
        assert research._BUNDLE_TOPIC_MARK not in r.text(now_written), now_written


def test_a_uid_with_no_digit_is_still_uid_shaped():
    """⛔ About one Firebase uid in a hundred and fifty has no digit, and the
    shape rule demanded one. A member whose run folders and queues have aged out
    is known to the redactor by shape and by nothing else, so theirs shipped.

    ⭐ ACCEPT POLARITY is `test_a_digest_is_not_a_uid` next door: the two CASES
    are what keep a digest out, and they still do."""
    no_digit = "bObXyZqrstuvWXYZabcdefghIJKL"
    assert len(no_digit) == 28
    r = _red(keep=U28_ALICE)
    assert (r.text(f"audio/{no_digit}/rX/pod.mp3")
            == "audio/member-1/rX/pod.mp3")
    assert r.text(f"sharedWith=['{no_digit}']") == "sharedWith=['member-1']"


def test_the_owner_of_a_digit_less_uid_is_still_kept():
    """⭐ ACCEPT POLARITY for the widened shape: widening it must not start
    aliasing the KEPT person, whose uid has no digit either."""
    no_digit = "bObXyZqrstuvWXYZabcdefghIJKL"
    r = _red(keep=no_digit)
    assert r.text(f"audio/{no_digit}/rX.mp3") == f"audio/{no_digit}/rX.mp3"


def test_a_machine_log_line_names_the_research_never_the_topic():
    """⛔⛔ THE LINE THAT NEVER CARRIES IT CANNOT LEAK IT. `backend.log` is the
    machine's, so every member's pickups land in the owner's copy and the tail
    ships in the owner's bundle; the redactor above is the backstop for the
    fourteen days of lines already on disk, not the fix.

    ⛔ `run_id` AND `resume_dir` ARE `safe_name(topic)_<stamp>`, so printing
    either whole would put the subject back in a different spelling. Only the
    stamp may go."""
    ref = research._log_job_ref
    assert ref({"research_id": "rB12345678", "topic": "Bobs divorce"}) == "rB123456…"
    # no research id: the queue's stamp, never its slug
    assert ref({"run_id": "bobs_divorce_20260920_000847",
                "topic": "Bobs divorce"}) == "queue 20260920_000847"
    assert ref({"resume_dir": "/srv/queues/bobs_divorce_20260920_000847",
                "topic": "Bobs divorce"}) == "queue 20260920_000847"
    # nothing to name is said as nothing, not guessed at
    assert ref({"topic": "Bobs divorce"}) == "?"
    assert ref({"research_id": "  ", "run_id": "no_stamp_here"}) == "?"
    assert ref(None) == "?" and ref("bobs divorce") == "?"
    for job in ({"research_id": "rB12345678", "topic": "Bobs divorce"},
                {"run_id": "bobs_divorce_20260920_000847", "topic": "Bobs divorce"},
                {"resume_dir": "/q/bobs_divorce_20260920_000847"},
                {"topic": "Bobs divorce"}):
        assert "bobs" not in ref(job).lower() and "divorce" not in ref(job).lower()


def test_the_sidebar_and_title_refresh_lines_lose_their_subject():
    """⛔⛔ THE FIRST PASS KNEW FOUR SHAPES AND THERE WERE NINE. Measured
    2026-09-22 against this owner's LIVE `backend.log`: 148 characters of
    another member's research subject survived in the shipped tail — the Gemini
    sidebar-adoption recovery names the chat it opens, the title-refresh refusal
    names the title it threw away, and both of those and the off-topic
    diagnostics print the topic's own distinctive words. None of them has a
    `topic=` key, so nothing in the first pass could see them.

    ⭐ The sources no longer write any of this (below), and the rule is here
    anyway for the same reason the first four are: a tail is fourteen days deep.
    """
    r = _red()
    cases = [
        ("[Gemini] top recent sidebar chats ['Bobs divorce shortlist', 'Bob v Bob']"
         " do NOT match our brief — not adopting (won't hijack a past run)",
         "[Gemini] top recent sidebar chats [<topic removed>] do NOT match our "
         "brief — not adopting (won't hijack a past run)"),
        ("[Gemini] opening owned sidebar chat 'Bobs divorce shortlist' (1/2) "
         "from the sidebar",
         "[Gemini] opening owned sidebar chat '<topic removed>' (1/2) from the sidebar"),
        ("[Gemini] sidebar entry 'Bobs divorce shortlist' vanished before open"
         " — trying next",
         "[Gemini] sidebar entry '<topic removed>' vanished before open — trying next"),
        ("[title-refresh] REFUSING the generated title 'Bobs Divorce Shortlist' "
         "— it shares none of the topic's distinctive terms (divorce, lawyer, "
         "custody), AND neither does the corpus it was written from.",
         "[title-refresh] REFUSING the generated title '<topic removed>' — it "
         "shares none of the topic's distinctive terms (<topic removed>), AND "
         "neither does the corpus it was written from."),
        ("[chatgpt] OFF-TOPIC text REJECTED at save: 900 chars mention none of "
         "the topic's distinctive terms (divorce, lawyer, custody) — this is "
         "not this run's research. Not saving it.",
         "[chatgpt] OFF-TOPIC text REJECTED at save: 900 chars mention none of "
         "the topic's distinctive terms (<topic removed>) — this is not this "
         "run's research. Not saving it."),
        ("[Phase 2] off-topic sweep is INERT this run: topic 'bobs divorce' "
         "yields 2 distinctive word(s) (divorce, bobs), below the 3 needed",
         "[Phase 2] off-topic sweep is INERT this run: topic '<topic removed>' "
         "yields 2 distinctive word(s) (<topic removed>), below the 3 needed"),
    ]
    for raw, want in cases:
        assert r.text(raw) == want, raw
    # ⛔ NOTHING ESCAPES THESE VALUES — they are interpolated straight into an
    # f-string — so a title with an apostrophe in it closes its own quoted value
    # for any `[^']*` rule and ships the rest, and a list entry with a bracket
    # does the same. Both are ordinary research titles.
    assert (r.text("[Gemini] opening owned sidebar chat 'Bob's divorce shortlist' "
                   "(1/2) from the sidebar")
            == "[Gemini] opening owned sidebar chat '<topic removed>' (1/2) "
               "from the sidebar")
    assert (r.text("[Gemini] top recent sidebar chats ['Bobs [2026] divorce'] do NOT")
            == "[Gemini] top recent sidebar chats [<topic removed>] do NOT")
    # ⭐ ACCEPT POLARITY. The lines the sources now write keep everything they
    # are read for — the counts, and the sentence around the bracket. The three
    # sidebar lines name nothing at all any more, so nothing is taken from them.
    for now_written in (
            "[Gemini] top 2 recent sidebar chat(s) ([31, 9] chars) do NOT match our brief",
            "[Gemini] opening owned sidebar chat #1/2 (31 chars) from the sidebar",
            "[Gemini] sidebar entry #1 (31 chars) vanished before open — trying next"):
        assert r.text(now_written) == now_written, now_written
    assert (r.text("[title-refresh] REFUSING the generated title (22 chars) — it "
                   "shares none of the topic's distinctive terms (divorce, lawyer), "
                   "AND neither does the corpus it was written from.")
            == "[title-refresh] REFUSING the generated title (22 chars) — it "
               "shares none of the topic's distinctive terms (<topic removed>), "
               "AND neither does the corpus it was written from.")


def test_a_subject_with_an_equals_sign_in_it_keeps_none_of_its_tail():
    """⛔⛔ THE VALUE ENDED AT THE FIRST `word=` INSIDE IT. `Firestore start:
    uid=… topic=why E=mc2 changed physics run_id=…` stopped the topic at `E=`
    and shipped `mc2 changed physics`. A subject written with an equals sign —
    a formula, a config key, `does p=np matter` — is all it takes."""
    r = _red()
    assert (r.text("Firestore start: uid=U_BOB topic=why E=mc2 changed physics "
                   "run_id=bobs_20260101_010101")
            == "Firestore start: uid=member-1 topic=<topic removed> "
               "run_id=20260101_010101")
    assert (r.text("topic=does p=np matter for crypto\nnext")
            == "topic=<topic removed>\nnext")
    # ⭐ ACCEPT POLARITY: the run id a reader follows the line by is still there,
    # and a key that is not one of the known enders now costs that key rather
    # than ending the subject early — the safe direction.
    assert "run_id=20260101_010101" in r.text(
        "topic=why E=mc2 changed physics run_id=bobs_20260101_010101")
    assert (r.text("topic=bobs divorce elapsed=12s")
            == "topic=<topic removed>")


def test_the_possessive_in_the_topics_is_not_an_opening_quote():
    """⛔⛔ THE BARE `topic` ALTERNATIVE READ `topic's` AS A QUOTED VALUE and
    deleted the line from that apostrophe to the next one. Ninety characters of
    the off-topic diagnostic went, and whether a line survived depended only on
    whether a second apostrophe happened to sit on it — which is also what made
    the anchors above LOOK redacted while nothing had decided they should be."""
    r = _red()
    # The real line, both halves at once: the words in the bracket go, and the
    # ninety characters of sentence after them stay. Before the fix this came
    # back as `…mentions NONE of the topic'<topic removed>'s research`.
    assert (r.text("Phase 1: the brief (900 chars) mentions NONE of the topic's "
                   "distinctive terms (divorce, lawyer, custody) — this is not a "
                   "brief for this run's research")
            == "Phase 1: the brief (900 chars) mentions NONE of the topic's "
               "distinctive terms (<topic removed>) — this is not a "
               "brief for this run's research")
    assert r.text("nothing here matched the topic's shape at all") == \
        "nothing here matched the topic's shape at all"
    # ⭐ ACCEPT POLARITY: the shape the alternative exists for — a bare `topic`
    # then a SPACE then a quoted value — is still removed.
    assert (r.text("brief topic check ABSTAINED — topic 'bobs divorce' yields 2")
            == "brief topic check ABSTAINED — topic '<topic removed>' yields 2")
    assert (r.text('sweep INERT: topic "bobs divorce" yields 2')
            == 'sweep INERT: topic "<topic removed>" yields 2')


# ══ 5c. every log line that names a subject, derived from the source ═══
#
# ⛔⛔ A RULE-SHAPED RE-CHECK CANNOT FIND THE NEXT ONE. The first pass closed
# four shapes and re-checked its work by re-applying its own rules, which can
# only see shapes the rules already know; five more were sitting in this
# owner's live `backend.log` the whole time. So this does not ask "do the rules
# still match the lines I thought of" — it asks the SOURCE which lines exist.
#
# Every `log(f"…")` in research.py that interpolates a research subject is
# rendered with a sentinel in place of that subject, written into a real
# machine tail, and put through the REAL builder. Nothing may come out.
_SUBJECT = "ZqSubjectZq"
_NEUTRAL = "x"
#: A variable whose NAME says subject…
_SUBJECT_NAME_RE = re.compile(r"(?i)(title|topic|anchor)")
#: …a dict key that fetches one…
_SUBJECT_KEY = frozenset({"topic", "title"})
#: …and a variable ASSIGNED from a function that returns one, which is how the
#: title-refresh lines' `text` and the sweep's `_t` / `_a` are subjects without
#: saying so in their names.
_SUBJECT_CALLS = frozenset({"topic_anchors", "smart_title", "_shape_title",
                            "_try_llm_title", "_run_topic_for_guard"})
#: ⛔ THE ONLY WAY PAST THIS TEST, and each one is a claim a reviewer can check:
#: the name says subject and the value is not one. Keyed by a literal from the
#: line itself, and every row must still match a line (below), so a row left
#: behind by an edit is a failure rather than a hole.
_NOT_A_SUBJECT = {
    "fail_agent suppressed": "`title` is the alert card's own title",
    "off-topic sweep rejected": "`_off_topic` is a list of agent keys",
}


class _Ghost:
    """A stand-in for anything a log line interpolates, carrying one word.

    ⛔⛔ A SLICE OF IT IS STILL THE WHOLE WORD. It used to return the sliced
    STRING, so `', '.join(anchors[:6])` rendered as `Z, q, S, u, b, j` — the
    sentinel cut into letters, and every anchor-list line passed this test
    without ever carrying a subject. The mutant that put the words back in a
    spelling the bundle cannot see survived because of it."""

    def __init__(self, word, subjects=frozenset()):
        self._w = word
        self._s = subjects

    def __getitem__(self, k):
        return self

    def __iter__(self):
        return iter([self._w, self._w, self._w])

    def __len__(self):
        return len(self._w)

    def __str__(self):
        return self._w

    def __repr__(self):
        return repr(self._w)

    def __format__(self, spec):
        return format(self._w, spec) if spec else self._w

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return _Ghost(_SUBJECT if name in self._s else self._w, self._s)

    def __call__(self, *a, **k):
        if any(isinstance(x, str) and x in self._s for x in a):
            return _Ghost(_SUBJECT, self._s)
        return self

    def __bool__(self):
        return True

    def __or__(self, other):
        return self

    def __ror__(self, other):
        return self

    def __add__(self, other):
        return self._w + str(other)

    def __radd__(self, other):
        return str(other) + self._w

    def __hash__(self):
        return hash(self._w)


class _GhostNs(dict):
    """The namespace a line is rendered in: real builtins, ghosts for the rest."""

    def __init__(self, subjects):
        super().__init__()
        self._subjects = subjects

    def __missing__(self, name):
        if name not in self._subjects and hasattr(builtins, name):
            return getattr(builtins, name)
        g = _Ghost(_SUBJECT if name in self._subjects else _NEUTRAL, self._subjects)
        self[name] = g
        return g


def _names_in(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Constant) and n.value in _SUBJECT_KEY:
            out.add(str(n.value))
    return out


def _subjects_assigned_in(scope, body_only=False):
    out = set()
    nodes = scope.body if body_only else list(ast.walk(scope))
    for node in nodes:
        targets = getattr(node, "targets", None) or (
            [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else [])
        value = getattr(node, "value", None)
        if not targets or not isinstance(value, ast.Call):
            continue
        fn = value.func
        fn = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if fn in _SUBJECT_CALLS:
            out |= {t.id for t in targets if isinstance(t, ast.Name)}
    return out


def _render_log_line(joined, subjects):
    """One `log(f"…")` argument, rendered with the subjects replaced."""
    ns = _GhostNs(subjects)
    try:
        return eval(compile(ast.Expression(joined), "<log>", "eval"), ns, ns)
    except Exception:
        pass  # an expression no ghost can stand in for — render it textually
    out = []
    for part in joined.values:
        if isinstance(part, ast.Constant):
            out.append(str(part.value))
        elif isinstance(part, ast.FormattedValue):
            e = part.value
            if (isinstance(e, ast.Call) and isinstance(e.func, ast.Name)
                    and e.func.id == "len"):
                out.append("12")
            else:
                out.append(_SUBJECT if _names_in(e) & subjects else _NEUTRAL)
    return "".join(out)


def _subject_log_lines():
    """Every log line in research.py that puts a research subject in it.

    Derived from the source, never from a list kept by hand — a list kept by
    hand is what left five of these shipping."""
    tree = ast.parse(Path(research.__file__).read_text(encoding="utf-8"))
    scopes = [(tree, True)] + [(n, False) for n in ast.walk(tree)
                               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    found: "dict[int, tuple]" = {}
    for scope, body_only in scopes:
        assigned = _subjects_assigned_in(scope, body_only)
        for node in ast.walk(scope):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "log" and node.args):
                continue
            arg = node.args[0]
            if not isinstance(arg, ast.JoinedStr):
                continue
            subs = set()
            for part in arg.values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                for name in _names_in(part.value):
                    # An ALL-CAPS name is a module constant, never a subject.
                    if not name.isupper() and (name in assigned
                                               or _SUBJECT_NAME_RE.search(name)):
                        subs.add(name)
            if subs:
                prev = found.get(node.lineno, (arg, set()))[1]
                found[node.lineno] = (arg, prev | subs)
    return {lineno: _render_log_line(arg, subs)
            for lineno, (arg, subs) in found.items()}


def test_no_log_line_that_names_a_subject_survives_the_bundle(machine):
    """⛔⛔ EVERY LINE THIS PROGRAM WRITES WITH A SUBJECT IN IT, asked of the
    source and put through the real builder. Measured 2026-09-22 against this
    owner's live `backend.log`: the first pass left 148 characters of another
    member's research subject in the tail that ships — `opening owned sidebar
    chat '…'`, `REFUSING the generated title '…'` and the topic's own
    distinctive words — because it re-checked its fix with the rules the fix had
    written. This asks a different question: whatever the sources say today,
    none of it may reach support.

    ⭐ A line passes either way it can be safe — by not writing the subject at
    all (the counts the sources now print) or by writing it behind a key the
    redactor finds. The two exemptions are named above and checked below."""
    lines = _subject_log_lines()
    assert len(lines) > 20, "the derivation found nothing — it is measuring nothing"
    exempt, corpus = {}, []
    for lineno, rendered in sorted(lines.items()):
        one = " ".join(rendered.split())
        hit = next((k for k in _NOT_A_SUBJECT if k in one), None)
        if hit:
            exempt[hit] = lineno
            continue
        corpus.append(f"[00:08:47] [WARN] {one}")
    # ⭐ ACCEPT POLARITY, and it is the whole test: the corpus really does carry
    # the sentinel, on more than a handful of lines, so "nothing was rendered"
    # cannot be what makes this pass.
    carriers = [ln for ln in corpus if _SUBJECT in ln]
    assert len(carriers) >= 15, f"only {len(carriers)} lines carried a subject"
    (machine["root"] / "backend.log").write_text("\n".join(corpus) + "\n",
                                                 encoding="utf-8")
    _summary, blobs = _build(machine, keep_uid="U_ALICE")
    tail = blobs["system/backend.log"].decode("utf-8", "surrogateescape")
    survivors = [ln for ln in tail.splitlines() if _SUBJECT in ln]
    assert not survivors, "a research subject reached the bundle:\n" + "\n".join(survivors)
    # ⭐ AND THE LINES REALLY SHIPPED — a tail that dropped them would be green
    # for the wrong reason.
    assert len(tail.splitlines()) == len(corpus)
    assert research._BUNDLE_TOPIC_MARK in tail
    assert sorted(exempt) == sorted(_NOT_A_SUBJECT), (
        "a row in _NOT_A_SUBJECT matches no line any more: " + str(exempt))


# ══ 5b. the redactor, chunked ══════════════════════════════════════════
def _corpus(reps):
    u_bob = U28_BOB
    u_carol = "ZzYyXxWwVvUuTtSsRrQqPpOoNnMm"
    lines = [
        # ⛔ CAROL FIRST AND ONLY SHAPE-MATCHED, BOB SECOND AND PATH-MATCHED, and
        # that order is the whole point: the users/ pass runs before the shape
        # pass, so whole-string numbering gives bob member-1 even though carol
        # appears first. A redactor that finished each piece before starting the
        # next would number them the other way round.
        f"[audio] audio/{u_carol}/rX/pod.mp3 sharedWith=['{u_carol}']\n",
        f"[fs] write users/{u_bob}/researches/chat_178 ownerUid='{u_bob}'\n",
        "Starting queued job: somebody's private subject\n",
        "[idle-rescan] worker 1: picking up orphan rB123456… (a subject) submittedBy=B0bXyzAA\n",
        '{"topic": "a private subject", "uid": "' + u_bob + '"}\n',
        "queues/some_slug_20260920_000847 run_id=some_slug_20260920_000847\n",
        "[cua] screenshot 1280x800 action=left_click (640, 400) step 17/40\n",
    ]
    return "".join(lines) * reps


@pytest.mark.parametrize("tail", ["\n", ""])
@pytest.mark.parametrize("reps", [1, 7, 61])
@pytest.mark.parametrize("size", [1, 64, 4096])
def test_a_chunked_redaction_is_the_whole_string_one(monkeypatch, reps, size, tail):
    """⛔⛔ CHUNKING HAS TO BE INVISIBLE, and the thing that could make it visible
    is not a cut uid — it is the ALIAS NUMBERING. `member-N` is handed out on
    first appearance, so running every pass over piece 1 before piece 2 would
    number the same two people differently. Pass first, piece second is what
    keeps the output equal, and this is what says so: the same corpus through a
    one-piece redactor and through a many-piece one, output AND alias map.

    ⛔⛔ AND IT MUST PROVE THE CUT HAPPENED. Comparing a chunked run to a whole
    one is green when there is NO chunking — both sides take the identical path
    — so `pieces = [s]` survived this test, and the helper next door pinned the
    helper, not its consumer. The spy is what makes the comparison mean
    something: the consumer has to have asked for the pieces it was given."""
    text = _corpus(reps).rstrip("\n") + tail
    seen, cut = _spy_on_chunks(monkeypatch)
    monkeypatch.setattr(research, "_BUNDLE_REDACT_CHUNK", 1 << 30)
    whole = _red(keep=U28_ALICE, known=[U28_BOB])
    expected = whole.text(text)
    assert seen == [1], "the whole-string run must still go through the cutter"
    monkeypatch.setattr(research, "_BUNDLE_REDACT_CHUNK", size)
    pieced = _red(keep=U28_ALICE, known=[U28_BOB])
    assert pieced.text(text) == expected
    assert pieced.aliases == whole.aliases
    # ⭐ The consumer cut this text itself, into exactly what the helper gives
    # for this size — not into one piece because there is no chunking left.
    assert seen == [1, len(cut(text, size))]
    # ⭐ ACCEPT POLARITY: the corpus really does carry two members and a topic,
    # so "both came out empty" cannot be what made this pass. And bob is
    # member-1 although carol's line comes first — that ordering is what a
    # piece-at-a-time redactor would get wrong.
    assert "member-1" in expected and "member-2" in expected
    assert whole.aliases[U28_BOB] == "member-1"
    assert research._BUNDLE_TOPIC_MARK in expected
    assert U28_BOB not in expected


def test_the_shipped_chunk_size_really_cuts_a_real_tail(monkeypatch):
    """⛔⛔ THE CONSTANT IS HALF THE FIX AND NOTHING WATCHED IT. Raise
    `_BUNDLE_REDACT_CHUNK` past any real log and the chunking is inert while
    every test that monkeypatches it stays green — and the stall is back: one
    `re.sub` over a capped 32 MB run.log holds the GIL for its whole run, eight
    passes deep, on a daemon thread beside the asyncio loop driving a live
    pipeline. No monkeypatch here: the SHIPPED size has to cut a text the size
    of a tail that really ships."""
    assert research._BUNDLE_REDACT_CHUNK < research.BUNDLE_MAX_BYTES
    seen, _cut = _spy_on_chunks(monkeypatch)
    line = "[00:08:47] [INFO] health probe ok, nothing to see here\n"
    text = (line * (research._BUNDLE_REDACT_CHUNK // len(line) + 8)
            + "Starting queued job: somebody's private subject\n")
    assert len(text) > research._BUNDLE_REDACT_CHUNK
    out = _red(keep=U28_ALICE).text(text)
    assert seen and seen[0] > 1, "the shipped chunk size cut nothing"
    # ⭐ ACCEPT POLARITY: cutting it did not cost the redaction or the text.
    assert research._BUNDLE_TOPIC_MARK in out
    assert "private subject" not in out and out.count(line) == text.count(line)


def test_a_chunk_never_ends_mid_line():
    """⛔ A cut anywhere but after a newline splits a uid in half and ships both
    halves. Every piece but the last has to end on `\\n`, and they have to
    rejoin into exactly what came in."""
    text = _corpus(40)
    pieces = research._bundle_line_chunks(text, 50)
    assert len(pieces) > 5, "one piece proves nothing about cutting"
    assert "".join(pieces) == text
    for piece in pieces[:-1]:
        assert piece.endswith("\n")
    assert research._bundle_line_chunks("no trailing newline", 4)[-1] == "no trailing newline"
    assert research._bundle_line_chunks("short", 1000) == ["short"]


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


def test_the_count_reaches_the_DONE_row_and_no_other(machine, device):
    """⛔ FLIPPED, wave 10.9 (W9). This pinned the count OFF the row, because the
    row's `hasOnly` refused the key and refused the whole write with it. The
    rules now name it, so the person who pressed Send is told that another
    member's run was left out — as a count, on the `done` write only, which is
    the one beside "Sent". The earlier writes stay as they were."""
    _run(machine, "bob_x", "U_BOB", "b\n")
    research._handle_send_logs_command(
        {"action": research.SEND_LOGS_ACTION, "code": "7QK4M2XZ",
         "requestId": "req-1", "submittedBy": "U_ALICE", "consent": True},
        "d-1", selected=False)
    writes = [op for op in device["_ops"] if "logBundles" in op[1]]
    assert writes, "no row was written — this proves nothing"
    done = [p for _k, _p, p in writes if p.get("status") == "done"]
    assert len(done) == 1 and done[0]["runsOtherMembers"] == 1
    for _kind, _path, payload in writes:
        if payload.get("status") != "done":
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
    # ⛔ FLIPPED, wave 10.9 (W9): the terminal's `done` row carries the count too,
    # so a bundle sent from the terminal says the same on the web as it printed.
    assert rows and rows[-1]["status"] == "done" and rows[-1]["runsOtherMembers"] == 2


def test_an_unpaired_terminal_does_not_blame_a_member(monkeypatch, capsys):
    """⛔⛔ THE SENTENCE WAS FALSE ON THE MACHINE MOST LIKELY TO PRINT IT.
    `--send-logs` is what somebody runs when their computer is in trouble, which
    is exactly when the pairing may be gone — and the runs it then leaves out
    are the person's OWN, on a computer that may have no other member at all.
    Measured through this same command: "0 run(s)" and "2 run(s) left out —
    another member ran them", with both runs the owner's.

    ⭐ The omission itself is right and is NOT changed here: an unpaired machine
    cannot prove whose any folder is."""
    seen = {}

    def _build(dest, **k):
        seen.update(k)
        return {"path": dest, "sizeBytes": 1, "runCount": 0, "sessionCount": 0,
                "maxRunsApplied": 30, "uncompressedBytes": 1,
                "droppedForSize": [], "sourcesRefused": [], "runsOtherMembers": 2}

    monkeypatch.setattr(research, "_build_log_bundle", _build)
    monkeypatch.setattr(research, "load_paired_uid", lambda: None)
    monkeypatch.setattr(research, "load_device_id", lambda: None)
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
    monkeypatch.setattr(research, "_post_bundle_to_ingest", lambda *a, **k: None)
    research.cmd_send_logs(assume_yes=True)
    out = capsys.readouterr().out
    assert seen["keep_uid"] is None, "the builder must still keep nobody"
    assert "another member ran them" not in out
    assert "2 run(s) left out" in out and "not paired" in out


def test_the_left_out_line_is_the_count_and_who_it_blames():
    """The decision the two tests above drive, executed directly — including the
    zero case, where a bundle that left nothing out must say nothing."""
    say = research._send_logs_left_out_line
    assert say(0, "U_PAIRED") == "" and say(None, None) == "" and say(0, None) == ""
    assert "another member ran them" in say(2, "U_PAIRED")
    assert "another member" not in say(2, None)
    assert "2 run(s) left out" in say(2, None) and "2 run(s) left out" in say(2, "U")
    # An empty-string uid is no uid: `load_paired_uid` strips before returning.
    assert "another member" not in say(1, "")
