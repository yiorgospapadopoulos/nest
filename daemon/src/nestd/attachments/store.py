"""Attachments live under `<data_dir>/attachments/<id>/<safe filename>`, indexed in SQLite."""

import asyncio
import base64
import mimetypes
import re
import shutil
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from nestd.clock import Clock
from nestd.errors import InvalidInputError, NestError, NotFoundError
from nestd.storage.db import Database

MAX_ATTACHMENT_BYTES = 500 * 1024 * 1024
MAX_FILENAME_LENGTH = 100
# Image types the agent receives as image content; anything else is passed by path.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
# Types of text that do not start with `text/`.
TEXT_TYPES = frozenset(
    {
        "application/javascript",
        "application/json",
        "application/sql",
        "application/toml",
        "application/x-sh",
        "application/x-yaml",
        "application/xml",
        "application/yaml",
    }
)
# Types that say nothing about the content: a file with one of these is read to see if it is
# text. `video/mp2t` is what `.ts` files get, which are more often TypeScript.
UNSURE_TYPES = frozenset({"application/octet-stream", "video/mp2t"})
SNIFF_BYTES = 8192
CHUNK_BYTES = 1024 * 1024

Read = Callable[[int], Awaitable[bytes]]


def is_text_type(media_type: str) -> bool:
    return (
        media_type.startswith("text/")
        or media_type in TEXT_TYPES
        or media_type.endswith(("+json", "+xml"))
    )


def looks_like_text(head: bytes) -> bool:
    """Whether a file's first bytes are UTF-8 text; a character cut off at the end is fine."""
    if b"\0" in head:
        return False
    try:
        head.decode()
    except UnicodeDecodeError as error:
        return error.start >= len(head) - 3 and error.reason == "unexpected end of data"
    return True


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

    @property
    def is_text(self) -> bool:
        return is_text_type(self.media_type)

    def read_base64(self) -> str:
        return base64.b64encode(self.path.read_bytes()).decode()


class StoredAttachment(BaseModel):
    """An attachment as Settings lists it, by size (D104)."""

    id: str
    name: str
    bytes: int
    media_type: str
    session_id: str | None
    # None while unsent, or when the chat is gone.
    session_title: str | None
    created_at: datetime


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).lstrip(".") or "file"
    if len(cleaned) > MAX_FILENAME_LENGTH:
        suffix = Path(cleaned).suffix
        cleaned = cleaned[: MAX_FILENAME_LENGTH - len(suffix)] + suffix
    return cleaned


class AttachmentStore:
    def __init__(
        self, db: Database, clock: Clock, root: Path, max_bytes: int = MAX_ATTACHMENT_BYTES
    ) -> None:
        self._db = db
        self._clock = clock
        self._root = root
        self.max_bytes = max_bytes

    async def save(self, filename: str, data: bytes, media_type: str | None) -> Attachment:
        async def read(size: int) -> bytes:
            nonlocal data
            chunk, data = data[:size], data[size:]
            return chunk

        return await self.save_from(filename, read, media_type)

    async def save_from(self, filename: str, read: Read, media_type: str | None) -> Attachment:
        """Saves what `read` gives, a chunk at a time, so a large file never sits in memory;
        one past the limit is refused and nothing of it is kept.
        """
        name = safe_filename(filename)
        attachment_id = uuid4().hex
        path = self._root / attachment_id / name
        path.parent.mkdir(parents=True)
        try:
            size, head = await self._write(path, read)
        except AttachmentTooLargeError:
            await asyncio.to_thread(self._delete_dirs, [path.parent])
            raise
        guessed = media_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        attachment = Attachment(
            id=attachment_id,
            session_id=None,
            filename=name,
            media_type="text/plain"
            if guessed in UNSURE_TYPES and looks_like_text(head)
            else guessed,
            path=path,
            size=size,
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

    async def _write(self, path: Path, read: Read) -> tuple[int, bytes]:
        """The size written and the first bytes, for telling text apart."""
        size = 0
        head = b""
        with await asyncio.to_thread(path.open, "wb") as out:
            while chunk := await read(CHUNK_BYTES):
                size += len(chunk)
                if size > self.max_bytes:
                    limit = self.max_bytes // (1024 * 1024)
                    msg = f"attachments larger than {limit} MB are not accepted"
                    raise AttachmentTooLargeError(msg)
                if len(head) < SNIFF_BYTES:
                    head += chunk[: SNIFF_BYTES - len(head)]
                await asyncio.to_thread(out.write, chunk)
        return size, head

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

    async def dirs(self, session_id: str) -> tuple[Path, ...]:
        """The directories of all of a session's attachments, images included."""
        rows = await self._db.fetch_all(
            "SELECT path FROM attachments WHERE session_id = ?", (session_id,)
        )
        return tuple(Path(row["path"]).parent for row in rows)

    async def largest(self, limit: int) -> list[StoredAttachment]:
        """The largest attachments first, with the chat each was sent in."""
        rows = await self._db.fetch_all(
            "SELECT a.id, a.filename, a.size, a.media_type, a.session_id, a.created_at,"
            " s.title AS session_title FROM attachments a LEFT JOIN sessions s"
            " ON s.id = a.session_id ORDER BY a.size DESC, a.created_at DESC, a.rowid DESC"
            " LIMIT ?",
            (limit,),
        )
        return [
            StoredAttachment(
                id=row["id"],
                name=row["filename"],
                bytes=row["size"],
                media_type=row["media_type"],
                session_id=row["session_id"],
                session_title=row["session_title"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def delete(self, attachment_id: str) -> None:
        """Delete one attachment and its file; its chat then shows it as missing."""
        attachment = await self.get(attachment_id)
        await self._db.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        await asyncio.to_thread(self._delete_dirs, [attachment.path.parent])

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
