"""A [Retry][Skip] card must live long enough to be answered — at both ends.

The alert taxonomy was incoherent in OPPOSITE directions, and the two halves are
one bug:

  * PHASE 2 retracted its card in ZERO seconds. The mid-run error path raised the
    card and then `del pending[name]`; when that was the last polling agent the
    round-robin exited on the same tick, and the exit sweep auto-skipped it
    immediately — logging "its Retry/Skip alert went unanswered" about a card that
    had existed for 0 seconds. Observed: persisted 14:36:55, cleared 14:36:55.
    The corpus counter-example: the identical card stood for 63 s on an earlier
    run, the user clicked Retry, and the leg recovered to status=done with 61,023
    chars. The configured budget (DG_AUTO_SKIP_UNACTED_SEC, 1800 s) was never
    consulted by that sweep — no reference, no timestamp, no deadline.

  * PHASE 3 never retracted its link-failure card. `await_phase_decision`
    defaults to 24 hours and the emitter stamped no deadline at all, so an
    unattended failure hung the run until the outer watchdog killed it, with no
    countdown shown because there was nothing to count down to.

These tests pin the card's LIFETIME, not its existence. Asserting the card exists
is what let the 0-second retraction ship in the first place.
"""
from __future__ import annotations

import inspect
import re

import pytest

import research
from conftest import code_only


# ── The shared budget ────────────────────────────────────────────────────────

def test_both_ends_read_one_budget(monkeypatch):
    """Hoisted to module scope so P2 and P3 cannot drift apart again."""
    monkeypatch.delenv("DG_AUTO_SKIP_UNACTED_SEC", raising=False)
    assert research.auto_skip_unacted_sec() == 1800
    monkeypatch.setenv("DG_AUTO_SKIP_UNACTED_SEC", "600")
    assert research.auto_skip_unacted_sec() == 600, (
        "read LIVE from the env, not captured at import — a test must be able to "
        "shrink the window without reloading the module"
    )


def test_the_round_robin_uses_the_shared_budget_not_its_own_literal():
    src = code_only(research.poll_all_agents_round_robin)
    assert "AUTO_SKIP_UNACTED_SEC = auto_skip_unacted_sec()" in src
    assert 'os.environ.get("DG_AUTO_SKIP_UNACTED_SEC"' not in src, (
        "the round-robin must not re-read the env itself — one source of truth"
    )


# ── Phase 2: park instead of drop ────────────────────────────────────────────

def _error_branch() -> str:
    """The whole `CONCLUSION: ERROR` branch, anchor-delimited.

    Anchors, not byte offsets: the offsets this used to slice were measured
    against the comment volume of the day, and `code_only` blanks comments IN
    PLACE — so adding an explanation silently pushed code out of the window a
    test was asserting over."""
    src = code_only(research.poll_all_agents_round_robin)
    i = src.index("if is_error:")
    return src[i:src.index("if is_generating and not is_done:", i)]


def _error_park_arm() -> str:
    """Just the arm/park/drop decision at the end of that branch."""
    branch = _error_branch()
    return branch[branch.index("_ae_window ="):]


def test_the_mid_run_error_parks_the_agent_instead_of_dropping_it():
    """Dropping it emptied `pending`, which exited the loop, which ran the exit
    sweep — all in the tick that raised the card.

    2026-08-02: it must park in BOTH modes. A first attempt at the auto-skip-OFF
    fix dropped the agent when no window was armed, reasoning that a card with no
    timer needs no consumer and that both backend finalizers early-return with the
    setting off. Both were true; the conclusion was not. Dropping the last polling
    agent empties `pending` → the round-robin exits → Phase 2 completes → the WEB
    APP's phase_complete:2 handler rewrites every non-clean agent alert to
    `type: "warn", actions: undefined`, stripping [Retry][Skip]. Same 0-second
    retraction, third actor, other repo."""
    arm = _error_park_arm()
    assert 'p["awaiting_decision"] = {' in arm
    assert '"kind": "agent_error"' in arm
    assert "del pending[name]" not in arm, (
        "dropping the agent is what lets Phase 2 complete under a live card"
    )
    assert "if not _ae_window:" not in arm, (
        "there is no second path here — a 0 window is a park with no deadline"
    )


