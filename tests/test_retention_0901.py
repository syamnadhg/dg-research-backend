"""Stretch 5C item 4, machine half — thirty days means thirty days.

⛔⛔ WHAT WAS ACTUALLY WRONG, MEASURED 2026-09-01 ON THE OWNER'S OWN DISK.

The machine kept three kinds of log and bounded them three different ways:

  runs/      60 folders OR 30 days, whichever bit first
  sessions/  40 groups  OR 30 days, whichever bit first
  the raw tails            64 MB, and NOTHING ELSE

`backend.log` was 44 MB, `backend-2.log` 40 MB, both last written 27 days
earlier, 187 MB of logs in total — under the byte cap, over any age anyone would
have described, and no code path on the machine could ever have removed them.
A size cap answers "how big". It never answers "how old".

⛔ AND THE 30-DAY BOUND THAT DID EXIST HAD NO CLOCK. `_prune_local_logs` had
exactly two callers: arming a run, and supervisor startup. The age bound
therefore only fired as a side effect of the machine being USED — a device that
was up and idle kept 45-day-old folders, and one that never ran another pipeline
kept them until its next restart. The bound was written; the guarantee was not.

⛔ AND THE COUNT BOUND WAS BEING READ AS THE POLICY. 60-runs and 30-days were
joined by `or`, so on a busy machine the run half of a person's diagnostics died
in DAYS while the cloud half lived its full thirty. The count stays — an
unbounded directory on a laptop is a real hazard — and is now named for what it
is, a disk valve.

⛔ AND DELETING A RUN NEVER REACHED THE DISK. The per-run cloud delete has been
deployed for months and the orphan sweep reacts within ~5 minutes, but it only
ever removed the QUEUE directory. "Delete this research" left the verbose half
of the run sitting in `logs/runs/`.

The tests below are grouped by which of those four this one prevents.
"""
import json
import time
from pathlib import Path

import pytest

import research


# ── the names, because the names were half the defect ──────────────────

def test_the_count_bound_is_named_as_a_valve_and_the_age_bound_as_the_policy():
    # ⛔ `LOCAL_RUNS_KEEP` read like a promise the product does not make. The
    # promise is the age one. Renaming is the fix for a defect of MEANING, so
    # it gets an assertion like any other.
    assert research.LOCAL_RUNS_DISK_VALVE == 60
    assert research.LOCAL_SESSIONS_DISK_VALVE == 40
    assert research.LOCAL_LOG_MAX_AGE_DAYS == 30
    assert not hasattr(research, "LOCAL_RUNS_KEEP")
    assert not hasattr(research, "LOCAL_SESSIONS_KEEP")


def test_the_run_index_never_advertises_more_than_the_valve_keeps():
    # An index row for a folder the valve already removed is a button that
    # leads nowhere.
    assert research.RUN_INDEX_MAX == research.LOCAL_RUNS_DISK_VALVE


def test_the_tails_are_bounded_by_the_same_thirty_days_as_everything_else():
    # "Both halves" in the signed item means machine and cloud; on the machine
    # it means all three sources, not the two that already had a clock.
    # ⛔ BOTH AGAINST THE NUMBER, not one against the other. The tail bound is
    # DEFINED as the log bound, so comparing them can never fail — it pins the
    # aliasing and leaves the promise itself unpinned.
    assert research.LOCAL_TAIL_MAX_AGE_DAYS == 30
    assert research.LOCAL_TAIL_MAX_AGE_DAYS == research.LOCAL_LOG_MAX_AGE_DAYS


# ── the trigger: the bound only means something if something runs it ───

def test_the_sweep_starts_due_so_a_machine_coming_back_cleans_itself_up():
    # ⭐ A device that has been off for two months should sweep on the way back,
    # not on its next run.
    #
    # ⛔ THE CONSTANT, NOT THE VARIABLE — found by mutation. Every test here sets
    # `_prune_next_ms` before it looks, so a mutant that changed the module's
    # INITIAL value to a far-future stamp survived the whole harness: the
    # behaviour was real, untested, and invisible. Pinning the named start value
    # is the only thing that can see it.
    assert research._PRUNE_START_DUE_MS == 0
    research._prune_next_ms = research._PRUNE_START_DUE_MS
    assert research._prune_due(1_000_000) is True


def test_the_sweep_does_not_run_twelve_times_a_minute():
    # ⛔ THE CALLER IS THE 5-SECOND HEARTBEAT. A predicate that only READ the
    # deadline would sweep on every tick forever — a directory walk plus a
    # meta.json read per folder, twelve times a minute. Advancing the clock is
    # the whole job, which is why it lives in the predicate.
    research._prune_next_ms = 0
    now = 5_000_000
    assert research._prune_due(now) is True
    assert research._prune_due(now + 1) is False
    assert research._prune_due(now + 5_000) is False


