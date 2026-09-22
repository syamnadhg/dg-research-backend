"""After phase 3 the machine hands off and stops interfering.

Wave 10.9, items N8 · 542-4 · 542-5 · 542-S4. One rule underneath all four —
contract rule 1 of `#Dev/wave109/P3_TO_P4_STALL.md`:

    When phase 3 ends, write `beDone` + `needsFeTrigger`, kick the route, and
    repeat with backoff until it answers claimed / in-flight / completed. After
    `beDone` the machine NEVER writes `status`, `phase` or any fe* field on that
    run. `delivery.json` "completed" means "hand-off done", never "run complete".

WHAT WAS WRONG, IN THE ORDER A RUN MEETS IT

  N8    The next run's START was held behind the PREVIOUS run's cloud tail.
        `_wait_for_prior_fe_completion` polled that run's status for up to 4200
        seconds; the start listener predicted the same wait and landed the new
        submission "queued", naming the run it was waiting for. Phases 4 and 5
        execute on Cloud Run, so there was nothing on this computer to contend
        for — on a shared machine this was one person's start held behind
        another person's cloud tail, and a disk snapshot carried the wait across
        a restart. The boot half of it went further and STAMPED the run it could
        not wait on: "Backend restarted before this run reached completion",
        status "stopped" — landing on runs that were mid-upload (a handed-off
        run is deliberately "ongoing"), and relabelling an ERRORED run "stopped"
        with a restart blamed for it.

  542-4 The same confusion, three more readers. `delivery.json` says "completed"
        at the END OF PHASE 3; `detect_resume_phase` read it as "the run is
        finished" and answered 6, so a Resume logged one line and did nothing.
        `_rehydrate_ongoing_for_tree` had no guard at all: every restart during
        a cloud tail either marked the run `paused_backend_restart` — a Resume
        CTA over a healthy upload — or, on a supervised device, re-enqueued it.

  542-5 The kick was sent ONCE. No token, a POST that never left, or a 5xx left
        the marker and nothing else: no video, no Super Research, no Doc, no
        email, and a run reading "ongoing" until somebody opened its chat.

  542-S4 And the two log lines a stuck-run report is read from both lied: the
        marker line printed "written" for a write that returned False, and a 202
        — "another caller holds the claim", i.e. this call did nothing — printed
        as "dispatched ✓".

WHAT THESE TESTS PIN

  1. An idle worker starts a run immediately, whatever the previous run is doing.
  2. `delivery.json` "completed" is read as the hand-off by every reader, and a
     run id that is a PATH decides nothing.
  3. A handed-off run found at boot is re-kicked, never stamped and never
     re-enqueued — and a run that was NOT handed off still recovers as before.
  4. A refusal reaches the document where the chat can see it, on `phases[4]`
     and never on `feP4State`.

Run:  pytest tests/test_handoff_is_the_end_109.py -v
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

from _queue_listener import Listener  # noqa: E402
from test_per_worker_rehydration_966 import _DevSnap, _Snap, _run, _setup  # noqa: E402

OWNER = "uid-owner"
RID = "rid-owner-1"


# ════ 1. N8 — nothing waits on the previous run ═══════════════════════════
#
# ⛔⛔ EXECUTED THROUGH THE REAL START LISTENER. The retired gate's own tests
# read its source for wording and branch order, which is exactly the shape that
# cannot notice a rule being moved. What matters is not that the function is
# gone; it is that a submission's ANSWER no longer depends on another run.

def _prior_run_in_its_cloud_tail():
    """The three keys the retired gate was fed from, describing a run that
    finished its BACKEND work moments ago and is now in the cloud.

    ⛔⛔ THE TIMESTAMP IS TAKEN NOW, AND THAT IS THE WHOLE PIN. The gate's
    deadline was `last_be_done_at + 4200s`, so a fixture with a small constant
    there describes a run that finished in 1970 — already past its window, so
    the gate would not have blocked and the test would have passed against the
    code it is supposed to fail against. Measured: with a literal `1` this test
    is green before the fix and after it."""
    return {
        "last_completed_uid": OWNER,
        "last_completed_rid": "rid-somebody-elses",
        "last_be_done_at": int(time.time() * 1000),
    }


def _start_ongoing(monkeypatch, tmp_path, **kw):
    return Listener(monkeypatch, tmp_path, owner=OWNER, research_docs={
        (OWNER, RID): {"status": "queued"}}, **kw).feed(
        action="start", uid=OWNER, submittedBy=OWNER, researchId=RID,
        topic="anything")


def test_a_start_is_not_held_behind_the_previous_runs_cloud_tail(tmp_path, monkeypatch):
    """⛔⛔ THE DEFECT. With the prior-run pointer set and a fresh finish time,
    the listener used to compute the gate's own predicate, write status
    "queued" with a `queuePosition`, and name the other run in
    `queuedBehindRunId` — on a shared computer, somebody else's run — while the
    worker sat in `_wait_for_prior_fe_completion` for as long as that run's
    CLOUD tail took. Nothing of that run executes on this machine.

    Nothing else can make this pass: the pointer is set, the worker is idle, and
    the only way to answer "ongoing" is to stop consulting the pointer."""
    lis = _start_ongoing(monkeypatch, tmp_path,
                         last_completed=_prior_run_in_its_cloud_tail())
    assert [j.get("research_id") for j in lis.enqueued] == [RID], (
        "the run was not enqueued at all")
    patches = [w[2] for w in lis.writes if w[:2] == (OWNER, RID)]
    assert patches, "the listener wrote no status for the new run"
    patch = patches[0]
    assert patch["status"] == "ongoing", (
        "a submission was parked because ANOTHER run's cloud tail was in "
        "flight — the queue gate is back")
    assert "queuePosition" not in patch
    assert "queuedBehindRunId" not in patch


def test_a_busy_worker_still_queues(tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY, and the thing the removal must not break: a worker
    that is genuinely running something still answers "queued", with a
    position. Being busy is real; waiting on the cloud was not."""
    lis = _start_ongoing(monkeypatch, tmp_path,
                         deque_jobs=[{"research_id": "rid-live", "uid": OWNER}])
    patch = [w[2] for w in lis.writes if w[:2] == (OWNER, RID)][0]
    assert patch["status"] == "queued"
    assert patch["queuePosition"] >= 1


