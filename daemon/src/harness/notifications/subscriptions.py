"""Web push subscriptions of paired devices, in SQLite."""

import sqlite3
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel

from harness.clock import Clock
from harness.storage.db import Database


class PushSubscription(BaseModel):
    id: str
    device_id: str
    endpoint: str
    p256dh: str
    auth: str
    created_at: datetime
    last_success_at: datetime | None
    failures: int


class PushSubscriptionStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def upsert(
        self, device_id: str, endpoint: str, p256dh: str, auth: str
    ) -> PushSubscription:
        """Store a subscription; the same endpoint again takes the new keys and device."""
        rows = await self._db.fetch_all(
            "INSERT INTO push_subscriptions (id, device_id, endpoint, p256dh, auth, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (endpoint) DO UPDATE SET device_id = excluded.device_id,"
            " p256dh = excluded.p256dh, auth = excluded.auth, failures = 0"
            " RETURNING *",
            (uuid4().hex, device_id, endpoint, p256dh, auth, self._clock.now().isoformat()),
        )
        return _subscription(rows[0])

    async def remove(self, device_id: str, endpoint: str) -> bool:
        """Delete one of the device's own subscriptions. False if it had none there."""
        changed = await self._db.execute(
            "DELETE FROM push_subscriptions WHERE device_id = ? AND endpoint = ?",
            (device_id, endpoint),
        )
        return changed == 1

    async def delete(self, subscription_id: str) -> None:
        await self._db.execute("DELETE FROM push_subscriptions WHERE id = ?", (subscription_id,))

    async def forget_device(self, device_id: str) -> int:
        return await self._db.execute(
            "DELETE FROM push_subscriptions WHERE device_id = ?", (device_id,)
        )

    async def for_device(self, device_id: str) -> list[PushSubscription]:
        rows = await self._db.fetch_all(
            "SELECT * FROM push_subscriptions WHERE device_id = ? ORDER BY created_at, rowid",
            (device_id,),
        )
        return [_subscription(row) for row in rows]

    async def active(self) -> list[PushSubscription]:
        """Subscriptions of devices that are not revoked, oldest first."""
        rows = await self._db.fetch_all(
            "SELECT s.* FROM push_subscriptions s JOIN devices d ON d.id = s.device_id"
            " WHERE d.revoked_at IS NULL ORDER BY s.created_at, s.rowid"
        )
        return [_subscription(row) for row in rows]

    async def succeeded(self, subscription_id: str) -> None:
        await self._db.execute(
            "UPDATE push_subscriptions SET last_success_at = ?, failures = 0 WHERE id = ?",
            (self._clock.now().isoformat(), subscription_id),
        )

    async def failed(self, subscription_id: str) -> None:
        await self._db.execute(
            "UPDATE push_subscriptions SET failures = failures + 1 WHERE id = ?",
            (subscription_id,),
        )


def _subscription(row: sqlite3.Row) -> PushSubscription:
    last = row["last_success_at"]
    return PushSubscription(
        id=row["id"],
        device_id=row["device_id"],
        endpoint=row["endpoint"],
        p256dh=row["p256dh"],
        auth=row["auth"],
        created_at=datetime.fromisoformat(row["created_at"]),
        last_success_at=None if last is None else datetime.fromisoformat(last),
        failures=row["failures"],
    )