def test_the_sweep_comes_due_again_after_the_interval():
    research._prune_next_ms = 0
    now = 9_000_000
    assert research._prune_due(now) is True
    later = now + research.LOCAL_PRUNE_INTERVAL_SEC * 1000
    assert research._prune_due(later - 1) is False
    assert research._prune_due(later) is True


def test_the_heartbeat_is_the_thing_that_calls_it():
    # ⛔ THE CONSUMER, NOT THE HELPER. `_prune_due` passing its own unit tests
    # proves nothing if nobody asks it. The heartbeat loop is a nested async
    # def inside the server entrypoint and cannot be imported, so this is a
    # source pin and is labelled as one — but an unwired throttle is exactly
    # the shape of defect this whole item is about.
    src = Path(research.__file__).read_text(encoding="utf-8")
    hb = src[src.index("async def _heartbeat_loop"):]
    hb = hb[:hb.index("\nasync def ", 10)]
    assert "_prune_due(" in hb, "the retention sweep has no clock again"
    assert "_prune_local_logs" in hb


# ── the raw tails ──────────────────────────────────────────────────────

def test_a_rolled_tail_older_than_the_bound_is_retired(tmp_path):
    old = tmp_path / "backend.log.1"
    old.write_text("ancient", encoding="utf-8")
    now = time.time()
    import os as _os
    _os.utime(old, (now - 40 * 86400, now - 40 * 86400))
    removed = research._retire_stale_rotations(root=tmp_path, max_age_days=30, now=now)
    assert str(old) in removed
    assert not old.exists()


def test_a_JUST_ROLLED_tail_is_not_deleted_on_the_same_boot(tmp_path):
    """⛔⛔⛔ THE BLOCKER CROSS-VERIFY FOUND, and mtime is the trap.

    `os.replace` PRESERVES mtime, so a generation that began 40 days ago arrives
    as a `.1` already past the bound and the prune deletes it on the same boot
    that rolled it. That file also holds YESTERDAY's lines — a long-lived
    generation is old at its head and current at its tail — so bounding it by
    its head throws away the diagnostics somebody is about to ask for.

    The rolled copy is bounded from the ROLL instead, which bounds its NEWEST
    content and over-retains the oldest lines in a file that is byte-capped
    anyway."""
    tail = tmp_path / "backend.log"
    tail.write_text("old head, and yesterday's tail", encoding="utf-8")
    now = time.time()
    import os as _os
    _os.utime(tail, (now - 40 * 86400, now - 40 * 86400))
    research._begin_raw_tail_generation(tail, now=now - 40 * 86400)

    assert research._rotate_if_stale(tail, max_age_days=30, now=now) > 0
    rolled = tmp_path / "backend.log.1"
    assert rolled.exists()
    # mtime still says 40 days; the roll marker says "just now".
    assert research._safe_mtime(rolled) < now - 39 * 86400
    assert research._retire_stale_rotations(root=tmp_path, max_age_days=30, now=now) == []
    assert rolled.exists(), "the tail was rolled and destroyed in the same breath"


def test_a_rolled_tail_is_retired_once_THIRTY_DAYS_AFTER_THE_ROLL(tmp_path):
    # The other polarity: bounding from the roll must still bound.
    tail = tmp_path / "backend.log"
    tail.write_text("x", encoding="utf-8")
    now = time.time()
    research._begin_raw_tail_generation(tail, now=now - 90 * 86400)
    assert research._rotate_if_stale(tail, max_age_days=30, now=now) > 0
    rolled = tmp_path / "backend.log.1"
    later = now + 31 * 86400
    assert str(rolled) in research._retire_stale_rotations(
        root=tmp_path, max_age_days=30, now=later)
    assert not rolled.exists()
    assert not research._raw_tail_marker(rolled).exists(), \
        "the marker outlived the file it described"


def test_a_rolled_tail_inside_the_bound_is_kept(tmp_path):
    fresh = tmp_path / "backend.log.1"
    fresh.write_text("recent", encoding="utf-8")
    now = time.time()
    import os as _os
    _os.utime(fresh, (now - 3 * 86400, now - 3 * 86400))
    assert research._retire_stale_rotations(root=tmp_path, max_age_days=30, now=now) == []
    assert fresh.exists()


