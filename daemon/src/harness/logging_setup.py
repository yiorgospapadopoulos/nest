"""Logging to stderr; under launchd, stderr is redirected to the daemon log file."""

import logging
from typing import TextIO

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(stream: TextIO, level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=FORMAT, stream=stream, force=True)
