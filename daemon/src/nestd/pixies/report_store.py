"""Pixie reports in SQLite (B42): kept with their pixie, newest listed first."""

import sqlite3
from uuid import uuid4

from nestd.clock import Clock
from nestd.errors import NotFoundError
from nestd.pixies.habit_models import PixieReport, Severity
from nestd.storage.db import Database

# Reports a listing returns at most.
LIST_MAX = 200


class ReportNotFoundError(NotFoundError):
    pass


class ReportStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def add(
        self,
        pixie_id: str,
        severity: Severity,
        title: str,
        body: str,
        link: str | None,
        *,
        habit: tuple[str, str] | None = None,
        run_id: str | None = None,
    ) -> PixieReport:
        """`habit` is the id and name of the habit whose run reported, if any."""
        report = PixieReport(
            id=uuid4().hex,
            pixie_id=pixie_id,
            severity=severity,
            title=title,
            body=body,
            link=link,
            habit_id=None if habit is None else habit[0],
            habit_name=None if habit is None else habit[1],
            run_id=run_id,
            created_at=self._clock.now(),
            read_at=None,
        )
        values = report.model_dump()
        values["created_at"] = report.created_at.isoformat()
        await self._db.execute(
            f"INSERT INTO pixie_reports ({', '.join(values)})"  # noqa: S608
            f" VALUES ({', '.join('?' for _ in values)})",
            tuple(values.values()),
        )
        return report

    async def get(self, report_id: str) -> PixieReport:
        row = await self._db.fetch_one("SELECT * FROM pixie_reports WHERE id = ?", (report_id,))
        if row is None:
            msg = f"unknown report {report_id!r}"
            raise ReportNotFoundError(msg)
        return _report(row)

    async def list_reports(self, unread: bool) -> list[PixieReport]:
        """Newest first, at most LIST_MAX; with `unread`, only those not read yet."""
        rows = await self._db.fetch_all(
            "SELECT * FROM pixie_reports WHERE (? = 0 OR read_at IS NULL)"
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (unread, LIST_MAX),
        )
        return [_report(row) for row in rows]

    async def mark_read(self, report_id: str) -> tuple[PixieReport, bool]:
        """The report, read; and whether it was unread until now."""
        changed = await self._db.execute(
            "UPDATE pixie_reports SET read_at = ? WHERE id = ? AND read_at IS NULL",
            (self._clock.now().isoformat(), report_id),
        )
        return await self.get(report_id), changed > 0

    async def mark_pixie_read(self, pixie_id: str) -> list[str]:
        """Marks every unread report of the pixie read; returns their ids, oldest first."""
        rows = await self._db.fetch_all(
            "UPDATE pixie_reports SET read_at = ? WHERE pixie_id = ? AND read_at IS NULL"
            " RETURNING id, created_at",
            (self._clock.now().isoformat(), pixie_id),
        )
        return [row["id"] for row in sorted(rows, key=lambda row: row["created_at"])]


def _report(row: sqlite3.Row) -> PixieReport:
    return PixieReport.model_validate(dict(row))
