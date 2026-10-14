"""Event bus: events are persisted, then fanned out to live subscribers.

Ephemeral events (such as token-level text deltas) are fanned out without being stored.
"""

import asyncio
import json
import sqlite3
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import JsonValue

from nestd.clock import Clock
from nestd.events.models import Event
from nestd.storage.db import Database

DEFAULT_QUEUE_SIZE = 1000
# A subscriber's backlog is read this many events at a time (IMP-13).
DEFAULT_BACKLOG_PAGE = 500
# `publish_many` stores this many events per transaction, then fans them out, so live
# subscribers can keep up between batches (I-K).
DEFAULT_BATCH_SIZE = 200
_INSERT = "INSERT INTO events (type, ts, session_id, payload) VALUES (?, ?, ?, ?) RETURNING id"
_SESSION_EVENTS = (
    "SELECT id, type, ts, session_id, payload FROM events"
    " WHERE session_id = ? AND id > ? AND (? IS NULL OR id < ?) ORDER BY id LIMIT ?"
)
_SESSION_EVENTS_DESC = _SESSION_EVENTS.replace("ORDER BY id", "ORDER BY id DESC")


class SubscriptionOverflowError(Exception):
    """A subscriber fell too far behind; it should reconnect with `after` set."""


@dataclass(eq=False)
class _Subscriber:
    # None marks overflow: the subscriber has been dropped and must reconnect.
    queue: asyncio.Queue[Event | None] = field(default_factory=asyncio.Queue[Event | None])


class EventBus:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        backlog_page: int = DEFAULT_BACKLOG_PAGE,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._db = db
        self._clock = clock
        self._queue_size = queue_size
        self._backlog_page = backlog_page
        self._batch_size = batch_size
        self._subscribers: set[_Subscriber] = set()
        # Serializes insert plus fan-out so subscribers see events in id order.
        self._publish_lock = asyncio.Lock()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(
        self, event_type: str, payload: Mapping[str, JsonValue], session_id: str | None = None
    ) -> Event:
        # The database finishes a write even if this caller is cancelled meanwhile, so the
        # event is fanned out too: live subscribers see everything stored, in order.
        return await asyncio.shield(self._publish(event_type, payload, session_id))

    async def _publish(
        self, event_type: str, payload: Mapping[str, JsonValue], session_id: str | None
    ) -> Event:
        async with self._publish_lock:
            ts = self._clock.now()
            rows = await self._db.fetch_all(
                _INSERT, (event_type, ts.isoformat(), session_id, json.dumps(payload))
            )
            event = Event(
                id=rows[0]["id"],
                type=event_type,
                ts=ts,
                session_id=session_id,
                payload=dict(payload),
            )
            self._fan_out([event])
        return event

    async def publish_many(
        self, events: Sequence[tuple[str, Mapping[str, JsonValue]]], session_id: str | None
    ) -> list[Event]:
        """Publish `events` in order, a batch per transaction; nothing published meanwhile
        lands between them (I-K). Cancelling the caller stops nothing already started.
        """
        return await asyncio.shield(self._publish_many(events, session_id))

    async def _publish_many(
        self, events: Sequence[tuple[str, Mapping[str, JsonValue]]], session_id: str | None
    ) -> list[Event]:
        published: list[Event] = []
        async with self._publish_lock:
            for start in range(0, len(events), self._batch_size):
                batch = events[start : start + self._batch_size]
                published += await self._store_and_deliver(batch, session_id)
        return published

    async def _store_and_deliver(
        self, events: Sequence[tuple[str, Mapping[str, JsonValue]]], session_id: str | None
    ) -> list[Event]:
        """Store `events` in one transaction, then fan them out."""
        ts = self._clock.now()
        stored: list[Event] = []
        async with self._db.transaction() as tx:
            for event_type, payload in events:
                rows = await tx.fetch_all(
                    _INSERT, (event_type, ts.isoformat(), session_id, json.dumps(payload))
                )
                stored.append(
                    Event(
                        id=rows[0]["id"],
                        type=event_type,
                        ts=ts,
                        session_id=session_id,
                        payload=dict(payload),
                    )
                )
        self._fan_out(stored)
        return stored

    def _fan_out(self, events: list[Event]) -> None:
        for event in events:
            for subscriber in list(self._subscribers):
                self._deliver(subscriber, event)

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

    async def last_id(self) -> int:
        """The id of the newest stored event, 0 if there is none."""
        rows = await self._db.fetch_all("SELECT COALESCE(MAX(id), 0) AS id FROM events")
        return rows[0]["id"]

    async def latest_id(self, session_id: str, event_type: str) -> int | None:
        """The id of the session's newest stored event of `event_type`, if any."""
        rows = await self._db.fetch_all(
            "SELECT MAX(id) AS id FROM events WHERE session_id = ? AND type = ?",
            (session_id, event_type),
        )
        return rows[0]["id"]

    async def session_events(
        self,
        session_id: str,
        after_id: int = 0,
        before_id: int | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        """One session's persisted events with after_id < id < before_id, oldest first.

        With a limit, the events nearest `before_id` when it is set, else nearest `after_id`.
        """
        newest_first = before_id is not None and limit is not None
        rows = await self._db.fetch_all(
            _SESSION_EVENTS_DESC if newest_first else _SESSION_EVENTS,
            (session_id, after_id, before_id, before_id, -1 if limit is None else limit),
        )
        events = [_from_row(row) for row in rows]
        return events[::-1] if newest_first else events

    async def latest_of_each_session(self, event_type: str) -> list[Event]:
        """The newest stored event of `event_type` of each session that has one."""
        rows = await self._db.fetch_all(
            "SELECT id, type, ts, session_id, payload FROM events WHERE id IN"
            " (SELECT MAX(id) FROM events WHERE type = ? AND session_id IS NOT NULL"
            " GROUP BY session_id) ORDER BY id",
            (event_type,),
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
                while True:
                    rows = await self._backlog(last_id)
                    for row in rows:
                        yield _from_row(row)
                        last_id = row["id"]
                    if len(rows) < self._backlog_page:
                        break
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
        """The next page of stored events after `after_id`."""
        return await self._db.fetch_all(
            "SELECT id, type, ts, session_id, payload FROM events WHERE id > ? ORDER BY id LIMIT ?",
            (after_id, self._backlog_page),
        )


def _from_row(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        type=row["type"],
        ts=datetime.fromisoformat(row["ts"]),
        session_id=row["session_id"],
        payload=json.loads(row["payload"]),
    )