def test_the_LIVE_tail_is_never_unlinked_by_the_timer(tmp_path):
    # ⛔⛔ THE HAZARD THIS SPLIT EXISTS FOR. The supervisor holds backend.log
    # open in append mode, so renaming or unlinking it from a background tick
    # leaves every later write going to an inode with no name — the same reason
    # `_clear_local_logs` truncates instead of unlinking. The timer touches
    # `.1` only.
    live = tmp_path / "backend.log"
    live.write_text("live", encoding="utf-8")
    now = time.time()
    import os as _os
    _os.utime(live, (now - 90 * 86400, now - 90 * 86400))
    assert research._retire_stale_rotations(root=tmp_path, max_age_days=30, now=now) == []
    assert live.exists()


def test_only_rolled_tails_are_retired_not_every_old_file(tmp_path):
    # The logs root also holds e2e captures and DOM dumps. A sweep that took
    # anything old would be a different, much larger promise.
    other = tmp_path / "e2e-0806.log"
    other.write_text("x", encoding="utf-8")
    dump = tmp_path / "claude_popover.html"
    dump.write_text("x", encoding="utf-8")
    now = time.time()
    import os as _os
    for p in (other, dump):
        _os.utime(p, (now - 99 * 86400, now - 99 * 86400))
    assert research._retire_stale_rotations(root=tmp_path, max_age_days=30, now=now) == []
    assert other.exists() and dump.exists()


def test_a_generation_older_than_the_bound_is_rolled_at_reopen(tmp_path):
    tail = tmp_path / "backend.log"
    tail.write_text("aged", encoding="utf-8")
    now = time.time()
    research._begin_raw_tail_generation(tail, now=now - 45 * 86400)
    rolled = research._rotate_if_stale(tail, max_age_days=30, now=now)
    assert rolled > 0
    assert (tmp_path / "backend.log.1").read_text(encoding="utf-8") == "aged"
    assert not tail.exists()


def test_a_fresh_generation_is_left_alone(tmp_path):
    tail = tmp_path / "backend.log"
    tail.write_text("new", encoding="utf-8")
    now = time.time()
    research._begin_raw_tail_generation(tail, now=now - 2 * 86400)
    assert research._rotate_if_stale(tail, max_age_days=30, now=now) == 0.0
    assert tail.exists()


def test_mtime_is_not_the_age_and_that_is_the_whole_reason_for_the_marker(tmp_path):
    # ⛔ THE TRAP THE MARKER EXISTS FOR. A tail that has been appended to one
    # second ago can still hold lines from four months back — mtime moves on
    # every write. If age were read from mtime this file would be "new" and
    # would never roll, which is precisely how 44 MB of May survived to
    # September.
    tail = tmp_path / "backend.log"
    tail.write_text("old lines, just appended to", encoding="utf-8")
    now = time.time()
    import os as _os
    _os.utime(tail, (now, now))          # touched a moment ago …
    research._begin_raw_tail_generation(tail, now=now - 60 * 86400)  # … but 60 days old
    assert research._rotate_if_stale(tail, max_age_days=30, now=now) > 0


def test_rolling_restarts_the_age_clock(tmp_path):
    # Otherwise the marker keeps describing a generation that no longer exists
    # and the next check rolls a file that is seconds old.
    tail = tmp_path / "backend.log"
    tail.write_text("a", encoding="utf-8")
    now = time.time()
    research._begin_raw_tail_generation(tail, now=now - 45 * 86400)
    assert research._rotate_if_stale(tail, max_age_days=30, now=now) > 0
    tail.write_text("b", encoding="utf-8")
    assert research._rotate_if_stale(tail, max_age_days=30, now=now) == 0.0
    assert tail.exists()


def test_a_size_roll_also_restarts_the_age_clock(tmp_path):
    # ⛔ THE CROSS-PATH ONE. Two rotations share one marker; if only the age
    # path reset it, a size roll would leave a brand-new file carrying an
    # ancient timestamp and the very next age check would roll it again.
    tail = tmp_path / "backend.log"
    tail.write_text("x" * 200, encoding="utf-8")
    now = time.time()
    research._begin_raw_tail_generation(tail, now=now - 90 * 86400)
    assert research._rotate_if_oversize(tail, max_bytes=100) > 0
    tail.write_text("fresh", encoding="utf-8")
    assert research._rotate_if_stale(tail, max_age_days=30, now=now) == 0.0