def test_the_error_card_is_armed_with_the_full_window():
    arm = _error_park_arm()
    assert "_ae_window = unacted_window_sec(_runtime.auto_skip_stuck)" in arm
    assert '"auto_skip_deadline": (time.time() + _ae_window) * 1000' in arm, (
        "the FE counts down to this epoch — without it there is no countdown"
    )
    assert '"timeout": _ae_window' in arm, (
        "the park window and the shown deadline must be the SAME value, or the "
        "countdown and the real fire disagree"
    )


def test_the_error_card_does_not_arm_the_registry_firer():
    """_fire_due_autoskips deliberately skips parked agents, so an armed registry
    entry would be dead weight that could still fire if the park were ever
    cleared without disarming. One timer, one actor."""
    assert '"arm_registry": False' in _error_park_arm()


# ── The window itself: one function, both ends, honours the setting ─────────

def test_the_window_is_zero_when_the_user_turned_auto_skip_off(monkeypatch):
    monkeypatch.setenv("DG_AUTO_SKIP_UNACTED_SEC", "1800")
    assert research.unacted_window_sec(True) == 1800.0
    assert research.unacted_window_sec(False) == 0.0, (
        "0 is the whole contract: no deadline, the card waits for a human"
    )


def test_the_window_still_tracks_the_shared_budget(monkeypatch):
    monkeypatch.setenv("DG_AUTO_SKIP_UNACTED_SEC", "42")
    assert research.unacted_window_sec(True) == 42.0, (
        "must read the ONE budget, not re-hardcode 1800"
    )


def test_both_ends_arm_their_window_through_that_one_function():
    """The regression was two ends of the SAME commit disagreeing: P3 gated its
    window on the flag, P2 armed unconditionally."""
    p2 = _error_park_arm()
    p3 = _p3_link_card()
    for where, src in (("P2 error park", p2), ("P3 link card", p3)):
        assert "unacted_window_sec(_runtime.auto_skip_stuck)" in src, where
    assert "AUTO_SKIP_UNACTED_SEC if" not in p2, (
        "an inline conditional here is exactly how the two ends drifted apart"
    )


def test_a_zero_window_arms_no_deadline_on_the_card():
    """A countdown to a fire that cannot happen is worse than no countdown."""
    arm = _error_park_arm()
    i_kw = arm.index('"auto_skip_deadline"')
    tail = arm[i_kw:i_kw + 220]
    assert "if _ae_window else {}" in tail, (
        "the deadline kwargs must be conditional on a non-zero window — with "
        "auto-skip off the card showed a 30-minute countdown to nothing"
    )


@pytest.mark.parametrize("parked,now,expect", [
    # An explicit 0 window means NO DEADLINE — never expires, however long.
    ({"since": 0.0, "timeout": 0.0}, 10 ** 9, False),
    ({"since": 0.0, "timeout": 0}, 10 ** 9, False),
    ({"since": 0.0, "timeout": None}, 10 ** 9, False),
    # A real window expires at it, not before.
    ({"since": 1000.0, "timeout": 300.0}, 1299.0, False),
    ({"since": 1000.0, "timeout": 300.0}, 1300.0, True),
    ({"since": 1000.0, "timeout": 300.0}, 5000.0, True),
    # An ABSENT timeout keeps the historical 300s default — the other four park
    # kinds must not change behaviour.
    ({"since": 1000.0}, 1299.0, False),
    ({"since": 1000.0}, 1300.0, True),
    ({}, 299.0, False),
    # Unreachable in the caller (`if _parked:` guards it) — pinned only so the
    # helper cannot start raising, and it too takes the 300s default.
    (None, 10 ** 9, True),
])
def test_park_window_elapsed(parked, now, expect):
    assert research.park_window_elapsed(parked, now=now) is expect


