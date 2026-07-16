"""#955 Phase 6 (BE half) — command-ack at dispatcher intake.

The FE stamps a client-nonce `command_id` on each command doc and shows the
button as "Sending…" until it hears back. The BE dispatcher acks the instant it
ACCEPTS the command (the control flag is set microseconds later) — NOT when the
engine consumes it, which can lag minutes during setup / hard-retry and would
falsely re-enable the button at the FE's 12s no-ack timeout.

Source-pin guards on the dispatcher (`_start_command_listener.on_snapshot`) —
the block is a deeply-nested Firestore callback, so we assert its shape rather
than drive a live snapshot.

Run: pytest tests/test_command_ack_955.py -v
"""
from __future__ import annotations

import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402

_SRC = inspect.getsource(research._start_command_listener)


def test_command_ack_emitted_with_command_id_and_decision_id():
    assert 'emit_event("command_ack"' in _SRC, (
        "the dispatcher must emit a command_ack event on intake (#955 Phase 6)."
    )
    # It carries the client nonce + the card's decision_id so the FE can match
    # the ack to the exact button it disabled.
    assert "command_id=_cmd_id" in _SRC
    assert 'data.get("decisionId")' in _SRC and 'data.get("decision_id")' in _SRC


def test_command_ack_is_at_intake_not_engine_consumption():
    # The ack sits right after the action is parsed (dispatcher intake), BEFORE
    # the ping branch — so it fires as soon as the command is accepted, not when
    # the engine eventually consumes the flag (which can lag minutes).
    _at_action = _SRC.index('action = data.get("action", "")')
    _at_ack = _SRC.index('emit_event("command_ack"')
    _at_ping = _SRC.index('if action == "ping":')
    assert _at_action < _at_ack < _at_ping, (
        "command_ack must be emitted at intake (after parse, before the ping "
        "branch), not deep in an action's engine-consumption path."
    )


def test_command_ack_skips_ping_and_missing_id():
    # Gated on a present command_id AND a real, non-ping action — a legacy
    # client that stamps no command_id gets no ack (nothing is waiting on one),
    # and ping keeps its own pong path.
    m = re.search(r"_cmd_id = data\.get\(\"command_id\"\)(.*?)if action == \"ping\":",
                  _SRC, re.DOTALL)
    assert m, "command_ack gating block not found before the ping branch."
    block = m.group(1)
    assert 'if _cmd_id and action and action != "ping":' in block, (
        "the ack must be gated on a present command_id + a real non-ping action."
    )


def test_command_ack_skips_invalid_agent_decision():
    # Acking an invalid agent_decision would falsely confirm a no-op (the consume
    # branch rejects a decision not in the whitelist), so the ack must gate on
    # the same whitelist. Gap #1: the whitelist now includes "continue_chat"
    # (non-blocking chat_mode's "Continue in chat mode") on BOTH the ack + consume
    # sides, so a valid continue_chat is acked and an invalid decision still isn't.
    m = re.search(r"_cmd_id = data\.get\(\"command_id\"\)(.*?)if action == \"ping\":",
                  _SRC, re.DOTALL)
    block = m.group(1)
    assert 'action == "agent_decision"' in block
    assert '_ad in ("retry", "skip", "stop", "continue_chat")' in block, (
        "an invalid agent_decision must NOT be acked (it does nothing)."
    )
