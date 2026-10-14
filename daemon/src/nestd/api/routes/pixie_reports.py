"""What pixies reported (B42): every report shows in its pixie's chat; clients list the
unread `warn` and `action` ones in the inbox.
"""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.pixies.habit_models import PixieReport

router = APIRouter(prefix="/api/pixie-reports", dependencies=[RequireDevice])


@router.get("")
async def list_reports(ctx: Context, unread: bool = False) -> list[PixieReport]:
    """Newest first, the latest 200; `unread=true` lists only those not read yet."""
    return await ctx.reports.list_reports(unread)


@router.post("/{report_id}/read")
async def read_report(report_id: str, ctx: Context) -> PixieReport:
    """Publishes `pixie.report_read` when it was unread."""
    return await ctx.reports.mark_read(report_id)
