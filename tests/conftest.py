"""Shared pytest fixtures / environment pins for the dg-research-backend suite.

#955 Phase 3: the async AI copy sharpen (`DG_ALERT_AI_COPY`) is OFF in prod by
default and MUST stay off across the whole suite so every alert-copy assertion
sees the deterministic TEMPLATE, never a live (or mocked) LLM rewrite. Without
this pin a developer with the flag exported in their shell would see spurious
byte-parity failures. Tests that exercise the enabled path opt in explicitly
with `monkeypatch.setenv("DG_ALERT_AI_COPY", "1")` (pytest restores it after).
"""
import os

import pytest

# Force OFF at collection time — before any test module imports `research`.
os.environ["DG_ALERT_AI_COPY"] = "0"


@pytest.fixture(autouse=True)
def _alert_ai_copy_off_by_default():
    """Re-assert the OFF default before every test so one test flipping it on
    via a raw os.environ write (rather than monkeypatch) can't leak forward."""
    os.environ["DG_ALERT_AI_COPY"] = "0"
    yield
