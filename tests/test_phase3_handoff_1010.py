"""Phase 3 ends at the hand-off, and the late phase-3 save writes what it was given.

Wave 10.10, the rest of "Analytics shows phase and agent times even for runs
nobody watched" (phases 0-2 and each agent's time: `test_analytics_times_1010.py`).

⛔⛔ 1. PHASE 3 HAD NO END ON A RUN THAT FINISHED NORMALLY. Only a stop saved
phase 3 closed. On a normal finish the phase-3 thread closed it early — before
the no-audio retries and before `phase_complete` — and then the status write
that `phase_complete` fires, a read-modify-write on a daemon thread, landed the
array it had READ over the whole-array write. The web's timeline module measured
what was left (dg-research `src/lib/analytics-timeline.ts`): phase 3 "complete",
a generic "Phase 3" label, a `startedAt` that is really when the phase finished,
no end and no duration.

⭐ The hand-off is phase 3's end, and it already makes one write — `beDone`. The
row now rides in that write (`_record_hand_off`), and the machine's writers of
the phase list take one lock across their read and their write, so the status
write can no longer land a stale array over it.

⛔⛔ 2. AFTER THE HAND-OFF THE MACHINE WRITES NO PHASE LIST. Phases 4 and 5 are
the cloud's; the web stamps their rows by read-modify-write. The phase-3 thread
usually lands after the hand-off, and it used to write `phases`, `status` and
`phase` — a whole-array replace over the web's rows and a `phase: 3` dragging
the pointer back off the upload. It now writes what it scanned and nothing about
where the run is.

⛔⛔ 3. THE LATE SAVE NAMED ITS RESEARCH AT DISPATCH BUT READ ITS DATA AT WRITE
TIME. The next run's `_runtime.reset()` empties the panel sources, curves and
findings the thread reads, so the late write put empty findings — or the next
run's — on its own run's record. The data is copied at dispatch now.

▶ EXECUTED. The real helpers against a record double that applies `update()` the
way Firestore does, real threads where the defect is a race, and the pipeline's
own hand-off statements lifted out of `run_pipeline`'s parse tree and run — a
5,000-line coroutine nothing can drive to its tail. One pin reads the parse tree
without running it, and says so.
"""
import ast
import inspect
import json
import os
import textwrap
import threading
import time
import types

import pytest

import research
from conftest import apply_firestore_update

TOPIC = "Grid storage"
UID = "uid-1"
RID = "chat_1758400000000_1"
MIN = 60_000


class _Snap:
    def __init__(self, data):
        self._data = json.loads(json.dumps(data))
        self.exists = True

    def to_dict(self):
        return self._data


class _Record:
    """One research document. `get()` answers with a copy as of the call;
    `update()` is applied the way Firestore applies it.

    `hold` parks the NEXT read after it has taken its copy — the window a
    read-modify-write has between its read and its write."""

    def __init__(self):
        self.data = {}
        self.patches = []
        self.hold = None
        self.parked = threading.Event()
        self.refuse_reads = False

    def collection(self, _name):
        return self

    def document(self, _id):
        return self

    def get(self):
        if self.refuse_reads:
            raise RuntimeError("read refused")
        snap = _Snap(self.data)
        if self.hold is not None:
            gate, self.hold = self.hold, None
            self.parked.set()
            gate.wait(10)
        return snap

    def update(self, patch):
        self.patches.append(dict(patch))
        apply_firestore_update(self.data, json.loads(json.dumps(patch)))


@pytest.fixture
def record(monkeypatch):
    r = _Record()
    monkeypatch.setattr(research, "_firebase_db", r)
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_fb_research_id", RID)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-1")
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "_agent_status_by_rid", {}, raising=False)
    monkeypatch.setattr(research, "_phase_status_by_rid", {}, raising=False)
    monkeypatch.setattr(research, "_runtime", research.PipelineRuntime())
    return r


@pytest.fixture
def run_dir(tmp_path):
    """A run folder whose creation files are backdated: the run began 30 min ago."""
    d = tmp_path / "Grid_storage_20260923_120000"
    (d / "documents").mkdir(parents=True)
    started = time.time() - 1800
    for name in ("config.json", "owner.json"):
        p = d / name
        p.write_text("{}")
        os.utime(p, (started, started))
    return d, int(started * 1000)