def test_the_jobs_this_process_holds_has_no_gate_slot(monkeypatch):
    """⛔ THE CANCEL GATE READS THIS LIST, and the checks after it carry no
    ownership clause of their own. The gate-pending slot is gone with the wait
    that filled it; a slot left reading `{}` for ever would be a lie about where
    a job can be."""
    monkeypatch.setitem(research._QUEUE_STATE, "current_job",
                        {"research_id": RID, "uid": OWNER})
    monkeypatch.setitem(research._QUEUE_STATE, "gate_pending_job",
                        {"research_id": "rid-ghost", "uid": "uid-ghost"})

    class _Q:
        _queue = ()

    held = research._jobs_held_locally(_Q())
    assert {j.get("research_id") for j in held if j} == {RID}, (
        "a job was collected from a slot nothing can write any more")


# ════ 2. 542-4 — what `delivery.json` actually says ═══════════════════════
@pytest.mark.parametrize("delivery, handed_off", [
    ({"status": "completed"}, True),
    ({"status": "ongoing"}, False),
    ({"status": "stopped"}, False),
    ({"status": "paused"}, False),
    ({}, False),
])
def test_the_delivery_record_is_read_as_the_hand_off(tmp_path, delivery, handed_off):
    d = tmp_path / "run"
    d.mkdir()
    (d / "delivery.json").write_text(json.dumps(delivery), encoding="utf-8")
    assert research._handed_off_to_cloud(d) is handed_off


def test_a_run_with_no_delivery_record_is_not_handed_off(tmp_path):
    """⭐ THE FAIL-TOWARD-RECOVERY DIRECTION. A missing, unreadable or absent
    record must read as NOT handed off — a run the machine never finished is one
    a checkpoint resume can still pick up."""
    d = tmp_path / "run"
    d.mkdir()
    assert research._handed_off_to_cloud(d) is False
    (d / "delivery.json").write_text("{ not json", encoding="utf-8")
    assert research._handed_off_to_cloud(d) is False
    assert research._handed_off_to_cloud(tmp_path / "missing") is False
    assert research._handed_off_to_cloud(None) is False


def test_detect_resume_phase_says_handed_off_not_complete(tmp_path):
    """⛔⛔ SIX IS THE HAND-OFF. The reason it must not say "complete" is that a
    caller acts on the sentence: the resume branch logged "Pipeline already
    complete — nothing to resume" and sat down on a run whose cloud tail had
    never started."""
    d = tmp_path / "run"
    d.mkdir()
    (d / "delivery.json").write_text(json.dumps({"status": "completed"}),
                                     encoding="utf-8")
    phase, why = research.detect_resume_phase(d)
    assert phase == 6
    assert "handed off" in why.lower()
    assert "complete" not in why.lower().replace("completed", "")


