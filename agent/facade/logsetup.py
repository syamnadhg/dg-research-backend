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

import io
import logging
import os
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


def _same_file(stream, path: Path) -> bool:
    """Is this stream already writing the file at ``path``?

    ⛔ BY INODE, NOT BY NAME. The stream is inherited from whatever started the
    process — a shell redirect names the path, the process only holds the
    descriptor — so comparing names would answer "no" for the one case this
    exists to catch. Anything unanswerable (a stream with no fileno, a closed
    descriptor, a path that is not there yet) is "no": dropping the console on a
    guess would silence the only output a person watching a foreground `serve`
    can see.
    """
    try:
        a = os.fstat(stream.fileno())
        b = path.stat()
    except (OSError, ValueError, AttributeError, io.UnsupportedOperation):
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


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
    console_is_the_log_file = False
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
            # ⛔⛔ ONE WRITER PER FILE. On the fleet the bridge is started with its
            # child stdout/stderr redirected INTO this same path — measured: the
            # fork's own starter builds $HERMES_HOME/.super-agent/bridge.log, and
            # HERMES_HOME and HOME are set to the same directory. So the console
            # handler and the shell redirect both append to one file while the
            # rotating handler RENAMES it at 1 MB: after the first rotation the
            # redirect keeps writing to the renamed inode, so the active file the
            # uploader sends is missing everything the console said, and the .1
            # backup — which is never uploaded — keeps growing instead.
            #
            # ⭐ THE CONSOLE IS THE HALF TO DROP, because it is the duplicate.
            # Every record it would print is already going to the file through the
            # handler beside it; what the redirect uniquely carries is output that
            # never reaches logging at all — a traceback on the way out — and that
            # is worth keeping.
            console_is_the_log_file = _same_file(console.stream, path)
            if console_is_the_log_file:
                logger.removeHandler(console)
                logger.warning(
                    "console output is redirected into %s — dropping the console "
                    "handler so this file has one writer", path)
        except OSError as e:  # pragma: no cover - disk/permission edge
            logger.warning("could not open log file %s — console only (%s)", path, e)
    return resolved
