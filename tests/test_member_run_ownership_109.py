"""A member of a shared computer can no longer resume or cancel another
member's run.

⛔⛔ WHAT WAVE 10.8 LEFT OPEN. Round three corroborated that a run belongs to
the RESEARCH it is named for, and never that the research belongs to the PERSON
asking. Research ids are not secret — `queueOwners` publishes them to every
member — and the rules let a member create a research document under any id in
their own tree. So a member who signed honestly as themselves could:

  · RESUME another member's run into their own tree. The payload's run id, the
    research document's run id and the disk lookup all matched on researchId
    alone; the resume then cleared the victim's `.pause` and `.no_auto_retry`,
    merged the sender's config into the victim's config.json, and enqueued the
    remaining phases — built from the victim's material — under the sender.
  · CANCEL another member's QUEUED run. A deferred run is held by no worker, so
    the local ownership gate saw nothing, and the deferred scan deleted the
    first start doc whose researchId matched. The status write landed in the
    sender's tree, so the victim's tile sat on "queued" with nothing behind it.

⭐ EVERY PIN HERE EXECUTES THE DECISION, and the consumer pins execute the REAL
listener callback (`_queue_listener.Listener`) — never a copy of the branch and
never its parse tree. Each refusal comes with its accept-polarity twin, because
"refuse everything" would pass a refusal pin and take the product away.
"""
import asyncio
import json

import pytest

import research
from _queue_listener import Listener

OWNER = "uid-owner"      # the device owner (paired)
ALICE = "uid-alice"      # a member whose run is at stake
BOB = "uid-bob"          # another member, naming Alice's research id
RID = "chat_1758400000000_1"
BOB_RID = "chat_1758400000000_9"   # Bob's own research, minted in his own tree
RUN = "Alice_topic_20260921_101500"


