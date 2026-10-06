"""Event bus: events are persisted, then fanned out to live subscribers.

Ephemeral events (such as token-level text deltas) are fanned out without being stored.
"""

import asyncio
import json
import sqlite3
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import JsonValue

from harness.clock import Clock
from harness.events.models import Event
from harness.storage.db import Database

DEFAULT_QUEUE_SIZE = 1000


class SubscriptionOverflowError(Exception):
    """A subscriber fell too far behind; it should reconnect with `after` set."""


@dataclass(eq=False)
class _Subscriber:
    # None marks overflow: the subscriber has been dropped and must reconnect.
    queue: asyncio.Queue[Event | None] = field(default_factory=asyncio.Queue[Event | None])


class EventBus:
    def __init__(self, db: Database, clock: Clock, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._db = db
        self._clock = clock
        self._queue_size = queue_size
        self._subscribers: set[_Subscriber] = set()
        # Serializes insert plus fan-out so subscribers see events in id order.
        self._publish_lock = asyncio.Lock()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(
        self, event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> Event:
        async with self._publish_lock:
            ts = self._clock.now()
            rows = await self._db.fetch_all(
                "INSERT INTO events (type, ts, session_id, payload) VALUES (?, ?, ?, ?)"
                " RETURNING id",
                (event_type, ts.isoformat(), session_id, json.dumps(payload)),
            )
            event = Event(
                id=rows[0]["id"],
                type=event_type,
                ts=ts,
                session_id=session_id,
                payload=dict(payload),
            )
            for subscriber in list(self._subscribers):
                self._deliver(subscriber, event)
        return event

    async def publish_ephemeral(
        self, event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> Event:
        async with self._publish_lock:
            event = Event(
                id=None,
                type=event_type,
                ts=self._clock.now(),
                session_id=session_id,
                payload=dict(payload),
            )
            for subscriber in list(self._subscribers):
                self._deliver(subscriber, event)
        return event

    async def session_events(self, session_id: str, after_id: int = 0) -> list[Event]:
        """One session's persisted events with id > after_id, oldest first."""
        rows = await self._db.fetch_all(
            "SELECT id, type, ts, session_id, payload FROM events"
            " WHERE session_id = ? AND id > ? ORDER BY id",
            (session_id, after_id),
        )
        return [_from_row(row) for row in rows]

    async def subscribe(self, after_id: int | None = None) -> AsyncGenerator[Event]:
        """Yield persisted events with id > after_id (none if None), then live events."""
        subscriber = _Subscriber()
        # Register before reading the backlog so nothing published in between is missed;
        # anything seen twice is dropped by the id check below.
        self._subscribers.add(subscriber)
        try:
            last_id = after_id or 0
            if after_id is not None:
                for row in await self._backlog(after_id):
                    yield _from_row(row)
                    last_id = row["id"]
            while True:
                event = await subscriber.queue.get()
                if event is None:
                    msg = "subscriber fell behind; reconnect with after set to the last event id"
                    raise SubscriptionOverflowError(msg)
                if event.id is None:
                    yield event
                elif event.id > last_id:
                    yield event
                    last_id = event.id
        finally:
            self._subscribers.discard(subscriber)

    def _deliver(self, subscriber: _Subscriber, event: Event) -> None:
        if subscriber.queue.qsize() >= self._queue_size:
            self._subscribers.discard(subscriber)
            subscriber.queue.put_nowait(None)
        else:
            subscriber.queue.put_nowait(event)

    async def _backlog(self, after_id: int) -> list[sqlite3.Row]:
        return await self._db.fetch_all(
            "SELECT id, type, ts, session_id, payload FROM events WHERE id > ? ORDER BY id",
            (after_id,),
        )


def _from_row(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        type=row["type"],
        ts=datetime.fromisoformat(row["ts"]),
        session_id=row["session_id"],
        payload=json.loads(row["payload"]),
    )
