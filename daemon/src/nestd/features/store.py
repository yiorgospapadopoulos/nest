"""Each device's first visit to Features and when it first showed each feature (B103)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from nestd.clock import Clock
from nestd.storage.db import Database


@dataclass(frozen=True)
class DeviceFeatures:
    # None until the device first reports the features it shows.
    first_visit: datetime | None
    shown: dict[str, datetime]


class FeatureStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def state(self, device_id: str) -> DeviceFeatures:
        visit = await self._db.fetch_one(
            "SELECT first_visit_at FROM feature_visits WHERE device_id = ?", (device_id,)
        )
        rows = await self._db.fetch_all(
            "SELECT feature_id, first_shown_at FROM feature_seen WHERE device_id = ?",
            (device_id,),
        )
        return DeviceFeatures(
            first_visit=None if visit is None else datetime.fromisoformat(visit["first_visit_at"]),
            shown={
                row["feature_id"]: datetime.fromisoformat(row["first_shown_at"]) for row in rows
            },
        )

    async def record_shown(self, device_id: str, ids: Iterable[str]) -> None:
        """The device shows these features now; only the first visit and showing are kept."""
        now = self._clock.now().isoformat()
        async with self._db.transaction() as tx:
            await tx.execute(
                "INSERT INTO feature_visits (device_id, first_visit_at) VALUES (?, ?)"
                " ON CONFLICT (device_id) DO NOTHING",
                (device_id, now),
            )
            for feature_id in ids:
                await tx.execute(
                    "INSERT INTO feature_seen (device_id, feature_id, first_shown_at)"
                    " VALUES (?, ?, ?) ON CONFLICT (device_id, feature_id) DO NOTHING",
                    (device_id, feature_id, now),
                )