def test_the_parked_block_reads_the_window_through_that_helper():
    """The inline `>= _parked.get("timeout", 300)` it replaces is true at 0."""
    src = code_only(research.poll_all_agents_round_robin)
    assert '_pk_expired = (_pk_dec == "pending" and park_window_elapsed(_parked))' in src
    assert '>= _parked.get("timeout"' not in src, (
        "comparing straight against the raw value is the bug: 0 expires at once"
    )


@pytest.mark.parametrize("entry,expect", [
    ({}, False),
    ({"done_count": 0, "done_marker_first_at": 0.0}, False),
    ({"done_count": 1}, True),                       # ← the swallow: 1 of the 2 needed
    ({"done_count": 2}, True),
    ({"done_marker_first_at": 1.0}, True),
    ({"done_count": None, "done_marker_first_at": None}, False),
    ({"done_count": "", "done_marker_first_at": ""}, False),
])
def test_inflight_looks_done(entry, expect):
    assert research.inflight_looks_done(entry) is expect


def test_voiding_the_signals_makes_the_staleness_guard_say_not_done():
    """The round trip is the point: writer and reader are paired, so zeroing the
    wrong field name cannot pass. A leftover done_count of 1 from the tick BEFORE
    an error verdict is what made the consumer log 'the agent already completed'
    and swallow the user's Retry."""
    p = {"done_count": 1, "done_marker_first_at": 1234.5, "page": object()}
    assert research.inflight_looks_done(p) is True
    research.void_completion_signals(p)
    assert research.inflight_looks_done(p) is False
    assert "page" in p, "only the completion readings are voided, not the entry"


def test_the_error_park_voids_the_stale_completion_signals_before_parking():
    """Order matters: the park is what keeps this dict alive for the consumer to
    read. Voiding after it would still race a same-tick reader."""
    arm = _error_park_arm()
    assert "void_completion_signals(p)" in arm
    assert arm.index("void_completion_signals(p)") < arm.index('p["awaiting_decision"] = {')
    # And the consumer must read through the paired helper, not its own copy.
    consumer = code_only(research.poll_all_agents_round_robin)
    assert "_inflight_done = inflight_looks_done(_p_inflight)" in consumer


def test_a_retracted_error_card_clears_its_own_already_raised_latch():
    """`failed_alert_emitted` suppresses fail_agent. Retracting the card without
    clearing it means a LATER failure parks in silence — a countdown running
    against a card the user cannot see."""
    src = code_only(research.poll_all_agents_round_robin)
    i = src.index("Hard retry ignored")
    branch = src[i:src.index("continue", src.index("_clear_pending_decision", i))]
    assert '_p_inflight["failed_alert_emitted"] = False' in branch


def test_fail_agent_can_opt_out_of_the_registry():
    sig = inspect.signature(research.fail_agent)
    assert "arm_registry" in sig.parameters
    assert sig.parameters["arm_registry"].default is True, (
        "opt-OUT, so every existing caller keeps its behaviour"
    )
    src = code_only(research.fail_agent)
    assert "arm_registry=arm_registry" in src, "must reach emit_decision"


def test_the_registry_firer_still_refuses_to_fire_a_parked_agent():
    """The invariant the park design leans on. If this guard is ever removed, the
    firer and the parked resolver both own the same timeout and can double-fire."""
    src = code_only(research.poll_all_agents_round_robin)
    i = src.index("async def _fire_due_autoskips")
    block = src[i:src.index("async def", i + 10)] if "async def" in src[i + 10:] else src[i:]
    assert '_p.get("awaiting_decision")' in block


# ── Phase 2: the resolver ────────────────────────────────────────────────────

def _resolver_branch() -> str:
    src = code_only(research._resolve_parked_agent_decision)
    i = src.index('if kind == "agent_error":')
    return src[i:src.index('if kind == "extract_empty_pw":', i)]


