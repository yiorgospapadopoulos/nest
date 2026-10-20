"""Which engines Nest has seen signed in, and when first (B94).

The first one decides the model new chats start on when none is chosen: the default
model of the engine the user signed in to first.
"""

from nestd.clock import Clock
from nestd.storage.db import Database

# The names engines are recorded by.
CLAUDE = "claude"
CODEX = "codex"


class SignInStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def record(self, provider: str) -> None:
        """The engine is signed in now; only the first time is kept."""
        await self._db.execute(
            "INSERT INTO engine_sign_ins (provider, first_seen_at) VALUES (?, ?)"
            " ON CONFLICT (provider) DO NOTHING",
            (provider, self._clock.now().isoformat()),
        )

    async def first(self) -> str | None:
        """The engine seen signed in first; None before any was."""
        row = await self._db.fetch_one(
            "SELECT provider FROM engine_sign_ins ORDER BY first_seen_at, provider LIMIT 1"
        )
        return None if row is None else str(row["provider"])
