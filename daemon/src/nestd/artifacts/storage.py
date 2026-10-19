"""What an artifact's page remembers (B88 stage 3, D117): keys and string values, one store
per artifact shared by all its versions and the user's devices, kept until the artifact is
deleted. A write is applied whole or not at all, with the caps checked on the result.
"""

import asyncio

from pydantic import BaseModel

from nestd.artifacts.models import InvalidArtifactError
from nestd.clock import Clock
from nestd.errors import NestError
from nestd.storage.db import Database

KEY_MAX = 256
# Bytes of one value, and of a page's keys and values in all.
VALUE_MAX = 256 * 1024
STORAGE_MAX = 2 * 1024 * 1024
KEYS_MAX = 1000


class StorageQuotaError(NestError):
    status_code = 413


class PageData(BaseModel):
    items: dict[str, str]
    # Bytes of the UTF-8 keys and values.
    size: int


class StorageSize(BaseModel):
    size: int


class PageStorage:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock
        # One write at a time, so the caps hold for the result of every write.
        self._lock = asyncio.Lock()

    async def read(self, artifact_id: str) -> PageData:
        rows = await self._db.fetch_all(
            "SELECT key, value FROM artifact_storage WHERE artifact_id = ? ORDER BY key",
            (artifact_id,),
        )
        items = {row["key"]: row["value"] for row in rows}
        return PageData(items=items, size=_size(items))

    async def write(self, artifact_id: str, values: dict[str, str], remove: list[str]) -> int:
        """The page's size after the write."""
        for key in [*values, *remove]:
            _check_key(key)
        for key, value in values.items():
            _check_value(key, value)
        both = sorted(set(values) & set(remove))
        if both:
            msg = f"{both[0]!r} is both set and removed"
            raise InvalidArtifactError(msg)
        async with self._lock:
            items = (await self.read(artifact_id)).items
            for key in remove:
                items.pop(key, None)
            items.update(values)
            _check_caps(items)
            if values or remove:
                await self._apply(artifact_id, values, remove)
        return _size(items)

    async def clear(self, artifact_id: str) -> None:
        async with self._lock:
            await self._db.execute(
                "DELETE FROM artifact_storage WHERE artifact_id = ?", (artifact_id,)
            )

    async def _apply(self, artifact_id: str, values: dict[str, str], remove: list[str]) -> None:
        now = self._clock.now().isoformat()
        async with self._db.transaction() as tx:
            for key in remove:
                await tx.execute(
                    "DELETE FROM artifact_storage WHERE artifact_id = ? AND key = ?",
                    (artifact_id, key),
                )
            for key, value in values.items():
                await tx.execute(
                    "INSERT INTO artifact_storage (artifact_id, key, value, updated_at)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT (artifact_id, key)"
                    " DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    (artifact_id, key, value, now),
                )


def _bytes(text: str) -> int:
    return len(text.encode())


def _size(items: dict[str, str]) -> int:
    return sum(_bytes(key) + _bytes(value) for key, value in items.items())


def _check_key(key: str) -> None:
    if not 1 <= len(key) <= KEY_MAX:
        msg = f"a stored key has 1 to {KEY_MAX} characters"
        raise InvalidArtifactError(msg)
    try:
        key.encode()
    except UnicodeEncodeError as error:
        msg = f"the key {key!r} is not valid text"
        raise InvalidArtifactError(msg) from error


def _check_value(key: str, value: str) -> None:
    try:
        size = _bytes(value)
    except UnicodeEncodeError as error:
        msg = f"the value of {key!r} is not valid text"
        raise InvalidArtifactError(msg) from error
    if size > VALUE_MAX:
        msg = (
            f"the value of {key!r} is {size} bytes; a stored value is at most {VALUE_MAX}"
            " bytes (256 KiB)"
        )
        raise StorageQuotaError(msg)


def _check_caps(items: dict[str, str]) -> None:
    if len(items) > KEYS_MAX:
        msg = f"the page would store {len(items)} keys; a page stores at most {KEYS_MAX}"
        raise StorageQuotaError(msg)
    size = _size(items)
    if size > STORAGE_MAX:
        msg = (
            f"the page would store {size} bytes; a page stores at most {STORAGE_MAX} bytes (2 MiB)"
        )
        raise StorageQuotaError(msg)