def test_retry_on_an_error_card_re_arms_a_HARD_retry():
    """Every other parked kind takes a SOFT action on Retry (reload, re-extract,
    nudge) because its page is healthy. This one's page is in a failure state, so
    a nudge recovers nothing — the corpus recovery was a HARD retry."""
    branch = _resolver_branch()
    assert "request_retry_agent_hard(key)" in branch
    for soft in ("paste_followup", "reload(", "extraction_attempts"):
        assert soft not in branch, f"a soft {soft} cannot recover a failed page"


def test_timeout_on_an_error_card_finalizes_with_the_honest_reason():
    branch = _resolver_branch()
    assert "autoskip_reason_for_status(" in branch, (
        "must not hardcode a reason — the mid-run/startup distinction is the "
        "whole point of the classifier"
    )
    assert "_finalize_agent_autoskip(" in branch
    assert "_disarm_registry(key)" in branch, "a resolved card must not leave a deadline"
    assert "del pending[name]" in branch, "the agent leaves the poll set only NOW"


def test_the_resolver_handles_agent_error_before_the_other_kinds():
    """Ordering guard: a bare `if kind == ...` chain means an earlier branch that
    matched loosely would swallow it."""
    src = code_only(research._resolve_parked_agent_decision)
    assert src.index('if kind == "agent_error":') < src.index('if kind == "extract_empty_pw":')


# ── Phase 2: the exit sweep is a backstop, not a timer ───────────────────────

def test_the_exit_sweep_refuses_to_finalize_a_live_card():
    src = code_only(research.poll_all_agents_round_robin)
    i = src.index("async def _finalize_unresolved_autoskips")
    block = src[i:src.index("async def _fire_due_autoskips", i)]
    assert 'awaiting_decision' in block, (
        "the sweep must skip an agent whose card is still live — otherwise a "
        "SIBLING agent finishing can trigger a sweep that kills it"
    )
    # And the skip must come BEFORE the finalize decision.
    assert block.index("awaiting_decision") < block.index("_needs_finalize")


# ── Phase 3: the card that blocked forever ──────────────────────────────────

def _p3_link_card() -> str:
    """From the card's own `_nb_skip_in = 0.0` seed to the end of its decision
    handling. Anchored, for the same reason `_error_branch` is."""
    src = code_only(research.run_pipeline)
    i = src.rindex("_nb_skip_in = 0.0")
    return src[i:src.index('reason=f"user_{decision}_link_extract"', i) + 60]


def test_the_p3_link_card_is_given_a_bounded_window():
    branch = _p3_link_card()
    assert "unacted_window_sec(" in branch, (
        "same budget as Phase 2 — the two ends must not drift"
    )
    assert "auto_skip_deadline" in branch
    assert "arm_registry" in branch
    assert "timeout=(_nb_skip_in if _nb_skip_in else 86400.0)" in branch, (
        "the wait must expire at the same moment the shown countdown does"
    )


def test_the_p3_window_honours_the_users_auto_skip_setting():
    """Every other auto-skip is gated on it; silently overriding it here would be
    an alert regression, which the owner explicitly warned about."""
    branch = _p3_link_card()
    assert "unacted_window_sec(_runtime.auto_skip_stuck)" in branch
    assert "_nb_skip_in = 0.0" in branch, (
        "0 means no auto-skip armed — the exemption both the sign-in wall and "
        "the auto-skip-OFF case land on"
    )


def test_a_signin_wall_is_never_auto_skipped():
    """The taxonomy classes a login card as a BLOCKER: the user CAN resolve it, so
    it must never auto-fire. Auto-skipping someone's notebook because they were
    away from a sign-in prompt is the wrong trade."""
    branch = _p3_link_card()
    i_wall = branch.index("if _nb_wall:")
    i_else = branch.index("else:", i_wall)
    wall_branch = branch[i_wall:i_else]
    assert "auto_skip_deadline" not in wall_branch
    assert "_nb_skip_in =" not in wall_branch


