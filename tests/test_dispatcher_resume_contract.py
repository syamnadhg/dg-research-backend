"""Dispatcher resume-contract regression guard.

User E2E 2026-05-18 revealed that several Firestore command-action
handlers in _start_command_listener set their action flag but never
called _controls.request_resume() — so the pipeline stayed paused
after the user clicked Retry / Skip / Continue on a paused alert.

Contract (DGOPS-2026-05-18): every dispatcher action that represents
human-intervention-on-a-paused-alert MUST call request_resume() in
addition to setting its action-specific flag. The flag tells the
waiting coroutine WHAT to do; resume tells it that NEW state is ready
to be consumed.

request_resume is idempotent (no-op when not paused), so adding it to
human-intervention handlers is safe even when the action runs while
the pipeline isn't paused.

This test scans research.py source for the dispatcher function body
and asserts the contract holds for every required action. Adding a new
action that should release pause? Add it to REQUIRED_RESUME_ACTIONS
and the dispatcher in one PR.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


REQUIRED_RESUME_ACTIONS = [
    # Phase 0 verify dropdown — paused at init_verify_loop
    "skip_init_verify",
    "retry_init_verify",
    # Phase 2 agent alerts — paused inside round-robin pending agent
    "skip_agent",
    "retry_agent",
    "continue_partial_agent",
    "poke_agent",
    "wait_longer_agent",
    # Phase-level watchdog / warning resolutions
    "skip_phase",
    "retry_phase",
    "continue_anyway",
    # Agent-decision modal (claude_chat_mode, agent_link_failed, etc.)
    "agent_decision",
]


def _read_dispatcher_body():
    """Extract the on_snapshot inner function body where dispatch lives."""
    src_path = os.path.join(os.path.dirname(__file__), "..", "research.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    # _start_command_listener contains the inner on_snapshot. We grab the
    # whole outer function body — the elif chain lives inside it.
    m = re.search(
        r"def _start_command_listener\b.*?(?=^def \w+\(|^async def \w+\()",
        src,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "_start_command_listener function not found in research.py"
    return m.group(0)


def _extract_action_block(body, action):
    """Return the source lines that belong to `elif action == "<action>":`.

    Block ends at the FIRST line whose indent is ≤ the elif keyword indent
    (12 spaces in research.py's on_snapshot). That cleanly terminates at
    either the next `elif action ==` (same indent), a section-divider
    comment (same indent), or the closing of the enclosing function
    (outdent).

    Line-based extraction is more robust than the regex-with-negative-
    lookahead approach: it doesn't false-positive on comments between
    handlers that happen to contain the string '_controls.request_resume'
    (caught by advisor 2026-05-18)."""
    ELIF_INDENT = 12  # research.py dispatcher elif column

    lines = body.split("\n")
    pat = re.compile(rf'^ {{{ELIF_INDENT}}}elif action == "{re.escape(action)}":\s*$')
    start = None
    for i, line in enumerate(lines):
        if pat.match(line):
            start = i + 1
            break
    if start is None:
        return None

    block = []
    for line in lines[start:]:
        if line.strip() == "":
            block.append(line)
            continue
        # Indentation of this content line
        indent = len(line) - len(line.lstrip())
        if indent <= ELIF_INDENT:
            break  # outdented from the elif keyword — block has ended
        block.append(line)
    return "\n".join(block)


def test_dispatcher_function_found():
    """Sanity: confirm we can find the dispatcher in research.py.
    Tests below depend on this; fails fast with clear message."""
    body = _read_dispatcher_body()
    assert "elif action ==" in body, "dispatcher elif chain not found in function body"


def test_required_actions_have_handlers():
    """Every action in REQUIRED_RESUME_ACTIONS must have a handler.
    Catches typos in either this list or in the dispatcher source."""
    body = _read_dispatcher_body()
    for action in REQUIRED_RESUME_ACTIONS:
        block = _extract_action_block(body, action)
        assert block is not None, f"action handler for {action!r} not found in dispatcher"


def test_required_actions_call_request_resume():
    """The contract: every human-intervention action must call
    request_resume() so the pipeline doesn't stay paused after the user
    clicks the action button. Was broken for 8 actions before 2026-05-18.

    Regression-asserting: adding a new resume-required action to
    REQUIRED_RESUME_ACTIONS without wiring request_resume in the handler
    fails this test."""
    body = _read_dispatcher_body()
    missing = []
    for action in REQUIRED_RESUME_ACTIONS:
        block = _extract_action_block(body, action)
        if block is None:
            missing.append(f"{action} (handler not found)")
            continue
        if "_controls.request_resume" not in block:
            missing.append(action)
    assert not missing, (
        f"Dispatcher actions missing request_resume() call: {missing}. "
        f"Per the 2026-05-18 human-intervention contract, every action "
        f"that acknowledges a paused alert must release the pause. "
        f"See the comment block in research.py just before the "
        f"`elif action == \"skip_init_verify\":` handler."
    )


def test_non_pause_actions_dont_falsely_resume():
    """Actions that shouldn't trigger resume should NOT have it either.
    Catches sloppy 'add resume everywhere' regressions that would release
    pause when the user explicitly wanted to stay paused.

    Currently enforced for: pause (just paused — resuming defeats it),
    stop / discard_run (terminating, no need to resume), ping (watchdog
    no-op), add_context / config (mutation only, doesn't acknowledge
    an alert)."""
    body = _read_dispatcher_body()
    must_not_resume = ["pause", "stop", "discard_run", "ping", "add_context", "config", "dismiss_alert"]
    for action in must_not_resume:
        block = _extract_action_block(body, action)
        if block is None:
            continue  # action may be handled in an outer if/elif chain (ping/stop are if not elif)
        assert "_controls.request_resume" not in block, (
            f"action {action!r} has request_resume() — this defeats the "
            f"action's intent (e.g. user just paused; resume undoes it). "
            f"Remove the request_resume call from that handler."
        )