def test_on_a_platform_with_no_birthtime_the_seed_is_the_CLOCK_not_the_epoch(tmp_path, monkeypatch):
    """⛔⛔⛔ THE LINUX PATH, AND THE ONE THAT DESTROYS DATA IF IT IS WRONG.

    `st_birthtime` exists on macOS and NOT on Linux, so on a fleet box the
    fallback is the entire answer — and this suite runs on macOS, where the
    birthtime branch quietly covered for it. Mutation caught that: seeding to
    the epoch instead of the clock survived every test in this file, because on
    this machine the fallback never executed. Seeded from the epoch, the first
    run after an upgrade decides every tail on the machine is infinitely old and
    deletes all of them."""
    tail = tmp_path / "backend.log"
    tail.write_text("pre-existing", encoding="utf-8")
    now = time.time()

    real_stat = Path.stat

    class _NoBirth:
        """A stat result shaped like Linux's — no st_birthtime attribute."""

        def __init__(self, st):
            self.st_mtime = st.st_mtime
            self.st_size = st.st_size

    def _stat(self, *a, **kw):
        return _NoBirth(real_stat(self, *a, **kw))

    monkeypatch.setattr(Path, "stat", _stat)
    seeded = research._raw_tail_started_at(tail, now=now)
    # Seeded from the clock: the generation is treated as new, not ancient.
    assert seeded == now


def test_a_marker_from_the_FUTURE_does_not_switch_the_bound_off(tmp_path):
    """⛔ A clock that jumped, a restore from another machine, or a corrupt
    write leaves a marker ahead of now — and `now - started` is then permanently
    negative, so the age bound never fires again for that file and says nothing
    about it. Clamped to now: one bound-length of over-retention, and nothing
    disabled."""
    tail = tmp_path / "backend.log"
    tail.write_text("x", encoding="utf-8")
    now = time.time()
    research._raw_tail_marker(tail).write_text(f"{now + 900 * 86400:.0f}", encoding="utf-8")
    assert research._raw_tail_started_at(tail, now=now) == now
    # and once real time passes the bound, it still rolls
    assert research._rotate_if_stale(tail, max_age_days=30,
                                     now=now + 31 * 86400) > 0


def test_a_missing_marker_seeds_instead_of_deleting_on_a_guess(tmp_path):
    # ⭐ FIRST RUN AFTER UPGRADE. Nobody recorded when the existing tail began,
    # so the bound becomes exact within one window rather than firing
    # immediately. Throwing away a person's whole log on the strength of a
    # guess is the one outcome worse than keeping it too long.
    tail = tmp_path / "backend.log"
    tail.write_text("pre-existing", encoding="utf-8")
    now = time.time()
    assert research._rotate_if_stale(tail, max_age_days=30, now=now) == 0.0
    assert tail.exists()
    assert research._raw_tail_marker(tail).exists()


def test_the_prune_reports_the_tails_it_retired(tmp_path, monkeypatch):
    # ⛔ THE CONSUMER AGAIN. `_retire_stale_rotations` working in isolation is
    # not the same as `_prune_local_logs` calling it — and the prune's return
    # value is what the supervisor and the heartbeat both log.
    root = tmp_path / "logs"
    (root / "runs").mkdir(parents=True)
    (root / "sessions").mkdir(parents=True)
    rolled = root / "backend.log.1"
    rolled.write_text("ancient", encoding="utf-8")
    now = time.time()
    import os as _os
    _os.utime(rolled, (now - 50 * 86400, now - 50 * 86400))
    monkeypatch.setattr(research, "_logs_root", lambda: root)
    monkeypatch.setattr(research, "_runs_log_root", lambda: root / "runs")
    monkeypatch.setattr(research, "_sessions_log_root", lambda: root / "sessions")
    removed = research._prune_local_logs(now=now)
    assert str(rolled) in removed
    assert not rolled.exists()


# ── deleting a run reaches the disk ────────────────────────────────────

def _folder(root, name, rid, status="completed"):
    d = root / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({
        "researchId": rid, "status": status, "startedUtc": "2026-08-01T00:00:00Z",
        "attempt": 1, "schema": 1,
    }), encoding="utf-8")
    (d / "run.log").write_text("lines", encoding="utf-8")
    return d


def test_every_attempt_for_one_research_is_found(tmp_path):
    a = _folder(tmp_path, "chat_1_1_20260801T000000", "chat_1")
    b = _folder(tmp_path, "chat_1_2_20260801T010000", "chat_1")
    _folder(tmp_path, "chat_2_1_20260801T020000", "chat_2")
    found = research._run_log_folders_for_research("chat_1", root=tmp_path)
    assert sorted(found) == sorted([a, b])


