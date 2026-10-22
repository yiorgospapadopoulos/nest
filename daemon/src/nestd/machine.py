"""The daemon machine's name for people, which clients on other machines show (B105)."""

import socket
import sys
from collections.abc import Callable
from pathlib import Path

from nestd.gitops.runner import CommandError, CommandRunner, run_command


async def machine_name(
    run: CommandRunner = run_command,
    *,
    platform: str = sys.platform,
    hostname: Callable[[], str] = socket.gethostname,
) -> str:
    """macOS's computer name (as in Sharing settings), otherwise the host name without
    a trailing `.local`."""
    if platform == "darwin":
        try:
            name = (await run(["scutil", "--get", "ComputerName"], Path("/"))).strip()
        except (CommandError, OSError):
            name = ""
        if name:
            return name
    return hostname().removesuffix(".local")
