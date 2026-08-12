"""The arbiter lost its throttle exactly when the safety limit engaged.

From the 2026-08-11 21:00 run, ChatGPT's leg:

    21:41  CUA arbiter: WORKING — verdict #1 ... resetting growth clock
    21:57  CUA arbiter: WORKING — verdict #2 ... resetting growth clock
    22:12  CUA arbiter: WORKING — verdict #3 ... NOT resetting the growth clock:
           the arbiter has already granted 2 extensions
    22:13  verdict #4
    22:14  verdict #5
    ...    28 probes in 31 minutes

WHY THE SPACING COLLAPSES AT VERDICT #3, EVERY TIME

`STUCK_WARN_THROTTLE_SEC` is a real 10-minute throttle and `since_warn` is a
real gate on the probe. But `stuck_warned_at` — the only thing `since_warn` is
measured from — was stamped ONLY on the CONFIRMED-STUCK path. The WORKING branch
was expected to space itself out by rewinding the growth clock instead, and the
note in the probe's own except-block said so out loud.

That rewind is capped at `_ARBITER_MAX_WORKING_RESETS`. The cap is right — an
uncapped reset let a model that kept answering "working" hold a dead leg open
forever. But it was the ONLY thing spacing the probes, so spending it removed
the spacing: `last_growth_time` stops moving, `no_growth_secs` stays above
`STUCK_NO_GROWTH_SEC` for the rest of the run, `stuck_warned_at` is still 0.0 so
`since_warn` is the entire run, and every gate in `_active_no_growth` is true on
every single tick.

Each of those probes is a full CUA vision call. None of them could reset the
clock (the cap is spent) or raise a card (the verdict is WORKING). Pure cost,
zero information, for the rest of a 90-minute leg.

THE FIX

`stuck_warned_at` is stamped at probe ENTRY, before the verdict — so it holds
for every outcome, including the one that has no resets left to spend and the
one where the CUA probe itself raises.

WHAT MUST NOT CHANGE, AND IS PINNED BELOW

  * A CONFIRMED-STUCK verdict still cards and alerts on the spot. The throttle
    spaces PROBES, and must never delay the card a probe produces.
  * The two-reset cap stays at two.
  * The `_never_grew` branch stays: a leg that has never scraped one character
    still refuses the reset regardless of the verdict.
  * Real growth, a poke, a wait-longer, and a card retraction all still clear
    `stuck_warned_at` — those are user- or agent-driven restarts of the whole
    escalation, and they were never the problem.
"""
import functools
import inspect
import re
import textwrap

import pytest

import research
from conftest import code_only


@functools.lru_cache(maxsize=1)
def poller_src() -> str:
    """poll_all_agents_round_robin's source with comments blanked.

    Mandatory here beyond the usual reason: the fix's own comment quotes the
    stale claim it replaces ("throttling comes from the WORKING branch's
    growth-clock reset"), so a presence assertion run against raw source would
    read the prose and pass against the bug.
    """
    return code_only(research.poll_all_agents_round_robin)


@functools.lru_cache(maxsize=1)
def arbiter_block() -> str:
    """The arbiter probe, from its gate down to the CUA call."""
    src = poller_src()
    at = src.index("_active_no_growth = (")
    # Snap to the start of the line, not the identifier — `textwrap.dedent`
    # takes the common prefix over ALL lines, and a first line that begins at
    # column 0 makes that prefix empty, leaving every following line indented.
    return src[src.rindex("\n", 0, at) + 1:src.index("_stuck_mission = (", at)]


@functools.lru_cache(maxsize=None)
def const_default(name: str) -> int:
    """The shipped default of one of the escalation constants.

    They are resolved from the environment INSIDE the poller, deliberately, so a
    run can be retuned without a restart — which also means they are locals and
    the test cannot import them. Read from the source instead of re-typed here,
    so a changed default changes the simulation rather than silently invalidating
    it, and an assertion for a shape that no longer exists fails loudly.
    """
    m = re.search(rf'^\s*{name} = int\(os\.environ\.get\("DG_[A-Z_]+", "(\d+)"\)\)',
                  poller_src(), re.M)
    assert m, f"{name} is no longer an env-overridable int literal in the poller"
    return int(m.group(1))