def test_it_matches_the_meta_not_the_folder_name(tmp_path):
    # ⛔⛔ THE DELETION SAFETY PROPERTY. The folder name is a SANITISED id, so a
    # prefix match can both miss the real folder and hit somebody else's. This
    # folder is named for one research and belongs to another; only the meta
    # is the truth.
    d = _folder(tmp_path, "chat_1_1_20260801T000000", "chat_999")
    assert research._run_log_folders_for_research("chat_1", root=tmp_path) == []
    assert research._run_log_folders_for_research("chat_999", root=tmp_path) == [d]


def test_a_prefix_neighbour_is_not_swept(tmp_path):
    _folder(tmp_path, "chat_10_1_20260801T000000", "chat_10")
    assert research._run_log_folders_for_research("chat_1", root=tmp_path) == []


def test_a_running_folder_is_never_returned(tmp_path, monkeypatch):
    # Liveness is the prune's, not a new one — and a run that is still being
    # written into is not an orphan no matter what the cloud says.
    d = _folder(tmp_path, "chat_1_1_20260801T000000", "chat_1", status="running")
    monkeypatch.setattr(research, "_folder_is_live", lambda p: Path(p) == d)
    assert research._run_log_folders_for_research("chat_1", root=tmp_path) == []


def test_a_folder_an_active_sink_owns_is_never_returned(tmp_path, monkeypatch):
    # ⛔ The sink list covers only runs THIS worker armed; `_folder_is_live` is
    # the cross-process half. Both are consulted, which is the multi-worker
    # hole mutation found in the prune.
    d = _folder(tmp_path, "chat_1_1_20260801T000000", "chat_1")

    class _Sink:
        dir = d

    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [_Sink()])
    assert research._run_log_folders_for_research("chat_1", root=tmp_path) == []


def test_an_unreadable_meta_is_left_alone_rather_than_guessed_at(tmp_path):
    d = tmp_path / "chat_1_1_20260801T000000"
    d.mkdir()
    (d / "meta.json").write_text("{not json", encoding="utf-8")
    assert research._run_log_folders_for_research("chat_1", root=tmp_path) == []
    assert d.exists()


@pytest.mark.parametrize("rid", ["", None, "   "])
def test_an_empty_research_id_matches_nothing(rid, tmp_path):
    # ⛔ ACCEPT-POLARITY'S OPPOSITE, and the dangerous direction here: a blank
    # id that fell through to "match everything" would let one bad owner.json
    # delete every run folder on the machine.
    _folder(tmp_path, "chat_1_1_20260801T000000", "chat_1")
    assert research._run_log_folders_for_research(rid, root=tmp_path) == []


@pytest.mark.parametrize("rid", ["", None, "   "])
def test_an_empty_id_does_not_match_a_folder_that_ALSO_has_no_id(rid, tmp_path):
    """⛔⛔⛔ THE CASE THE GUARD ACTUALLY EXISTS FOR — found by mutation.

    Removing `if not rid: return out` survived every test above, because a
    folder whose meta names a real research does not match an empty id anyway.
    But a folder whose meta.json has NO researchId reads back as "" as well, and
    "" == "" is a match. Without the guard, one malformed owner.json upstream
    deletes exactly the folders nothing can identify — and those are the oldest
    and least replaceable diagnostics on the machine."""
    d = tmp_path / "orphan_1_1_20260801T000000"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    (d / "run.log").write_text("lines", encoding="utf-8")
    assert research._run_log_folders_for_research(rid, root=tmp_path) == []
    assert d.exists()


def test_the_orphan_sweep_is_what_calls_it(tmp_path):
    # ⛔ THE CONSUMER. `_orphan_sweep_loop` is a nested async def inside the
    # server entrypoint and cannot be imported, so this is a source pin and is
    # labelled as one. It checks the call sits INSIDE the branch that has
    # already proved the research doc is gone — a call above that check would
    # delete the logs of every run on the machine.
    src = Path(research.__file__).read_text(encoding="utf-8")
    body = src[src.index("async def _orphan_sweep_loop"):]
    body = body[:body.index("[orphan-sweep] purged")]
    assert "_run_log_folders_for_research(rid)" in body
    # The existence re-check comes first — nothing may be deleted before the
    # research doc has been proved gone twice.
    assert body.index("if ref.get().exists") < body.index("_run_log_folders_for_research")
    # ⛔ AND THE LOOKUP COMES BEFORE THE QUEUE rmtree, not after. The queue
    # directory holds the only rid→uid key on disk; if the process dies between
    # the two removals, log folders resolved afterwards would be left behind
    # permanently unidentifiable. Reading first makes that window harmless.
    assert body.index("_run_log_folders_for_research") < body.index("_shutil.rmtree(d)")
