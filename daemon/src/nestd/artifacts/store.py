"""Artifacts on disk and in SQLite (B79): each version a file under
`<data dir>/artifacts/<artifact id>/v<n>.<md|html>`, the history in the database.
"""

import asyncio
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from nestd.artifacts.models import (
    EXTENSIONS,
    LIST_MAX,
    Artifact,
    ArtifactDetail,
    ArtifactKind,
    ArtifactNotFoundError,
    ArtifactVersion,
    Origin,
    VersionContent,
)
from nestd.artifacts.page import artifact_page
from nestd.clock import Clock
from nestd.storage.db import Database

# A chat or pixie deleted since keeps the name it had, which the delete triggers saved.
_SELECT = (
    "SELECT a.id, a.title, a.kind, a.repo, a.session_id,"
    " COALESCE(s.title, a.chat_title) AS chat_title,"
    " a.session_id IS NOT NULL AND s.id IS NULL AS chat_deleted,"
    " a.pixie_id, COALESCE(p.name, a.pixie_name) AS pixie_name,"
    " a.created_at, a.updated_at, a.seen_at IS NOT NULL AS seen,"
    " (SELECT MAX(version) FROM artifact_versions v WHERE v.artifact_id = a.id)"
    " AS latest_version,"
    " (SELECT COUNT(*) FROM artifact_versions v WHERE v.artifact_id = a.id) AS version_count"
    " FROM artifacts a LEFT JOIN sessions s ON s.id = a.session_id"
    " LEFT JOIN pixies p ON p.id = a.pixie_id"
)
_INSERT_VERSION = (
    "INSERT INTO artifact_versions (artifact_id, version, title, size, created_at)"
    " VALUES (?, ?, ?, ?, ?)"
)


class ArtifactStore:
    def __init__(self, db: Database, clock: Clock, root: Path) -> None:
        self._db = db
        self._clock = clock
        self._root = root
        # One save or delete at a time, so version numbers and files never collide.
        self._lock = asyncio.Lock()

    async def create(self, origin: Origin, kind: ArtifactKind, title: str, data: bytes) -> Artifact:
        artifact_id = uuid4().hex
        now = self._clock.now().isoformat()
        async with self._lock:
            path = await self._write(artifact_id, 1, kind, data)
            try:
                async with self._db.transaction() as tx:
                    await tx.execute(
                        "INSERT INTO artifacts (id, title, kind, repo, session_id, chat_title,"
                        " pixie_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            artifact_id,
                            title,
                            kind,
                            origin.repo,
                            origin.session_id,
                            origin.chat_title,
                            origin.pixie_id,
                            now,
                            now,
                        ),
                    )
                    await tx.execute(_INSERT_VERSION, (artifact_id, 1, title, len(data), now))
            except BaseException:
                await asyncio.to_thread(shutil.rmtree, path.parent, True)
                raise
        return await self.get(artifact_id)

    async def add_version(self, artifact_id: str, title: str | None, data: bytes) -> Artifact:
        """A new latest version, unseen; `title` None keeps the current one."""
        now = self._clock.now().isoformat()
        async with self._lock:
            current = await self.get(artifact_id)
            version = current.latest_version + 1
            title = title or current.title
            path = await self._write(artifact_id, version, current.kind, data)
            try:
                async with self._db.transaction() as tx:
                    await tx.execute(_INSERT_VERSION, (artifact_id, version, title, len(data), now))
                    await tx.execute(
                        "UPDATE artifacts SET title = ?, updated_at = ?, seen_at = NULL"
                        " WHERE id = ?",
                        (title, now, artifact_id),
                    )
            except BaseException:
                await asyncio.to_thread(path.unlink, True)
                raise
        return await self.get(artifact_id)

    async def get(self, artifact_id: str) -> Artifact:
        row = await self._db.fetch_one(f"{_SELECT} WHERE a.id = ?", (artifact_id,))
        if row is None:
            msg = f"unknown artifact {artifact_id!r}"
            raise ArtifactNotFoundError(msg)
        return _artifact(row)

    async def detail(self, artifact_id: str) -> ArtifactDetail:
        artifact = await self.get(artifact_id)
        rows = await self._db.fetch_all(
            "SELECT version, title, size, created_at FROM artifact_versions"
            " WHERE artifact_id = ? ORDER BY version",
            (artifact_id,),
        )
        versions = [ArtifactVersion.model_validate(dict(row)) for row in rows]
        return ArtifactDetail(**artifact.model_dump(), versions=versions)

    async def list_artifacts(
        self, repo: str | None, session_id: str | None, pixie_id: str | None
    ) -> list[Artifact]:
        """The most recently updated first, at most LIST_MAX; each filter left out (None)
        matches every artifact.
        """
        rows = await self._db.fetch_all(
            f"{_SELECT} WHERE (? IS NULL OR a.repo = ?) AND (? IS NULL OR a.session_id = ?)"
            " AND (? IS NULL OR a.pixie_id = ?) ORDER BY a.updated_at DESC, a.rowid DESC LIMIT ?",
            (repo, repo, session_id, session_id, pixie_id, pixie_id, LIST_MAX),
        )
        return [_artifact(row) for row in rows]

    async def content(self, artifact_id: str, version: int) -> VersionContent:
        artifact = await self.get(artifact_id)
        row = await self._db.fetch_one(
            "SELECT title, size, created_at FROM artifact_versions"
            " WHERE artifact_id = ? AND version = ?",
            (artifact_id, version),
        )
        if row is None:
            msg = f"artifact {artifact_id!r} has no version {version}"
            raise ArtifactNotFoundError(msg)
        path = self._path(artifact_id, version, artifact.kind)
        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except FileNotFoundError as error:
            msg = f"the file of version {version} of artifact {artifact_id!r} is missing"
            raise ArtifactNotFoundError(msg) from error
        return VersionContent(
            artifact_id=artifact_id,
            version=version,
            kind=artifact.kind,
            title=row["title"],
            content=text,
            page=artifact_page(artifact.kind, row["title"], text),
            size=row["size"],
            created_at=row["created_at"],
        )

    async def mark_seen(self, artifact_id: str) -> tuple[Artifact, bool]:
        """The artifact, seen; and whether it was unseen until now."""
        changed = await self._db.execute(
            "UPDATE artifacts SET seen_at = ? WHERE id = ? AND seen_at IS NULL",
            (self._clock.now().isoformat(), artifact_id),
        )
        return await self.get(artifact_id), changed > 0

    async def unseen(self) -> int:
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM artifacts WHERE seen_at IS NULL")
        assert row is not None  # noqa: S101 (COUNT always returns a row)
        return row["n"]

    async def delete(self, artifact_id: str) -> None:
        """Its rows and every version's file."""
        async with self._lock:
            deleted = await self._db.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
            if not deleted:
                msg = f"unknown artifact {artifact_id!r}"
                raise ArtifactNotFoundError(msg)
            await asyncio.to_thread(shutil.rmtree, self._root / artifact_id, True)

    def _path(self, artifact_id: str, version: int, kind: ArtifactKind) -> Path:
        return self._root / artifact_id / f"v{version}.{EXTENSIONS[kind]}"

    async def _write(self, artifact_id: str, version: int, kind: ArtifactKind, data: bytes) -> Path:
        path = self._path(artifact_id, version, kind)
        await asyncio.to_thread(_write_file, path, data)
        return path


def _write_file(path: Path, data: bytes) -> None:
    """Whole or not at all: a crash never leaves half a version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_bytes(data)
    partial.replace(path)


def _artifact(row: sqlite3.Row) -> Artifact:
    return Artifact.model_validate(dict(row))
