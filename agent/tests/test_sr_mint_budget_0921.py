"""A budget for the background SR-mint — shipped OFF, and why.

⛔⛔ THE LOOP: the watchdog re-checks every run in its 20-row window once a minute,
and a run whose share-link gap can never close costs one billed
POST /api/mintSrLinks per minute, forever. The code carries THREE separate
post-mortems of this exact loop, each closed by widening a hand-kept set of doc
types — so the pattern has recurred rather than been fixed. A budget bounds the
CLASS instead of its instances.

⛔⛔ AND ITS WORST CASE IS WORSE THAN THE BILL, which is why the switch is off. The
🎉 completion banner is posted ONCE and de-duped forever, and its permanent links
come from `phaseUpdates`, built from `sr` AFTER the mint on that same tick.
Suppress the mint on the tick a run completes and the single delivery message a
person ever sees ships with a missing link, with nothing to repair it. The
signature is what prevents that, and the test below IS that guarantee.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _bridge(enabled: bool):
    """Reload the module with the gate in a known state (it is read at import)."""
    if enabled:
        os.environ["DG_SR_MINT_BUDGET"] = "1"
    else:
        os.environ.pop("DG_SR_MINT_BUDGET", None)
    from facade import bridge as b
    importlib.reload(b)
    b._SR_MINT_MEMO.clear()
    return b


@pytest.fixture()
def on():
    b = _bridge(True)
    yield b
    _bridge(False)          # always leave the module in its shipped state


DONE2 = {1: "complete", 2: "complete"}
RUN = {"id": "r1", "status": "ongoing", "phase": 2, "updatedAt": "t0"}


def test_it_is_OFF_by_default_and_suppresses_nothing():
    """⭐⭐ THE SHIPPED STATE. Until there are production numbers to tune a cooldown
    against, this must not alter a single call — the memo is still maintained so
    the instrumentation can report what it WOULD have done."""
    b = _bridge(False)
    sig = b._sr_mint_signature(RUN, DONE2)
    assert b._SR_MINT_BUDGET_ENABLED is False
    assert all(b._sr_mint_allowed("r1", sig) for _ in range(10))


def test_a_stuck_run_is_bounded_once_enabled(on):
    """The loop this exists for: a gap that can never close stops costing a POST
    a minute after the budget is spent."""
    sig = on._sr_mint_signature(RUN, DONE2)
    got = [on._sr_mint_allowed("r1", sig) for _ in range(6)]
    assert got == [True, True, True, False, False, False], got


def test_a_run_that_COMPLETES_still_gets_its_mint(on):
    """⛔⛔ THE GUARANTEE THE WHOLE DESIGN RESTS ON, and the reason the memo is
    keyed on a signature rather than on the run id. A run that advances — new
    status, new phase, new updatedAt, another completed phase — earns a brand-new
    budget, so the completion tick always mints and the banner always has its
    links. Keying on the id alone is the obvious implementation and it is exactly
    the one that silently strips links off the one message the person sees."""
    spent = on._sr_mint_signature(RUN, DONE2)
    for _ in range(6):
        on._sr_mint_allowed("r1", spent)
    assert on._sr_mint_allowed("r1", spent) is False, "precondition: budget spent"

    done3 = {1: "complete", 2: "complete", 3: "complete"}
    completed = {"id": "r1", "status": "completed", "phase": 5, "updatedAt": "t1"}
    assert on._sr_mint_allowed("r1", on._sr_mint_signature(completed, done3)) is True


@pytest.mark.parametrize("field,value", [
    ("status", "completed"), ("phase", 3), ("updatedAt", "t9"),
])
def test_any_kind_of_progress_resets_the_budget(on, field, value):
    """Each component of the signature independently proves the run moved."""
    spent = on._sr_mint_signature(RUN, DONE2)
    for _ in range(6):
        on._sr_mint_allowed("r1", spent)
    moved = dict(RUN, **{field: value})
    assert on._sr_mint_allowed("r1", on._sr_mint_signature(moved, DONE2)) is True


def test_a_completed_phase_appearing_also_resets_it(on):
    """The fifth signature component: P3 finishing is progress even when status,
    phase and updatedAt all look unchanged in the window we sampled."""
    spent = on._sr_mint_signature(RUN, DONE2)
    for _ in range(6):
        on._sr_mint_allowed("r1", spent)
    more = {1: "complete", 2: "complete", 3: "complete"}
    assert on._sr_mint_allowed("r1", on._sr_mint_signature(RUN, more)) is True


def test_the_memo_is_bounded(on):
    """A dict that grows per run for the life of the process is its own bug."""
    for i in range(on._SR_MINT_MEMO_MAX + 50):
        r = {"id": f"r{i}", "status": "ongoing", "phase": 1, "updatedAt": "t"}
        on._sr_mint_allowed(r["id"], on._sr_mint_signature(r, DONE2))
    assert len(on._SR_MINT_MEMO) <= on._SR_MINT_MEMO_MAX


def test_the_manual_mint_is_never_gated():
    """⛔ WHAT MAKES A BUDGET ACCEPTABLE AT ALL. `sr status` force-mints
    unconditionally, so a person who ASKS always gets the link even when the
    background budget for that run is spent. Pinned against the source: the
    manual call site must not consult the budget."""
    import inspect
    b = _bridge(False)
    src = inspect.getsource(b._make_handler)
    manual = src[src.index("def _research_status"):]
    manual = manual[:manual.index("def _research_podcast")]
    assert "_mint_sr(" in manual, "the manual path must still mint"
    assert "_sr_mint_allowed" not in manual, (
        "the manual path must never be throttled — it is the escape hatch")
