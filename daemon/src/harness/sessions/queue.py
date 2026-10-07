"""Messages sent while a turn runs, stored in order and delivered one per turn (D032).

Every change publishes `session.queued` with the session's whole queue, oldest first.
"""

import json
import sqlite3
from uuid import uuid4

from pydantic import JsonValue

from harness.attachments.store import Attachment
from harness.clock import Clock
from harness.errors import NotFoundError
from harness.events import types
from harness.events.bus import EventBus
from harness.sessions.models import AttachmentSummary, QueuedMessage
from harness.storage.db import Database

_SELECT = "SELECT id, text, attachments, created_at FROM queued_messages"
# Urgent messages (they interrupted the turn) first, then oldest first.
_ORDER = " ORDER BY urgent DESC, created_at, rowid"


class QueuedMessageNotFoundError(NotFoundError):
    pass


class MessageQueue:
    def __init__(self, db: Database, clock: Clock, bus: EventBus) -> None:
        self._db = db
        self._clock = clock
        self._bus = bus

    async def messages(self, session_id: str) -> list[QueuedMessage]:
        rows = await self._db.fetch_all(f"{_SELECT} WHERE session_id = ?{_ORDER}", (session_id,))
        return [_message(row) for row in rows]

    async def add(
        self, session_id: str, text: str, attachments: list[Attachment], urgent: bool = False
    ) -> QueuedMessage:
        message = QueuedMessage(
            id=uuid4().hex,
            text=text,
            attachments=[
                AttachmentSummary(
                    id=a.id, filename=a.filename, media_type=a.media_type, size=a.size
                )
                for a in attachments
            ],
            created_at=self._clock.now(),
        )
        await self._db.execute(
            "INSERT INTO queued_messages (id, session_id, text, attachments, created_at, urgent)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                message.id,
                session_id,
                message.text,
                json.dumps([a.model_dump() for a in message.attachments]),
                message.created_at.isoformat(),
                urgent,
            ),
        )
        await self._announce(session_id)
        return message

    async def pop(self, session_id: str) -> QueuedMessage | None:
        """Take the oldest message off the queue, if there is one."""
        async with self._db.transaction() as tx:
            row = await tx.fetch_one(
                f"{_SELECT} WHERE session_id = ?{_ORDER} LIMIT 1", (session_id,)
            )
            if row is None:
                return None
            await tx.execute("DELETE FROM queued_messages WHERE id = ?", (row["id"],))
        await self._announce(session_id)
        return _message(row)

    async def cancel(self, session_id: str, message_id: str) -> None:
        removed = await self._db.execute(
            "DELETE FROM queued_messages WHERE id = ? AND session_id = ?", (message_id, session_id)
        )
        if not removed:
            msg = f"no queued message {message_id!r} in session {session_id!r}"
            raise QueuedMessageNotFoundError(msg)
        await self._announce(session_id)

    async def clear(self, session_id: str) -> None:
        removed = await self._db.execute(
            "DELETE FROM queued_messages WHERE session_id = ?", (session_id,)
        )
        if removed:
            await self._announce(session_id)

    async def _announce(self, session_id: str) -> None:
        queued: list[JsonValue] = [
            message.model_dump(mode="json") for message in await self.messages(session_id)
        ]
        await self._bus.publish(types.SESSION_QUEUED, {"queued": queued}, session_id)


def _message(row: sqlite3.Row) -> QueuedMessage:
    data = dict(row)
    data["attachments"] = json.loads(data["attachments"])
    return QueuedMessage.model_validate(data)
