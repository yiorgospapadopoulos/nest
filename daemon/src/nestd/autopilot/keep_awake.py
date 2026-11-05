"""Keeps the machine from going to sleep while a run is on (a closed MacBook still sleeps).

The helper is the system's own tool and watches the daemon, so it ends with it however the
daemon ends. Autopilot goes on without it: a machine that sleeps only pauses the run.
"""

import asyncio
import logging
import os
import shutil
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress

from nestd.platform.base import PlatformName

logger = logging.getLogger(__name__)

type Spawn = Callable[[Sequence[str]], Awaitable[asyncio.subprocess.Process]]


def command(platform: PlatformName, pid: int) -> list[str]:
    if platform == "macos":
        return ["caffeinate", "-i", "-w", str(pid)]
    return [
        "systemd-inhibit",
        "--what=idle:sleep",
        "--who=Nest",
        "--why=Autopilot is on",
        "--mode=block",
        "tail",
        f"--pid={pid}",
        "-f",
        "/dev/null",
    ]


async def _spawn(argv: Sequence[str]) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


class KeepAwake:
    def __init__(self, platform: PlatformName, spawn: Spawn = _spawn) -> None:
        self._platform: PlatformName = platform
        self._spawn = spawn
        self._process: asyncio.subprocess.Process | None = None

    async def hold(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        argv = command(self._platform, os.getpid())
        if shutil.which(argv[0]) is None:
            logger.warning("%s is not installed, so the machine may sleep", argv[0])
            return
        try:
            self._process = await self._spawn(argv)
        except OSError as error:
            logger.warning("keeping the machine awake failed (%s)", type(error).__name__)

    async def release(self) -> None:
        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return
        with suppress(ProcessLookupError):
            process.terminate()
        await process.wait()
