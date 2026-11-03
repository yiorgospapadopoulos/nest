"""Ending the daemon so its service starts it again (launchd's KeepAlive, systemd's
Restart=always)."""

import os
import signal
from collections.abc import Callable

type Restarter = Callable[[], None]


def terminate_self(kill: Callable[[int, int], None] = os.kill) -> None:
    """Send SIGTERM to this process: uvicorn shuts down as when the service is stopped,
    so the lifespan's shutdown marks in-flight turns interrupted, then the process exits."""
    kill(os.getpid(), signal.SIGTERM)