def _meta(d):
    return json.loads((d / "meta.json").read_text(encoding="utf-8"))


def _rows(record):
    return {r["phase"]: r for r in record.data.get("phases", [])}


def _after_phase_two(d, record, run_start):
    """What the machine leaves on disk and on the record once phase 2 is saved:
    rows 0-2 closed, each with its status. Phase 3 began 20 minutes in."""
    rows = [
        {"phase": 0, "label": "Initializing", "startedAt": run_start,
         "completedAt": run_start + 2 * MIN, "durationSec": 120, "status": "complete"},
        {"phase": 1, "label": "Research Brief", "startedAt": run_start + 2 * MIN,
         "completedAt": run_start + 5 * MIN, "durationSec": 180, "status": "complete"},
        {"phase": 2, "label": "Deep Research", "startedAt": run_start + 5 * MIN,
         "completedAt": run_start + 19 * MIN, "durationSec": 840, "status": "complete"},
    ]
    (d / "meta.json").write_text(json.dumps(
        {"id": d.name, "createdAt": run_start, "status": "ongoing", "phase": 2,
         "phases": rows}), encoding="utf-8")
    record.data.update({"status": "ongoing", "phase": 3, "currentPhase": 3,
                        "phases": json.loads(json.dumps(rows))})
    for p in (0, 1, 2):
        research._record_terminal_status(research._phase_status_by_rid, RID, p, "complete")
    return run_start + 20 * MIN


def _phase_three_completes():
    """What `phase_complete:3`'s hook does: record the status, then write it."""
    research._record_terminal_status(research._phase_status_by_rid, RID, 3, "complete")
    research._do_phase_terminal_status_write(3, "complete")


def _handoff_patch(record):
    [patch] = [p for p in record.patches if "beDone" in p]
    return patch


# ══ 1. phase 3 ends in the hand-off's own write ═══════════════════════════

def test_a_normal_finish_leaves_phase_three_with_an_end_and_a_duration(run_dir, record):
    """⛔⛔ THE DEFECT. The status write has already put its stub row on the
    record — no end, no duration, "Phase 3" — and the hand-off closes it."""
    d, run_start = run_dir
    began = _after_phase_two(d, record, run_start)
    _phase_three_completes()
    assert "completedAt" not in _rows(record)[3], "the stub this test starts from"

    research._record_hand_off(d, (UID, RID), began)

    row = _rows(record)[3]
    assert row["startedAt"] == began
    assert isinstance(row["completedAt"], int) and row["completedAt"] > began
    assert row["durationSec"] == (row["completedAt"] - began) // 1000
    assert 595 <= row["durationSec"] <= 700, row
    assert row["status"] == "complete"
    assert row["label"] == "Links + NotebookLM + Audio"
    assert record.data["beDone"] is True
    assert record.data["beDoneAt"] == row["completedAt"], "phase 3 ends AT the hand-off"
    # one write carries both — there is no later machine write to race anything
    patch = _handoff_patch(record)
    assert patch["beDone"] is True and "phases" in patch
    # and the disk says the same
    disk = _meta(d)["phases"][3]
    assert {k: disk[k] for k in ("startedAt", "completedAt", "durationSec")} == {
        k: row[k] for k in ("startedAt", "completedAt", "durationSec")}


def test_a_phase_three_row_is_added_when_the_record_has_none(run_dir, record):
    """The hand-off can land before the status write does."""
    d, run_start = run_dir
    began = _after_phase_two(d, record, run_start)
    research._record_terminal_status(research._phase_status_by_rid, RID, 3, "complete")
    research._record_hand_off(d, (UID, RID), began)
    [row] = [r for r in record.data["phases"] if r["phase"] == 3]
    assert row["startedAt"] == began and isinstance(row["completedAt"], int)
    assert row["status"] == "complete"


