"""How long the API's routes take, kept in memory since the daemon started (C15)."""

import statistics
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field

from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Each route keeps its latest durations for the median; the count and slowest cover all.
KEPT_PER_ROUTE = 500

# Set while a performance run calls the routes itself, so its calls are not counted.
measuring: ContextVar[bool] = ContextVar("perf_measuring", default=False)


@dataclass
class RouteStats:
    count: int = 0
    slowest_ms: float = 0.0
    bytes: int = 0
    recent: deque[float] = field(default_factory=lambda: deque[float](maxlen=KEPT_PER_ROUTE))


@dataclass(frozen=True)
class RouteTiming:
    route: str
    count: int
    median_ms: float
    slowest_ms: float
    bytes: int


class RouteTimings:
    def __init__(self) -> None:
        self._routes: dict[str, RouteStats] = {}

    def record(self, route: str, ms: float, size: int) -> None:
        stats = self._routes.setdefault(route, RouteStats())
        stats.count += 1
        stats.slowest_ms = max(stats.slowest_ms, ms)
        stats.bytes += size
        stats.recent.append(ms)

    def slowest(self, limit: int) -> list[RouteTiming]:
        """The routes with the slowest median, slowest first."""
        timings = [
            RouteTiming(route, s.count, statistics.median(s.recent), s.slowest_ms, s.bytes)
            for route, s in self._routes.items()
        ]
        timings.sort(key=lambda t: t.median_ms, reverse=True)
        return timings[:limit]


class TimingMiddleware:
    """Times every API request into `timings`; the web app's files are left out."""

    def __init__(self, app: ASGIApp, timings: RouteTimings) -> None:
        self._app = app
        self._timings = timings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or measuring.get():
            await self._app(scope, receive, send)
            return
        started = time.perf_counter()
        size = 0

        async def counting(message: Message) -> None:
            nonlocal size
            if message["type"] == "http.response.body":
                size += len(message.get("body", b""))
            await send(message)

        try:
            await self._app(scope, receive, counting)
        finally:
            route = _template(scope)
            if route is not None:
                ms = (time.perf_counter() - started) * 1000
                self._timings.record(f"{scope['method']} {route}", ms, size)


def _template(scope: Scope) -> str | None:
    """The matched API route's path template, such as /api/sessions/{session_id}; None
    for the web app's files and requests no route matched."""
    route = scope.get("route")
    if not isinstance(route, BaseRoute):
        return None
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path.startswith("/api/") else None
