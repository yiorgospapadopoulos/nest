from typing import Annotated

from fastapi import APIRouter, Query

from harness.api.deps import Context, RequireDevice
from harness.usage.models import MonthUsage, UsageLimits

router = APIRouter(prefix="/api/usage", dependencies=[RequireDevice])


@router.get("/month")
async def month_usage(
    ctx: Context,
    year: Annotated[int, Query(ge=2000, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
) -> MonthUsage:
    """Token totals of the month and of each of its days, by the daemon's local calendar."""
    return await ctx.usage.month(year, month)


@router.get("/limits")
async def usage_limits(ctx: Context) -> UsageLimits:
    """The latest five-hour and seven-day windows the engine reported."""
    return await ctx.usage.limits()
