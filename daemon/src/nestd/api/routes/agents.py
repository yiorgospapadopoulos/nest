"""The agent defaults new sessions use, from `[agents]` in settings.toml (D038)."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_agent_defaults
from nestd.config.models import AgentChoices
from nestd.errors import ConflictError

router = APIRouter(prefix="/api/agents", dependencies=[RequireDevice])


@router.get("/defaults")
async def get_defaults(ctx: Context) -> AgentChoices:
    agents = ctx.settings.agents
    return AgentChoices(
        model=agents.model,
        effort=agents.effort,
        permission_mode=agents.permission_mode,
        mode=agents.default_mode,
    )


@router.put("/defaults")
async def put_defaults(body: AgentChoices, ctx: Context) -> AgentChoices:
    """Set the defaults; 422 when the model does not take the effort or Auto mode. A null
    mode is Claude Code's own. Applies to the next new session.
    """
    await ctx.engine.require_effort(body.model, body.effort)
    await ctx.engine.require_mode(body.model, body.permission_mode)
    try:
        saved = save_agent_defaults(ctx.paths, body)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"agents": saved})
    return body
