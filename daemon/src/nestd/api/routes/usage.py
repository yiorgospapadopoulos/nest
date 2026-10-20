import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_usage
from nestd.config.models import UsageSettings
from nestd.errors import ConflictError
from nestd.usage.models import (
    CLAUDE,
    EngineLimits,
    PeriodUnit,
    PeriodUsage,
    UsageLimits,
    UsageProvider,
)

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
    `date`, by the daemon's local calendar, with a bar per hour, day or month. Every engine
    counts in the totals; `engines` splits them (B91).

    Usage probes are counted apart, in `probes`, and not in the other totals.
    """
    return await ctx.usage.period(unit, date)


@router.get("/limits")
async def usage_limits(
    ctx: Context, provider: UsageProvider = CLAUDE
) -> UsageLimits | EngineLimits:
    """The latest windows the engine reported: Claude's five-hour and seven-day ones, or
    with `provider=codex` Codex's by length, each with its label (B91).
    """
    if provider == CLAUDE:
        return await ctx.usage.limits()
    return await ctx.usage.engine_limits(provider)


@router.post("/refresh")
async def refresh_limits(
    ctx: Context, provider: UsageProvider = CLAUDE
) -> UsageLimits | EngineLimits:
    """Ask the engine for its windows now (Claude with a probe, Codex without a model call):
    429 within 20 s of the engine's last ask, 502 on failure.
    """
    if provider == CLAUDE:
        return await ctx.usage_refresher.refresh()
    return await ctx.usage_refresher.refresh_engine(provider)


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