def test_a_run_id_that_is_a_path_decides_nothing(tmp_path, monkeypatch):
    """⛔⛔ THE CLAIM ON A DOCUMENT IS A NAME, NOT A PATH — the same refusal
    every other reader of `backendRunId` makes. Joining it raw read a
    `delivery.json` from anywhere on the disk, so a claim could decide the
    hand-off branch on a file that was never a run's."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    queues = tmp_path / "queues"
    (queues / "real_run").mkdir(parents=True)
    (queues / "real_run" / "delivery.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8")
    # somebody else's handed-off record, reachable only by walking out
    (queues / "real_run" / "nested").mkdir()
    (queues / "real_run" / "nested" / "delivery.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8")

    assert research._claim_is_handed_off("real_run") is True      # ⭐ accept
    assert research._claim_is_handed_off("real_run/nested") is False
    assert research._claim_is_handed_off("../queues/real_run") is False
    assert research._claim_is_handed_off(str(queues / "real_run")) is False
    assert research._claim_is_handed_off("") is False
    assert research._claim_is_handed_off(None) is False


# ════ 3. 542-4 — boot recovery leaves a handed-off run alone ══════════════
def _handed_off_on_disk(tmp_path, monkeypatch, run_id="run-1", status="completed"):
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    d = tmp_path / "queues" / run_id
    d.mkdir(parents=True)
    (d / "delivery.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    return d


def _ongoing_handed_off(rid, run_id="run-1", assigned=1):
    return _Snap(rid, {"deviceId": "dev1", "status": "ongoing",
                       "assignedWorker": assigned, "backendRunId": run_id,
                       "topic": "t"})


def test_a_handed_off_run_is_re_kicked_and_never_stamped(tmp_path, monkeypatch):
    """⛔⛔ THE SECOND HALF OF #542's SCREEN. `_rehydrate_ongoing_for_tree`
    queries status=="ongoing", and a run in its cloud tail is "ongoing" ON
    PURPOSE for the whole of phases 4 and 5. So every restart during a tail
    marked it `paused_backend_restart` — a Resume CTA over an upload that was
    fine — or, on a supervised device, re-enqueued it: a second worker on the
    same research, re-running phase 3, beside a Cloud Run that was finishing the
    first one.

    ⭐ AND SITTING STILL IS NOT THE ANSWER. If the kick never landed, nobody is
    running those phases and no tab is open to notice, so the machine re-fires
    the kick it owns. The route is idempotent through its own claim."""
    _handed_off_on_disk(tmp_path, monkeypatch)
    updates, enqueues = _setup(
        monkeypatch, worker_id=1, fleet=1,
        researches={OWNER: [_ongoing_handed_off(RID)]},
        devices={"dev1": _DevSnap(True, {"supervised": True})},
    )
    kicks = []
    monkeypatch.setattr(research, "_post_fe_p4p5_trigger",
                        lambda uid, rid: kicks.append((uid, rid)))

    r, o, seen = _run(OWNER)
    assert (r, o) == (0, 0), "a handed-off run was counted as recovered here"
    assert updates == [], (
        "the machine wrote over a cloud-owned run — after beDone its status, "
        "phase and fe* fields are the route's")
    assert enqueues == [], "a handed-off run was re-enqueued for a second pass"
    assert kicks == [(OWNER, RID)], "nobody re-fired the kick for a stalled tail"
    assert RID in seen


def test_a_run_that_was_not_handed_off_still_recovers(tmp_path, monkeypatch):
    """⭐⭐ ACCEPT POLARITY, and the thing the guard must not eat: a run whose
    phase 3 never finished is still auto-resumed on a supervised device."""
    _handed_off_on_disk(tmp_path, monkeypatch, status="ongoing")
    updates, enqueues = _setup(
        monkeypatch, worker_id=1, fleet=1,
        researches={OWNER: [_ongoing_handed_off(RID)]},
        devices={"dev1": _DevSnap(True, {"supervised": True})},
    )
    kicks = []
    monkeypatch.setattr(research, "_post_fe_p4p5_trigger",
                        lambda uid, rid: kicks.append((uid, rid)))
    monkeypatch.setattr(research, "load_checkpoint", lambda _d: {"topic": "t"})
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", object())

    r, o, _seen = _run(OWNER)
    assert kicks == [], "a run still mid-phase-3 was handed to the cloud"
    assert (r, o) == (1, 0), "the supervised auto-resume stopped working"
    assert [j["research_id"] for j in enqueues] == [RID]


def test_an_unsupervised_handed_off_run_is_not_marked_paused(tmp_path, monkeypatch):
    """⛔ THE MARK IS THE VISIBLE HALF OF THE BUG — "Backend restarted mid-run,
    hit Resume", over a run the cloud was finishing. It must not fire for a
    handed-off run on ANY device, supervised or not."""
    _handed_off_on_disk(tmp_path, monkeypatch)
    updates, _enqueues = _setup(
        monkeypatch, worker_id=1, fleet=1,
        researches={OWNER: [_ongoing_handed_off(RID)]},
        devices={"dev1": _DevSnap(True, {"supervised": False})},
    )
    monkeypatch.setattr(research, "_post_fe_p4p5_trigger", lambda *a: None)
    r, o, _seen = _run(OWNER)
    assert (r, o) == (0, 0)
    assert updates == []


def test_an_out_of_fleet_handed_off_run_is_not_stamped_either(tmp_path, monkeypatch):
    """⛔ THE WORKER-1 SAFETY NET REACHES FURTHEST, so it is the branch most
    likely to stamp a run nobody on this machine owns. And its log line is said
    AFTER the guard now: it used to announce a paused mark that the guard then
    (correctly) did not make."""
    _handed_off_on_disk(tmp_path, monkeypatch)
    updates, _enqueues = _setup(
        monkeypatch, worker_id=1, fleet=1,
        researches={OWNER: [_ongoing_handed_off(RID, assigned=9)]},
        devices={"dev1": _DevSnap(True, {"supervised": False})},
    )
    said = []
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: said.append(str(msg)))
    monkeypatch.setattr(research, "_post_fe_p4p5_trigger", lambda *a: None)
    r, o, _seen = _run(OWNER)
    assert (r, o) == (0, 0)
    assert updates == []
    assert not any("marking" in m and "paused_backend_restart" in m for m in said), (
        "a paused mark was announced for a run that was never marked")


# ════ 4. 542-5 — a refusal reaches the chat ═══════════════════════════════
class _RefSnap:
    exists = True

    def __init__(self, data):
        self._d = data

    def to_dict(self):
        return dict(self._d)


class _RefRef:
    def __init__(self, data, sink):
        self._d = data
        self._sink = sink

    def get(self):
        return _RefSnap(self._d)

    def update(self, payload):
        self._sink.append(dict(payload))


class _RefDb:
    def __init__(self, data, sink):
        self._d = data
        self._sink = sink

    def collection(self, _n):
        return self

    def document(self, _n):
        return self

    def get(self):
        return _RefSnap(self._d)

    def update(self, payload):
        self._sink.append(dict(payload))


def _record(monkeypatch, existing):
    written = []
    monkeypatch.setattr(research, "_firebase_db", _RefDb(existing, written),
                        raising=False)
    monkeypatch.setattr(research, "_be_payload", lambda p: dict(p))
    monkeypatch.setattr(research, "_grpc_write_with_heal",
                        lambda op, what="": op())
    ok = research._record_cloud_kick_refusal(OWNER, RID, "the cloud said no")
    return ok, written


def test_a_refusal_lands_on_phase_4_and_never_on_fep4state(monkeypatch):
    """⛔⛔ NOT `feP4State`, AND THE ROUTE'S OWN SOURCE SAYS WHY.
    `cloudKickDecision` reads `feP4State`, and any terminal value there means
    "phase 4 has been TRIED": the next hand-off then asks for phase 5 ALONE and
    the Doc and the email go out with no video for an upload that never ran.
    Recording the refusal must not reroute the run that way.

    `phases[4].status` is read by `cloudPhaseRecorded`, which paints the tile —
    and never by `cloudKickDecision`, so a chat opening on this run still
    re-drives BOTH phases."""
    ok, written = _record(monkeypatch, {"phases": [{"phase": 3, "status": "complete"}]})
    assert ok is True
    assert len(written) == 1
    payload = written[0]
    assert set(payload) == {"phases"}, (
        "the refusal wrote a field other than the phases array")
    entry = next(p for p in payload["phases"] if p.get("phase") == 4)
    assert entry["status"] == "errored"
    assert "the cloud said no" in entry["reason"]
    flat = json.dumps(payload)
    assert "feP4State" not in flat and "feP5State" not in flat, (
        "the machine wrote an fe* field on a handed-off run — the next chat "
        "would ask for phase 5 alone and deliver with no video")
    assert "status" not in payload, "the machine wrote the run's own status"
    # ⭐ phase 3's record is carried through, not replaced
    assert {"phase": 3, "status": "complete"} in payload["phases"]


def test_a_refusal_upserts_rather_than_duplicating_phase_4(monkeypatch):
    """A run whose phase 4 already has an entry gets that entry updated — two
    rows for one phase and the surface reading it picks whichever comes first."""
    ok, written = _record(monkeypatch, {"phases": [{"phase": 4, "status": "running"}]})
    assert ok is True
    fours = [p for p in written[0]["phases"] if p.get("phase") == 4]
    assert len(fours) == 1
    assert fours[0]["status"] == "errored"


def test_the_refusal_record_never_raises(monkeypatch):
    """It runs on a detached thread at the end of a hand-off. A failure to write
    it must not take anything else down with it."""
    monkeypatch.setattr(research, "_firebase_db", None, raising=False)
    assert research._record_cloud_kick_refusal(OWNER, RID, "why") is False
    monkeypatch.setattr(research, "_firebase_db", object(), raising=False)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    assert research._record_cloud_kick_refusal("", RID, "why") is False