def test_an_unanswered_p3_card_auto_skips_instead_of_terminating_the_run():
    """Pre-fix `timeout` fell through to `pipeline_stopped` + return. With the
    24-hour default that was unreachable, so the run just hung; with a real
    window it would have KILLED the run instead of finishing it partially."""
    branch = _p3_link_card()
    i = branch.index('if decision == "skip" or _nb_auto or _nb_backstop:')
    skip_branch = branch[i:branch.index("break", i)]
    assert 'reason=("auto_skip_link_unanswered"' in skip_branch
    assert "_p3_link_skipped = True" in skip_branch
    assert "skipped_phases.add(4)" in skip_branch


def test_an_ARMED_timeout_is_the_only_timeout_that_may_skip():
    """The bug: `decision in ("skip", "timeout")` treated the 24-hour outer
    backstop as though it were the 30-minute countdown the FE had shown. It had
    not been shown — a sign-in wall and auto-skip-OFF both arm nothing — so the
    two documented exemptions auto-skipped after a weekend away."""
    branch = _p3_link_card()
    assert "_nb_auto = is_armed_timeout(decision, _nb_skip_in)" in branch
    assert 'if decision in ("skip", "timeout")' not in branch, (
        "the condition that could not tell the two timeouts apart"
    )


def test_an_UNARMED_timeout_still_DELIVERS_and_is_not_blamed_on_the_user():
    """Three outcomes, three reasons, one exit.

    An earlier attempt at this fix emitted `pipeline_stopped` + `return` for the
    unarmed expiry. That returns out of run_pipeline ABOVE the terminal handoff,
    so a run whose P1 and P2 had fully succeeded lost its Google Doc, its email
    and its P3 checkpoint — total loss where the bug it replaced at least
    delivered. The unarmed case must take the SAME skip-and-continue exit, with
    its own honest reason."""
    branch = _p3_link_card()
    assert "_nb_backstop = decision == \"timeout\" and not _nb_auto" in branch
    assert 'if decision == "skip" or _nb_auto or _nb_backstop:' in branch
    assert 'reason=("auto_skip_link_unanswered" if _nb_auto' in branch
    assert '"link_unresolved_backstop" if _nb_backstop' in branch
    # No stop/return anywhere between the branch and its `break`.
    body = branch[branch.index('if decision == "skip" or _nb_auto or _nb_backstop:'):]
    body = body[:body.index("break")]
    assert "pipeline_stopped" not in body
    assert "return" not in body
    # The remaining terminate path can no longer be reached by a timeout, so it
    # can no longer emit "user_timeout_link_extract".
    i_stop = branch.index('reason=f"user_{decision}_link_extract"')
    assert 'if decision == "timeout":' not in branch[:i_stop], (
        "a separate timeout branch before the stop means it was NOT folded in"
    )


def test_the_three_p3_reasons_are_all_distinct():
    """'You chose this', 'your 30 minutes ran out' and 'we waited a whole day'
    are three different stories, and only one of them is a setting the user
    chose."""
    branch = _p3_link_card()
    reasons = {"user_skip_at_link_extract", "auto_skip_link_unanswered",
               "link_unresolved_backstop"}
    for r in reasons:
        assert r in branch, r
    assert len(reasons) == 3


# ── The window family, applied everywhere it belongs ────────────────────────

def test_the_claude_two_artifact_park_honours_the_auto_skip_setting():
    """The fifth site in this family, and the one nobody had noticed. Its park
    carries a 300 s literal and its card is emitted with NO deadline, so with
    auto-skip OFF the user saw a Retry/Skip card with no countdown while a hidden
    ~10-minute fuse burned down to a greyed tile and a closed tab."""
    src = code_only(research._resolve_parked_agent_decision)
    i = src.index('if kind == "claude_2artifact_hf":')
    branch = src[i:src.index('if kind == "chat_mode":', i)]
    assert 'if p["hf_timeouts"] >= 2 and _runtime.auto_skip_stuck:' in branch
    # With the setting off it must fall through to keep-polling, not the finalizer.
    i_gate = branch.index('if p["hf_timeouts"] >= 2')
    i_final = branch.index("_finalize_agent_autoskip(", i_gate)
    assert i_gate < i_final, "the gate must precede the finalize it guards"


