"""Which Claude Code chats the user archived in harness (D040), never written to Claude Code."""

from harness.clock import Clock
from harness.storage.db import Database


class ChatArchive:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def archived_ids(self) -> set[str]:
        rows = await self._db.fetch_all("SELECT chat_id FROM claude_chat_archive")
        return {row["chat_id"] for row in rows}

    async def set(self, chat_id: str, *, archived: bool) -> None:
        """Idempotent: archiving again keeps the first archive time."""
        if archived:
            await self._db.execute(
                "INSERT OR IGNORE INTO claude_chat_archive (chat_id, archived_at) VALUES (?, ?)",
                (chat_id, self._clock.now().isoformat()),
            )
        else:
            await self._db.execute("DELETE FROM claude_chat_archive WHERE chat_id = ?", (chat_id,))
