"""Per-device tokens and one-time pairing codes. Only SHA-256 hashes are stored."""

import asyncio
import hashlib
import sqlite3
from collections import deque
from datetime import datetime, timedelta
from secrets import choice, token_urlsafe
from uuid import uuid4

from nestd.auth.models import Device, PairingCode
from nestd.auth.secrets import SecretStore
from nestd.clock import Clock
from nestd.storage.db import Database

LOCAL_DEVICE_NAME = "This Mac"
LOCAL_DEVICE_ACCOUNT = "local-device-token"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
# Failed redemptions allowed per client address, and in total as a safety net, within
# the window (H-01): one guesser locks out only itself, and spreading guesses over many
# addresses still stops soon. 31^8 codes make either rate hopeless for guessing.
MAX_FAILURES = 5
MAX_TOTAL_FAILURES = 20
FAILURE_WINDOW = timedelta(minutes=5)


class InvalidPairingCodeError(Exception):
    """The code is unknown, already used or expired."""


class PairingLockedError(Exception):
    """Too many failed redemptions recently; this client's (or everyone's) are refused."""

    def __init__(self, retry_after: timedelta) -> None:
        super().__init__(f"pairing locked; retry in {retry_after}")
        self.retry_after = retry_after


class DeviceService:
    def __init__(self, db: Database, clock: Clock, secrets: SecretStore) -> None:
        self._db = db
        self._clock = clock
        self._secrets = secrets
        # Failed redemption times inside the current window, oldest first: all of them,
        # and per client address.
        self._failures: deque[datetime] = deque()
        self._client_failures: dict[str, deque[datetime]] = {}
        # Redemptions run one at a time, so each failure counts before the next lockout
        # check; otherwise concurrent guesses all pass the check (D051).
        self._redeeming = asyncio.Lock()

    async def ensure_local_device(self) -> str:
        """Return a valid token for this Mac, creating or rotating it as needed."""
        stored = self._secrets.get(LOCAL_DEVICE_ACCOUNT)
        row = await self._db.fetch_one(
            "SELECT id, token_hash, revoked_at FROM devices WHERE is_local = 1"
        )
        if (
            row is not None
            and stored is not None
            and row["revoked_at"] is None
            and row["token_hash"] == _hash(stored)
        ):
            return stored
        token = token_urlsafe(32)
        if row is None:
            await self._db.execute(
                "INSERT INTO devices (id, name, token_hash, is_local, created_at)"
                " VALUES (?, ?, ?, 1, ?)",
                (uuid4().hex, LOCAL_DEVICE_NAME, _hash(token), self._clock.now().isoformat()),
            )
        else:
            await self._db.execute(
                "UPDATE devices SET token_hash = ?, revoked_at = NULL WHERE id = ?",
                (_hash(token), row["id"]),
            )
        self._secrets.set(LOCAL_DEVICE_ACCOUNT, token)
        return token

    async def create_pairing_code(self, ttl: timedelta = timedelta(minutes=5)) -> PairingCode:
        code = "".join(choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        now = self._clock.now()
        expires_at = now + ttl
        await self._db.execute(
            "INSERT INTO pairing_codes (code_hash, created_at, expires_at) VALUES (?, ?, ?)",
            (_hash(code), now.isoformat(), expires_at.isoformat()),
        )
        return PairingCode(code=code, expires_at=expires_at)

    async def redeem_pairing_code(
        self, code: str, device_name: str, *, client: str
    ) -> tuple[Device, str]:
        """Redeem a code for a new device; `client` is the address failures count against."""
        async with self._redeeming:
            return await self._redeem(code, device_name, client)

    async def _redeem(self, code: str, device_name: str, client: str) -> tuple[Device, str]:
        now = self._clock.now()
        self._check_lockout(now, client)
        code_hash = _hash(code.strip().upper())
        async with self._db.transaction() as tx:
            row = await tx.fetch_one(
                "SELECT expires_at, used_at FROM pairing_codes WHERE code_hash = ?", (code_hash,)
            )
            if (
                row is None
                or row["used_at"] is not None
                or datetime.fromisoformat(row["expires_at"]) <= now
            ):
                self._failures.append(now)
                self._client_failures.setdefault(client, deque()).append(now)
                raise InvalidPairingCodeError
            await tx.execute(
                "UPDATE pairing_codes SET used_at = ? WHERE code_hash = ?",
                (now.isoformat(), code_hash),
            )
            token = token_urlsafe(32)
            device = Device(
                id=uuid4().hex,
                name=device_name,
                is_local=False,
                created_at=now,
                last_seen_at=None,
                revoked_at=None,
            )
            await tx.execute(
                "INSERT INTO devices (id, name, token_hash, is_local, created_at)"
                " VALUES (?, ?, ?, 0, ?)",
                (device.id, device.name, _hash(token), now.isoformat()),
            )
        return device, token

    async def authenticate(self, token: str) -> Device | None:
        """Return the active device for a token and record that it was seen."""
        now = self._clock.now()
        async with self._db.transaction() as tx:
            row = await tx.fetch_one(
                "SELECT * FROM devices WHERE token_hash = ? AND revoked_at IS NULL",
                (_hash(token),),
            )
            if row is None:
                return None
            await tx.execute(
                "UPDATE devices SET last_seen_at = ? WHERE id = ?", (now.isoformat(), row["id"])
            )
        return _device(row).model_copy(update={"last_seen_at": now})

    async def list_devices(self) -> list[Device]:
        """Active (not revoked) devices, oldest first."""
        rows = await self._db.fetch_all(
            "SELECT * FROM devices WHERE revoked_at IS NULL ORDER BY created_at, rowid"
        )
        return [_device(row) for row in rows]

    async def revoke(self, device_id: str) -> bool:
        """Revoke an active device. Returns False if it is unknown or already revoked."""
        changed = await self._db.execute(
            "UPDATE devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (self._clock.now().isoformat(), device_id),
        )
        return changed == 1

    def _check_lockout(self, now: datetime, client: str) -> None:
        _drop_expired(self._failures, now)
        for address, failures in list(self._client_failures.items()):
            _drop_expired(failures, now)
            if not failures:
                del self._client_failures[address]
        mine = self._client_failures.get(client, deque[datetime]())
        if len(mine) >= MAX_FAILURES:
            raise PairingLockedError(mine[0] + FAILURE_WINDOW - now)
        if len(self._failures) >= MAX_TOTAL_FAILURES:
            raise PairingLockedError(self._failures[0] + FAILURE_WINDOW - now)


def _drop_expired(failures: deque[datetime], now: datetime) -> None:
    while failures and now - failures[0] >= FAILURE_WINDOW:
        failures.popleft()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _optional_time(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _device(row: sqlite3.Row) -> Device:
    return Device(
        id=row["id"],
        name=row["name"],
        is_local=bool(row["is_local"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        last_seen_at=_optional_time(row["last_seen_at"]),
        revoked_at=_optional_time(row["revoked_at"]),
    )
