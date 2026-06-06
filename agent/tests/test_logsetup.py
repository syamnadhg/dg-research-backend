"""Operational logging setup."""

import logging

import pytest

from facade import logsetup


@pytest.fixture(autouse=True)
def _isolate_facade_logger():
    """Don't let one test's handlers (esp. file handlers on tmp dirs) leak."""
    yield
    logger = logging.getLogger("facade")
    for h in list(logger.handlers):
        if getattr(h, logsetup._HANDLER_TAG, False):
            h.close()
            logger.removeHandler(h)
    logger.setLevel(logging.WARNING)
    logger.propagate = True


def test_creates_and_writes_log_file(tmp_path):
    p = tmp_path / "bridge.log"
    resolved = logsetup.configure(to_file=True, log_file=p)
    assert resolved == p
    logging.getLogger("facade.unit").info("hello-marker-123")
    assert p.exists()
    assert "hello-marker-123" in p.read_text(encoding="utf-8")


def test_verbose_toggles_level(tmp_path):
    logsetup.configure(verbose=True, to_file=False)
    assert logging.getLogger("facade").level == logging.DEBUG
    logsetup.configure(verbose=False, to_file=False)
    assert logging.getLogger("facade").level == logging.INFO


def test_idempotent_no_handler_stacking(tmp_path):
    p = tmp_path / "b.log"
    logsetup.configure(to_file=True, log_file=p)
    n1 = len(logging.getLogger("facade").handlers)
    logsetup.configure(to_file=True, log_file=p)
    n2 = len(logging.getLogger("facade").handlers)
    assert n1 == n2 == 2  # one console + one file, replaced not stacked


def test_console_only_when_to_file_false(tmp_path):
    resolved = logsetup.configure(to_file=False)
    assert resolved is None
    handlers = logging.getLogger("facade").handlers
    assert len([h for h in handlers if getattr(h, logsetup._HANDLER_TAG, False)]) == 1


def test_default_is_console_only(tmp_path):
    # A bare configure() must NOT write to the real ~/.super-agent/bridge.log.
    resolved = logsetup.configure()
    assert resolved is None
    handlers = logging.getLogger("facade").handlers
    assert len([h for h in handlers if getattr(h, logsetup._HANDLER_TAG, False)]) == 1


def test_no_propagation_to_root(tmp_path):
    logsetup.configure(to_file=False)
    assert logging.getLogger("facade").propagate is False
