"""Port blocks: each folder a chat works in keeps its own ports for its life (B108)."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from nestd.clock import Clock
from nestd.config.models import PortSettings
from nestd.storage.db import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PortBlock:
    start: int
    size: int

    @property
    def end(self) -> int:
        return self.start + self.size - 1

    def env(self) -> dict[str, str]:
        """`NEST_PORT` is the first port, `NEST_PORT_1` and on the next ones."""
        names = ["NEST_PORT", *(f"NEST_PORT_{offset}" for offset in range(1, self.size))]
        return {name: str(self.start + offset) for offset, name in enumerate(names)}


class PortBlocks:
    def __init__(self, db: Database, clock: Clock, settings: Callable[[], PortSettings]) -> None:
        """`settings` is read at each use, so a change applies to the next block given."""
        self._db = db
        self._clock = clock
        self._settings = settings

    async def block_for(self, folder: str, repo: str) -> PortBlock | None:
        """The folder's block, given the first time it is asked for: the lowest free one.
        A block that no longer fits the settings is given again. None when every block is
        taken: the folder works without ports.
        """
        settings = self._settings()
        async with self._db.transaction() as tx:
            row = await tx.fetch_one("SELECT block FROM port_blocks WHERE folder = ?", (folder,))
            if row is not None and row["block"] < settings.blocks:
                return _block(settings, row["block"])
            await tx.execute("DELETE FROM port_blocks WHERE folder = ?", (folder,))
            rows = await tx.fetch_all("SELECT block FROM port_blocks")
            taken = {taken_row["block"] for taken_row in rows}
            free = next((index for index in range(settings.blocks) if index not in taken), None)
            if free is None:
                logger.warning("no free port block for %s: all %d are taken", folder, len(taken))
                return None
            await tx.execute(
                "INSERT INTO port_blocks (folder, repo, block, created_at) VALUES (?, ?, ?, ?)",
                (folder, repo, free, self._clock.now().isoformat()),
            )
        return _block(settings, free)

    async def free(self, folder: str) -> None:
        await self._db.execute("DELETE FROM port_blocks WHERE folder = ?", (folder,))

    async def folders(self, repo: str) -> list[str]:
        """The folders of `repo` that hold a block."""
        rows = await self._db.fetch_all(
            "SELECT folder FROM port_blocks WHERE repo = ? ORDER BY folder", (repo,)
        )
        return [row["folder"] for row in rows]

    async def free_repo(self, repo: str) -> None:
        await self._db.execute("DELETE FROM port_blocks WHERE repo = ?", (repo,))


def _block(settings: PortSettings, index: int) -> PortBlock:
    return PortBlock(start=settings.start + index * settings.size, size=settings.size)