@functools.lru_cache(maxsize=1)
def gate_and_entry() -> str:
    """The REAL gate expression and the REAL statements the loop runs on entry,
    lifted verbatim and made executable.

    Executing the shipped source is the point. Every cheaper form of this test
    — asserting a line is present, asserting a constant's value, re-typing the
    condition into the test — passes just as happily against a stamp that was
    written in the wrong place, or against a gate whose fourth clause was
    quietly dropped. Only running it can tell.
    """
    return textwrap.dedent(arbiter_block())


def run_ticks(minutes: int, *, tick_sec: int = 60, elapsed_at_start: int = 3600,
              no_growth_at_start: int = 2700, growing: bool = False,
              status_is_active: bool = False) -> list:
    """Replay the 08-11 shape: extensions spent, page frozen, clock never reset.

    Defaults are that run's actual numbers — an hour in, flat for 45 minutes,
    both arbiter extensions already granted — and the 60s tick matches its
    observed probe spacing (28 probes across 31 minutes).

    Returns the elapsed-second of every probe the real code would fire.
    """
    code = compile(gate_and_entry(), "<arbiter-gate>", "exec")
    clock = {"now": 100_000.0}
    p = {"stuck_warned_at": 0.0}
    p["last_growth_time"] = clock["now"] - no_growth_at_start
    start = clock["now"] - elapsed_at_start
    probes = []

    class _Clock:
        @staticmethod
        def time():
            return clock["now"]

    for _ in range(int(minutes * 60 / tick_sec)):
        if growing:
            # What the growth branch above the gate does on a producing agent.
            p["last_growth_time"] = clock["now"]
        ns = {
            "p": p,
            "time": _Clock,
            "log": lambda *a, **k: None,
            "name": "ChatGPT",
            "no_growth_secs": clock["now"] - p["last_growth_time"],
            "elapsed": clock["now"] - start,
            "since_warn": clock["now"] - p["stuck_warned_at"],
            # The 08-11 freeze reported no status at all to the scraper; a
            # planning/thinking status gates the probe off entirely.
            "status_is_active": status_is_active,
            "STUCK_NO_GROWTH_SEC": const_default("STUCK_NO_GROWTH_SEC"),
            "STUCK_MIN_ELAPSED_SEC": const_default("STUCK_MIN_ELAPSED_SEC"),
            "STUCK_WARN_THROTTLE_SEC": const_default("STUCK_WARN_THROTTLE_SEC"),
        }
        exec(code, ns)
        if ns["_active_no_growth"]:
            probes.append(int(clock["now"] - start))
        # The verdict is WORKING and the extensions are spent, so nothing
        # downstream moves last_growth_time. That is the whole scenario.
        clock["now"] += tick_sec
    return probes


# ------------------------------------------------------- the storm itself


def test_a_frozen_leg_with_its_extensions_spent_does_not_probe_every_tick():
    """⭐ THE BUG. 31 minutes of the 08-11 shape, replayed against the shipped
    gate and entry statements."""
    probes = run_ticks(31)
    assert len(probes) <= 4, (
        f"{len(probes)} arbiter probes in 31 minutes — each one is a full CUA "
        f"vision call that cannot reset the clock or raise a card. The 08-11 "
        f"run fired 28."
    )


def test_consecutive_probes_are_at_least_the_throttle_apart():
    """The count above could be met by a gate that happens to fire in a burst
    and then goes quiet. Spacing is the actual property."""
    probes = run_ticks(90)
    gaps = [b - a for a, b in zip(probes, probes[1:])]
    assert gaps, "no second probe in 90 minutes — the gate is off, not throttled"
    assert min(gaps) >= const_default("STUCK_WARN_THROTTLE_SEC"), (
        f"probes {min(gaps)}s apart, throttle is "
        f"{const_default("STUCK_WARN_THROTTLE_SEC")}s: {probes}"
    )


