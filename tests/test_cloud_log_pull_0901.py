"""Stretch 5C item 3, machine half — the cloud's log lines reach a support bundle.

⛔⛔ WHAT A SUPPORT BUNDLE CONTAINED BEFORE THIS, MEASURED ON THE REAL DISK
2026-09-01: across six run folders the P4/P5 dispatch string appears ZERO times,
while it appears 23 times in the machine-wide `backend.log`. Not one byte of P4
or P5 lived in any run folder — not even the machine's own line saying it had
dispatched them. Phases 4 and 5 execute in the cloud, print to a platform log
nobody cutting a bundle can reach, and vanish.

⛔⛔ AND THE SIGNED DESIGN COULD NOT BE BUILT AS WRITTEN. The item asked for the
lines to be "written into the run's own record so they ride the send-logs
bundle". The collector NEVER READS FIRESTORE: it is disk-only, allow-listed to
under `~/.super-research/logs/`, and a scan of `_build_log_bundle`'s body for any
database call returns zero hits. A field on the run record would have been
collected by nothing — the same shape as the push audit that sat unreadable for
three months. The intent survived; the medium had to change to a FILE in the run
folder, which the collector's existing `rglob("*")` already ships.

The last test in this file is the one that matters most: it builds a real bundle
and opens the zip. Everything above it could pass while the file never shipped.
"""
import json
import time
import zipfile
from pathlib import Path

import pytest

import research


# ── the key that makes a folder addressable ────────────────────────────

def _queue(root, rid, uid):
    d = root / f"q_{rid}"
    d.mkdir(parents=True)
    (d / "owner.json").write_text(json.dumps({"uid": uid, "researchId": rid}),
                                  encoding="utf-8")
    return d


def test_the_owner_map_joins_a_research_to_its_uid(tmp_path):
    _queue(tmp_path, "chat_1", "user-a")
    _queue(tmp_path, "chat_2", "user-b")
    assert research._queue_owner_map(tmp_path) == {"chat_1": "user-a", "chat_2": "user-b"}


def test_a_queue_dir_missing_either_half_is_not_a_key(tmp_path):
    # ⛔ A half key is worse than none: it would address
    # `users//researches/chat_3`, which is a different document path entirely.
    d = tmp_path / "q_broken"
    d.mkdir()
    (d / "owner.json").write_text(json.dumps({"researchId": "chat_3"}), encoding="utf-8")
    assert research._queue_owner_map(tmp_path) == {}


def test_an_unreadable_owner_file_is_skipped_not_fatal(tmp_path):
    _queue(tmp_path, "chat_1", "user-a")
    bad = tmp_path / "q_bad"
    bad.mkdir()
    (bad / "owner.json").write_text("{not json", encoding="utf-8")
    assert research._queue_owner_map(tmp_path) == {"chat_1": "user-a"}


def test_a_missing_queues_directory_is_an_empty_map(tmp_path):
    assert research._queue_owner_map(tmp_path / "nope") == {}


# ── rendering ──────────────────────────────────────────────────────────

def _doc(ts, phase, lines, dropped=0, inv="abcdef1234"):
    return {"type": "cloud_logs", "timestamp": ts, "phase": phase,
            "data": {"lines": lines, "dropped": dropped, "invocation": inv}}


def test_the_records_are_ordered_by_their_own_timestamp():
    # ⛔ THERE IS NO `seq` TO SORT BY, deliberately — its absence is what keeps
    # these documents out of the app's live listener and out of chat's
    # narration. The write time is the only ordering available.
    out = research._render_cloud_log([
        _doc(200, 5, ["second"]),
        _doc(100, 4, ["first"]),
    ])
    assert out.index("first") < out.index("second")


def test_each_invocation_is_labelled_with_its_phase():
    out = research._render_cloud_log([_doc(1, 4, ["x"], inv="deadbeefcafe")])
    assert "cloud phase 4" in out
    assert "deadbeef" in out


