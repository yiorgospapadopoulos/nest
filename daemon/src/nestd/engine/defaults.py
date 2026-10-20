"""The concrete choices new chats start from when none is made (B94).

Nest never leaves a model, thinking level or permission mode to the engine: with nothing
chosen, a chat runs the default model of the engine the user signed in to first (the
model that engine marks as its default, by name), Medium thinking or the closest level the
model takes, and Ask. Defaults stored before B94 that deferred to the engine (nulls) are
resolved to these once the engine's model list is known, and then stored.
"""

from collections.abc import Callable
from dataclasses import dataclass

from nestd.config.models import AgentChoices, AgentDefaults, Effort, PermissionMode
from nestd.engine.models import closest_effort
from nestd.engine.service import mode_problem
from nestd.engine.sign_ins import SignInStore
from nestd.providers.base import ModelOption
from nestd.sessions.engines import Engine, Engines

ASK: PermissionMode = "default"


@dataclass(frozen=True)
class Resolved:
    choices: AgentChoices
    # Every choice is concrete: the model is known to its engine's list.
    complete: bool


def default_effort(option: ModelOption | None) -> Effort | None:
    """Medium or the closest level the model takes; None for a model without levels or
    one whose levels are not known.
    """
    return None if option is None else closest_effort(option.effort_levels)


def default_mode(option: ModelOption | None, mode: PermissionMode | None) -> PermissionMode:
    """`mode`, or Ask when none is set or the model does not run in it."""
    if mode is None or (option is not None and mode_problem(option, mode) is not None):
        return ASK
    return mode


class ChatDefaults:
    def __init__(self, engines: Callable[[], Engines], sign_ins: SignInStore) -> None:
        """`engines` are the session manager's, read when needed."""
        self._engines = engines
        self._sign_ins = sign_ins

    async def first_engine(self) -> Engine:
        """The engine Nest saw signed in first; the default one before any was."""
        engines = self._engines()
        first = await self._sign_ins.first()
        return engines.default if first is None else engines.by_name(first)

    async def engine_of(self, agents: AgentDefaults | AgentChoices) -> Engine:
        """The defaults' engine: the stored one; for a model stored before B94 (always
        Claude's) the default engine; with neither, the first signed in.
        """
        engines = self._engines()
        if agents.provider is not None:
            return engines.by_name(agents.provider)
        if agents.model is not None:
            return engines.default
        return await self.first_engine()

    async def resolve(self, agents: AgentDefaults | AgentChoices) -> Resolved:
        """The defaults with every null replaced by the value Nest picks."""
        engine = await self.engine_of(agents)
        model = agents.model or await engine.default_model()
        option = None if model is None else await engine.find(model)
        effort = agents.effort if agents.effort is not None else default_effort(option)
        mode = agents.mode if isinstance(agents, AgentChoices) else agents.default_mode
        choices = AgentChoices(
            provider=engine.name,
            model=model,
            effort=effort,
            permission_mode=default_mode(option, agents.permission_mode),
            mode=mode,
        )
        return Resolved(choices, complete=option is not None)
