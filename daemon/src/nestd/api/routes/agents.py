"""The agent defaults new sessions use, from `[agents]` in settings.toml (D038, B94)."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.config.errors import ConfigError
from nestd.config.loader import save_agent_defaults
from nestd.config.models import AgentChoices
from nestd.engine.service import effort_problem, mode_problem
from nestd.errors import ConflictError, InvalidInputError

router = APIRouter(prefix="/api/agents", dependencies=[RequireDevice])


@router.get("/defaults")
async def get_defaults(ctx: Context) -> AgentChoices:
    """Concrete: what older settings left to the engines is resolved and stored first."""
    return await ctx.settle_defaults()


@router.put("/defaults")
async def put_defaults(body: AgentChoices, ctx: Context) -> AgentChoices:
    """Set the defaults; nulls are the values Nest picks (the first engine signed in, its
    default model, Medium or the closest level, Ask). 422 for an unknown engine, or when
    the model does not take the effort or Auto mode. Applies to the next new session.
    """
    engines = ctx.sessions.engines
    if body.provider is not None:
        engines.named(body.provider)
    elif body.model is not None:
        # An older client names a model only: its engine, the stored one first.
        stored = await ctx.chat_defaults.engine_of(ctx.settings.agents)
        body = body.model_copy(
            update={"provider": (await engines.listing(body.model, stored)).name}
        )
    elif ctx.settings.agents.provider is not None:
        body = body.model_copy(update={"provider": ctx.settings.agents.provider})
    resolved = await ctx.chat_defaults.resolve(body)
    choices = resolved.choices
    engine = ctx.sessions.engines.by_name(str(choices.provider))
    option = None if choices.model is None else await engine.find(choices.model)
    if option is not None:
        # The values sent, not the ones Nest picked for nulls, which always fit.
        problem = effort_problem(option, body.effort) or mode_problem(option, body.permission_mode)
        if problem is not None:
            raise InvalidInputError(problem)
    try:
        saved = save_agent_defaults(ctx.paths, choices)
    except ConfigError as error:
        raise ConflictError(str(error)) from error
    ctx.settings = ctx.settings.model_copy(update={"agents": saved})
    return choices
