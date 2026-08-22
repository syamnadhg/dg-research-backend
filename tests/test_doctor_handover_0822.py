"""Wave 4: the doctor's hand-over line stops being a network-fault feature.

⛔⛔ IT LIVED INSIDE ONE BRANCH. `_doctor_share_logs_line()` — "Still stuck? Run
`--send-logs`… No terminal? Use Report Bug" — was printed only under
`elif _firebase_down_reason == "transient"`. Every other fault this command
reports ends the page with nothing to do next: patchright not importable,
Chromium refusing to launch, the supervisor unit missing, the refresh token
revoked, `--serve` not running, DISPLAY not reaching the user unit. The owner's
ask (2026-08-17) was that *every* failure a person can be left holding should
point at the way to hand it over.

⭐ AND `✓ Healthy` IS THE CASE A PERSON IS MOST STUCK IN. They ran the doctor
because something is wrong and the answer was that nothing here is — which is
precisely when the logs are the next move. The line opens "Still stuck?", a
question only that reader is being asked.

⚠ SOURCE-PINNED, AND THAT IS A REAL LIMIT WORTH STATING. `run_doctor` probes
Firestore, imports patchright and launches Chromium in a subprocess with a 60s
timeout; there is no cheap way to execute it here. So these tests pin the call
site's POSITION — unconditional, at function level, after the summary — which is
the property that makes it print on every run, and they pin that the branch it
used to live in no longer prints it. Mutation confirms the pins can feel both.

Run: pytest tests/test_doctor_handover_0822.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402


CALL = 'print(f"  {_c(_DIM, _doctor_share_logs_line())}")'


def _doctor() -> str:
    return code_only_deep(research.run_doctor)


def test_the_doctor_ends_every_run_with_the_hand_over():
    """⛔ FOUR SPACES. The indentation IS the assertion: at function level the
    line is unconditional, and one level deeper it is back inside whichever
    branch happened to enclose it."""
    src = _doctor()
    assert f"\n    {CALL}\n" in src, (
        "the hand-over is not printed unconditionally at the end of a doctor run")


def test_the_hand_over_is_printed_once_and_not_per_fault():
    """⛔ Two authors of one sentence is how `--resurrect` came to be prescribed
    twice in a three-step list — the defect `_dedupe_actions` exists for."""
    assert _doctor().count("_doctor_share_logs_line()") == 1


def test_the_network_branch_no_longer_carries_its_own_copy():
    """The branch it used to live in must not print it a second time now that
    every run ends with it."""
    src = _doctor()
    net = src[src.index('elif _firebase_down_reason == "transient":'):]
    net = net[:net.index('    else:\n        _fail("Firestore init failed"')]
    assert "_probe_host(" in net, "the slice missed the network branch entirely"
    assert "_doctor_share_logs_line()" not in net, (
        "the network fault now gets the hand-over twice on one page")


def test_the_hand_over_comes_after_the_verdict_not_before_it():
    """It answers "what now", so it has to follow both the healthy verdict and
    the issue count — not sit in the middle of the checks."""
    src = _doctor()
    assert src.index(CALL) > src.index("'✓  Healthy.'")
    assert src.index(CALL) > src.index("Manual steps still required")


def test_a_healthy_machine_is_offered_it_too():
    """⭐ THE HALF THAT IS EASY TO DROP. `issues_found == 0` prints one line and
    used to end there. The call sits AFTER the whole if/else, so both verdicts
    reach it — pinned by slicing from the healthy branch and finding the call
    outside the `else` that follows it."""
    src = _doctor()
    healthy = src.index("if issues_found == 0:")
    assert src.index(CALL) > healthy
    # …and not inside the else, which is where "only when something is wrong"
    # would put it.
    else_block = src[src.index("        tm.tm_emit(tm.Ev.DOCTOR_RUN"):src.index(CALL)]
    assert "_doctor_share_logs_line" not in else_block


def test_the_line_itself_still_names_both_routes():
    """Re-pinned here because this wave widened WHO sees it — if the sentence
    ever loses the command or the no-terminal route, it is now wrong on every
    page rather than on one."""
    line = research._doctor_share_logs_line()
    assert "--send-logs" in line
    assert "Report Bug" in line
    assert 'add_argument("--send-logs"' in inspect.getsource(research), (
        "the line names a command that no longer exists")