def test_the_budget_extension_is_still_spent_only_ONCE():
    """The gate above routes every later timeout into the tail that used to run
    only for the first one. That tail rewinds `start_time` to max_wait-15min, so
    re-extending on each ~5-minute re-park would keep `elapsed` below the agent's
    absolute limit forever and an unattended run would loop here indefinitely."""
    src = code_only(research._resolve_parked_agent_decision)
    i = src.index('if kind == "claude_2artifact_hf":')
    branch = src[i:src.index('if kind == "chat_mode":', i)]
    # Scoped past the `_retry` arm — a user Retry legitimately rewinds the budget
    # too, and that one must keep working.
    tail = branch[branch.index('p["hf_timeouts"] = int('):]
    assert 'if p["hf_timeouts"] < 2:' in tail
    i_guard = tail.index('if p["hf_timeouts"] < 2:')
    assert tail.count('p["start_time"] = time.time() - (max_wait_min * 60)') == 1, (
        "one rewind on the timeout path; a second would reopen the loop"
    )
    assert i_guard < tail.index('p["start_time"] = time.time() - (max_wait_min * 60)'), (
        "the rewind must sit INSIDE the once-only guard"
    )


@pytest.mark.parametrize("decision,armed,expect", [
    ("timeout", 1800.0, True),      # auto-skip on, the countdown really elapsed
    ("timeout", 0.0, False),        # auto-skip off / sign-in wall: nothing armed
    ("timeout", 0, False),          # int zero, same thing
    ("timeout", None, False),       # never armed at all
    ("skip", 1800.0, False),        # a user decision is not a timeout
    ("retry", 1800.0, False),
    ("stop", 1800.0, False),
    ("", 1800.0, False),
])
def test_is_armed_timeout(decision, armed, expect):
    assert research.is_armed_timeout(decision, armed) is expect


def test_the_two_p3_outcomes_carry_different_reasons():
    """A user choosing Skip and a card nobody answered are different stories and
    must not share a reason slug — the FE renders them differently."""
    branch = _p3_link_card()
    assert "user_skip_at_link_extract" in branch
    assert "auto_skip_link_unanswered" in branch


# ── The copy that was a lie ─────────────────────────────────────────────────

def test_the_unanswered_copy_is_only_used_after_the_window_actually_elapsed():
    """"its Retry/Skip alert went unanswered" was printed at 0 seconds. It may
    now appear only on a timeout path."""
    src = code_only(research.poll_all_agents_round_robin)
    i = src.index("async def _finalize_unresolved_autoskips")
    sweep = src[i:src.index("async def _fire_due_autoskips", i)]
    # The sweep is now a backstop reached only after every park resolved or
    # expired, so its copy is honest there. What must NOT exist is the old
    # same-tick raise-then-finalize: the error branch may not call the finalizer.
    assert "_finalize_agent_autoskip" not in _error_branch(), (
        "the branch that RAISES the card must never also finalize it"
    )
    assert "went unanswered" in sweep


@pytest.mark.parametrize("status,expect_copy", [
    ("agent_error", "started fine"),
    ("failed_setup", "couldn't start"),
])
def test_the_finalize_copy_still_matches_how_the_agent_actually_died(status, expect_copy):
    _, copy_key, why = research.autoskip_reason_for_status(status)
    assert expect_copy in research._autoskip_details(copy_key, "Claude", why)


def test_no_skip_branch_regressed_to_dropping_without_a_terminal_event():
    """Cheap re-run of the #100 family guard over the new code."""
    src = code_only(inspect.getsource(research))
    for m in re.finditer(r'\n(\s*)if kind == "agent_error":\n', src):
        body = src[m.end():m.end() + 2000]
        assert "_finalize_agent_autoskip" in body or "request_retry_agent_hard" in body