def test_the_hand_off_changes_no_row_but_phase_threes(run_dir, record):
    """⛔⛔ Phases 4 and 5 are the cloud's. A watched run's browser can have the
    route stamp a row before this write lands; every row but phase 3's goes back
    exactly as it was read, and phase 3 is not duplicated."""
    d, run_start = run_dir
    began = _after_phase_two(d, record, run_start)
    _phase_three_completes()
    record.data["phases"] += [
        {"phase": 4, "status": "skipped", "reason": "phase_off",
         "completedAt": run_start + 29 * MIN, "label": "YouTube Upload"},
        {"phase": 5, "status": "running", "label": "Delivery"},
    ]
    before = {p: r for p, r in _rows(record).items() if p != 3}

    research._record_hand_off(d, (UID, RID), began)

    after = _rows(record)
    assert {p: r for p, r in after.items() if p != 3} == before
    assert [r["phase"] for r in record.data["phases"]].count(3) == 1


def test_a_resume_that_ran_phase_three_again_ends_it_here(run_dir, record):
    """⛔ A stop saved phase 3 closed at the stop. This attempt ran phase 3 again
    from `began`, so the row is this attempt's span — not the old one kept."""
    d, run_start = run_dir
    _after_phase_two(d, record, run_start)
    meta = _meta(d)
    meta["phases"].append({"phase": 3, "label": "Links + NotebookLM + Audio",
                           "startedAt": run_start + 20 * MIN,
                           "completedAt": run_start + 22 * MIN, "durationSec": 120})
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    began = run_start + 25 * MIN

    research._record_hand_off(d, (UID, RID), began)

    row = _rows(record)[3]
    assert row["startedAt"] == began
    assert row["completedAt"] > run_start + 29 * MIN


def test_a_run_that_skipped_phases_one_and_two_still_gets_phase_three(run_dir, record):
    """Nothing saved a meta.json before phase 3 on this run."""
    d, run_start = run_dir
    began = run_start + 3 * MIN
    research._record_hand_off(d, (UID, RID), began)
    row = _rows(record)[3]
    assert row["startedAt"] == began and isinstance(row["completedAt"], int)
    assert _meta(d)["phases"][3]["startedAt"] == began


# ── accept polarity: nothing is invented, and the hand-off always lands ──

def _unchanged(d, record, run_start, began):
    before_disk = (d / "meta.json").read_bytes()
    before_rows = json.loads(json.dumps(record.data["phases"]))
    research._record_hand_off(d, (UID, RID), began)
    patch = _handoff_patch(record)
    assert patch["beDone"] is True and isinstance(patch["beDoneAt"], int)
    assert "phases" not in patch, "a phase list was written with no true start to write"
    assert record.data["phases"] == before_rows
    assert (d / "meta.json").read_bytes() == before_disk


def test_a_phase_three_that_did_not_run_here_gets_no_row(run_dir, record):
    """⭐ Skipped, or resumed past: the write is the hand-off alone, as before."""
    d, run_start = run_dir
    _after_phase_two(d, record, run_start)
    _unchanged(d, record, run_start, None)


@pytest.mark.parametrize("bad", [
    pytest.param("before", id="before-the-run-began"),
    pytest.param("future", id="after-the-hand-off"),
    pytest.param("seconds", id="in-seconds-not-ms"),
    pytest.param("text", id="a-string"),
])
def test_a_start_that_cannot_be_true_is_no_start(run_dir, record, bad):
    d, run_start = run_dir
    _after_phase_two(d, record, run_start)
    began = {"before": run_start - MIN,
             "future": int(time.time() * 1000) + 60 * MIN,
             "seconds": (run_start + 20 * MIN) // 1000,
             "text": str(run_start + 20 * MIN)}[bad]
    _unchanged(d, record, run_start, began)


def test_the_hand_off_lands_when_the_record_cannot_be_read(run_dir, record):
    """⛔ `beDone` is what stops a restart stamping a run the cloud is finishing.
    A refused read costs phase 3's row, never the hand-off."""
    d, run_start = run_dir
    began = _after_phase_two(d, record, run_start)
    record.refuse_reads = True
    research._record_hand_off(d, (UID, RID), began)
    assert record.data["beDone"] is True
    assert "phases" not in _handoff_patch(record)


