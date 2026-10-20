"""Codex's usage windows as Nest's (B91): its ChatGPT plan's rate limits.

Codex reports up to two windows, in a primary and a secondary place, each with the percent
used, its length in minutes and when it resets, in `account/rateLimits/read` and, while a
thread runs, in sparse `account/rateLimits/updated` notifications. Which windows a plan has
varies (the free plan has one of 30 days, in the primary place), so each is kept by its
length and named from it, shortest first, never by its place.
"""

from datetime import UTC, datetime

from nestd.providers.base import EngineWindow, LimitWindow, UsageInfo
from nestd.providers.codex_items import obj
from nestd.providers.codex_rpc import CodexRpc, JsonObject

CODEX = "codex"
# The windows a limit hit can name as Nest names Claude's (B78), by length in minutes.
WINDOWS: dict[int, LimitWindow] = {300: "five_hour", 10080: "seven_day"}
_PLACES = ("primary", "secondary")


def codex_usage(snapshot: JsonObject) -> UsageInfo | None:
    """The snapshot's windows; None when it has none."""
    windows: dict[int | None, EngineWindow] = {}
    for place in _PLACES:
        window = obj(snapshot.get(place))
        used = window.get("usedPercent")
        if not isinstance(used, int | float):
            continue
        length = window.get("windowDurationMins")
        minutes = length if isinstance(length, int) else None
        resets = window.get("resetsAt")
        windows.setdefault(
            minutes,
            EngineWindow(
                utilization=max(0.0, used / 100),
                resets_at=datetime.fromtimestamp(resets, UTC) if isinstance(resets, int) else None,
                minutes=minutes,
            ),
        )
    if not windows:
        return None
    return UsageInfo(
        five_hour=None,
        seven_day=None,
        provider=CODEX,
        windows=sorted(windows.values(), key=_shortest_first),
    )


def _shortest_first(window: EngineWindow) -> tuple[bool, int]:
    return (window.minutes is None, window.minutes or 0)


async def read_usage(rpc: CodexRpc) -> UsageInfo | None:
    """Asks Codex for its windows; reads the account's usage, never runs a model."""
    response = await rpc.request("account/rateLimits/read", {"excludeResetCreditDetails": True})
    return codex_usage(obj(response.get("rateLimits")))
