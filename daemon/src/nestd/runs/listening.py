"""Which TCP ports a run's processes listen on, as lsof sees them (B108)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

LSOF = Path("/usr/sbin/lsof")
LSOF_TIMEOUT_SECONDS = 10.0

logger = logging.getLogger(__name__)

# The ports the processes of a process group listen on, ascending.
type PortProbe = Callable[[int], Awaitable[list[int]]]


async def listening_ports(
    group: int, lsof: Path = LSOF, time_limit: float = LSOF_TIMEOUT_SECONDS
) -> list[int]:
    """The TCP ports process group `group` listens on. lsof failing counts as none: it
    exits 1 when nothing matches, and its output is read whatever it exits with.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            str(lsof),
            "-nP",
            "-a",
            "-g",
            str(group),
            "-iTCP",
            "-sTCP:LISTEN",
            "-Fn",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as error:
        logger.warning("could not run lsof (%s)", error)
        return []
    try:
        output, _ = await asyncio.wait_for(process.communicate(), time_limit)
    except TimeoutError:
        process.kill()
        await process.wait()
        logger.warning("lsof took longer than %ss", time_limit)
        return []
    return parse_ports(output.decode(errors="replace"))


def parse_ports(output: str) -> list[int]:
    """The ports of lsof's `-Fn` name lines, such as `n*:41020`, `n127.0.0.1:41020` or
    `n[::1]:41020`: unique, ascending.
    """
    ports: set[int] = set()
    for line in output.splitlines():
        if not line.startswith("n"):
            continue
        _, _, port = line.rpartition(":")
        if port.isdigit():
            ports.add(int(port))
    return sorted(ports)
