"""Approval rows in SQLite, joined with their session's repo and title."""

import json
import sqlite3
from collections.abc import Sequence
from uuid import uuid4

from pydantic import JsonValue

from harness.approvals.errors import ApprovalNotFoundError
from harness.approvals.models import Approval, ApprovalKind, ApprovalStatus
from harness.clock import Clock
from harness.storage.db import Database

_SELECT = "SELECT a.*, s.repo, s.title FROM approvals a JOIN sessions s ON s.id = a.session_id"
_ORDER = " ORDER BY a.created_at, a.rowid"


class ApprovalStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def create(
        self, session_id: str, kind: ApprovalKind, payload: dict[str, JsonValue]
    ) -> Approval:
        approval_id = uuid4().hex
        await self._db.execute(
            "INSERT INTO approvals (id, session_id, kind, status, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                approval_id,
                session_id,
                kind,
                ApprovalStatus.PENDING,
                json.dumps(payload),
                self._clock.now().isoformat(),
            ),
        )
        return await self.get(approval_id)

    async def get(self, approval_id: str) -> Approval:
        row = await self._db.fetch_one(f"{_SELECT} WHERE a.id = ?", (approval_id,))
        if row is None:
            msg = f"unknown approval {approval_id!r}"
            raise ApprovalNotFoundError(msg)
        return _approval(row)

    async def list_approvals(
        self, status: ApprovalStatus | None, repo: str | None
    ) -> list[Approval]:
        """Oldest first, optionally filtered by status and by the session's repo."""
        rows = await self._db.fetch_all(
            f"{_SELECT} WHERE (? IS NULL OR a.status = ?) AND (? IS NULL OR s.repo = ?){_ORDER}",
            (status, status, repo, repo),
        )
        return [_approval(row) for row in rows]

    async def pending(
        self, kinds: Sequence[ApprovalKind], session_id: str | None = None
    ) -> list[Approval]:
        """Pending items of the given kinds, of one session or of all sessions."""
        placeholders = ", ".join("?" for _ in kinds)
        rows = await self._db.fetch_all(
            f"{_SELECT} WHERE a.status = ? AND a.kind IN ({placeholders})"
            f" AND (? IS NULL OR a.session_id = ?){_ORDER}",
            (ApprovalStatus.PENDING, *kinds, session_id, session_id),
        )
        return [_approval(row) for row in rows]

    async def close(
        self,
        approval_id: str,
        status: ApprovalStatus,
        resolution: dict[str, JsonValue] | None,
    ) -> Approval | None:
        """Move a pending item to `status`; None if it is not pending (or unknown)."""
        changed = await self._db.execute(
            "UPDATE approvals SET status = ?, resolution = ?, resolved_at = ?"
            " WHERE id = ? AND status = ?",
            (
                status,
                None if resolution is None else json.dumps(resolution),
                self._clock.now().isoformat(),
                approval_id,
                ApprovalStatus.PENDING,
            ),
        )
        return await self.get(approval_id) if changed else None


def _approval(row: sqlite3.Row) -> Approval:
    data = dict(row)
    data["payload"] = json.loads(data["payload"])
    data["resolution"] = None if data["resolution"] is None else json.loads(data["resolution"])
    return Approval.model_validate(data)
