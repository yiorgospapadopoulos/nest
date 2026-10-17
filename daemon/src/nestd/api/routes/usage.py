import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_usage
from nestd.config.models import UsageSettings
from nestd.errors import ConflictError
from nestd.usage.models import PeriodUnit, PeriodUsage, UsageLimits

router = APIRouter(prefix="/api/usage", dependencies=[RequireDevice])

EARLIEST = datetime.date(2000, 1, 1)
LATEST = datetime.date(2100, 12, 31)


@router.get("/period")
async def period_usage(
    ctx: Context,
    unit: PeriodUnit,
    date: Annotated[datetime.date, Query(), Field(ge=EARLIEST, le=LATEST)],
) -> PeriodUsage:
    """Tokens of chats and subagents in the day, week (from Monday), month or year holding
    `date`, by the daemon's local calendar, with a bar per hour, day or month.

    Usage probes are counted apart, in `probes`, and not in the other totals.
    """
    return await ctx.usage.period(unit, date)


@router.get("/limits")
async def usage_limits(ctx: Context) -> UsageLimits:
    """The latest five-hour and seven-day windows the engine reported."""
    return await ctx.usage.limits()


@router.post("/refresh")
async def refresh_limits(ctx: Context) -> UsageLimits:
    """Probe Claude for the windows now: 429 within 20 s of the last probe, 502 on failure."""
    return await ctx.usage_refresher.refresh()


@router.get("/settings")
async def get_settings(ctx: Context) -> UsageSettings:
    return ctx.settings.usage


@router.put("/settings")
async def put_settings(body: UsageSettings, ctx: Context) -> UsageSettings:
    """Replace the `[usage]` section of settings.toml; applies at once."""
    try:
        saved = save_usage(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"usage": saved})
    return saved