def test_lines_dropped_at_the_bound_are_admitted_in_the_file():
    # A truncated artifact that does not say so is a false statement about the
    # run — the same rule the tail filter already follows.
    out = research._render_cloud_log([_doc(1, 4, ["x"], dropped=17)])
    assert "17 further line(s) dropped" in out


def test_a_record_with_no_data_is_skipped_rather_than_crashing():
    assert research._render_cloud_log([{"timestamp": 1, "phase": 4}]).strip() == ""


def test_an_enormous_render_is_truncated_and_says_so():
    big = _doc(1, 4, ["y" * 1000] * 2000)
    out = research._render_cloud_log([big])
    assert len(out) <= research.CLOUD_LOG_MAX_BYTES + 200
    assert "truncated at" in out


# ── the pull ───────────────────────────────────────────────────────────

class _FakeStream:
    def __init__(self, docs):
        self._docs = docs

    def stream(self):
        for d in self._docs:
            yield type("S", (), {"to_dict": staticmethod(lambda d=d: d)})()


def _folder(root, name, rid, mtime_age=0, submitter=None):
    d = root / name
    d.mkdir(parents=True)
    meta = {"researchId": rid, "status": "completed", "attempt": 1}
    if submitter:
        meta["submitterUid"] = submitter
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "run.log").write_text("machine lines\n", encoding="utf-8")
    if mtime_age:
        t = time.time() - mtime_age
        import os as _os
        _os.utime(d, (t, t))
    return d


class _Db:
    """A Firestore stand-in that records the path it was asked for."""

    def __init__(self, docs_by_rid):
        self.docs_by_rid = docs_by_rid
        self.paths = []
        self._parts = []

    def collection(self, name):
        self._parts.append(name)
        return self

    def document(self, key):
        self._parts.append(key)
        return self

    def where(self, **_kw):
        path = "/".join(self._parts)
        self.paths.append(path)
        rid = self._parts[3] if len(self._parts) > 3 else ""
        self._parts = []
        return _FakeStream(self.docs_by_rid.get(rid, []))


def test_the_cloud_lines_land_in_the_run_folder(tmp_path):
    runs = tmp_path / "runs"
    queues = tmp_path / "queues"
    _folder(runs, "chat_1_1_x", "chat_1")
    _queue(queues, "chat_1", "user-a")
    db = _Db({"chat_1": [_doc(1, 4, ["[fe-p4] uploading"])]})
    out = research._pull_cloud_logs(db=db, runs_root=runs, queues_root=queues)
    assert out["updated"] == 1
    body = (runs / "chat_1_1_x" / research.CLOUD_LOG_FILENAME).read_text(encoding="utf-8")
    assert "[fe-p4] uploading" in body


def test_it_asks_for_the_right_document_path(tmp_path):
    runs = tmp_path / "runs"
    queues = tmp_path / "queues"
    _folder(runs, "chat_1_1_x", "chat_1")
    _queue(queues, "chat_1", "user-a")
    db = _Db({"chat_1": [_doc(1, 4, ["x"])]})
    research._pull_cloud_logs(db=db, runs_root=runs, queues_root=queues)
    assert db.paths == ["users/user-a/researches/chat_1/pipeline_events"]


def test_a_folder_with_no_owner_anywhere_is_counted_not_silently_skipped(tmp_path):
    # ⛔ THE MEASURED MAJORITY CASE. Five of the six run folders on this machine
    # carry neither submitterUid nor claimedBy, and their queue dirs are gone —
    # so nothing on disk can name the owner. Reporting only "updated 0" would
    # read as "the cloud sent nothing".
    runs = tmp_path / "runs"
    queues = tmp_path / "queues"
    queues.mkdir()
    _folder(runs, "chat_1_1_x", "chat_1")
    db = _Db({})
    out = research._pull_cloud_logs(db=db, runs_root=runs, queues_root=queues)
    assert out == {"updated": 0, "unattributable": 1, "queried": 0}


