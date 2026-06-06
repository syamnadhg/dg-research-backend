"""Operational logging for the Super Agent bridge.

One place that wires up logging so every entry point (the `agent` CLI, the
long-running `serve` bridge) logs consistently:

  * a rotating FILE handler at ~/.super-agent/bridge.log (the durable record an
    operator greps later — request lines + run-lifecycle events), and
  * a CONSOLE handler (stderr) for live feedback.

Default level is INFO; ``--verbose`` flips both handlers to DEBUG (per-request
lines, token-refresh detail). We attach handlers to the ``facade`` package
logger (not the root) so we never capture third-party library noise, and the
call is idempotent — re-invoking it replaces our handlers rather than stacking
duplicates.

NEVER log a token or refresh secret. Lifecycle logs carry uid/email/run-id
only; the secret store + securetoken/Firestore clients deliberately log neither
the refresh token nor the id token.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config

_PKG_LOGGER = "facade"
_HANDLER_TAG = "_super_agent_handler"  # marks handlers we own, for idempotency

_FILE_MAX_BYTES = 1_000_000
_FILE_BACKUPS = 3

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _tag(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _HANDLER_TAG, True)
    return handler


def configure(verbose: bool = False, *, to_file: bool = False, log_file: Path | None = None) -> Path | None:
    """Configure the ``facade`` logger. Idempotent.

    Console-only by default; durable file logging is OPT-IN (only ``agent serve``
    wants it) so a bare ``configure()`` never silently writes to the real
    ~/.super-agent/bridge.log. Returns the resolved log-file path (or None if
    file logging was disabled or the file couldn't be opened). A failure to open
    the log file degrades to console-only rather than crashing the bridge.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger(_PKG_LOGGER)
    logger.setLevel(level)
    logger.propagate = False  # don't double-emit via the root logger

    # Drop (and close) any handlers we previously installed so re-configuring
    # doesn't stack or leak a file handle.
    for h in [h for h in logger.handlers if getattr(h, _HANDLER_TAG, False)]:
        logger.removeHandler(h)
        h.close()

    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    console = _tag(logging.StreamHandler())
    # Be self-sufficient on a legacy (cp1252) console rather than relying on the
    # CLI's _force_utf8_output having run: degrade un-encodable chars instead of
    # raising UnicodeEncodeError. No-op on streams that can't be reconfigured.
    try:
        console.stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    resolved: Path | None = None
    if to_file:
        path = log_file or config.log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fileh = _tag(
                RotatingFileHandler(
                    path, maxBytes=_FILE_MAX_BYTES, backupCount=_FILE_BACKUPS, encoding="utf-8"
                )
            )
            fileh.setLevel(level)
            fileh.setFormatter(fmt)
            logger.addHandler(fileh)
            resolved = path
        except OSError as e:  # pragma: no cover - disk/permission edge
            logger.warning("could not open log file %s — console only (%s)", path, e)
    return resolved
