"""Claude Code in Settings (D104): the standalone install Nest finds, and installing it."""

from fastapi import APIRouter, Response, status

from nestd.api.deps import Context, RequireDevice
from nestd.claude_code.cli import ClaudeCodeStatus

router = APIRouter(prefix="/api/claude-code", dependencies=[RequireDevice])


@router.get("")
async def claude_code_status(ctx: Context) -> ClaudeCodeStatus:
    return await ctx.claude_code.status()


@router.post("/install", status_code=status.HTTP_202_ACCEPTED)
async def install_claude_code(ctx: Context) -> Response:
    """Run Anthropic's official installer; 409 when installed or installing. Progress comes
    as `claude_code.install`, the new status as `claude_code.updated`.
    """
    await ctx.claude_code.install()
    return Response(status_code=status.HTTP_202_ACCEPTED)
