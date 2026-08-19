"""The suite must not write into the developer's own machine.

⛔⛔ MEASURED 2026-08-18, on the real box. The suite had put **8,025 test events**
into `~/.super-research/telemetry/`, and three were sitting in the pending spool
waiting to be POSTed to PRODUCTION the next time a human ran any command — a
fake install id and a synthetic research id, indistinguishable at the sink from
a real machine reporting real activity.

The conftest fixture that exists to prevent exactly this redirects
`research._STATE_DIR`. `telemetry.py` imports nothing from research — on purpose,
so a telemetry failure can never sit in the path of the thing it measures — and
therefore derives its own directory from `Path.home()`, which that fixture could
not see. One module over, the isolation the suite thought it had was gone.

These tests are the property, not the patch: they fail if any future module
starts writing under the real home again.
"""
from pathlib import Path

import research
import telemetry as tm


REAL_HOME_STATE = Path.home() / ".super-research"


def test_the_telemetry_spool_is_redirected_away_from_the_real_home():
    """⛔ The one that would have caught it."""
    spool = tm.spool_path()
    assert REAL_HOME_STATE not in spool.parents, (
        f"the suite is writing telemetry into the real state dir: {spool}")
    assert tm.sent_log_path().parent == spool.parent


def test_the_backend_state_dir_is_redirected_too():
    assert research._STATE_DIR != REAL_HOME_STATE, (
        "the autouse isolation fixture is not applying")


def test_the_log_capture_is_redirected():
    """Run folders, session files and bundles all hang off this one root."""
    root = research._logs_root()
    assert REAL_HOME_STATE not in root.parents and root != REAL_HOME_STATE / "logs"


def test_emitting_an_event_writes_nowhere_near_the_real_home():
    """The behavioural half: actually emit, then prove where it landed."""
    before = sorted(REAL_HOME_STATE.glob("telemetry/*.jsonl")) if REAL_HOME_STATE.exists() else []
    tm.tm_emit(tm.Ev.DOCTOR_RUN, count=1)
    after = sorted(REAL_HOME_STATE.glob("telemetry/*.jsonl")) if REAL_HOME_STATE.exists() else []
    assert before == after, f"an emit reached the real home: {set(after) - set(before)}"
    assert tm.spool_path().exists(), "and it should still have gone somewhere"


def test_building_a_bundle_writes_nowhere_near_the_real_home(tmp_path):
    before = sorted(REAL_HOME_STATE.glob("logs/outgoing/*")) if REAL_HOME_STATE.exists() else []
    research._build_log_bundle(tmp_path / "b.zip")
    after = sorted(REAL_HOME_STATE.glob("logs/outgoing/*")) if REAL_HOME_STATE.exists() else []
    assert before == after


def test_arming_a_run_capture_writes_nowhere_near_the_real_home():
    before = sorted(REAL_HOME_STATE.glob("logs/runs/*")) if REAL_HOME_STATE.exists() else []
    with research._RunLogCapture(research_id="chat_1755500000000_1") as sink:
        assert sink is not None
        research.log("a line from the suite", "INFO")
    after = sorted(REAL_HOME_STATE.glob("logs/runs/*")) if REAL_HOME_STATE.exists() else []
    assert before == after, f"a run folder landed in the real home: {set(after) - set(before)}"
