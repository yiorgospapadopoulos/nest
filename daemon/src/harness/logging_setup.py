"""Logging to stderr; under launchd, stderr is redirected to the daemon log file."""

import logging
from typing import TextIO

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# httpx and httpcore log every request URL at INFO; web push endpoint URLs are secrets.
QUIET_LOGGERS = ("httpx", "httpcore")


def configure_logging(stream: TextIO, level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=FORMAT, stream=stream, force=True)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
