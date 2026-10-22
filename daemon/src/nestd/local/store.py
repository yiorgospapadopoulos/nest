"""Local servers, their models, local usage and the local settings, in SQLite (B106)."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row

from pydantic import JsonValue

from nestd.local.models import ToolsRating
from nestd.storage.db import Database

_SERVER = "id, address, base_url, app, has_messages, has_responses, has_chat, has_key, checked_at"
_MODEL = (
    "id, server_id, model, name, context, tools, weak_reason, vision, thinking, size_bytes,"
    " position, added_at"
)


@dataclass(frozen=True)
class StoredServer:
    id: str
    address: str
    base_url: str
    app: str | None
    has_messages: bool
    has_responses: bool
    has_chat: bool
    has_key: bool
    checked_at: datetime


@dataclass(frozen=True)
class StoredModel:
    id: str
    server_id: str
    model: str
    name: str
    context: int | None
    tools: ToolsRating
    weak_reason: str | None
    vision: bool
    thinking: bool
    # Bytes on disk, when the server said.
    size: int | None
    position: int
    added_at: datetime


def server_id(address: str) -> str:
    return "ls_" + _hash(address)


def model_id(server: str, model: str) -> str:
    """Stable for the server and model, so re-adding one keeps chats that name it."""
    return "lm_" + _hash(f"{server}\0{model}")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


class LocalStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def servers(self) -> list[StoredServer]:
        rows = await self._db.fetch_all(
            f"SELECT {_SERVER} FROM local_servers ORDER BY address"  # noqa: S608
        )
        return [_server(row) for row in rows]

    async def server(self, server: str) -> StoredServer | None:
        row = await self._db.fetch_one(
            f"SELECT {_SERVER} FROM local_servers WHERE id = ?",  # noqa: S608
            (server,),
        )
        return None if row is None else _server(row)

    async def save_server(self, server: StoredServer) -> None:
        """Added, or updated with what it answered now."""
        await self._db.execute(
            f"INSERT INTO local_servers ({_SERVER}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"  # noqa: S608
            " ON CONFLICT (id) DO UPDATE SET base_url = excluded.base_url, app = excluded.app,"
            " has_messages = excluded.has_messages, has_responses = excluded.has_responses,"
            " has_chat = excluded.has_chat, has_key = excluded.has_key,"
            " checked_at = excluded.checked_at",
            (
                server.id,
                server.address,
                server.base_url,
                server.app,
                int(server.has_messages),
                int(server.has_responses),
                int(server.has_chat),
                int(server.has_key),
                server.checked_at.isoformat(),
            ),
        )

    async def remove_server(self, server: str) -> None:
        """Its models go with it."""
        await self._db.execute("DELETE FROM local_servers WHERE id = ?", (server,))

    async def models(self) -> list[StoredModel]:
        """In the order they were added."""
        rows = await self._db.fetch_all(
            f"SELECT {_MODEL} FROM local_models ORDER BY position"  # noqa: S608
        )
        return [_model(row) for row in rows]

    async def model(self, model: str) -> StoredModel | None:
        row = await self._db.fetch_one(
            f"SELECT {_MODEL} FROM local_models WHERE id = ?",  # noqa: S608
            (model,),
        )
        return None if row is None else _model(row)

    async def add_model(self, model: StoredModel) -> None:
        """Last in order; one already added stays as it is."""
        await self._db.execute(
            f"INSERT INTO local_models ({_MODEL})"  # noqa: S608
            " SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, coalesce(max(position), -1) + 1, ?"
            " FROM local_models WHERE true ON CONFLICT (id) DO NOTHING",
            (
                model.id,
                model.server_id,
                model.model,
                model.name,
                model.context,
                model.tools,
                model.weak_reason,
                int(model.vision),
                int(model.thinking),
                model.size,
                model.added_at.isoformat(),
            ),
        )

    async def remove_model(self, model: str) -> None:
        await self._db.execute("DELETE FROM local_models WHERE id = ?", (model,))

    async def add_usage(self, day: str, model: str, input_tokens: int, output_tokens: int) -> None:
        await self._db.execute(
            "INSERT INTO local_usage (day, model_id, input_tokens, output_tokens)"
            " VALUES (?, ?, ?, ?) ON CONFLICT (day, model_id) DO UPDATE SET"
            " input_tokens = input_tokens + excluded.input_tokens,"
            " output_tokens = output_tokens + excluded.output_tokens",
            (day, model, input_tokens, output_tokens),
        )

    async def usage(self, day: str) -> list[tuple[str, int, int]]:
        """Each model's (id, input, output) tokens on `day`."""
        rows = await self._db.fetch_all(
            "SELECT model_id, input_tokens, output_tokens FROM local_usage WHERE day = ?"
            " ORDER BY model_id",
            (day,),
        )
        return [(row["model_id"], row["input_tokens"], row["output_tokens"]) for row in rows]

    async def setting(self, key: str) -> JsonValue | None:
        row = await self._db.fetch_one("SELECT value FROM local_settings WHERE key = ?", (key,))
        if row is None:
            return None
        value: JsonValue = json.loads(row["value"])
        return value

    async def set_setting(self, key: str, value: JsonValue) -> None:
        await self._db.execute(
            "INSERT INTO local_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


def _server(row: Row) -> StoredServer:
    return StoredServer(
        id=row["id"],
        address=row["address"],
        base_url=row["base_url"],
        app=row["app"],
        has_messages=bool(row["has_messages"]),
        has_responses=bool(row["has_responses"]),
        has_chat=bool(row["has_chat"]),
        has_key=bool(row["has_key"]),
        checked_at=datetime.fromisoformat(row["checked_at"]),
    )


def _model(row: Row) -> StoredModel:
    return StoredModel(
        id=row["id"],
        server_id=row["server_id"],
        model=row["model"],
        name=row["name"],
        context=row["context"],
        tools=row["tools"],
        weak_reason=row["weak_reason"],
        vision=bool(row["vision"]),
        thinking=bool(row["thinking"]),
        size=row["size_bytes"],
        position=row["position"],
        added_at=datetime.fromisoformat(row["added_at"]),
    )