def _run_dir(tmp_path, run=RUN, owner=None):
    d = tmp_path / "queues" / run
    d.mkdir(parents=True, exist_ok=True)
    if owner is not None:
        (d / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
    return d


@pytest.fixture
def alices_run(tmp_path, monkeypatch):
    """Alice's paused run on disk, with every marker a foreign resume clears."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    d = _run_dir(tmp_path, owner={"uid": ALICE, "researchId": RID})
    (d / ".pause").write_text("", encoding="utf-8")
    (d / research.NO_AUTO_RETRY_MARKER).write_text("", encoding="utf-8")
    (d / "config.json").write_text(json.dumps({"podcast": True}), encoding="utf-8")
    return d


def _untouched(d):
    """Alice's directory exactly as the fixture left it."""
    assert (d / ".pause").exists(), "Alice's .pause was cleared by someone else"
    assert (d / research.NO_AUTO_RETRY_MARKER).exists(), (
        "Alice's .no_auto_retry was cleared by someone else")
    assert json.loads((d / "config.json").read_text(encoding="utf-8")) == {"podcast": True}, (
        "another member's payload config was merged into Alice's run")
    assert json.loads((d / "owner.json").read_text(encoding="utf-8"))["uid"] == ALICE


# ══ 1. the disk record names a person, and the helpers now ask it ═════════

def test_a_run_id_naming_another_persons_directory_is_refused(alices_run):
    """⛔⛔ THE PIN THE SPEC NAMED. The research matches; the person does not."""
    assert research._corroborated_run_id(RUN, RID, BOB) == ""
    # ⭐ ACCEPT POLARITY — the person the record names keeps their claim.
    assert research._corroborated_run_id(RUN, RID, ALICE) == RUN


def test_the_research_half_still_refuses_on_its_own(alices_run):
    """The person matching must not excuse a research that does not."""
    assert research._corroborated_run_id(RUN, "chat_other", ALICE) == ""


def test_a_record_naming_no_person_decides_only_the_research(tmp_path, monkeypatch):
    """⛔ ABSENT IS NOT DISAGREEING. `setup_firestore_run` writes both halves,
    so a record with no uid is an older or hand-made shape; it still decides
    the research, and nothing about the person."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    _run_dir(tmp_path, owner={"researchId": RID})
    assert research._corroborated_run_id(RUN, RID, BOB) == RUN
    assert research._corroborated_run_id(RUN, "chat_other", BOB) == ""
    assert research._run_dir_owning_research(RID, BOB) == tmp_path / "queues" / RUN


def test_silence_from_the_disk_still_keeps_the_claim(tmp_path, monkeypatch):
    """⭐ A directory with no readable owner.json keeps its claim, as before —
    refusing on absence would break resume for every run predating the file."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    _run_dir(tmp_path)  # no owner.json
    assert research._corroborated_run_id(RUN, RID, BOB) == RUN
    assert research._corroborated_run_id("never_existed", RID, BOB) == "never_existed"


def test_the_disk_lookup_skips_another_persons_directory(alices_run):
    """⛔⛔ THE PATH THE EVIDENCE WALKED: a research document minted with no
    `backendRunId` sent the resume to the disk, and the disk answered with
    Alice's directory for Bob."""
    assert research._run_dir_owning_research(RID, BOB) is None
    assert research._run_dir_owning_research(RID, ALICE) == alices_run


def test_the_disk_lookup_keeps_looking_past_a_foreign_directory(alices_run, tmp_path):
    """⛔ SKIPPED, NOT REFUSED. With both people holding a directory for the same
    research id, each gets their own — whichever order the filesystem lists
    them in. A `return None` on the first mismatch would lose Bob's."""
    bobs = _run_dir(tmp_path, run="Bob_topic_20260921_111500",
                    owner={"uid": BOB, "researchId": RID})
    assert research._run_dir_owning_research(RID, BOB) == bobs
    assert research._run_dir_owning_research(RID, ALICE) == alices_run


# ══ 2. the resume resolution, executed with a queue doc naming someone else ═

class _Db:
    def __init__(self, docs):
        self._docs = docs
        self.reads = []

    def collection(self, _n):
        return _Path(self, ())


class _Path:
    def __init__(self, db, parts):
        self._db, self._parts = db, parts

    def collection(self, n):
        return _Path(self._db, self._parts + (n,))

    document = collection

    def get(self):
        key = (self._parts[0], self._parts[2])
        self._db.reads.append(key)
        if isinstance(self._db._docs, Exception):
            raise self._db._docs
        data = self._db._docs.get(key)
        return type("S", (), {"exists": data is not None,
                              "to_dict": lambda _s, d=data: dict(d or {})})()


def _queue_doc(uid, **over):
    d = {"action": "resume", "uid": uid, "submittedBy": uid, "researchId": RID}
    d.update(over)
    return d


def test_the_resolution_refuses_a_payload_naming_another_persons_run(alices_run, monkeypatch):
    """⛔⛔ Bob's queue doc names Alice's run. The claim is refused and the
    resolution falls back to BOB's document, which does not exist."""
    db = _Db({})
    monkeypatch.setattr(research, "_firebase_db", db)
    run_id, rd = research._resume_run_id(_queue_doc(BOB, backendRunId=RUN), BOB, RID)
    assert run_id == ""
    assert rd is None
    assert db.reads == [(BOB, RID)], "the refused claim did not fall back to the document"


def test_the_resolution_refuses_a_document_naming_another_persons_run(alices_run, monkeypatch):
    """⛔⛔ THE SAME ATTACK WITH ONE MORE WRITE. Bob creates the research doc in
    his own tree with Alice's run id in `backendRunId` and leaves the payload
    empty. Checking only the payload would have moved the hole, not closed it."""
    monkeypatch.setattr(research, "_firebase_db", _Db({(BOB, RID): {"backendRunId": RUN}}))
    run_id, rd = research._resume_run_id(_queue_doc(BOB), BOB, RID)
    assert run_id == ""
    assert rd == {"backendRunId": RUN}


def test_the_resolution_keeps_an_honest_claim_without_reading_the_document(alices_run, monkeypatch):
    """⭐ ACCEPT POLARITY, and the synth-user design: a corroborated payload claim
    must not need the document, which a synth user may not be able to read."""
    db = _Db(RuntimeError("the document must not be read"))
    monkeypatch.setattr(research, "_firebase_db", db)
    assert research._resume_run_id(_queue_doc(ALICE, backendRunId=RUN), ALICE, RID) == (RUN, {})
    assert db.reads == []


def test_the_resolution_takes_the_documents_run_when_it_is_theirs(alices_run, monkeypatch):
    monkeypatch.setattr(research, "_firebase_db", _Db({(ALICE, RID): {"backendRunId": RUN}}))
    assert research._resume_run_id(_queue_doc(ALICE), ALICE, RID) == (RUN, {"backendRunId": RUN})


def test_a_failed_read_is_raised_for_the_caller_to_keep_silent(alices_run, monkeypatch):
    """The transient exit stays the caller's: a read that failed once replays."""
    monkeypatch.setattr(research, "_firebase_db", _Db(PermissionError("403")))
    with pytest.raises(PermissionError):
        research._resume_run_id(_queue_doc(BOB), BOB, RID)


# ══ 3. the resume branch itself, executed ═════════════════════════════════

def test_a_resume_naming_another_persons_run_touches_nothing_of_theirs(
        alices_run, tmp_path, monkeypatch):
    """⛔⛔⛔ THE CONSUMER. Bob's queue doc, signed honestly as Bob, names Alice's
    research and Alice's run. Nothing of Alice's may move.

    ⛔ BOB'S RECORD EXISTS (wave 10.10). Without it the pickup rule stands the
    Resume down as a deleted research before the ownership question is asked,
    and this test would pass with that question switched off."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(BOB, RID): {"status": "paused_backend_restart"}}).feed(
        **_queue_doc(BOB, backendRunId=RUN, config={"podcast": False}))
    assert lis.enqueued == [], "Alice's run was enqueued under Bob"
    _untouched(alices_run)
    assert lis.writes_to(ALICE) == []
    assert "incoming" in lis.incoming, "the refused resume was left to be re-read"


def test_a_minted_document_with_no_run_id_cannot_find_theirs_on_disk(
        alices_run, tmp_path, monkeypatch):
    """⛔⛔ THE EVIDENCE'S PATH, END TO END. Bob mints `users/Bob/researches/<Alice's
    id>` with no `backendRunId`; the disk fallback used to find Alice's
    directory, "repair" Bob's document with it and resume it. Now Bob is told
    there is nothing to resume, in his own tree."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(BOB, RID): {"status": "paused_backend_restart"}}).feed(
        **_queue_doc(BOB))
    assert lis.enqueued == []
    _untouched(alices_run)
    assert not any("backendRunId" in w[2] for w in lis.writes), (
        "Bob's document was repaired with Alice's run id")
    assert [w[:2] for w in lis.writes] == [(BOB, RID)]
    assert lis.writes[0][2]["resumeDropReason"] == research.RESUME_DROP_NO_RUN_ID


def test_a_minted_document_naming_their_run_is_refused(alices_run, tmp_path, monkeypatch):
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(BOB, RID): {"backendRunId": RUN}}).feed(
        **_queue_doc(BOB))
    assert lis.enqueued == []
    _untouched(alices_run)
    assert lis.writes_to(ALICE) == []


def test_a_payload_claim_backed_by_a_minted_document_is_still_refused(
        alices_run, tmp_path, monkeypatch):
    """⛔ BOTH CLAIMS AT ONCE, the shape an attacker would actually send: the
    payload names Alice's run AND Bob has minted a document so the "not found"
    exit does not save him. A branch that fell back to the raw payload whenever
    the resolution came back empty would resume Alice's run here and nowhere
    else in this file."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(BOB, RID): {"status": "paused_backend_restart"}}).feed(
        **_queue_doc(BOB, backendRunId=RUN))
    assert lis.enqueued == []
    _untouched(alices_run)
    assert lis.writes_to(ALICE) == []


def test_a_resume_for_a_research_that_does_not_exist_writes_nothing(tmp_path, monkeypatch):
    """The not-found exit moved into `_resume_run_id`'s return value; it still
    drops the request and writes nowhere, because there is no document to
    write to."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER).feed(**_queue_doc(ALICE))
    assert lis.writes == []
    assert lis.enqueued == []
    assert lis.incoming == ["incoming"]


def test_the_person_whose_run_it_is_still_resumes_it(alices_run, tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY — the whole product. Without this, a guard that
    refused every resume would pass every refusal above.

    ⭐ HER RECORD EXISTS, as it always does when a Resume is sent: the web reads
    it to route the request. A Resume for a research with no record is one whose
    research was deleted, and it stands down (wave 10.10)."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(ALICE, RID): {"status": "paused_backend_restart"}}).feed(
        **_queue_doc(ALICE, backendRunId=RUN))
    assert len(lis.enqueued) == 1, "Alice could not resume her own run"
    job = lis.enqueued[0]
    assert (job["uid"], job["research_id"], job["run_id"]) == (ALICE, RID, RUN)
    assert job["resume_dir"] == str(alices_run)
    assert not (alices_run / ".pause").exists()
    assert not (alices_run / research.NO_AUTO_RETRY_MARKER).exists()


def test_the_person_whose_run_it_is_still_resumes_it_from_the_disk_alone(
        alices_run, tmp_path, monkeypatch):
    """⭐ The disk fallback's accept polarity: a document whose `backendRunId`
    write-back failed is still repaired from the directory that IS hers."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(ALICE, RID): {"status": "paused_backend_restart"}}).feed(
        **_queue_doc(ALICE))
    assert (ALICE, RID, {"backendRunId": RUN}) in lis.writes
    assert [j["run_id"] for j in lis.enqueued] == [RUN]


def test_the_device_owner_still_resumes_a_sharers_run(alices_run, tmp_path, monkeypatch):
    """⭐⭐ THE OWNER-CONTROL PATH writes `uid=<sharer>`, `submittedBy=<owner>`
    on purpose. The sharer's own owner.json names the sharer, so it matches."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(ALICE, RID): {"status": "paused_backend_restart"}}).feed(
        **_queue_doc(ALICE, submittedBy=OWNER, backendRunId=RUN))
    assert [(j["uid"], j["run_id"]) for j in lis.enqueued] == [(ALICE, RUN)]


def _legacy_held(tmp_path):
    """A run this process holds for Alice, whose directory predates the uid half
    of owner.json — the one shape the disk cannot attribute."""
    _run_dir(tmp_path, run="Legacy_run", owner={"researchId": RID})
    return {"research_id": RID, "uid": ALICE, "run_id": "Legacy_run"}


def test_a_run_held_here_for_another_person_is_not_theirs_to_resume(tmp_path, monkeypatch):
    """⛔⛔ THE LOCAL GATE ON THE RESUME SIDE. The directory cannot say whose it
    is, but the job in hand always names its owner.

    ⛔ BOB'S RECORD EXISTS (wave 10.10), or the pickup rule would refuse this as
    a deleted research and the gate could be switched off unnoticed."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(BOB, RID): {"status": "paused_backend_restart"}},
                   current_job=_legacy_held(tmp_path)).feed(
        **_queue_doc(BOB, backendRunId="Legacy_run"))
    assert lis.enqueued == [], "a run held for Alice was resumed under Bob"
    assert lis.writes == []
    assert lis.incoming == ["incoming"]


def test_a_run_held_here_is_still_resumable_by_its_owner(tmp_path, monkeypatch):
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs={(ALICE, RID): {"status": "paused_backend_restart"}},
                   current_job=_legacy_held(tmp_path)).feed(
        **_queue_doc(ALICE, backendRunId="Legacy_run"))
    assert [j["run_id"] for j in lis.enqueued] == ["Legacy_run"]


# ══ 4. the deferred cancel ═══════════════════════════════════════════════

class _Q:
    def __init__(self, doc_id, **data):
        self.id = doc_id
        self._d = data

    def to_dict(self):
        return dict(self._d)


def _start(doc_id="s1", uid=ALICE, rid=RID, **extra):
    return _Q(doc_id, researchId=rid, uid=uid, submittedBy=uid, action="start", **extra)


def test_the_deferred_scan_leaves_another_persons_start_doc():
    """⛔⛔ THE PIN THE SPEC NAMED, on the production helper."""
    assert research._deferred_start_doc_id([_start()], RID, BOB) is None
    # ⭐ ACCEPT POLARITY
    assert research._deferred_start_doc_id([_start()], RID, ALICE) == "s1"


def test_the_deferred_scan_finds_this_persons_doc_past_a_foreign_one():
    """Skipped, not stopped at — the old `break` on the first researchId match
    must not become a `return None` on the first stranger."""
    docs = [_start("s1", uid=ALICE), _start("s2", uid=BOB)]
    assert research._deferred_start_doc_id(docs, RID, BOB) == "s2"
    assert research._deferred_start_doc_id(docs, RID, ALICE) == "s1"


def test_the_deferred_scan_still_matches_only_start_docs_for_this_research():
    docs = [
        _Q("c1", researchId=RID, uid=ALICE, action="cancel"),
        _start("s-other", rid="chat_other"),
        _Q("legacy", researchId=RID, uid=ALICE),          # no action = start
    ]
    assert research._deferred_start_doc_id(docs, RID, ALICE) == "legacy"
    assert research._deferred_start_doc_id(docs[:2], RID, ALICE) is None


def test_a_start_doc_naming_no_person_is_nobodys_to_delete():
    """⛔ STRICT ON PURPOSE. A start doc with no uid never runs — the start
    branch deletes it as missing a field — so matching it would only let anyone
    who knows the id delete it."""
    assert research._deferred_start_doc_id([_Q("s1", researchId=RID, action="start")],
                                           RID, ALICE) is None
    assert research._deferred_start_doc_id([_start()], RID, "") is None
    assert research._deferred_start_doc_id([_start()], "", ALICE) is None


def _cancel(uid, **over):
    d = {"action": "cancel", "uid": uid, "submittedBy": uid, "researchId": RID}
    d.update(over)
    return d


def _queued_start():
    return {"s1": {"action": "start", "researchId": RID, "uid": ALICE,
                   "submittedBy": ALICE, "topic": "Alice's topic"}}


def test_a_cancel_naming_another_persons_queued_run_leaves_it_queued(tmp_path, monkeypatch):
    """⛔⛔⛔ THE CONSUMER. No worker holds a deferred run, so the local gate
    passes it — and on a multi-worker machine every sibling reaches this path
    even when the holder refuses. Alice's start doc must survive Bob."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, queue_docs=_queued_start()).feed(
        **_cancel(BOB))
    assert "s1" not in lis.deleted_queue_ids, "Bob's cancel deleted Alice's queued run"
    assert "s1" in lis.db.queue.docs
    assert lis.writes_to(ALICE) == []


def test_a_person_still_cancels_their_own_queued_run(tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY — the Bull Dog fix (2026-05-22) this scan exists for."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, queue_docs=_queued_start()).feed(
        **_cancel(ALICE))
    assert lis.deleted_queue_ids == ["s1"]
    [(uid, rid, patch)] = lis.writes
    assert (uid, rid) == (ALICE, RID)
    assert patch["status"] == "stopped" and patch["cancelled"] is True


def test_the_device_owner_still_cancels_a_sharers_queued_run(tmp_path, monkeypatch):
    """⭐⭐ The owner's Stop on a sharer's queued run writes `uid=<sharer>`, the
    same uid the sharer's start doc carries — so it is unchanged."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, queue_docs=_queued_start()).feed(
        **_cancel(ALICE, submittedBy=OWNER, ownerControl="cancel"))
    assert lis.deleted_queue_ids == ["s1"]
    assert [w[:2] for w in lis.writes] == [(ALICE, RID)]


# ⛔ THE CANCEL GATE NOW READS ITS JOBS FROM `_jobs_held_locally`, shared with
# the resume branch. Each slot it collects is where a job can be parked, and the
# running check that follows it has NO ownership clause of its own — so a slot
# the helper forgets is a run another member can stop. (A third slot,
# `gate_pending_job`, retired with the queue gate in wave 10.9; a dequeued job
# is `current_job` from the moment it leaves the queue.)

_ALICES_JOB = {"research_id": RID, "uid": ALICE, "run_id": RUN}


@pytest.mark.parametrize("slot", ["current_job", "deque_jobs"])
def test_a_cancel_naming_a_run_held_here_for_another_person_is_refused(
        slot, tmp_path, monkeypatch):
    held = {slot: [dict(_ALICES_JOB)] if slot == "deque_jobs" else dict(_ALICES_JOB)}
    lis = Listener(monkeypatch, tmp_path, owner=OWNER, **held).feed(**_cancel(BOB))
    assert lis.controls.stops == 0, f"Bob's cancel stopped Alice's {slot} run"
    assert lis.exits == []
    assert lis.writes == []
    assert lis.incoming == ["incoming"]
    if slot == "deque_jobs":
        assert list(lis.jobs._queue) == [_ALICES_JOB]


def test_a_person_still_cancels_their_own_run_this_process_holds(tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY for the gate above.

    ⛔ It used to name the `gate_pending` slot, which retired with the queue
    gate (wave 10.9, N8). The slot is gone; the acceptance it measured is not,
    so it moves to the slot that now holds a dequeued job."""
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   current_job=dict(_ALICES_JOB)).feed(**_cancel(ALICE))
    assert lis.controls.stops == 1
    assert [w[:2] for w in lis.writes] == [(ALICE, RID)]


# ══ 5. boot recovery: the same claim, read off a research document ════════
#
# ⛔⛔ NOT IN THE SPEC, AND THE SAME HOLE. `_rehydrate_ongoing_for_tree` reads
# `backendRunId` off a research document in the scanned tree — on a sharer's
# tree, a document that sharer can create — and auto-resumed that directory into
# the tree on a supervised device's next boot.

class _RSnap:
    def __init__(self, doc_id, data):
        self.id, self._d = doc_id, data

    def to_dict(self):
        return dict(self._d)


class _RDb:
    """users/{uid}/researches (queried) and devices/{id} (read)."""

    def __init__(self, researches):
        self._researches = researches

    def collection(self, name):
        return _RNode(self, name)


class _RNode:
    def __init__(self, db, kind, uid=None):
        self._db, self._kind, self._uid = db, kind, uid

    def document(self, key):
        return _RNode(self._db, self._kind, key)

    def collection(self, _name):
        return _RNode(self._db, "researches", self._uid)

    def where(self, *a, **k):
        return self

    def get(self):
        if self._kind == "researches":
            return list(self._db._researches.get(self._uid, []))
        # devices/{id}: supervised
        return type("D", (), {"exists": True,
                              "to_dict": lambda _s: {"supervised": True}})()


def _rehydrate(monkeypatch, tree_uid, researches):
    updates, enqueues = [], []
    monkeypatch.setattr(research, "_firebase_db", _RDb(researches))
    monkeypatch.setattr(research, "load_device_id", lambda: "dev1")
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda u, r, p: updates.append((u, r, p)) or True)
    monkeypatch.setattr(research, "_safe_enqueue",
                        lambda q, job, source=None: enqueues.append(job) or True)
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda r, w: [])
    monkeypatch.setattr(research, "load_checkpoint", lambda qd: {"topic": "t"})
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", object())
    asyncio.run(research._rehydrate_ongoing_for_tree(tree_uid, OWNER, set()))
    return updates, enqueues


def _ongoing_doc():
    return [_RSnap(RID, {"deviceId": "dev1", "status": "ongoing", "backendRunId": RUN})]


def test_boot_recovery_will_not_auto_resume_another_persons_run(alices_run, monkeypatch):
    updates, enqueues = _rehydrate(monkeypatch, BOB, {BOB: _ongoing_doc()})
    assert enqueues == [], "boot recovery resumed Alice's run into Bob's tree"
    assert (alices_run / ".pause").exists()
    # it falls through to the paused mark, in Bob's own tree
    assert [(u, r) for u, r, _p in updates] == [(BOB, RID)]


def test_boot_recovery_still_auto_resumes_the_trees_own_run(alices_run, monkeypatch):
    """⭐ ACCEPT POLARITY."""
    updates, enqueues = _rehydrate(monkeypatch, ALICE, {ALICE: _ongoing_doc()})
    assert [(j["uid"], j["run_id"]) for j in enqueues] == [(ALICE, RUN)]
    assert updates == []


# ══ 6. a run id is a NAME, and a claim that is a path is not one ══════════
#
# ⛔⛔ ROUND TWO OF CROSS-VERIFY, EXECUTED BOTH WAYS. Everything above asks
# `queues/<claim>/owner.json` whose run a claim is, and a directory with no
# readable record deliberately keeps its claim — so a claim that was a PATH
# walked past the whole section. `<Alice's run>/documents` has no `owner.json`
# of its own: the claim was kept, Bob's config was merged into Alice's folder
# and a run was enqueued rooted inside it. An ABSOLUTE claim left `queues/`
# altogether, so any directory this account can write had its `config.json`
# merged over, its `.pause` unlinked and `run_pipeline` pointed at it.


def test_a_claim_into_a_subfolder_of_another_persons_run_is_refused(alices_run):
    """⛔⛔ THE CLAIM THE PROBE SENT. `documents/` is Alice's, and it is the one
    corner of her run that carries no record of its own."""
    (alices_run / "documents").mkdir()
    assert research._corroborated_run_id(f"{RUN}/documents", BOB_RID, BOB) == ""
    # ⛔ AND NOT BECAUSE IT IS BOB'S. It is not a run id, so it is nobody's —
    # Alice gets the same answer for the same string.
    assert research._corroborated_run_id(f"{RUN}/documents", RID, ALICE) == ""


def test_an_absolute_claim_that_leaves_queues_is_refused(alices_run, tmp_path):
    """⛔⛔ `Path("/a") / "/b"` is `/b`. The join simply left our tree."""
    outside = tmp_path / "elsewhere" / "someapp"
    outside.mkdir(parents=True)
    assert research._corroborated_run_id(str(outside), RID, ALICE) == ""


def test_a_claim_that_spells_its_way_back_into_queues_is_refused_too(
        alices_run, tmp_path):
    """⛔ A RUN ID IS A NAME. This one lands back inside `queues/` — so asking
    the filesystem where it ends up is not enough on its own, and it is Alice's
    OWN run at the end of it, which is what makes this pin about the spelling
    and nothing else."""
    _run_dir(tmp_path, run="Bob_run", owner={"uid": BOB, "researchId": BOB_RID})
    assert research._corroborated_run_id(f"Bob_run/../{RUN}", RID, ALICE) == ""


def test_a_run_id_that_is_a_plain_name_is_still_taken(tmp_path, monkeypatch):
    """⭐⭐ ACCEPT POLARITY, AND WHY THIS IS NOT A PATTERN MATCH. `safe_name`
    returns "" for a topic of pure punctuation, so a real run id can be
    `_20260921_101500`; a rule insisting on a name before the stamp would refuse
    its owner's own resume for ever. A name for a run whose folder is gone is
    kept too — that refusal belongs further down, where it says "artifacts
    gone"."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    run = f"{research.safe_name('...')}_20260921_101500"
    assert run == "_20260921_101500"
    _run_dir(tmp_path, run=run, owner={"uid": ALICE, "researchId": RID})
    assert research._corroborated_run_id(run, RID, ALICE) == run
    assert research._corroborated_run_id("never_existed", RID, ALICE) == "never_existed"


def test_the_disk_lookup_will_not_follow_a_link_out_of_queues(alices_run, tmp_path):
    """⛔ A LISTING IS A CLAIM TOO. `is_dir()` follows a symlink, so a link in
    `queues/` was handed back as a run directory to resume into — with whatever
    `owner.json` sits at the other end of it."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "owner.json").write_text(
        json.dumps({"uid": BOB, "researchId": BOB_RID}), encoding="utf-8")
    (tmp_path / "queues" / "Bob_run").symlink_to(outside, target_is_directory=True)
    assert research._run_dir_owning_research(BOB_RID, BOB) is None
    # ⭐ ACCEPT POLARITY — the same record in a real directory is still found.
    real = _run_dir(tmp_path, run="Bob_real_run",
                    owner={"uid": BOB, "researchId": BOB_RID})
    assert research._run_dir_owning_research(BOB_RID, BOB) == real


