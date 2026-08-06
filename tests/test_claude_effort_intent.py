"""Claude's effort tier must appear in the run's own verdict.

The 6 August run confirmed the tier off the composer trigger and skipped the
submenu — correct, and the reason the diagnostic added for that ticket never
fired. Checking why turned up the more actionable half: when the submenu DOES
fail to mount, the run proceeds with the tier left as it was (the reasoning
toggle is conditional on the submenu having opened), and Claude's effort had NO
entry in the end-of-run DOM-intent summary where ChatGPT's model pill does. So a
correct skip and a silent quality loss were indistinguishable from the one place
an operator looks.

On this family the reasoning knob is the quality lever for research work, so
"could not confirm the tier" is the single most worthwhile thing here to be able
to search a log for.
"""
import pytest

import research
from conftest import code_only


# ── The outcome mapping, by execution ────────────────────────────────────────

def test_a_tier_read_off_the_trigger_is_already():
    assert research._claude_effort_outcome(True, "trigger") == "already"


def test_a_tier_set_in_the_popover_is_verified():
    assert research._claude_effort_outcome(True, "submenu") == "verified"


def test_an_unconfirmed_tier_is_missed():
    assert research._claude_effort_outcome(False, "") == "missed"


def test_the_cheap_path_and_the_real_verification_stay_distinct():
    """Both are confirmed. Collapsing them under one label is what made a silent
    failure look like a skip."""
    assert research._claude_effort_outcome(True, "trigger") != \
        research._claude_effort_outcome(True, "submenu")


def test_a_via_of_trigger_wins_even_if_the_flag_was_never_set():
    """Defensive: the trigger path sets both together, so this state should not
    arise — but if it ever does, the honest reading is still "already read it",
    never "missed"."""
    assert research._claude_effort_outcome(False, "trigger") == "already"


@pytest.mark.parametrize("via", ["", "none", "unknown"])
def test_any_other_via_falls_back_to_the_confirmed_flag(via):
    assert research._claude_effort_outcome(True, via) == "verified"
    assert research._claude_effort_outcome(False, via) == "missed"


def test_missed_is_not_in_the_ledgers_ok_set():
    """The whole point: a missed tier must count against the run, so it appears
    with a cross in the summary and at WARN in the log rather than being folded
    in with the successes."""
    assert "missed" not in research._DOM_OK
    assert "already" in research._DOM_OK
    assert "verified" in research._DOM_OK


# ── The record actually reaches the ledger ───────────────────────────────────

def test_the_intent_is_recorded_from_the_setup_path():
    src = code_only(research.setup_claude_dr)
    assert '"claude.select_effort_tier"' in src
    assert "_claude_effort_outcome(_effort_confirmed, _effort_via)" in src


def test_the_intent_is_recorded_exactly_once():
    """One call at the point every path reaches. A note per branch is how a
    branch gets missed — and a second note would double-count in the summary."""
    src = code_only(research.setup_claude_dr)
    assert src.count('"claude.select_effort_tier"') == 1


def test_every_confirming_path_sets_the_via():
    """`_effort_confirmed = True` without a matching `_effort_via` would report a
    free trigger read as a real verification, or the reverse.

    ⚠ Asserted as "each confirm is immediately followed by a via", not by
    comparing totals — the first draft compared counts and failed on a correct
    fix, because the initialiser `_effort_via = ""` is a fourth assignment with no
    confirm of its own.
    """
    lines = [ln.strip() for ln in code_only(research.setup_claude_dr).splitlines()]
    confirms = [i for i, ln in enumerate(lines) if ln == "_effort_confirmed = True"]
    assert len(confirms) >= 3, f"expected the three confirm paths, found {len(confirms)}"
    for i in confirms:
        follower = next((lines[j] for j in range(i + 1, len(lines)) if lines[j]), "")
        assert follower.startswith("_effort_via = "), (
            f"confirm at line {i} is followed by {follower!r}, not a via assignment")


def test_the_miss_detail_says_what_was_wanted_and_what_it_costs():
    src = code_only(research.setup_claude_dr)
    assert "tier left as it was" in src
    assert "weaker than the run reports" in src


def test_the_record_is_filed_under_phase_two():
    """Claude only runs in phase 2; a wrong phase would file it under a phase
    that has no Claude leg and read as a stray."""
    src = code_only(research.setup_claude_dr)
    i = src.find('"claude.select_effort_tier"')
    assert "phase=2" in src[i:i + 400]


def test_the_ledger_accepts_the_new_intent_and_logs_a_miss_loudly(capsys):
    """End-to-end through the real recorder: a missed tier must land as WARN, and
    the summary must carry it."""
    research._dom_reset()
    research._dom_note("claude.select_effort_tier",
                       research._claude_effort_outcome(False, ""),
                       phase=2, via="none", detail="tier left as it was")
    out = capsys.readouterr().out
    assert "[WARN]" in out
    assert "claude.select_effort_tier: missed" in out
    research._dom_summary("test")
    summary = capsys.readouterr().out
    assert "claude.select_effort_tier" in summary
    assert "✗" in summary


def test_a_confirmed_tier_is_not_reported_as_a_problem(capsys):
    research._dom_reset()
    research._dom_note("claude.select_effort_tier",
                       research._claude_effort_outcome(True, "trigger"),
                       phase=2, via="trigger")
    out = capsys.readouterr().out
    assert "[INFO]" in out
    assert "already" in out
    assert "[WARN]" not in out
