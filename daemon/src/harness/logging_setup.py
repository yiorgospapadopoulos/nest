"""Logging to stderr; under launchd, stderr is redirected to the daemon log file."""

import logging
from typing import TextIO

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# httpx and httpcore log every request URL at INFO; web push endpoint URLs are secrets.
QUIET_LOGGERS = ("httpx", "httpcore")
# What Claude Code writes to stderr (MCP, hook and CLI warnings), logged at debug level and
# kept in the daemon log while the rest logs at `level` (BUG-82).
ENGINE_STDERR_LOGGER = "harness.engine_stderr"


def configure_logging(stream: TextIO, level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=FORMAT, stream=stream, force=True)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger(ENGINE_STDERR_LOGGER).setLevel(logging.DEBUG)