def test_the_throttle_holds_for_the_whole_ninety_minute_leg():
    """The cap is spent at ~30 min and the hard cap is at 90, so the ungated
    stretch is the majority of the leg — where nearly all the waste was."""
    probes = run_ticks(90)
    assert len(probes) <= 10, f"{len(probes)} probes across a full leg: {probes}"


def test_the_first_probe_still_happens_promptly():
    """⛔ Over-correction guard. Throttling a detector into silence is worse
    than the noise: the first probe is the one that can card a genuinely stuck
    agent, and it must not be delayed by the fix."""
    probes = run_ticks(31)
    assert probes and probes[0] <= 3660, (
        "the first probe on an already-frozen leg was delayed — a stuck agent "
        "now waits longer for its card than it did before the fix"
    )


def test_a_leg_that_is_still_growing_is_never_probed():
    """⛔ Over-correction guard. The gate's own clauses must survive: an agent
    whose scrape keeps moving is not a candidate at all, however long it runs."""
    assert run_ticks(90, growing=True) == []


def test_a_planning_leg_is_never_probed():
    """⛔ Over-correction guard, #929: a healthy Gemini research plan shows zero
    growth for 10+ minutes and got carded for it once. The status clause is what
    stopped that, and it is inside the same expression the fix edits."""
    assert run_ticks(90, status_is_active=True) == []


def test_a_young_leg_is_never_probed():
    """⛔ Over-correction guard: the 10-minute warm-up."""
    assert run_ticks(8, elapsed_at_start=60, no_growth_at_start=60) == []


# ------------------------------------------ where the stamp had to go, and why


def test_the_stamp_is_inside_the_probe_branch():
    block = arbiter_block()
    at = block.index("if _active_no_growth:")
    assert 'p["stuck_warned_at"] = time.time()' in block[at:], (
        "the throttle is stamped outside the branch that spends the probe — "
        "every tick would then re-stamp it and no probe would ever fire"
    )


def test_the_stamp_precedes_the_cua_call():
    """A probe that RAISES must still be throttled. The except-handler treats a
    raised probe as WORKING, so if the stamp sat after the call, a CUA client
    erroring every tick would reproduce the storm exactly — and that is the
    cheaper failure to hit, because a broken client fails fast."""
    src = poller_src()
    gate = src.index("_active_no_growth = (")
    stamp = src.index('p["stuck_warned_at"] = time.time()', gate)
    assert stamp < src.index("_confirmed_stuck = False", gate), (
        "the throttle is stamped after the verdict is initialised — a probe "
        "that raises would leave it unstamped"
    )
    assert stamp < src.index("_shadow_observed_cua(", gate), (
        "the throttle is stamped after the CUA call it is meant to space out"
    )


def test_the_probe_still_does_not_stamp_the_completion_clock():
    """2026-07-11: the arbiter used to stamp `last_cua_check`, deferring the
    real completion check by a whole interval on a WORKING verdict. The fix
    above touches the neighbouring line's comment; it must not revive that."""
    assert "last_cua_check" not in arbiter_block()


# -------------------------------------- everything the fix must not have moved


def test_a_confirmed_stuck_verdict_still_cards_without_waiting():
    """⛔ The throttle spaces PROBES. A probe that comes back stuck must still
    card on the spot — no `since_warn` check between the verdict and the card."""
    src = poller_src()
    at = src.index('log(f"[{name}] CUA arbiter: CONFIRMED STUCK"')
    # Bounded at the WORKING branch's first statement, not at the next `else:`
    # — the reload rescue inside this branch has an `else:` of its own, and
    # ending there would cut the window off before the card it is checking for.
    window = src[at:src.index("_never_grew = (", at)]
    assert "fail_agent(" in window, "the confirmed-stuck path no longer cards"
    assert "since_warn" not in window and "STUCK_WARN_THROTTLE_SEC" not in window, (
        "a throttle was introduced between the stuck verdict and its card"
    )
    assert "auto_skip_deadline=" in window, "the card lost its auto-skip arming"


