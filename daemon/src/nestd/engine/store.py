"""The engine's last reported model list and account, kept in SQLite (D038)."""

from datetime import datetime

from pydantic import TypeAdapter

from nestd.clock import Clock
from nestd.engine.models import ModelList
from nestd.providers.base import AccountInfo, EngineDetails, ModelOption
from nestd.storage.db import Database

_MODELS = TypeAdapter(list[ModelOption])


class EngineInfoStore:
    def __init__(self, db: Database, clock: Clock, prefix: str = "") -> None:
        """`prefix` keeps another engine's parts apart, such as Codex's (B91)."""
        self._db = db
        self._clock = clock
        self._models = f"{prefix}models"
        self._account = f"{prefix}account"

    async def save(self, details: EngineDetails) -> None:
        """Replace each part the engine reported; a part it left out keeps its last value."""
        now = self._clock.now().isoformat()
        parts: list[tuple[str, str]] = []
        if details.models is not None:
            parts.append((self._models, _MODELS.dump_json(details.models).decode()))
        if details.account is not None:
            parts.append((self._account, details.account.model_dump_json()))
        async with self._db.transaction() as tx:
            for name, data in parts:
                await tx.execute(
                    "INSERT INTO engine_info (name, data, updated_at) VALUES (?, ?, ?)"
                    " ON CONFLICT (name) DO UPDATE SET"
                    " data = excluded.data, updated_at = excluded.updated_at",
                    (name, data, now),
                )

    async def models(self) -> ModelList | None:
        row = await self._db.fetch_one(
            "SELECT data, updated_at FROM engine_info WHERE name = ?", (self._models,)
        )
        if row is None:
            return None
        return ModelList(
            models=_MODELS.validate_json(row["data"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def account(self) -> AccountInfo | None:
        row = await self._db.fetch_one(
            "SELECT data FROM engine_info WHERE name = ?", (self._account,)
        )
        return None if row is None else AccountInfo.model_validate_json(row["data"])
