"""Daemon (C15): how long it took to start, its memory, what it keeps on disk, and its
slowest routes since it started."""

import asyncio
import os
import sqlite3
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

from nestd.perf.formatting import duration, size
from nestd.perf.models import Collected, Measured, Part
from nestd.perf.store import DaemonStart
from nestd.perf.timing import RouteTimings
from nestd.storage.db import Database

LARGEST_TABLES = 5
SLOWEST_ROUTES = 5
# `du` over worktrees with their dependencies can take long; it gives up after this.
DU_SECONDS = 30.0

# Folders whose disk use is measured, read at each run: they change as chats come and go.
type Folders = Callable[[], Iterable[Path]]


class Daemon:
    def __init__(
        self,
        db: Database,
        db_path: Path,
        attachments: Path,
        worktrees: Folders,
        latest_start: Callable[[], Awaitable[DaemonStart | None]],
        timings: RouteTimings,
    ) -> None:
        self._db = db
        self._db_path = db_path
        self._attachments = attachments
        self._worktrees = worktrees
        self._latest_start = latest_start
        self._timings = timings

    async def __call__(self) -> Collected:
        start = await self._latest_start()
        worktrees = [path for path in self._worktrees() if path.is_dir()]
        metrics = [
            Measured(
                id="startup",
                label="Startup",
                unit="ms",
                better="lower",
                value=None if start is None else start.ready_ms,
            ),
            Measured(
                id="memory",
                label="Memory",
                unit="bytes",
                better="lower",
                value=await resident_bytes(os.getpid()),
            ),
            Measured(
                id="database",
                label="Database",
                unit="bytes",
                better="lower",
                value=_files_size(self._db_path, Path(f"{self._db_path}-wal")),
                parts=await self._largest_tables(),
            ),
            Measured(
                id="attachments",
                label="Attachments",
                unit="bytes",
                better="lower",
                value=await disk_use([self._attachments]) if self._attachments.is_dir() else 0,
            ),
            Measured(
                id="worktrees",
                label="Nest worktrees",
                unit="bytes",
                better="lower",
                value=await disk_use(worktrees) if worktrees else 0,
                sub=f"{len(worktrees)} {'worktree' if len(worktrees) == 1 else 'worktrees'}",
            ),
        ]
        for timing in self._timings.slowest(SLOWEST_ROUTES):
            metrics.append(
                Measured(
                    id=f"route:{timing.route}",
                    label=timing.route,
                    unit="ms",
                    better="lower",
                    value=timing.median_ms,
                    sub=f"{timing.count} {'call' if timing.count == 1 else 'calls'},"
                    f" slowest {duration(timing.slowest_ms)}, {size(timing.bytes)} sent",
                )
            )
        return Collected(metrics=metrics)

    async def _largest_tables(self) -> list[Part] | None:
        """Tables with their indexes, by the pages they use; None without SQLite's dbstat."""
        try:
            rows = await self._db.fetch_all(
                "SELECT s.tbl_name AS name, SUM(d.pgsize) AS bytes FROM dbstat d"
                " JOIN sqlite_schema s ON s.name = d.name GROUP BY s.tbl_name"
                " ORDER BY bytes DESC LIMIT ?",
                (LARGEST_TABLES,),
            )
        except sqlite3.OperationalError:
            return None
        return [Part(label=row["name"], value=row["bytes"]) for row in rows]


def _files_size(*paths: Path) -> float:
    return float(sum(path.stat().st_size for path in paths if path.exists()))


async def resident_bytes(pid: int) -> float | None:
    """The process's resident memory, from `ps`; None when it cannot be read."""
    output = await _run("ps", "-o", "rss=", "-p", str(pid))
    try:
        return int(output.strip()) * 1024 if output is not None else None
    except ValueError:
        return None


async def disk_use(paths: Iterable[Path]) -> float | None:
    """What the folders use on disk, from `du`; None when it fails or takes too long."""
    output = await _run("du", "-sk", *(str(path) for path in paths))
    if output is None:
        return None
    total = 0
    for line in output.splitlines():
        kilobytes, _, _ = line.partition("\t")
        if kilobytes.strip().isdigit():
            total += int(kilobytes)
    return float(total * 1024)


async def _run(*command: str) -> str | None:
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
    except OSError:
        return None
    try:
        async with asyncio.timeout(DU_SECONDS):
            stdout, _ = await process.communicate()
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    # `du` names folders it could not read but still counts the rest.
    return stdout.decode(errors="replace")
