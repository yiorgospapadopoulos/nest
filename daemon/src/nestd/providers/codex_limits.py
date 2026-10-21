"""Codex's usage windows as Nest's (B91): its ChatGPT plan's rate limits.

Codex reports up to two windows, in a primary and a secondary place, each with the percent
used, its length in minutes and when it resets, in `account/rateLimits/read` and, while a
thread runs, in sparse `account/rateLimits/updated` notifications. Which windows a plan has
varies (the free plan has one of 30 days, in the primary place), so each is kept by its
length and named from it, shortest first, never by its place.
"""

from datetime import UTC, datetime

from nestd.providers.base import BankedCredit, BankedResets, EngineWindow, LimitWindow, UsageInfo
from nestd.providers.codex_items import items, obj, text
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
    """Asks Codex for its windows and its banked resets' count (B98); reads the account's
    usage, never runs a model.
    """
    usage, _ = await read_limits(rpc, details=False)
    return usage


async def read_limits(rpc: CodexRpc, details: bool) -> tuple[UsageInfo | None, BankedResets | None]:
    """The windows (None without any, as `read_usage`) and the banked resets (None when
    Codex left them out), with each credit when `details`.
    """
    response = await rpc.request(
        "account/rateLimits/read", {"excludeResetCreditDetails": not details}
    )
    banked = banked_resets(response)
    usage = codex_usage(obj(response.get("rateLimits")))
    return None if usage is None else usage.model_copy(update={"banked": banked}), banked


async def consume_reset(rpc: CodexRpc, credit_id: str, idempotency_key: str) -> str:
    """Use one banked reset; Codex's outcome as it names it, such as "reset"."""
    response = await rpc.request(
        "account/rateLimitResetCredit/consume",
        {"creditId": credit_id, "idempotencyKey": idempotency_key},
    )
    return text(response.get("outcome"))


def banked_resets(response: JsonObject) -> BankedResets | None:
    """`rateLimitResetCredits`; None when Codex left it out."""
    summary = response.get("rateLimitResetCredits")
    if not isinstance(summary, dict):
        return None
    count = summary.get("availableCount")
    listed = summary.get("credits")
    kept = None
    if isinstance(listed, list):
        kept = [
            _credit(entry)
            for entry in map(obj, items(listed))
            if text(entry.get("id")) and entry.get("status") == "available"
        ]
    return BankedResets(available=count if isinstance(count, int) else 0, credits=kept)


def _credit(entry: JsonObject) -> BankedCredit:
    expires = entry.get("expiresAt")
    return BankedCredit(
        id=text(entry.get("id")),
        title=text(entry.get("title")) or None,
        description=text(entry.get("description")) or None,
        expires_at=datetime.fromtimestamp(expires, UTC) if isinstance(expires, int) else None,
    )
