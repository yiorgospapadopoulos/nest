from fastapi import APIRouter

from harness.api.deps import Context, RequireDevice
from harness.connectors.models import Connector

router = APIRouter(prefix="/api/connectors", dependencies=[RequireDevice])


@router.get("")
async def list_connectors(ctx: Context) -> list[Connector]:
    """MCP servers and claude.ai connectors with the status Claude Code last reported."""
    return await ctx.connectors.list_connectors()