def _bobs_paused_research():
    return {(BOB, BOB_RID): {"status": "paused_backend_restart"}}


def _bobs_resume(**over):
    d = {"action": "resume", "uid": BOB, "submittedBy": BOB, "researchId": BOB_RID}
    d.update(over)
    return d


def test_a_resume_claiming_a_subfolder_of_their_run_touches_nothing_in_it(
        alices_run, tmp_path, monkeypatch):
    """⛔⛔⛔ THE CONSUMER, and the probe's own scenario: Bob resumes his OWN
    research and points it at a corner of Alice's run."""
    docs = alices_run / "documents"
    docs.mkdir()
    (docs / "chatgpt.md").write_text("Alice's report", encoding="utf-8")
    lis = Listener(monkeypatch, tmp_path, owner=OWNER,
                   research_docs=_bobs_paused_research()).feed(
        **_bobs_resume(backendRunId=f"{RUN}/documents", config={"planted": True}))
    assert lis.enqueued == [], "a run was enqueued rooted inside Alice's run folder"
    assert sorted(p.name for p in docs.iterdir()) == ["chatgpt.md"], (
        "Bob's payload config was written into Alice's run folder")
    _untouched(alices_run)
    assert [w[:2] for w in lis.writes] == [(BOB, BOB_RID)]