def test_a_meta_that_names_its_submitter_needs_no_queue_dir(tmp_path):
    runs = tmp_path / "runs"
    queues = tmp_path / "queues"
    queues.mkdir()
    _folder(runs, "chat_1_1_x", "chat_1", submitter="user-z")
    db = _Db({"chat_1": [_doc(1, 5, ["[fe-p5] doc created"])]})
    out = research._pull_cloud_logs(db=db, runs_root=runs, queues_root=queues)
    assert out["updated"] == 1
    assert db.paths == ["users/user-z/researches/chat_1/pipeline_events"]


def test_a_run_older_than_the_window_is_not_queried(tmp_path):
    # P4/P5 finish minutes after the pipeline, not days. Querying every folder
    # every quarter hour would be a Firestore read per run forever.
    runs = tmp_path / "runs"
    queues = tmp_path / "queues"
    _folder(runs, "old_1_1_x", "chat_old", mtime_age=research.CLOUD_LOG_PULL_WINDOW_SEC + 3600)
    _queue(queues, "chat_old", "user-a")
    db = _Db({"chat_old": [_doc(1, 4, ["x"])]})
    out = research._pull_cloud_logs(db=db, runs_root=runs, queues_root=queues)
    assert out["queried"] == 0
    assert db.paths == []


def test_no_more_than_the_cap_is_queried_on_one_tick(tmp_path):
    runs = tmp_path / "runs"
    queues = tmp_path / "queues"
    queues.mkdir()
    for i in range(research.CLOUD_LOG_PULL_MAX_FOLDERS + 5):
        _folder(runs, f"chat_{i}_1_x", f"chat_{i}", submitter="u")
    db = _Db({})
    research._pull_cloud_logs(db=db, runs_root=runs, queues_root=queues)
    assert len(db.paths) <= research.CLOUD_LOG_PULL_MAX_FOLDERS


def test_nothing_to_pull_writes_no_file(tmp_path):
    runs = tmp_path / "runs"
    queues = tmp_path / "queues"
    _folder(runs, "chat_1_1_x", "chat_1")
    _queue(queues, "chat_1", "user-a")
    db = _Db({})
    out = research._pull_cloud_logs(db=db, runs_root=runs, queues_root=queues)
    assert out["updated"] == 0
    assert not (runs / "chat_1_1_x" / research.CLOUD_LOG_FILENAME).exists()


def test_an_unchanged_pull_does_not_touch_the_folder(tmp_path):
    # ⛔⛔ THE FOLDER'S mtime IS LOAD-BEARING. It is what the age bound reads and
    # what the bundle's own run selection sorts by, so rewriting an identical
    # file every fifteen minutes would keep a finished run looking freshly
    # touched for as long as the machine stayed up — and it would never age out.
    runs = tmp_path / "runs"
    queues = tmp_path / "queues"
    d = _folder(runs, "chat_1_1_x", "chat_1")
    _queue(queues, "chat_1", "user-a")
    db = _Db({"chat_1": [_doc(1, 4, ["x"])]})
    assert research._pull_cloud_logs(db=db, runs_root=runs, queues_root=queues)["updated"] == 1
    target = d / research.CLOUD_LOG_FILENAME
    before = target.stat().st_mtime_ns
    db2 = _Db({"chat_1": [_doc(1, 4, ["x"])]})
    assert research._pull_cloud_logs(db=db2, runs_root=runs, queues_root=queues)["updated"] == 0
    assert target.stat().st_mtime_ns == before


def test_new_lines_do_replace_the_file(tmp_path):
    # The other polarity: a pull that never rewrote would be a cache, not a
    # pull, and P5's lines arrive after P4's.
    runs = tmp_path / "runs"
    queues = tmp_path / "queues"
    d = _folder(runs, "chat_1_1_x", "chat_1")
    _queue(queues, "chat_1", "user-a")
    research._pull_cloud_logs(db=_Db({"chat_1": [_doc(1, 4, ["p4 only"])]}),
                              runs_root=runs, queues_root=queues)
    research._pull_cloud_logs(db=_Db({"chat_1": [_doc(1, 4, ["p4 only"]),
                                                 _doc(2, 5, ["p5 arrived"])]}),
                              runs_root=runs, queues_root=queues)
    body = (d / research.CLOUD_LOG_FILENAME).read_text(encoding="utf-8")
    assert "p5 arrived" in body and "p4 only" in body