def test_the_confirmed_stuck_path_still_stamps_too():
    """Redundant against the entry stamp, and kept deliberately: it means the
    entry stamp moving can never leave the card path unthrottled."""
    src = poller_src()
    at = src.index("if _confirmed_stuck:")
    window = src[at:src.index('log(f"[{name}] CUA arbiter: CONFIRMED STUCK"', at)]
    assert 'p["stuck_warned_at"] = time.time()' in window
    assert 'p["stuck_alerted_at"] = time.time()' in window


def test_the_reset_cap_is_still_two_and_still_gates_the_reset():
    assert const_default("_ARBITER_MAX_WORKING_RESETS") == 2
    src = poller_src()
    at = src.index("_reset_ok = (")
    assert "_ARBITER_MAX_WORKING_RESETS" in src[at:at + 200], (
        "the reset is no longer capped — a model that keeps answering 'working' "
        "can hold a dead leg open again"
    )
    assert "not _never_grew" in src[at:at + 200]


def test_a_leg_that_never_grew_still_refuses_the_reset():
    """⛔ The 2026-08-05 finding: 'stopped growing' and 'never grew once' are
    different failures, and a never-grew leg must not have its clock rewound by
    a verdict about output that may predate our send."""
    src = poller_src()
    at = src.index("_never_grew = (")
    window = src[at:at + 260]
    assert 'p.get("last_growth_len", 0) == 0' in window
    assert 'p.get("last_growth_sources", 0) == 0' in window


def test_the_growth_clock_is_still_reset_when_the_reset_is_allowed():
    """⛔ Over-correction guard: the cross-origin-blind class this branch exists
    for is real, and suppressing the card without moving the clock would put it
    straight back into a per-window re-probe."""
    src = poller_src()
    at = src.index("if _reset_ok:")
    assert 'p["last_growth_time"] = time.time()' in src[at:at + 120]


@pytest.mark.parametrize("restart", [
    "if _controls.consume_poke_agent(agent_key_stuck):",
    "if _controls.consume_wait_longer_agent(agent_key_stuck):",
])
def test_user_actions_still_clear_the_throttle(restart):
    """⛔ A poke or a wait-longer restarts the whole escalation on purpose. They
    reset the growth clock too, so the next probe is a full window away — the
    cleared throttle can't storm."""
    src = poller_src()
    at = src.index(restart)
    window = src[at:at + 1400]
    assert 'p["stuck_warned_at"] = 0.0' in window
    assert 'p["last_growth_time"] = time.time()' in window


def test_renewed_growth_still_clears_the_throttle():
    """⛔ Real growth after a card means the agent recovered; the escalation
    starts over from zero, throttle included."""
    src = poller_src()
    at = src.index('log(f"[{name}] Recovered after a stuck alert (growth resumed) — "')
    window = src[at - 400:at]
    assert 'p["stuck_warned_at"] = 0.0' in window
    assert 'p["stuck_alerted_at"] = 0.0' in window


def test_a_working_reverdict_still_retracts_a_live_card():
    """⛔ #929. An agent the arbiter just re-judged healthy must not keep
    counting down to an auto-skip measured from a stale alert."""
    src = poller_src()
    at = src.index('log(f"[{name}] WORKING re-verdict after a stuck alert — "')
    window = src[at - 400:at]
    assert 'p["stuck_alerted_at"] = 0.0' in window
    assert "_disarm_registry(agent_key_stuck)" in window


def test_the_stale_note_about_where_throttling_comes_from_is_gone():
    """The old comment told the next reader that the WORKING branch's reset was
    the throttle. It was the reason nobody looked here for eleven months, and it
    reads exactly as true as it ever did — comments do not fail."""
    raw = inspect.getsource(research.poll_all_agents_round_robin)
    assert "throttling comes from the WORKING\n" not in raw
    assert "branch's growth-clock reset below, not from this key" not in raw