def test_a_resume_claiming_an_absolute_path_touches_nothing_outside_queues(
        tmp_path, monkeypatch):
    """⛔⛔⛔ THE CONSUMER for the absolute claim: a directory that was never a
    run of ours, with its own settings and its own `.pause`."""
    app = tmp_path / "app"
    (app / "queues").mkdir(parents=True)
    victim = tmp_path / "elsewhere" / "someapp"
    victim.mkdir(parents=True)
    (victim / "config.json").write_text(
        json.dumps({"server": "https://good"}), encoding="utf-8")
    (victim / ".pause").write_text("", encoding="utf-8")
    lis = Listener(monkeypatch, app, owner=OWNER,
                   research_docs=_bobs_paused_research()).feed(
        **_bobs_resume(backendRunId=str(victim), config={"server": "https://evil"}))
    assert lis.enqueued == []
    assert json.loads((victim / "config.json").read_text(encoding="utf-8")) == {
        "server": "https://good"}, "a payload config was merged outside queues/"
    assert (victim / ".pause").exists(), "a .pause outside queues/ was cleared"


def test_boot_recovery_will_not_take_a_path_claim_either(alices_run, monkeypatch):
    """⛔⛔ THE SAME CLAIM ON THE OTHER CONSUMER. A supervised device's next boot
    reads `backendRunId` off a document in the scanned tree."""
    docs = alices_run / "documents"
    docs.mkdir()
    updates, enqueues = _rehydrate(monkeypatch, BOB, {BOB: [_RSnap(BOB_RID, {
        "deviceId": "dev1", "status": "ongoing",
        "backendRunId": f"{RUN}/documents"})]})
    assert enqueues == [], "boot recovery auto-resumed a folder inside Alice's run"
    assert [(u, r) for u, r, _p in updates] == [(BOB, BOB_RID)]


