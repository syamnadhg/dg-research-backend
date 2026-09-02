"""#704 — the command staleness gate must apply to the FIRST snapshot only.

Firestore replays every pre-existing doc as ADDED in the first callback after a
listener attaches, so a 30s staleness check skips a previous session's
leftovers. But both listeners attach while a person is using the product, so
Retry / Resume / Skip and every Settings button arrive LIVE — and `timestamp` is
written by the BROWSER. Applying the check to a live command therefore drops a
legitimate click whenever the machine's clock runs ahead of the browser's.

⛔⛔ THIS FILE USED TO BE SOURCE INSPECTION ONLY, AND THAT IS WHY THE BUG SURVIVED
FOR MONTHS. It read `_start_command_listener`'s source and asserted the gate sat
inside `if is_first_snapshot:`. It passed. Meanwhile the SECOND copy of the same
gate — in `_start_device_command_listener`, the one every Settings button talks
to — had never been fixed at all, and nothing here looked at it. A guard that
inspects one of two copies is not a guard; it is a receipt for the copy somebody
remembered.

So 2026-09-02 extracted the decision into `_is_stale_replay` — ONE function,
called by both listeners — and this file now does two things the old one could
not:

  * exercises the real decision behaviourally, including the live-command
    property that is the entire point of #704;
  * pins BOTH CONSUMERS, and pins that neither of them still does its own age
    arithmetic — because the failure mode being closed is precisely a second
    copy drifting away from the first.
"""
import research
from conftest import code_only

WINDOW = research.STALE_COMMAND_AGE_MS
NOW = 1_800_000_000_000  # a fixed clock, so nothing here depends on wall time


def _doc(age_ms):
    return {"action": "update", "timestamp": NOW - age_ms}


# ── the decision itself ──────────────────────────────────────────────────────

def test_a_live_command_is_never_stale_however_old_its_timestamp_looks():
    """⛔⛔ THE WHOLE POINT OF #704, AND THE DEFECT THAT LIVED IN THE DEVICE
    LISTENER. A live command is something that just happened; the only thing an
    old `timestamp` can mean there is that the browser's clock disagrees with
    this machine's. Executing it is always right."""
    assert research._is_stale_replay(_doc(WINDOW * 1000), False, now_ms=NOW) is False
    assert research._is_stale_replay(_doc(WINDOW + 1), False, now_ms=NOW) is False


def test_a_first_snapshot_leftover_is_stale():
    assert research._is_stale_replay(_doc(WINDOW + 1), True, now_ms=NOW) is True


def test_a_fresh_first_snapshot_command_still_runs():
    assert research._is_stale_replay(_doc(WINDOW - 1), True, now_ms=NOW) is False


def test_the_boundary_is_not_inclusive():
    """Exactly at the window is NOT stale — `>`, not `>=`. Pinned so a mutant
    that flips the comparison cannot pass on the two coarse cases above."""
    assert research._is_stale_replay(_doc(WINDOW), True, now_ms=NOW) is False


def test_a_command_with_no_usable_timestamp_executes():
    """Fail OPEN. A doc we cannot date is far more likely to be a live command
    than a leftover, and refusing it silently is the failure this gate caused."""
    for data in ({}, {"timestamp": 0}, {"timestamp": -1}, {"timestamp": None},
                 {"timestamp": "1800000000000"}):
        assert research._is_stale_replay(data, True, now_ms=NOW) is False, data


def test_a_boolean_is_not_a_timestamp():
    """⛔ `isinstance(True, int)` is True in Python, so the original numeric check
    accepted `{"timestamp": True}` and then subtracted it from the clock —
    making a live command look 1.7e12 ms old and dropping it."""
    assert research._is_stale_replay({"timestamp": True}, True, now_ms=NOW) is False
    assert research._is_stale_replay({"timestamp": False}, True, now_ms=NOW) is False


def test_the_window_is_the_documented_thirty_seconds():
    assert WINDOW == 30_000


# ── both consumers, because one of them was the bug ──────────────────────────

CONSUMERS = ("_start_command_listener", "_start_device_command_listener")


def _src(name):
    """COMMENTS STRIPPED — the same trap that bit this wave's sibling file: the
    fix comments in both listeners quote the constant and the phrasing these
    assertions hunt for, so a presence check on raw source cannot tell code from
    prose about code. `conftest.code_only` exists for exactly this."""
    return code_only(getattr(research, name))


def test_both_listeners_route_through_the_one_gate():
    for name in CONSUMERS:
        src = _src(name)
        assert "_is_stale_replay(data, is_first_snapshot)" in src, (
            f"{name} no longer calls the shared gate — the two copies that "
            "caused #704 have started to diverge again")


def test_neither_listener_dates_a_command_itself():
    """⛔⛔ THE REGRESSION THIS FILE EXISTS TO CATCH. Calling the shared gate is
    not enough: a listener that ALSO keeps its own age arithmetic can drop a live
    command again while the call above still satisfies the previous test. So the
    arithmetic must be gone from both.

    ⛔ Scoped to the SIGNATURE of dating a command, not to arithmetic in general:
    the first draft asserted `time.time() * 1000` was absent and failed on a
    ping-pong `updatedAt` write that has nothing to do with staleness. A guard
    that fails for the wrong reason gets loosened by the next reader.
    """
    for name in CONSUMERS:
        src = _src(name)
        assert "STALE_COMMAND_AGE_MS" not in src, (
            f"{name} has its own staleness constant again", name)
        assert 'data.get("timestamp")' not in src, (
            f"{name} reads the command's timestamp itself again — the shared "
            "gate owns that read, and a second reader is the second copy", name)


def test_both_listeners_consume_their_first_snapshot_flag():
    """The flag has to START True and then be FLIPPED — both halves.

    ⛔⛔ THE FIRST DRAFT PINNED ONLY THE FLIP, AND MUTATION WALKED THROUGH IT.
    Initialising the flag to False leaves the flip in place and satisfies a
    flip-only assertion, while the gate then never applies at all — so a previous
    session's unprocessed stop replays the moment a fresh serve attaches, which
    is the failure the gate was built for. Both ends or neither."""
    for name, var in ((CONSUMERS[0], "_cmd_first_snapshot"),
                      (CONSUMERS[1], "_dev_cmd_first_snapshot")):
        src = _src(name)
        assert f'{var} = {{"v": True}}' in src, (
            f"{var} no longer starts True — the stale gate never fires and a "
            "prior session's leftovers replay on attach", name)
        assert f'{var}["v"] = False' in src, (
            f"{var} is never flipped — the gate covers every callback forever "
            "and live commands get dated again", name)


def test_the_device_listener_says_when_it_drops_something():
    """⛔⛔ IT USED TO DROP SILENTLY, AND THAT IS WHY NOBODY FOUND IT. The
    `received action=` log line sits AFTER the skip, so a dropped Settings button
    left no line anywhere — the reported symptom was a button that did nothing
    and logs that showed the command had never arrived."""
    src = _src(CONSUMERS[1])
    gate = src[src.index("_is_stale_replay(data, is_first_snapshot)"):]
    gate = gate[:gate.index("continue")]
    assert "log(" in gate, "the device listener drops a stale command silently again"
    assert "stale" in gate.lower(), gate
