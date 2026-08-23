"""The `quiet` flag has to survive the durable mirror, not just the live event.

⛔ WHAT `quiet` IS FOR. `fail_phase(..., mark_phase_errored=False)` is a
PREFLIGHT abort: a later phase could not be reached, nothing in it errored, and
painting its tile red tells the user a step failed that never ran. The flag says
"surface the card, do not badge the tile", and the FE gates four separate
renders on `!alert.quiet`.

⛔⛔ THE MIRROR DROPPED IT. `emit_event`'s central seam persists a
`pendingDecision` so a blocking card re-surfaces on a cold chat-open, and its
payload enumerates kind / phase / agent / title / details / actions /
dismissible / alert_id plus the three unified-decision fields — and NOT `quiet`.

⚠ AND THE GATE MAKES THAT LOOK HARMLESS UNTIL YOU READ `force_mirror`. The seam
normally REFUSES to mirror a quiet card, so for most of them there is nothing to
carry. `force_mirror` is the deliberate exception, and it exists for exactly one
shape: a card that is quiet BY DESIGN and must still survive a cold open — the
login interrupt, where nothing errored and the run is simply waiting on the
person. That is the one card the mirror was rebuilding as a red ✖.
"""
import pytest

import research


def _seam(monkeypatch):
    """Keep the REAL emit_event so its mirror seam runs; stub the I/O.

    `emit_event` no-ops when `_tracks_dir` is falsy, so give it a truthy dummy.
    """
    seen: "list[dict]" = []
    monkeypatch.setattr(research, "_tracks_dir", object(), raising=False)
    monkeypatch.setattr(research, "_emit_to_firestore", lambda *a, **k: None)
    monkeypatch.setattr(research, "_update_firestore_research", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_agent_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_write_phase_terminal_status", lambda *a, **k: None)
    monkeypatch.setattr(research, "_persist_pending_decision",
                        lambda payload: seen.append(payload))
    return seen


ACTIONS = [{"id": "retry", "label": "Retry"}]


def test_an_ordinary_card_is_mirrored_as_not_quiet(monkeypatch):
    seen = _seam(monkeypatch)
    research.emit_event("pipeline_error", phase=3, error="boom",
                        actions=ACTIONS, alert_id="phase3_error")
    assert len(seen) == 1
    assert seen[0]["quiet"] is False


def test_a_quiet_card_is_not_mirrored_at_all(monkeypatch):
    """The normal case, unchanged: a preflight abort is transient and vanishes
    on recovery, so it never becomes a durable decision."""
    seen = _seam(monkeypatch)
    research.emit_event("pipeline_error", phase=3, error="boom",
                        actions=ACTIONS, alert_id="phase3_error", quiet=True)
    assert seen == []


def test_a_FORCE_MIRRORED_quiet_card_carries_the_flag(monkeypatch):
    """⛔⛔ THE ONE THAT WAS BROKEN. Quiet by design, durable by design — and
    rebuilt on cold open as a red ✖ because the flag was left behind."""
    seen = _seam(monkeypatch)
    research.emit_event("pipeline_error", phase=0, error="signed out",
                        actions=ACTIONS, alert_id="login_interrupt",
                        quiet=True, force_mirror=True)
    assert len(seen) == 1
    assert seen[0]["quiet"] is True


def test_the_flag_is_a_real_bool_not_whatever_arrived(monkeypatch):
    """The FE tests `quiet === true`. A truthy string mirrored verbatim would
    read as false there and the card would badge the tile again — a fix that
    passes every "is it carried" check and delivers nothing."""
    seen = _seam(monkeypatch)
    research.emit_event("pipeline_error", phase=1, error="x",
                        actions=ACTIONS, alert_id="a", quiet="yes",
                        force_mirror=True)
    assert seen[0]["quiet"] is True
    assert isinstance(seen[0]["quiet"], bool)


def test_an_absent_flag_mirrors_as_false_not_none(monkeypatch):
    """`None` is not `false` to a JSON consumer that spreads the document."""
    seen = _seam(monkeypatch)
    research.emit_event("pipeline_error", phase=2, agent="gemini",
                        error="x", actions=ACTIONS, alert_id="a")
    assert seen[0]["quiet"] is False


def test_the_flag_does_not_disturb_the_rest_of_the_payload(monkeypatch):
    seen = _seam(monkeypatch)
    research.emit_event("pipeline_error", phase=4, agent="Claude",
                        error="title", details="body", actions=ACTIONS,
                        alert_id="phase4_error", quiet=True, force_mirror=True)
    got = seen[0]
    assert got["kind"] == "pipeline_error"
    assert got["phase"] == 4
    assert got["agent"] == "claude"
    assert got["title"] == "title"
    assert got["details"] == "body"
    assert got["actions"] == ACTIONS
    assert got["alert_id"] == "phase4_error"


def test_a_card_with_no_actions_is_still_never_mirrored(monkeypatch):
    """The other half of the gate, pinned so the quiet change cannot loosen it:
    a card with no buttons asks nothing of the user and must stay transient."""
    seen = _seam(monkeypatch)
    research.emit_event("pipeline_error", phase=3, error="boom",
                        alert_id="phase3_error", force_mirror=True)
    assert seen == []


@pytest.mark.parametrize("kwargs", [
    {"quiet": True, "force_mirror": True},
    {},
])
def test_the_key_is_always_present(monkeypatch, kwargs):
    """A key that is sometimes absent makes the FE's `pd.quiet` undefined, and
    undefined is indistinguishable from "this build predates the field"."""
    seen = _seam(monkeypatch)
    research.emit_event("pipeline_error", phase=1, error="x",
                        actions=ACTIONS, alert_id="a", **kwargs)
    assert "quiet" in seen[0]


def test_fail_phase_still_sets_quiet_only_when_the_phase_is_not_errored(monkeypatch):
    """The producer side, pinned because this fix reads its output.

    ⚠ MY FIRST VERSION OF THIS TEST WAS WRONG. A plain `fail_phase(3)` is ALSO
    demoted to quiet when phase 3 has not started yet — #908, so a gate tagged
    with a future phase cannot paint that phase's tile red. The phase has to be
    CURRENT for a failure to be loud, which is the only state in which "loud"
    means anything.
    """
    seen = _seam(monkeypatch)
    monkeypatch.setattr(research, "emit_decision",
                        lambda **kw: seen.append(dict(kw)) or "d1")
    monkeypatch.setattr(research._runtime, "phase", 3, raising=False)

    research.fail_phase(3, "could not fetch the sources",
                        mark_phase_errored=False, actions=ACTIONS)
    assert seen[-1].get("quiet") is True

    seen.clear()
    research.fail_phase(3, "the phase failed", actions=ACTIONS)
    assert seen[-1].get("quiet") is not True


def test_a_future_phase_failure_is_demoted_to_quiet_too(monkeypatch):
    """#908, and now it reaches the tile it was always meant to reach."""
    seen = _seam(monkeypatch)
    monkeypatch.setattr(research, "emit_decision",
                        lambda **kw: seen.append(dict(kw)) or "d1")
    monkeypatch.setattr(research._runtime, "phase", 2, raising=False)
    research.fail_phase(3, "the P3 no-output gate", actions=ACTIONS)
    assert seen[-1].get("quiet") is True