# ── the dead-worker reconciler reads a run's delivery.json on the same claim ──

class _ReconcileDb:
    """`users/{uid}/researches`; the query itself goes through `_fs_where`."""

    def collection(self, _n):
        return self

    def document(self, _n):
        return self


def _reconcile(monkeypatch, tmp_path, docs):
    marks = []
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    monkeypatch.setattr(research, "_firebase_db", _ReconcileDb())
    monkeypatch.setattr(research, "_fs_where",
                        lambda col, *a, **k: type("Q", (), {"get": lambda _s: docs})())
    monkeypatch.setattr(research, "_owner_worker_of", lambda _a: 2)
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda r, w: [])
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda u, r, p: marks.append((u, r)) or True)
    asyncio.run(research._reconcile_dead_worker_runs(ALICE, {2}))
    return marks


def test_the_dead_worker_sweep_will_not_read_a_delivery_file_outside_queues(
        tmp_path, monkeypatch):
    """⛔ THE FOURTH CONSUMER of the same claim, found while fixing the other
    three: this joined `backendRunId` raw to decide whether the autonomous
    Cloud-Run tail had finished the run, so a path claim answered the question
    with a file that was never a run's. An unusable claim now reads exactly like
    an absent one — the shape this guard already handles — so the run is
    marked."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "delivery.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8")
    marks = _reconcile(monkeypatch, tmp_path,
                       [_RSnap(RID, {"assignedWorker": 2,
                                     "backendRunId": str(outside)})])
    assert marks == [(ALICE, RID)]


def test_the_dead_worker_sweep_still_leaves_a_finished_tail_alone(
        tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY, and the guard's whole purpose: a run whose BE handed
    P4/P5 to Cloud Run stays `ongoing` on purpose and must not gain a false
    Resume."""
    d = _run_dir(tmp_path, owner={"uid": ALICE, "researchId": RID})
    (d / "delivery.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8")
    assert _reconcile(monkeypatch, tmp_path,
                      [_RSnap(RID, {"assignedWorker": 2, "backendRunId": RUN})]) == []
    (d / "delivery.json").write_text(
        json.dumps({"status": "ongoing"}), encoding="utf-8")
    assert _reconcile(monkeypatch, tmp_path,
                      [_RSnap(RID, {"assignedWorker": 2,
                                    "backendRunId": RUN})]) == [(ALICE, RID)]
