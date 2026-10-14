from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.connectors.models import Connector

router = APIRouter(prefix="/api/connectors", dependencies=[RequireDevice])


@router.get("")
async def list_connectors(ctx: Context) -> list[Connector]:
    """MCP servers and claude.ai connectors with the status Claude Code last reported."""
    return await ctx.connectors.list_connectors()
