"""Every project chat's pixies at once (B46), for clients that show them all."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.pixies.call_models import GroupEntry

router = APIRouter(prefix="/api/pixie-groups", dependencies=[RequireDevice])


@router.get("")
async def pixie_groups(ctx: Context) -> dict[str, list[GroupEntry]]:
    """Each chat's group as `GET /api/sessions/{id}/pixies` gives it, for every chat with a
    pixie or team in it; clients load it once, then follow `session.pixies` events.
    """
    return await ctx.pixie_calls.groups()
