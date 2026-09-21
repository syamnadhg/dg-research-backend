"""The advisory lock on Hermes' shared cron registry — and why it must not block.

⛔⛔ THE BUG IT CLOSES: `_remove_stream_cron` and `_sweep_orphan_stream_crons`
rewrite the WHOLE of `$HERMES_HOME/cron/jobs.json`. A gateway save landing between
our read and our replace was discarded, deleting whatever it had just written —
possibly ANOTHER SKILL'S cron job. The confirm-read afterwards notices only
whether OUR removal survived; it is blind to somebody else's addition vanishing.
This is the one place Super Research can damage a neighbouring skill's state, and
the product already knew the rule — sr.py and sr_attention_poll.py both take this
same lock on this same file.

⛔⛔ AND WHY IT IS NON-BLOCKING, UNLIKE sr.py's. `_sweep_orphan_stream_crons` runs
inside `connect`, and `selfupdate` spawns a detached `connect --yes --no-login`
AFTER the bridge has shut down. A blocking `LOCK_EX` there means a bridge that
never comes back and a chat dead until the next login — sr.py's equivalent stall
costs one slow command; this one costs the agent. We try briefly, then proceed
unlocked, which is exactly the behaviour that shipped for two months.
"""

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "connect_0921", Path(__file__).resolve().parents[1] / "facade" / "connect.py")
connect = importlib.util.module_from_spec(_SPEC)
sys.modules["connect_0921"] = connect
_SPEC.loader.exec_module(connect)

posix_only = pytest.mark.skipif(connect.fcntl is None,
                                reason="fcntl is POSIX-only; on Windows the lock "
                                       "is a documented no-op")


@pytest.fixture()
def jobs(tmp_path):
    d = tmp_path / ".hermes" / "cron"
    d.mkdir(parents=True)
    f = d / "jobs.json"
    f.write_text(json.dumps({"jobs": []}), "utf-8")
    return f


@posix_only
def test_a_held_lock_does_not_hang_the_agent(jobs):
    """⭐⭐ THE ONE THAT MATTERS. A blocking acquire here would mean no bridge ever
    comes back after a self-update. Bounded wait, then proceed — never stall."""
    import fcntl
    holder = open(jobs.parent / ".jobs.lock", "a+")
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        t0 = time.monotonic()
        with connect._JobsLock(jobs) as lk:
            held = lk.held
        waited = time.monotonic() - t0
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()
    assert waited < 2.0, f"blocked for {waited:.2f}s — this would kill the agent"
    assert held is False, "it must report honestly that it proceeded unlocked"


@posix_only
def test_it_really_takes_the_lock_when_free(jobs):
    """⛔ NEGATIVE CONTROL FOR THE TEST ABOVE. Without this, a _JobsLock that never
    acquired anything would pass the no-hang test perfectly."""
    with connect._JobsLock(jobs) as lk:
        assert lk.held is True


@posix_only
def test_nesting_cannot_deadlock_against_itself(jobs):
    """⛔⛔ flock IS PER OPEN-FILE-DESCRIPTION, so a second open+flock from the SAME
    process blocks forever — and `_remove_stream_cron` calls `_stream_jobs_present`
    twice inside the lock. With a blocking acquire this would be a 100%
    reproducible `agent disconnect` deadlock, not a race."""
    with connect._JobsLock(jobs):
        t0 = time.monotonic()
        with connect._JobsLock(jobs):
            pass
        assert time.monotonic() - t0 < 2.0, "self-deadlock"


def test_it_never_materialises_a_cron_directory(tmp_path):
    """⛔ sr.py MAY mkdir this tree because it runs inside a Hermes that owns it.
    `connect` must never create a `cron/` dir in a runtime home that never had
    one — that would be building over Hermes rather than plugging into it."""
    missing = tmp_path / "nohermes" / "cron" / "jobs.json"
    with connect._JobsLock(missing):
        pass
    assert not missing.parent.exists()


def test_windows_takes_the_identical_unlocked_path(jobs, monkeypatch):
    """⛔ WINDOWS IS PRODUCTION HERE. With fcntl absent the lock is inert and the
    write takes exactly the path it took before this class existed — so the change
    cannot be a regression on that platform."""
    monkeypatch.setattr(connect, "fcntl", None)
    with connect._JobsLock(jobs) as lk:
        assert lk.held is False


def test_both_writers_take_the_lock_across_read_and_write():
    """⛔ THE LOCK MUST SPAN THE READ *AND* THE WRITE, or it buys nothing — the race
    is a gateway save landing between them. Pinned against the source so a
    refactor that narrows it to the write alone fails here."""
    import inspect
    for fn in (connect._remove_stream_cron, connect._sweep_orphan_stream_crons):
        src = inspect.getsource(fn)
        assert "with _JobsLock(jobs_file):" in src, fn.__name__
        assert src.index("with _JobsLock(") < src.index("read_text"), (
            f"{fn.__name__}: the lock must be taken BEFORE the read")
        assert src.index("with _JobsLock(") < src.index("os.replace"), fn.__name__


def test_the_temp_file_is_per_process():
    """⛔ A SHARED TEMP NAME IS A SHARED BUFFER. Two processes writing
    `jobs.json.tmp` interleave into one file, and whichever wins `os.replace`
    publishes a hybrid — for this file that is every cron job on the host replaced
    by garbage in one step."""
    import inspect
    for fn in (connect._remove_stream_cron, connect._sweep_orphan_stream_crons):
        assert 'os.getpid()' in inspect.getsource(fn), fn.__name__