def test_a_meta_file_it_cannot_use_never_stops_the_hand_off(run_dir, record):
    d, run_start = run_dir
    _after_phase_two(d, record, run_start)
    (d / "meta.json").write_text(json.dumps({"id": d.name, "createdAt": run_start,
                                             "phases": {"3": "not a list"}}))
    research._record_hand_off(d, (UID, RID), run_start + 20 * MIN)
    assert record.data["beDone"] is True
    assert "phases" not in _handoff_patch(record)


# ══ 2. one machine writer of the phase list at a time ════════════════════

def test_a_status_write_that_read_first_cannot_erase_phase_threes_end(run_dir, record):
    """⛔⛔ THE RACE, RUN. `phase_complete:3`'s status write reads the array and
    is parked there; the hand-off comes in behind it. Without one lock across
    each writer's read and write, the hand-off lands its row and the status
    write then lands the array it READ — the stub with no end, which is what
    the web measured."""
    d, run_start = run_dir
    began = _after_phase_two(d, record, run_start)
    research._record_terminal_status(research._phase_status_by_rid, RID, 3, "complete")
    gate = threading.Event()
    record.hold = gate
    status = threading.Thread(target=research._do_phase_terminal_status_write,
                              args=(3, "complete"), daemon=True)
    status.start()
    assert record.parked.wait(5), "the status write never read the record"
    handoff = threading.Thread(target=research._record_hand_off,
                               args=(d, (UID, RID), began), daemon=True)
    handoff.start()
    handoff.join(1.0)   # behind the lock it waits here; without one it is done
    gate.set()
    status.join(5)
    handoff.join(5)
    assert not status.is_alive() and not handoff.is_alive()

    row = _rows(record)[3]
    assert row.get("completedAt"), f"phase 3's end was written over: {row}"
    assert row["startedAt"] == began
    assert row["status"] == "complete"


def test_a_status_write_that_read_first_cannot_erase_phase_twos_end(run_dir, record):
    """The same race one phase earlier: `phase_complete:2` fires its status
    write before `save_meta` closes phase 2 with a whole-array write."""
    d, run_start = run_dir
    research.save_meta(d, TOPIC, 1, summary="x", started_ms=run_start + 2 * MIN)
    research._record_terminal_status(research._phase_status_by_rid, RID, 2, "complete")
    gate = threading.Event()
    record.hold = gate
    status = threading.Thread(target=research._do_phase_terminal_status_write,
                              args=(2, "complete"), daemon=True)
    status.start()
    assert record.parked.wait(5), "the status write never read the record"
    save = threading.Thread(target=research.save_meta, args=(d, TOPIC, 2), daemon=True)
    save.start()
    save.join(1.0)
    gate.set()
    status.join(5)
    save.join(5)
    assert not status.is_alive() and not save.is_alive()

    row = _rows(record)[2]
    assert row.get("completedAt"), f"phase 2's end was written over: {row}"
    assert row["status"] == "complete"


# ══ 3. the late phase-3 save ═════════════════════════════════════════════

FINDING_A = {"url": "https://grid.example.org/transmission",
             "snippet": "Transmission is the binding constraint.",
             "sourceTitle": "Grid study"}
FINDING_B = {"url": "https://other.example.org/divorce",
             "snippet": "Somebody else's research.", "sourceTitle": "Other"}