def test_with_no_firestore_it_does_nothing_rather_than_raising(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    assert research._pull_cloud_logs(db=None, runs_root=runs,
                                     queues_root=tmp_path / "q")["updated"] == 0


# ── the trigger ────────────────────────────────────────────────────────

def test_the_pull_is_throttled_off_the_five_second_heartbeat():
    research._cloud_pull_next_ms = 0
    now = 7_000_000
    assert research._cloud_pull_due(now) is True
    assert research._cloud_pull_due(now + 1) is False
    assert research._cloud_pull_due(now + research.CLOUD_LOG_PULL_INTERVAL_SEC * 1000) is True


def test_the_heartbeat_is_what_calls_the_pull():
    # ⛔ THE CONSUMER. A puller nothing calls is the shape of defect this whole
    # stretch keeps finding. Source pin, and labelled as one: the heartbeat is a
    # nested async def inside the server entrypoint.
    src = Path(research.__file__).read_text(encoding="utf-8")
    hb = src[src.index("async def _heartbeat_loop"):]
    hb = hb[:hb.index("\nasync def ", 10)]
    assert "_cloud_pull_due(" in hb
    assert "_pull_cloud_logs" in hb


# ── and the one that proves the item ───────────────────────────────────

def test_the_cloud_log_actually_rides_the_bundle(tmp_path, monkeypatch):
    """⭐⭐ THE ONE THAT PROVES THE ITEM. Everything above can pass while the
    file never leaves the disk. This builds a REAL bundle and opens the zip.

    It also proves the claim the whole design rests on — that the collector
    ships any file in a run folder through its existing `rglob("*")`, so no
    collector change and no bundle-contract edit was needed. The contract is
    pinned byte-identical in both repos and by SHA-256 in this suite; if that
    claim had been wrong, this item would have been a four-file, two-repo change
    instead of a new file in a folder."""
    root = tmp_path / "logs"
    (root / "sessions").mkdir(parents=True)
    runs = root / "runs"
    d = _folder(runs, "chat_1_1_20260901T000000", "chat_1")
    (d / research.CLOUD_LOG_FILENAME).write_text(
        "── cloud phase 4 · invocation abcd1234 ──\n[fe-p4] upload complete\n",
        encoding="utf-8")
    monkeypatch.setattr(research, "_logs_root", lambda: root)
    dest = tmp_path / "bundle.zip"
    research._build_log_bundle(dest)
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        member = f"runs/chat_1_1_20260901T000000/{research.CLOUD_LOG_FILENAME}"
        assert member in names, f"cloud log not in the bundle: {names}"
        body = zf.read(member).decode()
    assert "[fe-p4] upload complete" in body
    # ⭐ CLUBBED WITH THAT RUN'S MACHINE LOGS, which is the wording of the item —
    # not shipped as a separate thing beside them.
    assert "runs/chat_1_1_20260901T000000/run.log" in names


@pytest.mark.parametrize("name", ["meta.json", "run.log"])
def test_the_run_folder_still_carries_what_it_always_did(name, tmp_path, monkeypatch):
    # The cloud file is an addition. A regression that displaced a member would
    # trade one half of the run for the other.
    root = tmp_path / "logs"
    (root / "sessions").mkdir(parents=True)
    d = _folder(root / "runs", "chat_1_1_x", "chat_1")
    (d / research.CLOUD_LOG_FILENAME).write_text("cloud\n", encoding="utf-8")
    monkeypatch.setattr(research, "_logs_root", lambda: root)
    dest = tmp_path / "b.zip"
    research._build_log_bundle(dest)
    with zipfile.ZipFile(dest) as zf:
        assert f"runs/chat_1_1_x/{name}" in zf.namelist()
