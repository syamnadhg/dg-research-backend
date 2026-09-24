"""The orphan sweep stops paying for the same answer every five minutes.

⛔⛔ WHAT WAS WRONG, found in the 2026-09-20 pre-PR sweep. `_orphan_sweep_loop`
checks, for every directory under `queues/`, whether its research still exists
in Firestore — and that check is a billed document read. Its age gate only skips
directories YOUNGER than five minutes, and nothing prunes a finished one: the
7-day startup sweep explicitly spares completed and paused runs.

So every research this machine had ever finished stayed in the listing and cost
one read on every 300-second tick, forever, and the answer was `exists == True`
every single time. One old run is 288 reads a day. Ten is 2,880. The count only
ever grows, and nothing about the output changes.

⭐ A research that exists does not stop existing often, so the answer is worth
remembering. A directory confirmed present is re-checked at most hourly; one
never seen before is still read on the very next tick, so a genuine orphan —
the thing the sweep is actually for — is detected exactly as fast as it was.

⛔ THE COST WAS STATED AS "a research deleted in the app keeps its local queue
directory for up to an hour", and wave 10.10 found who paid it: the person who
deleted a research on the day they ran it, whose folders and logs then stayed on
the computer for up to about sixty-five minutes. So a folder whose run wrote its
`delivery.json` within the last day is asked about every tick again, and the
hour holds only after that. The tests at the bottom hold the hour where it must
still hold — the read bill for every older run is what this file exists for.
"""
import re

import research
from conftest import code_only
from test_incognito_teardown_109 import CHAT, HOUR, NOW, _sweep_tick


def _sweep_src() -> str:
    """The sweep loop's body, comments stripped so prose cannot satisfy a
    presence assertion — the trap `code_only` exists for."""
    src = code_only(open(research.__file__, encoding="utf-8").read())
    i = src.index("async def _orphan_sweep_loop():")
    j = src.index("swept_n += 1", i)
    return src[i:j]


def _consts_src() -> str:
    """⚠ The whole module, not a window. `code_only` blanks comments IN PLACE
    rather than removing them, so the explanatory block between the two
    constants still occupies its full width — a fixed-size slice from the first
    constant never reaches the second."""
    return code_only(open(research.__file__, encoding="utf-8").read())


def test_a_confirmed_research_is_not_re_read_every_tick():
    """⛔ THE FIX. Without the memo check the existence read runs on every
    directory on every tick; with it, a directory confirmed present inside the
    re-check window is skipped before the read."""
    body = _sweep_src()
    assert "_orphan_verified.get(" in body
    assert "ORPHAN_RECHECK_SEC" in body
    # The skip must come BEFORE the read, or it saves nothing.
    assert body.index("_orphan_verified.get(") < body.index("ref.get().exists")


def test_the_answer_is_actually_recorded():
    """A memo that is read and never written is a no-op that reads like a fix."""
    body = _sweep_src()
    assert re.search(r"_orphan_verified\[_seen_key\]\s*=", body), body[-1200:]


def test_the_recheck_window_is_much_longer_than_the_tick():
    """The saving is the ratio. A window equal to the tick would skip nothing."""
    src = _consts_src()
    tick = int(re.search(r"ORPHAN_SWEEP_INTERVAL_SEC = (\d+)", src).group(1))
    window = int(re.search(r"ORPHAN_RECHECK_SEC = (\d+)", src).group(1))
    assert window >= tick * 4, f"window {window}s vs tick {tick}s buys too little"


def test_the_memo_cannot_outgrow_the_directory_listing():
    """⛔⛔ THE UNBOUNDED-GROWTH GUARD. This dict lives for the life of the
    process. If an entry outlived its directory it would be the one thing in
    this loop that grows without bound — which is the exact defect class the
    change is fixing, moved from reads to memory."""
    src = code_only(open(research.__file__, encoding="utf-8").read())
    i = src.index("async def _orphan_sweep_loop():")
    j = src.index("_run_log_folders_for_research", i)
    after_rmtree = src[j:j + 1400]
    assert "_orphan_verified.pop(_seen_key" in after_rmtree, after_rmtree[:600]


def test_a_directory_never_seen_before_is_still_checked_immediately():
    """⭐ THE THING THE SWEEP IS FOR must not get slower. `.get(key, 0.0)`
    returns 0.0 for an unseen key, and `now - 0.0` is never under the window,
    so a new orphan is read on the very next tick exactly as before."""
    body = _sweep_src()
    assert "_orphan_verified.get(_seen_key, 0.0)" in body


def test_the_in_flight_statuses_still_skip_before_any_of_this():
    """The no-widening guard: an ongoing or queued run must still be skipped on
    its status, ahead of the memo and ahead of the read. Reordering those would
    make a live run eligible for deletion."""
    body = _sweep_src()
    assert body.index("ORPHAN_SWEEP_IN_FLIGHT_STATUSES") < body.index("_orphan_verified.get(")


# ── wave 10.10: the recency tier must not bring the read bill back ────────
#
# ⛔⛔ EXECUTED, through the real `_orphan_sweep_loop` rebuilt from
# `run_server` (the helper lives in test_incognito_teardown_109.py). Each of
# these fails if the tier widens to every folder, which is the 288-reads-a-day
# defect this file was written for.

def test_a_day_old_folder_still_skips_its_read_within_the_hour(tmp_path):
    """⛔⛔ THE READ BILL. A run that finished two days ago, confirmed present a
    minute ago, costs nothing this tick — even though its research is in fact
    gone, which is the hour of latency the old tier still pays on purpose."""
    still_there, reads = _sweep_tick(tmp_path, CHAT, verified_at=NOW - 60.0,
                                     record_exists=False,
                                     wrote_at=NOW - 2 * 86400)
    assert still_there and reads == 0, (
        f"a two-day-old folder cost {reads} read(s) inside its hour")


def test_a_file_stamped_days_ahead_is_not_recent_for_ever(tmp_path):
    """⛔ A CLOCK THAT MOVED BACKWARDS leaves files stamped in the future. If
    "recent" meant only "not older than a day", every such folder would be
    read on every tick until the clock caught up — days of it."""
    still_there, reads = _sweep_tick(tmp_path, CHAT, verified_at=NOW - 60.0,
                                     record_exists=False,
                                     wrote_at=NOW + 3 * 86400)
    assert still_there and reads == 0


def test_the_tier_is_one_day_wide_on_both_sides():
    """The window's edges, on the helper: inside a day either way is recent,
    a day or more is not, and an unknown time is the old tier."""
    day = research._ORPHAN_RECENT_WINDOW_SEC
    assert day == 86400
    due = research._orphan_recheck_due
    assert due(NOW - 60, NOW, CHAT, HOUR, NOW - day + 1) is True
    assert due(NOW - 60, NOW, CHAT, HOUR, NOW + day - 1) is True
    assert due(NOW - 60, NOW, CHAT, HOUR, NOW - day) is False
    assert due(NOW - 60, NOW, CHAT, HOUR, NOW + day) is False
    assert due(NOW - 60, NOW, CHAT, HOUR, None) is False
    assert due(NOW - 60, NOW, CHAT, HOUR) is False
