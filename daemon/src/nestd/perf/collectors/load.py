"""Load speed (C7): how long the daemon takes to serve what the apps load, and how big it
is. The same routes are called in-process, with their serialization, so the times are
the daemon's own; parsing on the device is not included."""

import time
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass

import httpx
from starlette.types import ASGIApp

from nestd.events.bus import EventBus
from nestd.perf.formatting import size
from nestd.perf.models import Collected, Measured
from nestd.perf.timing import measuring
from nestd.storage.db import Database

_BASE_URL = "http://127.0.0.1"

# One GET of an API path: how long it took in milliseconds and the bytes of its body.
type Fetch = Callable[[str], Awaitable[tuple[float, int]]]

# What a client loads when it opens.
OPEN_APP = (
    "/api/repos",
    "/api/sessions",
    "/api/approvals?status=pending",
    "/api/claude-chats",
)
BIGGEST_CHATS = 3
RECONNECT_EVENTS = 500
# The slow phone network estimate: 1.6 Mbit/s, and four round trips of 300 ms.
SLOW_BYTES_PER_SECOND = 1_600_000 / 8
SLOW_ROUND_TRIPS = 4
SLOW_ROUND_TRIP_MS = 300
_ORDINALS = ("Biggest chat opens", "Second biggest chat", "Third biggest chat")
_CHAT_IDS = ("biggest_chat", "second_chat", "third_chat")


@dataclass(frozen=True)
class _Timed:
    ms: float
    bytes: int


class LoadSpeed:
    def __init__(self, db: Database, bus: EventBus, fetch: Fetch) -> None:
        self._db = db
        self._bus = bus
        self._fetch = fetch

    async def __call__(self) -> Collected:
        opened = await self._all(OPEN_APP)
        metrics = [_timed("open_app", "Open the app", opened)]
        biggest: int | None = None
        for index, session_id in enumerate(await self._biggest_chats()):
            timed = await self._all(
                (f"/api/sessions/{session_id}", f"/api/sessions/{session_id}/events")
            )
            first = biggest is None
            biggest = timed.bytes if first else biggest
            metric = _timed(_CHAT_IDS[index], _ORDINALS[index], timed)
            if first:
                metric.chat_id = session_id
            metrics.append(metric)
        reconnect = await self._reconnect()
        metrics.append(
            Measured(
                id="reconnect",
                label="Reconnect",
                unit="ms",
                better="lower",
                value=None if reconnect is None else reconnect.ms,
                sub=None
                if reconnect is None
                else f"last {RECONNECT_EVENTS} events, {size(reconnect.bytes)}",
            )
        )
        metrics.append(
            Measured(
                id="slow_network",
                label="Biggest chat on a slow phone network",
                unit="ms",
                better="lower",
                value=None if biggest is None else slow_network_ms(biggest),
                sub="estimate at 1.6 Mbit/s",
            )
        )
        return Collected(metrics=metrics)

    async def _all(self, paths: tuple[str, ...]) -> _Timed:
        total_ms, total_bytes = 0.0, 0
        for path in paths:
            ms, count = await self._fetch(path)
            total_ms += ms
            total_bytes += count
        return _Timed(total_ms, total_bytes)

    async def _biggest_chats(self) -> list[str]:
        """The chats with the most stored transcript, biggest first."""
        rows = await self._db.fetch_all(
            "SELECT e.session_id, SUM(LENGTH(e.payload)) AS size FROM events e"
            " JOIN sessions s ON s.id = e.session_id GROUP BY e.session_id"
            " ORDER BY size DESC LIMIT ?",
            (BIGGEST_CHATS,),
        )
        return [row["session_id"] for row in rows]

    async def _reconnect(self) -> _Timed | None:
        """Replaying the latest events to a socket that reconnects, as the socket sends
        them; None when there are none."""
        last = await self._bus.last_id()
        if last == 0:
            return None
        started = time.perf_counter()
        sent = 0
        async with aclosing(self._bus.subscribe(max(0, last - RECONNECT_EVENTS))) as events:
            async for event in events:
                sent += len(event.model_dump_json().encode())
                if event.id is not None and event.id >= last:
                    break
        return _Timed((time.perf_counter() - started) * 1000, sent)


class InProcess:
    """GETs from the daemon's own app, in-process and as this Mac's device; not counted
    in the route timings. The app is attached once it exists, as it is built after the
    context."""

    def __init__(self, token: Callable[[], Awaitable[str]]) -> None:
        self._token = token
        self._app: ASGIApp | None = None

    def attach(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, path: str) -> tuple[float, int]:
        if self._app is None:
            msg = "the API is not attached"
            raise RuntimeError(msg)
        headers = {"Authorization": f"Bearer {await self._token()}"}
        transport = httpx.ASGITransport(app=self._app)
        reset = measuring.set(True)
        try:
            async with httpx.AsyncClient(transport=transport, base_url=_BASE_URL) as client:
                started = time.perf_counter()
                response = await client.get(path, headers=headers)
                ms = (time.perf_counter() - started) * 1000
        finally:
            measuring.reset(reset)
        response.raise_for_status()
        return ms, len(response.content)


def slow_network_ms(count: int) -> float:
    return count / SLOW_BYTES_PER_SECOND * 1000 + SLOW_ROUND_TRIPS * SLOW_ROUND_TRIP_MS


def _timed(metric: str, label: str, timed: _Timed) -> Measured:
    sub = size(timed.bytes)
    return Measured(id=metric, label=label, unit="ms", better="lower", value=timed.ms, sub=sub)
