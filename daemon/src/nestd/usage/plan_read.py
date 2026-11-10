"""The plan's usage windows read from Claude Code without a model turn (B142).

Claude Code answers its `get_usage` control request, the data behind its `/usage` command,
by asking Claude for the account's limits with its own login: no tokens are used and no
five-hour window is started. Claude Code's own SDK still marks the request experimental, so
every field is optional: an answer that does not fit gives None and the caller falls back to
the probe's turn, and a window without a number keeps its last one (B161).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from nestd.providers.base import ScopedWindow, UsageInfo, UsageWindow, scoped_name

logger = logging.getLogger(__name__)

# `skip_behaviors` leaves out the scan of local transcripts that only `/usage`'s advice needs.
USAGE_REQUEST: dict[str, Any] = {"subtype": "get_usage", "skip_behaviors": True}
# It answers in about 0.3 s; past this the probe sends its turn instead.
READ_TIMEOUT = timedelta(seconds=15)
# The weekly windows Claude Code names by key, with the names it shows for them (B161).
_NAMED_SCOPES = {
    "seven_day_opus": "Opus",
    "seven_day_sonnet": "Sonnet",
    "seven_day_oauth_apps": "Other apps",
}


class _Window(BaseModel):
    # A percent, 0 to 100, unlike the turn's report, which is a fraction; null when the
    # server has the window but gave no number.
    utilization: float | None = None
    resets_at: datetime | None = None


class _ModelWindow(_Window):
    # Claude's own name for the model, such as "Fable".
    display_name: str


class _RateLimits(BaseModel):
    five_hour: _Window | None = None
    seven_day: _Window | None = None
    seven_day_opus: _Window | None = None
    seven_day_sonnet: _Window | None = None
    seven_day_oauth_apps: _Window | None = None
    # Read entry by entry, so one that does not fit is left out alone.
    model_scoped: list[object] | None = None


class _Answer(BaseModel):
    rate_limits_available: bool = False
    rate_limits: _RateLimits | None = None


async def read_plan_usage(client: object) -> UsageInfo | None:
    """The windows Claude Code reports for the client's account; None when it cannot say."""
    query = getattr(client, "_query", None)
    if query is None:
        return None
    try:
        async with asyncio.timeout(READ_TIMEOUT.total_seconds()):
            response: object = await query._send_control_request(USAGE_REQUEST)
    except Exception as error:
        # An engine without the request refuses it with an error, which the SDK raises.
        logger.debug("get_usage failed (%s)", type(error).__name__)
        return None
    return plan_usage(cast("dict[str, Any]", response) if isinstance(response, dict) else {})


def plan_usage(response: dict[str, Any]) -> UsageInfo | None:
    try:
        answer = _Answer.model_validate(response)
    except ValidationError:
        return None
    limits = answer.rate_limits
    if not answer.rate_limits_available or limits is None:
        return None
    named = {"five_hour": limits.five_hour, "seven_day": limits.seven_day}
    scopes = _scopes(limits)
    if all(window is None for window in named.values()) and not scopes:
        return None
    unread = {name for name, w in named.items() if w is not None and w.utilization is None}
    unread |= {scoped_name(label) for label, window in scopes.items() if window.utilization is None}
    return UsageInfo(
        five_hour=_window(limits.five_hour),
        seven_day=_window(limits.seven_day),
        scoped=[
            ScopedWindow(label=label, utilization=w.utilization / 100, resets_at=w.resets_at)
            for label, w in scopes.items()
            if w.utilization is not None
        ],
        unread=frozenset(unread),
        complete=True,
    )


def _scopes(limits: _RateLimits) -> dict[str, _Window]:
    """The per-model windows by Claude Code's name for each; the server's own list of
    models comes last and wins over the older keys for the same name.
    """
    scopes: dict[str, _Window] = {}
    for key, label in _NAMED_SCOPES.items():
        window: _Window | None = getattr(limits, key)
        if window is not None:
            scopes[label] = window
    for entry in limits.model_scoped or []:
        try:
            window = _ModelWindow.model_validate(entry)
        except ValidationError:
            continue
        label = window.display_name.strip()
        if label:
            scopes[label] = window
    return scopes


def _window(window: _Window | None) -> UsageWindow | None:
    if window is None or window.utilization is None:
        return None
    return UsageWindow(utilization=window.utilization / 100, resets_at=window.resets_at)
