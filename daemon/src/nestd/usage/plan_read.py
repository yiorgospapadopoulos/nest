"""The plan's usage windows read from Claude Code without a model turn (B142).

Claude Code answers its `get_usage` control request, the data behind its `/usage` command,
by asking Claude for the account's limits with its own login: no tokens are used and no
five-hour window is started. Claude Code's own SDK still marks the request experimental, so
any answer that does not fit gives None and the caller falls back to the probe's turn.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from nestd.providers.base import UsageInfo, UsageWindow

logger = logging.getLogger(__name__)

# `skip_behaviors` leaves out the scan of local transcripts that only `/usage`'s advice needs.
USAGE_REQUEST: dict[str, Any] = {"subtype": "get_usage", "skip_behaviors": True}
# It answers in about 0.3 s; past this the probe sends its turn instead.
READ_TIMEOUT = timedelta(seconds=15)


class _Window(BaseModel):
    # A percent, 0 to 100, unlike the turn's report, which is a fraction.
    utilization: float
    resets_at: datetime | None = None


class _RateLimits(BaseModel):
    five_hour: _Window | None = None
    seven_day: _Window | None = None


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
    if limits.five_hour is None and limits.seven_day is None:
        return None
    return UsageInfo(
        five_hour=_window(limits.five_hour), seven_day=_window(limits.seven_day), complete=True
    )


def _window(window: _Window | None) -> UsageWindow | None:
    if window is None:
        return None
    return UsageWindow(utilization=window.utilization / 100, resets_at=window.resets_at)
