"""Messages sent while a turn runs, stored in order (D032). One the agent can read in the
running turn is written into it and marked sent until the agent echoes it; the others
start the next turns, one per turn (B59).

Every change publishes `session.queued` with the session's whole queue, oldest first.
"""

import json
import sqlite3
from uuid import uuid4

from pydantic import JsonValue

from nestd.attachments.store import Attachment
from nestd.clock import Clock
from nestd.errors import NotFoundError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.sessions.models import USER, AttachmentSummary, QueuedMessage, Sender
from nestd.storage.db import Database

_SELECT = "SELECT id, text, attachments, created_at, from_pixie, origin, sent FROM queued_messages"
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
        self,
        session_id: str,
        text: str,
        attachments: list[Attachment],
        urgent: bool = False,
        sender: Sender = USER,
        sent: bool = False,
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
            from_pixie=sender.from_pixie,
            origin=sender.origin,
            sent=sent,
        )
        await self._db.execute(
            "INSERT INTO queued_messages"
            " (id, session_id, text, attachments, created_at, urgent, from_pixie, origin, sent)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message.id,
                session_id,
                message.text,
                json.dumps([a.model_dump() for a in message.attachments]),
                message.created_at.isoformat(),
                urgent,
                sender.from_pixie,
                sender.origin,
                sent,
            ),
        )
        await self._announce(session_id)
        return message

    async def get(self, session_id: str, message_id: str) -> QueuedMessage:
        row = await self._db.fetch_one(
            f"{_SELECT} WHERE id = ? AND session_id = ?", (message_id, session_id)
        )
        if row is None:
            raise _not_found(session_id, message_id)
        return _message(row)

    async def waiting(self, session_id: str) -> list[QueuedMessage]:
        """The messages not sent into a turn, in the order they start turns."""
        rows = await self._db.fetch_all(
            f"{_SELECT} WHERE session_id = ? AND sent = 0{_ORDER}", (session_id,)
        )
        return [_message(row) for row in rows]

    async def sent_ids(self, session_id: str) -> list[str]:
        rows = await self._db.fetch_all(
            "SELECT id FROM queued_messages WHERE session_id = ? AND sent = 1"
            " ORDER BY created_at, rowid",
            (session_id,),
        )
        return [row["id"] for row in rows]

    async def mark_sent(self, session_id: str, message_ids: list[str], sent: bool) -> None:
        changed = 0
        for message_id in message_ids:
            changed += await self._db.execute(
                "UPDATE queued_messages SET sent = ? WHERE id = ? AND session_id = ? AND sent = ?",
                (sent, message_id, session_id, not sent),
            )
        if changed:
            await self._announce(session_id)

    async def unsend_all(self, session_id: str | None = None) -> None:
        """The agent that had the session's sent messages (or every session's: None) is
        gone without reading them; they wait for a turn again.
        """
        rows = await self._db.fetch_all(
            "UPDATE queued_messages SET sent = 0 WHERE sent = 1 AND (? IS NULL OR session_id = ?)"
            " RETURNING session_id",
            (session_id, session_id),
        )
        for changed in sorted({row["session_id"] for row in rows}):
            await self._announce(changed)

    async def make_urgent(self, session_id: str, message_id: str) -> None:
        """The message goes first: the user chose Send now (B59)."""
        updated = await self._db.execute(
            "UPDATE queued_messages SET urgent = 1 WHERE id = ? AND session_id = ?",
            (message_id, session_id),
        )
        if not updated:
            raise _not_found(session_id, message_id)
        await self._announce(session_id)

    async def take(self, session_id: str, message_id: str) -> QueuedMessage | None:
        """Remove the message the agent read in the running turn; None if it is gone."""
        async with self._db.transaction() as tx:
            row = await tx.fetch_one(
                f"{_SELECT} WHERE id = ? AND session_id = ?", (message_id, session_id)
            )
            if row is None:
                return None
            await tx.execute("DELETE FROM queued_messages WHERE id = ?", (message_id,))
        await self._announce(session_id)
        return _message(row)

    async def pop(self, session_id: str) -> QueuedMessage | None:
        """Take the first message waiting for a turn off the queue, if there is one."""
        async with self._db.transaction() as tx:
            row = await tx.fetch_one(
                f"{_SELECT} WHERE session_id = ? AND sent = 0{_ORDER} LIMIT 1", (session_id,)
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
            raise _not_found(session_id, message_id)
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


def _not_found(session_id: str, message_id: str) -> QueuedMessageNotFoundError:
    return QueuedMessageNotFoundError(f"no queued message {message_id!r} in session {session_id!r}")


def _message(row: sqlite3.Row) -> QueuedMessage:
    data = dict(row)
    data["attachments"] = json.loads(data["attachments"])
    return QueuedMessage.model_validate(data)
