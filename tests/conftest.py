"""Shared pytest fixtures / environment pins for the dg-research-backend suite.

#955 Phase 3: the async AI copy sharpen (`DG_ALERT_AI_COPY`) is OFF in prod by
default and MUST stay off across the whole suite so every alert-copy assertion
sees the deterministic TEMPLATE, never a live (or mocked) LLM rewrite. Without
this pin a developer with the flag exported in their shell would see spurious
byte-parity failures. Tests that exercise the enabled path opt in explicitly
with `monkeypatch.setenv("DG_ALERT_AI_COPY", "1")` (pytest restores it after).
"""
import inspect
import io
import os
import tokenize

import pytest

# Force OFF at collection time — before any test module imports `research`.
os.environ["DG_ALERT_AI_COPY"] = "0"


def code_only(target) -> str:
    """Source of `target` (a function, or a source string) with `#` comments
    stripped and all other layout preserved byte-for-byte.

    MANDATORY for any assertion that checks what the CODE does. Verified by
    mutation twice over: a mutation that DELETED `and not _p3_link_user_skipped`
    from the Phase-3 terminal gate — i.e. re-introduced the exact bug the test
    was written for — SURVIVED, because the explanatory comment directly above
    the gate names the flag and a presence assertion cannot tell code from prose.
    The same trap ate a share-dialog selector assertion whose fix comment quoted
    the selector it replaced.

    Comments are blanked IN PLACE rather than the source rebuilt from tokens:
    rebuilding normalises whitespace, which would make every assertion depend on
    how the tokenizer happens to space a condition.
    """
    src = target if isinstance(target, str) else inspect.getsource(target)
    lines = src.splitlines(keepends=True)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        r, c0 = tok.start[0] - 1, tok.start[1]
        lines[r] = (lines[r][:c0] + " " * len(tok.string)
                    + lines[r][c0 + len(tok.string):])
    return "".join(lines)


@pytest.fixture(autouse=True)
def _alert_ai_copy_off_by_default():
    """Re-assert the OFF default before every test so one test flipping it on
    via a raw os.environ write (rather than monkeypatch) can't leak forward."""
    os.environ["DG_ALERT_AI_COPY"] = "0"
    yield
