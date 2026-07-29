"""Resuming a run whose Phase 4 already finished completes its FE-P5 handoff.

DGOPS-9508. `run_pipeline`'s `start_phase == 5` branch is the "P4 was done before
the crash, but FE-owned Phase 5 may not have run" path. It re-emits
`phase_complete phase=4` so the FE listener re-fires `triggerFeP5`, then marks the
run done for the queue gate and posts the trigger directly.

**Its last three steps never executed.** The branch called `update_delivery(...)`,
and `update_delivery` is a nested `def` ~365 lines FURTHER DOWN in the same
function — a nested def binds the name as a LOCAL of `run_pipeline`, so the early
call raised `UnboundLocalError`, and the branch `return`s long before the def is
reached. The worker's `except Exception` turned it into
`Pipeline job error: cannot access local variable 'update_delivery' ...` and
flagged the job errored.

The damage was ordering, which is why it was easy to miss: `phase_complete` and
`pipeline_resumed` had ALREADY been emitted, so the FE saw a resume start. What
never happened was everything after:

    update_delivery(status="completed")          <- crashed here
    _update_firestore_research(beDone, phase=5, currentPhase=5)
    _post_fe_p4p5_trigger(...)

So `beDone` never landed (the queue gate for the next job never fired),
`currentPhase` stayed stale at 4 — the exact symptom the comment directly above
that call says it fixes — and the FE trigger never posted, leaving the chain
dangling whenever the FE listener was not alive to catch the event.

No test invoked `run_pipeline` anywhere in the suite before this file, which is
why a guaranteed crash on a user-reachable path survived. It is reachable with a
small harness because the early setup is gated: `uid=None` skips the Firestore
bridge and `email=None` skips validation, leaving ~10 module functions to stub.

Run:  pytest tests/test_resume_at_phase5_handoff.py -v
"""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research

CHECKPOINT = {
    "topic": "checkpointed topic",
    "youtube_url": "https://youtu.be/abc123",
    "notebook_url": "https://notebooklm.google.com/notebook/xyz",
    "brief_url": "https://docs.google.com/document/d/brief",
}


class _Recorder:
    def __init__(self):
        self.events = []
        self.firestore = []
        self.triggers = []


@pytest.fixture
def resumed_run(tmp_path, monkeypatch):
    """A resume-ready queue dir plus every side effect stubbed and recorded."""
    queue_dir = tmp_path / "topic_20260728_120000"
    (queue_dir / "documents").mkdir(parents=True)
    rec = _Recorder()

    # Entry setup — stubbed because it reaches the network, the OS clipboard or
    # the log file, none of which this branch is about.
    monkeypatch.setattr(research, "resolve_api_key", lambda _k: "test-key")
    monkeypatch.setattr(research, "_capture_anthropic_attribution", lambda *a, **k: None)
    monkeypatch.setattr(research, "clear_clipboard", lambda *a, **k: None)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "init_tracks", lambda *a, **k: None)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)

    async def _noop_dispatcher():
        return None
    monkeypatch.setattr(research, "run_input_dispatcher", _noop_dispatcher)

    # The branch under test.
    monkeypatch.setattr(research, "detect_resume_phase",
                        lambda _qd: (5, "P4 complete — FE-P5 pending"))
    monkeypatch.setattr(research, "load_checkpoint", lambda _qd: dict(CHECKPOINT))
    monkeypatch.setattr(research, "emit_event",
                        lambda name, **kw: rec.events.append((name, kw)))
    monkeypatch.setattr(research, "_update_firestore_research",
                        lambda patch, *a, **k: rec.firestore.append(patch))
    monkeypatch.setattr(research, "_post_fe_p4p5_trigger",
                        lambda *a, **k: rec.triggers.append(a))

    def _run():
        asyncio.run(research.run_pipeline(
            topic="checkpointed topic", resume_dir=str(queue_dir),
            uid=None, email=None, api_key="test-key",
        ))
    return rec, queue_dir, _run


def test_resume_at_phase5_writes_delivery_completed(resumed_run):
    """The line that used to crash. delivery.json is what the FE reads for links."""
    _rec, queue_dir, run = resumed_run
    run()

    delivery = queue_dir / "delivery.json"
    assert delivery.exists(), (
        "delivery.json was never written — the update_delivery call at the top of "
        "the start_phase==5 branch did not run"
    )
    assert json.loads(delivery.read_text(encoding="utf-8"))["status"] == "completed"


def test_resume_at_phase5_marks_bedone_and_advances_currentphase(resumed_run):
    """`currentPhase` stalling at 4 is the documented symptom this branch fixes.

    It could never actually fix it, because the crash was on the line above.
    """
    rec, _queue_dir, run = resumed_run
    run()

    assert rec.firestore, (
        "no Firestore patch was written — execution never got past "
        "update_delivery to the beDone marker"
    )
    patch = rec.firestore[-1]
    assert patch["beDone"] is True, "the queue gate keys off beDone"
    assert patch["phase"] == 5
    assert patch["currentPhase"] == 5, (
        "currentPhase must advance to 5 or the homepage diagram keeps painting "
        "YouTube as the active node forever post-resume"
    )
    assert patch["status"] == "ongoing"
    assert isinstance(patch.get("beDoneAt"), int)


def test_resume_at_phase5_posts_the_fe_p4p5_trigger(resumed_run):
    """The daemon-loop path cannot rely on a live FE listener, so it posts directly."""
    rec, _queue_dir, run = resumed_run
    run()
    assert rec.triggers, (
        "the FE P4/P5 trigger was never posted, so a resume running from the "
        "daemon loop leaves the phase chain dangling"
    )


def test_resume_at_phase5_reemits_phase_complete_with_checkpoint_links(resumed_run):
    """This part always worked — pinned so the fix cannot regress it.

    It is also what made the bug subtle: the FE saw a resume begin normally and
    only the follow-through was missing.
    """
    rec, _queue_dir, run = resumed_run
    run()

    completes = [kw for name, kw in rec.events if name == "phase_complete"]
    assert len(completes) == 1, f"expected one phase_complete, got {rec.events!r}"
    assert completes[0]["phase"] == 4
    urls = {link["url"] for link in completes[0]["links"]}
    assert urls == {CHECKPOINT["youtube_url"], CHECKPOINT["notebook_url"],
                    CHECKPOINT["brief_url"]}, (
        "the re-emitted phase_complete must carry the checkpoint links, or the "
        "FE re-renders Phase 4 with nothing in it"
    )
    assert any(name == "pipeline_resumed" for name, _ in rec.events)


def test_the_whole_branch_runs_in_order_without_raising(resumed_run):
    """End-to-end ordering: all four effects, one call, no exception.

    Before the fix this raised UnboundLocalError midway, so the first two effects
    landed and the last three did not. Asserting them together is what pins the
    ordering rather than each step in isolation.
    """
    rec, queue_dir, run = resumed_run
    run()  # must not raise

    assert any(name == "pipeline_resumed" for name, _ in rec.events)
    assert any(name == "phase_complete" for name, _ in rec.events)
    assert (queue_dir / "delivery.json").exists()
    assert rec.firestore
    assert rec.triggers


def test_a_completed_run_is_not_resumed(monkeypatch, resumed_run):
    """start_phase >= 6 returns early — no delivery write, no beDone, no trigger."""
    rec, queue_dir, run = resumed_run
    monkeypatch.setattr(research, "detect_resume_phase", lambda _qd: (6, "complete"))
    run()

    assert not (queue_dir / "delivery.json").exists()
    assert rec.firestore == []
    assert rec.triggers == []
