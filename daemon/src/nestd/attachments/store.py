"""Attachments live under `<data_dir>/attachments/<id>/<safe filename>`, indexed in SQLite."""

import asyncio
import base64
import mimetypes
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from nestd.clock import Clock
from nestd.errors import InvalidInputError, NestError, NotFoundError
from nestd.storage.db import Database

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_FILENAME_LENGTH = 100
# Image types the agent receives as image content; anything else is passed by path.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


class AttachmentTooLargeError(NestError):
    status_code = 413


class UnknownAttachmentError(InvalidInputError):
    pass


class AttachmentNotFoundError(NotFoundError):
    pass


class Attachment(BaseModel):
    id: str
    session_id: str | None
    filename: str
    media_type: str
    path: Path
    size: int
    created_at: datetime

    @property
    def is_image(self) -> bool:
        return self.media_type in IMAGE_TYPES

    def read_base64(self) -> str:
        return base64.b64encode(self.path.read_bytes()).decode()


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).lstrip(".") or "file"
    if len(cleaned) > MAX_FILENAME_LENGTH:
        suffix = Path(cleaned).suffix
        cleaned = cleaned[: MAX_FILENAME_LENGTH - len(suffix)] + suffix
    return cleaned


class AttachmentStore:
    def __init__(self, db: Database, clock: Clock, root: Path) -> None:
        self._db = db
        self._clock = clock
        self._root = root

    async def save(self, filename: str, data: bytes, media_type: str | None) -> Attachment:
        if len(data) > MAX_ATTACHMENT_BYTES:
            msg = "attachments larger than 20 MB are not accepted"
            raise AttachmentTooLargeError(msg)
        name = safe_filename(filename)
        attachment_id = uuid4().hex
        path = self._root / attachment_id / name
        path.parent.mkdir(parents=True)
        await asyncio.to_thread(path.write_bytes, data)
        attachment = Attachment(
            id=attachment_id,
            session_id=None,
            filename=name,
            media_type=media_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
            path=path,
            size=len(data),
            created_at=self._clock.now(),
        )
        await self._db.execute(
            "INSERT INTO attachments (id, session_id, filename, media_type, path, size, created_at)"
            " VALUES (?, NULL, ?, ?, ?, ?, ?)",
            (
                attachment.id,
                attachment.filename,
                attachment.media_type,
                str(attachment.path),
                attachment.size,
                attachment.created_at.isoformat(),
            ),
        )
        return attachment

    async def get(self, attachment_id: str) -> Attachment:
        row = await self._db.fetch_one("SELECT * FROM attachments WHERE id = ?", (attachment_id,))
        if row is None:
            msg = f"unknown attachment {attachment_id!r}"
            raise AttachmentNotFoundError(msg)
        return _attachment(row)

    async def for_session(self, ids: list[str], session_id: str | None) -> list[Attachment]:
        """The given attachments, in order, if each is unused or already in this session."""
        found: list[Attachment] = []
        for attachment_id in ids:
            row = await self._db.fetch_one(
                "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
            )
            if row is None:
                msg = f"unknown attachment {attachment_id!r}"
                raise UnknownAttachmentError(msg)
            attachment = _attachment(row)
            if attachment.session_id not in (None, session_id):
                msg = f"attachment {attachment_id!r} belongs to another session"
                raise UnknownAttachmentError(msg)
            found.append(attachment)
        return found

    async def assign(self, ids: list[str], session_id: str) -> None:
        async with self._db.transaction() as tx:
            for attachment_id in ids:
                await tx.execute(
                    "UPDATE attachments SET session_id = ? WHERE id = ?",
                    (session_id, attachment_id),
                )

    async def file_dirs(self, session_id: str) -> tuple[Path, ...]:
        """Directories of a session's non-image attachments, which the agent reads by path."""
        rows = await self._db.fetch_all(
            "SELECT path, media_type FROM attachments WHERE session_id = ?"
            " ORDER BY created_at, rowid",
            (session_id,),
        )
        return tuple(
            Path(row["path"]).parent for row in rows if row["media_type"] not in IMAGE_TYPES
        )

    async def delete_files(self, session_id: str) -> None:
        """Delete the files of a session's attachments; the rows go with the session."""
        rows = await self._db.fetch_all(
            "SELECT path FROM attachments WHERE session_id = ?", (session_id,)
        )
        await asyncio.to_thread(self._delete_dirs, [Path(row["path"]).parent for row in rows])

    def _delete_dirs(self, directories: list[Path]) -> None:
        root = self._root.resolve()
        for directory in directories:
            if directory.resolve().parent == root:
                shutil.rmtree(directory, ignore_errors=True)


def _attachment(row: sqlite3.Row) -> Attachment:
    return Attachment.model_validate(dict(row))
