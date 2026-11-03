"""Which TCP ports a run's processes listen on, as lsof sees them (B108), or on Linux
without lsof as /proc shows them (B117)."""

import asyncio
import logging
import shutil
from collections.abc import Awaitable, Callable, Iterator
from functools import partial
from pathlib import Path

from nestd.platform import Platform

LSOF = Path("/usr/sbin/lsof")
LSOF_TIMEOUT_SECONDS = 10.0
PROC = Path("/proc")
# The `st` column of /proc/net/tcp for a listening socket.
_TCP_LISTEN = "0A"

logger = logging.getLogger(__name__)

# The ports the processes of a process group listen on, ascending.
type PortProbe = Callable[[int], Awaitable[list[int]]]
type Which = Callable[..., str | None]


def port_probe(platform: Platform, search_path: str, which: Which = shutil.which) -> PortProbe:
    """lsof where macOS keeps it; on Linux the lsof on `search_path` (Ubuntu's is in
    /usr/bin), else /proc."""
    match platform.name:
        case "macos":
            return listening_ports
        case "linux":
            found = which("lsof", path=search_path)
            return partial(listening_ports, lsof=Path(found)) if found else proc_listening_ports


async def proc_listening_ports(group: int, proc: Path = PROC) -> list[int]:
    """The TCP ports process group `group` listens on, from /proc: its processes'
    socket inodes matched against the listening sockets in /proc/net/tcp and tcp6."""
    return await asyncio.to_thread(_proc_ports, group, proc)


def _proc_ports(group: int, proc: Path) -> list[int]:
    inodes = {inode for pid in _group_pids(group, proc) for inode in _socket_inodes(proc / pid)}
    ports: set[int] = set()
    for table in ("tcp", "tcp6"):
        try:
            lines = (proc / "net" / table).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) > 9 and fields[3] == _TCP_LISTEN and fields[9] in inodes:
                ports.add(int(fields[1].rpartition(":")[2], 16))
    return sorted(ports)


def _group_pids(group: int, proc: Path) -> Iterator[str]:
    try:
        entries = list(proc.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
        except OSError:
            continue
        # After the name, which may hold spaces and parentheses: state, parent, group.
        fields = stat.rpartition(")")[2].split()
        if len(fields) > 2 and fields[2] == str(group):
            yield entry.name


def _socket_inodes(process: Path) -> Iterator[str]:
    try:
        fds = list((process / "fd").iterdir())
    except OSError:
        return
    for fd in fds:
        try:
            target = str(fd.readlink())
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            yield target[len("socket:[") : -1]


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