class _Probe:
    """The podcast scan — ffprobe, a few seconds a file — parked until released."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, _path):
        self.entered.set()
        self.release.wait(10)
        return 1500


@pytest.fixture
def late_save(run_dir, record, monkeypatch):
    """Dispatch the REAL phase-3 save; returns (probe, join)."""
    d, _ = run_dir
    (d / "documents" / "claude.md").write_text(
        "## Findings\n\nTransmission, not generation, is the binding constraint "
        "in most of the markets studied, and permitting sets its pace.\n",
        encoding="utf-8")
    (d / "podcasts").mkdir()
    (d / "podcasts" / "Deep_Dive.mp3").write_bytes(b"audio")
    probe = _Probe()
    monkeypatch.setattr(research, "_audio_duration_sec", probe)
    made = []

    class _Kept(threading.Thread):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)

    monkeypatch.setattr(research, "_threading", types.SimpleNamespace(Thread=_Kept))

    def join():
        probe.release.set()
        [t] = made
        t.join(10)
        assert not t.is_alive(), "the phase-3 save never finished"
    return probe, join


def _this_runs_data(rt):
    rt.agent_findings["claude"] = [dict(FINDING_A)]
    rt.agent_progress_history["claude"] = [{"t": i * 1000, "sources": i} for i in range(5)]
    rt.agent_progress_snapshots["claude"] = {
        "searches": 7, "observed_sources": 3,
        "source_urls": ["https://grid.example.org/transmission"]}


@pytest.mark.parametrize("after", [
    pytest.param("reset", id="the-next-run-resets-the-runtime"),
    pytest.param("in-place", id="the-runtime-changes-in-place"),
])
def test_the_phase_three_save_writes_what_it_was_dispatched_with(
        run_dir, record, late_save, after):
    """⛔⛔ THE DEFECT. The thread is parked in its podcast scan while the run
    ends and the next one starts on this worker; what it writes must be what its
    own run had when it was dispatched — not empty, and not the next run's."""
    d, _ = run_dir
    probe, join = late_save
    rt = research._runtime
    _this_runs_data(rt)

    research._save_meta_in_background(d, TOPIC, 3)
    assert probe.entered.wait(5), "the save never reached its podcast scan"
    if after == "reset":
        rt.reset()                                   # what the next run does first
        rt.agent_findings["claude"] = [dict(FINDING_B)]
        rt.agent_progress_snapshots["claude"] = {
            "searches": 1, "source_urls": ["https://other.example.org/divorce"]}
    else:
        rt.agent_findings["claude"][:] = [dict(FINDING_B)]
        rt.agent_progress_history["claude"].clear()
        rt.agent_progress_snapshots["claude"]["searches"] = 1
        rt.agent_progress_snapshots["claude"]["source_urls"][:] = [
            "https://other.example.org/divorce"]
    join()

    claude = record.data["agents"]["claude"]
    assert claude["findings"] == [FINDING_A]
    assert claude["searches"] == 7
    assert claude["observedSources"] == 3
    assert "https://grid.example.org/transmission" in claude["sourceUrls"]
    assert "https://other.example.org/divorce" not in claude["sourceUrls"]
    assert len(claude["progressHistory"]) == 5


def test_the_late_save_leaves_the_hand_off_and_the_clouds_rows_alone(
        run_dir, record, late_save):
    """⛔⛔ It is dispatched before the hand-off and lands after it — after the
    route has claimed phase 4 and stamped its rows. It writes what it scanned
    and nothing about where the run is: not the phase list, not `phase`, not
    `status` — in the cloud or on disk."""
    d, run_start = run_dir
    probe, join = late_save
    began = _after_phase_two(d, record, run_start)
    _this_runs_data(research._runtime)

    research._save_meta_in_background(d, TOPIC, 3)
    assert probe.entered.wait(5), "the save never reached its podcast scan"
    research._record_hand_off(d, (UID, RID), began)
    # the cloud takes over: phase 4 claimed, both rows stamped, the run finished
    record.data.update({"phase": 5, "currentPhase": 5, "status": "completed"})
    record.data["phases"] += [
        {"phase": 4, "status": "complete", "label": "YouTube Upload", "durationSec": 240},
        {"phase": 5, "status": "complete", "label": "Delivery", "durationSec": 60}]
    cloud_before = json.loads(json.dumps(
        {k: record.data[k] for k in ("phases", "phase", "currentPhase", "status")}))
    disk_row3 = _meta(d)["phases"][3]
    join()

    assert {k: record.data[k] for k in ("phases", "phase", "currentPhase", "status")} \
        == cloud_before
    assert _meta(d)["phases"][3] == disk_row3, "the hand-off's end was lost on disk"
    assert _meta(d)["status"] == "ongoing" and _meta(d)["phase"] == 2
    # …and it still wrote what it scanned
    assert record.data["agents"]["claude"]["outputChars"] > 0
    assert _meta(d)["audios"][0]["durationSec"] == 1500


