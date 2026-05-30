"""#704 — the command-listener stale gate must apply to the FIRST snapshot only.

The per-research command listener replays every pre-existing doc as ADDED when
it first attaches; a 30s staleness check skips prior-session leftovers. But the
listener attaches at pipeline start, so a user's Retry/Resume/Skip on a paused
alert arrives LIVE — and applying the client-`timestamp` check to live commands
silently dropped legit clicks on browser-vs-BE clock skew, leaving the run stuck
on pause.

This is a source-inspection guard (the gate lives inside an onSnapshot closure,
not a unit-testable pure function). It pins the structure: the stale check must
sit inside `if is_first_snapshot:`, and the flag must be consumed so it only
gates the initial replay. Mirrors the source-inspection style of
test_safety_net_constants.py.
"""
import inspect

import research


def test_stale_gate_is_gated_on_first_snapshot():
    src = inspect.getsource(research._start_command_listener)

    assert "is_first_snapshot" in src, (
        "first-snapshot flag missing from _start_command_listener — the stale "
        "gate must NOT apply to live commands (#704). If you removed it, live "
        "Retry/Resume clicks can be silently staleSkipped and the run hangs."
    )

    i_flag = src.index("if is_first_snapshot:")
    i_stale = src.index("STALE_COMMAND_AGE_MS")
    assert i_flag < i_stale, (
        "STALE_COMMAND_AGE_MS must live INSIDE the `if is_first_snapshot:` "
        "block. If the staleness check runs for every change again, live "
        "commands can be dropped on clock skew (#704 regression)."
    )

    assert '_cmd_first_snapshot["v"] = False' in src, (
        "the first-snapshot flag must be flipped to False so the gate only "
        "covers the initial replay; otherwise it never gates and every command "
        "(including stale prior-session replays) executes."
    )
