"""Waiting on you (C8): how long questions, plans and permission prompts of the last 30
days waited for an answer, and how long a notification took to reach the push service
since the daemon started."""

from collections.abc import Callable

from nestd.clock import Clock
from nestd.perf.collectors.common import median, ms_between, since, slowest
from nestd.perf.models import Collected, Measured
from nestd.storage.db import Database

DAYS = 30
_KINDS = (
    ("questions", "Questions and plans", ("question", "plan")),
    ("permissions", "Permissions", ("permission",)),
)


class Waiting:
    def __init__(self, db: Database, clock: Clock, send_times: Callable[[], list[float]]) -> None:
        self._db = db
        self._clock = clock
        self._send_times = send_times

    async def __call__(self) -> Collected:
        rows = await self._db.fetch_all(
            "SELECT kind, created_at, resolved_at FROM approvals"
            " WHERE status = 'resolved' AND resolved_at IS NOT NULL AND created_at >= ?",
            (since(self._clock, DAYS).isoformat(),),
        )
        metrics: list[Measured] = []
        for key, label, kinds in _KINDS:
            waits = [
                ms_between(r["created_at"], r["resolved_at"]) for r in rows if r["kind"] in kinds
            ]
            count = len(waits)
            metrics += [
                Measured(
                    id=f"{key}_median",
                    label=f"{label}, typical wait",
                    unit="ms",
                    better="lower",
                    value=median(waits),
                    sub=f"{count} answered",
                ),
                Measured(
                    id=f"{key}_slowest",
                    label=f"{label}, longest wait",
                    unit="ms",
                    better="lower",
                    value=slowest(waits),
                ),
            ]
        sends = self._send_times()
        metrics.append(
            Measured(
                id="notification",
                label="Notification sent",
                unit="ms",
                better="lower",
                value=median(sends),
                sub=f"{len(sends)} since the daemon started",
            )
        )
        return Collected(metrics=metrics)
