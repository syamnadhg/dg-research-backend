"""The Research Brief always reported zero seconds.

From the 2026-08-11 run's own meta.json:

    {"phase": 0, "label": "Initializing",   "startedAt": …016732, "completedAt": null,    "durationSec": 0}
    {"phase": 1, "label": "Research Brief", "startedAt": …016732, "completedAt": …016733, "durationSec": 0}
    {"phase": 2, "label": "Deep Research",  "startedAt": …016733, "completedAt": …058973, "durationSec": 1042}

Phases 2 and 3 are right. Phase 1 ran from 18:45 to 19:00 — the longest single
wait in the run, and the one the owner actually sits through — and is recorded
as instantaneous, one millisecond wide.

WHY, AND WHY IT HAPPENS EVERY TIME

`save_meta` stamps `createdAt` with `now` on its first write, and backfilled
phases take their `startedAt` from `createdAt`. The first write is the END of
Phase 1. So on every run: meta.json is born at 19:00, Phase 0 and Phase 1 are
backfilled as starting at 19:00, Phase 1 is immediately marked complete at
19:00, and its duration is zero by construction. Phase 2 escapes only because
its start comes from Phase 1's completedAt.

Not a rounding error, not intermittent — structural, and guaranteed.

THE FIX IS TO THE CAUSE, NOT THE SYMPTOM

`createdAt` now comes from when the run's own directory was laid down.
`config.json` and `owner.json` are written once at queue-dir creation and never
touched again, so the earlier of the two is the run's true start. Nothing about
the phase arithmetic changed; it was always correct given a correct start.

Deliberately NOT changed: meta.json ending a successful run at
`status: "ongoing"` while delivery.json says `completed`. That is not a defect.
Phases 4 and 5 are stamped by the frontend, so from the backend's side the
pipeline genuinely is not over when it writes its last meta at Phase 3, and
delivery.json records a different thing — the backend's own delivery outcome.
"""
import inspect
import json
import os
import time

import pytest

import research


@pytest.fixture
def run_dir(tmp_path):
    """A queue dir shaped like a real one, whose creation files are backdated
    to a known run start."""
    d = tmp_path / "Some_Topic_20260811_184519"
    (d / "documents").mkdir(parents=True)
    started = time.time() - 1200          # the run began 20 minutes ago
    for name in ("config.json", "owner.json"):
        p = d / name
        p.write_text("{}")
        os.utime(p, (started, started))
    return d, int(started * 1000)


# --------------------------------------------------------- the run's start


def test_the_run_start_comes_from_the_files_written_when_it_started(run_dir):
    d, started_ms = run_dir
    assert abs(research._run_started_ms(d) - started_ms) < 2000


def test_the_run_start_is_not_now(run_dir):
    """⭐ THE BUG. `now` is the end of Phase 1, a quarter of an hour late."""
    d, started_ms = run_dir
    assert research._run_started_ms(d) < int(time.time() * 1000) - 600_000


def test_the_earlier_of_the_two_creation_files_wins(run_dir, tmp_path):
    """owner.json is written a beat after config.json. Either could be the one
    that survives a restart, so take the earlier rather than the first found."""
    d, started_ms = run_dir
    later = (started_ms / 1000) + 300
    os.utime(d / "config.json", (later, later))
    assert abs(research._run_started_ms(d) - started_ms) < 2000


def test_a_directory_with_no_creation_files_falls_back_to_now(tmp_path):
    """Exactly the old behaviour — a fallback must never be worse than what it
    replaced, and must never raise on a half-built dir."""
    d = tmp_path / "empty_run"
    d.mkdir()
    assert abs(research._run_started_ms(d) - int(time.time() * 1000)) < 2000


def test_an_unreadable_directory_does_not_raise(tmp_path):
    assert research._run_started_ms(tmp_path / "does_not_exist") > 0


