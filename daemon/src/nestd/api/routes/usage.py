from typing import Annotated

from fastapi import APIRouter, Query

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_usage
from nestd.config.models import UsageSettings
from nestd.errors import ConflictError
from nestd.usage.models import MonthUsage, UsageLimits

router = APIRouter(prefix="/api/usage", dependencies=[RequireDevice])


@router.get("/month")
async def month_usage(
    ctx: Context,
    year: Annotated[int, Query(ge=2000, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
) -> MonthUsage:
    """Token totals of the month and of each of its days, by the daemon's local calendar.

    Usage probes are counted apart, in `probes`, and not in the other totals.
    """
    return await ctx.usage.month(year, month)


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
