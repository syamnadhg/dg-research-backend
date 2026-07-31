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
    src = code_only(research.poll_all_agents_round_robin)
    i = src.index('"status": "agent_error"')
    return src[i - 2200:i + 900]


def test_the_mid_run_error_parks_the_agent_instead_of_dropping_it():
    """Dropping it emptied `pending`, which exited the loop, which ran the exit
    sweep — all in the tick that raised the card."""
    branch = _error_branch()
    assert 'p["awaiting_decision"] = {' in branch
    assert '"kind": "agent_error"' in branch
    assert "del pending[name]" not in branch, (
        "dropping the agent is what let the loop exit under a live card"
    )


def test_the_error_card_is_armed_with_the_full_window():
    branch = _error_branch()
    assert "_ae_window = AUTO_SKIP_UNACTED_SEC" in branch
    assert "auto_skip_deadline=(time.time() + _ae_window) * 1000" in branch, (
        "the FE counts down to this epoch — without it there is no countdown"
    )
    assert '"timeout": _ae_window' in branch, (
        "the park window and the shown deadline must be the SAME value, or the "
        "countdown and the real fire disagree"
    )


def test_the_error_card_does_not_arm_the_registry_firer():
    """_fire_due_autoskips deliberately skips parked agents, so an armed registry
    entry would be dead weight that could still fire if the park were ever
    cleared without disarming. One timer, one actor."""
    branch = _error_branch()
    assert "arm_registry=False" in branch


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
    src = code_only(research.run_pipeline)
    i = src.index('error="Couldn\'t get the NotebookLM link"')
    return src[i - 2000:i + 1200]


def test_the_p3_link_card_is_given_a_bounded_window():
    branch = _p3_link_card()
    assert "auto_skip_unacted_sec()" in branch, (
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
    assert "_runtime.auto_skip_stuck" in branch
    assert "_nb_skip_in = 0.0" in branch, (
        "0 means wait indefinitely — the pre-fix behaviour, preserved for the "
        "auto-skip-OFF case"
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
    src = code_only(research.run_pipeline)
    i = src.index('if decision in ("skip", "timeout"):')
    branch = src[i:i + 3600]
    assert 'reason=("auto_skip_link_unanswered"' in branch
    assert "_p3_link_skipped = True" in branch
    assert "skipped_phases.add(4)" in branch
    # The terminate path still exists for a real Stop — it is simply no longer
    # what an unanswered card falls into.
    j = src.index("pipeline_stopped", i)
    stop_line = src[src.rindex("\n", 0, j):j + 160]
    assert "link_extract" in stop_line
    assert "timeout" not in stop_line, (
        "a timeout must never reach the terminate path — that would kill the run "
        "instead of finishing it without the notebook"
    )


def test_the_two_p3_outcomes_carry_different_reasons():
    """A user choosing Skip and a card nobody answered are different stories and
    must not share a reason slug — the FE renders them differently."""
    src = code_only(research.run_pipeline)
    i = src.index('if decision in ("skip", "timeout"):')
    branch = src[i:i + 3600]
    assert "user_skip_at_link_extract" in branch
    assert "auto_skip_link_unanswered" in branch
    assert "_nb_auto = decision == \"timeout\"" in branch


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