def test_a_path_that_cannot_even_be_built_does_not_raise():
    """⭐ The previous test does not reach the except at all — a missing path
    answers `exists()` False without erroring, so `except: pass` was never
    exercised and a mutant that re-raised there survived. This argument fails
    inside the try, where a real stat error would.

    It matters because this helper runs on the meta-writing path of every phase
    completion, including the daemon thread Phase 3 spawns. An exception here
    would take out the run's whole record over a filesystem hiccup."""
    assert research._run_started_ms(object()) > 0


def test_the_run_start_is_stable_when_asked_twice(run_dir):
    """It reads timestamps that never move, so it answers the same every time.
    That is what makes the once-only `if "id" not in meta` guard belt-and-braces
    rather than load-bearing — worth pinning, since the old `now` version had
    the opposite property."""
    d, _ = run_dir
    assert research._run_started_ms(d) == research._run_started_ms(d)


def test_it_accepts_a_string_path_too(run_dir):
    """Call sites pass `queue_dir` in whatever form they hold it."""
    d, started_ms = run_dir
    assert abs(research._run_started_ms(str(d)) - started_ms) < 2000


# -------------------------------------------------- the phase that it fixes


def test_a_first_write_at_phase_one_records_the_real_duration(run_dir, monkeypatch):
    """End to end on the exact shape that failed: no meta.json yet, and the
    first save_meta call is Phase 1's completion."""
    d, started_ms = run_dir
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_firebase_db", None)
    research.save_meta(d, "Some Topic", 1, summary="x")

    meta = json.loads((d / "meta.json").read_text())
    p1 = next(p for p in meta["phases"] if p["phase"] == 1)
    assert p1["durationSec"] >= 1000, (
        f"Phase 1 recorded {p1['durationSec']}s for a 20-minute brief — the "
        f"timeline is back to calling the longest wait instantaneous"
    )
    assert p1["completedAt"] > p1["startedAt"]


def test_phase_zero_starts_when_the_run_did(run_dir, monkeypatch):
    d, started_ms = run_dir
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_firebase_db", None)
    research.save_meta(d, "Some Topic", 1, summary="x")

    meta = json.loads((d / "meta.json").read_text())
    p0 = next(p for p in meta["phases"] if p["phase"] == 0)
    assert abs(p0["startedAt"] - started_ms) < 2000
    assert abs(meta["createdAt"] - started_ms) < 2000


def test_later_phases_still_chain_off_the_previous_completion(run_dir, monkeypatch):
    """The arithmetic that was already right must stay right: Phase 2 takes its
    start from Phase 1's end, not from the run start."""
    d, _ = run_dir
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_firebase_db", None)
    research.save_meta(d, "Some Topic", 1, summary="x")
    p1_end = next(p for p in json.loads((d / "meta.json").read_text())["phases"]
                  if p["phase"] == 1)["completedAt"]
    research.save_meta(d, "Some Topic", 2)

    p2 = next(p for p in json.loads((d / "meta.json").read_text())["phases"]
              if p["phase"] == 2)
    assert p2["startedAt"] == p1_end


def test_a_second_write_does_not_restamp_the_run_start(run_dir, monkeypatch):
    """`createdAt` is set once, under `if "id" not in meta`. A later write that
    moved it would drag every backfilled phase forward again."""
    d, started_ms = run_dir
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "_firebase_db", None)
    research.save_meta(d, "Some Topic", 1, summary="x")
    first = json.loads((d / "meta.json").read_text())["createdAt"]
    research.save_meta(d, "Some Topic", 2)
    assert json.loads((d / "meta.json").read_text())["createdAt"] == first


def test_the_stamp_is_read_from_the_helper_not_from_the_clock():
    """Asserted on the source: a revert to `time.time()` reads identically in
    every unit test that runs fast enough."""
    src = inspect.getsource(research.save_meta)
    at = src.index('meta["id"] = queue_dir.name')
    window = src[at:at + 400]
    assert 'meta["createdAt"] = _run_started_ms(queue_dir)' in window
    assert 'meta["createdAt"] = int(time.time() * 1000)' not in window