# ══ 4. the pipeline's own hand-off, run ══════════════════════════════════
#
# ⛔⛔ A TESTED HELPER IS NOT A TESTED CONSUMER. Every pin above calls the helper
# with a start it picked; the pipeline could still make the old bare `beDone`
# write, or hand the helper nothing, with all of them green. The statements are
# lifted out of `run_pipeline`'s parse tree and executed as they are.

def _calls(node, name, *args):
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
                and [getattr(a, "value", None) for a in n.args[:len(args)]] == list(args)):
            return True
    return False


def _pipeline():
    return ast.parse(textwrap.dedent(inspect.getsource(research.run_pipeline))).body[0]


def _main_try(fn):
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)
             and any(_calls(s, "_dom_summary", "run complete") for s in n.body)]
    assert len(tries) == 1, f"expected ONE try whose body completes the run, found {len(tries)}"
    return tries[0]


def _hand_off_statements():
    """From `update_delivery(status="completed")` up to the cloud kick, as a
    function of no arguments whose free names are globals."""
    body = _main_try(_pipeline()).body

    def _is_delivery(s):
        return (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                and getattr(s.value.func, "id", "") == "update_delivery"
                and any(k.arg == "status" and getattr(k.value, "value", None) == "completed"
                        for k in s.value.keywords))
    [start] = [i for i, s in enumerate(body) if _is_delivery(s)]
    end = next(i for i, s in enumerate(body) if i > start and isinstance(s, ast.Try)
               and _calls(s, "_post_fe_p4p5_trigger"))
    shell = ast.parse("def _tail():\n    pass\n")
    shell.body[0].body = body[start:end]
    ast.fix_missing_locations(shell)
    return compile(shell, research.__file__, "exec")


def _run_tail(d, p3_start):
    delivered = []
    scope = {**vars(research), "queue_dir": d, "_p3_start": p3_start,
             "update_delivery": lambda **kw: delivered.append(kw)}
    exec(_hand_off_statements(), scope)
    scope["_tail"]()
    assert delivered == [{"status": "completed"}]


def test_the_pipelines_hand_off_ends_phase_three(run_dir, record):
    """⛔⛔ THE CONSUMER. Against the tail before this wave — a bare `beDone`
    write — phase 3 here keeps the status write's stub: no end, no duration."""
    d, run_start = run_dir
    _after_phase_two(d, record, run_start)
    _phase_three_completes()
    p3_start = time.time() - 595

    _run_tail(d, p3_start)

    row = _rows(record)[3]
    assert row["startedAt"] == int(p3_start * 1000)
    assert isinstance(row["completedAt"], int)
    assert 590 <= row["durationSec"] <= 700, row
    assert record.data["beDone"] is True


def test_a_pipeline_that_did_not_run_phase_three_hands_off_without_a_row(run_dir, record):
    """⭐ ACCEPT POLARITY, through the consumer: phase 3 skipped or resumed past."""
    d, run_start = run_dir
    _after_phase_two(d, record, run_start)
    before = json.loads(json.dumps(record.data["phases"]))
    _run_tail(d, None)
    assert record.data["beDone"] is True
    assert "phases" not in _handoff_patch(record)
    assert record.data["phases"] == before


def test_the_pipeline_binds_the_phase_three_start_before_any_phase_runs():
    """⚠ READ, NOT RUN — the one pin here that is. A run that skips phase 3 or
    resumes past it never assigns `_p3_start` in phase 3's branch, and the tail
    reads it; without a binding at the top of the function the hand-off raises
    `UnboundLocalError` into the crash card. Nothing short of driving the whole
    coroutine could execute that path, so the binding is checked where it must
    be: in the function's own top-level body, before the main `try`."""
    fn = _pipeline()
    main = _main_try(fn)
    [at_main] = [i for i, s in enumerate(fn.body) if s is main]
    binds = [i for i, s in enumerate(fn.body)
             if isinstance(s, ast.Assign) and len(s.targets) == 1
             and getattr(s.targets[0], "id", "") == "_p3_start"
             and isinstance(s.value, ast.Constant) and s.value.value is None]
    assert binds and binds[0] < at_main, (
        "`_p3_start = None` must be bound at the top of run_pipeline, before the "
        "main try — or a run that skips phase 3 cannot hand off")
